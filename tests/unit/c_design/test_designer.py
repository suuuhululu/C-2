"""Unit tests for app.c_design.designer (docs/C_DESIGN_CONTRACT.md §3, §3.3, §8.2-§8.10, §9.1).

Helpers build minimal brick/design dicts inline, in the same spirit as test_validator.py.
Where a scenario needs the full Mock chair (Initial Design), it is fetched once via the
`initial_design` fixture and bricks are looked up by `block_id` rather than by hard-coded
grid coordinates, so these tests do not re-derive (and risk mis-deriving) the Mock chair's
exact centered positions by hand.

designer.py is being implemented in parallel (WAVE 2); if it is still incomplete these
tests fail with clear AttributeErrors rather than silently passing.
"""

import copy

import pytest

from app.c_design import designer, validator

CHAIR = "CHAIR"

FORBIDDEN_KEY_SUBSTRINGS = ("plan", "steps", "order", "next", "slot")


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------


def _design_ids(design):
    return [b["block_id"] for b in design["bricks"]]


def _by_id(design_like):
    bricks = design_like["bricks"] if isinstance(design_like, dict) else design_like
    return {b["block_id"]: b for b in bricks if b.get("block_id") is not None}


def _shift(brick, dx=0, dy=0):
    b = dict(brick)
    b["grid_x"] = b["grid_x"] + dx
    b["grid_y"] = b["grid_y"] + dy
    return b


def _layer_cells(design, layer):
    bricks = [b for b in design["bricks"] if b["layer"] == layer]
    if not bricks:
        return set()
    return set().union(*(validator.footprint(b) for b in bricks))


def _assert_layer_mirror_symmetric(design, layer):
    cells = _layer_cells(design, layer)
    assert cells, f"layer {layer} has no bricks"
    xs = [x for x, _ in cells]
    axis = min(xs) + max(xs)
    mirrored = {(axis - x, y) for x, y in cells}
    assert mirrored == cells


