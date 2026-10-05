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
# parse_response (KEEP_ORIGINAL / CREATE_REVISED / UNCLEAR)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1번", d.KEEP_ORIGINAL),
        ("2번", d.CREATE_REVISED),
        ("일번", d.KEEP_ORIGINAL),
        ("1", d.KEEP_ORIGINAL),
        ("2번이요", d.CREATE_REVISED),
        ("이번에는 1번", d.KEEP_ORIGINAL),
        ("2번 말고 1번", d.KEEP_ORIGINAL),
        ("원래대로 할게", d.KEEP_ORIGINAL),
        ("원래대로요", d.KEEP_ORIGINAL),
        ("이대로 유지할게", d.CREATE_REVISED),
        ("지금 상태로 할게", d.CREATE_REVISED),
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


def test_parse_response_fallback_not_called_when_rule_matches():
    calls = []

    def fallback(text):
        calls.append(text)
        return d.CREATE_REVISED

    assert d.parse_response("1번", llm_fallback=fallback) == d.KEEP_ORIGINAL
    assert calls == []


def test_parse_response_fallback_called_when_nothing_matches():
    calls = []

    def fallback(text):
        calls.append(text)
        return d.CREATE_REVISED

    assert d.parse_response("음 글쎄요", llm_fallback=fallback) == d.CREATE_REVISED
    assert calls == ["음 글쎄요"]


def test_parse_response_fallback_invalid_value_is_unclear():
    assert d.parse_response("음 글쎄요", llm_fallback=lambda text: "NONSENSE") == d.UNCLEAR


# ---------------------------------------------------------------------------
# parse_escalation_response (MOVE_BACK / KEEP_SEARCHING / UNCLEAR)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1번", d.MOVE_BACK),
        ("2번", d.KEEP_SEARCHING),
        ("옮길게요", d.MOVE_BACK),
        ("계속 찾아줘", d.KEEP_SEARCHING),
        ("몰라", d.UNCLEAR),
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

_B001_EXPECTED = {
    "block_id": "B001",
    "color": "YELLOW",
    "geometry": "2x3x1",
    "grid_x": 6,
    "grid_y": 5,
    "orientation_deg": 0,
    "layer": 1,
}


def _with(base, **overrides):
    brick = dict(base)
    brick.update(overrides)
    return brick


def test_build_question_mentions_choices_and_position_diff():
    actual = _with(_B001_EXPECTED, grid_x=7)
    differences = [{"expected": _B001_EXPECTED, "actual": actual}]

    question = d.build_question(design={}, current=[], differences=differences)

    assert "1번" in question
    assert "2번" in question
    assert "원래 설계대로 고치기" in question
    assert "지금 놓인 상태를 살린 새 설계" in question
    assert "B001" in question
    assert "위치" in question


def test_build_question_mentions_orientation_and_color_diff():
    actual = _with(_B001_EXPECTED, orientation_deg=90, color="BLUE")
    differences = [{"expected": _B001_EXPECTED, "actual": actual}]

    question = d.build_question(design={}, current=[], differences=differences)

    assert "방향" in question
    assert "색" in question


def test_build_question_handles_missing_and_extra_brick():
    missing = {"expected": _B001_EXPECTED, "actual": None}
    extra = {"expected": None, "actual": _with(_B001_EXPECTED, block_id="B002")}

    question = d.build_question(design={}, current=[], differences=[missing, extra])

    assert "B001" in question
    assert "누락" in question
    assert "B002" in question
    assert "추가" in question


def test_build_reask_repeats_full_question():
    question = d.build_question(
        design={}, current=[], differences=[{"expected": _B001_EXPECTED, "actual": None}]
    )

    reask = d.build_reask(question)

    assert question in reask
    assert "다시" in reask


def test_short_confirm_and_status_check_prompts_mention_choices():
    assert "1번" in d.short_confirm_prompt()
    assert "2번" in d.short_confirm_prompt()
    assert "1번" in d.status_check_prompt()
    assert "2번" in d.status_check_prompt()


def test_final_notice_mentions_timeout_and_cancel():
    notice = d.final_notice()
    assert "5분" in notice
    assert "취소" in notice


def test_escalation_question_mentions_block_id_and_choices():
    actual = _with(_B001_EXPECTED, grid_x=7)
    differences = [{"expected": _B001_EXPECTED, "actual": actual}]

    question = d.escalation_question(differences)

    assert "B001" in question
    assert "1번" in question
    assert "2번" in question


def test_escalation_question_ignores_differences_without_actual():
    differences = [{"expected": _B001_EXPECTED, "actual": None}]

    question = d.escalation_question(differences)

    assert "B001" not in question
