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
| UNCLEAR | 06 §5 | `UNCLEAR` | 판단 불가. 선택지를 다시 설명해 재질문, 계속 불명확하면 명시 선택 대기 |
| 명시적 취소 | 09 취소 | `CANCEL` | 사용자의 취소 발화. HRI 결과가 아닌 C 내부 신호 |
| HRI 결과 | 06 §5 | `hri_result` | KEEP / REVISE / UNCLEAR 중 하나 |
| 질문 / 재질문 | 06 §5 | `questions` | C가 만든 질문 문장. 같은 문장을 화면·음성으로 제공 |

사용하지 않는 용어: Target Design, Modified Design, KEEP_TARGET, KEEP_CURRENT, KEEP_ORIGINAL, CREATE_REVISED, deviation, Decision, Brick(필드 묶음 이름), geometry, grid_x, grid_y, YELLOW, BLUE, block_id, parent_version, last_block_number, local_x, local_y, long_axis, design_local_stud.

## 2. 블록 필드 (06 §1)

| 필드 | 허용 값 | 정의 |
|---|---|---|
| `brick_type` | `1x2x1`, `2x2x1`, `2x3x1` | ASCII 소문자 `x`. `1x2x1`은 Stage 2 추가(가는 블록: rail·trim·wing·slat·좁은 지지용) |
| `color` | `yellow`, `blue`, `red` | 소문자. `red`는 Stage 2 추가 |
| `x` | 정수 0~23 | 24×24 Board stud 좌표, footprint의 최소 x 모서리. Robot mm·TCP 좌표 아님 |
| `y` | 정수 0~23 | footprint의 최소 y 모서리 |
| `layer` | 정수 1~5 | 1층이 판 위 첫 층(최대 5층: 2026-10-06 팀장 결정) |
| `orientation_deg` | `1x2x1`: 0 또는 90 / `2x3x1`: 0 또는 90 / `2x2x1`: 0 | `1x2x1`: 0 = X 1 stud · Y 2 stud, 90 = X 2 stud · Y 1 stud. `2x3x1`: 0 = X 2 stud · Y 3 stud, 90 = X 3 stud · Y 2 stud. `2x2x1`: X 2 · Y 2 |

- footprint 전체가 0~23 안에 있어야 합니다(예: `2x3x1` 0도 `x = 23`, `1x2x1` 90도 `x = 23`은 범위 초과).
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

생성 경로(MOCK / LLM) 같은 진단 정보와 설계 이름·설명은 Design 밖, envelope의 `design_metadata`에 둡니다(§6.1). layer 1~5·블록 수 1~40·brick_type·color는 validator 상수(`MAX_LAYER`, `MAX_BLOCKS`, `BRICK_TYPES`, `COLORS`)이며 LLM 프롬프트의 Rules 줄도 이 상수를 그대로 씁니다("blocks: 1..40", "brick_type: 1x2x1, 2x2x1, 2x3x1"). Rules 줄의 orientation 문장과 어휘 안내("red is available for accents; 1x2x1 is a thin brick … still needs 2 studs of support below")는 고정 문장입니다.

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

외부 모듈은 이 두 함수만 호출합니다. 두 함수 모두 예외를 밖으로 던지지 않고 §6의 결과 dict를 반환합니다. 후보 하나의 검증 탈락은 곧바로 Job 실패가 아니며 C 내부에서 **유한하게** 재생성합니다(§8.10). 실제 `main` 구현은 WAVE 4입니다.

실제 LLM 사용 여부는 호출 환경의 `C_DESIGN_USE_LLM=1`로 정하며 기본은 Mock입니다.

외부 provider key는 용도별 환경 변수 3개로 나누며 서로 대체하지 않습니다. 값은 호출 시점에만 읽고 출력·기록하지 않습니다.

| 환경 변수 | 용도 | 읽는 곳 |
|---|---|---|
| `OPENAI_LLM_API_KEY` | LLM Design 생성(Chat Completions) | `llm.py` (`LLM_KEY_ENV`) |
| `OPENAI_API_KEY` | STT (`whisper-1`) | `voice.py` (`STT_KEY_ENV`) |
| `OPENAI_TTS_API_KEY` | TTS (`tts-1`) | `voice.py` (`TTS_KEY_ENV`) |

