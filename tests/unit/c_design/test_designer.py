"""Unit tests for app.c_design.designer (docs/06_CONTRACT_DRAFT.md §1, §2, §4).

Helpers build minimal block/design dicts inline, in the same spirit as test_validator.py.
Where a scenario needs the full Mock chair (Initial Design), it is fetched once via the
`initial_design` fixture and blocks are looked up by value (position/layer), since there
are no block IDs.

designer.py is being implemented in parallel; if it is still incomplete these tests fail
with clear AttributeErrors rather than silently passing.
"""

from collections import Counter

import pytest

from app.c_design import designer, validator

CHAIR = "CHAIR"

FORBIDDEN_KEY_SUBSTRINGS = ("plan", "steps", "order", "next", "slot")


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------


def _blocks_at(design_like, layer):
    blocks = design_like["blocks"] if isinstance(design_like, dict) else design_like
    return [b for b in blocks if b["layer"] == layer]


def _shift(block, dx=0, dy=0):
    b = dict(block)
    b["x"] = b["x"] + dx
    b["y"] = b["y"] + dy
    return b


def _layer_cells(design, layer):
    blocks = _blocks_at(design, layer)
    if not blocks:
        return set()
    return set().union(*(validator.footprint(b) for b in blocks))


def _assert_layer_mirror_symmetric(design, layer):
    cells = _layer_cells(design, layer)
    assert cells, f"layer {layer} has no blocks"
    xs = [x for x, _ in cells]
    axis = min(xs) + max(xs)
    mirrored = {(axis - x, y) for x, y in cells}
    assert mirrored == cells


def _all_keys(obj):
    keys = []
    if isinstance(obj, dict):
        for k, val in obj.items():
            keys.append(k)
            keys.extend(_all_keys(val))
    elif isinstance(obj, list):
        for item in obj:
            keys.extend(_all_keys(item))
    return keys


def _assert_no_boundary_keys(obj):
    lowered = [k.lower() for k in _all_keys(obj) if isinstance(k, str)]
    for forbidden in FORBIDDEN_KEY_SUBSTRINGS:
        assert not any(forbidden in k for k in lowered), f"found forbidden '{forbidden}' in keys {lowered}"


def _assert_assembled_preserved(result_design, current):
    result_blocks = result_design["blocks"]
    for cur in current:
        tup = tuple(cur[key] for key in validator.BLOCK_FIELDS)
        assert any(
            tuple(rb[key] for key in validator.BLOCK_FIELDS) == tup for rb in result_blocks
        ), f"current block {cur!r} missing from result"


def _tiny_chair_design():
    # Minimal 2-block CHAIR design, independent of the 15-block Mock chair: a leg
    # (layer 1) with a seat block (layer 2) resting on it with full (4-stud) support.
    leg = dict(color="blue", brick_type="2x3x1", x=10, y=10, orientation_deg=0, layer=1)
    seat = dict(color="yellow", brick_type="2x2x1", x=10, y=10, orientation_deg=0, layer=2)
    return {"design_version": 1, "blocks": [leg, seat]}


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
# center_blocks / mock_initial_candidate / mock_revised_candidate / RETRY_DELAY
# ---------------------------------------------------------------------------


def test_retry_delay_constant_exists_and_nonnegative():
    assert isinstance(designer.RETRY_DELAY, (int, float))
    assert designer.RETRY_DELAY >= 0


def test_max_attempts_constant_is_ten():
    assert designer.MAX_ATTEMPTS == 10


def test_mock_initial_candidate_shape():
    candidate = designer.mock_initial_candidate(CHAIR)
    assert isinstance(candidate, dict)
    blocks = candidate["blocks"]
    assert isinstance(blocks, list)
    assert len(blocks) == 15
    for b in blocks:
        assert set(b.keys()) == set(validator.BLOCK_FIELDS)


