"""Stage 3 Wave 3: fake D caller로 C public API lifecycle을 시험한다(C-side caller fixture, offline).

D가 C를 호출하고 response를 받는다. 여기의 caller는 D 구현이 아니라 테스트 helper다: C API 호출 → response 수신 →
PREVIEW_READY 가정(sleep 없음) → 다음 API 호출. Candidate와 Approved는 caller가 들고 있는 변수(approved / candidate)로
구분한다(채택은 caller 몫이며 Design에 승인 표시는 없다). 실제 D/HMI integration은 팀 통합 단계다.

LLM 함수(요청·검토·Intervention 해석, Initial·Revised 생성, 설명, judge)는 모두 fake이고 네트워크·오디오는
tests/conftest.py가 막는다. 시나리오 2·3·6은 명세대로 LLM 모드(C_DESIGN_USE_LLM=1) + fake llm 함수로 검증한다.
"""

import copy

import pytest

from app.c_design import designer, dialogue, llm, main, validator, voice

ENVELOPE_KEYS = {"status", "hri_result", "design", "design_metadata", "questions", "error"}
DESIGN_KEYS = {"design_version", "blocks"}
REVIEW_QUESTION = {kind: dialogue.REVIEW_QUESTIONS[kind] for kind in ("initial", "revised")}


# ---------------------------------------------------------------------------
# fake LLM (C 내부 llm 함수만 바꾼다; main·dialogue·designer·validator는 실제 코드)
# ---------------------------------------------------------------------------


def _swap_colors(blocks, keep=()):
    """yellow↔blue(2x2x1·2x3x1 모두 허용 조합). keep에 든 위치·층 블록은 그대로(Current 보존)."""
    kept = {(b["x"], b["y"], b["layer"]) for b in keep}
    swapped = []
    for block in blocks:
        block = dict(block)
        if (block["x"], block["y"], block["layer"]) not in kept and block["color"] in ("yellow", "blue"):
            block["color"] = "blue" if block["color"] == "yellow" else "yellow"
        swapped.append(block)
    return swapped


def _judge(**overrides):
    base = {"design_family": "armchair", "design_name": "수정 후보", "visible_features": ["넓은 좌석"],
            "why_it_is_complete": "좌석·등받이·지지가 보인다", "change_summary": ["좌석을 넓혔다"],
            "interpretation_status": "clearly visible", "reads_as_seating": True, "recognizable_family": True,
            "family_confidence": "clear", "silhouette_clarity": "clear", "explanation_required_to_understand": False,
            "layer5_meaningful": False, "completeness_score": 4, "awkward": "없음", "chair_likeness": "clear",
            "richer_than_previous": True, "richer_why": "더 넓어졌다", "human_story": None}
    base.update(overrides)
    return base


