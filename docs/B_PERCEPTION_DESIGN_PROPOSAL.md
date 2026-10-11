# B Perception 설계 제안서

최신화: 2026-10-11 / 담당: 홍동  
상태: 최신 요구·10/8 계약 반영. 설계 요구, 로컬 구현, 실제 검증을 구분한다.

> 본문이 현재 기준이다. 문서 끝의 초기안은 역사적 출처이며 현재 계약으로 적용하지 않는다. B는 Current·revision·Expected·비교 담당, D는 검사 식별·진행/보류·Robot·HMI/DB 전달 담당이다. 과거 Backend 단독 소유 설명을 대체한다.

## 1. 지원 범위와 책임

- Day 4 팀 통합 1PC, Python 3.12 / ROS2 Jazzy, M0609 장착 D435i 및 RG2.
- Assembly Board는 24×24 stud, 전달판과 별개다.
- 노랑·파랑 2×2/2×3 및 빨강 2×1 한 종류, layer 1~5. 6층은 거부한다.
- YOLO 클래스는 yellow_2x2, yellow_2x3, blue_2x2, blue_2x3, red_2x1. 기존 네 클래스 자료는 보존하되 빨강 지원으로 간주하지 않는다.
- 현재 관측점은 **V0 → D1 → D3**. D2/D4 및 다섯 View 필수 촬영은 과거 후보안이다.
- 최신 검사 코어의 Design 상한은 40블록이다.

| 담당 | 책임 |
|---|---|
| B | 손 감지·촬영 판단·View별 인식/검증·통합·Observed, Current 채택/revision·Expected 계산·비교 |
| 계획 생산자 | 같은 Design·Plan·기준 Current를 B/D에 공유, 의도 확인·재계획 |
| D Backend | 활성 검사/버전 식별·요청/취소, 완료·보류·다음 전달 판단, HMI/DB 전달 |
| Controller | 승인 경로 이동·실제 정지·안전·실패/중단·V0 복귀 결과 |
| HMI | 영상·상태 투영, 사유·필요 조치·수정 가능·재관측 표시 |

B는 실제 관측을 Expected와 다르다고 거절하지 않는다. 확인하지 못한 기존 Current/아래층은 보존하며 목록 누락만으로 삭제하지 않는다. 실제 채택 변경만 revision을 증가시킨다. Expected는 고정 Plan 기준 Current와 Step 누적 효과로 계산하며 Robot 전달 완료를 조립 효과로 반영하지 않는다. B는 다음 Step/Robot 동작을 독자적으로 시작하지 않는다.

## 2. 정상 관측 사이클

```text
Robot 전달판에 블록 내려놓음
→ V0 복귀·실제 정지
→ 사람 가져오기·Assembly Board 조립
→ V0 보드 영역 손 진입·이탈 감지
→ 연속 손 이탈 3초 초과 + 영상 안정
→ V0 RGB-D 촬영 → 즉시 인식·검증
→ D1 이동·실제 정지·안정 → 촬영 → 즉시 인식·검증
→ D3 이동·실제 정지·안정 → 촬영 → 즉시 인식·검증
→ 시점 통합·Observed·B Current/Expected 비교
→ D가 활성 검사 및 진행 조건 확인
→ 조건 충족 시 다음 Step/전달
```

- 모든 촬영 후 일괄 분석하지 않는다. 각 View에서 촬영 직후 검증한다.
- 손 감지는 V0에서만 수행하며 D1/D3에서는 비활성이다.
- 손 재진입 시 이탈 대기 초기화, UNKNOWN을 이탈로 간주하지 않는다. 정확히 3초는 미충족이다.
- 손 이탈 >3초는 관측 전환이지 완료 판정이 아니다. 영상 안정·실제 안전 조건도 필요하다.
- 다른 View로 보완 가능하면 남은 관측을 진행하며 곧바로 사람 수정을 요구하지 않는다.
- 정상 D3 이후 V0 복귀를 필수 단계로 추가하지 않는다. 이후 이동은 승인된 다음 전달 경로다.
- 다음 진행에는 조립 확인 외 전달판 비움·활성 실행 없음·STOP/오류 없음 등의 D 조건이 필요하다.
- 시점 사이 조립물이 움직였으면 동일 정적 묶음으로 합치지 않는다.

## 3. 인식·학습·다중 시점

**OpenCV HSV 색상 구분 → YOLO Segmentation 종류/instance mask → Depth/Grid 검증**이 사용자 요구 파이프라인이다. 노랑·파랑·빨강 후보를 먼저 구분하고, 원래 RGB 좌표의 mask를 정렬 Depth와 연결한다. crop/resize 사용 시 원본 픽셀 좌표를 유지·복원한다. HSV 누락·반사 및 HSV/YOLO 충돌을 정상으로 숨기지 않는다.

YOLO는 RGB의 보이는 블록별 외곽/클래스를 학습한다. Depth는 후처리 근거이며 층·방향별 클래스는 늘리지 않는다. Roboflow 자동 후보/직접 polygon 모두 사람이 반사·접촉·가림 경계를 검토한다. 단층 독립 배치만으로 다층 분리를 보장하지 않는다.

학습 데이터에는 1~5층, 랜덤 위치·방향, 같은 색/다른 색 접촉·적층·가림·반사를 포함한다. 한 View에 고정하여 층·배치를 바꿔 수집해도 된다. 다중 시점 시험은 **같은 배치를 유지한 V0→D1→D3 묶음**이어야 한다. 유사 장면이 train/validation/test에 섞이지 않도록 장면 단위로 분리한다. 반복 고정 프레임만으로 다양성이 생기지 않는다.

모델 선택은 사용자 요구대로 속도보다 실제 인식·분할 성능을 우선하며 크기만으로 우수성을 확정하지 않는다. 클래스 이름/순서와 버전을 검증한다.

Depth는 mask 내부 유효값·CameraInfo·Depth scale·Board 변환으로 위치·높이·footprint·층을 검증한다. 사선 카메라 축 방향 거리와 보드 수직 높이는 다르다. 누락/0/이상값·홀 채우기·목표 높이로 확정하지 않는다. 일부 ROI의 품질 검사를 보드 전체 능력으로 확대하지 않는다.

시점 mask를 픽셀로 합치지 않고 Board 좌표·층·footprint·종류로 연결해 중복/충돌과 근거를 유지한다. 기존 가린 아래층은 추적 이력으로 보존하되 이번 visible_blocks에 넣지 않는다. 기록 없는 가려진 블록의 종류/색상을 높이만으로 추정하지 않는다.

## 4. 좌표·보정·높이

