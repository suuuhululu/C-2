# C Design 계약

## 최종 MVP Design 이행 (2026-10-07)

[최종 MVP](10_FINAL_MVP.md)는 LLM/사용자가 커스텀 의자를 대화로 디자인하고 **사용자가 설계를 확정한 뒤** 조립 순서/경로를 생성합니다. 아래 공개 함수·Schema·여섯 배치 필드는 기존 C 구현 계약입니다. `create_initial_design`의 후보 반환만으로 사용자의 설계 확정·Robot 시작을 표시하지 않습니다.

요구 구체화·후보/확정·취소/실패와 Design 버전의 연결은 새 이행 계약이 필요합니다. C는 Design/HRI를 제공하며 joint/TCP/힘·MotionPlan을 생성하지 않습니다. 연구 첨부의 Assembly Planner 역할 재배정은 아직 합의 대상입니다. 사용자별 저장에는 채택 Design과 사용자–Job 연결이 필요하며 C가 DB 완료·전체 조립 완료를 단독 선언하지 않습니다. 기존 두 stud 검사는 지지 위험·실제 안정성의 대체물이 아닙니다.

## 기존 C 공개 계약

상태: **확정 (2026-10-05 사용자 승인, WAVE 1) · Day4 공용 계약 정렬 (2026-10-06).** 시율(C) 파트의 공개 함수·입출력·Design 형식·검증·실패 반환을 정의합니다. 경계 형식과 의미는 [Day4 공통 인터페이스 계약](06_CONTRACT_DRAFT.md)(main), C·B·Backend 연결 합의(PR #6 `docs/09_C_B_BACKEND_HANDOFF.md`)와 2026-10-06 Slack 합의를 따르며, 이 문서는 C 쪽 생산·소비 규칙을 구체화합니다. 팀 공용 Owner는 [00_CURRENT_DECISIONS.md](00_CURRENT_DECISIONS.md)를 봅니다. 연결 담당 확인 항목은 [§11](#11-연결-담당-확인-항목)에 분리했습니다. 구조와 파일 책임은 [C_DESIGN_STRUCTURE.md](C_DESIGN_STRUCTURE.md), 진행 상황은 [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md)를 봅니다.

## 1. 용어

C 문서·코드·Fixture·테스트는 아래 팀 공용 용어만 씁니다. C 내부도 경계와 같은 필드명을 쓰며 변환 계층을 두지 않습니다.

| 공용 용어 | 근거 | 코드 식별자 | 의미 |
|---|---|---|---|
| Design | 06 §2 | `design` | 최종 목표 **전체** 배치. `design_version`과 `blocks`만 가짐 |
| Initial Design | 00 Initial / Revised | `design_version == 1` | 키워드로 처음 만든 Design |
| Revised Design | 06 §5 REVISE | (입력보다 큰 `design_version`) | 최신 Current를 보존해 새로 만든 전체 Design |
| 블록 | 06 §1 | `block` | 여섯 값으로 표현한 배치 하나 |
| Current | 00 Current | `current` | Backend가 채택한 실제 배치 |
| Difference | 06 §5 | `differences` | Backend가 판정한 Expected / Current 차이 |
| 변경 context | 00 F01 | (입력 묶음) | Design·채택 Current·Difference·지원 범위 |
| Intervention | 00 F06 | `run_intervention` | 실제 차이 발생 시 사용자 의도 확인 과정 |
| KEEP | 06 §5 | `KEEP` | 현재 채택 목표·`design_version` 유지. 최초 버전 복귀가 아님 |
| REVISE | 06 §5 | `REVISE` | 사람의 변경 의도를 반영한 전체 Design 후보 |
| UNCLEAR | 06 §5 | `UNCLEAR` | 판단 불가. 자연스럽게 다시 묻고(키워드 안내 없음) 재질문, 계속 불명확하면 명시 답변 대기 |
| 명시적 취소 | 09 취소 | `CANCEL` | 사용자의 취소 발화. HRI 결과가 아닌 C 내부 신호 |
| HRI 결과 | 06 §5 | `hri_result` | KEEP / REVISE / UNCLEAR 중 하나 |
| 질문 / 재질문 | 06 §5 | `questions` | C가 만든 질문 문장. 같은 문장을 화면·음성으로 제공 |

사용하지 않는 용어: Target Design, Modified Design, KEEP_TARGET, KEEP_CURRENT, KEEP_ORIGINAL, CREATE_REVISED, deviation, Decision, Brick(필드 묶음 이름), geometry, grid_x, grid_y, YELLOW, BLUE, block_id, parent_version, last_block_number, local_x, local_y, long_axis, design_local_stud.

## 2. 블록 필드 (06 §1)

| 필드 | 허용 값 | 정의 |
|---|---|---|
| `brick_type` | `1x2x1`, `2x2x1`, `2x3x1` | ASCII 소문자 `x`. `1x2x1`은 Stage 2 추가(가는 블록, red만: trim·rail·accent 등 작은 특징용) |
| `color` | `yellow`, `blue`, `red` | 소문자. `red`는 Stage 2 추가(`1x2x1`만) |
| `x` | 정수 0~23 | 24×24 Board stud 좌표, footprint의 최소 x 모서리. Robot mm·TCP 좌표 아님 |
| `y` | 정수 0~23 | footprint의 최소 y 모서리 |
| `layer` | 정수 1~5 | 1층이 판 위 첫 층(최대 5층: 2026-10-06 팀장 결정) |
| `orientation_deg` | `1x2x1`: 0 또는 90 / `2x3x1`: 0 또는 90 / `2x2x1`: 0 | `1x2x1`: 0 = X 1 stud · Y 2 stud, 90 = X 2 stud · Y 1 stud. `2x3x1`: 0 = X 2 stud · Y 3 stud, 90 = X 3 stud · Y 2 stud. `2x2x1`: X 2 · Y 2 |

- footprint 전체가 0~23 안에 있어야 합니다(예: `2x3x1` 0도 `x = 23`, `1x2x1` 90도 `x = 23`은 범위 초과).
- **색 × brick_type 허용 조합(최종 Stage 2 재고, 2026-10-08 사용자 결정)**: 실제 공급 재고에 있는 다섯 조합만 허용합니다. 그 밖의 조합은 brick_type·color가 각각 허용 값이어도 `invalid_combination`으로 거부합니다(§9.1). 단일 출처는 `validator.ALLOWED_COMBINATIONS`이며 블록 여섯 필드는 그대로입니다(새 필드 없음).

| color | 허용 brick_type | 금지 |
|---|---|---|
| `yellow` | `2x2x1`, `2x3x1` | `1x2x1` |
| `blue` | `2x2x1`, `2x3x1` | `1x2x1` |
| `red` | `1x2x1` (orientation 0 = X 1 · Y 2, 90 = X 2 · Y 1) | `2x2x1`, `2x3x1` |

- footprint 크기는 `validator.BRICK_SIZES`(0도 기준 X·Y stud 수, 90도면 바꿈), 허용 orientation은 `validator.ORIENTATIONS`가 단일 출처입니다.
- Stage 2 어휘(red, `1x2x1`)는 C에 적용됐지만 A·D·공유 문서는 아직 이전 어휘입니다. 바꿔야 할 지점은 [C_DESIGN_STAGE2_AD_HANDOFF.md](C_DESIGN_STAGE2_AD_HANDOFF.md)에 정리했습니다(C는 수정하지 않음).
- 정수 필드는 소수점 없는 JSON 정수만 허용합니다. `true`/`false`와 `1.0`은 정수가 아닙니다.
- C는 Board 좌표 규약만 사용합니다. Board 물리 방향과 Board → Robot / world 변환은 D 책임입니다.

## 3. Design 형식 (06 §2)

Design은 정확히 두 키를 가집니다. 그 외 키(`design_id`, 부모 버전, 생성 경로, 블록 ID 등)는 넣지 않으며 validator가 거부합니다.

| 필드 | 타입 | 의미 |
|---|---|---|
| `design_version` | int ≥ 1 | C 발급. Initial = 1, 전체 목표 배치가 실제로 바뀔 때만 +1 (§8.2) |
| `blocks` | 블록 배열, 1~40개(Stage 2 사용자 결정, 30 → 40: Revised richness v2 ≥ v1 + 6과 상한 충돌 방지) | 최종 목표 전체. 배열 순서는 의미 없음. 조립 순서는 A가 결정 |

```json
{
  "design_version": 2,
  "blocks": [
    {"brick_type": "2x3x1", "color": "blue", "x": 9, "y": 9, "layer": 1, "orientation_deg": 0}
  ]
}
```

생성 경로(MOCK / LLM) 같은 진단 정보와 설계 이름·설명은 Design 밖, envelope의 `design_metadata`에 둡니다(§6.1). layer 1~5·블록 수 1~40·brick_type·color는 validator 상수(`MAX_LAYER`, `MAX_BLOCKS`, `BRICK_TYPES`, `COLORS`)이며 LLM 프롬프트의 Rules 줄도 이 상수를 그대로 씁니다("blocks: 1..40", "brick_type: 1x2x1, 2x2x1, 2x3x1"). 허용 조합 줄("Allowed brick/colour combinations (stock): yellow: 2x2x1, 2x3x1; blue: 2x2x1, 2x3x1; red: 1x2x1 only. Never red 2x2x1 or 2x3x1, never yellow or blue 1x2x1.")은 `validator.ALLOWED_COMBINATIONS`로 만듭니다. Rules 줄의 orientation 문장과 red 안내("red 1x2x1 is the only red piece: use it for small features (trim, rail, accent, wing edge, armrest cap, backrest detail, border), not for large surfaces; it still needs 2 studs of support below. Red is optional, never required in quantity.")는 고정 문장입니다(2026-10-08 최종 재고).

### 3.3 Initial Design 배치

완성 Chair 전체 footprint(모든 layer 합집합의 bounding box)의 중심을 24×24 Board 중심에 최대한 맞춥니다. bounding box 크기가 W × H stud이면 최소 stud는 `x = (24 − W) // 2`, `y = (24 − H) // 2`입니다. 결과 footprint가 0~23을 벗어나면 §9.1 범위 검사로 거부합니다.

- **금지**: 특정 블록의 anchor를 `24 // 2 = (12, 12)`에 두는 구현. Board 중심은 stud 11과 12 사이이므로 (12, 12) anchor는 구조를 +X·+Y로 치우치게 합니다.
- 예: bounding box가 2x2 하나(W = H = 2)이면 최소 stud는 (11, 11)이고 footprint는 11~12로 중심에 대칭입니다. W = 5 → 9, W = 6 → 9, W = 7 → 8.
- 테스트 조건: Initial Design의 bounding box 최소 stud가 위 공식과 같아야 하며, Fixture·Designer·Test에서 `24 // 2`를 특정 블록 anchor로 쓰지 않습니다.

| 원칙 | Initial Design | Revised Design |
|---|---|---|
| 우선 기준 | Board 중앙 배치 | 최신 Current 보존 |
| 중앙 재정렬 | 위 공식으로 정렬 | **하지 않음** |
| 중심 이탈 | 공식 결과 외 불허 | 허용 (Current가 강제하는 위치를 따름) |
| 전체 이동(shift) | 해당 없음 | 조립된 블록은 움직일 수 없음, 미조립 블록의 기계적 일괄 이동 금지 (§8.6) |

## 4. 공개 함수 (`app.c_design.main`)

외부 모듈은 이 공개 함수들(§4.1·§4.2, Stage 3 Wave 1부터 §4.4 `review_design_candidate`)만 호출합니다. 두 함수 모두 예외를 밖으로 던지지 않고 §6의 결과 dict를 반환합니다. 후보 하나의 검증 탈락은 곧바로 Job 실패가 아니며 C 내부에서 **유한하게** 재생성합니다(§8.10). 실제 `main` 구현은 WAVE 4입니다.

실제 LLM 사용 여부는 호출 환경의 `C_DESIGN_USE_LLM=1`로 정하며 기본은 Mock입니다.

외부 provider key는 용도별 환경 변수 3개로 나누며 서로 대체하지 않습니다. 값은 호출 시점에만 읽고 출력·기록하지 않습니다.

| 환경 변수 | 용도 | 읽는 곳 |
|---|---|---|
| `OPENAI_LLM_API_KEY` | LLM Design 생성(Chat Completions) | `llm.py` (`LLM_KEY_ENV`) |
| `OPENAI_API_KEY` | STT (`whisper-1`) | `voice.py` (`STT_KEY_ENV`) |
| `OPENAI_TTS_API_KEY` | TTS (기본 `gpt-4o-mini-tts`, §10) | `voice.py` (`TTS_KEY_ENV`) |

LLM 모델은 `OPENAI_MODEL`(기본 `DEFAULT_MODEL`)입니다. 모델명이 reasoning 계열(`gpt-6`, `gpt-5`, `o1`, `o3`, `o4`로 시작)이면 요청에 `max_completion_tokens`(8000)와 `reasoning_effort`(medium)를 쓰고 `temperature`·`max_tokens`를 보내지 않습니다. 그 밖의 모델(gpt-4o 등)은 `temperature`·`max_tokens`를 씁니다. 따라서 Revised 재생성 temperature(0.3)는 reasoning 모델에서는 적용되지 않습니다. system prompt는 Initial(예시 설계 없이 넓은 의미의 앉는 가구)과 Revised(의자 형태 목표 + 검증 통과 예시)를 따로 씁니다.

LLM 모델은 역할별로 셋입니다(Stage 2 Wave 4c, 2026-10-08 사용자 결정). key는 모두 `OPENAI_LLM_API_KEY` 하나이며, 모델 환경 변수가 없으면 기본값을 씁니다.

| 역할 | 함수 | 모델 환경 변수 | 기본(코드) | 운영 |
|---|---|---|---|---|
| Design 생성·Initial 설명 | `generate_initial_design`, `generate_revised_design`, `describe_initial_design` | `OPENAI_MODEL` | `DEFAULT_MODEL` (`gpt-4o-mini`) | `gpt-6.1-sol` |
| Revised judge | `judge_revised_design` | `OPENAI_JUDGE_MODEL` (`llm.JUDGE_MODEL_ENV`) | `llm.DEFAULT_JUDGE_MODEL` (`gpt-4.1-mini`) | `gpt-4.1-mini` (§8.13) |
| 요청·답변 해석과 acknowledgment(`reply`) | `interpret_initial_request`, `interpret_intervention_answer`, `interpret_review_answer`(Stage 3 Wave 1, §4.4) | `OPENAI_AUX_MODEL` (`llm.AUX_MODEL_ENV`) | `llm.DEFAULT_AUX_MODEL` (`gpt-4.1-mini`) | `gpt-4.1-mini` |

보조 모델은 첫 TTS(acknowledgment)를 Design 생성보다 먼저, 빠르게 내기 위한 것입니다. Design 생성 정책·모델은 바꾸지 않습니다.

### 4.1 `create_initial_design(text=None, should_stop=None, preference_text=None, on_question=None, on_progress=None)`

| 입력 | 타입 | 의미 |
|---|---|---|
| `text` | str 또는 `None` | Mock 모드: 목표 문장(예: "오늘은 의자를 만들 거야", `parse_goal`). LLM 모드(Stage 2 Wave 4b): 사용자의 첫 자유 발화 전체(예: "오늘은 사과 같은 의자를 만들고 싶어요"). `None`이면 음성 모드: C가 인사하고 녹음·STT로 받음. str도 `None`도 아니면 `INVALID_INPUT` |
| `should_stop` | `callable() -> bool` 또는 `None` | D의 STOP·닫힌 요청 연결. 인사·되묻기 앞뒤, 요청 해석 중, 재생성 시도 사이에 확인하고 True면 `CANCELLED` / `STOPPED` |
| `preference_text` | str 또는 `None` | (LLM 모드, 텍스트 모드) 되묻기(follow-up)에 대한 답. `None`이면 되묻지 않고 "아무거나"로 진행. str도 `None`도 아니면 `INVALID_INPUT`. 음성 모드에서는 쓰지 않음 |
| `on_question` | `callable(str)` 또는 `None` | C가 인사·침묵 재질문·되묻기를 낼 때 그 문장으로 호출(HMI 표시). 예외는 호출자 책임(§4.2와 같음) |
| `on_progress` | `callable(dict)` 또는 `None` | (Stage 2 Wave 4c) 진행 단계마다 `{"stage", "message", "at": "HH:MM:SS.mmm"}`로 호출(§4.2 끝 "진행 표시"). 표시·로그용이며 envelope·Design에는 넣지 않음. `None`이면 이전과 같음. 예외는 호출자 책임

출력: §6 결과. 성공 시 `design`은 Initial Design, `hri_result`는 `null`.

흐름(Stage 2 Wave 4b, 2026-10-08 사용자 결정 — "의자 만들어줘" 같은 선행 발화를 요구하지 않음):

- **Mock 모드**(`C_DESIGN_USE_LLM` ≠ 1): 기존 흐름 그대로입니다(목표 문장 `parse_goal`, 음성 모드면 `voice.listen()` 한 번, 질문 없음, `questions` 빈 배열, D 통합 호환).
- **LLM 모드**:
  1. (음성) `voice.prewarm()` → 인사 "안녕하세요. 오늘 어떤 걸 만들고 싶으세요?"를 `questions`·`on_question`·TTS로 내고 `voice.listen(mode="free", beep=True)`로 한 번 듣습니다. 침묵이면 "잘 못 들었어요. 오늘 어떤 걸 만들고 싶으세요?"로 한 번만 다시 묻고, 그래도 침묵이면 "아무거나"로 진행합니다. (텍스트) `text`를 씁니다.
  2. `dialogue.parse_initial_request`가 `ANY`(특징·사물 단어 없는 명시적 "아무거나·알아서·맡길게요" 류)면 해석 호출 없이 무작위 family.
  3. 그 밖에는 `llm.interpret_initial_request(text)`(키 `llm.REQUEST_KEYS`). 해석 실패·키 누락은 "아무거나"로 진행하고 `design_metadata.error`에 `request_error`, 해석 중 STOP은 `CANCELLED` / `STOPPED`.
  4. `object`가 `UNSUPPORTED`면 (음성) "죄송해요, 지금은 의자나 벤치 같은 앉는 가구만 만들 수 있어요."를 읽고 `FAILED` / `UNSUPPORTED_OBJECT`.
  5. `object`가 `UNCLEAR`이거나 `sufficient`가 true가 아니면 해석의 `follow_up` 문장으로 **한 번만** 되묻습니다(음성: 질문 → `listen(mode="free", beep=True)`, 텍스트: `preference_text`가 있을 때만 질문으로 기록). 답이 명시적 "아무거나"면 무작위, 아니면 "첫 발화 / 답"을 합친 문자열로 한 번 다시 해석합니다. 답이 없거나 두 번째도 `UNCLEAR`·불충분·해석 실패면 더 묻지 않고 "아무거나"로 진행합니다. 두 번째가 `UNSUPPORTED`면 4와 같습니다.
  6. `llm.choose_initial_family(request)`: `SPECIFIC`이면 그 카탈로그 family, `CREATIVE`면 family 없음(None), 그 밖·"아무거나"는 균등 무작위. `llm.generate_initial_design(…, family, style_hint, concept)` — `CREATIVE`일 때만 `concept` = `style_hint`(카탈로그로 환원하지 않음) → validator(designer loop) → `llm.describe_initial_design(…, family, concept)` → `design_metadata`(§6.1, `family_source` = `"preference"` / `"random"` / `"creative"`).
  7. (Stage 2 Wave 4c) Design 생성 **전에 항상** 요청을 되짚는 확인(ack) 한 문장을 냅니다: 해석의 `reply`가 있으면 그것, 없으면(규칙 "아무거나"·침묵·해석 실패·되묻기 뒤 무작위) `dialogue.initial_ack_fallback`의 무작위 문장(바로 앞과 다른 문장). 음성 모드에서는 바로 읽고(질문이 아니므로 `questions`에 넣지 않음) 이어서 "디자인을 생성하고 있어요."를 읽은 뒤 생성합니다. 즉 6의 생성은 7의 ack 뒤에 시작합니다.
  - 음성 모드에서 듣기가 장치·STT 실패(`None`)면 `VOICE_IO_FAILED`(그때까지 낸 질문은 `questions`에 남음).

**Initial 요청 해석과 family·concept 함수 (Stage 2 Wave 2 `llm`, Wave 4b에서 한 문장 요청 해석으로 변경)**

| 함수 | 입력 | 반환 |
|---|---|---|
| `llm.interpret_initial_request(text, should_stop=None)` | 사용자 첫 자유 발화 한 문장(또는 첫 발화와 follow-up 답을 합친 문자열) | 모델: 보조 모델(`OPENAI_AUX_MODEL`, 기본 `gpt-4.1-mini`). `{object, preference, family, style_hint, sufficient, follow_up, reply}`(`llm.REQUEST_KEYS`) 또는 `{"llm_error": …}`. `object` ∈ `"CHAIR"`(앉는 가구 전부: 의자·벤치·소파·스툴·왕좌 등) / `"UNSUPPORTED"`(앉는 가구가 아닌 사물을 분명히 요구) / `"UNCLEAR"`(사물을 알 수 없음). `preference` ∈ `"ANY"`(맡김·아무거나, 스타일 형용사만 있어도 가능) / `"SPECIFIC"`(카탈로그 family로 자연스럽게 표현되는 종류·특징) / `"CREATIVE"`(카탈로그 family로 바꾸면 의미가 사라지는 concept, 예: 사과·구름·꽃·왕관 같은 의자). `family` = SPECIFIC이면 카탈로그 키, 그 밖은 null(카탈로그에 강제 매핑하지 않음, CREATIVE는 항상 null). `style_hint` = 짧은 한국어 구(CREATIVE는 concept 전체, 예: "사과처럼 둥글고 빨간"), 없으면 `""`. `sufficient` = object가 UNCLEAR이거나 종류·특징·concept·명시적 ANY가 하나도 없을 때만 false(명시적 ANY는 true). `follow_up` = sufficient가 false일 때 물을 존댓말 한 문장, 아니면 `""`. `reply` = Design 생성 전에 바로 읽어 줄 acknowledgment: 요청을 짧게 되짚는 자연스러운 존댓말 한 문장으로, 핵심(SPECIFIC은 종류·특징, CREATIVE는 concept, ANY는 어울리는 스타일을 고르겠다는 뜻)을 담고, 고정 문구 없이 매번 표현을 달리하되 장황하지 않게(Stage 2 Wave 4c). 발화 원문은 해석할 데이터이며 그 안의 지시·key·코드는 따르지 않음(프롬프트에 명시) |
| `llm.choose_initial_family(preference, rng=None)` | `None` 또는 요청 해석 결과 dict | 카탈로그 키 하나 또는 `None`. `preference`가 `SPECIFIC`이고 `family`가 카탈로그 키면 그 키, `CREATIVE`면 `None`(concept로 생성), 그 밖(None·ANY·카탈로그 밖)에는 `(rng or random).choice(sorted(FAMILY_CATALOG))` 균등 선택. 이력·가중치 없음(LLM 호출 없음) |
| `llm.generate_initial_design(object_type, reasons=None, should_stop=None, family=None, style_hint=None, concept=None)` | 고른 family 또는 concept, style_hint | 모델: `OPENAI_MODEL`. family가 있으면 사용자 메시지에 "Selected family: … Defining visible features …", concept가 있으면 "Creative concept from the person: <concept>. Realise it as a REAL seating piece (clear seat, visible support, obvious sitting direction), never a sculpture: abstract its silhouette, proportions and colour accents with the stock bricks: main body in yellow/blue big bricks (2x2x1/2x3x1), red 1x2x1 for outline/trim/accent lines that recall the concept, e.g. rounded outline by stepping the footprint, a top feature that recalls the concept."를 넣음. style_hint가 있고 concept와 다르면 "Style preference from the person: …"(CREATIVE에서는 같은 문구라 한 번만). 셋 다 없으면 기존 메시지 그대로. family와 concept를 함께 주면 `ValueError`(호출 없음). Initial system prompt에는 "주어진 family를 구현하라"(`_FAMILY_GIVEN`)와 "family 대신 concept가 주어질 수 있으며 그래도 실제 앉는 가구로, 조형물 금지"(`_CONCEPT_GIVEN`) 두 문장만 추가(예시 JSON 없음) |
| `llm.generate_initial_design(…, previous_candidate=None, scope=None)` (Stage 3 Wave 2) | Preview 검토 MODIFY의 직전 후보(Design dict)와 재생성 방식 | 둘을 함께 주면 family·concept·style_hint 줄 뒤에 직전 후보 문단을 넣음(§8.14: patch는 family·실루엣·대부분의 블록 유지 + 변경 적용, redesign은 참고만·뚜렷이 다른 설계·family 변경 허용, concept_change는 다른 concept였으니 배치 재현 금지). 하나만 주거나 scope가 `llm.REVIEW_SCOPES` 밖이면 `ValueError`(호출 없음). 없으면 기존 메시지와 같음. system prompt 불변 |
| `llm.describe_initial_design(design, should_stop=None, family=None, concept=None)` | Initial Design, 고른 family 또는 concept | 모델: `OPENAI_MODEL`. payload에 `selected_family`·`selected_family_features`·`concept`. 출력 키는 그대로이며 `family_design_match` ∈ `clear`/`weak`/`mismatch`는 "고른 family(와 defining features) 또는 concept를 실제 앉는 가구로 얼마나 실현했는가"(둘 다 없으면 보이는 family 기준)로 재정의(새 키 없음) |

Stage 2 Wave 2~4의 `llm.interpret_initial_preference`·`PREFERENCE_KEYS`·`SYSTEM_PROMPT_PREFERENCE`는 Wave 4b에서 위 `interpret_initial_request`·`REQUEST_KEYS`·`SYSTEM_PROMPT_REQUEST`로 대체하고 삭제했습니다.

`llm.FAMILY_CATALOG`는 앉는 가구 20종(dining chair, armchair, high-back chair, wingback chair, lounge chair, club chair, pedestal chair, sled-base chair, cantilever chair, chaise longue, stool, bar-stool-like seat, ottoman, bench, park bench, loveseat, sofa-like seat, daybed, throne, canopy chair)과 각각의 defining visible features(영어, 크기 포함, 좌표 없음)이고, `llm.CATALOG_TEXT`는 프롬프트용 목록입니다. 연결 흐름은 위 "흐름"입니다. 카탈로그는 hard constraint가 아닙니다: 일반 요청은 카탈로그 family로, 카탈로그로 환원하면 의미가 사라지는 창의적 concept는 family 없이 concept를 생성 프롬프트에 직접 전달합니다. 결과는 어느 경우든 실제 앉는 가구여야 합니다(조형물 금지).

**향후 옵션(미구현): 이미지·vision 검색.** 특정 제품 형태(예: 특정 브랜드 의자)처럼 말로 전하기 어려운 요청은 이미지 검색이나 vision 모델로 참고 형태를 얻는 방식을 검토할 수 있습니다. 현재 C에는 이미지·웹 검색 기능이 없으며 추가하지 않았습니다. 도입하려면 별도 사용자 결정과 dependency·비용·저작권 검토가 필요합니다.

### 4.2 `run_intervention(design, current, differences, text_answers=None, on_question=None, should_stop=None, on_progress=None)`

| 입력 | 타입 | 의미 |
|---|---|---|
| `design` | Design (§3) | 현재 채택된 Design |
| `current` | 블록 배열 | Backend 채택 Current (§5.1) |
| `differences` | Difference 배열, 1개 이상 | 이번 Intervention의 원인 차이 (§5.2). 빈 배열이면 `INVALID_INPUT` |
| `text_answers` | str 배열 또는 `None` | 텍스트 입력 모드: 질문마다 순서대로 쓰일 응답. `None`이면 음성 모드 |
| `on_question` | `callable(str)` 또는 `None` | C가 질문·재질문을 낼 때마다 그 문장으로 호출. D가 HMI 화면에 표시. 콜백이 던진 예외는 C가 잡지 않으며 호출자 책임(§4의 "예외 없음" 약속의 유일한 예외) |
| `on_progress` | `callable(dict)` 또는 `None` | (Stage 2 Wave 4c) §4.1과 같은 진행 이벤트(아래 "진행 표시"). `None`이면 이전과 같음
| `should_stop` | `callable() -> bool` 또는 `None` | 질문-응답 턴 사이와 재생성 시도 사이에 확인. True면 `CANCELLED` / `STOPPED` |

흐름: C가 질문 문장 생성 → `on_question` 통지 → (음성 모드) TTS 재생 → 재생 종료 후 듣기·STT → 응답 해석.

- 질문은 번호·선택지 없는 존댓말 주관식입니다(2026-10-08 사용자 확정, Stage 2 Wave 2). 차이 설명 앞뒤로 의도 여부("Design과 다르게 놓인 부분이 있는데, 의도하신 건가요?")를 묻고, 자유 설명을 유도하며, 실수라면 원래 자리로 고치는 길을 안내합니다.
- 자유 답변 해석(`dialogue.parse_response`): 취소 → 앞머리 예/아니요 → "일부러·의도·이대로·살려·새 설계·더 화려·다른 느낌" 등(REVISE) / "실수·잘못·원래대로·고칠게·되돌" 등과 "의도하지 않았어요"(KEEP) 구문. 부정된 구문은 뒤집지 않고, 두 부류가 함께 나오거나 아무것도 못 찾으면 LLM 모드에서만 `llm.interpret_intervention_answer`(답변 원문 + Difference)로 해석 → 그래도 아니면 UNCLEAR. LLM 해석 실패·`INTERVENTION_ANSWER_KEYS` 누락은 UNCLEAR(재질문), 해석 중 STOP은 `CANCELLED` / `STOPPED`. Mock 모드는 Rule만 씁니다. Stage 1의 "1번"·"2번" 답변은 질문에 안내하지 않지만 그대로 KEEP·REVISE로 받습니다(호환).
- `llm.interpret_intervention_answer` 반환 키(`llm.INTERVENTION_ANSWER_KEYS`)는 `decision`·`style_hint`·`reason`·`reply`입니다(Stage 2 Wave 4c에서 `reply` 추가). `reply`는 바로 읽어 줄 acknowledgment 한 문장(존댓말, 고정 문구 없이 매번 다르게): REVISE면 새 설계와 `style_hint`를 반영한 확인(예: "알겠습니다. 더 길고 넓은 형태로 다시 만들어볼게요."), KEEP이면 원래 자리로 고치면 그대로 진행한다는 안내(예: "네, 원래 자리로 고쳐 주시면 그대로 진행할게요."), UNCLEAR·CANCEL이면 `""`. 모델은 보조 모델(`OPENAI_AUX_MODEL`, 기본 `gpt-4.1-mini`)입니다.
- `llm.interpret_intervention_answer`의 decision 정의(Stage 2 Wave 4e, 실제 E2E에서 "어 할로윈 분위기 같지가 않아"가 KEEP으로 해석된 사례 보강, 키·구조 불변): 키워드가 아니라 문장 뜻으로 판단합니다.
  - REVISE = (a) 블록을 일부러 그렇게 놓았고 지금 배치를 살린 새 설계를 원함, 또는 (b) 현재 Design에 대한 불만·다른 느낌/모양/크기/분위기로의 변경 요청(예: "할로윈 분위기 같지가 않아", "내가 생각한 느낌이 아니야", "컵케이크처럼 안 보여", "더 단순하게 바꾸고 싶어", "이런 느낌 말고", "좀 더 화려했으면 좋겠어").
  - KEEP = 자기 배치 실수를 인정하거나 원래 자리로 되돌리겠다는 뜻만(예: "내가 잘못 놨어", "실수였어", "원래대로 고칠게", "내가 다시 놓을게").
  - UNCLEAR = 둘 다 아니거나 정말 애매함(예: "음… 좀 그런데") → 재질문. CANCEL = 그만.
  - 한국어 부정: "실수 아니야/아닌데"는 실수 부정이라 KEEP이 아님(REVISE 또는 UNCLEAR), "같지가 않아/안 보여/느낌이 아니야"는 현재 결과 부정이라 REVISE, "잘못한 것 같아"는 실수 인정이라 KEEP.
  - 불만 표현의 `style_hint`는 바라는 방향으로 적습니다(예: "할로윈 분위기를 더 강하게", "컵케이크처럼 보이게", "더 단순하게"). `reason` 예: "현재 Design이 원하는 분위기와 다르다는 말씀으로 이해했어요.", REVISE `reply` 예: "알겠습니다. 할로윈 분위기가 더 잘 느껴지도록 다시 만들어볼게요."
  - 이 정의는 LLM 해석(fallback·style_hint 전용 호출)에만 적용됩니다. `dialogue.parse_response` 규칙은 바꾸지 않습니다.
- Preview 검토(Stage 3 Wave 1, §4.4)의 답변은 이 함수가 아니라 별도 함수 `llm.interpret_review_answer(text, kind, should_stop=None)`로 해석합니다. 값(APPROVE / MODIFY / UNCLEAR / CANCEL)·프롬프트(`SYSTEM_PROMPT_REVIEW`)·키(`llm.REVIEW_KEYS`)가 Intervention의 KEEP / REVISE / UNCLEAR와 섞이지 않습니다.
- LLM 해석이 REVISE이면 그 `style_hint`(사람이 원한 것)를 Revised 생성(`llm.generate_revised_design(…, style_hint=…)`)에 직접 넘기고 `design_metadata.style_hint`에 남깁니다(Stage 2 Wave 4 After 구조: 별도 설계 의도 단계 없음, 생성 → validator → judge → 필요 시 재생성 1회 → 재judge, §8.13). Rule이 REVISE로 정한 자유 답변(예: "일부러 그렇게 놨어요. 팔걸이로 살려주세요.")도 LLM 모드에서는 같은 함수를 한 번 불러 `style_hint`만 받습니다(decision은 Rule 결과 그대로, 해석 실패·키 누락은 힌트 없이 진행하고 재질문·metadata error 없음, STOP은 `CANCELLED` / `STOPPED`). 빈 힌트는 null입니다.

| 답변 (LLM 모드) | `interpret_intervention_answer` 호출 |
|---|---|
| Rule이 REVISE로 정한 자유 답변("일부러…", "네" 등) | 1회(style_hint만 사용) |
| Rule이 정하지 못한 답(두 부류·무일치·부정 구문) | 1회(decision·style_hint 사용, 같은 답에 두 번 부르지 않음) |
| 숫자 답("2번"·"2번이요"·"이번" 등 답변 전체가 숫자 토큰), KEEP, CANCEL | 0회 |
| Mock 모드 | 0회 |
- UNCLEAR → "제가 잘 못 알아들었어요. 어떤 부분을 바꾸고 싶으신지 조금만 더 말씀해 주시겠어요? 실수로 놓으신 거라면 그렇게 말씀해 주셔도 돼요." + 질문 전체로 재질문(Stage 2 Wave 4e: 번호·키워드 안내 없음, 규칙 표는 늘리지 않고 불만·변경 요청의 뜻은 LLM 해석이 판단). 계속 불명확하면 사용자의 명시적 답변을 기다립니다.
- 텍스트 모드에서 `text_answers`가 소진될 때까지 불명확이면 `hri_result = "UNCLEAR"`로 반환합니다.
- KEEP → 입력 `design`을 **변경 없이** 그대로 반환. LLM 호출 없음, `design_version` 동일.
- REVISE → Revised Design을 생성·검증해 반환(§8).
- 명시적 취소 발화(`CANCEL`, 예: "취소할게") → `status: CANCELLED`, `error.code: USER_CANCEL`.

**진행 표시·확인 문장 (Stage 2 Wave 4c, 2026-10-08 사용자 결정)**

| 함수 | `on_progress` 단계 순서 |
|---|---|
| Initial (LLM) | (음성) `LISTENING` → `UNDERSTANDING`(발화 확보 뒤, 해석 전; 되묻기 답마다 다시) → `ACK` → `GENERATING` → `VALIDATING`(유효 후보 확정) → `DESCRIBING` → `READY` |
| Revised (LLM) | (음성) `LISTENING` → `UNDERSTANDING`(답변마다) → `HRI_INTERPRET`(답변 결정 직후, 디버그) → `ACK`(REVISE) 또는 `KEEP_ACK`(KEEP, 여기서 끝) → `GENERATING_REVISED` → `VALIDATING` → `JUDGING` → (재생성이면 `REGENERATING` → `VALIDATING` → `JUDGING`) → `READY_REVISED`. escalation 질문 전 `ESCALATION` |
| Mock | Initial `GENERATING` → `VALIDATING` → `READY`, Revised `GENERATING_REVISED` → `VALIDATING` → `READY_REVISED`만(ack·음성 없음) |
| 공통 끝 | 결과가 실패·취소면 마지막에 `FAILED`·`CANCELLED`(message = `"<error.code>: <error.message>"`) |

- `HRI_INTERPRET`(Stage 2 Wave 4e, LLM 모드 Intervention, 음성 없음): 답변마다 결정이 정해진 직후(ACK·KEEP_ACK·재질문 전) 1회, message = `"decision=<KEEP|REVISE|UNCLEAR|CANCEL> source=<rule|llm> reason=<LLM reason 또는 빈칸> style_hint=<힌트 또는 빈칸>"`. `source`는 decision을 정한 쪽이며(Rule이 정하고 style_hint만 LLM에서 받은 경우는 `rule`), 표시·로그 전용으로 envelope·Design에 넣지 않습니다. Mock은 보내지 않습니다.
- 단계 이름은 `main.PROGRESS_STAGES`, 고정 안내 문장은 `dialogue.PROGRESS_MESSAGES`입니다. `ACK`·`KEEP_ACK`의 message는 그때 낸 확인 문장입니다.
- **확인(ack) 규칙**: REVISE이면 Revised 생성 **전에 항상** 확인 한 문장을 냅니다. 이 문장은 LLM이 REVISE로 해석한 답의 `reply`이고, 그것이 없으면(숫자 답 "2번"·해석 실패·LLM decision이 REVISE가 아닌 style_hint 전용 호출) `dialogue.revise_ack_fallback(style_hint)`의 무작위 문장입니다. KEEP이면 `dialogue.keep_ack()`(escalation에서 원래대로 옮기겠다는 답 포함). Current support 위반으로 바로 escalation하는 경우에는 생성하지 않으므로 ack가 없습니다.
- **음성**: LLM 음성 모드에서만 ack·KEEP 확인과 `dialogue.PROGRESS_TTS_STAGES`(`GENERATING`·`READY`·`GENERATING_REVISED`·`JUDGING`·`READY_REVISED`)의 고정 문장을 읽습니다. `LISTENING`·`UNDERSTANDING`·`VALIDATING`·`DESCRIBING` 등은 콜백·로그만. 텍스트 모드와 Mock은 아무것도 읽지 않습니다(콜백만).
- 음성 순서 예: 인사 → (사용자 발화) → ack → "디자인을 생성하고 있어요." → (생성) → "디자인이 완성됐어요." / 질문 → (답변) → ack → "수정된 디자인을 만들고 있어요." → "완성된 디자인을 확인하고 있어요." → "수정된 디자인이 완성됐어요.". ack는 Design 생성을 기다리지 않습니다.

질문 문장·재질문 문장은 C가 만듭니다. D는 질문 문자열을 C에 주지 않습니다. 질문은 블록 ID 대신 위치로 블록을 가리킵니다(예: "(x=3, y=5) 2층 블록").

### 4.3 무응답 (Day4)

Day4에는 시간 기준 자동 취소·자동 KEEP·임의 종료가 없습니다(06 §5, 09 무응답). 사용자 입력을 기다리며, 종료는 D/HMI STOP(`should_stop`) 또는 사용자의 명시적 취소뿐입니다.

| 상황 | C 동작 |
|---|---|
| 침묵·잡음(STT 결과 빈 문자열) | 계속 기다림. 시간 기준 확인 질문·최종 안내 없음 |
| 의미 있는 발화(정규화 후 비어 있지 않은 STT 텍스트)인데 불명확 | 자연스러운 재질문(§4.2 UNCLEAR 문장)과 짧게 알려 주고 질문 전체로 재질문 |
| STOP | `CANCELLED` / `STOPPED` |
| 명시적 취소 발화 | `CANCELLED` / `USER_CANCEL` |
| 장치·엔진 실패 | 무응답이 아님. 녹음 장치·STT 실패는 §10에 따라 `VOICE_IO_FAILED` |

음성 I/O(`voice`, WAVE 6)는 순차로 동작합니다. `speak`는 TTS 재생이 끝나고 짧은 지연(기본 0.5초)을 기다린 뒤 돌아오며, 그 뒤에야 `listen`이 마이크 입력을 엽니다(질문 음성을 답으로 다시 인식하지 않음). `listen` 1회는 소리 크기(RMS) 기준으로 발화를 판정합니다. 스트림을 연 직후 0.2초는 버리고(warm-up: open 직후 레벨 변화·직전 재생 잔향 제외) 그다음 0.5초 동안 방 소음(noise floor, 블록 RMS 중앙값)을 재고, 판정 기준을 max(600, noise floor × 3)으로 정합니다(적응형 임계값: 방 소음이 커도 소음을 발화로 오인하지 않음). 그다음 발화 시작을 기다리고(기본 최대 8초), 발화 직전 0.3초를 앞에 붙여(첫 음절 보존) 발화 끝 무음(기본 1초) 또는 발화 시작부터 최대 길이(기본 10초)에서 녹음을 끝냅니다. 앞뒤 무음은 0.2초만 남기고 잘라 냅니다. 발화가 없거나, 발화로 판정된 길이가 0.2초 미만이거나, 잘라 낸 녹음 전체가 기준의 절반보다 약하면 STT를 호출하지 않고 빈 문자열을 돌려줍니다(무음·소음에서 STT가 자막형 문장을 지어내는 것을 막음). 2초보다 짧은 녹음은 앞 0.3초·뒤 나머지를 무음으로 채워 2초로 보냅니다(1초 미만 클립은 whisper 환각이 잦음). STT 요청에는 `language=ko`와 도메인 어휘 힌트(`prompt`: 의자·벤치·소파·스툴·만들어줘·만들고 싶어)를 함께 보내고 응답은 `verbose_json`으로 받습니다. 힌트에는 취소·원복·재설계 어휘와 숫자("1번"·"2번")를 넣지 않습니다(되풀이돼도 응답 의미가 바뀌지 않게, 숫자 힌트는 짧은 "2번"에 "3번, 4번, …" 나열을 지어내게 함). segment가 없거나 모든 segment의 `no_speech_prob`가 0.8 이상이면 빈 문자열(발화 없음)로 처리하고 `last_error`에 `stt_no_speech`를 남깁니다(짧은 정상 발화도 0.55 안팎이라 보수적으로 둠). STT 결과가 힌트 전체이거나, 힌트 항목을 3개 이상 담고 그 항목들을 지운 나머지가 2자 이하(사실상 힌트 나열뿐)이면 힌트를 되풀이한 것으로 보고(2026-10-08: 힌트 단어가 여럿 든 정상 자유 발화는 통과) 빈 문자열(발화 없음)로 처리하며 `last_error`에 `stt_prompt_echo`를 남깁니다. 환경 변수 `C_VOICE_DEBUG_DIR`이 있을 때만 STT에 보낸 WAV와 통계(길이·RMS·peak·noise floor·기준·발화 길이·잘라 낸 길이)를 그 폴더에 덮어써 남깁니다(기본 off, key 미기록). 통계에는 STT 전송 여부(`stt_called`)와 빈 문자열로 끝난 이유(`reason`: no_speech_detected / too_short / weak_input / no_speech_prob / prompt_echo)가 들어가며, STT를 부르지 않은 경우에는 통계만 남기고 이전 WAV는 지웁니다. `listen(on_ready=None)`의 선택 콜백은 warm-up·소음 보정이 끝나 발화를 기다리기 시작할 때 1회 호출되며(안내 표시용, 콜백 예외는 그대로 전파), `main`은 쓰지 않습니다(기본 None). 장치·STT 실패는 `None`입니다. 수치는 `voice` 모듈 상수입니다. 별도 thread·watchdog 없이 `main` 대화 루프에서 `should_stop`을 확인합니다. 텍스트 모드에는 대기가 없습니다.

Stage 2 Wave 4b(2026-10-08 사용자 E2E 로그 확정 원인 반영): `listen(on_ready=None, mode="short", beep=False)`. `mode="free"`(Initial 요청·되묻기 답·Intervention 답변)는 발화 시작 대기 10초·끝 무음 1.5초(말 사이 쉼에서 끊기지 않게), `"short"`(기본, D·Mock 경로)는 위 값(8초·1초) 그대로입니다. `beep=True`면 소음 보정이 끝난 직후 880 Hz 0.12초 알림음을 내고 0.3초 입력을 버린 뒤(그다음 `on_ready`) 발화를 기다립니다(알림음 출력 실패는 무시하고 계속 들음). 무음 판정은 whisper와 같은 복합 조건입니다: segment마다 `no_speech_prob` ≥ 0.8 **그리고** `avg_logprob` < −1.0일 때만 무음이고(모든 segment가 무음일 때 빈 문자열), `avg_logprob`가 없는 segment는 `no_speech_prob`만 봅니다. 디버그 통계에 `avg_logprobs`를 함께 남깁니다. `voice.prewarm()`은 음성 모드 Initial 시작 때 장치 준비(지연 import·입력 스트림 open/close)를 미리 하며 실패해도 예외 없이 `False`입니다. `record()`는 여전히 인자 없이 호출·대체할 수 있습니다(듣기 방식은 `listen`이 모듈 안에서 넘김).

### 4.4 `review_design_candidate(candidate, *, kind, design_metadata=None, previous_design=None, current=None, differences=None, text_answers=None, on_question=None, should_stop=None, on_progress=None)` — Preview 검토 (Stage 3 Wave 1·2)

**호출 전제**: D가 Candidate Design(Initial 또는 Revised)의 HMI Preview 표시를 끝낸 뒤 부릅니다. C는 Preview를 그리지 않고, 표시 완료를 확인하지도 않습니다. 이번 Wave에서 D 코드는 바뀌지 않았습니다(D 연결은 handoff 42번).

| 입력 | 타입 | 의미 |
|---|---|---|
| `candidate` | Design (§3) | 화면에 보인 후보. §9.1 `validate_design`을 통과해야 하며(아니면 `INVALID_INPUT`, `details`에 사유), C는 바꾸지 않고 같은 내용을 새 객체로 돌려줍니다 |
| `kind` | `"initial"` 또는 `"revised"` (키워드 전용) | 질문 문장과 LLM 해석 문맥. 그 밖의 값은 `INVALID_INPUT` |
| `design_metadata` | dict 또는 `None` | 후보의 metadata. 복사해 `review`를 붙여 돌려줌(입력은 바꾸지 않음). dict도 `None`도 아니면 `INVALID_INPUT`. `selected_family`·`family_source`·`style_hint`·이전 `review`(round·concept)가 검토 해석 문맥과 MODIFY 재생성에 쓰임 |
| `previous_design` / `current` / `differences` | Design / 블록 배열 / Difference 배열 (Stage 3 Wave 2) | `kind="revised"`일 때 **필수**: 채택(Approved) Design, Current, 이번 Intervention의 Difference. 하나라도 없거나 `validator.check_intervention_input` 위반이면 `INVALID_INPUT`. `kind="initial"`은 쓰지 않음 |
| `text_answers` | str 배열 또는 `None` | 텍스트 모드 답변. `None`이면 음성 모드 |
| `on_question` / `should_stop` / `on_progress` | §4.2와 같음 | 질문·재질문 표시, STOP, 진행 이벤트 |

**네 상태 (Intervention의 KEEP / REVISE / UNCLEAR와 별개, 값·파서·프롬프트를 섞지 않음)**

| `hri_result` | 의미 | 결과 |
|---|---|---|
| `APPROVE` | 이 후보가 마음에 들어 이대로 진행 | `status: OK`, `design` = 입력 후보 |
| `MODIFY` | 바꾸고 싶음 | (LLM 모드, Stage 3 Wave 2) `status: OK`, `design` = **새 Candidate**(Approved 아님 — 승인은 다음 검토의 APPROVE, 채택은 D), `design_metadata` = 새 후보의 metadata + `review`. (Mock) `design` = 입력 후보 그대로(재생성 없음). 생성 실패는 아래 "실패" |
| `UNCLEAR` | 재질문 1회 뒤에도 불명확(침묵 포함), 또는 텍스트 답변 소진 | `status: OK`, `design` = 입력 후보 |
| `CANCEL` | 작업 중단 | `status: CANCELLED`, `hri_result: "CANCEL"`, `error.code: USER_CANCEL`, `design` = 입력 후보 |

흐름:
1. 질문 "완성된 디자인이 화면에 표시됐어요. 어떠신가요?"(revised: "수정된 디자인이 화면에 표시됐어요. 어떠신가요?")을 `questions`·`on_question`에 내고, LLM 음성 모드면 TTS로 읽습니다.
2. (음성) `voice.listen(mode="free", beep=True)` / (텍스트) `text_answers`로 답을 받습니다.
3. `dialogue.parse_review_response`로 해석합니다. 취소 구문 → 짧은 긍정 답 전체("좋아요" 등) → 작은 APPROVE·MODIFY 구문 표 순서이고, 숫자 답은 받지 않습니다. 두 부류가 함께 나오거나, 부정어가 섞이거나("나쁘진 않은데…"), 무일치면 LLM 모드에서만 `llm.interpret_review_answer(text, kind)`(키 `llm.REVIEW_KEYS` = decision·style_hint·reason·reply)로 넘깁니다. 해석 실패·키 누락은 UNCLEAR입니다. Mock 모드는 규칙만 쓰고 음성을 내지 않습니다.
4. 규칙이 MODIFY로 정한 답은 LLM 모드에서 같은 함수를 한 번 더 불러 `style_hint`·`reply`만 받습니다(decision은 규칙 그대로, 실패면 힌트 없이 진행).
5. UNCLEAR이거나 침묵이면 "어떤 부분을 바꾸고 싶으신지 조금만 더 말씀해 주시겠어요? 이대로 괜찮으시면 그렇게 말씀해 주셔도 돼요."로 **한 번만** 다시 묻습니다.
6. 확인 문장(ack)은 LLM `reply`가 있으면 그것, 없으면 `dialogue.approve_ack` / `modify_ack_fallback(style_hint)` / `cancel_ack`입니다. LLM 음성 모드면 읽습니다.
7. (Stage 3 Wave 2, LLM 모드 MODIFY) ack 바로 뒤에 새 Candidate를 만듭니다. 해석에는 문맥 `context = {"family": metadata.selected_family, "concept": 후보의 concept}`(이전 검토가 갱신한 `review.concept`, 아니면 CREATIVE Initial의 `style_hint`)를 넘기고, 해석의 `scope`(`patch` / `redesign` / `concept_change`, 없거나 알 수 없으면 `patch`)·`concept`·`style_hint`로 재생성합니다(정책은 §8.14).
   - **initial**: `designer.build_initial_design("CHAIR", generate=…)`, generate = `llm.generate_initial_design(…, family=F, style_hint=H, concept=C, previous_candidate=candidate, scope=S)`.
     - `patch`: F = 기존 `selected_family`, C = 갱신 concept 또는 기존 concept, H = 기존 `style_hint`(기존 concept와 같으면 빼고) + " / " + 새 style_hint
     - `redesign`: F = C = None, H = 새 style_hint
     - `concept_change`: F = None, C = 갱신 concept, H = 새 style_hint
     - 진행은 `GENERATING` → `VALIDATING` → `DESCRIBING`(`describe_initial_design(…, family=F, concept=C)`) → `READY`. metadata는 §6.1 Initial 형식이고 `family_source` = scope입니다. design_version은 항상 1입니다.
   - **revised**: `designer.build_revised_design(previous_design, current, differences, generate=…, max_attempts=10, min_blocks=revised_min_blocks(previous_design))`, generate = `llm.generate_revised_design(previous_design, …, style_hint=H, previous_candidate=candidate, scope=S)`. 그 뒤 judge와 조건부 재생성(최대 1회)은 `run_intervention`의 REVISE와 같은 코드(`_finish_revised`)입니다. 진행은 `GENERATING_REVISED` → `VALIDATING` → `JUDGING` → (`REGENERATING`) → `READY_REVISED`. metadata는 §6.1 Revised 형식이고, design_version은 Approved + 1입니다(후보를 몇 번 고쳐도 늘지 않음). Current는 보존됩니다.
   - **실패**: 생성 한도 안에 유효 후보가 없으면 `FAILED` / `DESIGN_GENERATION_FAILED`, `hri_result: "MODIFY"`, design null. provider 실패는 `LLM_CALL_FAILED`, 생성·judge·설명 중 STOP은 `CANCELLED` / `STOPPED`.
   - APPROVE·UNCLEAR·CANCEL과 Mock 모드는 생성하지 않습니다. 텍스트 모드도 LLM 모드면 재생성합니다(음성만 없음).

STOP은 `CANCELLED` / `STOPPED`(design null), 음성 듣기 실패는 `VOICE_IO_FAILED`입니다.

**`design_metadata.review`** = `{kind, decision, style_hint, scope, concept, round, answers, source("rule" | "llm"), reply(낸 확인 문장 또는 null)}`.
- `round`(Stage 3 Wave 2): Candidate 반복 횟수입니다. 입력 metadata의 `review.round`(없으면 0)를 그대로 두고, MODIFY로 새 Candidate를 만들 때만 +1합니다.
- `answers`: 이번 호출에서 받은 의미 있는 답의 수입니다(Wave 1의 `round` 의미).
- `scope`·`concept`: MODIFY 해석 값입니다(그 밖에는 null).
- 입력 metadata의 다른 키는 그대로이고, Design `{design_version, blocks}`에는 아무것도 넣지 않습니다.

**진행 이벤트**: `REVIEW_LISTENING` → `REVIEW_UNDERSTANDING` → `HRI_INTERPRET`(decision·source·reason·style_hint, 모든 모드) → `REVIEW_ACK` → `REVIEW_READY`입니다. UNCLEAR면 REVIEW_LISTENING부터 한 번 더 하고, CANCEL은 REVIEW_ACK 뒤 `CANCELLED`로 끝납니다. LLM 모드 MODIFY는 REVIEW_ACK 뒤 7의 생성 단계로 이어지고 `REVIEW_READY` 대신 `READY`·`READY_REVISED`로 끝납니다. 음성으로 읽는 것은 질문·재질문·REVIEW_ACK와 생성 단계의 `PROGRESS_TTS_STAGES`(생성 중·판정 중·완성)이며 `PROGRESS_TTS_STAGES`는 바뀌지 않았습니다.

### 4.5 외부 caller 호출 계약 (Stage 3 Wave 3, 2026-10-11)

D(외부 caller)가 C를 호출하고 response를 받습니다. C가 D로 push하지 않습니다. 이 절은 C 쪽 준비 상태와 경계를 정합니다. 검증은 C-side caller fixture(fake D caller, fake PREVIEW_READY)로만 했으며, 실제 D/HMI integration은 팀 통합 단계입니다.

| public API | 언제 부르나 | C가 하는 일 | 돌려주는 것 |
|---|---|---|---|
| `create_initial_design(...)` (§4.1) | Initial 시작 | (음성) 인사 TTS → beep → STT → 해석 → ack → 생성·검증·설명 → READY TTS. D가 Initial STT를 대신하지 않는 구조 | Initial **Candidate**(version 1) envelope |
| `review_design_candidate(...)` (§4.4) | D가 Candidate의 Preview 표시를 끝낸 뒤 | 검토 질문 TTS → STT → 해석(APPROVE / MODIFY / UNCLEAR / CANCEL) → ack, LLM 모드 MODIFY면 새 Candidate 생성(§8.14) | 같은 후보(APPROVE·UNCLEAR·CANCEL) 또는 새 Candidate(MODIFY), `design_metadata.review` |
| `run_intervention(...)` (§4.2) | D가 Difference를 확정한 뒤 | 차이 설명 질문 TTS → STT → 해석(KEEP / REVISE / UNCLEAR) → ack, REVISE면 Revised Candidate 생성 | 입력 Design(KEEP) 또는 Revised **Candidate**(Approved + 1) |

- **동기 호출·독립성**: 세 함수는 동기 함수이며 호출 하나가 끝나면 envelope(§6)을 반환합니다. 각 호출은 독립적입니다. 이전 호출의 상태를 C 안에 보관하지 않고, 필요한 맥락(후보 Design, 그 `design_metadata`, Approved Design, Current, Difference)은 caller가 인자로 다시 넘깁니다. `main`에는 모듈 수준 요청·후보·버전 상태가 없습니다. 모듈 수준 상태는 `dialogue._last_pick`(ack 문장의 연속 반복 회피)과 `voice._last_*`(진단 기록)뿐이며 Design·version·round·판정에 쓰이지 않습니다(`tests/unit/c_design/test_stage3_contract.py`).
- **Candidate vs Approved**: C가 돌려주는 Initial·Revised·MODIFY 결과 Design은 모두 Candidate입니다. 승인은 검토의 APPROVE이고, **채택(Approved로 저장·A 요청)은 D**가 합니다. C는 Approved 여부를 Design에 표시하지 않습니다(§3 불변). version 정책은 §8.14입니다(Initial 후보 1, Revised 후보 Approved + 1 고정, 반복은 `review.round`).
- **Preview 완료 전제**: `review_design_candidate`는 caller가 Preview 표시를 끝냈다고 보고 부릅니다. C는 Preview 표시 여부를 확인하지 않으며(sleep·폴링 없음), 실제 Preview Ready 신호는 D/HMI 통합 단계의 일입니다.
- **D가 준비할 입력**: C가 받는 것은 후보 Design과 그 `design_metadata`(검토), Approved Design·Current 블록 목록·`differences`(Intervention·Revised 검토)뿐입니다. **Expected 전체는 받지 않습니다**(아래 결론).
- **DB·HMI·A 경계**: C는 DB에 쓰지 않고, HMI를 직접 그리지 않으며, A(Planner)를 부르지 않습니다. caller가 response를 받아 HMI 표시·Backend 상태·DB 저장·A 요청에 씁니다. 질문 문장은 `on_question`, 진행 단계는 `on_progress` 콜백으로도 전달합니다(표시·로그용).
- **correlation·stale (C가 지원하는 것 / caller가 관리할 것)**: C 세 함수와 voice·dialogue는 `request_id`·`job_id`·`current_revision`을 받지도 돌려주지도 않습니다(코드 grep으로 확인).

| 항목 | C가 지원 | caller(D)가 관리 |
|---|---|---|
| 요청 대응 | 동기 반환: 호출 한 번 = response 한 개(호출한 스레드가 받음) | `request_id`·`job_id`를 자기 요청 객체에 보관하고 response를 그 요청에 대응 |
| 중단 | `should_stop` 콜백(턴·시도 사이 확인 → `CANCELLED` / `STOPPED`) | 요청이 무효가 되면 `should_stop`이 True가 되게 함 |
| stale 판정 | 없음(입력 검증만, §9.1) | 응답 도착 시 활성 요청·`current_revision`·`design_version`이 그대로인지 확인하고 아니면 폐기 |
| 중복 호출 | 없음(재진입 금지 장치 없음) | 진행 중 호출이 있으면 새 호출을 시작하지 않음 |
| 버전 | Candidate `design_version` 발급(§8.2·§8.14) | Approved 채택·버전 이력 관리 |

  참고(GitHub 상태 기준, 최신이 아닐 수 있음, 읽기만 함): D의 `app/c_text_connection.py`는 이미 `CTextConnection.valid()`에서 `request_id`·`workflow_status`·`stop_request`·`job_id`·`current_revision`·`design_version`을 비교하고, `start()`에서 진행 중 호출이 있으면 `C_CALL_BUSY`로 거절하며, `finish()`에서 무효가 된 응답을 `_ignored`로 버리고, `should_stop`을 `threading.Event`로 넘깁니다. 이번 Wave에서 C에 correlation 필드를 추가하지 않습니다. 추가 후보(예: 입력 `request_id`를 envelope에 그대로 되돌려 주는 echo 필드)는 caller가 이미 같은 정보를 쥐고 있어 중복이며, 넣는다면 envelope 키 추가라 D 계약 합의가 먼저 필요합니다(구현하지 않음).
- **실패 경로**: 세 API가 침묵·장치 실패·LLM timeout·비 JSON·validator 실패·같은 후보 반복·사용자 취소·`should_stop`에서 돌려주는 값은 §10 "확인(Stage 3 Wave 4)" 행입니다. 어느 경우든 호출은 반환되며(listen·LLM·생성 횟수 상한), 예외는 Intervention 음성 침묵(caller의 `should_stop`으로만 끝남)입니다.
- **Expected 결론 (Expected 전체 불필요)**: `run_intervention(design, current, differences, …)`는 Expected 전체를 받지 않으며 추가하지 않습니다. 근거:
  - 입력 검사 `validator.check_intervention_input(design, current, differences)`는 Approved Design·Current·Difference만 봅니다.
  - 질문 문장 `dialogue.build_question`은 `design`·`current`를 쓰지 않고(`del design, current`), `_describe_difference`가 각 `differences[i].expected / actual`만으로 위치·차이를 설명합니다. escalation 질문(`escalation_question`)도 `differences`의 `actual`·`expected`만 씁니다.
  - Revised 생성 `llm.generate_revised_design(design, current, differences, …)`과 judge `llm.judge_revised_design(previous, design, current, differences)`는 Approved Design(전체 목표)·Current·Difference만 보냅니다. Current 보존 검사(`validate_revised`)는 Current만 씁니다.
  - Expected(채택 Plan 기준 Current + 완료 Step 효과)는 D(Backend)가 소유·계산하며(AGENTS), 어긋난 블록의 Expected 값은 이미 `differences[].expected`로 들어옵니다. Expected 전체를 더 받는 것은 중복입니다.

## 5. 입력 형식 (D → C)

C는 아래 필드만 읽고 나머지 키는 무시합니다. D는 자기 객체를 그대로 넘겨도 됩니다. D는 블록 ID를 주지 않으며 C는 같은 값 블록 간 대응(Data Association)을 하지 않습니다.

### 5.1 Current

블록 배열. 각 블록은 §2의 여섯 값이며 실제로 놓인 값입니다. 관측 순번·confidence 등 추가 키는 읽지 않습니다.

### 5.2 Difference

| 필드 | 타입 | 의미 |
|---|---|---|
| `expected` | 블록(§2) 또는 `null` | Expected에 있던 배치. `null`이면 Expected에 없던 블록 |
| `actual` | 블록(§2) 또는 `null` | Current의 실제 배치. `null`이면 누락된 블록 |

C는 두 블록의 값을 비교해 어떤 항목(위치·색·방향·크기·층)이 다른지 주관식 질문 문장의 차이 설명 줄에 씁니다. 어떤 블록끼리 대응하는지는 D가 준 쌍을 그대로 사용합니다.

## 6. 결과 형식 (C → D)

두 공개 함수는 같은 형식을 반환합니다. 진행 이벤트(`on_progress`, §4.2 끝)와 확인 문장은 envelope·Design에 넣지 않습니다(Stage 2 Wave 4c에서도 envelope 키와 Design `{design_version, blocks}`는 그대로).

| 필드 | 타입 | 의미 |
|---|---|---|
| `status` | `"OK"`, `"FAILED"`, `"CANCELLED"` | `CANCELLED` = STOP 또는 명시적 취소만. `FAILED` = 입력 오류, 재생성 한도 도달, 지속 장애 |
| `hri_result` | `"KEEP"`, `"REVISE"`, `"UNCLEAR"`, `null` | `create_initial_design`은 항상 `null` |
| `design` | Design 또는 `null` | 성공 시 채택 후보 Design |
| `design_metadata` | object 또는 `null` | `design`의 이름·설명·평가(§6.1). `design`이 `null`이면 항상 `null`. Design 구조(§3)에는 넣지 않음 |
| `questions` | str 배열 | 이번 호출에서 C가 낸 질문·재질문 문장(로그·표시용). Initial은 Mock 모드·선호 답이 없는 텍스트 모드에서 빈 배열, LLM 모드에서 선호 질문을 냈으면 그 문장 1개(§4.1) |
| `error` | `null` 또는 `{code, message, details}` | `status`가 `OK`가 아닐 때만 값이 있음 |

| 경우 | status | hri_result | design |
|---|---|---|---|
| Initial 성공 | OK | null | Initial Design |
| KEEP | OK | KEEP | 입력 Design 그대로 |
| REVISE 성공 | OK | REVISE | Revised Design (배치가 같으면 입력 Design 그대로, §8.2) |
| 텍스트 모드 응답 소진, 불명확 | OK | UNCLEAR | null |
| STOP / 명시적 취소 | CANCELLED | null | null |
| 입력 오류·재생성 한도·지속 장애 | FAILED | `REVISE`(Revised 생성 중) 또는 null | null |

`message`는 사람이 읽는 로그용 문장입니다. 분기는 `status`·`hri_result`·`error.code`로만 합니다. 생성 경로(MOCK / LLM)는 로그용 진단 정보이며 Design에 넣지 않습니다. 정확한 실패·취소 envelope는 D와 정상·실패·취소 예시로 확인합니다(§11).

### 6.1 `design_metadata` (2026-10-07)

Stage 2 Wave 3에서 Initial(LLM)에 `preference`·`selected_family`·`family_source`·`style_hint`·`family_design_match`, Revised(LLM)에 judge의 `chair_likeness`·`richer_than_previous`·`richer_why`와 `style_hint`를 실었습니다(아래 표). Mock metadata는 그대로입니다. Stage 2 Wave 4(2026-10-08 사용자 결정)부터 Revised에는 설계 의도 단계가 없으므로 `design_intent`는 항상 null이며(가짜 의도로 채우지 않음), 설명 필드는 모두 judge에서 옵니다.

표시·로그용 설명입니다. 분기에 쓰지 않으며, metadata를 만들지 못해도 설계 성공을 `FAILED`로 바꾸지 않습니다(`error` 필드에만 기록).

| 경우 | `design_metadata` |
|---|---|
| Initial 성공(LLM) | `{design_name, design_family, design_summary, visible_features, human_interpretation: null, judge: {silhouette_clarity, recognizable_family, completeness_score}, preference, selected_family, family_source, style_hint, family_design_match, source: "LLM", error}` — 설명 호출(`llm.describe_initial_design`) 결과와 family 선택. `preference` = 요청 해석 결과 dict(`REQUEST_KEYS`, Stage 2 Wave 4b) 또는 null(규칙 ANY·침묵·해석 실패 fallback), `selected_family` = 고른 카탈로그 키 또는 null(CREATIVE), `family_source` = `"preference"`(SPECIFIC 요청의 family) / `"random"` / `"creative"`(family 없이 concept로 생성), `style_hint` = 요청 해석의 짧은 한국어 구(CREATIVE는 concept) 또는 null, `family_design_match` = 설명의 `clear`/`weak`/`mismatch`(고른 family 또는 concept를 실제 앉는 가구로 실현한 정도, 없으면 null) |
| REVISE 성공(LLM) | 아래 Revised 필드표 |
| Mock(Initial·REVISE) | 고정 문자열: `design_name: "Mock 의자"`, `design_family: "chair"`, `source: "MOCK"`, `judge`·`design_intent`: null, `regenerations`: 0 |
| KEEP, UNCLEAR, FAILED, CANCELLED | `null` |
| Preview 검토 결과(Stage 3 Wave 1, §4.4) | 입력 `design_metadata`(없으면 `{}`)에 `review` 키 하나를 더해 그대로 돌려줌(아래 review 필드표). APPROVE·MODIFY·UNCLEAR·CANCEL 모두 같음 |

**`design_metadata.review` (Stage 3 Wave 1, `main.review_design_candidate`)**: 검토 결과 기록입니다. 형식은 `{kind, decision, style_hint, round, source, reply}`이며 Design(`{design_version, blocks}`)에는 넣지 않습니다(후보 Design은 그대로 반환, §3 불변). 기존 `design_metadata` 키(`design_name`·`judge`·`style_hint` 등)는 덮어쓰지 않고 그대로 둡니다. 이 위치에서 Stage 2 키와 이름이 같은 것은 `review.style_hint`뿐이며 최상위 `style_hint`(Initial 요청·Intervention 해석의 바람)와 별개입니다.

| review 필드 | 내용 |
|---|---|
| `kind` | `"initial"` / `"revised"` (검토한 후보 종류, 호출 인자 그대로) |
| `decision` | `"APPROVE"` / `"MODIFY"` / `"UNCLEAR"` / `"CANCEL"` (최종 해석, Intervention 값과 별개) |
| `style_hint` | MODIFY일 때 바꾸고 싶은 방향(한국어 구, LLM 해석 `style_hint`), 그 밖이나 얻지 못하면 null. Stage 3 Wave 2 후보 재생성의 입력 |
| `scope` | (Stage 3 Wave 2) MODIFY 재생성 방식 `"patch"` / `"redesign"` / `"concept_change"`(LLM 해석 `scope`, §8.14), 그 밖이나 얻지 못하면 null. 내부 값이며 public enum이 아님 |
| `round` | (Stage 3 Wave 2) 후보 반복 횟수: 입력 metadata의 `review.round`(없으면 0)에 MODIFY 재생성 때만 +1, APPROVE·UNCLEAR·CANCEL은 입력 값 유지(§8.14). Wave 1에서는 받은 답변 횟수였습니다 |
| `source` | 최종 decision을 정한 곳: `"rule"`(`dialogue.parse_review_response` 규칙) / `"llm"`(`llm.interpret_review_answer`) |
| `reply` | 읽어 준 acknowledgment 문장(LLM `reply` 또는 dialogue 고정 후보), 없으면 null |

| Revised 필드 | 내용 |
|---|---|
| `design_name` | judge의 `design_name`(judge를 쓸 수 없으면 null) |
| `design_family` | judge의 `design_family`(실제로 보이는 family, judge를 쓸 수 없으면 null) |
| `design_summary` | judge의 `why_it_is_complete` |
| `visible_features` | judge가 좌표에서 본 기하 특징 문구 목록(이름이 특징을 만들지 않음) |
| `human_interpretation` | `{placed_differently, interpretation, imagined_concept, lego_redesign, why_final_shape}` (judge `human_story`) 또는 null |
| `change_summary` | 이전 Design 대비 재설계 요약 문구 목록 |
| `interpretation_status` | `"clearly visible"` / `"weakly visible"` / `"mismatch"` (계획한 특징이 보이는 정도) |
| `judge` | `{recognizable_family, family_confidence, silhouette_clarity, explanation_required_to_understand, layer5_meaningful, completeness_score, awkward, chair_likeness, richer_than_previous, richer_why, verdict}` 또는 null(judge 응답을 쓸 수 없을 때). `verdict` = `"SHOWCASE"`(reads_as_seating·recognizable_family가 true, silhouette_clarity가 clear, explanation_required_to_understand가 false, chair_likeness가 not_chair가 아님, richer_than_previous가 true) 그 밖은 `"NOT_YET"`. feature_check 전부 visible은 조건이 아님 |
| `design_intent` | 항상 null(Stage 2 Wave 4부터 설계 의도 단계 없음, 키는 호환을 위해 유지) |
| `regenerations` | judge 결과로 다시 만든 횟수(0 또는 1, §8.12·§8.13) |
| `style_hint` | Intervention 답변의 LLM 해석이 준 바람(한국어 구) 또는 null(Rule로 결정·힌트 없음) |
| `source` | `"LLM"` / `"MOCK"` |
| `error` | null 또는 `{kind, message}`: `judge_error`(judge 응답 오류·필수 필드 누락·예상 밖 값, 재생성 없음), `regeneration_failed`(재생성이 유효 후보를 못 냄, 첫 설계 유지), `describe_error`(Initial 설명 실패), `request_error`(Initial 요청 해석 실패·`REQUEST_KEYS` 누락, ANY로 보고 무작위 family로 계속, Stage 2 Wave 4b; 이전 이름 `preference_error`). 여러 개면 마지막 오류 |

## 7. C → A 전달

A에게 가는 객체는 §3의 Design 그대로입니다(Initial·Revised 동일 형식, patch 아님). A는 블록의 여섯 값으로 Step 목표를 가리키고 `design_version`으로 기준 Design을 표시합니다. 재계획 입력의 Current는 A가 D에게서 받습니다(06 §6). C는 조립 순서·NextPart·Remaining·필요 블록 종류를 Design에 넣지 않으며 "다음 블록은 무엇" 같은 순서 지시도 하지 않습니다.

## 8. Revised Design 규칙

1. **full object**: Revised Design은 전체 블록 목록을 담은 새 Design입니다. 이전 Design과의 차이(patch)를 반환하지 않습니다.
2. **버전 (Owner = C)**: 검증을 통과한 후보의 블록 여섯 값 multiset이 입력 Design과 다를 때만 `design_version` = 입력 + 1입니다. 같으면 입력 Design을 그대로 반환합니다. 탈락 후보·KEEP·동일 배치·배열 순서 변화로는 증가하지 않습니다. 버전 값은 LLM이 아니라 Python이 정합니다. D는 채택 버전을 기록·관리하며 버전을 발급하지 않습니다.
3. **Current 보존 (hard)**: 최신 D 채택 `current`의 실제 배치 여섯 값 multiset이 Revised Design에 포함돼야 합니다(개수 포함). 잘못 놓인 블록도 실제 위치·방향 그대로 받아들입니다. 과거 완료 이력이나 ID로 고정하지 않습니다. 예: (5, 5)에 둘 블록을 (5, 6)에 놓고 REVISE → Revised Design에 (5, 6) 블록이 있음. 보존 대상은 LLM이 고르지 않고 Python이 `current`로 정합니다.
4. **블록 식별**: 경계 Design과 C 내부 모두 블록 ID를 두지 않습니다. 대응·보존은 여섯 값으로만 판단합니다. 내부 ID는 WAVE 5 LLM 프롬프트에서 필요해지면 결과 밖 진단 정보로 검토합니다.
5. Revised Design도 §9의 hard constraint를 모두 통과해야 반환합니다.
6. **기계적 평행이동을 생성 방법으로 삼지 않음**: 잘못 놓인 블록 하나에 맞춰 나머지 블록을 같은 거리만큼 옮기는(translate) 것을 Revised 생성 방법으로 쓰지 않습니다. 다만 완성된 앉는 가구가 된다면 본체가 옮겨지는 것은 허용합니다(2026-10-07 완화). 미조립 블록은 위치·방향·layer·역할을 바꿀 수 있고 Current를 기준으로 전체를 다시 설계합니다(§8.12). 결과가 hard constraint를 통과하면 validator가 거부할 근거는 없으므로 이 규칙은 Designer·Prompt의 soft goal(§8.9)입니다.
7. **사용자 선택 유지**: C는 사용자 동의 없이 선택을 취소하거나 KEEP으로 전환하거나 입력 Design을 대신 반환하지 않습니다. Revised 생성이 한도에 도달하면 `status: FAILED`, `hri_result: REVISE`, `error.code: DESIGN_GENERATION_FAILED`, `design: null`을 반환하고, 이후 전달 보류와 사용자 재확인은 D Workflow가 담당합니다.

### 8.8 Revised 생성 시 LLM에 주는 context

| 항목 | 출처 |
|---|---|
| 최종 목적물이 Chair라는 것 | C 내부 목표(Initial 요청) |
| 기존 Design 전체와 현재 `design_version` (맥락으로만: 지킬 기하가 아님, §8.12) | 입력 `design` |
| 최신 Current 전체(실제 위치·방향·색·layer) = 고정 블록 | 입력 `current` |
| Difference | 입력 `differences` |
| 사용자 의도 = REVISE | HRI 결과 |
| 지원 brick_type·color·orientation, Board 24 × 24, layer 1~5, 블록 수 상한 | §2, §3 |
| overlap·support·connectivity 규칙 | §9.1 |
| soft design goal | §8.9 |
| 직전 후보의 탈락 사유(재생성 시) | §8.10 |
| 사람이 말한 바람(`style_hint`, 없으면 "없음")·family 자유·chair-first·richer 문단, 최소 블록 수(LLM 모드) | Intervention 답변 해석(§4.2), `designer.revised_min_blocks` (§8.13) |
| judge 피드백(judge 결과 재생성 1회에만) | `llm.judge_feedback_text` (§8.12) |

LLM 출력은 블록 여섯 값의 목록(`{"blocks": [...]}`)뿐입니다. 버전은 Python이 채우고, 고정 블록을 바꾼 출력은 §9.1에서 거부합니다.

### 8.9 Hard constraint와 Soft design goal

| Hard constraint (validator가 검증, 위반 시 거부) |
|---|
| Current 보존 (§8.3) |
| 필수 필드·형식, 허용되지 않은 키 없음 |
| brick_type·color·orientation_deg·layer 허용 값 |
| footprint가 Board 0~23 안 |
| 블록 수 1~40 |
| 같은 layer overlap 없음 |
| support (A/C 합의된 Day4 기하 기준, §9.1) |
| connectivity |

| Soft design goal (Designer·Prompt에 반영, validator 미검증) |
|---|
| 사람이 앉는 가구로 한눈에 보임: 분명한 좌석, 좌석을 받치는 지지, 그 family에 필요한 큰 부분(전폭 높은 등받이, 양쪽 팔걸이, plinth, rail, crown) |
| 특징은 보일 만큼 크게(블록 두 개 이상 또는 한 줄 전체), 대칭이거나 의도적으로 균형. 한쪽만 튀어나온 블록 금지 |
| layer 5를 특징의 일부로 사용(crown, headrest, stepped top, tall back). validator 규칙이 아님 |
| 필요한 만큼 블록 사용(최대 40). 블록 수를 줄이는 것은 목표가 아님 |
| 기계적 평행이동이 아닌 전체 재설계(§8.6). 이전 Design과 다른 구조·family도 허용(§8.12) |

Soft design goal은 테스트로 강제하지 않습니다.

### 8.10 후보 탈락과 재생성

Validator가 후보 Design을 탈락시키는 것은 **후보 하나를 쓸 수 없다는 뜻**이며 곧바로 Job 실패가 아닙니다. 재생성은 유한합니다.

1. validator는 탈락 사유를 `[{rule, blocks, message}]` 목록으로 반환합니다(`blocks`는 관련 블록 여섯 값, 없으면 빈 배열). malformed JSON도 `rule: "malformed_output"`인 사유 하나입니다.
2. designer는 그 사유를 다음 생성에 전달해 "현재 후보는 이 이유로 사용할 수 없다. hard constraint와 Current를 유지하면서 다른 Design을 생성하라"고 재요청합니다.
3. **한도**: C 내부 최대 10회(`designer.MAX_ATTEMPTS = 10`). 10회 안에 유효 Design이 없으면 마지막 사유와 함께 `FAILED` / `DESIGN_GENERATION_FAILED`(details에 사유 목록). 탈락 후보는 버전을 소비하지 않습니다. 재생성 횟수는 C 내부 정책이며 공통 계약 숫자가 아닙니다(09).
4. busy loop 금지: 재요청 사이 1초 간격(`designer.RETRY_DELAY`, 테스트에서 0 주입 가능).
5. `should_stop`이 True면 시도 사이에서 중단합니다.
6. 연속 탈락 4회 이후에는 다른 구조로 재설계하도록 지시를 바꿀 수 있습니다(10회 한도 안). Mock 생성은 결정론적이므로 1회만 시도합니다.
7. 이 재생성(후보 탈락 → 다시 생성)은 §8.12의 judge 재생성(완성 설계가 알아보기 어려울 때 1회)·LLM provider API 재시도(§10)와 서로 독립입니다.

### 8.11 Escalation: 최소 물리 변경 제안 (C 정책, Day4 D 연결에서 필수 아님)

| 항목 | 내용 |
|---|---|
| 진입 조건 | 10회 한도 안에서 Revised 후보가 6회 연속 탈락, 또는 `current` 자체가 합의된 support 기준을 위반해 보존한 채로는 어떤 후보도 통과할 수 없는 경우(즉시, 재생성 시작 안 함) |
| 제안 내용 | `differences`에서 `actual`이 있는 블록을 현재 채택 Design 위치(`expected`)로 되돌리기. 임의의 새 위치는 제안하지 않음 |
| 질문 형태 | C(dialogue)가 만든 번호 없는 존댓말 문장. 블록은 위치로 표현. "…블록은 (x, y) N층 자리로 원래대로 돌려 주실 수 있을까요? 아니면 계속 새 설계를 찾아볼까요?" 답변은 "옮길게요·원래대로·고칠게요"(동의) / "계속·찾아·새 설계"(거절) / "취소"로 해석하며, "네"만으로는 고르지 않음. "1번"·"2번" 답변은 호환으로 받음 |
| 동의 | 사용자의 명시적 동의이므로 `hri_result: KEEP`, 입력 Design 그대로 반환 |
| 거절 | 남은 한도 안에서 재설계를 계속. `current`가 support를 위반한 경우에는 재설계할 수 없으므로 명시적 선택·취소·STOP을 기다림 |

Initial Design에는 고정 블록이 없으므로 escalation이 없습니다.

### 8.12 Revised 정책 EXPRESSIVE v4 (2026-10-07 사용자 승인)

- **Current만 고정**: "Preserve the Current exactly. Treat the previous Design as context, not as geometry to preserve. All non-Current blocks are future targets and may be freely moved, removed, replaced, or added. Redesign the remaining structure from scratch if that produces a more coherent, realistic, expressive seating-furniture design; the seat position, support layout, backrest, footprint and even the furniture family may change." 이전 Design은 사용자가 만들던 것(앉는 가구, 대략의 크기·색)을 알려 주는 맥락이며 지킬 기하가 아닙니다. family 변경도 허용합니다. 보수적인 낮은 1인 의자로 되돌리는 지시는 넣지 않습니다.
- **흐름(LLM 모드)**: ① 생성(§8.10 재생성 포함) → ② 완성 설계 judge(`llm.judge_revised_design`, 좌표만으로 평가) → ③ judge가 family를 알아볼 수 없다(`recognizable_family: false`)거나 실루엣이 모호(`silhouette_clarity: "ambiguous"`)할 때만 judge 피드백 문단으로 **재생성 최대 1회**(`main.METADATA_REGENERATIONS_MAX = 1`, 명시적 카운터) → 재judge → 최종. 2026-10-07의 생성 전 설계 의도 단계(`generate_design_intent`)는 2026-10-08 사용자 결정으로 삭제했습니다(§8.13).
- **재생성하지 않는 경우**: judge 응답이 provider 오류이거나 필수 필드(`recognizable_family`, `silhouette_clarity`, `reads_as_seating`, `explanation_required_to_understand`)가 없거나 예상 밖 값이면 그대로 끝내고 `design_metadata.error`에 `judge_error`를 남깁니다. awkward·weakly visible·feature mismatch만으로는 재생성하지 않습니다.
- **재생성 실패**: 재생성이 유효 후보를 못 내면 첫 설계와 그 judge를 그대로 반환합니다(`regeneration_failed`). 재생성 중 STOP이면 `CANCELLED` / `STOPPED`.
- 세 가지 반복은 서로 독립입니다: LLM provider API 재시도(§10, `llm.RETRY_BACKOFF`), 후보 탈락 재생성(§8.10, designer 시도 수), judge 재생성(최대 1회).
- escalation 뒤 "계속 찾기"로 다시 생성할 때도 ②·③을 똑같이 적용합니다. Mock 모드에는 judge가 없습니다.
- layer 5 사용·큰 특징·블록 수는 프롬프트의 soft goal이며 validator 규칙이 아닙니다. validator는 §9.1 그대로입니다(블록 수 상한만 40, Stage 2).

### 8.13 Stage 2 Revised 정책: After 구조(설계 의도 없음)·free-family·chair-first·richer (2026-10-08 사용자 결정, Wave 4)

- **목표**: 사람 배치를 문자 그대로 해석하는 것도, 최소 수정도 아닙니다. Current를 출발 조건이자 영감 단서로 쓰고, 이전 Design보다 **더 풍부하고 완성도 높으며 의자처럼 읽히는**(분명한 좌석, 읽히는 등받이, 앉는 방향) Revised Design을 만듭니다. 이전 Design은 맥락일 뿐이며, 핵심 문장 "Preserve the Current exactly. Treat the previous Design as context, not as geometry to preserve."와 조립 순서 규칙(새 블록을 이미 놓인 블록 아래층에 두지 않음)은 그대로입니다.
- **흐름(LLM 모드)**: Intervention 답변 해석(`dialogue.parse_response`, 필요 시 `llm.interpret_intervention_answer`로 `style_hint`, §4.2) → `llm.generate_revised_design` 직접 호출(설계 의도 호출 없음, §8.10 재생성 포함) → validator → judge → 필요 시 재생성 1회 → 재judge. `generate_design_intent`·`SYSTEM_PROMPT_INTENT`·`INTENT_KEYS`는 삭제했습니다. `design_metadata.design_intent`는 가짜로 채우지 않고 null입니다(§6.1).
- **생성** (`llm.generate_revised_design(design, current, differences, reasons=None, should_stop=None, feedback=None, min_blocks=None, style_hint=None, previous_candidate=None, scope=None)`; 마지막 두 인자는 Stage 3 Wave 2 Preview 검토 MODIFY 재생성용, §8.14): 사용자 메시지 첫 줄은 "The user chose REVISE. Design a complete seating-furniture piece around the blocks already on the board."이고 Current·Difference·이전 Design(맥락)·탈락 사유·최소 블록 수 문장·judge 피드백(재생성 때만)·`_REVISED_GUIDANCE`는 그대로입니다. 끝에 "Style hint from the person (follow it first): <style_hint 또는 없음>"과 "Choose the furniture family yourself; it may differ from the previous Design. The result must read as a chair first (a clear seat, a readable backrest, an obvious sitting direction) and be richer and more complete than the previous Design (at least M blocks, at most 40). Red exists only as 1x2x1: use it for trims, rails, accents or edges; the body is yellow/blue 2x2x1 and 2x3x1." (2026-10-08 최종 재고) 문단을 넣습니다(`min_blocks`가 None이면 괄호의 블록 수 부분을 뺍니다). system prompt(`SYSTEM_PROMPT_REVISED`)는 그대로입니다.
- **richness**: `designer.RICHNESS_MIN_DELTA = 6`, `designer.revised_min_blocks(design) = min(이전 블록 수 + 6, MAX_BLOCKS)`. LLM 모드에서만 `min_blocks`를 `designer.build_revised_design`과 `llm.generate_revised_design`에 넘깁니다(escalation 뒤 남은 4회와 judge 재생성 포함, Mock은 `None`). 값이 있으면 validator를 통과한 후보라도 블록이 그보다 적으면 `{"rule": "too_few_blocks", "blocks": [], "message": "Revised Design has N blocks; at least M required (previous K + 6, at most 40)"}`로 탈락시키고 §8.10 loop가 다시 만듭니다(validator 규칙은 그대로). `llm.generate_revised_design`은 값이 있으면 "The Revised Design must contain at least M blocks (the previous Design had K); use the extra blocks for meaningful chair structure, never filler."도 넣습니다.
- **judge** (`llm.judge_revised_design(previous, design, current, differences, should_stop=None)`): 설계 의도 인자와 payload의 `design_intent`를 없앴고, 설계 자체와 previous·Current·difference(추가·제거 블록 포함)만으로 판단합니다. `feature_check`(계획한 특징 대조)는 뺐고 `interpretation_status`는 judge가 본 family·특징이 블록에 얼마나 분명한지로 정의합니다. 나머지 출력 키(`design_name`, `design_family`, `family_guess_without_name`, `family_confidence`, `visible_features`, `change_summary`, `interpretation_status`, `recognizable_family`, `silhouette_clarity`, `explanation_required_to_understand`, `family_recognisable`, `looks_designed_not_patched`, `layer5_meaningful`, `completeness_score`, `human_story`, `silhouette_tags`, `chair_likeness`, `richer_than_previous`, `richer_why`, `awkward`, `reads_as_seating`, `why_it_is_complete`)는 유지합니다.
- **judge 모델**: `llm.DEFAULT_JUDGE_MODEL = "gpt-4.1-mini"`, 환경 변수 `OPENAI_JUDGE_MODEL`(`llm.JUDGE_MODEL_ENV`)로 바꿀 수 있습니다(예: gpt-6.1-sol로 복귀). key는 `OPENAI_LLM_API_KEY` 그대로이며, 생성·Initial 설명은 `OPENAI_MODEL`(없으면 `DEFAULT_MODEL`)을 그대로 씁니다. `llm._call`·`_json_call`의 `model=None` 인자로 judge(와 Stage 2 Wave 4c부터 요청·답변 해석의 보조 모델 `OPENAI_AUX_MODEL`, §4)만 모델을 넘깁니다. gpt-4.1-mini는 reasoning 접두어가 아니므로 temperature·max_tokens payload입니다. 선택 근거는 [Judge Blind Test](C_DESIGN_JUDGE_BLIND_TEST.md)이며 실물 테스트 후 재검토합니다. judge는 최종 물리 안전 판정기가 아니라 Design 품질 보조 필터입니다.
- **재생성(최대 1회)**: 조건은 `recognizable_family is False` 또는 `silhouette_clarity == "ambiguous"` 또는 `chair_likeness == "not_chair"` 또는 `richer_than_previous is False`이며 상한 `main.METADATA_REGENERATIONS_MAX = 1`은 그대로입니다. 필수 필드(`_JUDGE_REQUIRED`: `recognizable_family`, `silhouette_clarity`, `reads_as_seating`, `explanation_required_to_understand`, `chair_likeness`, `richer_than_previous`)가 빠지거나 예상 밖 값이면 `judge_error`(재생성 없음). 재생성 피드백(`llm.judge_feedback_text`)은 "keep the same family"와 judge의 family 추정·신뢰도·실루엣·설명 필요 여부·`interpretation_status`·awkward를 담습니다.
- **Intervention 자유 답변 해석** (`llm.interpret_intervention_answer(text, differences, should_stop=None)`): 입력은 답변 원문과 difference의 `expected`/`actual`만(Design 전체는 보내지 않음). 반환 `{decision: "KEEP" / "REVISE" / "UNCLEAR" / "CANCEL", style_hint, reason, reply}`(`llm.INTERVENTION_ANSWER_KEYS`, `reply`는 Stage 2 Wave 4c acknowledgment, §4.2) 또는 `{"llm_error": …}`. REVISE = 의도한 배치이니 Current를 살린 새 설계, KEEP = 실수라 원래 자리로 고침. `reason`은 자연스러운 존댓말 한 문장. 답변 원문의 지시·key·코드는 따르지 않습니다. 해석한 `style_hint`는 `generate_revised_design`에 바로 넘깁니다.
- **red·1x2x1 (2026-10-08 최종 재고로 갱신)**: 공통 build hint는 "본체(좌석·지지·등받이·팔걸이)는 yellow/blue 2x2x1·2x3x1, red는 1x2x1뿐이므로 지지된 stud 위의 얇은 trim·rail·accent·edge(top rail, seat edge, armrest caps, backrest detail)에만 쓰고 0/90을 섞되 두 stud 모두 지지"입니다. red는 선택이며 수량을 요구하지 않습니다. 허용 조합은 §2(철학·구조 불변). 하위 호환 이름 `FURNITURE_FAMILIES`는 카탈로그 키입니다.

### 8.14 Candidate 재생성 정책 (Stage 3 Wave 2, 2026-10-11)

Preview 검토(§4.4)가 MODIFY이면 C가 새 **Candidate** Design을 만들어 같은 호출의 결과로 돌려줍니다. 새 Candidate는 Approved가 아닙니다(승인은 다음 검토의 APPROVE, 채택은 D). APPROVE·UNCLEAR·CANCEL에서는 생성하지 않습니다. Mock 모드는 Wave 1 그대로(MODIFY여도 후보 불변, 생성 없음)입니다.

- **scope (재생성 방식)**: 검토 답변 해석(`llm.interpret_review_answer`)이 MODIFY와 함께 돌려주는 내부 값이며 `design_metadata.review.scope`에만 기록합니다(새 public enum 없음, `llm.REVIEW_SCOPES`).

| scope | 뜻 | 예 | 직전 후보 문단(생성 사용자 메시지) |
|---|---|---|---|
| `patch` | 현재 후보를 강하게 참고한 부분 수정, family·concept 유지 가능 | "등받이를 더 높게", "조금 더 길게", "팔걸이를 더 크게", "조금 더 화려하게"; CREATIVE concept 발전 "치즈컵케이크 느낌으로 바꿔줘"(concept "치즈컵케이크 느낌") | "Previous candidate (keep its family, overall silhouette and most of its blocks; apply this change: <style_hint>; move other blocks only as needed to stay valid): <json>" |
| `redesign` | 현재 후보는 참고만, 새 형태·family 변경 허용 | "완전히 다른 느낌으로", "다른 모양으로 다시", "그냥 새로", "지금 거 말고 다른 스타일" | "Previous candidate (reference only: make a clearly different seating design; the family may change; do not reproduce its layout): <json>" |
| `concept_change` | CREATIVE concept 교체 | "컵케이크 말고 바나나 느낌"(concept "바나나 느낌") | "Previous candidate followed a different concept; do not reproduce its layout: <json>" + 새 concept는 기존 concept 문단(§4.1) |

- **concept**: 현재 후보가 CREATIVE concept를 따르고 요청이 그것을 발전·교체하면 해석의 `concept`에 갱신된 concept 구가 옵니다(그 밖은 `""`). 검토 해석에는 현재 후보의 `{family, concept}`만 문맥(`context` → payload `current_candidate`)으로 보내며 블록은 보내지 않습니다.
- **family·concept 전달(main, §4.4)**: patch는 현재 family(있으면)와 concept(갱신값 또는 기존 creative concept)를 유지하고 style_hint를 변경으로 줍니다. redesign은 family·concept 없이 style_hint만, concept_change는 family 없이 새 concept와 style_hint를 줍니다. `generate_initial_design`의 family·concept 배타 규칙(§4.1)은 그대로입니다.
- **Revised 후보**: `llm.generate_revised_design(approved, current, differences, …, style_hint, previous_candidate=candidate, scope)`는 같은 방식의 "Previous Revised candidate" 문단(patch·redesign, Current 블록은 그대로라는 문장 포함)을 이전 채택 Design 줄 뒤에 넣습니다. Current 보존·`_REVISED_GUIDANCE`·min_blocks(`designer.revised_min_blocks(approved)`)·judge·재생성 ≤ 1은 §8.13 그대로입니다. `design` 인자는 Approved Design(버전 기준)입니다.
- **design_version**: Initial 후보는 항상 1(`designer.build_initial_design`가 발급). Revised 후보는 Approved + 1 고정(`designer.build_revised_design(approved, …)`가 approved 기준으로 발급)이며 후보 반복으로 증가하지 않습니다. 버전 값은 LLM이 정하지 않습니다(§8.2).
- **round**: 후보 반복 횟수는 `design_metadata.review.round`입니다. 입력 metadata의 `review.round`(없으면 0)에 MODIFY 재생성 때만 +1, APPROVE·UNCLEAR·CANCEL은 입력 값을 유지합니다(§6.1).
- 직전 후보 문단은 사용자 메시지에만 더하며 Initial·Revised system prompt와 설계 철학(§8.12·§8.13)은 바꾸지 않습니다. 재생성 후보도 §9.1 hard constraint(재고 조합 포함)를 그대로 통과해야 합니다.
- **unchanged_candidate (Stage 3 Wave 3, 2026-10-11)**: `designer.build_initial_design(..., differ_from=None)`·`build_revised_design(..., differ_from=None)`에 직전 후보를 주면 validator를 통과했어도 블록 multiset이 직전 후보와 같은 후보는 `{"rule": "unchanged_candidate", "blocks": [], "message": "candidate has the same blocks as the previous candidate; apply the requested change visibly"}`로 탈락시키고 같은 재생성 loop(§8.10, 최대 `MAX_ATTEMPTS`)이 사유를 생성기에 넘겨 다시 만듭니다. `review_design_candidate`의 MODIFY 재생성만 `differ_from=candidate`를 넘기며 `create_initial_design`·`run_intervention`은 None(기존 동작)입니다. 근거: Wave 3 fake-voice smoke에서 gpt-6.1-sol이 patch "등받이를 더 높게"에 직전 후보와 같은 37블록을 돌려준 사례. 끝까지 같으면 `FAILED`/`DESIGN_GENERATION_FAILED`(hri_result MODIFY)입니다.

## 9. 검증 책임

### 9.1 C (validator, LLM 없이 A / D / HMI 없이 단독 통과)

| 규칙 | rule |
|---|---|
| JSON 파싱 불가·객체 아님 | `malformed_output` |
| 필수 필드 누락 | `missing_field` |
| 정수 필드가 정수 아님(bool·1.0 포함) | `invalid_type` |
| 허용되지 않은 키(Design 두 키 외, 블록 여섯 키 외 — Robot·mm·TCP·joint field 유입 포함) | `unknown_key` |
| brick_type·color·orientation_deg(brick_type별)·layer 1~5 허용 값 | `invalid_value` |
| 색 × brick_type 허용 조합(§2 표: yellow·blue = 2x2x1·2x3x1, red = 1x2x1). brick_type·color가 각각 허용 값일 때만 검사. message 예 `red 2x2x1 is not in stock: red allows only 1x2x1`. Design·Revised 후보뿐 아니라 입력 Current·Difference 블록에도 적용(입력이면 `INVALID_INPUT`) | `invalid_combination` |
| footprint가 Board 0~23 밖 | `out_of_board` |
| 블록 수 1~40 밖 | `brick_count` |
| 같은 layer 안 footprint overlap | `overlap` |
| support: layer ≥ 2 블록은 바로 아래 layer 블록들과 겹치는 stud 수의 합계가 2 이상(아래 블록 개수 무관, 같은 stud 중복 합산 없음) | `support` |
| connectivity: 위아래 layer stud 겹침으로 연결했을 때 전체가 하나 | `connectivity` |
| Revised: §8.3 Current 보존 | `assembled_not_preserved` |

support는 **2026-10-06 세은(A)의 동의와 수현(D)의 회신으로 통일한 A/C Day4 기하 기준**입니다([A와 C의 지지 판정](09_C_B_BACKEND_HANDOFF.md#a와-c의-지지-판정)). 바로 아래층의 고유 stud 총 2개 이상을 확인하며, layer=1은 Board 위 첫 층으로 이 검사에서 제외합니다. 이 수치는 실제 체결·물리 안정성 검증 완료 또는 최종 프로젝트 전체의 영구 제한을 뜻하지 않습니다.

| Case | 바로 아래 layer와의 겹침 | 결과 |
|---|---|---|
| A | 아래 블록 1개와 2 stud (또는 3·4 stud) | 통과 |
| B | 아래 블록 2개와 각 1 stud, 합계 2 | 통과 |
| C | 아래 블록 여러 개, 합계 2 이상 | 통과 |
| D | 합계 0 또는 1 | 거부 |

`1x2x1`(Stage 2)은 stud가 2개뿐이므로 layer ≥ 2에 둘 때 **두 stud 모두** 바로 아래층 블록 위에 있어야 통과합니다(한 블록 위 Case A, 두 블록에 1 stud씩 Case B). 1 stud만 겹치면 Case D로 거부됩니다. 규칙 자체(`MIN_SUPPORT_STUDS = 2`)는 바뀌지 않았습니다.

입력 검사(`INVALID_INPUT`):

- `design`이 §3과 §9.1 Design 규칙을 만족하지 않음
- `current`·`differences`의 블록 값이 §2 범위·footprint 범위를 벗어나거나 허용 조합(§2)이 아님(`invalid_combination`). Revised의 Current 정확 보존은 Current가 이 규칙을 만족한다는 전제입니다
- `current` 자체가 같은 layer overlap을 위반함(같은 stud에 두 블록은 물리적으로 불가능한 관측 오류). support 위반은 입력 오류가 아닙니다: 실제로 가능한 상태이므로 Intervention을 정상 진행하고, REVISE이면 §8.11로 바로 갑니다. connectivity도 검사하지 않습니다.
- `differences`가 빈 배열이거나 `expected`·`actual`이 모두 `null`

### 9.2 A·D (참고, C가 대신하지 않음)

| 담당 | 검증 |
|---|---|
| A (세은) | 각 PLACE 시점의 bounds·공간 중복·지지·선행 관계와 invalid 사유(06 §6) |
| D (수현) | Observed 검증·Current 채택, Expected / Current 비교·Difference 판정, Design·Plan 최종 채택과 최신성(09 최종 채택) |

C의 Validator 통과는 후보 검증이며 최종 채택이 아닙니다.

## 10. 오류·실패 계약

| 구분 | 상황 | C 동작 | 반환 |
|---|---|---|---|
| 복구 | 후보 탈락, malformed LLM 출력, hard constraint 위반 | §8.10 재생성(한도 안) | 반환하지 않고 계속 |
| 복구 | 일시적 LLM·녹음·STT·TTS 실패 | 간격을 두고 재시도 | 반환하지 않고 계속 |
| 복구 | 불명확 응답 | 다시 설명해 재질문 | 반환하지 않고 계속 (텍스트 모드 소진 시만 `UNCLEAR`) |
| 복구 | `current`의 support 위반 | REVISE이면 즉시 §8.11 escalation | 반환하지 않고 계속 |
| 복구 | judge·Initial 설명·선호/답변 해석 호출 실패, judge 필수 필드 누락·예상 밖 값, judge 재생성 실패 | 설계는 그대로 반환, `design_metadata.error`에 `preference_error` / `judge_error` / `describe_error` / `regeneration_failed` 기록(§6.1, §8.12) | `OK` (metadata error만) |
| 취소 | D/HMI STOP (`should_stop`) | 턴·시도 사이에서 중단 | `CANCELLED` / `STOPPED` |
| 취소 | 사용자 명시적 취소 발화 | 중단 | `CANCELLED` / `USER_CANCEL` |
| 실패 | 호출자 입력 오류 | 즉시 반환 | `FAILED` / `INVALID_INPUT`, `UNSUPPORTED_OBJECT` |
| 실패 | 재생성 10회 한도 도달 | 반환 | `FAILED` / `DESIGN_GENERATION_FAILED` |
| 실패 | LLM provider 실패: 일시적 실패(network / timeout / 429 / 5xx)만 최대 3회(1·2·4초 backoff) API 재시도 후에도 실패. auth·키 없음(`OPENAI_LLM_API_KEY` 미설정, 다른 key로 대체하지 않음. 모델은 역할별 `OPENAI_MODEL` / `OPENAI_JUDGE_MODEL` / `OPENAI_AUX_MODEL`이며 key는 모두 이것 하나, §4)·비정상 응답(reasoning 모델에 지원하지 않는 파라미터를 보내 생기는 400 포함)은 재시도 없이 즉시. 재시도 사이 `should_stop` 확인 | 반환 | `FAILED` / `LLM_CALL_FAILED` |
| 실패 | 음성 입력 실패(Stage 2 Wave 4b: 자유 발화는 `listen(mode="free", beep=True)`, 무음은 `no_speech_prob` ≥ 0.8 그리고 `avg_logprob` < −1.0일 때만, §4.3): 녹음 장치를 열거나 읽지 못함, 또는 STT provider 실패(key: `OPENAI_API_KEY`. 일시적 network / timeout / 429 / 5xx는 최대 3회 API 재시도 후, auth·키 없음·비정상 응답은 즉시) | 반환 | `FAILED` / `VOICE_IO_FAILED` |
| 복구 | TTS 재생 실패(key: `OPENAI_TTS_API_KEY` 전용, 없으면 `OPENAI_API_KEY`로 대체하지 않고 `missing_key`. 모델은 `OPENAI_TTS_MODEL`, 기본 `gpt-4o-mini-tts`이며 `tts-1`·`tts-1-hd`에는 `instructions`를 보내지 않음. HTTP 실패 종류는 `auth`·`model_access`·`bad_param`·`billing`·`rate_limit`·`server`·`bad_response`) | 질문은 `on_question`으로 화면에 표시된 채 응답 대기를 계속하고 실패 사유는 `voice.last_error()`에 기록 | 반환하지 않고 계속 |
| 확인(Stage 3 Wave 4) | 음성 침묵(`listen`이 `""`): Initial | 인사 → 재질문(`SILENCE_REASK`) 1회, 그래도 침묵이면 "아무거나"로 생성(listen 2회) | caller가 받는 값: 생성 성공 시 `OK` / `null` / design v1 |
| 확인(Stage 3 Wave 4) | 음성 침묵: Preview 검토 | 재질문 1회(listen 2회) | `OK` / `UNCLEAR` / 입력 후보 그대로 |
| 확인(Stage 3 Wave 4) | 음성 침묵: Intervention | 시간 한도 없이 계속 듣고 매번 `should_stop` 확인(§4.3, Day4 정책) | caller가 STOP할 때만 반환: `CANCELLED` / `null` / `STOPPED`, design null |
| 확인(Stage 3 Wave 4) | `listen`이 `None`(장치·STT 실패): 세 API | 즉시 반환(listen 1회, 생성 0회) | `FAILED` / `null` / `VOICE_IO_FAILED`, design null |
| 확인(Stage 3 Wave 4) | LLM timeout(호출 하나당 transport 1 + 재시도 3 = 4회) | Initial은 요청 해석 실패 → "아무거나" 후 생성 실패. 해석만 실패한 검토 답은 UNCLEAR. provider 실패는 escalation 대상이 아님 | Initial `FAILED` / `null` / `LLM_CALL_FAILED`; 검토 MODIFY `FAILED` / `MODIFY` / `LLM_CALL_FAILED`; 검토 해석 실패 `OK` / `UNCLEAR`(재질문 뒤, 후보 그대로); Intervention REVISE `FAILED` / `REVISE` / `LLM_CALL_FAILED`. design null(UNCLEAR 제외) |
| 확인(Stage 3 Wave 4) | LLM 응답이 JSON이 아님 | 해석은 `bad_response`로 규칙·fallback 경로, 생성은 `malformed_output` 탈락·재생성 | Initial·검토 MODIFY: 생성 10회 후 `FAILED` / (`null`·`MODIFY`) / `DESIGN_GENERATION_FAILED`. Intervention: 6회 뒤 escalation 질문 → "계속" → 4회 → `FAILED` / `REVISE` / `DESIGN_GENERATION_FAILED`; 텍스트 답 소진이면 `OK` / `UNCLEAR`, design null |
| 확인(Stage 3 Wave 4) | 생성 후보가 계속 validator 실패(예: overlap) | 위와 같은 재생성·escalation | 위와 같음(`details`에 마지막 탈락 사유) |
| 확인(Stage 3 Wave 4) | 검토 MODIFY 생성이 직전 후보와 같은 블록 | `unchanged_candidate`로 탈락·재생성(§8.14) | 한 번 뒤 다르면 `OK` / `MODIFY` / 새 후보; 끝까지 같으면 생성 10회 후 `FAILED` / `MODIFY` / `DESIGN_GENERATION_FAILED`(`details` = `unchanged_candidate`) |
| 확인(Stage 3 Wave 4) | 사용자 취소 발화 | 검토·Intervention만 해석함. Initial에는 취소 발화 경로가 없어 caller가 `should_stop`으로 멈춤 | 검토 `CANCELLED` / `CANCEL` / `USER_CANCEL`, 입력 후보와 `review` metadata; Intervention `CANCELLED` / `null` / `USER_CANCEL`, design null |
| 확인(Stage 3 Wave 4) | `should_stop`: 호출 전·ack 후·생성 시도 사이 | 그 지점에서 중단(생성 0회 또는 1회) | 세 API 모두 `CANCELLED` / `null` / `STOPPED`, design null |

"확인(Stage 3 Wave 4)" 행의 값은 `status` / `hri_result` / `error.code` 순서이며, 현행 코드가 caller에게 돌려주는 값을 그대로 기록한 것입니다(정책 변경 없음, fake voice·LLM으로 확인: `tests/integration/test_c_stage3_failures.py`, `tests/unit/c_design/test_stage3_contract.py`).

| `error.code` | 의미 | 함수 |
|---|---|---|
| `UNSUPPORTED_OBJECT` | 목표 문장에서 지원 사물을 찾지 못함 | create_initial_design |
| `INVALID_INPUT` | `text` 타입 오류, `design` / `current` / `differences` 형식·범위·§9.1 입력 검사 위반 | 둘 다 |
| `DESIGN_GENERATION_FAILED` | 재생성 한도 안에 유효 Design 없음. `details`에 마지막 탈락 사유 | 둘 다 |
| `STOPPED` | D/HMI STOP·닫힌 요청 | 둘 다 |
| `USER_CANCEL` | 사용자의 명시적 취소 발화 | run_intervention |
| `VOICE_IO_FAILED` | 녹음 장치 또는 STT provider 실패(위 재시도 정책 후). message는 실패 종류만 담음(`voice I/O failed: <kind>`) | 둘 다 |
| `LLM_CALL_FAILED` | LLM provider 실패. 일시적 실패(network / timeout / 429 / 5xx)는 최대 3회(1·2·4초) API 재시도 후, auth·키 없음·비정상 응답은 즉시. 재시도 사이 `should_stop` 확인 | 둘 다 |

- 음성 실패 판정은 장치·provider 실패에만 쓰며 사용자 무응답과 무관합니다(사용자 무응답에는 시간 한도 없음).
- 공용 문서에 오류 코드 이름이 없어(06 §9 "구현에서 정함") C가 정의합니다. `INVALID_INPUT`은 참고 인터페이스 정책의 기존 이름입니다.
- 00 E04 "자동 재시도 없이 보류"는 Robot 전달 복구 범위이며 C의 LLM·음성 재시도와 무관합니다.

## 11. 연결 담당 확인 항목

| 항목 | C 제안 | 확인 |
|---|---|---|
| 정상·실패·취소 결과 envelope 예시(`STOPPED` / `USER_CANCEL` / `DESIGN_GENERATION_FAILED`) | §6, §10 | D (수현) |
| `should_stop` 콜백으로 STOP·닫힌 요청 연결 | §4 | D (수현) |
| `on_question` 콜백으로 HMI 화면 표시 | §4.2 | D (수현) |
| Difference `{expected, actual}` 블록 쌍 | §5.2 | D (수현) |
| support "아래 블록 개수와 무관하게 겹침 합계 2 stud 이상, 중복 합산 없음"(Case A~D)을 A Plan 검증과 같은 기준으로 사용 — 2026-10-06 A 동의·D 회신으로 통일 | §9.1 | A (세은) |
| A가 Step 목표를 블록 여섯 값으로 참조 | §7 | A (세은) |
| 최대 층수 5(2026-10-06 팀장 결정): C validator·문서는 적용 완료. 공유 계약(06·00), A planner(`MAX_LAYER` 4), D contracts(layer 1..4), D HMI schema는 아직 4층 — 팀 반영 필요 | §2, §9.1 | A (세은), D (수현), 공유 문서 Owner |

## 12. 이 계약에서 정하지 않는 것

- 질문 템플릿 세부, LLM 프롬프트, 실제 STT·TTS·LLM 연결: WAVE 4~5.
- Job·request_id·최신성 envelope: D가 통합에서 연결(06 §4).
- 임의의 새 위치로 옮기기를 제안하는 escalation: 새 HRI 결과와 D Workflow 변경이 필요하므로 넣지 않습니다(§8.11은 채택 Design 위치로 되돌리기만 제안).
- C 내부 블록 ID: 이번 정렬에서는 두지 않습니다(§8.4).
