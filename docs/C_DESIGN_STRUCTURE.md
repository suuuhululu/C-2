# C Design 구조

## 현재 코드와 최종 목표 (2026-10-07)

main `95259bd`에는 app/c_design의 main/dialogue/designer/validator/llm/voice 함수 코드가 있습니다. 아래 skeleton·미구현 표기는 **초기 구조 설계 당시 상태**입니다. 이후 결과는 [C 진행 기록](C_DESIGN_PROGRESS.md)과 [통합 기록](D_C_FUNCTION_INTEGRATION.md)을 확인합니다.

[최종 MVP](10_FINAL_MVP.md)의 커스텀 의자 대화·명시적 확정은 기존 모듈 책임에 맞춰 이행하되 새 상태·API·파일 이동을 이 문서에서 강제하지 않습니다. C의 Design 생성과 경로 생성·Backend 실행 허가를 분리합니다. 첨부 역할 재배정과 웹/HMI 분담은 미확정입니다.

## 초기 구조 설계 기록

> 2026-10-06 Day4 Contract Sync 반영 완료(commit 3bf0c10): 공통 여섯 필드·Design {design_version, blocks}·KEEP / REVISE / UNCLEAR 적용. 상세는 [C_DESIGN_CONTRACT.md](C_DESIGN_CONTRACT.md).


C 파트(담당: 시율, **Voice Interaction + LLM Design**)의 예정 구조와 파일 책임입니다. 팀장 승인 구조이며 **실제 기능은 아직 구현되지 않았습니다.** 진행 상황은 [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md)를 봅니다.

## 1. C 역할

C = Voice Interaction + LLM Design.

**Voice Interaction**

- 최초 사용자 음성 입력: 녹음, STT, 최초 목표 해석
- 변경 context(Design·Current·Difference) 해석, 어떤 질문을 할지 결정, 질문 문장 생성
- TTS로 질문 재생, 사용자 음성 수집(녹음), STT
- Intent Parsing: 응답을 HRI 결과 KEEP / REVISE / UNCLEAR로 판단, 명시적 취소 신호 인식
- 불명확한 응답 재질문

**LLM Design**

- Initial Design 생성과 Design Validation
- REVISE 시 Revised Design 생성과 Validation
- HRI 결과 / Design 반환

### HRI 결과

| HRI 결과 (코드 식별자) | 의미 |
|---|---|
| KEEP | 최초 v1 복귀가 아니라 **현재 채택된 Design**(예: v3)을 계속 따름. 선택했다고 물리 수정 완료를 뜻하지 않음. 이후 사람 수정 → B 관측 → D Current 갱신 → Expected 확인 |
| REVISE | D가 준 최신 Current의 실제 배치(여섯 값)를 보존하고 나머지를 다시 설계한 Revised Design 생성. 예: Design (5, 5) / Current (5, 6) → Revised Design에 (5, 6) 블록. 보존 대상은 Python이 Current 기준으로 결정하고, LLM이 보존 대상을 바꾸면 validator가 거부 |
| UNCLEAR | 응답을 판단할 수 없음. C가 선택지를 다시 설명해 재질문, 계속 불명확하면 명시 선택 대기 |

순차 조립 전제: A가 다음 블록 결정 → D가 M0609로 1개 전달 → 사람 조립 → B / D 확인. C는 동일 블록 간 Data Association을 하지 않습니다.

## 2. C가 하지 않는 것

| 하지 않는 것 | 담당 |
|---|---|
| 카메라 관측, Vision, Observed 생성, 관측 품질·신뢰도·오류 | B (홍동) |
| 사람 조립 순서, 필요한 블록 종류·색상, NextPart, 남은 작업, Replan | A (세은) |
| Observed 검증·Current 채택, Expected / Current 비교, Difference 판정 | D (수현) |
| M0609 블록 전달 정지·재개, 공급 슬롯, Robot mm 좌표, Board→Robot 변환, TCP / Joint / trajectory, Robot Control | D (수현) |
| Backend Workflow 진행, 전체 HMI 화면 구현 | D (수현) |
| 화면 표시 | HMI(D). **질문 문장·재질문·음성은 C** |