- 원점은 표시한 빨간점 (0,0), +X 오른쪽/+Y 위, stud 인덱스 0~23, layer 1~5.
- 공통 x/y는 최소 footprint 모서리 anchor다. mask 중심 픽셀이나 Robot TCP와 다르다.
- 2x3x1은 0도 X2/Y3, 90도 X3/Y2. 2x2x1은 0도로 정규화.
- 빨강 YOLO red_2x1은 공통 brick_type **1x2x1**: 0도 X1/Y2, 90도 X2/Y1.
- 사용자 stud 중심 간격 실측은 **17mm**. 근거 없이 다른 값으로 덮지 않는다.
- V0/D1/D3 실제 최종 자세마다 보정·독립 검증한다. 자세·해상도·내부 파라미터 변경 시 재확인한다.
- 클릭은 stud 중심이며 외곽 끝점·stud 사이 틈이 아니다. 보드 외곽 크기를 필수 입력으로 임의 추가하지 않는다.
- 평면 Grid 보정만으로 Z/층 검증이 끝나지 않는다. CameraInfo·정렬/scale·Board pose/높이 기준·실측 상면 설정이 필요하다.

### 보정 임계값

기존 1.5mm에서 사용자 승인으로 **2mm**를 사용한다. 독립 점의 예측 Board 좌표와 실제 지정 좌표 사이 오차에 대한 기준이다. max_error_mm는 다섯 점의 합이 아니라 **각 점 오차의 최대값**이며 설정값 이하가 통과다. RMSE는 별도 지표다.

이 값은 프로젝트 위치 오차 허용 설정이며 제조사 보장·Depth 층 판별 임계값·전체 장치 인증이 아니다. 임계값 확대가 정확도 향상을 뜻하지 않는다. grid_overlay 육안 정합만으로 독립 검증을 대신하지 않는다. 실제 통과 파일·기준·버전을 유지한다.

### 실측 높이와 빈 보드

| 사용자 실측 | 값 | 맥락 |
|---|---|---|
| 보드 stud 없는 부분 | 1.5mm | 실물 두께 |
| 보드 stud 돌출 | 4mm | 포함 총 5.5mm |
| 블록 몸체/stud 돌출 | 18mm / 4mm | 단일 측정 기록 |
| 블록끼리 체결 2층 | 42.5mm | 보드에 체결한 높이가 아님 |
| 블록끼리 체결 3층 | 61.5mm | 같은 측정 맥락 |
| 블록끼리 체결 4층 | 81mm | 같은 측정 맥락 |

**매 층 증가량 약 20mm**, 사용자와 정리한 **평균 증가량 약 19.7mm/층**은 근사 설계 참고다. Board 기준 실측 상면값을 대체하지 않으며 보드 표면/stud 상면/테이블 기준을 혼용하지 않는다. 체결 깊이·측정 기준/오차를 기록한다. 5층 실측은 별도로 필요하고 기존 4층 값으로 자동 생성하지 않는다.

빈 보드 RGB-D는 세 View에서 보드 기준면·유효값·누락/반사 분포를 확인한다. 이미지의 밝고 어두움은 표시 범위일 수 있으므로 원본 숫자·dtype·단위로 평가한다. 유효 거리 하나만으로 전체 보드 품질을 확정하지 않는다.

## 5. 공통 보류·수정·재관측

```text
필요 관측 후 판단 불가 또는 배치 수정 필요
→ 현재 검사 종료/무효화·다음 집기/전달 보류
→ 사유·필요 조치 표시
→ V0라면 정지 유지 / D1·D3라면 안전 확인·검증 경로로 V0 복귀
→ 실제 정지·안전 확인 후 사람 수정 가능 표시
→ 사람 손 진입·이탈
→ 연속 이탈 >3초 + 영상 안정
→ D가 새 check_id 발급, V0부터 새 관측
→ 필요한 D1·D3 추가 관측·View별 즉시 검증·통합
→ B 재비교·D 진행 판단
→ 통과 시 진행 / 미통과 시 보류 유지
```

View마다 복제하지 않고 공통 처리를 호출한다. 실제 배치 문제는 위치·색상·방향·층 수정 안내, 가림·반사·Depth 부족은 관측 조건 개선 안내로 구분한다. STOP·Robot 오류·전달판 점유는 별도 보류이며 재조립을 요구하지 않는다.

복귀 실패·STOP·안전 미확인은 수정 가능 표시·재관측·다음 전달을 차단한다. 현재 Step 확인 문맥은 유지하되 의도 확인·재계획이 필요하면 기존 Backend/Planner 흐름으로 연결한다. 항상 같은 Step을 재실행한다고 가정하지 않는다. 반복 실패는 사유/보류 유지이며 무한 이동·재시도/자동 물리 복구는 하지 않는다. 재검증 전 완료로 표시하지 않는다.

## 6. 최신 데이터·식별 계약

공통 Observed 여섯 필드는 **check_id / observation_seq / status / visible_blocks / verified_regions / reason**으로 유지한다. 블록 여섯 필드는 brick_type / color / x / y / layer / orientation_deg다. 영상·View·투영·보정 버전·시험 로그는 별도 전달한다. 추가 JSON 파일은 필수가 아니며 D/HMI 실제 인터페이스에 따른다.

현재 연결은 perception_mvp.team_connection.connect_inspection 및 load_plan/request/cancel/close다. 실제 관측 callable과 D 소유 스레드로 enqueue하는 결과 수신 함수가 필요하다.

| 검사 | 요청 | 의미 |
|---|---|---|
| INITIAL | plan_id/step_id null | 실제 초기 Current 확보, Expected/비교 null |
| STEP | plan_id/step_id 필수 | 고정 Plan 기준 해당 Step 비교 |
| FINAL | plan_id 필수, step_id null | 모든 Step MATCH 이후 승인 전체 Design 비교 |

요청은 check_id/check_kind/plan_id/step_id다. 촬영 시작 시 문맥을 고정하고 결과에 같은 check_id를 반환한다. 현재 로컬 연결은 새 요청 한 묶음 observation_seq=0이며 다른 순번 정책은 합의한다.

결과 봉투는 check_id/check_kind/plan_id/step_id/status/comparison/current/expected/difference/observation/reason이다. STEP/FINAL comparison은 MATCH/MISMATCH/UNOBSERVABLE. **OK는 판단 가능이지 목표 일치가 아니다.** 실제 차이와 미확인이 함께 있으면 MISMATCH와 unobservable 근거를 함께 반환하며 진행을 보류한다.

