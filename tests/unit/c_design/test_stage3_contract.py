"""Stage 3 Wave 3: C-side caller contract.

1. Fixture checks: tests/fixtures/c_stage3/*.json are real envelopes from the Wave 2 Sol smoke (Fable). They must keep
   the envelope / Design contract, the version policy, Current preservation and the review metadata keys, and must not
   contain secrets.
2. Invariants with a fake LLM (C_DESIGN_USE_LLM=1, text mode, no network, no audio): a caller (the D role) calls the C
   public API in sequence and passes each response's design / design_metadata to the next call. Candidate versions stay
   fixed, review.round counts candidate iterations, inputs are not mutated, and results do not depend on earlier calls.
"""

import copy
import json
import os
import re
from collections import Counter
from pathlib import Path

import pytest

from app.c_design import designer, dialogue, llm, main, validator, voice

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "c_stage3"
ENVELOPE_KEYS = {"status", "hri_result", "design", "design_metadata", "questions", "error"}
REVIEW_KEYS = {"kind", "decision", "style_hint", "scope", "concept", "round", "answers", "source", "reply"}
RESPONSES = ("initial_candidate_response", "review_modify_patch_response", "review_modify_redesign_response",
             "review_approve_response", "review_cancel_response", "intervention_revise_response",
             "review_revised_modify_patch_response")
SECRET_ENVS = ("OPENAI_LLM_API_KEY", "OPENAI_API_KEY", "OPENAI_TTS_API_KEY")


def load(name):
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)


def six(block):
    return tuple(block[field] for field in validator.BLOCK_FIELDS)


def preserves(design, current):
    """Current six-value multiset is contained in the design (§8.3)."""
    return not (Counter(map(six, current)) - Counter(map(six, design["blocks"])))


def assert_design_contract(design):
    assert set(design) == {"design_version", "blocks"}
    assert validator.validate_design(design) == []  # includes the stock combinations (invalid_combination)
    for block in design["blocks"]:
        assert set(block) == set(validator.BLOCK_FIELDS)
        assert block["brick_type"] in validator.ALLOWED_COMBINATIONS[block["color"]]


# ---------------------------------------------------------------------------
# 1. Fixture contract (real Wave 2 Sol smoke envelopes)
# ---------------------------------------------------------------------------


def test_all_fixtures_are_present():
    names = {path.stem for path in FIXTURES.glob("*.json")}
    assert names == set(RESPONSES) | {"intervention_revise_input"}


@pytest.mark.parametrize("name", RESPONSES)
def test_envelope_keys_and_design_contract(name):
    envelope = load(name)
    assert set(envelope) == ENVELOPE_KEYS
    assert isinstance(envelope["questions"], list)
    assert_design_contract(envelope["design"])
    assert isinstance(envelope["design_metadata"], dict)
    assert "review" not in envelope["design"] and "design_metadata" not in envelope["design"]


@pytest.mark.parametrize("name,version", [
    ("initial_candidate_response", 1), ("review_modify_patch_response", 1), ("review_modify_redesign_response", 1),
    ("review_approve_response", 1), ("review_cancel_response", 1),
    ("intervention_revise_response", 2), ("review_revised_modify_patch_response", 2),
])
def test_candidate_versions(name, version):
    """Initial candidates stay version 1; Revised candidates are Approved (v1) + 1 = 2, also after a review MODIFY."""
    assert load(name)["design"]["design_version"] == version


@pytest.mark.parametrize("name,status,hri,error_code", [
    ("initial_candidate_response", "OK", None, None),
    ("review_modify_patch_response", "OK", "MODIFY", None),
    ("review_modify_redesign_response", "OK", "MODIFY", None),
    ("review_approve_response", "OK", "APPROVE", None),
    ("review_cancel_response", "CANCELLED", "CANCEL", "USER_CANCEL"),
    ("intervention_revise_response", "OK", "REVISE", None),
    ("review_revised_modify_patch_response", "OK", "MODIFY", None),
])
def test_status_and_hri_result(name, status, hri, error_code):
    envelope = load(name)
    assert (envelope["status"], envelope["hri_result"]) == (status, hri)
    assert (envelope["error"] or {}).get("code") == error_code


