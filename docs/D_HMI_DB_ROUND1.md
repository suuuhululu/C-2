# HMI·DB 1차 통합 검토 — 2026-10-11

수현 제공 `C2_HMI_20261011.zip`, `C2_DB_20261011.zip`와 외부 DB 실행 안내를 검토하고, `codex/integration-round1`의 `0325fd6` 위에 소스·계약·Fixture·시험·실행 안내만 선택 반영했습니다. 원본 ZIP과 원자료는 그대로 보존합니다. 배포 Manifest·이전 시험 산출물·화면 이미지·로컬 비밀번호는 소스에 포함하지 않습니다.

## 적용 기준

수현의 2026-10-11 명시적 결정에 따라 [10/8 계약](handover/final_mvp_interface_20261008/README.md)을 우선합니다.

- B: Current, current_revision, Expected, 공간 비교, 관측 품질.
- D: 검사 식별·유효성 대응, 실행·진행, 최종 종료, HMI·DB.
- A: B가 발급한 revision을 D를 통해 받아 계획 입력에 복사.
- 공통 배치: 기존 6필드, 정수 layer 1~5. 범위 밖 시험은 6층.

기존 `app/backend.py`는 Day4의 D 상태 채택·비교 구현입니다. 이번 PR은 이 구현을 최신 B 소유 실행기로 바꾸지 않습니다. 구형 연결의 5층 회귀 시험과 최신 B 계약 결과의 HMI·DB 소비 시험을 구분합니다. B 결과를 받은 뒤 다시 Day4 관측으로 재비교해 revision을 발급하면 안 됩니다.

## 검토 결과와 변경

