import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from planner import (
    build_initial_plan, build_plan, calculate_remaining_blocks, validate_design,
    validate_initial_plan, validate_plan, plan_from_current,
)


HERE = Path(__file__).parent
BLOCK_FIELDS = {"brick_type", "color", "x", "y", "layer", "orientation_deg"}


def brick(x=0, y=0, layer=1, brick_type="2x2x1", color="yellow", angle=0):
    return {
        "brick_type": brick_type, "color": color, "x": x, "y": y,
        "layer": layer, "orientation_deg": angle,
    }


@pytest.fixture
def design():
    return json.loads((HERE / "sample_design.json").read_text(encoding="utf-8"))


def test_contract_order_dependencies_and_input_not_mutated(design):
    original = copy.deepcopy(design)
    plan = build_initial_plan(design)
    assert set(plan) == {"plan_id", "design_version", "base_current_revision", "steps"}
    assert plan["design_version"] == 1
    assert plan["base_current_revision"] == 0
    steps = plan["steps"]
    assert [(s["after"]["x"], s["after"]["y"], s["after"]["layer"]) for s in steps] == [
        (4, 6, 1), (8, 6, 1), (4, 4, 1), (8, 4, 1),
        (4, 6, 2), (7, 6, 2), (4, 4, 2), (7, 4, 2),
        (4, 6, 3), (7, 6, 3), (4, 6, 4), (8, 6, 4),
    ]
    assert steps[4]["prerequisites"] == ["S01", "S02", "S03", "S04"]
    for step in steps:
        assert set(step) == {
            "step_id", "operation", "before", "after", "prerequisites", "requires_delivery"
        }
        assert set(step["after"]) == BLOCK_FIELDS
        assert step["operation"] == "PLACE"
        assert step["before"] is None
        assert step["requires_delivery"] is True
    assert design == original


def test_input_order_does_not_change_steps_but_each_plan_has_unique_id(design):
    first = build_initial_plan(design)
    design["blocks"].reverse()
    second = build_initial_plan(design)
    assert first["steps"] == second["steps"]
    assert first["plan_id"] != second["plan_id"]


def test_internal_ids_are_optional_and_not_used_for_common_comparison(design):
    expected = build_initial_plan(design)["steps"]
    for block in design["blocks"]:
        block["block_id"] = "same_internal_id"
    assert build_initial_plan(design)["steps"] == expected


@pytest.mark.parametrize("field,value", [
    ("color", "red"), ("color", []), ("brick_type", "1x1x1"), ("brick_type", {}),
    ("x", -1), ("x", 24), ("x", True), ("y", 1.0),
    ("layer", 0), ("layer", 5), ("layer", True),
    ("orientation_deg", 45), ("orientation_deg", True),
    ("orientation_deg", 90),
])
def test_invalid_brick_fields(design, field, value):
    design["blocks"][0][field] = value  # first sample block is square
    original = copy.deepcopy(design)
    with pytest.raises(ValueError):
        build_initial_plan(design)
    assert design == original  # do not silently clamp/rotate/recolour invalid input


@pytest.mark.parametrize("field", sorted(BLOCK_FIELDS))
def test_missing_common_field_is_rejected(design, field):
    del design["blocks"][0][field]
    with pytest.raises(ValueError, match="missing fields"):
        build_initial_plan(design)


@pytest.mark.parametrize("angle,x,y", [(0, 22, 21), (90, 21, 22)])
def test_rotated_brick_fits_exact_board_edge(angle, x, y):
    design = {"design_version": 1, "blocks": [brick(x, y, brick_type="2x3x1", angle=angle)]}
    assert len(build_initial_plan(design)["steps"]) == 1
    design["blocks"][0]["x"] += 1
    with pytest.raises(ValueError, match="outside board"):
        build_initial_plan(design)
    design["blocks"][0]["x"] -= 1
    design["blocks"][0]["y"] += 1
    with pytest.raises(ValueError, match="outside board"):
        build_initial_plan(design)


