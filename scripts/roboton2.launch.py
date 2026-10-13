"""실기 bringup과 기존 TCP/Tool 선택을 함께 실행한다."""
import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    root = Path(__file__).resolve().parents[1]
    robot_root = Path(os.environ.get('C2_ROBOT_ROOT', root/'robot_control_integration')).resolve()
    bringup = Path(get_package_share_directory('m0609_rg2_bringup'))/'launch/bringup.launch.py'
    return LaunchDescription([
        DeclareLaunchArgument('camera', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('rviz', default_value='false', choices=['true', 'false']),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(bringup)), launch_arguments={
            'mode': 'real', 'host': '192.168.1.100', 'port': '12345',
            'camera': LaunchConfiguration('camera'), 'rviz': LaunchConfiguration('rviz')}.items()),
        ExecuteProcess(cmd=['python3', str(root/'scripts/robot_driver_setup.py'),
            '--config', str(robot_root/'interfaces/assembly_contact_trial.json')], output='screen'),
    ])