LLM 모델은 `OPENAI_MODEL`(기본 `DEFAULT_MODEL`)입니다. 모델명이 reasoning 계열(`gpt-6`, `gpt-5`, `o1`, `o3`, `o4`로 시작)이면 요청에 `max_completion_tokens`(8000)와 `reasoning_effort`(medium)를 쓰고 `temperature`·`max_tokens`를 보내지 않습니다. 그 밖의 모델(gpt-4o 등)은 `temperature`·`max_tokens`를 씁니다. 따라서 Revised 재생성 temperature(0.3)는 reasoning 모델에서는 적용되지 않습니다. system prompt는 Initial(예시 설계 없이 넓은 의미의 앉는 가구)과 Revised(의자 형태 목표 + 검증 통과 예시)를 따로 씁니다.

### 4.1 `create_initial_design(text=None, should_stop=None)`

| 입력 | 타입 | 의미 |
|---|---|---|
| `text` | str 또는 `None` | 텍스트 입력 모드면 목표 문장(예: "오늘은 의자를 만들 거야"). `None`이면 음성 모드: C가 녹음·STT로 목표를 받음. str도 `None`도 아니면 `INVALID_INPUT`, 공백뿐인 문자열은 `UNSUPPORTED_OBJECT` |
| `should_stop` | `callable() -> bool` 또는 `None` | D의 STOP·닫힌 요청 연결. 재생성 시도 사이에 확인하고 True면 `CANCELLED` / `STOPPED` |

출력: §6 결과. 성공 시 `design`은 Initial Design, `hri_result`는 `null`.

### 4.2 `run_intervention(design, current, differences, text_answers=None, on_question=None, should_stop=None)`

| 입력 | 타입 | 의미 |
|---|---|---|
| `design` | Design (§3) | 현재 채택된 Design |
| `current` | 블록 배열 | Backend 채택 Current (§5.1) |
| `differences` | Difference 배열, 1개 이상 | 이번 Intervention의 원인 차이 (§5.2). 빈 배열이면 `INVALID_INPUT` |
| `text_answers` | str 배열 또는 `None` | 텍스트 입력 모드: 질문마다 순서대로 쓰일 응답. `None`이면 음성 모드 |
| `on_question` | `callable(str)` 또는 `None` | C가 질문·재질문을 낼 때마다 그 문장으로 호출. D가 HMI 화면에 표시. 콜백이 던진 예외는 C가 잡지 않으며 호출자 책임(§4의 "예외 없음" 약속의 유일한 예외) |
| `should_stop` | `callable() -> bool` 또는 `None` | 질문-응답 턴 사이와 재생성 시도 사이에 확인. True면 `CANCELLED` / `STOPPED` |

흐름: C가 질문 문장 생성 → `on_question` 통지 → (음성 모드) TTS 재생 → 재생 종료 후 듣기·STT → 응답 해석.

- UNCLEAR → 선택지를 다시 설명해 재질문. 계속 불명확하면 사용자의 명시적 선택을 기다립니다.
- 텍스트 모드에서 `text_answers`가 소진될 때까지 불명확이면 `hri_result = "UNCLEAR"`로 반환합니다.
- KEEP → 입력 `design`을 **변경 없이** 그대로 반환. LLM 호출 없음, `design_version` 동일.
- REVISE → Revised Design을 생성·검증해 반환(§8).
- 명시적 취소 발화(`CANCEL`, 예: "취소할게") → `status: CANCELLED`, `error.code: USER_CANCEL`.

질문 문장·재질문 문장·선택지 표현은 C가 만듭니다. D는 질문 문자열을 C에 주지 않습니다. 질문은 블록 ID 대신 위치로 블록을 가리킵니다(예: "(x=3, y=5) 2층 블록").

### 4.3 무응답 (Day4)

