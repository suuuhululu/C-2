"""design_metadata, the judge-driven regeneration cap and the Stage 2 wiring (docs/C_DESIGN_CONTRACT.md §4, §6, §8.12, §8.13).

No real LLM or network: the generator / judge / describe / interpretation functions of llm are replaced per test.
Stage 2 Wave 4 (After 구조): Revised has no design-intent step; design_intent in metadata is always None.
Every Revised test asserts the number of design regenerations for one request (at most
main.METADATA_REGENERATIONS_MAX == 1) and how many design / judge calls were made.
"""

import json
import random
import re

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
                        lambda object_type, reasons=None, should_stop=None, family=None, style_hint=None, concept=None:
                        designer.mock_initial_candidate(object_type))
    monkeypatch.setattr(main.llm, "interpret_initial_request", lambda text, should_stop=None: _request("ANY"),
                        raising=False)
    monkeypatch.setattr(main.llm, "REQUEST_KEYS", REQUEST_KEYS, raising=False)  # A의 Wave 4b 상수(병합 전 대비)
    described = {"design_family": "high-back chair", "design_name": "높은 의자", "design_summary": "높은 등받이 의자",
                 "visible_features": ["좌석 6×6"], "why_it_is_complete": "다 있다", "silhouette_clarity": "clear",
                 "recognizable_family": True, "completeness_score": 4, "family_design_match": "clear"}
    monkeypatch.setattr(main.llm, "choose_initial_family", lambda preference, rng=None: "high-back chair")
    monkeypatch.setattr(main.llm, "describe_initial_design", lambda design, should_stop=None, family=None, concept=None: described)
    result = main.create_initial_design(text=GOAL_TEXT)
    assert set(result) == ENVELOPE_KEYS and result["status"] == "OK"
    assert result["design_metadata"] == {
        "design_name": "높은 의자", "design_family": "high-back chair", "design_summary": "높은 등받이 의자",
        "visible_features": ["좌석 6×6"], "human_interpretation": None,
        "judge": {"silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4},
        "preference": _request("ANY"), "selected_family": "high-back chair", "family_source": "random", "style_hint": None,
        "family_design_match": "clear", "source": "LLM", "error": None,
    }
    assert result["questions"] == []  # 텍스트 모드: 첫 발화는 호출자가 받았고, 되묻기가 필요 없으면 질문이 없다
    assert set(result["design"]) == {"design_version", "blocks"} and result["design"]["design_version"] == 1


def test_h_initial_describe_failure_keeps_the_design(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(main.llm, "generate_initial_design",
                        lambda object_type, reasons=None, should_stop=None, family=None, style_hint=None, concept=None:
                        designer.mock_initial_candidate(object_type))
    monkeypatch.setattr(main.llm, "interpret_initial_request", lambda text, should_stop=None: _request("ANY"),
                        raising=False)
    monkeypatch.setattr(main.llm, "REQUEST_KEYS", REQUEST_KEYS, raising=False)  # A의 Wave 4b 상수(병합 전 대비)
    monkeypatch.setattr(main.llm, "describe_initial_design",
                        lambda design, should_stop=None, family=None, concept=None: {"llm_error": {"kind": "auth", "message": "HTTP 401"}})
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
# Stage 2 Wave 4b: Initial 인사 → 자유 발화 해석 → 되묻기 ≤1 → family / concept (fake LLM, fake voice)
# ---------------------------------------------------------------------------

INITIAL_METADATA_KEYS = {"design_name", "design_family", "design_summary", "visible_features", "human_interpretation",
                         "judge", "preference", "selected_family", "family_source", "style_hint", "family_design_match",
                         "source", "error"}
REQUEST_KEYS = ("object", "preference", "family", "style_hint", "sufficient", "follow_up", "reply")  # llm.REQUEST_KEYS(A)
FOLLOW_UP = "어떤 느낌의 의자가 좋으세요? 팔걸이나 색, 모양을 말씀해 주셔도 돼요."


def _request(preference, family=None, style_hint="", obj="CHAIR", sufficient=True, follow_up="", reply=""):
    return {"object": obj, "preference": preference, "family": family, "style_hint": style_hint,
            "sufficient": sufficient, "follow_up": follow_up, "reply": reply}


@pytest.fixture
def initial_llm(monkeypatch):
    """LLM 모드 Initial: 요청 해석·family 선택·생성·설명을 fake로 바꾸고 인자를 기록한다(A의 새 시그니처 가정)."""
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(main.llm, "REQUEST_KEYS", REQUEST_KEYS, raising=False)
    calls = {"interpret": [], "choose": [], "generate": [], "describe": []}
    replies = {"interpret": []}

    def fake_interpret(text, should_stop=None):
        calls["interpret"].append(text)
        return replies["interpret"].pop(0)

    def fake_choose(preference, rng=None):  # A의 Wave 4b 규칙: SPECIFIC 키 → 그 키, CREATIVE → None, 그 밖 균등
        calls["choose"].append(preference)
        if isinstance(preference, dict) and preference.get("preference") == "CREATIVE":
            return None
        if isinstance(preference, dict) and preference.get("preference") == "SPECIFIC" and preference.get("family") in llm.FAMILY_CATALOG:
            return preference["family"]
        return random.Random(0).choice(sorted(llm.FAMILY_CATALOG))

    def fake_generate(object_type, reasons=None, should_stop=None, family=None, style_hint=None, concept=None):
        calls["generate"].append({"object_type": object_type, "family": family, "style_hint": style_hint, "concept": concept})
        return designer.mock_initial_candidate(object_type)

    def fake_describe(design, should_stop=None, family=None, concept=None):
        calls["describe"].append({"family": family, "concept": concept})
        return {"design_family": family or "armchair", "design_name": "의자", "design_summary": "요약", "visible_features": [],
                "silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4,
                "family_design_match": "clear"}

    monkeypatch.setattr(main.llm, "interpret_initial_request", fake_interpret, raising=False)
    monkeypatch.setattr(main.llm, "choose_initial_family", fake_choose)
    monkeypatch.setattr(main.llm, "generate_initial_design", fake_generate)
    monkeypatch.setattr(main.llm, "describe_initial_design", fake_describe)
    return calls, replies


RANDOM_FAMILY = random.Random(0).choice(sorted(llm.FAMILY_CATALOG))


def test_initial_creative_concept_goes_to_generation_without_family(initial_llm):
    calls, replies = initial_llm
    request = _request("CREATIVE", style_hint="사과처럼 둥글고 빨간", reply="좋아요, 사과처럼 둥글고 빨간 의자로 만들어 볼게요.")
    replies["interpret"] = [request]
    result = main.create_initial_design(text="오늘은 사과 같은 의자를 만들고 싶어요")
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and set(result["design"]) == {"design_version", "blocks"}
    assert calls["interpret"] == ["오늘은 사과 같은 의자를 만들고 싶어요"]
    assert calls["generate"][0] == {"object_type": "CHAIR", "family": None, "style_hint": "사과처럼 둥글고 빨간",
                                    "concept": "사과처럼 둥글고 빨간"}
    assert calls["describe"] == [{"family": None, "concept": "사과처럼 둥글고 빨간"}]
    assert set(metadata) == INITIAL_METADATA_KEYS
    assert (metadata["selected_family"], metadata["family_source"], metadata["preference"]) == (None, "creative", request)
    assert result["questions"] == []
    json.dumps(result)


def test_initial_specific_request_selects_catalog_family(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [_request("SPECIFIC", family="bench", style_hint="길고 넓은")]
    result = main.create_initial_design(text="벤치처럼 길고 넓은 의자")
    metadata = result["design_metadata"]
    assert calls["generate"][0] == {"object_type": "CHAIR", "family": "bench", "style_hint": "길고 넓은", "concept": None}
    assert (metadata["selected_family"], metadata["family_source"], metadata["style_hint"]) == ("bench", "preference", "길고 넓은")


def test_initial_explicit_any_by_rule_needs_no_llm(initial_llm):
    calls, _ = initial_llm
    result = main.create_initial_design(text="아무거나 만들어 주세요")
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and calls["interpret"] == [] and calls["choose"] == [None]
    assert (metadata["selected_family"], metadata["family_source"], metadata["preference"]) == (RANDOM_FAMILY, "random", None)


def test_initial_any_with_style_word_goes_to_llm_and_stays_random(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [_request("ANY", style_hint="멋진")]
    result = main.create_initial_design(text="아무거나 멋진 의자")
    metadata = result["design_metadata"]
    assert calls["interpret"] == ["아무거나 멋진 의자"]
    assert calls["generate"][0] == {"object_type": "CHAIR", "family": RANDOM_FAMILY, "style_hint": "멋진", "concept": None}
    assert metadata["family_source"] == "random" and metadata["style_hint"] == "멋진"


def test_initial_insufficient_request_asks_one_follow_up_and_reinterprets(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [_request("ANY", sufficient=False, follow_up=FOLLOW_UP),
                            _request("SPECIFIC", family="armchair", style_hint="팔걸이가 넓은")]
    shown = []
    result = main.create_initial_design(text="뭔가 만들고 싶어요", preference_text="팔걸이가 넓은 의자요", on_question=shown.append)
    assert result["status"] == "OK"
    assert result["questions"] == shown == [FOLLOW_UP]
    assert calls["interpret"] == ["뭔가 만들고 싶어요", "뭔가 만들고 싶어요 / 팔걸이가 넓은 의자요"]
    assert result["design_metadata"]["selected_family"] == "armchair"


def test_initial_second_unclear_falls_back_to_random(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [_request("ANY", obj="UNCLEAR", sufficient=False, follow_up=FOLLOW_UP),
                            _request("ANY", obj="UNCLEAR", sufficient=False, follow_up=FOLLOW_UP)]
    result = main.create_initial_design(text="뭔가요", preference_text="음 글쎄요 그냥")
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and len(calls["interpret"]) == 2 and result["questions"] == [FOLLOW_UP]
    assert (metadata["family_source"], metadata["preference"]) == ("random", None)


def test_initial_insufficient_without_follow_up_answer_in_text_mode_is_random(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [_request("ANY", sufficient=False, follow_up=FOLLOW_UP)]
    result = main.create_initial_design(text="뭔가 만들고 싶어요")
    assert result["status"] == "OK" and result["questions"] == [] and len(calls["interpret"]) == 1
    assert result["design_metadata"]["family_source"] == "random"


def test_initial_follow_up_answer_any_by_rule_needs_no_second_llm_call(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [_request("ANY", sufficient=False, follow_up=FOLLOW_UP)]
    result = main.create_initial_design(text="뭔가 만들고 싶어요", preference_text="아무거나요")
    assert result["status"] == "OK" and len(calls["interpret"]) == 1 and result["questions"] == [FOLLOW_UP]


def test_initial_obvious_non_seating_object_fails_without_llm(initial_llm):
    calls, _ = initial_llm
    result = main.create_initial_design(text="자동차 만들어줘")  # D 계약: 지원 밖 사물에는 LLM 호출이 없다
    assert (result["status"], result["error"]["code"]) == ("FAILED", "UNSUPPORTED_OBJECT")
    assert calls["interpret"] == [] and calls["generate"] == [] and result["design"] is None


@pytest.mark.parametrize("first", [True, False])
def test_initial_unsupported_object_by_llm_fails(initial_llm, first):
    calls, replies = initial_llm
    unsupported = _request("ANY", obj="UNSUPPORTED")
    replies["interpret"] = ([unsupported] if first else
                            [_request("ANY", sufficient=False, follow_up=FOLLOW_UP), unsupported])
    result = main.create_initial_design(text="하늘을 나는 걸 만들고 싶어요" if first else "뭔가 만들고 싶어요",
                                        preference_text="하늘을 나는 거요")
    assert (result["status"], result["error"]["code"]) == ("FAILED", "UNSUPPORTED_OBJECT")
    assert result["design"] is None and calls["generate"] == [] and len(calls["interpret"]) == (1 if first else 2)


def test_initial_follow_up_answer_naming_non_seating_object_fails(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [_request("ANY", sufficient=False, follow_up=FOLLOW_UP)]
    result = main.create_initial_design(text="뭔가 만들고 싶어요", preference_text="책상이요")
    assert result["error"]["code"] == "UNSUPPORTED_OBJECT" and len(calls["interpret"]) == 1


@pytest.mark.parametrize("reply", [{"llm_error": {"kind": "server", "message": "HTTP 503"}},
                                   {"object": "CHAIR", "preference": "SPECIFIC"}])
def test_initial_request_failure_falls_back_to_random(initial_llm, reply):
    calls, replies = initial_llm
    replies["interpret"] = [reply]
    result = main.create_initial_design(text="왕좌처럼 높고 화려한 의자요")
    metadata = result["design_metadata"]
    assert result["status"] == "OK" and calls["choose"] == [None]
    assert metadata["family_source"] == "random" and metadata["preference"] is None
    assert metadata["error"]["kind"] == "request_error"


def test_initial_stop_during_request_interpretation_cancels(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [{"llm_error": {"kind": "stopped", "message": "stopped"}}]
    result = main.create_initial_design(text="왕좌처럼 높고 화려한 의자요")
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED") and calls["generate"] == []


def test_initial_mock_mode_is_unchanged(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(main.llm, "interpret_initial_request", lambda *a, **k: pytest.fail("Mock must not interpret"),
                        raising=False)
    result = main.create_initial_design(text="의자 만들어줘", preference_text="왕좌요")
    assert result["status"] == "OK" and result["questions"] == [] and result["design_metadata"]["source"] == "MOCK"
    assert main.create_initial_design(text="책상 만들어줘")["error"]["code"] == "UNSUPPORTED_OBJECT"


def test_initial_mock_voice_mode_listens_once_without_arguments(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    heard = []
    monkeypatch.setattr(main.voice, "listen", lambda: heard.append("listen") or "의자 만들어줘")  # D 호환: 인자 없음
    monkeypatch.setattr(main.voice, "speak", lambda sentence: pytest.fail("Mock must not speak"))
    assert main.create_initial_design()["status"] == "OK" and heard == ["listen"]


def test_initial_invalid_preference_text_is_invalid_input(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    result = main.create_initial_design(text=GOAL_TEXT, preference_text=3)
    assert (result["status"], result["error"]["code"]) == ("FAILED", "INVALID_INPUT")


@pytest.fixture
def fake_voice(monkeypatch):
    events, heard = [], []

    def listen(on_ready=None, mode="short", beep=False):
        reply = heard.pop(0)
        events.append(("listen", mode, beep, reply))
        return reply

    monkeypatch.setattr(main.voice, "prewarm", lambda: events.append(("prewarm",)) or True)
    monkeypatch.setattr(main.voice, "listen", listen)
    monkeypatch.setattr(main.voice, "speak", lambda sentence: events.append(("speak", sentence)))
    return events, heard


def test_initial_voice_mode_greets_listens_free_with_beep_then_reads_back(initial_llm, fake_voice):
    calls, replies = initial_llm
    events, heard = fake_voice
    heard.append("왕좌처럼 높고 화려한 의자요")
    replies["interpret"] = [_request("SPECIFIC", family="throne", style_hint="높고 화려한",
                                     reply="좋아요, 높고 화려한 왕좌로 만들어 볼게요.")]
    result = main.create_initial_design()
    assert result["status"] == "OK" and result["questions"] == [dialogue.GREETING]
    assert events == [("prewarm",), ("speak", dialogue.GREETING), ("listen", "free", True, "왕좌처럼 높고 화려한 의자요"),
                      ("speak", "좋아요, 높고 화려한 왕좌로 만들어 볼게요."),  # ack(해석 reply)
                      ("speak", dialogue.PROGRESS_MESSAGES["GENERATING"]), ("speak", dialogue.PROGRESS_MESSAGES["READY"])]
    assert result["design_metadata"]["selected_family"] == "throne"


def test_initial_voice_follow_up_is_spoken_and_heard_in_free_mode(initial_llm, fake_voice):
    calls, replies = initial_llm
    events, heard = fake_voice
    heard.extend(["뭔가 만들고 싶어요", "팔걸이가 넓은 의자요"])
    replies["interpret"] = [_request("ANY", sufficient=False, follow_up=FOLLOW_UP),
                            _request("SPECIFIC", family="armchair", style_hint="팔걸이가 넓은")]
    result = main.create_initial_design()
    assert result["questions"] == [dialogue.GREETING, FOLLOW_UP]
    assert [e for e in events if e[0] == "listen"] == [("listen", "free", True, "뭔가 만들고 싶어요"),
                                                       ("listen", "free", True, "팔걸이가 넓은 의자요")]


def test_initial_voice_silence_reasks_once_then_random(initial_llm, fake_voice):
    calls, _ = initial_llm
    events, heard = fake_voice
    heard.extend(["", ""])
    result = main.create_initial_design()
    assert result["status"] == "OK" and calls["interpret"] == [] and calls["choose"] == [None]
    assert result["questions"] == [dialogue.GREETING, dialogue.SILENCE_REASK]
    assert events[-3][0] == "speak" and events[-3][1] in dialogue.INITIAL_ACKS  # 무작위 fallback도 생성 전에 확인
    assert events[-2:] == [("speak", dialogue.PROGRESS_MESSAGES["GENERATING"]), ("speak", dialogue.PROGRESS_MESSAGES["READY"])]
    assert result["design_metadata"]["family_source"] == "random"


def test_initial_voice_silence_then_request_is_used(initial_llm, fake_voice):
    calls, replies = initial_llm
    events, heard = fake_voice
    heard.extend(["", "아무거나요"])
    result = main.create_initial_design()
    assert result["status"] == "OK" and calls["interpret"] == []
    assert result["questions"] == [dialogue.GREETING, dialogue.SILENCE_REASK]
    assert events[-3][1] in dialogue.INITIAL_ACKS  # 명시적 "아무거나"도 생성 전에 확인 문장을 읽는다


def test_initial_voice_unsupported_speaks_reply(initial_llm, fake_voice):
    calls, replies = initial_llm
    events, heard = fake_voice
    heard.append("책상 만들어줘")
    replies["interpret"] = [_request("ANY", obj="UNSUPPORTED")]
    result = main.create_initial_design()
    assert result["error"]["code"] == "UNSUPPORTED_OBJECT" and events[-1] == ("speak", dialogue.UNSUPPORTED_REPLY)


def test_initial_voice_listen_failure_is_voice_io_failed(initial_llm, fake_voice):
    calls, _ = initial_llm
    events, heard = fake_voice
    heard.append(None)
    result = main.create_initial_design()
    assert (result["status"], result["error"]["code"]) == ("FAILED", "VOICE_IO_FAILED")
    assert result["questions"] == [dialogue.GREETING] and calls["generate"] == []


def test_initial_voice_stop_before_greeting_cancels(initial_llm, fake_voice):
    calls, _ = initial_llm
    events, heard = fake_voice
    result = main.create_initial_design(should_stop=lambda: True)
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED")
    assert result["questions"] == [] and calls["generate"] == [] and ("speak", dialogue.GREETING) not in events


# ---------------------------------------------------------------------------
# Stage 2 Wave 3: Intervention 자유 답변 → LLM fallback·style_hint → Revised (min_blocks, judge 확장)
# ---------------------------------------------------------------------------


@pytest.fixture
def answer_llm(monkeypatch, llm_mode):
    calls, replies = llm_mode
    calls["answers"] = []
    replies["answer"] = {"decision": "REVISE", "style_hint": "좌석을 넓고 화려하게", "reason": "더 화려하게 원하셨어요.", "reply": "좋아요. 더 넓고 화려하게 다시 만들어볼게요."}

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
    replies["answer"] = {"decision": "KEEP", "style_hint": "팔걸이로", "reason": "무시돼야 하는 decision", "reply": "무시돼야 하는 reply"}
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
    replies["answer"] = {"decision": "REVISE", "style_hint": "", "reason": "의도하셨어요.", "reply": "네, 지금 배치를 살려 새로 만들어볼게요."}
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


@pytest.mark.parametrize("reply", [{"decision": "UNCLEAR", "style_hint": "", "reason": "판단하기 어려워요.", "reply": ""},
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
    replies["answer"] = {"decision": "KEEP", "style_hint": "", "reason": "실수였어요.", "reply": "네, 원래 자리로 고쳐 주시면 그대로 진행할게요."}
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


def test_intervention_voice_answer_is_heard_in_free_mode_with_beep(scenario, monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    calls = []

    def listen(on_ready=None, mode="short", beep=False):
        calls.append((mode, beep))
        return "일부러 그렇게 놨어요"

    monkeypatch.setattr(main.voice, "listen", listen)
    monkeypatch.setattr(main.voice, "speak", lambda sentence: None)
    design, current, differences = scenario
    result = main.run_intervention(design, current, differences, text_answers=None)
    assert result["hri_result"] == "REVISE" and calls == [("free", True)]


# ---------------------------------------------------------------------------
# Stage 2 Wave 4c: on_progress 단계·확인(ack)·진행 음성
# ---------------------------------------------------------------------------


def _stages(events):
    return [event["stage"] for event in events]


def test_progress_event_shape_and_stage_constants():
    assert main.PROGRESS_STAGES[:2] == ("LISTENING", "UNDERSTANDING")
    for stage in ("ACK", "KEEP_ACK", "GENERATING", "GENERATING_REVISED", "VALIDATING", "DESCRIBING", "JUDGING",
                  "REGENERATING", "ESCALATION", "READY", "READY_REVISED", "FAILED", "CANCELLED"):
        assert stage in main.PROGRESS_STAGES


def test_initial_text_mode_progress_order_without_speech(initial_llm, monkeypatch):
    calls, replies = initial_llm
    replies["interpret"] = [_request("SPECIFIC", family="bench", style_hint="길고 넓은",
                                     reply="좋아요. 길고 편안한 벤치 형태로 만들어볼게요.")]
    monkeypatch.setattr(main.voice, "speak", lambda sentence: pytest.fail("text mode must not speak"))
    events = []
    result = main.create_initial_design(text="벤치처럼 길고 넓은 의자", on_progress=events.append)
    assert result["status"] == "OK" and set(result) == ENVELOPE_KEYS
    assert _stages(events) == ["UNDERSTANDING", "ACK", "GENERATING", "VALIDATING", "DESCRIBING", "READY"]
    assert events[1]["message"] == "좋아요. 길고 편안한 벤치 형태로 만들어볼게요."
    assert events[2]["message"] == dialogue.PROGRESS_MESSAGES["GENERATING"]
    assert all(re.fullmatch(r"\d\d:\d\d:\d\d\.\d{3}", event["at"]) for event in events)
    assert set(events[0]) == {"stage", "message", "at"}


def test_initial_rule_any_ack_uses_fallback_sentence(initial_llm):
    events = []
    main.create_initial_design(text="아무거나 만들어 주세요", on_progress=events.append)
    ack = [event for event in events if event["stage"] == "ACK"]
    assert len(ack) == 1 and ack[0]["message"] in dialogue.INITIAL_ACKS


def test_initial_voice_ack_is_spoken_before_generation_and_only_tts_stages_are_read(initial_llm, fake_voice, monkeypatch):
    calls, replies = initial_llm
    events, heard = fake_voice
    heard.append("오늘은 사과 같은 의자를 만들고 싶어요")
    replies["interpret"] = [_request("CREATIVE", style_hint="사과처럼 둥글고 빨간",
                                     reply="좋아요. 사과의 둥근 느낌을 살린 의자로 만들어볼게요.")]
    original = main.llm.generate_initial_design

    def generate(*args, **kwargs):
        events.append(("generate",))
        return original(*args, **kwargs)

    monkeypatch.setattr(main.llm, "generate_initial_design", generate)
    progress = []
    result = main.create_initial_design(on_progress=progress.append)
    assert result["status"] == "OK"
    spoken = [e[1] for e in events if e[0] == "speak"]
    assert spoken == [dialogue.GREETING, "좋아요. 사과의 둥근 느낌을 살린 의자로 만들어볼게요.",
                      dialogue.PROGRESS_MESSAGES["GENERATING"], dialogue.PROGRESS_MESSAGES["READY"]]
    ack_at = events.index(("speak", "좋아요. 사과의 둥근 느낌을 살린 의자로 만들어볼게요."))
    assert ack_at < events.index(("generate",))  # ack는 Design 생성을 기다리지 않는다
    assert _stages(progress) == ["LISTENING", "UNDERSTANDING", "ACK", "GENERATING", "VALIDATING", "DESCRIBING", "READY"]


def test_initial_unsupported_reports_failed_stage(initial_llm):
    events = []
    result = main.create_initial_design(text="자동차 만들어줘", on_progress=events.append)
    assert result["error"]["code"] == "UNSUPPORTED_OBJECT"
    assert _stages(events) == ["UNDERSTANDING", "FAILED"] and "UNSUPPORTED_OBJECT" in events[-1]["message"]


def test_initial_stop_reports_cancelled_stage(initial_llm):
    calls, replies = initial_llm
    replies["interpret"] = [{"llm_error": {"kind": "stopped", "message": "stopped"}}]
    events = []
    main.create_initial_design(text="왕좌처럼 높고 화려한 의자요", on_progress=events.append)
    assert _stages(events) == ["UNDERSTANDING", "CANCELLED"] and "STOPPED" in events[-1]["message"]


def test_initial_mock_mode_minimal_progress_without_ack_or_speech(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(main.voice, "speak", lambda sentence: pytest.fail("Mock must not speak"))
    events = []
    result = main.create_initial_design(text=GOAL_TEXT, on_progress=events.append)
    assert result["status"] == "OK" and _stages(events) == ["GENERATING", "VALIDATING", "READY"]


def _progress_answer(scenario, *answers):
    design, current, differences = scenario
    events = []
    result = main.run_intervention(design, current, differences, text_answers=list(answers), on_progress=events.append)
    return result, events


def test_revised_text_mode_progress_order_and_llm_reply_ack(scenario, answer_llm, monkeypatch):
    calls, replies = answer_llm
    replies["answer"] = {"decision": "REVISE", "style_hint": "팔걸이로", "reason": "…",
                         "reply": "알겠습니다. 팔걸이를 살린 형태로 다시 만들어볼게요."}
    monkeypatch.setattr(main.voice, "speak", lambda sentence: pytest.fail("text mode must not speak"))
    result, events = _progress_answer(scenario, "일부러 그렇게 놨어요. 팔걸이로 살려주세요.")
    assert result["hri_result"] == "REVISE" and set(result) == ENVELOPE_KEYS
    assert _stages(events) == ["UNDERSTANDING", "HRI_INTERPRET", "ACK", "GENERATING_REVISED", "VALIDATING", "JUDGING",
                               "READY_REVISED"]
    assert events[2]["message"] == "알겠습니다. 팔걸이를 살린 형태로 다시 만들어볼게요."


def test_revised_number_answer_uses_revise_ack_fallback(scenario, answer_llm):
    calls, _ = answer_llm
    result, events = _progress_answer(scenario, "2번")
    ack = [event for event in events if event["stage"] == "ACK"]
    assert calls["answers"] == [] and len(ack) == 1 and ack[0]["message"] in dialogue.REVISE_ACKS


def test_revised_hint_only_call_ignores_a_non_revise_reply(scenario, answer_llm):
    calls, replies = answer_llm
    replies["answer"] = {"decision": "KEEP", "style_hint": "팔걸이로", "reason": "…", "reply": "네, 원래 자리로 고쳐 주세요."}
    result, events = _progress_answer(scenario, "일부러 그렇게 놨어요. 팔걸이로 살려주세요.")
    ack = [event for event in events if event["stage"] == "ACK"][0]["message"]
    assert result["hri_result"] == "REVISE" and "팔걸이로" in ack and ack != "네, 원래 자리로 고쳐 주세요."


def test_keep_answer_has_keep_ack_only(scenario, answer_llm):
    result, events = _progress_answer(scenario, "제가 잘못 놨어요. 다시 고칠게요.")
    assert result["hri_result"] == "KEEP"
    assert _stages(events) == ["UNDERSTANDING", "HRI_INTERPRET", "KEEP_ACK"] and events[2]["message"] in dialogue.KEEP_ACKS


def test_regeneration_reports_regenerating_and_second_judging(scenario, llm_mode):
    calls, replies = llm_mode
    replies["judge"] = [judge(chair_likeness="not_chair"), judge()]
    result, events = _progress_answer(scenario, "2번")
    assert _stages(events) == ["UNDERSTANDING", "HRI_INTERPRET", "ACK", "GENERATING_REVISED", "VALIDATING", "JUDGING", "REGENERATING",
                               "VALIDATING", "JUDGING", "READY_REVISED"]


def test_revised_voice_mode_speaks_ack_before_generation_then_tts_stages(scenario, answer_llm, monkeypatch):
    calls, replies = answer_llm
    replies["answer"] = {"decision": "REVISE", "style_hint": "", "reason": "…", "reply": "좋아요. 지금 배치를 살려볼게요."}
    order = []
    monkeypatch.setattr(main.voice, "listen", lambda on_ready=None, mode="short", beep=False: "일부러 그렇게 놨어요")
    monkeypatch.setattr(main.voice, "speak", lambda sentence: order.append(("speak", sentence)))
    original = main.llm.generate_revised_design

    def generate(*args, **kwargs):
        order.append(("generate",))
        return original(*args, **kwargs)

    monkeypatch.setattr(main.llm, "generate_revised_design", generate)
    design, current, differences = scenario
    progress = []
    result = main.run_intervention(design, current, differences, text_answers=None, on_progress=progress.append)
    assert result["hri_result"] == "REVISE"
    spoken = [o[1] for o in order if o[0] == "speak"]
    assert spoken[1:] == ["좋아요. 지금 배치를 살려볼게요.", dialogue.PROGRESS_MESSAGES["GENERATING_REVISED"],
                          dialogue.PROGRESS_MESSAGES["JUDGING"], dialogue.PROGRESS_MESSAGES["READY_REVISED"]]
    assert order.index(("speak", "좋아요. 지금 배치를 살려볼게요.")) < order.index(("generate",))
    assert _stages(progress)[:2] == ["LISTENING", "UNDERSTANDING"]


def test_revised_mock_mode_minimal_progress(scenario, monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    result, events = _progress_answer(scenario, "2번")
    assert result["hri_result"] == "REVISE" and _stages(events) == ["GENERATING_REVISED", "VALIDATING", "READY_REVISED"]
    keep, keep_events = _progress_answer(scenario, "1번")
    assert keep["hri_result"] == "KEEP" and keep_events == []


def test_on_progress_none_keeps_envelopes_unchanged(scenario, answer_llm):
    design, current, differences = scenario
    with_cb = main.run_intervention(design, current, differences, text_answers=["2번"], on_progress=lambda e: None)
    without = main.run_intervention(design, current, differences, text_answers=["2번"])
    assert set(with_cb) == set(without) == ENVELOPE_KEYS
    assert with_cb["design"] == without["design"] and with_cb["questions"] == without["questions"]



# ---------------------------------------------------------------------------
# Stage 2 Wave 4e: 실제 Intervention 문장(불만·변경 요청 / 실수 인정 / 부정 / 애매), HRI_INTERPRET, 새 재질문
# ---------------------------------------------------------------------------

DISSATISFIED = ["할로윈 분위기 같지가 않아", "내가 생각한 느낌이 아니야", "컵케이크처럼 안 보여", "더 단순하게 바꾸고 싶어"]
MISTAKE = ["내가 잘못 놨어", "실수였어", "원래대로 고칠게"]
NEGATED_MISTAKE = ["실수 아니야", "이상한 건 아닌데 좀 더 길었으면 좋겠어"]


def _interpret_event(events):
    found = [event for event in events if event["stage"] == "HRI_INTERPRET"]
    assert len(found) == 1
    return found[0]["message"]


@pytest.mark.parametrize("answer", DISSATISFIED)
def test_dissatisfaction_goes_to_llm_and_becomes_revise_with_ack(scenario, answer_llm, answer):
    calls, replies = answer_llm
    assert dialogue.parse_response(answer) == dialogue.UNCLEAR  # 규칙 표는 늘리지 않는다: 뜻은 LLM이 판단
    replies["answer"] = {"decision": "REVISE", "style_hint": "할로윈 분위기를 더 강하게",
                         "reason": "현재 Design이 원하는 분위기와 다르다는 말씀으로 이해했어요.",
                         "reply": "알겠습니다. 할로윈 분위기가 더 잘 느껴지도록 다시 만들어볼게요."}
    result, events = _progress_answer(scenario, answer)
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert calls["answers"] == [answer] and calls["style_hints"] == ["할로윈 분위기를 더 강하게"]
    assert _stages(events)[:3] == ["UNDERSTANDING", "HRI_INTERPRET", "ACK"]
    assert _interpret_event(events) == ("decision=REVISE source=llm reason=현재 Design이 원하는 분위기와 다르다는 말씀으로 "
                                        "이해했어요. style_hint=할로윈 분위기를 더 강하게")
    assert events[2]["message"] == "알겠습니다. 할로윈 분위기가 더 잘 느껴지도록 다시 만들어볼게요."


@pytest.mark.parametrize("answer", MISTAKE)
def test_admitted_mistake_is_rule_keep_without_llm(scenario, answer_llm, answer):
    calls, _ = answer_llm
    result, events = _progress_answer(scenario, answer)
    assert result["hri_result"] == "KEEP" and calls["answers"] == [] and calls["design"] == 0
    assert _interpret_event(events) == "decision=KEEP source=rule reason= style_hint="
    assert _stages(events) == ["UNDERSTANDING", "HRI_INTERPRET", "KEEP_ACK"]


@pytest.mark.parametrize("answer", NEGATED_MISTAKE)
def test_negated_mistake_is_never_rule_keep(scenario, answer_llm, answer):
    calls, replies = answer_llm
    assert dialogue.parse_response(answer) != dialogue.KEEP
    replies["answer"] = {"decision": "REVISE", "style_hint": "좀 더 길게", "reason": "더 길게 바꾸길 원하셨어요.",
                         "reply": "알겠습니다. 더 길게 다시 만들어볼게요."}
    result, events = _progress_answer(scenario, answer)
    assert calls["answers"] == [answer] and result["hri_result"] == "REVISE"  # fallback 결과대로
    assert "source=llm" in _interpret_event(events)


def test_vague_answer_with_llm_unclear_gets_the_new_natural_reask(scenario, answer_llm):
    calls, replies = answer_llm
    replies["answer"] = [{"decision": "UNCLEAR", "style_hint": "", "reason": "판단하기 어려워요.", "reply": ""}]
    result, events = _progress_answer(scenario, "음... 좀 그런데", "2번")
    assert result["hri_result"] == "REVISE" and len(result["questions"]) == 2
    assert result["questions"][1] == dialogue.build_reask(result["questions"][0])
    assert result["questions"][1].startswith(dialogue.REASK_LEAD)
    interprets = [event["message"] for event in events if event["stage"] == "HRI_INTERPRET"]
    assert interprets == ["decision=UNCLEAR source=llm reason=판단하기 어려워요. style_hint=",
                          "decision=REVISE source=rule reason= style_hint="]


def test_rule_revise_with_hint_call_is_reported_as_rule_decision(scenario, answer_llm):
    calls, replies = answer_llm
    replies["answer"] = {"decision": "REVISE", "style_hint": "팔걸이로", "reason": "팔걸이로 쓰려고 놓으셨어요.",
                         "reply": "알겠습니다. 팔걸이를 살려볼게요."}
    result, events = _progress_answer(scenario, "일부러 그렇게 놨어요. 팔걸이로 살려주세요.")
    assert _interpret_event(events) == "decision=REVISE source=rule reason=팔걸이로 쓰려고 놓으셨어요. style_hint=팔걸이로"


def test_hri_interpret_is_debug_only(scenario, answer_llm, monkeypatch):
    assert "HRI_INTERPRET" in main.PROGRESS_STAGES and "HRI_INTERPRET" not in dialogue.PROGRESS_TTS_STAGES
    spoken = []
    monkeypatch.setattr(main.voice, "listen", lambda on_ready=None, mode="short", beep=False: "제가 잘못 놨어요")
    monkeypatch.setattr(main.voice, "speak", spoken.append)
    design, current, differences = scenario
    result = main.run_intervention(design, current, differences, text_answers=None, on_progress=lambda e: None)
    assert result["hri_result"] == "KEEP" and set(result) == ENVELOPE_KEYS
    assert not any(sentence.startswith("decision=") for sentence in spoken)


def test_mock_mode_has_no_hri_interpret_event(scenario, monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    result, events = _progress_answer(scenario, "제가 잘못 놨어요")
    assert result["hri_result"] == "KEEP" and events == []


# ---------------------------------------------------------------------------
# Stage 3 Wave 1·2: review_design_candidate (Preview 검토, fake LLM — A의 interpret_review_answer(context)·REVIEW_KEYS 6개·
# generate_*_design(previous_candidate, scope) 가정; 병합 전 B 트리의 llm에는 없으므로 raising=False·fake로 대체)
# ---------------------------------------------------------------------------

REVIEW_KEYS = ("decision", "style_hint", "scope", "concept", "reason", "reply")
MODIFY_REPLY = {"decision": "MODIFY", "style_hint": "등받이를 더 높고 화려하게", "scope": "patch", "concept": "",
                "reason": "더 화려하게 원하셨어요.", "reply": "좋아요. 등받이를 조금 더 높여서 다시 만들어볼게요."}


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    return main.create_initial_design(text=GOAL_TEXT)["design"]


@pytest.fixture
def review_llm(monkeypatch, candidate):
    """LLM 모드 검토: 해석·Initial/Revised 생성·설명·judge를 모두 fake로 바꾸고 인자를 기록한다."""
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(designer, "RICHNESS_MIN_DELTA", 0)  # Mock 후보는 블록 수를 늘리지 않는다(min_blocks 전달은 따로 확인)
    monkeypatch.setattr(main.llm, "REVIEW_KEYS", REVIEW_KEYS, raising=False)
    calls = {"review": [], "initial": [], "revised": [], "describe": [], "judge": 0}
    replies = {"review": dict(MODIFY_REPLY), "judge": [judge()]}

    def fake_review(text, kind, should_stop=None, context=None):
        calls["review"].append((text, kind, context))
        reply = replies["review"]
        return reply.pop(0) if isinstance(reply, list) else reply

    def fake_initial(object_type, reasons=None, should_stop=None, family=None, style_hint=None, concept=None,
                     previous_candidate=None, scope=None):
        calls["initial"].append({"family": family, "style_hint": style_hint, "concept": concept,
                                 "previous_candidate": previous_candidate, "scope": scope})
        return designer.mock_initial_candidate(object_type)

    def fake_revised(design, current, differences, reasons=None, should_stop=None, feedback=None, min_blocks=None,
                     style_hint=None, previous_candidate=None, scope=None):
        calls["revised"].append({"approved": design, "style_hint": style_hint, "previous_candidate": previous_candidate,
                                 "scope": scope, "min_blocks": min_blocks, "feedback": feedback})
        return designer.mock_revised_candidate(design, current, differences)

    def fake_describe(design, should_stop=None, family=None, concept=None):
        calls["describe"].append({"family": family, "concept": concept})
        return {"design_family": family or "armchair", "design_name": "새 후보", "design_summary": "요약",
                "visible_features": [], "silhouette_clarity": "clear", "recognizable_family": True,
                "completeness_score": 4, "family_design_match": "clear"}

    def fake_judge(previous, design, current, differences, should_stop=None):
        calls["judge"] += 1
        sequence = replies["judge"]
        return sequence[min(calls["judge"], len(sequence)) - 1]

    monkeypatch.setattr(main.llm, "interpret_review_answer", fake_review, raising=False)
    monkeypatch.setattr(main.llm, "generate_initial_design", fake_initial)
    monkeypatch.setattr(main.llm, "generate_revised_design", fake_revised)
    monkeypatch.setattr(main.llm, "describe_initial_design", fake_describe)
    monkeypatch.setattr(main.llm, "judge_revised_design", fake_judge)
    return calls, replies


def _review(candidate, *answers, kind="initial", metadata=None, **kwargs):
    events = []
    snapshot = json.loads(json.dumps(candidate))
    result = main.review_design_candidate(candidate, kind=kind, design_metadata=metadata, text_answers=list(answers),
                                          on_progress=events.append, **kwargs)
    assert set(result) == ENVELOPE_KEYS
    assert candidate == snapshot  # 입력 후보는 바뀌지 않는다
    return result, events


def _no_generation(calls):
    return calls["initial"] == [] and calls["revised"] == [] and calls["judge"] == 0


def test_review_approve_by_rule_returns_candidate_unchanged(candidate, review_llm):
    calls, _ = review_llm
    metadata = {"design_name": "왕좌", "source": "LLM", "selected_family": "throne"}
    result, events = _review(candidate, "좋아 이걸로 하자", metadata=metadata)
    assert (result["status"], result["hri_result"], result["error"]) == ("OK", "APPROVE", None)
    assert result["design"] == candidate and result["design"] is not candidate
    assert set(result["design"]) == {"design_version", "blocks"} and "review" not in result["design"]
    review = result["design_metadata"]["review"]
    assert review["decision"] == "APPROVE" and review["source"] == "rule" and review["round"] == 0 and review["answers"] == 1
    assert review["reply"] in dialogue.APPROVE_ACKS and review["kind"] == "initial" and review["style_hint"] is None
    assert result["design_metadata"]["design_name"] == "왕좌" and "review" not in metadata  # 입력 metadata도 그대로
    assert calls["review"] == [] and _no_generation(calls)  # APPROVE에는 해석·생성 없음
    assert result["questions"] == [dialogue.REVIEW_QUESTIONS["initial"]]
    assert [e["stage"] for e in events] == ["REVIEW_LISTENING", "REVIEW_UNDERSTANDING", "HRI_INTERPRET", "REVIEW_ACK",
                                            "REVIEW_READY"]


def test_review_keeps_input_round_for_non_modify(candidate, review_llm):
    calls, _ = review_llm
    metadata = {"review": {"round": 2, "decision": "MODIFY"}}
    for answers, expected in ((("좋아요",), "APPROVE"), (("음…", "글쎄"), "UNCLEAR"), (("그만할래",), "CANCEL")):
        calls["review"].clear()
        if expected == "UNCLEAR":
            review_llm[1]["review"] = [dict(MODIFY_REPLY, decision="UNCLEAR", scope="", style_hint="", reply="")] * 2
        result, _ = _review(candidate, *answers, metadata=metadata)
        assert result["hri_result"] == expected and result["design_metadata"]["review"]["round"] == 2
        assert result["design"] == candidate
    assert _no_generation(calls)


def test_review_context_is_passed_to_interpretation(candidate, review_llm):
    calls, _ = review_llm
    metadata = {"selected_family": None, "family_source": "creative", "style_hint": "컵케이크처럼 둥근"}
    _review(candidate, "음…", metadata=metadata)
    assert calls["review"][0] == ("음…", "initial", {"family": None, "concept": "컵케이크처럼 둥근"})
    _review(candidate, "음…", metadata={"selected_family": "throne", "family_source": "preference", "style_hint": "높은"})
    assert calls["review"][-1][2] == {"family": "throne", "concept": None}


def test_review_initial_patch_regenerates_with_family_and_previous_candidate(candidate, review_llm):
    calls, _ = review_llm
    metadata = {"selected_family": "throne", "family_source": "preference", "style_hint": "높고 화려한",
                "review": {"round": 1}}
    result, events = _review(candidate, "등받이를 더 높게", metadata=metadata)
    assert (result["status"], result["hri_result"]) == ("OK", "MODIFY")
    assert result["design"]["design_version"] == 1 and validator.validate_design(result["design"]) == []
    assert calls["initial"] == [{"family": "throne", "style_hint": "높고 화려한 / 등받이를 더 높고 화려하게", "concept": None,
                                 "previous_candidate": candidate, "scope": "patch"}]
    assert calls["describe"] == [{"family": "throne", "concept": None}]
    meta = result["design_metadata"]
    assert meta["family_source"] == "patch" and meta["selected_family"] == "throne" and meta["design_name"] == "새 후보"
    review = meta["review"]
    assert (review["round"], review["scope"], review["source"], review["decision"]) == (2, "patch", "rule", "MODIFY")
    assert review["reply"] == MODIFY_REPLY["reply"]
    stages = [e["stage"] for e in events]
    assert stages[stages.index("REVIEW_ACK"):] == ["REVIEW_ACK", "GENERATING", "VALIDATING", "DESCRIBING", "READY"]


def test_review_initial_redesign_drops_family_and_concept(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = dict(MODIFY_REPLY, style_hint="현재 디자인과 다른 새로운 형태", scope="redesign")
    metadata = {"selected_family": "throne", "family_source": "preference", "style_hint": "높은"}
    result, _ = _review(candidate, "완전히 다른 느낌으로 다시", metadata=metadata)
    assert calls["initial"][0] == {"family": None, "style_hint": "현재 디자인과 다른 새로운 형태", "concept": None,
                                   "previous_candidate": candidate, "scope": "redesign"}
    assert result["design_metadata"]["family_source"] == "redesign" and result["design_metadata"]["review"]["round"] == 1


def test_review_initial_concept_refine_keeps_family_slot_and_updates_concept(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = dict(MODIFY_REPLY, style_hint="치즈컵케이크 느낌", scope="patch", concept="치즈컵케이크 느낌")
    metadata = {"selected_family": None, "family_source": "creative", "style_hint": "컵케이크처럼 둥근"}
    result, _ = _review(candidate, "치즈컵케이크 느낌으로 바꿔줘", metadata=metadata)
    assert calls["initial"][0] == {"family": None, "style_hint": "치즈컵케이크 느낌", "concept": "치즈컵케이크 느낌",
                                   "previous_candidate": candidate, "scope": "patch"}
    assert calls["describe"][0] == {"family": None, "concept": "치즈컵케이크 느낌"}
    assert result["design_metadata"]["review"]["concept"] == "치즈컵케이크 느낌"


def test_review_initial_concept_change(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = dict(MODIFY_REPLY, style_hint="바나나 느낌", scope="concept_change", concept="바나나 느낌")
    metadata = {"selected_family": None, "family_source": "creative", "style_hint": "컵케이크처럼 둥근"}
    result, _ = _review(candidate, "컵케이크 말고 바나나 느낌", metadata=metadata)
    assert calls["initial"][0] == {"family": None, "style_hint": "바나나 느낌", "concept": "바나나 느낌",
                                   "previous_candidate": candidate, "scope": "concept_change"}
    assert result["design_metadata"]["family_source"] == "concept_change"
    # 다음 검토는 갱신된 concept를 문맥으로 받는다
    _review(result["design"], "음…", metadata=result["design_metadata"])
    assert calls["review"][-1][2] == {"family": None, "concept": "바나나 느낌"}


def test_review_missing_scope_defaults_to_patch(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = {"llm_error": {"kind": "server", "message": "HTTP 503"}}  # 규칙 MODIFY, 해석 실패
    result, _ = _review(candidate, "다른 느낌으로 다시")
    review = result["design_metadata"]["review"]
    assert result["hri_result"] == "MODIFY" and review["scope"] == "patch" and review["style_hint"] is None
    assert review["reply"] in dialogue.MODIFY_ACKS and calls["initial"][0]["scope"] == "patch"


def test_review_mixed_answer_goes_to_llm_then_regenerates(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = dict(MODIFY_REPLY, style_hint="조금 더 길게", reply="")
    result, _ = _review(candidate, "나쁘진 않은데 조금 더 길었으면 좋겠어")
    review = result["design_metadata"]["review"]
    assert result["hri_result"] == "MODIFY" and review["source"] == "llm" and review["style_hint"] == "조금 더 길게"
    assert len(calls["review"]) == 1 and len(calls["initial"]) == 1
    assert "조금 더 길게" in review["reply"]


def test_review_initial_generation_failure_is_failed_modify(candidate, review_llm, monkeypatch):
    monkeypatch.setattr(main.llm, "generate_initial_design", lambda *a, **k: {"blocks": []})
    result, _ = _review(candidate, "등받이를 더 높게")
    assert (result["status"], result["hri_result"], result["error"]["code"]) == ("FAILED", "MODIFY", "DESIGN_GENERATION_FAILED")
    assert result["design"] is None


def test_review_stop_after_ack_cancels_before_generation(candidate, review_llm):
    calls, _ = review_llm
    stops = iter([False, True])
    result, _ = _review(candidate, "등받이를 더 높게", should_stop=lambda: next(stops, True))
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED") and _no_generation(calls)


@pytest.fixture
def revised_case(scenario, monkeypatch):
    approved, current, differences = scenario
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    revised = designer.build_revised_design(approved, current, differences)["design"]
    return approved, current, differences, revised


def test_review_revised_patch_regenerates_from_approved(revised_case, review_llm):
    calls, _ = review_llm
    approved, current, differences, revised = revised_case
    result, events = _review(revised, "등받이를 더 높게", kind="revised", previous_design=approved, current=current,
                             differences=differences)
    assert (result["status"], result["hri_result"]) == ("OK", "MODIFY")
    assert result["design"]["design_version"] == approved["design_version"] + 1  # 후보 반복으로 버전이 늘지 않는다
    assert validator.validate_revised({"blocks": result["design"]["blocks"]}, current) == []  # Current 보존
    first = calls["revised"][0]
    assert (first["approved"], first["previous_candidate"], first["scope"]) == (approved, revised, "patch")
    assert first["style_hint"] == "등받이를 더 높고 화려하게" and first["min_blocks"] == designer.revised_min_blocks(approved)
    assert calls["review"][0][1] == "revised" and calls["judge"] == 1
    meta = result["design_metadata"]
    assert meta["review"]["round"] == 1 and meta["review"]["scope"] == "patch" and meta["design_intent"] is None
    assert meta["judge"]["verdict"] == "SHOWCASE" and meta["style_hint"] == "등받이를 더 높고 화려하게"
    stages = [e["stage"] for e in events]
    assert stages[stages.index("REVIEW_ACK"):] == ["REVIEW_ACK", "GENERATING_REVISED", "VALIDATING", "JUDGING", "READY_REVISED"]


def test_review_revised_redesign_regenerates_at_most_once(revised_case, review_llm):
    calls, replies = review_llm
    approved, current, differences, revised = revised_case
    replies["review"] = dict(MODIFY_REPLY, scope="redesign", style_hint="다른 스타일")
    replies["judge"] = [judge(chair_likeness="not_chair"), judge(chair_likeness="not_chair")]
    result, events = _review(revised, "지금 거 말고 다른 스타일", kind="revised", previous_design=approved, current=current,
                             differences=differences)
    assert result["hri_result"] == "MODIFY" and result["design_metadata"]["regenerations"] == 1
    assert len(calls["revised"]) == 2 and calls["judge"] == 2 and calls["revised"][0]["scope"] == "redesign"
    assert calls["revised"][1]["feedback"] is not None and "REGENERATING" in [e["stage"] for e in events]


def test_review_revised_needs_previous_current_and_differences(revised_case, review_llm):
    approved, current, differences, revised = revised_case
    for kwargs in ({}, {"previous_design": approved}, {"previous_design": approved, "current": current}):
        result = main.review_design_candidate(revised, kind="revised", text_answers=["좋아요"], **kwargs)
        assert (result["status"], result["error"]["code"]) == ("FAILED", "INVALID_INPUT")
    bad = main.review_design_candidate(revised, kind="revised", previous_design=approved, current=current, differences=[],
                                       text_answers=["좋아요"])
    assert bad["error"]["code"] == "INVALID_INPUT"


def test_review_revised_approve_does_not_generate(revised_case, review_llm):
    calls, _ = review_llm
    approved, current, differences, revised = revised_case
    result, _ = _review(revised, "마음에 들어", kind="revised", previous_design=approved, current=current,
                        differences=differences)
    assert result["hri_result"] == "APPROVE" and result["design"] == revised and _no_generation(calls)


def test_review_unclear_reasks_once_then_unclear(candidate, review_llm):
    calls, replies = review_llm
    unclear = dict(MODIFY_REPLY, decision="UNCLEAR", scope="", style_hint="", reply="")
    replies["review"] = [dict(unclear), dict(unclear)]
    result, events = _review(candidate, "음…", "글쎄", "좋아 이걸로 하자")
    assert (result["status"], result["hri_result"]) == ("OK", "UNCLEAR")
    assert result["questions"] == [dialogue.REVIEW_QUESTIONS["initial"], dialogue.REVIEW_REASK]  # 재질문 1회만
    assert result["design"] == candidate and result["design_metadata"]["review"]["answers"] == 2
    assert [e["stage"] for e in events].count("HRI_INTERPRET") == 2 and events[-1]["stage"] == "REVIEW_READY"
    assert _no_generation(calls)


def test_review_unclear_then_approve(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = [dict(MODIFY_REPLY, decision="UNCLEAR", scope="", style_hint="", reply="")]
    result, _ = _review(candidate, "음…", "마음에 들어")
    assert result["hri_result"] == "APPROVE" and result["design_metadata"]["review"]["answers"] == 2


def test_review_cancel(candidate, review_llm):
    calls, _ = review_llm
    result, events = _review(candidate, "그만할래")
    assert (result["status"], result["hri_result"]) == ("CANCELLED", "CANCEL")
    assert result["error"]["code"] == "USER_CANCEL" and result["design"] == candidate
    assert result["design_metadata"]["review"]["decision"] == "CANCEL"
    assert result["design_metadata"]["review"]["reply"] in dialogue.CANCEL_ACKS
    assert [e["stage"] for e in events][-2:] == ["REVIEW_ACK", "CANCELLED"] and _no_generation(calls)


def test_review_llm_cancel_uses_llm_reply(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = dict(MODIFY_REPLY, decision="CANCEL", scope="", style_hint="", reply="알겠습니다. 여기서 멈출게요.")
    result, _ = _review(candidate, "오늘은 이만하자")
    assert result["hri_result"] == "CANCEL" and result["design_metadata"]["review"]["reply"] == "알겠습니다. 여기서 멈출게요."


def test_review_text_answers_exhausted_is_unclear(candidate, review_llm):
    result, _ = _review(candidate)
    assert result["hri_result"] == "UNCLEAR" and result["design_metadata"]["review"]["answers"] == 0


@pytest.mark.parametrize("kind, bad", [("final", None), ("initial", {"design_version": 1, "blocks": []}),
                                       ("initial", "not a design")])
def test_review_invalid_input(candidate, kind, bad):
    result = main.review_design_candidate(bad if bad is not None else candidate, kind=kind, text_answers=["좋아요"])
    assert (result["status"], result["error"]["code"]) == ("FAILED", "INVALID_INPUT") and result["design"] is None


def test_review_stop(candidate, review_llm):
    result, _ = _review(candidate, "좋아요", should_stop=lambda: True)
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED")


def test_review_stop_during_llm_interpretation(candidate, review_llm):
    calls, replies = review_llm
    replies["review"] = {"llm_error": {"kind": "stopped", "message": "stopped"}}
    result, _ = _review(candidate, "음…")
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED")


def test_review_voice_mode_order(candidate, review_llm, monkeypatch):
    calls, replies = review_llm
    events = []

    def listen(on_ready=None, mode="short", beep=False):
        events.append(("listen", mode, beep))
        return "좋아 이걸로 하자"

    monkeypatch.setattr(main.voice, "listen", listen)
    monkeypatch.setattr(main.voice, "speak", lambda sentence: events.append(("speak", sentence)))
    result = main.review_design_candidate(candidate, kind="initial")
    assert result["hri_result"] == "APPROVE"
    assert events[0] == ("speak", dialogue.REVIEW_QUESTIONS["initial"]) and events[1] == ("listen", "free", True)
    assert events[2][0] == "speak" and events[2][1] in dialogue.APPROVE_ACKS and len(events) == 3  # REVIEW_* 단계는 읽지 않음


def test_review_voice_modify_speaks_ack_before_generation(candidate, review_llm, monkeypatch):
    calls, _ = review_llm
    order = []
    monkeypatch.setattr(main.voice, "listen", lambda on_ready=None, mode="short", beep=False: "등받이를 더 높게")
    monkeypatch.setattr(main.voice, "speak", lambda sentence: order.append(("speak", sentence)))
    original = main.llm.generate_initial_design
    monkeypatch.setattr(main.llm, "generate_initial_design",
                        lambda *a, **k: order.append(("generate",)) or original(*a, **k))
    result = main.review_design_candidate(candidate, kind="initial")
    assert result["hri_result"] == "MODIFY"
    spoken = [o[1] for o in order if o[0] == "speak"]
    assert spoken == [dialogue.REVIEW_QUESTIONS["initial"], MODIFY_REPLY["reply"],
                      dialogue.PROGRESS_MESSAGES["GENERATING"], dialogue.PROGRESS_MESSAGES["READY"]]
    assert order.index(("speak", MODIFY_REPLY["reply"])) < order.index(("generate",))


def test_review_voice_silence_reasks_once_then_unclear(candidate, review_llm, monkeypatch):
    spoken = []
    monkeypatch.setattr(main.voice, "listen", lambda on_ready=None, mode="short", beep=False: "")
    monkeypatch.setattr(main.voice, "speak", spoken.append)
    result = main.review_design_candidate(candidate, kind="initial")
    assert result["hri_result"] == "UNCLEAR" and spoken == [dialogue.REVIEW_QUESTIONS["initial"], dialogue.REVIEW_REASK]


def test_review_voice_listen_failure(candidate, review_llm, monkeypatch):
    monkeypatch.setattr(main.voice, "listen", lambda on_ready=None, mode="short", beep=False: None)
    monkeypatch.setattr(main.voice, "speak", lambda sentence: None)
    result = main.review_design_candidate(candidate, kind="initial")
    assert (result["status"], result["error"]["code"]) == ("FAILED", "VOICE_IO_FAILED")


def test_review_text_mode_never_speaks_but_regenerates(candidate, review_llm, monkeypatch):
    calls, _ = review_llm
    monkeypatch.setattr(main.voice, "speak", lambda sentence: pytest.fail("text mode must not speak"))
    result, _ = _review(candidate, "등받이를 더 높게")
    assert result["hri_result"] == "MODIFY" and len(calls["initial"]) == 1


def test_review_mock_mode_uses_rules_only_and_never_generates(candidate, monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    for name in ("interpret_review_answer", "generate_initial_design", "generate_revised_design"):
        monkeypatch.setattr(main.llm, name, lambda *a, **k: pytest.fail("Mock must not call LLM"), raising=False)
    result, _ = _review(candidate, "나쁘진 않은데 조금 더 길었으면 좋겠어", "등받이를 더 높게")
    assert result["hri_result"] == "MODIFY" and result["design"] == candidate  # Wave 1 동작: 후보 그대로
    assert result["design_metadata"]["review"]["style_hint"] is None and result["design_metadata"]["review"]["round"] == 0
    assert result["questions"] == [dialogue.REVIEW_QUESTIONS["initial"], dialogue.REVIEW_REASK]


def test_review_progress_stages_are_listed():
    for stage in ("REVIEW_LISTENING", "REVIEW_UNDERSTANDING", "REVIEW_ACK", "REVIEW_READY"):
        assert stage in main.PROGRESS_STAGES and stage not in dialogue.PROGRESS_TTS_STAGES
