# 홍동님용: 조립판 캘리브레이션 좌표를 비전 노드에서 사용하기

## 먼저 확인할 상태

압축본의 `HANDOFF_STATUS.md`와 `MANIFEST.json`을 먼저 확인한다. 현재 측정에서는 원점을 0부터 센 번호와 두 점의 선택 순서를 보정한 독립 검증의 최대 오차가 **1.655 mm**, RMSE가 **1.260 mm**다. 초기 최대 오차 기준 **1.5 mm는 통과하지 않았다**. 검증 상태를 임의로 true로 바꾸지 않는다. 이후 다시 패키징한 전달본의 최신 상태는 `HANDOFF_STATUS.md`를 따른다.

`vision_coordinates.py`는 기본적으로 미검증 결과를 거부한다. 현재 결과로 개발·시각화 시험을 할 때만 `allow_unvalidated=True` 또는 CLI `--allow-unvalidated`를 사용한다. 출력에도 미검증 상태가 유지된다. 이 옵션은 정확도 검증을 대신하지 않는다.

## 폴더와 필수 파일

압축을 풀면 `lego_calibration/` 폴더가 나온다. 이 폴더 안에서 명령을 실행한다. 원본 파일의 발신자 경로 `/home/rokey/...`를 수신자 PC에서 만들 필요는 없다.

| 파일 | 역할 |
|---|---|
| `runs/view01/calibration.json` | 실행 중 읽는 변환 H, 카메라 내부 파라미터, 판 자세, 간격, 검증 상태 |
| `runs/view01/stud_coordinates.csv` | 576개 stud 좌표표; 픽셀→임의 블록 좌표 변환은 JSON과 함수 사용 |
| `runs/view01/empty.png` | 같은 촬영 자세의 빈 판 기준 영상 |
| `runs/view01/grid_overlay.png` | 기준 영상에 격자를 겹친 확인용 영상 |
| `runs/view01/validation_zero_based_corrected.json` | 현재의 번호·순서 보정 후 검증 보고서 |
| `captures/` | 원본 영상/CameraInfo/클릭 기록. 실패한 원본 기록도 추적용으로 보존 |
| `geometry.py` | 실제 왜곡 보정·좌표 변환 함수 |
| `vision_coordinates.py` | 검출기와 연결할 간단한 Python API 및 단일 픽셀 CLI |
| `vision_demo_node.py` | ROS 2 이미지 구독→후보 좌표 JSON 발행 예제 |
| `README_ko.md` | 촬영부터 새 캘리브레이션을 만드는 절차 |

JSON의 `source_image`와 검증 보고서의 `source`는 발신자 촬영 기록이다. 수신자 실행에는 이 절대 경로가 필요하지 않다. 기준 영상은 `calibration.json` 옆 `empty.png`를 상대 경로로 찾는다.

## 재사용 가능한 조건

기존 H는 **현재 카메라-판의 상대 위치와 1280×720 컬러 영상**에만 적용된다. 같은 코드 파일을 옮기는 것과 같은 좌표 변환을 재사용하는 것은 별개다.

- 같은 판·같은 카메라·같은 렌즈/영상 설정·같은 손목 촬영 자세라면 결과를 검사한 뒤 재사용할 수 있다.
- 홍동님이 다른 카메라나 다른 위치에서 촬영하면 새 빈 판 영상으로 재캘리브레이션한다. 모델명이 D435i로 같아도 H를 그대로 적용하지 않는다.
- 카메라 손목이 움직인 뒤 촬영하려면 기록한 자세로 복귀하고 기준점을 다시 확인한다. 현재 빨간 테이프 방식은 이동을 자동 감시하지 않는다.
- 이미지 resize/crop/회전/좌우 반전 후의 픽셀을 H에 직접 넣지 않는다. 검출 좌표를 먼저 **원본 컬러 영상 픽셀 좌표**로 되돌린다.

현재 ROS 컬러 토픽은 `/camera/camera/color/image_raw`, CameraInfo는 `/camera/camera/color/camera_info`, 광학 frame ID는 `camera_color_optical_frame`이다. 수신자의 경로가 다르면 인자로 지정한다.

## 좌표계와 번호

- 물리적 원점은 빨간 stud **중심**, X/Y 단위는 **mm**다.
- 현재 기준 영상에서는 **+X가 오른쪽, +Y가 위쪽**이다. 판의 실제 화살표가 우선이다.
- X는 열 방향, Y는 행 방향이다. `row/col`을 `X/Y` 순서로 해석하면 축이 바뀐다.
- `pitch_mm=16.75`: stud 5개 포함 외곽 길이 75 mm, 지름 약 8 mm로부터 `(75−8)/(5−1)`로 계산한 값이다. 지름은 근삿값이므로 정확한 mm 스케일은 중심 간 거리 실측으로 추가 확인한다.
- **0부터 세는 번호:** `col_index_0based=X/16.75`, `row_index_0based=Y/16.75`.
- 기존 CSV의 `row,col`과 기본 `row_continuous,col_continuous`는 **1부터** 시작한다. 원점 행/열이 1이고 0 기반 번호보다 각각 1 크다.
- 블록 중심은 소수 행/열일 수 있다. 가장 가까운 stud를 찾았다고 블록 점유 영역이나 시작 stud가 확정되지는 않는다.

