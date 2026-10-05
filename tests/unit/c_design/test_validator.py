"""Unit tests for app.c_design.validator (docs/C_DESIGN_CONTRACT.md §9.1).

Helpers build minimal brick/design dicts inline; fixture files are owned by another
worker and are intentionally not read here.
"""

from app.c_design import validator as v


def brick(block_id="B001", color="YELLOW", geometry="2x2x1", grid_x=0, grid_y=0, orientation_deg=0, layer=1):
    return {
        "block_id": block_id,
        "color": color,
        "geometry": geometry,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "orientation_deg": orientation_deg,
        "layer": layer,
    }


def design(bricks, design_version=1, parent_version=None, object_type="CHAIR", source="MOCK"):
    return {
        "design_version": design_version,
        "parent_version": parent_version,
        "object_type": object_type,
        "source": source,
        "bricks": bricks,
    }


def rules(reasons):
    return {r["rule"] for r in reasons}


# ---------------------------------------------------------------------------
# footprint
# ---------------------------------------------------------------------------


def test_footprint_2x2x1():
    assert v.footprint(brick(grid_x=0, grid_y=0, geometry="2x2x1")) == {(0, 0), (0, 1), (1, 0), (1, 1)}


def test_footprint_2x3x1_orientation_0():
    b = brick(grid_x=2, grid_y=3, geometry="2x3x1", orientation_deg=0)
    assert v.footprint(b) == {(2, 3), (2, 4), (2, 5), (3, 3), (3, 4), (3, 5)}


def test_footprint_2x3x1_orientation_90():
    b = brick(grid_x=1, grid_y=1, geometry="2x3x1", orientation_deg=90)
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
    assert rules(v.validate_revised("not json", design([brick()]), [])) == {"malformed_output"}


# ---------------------------------------------------------------------------
# validate_design: top-level field rules
# ---------------------------------------------------------------------------


def test_missing_top_level_field():
    d = design([brick()])
    del d["source"]
    assert "missing_field" in rules(v.validate_design(d))


def test_unknown_top_level_key():
    d = design([brick()])
    d["tcp_pose"] = [0, 0, 0]
    assert "unknown_key" in rules(v.validate_design(d))


def test_design_version_bool_is_invalid_type():
    d = design([brick()], design_version=True)
    assert "invalid_type" in rules(v.validate_design(d))


def test_design_version_below_one_is_invalid_value():
    d = design([brick()], design_version=0)
    assert "invalid_value" in rules(v.validate_design(d))


def test_object_type_invalid_value():
    d = design([brick()], object_type="TABLE")
    assert "invalid_value" in rules(v.validate_design(d))


def test_source_invalid_value():
    d = design([brick()], source="REAL")
    assert "invalid_value" in rules(v.validate_design(d))


def test_bricks_count_zero_is_brick_count():
    assert "brick_count" in rules(v.validate_design(design([])))


def test_bricks_count_over_twenty_is_brick_count():
    bricks = [brick(block_id=f"B{i:03d}", grid_x=0, grid_y=i) for i in range(21)]
    assert "brick_count" in rules(v.validate_design(design(bricks)))


# ---------------------------------------------------------------------------
# validate_design: brick field rules
# ---------------------------------------------------------------------------


def test_brick_missing_field():
    b = brick()
    del b["layer"]
    assert "missing_field" in rules(v.validate_design(design([b])))


def test_brick_unknown_key():
    b = brick()
    b["x_mm"] = 42
    assert "unknown_key" in rules(v.validate_design(design([b])))


def test_brick_grid_x_float_is_invalid_type():
    b = brick(grid_x=1.5)
    assert "invalid_type" in rules(v.validate_design(design([b])))


def test_brick_grid_x_bool_is_invalid_type():
    b = brick(grid_x=True)
    assert "invalid_type" in rules(v.validate_design(design([b])))


def test_brick_layer_float_is_invalid_type():
    b = brick(layer=1.0)
    assert "invalid_type" in rules(v.validate_design(design([b])))


def test_brick_color_invalid_value():
    b = brick(color="GREEN")
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_brick_geometry_invalid_value():
    b = brick(geometry="3x3x1")
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_brick_orientation_invalid_for_2x2x1():
    b = brick(geometry="2x2x1", orientation_deg=90)
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_brick_layer_out_of_range():
    b = brick(layer=5)
    assert "invalid_value" in rules(v.validate_design(design([b])))


def test_brick_block_id_bad_format():
    b = brick(block_id="X1")
    assert "invalid_block_id" in rules(v.validate_design(design([b])))


def test_duplicate_block_id():
    bricks = [brick(block_id="B001", grid_x=0, grid_y=0), brick(block_id="B001", grid_x=10, grid_y=10)]
    assert "duplicate_block_id" in rules(v.validate_design(design(bricks)))


