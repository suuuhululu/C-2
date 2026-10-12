# 24×24 초록 조립판 좌표 캘리브레이션

## 현재 반영한 조건

- 조립판은 고정되어 있고, RealSense 계열 카메라는 로봇 손목의 **정해진 촬영 자세에서 정지**한다.
- 출력은 **조립판 기준 X/Y(mm), 행/열**이다. 로봇 베이스 XYZ는 선택 기능이다.
- **빨간 stud 중심을 원점**, 판의 실제 +X/+Y 표시를 좌표 방향으로 사용한다. 최초 자 사진에서는 원점이 오른쪽 아래, +X가 위쪽, +Y가 왼쪽이었다. 이후 손목 촬영 자세가 바뀌면서 화면 방향도 달라졌으므로 최초 사진의 화면 위치를 새 영상에 그대로 적용하지 않는다.
- 블록 색은 초록 조립판과 다르므로, 빈 판과의 영상 차이와 비초록 색 영역을 조합해 후보를 찾는다.
- 사용자가 stud 5개를 포함한 바깥 시작점~바깥 끝점 거리를 75 mm, stud 지름을 약 8 mm로 제공했다. 중심 간 간격은 **(75−8)/(5−1)=16.75 mm**로 계산해 입력한다. 지름이 근삿값이므로 최종 mm 정확도는 더 긴 중심 간 거리 실측으로 점검해야 한다. `--pitch-mm` 입력은 필수다.
- 사용자가 확인한 높이 약 5 mm는 **조립판 표면에서 stud 윗면까지의 stud 자체 높이**다. 블록 높이 보정값으로 사용하지 않는다.
- 목표 오차는 아직 정하지 않았으므로 **최대 1.5 mm를 초기 검증 문턱**으로 사용하고 실제 측정 후 조정한다. 이는 달성한 오차나 성능 보장이 아니다.

이번 파일은 원본 압축파일의 체커보드/핸드아이 흐름을 **고정 촬영 자세의 조립판 매핑**으로 대체한 독립 실행 코드다. 원본 ZIP, 기존 Python 파일, 기존 `T_gripper2camera.npy`는 수정하지 않았다. 원본 `verify.py`는 화면 클릭 후 로봇을 움직이므로, 아래 절차에서는 새 `lego_grid.py`를 사용한다. 새 코드는 로봇 이동·그리퍼 제어를 호출하지 않는다.

## 어떤 좌표를 만들고 어떻게 다른가

