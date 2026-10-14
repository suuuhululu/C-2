# B ↔ D Backend 인계 초안 — RGB only

사용자 요청에 따른 내부 초안이며 기존 공통 Schema/ROS 타입을 변경하거나 계약 확정을 뜻하지 않는다.
서비스 이름·타입·필드·timeout·취소·mode는 D와 합의해야 한다. 실제 Service 서버/클라이언트는 미연결이다.

## D → B

| 정보 | 현재 로컬 필드/의미 |
|---|---|
| 요청/Step | request_id, step_id |
| 필요한 블록 | brick_type, color |
| 관측 자세·설정 | view_id, config_id |
| 정지와 시간 창 | stopped, not_before_ns, expires_at_ns |
| 취소/닫힘/모드 | 실제 연결에서 합의·구현 필요, 누락을 REAL로 해석 금지 |

D는 관측 이동·정지·현재 Step·요청 생명주기를 소유한다.
촬영 당시 로봇 자세와 카메라–로봇 보정값은 D가 변환을 맡는다면 D 내부에서 유지한다.
B는 실제 슬롯 ROI와 grasp_edge_pair를 D와 대응 확인한다.

## B → D

현재 로컬 출력은 scope=LOCAL_ONLY다. 공통 메시지로 자동 송신하지 않는다.
request_id, step_id, view_id, config_id, calibration_id, frame_stamp_ns,
coordinate_frame=rgb_image, units=pixel, status=CANDIDATES/HOLD를 반환한다.
각 후보는 brick_type, color, slot, confidence와 geometry를 포함한다.
geometry에는 corners_uv(네 모서리), grasp_midpoints_uv(두 변 중점), center_uv,
grasp_edge_pair, orientation_deg, orientation_period_deg, orientation_basis,
angle_convention, method가 있다. center_uv는 YOLO 윗면 마스크에서 추정한 네 모서리의 대각선 교점이다.
각도는 영상 +u 기준 시계방향 degree이며 직사각형 긴 축은 180도, 2x2 축은 90도 동등하다.
마스크 근사 모서리는 둘레 순서이고 첫 변이 추정 긴 변이다. mask_contour_uv는 원본 마스크 외곽 근거다.
D는 이 각도를 로봇 회전값으로 직접 쓰지 않고 보정·파지 방향 기준을 적용한다. box는 검출 근거이며 집기 중심이 아니다.
slots에는 UNKNOWN 이유를 남겨 미검출/불확실을 빈 슬롯과 구분한다.

## D의 실제 집기 연결에 필요한 별도 합의

픽셀 좌표만으로 로봇을 움직일 수 없다. D는 실제 블록 윗면 높이와 내부/외부 보정을
반영해 픽셀을 로봇 목표로 변환한다. 보드 표면 평면 보정을 윗면에 무조건 적용하지 않는다.
왜곡 처리를 포함한 픽셀 기준과 calibration_id 대응을 확인해야 한다.
카메라 이동 후 같은 보정을 사용할 수 있는지 촬영 당시 자세와 확인한다.
그리퍼 TCP/닫힘 방향/파지 높이/경로는 D가 장치에서 검증하며 B는 생성하지 않는다.
후보 중 하나를 선택하고 최신 요청/버전/취소를 확인하는 것은 D 책임이다.
종류를 정하는 것은 C Design → A 채택 Plan의 현재 Step이고 D가 B 요청을 연결한다.

필요 자료: D 공급열·slot 배치표, 새 서플라이 수직 관측 자세, 파지 방향,
보정 담당/버전/허용 중심 오차, 실제 서비스 요청·성공·보류·취소 Fixture.
빨강 D 타입 1x2x1은 모델 red_2x1에 매핑한다. D 회신상 빨강 공급 교시 자료도 존재한다.
최종 검증: 실제 RGB 중심 오차, D 변환 오차, 파지 시 기울어짐/미끄러짐을 별도로 기록한다.

## 구현된 Python 호출 연결부 (2026-10-12)

request_session.SupplyRequestSession(model, config, now_ns)를 D 연결 adapter에서 생성한다.
now_ns는 RGB header와 동일한 ROS clock의 현재 nanoseconds를 반환하는 함수다.

```python
from supply_vision.main import load_model
from supply_vision.request_session import SupplyRequestSession

session = SupplyRequestSession(
    load_model(segmentation_weights), measured_config,
    lambda: ros_node.get_clock().now().nanoseconds,
)
accepted = session.submit(request)  # mode는 TEST 또는 REAL 명시
result = session.observe(request['request_id'], original_bgr, frame_stamp_ns)
# result는 D adapter가 현재 요청과 연결해 소비한다. Robot 명령은 아니다.
# session.cancel(request_id): 요청 취소
# session.expire(request_id): D/transport timer가 유효 기간 만료 처리
```

submit은 검증된 단일 활성 요청만 받으며 request_id는 session 생존 동안 재사용하지 않는다.
observe는 요청 이후·현재 시각 이하의 프레임만 받는다. 성공/HOLD 결과는 한 번 반환한 뒤 요청을 닫는다.
추론 중 cancel/expire되거나 완료 시 만료되면 결과를 반환하지 않는다.
모델 오류는 원래 예외로 전달하고 요청을 닫는다. 잘못된 시각 프레임은 요청을 닫지 않아
새 유효 프레임을 명시적으로 공급할 수 있다. 내부 자동 재시도는 없다.
복사한 config를 session 동안 고정한다. 새 config는 실행을 멈추고 새 session에서 사용한다.

ROS2 Service 타입/서버·클라이언트·오류 응답 매핑·스레드/executor 배치는 아직 미합의다.
영상 callback에서 긴 추론으로 D STOP 처리를 막지 않도록 실제 adapter가 worker/executor를 연결해야 한다.
지정 인식만 처리하며 후보 선택·로봇 실행·픽셀/각도 변환은 D의 별도 구현이다.
REAL 모드도 scope=LOCAL_ONLY를 유지한다. 이는 입력 출처 모드이며 실행권한이 아니다.


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
