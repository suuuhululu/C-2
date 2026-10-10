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

## 7.1 Wave 1 반영 (2026-10-11, A: llm·계약 문서)
- llm: `interpret_review_answer(text, kind, should_stop=None)`, `SYSTEM_PROMPT_REVIEW`, `REVIEW_KEYS = ("decision", "style_hint", "reason", "reply")`, `REVIEW_CONTEXT`(kind별 문맥 문장). 보조 모델(`OPENAI_AUX_MODEL`, 기본 gpt-4.1-mini), Design은 보내지 않음. kind는 `"initial"` / `"revised"`만(그 밖은 `ValueError`, 호출 없음).
- decision 값은 APPROVE / MODIFY / UNCLEAR / CANCEL이며 Intervention의 KEEP / REVISE와 값·프롬프트·키가 별개입니다(프롬프트에 KEEP·REVISE 단어 없음). 위 §4의 초안 `hri_result` ∈ {APPROVE, MODIFY, UNCLEAR}에 CANCEL이 더해졌습니다(명세 Wave 1).
- 한국어 부정·혼합: "나쁘진 않은데 조금 더 길었으면 좋겠어"·"싫은 건 아닌데 다른 것도 보고 싶어" → MODIFY, "싫은 건 아니야" 단독·"그냥 됐어"(문맥 없음) → UNCLEAR. 위 §4 초안의 규칙 예 "됐어 → APPROVE"는 LLM 해석에서는 쓰지 않습니다(규칙 표는 B 소유 dialogue에서 정함).
- 계약 영향: Design `{design_version, blocks}`와 envelope 키는 불변입니다. 검토 결과는 `design_metadata.review = {kind, decision, style_hint, round, source, reply}`로만 싣습니다([계약 §6.1](C_DESIGN_CONTRACT.md)). 후보 Design은 그대로 반환되고 `design_version`은 바뀌지 않습니다.
- `review.style_hint`(MODIFY 방향, 예: "그냥 다시" → "현재 디자인과 다른 새로운 형태")는 Wave 2 후보 재생성의 입력입니다. Wave 1에서는 재생성하지 않습니다.
- D 코드·공유 schema는 수정하지 않았습니다. snapshot `candidate_design`·`preview_rendered` 등 D 쪽 상태는 위 §2·§8 그대로 미결입니다.

## 7.2 Wave 2 반영 (2026-10-11, A: llm·계약 문서)
- llm: `REVIEW_KEYS = ("decision", "style_hint", "scope", "concept", "reason", "reply")`, `REVIEW_SCOPES = ("patch", "redesign", "concept_change")`. `interpret_review_answer(text, kind, should_stop=None, context=None)` — context `{family, concept}`를 payload `current_candidate`로 보냄(블록 미전송). `SYSTEM_PROMPT_REVIEW`에 scope·concept 정의와 예문 추가(기존 네 decision 정의·부정 지시·reply 규칙 유지).
- `generate_initial_design(…, previous_candidate=None, scope=None)`, `generate_revised_design(…, previous_candidate=None, scope=None)`: 둘을 함께 주면 scope별 직전 후보 문단을 사용자 메시지에 넣음(하나만이거나 scope가 밖이면 `ValueError`, 호출 없음). system prompt·Current 보존·min_blocks·judge 불변.
- 정책은 [계약 §8.14](C_DESIGN_CONTRACT.md)(scope 3종·family/concept 규칙·version·round). 위 §4 초안의 시그니처와 달리 public API는 추가하지 않고 `review_design_candidate`가 MODIFY에서 새 Candidate를 `design`에 담아 반환합니다(명세 Wave 2 §1, main은 B).
- 계약 영향: Design `{design_version, blocks}`·envelope 키 불변. 새 Candidate는 Approved가 아니며 채택은 D. Initial 후보 version 1, Revised 후보 Approved + 1 고정(위 §8 위험 1의 제안과 같음). `design_metadata.review`에 `scope` 추가, `round`는 후보 반복 횟수로 재정의([계약 §6.1](C_DESIGN_CONTRACT.md)).