D는 현재 채택 Design / Current / Difference를 C에 전달하고 C 결과를 받아 Workflow를 진행합니다. **D는 질문 문장을 만들지 않고 C에게 읽을 문자열을 주지 않습니다.** 질문 생성부터 음성 대화까지 전부 C 책임입니다.

LLM이 Robot 좌표·joint·TCP·속도·힘·trajectory를 생성하지 않습니다.

## 3. Package tree

```text
app/
└── c_design/
    ├── __init__.py    # 패키지 표시만, 내용 없음
    ├── main.py        # 다른 파트가 호출하는 공개 진입점, Initial Design·Intervention 대화 흐름 연결
    ├── voice.py       # 모든 음성 I/O: 녹음·STT·TTS 재생
    ├── dialogue.py    # 순수 텍스트: 질문·재질문 문장 생성, 응답 의도 해석, 목표 사물 인식
    ├── llm.py         # OpenAI Chat Completions 호출(표준 라이브러리 urllib)과 Design 후보 JSON 파싱 전용
    ├── designer.py    # Initial / Revised Design 생성
    └── validator.py   # Design 규칙 기반 독립 검증
```

production `.py`는 위 6개로 유지합니다. class·state machine·dialogue / conversation manager·service layer·framework를 추가하지 않습니다.

## 4. Test tree

```text
tests/
├── conftest.py                 # 모든 테스트에서 실제 오디오 장치·네트워크 접근 차단 (WAVE 6)
├── unit/
│   └── c_design/
│       ├── fixtures/           # Contract 형식의 정상·invalid·경계 JSON 8개 (WAVE 2)
│       ├── test_dialogue.py    # 질문 문장·응답 해석 규칙·불명확 (WAVE 2)
│       ├── test_validator.py   # 규칙별 정상 / invalid, support Case A~D (WAVE 2)
│       ├── test_fixtures.py    # fixture를 validator·dialogue에 통과 (WAVE 2)
│       ├── test_designer.py    # Mock Initial / Revised, Current 보존, 재생성 루프 (WAVE 3)
│       ├── test_main.py        # 공개 함수·대화 루프(텍스트 모드 = Fake Voice) (WAVE 4)
│       ├── test_llm.py         # 프롬프트·파싱·provider 실패 분류(fake 네트워크) (WAVE 5)
│       ├── test_design_metadata.py # design_metadata·judge 재생성 상한(최대 1회)·의도/judge 실패 경로 (2026-10-07)
│       └── test_voice.py       # 녹음 energy gate·STT·TTS·실패 분류(fake 장치·네트워크) (WAVE 6)
└── integration/
    └── test_c_contract.py      # D → C 입력·C → D envelope·C → A Design 계약 (WAVE 4)
```

```text
scripts/
├── c_e2e_smoke.py              # C 단독 E2E(수동 실행, 실제 마이크·LLM·TTS): initial / revise --scenario color|leg, 결과 envelope만 /tmp에 저장
└── c_voice_smoke.py            # L2 장치 시험(수동 실행): stt / tts "<문장>" / dialogue / echo(speak → listen 1회). 오디오 파일을 저장하지 않음 (WAVE 6)
```

테스트 파일은 기능 구현과 함께 하나씩 추가합니다. 루트 `pyproject.toml`의 pytest 설정으로 저장소 루트에서 `pytest`를 실행합니다. `voice.py`의 녹음 상태 기계·STT·TTS 요청 조립과 실패 분류는 fake 장치·fake 네트워크로 unit test(`test_voice.py`)하고, 실제 마이크·스피커·provider는 L2 장치 시험(`scripts/c_voice_smoke.py`)에서 확인합니다. `tests/conftest.py`가 모든 테스트에서 실제 오디오 장치와 네트워크 접근을 막습니다. 실행할 테스트가 없는 상태를 PASS로 표시하지 않습니다.

