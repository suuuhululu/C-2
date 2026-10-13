# 최신 integration 점검과 진행 중 수정 — 2026-10-12

## 후속 상태 안내

이 문서의 de59b08 불량 재현·의자 실패·검사 수치는 당시 결과로 보존합니다. 최신 상태는 [최종 통합용 대화 반영](16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md)을 우선합니다. D 다섯 문제는 로컬 수정/모의 검증 기록이 있고 A PR #28이 원격·로컬에 반영됐습니다. 원격은 자료 분류 PR #31까지 포함한 `727d101`이며 로컬 D/교시/전체 기능 변경을 모두 포함하지 않습니다. 당시 미해결 목록을 현재 로컬 상태로 그대로 읽지 않습니다. 접촉·인계·속도 개선은 진행 중입니다.


이 문서는 원격 코드에서 확인한 상태와 담당자에게 요청한 수정 목표를 구분한다. 이번 작업은 문서 반영과 격리 사본의 장치 없는 재현이며 코드 수정·삭제·commit·push·PR·merge·게시를 수행하지 않았다. D의 다섯 문제는 다른 채팅에서 수정 중이다. 그 작업의 결과를 이 문서의 원격 확인 결과에 합산하지 않는다.

## 1. 기준과 읽는 순서

| 대상 | 확인한 SHA / 의미 |
|---|---|
| 최신 `codex/integration-round1` | `de59b083ad7a5b2225b372078654d2af3a28255b` |
| 최신 `main` | `afd75d0b0943d85b44248ea563e89f860921e1dd` |
| 이전 검토 기준 | `89143206a6d61af1babae9295b9bd67a7ad1bcac` + PR #26 `3f0bdd1ba6b40fe6582994b50f01d65c19513a42` + PR #27 `a743d1b5e03bdd544ae99c797804b7765daabd31` |
| 병합 확인 | PR #27 merge `28348db` → PR #26 merge `de59b08`.두 PR head 모두 최신 integration의 조상임을 Git 객체로 확인 |
| 로컬 작업 위치 | `/home/ms-02/C_2`의 `work/suhyun-hmi-backend-robot-db` 유지. 원격 코드 자동 병합·브랜치 전환 없음 |

