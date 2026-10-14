# B ↔ D 서플라이 비전 계약 초안 (2026-10-13)

> **초안이다. 합의·구현·검증된 계약이 아니다.** 아래 "제안"은 B의 제안이며 D 확인 전에는 확정하지 않는다.
> 기존 공통 Schema/ROS 타입/Robot 명령은 바꾸지 않는다. 확정은 D와 같이 한다.

## 1. 이미 D 회신으로 정해진 것 (README/BACKEND_HANDOFF 기준)

| 항목 | 값 |
|---|---|
| 관측 ID | `view_id="SUPPLY_VIEW"` (`observation_id` 사용 안 함) |
| D 블록 타입 | 노랑·파랑 `2x2x1`, `2x3x1` / 빨강 `1x2x1` (모델 라벨 `red_2x1`로 명시 매핑) |
| 슬롯 | 종류·색상별 1~6, 영상 **오른쪽부터** 번호, 세로줄은 모든 종류 동일 번호 |
| `slot_id` | `{color}_{brick_type}_{slot:02d}` 예: `blue_2x3x1_01` |
| 좌표 | B는 `rgb_image` / `pixel` 값만 반환. Robot 명령·자세 아님 |
| 로봇 기준 | TCP=GripperDA_v4, Tool=ToolWeight0, Base XYZ(mm)/ZYZ(deg), 기존 높이 보정 중복 적용 안 함 |
| 관측 후보 | `posx([-442.7,-40,373,3,178,3])`, `posj([184.5,21.6,34,0,126,184])` (이동·정지 확인은 D) |
| 책임 | D: 이동·정지·요청 수명주기·파지 보정·후보 선택 / B: 영상 측정값 |

## 2. D와 같이 정해야 하는 것 (미합의)

각 항목에 B의 제안(권장)을 적었다. D가 수락/수정한다.

| # | 항목 | 현재 상태 | B 제안 | D 답변 |
|---|---|---|---|---|
| 1 | ROS2 인터페이스 종류와 이름 | 미정, 로컬 Python 호출만 있음 | 요청 1건 = 응답 1건이므로 **Service**. 취소가 필요하면 별도 cancel Service. (취소·진행 중 상태가 더 중요하면 Action으로 전환) | |
| 2 | 요청 필드 | `request_id, step_id, brick_type, color, slot_id, view_id, config_id, stopped, not_before_ns, expires_at_ns, mode` | 현재 필드 유지. `mode`는 `TEST`/`REAL` 필수, 누락 시 거부 | |
| 3 | 응답 필드 | `status(CANDIDATES/HOLD), reason, request_id, slot_id, calibration_id, frame_stamp_ns, candidates[geometry]` | 현재 필드 유지. HOLD `reason` 코드 목록을 D와 공유(아래 §3) | |
| 4 | `calibration_id` | 시험값 `UNMEASURED_PIXEL_REPLAY_ONLY`(실사용 불가) | 보정 담당이 부여한 ID를 config에 넣고 응답에 그대로 에코. 담당·버전 규칙 필요 | |
| 5 | 허용 오차 | 없음 | 중심 오차(px 또는 mm)와 각도 오차 허용값을 D가 제시. 이 값으로 B 중심 검증 합격선 설정 | |
| 6 | timeout | 요청에 `expires_at_ns`로 전달, 실측 없음 | 촬영+추론 실측 후(CPU 추론 시간 측정 필요) D가 `expires_at_ns` 여유를 설정 | |
| 7 | 취소/닫힘 | 로컬 `cancel/expire` 구현, transport 미연결 | 취소 시 결과 미반환. 닫힌 `request_id` 재사용 시 `duplicate_or_closed_request` | |
| 8 | 오류 응답 매핑 | 예외로 종료 | 모델/카메라 오류는 `status=ERROR`(HOLD와 구분)로 반환할지 D와 결정 | |
| 9 | 시계 | 요청·RGB header 모두 같은 ROS clock | 같은 clock 사용 확인 | |
| 10 | 스레드 | 추론이 길어 D STOP 처리를 막을 수 있음 | adapter에서 worker/executor로 분리, 담당자 지정 | |
| 11 | 빨강 줄 | 사진상 두 줄. D 교시 슬롯 1~6이 어느 줄인지 **로봇팀 확인 필요** | 답 전까지 빨강 config 연결 안 함 | |
| 12 | 파지 방향 | `grasp_edge_pair` 0=긴 변 / 1=짧은 변 | 타입별 값을 D 파지 교시점과 대조해 표로 확정(2x2는 90° 등가라 접근 방향은 D 기준) | |
| 13 | 영상 각도 | 참고값 | D는 각도를 로봇 회전값으로 직접 쓰지 않음(확인) | |

## 3. B가 반환하는 HOLD 사유 (현재 코드 기준)

`no_detection`, `multiple_detections`, `detection_crosses_slot`, `low_confidence`,
`opencv_yolo_color_mismatch`, `unexpected_class`, `surface_clipped`,
`missing_or_ambiguous_surface`, `surface_not_four_corners`, `surface_outline_unreliable`,
`invalid_mask_contour`. 미검출은 빈 슬롯(EMPTY) 증거가 아니다.

## 4. 응답 예 (구조 설명용, 값은 예시)

```json
{
  "scope": "LOCAL_ONLY",
  "mode": "TEST",
  "request_id": "req_001", "step_id": "step_01",
  "view_id": "SUPPLY_VIEW", "slot_id": "blue_2x3x1_01",
  "config_id": "…", "calibration_id": "…",
  "frame_stamp_ns": 1760000000000000000,
  "coordinate_frame": "rgb_image", "units": "pixel",
  "status": "CANDIDATES",
  "candidates": [{
    "slot_id": "blue_2x3x1_01", "confidence": 0.83,
    "geometry": {
      "center_uv": [0.0, 0.0],
      "corners_uv": [[0,0],[0,0],[0,0],[0,0]],
      "grasp_midpoints_uv": [[0,0],[0,0]],
      "grasp_edge_pair": 0,
      "orientation_deg": 0.0, "orientation_period_deg": 180
    }
  }]
}
```

HOLD 예: `"status": "HOLD"`, `slots[0].reason` 에 사유 코드.

## 5. 다음 단계

1. D에게 §2 표 전달 → 답변 수신.
2. 합의된 값으로 request/response Fixture(성공·HOLD·취소·만료) 작성.
3. 합의 후에만 Service 타입 정의와 서버 구현.

## 6. B 쪽 현재 한계 (D에게 알릴 것)

- 시험은 저장된 RGB 1장 기준이며 실카메라·D 연결·실제 파지는 미검증.
- 학습 6장/검증 2장이라 종류 오분류(예: 2x2↔2x3)와 모서리 추정 실패(빨강)가 확인됐다. 이런 경우 B는 값을 만들지 않고 HOLD를 반환한다.
