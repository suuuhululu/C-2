// SIM-only adapter: actual feedback -> MoveIt/OMPL -> validated timed trajectory -> JTC.
#include <moveit/move_group_interface/move_group_interface.hpp>
#include <moveit/planning_scene_interface/planning_scene_interface.hpp>
#include <moveit/robot_model_loader/robot_model_loader.hpp>
#include <moveit/planning_scene/planning_scene.hpp>
#include <moveit/robot_trajectory/robot_trajectory.hpp>
#include <moveit/trajectory_processing/time_optimal_trajectory_generation.hpp>
#include <moveit_msgs/srv/get_planning_scene.hpp>
#include <moveit_msgs/msg/attached_collision_object.hpp>
#include <moveit_msgs/msg/orientation_constraint.hpp>
#include <control_msgs/action/follow_joint_trajectory.hpp>
#include <std_msgs/msg/string.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <yaml-cpp/yaml.h>
#include <fstream>
#include <sstream>
#include <thread>
#include <mutex>
#include <chrono>

using namespace std::chrono_literals;
namespace mgi=moveit::planning_interface;
std::string read(const std::string& path){std::ifstream s(path);if(!s)throw std::runtime_error("Cannot read "+path);std::ostringstream o;o<<s.rdbuf();return o.str();}
geometry_msgs::msg::Pose pose(const YAML::Node& value){geometry_msgs::msg::Pose p;p.position.x=value["xyz_m"][0].as<double>();p.position.y=value["xyz_m"][1].as<double>();p.position.z=value["xyz_m"][2].as<double>();p.orientation.x=value["quaternion_xyzw"][0].as<double>();p.orientation.y=value["quaternion_xyzw"][1].as<double>();p.orientation.z=value["quaternion_xyzw"][2].as<double>();p.orientation.w=value["quaternion_xyzw"][3].as<double>();return p;}
Eigen::Isometry3d transform(const geometry_msgs::msg::Pose& p){Eigen::Isometry3d t=Eigen::Isometry3d::Identity();t.translation()<<p.position.x,p.position.y,p.position.z;t.linear()=Eigen::Quaterniond(p.orientation.w,p.orientation.x,p.orientation.y,p.orientation.z).normalized().toRotationMatrix();return t;}
geometry_msgs::msg::Pose pose(const Eigen::Isometry3d& t){geometry_msgs::msg::Pose p;p.position.x=t.translation().x();p.position.y=t.translation().y();p.position.z=t.translation().z();Eigen::Quaterniond q(t.rotation());p.orientation.x=q.x();p.orientation.y=q.y();p.orientation.z=q.z();p.orientation.w=q.w();return p;}
YAML::Node matrix(const Eigen::Isometry3d& t){YAML::Node n;for(int i=0;i<4;++i)for(int j=0;j<4;++j)n[i].push_back(t.matrix()(i,j));return n;}
Eigen::Isometry3d matrix(const YAML::Node& n){Eigen::Isometry3d t=Eigen::Isometry3d::Identity();for(int i=0;i<4;++i)for(int j=0;j<4;++j)t.matrix()(i,j)=n[i][j].as<double>();return t;}
struct Active{std::string path;Active(std::string p,const std::string& data):path(p){std::ofstream f(path+".tmp");f<<data;f.close();std::rename((path+".tmp").c_str(),path.c_str());}~Active(){std::remove(path.c_str());}};
struct Spin{rclcpp::executors::MultiThreadedExecutor exec;std::thread thread;Spin(const rclcpp::Node::SharedPtr& node){exec.add_node(node);thread=std::thread([this]{exec.spin();});}~Spin(){exec.cancel();if(thread.joinable())thread.join();}};

moveit_msgs::msg::CollisionObject object(const YAML::Node& data,const Eigen::Isometry3d& frame,const std::string& frame_id)
{
 moveit_msgs::msg::CollisionObject obj;obj.id=data["id"].as<std::string>();obj.header.frame_id=frame_id;obj.operation=obj.ADD;
 auto add=[&](std::vector<double> size,const Eigen::Isometry3d& t){shape_msgs::msg::SolidPrimitive p;p.type=p.BOX;for(double v:size)p.dimensions.push_back(v);obj.primitives.push_back(p);obj.primitive_poses.push_back(pose(t));};
 auto size=data["size_m"].as<std::vector<double>>();add(size,frame);
 if(data["studs"].as<bool>()){
  int nx=std::lround(size[0]/.016),ny=std::lround(size[1]/.016);
  for(int x=0;x<nx;++x)for(int y=0;y<ny;++y){auto t=Eigen::Isometry3d::Identity();t.translation()<< (x-(nx-1)/2.0)*.016,(y-(ny-1)/2.0)*.016,.01175;add({.01,.01,.0045},frame*t);}
 }return obj;
}


