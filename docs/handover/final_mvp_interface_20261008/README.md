# 최종 통합 MVP 인터페이스 배포 문서

> 2026-10-11 수현 재확인: 이 문서의 B 상태·비교 책임을 최신 1차 통합 기준으로 사용합니다. 공통 block layer는 정수 1~5입니다. 코드 연결 완료 여부와 HMI·DB 실제 검증은 [1차 통합 안내](../../D_HMI_DB_ROUND1.md)에 구분합니다.

기준일: 2026-10-08 · 인터페이스 최종 결정·버전 관리·배포 담당: **D 수현**

이 대화의 최신 사용자 결정을 반영한 문서 기준본이다. 아래 책임·호출 의미는 확정 사항이며, JSON의 새 봉투·필드명과 함수 연결 위치는 **문서용 매핑 초안**이다. 런타임 Schema·코드·DB 구조·로봇 설정에 적용하거나 실제 모듈을 연결·시험했다는 뜻이 아니다. 배포 날짜는 문서 식별이며 메시지마다 새 version/hash/generation을 요구하지 않는다. 이전 Day4·v4 원본과 시험 기록은 당시 근거로 보존한다.

## 1. 책임과 전체 연결

| 담당 | 최종 책임 | 경계 |
|---|---|---|
| C 시율 | 설계 대화·수정 중 설계 제공·사용자 승인·차이의 의도 확인 | 승인 설계는 C→A. HMI 버튼으로 설계를 승인하지 않음 |
| A 세은 | 계획·작업 방식·도움·경로 계산, A 연결 어댑터 | 계획 생성·갱신 때 동일 자료를 B와 D에 제공. 계산 결과는 실행권 없는 후보 |
| B 홍동 | 관측·Expected 구성·전체 관측 가능 영역 비교·실제 Current 확정·revision 관리 | D가 지정한 검사만 수행. 실행 Step 선택·다음 Step 진행은 하지 않음 |
| D 수현 | 실행 Step·로봇 실행·B 검사 요청·결과에 따른 진행/재검사/C 호출/변경 대기 | 공간 비교·Current 재채택·revision 발급은 하지 않음 |
| D 수현 | HMI·제스처 생산·기존 JSONL→DB·웹 연결, 인터페이스 최종 결정·버전 관리·배포 | B 전용 DB·저장 경로를 추가하지 않음 |

```text
사용자↔C 설계 대화 ── 수정 중 설계 ──→ D/HMI 수정 화면
  └─ 대화에서 승인 → C→A 전체 계획 계산·검증
                          ├─ 동일 Design/Plan/기준 Current/좌표·형상 기준 → B
                          └─ 동일 자료 + 작업·도움 후보 → D/HMI 승인 설계
D 실행 조건 확인 → A 직전 재평가 → A Step 경로 후보 → D 자동 승인·실행
  → supply board 집기 → assembly board 직접 결착 (필요한 도움/사람 조립 분기)
  → D→B 지정 검사 → B 관측·비교·Current 확정 → B→D 검사 결과
     ├─ MATCH → D 해당 Step 한 번 완료·자동 다음 공정
     ├─ MISMATCH → D 보류·C 의도 확인 → KEEP / REVISE / UNCLEAR
     └─ UNOBSERVABLE → D 보류·새 check_id로 재검사
모든 계획 블록 사용 → B 최종 검사·D 조립 종료 판단 → D JSONL→DB→사용자별 웹
```

수정 중 설계는 실행 중인 승인 설계를 덮어쓰지 않는다. 실행 중 수정안이 도착해도 자동 재계획·로봇 실행의 근거가 아니다. 실행 목표를 바꾸는 전환은 기존 실행/검사를 닫고 승인 후 새 계획을 채택하는 경계에서 한다. 수정 중 계속 실행할 수 있는 범위는 구현 전 확인하며 임의 동시 실행 정책을 추가하지 않는다.

## 2. 재사용 객체와 기준

