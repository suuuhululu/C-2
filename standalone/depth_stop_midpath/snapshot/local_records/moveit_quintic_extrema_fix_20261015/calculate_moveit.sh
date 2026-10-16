#!/bin/bash
set -eo pipefail
unset LD_LIBRARY_PATH PYTHONPATH AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH SEEUN_CHAIR_PLANNING_SECONDS SEEUN_CHAIR_PLANNING_FRACTION
source /opt/ros/jazzy/setup.bash
exec '/home/ms-02/Documents/ChatGPT/협동2_장애물회피/local_records/moveit_quintic_extrema_fix_20261015/build/moveit_plan_only' "$@"
