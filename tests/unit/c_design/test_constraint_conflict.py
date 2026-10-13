"""Current와 사용자 제약의 충돌 처리(2026-10-13 Robot-only design rule update Wave 4, docs/C_DESIGN_CONTRACT.md §8.16).

이미 조립된 Current는 지우지 않는다. 요청(N층 이하·블록 N개 이하·조립된 블록 제거)이 Current와 충돌하면 Revised 생성·ACK 전에
한 번 설명하고 "설계 그대로(KEEP) / 조립된 부분은 두고 나머지만(REVISE)"를 묻는다(답은 최대 2번: 질문 + 재질문 1회). REVISE면
Current로 맞춘(clamp) 제약으로 만들고 design_metadata.constraint_clamp에 기록한다. Review MODIFY(revised)는 질문 없이 clamp하고
ack 뒤에 고지한다. 새 hri/status/error 값은 없다(D mvp_workflow.receive_c 허용 집합과 대조). 실제 LLM·마이크는 쓰지 않는다.
"""

import ast
import json
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, main, validator

ROOT = Path(__file__).resolve().parents[3]
ENVELOPE_KEYS = {"status", "hri_result", "design", "design_metadata", "questions", "error"}
REASON = "사용자가 설계를 바꾸고 싶어 해요."


def block(x, y, layer, brick_type="2x2x1", color="blue", orientation_deg=0):
    return {"brick_type": brick_type, "color": color, "x": x, "y": y, "layer": layer, "orientation_deg": orientation_deg}


LOW = [block(10, 10, 1), block(12, 10, 1), block(11, 10, 2, color="yellow")]          # 2층 의자 골격
TALL = LOW + [block(11, 10, 3), block(11, 10, 4, color="yellow")]                    # 4층까지 조립된 Current
# TALL을 그대로 두고 1층 다리 위에 빨간 1x2x1 두 개(각 2/2 stud 지지)를 더한 Revised 후보: 최대층 4, 블록 7개.
TALL_PLUS = TALL + [block(10, 10, 2, "1x2x1", "red"), block(13, 10, 2, "1x2x1", "red")]
APPROVED_TALL = {"design_version": 1, "blocks": [dict(b) for b in TALL]}


def test_fixtures_are_valid_inputs():
    assert validator.validate_design({"design_version": 1, "blocks": TALL_PLUS}) == []
    assert validator.validate_revised({"blocks": TALL_PLUS}, TALL) == []
    assert validator.check_design_change_input(APPROVED_TALL, TALL) == []


# ---------------------------------------------------------------------------
# 1. 결정적 충돌 판정·문장
# ---------------------------------------------------------------------------


def test_constraints_vs_current():
    assert main.constraints_vs_current({"max_layer": 3}, TALL) == {"max_layer": {"requested": 3, "current": 4}}
    assert main.constraints_vs_current({"max_layer": 4, "complexity": "simple"}, TALL) == {}
    assert main.constraints_vs_current({"max_blocks": 3}, TALL) == {"max_blocks": {"requested": 3, "current": 5}}
    assert main.constraints_vs_current({"max_layer": 1}, []) == {}                         # Current 없음: 충돌 없음
    assert main.constraints_vs_current({}, TALL, {"assembled": False, "layers": [4]}) == {"removal": {"layers": [4]}}
    assert main.constraints_vs_current({}, LOW, {"assembled": False, "layers": [4]}) == {}  # 4층은 아직 없다
    assert main.constraints_vs_current({}, TALL, {"assembled": True, "layers": []}) == {"removal": {"layers": []}}


@pytest.mark.parametrize("text, expected", [
    ("4층 블록은 빼고 다시 바꿔줘", {"assembled": False, "layers": [4]}),
    ("조립된 블록 없애줘", {"assembled": True, "layers": []}),
    ("이미 쌓은 거 치워줘", {"assembled": True, "layers": []}),
    ("빨간 장식은 빼고 다시 만들어줘", None),       # 아직 조립 전인 부분은 Revised가 자유롭게 바꾼다
    ("조립된 블록은 빼지 마", None),               # 부정
    ("", None),
])
def test_removal_request(text, expected):
    assert dialogue.removal_request(text) == expected