def _all_keys(obj):
    keys = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.append(k)
            keys.extend(_all_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            keys.extend(_all_keys(item))
    return keys


def _assert_no_boundary_keys(obj):
    lowered = [k.lower() for k in _all_keys(obj) if isinstance(k, str)]
    for forbidden in FORBIDDEN_KEY_SUBSTRINGS:
        assert not any(forbidden in k for k in lowered), f"found forbidden '{forbidden}' in keys {lowered}"


def _assert_assembled_preserved(result_design, current):
    by_id = _by_id(result_design)
    for cur in current:
        rb = by_id.get(cur["block_id"])
        assert rb is not None, f"current block_id {cur['block_id']!r} missing from result"
        for field in validator.VALUE_FIELDS:
            assert rb[field] == cur[field], f"{cur['block_id']} field {field} not preserved"


def _assert_unassembled_ids_kept(input_design, result_design):
    input_ids = set(_design_ids(input_design))
    input_max = max(int(i[1:]) for i in input_ids)
    result_ids = set(_design_ids(result_design))
    for rid in result_ids:
        if rid not in input_ids:
            assert int(rid[1:]) > input_max, f"new id {rid} does not exceed input max B{input_max:03d}"


def _assert_not_uniform_nonzero_shift(input_design, result_design, current_ids):
    input_by_id = _by_id(input_design)
    result_by_id = _by_id(result_design)
    vectors = set()
    for bid, ib in input_by_id.items():
        if bid in current_ids:
            continue
        rb = result_by_id.get(bid)
        if rb is None:
            continue
        vectors.add((rb["grid_x"] - ib["grid_x"], rb["grid_y"] - ib["grid_y"]))
    if len(vectors) == 1:
        assert next(iter(vectors)) == (0, 0), "all unassembled bricks moved by one identical nonzero vector"


def _tiny_chair_design():
    # Minimal 2-brick CHAIR design, independent of the 15-brick Mock chair: a leg
    # (layer 1) with a seat brick (layer 2) resting on it with full (4-stud) support.
    leg = dict(block_id="B001", color="BLUE", geometry="2x3x1", grid_x=10, grid_y=10, orientation_deg=0, layer=1)
    seat = dict(block_id="B002", color="YELLOW", geometry="2x2x1", grid_x=10, grid_y=10, orientation_deg=0, layer=2)
    return {"design_version": 1, "parent_version": None, "object_type": CHAIR, "source": "MOCK", "bricks": [leg, seat]}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def initial_result():
    return designer.build_initial_design(CHAIR, max_attempts=1, delay=0)


@pytest.fixture(scope="module")
def initial_design(initial_result):
    design = initial_result["design"]
    assert design is not None, "build_initial_design must succeed for CHAIR before other tests can use it"
    return design


# ---------------------------------------------------------------------------
# center_bricks / mock_initial_candidate / mock_revised_candidate / RETRY_DELAY
# ---------------------------------------------------------------------------


def test_retry_delay_constant_exists_and_nonnegative():
    assert isinstance(designer.RETRY_DELAY, (int, float))
    assert designer.RETRY_DELAY >= 0


def test_mock_initial_candidate_shape():
    candidate = designer.mock_initial_candidate(CHAIR)
    assert isinstance(candidate, dict)
    bricks = candidate["bricks"]
    assert isinstance(bricks, list)
    assert len(bricks) == 15
    for b in bricks:
        # Initial candidates have no "existing vs new" distinction (unlike Revised), so
        # the Mock generator may omit block_id entirely rather than set it to None.
        assert b.get("block_id") is None


def test_center_bricks_matches_bbox_formula():
    candidate = designer.mock_initial_candidate(CHAIR)
    centered = designer.center_bricks(candidate["bricks"])
    cells = set().union(*(validator.footprint(b) for b in centered))
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    assert (min(xs), min(ys)) == ((24 - width) // 2, (24 - height) // 2)


def test_mock_revised_candidate_keeps_current_values(initial_design):
    by_id = _by_id(initial_design)
    current = [dict(by_id["B001"])]
    diffs = [{"expected": by_id["B002"], "actual": by_id["B002"]}]
    candidate = designer.mock_revised_candidate(initial_design, current, diffs)
    assert isinstance(candidate, dict)
    out_by_id = {b["block_id"]: b for b in candidate["bricks"] if b.get("block_id") is not None}
    assert out_by_id["B001"]["grid_x"] == by_id["B001"]["grid_x"]
    assert out_by_id["B001"]["grid_y"] == by_id["B001"]["grid_y"]


# ---------------------------------------------------------------------------
# build_initial_design: CHAIR success (Mock)
# ---------------------------------------------------------------------------


def test_initial_design_validates(initial_result):
    assert validator.validate_design(initial_result["design"]) == []


def test_initial_design_bbox_matches_formula(initial_design):
    cells = set().union(*(validator.footprint(b) for b in initial_design["bricks"]))
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    # §3.3: bounding-box min stud follows the formula; never hard-code 9 or 12.
    assert (min(xs), min(ys)) == ((24 - width) // 2, (24 - height) // 2)


def test_initial_design_versioning_and_metadata(initial_design):
    assert initial_design["design_version"] == 1
    assert initial_design["parent_version"] is None
    assert initial_design["object_type"] == CHAIR
    assert initial_design["source"] == "MOCK"


def test_initial_design_block_ids_sequential_and_unique(initial_design):
    ids = _design_ids(initial_design)
    assert len(ids) == len(set(ids))
    assert ids == [f"B{i:03d}" for i in range(1, len(ids) + 1)]


def test_initial_design_keys_exact(initial_design):
    assert set(initial_design.keys()) == set(validator.TOP_FIELDS)
    for b in initial_design["bricks"]:
        assert set(b.keys()) == set(validator.BRICK_FIELDS)


def test_initial_design_mirror_symmetry(initial_design):
    for layer in (1, 2, 3, 4):
        _assert_layer_mirror_symmetric(initial_design, layer)


def test_initial_design_layer_composition(initial_design):
    counts = {}
    for b in initial_design["bricks"]:
        counts[b["layer"]] = counts.get(b["layer"], 0) + 1
    assert counts.get(1) == 4  # four legs
    assert counts.get(2) == 6  # six seat bricks
    assert counts.get(3, 0) + counts.get(4, 0) == 5  # backrest (layers 3-4)


def test_initial_design_no_boundary_keys(initial_result):
    _assert_no_boundary_keys(initial_result)


def test_unsupported_object_rejected():
    result = designer.build_initial_design("TABLE", max_attempts=1, delay=0)
    assert result["design"] is None
    assert "unsupported_object" in {r["rule"] for r in result["reasons"]}


def test_injected_generate_is_used_and_marks_source_llm():
    good = designer.mock_initial_candidate(CHAIR)

    def gen(object_type, reasons):
        assert object_type == CHAIR
        return good

    result = designer.build_initial_design(CHAIR, generate=gen, max_attempts=1, delay=0)
    assert result["design"] is not None
    assert result["design"]["source"] == "LLM"
    assert validator.validate_design(result["design"]) == []


# ---------------------------------------------------------------------------
# build_initial_design: retry loop (§8.10)
# ---------------------------------------------------------------------------


def _invalid_candidate():
    good = designer.mock_initial_candidate(CHAIR)
    bricks = copy.deepcopy(good["bricks"])
    bricks[0]["color"] = "RED"  # invalid_value -> validator rejects the candidate
    return {"bricks": bricks}


def test_initial_retry_loop_recovers_after_invalid_candidates():
    good = designer.mock_initial_candidate(CHAIR)
    seen_reasons = []

    def gen(object_type, reasons):
        seen_reasons.append(reasons)
        if len(seen_reasons) <= 2:
            return _invalid_candidate()
        return good

    result = designer.build_initial_design(CHAIR, generate=gen, max_attempts=5, delay=0)
    assert result["attempts"] == 3
    assert result["design"] is not None
    assert validator.validate_design(result["design"]) == []
    assert result["design"]["design_version"] == 1
    assert seen_reasons[1], "second call should have received the first candidate's rejection reasons"
    assert seen_reasons[2], "third call should have received the second candidate's rejection reasons"


def test_initial_retry_loop_gives_up_at_max_attempts():
    def gen(object_type, reasons):
        return _invalid_candidate()

    result = designer.build_initial_design(CHAIR, generate=gen, max_attempts=2, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 2
    assert result["reasons"]


# ---------------------------------------------------------------------------
# build_revised_design: preservation scenarios built from the Mock Initial Design
# (ids follow Mock chair list order: legs B001-B004, seat B005-B010, backrest/top
# B011-B015; looked up by block_id, not by hard-coded grid coordinates).
# ---------------------------------------------------------------------------


def _run_revised(design, current, differences):
    result = designer.build_revised_design(design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert validator.validate_design(result["design"]) == []
    assert result["design"]["design_version"] == design["design_version"] + 1
    assert result["design"]["parent_version"] == design["design_version"]
    return result["design"]


def test_revised_scenario_a_two_legs_exact_one_leg_shifted(initial_design):
    by_id = _by_id(initial_design)
    b1, b2, b3 = by_id["B001"], by_id["B002"], by_id["B003"]
    shifted_b3 = _shift(b3, dy=1)
    current = [dict(b1), dict(b2), shifted_b3]
    differences = [{"expected": b3, "actual": shifted_b3}]

    result_design = _run_revised(initial_design, current, differences)
    _assert_assembled_preserved(result_design, current)
    _assert_unassembled_ids_kept(initial_design, result_design)
    current_ids = {c["block_id"] for c in current}
    _assert_not_uniform_nonzero_shift(initial_design, result_design, current_ids)


def test_revised_scenario_b_one_leg_exact_one_leg_shifted(initial_design):
    by_id = _by_id(initial_design)
    b1, b2 = by_id["B001"], by_id["B002"]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]

    result_design = _run_revised(initial_design, current, differences)
    _assert_assembled_preserved(result_design, current)
    _assert_unassembled_ids_kept(initial_design, result_design)
    current_ids = {c["block_id"] for c in current}
    _assert_not_uniform_nonzero_shift(initial_design, result_design, current_ids)


def test_revised_scenario_c_all_four_legs_one_shifted(initial_design):
    by_id = _by_id(initial_design)
    b1, b2, b3, b4 = by_id["B001"], by_id["B002"], by_id["B003"], by_id["B004"]
    shifted_b4 = _shift(b4, dy=1)
    current = [dict(b1), dict(b2), dict(b3), shifted_b4]
    differences = [{"expected": b4, "actual": shifted_b4}]

    result_design = _run_revised(initial_design, current, differences)
    _assert_assembled_preserved(result_design, current)
    _assert_unassembled_ids_kept(initial_design, result_design)
    current_ids = {c["block_id"] for c in current}
    _assert_not_uniform_nonzero_shift(initial_design, result_design, current_ids)


def test_revised_result_no_boundary_keys(initial_design):
    by_id = _by_id(initial_design)
    b1, b2 = by_id["B001"], by_id["B002"]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]
    result = designer.build_revised_design(initial_design, current, differences, max_attempts=1, delay=0)
    _assert_no_boundary_keys(result)


# ---------------------------------------------------------------------------
# build_revised_design: new block_id assignment, omitted ids not reused
# ---------------------------------------------------------------------------


def test_new_brick_gets_next_id_and_omitted_id_not_reused():
    design = _tiny_chair_design()
    by_id = _by_id(design)
    leg, seat = by_id["B001"], by_id["B002"]
    current = [dict(leg)]
    differences = [{"expected": seat, "actual": seat}]

    def gen(design_in, current_in, differences_in, reasons):
        new_brick = dict(seat)
        new_brick["block_id"] = None  # B002 is omitted (deleted); this is a "new" brick
        return {"bricks": [dict(leg), new_brick]}

    result = designer.build_revised_design(design, current, differences, generate=gen, max_attempts=1, delay=0)
    revised = result["design"]
    assert revised is not None, result["reasons"]
    assert validator.validate_design(revised) == []

    result_ids = set(_design_ids(revised))
    assert "B002" not in result_ids, "omitted id must not be reused"
    assert "B003" in result_ids, "new brick should receive input-design-max + 1"

    new_out = _by_id(revised)["B003"]
    for field in validator.VALUE_FIELDS:
        assert new_out[field] == seat[field]


# ---------------------------------------------------------------------------
# build_revised_design: input errors and current support violation
# ---------------------------------------------------------------------------


def test_tiny_chair_design_fixture_is_valid():
    # Sanity check on the minimal fixture used by the tests below.
    assert validator.validate_design(_tiny_chair_design()) == []


def test_current_support_violation_blocks_generation_without_attempts():
    design = _tiny_chair_design()
    by_id = _by_id(design)
    leg, seat = by_id["B001"], by_id["B002"]
    moved_seat = _shift(seat, dx=1, dy=2)
    # Sanity-check the crafted scenario really is a 1-stud (sub-support) overlap.
    assert len(validator.footprint(leg) & validator.footprint(moved_seat)) == 1

    current = [dict(leg), moved_seat]
    differences = [{"expected": seat, "actual": moved_seat}]

    result = designer.build_revised_design(design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 0
    assert "current_support_violation" in {r["rule"] for r in result["reasons"]}


def test_current_unknown_block_id_is_input_error_with_zero_attempts():
    design = _tiny_chair_design()
    bogus = dict(block_id="B999", color="BLUE", geometry="2x2x1", grid_x=0, grid_y=0, orientation_deg=0, layer=1)
    current = [bogus]
    differences = [{"expected": bogus, "actual": bogus}]

    result = designer.build_revised_design(design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 0
    assert "unknown_block_id" in {r["rule"] for r in result["reasons"]}


@pytest.mark.parametrize(
    "bad_output",
    ["not json", {"no_bricks": []}, {"bricks": [{"color": "BLUE"}]}],
    ids=["string", "no_bricks_list", "brick_missing_fields"],
)
def test_initial_malformed_generator_output_is_a_rejection_not_an_exception(bad_output):
    # §8.10: malformed LLM output is one rejection reason; §4: builders never raise.
    result = designer.build_initial_design("CHAIR", generate=lambda o, r: bad_output, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 1
    assert result["reasons"]


def test_revised_mock_layout_it_cannot_handle_is_rejected_not_raised(initial_design):
    # B002 moved onto unassembled B004's studs: the Mock drops B004, leaving one leg on that side.
    moved = _shift(_by_id(initial_design)["B002"], dy=2)
    current = [moved]
    differences = [{"expected": _by_id(initial_design)["B002"], "actual": moved}]
    result = designer.build_revised_design(initial_design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 1
    assert result["reasons"]
