# 다른 PC에서 round2 Robot 시험 브랜치 실행하기

[PR #36](https://github.com/suuuhululu/C-2/pull/36)의 공급 MoveL·40N 시험에 슬롯1~5 정책·외부 DRCF2 경로·다른 PC용 roboton2를 추가한 후속 안내다. [round1 PR #41](https://github.com/suuuhululu/C-2/pull/41)의 변경을 PR #40이 병합된 `codex/integration-round2 @ 8818518`에 동일하게 반영했다.

대상 저장소: `suuuhululu/C-2` · 후속 시험 브랜치: `codex/round2-trial-local-fixes-20261013` · PR 기준 브랜치: `codex/integration-round2`.

이 안내의 REAL 명령은 실제 Robot·그리퍼를 움직인다. B는 가짜 관측이다. `--c-mode offline`도 C 대화만 오프라인이며 Robot은 REAL이다. 장치를 연결하지 않는 검사는 아래 오프라인 검증 절차를 사용한다. 기존 Job을 자동 복원하지 않으며 새 시험으로 시작한다.

## 이번 브랜치 동작

| 구간 | 명령/설정 |
|---|---|
| 공급 재고·순환 | full-real에서 종류/색상별1→2→3→4→5→1. 사용자 전제: 1~5번 항상 보충, 6번 항상 비어 있음. 슬롯6 준비·실행 문서 생성·기존 문서 재개 차단 |
| 빈 상태에서 공급판 진입 | MoveB 비활성화. 현재 위치 상승 → BODY_BYPASS → SUPPLY_TRANSIT → **이번 Step 슬롯 상부**를 단독 MoveL로 진행. 이전 슬롯 복귀 없음 |
| 공급 슬롯 정렬·집기 | 슬롯 상부 최종 정렬 24mm/s·12mm/s² → 집기 하강 24mm/s·12mm/s² → 기존 폭35mm·파지 힘40N |
| 블록을 쥐고 조립판으로 이송 | 기존 MoveB 유지. 이송276.48mm/s·96mm/s², 반경40mm. 조립판 하강 직전 목표까지 진행 |
| 조립판 결착 | 접촉 전 위치 하강24mm/s·12mm/s² → 결착 하강6mm/s·6mm/s² → **XYZ 전체 반력 크기40N 이상에서 STOP** → 실제 정지 확인 → 개방 |
| 결착 힘의 의미 | 원하는 힘40N을 명령하는 힘 제어가 아니다. 하강하면서 측정한 `sqrt(Fx²+Fy²+Fz²)` 임계값이다. 임계값 도달은 끝까지 결착됐다는 실물 증거가 아니다 |
| 정지/블렌딩 | 정지 속도 허용5mm/s·5°/s, 위치1mm·자세1°. loaded 블렌딩 경유10mm·5°, 경로 폭80mm(반경40+여유40), timeout 최소45초. 필요 시 마지막 목표 MoveL 후 최종1mm·1° 확인 |
| 조립 위치 보정 | 노랑/파랑6점90° Base X +1.5mm, 2×2 회전90° Base X −1.5mm. 추가로 **조립 Grid x>11은 Base X −1mm**. 서로 합산하며 공급판 교시는 변경하지 않음 |
| 손/엄지척 확인 | 인계·도움 준비·조립 완료·정렬의 현재 요청에 화면 확인 버튼 사용 가능. 재개 버튼과 확인 버튼은 별개 |
| 알려진 이동 timeout | 실제 정지·파지·명령 결과가 확인되는 체크포인트에서 재개. 블렌딩 마지막 목표 근처이면 마지막 목표만 MoveL로 이어감. 알 수 없는 개방/파지 결과는 자동 반복하지 않음 |

위 속도는 TCP 직선 이동의 설정값이다. 관절 MoveJ 속도 설정이 아니다. 비결착 구간에는 앱의35/40N 정지 제한을 적용하지 않으며 제어기 자체 고장/충돌 상태, 파지·TCP/Tool·피드백 검사까지 해제하는 변경은 아니다. Robot의 결착이 없는 사람 PRESS/인계 방식에는 자동 결착을 추가하지 않는다.

슬롯은 집기 성공 확인 시에만 진행하며 중복 이벤트·재검사로 추가 소비하지 않는다. A에는 선택된1~5번 예약을 전달하고 HMI의 다음 슬롯도 같은 값을 표시한다. 공급판을5칸짜리로 재계산하거나6번 교시 자료를 삭제하지 않는다. 6번 교시는 기존 좌표 보정 근거이며, 별도 MOCK/레거시 경로의 기본6슬롯·설계 최대40블록·공통 계약은 유지한다. 슬롯6 제외는 그 슬롯 접근의 특이점 정지에 대한 운영 우회이며 다른 경로의 물리 성공을 보장하지 않는다.

## 1. 브랜치 받기

새 폴더를 사용하면 다른 PC의 기존 작업을 보존할 수 있다. private 저장소라면 해당 PC의 GitHub 인증이 먼저 필요하다.

```bash
git clone --branch codex/round2-trial-local-fixes-20261013 --single-branch   https://github.com/suuuhululu/C-2.git "$HOME/C-2-robot-trial"
cd "$HOME/C-2-robot-trial"
git branch --show-current
git log -1 --oneline
export C2_ROBOT_ROOT="$PWD/robot_control_integration"
```

이미 이 전용 checkout을 받았다면, 변경이 없는지 확인한 후 같은 브랜치만 갱신한다. `pull --ff-only`가 실패하면 로컬 변경을 확인하고 중단한다. 강제 덮어쓰기는 사용하지 않는다.

```bash
cd "$HOME/C-2-robot-trial"
git status --short
git fetch origin codex/round2-trial-local-fixes-20261013
git pull --ff-only origin codex/round2-trial-local-fixes-20261013
export C2_ROBOT_ROOT="$PWD/robot_control_integration"
```

`scripts/cad_trial_ms02.sh`는 기존 ms-02 전용 경로를 유지한다. `scripts/roboton2.launch.py`는 `C2_ROBOT_ROOT` 또는 checkout 내부 `robot_control_integration`을 사용한다. `C2_ROBOT_ROOT`를 예전 외부 D 폴더로 지정하면 후속 D 코드가 실행되지 않는다.

## 2. 해당 PC의 기존 장치 환경 준비

현재 현장 구성은 Ubuntu/ROS2 Jazzy, Doosan M0609 DRCF2 드라이버, RG2 그리퍼다. 기본 Python의 현장 버전은 NumPy1.26.4·SciPy1.11.4·pymodbus3.6.9·sounddevice0.5.6·PyQt5 5.15.10이다. 아래는 현장 환경의 재현값이며 새 버전 추천이 아니다. ROS의 rclpy·dsr_msgs2·sensor_msgs·cv_bridge, `m0609_rg2_bringup`과 검증된 DRCF2 overlay는 Git clone에 포함되지 않는다.

ROS/드라이버를 설치한 **기존 환경**에서 작업한다. 필요하면 ROS Python을 유지하는 별도 가상 환경에 앱 의존성을 준비한다. PortAudio 및 ROS/Qt 시스템 라이브러리는 해당 PC에 이미 설치되어 있어야 한다.

```bash
cd "$HOME/C-2-robot-trial"
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python3 -m pip install -r requirements-test.txt   numpy==1.26.4 scipy==1.11.4 pymodbus==3.6.9 sounddevice==0.5.6
```

모든 실행 터미널에서 다음 환경을 준비한다. `C2_BASE_WS`와 `C2_DRIVER_ROOT`는 해당 PC에 설치된 실제 경로로 고친다. 드라이버 바이너리를 다른 OS/CPU/Python 환경에 그대로 복사하지 않는다. 해당 PC에서 검증된 DRCF2 빌드와 `READY.json`이 필요하다.

```bash
export C2_BASE_WS="$HOME/cobot2_ws"
export C2_DRIVER_ROOT="$HOME/c2-drcf2"
source /opt/ros/jazzy/setup.bash
source "$C2_BASE_WS/install/local_setup.bash"
COLCON_CURRENT_PREFIX="$C2_DRIVER_ROOT/install" source "$C2_DRIVER_ROOT/install/local_setup.bash"
export ROS_DOMAIN_ID=20
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
cd "$HOME/C-2-robot-trial"
source .venv/bin/activate
export C2_ROBOT_ROOT="$PWD/robot_control_integration"
```

기존 실기 연결값은 Robot `192.168.1.100:12345`, namespace `dsr01`, 그리퍼 `192.168.1.1`, TCP `GripperDA_v4`, Tool `ToolWeight0`이다. 이 설정은 **같은 현장 Robot·공급판·조립판 배치**의 시험용이다. 다른 장치/배치에는 포함된 교시 pose를 그대로 실행하지 말고 해당 장치의 교시를 준비한다. 사용자별 최신 교시가 있다면 `logs/teaching-20261012`의 supply/assembly 파일이 저장소 fixture보다 먼저 선택된다. 새 clone은 `robot_control_integration/fixtures/teaching_sources/operator_*.json`을 사용한다.

## 3. 손 인식 모델과 개인 API 환경 준비

손 인식 모델/추가 라이브러리와 API 키는 저장소에 없다. 확인 버튼은 **영상 분류 실패**에 대한 대체 입력이다. Camera 자체 연결 실패/모델 누락까지 생략하는 모드가 아니다.

같은 Ubuntu·Python·CPU 환경이면 ms-02에서 쓰던 손 모델과 `model-deps`를 복사할 수 있다. `C2_SOURCE_HOST`를 ms-02의 실제 SSH 주소로 바꾼다. 다른 실행 환경이면 이 추가 라이브러리 환경을 해당 PC에서 별도로 준비한다. 현장 `model-deps`의 MediaPipe1.0.1·NumPy2.5.3·opencv-contrib-python5.0.0.93을 기본 앱 가상 환경의 NumPy와 한꺼번에 섞어 설치하지 않는다.

```bash
export C2_SOURCE_HOST='ms-02@MS02_IP'
export C2_SOURCE_D='/home/ms-02/C-2_협동2자료/work/c2-virtual-inputs-20261011/D_robot_control_integration_20261011/robot_control_integration_20261010'
mkdir -p "$C2_ROBOT_ROOT/logs/handover/stage02" "$C2_ROBOT_ROOT/logs/handover/model-deps"
scp "$C2_SOURCE_HOST:$C2_SOURCE_D/logs/handover/stage02/hand_landmarker.task"   "$C2_ROBOT_ROOT/logs/handover/stage02/hand_landmarker.task"
rsync -a "$C2_SOURCE_HOST:$C2_SOURCE_D/logs/handover/model-deps/"   "$C2_ROBOT_ROOT/logs/handover/model-deps/"
```

라이브 C 대화를 사용하려면 그 PC의 개인 환경에 `OPENAI_LLM_API_KEY`를 준비한다. 음성 입력은 `OPENAI_API_KEY`, 음성 출력은 `OPENAI_TTS_API_KEY`도 필요하다. 키를 코드/Git/로그에 넣지 않는다. 이미 개인 환경파일을 준비했다면 해당 PC에서만 읽는다. 모델 설정 파일은 선택 사항이다.

```bash
if [ -f "$HOME/.config/c2/api.env" ]; then source "$HOME/.config/c2/api.env"; fi
if [ -f "$HOME/.config/c2/models.env" ]; then source "$HOME/.config/c2/models.env"; fi
```

## 4. 장치를 움직이지 않는 확인

아래 첫 검사는 파일/라이브러리만 읽고 Robot API를 호출하지 않는다. 선택된 드라이버 경로와 저장된 라이브러리 해시도 확인한다. 모델은 존재 확인만 하며 카메라는 열지 않는다.

```bash
python3 - <<'CHECK'
import hashlib, json, os
from pathlib import Path
from ament_index_python.packages import get_package_prefix
import rclpy, pymodbus, sounddevice, numpy, scipy
from dsr_msgs2 import srv
from PyQt5.QtWidgets import QApplication
root=Path(os.environ['C2_ROBOT_ROOT'])
driver=Path(os.environ['C2_DRIVER_ROOT'])
ready=json.loads((driver/'READY.json').read_text())
libraries=ready['libraries'] if 'libraries' in ready else ready['packages']
for name in ('dsr_hardware2','dsr_controller2'):
    expected=driver/'install'/name
    assert Path(get_package_prefix(name)).resolve()==expected.resolve(), name
    library=expected/'lib'/('lib'+name+'.so')
    assert hashlib.sha256(library.read_bytes()).hexdigest()==libraries[name]['sha256'], name
for relative in ('scripts/robot_integration_runtime.py',
                 'fixtures/teaching_sources/operator_supply.json',
                 'logs/handover/stage02/hand_landmarker.task'):
    assert (root/relative).is_file(), relative
assert (root/'logs/handover/model-deps/mediapipe').is_dir(), 'mediapipe model-deps missing'
print('환경 파일 확인 완료 · 장치 연결/움직임 없음')
CHECK
```

이어서 장치/외부 네트워크 연결을 막은 D 테스트와 실제 A/D 문서→MOCK 실행을 확인한다. 테스트는 위 REAL 실행 명령과 다르다. 로그의 teaching 원자료가 없는 새 clone에서도 아래 검사는 fixture를 사용한다.

```bash
python3 scripts/test_robot_trial_offline.py
C_DESIGN_USE_LLM=0 QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1   python3 -m pytest tests/unit/test_mvp_supply_cycle.py tests/integration/test_mvp_full_real_adapter.py   tests/integration/test_cad_x_boundary_offset.py -q --tb=short
```

## 5. REAL 시험 실행

드라이버와 카메라가 이미 실행 중이면 중복 실행하지 않는다. 아래 bringup은 실제 장치에 연결한다. 터미널1에 2번의 ROS/드라이버 환경을 적용한 뒤 실행한다. 드라이버를 띄울 다른 제어 PC가 동시에 Robot 명령을 보내지 않도록 현재 현장 구성에 맞춘다.

```bash
ros2 launch m0609_rg2_bringup bringup.launch.py   mode:=real host:=192.168.1.100 port:=12345 camera:=false rviz:=false
```

터미널2에도 같은 환경을 적용한다. 다음 명령은 기존 TCP/Tool을 선택하며 필요 시 manual mode로 바꿨다가 원래 mode로 복원한다. pose/도구 무게 생성이나 arm 이동 명령은 없다.

```bash
cd "$HOME/C-2-robot-trial"
python3 scripts/robot_driver_setup.py   --config "$C2_ROBOT_ROOT/interfaces/assembly_contact_trial.json"
```

카메라는 기존 현장 방법으로 RGB topic `/camera/color/image_raw`를 제공한다. 이 guide에서 Camera 재보정/새 launch 구성을 생성하지 않는다.

### roboton2로 함께 시작하기

드라이버와 카메라를 새로 기동할 때는 위 bringup/setup 두 명령 대신 아래 복합 launch를 사용할 수 있다. 2번의 ROS·DRCF2·Python 환경을 적용한 뒤 실행한다. 현재 checkout의 설정을 사용해 드라이버 서비스 준비를 기다리고, 정지/STANDBY 및 실제 장치 여부 확인 후 기존 TCP `GripperDA_v4`·Tool `ToolWeight0`을 선택한다. 필요 시 manual mode를 사용한 뒤 원래 mode로 복원한다. TCP pose·Tool 무게를 새로 생성하거나 팔 이동을 명령하지 않는다.

```bash
export C2_CHECKOUT_ROOT="$PWD"
alias roboton2='ros2 launch "$C2_CHECKOUT_ROOT/scripts/roboton2.launch.py" camera:=true'
roboton2
```

성공 표시는 `ROBOTON2_READY`이고 실패 표시는 `ROBOTON2_SETUP_FAILED`다. 카메라가 따로 실행 중이면 `roboton2 camera:=false`를 사용한다. 이 복합 launch는 이미 실행 중인 드라이버를 교체하거나 중복 기동하지 않도록 운영자가 기존 프로세스를 확인한 뒤 사용한다. alias와 ROS/드라이버 환경 로딩은 각 PC의 개인 설정이며 바이너리·API 키와 함께 Git에 포함하지 않는다.

현재 실행 중인 DRCF2 검사에는 `C2_DRIVER_ROOT`가 선택한 `install` 경로를 사용한다. 변수가 없으면 D root 내부 `runtime/drcf2/install` 경로를 유지한다. 실제 dsr01 프로세스에 controller/hardware 두 라이브러리가 모두 로드됐는지 검사하며, 경로 불일치나 한쪽 누락은 계속 거부한다. 경로 불일치 시 선택한 overlay와 실행 중인 프로세스를 먼저 확인한다.

같은 터미널에서 전체 시험 창을 연다. **이 명령과 창의 시작 버튼은 실제 Robot을 실행한다.** 이번 공급 MoveL·40N·확인 버튼·x>11 보정이 이 명령에 적용된다.

```bash
export C_DESIGN_USE_LLM=1
python3 -m app.mvp_real_trial   --robot-root "$C2_ROBOT_ROOT" --execute --c-mode live   --contact-alignment-trial --log-directory logs/full-feature-real
```

키 없이 C를 가짜 대화로 시험하려면 다음 명령을 사용한다. **Robot은 여전히 실제로 움직인다.**

```bash
export C_DESIGN_USE_LLM=0
python3 -m app.mvp_real_trial   --robot-root "$C2_ROBOT_ROOT" --execute --c-mode offline   --contact-alignment-trial --log-directory logs/full-feature-real
```

실물 준비 항목을 확인한 뒤 창에서 채택 설계를 확인하고 시작한다. 인식이 실패하면 현재 단계의 확인 버튼을 누른다. 인계는 **손으로 받을 준비 완료**, 도움은 **도움 준비 완료**, 사람 조립 후에는 **조립 완료 · 검사 진행**이다. B 관측 불가는 **다시 검사**, 알려진 정지 보류는 **재개**를 사용한다. 재개는 손/엄지척 확인을 대신하지 않는다.

## 적용 확인과 문제 기록

새 Job의 JSONL과 실행 JSON이 `logs/full-feature-real`에 저장된다. 실행 문서에서 다음을 확인하면 이전 코드나 외부 D를 잘못 실행했는지 구분할 수 있다.

- `d_profile.supply_slot_count=5`, `supply_unavailable_slots=[6]`, `supply_slots_always_replenished=true`. 같은 종류/색상7개 예약은1,2,3,4,5,1,2이며 공급 교시6번을 사용하지 않는다.
- `d_profile.supply_approach_blending=false`, `force_stop_n=40`, `native_press.force_n=40`, `native_press.alignment_trial=true`.
- 공급 접근의 `ROBOT_MOVE_STARTED`: `BODY_EMPTY` → `SUPPLY_EMPTY` → `PICKUP_HIGH` → `PICKUP_LOWER`. 공급 구간 `ROBOT_SINGLE_WRITER_BLEND` 없음. loaded 이송에는 블렌딩이 남는다.
- 결착 결과의 `press_control=POSITION_DESCENT_REACTION_STOP`, `force_control_target_n=null`, `native_force_commands=0`, 임계 반력≥40N 및 정지 검증.
- 버튼 답변은 `OPERATOR_CONFIRMATION_ACCEPTED`의 `source=HMI`로 남는다. B/Current 판정은 기존 검사 결과를 따른다.

`settings/integration_native35/profile.reference.json`과 독립 native35 시험 파일명/값은 과거 교시·독립 시험 기준이다. full-real이 실행 사본을40N으로 덮어쓰므로 그 원본만 보고 이번 임계값을35N으로 판단하지 않는다.

`PROCESS_START_FAILED`는 Python/ROS/모델/Camera 환경과 프로세스 stderr를 확인한다. `BLEND_MOTION_TIMEOUT`이 다시 나면 어느 구간인지 확인한다. 이번 코드의 공급 접근은 MoveL이므로 공급 MoveB 기록이면 구 코드/잘못된 D 경로다. loaded 블렌딩 timeout은 여전히 별도 원인 확인 대상이다. `resume_allowed=false`는 로그 파일이나 터미널에서 true로 강제 변경하지 않는다. 명령 결과·정지 피드백이 불명확한 상태는 화면의 사유와 최신 피드백으로 확인한다.

이번 PR의 검증 범위는 [검증 기록](reviews/robot-trial-followup-verification-20261013.json)과 [확인 버튼/재개 시나리오](reviews/robot-resume-scenarios-20261013.md)를 따른다. 다른 PC 설치·실제 Robot·Camera 실행, 새40N에서 끝까지 결착되는지와 블록 미끄러짐 개선은 아직 현장 검증하지 않았다.
