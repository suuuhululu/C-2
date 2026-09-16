# 워크스페이스와 팀 공유

2026-09-16 사용자 제공 강사 디렉토리 구조에 맞췄다. 팀 코드는 C-2에서 공유하고, 외부 실행환경은 각 PC에 별도로 준비한다. 사용자는 공용 MSI Ubuntu에서 Docker 에뮬레이터를 통한 가상 로봇 동작을 확인했다고 보고했다. 이 문서 수정 작업에서 설치·구동을 직접 검증하지는 않았다.

## 기존 경로와 새 경로

| 이전 초안 | 현재 경로 | 용도 |
| --- | --- | --- |
| mini_project/ws/src | ros2_ws/src | 수업·미니 실습 ROS 패키지 |
| mini_project/docs | ros2_ws/docs | 실습·복습 기록 |
| 별도 위치 미정 | ros2_ws/exercises | DRL·Dart 등 비 ROS 실습 |
| main_project/ws/src | ws_cobot_pjt/ws_cobot1/src | 팀 공정 ROS 패키지 |
| main_project/docs | ws_cobot_pjt/docs | 메인 기획·검증 |
| 공급자용 vendor_ws 제안 | ws_cobot_pjt/ws_dsr | 로봇·그리퍼 실행환경 |

메인에는 backend/app, frontend/src·public, docker, DartPlatform을 추가했다. ROS 실행 방법은 ws_cobot1/doc에 기록한다. 공통 문서는 루트 docs, GitHub 설정과 자동화는 기존 위치를 유지한다. Issue의 mini/main 분류도 유지한다.

## 분리 원칙

```text
수업·미니: ROS 2 Jazzy → ros2_ws
메인:      ROS 2 Jazzy → ws_cobot_pjt/ws_dsr → ws_cobot_pjt/ws_cobot1
```

세 ROS 워크스페이스는 각자 src/build/install/log를 사용한다. 메인에서는 ws_dsr가 로봇·그리퍼 기반 환경이고 ws_cobot1이 팀 공정 환경이다. 수업 환경을 메인의 필수 의존성으로 만들지 않는다. 같은 dsr 패키지를 여러 src에 중복 배치하거나 수업과 메인 환경을 한 터미널에 함께 source하지 않는다.

팀 코드 폴더마다 새로 git init하지 않는다. 수업 절차로 받은 외부 `cobot_rg2`는 `ws_dsr/src/.git`을 가진 별도 저장소이며 그대로 보존한다. C-2는 `ws_dsr/src/` 전체를 제외하므로 외부 원본은 [의존성 기록](DEPENDENCIES.md)에 따라 준비하고 출처·버전만 공유한다. 팀의 메인 ROS 패키지와 launch 파일은 고유한 패키지명으로 `ws_cobot1/src/`에 둔다.

## 현재 준비 범위

- 수업용 `ros2_ws`의 DoosanBootcamInt1·onrobot_rg2는 이름만 제공됐으며, 메인 실행환경은 수업 지정 `ahnisinc/cobot_rg2`를 사용한다고 팀원이 보고했다. 서로 같은 소스로 가정하지 않는다.
- `ws_dsr/src`는 로컬 외부 원본 전용이며 `.gitkeep`을 공유하지 않는다. 새 C-2 clone에는 이 폴더가 없고, 외부 원본을 clone할 때 생성된다. 기존에 설치한 PC의 폴더·버전은 변경하지 않는다.
- 상위 개인 프로젝트의 doosan 폴더는 이동·복사하지 않았다. 2026-09-16 확인한 Jazzy 커밋은 의존성 기록에 남겼다.
- 강사 예시는 RG2 환경이지만 실제 장비 모델·배선·통신·피드백은 미확인이다. 로봇 기준은 M0609, ROS 기준은 Jazzy다.
- DartPlatform은 README만 공유한다. 프로그램·Logs, ROS build/install/log, frontend node_modules는 각 PC에서 생성하고 Git에서 제외한다.
- backend·frontend·docker는 폴더와 안내만 있다. 프레임워크·이미지는 미정이다.
- 현재 편집 PC는 macOS이며 ROS 빌드·시뮬레이션·실기 실행은 수행하지 않았다.

## 빌드·환경 적용 위치

아래는 Ubuntu Jazzy와 필요한 소스·의존성이 준비된 이후의 경로 예시다. C-2를 clone하는 것만으로 외부 실행환경이 설치되지는 않는다. 실제 제어기 버전별 빌드 옵션은 제조사 문서와 대조한다.

각 블록은 C-2 저장소 루트(현재 로컬 폴더명 collaborative)에서 시작하는 새 Bash 터미널 기준이다. 이미 대상 워크스페이스를 source한 터미널에서 다시 빌드하지 않는다.

수업·미니 빌드:

```bash
source /opt/ros/jazzy/setup.bash
cd ros2_ws
colcon list
colcon build --symlink-install
```

메인 로봇 실행환경 빌드:

```bash
source /opt/ros/jazzy/setup.bash
cd ws_cobot_pjt/ws_dsr
colcon list
colcon build --symlink-install
```

ws_dsr 빌드 성공 후, 새 터미널에서 팀 공정 빌드:

```bash
source /opt/ros/jazzy/setup.bash
source ws_cobot_pjt/ws_dsr/install/local_setup.bash
cd ws_cobot_pjt/ws_cobot1
colcon list
colcon build --symlink-install
```

메인 실행용 새 터미널의 환경 적용:

```bash
source /opt/ros/jazzy/setup.bash
source ws_cobot_pjt/ws_dsr/install/local_setup.bash
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash
```

수업 실행용 터미널에서는 Jazzy 다음 ros2_ws/install/local_setup.bash만 적용한다. C-2 전체나 ws_cobot_pjt 전체에서 colcon build하지 않는다. 이 명령은 환경 준비이며 로봇을 구동하지 않는다. 실제 launch·설정·종료 절차는 [실행 기록](../ws_cobot_pjt/ws_cobot1/doc/README.md)에 작성한다.

## 팀 공유 절차

1. 검토와 최초 초기화·PR 반영 후 같은 C-2 저장소를 clone한다. 기존 강사 작업 폴더를 덮어쓰지 않는다.
2. 같은 상대 경로에 작업한다. 개인 홈·상위 폴더 이름은 달라도 된다.
3. 외부 패키지는 [DEPENDENCIES.md](DEPENDENCIES.md)의 확인된 출처·버전으로 각자 설치한다. 미정 항목은 준비 완료로 취급하지 않는다.
4. 팀 소스·문서·설정 예제·의존성 잠금 파일을 PR로 공유한다. build/install/log/node_modules와 비밀 값은 공유하지 않는다.
5. 다른 팀원이 경로와 실행 방법을 재현하고 검토한다. 코드 병합과 실기 검증은 구분한다.

미니 기능을 메인에 사용할 때는 별도 Issue를 만들고 필요한 로직만 ws_cobot1/src로 옮긴다. 메인의 장비·제어 계층·단위·좌표계에서 재검증하고 원래 실습 기록과 연결한다.

근거: 사용자 제공 강사 구조(2026-09-16), [두산 공식 Jazzy 저장소](https://github.com/DoosanRobotics/doosan-robot2/tree/jazzy), [ROS Jazzy 워크스페이스 공식 원문](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-Client-Libraries/Creating-A-Workspace/Creating-A-Workspace.rst).
