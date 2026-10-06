"""Unit tests for app.c_design.voice (record / STT / TTS plumbing).

No real microphone, speaker or network call is ever made. tests/conftest.py already
installs an autouse guard that replaces voice._sounddevice and urllib.request.urlopen
with tripwires; every test here installs its own fake on top of that guard before
calling into voice.py. The API keys used (OPENAI_API_KEY for STT, OPENAI_TTS_API_KEY
for TTS) are obviously fake values, set via monkeypatch.setenv/delenv; they are never
printed and we assert they never leak into last_error() or any returned value.
"""

import importlib
import io
import json
import struct
import sys
import types
import wave

import pytest

import urllib.error
import urllib.request

from app.c_design import voice

try:
    import numpy as _np
except ImportError:  # pragma: no cover - numpy is expected to be installed
    _np = None

FAKE_KEY = "sk-test-FAKE0000000000000000"
FAKE_TTS_KEY = "sk-test-FAKETTS111111111111111"

BLOCKSIZE = int(voice.SAMPLE_RATE * voice.BLOCK_SECONDS)


# ---------------------------------------------------------------------------
# audio block helpers
# ---------------------------------------------------------------------------


def _int16_block(amplitude, n=BLOCKSIZE):
    """A block shaped like what sounddevice.InputStream.read() returns for
    channels=1, dtype="int16": a (n, 1) int16 array."""
    if _np is not None:
        return _np.full((n, 1), amplitude, dtype=_np.int16)
    import array

    return array.array("h", [amplitude] * n)


def quiet_block(n=BLOCKSIZE):
    return _int16_block(0, n)


def loud_block(n=BLOCKSIZE, amplitude=3000):
    return _int16_block(amplitude, n)


def _raw_pcm(n=800, amplitude=1000):
    """Raw int16 PCM bytes (stdlib struct), the shape transcribe(pcm) accepts."""
    return struct.pack("<%dh" % n, *([amplitude] * n))