Day4에는 시간 기준 자동 취소·자동 KEEP·임의 종료가 없습니다(06 §5, 09 무응답). 사용자 입력을 기다리며, 종료는 D/HMI STOP(`should_stop`) 또는 사용자의 명시적 취소뿐입니다.

| 상황 | C 동작 |
|---|---|
| 침묵·잡음(STT 결과 빈 문자열) | 계속 기다림. 시간 기준 확인 질문·최종 안내 없음 |
| 의미 있는 발화(정규화 후 비어 있지 않은 STT 텍스트)인데 불명확 | 선택지를 다시 설명해 재질문 |
| STOP | `CANCELLED` / `STOPPED` |
| 명시적 취소 발화 | `CANCELLED` / `USER_CANCEL` |
| 장치·엔진 실패 | 무응답이 아님. 녹음 장치·STT 실패는 §10에 따라 `VOICE_IO_FAILED` |

음성 I/O(`voice`, WAVE 6)는 순차로 동작합니다. `speak`는 TTS 재생이 끝나고 짧은 지연(기본 0.5초)을 기다린 뒤 돌아오며, 그 뒤에야 `listen`이 마이크 입력을 엽니다(질문 음성을 답으로 다시 인식하지 않음). `listen` 1회는 소리 크기(RMS) 기준으로 발화를 판정합니다. 스트림을 연 직후 0.2초는 버리고(warm-up: open 직후 레벨 변화·직전 재생 잔향 제외) 그다음 0.5초 동안 방 소음(noise floor, 블록 RMS 중앙값)을 재고, 판정 기준을 max(600, noise floor × 3)으로 정합니다(적응형 임계값: 방 소음이 커도 소음을 발화로 오인하지 않음). 그다음 발화 시작을 기다리고(기본 최대 8초), 발화 직전 0.3초를 앞에 붙여(첫 음절 보존) 발화 끝 무음(기본 1초) 또는 발화 시작부터 최대 길이(기본 10초)에서 녹음을 끝냅니다. 앞뒤 무음은 0.2초만 남기고 잘라 냅니다. 발화가 없거나, 발화로 판정된 길이가 0.2초 미만이거나, 잘라 낸 녹음 전체가 기준의 절반보다 약하면 STT를 호출하지 않고 빈 문자열을 돌려줍니다(무음·소음에서 STT가 자막형 문장을 지어내는 것을 막음). 2초보다 짧은 녹음은 앞 0.3초·뒤 나머지를 무음으로 채워 2초로 보냅니다(1초 미만 클립은 whisper 환각이 잦음). STT 요청에는 `language=ko`와 도메인 어휘 힌트(`prompt`: 의자·벤치·소파·스툴·만들어줘·만들고 싶어)를 함께 보내고 응답은 `verbose_json`으로 받습니다. 힌트에는 취소·원복·재설계 어휘와 숫자("1번"·"2번")를 넣지 않습니다(되풀이돼도 응답 의미가 바뀌지 않게, 숫자 힌트는 짧은 "2번"에 "3번, 4번, …" 나열을 지어내게 함). segment가 없거나 모든 segment의 `no_speech_prob`가 0.8 이상이면 빈 문자열(발화 없음)로 처리하고 `last_error`에 `stt_no_speech`를 남깁니다(짧은 정상 발화도 0.55 안팎이라 보수적으로 둠). STT 결과가 힌트 전체이거나 힌트 항목을 3개 이상 담고 있으면 힌트를 되풀이한 것으로 보고 빈 문자열(발화 없음)로 처리하며 `last_error`에 `stt_prompt_echo`를 남깁니다. 환경 변수 `C_VOICE_DEBUG_DIR`이 있을 때만 STT에 보낸 WAV와 통계(길이·RMS·peak·noise floor·기준·발화 길이·잘라 낸 길이)를 그 폴더에 덮어써 남깁니다(기본 off, key 미기록). 통계에는 STT 전송 여부(`stt_called`)와 빈 문자열로 끝난 이유(`reason`: no_speech_detected / too_short / weak_input / no_speech_prob / prompt_echo)가 들어가며, STT를 부르지 않은 경우에는 통계만 남기고 이전 WAV는 지웁니다. `listen(on_ready=None)`의 선택 콜백은 warm-up·소음 보정이 끝나 발화를 기다리기 시작할 때 1회 호출되며(안내 표시용, 콜백 예외는 그대로 전파), `main`은 쓰지 않습니다(기본 None). 장치·STT 실패는 `None`입니다. 수치는 `voice` 모듈 상수입니다. 별도 thread·watchdog 없이 `main` 대화 루프에서 `should_stop`을 확인합니다. 텍스트 모드에는 대기가 없습니다.

