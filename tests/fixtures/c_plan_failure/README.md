# A Planning failure fixtures (Wave 1, 2026-10-12, integration de59b08)

Wave 4~5(Planning failure → C 대화 라우팅)용. 모두 실제 A 계약(`planning_trial.assembly_contract.validate_message`)을 통과하는 `WholePlanResult` / `StepReassessmentResult`이며, 새 필드를 정의하지 않았다. `context.request_id`·`candidate_id`는 고정 문자열이다.

| 파일 | message_type | 출처 | 의미 |
|---|---|---|---|
| `whole_no_feasible_order_real_unpatched.json` | WholePlanResult | `handle_whole_plan(whole_input(approved_design, current_prefix, mvp_fake.settings()))` **실제 출력 그대로** | 15블록 fixture Design이 FAKE 설정에서 실제로 `NO_FEASIBLE_ORDER`. `stage_errors[0].block`은 `null` → 현재 A 결과에는 막힌 블록 정보가 없다는 증거 |
| `whole_no_feasible_order_with_block.json` | WholePlanResult | 실제 출력에 `stage_errors[0].block`(4층 등받이 블록)을 채운 변형 | "막힌 블록이 있는" 경우. A가 이 위치에 블록을 넣어 주는지는 A 소유 결정(미확정) |
| `whole_no_feasible_order_no_block.json` | WholePlanResult | 실제 출력과 같은 모양(`block: null`) | 막힌 블록 없이 전체 순서 불가 |
| `whole_search_limit.json` | WholePlanResult | `calculation_status`·`stage_errors` 코드를 `SEARCH_LIMIT`으로 바꾼 변형 | 설계 문제로 단정하면 안 되는 실패(C 재설계 라우팅 금지 검증용) |
| `whole_invalid_context.json` | WholePlanResult | `assembly_context.geometry.pitch_mm = 0`로 만든 **실제 출력** | integration 오류(`INVALID_CONTEXT`), 사용자 설계 질문 금지 검증용 |
| `step_current_mismatch.json` | StepReassessmentResult | `assembly_contract.envelope` + `assembly_wire.error("CURRENT_MISMATCH", …, 좌석 블록)` | B/D 최신 Current 문제, C 재설계 라우팅 금지 검증용 |

패치 방식은 `tests/unit/test_mvp_workflow.py::test_a_no_order_opens_c_but_invalid_input_does_not`가 D 쪽에서 쓰는 방식과 같다.