def test_intervention_input_is_valid_and_revised_candidates_preserve_current():
    given = load("intervention_revise_input")
    assert set(given) == {"design", "current", "differences", "text_answers"}
    assert validator.check_intervention_input(given["design"], given["current"], given["differences"]) == []
    assert given["design"] == load("initial_candidate_response")["design"]  # the Approved v1 was the Initial candidate
    for name in ("intervention_revise_response", "review_revised_modify_patch_response"):
        design = load(name)["design"]
        assert validator.validate_revised({"blocks": design["blocks"]}, given["current"]) == []
        assert preserves(design, given["current"])
        assert len(design["blocks"]) >= designer.revised_min_blocks(given["design"])


@pytest.mark.parametrize("name", ["review_modify_patch_response", "review_modify_redesign_response",
                                  "review_approve_response", "review_cancel_response",
                                  "review_revised_modify_patch_response"])
def test_review_metadata_keys(name):
    review = load(name)["design_metadata"]["review"]
    assert set(review) == REVIEW_KEYS
    assert review["kind"] in ("initial", "revised")
    assert review["decision"] in ("APPROVE", "MODIFY", "UNCLEAR", "CANCEL")
    assert review["source"] in ("rule", "llm")
    assert review["scope"] in (None,) + llm.REVIEW_SCOPES
    assert isinstance(review["round"], int) and isinstance(review["answers"], int)


def test_modify_returns_a_new_candidate_and_approve_cancel_return_the_input_candidate():
    candidate = load("initial_candidate_response")["design"]
    for name, scope in (("review_modify_patch_response", "patch"), ("review_modify_redesign_response", "redesign")):
        envelope = load(name)
        assert envelope["design"] != candidate
        assert envelope["design_metadata"]["review"]["scope"] == scope
        assert envelope["design_metadata"]["review"]["round"] == 1
    for name in ("review_approve_response", "review_cancel_response"):
        envelope = load(name)
        assert envelope["design"] == candidate
        assert envelope["design_metadata"]["review"]["round"] == 0  # no regeneration: round kept
    revised = load("review_revised_modify_patch_response")
    assert revised["design"] != load("intervention_revise_response")["design"]
    assert revised["design_metadata"]["review"]["kind"] == "revised"


def test_review_metadata_keeps_the_candidate_metadata():
    """APPROVE / CANCEL add only 'review' to the candidate's metadata (§6.1)."""
    before = load("initial_candidate_response")["design_metadata"]
    for name in ("review_approve_response", "review_cancel_response"):
        after = dict(load(name)["design_metadata"])
        after.pop("review")
        assert after == before


def test_fixtures_contain_no_secrets():
    for path in FIXTURES.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sk-[A-Za-z0-9_-]{8,}", text), path.name
        assert "Bearer " not in text and "Authorization" not in text, path.name
        for env in SECRET_ENVS:
            value = os.environ.get(env, "").strip()
            if len(value) >= 8:
                assert value not in text, f"{path.name} contains the value of {env}"


# ---------------------------------------------------------------------------
# 2. Sequential caller invariants (fake LLM, text mode)
# ---------------------------------------------------------------------------

JUDGE_OK = {"recognizable_family": True, "silhouette_clarity": "clear", "reads_as_seating": True,
            "explanation_required_to_understand": False, "chair_likeness": "clear", "richer_than_previous": True,
            "design_name": "벤치", "design_family": "bench"}