## 5. 입력 형식 (D → C)

C는 아래 필드만 읽고 나머지 키는 무시합니다. D는 자기 객체를 그대로 넘겨도 됩니다. D는 블록 ID를 주지 않으며 C는 같은 값 블록 간 대응(Data Association)을 하지 않습니다.

### 5.1 Current

블록 배열. 각 블록은 §2의 여섯 값이며 실제로 놓인 값입니다. 관측 순번·confidence 등 추가 키는 읽지 않습니다.

### 5.2 Difference

| 필드 | 타입 | 의미 |
|---|---|---|
| `expected` | 블록(§2) 또는 `null` | Expected에 있던 배치. `null`이면 Expected에 없던 블록 |
| `actual` | 블록(§2) 또는 `null` | Current의 실제 배치. `null`이면 누락된 블록 |

C는 두 블록의 값을 비교해 어떤 항목(위치·색·방향·크기·층)이 다른지 질문 문장에 씁니다. 어떤 블록끼리 대응하는지는 D가 준 쌍을 그대로 사용합니다.

## 6. 결과 형식 (C → D)

두 공개 함수는 같은 형식을 반환합니다.

| 필드 | 타입 | 의미 |
|---|---|---|
| `status` | `"OK"`, `"FAILED"`, `"CANCELLED"` | `CANCELLED` = STOP 또는 명시적 취소만. `FAILED` = 입력 오류, 재생성 한도 도달, 지속 장애 |
| `hri_result` | `"KEEP"`, `"REVISE"`, `"UNCLEAR"`, `null` | `create_initial_design`은 항상 `null` |
| `design` | Design 또는 `null` | 성공 시 채택 후보 Design |
| `design_metadata` | object 또는 `null` | `design`의 이름·설명·평가(§6.1). `design`이 `null`이면 항상 `null`. Design 구조(§3)에는 넣지 않음 |
| `questions` | str 배열 | 이번 호출에서 C가 낸 질문·재질문 문장(로그·표시용). Initial은 빈 배열 |
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

표시·로그용 설명입니다. 분기에 쓰지 않으며, metadata를 만들지 못해도 설계 성공을 `FAILED`로 바꾸지 않습니다(`error` 필드에만 기록).

| 경우 | `design_metadata` |
|---|---|
| Initial 성공(LLM) | `{design_name, design_family, design_summary, visible_features, human_interpretation: null, judge: {silhouette_clarity, recognizable_family, completeness_score}, source: "LLM", error}` — 설명 호출(`llm.describe_initial_design`) 결과 |
| REVISE 성공(LLM) | 아래 Revised 필드표 |
| Mock(Initial·REVISE) | 고정 문자열: `design_name: "Mock 의자"`, `design_family: "chair"`, `source: "MOCK"`, `judge`·`design_intent`: null, `regenerations`: 0 |
| KEEP, UNCLEAR, FAILED, CANCELLED | `null` |

