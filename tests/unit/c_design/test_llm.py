"""Unit tests for app.c_design.llm (LLM provider call: payload shape, prompt
content, response parsing, error classification/retry, secret handling).

llm.py is being implemented in parallel; if it is still incomplete these tests fail
with clear AttributeErrors/ImportErrors rather than silently passing.

No real network call is ever made: urllib.request.urlopen is monkeypatched with a
fake that records the outgoing Request and returns/raises canned outcomes. The API
key used is an obviously fake value, set via monkeypatch.setenv/delenv; it is never
printed and we assert it never leaks into any returned value or logged text.
"""

import json

import pytest

import urllib.error
import urllib.request

from app.c_design import llm, validator

FAKE_KEY = "sk-test-FAKE0000000000000000"


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeResponse:
    """Stands in for the object returned by urllib.request.urlopen(...)."""

    def __init__(self, body_bytes):
        self._body = body_bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class FakeUrlopen:
    """Records every Request it receives and plays back a scripted list of
    outcomes in order. Each outcome is either:
      - bytes: returned as a successful response body
      - an Exception instance: raised
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append({"request": request, "timeout": timeout})
        if not self.outcomes:
            raise AssertionError("FakeUrlopen called more times than scripted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    @property
    def call_count(self):
        return len(self.calls)


def _body(content_str):
    """A successful chat-completion response body carrying content_str."""
    return json.dumps({"choices": [{"message": {"content": content_str}}]}).encode("utf-8")


def _malformed_body():
    """A 200 response with no choices/message/content."""
    return json.dumps({"unexpected": "shape"}).encode("utf-8")


def _http_error(code, msg="error"):
    return urllib.error.HTTPError("https://api.openai.com/v1/chat/completions", code, msg, None, None)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    """Never actually sleep between retries in tests."""
    monkeypatch.setattr(llm, "RETRY_BACKOFF", (0, 0, 0))


@pytest.fixture
def with_fake_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    return FAKE_KEY


def _install(monkeypatch, outcomes):
    fake = FakeUrlopen(outcomes)
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    return fake


SIMPLE_DESIGN = {
    "design_version": 1,
    "blocks": [
        {"brick_type": "2x2x1", "color": "yellow", "x": 0, "y": 0, "layer": 1, "orientation_deg": 0},
    ],
}


# ---------------------------------------------------------------------------
# 1. initial payload shape
# ---------------------------------------------------------------------------


class TestInitialPayload:
    def test_payload_fields_and_request(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_body(json.dumps({"design_version": 1, "blocks": []}))])

        llm.generate_initial_design("CHAIR")

        assert fake.call_count == 1
        request = fake.calls[0]["request"]
        payload = json.loads(request.data)

        assert payload["model"] == llm.DEFAULT_MODEL
        assert payload["temperature"] == 0
        assert payload["response_format"] == {"type": "json_object"}
        assert "max_tokens" in payload
        assert len(payload["messages"]) == 2
        roles = [m["role"] for m in payload["messages"]]
        assert "system" in roles
        assert "user" in roles

        assert request.get_header("Authorization") == "Bearer " + FAKE_KEY
        assert request.get_full_url() == llm.API_URL
        assert fake.calls[0]["timeout"] == llm.TIMEOUT_SECONDS

    def test_model_env_override(self, monkeypatch, with_fake_key):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-test-override")
        fake = _install(monkeypatch, [_body(json.dumps({"design_version": 1, "blocks": []}))])

        llm.generate_initial_design("CHAIR")

        payload = json.loads(fake.calls[0]["request"].data)
        assert payload["model"] == "gpt-test-override"


# ---------------------------------------------------------------------------
# 2. system prompt content
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_forbids_robot_output(self):
        lowered = llm.SYSTEM_PROMPT.lower()
        for forbidden in ("robot", "ros2", "plan", "slot"):
            assert forbidden in lowered

    def test_states_rule_values(self):
        for value in ("2x2x1", "2x3x1", "yellow", "blue", "24"):
            assert value in llm.SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 3. initial user message content
# ---------------------------------------------------------------------------


class TestInitialUserMessage:
    def _user_content(self, fake):
        payload = json.loads(fake.calls[0]["request"].data)
        return next(m["content"] for m in payload["messages"] if m["role"] == "user")

    def test_contains_object_type_and_reasons(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_body(json.dumps({"design_version": 1, "blocks": []}))])

        reasons = [
            {"rule": "support", "blocks": [], "message": "block support studs=0 < 2"},
        ]
        llm.generate_initial_design("CHAIR", reasons=reasons)

        content = self._user_content(fake)
        assert "CHAIR" in content
        assert "support" in content

    def test_no_raw_user_speech(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_body(json.dumps({"design_version": 1, "blocks": []}))])

        llm.generate_initial_design("CHAIR")

        content = self._user_content(fake)
        assert "오늘은" not in content


# ---------------------------------------------------------------------------
# 4. revised user message content
# ---------------------------------------------------------------------------


class TestRevisedUserMessage:
    def test_contains_current_and_differences_and_preserve_note(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_body(json.dumps({"blocks": []}))])

        current = [
            {"brick_type": "2x2x1", "color": "yellow", "x": 5, "y": 5, "layer": 1, "orientation_deg": 0},
        ]
        differences = [
            {
                "expected": {"brick_type": "2x2x1", "color": "blue", "x": 1, "y": 1, "layer": 1, "orientation_deg": 0},
                "actual": None,
            }
        ]
        reasons = [{"rule": "overlap", "blocks": [], "message": "blocks overlap"}]

        llm.generate_revised_design(SIMPLE_DESIGN, current, differences, reasons=reasons)

        payload = json.loads(fake.calls[0]["request"].data)
        content = next(m["content"] for m in payload["messages"] if m["role"] == "user")

        assert "5" in content  # current block's x/y value present somewhere
        assert "blue" in content  # difference's expected color present
        assert "current" in content.lower()
        # some wording that tells the model to keep Current exactly as-is
        assert "exactly" in content.lower() or "preserve" in content.lower()


# ---------------------------------------------------------------------------
# 5. response parsing
# ---------------------------------------------------------------------------


class TestParsing:
    def test_plain_json(self, monkeypatch, with_fake_key):
        design = {"design_version": 1, "blocks": []}
        _install(monkeypatch, [_body(json.dumps(design))])
        result = llm.generate_initial_design("CHAIR")
        assert result == design

    def test_fenced_json(self, monkeypatch, with_fake_key):
        design = {"design_version": 1, "blocks": []}
        fenced = "```json\n" + json.dumps(design) + "\n```"
        _install(monkeypatch, [_body(fenced)])
        result = llm.generate_initial_design("CHAIR")
        assert result == design

    def test_whitespace_padded_json(self, monkeypatch, with_fake_key):
        design = {"design_version": 1, "blocks": []}
        padded = "\n\n   " + json.dumps(design) + "   \n\n"
        _install(monkeypatch, [_body(padded)])
        result = llm.generate_initial_design("CHAIR")
        assert result == design

    def test_non_json_text_returned_as_str(self, monkeypatch, with_fake_key):
        _install(monkeypatch, [_body("Sure, here it is")])
        result = llm.generate_initial_design("CHAIR")
        assert result == "Sure, here it is"

    def test_truncated_json_returned_as_str(self, monkeypatch, with_fake_key):
        truncated = '{"blocks": ['
        _install(monkeypatch, [_body(truncated)])
        result = llm.generate_initial_design("CHAIR")
        assert result == truncated


# ---------------------------------------------------------------------------
# 6. error classification / retry behavior
# ---------------------------------------------------------------------------


class TestErrors:
    def test_401_auth_no_retry(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(401)])
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "auth"
        assert fake.call_count == 1

    def test_403_auth(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(403)])
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "auth"
        assert fake.call_count == 1

    def test_429_then_success(self, monkeypatch, with_fake_key):
        design = {"design_version": 1, "blocks": []}
        fake = _install(monkeypatch, [_http_error(429), _body(json.dumps(design))])
        result = llm.generate_initial_design("CHAIR")
        assert result == design
        assert fake.call_count == 2

    def test_429_always_rate_limit(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(429)] * 4)
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "rate_limit"
        assert fake.call_count == 4

    def test_500_always_server(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(500)] * 4)
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "server"
        assert fake.call_count == 4

    def test_urlerror_always_network(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [urllib.error.URLError("boom")] * 4)
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "network"
        assert fake.call_count == 4

    def test_timeout_always_timeout(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [TimeoutError()] * 4)
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "timeout"
        assert fake.call_count == 4

    def test_400_bad_response_no_retry(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(400)])
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "bad_response"
        assert fake.call_count == 1

    def test_body_without_choices_bad_response(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_malformed_body()])
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "bad_response"
        assert fake.call_count == 1

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        fake = _install(monkeypatch, [])
        result = llm.generate_initial_design("CHAIR")
        assert result["llm_error"]["kind"] == "missing_key"
        assert fake.call_count == 0


# ---------------------------------------------------------------------------
# 7. should_stop cooperative cancellation
# ---------------------------------------------------------------------------


class TestShouldStop:
    def test_stopped_before_retry(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(500)] * 4)
        result = llm.generate_initial_design("CHAIR", should_stop=lambda: True)
        assert result["llm_error"]["kind"] == "stopped"
        assert fake.call_count == 1


# ---------------------------------------------------------------------------
# 8. secret leakage
# ---------------------------------------------------------------------------


class TestSecretLeakage:
    def _assert_key_absent(self, value, fake):
        assert FAKE_KEY not in json.dumps(value)
        assert FAKE_KEY not in llm.SYSTEM_PROMPT
        for call in fake.calls:
            payload = json.loads(call["request"].data)
            for message in payload["messages"]:
                assert FAKE_KEY not in message["content"]

    def test_success(self, monkeypatch, with_fake_key):
        design = {"design_version": 1, "blocks": []}
        fake = _install(monkeypatch, [_body(json.dumps(design))])
        result = llm.generate_initial_design("CHAIR")
        self._assert_key_absent(result, fake)

    def test_auth_error(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(401)])
        result = llm.generate_initial_design("CHAIR")
        self._assert_key_absent(result, fake)

    def test_server_error(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_http_error(500)] * 4)
        result = llm.generate_initial_design("CHAIR")
        self._assert_key_absent(result, fake)

    def test_malformed_body(self, monkeypatch, with_fake_key):
        fake = _install(monkeypatch, [_malformed_body()])
        result = llm.generate_initial_design("CHAIR")
        self._assert_key_absent(result, fake)


# ---------------------------------------------------------------------------
# 9. forbidden keys are not special-cased by llm.py; validator rejects them
# ---------------------------------------------------------------------------


class TestForbiddenKeysLeftToValidator:
    def test_unknown_block_key_passed_through_and_rejected_by_validator(self, monkeypatch, with_fake_key):
        design = {
            "design_version": 1,
            "blocks": [
                {
                    "brick_type": "2x2x1",
                    "color": "yellow",
                    "x": 0,
                    "y": 0,
                    "layer": 1,
                    "orientation_deg": 0,
                    "robot_x": 123,
                }
            ],
        }
        _install(monkeypatch, [_body(json.dumps(design))])
        result = llm.generate_initial_design("CHAIR")

        assert result == design

        reasons = validator.validate_design(result)
        assert any(r["rule"] == "unknown_key" for r in reasons)

    def test_top_level_plan_key_rejected_by_validator(self, monkeypatch, with_fake_key):
        design = {
            "design_version": 1,
            "blocks": [],
            "plan": ["step1"],
        }
        _install(monkeypatch, [_body(json.dumps(design))])
        result = llm.generate_initial_design("CHAIR")

        assert result == design

        reasons = validator.validate_design(result)
        assert any(r["rule"] == "unknown_key" for r in reasons)