def test_out_of_board():
    b = brick(grid_x=23, grid_y=23, geometry="2x2x1")  # footprint reaches stud 24
    assert "out_of_board" in rules(v.validate_design(design([b])))


def test_overlap_same_layer():
    bricks = [
        brick(block_id="B001", grid_x=0, grid_y=0, layer=1),
        brick(block_id="B002", grid_x=1, grid_y=0, layer=1),
    ]
    reasons = v.validate_design(design(bricks))
    assert "overlap" in rules(reasons)
    overlap_reason = next(r for r in reasons if r["rule"] == "overlap")
    assert set(overlap_reason["block_ids"]) == {"B001", "B002"}


def test_connectivity_two_disconnected_clusters():
    bricks = [
        brick(block_id="B001", grid_x=0, grid_y=0, layer=1),
        brick(block_id="B002", grid_x=10, grid_y=10, layer=1),
    ]
    reasons = v.validate_design(design(bricks))
    assert rules(reasons) == {"connectivity"}


# ---------------------------------------------------------------------------
# support: Case A-D (§9.1)
# ---------------------------------------------------------------------------


def test_support_case_a_one_below_brick_two_studs_pass():
    bricks = [
        brick(block_id="B001", geometry="2x3x1", orientation_deg=0, grid_x=3, grid_y=0, layer=1),
        brick(block_id="B002", geometry="2x2x1", grid_x=3, grid_y=2, layer=2),
    ]
    assert v.validate_design(design(bricks)) == []


def test_support_case_a_one_below_brick_four_studs_pass():
    bricks = [
        brick(block_id="B001", geometry="2x3x1", orientation_deg=0, grid_x=0, grid_y=0, layer=1),
        brick(block_id="B002", geometry="2x2x1", grid_x=0, grid_y=0, layer=2),
    ]
    assert v.validate_design(design(bricks)) == []


def test_support_case_b_two_below_bricks_one_stud_each_pass():
    bricks = [
        brick(block_id="B001", geometry="2x2x1", grid_x=4, grid_y=4, layer=1),
        brick(block_id="B002", geometry="2x2x1", grid_x=6, grid_y=6, layer=1),
        brick(block_id="B003", geometry="2x2x1", grid_x=5, grid_y=5, layer=2),
    ]
    assert v.validate_design(design(bricks)) == []


def test_support_case_c_three_below_bricks_sum_pass():
    bricks = [
        brick(block_id="B001", geometry="2x2x1", grid_x=9, grid_y=9, layer=1),
        brick(block_id="B002", geometry="2x2x1", grid_x=9, grid_y=11, layer=1),
        brick(block_id="B003", geometry="2x2x1", grid_x=11, grid_y=9, layer=1),
        brick(block_id="B004", geometry="2x3x1", orientation_deg=0, grid_x=10, grid_y=10, layer=2),
    ]
    assert v.validate_design(design(bricks)) == []


def test_support_case_d_sum_one_fails():
    bricks = [
        brick(block_id="B001", geometry="2x2x1", grid_x=14, grid_y=14, layer=1),
        brick(block_id="B002", geometry="2x2x1", grid_x=15, grid_y=15, layer=2),
    ]
    reasons = v.validate_design(design(bricks))
    assert "support" in rules(reasons)
    support_reason = next(r for r in reasons if r["rule"] == "support")
    assert support_reason["block_ids"] == ["B002"]


def test_support_case_d_sum_zero_fails():
    bricks = [
        brick(block_id="B001", geometry="2x2x1", grid_x=0, grid_y=0, layer=1),
        brick(block_id="B002", geometry="2x2x1", grid_x=20, grid_y=20, layer=2),
    ]
    assert "support" in rules(v.validate_design(design(bricks)))


# ---------------------------------------------------------------------------
# validate_revised: preservation (§8.3, §8.4)
# ---------------------------------------------------------------------------


def test_validate_revised_moved_assembled_brick_rejected():
    assembled = brick(block_id="B001", grid_x=0, grid_y=0, layer=1)
    input_design = design([assembled])
    candidate = design([brick(block_id="B001", grid_x=1, grid_y=0, layer=1)])
    reasons = v.validate_revised(candidate, input_design, [assembled])
    assert "assembled_not_preserved" in rules(reasons)


def test_validate_revised_missing_assembled_brick_rejected():
    assembled = brick(block_id="B001", grid_x=0, grid_y=0, layer=1)
    input_design = design([assembled])
    candidate = design([brick(block_id="B002", grid_x=5, grid_y=5, layer=1)])
    candidate["bricks"][0]["block_id"] = None
    reasons = v.validate_revised(candidate, input_design, [assembled])
    assert "assembled_not_preserved" in rules(reasons)


def test_validate_revised_value_changed_assembled_brick_rejected():
    assembled = brick(block_id="B001", color="YELLOW", grid_x=0, grid_y=0, layer=1)
    input_design = design([assembled])
    candidate = design([brick(block_id="B001", color="BLUE", grid_x=0, grid_y=0, layer=1)])
    reasons = v.validate_revised(candidate, input_design, [assembled])
    assert "assembled_not_preserved" in rules(reasons)


