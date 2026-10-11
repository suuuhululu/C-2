# C Stage3 A·D 정합 검증 — 2026-10-11

## 기준과 범위

수현님 지시에 따라 C PR #23의 최종 vocabulary와 Preview/Review lifecycle에 A·D를 맞췄습니다. 검증 기준은 integration `8fe480f`와 기존 HMI·DB PR #22 `d051809`를 합친 로컬 기준 `67fab1c`입니다. C source와 A의 기존 순서 계산 본문 및 REAL 측정 자료는 보존했습니다. 10/8 계약에서 B가 Current·current_revision·Expected·공간 비교를 확정하고 D가 실행·진행·최종 종료를 담당합니다.

소스·Schema·화면·문서·회귀 검사에 걸친 변경이므로 여러 파일이 필요합니다. 신규 production 모듈은 후보 상태를 분리하는 `app/c_candidate.py` 하나이며 신규 클래스·프레임워크·runtime dependency는 없습니다. 기존 C public API를 호출합니다.

## 실제 실행 결과

| 검사 | 결과 |
|---|---|
| A/D/C 호출·5층·계약·HMI·Robot FAKE 관련 12개 검사 파일 | 504 passed, 4 warnings, 70.94초 |
| 신규 Stage3 연결 경계 | 22 passed, 2 warnings, 1.36초 |
| 전체 unit/integration + A planner | 2243 passed, 31 failed, 11 errors, 34 skipped, 22 warnings, 183.18초 |
| 수정 전 동일 합성 기준의 REAL 관련 5개 파일 | 47 passed, 31 failed, 11 errors |
| REAL 실패/오류 node ID 비교 | 수정 전/후 42개 집합 동일 |

관련 검사는 PASS, 전체 검사는 PASS가 아닙니다. 남은 REAL 검사에는 `/home/ms-02/C_2/interfaces/robot_trial_blue5.json` 및 `/home/ms-02/C-2_협동2자료/...` 등 이 PC에 없는 측정·원본 파일이 필요합니다. 이번 변경의 성공으로 집계하지 않습니다. RefResolver deprecation 경고는 기존 Schema 검증 방식이며 lint/type/CI는 미구성입니다.

## 확인한 동작

- C validator → 실제 A planner → D contract → HMI: 빨강 2점, 두 방향, 5층 및 연결된 40블록 수용; 41블록과 잘못된 재고 조합 거절.
- 후보/사용자 승인/Backend 채택 분리, Qt Preview 완료 후 Review 시작, MODIFY 재표시, APPROVE 뒤에만 실제 A 계획 요청.
- Revised Current 보존과 같은 후보군의 버전 유지, metadata 분리, duplicate·stale·다른 Job/Current revision·STOP 이후 응답 거절.
- C 음성 public API 연결을 Fake로 검사, TTS 완료 뒤 STT 순서, TTS 실패 시 보류 및 실행 요청 없음.
- 승인 전 STOP/RESUME에서 새 C 요청을 열고 Pick을 만들지 않음.
- 다섯 공급열 여섯 슬롯 FAKE 보충; 기존 네 열 설정의 빨강 요청은 I/O 전에 거절; HMI/Day4 Schema 정합.

## 실행 환경과 재현

Python 3.12, pytest 7.4.4, Qt offscreen입니다. 기존 시험 전용 jsonschema 의존성을 `/tmp`에서 읽었습니다. `tests/conftest.py`의 네트워크·음향 차단과 Fake 응답을 사용했습니다. 실제 OpenAI·마이크·Robot/Camera·DB 연결은 실행하지 않았습니다.

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=/tmp/c2-hmi-db-test-deps:/tmp/c2-round1-schema-test-deps:.:tests/unit \
python3 -m pytest -q \
  tests/integration/test_c_stage3_ad_alignment.py \
  tests/integration/test_c_function_hmi.py tests/integration/test_c_voice_hmi.py \
  tests/integration/test_a_backend.py tests/integration/test_five_layer_pipeline.py \
  tests/unit/test_contracts.py tests/unit/test_hmi_contracts.py \
  tests/unit/test_planner_results.py tests/unit/test_robot_controller.py \
  tests/unit/test_robot_backend.py tests/unit/test_replan.py tests/unit/test_qt_hmi.py
```

동일 환경에서 전체 대상은 `tests/unit tests/integration planning_trial/test_planner.py`입니다. 상세 로그는 게시하지 않은 로컬 `/tmp/c2-stage3-final-required.log`, `/tmp/c2-stage3-final-full.log`, `/tmp/c2-stage3-real-baseline.log`에 있습니다.

## 정적 확인

변경/신규 33개 파일의 Python·JSON 파싱 및 `git diff --check`를 통과했습니다. 변경 Markdown의 상대 파일 링크 검사에서 신규 누락은 없으며 STATUS의 과거 로컬 로그/이미지 링크 14개는 보존했습니다.

## 남은 통합 조건

- BLOCKER: 최신 B 실제 생산자의 Current/Difference와 D 소비자 연결을 공동 확인해야 합니다. 합성 B 시험은 실제 Vision 검증을 대신하지 않습니다.
- REQUIRED CHANGE: REAL 빨강 공급은 담당 장비의 pose·파지·공급열 검증 자료를 준비한 후 별도 구현/검증해야 합니다.
- AFFECTED INTERFACE: C Candidate/Review → A Plan/Replan → D HMI/진행 및 공통 block vocabulary.
- REASON: C가 생성한 빨강 후보를 A/D가 거절하는 문제와 승인 전 계획 채택을 막기 위한 정합 변경입니다.

PR #22는 Draft로 유지하며 사람 리뷰와 공동 FAKE 시험 뒤 병합 여부를 판단합니다. 이번 결과는 실제 Robot 직접 결착·최종 Vision·사용자/Job/웹 전체 통합 완료를 뜻하지 않습니다.
