"""app.c_design.dialogue 단위 테스트(순수 텍스트, LLM/음성 없음)."""

import pytest

from app.c_design import dialogue as d


# ---------------------------------------------------------------------------
# is_meaningful
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("잠시만요", True),
        ("뭐라고요?", True),
        ("", False),
        ("   ", False),
        (None, False),
        (".,!", False),
    ],
)
def test_is_meaningful(text, expected):
    assert d.is_meaningful(text) is expected


# ---------------------------------------------------------------------------
# parse_response (KEEP / REVISE / UNCLEAR / CANCEL)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1번", d.KEEP),
        ("2번", d.REVISE),
        ("일번", d.KEEP),
        ("1", d.KEEP),
        ("2번이요", d.REVISE),
        ("이번에는 1번", d.KEEP),
        ("2번 말고 1번", d.KEEP),
        ("원래대로 할게", d.KEEP),
        ("원래대로요", d.KEEP),
        ("이대로 유지할게", d.REVISE),
        ("지금 상태로 할게", d.REVISE),
        ("원래대로 하지 마", d.UNCLEAR),
        ("2번은 싫어", d.UNCLEAR),
        ("1번 2번", d.UNCLEAR),
        ("음 글쎄요", d.UNCLEAR),
        ("잠시만요", d.UNCLEAR),
        ("뭐라고요?", d.UNCLEAR),
        ("", d.UNCLEAR),
        ("   ", d.UNCLEAR),
    ],
)
def test_parse_response_rules(text, expected):
    assert d.parse_response(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("취소할게", d.CANCEL),
        ("그만할게", d.CANCEL),
        ("그만하자", d.CANCEL),
        ("중단할게요", d.CANCEL),
        ("취소", d.CANCEL),
        ("취소하지 마", d.UNCLEAR),
    ],
)
def test_parse_response_explicit_cancel(text, expected):
    assert d.parse_response(text) == expected


def test_parse_response_fallback_not_called_when_rule_matches():
    calls = []

    def fallback(text):
        calls.append(text)
        return d.REVISE

    assert d.parse_response("1번", llm_fallback=fallback) == d.KEEP
    assert calls == []


def test_parse_response_fallback_called_when_nothing_matches():
    calls = []

    def fallback(text):
        calls.append(text)
        return d.REVISE

    assert d.parse_response("음 글쎄요", llm_fallback=fallback) == d.REVISE
    assert calls == ["음 글쎄요"]


def test_parse_response_fallback_invalid_value_is_unclear():
    assert d.parse_response("음 글쎄요", llm_fallback=lambda text: "NONSENSE") == d.UNCLEAR


# ---------------------------------------------------------------------------
# parse_escalation_response (MOVE_BACK / KEEP_SEARCHING / UNCLEAR / CANCEL)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1번", d.MOVE_BACK),
        ("2번", d.KEEP_SEARCHING),
        ("옮길게요", d.MOVE_BACK),
        ("계속 찾아줘", d.KEEP_SEARCHING),
        ("몰라", d.UNCLEAR),
        ("취소", d.CANCEL),
    ],
)
def test_parse_escalation_response(text, expected):
    assert d.parse_escalation_response(text) == expected


def test_parse_escalation_response_fallback_not_called_when_rule_matches():
    calls = []
    d.parse_escalation_response("1번", llm_fallback=lambda text: calls.append(text))
    assert calls == []


# ---------------------------------------------------------------------------
# parse_goal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("오늘은 의자를 만들 거야", "CHAIR"),
        ("의자 만들자", "CHAIR"),
        ("책상 만들 거야", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_goal(text, expected):
    assert d.parse_goal(text) == expected


# ---------------------------------------------------------------------------
# build_question / build_reask / escalation_question / 고정 문구
# ---------------------------------------------------------------------------

_EXPECTED_BRICK = {
    "brick_type": "2x3x1",
    "color": "yellow",
    "x": 6,
    "y": 5,
    "orientation_deg": 0,
    "layer": 1,
}


def _with(base, **overrides):
    brick = dict(base)
    brick.update(overrides)
    return brick


def test_build_question_mentions_choices_and_position_diff():
    actual = _with(_EXPECTED_BRICK, x=7)
    differences = [{"expected": _EXPECTED_BRICK, "actual": actual}]

    question = d.build_question(design={}, current=[], differences=differences)

    assert "1번" in question
    assert "2번" in question
    assert "원래 설계 유지" in question
    assert "지금 놓인 상태를 살린 새 설계" in question
    assert "(x=" in question
    assert "B0" not in question
    assert "위치" in question


def test_build_question_mentions_orientation_and_color_diff():
    actual = _with(_EXPECTED_BRICK, orientation_deg=90, color="blue")
    differences = [{"expected": _EXPECTED_BRICK, "actual": actual}]

    question = d.build_question(design={}, current=[], differences=differences)

    assert "방향" in question
    assert "색" in question


def test_build_question_handles_missing_and_extra_brick():
    missing = {"expected": _EXPECTED_BRICK, "actual": None}
    extra_brick = _with(_EXPECTED_BRICK, x=9, y=10)
    extra = {"expected": None, "actual": extra_brick}

    question = d.build_question(design={}, current=[], differences=[missing, extra])

    assert "(x=6, y=5)" in question
    assert "누락" in question
    assert "(x=9, y=10)" in question
    assert "추가" in question
    assert "B0" not in question


def test_build_reask_repeats_full_question():
    question = d.build_question(
        design={}, current=[], differences=[{"expected": _EXPECTED_BRICK, "actual": None}]
    )

    reask = d.build_reask(question)

    assert question in reask
    assert "다시 설명" in reask


def test_build_reask_explains_each_choice_and_cancel():
    question = d.build_question(
        design={}, current=[], differences=[{"expected": _EXPECTED_BRICK, "actual": None}]
    )

    reask = d.build_reask(question)

    assert "원래 위치" in reask
    assert "새 설계" in reask
    assert "1번 또는 2번" in reask
    assert "취소" in reask


def test_escalation_question_mentions_position_and_choices():
    actual = _with(_EXPECTED_BRICK, x=7)
    differences = [{"expected": _EXPECTED_BRICK, "actual": actual}]

    question = d.escalation_question(differences)

    assert "(x=7, y=5)" in question
    assert "(x=6, y=5)" in question
    assert "1번" in question
    assert "2번" in question


def test_escalation_question_ignores_differences_without_actual():
    differences = [{"expected": _EXPECTED_BRICK, "actual": None}]

    question = d.escalation_question(differences)

    assert "(x=6, y=5)" not in question


# ---------------------------------------------------------------------------
# Day4에는 시간 기준 자동 취소 프롬프트가 없다
# ---------------------------------------------------------------------------


def test_time_based_prompts_removed():
    assert not hasattr(d, "short_confirm_prompt")
    assert not hasattr(d, "status_check_prompt")
    assert not hasattr(d, "final_notice")
