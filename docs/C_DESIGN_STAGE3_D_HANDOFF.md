# C Stage 3 D Handoff

2026-10-11 · C 파트(Stage 3 Wave 3) · 대상: D(Backend·HMI·통합 담당)

이 문서는 **D가 C를 호출하고 response를 받는** 방법을 정리합니다. C는 D에 push하지 않습니다. 모든 C 공개 함수는 **동기 호출**이며 결과 envelope을 반환값으로 돌려줍니다.

현재 상태는 다음까지입니다.
- C-side caller fixture PASS: [tests/integration/test_c_stage3_lifecycle.py](../tests/integration/test_c_stage3_lifecycle.py)
- fake PREVIEW_READY 기반 review 호출 PASS
- D가 Preview 완료 후 호출할 C API 준비 완료

**실제 D/HMI integration은 팀 통합 단계**입니다. 이 문서는 D 코드가 바뀌었거나 연결됐다는 뜻이 아닙니다(D 코드는 수정하지 않았습니다).

계약 세부는 [C_DESIGN_CONTRACT.md](C_DESIGN_CONTRACT.md) §4.1(Initial)·§4.2(Intervention)·§4.4(Preview 검토)·§4.5(외부 caller 호출 계약, A 작성)·§6(envelope)을 기준으로 합니다.

## 공통: response envelope

세 함수 모두 같은 키를 돌려줍니다: `{status, hri_result, design, design_metadata, questions, error}`(§6).

| 필드 | 값 |
|---|---|
| `status` | `"OK"` / `"FAILED"` / `"CANCELLED"` |
| `hri_result` | Initial: `null` · Intervention: `"KEEP"` / `"REVISE"` / `"UNCLEAR"` · 검토: `"APPROVE"` / `"MODIFY"` / `"UNCLEAR"` / `"CANCEL"`(값이 서로 다름) |
| `design` | `{design_version, blocks}`(블록 6필드) 또는 `null`. Design에는 승인 표시·metadata가 없습니다 |
| `design_metadata` | 설명·판정·검토 기록(표시·로그용, 분기에 쓰지 않음) 또는 `null` |
| `questions` | 이번 호출에서 C가 낸 질문 문장 |
| `error` | `null` 또는 `{code, message, details}`(§10: `INVALID_INPUT`, `UNSUPPORTED_OBJECT`, `DESIGN_GENERATION_FAILED`, `LLM_CALL_FAILED`, `VOICE_IO_FAILED`, `STOPPED`, `USER_CANCEL`) |

세 함수 모두 예외를 밖으로 던지지 않습니다. 단, D가 넘긴 콜백(`on_question`·`on_progress`)이 던진 예외는 호출자 책임입니다.

## 1. Initial 시작

```python
create_initial_design(text=None, should_stop=None, preference_text=None, on_question=None, on_progress=None)
```

- **음성 모드(`text=None`, 권장)**: C가 Initial Voice/HRI 전체를 맡습니다. D가 Initial STT를 대신하지 않습니다.
  - 순서: 인사 TTS("안녕하세요. 오늘 어떤 걸 만들고 싶으세요?") → beep → STT(`listen(mode="free", beep=True)`) → 해석 → (필요 시 되묻기 1회) → ack TTS → 생성 → validator → 설명 → "디자인이 완성됐어요." TTS → response.
- **텍스트 모드**: `text` = 사용자 첫 발화 전체, `preference_text` = 되묻기 답(선택). C는 음성을 내지 않습니다.
- **반환**: `status OK`, `hri_result null`, `design` = **Initial Candidate**(`design_version` 1), `design_metadata` = 설명·family 선택·`family_source` 등(§6.1).
- **실패**: 앉는 가구가 아니면 `FAILED`/`UNSUPPORTED_OBJECT`, 음성 장치·STT 실패면 `VOICE_IO_FAILED`, STOP이면 `CANCELLED`/`STOPPED`.

D가 할 일: `design`을 **Candidate**로 보관하고 HMI Preview에 표시합니다(아직 Approved가 아님).

## 2. Preview 표시 완료 후

```python
review_design_candidate(candidate, *, kind, design_metadata=None, previous_design=None, current=None, differences=None,
                        text_answers=None, on_question=None, should_stop=None, on_progress=None)
```

