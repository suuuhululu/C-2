"""Unit tests for app.c_design.main (docs/C_DESIGN_CONTRACT.md §4, §6, §8, §10).

main.py is being implemented in parallel by the lead; these tests build valid inputs
from the real (Mock) designer/validator so they exercise the real orchestration logic,
not hand-crafted fixtures. If main.py is still a stub when this runs, most tests fail
with AttributeError/TypeError -- that is expected and not weakened here.

Conventions:
    - ``designer.RETRY_DELAY`` is monkeypatched to 0 in every test that can reach a
      retry loop, per the lead's instruction (main passes delay=designer.RETRY_DELAY).
    - Legs are identified by ``layer == 1`` (no block ids exist, per contract §8.4).
    - Questions are open-ended (no numbered choices); "1번" / "2번" answers are still
      accepted silently as KEEP/REVISE (and MOVE_BACK/KEEP_SEARCHING) via
      dialogue.OPTIONS / dialogue.ESCALATION_OPTIONS, so these tests keep using them.
"""

import pytest

from app.c_design import designer, main, validator

GOAL_TEXT = "오늘은 의자를 만들 거야"
ESCALATION_MARK = "계속 새 설계를 찾아볼까요"  # dialogue.escalation_question에만 있는 문구
ENVELOPE_KEYS = {"status", "hri_result", "design", "design_metadata", "questions", "error"}


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------


def _block_tuple(block):
    return tuple(block[key] for key in validator.BLOCK_FIELDS)


def _assert_envelope_shape(result):
    assert set(result.keys()) == ENVELOPE_KEYS
    assert result["status"] in {"OK", "FAILED", "CANCELLED"}
    assert result["hri_result"] in {"KEEP", "REVISE", "UNCLEAR", None}
    if result["status"] == "OK":
        assert result["error"] is None
    else:
        assert result["error"] is not None
        assert set(result["error"].keys()) == {"code", "message", "details"}
        assert isinstance(result["error"]["details"], list)
    return result


def _legs(design):
    return sorted((b for b in design["blocks"] if b["layer"] == 1), key=lambda b: (b["x"], b["y"]))


def _build_shift_scenario(design):
    """current = all four legs, the one with the largest y shifted by +1 in y;
    differences = the matching single expected/actual pair (§5.2, §8.3)."""
    legs = _legs(design)
    target = max(legs, key=lambda b: b["y"])
    shifted = dict(target, y=target["y"] + 1)
    current = [shifted if b is target else dict(b) for b in legs]
    differences = [{"expected": dict(target), "actual": dict(shifted)}]
    return current, differences


def _single_stud_overlap_block(leg, other_legs):
    """A 2x2x1 layer-2 block overlapping `leg`'s footprint by exactly one stud and
    not touching any other leg (§9.1 support Case D: shared studs < 2)."""
    leg_cells = validator.footprint(leg)
    other_cells = set()
    for other in other_legs:
        other_cells |= validator.footprint(other)
    for (cx, cy) in sorted(leg_cells):
        for dx in (0, 1):
            for dy in (0, 1):
                bx, by = cx - dx, cy - dy
                if not (0 <= bx <= 22 and 0 <= by <= 22):
                    continue
                candidate = dict(brick_type="2x2x1", color="yellow", x=bx, y=by, layer=2, orientation_deg=0)
                fp = validator.footprint(candidate)
                if (fp & leg_cells) == {(cx, cy)} and not (fp & other_cells):
                    return candidate
    raise AssertionError("could not build a single-stud-overlap block for this leg layout")


def _build_support_violation_scenario(design):
    """current = all four legs + one layer-2 block overlapping one leg by exactly one
    stud (violates support, §9.1/§8.11); differences describes that extra block."""
    legs = _legs(design)
    leg, others = legs[0], legs[1:]
    extra = _single_stud_overlap_block(leg, others)
    current = [dict(b) for b in legs] + [extra]
    assert validator.current_support_violations(current), "scenario must actually violate support"
    differences = [{"expected": None, "actual": dict(extra)}]
    return current, differences


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    monkeypatch.setattr(designer, "RETRY_DELAY", 0)