def test_center_blocks_matches_bbox_formula():
    candidate = designer.mock_initial_candidate(CHAIR)
    centered = designer.center_blocks(candidate["blocks"])
    cells = set().union(*(validator.footprint(b) for b in centered))
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    assert (min(xs), min(ys)) == ((24 - width) // 2, (24 - height) // 2)


def test_mock_revised_candidate_keeps_current_values(initial_design):
    leg = _blocks_at(initial_design, 1)[0]
    seat = _blocks_at(initial_design, 2)[0]
    current = [dict(leg)]
    diffs = [{"expected": seat, "actual": seat}]
    candidate = designer.mock_revised_candidate(initial_design, current, diffs)
    assert isinstance(candidate, dict)
    out_blocks = candidate["blocks"]
    match = [b for b in out_blocks if b["x"] == leg["x"] and b["y"] == leg["y"] and b["layer"] == 1]
    assert match, "current leg must be preserved in the mock revised candidate"


# ---------------------------------------------------------------------------
# build_initial_design: CHAIR success (Mock)
# ---------------------------------------------------------------------------


def test_initial_design_validates(initial_result):
    assert validator.validate_design(initial_result["design"]) == []


def test_initial_design_bbox_matches_formula(initial_design):
    cells = set().union(*(validator.footprint(b) for b in initial_design["blocks"]))
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    # §3.3: bounding-box min stud follows the formula; never hard-code 9 or 12.
    assert (min(xs), min(ys)) == ((24 - width) // 2, (24 - height) // 2)


def test_initial_design_version_and_keys_exact(initial_design):
    assert initial_design["design_version"] == 1
    assert set(initial_design.keys()) == set(validator.TOP_FIELDS)
    for b in initial_design["blocks"]:
        assert set(b.keys()) == set(validator.BLOCK_FIELDS)


def test_initial_result_source_is_mock(initial_result):
    assert initial_result["source"] == "MOCK"
    assert "source" not in initial_result["design"]


def test_initial_design_mirror_symmetry(initial_design):
    for layer in (1, 2, 3, 4):
        _assert_layer_mirror_symmetric(initial_design, layer)


def test_initial_design_layer_composition(initial_design):
    counts = {}
    for b in initial_design["blocks"]:
        counts[b["layer"]] = counts.get(b["layer"], 0) + 1
    assert counts.get(1) == 4  # four legs
    assert counts.get(2) == 6  # six seat blocks
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
    assert result["source"] == "LLM"
    assert "source" not in result["design"]
    assert validator.validate_design(result["design"]) == []


# ---------------------------------------------------------------------------
# build_initial_design: retry loop (§8.10) and MAX_ATTEMPTS / should_stop
# ---------------------------------------------------------------------------


def _invalid_candidate():
    good = designer.mock_initial_candidate(CHAIR)
    blocks = [dict(b) for b in good["blocks"]]
    blocks[0]["color"] = "RED"  # invalid_value -> validator rejects the candidate
    return {"blocks": blocks}


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


def test_default_max_attempts_is_ten_and_reached_with_always_invalid_generate():
    def gen(object_type, reasons):
        return _invalid_candidate()

    result = designer.build_initial_design(CHAIR, generate=gen, delay=0)
    assert result["design"] is None
    assert result["attempts"] == designer.MAX_ATTEMPTS == 10


def test_should_stop_true_after_first_rejected_attempt_stops_with_stopped_rule():
    # With an injected generate, should_stop is now checked once BEFORE the first
    # attempt (cheap guard against a costly LLM call), then between attempts as
    # before. should_stop is False on the pre-check so the first attempt runs,
    # then True on the between-attempts check.
    calls = []

    def gen(object_type, reasons):
        return _invalid_candidate()

    def should_stop():
        calls.append(1)
        return len(calls) > 1

    result = designer.build_initial_design(CHAIR, generate=gen, max_attempts=10, delay=0, should_stop=should_stop)
    assert result["design"] is None
    assert result["attempts"] == 1
    assert {r["rule"] for r in result["reasons"]} == {"stopped"}
    assert len(calls) == 2, "should_stop must be checked once before the first attempt and once between attempts"


# ---------------------------------------------------------------------------
# build_revised_design: preservation scenarios built from the Mock Initial Design
# ---------------------------------------------------------------------------


def _run_revised(design, current, differences):
    result = designer.build_revised_design(design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert validator.validate_design(result["design"]) == []
    return result["design"]


def test_revised_scenario_a_two_legs_exact_one_leg_shifted(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2, b3 = legs[0], legs[1], legs[2]
    shifted_b3 = _shift(b3, dy=1)
    current = [dict(b1), dict(b2), shifted_b3]
    differences = [{"expected": b3, "actual": shifted_b3}]

    result_design = _run_revised(initial_design, current, differences)
    assert result_design["design_version"] == initial_design["design_version"] + 1
    _assert_assembled_preserved(result_design, current)


def test_revised_scenario_b_one_leg_exact_one_leg_shifted(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2 = legs[0], legs[1]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]

    result_design = _run_revised(initial_design, current, differences)
    assert result_design["design_version"] == initial_design["design_version"] + 1
    _assert_assembled_preserved(result_design, current)


def test_revised_scenario_c_all_four_legs_one_shifted(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2, b3, b4 = legs
    shifted_b4 = _shift(b4, dy=1)
    current = [dict(b1), dict(b2), dict(b3), shifted_b4]
    differences = [{"expected": b4, "actual": shifted_b4}]

    result_design = _run_revised(initial_design, current, differences)
    assert result_design["design_version"] == initial_design["design_version"] + 1
    _assert_assembled_preserved(result_design, current)


def test_revised_result_no_boundary_keys(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2 = legs[0], legs[1]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]
    result = designer.build_revised_design(initial_design, current, differences, max_attempts=1, delay=0)
    _assert_no_boundary_keys(result)


def test_revised_result_source_is_mock_and_outside_design(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2 = legs[0], legs[1]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]
    result = designer.build_revised_design(initial_design, current, differences, max_attempts=1, delay=0)
    assert result["source"] == "MOCK"
    assert "source" not in result["design"]


# ---------------------------------------------------------------------------
# build_revised_design: version only increases when the layout really changes (§4)
# ---------------------------------------------------------------------------


def test_revised_version_unchanged_when_candidate_equals_input_layout():
    design = _tiny_chair_design()
    leg, seat = design["blocks"]
    current = [dict(leg)]
    differences = [{"expected": seat, "actual": seat}]

    def gen(design_in, current_in, differences_in, reasons):
        return {"blocks": [dict(b) for b in design_in["blocks"]]}

    result = designer.build_revised_design(design, current, differences, generate=gen, max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert result["design"]["design_version"] == 1
    assert result["design"] == design
    assert result["reasons"] == []


def test_revised_version_increments_when_layout_changes():
    design = _tiny_chair_design()
    leg, seat = design["blocks"]
    moved_seat = dict(seat, x=seat["x"] + 1)
    current = [dict(leg)]
    differences = [{"expected": seat, "actual": seat}]

    def gen(design_in, current_in, differences_in, reasons):
        return {"blocks": [dict(leg), moved_seat]}

    result = designer.build_revised_design(design, current, differences, generate=gen, max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert result["design"]["design_version"] == 2


# ---------------------------------------------------------------------------
# build_revised_design: input errors and current support violation
# ---------------------------------------------------------------------------


def test_tiny_chair_design_fixture_is_valid():
    assert validator.validate_design(_tiny_chair_design()) == []


def test_current_support_violation_blocks_generation_without_attempts():
    design = _tiny_chair_design()
    leg, seat = design["blocks"]
    moved_seat = dict(seat, x=seat["x"] + 1, y=seat["y"] + 2)
    # Sanity-check the crafted scenario really is a 1-stud (sub-support) overlap.
    assert len(validator.footprint(leg) & validator.footprint(moved_seat)) == 1

    current = [dict(leg), moved_seat]
    differences = [{"expected": seat, "actual": moved_seat}]

    result = designer.build_revised_design(design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 0
    assert "current_support_violation" in {r["rule"] for r in result["reasons"]}


def test_current_malformed_block_is_input_error_with_zero_attempts():
    design = _tiny_chair_design()
    bogus = dict(color="blue", brick_type="2x2x1", x=0, y=0, orientation_deg=0, layer=1)
    del bogus["layer"]
    current = [bogus]
    differences = [{"expected": design["blocks"][0], "actual": design["blocks"][0]}]

    result = designer.build_revised_design(design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 0
    assert "missing_field" in {r["rule"] for r in result["reasons"]}


@pytest.mark.parametrize(
    "bad_output",
    ["not json", {"no_blocks": []}, {"blocks": [{"color": "blue"}]}],
    ids=["string", "no_blocks_list", "block_missing_fields"],
)
def test_initial_malformed_generator_output_is_a_rejection_not_an_exception(bad_output):
    # §8.10: malformed LLM output is one rejection reason; builders never raise.
    result = designer.build_initial_design("CHAIR", generate=lambda o, r: bad_output, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 1
    assert result["reasons"]


def test_revised_mock_layout_it_cannot_handle_is_rejected_not_raised(initial_design):
    # A leg moved onto an unassembled leg's studs on the other side: the Mock cannot
    # lay out a valid upper structure for this and must reject, not raise.
    legs = _blocks_at(initial_design, 1)
    moved = _shift(legs[1], dy=2)
    current = [moved]
    differences = [{"expected": legs[1], "actual": moved}]
    result = designer.build_revised_design(initial_design, current, differences, max_attempts=1, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 1
    assert result["reasons"]


# ---------------------------------------------------------------------------
# WAVE 5: injected generate — LLM-shaped candidates, rejection-reason passing,
# should_stop before the first attempt, and llm_error short-circuiting.
# ---------------------------------------------------------------------------


def _block_tuple(block):
    return tuple(block[key] for key in validator.BLOCK_FIELDS)


def _multiset(blocks):
    return Counter(_block_tuple(b) for b in blocks)


def test_initial_injected_generate_llm_shaped_candidate_without_design_version():
    good = designer.mock_initial_candidate(CHAIR)  # {"blocks": [...]}, no design_version key
    result = designer.build_initial_design(CHAIR, generate=lambda o, r: dict(good), max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert result["source"] == "LLM"
    assert validator.validate_design(result["design"]) == []
    assert "source" not in result["design"]


def test_initial_injected_generate_llm_shaped_candidate_design_version_field_is_ignored():
    good = designer.mock_initial_candidate(CHAIR)
    # an LLM candidate may echo a design_version; build_initial_design always owns versioning.
    candidate = dict(good, design_version=99)
    result = designer.build_initial_design(CHAIR, generate=lambda o, r: candidate, max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert result["design"]["design_version"] == 1
    assert result["source"] == "LLM"


def test_initial_injected_generate_rejection_reasons_passed_attempts_two_version_one():
    good = designer.mock_initial_candidate(CHAIR)
    seen_reasons = []

    def gen(object_type, reasons):
        seen_reasons.append(reasons)
        if len(seen_reasons) == 1:
            return {"blocks": []}  # rejected: no blocks at all
        return dict(good)

    result = designer.build_initial_design(CHAIR, generate=gen, max_attempts=5, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert result["attempts"] == 2
    assert result["design"]["design_version"] == 1
    assert seen_reasons[0] == []
    assert seen_reasons[1], "second call must receive the first candidate's rejection reasons"


def test_revised_injected_generate_rejection_reasons_passed_attempts_two_version_increments(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2 = legs[0], legs[1]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]
    seen_reasons = []

    def gen(design_in, current_in, differences_in, reasons):
        seen_reasons.append(reasons)
        if len(seen_reasons) == 1:
            return {"blocks": []}  # rejected: drops the preserved current blocks
        return designer.mock_revised_candidate(design_in, current_in, differences_in)

    result = designer.build_revised_design(
        initial_design, current, differences, generate=gen, max_attempts=5, delay=0
    )
    assert result["design"] is not None, result["reasons"]
    assert result["attempts"] == 2
    # the rejected first candidate must not itself have consumed a version bump.
    assert result["design"]["design_version"] == initial_design["design_version"] + 1
    assert seen_reasons[0] == []
    assert seen_reasons[1], "second call must receive the first candidate's rejection reasons"
    _assert_assembled_preserved(result["design"], current)


def test_revised_injected_generate_preserves_current_as_exact_multiset(initial_design):
    legs = _blocks_at(initial_design, 1)
    current = [dict(legs[0]), dict(legs[1])]  # current left unshifted: a no-op intervention
    differences = [{"expected": dict(legs[0]), "actual": dict(legs[0])}]

    def gen(design_in, current_in, differences_in, reasons):
        return {"blocks": [dict(b) for b in design_in["blocks"]]}  # echoes the input design verbatim

    result = designer.build_revised_design(
        initial_design, current, differences, generate=gen, max_attempts=1, delay=0
    )
    assert result["design"] is not None, result["reasons"]
    current_counts = _multiset(current)
    result_counts = _multiset(result["design"]["blocks"])
    for tup, count in current_counts.items():
        assert result_counts[tup] == count, f"current block {tup!r} not preserved with the right multiplicity"


def test_revised_injected_generate_same_layout_keeps_input_design_and_version(initial_design):
    legs = _blocks_at(initial_design, 1)
    current = [dict(legs[0]), dict(legs[1])]  # current left unshifted: a no-op intervention
    differences = [{"expected": dict(legs[0]), "actual": dict(legs[0])}]

    def gen(design_in, current_in, differences_in, reasons):
        return {"blocks": [dict(b) for b in design_in["blocks"]]}  # same layout as the input design

    result = designer.build_revised_design(
        initial_design, current, differences, generate=gen, max_attempts=1, delay=0
    )
    assert result["design"] is not None, result["reasons"]
    assert result["design"] == initial_design
    assert result["design"]["design_version"] == initial_design["design_version"]


def test_initial_should_stop_true_before_first_attempt_with_injected_generate_never_calls_generate():
    calls = []

    def gen(object_type, reasons):
        calls.append(1)
        return designer.mock_initial_candidate(CHAIR)

    result = designer.build_initial_design(
        CHAIR, generate=gen, max_attempts=5, delay=0, should_stop=lambda: True
    )
    assert result["design"] is None
    assert result["attempts"] == 0
    assert {r["rule"] for r in result["reasons"]} == {"stopped"}
    assert calls == [], "generate must never be called when should_stop is already True before the first attempt"


def test_revised_should_stop_true_before_first_attempt_with_injected_generate_never_calls_generate(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2 = legs[0], legs[1]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]
    calls = []

    def gen(design_in, current_in, differences_in, reasons):
        calls.append(1)
        return designer.mock_revised_candidate(design_in, current_in, differences_in)

    result = designer.build_revised_design(
        initial_design, current, differences, generate=gen, max_attempts=5, delay=0, should_stop=lambda: True
    )
    assert result["design"] is None
    assert result["attempts"] == 0
    assert {r["rule"] for r in result["reasons"]} == {"stopped"}
    assert calls == [], "generate must never be called when should_stop is already True before the first attempt"


def test_revised_should_stop_true_after_first_rejected_attempt_with_injected_generate(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2 = legs[0], legs[1]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]
    calls = []

    def gen(design_in, current_in, differences_in, reasons):
        return {"blocks": []}  # always rejected

    def should_stop():
        calls.append(1)
        return len(calls) > 1

    result = designer.build_revised_design(
        initial_design, current, differences, generate=gen, max_attempts=10, delay=0, should_stop=should_stop
    )
    assert result["design"] is None
    assert result["attempts"] == 1
    assert {r["rule"] for r in result["reasons"]} == {"stopped"}


def test_initial_llm_error_stops_without_regeneration_on_first_call():
    calls = []

    def gen(object_type, reasons):
        calls.append(1)
        return {"llm_error": {"kind": "auth", "message": "bad api key"}}

    result = designer.build_initial_design(CHAIR, generate=gen, max_attempts=10, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 0
    assert result["reasons"] == [{"rule": "llm_call_failed", "blocks": [], "message": "auth"}]
    assert len(calls) == 1, "an llm_error candidate must end the loop without a regeneration attempt"


def test_initial_llm_error_after_one_rejected_candidate_has_attempts_one():
    seen = []

    def gen(object_type, reasons):
        seen.append(1)
        if len(seen) == 1:
            return {"blocks": []}  # a normal rejection, consumes one attempt
        return {"llm_error": {"kind": "rate_limit", "message": "HTTP 429"}}

    result = designer.build_initial_design(CHAIR, generate=gen, max_attempts=10, delay=0)
    assert result["design"] is None
    assert result["attempts"] == 1
    assert result["reasons"] == [{"rule": "llm_call_failed", "blocks": [], "message": "rate_limit"}]
    assert len(seen) == 2, "no further regeneration after the llm_error candidate"


def test_initial_llm_error_kind_stopped_becomes_stopped_rule():
    result = designer.build_initial_design(
        CHAIR, generate=lambda o, r: {"llm_error": {"kind": "stopped", "message": "halted"}},
        max_attempts=10, delay=0,
    )
    assert result["design"] is None
    assert result["attempts"] == 0
    assert result["reasons"] == [{"rule": "stopped", "blocks": [], "message": "stopped"}]


def test_revised_llm_error_stops_without_regeneration(initial_design):
    legs = _blocks_at(initial_design, 1)
    b1, b2 = legs[0], legs[1]
    shifted_b2 = _shift(b2, dx=1)
    current = [dict(b1), shifted_b2]
    differences = [{"expected": b2, "actual": shifted_b2}]
    calls = []

    def gen(design_in, current_in, differences_in, reasons):
        calls.append(1)
        return {"llm_error": {"kind": "network", "message": "connection reset"}}

    result = designer.build_revised_design(
        initial_design, current, differences, generate=gen, max_attempts=10, delay=0
    )
    assert result["design"] is None
    assert result["attempts"] == 0
    assert result["reasons"] == [{"rule": "llm_call_failed", "blocks": [], "message": "network"}]
    assert len(calls) == 1
