# 홍동 B — 최종 MVP 발표 준비

작성일: 2026-10-11 / 담당: 홍동 / 검토 필요 초안  
기준 소스: `work/hongdong-vision-round1`, `8f75e5a15bfc0fd51b56f83e60d73ea7eab76f6d`  
작성 범위: 실제 로컬 코드·설정·저장 보고서·개발 기록 확인. 장치 이동·운영 설정 변경 없음.

> 최종 목표는 Robot 직접 결착이다. 전달판 전달·사람 조립 관측 기록을 직접 결착 성공으로 해석하지 않는다. 최신 10/8 및 10/11 계약에 따라 **B는 Current·revision·Expected·공간 비교**, **D는 실행·진행·최종 종료·HMI/DB**를 담당한다. 아래 시험 개수는 인식 정확도·물리 안전·팀 전체 완료율이 아니다.

## 1. 팀장용 한 장 요약

| 항목 | 요약 |
|---|---|
| 최종 MVP 기여 | 실제 RGB-D에서 조립 상태·확인 가능한 영역을 보고하고 목표와 비교하여 D가 진행/보류·최종 종료를 판단할 근거 제공 |
| 핵심 기술 | OpenCV HSV 색상 후보, YOLO instance segmentation, 보정 기반 Depth/Grid, 다중 View·확인 이력, 요청별 검사/취소 |
| 지금 설명·재현 가능 | 저장 보드 보정 결과, 로컬 코드 검사, B 검사 결과 봉투. 모델 파일·로컬 ROS 뷰어 존재 |
| 실시간 시연 전제 | 실제 ROS 수신·모델·View별 보정·손 ROI/임계값·실측 층 높이 설정 및 D/Controller 결선 |
| 가장 큰 미검증 | 실제 자동 사이클·5층 전체 판별·최종 물리 결착·HMI/DB 전체 실시간 연결 |
| 발표 전 필수 | 현재 코드 테스트·자료 출처 확인, 시연 설정 점검, 실제 연결 범위 협의, 별도 정답을 둔 짧은 장치 시연 |
| 협업 요청 | D 요청/취소/결과 enqueue, Controller 실제 정지·안전 신호, 같은 Design/Plan 공유 및 접촉 근거 |

현재 공통 소프트웨어 범위: 노랑/파랑 2×2·2×3, 빨강 2점 `1x2x1`, 24×24, 정수 layer 1~5, 실행 후보 1~40블록. 실제 인식·Robot 직접 결착 가능 범위는 별도다.

## 2. 담당 범위·입출력

| 기능 | 입력 | 핵심 처리 | 출력 | 상대/책임 경계 | 상태 |
|---|---|---|---|---|---|
| 영상 수신/저장 | ROS RGB·raw/aligned Depth·CameraInfo | 시각 정합·형식 검사·원본 저장 | RGB-D·metadata | Camera; 노드 존재만으로 수신 성공 아님 | 코드 구현 |
| 색상/종류 | RGB·학습 모델 | HSV 후보→원본 crop YOLO→원본 좌표 mask | 색상·종류·instance mask | B; confidence는 실제 정답 확률 아님 | 로컬 통합 화면 구현 |
| Grid/층 | mask·Depth·보정·실측 높이 | 역투영·좌표 변환·기하/품질 검사 | 배치 후보/UNKNOWN | B; 물리 체결 증거 아님 | 코드·저장 데이터 진단 |
| 관측 근거 | View별 후보·실제 확인 영역 | 시점 통합·충돌·가림 처리 | Observed 여섯 필드 | B; ROI만으로 빈 영역 확인 불가 | 코드 구현 |
| 상태/비교 | 실제 Observed·동일 승인 Design/Plan·baseline | 실제 Current 채택·revision·Expected 비교 | INITIAL/STEP/FINAL 결과 | B→D; D는 진행·종료 책임 | 독립 검사 기록 |
| 손 게이트 | V0 손 모델·ROI·동기화 영상 | 진입 후 연속 이탈 >3초+안정 | 관측 허용/보류 | Controller 안전 확인을 대신하지 않음 | 설정 미완료 |
| 제스처 | 지원 요청 문맥·제스처 영상 | 엄지척 등 분류 | 준비 응답 | 10/8 계약은 D 생산/유효성 판단; B에 구현된 것은 손 존재 감지 | B 분류 미구현 |

Observed 필드: `check_id, observation_seq, status, visible_blocks, verified_regions, reason`. 블록 필드: `brick_type, color, x, y, layer, orientation_deg`. 영상/투영/시험 로그를 공통 필드에 추가하지 않는다.