def test_overlap_checks_entire_footprint_and_layer():
    lower = brick(brick_type="2x3x1", angle=90)
    upper = brick(x=2)
    design = {"design_version": 1, "blocks": [lower, upper]}
    with pytest.raises(ValueError, match="overlap"):
        build_initial_plan(design)
    upper["layer"] = 2  # two studs overlap below, different layer is allowed
    assert len(build_initial_plan(design)["steps"]) == 2


@pytest.mark.parametrize("upper,passes", [
    (brick(0, 0, 2), True),  # four stud support
    (brick(1, 0, 2), True),  # one lower brick provides two studs
    (brick(1, 1, 2), False),  # only one stud
    (brick(2, 0, 2), False),  # no support
    (brick(0, 0, 3), False),  # layer 1 cannot replace missing layer 2
])
def test_support_uses_immediately_lower_layer_and_two_stud_threshold(upper, passes):
    design = {"design_version": 1, "blocks": [upper, brick()]}
    if passes:
        assert len(build_initial_plan(design)["steps"]) == 2
    else:
        with pytest.raises(ValueError, match="support"):
            build_initial_plan(design)


def test_support_sums_unique_studs_across_two_lower_bricks():
    # Upper (2,2) touches one stud from (1,1) and one from (3,3).
    design = {"design_version": 1, "blocks": [brick(2, 2, 2), brick(1, 1), brick(3, 3)]}
    assert len(build_initial_plan(design)["steps"]) == 3
    design["blocks"].pop()
    with pytest.raises(ValueError, match="found 1"):
        build_initial_plan(design)


def test_duplicate_lower_blocks_cannot_double_count_support():
    design = {"design_version": 1, "blocks": [brick(), brick(), brick(1, 1, 2)]}
    with pytest.raises(ValueError, match="overlap"):
        build_initial_plan(design)


@pytest.mark.parametrize("bad_design", [
    None, [], {}, {"design_version": True, "blocks": [brick()]},
    {"design_version": 0, "blocks": [brick()]}, {"design_version": 1, "blocks": []},
    {"design_version": 1, "blocks": {}}, {"design_version": 1, "blocks": [None]},
])
def test_malformed_design_is_rejected(bad_design):
    with pytest.raises(ValueError):
        build_initial_plan(bad_design)


def test_old_trial_coordinates_are_not_silently_accepted():
    old = {"design_version": 1, "blocks": [{
        "block_id": "B1", "brick_type": "2x2x1", "color": "yellow",
        "x": 0, "y": 0, "z": 0, "orientation": 0,
    }]}
    with pytest.raises(ValueError, match="missing fields"):
        build_initial_plan(old)


@pytest.mark.parametrize("change,reason", [
    ("duplicate_id", "unique"),
    ("unknown_reference", "earlier Steps"),
    ("future_reference", "earlier Steps"),
    ("missing_prerequisite", "missing lower-layer"),
    ("duplicate_prerequisite", "duplicate prerequisite"),
    ("wrong_version", "design_version"),
    ("wrong_revision", "revision 0"),
    ("unsupported_operation", "only PLACE"),
    ("missing_block", "match all Design"),
    ("wrong_colour", "match all Design"),
])
def test_plan_validator_rejects_invalid_output(design, change, reason):
    plan = build_initial_plan(design)
    if change == "duplicate_id":
        plan["steps"][1]["step_id"] = "S01"
    elif change == "unknown_reference":
        plan["steps"][0]["prerequisites"] = ["unknown"]
    elif change == "future_reference":
        plan["steps"][0]["prerequisites"] = ["S02"]
    elif change == "missing_prerequisite":
        plan["steps"][4]["prerequisites"].pop()
    elif change == "duplicate_prerequisite":
        plan["steps"][4]["prerequisites"].append("S01")
    elif change == "wrong_version":
        plan["design_version"] = 2
    elif change == "wrong_revision":
        plan["base_current_revision"] = 1
    elif change == "unsupported_operation":
        plan["steps"][0]["operation"] = "MOVE"
    elif change == "missing_block":
        plan["steps"].pop()
    elif change == "wrong_colour":
        plan["steps"][0]["after"]["color"] = "blue"
    with pytest.raises(ValueError, match=reason):
        validate_initial_plan(design, plan)


