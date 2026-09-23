# 새김 시스템 인터페이스 안내

기준: `main` `6536a29` (2026-09-23). 이 문서는 현재 코드의 통신 경계와 작업 순서를 설명한다. 세부 필드의 원본은 [`c2_interfaces`](../ws_cobot1/src/c2_interfaces/README.md)의 `.action`·`.srv`·`.msg`, 실행 조건의 원본은 [`c2_process`](../ws_cobot1/src/c2_process/README.md)와 [`c2_path`](../ws_cobot1/src/c2_path/README.md) 코드다. 이전 설계·시험의 날짜별 기록을 현재 구현으로 읽지 않는다.

## 구성과 책임

- 운영자 화면(React)은 HTTP·WebSocket으로 FastAPI 서버와 통신한다. 서버의 `monitor_gateway_node`(`backend/app/ros_bridge.py`)가 ROS 요청·상태를 변환하고 SQLite·관리 파일을 보관한다.
- `path_planner_node`(`c2_path/node.py`)는 이미지에서 도구 끝 경로·미리보기·기하 검증 산출물을 만든다. 로봇을 움직이지 않는다.
- `process_controller_node`(`c2_process/node.py`)는 준비·측정과 실행 요청을 수신하고 모션 소유권·상태·정지를 관리한다. 같은 패키지의 측정·조각·로봇 어댑터는 내부 Python 호출로 연결한다. 별도 그리퍼/측정 ROS 노드를 두지 않는다.
- 외부 두산 드라이버와 실제 M0609는 공정 노드의 로봇 어댑터 뒤에 있다. 두산 ROS 서비스/공급자 Topic은 팀의 여섯 공통 통신과 구별한다.

## ROS 통신 6개

| 이름 | 형식 | 역할 |
| --- | --- | --- |
| `/c2/prepare_workpiece` | `PrepareWorkpiece` Action | `MEASURE`: 상태·필요 시 홈·재검사·양초 측정. `BIND_SNAPSHOT`: 측정 원본과 새 불변 설정 연결, 모션 없음 |
| `/c2/generate_path` | `GeneratePath` Action | 관리 이미지·설정 ID/해시로 3D 경로·미리보기·검증 보고서 생성 |
| `/c2/execute_process` | `ExecuteProcess` Action | 확인한 경로 ID/버전/해시로 최종 검사 후 조각 요청 |
| `/c2/stop_process` | `StopProcess` Service | 정지 **접수**. 실제 정지 완료는 상태와 Action 결과로 확인 |
| `/c2/process_state` | `ProcessState` Topic | 공정·장비 최신 상태와 신호 품질 |
| `/c2/process_events` | `ProcessEvent` Topic | 단계·오류·완료 사건 기록 |

Action은 오래 걸리는 작업의 진행·결과·취소를 전달한다. 팀 내부 파일을 나누었다는 이유로 ROS 통신을 추가하지 않는다. 모든 송수신자는 **동일한 생성 타입**을 빌드·source해야 한다. `schema_version=2`만 같고 `PrepareWorkpiece.Result` 필드가 다른 설치본은 호환되지 않는다.

## 현재 기본 흐름

