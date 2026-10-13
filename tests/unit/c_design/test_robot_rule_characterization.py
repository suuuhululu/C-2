"""Robot-only design rule update (2026-10-13) — characterization and acceptance tests.

Wave 1 pinned the behaviour of the C part at the integration baseline (ebeeef2). Each later wave
rewrites the affected section to the new contract in the same commit (never silently deleted):
section 1-2 = Wave 2 (support rule min(4, studs of the brick) on every candidate path), sections
3-5 still describe the behaviour Wave 3 (user constraints over expressive defaults) and Wave 4
(Current-vs-request conflict handling) change.

Scope: C modules only (app/c_design) and C-owned fixtures. Designs that D-owned tests feed
into the C validator are reproduced inline (they are read-only facts about today's rule);
the D test files themselves are not imported or modified.
"""

import json
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, main, validator as v

ROOT = Path(__file__).resolve().parents[3]


def block(color="yellow", brick_type="2x2x1", x=0, y=0, orientation_deg=0, layer=1):
    return {"color": color, "brick_type": brick_type, "x": x, "y": y, "orientation_deg": orientation_deg,
            "layer": layer}


def design(blocks):
    return {"design_version": 1, "blocks": blocks}


def rules(reasons):
    return {r["rule"] for r in reasons}


def min_support_per_block(blocks):
    """(shared studs with the layer directly below, studs of the brick) for every layer>=2 block."""
    nodes = []
    for b in blocks:
        _, node = v._check_block(b, reject_unknown_keys=False)
        if node is not None:
            nodes.append(node)
    by_layer = {}
    for node in nodes:
        by_layer.setdefault(node["layer"], []).append(node)
    out = []
    for node in nodes:
        if node["layer"] < 2:
            continue
        shared = set()
        for below in by_layer.get(node["layer"] - 1, []):
            shared |= node["footprint"] & below["footprint"]
        out.append((len(shared), len(node["footprint"])))
    return out


# ---------------------------------------------------------------------------
# 1. Validator support rule (Wave 2, 2026-10-13): required = min(4, studs of the brick), every candidate path
# ---------------------------------------------------------------------------


def test_support_constant_is_four_and_per_brick():
    assert v.MIN_SUPPORT_STUDS == 4
    assert (v.MAX_LAYER, v.MAX_BLOCKS) == (5, 40)  # upper bounds; unchanged by the update
    assert v.required_support_studs(block(brick_type="2x2x1")) == 4
    assert v.required_support_studs(block(brick_type="2x3x1")) == 4
    assert v.required_support_studs(block(color="red", brick_type="1x2x1")) == 2


def test_2x2x1_on_two_studs_rejected():
    # Until 2026-10-12 this passed (2-stud rule). Now a 2x2x1 on layer >= 2 needs all 4 studs supported.
    blocks = [block(brick_type="2x3x1", x=3, y=0, layer=1), block(brick_type="2x2x1", x=3, y=2, layer=2)]
    assert min_support_per_block(blocks) == [(2, 4)]
    assert rules(v.validate_design(design(blocks))) == {"support"}


def test_2x2x1_on_three_studs_rejected():
    blocks = [block(brick_type="2x3x1", x=0, y=0, layer=1), block(brick_type="2x2x1", x=1, y=0, layer=2),
              block(brick_type="2x2x1", x=2, y=1, layer=1)]  # 2 studs from the 2x3x1 + 1 stud from the 2x2x1
    assert min_support_per_block(blocks) == [(3, 4)]
    assert rules(v.validate_design(design(blocks))) == {"support"}


def test_2x2x1_on_four_studs_passes():
    blocks = [block(brick_type="2x3x1", x=0, y=0, layer=1), block(brick_type="2x2x1", x=0, y=1, layer=2)]
    assert min_support_per_block(blocks) == [(4, 4)]
    assert v.validate_design(design(blocks)) == []


def test_2x3x1_on_three_studs_rejected_four_and_six_pass():
    base = block(brick_type="2x3x1", x=0, y=0, layer=1)
    assert rules(v.validate_design(design([base, block(brick_type="2x3x1", x=1, y=0, layer=2)]))) == {"support"}
    assert v.validate_design(design([base, block(brick_type="2x3x1", x=0, y=1, layer=2)])) == []  # 4 of 6
    assert v.validate_design(design([base, block(brick_type="2x3x1", x=0, y=0, layer=2)])) == []  # 6 of 6