| Revised 필드 | 내용 |
|---|---|
| `design_name` | judge의 `design_name`, 없으면 intent의 `concept_name` |
| `design_family` | judge의 `design_family`(실제로 보이는 family), 없으면 intent의 `design_family` |
| `design_summary` | judge의 `why_it_is_complete` |
| `visible_features` | judge가 좌표에서 본 기하 특징 문구 목록(이름이 특징을 만들지 않음) |
| `human_interpretation` | `{placed_differently, interpretation, imagined_concept, lego_redesign, why_final_shape}` (judge `human_story`) 또는 null |
| `change_summary` | 이전 Design 대비 재설계 요약 문구 목록 |
| `interpretation_status` | `"clearly visible"` / `"weakly visible"` / `"mismatch"` (계획한 특징이 보이는 정도) |
| `judge` | `{recognizable_family, family_confidence, silhouette_clarity, explanation_required_to_understand, layer5_meaningful, completeness_score, awkward, verdict}` 또는 null(judge 응답을 쓸 수 없을 때). `verdict` = `"SHOWCASE"`(reads_as_seating·recognizable_family가 true, silhouette_clarity가 clear, explanation_required_to_understand가 false) 그 밖은 `"NOT_YET"`. feature_check 전부 visible은 조건이 아님 |
| `design_intent` | 생성 전에 정한 설계 의도 전체 또는 null(실패) |
| `regenerations` | judge 결과로 다시 만든 횟수(0 또는 1, §8.12) |
| `source` | `"LLM"` / `"MOCK"` |
| `error` | null 또는 `{kind, message}`: `intent_error`(의도 실패, 의도 없이 생성), `judge_error`(judge 응답 오류·필수 필드 누락·예상 밖 값, 재생성 없음), `regeneration_failed`(재생성이 유효 후보를 못 냄, 첫 설계 유지), `describe_error`(Initial 설명 실패). 여러 개면 마지막 오류 |

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
| 설계 의도(DESIGN INTENT: family·보일 특징·layer 5 특징·기하 계획, 실패하면 생략) | `llm.generate_design_intent` (§8.12) |
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
| 질문 형태 | C(dialogue)가 만든 문장. 블록은 위치로 표현. "1번 원래 위치로 옮기기, 2번 계속 새 설계 찾기" |
| 동의 | 사용자의 명시적 동의이므로 `hri_result: KEEP`, 입력 Design 그대로 반환 |
| 거절 | 남은 한도 안에서 재설계를 계속. `current`가 support를 위반한 경우에는 재설계할 수 없으므로 명시적 선택·취소·STOP을 기다림 |

Initial Design에는 고정 블록이 없으므로 escalation이 없습니다.

### 8.12 Revised 정책 EXPRESSIVE v4 (2026-10-07 사용자 승인)

- **Current만 고정**: "Preserve the Current exactly. Treat the previous Design as context, not as geometry to preserve. All non-Current blocks are future targets and may be freely moved, removed, replaced, or added. Redesign the remaining structure from scratch if that produces a more coherent, realistic, expressive seating-furniture design; the seat position, support layout, backrest, footprint and even the furniture family may change." 이전 Design은 사용자가 만들던 것(앉는 가구, 대략의 크기·색)을 알려 주는 맥락이며 지킬 기하가 아닙니다. family 변경도 허용합니다. 보수적인 낮은 1인 의자로 되돌리는 지시는 넣지 않습니다.
- **흐름(LLM 모드)**: ① 설계 의도 결정(`llm.generate_design_intent`: 후보 family 중 하나·보일 특징·layer 5 특징·기하 계획, 좌표 없음. 실패하면 의도 없이 진행, STOP이면 `CANCELLED`) → ② 생성(§8.10 재생성 포함, 의도를 메시지에 넣음) → ③ 완성 설계 judge(`llm.judge_revised_design`, 좌표만으로 평가) → ④ judge가 family를 알아볼 수 없다(`recognizable_family: false`)거나 실루엣이 모호(`silhouette_clarity: "ambiguous"`)할 때만 같은 의도 + judge 피드백 문단으로 **재생성 최대 1회**(`main.METADATA_REGENERATIONS_MAX = 1`, 명시적 카운터) → 재judge → 최종.
- **재생성하지 않는 경우**: judge 응답이 provider 오류이거나 필수 필드(`recognizable_family`, `silhouette_clarity`, `reads_as_seating`, `explanation_required_to_understand`)가 없거나 예상 밖 값이면 그대로 끝내고 `design_metadata.error`에 `judge_error`를 남깁니다. awkward·weakly visible·feature mismatch만으로는 재생성하지 않습니다.
- **재생성 실패**: 재생성이 유효 후보를 못 내면 첫 설계와 그 judge를 그대로 반환합니다(`regeneration_failed`). 재생성 중 STOP이면 `CANCELLED` / `STOPPED`.
- 세 가지 반복은 서로 독립입니다: LLM provider API 재시도(§10, `llm.RETRY_BACKOFF`), 후보 탈락 재생성(§8.10, designer 시도 수), judge 재생성(최대 1회).
- escalation 뒤 "계속 찾기"로 다시 생성할 때도 같은 의도를 쓰고 ③·④를 똑같이 적용합니다. Mock 모드에는 의도·judge가 없습니다.
- layer 5 사용·큰 특징·블록 수는 프롬프트의 soft goal이며 validator 규칙이 아닙니다. validator는 §9.1 그대로입니다(블록 수 상한만 40, Stage 2).

