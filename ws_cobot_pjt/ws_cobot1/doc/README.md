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

## 설계·환경 기준

- [8페이지 draw.io 시스템 아키텍처](../../docs/architecture/README.md)
- [팀 인터페이스 안내](../../docs/INTERFACE_GUIDE.md), [목표 디렉토리](../../docs/SYSTEM_STRUCTURE.md), [상세 통신 계약](../../docs/INTERFACE_RECOMMENDATION.md)
- [개발 디렉토리](../src/README.md), [워크스페이스 가이드](../../../docs/WORKSPACES.md), [외부 의존성 기록](../../../docs/DEPENDENCIES.md)

ROS 2 Jazzy와 M0609를 기준으로 하며, 실행 PC의 공급자 버전·제어기·그리퍼 피드백·주소·TCP·하중·좌표·제한 시간은 현장 확인값으로 설정한다. 이전 실행 안내의 장비값은 보관 시점의 기록이며 새 공정의 승인된 설정으로 간주하지 않는다.

## 다음 실행 문서에 기록할 항목

대상 PC·OS·ROS·공급자 커밋, 준비 설정, 실제 서비스·타입·QoS, 실행 순서, 정상 종료, 정지 확인, 통신 단절·오류 후 절차, 시험 커밋과 결과를 기록한다. [검증 기록 양식](../../docs/VALIDATION_TEMPLATE.md)을 사용하며 소스 존재·모의 시험·실기 시험을 구분한다.