[10/8 확정 인터페이스](handover/final_mvp_interface_20261008/README.md)의 책임·승인·Expected·취소 경계는 유지한다. [10/11 비교](12_INTEGRATION_SYNC_20261011.md)는 당시 `02137d8` 기록이다. 최신 원격의 [실행 업데이트 문서](https://github.com/suuuhululu/C-2/blob/de59b083ad7a5b2225b372078654d2af3a28255b/docs/13_RUNTIME_UPDATE_20261012.md)와 아래 확인 결과를 함께 읽는다. 원격 업데이트 문서의 “병합 전” 표현은 작성 당시 기록이며 현재 두 PR은 integration에 병합돼 있다. main에 동일 기능이 반영됐다고 해석하지 않는다.

원 검토 자료와 재현 스크립트는 integration-simulation-20261012（로컬 증거 경로：`/home/ms-02/C-2_협동2자료/work/integration-simulation-20261012/`）에 보존했다. 이번 재현은 원격 SHA의 `/tmp/c2-doc-review-20261012/integration` 사본에서 수행했다. [이번 검사 기록](reviews/integration_20261012_review.json)은 문서 근거이며 런타임 Schema가 아니다.

## 2. 실제 연결과 남은 경계

| 담당/기능 | 최신 원격에서 확인 | 미구현·미검증 또는 제한 |
|---|---|---|
| C | 후보 Preview → C Review → 대화 APPROVE → A 전달; A 계획 실패를 `c.plan_failure` 문맥으로 전달하는 D 분기 | 기본 의자가 현재 설정에서 계획 실패. 구체적 실패 이유·수정 대화·재승인 왕복은 담당자 수정/검증 필요 |
| A | API `assembly-ad-calculation-draft/0.5.1`, bundle `0.1.1`; 전체 계획 → Step 재평가 → Step 경로 후보 | 의자 실패 원인 구체화, 실행용 Isaac 입력 정렬 필요. 후보 `execution_allowed=false` 유지 |
| B | 실제 Python 검사 함수를 MOCK 관측과 연결; Expected·Current/revision 확정 결과를 D가 소비 | B 전체 기능 완성·실영상·Camera 연결 완료로 해석하지 않음 |
| D | `app.mvp_integration`에서 A 세 호출 → D 진행 → 별도 MOCK Robot 프로세스 연결; B 결과에 따라 진행 | 아래 STOP·ERROR 재검사·슬롯·충돌 결과·REVISE 경계 수정 중 |
| HMI/이력/웹 | B 결과·D 상태 표시, JSONL 및 개인 저장/웹 코드가 원격에 포함 | 이번 DB/웹 왕복 재시험 없음. 수정된 D 상태와 snapshot/JSONL 일치 확인은 후속 완료 조건 |
| 실물 C→A→D | `app.cad_real_trial`은 B 없는 별도 시험; `ROBOT_GRIP + NONE`만 선택 | 가정 누적 배치는 B Current가 아님. 사람 도움/직접 조립·전체 MVP 실물 완료 증거 아님 |

전체 계획 호출은 Plan 생성/재계획마다 한다. Step마다 D 준비 입력 → A 직전 재평가 → A 경로 후보 → D 실행 조건 확인 → 로봇 실행으로 이어진다. A 경로를 무조건 실행하지 않고 D의 기존 실행 프로필과 정합성을 확인한다. 실제 정지·파지·Contact·슬롯 예약·도움 준비/해제 경계를 유지한다.

종류·색상별 공급 슬롯은 독립적으로 1→2→3→4→5→6→1을 순환한다. 재검사·중복 검사 이벤트는 새 집기가 아니므로 슬롯 소비나 모의 장면 효과를 반복하면 안 된다. 공급판은 항상 보충된다는 운영 전제이며 40블록 Design 제한과 별개다.

## 3. A/C 담당자 수정 요청

### 의자 설계 실패와 수정 대화

최신 원격으로 네 설계를 두 설정에서 계산했다. C 오프라인 기본 15블록 의자, `planning_trial/sample_design.json`, `sample_modified_design.json`은 MVP와 CAD 모두 `NO_FEASIBLE_ORDER`였다. 5블록·5층 적층은 두 설정 모두 `COMPLETED`였다. 반환 오류는 현재 `code=NO_FEASIBLE_ORDER, reason=NO_FEASIBLE_ORDER, block=null`로 구체적 막힘 원인을 충분히 전달하지 못한다.

`NO_FEASIBLE_ORDER`는 현재 계산 조건에서 완성 순서를 찾지 못한 결과다. 실제 설계가 물리적으로 불가능하다고 단정하지 않는다. `SEARCH_LIMIT`는 탐색 한도 도달이며 같은 원인이 아니다. 과거 26블록의 `SEARCH_LIMIT` 기록을 이번 의자 결과에 덮어쓰거나 해결됐다고 표시하지 않는다.

- A: 원시 반환·막힌 블록·도움/그리퍼 접근/설정 조건을 확인하고 C가 활용할 실패 사유를 전달한다. 실제 불가한 설계를 억지로 통과시키거나 임의 Plan으로 대체하지 않는다.
- C: A 실패 이유로 수정 대화 → 수정 후보 표시 → 사용자 대화 재승인 → A 재계산을 확인한다.
- D: 승인 목표·B Current·진행 기록을 유지하며 대기한다. 다른 샘플로 바꾸어 실행하지 않는다.

### 실행용 Isaac 입력

`isaac_sim/config/whole*.request.json`과 `validation_three_blocks.request.json`에는 API 0.5가 남아 현재 A 0.5.1의 입력 검사에서 `INVALID_CONTEXT`가 된다. `isaac_sim/scripts/scenario_core.py`에는 4층 제한도 남아 있다. 원본 `isaac_sim/fixtures/source`, `fixtures/original_a`와 보호 해시는 보존한다.

실행용 요청·연결부는 전체 계획뿐 아니라 재평가·경로 요청의 문맥·프로필·기준 Current까지 함께 정렬해야 한다. 현재 소프트웨어 5층 범위와 옛 4층 시나리오를 구분한다. 완료 확인은 정상/실패 반환 및 세 호출 연결이며, 실제 Isaac 물리 실행·IK·충돌·체결 검증과 구분한다.

## 4. D의 다섯 문제: 원격 재현과 수정 완료 조건

| 문제 | 최신 원격에서 재현한 동작 | 다른 채팅의 수정 완료 조건 |
|---|---|---|
| 불일치 대화 중 STOP | MISMATCH → WAIT_INTENT → STOP 후 execution_id 잔류, `STOP_PENDING`, RESUME=false; Robot `STOP_IDLE` 기록 | 계산/대화 대기의 MOCK 유휴 확인과 REAL 실제 정지 증거를 구분. STOP_IDLE을 실제 정지 성공으로 승격하지 않음. 승인 Design/B Current 보존, 닫힌 응답으로 진행 금지 |
| B ERROR 뒤 재검사 | 처리 실패 후 HOLD; 명시적 재검사에서 `NO_REINSPECTION_PENDING`, 새 검사 없음 | ERROR 의미를 유지하며 원인 해소 후 새 check_id로 동일 Plan/Step 재검사. 집기/접촉 재실행·완료 Step 증가 금지 |
| 재검사 슬롯 소비 | 첫 실행 후 다음 슬롯 2; 수동 재검사 뒤 3으로 증가 | 동일 실행의 검사 반복/중복 이벤트에 슬롯 소비·모의 장면 효과 한 번만 적용. 종류/색상별 순환 유지 |
| 동일 검사 ID 내용 충돌 | 첫 정상 결과 뒤 다른 Current/MISMATCH 결과는 `CLOSED_OR_STALE_CHECK`로 거절되지만 진행 상태 유지 | 동일 중복·내용 충돌·다른 옛 검사 구분. 충돌 시 원결과/진단 보존·보류, 실행 중이면 필요한 STOP 요청. B Current 재계산/revision 재발급 금지 |
| Design 없는 REVISE | `ValueError: design: expected object` | REVISE는 수정 의도 접수. 변경 대기 중 기존 승인 목표/Current/기록 보존. 후보 도착 → Preview → Review → APPROVE 이후 A. 기존 Design 동시 반환 경로 유지 |

이 표의 오른쪽은 요구되는 동작이며 현재 원격의 구현 완료 목록이 아니다. 실제 C 생산자 계약을 먼저 확인하고 존재하지 않는 호출/봉투를 만들지 않는다. KEEP도 불일치 Step 완료를 뜻하지 않으며 최신 B Current로 기존 목표 재계획이 필요하다.

D 수정 검증은 별도 MOCK Robot + 실제 B 검사 함수로 1~3을 재현하고, 확정 계약 Fixture로 4~5 소비부를 독립 확인한다. 정상 5층/회전/사람 전달/KEEP 재계획/STOP·늦은 결과/재검사·중복/슬롯 순환 및 HMI snapshot·JSONL을 확인한다. 저장/웹 코드가 바뀌면 격리 DB 왕복 검사가 필요하다. 이번 문서 작업은 그 수정·회귀 검사나 실제 정지·체결 성공을 대신하지 않는다.

## 5. 공급판 파지 중심 비전: 추가로 확인한 차이

최신 원격에 `perception/supply_vision`의 RGB 중심 후보 코드가 있다. 로봇 장착 카메라의 수직 관측·정지를 전제로 일반 Detection과 색상 외곽 사각형에서 `corners_uv`, `grasp_midpoints_uv`, `center_uv`를 구한다. **YOLO 바운딩 박스 중심을 그대로 파지 중심으로 반환하는 구현이 아니다.** 색상 외곽이 실제 윗면임은 별도 검증해야 한다.

현재 출력은 픽셀 좌표의 로컬 진단 후보이며 실제 Service 서버/클라이언트·D 공급 집기 호출은 미연결이다. D/A/Robot 실행 코드에서 `supply_vision`, `center_uv`, `grasp_midpoints_uv`를 소비하는 연결은 검색으로 확인되지 않았다. 새 모델·ROI·보정도 실제 준비가 필요하다. 미검출은 EMPTY가 아닌 UNKNOWN/HOLD다.

Vision의 빨강 `2x1x1`/`red_2x1`과 공통 Design/A/D의 `1x2x1`/방향 규칙이 다르므로 명시적 매핑 합의가 필요하다. 공급 RGB 결과를 조립판 Current나 조립 완료 근거로 사용하지 않는다. 픽셀 → 로봇 좌표는 촬영 당시 자세·카메라 보정·블록 윗면 높이를 반영해야 하며 보드 표면 보정을 그대로 적용하지 않는다. B는 TCP·파지 높이·로봇 명령을 생성하지 않는다. 공급 패드 하단=블록 밑면+5mm 및 기존 보정 중복 금지 기준을 유지한다.

후속 연결 순서는 현재 Step의 종류/색/슬롯 확정 → D 관측 이동·정지 → B 중심 후보 요청/반환 → 최신성·대상·보정/좌표 검증 → 기존 A 경로 후보 계산·D 실행 조건 확인이다. 이 순서는 연결 권장안이며 새 서비스 타입·제어값을 확정하거나 이번에 구현한 것이 아니다.

## 6. 이번에 수행한 검사와 한계

| 대상 | 결과 | 종료 코드 / 의미 |
|---|---|---|
| `reproduce_boundaries.py` | 3개 문제 재현: STOP·ERROR 재검사·슬롯 | 0. 알려진 불량 동작을 확인하는 assert가 만족한 것으로 수정 PASS가 아님 |
| `probe_consumer_contracts.py` | 충돌 결과·Design 없는 REVISE 2개 재현 | 0. 소비부 문제 존재 확인 |
| `probe_plans.py` | 8개 조합: 의자 6개 NO_FEASIBLE_ORDER, 적층 2개 COMPLETED | 0. 실제 조립 성공이 아니라 계획 반환 확인 |
| `isaac_sim/scripts/test_completion_priority.py` | 1 passed / 4 failed / 0 skipped / 0 errors | 1. 구형 0.5 요청의 INVALID_CONTEXT와 후속 None 접근. 테스트 삭제/약화/제외 없음 |
| `perception/supply_vision/tests` | 19 passed / 0 failed / 0 skipped / 0 errors | 0. 합성 입력·기하/실패 경로이며 실제 모델·Camera·파지 시험 아님 |

위 검사 집합을 이전 검토 수치와 합산하지 않는다. 이전 `review-results.json`의 focused/broad/robot/DB 수치는 당시 합성 트리의 기록이며 현재 전체 pytest 결과가 아니다. 이번에는 전체 회귀·음성·DB·Isaac 물리·Camera·Robot·외부 LLM을 실행하지 않았다. MOCK 실행의 ZYZ 변환 경고가 있었으며 새 자세 값을 생성하거나 수정하지 않았다.

main과 integration의 정리 후보 및 실행 전 검토 조건은 [후속 정리 프롬프트](15_CLEANUP_PROMPTS_20261012.md)에 남겼다. 실패 테스트, 원본, 실측값, 모델, 구형 진입점을 이번에 삭제하지 않았다.

## 7. 이번 수정 파일과 문서 확인

- 기존 안내 갱신: `README.md`, `docs/04_ISAAC_SIM.md`, `docs/12_INTEGRATION_SYNC_20261011.md`, `docs/D_MVP_INTEGRATION_20261011.md`, `docs/handover/final_mvp_interface_20261008/README.md`, `docs/STATUS.md`.
- 신규 문서: `docs/14_INTEGRATION_REVIEW_20261012.md`, `docs/15_CLEANUP_PROMPTS_20261012.md`.
- 신규 문서용 기록: `docs/reviews/integration_20261012_review.json`.
- 자료 폴더의 기록 추가: `/home/ms-02/C-2_협동2자료/contract_records/인터페이스 결정 타임라인.md`.

변경한 Markdown 9개의 추가 내용에서 링크 22개·표 5개·코드 블록 4개 및 JSON 기록을 확인했다. 고정 GitHub 링크는 해당 Git 객체의 파일 존재로 확인했으며 HTTP/CI 검사가 아니다. 기존 문서 본문·타임라인 원문은 보존했고 `git diff --check` 종료 0이다. 격리 사본의 추적 파일 1,687개를 원격 Git blob과 대조해 변경 0개를 확인했다. 문서 확인은 코드 수정 검증이나 실제 Camera/Robot 통합 시험이 아니다.
