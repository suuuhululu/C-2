# 워크스페이스와 실행 PC

기준: 2026-09-25 `origin/main` `987a3b7`. 프로젝트 기준은 M0609·ROS 2 Jazzy다. **팀 소스의 구현 상태와 각 PC의 설치·동작 상태는 다르다.** 9/17~23의 변경 경과는 날짜별 일지와 검증 기록에 보존한다.

## 저장소 배치

| 경로 | 현재 용도 |
| --- | --- |
| `ws_cobot_pjt/ws_cobot1/src/` | 팀 ROS 패키지 `c2_interfaces`, `c2_path`, `c2_process`. 세 패키지의 노드·빌드 설정이 있다. [패키지 안내](../ws_cobot_pjt/ws_cobot1/src/README.md) |
| `ws_cobot_pjt/backend/`, `ws_cobot_pjt/frontend/` | FastAPI·SQLite·관리 파일과 React HMI. 기본 MOCK, ROS SIM, 설정을 갖춘 REAL 연결 코드를 포함한다. |
| `ws_cobot_pjt/ws_cobot1/doc/` | 팀 노드의 [현재 실행·설정 안내](../ws_cobot_pjt/ws_cobot1/doc/README.md) |
| `ws_cobot_pjt/ws_dsr/src/` | 실행 PC에 따로 준비하는 외부 로봇·그리퍼 소스. 기본 Git 제외이지만 제어권 관측 패치 4개 파일은 추적한다. 정확한 설치본은 PC별로 확인한다. |
| `ws_cobot_pjt/docs/`, `docs/` | 시스템 계약·검증 기록·일지, 공통 환경·협업 문서 |

`c2_process/node.py`, `setup.py`, `PrepareWorkpiece.action`은 main에 있다. `c2_process/launch/`에는 `.gitkeep`만 있고 `process.launch.py`는 없다. 과거 계획의 `workcell.yaml`·`tools.yaml`도 없다. 현재 설정은 코드가 읽는 JSON·HMI 관리 자산 및 실행 프로파일 계약을 확인한다. 존재하지 않는 launch/YAML을 실행 절차로 안내하지 않는다.

## PC와 워크스페이스의 역할

```text
실행 PC의 ROS 2 Jazzy
  ├─ ws_cobot_pjt/ws_dsr: 외부 두산 드라이버·의존성 overlay (PC별 설치)
  └─ ws_cobot_pjt/ws_cobot1: 팀 인터페이스·경로·공정 overlay
       ↔ backend/프런트엔드 HMI
```

현재 편집 PC의 저장소와 실행 PC의 외부 드라이버·제어기·에뮬레이터 설치는 별개다. 이 문서에서 실행 PC의 실제 커밋, ROS domain, 서비스 prefix, TCP, 하중, 그리퍼 모델·배선·피드백을 확정하지 않는다. 현장 PC에서 확인한 값만 배포 설정에 사용한다. 수업 지정 [`cobot_rg2`](https://github.com/ahnisinc/cobot_rg2)의 9/16 설치·가상 이동 보고는 [외부 의존성 기록](DEPENDENCIES.md)에 출처와 확인 주체를 구분했다.

`ws_dsr`와 `ws_cobot1`은 각각 `src/build/install/log`를 사용한다. 같은 `dsr_msgs2`를 여러 원본에서 중복 배치하거나 한 PC의 빌드 결과를 다른 PC에 복사하지 않는다. 팀의 주 ROS 소스는 `ws_cobot1/src/`에서 공유한다. C-2가 추적하는 외부 드라이버 패치 4개 파일은 실제 설치 원본과 대조해야 하며, 그것만으로 외부 드라이버 전체를 빌드할 수 없다. 외부 저장소의 `.git`을 지우거나 기존 설치를 새 clone으로 덮어쓰지 않는다.

## 빌드·실행 범위

다음은 **외부 소스와 Jazzy가 설치된 실행 PC**에서만 적용하는 순서다. 저장소 루트에서 각 워크스페이스의 실제 위치·설치본을 확인한 뒤 사용한다. `colcon list`로 패키지를 먼저 확인한다.

```bash
source /opt/ros/jazzy/setup.bash
(cd ws_cobot_pjt/ws_dsr && colcon list && colcon build --symlink-install)
source ws_cobot_pjt/ws_dsr/install/local_setup.bash
(cd ws_cobot_pjt/ws_cobot1 && colcon list && colcon build --symlink-install)
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash
```

이 명령은 소스가 준비된 워크스페이스의 빌드 예시이며 로봇을 구동하지 않는다. `ws_dsr`가 없는 편집 PC에서는 팀 코드 검토·문서·Python 모의 시험을 할 수 있지만 외부 드라이버의 실기 준비 완료라고 표시하지 않는다. `c2_process`는 `dsr_msgs2` 실행 의존성이 있으므로 실행 PC의 외부 overlay와 같은 Jazzy 환경을 확인한다.

HMI 실행기 `run_monitor.py`의 기본은 MOCK이다. ROS SIM 공정 연결은 `--transport ros --process-integration`을 사용하고 공정 노드는 별도 기동한다. REAL HMI는 `--transport ros --mode REAL` 및 확인된 준비·실행 설정을 받는다. REAL 공정 진입점 `real_process_node`와 외부 드라이버도 별도 기동 대상이다. 구체적인 옵션은 [팀 실행 안내](../ws_cobot_pjt/ws_cobot1/doc/README.md), [HMI 안내](../ws_cobot_pjt/backend/README.md)에 있다. 코드와 가상 장치 시험이 존재하지만 실제 M0609의 측정→경로→조각 전체 완료는 별도 현장 검증 항목이다.

## 팀 공유 절차

1. 팀 코드는 C-2의 같은 경로에 PR로 공유한다. `build/install/log`, `node_modules`, 운영 DB와 비밀 값은 공유하지 않는다.
2. 외부 패키지는 실행 PC마다 원본 URL, 커밋, 로컬 수정, ROS·제어기·에뮬레이터 버전을 확인해 [의존성 기록](DEPENDENCIES.md)에 남긴다.
3. 빌드, 가상 장치 통합, 실제 로봇 측정, 실제 가공을 서로 다른 검증 결과로 기록한다. 요청 수락과 동작 완료·정지 확인도 분리한다.

워크스페이스 구성의 일반 원리는 [ROS 2 Jazzy 공식 워크스페이스 튜토리얼](https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Creating-A-Workspace/Creating-A-Workspace.html)을 참고한다. 두산 패키지의 기본 참고 소스는 [공식 doosan-robot2 Jazzy 브랜치](https://github.com/DoosanRobotics/doosan-robot2/tree/jazzy)이며 수업 배포본의 로컬 수정·설치 버전과 동일하다고 추정하지 않는다.
