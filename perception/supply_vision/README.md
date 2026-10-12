# 서플라이 RGB 중심 후보 인식 — RealSense

현재 사용자 결정: 로봇 장착 RealSense가 서플라이를 수직 관측하며 정지한 뒤 RGB만 사용한다.
OpenCV HSV로 슬롯 내 노랑·파랑·빨강 후보를 먼저 구분하고, 후보 영역의 원본 RGB를
일반 YOLO Detection에 넣어 노랑/파랑 2x2·2x3, 빨강 2x1 종류를 구분한다. OBB/Depth는 사용하지 않는다.
고정 슬롯 좌표만으로 파지 중심 오차가 발생하므로 실제 윗면 외곽과 파지할 두 변의 중점을 추정한다.
기존 assembly 모듈은 수정하지 않는다. Robot 명령·TCP·파지 높이·좌표 변환을 생성하지 않는다.

## 구성과 실제 구현 범위

- main.py: RealSense ROS RGB Topic 수신, OpenCV 색상 후보 추출 → 원본 RGB crop의 일반 detection CPU 추론,
  기존 brick_type/color/slot(1~6) 대응, 요청 후 프레임과 유효 시간 검사, 결과 JSON/진단 화면.
- top_surface.py: 검출 주변 색상 외곽의 단일 볼록 사각형 후보 추출.
  사각형에 단위 직사각형을 투영하여 원근을 반영한 중심과 두 변의 중점을 구한다.
  minAreaRect로 가짜 모서리를 만들거나 YOLO 박스 중심을 파지 중심으로 반환하지 않는다.
- config_TEMPLATE.json: 실제 슬롯 ROI·해상도·관측 ID·설정 ID·보정 ID·파지할 변·시험 임계값 준비 양식.
- request_TEMPLATE.json: D 요청 의미를 확인할 로컬 입력 양식.
- BACKEND_HANDOFF.md: D 전달/수신 항목·책임·미확정 연결 계약.

OpenCV 후보가 없으면 YOLO를 실행하지 않는다. 모델 입력에는 마스크/박스/글자를 그리지 않는다.
후보 crop의 검출 좌표를 원본 영상 좌표로 복원한 뒤 슬롯/중심을 처리한다.
HSV와 YOLO 색상이 다르면 UNKNOWN으로 보류한다. 후보끼리의 중복을 자동 병합하지 않으며
복수 검출은 보류한다. 후보 영역은 슬롯 ROI와 영상 해상도 안에서 잘라낸다.
색상 범위가 블록을 놓치면 YOLO도 해당 대상을 볼 수 없으므로 HSV 누락률을 먼저 검증한다.
학습 라벨은 오버레이 없는 원본 RGB에 일반 박스로 작성하며, 실제 후보 crop 입력에서도 별도 평가한다.

색상 외곽이 실제 윗면이라고 보장되지 않는다. 측면·반사·가림으로 잘못된 사각형이 나올 수 있다.
출력 CENTER_CANDIDATE는 실측 검증 전 진단 후보이며 파지 가능/안전/실행 허가가 아니다.
모서리 실패·복수 색상 영역·경계 잘림·미검출·복수 검출·잘못된 종류는 UNKNOWN/HOLD다.
미검출을 EMPTY로 바꾸지 않는다. temporal 안정화/손 검출/자동 재시도는 추가하지 않았다.

## 준비 파일

템플릿을 별도 실제 파일로 복사하고 null/빈 HSV 범위를 실측/검증 값으로 채운다.
실제 camera 해상도, 각 슬롯의 비중첩 ROI, D의 종류/색상/slot 대응이 필요하다.
슬롯별 brick_type은 2x2x1·2x3x1·2x1x1이며 red 2x1은 D 기존 공급 계약에 없으므로 협의 필요하다.
같은 종류의 서로 다른 슬롯은 slot 번호로 구분한다. 아직 실측 ROI/보정/모델은 이 변경에서 만들지 않았다.

corners_uv는 영상 좌상단에 가장 가까운(sum u+v 최소) 모서리부터 둘레 순서다.
grasp_edge_pair=0은 변 0→1과 2→3, 1은 변 1→2와 3→0을 뜻한다.
화면 방향과 실제 그리퍼 닫힘 방향의 대응을 B/D가 확인한다. 특히 정사각 블록은 방향을 추정하지 않는다.
HSV 값은 OpenCV H=0..179, S/V=0..255이고 빨강은 필요시 두 구간을 지정한다.
minimum_area는 pixel², approx_fraction은 contour 둘레 비율(<0.1), minimum_fill은 (0,1]이다.
모든 임계값은 실제 원본 이미지에서 중심 오차를 검증한 뒤 지정하며 임의 운영 기본값은 없다.

request의 not_before_ns/expires_at_ns는 RGB header와 같은 ROS clock의 정수 nanoseconds다.
D는 관측 정지 후 시작 시각을 제공하며 stopped=true는 시험 확인값이지 안전 인터록이 아니다.
ROS 시각과 벽시계 시각을 섞지 않는다. 모델 로딩 시간을 고려해 실제 유효 기간을 설정한다.
closed/중복 요청 취소 관리는 실제 Service 연결부에서 구현해야 하며 로컬 JSON 입력은 이를 대체하지 않는다.

## 실행

RealSense ROS 노드를 유지하고 Ubuntu 로컬 터미널에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
cd /home/roh/C-2/perception
python3 -m supply_vision.main --config /실제/supply_config.json --request /실제/request.json --weights /실제/detection/best.pt --output /새로운/result.json --timeout 10
```

경로와 timeout은 실제 값으로 지정한다. 요청 후 첫 유효 프레임을 받아 한 번 측정한다.
추론 종료 시 유효 기간이 지나면 결과를 출력하지 않고 실패한다.
새 JSON만 저장하고 덮어쓰지 않는다. 화면은 AUTOSIZE로 후보 외곽·중점만 표시한다.
아무 키로 화면을 닫는다. 창은 정지 영상이며 연속 live/실제 Backend 응답 서버가 아니다.
카메라/모델/출력 오류는 예외로 종료하며 자동 재시작하지 않는다.
기존 segmentation 모델은 거부한다. 새 일반 detection 학습·사람 검수 라벨이 필요하다.
학습용 원본 RGB와 일반 박스 라벨은 윗면 중심의 정답 데이터가 아니다.
중심 측정 정확도는 별도의 사람 확인 모서리/중점과 비교한다.

## 검증

```bash
cd /home/roh/C-2
PYTHONPATH=perception:perception/legacy python3 -m pytest perception/supply_vision/tests perception/perception_mvp/tests perception/legacy/tests -q
```

합성 영상/대체 검출은 알고리즘·실패 경로 검증이다. 실제 모델·RealSense·D Service·Robot 파지는 미검증이다.
Ultralytics API: https://docs.ultralytics.com/modes/predict/