### 정상 입력·출력 예시 — 합성 설명용

아래는 실제 촬영 반환을 복사한 것이 아니라 계약을 설명하는 합성 예시다. Plan 사전 공유와 baseline이 필요하다.

```json
{"check_id":"demo-step-001","check_kind":"STEP","plan_id":"demo-plan","step_id":"S01"}
```

실제 관측이 해당 Expected와 같다면 결과 `status=OK, comparison=MATCH`. `current={current_revision,blocks}`, `expected={plan_id,step_id,blocks}`, `difference={missing,unexpected,unobservable}`와 이번 관측 근거를 반환한다. OK만으로 목표 일치를 뜻하지 않는다.

### 실패 출력 예시 — 합성 설명용

```json
{
  "check_id":"demo-step-001","check_kind":"STEP","plan_id":"missing-plan","step_id":"S01",
  "status":"ERROR","comparison":null,"current":null,"expected":null,
  "difference":null,"observation":null,"reason":"PLAN_NOT_FOUND"
}
```

없는 Plan 검사·촬영 실패를 빈 Current/MATCH로 바꾸지 않는다. 최초 INITIAL의 일부 영역만 확인했거나 전체 상태를 알 수 없으면 `INITIAL_STATE_UNAVAILABLE`로 상태 미확인을 유지한다. 정상 검사의 판정 불가는 UNOBSERVABLE이며 기존 확인 이력과 구분한다.

## 3. 기능별 진행 상태

| 기능 | 최종 요구 | 현재 구현/근거 | 검증 수준 | 미완료·blocker | 다음 완료 조건 |
|---|---|---|---|---|---|
| 분할·색상 | 다층 실제 배치 인식 | integrated_view.py, 11n/26n/26s 모델 파일 | 코드 검사·과거 화면 기록 | 독립 평가의 최신 지표 원문 미확보 | 별도 정답 세트 평가·실시간 재현 |
| 보드 보정 | 세 View 같은 좌표 | 활성 run/calibration.json·검증 JSON | 저장 영상/수동 독립점 5개씩 | 높은 층·실제 자세 반복성은 별도 | 자세/층별 반복 측정 |
| Z/층 | Board 기준 layer 1~5 | depth_grid.py·저장 진단 보고서 | L1·저장 Depth 진단 | top_heights/허용 오차 null, 5층 실측 없음 | 기준면·실측 상면·허용 오차 채택 |
| View 통합 | V0→D1→D3 즉시 검사 | main.observe_cycle·multiview.py | hook/Fixture 독립 검사 | 실제 Controller/capture callable 결선 | 정지·시각·연속성 실제 시험 |
| Current/비교 | INITIAL/STEP/FINAL | inspection.py·team_connection.py | B L1/L3 검사 기록 | 실시간 D bind 미검증 | 정상·보류·취소 공동 실행 |
| 손 인식 | V0 이탈 >3초 | hand_cycle.py·손 detect 모델 | 상태기계 검사, 장치 재검증 필요 | ROI/confidence/안정 임계값 null | 보드 ROI/정답 영상·재진입 평가 |
| 3D 상태 표시 | Current/Expected 투명 투영 | visualization.render_state_overlay | 코드 검사 | live_view 자동 결선 없음·실측 투영 설정 필요 | D 상태 문맥과 화면 통합 |
| 제스처 | 요청별 준비 응답 | B에는 hand detect만 있음 | 해당 없음 | 지원 제스처는 D 계약; B 담당 변경 합의 없음 | D 담당/생산자 확인 |
| 최종 완료 | 외형+실행/접촉 증거 | B 공간 FINAL 검사 | 합성 입력 검사 | 접촉·물리 결착·팀 종료 실기 미검증 | B FINAL+D 실제 증거로 종료 |

설정 확인: config.yaml의 RGB 기준은 1280×720, stud_pitch_m=0.016, min_confidence=0.25, exit_seconds=3.0이다. fps·timeout·손 ROI/신뢰도/안정/프레임 간격·실측 높이·기하 허용값은 다수 null이다. 기본 설정 파일만으로 모든 항목을 시연 가능하다고 주장하지 않는다.

## 4. 원리·알고리즘·코드 구성

### 4.1 색상과 instance 분할

