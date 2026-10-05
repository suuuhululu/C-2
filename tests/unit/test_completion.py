from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.completion import (
    calculate_expected, evaluate_job_completion, evaluate_observation, freeze_plan_basis,
)
from app.current import open_observation_check


FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / "interfaces/fixtures/day4.json").read_text()
)
A, B, C = FIXTURES["design"]["blocks"]
RA = dict(x=3, y=5, width=2, height=2, layer=1)
RB = dict(x=5, y=5, width=2, height=2, layer=1)
RC = dict(x=3, y=5, width=3, height=2, layer=2)


def current(blocks=(), revision=0):
    return dict(current_revision=revision, blocks=deepcopy(list(blocks)))


def initial_context():
    return freeze_plan_basis(FIXTURES["design"], FIXTURES["initial_plan"], current())


def confirmation(context, state, blocks, regions, seq=12, check_id=None):
    index = len(context["confirmed_steps"])
    step_id = context["plan"]["steps"][index]["step_id"]
    check_id = check_id or f"J01:C{index + 1:02d}"
    active = open_observation_check(check_id, "J01", context["plan"]["plan_id"], step_id)
    observation = {**deepcopy(FIXTURES["observed_match"]), "check_id": check_id,
                   "observation_seq": seq, "visible_blocks": deepcopy(blocks),
                   "verified_regions": deepcopy(regions)}
    return evaluate_observation(context, state, active, observation)


def before_s03():
    first = confirmation(initial_context(), current(), [A], [RA])
    second = confirmation(first["context"], first["current"], [A, B], [RA, RB])
    return second["context"], second["current"]


def active_s03():
    return open_observation_check("J01:C07", "J01", FIXTURES["initial_plan"]["plan_id"], "S03")


def test_expected_contains_only_baseline_completed_and_current_step_effects():
    context = initial_context()
    assert calculate_expected(context) == dict(plan_id=FIXTURES["initial_plan"]["plan_id"],
                                               step_id="S01", blocks=[A])
    first = confirmation(context, current(), [A], [RA])
    assert calculate_expected(first["context"])["blocks"] == [A, B]
    context, _ = before_s03()
    assert calculate_expected(context)["blocks"] == [A, B, C]
    assert context["base_current"] == current()


def test_basis_is_a_deep_copy_and_expected_does_not_mutate_it():
    design, plan, base = deepcopy(FIXTURES["design"]), deepcopy(FIXTURES["initial_plan"]), current()
    context = freeze_plan_basis(design, plan, base)
    design["blocks"].clear()
    plan["steps"].clear()
    base["blocks"].append(C)
    expected = calculate_expected(context)
    expected["blocks"][0]["color"] = "blue"
    assert calculate_expected(context)["blocks"] == [A]
    assert context["base_current"] == current()


def test_normal_three_step_completion_uses_accumulated_current_with_lower_layers_hidden():
    context, state = initial_context(), current()
    for index, (blocks, regions) in enumerate([([A], [RA]), ([A, B], [RA, RB]), ([C], [RC])]):
        result = confirmation(context, state, blocks, regions)
        context, state = result["context"], result["current"]
        assert result["comparison"] == "MATCH" and result["step_confirmed"] is True
        assert result["active_check"] is None
        assert result["job_complete"] is (index == 2)
        assert len(context["confirmed_steps"]) == index + 1
    assert state == current([A, B, C], 3)
    assert context["confirmed_steps"][-1] == dict(step_id="S03", check_id="J01:C03", observation_seq=12)
    assert result["reason"] == "JOB_CONFIRMED" and result["difference"] is None


