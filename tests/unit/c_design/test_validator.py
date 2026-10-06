"""Unit tests for app.c_design.validator (docs/06_CONTRACT_DRAFT.md §1, §2).

Helpers build minimal block/design dicts inline; fixture files are owned by another
worker and are intentionally not read here.
"""

import json

from app.c_design import validator as v


def block(color="yellow", brick_type="2x2x1", x=0, y=0, orientation_deg=0, layer=1):
    return {
        "color": color,
        "brick_type": brick_type,
        "x": x,
        "y": y,
        "orientation_deg": orientation_deg,
        "layer": layer,
    }


def design(blocks, design_version=1):
    return {"design_version": design_version, "blocks": blocks}


def rules(reasons):
    return {r["rule"] for r in reasons}


# ---------------------------------------------------------------------------
# footprint
# ---------------------------------------------------------------------------


def test_footprint_2x2x1():
    assert v.footprint(block(x=0, y=0, brick_type="2x2x1")) == {(0, 0), (0, 1), (1, 0), (1, 1)}


def test_footprint_2x3x1_orientation_0():
    b = block(x=2, y=3, brick_type="2x3x1", orientation_deg=0)
    assert v.footprint(b) == {(2, 3), (2, 4), (2, 5), (3, 3), (3, 4), (3, 5)}


def test_footprint_2x3x1_orientation_90():
    b = block(x=1, y=1, brick_type="2x3x1", orientation_deg=90)
    assert v.footprint(b) == {(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)}


# ---------------------------------------------------------------------------
# validate_design: malformed input
# ---------------------------------------------------------------------------


def test_malformed_not_json_string():
    assert rules(v.validate_design("not json")) == {"malformed_output"}


def test_malformed_json_array_string():
    assert rules(v.validate_design("[1,2]")) == {"malformed_output"}


def test_malformed_non_dict_non_str():
    assert rules(v.validate_design([1, 2])) == {"malformed_output"}


def test_malformed_candidate_also_rejected_in_validate_revised():
    assert rules(v.validate_revised("not json", [])) == {"malformed_output"}


# ---------------------------------------------------------------------------
# validate_design: top-level field rules (§2: exactly design_version, blocks)
# ---------------------------------------------------------------------------


def test_missing_top_level_field():
    d = design([block()])
    del d["design_version"]
    assert "missing_field" in rules(v.validate_design(d))


def test_unknown_top_level_key():
    d = design([block()])
    d["parent_version"] = None
    assert "unknown_key" in rules(v.validate_design(d))


def test_object_type_key_rejected():
    d = design([block()])
    d["object_type"] = "CHAIR"
    assert "unknown_key" in rules(v.validate_design(d))


def test_source_key_rejected():
    d = design([block()])
    d["source"] = "MOCK"
    assert "unknown_key" in rules(v.validate_design(d))


def test_design_version_bool_is_invalid_type():
    d = design([block()], design_version=True)
    assert "invalid_type" in rules(v.validate_design(d))


def test_design_version_below_one_is_invalid_value():
    d = design([block()], design_version=0)
    assert "invalid_value" in rules(v.validate_design(d))


def test_blocks_count_zero_is_brick_count():
    assert "brick_count" in rules(v.validate_design(design([])))


def test_blocks_count_over_twenty_is_brick_count():
    blocks = [block(x=0, y=i) for i in range(21)]
    assert "brick_count" in rules(v.validate_design(design(blocks)))


# ---------------------------------------------------------------------------
# validate_design: block field rules
# ---------------------------------------------------------------------------


def test_block_missing_field():
    b = block()
    del b["layer"]
    assert "missing_field" in rules(v.validate_design(design([b])))


def test_block_unknown_key():
    b = block()
    b["x_mm"] = 42
    assert "unknown_key" in rules(v.validate_design(design([b])))


def test_block_x_float_is_invalid_type():
    b = block(x=1.5)
    assert "invalid_type" in rules(v.validate_design(design([b])))


def test_block_x_bool_is_invalid_type():
    b = block(x=True)
    assert "invalid_type" in rules(v.validate_design(design([b])))


def test_block_layer_float_is_invalid_type():
    b = block(layer=1.0)
    assert "invalid_type" in rules(v.validate_design(design([b])))


def test_block_color_invalid_value():
    b = block(color="GREEN")
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_block_color_uppercase_rejected():
    # §1: color is lowercase yellow/blue; the old uppercase spelling is invalid now.
    b = block(color="YELLOW")
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_block_color_lowercase_accepted():
    b = block(color="blue")
    assert v.validate_design(design([b])) == []


