"""design_metadata, the judge-driven regeneration cap and the Stage 2 wiring (docs/C_DESIGN_CONTRACT.md §4, §6, §8.12, §8.13).

No real LLM or network: the generator / judge / describe / interpretation functions of llm are replaced per test.
Stage 2 Wave 4 (After 구조): Revised has no design-intent step; design_intent in metadata is always None.
Every Revised test asserts the number of design regenerations for one request (at most
main.METADATA_REGENERATIONS_MAX == 1) and how many design / judge calls were made.
"""

import json
import random

import pytest

from app.c_design import designer, dialogue, llm, main, validator

GOAL_TEXT = "의자 만들어줘"
_REAL_GENERATE_REVISED = llm.generate_revised_design  # saved before any test replaces it
ENVELOPE_KEYS = {"status", "hri_result", "design", "design_metadata", "questions", "error"}
REVISED_METADATA_KEYS = {"design_name", "design_family", "design_summary", "visible_features", "human_interpretation",
                         "change_summary", "interpretation_status", "judge", "design_intent", "regenerations", "style_hint",
                         "source", "error"}
MOCK_REVISED_METADATA_KEYS = REVISED_METADATA_KEYS - {"style_hint"}

def judge(**overrides):
    base = {
        "design_family": "throne", "design_name": "푸른 왕좌", "visible_features": ["좌석 6×6", "등받이 3층"],
        "why_it_is_complete": "받침·좌석·등받이가 모두 보인다", "change_summary": ["받침을 넓혔다"],
        "feature_check": [{"planned": "좌석 6×6", "status": "clearly visible"}], "interpretation_status": "clearly visible",
        "layer5_meaningful": True, "layer5_note": "crown", "reads_as_seating": True, "family_guess_without_name": "throne",
        "recognizable_family": True, "family_confidence": "clear", "silhouette_clarity": "clear",
        "explanation_required_to_understand": False, "family_recognisable": True, "looks_designed_not_patched": True,
        "completeness_score": 4,
        "human_story": {"placed_differently": "다리가 옆에 놓였다", "interpretation": "받침 모서리로 봤다",
                        "imagined_concept": "왕좌를 상상했고", "lego_redesign": "그래서 넓은 받침으로 발전시켰다",
                        "why_final_shape": "받침이 좌석을 받친다"},
        "silhouette_tags": ["plinth"], "awkward": "없음",
        "chair_likeness": "clear", "richer_than_previous": True, "richer_why": "받침과 crown이 늘었다",  # Stage 2
    }
    base.update(overrides)
    return base


def _legs(design):
    return sorted((b for b in design["blocks"] if b["layer"] == 1), key=lambda b: (b["x"], b["y"]))