## 7.3 Wave 3 반영 (2026-10-11, A: contract·invariant·fixture·조사)
- 표현: "D가 C를 호출하고 response를 받는다". 이번 Wave의 결과는 C-side caller fixture PASS, fake PREVIEW_READY 기반 review 호출 PASS, D가 Preview 완료 후 호출할 C API 준비 완료입니다. 실제 D/HMI integration은 팀 통합 단계입니다.
- fixture: `tests/fixtures/c_stage3/*.json`(Fable이 Wave 2 Sol smoke에서 얻은 실제 envelope 8개, 설명은 같은 폴더 README). `tests/unit/c_design/test_stage3_contract.py`가 envelope 키·Design 계약(재고 조합 포함)·version(Initial·MODIFY 후보 1, Revised 후보 2)·Current 보존·review metadata 키·MODIFY ≠ 입력 후보·APPROVE/CANCEL = 입력 후보·비밀값 없음을 검사합니다.
- invariant(fake LLM, 텍스트 모드): Initial → review MODIFY → MODIFY → APPROVE에서 version 1 고정·round 1, 2, 2·APPROVE 생성 0회; Approved v1 → run_intervention REVISE → review(revised) MODIFY → MODIFY → APPROVE에서 version 2 고정·Current 보존·judge 매 생성 1회; 입력 후보·metadata·Intervention 입력 불변; 같은 입력의 결과가 앞선 호출과 무관(ack 문장 표현 제외); `main`에 모듈 수준 요청·후보 상태 없음.
- **correlation 결론**: C에는 `request_id`·`job_id`·`current_revision`이 없습니다(grep). 동기 반환으로 호출과 response가 1:1이고, stale·중복·활성 요청 판정은 caller(D) 책임입니다. GitHub 상태 기준(최신 아닐 수 있음) D `CTextConnection`이 이미 `valid()`·`C_CALL_BUSY`·`_ignored`·`threading.Event`로 이를 합니다. production field는 추가하지 않습니다(후보·이유는 [계약 §4.5](C_DESIGN_CONTRACT.md)).
- **Expected 결론**: Expected 전체는 C에 불필요합니다. `run_intervention`·질문·escalation·Revised 생성·judge·Current 보존 검사는 Approved Design·Current·`differences[].expected / actual`만 씁니다(코드 근거 [계약 §4.5](C_DESIGN_CONTRACT.md)). Expected는 D가 관리하는 입력이며 C API에 추가하지 않습니다.

## 8. 위험 요소 / 결정 필요
1. 후보 반복 중 `design_version` 정책(§3.1·§3.2 제안: Initial 후보 1 고정, Revised 후보 승인+1 고정). docs/06 §4와 D `replan.on_intent` 검증과 맞물림.
2. snapshot `candidate_design` 필드 추가는 D/공유 schema 변경 → D 작업. 대안(채택 `design`에 후보를 넣고 제목만 바꾸기)은 §8 원칙 위반이라 비권장.
3. D의 `question_preview` 용어와 HMI Preview 충돌 → 계약에서 `question_preview`로 명기.
4. 음성 모드 Initial은 D가 직접 STT하는 현 구조라 C의 인사·한 문장 해석이 나오지 않음 → Stage 3에서 D가 `text=None`으로 위임하는 결정 필요(handoff 40).
5. A 어휘(red 1x2x1·5층·40블록, handoff 1~3)와 D contracts(4~6) 미반영 상태에서는 승인 후 A 단계가 INVALID로 끊긴다. Stage 3 E2E의 "A 입력 가능 데이터 확인"은 A 반영 전까지 데이터 형식 확인에 그친다.
6. 검토 루프 시간: 검토 1회 = TTS 3~4 s + 듣기 + 해석 1~2 s; MODIFY 시 재생성 40~100 s가 추가된다. UNCLEAR 2회 뒤 HMI 명시 선택으로 종료(기존 정책 재사용).
7. Current가 바뀐 뒤 도착한 검토 결과는 채택하지 않는다(요청 식별 검사). 검토 중 STOP은 CANCELLED.
