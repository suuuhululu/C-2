"""SIM-only launch: measured joint states and sim clock; no fake publisher."""
from pathlib import Path
import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument,OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def launch(context):
    root=Path(LaunchConfiguration('root').perform(context));model=root/'ros_ws/src/m0609_rg2_sim_model'
    def load(path):return yaml.safe_load(path.read_text())
    common={'robot_description':(root/'config/robot.urdf').read_text(),
            'robot_description_semantic':(model/'config/m0609_rg2_sim.srdf').read_text(),
            'robot_description_kinematics':load(model/'config/kinematics.yaml'),
            'robot_description_planning':load(root/'config/joint_limits.sim.yaml'),
            'use_sim_time':True}
    pipelines={'planning_pipelines':['ompl'],'default_planning_pipeline':'ompl','ompl':load(root/'config/ompl.yaml')}
    return [
      Node(package='robot_state_publisher',executable='robot_state_publisher',name='sim_robot_state_publisher',
           parameters=[{'robot_description':common['robot_description'],'use_sim_time':True}],
           remappings=[('/joint_states','/sim/m0609/joint_states')]),
      Node(package='moveit_ros_move_group',executable='move_group',name='move_group',output='screen',
           parameters=[common,pipelines,load(root/'config/moveit_controllers.yaml'),
                       {'allow_trajectory_execution':True,'publish_robot_description_semantic':True,
                        'publish_planning_scene':True,'publish_geometry_updates':True,
                        'publish_state_updates':True,'publish_transforms_updates':True}],
           remappings=[('/joint_states','/sim/m0609/joint_states')])]

def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument('root'),OpaqueFunction(function=launch)])