ERROR/CANCELED의 상태 관련 payload는 null이다. 미수신/실패를 빈 Current/MATCH로 처리하지 않는다. 최초 Current 없는 INITIAL 미확인은 현재 PR #22 소비자 제약 때문에 ERROR/INITIAL_STATE_UNAVAILABLE로 반환하며 D 초기 미확인 표시·재검사 정책은 미확정이다.

D는 이전 요청을 닫고 B 동일 ID를 취소한 뒤 새 ID를 발급한다. Plan 공유만으로 묵시 취소하지 않는다. 취소가 먼저면 늦은 계산을 채택하지 않고 확정이 먼저면 취소로 상태를 되돌리지 않는다. 같은 요청 중복은 재촬영하지 않으며 동일 ID의 다른 내용은 오류다. 늦은/닫힌 결과로 진행하지 않는다.

결과 callback 전달 실패는 채택 실패로 위장/rollback하지 않고 미전달 원문·원인을 보존한다. D는 진행 보류·연결 복구를 처리한다.

기존 connect(bridge)→bridge.bind(handler), submit_observation/submit_place/submit_failure는 **별도 호환 경로**다. PLACE(전달판)/ASSEMBLY(현재 Step)/CURRENT(실제 재관측)를 구분하고 after=null만으로 목적을 추정하지 않는다. 새 검사 봉투와 자동 혼용하지 않는다. 전달판 EMPTY/OCCUPIED/UNOBSERVABLE은 별도 반환하며 미수신·실패를 EMPTY로 만들지 않는다.

## 7. 통합 화면·저장

한 화면에 OpenCV 색상, YOLO 종류/instance mask, Depth/Grid, V0 손 상태를 함께 표시한다. 기본 블록 라벨은 **색상+사이즈(종류), layer, Grid anchor (x,y)**다. 방향은 기본 텍스트에서 제외하되 계약·비교에는 유지한다. confidence·원시 축·높이·긴 사유는 진단/상태 영역에 두고 미확인 좌표/층을 확정처럼 표시하지 않는다.

Current/Expected는 최신 유효 버전을 받아 **3D footprint와 층 높이로 투영**한다. 실제 영상이 보이는 높은 투명도의 면·경계·범례를 사용한다. 단순 평면 2D 사각형으로 대체하지 않는다. 보정/높이/버전이 없으면 투영 불가 사유를 표시한다. 재관측 시작 시 최신 Current와 유효 Expected로 갱신하며 Step 목표와 최종 Design을 혼동하지 않는다.

손 대기/안정은 V0에서 표시, D1/D3는 비활성이다. moving·정지 미확인·보류·수정 가능·재관측을 구분한다. 실제 해상도/CameraInfo를 맞추며 화면 resize와 보정 픽셀을 혼용하지 않는다. 수동 View 선택은 Robot 이동 명령이 아니다. 자동 전환은 Controller 도착·정지 신호와 연결해야 한다.

RGB-D 원본은 RGB, raw Depth, aligned Depth, metadata(CameraInfo/scale/timestamp/View/보정·모델·검사 문맥)를 유지한다. 기존 png/npy 저장을 사용하며 Depth 표시 PNG만을 원본 수치로 대신하지 않는다. 촬영별 고유 시각/ID 폴더로 덮어쓰기 방지, 업로드 RGB 고유 이름·출처 연결을 보존한다.

통합 사이클 자동 저장과 live_view의 c 수동 저장은 다르다. 실제 통합 관측 callable에 저장/실패 기록을 연결해야 자동 저장 완료라고 할 수 있다. raw/compressed 전송 선택이 기존 자료를 무효화하지는 않지만 이후 mask 품질·RGB–Depth 동기화/해상도 정합을 확인한다.

## 8. 평가·기록·복구 시험

사람이 시험별 **실제 배치·완료 여부**를 별도로 기록하고 Expected를 정답으로 대신하지 않는다. 동일 확인 요청으로 **관측 → B 채택/비교 → D 완료/보류 → 다음 전달 여부**를 별도 시험 로그에 연결한다. Observed 필드를 늘리지 않는다.

B 단독은 mask/색상/종류·Grid·방향·층·확인 영역·중복/충돌·가림 유지·revision·보정 반복성·시간을 정답과 비교한다. YOLO confidence, NMS IoU, 보정 위치 오차, 높이 허용 오차는 서로 다른 기준이다.

| B/D 공동 지표 | 기록 | 미확정 |
|---|---|---|
| 잘못된 완료 비율 | 실제 미완료/오조립을 완료 처리 | 분모·시험 단위 |
| 실제 차이 검출 비율 | 실제 차이 중 찾아낸 차이 | 분모·블록/속성/장면 단위 |
| 부적절한 다음 진행 횟수 | 불일치/판단 불가인데 Step 진행 | 중복 집계 정책 |
| 수정 후 복구 비율 | 보류→사람 수정→재관측→정상 진행 | 분모·성공 기준·시간 한도 |

분모·복구 성공 기준·목표값은 팀과 합의하며 임의 확정하지 않는다. 자동 Robot 복구를 새로 요구하지 않는다.

필수 사례:
- 빈 보드·다섯 클래스·위치/방향·1~5층·같은 색/다른 색 접촉/적층·추가/이동/제거.
- V0/D1/D3 보류 진입, V0 불필요 복귀 없음, 다른 View 보완으로 수정 없이 진행.
- 손 재진입 대기 초기화, >3초/영상 안정·안전 조건, 복귀 실패·STOP·전달판 점유 차단.
- 취소 전/후 확정, 중복/역순/늦은 결과, 기준 Current/버전 불일치, 결과 전달 실패.
- 오조립→보류→사람 수정→새 검사→정상 복구 및 재불일치/판단 불가.
- INITIAL 미확인·STEP·FINAL, 아래층 가림 유지, 반사/Depth 누락/보정 실패.
- 실제 HMI·DB·다음 전달을 동일 ID로 추적.

## 9. 구현·검증 상태와 남은 작업

2026-10-11 로컬 기록에서 검사 코어/connect_inspection, B Current/Expected/비교·가림/취소, 5층·빨강 계약을 구현했다. B 검사 **201 passed**는 PR #22 DB/HMI **입력 검증 함수 사본** 대조를 포함한다. 사본 미설정은 **200 passed, 1 skipped**. 관련 공유 계약 **1286 passed** 기록은 STATUS에 있다.

이는 실제 Camera/Robot·Qt 표시·DB 적재 전체 통합 완료가 아니다. 통합 화면/손/투영/관측 함수의 코드 존재와 실제 D·Controller 결선 성공을 구분한다. 기존 C 음성/LLM 전체 회귀 실패를 해결한 것으로 표시하지 않는다.

