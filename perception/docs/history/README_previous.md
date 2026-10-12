# Assembly RGB-D 코드 기반

> 2026-10-06 신규 실제 실행은 [perception_mvp/README.md](../../perception_mvp/README.md)의
> 패키지 내부 14개 운영 파일을 사용합니다. 루트의 기존 실행 코드는 보존본이며
> 아래 내용은 이전 단계 기록입니다. 새 실행 경로는 예시/데모를 import하지 않습니다.

2026-10-06: 팀장 검토용 다섯 callback 사례와 임시 표현 표시는
[perception_mvp/README.md](../../perception_mvp/README.md)를 참고하세요.
로컬 예시 전달을 추가했으며 실제 인식 결과와 Backend 연결은 아직 별도 작업입니다.

2026-10-05 최신 사용자 계획을 적용합니다. 기존 세 문서는 역사적 논의 자료로 보존하며,
현재 경로는 Assembly Board의 YOLO Segmentation + Depth/Grid입니다.
Supply 인식·과거 역할표·Current 직접 갱신은 이번 구현에 적용하지 않습니다.

## 이번 코드의 입출력

- `rgbd_io.py`: uint8 RGB, uint16 원본/정렬 Depth, 메타데이터 ↔ 로컬 기록 폴더.
- `capture_rgbd.py`: 담당자가 정지·사람 이탈을 확인한 카메라에서 한 프레임 기록.
  Robot 제어·촬영 신호·손 감지는 구현하지 않았습니다.
- `depth_grid.py`: boolean mask + 정렬 Depth + 보정/설정 → 보이는 표면 후보 또는 UNKNOWN.
- `saved_perception.py`: 저장 영상 + 로컬 학습 weights → 후보 계산. 출력은 항상 PARTIAL이며
  Backend Observed Schema나 채택 가능한 전체 상태가 아닙니다.

실패한 파일 읽기·카메라 timeout·미설치 dependency·잘못된 설정은 예외로 반환합니다.
실패를 빈 정상 결과로 변환하지 않습니다. 검출 0개도 빈 보드의 증거가 아닙니다.

## 실행

기존 numpy/OpenCV와 표준 라이브러리를 사용합니다. 패키지 설치·모델 다운로드는 수행하지 않았습니다.
실제 YOLO 경로에는 ultralytics와 네 클래스의 학습된 segmentation weights,
카메라 경로에는 pyrealsense2가 추가로 필요합니다. 버전/호환성은 설치 전 확인해야 합니다.

```bash
python3 -m pytest -q
python3 capture_rgbd.py --help
python3 saved_perception.py --help
```

촬영 CLI에는 출력 directory와 `--serial --scene-id --view-id --robot-pose --mode REAL`
및 `--width --height --fps --timeout-ms`를 모두 지정합니다. robot-pose는 실측 메타데이터 JSON 파일입니다.
frame·단위·회전 규약·측정 시각을 기록해야 합니다. directory가 이미 있으면 덮어쓰지 않습니다.
RGB는 `rgb.npy`, 원본 Depth는 `depth_raw.npy`, RGB 정렬 Depth는 `depth_aligned.npy`,
정보는 `metadata.json`에 저장합니다. 정렬 외 Depth 필터/홀 메우기는 사용하지 않습니다.
실패 도중 생성된 폴더는 불완전 기록일 수 있으며 load가 오류를 반환합니다.

추론 CLI에는 recording directory와 `--weights --config --calibration --detector-confidence`가 필요합니다.
동일 scene_id의 모든 View·연속 프레임은 학습/검증에서 같은 분할에 넣어야 합니다.
라벨은 보이는 부분만 instance mask로 작성하며 네 클래스는
yellow_2x2, yellow_2x3, blue_2x2, blue_2x3입니다.

## 보정과 설정: 내부 파일 형식 제안

실제 실행용 기본값은 제공하지 않습니다. tests의 숫자는 합성 시험 전용입니다.
`calibration_id`가 일치하는 설정과 보정 파일을 사용해야 합니다.
보정 JSON에는 `calibration_id`, `views`가 필요하고 views는 V0/D1~D4별
Camera→Board rigid 4×4 행렬(translation m)을 담습니다. Robot 장착 카메라는
촬영 pose와 보정 pose의 일치·유효성을 담당자가 확인해야 합니다. 자동 검사는 아직 없습니다.

camera_info.aligned는 fx/fy/cx/cy와 model을 담습니다. 계산은 왜곡 없는
rectified pinhole(model=none) 영상만 지원합니다. 실제 카메라 왜곡 모델이면
UNKNOWN으로 뭉개지 않고 오류를 반환하므로 SDK deprojection/정렬 보완이 필요합니다.

config 필수 항목:

| 항목 | 의미 |
|---|---|
| calibration_id, coordinate_rules | 보정 식별, 원점·축·높이 방향 설명 |
| point_reference | 현재 지원: visible_surface_center, 공통 블록 anchor와 다름 |
| stud_pitch_m, board_bounds_m | 실측 stud 간격, [[xmin,xmax],[ymin,ymax]] |
| top_heights_m | 보드 기준 실측 1~4층 상면 높이, 증가하는 네 값 |
| footprint_sizes_m | 클래스별 실측 두 변의 길이 |
| center_offsets_stud | 클래스별 방향 문자열 0/90의 center lattice offset [x,y] |
| min_confidence, min_valid_fraction, min_depth_pixels | 모델/Depth 시험 기준 |
| min_depth_m, max_depth_m | 허용 카메라 거리 |
| grid_tolerance_stud, size_tolerance_m | Grid 및 footprint 시험 오차 |
| height_tolerance_m, max_height_spread_m | 층 판별 오차, 표면 높이 분산 기준 |
| angle_tolerance_deg, threshold_status | 방향 오차, temporary_test 또는 validated |