OpenCV HSV로 노랑·파랑·빨강 mask를 만들고 합집합을 포함하는 padding crop의 **원본 RGB**를 YOLO에 입력한다. YOLO mask는 원본 픽셀 위치로 복원한다. 색상 표와 모델 클래스를 대조하며 반사·충돌을 기록한다.

선택 이유는 사용자 요구의 역할 분리다: 색상 후보는 OpenCV, 맞닿은 개별 블록 경계·종류는 YOLO, 층/좌표는 Depth/Grid. 색상 connected component만으로 같은 색 접촉 블록을 분리하기 어렵고, RGB만으로 높이를 확정하기 어렵다. HSV는 반사·조명에 민감하며 crop이 보드 ROI와 같지는 않다.

`integrated_view.process_frame/color_crop/measure_instance/draw_integrated`는 로컬 화면 경로다. 한편 `main.observe_cycle`은 `infer_masks`로 원본 RGB YOLO를 호출한다. **두 경로의 전처리를 실제 팀 실행에서 동일하게 연결했다는 증거는 아직 없다.** 자동 사이클까지 HSV 선처리가 완료됐다고 확대하지 않는다.

모델 기본값은 `models/block_v1_six_runs_20261010/blocks_yolo26s_best.pt`. 11n/26n도 존재하지만 최신 비교 성능 JSON은 이번 열람에서 발견하지 못했다. 성능 우선 선택은 사용자 의도이며 26s 우수 정확도 수치를 임의 생성하지 않는다. `mask_iou_eval.py`에는 25장/387 GT·confidence .25·같은 클래스 IoU≥.5 매칭 프로토콜이 있지만 **스크립트 조건은 실행 결과가 아니다**. 조정에 사용한 validation은 독립 test가 아니다.

### 4.2 좌표·높이

왜곡 보정과 homography로 기준 평면 픽셀→Board를 연결하고, `solvePnP` 기반 camera pose를 사용한다. 블록 높이에는 RGB 정렬 Depth 역투영과 Camera↔Board 변환·높이 기준이 추가로 필요하다. 평면 homography만으로 높은 블록 좌표를 처리하면 시차 오차가 생긴다.

대표 무왜곡 역투영: X=(u−cx)·Z/fx, Y=(v−cy)·Z/fy. scale로 원본 단위를 미터로 바꿔 rigid 변환하고 Board의 Z/footprint를 검증한다. 사선 camera optical Z는 Board 수직 높이가 아니다. 공통 anchor는 최소 footprint 모서리, +X 오른쪽/+Y 위, 0~23 정수다.

현재 활성 보정은 **16mm pitch**다. 과거 17mm 대화/자료는 run_pitch17_archive와 구분한다. 보드끼리/블록끼리 자 측정의 약 20mm(평균 약 19.7mm/층)는 근사 참고이며 Board 기준 실측 높이를 대신하지 않는다. 5층 값은 자동 추정하지 않는다.

confidence .25는 후보 필터의 시험 설정이다. NMS IoU, mask 평가 IoU, 보정 위치 오차 2mm, 높이 허용 오차는 서로 다른 기준이다.

### 4.3 관측 근거·추적·비교

`visible_blocks`는 실제 확인된 후보가 공통 좌표·종류·층 검사를 통과한 결과다. `verified_regions`는 해당 층의 점유/빈 영역을 실제 검사한 근거가 있어야 한다. main은 capture_view가 제공한 verification_basis를 요구하며 자동 전체 보드 ROI를 확인 영역으로 채우지 않는다. 전체 영역 생산은 장치 연결 측의 미검증 항목이다.

`multiview.merge_views`가 문맥·좌표별 근거와 충돌을 통합한다. `VisionInspection`은 동일 Plan baseline을 고정하여 prefix Expected와 실제 Current를 비교한다. 가린 아래층은 이력으로 보존하되 visible_blocks에 새 검출로 넣지 않는다. 실제 배치 변경만 revision 증가, 늦은/취소 결과는 확정 권한 검사로 차단한다.

최신 보완: 첫 INITIAL은 24×24×5 전체 verified 근거가 없으면 초기 Current를 확정하지 않는다. FINAL의 새 verified 근거가 없으면 과거 MATCH를 재사용하지 않고 UNOBSERVABLE이다. 이는 추측 빈 보드/오완료를 막지만 전체 관측 근거 생산이 현실적으로 가능한지 시험해야 한다.

### 4.4 입력 하나의 통과 예시