def test_block_brick_type_invalid_value():
    b = block(brick_type="3x3x1")
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_block_orientation_invalid_for_2x2x1():
    b = block(brick_type="2x2x1", orientation_deg=90)
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_block_layer_out_of_range():
    b = block(layer=5)
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_out_of_board():
    b = block(x=23, y=23, brick_type="2x2x1")  # footprint reaches stud 24
    assert "out_of_board" in rules(v.validate_design(design([b])))


def test_overlap_same_layer():
    blocks = [
        block(x=0, y=0, layer=1),
        block(x=1, y=0, layer=1),
    ]
    reasons = v.validate_design(design(blocks))
    assert "overlap" in rules(reasons)
    overlap_reason = next(r for r in reasons if r["rule"] == "overlap")
    assert len(overlap_reason["blocks"]) == 2


def test_connectivity_two_disconnected_clusters():
    blocks = [
        block(x=0, y=0, layer=1),
        block(x=10, y=10, layer=1),
    ]
    reasons = v.validate_design(design(blocks))
    assert rules(reasons) == {"connectivity"}


# ---------------------------------------------------------------------------
# support: Case A-D
# ---------------------------------------------------------------------------


def test_support_case_a_one_below_block_two_studs_pass():
    blocks = [
        block(brick_type="2x3x1", orientation_deg=0, x=3, y=0, layer=1),
        block(brick_type="2x2x1", x=3, y=2, layer=2),
    ]
    assert v.validate_design(design(blocks)) == []


def test_support_case_a_one_below_block_four_studs_pass():
    blocks = [
        block(brick_type="2x3x1", orientation_deg=0, x=0, y=0, layer=1),
        block(brick_type="2x2x1", x=0, y=0, layer=2),
    ]
    assert v.validate_design(design(blocks)) == []


def test_support_case_b_two_below_blocks_one_stud_each_pass():
    blocks = [
        block(brick_type="2x2x1", x=4, y=4, layer=1),
        block(brick_type="2x2x1", x=6, y=6, layer=1),
        block(brick_type="2x2x1", x=5, y=5, layer=2),
    ]
    assert v.validate_design(design(blocks)) == []


def test_support_case_c_three_below_blocks_sum_pass():
    blocks = [
        block(brick_type="2x2x1", x=9, y=9, layer=1),
        block(brick_type="2x2x1", x=9, y=11, layer=1),
        block(brick_type="2x2x1", x=11, y=9, layer=1),
        block(brick_type="2x3x1", orientation_deg=0, x=10, y=10, layer=2),
    ]
    assert v.validate_design(design(blocks)) == []


def test_support_case_d_sum_one_fails():
    blocks = [
        block(brick_type="2x2x1", x=14, y=14, layer=1),
        block(brick_type="2x2x1", x=15, y=15, layer=2),
    ]
    reasons = v.validate_design(design(blocks))
    assert "support" in rules(reasons)
    support_reason = next(r for r in reasons if r["rule"] == "support")
    assert support_reason["blocks"] == [block(brick_type="2x2x1", x=15, y=15, layer=2)]


def test_support_case_d_sum_zero_fails():
    blocks = [
        block(brick_type="2x2x1", x=0, y=0, layer=1),
        block(brick_type="2x2x1", x=20, y=20, layer=2),
    ]
    assert "support" in rules(v.validate_design(design(blocks)))


# ---------------------------------------------------------------------------
# validate_revised: candidate shape (§2)
# ---------------------------------------------------------------------------


def test_validate_revised_unknown_top_level_key_rejected():
    candidate = {"blocks": [block()], "parent_version": 1}
    assert "unknown_key" in rules(v.validate_revised(candidate, []))


def test_validate_revised_missing_blocks_field():
    assert "missing_field" in rules(v.validate_revised({}, []))


def test_validate_revised_valid_candidate_no_current():
    candidate = {"blocks": [block()]}
    assert v.validate_revised(candidate, []) == []


# ---------------------------------------------------------------------------
# validate_revised: value-based preservation (§4)
# ---------------------------------------------------------------------------


def test_validate_revised_moved_assembled_block_rejected():
    assembled = block(x=0, y=0, layer=1)
    candidate = {"blocks": [block(x=1, y=0, layer=1)]}
    reasons = v.validate_revised(candidate, [assembled])
    assert "assembled_not_preserved" in rules(reasons)
    reason = next(r for r in reasons if r["rule"] == "assembled_not_preserved")
    assert reason["blocks"] == [assembled]


def test_validate_revised_missing_assembled_block_rejected():
    assembled = block(x=0, y=0, layer=1)
    candidate = {"blocks": [block(x=5, y=5, layer=1)]}
    reasons = v.validate_revised(candidate, [assembled])
    assert "assembled_not_preserved" in rules(reasons)


