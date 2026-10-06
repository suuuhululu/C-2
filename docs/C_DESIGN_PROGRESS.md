# C Design 진행 현황

> 2026-10-05 계약 갱신: 아래는 기존 C 구조·작업 기록입니다. 공통 반환은 [06_CONTRACT_DRAFT.md](06_CONTRACT_DRAFT.md)의 brick_type / color / x / y / layer / orientation_deg, Design 버전, KEEP / REVISE / UNCLEAR를 따릅니다. 기존 geometry / grid_x / grid_y / 대문자 색상·KEEP_TARGET / KEEP_CURRENT의 이행은 [02_TEAM_GUIDE.md](02_TEAM_GUIDE.md)에 정리했습니다. 계속 불명확한 응답은 명시 선택 대기로 처리하며 자동 재질문 반복을 강제하지 않습니다. 코드 변경·진행률 갱신·C 계약 시험 통과를 의미하지 않습니다.


C 파트(시율: **Voice Interaction + LLM Design** — 질문 결정·생성, TTS, 녹음, STT, 응답 해석, 재질문, Target Design 생성·검증)의 진행률·현재 단계·Blocker를 기록합니다. PR마다 이 파일을 갱신합니다. 구조와 파일 책임은 [C_DESIGN_STRUCTURE.md](C_DESIGN_STRUCTURE.md)를 봅니다.

## 요약

| 항목 | 값 |
|---|---|
| 전체 진행률 | **60%** (기능 단계 10개 중 완료 6개: Contract, Fixture, Text Dialogue, Validator, Mock Initial, Mock Revised) |
| 현재 작업 단계 | 7. A/D Contract Test + Fake Voice Dialogue — REVIEW READY (WAVE 4) |
| 다음 단계 | WAVE 4 리뷰 후 8. 실제 LLM (WAVE 5) |
| 현재 상태 | `main.py` 공개 함수 2개 구현(텍스트 모드 = Fake Voice), `voice.py`는 provider 미연결 stub, `test_main.py`·`test_c_contract.py` 작성. llm은 docstring만 |
| Blocker | 지지 2 stud 기준 A(세은) 확인 대기, 실패·취소 결과 envelope D(수현) 예시 확인 대기 |
| 마지막 업데이트 | 2026-10-06 · branch `feature/c-fixture-dialogue-validator-wave2` |

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
| 7 | A/D Contract Test + Fake Voice Dialogue | REVIEW READY | 0% | A·D가 C 출력을 소비하는 계약 테스트, main 대화 루프를 fake voice로 검증 | main, tests/integration | 공개 함수만 호출, UNCLEAR 재질문, KEEP은 LLM 0회, STOP·명시적 취소 → CANCELLED | `test_main.py`·`test_c_contract.py` PASS, 연결 담당 확인 |
| 8 | 실제 LLM | 대기 | 0% | llm.py 실제 provider 연결, Design 생성과 애매한 응답 fallback | llm, designer, dialogue | API key는 환경 변수, 재시도는 designer, Robot 값 생성 금지 | 실제 호출 결과가 Validator 통과, 실패 경로 확인 |
| 9 | 실제 STT + 녹음 | 대기 | 0% | 녹음 → 한국어 텍스트, 목표·응답 공용 | voice (녹음·STT) | 짧은 응답("1번") 오인식 실측, L2 장치 시험 | 실제 녹음 샘플 인식 결과 기록 |
| 10 | 실제 TTS + Voice Dialogue 완성 | 대기 | 0% | C 담당 TTS 질문 재생과 음성 대화 전체 연결 | voice (TTS), main | 재생 종료 후 녹음 시작으로 질문 음성 재인식 방지(F05·F07), echo 방지 실측 | 실제 음성 대화 1회 이상 기록, echo 재인식 없음 확인 |

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
