"""Wave 5: A planning failure → C design-change HRI → Revised Candidate → Preview → APPROVE → A replan (offline).

Drives the fake D caller of scripts/c_stage3_integration_smoke.py (`--scenario plan-failure`) and the real C public API.
A is the real planning_trial.assembly_adapter.handle_whole_plan (read-only calculation with the D MVP FAKE settings; the
Wave 1 fixture Design really returns NO_FEASIBLE_ORDER). Only C's LLM functions are stubbed (LLM mode) so a Revised
Candidate v2 can be produced without the network; voice is never touched (tests/conftest.py guard). No Robot, no
Camera, no DB: the caller counts robot_calls and replan_calls instead.
"""

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, main, validator

PLAN_FAILURE = Path(__file__).parents[1] / "fixtures" / "c_plan_failure"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "unit", "c_design"))
import c_stage3_integration_smoke as runner  # noqa: E402
import c_facing_helper as facing  # noqa: E402

JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True,
            "design_name": "순서 가능한 의자", "design_family": "chair", "why_it_is_complete": "ok", "visible_features": ["tall back"],
            "change_summary": ["등받이 재배치"]}


def _taller(approved):
    blocks = [b for b in approved["blocks"] if b["layer"] != 5]
    blocks += [dict(brick_type="2x2x1", color="blue", x=8, y=y, layer=5, orientation_deg=0) for y in (8, 10, 12)]
    assert validator.validate_design({"design_version": 1, "blocks": blocks}) == []
    return {"blocks": blocks}


class StubLLM:
    """C llm 대역(LLM 모드): 해석은 결정론적 JSON, 생성은 fixture 기반 유효 Revised 후보, judge는 SHOWCASE."""

    def __init__(self, approved, *, candidate=None):
        self.candidate = candidate or _taller(approved)
        self.generate_calls, self.interpret_calls, self.review_calls = [], [], []

    def generate_revised_design(self, design, current, differences, reasons=None, **kwargs):
        self.generate_calls.append(kwargs)
        return deepcopy(self.candidate)

    def interpret_intervention_answer(self, text, differences, should_stop=None, context=None, planning_failure=None):
        self.interpret_calls.append({"text": text, "context": context, "planning_failure": planning_failure})
        decision = dialogue.REVISE if "수정" in text or "바꿔" in text else dialogue.KEEP if "기존" in text else dialogue.UNCLEAR
        return {"decision": decision, "style_hint": "막힌 부분 재배치" if decision == dialogue.REVISE else "", "reason": "r",
                "reply": "조립된 부분은 두고 다시 만들어볼게요." if decision == dialogue.REVISE else ""}

    def interpret_review_answer(self, text, kind, should_stop=None, context=None):
        self.review_calls.append({"text": text, "kind": kind})
        decision = dialogue.APPROVE if "좋아" in text or "이대로" in text else dialogue.UNCLEAR
        return {"decision": decision, "style_hint": "", "scope": "", "concept": "", "reason": "r", "reply": "이 디자인으로 진행할게요."}

    def judge_revised_design(self, *args, **kwargs):
        return deepcopy(JUDGE_OK)


@pytest.fixture
def approved():
    return runner._fixture("approved_design.json")


@pytest.fixture
def stub(monkeypatch, approved):
    stub = StubLLM(approved)
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(designer, "revised_min_blocks", lambda design: len(design["blocks"]))
    for name in ("generate_revised_design", "interpret_intervention_answer", "interpret_review_answer", "judge_revised_design"):
        monkeypatch.setattr(llm, name, getattr(stub, name))
    return stub


def _caller(answers, tmp_path):
    return runner.FakeDCaller("text", runner.AnswerFeed(list(answers)), None, str(tmp_path))


def _run(caller, blocked_block=False):
    runner.run_scenario(caller, "plan-failure", blocked_block=blocked_block)
    return caller


