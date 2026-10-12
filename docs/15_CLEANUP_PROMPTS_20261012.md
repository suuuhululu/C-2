# 코드·테스트 정리 후보와 후속 프롬프트 — 2026-10-12

## 후속 프롬프트 사용 전 확인

[최신 대화 반영](16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md)을 먼저 확인합니다. 아래 후보·프롬프트는 de59b08 점검 당시 자료이며 새 원격은 A PR #28·문서 PR #31 포함 `727d101`입니다. A 단일 코드/예제/보존 분류는 PR #31에서 이미 정리했으므로 중복 삭제·재작성을 하지 않습니다. 로컬 D 다섯 문제와 교시 보완을 미구현으로 가정하지 않습니다. 실행용 SIM 정렬은 여전히 남지만 실패 시험·원본 삭제는 이번에도 수행하지 않았습니다.


이번에는 삭제·코드 수정하지 않았다. 기준은 integration `de59b083ad7a5b2225b372078654d2af3a28255b`, main `afd75d0b0943d85b44248ea563e89f860921e1dd`다. 아래는 사용자가 후속 작업을 지시할 때 사용할 프롬프트다. [통합 점검](14_INTEGRATION_REVIEW_20261012.md)의 A/C 수정과 D 다섯 문제 작업을 중복 수행하지 않는다.

## 후보 판정

| 후보 | 확인한 근거 | 권장 처리 |
|---|---|---|
| 구형 Isaac 실행 입력/시험 | `isaac_sim/config/whole*.request.json`의 API 0.5, `scripts/scenario_core.py`의 4층 제한; completion priority 시험 4건 실패 | 실행용 입력·연결 갱신. 실패 시험은 유지하고 계약 정렬 후 재검사 |
| 원본 A 시험 복사본 | `planning_trial/test_supply_pick.py`, `test_assembly_optimizer.py`, `test_assembly_target.py`, `test_user_assembly_rules.py`와 `isaac_sim/fixtures/original_a/planning_trial/`의 대응 파일이 바이트 동일 | 원본 보존. 실행 대상의 권위만 명시. 현재 pytest.ini 기본 수집은 원본 디렉터리를 포함하지 않으므로 당장 삭제할 이유 없음 |
| pytest 진입 설정 | pytest.ini는 planning_trial/isaac_sim/scripts/tests, pyproject.toml은 tests; B/D 하위 시험은 기본 수집 목록 밖 | 실제 사용되는 설정·명령을 명시하고 하위 독립 시험 포함 방법 확인. 실패를 감추는 제외 추가 금지 |
| 구형 음성/승인 Fixture | 이전 review-results의 음성 관련 실패, `tests/integration/test_real_voice_workflow.py`, `test_real_voice_replan.py`가 기존 전달 흐름에 연결 | 최신 producer 의미와 Day4 보존 범위 대조 후 Fixture 수정 필요성 판단. 이번에 이 시험들을 재실행하거나 삭제 필요성을 확정하지 않음 |
| 구형 Backend/전달 진입점 | `app/backend.py`는 `app/real_workflow_hmi.py`와 기존 시험/음성 도구가 참조 | 죽은 코드로 단정하지 않음. 최종 MVP와 격리·안내 필요. 사용자 사용 여부와 회귀 범위를 확인한 뒤 폐기 검토 |
| 대형 모델/학습·관측 자료 | `perception/models/`의 여러 .pt, `perception/labeling/hand_dataset/hand_train_trial.zip`, `perception/recordings/` 원자료 | 코드와 자산의 관리 분리 후보. 런타임 참조·재현 가치 확인 후 보존 위치/해시/경로를 제안; 무단 삭제 금지 |

두 원격 트리에서 추적된 `.pyc`/`__pycache__`는 확인되지 않았다. main에는 새 MVP/Robot/Isaac/perception 묶음이 없고 기존 C/A/D·이력·시험이 남아 있다. main의 테스트/코드를 미사용이라는 이유로 즉시 삭제할 근거는 이번 점검에서 확보하지 못했다. 파일 크기나 실패 여부만으로 삭제를 결정하지 않는다.

## 프롬프트 1 — 실행용 SIM과 원본 시험의 경계 정리

