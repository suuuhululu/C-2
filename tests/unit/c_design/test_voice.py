"""Unit tests for app.c_design.voice (record / STT / TTS plumbing).

No real microphone, speaker or network call is ever made. tests/conftest.py already
installs an autouse guard that replaces voice._sounddevice and urllib.request.urlopen
with tripwires; every test here installs its own fake on top of that guard before
calling into voice.py. The API keys used (OPENAI_API_KEY for STT, OPENAI_TTS_API_KEY
for TTS) are obviously fake values, set via monkeypatch.setenv/delenv; they are never
printed and we assert they never leak into last_error() or any returned value.
"""

import importlib
import email.message
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


WARMUP_BLOCKS = round(voice.WARMUP_SECONDS / voice.BLOCK_SECONDS)  # 2 discarded blocks right after open
CAL_BLOCKS = round(voice.NOISE_CALIBRATION_SECONDS / voice.BLOCK_SECONDS)  # 5 blocks of noise calibration
PREFIX_BLOCKS = WARMUP_BLOCKS + CAL_BLOCKS  # 7


def calibration(amplitude=0, warmup_amplitude=0):
    """The first blocks record() reads: warm-up (discarded) then the noise-floor calibration window."""
    return [_int16_block(warmup_amplitude) for _ in range(WARMUP_BLOCKS)] + [
        _int16_block(amplitude) for _ in range(CAL_BLOCKS)]


def _block_levels(pcm):
    """First sample of every block in a PCM byte string (blocks here are constant-amplitude)."""
    samples = _np.frombuffer(pcm, dtype="<i2")
    return [int(samples[i]) for i in range(0, len(samples), BLOCKSIZE)]


def _stt_body(text, no_speech_prob=0.1, segments=None):
    """A whisper verbose_json response body."""
    if segments is None:
        segments = [{"id": 0, "text": text, "no_speech_prob": no_speech_prob}]
    return json.dumps({"text": text, "language": "korean", "duration": 2.0, "segments": segments}).encode("utf-8")


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