실제 승인 Plan의 S01 검사 ID 고정 → 실제 V0 정지/손 게이트 → View 촬영 metadata의 ID/seq/보정/scene 확인 → mask 생성 → Depth 후보 검증 → 확인 영역과 통합 → S01 prefix와 공간 비교 → Current/revision·Difference 결과 callback → D가 활성 Job/check·STOP/실행 상태를 검사한다. 다른 실제 색상은 목표 색상으로 보정하지 않고 MISMATCH 근거로 남긴다.

카메라/모델 오류는 ERROR, 부족한 관측은 UNOBSERVABLE/UNKNOWN이다. B는 LLM으로 배치를 생성하거나 Robot pose를 실행하지 않는다.

### 4.5 핵심 파일

| 파일(perception 기준) | 책임 |
|---|---|
| perception_mvp/rgbd_io.py | ROS/SDK 수신·시각/형식 검사·고유 저장 |
| perception_mvp/live_view.py | 로컬 ROS 화면·수동 View 문맥, Robot 명령 없음 |
| perception_mvp/integrated_view.py·opencv_live.py | HSV→YOLO 로컬 분할·기하·간결한 라벨 |
| perception_mvp/yolo_pipeline.py | 모델/클래스 검사·원본 RGB 분할·자료 검사 |
| calibration/lego_grid.py·geometry.py | stud 클릭·보정·독립점 검증 |
| perception_mvp/depth_grid.py·contracts.py | 역투영·품질·footprint/anchor·층 검사 |
| perception_mvp/multiview.py·backend_adapter.py | 근거 통합·Observed 생성 |
| perception_mvp/hand_cycle.py | V0 손 존재와 >3초/안정 상태기계 |
| perception_mvp/main.py | hook 기반 View별 촬영/즉시 처리·저장·재관측 |
| perception_mvp/inspection.py·team_connection.py | B 상태/비교·request/cancel·worker/callback |
| perception_mvp/visualization.py | Current/Expected 3D 투영 함수; 실시간 결선 별도 |

## 5. 실제 구성과 목표 구성

### 현재 코드/확인된 처리 — 배포 ROS graph가 아님

```text
ROS 수신 코드 → live_view(perception_live_diagnostic)
             → integrated_view → 로컬 OpenCV 진단 화면
저장 RGB-D → depth_grid / main → Observed
시험 관측 callable → connect_inspection → VisionInspection → 결과 callback
Current/Expected + projection → visualization(별도 함수)
```

카메라 수신·화면 코드 및 함수 호출은 확인했지만 이번 작업에서 운영 ROS graph를 조회하지 않았다. 실제 D/Controller 결선은 위 흐름에 실선으로 합치지 않는다.

### 최종 목표 — 미연결 포함

```text
승인 Design/Plan → 동일 자료 A→B/D
D 검사 요청 ↔ B 검사/취소
Controller 실제 도착·정지 → RGB-D View 관측·B 상태 비교
B 결과 → D 진행/최종 종료 → HMI·DB·사용자 웹
Controller 접촉/실행 근거 ──────↑
```

| 모듈·노드 | 실제 이름/파일 | 입출력·연결 | 위치 | 확인/한계 |
|---|---|---|---|---|
| 카메라 | 과거 ROS /camera, RealSense driver | Image/CameraInfo topics | 과거 camera PC; 목표 1PC | 대화 기록, 현재 graph 미확인 |
| 로컬 노드 | perception_live_diagnostic / live_view.py | ROS subscriptions→OpenCV 창 | 실행 PC | 소스 확인, B 검사 노드와 다름 |
| B 검사 | InspectionConnection / team_connection.py | Python request·cancel·observe callable·callback | 통합 PC worker | 함수 코드·합성 검사, 실제 D bind 미검증 |
| View 사이클 | main.observe_cycle | confirm_view/capture_view/bundle_valid hooks | 통합 PC | Robot move 명령 없음 |
| 표시 | visualization.render_state_overlay | Python RGB/상태/투영→RGB | 호출 PC | ROS 노드 아님, 실제 화면 결선 필요 |
| D/HMI/DB | D 실행부·history.final_mvp·app/hmi_mvp_contracts | 결과 봉투·수신 validator | 통합 PC/DB | 소비자 함수 시험과 운영 적재 구분 |

소스의 ROS 구독:

| Topic | 타입 | 구독 QoS |
|---|---|---|
| /camera/color/image_raw | sensor_msgs/msg/Image | RELIABLE, KEEP_LAST depth=1 |
| /camera/depth/image_rect_raw | sensor_msgs/msg/Image | sensor_data |
| /camera/aligned_depth_to_color/image_raw | sensor_msgs/msg/Image | sensor_data |
| 위 세 영상의 camera_info | sensor_msgs/msg/CameraInfo | sensor_data |