@pytest.fixture(scope="module")
def initial_design():
    result = main.create_initial_design(text=GOAL_TEXT)
    design = result["design"]
    assert design is not None, "create_initial_design must succeed for a CHAIR goal before other tests can use it"
    return design


# ---------------------------------------------------------------------------
# 1. Initial success
# ---------------------------------------------------------------------------


def test_initial_success_envelope():
    result = main.create_initial_design(text=GOAL_TEXT)
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] is None
    assert result["error"] is None
    assert result["questions"] == []
    design = result["design"]
    assert design["design_version"] == 1
    assert validator.validate_design(design) == []


# ---------------------------------------------------------------------------
# 2. unsupported goal / invalid text types
# ---------------------------------------------------------------------------


def test_unsupported_goal():
    result = main.create_initial_design(text="책상 만들 거야")
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "UNSUPPORTED_OBJECT"
    assert result["design"] is None
    assert result["hri_result"] is None


def test_whitespace_only_text_is_unsupported_object():
    # Contract §4.1: "공백뿐인 문자열은 UNSUPPORTED_OBJECT" (whitespace-only -> no
    # recognizable goal, same as any other unsupported sentence; NOT INVALID_INPUT).
    result = main.create_initial_design(text="   ")
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "UNSUPPORTED_OBJECT"


def test_non_str_non_none_text_is_invalid_input():
    result = main.create_initial_design(text=42)
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "INVALID_INPUT"
    assert result["design"] is None


# ---------------------------------------------------------------------------
# 3. KEEP
# ---------------------------------------------------------------------------


