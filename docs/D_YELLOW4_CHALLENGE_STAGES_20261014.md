# 노랑4점 결착·분리 challenge 단계 설계

작업 checkout: `/home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge`

브랜치: `codex/integration-challenge`. 노랑 `2x2x1` 한 블록의 별도 시나리오이며 팀원의 Round2 기본 step/Plan/Current를 변경하지 않는다. [시나리오 입력·진행 기록](../robot_control_integration/settings/yellow4_challenge_20261014/scenario.json), [각 단계 실행 프롬프트](D_YELLOW4_CHALLENGE_PROMPTS_20261014.md)를 함께 사용한다. 0단계 완료는 설계/소프트웨어 준비 완료이며 실물 동작 완료가 아니다.

## 원리와 연구의 적용 범위

결착 방식은 **걸린 접촉부를 지점으로 회전하며 순차적으로 stud를 진입시키는 방식**이다. 체결 자체는 stud와 블록 밑면의 끼워맞춤이고 회전은 이를 수행하는 동작 전략이다. 수직축 yaw 비틀기만 하는 것이 아니라 접촉축에 대한 roll/pitch와 TCP XYZ 원호 이동을 함께 계산한다. 고정 TCP에서 자세만 바꾸면 블록의 접촉부가 미끄러질 수 있다.

사용자 영상/설명에서는 최초 접촉부가 stud에 걸려 더 밀리지 않고 이후 눕힌다. 이것은 작업자 관찰이며 자동 센서 판정은 아직 없다. 최초 모델은 고정 접촉선이지만 한 점 접촉/축 이동/그리퍼 미끄러짐이 보이면 관측에 맞춰 수정한다. 영상 속 아래 블록의 손 지지와 조립판 고정 조건도 다르다.

