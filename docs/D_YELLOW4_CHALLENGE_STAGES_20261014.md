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

## 4단계 산출물 — 공급 최초 파지·걸림 관찰·부분 회전 준비

`app/yellow4_contact_trial.py`, `scripts/yellow4_contact_trial.py`, `settings/yellow4_challenge_20261014/contact_trial.json`을 추가했다. 노랑2×2 하나의 공급 파지부터 시작하며 STANDARD 공급 TCP는 기존5mm 교시 그대로다. HUMAN_REPLACEMENT의15mm는 동일 grasp_id/mode/height에 묶인 별도 실측 공급 TCP가 있어야 하며 +10mm 후보로 대체하지 않는다. 다른 checkout, 기본 Round2 step/Plan/B Current와 원본 교시는 변경하지 않는다.

### 실제 입력과 준비 상태

사용자가 실행한3단계 preview는 `PREPARED_MISSING_FIELD_GEOMETRY / physical_commands=0`이다. 실제 상공 회전 결과가 아니다. 현재4단계는 코드 준비 상태이고 실행 가능한 실측 프로파일은 아직 없다. 기존 공급판/층/카메라 자료는 즉시 읽되 paired TCP–블록 관계, 착좌 블록 pose, 실제 결착 축/방향, 판 고정과3단계 실제 원호·파지 검토가 남아 있다. 분리 축은4단계 필수 입력에서 제외한다.

`--air-run`은3단계 실제 run 디렉터리다. events.jsonl의 REAL 완료/held context와 **run 내부 preview.json**을 읽는다. 실패/빈 그리퍼 시험을 결착 검증으로 쓰지 않고 대상·TCP/tool·파지 관계·착좌 기준·블록 치수·stud·축·기울임 방향이 이번 입력과 일치하는지 검사한다. 3단계 launcher에도 run별 preview 복사본을 추가해 후속 preview가 원래 실행 입력을 덮어쓰지 않도록 했다. `contact_trial.json` 복사본의 `air_trial_review`에는 실제 검토 근거 `evidence_ref`, `arc_observed=true`, `grip_maintained=true`를 기록한다. 작업자 검토와 로봇 명령 완료를 구분하며 자동 실물 성공 판정으로 승격하지 않는다.

### 시험 후보 설정과 흐름

사용자 응답은 접촉 속도·중단값 미정, 지나치게 느리지 않게 준비였다. 아래 값은 설정으로 변경 가능한 **미검증 시험 후보**다. 물성/안전 한도/실측 조건으로 표시하지 않는다.

| 항목 | 후보와 근거 |
|---|---|
| 비접촉 이송/상하 | 기존 통합120/12mm/s 설정 읽기 |
| 접촉 하강·원호/회전 |6mm/s·1°/s; 이전 하강6 요청과 개발 후보, 무접촉120/12를 접촉에 복사하지 않음 |
| 접촉 가속도 |12mm/s²·1°/s² 개발 후보 |
| 정렬 높이/검색 진입 |목표+20mm, 기울임 후 명목 접촉 pose+2mm로 접근 |
| 수동 검색 |N마다0.5mm, 명목 접촉 pose 아래2mm까지; 간격/범위는 설정 |
| 부분 회전 |2° 후보, 실측 최초 기울임보다 작아야 함;0° 완전 착좌까지 이동하지 않음 |
| 합력 중단 |raw XYZ 합력45N; 이전 사용자 중단값 재사용, stud 걸림 기준/일정 힘 제어가 아님 |
| 모멘트 중단 |접촉 직전 기준 대비 XYZ 모멘트 변화 norm1Nm; 이전 held 시험 README의 후보, raw 전체 모멘트 한도와 구분 |
| 파지/등록 검사 |실제 최초 파지 폭 대비2mm 변화 중단, 명목 걸림 TCP와0.5mm 등록 오차 후보; 실물값 아님 |

시작은 빈 그리퍼를60mm로 연 정지 상태, 공급1번 노랑2×2, 빈 목표 위치다. 3단계에서 잡고 있던 블록은 사용자가 공급판에 돌려놓고 시작 상태를 준비한다. 자동 회수/개방 기능은 없다. home/assembly→공급판 관측은 기존 MoveL 경유, 파지 후 공급판 이송→몸체 우회→조립판 관측으로 이동한다. 과거 몸체 우회 경로의39N/잔류21N 중단 근거를 보존하며 `--confirm-route-clear`는 새 현장 경로 확인이다.

