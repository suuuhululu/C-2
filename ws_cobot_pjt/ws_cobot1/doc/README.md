# 프로젝트 ROS 실행·설정 기록

2026-09-18, 기준 main `c414821`. 팀 공정은 `ws_cobot1`, 외부 로봇·그리퍼 환경은 `ws_dsr`로 분리한다. 기존 Clay 코드와 전용 실행 안내는 사용자 요청으로 로컬 보관 후 저장소에서 제거했다. [보관·복구 기록](../../docs/LEGACY_CLAY_ARCHIVE.md).

## 현재 구현과 실행 가능 범위

| 대상 | 확인한 상태 |
| --- | --- |
| `c2_interfaces` | 개발 폴더만 있음. `.action`·`.srv`·`.msg`와 빌드 설정 미구현 |
| `c2_path` | 개발 폴더만 있음. 노드·계산 모듈·빌드 설정 미구현 |
| `c2_process` | `robot_adapter.py`, `__init__.py`, 시험 소스 존재. 공정 노드·빌드 설정 미구현 |
| `monitor_gateway_node` | `backend/app/ros_bridge.py`에 개발할 목표. 서버 코드 미구현 |
| 조각·청소 | `feat/12-robot-adapter`의 `4b6416d`에 소스 존재. 기준 main에는 미포함 |

현재 C-2를 clone한 것만으로 새 세 노드 공정을 실행할 수 없다. 실제 launch·설정·종료 절차는 구현과 검증 후 이 문서에 추가한다. 기존 Clay의 실행 명령을 새 패키지 이름으로 바꾸어 사용하지 않는다.

현재 구현 예정 패키지는 `c2_interfaces`, `c2_path`, `c2_process`다. 그리퍼 제어·파지 확인과 도구 집기·반납은 `c2_process` 내부 모듈로 둔다. 모니터 게이트웨이 노드는 백엔드에 둔다. 전체 배치와 도구별 설정은 [현재 디렉토리 구조](../../docs/SYSTEM_STRUCTURE.md)를 따른다.

통신 구현 전 [인터페이스 권장안 v1](../../docs/INTERFACE_RECOMMENDATION.md)의 필드·좌표 규약·완료 판단을 합의한다. 문서의 소프트웨어 초기 기한과 현장에서 정할 실제 동작 기한은 구분한다.

빌드·환경 적용 순서는 [공통 환경 가이드](../../../docs/WORKSPACES.md)를 따른다. 실제 실행 코드가 생기면 이 문서에 다음 항목을 채운다.

| 항목 | 현재 상태 |
| --- | --- |
| 실행 PC·ROS 배포판·소스 커밋 | 공용 MSI Ubuntu 사용 보고, 정확한 설치 버전 대기. 이시율 PC의 Jazzy·소스 커밋 보고는 의존성 기록 참조 |
| 필요한 ws_dsr 패키지·버전 | 외부 cobot_rg2 사용. PC별 버전 보고는 의존성 기록에 구분, 팀 공통 고정 버전은 확인 대기 |
| 팀 패키지명·launch·실행 순서 | `clay_carving`, `clay_hmi`. 실행 순서는 [clay_run.md](clay_run.md) 3절 |
| 로봇 ID·네임스페이스·연결 설정 | `dsr01`, 실물 브링업 `mode:=real host:=192.168.1.100 port:=12345 model:=m0609`. 툴 `ToolWeight_1`, TCP `GripperDA_v3` ([clay_run.md](clay_run.md) 4절) |
| DRL·DRFL·ROS 서비스·Python 래퍼 구분 | 기능별 확인 필요 |
| 시작 전 확인·종료·오류 후 복구 | [clay_run.md](clay_run.md) 4·5절 |
| 확인한 로그·시험 결과 | 노드 1~4 실기 완주 2026-09-17 (bag 파일명은 [clay_run.md](clay_run.md) 6절). HMI 연동 실기 미수행 |

실제 장비 값은 로컬 설정에 두고 공유 예제에는 필요한 항목만 표시한다. 프로젝트 설계는 [프로젝트 계획](../../docs/PROJECT_PLAN.md), 실제 결과는 [검증 기록](../../docs/VALIDATION_TEMPLATE.md)에 연결한다.


## 새 모니터 게이트웨이 개발 상태 · 2026-09-18

HTTP 서버와 같은 프로세스에서 ROS 클라이언트 노드 `monitor_gateway_node`를 구성하는 코드는 `../../backend/app/ros_bridge.py`에 있다. 기본 실행은 ROS 없이 MOCK 상대를 사용한다. `c2_interfaces` 생성 타입과 좌표 파일 해석 어댑터가 아직 없어 ROS 통합 기동은 검증하지 않았다. [모니터 구현·남은 연동 순서](../../docs/HMI_MONITOR_IMPLEMENTATION.md)를 먼저 확인한다. 가짜 경로를 실제 상대나 로봇에 전달하지 않는다.
