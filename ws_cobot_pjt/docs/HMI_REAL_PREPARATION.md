# 한 PC의 REAL 준비·측정 통합

> **9/21 당시 통합 기록. 현재 실행 안내가 아니다.** 2026-09-23 `main` `b9eb003`은 REAL 실측 미리보기와 조건부 BIND·경로 후보·별도 실행 요청, prepared entry 계획까지 포함한다. 현재 옵션과 조건은 [백엔드 실행 안내](../backend/README.md), [작업 흐름](INTERFACE_GUIDE.md)을 따른다. 아래 명령·차단 범위는 당시 브랜치에만 적용한다.

기준 main `08956e5`(PR #54), `codex/hmi-preparation-flow`의 HMI 수정. 이전 SIM 전용 안내를 이 문서의 REAL 준비 범위에 한해 갱신한다.

## 연결 범위

HMI → 기존 PrepareWorkpiece MEASURE → 세은 REAL 공정 노드 → 시율 측정 함수 → 드라이버/로봇 → Action Result → HMI 원본 보관·표시.
동시에 기존 `/c2/process_state`의 REAL 상태를 수신한다. 첫 요청 전 관절/TCP UNKNOWN은 관측기 설정 미연결일 수 있다.
측정 성공은 `SUCCEEDED / MEASUREMENT_ONLY`로 보존한다. `ESTIMATED`를 SIMULATED나 절대 높이 검증 완료로 바꾸지 않는다.
당시 구현은 REAL에서 BIND·GeneratePath·ExecuteProcess를 허용하지 않았다. 9/23 main의 제한으로 적용하지 않는다. 이 단계의 목적은 실제 준비/측정 결과를 받는 통합이었으며 전체 조각 완료가 아니다.
공통 Action/Topic/HTTP 요청 필드는 변경하지 않았다. 제어·측정·드라이버 코드는 변경하지 않았다.

## 현장 설정

`--preparation-config`로 현장에 맞는 파일을 명시 선택한다. 파일을 지정하지 않으면 REAL HMI를 기동하지 않는다.
기존 `prepare-workpiece-config/1` 파일 또는 시율의 native workcell/profiles REAL JSON을 받는다.
native 형식은 원본을 별도 보관하고, 기존 Action 설정 봉투만 붙인다. tool_id=engraving_drill, TCP/하중은 원본 workcell에서 읽는다. 좌표·힘·속도·제한시간은 수정하지 않는다. 소비자용 최종 바이트에 ID/해시를 발급한다.
`workpiece_real_trial_0921.json`은 저장소에 있지만 **현재 현장 승인값으로 자동 선택하지 않는다.** 양초·받침·고정 상태, TCP·하중·높이와 해당 파일의 전제가 그대로인지 담당자 확인 후 선택한다.

HMI는 기동 시와 준비 요청 직전에 제어기를 읽기 전용으로 조회하고 `hardware_snapshot` JSON을 저장한다. 해당 JSON은 로봇 상태·AUTO/REAL·모션 정지·현재 TCP/load·관절·TCP 위치만 담는다. 속도·힘·실행 프로파일은 자동 생성하거나 기본값으로 채우지 않는다. 자동 관측할 수 없는 고정 설비·그리퍼/드릴 체결·드릴 OFF·이동 경로·지속 감시는 REAL 준비 화면의 한 번의 수동 확인으로 남긴다.

고정 설비 계약은 TCP `GripperDA_v1`, load/tool `ToolWeight_1`이며 설정 파일·HMI 자동 관측·모션 직전 재조회 중 하나라도 다르면 REAL 진행을 차단한다. 그리퍼 개폐나 홈 복귀를 HMI가 자동 추가하지 않는다.

## 실행 — 같은 PC의 bash 터미널

먼저 최신 패키지를 빌드한다. 실제 장치 실행은 아래 별도 단계다.

```bash
cd /home/rokey/cobot1/ws_cobot_pjt/ws_cobot1
source /opt/ros/jazzy/setup.bash
colcon build --packages-select c2_interfaces c2_path c2_process --symlink-install
```

터미널 1 — HMI (현장설정.json은 확인한 실제 파일의 절대 경로로 교체):

```bash
cd /home/rokey/cobot1
source /opt/ros/jazzy/setup.bash
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash
python3 ws_cobot_pjt/run_monitor.py --transport ros --mode REAL \
  --preparation-config /확인한/현장설정.json --ros-domain-id 20
```

당시 실행기 설정은 REAL에서 경로 노드를 자동 기동하지 않았다. 현재 `run_monitor.py`는 기본적으로 경로 노드를 시작한다. 화면은 http://127.0.0.1:5174/operator 이며 REAL 경고를 표시한다.
데이터는 기본 `backend/monitor_data/real_preparation`에 SIM과 분리된다. 기존 화면·서버가 5174/8010에서 실행 중이면 정상 종료한 후 기동한다.

터미널 2 — 공정 REAL 준비 노드. 아래 prefix는 **선택한 파일의 controller_prefix와 같을 때만** 사용한다.

```bash
cd /home/rokey/cobot1
source /opt/ros/jazzy/setup.bash
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash
export ROS_DOMAIN_ID=20
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_STATIC_PEERS=''
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
mkdir -p ws_cobot_pjt/backend/monitor_data/real_preparation
ros2 run c2_process real_preparation_node \
  --preparation-backend-url http://127.0.0.1:8010 \
  --preparation-journal-path /home/rokey/cobot1/ws_cobot_pjt/backend/monitor_data/real_preparation/process.sqlite3 \
  --controller-prefix /dsr01/dsr_controller2
```

드라이버도 같은 PC에서 검증된 기존 실행 방법과 같은 domain/RMW로 실행되어 있어야 한다. 위 명령은 드라이버를 설치·기동하거나 제어권을 강제로 얻지 않는다. 드라이버 실행 명령·로봇 IP·현장 안전조건을 추정하지 않는다.
`--controller-prefix`로 DSR_ROBOT2 측정·실행 service와 `<prefix>/control_authority` 토픽을 같이 결정한다. 공정 노드 namespace remap은 필요하지 않다. 이 데스크톱의 외부 드라이버는 `/home/rokey/ws_cobot_pjt/ws_dsr`에 있으므로 필요한 `dsr_msgs2` 등은 해당 `install/setup.bash`를 먼저 source한 뒤 팀 워크스페이스를 source한다. 다른 PC는 실제 설치 경로를 확인한다.
HMI와 REAL/SIM 공정 노드를 같은 domain에 중복 실행하지 않는다. 경로 노드가 꺼져 있어도 REAL 준비 요청에는 문제가 없다.

## 실제 확인 순서

1. 선택한 설정·로봇 주변·드릴 수동 OFF·고정 장착 상태를 확인한다. 보호 기능을 우회하지 않는다.
2. HMI 상단 REAL, 공정 상태 수신을 확인한다. 연결 표시는 모션 안전 승인이 아니다.
3. 준비 요청을 한 번 보내고 홈 검사·필요한 홈 이동·측정 진행을 확인한다. **이 버튼은 실제 이동을 시작할 수 있다.**
4. Result의 준비/측정 ID·기하 유효 상태·정지 확인·원본을 확인한다. ESTIMATED면 절대 높이 미검증 표시가 유지돼야 한다.
5. 이후에도 상태 토픽이 발행되는지 확인한다. 취소 접수와 실제 정지 확인을 구분한다. UI 취소는 안전등급 비상정지를 대신하지 않는다.

종료는 작업이 끝나고 실제 정지가 확인된 뒤 진행한다. 실행기 Ctrl+C는 로봇 안전 정지 명령이 아니다. 공정 노드/드라이버를 측정 도중 단순 종료하지 않는다.

## 검증 수준

### 9/21 PR 제출 시점 추가 확인

- 최신 main `08956e5`와 동일한 기반을 확인했다. 이번 재검사는 backend 선택 9개 파일 **94 passed, 1 skipped**(ROS 타입 환경 의존 검사), frontend Node 4개 파일·TypeScript·Vite 빌드 통과다.
- 저장소 검사 234개 파일, Git hook 시험 8개, `git diff --check` 통과. 아래 108 passed는 이전 환경의 시험 기록이며 이번 재실행 수치와 합산하지 않는다.
- 사용자가 실기 준비 요청을 실행했고, HMI API에 `SUCCEEDED`, `stop_confirmed=true`, 접촉 9점, `validity=ESTIMATED`, `MEASUREMENT_ONLY` 결과가 저장된 것을 읽기 전용으로 확인했다. 독립 좌표 정확도·절대 높이·실제 가공·취소/비상정지 성능 검증을 뜻하지 않는다.
- 공정의 ESTIMATED BIND 거절과 경로 노드의 SIMULATION 전용 제한은 유지한다. 실측 기반 미리보기 연결은 후속 담당자 협의·작업이며 이 PR에 구현하지 않았다.
- 모션 전 거절로 남은 특정 UNKNOWN 기록의 오프라인 복구는 [복구 안내](HMI_PRECHECK_RECOVERY.md), 외부 드라이버 별도 빌드 근거는 [데스크톱 기록](DESKTOP_DRIVER_AUTHORITY_20260921.md)을 따른다. 외부 드라이버 소스는 이 PR에 포함하지 않는다.

### 이전 단계 기록

- 관련 backend 시험은 REAL 대역과 SIM localhost/domain 20 ROS Action 왕복을 포함한다.
- frontend Node 시험 4개 파일, TypeScript 확인 및 Vite 빌드 통과. 저장소 검사와 diff 공백 검사 통과.
- 변경은 미커밋 작업 파일이다. commit/push/PR 생성 및 실기 실행은 하지 않았다.

REAL 모드 시험은 가짜 Action 상대와 임시 DB로 요청 모드·상태 수신·Result 보관·MEASUREMENT_ONLY·경로/조각 차단을 확인한다. 실제 REAL 노드/로봇을 기동하지 않았다.
실기 통합 검증, 현장 설정 승인, 드라이버 통신/제어권, 실제 취소·정지 지연 검증은 현장 단계로 남는다. 테스트 성공이 현장 설정 승인을 뜻하지 않는다.