def test_plan_validator_checks_actual_placement_support(design):
    plan = build_initial_plan(design)
    # A future reference would also be invalid; isolate missing support here.
    upper = plan["steps"].pop(8)
    upper["prerequisites"] = []
    plan["steps"].insert(0, upper)
    with pytest.raises(ValueError, match="support"):
        validate_initial_plan(design, plan)


def test_plan_validator_requires_whole_lower_layer_first():
    design = {"design_version": 1, "blocks": [brick(), brick(4, 0), brick(0, 0, 2)]}
    plan = build_initial_plan(design)
    # Support exists, but one separate layer-1 brick is delayed until layer 2.
    lower_late = plan["steps"].pop(1)
    plan["steps"][1]["prerequisites"] = ["S01"]
    plan["steps"].append(lower_late)
    with pytest.raises(ValueError, match="finish each lower layer"):
        validate_initial_plan(design, plan)


def test_revised_and_current_samples_share_common_block_fields():
    current = json.loads((HERE / "sample_current_state.json").read_text(encoding="utf-8"))
    revised = json.loads((HERE / "sample_modified_design.json").read_text(encoding="utf-8"))
    assert set(revised) == {"design_version", "blocks"}
    targets = validate_design(revised)
    assert len(targets) == 12
    assert len(current["blocks"]) == 3
    for block in current["blocks"]:
        assert set(block) == BLOCK_FIELDS
        assert block in targets
    assert set(current) == {"current_revision", "blocks"}
    assert current["current_revision"] == 7  # synthetic Backend revision


def test_cli_saves_contract_plan_and_reports_invalid_json(tmp_path):
    output = tmp_path / "plan.json"
    result = subprocess.run(
        [sys.executable, str(HERE / "planner.py"), str(HERE / "sample_design.json"),
         "--output", str(output)], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text(encoding="utf-8"))
    validate_initial_plan(json.loads((HERE / "sample_design.json").read_text()), plan)
    assert len(plan["steps"]) == 12
    assert "layer=1" in result.stdout
    invalid = tmp_path / "bad.json"
    invalid.write_text("{", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HERE / "planner.py"), str(invalid)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "INVALID_INPUT" in result.stderr


def test_remaining_sample_preserves_three_and_returns_nine_without_mutation():
    current = json.loads((HERE / "sample_current_state.json").read_text(encoding="utf-8"))
    revised = json.loads((HERE / "sample_modified_design.json").read_text(encoding="utf-8"))
    originals = copy.deepcopy((revised, current))
    remaining = calculate_remaining_blocks(revised, current["blocks"])
    assert len(remaining) == 9
    assert all(block not in current["blocks"] for block in remaining)
    assert [(b["x"], b["y"], b["layer"]) for b in remaining] == [
        (8, 4, 1), (4, 6, 2), (7, 6, 2), (4, 4, 2), (7, 4, 2),
        (4, 6, 3), (7, 6, 3), (4, 6, 4), (8, 6, 4),
    ]
    assert (revised, current) == originals
    remaining[0]["color"] = "blue"
    assert (revised, current) == originals


def test_empty_and_fully_matching_current(design):
    assert calculate_remaining_blocks(design, []) == [
        step["after"] for step in build_initial_plan(design)["steps"]
    ]
    assert calculate_remaining_blocks(design, design["blocks"]) == []
    # Empty Remaining does not itself mean Backend has confirmed Job completion.


def test_remaining_ignores_ids_and_current_list_order(design):
    current = copy.deepcopy(design["blocks"])
    for i, value in enumerate(current):
        value["block_id"] = f"camera-internal-{i}"
    current.reverse()
    assert calculate_remaining_blocks(design, current) == []