## 5. 파일 설명

| 파일 | 한 줄 설명 | 앞으로 들어갈 것 | 넣지 않는 것 |
|---|---|---|---|
| `main.py` | 공개 진입점 | 구현(WAVE 4): Initial Design 흐름, Intervention 대화 루프(KEEP / REVISE / UNCLEAR 재설명 / 명시적 취소 / STOP), REVISE 6회 + escalation + 4회, envelope 변환, 텍스트 모드(Fake Voice). 음성 모드(WAVE 6): speak 재생 종료 후 listen, listen None → VOICE_IO_FAILED(`voice I/O failed: <kind>`), ""(침묵) → 계속 대기 2026-10-07: envelope에 `design_metadata` sibling 키(Design 구조 불변, design이 null이면 null). REVISE(LLM) = 설계 의도(`generate_design_intent`) → 생성(의도 주입) → judge(`judge_revised_design`) → `recognizable_family` false 또는 `silhouette_clarity` ambiguous일 때만 같은 의도 + judge 피드백으로 재생성 최대 1회(`METADATA_REGENERATIONS_MAX`) → 재judge. judge 오류·필드 누락은 재생성 없이 `error`에 기록. Initial(LLM)은 `describe_initial_design`으로 설명. KEEP·실패·취소는 null, Mock은 고정 문자열 | 음성 I/O·질문 문장·응답 규칙·LLM·검증 로직 직접 구현 |
| `voice.py` | 음성 I/O | 구현(WAVE 6): 녹음(record, 적응형 RMS energy gate: 스트림 open 직후 warm-up 0.2초 버림 → 0.5초 noise floor 보정 후 기준 max(600, floor × 3), 시작 대기 8초·끝 무음 1초·최대 10초, pre-roll 0.3초, 최소 발화 0.2초, 앞뒤 무음 0.2초만 남기고 트리밍, 짧거나 약한 입력·침묵이면 b""), STT(transcribe, OpenAI `whisper-1`, key `OPENAI_API_KEY`, 메모리 WAV, 2초 미만 클립은 무음 패딩(앞 0.3초·뒤 나머지)해 2초로 전송, `language=ko` + 도메인 어휘 `prompt`(명사·동사만: 취소·원복·재설계·숫자 제외), `verbose_json` 응답의 no_speech 게이트(segment 없음 또는 모두 no_speech_prob ≥ 0.8 → "" + `stt_no_speech`), 힌트 되풀이 가드: 결과가 힌트 전체이거나 힌트 항목 3개 이상이면 "" + last_error `stt_prompt_echo`, `C_VOICE_DEBUG_DIR` 설정 시에만 입력 WAV·통계 덤프, STT 미호출·거부도 `stt_called`·`reason`으로 기록), listen(on_ready=None: 보정이 끝나 발화 대기에 들어갈 때 1회 호출, 안내 표시용), listen(침묵이면 STT 없이 "", 장치·STT 실패 None), TTS 재생(speak, OpenAI `tts-1`, key `OPENAI_TTS_API_KEY` 전용·대체 없음, 재생 종료 + 0.5초 뒤 반환, 예외 없음), last_error(실패 종류, key 미포함). sounddevice·numpy는 호출 시점 지연 import. 재생 종료 후 녹음 시작으로 echo 방지(F05·F07) | 의미 판단, 질문 문장 생성, 임시 파일·오디오 파일 저장 |
| `dialogue.py` | 대화 텍스트 처리 | 질문·재질문 문장, 선택지 상수(1번 KEEP / 2번 REVISE), 응답 해석(Rule → LLM fallback → UNCLEAR), 명시적 취소 신호(CANCEL), 목표 사물 인식 | 음성 I/O, 대화 루프 |
| `llm.py` | LLM 호출 전용 | 구현(WAVE 5): Design 후보 생성 함수 2개(Initial / Revised), 프롬프트 상수(validator 상수로 규칙 표기), JSON 파싱, provider 실패 분류(`llm_error`), 일시적 실패만 최대 3회 API 재시도. 모델 `DEFAULT_MODEL` / 환경 변수 `OPENAI_MODEL`, key는 LLM 전용 `OPENAI_LLM_API_KEY`(STT·TTS key로 대체 없음). 모델별 payload(`_payload`: reasoning 모델은 `max_completion_tokens`·`reasoning_effort`, 그 밖은 `temperature`·`max_tokens`). system prompt 분리: `SYSTEM_PROMPT_INITIAL`(넓은 의미의 앉는 가구, 예시 JSON 없음) / `SYSTEM_PROMPT_REVISED`(의자 형태 목표 + 예시, `SYSTEM_PROMPT`는 이 이름의 하위 호환 alias). main이 호출 시점 `C_DESIGN_USE_LLM=1`일 때만 사용. smoke test로 확인된 모델: gpt-4o(환경변수 지정). Revised는 일부 사례(다리 이동으로 생긴 빈 줄)에서 유효 후보를 만들지 못하며, 이때 Day4는 escalation → 원복 → KEEP 경로를 사용 2026-10-07 EXPRESSIVE v4: `SYSTEM_PROMPT_REVISED` = Initial과 같은 Rules·concept·build hints + `_EXPRESSIVE_HINTS`(굵은 family 구성법) + 설계 원칙 + 조립 순서 규칙 + procedure + self-check, 고정 예시 의자·`_CHAIR_SHAPE` 삭제. `_REVISED_GUIDANCE`(Current만 고정, 이전 Design은 맥락, family 변경 허용, First~Sixth). `_revised_user_message(…, intent=None, feedback=None)`. 새 함수 `generate_design_intent`(`SYSTEM_PROMPT_INTENT`, `FURNITURE_FAMILIES`, `INTENT_KEYS`), `judge_revised_design`(`SYSTEM_PROMPT_JUDGE`), `describe_initial_design`(`SYSTEM_PROMPT_DESCRIBE`), `judge_feedback_text`, `generate_revised_design(…, intent=None, feedback=None)` Stage 2 Wave 1: `_RULE_LINES`의 orientation 문장에 1x2x1(0 = X1·Y2, 90 = X2·Y1)을 넣고 어휘 안내 한 줄(red accent, 1x2x1 용도와 2 stud 지지) 추가. brick·색·블록 수는 validator 상수에서 자동 반영. 프롬프트 철학·구조는 그대로 | 설계 검증·금지 키 검사, 설계 재생성 정책·버전, 응답 보정, import 시 secret loading |
| `designer.py` | Design 생성 | Mock Initial / Revised 구현(WAVE 3), LLM 생성기 주입 자리(`generate`). Initial / Revised 생성, 보존 대상 Python 결정, 탈락 사유로 재생성(최대 10회), 배치가 바뀐 경우에만 검증 통과 후 버전 +1 | 조립 순서, NextPart, Robot 좌표 |
| `validator.py` | Design 검증 | brick_type(1x2x1·2x2x1·2x3x1, Stage 2에 1x2x1 추가), color(yellow·blue·red, Stage 2에 red 추가), x / y, orientation_deg(`ORIENTATIONS`: 1x2x1·2x3x1은 0/90, 2x2x1은 0), footprint(`BRICK_SIZES` 표, 90도면 X·Y 교환), layer 1~5, 블록 수 1~40(`MAX_BLOCKS`, Stage 2 30 → 40), Board 범위, overlap, support(C 후보 기준: 아래 블록 개수와 무관하게 겹침 합계 2 stud 이상, A 확인 대기), connectivity, Current 보존(여섯 값), malformed, Robot field 유입 거부 | LLM 호출, Plan 검증 |