class FakeLLM:
    """llm 함수 대역. 호출 인자를 기록하고 시나리오가 정한 응답을 순서대로 돌려준다."""

    def __init__(self):
        self.calls = {name: [] for name in ("request", "review", "answer", "initial", "revised", "describe", "judge")}
        self.reviews = []      # interpret_review_answer 응답 목록(순서대로)
        self.answers = []      # interpret_intervention_answer 응답 목록
        self.judges = []       # judge 응답 목록(비면 _judge())
        self.families = []     # describe가 돌려줄 family 목록(비면 입력 family 또는 "armchair")

    def interpret_initial_request(self, text, should_stop=None):
        self.calls["request"].append(text)
        return {"object": "CHAIR", "preference": "ANY", "family": None, "style_hint": "", "sufficient": True,
                "follow_up": "", "reply": "좋아요. 제가 어울리는 의자를 골라서 만들어볼게요."}

    def interpret_review_answer(self, text, kind, should_stop=None, context=None):
        self.calls["review"].append({"text": text, "kind": kind, "context": copy.deepcopy(context)})
        return self.reviews.pop(0)

    def interpret_intervention_answer(self, text, differences, should_stop=None):
        self.calls["answer"].append(text)
        return self.answers.pop(0)

    def generate_initial_design(self, object_type, reasons=None, should_stop=None, family=None, style_hint=None,
                                concept=None, previous_candidate=None, scope=None):
        self.calls["initial"].append({"family": family, "style_hint": style_hint, "concept": concept,
                                      "previous_candidate": previous_candidate, "scope": scope})
        blocks = designer.mock_initial_candidate(object_type)["blocks"]
        if len(self.calls["initial"]) % 2 == 0:  # 두 번째 생성마다 다른 후보(색 반전)
            blocks = _swap_colors(blocks)
        return {"blocks": blocks}

    def generate_revised_design(self, design, current, differences, reasons=None, should_stop=None, feedback=None,
                                min_blocks=None, style_hint=None, previous_candidate=None, scope=None):
        self.calls["revised"].append({"approved": design, "style_hint": style_hint, "previous_candidate": previous_candidate,
                                      "scope": scope, "min_blocks": min_blocks})
        candidate = designer.mock_revised_candidate(design, current, differences)
        if len(self.calls["revised"]) % 2 == 0:  # 두 번째 생성마다 Current 밖 블록만 색 반전
            candidate = {"blocks": _swap_colors(candidate["blocks"], keep=current)}
        return candidate

    def describe_initial_design(self, design, should_stop=None, family=None, concept=None):
        self.calls["describe"].append({"family": family, "concept": concept})
        shown = self.families.pop(0) if self.families else (family or "armchair")
        return {"design_family": shown, "design_name": "후보", "design_summary": "요약", "visible_features": [],
                "silhouette_clarity": "clear", "recognizable_family": True, "completeness_score": 4,
                "family_design_match": "clear"}

    def judge_revised_design(self, previous, design, current, differences, should_stop=None):
        self.calls["judge"].append(design)
        return self.judges.pop(0) if self.judges else _judge()


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(designer, "RICHNESS_MIN_DELTA", 0)  # fake 후보는 블록 수를 늘리지 않는다
    fake = FakeLLM()
    for name in ("interpret_initial_request", "interpret_review_answer", "interpret_intervention_answer",
                 "generate_initial_design", "generate_revised_design", "describe_initial_design", "judge_revised_design"):
        monkeypatch.setattr(llm, name, getattr(fake, name))
    monkeypatch.setattr(llm, "choose_initial_family", lambda preference, rng=None: "armchair")
    return fake


def review_reply(decision, style_hint="", scope="", concept="", reply=""):
    return {"decision": decision, "style_hint": style_hint, "scope": scope, "concept": concept, "reason": "…",
            "reply": reply}


# ---------------------------------------------------------------------------
# fake D caller (테스트 helper, production 아님)
# ---------------------------------------------------------------------------


class Caller:
    """D 역할의 최소 caller: C public API를 부르고 response를 받아 다음 호출을 정한다."""

    def __init__(self):
        self.approved = None        # 채택(Approved) Design: review가 APPROVE를 돌려줬을 때만 caller가 바꾼다
        self.candidate = None       # 화면에 보일(Preview) 후보 Design
        self.metadata = None        # 그 후보의 design_metadata(다음 review에 그대로 넘긴다)
        self.log = []               # (api, response) 기록
        self.progress = []          # (api, event) 기록
        self.preview_ready = 0      # fake PREVIEW_READY 횟수

    def _call(self, api, func, *args, **kwargs):
        events = []
        response = func(*args, on_progress=events.append, **kwargs)
        assert set(response) == ENVELOPE_KEYS
        self.log.append((api, response))
        self.progress.append((api, events))
        return response

    def initial(self, text):
        response = self._call("create_initial_design", main.create_initial_design, text=text)
        if response["status"] == "OK":
            self.candidate, self.metadata = response["design"], response["design_metadata"]
        return response

    def assume_preview_ready(self):
        self.preview_ready += 1  # D가 Preview 표시를 끝냈다고 가정(실제 HMI 없음, sleep 없음)

    def review(self, answers, kind="initial", intervention=None):
        self.assume_preview_ready()
        extra = {}
        if kind == "revised":
            extra = {"previous_design": self.approved, "current": intervention["current"],
                     "differences": intervention["differences"]}
        response = self._call("review_design_candidate", main.review_design_candidate, self.candidate, kind=kind,
                              design_metadata=self.metadata, text_answers=list(answers), **extra)
        if response["hri_result"] == "APPROVE":
            self.approved = response["design"]  # 채택은 caller 몫
        elif response["hri_result"] == "MODIFY" and response["status"] == "OK":
            self.candidate, self.metadata = response["design"], response["design_metadata"]
        return response

    def intervene(self, current, differences, answers):
        response = self._call("run_intervention", main.run_intervention, self.approved, current, differences,
                              text_answers=list(answers))
        if response["hri_result"] == "REVISE" and response["status"] == "OK":
            self.candidate, self.metadata = response["design"], response["design_metadata"]
        return response