frame_id는 실제 메시지로 확인한다. 과거 RGB는 camera_color_optical_frame 기록이 있다. 영상 시각은 ROS header stamp, 손 게이트는 단조 시간, 저장 폴더 UTC 시각이며 서로 혼용하지 않는다. live_view 동기화 함수 기본 허용 span은 50ms(코드 설정, 정확도 보장 아님). SDK scale와 ROS 저장 단위는 metadata를 확인한다. 서비스/Action 신규 이름은 확인되지 않았으므로 만들지 않는다.

## 6. 시험 결과와 앞으로의 검증

### 실행 기록 / 저장 결과

| ID | 대상·수준 | 입력/조건·기대 | 실제 결과 | 근거·버전 | 남은 검증 |
|---|---|---|---|---|---|
| T01 | 독립 Grid 점, 저장 영상 | View별 5점, max≤2mm | V0 1.286 / D1 1.771 / D3 1.461mm, 모두 passed | run/validation_error_report.json, 현재 파일 참조; 당시 git SHA 미기록 | 실제 자세 반복·비평면 층 |
| T02 | D1 빈 보드, 저장 Depth | 유효값·평면 진단 | 99.332% 유효, trimmed RMSE 2.048mm, 합격 판정 없음 | 2026-10-07T09:36:01Z 보고서 | threshold·시간 반복·정답 |
| T03 | 노랑 2×2 1~4층 | 상면 ROI 진단 | 보고서 존재, DIAGNOSTIC_ONLY_NOT_LAYER_VALIDATION | 10/7 block_depth_check | polygon 사람 검토·기준면·5층 |
| T04 | B/A/D 관련 L1/L3 | Qt offscreen·합성·Fake | 과거 692 passed | STATUS의 f9b8912 병합 후 기록 | 최신 소스 전체 재실행 아님 |
| T05 | 최신 INITIAL/FINAL L1 | 부분 INITIAL·무근거 FINAL 차단 | 과거 246 passed, 1 skipped | 10/11 STATUS 기록, 현재 HEAD 관련 변경 포함; 당시 실행 tree SHA 별도 미기록 | 실제 생산자·소비자 운영 |
| T06 | 이번 문서 작성 재검사 | 최신 B/legacy/calibration/supply + 실제 로컬 consumer 함수 | 247 passed, 종료 0 / 13.48초 | 현재 HEAD, [검사 기록](evidence/test_result.md) | 장치·DB 적재·전체 D 공정 제외 |

과거 201/1286개 등 다른 tree·범위의 수치를 최신 검사 수와 합산하지 않는다. 기본 전체 pytest의 psycopg/import 수집 오류와 별도 A/C/D 전체 실패 기록은 전체 PASS로 바꾸지 않는다. 모델 평가 스크립트만으로 정확도 수치를 주장하지 않는다.

### 재현 명령 — 저장소 루트, 장치 없는 코드 검사

```bash
QT_QPA_PLATFORM=offscreen \
PYTHONPATH=.:perception:perception/legacy \
B_ROUND1_CONSUMER_PATH="$PWD/history/final_mvp.py" \
B_ROUND1_HMI_CONSUMER_PATH="$PWD/app/hmi_mvp_contracts.py" \
python3 -m pytest -p no:cacheprovider \
  perception/perception_mvp/tests perception/legacy/tests \
  perception/calibration/tests perception/supply_vision/tests -q
```

### 향후 시험

| 시험 | 준비·절차 | 지표·기준 | 협업 |
|---|---|---|---|
| 모델 독립 평가 | 조정과 다른 실제 배치/조명, 사람 mask·클래스 정답 | instance precision/recall·mask IoU·표본 수; 목표값 팀 합의 | B |
| 위치·층 | 최종 pose·보정·Board 기준 상면 1~5층 실측·여러 위치/반복 | Grid 오차·층 혼동·누락; 높이 허용값 합의 | B/Controller |
| 전체 근거 | 빈 판/적층/가림에서 View별 실제 verified 생성 | INITIAL 전체 확인 가능·ROI≠근거, FINAL fresh evidence | B/D |
| 자동 사이클 | 실제 stop/capture/bind, ID를 고정하여 V0→D1→D3 | 정상/보완·취소·STOP·늦은 결과가 한 번만 처리 | B/D/Controller |
| 공동 복구 | 오조립→보류→사람 수정→새 check 재관측 | 오완료 비율·차이 검출·부적절 진행 횟수·복구 비율, 분모/성공 기준 합의 | B/D/HMI |
| 물리 완료 | B FINAL 외 Controller 실행/접촉·실물 체결 확인 | 외형 MATCH만으로 물리 결착 완료 금지 | D/Controller |

