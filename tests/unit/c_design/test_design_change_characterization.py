"""Wave 1 characterization (integration de59b08) → Wave 3 acceptance for `run_design_change`.

Wave 1 pinned the de59b08 defects as the behaviour we want, marked xfail(strict=True). Wave 3 (direct Design Change mode)
removed the markers on the three design-change tests, which now pass; the planning-failure wording test stays xfail for
Wave 4. Tests without a marker are behaviours that survived the fix (Difference Intervention, number-answer
compatibility, input contracts). Mock mode only (C_DESIGN_USE_LLM unset); no LLM/STT/TTS.
"""

import json
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, main, validator
from planning_trial.assembly_contract import validate_message

FIXTURES = Path(__file__).parents[2] / "fixtures"
DESIGN_CHANGE = FIXTURES / "c_design_change"
PLAN_FAILURE = FIXTURES / "c_plan_failure"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def approved():
    return _load(DESIGN_CHANGE / "approved_design.json")


@pytest.fixture
def current():
    return _load(DESIGN_CHANGE / "current_prefix.json")


@pytest.fixture
def difference_scenario():
    return _load(DESIGN_CHANGE / "difference_scenario.json")


@pytest.fixture
def change_reason():
    return _load(DESIGN_CHANGE / "design_change_request.json")["reason"]


