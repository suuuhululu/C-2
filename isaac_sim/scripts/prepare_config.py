from pathlib import Path
import xml.etree.ElementTree as ET
import yaml
ROOT=Path(__file__).resolve().parents[1]
model=ROOT/'ros_ws/src/m0609_rg2_sim_model'
robot=ET.parse(model/'urdf/m0609_rg2_sim.urdf').getroot()
for mesh in robot.findall('.//mesh'):
    mesh.set('filename',(model/mesh.get('filename').split('package://m0609_rg2_sim_model/')[1]).as_uri())
ET.indent(robot);ET.ElementTree(robot).write(ROOT/'config/robot.urdf',encoding='utf-8',xml_declaration=True)
limits=yaml.safe_load((model/'config/joint_limits.yaml').read_text())
limits['default_velocity_scaling_factor']=1.0;limits['default_acceleration_scaling_factor']=1.0
for name,limit in limits['joint_limits'].items():
    if name.startswith('joint_'):
        limit.update(max_velocity=.35,has_acceleration_limits=True,max_acceleration=.7)
(ROOT/'config/joint_limits.sim.yaml').write_text(yaml.safe_dump(limits,sort_keys=False))
(ROOT/'config/ompl.yaml').write_text(yaml.safe_dump({
 'planning_plugins':['ompl_interface/OMPLPlanner'],
 'request_adapters':['default_planning_request_adapters/ResolveConstraintFrames','default_planning_request_adapters/ValidateWorkspaceBounds','default_planning_request_adapters/CheckStartStateBounds','default_planning_request_adapters/CheckStartStateCollision'],
 'response_adapters':['default_planning_response_adapters/AddTimeOptimalParameterization','default_planning_response_adapters/ValidateSolution','default_planning_response_adapters/DisplayMotionPath'],
 'planner_configs':{'RRTConnect':{'type':'geometric::RRTConnect','range':.12}},
 'manipulator':{'planner_configs':['RRTConnect'],'default_planner_config':'RRTConnect','longest_valid_segment_fraction':.0001,'maximum_waypoint_distance':.001},
},sort_keys=False))
(ROOT/'config/moveit_controllers.yaml').write_text(yaml.safe_dump({
 'moveit_controller_manager':'moveit_simple_controller_manager/MoveItSimpleControllerManager',
 'moveit_simple_controller_manager':{'controller_names':['/sim/m0609/arm_controller'],
 '/sim/m0609/arm_controller':{'type':'FollowJointTrajectory','action_ns':'follow_joint_trajectory','default':True,'joints':[f'joint_{i}' for i in range(1,7)]}},
 'trajectory_execution':{'allowed_start_tolerance':.02,'allowed_execution_duration_scaling':2.0,'allowed_goal_duration_margin':10.0},
},sort_keys=False))
print('SIM MoveIt config prepared')
