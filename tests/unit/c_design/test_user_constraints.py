"""사용자 명시 제약과 우선순위(2026-10-13 Robot-only design rule update Wave 3, docs/C_DESIGN_CONTRACT.md §8.15).

"5층·풍부함·화려함"은 제한이 없을 때의 기본 선호이고, 사용자가 말한 제한(N층 이하·낮게·간단·블록 적게·작게)이 이긴다.
제약은 규칙 추출(결정적, 우선) + 해석 LLM의 선택 키 "constraints"(값 검증)로 모으고 family 선택·생성 프롬프트·후보 검사
(designer.constraint_violations, LLM 후보만)·judge·metadata.user_constraints로 이어진다. 새 공개 API·hri/status/error 값은 없다.
실제 LLM·네트워크·마이크는 쓰지 않는다(llm 함수 fake, tests/conftest.py 차단).
"""

import json
import random

import pytest

from app.c_design import designer, dialogue, llm, main, validator

ENVELOPE_KEYS = {"status", "hri_result", "design", "design_metadata", "questions", "error"}


def block(x, y, layer, brick_type="2x2x1", color="blue", orientation_deg=0):
    return {"brick_type": brick_type, "color": color, "x": x, "y": y, "layer": layer, "orientation_deg": orientation_deg}


# 두 다리 위에 좌석 한 장(2층): 2x2x1 좌석은 아래 두 블록의 고유 stud 4개에 얹힌다(support = min(4, 4)).
LOW_BLOCKS = [block(10, 10, 1), block(12, 10, 1), block(11, 10, 2, color="yellow")]
# 같은 좌석 위로 3·4층 기둥을 올린 후보: max_layer 3 제약이면 user_constraint로 탈락한다.
TALL_BLOCKS = LOW_BLOCKS + [block(11, 10, 3), block(11, 10, 4, color="yellow")]


def test_fixture_designs_are_valid():
    for blocks in (LOW_BLOCKS, TALL_BLOCKS):
        assert validator.validate_design({"design_version": 1, "blocks": blocks}) == []


# ---------------------------------------------------------------------------
# 1. 규칙 추출·병합·판정 (dialogue)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("3층까지만 만들어줘", {"max_layer": 3}),                              # A. 층수 상한
    ("간단하게 만들어줘", {"complexity": "simple"}),                       # B. 단순
    ("낮고 넓게 만들어줘", {"height": "low", "footprint": "wide"}),        # C. 낮고 넓은 좌석
    ("블록 적게 써서 만들어줘", {"block_budget": "fewer"}),                # D. compact
    ("아무거나 멋지게 만들어줘", {}),                                      # E. 제한 없음 → expressive 기본
    ("등받이를 높이고 화려하게", {"complexity": "rich"}),                  # F. 부위 높이는 전체 높이 제약이 아니다
    ("3층 이하로 바꿔주세요", {"max_layer": 3}),                           # G. Revised 상한
    ("의자 높이는 3층까지만", {"max_layer": 3}),                           # 명사 "높이는"은 "높게"가 아니다
    ("3층 이상으로 높게", {"height": "high"}),                             # "이상"은 상한이 아니다
    ("팔걸이가 넓은 의자요", {}),                                          # 부위의 폭은 footprint가 아니다
    ("좌석이 넓은 의자", {"footprint": "wide"}),                           # 좌석 폭은 footprint
    ("작은 의자", {"footprint": "narrow"}),
    ("", {}),
])
def test_extract_constraints_examples(text, expected):
    assert dialogue.extract_constraints(text) == expected


@pytest.mark.parametrize("text", ["3층에 팔걸이 추가해줘", "2층에 빨간 블록 하나 더", "등받이는 3층 높이로",
                                  "등받이를 4층까지 올려줘", "15층", "낮에 앉을 의자"])
def test_layer_words_that_are_not_limits(text):
    # Opus A Wave 3 review W3-N2/N3: 위치("N층에")·부위 높이(부위 단어 뒤)·두 자리 숫자·"낮에"(시간)는 제한이 아니다.
    assert dialogue.extract_constraints(text) == {}


