# B Perception — 실행·재현·자료 보존 안내

갱신: 2026-10-12. 최신 B 계약은 Current·revision·Expected·공간 비교를 B가 확정하고 D가 진행·실행·최종 종료 및 HMI/DB 중계를 담당하는 것이다. 아래 안내는 B 범위이며 직접 Robot 명령을 실행하지 않는다.

## 1. 무엇을 실행할 것인가

| 목적 | 진입점 | 현재 범위 |
|---|---|---|
| 처음 보는 사람의 장치 없는 표본 재현 | `perception_mvp.replay_inspection` | 합성 입력을 실제 B 검사 코어에 넣어 정상·불일치·관측 불가·오류를 재현 |
| 실제 저장 RGB의 모델 추론 | `perception_mvp.supply_test` | 아래 표본의 HSV→YOLO 분할·검출 표시. 정답/집기/완료 판정 아님 |
| 실제 ROS 조립판 진단 화면 | `perception_mvp.live_view --integrated` | 정지 구간 수신·V0 손 대기·RGB-D 1쌍 분석. Controller 실결선 아님 |
| D에 제공할 B 관측 callable | `main.make_inspection_observer` → `team_connection.connect_inspection` | 실제 Camera/Controller/확인 영역/Geometry hook을 제공해야 함 |
| 보드 보정/검증 도구 | `calibration/lego_grid.py` | 별도 작업. 이번 정리에서는 실측·보정값을 바꾸지 않음 |
| 학습·자료 준비 | `perception_mvp/labeling.py`, `labeling/` | 운영 추론과 별개 |
| 공급판 처리 | `supply_vision/` | 별도 B 경로; [담당 README](supply_vision/README.md). 미커밋 OBB 변경 등은 이번에 수정하지 않음 |
| 과거 구현 | `legacy/`, `docs/history/`, 과거 callback 예시 | 현재 운영 진입점으로 자동 선택하지 않음 |

자세한 B 코드·시작 조건은 [perception_mvp README](perception_mvp/README.md)를 참조한다. 프로젝트 전체 최초 clone은 팀 저장소 기준으로 수행하고, 아래 명령은 **C-2 루트**에서 실행한다. 모델·촬영 자료가 현재 일반 Git 파일인지 먼저 확인한다. Release 자동 다운로드·모델 자동 대체는 하지 않는다.

## 2. 외부 환경과 설치

재현 PC의 확인값: Ubuntu 24.04 / Python 3.12, CPU. 다음은 2026-10-12 로컬 설치 버전이며 새 PC 설치 성공·공식 최신 버전 보장은 아니다.

