"""design_metadata and the judge-driven regeneration cap (docs/C_DESIGN_CONTRACT.md §6, §8.12).

No real LLM or network: the intent / generator / judge / describe functions of llm are replaced per test.
Every Revised test asserts the number of design regenerations for one request (at most
main.METADATA_REGENERATIONS_MAX == 1) and how many design / judge calls were made.
"""

import json

import pytest

from app.c_design import designer, llm, main, validator

GOAL_TEXT = "의자 만들어줘"
_REAL_GENERATE_REVISED = llm.generate_revised_design  # saved before any test replaces it
ENVELOPE_KEYS = {"status", "hri_result", "design", "design_metadata", "questions", "error"}
REVISED_METADATA_KEYS = {"design_name", "design_family", "design_summary", "visible_features", "human_interpretation",
                         "change_summary", "interpretation_status", "judge", "design_intent", "regenerations", "source", "error"}

INTENT = {
    "parent_family": "throne", "variation": "none", "design_family": "throne", "concept_name": "왕좌",
    "recognition_cue": "넓은 받침, 높은 등받이, 양쪽 팔걸이", "human_reading": "놓인 블록을 받침 모서리로 해석했다",
    "misplaced_block_meaning": "받침의 한 모서리", "planned_visible_features": ["좌석 6×6", "등받이 3층"],
    f"layer{validator.MAX_LAYER}_feature": "등받이 위 crown", "geometry_plan": "plinth under the seat, back behind it",
    "style_hint_used": "없음", "target_blocks": 21,  # Stage 2 Wave 2 INTENT_KEYS
}


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
    calls = {"intent": 0, "design": 0, "judge": 0, "design_intents": [], "feedbacks": [], "judges": []}
    replies = {"intent": INTENT, "judge": [judge()], "design": None}

    def fake_intent(design, current, differences, recent_families=(), should_stop=None):
        calls["intent"] += 1
        return replies["intent"]

    def fake_generate(design, current, differences, reasons=None, should_stop=None, intent=None, feedback=None):
        calls["design"] += 1
        calls["design_intents"].append(intent)
        calls["feedbacks"].append(feedback)
        if replies["design"] is not None:
            return replies["design"](calls["design"])
        return designer.mock_revised_candidate(design, current, differences)

    def fake_judge(intent, previous, design, current, differences, should_stop=None):
        calls["judge"] += 1
        sequence = replies["judge"]
        reply = sequence[min(calls["judge"], len(sequence)) - 1]
        calls["judges"].append(reply)
        return reply

    monkeypatch.setattr(main.llm, "generate_design_intent", fake_intent)
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
    assert (calls["design"], calls["judge"], calls["intent"]) == (2, 2, 1)
    assert calls["feedbacks"][0] is None and "JUDGE FEEDBACK" in calls["feedbacks"][1]
    assert calls["design_intents"] == [INTENT, INTENT]  # same intent for the regeneration
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
    assert metadata["design_name"] == INTENT["concept_name"] and metadata["design_family"] == INTENT["design_family"]


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


@pytest.mark.parametrize("intent_reply", [{"llm_error": {"kind": "server", "message": "HTTP 500"}}, {"parent_family": "throne"}])
def test_f_intent_failure_continues_without_intent(scenario, llm_mode, intent_reply):
    calls, replies = llm_mode
    replies["intent"] = intent_reply
    result = _revise(scenario)
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and result["hri_result"] == "REVISE"
    assert metadata["regenerations"] == 0
    assert (calls["design"], calls["judge"]) == (1, 1)
    assert calls["design_intents"] == [None]
    assert metadata["design_intent"] is None
    assert metadata["error"]["kind"] == "intent_error"
    assert metadata["design_name"] == "푸른 왕좌"  # judge still names it


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
                        lambda object_type, reasons=None, should_stop=None: designer.mock_initial_candidate(object_type))
    described = {"design_family": "high-back chair", "design_name": "높은 의자", "design_summary": "높은 등받이 의자",
                 "visible_features": ["좌석 6×6"], "why_it_is_complete": "다 있다", "silhouette_clarity": "clear",
                 "recognizable_family": True, "completeness_score": 4}
    monkeypatch.setattr(main.llm, "describe_initial_design", lambda design, should_stop=None: described)
    result = main.create_initial_design(text=GOAL_TEXT)
    assert set(result) == ENVELOPE_KEYS and result["status"] == "OK"
    assert result["design_metadata"] == {
        "design_name": "높은 의자", "design_family": "high-back chair", "design_summary": "높은 등받이 의자",
        "visible_features": ["좌석 6×6"], "human_interpretation": None,
        "judge": {"silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4},
        "source": "LLM", "error": None,
    }
    assert set(result["design"]) == {"design_version", "blocks"} and result["design"]["design_version"] == 1


def test_h_initial_describe_failure_keeps_the_design(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(main.llm, "generate_initial_design",
                        lambda object_type, reasons=None, should_stop=None: designer.mock_initial_candidate(object_type))
    monkeypatch.setattr(main.llm, "describe_initial_design",
                        lambda design, should_stop=None: {"llm_error": {"kind": "auth", "message": "HTTP 401"}})
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
    assert set(revised["design_metadata"]) == REVISED_METADATA_KEYS
