"""A Planning failure → C Design-Change HRI (Wave 4, 2026-10-12; docs/C_DESIGN_CONTRACT.md §4.6).

`run_design_change(..., planning_failure=...)` reuses the Wave 3 design-change mode: the same ask()/TTS/STT turn loop, the
same parser and LLM fallback, the same Revised generation (Current preserved, facing soft goal) — only the question text
and the generation change request come from the planning failure. Wrongly routed failures are refused before any question.
No real LLM/STT/TTS (conftest guard); voice is exercised with monkeypatched voice.speak / voice.listen.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

import c_facing_helper as facing
from app.c_design import designer, dialogue, llm, main, validator, voice

FIXTURES = Path(__file__).parents[2] / "fixtures"
DESIGN_CHANGE = FIXTURES / "c_design_change"
PLAN_FAILURE = FIXTURES / "c_plan_failure"
JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True,
            "design_name": "순서 가능한 의자", "design_family": "chair", "why_it_is_complete": "ok", "visible_features": [],
            "change_summary": ["등받이 재배치"]}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def approved():
    return _load(DESIGN_CHANGE / "approved_design.json")


@pytest.fixture
def current():
    return _load(DESIGN_CHANGE / "current_prefix.json")


def _failure_from(result_name, *, redesign_required, blocked=None):
    """Build the D → C planning_failure the way D would from an A WholePlanResult fixture."""
    result = _load(PLAN_FAILURE / result_name)
    errors = result.get("stage_errors") or result.get("errors") or []
    code = result.get("calculation_status") or (errors[0]["code"] if errors else None)
    blocks = blocked if blocked is not None else [e["block"] for e in errors if e.get("block")]
    return {"failure_code": code, "redesign_required": redesign_required, "retryable": code == "SEARCH_LIMIT",
            "blocked_blocks": blocks, "detail": str(errors)}


@pytest.fixture
def failure_with_block():
    return _failure_from("whole_no_feasible_order_with_block.json", redesign_required=True)


@pytest.fixture
def failure_no_block():
    return _failure_from("whole_no_feasible_order_real_unpatched.json", redesign_required=True)


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(designer, "RETRY_DELAY", 0)


def _mock_chair():
    design = designer.build_initial_design("CHAIR")["design"]
    return design, [dict(b) for b in design["blocks"] if b["layer"] == 1]


# ---------------------------------------------------------------------------
# A. planning_failure validation and routing
# ---------------------------------------------------------------------------


def test_no_feasible_order_with_redesign_required_opens_the_dialogue(failure_with_block):
    design, current = _mock_chair()
    envelope = main.run_design_change(design, current, reason="[{'code': 'NO_FEASIBLE_ORDER'}]",
                                      planning_failure=failure_with_block, text_answers=["1번"])
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.KEEP
    assert envelope["questions"] == [dialogue.build_plan_failure_question(failure_with_block)]


@pytest.mark.parametrize("name, redesign_required", [
    ("whole_no_feasible_order_no_block.json", False),   # D did not mark it as a redesign case
    ("whole_search_limit.json", False),
    ("whole_search_limit.json", True),                   # even if D wrongly says so: SEARCH_LIMIT is never a design verdict
    ("step_current_mismatch.json", False),
    ("step_current_mismatch.json", True),
    ("whole_invalid_context.json", False),
])
def test_wrongly_routed_failures_are_refused_without_a_question(name, redesign_required):
    design, current = _mock_chair()
    failure = _failure_from(name, redesign_required=redesign_required)
    asked = []
    envelope = main.run_design_change(design, current, reason="x", planning_failure=failure, text_answers=["2번"],
                                      on_question=asked.append)
    assert envelope["status"] == "FAILED" and envelope["error"]["code"] == "PLANNING_FAILURE_NOT_REDESIGN"
    assert failure["failure_code"] in envelope["error"]["message"]
    assert envelope["questions"] == [] and asked == [] and envelope["design"] is None


def test_calculation_error_is_refused():
    design, current = _mock_chair()
    failure = {"failure_code": "CALCULATION_ERROR", "redesign_required": False, "detail": "ZeroDivisionError"}
    assert main.run_design_change(design, current, reason="x", planning_failure=failure,
                                  text_answers=["2번"])["error"]["code"] == "PLANNING_FAILURE_NOT_REDESIGN"


@pytest.mark.parametrize("failure, rule", [
    ({"failure_code": "NO_FEASIBLE_ORDER"}, "missing_field"),
    ({"failure_code": "", "redesign_required": True}, "invalid_type"),
    ({"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": "yes"}, "invalid_type"),
    ({"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True, "blocked_blocks": {"x": 1}}, "invalid_type"),
    ({"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True, "blocked_blocks": [{"x": 1}]}, "missing_field"),
    ({"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True, "retryable": "no"}, "invalid_type"),
    ("NO_FEASIBLE_ORDER", "invalid_type"),
])
def test_malformed_planning_failure_is_invalid_input(failure, rule):
    design, current = _mock_chair()
    envelope = main.run_design_change(design, current, reason="x", planning_failure=failure, text_answers=["2번"])
    assert envelope["status"] == "FAILED" and envelope["error"]["code"] == "INVALID_INPUT"
    assert rule in {r["rule"] for r in envelope["error"]["details"]}
    assert validator.check_planning_failure(failure) == envelope["error"]["details"]


def test_planning_failure_extra_keys_are_ignored_and_not_part_of_the_design(failure_with_block):
    failure = dict(failure_with_block, a_candidate_id="candidate-x", optimization={"expanded_states": 10})
    assert validator.check_planning_failure(failure) == []
    assert validator.TOP_FIELDS == ("design_version", "blocks")  # schema untouched


def test_callers_without_planning_failure_are_unchanged(approved, current):
    assert main.run_design_change(approved, current, reason="USER_DESIGN_CHANGE", text_answers=["1번"])["hri_result"] == dialogue.KEEP


# ---------------------------------------------------------------------------
# B. question builder — natural language only
# ---------------------------------------------------------------------------


def test_question_with_blocked_block_names_layer_and_position_only(failure_with_block):
    question = dialogue.build_plan_failure_question(failure_with_block)
    block = failure_with_block["blocked_blocks"][0]
    lines = question.split("\n")
    assert len(lines) == 3
    assert lines[0] == f"(x={block['x']}, y={block['y']}) {block['layer']}층 블록은 로봇이 조립할 수 있는 순서를 찾지 못했어요."
    assert lines[1] == dialogue.PLAN_FAILURE_CONSEQUENCE and lines[2] == dialogue.PLAN_FAILURE_CHOICE_BLOCKED
    for forbidden in ("NO_FEASIBLE_ORDER", "등받이", "팔걸이", "좌석", "{", "[", "code"):
        assert forbidden not in question


def test_question_without_blocked_block_is_general(failure_no_block):
    assert failure_no_block["blocked_blocks"] == []  # the real A result carries no block today
    question = dialogue.build_plan_failure_question(failure_no_block)
    assert question.split("\n") == [dialogue.PLAN_FAILURE_GENERAL, dialogue.PLAN_FAILURE_CONSEQUENCE, dialogue.PLAN_FAILURE_CHOICE_GENERAL]
    assert "NO_FEASIBLE_ORDER" not in question and "[" not in question and "번" not in question


def test_question_limits_spoken_blocks(failure_with_block):
    block = failure_with_block["blocked_blocks"][0]
    many = dict(failure_with_block, blocked_blocks=[block, dict(block, y=block["y"] + 3), dict(block, y=block["y"] + 6)])
    first = dialogue.build_plan_failure_question(many).split("\n")[0]
    assert first.count("층 블록") == dialogue.PLAN_FAILURE_MAX_SPOKEN_BLOCKS and first.endswith("등은 로봇이 조립할 수 있는 순서를 찾지 못했어요.")


def test_raw_reason_and_detail_never_reach_the_question(failure_with_block):
    design, current = _mock_chair()
    raw = "[{'code': 'NO_FEASIBLE_ORDER', 'reason': 'NO_FEASIBLE_ORDER', 'block': None}]"
    envelope = main.run_design_change(design, current, reason=raw, planning_failure=dict(failure_with_block, detail=raw),
                                      text_answers=["글쎄"])
    for question in envelope["questions"]:
        assert "NO_FEASIBLE_ORDER" not in question and "{" not in question and "[" not in question
    assert envelope["questions"][1] == dialogue.build_design_change_reask(envelope["questions"][0])


def test_voice_mode_speaks_the_natural_question_through_the_existing_ask_and_listen(monkeypatch, failure_with_block):
    design, current = _mock_chair()
    spoken, heard = [], iter(["응, 수정해줘"])
    monkeypatch.setattr(voice, "speak", spoken.append)
    monkeypatch.setattr(voice, "listen", lambda on_ready=None, mode="short", beep=False: next(heard))
    asked = []
    envelope = main.run_design_change(design, current, reason="[{'code': 'NO_FEASIBLE_ORDER'}]",
                                      planning_failure=failure_with_block, on_question=asked.append)  # text_answers=None → voice
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.REVISE and envelope["design"] is not None
    assert spoken == asked == [dialogue.build_plan_failure_question(failure_with_block)]
    assert all("NO_FEASIBLE_ORDER" not in sentence for sentence in spoken)


# ---------------------------------------------------------------------------
# C. intent — Wave 3 design-change semantics, no new enum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("응, 수정해줘", dialogue.REVISE), ("수정할게요", dialogue.REVISE), ("바꿔줘", dialogue.REVISE), ("새 설계로 해줘", dialogue.REVISE),
    ("그 부분 바꿔서 다시 설계해줘", dialogue.REVISE), ("2번", dialogue.REVISE),
    ("아니, 기존 설계로 할래", dialogue.KEEP), ("그대로 둘게", dialogue.KEEP), ("기존 설계 유지할게", dialogue.KEEP),
    ("안 바꿀게", dialogue.KEEP), ("1번", dialogue.KEEP),
    ("무슨 뜻이야?", dialogue.UNCLEAR), ("글쎄", dialogue.UNCLEAR), ("잘 모르겠어", dialogue.UNCLEAR),
    ("취소할게", dialogue.CANCEL),
])
def test_plan_failure_answers_use_the_design_change_table(text, expected, failure_with_block):
    assert dialogue.parse_design_change_response(text) == expected
    design, current = _mock_chair()
    envelope = main.run_design_change(design, current, reason="x", planning_failure=failure_with_block, text_answers=[text])
    if expected == dialogue.CANCEL:
        assert envelope["status"] == "CANCELLED" and envelope["error"]["code"] == "USER_CANCEL"
    else:
        assert envelope["status"] == "OK" and envelope["hri_result"] == expected


def test_the_same_words_keep_their_mode_specific_meaning():
    assert dialogue.parse_response("수정할게요") == dialogue.KEEP            # Difference Intervention: fix my block
    assert dialogue.parse_design_change_response("수정할게요") == dialogue.REVISE  # Design Change / Planning failure


def test_llm_fallback_receives_planning_failure_separately_from_inspection_context(monkeypatch, failure_with_block):
    seen = []

    def fake_json_call(system_prompt, user_message, should_stop, model=None):
        seen.append((system_prompt, json.loads(user_message.split("\n", 1)[1])))
        return {"decision": "UNCLEAR", "style_hint": "", "reason": "r", "reply": ""}
    monkeypatch.setattr(llm, "_json_call", fake_json_call)
    context = {"expected": None, "difference": None, "observation": None, "reason": "PLAN"}
    llm.interpret_design_change_answer("무슨 뜻이야?", "PLAN", context=context, planning_failure=failure_with_block)
    system, payload = seen[0]
    assert system == llm.SYSTEM_PROMPT_DESIGN_CHANGE_ANSWER
    assert payload["planning_failure"] == llm.planning_failure_summary(failure_with_block)
    assert "planning_failure" not in payload["inspection_context"] and payload["inspection_context"]["change_reason"] == "PLAN"
    assert "detail" not in payload["planning_failure"]  # raw detail is diagnostics only
    assert payload["planning_failure"]["blocked_blocks"] == [{"x": b["x"], "y": b["y"], "layer": b["layer"]} for b in failure_with_block["blocked_blocks"]]


# ---------------------------------------------------------------------------
# D / E. REVISE candidate and KEEP (LLM stubs)
# ---------------------------------------------------------------------------


def _taller(approved):
    blocks = [b for b in approved["blocks"] if b["layer"] != 5]
    blocks += [dict(brick_type="2x2x1", color="blue", x=8, y=y, layer=5, orientation_deg=0) for y in (8, 10, 12)]
    assert validator.validate_design({"design_version": 1, "blocks": blocks}) == []
    return {"blocks": blocks}


def _llm_stubs(monkeypatch, approved):
    calls = {"generate": [], "interpret": []}

    def generate(design, current, differences, reasons=None, **kwargs):
        calls["generate"].append(kwargs)
        return deepcopy(_taller(approved))

    def interpret(text, differences, should_stop=None, context=None, planning_failure=None):
        calls["interpret"].append((context, planning_failure))
        return {"decision": "REVISE", "style_hint": "막힌 부분 재배치", "reason": "r", "reply": "조립된 부분은 두고 다시 만들어볼게요."}
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(llm, "generate_revised_design", generate)
    monkeypatch.setattr(llm, "interpret_intervention_answer", interpret)
    monkeypatch.setattr(llm, "judge_revised_design", lambda *a, **k: deepcopy(JUDGE_OK))
    monkeypatch.setattr(designer, "revised_min_blocks", lambda design: len(design["blocks"]))
    return calls


def test_revise_builds_v2_candidate_with_current_preserved_facing_and_metadata(monkeypatch, approved, current, failure_with_block):
    calls = _llm_stubs(monkeypatch, approved)
    events = []
    envelope = main.run_design_change(approved, current, reason="[{'code': 'NO_FEASIBLE_ORDER'}]", planning_failure=failure_with_block,
                                      text_answers=["응, 수정해줘"], on_progress=events.append)
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.REVISE
    design = envelope["design"]
    assert design["design_version"] == approved["design_version"] + 1
    assert validator.validate_design(design) == [] and validator.validate_revised({"blocks": design["blocks"]}, current) == []
    assert all(b in design["blocks"] for b in current)
    assert facing.classify_facing(design, current=current)[0] in (facing.PASS, facing.FOLLOWS_CURRENT)
    meta = envelope["design_metadata"]
    assert meta["source"] == "LLM" and meta["judge"]["verdict"] == "SHOWCASE" and meta["style_hint"] == "막힌 부분 재배치"
    assert "planning_failure" not in meta and "planning_failure" not in design
    request = calls["generate"][0]["change_request"]
    block = failure_with_block["blocked_blocks"][0]
    assert request == llm.planning_failure_change_request(failure_with_block)
    assert "no feasible assembly order" in request and f"layer {block['layer']} at (x={block['x']}, y={block['y']})" in request
    assert "[{" not in request and "keep every Current block exactly" in request
    assert calls["interpret"][0][1] == failure_with_block  # style-hint call also sees the planning failure
    stages = [e["stage"] for e in events]
    assert "ACK" in stages and stages[-1] == "READY_REVISED"


def test_revise_without_blocked_block_still_generates(monkeypatch, approved, current, failure_no_block):
    calls = _llm_stubs(monkeypatch, approved)
    envelope = main.run_design_change(approved, current, reason="x", planning_failure=failure_no_block, text_answers=["2번"])
    assert envelope["status"] == "OK" and envelope["design"]["design_version"] == 2
    assert "No specific blocked block was reported" in calls["generate"][0]["change_request"]


def test_keep_returns_approved_unchanged_and_generates_nothing(monkeypatch, approved, current, failure_with_block):
    calls = _llm_stubs(monkeypatch, approved)
    events = []
    envelope = main.run_design_change(approved, current, reason="x", planning_failure=failure_with_block,
                                      text_answers=["아니, 기존 설계로 할래"], on_progress=events.append)
    assert envelope["status"] == "OK" and envelope["hri_result"] == dialogue.KEEP
    assert envelope["design"] == approved and envelope["design_metadata"] is None
    assert calls["generate"] == [] and calls["interpret"] == []  # rule KEEP: no LLM, no Candidate, no replanning by C
    assert [e["stage"] for e in events if e["stage"] in ("GENERATING_REVISED", "ACK")] == []
    assert any(e["stage"] == "KEEP_ACK" and e["message"] in dialogue.DESIGN_CHANGE_KEEP_ACKS for e in events)


def test_candidate_review_after_plan_failure_keeps_v2_and_planning_context(monkeypatch, approved, current, failure_with_block):
    calls = _llm_stubs(monkeypatch, approved)
    first = main.run_design_change(approved, current, reason="x", planning_failure=failure_with_block, text_answers=["2번"])
    candidate, meta = first["design"], first["design_metadata"]
    even_taller = {"blocks": _taller(approved)["blocks"] + [dict(brick_type="1x2x1", color="red", x=10, y=8, layer=3, orientation_deg=0)]}
    monkeypatch.setattr(llm, "generate_revised_design", lambda *a, **k: (calls["generate"].append(k), deepcopy(even_taller))[1])
    monkeypatch.setattr(llm, "interpret_review_answer", lambda *a, **k: {"decision": "MODIFY", "style_hint": "더 단순하게", "scope": "patch",
                                                                       "concept": "", "reason": "r", "reply": "p"})
    modified = main.review_design_candidate(candidate, kind="revised", design_metadata=meta, previous_design=approved, current=current,
                                            differences=[], change_reason="x", planning_failure=failure_with_block,
                                            text_answers=["좀 더 단순하게 바꿔줘"])
    assert modified["status"] == "OK" and modified["hri_result"] == dialogue.MODIFY
    assert modified["design"]["design_version"] == 2 and modified["design_metadata"]["review"]["round"] == 1
    assert calls["generate"][-1]["change_request"] == llm.planning_failure_change_request(failure_with_block)
    assert main.review_design_candidate(candidate, kind="revised", previous_design=approved, current=current, differences=[],
                                        change_reason="x", planning_failure={"failure_code": "X"},
                                        text_answers=["좋아"])["error"]["code"] == "INVALID_INPUT"