def test_conflict_question_is_polite_korean_without_codes():
    conflict = {"max_layer": {"requested": 3, "current": 4}}
    question = dialogue.build_constraint_conflict_question(conflict, {"max_layer": 3}, design_change=True)
    assert question == ("지금 4층까지 이미 조립돼 있어서 그 부분은 그대로 두어야 해요.\n"
                        "지금 설계를 그대로 둘까요, 아니면 조립된 부분은 두고 나머지만 낮게 바꿀까요?")
    intervention = dialogue.build_constraint_conflict_question(
        {"max_blocks": {"requested": 3, "current": 5}, "removal": {"layers": [4]}}, {}, design_change=False)
    assert "블록 5개가 이미 조립돼" in intervention and "빼거나 없앨 수 없어서" in intervention
    assert "놓인 블록을 원래대로 돌리고 지금 설계를 그대로 둘까요" in intervention
    for text in (question, intervention):
        assert not any(code in text for code in ("max_layer", "max_blocks", "KEEP", "REVISE", "removal", "_"))


@pytest.mark.parametrize("answer, decision", [
    ("조립된 부분은 두고 나머지만 낮게 바꿔주세요", dialogue.REVISE), ("나머지만", dialogue.REVISE), ("2번", dialogue.REVISE),
    ("지금 설계 그대로 해줘", dialogue.KEEP), ("그대로 둘게요", dialogue.KEEP), ("1번", dialogue.KEEP),
    ("취소할게", dialogue.CANCEL), ("나머지는 취소", dialogue.CANCEL), ("글쎄요 잘 모르겠어요", dialogue.UNCLEAR),
])
def test_parse_constraint_conflict_response(answer, decision):
    assert dialogue.parse_constraint_conflict_response(answer) == decision


# ---------------------------------------------------------------------------
# 2. Direct Design Change 사례 G (Current 4층 + "3층 이하로")
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.delenv("C_DESIGN_USE_LLM", raising=False)
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)


def _change(answers, **kwargs):
    result = main.run_design_change(APPROVED_TALL, [dict(b) for b in TALL], reason=REASON, text_answers=answers, **kwargs)
    assert set(result) == ENVELOPE_KEYS
    return result


def test_g_keep_after_conflict_question(mock_mode):
    result = _change(["3층 이하로 바꿔주세요", "지금 설계 그대로 해줘"])
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.KEEP)
    assert result["design"] == APPROVED_TALL
    assert len(result["questions"]) == 2 and result["questions"][1].startswith("지금 4층까지 이미 조립돼")


def test_g_answers_exhausted_after_conflict_question_is_unclear(mock_mode):
    result = _change(["3층 이하로 바꿔주세요"])
    assert (result["status"], result["hri_result"], result["design"]) == ("OK", dialogue.UNCLEAR, None)
    assert result["questions"][1].startswith("지금 4층까지 이미 조립돼")


def test_g_unclear_twice_ends_unclear_after_one_reask(mock_mode):
    result = _change(["3층 이하로 바꿔주세요", "글쎄요 잘 모르겠어요", "글쎄요 잘 모르겠어요", "나머지만"])
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.UNCLEAR)  # 세 번째 답은 듣지 않는다
    assert len(result["questions"]) == 3 and result["questions"][2].startswith(dialogue.CONSTRAINT_CONFLICT_REASK_LEAD)


def test_g_cancel_after_conflict_question(mock_mode):
    result = _change(["3층 이하로 바꿔주세요", "취소할게"])
    assert (result["status"], result["hri_result"], result["error"]["code"]) == ("CANCELLED", None, "USER_CANCEL")


