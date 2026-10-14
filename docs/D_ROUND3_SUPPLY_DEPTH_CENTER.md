# 공급판 RGB-D 중심 XY 보정

2026-10-15. 코드 연결과 합성 입력 검증 단계이며 실제 카메라 보정·집기 정확도 검증은 아니다.
기본 실행은 기존 동작이다. 프로파일을 명시한 실행만 새 보정을 요구한다.
회전·Z·속도·힘·재파지·B의 Current/비교 책임은 변경하지 않는다.

## 처리 흐름

1. 공급판 관측 자세에서 정지를 확인하고 새 RGB·정렬 Depth·RGB CameraInfo를 받는다.
2. 1280×720 RGB는 640×360으로 균등 축소하고 상하 60픽셀을 추가한다. 기존 640×480 입력은 그대로 사용한다.
3. D OpenCV가 처리 영상의 스터드 중심을 검출한다. 중심을 원본 픽셀 좌표로 역변환한다.
4. 원본 RGB와 정렬된 Depth에서 블록 내부 3×3 패치의 깊이를 확인한다. 0/범위 밖/깊이 편차 초과/블록 밖 패치는 거부한다. 배경으로 구멍을 메우지 않는다.
5. RGB CameraInfo의 내부 파라미터·왜곡으로 카메라 좌표를 구하고, `T_base_tcp @ T_tcp_camera_mm`으로 Base 좌표로 바꾼다. pose는 기존 mm/ZYZ 도 단위다.
6. `현재 표면 중심 - 교시 당시 기준 표면 중심`의 XY만 기존 pickup_pose에 더한다. TCP와 물체 중심의 차이는 교시 기준과의 상대 변위로 유지한다. 표면 깊이를 TCP의 목표 Z로 쓰지 않는다.
7. 보정 상한·높이 차이·공급판 교시 범위·촬영 전후 정지/자세·이동 직전 유효시간을 확인한 뒤 기존 파지 경로로 전달한다.

각 RGB/Depth/CameraInfo는 300ms 이내, 서로의 시각 차이는 50ms 이내여야 한다. ROS 시계 기준으로 확인하며 이동 직전에는 남은 유효시간을 monotonic clock으로 확인한다. Depth는 RGB에 정렬된 `16UC1`, 단위 mm만 받는다. 다른 단위/형식은 자동 추정하지 않는다.
토픽은 RGB=기존 vision.rgb_topic, Depth=`/camera/aligned_depth_to_color/image_raw`, 정보=`/camera/color/camera_info`이다.

좌표 역변환은 축소하면서 잃은 중심 검출 정보를 복원하지 않는다. 처리 영상의 0.5픽셀 차이는 원본 1픽셀에 대응하며 RGB–Depth 정렬·깊이·외부 보정 오차도 남는다. 원본 해상도의 슬롯 영역에서 중심을 직접 검출하는 개선은 아직 반영하지 않았다. 현재 합성 검사 통과를 실제 집기 정확도 보장으로 해석하지 않는다.

## 실측 프로파일: 자동으로 채우면 안 되는 값

[템플릿](../robot_control_integration/settings/supply_depth_center.template.json)을 별도 파일로 복사한다. 템플릿 자체는 실행 불가다.

| 필드 | 필요한 실제 근거 |
|---|---|
| calibration_ref / independently_verified | 실제 장착·TCP 기준으로 확인한 보정 기록과 검증 결과 |
| connection / observation_pose | 실행 구성의 robot_id·tcp·tool 및 공급판 관측 pose와 정확히 일치 |
| T_tcp_camera_mm | RGB optical 좌표를 현재 TCP 좌표로 옮기는 4×4 rigid transform. translation은 mm |
| input_size / camera_frame | 실제 RGB·정렬 Depth·CameraInfo의 해상도와 동일 optical frame |
| layout_sha256 | 위 변환을 적용한 **실제 영상에서 다시 확인한** 640×480 공급 슬롯 layout 파일의 SHA256 |
| depth_range_mm / max_depth_spread_mm | 공급판 표면 관측에서 확인한 유효 깊이 범위·패치 편차 |
| max_height_error_mm / max_shift_mm | 기준 표면 높이와의 허용 차이·허용 XY 보정 거리 |
| references | 각 실행 슬롯의 기준 중심. 아래 형식 사용 |

