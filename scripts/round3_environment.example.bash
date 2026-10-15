# source this file after setting the three paths for this computer.
# Environment selection only; no Robot/Camera/Gripper commands.
export C2_PROJECT_ROOT="${C2_PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
export C2_ROS_WS="${C2_ROS_WS:-$HOME/cobot2_ws}"
export C2_DRIVER_ROOT="${C2_DRIVER_ROOT:-$HOME/c2-drcf2}"
export C2_APP_VENV="${C2_APP_VENV:-$C2_PROJECT_ROOT/.venv}"

for c2_round3_required in /opt/ros/jazzy/setup.bash \
    "$C2_ROS_WS/install/local_setup.bash" \
    "$C2_DRIVER_ROOT/install/local_setup.bash" "$C2_APP_VENV/bin/activate"; do
    if [[ ! -f "$c2_round3_required" ]]; then
        printf 'Required environment file missing: %s\n' "$c2_round3_required" >&2
        return 1
    fi
done
unset c2_round3_required
source /opt/ros/jazzy/setup.bash || return
source "$C2_ROS_WS/install/local_setup.bash" || return
COLCON_CURRENT_PREFIX="$C2_DRIVER_ROOT/install" source "$C2_DRIVER_ROOT/install/local_setup.bash" || return
source "$C2_APP_VENV/bin/activate" || return
export C2_ROBOT_ROOT="$C2_PROJECT_ROOT/robot_control_integration"
export ROS_DOMAIN_ID=20
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
cd "$C2_PROJECT_ROOT" || return
