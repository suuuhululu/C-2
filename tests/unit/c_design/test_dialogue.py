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
        # Stage 2 주관식 자유 답변
        ("네", d.REVISE),
        ("맞아요 팔걸이로 쓰려고요", d.REVISE),
        ("네, 일부러 그렇게 놨어요", d.REVISE),
        ("이대로 더 화려하게 만들어줘", d.REVISE),
        ("좀 다른 느낌으로 바꿔보자", d.REVISE),
        ("2층 블록은 일부러 놨어요", d.REVISE),  # "2층"의 숫자는 번호로 보지 않는다
        ("아니요", d.KEEP),
        ("아니요 실수예요", d.KEEP),
        ("내가 잘못 놨어, 내가 수정할게", d.KEEP),
        ("제가 원래 자리로 고칠게요", d.KEEP),
        ("의도하지 않았어요", d.KEEP),
        ("일부러 그런 거 아니에요", d.KEEP),
        ("실수 아니에요", d.UNCLEAR),  # 부정된 구문은 뒤집지 않는다
        ("아니 일부러 그런 거예요", d.UNCLEAR),  # 아니요 + 일부러: 두 부류
        ("일부러 놨는데 원래대로 할게요", d.UNCLEAR),
        ("네가 정해", d.UNCLEAR),  # "네가"는 예가 아니다
        ("모르겠어요", d.UNCLEAR),
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


@pytest.mark.parametrize("text", ["일부러 놨는데 원래대로 할게요", "아니 일부러 그런 거예요", "실수 아니에요"])
def test_parse_response_fallback_called_when_both_kinds_or_negated(text):
    calls = []

    def fallback(answer):
        calls.append(answer)
        return d.REVISE

    assert d.parse_response(text, llm_fallback=fallback) == d.REVISE
    assert calls == [text]


@pytest.mark.parametrize("value", [d.KEEP, d.REVISE, d.UNCLEAR, d.CANCEL])
def test_parse_response_fallback_values_passed_through(value):
    assert d.parse_response("음 글쎄요", llm_fallback=lambda text: value) == value


def test_parse_response_fallback_not_called_for_clear_free_answer():
    calls = []
    assert d.parse_response("실수로 놨어요", llm_fallback=lambda text: calls.append(text)) == d.KEEP
    assert d.parse_response("일부러 놨어요", llm_fallback=lambda text: calls.append(text)) == d.REVISE
    assert calls == []


def test_parse_response_fallback_invalid_value_is_unclear():
    assert d.parse_response("음 글쎄요", llm_fallback=lambda text: "NONSENSE") == d.UNCLEAR


@pytest.mark.parametrize("text, expected", [
    ("2번", True), ("2번이요", True), ("이번", True), ("1", True), ("일번", True),
    ("네", False), ("일부러요", False), ("이번에는 2번", False), ("2층 블록은 일부러", False), ("", False), (None, False),
])
def test_is_number_answer(text, expected):
    assert d.is_number_answer(text) is expected


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
        ("원래대로 돌려놓을게요", d.MOVE_BACK),
        ("제가 고칠게요", d.MOVE_BACK),
        ("새 설계 찾아 주세요", d.KEEP_SEARCHING),
        ("네", d.UNCLEAR),  # 두 길을 함께 묻는 질문이라 예/아니요로는 고르지 않는다
        ("옮기지 마세요", d.UNCLEAR),
    ],
)
def test_parse_escalation_response(text, expected):
    assert d.parse_escalation_response(text) == expected


def test_parse_escalation_response_fallback_not_called_when_rule_matches():
    calls = []
    d.parse_escalation_response("1번", llm_fallback=lambda text: calls.append(text))
    assert calls == []


# ---------------------------------------------------------------------------
# Initial 인사 / parse_initial_request (ANY 또는 None) / 고정 문장 (Stage 2 Wave 4b)
# ---------------------------------------------------------------------------


def test_greeting_is_a_polite_open_question():
    assert d.build_greeting() == d.GREETING == "안녕하세요. 오늘 어떤 걸 만들고 싶으세요?"


def test_fixed_initial_sentences():
    assert d.UNSUPPORTED_REPLY == "죄송해요, 지금은 의자나 벤치 같은 앉는 가구만 만들 수 있어요."
    assert d.SILENCE_REASK == "잘 못 들었어요. 오늘 어떤 걸 만들고 싶으세요?"
    for sentence in (d.GREETING, d.UNSUPPORTED_REPLY, d.SILENCE_REASK):
        assert "1번" not in sentence and "2번" not in sentence


