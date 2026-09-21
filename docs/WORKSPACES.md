# 워크스페이스와 팀 공유

2026-09-21 최신 main `19ef4c6`: 팀 앱은 React·FastAPI·SQLite로 구현돼 있고, `c2_interfaces`와 `c2_path`는 ROS 2 Jazzy 패키지로 존재한다. HMI는 MOCK뿐 아니라 native rclpy로 `c2_path` Action 서버를 호출해 관리 산출물과 미리보기를 읽는 부분 통합까지 검증했다. 이 경로는 `SIMULATION/test_only`이며 `c2_process`의 공정 노드·패키지/launch·실행 YAML과 전체 로봇 통합은 아직 없다. 현재 상태는 [진행 현황](REVIEW_STATUS.md)과 [0920 일지](../ws_cobot_pjt/docs/daily/2026-09-20.md)를 우선한다.

2026-09-19 후속: 현재 HMI는 React, 서버는 FastAPI·SQLite, 공통 c2_interfaces는 Jazzy 빌드 가능한 패키지다. 편집 PC에서 타입 빌드·모의 시험을 수행했으며 실제 로봇 통합 검증과 구분한다. 아래 Mac/미구현 표기는 당시 환경 기록이다. [최신 구조·구현 범위](../ws_cobot_pjt/docs/SYSTEM_STRUCTURE.md)를 따른다. ws_dsr 외부 설치는 변경하지 않았다.

2026-09-17 사용자 요청에 따라 메인 프로젝트 중심으로 정리했다. 팀 코드는 C-2에서 공유하고, 외부 실행환경은 각 PC에 별도로 준비한다. 사용자는 공용 MSI Ubuntu에서 Docker 에뮬레이터를 통한 가상 로봇 동작을 확인했다고 보고했다. 이 문서 수정 작업에서 설치·구동을 직접 검증하지는 않았다.

외부 소스 제외 규칙은 PR #3, 아래 메인 중심 구조와 양식 정리는 9/17 PR #4로 main에 반영됐다. 현재 게시·병합 상태는 [진행 현황](REVIEW_STATUS.md)을 확인한다.

## 프로젝트 경로

| 경로 | 용도 |
| --- | --- |
| ws_cobot_pjt/ws_cobot1/src | 팀 공정 ROS 패키지 |
| ws_cobot_pjt/ws_cobot1/doc | ROS 실행·설정·재현 절차 |
| ws_cobot_pjt/ws_dsr | 로봇·그리퍼 외부 실행환경 |
| ws_cobot_pjt/docs | 메인 기획·통합·검증 |
| docs | 공통 환경·일정·Git 협업 |

서버 코드는 backend/app, 화면 코드는 frontend/src·public, 컨테이너 구성은 docker에 둔다. DartPlatform은 로컬 설치 위치 안내다. GitHub 설정과 자동화는 기존 위치를 유지하고, Issue는 main(프로젝트 기능)과 common(공통 환경·협업)으로 구분한다.

## 분리 원칙

```text
ROS 2 Jazzy → ws_cobot_pjt/ws_dsr → ws_cobot_pjt/ws_cobot1
```

두 ROS 워크스페이스는 각자 src/build/install/log를 사용한다. ws_dsr는 로봇·그리퍼 기반 환경이고 ws_cobot1은 팀 공정 환경이다. 같은 dsr 패키지를 여러 src에 중복 배치하거나 서로 다른 환경의 빌드 결과를 복사하지 않는다.

팀 코드 폴더마다 새로 git init하지 않는다. 수업 절차로 받은 외부 `cobot_rg2`는 `ws_dsr/src/.git`을 가진 별도 저장소이며 그대로 보존한다. C-2는 `ws_dsr/src/` 전체를 제외하므로 외부 원본은 [의존성 기록](DEPENDENCIES.md)에 따라 준비하고 출처·버전만 공유한다. 팀의 메인 ROS 패키지와 launch 파일은 고유한 패키지명으로 `ws_cobot1/src/`에 둔다.

## 현재 준비 범위