## 7. 트러블슈팅·노하우

| 문제/재현 | 원인 확인 | 조치·재검증 | 남은 한계 |
|---|---|---|---|
| 보정 약 24mm 오차·overlay 좌표 불일치 | 원점/인덱스/기준 대응 점검; 정확한 단일 원인은 과거 로그 재구성 필요 | stud 중심·(0,0) 대응 수정/재클릭, 현재 16mm 검증 보고서 통과 | pass 수치를 당시 모든 수정의 인과 증거로 쓰지 않음 |
| Depth 영상 흑/백으로 보임 | 표시 dynamic range와 raw 수치 차이 | 원본 uint16·scale·분포 검사 | 표시 개선은 센서 품질 개선 아님 |
| D1 반사·누락 | 반사 가설·사용자 차광/재촬영 기록; 센서 원인 단정 불가 | 저장 ROI 유효률 진단 99.332% | 품질 threshold 미합의·stud/평면 혼합 |
| 토픽은 존재하지만 Waiting for ROS RGB | 사용자 camera PC USB 이탈 확인; 이후 raw 수신/QoS도 별도 문제 | USB 재연결 기록·reliable echo·구독 설정 확인 | USB만으로 이후 모든 수신 문제 원인 확정 불가 |
| 같은 파일명으로 업로드 혼동 | rgb.png 반복 | 고유 파일명·원본 출처 연결 | 현 자료 전체 파일 연결 audit 필요 |
| 라벨 정보 겹침 | 블록별 긴 diagnostics | draw_integrated 종류·XY·L로 축약 | 밀집 배치 가독성 실제 시험 |
| 보드 밖 후보 검출 | HSV crop은 보드 ROI가 아님 | **View별 보드 ROI 필터 개선 제안** | 현재 integrated_view에 명시 보드 ROI 필터 없음; 해결 완료로 쓰지 않음 |
| 무근거 INITIAL/FINAL 성공 위험 | 일부 영역 빈 상태 초기화·과거 상태 재사용 결함, 신규 검사로 재현 기록 | 최신 전체 INITIAL coverage·fresh FINAL guard | 전체 근거 생성 실제 시험 필요 |

ROI는 세 용도를 구분한다: 손 보드 ROI, Depth 진단 ROI, 블록 검출 ROI. ROI 자체는 verified_regions 증거가 아니다. 보드 밖 필터는 적층 돌출/사선 투영과 가장자리 블록을 보존해야 한다.

노하우: 구독 여부→header/frame 발행→형식/동기화→모델→기하 설정 순서로 분리 점검한다. 독립 클릭은 보정점과 분리하고 최대 오차/RMSE를 구분한다. 실제 정답은 Expected가 아니라 사람이 배치 기록으로 만든다. 안전 정지와 손 게이트/제스처는 별개다.

## 8. 고도화·협업 요청

| 구분/우선순위 | 개선·한계 | 방법·기대 효과 | 검증 | 선행/상대 | 작업량 |
|---|---|---|---|---|---|
| 발표 전 P0 | 시연 준비 상태 불명 | 실제 설정·모델·ROS 수신 점검 | 짧은 재현 및 화면 저장 | B/Camera PC | 설정 점검+장치 시험, 시간 미산정 |
| 발표 전 P0 | D bind·전체 관측 근거 | 실제 callable·Qt enqueue·ID 연결 | 정상/취소/불가 공동 시험 | D/Controller | 연동 작업, 인터페이스 확인 필요 |
| 발표 전 P0 | 5층 Z 미측정 | Board 기준면·상면 채택 | 위치/층 정답 반복 | B/Controller | 실측 시간 필요 |
| 발표 전 P1 | 보드 밖 후보·표시 | ROI·HSV 사이클 경로·3D 화면 연결 | 내부 유지/외부 제외·투영 오차 | B/HMI | 코드 변경은 별도 승인 |
| 이후 P1 | 독립 성능 근거 부족 | 장면 분리 GT·모델/임계값 평가 | 별도 test precision/recall/IoU | B | 라벨/표본 규모 합의 |
| 이후 P2 | 어려운 가림/반사 | 품질 기준·추가 View 정책, 필요 시 공간 융합 검토 | 동일 정답 시점 비교 | B/D | 필요성 확인 후 산정 |

