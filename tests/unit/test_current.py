from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.current import adopt_observation, open_observation_check


FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / "interfaces/fixtures/day4.json").read_text()
)
A, B, C = FIXTURES["design"]["blocks"]
RA = dict(x=3, y=5, width=2, height=2, layer=1)
RB = dict(x=5, y=5, width=2, height=2, layer=1)
RC = dict(x=3, y=5, width=3, height=2, layer=2)


def state(blocks=(), revision=0):
    return dict(current_revision=revision, blocks=deepcopy(list(blocks)))


def check(check_id="J01:C07", step_id="S03"):
    return open_observation_check(check_id, "J01", "plan-fixture-initial", step_id)


def observed(blocks, regions, seq=12):
    return {**deepcopy(FIXTURES["observed_match"]), "observation_seq": seq,
            "visible_blocks": deepcopy(blocks), "verified_regions": deepcopy(regions)}


def test_normal_three_observations_accumulate_current_without_declaring_completion():
    current = state()
    for index, (blocks, regions) in enumerate([([A], [RA]), ([A, B], [RA, RB]), ([C], [RC])]):
        context = check(f"J01:C{index}", f"S0{index + 1}")
        payload = {**observed(blocks, regions, 0), "check_id": context["check_id"]}
        result = adopt_observation(current, context, payload)
        current = result["current"]
        assert current == state([A, B, C][:index + 1], index + 1)
        assert result["disposition"] == "ADOPTED"
        assert result["existing_changed"] is False
        assert result["active_check"]["step_id"] == f"S0{index + 1}"
        assert "complete" not in result and "progress" not in result


def test_actual_wrong_color_is_adopted_without_using_the_target_as_current():
    result = adopt_observation(state([A, B], 2), check(), FIXTURES["observed_mismatch"])
    wrong = {**C, "color": "yellow"}
    assert result["current"] == state([A, B, wrong], 3)
    assert result["existing_changed"] is False
    assert FIXTURES["design"]["blocks"][2] == C


def test_color_change_of_a_confirmed_block_replaces_actual_and_marks_existing_change():
    result = adopt_observation(state([A, B, C], 3), check(), FIXTURES["observed_mismatch"])
    assert result["current"] == state([A, B, {**C, "color": "yellow"}], 4)
    assert result["existing_changed"] is True


@pytest.mark.parametrize("replacement,region", [
    ({**A, "brick_type": "2x3x1"}, dict(x=3, y=5, width=1, height=1, layer=1)),
    ({**C, "orientation_deg": 0}, dict(x=3, y=5, width=1, height=1, layer=2)),
])
def test_direct_type_or_angle_replacement_does_not_require_entire_old_area_empty(replacement, region):
    old = A if replacement["layer"] == 1 else C
    result = adopt_observation(state([old], 1), check(), observed([replacement], [region]))
    assert result["current"] == state([replacement], 2)
    assert result["existing_changed"] is True


def test_empty_verified_target_removes_only_that_layer_and_keeps_hidden_supports():
    result = adopt_observation(state([A, B, C], 3), check(), FIXTURES["observed_empty"])
    assert result["current"] == state([A, B], 4)
    assert result["existing_changed"] is True


@pytest.mark.parametrize("regions", [
    [dict(x=3, y=5, width=1, height=2, layer=1)],
    [dict(x=3, y=5, width=2, height=2, layer=2)],
    [dict(x=10, y=10, width=2, height=2, layer=1)],
    [],
])
def test_missing_list_entry_does_not_delete_without_full_same_layer_verification(regions):
    original = state([A], 9)
    result = adopt_observation(original, check(), observed([], regions))
    assert result["current"] == original
    assert result["existing_changed"] is False
    assert result["disposition"] == ("UNCHANGED" if regions else "HOLD")


def test_union_of_regions_proves_full_footprint_empty():
    regions = [dict(x=3, y=5, width=1, height=2, layer=1),
               dict(x=4, y=5, width=1, height=2, layer=1)]
    result = adopt_observation(state([A], 1), check(), observed([], regions))
    assert result["current"] == state([], 2)


def test_boundary_block_is_returned_whole_even_when_verified_region_is_partial():
    result = adopt_observation(state([A, B], 2), check(), FIXTURES["observed_partial"])
    assert result["current"] == state([A, B, C], 3)


def test_unobservable_preserves_current_and_consumes_latest_sequence():
    original = state([A, B], 2)
    result = adopt_observation(original, check(), FIXTURES["observed_unobservable"])
    assert result["current"] == original
    assert result["disposition"] == "HOLD" and result["reason"] == "UNOBSERVABLE"
    assert result["pending_observation"] == FIXTURES["observed_unobservable"]
    late = adopt_observation(result["current"], result["active_check"], FIXTURES["observed_match"])
    assert late["current"] == original
    assert late["reason"] == "STALE_OBSERVATION"


