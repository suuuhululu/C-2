from copy import deepcopy

import pytest

from perception_mvp.backend_adapter import build_observed, build_current_observed, deliver_observed
from perception_mvp.contracts import candidate_to_block, validate_block
from perception_mvp.multiview import merge_views, compare_previous


def brick(color="yellow", layer=1, x=4):
    return {"brick_type": "2x2x1", "color": color, "x": x, "y": 6,
            "layer": layer, "orientation_deg": 0}


def area(layer=1, x=4, width=2):
    return {"x": x, "y": 6, "width": width, "height": 2, "layer": layer}


def test_fifth_layer_observation_and_sixth_layer_rejection():
    from perception_mvp.contracts import region_cells
    validate_block(brick(layer=5))
    assert all(cell[2] == 5 for cell in region_cells([area(layer=5)]))
    with pytest.raises(ValueError):
        validate_block(brick(layer=6))
    with pytest.raises(ValueError):
        region_cells([area(layer=6)])


def view(view_id="V0", blocks=None, regions=None):
    return {"check_id": "check", "observation_seq": 0, "calibration_id": "synthetic",
            "view_id": view_id, "status": "OK", "reason": None,
            "visible_blocks": [brick()] if blocks is None else blocks,
            "verified_regions": [area()] if regions is None else regions}


def test_current_verified_empty_is_not_missing_observation():
    observed, _ = build_current_observed("check", 0, [view(blocks=[])], [],
                                         [area()], scene_stable=True)
    sent = []
    deliver_observed(observed, sent.append)
    assert sent[0]["status"] == "OK" and sent[0]["visible_blocks"] == []
    missing, _ = build_current_observed("check", 0, [], [], [area()], scene_stable=True)
    assert missing["status"] == "UNOBSERVABLE"


def test_current_other_view_can_supply_missing_scope():
    partial = view(regions=[])
    partial.update(status="UNOBSERVABLE", reason="depth_missing")
    observed, _ = build_current_observed("check", 0, [partial, view("D1")],
                                         [], [area()], scene_stable=True)
    assert observed["status"] == "OK" and observed["visible_blocks"] == [brick()]


@pytest.mark.parametrize("scope", [[], [area(layer=2)]])
def test_current_requires_actual_requested_layer_coverage(scope):
    if not scope:
        with pytest.raises(ValueError, match="scope"):
            build_current_observed("check", 0, [view()], [], scope, scene_stable=True)
    else:
        observed, diagnostics = build_current_observed("check", 0, [view()],
            [brick(layer=2)], scope, scene_stable=True)
        assert observed["status"] == "UNOBSERVABLE"
        assert diagnostics["tracking"]["tracked_blocks"]


def test_current_unstable_conflicting_and_wrong_check_not_accepted():
    for views, stable in (([view()], False), ([view(), view("D1", [brick("blue")])], True)):
        observed, _ = build_current_observed("check", 0, views, [], [area()], scene_stable=stable)
        assert observed["status"] == "UNOBSERVABLE"
    with pytest.raises(ValueError, match="identifiers"):
        build_current_observed("new", 0, [view()], [], [area()], scene_stable=True)


def test_duplicate_views_merge_once():
    result = merge_views([view(), view("D1")], scene_stable=True)
    assert result["visible_blocks"] == [brick()]
    assert result["block_evidence"][0]["views"] == ["V0", "D1"]


def test_conflicting_color_never_becomes_verified_empty():
    result = merge_views([view(), view("D1", [brick("blue")])], scene_stable=True)
    assert result["visible_blocks"] == [] and result["verified_regions"] == []
    assert "overlapping_placement_conflict" in result["issues"]


def test_empty_view_cannot_contradict_occupied_view_silently():
    # A verified empty claim in D1 contradicts V0's block at the same layer.
    result = merge_views([view(), view("D1", [])], scene_stable=True)
    assert result["issues"] and not result["verified_regions"]


