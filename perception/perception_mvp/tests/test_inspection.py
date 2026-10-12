"""Synthetic contract/core tests; no Camera/Robot performance claims."""
from copy import deepcopy

import pytest

from perception_mvp.inspection import VisionInspection, build_step_models
from perception_mvp.main import inspect_cycle


def block(x=3, y=5, layer=1, color="yellow"):
    return dict(brick_type="2x2x1", color=color, x=x, y=y,
                layer=layer, orientation_deg=0)


def region(layer=1):
    return dict(x=0, y=0, width=24, height=24, layer=layer)


def materials(blocks, base=None, plan_id="p"):
    base = base or dict(current_revision=0, blocks=[])
    steps = [dict(step_id=f"s{i}", operation="PLACE", before=None, after=b,
                  prerequisites=[], requires_delivery=True) for i, b in enumerate(blocks)]
    return (dict(design_version=1, blocks=base["blocks"] + blocks),
            dict(plan_id=plan_id, design_version=1,
                 base_current_revision=base["current_revision"], steps=steps), base)


def session(blocks=None, base=None):
    inputs = materials(blocks or [block()], base)
    value = VisionInspection(inputs[2])
    value.load_plan(*inputs, geometry_reference="profile-16mm")
    return value


def inspect(value, blocks, *, check="c", step="s0", regions=None, status="OK", issues=()):
    value.start(check, "p", step, geometry_reference="profile-16mm")
    observed = dict(check_id=check, observation_seq=0, status=status, visible_blocks=blocks,
                    verified_regions=[region()] if regions is None else regions,
                    reason=None if status == "OK" else "depth_insufficient")
    return value.finish(observed, plan_id="p", step_id=step,
                        geometry_reference="profile-16mm", issues=issues)


def test_models_follow_mixed_layer_step_order_and_preserve_inputs():
    inputs = materials([block(layer=3), block(10, 10, layer=1)])
    original = deepcopy(inputs)
    _, _, models = build_step_models(*inputs)
    assert models["s0"] == [block(layer=3)]
    assert models["s1"] == inputs[0]["blocks"]
    assert inputs == original


def test_actual_mismatch_updates_current_not_expected_and_same_state_keeps_revision():
    value = session()
    actual = block(15, 15, color="blue")
    first = inspect(value, [actual])
    assert first["comparison"] == "MISMATCH"
    assert first["current"] == dict(current_revision=1, blocks=[actual])
    assert first["expected"] == [block()]
    assert first["difference"]["missing"] == [block()]
    assert first["actual_changes"]["added"] == [actual]
    assert first["actual_changes"]["identity"] == "NOT_INFERRED"
    assert value.final_model == [block()]
    again = inspect(value, [actual], check="c2")
    assert again["current"]["current_revision"] == 1
    again["current"]["blocks"].clear()
    assert value.current["blocks"] == [actual]


def test_target_normal_but_old_structure_changed_is_mismatch():
    old, new = block(), block(8, 8, color="blue")
    base = dict(current_revision=2, blocks=[old])
    value = session([new], base)
    result = inspect(value, [new, block(color="blue")])
    assert result["comparison"] == "MISMATCH"
    assert result["current"]["current_revision"] == 3
    assert old not in result["current"]["blocks"]


def test_confirmed_below_layer_retained_when_occluded():
    old, new = block(), block(layer=2)
    value = session([new], dict(current_revision=1, blocks=[old]))
    result = inspect(value, [new], regions=[region(2)])
    assert result["comparison"] == "MATCH"
    assert result["current"]["blocks"] == [old, new]
    assert result["retained_history"] == [old]
    assert result["observed_blocks"] == [new]


def test_real_empty_region_removes_but_no_evidence_does_not():
    old = block()
    value = session([block(8, 8)], dict(current_revision=1, blocks=[old]))
    unknown = inspect(value, [], regions=[], status="UNOBSERVABLE")
    assert unknown["current"]["blocks"] == [old]
    assert unknown["comparison"] == "UNOBSERVABLE"
    empty = inspect(value, [], check="c2")
    assert empty["current"] == dict(current_revision=2, blocks=[])
    assert empty["comparison"] == "MISMATCH"


def test_confirmed_deviation_and_unknown_both_preserved():
    value = session()
    actual = block(15, 15, color="blue")
    small = dict(x=15, y=15, width=2, height=2, layer=1)
    result = inspect(value, [actual], regions=[small], status="UNOBSERVABLE")
    assert result["comparison"] == "MISMATCH"
    assert result["current"]["blocks"] == [actual]
    assert result["difference"]["unobservable"] == [block()]
    assert result["difference"]["missing"] == []
    assert result["unverified_regions"] and result["reason"] == "depth_insufficient"