@pytest.fixture
def scenario(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    design = main.create_initial_design(text=GOAL_TEXT)["design"]
    legs = _legs(design)
    target = max(legs, key=lambda b: b["y"])
    shifted = dict(target, y=target["y"] + 1)
    current = [shifted if b is target else dict(b) for b in legs]
    differences = [{"expected": dict(target), "actual": dict(shifted)}]
    return design, current, differences


@pytest.fixture
def llm_mode(monkeypatch):
    """LLM mode with every llm call replaced; counts calls and records the arguments that matter."""
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    # Mock 후보는 블록 수를 늘리지 않으므로 richness 하한(§8.13)을 이전 블록 수로 둔다. 하한 자체는 richness 테스트가 본다.
    monkeypatch.setattr(designer, "RICHNESS_MIN_DELTA", 0)
    calls = {"design": 0, "judge": 0, "feedbacks": [], "judges": [], "style_hints": [], "min_blocks": []}
    replies = {"judge": [judge()], "design": None}

    def fake_generate(design, current, differences, reasons=None, should_stop=None, feedback=None, min_blocks=None,
                      style_hint=None):
        calls["design"] += 1
        calls["min_blocks"].append(min_blocks)
        calls["style_hints"].append(style_hint)
        calls["feedbacks"].append(feedback)
        if replies["design"] is not None:
            return replies["design"](calls["design"])
        return designer.mock_revised_candidate(design, current, differences)

    def fake_judge(previous, design, current, differences, should_stop=None):
        calls["judge"] += 1
        sequence = replies["judge"]
        reply = sequence[min(calls["judge"], len(sequence)) - 1]
        calls["judges"].append(reply)
        return reply

    monkeypatch.setattr(main.llm, "generate_revised_design", fake_generate)
    monkeypatch.setattr(main.llm, "judge_revised_design", fake_judge)
    return calls, replies


def _revise(scenario):
    design, current, differences = scenario
    result = main.run_intervention(design, current, differences, text_answers=["2번"])
    assert set(result) == ENVELOPE_KEYS
    return result


def test_regeneration_cap_is_one():
    assert main.METADATA_REGENERATIONS_MAX == 1


def test_a_unrecognizable_twice_regenerates_exactly_once(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [judge(recognizable_family=False, family_confidence="mismatch"),
                        judge(recognizable_family=False, family_confidence="mismatch")]
    result = _revise(scenario)
    metadata = result["design_metadata"]
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert metadata["regenerations"] == 1  # design regenerations for this request
    assert (calls["design"], calls["judge"]) == (2, 2)
    assert calls["feedbacks"][0] is None and "JUDGE FEEDBACK" in calls["feedbacks"][1]
    assert calls["style_hints"] == [None, None]  # the regeneration gets the same (absent) style_hint
    assert metadata["judge"]["recognizable_family"] is False and metadata["judge"]["verdict"] == "NOT_YET"
    assert metadata["error"] is None


def test_b_judge_missing_required_field_does_not_regenerate(scenario, llm_mode):
    calls, replies = llm_mode
    broken = judge()
    del broken["silhouette_clarity"]
    replies["judge"] = [broken]
    result = _revise(scenario)
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and result["design"] is not None
    assert metadata["regenerations"] == 0
    assert (calls["design"], calls["judge"]) == (1, 1)
    assert metadata["judge"] is None
    assert metadata["error"]["kind"] == "judge_error" and "silhouette_clarity" in metadata["error"]["message"]
    assert metadata["design_name"] is None and metadata["design_family"] is None  # names come only from the judge
    assert metadata["design_intent"] is None


@pytest.mark.parametrize("bad", [{"silhouette_clarity": "fuzzy"}, {"recognizable_family": "yes"}, {"reads_as_seating": None}])
def test_b_judge_unexpected_value_does_not_regenerate(scenario, llm_mode, bad):
    calls, replies = llm_mode
    replies["judge"] = [judge(**bad)]
    metadata = _revise(scenario)["design_metadata"]
    assert metadata["regenerations"] == 0
    assert (calls["design"], calls["judge"]) == (1, 1)
    assert metadata["error"]["kind"] == "judge_error"


def test_c_ambiguous_silhouette_regenerates_once(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [judge(silhouette_clarity="ambiguous"), judge()]
    metadata = _revise(scenario)["design_metadata"]
    assert metadata["regenerations"] == 1
    assert (calls["design"], calls["judge"]) == (2, 2)
    assert metadata["judge"]["silhouette_clarity"] == "clear" and metadata["judge"]["verdict"] == "SHOWCASE"


def test_d_awkward_or_weakly_visible_only_does_not_regenerate(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [judge(awkward="오른쪽 팔걸이가 짧다", interpretation_status="weakly visible", layer5_meaningful=False,
                              feature_check=[{"planned": "crown", "status": "mismatch"}], completeness_score=2)]
    metadata = _revise(scenario)["design_metadata"]
    assert metadata["regenerations"] == 0
    assert (calls["design"], calls["judge"]) == (1, 1)
    assert metadata["judge"]["verdict"] == "SHOWCASE"  # verdict ignores feature_check / awkward by definition
    assert metadata["interpretation_status"] == "weakly visible" and metadata["judge"]["awkward"] == "오른쪽 팔걸이가 짧다"


def test_e_judge_llm_error_does_not_regenerate(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [{"llm_error": {"kind": "timeout", "message": "no response within 30 s"}}]
    result = _revise(scenario)
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and result["design"] is not None  # metadata failure never fails the design
    assert metadata["regenerations"] == 0
    assert (calls["design"], calls["judge"]) == (1, 1)
    assert metadata["judge"] is None
    assert metadata["error"]["kind"] == "judge_error" and "timeout" in metadata["error"]["message"]


def test_f_revised_has_no_design_intent_step(scenario, llm_mode, monkeypatch):
    """Wave 4 After 구조: 설계 의도 호출이 없고 metadata.design_intent는 가짜로 채우지 않는다."""
    calls, replies = llm_mode
    monkeypatch.setattr(main.llm, "generate_design_intent",
                        lambda *a, **k: pytest.fail("Revised must not call a design-intent step"), raising=False)
    result = _revise(scenario)
    metadata = result["design_metadata"]
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert (calls["design"], calls["judge"]) == (1, 1)
    assert metadata["design_intent"] is None and metadata["error"] is None
    assert metadata["design_name"] == "푸른 왕좌" and metadata["design_family"] == "throne"


def test_g_metadata_never_changes_the_design_shape_or_version(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [judge(recognizable_family=False), judge()]
    design, current, _ = scenario
    result = _revise(scenario)
    assert result["design_metadata"]["regenerations"] == 1
    assert set(result["design"]) == {"design_version", "blocks"}
    assert result["design"]["design_version"] == design["design_version"] + 1
    assert validator.validate_design(result["design"]) == []
    assert validator.validate_revised({"blocks": result["design"]["blocks"]}, current) == []
    assert "design_metadata" not in result["design"]
    assert set(result["design_metadata"]) == REVISED_METADATA_KEYS
    assert result["design_metadata"]["human_interpretation"]["lego_redesign"] == "그래서 넓은 받침으로 발전시켰다"
    json.dumps(result)  # the whole envelope stays JSON-serialisable


def test_h_initial_metadata_llm(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(main.llm, "generate_initial_design",
                        lambda object_type, reasons=None, should_stop=None, family=None, style_hint=None:
                        designer.mock_initial_candidate(object_type))
    described = {"design_family": "high-back chair", "design_name": "높은 의자", "design_summary": "높은 등받이 의자",
                 "visible_features": ["좌석 6×6"], "why_it_is_complete": "다 있다", "silhouette_clarity": "clear",
                 "recognizable_family": True, "completeness_score": 4, "family_design_match": "clear"}
    monkeypatch.setattr(main.llm, "choose_initial_family", lambda preference, rng=None: "high-back chair")
    monkeypatch.setattr(main.llm, "describe_initial_design", lambda design, should_stop=None, family=None: described)
    result = main.create_initial_design(text=GOAL_TEXT)
    assert set(result) == ENVELOPE_KEYS and result["status"] == "OK"
    assert result["design_metadata"] == {
        "design_name": "높은 의자", "design_family": "high-back chair", "design_summary": "높은 등받이 의자",
        "visible_features": ["좌석 6×6"], "human_interpretation": None,
        "judge": {"silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4},
        "preference": None, "selected_family": "high-back chair", "family_source": "random", "style_hint": None,
        "family_design_match": "clear", "source": "LLM", "error": None,
    }
    assert result["questions"] == []  # 텍스트 모드에서 선호 답이 없으면 선호 질문을 하지 않는다
    assert set(result["design"]) == {"design_version", "blocks"} and result["design"]["design_version"] == 1


def test_h_initial_describe_failure_keeps_the_design(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(main.llm, "generate_initial_design",
                        lambda object_type, reasons=None, should_stop=None, family=None, style_hint=None:
                        designer.mock_initial_candidate(object_type))
    monkeypatch.setattr(main.llm, "describe_initial_design",
                        lambda design, should_stop=None, family=None: {"llm_error": {"kind": "auth", "message": "HTTP 401"}})
    result = main.create_initial_design(text=GOAL_TEXT)
    assert result["status"] == "OK" and result["design"] is not None
    assert result["design_metadata"]["error"] == {"kind": "describe_error", "message": str({"kind": "auth", "message": "HTTP 401"})}
    assert result["design_metadata"]["design_name"] is None and result["design_metadata"]["judge"] is None


def test_h_initial_mock_metadata(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    result = main.create_initial_design(text=GOAL_TEXT)
    assert result["design_metadata"]["source"] == "MOCK" and result["design_metadata"]["design_name"] == "Mock 의자"


def test_i_provider_retries_are_independent_of_regeneration(scenario, llm_mode, monkeypatch):
    calls, replies = llm_mode
    replies["judge"] = [judge(recognizable_family=False), judge(recognizable_family=False)]
    # the real generator over a fake transport: every design request times out once before it answers
    monkeypatch.setattr(main.llm, "generate_revised_design", _REAL_GENERATE_REVISED)
    monkeypatch.setenv(llm.LLM_KEY_ENV, "sk-test-FAKE-LLM-000000000000")
    monkeypatch.setattr(llm, "RETRY_BACKOFF", (0, 0, 0))
    design, current, differences = scenario
    candidate = designer.mock_revised_candidate(design, current, differences)
    posts = {"n": 0}

    def flaky_post(payload, api_key):
        posts["n"] += 1
        if posts["n"] % 2 == 1:
            raise TimeoutError("slow provider")
        return {"choices": [{"message": {"content": json.dumps(candidate)}}]}

    monkeypatch.setattr(llm, "_post_json", flaky_post)
    result = _revise(scenario)
    assert result["status"] == "OK"
    assert result["design_metadata"]["regenerations"] == 1  # capped, not inflated by provider retries
    assert posts["n"] == 4  # 2 design builds x (1 timeout + 1 answer): provider retries stay inside llm._call
    assert calls["judge"] == 2


def test_regeneration_that_fails_keeps_the_first_design(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [judge(recognizable_family=False)]
    first = {}

    def design_reply(n):
        if n == 1:
            first["candidate"] = designer.mock_revised_candidate(*scenario)
            return first["candidate"]
        return {"llm_error": {"kind": "server", "message": "HTTP 503"}}

    replies["design"] = design_reply
    result = _revise(scenario)
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and result["design"]["blocks"] == first["candidate"]["blocks"]
    assert metadata["regenerations"] == 1
    assert (calls["design"], calls["judge"]) == (2, 1)
    assert metadata["error"]["kind"] == "regeneration_failed"
    assert metadata["judge"]["recognizable_family"] is False  # the first design's judge is kept


def test_stop_during_judge_cancels(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [{"llm_error": {"kind": "stopped", "message": "stopped before the next API retry"}}]
    result = _revise(scenario)
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED")
    assert result["design_metadata"] is None


def test_keep_and_mock_revise_metadata(scenario, monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    design, current, differences = scenario
    keep = main.run_intervention(design, current, differences, text_answers=["1번"])
    assert keep["hri_result"] == "KEEP" and keep["design_metadata"] is None
    revised = main.run_intervention(design, current, differences, text_answers=["2번"])
    assert revised["design_metadata"]["source"] == "MOCK" and revised["design_metadata"]["regenerations"] == 0
    assert set(revised["design_metadata"]) == MOCK_REVISED_METADATA_KEYS


# ---------------------------------------------------------------------------
# Stage 2 Wave 3: Initial 선호 질문 → family 선택 (fake LLM, fake voice)
# ---------------------------------------------------------------------------

INITIAL_METADATA_KEYS = {"design_name", "design_family", "design_summary", "visible_features", "human_interpretation",
                         "judge", "preference", "selected_family", "family_source", "style_hint", "family_design_match",
                         "source", "error"}


@pytest.fixture
def initial_llm(monkeypatch):
    """LLM 모드 Initial: 선호 해석·family 선택·생성·설명을 fake로 바꾸고 인자를 기록한다."""
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    calls = {"interpret": [], "choose": [], "generate": [], "describe": []}
    replies = {"interpret": None}
    real_choose = llm.choose_initial_family

    def fake_interpret(text, should_stop=None):
        calls["interpret"].append(text)
        return replies["interpret"]

    def fake_choose(preference, rng=None):
        calls["choose"].append(preference)
        return real_choose(preference, rng=random.Random(0))

    def fake_generate(object_type, reasons=None, should_stop=None, family=None, style_hint=None):
        calls["generate"].append({"family": family, "style_hint": style_hint})
        return designer.mock_initial_candidate(object_type)

    def fake_describe(design, should_stop=None, family=None):
        calls["describe"].append(family)
        return {"design_family": family, "design_name": "의자", "design_summary": "요약", "visible_features": [],
                "silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4,
                "family_design_match": "clear"}

    monkeypatch.setattr(main.llm, "interpret_initial_preference", fake_interpret)
    monkeypatch.setattr(main.llm, "choose_initial_family", fake_choose)
    monkeypatch.setattr(main.llm, "generate_initial_design", fake_generate)
    monkeypatch.setattr(main.llm, "describe_initial_design", fake_describe)
    return calls, replies


def _preference(family, style_hint, kind="SPECIFIC"):
    return {"preference": kind, "family": family, "style_hint": style_hint, "reply": f"좋아요, {family}로 해볼게요."}


def test_initial_any_answer_picks_random_family_without_llm_interpretation(initial_llm):
    calls, _ = initial_llm
    shown = []
    result = main.create_initial_design(text=GOAL_TEXT, preference_text="아무거나 괜찮아요", on_question=shown.append)
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and set(result["design"]) == {"design_version", "blocks"}
    assert result["questions"] == shown == [dialogue.INITIAL_PREFERENCE_QUESTION]
    assert calls["interpret"] == [] and calls["choose"] == [None]
    expected_family = llm.choose_initial_family(None, rng=random.Random(0))
    assert calls["generate"][0] == {"family": expected_family, "style_hint": None}
    assert calls["describe"] == [expected_family]
    assert set(metadata) == INITIAL_METADATA_KEYS
    assert (metadata["selected_family"], metadata["family_source"], metadata["preference"]) == (expected_family, "random", None)
    assert metadata["family_design_match"] == "clear" and metadata["error"] is None


@pytest.mark.parametrize("answer, family, style_hint", [
    ("팔걸이가 있는 빨간 의자요", "armchair", "빨간 팔걸이"),
    ("왕좌처럼 높고 화려한 의자요", "throne", "높고 화려한"),
])
def test_initial_specific_preference_selects_that_family(initial_llm, answer, family, style_hint):
    calls, replies = initial_llm
    replies["interpret"] = _preference(family, style_hint)
    result = main.create_initial_design(text=GOAL_TEXT, preference_text=answer)
    metadata = result["design_metadata"]
    assert result["status"] == "OK"
    assert calls["interpret"] == [answer]
    assert calls["generate"][0] == {"family": family, "style_hint": style_hint}
    assert calls["describe"] == [family]
    assert metadata["preference"] == replies["interpret"]
    assert (metadata["selected_family"], metadata["family_source"], metadata["style_hint"]) == (family, "preference", style_hint)
    json.dumps(result)


@pytest.mark.parametrize("reply", [{"llm_error": {"kind": "server", "message": "HTTP 503"}},
                                   {"preference": "SPECIFIC", "family": "throne"}])
def test_initial_preference_failure_falls_back_to_random_family(initial_llm, reply):
    calls, replies = initial_llm
    replies["interpret"] = reply
    result = main.create_initial_design(text=GOAL_TEXT, preference_text="왕좌처럼 높고 화려한 의자요")
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and calls["choose"] == [None]
    assert metadata["family_source"] == "random" and metadata["preference"] is None
    assert metadata["error"]["kind"] == "preference_error"


def test_initial_mock_mode_asks_nothing(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(main.llm, "interpret_initial_preference", lambda *a, **k: pytest.fail("Mock must not interpret"))
    result = main.create_initial_design(text=GOAL_TEXT, preference_text="왕좌요")
    assert result["status"] == "OK" and result["questions"] == []
    assert result["design_metadata"]["source"] == "MOCK"


def test_initial_invalid_preference_text_is_invalid_input(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    result = main.create_initial_design(text=GOAL_TEXT, preference_text=3)
    assert (result["status"], result["error"]["code"]) == ("FAILED", "INVALID_INPUT")


@pytest.fixture
def fake_voice(monkeypatch):
    events, heard = [], []

    def listen(on_ready=None):
        reply = heard.pop(0)
        events.append(("listen", reply))
        return reply

    monkeypatch.setattr(main.voice, "listen", listen)
    monkeypatch.setattr(main.voice, "speak", lambda sentence: events.append(("speak", sentence)))
    return events, heard


def test_initial_voice_mode_speaks_question_then_listens_then_reads_back(initial_llm, fake_voice):
    calls, replies = initial_llm
    events, heard = fake_voice
    heard.extend(["의자 만들어줘", "왕좌처럼 높고 화려한 의자요"])
    replies["interpret"] = _preference("throne", "높고 화려한")
    result = main.create_initial_design()
    assert result["status"] == "OK" and result["questions"] == [dialogue.INITIAL_PREFERENCE_QUESTION]
    assert events == [("listen", "의자 만들어줘"), ("speak", dialogue.INITIAL_PREFERENCE_QUESTION),
                      ("listen", "왕좌처럼 높고 화려한 의자요"), ("speak", "좋아요, throne로 해볼게요.")]
    assert result["design_metadata"]["selected_family"] == "throne"


def test_initial_voice_silence_is_any(initial_llm, fake_voice):
    calls, _ = initial_llm
    events, heard = fake_voice
    heard.extend(["의자 만들어줘", ""])
    result = main.create_initial_design()
    assert result["status"] == "OK" and calls["interpret"] == [] and calls["choose"] == [None]
    assert result["design_metadata"]["family_source"] == "random"


def test_initial_voice_preference_listen_failure_is_voice_io_failed(initial_llm, fake_voice):
    calls, _ = initial_llm
    events, heard = fake_voice
    heard.extend(["의자 만들어줘", None])
    result = main.create_initial_design()
    assert (result["status"], result["error"]["code"]) == ("FAILED", "VOICE_IO_FAILED")
    assert result["questions"] == [dialogue.INITIAL_PREFERENCE_QUESTION] and calls["generate"] == []


def test_initial_stop_before_preference_question_cancels(initial_llm):
    calls, _ = initial_llm
    result = main.create_initial_design(text=GOAL_TEXT, preference_text="아무거나", should_stop=lambda: True)
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED")
    assert result["questions"] == [] and calls["generate"] == []


def test_initial_stop_during_preference_interpretation_cancels(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = {"llm_error": {"kind": "stopped", "message": "stopped"}}
    result = main.create_initial_design(text=GOAL_TEXT, preference_text="왕좌처럼 높고 화려한 의자요")
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED")
    assert result["questions"] == [dialogue.INITIAL_PREFERENCE_QUESTION] and calls["generate"] == []


# ---------------------------------------------------------------------------
# Stage 2 Wave 3: Intervention 자유 답변 → LLM fallback·style_hint → Revised (min_blocks, judge 확장)
# ---------------------------------------------------------------------------


@pytest.fixture
def answer_llm(monkeypatch, llm_mode):
    calls, replies = llm_mode
    calls["answers"] = []
    replies["answer"] = {"decision": "REVISE", "style_hint": "좌석을 넓고 화려하게", "reason": "더 화려하게 원하셨어요."}

    def fake_answer(text, differences, should_stop=None):
        calls["answers"].append(text)
        reply = replies["answer"]
        return reply.pop(0) if isinstance(reply, list) else reply

    monkeypatch.setattr(main.llm, "interpret_intervention_answer", fake_answer)
    return calls, replies


def _answer(scenario, *answers):
    design, current, differences = scenario
    return main.run_intervention(design, current, differences, text_answers=list(answers))


def test_intervention_clear_keep_answer_needs_no_llm(scenario, answer_llm):
    calls, _ = answer_llm
    result = _answer(scenario, "제가 잘못 놨어요. 다시 고칠게요.")
    assert (result["status"], result["hri_result"]) == ("OK", "KEEP") and result["design"] == scenario[0]
    assert calls["answers"] == [] and calls["design"] == 0


def test_intervention_clear_revise_answer_takes_style_hint_from_llm_once(scenario, answer_llm):
    """FIX-1: Rule이 REVISE로 정한 자유 답변도 LLM에서 style_hint만 받는다(decision은 Rule 그대로)."""
    calls, replies = answer_llm
    replies["answer"] = {"decision": "KEEP", "style_hint": "팔걸이로", "reason": "무시돼야 하는 decision"}
    answer = "일부러 그렇게 놨어요. 팔걸이로 살려주세요."
    assert dialogue.parse_response(answer) == dialogue.REVISE
    result = _answer(scenario, answer)
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert calls["answers"] == [answer]
    assert calls["style_hints"] == ["팔걸이로"]
    assert result["design_metadata"]["style_hint"] == "팔걸이로"


@pytest.mark.parametrize("answer", ["2번", "2번이요", "이번", "2"])
def test_intervention_number_revise_answer_calls_no_llm(scenario, answer_llm, answer):
    calls, _ = answer_llm
    result = _answer(scenario, answer)
    assert result["hri_result"] == "REVISE"
    assert calls["answers"] == [] and calls["style_hints"] == [None]
    assert result["design_metadata"]["style_hint"] is None


def test_intervention_short_yes_calls_llm_once_and_empty_hint_is_none(scenario, answer_llm):
    calls, replies = answer_llm
    replies["answer"] = {"decision": "REVISE", "style_hint": "", "reason": "의도하셨어요."}
    result = _answer(scenario, "네")
    assert result["hri_result"] == "REVISE"
    assert calls["answers"] == ["네"] and calls["style_hints"] == [None]
    assert result["design_metadata"]["style_hint"] is None


@pytest.mark.parametrize("reply", [{"llm_error": {"kind": "server", "message": "HTTP 503"}}, {"decision": "REVISE"}])
def test_intervention_style_hint_failure_still_revises_without_reask(scenario, answer_llm, reply):
    calls, replies = answer_llm
    replies["answer"] = reply
    result = _answer(scenario, "일부러 그렇게 놨어요. 팔걸이로 살려주세요.")
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert len(result["questions"]) == 1 and calls["answers"] == ["일부러 그렇게 놨어요. 팔걸이로 살려주세요."]
    assert calls["style_hints"] == [None]
    assert result["design_metadata"]["style_hint"] is None and result["design_metadata"]["error"] is None


def test_intervention_stop_during_style_hint_cancels(scenario, answer_llm):
    calls, replies = answer_llm
    replies["answer"] = {"llm_error": {"kind": "stopped", "message": "stopped"}}
    result = _answer(scenario, "일부러 그렇게 놨어요. 팔걸이로 살려주세요.")
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED") and calls["design"] == 0


@pytest.mark.parametrize("answer", ["제가 잘못 놨어요. 다시 고칠게요.", "1번", "취소할게"])
def test_intervention_keep_or_cancel_calls_no_llm(scenario, answer_llm, answer):
    calls, _ = answer_llm
    result = _answer(scenario, answer)
    assert result["hri_result"] in ("KEEP", None) and calls["answers"] == []


@pytest.mark.parametrize("answer", ["좀 더 넓고 화려하게 하고 싶어요.", "실수 아니에요"])
def test_intervention_unclear_rule_goes_to_llm_and_style_hint_reaches_generator(scenario, answer_llm, answer):
    calls, replies = answer_llm
    assert dialogue.parse_response(answer) == dialogue.UNCLEAR  # Rule alone cannot decide
    result = _answer(scenario, answer)
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert calls["answers"] == [answer]  # fallback이 이미 해석했으므로 style_hint용 두 번째 호출 없음
    assert calls["style_hints"] == ["좌석을 넓고 화려하게"]
    assert result["design_metadata"]["style_hint"] == "좌석을 넓고 화려하게"
    assert len(result["questions"]) == 1


@pytest.mark.parametrize("reply", [{"decision": "UNCLEAR", "style_hint": "", "reason": "판단하기 어려워요."},
                                   {"llm_error": {"kind": "server", "message": "HTTP 503"}},
                                   {"decision": "REVISE"}])
def test_intervention_llm_unclear_or_failure_reasks(scenario, answer_llm, reply):
    calls, replies = answer_llm
    replies["answer"] = [reply]
    result = _answer(scenario, "음 그게요", "2번")
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert len(result["questions"]) == 2 and "잘 못 알아들었어요" in result["questions"][1]
    assert calls["style_hints"] == [None]


def test_intervention_llm_keep_decision_keeps_design(scenario, answer_llm):
    calls, replies = answer_llm
    replies["answer"] = {"decision": "KEEP", "style_hint": "", "reason": "실수였어요."}
    result = _answer(scenario, "음 그게요")
    assert (result["status"], result["hri_result"]) == ("OK", "KEEP") and calls["design"] == 0


def test_intervention_stop_during_answer_interpretation_cancels(scenario, answer_llm):
    calls, replies = answer_llm
    replies["answer"] = {"llm_error": {"kind": "stopped", "message": "stopped"}}
    result = _answer(scenario, "음 그게요", "2번")
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED") and calls["design"] == 0


def test_intervention_mock_mode_has_no_llm_fallback(scenario, monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(main.llm, "interpret_intervention_answer", lambda *a, **k: pytest.fail("Mock must not call LLM"))
    result = _answer(scenario, "좀 더 넓고 화려하게 하고 싶어요.")
    assert (result["status"], result["hri_result"]) == ("OK", "UNCLEAR")


def test_min_blocks_reaches_designer_and_generator_including_extra_attempts(scenario, llm_mode, monkeypatch):
    calls, replies = llm_mode
    monkeypatch.setattr(designer, "RICHNESS_MIN_DELTA", 6)  # 실제 정책 값
    design = scenario[0]
    expected = designer.revised_min_blocks(design)
    seen = []
    real_build = designer.build_revised_design

    def spy_build(*args, **kwargs):
        seen.append(kwargs.get("min_blocks"))
        return real_build(*args, **kwargs)

    monkeypatch.setattr(main.designer, "build_revised_design", spy_build)
    # Mock 후보는 블록이 늘지 않아 매번 too_few_blocks로 탈락 → escalation → 계속 찾기 → 남은 4회도 탈락
    result = _answer(scenario, "2번", "계속 찾아 주세요")
    assert expected == len(design["blocks"]) + 6
    assert seen == [expected, expected]
    assert calls["min_blocks"] == [expected] * designer.MAX_ATTEMPTS
    assert (result["status"], result["error"]["code"]) == ("FAILED", "DESIGN_GENERATION_FAILED")
    assert {r["rule"] for r in result["error"]["details"]} == {"too_few_blocks"}


def test_mock_mode_passes_no_min_blocks(scenario, monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    seen = []
    real_build = designer.build_revised_design

    def spy_build(*args, **kwargs):
        seen.append(kwargs.get("min_blocks"))
        return real_build(*args, **kwargs)

    monkeypatch.setattr(main.designer, "build_revised_design", spy_build)
    assert _answer(scenario, "2번")["hri_result"] == "REVISE"
    assert seen == [None]


@pytest.mark.parametrize("bad", [{"chair_likeness": "not_chair"}, {"richer_than_previous": False}])
def test_not_chair_or_not_richer_regenerates_once_only(scenario, llm_mode, bad):
    calls, replies = llm_mode
    replies["judge"] = [judge(**bad), judge(**bad)]
    metadata = _revise(scenario)["design_metadata"]
    assert metadata["regenerations"] == 1
    assert (calls["design"], calls["judge"]) == (2, 2)
    assert metadata["judge"]["verdict"] == "NOT_YET"


def test_weak_chair_likeness_does_not_regenerate_and_keeps_showcase(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [judge(chair_likeness="weak")]
    metadata = _revise(scenario)["design_metadata"]
    assert metadata["regenerations"] == 0 and calls["design"] == 1
    assert metadata["judge"]["verdict"] == "SHOWCASE"


def test_revised_metadata_carries_stage2_judge_fields(scenario, llm_mode):
    metadata = _revise(scenario)["design_metadata"]
    assert set(metadata) == REVISED_METADATA_KEYS
    assert {key: metadata["judge"][key] for key in ("chair_likeness", "richer_than_previous", "richer_why")} == {
        "chair_likeness": "clear", "richer_than_previous": True, "richer_why": "받침과 crown이 늘었다"}


@pytest.mark.parametrize("missing", ["chair_likeness", "richer_than_previous"])
def test_missing_stage2_judge_field_is_judge_error(scenario, llm_mode, missing):
    calls, replies = llm_mode
    broken = judge()
    del broken[missing]
    replies["judge"] = [broken]
    metadata = _revise(scenario)["design_metadata"]
    assert metadata["regenerations"] == 0 and metadata["judge"] is None
    assert metadata["error"]["kind"] == "judge_error" and missing in metadata["error"]["message"]