@pytest.mark.parametrize("changed", [
    brick(x=1), brick(y=1), brick(color="blue"),
    brick(brick_type="2x3x1"), brick(layer=2),
])
def test_unpreserved_actual_block_is_not_silently_deleted(changed):
    target = {"design_version": 2, "blocks": [brick()]}
    original = copy.deepcopy((target, changed))
    with pytest.raises(ValueError, match="not preserved"):
        calculate_remaining_blocks(target, [changed])
    assert (target, changed) == original


def test_remaining_detects_orientation_change():
    target = {"design_version": 2, "blocks": [brick(brick_type="2x3x1")]}
    with pytest.raises(ValueError, match="not preserved"):
        calculate_remaining_blocks(target, [brick(brick_type="2x3x1", angle=90)])


def test_remaining_does_not_collapse_duplicate_current_quantity():
    target = {"design_version": 2, "blocks": [brick()]}
    with pytest.raises(ValueError, match="quantity is not preserved"):
        calculate_remaining_blocks(target, [brick(), brick()])


@pytest.mark.parametrize("current", [None, {}, "unknown", [None], [{"color": "yellow"}]])
def test_malformed_current_block_list_is_rejected(design, current):
    with pytest.raises(ValueError):
        calculate_remaining_blocks(design, current)


def test_remaining_rejects_invalid_revised_target_before_comparison():
    invalid = {"design_version": 2, "blocks": [brick(layer=5)]}
    with pytest.raises(ValueError, match="layer"):
        calculate_remaining_blocks(invalid, [])


def test_replan_sample_has_nine_steps_and_copies_revision():
    current = json.loads((HERE / "sample_current_state.json").read_text(encoding="utf-8"))["blocks"]
    revised = json.loads((HERE / "sample_modified_design.json").read_text(encoding="utf-8"))
    originals = copy.deepcopy((revised, current))
    plan = build_plan(revised, current, 7)  # synthetic revision, not emitted by A
    assert plan["design_version"] == 2
    assert plan["base_current_revision"] == 7
    assert len(plan["steps"]) == 9
    assert plan["steps"][0]["after"] == brick(8, 4)
    assert plan["steps"][1]["prerequisites"] == ["S01"]
    assert all(step["after"] not in current for step in plan["steps"])
    assert all(step["requires_delivery"] for step in plan["steps"])
    assert (revised, current) == originals
    validate_plan(revised, current, 7, plan)
    plan["steps"][0]["after"]["color"] = "blue"
    assert (revised, current) == originals


def test_initial_wrapper_and_empty_current_share_the_same_steps(design):
    assert build_initial_plan(design)["steps"] == build_plan(design, [], 0)["steps"]
    # An emptied Board later in a Job keeps the supplied Backend revision.
    assert build_plan(design, [], 8)["base_current_revision"] == 8


def test_completed_target_returns_empty_steps_without_declaring_job_done(design):
    plan = build_plan(design, design["blocks"], 12)
    assert plan["steps"] == []
    assert plan["base_current_revision"] == 12
    assert set(plan) == {"plan_id", "design_version", "base_current_revision", "steps"}
    validate_plan(design, design["blocks"], 12, plan)


def test_current_support_needs_no_artificial_prerequisite():
    lower, upper = brick(), brick(layer=2, color="blue")
    design = {"design_version": 2, "blocks": [lower, upper]}
    plan = build_plan(design, [dict(lower, block_id="internal")], 5)
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["after"] == upper
    assert plan["steps"][0]["prerequisites"] == []
    validate_plan(design, [lower], 5, plan)


def test_support_combines_current_and_newly_placed_studs():
    existing, pending, upper = brick(1, 1), brick(3, 3), brick(2, 2, 2)
    design = {"design_version": 2, "blocks": [existing, pending, upper]}
    plan = build_plan(design, [existing], 3)
    assert [step["after"] for step in plan["steps"]] == [pending, upper]
    assert plan["steps"][1]["prerequisites"] == ["S01"]
    # Without the pending lower block, Current contributes only one stud.
    plan["steps"].pop(0)
    plan["steps"][0]["prerequisites"] = []
    with pytest.raises(ValueError, match="found 1"):
        validate_plan(design, [existing], 3, plan)


