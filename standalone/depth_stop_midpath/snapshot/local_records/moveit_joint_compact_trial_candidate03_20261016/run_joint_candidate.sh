#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASK_ALLOCATION="${2:?Pass a separately granted new allocation JSON; no allocation is created by this script}"
case "${1:-}" in preflight|run) ;; *) exit 2 ;; esac
python3 "$TASK_ROOT/local_records/moveit_joint_compact_trial_candidate03_20261016/prepare_implementation_handoff.py" "${1}" "$TASK_ALLOCATION"
export ROS_DOMAIN_ID=194
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export DISPLAY=:1
export PYTHONPATH="$TASK_ROOT/local_records/step6_cumotion_20261014/venv/lib/python3.12/site-packages:/home/ms-02/isaacsim/extscache/omni.cip.pip-2.1.2+lx64.cp312/pip_prebundle:$TASK_ROOT/work/C-2-moveit:$TASK_ROOT/work/C-2-moveit/isaac_sim/scripts:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="/home/ms-02/isaacsim/exts/isaacsim.ros2.core/jazzy/lib:${LD_LIBRARY_PATH:-}"
if [[ "${1:-run}" == preflight ]]; then
 TASK_OUT="$TASK_ROOT/local_records/moveit_joint_compact_trial_candidate03_20261016/runtime_preflight"
else
 TASK_OUT="$TASK_ROOT/local_records/moveit_joint_compact_trial_candidate03_20261016/native_joint03"
 test -f "$TASK_ROOT/local_records/moveit_joint_compact_trial_candidate03_20261016/implementation_handoff.json"
fi
ARGS=(--joint-current-inputs --compact-stop-handoff --current-stop-providers --bounded-stop-video --command-start-planning --cpp-depth-interval-manifest "$TASK_ROOT/local_records/moveit_interval_kernel_integration_20261015/interval_manifest.json" --sim-stop-owner-limits "$TASK_ROOT/local_records/moveit_stop_owner_publication_20261015/owner_limits.json" --cpp-depth-raster-manifest "$TASK_ROOT/local_records/moveit_cpp_kernel_integration_20261015/kernel_manifest.json" --foreground-stop-max-source-age-s .4 --foreground-python-switch-interval-ms 1 --fresh-foreground-stop --sim-command-profile SIM_FAST_J20 --source-render-every-physics-steps 4 --same-runtime-worker-handoff "$TASK_ROOT/management/reports/rosbridge_same_runtime_worker_handoff.json" --root "$TASK_ROOT" --out "$TASK_OUT" --transport-calculator "$TASK_ROOT/local_records/moveit_command_start_plan_20261016/calculate_moveit.sh" --bootstrap-gripper-wall-budget-s 120 --show-wrist-camera --source-depth-baseline --direct-camera-display --unlabelled-static-shadow --allocation "$TASK_ALLOCATION" --qualification-report-path "$TASK_ROOT/management/reports/depth_native12_source_qualification.json" --pre-obstacle-handoff-public-path "$TASK_ROOT/local_records/moveit_joint_compact_trial_candidate03_20261016/pre_obstacle_handoff.json")
if [[ "${1:-run}" == preflight ]]; then
 exec python3 "$TASK_ROOT/work/C-2-moveit/isaac_sim/scripts/run_depth_stop_native.py" "${ARGS[@]}" --runtime-preflight-only
else
 exec python3 "$TASK_ROOT/local_records/moveit_launch_capture_preparation_20261016/staged_v3/observe_launch.py" --scope EXPLICIT_ISOLATED_SIM_STARTUP_DIAGNOSTIC --out "$TASK_ROOT/local_records/moveit_joint_compact_trial_candidate03_20261016/launch_diagnostics" --sdk-log "$TASK_ROOT/local_records/moveit_joint_compact_trial_candidate03_20261016/native_joint03.sdk.log" --native-process-record "$TASK_OUT/native_process.json" -- /home/ms-02/isaacsim/python.sh "$TASK_ROOT/work/C-2-moveit/isaac_sim/scripts/run_depth_stop_native.py" "${ARGS[@]}"
fi