D에게 발표 전 실제 request/cancel/Plan/result 결선과 INITIAL 미확인 표시를 요청한다. Controller에게 최종 관측 pose/정지 근거·시각 연결을 요청한다. HMI 담당에게 최신 B 결과 문맥·투영 입력을 요청한다. 직접 결착의 접촉 근거·제스처 생산은 D 담당 확인이 필요하다. 구체 완료 시각은 담당자와 합의하며 문서가 임의로 약속하지 않는다.

## 9. 발표용 자료·본인 확인

### 핵심 메시지 3개

1. 색상·개별 블록 경계·실제 위치/층을 각각 HSV·YOLO·Depth/Grid로 구분한다.
2. 관측 근거 없는 빈 상태/완료를 만들지 않고 가림·취소·늦은 결과를 보류한다.
3. 코드 계약 검증과 실제 결착 검증은 다르며 최종 완료는 B 공간 근거와 D 실행 근거를 함께 확인한다.

### 슬라이드 4장

1. 역할/범위: 실제 상태를 읽는 B, 진행·접촉은 D. 현재/목표 구조도 분리.
2. 인식 원리: RGB→HSV→YOLO→Depth/Grid, 실제 Grid 검증 이미지.
3. 실패와 신뢰성: 반사·보정·무근거 확인·check_id/취소.
4. 검증/다음 작업: 수치의 표본·범위, 현재 미설정·미연결 및 공동 시험.

### 2분 설명 대본 — 본인 확인 후 사용

“저는 B 비전 파트를 맡아 실제 조립 상태를 읽고 목표와 비교할 근거를 만드는 작업을 했습니다. 최종 목표는 로봇의 직접 결착이지만, 기존 사람 조립 관측 시험을 직접 결착 성공이라고 말하지는 않습니다.

로컬 화면은 OpenCV로 색상 후보를 구분하고 YOLO segmentation으로 개별 블록의 종류와 외곽을 얻습니다. 이후 정렬 Depth와 보정값으로 보드 좌표와 층을 확인합니다. 현재 활성 보정은 16밀리미터 간격이며 세 관측점의 독립 다섯 점 검사에서 최대 오차가 2밀리미터 이내였습니다. 이 결과가 5층 전체 정확도를 보장하는 것은 아닙니다.

관측은 V0, D1, D3에서 정지 후 View별로 즉시 검사하도록 구성했습니다. 손 이탈 3초 초과는 V0 관측을 시작하는 조건이지 안전 인증이나 조립 완료가 아닙니다. 가린 아래층은 확인 이력으로 유지하고, 초기 전체 근거가 없거나 마지막 새 관측 근거가 없으면 완료를 만들지 않습니다. 검사 ID와 취소 처리는 늦은 결과로 진행하는 문제를 막습니다.

현재는 코드와 저장 자료의 근거가 있고 실제 자동 사이클, 손과 높이 설정, D 연결 및 최종 물리 결착 시험은 남아 있습니다. 발표 시에는 확인한 부분만 시연하고 나머지는 공동 검증 계획으로 설명하겠습니다.”

### 시연 절차·대체 자료

1. 장치 없는 코드 검사 결과와 아래 Grid 검증 파일을 먼저 제시한다.
2. 실제 ROS/모델/설정이 준비됐으면 **로컬 진단** 화면에서 블록 mask·색상·XY·L/미확인을 보여준다. 현재 null 설정으로 손/층을 정상이라고 표시하지 않는다.
3. 실제 D 결선이 확인된 경우에만 STEP/FINAL·보류·취소·다음 진행을 시연한다. 수동 View 키로 Robot을 이동시킨다고 설명하지 않는다.
4. 실패하면 기존 저장 Grid/Depth 보고서와 합성 계약 예시로 범위를 설명한다. 대체 영상은 아직 선정되지 않았으며 실제 시연처럼 위장하지 않는다.

팀 전체 단일 실행 명령은 D 진입점/실제 결선 확인 전 작성하지 않는다. 성공 근거는 mask가 보이는 것만이 아니라 실제 정답·검사 ID·확인 영역·D 진행 disposition이다.

### 시각화 후보 — 원본 경로만 연결, 이번 작업에서 새 이미지 생성 없음