def test_max_layer_at_the_upper_bound_is_not_a_restriction():
    assert dialogue.extract_constraints("5층까지 써도 돼") == {"max_layer": 5}
    assert dialogue.restricts_richness({"max_layer": 5}) is False                # MAX_LAYER와 같으면 실제 제한 아님(W3-N3)
    assert dialogue.restricts_richness({"max_layer": 4}) is True


def test_merge_constraints_rule_wins_and_llm_values_are_validated():
    rule = {"max_layer": 3}
    interpreted = {"max_layer": 4, "height": "low", "complexity": "fancy", "block_budget": "fewer", "bogus": 1}
    assert dialogue.merge_constraints(rule, interpreted) == {"max_layer": 3, "height": "low", "block_budget": "fewer"}
    assert dialogue.merge_constraints({}, {"max_layer": 9}) == {}            # 1..5 밖은 버린다
    assert dialogue.merge_constraints({}, {"max_layer": True}) == {}         # bool은 정수가 아니다
    assert dialogue.merge_constraints({}, "3층") == {}                       # dict가 아니면 무시
    assert dialogue.merge_constraints(None, None) == {}


@pytest.mark.parametrize("constraints, restricts", [
    ({}, False), (None, False),
    ({"max_layer": 3}, True), ({"height": "low"}, True), ({"complexity": "simple"}, True),
    ({"block_budget": "fewer"}, True), ({"footprint": "narrow"}, True),
    ({"height": "high"}, False), ({"complexity": "rich"}, False), ({"block_budget": "more"}, False),
    ({"footprint": "wide"}, False),
])
def test_restricts_richness(constraints, restricts):
    assert dialogue.restricts_richness(constraints) is restricts


def test_any_fast_path_keeps_stated_limits():
    assert dialogue.parse_initial_request("아무거나 만들어 주세요") == dialogue.ANY   # 제한 없는 ANY는 그대로 빠른 경로
    for text in ("아무거나 간단하게", "알아서 3층까지만", "블록 적게 아무거나"):
        assert dialogue.parse_initial_request(text) is None                       # 해석으로 보내 제약을 잃지 않는다
        assert dialogue.extract_constraints(text)


def test_block_count_limit_needs_the_word_block():
    assert dialogue.extract_constraints("블록 20개까지만 써줘") == {"max_blocks": 20, "block_budget": "fewer"}
    assert dialogue.extract_constraints("블록을 10개 이하로") == {"max_blocks": 10, "block_budget": "fewer"}
    assert dialogue.extract_constraints("다리는 4개까지만") == {}                 # 블록 수가 아니다
    assert dialogue.extract_constraints("5개까지만 써줘") == {}
    assert dialogue.merge_constraints({}, {"max_blocks": 41}) == {}               # 1..40 밖은 버린다
    assert dialogue.restricts_richness({"max_blocks": 30}) is True


def test_constraints_sentence():
    assert dialogue.constraints_sentence({"max_layer": 3, "complexity": "simple"}) == "3층 이하·간단한 구성"
    assert dialogue.constraints_sentence({}) == ""


# ---------------------------------------------------------------------------
# 2. 프롬프트 렌더(llm): 제한이 없으면 Wave 2 문장 그대로, 제한이 있으면 사용자 요구가 기본 선호보다 앞선다
# ---------------------------------------------------------------------------


def _scenario():
    design = {"design_version": 1, "blocks": [dict(b) for b in LOW_BLOCKS]}
    moved = dict(LOW_BLOCKS[1], y=11)
    current = [dict(LOW_BLOCKS[0]), moved]
    return design, current, [{"expected": dict(LOW_BLOCKS[1]), "actual": moved}]


def test_revised_guidance_without_restricting_limits_is_the_expressive_text():
    assert llm.revised_guidance(None) is llm._REVISED_GUIDANCE
    assert llm.revised_guidance({}, design_change=True) is llm._REVISED_DESIGN_CHANGE_GUIDANCE
    assert llm.revised_guidance({"complexity": "rich", "footprint": "wide"}) is llm._REVISED_GUIDANCE
    for constraints in ({"max_layer": 3}, {"complexity": "simple"}, {"height": "low"}, {"block_budget": "fewer"}):
        assert llm.revised_guidance(constraints) is not llm._REVISED_GUIDANCE