상면 높이·길이는 stud 돌기와 촬영각 영향을 포함해 측정해야 합니다.
방향은 내부 Board +X 기준 장축, 2×3은 180° 대칭, 2×2는 90° 대칭입니다.
`measured_layer_index`는 높이 배열의 내부 index이며 Backend layer 번호가 아닙니다.
부분 mask·사선 옆면으로 충분한 footprint/평면을 확인할 수 없으면 UNKNOWN을 반환합니다.
이 방식은 사선 View에서 top-surface 분리 보완이 필요할 수 있습니다.

## 후속 연결

2026-10-06: 정규화 배치 기반 다중 시점 통합·충돌 검사, 이전 Backend 채택 상태 비교,
공통 Observed 구성과 주입 callback 전달을 구현했습니다. 실제 카메라와 Backend 수신 함수의 연결은 미검증입니다.
전체 보드 coverage/손·반사 판정, 학습 실행·장면 분할 도구는 아직 구현하지 않았습니다.
이전 블록을 관측 누락만으로 제거하거나 이전 채택 상태를 자동 갱신하는 코드는 없습니다.
외부 JSON·callback·Topic·ID/Step/버전은 합의 후 별도 연결해야 합니다.

## 실제 Perception 개발 — 2026-10-06 연결 계산 단위

코드는 `perception_mvp/contracts.py`, `multiview.py`, `state_tracking.py`,
`backend_adapter.py`이며 예시 값 생성 코드와 독립적입니다. 로컬 JSON 자료가 아니라
어제 작성한 저장 RGB-D 측정 함수의 결과를 입력으로 연결할 수 있습니다.

```bash
python3 -m pytest -q tests/test_rgbd.py perception_mvp/tests/test_observation.py
```

`saved_perception.process_saved_bundle` 입력:

- recordings: directory, detections, verified_regions를 가진 항목 목록.
  detections는 infer_masks가 반환하는 실제 mask/class/confidence 목록입니다.
- calibration/config: 기존 측정 입력. config에 center_to_anchor_offsets_stud를 추가합니다.
  클래스 이름→공통 방향 문자열(0/90)→[중심에서 최소 anchor까지 X/Y stud 차이] 구조입니다.
  기존 중심 기준 보정과 일치하는 실측값을 입력해야 하며 기본값은 없습니다.
- check_id/observation_seq: Backend check 및 관측 묶음 시작 순번.
- previous_accepted_blocks: Backend가 채택한 이전 배치 목록; 함수는 이를 수정/채택하지 않습니다.
- target_after: 현재 확인 대상 여섯 필드 배치. 목표는 필요한 확인 범위를 판단하는 데만 사용합니다.
- scene_stable: 실제 장면 안정 확인의 명시적 bool 입력; 파일 목록만으로 자동 판정하지 않습니다.

반환은 `(observed, diagnostics)`입니다. observed는 공통 여섯 필드이며
backend_adapter.deliver_observed에 실제 Backend callback을 주입하면 전달할 수 있습니다.
진단 필드/연결 위치는 제안이며 별도 수신 경로는 아직 미정입니다.

verified_regions는 **실제 점유 검증을 완료한 영역을 독립적으로 입력**해야 합니다.
카메라 ROI·보드 bounds·검출 0개만으로 생성하면 안 됩니다. 이 근거를 만드는 영상
coverage 모듈은 아직 없으므로 실제 장치에서 정상 OK를 자동 보장하지 않습니다.
UNKNOWN 검출이 있는 View는 확인 영역을 보수적으로 비우고 원인을 진단에 남깁니다.
다른 View의 유효 근거가 대상 footprint 전체를 확인하면 OK일 수 있습니다.

다중 View는 공통 check/순번/보정과 정적인 scene이 필요합니다. 완전히 동일한 정규화
배치는 하나로 합치고, 동일 layer의 겹친 배치나 확인된 empty/occupied 충돌은
해당 후보와 걸친 확인 영역을 제외합니다. 큰 영역 전체를 제외할 수 있는 보수적 MVP 처리입니다.
아직 연속 좌표 오차 허용범위에 따른 근접 후보 연결은 없으며 서로 다른 layer는 합치지 않습니다.

추적은 유지·추가·제거·이동 후보를 진단으로만 반환합니다. 제거 후보는 이전 블록의
같은 layer 전체 footprint가 실제 확인 영역으로 덮일 때만 생성합니다.
이동의 물리 동일성은 UNCONFIRMED이며 Backend Current를 갱신하지 않습니다.
실제 Vision 실패를 빈 정상 관측으로 바꾸지 않으며 callback 오류도 그대로 전파합니다.

검증은 합성 RGB-D→측정→공통 배치→Observed 계산과 정상/충돌/가림/실패 경로입니다.
YOLO 패키지·weights·실측 보정·실제 장치·Backend 소비·HMI 통합은 미검증입니다.

API 근거: [YOLO segmentation](https://docs.ultralytics.com/tasks/segment/),
[YOLO prediction](https://docs.ultralytics.com/modes/predict/),
[RealSense alignment example](https://github.com/realsenseai/librealsense/blob/master/wrappers/python/examples/align-depth2color.py).