def test_keep_returns_input_design_unchanged(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=["1번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"
    assert result["design"] == initial_design
    assert result["design"]["design_version"] == initial_design["design_version"]


# ---------------------------------------------------------------------------
# 4. REVISE success
# ---------------------------------------------------------------------------


def test_revise_success_preserves_current_and_validates(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=["2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "REVISE"
    design = result["design"]
    assert design["design_version"] == initial_design["design_version"] + 1
    result_tuples = {_block_tuple(b) for b in design["blocks"]}
    for block in current:
        assert _block_tuple(block) in result_tuples
    assert validator.validate_design(design) == []


# ---------------------------------------------------------------------------
# 5 / 6. one UNCLEAR reask, then a clear choice
# ---------------------------------------------------------------------------


def test_unclear_then_keep_reasks_once(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=["모르겠어요", "1번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"
    assert len(result["questions"]) == 2
    assert "잘 못 알아들었어요" in result["questions"][1]


def test_unclear_then_revise(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=["모르겠어요", "2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "REVISE"


# ---------------------------------------------------------------------------
# 7. several UNCLEAR then a clear choice
# ---------------------------------------------------------------------------


def test_several_unclear_then_keep(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    answers = ["모르겠어요", "글쎄요", "음...", "1번"]
    result = main.run_intervention(initial_design, current, differences, text_answers=answers)
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"
    assert result["design"] == initial_design
    # original question + one reask per unclear answer consumed before the clear one
    assert len(result["questions"]) == len(answers)


# ---------------------------------------------------------------------------
# 8. should_stop always True
# ---------------------------------------------------------------------------


def test_should_stop_always_true_cancels(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(
        initial_design, current, differences, text_answers=["1번"], should_stop=lambda: True
    )
    _assert_envelope_shape(result)
    assert result["status"] == "CANCELLED"
    assert result["error"]["code"] == "STOPPED"
    assert result["design"] is None
    assert result["hri_result"] is None
    assert len(result["questions"]) >= 1


# ---------------------------------------------------------------------------
# 9. explicit cancel
# ---------------------------------------------------------------------------


def test_explicit_cancel(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=["취소할게"])
    _assert_envelope_shape(result)
    assert result["status"] == "CANCELLED"
    assert result["error"]["code"] == "USER_CANCEL"
    assert result["design"] is None
    assert result["hri_result"] is None


# ---------------------------------------------------------------------------
# 10. designer generation limit reached -> DESIGN_GENERATION_FAILED
# ---------------------------------------------------------------------------


def test_revise_generation_failure_after_escalation_decline(initial_design, monkeypatch):
    current, differences = _build_shift_scenario(initial_design)
    calls = {"n": 0}

    def always_invalid(design, current_, differences_, reasons=None):
        calls["n"] += 1
        return {"blocks": []}

    monkeypatch.setattr(designer, "mock_revised_candidate", always_invalid)

    result = main.run_intervention(initial_design, current, differences, text_answers=["2번", "2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "DESIGN_GENERATION_FAILED"
    assert result["hri_result"] == "REVISE"
    assert result["design"] is None
    assert result["error"]["details"]
    assert 1 <= calls["n"] <= 10
    # "계속 새 설계를 찾아볼까요" only appears in dialogue.escalation_question;
    # the ordinary HRI question/reask never use this exact phrasing.
    assert any(ESCALATION_MARK in q for q in result["questions"]), "escalation question must be among questions"


# ---------------------------------------------------------------------------
# 11. rejected once, then recovers via escalation KEEP_SEARCHING
# ---------------------------------------------------------------------------


def test_revise_recovers_after_one_rejection(initial_design, monkeypatch):
    current, differences = _build_shift_scenario(initial_design)
    original_mock_revised = designer.mock_revised_candidate
    calls = {"n": 0}

    def flaky(design, current_, differences_, reasons=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"blocks": []}
        return original_mock_revised(design, current_, differences_, reasons)

    monkeypatch.setattr(designer, "mock_revised_candidate", flaky)

    result = main.run_intervention(initial_design, current, differences, text_answers=["2번", "2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "REVISE"
    assert result["design"]["design_version"] == initial_design["design_version"] + 1
    assert calls["n"] >= 2


# ---------------------------------------------------------------------------
# 12. REVISE with an unchanged layout -> input design returned, version unchanged
# ---------------------------------------------------------------------------


def test_revise_same_layout_keeps_version(initial_design):
    legs = _legs(initial_design)
    current = [dict(leg) for leg in legs]
    differences = [{"expected": dict(legs[0]), "actual": dict(legs[0])}]
    result = main.run_intervention(initial_design, current, differences, text_answers=["2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "REVISE"
    assert result["design"] == initial_design
    assert result["design"]["design_version"] == initial_design["design_version"]


# ---------------------------------------------------------------------------
# 13 / 14 / 15. tolerance of absent/extra keys on D's inputs
# ---------------------------------------------------------------------------


def test_current_naturally_has_no_block_id(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    for block in current:
        assert "block_id" not in block
    result = main.run_intervention(initial_design, current, differences, text_answers=["1번"])
    assert result["status"] == "OK"


def test_difference_with_extra_keys_still_works(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    differences = [dict(differences[0], diff_id="d1", reason="shifted leg")]
    result = main.run_intervention(initial_design, current, differences, text_answers=["1번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"


def test_current_with_extra_d_metadata_and_clean_result_blocks(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    current = [dict(block, confidence=0.97, observation_seq=3, check_id="chk-1") for block in current]
    result = main.run_intervention(initial_design, current, differences, text_answers=["2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "REVISE"
    for block in result["design"]["blocks"]:
        assert set(block.keys()) == set(validator.BLOCK_FIELDS)


# ---------------------------------------------------------------------------
# 16. envelope invariants across several kinds of results
# ---------------------------------------------------------------------------


def test_envelope_invariants_across_results(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    results = [
        main.create_initial_design(text=GOAL_TEXT),
        main.create_initial_design(text="책상 만들 거야"),
        main.run_intervention(initial_design, current, differences, text_answers=["1번"]),
        main.run_intervention(initial_design, current, differences, text_answers=["2번"]),
        main.run_intervention(initial_design, current, differences, text_answers=["모르겠어요", "모르겠어요"]),
        main.run_intervention(initial_design, current, differences, text_answers=["취소할게"]),
        main.run_intervention(
            initial_design, current, differences, text_answers=["1번"], should_stop=lambda: True
        ),
    ]
    for result in results:
        _assert_envelope_shape(result)

    unclear_exhausted = results[4]
    assert unclear_exhausted["status"] == "OK"
    assert unclear_exhausted["hri_result"] == "UNCLEAR"
    assert unclear_exhausted["design"] is None


# ---------------------------------------------------------------------------
# 17. empty differences -> INVALID_INPUT
# ---------------------------------------------------------------------------


def test_empty_differences_is_invalid_input(initial_design):
    current, _ = _build_shift_scenario(initial_design)
    result = main.run_intervention(initial_design, current, [], text_answers=["1번"])
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "INVALID_INPUT"
    assert result["hri_result"] is None
    assert result["error"]["details"]


# ---------------------------------------------------------------------------
# 18. current support violation -> escalation (§8.11), no generation attempted
# ---------------------------------------------------------------------------


def test_current_support_violation_escalates_once_then_keep(initial_design):
    current, differences = _build_support_violation_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=["2번", "1번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"
    assert result["design"] == initial_design
    escalation_questions = [q for q in result["questions"] if ESCALATION_MARK in q]
    assert len(escalation_questions) == 1


def test_current_support_violation_escalates_twice_then_keep(initial_design):
    current, differences = _build_support_violation_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=["2번", "2번", "1번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "KEEP"
    assert result["design"] == initial_design
    escalation_questions = [q for q in result["questions"] if ESCALATION_MARK in q]
    assert len(escalation_questions) == 2


# ---------------------------------------------------------------------------
# 19. voice mode, audio device unavailable (blocked by tests/conftest.py) -> VOICE_IO_FAILED
# ---------------------------------------------------------------------------


def test_create_initial_design_voice_mode_fails():
    result = main.create_initial_design(text=None)
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "VOICE_IO_FAILED"
    assert result["error"]["message"] == "voice I/O failed: audio_device: RuntimeError"
    assert result["design"] is None


def test_run_intervention_voice_mode_fails(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(initial_design, current, differences, text_answers=None)
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "VOICE_IO_FAILED"
    assert result["design"] is None
    assert len(result["questions"]) >= 1


# ---------------------------------------------------------------------------
# 20. should_stop flips True after the first designer attempt
# ---------------------------------------------------------------------------


def test_should_stop_during_escalation_wait_cancels(initial_design, monkeypatch):
    current, differences = _build_shift_scenario(initial_design)
    stop_flag = {"go": False}

    def flip_and_fail(design, current_, differences_, reasons=None):
        stop_flag["go"] = True
        return {"blocks": []}

    monkeypatch.setattr(designer, "mock_revised_candidate", flip_and_fail)

    asked = []
    result = main.run_intervention(
        initial_design,
        current,
        differences,
        text_answers=["2번", "2번"],
        on_question=asked.append,
        should_stop=lambda: stop_flag["go"],
    )
    _assert_envelope_shape(result)
    assert result["status"] == "CANCELLED"
    assert result["error"]["code"] == "STOPPED"
    assert result["design"] is None
    assert result["hri_result"] is None
    assert asked == result["questions"]
    assert len(asked) >= 1


# ---------------------------------------------------------------------------
# STOP while waiting through silence (Day4: no time-based cancel, but STOP must still stop)
# ---------------------------------------------------------------------------


def _stop_from_second_call():
    calls = []

    def should_stop():
        calls.append(None)
        return len(calls) >= 2

    return should_stop


def test_stop_during_voice_silence_wait(initial_design, monkeypatch):
    current, differences = _build_shift_scenario(initial_design)
    monkeypatch.setattr(main.voice, "listen", lambda: "")  # silence forever
    result = main.run_intervention(
        initial_design, current, differences, text_answers=None, should_stop=_stop_from_second_call()
    )
    _assert_envelope_shape(result)
    assert result["status"] == "CANCELLED"
    assert result["error"]["code"] == "STOPPED"
    assert len(result["questions"]) == 1  # silence never triggers a re-ask


def test_stop_during_text_mode_empty_answers(initial_design):
    current, differences = _build_shift_scenario(initial_design)
    result = main.run_intervention(
        initial_design, current, differences, text_answers=["", ""], should_stop=_stop_from_second_call()
    )
    _assert_envelope_shape(result)
    assert result["status"] == "CANCELLED"
    assert result["error"]["code"] == "STOPPED"
    assert len(result["questions"]) == 1


# ---------------------------------------------------------------------------
# WAVE 5: C_DESIGN_USE_LLM switches the generator main injects into designer.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_use_llm_env(monkeypatch):
    # main reads os.environ at call time (not import time); make sure no test leaks
    # C_DESIGN_USE_LLM into another test via a real environment variable.
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)


@pytest.fixture(autouse=True)
def _no_real_metadata_calls(monkeypatch):
    # LLM-mode tests here stub only the design generator; the metadata calls (intent / judge / describe) answer with
    # a provider error so no request is ever built. tests/unit/c_design/test_design_metadata.py covers them.
    def not_stubbed(*args, **kwargs):
        return {"llm_error": {"kind": "bad_response", "message": "not stubbed in test_main"}}

    for name in ("generate_design_intent", "judge_revised_design", "describe_initial_design"):
        monkeypatch.setattr(main.llm, name, not_stubbed)


def test_use_llm_unset_takes_the_mock_path(monkeypatch):
    def must_not_be_called(object_type, reasons=None, should_stop=None):
        raise AssertionError("llm.generate_initial_design must not be called when C_DESIGN_USE_LLM is unset")

    monkeypatch.setattr(main.llm, "generate_initial_design", must_not_be_called)
    result = main.create_initial_design(text=GOAL_TEXT)
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["design"]["design_version"] == 1


def test_use_llm_set_takes_the_llm_path_for_initial_design(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    calls = {"n": 0}

    def fake_generate_initial(object_type, reasons=None, should_stop=None):
        calls["n"] += 1
        calls["object_type"] = object_type
        calls["reasons"] = reasons
        calls["should_stop"] = should_stop
        return designer.mock_initial_candidate(object_type)

    monkeypatch.setattr(main.llm, "generate_initial_design", fake_generate_initial)
    result = main.create_initial_design(text=GOAL_TEXT)
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["design"]["design_version"] == 1
    assert validator.validate_design(result["design"]) == []
    assert calls["n"] >= 1
    assert calls["object_type"] == "CHAIR"
    assert "should_stop" in calls  # the should_stop parameter is forwarded (may be None)


def test_use_llm_set_takes_the_llm_path_for_revised_design(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    # Build a fresh Initial Design via the plain Mock path (env unset for this call)
    # so this test does not depend on the shared module-scoped fixture's provenance.
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    design = main.create_initial_design(text=GOAL_TEXT)["design"]
    assert design is not None
    current, differences = _build_shift_scenario(design)

    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    calls = {"n": 0}

    def fake_generate_revised(design_in, current_in, differences_in, reasons=None, should_stop=None, intent=None, feedback=None):
        calls["n"] += 1
        calls["should_stop"] = should_stop
        return designer.mock_revised_candidate(design_in, current_in, differences_in)

    monkeypatch.setattr(main.llm, "generate_revised_design", fake_generate_revised)
    result = main.run_intervention(design, current, differences, text_answers=["2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "OK"
    assert result["hri_result"] == "REVISE"
    assert result["design"]["design_version"] == design["design_version"] + 1
    assert validator.validate_design(result["design"]) == []
    assert calls["n"] >= 1
    assert "should_stop" in calls


def test_use_llm_set_initial_design_llm_error_is_llm_call_failed(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")

    def fake_generate_initial(object_type, reasons=None, should_stop=None):
        return {"llm_error": {"kind": "rate_limit", "message": "HTTP 429"}}

    monkeypatch.setattr(main.llm, "generate_initial_design", fake_generate_initial)
    result = main.create_initial_design(text=GOAL_TEXT)
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "LLM_CALL_FAILED"
    assert result["error"]["message"] == "rate_limit"
    assert result["error"]["details"] == []
    assert result["design"] is None
    assert result["hri_result"] is None


def test_use_llm_set_revised_design_llm_error_is_llm_call_failed_with_revise_hri(initial_design, monkeypatch):
    current, differences = _build_shift_scenario(initial_design)
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")

    def fake_generate_revised(design_in, current_in, differences_in, reasons=None, should_stop=None, intent=None, feedback=None):
        return {"llm_error": {"kind": "rate_limit", "message": "HTTP 429"}}

    monkeypatch.setattr(main.llm, "generate_revised_design", fake_generate_revised)
    result = main.run_intervention(initial_design, current, differences, text_answers=["2번"])
    _assert_envelope_shape(result)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "LLM_CALL_FAILED"
    assert result["error"]["message"] == "rate_limit"
    assert result["hri_result"] == "REVISE"
    assert result["design"] is None