공급판에서 OpenCV stud 중심을 계산하고 검출/미검출·metric XY 보조 적용·좌표 fallback을 기록한다. 카메라 지연 시 정지 상태에서 피드백/팝업을 처리하며 기다린다. 공급 ROI는 B→두 클릭으로 바꿀 수 있다. 원본 ROI/교시를 덮어쓰지 않는다. mapping 검증과 같은 관측 pose가 없으면 검출돼도 metric XY를 적용하지 않는다. 정확히 분석에 사용한 원본 영상·샘플·RGB stamp도 저장한다.

파지 후 G로 실제 블록 존재와 등록된 파지 관계를 확인한다. 조립판에서는 실측 착좌 TCP의+20mm pose로 이동하고 A로 블록/격자 방향을 확인한다. 이는 기준 pose 적용과 작업자 확인이며 자동 실제 윗면 roll/pitch 측정·보정이 아니다. T→두 클릭의 윗면 모서리는 기존 가상 격자와 **픽셀 yaw 진단**에만 사용한다. 이후에는 수평 복귀/XY 보정/HJK 루프를 호출하지 않는다. 의도적 기울임도 접촉축을 상공으로 옮긴 XYZ+자세 waypoint로 수행한다.

기울임 후 접촉 직전 raw wrench를 기준으로 저장한다. entry pose까지 이동한 뒤 N으로 제한 검색, E로 실제 stud 걸림을 보고한다. 눌림 힘이45N 미만이라는 이유로 자동 걸림 전이하지 않는다. 실제 걸림 TCP와 등록된 축의 차이가 크면 임의로 축을 평행 이동하지 않고 재측정 사유를 남긴다. R 후 실제 정지 걸림 TCP를 시작점으로 명시된 BASE 접촉축에 대해 부분 XYZ+자세 원호를 계산한다. I로 결과를 기록하고 **부분 기울임·파지 유지 상태에서 종료**한다. 끝에서 완전 착좌/개방/상승/윗면 누름으로 넘어가지 않는다.

| 팝업 입력 | 의미 |
|---|---|
| G / A |각 해당 대기 단계에서 실제 파지 관계 / 정렬 확인 |
| N / E |정지 검색 단계에서 다음 제한 하강 / stud 걸림 보고 |
| R / I |부분 회전 실행 / 부분 결과 관찰 기록 |
| B / T / C |공급 ROI / 윗면 모서리 두 클릭 / 진단 선택 초기화; 이동 명령 없음 |
| L / S / M / U |판·구조 들림 / 파지 미끄러짐 / 접촉부 이동 / 미확인 보고 후 STOP |
| ESC / 창 닫기 |STOP, 자동 개방·재전송·재시도 없음 |

해당 대기 단계의 키만 받으며 움직이는 중의 사전 확인 키는 다음 단계로 가져가지 않는다. fault/ESC는 항상 처리한다. 단일 ROS node/기존 writer와 worker 분석·저장을 사용한다. events.jsonl에 명령·실제 TCP/SO(3) 오차·폭 변화·raw 힘/모멘트·기준 모멘트 변화·작업자 입력과 확정 관찰·시간을 저장한다. 동작 중 최대5Hz와 단계별 RGB/overlay를 저장하며 연속 동영상/영상–pose 독립 동기화 검증은 아니다. STOP 후 오류 시점 영상 저장을 마친 뒤 정리한다. 기록 실패가 STOP을 막지 않는다.

### 사용자 명령

현재 자료로 장치 연결 없이 준비 상태를 확인한다.

```bash
cd "/home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge"
python3 robot_control_integration/scripts/yellow4_contact_trial.py --output logs/yellow4-challenge-stage4-preview
```

실측 입력과3단계 실제 run/검토가 준비된 뒤 별도 contact 설정 복사본을 사용한다. 아래 `/절대경로/...`는 실제 파일로 바꾼다. 현재 pending 양식과 preview 출력만으로 실행하지 않는다.