def test_unconstrained_revised_message_is_unchanged_by_empty_constraints():
    design, current, differences = _scenario()
    for kwargs in ({}, {"min_blocks": 9, "style_hint": "팔걸이로"}, {"change_request": "등받이를 높여줘"}):
        assert (llm._revised_user_message(design, current, differences, [], **kwargs)
                == llm._revised_user_message(design, current, differences, [], constraints={}, **kwargs)
                == llm._revised_user_message(design, current, differences, [], constraints=None, **kwargs))


def test_restricting_limits_rewrite_the_revised_priorities():
    design, current, differences = _scenario()
    message = llm._revised_user_message(design, current, differences, [], style_hint="3층까지만 간단하게",
                                        constraints={"max_layer": 3, "complexity": "simple"})
    second = message.index("- Second, the result passes every rule above")
    third = message.index("- Third, the person's stated requirements for this revision win over everything below: "
                          "use at most 3 layers (no block above layer 3); keep it simple")
    facing = message.index("- Then, where the Current blocks allow it, keep the canonical facing")
    assert second < third < facing
    assert "- First, every Current block appears exactly" in message
    assert "Fifth, layer 5 is part of a feature" not in message
    assert "Sixth, use as many blocks" not in message
    assert "a plain low single-seat chair is not acceptable" not in message
    assert "Stated limits from the person (these win over every default preference" in message
    assert "realise the person's stated direction (it may be lower, simpler or smaller than the previous Design)" in message
    assert "be richer and more complete than the previous Design" not in message
    assert "(at least" not in message.split("Style hint from the person", 1)[1]  # main은 제한 시 min_blocks를 주지 않는다


def test_non_restricting_limits_keep_expressive_guidance_and_add_the_limits_paragraph():
    design, current, differences = _scenario()
    message = llm._revised_user_message(design, current, differences, [], min_blocks=9, style_hint="넓고 화려하게",
                                        constraints={"complexity": "rich", "footprint": "wide"})
    assert llm._REVISED_GUIDANCE in message
    assert "make it rich and elaborate; make the seating area wide" in message
    assert "be richer and more complete than the previous Design (at least 9 blocks" in message


def test_initial_message_carries_stated_limits_before_the_family_paragraph():
    plain = llm._initial_user_message("CHAIR", [], family="throne", style_hint="낮게")
    limited = llm._initial_user_message("CHAIR", [], family="throne", style_hint="낮게",
                                        constraints={"height": "low", "max_layer": 3})
    assert "Stated limits" not in plain
    paragraph = ("Stated limits from the person (these win over every default preference, family feature, richness or "
                 "height goal in this message and in the system message): use at most 3 layers (no block above layer 3); "
                 "keep the whole piece low.\n")
    assert paragraph in limited
    assert limited.index(llm._INITIAL_GOAL) < limited.index(paragraph) < limited.index("throne")
    assert limited.replace(paragraph, "") == plain


def test_system_prompts_state_defaults_as_preferences_not_goals():
    assert llm._DEFAULT_PREFERENCE in llm.SYSTEM_PROMPT_INITIAL
    assert "only when the person stated no limit" in llm._DEFAULT_PREFERENCE
    assert "upper bounds, never goals" in llm._DEFAULT_PREFERENCE
    assert "the stated limits win over any defining feature" in llm.SYSTEM_PROMPT_INITIAL
    assert "bigger and bolder than the previous design when the person stated no limit" in llm.SYSTEM_PROMPT_REVISED
    assert "a smaller or lower design is then NOT a reason for false" in llm.SYSTEM_PROMPT_JUDGE