| 객체 | 재사용할 형태·의미 |
|---|---|
| Design | `design_version, blocks` 전체 목표. C 발급, D는 승인·실행 목표 연결을 관리 |
| Plan | `plan_id, design_version, base_current_revision, steps` 그대로 사용 |
| Step | `step_id, operation, before, after, prerequisites, requires_delivery` 그대로 사용. 작업 방식·도움·경로 후보는 v4 자료에서 연결하며 Step 필드를 조용히 재해석하지 않음 |
| Current | `current_revision, blocks`. **B가 확정·발급**. D는 받은 자료를 표시·전달·기록 |
| Expected | 고정 `plan_base_current` + 검사 대상까지의 Step 목표 효과. 계산·비교는 B |
| Difference | 기존 `missing, unexpected, unobservable` 한 객체 재사용 |
| 관측 근거 | 기존 `observation_seq, visible_blocks, verified_regions, reason` 의미 재사용. B 내부 추적을 새 관측으로 표시하지 않음 |

배치는 `brick_type, color, x, y, layer, orientation_deg` 여섯 필드와 개수로 다룬다. 현재 공통 범위는 4점 `2x2x1`·6점 `2x3x1`, yellow/blue, 24×24 stud, layer 1~5다(층 상한은 2026-10-11 통합 정합 반영). x/y는 회전 후 점유 영역 최소 모서리, 0~23 정수이며 footprint 전체가 판 안에 있어야 한다. 사진 기준 +X 오른쪽·+Y 위. 4점 방향은 0, 6점은 0/90도(0도 X2/Y3, 90도 X3/Y2). 이 값은 Robot TCP 좌표가 아니다.

Expected의 기준 Current는 Plan 시작 시 고정한 사본이다. 같은 Plan에서 r0→r1→r2로 실제 Current가 바뀌어도 baseline을 교체하지 않는다. 이전 완료 Step과 현재 검사 Step의 효과만 포함하며 미래 Step은 제외한다. INITIAL은 초기 실제 상태 확인, STEP은 해당 단계 Expected, FINAL은 누적 Step 효과와 승인 Design 전체의 정합성을 검사한다. FINAL에서 둘이 다르면 목표/계획 오류로 보류하며 비교 기준을 몰래 교체하지 않는다.

새 Plan은 B가 확정한 최신 Current로 계산·시작한다. `base_current_revision`은 계산에 쓴 값이며 수신 시 최신값으로 덮어쓰지 않는다. 계산 중 Current가 달라진 새 후보는 채택 보류·최신 기준 재계산 대상이다. 정상 Step 진행으로 revision이 증가한 것은 같은 Plan을 폐기할 이유가 아니다.

## 3. 핵심 계약 ① A→B·D 계획 공유

| 항목 | 계약 |
|---|---|
| 입력/출력 | 기존 승인 Design·Plan·고정 Plan 기준 Current 전체 사본, 좌표·블록 형상 기준. 작업 방식·도움 후보는 기존 v4 결과에 연결 |
| 호출 시점 | 최초 전체 계획·재계획의 생성/갱신 결과가 유효할 때 A 어댑터가 B·D 양쪽에 동일 계획 자료 전달 |
| 동일성 | 같은 plan_id/design_version/base_current_revision/Step 내용/기준 Current/좌표·형상 기준. B 전용으로 Plan을 수정하지 않음 |
| B 처리 | Plan 자료를 검사하고 비교 기준 보관. 공유만으로 촬영·Current 갱신·Step 진행하지 않음 |
| D 처리 | 활성 계획 요청·사용자 승인·기준 revision·Plan/작업 후보의 유효성을 확인하고 실행 조건 관리 |
| 실패 | 잘못된 Plan·버전/기준 충돌·한쪽 전달 실패는 실행 보류. B가 계획을 못 받았으면 해당 검사를 PLAN_NOT_FOUND 오류로 반환 |

