# C Design 진행 현황

> 2026-10-06 Day4 Contract Sync 반영 완료(commit 3bf0c10): 공통 여섯 필드·Design {design_version, blocks}·KEEP / REVISE / UNCLEAR 적용. 상세는 [C_DESIGN_CONTRACT.md](C_DESIGN_CONTRACT.md).


C 파트(시율: **Voice Interaction + LLM Design** — 질문 결정·생성, TTS, 녹음, STT, 응답 해석, 재질문, Initial / Revised Design 생성·검증)의 진행률·현재 단계·Blocker를 기록합니다. PR마다 이 파일을 갱신합니다. 구조와 파일 책임은 [C_DESIGN_STRUCTURE.md](C_DESIGN_STRUCTURE.md)를 봅니다.

## 요약

| 항목 | 값 |
|---|---|
| 전체 진행률 | **100%** (기능 단계 10개 중 완료 10개: Contract, Fixture, Text Dialogue, Validator, Mock Initial, Mock Revised, A/D Contract Test + Fake Voice Dialogue, 실제 LLM, 실제 STT + 녹음, 실제 TTS + Voice Dialogue) |
| 현재 작업 단계 | 개발 완료 — A/B/C/D 실제 통합 단계 |
| 다음 단계 | D Difference adapter·D 실제 C 호출 배선·전체 통합 시험(C 기능 개발 아님) |
| 현재 상태 | WAVE 5 완료(사용자 결정 2026-10-06), WAVE 6 완료(사용자 승인 2026-10-06). live 검증 완료: 실제 마이크 입력, `whisper-1` STT, `tts-1` TTS(`OPENAI_TTS_API_KEY` 전용), 실제 스피커 재생, TTS 종료 후 listen, 음성 Initial(v1), 음성 Revised(v2·Current 보존), 강제 Reject → escalation → KEEP(기존 Design 유지). 남은 제약은 아래 Known limitation |
| Blocker | 지지 2 stud 기준 A(세은) 확인 대기, 실패·취소 결과 envelope D(수현) 예시 확인 대기 |
| 마지막 업데이트 | 2026-10-06 · branch `work/siyul-design-hri` |

진행률은 완료 기준을 충족한 단계만 셉니다. 단계 하나 = 10%. 진행 중인 단계는 표의 진행률 칸에만 표시하고 전체 진행률에는 더하지 않습니다. **Skeleton·문서 변경은 개발 단계 완료로 계산하지 않습니다.**

## 상태 값

| 값 | 의미 |
|---|---|
| 대기 | 앞 단계 미완료로 시작 전 |
| READY | 시작 가능, 아직 착수 전 |
| 진행 중 | 작업 중, 완료 기준 미충족 |
| REVIEW READY | 산출물 작성 완료, Team Lead·사용자 리뷰 대기 (완료 아님) |
| 리뷰 | PR 리뷰 중 |
| 완료 (DONE) | 완료 기준 충족·사용자 승인. 이 상태만 전체 진행률에 반영. Merge 전이면 PR을 함께 기록 |
| BLOCKED | 외부 확인 대기로 진행 불가 (Blocker 칸에 사유 기록) |

## 개발 단계

