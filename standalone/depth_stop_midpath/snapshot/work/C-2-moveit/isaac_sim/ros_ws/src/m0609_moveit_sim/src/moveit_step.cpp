// File-only MoveIt candidate calculation. Execution and Current adoption belong to D/B.
#include <moveit/robot_model_loader/robot_model_loader.hpp>
#include <moveit/planning_scene/planning_scene.hpp>
#include <moveit/robot_trajectory/robot_trajectory.hpp>
#include <moveit/trajectory_processing/time_optimal_trajectory_generation.hpp>
#include <moveit_msgs/msg/attached_collision_object.hpp>
#include <moveit_msgs/msg/orientation_constraint.hpp>
#include <yaml-cpp/yaml.h>
#include <fstream>
#include <sstream>
#include <chrono>
#include <set>
#include <array>
#include <rclcpp/rclcpp.hpp>
#include <moveit/planning_pipeline/planning_pipeline.hpp>
#include <moveit/kinematic_constraints/utils.hpp>
#include <moveit/robot_state/conversions.hpp>

using namespace std::chrono_literals;
std::string read(const std::string& path){std::ifstream s(path);if(!s)throw std::runtime_error("Cannot read "+path);std::ostringstream o;o<<s.rdbuf();return o.str();}
geometry_msgs::msg::Pose pose(const YAML::Node& value){geometry_msgs::msg::Pose p;p.position.x=value["xyz_m"][0].as<double>();p.position.y=value["xyz_m"][1].as<double>();p.position.z=value["xyz_m"][2].as<double>();p.orientation.x=value["quaternion_xyzw"][0].as<double>();p.orientation.y=value["quaternion_xyzw"][1].as<double>();p.orientation.z=value["quaternion_xyzw"][2].as<double>();p.orientation.w=value["quaternion_xyzw"][3].as<double>();return p;}
Eigen::Isometry3d transform(const geometry_msgs::msg::Pose& p){Eigen::Isometry3d t=Eigen::Isometry3d::Identity();t.translation()<<p.position.x,p.position.y,p.position.z;t.linear()=Eigen::Quaterniond(p.orientation.w,p.orientation.x,p.orientation.y,p.orientation.z).normalized().toRotationMatrix();return t;}
geometry_msgs::msg::Pose pose(const Eigen::Isometry3d& t){geometry_msgs::msg::Pose p;p.position.x=t.translation().x();p.position.y=t.translation().y();p.position.z=t.translation().z();Eigen::Quaterniond q(t.rotation());p.orientation.x=q.x();p.orientation.y=q.y();p.orientation.z=q.z();p.orientation.w=q.w();return p;}
YAML::Node matrix(const Eigen::Isometry3d& t){YAML::Node n;for(int i=0;i<4;++i)for(int j=0;j<4;++j)n[i].push_back(t.matrix()(i,j));return n;}
Eigen::Isometry3d matrix(const YAML::Node& n){Eigen::Isometry3d t=Eigen::Isometry3d::Identity();for(int i=0;i<4;++i)for(int j=0;j<4;++j)t.matrix()(i,j)=n[i][j].as<double>();return t;}

moveit_msgs::msg::CollisionObject object(const YAML::Node& data,const Eigen::Isometry3d& frame,const std::string& frame_id,double padding=0)
{
 moveit_msgs::msg::CollisionObject obj;obj.id=data["id"].as<std::string>();obj.header.frame_id=frame_id;obj.operation=obj.ADD;
 auto add=[&](std::vector<double> size,const Eigen::Isometry3d& t){shape_msgs::msg::SolidPrimitive p;p.type=p.BOX;for(double v:size)p.dimensions.push_back(v+2*padding);obj.primitives.push_back(p);obj.primitive_poses.push_back(pose(t));};
 // The plate's nominal convex outline is shared with Isaac and the FCL guard.
 if(data["mesh_vertices_m"]){
  shape_msgs::msg::Mesh mesh;
  for(const auto& v:data["mesh_vertices_m"]){geometry_msgs::msg::Point p;p.x=v[0].as<double>();p.y=v[1].as<double>();p.z=v[2].as<double>();mesh.vertices.push_back(p);}
  for(const auto& t:data["mesh_triangles"]){shape_msgs::msg::MeshTriangle tri;for(int i=0;i<3;++i)tri.vertex_indices[i]=t[i].as<unsigned int>();mesh.triangles.push_back(tri);}
  obj.meshes.push_back(mesh);obj.mesh_poses.push_back(pose(frame));return obj;
 }
 auto size=data["size_m"].as<std::vector<double>>();add(size,frame);
 if(data["studs"].as<bool>()){
  int nx=std::lround(size[0]/.016),ny=std::lround(size[1]/.016);
  for(int x=0;x<nx;++x)for(int y=0;y<ny;++y){auto t=Eigen::Isometry3d::Identity();t.translation()<< (x-(nx-1)/2.0)*.016,(y-(ny-1)/2.0)*.016,.01175;add({.01,.01,.0045},frame*t);}
 }return obj;
}

// Each row has its own emitter: avoid merging thousands of YAML node graphs.
void record_checked_state(std::ostream& stream,const moveit::core::RobotState& state,const moveit::core::JointModelGroup* jmg,double time_s) {
 YAML::Emitter row;row.SetDoublePrecision(17);row<<YAML::Flow<<YAML::BeginMap<<YAML::Key<<"q_rad"<<YAML::Value<<YAML::BeginSeq;
 for(const auto& name:jmg->getVariableNames())row<<state.getVariablePosition(name);
 row<<YAML::EndSeq<<YAML::Key<<"tcp_matrix"<<YAML::Value<<YAML::BeginSeq;const auto& t=state.getGlobalLinkTransform("GripperDA_v4_tcp");
 for(int i=0;i<4;++i){row<<YAML::BeginSeq;for(int j=0;j<4;++j)row<<t.matrix()(i,j);row<<YAML::EndSeq;}
 row<<YAML::EndSeq<<YAML::Key<<"time_from_start_s"<<YAML::Value<<time_s<<YAML::EndMap;stream<<"  - "<<row.c_str()<<'\n';
}