### PR #24 최신 integration 정렬 — 2026-10-11

원격 `codex/integration-round1`의 `02137d8` 기반 별도 로컬 브랜치
`codex/b-round1-realign`에 B 제출 코드만 옮겼다. 최신 사용자 지시에 따라 D 코드와
D 연결 시험의 추가/수정은 제외한다. 최신 A/C/D·공통 계약·Robot 설정은 그대로 유지한다.
이전 PR에 들어 있던 D 변경을 다시 얹지 않는다.

최종 관련 검사 **692 passed**, 실패/오류/skip 0, 종료 0. B 검사와 최신 DB/HMI
입력 검증 함수 대조, 최신 A/C/D Stage3·relay·stale/STOP 회귀를 실행했다.
Qt는 offscreen, 관측은 합성 입력, Robot은 FAKE다. D 코드가 B 실결선까지
완성됐다는 뜻은 아니다. D가 제공해야 할 연결은
[B→D 인계](../perception/docs/D_INSPECTION_CONNECTION.md)를 따른다.
add/commit/push 및 PR #24 수정은 하지 않았다.

남은 연결:
1. D 요청/취소/Plan 공유 및 스레드 안전 결과 수신.
2. 실제 Camera/Controller 관측 callable, 도착/정지/오류/복귀·자동 저장 연결.
3. 보정/ROI/모델·5층 실측·빨강 기하 설정, 실제 다층/가림/투영 시험.
4. INITIAL 미확인·순번·안정화/timeout·재관측 정책 합의.
5. 공동 평가 기준과 시험 참여 시간 공유.

과거 일정은 완료 증거가 아니다. voxel 융합은 필요 시 별도 확장이며 필수로 추가하지 않는다. Git add/commit/push/PR/Issue는 별도 요청 전 수행하지 않는다.

## 10. 근거

- [프로젝트](../README.md), [현재 결정](00_CURRENT_DECISIONS.md), [공통 계약](06_CONTRACT_DRAFT.md)
- [실측 안내](03_MEASUREMENT_GUIDE.md), [팀 역할](02_TEAM_GUIDE.md), [검증 기록](STATUS.md)
- [10/8 실제 검사 연결](../perception/docs/ROUND1_INSPECTION.md), [기존 bridge 호환](../perception/docs/TEAM_CONNECTION.md)
- 2026-10-11 사용자 최신 요구 및 팀장님 PR #22. 최신 책임 구분은 과거안보다 우선한다.

<details>
<summary>2026-10-05 초기안 보존 — 현재 계약으로 적용하지 않음</summary>

아래 초기안의 Backend 소유, 다섯 관측점, 네 클래스, HMI 완료 버튼, 제안 payload는 위 최신 본문으로 대체되었다. 초기 검토 근거를 보존하기 위한 기록이다.

# B Perception 설계 제안서

상태: **팀 검토용 제안**

대상: Assembly Board 관측 및 `Observed` 생성

담당: 홍동 / Perception

작성 기준: 2026-10-05

> 알고리즘 구성은 2026-10-05 사용자 결정으로 확정되었다. 인터페이스 Schema, 실측 보정값, 모델 버전, 신뢰도 임계값 및 Robot pose는 담당자 협의와 실제 시험으로 확정한다. 알고리즘 구성의 확정은 실제 인식 성능의 검증 완료를 의미하지 않는다.

## 1. 제안 목적

사람이 Assembly Board에 조립한 실제 상태를 RealSense D435i로 관측하고, Backend가 채택 여부를 판단할 수 있는 `Observed`를 생성한다. Perception은 계획과 다른 관측도 그대로 보고하며, 관측할 수 없는 상태를 임의로 완성하거나 예상값으로 보정하지 않는다.

최종적으로 다음 질문에 답할 수 있어야 한다.

- 어떤 블록이 존재하는가?
- 블록의 색상과 형상은 무엇인가?
- 24×24 stud Grid에서 어느 위치와 방향에 있는가?
- 몇 번째 층에 있는가?
- 직접 확인된 정보와 가림·미확인 정보는 무엇인가?
- Backend가 이번 관측을 `Current`로 채택할 만큼 신뢰할 수 있는가?

## 2. 프로젝트 범위와 책임 경계

### 2.1 MVP 지원 범위

| 항목 | 범위 |
|---|---|
| 카메라 | M0609 J6 플랜지에 장착된 RealSense D435i 1대 |
| Assembly Board | 24×24 stud Baseplate |
| 블록 색상 | Yellow, Blue |
| 블록 형상 | `2×2×1`, `2×3×1` brick |
| 최대 높이 | 최대 5층 |
| 관측 결과 | 종류·색상·Grid 위치·방향·층·신뢰도·가림·오류 |
| 시스템 구성 | Day 4 기준 1PC |

정확한 Board 원점·축·anchor·layer 시작 번호·방향 표현은 팀 공통 계약으로 확정해야 한다. 과거 Ground Truth의 규칙을 확인 없이 전체 시스템에 강제하지 않는다.

### 2.2 데이터 책임

```text
Perception(홍동) ── Observed ──▶ Backend(수현)
                                  │
                                  ├─ 유효 관측: Current로 채택
                                  └─ 부분·가림·실패: 기존 Current 유지 및 진행 보류
```

- **Observed:** 해당 촬영 시점에서 Perception이 직접 관측하거나 명시적으로 추적한 결과다.
- **Current:** Backend가 유효한 Observed를 채택한 시스템의 현재 상태다.
- **Expected:** Backend가 관리하는 현재 Step의 목표 상태다.
- Perception은 Expected와 다르다는 이유로 유효한 실제 관측을 거절하거나 예상값으로 수정하지 않는다.
- Robot의 부품 전달 완료는 사람의 조립 완료 증거가 아니다.
- 공급 이력은 추적의 참고 자료일 수 있지만, 영상 검증 없이 조립 완료로 확정하지 않는다.

## 3. 관측 구성

### 3.1 후보 관측 자세

동·서·남·북 정면 관측은 기본 구성에서 제외하고, 중앙 상부와 네 대각선 사선 관측을 후보로 사용한다.

| View ID | 위치 | 주요 목적 |
|---|---|---|
| V0 | 보드 중앙 상부 | 전체 Grid, 윗면, 기본 높이맵 확인 |
| D1 | 북서 사선 | 북쪽·서쪽 측면 및 가림 보완 |
| D2 | 북동 사선 | 북쪽·동쪽 측면 및 가림 보완 |
| D3 | 남동 사선 | 남쪽·동쪽 측면 및 가림 보완 |
| D4 | 남서 사선 | 남쪽·서쪽 측면 및 가림 보완 |

