"""Stage 3 Wave 4: failure paths of the three C public APIs, as an external caller sees them.

LLM mode (C_DESIGN_USE_LLM=1) with fakes only: no network, no audio. Each case checks that the call returns (bounded
listen / LLM / generation calls), and records the status / error code / design the caller receives under the current
policy (CONTRACT §10, "caller가 받는 값"). Nothing here changes the policy.
"""

import copy
import json
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, main, voice

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "c_stage3"


def load(name):
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)


INITIAL = load("initial_candidate_response")
GIVEN = load("intervention_revise_input")
REVISED = load("intervention_revise_response")
OTHER_INITIAL = load("review_modify_patch_response")["design"]
JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True}


class Harness:
    """Fake voice and LLM for one test. listens / speaks / transport / generations are call logs."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.listens, self.speaks, self.transport, self.generations = [], [], [], []
        self.answers = iter(())
        monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
        monkeypatch.setenv("OPENAI_LLM_API_KEY", "test-key-not-real")
        monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
        monkeypatch.setattr(llm, "RETRY_BACKOFF", (0, 0, 0))
        monkeypatch.setattr(voice, "prewarm", lambda: True)
        monkeypatch.setattr(voice, "speak", lambda text, *a, **k: self.speaks.append(text))
        monkeypatch.setattr(voice, "listen", self._listen)
        monkeypatch.setattr(llm, "_post_json", lambda *a, **k: pytest.fail("set a transport or function fakes"))

    def _listen(self, *args, **kwargs):
        self.listens.append(kwargs)
        return next(self.answers, "")

    def hear(self, *answers):
        """Scripted listen results; after them listen keeps returning silence ("")."""
        self.answers = iter(answers)

    def fail_transport(self, kind):
        """Real llm.py functions over a broken transport: 'timeout' raises TimeoutError, 'badjson' returns non-JSON text."""
        def post(payload, api_key):
            self.transport.append(payload["model"])
            if kind == "timeout":
                raise TimeoutError()
            return {"choices": [{"message": {"content": "this is not json"}}]}
        self.monkeypatch.setattr(llm, "_post_json", post)

    def working_llm(self, initial_outputs=(OTHER_INITIAL,), revised_outputs=None, review=None, intervention=None):
        """Function-level fakes; generation returns the scripted outputs (the last one repeats)."""
        def generated(outputs):
            def generate(*args, **kwargs):
                self.generations.append(kwargs)
                return copy.deepcopy(outputs[min(len(self.generations), len(outputs)) - 1])
            return generate
        self.monkeypatch.setattr(llm, "interpret_initial_request", lambda text, should_stop=None: {
            "object": "CHAIR", "preference": "ANY", "family": None, "style_hint": "", "sufficient": True,
            "follow_up": "", "reply": "좋아요."})
        self.monkeypatch.setattr(llm, "generate_initial_design", generated(list(initial_outputs)))
        self.monkeypatch.setattr(llm, "describe_initial_design", lambda *a, **k: {"design_name": "의자"})
        self.monkeypatch.setattr(llm, "interpret_review_answer", lambda *a, **k: review or {
            "decision": "MODIFY", "style_hint": "등받이를 더 높게", "scope": "patch", "concept": "", "reason": "", "reply": ""})
        self.monkeypatch.setattr(llm, "interpret_intervention_answer", lambda *a, **k: intervention or {
            "decision": "REVISE", "style_hint": "더 넓게", "reason": "", "reply": ""})
        self.monkeypatch.setattr(llm, "generate_revised_design",
                                 generated(list(revised_outputs or [{"blocks": REVISED["design"]["blocks"]}])))
        self.monkeypatch.setattr(llm, "judge_revised_design", lambda *a, **k: dict(JUDGE_OK))


def outcome(response):
    return response["status"], response["hri_result"], (response["error"] or {}).get("code")


def review_initial(**kwargs):
    return main.review_design_candidate(INITIAL["design"], kind="initial", design_metadata=INITIAL["design_metadata"],
                                        **kwargs)


def intervene(**kwargs):
    return main.run_intervention(GIVEN["design"], GIVEN["current"], GIVEN["differences"], **kwargs)


def invalid_initial():
    block = OTHER_INITIAL["blocks"][0]
    return {"design_version": 1, "blocks": [block, dict(block)]}  # same stud twice -> overlap


def invalid_revised():
    return {"blocks": GIVEN["current"] + [dict(GIVEN["current"][0])]}  # Current kept, one block doubled -> overlap


def stop_after(n):
    """should_stop that turns True from the n-th check on."""
    seen = {"checks": 0}

    def should_stop():
        seen["checks"] += 1
        return seen["checks"] >= n
    return should_stop


# ---------------------------------------------------------------------------
# STT empty: silence ("") or device / STT failure (None)
# ---------------------------------------------------------------------------


def test_initial_silence_reasks_once_then_continues_as_any(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm()
    response = main.create_initial_design()
    assert outcome(response) == ("OK", None, None) and response["design"]["design_version"] == 1
    assert response["questions"] == [dialogue.build_greeting(), dialogue.SILENCE_REASK]
    assert len(h.listens) == 2 and all(k == {"mode": "free", "beep": True} for k in h.listens)


@pytest.mark.parametrize("api", ["initial", "review", "intervention"])
def test_listen_failure_is_voice_io_failed(monkeypatch, api):
    h = Harness(monkeypatch)
    h.working_llm()
    h.hear(None)
    response = {"initial": main.create_initial_design, "review": review_initial, "intervention": intervene}[api]()
    assert (response["status"], (response["error"] or {}).get("code")) == ("FAILED", "VOICE_IO_FAILED")
    assert response["design"] is None and len(h.listens) == 1 and h.generations == []


def test_review_silence_reasks_once_then_unclear(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm()
    response = review_initial()
    assert outcome(response) == ("OK", "UNCLEAR", None) and response["design"] == INITIAL["design"]
    assert response["questions"] == [dialogue.build_review_question("initial"), dialogue.build_review_reask()]
    assert len(h.listens) == 2 and h.generations == []


def test_intervention_silence_waits_until_stop(monkeypatch):
    """Day4 policy (§4.3): no time limit on silence; the call returns when the caller's should_stop turns True."""
    h = Harness(monkeypatch)
    h.working_llm()
    response = intervene(should_stop=stop_after(4))
    assert outcome(response) == ("CANCELLED", None, "STOPPED") and response["design"] is None
    assert len(h.listens) == 3 and h.generations == []