def test_judge_payload_carries_stated_limits_only_when_given(monkeypatch):
    sent = []
    monkeypatch.setenv(llm.LLM_KEY_ENV, "sk-test-FAKE-LLM-000000000000")
    monkeypatch.setattr(llm, "_post_json", lambda payload, key: sent.append(payload) or
                        {"choices": [{"message": {"content": json.dumps({"recognizable_family": True})}}]})
    design, current, differences = _scenario()
    llm.judge_revised_design(design, design, current, differences)
    llm.judge_revised_design(design, design, current, differences, constraints={"complexity": "simple"})
    payloads = [json.loads(p["messages"][-1]["content"].split("\n", 1)[1]) for p in sent]
    assert "stated_limits" not in payloads[0]
    assert payloads[1]["stated_limits"] == "keep it simple: no decorative extras, only the parts the seat needs"


def test_choose_initial_family_drops_tall_families_for_low_or_short_requests():
    for constraints in ({"height": "low"}, {"max_layer": 3}, {"max_layer": 1}):
        picks = {llm.choose_initial_family(None, rng=random.Random(seed), constraints=constraints) for seed in range(300)}
        assert picks and not picks & set(llm.TALL_FAMILIES)
    unrestricted = {llm.choose_initial_family(None, rng=random.Random(seed)) for seed in range(300)}
    assert set(llm.TALL_FAMILIES) <= unrestricted                         # 제한이 없으면 기존 균등 선택 그대로
    named = {"preference": "SPECIFIC", "family": "throne"}
    assert llm.choose_initial_family(named, constraints={"height": "low"}) == "throne"  # 이름을 댄 family는 프롬프트가 낮춘다


# ---------------------------------------------------------------------------
# 3. 후보 검사(designer): 수치 제약은 LLM 후보에만, Mock은 기록만
# ---------------------------------------------------------------------------


def test_constraint_violations_reports_layers_and_blocks():
    assert designer.constraint_violations(TALL_BLOCKS, {"max_layer": 3})[0]["rule"] == "user_constraint"
    assert designer.constraint_violations(LOW_BLOCKS, {"max_layer": 3}) == []
    assert designer.constraint_violations(TALL_BLOCKS, {"max_blocks": 4})[0]["rule"] == "user_constraint"
    assert designer.constraint_violations(TALL_BLOCKS, {"complexity": "simple"}) == []  # 정성 제약은 프롬프트만


def test_initial_builder_rejects_llm_candidates_over_the_limit_and_retries(monkeypatch):
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    replies = [{"blocks": TALL_BLOCKS}, {"blocks": LOW_BLOCKS}]
    seen = []

    def generate(object_type, reasons):
        seen.append(reasons)
        return replies.pop(0)
    result = designer.build_initial_design("CHAIR", generate=generate, delay=0, constraints={"max_layer": 3})
    assert len(result["design"]["blocks"]) == len(LOW_BLOCKS)            # designer가 Board 중앙으로 옮긴 같은 설계
    assert max(b["layer"] for b in result["design"]["blocks"]) == 2
    assert [r["rule"] for r in seen[1]] == ["user_constraint"]


def test_mock_initial_builder_ignores_constraints():
    mock = designer.build_initial_design("CHAIR", constraints={"max_layer": 1})
    assert mock["design"] == designer.build_initial_design("CHAIR")["design"]


def test_stated_limits_context_feeds_llm_functions_without_new_arguments(monkeypatch):
    assert llm.active_stated_limits() is None
    with llm.stated_limits({"height": "low"}):
        assert llm.active_stated_limits() == {"height": "low"}
        with llm.stated_limits(None):                                             # 안쪽에서 제약 없음으로 덮을 수 있다
            assert llm.active_stated_limits() is None
        assert llm.active_stated_limits() == {"height": "low"}
        picks = {llm.choose_initial_family(None, rng=random.Random(seed)) for seed in range(200)}
        assert not picks & set(llm.TALL_FAMILIES)                                 # 인자 없이도 컨텍스트를 읽는다
        assert llm._limits({"complexity": "rich"}) == {"complexity": "rich"}     # 명시 인자가 컨텍스트보다 우선
    assert llm.active_stated_limits() is None                                     # with 밖으로 새지 않는다