def test_distinct_layers_do_not_conflict():
    result = merge_views([view(), view("D1", [brick("blue", 2)], [area(2)])], scene_stable=True)
    assert len(result["visible_blocks"]) == 2


@pytest.mark.parametrize("field,value", [("check_id", "other"), ("observation_seq", 1),
                                         ("calibration_id", "other")])
def test_mixed_bundle_rejected(field, value):
    other = view("D1")
    other[field] = value
    with pytest.raises(ValueError, match="mixed"):
        merge_views([view(), other], scene_stable=True)


def test_unstable_bundle_has_no_verified_evidence():
    result = merge_views([view()], scene_stable=False)
    assert result["visible_blocks"] == [] and result["verified_regions"] == []


def test_occluded_lower_layer_kept_without_mutating_input():
    previous = [brick()]
    snapshot = deepcopy(previous)
    observed, diagnostics = build_observed("check", 0,
        [view(blocks=[brick("blue", 2)], regions=[area(2)])], previous,
        brick("blue", 2), scene_stable=True)
    assert observed["status"] == "OK"
    assert diagnostics["tracking"]["tracked_blocks"][0]["placement"] == brick()
    assert previous == snapshot


def test_partial_region_not_removal_evidence():
    result = compare_previous([], [brick()], [area(width=1)])
    assert result["removed_candidates"] == [] and result["tracked_blocks"]


def test_complete_same_layer_region_allows_removal_candidate():
    result = compare_previous([], [brick()], [area()])
    assert result["removed_candidates"] == [brick()]
    assert result["tracked_blocks"] == []


def test_move_identity_remains_unconfirmed():
    result = compare_previous([brick(x=8)], [brick()], [area()])
    assert result["movement_candidates"][0]["identity"] == "UNCONFIRMED"


def test_mismatch_is_ok_and_actual_color_returned():
    observed, _ = build_observed("check", 0, [view(blocks=[brick("blue")])], [],
                                 brick(), scene_stable=True)
    assert observed["status"] == "OK" and observed["visible_blocks"] == [brick("blue")]


def test_verified_empty_and_no_input_are_distinct():
    empty, _ = build_observed("check", 0, [view(blocks=[])], [], brick(), scene_stable=True)
    failed, _ = build_observed("check", 0, [], [], brick(), scene_stable=True)
    assert empty["status"] == "OK" and empty["visible_blocks"] == []
    assert failed["status"] == "UNOBSERVABLE" and failed["reason"]


def test_callback_error_not_hidden():
    observed, _ = build_observed("check", 0, [view()], [], brick(), scene_stable=True)
    def broken(payload):
        raise RuntimeError("Backend failure")
    with pytest.raises(RuntimeError, match="Backend failure"):
        deliver_observed(observed, broken)


@pytest.mark.parametrize("angle,orientation", [(0, 90), (90, 0)])
def test_candidate_axis_conversion(angle, orientation):
    candidate = {"status": "CANDIDATE", "part_class": "blue_2x3",
                 "axis_angle_deg": angle, "grid_center_stud": [5.5, 7.],
                 "measured_layer_index": 1}
    offsets = {"blue_2x3": {str(orientation): [1.5, 1.]}}
    block = candidate_to_block(candidate, offsets)
    assert block == {"brick_type": "2x3x1", "color": "blue", "x": 4, "y": 6,
                     "layer": 2, "orientation_deg": orientation}


def test_missing_anchor_calibration_no_default():
    candidate = {"status": "CANDIDATE", "part_class": "blue_2x3",
                 "axis_angle_deg": 0, "grid_center_stud": [5.5, 7.], "measured_layer_index": 0}
    with pytest.raises(KeyError):
        candidate_to_block(candidate, {})


def test_footprint_outside_board_rejected():
    with pytest.raises(ValueError, match="footprint"):
        validate_block(brick(x=23))
