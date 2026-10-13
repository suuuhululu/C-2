#!/usr/bin/env bash
# ms-02 전용 환경. driver/real/voice/stack을 명시했을 때만 실제 장치에 연결한다.
set -eo pipefail
TASK_C2_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [ -f /home/ms-02/.config/c2/api.env ]; then
    source /home/ms-02/.config/c2/api.env
fi
if [ -f /home/ms-02/.config/c2/models.env ]; then
    source /home/ms-02/.config/c2/models.env
fi
TASK_ROBOT_ROOT=${C2_ROBOT_ROOT:-"$TASK_C2_ROOT/robot_control_integration"}
TASK_DRIVER_ROOT=${C2_DRIVER_ROOT:-'/home/ms-02/C-2_협동2자료/work/c2-virtual-inputs-20261011/D_robot_control_integration_20261011/robot_control_integration_20261010/runtime/drcf2'}
source /opt/ros/jazzy/setup.bash
source /home/ms-02/cobot2_ws/install/local_setup.bash
COLCON_CURRENT_PREFIX="$TASK_DRIVER_ROOT/install" source "$TASK_DRIVER_ROOT/install/local_setup.bash"
export ROS_DOMAIN_ID=20 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
cd "$TASK_C2_ROOT"
python3 - "$TASK_DRIVER_ROOT" <<'PY'
import hashlib, json, sys
from pathlib import Path
from ament_index_python.packages import get_package_prefix
from dsr_msgs2 import srv
from PyQt5.QtWidgets import QApplication
import pymodbus, sounddevice
root = Path(sys.argv[1])
ready = json.loads((root/'READY.json').read_text())
for name in ('dsr_hardware2', 'dsr_controller2'):
    expected = root/'install'/name
    if Path(get_package_prefix(name)).resolve() != expected.resolve():
        raise RuntimeError('DRCF2_OVERLAY_NOT_SELECTED:'+name)
    library = expected/'lib'/('lib'+name+'.so')
    if hashlib.sha256(library.read_bytes()).hexdigest() != ready['libraries'][name]['sha256']:
        raise RuntimeError('DRIVER_CHANGED_RECHECK_REQUIRED:'+name)
print('ms-02 DRCF2 환경 확인 · 장치 연결/움직임 없음')
PY
TASK_COMMAND=${1:---check}
if [ "$#" -gt 0 ]; then shift; fi
case "$TASK_COMMAND" in
    --check) exit 0 ;;
    driver)
        if pgrep -f '^/opt/ros/jazzy/lib/controller_manager/ros2_control_node .*__ns:=/dsr01' >/dev/null; then
            echo 'dsr01 드라이버가 이미 실행 중입니다. 중복 실행하지 않습니다.' >&2
            exit 2
        fi
        exec ros2 launch "$TASK_C2_ROOT/scripts/roboton2.launch.py"
        ;;
    prepare|real)
        export C_DESIGN_USE_LLM=0
        TASK_DESIGN=${1:-interfaces/fixtures/cad_trial_yellow_blue_five_layers.json}
        if [ "$#" -gt 0 ]; then shift; fi
        TASK_EXTRA=()
        if [ "$TASK_COMMAND" = real ]; then TASK_EXTRA=(--execute); fi
        exec python3 -m app.cad_real_trial --robot-root "$TASK_ROBOT_ROOT" --design "$TASK_DESIGN" "${TASK_EXTRA[@]}" "$@"
        ;;
    full-real|full-real-offline)
        export C_DESIGN_USE_LLM=1
        TASK_C_MODE=live
        if [ "$TASK_COMMAND" = full-real-offline ]; then
            export C_DESIGN_USE_LLM=0
            TASK_C_MODE=offline
        fi
        exec python3 -m app.mvp_real_trial --robot-root "$TASK_ROBOT_ROOT" --execute --c-mode "$TASK_C_MODE" --log-directory logs/full-feature-real "$@"
        ;;
    teach)
        exec python3 -m app.robot_teaching --robot-root "$TASK_ROBOT_ROOT" "$@"
        ;;
    voice)
        export C_DESIGN_USE_LLM=1
        exec python3 -m app.cad_real_trial --robot-root "$TASK_ROBOT_ROOT" --voice --execute "$@"
        ;;
    stack)
        export C_DESIGN_USE_LLM=1
        exec python3 -m app.cad_real_trial --robot-root "$TASK_ROBOT_ROOT" --design interfaces/fixtures/cad_trial_yellow_blue_five_layers.json --llm-context --execute "$@"
        ;;
    *) echo '사용: bash scripts/cad_trial_ms02.sh --check|driver|prepare|real [설계파일]|voice|stack [--voice]|full-real|full-real-offline|teach [--section supply|assembly|handover|route|all]' >&2; exit 2 ;;
esac