예를 들어 0 기반 `(row,col)=(3,3)`이면 `X=50.25,Y=50.25 mm`이고, 기존 CSV 인덱스로는 `(4,4)`다.

## 기존 Python 검출기 연결

같은 디렉터리 또는 자신의 ROS Python 패키지 안에 `geometry.py`, `vision_coordinates.py`를 함께 배치한다. 패키지 안으로 옮긴다면 모듈 import 경로도 실제 패키지 이름에 맞춘다. 예제는 이 폴더에서 실행하는 구조다.

```python
from vision_coordinates import BoardCoordinateMapper

# 개발용 임시 사용. 검증 통과 전달본에서는 allow_unvalidated 인자를 생략한다.
mapper = BoardCoordinateMapper(
    "runs/view01/calibration.json",
    allow_unvalidated=True,
)

def convert_detection(frame_bgr, box_xyxy, measured_surface_height_mm=0.0):
    height, width = frame_bgr.shape[:2]
    result = mapper.map_bbox(
        box_xyxy,
        image_size=[width, height],
        surface_height_mm=measured_surface_height_mm,
    )
    if not result["inside_board"]:
        return None
    return result
```

`box_xyxy`는 원본 영상에서의 `[x1,y1,x2,y2]`다. 모델 입력이 640×640이고 원본이 1280×720이면 letterbox padding과 resize 비율을 역변환한 뒤 넣는다. 사용하는 검출기 API가 이미 원본 좌표를 반환하는지도 확인한다. `u,v`는 정수로 반올림하지 말고 소수 중심을 유지한다.

윗면 중심을 별도로 검출한다면 bbox 대신 다음을 사용한다.

```python
point = mapper.map_pixel(
    u=detected_top_centre_u,
    v=detected_top_centre_v,
    image_size=[frame_bgr.shape[1], frame_bgr.shape[0]],
    surface_height_mm=measured_surface_height_mm,
)
x_mm, y_mm = point["board_xy_mm"]
row0 = point["row_index_0based"]
col0 = point["col_index_0based"]
```

바운딩박스 중심은 보이는 옆면 때문에 실제 윗면 중심과 다를 수 있다. 정확한 중심이 필요하면 윗면 중심/분할 결과를 사용한다. 객체의 confidence/class ID는 검출기 출력에서 그대로 붙인다. 변환 함수는 클래스나 블록 종류를 판정하지 않는다.

### 반환 데이터의 핵심 항목

| 항목 | 의미 |
|---|---|
| `frame_id` | `lego_board`; 카메라 광학 좌표나 robot base 좌표가 아님 |
| `board_xy_mm` | 물체 지점의 판 기준 X/Y |
| `row_index_0based`, `col_index_0based` | 원점 0 기준 소수 번호 |
| `row_continuous`, `col_continuous` | 기존 코드와 호환되는 원점 1 기준 소수 번호 |
| `inside_board` | 계산된 점이 판 영역 안에 있는지 |
| `independently_validated` | 독립 검증 통과 여부 |
| `coordinate_kind` | 높이 미지정이면 `reference_plane_projection`; 보정하면 `known_height_surface` |
| `view_monitoring` | 현재 수동 방식은 `unmonitored_fixed_view` |

검출이 없거나 변환을 거부했을 때 `(0,0)`을 반환하지 않는다. `(0,0)`은 실제 원점이므로 `None`, 유효성 플래그 또는 빈 객체 목록으로 처리한다.

## 기존 로컬 비전 코드와의 접점

발신자의 `pick_and_place_text/detection.py`는 `_compute_position()`에서 bbox 중심 `cx,cy`를 구한 후 depth를 읽어 **카메라 기준 XYZ**를 계산한다. 판 좌표가 필요하면 bbox 중심이 구해진 직후 위 mapper를 호출하는 별도 출력 경로를 추가한다.

기존 `get_3d_position`/`SrvDepthPosition.depth_position`에 판 X/Y를 그대로 넣으면 카메라 XYZ를 기대하는 로봇 소비자가 잘못 해석할 수 있다. **새 이름의 판 좌표 topic/service와 `frame_id=lego_board`, 단위 mm를 사용**하고, 소비자도 이 의미에 맞춘다. 원래 robot move 코드는 이 전달본에서 수정하지 않았다. 현재 측정에는 robot base 변환이 없으며 판 좌표를 로봇 TCP 이동 목표로 바로 사용할 수 없다.

