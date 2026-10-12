"""Wave 6 final contract pins (2026-10-12): intent table across the three dialogue modes, version chain v1→v2→v3,
metadata carried through review, planning-failure routing, and the unchanged Design schema / validator limits.

Everything here is already exercised piecewise by the Wave 1–5 tests; this file states the final contract in one place
so a future change that flips any of these shows up by name. Mock mode unless noted; LLM functions are stubbed.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, main, validator

FIXTURES = Path(__file__).parents[2] / "fixtures" / "c_design_change"
JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True,
            "design_name": "n", "design_family": "chair", "why_it_is_complete": "ok", "visible_features": [], "change_summary": []}


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(designer, "RETRY_DELAY", 0)


# ---------------------------------------------------------------------------
# Intent final table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("수정할게요", dialogue.KEEP), ("원래대로 할게", dialogue.KEEP), ("2번", dialogue.REVISE), ("이대로 유지해", dialogue.REVISE),
])
def test_intent_difference_intervention(text, expected):
    assert dialogue.parse_response(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("수정할게요", dialogue.REVISE), ("바꿔줘", dialogue.REVISE), ("그대로 갈게", dialogue.KEEP), ("바꾸지 마", dialogue.KEEP),
    ("글쎄", dialogue.UNCLEAR),
])
def test_intent_direct_design_change(text, expected):
    assert dialogue.parse_design_change_response(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("응, 수정해줘", dialogue.REVISE), ("아니, 기존 설계로 할래", dialogue.KEEP), ("무슨 뜻이야", dialogue.UNCLEAR),
])
def test_intent_planning_failure_uses_design_change_table(text, expected):
    design = designer.build_initial_design("CHAIR")["design"]
    current = [b for b in design["blocks"] if b["layer"] == 1]
    failure = {"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True, "blocked_blocks": []}
    envelope = main.run_design_change(design, current, reason="PLANNING_FAILURE", planning_failure=failure, text_answers=[text])
    assert envelope["status"] == "OK" and envelope["hri_result"] == expected


# ---------------------------------------------------------------------------
# Planning failure routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code, redesign_required, dialogue_opens", [
    ("NO_FEASIBLE_ORDER", True, True), ("NO_FEASIBLE_ORDER", False, False), ("SEARCH_LIMIT", True, False),
    ("SEARCH_LIMIT", False, False), ("CURRENT_MISMATCH", True, False), ("INVALID_CONTEXT", True, False),
    ("INPUTS_REQUIRED", True, False), ("CALCULATION_ERROR", True, False), ("REAL_PLAN_NEEDS_REFILL", True, False),
    ("STOP", True, False),
])
def test_planning_failure_routing(code, redesign_required, dialogue_opens):
    design = designer.build_initial_design("CHAIR")["design"]
    current = [b for b in design["blocks"] if b["layer"] == 1]
    asked = []
    envelope = main.run_design_change(design, current, reason="x", text_answers=["1번"], on_question=asked.append,
                                      planning_failure={"failure_code": code, "redesign_required": redesign_required})
    if dialogue_opens:
        assert envelope["status"] == "OK" and len(asked) == 1 and code not in asked[0]
    else:
        assert envelope["error"]["code"] == "PLANNING_FAILURE_NOT_REDESIGN" and asked == []
    assert main.REDESIGN_FAILURE_CODES == ("NO_FEASIBLE_ORDER",)


# ---------------------------------------------------------------------------
# Version chain and metadata (LLM stubs on the fixture Design)
# ---------------------------------------------------------------------------


def _taller(approved, extra=0):
    blocks = [b for b in approved["blocks"] if b["layer"] != 5]
    blocks += [dict(brick_type="2x2x1", color="blue", x=8, y=y, layer=5, orientation_deg=0) for y in (8, 10, 12)]
    if extra:
        blocks.append(dict(brick_type="1x2x1", color="red", x=10, y=8, layer=3, orientation_deg=0))
    return {"blocks": blocks}


def test_version_chain_v1_v2_v3_and_metadata(monkeypatch):
    approved_v1 = _load("approved_design.json")
    # Difference = the layer-5 crown is still missing (expected set, actual None); Current = the four legs, which every
    # stubbed candidate preserves. (A shifted-leg Current would make the stub candidates fail Current preservation.)
    crown = next(b for b in approved_v1["blocks"] if b["layer"] == 5)
    scenario = {"current": _load("current_prefix.json"), "differences": [{"expected": crown, "actual": None}]}
    assert validator.check_intervention_input(approved_v1, scenario["current"], scenario["differences"]) == []
    outputs = {"next": _taller(approved_v1)}
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "revised_min_blocks", lambda design: len(design["blocks"]))
    monkeypatch.setattr(llm, "generate_revised_design", lambda *a, **k: deepcopy(outputs["next"]))
    monkeypatch.setattr(llm, "judge_revised_design", lambda *a, **k: deepcopy(JUDGE_OK))
    monkeypatch.setattr(llm, "interpret_intervention_answer",
                        lambda text, differences, should_stop=None, context=None, planning_failure=None:
                        {"decision": "REVISE", "style_hint": "더 높게", "reason": "r", "reply": "p"})
    monkeypatch.setattr(llm, "interpret_review_answer",
                        lambda text, kind, should_stop=None, context=None:
                        {"decision": "MODIFY" if "바꿔" in text else "APPROVE", "style_hint": "조금 더", "scope": "patch",
                         "concept": "", "reason": "r", "reply": "p"})

    # Approved v1 → Difference REVISE → Candidate v2 (metadata: source, style_hint, judge)
    revise = main.run_intervention(approved_v1, scenario["current"], scenario["differences"], text_answers=["2번"])
    v2, meta = revise["design"], revise["design_metadata"]
    assert v2["design_version"] == 2 and meta["source"] == "LLM" and meta["judge"]["verdict"] == "SHOWCASE"
    assert validator.validate_revised({"blocks": v2["blocks"]}, scenario["current"]) == []

    # Revised MODIFY → v2 kept, review.round 1; APPROVE → Approved v2, round unchanged, Stage 2 keys kept
    outputs["next"] = _taller(approved_v1, extra=1)
    modified = main.review_design_candidate(v2, kind="revised", design_metadata=meta, previous_design=approved_v1,
                                            current=scenario["current"], differences=scenario["differences"],
                                            text_answers=["조금 더 바꿔줘"])
    assert modified["hri_result"] == dialogue.MODIFY and modified["design"]["design_version"] == 2
    assert modified["design_metadata"]["review"]["round"] == 1 and modified["design_metadata"]["review"]["kind"] == "revised"
    approved_review = main.review_design_candidate(modified["design"], kind="revised", design_metadata=modified["design_metadata"],
                                                   previous_design=approved_v1, current=scenario["current"],
                                                   differences=scenario["differences"], text_answers=["좋아 이걸로 하자"])
    assert approved_review["hri_result"] == dialogue.APPROVE and approved_review["design"] == modified["design"]
    assert approved_review["design_metadata"]["review"]["round"] == 1 and approved_review["design_metadata"]["source"] == "LLM"
    approved_v2 = approved_review["design"]

    # Approved v2 → next REVISE (direct Design Change, Current = v2 prefix) → Candidate v3
    current_v2 = [b for b in approved_v2["blocks"] if b["layer"] == 1]
    outputs["next"] = {"blocks": approved_v2["blocks"] + [dict(brick_type="1x2x1", color="red", x=12, y=8, layer=3, orientation_deg=0)]}
    assert validator.validate_design({"design_version": 3, "blocks": outputs["next"]["blocks"]}) == []
    change = main.run_design_change(approved_v2, current_v2, reason="USER_DESIGN_CHANGE", text_answers=["수정할게요"])
    assert change["hri_result"] == dialogue.REVISE and change["design"]["design_version"] == 3
    assert all(b in change["design"]["blocks"] for b in current_v2)
    for design in (v2, modified["design"], approved_v2, change["design"]):
        assert set(design) == {"design_version", "blocks"} and "planning_failure" not in design


# ---------------------------------------------------------------------------
# Design schema / validator limits unchanged
# ---------------------------------------------------------------------------


def test_schema_and_validator_limits_are_final():
    assert validator.TOP_FIELDS == ("design_version", "blocks")
    assert validator.BLOCK_FIELDS == ("brick_type", "color", "x", "y", "layer", "orientation_deg")
    assert validator.ALLOWED_COMBINATIONS == {"yellow": frozenset({"2x2x1", "2x3x1"}), "blue": frozenset({"2x2x1", "2x3x1"}),
                                             "red": frozenset({"1x2x1"})}
    assert validator.BOARD_RANGE == range(0, 24) and validator.MAX_LAYER == 5 and validator.MAX_BLOCKS == 40
    assert validator.MIN_SUPPORT_STUDS == 2
    design = _load("approved_design.json")
    assert validator.validate_design(dict(design, facing="+X")) != []  # unknown top-level key is rejected
    assert validator.validate_design({"design_version": 1, "blocks": [dict(design["blocks"][0], facing="+X")]}) != []
