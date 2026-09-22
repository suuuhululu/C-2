#!/usr/bin/env bash
set -e
TASK_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMMON_ROOT="$(dirname "$(git -C "$TASK_ROOT" rev-parse --path-format=absolute --git-common-dir)")"
source /opt/ros/jazzy/setup.bash
if [ -f "$TASK_ROOT/ws_cobot_pjt/ws_cobot1/install/local_setup.bash" ]; then
  source "$TASK_ROOT/ws_cobot_pjt/ws_cobot1/install/local_setup.bash"
elif [ -f "$COMMON_ROOT/ws_cobot_pjt/ws_cobot1/install/local_setup.bash" ]; then
  source "$COMMON_ROOT/ws_cobot_pjt/ws_cobot1/install/local_setup.bash"
else
  echo '먼저 ws_cobot_pjt/ws_cobot1에서 colcon build --packages-select c2_interfaces를 실행하세요.' >&2
  exit 1
fi
TASK_PYTHON="${C2_PYTHON:-$TASK_ROOT/ws_cobot_pjt/backend/.venv/bin/python}"
if [ ! -x "$TASK_PYTHON" ]; then TASK_PYTHON="$COMMON_ROOT/ws_cobot_pjt/backend/.venv/bin/python"; fi
if [ "${1:-}" = "--check" ]; then
  shift
  exec "$TASK_PYTHON" "$TASK_ROOT/ws_cobot_pjt/tools/check_virtual_cell.py" "$@"
fi
exec "$TASK_PYTHON" "$TASK_ROOT/ws_cobot_pjt/tools/run_virtual_cell.py" "$@"