def test_g_stop_during_conflict_question(mock_mode):
    flags = {"stop": False}

    def on_question(text):
        if text.startswith("지금 4층까지"):
            flags["stop"] = True
    result = _change(["3층 이하로 바꿔주세요", "나머지만"], on_question=on_question, should_stop=lambda: flags["stop"])
    assert (result["status"], result["error"]["code"]) == ("CANCELLED", "STOPPED")


def test_g_voice_repeated_unclear_answer_does_not_hang(mock_mode, monkeypatch):
    heard, spoken = [], []
    replies = iter(["3층 이하로 바꿔주세요"])

    def listen(on_ready=None, mode="short", beep=False):
        heard.append(mode)
        return next(replies, "글쎄요 잘 모르겠어요")  # 같은 답을 끝없이 반복하는 fake
    monkeypatch.setattr(main.voice, "listen", listen)
    monkeypatch.setattr(main.voice, "speak", spoken.append)
    result = main.run_design_change(APPROVED_TALL, [dict(b) for b in TALL], reason=REASON, text_answers=None)
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.UNCLEAR)
    assert len(heard) == 3                                           # 첫 답 + 충돌 질문 답 2번(질문 + 재질문 1회)
    assert len(spoken) == 3 and spoken[1].startswith("지금 4층까지")


@pytest.mark.parametrize("answer, phrase", [("블록 3개까지만 쓰게 바꿔줘", "지금 블록 5개가 이미 조립돼"),
                                            ("4층 블록은 빼고 다시 바꿔줘", "이미 조립된 블록은 제가 빼거나 없앨 수 없어서")])
def test_block_count_and_removal_requests_use_the_same_question(mock_mode, answer, phrase):
    result = _change([answer, "그대로 둘게요"])
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.KEEP)
    assert phrase in result["questions"][1]


JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True,
            "design_family": "armchair", "design_name": "의자", "visible_features": [], "completeness_score": 4}


@pytest.fixture
def llm_fakes(monkeypatch):
    """C 내부 llm 함수만 fake. 시그니처에 constraints 인자가 없다(제약은 llm.stated_limits 컨텍스트, 결정 D-1)."""
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    calls = {"generate": [], "judge": [], "interpret": []}
    promise = {"decision": "REVISE", "style_hint": "3층까지만", "reason": "낮게 원하셨어요.",
               "reply": "네, 3층까지만 낮게 다시 만들어볼게요."}  # 지킬 수 없는 약속: ACK로 쓰이면 안 된다

    def interpret(text, reason, should_stop=None, context=None, planning_failure=None):
        calls["interpret"].append(text)
        return dict(promise)

    def generate(design, current, differences, reasons=None, should_stop=None, feedback=None, min_blocks=None,
                 style_hint=None, change_request=None):
        calls["generate"].append({"min_blocks": min_blocks, "limits": llm.active_stated_limits()})
        return {"blocks": [dict(b) for b in TALL_PLUS]}

    def judge(previous, design, current, differences, should_stop=None):
        calls["judge"].append(llm.active_stated_limits())
        return dict(JUDGE_OK)

    monkeypatch.setattr(main.llm, "interpret_design_change_answer", interpret)
    monkeypatch.setattr(main.llm, "generate_revised_design", generate)
    monkeypatch.setattr(main.llm, "judge_revised_design", judge)
    return calls


