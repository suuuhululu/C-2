"""Direct Design Change (Wave 3, 2026-10-12; docs/C_DESIGN_CONTRACT.md §4.6).

Covers the design-change mode of app.c_design: its own question, rule table, LLM prompt dispatch, input check, Revised
generation message, Candidate version policy and metadata through Preview review. The Difference Intervention tables and
prompts are asserted unchanged. No real LLM/STT/TTS (conftest guard); LLM mode uses stubs.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, main, validator

FIXTURES = Path(__file__).parents[2] / "fixtures" / "c_design_change"
JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True,
            "design_name": "높은 등받이 의자", "design_family": "chair", "why_it_is_complete": "등받이가 더 높다",
            "visible_features": ["tall back"], "change_summary": ["등받이 한 층 추가"]}


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def approved():
    return _load("approved_design.json")


@pytest.fixture
def current():
    return _load("current_prefix.json")


@pytest.fixture
def change_reason():
    return _load("design_change_request.json")["reason"]


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    monkeypatch.setattr(designer, "RETRY_DELAY", 0)


def _taller(approved):
    """A valid Revised layout for the fixture: the layer-5 crown becomes a full-width layer-5 backrest row (Current preserved).

    The middle 2x2 bridges the two backrest columns (in the fixture only the crown joined them), so connectivity holds.
    """
    blocks = [b for b in approved["blocks"] if b["layer"] != 5]
    blocks += [dict(brick_type="2x2x1", color="blue", x=8, y=y, layer=5, orientation_deg=0) for y in (8, 10, 12)]
    design = {"design_version": 1, "blocks": blocks}
    assert validator.validate_design(design) == []
    return {"blocks": blocks}


# ---------------------------------------------------------------------------
# A. rule table — design-change parser is its own table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "수정할게요", "수정해줘", "바꿔줘", "새 설계로 해줘", "등받이를 높여줘", "팔걸이를 추가해줘",
    "현재 상태를 반영해서 다시 만들어줘", "2번", "응, 바꿔줘", "네, 수정해줘", "그대로 두지 말고 바꿔줘",
])
def test_design_change_revise_phrases(text):
    assert dialogue.parse_design_change_response(text) == dialogue.REVISE


@pytest.mark.parametrize("text", [
    "그대로 갈게", "원래 설계 유지해", "바꾸지 마", "수정하지 마", "고치지 마", "지금 설계 그대로 해", "이대로 갈게",
    "1번", "아니, 안 바꿀게", "수정하지 않을래", "변경하지 마세요",
])
def test_design_change_keep_phrases(text):
    assert dialogue.parse_design_change_response(text) == dialogue.KEEP


@pytest.mark.parametrize("text", ["음...", "글쎄", "모르겠어", "무슨 뜻이야", "네", "아니"])
def test_design_change_unclear_without_llm(text):
    # Two-way question: a bare yes/no does not decide; without an LLM fallback it is UNCLEAR (re-ask).
    assert dialogue.parse_design_change_response(text) == dialogue.UNCLEAR


def test_design_change_unclear_goes_to_llm_fallback_only_when_rules_cannot_decide():
    calls = []

    def fallback(text):
        calls.append(text)
        return dialogue.REVISE
    assert dialogue.parse_design_change_response("무슨 뜻이야", fallback) == dialogue.REVISE
    assert dialogue.parse_design_change_response("수정하지 마", fallback) == dialogue.KEEP
    assert calls == ["무슨 뜻이야"]


def test_design_change_cancel_and_negated_cancel():
    assert dialogue.parse_design_change_response("취소할게") == dialogue.CANCEL
    assert dialogue.parse_design_change_response("취소하지 말고 바꿔줘") == dialogue.REVISE


def test_intervention_table_and_prompt_are_unchanged_by_design_change_mode():
    # Same utterances, opposite meanings: the two tables must not be shared.
    assert dialogue.parse_response("수정할게요") == dialogue.KEEP
    assert dialogue.parse_response("이대로 해줘") == dialogue.REVISE
    assert dialogue.parse_design_change_response("이대로 해줘") == dialogue.KEEP
    assert "수정할게" in dialogue._INTERVENTION_PHRASES[dialogue.KEEP]
    assert "수정" not in dialogue._DESIGN_CHANGE_PHRASES[dialogue.KEEP]
    assert "no block is misplaced" in llm.SYSTEM_PROMPT_DESIGN_CHANGE_ANSWER
    assert "A block was placed differently" in llm.SYSTEM_PROMPT_INTERVENTION_ANSWER
    assert "A block was placed differently" not in llm.SYSTEM_PROMPT_DESIGN_CHANGE_ANSWER


# ---------------------------------------------------------------------------
# question / re-ask / acknowledgement sentences
# ---------------------------------------------------------------------------


def test_design_change_question_is_open_two_way_and_hides_code_tokens():
    plain = dialogue.build_design_change_question("USER_DESIGN_CHANGE")
    assert plain == dialogue.DESIGN_CHANGE_QUESTION
    assert "USER_DESIGN_CHANGE" not in plain and "수정할까요" not in plain
    assert "그대로" in plain and "바꿀까요" in plain and "번" not in plain
    spoken = dialogue.build_design_change_question("로봇이 다음 블록을 놓기 전에 설계를 바꿀 수 있어요.")
    assert spoken.split("\n") == ["로봇이 다음 블록을 놓기 전에 설계를 바꿀 수 있어요.", dialogue.DESIGN_CHANGE_QUESTION]


def test_design_change_reask_repeats_the_two_choices_and_the_question():
    question = dialogue.build_design_change_question(None)
    reask = dialogue.build_design_change_reask(question)
    assert reask.startswith(dialogue.DESIGN_CHANGE_REASK_LEAD) and reask.endswith(question)
    assert "실수로 놓으신" not in reask  # the Intervention re-ask wording is not reused


@pytest.mark.parametrize("options", [dialogue.DESIGN_CHANGE_KEEP_ACKS, dialogue.DESIGN_CHANGE_REVISE_ACKS])
def test_design_change_ack_candidates_are_polite_and_about_the_design(options):
    assert 3 <= len(options) <= 4
    for sentence in options:
        assert sentence.endswith("요.") and "자리로" not in sentence
    assert dialogue.design_change_keep_ack() in dialogue.DESIGN_CHANGE_KEEP_ACKS
    assert dialogue.design_change_revise_ack_fallback() in dialogue.DESIGN_CHANGE_REVISE_ACKS
    assert "등받이를 더 높게" in dialogue.design_change_revise_ack_fallback("등받이를 더 높게")


# ---------------------------------------------------------------------------
# validator wrapper and designer flag
# ---------------------------------------------------------------------------


def test_check_design_change_input_bundles_design_and_current_checks(approved, current):
    assert validator.check_design_change_input(approved, current) == []
    bad_design = {"design_version": 1, "blocks": approved["blocks"] + [dict(approved["blocks"][0])]}
    assert any(r["rule"] == "overlap" for r in validator.check_design_change_input(bad_design, current))
    assert validator.check_design_change_input(approved, [current[0], dict(current[0])]) != []
    assert validator.check_design_change_input(approved, "not a list")[0]["rule"] == "invalid_type"
    # Same rules as the Intervention check minus the Difference part: no new or relaxed rule.
    assert (validator.check_design_change_input(bad_design, current)
            == validator.check_intervention_input(bad_design, current, [])[:-1])


def test_main_does_not_call_private_validator_helpers():
    source = (Path(main.__file__)).read_text(encoding="utf-8")
    assert "validator._check_current" not in source


# ---------------------------------------------------------------------------
# B. direct Design Change in Mock mode (envelope, KEEP/REVISE, Current, on_progress)
# ---------------------------------------------------------------------------


def _mock_chair():
    design = designer.build_initial_design("CHAIR")["design"]
    return design, [dict(b) for b in design["blocks"] if b["layer"] == 1]


def test_mock_keep_returns_approved_unchanged_and_no_metadata(monkeypatch, change_reason):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    design, current = _mock_chair()
    events = []
    envelope = main.run_design_change(design, current, reason=change_reason, text_answers=["그대로 갈게"],
                                      on_progress=events.append)
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.KEEP
    assert envelope["design"] == design and envelope["design_metadata"] is None
    assert events == []  # Mock KEEP: no stages, same as run_intervention


def test_mock_revise_builds_candidate_with_current_preserved_and_progress(monkeypatch, change_reason):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    design, current = _mock_chair()
    events = []
    envelope = main.run_design_change(design, current, reason=change_reason, text_answers=["등받이를 높여줘"],
                                      on_progress=events.append)
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.REVISE
    assert validator.validate_revised({"blocks": envelope["design"]["blocks"]}, current) == []
    assert envelope["design_metadata"]["source"] == "MOCK"
    assert [e["stage"] for e in events] == ["GENERATING_REVISED", "VALIDATING", "READY_REVISED"]
    assert all(set(e) == {"stage", "message", "at"} and e["stage"] in main.PROGRESS_STAGES for e in events)


def test_mock_unclear_reasks_with_design_change_wording_then_runs_out(monkeypatch, change_reason):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    design, current = _mock_chair()
    envelope = main.run_design_change(design, current, reason=change_reason, text_answers=["글쎄"])
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.UNCLEAR and envelope["design"] is None
    question = dialogue.build_design_change_question(change_reason)  # the sentence-like reason is read first
    assert envelope["questions"] == [question, dialogue.build_design_change_reask(question)]
    assert main.run_design_change(design, current, reason="USER_DESIGN_CHANGE", text_answers=["글쎄"])["questions"][0] \
        == dialogue.DESIGN_CHANGE_QUESTION


def test_input_failures_use_the_design_change_check(approved, current, change_reason):
    broken = {"design_version": 1, "blocks": approved["blocks"] + [dict(approved["blocks"][0])]}
    envelope = main.run_design_change(broken, current, reason=change_reason, text_answers=["1번"])
    assert envelope["status"] == "FAILED" and envelope["error"]["code"] == "INVALID_INPUT"
    assert any(r["rule"] == "overlap" for r in envelope["error"]["details"])
    assert main.run_design_change(approved, current, reason="   ", text_answers=["1번"])["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# LLM mode: prompt dispatch, Revised message, version and metadata through Preview review
# ---------------------------------------------------------------------------


def test_interpret_design_change_answer_uses_its_own_prompt_and_keeps_context(monkeypatch):
    seen = []

    def fake_json_call(system_prompt, user_message, should_stop, model=None):
        seen.append((system_prompt, json.loads(user_message.split("\n", 1)[1])))
        return {"decision": "REVISE", "style_hint": "등받이를 더 높게", "reason": "r", "reply": "p"}
    monkeypatch.setattr(llm, "_json_call", fake_json_call)
    context = {"expected": {"blocks": []}, "difference": None, "observation": None, "reason": "USER_DESIGN_CHANGE"}
    out = llm.interpret_design_change_answer("등받이를 더 높여줘", "USER_DESIGN_CHANGE", context=context)
    assert out["decision"] == "REVISE"
    system, payload = seen[0]
    assert system == llm.SYSTEM_PROMPT_DESIGN_CHANGE_ANSWER
    assert payload["differences"] == [] and payload["inspection_context"]["change_reason"] == "USER_DESIGN_CHANGE"
    assert payload["inspection_context"]["expected"] == context["expected"]
    # Difference interpretation is untouched: same entry, Intervention prompt, no change_reason.
    llm.interpret_intervention_answer("일부러 놨어요", [{"expected": None, "actual": None}], context=context)
    assert seen[1][0] == llm.SYSTEM_PROMPT_INTERVENTION_ANSWER


def test_revised_message_design_change_variant_and_difference_variant_unchanged(approved, current, change_reason):
    change = llm._revised_user_message(approved, current, [], [], change_request=change_reason)
    assert "User requested change" in change and change_reason in change
    assert "Differences (expected vs actual)" not in change and llm._REVISED_DIFFERENCE_NOTE not in change
    assert "The user chose REVISE" not in change and "no misplaced block" in change
    assert llm._REVISED_DESIGN_CHANGE_NOTE in change and _current_line(current) in change
    diff = [{"expected": approved["blocks"][0], "actual": None}]
    before = llm._revised_user_message(approved, current, diff, [])
    assert before.startswith("The user chose REVISE.") and "Differences (expected vs actual)" in before
    assert llm._REVISED_GUIDANCE in before and llm._REVISED_DIFFERENCE_NOTE in llm._REVISED_GUIDANCE
    assert llm._REVISED_GUIDANCE.endswith(llm._REVISED_CLOSING) and "misplaced block" in llm._REVISED_GUIDANCE


def _current_line(current):
    return json.dumps(current, ensure_ascii=False)


def _llm_stubs(monkeypatch, approved, taller, *, decision="REVISE", hint="등받이를 더 높게"):
    calls = {"generate": [], "interpret": [], "review": []}

    def generate(design, current, differences, reasons=None, **kwargs):
        calls["generate"].append(kwargs)
        return deepcopy(taller)

    def interpret(text, differences, should_stop=None, context=None):
        calls["interpret"].append(context)
        return {"decision": decision, "style_hint": hint, "reason": "이해했어요.", "reply": "조립된 부분은 두고 바꿔볼게요."}

    def review(text, kind, should_stop=None, context=None):
        calls["review"].append(text)
        return {"decision": "MODIFY", "style_hint": "더 높게", "scope": "patch", "concept": "", "reason": "r", "reply": "p"}
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(llm, "generate_revised_design", generate)
    monkeypatch.setattr(llm, "interpret_intervention_answer", interpret)
    monkeypatch.setattr(llm, "interpret_review_answer", review)
    monkeypatch.setattr(llm, "judge_revised_design", lambda *a, **k: deepcopy(JUDGE_OK))
    monkeypatch.setattr(designer, "revised_min_blocks", lambda design: len(design["blocks"]))
    return calls


def test_llm_revise_candidate_is_v2_preserves_current_and_sends_change_request(monkeypatch, approved, current, change_reason):
    taller = _taller(approved)
    calls = _llm_stubs(monkeypatch, approved, taller)
    events = []
    envelope = main.run_design_change(approved, current, reason=change_reason, text_answers=["수정할게요"],
                                      on_progress=events.append, inspection_context={"reason": change_reason})
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.REVISE
    assert envelope["design"]["design_version"] == approved["design_version"] + 1
    assert validator.validate_revised({"blocks": envelope["design"]["blocks"]}, current) == []
    assert all(b in envelope["design"]["blocks"] for b in current)
    assert calls["generate"][0]["change_request"] == change_reason and calls["generate"][0]["style_hint"] == "등받이를 더 높게"
    assert calls["interpret"][0]["change_reason"] == change_reason and calls["interpret"][0]["reason"] == change_reason
    stages = [e["stage"] for e in events]
    assert stages[:4] == ["UNDERSTANDING", "HRI_INTERPRET", "ACK", "GENERATING_REVISED"] and stages[-1] == "READY_REVISED"
    assert [e["message"] for e in events if e["stage"] == "ACK"] == ["조립된 부분은 두고 바꿔볼게요."]
    meta = envelope["design_metadata"]
    assert meta["source"] == "LLM" and meta["style_hint"] == "등받이를 더 높게" and meta["judge"]["verdict"] == "SHOWCASE"


def test_llm_keep_uses_design_change_ack(monkeypatch, approved, current, change_reason):
    _llm_stubs(monkeypatch, approved, _taller(approved), decision="KEEP", hint="")
    events = []
    envelope = main.run_design_change(approved, current, reason=change_reason, text_answers=["음, 그냥 두는 게 낫겠어"],
                                      on_progress=events.append)
    assert envelope["hri_result"] == dialogue.KEEP and envelope["design"] == approved
    ack = next(e["message"] for e in events if e["stage"] == "KEEP_ACK")
    assert ack in dialogue.DESIGN_CHANGE_KEEP_ACKS


def test_candidate_review_modify_keeps_v2_and_round_then_approve(monkeypatch, approved, current, change_reason):
    taller = _taller(approved)
    calls = _llm_stubs(monkeypatch, approved, taller)
    first = main.run_design_change(approved, current, reason=change_reason, text_answers=["2번"])
    candidate, meta = first["design"], first["design_metadata"]
    assert candidate["design_version"] == 2

    # Preview MODIFY of the design-change Candidate: differences=[] + change_reason → design-change mode, version stays 2.
    even_taller = {"blocks": taller["blocks"] + [dict(brick_type="1x2x1", color="red", x=10, y=8, layer=3, orientation_deg=0)]}
    assert validator.validate_design({"design_version": 2, "blocks": even_taller["blocks"]}) == []
    monkeypatch.setattr(llm, "generate_revised_design", lambda *a, **k: (calls["generate"].append(k), deepcopy(even_taller))[1])
    modified = main.review_design_candidate(candidate, kind="revised", design_metadata=meta, previous_design=approved,
                                            current=current, differences=[], change_reason=change_reason,
                                            text_answers=["등받이를 조금 더 높게 바꿔줘"])
    assert modified["status"] == "OK" and modified["hri_result"] == dialogue.MODIFY
    assert modified["design"]["design_version"] == 2 and modified["design"]["blocks"] != candidate["blocks"]
    assert validator.validate_revised({"blocks": modified["design"]["blocks"]}, current) == []
    assert modified["design_metadata"]["review"]["round"] == 1
    assert calls["generate"][-1]["change_request"] == change_reason and calls["generate"][-1]["scope"] == "patch"

    approved_review = main.review_design_candidate(modified["design"], kind="revised", design_metadata=modified["design_metadata"],
                                                   previous_design=approved, current=current, differences=[],
                                                   change_reason=change_reason, text_answers=["좋아 이걸로 하자"])
    assert approved_review["hri_result"] == dialogue.APPROVE and approved_review["design"] == modified["design"]
    assert approved_review["design_metadata"]["review"]["round"] == 1  # APPROVE does not add a round
    # MODIFY makes a new Candidate with its own Stage 2 metadata (style_hint = the MODIFY wish); APPROVE carries it through.
    assert modified["design_metadata"]["style_hint"] == "더 높게" and modified["design_metadata"]["review"]["style_hint"] == "더 높게"
    assert approved_review["design_metadata"]["style_hint"] == "더 높게" and meta["style_hint"] is None  # "2번" gives no wish


def test_review_without_metadata_restarts_round_at_zero(monkeypatch, approved, current, change_reason):
    # C cannot recover metadata the caller drops (PR #26 MVP review passes none): documented for the D handoff.
    _llm_stubs(monkeypatch, approved, _taller(approved))
    first = main.run_design_change(approved, current, text_answers=["2번"], reason=change_reason)
    review = main.review_design_candidate(first["design"], kind="revised", previous_design=approved, current=current,
                                          differences=[], change_reason=change_reason, text_answers=["좋아 이걸로 하자"])
    assert review["design_metadata"]["review"]["round"] == 0 and "style_hint" not in review["design_metadata"]