def test_validate_revised_value_changed_assembled_block_rejected():
    assembled = block(color="yellow", x=0, y=0, layer=1)
    candidate = {"blocks": [block(color="blue", x=0, y=0, layer=1)]}
    reasons = v.validate_revised(candidate, [assembled])
    assert "assembled_not_preserved" in rules(reasons)


def test_validate_revised_assembled_block_preserved_accepted():
    assembled = block(x=0, y=0, layer=1)
    candidate = {"blocks": [assembled, block(x=10, y=10, layer=1)]}
    reasons = v.validate_revised(candidate, [assembled])
    assert "assembled_not_preserved" not in rules(reasons)


def test_validate_revised_unassembled_block_can_change_values():
    unassembled = block(x=7, y=5, layer=1)
    moved = block(x=8, y=5, layer=1)
    candidate = {"blocks": [block(x=0, y=0, layer=1), moved]}
    reasons = v.validate_revised(candidate, [block(x=0, y=0, layer=1)])
    assert "assembled_not_preserved" not in rules(reasons)


def test_validate_revised_preservation_counts_duplicates():
    # Two distinct current blocks that happen to share values still need two matching
    # entries in the candidate (count included in the multiset containment).
    a = block(x=0, y=0, layer=1)
    far = block(x=10, y=10, layer=1)
    current = [a, far]
    candidate_missing_one = {"blocks": [a]}
    reasons = v.validate_revised(candidate_missing_one, current)
    assert "assembled_not_preserved" in rules(reasons)

    candidate_both = {"blocks": [a, far]}
    reasons = v.validate_revised(candidate_both, current)
    assert "assembled_not_preserved" not in rules(reasons)


# ---------------------------------------------------------------------------
# check_intervention_input
# ---------------------------------------------------------------------------


def test_check_intervention_input_current_missing_field():
    d = design([block()])
    cur = [block()]
    del cur[0]["layer"]
    diffs = [{"expected": block(), "actual": None}]
    assert "missing_field" in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_current_extra_keys_ignored():
    d = design([block()])
    cur = [dict(block(), tcp_pose=[0, 0, 0])]
    diffs = [{"expected": block(), "actual": None}]
    assert "unknown_key" not in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_current_overlap():
    d = design([block(x=0, y=0), block(x=10, y=10)])
    cur = [
        block(x=0, y=0, layer=1),
        block(x=1, y=0, layer=1),
    ]
    diffs = [{"expected": block(), "actual": None}]
    assert "overlap" in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_empty_differences():
    d = design([block()])
    cur = [block()]
    assert "invalid_value" in rules(v.check_intervention_input(d, cur, []))


def test_check_intervention_input_difference_both_null_rejected():
    d = design([block()])
    cur = [block()]
    diffs = [{"expected": None, "actual": None}]
    assert "invalid_value" in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_current_support_violation_not_reported_here():
    # d is a fully valid Design (Case A support); cur reflects a different *actual*
    # placement where the second block only gets 1 support stud from the first.
    d = design(
        [
            block(brick_type="2x3x1", orientation_deg=0, x=0, y=0, layer=1),
            block(brick_type="2x2x1", x=0, y=0, layer=2),
        ]
    )
    assert v.validate_design(d) == []

    cur = [
        block(brick_type="2x2x1", x=14, y=14, layer=1),
        block(brick_type="2x2x1", x=15, y=15, layer=2),
    ]
    diffs = [{"expected": block(), "actual": None}]

    assert "support" not in rules(v.check_intervention_input(d, cur, diffs))
    assert "support" in rules(v.current_support_violations(cur))


def test_connectivity_reason_lists_each_disconnected_component():
    left = [block(x=0, y=0, layer=1), block(x=0, y=0, layer=2)]  # stacked pair, connected
    far = [block(x=10, y=10, layer=1)]
    reasons = [r for r in v.validate_design(design(left + far)) if r["rule"] == "connectivity"]
    assert len(reasons) == 1
    reason = reasons[0]
    assert reason["rule"] == "connectivity"
    assert set(reason) == {"rule", "blocks", "message"}
    assert "2 disconnected components" in reason["message"]
    assert "sizes 2, 1" in reason["message"]
    components = json.loads(reason["message"].split("components: ", 1)[1])
    assert components == [[{k: b[k] for k in v.BLOCK_FIELDS} for b in left], [{k: far[0][k] for k in v.BLOCK_FIELDS}]]
    # blocks keeps every block, ordered by component (largest first)
    assert reason["blocks"] == left + far


def test_connected_design_has_no_connectivity_reason():
    blocks = [block(x=0, y=0, layer=1), block(x=0, y=0, layer=2)]
    assert "connectivity" not in rules(v.validate_design(design(blocks)))