체커보드 내부 코너를 찾는 `findChessboardCorners`는 초록 stud 판에 적용할 수 없다. `board_size=(24,24)`로 숫자만 바꾸어 해결되지 않는다. 새 방식은 **위치를 아는 기준점의 영상 좌표와 판 좌표를 대응시켜 평면 변환(H)을 구하고, 규칙적인 간격으로 576개 stud 좌표를 생성**한다. 색이 같은 stud 전체를 자동 검출할 필요가 없다. 카메라 내부 파라미터가 있으면 렌즈 왜곡을 먼저 보정한다. 평면 매핑의 근거는 [OpenCV homography 설명](https://docs.opencv.org/4.5.1/d9/dab/tutorial_homography.html)이다.

좌표축과 인덱스는 다음처럼 고정한다. 여기서 행/열은 화면의 위·아래가 아니라 판에 표시한 물리적 방향을 뜻한다.

| 기준점 | 판의 물리적 위치 | 행 row | 열 col | X/Y(mm), 간격 p |
|---|---|---:|---:|---|
| A | 빨간 원점 stud | 1 | 1 | (0, 0) |
| B | A에서 +X 방향 끝의 모서리 stud | 1 | 24 | (23p, 0) |
| C | A의 대각선 반대 모서리 stud | 24 | 24 | (23p, 23p) |
| D | A에서 +Y 방향 끝의 모서리 stud | 24 | 1 | (0, 23p) |

확인한 RealSense 빈 판 영상에서는 원점이 화면 왼쪽 아래에 있다. 왼쪽 변을 따라 위로 향한 화살표가 +Y이고 아래쪽 변의 오른쪽이 +X인 경우 A→B→C→D는 **왼쪽 아래→오른쪽 아래→오른쪽 위→왼쪽 위** 순서다. 촬영 전에 실제 축 표시를 확인한다.

`X=(col-1)×p`, `Y=(row-1)×p`. **판 외곽 모서리가 아니라 가장 바깥 stud의 중심**을 클릭한다. 24개 중심 사이에는 23개 간격이 있으므로 p=16 mm일 때 첫 중심에서 마지막 중심까지는 368 mm다. 판 외형 크기는 이 값과 다르며 직접 측정해야 한다. 24×24가 실제 stud 개수인지도 확인한다.

블록 중심은 stud 중심과 일치하지 않을 수 있다. 예를 들어 원점에서 시작하는 2×2 블록의 중심은 `(row,col)=(1.5,1.5)`이다. `nearest_stud`는 가까운 stud 표시이며, 실제 점유 stud나 블록 시작 위치가 아니다. 코드가 블록 종류·방향·점유 칸을 자동 판정하지는 않는다.

## 추가로 준비할 정보

| 항목 | 필요한 이유 / 확인 방법 |
|---|---|
| stud **중심 간 간격** | 현재 입력값은 16.75 mm다(5개 stud 바깥 길이 75 mm, 지름 약 8 mm). 정밀 검증에는 X/Y 양방향의 여러 중심 사이 거리를 직접 재어 간격 수로 나눈다. |
| 전체 빈 판의 RealSense 원본 영상 | 정해진 손목 촬영 자세에서 24×24와 A/B/C/D가 모두 보여야 한다. 이번 휴대폰 근접 사진은 크기 추정용이고 카메라 매핑용이 아니다. |
| 블록을 올린 동일 자세의 영상 | 자·손을 치우고 조명·해상도·촬영 자세를 유지한다. 정확도가 필요한 블록의 윗면 중심을 식별할 수 있어야 한다. |
| 컬러 토픽과 CameraInfo | `rs_02`는 장치/네임스페이스 이름일 수 있어 모델명만으로 토픽을 확정할 수 없다. `ros2 topic list` 결과로 실제 경로를 확인한다. |
| 정확한 높이 h | **빈 판의 stud 윗면(기준 평면)에서 블록의 검출/클릭한 윗면까지의 수직 거리**다. stud 자체 높이 또는 책상부터의 전체 높이가 아니다. 판 표면에서 블록 윗면까지를 재었다면 약 5 mm의 stud 높이를 빼되 실제 높이를 다시 확인한다. 여러 블록/적층이면 각각 필요하다. |
| 검증 오차 | 사용자 미정. 우선 최대 1.5 mm로 측정하고 결과를 보고 조정한다. `--max-error-mm`는 문턱이며 성능 보장이 아니다. |
| 촬영 자세의 식별 정보 | 로봇 관절각 또는 TCP 자세와 촬영 자세 이름을 기록한다. 코드의 `view_id`는 메모이며 자세 복귀를 자동 수행하지 않는다. |

사진에 빨간 표시와 +Y 화살표가 이미 있으므로 원점으로 쓸 수 있다. 나머지 모서리도 A/B/C/D로 표시하면 반복 측정이 쉽다. 빨간 테이프를 판 밖에만 놓고 그 픽셀을 stud 중심인 것처럼 입력해서는 안 된다. 테이프 기준점을 직접 쓸 때는 그 점의 실제 X/Y와 기준 평면 높이를 측정해야 한다.

## 실행 환경

이 PC에서 확인한 기본 패키지는 Python 3, OpenCV 4.6.0, NumPy 1.26.4이며 ArUco 모듈도 있다. 추가 설치 없이 기본 이미지 기반 기능을 시험했다. ROS 2 Jazzy 경로는 `/opt/ros/jazzy`다. `capture_ros.py`는 별도로 `rclpy`, `sensor_msgs`, `cv_bridge`와 실행 중인 카메라 노드가 필요하다. 사용자가 D435i의 1280×720 컬러 영상과 CameraInfo를 저장했고 두 파일의 크기 일치를 확인했다. 실제 576개 좌표 생성은 완료했고, 0부터 센 번호와 선택 순서를 보정한 독립 검증은 최대 1.655 mm, RMSE 1.260 mm로 초기 최대 1.5 mm 기준을 조금 넘는다. 블록 위치의 현장 검증은 아직 남아 있다.

```bash
cd /home/rokey/corecode/Calibration_Tutorial/lego_calibration
python3 lego_grid.py --help
```

다른 PC에서 이미지 기반 기능만 사용할 경우 필요한 패키지는 `numpy`, `opencv-python`이다. ArUco를 사용할 경우 OpenCV 패키지를 중복 설치하지 말고 `opencv-contrib-python`을 사용한다. ROS 환경에서는 기존 OpenCV/cv_bridge 구성을 먼저 사용한다.

## 실제 작업 절차

### 1. 촬영 준비와 간격 확인

판과 로봇 촬영 자세를 정한 뒤 카메라가 완전히 정지한 상태에서 촬영한다. RGB 영상에서 판 전체가 충분한 픽셀 크기로 보이게 한다. 정면에 가까울수록 블록 옆면과 높이에 따른 오차가 줄어든다. 카메라 장착부와 TCP/관절 설정도 기록한다.

조명을 넓게 확산하고 정면 직사광을 피한다. 빈 판을 촬영하기 전에 노출/화이트밸런스가 안정될 시간을 준 뒤 가능하면 값을 고정한다. 필요하면 광원과 카메라에 편광 필터를 검토한다. 강한 반사, 그림자, 손, 자는 검출 후보를 만들 수 있으므로 촬영할 때 제거한다. 테이프는 기준 촬영과 블록 촬영 사이에 옮기지 않는다.

아래 명령은 사용자 측정값으로 계산한 **16.75 mm**를 사용한다. 이후 직접 잰 중심 간 간격이 다르면 모든 명령에서 바꾸고 새 캘리브레이션을 생성한다.

### 2. 빈 판 영상과 내부 파라미터 저장

기존 RealSense 노드를 사용한다. 실제 토픽을 먼저 찾는다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/rokey/cobot2_ws/install/setup.bash
ros2 topic list
```

원본 코드의 경로가 실제로 존재한다면 다음을 실행한다.

```bash
python3 capture_ros.py \
  --image-topic /camera/camera/color/image_raw \
  --info-topic /camera/camera/color/camera_info \
  --out captures/empty.png
```

`captures/empty.png`와 `captures/empty.intrinsics.json`이 함께 생성된다. 네임스페이스에 따라 `/camera/camera/color/...` 또는 `/.../rs_02/color/...`일 수 있다. 경로는 [RealSense ROS 2 공식 문서](https://dev.realsenseai.com/docs/ros2-wrapper/)처럼 네임스페이스/카메라 이름에 의해 달라진다. 카메라 노드가 실행되지 않았다면 설치된 드라이버의 launch 구성을 먼저 확인한다. 촬영 코드는 드라이버를 자동 실행하지 않는다.

**raw 컬러 영상과 그 영상의 CameraInfo를 사용**한다. rectified 영상의 P와 raw 영상의 K/D를 섞지 않는다. 코드가 지원하는 왜곡 모델은 OpenCV pinhole의 `plumb_bob`, `rational_polynomial`, `none`이며 fisheye/equidistant는 별도 변환이 필요하다. 이미지/CameraInfo 해상도와 frame ID가 다르면 촬영하지 않는다.

일반 USB 컬러 촬영으로 시작할 수도 있다.

```bash
python3 lego_grid.py capture --device 0 --out captures/empty.png
```

S로 저장하고 ESC로 취소한다. USB 경로는 CameraInfo를 자동 저장하지 않으므로 높이 보정에는 별도의 내부 파라미터 JSON이 필요하다. 원본의 `DEVICE_NUMBER=6`을 현재 장치 번호라고 가정하지 않는다.

### 3. A/B/C/D를 클릭하고 576개 좌표 생성

```bash
python3 lego_grid.py calibrate \
  --image captures/empty.png \
  --intrinsics captures/empty.intrinsics.json \
  --pitch-mm 16.75 \
  --view-id wrist_board_view_01 \
  --out runs/view01
```

창에 표시되는 A→B→C→D 순서로 **빈 판 모서리 stud 중심**을 클릭한다. 화면의 왼쪽 위부터 클릭하는 순서가 아니라 앞 표의 물리적 위치 순서다. U는 한 점 취소, ENTER는 저장, ESC는 취소다. 원본 픽셀 크기로 표시하며, 화면보다 큰 사진은 임의로 축소하지 말고 좌표 JSON/외부 뷰어를 사용한다.

생성 파일:

- `calibration.json`: 영상→판 변환, 내부 파라미터, 선택적 카메라 자세, 축 정의, 검증 상태.
- `empty.png`: 검출에서 사용하는 빈 판 기준 영상.
- `stud_coordinates.csv`: 576행, `row,col,x_mm,y_mm,u_px,v_px`. 로봇 측정값을 주지 않으면 base XYZ 열은 비워 둔다.
- `grid_overlay.png`: 생성 격자가 실제 stud 중심과 맞는지 확인할 영상.

`grid_overlay.png`에서 빨간 점이 판 전체의 stud 중심에 맞는지 확인한다. 4점만 사용하면 그 4점의 적합 오차는 거의 0이 될 수 있으므로 출력된 `max_fit_error_mm`만으로 실제 정확도를 판단하지 않는다. 모서리 클릭이 불명확하면 8~12개의 분산된 stud를 `collect-points`로 수집한 후 `calibrate --points 파일.json`으로 사용한다. 형식은 `pixel_xy`, `board_xy_mm`이며 예시는 `examples/`에 있다.

### 4. 사용하지 않은 점으로 독립 검증

다음은 판 중앙과 주변에 분산된 5개 stud를 **실제로 세어서** 클릭하는 명령이다. 예측 격자 점을 그대로 다시 클릭하면 독립 검증이 아니다. row는 원점에서 물리적 +Y 방향, col은 물리적 +X 방향으로 센다.

원점 stud 자체가 **row=1, col=1**이다. 따라서 row=3,col=3은 원점에서 +Y로 **2개 간격**, +X로 **2개 간격** 떨어진 stud다. 현재 영상에서는 row가 위로, col이 오른쪽으로 증가한다. 클릭 화면에는 각 점까지의 간격 수와 축 안내를 표시한다. 약 한 stud 간격씩 오차가 나면 시작 인덱스를 확인하고, 먼 모서리 두 점에서 큰 오차가 나면 row/col을 바꾸어 선택했는지 확인한다. 검증 실패 후 자동으로 기준점을 예측 격자에 맞추어 수정하지 않는다.

**원점을 0행 0열로 세려면 `collect-points --index-base 0`을 추가**한다. 이때 `--stud 3 3`은 원점에서 각 축으로 3개 간격 떨어진 stud다. 물리적 XY(mm) 계산은 선택한 번호 시작값을 반영하며, JSON에 `input_index_base`도 기록한다. 기존 `stud_coordinates.csv`의 행/열 번호와 위치 조회의 `row_continuous/col_continuous`는 여전히 1부터 시작한다. 이 값을 0부터 표시하려면 각각 1을 뺀다. XY(mm)의 원점은 항상 (0,0)이다.

```bash
python3 lego_grid.py collect-points \
  --image captures/empty.png --pitch-mm 16.75 \
  --stud 3 3 --stud 3 22 --stud 12 12 --stud 22 3 --stud 22 22 \
  --out captures/validation_points.json

python3 lego_grid.py verify \
  --calibration runs/view01/calibration.json \
  --points captures/validation_points.json \
  --max-error-mm 1.5 \
  --out runs/view01/validation.json
```

**최대 오차와 RMSE**를 보고 판단한다. 기준점을 재사용하거나 공간적으로 좁은 영역만 검증하면 코드가 거부한다. 검증 실패 시 종료 코드 2를 반환하고 저장된 검증 상태도 false로 바꾼다. 목표 오차를 만족하지 않으면 간격, 원점, 클릭 위치, 왜곡 보정, 카메라 자세를 점검한다.

빈 판 검증을 통과한 뒤, **위치를 아는 블록을 중앙과 주변 최소 5곳에 놓고 윗면 중심을 검증**한다. 2×2 블록의 시작 stud가 `(r,c)`이면 윗면 중심 예상 인덱스는 `(r+0.5,c+0.5)`이며 `collect-points --stud`에 소수 인덱스도 사용할 수 있다. 여기서는 실제 높이 h를 `--surface-height-mm h`로 입력하고 모은 JSON을 같은 `verify`에 넣는다. 여러 이미지에서 클릭한 데이터를 합칠 경우 동일 해상도·자세·높이를 유지하고 중복 없는 위치를 수집한다. 빈 판 검증만으로 블록 중심 정확도가 입증되지는 않는다.

### 5. 블록 위치 읽기

같은 촬영 자세에서 블록을 올린 영상을 저장한다.

```bash
python3 capture_ros.py \
  --image-topic /camera/camera/color/image_raw \
  --info-topic /camera/camera/color/camera_info \
  --out captures/blocks.png
```

먼저 수동 윗면 중심 클릭으로 좌표 변환이 올바른지 확인한다. **아래 명령은 높이를 모르므로 높이 보정을 생략한 초기 조회**다. 결과는 판 평면으로의 투영 위치이며 정확한 블록 위치로 아직 확정하지 않는다. 실제 높이 h를 재면 `--surface-height-mm h`를 추가한다. 사용자가 말한 stud 자체 높이 5 mm를 여기에 넣지 않는다.

```bash
python3 lego_grid.py query \
  --calibration runs/view01/calibration.json \
  --image captures/blocks.png \
  --out results/query.json
```

자동 후보 검출:

```bash
python3 lego_grid.py detect \
  --calibration runs/view01/calibration.json \
  --image captures/blocks.png \
  --mode hybrid \
  --out results/blocks01
```

`candidates.json`, `overlay.png`, `mask.png`을 저장한다. `board_xy_mm`, 소수 `row_continuous/col_continuous`, `inside_board` 등을 출력한다. `hybrid`는 영상 차이와 비초록 색을 함께 사용한다. 실제 초록 색 범위가 맞지 않으면 OpenCV HSV 범위 `--green-hue 35 90`, `--green-sat-min 45`를 조정한다. `--mode difference`는 색 제한 없이 빈 판과의 차이만 사용한다. `--threshold`는 차이 문턱, `--min-area-mm2`는 작은 후보 제거 기준이다.

**검출 결과는 후보**다. 반사/그림자/손은 오검출, 맞닿은 블록은 하나로 병합, stud가 있는 윗면은 여러 영역으로 분할될 수 있다. 비스듬히 보이는 옆면까지 한 윤곽에 포함되면 중심이 치우친다. 높이 보정은 동일 높이 평면 위의 점을 위한 것이며, 여러 높이가 섞인 윤곽을 정확한 윗면 중심으로 바꾸지는 않는다. 정확한 블록 중심·개별 객체·방향·점유 stud가 필요하면 윗면 중심 검출기/인스턴스 분할과 블록 크기 정보를 추가해야 한다. 지금은 윗면 중심 클릭을 기준 검증으로 사용한다.

## 높이와 카메라 이동

평면 H는 **기준 stud 윗면 z=0**에만 정확하다. 블록 윗면 픽셀을 H에 바로 넣으면 시선이 판 평면과 만나는 좌표가 되어, 실제 블록의 수직 투영 위치와 다를 수 있다. `--surface-height-mm`를 생략하면 코드가 `coordinate_kind=reference_plane_projection`이라고 표시한다. 이것을 정확한 블록 중심 좌표로 해석하지 않는다.

사용자의 stud 높이 약 5 mm는 판 표면과 이 기준 평면의 차이다. 판 표면을 기준으로 측정한 블록 검출 지점 높이가 `H_block`이면 필요한 보정값은 `h=H_block-H_stud`이다. 두 높이는 동일한 판 표면에서 수직으로 잰 값을 사용한다. 윗면에 추가 stud가 있으면 실제로 클릭하는 면의 높이를 사용한다.

내부 파라미터와 mm 기준점이 있으면 [OpenCV solvePnP](https://docs.opencv.org/4.12.0/d5/d1f/calib3d_solvePnP.html)로 판의 카메라 자세를 구하고, 픽셀의 시선과 높이 h 평면의 교점으로 보정한다. 높이는 카메라 쪽으로 양수다. 카메라 내부 파라미터가 없는데 높이 보정을 요청하면 코드는 거부한다. 임의로 5 mm를 빼는 방식과는 다르다.

카메라가 정면이고 높이가 H일 때 단순 평면 투영의 오차 크기는 대략 `h×r/(H-h)`다(r은 카메라 수직 투영점부터 블록까지의 거리). 예를 들어 H=600 mm, h=5 mm, r=200 mm라면 약 1.68 mm이므로 낮은 블록도 목표 오차에 영향을 줄 수 있다. 수치는 설명용이며 현재 설치의 실측값이 아니다.

**손목이 움직이면 H가 달라진다.** 로봇을 이동시킨 후에는 촬영 자세로 정확히 복귀하고 기준점 위치를 확인한다. 수동/빨간 테이프 모드는 카메라 이동을 자동 감시하지 않는다. JSON의 `view_check.status=unmonitored`가 이를 표시한다. 반복 자세 오차까지 검증하려면 복귀 후 실제 기준점/블록 측정을 반복한다. 연속 이동 중 촬영하려면 판 기준점 실시간 재검출 또는 로봇 자세를 이용한 새로운 3D 변환 흐름이 필요하다.

## 기준 마커를 사용할 경우

**빨간 종이테이프:** 현재 사용자에게 가능한 기본 방식이다. A/B/C/D 위치 표시와 수동 클릭 보조로 사용한다. 빨간 블록과 같은 색이므로 자동으로 동일성이 보장되지 않는다. 이 코드에는 빨간 테이프 자동 검출을 넣지 않았으며, 테이프만으로 자동 이동 감시가 켜지지 않는다.

**선택적 ArUco:** 자동 위치 재확인이 필요하면 판 주변에 고유 ID가 있는 흑백 마커를 분산해 붙인다. 코드가 제공하는 `make-markers`로 ID 0~3 PNG를 만들 수 있다.

```bash
python3 lego_grid.py make-markers --out markers
```

마커의 **검은 사각형 네 코너의 실제 판 X/Y(mm)**를 측정해서 `examples/marker_layout_FORMAT_ONLY.json` 형식을 채운다. 코너 순서는 회전된 화면 기준이 아니라 **마커를 정방향으로 해독했을 때 좌상→우상→우하→좌하**이며 인쇄 방향을 기록한다. 각 마커에 ID가 달라야 한다. PNG는 마커 픽셀을 제공할 뿐 인쇄의 mm 크기를 보장하지 않는다. 인쇄 후 검은 사각형을 실측한다.

**마커 표면은 빈 stud 윗면과 같은 평면이어야 한다.** 책상에 붙인 마커는 stud 윗면보다 낮으므로 그 좌표를 이 평면 코드에 바로 섞으면 오차가 생긴다. 동일 높이 받침대에 올려 측정하거나, 높이가 다른 마커용 3D 모델을 별도로 구현해야 한다. 평면 배치와 좌표가 정확하다면 다음 경로를 쓴다.

```bash
python3 lego_grid.py calibrate \
  --image captures/empty.png --intrinsics captures/empty.intrinsics.json \
  --pitch-mm 16.75 --markers captures/measured_marker_layout.json \
  --out runs/marker_view01
```

ArUco로 캘리브레이션한 결과에서는 `query/detect`마다 설정한 모든 마커를 확인한다. 가려지거나 이동 오차가 문턱을 넘으면 기존 좌표 출력을 거부한다. 이 경우 자세를 복구하거나 새 빈 판 영상으로 다시 캘리브레이션한다. 기본 수동 방식에는 이 자동 확인이 없다.

## 선택 기능: 로봇 베이스 좌표

현재 요청에는 필요하지 않다. 추후 추가하려면 동일 기준 평면의 위치를 아는 stud 최소 3개(권장 6개 이상, 넓게 분산)에 대해 측정된 robot base XYZ(mm)를 준비하고 `--robot-points`를 사용한다. 코드는 강체 변환을 적합하고 잔차를 검사한다. 서로 다른 높이의 TCP, 잘못된 TCP 오프셋, 단위가 m인 데이터는 그대로 쓰면 안 된다. 평평한 판의 높이 방향은 robot base +Z 방향으로 자동 선택하고, 크게 기울어진 판은 `normal_sign`을 명시한다. `T_base_from_board`는 오른손 좌표 변환이며 물리적 위쪽 높이 부호는 별도로 저장한다. 출력은 물체의 기하학적 점이지 로봇의 이동 목표 TCP 자세가 아니다.

## 파일 구성과 검증 상태

- `geometry.py`: 왜곡 보정, 평면 매핑, PnP/높이 보정, 선택적 로봇 강체 변환, CSV 생성.
- `lego_grid.py`: USB 촬영, 기준점 클릭/수집, 캘리브레이션, 검증, 위치 조회, 후보 검출, ArUco.
- `capture_ros.py`: 원본 RealSense ROS 구독 방식을 토픽 인자/QoS/시간 제한/CameraInfo 저장 기능으로 대체.
- `tests/test_geometry.py`: 합성 데이터로 좌표·단위·높이·검출·이동 감시·명령 전체 흐름을 검증.
- `examples/`: 형식 설명용 JSON. 실제 카메라나 판에서 측정한 값이 아니다.

```bash
python3 -m pytest -q tests
```

구현 시 합성 테스트 **20개 통과**, Python 구문 검사와 명령 도움말 확인을 완료했다. 렌즈 왜곡과 기울어진 카메라의 높이 보정, 576행 출력, 동일 색 밝기 변화 억제, 고정 빨간 표시 제외, ArUco 이동/누락 거부, 검증 실패 시 상태 철회를 시험했다. 실제 전체 빈 판 영상과 CameraInfo는 확보했다. 중심 간격은 사용자 치수로 16.75 mm를 계산했고, 정밀 치수 재확인·블록 높이 확정과 현장 좌표 검증이 남아 있어 **현재 설치의 캘리브레이션과 정확도는 아직 검증되지 않았다**. 합성 테스트 통과를 현장 mm 정확도로 해석하지 않는다.

## 홍동님 전달본

`HONGDONG_VISION_GUIDE.md`는 비전 노드 연동 가이드이며 `vision_coordinates.py`는 0 기반 번호 출력도 포함하는 변환 API다. `vision_demo_node.py`는 ROS 2 후보 좌표 발행 예제다. `build_handoff.py --out 압축경로.zip`으로 현재 코드/Markdown/실측 결과/검증 기록/체크섬을 함께 묶는다. `HANDOFF_STATUS.md`와 압축 내 `MANIFEST.json`이 패키징 당시 검증 상태를 기록한다. 현재는 검증이 남은 초안이며, 미검증 결과를 임의로 검증 완료로 표시하지 않는다.
# 현장 적용 간격 갱신 — 2026-10-08

사용자 요청으로 현재 V0/D1/D3 보정의 stud 중심 간격은 **16mm**를 적용한다(세은 담당의 외곽 stud 중심 직접교시 약 16mm 기준). 24×24 보드의 양 끝 stud 중심 간 거리는 23×16=**368mm**이다. 보드 외곽 치수가 아니다. 아래 전달 초안의 16.75mm 예시는 과거 값이며 이번 보드 작업의 입력값으로 사용하지 않는다. 촬영·원점·축은 유지하고 기존 클릭 원자료를 새 간격으로 재계산했다. TCP/그리퍼 접촉점 및 실제 RGB-D 좌표 정확도는 별도 검증 대상이다.
