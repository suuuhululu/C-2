# 서플라이 RGB-only YOLO segmentation 중심·방향 후보

2026-10-13 사용자 채택: OpenCV 색상 후보 → YOLO 윗면 segmentation → 중심·방향 후보.
RealSense가 서플라이 수직 관측 자세에서 정지한 뒤 RGB만 사용한다. Depth는 사용하지 않는다.
기존 assembly 모듈/공통 ROS·Schema·Robot 명령은 수정하지 않는다.

## 구현

main.py는 슬롯 ROI 내 HSV 노랑/파랑/빨강 후보를 먼저 찾고 색상 후보를 확인한 뒤 원본 전체 BGR 영상을 모델에 입력한다.
색상 후보가 없으면 YOLO를 호출하지 않는다. 색상 마스크를 모델 입력에 덧칠하지 않는다.
로컬 task=segment .pt와 정확한 다섯 클래스가 필요하다:
yellow_2x2, yellow_2x3, blue_2x2, blue_2x3, red_2x1.
detect/obb 모델은 거부하며 자동 다운로드하지 않는다. 모델 경로는 config의 `weights`로 지정한다(상대 경로는 config 파일 위치 기준, 절대 경로 가능). `--weights`를 주면 config 값 대신 사용한다. 둘 다 없으면 실패한다.
현재 모델: `perception/models/supply_top_yolo26s_seg_20261013/best.pt` (YOLO26s-seg, Colab T4 60 epoch,
SHA256 `4a55859c59fc77eb32f8270e7d0b123809efc6589b6f337729148f2165c5d486`). 학습 6장/검증 2장이며 실물 파지 검증은 아니다.
retina_masks=True로 원본 전체 영상 크기의 인스턴스 마스크를 받는다. HSV 후보와 겹친 검출만 사용한다.

seg_geometry.py는 윗면 마스크 외곽을 네 꼭짓점으로 근사한다.
중심은 네 꼭짓점 평균/검출 박스 중심이 아니라 윗면 두 대각선 교점이다.
두 파지 변 중점은 같은 사각형의 원근 변환으로 계산한다.
잘림·분리된 큰 영역·네 모서리 추정 실패·외곽 적합도 부족은 UNKNOWN/HOLD다.
누락된 모서리를 회전 사각형으로 대신 만들지 않는다. 모델이 옆면까지 잘못 예측하면
이 검사만으로 실제 윗면임을 보장하지 못하므로 실제 중심 오차 검증이 필요하다.

orientation_deg는 원근 변환된 긴 축과 영상 +u축 사이 시계방향 degree다(v 아래 방향).
직사각형 orientation_period_deg=180, 2x2=90 및 orientation_basis=square_equivalent_axes다.
corners_uv는 둘레 순서이며 첫 변은 추정 긴 변이다.
grasp_edge_pair=0은 긴 변 두 개, 1은 짧은 변 두 개의 중점이다.
정사각형은 90도 동등하며 실제 그리퍼 접근 방향은 D와 대응해야 한다.
center_uv, corners_uv, grasp_midpoints_uv, orientation_deg는 영상 후보이고 Robot 명령이 아니다.

UNKNOWN: 미검출/낮은 신뢰도/다중 검출/슬롯 침범/HSV-모델 색상 불일치/다른 종류/무효 외곽.
성공도 CENTER_CANDIDATE/LOCAL_ONLY이며 실행 허가가 아니다. 미검출은 EMPTY 증거가 아니다.
HSV 누락률과 원본 전체 영상의 인식 성능은 별도로 검증해야 한다.
이전 OBB 코드와 학습 준비 스크립트는 저장소에서 제외하고 로컬 백업으로 보존한다.
top_surface.py의 quad_geometry/validate_surface는 현재 segmentation 경로에서 사용한다.

## 입력 파일

config_TEMPLATE.json의 null을 실제 측정값으로 채운 별도 config를 사용한다.
image_size, 비중첩 슬롯 ROI, D 구조 brick_type/color/slot 1~6, grasp_edge_pair,
config_id/view_id/calibration_id, candidate_confidence/confidence를 제공한다.
surface에는 minimum_area(pixel²), hsv_ranges, approx_fraction(외곽 근사 허용 비율),
minimum_fill(마스크와 사각형 면적 적합도)을 실제 영상으로 검증하여 제공한다.
HSV는 H 0..179/S,V 0..255이며 빨강은 필요시 두 hue 구간이다.
빨강은 D brick_type=1x2x1을 모델 클래스 red_2x1에 명시적으로 매핑한다.
이전 2x1x1 요청은 받지 않는다.

request_TEMPLATE.json은 로컬 시험 요청이다. request_id/step_id, 요청 종류·색상,
관측/설정 ID, 정지 확인, 같은 ROS clock의 not_before_ns/expires_at_ns를 제공한다.
요청 후 수신한 첫 유효 프레임만 측정하며 추론 후 만료를 다시 확인한다.
실제 닫힘/취소/중복 요청·모드와 Service 타입은 D와 합의·연결해야 한다.

## 실행

```bash
source /opt/ros/jazzy/setup.bash
cd /home/roh/C-2/perception
python3 -m supply_vision.main --config /실제/supply_config.json --request /실제/request.json --output /새로운/result.json --timeout 10
```

실제 값으로 바꾼다. 새 JSON만 저장하고 화면에 윗면 외곽·대각선 십자·중심/변 중점을 표시한다.
한 번의 정지 영상이며 아무 키로 종료한다. 실제 Backend 송신/Robot 실행 서버가 아니다.
카메라 실패/만료/모델 오류는 실패로 종료한다. 자동 재시작/재파지는 없다.