```bash
python3 robot_control_integration/scripts/yellow4_contact_trial.py \
  --measurements /절대경로/measurements.json \
  --config /절대경로/contact-trial-reviewed.json \
  --air-run /절대경로/yellow4-stage3/run-실제기록 \
  --start-zone home --output logs/yellow4-challenge-stage4
```

preview.json의 입력/후보/누락과 partial-path.png를 확인하고 기존 ROS 환경에서 사용자가 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/cobot2_ws/install/setup.bash
export ROS_DOMAIN_ID=20
python3 robot_control_integration/scripts/yellow4_contact_trial.py \
  --measurements /절대경로/measurements.json \
  --config /절대경로/contact-trial-reviewed.json \
  --air-run /절대경로/yellow4-stage3/run-실제기록 \
  --start-zone home --output logs/yellow4-challenge-stage4 \
  --execute --confirm-hand-clear --confirm-route-clear --confirm-target-empty
```

현재4단계는 PREPARED_FOR_FIELD_TEST다. 미측정 입력/3단계 실제 결과/이번 걸림·부분 회전 실물 결과가 남아 있다. 5단계 요청 시 이 기록을 먼저 검토하며 명령 완료나 I 입력을 완전 체결 완료로 판단하지 않는다.

## 5단계 산출물 — 완전 회전·개방 후 검사·선택적 중심 누름 준비

`app/yellow4_seating_trial.py`와 `settings/yellow4_challenge_20261014/seating_trial.json`을 추가하고 기존 contact 실행기에 `--stage 5`를 연결했다. 기본 옵션은 계속4단계다. 공급 최초5mm 파지·OpenCV 검출/미검출/metric 보조/fallback·MoveL 경유와 관측·수동 걸림·부분 회전까지 같은 코드를 사용한다. 원본 공급/착좌/TCP/tool/보정, Round2 기본 step/Plan/B Current 및 다른 checkout은 변경하지 않는다. HUMAN_REPLACEMENT는 별도 실측15mm 공급 파지/같은 grasp_id 관계가 필요하며 +10mm 후보로 실행하지 않는다.

### 입력과 실제 검증 경계

현재 저장된 자료에는 읽기 전용2단계 캡처와3단계 미완성 preview만 있으며 실제3·4단계 회전 run은 없다. 따라서5단계는 **PREPARED_FOR_FIELD_TEST**다. 실제 파지 관계·착좌 블록 pose·축/방향·판 고정 및 앞 단계 실물 확인을 합성값으로 채우지 않는다. 분리 축은 결착 필수 조건으로 추가하지 않는다.

`--partial-run`의4단계 run 내부 preview.json/events.jsonl에서 REAL 부분 회전 결과, 실제 작업자 걸림/부분 관찰 기록, 대상·grasp_id·파지 pose/관계·축·각도/간격·블록/stud·접촉 조건을 확인한다. ABORT/개방/누름을 수행한 run이나 달라진 조건은4단계 근거로 사용하지 않는다. `partial_trial_review`에는 실제 근거 `evidence_ref`와 `contact_axis_observed`, `rotation_direction_confirmed`, `grip_maintained`, `board_fixed`, `conditions_confirmed`를 실제 검토 후 true로 기록한다. 소프트웨어가 후보6mm/s·1°/s·45N·모멘트 변화1Nm을 실물 조건이나 물성 한도로 자동 승격하지 않는다.

별도 `--contact-config`가 없으면4단계 run에 저장된 실제 사용 설정을 우선한다. `--measurements`/`--air-run`도 명시하지 않은 경우 기록된 출처 파일이 현재 존재하면 읽어 사용한다. 파일이 없으면 미확인으로 남기며 새 pose/축/실측 관계를 생성하지 않는다. 다른 파일을 명시하면 기록과 일치하는지 검사한다. 새로운 실물 시험은 공급판에서 다시 시작하며4단계 종료 위치에서 이어 움직이는 resume 명령이 아니다.

### 결착·검사 순서

공급판 빈 그리퍼60mm·1번 노랑 한 블록·빈 목표·정지 상태로 시작한다.4단계까지 G/A/N·E/R/I를 동일하게 수행한 뒤 **F로 나머지 접촉축 회전 → O로 착좌 상태 확인/개방 → 실제 개방 pose의 XY·자세 유지 수직 상승 → I로 개방 후 블록 위치/윗면 상태/유지 확인**을 수행한다. 의도적 기울임 이후에는 yaw/XY/수평/HJK 보정을 호출하지 않는다. 나머지 원호는 현재 실제 부분 회전 TCP에서 같은 BASE 축에 대한 XYZ+SO(3) 회전으로 계산하며 목표 모델 각도0°까지 간다.

O는 작업자 착좌 관찰이고 I는 개방 후 유지 관찰이다. 실제 블록 RPY 수치/독립 위치 판정은 producer가 없어 UNKNOWN/null로 기록한다. `operator_reported_seated=true`와 `assembly_completion=false`를 구분한다. 위치·힘·모멘트·폭/미끄러짐·응답 불명·STOP이 먼저 발생하면 개방·자동 복구·재전송을 수행하지 않는다. 정상적으로 요청한 개방 이후의 실패도 다시 닫거나 개방을 반복하지 않고 현재 상태를 보존한다.

### 선택적 닫힌 패드 누름

기본 `press.enabled=false`이므로 패드 자료가 없다는 이유로 기본 결착/개방 후보를 막지 않는다. 누름을 선택할 경우 `press.profile`에 **실측 닫힌 빈 패드 접촉 TCP**와 같은 대상/grasp_id/TCP/tool 관계를 제공한다. 높이/자세가 null인 기존15mm pending 양식이나 단순 base-Z+10mm를 패드 datum으로 사용하지 않는다.

프로파일 필드: `evidence_ref`, `pad_contact_verified=true`, `frame="BASE"`, 동일 `target`, `grasp_id`, `tcp`, `tool`, `contact_tcp_pose_mm_zyz_deg`, `parameter_ref`, 양의 `near_contact_offset_mm`, `max_travel_mm`, `velocity_mm_s`, `acceleration_mm_s2`, `empty_width_mm`, `empty_width_tolerance_mm`, `force_stop_n=45`. 접촉 pose는 등록된 착좌 XY/자세와 일치해야 한다. 숫자는 실제 캡처/검토 자료에서 지정한다. empty 폭12mm 이하 조건은 기존 RG2 빈 패드 경로에서 읽는 범위이며 status0/2를 둘 다 처리한다. status2만으로 블록을 쥐었다고 판정하지 않는다.

누름 전 실제 개방 후 FK pose를 사용해 XY·자세를 고정한다. 등록된 블록 평면의 normal과 실측 패드 접촉 pose로 실제 XY에서의 접촉 Z를 계산하고 명시된 near offset을 적용한다. 이 계산은 현재 놓인 블록의 실제 평면 재측정이 아니다. 같은 자세의 datum/현재 관찰이 불명확하면 UNKNOWN/중단으로 남긴다. 높이는 실제 개방 pose+검토한 clearance와 측정된 near-contact 높이+clearance 중 높은 값으로 수직 상승한다.

I로 개방 후 유지 확인 → P로 선택 누름 시작 → 빈 그리퍼 닫기 → 같은 XY/자세로 near-contact까지 수직 하강 → 기존 `assembly_press_trial.press`의 위치 하강을 수행한다. raw 합력45N은 STOP 조건이며 일정45N 유지 힘 제어가 아니다. 패드 접근/누름에는45N과 기준 모멘트 변화 검사를 유지한다. 네이티브 force/compliance 명령은 호출하지 않는다.

결과는 `FORCE_THRESHOLD_REACHED_STOP_VERIFIED` 또는 `MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD`이며 둘 다 체결 성공 판정이 아니다. 압력 중단/이동 한도 종료 후 자동 상승/개방/재시도 없이 정지 위치에서 I로 관찰한다. 확인된 압력 STOP 뒤의 수동 관찰에서는 같은45N을 다시 실패로 처리하지 않지만 장치·그리퍼·피드백 검사는 계속한다. 오류/창 닫기와 nested 누름 STOP은 UI 없이 ROS 응답을 처리하며 이미 요청한 STOP/이동을 자동 재전송하지 않는다.

### 사용자 실행

현재 상태를 장치 연결 없이 확인한다.

```bash
cd "/home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge"
python3 robot_control_integration/scripts/yellow4_contact_trial.py --stage 5 --output logs/yellow4-challenge-stage5-preview
```

앞 단계 실제 run과 검토가 준비된 뒤 `seating_trial.json`의 별도 검토 복사본을 사용한다. 아래 경로는 실제 파일로 바꾸고 원호 그림/preview의 출처와 누락을 먼저 확인한다. 기본은 누름 제외다.

```bash
python3 robot_control_integration/scripts/yellow4_contact_trial.py --stage 5 \
  --config /절대경로/seating-trial-reviewed.json \
  --partial-run /절대경로/stage4/run-실제기록 \
  --start-zone home --output logs/yellow4-challenge-stage5