| 순서 | 작업 단계 | 상태 | 진행률 | 작업 설명 | 관련 모듈 | 알아야 할 핵심 | 완료 기준 |
|---|---|---|---|---|---|---|---|
| 1 | Contract | 완료 (DONE) | 100% | main 공개 함수 Input/Output, Design / Current / Difference 형식, HRI 결과, 실패 반환, Validation 책임 정의 | main, dialogue, designer, validator | 06 §1 여섯 값(brick_type, color 소문자, x, y, layer 1~4, orientation_deg), Design = design_version + blocks, HRI 결과 KEEP / REVISE / UNCLEAR | 계약 문서 작성·사용자 승인(2026-10-05). A·D 확인 항목(§11)은 PR 리뷰에서 |
| 2 | Fixture | 완료 (DONE) | 100% | 정상·invalid·경계 Design / Current / Difference / 응답 텍스트 예시 | tests | Contract 형식을 그대로 따르고, 다른 담당이 같은 Fixture를 재사용 | Fixture가 Contract와 일치, 연결 담당 확인 |
| 3 | Text Dialogue | 완료 (DONE) | 100% | 질문·재질문 문장 생성, 텍스트 응답 → KEEP / REVISE / UNCLEAR, 명시적 취소 신호, 목표 사물 인식 | dialogue | 선택지 상수 1번 KEEP / 2번 REVISE를 질문과 해석이 공유, Python Rule 우선, LLM fallback은 8단계 이후 | `test_dialogue.py` PASS (정상·오매칭·부정·UNCLEAR) |
| 4 | Validator | 완료 (DONE) | 100% | brick_type·color·x·y·layer·orientation·범위·overlap·support(C 후보 2 stud)·connectivity·Current 보존(여섯 값)·malformed·Robot field 검증 | validator | 순수 Python, LLM 판단 금지, 실패 항목·사유 목록 반환 | `test_validator.py` 규칙별 정상 / invalid PASS |
| 5 | Mock Initial Design | 완료 (DONE) | 100% | 목표 사물 → 고정 Initial Design (LLM 없음, Board 중앙 배치) | designer | 출력이 Validator 통과, 식별·버전은 Python이 결정 | `test_designer.py` Initial PASS |
| 6 | Mock Revised Design | 완료 (DONE) | 100% | Design + Current + Revised 생성 → Current 배치 보존 전체 Revised Design | designer, validator | 보존 대상은 Python이 Current 기준 결정, Revised Design까지만(조립 순서·NextPart는 A) | preserved 검증 포함 `test_designer.py` PASS |
| 7 | A/D Contract Test + Fake Voice Dialogue | 완료 (DONE) | 100% | A·D가 C 출력을 소비하는 계약 테스트, main 대화 루프를 fake voice로 검증 | main, tests/integration | 공개 함수만 호출, UNCLEAR 재질문, KEEP은 LLM 0회, STOP·명시적 취소 → CANCELLED | `test_main.py`·`test_c_contract.py` PASS, 연결 담당 확인 |
| 8 | 실제 LLM | 완료 (DONE) | 100% | llm.py 실제 provider 연결, Design 생성과 애매한 응답 fallback | llm, designer, dialogue | API key는 환경 변수, 재시도는 designer, Robot 값 생성 금지 | 실제 호출 결과가 Validator 통과, 실패 경로 확인 |
| 9 | 실제 STT + 녹음 | 완료 (DONE) | 100% | 녹음 → 한국어 텍스트, 목표·응답 공용 | voice (녹음·STT) | 짧은 응답("1번") 오인식 실측, L2 장치 시험 | 실제 마이크·`whisper-1`로 '의자 만들어줘'·'2번'·'1번' 인식(사용자 실행 E2E 2026-10-06) |
| 10 | 실제 TTS + Voice Dialogue 완성 | 완료 (DONE) | 100% | C 담당 TTS 질문 재생과 음성 대화 전체 연결 | voice (TTS), main | 재생 종료 후 녹음 시작으로 질문 음성 재인식 방지(F05·F07), echo 방지 실측 | `tts-1` 실제 재생 → 0.5초 → listen 순서, 색 교체 Revised v2(Current 보존), 강제 Reject 6회 → escalation TTS → '1번' → KEEP(기존 Design 유지) 실제 음성으로 확인 |

## 변경 이력