def _difference_from(approved):
    """caller가 Approved의 layer-1 블록 하나를 1 stud 옮긴 Current/Difference를 만든다."""
    legs = [b for b in approved["blocks"] if b["layer"] == 1]
    target = max(legs, key=lambda b: b["y"])
    moved = dict(target, y=target["y"] + 1)
    current = [moved if b is target else dict(b) for b in legs]
    differences = [{"expected": dict(target), "actual": moved}]
    assert validator.check_intervention_input(approved, current, differences) == []
    return {"current": current, "differences": differences}


def _stages(events):
    return [event["stage"] for event in events]


def _review_meta(response):
    return response["design_metadata"]["review"]


def _approve_candidate(caller):
    """시나리오 4~6의 출발점: Initial → Preview → APPROVE로 Approved v1을 만든다."""
    caller.initial("의자 만들어줘")
    caller.review(["좋아 이걸로 하자"])
    assert caller.approved is not None and caller.approved["design_version"] == 1
    return caller.approved


# ---------------------------------------------------------------------------
# 시나리오 1~8
# ---------------------------------------------------------------------------


def test_1_initial_preview_approve(fake_llm):
    caller = Caller()
    initial = caller.initial("의자 만들어줘")
    assert (initial["status"], initial["hri_result"]) == ("OK", None)
    candidate = initial["design"]
    assert candidate["design_version"] == 1 and set(candidate) == DESIGN_KEYS
    response = caller.review(["좋아 이걸로 하자"])
    assert (response["status"], response["hri_result"]) == ("OK", "APPROVE")
    assert response["design"] == candidate and caller.approved == candidate
    assert fake_llm.calls["initial"] and len(fake_llm.calls["initial"]) == 1  # APPROVE는 생성하지 않는다
    assert _review_meta(response)["round"] == 0 and caller.preview_ready == 1


def test_2_modify_patch_then_approve(fake_llm):
    caller = Caller()
    caller.initial("의자 만들어줘")
    candidate_a, metadata_a = caller.candidate, copy.deepcopy(caller.metadata)
    fake_llm.reviews = [review_reply("MODIFY", "등받이를 더 높게", "patch", reply="좋아요. 등받이를 높여 볼게요.")]
    modify = caller.review(["등받이를 더 높게"])
    candidate_b = modify["design"]
    assert (modify["status"], modify["hri_result"]) == ("OK", "MODIFY")
    assert candidate_b != candidate_a and candidate_b["design_version"] == 1 == candidate_a["design_version"]
    assert validator.validate_design(candidate_b) == []
    assert caller.approved is None  # MODIFY 후보는 승인이 아니다
    assert fake_llm.calls["initial"][-1]["previous_candidate"] == candidate_a
    assert fake_llm.calls["initial"][-1]["scope"] == "patch" and fake_llm.calls["initial"][-1]["family"] == "armchair"
    assert _review_meta(modify)["round"] == 1 and modify["design_metadata"]["family_source"] == "patch"
    generated = len(fake_llm.calls["initial"])
    approve = caller.review(["좋아 이걸로 하자"])
    assert (approve["hri_result"], approve["design"]) == ("APPROVE", candidate_b)
    assert len(fake_llm.calls["initial"]) == generated  # APPROVE 생성 0회
    assert _review_meta(approve)["round"] == 1 and caller.approved == candidate_b
    assert caller.metadata is not metadata_a and "review" not in metadata_a  # 이전 metadata가 덮이지 않음
    assert [stage for stage in _stages(caller.progress[1][1]) if stage in ("REVIEW_ACK", "GENERATING")] == ["REVIEW_ACK",
                                                                                                         "GENERATING"]


