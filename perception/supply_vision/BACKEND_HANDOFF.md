# B ↔ D Backend 인계 초안 — RGB only

사용자 요청에 따른 내부 초안이며 기존 공통 Schema/ROS 타입을 변경하거나 계약 확정을 뜻하지 않는다.
서비스 이름·타입·필드·timeout·취소·mode는 D와 합의해야 한다. 실제 Service 서버/클라이언트는 미연결이다.

## D → B

| 정보 | 현재 로컬 필드/의미 |
|---|---|
| 요청/Step | request_id, step_id |
| 필요한 블록 | brick_type, color |
| 관측 자세·설정 | observation_id, config_id |
| 정지와 시간 창 | stopped, not_before_ns, expires_at_ns |
| 취소/닫힘/모드 | 실제 연결에서 합의·구현 필요, 누락을 REAL로 해석 금지 |

D는 관측 이동·정지·현재 Step·요청 생명주기를 소유한다.
촬영 당시 로봇 자세와 카메라–로봇 보정값은 D가 변환을 맡는다면 D 내부에서 유지한다.
B는 실제 슬롯 ROI와 grasp_edge_pair를 D와 대응 확인한다.

## B → D

현재 로컬 출력은 scope=LOCAL_ONLY다. 공통 메시지로 자동 송신하지 않는다.
request_id, step_id, observation_id, config_id, calibration_id, frame_stamp_ns,
coordinate_frame=rgb_image, units=pixel, status=CANDIDATES/HOLD를 반환한다.
각 후보는 brick_type, color, slot, confidence와 geometry를 포함한다.
geometry에는 corners_uv(네 모서리), grasp_midpoints_uv(두 변 중점), center_uv,
grasp_edge_pair, method가 있다. box는 검출 근거이며 집기 중심이 아니다.
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
빨강 2x1은 Vision에 포함하되 D 기존 네 공급열에 없는 지원 추가를 합의해야 한다.
최종 검증: 실제 RGB 중심 오차, D 변환 오차, 파지 시 기울어짐/미끄러짐을 별도로 기록한다.