```text
C-2 최신 원격 main/integration SHA와 AGENTS.md·확정 인터페이스를 먼저 확인하라.
원래 /home/ms-02/C_2 지정 브랜치·미완료 변경을 보존하고 격리 사본에서 작업하라.
A 담당자의 실행용 Isaac 계약 정렬 결과를 확인한 뒤, 원본 보존 자료와 실행용 입력의
경계를 정리하라. isaac_sim/fixtures/source, fixtures/original_a, protected_sources.json의
원본과 해시는 보존하라. 동일 A 시험 복사본 네 쌍을 확인하고 실제 pytest 수집에
중복이 있는지 검증하라. 기본 수집에서 제외된 보관 파일을 불필요하다고 삭제하지 마라.
whole→reassessment→motion 및 5층/실패 반환을 확인하고 기존 assertion을 약화하지 마라.
API 0.5 실행 입력으로 생기는 실패는 정렬 대상으로 보고하라. 실제 Isaac 물리 실행,
Robot/Camera/음성/외부 LLM 실행, commit/push/PR/merge/게시는 수행하지 마라.
변경 전후 파일·검사 수·실패 원인·원본 해시 보존 결과를 보고하라.
```

## 프롬프트 2 — 시험 수집·구형 음성 Fixture 정리

```text
C-2의 pytest.ini와 pyproject.toml 중 실제 적용되는 설정을 확인하고,
tests/conftest.py의 네트워크/음성 차단과 perception·robot_control_integration의
독립 import 경계를 확인하라. 두 app 패키지를 같은 import 경로에 합치지 마라.
기본 검사와 B/D 하위 검사를 실행하는 명령·환경·장치 차단 범위를 문서로 정리하라.
test_real_voice_workflow.py와 test_real_voice_replan.py의 이전 실패 기록을 현재
C Preview/Review/승인 계약 및 Day4 생산자와 대조하라. 최신 기능의 회귀 시험인지,
구형 Fixture인지 구분해 최소 갱신 후보를 제시하라. 실패를 이유로 삭제·skip·xfail을
추가하거나 assertion을 약화하지 마라. 이번 대상의 정상/실패/취소 의미를 유지하라.
사용자의 후속 정리 지시 범위 안에서만 수정하고, 실제 장치/음성/외부 API와 운영 DB는
사용하지 마라. main/integration을 자동 병합하거나 원래 작업 브랜치를 전환하지 마라.
중복 검사 집합을 합산하지 말고 각 명령의 결과·종료 코드·남은 실패를 보고하라.
```

## 프롬프트 3 — 구형 진입점과 미사용 코드 판별

```text
C-2 main과 integration의 최신 SHA에서 기존 Day4 Backend/real_workflow_hmi와
최종 MVP mvp_workflow/mvp_integration, B 없는 cad_real_trial의 진입점을 대조하라.
함수/CLI/실행 스크립트/시험/문서 참조를 조사하고, 동적 호출 가능성도 확인하라.
참조가 적다는 이유로 dead code로 단정하지 마라. 사용 중인 전달 흐름의 Current/Expected
비교를 최종 MVP B 소유 흐름과 동시에 실행하지 않는 경계를 확인하라.
실제로 미사용이 확인된 항목만 위치·근거·영향·보존할 시험과 함께 삭제 후보로 제시하라.
먼저 후보 목록을 보고하고 이 프롬프트만으로 삭제하지 마라. D 다섯 문제 수정과
A/C/B 담당 기능을 대신 구현하지 마라. 원자료·실측 설정·기존 변경·지정 브랜치를 보존하라.
```

## 프롬프트 4 — 모델·관측 원자료 보존과 저장소 크기 정리

```text
perception/models, perception/labeling/hand_dataset/hand_train_trial.zip,
perception/recordings와 robot_control_integration/settings의 원자료·시험 근거를 조사하라.
현재 모델/실행 설정/문서/시험이 참조하는 경로와 각 파일의 해시·용량·재현 목적을 적어라.
중복 자산 또는 운영 실행에 필요 없는 과거 세션을 구분하되 원본은 삭제하지 마라.
보존 위치·다운로드/복원 절차·해시 확인·기존 경로 호환 방안을 문서로 제안하라.
새 저장 서비스·dependency를 설치하거나 Git 이력을 재작성하지 마라.
사용자 승인 없이 모델/실측/학습·관측 원자료를 이동·삭제하거나 현장 Robot 설정을 바꾸지 마라.
```