# ---------------------------------------------------------------------------
# Scenario 1 — NO_FEASIBLE_ORDER → REVISE → Candidate v2 → Preview → APPROVE → A replan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blocked_block", [False, True])
def test_scenario1_revise_candidate_preview_approve_replan(stub, approved, tmp_path, blocked_block):
    caller = _run(_caller(["응, 수정해줘", "좋아, 이대로 해"], tmp_path), blocked_block=blocked_block)
    first, failure = caller.planning["first"], caller.planning["failure"]
    # Real A is called read-only; since PR #28 (complete-order search) it plans this fixture (READY), so the caller injects
    # the Wave 1 stored NO_FEASIBLE_ORDER result as the failure D would hand over. Either way: no execution, one failure.
    assert first["execution_allowed"] is False and first["calculation_status"] in ("COMPLETED", "NO_FEASIBLE_ORDER")
    assert caller.planning["failure_source"] in ("real A result", "fixture (real A returned READY)")
    assert failure["failure_code"] == "NO_FEASIBLE_ORDER" and failure["redesign_required"] is True
    assert len(failure["blocked_blocks"]) == (1 if blocked_block else 0)

    change, review = caller.rows[0], caller.rows[1]
    assert change["api"] == "run_design_change" and change["status"] == "OK" and change["hri"] == dialogue.REVISE
    question = caller.planning["c_result"]["questions"][0]
    assert question == dialogue.build_plan_failure_question(failure)
    assert "NO_FEASIBLE_ORDER" not in question and "[" not in question and "로봇" in question
    if blocked_block:
        block = failure["blocked_blocks"][0]
        assert f"(x={block['x']}, y={block['y']}) {block['layer']}층 블록" in question
    assert change["design_version"] == approved["design_version"] + 1 and change["validator"] == "PASS"
    assert change["current_preserved"] is True

    assert review["api"] == "review_design_candidate" and review["kind"] == "revised" and review["hri"] == dialogue.APPROVE
    assert review["design_version"] == 2 and review["round"] == 0  # no MODIFY: round stays 0
    assert caller.approved["design_version"] == 2 and caller.candidate[0] == caller.approved
    assert all(block in caller.approved["blocks"] for block in caller.current)
    assert facing.classify_facing(caller.approved, current=caller.current)[0] in (facing.PASS, facing.FOLLOWS_CURRENT)
    assert "planning_failure" not in caller.approved and set(caller.approved) == {"design_version", "blocks"}

    # review got the full context (metadata, previous design, current, change_reason, planning_failure)
    assert stub.review_calls[0]["kind"] == "revised"
    assert stub.generate_calls[0]["change_request"] == llm.planning_failure_change_request(failure)
    assert stub.interpret_calls[0]["planning_failure"] == failure and "planning_failure" not in (stub.interpret_calls[0]["context"] or {})

    replan = caller.planning["replan"]
    assert caller.replan_calls == 1 and caller.robot_calls == 0 and caller.state == "REPLANNED"
    assert replan["calculation_status"] in ("COMPLETED", "NO_FEASIBLE_ORDER", "SEARCH_LIMIT") and replan["execution_allowed"] is False
    assert [row["api"] for row in caller.rows] == ["run_design_change", "review_design_candidate"]


def test_scenario1_metadata_survives_review(stub, approved, tmp_path):
    caller = _run(_caller(["응, 수정해줘", "좋아, 이대로 해"], tmp_path))
    meta = caller.candidate[1]
    assert meta["source"] == "LLM" and meta["judge"]["verdict"] == "SHOWCASE" and meta["style_hint"] == "막힌 부분 재배치"
    assert meta["review"]["decision"] == dialogue.APPROVE and meta["review"]["round"] == 0 and meta["review"]["kind"] == "revised"


# ---------------------------------------------------------------------------
# Scenario 2 — KEEP → HOLD, no replan, no robot
# ---------------------------------------------------------------------------


def test_scenario2_keep_holds_without_replan(stub, approved, tmp_path):
    caller = _run(_caller(["아니, 기존 설계로 할래"], tmp_path))
    assert caller.rows[0]["hri"] == dialogue.KEEP and caller.rows[0]["status"] == "OK"
    assert caller.approved == approved and caller.candidate is None
    assert caller.state == "HOLD" and caller.replan_calls == 0 and caller.robot_calls == 0
    assert stub.generate_calls == [] and "replan" not in caller.planning


# ---------------------------------------------------------------------------
# Scenario 3 — UNCLEAR → re-ask, state preserved
# ---------------------------------------------------------------------------