@pytest.mark.parametrize("changes,new_region", [
    ({"color": "yellow"}, RC),
    ({"x": 9}, dict(x=9, y=5, width=3, height=2, layer=2)),
    ({"y": 9}, dict(x=3, y=9, width=3, height=2, layer=2)),
    ({"layer": 3}, {**RC, "layer": 3}),
    ({"orientation_deg": 0}, dict(x=3, y=5, width=2, height=3, layer=2)),
    ({"brick_type": "2x2x1", "orientation_deg": 0}, dict(x=3, y=5, width=2, height=2, layer=2)),
])
def test_actual_mismatch_is_adopted_but_expected_and_completion_records_stay_fixed(changes, new_region):
    context, state = before_s03()
    actual = {**C, **changes}
    result = confirmation(context, state, [actual], [RC, new_region])
    assert result["current"] == current([A, B, actual], 3)
    assert result["expected"]["blocks"] == [A, B, C]
    assert calculate_expected(result["context"])["blocks"] == [A, B, C]
    assert result["difference"] == dict(missing=[C], unexpected=[actual], unobservable=[])
    assert result["comparison"] == "MISMATCH" and result["requires_intent"] is True
    assert result["active_check"] is None
    assert result["context"]["confirmed_steps"] == context["confirmed_steps"]
    assert result["step_confirmed"] is False and result["job_complete"] is False


def test_confirmed_empty_target_is_mismatch_not_waiting_or_unobservable():
    context, state = before_s03()
    result = evaluate_observation(context, state, active_s03(), FIXTURES["observed_empty"])
    assert result["current"] == state
    assert result["comparison"] == "MISMATCH"
    assert result["difference"] == dict(missing=[C], unexpected=[], unobservable=[])
    assert result["requires_intent"] is True and result["step_confirmed"] is False


def test_unobservable_keeps_current_records_and_open_check_but_consumes_sequence():
    context, state = before_s03()
    result = evaluate_observation(context, state, active_s03(), FIXTURES["observed_unobservable"])
    assert result["comparison"] == "UNOBSERVABLE"
    assert result["current"] == state and result["context"] == context
    assert result["difference"] is None and result["requires_intent"] is False
    late = evaluate_observation(result["context"], result["current"], result["active_check"],
                                FIXTURES["observed_match"])
    assert late["reason"] == "STALE_OBSERVATION"
    assert late["context"] == context and late["current"] == state


def test_partial_unverified_target_does_not_turn_missing_target_into_actual_difference():
    context, state = before_s03()
    result = confirmation(context, state, [], [{**RC, "width": 1}])
    assert result["comparison"] == "UNOBSERVABLE" and result["reason"] == "TARGET_UNVERIFIED"
    assert result["current"] == state and result["context"] == context
    assert result["difference"] is None and result["job_complete"] is False
    observation = {**FIXTURES["observed_match"], "check_id": result["active_check"]["check_id"],
                   "observation_seq": 13}
    resolved = evaluate_observation(context, state, result["active_check"], observation)
    assert resolved["job_complete"] is True


def test_whole_block_values_at_region_boundary_are_positive_confirmation_evidence():
    context, state = before_s03()
    result = evaluate_observation(context, state, active_s03(), FIXTURES["observed_partial"])
    assert result["comparison"] == "MATCH" and result["job_complete"] is True


def test_actual_wrong_color_in_partial_verified_target_is_known_difference_not_occlusion():
    context, state = before_s03()
    actual = {**C, "color": "yellow"}
    result = confirmation(context, state, [actual], [{**RC, "width": 1}])
    assert result["difference"] == dict(missing=[C], unexpected=[actual], unobservable=[])
    assert result["step_confirmed"] is False


def test_current_already_contains_target_but_no_fresh_target_evidence_cannot_confirm_step():
    context, _ = before_s03()
    state = current([A, B, C], 3)
    result = evaluate_observation(context, state, active_s03(), FIXTURES["observed_unobservable"])
    assert result["current"] == state and result["context"] == context
    assert result["step_confirmed"] is False and result["job_complete"] is False