기존 일부 RealSense 구독 경로는 `/camera/color/...`로 되어 있다. 실제 `/camera/camera/color/...`에 맞추고, 카메라 이미지 구독에는 예제처럼 `qos_profile_sensor_data`를 사용한다.

## 높이 보정

기준 평면은 **빈 판 stud 윗면**이다. 알려진 stud 자체 높이 약 5 mm는 판 표면과 기준 평면의 차이며 블록 보정값이 아니다.

`surface_height_mm = 판 표면에서 검출한 블록 윗면까지 높이 − 판 표면에서 빈 stud 윗면까지 높이`

현재 블록 윗면 높이는 아직 측정하지 않았다. 높이 0으로 실행하면 기준 평면에 투영된 위치이며 블록의 실제 수직 투영 중심이 보장되지 않는다. 높이가 다른 블록은 객체별로 다른 값을 넣는다. 예제 ROS 노드의 한 개 전역 높이 파라미터는 같은 높이의 블록만 가정한다. 반사나 깊이 결측은 이 API가 자동으로 해결하지 않는다.

## ROS 2 예제 노드 실행

예제는 **빈 판 차이 + 비초록 색 후보 검출**만 수행한다. 학습된 YOLO 모델이나 정확한 블록 인스턴스 분할을 포함하지 않는다. 형광등 반사·그림자·손·맞닿은 블록으로 생긴 후보를 확인해야 한다.

터미널 A에서 카메라를 실행한다(같은 PC에서 이미 실행 중이면 중복 실행하지 않는다).

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch realsense2_camera rs_launch.py \
  camera_namespace:=camera camera_name:=camera \
  enable_color:=true enable_depth:=false \
  rgb_camera.color_profile:=1280x720x15
```

터미널 B에서 압축을 푼 `lego_calibration/` 폴더로 이동하고 다음을 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
python3 vision_demo_node.py --ros-args \
  -p calibration_file:=runs/view01/calibration.json \
  -p image_topic:=/camera/camera/color/image_raw \
  -p expected_camera_frame:=camera_color_optical_frame \
  -p surface_height_mm:=0.0 \
  -p allow_unvalidated:=true
```

**`allow_unvalidated:=true`는 현재 초안 시험용**이다. 검증을 통과한 최종 결과는 이 인자를 제거하고 사용한다. 정확한 블록 높이를 측정하면 `surface_height_mm`도 바꾼다. 노드는 로봇/그리퍼를 제어하지 않는다.

터미널 C:

```bash
source /opt/ros/jazzy/setup.bash
ros2 topic echo /lego/board_candidates --once
```

출력 메시지는 `std_msgs/msg/String` 안의 JSON이다. `frame_id`, `length_unit`, `independently_validated`, `view_check`, `candidates`를 함께 처리한다. 실행 중 카메라 크기/frame ID가 다르거나 마커 검사가 실패하면 해당 프레임의 새 결과를 발행하지 않는다. 현재 수동 방식은 같은 크기·frame ID에서도 카메라 이동을 자동 검출하지 못한다. 소비자는 timestamp를 보고 오래된 결과를 재사용하지 않는다.

## 카메라 없이 전달본 시험

현재 원점 픽셀 `(391,693)`을 판 좌표로 변환해 API·경로를 점검할 수 있다.

```bash
python3 vision_coordinates.py \
  --calibration runs/view01/calibration.json \
  --pixel 391 693 --image-size 1280 720 \
  --allow-unvalidated
```

이 픽셀은 발신자가 클릭한 원점이며 새 카메라 영상에서도 같은 픽셀이 원점이라는 뜻은 아니다. 결과의 X/Y와 0 기반 행/열은 부동소수점 정밀도 범위에서 0에 가깝다.

```bash
python3 -m pytest -q tests
```

실제 ROS 메시지 발행과 블록 중심 정확도는 별도 현장 확인이 필요하다. 먼저 알려진 stud를 수동 클릭해 좌표 변환을 확인하고, 알려진 위치에 블록을 놓아 높이와 검출 중심의 오차를 검증한다.
# 현재 보드 간격 — 2026-10-08 갱신

현장 사용 간격은 **16mm**, 양 끝 stud 중심 간 거리는 **368mm(23칸)**이다. 아래 전달 초안의 16.75mm는 과거 예시이다. 현재 사용 파일은 `recordings/board_calibration_{V0,D1,D3}/{View}/run/calibration.json`이며 17mm 원본은 각 `run_pitch17_archive`에 보존했다. 기존 클릭점 재검증과 실제 RGB-D 정확도 검증은 구분한다.
