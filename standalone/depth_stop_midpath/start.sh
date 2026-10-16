#!/bin/bash
set -eo pipefail
TASK_PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" != --help && "${1:-}" != -h ]]; then
 source /opt/ros/jazzy/setup.bash
 export ROS_DOMAIN_ID=194
 export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
fi
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$TASK_PACKAGE_DIR/tools/launcher.py" "$@"