def test_current_with_missing_support_is_not_used_as_valid_start_state():
    design = {"design_version": 2, "blocks": [brick(), brick(layer=2)]}
    with pytest.raises(ValueError, match=r"current_blocks\[0\].*support"):
        build_plan(design, [brick(layer=2)], 3)


def test_existing_upper_block_prevents_vertical_insertion_below():
    lower, pending = brick(), brick(x=2)
    bridge = brick(layer=2, brick_type="2x3x1", angle=90)
    design = {"design_version": 2, "blocks": [lower, pending, bridge]}
    original = copy.deepcopy(design)
    # The bridge has four support studs, but obstructs the pending lower brick.
    with pytest.raises(ValueError, match="insertion from above is blocked"):
        build_plan(design, [lower, bridge], 3)
    assert design == original


def test_current_upper_block_does_not_block_separate_lower_work():
    lower, upper, separate = brick(), brick(layer=2), brick(4, 0)
    design = {"design_version": 2, "blocks": [lower, upper, separate]}
    plan = build_plan(design, [lower, upper], 4)
    assert [step["after"] for step in plan["steps"]] == [separate]


def test_replan_does_not_reissue_current_block():
    lower, upper = brick(), brick(layer=2)
    design = {"design_version": 2, "blocks": [lower, upper]}
    plan = build_plan(design, [lower], 1)
    plan["steps"][0]["after"] = lower
    with pytest.raises(ValueError, match="overlaps an existing block"):
        validate_plan(design, [lower], 1, plan)


def test_replan_missing_remaining_step_fails_final_coverage():
    design = {"design_version": 2, "blocks": [brick(), brick(4, 0)]}
    plan = build_plan(design, [brick()], 1)
    plan["steps"] = []
    with pytest.raises(ValueError, match="match all Design"):
        validate_plan(design, [brick()], 1, plan)


def test_replan_must_match_exact_input_revision(design):
    plan = build_plan(design, [], 7)
    with pytest.raises(ValueError, match="revision 8"):
        validate_plan(design, [], 8, plan)


@pytest.mark.parametrize("revision", [None, -1, True, 1.0, "7"])
def test_invalid_revision_is_not_guessed_or_generated(design, revision):
    with pytest.raises(ValueError, match="current_revision"):
        build_plan(design, [], revision)


def test_replan_rejects_current_that_new_design_did_not_preserve():
    design = {"design_version": 2, "blocks": [brick()]}
    with pytest.raises(ValueError, match="not preserved"):
        build_plan(design, [brick(x=1)], 1)


@pytest.mark.parametrize("name", [
    "initial", "partial", "all_assembled", "needs_correction", "invalid",
])
def test_backend_handoff_examples(name):
    example = json.loads((HERE / "handoff_examples.json").read_text())[name]
    original = copy.deepcopy(example)
    result = plan_from_current(example["design"], example["current"])
    assert set(result) == {"status", "plan", "errors"}
    assert result["status"] == example["expected_status"]
    assert example == original
    assert json.loads(json.dumps(result)) == result
    if result["status"] == "READY":
        plan = result["plan"]
        assert result["errors"] == []
        assert len(plan["steps"]) == example["expected_step_count"]
        assert plan["base_current_revision"] == example["current"]["current_revision"]
        validate_plan(example["design"], example["current"]["blocks"],
                      example["current"]["current_revision"], plan)
    else:
        assert result["plan"] is None
        assert len(result["errors"]) == 1
        assert set(result["errors"][0]) == {"reason", "block"}
        assert result["errors"][0]["reason"]
        source = example["current"] if name == "needs_correction" else example["design"]
        assert result["errors"][0]["block"] == source["blocks"][0]