// Each row has its own emitter: avoid merging thousands of YAML node graphs.
void record_checked_state(std::ostream& stream,const moveit::core::RobotState& state,const moveit::core::JointModelGroup* jmg) {
 YAML::Emitter row;row.SetDoublePrecision(17);row<<YAML::Flow<<YAML::BeginMap<<YAML::Key<<"q_rad"<<YAML::Value<<YAML::BeginSeq;
 for(const auto& name:jmg->getVariableNames())row<<state.getVariablePosition(name);
 row<<YAML::EndSeq<<YAML::Key<<"tcp_matrix"<<YAML::Value<<YAML::BeginSeq;const auto& t=state.getGlobalLinkTransform("GripperDA_v4_tcp");
 for(int i=0;i<4;++i){row<<YAML::BeginSeq;for(int j=0;j<4;++j)row<<t.matrix()(i,j);row<<YAML::EndSeq;}
 row<<YAML::EndSeq<<YAML::EndMap;stream<<"  - "<<row.c_str()<<'\n';
}

int main(int argc,char** argv) {
 if(argc<5) return 2;const bool fast=argc>5&&std::string(argv[5])=="fast";const bool streamed=fast||(argc>5&&std::string(argv[5])=="stream");std::ostringstream records;
 const std::string root=argv[1];const auto recorded=YAML::LoadFile(argv[2]);const auto req=YAML::LoadFile(argv[3]);
 rclcpp::init(argc,argv);auto node=std::make_shared<rclcpp::Node>("offline_collision_benchmark");
 node->declare_parameter("robot_description",read(root+"/config/robot.urdf"));
 node->declare_parameter("robot_description_semantic",read(root+"/ros_ws/src/m0609_rg2_sim_model/config/m0609_rg2_sim.srdf"));
 robot_model_loader::RobotModelLoader loader(node,"robot_description",false);auto model=loader.getModel();
 planning_scene::PlanningScene scene(model);const auto slot=recorded["selected_slot"].as<std::string>();
 auto& acm=scene.getAllowedCollisionMatrixNonConst();const bool contact=req["contact_phase"].as<bool>();
 acm.setEntry(slot,"rg2_left_inner_finger",contact);acm.setEntry(slot,"rg2_right_inner_finger",contact);acm.setEntry(slot,"SupplySurface",req["phase"].as<std::string>()=="LIFT");
 YAML::Node selected;
 for(const auto& obj:recorded["actual_start"]["world_objects"]) {
  if(obj["id"].as<std::string>()==slot)selected=YAML::Clone(obj);
  if(req["held"].as<bool>()&&obj["id"].as<std::string>()==slot)continue;
  scene.processCollisionObjectMsg(object(obj,transform(pose(obj["pose"])),"base_link"));
 }
 if(req["held"].as<bool>()) {moveit_msgs::msg::AttachedCollisionObject a;a.link_name="GripperDA_v4_tcp";a.object=object(selected,matrix(req["attachment"]),a.link_name);a.touch_links={"rg2_left_inner_finger","rg2_right_inner_finger"};scene.processAttachedCollisionObjectMsg(a);}
 auto state=scene.getCurrentState();state.setVariablePosition("rg2_finger_joint",recorded["actual_start"]["grip_rad"].as<double>());
 const auto now=[] {return std::chrono::steady_clock::now();};const auto seconds=[](auto begin) {return std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();};
 double collision_s=0,record_s=0,minimum=1e9;YAML::Node output,states;int count=0,hits=0;
 for(const auto& row:recorded["checked_states"]) {
  for(int j=0;j<6;++j)state.setVariablePosition("joint_"+std::to_string(j+1),row["q_rad"][j].as<double>());state.update();
  auto begin=now();collision_detection::CollisionRequest cr;cr.contacts=true;cr.max_contacts=10;cr.distance=!fast||(count%100==0)||(count+1==int(recorded["checked_states"].size()));collision_detection::CollisionResult result;scene.checkCollision(cr,result,state);collision_s+=seconds(begin);hits+=result.collision;if(cr.distance)minimum=std::min(minimum,result.distance);
  begin=now();if(streamed)record_checked_state(records,state,model->getJointModelGroup("manipulator"));else {YAML::Node item;item["q_rad"]=std::vector<double>();for(int j=0;j<6;++j)item["q_rad"].push_back(state.getVariablePosition("joint_"+std::to_string(j+1)));item["tcp_matrix"]=matrix(state.getGlobalLinkTransform("GripperDA_v4_tcp"));states.push_back(item);}record_s+=seconds(begin);++count;
 }
 auto begin=now();std::ostringstream stream;if(streamed)stream<<records.str();else stream<<states;double serialize_s=seconds(begin);
 output["mode"]="offline_same_recorded_states_no_execution";output["streamed_records"]=streamed;output["distance_sampled"]=fast;output["states"]=count;output["collision_hits"]=hits;output["collision_distance_wall_s"]=collision_s;output["yaml_node_record_wall_s"]=record_s;output["yaml_serialize_wall_s"]=serialize_s;output["minimum_distance_m"]=minimum;std::ofstream report(argv[4]);report<<output<<'\n';std::cout<<output<<'\n';rclcpp::shutdown();return hits?1:0;
}