def test_stated_limits_context_reaches_the_rendered_prompt(monkeypatch):
    sent = []
    monkeypatch.setenv(llm.LLM_KEY_ENV, "sk-test-FAKE-LLM-000000000000")
    monkeypatch.setattr(llm, "_post_json", lambda payload, key: sent.append(payload) or
                        {"choices": [{"message": {"content": json.dumps({"blocks": LOW_BLOCKS})}}]})
    design, current, differences = _scenario()
    with llm.stated_limits({"max_layer": 3}):
        llm.generate_initial_design("CHAIR")
        llm.generate_revised_design(design, current, differences)
    llm.generate_initial_design("CHAIR")
    users = [next(m["content"] for m in p["messages"] if m["role"] == "user") for p in sent]
    assert all("use at most 3 layers" in text for text in users[:2]) and "Stated limits" not in users[2]


def test_stated_limits_do_not_cross_threads():
    import threading
    seen = []
    with llm.stated_limits({"max_layer": 2}):
        worker = threading.Thread(target=lambda: seen.append(llm.active_stated_limits()))
        worker.start()
        worker.join()
    assert seen == [None]


def test_clamp_to_current_never_asks_to_remove_assembled_layers():
    current = [block(11, 10, 4)]
    assert main._clamp_to_current({"max_layer": 3, "complexity": "simple"}, current) == {"max_layer": 4, "complexity": "simple"}
    assert main._clamp_to_current({"max_layer": 4}, current) == {"max_layer": 4}
    assert main._clamp_to_current({"max_layer": 2}, []) == {"max_layer": 2}
    assert main._clamp_to_current({"height": "low"}, current) == {"height": "low"}
    assert main._clamp_to_current(None, current) == {}
    two = [block(10, 10, 1), block(12, 10, 1)]
    assert main._clamp_to_current({"max_blocks": 1}, two) == {"max_blocks": 2}    # 조립된 블록 수 아래로 내리지 않는다(D-3)
    assert main._clamp_to_current({"max_blocks": 9}, two) == {"max_blocks": 9}


# ---------------------------------------------------------------------------
# 4. main 흐름(fake LLM)
# ---------------------------------------------------------------------------

REQUEST_ANY = {"object": "CHAIR", "preference": "ANY", "family": None, "style_hint": "", "sufficient": True,
               "follow_up": "", "reply": "좋아요. 말씀하신 대로 만들어볼게요."}


