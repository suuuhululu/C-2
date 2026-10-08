# Stage 3 C–D 통합 계약 초안 (Wave 0 조사, 2026-10-08)

목적: C의 Design 후보(Candidate Design)와 Voice/HRI를 D/HMI Preview와 A Planning 사이에 연결한다. 흐름은 C → D → HMI Preview → 사용자 검토/승인 → A → D. 이 문서는 조사 결과와 계약 초안이며 구현·채택이 아니다. Stage 2의 Design/HRI 품질(Initial ANY/SPECIFIC/CREATIVE, Revised After 구조, judge, 재고 제약, TTS/ack/progress)은 바꾸지 않는다.

## 1. 현재 구조(조사 결과, 2026-10-08 work/siyul-design-hri 109ed2e)

### 1.1 C 공개 API (app/c_design/main.py)
- `create_initial_design(text=None, should_stop=None, preference_text=None, on_question=None, on_progress=None)`
- `run_intervention(design, current, differences, text_answers=None, on_question=None, should_stop=None, on_progress=None)`
- 반환 envelope: `{status: OK|FAILED|CANCELLED, hri_result: None|KEEP|REVISE|UNCLEAR, design: {design_version, blocks}|None, design_metadata: dict|None, questions: [str], error: {code, message, details}|None}`.
- 음성 모드(text None / text_answers None)는 C가 듣고 말하며, 반환 시점에 마이크는 닫혀 있다(listen은 호출 안에서만 열림). 따라서 "Design 반환 후 STT를 열어 두는" 문제는 없고, 검토 대화는 D가 다시 호출해야 시작된다.

### 1.2 C → A 연결 위치
- C는 A를 호출하지 않는다. D의 `app/planning_connection.py`:
  - `on_initial_design(backend, request_id, response)`: status OK·hri_result None·design 키 확인·design_version == 1 → `planning_request["design"]`에 보관 → 이벤트 INITIAL_DESIGN_RECEIVED → `_send("planner", {..., design, current, supported_scope})`.
  - `run_planning_request` → `planning_trial.planner.plan_from_current(design, current)` → `backend.on_plan_result` → READY면 `backend.on_plan`이 `freeze_plan_basis`로 `state["context"]`(채택 Design + Plan)를 만들고 PLAN_ADOPTED.
  - Revised: `on_c_intervention` → `backend.on_intent` → `app/replan.on_intent`가 후보를 검증(design_version은 배치가 바뀌면 +1)하고 **즉시** `begin_replan(pending_design)` → A → `on_plan` 채택.
- 즉 현재 "승인"은 사람이 아니라 A의 READY 결과가 대신한다. 사용자 검토 단계는 없다.

### 1.3 D → C 호출 위치 (app/c_text_connection.py `CTextConnection`)
- `start(kind="initial"|"intervention", payload, answers=(), preview=False)` → 별도 Thread에서 C 호출 → Qt signal `result_received` → `finish` → `backend.on_initial_design` 또는 `on_c_intervention`.
- Initial 텍스트 모드: `c_main.create_initial_design(text=self.initial_text, ...)`(고정 "의자 만들어줘"). 음성 모드(`voice_call`): **D가 직접** `voice.listen()`으로 목표를 듣고 그 텍스트로 C를 부른다(C의 인사·한 문장 해석·follow-up은 `text=None`일 때만 동작하므로 현재 D 경로에서는 나오지 않음. handoff 36·37·40).
- Intervention: `run_intervention(payload["design"], current_blocks_for_c(payload), differences_for_c(payload["difference"]), text_answers, on_question, should_stop)`. D의 `preview=True`는 "답변 없이 질문 문장만 받는 호출"(question_preview)이며 HMI Design Preview와 **이름만 같고 뜻이 다르다**. 계약에서는 `question_preview`로 부른다.
- emit 라우팅: `abd_input_hmi.emit` / `real_workflow_hmi.emit` / `fake_demo.emit`에서 port "planner"(initial)·"hri"(intervention)를 C 호출로 연결한다.