## 9. 검증 책임

### 9.1 C (validator, LLM 없이 A / D / HMI 없이 단독 통과)

| 규칙 | rule |
|---|---|
| JSON 파싱 불가·객체 아님 | `malformed_output` |
| 필수 필드 누락 | `missing_field` |
| 정수 필드가 정수 아님(bool·1.0 포함) | `invalid_type` |
| 허용되지 않은 키(Design 두 키 외, 블록 여섯 키 외 — Robot·mm·TCP·joint field 유입 포함) | `unknown_key` |
| brick_type·color·orientation_deg(brick_type별)·layer 1~5 허용 값 | `invalid_value` |
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
- `current`·`differences`의 블록 값이 §2 범위·footprint 범위를 벗어남
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
| 복구 | 설계 의도·judge·Initial 설명 호출 실패, judge 필수 필드 누락·예상 밖 값, judge 재생성 실패 | 설계는 그대로 반환, `design_metadata.error`에 `intent_error` / `judge_error` / `describe_error` / `regeneration_failed` 기록(§6.1, §8.12) | `OK` (metadata error만) |
| 취소 | D/HMI STOP (`should_stop`) | 턴·시도 사이에서 중단 | `CANCELLED` / `STOPPED` |
| 취소 | 사용자 명시적 취소 발화 | 중단 | `CANCELLED` / `USER_CANCEL` |
| 실패 | 호출자 입력 오류 | 즉시 반환 | `FAILED` / `INVALID_INPUT`, `UNSUPPORTED_OBJECT` |
| 실패 | 재생성 10회 한도 도달 | 반환 | `FAILED` / `DESIGN_GENERATION_FAILED` |
| 실패 | LLM provider 실패: 일시적 실패(network / timeout / 429 / 5xx)만 최대 3회(1·2·4초 backoff) API 재시도 후에도 실패. auth·키 없음(`OPENAI_LLM_API_KEY` 미설정, 다른 key로 대체하지 않음)·비정상 응답(reasoning 모델에 지원하지 않는 파라미터를 보내 생기는 400 포함)은 재시도 없이 즉시. 재시도 사이 `should_stop` 확인 | 반환 | `FAILED` / `LLM_CALL_FAILED` |
| 실패 | 음성 입력 실패: 녹음 장치를 열거나 읽지 못함, 또는 STT provider 실패(key: `OPENAI_API_KEY`. 일시적 network / timeout / 429 / 5xx는 최대 3회 API 재시도 후, auth·키 없음·비정상 응답은 즉시) | 반환 | `FAILED` / `VOICE_IO_FAILED` |
| 복구 | TTS 재생 실패(key: `OPENAI_TTS_API_KEY` 전용, 없으면 `OPENAI_API_KEY`로 대체하지 않고 `missing_key`. 모델은 `OPENAI_TTS_MODEL`, 기본 `gpt-4o-mini-tts`이며 `tts-1`·`tts-1-hd`에는 `instructions`를 보내지 않음. HTTP 실패 종류는 `auth`·`model_access`·`bad_param`·`billing`·`rate_limit`·`server`·`bad_response`) | 질문은 `on_question`으로 화면에 표시된 채 응답 대기를 계속하고 실패 사유는 `voice.last_error()`에 기록 | 반환하지 않고 계속 |

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
