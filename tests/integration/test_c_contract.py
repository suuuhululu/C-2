"""A/D-facing contract test for app.c_design.main (docs/C_DESIGN_CONTRACT.md).

Checks the C <-> D/A boundary exactly as an outside caller would see it, not C's
own internals:

  - D -> C (docs/C_DESIGN_CONTRACT.md §5): Current / Difference blocks need only
    the six common fields (brick_type, color, x, y, layer, orientation_deg); no
    block_id anywhere; extra D-only fields on Current blocks (confidence,
    observation_seq, check_id) and on Difference items are read and ignored.
  - C -> D (§4, §6, §10): the result envelope
    {"status", "hri_result", "design", "questions", "error"} for every
    documented outcome - Initial OK, KEEP, REVISE, UNCLEAR, FAILED
    (INVALID_INPUT / UNSUPPORTED_OBJECT / VOICE_IO_FAILED) and CANCELLED
    (STOPPED / USER_CANCEL) - with every error.code restricted to the allowed
    set and error.details always a list.
  - C -> A (§3, §7): the returned Design has exactly {"design_version",
    "blocks"}, each block has exactly the six fields with values inside
    docs/06_CONTRACT_DRAFT.md §1, and no plan/step/robot-ish key leaks into it.

This file imports only app.c_design.main (the two public entry points D/A call,
per §4) and app.c_design.designer (only to zero out its retry sleep for fast
tests). It does not import app.c_design.validator or app.c_design.dialogue, so
the C -> A checks below (footprint/value ranges) are computed independently of
C's own validator - the point is what an outside consumer sees, not a re-check
of C's own logic. No A or D code is imported either: no such Python modules
exist in this repo (A and D live elsewhere); main's public functions are the
only seam under test.

Note on "support" (docs/C_DESIGN_CONTRACT.md §9.1, §11): the rule "a layer >= 2
block needs >= 2 studs of overlap with the layer directly below" is a C
candidate validator rule that Jieun (A) has not yet confirmed - it may still
change. This file does not assert that number anywhere; it only checks Design
*shape* and *value ranges*, which is what A actually consumes (§7).
"""

from collections import Counter

import pytest

from app.c_design import designer, main

CHAIR_TEXT = "오늘은 의자를 만들 거야"

DESIGN_KEYS = {"design_version", "blocks"}
BLOCK_KEYS = {"brick_type", "color", "x", "y", "layer", "orientation_deg"}
ALLOWED_ERROR_CODES = {
    "UNSUPPORTED_OBJECT",
    "INVALID_INPUT",
    "DESIGN_GENERATION_FAILED",
    "STOPPED",
    "USER_CANCEL",
    "VOICE_IO_FAILED",
    "LLM_CALL_FAILED",
}
# Forbidden-key substrings (case-insensitive) that would mean C leaked
# assembly-order / NextPart / Robot concerns into a Design (§7).
FORBIDDEN_KEY_SUBSTRINGS = ("plan", "steps", "next", "slot", "robot", "order")


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    # §8.10: busy-loop-free retry delay is a C-internal concern; tests inject 0.
    monkeypatch.setattr(designer, "RETRY_DELAY", 0)


# ---------------------------------------------------------------------------
# Helpers. Deliberately independent of app.c_design.validator (see docstring).
# ---------------------------------------------------------------------------


def footprint(block):
    """Studs covered by a block, recomputed independently of C's own validator
    (docs/06_CONTRACT_DRAFT.md §1: 0deg = X2*Y3 or X2*Y2, 90deg = X3*Y2)."""
    x, y = block["x"], block["y"]
    if block["brick_type"] == "2x2x1":
        w, h = 2, 2
    else:  # "2x3x1"
        w, h = (2, 3) if block["orientation_deg"] == 0 else (3, 2)
    return {(x + dx, y + dy) for dx in range(w) for dy in range(h)}


def _block_tuple(block):
    return tuple(block[key] for key in BLOCK_KEYS)