@pytest.mark.parametrize("current", [
    None, [], {}, {"blocks": []}, {"current_revision": 0},
    {"current_revision": True, "blocks": []}, {"current_revision": -1, "blocks": []},
    {"current_revision": "1", "blocks": []}, {"current_revision": 1.0, "blocks": []},
    {"current_revision": 0, "blocks": None},
])
def test_boundary_rejects_missing_or_malformed_current_without_empty_fallback(design, current):
    result = plan_from_current(design, current)
    assert result["status"] == "INVALID"
    assert result["plan"] is None
    assert result["errors"][0]["block"] is None
    assert "Current" in result["errors"][0]["reason"]


def test_boundary_uses_actual_revision_and_same_initial_replan_calculation(design):
    initial = plan_from_current(design, {"current_revision": 8, "blocks": []})
    assert initial["plan"]["steps"] == build_initial_plan(design)["steps"]
    assert initial["plan"]["base_current_revision"] == 8
    revised = json.loads((HERE / "sample_modified_design.json").read_text())
    current = json.loads((HERE / "sample_current_state.json").read_text())
    result = plan_from_current(revised, current)
    assert result["status"] == "READY"
    assert len(result["plan"]["steps"]) == 9
    assert result["plan"]["base_current_revision"] == current["current_revision"]


def test_boundary_correction_then_latest_observed_current():
    target = {"design_version": 1, "blocks": [brick()]}
    conflict = {"current_revision": 1, "blocks": [brick(x=1)]}
    assert plan_from_current(target, conflict)["status"] == "NEEDS_CORRECTION"
    # D supplies a new adopted Current; A never edits the previous snapshot.
    corrected = {"current_revision": 2, "blocks": [brick()]}
    result = plan_from_current(target, corrected)
    assert result["status"] == "READY"
    assert result["plan"]["steps"] == []
    assert result["plan"]["base_current_revision"] == 2
    assert conflict == {"current_revision": 1, "blocks": [brick(x=1)]}


def test_boundary_blocked_insertion_and_unsupported_current_need_correction():
    lower, pending = brick(), brick(x=2)
    bridge = brick(layer=2, brick_type="2x3x1", angle=90)
    design = {"design_version": 2, "blocks": [lower, pending, bridge]}
    result = plan_from_current(design, {"current_revision": 3, "blocks": [lower, bridge]})
    assert result["status"] == "NEEDS_CORRECTION"
    assert result["plan"] is None
    assert result["errors"][0]["block"] == pending
    assert "insertion" in result["errors"][0]["reason"]
    result = plan_from_current(design, {"current_revision": 4, "blocks": [bridge]})
    assert result["status"] == "NEEDS_CORRECTION"
    assert result["errors"][0]["block"] == bridge
    assert "support" in result["errors"][0]["reason"]


@pytest.mark.parametrize("blocks", [[None], [{"color": "yellow"}], [brick(), brick()]])
def test_boundary_malformed_or_overlapping_current_is_invalid(blocks):
    target = {"design_version": 1, "blocks": [brick()]}
    result = plan_from_current(target, {"current_revision": 1, "blocks": blocks})
    assert result["status"] == "INVALID"
    assert result["plan"] is None
    assert "Current.blocks" in result["errors"][0]["reason"]


def test_boundary_internal_id_is_not_a_required_or_emitted_field():
    lower, upper = brick(), brick(layer=2)
    target = {"design_version": 2, "blocks": [dict(lower, block_id="C01"), upper]}
    current = {"current_revision": 5, "blocks": [dict(lower, block_id="D99")]}
    result = plan_from_current(target, current)
    assert result["status"] == "READY"
    assert result["plan"]["steps"][0]["after"] == upper
    assert result["plan"]["steps"][0]["prerequisites"] == []


def test_boundary_design_error_precedes_current_conflict_and_can_have_no_block():
    result = plan_from_current({"blocks": [brick()]}, {"current_revision": 1, "blocks": [brick(x=1)]})
    assert result["status"] == "INVALID"
    assert result["errors"][0]["block"] is None
    assert "design_version" in result["errors"][0]["reason"]