// FJT with positions, velocities and accelerations uses quintic interpolation.
// Validate that curve rather than a straight chord between timed points.
std::array<double,6> quintic(const moveit::core::RobotState& a,const moveit::core::RobotState& b,const std::string& name,double dt){
 std::array<double,6> c={a.getVariablePosition(name),a.getVariableVelocity(name)*dt,.5*a.getVariableAcceleration(name)*dt*dt,0,0,0};
 const double p=b.getVariablePosition(name)-c[0]-c[1]-c[2],v=b.getVariableVelocity(name)*dt-c[1]-2*c[2],acc=b.getVariableAcceleration(name)*dt*dt-2*c[2];
 c[3]=10*p-4*v+.5*acc;c[4]=-15*p+7*v-acc;c[5]=6*p-3*v+.5*acc;return c;
}
double polynomial(const std::array<double,6>& c,double u,int derivative=0){
 double value=0;for(int i=derivative;i<6;++i){double factor=1;for(int j=0;j<derivative;++j)factor*=i-j;value+=factor*c[i]*std::pow(u,i-derivative);}return value;
}
// Peak estimates must not depend on a sampling grid that changes after dilation.
// Acceleration is cubic in normalized u: its extrema are quadratic jerk roots.
// Partition at those roots to bracket every velocity extremum (acceleration root).
std::array<double,2> quintic_motion_peaks(const std::array<double,6>& c,double dt){
 for(double coefficient:c)if(!std::isfinite(coefficient))throw std::runtime_error("Nonfinite quintic coefficient");
 if(!std::isfinite(dt)||dt<=0)throw std::runtime_error("Invalid quintic interval duration");
 std::vector<double> partitions={0.,1.};
 auto add_partition=[&](double u){if(std::isfinite(u)&&u>0&&u<1)partitions.push_back(u);};
 double a=60*c[5],b=24*c[4],d=6*c[3];
 const double magnitude=std::max({std::abs(a),std::abs(b),std::abs(d)});
 if(magnitude>0){
  a/=magnitude;b/=magnitude;d/=magnitude;
  if(a==0){if(b!=0)add_partition(-d/b);}
  else{
   const double discriminant=b*b-4*a*d;
   if(discriminant>=0){
    const double q=-.5*(b+std::copysign(std::sqrt(discriminant),b));
    if(q==0)add_partition(-b/(2*a));
    else{add_partition(q/a);add_partition(d/q);}
   }
  }
 }
 std::sort(partitions.begin(),partitions.end());
 partitions.erase(std::unique(partitions.begin(),partitions.end()),partitions.end());
 std::vector<double> velocity_candidates=partitions;
 for(std::size_t i=1;i<partitions.size();++i){
  double lo=partitions[i-1],hi=partitions[i];
  double flo=polynomial(c,lo,2),fhi=polynomial(c,hi,2);
  if(flo==0||fhi==0||std::signbit(flo)==std::signbit(fhi))continue;
  for(int iteration=0;iteration<80;++iteration){
   const double mid=(lo+hi)/2;if(mid==lo||mid==hi)break;
   const double fm=polynomial(c,mid,2);
   if(fm==0){lo=hi=mid;break;}
   if(std::signbit(fm)==std::signbit(flo)){lo=mid;flo=fm;}else hi=mid;
  }
  velocity_candidates.push_back((lo+hi)/2);
 }
 std::array<double,2> peaks={0.,0.};
 for(double u:velocity_candidates)peaks[0]=std::max(peaks[0],std::abs(polynomial(c,u,1)/dt));
 for(double u:partitions)peaks[1]=std::max(peaks[1],std::abs(polynomial(c,u,2)/(dt*dt)));
 if(!std::isfinite(peaks[0])||!std::isfinite(peaks[1]))throw std::runtime_error("Nonfinite quintic motion peak");
 return peaks;
}
int timed_samples(const std::vector<std::array<double,6>>& coefficients,double dt){
 double bound=0;for(const auto& c:coefficients){double v=0;for(int i=1;i<6;++i)v+=i*std::abs(c[i]);bound=std::max(bound,v);}
 return std::max({1,int(std::ceil(bound/.001)),int(std::ceil(dt/.005))});
}

// A real pickup still rests on its support. Equivalent controller/model FK
// differs by nanometres; handle only that same initial contact, never a board
// exemption, physical penetration, sliding contact, or added lift waypoint.
bool initial_support_contact(collision_detection::AllowedCollisionMatrix& contact_matrix,const YAML::Node& req,
                             const YAML::Node& selected,const collision_detection::CollisionResult& result,
                             const Eigen::Isometry3d& actual_tcp,const Eigen::Isometry3d& expected_tcp,YAML::Node& output){
 if(!req["confirmation_kind"])return false;
 const auto kind=req["confirmation_kind"].as<std::string>();
 const bool sim=kind=="SIM_TEST_STATE"&&req["source_snapshot"]["simulation_provenance"]["source_kind"]&&
   req["source_snapshot"]["simulation_provenance"]["source_kind"].as<std::string>()=="ISAAC_SIM_SAVED_STATE";
 // PhysX dynamic resting bodies have micrometre solver residuals. REAL's
 // equivalent-FK 100nm criterion remains unchanged and never uses this bound.
 const double numerical_m=sim?5e-6:1e-7;
 if((!sim&&kind!="REAL_D_SYNTHETIC_B_OPERATOR_TRIAL_STATE")||
    (actual_tcp.translation()-expected_tcp.translation()).norm()>numerical_m||
    Eigen::AngleAxisd(expected_tcp.linear().transpose()*actual_tcp.linear()).angle()>(sim?1e-5:1e-6))return false;
 YAML::Node board;bool board_found=false;
 for(const auto& o:req["planning_snapshot"]["world_objects"])if(o["role"].as<std::string>()=="SUPPLY_BOARD"){
  if(board_found)return false;board=YAML::Clone(o);board_found=true;
 }
 if(!board_found||board["mesh_vertices_m"]||board["studs"].as<bool>())return false;
 const auto bt=transform(pose(board["pose"])),held=transform(pose(selected["pose"]));
 if((bt.linear()-Eigen::Matrix3d::Identity()).norm()>1e-9||
    // A freshly squeezed SIM block can rest on a corner within 0.01rad tilt.
    // Its actual lowest corner and FCL support point must still meet 5um.
    (held.linear().col(2)-Eigen::Vector3d::UnitZ()).norm()>(sim?.01:1e-9))return false;
 const double top=bt.translation().z()+board["size_m"][2].as<double>()/2;
 double bottom=held.translation().z()-selected["size_m"][2].as<double>()/2;
 if(sim){bottom=std::numeric_limits<double>::infinity();const auto size=selected["size_m"].as<std::vector<double>>();
  for(double x:{-size[0]/2,size[0]/2})for(double y:{-size[1]/2,size[1]/2})bottom=std::min(bottom,(held*Eigen::Vector3d(x,y,-size[2]/2)).z());
 }
 if(std::abs(bottom-top)>(sim?numerical_m:1e-9)||result.contacts.size()!=1)return false;
 const std::pair<std::string,std::string> key=std::minmax(board["id"].as<std::string>(),selected["id"].as<std::string>());
 const auto& pair=*result.contacts.begin();
 if(pair.first.first!=key.first||pair.first.second!=key.second||pair.second.empty())return false;
 std::vector<Eigen::Vector3d> positions;
 for(const auto& c:pair.second){
  if(!std::isfinite(c.depth)||c.depth<0||c.depth>numerical_m||!c.pos.allFinite()||
     std::abs(c.pos.z()-top)>numerical_m||std::abs(std::abs(c.normal.z())-1)>1e-6)return false;
  positions.push_back(c.pos);output["initial_support_contact"]["depth_m"].push_back(c.depth);
 }
 collision_detection::DecideContactFn decision=[positions,top,numerical_m](collision_detection::Contact& c){
  if(!std::isfinite(c.depth)||c.depth<0||c.depth>numerical_m||!c.pos.allFinite()||
     std::abs(c.pos.z()-top)>numerical_m||std::abs(std::abs(c.normal.z())-1)>1e-6)return false;
  for(const auto& p:positions)if((c.pos-p).norm()<=numerical_m)return true;
  return false;
 };
 contact_matrix.setEntry(pair.first.first,pair.first.second,decision);
 output["initial_support_contact"]["policy"]=sim?"SIM_SAME_INITIAL_CONTACT_WITHIN_5_MICROMETRES":"SAME_INITIAL_CONTACT_WITHIN_100_NANOMETRES";
 output["initial_support_contact"]["pair"]=pair.first.first+" / "+pair.first.second;
 output["initial_support_contact"]["position_limit_m"]=numerical_m;
 output["initial_support_contact"]["blanket_world_touch_allowed"]=false;
 return true;
}