별도 모델 준비 ACK는 추가하지 않는다. 기존 함수 반환·오류·콜백으로 전달 성공/실패를 다루며, B의 계획 누락 오류로도 실행을 보류한다. 새 Current 조회 API 없이 B의 초기/최근 유효 검사 결과를 A의 기준 입력으로 전달한다. C가 승인 설계를 A에 주어도 실제 기준 Current가 없으면 D가 INITIAL 검사를 요청해 확보한 후 계획을 계산한다. 빈 배열을 초기 관측 성공으로 대신 넣지 않는다.

## 4. 핵심 계약 ② D→B 검사 요청

| 항목 | 계약 |
|---|---|
| 최소 연결 | 기존 `check_id`와 검사 종류, `plan_id, step_id`. Job은 기존 호출 문맥으로 연결; 별도 봉투가 필요할 때만 job_id 사용 |
| INITIAL | Plan 생성 전 초기/정리 상태 확인. plan_id=null, step_id=null. Step 완료로 사용하지 않음 |
| STEP | 활성 Plan의 지정 Step 완료 검사. plan_id·step_id 모두 필수 |
| FINAL | 활성 Plan 전체·승인 Design·누적 확인 근거 검사. plan_id 필수, step_id=null |
| 시점 | INITIAL은 계획 기준 확보가 필요할 때, STEP은 로봇/사람 작업 뒤 검증된 관측 자세·정지 조건을 만족했을 때, FINAL은 필요한 모든 Step 확인 뒤 |
| 재검사 | 같은 Step도 새 check_id. 한 검사 요청당 하나의 최종 결과, B 내부 다중 View/재관측은 그 요청에 묶음 |
| 금지 | B가 촬영 결과로 실행 Step을 추정·변경하거나 D 요청 없이 다음 Step 검사로 전환 |
| 실패 | 입력 오류·Step/Plan 누락·처리 실패·카메라 관측 불가를 구분. 실패를 MATCH·빈 정상 상태로 반환하지 않음 |

요청할 때 식별·대상을 고정하고 결과 수신 시 현재 Step을 뒤늦게 붙이지 않는다. 검사 재요청은 이전 check를 닫은 뒤 새 check로 연다. D는 기존 완료 Step 기록을 이용해 대상 순서를 지정하며, B는 Plan의 해당 prefix로 Expected를 구성한다. D가 Expected 블록 목록을 다시 계산해 B에 보내는 구조는 추가하지 않는다.

## 5. 핵심 계약 ③ B→D 검사 결과

| 정보 | 의미 |
|---|---|
| 요청 연결 | 원래 check_id·검사 종류·plan_id·step_id 반환 또는 원래 호출 문맥 유지. 예시에서는 명시 필드 사용 |
| Current | B 내부 관측·비교·확정을 마친 실제 Current와 current_revision. D 채택 회신을 기다리지 않음 |
| 판정 | 기존 comparison의 MATCH / MISMATCH / UNOBSERVABLE 의미 재사용. 업무 실패에는 정상 판정을 넣지 않음 |
| Expected | 실제 비교한 Plan 기준·대상과 blocks. INITIAL은 계획 비교 전이므로 null |
| 차이 | missing=확인된 목표 누락, unexpected=확인된 예상 밖 배치, unobservable=확인할 수 없는 대상. 같은 근거를 missing과 unobservable 양쪽에 넣지 않음 |
| 관측 근거 | 이번 관측에서 읽은 블록·확인 영역·촬영 순번·가림/품질 사유. 기존 확인 이력은 Current에 유지하되 visible_blocks에 새 검출로 넣지 않음 |
| 실패 | 원인 코드·사유. 카메라 관측 불가와 INVALID_INPUT / PLAN_NOT_FOUND / PROCESSING_FAILED를 구분 |

문서용 예시에서 `status=OK`는 처리가 정상 끝났다는 뜻이고 `comparison=MATCH`와 다르다. `status=UNOBSERVABLE`은 필요한 관측 근거가 부족함, `status=ERROR`는 입력/계획/처리 오류, `status=CANCELED`는 취소 경계 완료다. 새 오류명·봉투명은 매핑 초안이며 기존 오류 의미를 우선 연결한다.