def test_unconfirmed_move_identity_keeps_history_and_actual_addition():
    old, actual = block(), block(15, 15)
    value = session([block(8, 8)], dict(current_revision=1, blocks=[old]))
    result = inspect(value, [actual], regions=[dict(x=15, y=15, width=2, height=2, layer=1)])
    assert old in result["retained_history"] and actual in result["observed_blocks"]
    assert result["current"]["blocks"] == [old, actual]


def test_cancelled_late_duplicate_results_do_not_mutate_current():
    value = session()
    value.start("late", "p", "s0", geometry_reference="profile-16mm")
    value.cancel("late")
    observed = dict(check_id="late", observation_seq=0, status="OK",
                    visible_blocks=[block()], verified_regions=[region()], reason=None)
    with pytest.raises(ValueError, match="cancelled"):
        value.finish(observed, plan_id="p", step_id="s0", geometry_reference="profile-16mm")
    assert value.current["current_revision"] == 0
    with pytest.raises(ValueError, match="new nonempty"):
        value.start("late", "p", "s0", geometry_reference="profile-16mm")
    inspect(value, [block()])
    with pytest.raises(ValueError):
        value.finish({**observed, "check_id": "c"}, plan_id="p", step_id="s0", geometry_reference="profile-16mm")
    assert value.current["current_revision"] == 1


def test_replan_requires_explicit_cancel_and_preserves_current():
    value = session()
    value.start("old", "p", "s0", geometry_reference="profile-16mm")
    with pytest.raises(ValueError, match='cancel'):
        value.load_plan(*materials([block()], plan_id="p2"), geometry_reference="profile-16mm")
    value.cancel('old')
    value.load_plan(*materials([block()], plan_id="p2"), geometry_reference="profile-16mm")
    assert not value.is_active("old", "p", "s0")
    assert value.current["current_revision"] == 0
    with pytest.raises(ValueError, match="unavailable"):
        value.start("new", "p", "s0", geometry_reference="profile-16mm")


@pytest.mark.parametrize("failure", ["revision", "design", "geometry", "step"])
def test_invalid_model_or_request_never_falls_back(failure):
    value = session()
    if failure in ("revision", "design"):
        design, plan, base = materials([block()], plan_id="p2")
        if failure == "revision":
            plan["base_current_revision"] = 1
        else:
            design["blocks"] = [block(8, 8)]
        with pytest.raises(ValueError):
            value.load_plan(design, plan, base, geometry_reference="profile-16mm")
    else:
        with pytest.raises(ValueError):
            value.start("new", "p", "missing" if failure == "step" else "s0",
                        geometry_reference="wrong" if failure == "geometry" else "profile-16mm")
    assert value.current == dict(current_revision=0, blocks=[])


def test_view_issues_prevent_false_match():
    result = inspect(session(), [block()], issues=["D3:overlapping_placement_conflict"])
    assert result["comparison"] == "UNOBSERVABLE" and result["issues"]


def test_live_pipeline_entry_uses_b_current_and_d_selected_model(monkeypatch):
    value = session()
    def fake_cycle(gate, capture, manifest, *args, **kwargs):
        assert manifest["target_after"] == block()
        assert manifest["previous_accepted_blocks"] == []
        assert kwargs["bundle_valid"]()
        return dict(check_id="c", observation_seq=0, status="OK", visible_blocks=[block()],
                    verified_regions=[region()], reason=None), dict(issues=[], source="synthetic_test")
    monkeypatch.setattr("perception_mvp.main.observe_cycle", fake_cycle)
    result = inspect_cycle(value, None, None,
        dict(check_id="c", plan_id="p", step_id="s0", geometry_reference="profile-16mm"),
        None, None, None, .5, confirm_view=lambda _: True, bundle_valid=lambda: True)
    assert result["comparison"] == "MATCH" and value.current["current_revision"] == 1


def test_pipeline_cancellation_before_commit_leaves_current(monkeypatch):
    value = session()
    def fake_cycle(*args, **kwargs):
        value.cancel("c")
        return {}, dict(issues=[])
    monkeypatch.setattr("perception_mvp.main.observe_cycle", fake_cycle)
    with pytest.raises(RuntimeError, match="cancelled before"):
        inspect_cycle(value, None, None,
            dict(check_id="c", plan_id="p", step_id="s0", geometry_reference="profile-16mm"),
            None, None, None, .5, confirm_view=lambda _: True, bundle_valid=lambda: True)
    assert value.current["current_revision"] == 0
