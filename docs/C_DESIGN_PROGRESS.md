# C Design 진행 현황

C 파트(시율: **Voice Interaction + LLM Design** — 질문 결정·생성, TTS, 녹음, STT, 응답 해석, 재질문, Target Design 생성·검증)의 진행률·현재 단계·Blocker를 기록합니다. PR마다 이 파일을 갱신합니다. 구조와 파일 책임은 [C_DESIGN_STRUCTURE.md](C_DESIGN_STRUCTURE.md)를 봅니다.

## 요약

| 항목 | 값 |
|---|---|
| 전체 진행률 | **0%** (기능 단계 10개 중 완료 0개) |
| 현재 작업 단계 | 1. Contract — READY |
| 다음 단계 | 1. Contract 착수 |
| 현재 상태 | 승인 구조로 `app/c_design/` 6개 모듈 docstring skeleton과 `tests/` 폴더 준비. 기능 코드·테스트 없음 |
| Blocker | 없음 |
| 마지막 업데이트 | 2026-10-05 · branch `feature/c-design-contract` |

진행률은 완료 기준을 충족한 단계만 셉니다. 단계 하나 = 10%. 진행 중인 단계는 표의 진행률 칸에만 표시하고 전체 진행률에는 더하지 않습니다. **Skeleton·문서 변경은 개발 단계 완료로 계산하지 않습니다.**

## 상태 값

| 값 | 의미 |
|---|---|
| 대기 | 앞 단계 미완료로 시작 전 |
| READY | 시작 가능, 아직 착수 전 |
| 진행 중 | 작업 중, 완료 기준 미충족 |
| 리뷰 | PR 리뷰 중 |
| 완료 | 완료 기준 충족·Merge |
| BLOCKED | 외부 확인 대기로 진행 불가 (Blocker 칸에 사유 기록) |

## 개발 단계

| 순서 | 작업 단계 | 상태 | 진행률 | 작업 설명 | 관련 모듈 | 알아야 할 핵심 | 완료 기준 |
|---|---|---|---|---|---|---|---|
| 1 | Contract | READY | 0% | main 공개 함수 Input/Output, Target / Current / deviation context 형식, 의도값, 실패 반환, Validation 책임 정의 | main, dialogue, designer, validator | layer 1-based(1~4), grid_x/grid_y 0~23은 Board stud 위치(Robot mm 아님), orientation_deg는 GT 정의, 의도값 KEEP_TARGET / KEEP_CURRENT / UNCLEAR | 계약 문서 작성, A·D 담당 확인 |
| 2 | Fixture | 대기 | 0% | 정상·invalid·경계 Target Design / Current / deviation context / 응답 텍스트 예시 | tests | Contract 형식을 그대로 따르고, 다른 담당이 같은 Fixture를 재사용 | Fixture가 Contract와 일치, 연결 담당 확인 |
| 3 | Text Dialogue | 대기 | 0% | 질문·재질문 문장 생성, 텍스트 응답 → KEEP_TARGET / KEEP_CURRENT / UNCLEAR, 목표 사물 인식 | dialogue | 선택지 상수 1번 KEEP_TARGET / 2번 KEEP_CURRENT를 질문과 해석이 공유, Python Rule 우선, LLM fallback은 8단계 이후 | `test_dialogue.py` PASS (정상·오매칭·부정·UNCLEAR) |
| 4 | Validator | 대기 | 0% | color·geometry·grid·layer·orientation·범위·overlap·support·connectivity·preserved·malformed·Robot field 검증 | validator | 순수 Python, LLM 판단 금지, 실패 항목·사유 목록 반환 | `test_validator.py` 규칙별 정상 / invalid PASS |
| 5 | Mock Initial Design | 대기 | 0% | 목표 사물 → 고정 Initial Target Design (LLM 없음) | designer, main | 출력이 Validator 통과, 식별·버전은 Python이 결정 | `test_designer.py` Initial PASS |
| 6 | Mock Modified Design | 대기 | 0% | Target + Current + KEEP_CURRENT → Current 배치 보존 전체 Target | designer, validator | 보존 대상은 Python이 Current 기준 결정, 새 Target Design까지만(조립 순서·NextPart는 A) | preserved 검증 포함 `test_designer.py` PASS |
| 7 | A/D Contract Test + Fake Voice Dialogue | 대기 | 0% | A·D가 C 출력을 소비하는 계약 테스트, main 대화 루프를 fake voice로 검증 | main, tests/integration | 공개 함수만 호출, UNCLEAR 재질문 반복, KEEP_TARGET은 LLM 0회 | `test_main.py`·`test_c_contract.py` PASS, 연결 담당 확인 |
| 8 | 실제 LLM | 대기 | 0% | llm.py 실제 provider 연결, Design 생성과 애매한 응답 fallback | llm, designer, dialogue | API key는 환경 변수, 재시도는 designer, Robot 값 생성 금지 | 실제 호출 결과가 Validator 통과, 실패 경로 확인 |
| 9 | 실제 STT + 녹음 | 대기 | 0% | 녹음 → 한국어 텍스트, 목표·응답 공용 | voice (녹음·STT) | 짧은 응답("1번") 오인식 실측, L2 장치 시험 | 실제 녹음 샘플 인식 결과 기록 |
| 10 | 실제 TTS + Voice Dialogue 완성 | 대기 | 0% | C 담당 TTS 질문 재생과 음성 대화 전체 연결 | voice (TTS), main | 재생 종료 후 녹음 시작으로 질문 음성 재인식 방지(F05·F07), echo 방지 실측 | 실제 음성 대화 1회 이상 기록, echo 재인식 없음 확인 |

## 변경 이력

| 날짜 | 단계 | 변경 | 검증 |
|---|---|---|---|
| 2026-10-05 | 0. 준비 | `app/c_design/` 6개 모듈 docstring skeleton, 진행·구조 문서 추가 | `python3 -c "import app.c_design"` 및 각 모듈 import 성공, side effect 없음 확인 |
| 2026-10-05 | 0. 준비 | `stt.py` → `voice.py`, `intent.py` → `dialogue.py` rename. C 역할을 Voice Interaction + LLM Design으로 docstring·문서 갱신(질문 생성·재질문·TTS는 C) | 7개 모듈 import 성공, import문·실행 코드 없음, production `.py` 6개 확인 |
