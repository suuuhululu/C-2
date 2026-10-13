# C Robot-only Design Rule Update — A/B/D 인계 메모 (2026-10-13)

C 파트(시율)가 `work/siyul-c-robot-rule`(base `codex/integration-round1 @ ebeeef2`)에서 적용한 변경 중 다른 파트가 알아야 할 것만 적는다. A/B/D production 코드는 바꾸지 않았다. 상세 계약은 [C_DESIGN_CONTRACT.md](C_DESIGN_CONTRACT.md) §6.1·§8.15·§8.16·§9.1, 진행 기록은 [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md) 2026-10-13 행.

## 1. 바뀐 것 (C-only)

| 항목 | 이전(2026-10-06~10-12) | 이후(2026-10-13) |
|---|---|---|
| support hard rule | layer ≥ 2 블록은 바로 아래층과 겹침 합계 2 stud 이상(A/C 공통 Day4 기하 기준) | C가 생성·수정하는 **모든 Candidate**(Initial, Revised, Difference REVISE, Direct Design Change, Review MODIFY, Planning Failure 재설계)에 **고유 stud ≥ min(4, 블록 stud 수)**: 2x2x1 4/4, 2x3x1 ≥4/6, 1x2x1 2/2. 입력 Design·Current 판정도 같은 함수(`validate_design`, `validate_revised`, `current_support_violations`). production 2-stud 예외 없음 |
| 5층·풍부함·expressive | Revised 프롬프트·judge·`+6` 블록 하한이 사실상 강제 | **기본 선호(soft)**. 사용자가 명시한 제한(N층 이하, 낮게, 간단하게, 블록 적게/N개까지, 작게)이 우선하면 하한·richer 재생성·5층 안내를 적용하지 않음. MAX_LAYER 5·MAX_BLOCKS 40은 상한 |
| 우선순위 | 명문화 없음 | Initial: hard rule > 사용자 명시 요구 > 품질 > (제한 없을 때) expressive > facing. Revised: Current 보존 > hard rule > 이번 요구 > 품질/expressive > facing |
| Current 충돌 | 감지 없음 | 요청 상한이 조립된 Current와 충돌하면(예: Current 4층 + "3층 이하") Current를 지우지 않고 **기존 질문 루프로 1회 재선택**(KEEP / REVISE(clamp) / UNCLEAR / CANCEL). Review MODIFY는 clamp + ack 고지 |

## 2. A (세은) — 변경 불필요, 알아둘 것

- `planning_trial/planner.py`의 `MIN_SUPPORT_STUDS = 2`는 그대로다. C 출력이 ≥ min(4, studs)이면 A의 ≥2 검사를 항상 통과한다(C 출력 ⊂ A 수용 집합). 1x2x1 2/2도 통과.
- A의 별개 기준(`assembly_geometry.contacts` weak 임계 4는 아래 블록별, `ROBOT_RELEASE_PRESS`는 footprint 전체 지지)은 이번 규칙이 보장하지 않는다. 2x3x1이 4/6만 지지되면 여전히 release 불가·weak일 수 있다.
- 공유 문서 `docs/06_CONTRACT_DRAFT.md:37`, `docs/09_C_B_BACKEND_HANDOFF.md:28,89`, `docs/00_CURRENT_DECISIONS.md:46`의 "A/C 지지 기준 2 stud 통일" 문장은 **A 검증 기준으로는 여전히 참**이고 C 생성 기준만 강화됐다. 공유 문서에 "C 생성 Candidate는 2026-10-13부터 min(4, studs)(C_DESIGN_CONTRACT §9.1)"을 한 줄 병기하는 것을 제안한다(C 단독 수정 안 함).
- A 소유 historical fixture(`planning_trial/fixtures/planning_failure_9a091aa3.json`, `search_limit_26blocks_20261012.json`)는 2~3 stud 지지 블록을 가진 당시 기록이며 그대로 둔다.

## 3. B (홍동) — 변경 없음

- Observed·Current/revision 계약 불변. B가 확정한 Current는 C에서 `current_support_violations`로만 판정되며(입력 오류 아님), 2~3 stud 블록이 실제로 놓인 Current에서는 REVISE가 §8.11 escalation(재설계 불가)으로 간다 — 아래 D 항목 참고.

## 4. D (수현) — 알아둘 것·결정 요청