@pytest.fixture(autouse=True)
def no_debug_dump(monkeypatch):
    """C_VOICE_DEBUG_DIR must never leak into tests from the developer's shell."""
    monkeypatch.delenv(voice.DEBUG_DIR_ENV, raising=False)


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
        blocks = calibration() + [loud_block()] * 5 + [quiet_block()] * 20
        _install_sd(monkeypatch, blocks=blocks)
        fake_url = _install_urlopen(
            monkeypatch, [_stt_body("  안녕하세요  ")]
        )

        result = voice.listen()

        assert result == "안녕하세요"
        assert fake_url.call_count == 1

    def test_stt_provider_failure_returns_none(self, monkeypatch, with_fake_key):
        blocks = calibration() + [loud_block()] * 5 + [quiet_block()] * 20
        _install_sd(monkeypatch, blocks=blocks)
        _install_urlopen(monkeypatch, [_http_error(500)] * 4)

        assert voice.listen() is None

    def test_missing_key_returns_none_without_request(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        blocks = calibration() + [loud_block()] * 5 + [quiet_block()] * 20
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
        expected = PREFIX_BLOCKS + round(voice.WAIT_SECONDS / voice.BLOCK_SECONDS)  # 2 + 5 + 80
        assert stream.reads == expected == 87  # block counts are exact, not wall clock
        assert stream.reads < len(blocks)  # stopped itself, didn't drain the script

    def test_stops_on_trailing_silence(self, monkeypatch, with_fake_key):
        blocks = calibration() + [loud_block()] * 5 + [quiet_block() for _ in range(40)]
        fake_sd = _install_sd(monkeypatch, blocks=blocks)

        result = voice.record()

        assert result not in (None, b"")
        stream = fake_sd.streams[0]
        expected_trailing = round(voice.TRAILING_SILENCE_SECONDS / voice.BLOCK_SECONDS)  # 10
        assert stream.reads == PREFIX_BLOCKS + 5 + expected_trailing == 22
        assert stream.reads < len(blocks)
        # trimmed: 5 voiced blocks + TRIM_MARGIN (2 blocks) of the trailing silence, no pre-roll (speech came first)
        assert _block_levels(result) == [3000] * 5 + [0, 0]

    def test_stops_on_max_utterance(self, monkeypatch, with_fake_key):
        blocks = calibration() + [loud_block() for _ in range(250)]
        fake_sd = _install_sd(monkeypatch, blocks=blocks)

        result = voice.record()

        assert result not in (None, b"")
        stream = fake_sd.streams[0]
        expected_max = round(voice.MAX_UTTERANCE_SECONDS / voice.BLOCK_SECONDS)  # 100, counted from speech start
        assert stream.reads == PREFIX_BLOCKS + expected_max == 107
        assert len(result) == expected_max * int(voice.SAMPLE_RATE * voice.BLOCK_SECONDS) * 2  # int16
        assert stream.reads < len(blocks)


class TestAdaptiveGate:
    def test_threshold_is_max_of_floor_and_minimum(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=calibration(800) + [_int16_block(800)] * 100)
        voice.record()
        assert voice._last_capture["noise_floor"] == 800
        assert voice._last_capture["threshold"] == 800 * voice.NOISE_MULTIPLIER == 2400
        _install_sd(monkeypatch, blocks=calibration(50) + [quiet_block()] * 100)
        voice.record()
        assert voice._last_capture["threshold"] == voice.RMS_THRESHOLD_MIN == 600

    def test_constant_room_noise_is_silence_without_stt(self, monkeypatch, with_fake_key):
        fake_sd = _install_sd(monkeypatch, blocks=calibration(800) + [_int16_block(800)] * 200)
        fake_url = _install_urlopen(monkeypatch, [])
        assert voice.listen() == ""
        assert fake_url.call_count == 0
        assert fake_sd.streams[0].reads == PREFIX_BLOCKS + round(voice.WAIT_SECONDS / voice.BLOCK_SECONDS)

    def test_louder_noise_below_adaptive_threshold_is_not_speech(self, monkeypatch, with_fake_key):
        # RMS 1500 would have passed the old fixed threshold (500); with floor 800 the threshold is 2400.
        _install_sd(monkeypatch, blocks=calibration(800) + [_int16_block(1500)] * 200)
        assert voice.record() == b""

    def test_speech_above_adaptive_threshold_is_captured(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=calibration(800) + [loud_block()] * 5 + [_int16_block(800)] * 20)
        result = voice.record()
        assert _block_levels(result) == [3000] * 5 + [800, 800]
        assert voice._last_capture["voiced_seconds"] == 0.5

    def test_pre_roll_keeps_the_blocks_just_before_speech(self, monkeypatch, with_fake_key):
        quiet_marks = [_int16_block(level) for level in range(11, 21)]  # below threshold, distinguishable
        _install_sd(monkeypatch, blocks=calibration() + quiet_marks + [loud_block()] * 5 + [quiet_block()] * 20)
        result = voice.record()
        # pre-roll holds the last 3 blocks (18, 19, 20); front trimming keeps TRIM_MARGIN = 2 of them
        assert _block_levels(result) == [19, 20] + [3000] * 5 + [0, 0]
        assert voice._last_capture["trimmed_seconds"] == round((1 + 8) * voice.BLOCK_SECONDS, 2)

    def test_warmup_blocks_do_not_raise_the_noise_floor(self, monkeypatch, with_fake_key):
        # loud level ramp / TTS tail right after open must not count as room noise
        _install_sd(monkeypatch, blocks=calibration(0, warmup_amplitude=5000) + [quiet_block()] * 100)
        voice.record()
        assert voice._last_capture["noise_floor"] == 0
        assert voice._last_capture["threshold"] == voice.RMS_THRESHOLD_MIN == 600

    def test_one_voiced_block_is_too_short(self, monkeypatch, with_fake_key):
        assert round(voice.MIN_SPEECH_SECONDS / voice.BLOCK_SECONDS) == 2
        _install_sd(monkeypatch, blocks=calibration() + [loud_block()] + [quiet_block()] * 20)
        fake_url = _install_urlopen(monkeypatch, [])
        assert voice.listen() == ""
        assert fake_url.call_count == 0
        assert voice._last_capture["voiced_seconds"] == 0.1

    def test_two_voiced_blocks_reach_stt(self, monkeypatch, with_fake_key):
        # a short answer such as "2번" (~0.2 s voiced) must still be transcribed
        _install_sd(monkeypatch, blocks=calibration() + [loud_block()] * 2 + [quiet_block()] * 20)
        fake_url = _install_urlopen(monkeypatch, [_stt_body("2번")])
        assert voice.listen() == "2번"
        assert fake_url.call_count == 1
        assert voice._last_capture["voiced_seconds"] == 0.2

    def test_weak_sparse_input_is_not_sent(self, monkeypatch, with_fake_key):
        # three isolated blocks exactly at the threshold: voiced 0.3 s, but the trimmed clip is mostly silence
        level = voice.RMS_THRESHOLD_MIN
        clicks = [_int16_block(level)] + [quiet_block()] * 9 + [_int16_block(level)] + [quiet_block()] * 9 + [_int16_block(level)]
        _install_sd(monkeypatch, blocks=calibration() + clicks + [quiet_block()] * 20)
        fake_url = _install_urlopen(monkeypatch, [])
        assert voice.listen() == ""
        assert fake_url.call_count == 0


class TestPromptEchoGuard:
    def _transcribe(self, monkeypatch, text):
        fake_url = _install_urlopen(monkeypatch, [_stt_body(text)])
        result = voice.transcribe(_raw_pcm())
        assert fake_url.call_count == 1  # STT was called; only the result is discarded
        return result

    def test_whole_prompt_echo_becomes_silence(self, monkeypatch, with_fake_key):
        assert self._transcribe(monkeypatch, voice.STT_PROMPT) == ""
        assert voice.last_error() == "stt_prompt_echo: transcript repeats the STT prompt; treated as no speech"

    def test_three_prompt_items_are_an_echo(self, monkeypatch, with_fake_key):
        assert self._transcribe(monkeypatch, "의자, 벤치, 소파.") == ""
        assert voice.last_error().startswith("stt_prompt_echo")

    @pytest.mark.parametrize("utterance", ["의자 벤치 소파 스툴 만들어줘", "의자, 벤치, 소파, 스툴", "의자 벤치 소파요"])
    def test_hint_listing_is_an_echo(self, monkeypatch, with_fake_key, utterance):
        assert self._transcribe(monkeypatch, utterance) == ""
        assert voice.last_error().startswith("stt_prompt_echo")

    @pytest.mark.parametrize("utterance", ["의자 만들어줘", "의자를 만들고 싶어", "2번", "1번이요",
                                           "벤치처럼 길고 넓은 의자를 만들고 싶어요",  # 2026-10-08 재현: 힌트 3개, 나머지 많음
                                           "소파 같은 의자 만들어줘 등받이 높게", "왕좌처럼 높고 화려한 의자를 만들고 싶어요"])
    def test_normal_utterances_pass(self, monkeypatch, with_fake_key, utterance):
        assert self._transcribe(monkeypatch, utterance) == utterance
        assert voice.last_error() is None

    def test_listen_returns_empty_string_for_an_echo(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=calibration() + [loud_block()] * 3 + [quiet_block()] * 20)
        _install_urlopen(monkeypatch, [_stt_body(" " + voice.STT_PROMPT + " ")])
        assert voice.listen() == ""
        assert voice.last_error().startswith("stt_prompt_echo")


class TestShortClipPadding:
    def _sent_frames(self, monkeypatch, pcm):
        fake_url = _install_urlopen(monkeypatch, [_stt_body("2번")])
        assert voice.transcribe(pcm) == "2번"
        body = fake_url.calls[0]["request"].data
        wav_bytes = body[body.index(b"RIFF"):body.rindex(b"\r\n--")]
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            return _np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2")

    def test_short_clip_is_padded_to_two_seconds(self, monkeypatch, with_fake_key):
        clip = _raw_pcm(n=int(0.6 * voice.SAMPLE_RATE), amplitude=3000)  # 0.6 s
        sent = self._sent_frames(monkeypatch, clip)
        front = int(voice.PAD_FRONT_SECONDS * voice.SAMPLE_RATE)  # 4800 samples
        assert len(sent) == int(voice.MIN_CLIP_SECONDS * voice.SAMPLE_RATE) == 32000
        assert not sent[:front].any()  # 0.3 s of silence in front
        assert (sent[front:front + 9600] == 3000).all()  # the 0.6 s clip unchanged
        assert not sent[front + 9600:].any()  # the remaining 1.1 s of silence behind

    def test_long_clip_is_sent_unchanged(self, monkeypatch, with_fake_key):
        clip = _raw_pcm(n=int(2.5 * voice.SAMPLE_RATE), amplitude=3000)  # 2.5 s
        sent = self._sent_frames(monkeypatch, clip)
        assert len(sent) == 40000 and (sent == 3000).all()

    def test_front_padding_shrinks_when_close_to_the_minimum(self, monkeypatch, with_fake_key):
        clip = _raw_pcm(n=int(1.9 * voice.SAMPLE_RATE), amplitude=3000)  # deficit 0.1 s < 0.3 s front pad
        sent = self._sent_frames(monkeypatch, clip)
        assert len(sent) == 32000
        assert not sent[:1600].any() and (sent[1600:] == 3000).all()


class TestNoSpeechGate:
    def _transcribe(self, monkeypatch, body):
        fake_url = _install_urlopen(monkeypatch, [body])
        result = voice.transcribe(_raw_pcm())
        assert fake_url.call_count == 1
        return result

    def test_high_no_speech_prob_is_silence(self, monkeypatch, with_fake_key):
        assert self._transcribe(monkeypatch, _stt_body("흐흐흐흐", no_speech_prob=0.9)) == ""
        assert voice.last_error() == ("stt_no_speech: every segment has no_speech_prob >= 0.8 and avg_logprob < -1.0; "
                                      "treated as no speech")

    def test_low_no_speech_prob_passes(self, monkeypatch, with_fake_key):
        assert self._transcribe(monkeypatch, _stt_body("2번", no_speech_prob=0.3)) == "2번"
        assert voice.last_error() is None

    def test_short_answer_at_measured_no_speech_prob_passes(self, monkeypatch, with_fake_key):
        # a real short "2번" measured 0.55: the gate must stay conservative
        assert self._transcribe(monkeypatch, _stt_body("2번", no_speech_prob=0.55)) == "2번"

    def test_empty_segments_with_empty_text_are_silence(self, monkeypatch, with_fake_key):
        assert self._transcribe(monkeypatch, _stt_body("", segments=[])) == ""
        assert voice.last_error().startswith("stt_no_speech")

    def test_missing_segments_trust_text(self, monkeypatch, with_fake_key):
        # json 형식 응답·D 통합 테스트 fake처럼 segments 키가 없으면 text를 그대로 쓴다(무음 판정 불가).
        no_segments = json.dumps({"text": "의자"}).encode("utf-8")
        assert self._transcribe(monkeypatch, no_segments) == "의자"
        assert self._transcribe(monkeypatch, _stt_body("의자", segments=[])) == "의자"

    def test_one_confident_segment_is_enough(self, monkeypatch, with_fake_key):
        segments = [{"no_speech_prob": 0.95}, {"no_speech_prob": 0.2}]
        assert self._transcribe(monkeypatch, _stt_body("의자 만들어줘", segments=segments)) == "의자 만들어줘"

    def test_listen_returns_empty_string_for_no_speech(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=calibration() + [loud_block()] * 3 + [quiet_block()] * 20)
        _install_urlopen(monkeypatch, [_stt_body("흐흐흐흐", no_speech_prob=0.85)])
        assert voice.listen() == ""
        assert voice.last_error().startswith("stt_no_speech")


class TestOnReady:
    def test_called_once_after_warmup_and_calibration(self, monkeypatch, with_fake_key):
        fake_sd = _install_sd(monkeypatch, blocks=calibration() + [loud_block()] * 3 + [quiet_block()] * 20)
        _install_urlopen(monkeypatch, [_stt_body("의자")])
        reads_at_call = []

        assert voice.listen(on_ready=lambda: reads_at_call.append(fake_sd.streams[0].reads)) == "의자"
        assert reads_at_call == [PREFIX_BLOCKS] == [7]  # after 2 warm-up + 5 calibration, before the first wait block

    def test_called_once_even_when_nobody_speaks(self, monkeypatch, with_fake_key):
        fake_sd = _install_sd(monkeypatch, blocks=calibration() + [quiet_block()] * 100)
        calls = []
        assert voice.listen(on_ready=lambda: calls.append(fake_sd.streams[0].reads)) == ""
        assert calls == [PREFIX_BLOCKS]
        assert fake_sd.streams[0].reads == PREFIX_BLOCKS + round(voice.WAIT_SECONDS / voice.BLOCK_SECONDS)

    def test_default_is_no_callback(self, monkeypatch, with_fake_key):
        import inspect
        assert inspect.signature(voice.listen).parameters["on_ready"].default is None
        assert inspect.signature(voice.record).parameters["on_ready"].default is None
        _install_sd(monkeypatch, blocks=calibration() + [quiet_block()] * 100)
        assert voice.listen() == ""
        assert voice.last_error() is None

    def test_callback_exception_propagates(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=calibration() + [quiet_block()] * 100)

        def broken():
            raise ValueError("display failed")

        with pytest.raises(ValueError, match="display failed"):
            voice.listen(on_ready=broken)
        assert voice.last_error() is None  # not reported as an audio device failure


class TestDebugDumpReasons:
    @pytest.fixture
    def debug_dir(self, monkeypatch, tmp_path):
        path = tmp_path / "voice_debug"
        monkeypatch.setenv(voice.DEBUG_DIR_ENV, str(path))
        return path

    @staticmethod
    def _info(debug_dir):
        return json.loads((debug_dir / "latest_input.json").read_text(encoding="utf-8"))

    def test_no_speech_detected(self, monkeypatch, with_fake_key, debug_dir):
        _install_sd(monkeypatch, blocks=calibration() + [quiet_block()] * 100)
        fake_url = _install_urlopen(monkeypatch, [])
        assert voice.listen() == ""
        assert fake_url.call_count == 0
        assert self._info(debug_dir) == {"stt_called": False, "reason": "no_speech_detected", "noise_floor": 0,
                                         "threshold": voice.RMS_THRESHOLD_MIN, "voiced_seconds": 0.0,
                                         "duration": voice.WAIT_SECONDS, "calibration_unstable": False, "calibration_retries": 0}
        assert not (debug_dir / "latest_input.wav").exists()

    def test_too_short(self, monkeypatch, with_fake_key, debug_dir):
        _install_sd(monkeypatch, blocks=calibration() + [quiet_block()] * 4 + [loud_block()] + [quiet_block()] * 20)
        assert voice.listen() == ""
        info = self._info(debug_dir)
        assert (info["stt_called"], info["reason"], info["voiced_seconds"]) == (False, "too_short", 0.1)
        assert info["duration"] == round((4 + 1 + 10) * voice.BLOCK_SECONDS, 2)  # wait 4 + speech 1 + trailing 10

    def test_weak_input(self, monkeypatch, with_fake_key, debug_dir):
        level = voice.RMS_THRESHOLD_MIN
        clicks = [_int16_block(level)] + [quiet_block()] * 9 + [_int16_block(level)] + [quiet_block()] * 9 + [_int16_block(level)]
        _install_sd(monkeypatch, blocks=calibration() + clicks + [quiet_block()] * 20)
        assert voice.listen() == ""
        info = self._info(debug_dir)
        assert (info["stt_called"], info["reason"], info["voiced_seconds"]) == (False, "weak_input", 0.3)

    @pytest.mark.parametrize("body, reason", [
        (lambda: _stt_body("흐흐흐흐", no_speech_prob=0.9), "no_speech_prob"),
        (lambda: _stt_body(voice.STT_PROMPT), "prompt_echo"),
    ])
    def test_stt_called_but_rejected(self, monkeypatch, with_fake_key, debug_dir, body, reason):
        _install_sd(monkeypatch, blocks=calibration() + [loud_block()] * 3 + [quiet_block()] * 20)
        fake_url = _install_urlopen(monkeypatch, [body()])
        assert voice.listen() == ""
        assert fake_url.call_count == 1
        info = self._info(debug_dir)
        assert (info["stt_called"], info["reason"]) == (True, reason)
        assert (debug_dir / "latest_input.wav").exists()  # the WAV that was actually sent

    def test_stale_wav_removed_when_stt_is_not_called(self, monkeypatch, with_fake_key, debug_dir):
        _install_sd(monkeypatch, blocks=calibration() + [loud_block()] * 3 + [quiet_block()] * 20)
        _install_urlopen(monkeypatch, [_stt_body("의자")])
        assert voice.listen() == "의자"
        assert (debug_dir / "latest_input.wav").exists()
        _install_sd(monkeypatch, blocks=calibration() + [quiet_block()] * 100)
        assert voice.listen() == ""
        assert not (debug_dir / "latest_input.wav").exists()
        assert self._info(debug_dir)["reason"] == "no_speech_detected"


class TestDebugDump:
    SPEECH = staticmethod(lambda: calibration() + [loud_block()] * 5 + [quiet_block()] * 20)

    def test_dump_written_only_when_env_is_set(self, monkeypatch, with_fake_key, tmp_path):
        debug_dir = tmp_path / "voice_debug"
        monkeypatch.setenv(voice.DEBUG_DIR_ENV, str(debug_dir))
        _install_sd(monkeypatch, blocks=self.SPEECH())
        _install_urlopen(monkeypatch, [_stt_body("의자")])

        assert voice.listen() == "의자"

        with wave.open(str(debug_dir / "latest_input.wav"), "rb") as wav_file:
            assert wav_file.getframerate() == voice.SAMPLE_RATE
            assert wav_file.getnchannels() == 1
            # the trimmed clip (0.7 s) padded with silence to MIN_CLIP_SECONDS: exactly what was sent to STT
            assert wav_file.getnframes() == int(voice.MIN_CLIP_SECONDS * voice.SAMPLE_RATE) == 32000
        info = json.loads((debug_dir / "latest_input.json").read_text(encoding="utf-8"))
        assert info["sample_rate"] == voice.SAMPLE_RATE and info["channels"] == 1
        assert info["duration"] == voice.MIN_CLIP_SECONDS == 2.0
        assert info["peak"] == 3000
        assert info["noise_floor"] == 0 and info["threshold"] == voice.RMS_THRESHOLD_MIN == 600
        assert info["voiced_seconds"] == 0.5
        assert set(info) == {"sample_rate", "channels", "duration", "rms", "peak", "weak_input", "noise_floor", "threshold",
                             "voiced_seconds", "trimmed_seconds", "calibration_unstable", "calibration_retries", "stt_called", "reason",
                             "whisper_text", "no_speech_probs", "avg_logprobs"}
        assert info["stt_called"] is True and info["reason"] is None
        assert info["weak_input"] is True  # peak 3000 < WEAK_INPUT_PEAK: 표시만 하고 STT 결과는 바꾸지 않는다
        assert info["whisper_text"] == "의자" and info["no_speech_probs"] == [0.1] and info["avg_logprobs"] == [None]
        assert FAKE_KEY not in (debug_dir / "latest_input.json").read_text(encoding="utf-8")

    def test_no_dump_without_env(self, monkeypatch, with_fake_key, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(voice, "_dump_debug", lambda *a: pytest.fail("debug dump without C_VOICE_DEBUG_DIR"))
        _install_sd(monkeypatch, blocks=self.SPEECH())
        _install_urlopen(monkeypatch, [_stt_body("의자")])
        assert voice.listen() == "의자"
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# 4. transcribe(): request shape, retries, env overrides, temp files
# ---------------------------------------------------------------------------


class TestTranscribeRequestShape:
    def test_multipart_fields_and_headers(self, monkeypatch, with_fake_key):
        fake_url = _install_urlopen(monkeypatch, [_stt_body("hello")])

        result = voice.transcribe(_raw_pcm())

        assert result == "hello"
        assert fake_url.call_count == 1
        request = fake_url.calls[0]["request"]
        body = request.data

        assert b'name="model"' in body
        assert b"whisper-1" in body
        assert b'name="language"\r\n\r\nko\r\n' in body
        assert ('name="prompt"\r\n\r\n' + voice.STT_PROMPT + "\r\n").encode("utf-8") in body
        assert b'name="response_format"\r\n\r\nverbose_json\r\n' in body
        assert voice.STT_PROMPT == "의자, 벤치, 소파, 스툴, 만들어줘, 만들고 싶어"
        # echoed hints must never change the answer's meaning; numbers made whisper invent "3번, 4번, …"
        for word in ("취소", "원래대로", "재설계", "번", "1", "2"):
            assert word not in voice.STT_PROMPT
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
        fake_url = _install_urlopen(monkeypatch, [_stt_body("hi")])

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
            monkeypatch, [_http_error(429), _stt_body("ok")]
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

        _install_urlopen(monkeypatch, [_stt_body("ok")])

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


def _tts_http_error(code, provider_code=None, param=None):
    """OpenAI 형식 오류 본문을 가진 HTTPError(본문 문장은 last_error에 남으면 안 된다)."""
    body = json.dumps({"error": {"message": "secret-ish provider sentence", "type": "invalid_request_error",
                                 "param": param, "code": provider_code}}).encode("utf-8")
    return urllib.error.HTTPError("https://example.invalid/", code, "error", None, io.BytesIO(body))


@pytest.fixture
def clean_tts_env(monkeypatch):
    for name in ("OPENAI_TTS_MODEL", "OPENAI_TTS_VOICE", "OPENAI_TTS_INSTRUCTIONS"):
        monkeypatch.delenv(name, raising=False)


class TestTtsModelPayload:
    """Stage 2: 기본 gpt-4o-mini-tts + instructions, tts-1은 기존 payload 그대로(D 통합 테스트 호환)."""

    def _payload(self, monkeypatch):
        _install_sd(monkeypatch)
        fake_url = _install_urlopen(monkeypatch, [_build_wav_bytes()])
        voice.speak("혹시 생각했거나 만들고 싶은 의자가 있어?")
        return json.loads(fake_url.calls[0]["request"].data)

    def test_default_is_gpt_4o_mini_tts_with_instructions(self, monkeypatch, with_fake_key, clean_tts_env):
        payload = self._payload(monkeypatch)
        assert voice.DEFAULT_TTS_MODEL == "gpt-4o-mini-tts"
        assert payload == {
            "model": "gpt-4o-mini-tts",
            "input": "혹시 생각했거나 만들고 싶은 의자가 있어?",
            "voice": voice.DEFAULT_TTS_VOICE,
            "response_format": "wav",
            "instructions": voice.DEFAULT_TTS_INSTRUCTIONS,
        }

    @pytest.mark.parametrize("model", ["tts-1", "tts-1-hd"])
    def test_legacy_model_payload_has_no_instructions(self, monkeypatch, with_fake_key, clean_tts_env, model):
        monkeypatch.setenv("OPENAI_TTS_MODEL", model)
        monkeypatch.setenv("OPENAI_TTS_VOICE", "alloy")
        monkeypatch.setenv("OPENAI_TTS_INSTRUCTIONS", "무시돼야 하는 지시")
        payload = self._payload(monkeypatch)
        assert payload == {"model": model, "input": "혹시 생각했거나 만들고 싶은 의자가 있어?",
                           "voice": "alloy", "response_format": "wav"}

    def test_env_overrides_voice_and_instructions(self, monkeypatch, with_fake_key, clean_tts_env):
        monkeypatch.setenv("OPENAI_TTS_VOICE", "marin")
        monkeypatch.setenv("OPENAI_TTS_INSTRUCTIONS", "밝게 말해 주세요.")
        payload = self._payload(monkeypatch)
        assert payload["model"] == "gpt-4o-mini-tts"
        assert payload["voice"] == "marin"
        assert payload["instructions"] == "밝게 말해 주세요."

    def test_empty_env_values_fall_back_to_defaults(self, monkeypatch, with_fake_key, clean_tts_env):
        for name in ("OPENAI_TTS_MODEL", "OPENAI_TTS_VOICE", "OPENAI_TTS_INSTRUCTIONS"):
            monkeypatch.setenv(name, "")
        payload = self._payload(monkeypatch)
        assert payload["model"] == voice.DEFAULT_TTS_MODEL
        assert payload["voice"] == voice.DEFAULT_TTS_VOICE
        assert payload["instructions"] == voice.DEFAULT_TTS_INSTRUCTIONS

    def test_playback_call_shape_and_last_speak(self, monkeypatch, with_fake_key, clean_tts_env):
        fake_sd = _install_sd(monkeypatch)
        _install_urlopen(monkeypatch, [_build_wav_bytes(sample_rate=24000, n_samples=2400)])

        voice.speak("Design과 다르게 놓인 부분이 있는데 의도된 행동인가요?")

        assert len(fake_sd.play_calls) == 1 and fake_sd.wait_calls == 1
        frames, samplerate = fake_sd.play_calls[0]
        assert samplerate == 24000 and len(frames) == 2400
        info = voice._last_speak
        assert info["model"] == "gpt-4o-mini-tts" and info["instructions_sent"] is True
        assert info["audio_seconds"] == 0.1 and info["samplerate"] == 24000
        assert info["play_started_at"] and info["play_ended_at"]
        assert FAKE_TTS_KEY not in json.dumps(info)
        assert voice.last_error() is None


class TestTtsErrorKinds:
    """TTS 실패는 kind와 HTTP code만 남긴다(응답 본문·key 미기록)."""

    @pytest.mark.parametrize("outcomes, expected", [
        ([_tts_http_error(401)], "auth: HTTP 401"),
        ([_tts_http_error(403)], "auth: HTTP 403"),
        ([_tts_http_error(403, "model_not_found")], "model_access: HTTP 403"),
        ([_tts_http_error(404, "model_not_found")], "model_access: HTTP 404"),
        ([_tts_http_error(400, "model_not_found")], "model_access: HTTP 400"),
        ([_tts_http_error(400, None, "instructions")], "bad_param: HTTP 400"),
        ([_tts_http_error(400, "unsupported_parameter")], "bad_param: HTTP 400"),
        ([_tts_http_error(400)], "bad_response: HTTP 400"),
        ([_tts_http_error(429, "insufficient_quota") for _ in range(4)], "billing: HTTP 429"),
        ([_tts_http_error(429, "rate_limit_exceeded") for _ in range(4)], "rate_limit: HTTP 429"),
        ([_tts_http_error(503) for _ in range(4)], "server: HTTP 503"),
        ([TimeoutError()] * 4, f"timeout: no response within {voice.TIMEOUT_SECONDS} s"),
        ([_http_error(403)], "auth: HTTP 403"),  # 본문 없는 오류도 분류는 유지
    ])
    def test_kind(self, monkeypatch, with_fake_key, clean_tts_env, outcomes, expected):
        fake_sd = _install_sd(monkeypatch)
        _install_urlopen(monkeypatch, outcomes)

        voice.speak("hello")  # must not raise

        assert voice.last_error() == expected
        assert "provider sentence" not in voice.last_error()
        assert FAKE_TTS_KEY not in voice.last_error()
        assert len(fake_sd.play_calls) == 0

    def test_stale_http_error_is_not_reused_for_missing_key(self, monkeypatch, with_fake_key, clean_tts_env):
        _install_sd(monkeypatch)
        _install_urlopen(monkeypatch, [_tts_http_error(403, "model_not_found")])
        voice.speak("hello")
        monkeypatch.delenv("OPENAI_TTS_API_KEY")

        voice.speak("hello")

        assert voice.last_error() == "missing_key: OPENAI_TTS_API_KEY is not set"

    def test_stt_error_kinds_are_unchanged(self, monkeypatch, with_fake_key):
        _install_urlopen(monkeypatch, [_tts_http_error(403, "model_not_found")])
        assert voice.transcribe(_raw_pcm()) is None
        assert voice.last_error() == "auth: HTTP 403"


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
        fake_url = _install_urlopen(monkeypatch, [_stt_body("ok")])

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
        _install_urlopen(monkeypatch, [_stt_body("ok")])
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


class TestCalibrationGuard:
    """보정 구간에 발화·순간 잡음이 섞이면 0.3 s를 버리고 딱 한 번만 다시 보정한다(무한 재보정 금지)."""

    def _blocks(self, first_cal, second_cal, after):
        retry_gap = round(voice.CALIBRATION_RETRY_DELAY_SECONDS / voice.BLOCK_SECONDS)
        return ([quiet_block() for _ in range(WARMUP_BLOCKS)] + first_cal + [_int16_block(9999)] * retry_gap + second_cal + after)

    def test_speech_in_calibration_triggers_exactly_one_retry(self, monkeypatch, with_fake_key):
        first = [quiet_block(), quiet_block(), _int16_block(3000), _int16_block(3000), quiet_block()]  # 발화가 섞인 보정
        second = [quiet_block() for _ in range(CAL_BLOCKS)]
        fake_sd = _install_sd(monkeypatch, blocks=self._blocks(first, second, [loud_block()] * 5 + [quiet_block()] * 20))
        pcm = voice.record()
        cap = voice._last_capture
        assert cap["calibration_unstable"] is True and cap["calibration_retries"] == 1 and cap["calibration_still_unstable"] is False
        assert cap["noise_floor"] == 0 and cap["threshold"] == voice.RMS_THRESHOLD_MIN  # 재보정 결과를 쓴다
        assert cap["calibration_max"] == 0 and cap["calibration_median"] == 0
        assert pcm != b"" and cap["voiced_seconds"] == 0.5  # 뒤따르는 발화를 놓치지 않는다
        assert fake_sd.streams[-1].reads >= WARMUP_BLOCKS + CAL_BLOCKS + 3 + CAL_BLOCKS + 5

    def test_second_unstable_calibration_is_not_retried_again(self, monkeypatch, with_fake_key):
        noisy = [quiet_block(), _int16_block(3000), quiet_block(), quiet_block(), quiet_block()]
        _install_sd(monkeypatch, blocks=self._blocks(list(noisy), list(noisy), [quiet_block()] * 100))
        voice.record()
        cap = voice._last_capture
        assert cap["calibration_retries"] == voice.CALIBRATION_RETRIES_MAX == 1  # 두 번째 보정도 불안정하지만 더 재보정하지 않는다
        assert cap["calibration_unstable"] is True and cap["calibration_still_unstable"] is True
        assert cap["calibration_max"] == 3000 and cap["noise_floor"] == 0

    def test_steady_noise_is_not_unstable(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=calibration(800) + [_int16_block(800)] * 100)
        voice.record()
        cap = voice._last_capture
        assert cap["calibration_unstable"] is False and cap["calibration_retries"] == 0
        assert cap["calibration_min"] == cap["calibration_median"] == cap["calibration_max"] == 800

    def test_timeline_and_stream_timestamps_are_recorded(self, monkeypatch, with_fake_key):
        _install_sd(monkeypatch, blocks=calibration() + [loud_block()] * 5 + [quiet_block()] * 20)
        seen = []
        voice.record(on_ready=lambda: seen.append("ready"))
        cap = voice._last_capture
        assert seen == ["ready"]
        assert set(cap["timeline"]) == {"warmup_done", "calibration_done", "on_ready"}
        assert cap["timeline"]["warmup_done"] <= cap["timeline"]["calibration_done"] <= cap["timeline"]["on_ready"]
        assert cap["stream_opened_at"] <= cap["stream_closed_at"]



# ---------------------------------------------------------------------------
# Stage 2 Wave 4b: 복합 무음 규칙, listen mode "free", beep, prewarm
# ---------------------------------------------------------------------------


def _segment(text, no_speech_prob, avg_logprob=None):
    seg = {"id": 0, "text": text, "no_speech_prob": no_speech_prob}
    if avg_logprob is not None:
        seg["avg_logprob"] = avg_logprob
    return seg


class TestCompositeNoSpeech:
    def _transcribe(self, monkeypatch, segments, text):
        _install_urlopen(monkeypatch, [_stt_body(text, segments=segments)])
        return voice.transcribe(_raw_pcm())

    def test_measured_free_request_passes_when_decoding_is_confident(self, monkeypatch, with_fake_key):
        # 2026-10-08 사용자 E2E: no_speech_prob 0.812 하나로 버려진 실제 발화(avg_logprob은 -1.0 이상이라고 가정)
        text = "왕자처럼 높고 화려한 의자"
        assert self._transcribe(monkeypatch, [_segment(text, 0.812, -0.4)], text) == text
        assert voice.last_error() is None

    def test_high_no_speech_and_low_logprob_is_silence(self, monkeypatch, with_fake_key):
        assert self._transcribe(monkeypatch, [_segment("흐흐흐흐", 0.9, -1.5)], "흐흐흐흐") == ""
        assert voice.last_error().startswith("stt_no_speech")

    def test_segment_without_avg_logprob_keeps_the_old_rule(self, monkeypatch, with_fake_key):
        assert self._transcribe(monkeypatch, [_segment("흐흐흐흐", 0.9)], "흐흐흐흐") == ""

    def test_any_speech_segment_keeps_the_transcript(self, monkeypatch, with_fake_key):
        segments = [_segment("음", 0.95, -1.8), _segment("벤치처럼 넓은 의자", 0.85, -0.3)]
        assert self._transcribe(monkeypatch, segments, "음 벤치처럼 넓은 의자") == "음 벤치처럼 넓은 의자"

    def test_debug_records_avg_logprobs(self, monkeypatch, with_fake_key, tmp_path):
        monkeypatch.setenv(voice.DEBUG_DIR_ENV, str(tmp_path))
        self._transcribe(monkeypatch, [_segment("왕좌", 0.812, -0.4), _segment("의자", 0.2)], "왕좌 의자")
        info = json.loads((tmp_path / "latest_input.json").read_text(encoding="utf-8"))
        assert info["no_speech_probs"] == [0.812, 0.2] and info["avg_logprobs"] == [-0.4, None]


def _speech_after(prefix_blocks, speech=5, pause=0, more_speech=0):
    """warm-up·보정(+버림) 뒤 발화 → (pause 무음) → (more_speech 발화) → 긴 무음."""
    return (calibration() + [quiet_block() for _ in range(prefix_blocks)] + [loud_block()] * speech
            + [quiet_block()] * pause + [loud_block()] * more_speech + [quiet_block()] * 40)


class TestListenModes:
    def test_defaults_are_unchanged_and_free_values(self):
        assert (voice.WAIT_SECONDS, voice.TRAILING_SILENCE_SECONDS) == (8.0, 1.0)
        assert (voice.FREE_WAIT_SECONDS, voice.FREE_TRAILING_SILENCE_SECONDS) == (10.0, 1.5)

    def test_free_mode_keeps_a_1_2_s_pause_inside_one_utterance(self, monkeypatch, with_fake_key):
        blocks = _speech_after(0, speech=5, pause=12, more_speech=5)
        _install_sd(monkeypatch, blocks=list(blocks))
        short = voice.record()
        short_voiced = voice._last_capture["voiced_seconds"]
        _install_sd(monkeypatch, blocks=list(blocks))
        _install_urlopen(monkeypatch, [_stt_body("왕좌처럼 높고 화려한 의자")])
        assert voice.listen(mode="free") == "왕좌처럼 높고 화려한 의자"
        assert voice._last_capture["mode"] == "free"
        assert short_voiced == 0.5 and voice._last_capture["voiced_seconds"] == 1.0  # short는 쉼에서 끊긴다
        assert short != b""

    def test_free_mode_waits_longer_for_the_first_word(self, monkeypatch, with_fake_key):
        blocks = _speech_after(90)  # 9 s 뒤에 말하기 시작
        _install_sd(monkeypatch, blocks=list(blocks))
        assert voice.listen() == ""  # short: 8 s 대기 후 침묵
        _install_sd(monkeypatch, blocks=list(blocks))
        _install_urlopen(monkeypatch, [_stt_body("벤치")])
        assert voice.listen(mode="free") == "벤치"

    def test_mode_is_reset_after_each_listen_and_record_stays_argument_free(self, monkeypatch, with_fake_key):
        seen = []
        monkeypatch.setattr(voice, "record", lambda: seen.append(dict(voice._capture_options)) or b"")
        assert voice.listen(mode="free", beep=True) == ""
        assert seen == [{"mode": "free", "beep": True}]
        assert voice._capture_options == {"mode": "short", "beep": False}

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError):
            voice.listen(mode="long")


class TestBeep:
    def test_beep_plays_after_calibration_and_discards_input_before_waiting(self, monkeypatch, with_fake_key):
        discard = round(voice.BEEP_DISCARD_SECONDS / voice.BLOCK_SECONDS)
        # 버리는 구간을 크게 만들어 두면, 버리지 않을 경우 그 블록이 발화로 잡힌다
        blocks = calibration() + [loud_block(amplitude=9000)] * discard + [quiet_block()] * 5 + [loud_block()] * 5 + [quiet_block()] * 30
        events = []
        fake_sd = _install_sd(monkeypatch, events=events, blocks=blocks)
        ready = []
        _install_urlopen(monkeypatch, [_stt_body("네")])
        assert voice.listen(on_ready=lambda: ready.append(fake_sd.streams[0].reads), mode="free", beep=True) == "네"
        frames, samplerate = fake_sd.play_calls[0]
        assert samplerate == voice.SAMPLE_RATE and len(frames) == int(voice.SAMPLE_RATE * voice.BEEP_SECONDS)
        assert ready == [PREFIX_BLOCKS + discard]  # 보정 → beep → 버림 → on_ready
        assert voice._last_capture["beep"] is True and voice._last_capture["voiced_seconds"] == 0.5

    def test_beep_output_failure_is_ignored(self, monkeypatch, with_fake_key):
        fake_sd = _install_sd(monkeypatch, blocks=_speech_after(round(voice.BEEP_DISCARD_SECONDS / voice.BLOCK_SECONDS)))

        def broken_play(*a, **k):
            raise OSError("no output device")

        monkeypatch.setattr(fake_sd, "play", broken_play)
        _install_urlopen(monkeypatch, [_stt_body("아무거나")])
        assert voice.listen(beep=True) == "아무거나"
        assert voice._last_capture["beep"] is False and voice.last_error() is None

    def test_no_beep_by_default(self, monkeypatch, with_fake_key):
        fake_sd = _install_sd(monkeypatch, blocks=_speech_after(0))
        _install_urlopen(monkeypatch, [_stt_body("1번")])
        assert voice.listen() == "1번"
        assert fake_sd.play_calls == []


class TestPrewarm:
    def test_prewarm_opens_and_closes_one_stream_without_reading(self, monkeypatch):
        fake_sd = _install_sd(monkeypatch)
        assert voice.prewarm() is True
        assert len(fake_sd.streams) == 1 and fake_sd.streams[0].closed and fake_sd.streams[0].reads == 0

    def test_prewarm_failure_returns_false_without_raising(self, monkeypatch):
        _install_sd(monkeypatch, open_error=OSError("no input device"))
        assert voice.prewarm() is False

    def test_prewarm_missing_module_returns_false(self, monkeypatch):
        def missing():
            raise ImportError("sounddevice")

        monkeypatch.setattr(voice, "_sounddevice", missing)
        assert voice.prewarm() is False


# ---------------------------------------------------------------------------
# Stage 3 mic E2E 429 진단: STT 429의 세부(type·code·message·Retry-After)와 quota 즉시 실패
# ---------------------------------------------------------------------------


def _stt_http_error(code, provider_code, error_type, message, retry_after=None):
    body = json.dumps({"error": {"message": message, "type": error_type, "param": None, "code": provider_code}}).encode("utf-8")
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.invalid/", code, "error", headers, io.BytesIO(body))


class TestStt429Diagnostics:
    def test_insufficient_quota_fails_immediately_as_billing_with_detail(self, monkeypatch, with_fake_key):
        fake = _install_urlopen(monkeypatch, [_stt_http_error(429, "insufficient_quota", "insufficient_quota",
                                                              "You exceeded your current quota sk-abcdefghijkl end")
                                              for _ in range(4)])
        assert voice.transcribe(_raw_pcm()) is None
        assert fake.call_count == 1  # quota/billing 429는 재시도하지 않는다
        assert voice.last_error() == "billing: HTTP 429"
        detail = voice.last_http_error()
        assert detail["http_status"] == 429 and detail["code"] == "insufficient_quota"
        assert detail["type"] == "insufficient_quota" and detail["retry_after"] is None
        assert "quota" in detail["message"] and "sk-abcdefghijkl" not in detail["message"] and "[redacted]" in detail["message"]
        assert FAKE_KEY not in json.dumps(detail)

    def test_real_credit_balance_exhausted_shape_is_billing_without_retry(self, monkeypatch, with_fake_key):
        # 2026-10-11 실측 응답 형식: type insufficient_quota, code credit_balance_exhausted
        fake = _install_urlopen(monkeypatch, [_stt_http_error(429, "credit_balance_exhausted", "insufficient_quota",
                                                              "You have no credits remaining. Add credits to continue.")
                                              for _ in range(4)])
        assert voice.transcribe(_raw_pcm()) is None and fake.call_count == 1
        assert voice.last_error() == "billing: HTTP 429"
        assert voice.last_http_error()["code"] == "credit_balance_exhausted"

    def test_rate_limit_exceeded_keeps_the_limited_retry_and_records_retry_after(self, monkeypatch, with_fake_key):
        fake = _install_urlopen(monkeypatch, [_stt_http_error(429, "rate_limit_exceeded", "requests", "Rate limit reached",
                                                              retry_after="20") for _ in range(4)])  # 본문은 1회만 읽힌다
        assert voice.transcribe(_raw_pcm()) is None
        assert fake.call_count == 4  # 기존 정책: 일시적 429는 최대 3회 재시도
        assert voice.last_error() == "rate_limit: HTTP 429"
        detail = voice.last_http_error()
        assert (detail["code"], detail["type"], detail["retry_after"]) == ("rate_limit_exceeded", "requests", "20")

    def test_success_clears_the_http_detail(self, monkeypatch, with_fake_key):
        _install_urlopen(monkeypatch, [_stt_http_error(429, "rate_limit_exceeded", "requests", "x"), _stt_body("ok")])
        assert voice.transcribe(_raw_pcm()) == "ok"
        _install_urlopen(monkeypatch, [_stt_body("ok")])
        assert voice.transcribe(_raw_pcm()) == "ok" and voice.last_http_error() is None