@pytest.mark.parametrize("visible,regions,missing,unexpected", [
    ([C], [RA, RC], [A], []),
    ([{**A, "color": "blue"}, C], [RA, RC], [A], [{**A, "color": "blue"}]),
])
def test_known_previous_change_blocks_current_step_even_if_target_matches(visible, regions, missing, unexpected):
    context, state = before_s03()
    result = confirmation(context, state, visible, regions)
    assert C in result["current"]["blocks"]
    assert result["comparison"] == "MISMATCH" and result["existing_changed"] is True
    assert result["difference"] == dict(missing=missing, unexpected=unexpected, unobservable=[])
    assert result["context"]["confirmed_steps"] == context["confirmed_steps"]
    assert result["step_confirmed"] is False and result["requires_intent"] is True


def test_known_previous_change_is_reported_without_claiming_unverified_target_is_empty():
    context, state = before_s03()
    result = confirmation(context, state, [], [RA])
    assert result["current"] == current([B], 3)
    assert result["comparison"] == "MISMATCH"
    assert result["difference"] == dict(missing=[A], unexpected=[], unobservable=[C])


def test_unplanned_extra_block_blocks_completion():
    context, state = before_s03()
    extra = {**A, "color": "blue", "x": 12}
    result = confirmation(context, state, [C, extra], [RC, {**RA, "x": 12}])
    assert result["comparison"] == "MISMATCH"
    assert result["difference"]["unexpected"] == [extra]
    assert result["step_confirmed"] is False


def test_ambiguous_relocation_keeps_current_and_never_advances_confirmation():
    context, state = before_s03()
    moved = {**A, "x": 8}
    result = confirmation(context, state, [moved], [{**RA, "x": 8}])
    assert result["reason"] == "AMBIGUOUS_RELOCATION"
    assert result["context"] == context and result["current"] == state
    assert result["step_confirmed"] is False and result["requires_intent"] is False


def test_duplicate_completed_result_preserves_job_completion_without_confirming_twice():
    context, state = before_s03()
    first = evaluate_observation(context, state, active_s03(), FIXTURES["observed_match"])
    repeated = evaluate_observation(first["context"], first["current"], first["active_check"],
                                    FIXTURES["observed_match"])
    assert repeated["context"] == first["context"] and repeated["current"] == first["current"]
    assert repeated["step_confirmed"] is False and repeated["job_complete"] is True


@pytest.mark.parametrize("active", [None, {**active_s03(), "plan_id": "old-plan"},
                                    {**active_s03(), "step_id": "S02"}])
def test_closed_old_plan_or_wrong_step_check_cannot_adopt_or_complete(active):
    context, state = before_s03()
    result = evaluate_observation(context, state, active, FIXTURES["observed_mismatch"])
    assert result["disposition"] == "IGNORED"
    assert result["context"] == context and result["current"] == state
    assert result["step_confirmed"] is False and result["requires_intent"] is False


def test_reusing_a_completed_check_for_new_step_is_rejected():
    context, state = before_s03()
    active = {**active_s03(), "check_id": context["confirmed_steps"][0]["check_id"]}
    observation = {**FIXTURES["observed_match"], "check_id": active["check_id"]}
    result = evaluate_observation(context, state, active, observation)
    assert result["reason"] == "CHECK_CONTEXT_MISMATCH" and result["current"] == state


def test_all_steps_confirmed_is_insufficient_if_whole_current_differs_from_design():
    context, state = before_s03()
    final = confirmation(context, state, [C], [RC])
    changed = current([A, {**B, "color": "blue"}, C], 4)
    result = evaluate_job_completion(final["context"], changed)
    assert result["job_complete"] is False and result["reason"] == "FINAL_DESIGN_MISMATCH"
    assert result["difference"]["missing"] == [B]


def test_complete_looking_current_cannot_replace_unconfirmed_required_steps():
    assert evaluate_job_completion(initial_context(), current([A, B, C], 3)) == dict(
        job_complete=False, reason="STEPS_UNCONFIRMED", difference=None)


@pytest.mark.parametrize("blocks,complete", [([A, B, C], True), ([A, B], False),
                                           ([A, B, {**C, "color": "yellow"}], False)])