```text
D1(북서)                 D2(북동)
          \             /
            [ V0/보드 ]
          /             \
D4(남서)                 D3(남동)
```

V0·D1~D4를 확정 알고리즘의 관측 자세 집합으로 사용한다. 초기 시험에서는 다섯 View를 모두 촬영해 각 방향의 실제 기여도를 측정한다. 여러 시점의 블록 mask를 그대로 합치지 않고 Board 좌표로 변환한 블록 후보를 통합한다. 실제 pose·관측 순서·접근 경로는 Robot 담당이 확인한 후 승인한다.

### 3.2 J6 장착 카메라의 제약

D435i 한 대가 로봇에 장착되어 있으므로 여러 시점은 동시에 촬영되지 않는다. 따라서 다중 시점 융합 중에는 조립물이 움직이지 않아야 한다.

- 각 자세에서 Robot이 완전히 정지한 후 촬영한다.
- 사람은 Robot 관측 이동 전에 위험영역에서 이탈한다.
- 각 프레임에 촬영 시각, View ID, Robot pose와 Calibration version을 연결한다.
- 각 Depth를 카메라 거리가 아니라 `assembly_board_frame`의 높이로 변환한다.
- 관측 중 구조물이 움직였으면 서로 다른 시점의 결과를 하나로 합치지 않고 해당 관측 batch를 실패 처리한다.
- Perception은 원하는 카메라 View ID와 품질 결과를 제공하고, joint/TCP/속도·경로 생성은 Robot 담당이 수행한다.

## 4. 확정 알고리즘과 선정 근거

**YOLO Segmentation + D435i Depth/Grid 검증 + 다중 시점 관측 + 이전 조립 상태 추적**을 하나의 관측 파이프라인으로 사용한다.

| 구성 | 역할 | 선택 이유 |
|---|---|---|
| YOLO Segmentation | 보이는 블록의 mask와 종류·색상 클래스 검출 | 맞닿은 블록과 배경에서 블록 후보 영역을 얻기 위함 |
| D435i Depth/Grid 검증 | Board 기준 높이로 layer를 계산하고 위치·크기·방향 검증 | RGB mask만으로 알 수 없는 실제 높이와 Grid 배치를 확인하기 위함 |
| 다중 시점 관측 | D435i 한 대를 V0·D1~D4로 이동하여 반사·가림 보완 | 특정 시점에서 불확실한 블록을 다른 시점에서 확인하기 위함 |
| 이전 조립 상태 추적 | 단계별 추가·제거·이동 후보 확인 및 확인된 아래층 정보 유지 | 현재 가려진 블록과 같은 색 적층 구조를 시간 순서로 추적하기 위함 |

### 4.1 YOLO Segmentation과 학습 클래스

학습 클래스는 다음 네 가지로 고정한다.

- `yellow_2x2`
- `yellow_2x3`
- `blue_2x2`
- `blue_2x3`

RGB 이미지에 보이는 블록별 instance mask와 클래스 정답을 라벨링한다. RGB-D를 함께 기록하되 YOLO 입력은 RGB이고, Depth는 후처리 검증에 사용한다. 층수와 방향은 별도 학습 클래스로 늘리지 않고 Depth/Grid로 검증한다.

**장점:** 블록별 후보 mask와 네 종류를 함께 얻고, 그림자·배경·인접 블록에 대한 학습 사례를 반영할 수 있다.

**한계:** 실제 촬영 환경의 mask 라벨링과 학습이 필요하다. 같은 색으로 맞닿거나 포개진 블록은 경계가 모호할 수 있고, 완전히 가려진 아래 블록은 검출할 수 없다. 반사로 RGB가 포화되면 검출이 실패할 수 있다.

### 4.2 D435i Depth/Grid 검증

RGB에 정렬한 Depth에서 mask 내부의 유효한 점을 추출한다. 내부 파라미터로 3D 좌표를 구한 뒤 `assembly_board_frame`으로 변환하여 Board 평면 대비 높이와 footprint를 계산한다. 알려진 brick 높이·stud 간격·허용 방향으로 종류·위치·layer·방향을 검증한다.

**장점:** YOLO 오분류나 mask 오차를 기하 제약으로 확인하고, RGB만으로 판단하기 어려운 층을 측정할 수 있다.

**한계:** 사선 촬영의 raw Depth는 수직 높이가 아니다. 보정 오차·Depth 누락·경계 노이즈가 크면 layer를 확정하지 않는다. 홀 채우기로 생성된 값만으로 층을 확정하지 않는다. 관측된 면과 가림을 고려해야 하므로 mask 면적을 곧바로 실제 footprint로 해석하지 않는다. 2×2의 회전 대칭은 팀의 방향 정규화 규칙으로 처리한다.

### 4.3 다중 시점 관측과 결과 통합

각 View의 mask·클래스·Depth/Grid 검증 결과를 Board 좌표로 변환한 후 위치·layer·footprint·클래스 일관성을 이용해 동일 블록 후보를 연결한다. 같은 블록을 여러 번 세지 않고 View별 근거를 유지한다.

**장점:** 한 View의 반사·가림을 다른 View로 보완하고 관측 결과를 교차 검증할 수 있다.

**한계:** 장착 보정과 Robot pose가 부정확하면 서로 다른 블록을 합치거나 하나의 블록을 중복 집계할 수 있다. 시점 간 장면은 정적이어야 한다. 모든 View에서 가린 영역은 여전히 미확인이다. 이동·촬영으로 처리시간이 늘어난다.

### 4.4 이전 조립 상태 추적

매 사이클 기존 블록을 포함한 전체 보드를 다시 관측한다. 직전 Backend 채택 상태 또는 채택이 확인된 추적 상태와 이번 관측을 비교한다. 같은 색 블록이 포개진 경우 YOLO는 보이는 블록을 인식하고, Board 기준 높이 변화와 이전 확정 상태로 아래층을 추적한다.

**장점:** 이미 확인한 아래층 정보를 유지하며 단계별 추가·제거·이동 후보를 찾을 수 있다.

**한계:** 이전 오인식이 누적될 수 있다. 미채택·실패 관측으로 확정 추적 상태를 덮어쓰지 않는다. 보이지 않는다는 이유만으로 제거하지 않고, 실제 제거 근거가 부족하면 `OCCLUDED/UNKNOWN`으로 유지한다. 기록이 없는 아래층의 종류·색상은 높이만으로 확정하지 않는다.

### 4.5 학습·측정 계획