def test_scenario3_unclear_reasks_and_preserves_state(stub, approved, tmp_path):
    caller = _run(_caller(["무슨 뜻이야?"], tmp_path))
    result = caller.planning["c_result"]
    assert result["hri"] == dialogue.UNCLEAR and caller.rows[0]["design_version"] is None
    assert len(result["questions"]) == 2 and result["questions"][1] == dialogue.build_design_change_reask(result["questions"][0])
    assert caller.approved == approved and caller.candidate is None
    assert caller.state == "HOLD" and caller.replan_calls == 0 and caller.robot_calls == 0 and stub.generate_calls == []


# ---------------------------------------------------------------------------
# Scenario 4 — SEARCH_LIMIT wrongly sent to C → refused, no question, no candidate
# ---------------------------------------------------------------------------


def test_scenario4_search_limit_is_refused_by_c(stub, approved, tmp_path):
    caller = _caller(["응, 수정해줘"], tmp_path)
    caller.approved, caller.current = approved, runner._fixture("current_prefix.json")
    asked = []
    failure = {"failure_code": "SEARCH_LIMIT", "redesign_required": True, "retryable": True, "blocked_blocks": []}
    envelope = main.run_design_change(caller.approved, caller.current, reason="PLANNING_FAILURE", planning_failure=failure,
                                      text_answers=["응, 수정해줘"], on_question=asked.append)
    assert envelope["status"] == "FAILED" and envelope["error"]["code"] == "PLANNING_FAILURE_NOT_REDESIGN"
    assert envelope["questions"] == [] and asked == [] and envelope["design"] is None
    assert stub.generate_calls == [] and stub.interpret_calls == []
    assert caller.approved == approved and caller.replan_calls == 0 and caller.robot_calls == 0


# ---------------------------------------------------------------------------
# Scenario 5 — Candidate generation fails → Approved/Current preserved, no replan, no robot
# ---------------------------------------------------------------------------


def test_scenario5_candidate_failure_keeps_approved(monkeypatch, stub, approved, tmp_path):
    broken = {"blocks": [dict(b, color="red") for b in approved["blocks"]]}  # red is only 1x2x1 → validator rejects every attempt
    monkeypatch.setattr(llm, "generate_revised_design", lambda *a, **k: deepcopy(broken))
    # Through the fake D caller (one text answer per call): six rejected attempts → §8.11 escalation question, which has no
    # answer left → OK / UNCLEAR, no Candidate. Approved and Current untouched, review never called, no replan, no robot.
    caller = _run(_caller(["응, 수정해줘", "좋아, 이대로 해"], tmp_path))
    row = caller.rows[0]
    assert row["status"] == "OK" and row["hri"] == dialogue.UNCLEAR and row["design_version"] is None
    questions = caller.planning["c_result"]["questions"]
    assert len(questions) == 2 and "계속 새 설계를 찾아볼까요" in questions[1]
    assert caller.approved == approved and caller.current == runner._fixture("current_prefix.json")
    assert caller.candidate is None and caller.state == "HOLD"
    assert caller.replan_calls == 0 and caller.robot_calls == 0 and "replan" not in caller.planning
    assert len(caller.rows) == 1  # review never called
    # Directly on C with the escalation answered "keep searching": the attempt limit ends in FAILED / DESIGN_GENERATION_FAILED.
    failure = caller.planning["failure"]
    envelope = main.run_design_change(approved, caller.current, reason="PLANNING_FAILURE", planning_failure=failure,
                                      text_answers=["응, 수정해줘", "계속 찾아줘"])
    assert envelope["status"] == "FAILED" and envelope["error"]["code"] == "DESIGN_GENERATION_FAILED"
    assert envelope["hri_result"] == dialogue.REVISE and envelope["design"] is None
    assert caller.approved == approved  # the caller never adopts a FAILED envelope


# ---------------------------------------------------------------------------
# Scenario 6 — Preview ordering and stale approval
# ---------------------------------------------------------------------------


