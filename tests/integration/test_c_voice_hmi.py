"""C 실제 음성 함수→C/A/D/Qt. 녹음 장치·HTTP·재생은 Fake, Robot도 Fake다."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.abd_input_hmi import AbdInputDemo
from app.c_design import llm, voice
from app.qt_hmi import HmiWindow
from test_abd_input_hmi import records, transfer, wait_for
from test_c_function_hmi import INITIAL, settled

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def audio(monkeypatch):
    """실제 listen/transcribe/speak의 입출력 경계만 대체한다."""
    texts, events = ["의자 만들어줘"], []
    monkeypatch.setenv("OPENAI_API_KEY", "mock-stt-secret")
    monkeypatch.setenv("OPENAI_TTS_API_KEY", "mock-tts-secret")
    monkeypatch.setenv("OPENAI_STT_MODEL", "whisper-1")
    monkeypatch.setenv("OPENAI_TTS_MODEL", "tts-1")
    monkeypatch.setenv("OPENAI_TTS_VOICE", "alloy")
    monkeypatch.setattr(voice, "POST_SPEAK_DELAY", 0)

    def record():
        voice._clear_error()
        events.append("record")
        return b"\x00\x01" * 160

    def request(url, body, content_type, key_env):
        if url == voice.STT_URL:
            assert key_env == "OPENAI_API_KEY" and b"whisper-1" in body and b"speech.wav" in body
            events.append("stt")
            return json.dumps(dict(text=texts.pop(0))).encode()
        assert url == voice.TTS_URL and key_env == "OPENAI_TTS_API_KEY"
        payload = json.loads(body)
        assert payload["model"] == "tts-1" and payload["voice"] == "alloy"
        events.append(("tts", payload["input"]))
        return voice._wav_bytes(b"\x00\x01" * 160)

    class Output:
        def play(self, frames, samplerate):
            assert frames.size == 160 and samplerate == 16000
            events.append("play")

        def wait(self):
            events.append("play_finished")

    monkeypatch.setattr(voice, "record", record)
    monkeypatch.setattr(voice, "_request", request)
    monkeypatch.setattr(voice, "_sounddevice", Output)
    return texts, events


@pytest.fixture
def create(audio, monkeypatch, tmp_path):
    qapp = QApplication.instance() or QApplication([])
    windows, llm_calls = [], []

    def http(payload, key):
        llm_calls.append(deepcopy(payload))
        assert payload["model"] == "gpt-4o"
        design = deepcopy(INITIAL["design"])
        if len(llm_calls) > 1:
            design["design_version"] = 2
            first = next(b for b in design["blocks"] if (b["x"], b["y"], b["layer"]) == (9, 12, 1))
            first["color"] = "blue" if first["color"] == "yellow" else "yellow"
        return dict(choices=[dict(message=dict(content=json.dumps(design)))])

    monkeypatch.setattr(llm, "_post_json", http)
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")

    def build(start=True):
        window = HmiWindow(screen_size=QSize(1920, 1080))
        demo = AbdInputDemo(window, tmp_path, c_mode="live", c_voice=True, delay_ms=1)
        windows.append((window, demo))
        window.show()
        qapp.processEvents()
        if start:
            window.buttons["START"].click()
            settled(demo)
        return window, demo, llm_calls

    yield build
    for window, demo in windows:
        demo.c_connection.close()
        settled(demo)
        window.close()


def mismatch(demo):
    transfer(demo)
    target = deepcopy(demo.backend._next_step()["after"])
    demo.receive(dict(event="observe_wrong_color"))
    settled(demo)
    return target


def test_start_mic_design_actual_a_fake_delivery_only_observation_completes(create, audio, tmp_path):
    window, demo, calls = create(start=False)
    assert audio[1] == [] and not demo.driver.calls
    window.buttons["START"].click()
    settled(demo)
    assert audio[1] == ["record", "stt"] and len(calls) == 1
    assert window.design_board.blocks == INITIAL["design"]["blocks"]
    assert not demo.driver.calls and demo.backend.state["current"]["blocks"] == []
    transfer(demo)
    assert demo.backend.state["current"]["blocks"] == []
    assert demo.backend.state["context"]["confirmed_steps"] == []
    demo.receive(dict(event="observe"))
    QApplication.instance().processEvents()
    assert len(demo.backend.state["context"]["confirmed_steps"]) == 1
    assert len(demo.driver.calls) == 3 and demo.backend.state["reason"] == "WAIT_PLACE_EMPTY"
    assert "AI 생성 음성" in window.notice.toPlainText()
    assert window.grab().save(str(tmp_path / "voice-start-observed.png"))
    log = records(demo)
    assert any(r["event"] == "C_VOICE_RESULT" and r["result"]["text"] == "의자 만들어줘" for r in log)
    assert "mock-stt-secret" not in json.dumps(log) and "mock-tts-secret" not in json.dumps(log)
    assert any(r["event"] == "SYNTHETIC_OBSERVATION_INPUT" for r in log)


@pytest.mark.parametrize("answer,workflow", [("1번", "WAIT_CORRECTION"), ("취소", "HOLD"),
                                             ("2번", "HOLD")])
def test_question_playback_before_spoken_answer_and_revise_uses_actual_a(create, audio, answer, workflow):
    audio[0].append(answer)
    window, demo, calls = create()
    target = mismatch(demo)
    state = demo.backend.state
    actual = {**target, "color": "blue" if target["color"] == "yellow" else "yellow"}
    assert state["current"] == dict(current_revision=1, blocks=[actual])
    assert state["workflow_status"] == workflow and len(demo.driver.calls) == 3
    events = audio[1]
    assert isinstance(events[2], tuple) and events[2][0] == "tts"
    assert events[3:] == ["play", "play_finished", "record", "stt"]
    QApplication.instance().processEvents()
    assert actual in window.target_board.blocks
    if answer == "2번":
        assert len(calls) == 2 and state["context"]["design"]["design_version"] == 2
        assert state["context"]["base_current"] == state["current"]
        assert len(state["context"]["plan"]["steps"]) == 14
        assert state["reason"] == "WAIT_PLACE_EMPTY"
        transfer(demo)
        assert len(demo.driver.calls) == 6
    else:
        assert len(calls) == 1 and state["context"]["design"]["design_version"] == 1


def test_two_unclear_answers_wait_for_explicit_choice_without_more_recording(create, audio):
    audio[0].extend(["모르겠어요", "모르겠어요"])
    window, demo, _ = create()
    mismatch(demo)
    assert demo.backend.state["workflow_status"] == "WAIT_INTENT"
    assert demo.backend.state["choice_required"] and not demo.c_connection.active
    assert audio[1].count("record") == 3
    before = deepcopy(audio[1])
    QTest.qWait(30)
    assert audio[1] == before and len(demo.driver.calls) == 3
    with pytest.raises(ValueError, match="음성 시험"):
        demo.receive(dict(event="answer", request_id=demo.backend.state["question_request"]["request_id"], text="1번"))


@pytest.mark.parametrize("failure", ["silence", "device", "auth", "unsupported"])
def test_initial_audio_failure_has_no_plan_or_mock_fallback(create, audio, monkeypatch, failure):
    if failure in ("silence", "device"):
        def record():
            voice._clear_error()
            if failure == "device":
                voice._set_error("audio_device", "TestMicrophoneMissing")
                return None
            return b""
        monkeypatch.setattr(voice, "record", record)
    elif failure == "auth":
        def request(*args):
            voice._set_error("auth", "HTTP 401")
            return None
        monkeypatch.setattr(voice, "_request", request)
    else:
        audio[0][0] = "자동차 만들어줘"
    window, demo, calls = create()
    assert demo.backend.state["workflow_status"] == "HOLD"
    assert demo.backend.state["context"] is None and not demo.driver.calls and not calls
    assert not window.design_board.blocks
    reason = demo.backend.state["reason"]
    assert ("UNSUPPORTED_OBJECT" if failure == "unsupported" else "VOICE_IO_FAILED") in reason


def test_tts_failure_holds_without_listening_to_an_unheard_question(create, audio, monkeypatch):
    _, demo, _ = create()
    original = voice._request
    def request(url, *args):
        if url == voice.TTS_URL:
            voice._set_error("auth", "HTTP 403")
            return None
        return original(url, *args)
    monkeypatch.setattr(voice, "_request", request)
    mismatch(demo)
    assert demo.backend.state["workflow_status"] == "HOLD"
    assert "VOICE_IO_FAILED" in demo.backend.state["reason"]
    assert audio[1] == ["record", "stt"] and len(demo.driver.calls) == 3
    assert any(r["event"] == "C_VOICE_FAILED" and r["result"]["phase"] == "TTS_QUESTION" for r in records(demo))


def test_stop_while_recording_ignores_late_audio_without_generating_design(create, monkeypatch):
    entered, release = Event(), Event()
    def record():
        voice._clear_error()
        entered.set()
        assert release.wait(2)
        return b"\x00\x01" * 160
    monkeypatch.setattr(voice, "record", record)
    window, demo, calls = create(start=False)
    window.buttons["START"].click()
    QApplication.instance().processEvents()
    try:
        assert entered.wait(1)
        window.buttons["STOP"].click()
        wait_for(demo, "STOPPED")
        assert demo.c_connection.active[2].is_set()
    finally:
        release.set()
    settled(demo)
    assert not calls and demo.backend.state["context"] is None
    assert demo.backend.state["workflow_status"] == "STOPPED"
    assert not demo.driver.calls[1:]
    assert any(r["event"] == "LATE_RESULT_IGNORED" for r in records(demo))


@pytest.mark.parametrize("mode,missing", [(None, None), ("offline", "OPENAI_API_KEY"),
                                         ("offline", "OPENAI_TTS_API_KEY")])
def test_voice_cli_requires_explicit_mode_and_both_keys_before_devices(monkeypatch, mode, missing):
    import os
    environment = dict(os.environ, C_DESIGN_USE_LLM="0", OPENAI_API_KEY="mock", OPENAI_TTS_API_KEY="mock")
    if missing:
        environment.pop(missing)
    arguments = [sys.executable, "-m", "app.abd_input_hmi", "--synthetic-b", "--c-voice"]
    if mode:
        arguments += ["--c-mode", mode]
    result = subprocess.run(arguments, cwd=ROOT, env=environment, capture_output=True, text=True)
    assert result.returncode == 2
    assert (missing or "--c-mode") in result.stderr


def test_stop_during_question_playback_keeps_same_question_and_never_opens_answer_mic(
        create, audio, monkeypatch, tmp_path):
    window, demo, _ = create()
    entered, release = Event(), Event()
    output = voice._sounddevice
    class BlockingOutput(output):
        def wait(self):
            entered.set()
            assert release.wait(2)
            super().wait()
    monkeypatch.setattr(voice, "_sounddevice", BlockingOutput)
    transfer(demo)
    demo.receive(dict(event="observe_wrong_color"))
    try:
        assert entered.wait(1)
        spoken = next(event[1] for event in audio[1] if isinstance(event, tuple))
        for _ in range(50):  # C 신호 뒤 큐에 넣는 snapshot의 실제 화면 반영까지 기다린다.
            QTest.qWait(5)
            if spoken in window.notice.toPlainText():
                break
        assert demo.backend.state["question"] == spoken
        assert spoken in window.notice.toPlainText()
        assert "AI 생성 음성" in window.notice.toPlainText()
        assert window.grab().save(str(tmp_path / "voice-question.png"))
        window.buttons["STOP"].click()
        wait_for(demo, "STOPPED")
    finally:
        release.set()
    settled(demo)
    assert audio[1].count("record") == 1
    assert demo.backend.state["current"]["current_revision"] == 1
    assert not demo.backend.state["context"]["confirmed_steps"]
    assert demo.backend.state["workflow_status"] == "STOPPED"


def test_current_changes_while_answer_recording_old_intent_does_not_replan(create, audio, monkeypatch):
    _, demo, calls = create()
    entered, release = Event(), Event()
    audio[0].append("2번")
    original = voice.record
    def record():
        entered.set()
        assert release.wait(2)
        return original()
    monkeypatch.setattr(voice, "record", record)
    transfer(demo)
    target = deepcopy(demo.backend._next_step()["after"])
    design = demo.backend.state["context"]["design"]
    demo.receive(dict(event="observe_wrong_color"))
    try:
        assert entered.wait(1)
        state = demo.backend.state
        identity = state["question_request"]["request_id"]
        case = dict(vision_result=dict(check_id=state["current_check"]["check_id"], observation_seq=0,
            status="OK", visible_blocks=[target], verified_regions=[demo.b.region(layer=i) for i in range(1, 5)],
            reason=None))
        assert demo.b.deliver_example(case, demo.backend.on_observation)
        demo.publish()
        assert demo.backend.state["current"]["current_revision"] == 2
    finally:
        release.set()
    settled(demo)
    assert len(calls) == 1 and len(demo.driver.calls) == 3
    assert demo.backend.state["context"]["design"] == design
    assert demo.backend.state["current"]["blocks"] == [target]
    assert any(r["event"] == "LATE_RESULT_IGNORED" and r["request_id"] == identity for r in records(demo))