def test_two_below_blocks_one_stud_each_rejected():
    # Case B of the Day4 rule (1 + 1 = 2 studs) is no longer enough for a 2x2x1.
    blocks = [block(x=4, y=4, layer=1), block(x=6, y=6, layer=1), block(x=5, y=5, layer=2)]
    assert min_support_per_block(blocks) == [(2, 4)]
    assert rules(v.validate_design(design(blocks))) == {"support"}


def test_duplicate_studs_are_not_counted_twice():
    # The same stud cannot be supplied by two blocks of the layer below (they would overlap and be rejected),
    # so the count is the size of the union of overlaps, never a sum.
    blocks = [block(x=0, y=0, layer=1), block(x=2, y=0, layer=1), block(x=1, y=0, layer=2)]  # 2 + 2 unique = 4
    assert min_support_per_block(blocks) == [(4, 4)]
    assert v.validate_design(design(blocks)) == []


def test_red_1x2x1_fully_supported_passes_and_one_stud_fails():
    base = block(brick_type="2x2x1", x=0, y=0, layer=1)
    assert v.validate_design(design([base, block(color="red", brick_type="1x2x1", x=0, y=0, layer=2)])) == []
    assert rules(v.validate_design(design([base, block(color="red", brick_type="1x2x1", x=1, y=1, layer=2)]))) == {"support"}


def test_layer_one_never_checked():
    blocks = [block(x=0, y=0, layer=1), block(x=10, y=10, layer=1), block(x=0, y=2, layer=1)]
    assert "support" not in rules(v.validate_design(design(blocks)))


def test_only_the_layer_directly_below_counts():
    blocks = [block(brick_type="2x3x1", x=0, y=0, layer=1), block(brick_type="2x3x1", x=2, y=0, layer=1),
              block(brick_type="2x2x1", x=1, y=0, layer=2), block(brick_type="2x2x1", x=1, y=1, layer=3)]
    reasons = v.validate_design(design(blocks))
    assert [r["blocks"][0]["layer"] for r in reasons if r["rule"] == "support"] == [3]  # layer 1 under it does not count


def test_current_and_revised_candidates_use_the_same_rule_no_two_stud_exception():
    # No production exception: a Current block on 2 studs is an escalation trigger and a Revised candidate
    # that keeps it is rejected the same way as a new block would be.
    current = [block(brick_type="2x3x1", x=3, y=0, layer=1), block(brick_type="2x2x1", x=3, y=2, layer=2)]
    assert rules(v.current_support_violations(current)) == {"support"}
    candidate = {"blocks": [dict(current[0]), dict(current[1])]}
    assert rules(v.validate_revised(candidate, current)) == {"support"}


def test_every_candidate_path_validates_with_the_same_functions():
    # Initial → validate_design (designer.build_initial_design finalize); Revised / Design Change / Difference /
    # Planning-failure redesign / Review MODIFY → validate_revised + validate_design (designer.build_revised_design
    # finalize) and _review → validate_design. All share _placement_violations → _support_violations.
    import inspect
    src_designer = inspect.getsource(designer)
    assert "validator.validate_design(design)" in src_designer and "validator.validate_revised(candidate, current)" in src_designer
    assert "validator.validate_design(final)" in src_designer
    assert "_support_violations(nodes)" in inspect.getsource(v._placement_violations)
    assert "_placement_violations(nodes)" in inspect.getsource(v.validate_design)
    assert "_placement_violations(nodes)" in inspect.getsource(v.validate_revised)
    assert "_support_violations(nodes)" in inspect.getsource(v.current_support_violations)
    assert "validator.validate_design(candidate)" in inspect.getsource(main._review)


def test_prompt_rule_lines_state_the_per_brick_rule():
    assert "min(4, its own stud count)" in llm._RULE_LINES
    assert "a 2x2x1 needs all 4 of its studs supported, a 2x3x1 at least 4 of its 6, a 1x2x1 both of its 2" in llm._RULE_LINES
    assert "both of its 2 studs must rest on blocks of the layer directly below" in llm._RULE_LINES
    assert "at least min(4, the block's own stud count)" in llm._SELF_CHECK
    assert "it still needs" not in llm._RULE_LINES


# ---------------------------------------------------------------------------
# 2. Designs other tests feed into the validator (facts, reproduced inline)
# ---------------------------------------------------------------------------


def _five_layer_thirty_blocks():
    # Same construction as tests/integration/test_five_layer_pipeline.py::thirty_blocks (D-owned test; synthetic input
    # adjusted on 2026-10-13: odd layers 2x3x1 0°, even layers 2x3x1 90° over the same 6x6 footprint).
    blocks = []
    for layer in range(1, 6):
        if layer % 2:
            blocks += [dict(brick_type="2x3x1", color="yellow", x=8 + col * 2, y=8 + row * 3, layer=layer,
                            orientation_deg=0) for row in range(2) for col in range(3)]
        else:
            blocks += [dict(brick_type="2x3x1", color="yellow", x=8 + col * 3, y=8 + row * 2, layer=layer,
                            orientation_deg=90) for row in range(3) for col in range(2)]
    return blocks