def test_g_revise_clamps_to_current_and_acks_only_after_the_question(llm_fakes):
    timeline = []
    result = _change(["3층 이하로 바꿔주세요", "조립된 부분은 두고 나머지만 낮게 바꿔주세요"],
                     on_question=lambda text: timeline.append(("Q", text)),
                     on_progress=lambda event: timeline.append((event["stage"], event["message"])))
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.REVISE)
    assert result["design"]["design_version"] == 2
    assert validator.validate_revised({"blocks": result["design"]["blocks"]}, TALL) == []   # Current 보존(4층 그대로)
    conflict_at = next(i for i, item in enumerate(timeline) if item[0] == "Q" and item[1].startswith("지금 4층까지"))
    acks = [i for i, item in enumerate(timeline) if item[0] == "ACK"]
    assert len(acks) == 1 and acks[0] > conflict_at                                      # ACK는 충돌 확인 뒤에만
    assert timeline[acks[0]][1] == "알겠습니다. 이미 조립된 4층까지는 그대로 두고 나머지만 맞춰서 다시 만들어볼게요."
    assert all("3층까지만 낮게 다시 만들어볼게요" not in str(item[1]) for item in timeline)  # 약속 reply는 읽지 않는다
    # 충돌 답의 "낮게"도 이번 요청의 제한으로 합쳐진다(규칙 추출). 3층은 조립된 4층으로 맞춘다.
    limits = {"max_layer": 4, "height": "low"}
    assert llm_fakes["generate"] == [{"min_blocks": None, "limits": limits}]
    assert llm_fakes["judge"] == [limits]
    metadata = result["design_metadata"]
    assert metadata["user_constraints"] == limits
    assert metadata["constraint_clamp"] == {"requested": {"max_layer": 3, "height": "low"}, "applied": limits}


def test_g_answer_with_a_new_limit_is_merged_and_clamped(llm_fakes):
    result = _change(["3층 이하로 바꿔주세요", "그럼 나머지만 간단하게 바꿔주세요"])
    assert result["hri_result"] == dialogue.REVISE
    assert llm_fakes["generate"][0]["limits"] == {"max_layer": 4, "complexity": "simple"}


def test_f_no_conflict_when_current_is_below_the_limit(monkeypatch):
    """사례 F: Current에 4층이 없으면 질문 없이 v2 ≤ 3층·Current 보존(Difference Intervention)."""
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    approved = {"design_version": 1, "blocks": [dict(b) for b in LOW]}
    moved = dict(LOW[1], y=11)
    current = [dict(LOW[0]), moved]
    candidate = current + [block(10, 10, 2, "2x3x1", "yellow", 90)]  # 다리 둘 위 좌석(4 stud 이상 지지)
    seen = []
    monkeypatch.setattr(main.llm, "interpret_intervention_answer", lambda text, differences, should_stop=None: {
        "decision": "REVISE", "style_hint": "", "reason": "r", "reply": "네."})
    monkeypatch.setattr(main.llm, "generate_revised_design", lambda *a, **k: (seen.append(llm.active_stated_limits()),
                                                                               {"blocks": candidate})[1])
    monkeypatch.setattr(main.llm, "judge_revised_design", lambda *a, **k: dict(JUDGE_OK))
    result = main.run_intervention(approved, current, [{"expected": dict(LOW[1]), "actual": moved}],
                                   text_answers=["3층 이하로 바꿔주세요"])
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.REVISE)
    assert len(result["questions"]) == 1                                    # 충돌 질문 없음
    assert max(b["layer"] for b in result["design"]["blocks"]) <= 3
    assert validator.validate_revised({"blocks": result["design"]["blocks"]}, current) == []
    assert seen == [{"max_layer": 3}] and result["design_metadata"]["constraint_clamp"] is None


def test_intervention_conflict_keeps_by_restoring_the_block(mock_mode):
    approved = {"design_version": 1, "blocks": [dict(b) for b in TALL_PLUS]}
    current = [dict(b) for b in TALL] + [dict(TALL_PLUS[5])]
    differences = [{"expected": dict(TALL_PLUS[6]), "actual": None}]
    result = main.run_intervention(approved, current, differences, text_answers=["3층 이하로 바꿔주세요", "그대로 둘게요"])
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.KEEP) and result["design"] == approved
    assert "놓인 블록을 원래대로 돌리고 지금 설계를 그대로 둘까요" in result["questions"][1]