[CMU 2023 연구](https://arxiv.org/html/2305.15667)의 II-C/Fig.3은 전용 3D 프린트 도구의 부착·비틀기 동작을 제시한다. 직접 수직 인양하면 아래 구조까지 끌려갈 수 있다는 문제를 설명한다. 작업 순서의 역전과 접촉 궤적의 단순 역재생은 구분한다. RG2의 옆면 파지와 이 도구의 결합 방식은 다르므로 도구 동작/힘/성공률을 그대로 채택하지 않는다.

[부분 구속 삽입 연구](https://www.mdpi.com/2076-3417/11/16/7394)의 4.2/Fig.14는 접촉 가장자리를 중심으로 회전하는 삽입 전략의 참고다. LEGO 실물 검증이나 현재 장비의 접촉 파라미터를 제공하는 논문은 아니다. [CMU Eye-in-Finger 2025 연구](https://arxiv.org/html/2503.06848v1)의 III-D는 대상 위치 선관측→집기→놓기→검사를 분리한다. 그 논문의 전용 카메라/조명 반사 기반 roll/pitch 측정을 현재 D435i OpenCV 모서리 검출과 동일하게 취급하지 않는다.

분리는 **결착된 블록 재파지→반대편 stud부터 부분 해제→남은 결합 해제 확인→상승 회수**를 가설로 시험한다. 결착 때의 축/각도/힘을 분리용으로 그대로 복사하지 않는다. 판이 함께 들리거나 파지가 미끄러지는 경우를 분리 성공으로 기록하지 않는다.

## 개발 순서와 완료 기준

| 단계 | 개발/시험 내용 | 완료 증거 |
|---|---|---|
| 0 | 독립 범위, 상태 흐름, 증거 구분, 단계 프롬프트 적용 | 현재 브랜치·문서·JSON 정합성, 기존 preview 검사; 장치 명령 0 |
| 1 | 공급 파지/접촉축 관계를 받는 공통 기하, 결착·분리 별도 preview | 임의 축·좌표 변환·접촉점 불변량·회전 부호·원본 보존 테스트; 합성 표시 |
| 2 | 기존 교시/보정 읽기, 실제 TCP–블록 관계 확인, 관측 팝업/기록 | 출처 있는 좌표·영상·실측 관계와 잔여 미확인 값; 이동 없이 확인 |
| 3 | 실제 조립판보다 위로 평행 이동한 무접촉 원호·회전 경로 | 명령/실제 XYZ·SO(3) 자세·오차·피드백, 전체 경로 간섭/그리퍼 유지 확인 |
| 4 | 최초 stud 걸림과 짧은 부분 회전 결착 | 접촉부·회전 방향·파지 미끄러짐·반력/모멘트·지지 상태 관찰 |
| 5 | 회전 결착 전체, 개방/필요 시 닫힌 패드 누름, 개방 후 검사 | 실제 착좌/기울기/유지 결과; 명령 완료·45N 도달과 별도 판정 |
| 6 | 결착된 노랑 한 블록 재파지·부분 회전 분리 | 한쪽 해제와 남은 결합 구분, 판 고정·파지 유지·하부 구조 불변 확인 |
| 7 | 완전 분리 후 회수, 결착→검사→분리→검사 연결 | 목표 한 블록만 회수, 빈 목표/조립판 유지/회수 위치 검사와 반복 결과 |

1단계에서 양방향 기하를 함께 준비하되, 실물은 3→4→5의 결착을 먼저 검증하고 6→7의 분리를 진행한다. 동시에 두 물리 제어 루프를 실행하지 않는다. 횟수만 채우는 반복 제한을 넣지 않고 결과·영상·실제 피드백으로 판단한다.

## 좌표·관측·제어 연결

- 목표 예시 `(17,17), 1층`은 기존 사용자 지정/preview에서 이어받은 제안이다. 현재 실물 배치 확인으로 표시하지 않으며 각 단계에서 설정으로 바꿀 수 있다.
- 기존 supply/assembly teaching, grid calibration, 카메라 투영 데이터를 먼저 읽어 사용한다. 기본 로봇/challenge 파지는 바닥 기준 **5mm**다. 사람이 직접 결착하던 조립을 로봇으로 보완하는 별도 경로는 **15mm**다. +10mm 시험 후보는 이 보완 모드에서만 최초 공급 파지와 안착에 함께 적용하며 실측 프로파일과 구분한다. 이미 낮게 잡은 블록을 올려 같은 파지로 표시하지 않는다.
- 블록 좌표와 TCP의 상대 변환 및 접촉축을 명시한다. 입력 자세는 XYZ(mm)+ZYZ(deg), 물리 회전은 SO(3)로 비교한다. 파지 높이가 달라지면 TCP 기준 접촉축도 다시 계산한다.
- 관측 팝업은 블록 모서리, 기준 격자 방향, 접촉축, 예상 원호, 실제 자세/반력, 현재 상태를 구분해 표시한다. RGB 획득/ROI 입력 동안 ROS 피드백과 창 처리를 계속한다. 일시적 자료 지연은 정지 상태에서 대기하며 이미 보낸 이동을 재전송하지 않는다.
- yaw 각도 비교와 실제 윗면 roll/pitch는 별도다. 2D 모서리 기울기나 H/J/K 기준 자세 복귀만으로 실제 블록 평면 정렬을 확정하지 않는다. 확인된 평면 제공자가 있을 때 기존 ±0.50° 자동 보정을 연결한다.
- 의도적인 기울임/접촉축 회전 중에는 기존 자동 수평 복귀와 상쇄하지 않도록 상태를 분리한다. 접촉 회전 중 기존 XY 보정도 접촉축을 밀어내지 않게 한다.
- `app/edge_first_seating.py`의 waypoint는 원호지만 MoveL 구간은 chord 근사다. 샘플 간격에 따른 접촉부 오차와 실제 자세를 검사한다. H/J/K는 회전 표현/오차 계산만 재사용하고 실제 접촉축 제어의 검증으로 대신하지 않는다.

## 실물 기록과 진행 원칙

최소 기록은 run/stage/operation, 입력 출처와 프레임, UTC/피드백 시간, command/actual TCP, gripper 폭, raw wrench(Fx,Fy,Fz,Mx,My,Mz), 합력, 영상, 작업자 관찰, 상태 전이 이유다. 검출/분류 실패는 UNKNOWN으로 남기며 성공으로 바꾸지 않는다. 기존 B Current/revision을 이 시험 로그로 갱신하지 않는다.

기존45N은 위치 하강 누름의 raw 합력 중단값이다. 일정45N 유지 제어와 구분하며 최초 걸림/분리 감지값으로 사용하지 않는다. 접촉 회전의 속도·최대 각도·반력/모멘트 조건은 2~4단계 관측과 장비/파지 관계에서 지정하고 없는 실측값을 임의 정상값으로 채우지 않는다.

접촉/해제 판정은 초기 실물에서는 작업자 관찰과 로그를 연결한다. 자동 판정은 동일 시험 기록에서 검증된 경우에 연결한다. 압력이 줄었다는 이유만으로 ALL_STUDS_RELEASED나 SEATED로 전이하지 않는다. STOP/응답 미확정 시 기존 정지 처리를 유지하고 그리퍼를 자동 개방하거나 전체 동작을 재시도하지 않는다.

코드 준비와 실물 단계 완료는 각각 기록한다. 3~7단계는 사용자 실물 결과가 없는 동안 PREPARED_FOR_FIELD_TEST로 유지하며 단계 완료로 승격하지 않는다. 단계 완료 후 다음 프롬프트를 제공하고 사용자가 입력한 단계만 이어서 개발한다. 미확인 값은 그 값을 필요로 하지 않는 소프트웨어 작업을 막지 않는다.

## 1단계 산출물 — 공통 기하와 두 작업 preview

`app/edge_first_seating.py`에 v2 preview를 연결했다. 기존 v1 fixture/기본 CLI는 보존했다. v2는 하나의 노랑 블록과 별도로 지정된 assembly/removal 접촉축·각도·샘플 간격을 사용한다. 제거 preview의 끝은 부분 회전이며 전체 해제를 판정하거나 수직 회수하지 않는다.

### 입력 좌표의 의미

- `coordinate_frame`: seated block pose, 접촉축, 목표 stud 중심의 입력 프레임. 접촉축/stud의 `frame`이 다르면 변환을 명시해야 한다. camera/base로 추정하지 않는다.
- `output_frame`, `frame_pose_in_output_mm_zyz_deg`: 입력 프레임의 출력 프레임 내 자세 `T_output_frame`. 프레임 이름이 같으면 identity 변환을 사용한다. 출력 XYZ/자세/축/stud는 모두 출력 프레임 기준이다.
- `seated_block_pose_mm_zyz_deg`: 블록 기준 좌표의 입력 프레임 내 자세 `T_frame_block`.
- `tcp_to_block_pose_mm_zyz_deg`: **블록 좌표를 TCP 좌표로 옮기는** 강체 파지 변환 `T_tcp_block`. 블록 원점이 TCP에서 어디에 있는지 나타내며 base의 파지 pose가 아니다.
- `block_geometry`: 블록 로컬 XYZ의 순서 있는 네 바닥 모서리와 +Z 높이. `target_studs`는 네 중심의 입력 프레임 좌표다.
- `operations.assembly/removal`: 작업별 `contact_line` 두 점, 부호 있는 `tilt_deg`, 양의 `angular_step_deg`. 결착은 tilt→0, 분리는0→tilt로 각각 샘플링한다. 다른 작업의 축을 fallback으로 채우지 않는다.

계산 관계는 `T_output_block = T_output_frame × T_frame_block`, `T_output_tcp = T_output_block × inverse(T_tcp_block)`이다. 출력 프레임의 접촉축으로 TCP XYZ/자세를 함께 회전하고, 각 waypoint에서 `T_output_block = T_output_tcp × T_tcp_block`을 유지한다. 파지 관계를 바꾸면 TCP 원호가 바뀌며 같은 블록 회전 경로를 유지한다.

`chord_error_bound_mm`는 직선 TCP XYZ와 최단 SO(3) 자세 보간을 가정한 구간의 기하 오차 상한이다. 실제 MoveL 제어기 보간·접촉 유지의 실측 결과가 아니다. 샘플 간격은 설정으로 받으며 실제 접촉 시험에서 확인한다.

### 장치 연결 없는 실행

저장소 루트에서 두 작업의 JSON과 경로 그림을 함께 생성한다.

```bash
python3 robot_control_integration/scripts/yellow4_edge_first_preview.py \
  --config robot_control_integration/fixtures/yellow4_pivot_preview.json \
  --operation both \
  --output /tmp/yellow4-challenge-stage1-preview.json \
  --plot /tmp/yellow4-challenge-stage1.png
```

`--operation assembly` 또는 `--operation removal`로 한 작업만 출력할 수 있다. `--plot`은 PNG/SVG 파일을 저장하며 장치 창/카메라를 열지 않는다. 관측 팝업은 2단계 범위다. 실행 옵션/장치 명령은 없다. 그림 저장은 현재 환경의 Matplotlib을 사용하며 ROS/그리퍼 패키지를 추가하지 않았다.

![합성 결착·분리 경로](assets/yellow4-challenge-stage1.png)

길이·높이·축·10°/-8°는 합성 입력이다. 실제 치수·stud 걸림 위치·권장 각도로 채택하지 않는다. 빨간 선은 가정한 접촉축, 초록 점은 목표 stud 중심, 파란 원호는 TCP, 색상별 블록은 시작·중간·끝 자세다. 점선은 강체 파지의 TCP–블록 관계다. 접촉/간섭/체결/완전 해제는 이 그림으로 검증하지 않았다.

## 2단계 산출물 — 기존 데이터 연결·읽기 전용 관측

`app/yellow4_observation.py`와 `scripts/yellow4_observe.py`를 추가했다. 공급판 OpenCV stud backend/중심 보정 함수, 기존 층별 착좌 기록과 anchored affine 목표 이동, VirtualBoardGrid 투영을 재사용한다. 원본 교시/ROI/profile과 팀원 checkout은 변경하지 않는다. 기준 목표는 현재 시나리오 `(17,17), 1층`이며 실물 위치 확인으로 취급하지 않는다.

### 파지 모드 — 사용자 최신 확인 반영

기본 `STANDARD`는 바닥 기준5mm이며 공급 파지/착좌의 기존 TCP를 그대로 사용한다. `HUMAN_REPLACEMENT`만15mm이며 사람 직접 결착 보완을 위한 별도 모드다. 이 모드의 +10mm는 사용자 지정 base-Z 시험 후보로 표시하고 실측15mm 관계로 승격하지 않는다. 조립판/카메라/치수/층 자료의 출처 경로·SHA256·provisional 상태를 prepared.json에 보존한다. 현재31.8mm 외곽 길이/19.6mm 몸체 높이 등은 기존 사용자 보고 치수이며 1단계 합성16mm/10mm 그림과 구분한다.

### 실행

challenge 저장소 루트에서 장치 연결 없는 준비 결과를 저장한다.

```bash
python3 robot_control_integration/scripts/yellow4_observe.py prepare --output /tmp/yellow4-stage2-prepared.json
```

데스크톱 터미널에서 기존 ROS 환경을 불러오고 팝업을 실행한다. 로봇 이동/그리퍼 조작은 하지 않는다.

```bash
cd "/home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge"
source /opt/ros/jazzy/setup.bash
source /home/rokey/cobot2_ws/install/setup.bash
export ROS_DOMAIN_ID=20
python3 robot_control_integration/scripts/yellow4_observe.py observe --live --view supply --output logs/yellow4-challenge-stage2-observations
```

기본은5mm다. 사람 결착 보완 경로를 관측할 때만 `--grasp-mode human-replacement`를 추가한다. RG2 폭을 읽을 때만 `--read-gripper`를 추가한다. RG2는 holding register258~275의 읽기만 사용하며 write register/파지 명령을 호출하지 않는다.

| 입력 | 의미 |
|---|---|
| 1 / 2 | 공급판 / 조립판 영상 진단 전환; 로봇 이동 없음 |
| B → 두 번 클릭 | 현재 영상의 공급 블록 ROI 양끝; 원본 ROI를 덮어쓰지 않음 |
| E → 두 번 클릭 | 보이는 몸체 **윗면 모서리** 양끝 |
| L → 두 번 클릭 | 먼저 닿을 부분의 **픽셀 접촉축 후보**; 실제3D 축이 아님 |
| SPACE | rgb.png / overlay.png / capture.json / prepared.json 저장 |
| C / ESC | 선택 초기화 / 관측 창 종료 |

ROI 선택 동안 별도 blocking 창을 열지 않는다. OpenCV 분석은 단일 worker에서 처리하고 ROS 비동기 조회·창 입력은 계속 처리한다. 결과는 분석 당시 RGB/샘플/타임스탬프와 함께 저장한다. 최신 RGB/pose가 없으면 대기/UNKNOWN으로 표시한다. RGB가 없어도 로봇 피드백은 별도 조회하며 관측 종료는 move_stop/그리퍼 조작을 호출하지 않는다.

픽셀 모서리–격자 방향 비교는 yaw 진단이고 실제 블록 roll/pitch는 UNKNOWN이다. 등록 파지 자료가 없으면 우측에는 명시적으로 합성1단계 경로를 표시한다. field measurement가 제공되면 그 기하의 TCP 경로/접촉축을 카메라로 투영하되 provisional 투영과 접촉 유지 실측을 구분한다. 중심 검출/XY 보정 적용/coordinate fallback 이유도 별도로 기록한다. 독립적인 stud-center metric mapping과 같은 관측 pose가 확인된 경우에만 XY 후보를 계산한다. 이 관측기는 계산된 후보로 로봇을 움직이지 않는다.

### 캡처와 남은 실측

`--role SUPPLY_GRASP_CANDIDATE`, `--role SEATED_GRASP_CANDIDATE`, `--role CONTACT_AXIS_CANDIDATE` 및 `--notes "관찰 내용"`으로 기록을 구분할 수 있다. role/notes/SPACE만으로 실제 파지 높이·평면·접촉축을 검증했다고 표시하지 않는다. 각 영상은 노랑 한 블록의 몸체/패드 관계를 포함하고, 파지 관계를 구하려면 **동일 파지에서 실제 블록 좌표와 TCP 좌표**가 함께 필요하다. 분리 재파지가 다르면 새 grasp_id/관계로 기록한다.

`settings/yellow4_challenge_20261014/measurements.pending.json`은 미완성 양식이다. 복사본에 선택 모드/관찰 높이, 동일 착좌 파지의 paired BASE TCP·block pose, 근거 캡처 경로, grasp_id, 실제 블록 로컬 모서리/높이와 목표 stud, 작업별 접촉축/각도/간격, 판 고정 확인을 입력한다. 픽셀 두 점/기준 tool 자세를 실제 블록3D pose로 복사하지 않는다.

```bash
python3 robot_control_integration/scripts/yellow4_observe.py prepare --measurements /절대경로/measurements.json --output /tmp/yellow4-measured-input-preview.json
```

분리 축이 아직 없어도 확인된 결착 기하를 먼저 사용한다. 누락된 분리 축/치수는 missing_measurements로 남긴다.

paired pose로 `T_tcp_block = inverse(T_base_tcp) × T_base_block`을 계산해 1단계 기하에 연결한다. 반력/접촉/체결 성공으로 승격하지 않는다. 현재 실측 양식은 null이고 실제 파지 관계·축·판 고정은 확인이 남아 있으므로 2단계는 PREPARED_FOR_FIELD_TEST로 기록한다. 다음3단계는 실측 입력/미확인 항목을 먼저 읽어 필요한 실물 준비와 무접촉 경로 시험을 분리한다.

## 3단계 산출물 — 무접촉 XYZ 원호·자세 회전 시험 준비

`app/yellow4_air_trial.py`, `scripts/yellow4_air_trial.py`, `settings/yellow4_challenge_20261014/air_trial.json`을 추가했다. 기존 `AssemblyMotionRos`의 MoveL을 사용하며 관측기와 같은 ROS node를 공유한다. Round2 기본 step/Plan/B Current, 원본 교시와 다른 checkout은 변경하지 않는다. 기본 STANDARD는5mm이며 +10mm를 적용하지 않는다.

### 경로와 입력

실측 입력의 착좌 TCP가 기존 이송 높이에 도달하도록 BASE Z 평행 이동량을 계산하고 **블록 pose·TCP 원호·선택 접촉축·비교용 가상 stud를 모두 같은 양만큼 이동**한다. TCP–블록 상대 변환은 유지한다. 가상 stud는 실제 상공에 존재하는 stud가 아니다. 기본 높이194.73294067382812mm는 기존 이송 설정에서 읽는다. `air_tcp_z_mm`으로 별도 높이를 지정할 수 있으며 전체 블록의 원호가 지면 stud보다 최소20mm 위인지 계산한다. 이 수직 여유 계산은 주변 구조/그리퍼/로봇 링크의 전체 간섭 검증이 아니다.

관측 자료의 paired BASE TCP·block pose, 실제 블록 로컬 치수, 대상 stud, 선택 작업의 실제 접촉축/회전 방향/각도/간격을 사용한다. 값이 없으면 `PREPARED_MISSING_FIELD_GEOMETRY`와 누락 항목을 출력하고 장치 연결 없이 마친다. 분리 축이 null이어도 결착 축이 있으면 assembly 시험을 준비한다. removal은 독립된 입력을 요구한다. 보드 고정 확인이 없다는 사실도 보존하며 무접촉 시험 결과로 접촉 시험의 고정을 승인하지 않는다.

모든 경유는 MoveL이다. supply 시작은 수직 상승 → 공급판 이송점 → 몸체 우회점 → 조립판 관측점 → 상공 기준점 → 접촉축 원호 → 상공 기준점 복귀다. home 시작은 공급판 관측점을 먼저 방문한다. assembly 시작은 현재 위치에서 수직 상승 후 조립판 관측점으로 간다. 마지막 기존 place-board 경유점은 상공 기준점 XY의 조립판 관측점으로 대체했다. 공급 집기·그리퍼 개폐·착좌·누름은 이 단계에서 수행하지 않는다. 이미 해당 파지 관계로 잡은 노랑 한 블록을 사용한다.

속도는 기존 held 통합 설정에서 이동120mm/s, 상하/원호12mm/s, 각속도6°/s, 가속도48mm/s²·3°/s²를 읽는다. `rates`에 명시한 값만 덮어쓴다. 무접촉 조건을 향후 접촉 회전 속도로 자동 채택하지 않는다.

### 사용자 실행

현재 준비 상태부터 확인한다. 아래 명령은 장치에 연결하지 않는다.

```bash
cd "/home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge"
python3 robot_control_integration/scripts/yellow4_air_trial.py --output logs/yellow4-challenge-stage3-preview
```

실제 paired 관계와 접촉축을 입력한 **별도 실측 파일**이 있는 경우 preview를 만든다. `/절대경로/measurements.json`은 그 파일로 바꾼다. pending 양식과 합성 fixture는 실제 시험 입력이 아니다.

```bash
python3 robot_control_integration/scripts/yellow4_air_trial.py \
  --measurements /절대경로/measurements.json \
  --operation assembly --start-zone supply \
  --output logs/yellow4-challenge-stage3
```

preview.json에서 원본 출처/파지 모드·관계, 지면/상공 기하, 원호/자세/수직 여유를 확인하고 air-path.png를 비교한다. 실제 경로가 비어 있는 것을 확인한 뒤 데스크톱 터미널에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/cobot2_ws/install/setup.bash
export ROS_DOMAIN_ID=20
python3 robot_control_integration/scripts/yellow4_air_trial.py \
  --measurements /절대경로/measurements.json \
  --operation assembly --start-zone supply \
  --output logs/yellow4-challenge-stage3 \
  --execute --confirm-hand-clear --confirm-route-clear
```

시작 위치에 따라 `--start-zone home` 또는 `assembly`를 사용한다. `--empty-gripper`는 그리퍼 폭/상태를 유지한 채 TCP만 시험한다. 빈 그리퍼 결과는 실제 블록 파지 유지 검증이 아니다. 이전 몸체 우회→place 이동에서39N/잔류21N 힘 중단이 기록돼 있으므로 그 기록을 preview에 보존하고 새 MoveL 경로의 현장 확인을 `--confirm-route-clear`로 받는다. 원본 복귀 비활성 표시를 해제하거나 과거 경로를 검증 완료로 바꾸지 않는다.

### 팝업·기록·남은 검증

팝업에 목표/실제 TCP, 위치·SO(3) 오차, 폭, raw 힘/모멘트, RGB 나이를 표시하고 입력 기하의 축/예상 원호를 카메라로 투영한다. 투영은 기존 provisional 자료의 진단이며 실제 블록 roll/pitch 측정이나 영상–pose 동기화 확인이 아니다. OpenCV 분석·원본/overlay 저장은 worker에서 수행하고 서비스 대기/settling 중 ROS와 창 입력을 계속 처리한다. ESC/창 닫기/신호는 정지 요청을 보낸다. 팝업 종료나 journal 실패가 정지 요청/응답 처리를 막지 않도록 별도 ROS spin을 사용한다.

run별 events.jsonl에 command/actual TCP, 전체 SO(3) 자세 오차, gripper 폭·초기 폭 대비 변화, raw wrench, ROS RGB stamp와 수신 시각을 저장한다. 시작·각 원호/경유 도착·종료에는 RGB/overlay/capture.json/prepared.json을 저장한다. 이는 시각별 영상 프레임이며 연속 동영상 녹화/영상–pose 독립 동기화 검증은 아니다. 느린 **정지 상태** 피드백은 읽기만 다시 기다린다. 이동 중 피드백 지연/장치 오류/힘 중단/명령 응답 불명은 정지하고 명령 재전송·그리퍼 개방을 하지 않는다.

모든 endpoint IK/FK와 실제 도착 오차를 확인한다. 이산 MoveL은 원호의 chord를 따라가며 SO(3) 보간 가정의 계산 오차와 실제 제어기 동작은 구분한다. 실제 중간 피드백/영상으로 원호·파지 유지·간섭을 검토해야 한다. H/J/K 기준 자세 복귀를 원호/블록 평면 검증으로 대체하지 않는다.

현재 코드는 PREPARED_FOR_FIELD_TEST다. 실제5mm 파지 관계·결착 접촉축 입력 및 사용자 실물 결과가 없으므로 원호 검증 완료/체결 완료를 기록하지 않는다. 4단계 개발 요청 시 이 입력과3단계 실물 기록을 먼저 확인한다.