def test_validate_revised_unknown_block_id_rejected():
    input_design = design([brick(block_id="B001")])
    candidate = design([brick(block_id="B999")])
    reasons = v.validate_revised(candidate, input_design, [])
    assert "unknown_block_id" in rules(reasons)


def test_validate_revised_duplicate_block_id_rejected():
    input_design = design([brick(block_id="B001"), brick(block_id="B002", grid_x=10, grid_y=10)])
    candidate = design(
        [
            brick(block_id="B002", grid_x=0, grid_y=0),
            brick(block_id="B002", grid_x=10, grid_y=10),
        ]
    )
    reasons = v.validate_revised(candidate, input_design, [])
    assert "duplicate_block_id" in rules(reasons)


def test_validate_revised_null_new_brick_accepted():
    assembled = brick(block_id="B001", grid_x=0, grid_y=0, layer=1)
    input_design = design([assembled])
    new_brick = brick(grid_x=10, grid_y=10, layer=1)
    new_brick["block_id"] = None
    candidate = design([assembled, new_brick])
    reasons = v.validate_revised(candidate, input_design, [assembled])
    assert "unknown_block_id" not in rules(reasons)
    assert "invalid_block_id" not in rules(reasons)
    assert "duplicate_block_id" not in rules(reasons)
    assert "assembled_not_preserved" not in rules(reasons)


def test_validate_revised_unassembled_brick_can_change_values():
    unassembled = brick(block_id="B002", grid_x=7, grid_y=5, layer=1)
    input_design = design([brick(block_id="B001", grid_x=0, grid_y=0, layer=1), unassembled])
    moved = brick(block_id="B002", grid_x=8, grid_y=5, layer=1)
    candidate = design([brick(block_id="B001", grid_x=0, grid_y=0, layer=1), moved])
    reasons = v.validate_revised(candidate, input_design, [brick(block_id="B001", grid_x=0, grid_y=0, layer=1)])
    assert "assembled_not_preserved" not in rules(reasons)
    assert "unknown_block_id" not in rules(reasons)


# ---------------------------------------------------------------------------
# check_intervention_input
# ---------------------------------------------------------------------------


def test_check_intervention_input_current_missing_block_id():
    d = design([brick(block_id="B001")])
    cur = [brick(block_id="B001")]
    del cur[0]["block_id"]
    diffs = [{"expected": brick(block_id="B001"), "actual": None}]
    assert "missing_field" in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_current_unknown_block_id():
    d = design([brick(block_id="B001")])
    cur = [brick(block_id="B999")]
    diffs = [{"expected": brick(block_id="B001"), "actual": None}]
    assert "unknown_block_id" in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_current_duplicate_block_id():
    d = design([brick(block_id="B001"), brick(block_id="B002", grid_x=10, grid_y=10)])
    cur = [brick(block_id="B001", grid_x=0, grid_y=0), brick(block_id="B001", grid_x=10, grid_y=10)]
    diffs = [{"expected": brick(block_id="B001"), "actual": None}]
    assert "duplicate_block_id" in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_current_overlap():
    d = design([brick(block_id="B001"), brick(block_id="B002", grid_x=10, grid_y=10)])
    cur = [
        brick(block_id="B001", grid_x=0, grid_y=0, layer=1),
        brick(block_id="B002", grid_x=1, grid_y=0, layer=1),
    ]
    diffs = [{"expected": brick(block_id="B001"), "actual": None}]
    assert "overlap" in rules(v.check_intervention_input(d, cur, diffs))


def test_check_intervention_input_empty_differences():
    d = design([brick(block_id="B001")])
    cur = [brick(block_id="B001")]
    assert "invalid_value" in rules(v.check_intervention_input(d, cur, []))


def test_check_intervention_input_current_support_violation_not_reported_here():
    # d is a fully valid Design (Case A support); cur uses the same ids but reflects a
    # different *actual* placement where B002 only gets 1 support stud from B001.
    d = design(
        [
            brick(block_id="B001", geometry="2x3x1", orientation_deg=0, grid_x=0, grid_y=0, layer=1),
            brick(block_id="B002", geometry="2x2x1", grid_x=0, grid_y=0, layer=2),
        ]
    )
    assert v.validate_design(d) == []

    cur = [
        brick(block_id="B001", geometry="2x2x1", grid_x=14, grid_y=14, layer=1),
        brick(block_id="B002", geometry="2x2x1", grid_x=15, grid_y=15, layer=2),
    ]
    diffs = [{"expected": brick(block_id="B001"), "actual": None}]

    assert "support" not in rules(v.check_intervention_input(d, cur, diffs))
    assert "support" in rules(v.current_support_violations(cur))