def _build_wav_bytes(sample_rate=16000, n_samples=160, amplitude=1000):
    """A real, small WAV file built with the stdlib wave module, used as the
    TTS provider's response body (response_format="wav")."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<%dh" % n_samples, *([amplitude] * n_samples)))
    return buf.getvalue()


def _http_error(code, msg="error"):
    return urllib.error.HTTPError("https://example.invalid/", code, msg, None, None)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeStream:
    """Stands in for sounddevice.InputStream. Scripted blocks are returned in
    order; once exhausted it keeps repeating the last block instead of raising,
    so an off-by-one in an internal block-count constant doesn't explode a test
    with an unrelated error."""

    def __init__(self, blocks, overflowed=False):
        self.blocks = list(blocks)
        self._last = self.blocks[-1] if self.blocks else quiet_block()
        self._overflowed = overflowed
        self.reads = 0
        self.closed = False
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False

    def read(self, n):
        self.reads += 1
        if self.blocks:
            data = self.blocks.pop(0)
        else:
            data = self._last
        return data, self._overflowed


class FakeSD:
    """Stands in for the sounddevice module (the object voice._sounddevice()
    returns)."""

    def __init__(self, events=None, blocks=None, overflowed=False, open_error=None):
        self.events = events if events is not None else []
        self._blocks = blocks if blocks is not None else [quiet_block() for _ in range(300)]
        self._overflowed = overflowed
        self._open_error = open_error
        self.streams = []
        self.play_calls = []
        self.wait_calls = 0

    def InputStream(self, **kwargs):
        self.events.append(("open_stream", dict(kwargs)))
        if self._open_error is not None:
            raise self._open_error
        stream = FakeStream(self._blocks, overflowed=self._overflowed)
        self.streams.append(stream)
        return stream

    def play(self, frames, samplerate):
        self.events.append(("play", frames, samplerate))
        self.play_calls.append((frames, samplerate))

    def wait(self):
        self.events.append(("wait",))
        self.wait_calls += 1


class FakeResponse:
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
    outcomes in order. Each outcome is either bytes (a successful response
    body) or an Exception instance (raised)."""

    def __init__(self, outcomes, events=None):
        self.outcomes = list(outcomes)
        self.calls = []
        self.events = events if events is not None else []

    def __call__(self, request, timeout=None):
        self.calls.append({"request": request, "timeout": timeout})
        self.events.append(("urlopen", request.get_full_url()))
        if not self.outcomes:
            raise AssertionError("FakeUrlopen called more times than scripted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    @property
    def call_count(self):
        return len(self.calls)


def _install_sd(monkeypatch, events=None, blocks=None, overflowed=False, open_error=None):
    fake = FakeSD(events=events, blocks=blocks, overflowed=overflowed, open_error=open_error)
    monkeypatch.setattr(voice, "_sounddevice", lambda: fake, raising=False)
    return fake


def _install_urlopen(monkeypatch, outcomes, events=None):
    fake = FakeUrlopen(outcomes, events=events)
    monkeypatch.setattr(voice.urllib.request, "urlopen", fake)
    return fake


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    """Never actually sleep between API retries in tests."""
    monkeypatch.setattr(voice, "RETRY_BACKOFF", (0, 0, 0), raising=False)


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """By default, no-op any time.sleep() call (e.g. the post-speak delay) so
    tests run fast. Tests that care about the sleep value/order override this
    with sleep_log below."""
    if hasattr(voice, "time"):
        monkeypatch.setattr(voice.time, "sleep", lambda seconds: None, raising=False)


@pytest.fixture(autouse=True)
def real_numpy(monkeypatch):
    """RMS needs numpy; use the genuinely-installed one rather than relying on
    voice.py's own lazy import path."""
    if _np is not None:
        monkeypatch.setattr(voice, "_numpy", lambda: _np, raising=False)


@pytest.fixture
def sleep_log(monkeypatch):
    log = []

    def _fake_sleep(seconds):
        log.append(seconds)

    monkeypatch.setattr(voice.time, "sleep", _fake_sleep)
    return log


@pytest.fixture
def with_fake_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("OPENAI_TTS_API_KEY", FAKE_TTS_KEY)
    return FAKE_KEY


# ---------------------------------------------------------------------------
# 1. import side effects
# ---------------------------------------------------------------------------


class TestImportSideEffectFree:
    def test_reload_does_not_touch_device_or_network(self, monkeypatch):
        calls = {"urlopen": 0, "sounddevice": 0}

        def _tripwire_urlopen(*a, **k):
            calls["urlopen"] += 1
            raise AssertionError("urlopen touched at import time")

        monkeypatch.setattr(urllib.request, "urlopen", _tripwire_urlopen)

        fake_sd_module = types.ModuleType("sounddevice")

        def _tripwire_input_stream(**k):
            calls["sounddevice"] += 1
            raise AssertionError("sounddevice touched at import time")

        fake_sd_module.InputStream = _tripwire_input_stream
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd_module)

        importlib.reload(voice)

        assert calls == {"urlopen": 0, "sounddevice": 0}


# ---------------------------------------------------------------------------
# 2. listen(): silence / speech / failure paths
# ---------------------------------------------------------------------------