int main(int argc,char** argv)
{
 if(argc<5||argc>7){std::cerr<<"moveit_plan_only ROOT RUN_DIR REQUEST_YAML RESULT_YAML [EXTERNAL_CUMOTION_YAML_OR_DASH] [BENCHMARK_FIXTURE_YAML]\n";return 2;}
 const bool external=argc>=6&&std::string(argv[5])!="-",benchmark=argc==7;
 std::string root=argv[1],run=argv[2];std::ostringstream checked_stream;YAML::Node output;output["scope"]="FILE_ONLY_PLAN_CANDIDATE";output["result_provenance"]="MOVEIT_LOCAL_PLANNING_RESULT";output["execution_allowed"]=false;output["execution_issued"]=false;output["hardware_execution_allowed"]=false;output["assembly_completed"]=false;output["plan_success"]=false;output["execution_success"]=false;
 auto write=[&]{std::string target=argv[4];std::ofstream stream(target+".tmp");stream<<output<<'\n';if(!checked_stream.str().empty())stream<<"checked_states:\n"<<checked_stream.str();stream.close();std::rename((target+".tmp").c_str(),target.c_str());};
 try{
  YAML::Node req=YAML::LoadFile(argv[3]);std::string phase=req["phase"].as<std::string>();output["phase"]=phase;
  double planning_seconds=15,planning_fraction=.00001;
  if(const char* value=std::getenv("SEEUN_CHAIR_PLANNING_SECONDS")){
   const char* domain=std::getenv("ROS_DOMAIN_ID");const char* discovery=std::getenv("ROS_AUTOMATIC_DISCOVERY_RANGE");
   if(req["confirmation_kind"].as<std::string>()!="SIM_TEST_STATE"||!domain||std::string(domain)!="93"||
      !discovery||std::string(discovery)!="LOCALHOST")throw std::runtime_error("SIM_PLANNING_BUDGET_ONLY");
   std::size_t consumed=0;planning_seconds=std::stod(value,&consumed);
   if(consumed!=std::string(value).size()||!std::isfinite(planning_seconds)||planning_seconds<15||planning_seconds>60)
    throw std::runtime_error("SIM_PLANNING_BUDGET_RANGE");
  }
  output["planner_allowed_time_s"]=planning_seconds;
  if(const char* value=std::getenv("SEEUN_CHAIR_PLANNING_FRACTION")){
   const char* domain=std::getenv("ROS_DOMAIN_ID");const char* discovery=std::getenv("ROS_AUTOMATIC_DISCOVERY_RANGE");
   if(req["confirmation_kind"].as<std::string>()!="SIM_TEST_STATE"||!domain||std::string(domain)!="93"||
      !discovery||std::string(discovery)!="LOCALHOST")throw std::runtime_error("SIM_PLANNING_RESOLUTION_ONLY");
   std::size_t consumed=0;planning_fraction=std::stod(value,&consumed);
   if(consumed!=std::string(value).size()||!std::isfinite(planning_fraction)||planning_fraction<.00001||planning_fraction>.0001)
    throw std::runtime_error("SIM_PLANNING_RESOLUTION_RANGE");
  }
  output["planner_segment_fraction"]=planning_fraction;
  // Reject executable and legacy requests before creating any ROS context.
  for(const auto& key:{"execute","sim_execution_authorized","hardware_execution_allowed","a_execution_allowed"})
   if(!req[key]||req[key].as<bool>())throw std::runtime_error("PLAN_ONLY_GATE_REJECTED");
  if(req["kind"].as<std::string>()!="POSE"||phase!="TRANSPORT"||!req["held"].as<bool>()||req["contact_phase"].as<bool>()||!req["planning_allowed"].as<bool>())throw std::runtime_error("POST_GRASP_TRANSPORT_ONLY");
  if(req["allow_touch_world_id"])throw std::runtime_error("WORLD_TOUCH_ALLOWANCE_FORBIDDEN");
  if(req["terminal_gripper_policy"].as<std::string>()!="HOLD_NO_AUTOMATIC_OPEN"||req["handoff_to"].as<std::string>()!="D_CONTACT")throw std::runtime_error("PRECONTACT_BOUNDARY_REQUIRED");
  if(req["transport_boundary"].as<std::string>()!="POST_GRASP_TO_PRE_CONTACT_POSE"||req["cartesian"].as<bool>()||req["mandatory_waypoint_count"].as<int>()!=0||req["trajectory_interpolation"].as<std::string>()!="QUINTIC"||req["contact_approach_owner"].as<std::string>()!="D"||req["final_goal"].IsDefined())throw std::runtime_error("ENDPOINT_ONLY_TRANSPORT_REQUIRED");
  const auto goal_pose=transform(pose(req["goal"]));
  if(!goal_pose.matrix().allFinite()||(goal_pose.matrix()-transform(pose(req["expected_precontact"])).matrix()).norm()>1e-8)throw std::runtime_error("PRECONTACT_TARGET_CHANGED");
  output["transport_boundary"]="POST_GRASP_TO_PRE_CONTACT_POSE";output["mandatory_waypoint_count"]=0;
  output["cartesian_tail_executed"]=false;output["single_transport_trajectory"]=true;
  output["trajectory_interpolation"]="QUINTIC";
  const auto bundle=req["model_bundle"];const auto folder=bundle["bundle_path"].as<std::string>();
  const auto robot_xml=read(folder+"/robot.urdf"),semantic_xml=read(folder+"/semantic.srdf"),limits_yaml=read(folder+"/joint_limits.yaml");
  if(robot_xml!=bundle["robot_description"].as<std::string>()||semantic_xml!=bundle["robot_description_semantic"].as<std::string>()||limits_yaml!=bundle["joint_limits_yaml"].as<std::string>())throw std::runtime_error("MODEL_FILES_CHANGED");
  auto check_contract=[&]{auto ctx=YAML::LoadFile(run+"/scene_context.json");
   for(const auto& key:{"plan_id","step_id","current_revision","world_revision","profile_version","reservation_id","request_id","workflow_generation","source_epoch","assessment_input_digest","scene_digest","job_id","design_version","profile_id","reservation_generation","assessment_id","motion_input_digest","motion_result_digest","model_digest","planning_request_digest"})
    if(ctx[key].as<std::string>()!=req[key].as<std::string>())throw std::runtime_error("STALE_CONTEXT");
  };check_contract();
  YAML::Node fixture;
  if(benchmark){
   fixture=YAML::LoadFile(argv[6]);
   if(req["confirmation_kind"].as<std::string>()!="SIM_TEST_STATE"||fixture["scope"].as<std::string>()!="OFFLINE_BENCHMARK_OVERLAY_NOT_OBSERVED_CURRENT"||fixture["execution_allowed"].as<bool>()||fixture["planning_request_digest"].as<std::string>()!=req["planning_request_digest"].as<std::string>())throw std::runtime_error("BENCHMARK_GATE_REJECTED");
   output["scope"]="FILE_ONLY_BENCHMARK_CANDIDATE";output["benchmark_fixture"]=fixture;
   if(fixture["start_override_rad"]){if(fixture["start_override_rad"].size()!=6)throw std::runtime_error("BENCHMARK_INVALID_START_VECTOR");for(const auto& q:fixture["start_override_rad"])if(!std::isfinite(q.as<double>()))throw std::runtime_error("BENCHMARK_NONFINITE_START");}
  }
  YAML::Node imported;
  if(external){
   imported=YAML::LoadFile(argv[5]);
   const auto origin=imported["scope"].as<std::string>();
   const bool adapter_fixture=benchmark&&origin=="FILE_ONLY_EXTERNAL_TIMED_ADAPTER_FIXTURE";
   output["result_provenance"]=adapter_fixture?"EXTERNAL_TIMED_ADAPTER_FIXTURE_FCL_RESULT":"CUMOTION_STANDALONE_WITH_FCL_POSTCHECK";
   if(req["confirmation_kind"].as<std::string>()!="SIM_TEST_STATE"||
      (origin!="FILE_ONLY_EXTERNAL_CUMOTION_TIMED"&&!adapter_fixture)||
      imported["execution_allowed"].as<bool>()||imported["hardware_execution_allowed"].as<bool>())throw std::runtime_error("EXTERNAL_CALCULATION_ONLY_SIM_REQUIRED");
   auto ctx=YAML::LoadFile(run+"/scene_context.json");
   if(imported["binding"].size()!=ctx.size())throw std::runtime_error("EXTERNAL_BINDING_INCOMPLETE");
   for(const auto& item:ctx)if(!imported["binding"][item.first.as<std::string>()]||imported["binding"][item.first.as<std::string>()].as<std::string>()!=item.second.as<std::string>())throw std::runtime_error("EXTERNAL_STALE_BINDING");
  }
  rclcpp::init(0,nullptr);
  rclcpp::NodeOptions options;options.automatically_declare_parameters_from_overrides(true);
  std::vector<rclcpp::Parameter> parameters={rclcpp::Parameter("use_sim_time",false),rclcpp::Parameter("robot_description",robot_xml),rclcpp::Parameter("robot_description_semantic",semantic_xml),rclcpp::Parameter("robot_description_kinematics.manipulator.kinematics_solver","kdl_kinematics_plugin/KDLKinematicsPlugin"),rclcpp::Parameter("robot_description_kinematics.manipulator.kinematics_solver_timeout",.1)};
  auto limits=YAML::Load(limits_yaml)["joint_limits"];
  for(const auto& joint:limits)for(const auto& entry:joint.second){
   std::string name="robot_description_planning.joint_limits."+joint.first.as<std::string>()+"."+entry.first.as<std::string>();
   if(entry.first.as<std::string>().find("has_")==0)parameters.emplace_back(name,entry.second.as<bool>());else parameters.emplace_back(name,entry.second.as<double>());
  }
  parameters.emplace_back("ompl.planner_configs.RRTConnect.type","geometric::RRTConnect");
  parameters.emplace_back("ompl.planner_configs.RRTConnect.range",.12);
  parameters.emplace_back("ompl.manipulator.planner_configs",std::vector<std::string>{"RRTConnect"});
  parameters.emplace_back("ompl.manipulator.default_planner_config","RRTConnect");
  // Use the same joint-space interpolation in planning and exported-path checks.
  parameters.emplace_back("ompl.manipulator.enforce_joint_model_state_space",true);
  output["planning_state_space"]="JOINT_MODEL";
  // MoveIt 2.12.4 loads this group resolution; maximum_waypoint_distance is
  // not one of its loaded group parameters. Avoid skipping thin stud contacts.
  parameters.emplace_back("ompl.manipulator.longest_valid_segment_fraction",planning_fraction);
  options.parameter_overrides(parameters);
  auto node=std::make_shared<rclcpp::Node>("file_only_moveit_plan", "/a_plan_only", options);
  YAML::Node state_data=YAML::Clone(req["planning_snapshot"]);
  if(benchmark&&fixture["start_override_rad"])state_data["q_rad"]=YAML::Clone(fixture["start_override_rad"]);
  output["actual_start"]=state_data;
  robot_model_loader::RobotModelLoader loader(node,"robot_description",true);auto model=loader.getModel();
  if(!model)throw std::runtime_error("Robot model missing");
  auto scene=std::make_shared<planning_scene::PlanningScene>(model);
  const std::string slot=state_data["selected_slot_id"].as<std::string>();const bool held=true;
  YAML::Node selected;
  // Conservative envelopes for blocks only: compensate nominal tracking and
  // PhysX contact-offset effects without rewriting saved/physical geometry.
  output["planning_block_padding_m"]=.002;
  output["planning_padding_roles"]=std::vector<std::string>{"SUPPLY_BLOCK","CURRENT_BLOCK"};
  for(const auto& obj:state_data["world_objects"]){
   if(obj["id"].as<std::string>()==slot)selected=YAML::Clone(obj);
   else {const auto role=obj["role"].as<std::string>();const double padding=(role=="SUPPLY_BLOCK"||role=="CURRENT_BLOCK")?.002:0;
    if(!scene->processCollisionObjectMsg(object(obj,transform(pose(obj["pose"])),"base_link",padding)))throw std::runtime_error("World collision object rejected");}
  }
  if(benchmark)for(const auto& obj:fixture["test_obstacles"]){
   if(obj["role"].as<std::string>()!="BENCHMARK_OBSTACLE"||obj["id"].as<std::string>().find("Benchmark_")!=0||scene->getWorld()->hasObject(obj["id"].as<std::string>()))throw std::runtime_error("BENCHMARK_ADDITIVE_OBSTACLES_ONLY");
   if(obj["size_m"].size()!=3||obj["studs"].as<bool>()||!transform(pose(obj["pose"])).matrix().allFinite())throw std::runtime_error("BENCHMARK_INVALID_CUBOID");
   for(const auto& v:obj["size_m"])if(!std::isfinite(v.as<double>())||v.as<double>()<=0)throw std::runtime_error("BENCHMARK_INVALID_SIZE");
   if(!scene->processCollisionObjectMsg(object(obj,transform(pose(obj["pose"])),"base_link")))throw std::runtime_error("Benchmark obstacle rejected");
  }
  if(!selected)throw std::runtime_error("Held collision geometry missing");
  moveit_msgs::msg::AttachedCollisionObject attached;attached.link_name="GripperDA_v4_tcp";
  attached.object=object(selected,matrix(req["attachment"]),attached.link_name);
  attached.touch_links={"rg2_left_inner_finger","rg2_right_inner_finger"};
  if(!scene->processAttachedCollisionObjectMsg(attached))throw std::runtime_error("Attachment rejected");
  auto& start=scene->getCurrentStateNonConst();
  for(int i=0;i<6;++i)start.setVariablePosition("joint_"+std::to_string(i+1),state_data["q_rad"][i].as<double>());
  start.setVariablePosition("rg2_finger_joint",state_data["grip_rad"].as<double>());start.update();
  if(!start.satisfiesBounds())throw std::runtime_error("Start bounds violation");
  const auto expected_tcp=transform(pose(state_data["tcp_pose"]));const auto actual_tcp=start.getGlobalLinkTransform("GripperDA_v4_tcp");
  if((expected_tcp.translation()-actual_tcp.translation()).norm()>.0008||Eigen::AngleAxisd(expected_tcp.linear().transpose()*actual_tcp.linear()).angle()>.005)throw std::runtime_error("Snapshot FK/TCP mismatch");
  output["world_object_count"]=scene->getWorld()->size();output["attached_object_count"]=1;output["touch_links"]=attached.touch_links;
  planning_pipeline::PlanningPipeline pipeline(model,node,"ompl",{"ompl_interface/OMPLPlanner"});
  const auto planner=pipeline.getPlannerManager("ompl_interface/OMPLPlanner");
  if(!planner)throw std::runtime_error("OMPL planner instance missing");
  for(const auto& config:planner->getPlannerConfigurations())for(const auto& item:config.second.config)
   output["effective_planner_config"][config.first][item.first]=item.second;
  collision_detection::CollisionRequest start_request;start_request.contacts=true;start_request.max_contacts=100;start_request.max_contacts_per_pair=50;collision_detection::CollisionResult start_result;scene->checkCollision(start_request,start_result,start);
  if(start_result.collision&&!req["controller_command_start"]&&initial_support_contact(scene->getAllowedCollisionMatrixNonConst(),req,selected,start_result,actual_tcp,expected_tcp,output)){
   start_result.clear();scene->checkCollision(start_request,start_result,start);
  }
  // A commanded HOLD does not erase the separately observed pickup contact.
  // Apply the EXISTING bounded SIM support policy only to a value-copy matrix
  // used for that observed-state recheck. Planning/command/path ACM stays strict.
  bool observed_support_verified=false;
  if(start_result.collision&&req["controller_command_start"]&&req["confirmation_kind"].as<std::string>()=="SIM_TEST_STATE"){
   const auto original_matrix=scene->getAllowedCollisionMatrix();
   auto observed_contact_matrix=original_matrix;
   if(initial_support_contact(observed_contact_matrix,req,selected,start_result,actual_tcp,expected_tcp,output)){
    collision_detection::CollisionResult observed_recheck;
    scene->checkCollision(start_request,observed_recheck,start,observed_contact_matrix);
    observed_support_verified=!observed_recheck.collision;
    moveit_msgs::msg::AllowedCollisionMatrix before_matrix,after_matrix;
    original_matrix.getMessage(before_matrix);scene->getAllowedCollisionMatrix().getMessage(after_matrix);
    if(before_matrix!=after_matrix)throw std::runtime_error("Observed support classification mutated planning collision matrix");
    output["observed_initial_support_classification"]["scope"]="EXISTING_SIM_NUMERICAL_POLICY_OBSERVED_STATE_ONLY";
    output["observed_initial_support_classification"]["original_observed_collision"]=true;
    output["observed_initial_support_classification"]["full_observed_state_recheck_passed"]=observed_support_verified;
    output["observed_initial_support_classification"]["planning_matrix_unchanged"]=true;
    output["observed_initial_support_classification"]["command_and_path_contact_exception"]=false;
   }
  }
  if(start_result.collision&&!observed_support_verified){for(const auto& pair:start_result.contacts)output["collision_pairs"].push_back(pair.first.first+" / "+pair.first.second);throw std::runtime_error("Actual start state collision: no planning or execution issued");}
  if(req["controller_command_start"]){
   const auto command_start=req["controller_command_start"];
   if(external||benchmark||phase!="TRANSPORT"||req["confirmation_kind"].as<std::string>()!="SIM_TEST_STATE"||req["simulation_provenance"]["source_kind"].as<std::string>()!="ISAAC_SIM_SAVED_STATE"||command_start["scope"].as<std::string>()!="SIM_VERIFIED_HOLD_JTC_DESIRED_PLANNING_START"||command_start["joint_names"].as<std::vector<std::string>>()!=std::vector<std::string>{"joint_1","joint_2","joint_3","joint_4","joint_5","joint_6"})throw std::runtime_error("Unsupported command planning start");
   const auto command=command_start["command"];
   for(const auto name:{"q_rad","v_rad_s","a_rad_s2"})if(command[name].size()!=6)throw std::runtime_error("Complete command planning PVA required");
   for(int i=0;i<6;++i){
    const double q=command["q_rad"][i].as<double>(),v=command["v_rad_s"][i].as<double>(),a=command["a_rad_s2"][i].as<double>();
    if(!std::isfinite(q)||!std::isfinite(v)||!std::isfinite(a)||v!=0||a!=0)throw std::runtime_error("Verified HOLD command planning start required");
    start.setVariablePosition("joint_"+std::to_string(i+1),q);
   }
   start.update();if(!start.satisfiesBounds())throw std::runtime_error("Command planning start bounds violation");
   collision_detection::CollisionResult command_collision;scene->checkCollision(start_request,command_collision,start);
   if(command_collision.collision)throw std::runtime_error("Command planning start full collision");
   output["observed_start_separately_collision_checked"]=true;
   output["controller_command_start"]=YAML::Clone(command_start);
   output["planning_start"]["q_rad"]=YAML::Clone(command["q_rad"]);
   output["planning_start"]["grip_rad"]=YAML::Clone(state_data["grip_rad"]);
   output["planning_start"]["tcp_source_kind"]="MODEL_DERIVED_COMMAND_START_TCP";
   output["planning_start"]["tcp_matrix"]=matrix(start.getGlobalLinkTransform("GripperDA_v4_tcp"));
  }
  moveit_msgs::msg::Constraints constraints;
  if(held&&phase=="TRANSPORT"){
   moveit_msgs::msg::OrientationConstraint c;c.header.frame_id="base_link";c.link_name="GripperDA_v4_tcp";c.orientation=pose(req["holding_orientation"]).orientation;c.absolute_x_axis_tolerance=.25;c.absolute_y_axis_tolerance=.25;c.absolute_z_axis_tolerance=req["allow_yaw_reorientation"]&&req["allow_yaw_reorientation"].as<bool>()?M_PI:.6;c.weight=1;c.parameterization=c.ROTATION_VECTOR;constraints.orientation_constraints.push_back(c);
  }
  struct {moveit_msgs::msg::RobotTrajectory trajectory;} plan;
  robot_trajectory::RobotTrajectory trajectory(model,"manipulator");
  if(!external){
  const auto planning_begin=std::chrono::steady_clock::now();
  const auto* joints=model->getJointModelGroup("manipulator");
  output["goal_raw_ik_found"]=false;
  moveit::core::RobotState best(start);double score=std::numeric_limits<double>::infinity();
  std::vector<moveit::core::RobotState> goal_states;
  auto nearest=[&](moveit::core::RobotState& candidate){for(const auto& name:joints->getVariableNames()){double q=candidate.getVariablePosition(name),reference=start.getVariablePosition(name);const auto& bounds=model->getVariableBounds(name);while(q-reference>M_PI&&q-2*M_PI>=bounds.min_position_)q-=2*M_PI;while(q-reference<-M_PI&&q+2*M_PI<=bounds.max_position_)q+=2*M_PI;candidate.setVariablePosition(name,q);}candidate.update();};
  auto valid=[&](moveit::core::RobotState* candidate,const moveit::core::JointModelGroup* group,const double* values){
   candidate->setJointGroupPositions(group,values);nearest(*candidate);
   if(!candidate->satisfiesBounds()||!scene->isStateConstrained(*candidate,constraints))return false;
   output["goal_raw_ik_found"]=true;collision_detection::CollisionRequest cr;cr.contacts=true;cr.max_contacts=30;
   collision_detection::CollisionResult full;scene->checkCollision(cr,full,*candidate);
   // A detached COPY is diagnostic only; accepted goals always use full.
   moveit::core::RobotState robot_only(*candidate);robot_only.clearAttachedBodies();robot_only.update();
   collision_detection::CollisionResult bare;scene->checkCollision(cr,bare,robot_only);
   if(!bare.collision){output["goal_robot_only_collision"]=false;output["goal_with_held_collision"]=full.collision;output["goal_held_only_collision"]=full.collision;
    output["goal_collision_pairs"]=YAML::Node(YAML::NodeType::Sequence);for(const auto& pair:full.contacts)output["goal_collision_pairs"].push_back(pair.first.first+" / "+pair.first.second);
   }
   return !full.collision;
  };
  for(int attempt=0;attempt<24;++attempt){moveit::core::RobotState candidate(start);if(attempt)candidate.setToRandomPositions(joints);if(candidate.setFromIK(joints,transform(pose(req["goal"])),"GripperDA_v4_tcp",.05,valid)){nearest(candidate);double cost=0;for(const auto& name:joints->getVariableNames())cost+=std::pow(candidate.getVariablePosition(name)-start.getVariablePosition(name),2);if(cost<score){score=cost;best=candidate;}
   bool duplicate=false;for(const auto& goal_state:goal_states)if(candidate.distance(goal_state,joints)<.05){duplicate=true;break;}
   if(!duplicate)goal_states.push_back(candidate);
  }}
  if(!std::isfinite(score))throw std::runtime_error("No collision-free IK goal");
  const bool chair_search=std::getenv("SEEUN_CHAIR_PLANNING_SECONDS")!=nullptr;
  auto same_topology=[&](const moveit::core::RobotState& candidate){return candidate.getVariablePosition("joint_3")*start.getVariablePosition("joint_3")>0&&candidate.getVariablePosition("joint_5")*start.getVariablePosition("joint_5")>0;};
  if(chair_search){
   // A useful ranking hint, never a reason to delete a valid IK family.
   std::stable_sort(goal_states.begin(),goal_states.end(),[&](const auto& a,const auto& b){if(same_topology(a)!=same_topology(b))return same_topology(a);return a.distance(start,joints)<b.distance(start,joints);});
   best=goal_states.front();output["sim_goal_topology_preference"]="RANK_ONLY_ALL_VALID_FAMILIES_RETAINED";
  }else goal_states={best};
  output["goal_ik_family_count"]=goal_states.size();
  for(const auto& goal_state:goal_states){YAML::Node family;for(const auto& name:joints->getVariableNames())family.push_back(goal_state.getVariablePosition(name));output["goal_ik_families"].push_back(family);}
  // Diagnostic only: joint interpolation is never issued as a motion command.
  double direct_step=0;for(const auto& name:joints->getVariableNames())direct_step=std::max(direct_step,std::abs(best.getVariablePosition(name)-start.getVariablePosition(name)));
  int direct_count=std::max(1,int(std::ceil(direct_step/.005)));int direct_collisions=0;
  for(int i=0;i<=direct_count;++i){moveit::core::RobotState state(start);start.interpolate(best,double(i)/direct_count,state);state.update();if(scene->isStateColliding(state)){
   ++direct_collisions;
   if(direct_collisions<=10){YAML::Node sample;sample["index"]=i;sample["fraction"]=double(i)/direct_count;
    collision_detection::CollisionRequest cr;cr.contacts=true;cr.max_contacts=30;collision_detection::CollisionResult detail;scene->checkCollision(cr,detail,state);
    sample["detailed_collision"]=detail.collision;for(const auto& pair:detail.contacts)sample["pairs"].push_back(pair.first.first+" / "+pair.first.second);
    for(const auto& name:joints->getVariableNames())sample["q_rad"].push_back(state.getVariablePosition(name));
    output["direct_joint_collision_samples"].push_back(sample);
   }
  }}
  output["start_holding_constraint_valid"]=scene->isStateConstrained(start,constraints);
  output["goal_q_rad"]=std::vector<double>();for(const auto& name:joints->getVariableNames())output["goal_q_rad"].push_back(best.getVariablePosition(name));
  output["direct_joint_path_collision_count"]=direct_collisions;output["direct_joint_path_diagnostic_only"]=true;
  planning_interface::MotionPlanRequest planning_request;planning_request.group_name="manipulator";planning_request.planner_id="RRTConnect";planning_request.allowed_planning_time=planning_seconds;planning_request.num_planning_attempts=4;
  moveit::core::robotStateToRobotStateMsg(start,planning_request.start_state);
  // Each goal is the same required TCP pose with a checked IK family. A
  // numerically nearest family can be disconnected under the holding cone.
  for(const auto& goal_state:goal_states)planning_request.goal_constraints.push_back(kinematic_constraints::constructGoalConstraints(goal_state,joints));
  planning_request.path_constraints=constraints;
  output["calculation_stage"]="SEARCH_PENDING_NOT_A_TRAJECTORY";write();
  planning_interface::MotionPlanResponse response;
  if(!chair_search){
   if(!pipeline.generatePlan(scene,planning_request,response)||response.error_code!=moveit::core::MoveItErrorCode::SUCCESS||!response.trajectory)throw std::runtime_error("MoveIt local planning failed");
  }else{
   double selected_cost=std::numeric_limits<double>::infinity();int feasible=0;int extra_attempts=0;
   output["ik_candidate_attempts"]=YAML::Node(YAML::NodeType::Sequence);
   auto screen=[&](robot_trajectory::RobotTrajectory& route,double& cost,std::size_t& checks,YAML::Node& record){
    if(route.getWayPointCount()<2||route.getFirstWayPoint().distance(start,joints)>1e-6)throw std::runtime_error("Candidate start changed");
    auto endpoint=route.getLastWayPoint().getGlobalLinkTransform("GripperDA_v4_tcp"),target=transform(pose(req["goal"]));
    if((endpoint.translation()-target.translation()).norm()>.0008||Eigen::AngleAxisd(target.linear().transpose()*endpoint.linear()).angle()>.005)throw std::runtime_error("Candidate approximate/wrong endpoint");
    auto check=[&](moveit::core::RobotState& state){state.update();++checks;
     if(!state.satisfiesBounds())throw std::runtime_error("Candidate joint bounds violation");
     if(!scene->isStateConstrained(state,constraints))throw std::runtime_error("Candidate holding orientation violation");
     if(scene->isStateColliding(state)){collision_detection::CollisionRequest request;request.contacts=true;request.max_contacts=10;collision_detection::CollisionResult detail;scene->checkCollision(request,detail,state);
      for(const auto& pair:detail.contacts)record["collision_pairs"].push_back(pair.first.first+" / "+pair.first.second);throw std::runtime_error("Candidate full-scene collision");}
    };
    cost=0;record["screen_stage"]="GEOMETRIC";
    for(std::size_t i=1;i<route.getWayPointCount();++i){auto a=route.getWayPoint(i-1),b=route.getWayPoint(i);cost+=a.distance(b,joints);double maximum=0;
     for(const auto& name:joints->getVariableNames())maximum=std::max(maximum,std::abs(a.getVariablePosition(name)-b.getVariablePosition(name)));
     int count=std::max(1,int(std::ceil(maximum/.001)));for(int j=0;j<=count;++j){moveit::core::RobotState state(a);a.interpolate(b,double(j)/count,state);check(state);}
    }
    trajectory_processing::TimeOptimalTrajectoryGeneration timing(.00005,.01,.00001);
    if(!timing.computeTimeStamps(route,1,1))throw std::runtime_error("Candidate time parameterization failed");
    // Apply the same velocity/acceleration time scaling as the final gate.
  double peak_velocity=0,peak_acceleration=0;for(std::size_t i=0;i<route.getWayPointCount();++i)for(int j=1;j<=6;++j){auto name="joint_"+std::to_string(j);peak_velocity=std::max(peak_velocity,std::abs(route.getWayPoint(i).getVariableVelocity(name)));peak_acceleration=std::max(peak_acceleration,std::abs(route.getWayPoint(i).getVariableAcceleration(name)));}
  for(std::size_t i=1;i<route.getWayPointCount();++i){const auto& a=route.getWayPoint(i-1);const auto& b=route.getWayPoint(i);const double dt=route.getWayPointDurationFromPrevious(i);if(dt<=0)throw std::runtime_error("Non-increasing timed route");
   std::vector<std::array<double,6>> coefficients;for(const auto& name:joints->getVariableNames())coefficients.push_back(quintic(a,b,name,dt));
   for(const auto& c:coefficients){const auto peaks=quintic_motion_peaks(c,dt);peak_velocity=std::max(peak_velocity,peaks[0]);peak_acceleration=std::max(peak_acceleration,peaks[1]);}
  }
  double scale=std::max({1.0,peak_velocity/.35,std::sqrt(peak_acceleration/.7)})*1.01;
  for(std::size_t i=0;i<route.getWayPointCount();++i){route.setWayPointDurationFromPrevious(i,route.getWayPointDurationFromPrevious(i)*scale);for(int j=1;j<=6;++j){auto name="joint_"+std::to_string(j);auto& point=*route.getWayPointPtr(i);point.setVariableVelocity(name,point.getVariableVelocity(name)/scale);point.setVariableAcceleration(name,point.getVariableAcceleration(name)/(scale*scale));}}

    record["screen_stage"]="TIMED_QUINTIC";
    for(std::size_t i=1;i<route.getWayPointCount();++i){const auto& a=route.getWayPoint(i-1);const auto& b=route.getWayPoint(i);double dt=route.getWayPointDurationFromPrevious(i);
     if(dt<=0)throw std::runtime_error("Candidate invalid time");std::vector<std::array<double,6>> coefficients;
     for(const auto& name:joints->getVariableNames())coefficients.push_back(quintic(a,b,name,dt));int count=timed_samples(coefficients,dt);
     for(int j=0;j<=count;++j){moveit::core::RobotState state(a);int k=0;for(const auto& name:joints->getVariableNames())state.setVariablePosition(name,polynomial(coefficients[k++],double(j)/count));check(state);}
    }
   };
   for(std::size_t index=0;index<goal_states.size()&&feasible<2&&(!feasible||extra_attempts<1);++index){
    double remaining=planning_seconds-std::chrono::duration<double>(std::chrono::steady_clock::now()-planning_begin).count();
    if(remaining<.1)break;
    if(feasible)++extra_attempts;
    auto attempt=planning_request;attempt.goal_constraints={kinematic_constraints::constructGoalConstraints(goal_states[index],joints)};
    attempt.allowed_planning_time=std::min(15.,remaining);attempt.num_planning_attempts=2;
    YAML::Node record;record["family_index"]=index;record["same_elbow_wrist_signs"]=same_topology(goal_states[index]);record["allowed_planning_time_s"]=attempt.allowed_planning_time;
    planning_interface::MotionPlanResponse candidate;double cost=0;std::size_t checks=0;
    try{
     if(!pipeline.generatePlan(scene,attempt,candidate)||candidate.error_code!=moveit::core::MoveItErrorCode::SUCCESS||!candidate.trajectory)throw std::runtime_error("Candidate search failed");
     // Validate a copy: keep the geometric result for the unchanged final
     // retiming/limits/endpoint/binding gate below.
     robot_trajectory::RobotTrajectory screened(*candidate.trajectory,true);
     screen(screened,cost,checks,record);record["status"]="SCREENED_FEASIBLE";record["joint_path_length_rad"]=cost;++feasible;
     if(cost<selected_cost){selected_cost=cost;response=candidate;best=goal_states[index];output["selected_ik_family_index"]=index;}
    }catch(const std::runtime_error& failure){record["status"]="REJECTED";record["reason"]=failure.what();}
    record["screen_checks"]=checks;output["ik_candidate_attempts"].push_back(record);write();
   }
   output["ik_feasible_routes_compared"]=feasible;if(std::isfinite(selected_cost))output["ik_selected_path_length_rad"]=selected_cost;
   output["ik_search_exhaustive"]=false;output["ik_extra_attempts_after_first_feasible"]=extra_attempts;output["ik_search_budget_includes_screening"]=true;
   if(!feasible)throw std::runtime_error("No screened IK route within SIM search budget");
   output["direct_joint_path_diagnostic_goal_q_rad"]=YAML::Clone(output["goal_q_rad"]);
   output["goal_q_rad"]=std::vector<double>();for(const auto& name:joints->getVariableNames())output["goal_q_rad"].push_back(best.getVariablePosition(name));
  }
  response.trajectory->getRobotTrajectoryMsg(plan.trajectory);
  output["performance"]["ik_and_planning_wall_s"]=std::chrono::duration<double>(std::chrono::steady_clock::now()-planning_begin).count();
  const auto timing_begin=std::chrono::steady_clock::now();
  trajectory.setRobotTrajectoryMsg(start,plan.trajectory);
  // Isolate a planner collision from any change introduced by time smoothing.
  std::size_t geometric_checks=0;
  for(std::size_t i=1;i<trajectory.getWayPointCount();++i){const auto& a=trajectory.getWayPoint(i-1);const auto& b=trajectory.getWayPoint(i);double maximum=0;
   for(const auto& name:joints->getVariableNames())maximum=std::max(maximum,std::abs(a.getVariablePosition(name)-b.getVariablePosition(name)));
   int count=std::max(1,int(std::ceil(maximum/.001)));
   for(int j=0;j<=count;++j){moveit::core::RobotState state(a);a.interpolate(b,double(j)/count,state);state.update();++geometric_checks;
    collision_detection::CollisionRequest cr;cr.contacts=true;cr.max_contacts=10;collision_detection::CollisionResult collision;scene->checkCollision(cr,collision,state);
    if(collision.collision){for(const auto& pair:collision.contacts)output["collision_pairs"].push_back(pair.first.first+" / "+pair.first.second);output["collision_validation_phase"]="GEOMETRIC";output["collision_seen_by_group"]=scene->isStateColliding(state,"manipulator");output["collision_state_q_rad"]=std::vector<double>();for(const auto& name:joints->getVariableNames())output["collision_state_q_rad"].push_back(state.getVariablePosition(name));throw std::runtime_error("Geometric trajectory collision; no timing or execution issued");}
   }
  }
  output["geometric_collision_checks"]=geometric_checks;
  trajectory_processing::TimeOptimalTrajectoryGeneration timing(.00005,.01,.00001);
  output["timing_path_tolerance_rad"]=.00005;output["timing_resample_dt_s"]=.01;
  if(!timing.computeTimeStamps(trajectory,1,1))throw std::runtime_error("Time parameterization failed");
  double peak_velocity=0,peak_acceleration=0;for(std::size_t i=0;i<trajectory.getWayPointCount();++i)for(int j=1;j<=6;++j){auto name="joint_"+std::to_string(j);peak_velocity=std::max(peak_velocity,std::abs(trajectory.getWayPoint(i).getVariableVelocity(name)));peak_acceleration=std::max(peak_acceleration,std::abs(trajectory.getWayPoint(i).getVariableAcceleration(name)));}
  for(std::size_t i=1;i<trajectory.getWayPointCount();++i){const auto& a=trajectory.getWayPoint(i-1);const auto& b=trajectory.getWayPoint(i);const double dt=trajectory.getWayPointDurationFromPrevious(i);if(dt<=0)throw std::runtime_error("Non-increasing timed trajectory");
   std::vector<std::array<double,6>> coefficients;for(const auto& name:joints->getVariableNames())coefficients.push_back(quintic(a,b,name,dt));
   for(const auto& c:coefficients){const auto peaks=quintic_motion_peaks(c,dt);peak_velocity=std::max(peak_velocity,peaks[0]);peak_acceleration=std::max(peak_acceleration,peaks[1]);}
  }
  double scale=std::max({1.0,peak_velocity/.35,std::sqrt(peak_acceleration/.7)})*1.01;
  for(std::size_t i=0;i<trajectory.getWayPointCount();++i){trajectory.setWayPointDurationFromPrevious(i,trajectory.getWayPointDurationFromPrevious(i)*scale);for(int j=1;j<=6;++j){auto name="joint_"+std::to_string(j);auto& point=*trajectory.getWayPointPtr(i);point.setVariableVelocity(name,point.getVariableVelocity(name)/scale);point.setVariableAcceleration(name,point.getVariableAcceleration(name)/(scale*scale));}}
  output["time_dilation_factor"]=scale;output["peak_velocity_rad_s"]=peak_velocity/scale;output["peak_acceleration_rad_s2"]=peak_acceleration/(scale*scale);
  trajectory.getRobotTrajectoryMsg(plan.trajectory);
  output["trajectory_points"]=trajectory.getWayPointCount();output["planned_duration_s"]=trajectory.getDuration();
  // Recheck the actual timed trajectory after smoothing, including held studs.
  output["performance"]["time_parameterization_wall_s"]=std::chrono::duration<double>(std::chrono::steady_clock::now()-timing_begin).count();
  }else{
   const auto timed=imported["trajectory"];const auto* group=model->getJointModelGroup("manipulator");
   const auto names=timed["joint_names"].as<std::vector<std::string>>();
   if(names!=group->getVariableNames()||timed["points"].size()<2)throw std::runtime_error("EXTERNAL_ORDERED_TIMED_POINTS_REQUIRED");
   plan.trajectory.joint_trajectory.joint_names=names;double previous=-1;
   for(std::size_t index=0;index<timed["points"].size();++index){const auto row=timed["points"][index];trajectory_msgs::msg::JointTrajectoryPoint point;
    point.positions=row["positions_rad"].as<std::vector<double>>();point.velocities=row["velocities_rad_s"].as<std::vector<double>>();point.accelerations=row["accelerations_rad_s2"].as<std::vector<double>>();
    const double t=row["time_from_start_s"].as<double>();
    if(!std::isfinite(t)||t<=previous||(index==0&&t!=0)||t>3600||point.positions.size()!=6||point.velocities.size()!=6||point.accelerations.size()!=6)throw std::runtime_error("EXTERNAL_INVALID_TIME_OR_VECTOR");
    for(int j=0;j<6;++j){if(!std::isfinite(point.positions[j])||!std::isfinite(point.velocities[j])||!std::isfinite(point.accelerations[j])||std::abs(point.velocities[j])>.350001||std::abs(point.accelerations[j])>.700001)throw std::runtime_error("EXTERNAL_NONFINITE_OR_LIMIT_VIOLATION");
     if(index==0&&std::abs(point.positions[j]-state_data["q_rad"][j].as<double>())>1e-6)throw std::runtime_error("EXTERNAL_START_CHANGED");
     if(index+1==timed["points"].size()&&std::abs(point.velocities[j])>1e-6)throw std::runtime_error("EXTERNAL_NONZERO_TERMINAL_VELOCITY");}
    point.time_from_start=rclcpp::Duration::from_seconds(t);plan.trajectory.joint_trajectory.points.push_back(point);previous=t;
   }
   trajectory.setRobotTrajectoryMsg(start,plan.trajectory);
   output["timing_engine"]=imported["scope"].as<std::string>()=="FILE_ONLY_EXTERNAL_TIMED_ADAPTER_FIXTURE"?"EXTERNAL_ADAPTER_FIXTURE_NO_TOTG":"CUMOTION_NATIVE_NO_TOTG";
   if(imported["timing_engine"]){
    const auto engine=imported["timing_engine"].as<std::string>();
    if(engine=="CUMOTION_SDK_CSPACE_SPLINE_RETIMED_NO_TOTG"){
     if(!imported["native_timing_changed"]||!imported["native_timing_changed"].as<bool>()||!imported["timing_metadata"])throw std::runtime_error("EXPLICIT_SPLINE_RETIMING_METADATA_REQUIRED");
     output["timing_engine"]=engine;output["native_timing_changed"]=true;output["timing_metadata"]=imported["timing_metadata"];
    }else if(engine!="CUMOTION_NATIVE_NO_TOTG")throw std::runtime_error("UNKNOWN_EXTERNAL_TIMING_ENGINE");
   }
   output["trajectory_points"]=trajectory.getWayPointCount();output["planned_duration_s"]=trajectory.getDuration();
  }
  const auto validation_begin=std::chrono::steady_clock::now();double collision_wall=0,record_wall=0;
  const auto* jmg=model->getJointModelGroup("manipulator");std::size_t checked=0,distance_checks=0;double minimum=std::numeric_limits<double>::infinity();
  for(std::size_t i=0;i<trajectory.getWayPointCount();++i){
   const auto& a=trajectory.getWayPoint(i?i-1:i);const auto& b=trajectory.getWayPoint(i);const double dt=i?trajectory.getWayPointDurationFromPrevious(i):0;
   std::vector<std::array<double,6>> coefficients;if(i)for(const auto& name:jmg->getVariableNames())coefficients.push_back(quintic(a,b,name,dt));
   const int count=i?timed_samples(coefficients,dt):1;
   for(int sample=0;sample<=count;++sample){moveit::core::RobotState state(a);if(i){int joint=0;for(const auto& name:jmg->getVariableNames()){const auto& c=coefficients[joint++];state.setVariablePosition(name,polynomial(c,double(sample)/count));
    const std::array<double,3> values={polynomial(c,double(sample)/count,1)/dt,polynomial(c,double(sample)/count,2)/(dt*dt),polynomial(c,double(sample)/count,3)/(dt*dt*dt)};
    const std::array<double,3> limits={.350001,.700001,5.00001};
    const std::array<std::string,3> quantities={"velocity_rad_s","acceleration_rad_s2","jerk_rad_s3"};
    for(int order=0;order<(external?3:2);++order)if(std::abs(values[order])>limits[order]){
     auto failure=output["interpolation_limit_violation"];failure["joint"]=name;failure["quantity"]=quantities[order];
     failure["value"]=values[order];failure["absolute_limit"]=limits[order];failure["interval_index"]=i-1;
     failure["interval_duration_s"]=dt;failure["time_from_start_s"]=trajectory.getWayPointDurationFromStart(i-1)+double(sample)/count*dt;
     failure["sample_index"]=sample;failure["samples_in_interval"]=count;
     throw std::runtime_error("Interpolated timed trajectory exceeds limits");
    }
   }}state.update();
    if(!constraints.orientation_constraints.empty()&&!scene->isStateConstrained(state,constraints)){
     output["holding_violation"]["time_from_start_s"]=trajectory.getWayPointDurationFromStart(i?i-1:0)+double(sample)/count*dt;
     output["holding_violation"]["tcp_matrix"]=matrix(state.getGlobalLinkTransform("GripperDA_v4_tcp"));
     for(const auto& name:jmg->getVariableNames())output["holding_violation"]["q_rad"].push_back(state.getVariablePosition(name));
     throw std::runtime_error("Timed trajectory violates holding orientation");
    }
    if(!state.satisfiesBounds())throw std::runtime_error("Timed trajectory bounds violation");
    collision_detection::CollisionRequest cr;cr.contacts=true;cr.max_contacts=10;cr.distance=(checked%100==0)||(sample==count&&i+1==trajectory.getWayPointCount());if(cr.distance)++distance_checks;collision_detection::CollisionResult result;const auto collision_begin=std::chrono::steady_clock::now();scene->checkCollision(cr,result,state);collision_wall+=std::chrono::duration<double>(std::chrono::steady_clock::now()-collision_begin).count();checked++;
    if(result.collision){for(const auto& pair:result.contacts){output["collision_pairs"].push_back(pair.first.first+" / "+pair.first.second);}output["collision_validation_phase"]="TIMED";output["collision_state_q_rad"]=std::vector<double>();for(const auto& name:jmg->getVariableNames())output["collision_state_q_rad"].push_back(state.getVariablePosition(name));throw std::runtime_error("Timed trajectory collision; no execution issued");}
    if(cr.distance)minimum=std::min(minimum,result.distance);
    const auto record_begin=std::chrono::steady_clock::now();record_checked_state(checked_stream,state,jmg,trajectory.getWayPointDurationFromStart(i?i-1:0)+double(sample)/count*dt);record_wall+=std::chrono::duration<double>(std::chrono::steady_clock::now()-record_begin).count();
   }
  }
  output["performance"]["validation_wall_s"]=std::chrono::duration<double>(std::chrono::steady_clock::now()-validation_begin).count();output["performance"]["collision_distance_wall_s"]=collision_wall;output["performance"]["state_record_wall_s"]=record_wall;
  output["post_timing_collision_checks"]=checked;output["max_joint_check_interval_rad"]=.001;output["minimum_sampled_distance_m"]=minimum;output["distance_diagnostic_samples"]=distance_checks;output["distance_diagnostic_stride_states"]=100;output["distance_is_diagnostic_only"]=true;
  const auto target=transform(pose(req["goal"]));
  const auto endpoint=trajectory.getLastWayPoint().getGlobalLinkTransform("GripperDA_v4_tcp");
  output["endpoint_position_error_m"]=(endpoint.translation()-target.translation()).norm();output["endpoint_orientation_error_rad"]=Eigen::AngleAxisd(target.linear().transpose()*endpoint.linear()).angle();
  if(output["endpoint_position_error_m"].as<double>()>.0008||output["endpoint_orientation_error_rad"].as<double>()>.005)throw std::runtime_error("Timed endpoint differs from pre-contact target");
  output["validated_target"]=YAML::Clone(req["goal"]);output["planned_attachment"]=YAML::Clone(req["attachment"]);
  output["endpoint_validation_passed"]=true;output["plan_success"]=true;output["calculation_stage"]="TIMED_VALIDATION_PASSED";check_contract();
  // Preserve every timed point for D receive-only contract tests.
  YAML::Node timed;timed["joint_names"]=plan.trajectory.joint_trajectory.joint_names;
  for(const auto& point:plan.trajectory.joint_trajectory.points){YAML::Node p;p["positions_rad"]=point.positions;p["velocities_rad_s"]=point.velocities;p["accelerations_rad_s2"]=point.accelerations;p["time_from_start_s"]=point.time_from_start.sec+point.time_from_start.nanosec*1e-9;timed["points"].push_back(p);}
  output["planned_trajectory"]=timed;
  auto binding=YAML::LoadFile(run+"/scene_context.json");
  // JSON's quoted numeric strings must remain strings in emitted YAML.
  for(auto item:binding)if(item.second.Tag()=="!")item.second.SetTag("tag:yaml.org,2002:str");
  output["binding"]=binding;output["model_digest"]=req["model_digest"];
  output["handoff_to"]="D_CONTACT";output["terminal_gripper_policy"]="HOLD_NO_AUTOMATIC_OPEN";
  output["start_drift_check_owner"]="D_BEFORE_EXECUTION";check_contract();write();rclcpp::shutdown();return 0;
 }catch(const std::exception& e){output["plan_success"]=false;output["calculation_stage"]="REJECTED";output["error"]=e.what();write();std::cerr<<e.what()<<'\n';if(rclcpp::ok())rclcpp::shutdown();return 1;}
}