1. 운영자가 PNG/JPEG와 크기·배치를 입력하고 REAL이면 측정 설정을 선택한다. HMI는 REAL 기동 시와 준비 요청 직전에 제어기를 **읽기 전용**으로 조회하여 `c2-hardware-observation/1`을 보관한다. 현재 TCP `GripperDA_v1`, load `ToolWeight_1`, AUTO/REAL·STANDBY/정지 등 조회 가능한 값이 설정과 맞아야 한다. 고정 설비·드릴 체결·드릴 OFF·이동 경로·지속 감시는 준비 화면에서 사람이 확인한다. 이 확인은 센서 관측으로 둔갑하지 않는다.
2. HMI가 `MEASURE`를 보낸다. 공정 노드가 제어권·상태·중복 요청·모션 소유권을 검사하고 필요 시 검사된 홈 이동·상태 재검사를 거쳐 윗면과 옆면 8점을 접촉 측정한다. #75의 옆면 점 재측정은 복구 가능한 오류에 한해 정지·후퇴 검사를 거쳐 제한적으로 수행하며, 힘 한계·불명확한 정지는 재시도하지 않는다. 높이는 운영자 자 측정값이며 수직 축은 가정이다. `ESTIMATED` 또는 `FORCE_CONTACT_ESTIMATE`, 절대 윗면 검증 여부 등 **원본 신뢰도**를 보존한다.
3. 서버가 측정 원본을 관리 파일에 저장하고 해당 측정의 설정과 기하를 조립해 새 ID·SHA-256을 발급한다. 유효한 REAL 실행 설정이 있으면 `BIND_SNAPSHOT`이 제어 측의 같은 측정 원본·설정 식별·기하·신뢰도와 대조한다. 실행 설정이 없거나 잘못되면 측정은 허용하되 REAL 추정값 **미리보기 전용** 스냅샷을 만들며 BIND·조각은 진행하지 않는다. BIND 성공은 실행 승인이나 새 측정을 뜻하지 않는다.
4. `GeneratePath`가 그 스냅샷으로 경로를 만든다. SIMULATION `/1`·`/2`, REAL 추정값 미리보기 `/3`, REAL 실행 후보 계약은 구분된다. REAL 실행 후보는 별도 `allow_real_execution` 설정과 BIND·실행 설정·작업 범위 조건을 거쳐 `test_only=false`, `real_execution_allowed=true`가 될 수 있다. 이 표시는 로봇 IK/관절·실물 충돌·가공 품질의 통과가 아니다.
5. 운영자가 미리보기를 확인한 뒤 별도 `ExecuteProcess`를 요청한다. HMI는 REAL에서 준비 수동 확인, 같은 준비/스냅샷/경로, 파일 해시, 최신 상태, 실행 후보 표시 등을 다시 대조한다. 드릴 ON 체크는 **화면 전용 수동 확인**이며 공정 Action 필드·전원 센서·드릴 제어 명령이 아니다. `operator_confirmed_fixture`는 ExecuteProcess의 별도 공작물 고정 확인이다.
6. 공정 노드는 경로·스냅샷 바이트/ID/해시, 실행 모드·설정, 장치 상태·제어권을 다시 검사한다. 깊이·접근·이탈을 반영한 실행 계획의 **모든 명시 waypoint**를 IK·관절 한계·J6로 검사한 후 같은 계획으로 조각한다. 이 검사는 waypoint 사이 연속 경로의 충돌 보증이 아니다. 성공·실패·정지 미확인은 Action 결과/상태/이벤트로 전달하며 미확인 정지는 새 공정을 차단한다.

## 모드·단위·배포 경계

- 기본 `run_monitor.py`는 `SIMULATION`/MOCK이다. ROS SIM 통합은 `--transport ros --process-integration`; REAL HMI는 `--transport ros --mode REAL --preparation-config ...`를 사용하고 배포 실행 설정을 공급한다. 실행기는 HMI·서버·경로 노드를 시작하지만 **공정 노드·두산 드라이버는 별도 기동**한다. REAL 경로 노드는 명시 `allow_real_execution:=true` 설정으로 실행 후보를 생성할 수 있다. 현재 옵션은 [백엔드 실행 안내](../backend/README.md)를 따른다.
- 경로는 `c2_base`의 **드릴 끝** 위치 m·정규화 quaternion `(x,y,z,w)`다. 2D 크기·배치는 mm, 화면 회전은 deg, 관절은 rad다. 도구 끝에서 두산 제어기 TCP로의 변환과 서비스 단위 변환은 `robot_adapter.py`에서만 한다.
- 로봇 제어기 주소·TCP·하중·힘·속도·깊이·정지 기한은 현장 배포 설정과 실제 설치본을 대조한다. 저장소의 예시·시험값을 실기 승인값으로 사용하지 않는다. 그리퍼의 제조사·모델·배선·피드백은 현장 확인 전 미정이며, 철사로 드릴을 고정한 동안 그리퍼 열기·자동 집기·반납·청소는 공정 범위에서 제외한다.
- 이 커밋에는 통신·가상 장치/대역 시험과 REAL 연결 코드가 있지만, **HMI→실제 M0609 측정·조각 전체 성공의 실기 검증은 확인되지 않았다.** 소스 존재, 모의 시험, DDS 왕복, 실기·품질 결과를 분리한다.

날짜별 결정과 실험은 [`2026-09-21 일지`](daily/2026-09-21.md), [`2026-09-22 일지`](daily/2026-09-22.md), [`실기 시행착오`](LESSONS_ROBOT.md)에 남긴다. 일지의 당시 계획은 현재 실행 계약의 원본이 아니다.