class TestListen:
    def test_silence_returns_empty_string_without_stt_call(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=[quiet_block() for _ in range(150)])
        fake_url = _install_urlopen(monkeypatch, [])

        result = voice.listen()

        assert result == ""
        assert fake_url.call_count == 0

    def test_speech_then_silence_returns_stripped_stt_text(self, monkeypatch, with_fake_key):
        blocks = [loud_block()] * 5 + [quiet_block()] * 20
        _install_sd(monkeypatch, blocks=blocks)
        fake_url = _install_urlopen(
            monkeypatch, [json.dumps({"text": "  안녕하세요  "}).encode("utf-8")]
        )

        result = voice.listen()

        assert result == "안녕하세요"
        assert fake_url.call_count == 1

    def test_stt_provider_failure_returns_none(self, monkeypatch, with_fake_key):
        blocks = [loud_block()] * 5 + [quiet_block()] * 20
        _install_sd(monkeypatch, blocks=blocks)
        _install_urlopen(monkeypatch, [_http_error(500)] * 4)

        assert voice.listen() is None

    def test_missing_key_returns_none_without_request(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        blocks = [loud_block()] * 5 + [quiet_block()] * 20
        _install_sd(monkeypatch, blocks=blocks)
        fake_url = _install_urlopen(monkeypatch, [])

        result = voice.listen()

        assert result is None
        assert voice.last_error().startswith("missing_key")
        assert fake_url.call_count == 0

    def test_device_open_failure_returns_none(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, open_error=OSError("no such device"))

        result = voice.listen()

        assert result is None
        assert voice.last_error().startswith("audio_device")


# ---------------------------------------------------------------------------
# 3. record(): block-count behavior at the timing boundaries
# ---------------------------------------------------------------------------


class TestRecordTiming:
    def test_pure_silence_times_out_to_empty_bytes(self, monkeypatch, with_fake_key):
        blocks = [quiet_block() for _ in range(200)]
        fake_sd = _install_sd(monkeypatch, blocks=blocks)

        result = voice.record()

        assert result == b""
        stream = fake_sd.streams[0]
        expected = round(voice.WAIT_SECONDS / voice.BLOCK_SECONDS)  # nominally 80
        assert stream.reads == expected  # block counts are exact, not wall clock
        assert stream.reads < len(blocks)  # stopped itself, didn't drain the script

    def test_stops_on_trailing_silence(self, monkeypatch, with_fake_key):
        blocks = [loud_block()] + [quiet_block() for _ in range(40)]
        fake_sd = _install_sd(monkeypatch, blocks=blocks)

        result = voice.record()

        assert result not in (None, b"")
        stream = fake_sd.streams[0]
        expected_trailing = round(voice.TRAILING_SILENCE_SECONDS / voice.BLOCK_SECONDS)  # 10
        assert stream.reads == 1 + expected_trailing
        assert stream.reads < len(blocks)

    def test_stops_on_max_utterance(self, monkeypatch, with_fake_key):
        blocks = [loud_block() for _ in range(250)]
        fake_sd = _install_sd(monkeypatch, blocks=blocks)

        result = voice.record()

        assert result not in (None, b"")
        stream = fake_sd.streams[0]
        expected_max = round(voice.MAX_UTTERANCE_SECONDS / voice.BLOCK_SECONDS)  # 100
        assert stream.reads == expected_max
        assert len(result) == expected_max * int(voice.SAMPLE_RATE * voice.BLOCK_SECONDS) * 2  # int16
        assert stream.reads < len(blocks)


# ---------------------------------------------------------------------------
# 4. transcribe(): request shape, retries, env overrides, temp files
# ---------------------------------------------------------------------------


class TestTranscribeRequestShape:
    def test_multipart_fields_and_headers(self, monkeypatch, with_fake_key):
        fake_url = _install_urlopen(monkeypatch, [json.dumps({"text": "hello"}).encode("utf-8")])

        result = voice.transcribe(_raw_pcm())

        assert result == "hello"
        assert fake_url.call_count == 1
        request = fake_url.calls[0]["request"]
        body = request.data

        assert b'name="model"' in body
        assert b"whisper-1" in body
        assert b'name="language"' in body
        assert b"ko" in body
        assert b'name="file"; filename="speech.wav"' in body
        assert b"RIFF" in body
        assert request.get_header("Authorization") == "Bearer " + FAKE_KEY
        assert request.get_full_url() == voice.STT_URL
        assert fake_url.calls[0]["timeout"] == voice.TIMEOUT_SECONDS

    def test_missing_key_no_request(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        fake_url = _install_urlopen(monkeypatch, [])

        result = voice.transcribe(_raw_pcm())

        assert result is None
        assert voice.last_error().startswith("missing_key")
        assert fake_url.call_count == 0


class TestEnvOverrides:
    def test_stt_model_env_override(self, monkeypatch, with_fake_key):
        monkeypatch.setenv("OPENAI_STT_MODEL", "whisper-test")
        fake_url = _install_urlopen(monkeypatch, [json.dumps({"text": "hi"}).encode("utf-8")])

        voice.transcribe(_raw_pcm())

        body = fake_url.calls[0]["request"].data
        assert b"whisper-test" in body

    def test_tts_model_and_voice_env_override(self, monkeypatch, with_fake_key):
        monkeypatch.setenv("OPENAI_TTS_MODEL", "tts-test")
        monkeypatch.setenv("OPENAI_TTS_VOICE", "nova")
        _install_sd(monkeypatch)
        fake_url = _install_urlopen(monkeypatch, [_build_wav_bytes()])

        voice.speak("hello there")

        payload = json.loads(fake_url.calls[0]["request"].data)
        assert payload["model"] == "tts-test"
        assert payload["voice"] == "nova"


class TestTranscribeRetries:
    def test_401_no_retry(self, monkeypatch, with_fake_key):
        fake = _install_urlopen(monkeypatch, [_http_error(401)])
        assert voice.transcribe(_raw_pcm()) is None
        assert fake.call_count == 1

    def test_403_no_retry(self, monkeypatch, with_fake_key):
        fake = _install_urlopen(monkeypatch, [_http_error(403)])
        assert voice.transcribe(_raw_pcm()) is None
        assert fake.call_count == 1

    def test_429_then_success(self, monkeypatch, with_fake_key):
        fake = _install_urlopen(
            monkeypatch, [_http_error(429), json.dumps({"text": "ok"}).encode("utf-8")]
        )
        assert voice.transcribe(_raw_pcm()) == "ok"
        assert fake.call_count == 2

    def test_500_always_four_calls(self, monkeypatch, with_fake_key):
        fake = _install_urlopen(monkeypatch, [_http_error(500)] * 4)
        assert voice.transcribe(_raw_pcm()) is None
        assert fake.call_count == 4


class TestNoTempFiles:
    def test_transcribe_does_not_use_temp_files(self, monkeypatch, with_fake_key):
        import tempfile

        def _boom(*a, **k):
            raise AssertionError("a temp file was used")

        monkeypatch.setattr(tempfile, "NamedTemporaryFile", _boom)
        monkeypatch.setattr(tempfile, "mkstemp", _boom)

        _install_urlopen(monkeypatch, [json.dumps({"text": "ok"}).encode("utf-8")])

        assert voice.transcribe(_raw_pcm()) == "ok"


# ---------------------------------------------------------------------------
# 5. speak(): payload, ordering, failure tolerance
# ---------------------------------------------------------------------------


class TestSpeakPayload:
    def test_default_model_voice_and_request_shape(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch)
        fake_url = _install_urlopen(monkeypatch, [_build_wav_bytes()])

        voice.speak("hello")

        payload = json.loads(fake_url.calls[0]["request"].data)
        assert payload["model"] == voice.DEFAULT_TTS_MODEL
        assert payload["voice"] == voice.DEFAULT_TTS_VOICE
        assert payload["input"] == "hello"
        assert payload["response_format"] == "wav"
        request = fake_url.calls[0]["request"]
        assert request.get_header("Authorization") == "Bearer " + FAKE_TTS_KEY
        assert request.get_full_url() == voice.TTS_URL


class TestSpeakOrdering:
    def test_event_order_tts_play_wait_sleep_and_no_input_stream(
        self, monkeypatch, with_fake_key, sleep_log
    ):
        events = []
        fake_sd = _install_sd(monkeypatch, events=events)
        _install_urlopen(monkeypatch, [_build_wav_bytes()], events=events)

        voice.speak("안녕")

        kinds = [e[0] for e in events]
        assert kinds.index("urlopen") < kinds.index("play") < kinds.index("wait")
        assert sleep_log == [voice.POST_SPEAK_DELAY]
        assert len(fake_sd.streams) == 0
        assert all(k != "open_stream" for k in kinds)

    def test_speak_then_listen_playback_completes_before_recording_starts(
        self, monkeypatch, with_fake_key, sleep_log
    ):
        events = []
        blocks = [quiet_block() for _ in range(120)]
        _install_sd(monkeypatch, events=events, blocks=blocks)
        _install_urlopen(monkeypatch, [_build_wav_bytes()], events=events)

        voice.speak("질문입니다")
        voice.listen()

        kinds = [e[0] for e in events]
        play_idx = kinds.index("play")
        wait_idx = kinds.index("wait")
        open_idx = kinds.index("open_stream")
        assert play_idx < wait_idx < open_idx
        assert sleep_log == [voice.POST_SPEAK_DELAY]


class TestSpeakNeverRaises:
    def test_speak_403_does_not_raise(self, monkeypatch, with_fake_key):
        fake_sd = _install_sd(monkeypatch)
        _install_urlopen(monkeypatch, [_http_error(403)])

        voice.speak("hello")  # must not raise

        assert voice.last_error() is not None
        assert len(fake_sd.play_calls) == 0

    def test_speak_incomplete_read_is_retried_as_network_and_does_not_raise(self, monkeypatch, with_fake_key):
        import http.client

        fake_sd = _install_sd(monkeypatch)
        fake_url = _install_urlopen(monkeypatch, [http.client.IncompleteRead(b"")] * 4)

        voice.speak("hello")  # must not raise

        assert fake_url.call_count == 4
        assert voice.last_error().startswith("network")
        assert len(fake_sd.play_calls) == 0

    def test_speak_missing_key_does_not_raise(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_TTS_API_KEY", raising=False)
        fake_sd = _install_sd(monkeypatch)
        fake_url = _install_urlopen(monkeypatch, [])

        voice.speak("hello")  # must not raise

        assert voice.last_error().startswith("missing_key")
        assert fake_url.call_count == 0
        assert len(fake_sd.play_calls) == 0

    def test_speak_server_error_does_not_raise(self, monkeypatch, with_fake_key):
        fake_sd = _install_sd(monkeypatch)
        _install_urlopen(monkeypatch, [_http_error(500)] * 4)

        voice.speak("hello")  # must not raise

        assert voice.last_error() is not None
        assert len(fake_sd.play_calls) == 0


class TestKeySeparation:
    """STT는 OPENAI_API_KEY, TTS는 OPENAI_TTS_API_KEY만 쓴다. 서로 대체하지 않는다(사용자 지시)."""

    def test_speak_uses_tts_key_not_stt_key(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch)
        fake_url = _install_urlopen(monkeypatch, [_build_wav_bytes()])

        voice.speak("hello")

        header = fake_url.calls[0]["request"].get_header("Authorization")
        assert header == "Bearer " + FAKE_TTS_KEY
        assert FAKE_KEY not in header

    def test_speak_without_tts_key_does_not_fall_back_to_stt_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
        monkeypatch.delenv("OPENAI_TTS_API_KEY", raising=False)
        fake_sd = _install_sd(monkeypatch)
        fake_url = _install_urlopen(monkeypatch, [])

        voice.speak("hello")  # must not raise

        assert fake_url.call_count == 0
        assert voice.last_error() == "missing_key: OPENAI_TTS_API_KEY is not set"
        assert len(fake_sd.play_calls) == 0

    def test_transcribe_uses_stt_key_not_tts_key(self, monkeypatch, with_fake_key):
        fake_url = _install_urlopen(monkeypatch, [json.dumps({"text": "ok"}).encode("utf-8")])

        assert voice.transcribe(_raw_pcm()) == "ok"

        header = fake_url.calls[0]["request"].get_header("Authorization")
        assert header == "Bearer " + FAKE_KEY
        assert FAKE_TTS_KEY not in header

    def test_transcribe_without_stt_key_does_not_fall_back_to_tts_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_TTS_API_KEY", FAKE_TTS_KEY)
        fake_url = _install_urlopen(monkeypatch, [])

        assert voice.transcribe(_raw_pcm()) is None
        assert fake_url.call_count == 0
        assert voice.last_error() == "missing_key: OPENAI_API_KEY is not set"


# ---------------------------------------------------------------------------
# 6. secret leakage
# ---------------------------------------------------------------------------


class TestSecretLeakage:
    def _assert_key_absent(self, result):
        for key in (FAKE_KEY, FAKE_TTS_KEY):
            assert key not in str(result)
            err = voice.last_error()
            assert err is None or key not in err

    def test_stt_success(self, monkeypatch, with_fake_key):
        _install_urlopen(monkeypatch, [json.dumps({"text": "ok"}).encode("utf-8")])
        result = voice.transcribe(_raw_pcm())
        self._assert_key_absent(result)

    def test_stt_auth_error(self, monkeypatch, with_fake_key):
        _install_urlopen(monkeypatch, [_http_error(401)])
        result = voice.transcribe(_raw_pcm())
        self._assert_key_absent(result)

    def test_stt_server_error(self, monkeypatch, with_fake_key):
        _install_urlopen(monkeypatch, [_http_error(500)] * 4)
        result = voice.transcribe(_raw_pcm())
        self._assert_key_absent(result)

    def test_speak_auth_error(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch)
        _install_urlopen(monkeypatch, [_http_error(403)])
        voice.speak("hello")
        self._assert_key_absent(None)