def test_confirmed_old_empty_and_new_occupied_adopts_relocation_without_physical_id():
    moved = {**A, "x": 8}
    regions = [RA, dict(x=8, y=5, width=2, height=2, layer=1)]
    result = adopt_observation(state([A], 5), check(), observed([moved], regions))
    assert result["current"] == state([moved], 6)
    assert result["existing_changed"] is True


def test_overlapping_relocation_can_use_actual_replacement_evidence_in_verified_overlap():
    moved = {**A, "x": 4}
    region = dict(x=4, y=5, width=2, height=2, layer=1)
    result = adopt_observation(state([A], 5), check(), observed([moved], [region]))
    assert result["current"] == state([moved], 6)
    assert result["existing_changed"] is True


@pytest.mark.parametrize("moved,region", [
    ({**A, "x": 8}, dict(x=8, y=5, width=2, height=2, layer=1)),
    ({**A, "x": 4}, dict(x=5, y=5, width=1, height=2, layer=1)),
])
def test_uncertain_move_or_addition_keeps_current_and_retains_observation(moved, region):
    payload = observed([moved], [region])
    original = state([A], 5)
    result = adopt_observation(original, check(), payload)
    assert result["current"] == original
    assert result["reason"] == "AMBIGUOUS_RELOCATION"
    assert result["disposition"] == "HOLD"
    assert result["pending_observation"] == payload
    assert result["active_check"]["last_observation_seq"] == 12


def test_additional_verification_resolves_pending_relocation_once():
    moved = {**A, "x": 8}
    region = dict(x=8, y=5, width=2, height=2, layer=1)
    held = adopt_observation(state([A], 5), check(), observed([moved], [region]))
    result = adopt_observation(held["current"], held["active_check"],
                               observed([moved], [RA, region], 13))
    assert result["current"] == state([moved], 6)
    assert result["pending_observation"] is None
    duplicate = adopt_observation(result["current"], result["active_check"],
                                  observed([moved], [RA, region], 13))
    assert duplicate["current"] == result["current"]
    assert duplicate["reason"] == "STALE_OBSERVATION"


def test_addition_is_distinguishable_when_previous_same_kind_block_is_also_visible():
    result = adopt_observation(state([A], 1), check(), observed([A, B], [RA, RB]))
    assert result["current"] == state([A, B], 2)
    assert result["existing_changed"] is False


def test_hidden_confirmed_lower_layer_is_kept_even_with_same_kind_and_color_above():
    upper = {**A, "layer": 2}
    result = adopt_observation(state([A], 1), check(), observed([upper], [{**RA, "layer": 2}]))
    assert result["current"] == state([A, upper], 2)


def test_existing_change_is_reported_even_when_current_step_target_is_visible():
    result = adopt_observation(state([A, B], 2), check(), observed([C], [RA, RC]))
    assert result["current"] == state([B, C], 3)
    assert result["existing_changed"] is True


def test_repeat_duplicate_blocks_and_list_order_do_not_increment_revision():
    original = state([A, B, C], 3)
    payload = observed([C, B, A, C], [RA, RB, RC])
    result = adopt_observation(original, check(), payload)
    assert result["current"] == original
    assert result["disposition"] == "UNCHANGED"
    assert result["active_check"]["last_observation_seq"] == 12
    repeat = adopt_observation(result["current"], result["active_check"], {**payload, "observation_seq": 20})
    assert repeat["current"] == original
    assert repeat["disposition"] == "UNCHANGED"


@pytest.mark.parametrize("seq", [0, 11, 12])
def test_duplicate_and_reverse_results_cannot_replace_a_newer_actual_layout(seq):
    first = adopt_observation(state([A, B], 2), check(), FIXTURES["observed_match"])
    payload = {**FIXTURES["observed_mismatch"], "observation_seq": seq}
    result = adopt_observation(first["current"], first["active_check"], payload)
    assert result["current"] == first["current"]
    assert result["active_check"] == first["active_check"]
    assert result["reason"] == "STALE_OBSERVATION"


@pytest.mark.parametrize("context,reason", [(None, "NO_ACTIVE_CHECK"), (check("J01:C08"), "CHECK_MISMATCH")])
def test_closed_or_reopened_check_rejects_previous_check_results(context, reason):
    original = state([A], 1)
    result = adopt_observation(original, context, FIXTURES["observed_match"])
    assert result["current"] == original and result["active_check"] == context
    assert result["disposition"] == "IGNORED" and result["reason"] == reason