```

기록된 원본 파일이 다른 위치에 있다면 `--measurements /절대경로/measurements.json --air-run /절대경로/stage3/run-실제기록 --contact-config /절대경로/contact-trial-reviewed.json`으로 명시한다. source/관계/조건을 다시 검사한다. 실제 장치 실행은 데스크톱 터미널에서 사용자만 수행한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/cobot2_ws/install/setup.bash
export ROS_DOMAIN_ID=20
python3 robot_control_integration/scripts/yellow4_contact_trial.py --stage 5 \
  --config /절대경로/seating-trial-reviewed.json \
  --partial-run /절대경로/stage4/run-실제기록 \
  --start-zone home --output logs/yellow4-challenge-stage5 \
  --execute --confirm-hand-clear --confirm-route-clear --confirm-target-empty
```

기존 command/actual/SO(3)/폭/raw wrench/작업자 입력·시간·최대5Hz RGB/overlay 기록을 유지하고 실제 개방 pose·패드 높이 계산·누름 결과를 추가 저장한다. 압력 구간도 실제 TCP/SO(3) 오차를 기록한다. 실제 팝업 조작/결착/개방 후 유지/패드 누름은 미검증이다. 다음6단계는 이 결과와 완전 결착된 노랑 한 블록을 확인하고 별도 분리 재파지/축 자료로 준비한다.