- **호출 시점**: D가 Candidate의 Preview 표시를 끝낸 뒤(PREVIEW_READY)입니다. C는 표시 완료를 확인하지 않습니다(테스트에서는 caller가 PREVIEW_READY를 가정하며 sleep은 필요 없음).
- **인자**
  - `candidate`: 방금 표시한 후보.
  - `kind`: `"initial"` 또는 `"revised"`.
  - `design_metadata`: 그 후보를 받은 response의 `design_metadata` **그대로**.
  - `kind="revised"`면 `previous_design`(Approved)·`current`·`differences`가 필수입니다.
- **C가 하는 일**: 검토 질문 TTS("완성된 디자인이 화면에 표시됐어요. 어떠신가요?" / revised: "수정된 디자인이 화면에 표시됐어요. 어떠신가요?") → beep → STT → 해석(불명확하면 재질문 1회) → ack TTS.

| 결과 | C | D |
|---|---|---|
| `APPROVE` | `status OK`, `design` = 입력 후보 그대로 | 그 후보를 **Approved Design으로 채택** → A Plan 요청 가능. 채택은 D 몫이며 Design에 승인 표시는 없습니다 |
| `MODIFY` | (LLM 모드) ack 뒤 **새 Candidate**를 만들어 `design`에 담아 반환(Initial 후보는 version 1, Revised 후보는 Approved + 1, Current 보존). `design_metadata.review.round`가 1 늘어남 | 새 Candidate로 Preview 갱신 → `review_design_candidate`를 **다시 호출**합니다. 이때 이번 response의 `design_metadata`를 그대로 넘기면 round가 이어집니다. (Mock 모드는 후보 그대로) |
| `UNCLEAR` | `status OK`, `design` = 입력 후보 | 보류하거나 다시 검토 호출 |
| `CANCEL` | `status CANCELLED`, `hri_result "CANCEL"`, `error.code USER_CANCEL`, `design` = 입력 후보 | 작업 중단 |
| 생성 실패 | `FAILED`/`DESIGN_GENERATION_FAILED`(또는 `LLM_CALL_FAILED`), `hri_result "MODIFY"`, design null | 이전 후보로 다시 검토하거나 보류 |

## 3. 조립 중 Difference 발생

```python
run_intervention(design, current, differences, text_answers=None, on_question=None, should_stop=None, on_progress=None)
```

- **입력은 세 가지뿐입니다**: `design` = **Approved Design**, `current` = Backend가 채택한 Current 블록 배열, `differences` = 이번 원인 Difference(`[{expected, actual}]`).
- **Expected 전체는 C API에 넘기지 않습니다.** Expected는 D(Backend)가 관리합니다. C의 질문 문장과 생성·judge는 `differences[].expected/actual`과 Current만 씁니다. 근거와 결론은 A 문서 [C_DESIGN_STAGE3_C_D_CONTRACT_DRAFT.md](C_DESIGN_STAGE3_C_D_CONTRACT_DRAFT.md)의 correlation/Expected 결론 절과 CONTRACT §4.5를 참고하세요.
- **C가 하는 일**: Difference 설명 질문 TTS("Design과 다르게 놓인 부분이 있는데, 의도하신 건가요?" + 차이 설명) → beep → STT → 해석 → ack → (REVISE면) 생성·validator·judge.

| 결과 | C | D |
|---|---|---|
| `KEEP` | `design` = 입력 Approved 그대로 | 사람이 블록을 원래 자리로 고치면 기존 계획대로 진행 |
| `REVISE` | **Revised Candidate**(`design_version` = Approved + 1, Current 보존)를 `design`에 담아 반환 | Preview 표시 → `review_design_candidate(candidate, kind="revised", design_metadata=…, previous_design=Approved, current=…, differences=…)` |
| `UNCLEAR` | 텍스트 답변 소진 시 | 보류 |
| 실패·취소 | §10 코드 | 보류 |

## 4. 데이터 저장

C는 DB·파일·HMI에 직접 쓰지 않습니다. D가 response를 받은 뒤 HMI 표시, Backend state, DB 기록, A Plan 요청에 씁니다. 저장 실패가 C 호출 결과를 바꾸지 않습니다.

## 5. correlation (요청 대응)

C 세 함수는 request_id·job_id·current_revision을 **받지도 돌려주지도 않습니다**(C 코드 grep으로 확인: `app/c_design/main.py`·`voice.py`·`dialogue.py`에 해당 필드 없음). 호출은 동기이므로 D가 자기 스레드·요청 단위로 response를 대응시키며, stale·중복 response 구분과 폐기는 **caller(D) 책임**입니다. 자세한 "C가 지원 / D가 관리" 표는 A 문서(초안 correlation 절, CONTRACT §4.5)에 있습니다.