def test_scenario6_review_before_preview_ready_is_refused(stub, approved, tmp_path):
    caller = _caller(["응, 수정해줘", "좋아, 이대로 해"], tmp_path)
    caller.approved, caller.current, caller.differences = approved, runner._fixture("current_prefix.json"), []
    envelope = main.run_design_change(caller.approved, caller.current, reason="PLANNING_FAILURE",
                                      planning_failure={"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True},
                                      text_answers=["응, 수정해줘"])
    caller.candidate, caller.candidate_phase = (envelope["design"], envelope["design_metadata"]), "PREVIEW"
    with pytest.raises(RuntimeError, match="before PREVIEW_READY"):
        caller.review("revised", extra={"differences": [], "change_reason": "PLANNING_FAILURE"})
    assert caller.approved == approved and caller.replan_calls == 0


def test_scenario6_stale_approval_is_refused(monkeypatch, stub, approved, tmp_path):
    caller = _caller(["응, 수정해줘", "좋아, 이대로 해"], tmp_path)
    assert caller.plan_failure() is True
    displayed = deepcopy(caller.candidate[0])
    real_review = main.review_design_candidate

    def stale(candidate, **kwargs):  # APPROVE that carries a different design than the one displayed
        envelope = real_review(candidate, **kwargs)
        envelope["design"] = {"design_version": 2, "blocks": _taller(approved)["blocks"][:-1] + [dict(brick_type="2x2x1", color="yellow", x=8, y=12, layer=5, orientation_deg=0)]}
        return envelope
    monkeypatch.setattr(main, "review_design_candidate", stale)
    assert caller.review("revised", extra={"differences": [], "change_reason": "PLANNING_FAILURE"}) is False
    assert caller.approved == approved and caller.candidate[0] == displayed and caller.replan_calls == 0


# ---------------------------------------------------------------------------
# Scenario 7 — STOP during the dialogue and a late result after STOP
# ---------------------------------------------------------------------------


def test_scenario7_stop_cancels_and_late_result_is_ignored(stub, approved, tmp_path):
    current = runner._fixture("current_prefix.json")
    failure = {"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True, "blocked_blocks": []}
    stopped = {"flag": False}

    def should_stop():
        return stopped["flag"]
    stopped["flag"] = True  # STOP arrives before the first turn
    envelope = main.run_design_change(approved, current, reason="PLANNING_FAILURE", planning_failure=failure,
                                      text_answers=["응, 수정해줘"], should_stop=should_stop)
    assert envelope["status"] == "CANCELLED" and envelope["error"]["code"] == "STOPPED" and envelope["design"] is None

    # late result: a REVISE envelope that arrives after D stopped must not become a Candidate or trigger a replan
    caller = _caller([], tmp_path)
    caller.approved, caller.current, caller.state = approved, current, "STOPPED"
    stopped["flag"] = False
    late = main.run_design_change(approved, current, reason="PLANNING_FAILURE", planning_failure=failure, text_answers=["응, 수정해줘"])
    assert late["status"] == "OK" and late["hri_result"] == dialogue.REVISE
    if caller.state == "STOPPED":  # D-side guard (mirrors mvp_workflow LATE_RESULT_IGNORED): nothing adopted
        ignored = True
    assert ignored and caller.candidate is None and caller.approved == approved
    assert caller.replan_calls == 0 and caller.robot_calls == 0


# ---------------------------------------------------------------------------
# Question wording in both fixture shapes, straight from the D-side builder
# ---------------------------------------------------------------------------


def test_planning_failure_from_stored_a_result_has_no_block_and_speaks_the_general_sentence(approved):
    # The Wave 1 stored A result (de59b08: NO_FEASIBLE_ORDER with block null) is what D would convert; the live A after
    # PR #28 plans this fixture instead, which the caller records as the real first result.
    stored = _load(PLAN_FAILURE / "whole_no_feasible_order_real_unpatched.json")
    summary = {"calculation_status": stored["calculation_status"], "stage_errors": stored["stage_errors"]}
    failure = runner.planning_failure_from(summary)
    assert summary["calculation_status"] == "NO_FEASIBLE_ORDER" and failure["blocked_blocks"] == []
    assert validator.check_planning_failure(failure) == []
    assert dialogue.build_plan_failure_question(failure).split("\n")[0] == dialogue.PLAN_FAILURE_GENERAL
    assert "NO_FEASIBLE_ORDER" in failure["detail"]  # diagnostics only, never spoken
    live = runner.a_whole_plan(approved, runner._fixture("current_prefix.json"), generation=1)
    assert live["execution_allowed"] is False  # read-only either way