## 라벨·검증

Roboflow instance segmentation에서 옆면을 제외한 윗면 polygon을 라벨링한다.
원본 RGB와 라벨을 보존한다. 회전·조명·빈 슬롯이 다른 장면과 별도 촬영 세션으로 검증한다.
영상 중심/각도 오차, 픽셀→로봇 변환 오차, 실제 파지 기울어짐은 별도 검증한다.

```bash
cd /home/roh/C-2
PYTHONPATH=perception:perception/legacy python3 -m pytest perception/supply_vision/tests perception/perception_mvp/tests perception/legacy/tests -q
```

합성/대체 추론 검사는 실제 모델/장치 검증이 아니다.
API: https://docs.ultralytics.com/tasks/segment/

## 요청 연결·저장 RGB 시험 (2026-10-12)

request_session.py는 submit/observe/cancel/expire 호출과 요청 생명주기를 구현한다.
request JSON에는 mode=TEST 또는 REAL을 명시한다. 누락을 REAL로 처리하지 않는다.
라이브 단발 실행도 이 연결부를 사용한다. 자세한 인계는 BACKEND_HANDOFF.md를 따른다.
실제 ROS2 Service 타입은 아직 정하지 않았다는 사용자 확인에 따라 transport 서버는 만들지 않았다.

카메라·ROS 없이 저장된 RGB로 실제 segmentation 모델을 평가하려면:

```bash
cd /home/roh/C-2/perception
python3 -m supply_vision.replay --image /실제/원본RGB.png --config /실제/supply_config.json --request /실제/test_request.json --frame-stamp-ns 123456 --output /새로운/replay_result.json
```

숫자·경로는 예시다. 실제 기록의 시각과 그 시각을 포함하는 TEST 요청 시간 창을 제공한다.
replay는 mode=TEST만 허용하며 source=SAVED_RGB_REPLAY로 구분한다. Robot 이동/ROS 송신은 없다.
이 경로는 request lifecycle을 실제 실시간으로 진행하는 시험이 아니라 저장 영상의 인식 평가다.
학습 완료만으로 실측 슬롯/HSV·D 보정·실제 집기 연결이 준비됐다는 뜻은 아니다.


## 2026-10-13 D 회신 반영

- 관측 필드는 요청/config/응답 모두 view_id=SUPPLY_VIEW로 통일한다. observation_id는 사용하지 않는다.
- D 타입은 노랑·파랑 2x2x1/2x3x1, 빨강 1x2x1이다. 모델 라벨 red_2x1은 유지한다.
- 슬롯은 종류·색상별 1~6이며 slot_id는 yellow_2x2x1_01과 같은 형식이다.
  config의 color/brick_type/slot으로 식별값을 생성한다. 요청의 slot_id는 D 예약 슬롯을 명시한다.
  요청 종류·색상과 config에 일치하지 않으면 거부하며 다른 슬롯 후보로 대체하지 않는다.
  이 예약 필드는 로컬 연결 초안에 반영한 것으로 실제 ROS Service 합의를 뜻하지 않는다.
- B는 rgb_image/pixel의 center_uv, corners_uv, grasp_midpoints_uv, grasp_edge_pair 및 식별 정보를 전달한다.
  D가 기존 파지 교시점에 보정을 반영한다. 영상 각도는 참고값이며 로봇 자세 명령이 아니다.
- 관측 후보는 사용자 제공 posx([-442.7,-40,373,3,178,3]),
  posj([184.5,21.6,34,0,126,184])다. 이동·도착·정지 검증과 코드 연결은 D 담당이다.
- D 회신 기준 TCP=GripperDA_v4, Tool=ToolWeight0, Robot Base XYZ(mm)/ZYZ(deg).
  교시점은 실제 집기 기준이고 SUPPLY_VIEW는 촬영 기준이다. 기존 높이 보정은 중복 적용하지 않는다.
- 아직 필요한 자료: SUPPLY_VIEW 실제 영상의 슬롯 번호/ROI 대응, 보정값·calibration_id·허용 오차,
  Service 이름/타입·timeout·취소 연결. mode=TEST/REAL은 필수다.


### 슬롯 영상 방향 및 2026-10-13 시험

사용자 확인: 오른쪽부터 1~6, 세로줄 하나가 같은 번호이며 모든 종류에 동일 적용.
기존 보드 ROI는 recordings/supply_board_roi/20261012T002844481743Z/supply_roi.json을 보존한다.
저장 영상 기준 노랑·파랑 4개 행의 개별 슬롯 ROI를 시험 설정에 연결했다.
빨강은 사진상 두 행이며 D 교시점의 대상 행은 로봇팀 확인 필요로 제외했다.
전체 영상 학습 모델에 작은 블록 crop을 넣으면 미검출하여, OpenCV 색상 선행 뒤 전체 원본 영상으로 추론하고 색상 후보와 검출을 대응하도록 수정했다.
픽셀 시험 설정은 calibration_id=UNMEASURED_PIXEL_REPLAY_ONLY이며 실제 로봇 보정/집기용 설정이 아니다.


2026-10-13 사용자 범위 확인: 현재 Step의 종류·색상 및 D 예약 slot_id 하나만 HSV 후보 확인·중심/파지 방향 계산·응답한다. YOLO는 학습 영상 문맥을 유지하기 위해 전체 원본 영상에서 추론하지만 다른 슬롯은 중심 계산/반환하지 않는다. slots도 요청 슬롯 하나의 진단이다. 다른 슬롯의 중복은 결과에 영향이 없으며, 요청 슬롯 자체의 서로 다른 복수 검출은 여전히 UNKNOWN/HOLD로 남긴다.
