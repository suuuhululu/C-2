"""Full Voice HRI E2E harness (scripts/c_full_voice_hri_e2e.py) run offline: text mode, LLM stubbed, real A read-only.

Proves the one-command lifecycle (Initial → Direct Design Change → Difference → Planning failure → A replan) is wired
before the operator runs it with the real microphone: four previews, version chain v1→v2→v3→v4, Current preserved on
every Revised stage, planning-failure question without machine codes, robot_calls 0, replan_calls 1, files written.
The stubbed designs come from the Wave 1 fixture (canonical facing), re-coloured per stage so every REVISE is a new layout.
"""

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, validator

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
import c_full_voice_hri_e2e as harness  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "fixtures" / "c_design_change" / "approved_design.json"
JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True,
            "design_name": "후보", "design_family": "armchair", "why_it_is_complete": "ok", "visible_features": [],
            "change_summary": []}


def _recolour(blocks, current, pattern):
    """Current 밖 블록 중 layer % 3 == pattern인 블록의 노랑↔파랑을 뒤집는다(호출마다 다른 패턴 → 새 후보)."""
    kept = {(b["x"], b["y"], b["layer"]) for b in current}
    out = []
    for b in blocks:
        b = dict(b)
        if (b["x"], b["y"], b["layer"]) not in kept and b["layer"] % 3 == pattern and b["color"] in ("yellow", "blue"):
            b["color"] = "blue" if b["color"] == "yellow" else "yellow"
        out.append(b)
    return out


@pytest.fixture
def stubs(monkeypatch):
    calls = {"revised": []}
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(designer, "RICHNESS_MIN_DELTA", 0)
    monkeypatch.setattr(llm, "interpret_initial_request", lambda text, should_stop=None: {
        "object": "CHAIR", "preference": "ANY", "family": None, "style_hint": "", "sufficient": True, "follow_up": "", "reply": "좋아요."})
    monkeypatch.setattr(llm, "choose_initial_family", lambda preference, rng=None: "armchair")
    monkeypatch.setattr(llm, "generate_initial_design", lambda object_type, reasons=None, should_stop=None, **kw:
                        {"blocks": deepcopy(fixture["blocks"])})
    monkeypatch.setattr(llm, "describe_initial_design", lambda design, should_stop=None, family=None, concept=None: {
        "design_family": "armchair", "design_name": "후보", "design_summary": "요약", "visible_features": [],
        "silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4, "family_design_match": "clear"})

    def generate_revised(design, current, differences, reasons=None, **kwargs):
        calls["revised"].append(kwargs)
        # Current(놓인 블록 그대로) + Approved의 나머지 블록을 이번 stage 패턴으로 다시 칠한다(기하 동일 → validator 통과).
        upper = [b for b in design["blocks"] if b["layer"] != 1]
        candidate = [dict(b) for b in current] + _recolour(upper, current, len(calls["revised"]) % 3)
        return {"blocks": candidate}
    monkeypatch.setattr(llm, "generate_revised_design", generate_revised)
    monkeypatch.setattr(llm, "interpret_intervention_answer",
                        lambda text, differences, should_stop=None, context=None, planning_failure=None:
                        {"decision": "REVISE", "style_hint": "등받이를 더 높게", "reason": "r", "reply": "조립된 부분은 두고 다시 만들어볼게요."})
    monkeypatch.setattr(llm, "interpret_review_answer", lambda text, kind, should_stop=None, context=None:
                        {"decision": "UNCLEAR" if "글쎄" in text else "APPROVE", "style_hint": "", "scope": "", "concept": "",
                         "reason": "r", "reply": "" if "글쎄" in text else "이 디자인으로 진행할게요."})
    monkeypatch.setattr(llm, "judge_revised_design", lambda *a, **k: deepcopy(JUDGE_OK))
    return calls


def test_full_lifecycle_offline(stubs, tmp_path):
    out = str(tmp_path / "full_hri")
    code = harness.main_cli(["--mode", "text", "--out", out, "--answers", *harness.DEFAULT_ANSWERS])
    summary = json.loads((tmp_path / "full_hri" / "summary.json").read_text(encoding="utf-8"))
    assert summary["final"] == "PASS" and code == 0, summary["checks"]
    assert summary["versions"] == [1, 2, 3, 4]
    assert summary["robot_calls"] == 0 and summary["replan_calls"] == 1
    assert [p["stage"] for p in summary["previews"]] == ["initial", "design_change", "difference", "plan_failure"]
    for name in ("events.jsonl", "01_initial.json", "02_initial_review.json", "03_design_change.json", "04_design_change_review.json",
                 "05_difference.json", "06_difference_review.json", "07_plan_failure.json", "08_plan_failure_review.json",
                 "preview_initial.png", "preview_design_change.png", "preview_difference.png", "preview_plan_failure.png"):
        assert (tmp_path / "full_hri" / name).exists(), name
    stages = summary["stages"]
    assert stages["design_change"]["request"] == "등받이를 조금 더 높이고 싶어"
    assert stages["design_change"]["run_design_change"]["hri"] == dialogue.REVISE
    assert stages["difference"]["run_intervention"]["hri"] == dialogue.REVISE
    assert stages["plan_failure"]["run_design_change"]["hri"] == dialogue.REVISE
    for stage in ("design_change", "difference", "plan_failure"):
        for api, row in stages[stage].items():
            if isinstance(row, dict) and "current_preserved" in row:
                assert row["current_preserved"] is True and row["validator"] == "PASS" and row["facing"] in ("PASS", "FOLLOWS_CURRENT")
    assert stages["plan_failure"]["planning_failure"]["failure_code"] == "NO_FEASIBLE_ORDER"
    assert stages["plan_failure"]["replan"]["calculation_status"] in ("COMPLETED", "NO_FEASIBLE_ORDER", "SEARCH_LIMIT")
    questions = stages["plan_failure"]["run_design_change"]["questions"]
    assert questions and "NO_FEASIBLE_ORDER" not in questions[0] and "로봇" in questions[0]
    assert any("no feasible assembly order" in (k.get("change_request") or "") for k in stubs["revised"])
    approved = json.loads((tmp_path / "full_hri" / "08_plan_failure_review.json").read_text(encoding="utf-8"))["design"]
    assert validator.validate_design(approved) == [] and approved["design_version"] == 4


def test_unclear_stops_the_stage_without_approval(stubs, tmp_path):
    out = str(tmp_path / "full_hri_unclear")
    answers = list(harness.DEFAULT_ANSWERS)
    answers[1] = "글쎄"  # Initial review: UNCLEAR (rule and LLM) → re-ask has no answer → stage stops, nothing approved
    code = harness.main_cli(["--mode", "text", "--out", out, "--answers", *answers])
    summary = json.loads((tmp_path / "full_hri_unclear" / "summary.json").read_text(encoding="utf-8"))
    assert code == 1 and summary["final"] == "FAIL"
    assert summary["versions"] == [None, None, None, None] and summary["robot_calls"] == 0 and summary["replan_calls"] == 0
    assert summary["stages"]["initial"]["review_design_candidate#1"]["hri"] == dialogue.UNCLEAR