### 1.4 C response 소비 구조
- D는 `status`, `hri_result`, `design`, `questions`(UNCLEAR면 마지막 질문)만 읽는다. `design_metadata`는 소비하지 않고 JSONL 이벤트(`C_CALL_RESULT`, `INITIAL_DESIGN_RECEIVED`, `C_INTERVENTION_RESULT`)에 전체 응답으로 기록만 된다.
- 유효성 검사(`app/contracts.py`, `replan.on_intent`)는 여섯 필드·layer 1..4·yellow/blue·2x2x1/2x3x1 기준이라 Stage 2 어휘(red 1x2x1, 5층)는 D에서 거부된다(handoff 1~6, 36~41).
- `interfaces/fixtures/c_design_initial_result.json`·`c_design_revised_result.json`은 design_metadata가 없는 Stage 1 envelope이다.

### 1.5 HMI Preview renderer 위치
- `app/qt_hmi.HmiWindow.render_snapshot(snapshot)` ← Qt signal `snapshot_received` ← D의 `publish()`(`make_snapshot(backend.state)`). 미리보기는 `snapshot["design"]` = `state["context"]["design"]`(**채택 Design만**)을 `BoardView.set_blocks`로 그린다(제목 "전체 완성 목표 · 채택 Design vN" / "미채택").
- 승인되지 않은 후보를 그릴 자리가 없다. `state["pending_design"]`(REVISE 후보)은 snapshot에 포함되지 않는다. `interfaces/schemas/hmi.schema.json`의 `design`은 채택 Design 의미다(docs/06 §8: "수정 후보를 확정 목표처럼 보여주지 않는다").
- C-only 시험용 renderer(`scripts/c_design_hmi_render.py`)는 Stage 2 검증 전용이며 D 경로가 아니다.

### 1.6 Preview render 완료를 감지할 수 있는 지점
- `render_snapshot`은 `snapshot_received`(QueuedConnection)로 Qt 스레드에서 동기 실행된다. `design_board.set_blocks()`는 `update()`로 repaint를 예약하므로 "함수 반환 = 화면 갱신 요청 완료"이고, 실제 paint는 다음 이벤트 루프에서 일어난다.
- 감지 후보(D 소유): (a) `render_snapshot` 끝에서 `preview_rendered`(pyqtSignal(dict: request_id, kind, design_version)) 발행 → D가 `QApplication.processEvents()` 뒤 C 검토 호출 시작; (b) `BoardView.paintEvent` 뒤 1회성 콜백(가장 정확, 구현 복잡). 권장 (a). 시간 sleep 추정은 쓰지 않는다.

### 1.7 Initial candidate / approved Design 구분 현황
- Initial: C 후보는 `planning_request["design"]`에만 있고, A READY → `on_plan`에서 `context.design`이 되는 순간이 채택이다. 사용자 승인 단계·후보 수정 루프 없음.
- Revised: `pending_design`(REVISE 후보) → `begin_replan` → A READY → 채택. "REVISE 결정"과 "후보 승인"이 같은 순간에 일어난다.

## 2. 필요한 새 상태(초안)

| 쪽 | 상태/값 | 의미 |
|---|---|---|
| C envelope | `hri_result` ∈ {APPROVE, MODIFY, UNCLEAR}(검토 호출 전용) | 검토 대화 결과. Intervention의 KEEP/REVISE/UNCLEAR과 값 공간을 섞지 않는다(호출 종류로 구분) |
| C design_metadata | `review`: {decision, style_hint, reply, round}(검토 호출 시) | 표시·로그용. Design에는 넣지 않음 |
| D workflow_status | `WAIT_REVIEW` | 후보 Preview가 표시됐고 사용자 검토(APPROVE/MODIFY) 대기 |
| D state | `candidate_design`, `candidate_kind` ("initial"\|"revised"), `review_request` | 미승인 후보와 검토 요청 식별(request_id·job_id·design_version·current_revision) |
| D snapshot | `candidate_design`(새 필드, 채택 `design`과 분리) | HMI가 "후보 · 미채택"으로 그림. hmi.schema.json 변경(D/공유 문서) |
| D 이벤트 | CANDIDATE_RECEIVED, PREVIEW_READY, REVIEW_RESULT, DESIGN_APPROVED | JSONL 기록 |

## 3. 제안 C–D 계약