- 메인 실행환경은 수업 지정 `ahnisinc/cobot_rg2`를 사용한다. PC별 소스·설치·실행 확인 범위는 [의존성 기록](DEPENDENCIES.md)에 구분한다.
- `ws_dsr/src`는 로컬 외부 원본 전용이며 `.gitkeep`을 공유하지 않는다. 새 C-2 clone에는 이 폴더가 없고, 외부 원본을 clone할 때 생성된다. 기존에 설치한 PC의 폴더·버전은 변경하지 않는다.
- 상위 개인 프로젝트의 doosan 폴더는 이동·복사하지 않았다. 2026-09-16 확인한 Jazzy 커밋은 의존성 기록에 남겼다.
- 강사 예시는 RG2 환경이지만 실제 장비 모델·배선·통신·피드백은 미확인이다. 로봇 기준은 M0609, ROS 기준은 Jazzy다.
- DartPlatform은 README만 공유한다. 프로그램·Logs, ROS build/install/log, frontend node_modules는 각 PC에서 생성하고 Git에서 제외한다.
- backend·frontend는 실행 코드와 잠금 파일이 있다. `python3 ws_cobot_pjt/run_monitor.py`의 기본은 MOCK이고, Jazzy overlay를 source한 뒤 `--transport ros`를 사용하면 c2_path와 HMI의 SIM 부분 통합을 실행한다. REAL 공정 실행 명령은 아니다.
- docker 폴더의 용도와 외부 두산 에뮬레이터 설치는 구분한다. 저장소 앱 구현만으로 각 PC의 공급자 드라이버·에뮬레이터 버전이 고정되는 것은 아니다.
- 검증 환경은 기록마다 다르다. c2_interfaces는 Ubuntu/Jazzy, HMI↔c2_path는 macOS의 별도 Jazzy 환경에서 확인됐고, 실제 M0609 시험은 9/19 기록 범위다. 한 환경의 통과를 다른 환경의 완료로 확장하지 않는다.

## 빌드·환경 적용 위치

아래는 Ubuntu Jazzy와 필요한 소스·의존성이 준비된 이후의 경로 예시다. C-2를 clone하는 것만으로 외부 실행환경이 설치되지는 않는다. 실제 제어기 버전별 빌드 옵션은 제조사 문서와 대조한다.

각 블록은 C-2 저장소 루트(현재 로컬 폴더명 collaborative)에서 시작하는 새 Bash 터미널 기준이다. 이미 대상 워크스페이스를 source한 터미널에서 다시 빌드하지 않는다.

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

C-2 전체나 ws_cobot_pjt 전체에서 colcon build하지 않는다. 이 명령은 환경 준비이며 로봇을 구동하지 않는다. 실제 launch·설정·종료 절차는 [실행 기록](../ws_cobot_pjt/ws_cobot1/doc/README.md)에 작성한다.

## 팀 공유 절차

1. 현재 main을 clone하거나 기존 작업을 보존한 뒤 병합된 변경을 받는다. 기존 강사 작업 폴더를 덮어쓰지 않는다. 메인 중심 구조는 PR #4로 병합됐으며 후속 변경도 PR을 통해 공유한다.
2. 같은 상대 경로에 작업한다. 개인 홈·상위 폴더 이름은 달라도 된다.
3. 외부 패키지는 [DEPENDENCIES.md](DEPENDENCIES.md)의 확인된 출처·버전으로 각자 설치한다. 미정 항목은 준비 완료로 취급하지 않는다.
4. 팀 소스·문서·설정 예제·의존성 잠금 파일을 PR로 공유한다. build/install/log/node_modules와 비밀 값은 공유하지 않는다.
5. 다른 팀원이 경로와 실행 방법을 재현하고 검토한다. 코드 병합과 실기 검증은 구분한다.

근거: 사용자 제공 강사 구조(2026-09-16), [두산 공식 Jazzy 저장소](https://github.com/DoosanRobotics/doosan-robot2/tree/jazzy), [ROS Jazzy 워크스페이스 공식 원문](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-Client-Libraries/Creating-A-Workspace/Creating-A-Workspace.rst).