### 공통 LEGO / Board 규약 (Day 4 MVP)

| 항목 | 값 |
|---|---|
| brick_type | 2x2x1, 2x3x1 |
| color | yellow, blue |
| Board | 24 × 24 stud |
| x, y | 0~23, Board의 stud 위치, footprint 최소 모서리 (Robot mm 좌표 아님) |
| layer | 1~5, **1-based** (layer 1 = Board 위 첫 LEGO 층, 최대 5층: 2026-10-06 팀장 결정) |
| orientation_deg | 2x3x1: 0 = X 2 / Y 3 stud, 90 = X 3 / Y 2 stud. 2x2x1: 0 |
| support | 바로 아래 layer와 겹치는 stud 합계 2 이상(아래 블록 개수 무관). 세은(A)과 확인할 C 후보 기준이며 팀 공용 확정값 아님 |

`docs/reference/` GT 원본의 0-based layer 표기는 원자료 규약이며 C 구현에는 적용하지 않습니다.

## 6. 모듈 간 예상 호출 관계

```text
외부 / D (Intervention: 실제 차이 발생 시 호출)
   │  공개 함수만 호출
   ▼
main.py
   ├─▶ dialogue.py  질문 문장 생성
   ├─▶ voice.py     TTS 재생
   ├─▶ voice.py     녹음 + STT
   ├─▶ dialogue.py  응답 해석 (llm_fallback 인자 자리, 미연결)
   │
   ├─ UNCLEAR       → dialogue 재질문 문장 → voice 재생·녹음·STT → 다시 해석
   ├─ KEEP          → 현재 채택된 Design 그대로 반환 (LLM 호출 없음)
   └─ REVISE        → designer.py ──▶ llm.py
                         └──▶ validator.py
   ▼
HRI 결과 / Design 반환
```