def test_3_modify_redesign_then_approve(fake_llm):
    caller = Caller()
    caller.initial("의자 만들어줘")
    candidate_a = caller.candidate
    fake_llm.reviews = [review_reply("MODIFY", "현재 디자인과 다른 새로운 형태", "redesign")]
    fake_llm.families = ["throne"]  # redesign은 family 변경을 허용한다
    modify = caller.review(["완전히 다른 느낌으로 다시"])
    candidate_b = modify["design"]
    assert candidate_b != candidate_a and candidate_b["design_version"] == 1
    assert validator.validate_design(candidate_b) == []
    assert fake_llm.calls["initial"][-1]["family"] is None and fake_llm.calls["initial"][-1]["scope"] == "redesign"
    assert modify["design_metadata"]["design_family"] == "throne" and _review_meta(modify)["round"] == 1
    approve = caller.review(["마음에 들어"])
    assert approve["hri_result"] == "APPROVE" and caller.approved == candidate_b and _review_meta(approve)["round"] == 1


def test_4_intervention_keep(fake_llm):
    caller = Caller()
    approved = _approve_candidate(caller)
    case = _difference_from(approved)
    response = caller.intervene(case["current"], case["differences"], ["제가 잘못 놨어요"])
    assert (response["status"], response["hri_result"]) == ("OK", "KEEP")
    assert response["design"] == approved and fake_llm.calls["revised"] == []


def test_5_intervention_revise_then_review_approve(fake_llm):
    caller = Caller()
    approved = _approve_candidate(caller)
    case = _difference_from(approved)
    fake_llm.answers = [{"decision": "REVISE", "style_hint": "", "reason": "…", "reply": "알겠습니다. 다시 만들어볼게요."}]
    revise = caller.intervene(case["current"], case["differences"], ["일부러 그렇게 놨어요"])
    assert (revise["status"], revise["hri_result"]) == ("OK", "REVISE")
    revised_candidate = revise["design"]
    assert revised_candidate["design_version"] == 2 and caller.approved == approved  # 승인은 아직 v1
    assert validator.validate_revised({"blocks": revised_candidate["blocks"]}, case["current"]) == []
    approve = caller.review(["좋아 이걸로 하자"], kind="revised", intervention=case)
    assert (approve["hri_result"], approve["design"]) == ("APPROVE", revised_candidate)
    assert caller.approved == revised_candidate and caller.approved["design_version"] == 2
    assert approve["questions"] == [REVIEW_QUESTION["revised"]]


def test_6_revised_modify_then_approve(fake_llm):
    caller = Caller()
    approved = _approve_candidate(caller)
    case = _difference_from(approved)
    fake_llm.answers = [{"decision": "REVISE", "style_hint": "", "reason": "…", "reply": ""}]
    caller.intervene(case["current"], case["differences"], ["일부러 그렇게 놨어요"])
    candidate_a = caller.candidate
    judges_before = len(fake_llm.calls["judge"])
    fake_llm.reviews = [review_reply("MODIFY", "조금 더 넓게", "patch")]
    modify = caller.review(["조금 더 넓게"], kind="revised", intervention=case)
    candidate_b = modify["design"]
    assert (modify["status"], modify["hri_result"]) == ("OK", "MODIFY")
    assert candidate_b != candidate_a
    assert candidate_a["design_version"] == candidate_b["design_version"] == approved["design_version"] + 1 == 2
    for candidate in (candidate_a, candidate_b):
        assert validator.validate_revised({"blocks": candidate["blocks"]}, case["current"]) == []  # Current 보존
    assert len(fake_llm.calls["judge"]) == judges_before + 1  # judge 경로
    last = fake_llm.calls["revised"][-1]
    assert (last["approved"], last["previous_candidate"], last["scope"]) == (approved, candidate_a, "patch")
    assert _review_meta(modify)["round"] == 1
    generated = len(fake_llm.calls["revised"])
    approve = caller.review(["좋아 이걸로 하자"], kind="revised", intervention=case)
    assert approve["hri_result"] == "APPROVE" and approve["design"] == candidate_b
    assert len(fake_llm.calls["revised"]) == generated and _review_meta(approve)["round"] == 1
    assert caller.approved == candidate_b


