# 프로젝트 ROS 실행·설정 기록

2026-09-20 갱신: main `72618aa`의 PR #38과 HMI 부분 통합 기준이다.
실제 이미지→경로 생성·미리보기와 한 PC 실행은 [HMI 경로 통합 안내](../../docs/HMI_PATH_INTEGRATION.md)를 따른다.
아래 과거 PR 상태는 당시 기록이며 현재 실행 가능 여부는 이 통합 범위를 기준으로 한다.

현재 도구는 engraving_drill, 프레임은 c2_base다. 철사 고정 중 그리퍼 열기·집기·청소·반납을 금지한다. 보정 소스 PR #27은 미병합이며 새 측정값은 경로 생성 전 스냅샷으로 고정해야 한다. [구조·전환](../../docs/C2_FIXED_DRILL_20260919.md).

2026-09-19, 기준 main `301ea6e`에 고정 드릴 v2 변경을 반영했다. 팀 공정은 `ws_cobot1`, 외부 로봇·그리퍼 환경은 `ws_dsr`로 분리한다. 기존 Clay 코드와 전용 실행 안내는 PR #16에서 로컬 보관 후 저장소에서 제거했다. 과거 실행·시험 기록은 [보관·복구 기록](../../docs/LEGACY_CLAY_ARCHIVE.md)의 고정 커밋 링크로 확인한다.

## 현재 구현과 실행 가능 범위

| 대상 | 확인한 상태 |
| --- | --- |
| `c2_interfaces` | Action 2개·Service 1개·Message 2개와 빌드 설정 구현. Jazzy 타입 생성·직렬화 시험 통과. [빌드·사용법](../src/c2_interfaces/README.md) |
| `c2_path` | PR #38의 노드·이미지 계산·관리 파일·빌드 설정 구현. 실제 ROS 경로 생성/HMI 조회 시험 통과. SIMULATION/test_only |
| `c2_process` | `robot_adapter.py`, `__init__.py`, 시험 소스 존재. 공정 노드·빌드 설정 미구현 |
| 운영자 HMI·서버 | React·FastAPI·SQLite, MOCK 및 c2_path 부분 통합. 실행 방법은 [서버](../../backend/README.md)·[화면](../../frontend/README.md) 안내 참조 |
| `monitor_gateway_node` | `backend/app/ros_bridge.py`의 native rclpy 클라이언트와 artifact_loader 연결. 파일 무결성·실제 경로 노드 통합 시험 완료. 공정/실기 미검증 |
| 조각·보정 | 조각 이관 PR #25·보정 PR #27 미병합. 어댑터 frame 변경은 PR #23. cleaning은 feat/12-robot-adapter의 4b6416d에 예비 보관 |

저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py`는 기본 SIMULATION/MOCK이다. Jazzy 환경을 준비하고
`--transport ros`를 주면 저장소를 초기화한 뒤 경로 노드와 HMI를 함께 켠다. 실제 공정 전체를 실행하는 명령은 아니다.
기존 Clay의 실행 명령을 새 패키지 이름으로 바꾸어 사용하지 않는다.

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