def _supply_cycle_forty_blocks():
    # Same construction as tests/unit/test_mvp_supply_cycle.py::test_design_count_limit_remains_forty_in_c_and_a
    # (synthetic input adjusted on 2026-10-13: pyramid 11+10+9+8+7, ends inset by one stud per layer).
    blocks = [dict(brick_type="2x2x1", color="yellow", x=2 * i + (layer - 1), y=0, layer=layer, orientation_deg=0)
              for layer, count in [(1, 11), (2, 10), (3, 9), (4, 8), (5, 7)] for i in range(count)][:41]
    return blocks[:40]


def test_d_synthetic_designs_now_satisfy_the_per_brick_rule():
    thirty, forty = _five_layer_thirty_blocks(), _supply_cycle_forty_blocks()
    assert len(thirty) == 30 and len(forty) == 40
    assert v.validate_design(design(thirty)) == []
    assert v.validate_design(design(forty)) == []
    assert all(shared >= min(4, studs) for shared, studs in min_support_per_block(thirty))
    assert all(shared >= min(4, studs) for shared, studs in min_support_per_block(forty))


@pytest.mark.parametrize("name", ["intervention_revise_response.json", "review_revised_modify_patch_response.json"])
def test_historical_sol_fixtures_keep_their_three_stud_blocks(name):
    # Real gpt-6.1-sol outputs recorded in Stage 3 (2-stud era) are kept unchanged as historical records. Under the
    # 2026-10-13 rule they are no longer valid candidates: exactly four 2x3x1 blocks on 3 studs are reported.
    data = json.loads((ROOT / "tests/fixtures/c_stage3" / name).read_text())
    blocks = data["design"]["blocks"]
    reasons = v.validate_design(data["design"])
    assert rules(reasons) == {"support"} and len(reasons) == 4
    sub_four = [(shared, studs) for shared, studs in min_support_per_block(blocks) if shared < min(4, studs)]
    assert sub_four == [(3, 6)] * 4


def test_mock_initial_and_mock_revised_satisfy_the_per_brick_rule():
    # Mock Initial (15 blocks) has full support. Mock Revised after a back leg moves by one stud used to build a
    # layer-4 bridge on 3 studs; since 2026-10-13 designer._chair_upper aligns the backrest rows so the bridge rests
    # on 2 + 2 studs.
    initial = designer.build_initial_design("CHAIR", max_attempts=1, delay=0)["design"]
    assert all(shared >= min(4, studs) for shared, studs in min_support_per_block(initial["blocks"]))
    legs = [b for b in initial["blocks"] if b["layer"] == 1]
    target = max(legs, key=lambda b: b["y"])
    shifted = dict(target, y=target["y"] + 1)
    current = [shifted if b is target else dict(b) for b in legs]
    differences = [{"expected": dict(target), "actual": dict(shifted)}]
    result = designer.build_revised_design(initial, current, differences, max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    assert all(shared >= min(4, studs) for shared, studs in min_support_per_block(result["design"]["blocks"]))
    assert v.validate_design(result["design"]) == []


# ---------------------------------------------------------------------------
# 3. Expressive defaults are hard today (Wave 3 makes them yield to stated user limits)
# ---------------------------------------------------------------------------


def test_w1_revised_requires_six_more_blocks_than_the_previous_design():
    assert designer.RICHNESS_MIN_DELTA == 6
    previous = design([block(layer=1)] * 15)
    assert designer.revised_min_blocks(previous) == 21
    assert designer.revised_min_blocks(design([block(layer=1)] * 38)) == 40


def test_w1_too_few_blocks_rejects_a_valid_smaller_candidate():
    leg = block(color="blue", brick_type="2x3x1", x=10, y=10, layer=1)
    seat = block(brick_type="2x2x1", x=10, y=10, layer=2)
    approved = design([leg, seat])
    current = [dict(leg)]
    differences = [{"expected": seat, "actual": seat}]

    def gen(design_in, current_in, differences_in, reasons):
        return {"blocks": [dict(leg), dict(seat, y=11)]}  # still only 2 blocks, seat still 4/4 on the leg

    result = designer.build_revised_design(approved, current, differences, generate=gen, max_attempts=1, delay=0,
                                           min_blocks=designer.revised_min_blocks(approved))
    assert result["design"] is None
    assert rules(result["reasons"]) == {"too_few_blocks"}


def test_w1_revised_guidance_orders_layer_five_and_block_count_above_the_style_hint():
    guidance = llm._REVISED_PRIORITIES
    assert "- Fifth, layer 5 is part of a feature" in guidance
    assert "a plain low single-seat chair is not acceptable" in guidance
    assert "person" not in guidance.split("- Third,")[1].split("- Fourth,")[0]  # no "stated limits" priority item today
    message = llm._revised_user_message(design([block(layer=1)]), [], [], [], style_hint="낮고 간단하게")
    assert message.index("- Sixth, use as many blocks") < message.index("Style hint from the person (follow it first)")
    assert "bigger and bolder than the previous design" in llm.SYSTEM_PROMPT_REVISED
    assert "use layer 5 as a real feature" in llm.SYSTEM_PROMPT_REVISED


def test_w1_judge_regenerates_when_not_richer_regardless_of_the_request():
    judge = {"recognizable_family": True, "silhouette_clarity": "clear", "chair_likeness": "clear",
             "richer_than_previous": False}
    assert main._needs_regeneration(judge) is True


def test_w1_initial_prompt_has_no_expressive_default_and_no_user_priority_item():
    assert "Size and height are free within the rules" in llm.SYSTEM_PROMPT_INITIAL
    assert "Tall back" not in llm.SYSTEM_PROMPT_INITIAL
    message = llm._initial_user_message("CHAIR", [], family="high-back chair", style_hint="낮게")
    assert "Style preference from the person: 낮게" in message
    assert "wins over" not in message  # only the review-patch path says the person's change wins today


# ---------------------------------------------------------------------------
# 4. User constraints (Wave 3 acceptance, 2026-10-13). Wave 1 pinned that the ANY fast path swallowed stated limits and
#    that no structured constraint existed; Wave 3 keeps those limits (rule extraction + optional interpretation key).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [("아무거나 간단하게", {"complexity": "simple"}),
                                            ("알아서 3층까지만", {"max_layer": 3}),
                                            ("블록 적게 아무거나", {"block_budget": "fewer"})])