- 최초 목표: main → (voice 녹음 + STT) → dialogue 목표 사물 인식 → designer Initial → validator → 반환
- 텍스트 입력 모드에서는 voice를 호출하지 않습니다.

## 7. 외부 호출 원칙

외부 모듈은 `app.c_design.main`의 공개 함수만 호출합니다. `voice`, `dialogue`, `llm`, `designer`, `validator`를 직접 import하지 않습니다. 내부 구조가 바뀌어도 공개 함수의 계약만 유지하면 연결 담당 코드가 바뀌지 않게 하기 위함입니다.

## 8. import side effect 금지

패키지나 모듈을 import하는 것만으로 다음이 일어나면 안 됩니다.

- 녹음 시작, 마이크 접근, 음성 재생
- STT·TTS·LLM 모델 로딩
- API 호출, 네트워크 요청, API key 등 secret loading
- 파일 쓰기, 로그 폴더 생성

무거운 작업은 공개 함수가 호출될 때만 실행합니다. 테스트와 다른 담당의 import가 장치나 네트워크 없이 성공해야 합니다.

## 9. Contract

`main.py` 공개 함수 이름·Input / Output, D → C 입력, C → D 결과, C → A 전달, Design 형식, Revised Design 규칙, 검증 책임, 실패 반환은 [C_DESIGN_CONTRACT.md](C_DESIGN_CONTRACT.md)에서 정의합니다. 공통 계약 초안은 [06_CONTRACT_DRAFT.md](06_CONTRACT_DRAFT.md)를 따릅니다.

## 10. 개발 순서

1. Contract
2. Fixture
3. Text Dialogue
4. Validator
5. Mock Initial Design
6. Mock Revised Design
7. A/D Contract Test + Fake Voice Dialogue
8. 실제 LLM
9. 실제 STT + 녹음
10. 실제 TTS + Voice Dialogue 완성

실제 LLM·STT·TTS는 Mock 경로와 계약 테스트가 끝난 뒤 연결합니다.