def assert_no_forbidden_keys(value, path="design"):
    if isinstance(value, dict):
        for key, sub in value.items():
            lowered = str(key).lower()
            assert not any(bad in lowered for bad in FORBIDDEN_KEY_SUBSTRINGS), (
                f"forbidden key '{key}' found at {path} (plan/step/robot concerns must stay out of Design, §7)"
            )
            assert_no_forbidden_keys(sub, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            assert_no_forbidden_keys(item, f"{path}[{i}]")


def assert_envelope_shape(result):
    """§6: the result envelope shape, shared by both public functions."""
    assert set(result.keys()) == {"status", "hri_result", "design", "questions", "error"}
    assert result["status"] in {"OK", "FAILED", "CANCELLED"}
    assert result["hri_result"] in {"KEEP", "REVISE", "UNCLEAR", None}
    assert isinstance(result["questions"], list)
    assert all(isinstance(q, str) for q in result["questions"])
    if result["status"] == "OK":
        assert result["error"] is None
    else:
        error = result["error"]
        assert error is not None
        assert error["code"] in ALLOWED_ERROR_CODES
        assert isinstance(error["details"], list)


def assert_design_is_consumer_valid(design):
    """C -> A checks (docs/C_DESIGN_CONTRACT.md §3, §7; docs/06_CONTRACT_DRAFT.md §1-2)."""
    assert set(design.keys()) == DESIGN_KEYS
    assert isinstance(design["design_version"], int) and design["design_version"] >= 1
    blocks = design["blocks"]
    assert isinstance(blocks, list)
    assert 1 <= len(blocks) <= 20

    for block in blocks:
        assert set(block.keys()) == BLOCK_KEYS
        assert block["brick_type"] in {"2x2x1", "2x3x1"}
        assert block["color"] in {"yellow", "blue"}
        assert block["layer"] in {1, 2, 3, 4}
        if block["brick_type"] == "2x2x1":
            assert block["orientation_deg"] == 0
        else:
            assert block["orientation_deg"] in {0, 90}
        assert isinstance(block["x"], int) and not isinstance(block["x"], bool)
        assert isinstance(block["y"], int) and not isinstance(block["y"], bool)

        cells = footprint(block)
        xs = [cx for cx, _ in cells]
        ys = [cy for _, cy in cells]
        assert 0 <= min(xs) and max(xs) <= 23, f"block {block} footprint escapes x 0..23"
        assert 0 <= min(ys) and max(ys) <= 23, f"block {block} footprint escapes y 0..23"

    assert_no_forbidden_keys(design)


def assert_current_preserved(current, result_blocks):
    """§8.3: the latest D-adopted current's six-value multiset must be contained
    in the Revised Design (counts included)."""
    current_counts = Counter(_block_tuple(b) for b in current)
    result_counts = Counter(_block_tuple(b) for b in result_blocks)
    for tup, needed in current_counts.items():
        assert result_counts.get(tup, 0) >= needed, f"current block {tup} not preserved in result"


def shift_one_leg(legs):
    """Return (new_legs, old_leg, moved_leg): a copy of a layer-1 leg list with
    exactly one leg nudged by one stud, staying on the Board and not colliding
    with any other leg. A one-stud nudge keeps the moved leg's footprint
    overlapping its own original footprint, which is what lets the Mock
    Revised generator treat it as "the same leg, moved" instead of adding a
    second leg at the old spot (designer.py's mock_revised_candidate keys off
    footprint overlap with current, not block identity - there is no
    block_id, by design, §8.4)."""
    for i, leg in enumerate(legs):
        others = [other for j, other in enumerate(legs) if j != i]
        other_cells = set()
        for other in others:
            other_cells |= footprint(other)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            moved = dict(leg)
            moved["x"] += dx
            moved["y"] += dy
            cells = footprint(moved)
            if all(0 <= cx <= 23 for cx, _ in cells) and all(0 <= cy <= 23 for _, cy in cells):
                if not (cells & other_cells):
                    new_legs = [dict(b) for b in legs]
                    new_legs[i] = moved
                    return new_legs, leg, moved
    raise AssertionError("could not find a safe one-stud leg shift for this mock design")


@pytest.fixture
def initial_design():
    """A real Initial Design from the Mock generator (docs/C_DESIGN_CONTRACT.md §4.1)."""
    result = main.create_initial_design(text=CHAIR_TEXT)
    assert result["status"] == "OK", result
    design = result["design"]
    assert_design_is_consumer_valid(design)
    return design


@pytest.fixture
def moved_leg_scenario(initial_design):
    """A plausible Intervention trigger: one layer-1 leg physically placed one
    stud off from where the Initial Design put it. Current only has the legs
    assembled so far (designer.py: "Mock Revised는 다리(layer 1)만 조립된 상태를
    다룬다"); differences carries the single Difference causing the Intervention."""
    legs = [b for b in initial_design["blocks"] if b["layer"] == 1]
    current, old_leg, moved_leg = shift_one_leg(legs)
    differences = [{"expected": old_leg, "actual": moved_leg}]
    return initial_design, current, differences


# ---------------------------------------------------------------------------
# C -> D: create_initial_design outcomes
# ---------------------------------------------------------------------------


def test_create_initial_design_ok():
    result = main.create_initial_design(text=CHAIR_TEXT)
    assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] is None
    assert result["questions"] == []  # §6: Initial은 빈 배열
    design = result["design"]
    assert_design_is_consumer_valid(design)
    assert design["design_version"] == 1
    assert len(design["blocks"]) == 15
    assert any(b["layer"] == 1 for b in design["blocks"])