B는 실제 확정 배치가 달라졌을 때만 revision을 한 번 증가시킨다. 동일 상태 재관측·가림·로봇 전달·검사 번호만 바뀐 경우는 증가시키지 않는다. 순수 관측 불가 결과에서는 기존 Current를 유지하고 unobservable과 사유를 반환한다. 오류·취소 결과는 Current 갱신 없음이며 예시의 current/expected/difference/observation은 null이다. null을 빈 정상 자료로 해석하지 않는다.

D는 활성 Job·check·Plan·Step·검사 종류와 결과의 대응, 중복·취소·종료 여부를 확인한다. 유효 결과의 B Current/revision을 화면·로그·후속 A/C 입력에 전달한다. **D가 공간 비교·블록 병합/삭제·Current 채택·revision 재발급을 반복하지 않는다.** 구조·대응 검사와 공간 의미의 재판단을 구분한다.

## 6. 전체 조립판 비교와 관측 한계

B는 최종 Design, 현재 단계 Expected, 이전 확인 Current를 함께 참고해 **관측 가능한 조립판 전체**를 비교한다. 현재 목표 블록 하나가 맞아도 다른 위치·색상·층의 추가 블록, 기존 구조의 이동·제거·색상 변화가 확인되면 MISMATCH다. 아직 실행하지 않은 미래 목표 블록도 현재 Expected에 없으면 예상 밖 배치로 보고한다.

격자/색상/높이 또는 3D 모델 비교 방법은 B 구현에서 선택한다. verified_regions는 이번에 실제 점유/빈 상태를 확인한 영역이며 검출 누락 자체를 빈 공간 증거로 삼지 않는다. 과거에 확인한 가려진 아래층은 이력으로 유지할 수 있다. 가림만으로 전체 Current를 지우거나, 보이지 않는 변경을 확인했다고 단정하지 않는다.

현재 목표는 읽을 수 있고 아래층만 가려졌다면 이전 확인 근거를 유지하며 MATCH가 가능하다. 검사가 요구하는 근거가 부족하면 UNOBSERVABLE이다. 관측 가능한 다른 영역에 확실한 변경과 가림이 함께 있으면 MISMATCH와 unobservable을 함께 반환할 수 있으나 완료·다음 실행은 금지한다. B는 확인된 변경만 Current에 반영하고 숨은 영역은 이력으로 남긴다. C에는 확인된 차이와 관측 한계를 함께 전달한다. 기존 C 변환 함수가 unobservable을 거부하는 점은 후속 연결 과제이며 이번 문서로 해결됐다고 보지 않는다.

## 7. STOP·재계획 취소와 늦은 결과

늦은 결과를 D가 무시하는 것만으로 B의 뒤늦은 Current 갱신을 막을 수 없다. 다음 **취소 의미**를 B·D 연결에 함께 적용한다. 구체적 함수명/콜백 위치는 기존 연결에서 매핑한다.

1. D는 STOP·재계획·검사 교체 시 활성 check를 즉시 로컬에서 닫고 B에 같은 check_id의 취소를 전달한다. 새 실행은 보류한다.
2. B는 같은 Job의 검사 확정과 취소를 순서화한다. Current/revision을 확정하기 직전에 활성 여부를 다시 확인하며, 취소 경계 뒤 완료된 계산은 Current·revision·확인 이력을 갱신하지 않는다.
3. B의 취소 처리 완료는 더 이상 해당 check로 상태를 쓸 수 없다는 뜻이다. 계산 thread의 물리 종료까지 기다릴 필요는 없지만 그 결과의 확정 권한은 닫혀 있어야 한다. 기존 취소 호출의 반환/콜백으로 알리고 새 서비스·모델 준비 ACK를 추가하지 않는다.
4. 취소 처리 실패/응답 불명은 경계 미확인으로 보류한다. D는 새 기준 Plan이나 재개 실행을 시작하지 않는다. 카메라 UNOBSERVABLE로 바꾸지 않는다.
5. B 확정이 취소보다 먼저 끝났으면 그 확정은 되돌리지 않는다. 늦은 옛 결과로 D가 진행하지는 않으며, 취소 경계 확인 후 새 check의 초기/상태 확인 결과로 B 최신 Current를 확보해 재계획한다. Current 조회 API나 D 재채택으로 보정하지 않는다.
6. 새 검사·계획은 기존 check와 다른 ID를 사용한다. 동일 결과 재수신은 Current/revision·완료 Step·로봇 명령을 다시 만들지 않는다. 동일 check_id의 서로 다른 결과는 정상 재검사로 수용하지 않고 충돌로 보류한다.