## 6단계 산출물 — 독립 재파지·부분 회전 분리 코드 준비

사용자 요청에 따라 실물 시험은 뒤로 미루고 개발만 진행했다. 현재2단계 센서 캡처와3·5단계 미완성 preview가 있고3~5단계 REAL 완료 run은 없다. 현재 블록의 실제 결착/위치/기울기/판 고정/빈 패드 상태도 이번 개발에서 확인하지 않았다. **PREPARED_FOR_FIELD_TEST**는 코드 준비이며 실행 가능한 실측 프로파일이나 실물 분리 성공을 뜻하지 않는다. 기존 completed_stage1/physical next_stage2를 보존하고 next_development_stage7로 구분한다.

`app/yellow4_removal_trial.py`는 공급 파지와 별개의 재파지 입력을 받아 Stage1 임의 축/프레임 기하를 호출한다. `scripts/yellow4_contact_trial.py --stage 6`으로 기존 MoveL writer·ROS node·독점 잠금·팝업·원본 영상/시간 기록을 재사용한다. 기본 CLI 단계4와 Round2 기본 step/Plan/B Current·다른 checkout·원본 공급 교시는 유지한다. 새 서비스/클래스/dependency는 없다. 같은 guard/MoveL/STOP/기록 로직을 복제하는 별도 실행기 대신 기존 challenge 실행기에 분리 분기를 연결했다.

### 독립 입력과 출처

`settings/yellow4_challenge_20261014/removal_trial.json`의 속도/가속도·힘/기준 대비 모멘트 변화·폭 변화·축 등록 허용값은 null이다. 4단계 후보6mm/s·1°/s·45N·1Nm을 분리에 자동 복사하지 않는다. 공급판과 관측/이송의 기존 사용자120/12mm/s 설정은 출처를 읽어 재사용한다. 재파지 상공20mm는 이전 사용자 관측 여유의 재사용이며 실제 간섭 여유 검증이 아니다. 접촉 속도/가속도·중단값과 `parameter_source`, 현재 블록·판 고정·재파지 관계·분리축·조건의 검토를 별도 지정한다.