- V0·D1~D4, 네 클래스, 1~5층, 같은 색 접촉·적층, 조명·반사·가림 사례를 수집한다.
- RGB instance mask 정답과 Depth/Grid·layer 정답을 구분해 준비한다.
- 동일 조립 장면의 연속 프레임이 train과 validation에 섞이지 않도록 장면 단위로 분리한다.
- 학습에 사용하지 않은 조립 장면으로 mask·클래스와 최종 상태 정확도를 평가한다.
- 모델 버전·클래스 순서·촬영 조건·Calibration version을 기록한다.
- 데이터 수량·모델 버전·confidence 임계값은 실제 시험 후 확정한다.

### 4.6 확장 기능과 적용 한계

Voxel 융합은 좌판 아래 빈 공간과 복잡한 3D 점유 구조를 명시적으로 표현해야 할 때 추가하는 확장 기능이다. Day 4 기본 파이프라인은 블록별 mask와 Depth/Grid 검증 결과 통합으로 구성하며 voxel 구축을 필수 조건으로 두지 않는다.

> 확정 조합으로 보이는 블록을 인식하고 Depth/Grid·다중 시점·이전 상태로 검증한다. 복잡한 내부 공간 표현이 필요하면 voxel 융합을 확장하고, 반사·가림 또는 시점 간 충돌로 확인하지 못한 상태는 `UNKNOWN`으로 보고한다.

실제 인식 성능은 학습 결과와 D435i 측정 시험으로 검증한다. 사진만으로 하부 Depth 확보나 개별 블록의 완전한 분리를 보장하지 않는다.

## 5. 제안 처리 흐름

```text
Backend/HMI 관측 요청
→ 사람 이탈 확인·Robot이 승인된 V0·D1~D4로 이동
→ 각 자세에서 정지 후 RGB-D 촬영
→ YOLO Segmentation으로 mask·종류 검출
→ D435i Depth와 Grid로 위치·높이·layer·크기·방향 검증
→ 여러 시점의 동일 블록 결과 통합
→ 이전 확정 상태와 비교하여 추가·제거·이동 및 아래층 추적
→ CurrentAssemblyState 관측 결과 생성
→ 정상 또는 PARTIAL/UNKNOWN·오류와 근거를 Backend에 전달
→ Backend가 Current 채택 또는 기존 Current 유지
```

사용자가 정의한 `CurrentAssemblyState`는 이 파이프라인의 조립 상태 관측 결과를 뜻한다. 기존 저장소의 Backend 전달 객체 `Observed`와 의미를 연결해 본 문서에서는 **CurrentAssemblyState(Observed)**로 설명한다. 실제 클래스명·Schema 이름은 Backend와 합의하되, 최종 Current 채택 책임은 Backend에 둔다.

매 사이클마다 이전 블록도 관측 대상에 포함한다. 변화가 없는 영역은 직전 상태와 일관성을 확인하고, 변화 영역은 정밀 판정한다. 새 블록 때문에 이전 블록이 보이지 않는 경우 제거로 단정하지 않고 `OCCLUDED` 또는 `UNKNOWN`으로 표시한다.

## 6. 촬영 및 전송 시점 제안

현재 문서는 초기 빈 보드 관측, 반복적인 Observed 제공, Robot 전달과 사람 조립 완료의 분리만 확정하고 있으며 자동 촬영 조건은 미정이다. J6 장착 D435i 구성에는 다음 event-driven 방식을 제안한다.

### 6.1 최초 관측

1. Assembly Board를 비운다.
2. Robot이 V0로 이동해 정지한다.
3. 빈 보드의 RGB-D와 Board 보정을 확인한다.
4. 초기 `Observed`를 Backend로 전달한다.

### 6.2 조립 사이클 관측

1. Robot이 필요한 블록을 전달한다.
2. 전달 완료는 조립 완료로 처리하지 않는다.
3. 사람이 Assembly Board에 블록을 조립한다.
4. MVP에서는 사람이 HMI의 `조립 완료`를 입력한다.
5. 사람의 손과 신체가 Robot 위험영역 및 Board 관측 영역에서 벗어났는지 확인한다.
6. Robot이 승인된 V0 관측 자세로 이동하고 완전히 정지한다.
7. V0의 RGB-D 여러 프레임이 안정될 때까지 수집한다.
8. Robot이 승인된 D1~D4로 순차 이동하고 각 자세에서 정지 후 촬영한다.
9. 각 View에서 YOLO mask·종류를 검출하고 Depth/Grid로 위치·높이·layer·방향을 검증한다.
10. 동일 블록의 여러 시점 결과를 통합하고 이전 상태와 비교해 이번 변화와 아래층 정보를 추적한다.
11. 근거가 충분하면 하나의 `Observed`를 Backend에 전달하고, 부족하면 `PARTIAL/UNKNOWN`과 원인을 전달한다.

초기 실험에서는 V0·D1~D4를 모두 사용한다. View별 기여도와 처리시간을 측정한 뒤, 특정 View를 제외해도 하부 구조·층·가림 판정이 유지된다는 증거가 있을 때만 촬영 수를 줄인다.

### 6.3 촬영 금지·보류 조건

- 사람 손 또는 Robot이 Assembly Board를 가리는 경우
- Robot 또는 카메라가 이동 중인 경우
- RGB와 Depth timestamp 동기화가 유효하지 않은 경우
- Board 보정이 유효하지 않은 경우
- 다중 시점 촬영 사이에 조립 상태가 변한 경우
- Depth 유효 픽셀이 부족하거나 결과가 관측 자세끼리 충돌하는 경우

이 경우 정상 `Observed`를 억지로 만들지 않고 `UNSTABLE`, `PARTIAL`, `CALIBRATION_ERROR`, `CAMERA_ERROR` 등의 상태와 사유를 전달한다. Backend는 기존 `Current`를 유지하고 다음 전달을 보류한다.

### 6.4 아직 합의가 필요한 촬영 조건

- 안정 상태로 볼 연속 프레임 수
- 허용할 위치·높이 변화량과 대기 시간
- HMI 버튼 외 손 제거 자동 감지를 MVP에 포함할지
- V0 실패 시 선택할 대각선 View 순서
- 한 관측 batch의 timeout
- 재촬영 횟수와 사람 확인 전환 조건

## 7. Backend 전달 데이터 형식 제안

최신 역할에 따라 Perception은 `Current`가 아니라 `Observed`를 보낸다. 아래 형식은 설계 제안이며 Backend 담당과 정상·invalid Fixture를 검토한 후 확정 Schema로 승격한다.

### 7.1 Integration envelope 제안