@pytest.fixture(autouse=True)
def _mock_mode_no_delay(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(designer, "RETRY_DELAY", 0)


@pytest.fixture
def mock_scenario():
    """The deterministic Mock chair with its four legs as Current (tests/unit/c_design/test_main.py convention).

    The Mock Revised generator only knows this chair (designer._chair_upper), so every test that must reach a Revised
    Candidate in Mock mode runs on it; the fixture Design is for contract, facing and planning-failure checks.
    """
    design = designer.build_initial_design("CHAIR")["design"]
    legs = sorted((b for b in design["blocks"] if b["layer"] == 1), key=lambda b: (b["x"], b["y"]))
    target = max(legs, key=lambda b: b["y"])
    shifted = dict(target, y=target["y"] + 1)
    return {"design": design, "current": [dict(b) for b in legs],
            "diff_current": [shifted if b is target else dict(b) for b in legs],
            "differences": [{"expected": dict(target), "actual": dict(shifted)}]}


# ---------------------------------------------------------------------------
# fixtures are valid under the current contract
# ---------------------------------------------------------------------------


def test_fixtures_satisfy_current_contract(approved, current, difference_scenario):
    assert validator.validate_design(approved) == []
    assert len(approved["blocks"]) == 15 and max(b["layer"] for b in approved["blocks"]) == validator.MAX_LAYER
    assert validator._check_current(current) == [] and validator.current_support_violations(current) == []
    assert all(b in approved["blocks"] for b in current)  # prefix of the Approved Design
    assert validator.check_intervention_input(approved, difference_scenario["current"], difference_scenario["differences"]) == []


@pytest.mark.parametrize("name, message_type", [
    ("whole_no_feasible_order_real_unpatched.json", "WholePlanResult"),
    ("whole_no_feasible_order_with_block.json", "WholePlanResult"),
    ("whole_no_feasible_order_no_block.json", "WholePlanResult"),
    ("whole_search_limit.json", "WholePlanResult"),
    ("whole_invalid_context.json", "WholePlanResult"),
    ("step_current_mismatch.json", "StepReassessmentResult"),
])
def test_plan_failure_fixtures_match_a_contract(name, message_type):
    validate_message(_load(PLAN_FAILURE / name), message_type)


def test_real_a_result_carries_no_blocked_block():
    # Evidence for the Wave 4 A→D proposal: today's WholePlanResult cannot tell C which block was blocked.
    real = _load(PLAN_FAILURE / "whole_no_feasible_order_real_unpatched.json")
    assert real["calculation_status"] == "NO_FEASIBLE_ORDER"
    assert real["stage_errors"] == [{"code": "NO_FEASIBLE_ORDER", "reason": "NO_FEASIBLE_ORDER", "block": None}]


# ---------------------------------------------------------------------------
# Case A: "수정할게요" is a design-change request, so it must become REVISE (de59b08: KEEP via the Intervention phrase table)
# ---------------------------------------------------------------------------


def test_design_change_sujunghalgeyo_should_revise(mock_scenario, change_reason):
    envelope = main.run_design_change(mock_scenario["design"], mock_scenario["current"], reason=change_reason,
                                      text_answers=["수정할게요"])
    assert envelope["status"] == "OK"
    assert envelope["hri_result"] == dialogue.REVISE
    assert envelope["design"] is not None


def test_intervention_phrase_table_still_treats_sujunghalgeyo_as_keep():
    # The Intervention parser is untouched by Wave 3: "수정할게" still means "I will fix my misplaced block" there.
    assert "수정할게" in dialogue._INTERVENTION_PHRASES[dialogue.KEEP]
    assert dialogue.parse_response("수정할게요") == dialogue.KEEP
    assert dialogue.parse_design_change_response("수정할게요") == dialogue.REVISE


# ---------------------------------------------------------------------------
# Case B / C: a REVISE answer must produce a Revised Candidate that preserves the Current
# (de59b08: designer rejected differences=[] → escalation → UNCLEAR / DESIGN_GENERATION_FAILED)
# ---------------------------------------------------------------------------


def test_design_change_option2_should_build_revised_candidate(mock_scenario, change_reason):
    # Mock mode: a Candidate here is the Mock chair again (same blocks → version stays 1, see designer §4); what matters is
    # that the REVISE path completes with a design that preserves the Current, exactly as run_intervention does below.
    envelope = main.run_design_change(mock_scenario["design"], mock_scenario["current"], reason=change_reason,
                                      text_answers=["2번"])
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.REVISE
    assert envelope["design"] is not None
    assert validator.validate_revised({"blocks": envelope["design"]["blocks"]}, mock_scenario["current"]) == []


def test_design_change_forced_revise_should_not_fail_on_empty_differences(mock_scenario, change_reason):
    envelope = main.run_design_change(mock_scenario["design"], mock_scenario["current"], reason=change_reason,
                                      text_answers=["2번", "계속 찾아줘"])
    assert envelope["status"] == "OK"
    assert envelope["design"] is not None
    assert len(envelope["questions"]) == 1  # no escalation question any more: the second answer was never needed


def test_designer_difference_mode_still_rejects_empty_differences_but_design_change_mode_accepts(mock_scenario):
    # The Intervention input contract is unchanged; only the explicit design_change flag accepts an empty list.
    design, current = mock_scenario["design"], mock_scenario["current"]
    result = designer.build_revised_design(design, current, [], generate=None)
    assert result["design"] is None
    assert [r["message"] for r in result["reasons"]] == ["differences must not be empty"]
    accepted = designer.build_revised_design(design, current, [], generate=None, design_change=True)
    assert accepted["design"] is not None
    rejected = designer.build_revised_design(design, current, mock_scenario["differences"], generate=None, design_change=True)
    assert [r["message"] for r in rejected["reasons"]] == ["differences must be empty for a design change"]


# ---------------------------------------------------------------------------
# Case D and compatibility: what must survive the Wave 3 fix
# ---------------------------------------------------------------------------


def test_existing_difference_intervention_option2_is_revise_with_candidate(mock_scenario):
    envelope = main.run_intervention(mock_scenario["design"], mock_scenario["diff_current"], mock_scenario["differences"],
                                     text_answers=["2번"])
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.REVISE
    assert envelope["design"] is not None
    assert validator.validate_revised({"blocks": envelope["design"]["blocks"]}, mock_scenario["diff_current"]) == []


def test_existing_difference_intervention_sujunghalgeyo_stays_keep(approved, difference_scenario):
    # In a Difference Intervention "수정할게요" means "I will put the block back" and must remain KEEP after Wave 3.
    envelope = main.run_intervention(approved, difference_scenario["current"], difference_scenario["differences"],
                                     text_answers=["수정할게요"])
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.KEEP
    assert envelope["design"] == approved


def test_fixture_difference_scenario_is_accepted_by_intervention_input_check(approved, difference_scenario):
    # The fixture is a valid Intervention input; generating a Revised on it needs the LLM path (Mock generator is chair-only).
    assert validator.check_intervention_input(approved, difference_scenario["current"], difference_scenario["differences"]) == []
    assert any(r["rule"] == "connectivity" for r in designer.build_revised_design(
        approved, difference_scenario["current"], difference_scenario["differences"], generate=None)["reasons"])


def test_design_change_option1_is_keep_and_returns_approved_unchanged(approved, current, change_reason):
    # tests/unit/test_mvp_workflow.py relies on '1번' → KEEP; keep this compatibility in Wave 3.
    envelope = main.run_design_change(approved, current, reason=change_reason, text_answers=["1번"])
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.KEEP
    assert envelope["design"] == approved and envelope["design_metadata"] is None


def test_run_intervention_still_rejects_empty_differences(approved, current):
    envelope = main.run_intervention(approved, current, [], text_answers=["2번"])
    assert envelope["status"] == "FAILED" and envelope["error"]["code"] == "INVALID_INPUT"


def test_design_change_requires_a_reason(approved, current):
    assert main.run_design_change(approved, current, reason="", text_answers=["1번"])["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Planning-failure question wording (Wave 4 target, recorded now)
# ---------------------------------------------------------------------------


def test_plan_failure_question_should_not_read_machine_codes(approved, current):
    # de59b08: D passed str(A stage_errors) as `reason` and the question started with "[{'code': 'NO_FEASIBLE_ORDER', …}]".
    # Wave 4: a reason without Hangul is never spoken, and a planning_failure gets its own natural-language question.
    stage_errors = _load(PLAN_FAILURE / "whole_no_feasible_order_real_unpatched.json")["stage_errors"]
    envelope = main.run_design_change(approved, current, reason=str(stage_errors), text_answers=["1번"])
    question = envelope["questions"][0]
    assert "NO_FEASIBLE_ORDER" not in question and "[" not in question and "{" not in question
    assert question == dialogue.DESIGN_CHANGE_QUESTION
    failure = {"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True, "blocked_blocks": [], "detail": str(stage_errors)}
    spoken = main.run_design_change(approved, current, reason=str(stage_errors), planning_failure=failure,
                                    text_answers=["1번"])["questions"][0]
    assert spoken == dialogue.build_plan_failure_question(failure) and "로봇" in spoken and "NO_FEASIBLE_ORDER" not in spoken