`field_review`에는 `evidence_ref`와 `current_seated_block_verified`, `board_fixed`, `regrasp_relation_checked`, `removal_axis_checked`, `conditions_confirmed`를 실제 확인 후 true로 기록한다. `--seating-run`은5단계 실제 run의 고정 preview/events에서 REAL 결과·착좌 및 개방 후 작업자 관찰·앞3/4단계 출처를 확인한다. ABORT/FAKE/누락 결과는 사용하지 않는다. 로봇 명령 완료/작업자 보고만으로 현재 결착을 독립 검증했다고 판단하지 않고 별도 현재 실측/검토를 요구한다.

`--measurements`에는 아래 **미완성 입력 형식**을 채운 별도 파일을 제공한다. null은 확인이 필요한 값이며 이 예제는 실행할 수 없다. `target`/TCP/tool은 preview에 표시된 실제 연결 대상과 일치해야 한다.

```json
{
  "schema_version": "yellow4-removal-measurement/1",
  "source_kind": "OPERATOR_FIELD_MEASUREMENT",
  "evidence_ref": null,
  "target": null,
  "tcp": null,
  "tool": null,
  "grasp_id": null,
  "grasp_mode": "STANDARD",
  "pad_bottom_from_block_bottom_mm": 5,
  "coordinate_frame": null,
  "frame_pose_in_base_mm_zyz_deg": null,
  "board_fixation_confirmed": false,
  "regrasp_tcp_pose_mm_zyz_deg": null,
  "seated_block_pose_mm_zyz_deg": null,
  "block_geometry": null,
  "target_studs": {"frame": null, "centers_mm": null},
  "close_mm": null,
  "width_tolerance_mm": null,
  "removal": {"tilt_deg": null, "angular_step_deg": null,
    "contact_line": {"frame": null, "points_mm": null}}
}
```

pose 단위는 XYZ mm/ZYZ deg이고 축 두 점/stud 네 중심의 frame은 `coordinate_frame`이다. `frame_pose_in_base_mm_zyz_deg`는 T_BASE_frame, BASE 자체면 identity다. 재파지 TCP와 현재 착좌 블록 pose를 같은 입력 프레임에서 측정해 T_tcp_block=inverse(T_frame_tcp)×T_frame_block을 계산한다. 실제 분리 축은 별도로 명시하며 assembly 축이 없어도 분리 기하를 계산할 수 있다. 축이 결착과 같거나 경로가 역재생 가능하다고 추정하지 않는다. 각도 부호/간격은 `removal`에서 읽는다. 실제 파지 관계를 변경하면 TCP 원호는 달라지고 블록의 같은 접촉축 회전을 유지한다.

기본 STANDARD5/보완 HUMAN15를 그대로 구분한다.15mm 모드도 별도 재파지 pose/관계가 필요하고 base-Z+10mm나 공급판 TCP를 사용하지 않는다. `close_mm`과 실제 폭 허용범위는 빈 닫힌 패드/60mm 개방과 구분 가능해야 한다(기존 빈 패드 범위12mm 이하). 검토 기록·pose·block geometry/stud 자료의 출처를 보존한다.5단계 등록 블록 pose와 현재 실측 pose 차이는 기록하며 실제 기울기는 실측 입력 외에 팝업 픽셀 yaw만으로 생성하지 않는다.

### 실행 흐름과 팝업

초기 실제 그리퍼 폭/status와 함께 **V: OPEN_EMPTY / D: CLOSED_EMPTY_PAD**를 작업자가 확인한다. status2를 블록 파지로 간주하지 않는다. 닫힌 빈 패드가 확인된 경우에만 한번 개방하고, 공급판으로 파지하러 가지 않는다. home/supply 시작은 기존 첫·둘째 MoveL 경유 → 마지막 경유를 조립판 재파지 관측점으로 연결한다. assembly 시작도 수직 여유 확보 후 관측점에 간다.