Backend가 현재 작업과 늦은 결과를 연결하기 위한 정보다. 실제 필수 필드와 발급 주체는 Backend 담당과 합의한다.

```json
{
  "job_id": "job_001",
  "design_version": "design_v1",
  "plan_version": "plan_v1",
  "step_id": "step_03",
  "delivery_execution_id": "delivery_003",
  "payload": {}
}
```

Perception 핵심 계산은 이 envelope 없이 저장 이미지 Fixture로도 실행할 수 있어야 한다.

### 7.2 Observed payload 제안

```json
{
  "observation_id": "obs_0007",
  "sequence": 7,
  "captured_at": "2026-10-05T10:30:12.350+09:00",
  "calibration_version": "calib_01",
  "frame_id": "assembly_board_frame",
  "status": "COMPLETE",
  "views": [
    {
      "view_id": "V0",
      "captured_at": "2026-10-05T10:30:11.900+09:00",
      "rgb_depth_synchronized": true,
      "calibration_valid": true
    }
  ],
  "blocks": [
    {
      "observation_block_id": "ob_001",
      "geometry": "2x3x1",
      "color": "YELLOW",
      "grid": {
        "x": 10,
        "y": 12,
        "layer": 1
      },
      "orientation_deg": 90,
      "visibility": "VISIBLE",
      "evidence": "DIRECT",
      "confidence": {
        "geometry": 0.96,
        "color": 0.99,
        "position": 0.94,
        "layer": 0.91,
        "orientation": 0.89
      }
    }
  ],
  "unknown_regions": [],
  "errors": []
}
```

### 7.3 상태와 근거 표현 제안

| 필드 | 후보값 | 의미 |
|---|---|---|
| `status` | `COMPLETE` | 현재 비교에 사용할 수 있는 정상 관측 |
|  | `PARTIAL` | 일부 영역·속성만 판별 가능 |
|  | `UNSTABLE` | 손·움직임·시점 간 상태 변화 |
|  | `CALIBRATION_ERROR` | Board/Camera 좌표 보정 실패 |
|  | `CAMERA_ERROR` | RGB-D 입력·동기화 실패 |
| `visibility` | `VISIBLE` | 현재 RGB-D에서 직접 확인 |
|  | `OCCLUDED` | 이전에는 확인했지만 현재 가림 |
|  | `UNKNOWN` | 존재·속성을 확정할 근거 부족 |
| `evidence` | `DIRECT` | 현재 관측에서 직접 확인 |
|  | `MULTI_VIEW_FUSED` | 여러 시점의 현재 관측으로 확인 |
|  | `TEMPORAL_INFERENCE` | 이전 확정 상태와 변화로 추론 |

`TEMPORAL_INFERENCE`는 직접 보이는 블록과 구분해야 하며, Backend가 채택 정책을 결정할 수 있도록 근거와 confidence를 함께 보낸다.

### 7.4 Confidence 원칙

- 범위는 `0.00~1.00`, 소수점 두 자리 표현을 기본 제안으로 사용한다.
- geometry·color·position·layer·orientation별 confidence를 분리한다.
- 전체 confidence 계산식과 채택 임계값은 실제 시험 전 임의 확정하지 않는다.
- 낮은 confidence를 정상값 또는 빈 블록 목록으로 숨기지 않는다.
- `blocks: []`는 **정상 확인된 빈 보드**와 **관측 실패**에서 의미가 다르므로 반드시 `status`와 함께 해석한다.

## 8. 좌표·보정 요구사항

최소한 다음 변환과 설정이 필요하다.

```text
robot_base_frame
→ flange_frame(J6)
→ camera_color/depth_optical_frame
→ assembly_board_frame
```

- RealSense RGB/Depth 내부 파라미터와 Depth scale
- RGB와 Depth 간 정렬 정보
- 플랜지와 카메라 사이 Hand-Eye 변환
- Robot base와 Assembly Board 사이 변환
- Board 원점·X/Y/Z축·stud 간격·anchor 규칙
- brick 한 층의 실측 높이와 허용 오차
- View별 실제 pose, 시선 방향, Calibration version

기존 `Observation` posx/posj 기록은 단위·frame·회전·TCP/tool 확인 전 실행 설정으로 사용하지 않는다. 임의의 joint/TCP pose를 생성하지 않는다.

## 9. 오류 및 불확실성 처리

| 상황 | Perception 출력 | Backend 기대 처리 |
|---|---|---|
| 정상 전체 관측 | `COMPLETE` + blocks | 유효성 확인 후 Current 채택 후보 |
| 일부 블록 가림 | `PARTIAL`, `OCCLUDED/UNKNOWN` | 기존 Current 유지 또는 추가 관측 |
| 현재 블록을 아직 놓지 않음 | 안정 상태와 Step 문맥을 함께 전달 | 정상 조립 대기, 즉시 차이로 확정하지 않음 |
| 손이 화면에 있음 | `UNSTABLE` | 완료·다음 전달 보류 |
| Board 보정 실패 | `CALIBRATION_ERROR` | Current 유지·재보정 요청 |
| RGB-D 입력 실패 | `CAMERA_ERROR` | Current 유지·장치 확인 |
| 관측 자세 간 충돌 | `PARTIAL` 또는 `UNSTABLE` + 사유 | 자동 채택하지 않음 |
| 낮은 confidence | 항목별 낮은 값과 근거 | 재관측 또는 사람 확인 |

이전 관측의 촬영 시각·순번·Step 연결을 확인하여 오래된 결과로 다음 Step을 진행하거나 같은 조립을 두 번 완료 처리하지 않는다.

## 10. 확정 알고리즘의 검증 계획

### 10.1 Ground Truth 장면

- 빈 보드
- Yellow/Blue × `2×2×1`, `2×3×1`
- `2×3×1` 허용 방향별 배치
- 같은 위치의 1~5층 적층
- X/Y 위치 변경
- 블록 추가·이동·제거
- 같은 색 블록의 수직 적층
- 높은 블록 뒤의 낮은 블록
- 손·Robot 가림
- Depth 누락·RGB 포화·보정 실패
- V0 및 D1~D4 관측

원자료에서 `TBD`인 좌표·layer·방향은 사진만 보고 정답으로 확정하지 않고 실물 또는 조립 기록으로 확인한다.

### 10.2 평가 지표