| 후보/파일 | 입증하는 내용 | 주의 |
|---|---|---|
| [V0 Grid](../../../perception/recordings/board_calibration_V0/V0/run/grid_overlay.png) | 보정 Grid 시각 정합 | 독립 수치 검증과 별개 |
| [D1 Grid](../../../perception/recordings/board_calibration_D1/D1/run/grid_overlay.png) | 사선 보정 | 층 시차/반복 pose 미검증 |
| [D3 Grid](../../../perception/recordings/board_calibration_D3/D3/run/grid_overlay.png) | 반대 시점 보정 | 동일 |
| [D1 Depth ROI](../../../perception/recordings/empty_board_depth/D1/depth_baseline_review_20261007T093600059227Z/depth_roi_review.png) | 진단 ROI·Depth 품질 | 블록 검출 ROI/verified 아님 |
| [4층 V0 상면 ROI](../../../perception/recordings/block_depth_check/scene_04_yellow_2x2_layer_04/top_depth_review/V0_top_roi.png) | 저장 블록 높이 측정 영역 | AI polygon 사람 검토 대기·진단 |

현재 링크는 로컬 프로젝트 기준이다. 드라이브 제출 전에 선정한 원본 이미지를 함께 업로드하고 파일명/링크를 바꿔야 한다. 이번 초안은 이미지를 실제로 열어 시각 품질을 검수한 단계는 아니다. 통합 화면·Roboflow·ROI 전후·영상은 파일 재확인/선정 필요. AI 생성 이미지를 실제 코드 출력 증거로 쓰지 않는다.

### 예상 질문·답변 5개

1. **confidence .25는 정확도 25%인가?** 아니다. 모델 후보 점수 필터이며 실제 정확도는 정답 세트 평가가 필요하다.
2. **보정 2mm 통과면 층도 정확한가?** 아니다. 평면 독립점 오차와 Z/층 기준은 별도다.
3. **가린 아래층은 어떻게 아는가?** 기존 유효 확인 이력을 유지하며 새 visible 검출로 만들지 않는다. 신규 미확인 블록은 추정하지 않는다.
4. **최종 MATCH면 체결 완료인가?** 외형 공간 일치 근거다. 실제 물리 결착·접촉·실행 상태는 D/Controller 근거가 추가로 필요하다.
5. **ROI로 밖의 검출을 해결했나?** 손/Depth ROI는 존재하지만 현재 integrated 경로의 명시 보드 검출 ROI 해결은 아직 제안이다.

### 본인 확인 체크

- [ ] 최신 모델 비교 결과·조정/독립 평가 데이터와 클래스/표본 수를 직접 설명할 수 있는가?
- [ ] 과거 17mm와 현재 16mm 보정 채택 근거·클릭 방법·2mm 임계값을 설명할 수 있는가?
- [ ] 픽셀→카메라→보드 단위·height 기준과 5층 실측 필요를 설명할 수 있는가?
- [ ] verified_regions의 실제 생산 근거와 INITIAL 전체 coverage 조건을 설명할 수 있는가?
- [ ] B 상태 확정과 D 진행, 취소 전/후 경쟁·늦은 결과 처리를 설명할 수 있는가?
- [ ] 손 detect와 지원 제스처를 구분하며 실제 담당/미구현을 확인했는가?
- [ ] 로그/이미지에서 비밀정보·개인정보를 점검하고 실제 화면을 열어 검수했는가?
- [ ] 원본 이미지/로그를 함께 업로드하고 문서 링크·제출 완료 DM을 본인이 보냈는가?

## 참고·제출

- [현재 제품 목표](../../10_FINAL_MVP.md), [최신 결정](../../00_CURRENT_DECISIONS.md), [개발 기록](../../STATUS.md)
- [10/8 책임 계약](../../handover/final_mvp_interface_20261008/README.md)
- [B→D 실제 연결 요구](../../../perception/docs/D_INSPECTION_CONNECTION.md)
- 안내 원문: `/home/roh/Downloads/최종MVP_발표준비_팀원별_제출안내.md`(2026-10-10 작성).
- Google Docs 네 참고 링크는 이번 작성에서 내용을 열람하지 않았으며 로컬 문서와 실제 소스를 기준으로 작성했다. 접근 가능한 최신 공동 문서와 차이는 팀장 확인이 필요하다.
- 제출: 2026-10-11 오후, 구글드라이브 ‘인원별 제출물’. 로컬 docs/presentation/B는 작업 편의를 위한 경로이며 팀장 지정 경로가 아니다. Drive 업로드·Slack DM·Git 게시는 수행하지 않았다.