def test_empty_remaining_plan_still_requires_whole_current_design_agreement(blocks, complete):
    state = current(blocks, 3)
    context = freeze_plan_basis(FIXTURES["design"], FIXTURES["completed_plan"], state)
    assert evaluate_job_completion(context, state)["job_complete"] is complete


def test_last_step_match_with_incomplete_plan_does_not_finish_whole_design():
    plan = {**deepcopy(FIXTURES["initial_plan"]), "steps": [FIXTURES["initial_plan"]["steps"][0]]}
    context = freeze_plan_basis(FIXTURES["design"], plan, current())
    result = confirmation(context, current(), [A], [RA])
    assert result["step_confirmed"] is True and result["job_complete"] is False
    assert result["reason"] == "FINAL_DESIGN_MISMATCH" and result["requires_intent"] is True
    assert result["difference"]["missing"] == [B, C]


def test_replan_freezes_new_basis_but_old_context_remains_fixed():
    context, state = before_s03()
    changed = confirmation(context, state, [{**C, "color": "yellow"}], [RC])
    revised = deepcopy(FIXTURES["design"])
    revised["design_version"] = 2
    revised["blocks"][2]["color"] = "yellow"
    plan = dict(plan_id="new-plan", design_version=2, base_current_revision=3, steps=[])
    new = freeze_plan_basis(revised, plan, changed["current"])
    assert new["base_current"] == changed["current"]
    assert calculate_expected(new)["blocks"] == revised["blocks"]
    assert calculate_expected(context)["blocks"] == FIXTURES["design"]["blocks"]
    assert evaluate_job_completion(new, changed["current"])["job_complete"] is True


def test_remaining_plan_keeps_confirmed_baseline_and_survives_normal_revision_increases():
    context = freeze_plan_basis(FIXTURES["design"], FIXTURES["remaining_plan"], current([A], 1))
    assert calculate_expected(context)["blocks"] == [A, B]
    second = confirmation(context, current([A], 1), [A, B], [RA, RB])
    final = confirmation(second["context"], second["current"], [C], [RC])
    assert final["context"]["base_current"] == current([A], 1)
    assert final["current"] == current([A, B, C], 3)
    assert final["job_complete"] is True
    assert [record["step_id"] for record in final["context"]["confirmed_steps"]] == ["S02", "S03"]


@pytest.mark.parametrize("field,value", [("design_version", 2), ("base_current_revision", 1)])
def test_stale_version_or_revision_cannot_be_frozen_as_adoption_basis(field, value):
    plan = {**FIXTURES["initial_plan"], field: value}
    with pytest.raises(ValueError, match=field):
        freeze_plan_basis(FIXTURES["design"], plan, current())


@pytest.mark.parametrize("records", [
    [dict(step_id="S02", check_id="C1", observation_seq=1)],
    [dict(step_id="S01", check_id="C1", observation_seq=1),
     dict(step_id="S02", check_id="C1", observation_seq=2)],
    [dict(step_id="S01", check_id="C1", observation_seq=True)],
])
def test_invalid_confirmation_history_is_not_accepted_as_progress(records):
    context = {**initial_context(), "confirmed_steps": records}
    with pytest.raises(ValueError):
        calculate_expected(context)


def test_robot_success_is_rejected_and_does_not_modify_expected_or_confirmation():
    context, state = before_s03()
    before = deepcopy((context, state))
    with pytest.raises(ValueError, match="observed"):
        evaluate_observation(context, state, active_s03(), {"execution_id": "R01", "status": "SUCCEEDED"})
    assert (context, state) == before


def test_result_mutation_does_not_change_inputs_or_fixed_expected_basis():
    context, state = before_s03()
    before = deepcopy((context, state, FIXTURES["observed_match"]))
    result = evaluate_observation(context, state, active_s03(), FIXTURES["observed_match"])
    result["context"]["base_current"]["blocks"].append(C)
    result["expected"]["blocks"][0]["color"] = "blue"
    result["current"]["blocks"].clear()
    assert (context, state, FIXTURES["observed_match"]) == before
