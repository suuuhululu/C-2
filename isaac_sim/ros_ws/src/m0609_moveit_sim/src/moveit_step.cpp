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
#include <set>

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

int main(int argc,char** argv)
{
 if(argc<5){std::cerr<<"moveit_step ROOT RUN_DIR REQUEST_YAML RESULT_YAML\n";return 2;}
 std::string root=argv[1],run=argv[2];std::ostringstream checked_stream;YAML::Node output;output["scope"]="SIM_ONLY";output["plan_success"]=false;output["execution_success"]=false;
 auto write=[&]{std::string target=argv[4];std::ofstream stream(target+".tmp");stream<<output<<'\n';if(!checked_stream.str().empty())stream<<"checked_states:\n"<<checked_stream.str();stream.close();std::rename((target+".tmp").c_str(),target.c_str());};
 try{
  YAML::Node req=YAML::LoadFile(argv[3]);std::string phase=req["phase"].as<std::string>();output["phase"]=phase;
  if(!req["sim_execution_authorized"].as<bool>()||req["a_execution_allowed"].as<bool>())throw std::runtime_error("SIM scope gate rejected");
  rclcpp::init(argc,argv);rclcpp::NodeOptions options;options.automatically_declare_parameters_from_overrides(true);
  options.arguments({"--ros-args","-r","/joint_states:=/sim/m0609/joint_states"});
  std::vector<rclcpp::Parameter> parameters={rclcpp::Parameter("use_sim_time",true),rclcpp::Parameter("robot_description",read(root+"/config/robot.urdf")),rclcpp::Parameter("robot_description_semantic",read(root+"/ros_ws/src/m0609_rg2_sim_model/config/m0609_rg2_sim.srdf")),rclcpp::Parameter("robot_description_kinematics.manipulator.kinematics_solver","kdl_kinematics_plugin/KDLKinematicsPlugin"),rclcpp::Parameter("robot_description_kinematics.manipulator.kinematics_solver_timeout",.1)};
  auto limits=YAML::LoadFile(root+"/config/joint_limits.sim.yaml")["joint_limits"];
  for(const auto& joint:limits)for(const auto& entry:joint.second){
   std::string name="robot_description_planning.joint_limits."+joint.first.as<std::string>()+"."+entry.first.as<std::string>();
   if(entry.first.as<std::string>().find("has_")==0)parameters.emplace_back(name,entry.second.as<bool>());else parameters.emplace_back(name,entry.second.as<double>());
  }options.parameter_overrides(parameters);
  auto node=std::make_shared<rclcpp::Node>("sim_moveit_step",options);std::mutex mutex;YAML::Node live;
  auto sub=node->create_subscription<std_msgs::msg::String>("/sim/review_state",10,[&](const std_msgs::msg::String::SharedPtr msg){std::lock_guard<std::mutex> lock(mutex);live=YAML::Load(msg->data);});
  Spin spin(node);
  auto actual=[&]{std::lock_guard<std::mutex> lock(mutex);return YAML::Clone(live);};
  auto deadline=std::chrono::steady_clock::now()+20s;
  while(!actual()["q_rad"]&&std::chrono::steady_clock::now()<deadline)std::this_thread::sleep_for(20ms);
  YAML::Node state_data=actual();if(!state_data["q_rad"])throw std::runtime_error("No actual Isaac feedback");
  while(node->now().nanoseconds()==0&&std::chrono::steady_clock::now()<deadline)std::this_thread::sleep_for(20ms);
  if(node->now().nanoseconds()==0)throw std::runtime_error("No Isaac simulation clock");
  output["actual_start"]=state_data;
  auto check_contract=[&]{if(std::ifstream(run+"/runtime_guard_failure.json").good())throw std::runtime_error("RUNTIME_GUARD_LATCHED: no new execution");auto ctx=YAML::LoadFile(run+"/scene_context.json");if(ctx["current_revision"].as<int>()!=req["current_revision"].as<int>()||ctx["world_revision"].as<int>()!=req["world_revision"].as<int>()||ctx["profile_version"].as<std::string>()!=req["profile_version"].as<std::string>()||ctx["reservation_id"].as<std::string>()!=req["reservation_id"].as<std::string>())throw std::runtime_error("STALE_CONTEXT: Current/world/profile/reservation changed; re-evaluate before execution");};
  check_contract();
  if(req["kind"].as<std::string>()=="GRIP"){
   using Action=control_msgs::action::FollowJointTrajectory;auto client=rclcpp_action::create_client<Action>(node,"/sim/m0609/gripper_controller/follow_joint_trajectory");
   if(!client->wait_for_action_server(15s))throw std::runtime_error("Gripper action unavailable");
   Action::Goal goal;goal.trajectory.joint_names={"rg2_finger_joint"};trajectory_msgs::msg::JointTrajectoryPoint p;p.positions={req["grip_rad"].as<double>()};p.velocities={0};p.time_from_start.sec=3;goal.trajectory.points.push_back(p);
   check_contract();Active active(run+"/execution.active.json",read(run+"/scene_context.json"));output["execution_issued"]=true;auto sent=client->async_send_goal(goal);if(sent.wait_for(15s)!=std::future_status::ready)throw std::runtime_error("Gripper goal timeout");auto handle=sent.get();if(!handle)throw std::runtime_error("Gripper goal rejected");
   auto result=client->async_get_result(handle);if(result.wait_for(60s)!=std::future_status::ready){client->async_cancel_goal(handle);throw std::runtime_error("Gripper completion timeout");}
   auto done=result.get();output["execution_success"]=done.code==rclcpp_action::ResultCode::SUCCEEDED;output["gripper_action_error_code"]=done.result->error_code;output["actual_final"]=actual();if(!output["execution_success"].as<bool>())throw std::runtime_error("Gripper JTC failed: "+std::to_string(done.result->error_code)+" "+done.result->error_string);write();rclcpp::shutdown();return 0;
  }
  mgi::MoveGroupInterface group(node,"manipulator");group.setPoseReferenceFrame("base_link");group.setEndEffectorLink("GripperDA_v4_tcp");group.setPlanningPipelineId("ompl");group.setPlannerId("RRTConnect");group.setWorkspace(-1,-1,-.05,1,1,1.2);group.setPlanningTime(15);group.setNumPlanningAttempts(4);group.setGoalPositionTolerance(.0008);group.setGoalOrientationTolerance(.005);group.setMaxVelocityScalingFactor(1);group.setMaxAccelerationScalingFactor(1);
  if(!group.startStateMonitor(15))throw std::runtime_error("Actual joint state monitor incomplete");
  auto current=group.getCurrentState(15);if(!current)throw std::runtime_error("MoveIt did not receive measured joint states");
  state_data=actual();double feedback_error=0;for(int i=0;i<6;++i)feedback_error=std::max(feedback_error,std::abs(current->getVariablePosition("joint_"+std::to_string(i+1))-state_data["q_rad"][i].as<double>()));
  output["moveit_feedback_max_joint_error_rad"]=feedback_error;if(feedback_error>.03)throw std::runtime_error("MoveIt actual joint feedback mismatch");
  mgi::PlanningSceneInterface psi;
  auto scene_client=node->create_client<moveit_msgs::srv::GetPlanningScene>("/get_planning_scene");
  if(!scene_client->wait_for_service(20s))throw std::runtime_error("PlanningScene unavailable");
  auto snapshot=[&]{auto request=std::make_shared<moveit_msgs::srv::GetPlanningScene::Request>();request->components.components=1023;auto future=scene_client->async_send_request(request);if(future.wait_for(15s)!=std::future_status::ready)throw std::runtime_error("GetPlanningScene timeout");return future.get()->scene;};
  auto before=snapshot();
  // Empty-gripper/mock boundary: detach first, then synchronize all live objects.
  if(!req["held"].as<bool>()&&!before.robot_state.attached_collision_objects.empty()){
   moveit_msgs::msg::PlanningScene detach;detach.is_diff=true;detach.robot_state.is_diff=true;
   for(const auto& attached:before.robot_state.attached_collision_objects){auto a=attached;a.object.operation=a.object.REMOVE;detach.robot_state.attached_collision_objects.push_back(a);}
   if(!psi.applyPlanningScene(detach))throw std::runtime_error("Attached removal rejected");before=snapshot();
  }
  collision_detection::AllowedCollisionMatrix acm(before.allowed_collision_matrix);
  for(const auto& body:before.world.collision_objects){acm.setEntry(body.id,"rg2_left_inner_finger",false);acm.setEntry(body.id,"rg2_right_inner_finger",false);}
  if(req["allow_touch_world_id"]){auto id=req["allow_touch_world_id"].as<std::string>();acm.setEntry(id,"rg2_left_inner_finger",true);acm.setEntry(id,"rg2_right_inner_finger",true);}
  std::string slot=state_data["selected_slot_id"].as<std::string>();bool held=req["held"].as<bool>();bool contact=req["contact_phase"].as<bool>();
  acm.setEntry(slot,"rg2_left_inner_finger",contact);acm.setEntry(slot,"rg2_right_inner_finger",contact);acm.setEntry(slot,"SupplySurface",phase=="LIFT");
  moveit_msgs::msg::PlanningScene update;update.is_diff=true;update.robot_state.is_diff=true;acm.getMessage(update.allowed_collision_matrix);
  std::set<std::string> live_ids;for(const auto& obj:state_data["world_objects"])live_ids.insert(obj["id"].as<std::string>());
  for(const auto& previous:before.world.collision_objects){if(!live_ids.count(previous.id)){moveit_msgs::msg::CollisionObject remove;remove.id=previous.id;remove.header.frame_id="base_link";remove.operation=remove.REMOVE;update.world.collision_objects.push_back(remove);}}
  YAML::Node selected;
  for(const auto& obj:state_data["world_objects"]){
   std::string id=obj["id"].as<std::string>();if(id==slot)selected=YAML::Clone(obj);
   if(held&&id==slot){continue;} // Attached ADD consumes the world object; do not also REMOVE it.
   else update.world.collision_objects.push_back(object(obj,transform(pose(obj["pose"])),"base_link"));
  }
  if(held){moveit_msgs::msg::AttachedCollisionObject a;a.link_name="GripperDA_v4_tcp";a.object=object(selected,matrix(req["attachment"]),a.link_name);a.touch_links={"rg2_left_inner_finger","rg2_right_inner_finger"};update.robot_state.attached_collision_objects.push_back(a);}
  if(!psi.applyPlanningScene(update))throw std::runtime_error("PlanningScene update rejected");
  auto scene_msg=snapshot();robot_model_loader::RobotModelLoader loader(node,"robot_description",true);auto model=loader.getModel();auto scene=std::make_shared<planning_scene::PlanningScene>(model);scene->setPlanningSceneMsg(scene_msg);
  output["world_object_count"]=scene_msg.world.collision_objects.size();output["attached_object_count"]=scene_msg.robot_state.attached_collision_objects.size();output["scene_current_revision"]=req["current_revision"];output["selected_slot"]=slot;
  for(const auto& obj:scene_msg.world.collision_objects)output["world_object_ids"].push_back(obj.id);
  for(const auto& a:scene_msg.robot_state.attached_collision_objects){output["attached_ids"].push_back(a.object.id);output["touch_links"]=a.touch_links;}
  if(req["kind"].as<std::string>()=="SYNC"){
   output["scene_sync_success"]=true;output["execution_issued"]=false;output["actual_final"]=actual();write();rclcpp::shutdown();return 0;
  }
  auto& start=scene->getCurrentStateNonConst();state_data=actual();
  for(int i=0;i<6;++i)start.setVariablePosition("joint_"+std::to_string(i+1),state_data["q_rad"][i].as<double>());
  start.setVariablePosition("rg2_finger_joint",state_data["grip_rad"].as<double>());start.update();group.setStartState(start);
  if(req["kind"].as<std::string>()=="NEGATIVE_HELD"){
   if(!held)throw std::runtime_error("Negative held test requires attached block");
   const auto world_block=start.getGlobalLinkTransform("GripperDA_v4_tcp")*matrix(req["attachment"]);
   for(double x:{-.008,.008})for(double y:{-.008,.008})for(double z:{.014,-.009}){
    auto t=world_block; t.translation()=world_block*Eigen::Vector3d(x,y,z);
    moveit_msgs::msg::CollisionObject fixture;fixture.id="SIM_NEGATIVE_HELD_ONLY";fixture.header.frame_id="base_link";fixture.operation=fixture.ADD;
    shape_msgs::msg::SolidPrimitive box;box.type=box.BOX;for(int i=0;i<3;++i)box.dimensions.push_back(.003);fixture.primitives.push_back(box);fixture.primitive_poses.push_back(pose(t));scene->processCollisionObjectMsg(fixture);
    moveit::core::RobotState without(start);without.clearAttachedBody(slot);without.update();collision_detection::CollisionRequest cr;collision_detection::CollisionResult with_result,without_result;
    scene->checkCollision(cr,with_result,start);scene->checkCollision(cr,without_result,without);
    if(with_result.collision&&!without_result.collision){output["held_only_negative_control_pass"]=true;output["without_held_block_collision"]=false;output["with_held_block_collision"]=true;output["execution_issued"]=false;throw std::runtime_error("NEGATIVE_HELD_COLLISION_REJECTED: no execution issued");}
   }throw std::runtime_error("No held-only negative fixture found");
  }
  collision_detection::CollisionRequest start_request;start_request.contacts=true;start_request.max_contacts=10;collision_detection::CollisionResult start_result;scene->checkCollision(start_request,start_result,start);
  if(start_result.collision){for(const auto& pair:start_result.contacts)output["collision_pairs"].push_back(pair.first.first+" / "+pair.first.second);throw std::runtime_error("Actual start state collision: no planning or execution issued");}
  moveit_msgs::msg::Constraints constraints;
  if(held&&phase=="TRANSPORT"){
   moveit_msgs::msg::OrientationConstraint c;c.header.frame_id="base_link";c.link_name="GripperDA_v4_tcp";c.orientation=pose(req["holding_orientation"]).orientation;c.absolute_x_axis_tolerance=.25;c.absolute_y_axis_tolerance=.25;c.absolute_z_axis_tolerance=req["allow_yaw_reorientation"]&&req["allow_yaw_reorientation"].as<bool>()?M_PI:.6;c.weight=1;c.parameterization=c.ROTATION_VECTOR;constraints.orientation_constraints.push_back(c);group.setPathConstraints(constraints);
  }
  const auto planning_begin=std::chrono::steady_clock::now();
  mgi::MoveGroupInterface::Plan plan;
  if(req["kind"].as<std::string>()=="PROBE"){
   auto q=state_data["q_rad"].as<std::vector<double>>();q[0]+=req["probe_delta_rad"]?req["probe_delta_rad"].as<double>():.05;group.setJointValueTarget(q);
   auto code=group.plan(plan);output["planning_error_code"]=code.val;if(code!=moveit::core::MoveItErrorCode::SUCCESS)throw std::runtime_error("MoveIt PROBE planning failed");
  }else if(req["cartesian"].as<bool>()){
   moveit_msgs::msg::MoveItErrorCodes error;double fraction=group.computeCartesianPath({pose(req["goal"])},.001,plan.trajectory,true,&error);
   output["cartesian_fraction"]=fraction;output["planning_error_code"]=error.val;if(fraction<.999999)throw std::runtime_error("Cartesian approach incomplete; do not execute partial path");
  }else{
   const auto* joints=model->getJointModelGroup("manipulator");moveit::core::RobotState best(start);double score=std::numeric_limits<double>::infinity();
   auto nearest=[&](moveit::core::RobotState& candidate){for(const auto& name:joints->getVariableNames()){double q=candidate.getVariablePosition(name),reference=start.getVariablePosition(name);const auto& bounds=model->getVariableBounds(name);while(q-reference>M_PI&&q-2*M_PI>=bounds.min_position_)q-=2*M_PI;while(q-reference<-M_PI&&q+2*M_PI<=bounds.max_position_)q+=2*M_PI;candidate.setVariablePosition(name,q);}candidate.update();};
   auto valid=[&](moveit::core::RobotState* candidate,const moveit::core::JointModelGroup* group,const double* values){candidate->setJointGroupPositions(group,values);nearest(*candidate);return candidate->satisfiesBounds()&&!scene->isStateColliding(*candidate);};
   for(int attempt=0;attempt<24;++attempt){moveit::core::RobotState candidate(start);if(attempt)candidate.setToRandomPositions(joints);if(candidate.setFromIK(joints,transform(pose(req["goal"])),"GripperDA_v4_tcp",.05,valid)){nearest(candidate);if(scene->isStateColliding(candidate))continue;double cost=0;for(const auto& name:joints->getVariableNames())cost+=std::pow(candidate.getVariablePosition(name)-start.getVariablePosition(name),2);if(cost<score){score=cost;best=candidate;}}}
   if(!std::isfinite(score))throw std::runtime_error("No collision-free MoveIt IK goal; A endpoint preserved; no HUMAN rerouting");
   std::vector<double> goal_q;best.copyJointGroupPositions(joints,goal_q);output["selected_moveit_ik_q_rad"]=goal_q;output["selected_ik_joint_distance_rad"]=std::sqrt(score);output["selected_ik_tcp_matrix"]=matrix(best.getGlobalLinkTransform("GripperDA_v4_tcp"));group.setJointValueTarget(goal_q);
   moveit::core::MoveItErrorCode code;for(int attempt=0;attempt<3;++attempt){code=group.plan(plan);output["planning_attempt_error_codes"].push_back(code.val);if(code==moveit::core::MoveItErrorCode::SUCCESS)break;}
   output["planning_error_code"]=code.val;if(code!=moveit::core::MoveItErrorCode::SUCCESS)throw std::runtime_error("MoveIt pose planning failed; A endpoint preserved");
  }
  output["performance"]["ik_and_planning_wall_s"]=std::chrono::duration<double>(std::chrono::steady_clock::now()-planning_begin).count();
  const auto timing_begin=std::chrono::steady_clock::now();
  robot_trajectory::RobotTrajectory trajectory(model,"manipulator");trajectory.setRobotTrajectoryMsg(start,plan.trajectory);
  trajectory_processing::TimeOptimalTrajectoryGeneration timing(.001,.03,.001);
  if(!timing.computeTimeStamps(trajectory,1,1))throw std::runtime_error("Time parameterization failed");
  double peak_velocity=0,peak_acceleration=0;for(std::size_t i=0;i<trajectory.getWayPointCount();++i)for(int j=1;j<=6;++j){auto name="joint_"+std::to_string(j);peak_velocity=std::max(peak_velocity,std::abs(trajectory.getWayPoint(i).getVariableVelocity(name)));peak_acceleration=std::max(peak_acceleration,std::abs(trajectory.getWayPoint(i).getVariableAcceleration(name)));}
  double scale=std::max({1.0,peak_velocity/.35,std::sqrt(peak_acceleration/.7)})*1.01;
  for(std::size_t i=0;i<trajectory.getWayPointCount();++i){trajectory.setWayPointDurationFromPrevious(i,trajectory.getWayPointDurationFromPrevious(i)*scale);for(int j=1;j<=6;++j){auto name="joint_"+std::to_string(j);auto& point=*trajectory.getWayPointPtr(i);point.setVariableVelocity(name,point.getVariableVelocity(name)/scale);point.setVariableAcceleration(name,point.getVariableAcceleration(name)/(scale*scale));}}
  output["time_dilation_factor"]=scale;output["peak_velocity_rad_s"]=peak_velocity/scale;output["peak_acceleration_rad_s2"]=peak_acceleration/(scale*scale);
  trajectory.getRobotTrajectoryMsg(plan.trajectory);
  output["trajectory_points"]=trajectory.getWayPointCount();output["planned_duration_sim_s"]=trajectory.getDuration();
  // Recheck the actual timed trajectory after smoothing, including held studs.
  output["performance"]["time_parameterization_wall_s"]=std::chrono::duration<double>(std::chrono::steady_clock::now()-timing_begin).count();
  const auto validation_begin=std::chrono::steady_clock::now();double collision_wall=0,record_wall=0;
  const auto* jmg=model->getJointModelGroup("manipulator");std::size_t checked=0,distance_checks=0;double minimum=std::numeric_limits<double>::infinity();
  for(std::size_t i=0;i<trajectory.getWayPointCount();++i){
   const auto& a=trajectory.getWayPoint(i?i-1:i);const auto& b=trajectory.getWayPoint(i);double maximum=0;
   for(const auto& name:jmg->getVariableNames())maximum=std::max(maximum,std::abs(a.getVariablePosition(name)-b.getVariablePosition(name)));
   int count=std::max(1,static_cast<int>(std::ceil(maximum/.001)));
   for(int sample=0;sample<=count;++sample){moveit::core::RobotState state(a);a.interpolate(b,double(sample)/count,state);state.update();
    if(!constraints.orientation_constraints.empty()&&!scene->isStateConstrained(state,constraints))throw std::runtime_error("Timed trajectory violates holding orientation");
    if(!state.satisfiesBounds())throw std::runtime_error("Timed trajectory bounds violation");
    collision_detection::CollisionRequest cr;cr.contacts=true;cr.max_contacts=10;cr.distance=(checked%100==0)||(sample==count&&i+1==trajectory.getWayPointCount());if(cr.distance)++distance_checks;collision_detection::CollisionResult result;const auto collision_begin=std::chrono::steady_clock::now();scene->checkCollision(cr,result,state);collision_wall+=std::chrono::duration<double>(std::chrono::steady_clock::now()-collision_begin).count();checked++;
    if(result.collision){for(const auto& pair:result.contacts){output["collision_pairs"].push_back(pair.first.first+" / "+pair.first.second);}throw std::runtime_error("Timed trajectory collision; no execution issued");}
    if(cr.distance)minimum=std::min(minimum,result.distance);
    const auto record_begin=std::chrono::steady_clock::now();record_checked_state(checked_stream,state,jmg);record_wall+=std::chrono::duration<double>(std::chrono::steady_clock::now()-record_begin).count();
   }
  }
  output["performance"]["validation_wall_s"]=std::chrono::duration<double>(std::chrono::steady_clock::now()-validation_begin).count();output["performance"]["collision_distance_wall_s"]=collision_wall;output["performance"]["state_record_wall_s"]=record_wall;
  output["post_timing_collision_checks"]=checked;output["max_joint_check_interval_rad"]=.001;output["minimum_sampled_distance_m"]=minimum;output["distance_diagnostic_samples"]=distance_checks;output["distance_diagnostic_stride_states"]=100;output["distance_is_diagnostic_only"]=true;
  output["plan_success"]=true;check_contract();
  state_data=actual();double start_change=0;for(int i=0;i<6;++i)start_change=std::max(start_change,std::abs(start.getVariablePosition("joint_"+std::to_string(i+1))-state_data["q_rad"][i].as<double>()));
  output["start_drift_before_execution_rad"]=start_change;if(start_change>.02)throw std::runtime_error("START_STATE_CHANGED: replan from actual stopped state");
  if(req["execute"].as<bool>()){
   Active active(run+"/execution.active.json",read(run+"/scene_context.json"));output["execution_issued"]=true;const auto execute_begin=std::chrono::steady_clock::now();auto result=group.execute(plan);output["performance"]["execution_wall_s"]=std::chrono::duration<double>(std::chrono::steady_clock::now()-execute_begin).count();output["execution_error_code"]=result.val;output["execution_success"]=result==moveit::core::MoveItErrorCode::SUCCESS;
   if(!output["execution_success"].as<bool>())throw std::runtime_error("Trajectory execution failed; hold and report");
  }
  output["actual_final"]=actual();write();rclcpp::shutdown();return 0;
 }catch(const std::exception& e){output["error"]=e.what();write();std::cerr<<e.what()<<'\n';if(rclcpp::ok())rclcpp::shutdown();return 1;}
}
