# 프로젝트 ROS 실행·설정 기록

2026-09-23 갱신: main `b9eb003`의 HMI·경로·공정 연결과 PR #80 entry planner 기준이다.
현재 실행 흐름은 [인터페이스 안내](../../docs/INTERFACE_GUIDE.md), 파일·노드 책임은
[시스템 구조](../../docs/SYSTEM_STRUCTURE.md)를 따른다. 날짜별 과거 PR 문서는 당시 기록이며
현재 실행 가능 여부는 이 문서와 실제 코드·설정으로 다시 확인한다.

현재 도구는 engraving_drill, 프레임은 c2_base다. 철사 고정 중 그리퍼 열기·집기·청소·반납을 금지한다. `tool_calibration.py`는 main에 있지만 양초 위치 측정과 별개이며, 새 측정값은 경로 생성 전 스냅샷으로 고정해야 한다. [구조·전환](../../docs/C2_FIXED_DRILL_20260919.md).

2026-09-19, 기준 main `301ea6e`에 고정 드릴 v2 변경을 반영했다. 팀 공정은 `ws_cobot1`, 외부 로봇·그리퍼 환경은 `ws_dsr`로 분리한다. 기존 Clay 코드와 전용 실행 안내는 PR #16에서 로컬 보관 후 저장소에서 제거했다. 과거 실행·시험 기록은 [보관·복구 기록](../../docs/LEGACY_CLAY_ARCHIVE.md)의 고정 커밋 링크로 확인한다.

## 현재 구현과 실행 가능 범위

| 대상 | 확인한 상태 |
| --- | --- |
| `c2_interfaces` | Action 3개·Service 1개·Message 2개와 빌드 설정 구현. 모든 ROS 노드는 같은 설치본을 사용해야 한다. [빌드·사용법](../src/c2_interfaces/README.md) |
| `c2_path` | 이미지→중심선/해칭→원통 3D 경로·미리보기·관리 파일 구현. SIMULATION/test_only와 조건부 REAL 실행 후보를 구분하며 로봇을 움직이지 않는다. |
| `c2_process` | 준비 MEASURE/BIND, 상태 기계·preconditions·측정·entry planner·전체 명시 waypoint 관절 검사·조각·정지와 SIM/REAL entry point 구현. `launch/process.launch.py`와 실행 YAML은 없음. |
| 운영자 HMI·서버 | React·FastAPI·SQLite, 관리 자산, MOCK/ROS SIM/REAL 준비→경로→별도 실행 요청 연결. 실행 방법은 [서버](../../backend/README.md)·[화면](../../frontend/README.md) 안내 참조. |
| `monitor_gateway_node` | `backend/app/ros_bridge.py`의 native rclpy 클라이언트. `PrepareWorkpiece`·`GeneratePath`·`ExecuteProcess`·정지·상태·이벤트 계약을 연결한다. |
| prepared 실행 | `PRECHECK → ENTRY → ENGRAVE → FINISH`. entry는 실측 기하와 승인된 상대 정책으로 후보를 검사·고정한 뒤 실행한다. 전체 메시 충돌과 실제 M0609 전체 공정은 별도 검증 대상이다. |

저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py`는 기본 SIMULATION/MOCK이다. Jazzy 환경을 준비하고
`--transport ros`를 주면 저장소를 초기화한 뒤 경로 노드와 HMI를 함께 켠다. 실제 공정 전체를 실행하는 명령은 아니다.
기존 Clay의 실행 명령을 새 패키지 이름으로 바꾸어 사용하지 않는다.

REAL에서 `--preparation-config`는 측정용 현장 설정이다. `--execution-profile`은 속도·깊이·관절 한계와
`execution_context.entry_planning` 같은 승인 정책이며, 생략하면 측정·test_only 미리보기까지만 가능하다.
양초 중심·반지름·윗면·바닥은 실행 프로파일의 고정값으로 쓰지 않고 매 준비의 측정 스냅샷으로 대체한다.
사전 검사는 원본 JSON을 수정하지 않는다.

## 새 모니터 게이트웨이 연동

HTTP 서버와 같은 프로세스에서 ROS 클라이언트 노드 `monitor_gateway_node`를 구성하는 코드는 [ros_bridge.py](../../backend/app/ros_bridge.py)에 있다. 기본 실행은 ROS 없이 MOCK 상대를 사용한다. `/c2/generate_path`, `/c2/execute_process`, `/c2/stop_process`, `/c2/process_state`, `/c2/process_events` 계약을 연결한다.

공통 타입과 c2_path를 같은 checkout에서 빌드·source한다. PR #38의 불변 프로파일과 파일 계약을 사용하는
`artifact_loader`가 연결돼 있다. [현재 통합 범위](../../docs/HMI_PATH_INTEGRATION.md)를 먼저 확인한다.
가짜 경로는 실제 상대 노드에 전달하지 않는다.

경로 waypoint는 도구 끝 기준이며 제어기 TCP `GripperDA_v1`은 그리퍼 끝점이다. 도구 끝에서 제어기 TCP로의 변환은 `robot_adapter.py`가 담당한다. 과거 Clay 실행 안내의 `GripperDA_v3`·주소·자세·힘 값을 현재 승인된 실행 설정으로 옮기지 않는다.

## 설계·환경 기준

- [8페이지 draw.io 시스템 아키텍처](../../docs/architecture/README.md)
- [팀 인터페이스 안내](../../docs/INTERFACE_GUIDE.md), [목표 디렉토리](../../docs/SYSTEM_STRUCTURE.md), [상세 통신 계약](../../docs/INTERFACE_RECOMMENDATION.md)
- [개발 디렉토리](../src/README.md), [워크스페이스 가이드](../../../docs/WORKSPACES.md), [외부 의존성 기록](../../../docs/DEPENDENCIES.md)

ROS 2 Jazzy와 M0609를 기준으로 하며, 실행 PC의 공급자 버전·제어기·그리퍼 피드백·주소·TCP·하중·좌표·제한 시간은 현장 확인값으로 설정한다. 고정 좌표·도구 프로파일과 경로의 버전·해시를 대조한 뒤 실행하도록 연결한다.

## 다음 실행 문서에 기록할 항목

대상 PC·OS·ROS·공급자 커밋, 준비 설정, 실제 서비스·타입·QoS, 실행 순서, 정상 종료, 정지 확인, 통신 단절·오류 후 절차, 시험 커밋과 결과를 기록한다. [검증 기록 양식](../../docs/VALIDATION_TEMPLATE.md)을 사용하며 소스 존재·모의 시험·실기 시험을 구분한다.

랜선 없는 실제 HMI·경로·공정 ROS 통합은 [가상 장치 실행 안내](../../docs/VIRTUAL_CELL_20260922.md)를 따른다. SIMULATION 전용이며 실물 드라이버는 실행하지 않는다.
