"""실기 bringup과 기존 TCP/Tool 선택을 함께 실행한다."""
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    root = Path(__file__).resolve().parents[1]
    robot_root = Path('/home/ms-02/C-2_협동2자료/work/c2-virtual-inputs-20261011/D_robot_control_integration_20261011/robot_control_integration_20261010')
    bringup = Path(get_package_share_directory('m0609_rg2_bringup'))/'launch/bringup.launch.py'
    return LaunchDescription([
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(bringup)), launch_arguments={
            'mode': 'real', 'host': '192.168.1.100', 'port': '12345',
            'camera': 'false', 'rviz': 'false'}.items()),
        ExecuteProcess(cmd=['python3', str(root/'scripts/robot_driver_setup.py'),
            '--config', str(robot_root/'interfaces/assembly_contact_trial.json')], output='screen'),
    ])