새 Plan 자료 공유만으로 옛 검사가 자동 취소됐다고 간주하지 않는다. 검사 취소 완료와 실제 로봇 정지는 별도 경계다. 위 순서화·취소 기능은 **구현·경쟁 상황 시험 전**이다. Robot lease/generation을 B 검사 메시지에 복제하지 않고 check_id·활성/종료 기록으로 필요한 경계를 만든다.

## 8. 의도·진행·HMI·이력

| 상황/연결 | 처리 |
|---|---|
| D→C 의도 요청 | 실제 B Current/revision, 해당 단계 B Expected, 기존 승인 Design, B Difference와 관측 한계, 기존 질문 식별 전달 |
| C→D KEEP | 기존 목표 유지. 실제 상태가 계획을 만족한다는 뜻이 아님. 필요하면 사람 정리→B 새 검사 또는 같은 목표+최신 B Current로 A 재계획 |
| C→D REVISE | 수정 의도 접수 후 변경 대기. 이 응답 즉시 완성 Design을 필수로 요구하지 않음 |
| REVISE 이후 | C 대화·수정 중 설계 제공→사용자 승인→기존 C→A→B·D 계획 공유→D 새 계획 채택. 미승인 초안을 실행하지 않음 |
| C→D UNCLEAR | 재질문/명시 선택 대기. 자동 KEEP·무응답 시간 경과 승인 없음. 호출 실패와 구분 |
| 정상 STEP MATCH | D 해당 Step 한 번 완료 후 다음 실행 조건 확인·자동 진행. Step별 사용자 승인 버튼 없음 |
| UNOBSERVABLE | 완료/다음 실행 보류, 사유 표시·새 검사. 재검사로 로봇 이동을 무제한 자동 반복하지 않음 |
| ERROR / C 실패 | 원인 보존·보류. 관측 불가·UNCLEAR·성공으로 대체하지 않음 |
| HMI | 수정 중 Design / 실행 중 승인 Design을 별도 표시. B 판정·Current revision·관측 한계와 D 실행/검사/의도/변경/정지 상태 구분 |
| HMI 입력 | 시작·안전 정지·재개·홈 복귀는 기존 실행 조건에 따름. 설계 승인은 C 대화에서만 수집. 도움 준비 응답과 설계/Step 승인을 구분 |
| D 제스처 | D가 생산하고 활성 도움/전달 요청에 연결·유효성 확인. 제스처 자체로 조립 완료·Current를 확정하지 않음 |
| JSONL→DB→웹 | D가 계획 원문·검사 결과·B Current/revision·의도 응답·수정/승인/계획 변경·완료 이력을 기존 흐름으로 전달. 사용자–Job 소유권을 따라 웹 조회 |

승인 이후 A의 계산 검증과 D의 실행 조건 확인은 사용자 설계 승인과 다른 절차다. 최종 종료는 ①계획 Step에 필요한 블록 사용/작업 소진 ②B FINAL 결과·누적 확인에 근거한 D 조립 종료 ③D DB 저장·사용자별 웹 반영으로 구분한다. 빈 Plan·그리퍼 성공·DB 저장만으로 조립 완료를 만들지 않는다. 저장 실패는 별도 상태로 남기며 로봇 재실행 원인이 아니다. 기존 DB 적재 호환성·사용자 소유권·웹 연결은 확인 필요다.

