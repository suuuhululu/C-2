#!/usr/bin/env bash
set -eo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
export PYTHONPATH="$ROOT/python_deps${PYTHONPATH:+:$PYTHONPATH}"
source "${ROS_SETUP_PATH:-/opt/ros/jazzy/setup.bash}"
"${SIM_PYTHON:-python3}" scripts/prepare_config.py
colcon --log-base ros_ws/log build --base-paths ros_ws/src --build-base ros_ws/build --install-base ros_ws/install --cmake-args -DCMAKE_BUILD_TYPE=Release