1. **이전 규칙으로 만든 Approved/Current의 후속 HRI 동작 변화**: 2-stud 기준으로 승인된 Approved Design은 `run_intervention`/`run_design_change`/`review_design_candidate`(kind="initial"은 후보 자체, kind="revised"는 previous_design) 입력 검사에서 `FAILED / INVALID_INPUT`이 되고, 2~3 stud 블록이 놓인 Current는 REVISE 시 escalation(can_redesign=False)으로 간다. 새 실행 흐름(Initial v1부터 새 규칙)에서는 생기지 않는 상황이며, 과거 Job 재생·fixture 재사용 시에만 해당한다.
2. **D 소유 테스트 2건의 합성 입력 수정**(사용자 결정, commit `01e8ddf`): `tests/integration/test_five_layer_pipeline.py::thirty_blocks`(홀수층 2x3x1 0°, 짝수층 90°로 같은 6×6 덮기)와 `tests/unit/test_mvp_supply_cycle.py::test_design_count_limit_remains_forty_in_c_and_a`(피라미드 11+10+9+8+7 중 41개). D production·assertion·목적은 그대로다.
3. **`design_metadata`에 새 키**(pass-through): `user_constraints`(C가 생성한 Candidate의 metadata에는 항상 존재하고 없으면 null; Review 결과는 입력 metadata를 그대로 넘기고 KEEP·UNCLEAR·FAILED는 metadata가 null; `{max_layer, max_blocks, height, complexity, block_budget, footprint}` 중 명시된 키만), Revised 전용 `constraint_clamp {requested, applied}`. D는 dict/null 검사 후 deepcopy로 넘기므로 변경 불필요(확인 요청).
4. **명시 제약은 요청 단위**(CONTRACT §8.15): Initial의 "3층까지만"은 이후 `run_intervention`/`run_design_change`에 자동으로 이어지지 않는다(Review MODIFY는 metadata로 이어짐). 세션 단위 유지가 필요하면 D가 `inspection_context`(또는 동등한 인자)에 Approved 후보의 `design_metadata.user_constraints`를 넘기는 방식이 후보이며, C public API 추가 없이 받을 수 있는지는 별도 합의.
5. **블록 수 상한이 Current 블록 수와 같게 clamp되는 경우**(예: Current 5개 + "블록 3개까지"): 유효 후보가 Current 자체뿐이라 v+1 = Current가 되거나(연결이 끊긴 Current면 DESIGN_GENERATION_FAILED), ack 문구는 "나머지만 맞춰서"로 나온다. 운영 문구·정책 결정 요청.
6. **C 테스트가 D 소스를 읽는다**: `tests/unit/c_design/test_constraint_conflict.py`가 `app/mvp_workflow.py`의 `receive_c` 허용 hri 집합(변수 `allowed`)을 ast로 읽어 C 결과값과 대조한다. 변수 이름·구조를 바꾸면 C 테스트가 실패하므로 바꿀 때 알려 주기 바란다.
7. 기존 결함(이번 범위 밖, 보고만): Design Change 모드의 escalation 문장이 Intervention용("놓인 블록을 원래대로"), 해석 LLM 실패 시 사용자 요청(style_hint)이 사라짐, 블록 상한 문서 30/40 불일치(`docs/10_FINAL_MVP.md:101`, `docs/11_ROUND1_INTERFACE_AUDIT.md:25` vs 40), Initial의 상한 밖 요청("6층", "50개")은 제한으로 잡지 않음.

## 5. 검증 요약 (2026-10-13, HEAD 기준)

- 오프라인: C unit 1190 / C integration 139 / A planning_trial 458 passed, D 호환 13파일 121 P · 82 S · 22 F · 11 E(실패·오류 33건 node ID가 `ebeeef2` 기준선과 동일 — 기존 `test_real_voice_*`·`test_real_stop_resume` 절대경로 REAL 시험), 루트 전체 40 F · 16 E node ID 56건 기준선 동일(새 실패 0).
- 실제 gpt-6.1-sol 텍스트 smoke 21회(마이크·로봇 없음): FAILED 0, 모든 새 Candidate(27개) validator PASS·support ≥ min(4, studs); "3층까지만" 3/3 ≤3층; Revised 단순화 3/3 ≤3층·블록 감소·Current 보존; 무제한 3/3 4~5층·Revised 36~40블록; Current 충돌 3/3 질문 발화(REVISE clamp 4층 / KEEP / UNCLEAR). 상세는 C 아카이브 `team_history_assets/c_rule_update/WAVE5_SOL_SMOKE.md`(저장소 밖).
- 미검증: 실제 마이크·TTS·HMI·로봇·카메라, D 경유 실제 음성 E2E, 해석 LLM이 `constraints` 키를 채우는 비율.