## 6. Voice 독립성과 마이크 lifecycle

- **질문은 호출마다 자기 것으로 시작합니다**: Initial은 인사, 검토는 "완성된(수정된) 디자인이 화면에 표시됐어요. 어떠신가요?", Intervention은 Difference 설명 질문입니다. 이전 호출의 질문·답이 다음 호출로 넘어가지 않습니다(fake listen/speak 테스트로 확인).
- **마이크는 호출 사이에 열려 있지 않습니다**: `voice.record()`는 호출마다 `sd.InputStream(...)`을 `with` 블록으로 열고, 녹음이 끝나면 닫습니다(`app/c_design/voice.py`의 `record`). 테스트 `test_record_opens_and_closes_the_input_stream_on_every_call`이 open → close가 호출마다 한 번씩인 것을 확인합니다.
- `voice.prewarm()`은 Initial 음성 모드 시작 때 스트림을 한 번 열었다 닫는 준비 동작입니다.
- **C 모듈 전역 값**: `voice._last_error`·`_last_capture`·`_last_speak`(디버그용 마지막 기록), `voice._capture_options`(listen 안에서만 설정하고 끝나면 원복), `dialogue._last_pick`(ack 문장 직전 회피용)이 있습니다. 호출 간 결정에는 쓰이지 않습니다.
- **D 쪽 주의**: D가 C를 텍스트 모드로 부르면서 자기 마이크를 따로 쓰는 경우, D와 C가 같은 장치를 동시에 열지 않도록 순서를 맞춰야 합니다(C 음성 모드 호출 중에는 D가 마이크를 잡지 않음).

## 7. 음성 / 텍스트 모드 선택

| 함수 | 음성 모드 | 텍스트 모드 |
|---|---|---|
| `create_initial_design` | `text=None` | `text="…"`(+ `preference_text`) |
| `review_design_candidate` | `text_answers=None` | `text_answers=["…"]` |
| `run_intervention` | `text_answers=None` | `text_answers=["…"]` |

텍스트 모드에서는 C가 TTS를 내지 않습니다. 진행 이벤트(`on_progress`)와 질문(`on_question`)은 두 모드 모두 콜백으로 받을 수 있습니다.

## 8. Mock / LLM 모드

| | Mock(`C_DESIGN_USE_LLM` 미설정 또는 ≠ 1) | LLM(`C_DESIGN_USE_LLM=1`) |
|---|---|---|
| Initial | 목표 문장 `parse_goal`, 질문 없음, 고정 Mock 의자 | 인사·해석·family/concept 생성 |
| 답변 해석 | 규칙만 | 규칙 → 애매하면 LLM 해석 |
| 검토 MODIFY | 후보 그대로(재생성 없음) | 새 Candidate 생성 |
| 음성 | 검토는 음성 없음(질문은 `on_question`). Intervention 음성 모드는 질문을 읽음 | 질문·ack·주요 진행 문장 TTS |

키는 용도별 환경 변수 `OPENAI_LLM_API_KEY`(LLM)·`OPENAI_API_KEY`(STT)·`OPENAI_TTS_API_KEY`(TTS)이며 서로 대체하지 않습니다(§4).

## 9. 실행 명령

fake D caller runner: [scripts/c_stage3_integration_smoke.py](../scripts/c_stage3_integration_smoke.py). C 시험용이며 D 구현이 아닙니다.

Mock 텍스트(키 없음):

```bash
python3 scripts/c_stage3_integration_smoke.py --mode text --scenario full
```

fake-voice(정해 둔 답을 순서대로, TTS는 실제):

```bash
env C_DESIGN_USE_LLM=1 OPENAI_LLM_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" OPENAI_TTS_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" python3 scripts/c_stage3_integration_smoke.py --mode fake-voice --scenario full --answers "벤치처럼 길고 넓은 의자" "등받이를 더 높게" "좋아 이걸로 하자" "일부러 그렇게 놨어요" "마음에 들어"
```

실제 마이크·TTS(사용자 실행):

```bash
env C_DESIGN_USE_LLM=1 OPENAI_API_KEY="$(cat ~/C2_OpenAi_API_Key.txt)" OPENAI_LLM_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" OPENAI_TTS_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" python3 scripts/c_stage3_integration_smoke.py --mode mic --scenario full
```

offline 검증:

```bash
python3 -m pytest tests/integration/test_c_stage3_lifecycle.py -q
```