def test_w3_any_with_stated_limits_is_not_swallowed(text, expected):
    # Wave 1: these returned ANY (no interpretation, limit lost). Now they go to interpretation and the rule keeps the limit.
    assert dialogue.parse_initial_request(text) is None
    assert dialogue.extract_constraints(text) == expected


@pytest.mark.parametrize("text", ["아무거나 낮게", "3층까지만 만들어줘"])
def test_w1_other_limit_phrases_go_to_llm_interpretation(text):
    assert dialogue.parse_initial_request(text) is None


def test_w3_constraints_are_optional_interpretation_keys_with_rule_extraction():
    # Interpretation responses stay valid without "constraints" (optional key, not in the required key tuples).
    assert "constraints" not in llm.REQUEST_KEYS
    assert "constraints" not in llm.INTERVENTION_ANSWER_KEYS
    assert "constraints" not in llm.REVIEW_KEYS
    for prompt in (llm.SYSTEM_PROMPT_REQUEST, llm.SYSTEM_PROMPT_INTERVENTION_ANSWER, llm.SYSTEM_PROMPT_DESIGN_CHANGE_ANSWER,
                   llm.SYSTEM_PROMPT_REVIEW):
        assert '"constraints": optional object' in prompt
    assert dialogue.CONSTRAINT_KEYS == ("max_layer", "max_blocks", "height", "complexity", "block_budget", "footprint")
    assert dialogue.extract_constraints("낮고 넓게, 3층까지만") == {"max_layer": 3, "height": "low", "footprint": "wide"}


# ---------------------------------------------------------------------------
# 5. Current-vs-request conflicts (Wave 4 acceptance, 2026-10-13). Wave 1 pinned that no conflict detection existed;
#    Wave 4 compares stated limits with the assembled Current deterministically and asks before generating.
# ---------------------------------------------------------------------------


def test_w4_conflict_detection_exists_before_revise():
    current = [block(layer=1), block(layer=2), block(layer=3), block(layer=4)]
    assert main.constraints_vs_current({"max_layer": 3}, current) == {"max_layer": {"requested": 3, "current": 4}}
    assert main.constraints_vs_current({"max_layer": 4}, current) == {}
    question = dialogue.build_constraint_conflict_question({"max_layer": {"requested": 3, "current": 4}}, design_change=True)
    assert question.startswith("지금 4층까지 이미 조립돼 있어서")