| 구성 | 확인 버전 | 출처·준비 방법 |
|---|---|---|
| ROS2 | Jazzy / rclpy Debian 패키지 7.1.12-1noble.20260902.053513 | [공식 Ubuntu 설치](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html) 후 `source /opt/ros/jazzy/setup.bash`. 공식 페이지는 이번 열람에서 접근 제한이 있어 설치를 재검증하지 못함 |
| RealSense ROS | ros-jazzy-realsense2-camera 4.58.4-1noble.20260903.072830 | [공식 ROS wrapper](https://github.com/realsenseai/realsense-ros), ROS 저장소 구성 후 `sudo apt install ros-jazzy-realsense2-camera`. 실제 camera PC/USB 연결 확인 필요 |
| RealSense Python SDK | 2.58.4.10922 | [공식 SDK](https://github.com/realsenseai/librealsense), 아래 requirements의 pyrealsense2 |
| PyTorch / torchvision | 2.14.1+cpu / 0.29.1+cpu | [공식 설치 선택기](https://docs.pytorch.org/get-started/locally/). CPU wheel index는 requirements에 명시 |
| NumPy / OpenCV | 1.26.4 / opencv-python 4.11.0.86 | [NumPy](https://numpy.org/install/), [OpenCV](https://github.com/opencv/opencv-python), 아래 requirements |
| Ultralytics / YAML | 8.4.173 / PyYAML 6.0.3 | [Ultralytics 설치](https://docs.ultralytics.com/quickstart/), [PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation) |

이미 동작하는 ROS/OpenCV 환경을 무조건 재설치하지 않는다. 기존 PC는 사용자 계정 설치를 사용한다. 새 PC는 패키지 충돌/배포판 Python의 외부 관리 정책을 먼저 확인하고 적절한 설치 환경을 선택한다. 시스템 보호를 강제로 해제하는 옵션은 안내하지 않는다.

Python 패키지 설치 안내(기존 환경에 바로 실행하라는 뜻이 아님):

```bash
python3 -m pip install -r perception/perception_mvp/requirements.txt
python3 -m pip install pytest jsonschema
```

표본 재현에는 ROS·USB·Robot·LLM·DB 서버가 필요 없다. 코드 import에 필요한 Python 패키지는 필요하다. 실제 ROS 화면에는 rclpy와 sensor_msgs가 추가로 필요하다. 설치 명령은 이번 정리에서 실행하지 않았다.

준비 확인:

```bash
PYTHONPATH=.:perception python3 -m perception_mvp.local_test preflight
```

예상: 패키지 존재 여부 JSON. `device_or_model_validation=not_performed`이며 센서/모델 정확도 통과가 아니다.

## 3. 가장 먼저 실행할 표본 — 모델·장치 없이 B 상태 재현

입력: [sample.json](samples/inspection_replay/sample.json). 출처는 **SYNTHETIC_NOT_CAMERA**이며 실측·학습 GT가 아니다.

```bash
PYTHONPATH=.:perception python3 -m perception_mvp.replay_inspection \
  --sample perception/samples/inspection_replay/sample.json \
  --output /tmp/b-inspection-replay.json
```

예상 터미널: `SYNTHETIC replay: 7 checks PASS`. 출력 JSON의 `source`·`checks`·`status`와 각 결과의 Current/Expected/Difference를 확인한다. 기존 출력 파일을 덮지 않는 writer이므로 재실행은 새 출력 이름을 사용한다.

| 표본 | 예상 status / comparison | Current revision |
|---|---|---:|
| 전체 확인된 초기 빈 상태 | OK / null | 0 |
| STEP 실제 목표 일치 | OK / MATCH | 1 |
| FINAL 새 근거 없음 | UNOBSERVABLE / UNOBSERVABLE | 1 유지 |
| FINAL 새 유효 근거 | OK / MATCH | 1 유지 |
| STEP 실제 다른 색상 | OK / MISMATCH | 2 |
| 없는 Plan 요청 | ERROR / null | 반환 current=null; 내부 상태를 빈 상태로 대체하지 않음 |
| 최초 INITIAL의 일부 영역만 확인 | ERROR / null, INITIAL_STATE_UNAVAILABLE | 초기 상태 미확인 |

잘못된 표본·없는 파일·예상 결과 불일치는 비정상 종료한다. 오류를 PASS로 숨기지 않는다. 표본 출력의 PASS는 이 7개 계약 사례 재현이지 실제 인식 정확도나 물리 결착 성공이 아니다.

## 4. 실제 저장 사진 표본 — 모델 추론만 재현

아래 RGB·ROI·모델은 현재 Git 추적 자료다. [원본 RGB](recordings/supply_board_roi/20261012T002844481743Z/rgb.png)와 [ROI](recordings/supply_board_roi/20261012T002844481743Z/supply_roi.json)는 실제 촬영이고, 테스트 정답 label은 아니다.

```bash
PYTHONPATH=.:perception python3 -m perception_mvp.supply_test \
  --roi perception/recordings/supply_board_roi/20261012T002844481743Z/supply_roi.json \
  --weights perception/models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt \
  --confidence 0.25 \
  --output /tmp/b-supply-replay
```

예상 산출물: 새 시각 폴더의 `preview.png`, `detections.json`. 보고서 상태는 `LOCAL_DIAGNOSTIC_NOT_GROUND_TRUTH`다. 이번 PC 재현은 yellow_2x3 12, blue_2x3 12, red_2x1 19로 43개 검출했다. 이 수치가 실제 블록 개수/정확한 클래스와 일치한다는 뜻은 아니며 모델·버전·추론 조건에 따른 진단 기록이다. Depth/Grid·Robot 집기·EMPTY/완료를 판정하지 않는다.

기존 ROS 저장 형식 `ros_rgbd_capture_v1/CAPTURE_ONLY`와 strict 처리 loader 형식은 다를 수 있다. 캡처 파일을 가짜 scene/robot_pose/확인 영역으로 채워 strict 검사를 우회하지 않는다. 실제 Geometry가 null인 상태에서 `local_test measure`를 정상 시연 명령으로 안내하지 않는다.

## 5. 모델·보정·설정 준비

| 자료 | 용도 | 적용 조건/확보 |
|---|---|---|
| `models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt` | 블록 instance mask·클래스 | 현재 커밋의 Git 파일. 통합 화면은 다섯 클래스 이름 집합 검사; 임의 ID/클래스 치환 없음 |
| `models/hand_yolo11n_added_20261012/weights/best.pt` | 손 detect | V0용, 실제 사람/조명 독립 검증 별도. train/val 동일 결과를 일반화 성능으로 주장하지 않음 |
| `recordings/board_calibration_{V0,D1,D3}/{View}/run/calibration.json` | 관측점별 Board pose/Grid | 채택 pitch 16mm. 실제 pose·CameraInfo·해상도 일치 및 저장된 독립 검증 필요 |
| 같은 run의 `validation_error_report.json` | 독립 점 검증 증거 | 2mm 최대 오차 시험 기준. 높이·체결 전체 검증이 아님 |
| `captures/empty.intrinsics.json` | 촬영 당시 내부 파라미터 | 새 pose/해상도 변경 시 재확인. 원본 임의 수정 없음 |
| `recordings/assembly_board_roi/{View}/.../assembly_roi.json` | View별 영상 ROI | 보드/손 검색 범위이지 확인된 빈 영역 증거가 아님 |
| V0의 `hand_config.json` | 손 모델/ROI/현장 시험 임계값 | 시작 조건과 상태기계는 B README 확인 |
| `perception_mvp/config.yaml` | 설정 구조/일부 채택값 | 아직 Geometry null 항목 있음. 설정 틀과 완성 실기 프로필을 구분 |
| `--layer-reference`용 높이 JSON | 보드 기준 층별 높이·허용오차 | 아직 완성 자료 미확인. 블록끼리 잰 값·평균 증가량으로 자동 생성하지 않음 |

원본 보존 목록과 SHA256은 [자료 목록](docs/ASSET_INVENTORY_20261012.json)을 참조한다. 파일이 없으면 담당자에게 동일 버전/해시 자료를 요청하고, 다른 모델이나 보정값으로 자동 대체하지 않는다. 로컬에서 삭제 표시된 과거 손 모델은 기록된 Git 커밋에 원본이 남아 있으며 이번 작업이 복구/삭제 확정하지 않았다.

## 6. 실제 촬영·관측 — 표본 재생과 다름

아래는 실제 카메라가 켜진 환경에서 사람이 View/정지 상태를 입력하는 로컬 진단이다. 단일 팀 자동 실행 명령이 아니다.

```bash
source /opt/ros/jazzy/setup.bash
cd perception
python3 -m perception_mvp.live_view \
  --view V0 --integrated --manual-views --diagnostic-geometry \
  --calibration-root recordings --roi-root recordings/assembly_board_roi \
  --hand-config recordings/assembly_board_roi/V0/20261012T004735740339Z/hand_config.json \
  --weights models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt \
  --confidence 0.25 --output recordings/integrated_live
```

이동 전 m, v/d/f View 선택, 실제 정지·안정화 후 s. 이동 중 B 수신·분석 없음. V0는 연속 손 감지 후 새 RGB-D 1쌍만 블록 분석, D1/D3는 손 감지 없이 1쌍 분석. 결과는 고정되며 r 명시 재관측. 키는 Robot 명령이 아니고 안전 증거를 대신하지 않는다. 이 명령은 이번 자료 정리에서 실행하지 않았다.

## 7. D 요청 → B 상태 확정 흐름

```text
INITIAL: 실제 초기 관측 → 충분한 확인 영역 → B Current 확보
승인 Design/동일 Plan/baseline 공유 → B 고정 Expected 모델 생성
STEP: 실제 블록/확인 영역 → 전체 관측 영역 비교 → Current/revision/Difference
FINAL: 새 관측 근거 + 누적 확인 상태 → 전체 Design 비교
결과 callback → D 활성 check/STOP/진행 판단 → HMI/로그/DB
```

- B는 목표를 관측값으로 채우지 않는다. 실제 유효 배치 변화만 revision 증가.
- visible_blocks는 이번 실제 검출, 가린 아래층은 Current 이력으로 유지한다.
- verified_regions는 실제 점유/빈 상태 확인 근거이며 ROI/미검출과 다르다.
- INITIAL 일부 범위만 확인하면 첫 빈 Current를 만들지 않는다. FINAL 새 근거 없으면 보류.
- 2026-10-13: D가 엄지척 또는 로봇 작업 완료 후 요청하는 INITIAL/STEP/FINAL은 기본 STOPPED_CLEAR다. 새 손 진입/3초 대기 없이 손 없음·안정·정지/안전을 확인하고 실제 배치를 비교한다. 독립 손 사이클은 명시적 HUMAN_ASSEMBLY로 진입→이탈 >3초+안정을 사용한다.
- 실제 Camera/Controller hook과 D observe 주입은 아직 공동 검증 필요. D 코드를 이번에 수정하지 않음.

## 8. 자료 분류·보존 원칙

현재 **recordings/models가 전부 Git 제외라는 설명은 틀리다**. 일반 Git 추적 자료가 있으며 Git 추적 여부는 파일별 목록을 따른다.

| 분류 | 자료 | 처리 |
|---|---|---|
| 실행 필수/선택 | 채택 모델·View 보정·실제 설정/ROI | 적용 조건과 버전을 유지 |
| 최소 재현 표본 | 합성 sample 및 실제 RGB/ROI 표본 | README 명령/예상 결과 제공 |
| 보존 원자료 | RGB/raw/aligned Depth/npy·metadata·학습 이미지/라벨 | 삭제·이동 없이 원형 유지 |
| 역사적 진단/중간 출력 | run_pitch17_archive·미채택 모델/예전 기록·ZIP | 현재 운영과 구분하되 유지 |
| 자동 캐시 | __pycache__·pytest/학습 cache | 학습 원본·시험 증거와 구분; 이번 삭제 없음 |

조사한 자료 617개: 로컬 미추적 95개, Git 추적이나 로컬 삭제 상태 1개. 이 목록에는 현재 B assets만 포함되며 문서/코드 전체 Git 목록이나 저장소 밖 자료 전체를 의미하지 않는다. 기록된 상태는 조사 시점의 working tree이고 commit 링크 존재만으로 Release 다운로드 검증이 끝난 것은 아니다.

**전체 자료 GitHub 보존 완료는 아직 아니다.** 미추적 자료는 사용자의 로컬 전용 변경이며 이번에 임의 게시하지 않았다. 저장소 밖 이전 보관 폴더도 보존 위치/목록/해시를 추가 확인한 뒤 게시 방식 합의가 필요하다. 로컬 원자료는 GitHub 보존의 대체물이 아니다.

Release로 옮기려면 파일별 출처/촬영 조건·SHA256·현재 위치 → 첨부 링크 → 실제 재다운로드 SHA 일치 확인 순서로 진행한다. 확인 전 기존 파일 유지. 이번 작업은 Release 생성/첨부/이동/삭제·이력 재작성·force push를 수행하지 않았다. 상세 제출 목록은 [정리·재현 결과](docs/B_REPOSITORY_REPRODUCTION_20261012.md)에 기록한다.

## 9. B 회귀 검사

```bash
QT_QPA_PLATFORM=offscreen \
PYTHONPATH=.:perception:perception/legacy \
B_ROUND1_CONSUMER_PATH="$PWD/history/final_mvp.py" \
B_ROUND1_HMI_CONSUMER_PATH="$PWD/app/hmi_mvp_contracts.py" \
python3 -m pytest -q perception/perception_mvp/tests perception/legacy/tests \
  perception/calibration/tests perception/supply_vision/tests
```

장치 없는 코드/입력 함수 대조 검사이며 실제 Camera·Robot·외부 API·DB 서버/웹 저장 성공과 구분한다.

<details>
<summary>폴더 이전·과거 실행 안내 원문 보존 — 위 최신 안내를 우선</summary>

아래는 과거 시점 기록이다. Git 제외·이동 중 분석·네 층 표현 등은 현재 운영 상태로 적용하지 않는다.

# B Perception 작업 폴더

실제 코드와 촬영 자료를 `/home/roh/Documents/ChatGPT/협동2`에서 이 폴더로 이전했습니다.

| 위치 | 내용 |
|---|---|
| perception_mvp/ | 실제 처리 코드·설정·독립 시험 도구·기존 회귀 테스트 |
| recordings/ | 실제 RGB·원본 Depth·camera_info. 로컬 보존 |
| docs/reference/ | 코드 요청서·설계 조건·계획·이전 논의 원문 |
| docs/callback_examples/ | 이전 합성 callback 예시의 제출·촬영 안내 |
| docs/history/ | 이전 README와 누적 STATUS. 당시 경로/미완료 기록 보존 |
| legacy/ | 이전 루트 코드·데모·기존 테스트. 신규 운영 코드와 구분 |
| archives/ | 과거 제출 ZIP. 로컬 보존, Git 제외 |

운영 방법은 [실제 코드 README](perception_mvp/README.md)를 따릅니다.
RGB 정리·수동 polygon·YOLO 변환은 [라벨링 작업 순서](LABELING.md)를 따릅니다.
perception_mvp/callback_examples.py와 fixtures/는 기존 합성 예시이며 실제 센서 처리 코드가 아닙니다.
docs/reference의 예전 생성 위치·읽기 전용 제한은 당시 요청 기록입니다.
이번 사용자의 명시적 이전 요청으로 앞으로 이 폴더에서 작업합니다.

## 실행 위치

보드 보정의 관측점별 파일은 다음처럼 구분합니다. 이름만 변경했으며 계산값은 동일합니다.

| 파일 | 의미 |
|---|---|
| `captures/validation_clicked_points.json` | 검증 입력: 사람이 클릭한 stud 픽셀과 해당 실제 보드 좌표 |
| `run/validation_error_report.json` | 검증 출력: 각 점 오차·최대 오차·기준·통과 여부 |
| `run/calibration.json` | 영상과 보드 사이의 보정값 및 마지막 검증 상태 |

`collect-points --out`과 `verify --points`에는 클릭 입력 파일을, `verify --out`에는 오차 결과 파일을 지정합니다. 이전 시도의 기록은 저장소 밖 `/home/roh/Documents/ChatGPT/협동2/board_calibration_trials_20261007/`에 보관합니다.

```bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.local_test preflight
```

실행 중인 RealSense ROS/rqt를 유지하고, V0에서 실제 정지·손 이탈을 확인한 뒤:

```bash
source /opt/ros/jazzy/setup.bash
cd /home/roh/C-2/perception
python3 -m perception_mvp.ros_capture --view V0 --output recordings/board_calibration/V0 --stopped-and-clear
```

새 촬영은 이전된 recordings/ 아래에 저장됩니다. 기존 두 촬영 폴더도 그대로 보존했습니다.
ros_capture 자료는 CAPTURE_ONLY이며 보정 계산/기존 strict 로더 연결이 완료된 것이 아닙니다.
가상환경은 사용하지 않습니다. .venv/Git/캐시는 이전 대상에서 제외했습니다.

## 이전 후 회귀 검사

## 로컬 실시간 화면 (2026-10-09)

2026-10-10: V0 통합 모드에서 `--hand-config perception_mvp/config.yaml`로 기존 `hand`
설정을 지정하면 같은 RGB 화면 하단에 손 진입/이탈/불확실, 연속 이탈 시간,
영상 안정 여부와 상태를 표시합니다. 별도 `hand` 클래스 검출 모델과 실제 V0 ROI,
품질/안정화 임계값이 필요하며 현재 null 설정을 임의 값으로 채우지 않습니다.
미설정/모델 오류/정지 확인 없음/동기 프레임 누락은 HOLD 또는 UNKNOWN입니다.
손 진입 후 연속 이탈 **3초 초과**와 영상 안정 확인을 모두 요구하며 손 재진입,
검출 불확실/프레임 끊김은 대기를 초기화합니다. 같은 프레임을 반복 처리해
이탈 시간을 늘리지 않습니다. V0에서 허용 전에는 블록 색상/YOLO 안내는 유지하되
Depth/Grid 확정 측정을 보류합니다. D1/D3는 손 모델을 로딩/실행하지 않습니다.
이 화면은 관측 시작 가능 상태만 표시하며 Robot 이동/다음 Step/Backend callback을
자동 실행하지 않습니다. 사람 손 검출은 Robot 안전 인터록이 아닙니다.

`live_view --integrated`는 OpenCV 노랑/파랑/빨강 후보 영역의 원본 RGB를
CPU YOLO에 넣고, 개별 mask를 전체 영상 좌표로 복원하여 Depth/Grid를 같은 화면에 표시합니다.
다섯 클래스 `yellow_2x2`, `yellow_2x3`, `blue_2x2`, `blue_2x3`, `red_2x1` 모델이 필요합니다.
모델의 클래스 ID 순서는 달라도 되지만 이름 집합과 개수는 일치해야 합니다.
기존 네 클래스 학습/Backend 계약은 바꾸지 않습니다.

실행 위치는 `/home/roh/C-2/perception`이며 옵션은 다음과 같습니다.

```text
python3 -m perception_mvp.live_view --view V0 --output recordings/live_integrated/V0
  --integrated --confidence 시험할_임계값
  --calibration 실제_V0_calibration.json --stopped-and-clear
```

위 명령은 옵션 설명이며 모델 경로/임계값을 실제 값으로 바꾼 뒤 한 줄로 실행합니다.
성능 우선 기본 모델은 `models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt`
(YOLO26s 1차)입니다. 통합 모드에서는 `--weights`를 생략하면 사용하며,
명시한 `--weights`가 있으면 그 파일을 우선합니다. 기존 11n 명령을 그대로 사용하면
11n이 실행되므로 해당 옵션을 제거하거나 26s 경로로 변경하세요.
모델 누락 시 다른 모델로 대체하거나 다운로드하지 않고 오류로 종료합니다.
V0/D1/D3 각각 해당 관측점의 보정값을 사용합니다. 로봇 이동/Backend 채택은 수행하지 않습니다.
보정/동기 Depth/정지 확인이 없으면 색상·YOLO는 표시하되 기하는 UNKNOWN입니다.
기하 방향은 +X 기준 긴 축(`axis`) 진단값이며 Backend orientation DTO가 아닙니다.
기하 오차·HSV 범위는 기존 진단 시험값으로 실제 장치에서 검증해야 합니다.
선택 옵션 `--layer-reference`에는 JSON의 `top_heights_mm`(보드 기준 실제 네 층 높이),
`tolerance_mm`(층 간 허용 구간이 겹치지 않는 양수)을 제공합니다.
블록끼리만 쌓아 잰 높이를 보드 기준으로 그대로 대입하지 않습니다.
층 기준이 없거나 범위 밖이면 층 UNKNOWN과 사유를 표시합니다.
색상 후보 없음/YOLO 미검출은 확인된 빈 보드라는 뜻이 아닙니다.
기존 라벨링·학습/CLI 추론은 자동으로 이 통합 모드로 전환되지 않습니다.

### 한 화면에서 수동 관측점 전환 (2026-10-10)

`live_view --integrated --manual-views --calibration-root /home/roh/C-2/perception/recordings`
를 기존 모델/confidence/output/view 옵션과 함께 실행합니다. 단일 `--calibration`은 사용하지 않습니다.
root 아래 `board_calibration_V0/V0/run/calibration.json` 및 D1/D3 대응 파일을 검증해 로드합니다.
시작 상태는 미정지이며, `--stopped-and-clear`를 넣어도 수동 확인 전에는 적용하지 않습니다.

- `m`: 로봇을 움직이기 **전에** 이동 중으로 설정합니다. 기하 검증·캡처를 막습니다.
- `v` / `d` / `f`: 이동 중 상태에서 각각 V0 / D1 / D3을 선택합니다.
- `s`: 실제 해당 보정 자세에서 정지한 뒤 정지 상태를 수동 확인합니다.
- `c`: 정지·동기·신선한 RGB-D 조건 확인 후 output/View/시각 폴더에 저장합니다.
- `q`: 종료합니다. 기존 좌표 비교용 `1`/`2` 키는 유지합니다.

전환 때 이전 프레임·측정·비교 기준·추적·손 표시를 초기화합니다. V0 복귀 후에는 손 진입 조건을
새로 확인하며 D1/D3에서는 손 추론을 실행하지 않습니다. 손 설정이 없으면 V0 기하는 HOLD입니다.
화면과 블록 색상/YOLO 표시는 이동 중에도 유지하지만 위치·층 결과는 미확인으로 표시합니다.
`ViewSelection.update(view, stopped=bool)`는 키 입력과 향후 Controller 입력이 공유하는 내부 경계입니다.
Controller Topic/callback 어댑터·thread 전달·실제 정지/영상 안정 확인은 아직 연결하지 않았습니다.
키 입력은 로봇 제어 명령이나 안전 증거가 아니며 Current/Expected 입체 표시 연결도 별도입니다.

### 기존 회귀 검사 실행

기존 테스트 일부는 이전 루트 모듈을 import하므로 legacy 경로를 명시합니다.
이 경로는 기존 테스트 전용이며 정상 실행에는 필요 없습니다.

```bash
cd /home/roh/C-2/perception
PYTHONPATH="$PWD:$PWD/legacy" python3 -m pytest perception_mvp/tests legacy/tests -q
```

이 검사는 합성 입력을 사용하는 기존 L1 회귀 검사이며 실제 Camera/Robot/HMI 통합 시험이 아닙니다.
기존 C-2 Backend의 import/수신부를 바꾸지 않았으므로 폴더 이전이 통합 완료를 의미하지 않습니다.

</details>
