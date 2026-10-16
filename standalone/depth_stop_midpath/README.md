# 중간 경로 Depth 정지 standalone

공급판과 조립판 사이의 주황 장애물을 손목 Depth 카메라로 검출하고, 활성 목표를 한 번 취소해 정지·파지를 확인하는 독립 SIM 실행본입니다. 공급판·조립판은 초록색이며 전달판과 큰 배경판은 없습니다. 장애물은 45×45×65 mm, 바로 아래의 알려진 받침은 45×45×4 mm입니다.

## 설치와 실행

Ubuntu 24.04 x86_64, Isaac Sim **6.1.0 전체 바이너리 설치본**, `/opt/ros/jazzy`의 ROS Jazzy와 **MoveIt 2.12.4**가 필요합니다. 새 실행 기록을 위한 여유 디스크는 8 GiB 이상이어야 합니다. GUI 데스크톱의 `DISPLAY`를 그대로 사용합니다.

저장소 루트에서:

```bash
cd standalone/depth_stop_midpath
./setup.sh --isaac-root "$HOME/isaacsim"
./start.sh --run
```

Isaac Sim이 `~/isaacsim`, `/opt/isaacsim` 또는 기존 Omniverse 설치 위치에 있으면 `./setup.sh`만 실행해도 됩니다. 다른 경로는 `--isaac-root` 또는 `ISAAC_SIM_ROOT`로 지정합니다. 설치 경로는 Git에서 제외한 `runtime.local.json`에 저장됩니다.

`setup.sh`는 배포 파일의 해시와 설치 버전을 검사하고, `requirements.lock`의 해시로 검증한 Python 3.12 wheel을 `.runtime/`에 설치한 다음 CPU 사전 점검을 실행합니다. 최초 설치에는 PyPI 연결과 Ubuntu `python3-pip`가 필요합니다. **루트 `requirements.txt`와 전역 Python 환경은 바꾸지 않습니다.**

ROS 패키지가 빠진 PC에서는 ROS Jazzy 저장소를 설정한 뒤 필요한 항목을 설치합니다. MoveIt은 바이너리 ABI가 같은 2.12.4여야 합니다.

```bash
sudo apt install python3-pip libfcl0.7 libassimp5 libyaml-cpp0.8 \
  ros-jazzy-rclpy ros-jazzy-control-msgs ros-jazzy-controller-manager-msgs \
  ros-jazzy-moveit-ros-planning ros-jazzy-moveit-kinematics \
  ros-jazzy-moveit-planners-ompl ros-jazzy-ros2-control ros-jazzy-ros2-controllers
```

다른 Isaac Sim·플래너는 먼저 정상 종료하세요. 실행기는 충돌하는 프로세스를 발견하면 시작을 거절합니다.

```bash
./start.sh --check                  # CPU 점검만 실행, SIM/GPU 시작 없음
./start.sh --run --exit-after-stop  # 정지 검증 후 자동 종료 옵션
```

초기 파지·카메라 기준 2프레임의 새 검증·새 MoveIt 경로와 전체 FCL 검사를 마친 뒤 이동합니다. 검출 후 같은 UUID의 목표를 한 번만 취소하고, STOP·파지·명령 수0·새 센서 2프레임과 원자료 저장을 확인합니다. 그 뒤 **Isaac Sim은 일시정지 상태로 열려 있습니다**. 창을 닫으면 정상 종료와 최종 `runs/<시각_UUID>/result.json` 저장을 진행합니다.

오류가 나면 표시된 실행 폴더의 `native.sdk.log`를 확인하세요. 자동 재시도·그리퍼 개방·재개·추가 목표·SDK 제어·실물 로봇 제어는 포함하지 않습니다.

## 필수 파일의 범위

`snapshot/`은 검증된 실행기가 복제하는 **280개 입력**으로 한정했습니다. 보존본 1,598개에서 과거 STOP 메타데이터·이미지·Depth 배열·영상·로그 등 1,318개를 제외했습니다. 원 소스 126개 실행 시점 핀, 모델 38개, USD·교시·보정 입력·비교 목록·선택한 계산 라이브러리는 원래 바이트를 유지합니다. 과거 시험 결과를 새 검증으로 사용하지 않습니다.

기존 앱·ROS 인터페이스·루트 의존성은 변경하지 않습니다. 매 실행은 자신의 새 폴더 안에 경로를 연결한 입력을 만듭니다. snapshot의 옛 PC 경로는 출처 정보이며 해당 프로젝트 설치는 필요하지 않습니다. 모델·선택한 ELF 바이트가 바뀌면 기존 검사가 거절합니다.

`FILES.sha256`은 가변 `.runtime/`·`runtime.local.json`·`runs/`·`verification/`을 제외한 배포 파일의 상대 경로 검사입니다. `setup.sh`가 매번 확인합니다.

## 검증 상태

원 PC의 전체 실행본에서는 실제 주황 장애물 118픽셀 검출·같은 UUID 취소1회·ACK0·CANCELED5/error0·STOP·파지·창 유지·정상 종료를 확인했습니다. source→cancel은 0.1833345 SIM초로 기존 0.4 SIM초 정책 안에 있습니다.

이 Git용 280개 입력 구성의 새 CPU·이동 경로 검증은 `VALIDATION.json`에 기록합니다. 원 PC의 성공을 이 구성이나 다른 PC의 새 SIM 성공으로 표시하지 않습니다. 위험도·3D 오차 검증, 회피·재계획·실물 운반은 이 시험의 범위 밖입니다.