## 9. A–D v4와 Robot 경계 유지

| 계산/실행 | 유지할 기준 |
|---|---|
| 전체 계획 | 기존 `plan_assembly_from_current(design, current, assembly_context)` 계산. A 어댑터가 동일 계획 자료를 B·D에 공유 |
| 실행 직전 재평가 | 기존 `assess_step(design, plan, step_id, current, context)` 방향. B 최신 Current와 고정 Plan baseline 구분 |
| Step 경로 | 기존 `plan_step_motion(...)` 제안 경계 유지. 예약 슬롯·RobotState·frame/geometry 기준의 경로 후보; 구현 확인 필요 |
| 실행 권한 | 후보 수신만으로 실행 없음. D가 Plan/요청·B 상태·재평가·예약·경로·도움·실제 Robot 조건 확인 뒤 **자동 승인·진행**. 매 Step 사용자 승인 요구 없음 |
| 공급 예약 | 슬롯 예약/부품 확인·유효성·집기 결과·불확실 상태 유지. 계산 성공만으로 슬롯 소모하지 않음 |
| pre-contact | 실제 목표 도달·정지·파지 유지·명령 비움 근거 확인. SUCCEEDED 문자열이나 ACK만으로 Contact 시작하지 않음 |
| Contact | Motion 실행권 무효화→Contact 인계 적용 확인→최신 조건 재검사→D Contact. v4의 필요한 lease·예약 경계는 Robot 쪽에 유지 |
| 도움 | 사전 안내와 해당 도움 요청의 준비를 구분. 운반 경로 밖 손, pre-contact 정지 뒤 준비·실행 알림, 체결/구조 확인 뒤 해제 |
| 실패/STOP | 파지/구조/실제 정지 확인·D Recovery 검토. 자동 개방·무조건 손 해제·자동 재실행 없음 |
| 사람 조립 | 전달판 도착·정지·정상 해제/철수→사람 작업→D 요청 B 검사. 전달·사람 응답은 조립 완료 아님 |

v4 원본의 후보/실행 분리·실제 상태·슬롯·Contact·도움 경계는 유지한다. 원본의 D Current 채택/비교 문구는 이번 B 책임으로 대체한다. 원본의 별도 실행 승인은 D의 조건 확인을 통한 자동 승인으로 해석하며 사용자 매회 승인을 추가하지 않는다. 새로운 공통 hash/버전/세대·모델 ACK·Current 조회·D 채택 회신·서비스·큐·DB 테이블은 추가 요구가 아니다.

v4의 `expected_current_before_step`에는 첫 Step이면 고정 baseline, 이후에는 직전 정상 B 검사에서 받은 Expected를 재사용한다. D가 공간 목표를 새로 계산하지 않는다. A 어댑터의 Plan 재현·후보 타당성 검사는 계획 책임으로 유지하며 실제 관측 비교·Current 확정은 B에 둔다. A의 ALREADY_ASSEMBLED도 B 검사 없이 D Step 완료로 바꾸지 않는다. 이 역할 매핑의 실제 함수 연결은 미구현이다.

**공급 파지 기준은 패드 하단이 블록 밑면보다 5mm 위**다. 이는 TCP 높이 5mm라는 뜻이 아니다. 기존 보정 오프셋을 다시 적용하거나 기존 실측 결착 TCP에 공급 파지 보정을 더하지 않는다. 기존 v4의 synthetic 기하 상수와 실물 파지 프로필의 정합성, 공통/시험 좌표 원점·축·판 자세, TCP/tool·파지·체결 유지의 실기 검증은 확인 필요다. 이번 문서에서는 새 제어값·pose·속도·힘을 생성하지 않았다.

## 10. 담당자별 단위기능 개발 순서

아래는 후속 개발 순서이며 이번 문서 작업의 구현 완료 목록이 아니다. upstream 구현 대신 문서 예시로 독립 검사한 뒤 실제 연결을 확인한다.