@pytest.fixture
def initial_fakes(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    calls = {"interpret": [], "choose": [], "generate": []}
    replies = {"interpret": dict(REQUEST_ANY), "generate": [{"blocks": TALL_BLOCKS}, {"blocks": LOW_BLOCKS}]}

    def interpret(text, should_stop=None):
        calls["interpret"].append(text)
        return dict(replies["interpret"])

    # 기존 fake와 같은 시그니처(constraints 인자 없음): 제약은 llm.stated_limits 컨텍스트로 온다(결정 D-1).
    def choose(preference, rng=None):
        calls["choose"].append(llm.active_stated_limits())
        return "armchair"

    def generate(object_type, reasons=None, should_stop=None, family=None, style_hint=None, concept=None):
        calls["generate"].append(llm.active_stated_limits())
        return replies["generate"].pop(0) if len(replies["generate"]) > 1 else replies["generate"][0]

    def describe(design, should_stop=None, family=None, concept=None):
        return {"design_family": family or "armchair", "design_name": "의자", "design_summary": "요약", "visible_features": [],
                "silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4,
                "family_design_match": "clear"}

    monkeypatch.setattr(main.llm, "interpret_initial_request", interpret)
    monkeypatch.setattr(main.llm, "choose_initial_family", choose)
    monkeypatch.setattr(main.llm, "generate_initial_design", generate)
    monkeypatch.setattr(main.llm, "describe_initial_design", describe)
    return calls, replies


def test_initial_three_layers_only_reaches_family_generation_builder_and_metadata(initial_fakes):
    calls, replies = initial_fakes
    replies["interpret"]["constraints"] = {"max_layer": 4, "footprint": "wide"}  # 규칙(3)이 LLM(4)을 이긴다
    result = main.create_initial_design(text="3층까지만 만들어줘")
    assert set(result) == ENVELOPE_KEYS and result["status"] == "OK"
    expected = {"max_layer": 3, "footprint": "wide"}
    assert calls["choose"] == [expected]
    assert calls["generate"] == [expected, expected]               # 4층 후보는 user_constraint로 탈락해 다시 만든다
    assert max(b["layer"] for b in result["design"]["blocks"]) <= 3
    assert result["design_metadata"]["user_constraints"] == expected
    assert set(result["design"]) == {"design_version", "blocks"}    # 제약은 Design JSON에 들어가지 않는다


def test_initial_any_with_simple_goes_to_interpretation_and_keeps_the_limit(initial_fakes):
    calls, replies = initial_fakes
    replies["generate"] = [{"blocks": LOW_BLOCKS}]
    result = main.create_initial_design(text="아무거나 간단하게")
    assert calls["interpret"] == ["아무거나 간단하게"]
    assert calls["generate"] == [{"complexity": "simple"}]
    assert result["design_metadata"]["user_constraints"] == {"complexity": "simple"}


def test_initial_without_limits_passes_no_constraint_kwargs(initial_fakes):
    calls, replies = initial_fakes
    replies["generate"] = [{"blocks": TALL_BLOCKS}]
    result = main.create_initial_design(text="아무거나 멋지게 만들어줘")
    assert calls["choose"] == [None] and calls["generate"] == [None]  # 기존 호출 인자 그대로(expressive 기본)
    assert result["design_metadata"]["user_constraints"] is None


def test_mock_initial_records_constraints_without_changing_the_design(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    plain = main.create_initial_design(text="의자 만들어줘")
    limited = main.create_initial_design(text="간단하게 3층까지만 의자 만들어줘")
    assert limited["design"] == plain["design"]                       # Mock은 고정 설계(제약 미반영)
    assert limited["design_metadata"]["user_constraints"] == {"max_layer": 3, "complexity": "simple"}
    assert plain["design_metadata"]["user_constraints"] is None


@pytest.fixture
def revised_fakes(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(designer, "RICHNESS_MIN_DELTA", 0)  # fake 후보는 블록 수를 늘리지 않는다(하한 값만 본다)
    calls = {"generate": [], "judge": [], "answers": []}
    replies = {"answer": {"decision": "REVISE", "style_hint": "", "reason": "바꾸고 싶대요.", "reply": "알겠습니다."},
               # 재생성 판단에 쓸 수 있는 judge(main._JUDGE_REQUIRED 전부): 의자로 읽히지만 이전보다 풍부하지 않다.
               "judge": {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
                         "explanation_required_to_understand": False, "chair_likeness": "clear",
                         "richer_than_previous": False, "design_family": "armchair", "design_name": "의자",
                         "visible_features": [], "completeness_score": 4}}

    def answer(text, differences, should_stop=None):
        calls["answers"].append(text)
        return dict(replies["answer"])

    def generate(design, current, differences, reasons=None, should_stop=None, feedback=None, min_blocks=None,
                 style_hint=None):
        calls["generate"].append({"min_blocks": min_blocks, "constraints": llm.active_stated_limits()})
        return designer.mock_revised_candidate(design, current, differences)

    def judge(previous, design, current, differences, should_stop=None):
        calls["judge"].append(llm.active_stated_limits())
        return dict(replies["judge"])

    monkeypatch.setattr(main.llm, "interpret_intervention_answer", answer)
    monkeypatch.setattr(main.llm, "generate_revised_design", generate)
    monkeypatch.setattr(main.llm, "judge_revised_design", judge)
    return calls, replies


@pytest.fixture
def mock_scenario(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    design = main.create_initial_design(text="의자 만들어줘")["design"]
    legs = sorted((b for b in design["blocks"] if b["layer"] == 1), key=lambda b: (b["x"], b["y"]))
    target = max(legs, key=lambda b: b["y"])
    shifted = dict(target, y=target["y"] + 1)
    current = [shifted if b is target else dict(b) for b in legs]
    return design, current, [{"expected": dict(target), "actual": dict(shifted)}]


def test_intervention_simpler_request_drops_richness_floor_and_richer_regeneration(mock_scenario, revised_fakes):
    calls, _ = revised_fakes
    design, current, differences = mock_scenario
    result = main.run_intervention(design, current, differences, text_answers=["더 단순하게 바꾸고 싶어"])
    assert (result["status"], result["hri_result"]) == ("OK", "REVISE")
    assert calls["generate"] == [{"min_blocks": None, "constraints": {"complexity": "simple"}}]
    assert calls["judge"] == [{"complexity": "simple"}]
    assert result["design_metadata"]["regenerations"] == 0           # richer False여도 단순 요청이면 재생성 사유가 아니다
    assert result["design_metadata"]["user_constraints"] == {"complexity": "simple"}


def test_intervention_without_limits_keeps_richness_floor_and_regeneration(mock_scenario, revised_fakes):
    calls, _ = revised_fakes
    design, current, differences = mock_scenario
    result = main.run_intervention(design, current, differences, text_answers=["실수 아니에요"])
    assert result["hri_result"] == "REVISE"
    floor = designer.revised_min_blocks(design)
    assert calls["generate"] == [{"min_blocks": floor, "constraints": None}] * 2  # +하한 유지, richer False → 재생성 1회
    assert calls["judge"] == [None, None]
    assert result["design_metadata"]["regenerations"] == 1 and result["design_metadata"]["user_constraints"] is None


def test_intervention_non_restricting_limits_keep_the_richness_floor(mock_scenario, revised_fakes):
    calls, _ = revised_fakes
    design, current, differences = mock_scenario
    main.run_intervention(design, current, differences, text_answers=["좀 더 넓고 화려하게 하고 싶어요."])
    assert calls["generate"][0] == {"min_blocks": designer.revised_min_blocks(design),
                                    "constraints": {"complexity": "rich", "footprint": "wide"}}


def test_intervention_llm_constraints_are_validated_and_merged(mock_scenario, revised_fakes):
    calls, replies = revised_fakes
    replies["answer"]["constraints"] = {"max_layer": 9, "height": "low", "bogus": True}
    design, current, differences = mock_scenario
    result = main.run_intervention(design, current, differences, text_answers=["실수 아니에요"])
    assert calls["generate"][0] == {"min_blocks": None, "constraints": {"height": "low"}}
    assert result["design_metadata"]["user_constraints"] == {"height": "low"}


def test_review_modify_inherits_candidate_limits_and_clamps_to_current(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    approved = main.create_initial_design(text="의자 만들어줘")["design"]
    assert max(b["layer"] for b in approved["blocks"]) == 4
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    seen = []
    monkeypatch.setattr(main.llm, "interpret_review_answer", lambda *a, **k: {
        "decision": "MODIFY", "style_hint": "더 단순하게", "scope": "patch", "concept": "", "reason": "r", "reply": "네."})

    def generate(*args, min_blocks=None, **kwargs):
        assert "constraints" not in kwargs
        seen.append({"min_blocks": min_blocks, "constraints": llm.active_stated_limits()})
        return {"llm_error": {"kind": "server", "message": "HTTP 503"}}  # 전달된 인자만 본다
    monkeypatch.setattr(main.llm, "generate_revised_design", generate)
    current = [dict(b) for b in approved["blocks"]]  # 4층까지 이미 조립됨
    result = main.review_design_candidate(approved, kind="revised", design_metadata={"user_constraints": {"max_layer": 3}},
                                          previous_design=approved, current=current, differences=[], change_reason="x",
                                          text_answers=["좀 더 단순하게 바꿔줘"])
    assert set(result) == ENVELOPE_KEYS and result["status"] == "FAILED"
    assert seen and all(call == {"min_blocks": None, "constraints": {"max_layer": 4, "complexity": "simple"}} for call in seen)
