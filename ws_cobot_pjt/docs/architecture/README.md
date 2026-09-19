# C-2 시스템 아키텍처 · 팀 협업용 세부 설계도

> **보관 도면 · 9/18 기준:** 아래 draw.io와 overview.png에는 이전 집기·청소·반납 구조가 남아 있다. 현재 설계도로 사용하지 않는다. 9/19 고정 드릴 6개 모듈·통신 v2·열기 금지는 [현재 구조](../SYSTEM_STRUCTURE.md)와 [운영 결정](../C2_FIXED_DRILL_20260919.md)이 원본이다. 이번 점검에서 도형·PNG 자체를 재작성하거나 최신 검증본으로 표시하지 않았다.

**편집 원본: [C2_SYSTEM_ARCHITECTURE.drawio](C2_SYSTEM_ARCHITECTURE.drawio)** · [전체 구성 미리보기](overview.png)

[diagrams.net](https://app.diagrams.net/) 또는 draw.io 데스크톱에서 원본을 열면 아래 8개 페이지를 편집할 수 있다. 모든 박스·표·연결선·텍스트는 편집 가능한 도형이며 이미지 한 장으로 합친 파일이 아니다. 하단 페이지 탭에서 전체 구조 → 통신 → 내부 모듈 → 실행 흐름 순으로 확인한다.

## 기준과 범위

- 원격 조회·로컬 갱신 기준: 2026-09-18, `origin/main`의 `c414821d23c3083a0b160efc8d523e1739e7dd1d`.
- 최신 main을 로컬 main에 fast-forward한 뒤 `docs/system-architecture-drawio`에서 작성했다.
- 설계 원본: [INTERFACE_GUIDE](../INTERFACE_GUIDE.md), [SYSTEM_STRUCTURE](../SYSTEM_STRUCTURE.md), [INTERFACE_RECOMMENDATION v1](../INTERFACE_RECOMMENDATION.md). 통신 계약을 새로 변경한 문서가 아니라 기존 계약의 시각화다.
- 운영 PC 1대, 모니터·경로·공정의 세 노드, 등록된 고정 좌표, 고정 그리퍼와 교체 도구를 기준으로 한다. 공급자 드라이버도 같은 운영 PC에서 실행한다.
- 기존 Clay 코드·전용 실행 안내는 사용자 요청으로 로컬에 보관한 후 저장소에서 제거했다. [보관 범위·복구 방법](../LEGACY_CLAY_ARCHIVE.md).
- 공식 참고 `doosan/`의 Jazzy 커밋 `8e033f0`은 버전을 유지했다. 팀 저장소 갱신과 외부 로봇 라이브러리 자동 갱신을 구분한다.

## 페이지 구성

| 페이지 | 팀원이 파악할 내용 |
| --- | --- |
| 01 전체 구성 | 운영자 화면, 모니터 게이트웨이, 경로 생성, 공정 제어, 로컬 저장소, 공급자·장비 연결 |
| 02 경로 생성·실행 계약 | 두 Action의 송수신자, Goal·Feedback·Result 필드, ID·버전·해시·단위 |
| 03 정지·상태·이벤트 | Service·Topic 방향, 접수와 실제 정지 구분, 상태값, 신호 품질, QoS·제한 시간 |
| 04 내부 모듈 | 경로 계산 파이프라인, 상태 기계·집기·조각·청소·어댑터의 함수 호출 관계 |
| 05 파일·좌표·화면 API | asset/profile/path 파일 연결, 2D→3D 단위·프레임, HTTP·WebSocket 목록, 기록 저장 |
| 06 공정 흐름 | 입력→미리보기→별도 실행, 집기·조각·청소·반납, 정지·오류 분기와 완료 의미 |
| 07 어댑터 API | 현재 `robot_adapter.py`의 DSR_ROBOT2·dsr_msgs2 연결과 내부 결과 객체 |
| 08 구현·통합 확인 | main/작업 브랜치/구현 목표/로컬 보관 구분, 소스와 계약의 차이, 근거 |

색은 역할을 구분한다. 점선 박스는 구현 목표 또는 미확정 연결이고, 현재 소스가 있는 부분은 본문에 명시했다. 공급자 노드와 팀 내부 Python 모듈을 팀의 세 ROS 노드와 혼동하지 않는다. 실제 구동 그래프를 수집한 그림은 아니다.

## 송수신의 중심 계약

| ID | 이름 | 형식 | 방향 |
| --- | --- | --- | --- |
| A1 | `/c2/generate_path` | `c2_interfaces/action/GeneratePath` | 모니터 → 경로, Feedback·Result 역방향 |
| A2 | `/c2/execute_process` | `c2_interfaces/action/ExecuteProcess` | 모니터 → 공정, Feedback·Result 역방향 |
| S1 | `/c2/stop_process` | `c2_interfaces/srv/StopProcess` | 모니터 → 공정, 접수 Response 역방향 |
| T1 | `/c2/process_state` | `c2_interfaces/msg/ProcessState` | 공정 발행 → 모니터 구독 |
| T2 | `/c2/process_events` | `c2_interfaces/msg/ProcessEvent` | 공정 발행 → 모니터 구독 |

위 타입 파일·실행 노드는 기준 커밋에서 아직 구현되지 않았다. 필드의 전체 자료형, 시각의 ROS 타입, 중첩된 신호 품질 표현 등 원문이 확정하지 않은 내용은 임의로 추가하지 않았다. 공통 타입 PR에서 송수신자가 함께 확인한다. 명령 Service 및 Action의 Goal·Result·Cancel은 Jazzy 기본 Service QoS, Action 내부 상태 Topic은 기본 Action QoS를 따른다. 장치 Topic 구독은 실제 공급자의 QoS를 확인한다.

## 코드와 계약 사이의 통합 확인점

| 확인점 | 확인한 소스·의미 | 통합 시 필요한 일 |
| --- | --- | --- |
| ROS 실행 경계 | [개발 폴더](../../ws_cobot1/src/README.md)의 세 패키지에 실행 노드·빌드 설정 없음 | `/c2/*` 타입·노드·launch·설정 구현 후 통합 시험 |
| 로봇 어댑터 | [robot_adapter.py](../../ws_cobot1/src/c2_process/c2_process/robot_adapter.py)에 `StepResult`, 실기·모의 어댑터 존재 | 소스 존재를 새 공정 실행 완료와 구분 |
| 대기·정지 처리 | 어댑터 함수는 호출자 입장에서 동기 반환, 내부에서 비동기 이동·상태 감시 | 실행 대기 중 정지·상태 콜백을 처리할 실행 모델 검증 |
| 취소 결과 | `_wait_motion()` 등의 취소 분기는 `_qstop()` 뒤 `STOPPED`를 반환하지만 별도의 정지 확인 결과를 강제하지 않음 | v1의 실제 정지 확인 계약과 맞춰 연결·검증; 미확인 성공 처리 금지 |
| 이동 완료 | 현재 감시는 주로 XYZ 위치 오차와 로봇 상태를 사용 | 계약이 요구하는 목표 자세·확인 방식·신선도 검증 보완 |
| stop_mode | 현재 코드에는 `2`를 QSTOP으로 부르는 주석이 있으나 공식 Jazzy 정의는 `1` Quick, `2` Soft Stop으로 구분 | 실행 PC 설치본과 제어기의 정의 대조. 도면에서 특정 숫자를 팀 공통 설정으로 제시하지 않음 |
| 조각·청소 | [PR #15](https://github.com/suuuhululu/C-2/pull/15)는 `feat/12-robot-adapter`로 병합됨. `4b6416d`에는 세 파일 추가, 기준 main에는 미포함 | 해당 브랜치의 코드 검토·main 반영 상태를 별도 추적 |
| 고정 좌표 | 어댑터의 `probe_touch()`는 존재하지만 새 목표 공정에 매 작업 위치 탐색 단계는 없음 | 기능 존재만으로 시나리오를 확장하지 않음 |
| 장치·검사 | 그리퍼 모델·피드백·현장 profile과 제품 품질 합격은 별도 확인 대상 | 명령 접수·이동·파지·정지·전체 공정·검사 합격을 각각 기록 |

이 문서 작업은 통합 차이를 기록했으며 로봇 제어 코드를 수정하거나 동작을 시험하지 않았다. 기존 코드의 특정 현장값을 새로운 승인 설정으로 복제하지 않았다.

## 실제 확인한 근거

프로젝트 사실은 아래 고정 커밋·로컬 파일을 우선한다.

- [기준 main c414821](https://github.com/suuuhululu/C-2/commit/c414821d23c3083a0b160efc8d523e1739e7dd1d), [PR #13 로봇 어댑터](https://github.com/suuuhululu/C-2/pull/13), [PR #15 조각·청소](https://github.com/suuuhululu/C-2/pull/15).
- [브랜치 4b6416d](https://github.com/suuuhululu/C-2/commit/4b6416dff6cfb31218d9ec28739812079f3fe68e). 이 브랜치의 [Repository checks 성공](https://github.com/suuuhululu/C-2/actions/runs/35332900599)은 조회한 과거 결과이며 이번 도면의 원격 CI 결과가 아니다.
- [ROS 실행 문서](../../ws_cobot1/doc/README.md), [외부 의존성](../../../docs/DEPENDENCIES.md), [작업 규칙](../../../AGENTS.md).
- [두산 공식 Jazzy 소스](https://github.com/DoosanRobotics/doosan-robot2/tree/8e033f0e2284be0a25b655266e02878ebc915c50): `dsr_common2/imp/DSR_ROBOT2.py`, `dsr_msgs2/srv/MoveLine.srv`, `MoveSplineTask.srv`, `MoveStop.srv`, `GetCurrentPosx.srv`, `GetRobotState.srv`를 로컬에서 대조했다.
- [공식 Jazzy Motion Services](https://doosanrobotics.github.io/doosan-robotics-ros-manual/jazzy/services/motion_services.html): MoveLine·MoveSplineTask·MoveStop 정의를 확인했다. [공식 DRL Services](https://doosanrobotics.github.io/doosan-robotics-ros-manual/jazzy/services/drl_services.html)는 앞선 설계와 비교할 때 확인했으며 현재 도면의 주 실행 경로는 확인된 어댑터·ROS 서비스다.
- [ROS 2 Jazzy Actions](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/Concepts/Basic/About-Actions.rst), [ROS 2 Jazzy QoS](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/Concepts/Intermediate/About-Quality-of-Service-Settings.rst). 구체적인 `/c2/*` 필드·시간은 제조사 규격이 아니라 팀 v1 계약이다.

## 도면 검증과 미수행 범위

- 8개 페이지의 draw.io XML 구문, 도형 ID 중복, 연결선의 source/target 참조, 페이지 경계를 검사했다.
- draw.io 공식 뷰어 엔진으로 모든 페이지를 렌더링하고 글자 잘림·연결선 배치를 확인했다.
- 저장소 텍스트·Python 구문·상대 링크 50개 파일, Git hook 시험 8개, Issue 자동화 시험 27개, 팀 설정·셸 구문·공백 검사가 통과했다.
- Clay 제거 후 남은 `test_robot_adapter_mock.py`의 기존 모의 시험 7개가 통과했다. 로봇·ROS 연결 없이 실행한 시험이다.
- Clay 백업 32개 파일을 원본과 SHA-256으로 대조했다. 남은 팀 코드에 Clay import 의존성이 없는지 확인했다.
- ROS 빌드·새 공정 통합·시뮬레이션·실기 시험은 수행하지 않았다. 편집 PC는 macOS다.

파일을 고칠 때는 이 원본의 관련 페이지와 인터페이스 명세를 함께 대조하고, main에 없는 구현을 완료로 표시하지 않는다.
