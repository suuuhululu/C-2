#!/usr/bin/env bash
set -eo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
if [ "${1:-}" = --help ]; then
 echo 'RUN_SIM.sh [--scenario red|chair] [--headless] [--auto-start] [--auto-human]'
 echo 'Set ISAAC_SIM_ROOT, ROS_SETUP_PATH, SIM_PYTHON as needed. Build with bash BUILD.sh first.'
 exit 0
fi
export ISAAC_SIM_ROOT="${ISAAC_SIM_ROOT:-$HOME/isaacsim}"
SIM_PYTHON="${SIM_PYTHON:-python3}"
export PYTHONPATH="$ROOT/python_deps${PYTHONPATH:+:$PYTHONPATH}"
[ -x "$ISAAC_SIM_ROOT/python.sh" ] || { echo "Isaac python.sh missing: $ISAAC_SIM_ROOT"; exit 1; }
[ -f "$ROOT/ros_ws/install/setup.bash" ] || { echo 'Local ROS build missing; run bash BUILD.sh first'; exit 1; }
source "${ROS_SETUP_PATH:-/opt/ros/jazzy/setup.bash}"
source "$ROOT/ros_ws/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}" ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
exec 9>"$ROOT/session.lock"
flock -n 9 || { echo 'Chair SIM already running'; exit 1; }
if ros2 service list --no-daemon --spin-time 2 | rg -q '^/get_planning_scene$'; then
 echo "An isolated domain $ROS_DOMAIN_ID MoveIt session is already active"; exit 1
fi
HOST_ARGS=()
ADAPTER_ARGS=()
PREP_ARGS=()
SCENARIO=red
while [ "$#" -gt 0 ]; do
 value=$1;shift
 if [ "$value" = --auto-human ]; then ADAPTER_ARGS+=(--auto-human)
 elif [ "$value" = --manual-regression-from ]; then PREP_ARGS+=("$value" "$1");shift
 elif [ "$value" = --scenario ]; then SCENARIO=$1;shift
 else HOST_ARGS+=("$value"); fi
done
case "$SCENARIO" in
 red) PREP_ARGS+=(--whole-request "$ROOT/config/whole.complete_first.request.json");;
 chair) PREP_ARGS+=(--whole-request "$ROOT/config/whole.chair.regression.request.json");;
 *) echo 'Scenario must be red or chair';exit 1;;
esac
RUN="$ROOT/runs/chair_$(TZ=Asia/Seoul date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN"
printf '%s\n' "$RUN" > latest_run.txt
"$SIM_PYTHON" scripts/prepare_scenario.py --run-dir "$RUN" "${PREP_ARGS[@]}" >"$RUN/prepare.log" 2>&1
SIM_PID= MOVEIT_PID= ADAPTER_PID=
cleanup() {
 [ -z "$ADAPTER_PID" ] || kill -TERM -- "-$ADAPTER_PID" 2>/dev/null || true
 [ -z "$MOVEIT_PID" ] || kill -TERM -- "-$MOVEIT_PID" 2>/dev/null || true
 touch "$RUN/shutdown.request"
}
trap cleanup EXIT INT TERM
(
 exec 9>&-
 export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$ISAAC_SIM_ROOT/exts/isaacsim.ros2.core/jazzy/lib"
 exec "$ISAAC_SIM_ROOT/python.sh" scripts/sim_host.py --run-dir "$RUN" "${HOST_ARGS[@]}"
) >"$RUN/host.log" 2>&1 &
SIM_PID=$!
"$SIM_PYTHON" - "$RUN" "$SIM_PID" <<'PY'
import json,os,sys,time
from pathlib import Path
run=Path(sys.argv[1]);pid=int(sys.argv[2]);end=time.monotonic()+100
while time.monotonic()<end:
 os.kill(pid,0)
 if (run/'host_failure.json').exists():raise SystemExit((run/'host_failure.json').read_text())
 if (run/'host_status.json').exists() and json.loads((run/'host_status.json').read_text()).get('ready'):break
 time.sleep(.2)
else:raise SystemExit('Isaac readiness timed out; see host.log')
PY
setsid ros2 launch m0609_moveit_sim sim_moveit.launch.py root:="$ROOT" >"$RUN/move_group.log" 2>&1 9>&- &
MOVEIT_PID=$!
setsid "$SIM_PYTHON" scripts/run_chair.py --run-dir "$RUN" "${ADAPTER_ARGS[@]}" >"$RUN/adapter.log" 2>&1 9>&- &
ADAPTER_PID=$!
printf 'Chair SIM ready: %s\n' "$RUN"
wait "$SIM_PID"