# ---------------------------------------------------------------------------
# LLM timeout (llm.py retries a timeout 3 times: 4 transport calls per LLM call)
# ---------------------------------------------------------------------------


def test_timeout_initial(monkeypatch):
    h = Harness(monkeypatch)
    h.fail_transport("timeout")
    response = main.create_initial_design(text="벤치처럼 길고 넓은 의자")
    assert outcome(response) == ("FAILED", None, "LLM_CALL_FAILED") and response["design"] is None
    assert len(h.transport) == 8  # request interpretation (fails -> "아무거나") + one generation, 4 tries each


def test_timeout_review_modify(monkeypatch):
    h = Harness(monkeypatch)
    h.fail_transport("timeout")
    response = review_initial(text_answers=["등받이를 더 높게"])
    assert outcome(response) == ("FAILED", "MODIFY", "LLM_CALL_FAILED") and response["design"] is None
    assert len(h.transport) == 8  # style_hint interpretation + one generation


def test_timeout_review_interpretation_gives_unclear(monkeypatch):
    h = Harness(monkeypatch)
    h.fail_transport("timeout")
    response = review_initial(text_answers=["음 글쎄 뭐랄까"])
    assert outcome(response) == ("OK", "UNCLEAR", None) and response["design"] == INITIAL["design"]
    assert len(h.transport) == 4 and len(response["questions"]) == 2  # reask once, then text answers ran out


def test_timeout_intervention_revise(monkeypatch):
    h = Harness(monkeypatch)
    h.fail_transport("timeout")
    response = intervene(text_answers=["일부러 옮겼어, 더 넓게 만들고 싶어"])
    assert outcome(response) == ("FAILED", "REVISE", "LLM_CALL_FAILED") and response["design"] is None
    assert len(h.transport) == 8  # provider failure is not an escalation case


# ---------------------------------------------------------------------------
# LLM invalid JSON: interpretation -> bad_response (fallback), generation -> malformed_output rejections
# ---------------------------------------------------------------------------


def test_invalid_json_initial(monkeypatch):
    h = Harness(monkeypatch)
    h.fail_transport("badjson")
    response = main.create_initial_design(text="벤치처럼 길고 넓은 의자")
    assert outcome(response) == ("FAILED", None, "DESIGN_GENERATION_FAILED") and response["design"] is None
    assert {r["rule"] for r in response["error"]["details"]} == {"malformed_output"}
    assert len(h.transport) == 1 + designer.MAX_ATTEMPTS


def test_invalid_json_review_modify(monkeypatch):
    h = Harness(monkeypatch)
    h.fail_transport("badjson")
    response = review_initial(text_answers=["등받이를 더 높게"])
    assert outcome(response) == ("FAILED", "MODIFY", "DESIGN_GENERATION_FAILED") and response["design"] is None
    assert len(h.transport) == 1 + designer.MAX_ATTEMPTS


def test_invalid_json_intervention_asks_escalation_then_fails_at_the_limit(monkeypatch):
    h = Harness(monkeypatch)
    h.fail_transport("badjson")
    response = intervene(text_answers=["일부러 옮겼어, 더 넓게 만들고 싶어", "계속 새 설계를 찾아 주세요"])
    assert outcome(response) == ("FAILED", "REVISE", "DESIGN_GENERATION_FAILED") and response["design"] is None
    assert response["questions"][1] == dialogue.escalation_question(GIVEN["differences"])
    assert len(h.transport) == 1 + designer.MAX_ATTEMPTS  # 6 + escalation "계속" + 4