def test_new_check_accepts_sequence_zero_for_same_step_and_keeps_bound_context():
    context = open_observation_check("new-check", "other-job", "other-plan", "S03")
    payload = {**FIXTURES["observed_match"], "check_id": "new-check", "observation_seq": 0}
    result = adopt_observation(state(), context, payload)
    assert result["current"] == state([C], 1)
    assert result["active_check"] == {**context, "last_observation_seq": 0}


def test_high_sequence_from_another_check_does_not_consume_active_sequence():
    context = check("J01:C08")
    ignored = adopt_observation(state(), context,
                                {**FIXTURES["observed_match"], "observation_seq": 999})
    payload = {**FIXTURES["observed_match"], "check_id": "J01:C08", "observation_seq": 0}
    result = adopt_observation(ignored["current"], ignored["active_check"], payload)
    assert result["current"] == state([C], 1)


def test_new_unchanged_frame_also_prevents_older_mismatch_from_rewinding_current():
    result = adopt_observation(state([A, B, C], 3), check(),
                               {**FIXTURES["observed_match"], "observation_seq": 20})
    late = adopt_observation(result["current"], result["active_check"], FIXTURES["observed_mismatch"])
    assert late["current"] == state([A, B, C], 3)
    assert late["reason"] == "STALE_OBSERVATION"


def test_robot_delivery_success_is_not_an_observation_or_assembly_effect():
    original, context = state(), check()
    with pytest.raises(ValueError, match="observed"):
        adopt_observation(original, context, {"execution_id": "R01", "status": "SUCCEEDED"})
    assert original == state() and context["last_observation_seq"] is None


@pytest.mark.parametrize("blocks,regions,error", [
    ([{**C, "x": 22}], [RC], "outside board"),
    ([C], [RA], "same-layer verified region"),
    ([C], [], "same-layer verified region"),
    ([C, {**C, "color": "yellow"}], [RC], "conflicting"),
])
def test_inconsistent_observation_is_rejected_without_consuming_sequence(blocks, regions, error):
    original, context = state([A, B], 2), check()
    before = deepcopy((original, context))
    with pytest.raises(ValueError, match=error):
        adopt_observation(original, context, observed(blocks, regions, 99))
    assert (original, context) == before
    result = adopt_observation(original, context, FIXTURES["observed_match"])
    assert result["current"] == state([A, B, C], 3)


@pytest.mark.parametrize("brick,region", [
    ({**A, "x": 22, "y": 22, "layer": 4}, dict(x=22, y=22, width=2, height=2, layer=4)),
    ({**C, "x": 21, "y": 22, "layer": 4}, dict(x=21, y=22, width=3, height=2, layer=4)),
    ({**C, "x": 22, "y": 21, "orientation_deg": 0}, dict(x=22, y=21, width=2, height=3, layer=2)),
])
def test_supported_footprints_at_board_edge_and_layer_four(brick, region):
    result = adopt_observation(state(), check(), observed([brick], [region]))
    assert result["current"] == state([brick], 1)


@pytest.mark.parametrize("invalid", [
    {"current_revision": True, "blocks": []}, {"current_revision": -1, "blocks": []},
    state([A, A]), state([A, {**A, "x": 4}]), state([{**A, "x": 23}]),
])
def test_invalid_current_is_not_treated_as_empty_or_repaired(invalid):
    with pytest.raises(ValueError):
        adopt_observation(invalid, check(), FIXTURES["observed_match"])


@pytest.mark.parametrize("context", [{**check(), "last_observation_seq": True}, {**check(), "job_id": ""}])
def test_invalid_active_context_is_rejected(context):
    with pytest.raises(ValueError, match="active_check"):
        adopt_observation(state(), context, FIXTURES["observed_match"])


def test_malformed_newer_observation_does_not_block_a_valid_older_sequence():
    context = check()
    malformed = {**FIXTURES["observed_match"], "observation_seq": 999, "status": "FAILED"}
    with pytest.raises(ValueError, match="status"):
        adopt_observation(state(), context, malformed)
    result = adopt_observation(state(), context, FIXTURES["observed_match"])
    assert result["current"] == state([C], 1)
    assert context["last_observation_seq"] is None


@pytest.mark.parametrize("fixture", ["observed_match", "observed_unobservable"])
def test_inputs_and_outputs_do_not_share_mutable_data(fixture):
    original, context, payload = state([A, B], 2), check(), deepcopy(FIXTURES[fixture])
    before = deepcopy((original, context, payload))
    result = adopt_observation(original, context, payload)
    result["current"]["blocks"][0]["color"] = "blue"
    result["active_check"]["job_id"] = "mutated"
    if result["pending_observation"] is not None:
        result["pending_observation"]["verified_regions"].append(RA)
    assert (original, context, payload) == before