| 날짜 | 단계 | 변경 | 검증 |
|---|---|---|---|
| 2026-10-05 | 0. 준비 | `app/c_design/` 6개 모듈 docstring skeleton, 진행·구조 문서 추가 | `python3 -c "import app.c_design"` 및 각 모듈 import 성공, side effect 없음 확인 |
| 2026-10-05 | 0. 준비 | `stt.py` → `voice.py`, `intent.py` → `dialogue.py` rename. C 역할을 Voice Interaction + LLM Design으로 docstring·문서 갱신(질문 생성·재질문·TTS는 C) | 7개 모듈 import 성공, import문·실행 코드 없음, production `.py` 6개 확인 |
| 2026-10-05 | 1. Contract | `docs/C_DESIGN_CONTRACT.md` 초안 작성(REVIEW READY). C 문서·docstring 용어를 공용 용어로 통일: Target Design → Design, Modified → Revised, KEEP_TARGET / KEEP_CURRENT → KEEP_ORIGINAL / CREATE_REVISED, deviation → Difference / Intervention | 7개 모듈 import 성공, docstring 외 코드 없음, 옛 용어 grep 확인 |
| 2026-10-05 | 1. Contract | Contract 개정: 조립된 Brick `block_id` 유지·값이 그대로인 미조립 Brick은 ID 유지, 바뀐·새 Brick만 `last_block_number`로 새 ID, Design 버전 Owner = C 확정, support 겹침 합계 2 stud, Revised context·Hard / Soft 분리·단순 이동 금지, Initial 중앙 배치 `24 // 2` anchor 금지, 무응답 5분 종료 `NO_RESPONSE`(제안), Board 물리 방향은 D | 7개 모듈 import 성공, docstring 외 코드 없음, 폐기 문구 grep 확인 |
| 2026-10-05 | 1. Contract | Contract 개정 2(이전 행의 block_id·무응답 규칙 대체): 이전 Design의 Brick은 값이 바뀌어도 같은 `block_id` 유지(LLM이 기존 ID echo, 새 Brick만 null → Python 발급), `last_block_number` 제거, 버전은 검증 통과 후 부여, 후보 거부 ≠ 실패(최대 횟수 없는 재생성·backoff·전략 전환·escalation), Recovery First(`FAILED`는 입력 오류·300초 지속 장애만), 무응답 300초 최종 안내 후 `CANCELLED` / `NO_RESPONSE`, support 정의 Case A~D, Current support 위반은 입력 오류가 아니라 즉시 escalation(overlap 위반만 `INVALID_INPUT`), §8 소절 순서 정리 | 7개 모듈 import 성공, docstring 외 코드 없음, 폐기 문구 grep 확인 |
| 2026-10-05 | 1. Contract | Contract 확정(사용자 승인, WAVE 1). Contract 완료(DONE), 전체 진행률 10%. 공용 문서 정렬은 별도 commit. 2·3·4 진행 시작 | 7개 모듈 import, AST docstring-only, 폐기 문구 grep, 링크 확인 |
| 2026-10-05 | 2·3·4 | WAVE 2: `tests/unit/c_design/fixtures/` 8개, `dialogue.py`(질문·재질문·확인·최종 안내·escalation 문장, 응답·목표 해석), `validator.py`(§9.1 규칙, Revised 보존, 입력 검사, Current support 판정), unit test 3개 파일, 루트 `pyproject.toml`(pytest 경로 설정) | `pytest` 157 passed, exit 0. import 부작용 없음, class 없음, 외부 dependency 없음 |
| 2026-10-05 | 2·3·4 | WAVE 2 통과(사용자 승인): Fixture·Text Dialogue·Validator 완료(DONE), 전체 진행률 40%. origin/main PR #5의 06_CONTRACT_DRAFT 개정과 C 계약 불일치로 5·6 대기 | `pytest` 157 passed, exit 0. 7개 모듈 import exit 0 |
| 2026-10-05 | 5·6 | WAVE 3 통과(사용자 승인): Mock Initial / Revised 완료(DONE), 전체 진행률 60%. 기준 Chair 15 Brick(다리·좌석·뒤쪽 등받이·좌우 연결 상단, 좌우 대칭, 중앙 (9,9)). Mock Revised는 실제 다리 기준으로 측면별 재설계, 빈 행 위 3칸 connector, 단순 shift 아님. `test_designer.py` 28개 | `pytest` 185 passed, exit 0. 7개 모듈 import exit 0 |
| 2026-10-06 | Day4 Contract Sync | WAVE 1~3 산출물을 Day4 공용 계약(main 06, PR #6 09, Slack 합의)에 정렬: 블록 여섯 값(brick_type, 소문자 color, x, y), Design = `design_version` + `blocks`, 블록 ID·부모 버전·생성 경로를 Design에서 제거, HRI KEEP / REVISE / UNCLEAR, 명시적 취소·STOP → CANCELLED, 시간 기준 무응답 취소 제거, 재생성 최대 10회·`DESIGN_GENERATION_FAILED`, 배치가 같으면 버전 유지, Current 보존은 여섯 값 multiset, support는 A 확인 대기 후보로 표기. 진행률 60% 유지 | `pytest` 197 passed, exit 0(루트 포함), import 7개, class 0, 옛 용어 grep 의도된 항목 외 0건 |
| 2026-10-06 | 7 | WAVE 4: `main.py` 공개 함수 2개(Initial, Intervention: KEEP / REVISE / UNCLEAR 재설명 / 명시적 취소 / STOP, REVISE 6회 + escalation + 4회, envelope), `voice.py` provider 미연결 stub(VOICE_IO_FAILED), designer Mock 1회 제한, 침묵 대기 중에도 STOP 확인, `test_main.py` 26개(텍스트 모드 = Fake Voice), `tests/integration/test_c_contract.py` 11개(D → C, C → D, C → A). 진행률 60% 유지 | unit 223 passed, integration 11 passed, 루트 `pytest` 234 passed, 모두 exit 0. import 7개, class 0 |
| 2026-10-06 | 7 | WAVE 4 통과(사용자 승인): 7단계 완료(DONE), 전체 진행률 70%. 최신 origin/main(66ec4b6) 기준 고정 branch `work/siyul-design-hri`를 만들고 WAVE 2~4·Sync commit 4개를 merge(중복 없음). C 문서의 PR #5 이행 배너를 Sync 완료 안내로 교체 | unit 223 passed, integration 11 passed, 루트 `pytest` 234 passed, 모두 exit 0. import 7개 |
| 2026-10-06 | 8 | WAVE 5: `llm.py`(OpenAI Chat Completions, 표준 라이브러리 urllib, 모델 상수 + `OPENAI_MODEL`, JSON 파싱, provider 실패 `llm_error` 분류, 일시적 실패만 API 재시도 3회), designer(주입 생성기 첫 호출 전 STOP 확인, `llm_error`는 재생성 없이 `llm_call_failed`), main(`C_DESIGN_USE_LLM=1`일 때만 llm, `LLM_CALL_FAILED` 매핑), validator 상수(`MAX_LAYER`, `MAX_BLOCKS`, `MIN_SUPPORT_STUDS`)를 프롬프트와 공유. `test_llm.py` 29개, designer·main 회귀 추가. Contract §10 LLM 재시도 문구를 구현에 맞춤. live smoke test는 API key 미설정으로 미수행 | offline(OPENAI_API_KEY·C_DESIGN_USE_LLM 미설정): unit 270, integration 11, 루트 `pytest` 281 passed, 모두 exit 0. import 7개, class 0, secret grep 0건, key 파일 미추적 |
| 2026-10-06 | 8 | WAVE 5 완료(사용자 결정 (b)): live smoke를 `OPENAI_MODEL=gpt-4o` 환경 변수로 수행(DEFAULT_MODEL `gpt-4o-mini` 유지, 이 key의 프로젝트는 `gpt-4o-mini` 미허용: HTTP 403 `model_not_found`). Initial: 독립 실행 2회 모두 1회 시도에 통과(15블록, validator 통과, version 1). Revised: 뒷다리 y+1 사례에서 Current 4/4 보존·Validator 거부·rejection feedback 전달·escalation 경로 확인, connectivity를 만족하는 후보는 생성하지 못함. 관련 commit: 20a70b2(prompt 보강: few-shot·자기 점검·Current 보존), fc5e4a8(Revised 일반 재설계 전략), d8acb8a(design_version 무시 버그), 4969e4a(connectivity component 피드백), aa6c72e(Revised 재시도 temperature 0.3) | offline: unit 284, integration 11, 루트 `pytest` 295 passed, 모두 exit 0. import 7개, secret grep 0건 |
| 2026-10-06 | 9·10 | WAVE 6(미commit): `voice.py` 실제 구현 — record(InputStream, RMS energy gate: 임계값 500·시작 대기 8초·끝 무음 1초·최대 10초, 침묵 b""), transcribe(`whisper-1`, 메모리 WAV multipart, 임시 파일 없음), listen(침묵이면 STT 없이 "", 장치·STT 실패 None), speak(`tts-1`, 재생 종료 + 0.5초 뒤 반환, 예외 없음), last_error(key 미포함), sounddevice·numpy 지연 import, API 재시도는 llm.py와 같은 정책. main: VOICE_IO_FAILED 메시지 `voice I/O failed: <kind>`. `tests/conftest.py`(실제 오디오·네트워크 차단), `test_voice.py`, `scripts/c_voice_smoke.py`(L2 수동 시험). Contract §4.3·§10 음성 실패 문구 갱신. 실측: STT 호출 경로는 WAVE 6 사전 확인에서 `whisper-1` HTTP 200. 실제 마이크 주변 소음 RMS p50 724·max 2880으로 임계값 500을 넘어 침묵 게이팅이 이 환경에서 성립하지 않음(임계값 조정 필요). 문장 인식은 USER RUN REQUIRED. TTS는 `tts-1`·`gpt-4o-mini-tts` 모두 403 `model_not_found`로 BLOCKED, echo·음성 대화 e2e도 BLOCKED | offline: unit 313, integration 11, 루트 `pytest` 324 passed, 모두 exit 0 |
| 2026-10-06 | 9·10 | WAVE 6 후속(미commit): TTS key 분리 — STT는 `OPENAI_API_KEY`, TTS는 `OPENAI_TTS_API_KEY`만 사용(서로 대체 없음, 사용자 지시), `_request`가 key 변수 이름을 인자로 받음, `missing_key` 메시지는 변수 이름만 담음. `c_voice_smoke.py echo`(speak → listen 1회, 관측값만 출력, 파일 저장 없음) 추가. 실측: `tts-1` / alloy / wav, TTS 요청 key 변수 `OPENAI_TTS_API_KEY`, 응답 248,444 bytes, WAV 5.17초·24,000 Hz, play → sd.wait() 반환 5.30초, 재생 종료 → listen 시작 0.50초. listen 결과 "프로젝트 만족"(TTS 문장과 유사도 0.09) → echo 재인식 아님, 배경 소음이 임계값을 넘어 STT로 간 소음 환각으로 판정. 스피커에서 실제로 들렸는지는 사용자 청취 확인 필요. 음성 대화 e2e(dialogue)는 미실행 | offline(두 key 변수 미설정): unit 317, integration 11, 루트 `pytest` 328 passed, 모두 exit 0 |
| 2026-10-06 | 9·10 | 사용자 실제 음성 E2E(`scripts/c_e2e_smoke.py`, 실제 마이크·STT `whisper-1`·LLM `gpt-4o`·TTS `tts-1`, 결과 envelope은 /tmp): initial OK, version 1, 15블록(validate_design PASS) / revise color(layer 2 블록 색 교체, "2번") OK·REVISE, version 2, 19블록, 질문 1개 / revise leg(뒷다리 y+1, "2번") OK·REVISE, version 2, 17블록, 질문 1개 — 실제 LLM 6번째 후보가 Validator 통과, escalation 미발생. **Revised live 성공 사례**(사용자 인정). escalation 음성 경로는 미검증: 결정적 시험용 `revise --scenario leg --force-reject` 추가(스크립트 프로세스 안에서만 가짜 생성기로 6회 거부, LLM API 요청 0), 실제 음성 실행 대기. 결과 파일 이름 정리: color `/tmp/c_design_revised_color_result.json`, leg `/tmp/c_design_revised_leg_result.json`, force-reject `/tmp/c_design_escalation_result.json` | 사용자 실행 결과를 /tmp envelope으로 Fable이 확인. force-reject 경로는 가짜 음성·네트워크 차단 dry run만(실측 아님). offline: unit 317, integration 11, 루트 `pytest` 328 passed |
| 2026-10-06 | 9·10 | WAVE 6 완료(사용자 승인). live 검증 완료 항목: 실제 마이크 입력, `whisper-1` STT, `tts-1` TTS(`OPENAI_TTS_API_KEY` 전용), 실제 스피커 재생, TTS 종료 후 listen, 음성 '의자 만들어줘' → CHAIR → `gpt-4o` → Validator PASS → Initial v1, Difference / HRI → TTS 질문 → '2번' → REVISE → `gpt-4o` Revised → Validator PASS → v2·Current 보존, 강제 Reject 6회 → escalation TTS → '1번' → MOVE_BACK / KEEP → 기존 Design 유지. 전체 진행률 100%. 이후는 기능 개발이 아니라 A/B/C/D 통합 단계 | offline: unit 317, integration 11, 루트 `pytest` 328 passed |

## Known limitation / Day4 이후

- Initial Design live generation 검증 완료.
- Revised generation live 경로 검증 완료.
- Current 보존·Validator·rejection feedback 검증 완료.
- 현재 테스트 사례(뒷다리 y+1)에서는 connectivity를 만족하는 Revised 후보 생성에 실패했습니다. 2026-10-06 실제 음성 E2E에서는 6번째 후보가 통과했습니다(비결정적: 같은 사례도 실행마다 성공·실패가 달라질 수 있음).
- 이 경우 Day4에서는 escalation → 사용자 원복 → KEEP을 정상 Recovery 경로로 사용합니다(2026-10-06 사용자 결정).
- 보다 자유로운 Revised 재설계 성능 개선은 Day4 이후 과제입니다.
- 개선 항목(구현 안 함): Revised LLM이 기존 Design·few-shot 예시에 과도하게 고착되는 현상을 줄이기 위해 Revised Prompt에서 기존 Design 전체 의존도를 낮추고 Current + Difference 중심으로 재설계를 유도하는 Prompt 구조를 검토한다.

### Day4 이후·통합 단계에서 결정할 항목

- 음성 입력 RMS 고정 임계값(`RMS_THRESHOLD` 500): 실측 환경의 배경 소음(RMS p50 724, max 2880)보다 낮아, 말하지 않아도 소음이 STT로 넘어가 환각 텍스트가 생길 수 있음. 적응형 noise floor 미구현.
- Initial 음성 경로의 침묵 처리: `create_initial_design`은 `listen()`을 한 번만 호출하므로, 시작 대기(8초) 안에 말하지 않으면 `UNSUPPORTED_OBJECT`로 끝남. Intervention처럼 계속 기다리지 않음.
- 색 차이 escalation 문장: 위치가 같은 색 차이에도 "같은 위치로 옮겨 주시겠어요?" 형태의 문장이 나옴(`dialogue.escalation_question`).
- (f) Revised Prompt 재구성(위 개선 항목): deferred.
- dialogue의 애매한 응답 LLM fallback: 미연결(현재 Python Rule만 사용).
- TTS 모델 권한: LLM / STT용 project key(`OPENAI_API_KEY`)로는 `tts-1`·`gpt-4o-mini-tts`가 HTTP 403 `model_not_found`. TTS는 전용 key `OPENAI_TTS_API_KEY`가 필요하며 두 key를 서로 대체하지 않음.