def test_create_initial_design_unsupported_object_is_failed():
    result = main.create_initial_design(text="오늘은 바나나를 만들 거야")
    assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["hri_result"] is None
    assert result["design"] is None
    assert result["error"]["code"] == "UNSUPPORTED_OBJECT"


# NOTE: there is intentionally no "create_initial_design + should_stop=True ->
# CANCELLED/STOPPED" test here. §4.1 only promises should_stop is checked
# "재생성 시도 사이" (between regeneration attempts), and designer.py's Mock
# Initial generator always succeeds on its first attempt (it is deterministic,
# §8.10), so should_stop is never actually invoked for create_initial_design
# in this wave - asserting CANCELLED here would fail against a contract-
# conformant implementation. See the contract-review notes in this worker's
# report: this makes should_stop effectively unobservable for Initial Design
# until a real (retry-capable) generator exists. STOPPED is covered below via
# run_intervention, where main.py does check should_stop before the first
# question.


# ---------------------------------------------------------------------------
# D -> C: Current / Difference acceptance
# ---------------------------------------------------------------------------


def test_current_and_difference_need_only_six_fields_and_no_block_id(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    for block in current:
        assert set(block.keys()) == BLOCK_KEYS
        assert "block_id" not in block
    for diff in differences:
        for side in ("expected", "actual"):
            assert set(diff[side].keys()) == BLOCK_KEYS
            assert "block_id" not in diff[side]

    result = main.run_intervention(design, current, differences, text_answers=["1번"])
    assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"


def test_extra_d_fields_on_current_and_difference_are_ignored(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    # D-only diagnostic fields that C must read-and-ignore (§5): per-block
    # observation metadata on Current, plus a check_id tying a Difference back
    # to the observation that produced it.
    noisy_current = [dict(b, confidence=0.97, observation_seq=12, check_id="J01:C07") for b in current]
    noisy_differences = [
        {
            "expected": dict(d["expected"], confidence=0.99) if d["expected"] else None,
            "actual": dict(d["actual"], confidence=0.81) if d["actual"] else None,
            "check_id": "J01:C07",
            "observation_seq": 12,
        }
        for d in differences
    ]

    result = main.run_intervention(design, noisy_current, noisy_differences, text_answers=["1번"])
    assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"
    # The extra keys must not leak into the returned Design's blocks either.
    for block in result["design"]["blocks"]:
        assert set(block.keys()) == BLOCK_KEYS


# ---------------------------------------------------------------------------
# C -> D: run_intervention outcomes
# ---------------------------------------------------------------------------


def test_run_intervention_keep(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    result = main.run_intervention(design, current, differences, text_answers=["1번"])
    assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"
    assert result["design"] == design  # §4.2: input design returned unchanged
    assert result["design"]["design_version"] == design["design_version"]


def test_run_intervention_revise(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    result = main.run_intervention(design, current, differences, text_answers=["2번"])
    assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "REVISE"
    revised = result["design"]
    assert_design_is_consumer_valid(revised)
    # §8.2: version bumps by exactly 1 because the leg actually moved.
    assert revised["design_version"] == design["design_version"] + 1
    # §8.3: the latest adopted Current (incl. the moved leg) must be preserved.
    assert_current_preserved(current, revised["blocks"])


def test_run_intervention_unclear(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    result = main.run_intervention(design, current, differences, text_answers=["모르겠어요"])
    assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "UNCLEAR"
    assert result["design"] is None


def test_run_intervention_invalid_input_empty_differences(moved_leg_scenario):
    design, current, _ = moved_leg_scenario

    result = main.run_intervention(design, current, [], text_answers=["1번"])
    assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["hri_result"] is None
    assert result["design"] is None
    assert result["error"]["code"] == "INVALID_INPUT"


def test_run_intervention_voice_mode_not_connected_is_failed(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    # text_answers=None => voice mode; no voice provider is wired up this wave.
    result = main.run_intervention(design, current, differences, text_answers=None)
    assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["design"] is None
    assert result["error"]["code"] == "VOICE_IO_FAILED"


def test_run_intervention_stopped_is_cancelled(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    result = main.run_intervention(
        design, current, differences, text_answers=["1번"], should_stop=lambda: True
    )
    assert_envelope_shape(result)
    assert result["status"] == "CANCELLED"
    assert result["hri_result"] is None
    assert result["design"] is None
    assert result["error"]["code"] == "STOPPED"


def test_run_intervention_user_cancel(moved_leg_scenario):
    design, current, differences = moved_leg_scenario

    result = main.run_intervention(design, current, differences, text_answers=["취소할게"])
    assert_envelope_shape(result)
    assert result["status"] == "CANCELLED"
    assert result["hri_result"] is None
    assert result["design"] is None
    assert result["error"]["code"] == "USER_CANCEL"
