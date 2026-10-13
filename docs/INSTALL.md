# 설치·환경 설정

이 안내는 README의 실행용 구성을 대상으로 한다. Ubuntu 24.04 / Python 3.12.3 / ROS 2 Jazzy가 현장 기준이다. Windows/macOS 및 다른 장치 배치는 실물 환경으로 검증하지 않았다.

## 저장소 받기

이 문서가 포함된 브랜치/커밋을 받는다. PR 검토 중에는 `codex/main-runtime-20261013`, main 병합 후에는 main을 사용한다. 기존 현장 checkout을 덮어쓰지 않고 새 폴더에서 준비한다.

```bash
git clone --branch codex/main-runtime-20261013 --single-branch https://github.com/suuuhululu/C-2.git C-2-runtime
cd C-2-runtime
```

## 기본 통합·DB

저장소 루트에서 별도 Python 환경을 만든다. ROS 장치 연결이 필요하면 ROS Python을 사용할 수 있도록 현장 환경의 `--system-site-packages` 정책을 적용한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
# DB·웹을 사용할 경우
python3 -m pip install -r requirements-history.txt
```

`requirements.txt`는 기존 검증 버전의 PyQt5·numpy·scipy·jsonschema다. GUI에는 Qt 시스템 라이브러리·화면 환경·한글 폰트도 필요하다. `QT_QPA_PLATFORM=offscreen`은 화면 없는 검증용 설정이다.

DB에는 별도 PostgreSQL이 필요하다. Python 드라이버 설치가 DB 서버/계정 생성은 아니다. 이 구성은 Docker/Compose를 포함하지 않는다.

```bash
export HISTORY_DATABASE_DSN='postgresql://DB_USER@127.0.0.1:DB_PORT/DB_NAME'
export HISTORY_WEB_URL='http://127.0.0.1:8765'
```

주소·포트·DB 이름은 실제 환경 값으로 바꾼다. 비밀번호는 개인 환경/비밀번호 파일 등으로 제공하고 Git·문서·로그에 기록하지 않는다. CLI/웹은 PostgreSQL의 PGHOST/PGDATABASE/PGUSER/PGPASSWORD 환경도 사용할 수 있지만 HMI 로그인·저장 연결에는 HISTORY_DATABASE_DSN을 설정한다. HMI와 웹은 같은 DB를 사용한다.

`.env.history.example`은 직접 실행용 변수의 빈 예제다. **앱이 이 파일을 자동으로 읽지 않으므로** 필요한 값을 실행 환경에 제공해야 한다. 실제 비밀번호·계정·Job 데이터는 소스와 함께 복사되지 않는다.

## C 실제 LLM·음성

기본 offline C는 외부 API/음성 장치를 사용하지 않는다. live C에서는 `C_DESIGN_USE_LLM=1`과 `--c-mode live`를 함께 설정한다. LLM/STT/TTS 키는 서로 자동 대체되지 않는다.

| 기능 | 현재 코드가 읽는 변수 |
|---|---|
| LLM | `OPENAI_LLM_API_KEY` |
| STT | `OPENAI_API_KEY` |
| TTS | `OPENAI_TTS_API_KEY` |
| 선택 모델 | `OPENAI_MODEL`, `OPENAI_JUDGE_MODEL`, `OPENAI_AUX_MODEL`, `OPENAI_STT_MODEL`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE` |

기존 현장 오디오 의존성은 sounddevice 0.5.6이며 PortAudio·마이크·스피커 환경도 필요하다. 별도 개인 환경의 API/model 설정을 사용하고 키를 저장소에 넣지 않는다. 모델 이름·접근 권한·응답 품질은 실제 사용하는 계정에서 확인한다.

## D 실제 장치 환경

현장은 M0609·RG2·GripperDA_v4·ROS Jazzy·검증된 DRCF2 overlay를 사용한다. 드라이버 전체·build/install·가상환경을 이 저장소에 넣지 않는다.

- [Doosan upstream](https://github.com/doosan-robotics/doosan-robot2)의 기준 commit과 우리 패치는 [source_reference.json](../robot_control_integration/driver/source_reference.json), [패치](../robot_control_integration/driver/drcf2-release-version-query.patch)에 있다.
- `m0609_rg2_bringup`, ROS 메시지·rclpy·sensor_msgs·카메라 환경, 현장 DRCF2 runtime·READY.json은 별도로 확보한다. 드라이버 patch만으로 이 전체 workspace가 만들어지는 것은 아니다.
- cobot2_ws의 다른 DRCF 빌드와 별도 DRCF2 overlay를 혼용하지 않는다. 실제 로드 경로·기준을 확인하고 현장 운영자가 준비한다.
- 현장 기본 라이브러리는 numpy 1.26.4 / scipy 1.11.4 / pymodbus 3.6.9 / sounddevice 0.5.6 / PyQt5 5.15.10이다. pymodbus·sounddevice는 REAL/음성 사용 환경에 설치한다.

아래는 이미 준비된 ROS/driver 환경을 셸에 적용하는 예다. 이 단계는 로봇 노드 시작·재빌드 명령이 아니다.

```bash
export C2_BASE_WS='/실제/cobot2_ws'
export C2_DRIVER_ROOT='/실제/검증된/drcf2'
source /opt/ros/jazzy/setup.bash
source "$C2_BASE_WS/install/local_setup.bash"
COLCON_CURRENT_PREFIX="$C2_DRIVER_ROOT/install" source "$C2_DRIVER_ROOT/install/local_setup.bash"
export ROS_DOMAIN_ID=20
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export C2_ROBOT_ROOT="$PWD/robot_control_integration"
```

기존 현장 연결값은 Robot `192.168.1.100:12345`, namespace `dsr01`, RG2 `192.168.1.1`, TCP `GripperDA_v4`, Tool `ToolWeight0`이다. 포함된 교시는 같은 현장 배치의 원자료다. 다른 로봇/보드 배치에 좌표를 그대로 적용하지 않는다.

`scripts/cad_trial_ms02.sh`와 `scripts/roboton2.launch.py`는 ms-02의 개인 설정·workspace 절대경로를 포함한다. 다른 PC는 RUN의 직접 실행 방법을 사용한다. 이 PR은 launcher·교시·속도·힘·API 동작을 새로 변경하지 않는다.

## D 제스처 모델

실제 제스처 연결은 아래 모델/라이브러리를 요구한다. **Git clone에는 포함되지 않는다.** 확인 버튼은 손 분류 실패의 대체 입력이며, 모델/카메라 누락까지 생략하는 모드는 아니다.

```text
robot_control_integration/logs/handover/stage02/hand_landmarker.task
robot_control_integration/logs/handover/model-deps/
```

현장 운영자에게 사용 중인 모델과 출처·라이선스·hash·의존 환경을 받아 같은 위치에 준비한다. 동일 환경의 현장 사본은 기준 자료가 될 수 있지만 다른 OS/Python/CPU에 바이너리 의존성을 그대로 복사하지 않는다. 기존 현장 안내의 model-deps는 MediaPipe 1.0.1 / numpy 2.5.3 / opencv-contrib-python 5.0.0.93이며, 기본 앱 numpy와 분리된 경로를 사용한다. 이 버전은 현장 기록이고 모든 새 PC의 설치 호환성을 보장하지 않는다.

새 PC 전체 설치, 모델 재다운로드/hash 검증, 외부 bringup 구성의 재현은 이 실행용 배포 준비에서 수행하지 않았다. 필요한 외부 파일을 준비한 뒤 현장 검증한다.
