# B Perception 작업 폴더

실제 코드와 촬영 자료를 `/home/roh/Documents/ChatGPT/협동2`에서 이 폴더로 이전했습니다.

| 위치 | 내용 |
|---|---|
| perception_mvp/ | 실제 처리 코드·설정·독립 시험 도구·기존 회귀 테스트 |
| recordings/ | 실제 RGB·원본 Depth·camera_info. 로컬 보존, Git 제외 |
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

## 통합 실시간 화면 (2026-10-09)

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