@pytest.mark.parametrize(
    "text",
    ["아무거나", "아무거나요", "아무거나 만들어 주세요", "아무 의자나 만들어줘", "알아서 의자 하나 만들어줘", "알아서 해 주세요",
     "네가 정해줘", "맡길게요", "상관없어요", "오늘은 그냥 아무거나 알아서 의자 하나 만들어 주세요"],
)
def test_parse_initial_request_explicit_any(text):
    assert d.parse_initial_request(text) == d.ANY


@pytest.mark.parametrize(
    "text",
    ["아무거나 멋진 의자", "벤치처럼 길고 넓은 의자", "오늘은 사과 같은 의자를 만들고 싶어요", "왕좌처럼 높고 화려한 의자",
     "빨간 등받이 의자요", "팔걸이 있는 거", "등받이 없는 의자", "긴 의자요", "아무거나 책상 만들어줘",
     "의자 만들어줘", "모르겠어요", "없어요", "아니요", "글쎄요", "뭔가 만들고 싶어요", "음", "", "   ", None,
     "특별히 생각해 둔 건 없지만 그래도 앉기 편하고 튼튼하면 좋겠어요"],
)
def test_parse_initial_request_needs_llm(text):
    assert d.parse_initial_request(text) is None


@pytest.mark.parametrize("text, expected", [
    ("자동차 만들어줘", True), ("책상 만들어줘", True), ("로봇처럼 생긴 거", True),
    ("자동차 모양 의자", False), ("테이블이랑 의자", False), ("사과 같은 의자", False), ("왕좌 만들어줘", False),
    ("하늘을 나는 걸 만들고 싶어요", False), ("", False), (None, False),
])
def test_is_unsupported_request(text, expected):
    assert d.is_unsupported_request(text) is expected


def test_old_preference_question_api_is_removed():
    for name in ("INITIAL_PREFERENCE_QUESTION", "build_initial_preference_question", "parse_initial_preference"):
        assert not hasattr(d, name)


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


def _assert_no_numbered_choices(text):
    assert "1번" not in text and "2번" not in text
    assert "선택" not in text


def test_build_question_is_open_question_with_position_diff():
    actual = _with(_EXPECTED_BRICK, x=7)
    differences = [{"expected": _EXPECTED_BRICK, "actual": actual}]

    question = d.build_question(design={}, current=[], differences=differences)

    assert "의도하신 건가요?" in question  # (1) 의도 여부
    assert "편하게 말씀해 주세요" in question  # (2) 자유 설명 유도
    assert "원래 자리로 고쳐" in question  # (3) 실수면 원래 위치로
    _assert_no_numbered_choices(question)
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

    assert "(x=6, y=5) 1층 블록이 Design에는 있는데 아직 놓이지 않았어요." in question
    assert "(x=9, y=10) 1층 블록은 Design에 없는 블록이에요." in question
    assert "B0" not in question


@pytest.mark.parametrize("overrides, sentence", [
    ({"x": 7}, "(x=6, y=5) 1층 블록의 위치가 달라요."),
    ({"color": "blue"}, "(x=6, y=5) 1층 블록의 색이 달라요."),
    ({"orientation_deg": 90}, "(x=6, y=5) 1층 블록의 방향이 달라요."),
    ({"brick_type": "2x2x1"}, "(x=6, y=5) 1층 블록의 크기가 달라요."),
    ({"layer": 2}, "(x=6, y=5) 1층 블록의 층이 달라요."),
    ({"x": 7, "color": "red"}, "(x=6, y=5) 1층 블록의 위치와 색이 달라요."),
    ({"orientation_deg": 90, "color": "red"}, "(x=6, y=5) 1층 블록의 방향과 색이 달라요."),
    ({"x": 7, "orientation_deg": 90, "color": "red"}, "(x=6, y=5) 1층 블록의 위치, 방향, 색이 달라요."),
])
def test_difference_sentence_uses_matching_particles(overrides, sentence):
    question = d.build_question(design={}, current=[], differences=[{"expected": _EXPECTED_BRICK,
                                                                      "actual": _with(_EXPECTED_BRICK, **overrides)}])
    assert sentence in question
    assert "(가)" not in question and "다릅니다" not in question


def test_build_reask_repeats_full_question():
    question = d.build_question(
        design={}, current=[], differences=[{"expected": _EXPECTED_BRICK, "actual": None}]
    )

    reask = d.build_reask(question)

    assert question in reask
    assert "잘 못 알아들었어요" in reask


