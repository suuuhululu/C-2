# 프로젝트 ROS 실행·설정 기록

2026-09-19, 기준 main `42e8416`에 공통 타입 v1 구현을 반영했다. 팀 공정은 `ws_cobot1`, 외부 로봇·그리퍼 환경은 `ws_dsr`로 분리한다. 기존 Clay 코드와 전용 실행 안내는 PR #16에서 로컬 보관 후 저장소에서 제거했다. 과거 실행·시험 기록은 [보관·복구 기록](../../docs/LEGACY_CLAY_ARCHIVE.md)의 고정 커밋 링크로 확인한다.

## 현재 구현과 실행 가능 범위

| 대상 | 확인한 상태 |
| --- | --- |
| `c2_interfaces` | Action 2개·Service 1개·Message 2개와 빌드 설정 구현. Jazzy 타입 생성·직렬화 시험 통과. [빌드·사용법](../src/c2_interfaces/README.md) |
| `c2_path` | 개발 폴더만 있음. 노드·계산 모듈·빌드 설정 미구현 |
| `c2_process` | `robot_adapter.py`, `__init__.py`, 시험 소스 존재. 공정 노드·빌드 설정 미구현 |
| 운영자 HMI·서버 | React·FastAPI·SQLite와 MOCK 상대 구현. 실행 방법은 [서버](../../backend/README.md)·[화면](../../frontend/README.md) 안내 참조 |
| `monitor_gateway_node` | `backend/app/ros_bridge.py`에 ROS 클라이언트 코드 구현. 생성 타입과 시각·품질 변환 시험 통과. 파일 해석·실제 상대 통합 기동 미검증 |
| 조각·청소 | `feat/12-robot-adapter`의 `4b6416d`에 소스 존재. 기준 main에는 미포함 |

저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py`로 시작하는 화면은 SIMULATION / MOCK 전용이다. 현재 C-2를 clone한 것만으로 새 세 노드의 ROS 공정을 실행할 수 없다. 기존 Clay의 실행 명령을 새 패키지 이름으로 바꾸어 사용하지 않는다.

## 새 모니터 게이트웨이 연동

HTTP 서버와 같은 프로세스에서 ROS 클라이언트 노드 `monitor_gateway_node`를 구성하는 코드는 [ros_bridge.py](../../backend/app/ros_bridge.py)에 있다. 기본 실행은 ROS 없이 MOCK 상대를 사용한다. `/c2/generate_path`, `/c2/execute_process`, `/c2/stop_process`, `/c2/process_state`, `/c2/process_events` 계약을 연결한다.

공통 타입은 [c2_interfaces 안내](../src/c2_interfaces/README.md)대로 빌드·source한다. 좌표 파일을 해석하는 `artifact_loader`와 실제 상대 노드는 아직 연결 전이다. [모니터 구현·남은 연동 순서](../../docs/HMI_MONITOR_IMPLEMENTATION.md)를 먼저 확인한다. 가짜 경로는 실제 상대 노드에 전달하지 않는다.

경로 waypoint는 도구 끝 기준이며 제어기 TCP `GripperDA_v1`은 그리퍼 끝점이다. 도구 끝에서 제어기 TCP로의 변환은 `robot_adapter.py`가 담당한다. 과거 Clay 실행 안내의 `GripperDA_v3`·주소·자세·힘 값을 현재 승인된 실행 설정으로 옮기지 않는다.

## 설계·환경 기준

- [8페이지 draw.io 시스템 아키텍처](../../docs/architecture/README.md)
- [팀 인터페이스 안내](../../docs/INTERFACE_GUIDE.md), [목표 디렉토리](../../docs/SYSTEM_STRUCTURE.md), [상세 통신 계약](../../docs/INTERFACE_RECOMMENDATION.md)
- [개발 디렉토리](../src/README.md), [워크스페이스 가이드](../../../docs/WORKSPACES.md), [외부 의존성 기록](../../../docs/DEPENDENCIES.md)

ROS 2 Jazzy와 M0609를 기준으로 하며, 실행 PC의 공급자 버전·제어기·그리퍼 피드백·주소·TCP·하중·좌표·제한 시간은 현장 확인값으로 설정한다. 고정 좌표·도구 프로파일과 경로의 버전·해시를 대조한 뒤 실행하도록 연결한다.

## 다음 실행 문서에 기록할 항목

대상 PC·OS·ROS·공급자 커밋, 준비 설정, 실제 서비스·타입·QoS, 실행 순서, 정상 종료, 정지 확인, 통신 단절·오류 후 절차, 시험 커밋과 결과를 기록한다. [검증 기록 양식](../../docs/VALIDATION_TEMPLATE.md)을 사용하며 소스 존재·모의 시험·실기 시험을 구분한다.
