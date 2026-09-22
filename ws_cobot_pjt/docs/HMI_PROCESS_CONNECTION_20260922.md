> 9/22 HMI 작업 변경: [REAL 실행 연결 계약](HMI_REAL_EXECUTION_20260922.md). 아래의 REAL 측정 전용 설명은 이전 기준이며, 현재 작업 브랜치는 BIND·생성·실행 요청을 연결한다. 상대 PR과 실기 검증은 별도다.

# 9/22 최신 공정 노드와 HMI 연결

기준: main `c29de08`(PR #61). `codex/hmi-partial-integration`에 `git pull --ff-only origin main` 반영. 기존 HMI 수정 보존. 원래 `/home/rokey/cobot1`의 미커밋 main은 변경하지 않았다.

## 1. 최초 빌드

```bash
cd /tmp/c2-hmi-partial-integration/ws_cobot_pjt/ws_cobot1
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
colcon build --packages-select c2_interfaces c2_path c2_process --symlink-install
```

빌드 실패 시 다음 단계로 진행하지 않는다. 이 안내는 현재 PC의 기존 Python 가상환경과 빌드된 frontend/dist를 사용한다.

## 2. 이후 모든 터미널 공통 설정

```bash
cd /tmp/c2-hmi-partial-integration
source /opt/ros/jazzy/setup.bash
source /home/rokey/ws_cobot_pjt/ws_dsr/install/setup.bash
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash
export ROS_DOMAIN_ID=20
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

기존 드라이버도 위 domain/RMW로 실행 중이어야 한다. 같은 PC `/dsr01/dsr_controller2` 기준이다. 드라이버가 다른 domain을 쓰면 모든 터미널을 그 값으로 맞춘다. 드라이버를 중복 기동하지 않는다. 이전 MOCK HMI의 8010 포트 점유를 해제하고, 같은 `/c2` Action을 제공하는 기존 공정 노드를 중복 실행하지 않는다. 동작 중인 공정은 실제 정지 확인 후 전환한다.

## 3. 터미널 A — HMI

공통 설정 후:

```bash
export C2_MONITOR_MODE=REAL
export C2_MONITOR_TRANSPORT=ros
export C2_IMAGE_WORKFLOW=1
export C2_ROS_EXECUTION_SIM=0
export C2_MONITOR_DATA=/tmp/c2-hmi-partial-integration/ws_cobot_pjt/backend/monitor_data/real_process
export C2_PREPARATION_CONFIG=/tmp/c2-hmi-partial-integration/ws_cobot_pjt/ws_cobot1/src/c2_process/config/workpiece_real_trial_0921.json
mkdir -p "$C2_MONITOR_DATA"
/home/rokey/cobot1/ws_cobot_pjt/backend/.venv/bin/python -m uvicorn app.monitor:app   --app-dir ws_cobot_pjt/backend --host 127.0.0.1 --port 8010
```

브라우저: http://127.0.0.1:8010/operator
선택한 JSON은 최신 main에 반영된 20 mm 접촉 오프셋·150 mm 양초 높이 설정이다. ZIP 업로드는 없다. 실제 측정 전 장착·TCP·하중·양초 조건과 선택한 설정의 일치 여부를 확인한다.

## 4. 터미널 B — 세은의 새 공정 노드

공통 설정 후:

```bash
mkdir -p ws_cobot_pjt/backend/monitor_data/real_process
ros2 run c2_process real_process_node   --preparation-backend-url http://127.0.0.1:8010   --preparation-journal-path /tmp/c2-hmi-partial-integration/ws_cobot_pjt/backend/monitor_data/real_process/preparation.sqlite3   --execution-journal-path /tmp/c2-hmi-partial-integration/ws_cobot_pjt/backend/monitor_data/real_process/execution.sqlite3   --controller-prefix /dsr01/dsr_controller2   --control-authority-topic /dsr01/dsr_controller2/control_authority   --ros-args -r __ns:=/dsr01
```

`real_preparation_node`와 함께 띄우지 않는다. 새 노드가 준비와 실행을 함께 제공한다. HMI 자산 HTTP API로 경로·보고서·스냅샷을 읽으며 작업자가 JSON/ZIP을 노드에 전달하지 않는다.

## 5. 터미널 C — 읽기 전용 연결 확인

공통 설정 후:

```bash
ros2 action list -t
ros2 service list
ros2 topic info /c2/process_state --verbose
curl --fail --silent http://127.0.0.1:8010/api/operator/snapshot | python3 -m json.tool
```

PrepareWorkpiece·ExecuteProcess 서버와 상태 발행자, HMI의 REAL/ROS 상태를 확인한다. 목록에 이름이 있다는 것만으로 제어권이나 실행 준비가 검증된 것은 아니다. HMI 준비 버튼은 실제 로봇 이동을 시작할 수 있다.

## 현재 가능한 범위 / 후속 작업

- 새 공정 노드: REAL 준비·실행 Action, HMI 자산 조회, REAL 실행 설정 로더가 구현됨.
- 현재 HMI: REAL 준비·측정 요청 및 결과 저장/표시. REAL BIND·경로 생성·실행 요청은 여전히 제한됨.
- c2_path `/3`: REAL 미리보기 전용. `test_only` 플래그를 바꾸어 실행용으로 사용하지 않음.
- 따라서 이 명령은 새 공정 노드와 HMI 연결/측정을 시도하는 절차다. PNG → 실제 조각 전체 연결에는 HMI의 REAL 스냅샷 조립·BIND·실행용 경로 계약 연결이 추가로 필요하다.

검증: CLI `--help`, 기존 환경의 rclpy/uvicorn/dsr_msgs2 import 확인. 이번 작업에서 colcon 빌드·DDS 연결·로봇 구동은 수행하지 않았다. commit/push/PR은 수행하지 않았다.

추가 회귀검사: `tests/test_image_workflow.py`를 실행했으나 결과 출력 없이 대기가 지속되어 중단했다. 이번 pull 이후 해당 검사의 통과는 확인하지 못했다. `git diff --check`는 통과했다.