### 3.1 호출 순서(Initial)
1. D → C `create_initial_design(text=None|문장, on_question, on_progress, should_stop)` (planner port 요청 그대로). C는 인사·한 문장 해석·필요 시 follow-up 1회·ack·생성을 마치고 envelope(design = Candidate Design v1)을 반환하며 마이크를 닫는다.
2. D: `candidate_design` 보관, `workflow_status = WAIT_REVIEW`, snapshot에 `candidate_design` 포함 → publish → HMI `render_snapshot` → `preview_rendered` 발행.
3. D → C `review_design_candidate(candidate, kind="initial", design_metadata, text_answers=None, on_question, on_progress, should_stop)`. C: TTS "완성된 디자인이 화면에 표시됐어요. 어떠신가요?" → beep → STT → 해석.
   - APPROVE: envelope `{status: OK, hri_result: "APPROVE", design: candidate(동일), ...}` → D: DESIGN_APPROVED → `_send("planner", design)` → A → PLAN_ADOPTED(기존 경로).
   - MODIFY: C가 style_hint를 합쳐 Initial 후보를 다시 생성(같은 family/concept 유지, 사용자가 다른 느낌을 원하면 해석 결과에 따라 ANY/CREATIVE 재선택) → envelope `{hri_result: "MODIFY", design: 새 후보}` → D: 2번으로 돌아가 Preview 갱신 → 다시 3번.
   - UNCLEAR: 재질문 문장을 questions에 넣고 반환 → D는 같은 WAIT_REVIEW에서 새 request_id로 재호출(Intervention UNCLEAR 처리와 같은 패턴, 2회 넘으면 HMI 명시 선택).
   - CANCELLED/FAILED: 기존 의미.
4. 승인 전 후보의 `design_version`은 1로 고정(Initial은 항상 1, docs/06 §4). 후보 반복은 metadata `review.round`로 구분한다.

### 3.2 호출 순서(조립 중 Difference)
1. D → C `run_intervention(approved_design, current, differences, ...)`(hri port 그대로). 결과 KEEP → 기존대로. 결과 REVISE → envelope의 design은 **Revised Candidate**이며 D는 `begin_replan`을 바로 부르지 않고 `candidate_design`에 보관, WAIT_REVIEW, Preview, `preview_rendered`.
2. D → C `review_design_candidate(candidate, kind="revised", previous_design=approved, current, differences, ...)`. APPROVE → D `replan.begin_replan(candidate)`(기존 검증 포함) → A → 채택. MODIFY → C가 Current 보존·style_hint 합쳐 Revised 후보 재생성(After 구조·min_blocks·judge 그대로) → Preview → 재검토. UNCLEAR → 재질문.
3. "REVISE 결정"(INTENT_RECEIVED)과 "Revised 후보 승인"(DESIGN_APPROVED)은 별개 이벤트·상태다. 후보의 `design_version` = 승인 Design + 1(후보 반복 중 동일 유지; 승인 시점에 확정). 배치가 승인 Design과 같으면 +0(기존 규칙).

### 3.3 유효성·식별
- 검토 호출 payload: `{request_id, job_id, kind, design_version, current_revision, candidate, design_metadata, previous_design?, current?, difference?}`. C는 `candidate`의 §9.1 유효성과 kind별 입력(revised면 current 보존)을 검사하고, 아니면 INVALID_INPUT.
- D는 응답의 request_id·design_version·current_revision이 활성 검토 요청과 다르면 채택하지 않는다(기존 `valid()` 패턴).
- A가 받는 Design은 승인된 `{design_version, blocks}`뿐이다. C는 Plan/Step/Remaining/NextPart/좌표를 만들지 않는다.

## 4. 제안 C 공개 API(최소)
- 유지: `create_initial_design(...)`, `run_intervention(...)` (시그니처·의미 불변; REVISE 결과의 design은 "후보"임을 문서에 명시).
- 신규(1개, main.py 안): `review_design_candidate(candidate, *, kind, design_metadata=None, previous_design=None, current=None, differences=None, text_answers=None, on_question=None, should_stop=None, on_progress=None) -> envelope`. `hri_result` ∈ {APPROVE, MODIFY, UNCLEAR}. 기존 함수에 `mode`/`phase`를 넣어 합치는 안은 Initial/Review/Intervention 의미가 섞이고 D의 `valid()`/이벤트 분기가 복잡해져 채택하지 않는다.
- dialogue: `build_review_question(kind)`, `parse_review_response(text, llm_fallback)`(규칙: "좋아/이걸로/됐어/마음에 들어" → APPROVE, "다시/바꿔/더 ~하게/말고" → MODIFY, 취소, 그 외 LLM), 검토 ack/progress 문장. llm: `interpret_review_answer(text, kind, should_stop)`(보조 모델, keys decision/style_hint/reply/reason). designer/validator: 변경 없음(재생성은 기존 generate 함수 재사용). voice: 변경 없음.
- progress 단계 추가: REVIEW_LISTENING/REVIEW_ACK/REGENERATING_CANDIDATE/CANDIDATE_READY.