references 항목은 `slot_id`, `pickup_pose`(6개 값), `surface_center_base_mm`(3개 값)이다.
예를 들어 T1의 slot_id는 `yellow_2x2x1_04`이며, pickup_pose는 현재 T1 준비 결과와 일치해야 한다.
surface_center는 **교시 위치에 블록이 놓인 상태에서 같은 스터드 중심/패치 처리로 측정한 기준점**이다.
pickup_pose의 XYZ를 surface_center로 복사하면 안 된다. TCP 집기 위치와 블록 윗면은 다른 점이다.

기존 640×480 슬롯 영역·크기 임계값은 1280×720 변환 영상과 일치한다고 가정하지 않는다. 실영상으로 다시 확인하고 설정을 저장한 뒤 해시를 기록한다. 프로파일 지정만으로 기존 layout을 자동 변경하지 않는다.
현재 저장소의 PROVISIONAL_NOT_FOR_MOTION 보정·URDF 명목 장착값을 검증 완료 값으로 승격하지 않는다. CameraInfo 자체는 카메라–TCP 외부 보정을 제공하지 않는다.

## 실행 경로

로봇 PC에서 보정 자료가 갖춰진 뒤 native T1 준비 결과 확인(장치 연결 없음):

```bash
cd robot_control_integration
python3 -m scripts.round2_three_step_trial preview --only-step T1 \
  --supply-depth-profile /absolute/path/supply-depth-verified.json
```

실물 실행은 같은 옵션에 `run --execute --confirm-hand-clear --start-zone home`을 사용한다. 원래 T1 사전 배치·팝업 순서·장치 확인은 [기존 안내](D_ROUND3_FIXED_HMI.md)를 따른다.
독립 공급판 시험에도 `scripts.supply_pick_release_trial --supply-depth-profile ...`를 지정할 수 있다.
`replay`에는 실제 RGB-D 프로파일을 넣을 수 없다. 합성 중심값을 실제 Depth 보정으로 표시하지 않는다.

HMI T1도 사용하는 공급판 설정의 `vision.depth_center_profile`에 프로파일 경로를 명시하면 이를 계승한다. 상대 경로는 저장소 루트 기준이다. 별도 HMI CLI 옵션은 추가하지 않았다. 프로파일 미지정 시 기존 T1/full-real 기본 동작을 유지한다.

## 실패와 기록

활성화된 경로에서는 검출 실패·Depth 누락·CameraInfo 불일치·오래된 관측·기준점 불일치·이동·보정 상한 초과를 오류로 중단한다. 교시 위치로 조용히 대체하지 않는다. 카메라 재시작/재보정/자동 재시도는 하지 않는다.
`VISION_DECISION`에는 `depth_center`, `center_assist_applied`, `commanded_pickup_pose`가 기록된다.
영상 옆 JSON에는 원본 중심 픽셀·표면 Base 좌표·기준 좌표·3×3 깊이 패치·CameraInfo·calibration_ref·촬영 pose·XY 이동량이 남는다. 정상 자료 생성 이전 오류는 실행 콘솔에서 `SUPPLY_DEPTH_*` 원인을 확인한다.

## 장치 없는 검증

```bash
cd robot_control_integration
PYTHONPATH="$PWD:$PWD/../perception" python3 -m pytest \
  tests/unit/test_supply_depth_center.py \
  tests/unit/test_supply_stud_backend.py \
  tests/unit/test_supply_pick_release_trial.py -q
```

합성 RGB-D·로봇 pose로 좌표 변환, XY만 변경, 해상도 역변환, 누락/역순 시각/잘못된 frame/깊이/슬롯/보정 범위와 LiveVision 연결을 확인한다. 실제 ROS 전달·깊이 품질·외부 보정·집기 성공을 증명하지 않는다.