def test_build_reask_explains_how_to_answer_and_cancel():
    reask = d.build_reask("질문")

    assert "'일부러'" in reask
    assert "'실수'" in reask
    assert "'취소'" in reask
    _assert_no_numbered_choices(reask)
    # 재질문에서 안내한 낱말은 그대로 해석된다
    assert d.parse_response("일부러") == d.REVISE
    assert d.parse_response("실수") == d.KEEP
    assert d.parse_response("취소") == d.CANCEL


def test_escalation_question_mentions_position_and_both_ways():
    actual = _with(_EXPECTED_BRICK, x=7)
    differences = [{"expected": _EXPECTED_BRICK, "actual": actual}]

    question = d.escalation_question(differences)

    assert "(x=7, y=5)" in question
    assert "(x=6, y=5)" in question
    assert "원래대로 돌려 주실 수 있을까요?" in question
    assert "계속 새 설계를 찾아볼까요?" in question
    _assert_no_numbered_choices(question)


def test_escalation_question_extra_block_and_empty():
    extra = {"expected": None, "actual": _with(_EXPECTED_BRICK, x=9, y=10)}
    assert "(x=9, y=10) 1층 블록은 빼서" in d.escalation_question([extra])
    assert "놓인 블록을 원래대로 돌려 주실 수 있을까요?" in d.escalation_question([])


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


# ---------------------------------------------------------------------------
# Stage 2 Wave 4c: 진행 문장·확인(ack) 문장
# ---------------------------------------------------------------------------


def test_progress_messages_and_tts_stages():
    expected = {"GENERATING": "디자인을 생성하고 있어요.", "VALIDATING": "구조를 확인하고 있어요.",
                "DESCRIBING": "디자인을 정리하고 있어요.", "READY": "디자인이 완성됐어요.",
                "GENERATING_REVISED": "수정된 디자인을 만들고 있어요.", "JUDGING": "완성된 디자인을 확인하고 있어요.",
                "READY_REVISED": "수정된 디자인이 완성됐어요."}
    assert {key: d.PROGRESS_MESSAGES[key] for key in expected} == expected
    assert d.PROGRESS_TTS_STAGES == ("GENERATING", "READY", "GENERATING_REVISED", "JUDGING", "READY_REVISED")
    assert all(stage in d.PROGRESS_MESSAGES for stage in d.PROGRESS_TTS_STAGES)
    for stage in ("LISTENING", "UNDERSTANDING", "VALIDATING", "DESCRIBING"):
        assert stage not in d.PROGRESS_TTS_STAGES


@pytest.mark.parametrize("options", [d.INITIAL_ACKS, d.INITIAL_CONCEPT_ACKS, d.REVISE_ACKS, d.REVISE_HINT_ACKS, d.KEEP_ACKS])
def test_ack_candidates_are_three_or_four_polite_sentences(options):
    assert 3 <= len(options) <= 4 and len(set(options)) == len(options)
    for sentence in options:
        assert sentence.endswith(("요.", "다.")) and "1번" not in sentence


def test_keep_ack_picks_from_candidates_without_immediate_repeat():
    picks = [d.keep_ack() for _ in range(30)]
    assert set(picks) <= set(d.KEEP_ACKS) and len(set(picks)) >= 2
    assert all(a != b for a, b in zip(picks, picks[1:]))


def test_revise_ack_fallback_with_and_without_style_hint():
    with_hint = d.revise_ack_fallback("좌석을 넓고 화려하게")
    assert "좌석을 넓고 화려하게" in with_hint
    assert with_hint in {t.format(hint="좌석을 넓고 화려하게") for t in d.REVISE_HINT_ACKS}
    assert d.revise_ack_fallback() in d.REVISE_ACKS and d.revise_ack_fallback("  ") in d.REVISE_ACKS


def test_initial_ack_fallback_uses_concept_and_never_reads_family_key():
    assert d.initial_ack_fallback() in d.INITIAL_ACKS
    assert d.initial_ack_fallback(family="sled-base chair") in d.INITIAL_ACKS
    concept = d.initial_ack_fallback(concept="사과처럼 둥글고 빨간")
    assert "사과처럼 둥글고 빨간" in concept and "sled" not in concept


def test_ack_choice_is_random(monkeypatch):
    seen = []
    monkeypatch.setattr(d.random, "choice", lambda choices: seen.append(list(choices)) or choices[-1])
    d._last_pick.clear()
    assert d.keep_ack() == d.KEEP_ACKS[-1] and seen[0] == list(d.KEEP_ACKS)
    d.keep_ack()
    assert d.KEEP_ACKS[-1] not in seen[1]  # 바로 앞 문장은 후보에서 뺀다