| 지표 | 확인 내용 |
|---|---|
| Geometry accuracy | 2×2 / 2×3 구분 |
| Color accuracy | Yellow / Blue 구분 |
| Grid accuracy | anchor `(x,y)` 일치 |
| Layer accuracy | 합의된 layer 값 일치 |
| Orientation accuracy | 합의된 방향 표현 일치 |
| Exact state match | 한 관측의 전체 블록 상태 일치 |
| False accept | 틀린 상태를 높은 신뢰도로 정상 반환한 횟수 |
| Unknown quality | 실제 불확실 사례를 무리하게 확정하지 않는지 |
| Calibration repeatability | View가 달라도 동일 Grid로 변환되는지 |
| Cycle latency | 요청부터 Observed callback까지 걸린 시간 |
| Additional-view rate | V0 외 사선 관측이 필요했던 비율 |

False accept는 단순 미검출보다 우선적으로 줄인다. 미검출은 재관측할 수 있지만 잘못된 정상 상태는 불필요한 Difference·질문·재계획·Robot 전달로 이어질 수 있다.

정확도 목표, 반복 횟수, 시간 한도, confidence 임계값은 실험 전에 팀이 합의한다. 문서 검토나 Mock 결과를 실제 D435i 성능 검증으로 표시하지 않는다.

### 10.3 단계별 검증 기준

1. 네 클래스 YOLO mask·분류 성능을 학습에 사용하지 않은 장면에서 확인한다.
2. 빈 보드와 1~5층의 유효 Depth 분포, Board 좌표 오차와 layer 판정을 측정한다.
3. V0·D1~D4 통합 시 중복 블록·잘못된 연결·시점 간 충돌을 확인한다.
4. 같은 색 적층과 추가·제거·이동 장면에서 이전 상태 추적 오류를 확인한다.
5. 최종 CurrentAssemblyState(Observed)의 전체 일치율·False accept·UNKNOWN·처리시간을 평가한다.
6. voxel 확장은 복잡한 3D 공간 표현이 실제 요구될 때 별도 검토한다.

## 11. Day 1~4 구현·통합 제안

본 제안서의 일정 범위는 **10월 8일 Day 4 MVP까지**다.

### Day 1 — 계약과 Fixture

- Observed 최소 필드·정상·부분·실패 의미 합의
- Board grid·layer·orientation 규칙 합의
- 정상/invalid JSON Fixture 작성
- Backend callback 소비 예시 확인
- 네 학습 클래스·mask 라벨 규칙·촬영 및 장면별 데이터 분할 계획 확정

### Day 2 — 기본 알고리즘과 실기 준비

- 저장 RGB-D 입력 adapter와 YOLO·Depth/Grid·결과 통합·추적 로직 분리
- 네 클래스 RGB 촬영·instance mask 라벨링·초기 YOLO 학습 및 검증
- RGB/Depth 정렬·유효 Depth 검사
- Board 보정 및 빈 보드·1~5층 높이 분포 측정
- J6 Camera와 Board 좌표 보정 자료 기록
- mask 내부 Depth의 Board 좌표 변환·높이·Grid 검증
- V0·D1~D4 동일 블록 연결과 이전 상태 추적 준비

### Day 3 — 부분 통합

- Vision callback으로 Observed 전달
- Backend의 Current 채택·유지 확인
- YOLO→Depth/Grid→다중 시점 통합→이전 상태 추적 연결
- 같은 색 접촉·적층, 정상·가림·실패·낮은 confidence 처리
- 오래된 관측·중복 처리 Fixture 확인

### Day 4 — 전체 Cycle

- Robot 전달과 사람 조립 완료 분리
- HMI 완료 입력 후 승인된 Observation pose 촬영
- 정상 조립과 실제 변경에서 Observed 생성
- Backend 비교·보류·다음 진행 증거 기록

**Day 4 Gate — Perception MVP 연결:** 실제 D435i 입력으로 `Observed`가 생성되고, Backend가 정상 관측의 채택과 부분·실패 관측의 보류를 구분한다.

## 12. 결정 필요 사항

설계 확정을 위해 홍동·수현·세은 및 관련 담당자가 다음을 합의해야 한다.

1. Board 원점·축·anchor·layer 시작 번호·방향 표현
2. Observed의 필수 필드·enum·직렬화·callback 또는 Topic 관계
3. HMI 완료 입력과 손 제거·안정 프레임의 결합 방식
4. confidence 계산식·채택 임계값·재관측 조건
5. V0·D1~D4 촬영 순서, 초기 필수 View와 최적화 후 최소 View 수
6. `OCCLUDED`, `UNKNOWN`, `TEMPORAL_INFERENCE`의 Backend 채택 정책
7. 다중 시점 중 장면 변화 검출 및 batch 폐기 기준
8. 실제 pose·작업공간·충돌·속도·사람 이탈 안전 절차
9. Ground Truth 장면·반복 횟수·성공률·시간 한도
10. YOLO 모델 버전·mask 라벨 규칙·학습 데이터 분할·학습시간
11. CurrentAssemblyState와 Observed의 실제 Schema 명칭 및 채택 상태 전달 방식

## 13. 설계 결론

Assembly Board 관측 알고리즘은 **YOLO Segmentation + D435i Depth/Grid 검증 + 다중 시점 관측 + 이전 조립 상태 추적**으로 확정한다. 네 클래스의 보이는 블록을 학습으로 인식하고, mask에 대응하는 Depth를 Board 기준으로 변환하여 위치·크기·방향·layer를 검증한다. V0·D1~D4 결과를 통합하고 이전 확정 상태와 비교하여 확인된 아래층 정보를 유지한다.

반사·가림·유효 Depth 부족·결과 충돌은 `UNKNOWN`으로 처리한다. voxel 융합은 복잡한 3D 공간 표현을 위한 확장 기능으로 둔다. 구성은 확정되었으나 실제 성능과 임계값은 학습·측정 시험으로 검증해야 한다.

일정 범위는 **10월 8일 Day 4까지**이며 데이터 수집·라벨링·학습이 포함된다. 학습시간이나 Depth 품질이 목표를 충족하지 못하면 미검증 범위와 제한을 기록하고 정상 성능을 확보했다고 보고하지 않는다.

## 14. 근거 문서

- [README](../README.md)
- [최신 결정과 남은 확인](00_CURRENT_DECISIONS.md)
- [Day 1~4 개발·통합 일정](01_DAY_PLAN.md)
- [팀원 협업·독립 개발 안내](02_TEAM_GUIDE.md)
- [장치·좌표·실측 확인](03_MEASUREMENT_GUIDE.md)
- [공통 입출력 계약 초안](06_CONTRACT_DRAFT.md)
- 2026-10-05 사용자 확정 사항: YOLO Segmentation + D435i Depth/Grid 검증 + 다중 시점 관측 + 이전 조립 상태 추적

</details>