class FakeLLM:
    """Records calls; generation returns the fixture designs in a fixed cycle so candidates differ call to call."""

    def __init__(self, monkeypatch):
        self.calls = []
        self.initial = [load(n)["design"] for n in ("initial_candidate_response", "review_modify_patch_response",
                                                    "review_modify_redesign_response")]
        self.revised = [load(n)["design"] for n in ("intervention_revise_response", "review_revised_modify_patch_response")]
        monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
        monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
        monkeypatch.setattr(voice, "speak", lambda *a, **k: pytest.fail("text mode must not speak"))
        monkeypatch.setattr(voice, "listen", lambda *a, **k: pytest.fail("text mode must not listen"))
        for name in ("interpret_initial_request", "generate_initial_design", "describe_initial_design",
                     "interpret_review_answer", "interpret_intervention_answer", "generate_revised_design",
                     "judge_revised_design"):
            monkeypatch.setattr(llm, name, self._recorder(name))
        monkeypatch.setattr(llm, "_post_json", lambda *a, **k: pytest.fail("no network in the caller tests"))

    def _recorder(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return getattr(self, name)(*args, **kwargs)
        return call

    def count(self, name):
        return sum(1 for call in self.calls if call[0] == name)

    def interpret_initial_request(self, text, should_stop=None):
        return {"object": "CHAIR", "preference": "SPECIFIC", "family": "daybed", "style_hint": "길게", "sufficient": True,
                "follow_up": "", "reply": "좋아요. 길게 누울 수 있는 의자로 만들어볼게요."}

    def generate_initial_design(self, object_type, reasons=None, should_stop=None, **kwargs):
        return copy.deepcopy(self.initial[(self.count("generate_initial_design") - 1) % len(self.initial)])

    def describe_initial_design(self, design, should_stop=None, family=None, concept=None):
        return {"design_name": "의자", "design_family": family or "chair", "design_summary": "의자",
                "visible_features": [], "silhouette_clarity": "clear", "recognizable_family": True,
                "completeness_score": 4, "family_design_match": "clear"}

    def interpret_review_answer(self, text, kind, should_stop=None, context=None):
        if "넓게" in text or "높게" in text:
            return {"decision": "MODIFY", "style_hint": text, "scope": "patch", "concept": "", "reason": "바꾸고 싶다고 하셨어요.",
                    "reply": "좋아요. 다시 만들어볼게요."}
        if "다른" in text:
            return {"decision": "MODIFY", "style_hint": "현재 디자인과 다른 형태", "scope": "redesign", "concept": "",
                    "reason": "다른 형태를 원하셨어요.", "reply": "좋아요. 새로 만들어볼게요."}
        return {"decision": "APPROVE", "style_hint": "", "scope": "", "concept": "", "reason": "마음에 드신대요.",
                "reply": "좋아요. 이 디자인으로 진행할게요."}

    def interpret_intervention_answer(self, text, differences, should_stop=None):
        return {"decision": "REVISE", "style_hint": "더 넓게", "reason": "일부러 옮기셨어요.", "reply": "알겠습니다. 더 넓게 다시 만들어볼게요."}

    def generate_revised_design(self, design, current, differences, reasons=None, should_stop=None, **kwargs):
        return {"blocks": copy.deepcopy(self.revised[(self.count("generate_revised_design") - 1) % len(self.revised)]["blocks"])}

    def judge_revised_design(self, previous, design, current, differences, should_stop=None):
        return dict(JUDGE_OK)


def review(response, kind, answer, **kwargs):
    """Caller step: Preview of response['design'] is assumed shown (fake PREVIEW_READY), then the review call."""
    return main.review_design_candidate(response["design"], kind=kind, design_metadata=response["design_metadata"],
                                        text_answers=[answer], **kwargs)


def test_initial_review_sequence_keeps_version_1_and_counts_rounds(monkeypatch):
    fake = FakeLLM(monkeypatch)
    initial = main.create_initial_design(text="데이베드처럼 길게 누울 수 있는 의자")
    assert initial["status"] == "OK" and initial["design"]["design_version"] == 1
    assert "review" not in initial["design_metadata"]

    first = review(initial, "initial", "등받이를 더 높게")
    second = review(first, "initial", "완전히 다른 모양으로 다시")
    approved = review(second, "initial", "좋아 이걸로 하자")

    rounds = [r["design_metadata"]["review"]["round"] for r in (first, second, approved)]
    assert rounds == [1, 2, 2]
    assert [r["hri_result"] for r in (first, second, approved)] == ["MODIFY", "MODIFY", "APPROVE"]
    assert [r["design"]["design_version"] for r in (initial, first, second, approved)] == [1, 1, 1, 1]
    assert initial["design"] != first["design"] != second["design"]
    assert approved["design"] == second["design"]  # APPROVE returns the reviewed candidate as is
    assert [r["design_metadata"]["review"]["scope"] for r in (first, second)] == ["patch", "redesign"]
    # previous_candidate / scope reach generation; APPROVE generates nothing
    generations = [call for call in fake.calls if call[0] == "generate_initial_design"]
    assert len(generations) == 3
    assert generations[1][2]["previous_candidate"] == initial["design"] and generations[1][2]["scope"] == "patch"
    assert generations[2][2]["previous_candidate"] == first["design"] and generations[2][2]["scope"] == "redesign"
    for response in (initial, first, second, approved):
        assert set(response) == ENVELOPE_KEYS
        assert_design_contract(response["design"])


def test_revised_review_sequence_keeps_version_2_and_preserves_current(monkeypatch):
    fake = FakeLLM(monkeypatch)
    given = load("intervention_revise_input")
    approved_v1 = given["design"]
    revise = main.run_intervention(approved_v1, given["current"], given["differences"], text_answers=given["text_answers"])
    assert (revise["status"], revise["hri_result"]) == ("OK", "REVISE")

    extra = {"previous_design": approved_v1, "current": given["current"], "differences": given["differences"]}
    first = review(revise, "revised", "조금 더 넓게", **extra)
    second = review(first, "revised", "등받이를 더 높게", **extra)
    done = review(second, "revised", "마음에 들어", **extra)

    responses = (revise, first, second, done)
    assert [r["design"]["design_version"] for r in responses] == [2, 2, 2, 2]
    assert [r["design_metadata"]["review"]["round"] for r in (first, second, done)] == [1, 2, 2]
    assert done["hri_result"] == "APPROVE" and done["design"] == second["design"]
    for response in responses:
        assert validator.validate_revised({"blocks": response["design"]["blocks"]}, given["current"]) == []
        assert preserves(response["design"], given["current"])
    revised_calls = [call for call in fake.calls if call[0] == "generate_revised_design"]
    assert len(revised_calls) == 3  # REVISE + two MODIFY; APPROVE generates nothing
    assert revised_calls[1][1][0] == approved_v1  # Revised candidates are built from the Approved Design
    assert revised_calls[1][2]["previous_candidate"] == revise["design"]
    assert fake.count("judge_revised_design") == 3


def test_inputs_are_not_mutated(monkeypatch):
    FakeLLM(monkeypatch)
    initial = load("initial_candidate_response")
    candidate, metadata = copy.deepcopy(initial["design"]), copy.deepcopy(initial["design_metadata"])
    for answer in ("등받이를 더 높게", "좋아 이걸로 하자", "그만할래"):
        response = main.review_design_candidate(candidate, kind="initial", design_metadata=metadata, text_answers=[answer])
        assert candidate == initial["design"] and metadata == initial["design_metadata"]
        assert response["design"] is not candidate and response["design_metadata"] is not metadata
    given = load("intervention_revise_input")
    frozen = copy.deepcopy(given)
    main.run_intervention(given["design"], given["current"], given["differences"], text_answers=given["text_answers"])
    assert given == frozen


def _stable(response):
    """Contract fields of a response; review.reply is excluded (ack wording varies on purpose, dialogue._pick)."""
    review_ = dict(response["design_metadata"]["review"])
    review_.pop("reply")
    return response["status"], response["hri_result"], response["design"], review_


def test_same_input_gives_the_same_result_regardless_of_earlier_calls(monkeypatch):
    FakeLLM(monkeypatch)
    initial = load("initial_candidate_response")
    alone = review(initial, "initial", "좋아 이걸로 하자")
    # unrelated calls in between: a MODIFY on another candidate, an Intervention, a CANCEL
    review(load("review_modify_redesign_response"), "initial", "등받이를 더 높게")
    given = load("intervention_revise_input")
    main.run_intervention(given["design"], given["current"], given["differences"], text_answers=given["text_answers"])
    review(initial, "initial", "그만할래")
    again = review(initial, "initial", "좋아 이걸로 하자")
    assert _stable(again) == _stable(alone)
    assert again["questions"] == alone["questions"] == ["완성된 디자인이 화면에 표시됐어요. 어떠신가요?"]


def test_main_keeps_no_module_level_lifecycle_state():
    """C keeps no request / candidate / version state between calls: main has no 'global' and no module-level containers.

    dialogue._last_pick (ack wording variety) and voice._last_* (diagnostics) are the only module-level state in C; they
    never feed Design, version, round or decision.
    """
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*global\s", source, re.M)
    assert not re.search(r"^[A-Za-z_]\w*\s*=\s*(\[\]|\{\}|dict\(\)|list\(\)|set\(\))\s*(#.*)?$", source, re.M)
    for name in ("request_id", "job_id", "revision"):
        assert name not in source, name
    assert set(vars(dialogue)) >= {"_last_pick"}