**A: 현재 대상 완전 결착·판 고정 확인 → 등록 재파지 TCP로 하강 → 그리퍼 닫기 → G: 실제 재파지 관계 확인 → R: 분리 원호 시작 → I/W/N: 결과 관찰** 순서다. 접촉 직전 raw 모멘트를 기준으로 하강·닫기·회전 중 변화와 합력·폭 drift를 감시한다. 실제 정지 재파지 TCP가 등록 축/자세 허용범위 안에 있을 때만 같은 BASE 축에서 XYZ+SO(3) 원호를 수행한다. 실제 위치에 맞추려고 축을 임의 이동하지 않는다. 의도적 분리 회전 중 수평 복귀·XY·HJK 보정이 없다.

- I: 한쪽 해제·남은 stud 결합, W: 전체 해제 관찰, N: 해제 관찰 안 됨을 작업자 보고로 구분한다. **세 결과 모두 자동 상승·회수·개방 없이 마지막 파지를 유지한다.** W도 독립 전체 해제 검증이나 인양 허가가 아니다.
- L: 조립판/아래 구조 들림, S: 파지 미끄러짐, M: 접촉부 이동, U: UNKNOWN 및 ESC/창 닫기는 중단한다. 자동 개방/재전송/재시도/축 이동/상태 복구가 없다.
- 결과의 `removal_completion=false`, `all_studs_released_independently_verified=false`, 실제 block RPY null을 유지한다. 힘 저하/명령 완료/기하의 마지막 각도만으로 해제 판정하지 않는다. STOP 이후 현재 상태에서 자동 이어서 실행하는 기능은 없다.

command/actual TCP·SO(3) 오차·폭·raw 힘/모멘트·모멘트 변화·현재/등록 블록 pose 차이·관찰/중단 원인과 시간, 최대5Hz 원본 RGB/overlay를 기존 worker로 기록한다. 영상/pose의 독립 동기화나 실제 접촉축 유지 검증을 주장하지 않는다. ROS/팝업은 이동·응답·관찰 대기 중 계속 처리한다. 과거39N/잔류21N 경로 간섭 기록과 별도 경로 여유 확인을 유지한다.

### 사용자 명령 — 현재는 preview만

```bash
cd "/home/rokey/Documents/ChatGPT/로봇제어 개발/c2_integration_challenge"
python3 robot_control_integration/scripts/yellow4_contact_trial.py --stage 6 --output logs/yellow4-challenge-stage6-preview
```

실측 준비를 재개할 때 다음 기존 도구로 수동 정지 위치의 센서/카메라를 읽고 SPACE로 저장할 수 있다. 로봇/그리퍼 자동 명령은 없다. 이것만으로 블록 pose·접촉축·파지 높이가 측정된 것으로 채택하지 않는다. `--measurements`에 분리 양식을 이 관측 도구로 넘기지 않는다(서로 다른 계약이다).

```bash
python3 robot_control_integration/scripts/yellow4_observe.py observe --live --read-gripper \
  --view assembly --role SEATED_GRASP_CANDIDATE --output logs/yellow4-challenge-stage6-read-only
```

실측 자료와5단계 실제 run/검토가 준비되면 아래 실제 파일 경로를 채워 먼저 execute 없이 preview/`removal-path.png`를 확인한다. 이번 개발에서는 이 실물 명령을 실행하지 않았다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/cobot2_ws/install/setup.bash
export ROS_DOMAIN_ID=20
python3 robot_control_integration/scripts/yellow4_contact_trial.py --stage 6 \
  --config /절대경로/removal-trial-reviewed.json \
  --measurements /절대경로/removal-measured.json \
  --seating-run /절대경로/stage5/run-실제기록 \
  --start-zone home --output logs/yellow4-challenge-stage6 \
  --execute --confirm-hand-clear --confirm-route-clear --confirm-target-seated
```

재파지/원호 계약·양쪽 회전·임의 프레임·접촉선 유지·파지 변경·STD5/HUMAN15·출처 보존·빈 패드status0/2·분리 관찰·fault/ACK·node-free CLI/팝업 경로 검사를 합성 fixture와 Fake backend로 수행한다. 실제 로봇 시험/팝업 조작/부분 해제/판 고정·간섭 결과는 미검증이며 다음7단계는 실제 부분 결과를 별도로 확인하고 완전 해제·회수 코드를 준비한다.