@pytest.mark.parametrize("second, expected", [("좋아 이걸로 하자", "APPROVE"), ("등받이를 더 높게", "MODIFY")])
def test_7_unclear_reask_then_decision(fake_llm, second, expected):
    caller = Caller()
    caller.initial("의자 만들어줘")
    fake_llm.reviews = [review_reply("UNCLEAR"), review_reply("MODIFY", "등받이를 더 높게", "patch")]
    response = caller.review(["음…", second])
    assert response["hri_result"] == expected
    assert response["questions"] == [REVIEW_QUESTION["initial"], dialogue.REVIEW_REASK]


def test_8_review_cancel(fake_llm):
    caller = Caller()
    caller.initial("의자 만들어줘")
    candidate = caller.candidate
    response = caller.review(["그만할래"])
    assert (response["status"], response["hri_result"], response["error"]["code"]) == ("CANCELLED", "CANCEL", "USER_CANCEL")
    assert response["design"] == candidate and caller.approved is None
    assert _stages(caller.progress[-1][1])[-1] == "CANCELLED"


# ---------------------------------------------------------------------------
# 호출 간 상태 오염 없음
# ---------------------------------------------------------------------------


def test_sequential_calls_do_not_leak_state(fake_llm):
    caller = Caller()
    initial = caller.initial("의자 만들어줘")
    fake_llm.reviews = [review_reply("MODIFY", "등받이를 더 높게", "patch")]
    first = caller.review(["등받이를 더 높게"])
    second = caller.review(["좋아 이걸로 하자"])
    case = _difference_from(caller.approved)
    fake_llm.answers = [{"decision": "REVISE", "style_hint": "", "reason": "…", "reply": ""}]
    revise = caller.intervene(case["current"], case["differences"], ["일부러 그렇게 놨어요"])
    third = caller.review(["마음에 들어"], kind="revised", intervention=case)

    # 질문은 그 호출의 것만(이전 호출의 질문·답변이 섞이지 않음)
    assert initial["questions"] == []
    assert first["questions"] == [REVIEW_QUESTION["initial"]] and second["questions"] == [REVIEW_QUESTION["initial"]]
    assert len(revise["questions"]) == 1 and revise["questions"][0].startswith("Design과 다르게 놓인 부분이 있는데")
    assert third["questions"] == [REVIEW_QUESTION["revised"]]
    # review metadata는 그 호출의 결정만 담고, 이전 응답 객체는 바뀌지 않는다
    assert _review_meta(first)["decision"] == "MODIFY" and _review_meta(second)["decision"] == "APPROVE"
    assert _review_meta(third)["decision"] == "APPROVE" and _review_meta(third)["kind"] == "revised"
    assert _review_meta(third)["round"] == 0  # Revised 후보의 새 반복(Initial 검토 round가 넘어오지 않음)
    assert _review_meta(first)["round"] == 1 and _review_meta(first)["answers"] == 1
    # design_version은 호출 횟수로 늘지 않는다(Initial 1, Revised = Approved + 1)
    assert [r["design"]["design_version"] for _, r in caller.log] == [1, 1, 1, 2, 2]
    # 후보는 승인 표시를 갖지 않는다(Design 키 2개, 승인은 caller 변수)
    assert all(set(r["design"]) == DESIGN_KEYS for _, r in caller.log)
    assert caller.approved == third["design"]


def test_same_candidate_reviewed_twice_depends_only_on_its_input(fake_llm):
    caller = Caller()
    caller.initial("의자 만들어줘")
    candidate, metadata = caller.candidate, copy.deepcopy(caller.metadata)
    a = main.review_design_candidate(candidate, kind="initial", design_metadata=metadata, text_answers=["좋아요"])
    b = main.review_design_candidate(candidate, kind="initial", design_metadata=metadata, text_answers=["좋아요"])
    assert a["design"] == b["design"] == candidate
    assert {k: v for k, v in _review_meta(a).items() if k != "reply"} == {k: v for k, v in _review_meta(b).items()
                                                                           if k != "reply"}
    assert metadata == caller.metadata  # 입력 metadata는 호출 뒤에도 그대로