| 담당 | 순서 | 단위 입력→출력 및 확인할 실패 |
|---|---|---|
| 수현 인터페이스 | 1 | 기존 함수/콜백·오류 매핑과 문서용 필드 확인→최종 배포 기준 관리. 새 공통 규약을 임의 확대하지 않음 |
| A | 2→3→4 | Design+B 기준 Current→Plan/작업/도움 후보→동일 자료 B·D 공유→직전 평가→Step 경로. 전달 실패·기준 충돌·BLOCKED 검증 |
| B | 2→3→4→5 | Plan 자료 수신/검사→INITIAL/STEP/FINAL 요청 처리→전체 관측 비교·Current/revision 확정→결과→취소 직전/직후 경쟁 검증 |
| C | 2→3→4 | 수정 중 설계 제공→대화 승인→C→A. 차이 문맥→KEEP/REVISE/UNCLEAR→수정·재승인. 실패·취소·승인 전 후보 검증 |
| D Backend | 2→3→4→5 | 검사 문맥/취소→B 결과 대응·중복/옛 결과 차단→판정별 진행/C 호출→새 Plan 전환. D 공간 비교·채택 제거는 후속 코드 작업 |
| D Robot/HMI | 3→4→5 | v4 실행 경계·자동 승인→수정/승인 화면 분리·B 판정/D 상태·제스처 연결→Fake 경계 검사 후 SIM/REAL 별도 검증 |
| D DB/웹 | 4→5 | 기존 JSONL의 새 계획/검사/의도/완료 이력 전달→기존 적재 호환성→사용자별 웹 조회·저장 실패. 구조 변경은 별도 요청 |
| 전원·수현 통합 | 6 | 정상/차이/가림/오류/취소/설계 변경의 실제 Producer–Consumer 연결→장치 시험. 문서 검증과 구분 |

## 11. 배포 예시와 판독

[EXAMPLES.json](EXAMPLES.json)은 **실행 불가 문서용 예시**다. 작은 두 블록 구조로 흐름을 설명하며 완성 의자·최신 Producer 실제 반환·실기 좌표가 아니다. 기존 실행 Schema에 입력하지 않는다. 예시의 observation은 기존 관측 필드의 근거 부분을 재사용하며 result.check_id가 촬영 문맥을 연결한다. 오류명·check_kind·결과 봉투·수정 중 설계 통지의 실제 함수 매핑은 미구현이다.

| 예시 | 확인할 계약 |
|---|---|
| initial / normal_step / lower_layer_occluded / final | 초기 상태·정상 진행·아래층 이력 유지·최종 검사 구분 |
| wrong_position_layer / existing_structure_changed | 목표 외 위치·층·색상 및 기존 구조 변경도 B가 비교 |
| unobservable / invalid_input / plan_missing / processing_failed | 가림과 업무 오류 구분, Current·다음 Step 보존 |
| old_result / canceled_before_commit / committed_before_cancel | D 옛 결과 차단과 B 취소 확정 경계의 차이 |
| keep / unclear / design_change | KEEP 즉시 진행 금지, UNCLEAR 대기, REVISE→수정·대화 승인→C→A→B·D |
| same_state_recheck / conflicting_duplicate | 동일 상태는 revision 유지, 중복 결과는 한 번만 처리·충돌 보류 |

## 12. 확정·미구현·미검증과 근거