| 연결 | 확인 결과 | 남은 작업 |
|---|---|---|
| C Design → 기존 A Plan → Day4 D → Qt | 실제 Python 모듈, Fake Robot·합성 관측으로 1~5층 및 30블록 회귀 통과 | 최신 B 실행 경로의 검증으로 간주하지 않음 |
| B 10/8 Response → HMI | 계약 Fixture로 5층, revision=17, MISMATCH, 아래 4층 보존 및 무명령 표시 확인 | 실제 B 생산자와 D snapshot 매핑 연결 |
| B Response → JSONL → DB → 개인 조회/저장 | 실제 PostgreSQL에서 raw·revision 보존, 중복 적재/저장, 소유자 격리 확인 | D CHECK_RESULT 로그 생산과 로그인 세션의 owner 연결 |
| 새 HMI 대화·설계 확정·도움·저장 요청 | UI 계약·식별·중복 방지 단위 시험 통과 | D 수신부 및 C/B/DB 호출 연결; 필드가 없는 기존 snapshot은 새 요청 기능을 숨김 |
| 최신 A 후보 API 0.5.1 | 별도 A 정정 PR [#21](https://github.com/suuuhululu/C-2/pull/21), B provenance로 시험 완료 | 이 PR에는 오래된 A 트리 전체를 합치지 않음. 후보 수신·채택은 별도 연결 |
| 웹 기록 반영 | `NOT_CONNECTED` 표시 | 실제 웹 앱·인증·조회 연결 |

원 ZIP의 4층 공통 runtime/schema를 5층으로 맞췄습니다. HMI의 B 최종 검사 `MISMATCH/UNOBSERVABLE`을 `completion.assembly=MATCH`가 덮어 성공으로 표시할 수 있던 충돌을 거절합니다. `status=OK`와 `comparison=UNOBSERVABLE` 조합도 거절합니다. DB Expected 재계산·Robot 재실행은 하지 않습니다. Docker 이력 이미지가 필요한 기존 A 모듈을 포함하도록 구성했습니다.

## 실제 검증

실행자: agent, 2026-10-11, Python 3.12.3, pytest 7.4.4, jsonschema 4.10.3, PyQt5 offscreen. Robot·Camera·음성·LLM·Isaac 실기는 호출하지 않았습니다.

- 관련 회귀 **1,159 passed**, 실패/오류/skip 0, 종료 0. 대상은 `tests/unit/test_*.py` 중 `test_real_trial_hmi.py`, `test_robot_trial.py`를 제외한 파일, `planning_trial/test_planner.py`, 아래 8개 integration 파일입니다.
- integration 대상: `test_a_backend.py`, `test_abd_callback.py`, `test_abd_input_hmi.py`, `test_five_layer_pipeline.py`, `test_hmi_db_round1.py`, `test_accounts_db.py`, `test_history_db.py`, `test_history_personal_db.py`.
- 실제 PostgreSQL 17의 새 로컬 시험 DB에서 계정·이력·개인 이력 **33개** 별도 통과. 위 1,159개 실행에도 해당 DB 시험과 신규 B 5층 왕복 시험을 포함했습니다. 기존 사용자 DB·볼륨은 사용하지 않았습니다.
- 작업 중 #19 병합 후 최신 통합 기준 `0325fd6`으로 갱신하고, 달라진 A·5층 pipeline·이력 생성 관련 **166개** 추가 회귀 통과. 기존 병합 문서는 보존하고 B 최신 결정 주석을 추가했습니다.
- `Dockerfile.history` 이미지 빌드 통과. 컨테이너에서 기존 Day4 Fake JSONL 생성까지 실행하여 COMPLETE 확인(최신 B 경로/실기 증거 아님).
- HMI·DB ZIP SHA256 각각 제공 체크섬과 일치. 외부 DB 실행 안내는 ZIP 내부 안내와 동일했습니다.
- 탐색적 전체 시험은 특정 PC의 `/home/ms-02/...` Robot fixture 경로 누락 및 C 함수/음성 시험 실패 등으로 중단했습니다(당시 32 failed, 135 passed, 33 skipped, 11 errors, 종료 2). 전체 PASS가 아닙니다. 대표 C 함수·음성 실패 2개는 수정 없는 integration 기준에서도 동일하게 재현했습니다. 이 PR에서 무관한 Robot 보정/경로나 C 동작을 수정하지 않았습니다.

재현은 [HMI 안내](D_HMI_RUN.md), [DB 안내](D_DB_OTHER_PC.md), [DB 계약/저장 안내](D_DB_HISTORY.md)를 따릅니다. 관련 시험은 `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=.:tests/unit`, pytest/jsonschema/PyQt5와 `requirements-history.txt` 의존성을 사용합니다. DB 시험에는 이름이 `_test`로 끝나는 별도 DB의 `HISTORY_TEST_DSN`을 설정합니다. 접속 비밀번호는 로컬 `.env.history`에만 보관합니다.

## 통합 순서와 차단 항목

1. B 담당자는 10/8 Request/Response와 5층 결과를 제출합니다. STEP/FINAL, MATCH/MISMATCH/UNOBSERVABLE, 가림 아래층 유지, revision, 취소·늦은 결과 사례를 함께 검토합니다.
2. D 담당 수현은 활성 check_id·Plan/Step·늦은 결과를 검사하고 B 결과를 snapshot/JSONL로 전달하는 경로를 연결합니다. 새 HMI 요청 수신과 사용자–Job owner도 연결합니다. Expected를 D에서 재계산하지 않습니다.
3. A 정정 #21 검토 후 필요한 A 소스만 통합하며, C/A/B/D Fake 전체 시나리오를 실행합니다. 그 뒤 실제 장치 시험을 진행합니다.

**BLOCKER:** 최신 실제 B 생산자→D 수신부, 새 HMI 요청 수신부, 로그인 owner/웹 연결이 이 자료만으로 완성되지 않았습니다. **REQUIRED CHANGE:** 담당 코드의 명시적 연결. **AFFECTED INTERFACE:** B 검사·D snapshot/CHECK_RESULT·HMI 사용자 요청·DB 소유자. **REASON:** Fixture 소비 통과는 실제 팀원 모듈 전체 연결의 증거가 아닙니다.

PR #19는 작업 중 통합 브랜치에 병합되었습니다. 그 공통 5층 runtime과 기존 기록은 보존하며, 이번 PR의 10/8 B 소유 결정을 최신 기준으로 명시합니다. #20은 정정 전에 이미 A 브랜치에 병합되어 #21로 보완합니다. 이 PR은 Draft이며 사람 리뷰·CI·실기 통과를 의미하지 않습니다.