# ---------------------------------------------------------------------------
# Voice 독립성 (fake listen / speak)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_voice(monkeypatch):
    events = []
    heard = []

    def listen(on_ready=None, mode="short", beep=False):
        events.append(("listen", mode, beep))
        return heard.pop(0)

    monkeypatch.setattr(voice, "prewarm", lambda: events.append(("prewarm",)) or True)
    monkeypatch.setattr(voice, "listen", listen)
    monkeypatch.setattr(voice, "speak", lambda sentence: events.append(("speak", sentence)))
    return events, heard


def _segment(events, start):
    return events[start:]


def test_voice_each_call_starts_with_its_own_tts_and_listens_freshly(fake_llm, fake_voice):
    events, heard = fake_voice
    approved_holder = {}

    heard.append("의자 만들어줘")
    initial = main.create_initial_design()
    initial_part = list(events)
    assert initial["status"] == "OK"
    assert [e for e in initial_part if e[0] == "speak"][0] == ("speak", dialogue.GREETING)
    assert initial_part.count(("listen", "free", True)) == 1

    mark = len(events)
    heard.append("좋아 이걸로 하자")
    review = main.review_design_candidate(initial["design"], kind="initial", design_metadata=initial["design_metadata"])
    review_part = _segment(events, mark)
    assert review["hri_result"] == "APPROVE"
    assert review_part[0] == ("speak", REVIEW_QUESTION["initial"]) and review_part[1] == ("listen", "free", True)
    assert review_part.count(("listen", "free", True)) == 1
    approved_holder["design"] = review["design"]

    case = _difference_from(approved_holder["design"])
    mark = len(events)
    heard.append("제가 잘못 놨어요")
    keep = main.run_intervention(approved_holder["design"], case["current"], case["differences"])
    intervention_part = _segment(events, mark)
    assert keep["hri_result"] == "KEEP"
    assert intervention_part[0][0] == "speak"
    assert intervention_part[0][1].startswith("Design과 다르게 놓인 부분이 있는데")  # Difference 설명 질문
    assert "(x=" in intervention_part[0][1]
    assert intervention_part[1] == ("listen", "free", True) and intervention_part.count(("listen", "free", True)) == 1
    assert heard == []  # 각 호출이 자기 답 하나만 소비했다


def test_voice_revised_review_first_tts_is_revised_question(fake_llm, fake_voice):
    events, heard = fake_voice
    caller = Caller()
    approved = _approve_candidate(caller)
    case = _difference_from(approved)
    fake_llm.answers = [{"decision": "REVISE", "style_hint": "", "reason": "…", "reply": ""}]
    caller.intervene(case["current"], case["differences"], ["일부러 그렇게 놨어요"])
    mark = len(events)
    heard.append("마음에 들어")
    response = main.review_design_candidate(caller.candidate, kind="revised", design_metadata=caller.metadata,
                                            previous_design=approved, current=case["current"],
                                            differences=case["differences"])
    assert response["hri_result"] == "APPROVE"
    assert events[mark] == ("speak", REVIEW_QUESTION["revised"])


class _Stream:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        self.log.append("open")
        return self

    def __exit__(self, *exc):
        self.log.append("close")
        return False

    def read(self, frames):
        import numpy as np
        return np.zeros((frames, 1), dtype=np.int16), False


def test_record_opens_and_closes_the_input_stream_on_every_call(monkeypatch):
    """voice.record는 호출마다 InputStream을 열고 with 블록 끝에서 닫는다(호출 사이에 마이크를 잡고 있지 않음)."""
    log = []

    class FakeSD:
        def InputStream(self, **kwargs):
            return _Stream(log)

    monkeypatch.setattr(voice, "_sounddevice", lambda: FakeSD())
    assert voice.record() == b"" and voice.record() == b""  # 무음 → b""
    assert log == ["open", "close", "open", "close"]
