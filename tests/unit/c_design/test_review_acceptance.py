"""Preview Review: natural acceptance phrases are APPROVE, concrete change requests win as MODIFY (Wave 6, 2026-10-12).

Actual mic E2E answered "음... 나쁘진 않은 것 같아" and "나쁘지 않은 것 같다고" to the review question and both came back
UNCLEAR: the rule table had no acceptance phrases, "않" counted as a negation, and the review LLM prompt only described
"싫은 건 아니야" as UNCLEAR. These tests pin the new rule and that Intervention / Design-Change parsing is untouched.
"""

import pytest

from app.c_design import dialogue as d
from app.c_design import llm, main, validator, designer


@pytest.mark.parametrize("text", [
    "좋아", "마음에 들어", "괜찮아", "괜찮은 것 같아", "나쁘지 않아", "나쁘지 않은 것 같아", "음... 나쁘진 않은 것 같아",
    "나쁘지 않은 것 같다고", "나쁘진 않은데 괜찮아", "이 정도면 괜찮아", "이 정도면 됐어", "이걸로 하자", "이대로 진행해",
    "진행해도 될 것 같아",
])
def test_acceptance_is_approve_without_llm(text):
    calls = []
    assert d.parse_review_response(text, llm_fallback=lambda a: calls.append(a) or d.UNCLEAR) == d.APPROVE
    assert calls == []


@pytest.mark.parametrize("text", [
    "나쁘진 않은데 등받이를 높여줘", "괜찮은데 팔걸이를 추가해줘", "이 정도면 괜찮은데 좌석을 넓혀줘", "좋은데 색을 바꿔줘",
    "나쁘지 않은데 바꿔줘", "나쁘진 않은데 조금 더 길었으면 좋겠어", "이걸로 하되 등받이만 바꿔줘", "괜찮은데 조금 더 화려하게",
])
def test_concrete_change_wins_as_modify_without_llm(text):
    calls = []
    assert d.parse_review_response(text, llm_fallback=lambda a: calls.append(a) or d.UNCLEAR) == d.MODIFY
    assert calls == []


@pytest.mark.parametrize("text", ["음...", "글쎄", "잘 모르겠어", "조금 아쉬운데", "나쁘진 않은데 뭔가...", "괜찮은 건가?",
                                  "괜찮지 않아", "싫은 건 아니야", "그냥 됐어", "마음에 안 들어", "네"])
def test_hesitation_and_negated_acceptance_stay_unclear_or_go_to_llm(text):
    assert d.parse_review_response(text) == d.UNCLEAR
    calls = []
    assert d.parse_review_response(text, llm_fallback=lambda a: calls.append(a) or d.MODIFY) == d.MODIFY
    assert calls == [text]  # the LLM decides, never a forced APPROVE


@pytest.mark.parametrize("text", ["그만할래", "취소해줘", "오늘은 안 만들래", "괜찮은데 그만할래"])
def test_cancel_phrases_unchanged(text):
    assert d.parse_review_response(text) == d.CANCEL


def test_other_parsers_are_untouched():
    assert d.parse_response("괜찮아") == d.UNCLEAR and d.parse_response("수정할게요") == d.KEEP
    assert d.parse_design_change_response("괜찮아") == d.UNCLEAR and d.parse_design_change_response("수정할게요") == d.REVISE
    assert "괜찮" not in d._INTERVENTION_PHRASES[d.KEEP] + d._INTERVENTION_PHRASES[d.REVISE]
    assert "괜찮" not in d._DESIGN_CHANGE_PHRASES[d.KEEP] + d._DESIGN_CHANGE_PHRASES[d.REVISE]


def test_review_prompt_describes_acceptance_and_change_priority():
    prompt = llm.SYSTEM_PROMPT_REVIEW
    assert "'나쁘진 않은 것 같아'" in prompt and "'이 정도면 됐어'" in prompt and "are all APPROVE" in prompt
    assert "'나쁘진 않은데 등받이를 좀 높여줘'" in prompt and "is MODIFY" in prompt
    assert "'괜찮은 건가?'" in prompt and "stays UNCLEAR" in prompt


def test_review_flow_approves_the_candidate_unchanged(monkeypatch):
    """Mock review: the actual mic sentence approves the displayed candidate as-is (version kept, round 0)."""
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(designer, "RETRY_DELAY", 0)
    candidate = designer.build_initial_design("CHAIR")["design"]
    envelope = main.review_design_candidate(candidate, kind="initial", design_metadata={"source": "MOCK"},
                                            text_answers=["음... 나쁘진 않은 것 같아"])
    assert envelope["status"] == "OK" and envelope["hri_result"] == d.APPROVE
    assert envelope["design"] == candidate and validator.validate_design(envelope["design"]) == []
    review = envelope["design_metadata"]["review"]
    assert review["decision"] == d.APPROVE and review["round"] == 0 and review["source"] == "rule"
    assert envelope["design_metadata"]["source"] == "MOCK"