# ---------------------------------------------------------------------------
# 3. Review MODIFY(revised): 질문 없이 clamp + 고지 + metadata
# ---------------------------------------------------------------------------


def test_review_modify_clamps_and_notices_without_a_question(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    candidate = {"design_version": 2, "blocks": [dict(b) for b in TALL_PLUS[:6]]}
    seen = []
    monkeypatch.setattr(main.llm, "interpret_review_answer", lambda *a, **k: {
        "decision": "MODIFY", "style_hint": "3층까지만", "scope": "patch", "concept": "", "reason": "r",
        "reply": "좋아요. 3층까지만 낮게 다시 만들어볼게요."})
    monkeypatch.setattr(main.llm, "generate_revised_design", lambda *a, **k: (seen.append(llm.active_stated_limits()),
                                                                               {"blocks": [dict(b) for b in TALL_PLUS]})[1])
    monkeypatch.setattr(main.llm, "judge_revised_design", lambda *a, **k: dict(JUDGE_OK))
    events = []
    result = main.review_design_candidate(candidate, kind="revised", design_metadata={}, previous_design=APPROVED_TALL,
                                          current=[dict(b) for b in TALL], differences=[], change_reason=REASON,
                                          text_answers=["3층까지만 낮게 바꿔줘"], on_progress=events.append)
    assert (result["status"], result["hri_result"]) == ("OK", dialogue.MODIFY)
    assert len(result["questions"]) == 1                                                  # 검토 질문만(충돌 질문 없음)
    ack = next(event["message"] for event in events if event["stage"] == "REVIEW_ACK")
    assert ack.endswith("\n다만 이미 조립된 4층까지는 그대로 두고 나머지만 맞출게요.")
    assert seen == [{"max_layer": 4, "height": "low"}]
    assert result["design"]["design_version"] == 2
    assert validator.validate_revised({"blocks": result["design"]["blocks"]}, TALL) == []
    assert result["design_metadata"]["constraint_clamp"] == {"requested": {"max_layer": 3, "height": "low"},
                                                             "applied": {"max_layer": 4, "height": "low"}}


# ---------------------------------------------------------------------------
# 4. 새 값 없음: D mvp_workflow.receive_c 허용 집합(read-only, 소스 파싱)과 envelope 키
# ---------------------------------------------------------------------------


def _d_allowed_decisions():
    """D 소유 app/mvp_workflow.py의 receive_c 허용 집합을 import 없이 소스에서 읽는다(D 코드 변경·실행 없음)."""
    tree = ast.parse((ROOT / "app/mvp_workflow.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "allowed" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict) and "c.intent" in value:
                return value
    raise AssertionError("receive_c allowed set not found")


def test_conflict_outcomes_stay_inside_the_d_allowed_set(mock_mode):
    allowed = _d_allowed_decisions()
    assert allowed["c.intent"] == allowed["c.plan_failure"] == ("KEEP", "REVISE", "UNCLEAR")
    assert set(allowed["c.review"]) == {"APPROVE", "MODIFY", "UNCLEAR"}
    assert {dialogue.KEEP, dialogue.REVISE, dialogue.UNCLEAR} == set(allowed["c.intent"])
    outcomes = [_change(answers) for answers in (["3층 이하로 바꿔주세요", "그대로 둘게요"], ["3층 이하로 바꿔주세요"],
                                                 ["3층 이하로 바꿔주세요", "취소할게"])]
    for result in outcomes:
        if result["status"] == "OK":
            assert result["hri_result"] in allowed["c.intent"]
        else:
            assert result["status"] in ("CANCELLED", "FAILED")                    # D는 status != OK를 HOLD로 처리
            assert result["error"]["code"] in ("USER_CANCEL", "STOPPED", "VOICE_IO_FAILED", "INVALID_INPUT",
                                               "DESIGN_GENERATION_FAILED", "LLM_CALL_FAILED")
        json.dumps(result)