| 상태 | 내용 |
|---|---|
| 사용자 확정 | C/A/B/D 책임, A 동일 계획 공유, D 지정 검사, B Current/revision·Expected/비교, 전체 관측 영역 판단, C 대화 승인, D 자동 진행, 제스처 D, 기존 이력 경로, 5mm 파지 기준 |
| 문서용 매핑 초안 | check_kind와 결과/오류 봉투, 취소 반환/콜백 위치, 수정 중 설계 통지 필드. 의미는 위 결정대로 연결하되 현재 함수가 받는다고 주장하지 않음 |
| 후속 구현 필요 | B 단일 Current 확정/취소 경계, A 공유 어댑터, D 기존 비교·채택 역할 이관, C 지연 REVISE/미리보기/승인 연결, HMI·JSONL·웹 인계 |
| 후속 검증 필요 | 실제 A/B/C/D 정상·실패 반환, 취소 경쟁, 전체 판 관측·가림/기존 구조 변경, Robot 도달·정지·파지·Contact·도움, 좌표/기하 정합·5mm 실물 파지·최종 결착·사용자별 저장/웹 |
| 이번 작업 | 문서·예시·링크/표/코드 블록·계약 일관성 검사. 실행 코드·런타임 Schema·DB 구조·Robot 설정 수정 및 앱/Camera/Robot/Isaac/DB 시험 없음. commit/push/GitHub 게시 없음 |

근거는 2026-10-08 이 대화의 사용자 확정 결정, 자료 폴더의 `contract_records/인터페이스 결정 타임라인.md`, `assembly_reference_20261008/V4_REVIEW.md` 및 보존된 v4 `CONTRACT_DECISIONS.md`·`EXECUTION_BOUNDARIES.md`·`FUNCTION_MAPPING.md`, 개발 저장소의 기존 `docs/06_CONTRACT_DRAFT.md`·`09_C_B_BACKEND_HANDOFF.md`·`D_A_PLANNER_HANDOFF.md`·`D_C_FUNCTION_INTEGRATION.md`다. 이 배포 문서는 과거 원자료/시험 기록을 대체 삭제하지 않으며 충돌하는 책임·진행 의미만 위 최신 결정으로 대체한다. 담당별 구현 증거가 생기면 수현이 문서 상태와 배포 기준을 갱신한다.

### 이번 문서 검사와 수정 파일

2026-10-08 문서 15개(Markdown 14개·문서용 JSON 1개)를 대상으로 로컬 링크 241개·표 66개·코드 블록 39개와 JSON 시나리오 18개를 검사했다. 신규 링크 오류·표 열/블록 닫힘 오류는 없었다. 예시의 요청/결과 대응, 고정 Expected, revision 변화/유지, 가림 이력 분리, 동일 A→B/D 계획, REVISE 후 승인·재계획 연결을 정적 검사했다. 이 검사는 업무 코드를 실행한 단위/통합 시험이 아니다.

작업 전 기록과 대조해 기존 13개 문서 본문을 보존했고 나머지 335개 조사 대상 파일의 해시가 같았다. `git diff --check` 종료 코드 0, 지정 브랜치를 유지했다. 배포 ZIP은 이 README와 EXAMPLES.json 두 파일만 포함하며 원문 바이트 일치를 검사했다. 기존 STATUS의 `/tmp` 화면·로그 링크 7개는 대상 파일이 없어 과거 증거 재열람이 제한된다. 이번 변경과 무관한 원기록이므로 링크나 수치를 임의 수정하지 않았다.

수정한 기존 파일은 개발 저장소의 `README.md`, `docs/00_CURRENT_DECISIONS.md`, `docs/02_TEAM_GUIDE.md`, `docs/06_CONTRACT_DRAFT.md`, `docs/09_C_B_BACKEND_HANDOFF.md`, `docs/D_A_PLANNER_HANDOFF.md`, `docs/D_C_FUNCTION_INTEGRATION.md`, `docs/STATUS.md` 8개와 자료 폴더의 `contract_records/인터페이스 결정 타임라인.md`, `contract_records/assembly_reference_20261008/README.md`, `contract_records/assembly_reference_20261008/V4_REVIEW.md`, `최종_MVP_발표문서/README.md`, `최종_MVP_발표문서/05_Interface_Specification.md` 5개다. 새 문서는 이 배포 묶음의 README.md·EXAMPLES.json이며 자료 폴더 `contract_records/final_mvp_interface_20261008.zip`으로도 제공한다. Google Drive 공동 문서는 이번 로컬 작업 범위에 포함하지 않았다.
