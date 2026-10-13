"""WAVE 1 characterization — Robot-only design rule update (2026-10-13).

These tests pin the behaviour of the C part at the integration baseline (ebeeef2) BEFORE the
support rule (2 studs → min(4, studs of the brick)) and the user-constraint priority are
introduced. Each test says which later wave changes the pinned behaviour; when that wave
lands, the test is updated to the new contract in the same commit, never silently deleted.

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
# 1. Validator support rule today: 2 studs in total, no per-brick requirement (Wave 2 changes this)
# ---------------------------------------------------------------------------


def test_w1_support_constant_is_two_today():
    assert v.MIN_SUPPORT_STUDS == 2
    assert (v.MAX_LAYER, v.MAX_BLOCKS) == (5, 40)  # upper bounds; unchanged by the update


def test_w1_2x2x1_on_two_studs_passes_today():
    # Wave 2: a 2x2x1 on layer >= 2 needs all 4 studs supported → this design will be rejected (rule "support").
    blocks = [block(brick_type="2x3x1", x=3, y=0, layer=1), block(brick_type="2x2x1", x=3, y=2, layer=2)]
    assert min_support_per_block(blocks) == [(2, 4)]
    assert v.validate_design(design(blocks)) == []


def test_w1_2x2x1_on_three_studs_passes_today():
    # Wave 2: 3 < 4 → rejected.
    blocks = [block(brick_type="2x3x1", x=0, y=0, layer=1), block(brick_type="2x2x1", x=1, y=0, layer=2),
              block(brick_type="2x2x1", x=2, y=1, layer=1)]  # 2 studs from the 2x3x1 + 1 stud from the 2x2x1
    assert min_support_per_block(blocks) == [(3, 4)]
    assert v.validate_design(design(blocks)) == []


def test_w1_2x3x1_on_three_studs_passes_today():
    # Wave 2: a 2x3x1 needs at least 4 of its 6 studs → 3 is rejected.
    blocks = [block(brick_type="2x3x1", x=0, y=0, layer=1), block(brick_type="2x3x1", x=1, y=0, layer=2)]
    assert min_support_per_block(blocks) == [(3, 6)]
    assert v.validate_design(design(blocks)) == []


def test_w1_two_below_blocks_one_stud_each_passes_today():
    # Case B of the Day4 rule: 1 + 1 = 2 studs. Wave 2: 2 < 4 → rejected.
    blocks = [block(x=4, y=4, layer=1), block(x=6, y=6, layer=1), block(x=5, y=5, layer=2)]
    assert min_support_per_block(blocks) == [(2, 4)]
    assert v.validate_design(design(blocks)) == []


def test_w1_red_1x2x1_fully_supported_passes_today():
    # Unchanged by Wave 2: a 1x2x1 has 2 studs, both must be supported (min(4, 2) = 2).
    blocks = [block(brick_type="2x2x1", x=0, y=0, layer=1), block(color="red", brick_type="1x2x1", x=0, y=0, layer=2)]
    assert min_support_per_block(blocks) == [(2, 2)]
    assert v.validate_design(design(blocks)) == []


def test_w1_layer_one_never_checked():
    blocks = [block(x=0, y=0, layer=1), block(x=10, y=10, layer=1), block(x=0, y=2, layer=1)]
    assert "support" not in rules(v.validate_design(design(blocks)))


def test_w1_current_support_judged_with_the_same_constant_today():
    # A Current block resting on 2 studs is not an escalation trigger today. Wave 2 applies the same
    # per-brick rule to Current (no 2-stud exception in production).
    current = [block(brick_type="2x3x1", x=3, y=0, layer=1), block(brick_type="2x2x1", x=3, y=2, layer=2)]
    assert v.current_support_violations(current) == []


def test_w1_revised_candidate_checks_all_blocks_with_the_same_rule():
    current = [block(brick_type="2x3x1", x=3, y=0, layer=1)]
    candidate = {"blocks": [dict(current[0]), block(brick_type="2x2x1", x=3, y=2, layer=2)]}
    assert v.validate_revised(candidate, current) == []


def test_w1_prompt_rule_lines_follow_the_constant():
    assert "at least 2 studs in total" in llm._RULE_LINES
    assert "it still needs 2 studs of support below" in llm._RULE_LINES  # Wave 2 rewrites (1x2x1 = both studs)
    assert "at least 2" in llm._SELF_CHECK


# ---------------------------------------------------------------------------
# 2. Designs other tests feed into the validator today (facts, reproduced inline)
# ---------------------------------------------------------------------------


def _five_layer_thirty_blocks():
    # Same construction as tests/integration/test_five_layer_pipeline.py::thirty_blocks (D-owned test).
    return [dict(brick_type="2x3x1", color="yellow", x=8 + col * 2 + (layer % 2), y=8 + row * 3 + (layer % 2),
                 layer=layer, orientation_deg=0) for layer in range(1, 6) for row in range(2) for col in range(3)]


def _supply_cycle_forty_blocks():
    # Same construction as tests/unit/test_mvp_supply_cycle.py::test_design_count_limit_remains_forty_in_c_and_a.
    blocks = [dict(brick_type="2x2x1", color="yellow", x=2 * i + (layer + 1) % 2, y=0, layer=layer, orientation_deg=0)
              for layer, count in [(1, 11), (2, 10), (3, 11), (4, 9)] for i in range(count)]
    return blocks[:40]


def test_w1_d_synthetic_designs_pass_today_but_have_sub_four_stud_blocks():
    # Both D-owned synthetic designs are valid under the 2-stud rule. Under min(4, studs) they are NOT:
    # thirty_blocks has edge blocks on 2-3 studs, the 40-block stagger has end blocks on 2 studs.
    # Decision needed before Wave 2 (D-owned test inputs; C must not edit them).
    thirty, forty = _five_layer_thirty_blocks(), _supply_cycle_forty_blocks()
    assert v.validate_design(design(thirty)) == []
    assert v.validate_design(design(forty)) == []
    assert sum(1 for shared, studs in min_support_per_block(thirty) if shared < min(4, studs)) == 8
    assert sum(1 for shared, studs in min_support_per_block(forty) if shared < min(4, studs)) == 2


@pytest.mark.parametrize("name", ["intervention_revise_response.json", "review_revised_modify_patch_response.json"])
def test_w1_historical_sol_fixtures_have_three_stud_blocks(name):
    # Real gpt-6.1-sol outputs recorded in Stage 3 (2-stud era). They stay as historical records;
    # Wave 2 re-points the tests that assert `validate_design == []` on them to the historical rule.
    data = json.loads((ROOT / "tests/fixtures/c_stage3" / name).read_text())
    blocks = data["design"]["blocks"]
    assert v.validate_design(data["design"]) == []
    sub_four = [(shared, studs) for shared, studs in min_support_per_block(blocks) if shared < min(4, studs)]
    assert sub_four == [(3, 6)] * 4


def test_w1_mock_initial_satisfies_four_studs_but_mock_revised_bridge_does_not():
    # Mock Initial (15 blocks) already has full support. Mock Revised after a back leg moves by one stud
    # builds a layer-4 bridge on 3 studs (designer._chair_upper). Wave 2 strengthens the Mock generator.
    initial = designer.build_initial_design("CHAIR", max_attempts=1, delay=0)["design"]
    assert all(shared >= min(4, studs) for shared, studs in min_support_per_block(initial["blocks"]))
    legs = [b for b in initial["blocks"] if b["layer"] == 1]
    target = max(legs, key=lambda b: b["y"])
    shifted = dict(target, y=target["y"] + 1)
    current = [shifted if b is target else dict(b) for b in legs]
    differences = [{"expected": dict(target), "actual": dict(shifted)}]
    result = designer.build_revised_design(initial, current, differences, max_attempts=1, delay=0)
    assert result["design"] is not None, result["reasons"]
    sub_four = [(shared, studs) for shared, studs in min_support_per_block(result["design"]["blocks"])
                if shared < min(4, studs)]
    assert sub_four == [(3, 4)]


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
        return {"blocks": [dict(leg), dict(seat, x=11)]}  # still only 2 blocks

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
# 4. User constraints are lost or free-text only today (Wave 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["아무거나 간단하게", "알아서 3층까지만", "블록 적게 아무거나"])
def test_w1_any_fast_path_swallows_stated_limits(text):
    # The rule-based ANY shortcut returns ANY (no LLM interpretation, no style_hint) for these.
    assert dialogue.parse_initial_request(text) == dialogue.ANY


@pytest.mark.parametrize("text", ["아무거나 낮게", "3층까지만 만들어줘"])
def test_w1_other_limit_phrases_go_to_llm_interpretation(text):
    assert dialogue.parse_initial_request(text) is None


def test_w1_no_structured_constraint_fields_exist_today():
    assert "constraints" not in llm.REQUEST_KEYS
    assert "constraints" not in llm.INTERVENTION_ANSWER_KEYS
    assert "constraints" not in llm.REVIEW_KEYS
    assert not hasattr(dialogue, "extract_constraints")


# ---------------------------------------------------------------------------
# 5. Current-vs-request conflicts are not detected today (Wave 4)
# ---------------------------------------------------------------------------


def test_w1_no_conflict_detection_before_revise_today():
    # There is no helper comparing stated limits with the assembled Current; the only Current-related
    # pre-check before generation is the support-violation escalation.
    assert not hasattr(main, "constraints_vs_current")
    assert not hasattr(dialogue, "build_constraint_conflict_question")