## 5. 기존 6개 모듈 안에서 구현 가능한지 / 새 모듈 필요 여부
- 가능. main(진입·검토 루프), dialogue(질문·규칙·문장), llm(검토 해석), designer/validator(기존 재사용), voice(불변). 새 production 모듈은 필요 없다. C-only 시험 runner는 scripts에 있고 production이 아니다.

## 6. Fixture / 검증 계획
- tests/unit/c_design: review 대화 규칙·해석 fake·재생성 경로·envelope 키·design_version 정책·Mock 모드(텍스트 답변, TTS 없음).
- tests/integration: "fake D" 순서 fixture — create → (가짜 preview_rendered) → review(MODIFY) → 새 후보 → review(APPROVE) → A 입력 가능 데이터 확인; Difference → run_intervention(REVISE) → review(APPROVE) → replan 입력 확인. `interfaces/fixtures/c_design_*_result.json`을 현재 envelope(design_metadata 포함)로 갱신하는 것은 공유 fixture라 D 합의 후.
- 실제 D 연결(`c_text_connection`·backend·snapshot·hmi.schema)은 handoff로 넘기고, C쪽은 fake callback으로 검증한다.

## 7. 예상 Wave
- Wave 1(Opus B): 검토 대화(APPROVE/MODIFY/UNCLEAR/CANCEL)·질문·ack·STT·`review_design_candidate` 골격(재생성 없이 결과만)·tests. A는 contract 질의.
- Wave 2(Opus A + B): 후보 lifecycle — Initial 후보 재생성(style_hint 합성), Revised 후보 재생성, design_version 정책, metadata `review`, 문서. main 배선은 B가 순차.
- Wave 3(B 중심): fake D 콜백·preview_rendered 동기화 fixture, D handoff(상태·snapshot 필드·이벤트·`question_preview` 명칭 정리) 문서.
- Wave 4(Fable): C-only runner에 검토 루프 추가해 음성 E2E, 회귀, 보고.

## 8. 위험 요소 / 결정 필요
1. 후보 반복 중 `design_version` 정책(§3.1·§3.2 제안: Initial 후보 1 고정, Revised 후보 승인+1 고정). docs/06 §4와 D `replan.on_intent` 검증과 맞물림.
2. snapshot `candidate_design` 필드 추가는 D/공유 schema 변경 → D 작업. 대안(채택 `design`에 후보를 넣고 제목만 바꾸기)은 §8 원칙 위반이라 비권장.
3. D의 `question_preview` 용어와 HMI Preview 충돌 → 계약에서 `question_preview`로 명기.
4. 음성 모드 Initial은 D가 직접 STT하는 현 구조라 C의 인사·한 문장 해석이 나오지 않음 → Stage 3에서 D가 `text=None`으로 위임하는 결정 필요(handoff 40).
5. A 어휘(red 1x2x1·5층·40블록, handoff 1~3)와 D contracts(4~6) 미반영 상태에서는 승인 후 A 단계가 INVALID로 끊긴다. Stage 3 E2E의 "A 입력 가능 데이터 확인"은 A 반영 전까지 데이터 형식 확인에 그친다.
6. 검토 루프 시간: 검토 1회 = TTS 3~4 s + 듣기 + 해석 1~2 s; MODIFY 시 재생성 40~100 s가 추가된다. UNCLEAR 2회 뒤 HMI 명시 선택으로 종료(기존 정책 재사용).
7. Current가 바뀐 뒤 도착한 검토 결과는 채택하지 않는다(요청 식별 검사). 검토 중 STOP은 CANCELLED.