def test_invalid_json_intervention_without_an_escalation_answer_is_unclear(monkeypatch):
    """Text mode: when the answers run out at the escalation question the caller gets OK / UNCLEAR with no design."""
    h = Harness(monkeypatch)
    h.fail_transport("badjson")
    response = intervene(text_answers=["일부러 옮겼어, 더 넓게 만들고 싶어"])
    assert outcome(response) == ("OK", "UNCLEAR", None) and response["design"] is None
    assert len(h.transport) == 1 + main.FIRST_ATTEMPTS


# ---------------------------------------------------------------------------
# validator failure: every generated candidate is invalid
# ---------------------------------------------------------------------------


def test_validator_failure_initial(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm(initial_outputs=[invalid_initial()])
    response = main.create_initial_design(text="벤치처럼 길고 넓은 의자")
    assert outcome(response) == ("FAILED", None, "DESIGN_GENERATION_FAILED") and response["design"] is None
    assert "overlap" in {r["rule"] for r in response["error"]["details"]}
    assert len(h.generations) == designer.MAX_ATTEMPTS


def test_validator_failure_review_modify(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm(initial_outputs=[invalid_initial()])
    response = review_initial(text_answers=["등받이를 더 높게"])
    assert outcome(response) == ("FAILED", "MODIFY", "DESIGN_GENERATION_FAILED") and response["design"] is None
    assert len(h.generations) == designer.MAX_ATTEMPTS


def test_validator_failure_intervention(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm(revised_outputs=[invalid_revised()])
    response = intervene(text_answers=["일부러 옮겼어, 더 넓게 만들고 싶어", "계속 새 설계를 찾아 주세요"])
    assert outcome(response) == ("FAILED", "REVISE", "DESIGN_GENERATION_FAILED") and response["design"] is None
    assert "overlap" in {r["rule"] for r in response["error"]["details"]}
    assert len(h.generations) == designer.MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# user CANCEL (Initial has no cancel utterance path: the caller stops it with should_stop)
# ---------------------------------------------------------------------------


def test_cancel_review(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm()
    response = review_initial(text_answers=["그만할래"])
    assert outcome(response) == ("CANCELLED", "CANCEL", "USER_CANCEL") and response["design"] == INITIAL["design"]
    assert response["design_metadata"]["review"]["decision"] == "CANCEL" and h.generations == []


def test_cancel_intervention(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm()
    response = intervene(text_answers=["취소할게요"])
    assert outcome(response) == ("CANCELLED", None, "USER_CANCEL") and response["design"] is None
    assert h.generations == []


def test_cancel_voice_review_closes_after_one_listen(monkeypatch):
    h = Harness(monkeypatch)
    h.working_llm()
    h.hear("그만할래")
    response = review_initial()
    assert outcome(response) == ("CANCELLED", "CANCEL", "USER_CANCEL") and len(h.listens) == 1
    assert h.speaks[0] == dialogue.build_review_question("initial")  # question, then the cancel ack


# ---------------------------------------------------------------------------
# should_stop: before the call, after the ack (before generation), between generation attempts
# ---------------------------------------------------------------------------


def call_api(api, **kwargs):
    if api == "initial":
        return main.create_initial_design(text="벤치처럼 길고 넓은 의자", **kwargs)
    if api == "review":
        return review_initial(text_answers=["등받이를 더 높게"], **kwargs)
    return intervene(text_answers=["일부러 옮겼어, 더 넓게 만들고 싶어"], **kwargs)


@pytest.mark.parametrize("api", ["initial", "review", "intervention"])
def test_stop_before_the_call(monkeypatch, api):
    h = Harness(monkeypatch)
    h.working_llm()
    response = call_api(api, should_stop=lambda: True)
    assert outcome(response) == ("CANCELLED", None, "STOPPED") and response["design"] is None
    assert h.generations == [] and h.listens == []


@pytest.mark.parametrize("api,ack", [("initial", "ACK"), ("review", "REVIEW_ACK"), ("intervention", "ACK")])
def test_stop_after_the_ack(monkeypatch, api, ack):
    h = Harness(monkeypatch)
    h.working_llm()
    stopped = {"now": False}

    def on_progress(event):
        if event["stage"] == ack:
            stopped["now"] = True
    response = call_api(api, should_stop=lambda: stopped["now"], on_progress=on_progress)
    assert outcome(response) == ("CANCELLED", None, "STOPPED") and response["design"] is None
    assert h.generations == []  # stopped before the first generation


@pytest.mark.parametrize("api", ["initial", "review", "intervention"])
def test_stop_between_generation_attempts(monkeypatch, api):
    h = Harness(monkeypatch)
    h.working_llm(initial_outputs=[invalid_initial()], revised_outputs=[invalid_revised()])
    response = call_api(api, should_stop=lambda: len(h.generations) >= 1)
    assert outcome(response) == ("CANCELLED", None, "STOPPED") and response["design"] is None
    assert len(h.generations) == 1
