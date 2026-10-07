#!/usr/bin/env python3
"""Manual smoke test for app.c_design.voice (real mic/speaker + OpenAI).

Run from the repo root, one subcommand at a time:

    python3 scripts/c_voice_smoke.py stt
    python3 scripts/c_voice_smoke.py tts "문장"
    python3 scripts/c_voice_smoke.py questions
    python3 scripts/c_voice_smoke.py dialogue
    python3 scripts/c_voice_smoke.py echo

What each subcommand checks:
  stt       Records a few seconds from the real microphone, sends it to the
            real STT provider, and prints the recognized text (or "" for
            silence) plus how dialogue.parse_response interprets it.
  tts       Sends the given sentence to the real TTS provider and plays it
            on the real speaker.
  questions Plays the two Stage 2 open-ended Korean questions (Initial
            preference and Intervention) one after another and prints, per
            sentence, model / voice / whether instructions were sent, audio
            length and playback start/end clock times (voice._last_speak).
            Listening check for the user: natural Korean, calm tone, no cut-off
            at the end of a 2-3 sentence question.
  dialogue  Runs one full run_intervention() turn against a Mock CHAIR
            design with text_answers=None, i.e. voice mode: it speaks the
            question through the real speaker and listens on the real mic
            for your KEEP/REVISE answer, and also goes through the real
            LLM path if C_DESIGN_USE_LLM=1 is set.
  echo      One real speak() -> listen() sequence through voice.py's own code
            path: prints the TTS key variable used, TTS response size, WAV
            length and samplerate, sd.wait() elapsed time, the delay before
            listen() starts, and the listen() result compared with the
            spoken sentence (echo check). Nothing is written to disk.

All subcommands talk to the real OpenAI API (STT and/or TTS) and incur real
API costs; stt, dialogue and echo use the real microphone, and tts,
dialogue and echo use the real speaker. STT uses OPENAI_API_KEY and TTS uses
OPENAI_TTS_API_KEY (no fallback between them). This script never reads,
prints, or logs a key value -- it only reports whether each variable is
set. Supply the keys in the calling shell's environment for that one
command, not exported into your shell, so they do not linger in your
session or shell history:

    OPENAI_TTS_API_KEY="$(tr -d '[:space:]' < ~/c2_cobot2_API_key.txt)" \\
    OPENAI_API_KEY="$(tr -d '[:space:]' < ~/C2_OpenAi_API_Key.txt)" \\
        python3 scripts/c_voice_smoke.py echo

TTS model, voice and speaking-style instructions come from OPENAI_TTS_MODEL
(default gpt-4o-mini-tts), OPENAI_TTS_VOICE (default coral) and
OPENAI_TTS_INSTRUCTIONS (sent only to models other than tts-1 / tts-1-hd).
Compare voices by repeating `questions` with e.g. OPENAI_TTS_VOICE=marin or
OPENAI_TTS_VOICE=cedar in the same inline form; OPENAI_TTS_MODEL=tts-1 reproduces
the Stage 1 voice (no instructions). On failure the printed last_error is
"kind: HTTP code" (auth / model_access / bad_param / billing / rate_limit /
server / bad_response), never the response body.

Do not `export OPENAI_API_KEY=...` or `export OPENAI_TTS_API_KEY=...` -- that
leaves the key set for every later command in the shell. Prefer the inline
form above, once per run.

Add C_VOICE_DEBUG_DIR=/tmp/c_voice_debug to the same command to keep the exact WAV sent to STT
(latest_input.wav) and its gate statistics (latest_input.json); nothing is saved without it.
"""

import argparse
import difflib
import io
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.c_design import designer, dialogue, main, voice  # noqa: E402


def _print_key_and_models():
    for name in (voice.STT_KEY_ENV, voice.TTS_KEY_ENV):
        print(f"{name} is configured" if os.environ.get(name) else f"{name} is not set")
    stt_model = os.environ.get("OPENAI_STT_MODEL") or voice.DEFAULT_STT_MODEL
    tts_model = os.environ.get("OPENAI_TTS_MODEL") or voice.DEFAULT_TTS_MODEL
    print(f"STT model: {stt_model}")
    print(f"TTS model: {tts_model}")
    print(f"TTS voice: {os.environ.get('OPENAI_TTS_VOICE') or voice.DEFAULT_TTS_VOICE}")
    if tts_model in voice.TTS_MODELS_WITHOUT_INSTRUCTIONS:
        print("TTS instructions: not sent for this model")
    else:
        print(f"TTS instructions: {os.environ.get('OPENAI_TTS_INSTRUCTIONS') or voice.DEFAULT_TTS_INSTRUCTIONS}")


def run_stt(_args):
    _print_key_and_models()
    # the prompt appears only after warm-up and noise calibration, so speech does not leak into the calibration
    text = voice.listen(on_ready=lambda: print("Speak now (up to ~8 s)...", flush=True))
    if text is None:
        print("listen failed: " + str(voice.last_error()))
        return 1
    if text == "":
        print("(silence: no speech detected, STT not called)")
        return 0
    print("recognized: " + text)
    print("parse_response: " + str(dialogue.parse_response(text)))
    return 0


def run_tts(args):
    _print_key_and_models()
    voice.speak(args.sentence)
    print("speak done")
    error = voice.last_error()
    if error:
        print(str(error))
        return 1
    return 0


QUESTION_SENTENCES = (
    "혹시 생각했거나 만들고 싶은 의자가 있어?",
    "Design과 다르게 놓인 부분이 있는데 의도된 행동인가요?",
)


def run_questions(_args):
    _print_key_and_models()
    failed = False
    for sentence in QUESTION_SENTENCES:
        print("sentence: " + sentence)
        voice.speak(sentence)
        info = voice._last_speak or {}
        print(f"  model {info.get('model')}, voice {info.get('voice')}, instructions sent {info.get('instructions_sent')}, "
              f"audio {info.get('audio_seconds')} s at {info.get('samplerate')} Hz, "
              f"play {info.get('play_started_at')} -> {info.get('play_ended_at')}")
        error = voice.last_error()
        if error:
            print("  speak failed: " + str(error))
            failed = True
    return 1 if failed else 0


def run_dialogue(_args):
    _print_key_and_models()
    design = designer.build_initial_design("CHAIR")["design"]
    legs = [b for b in design["blocks"] if b["layer"] == 1]
    back_leg = max(legs, key=lambda b: b["y"])
    moved_leg = dict(back_leg, y=back_leg["y"] + 1)
    current = [moved_leg if b is back_leg else dict(b) for b in design["blocks"]]
    differences = [{"expected": back_leg, "actual": moved_leg}]

    use_llm = os.environ.get("C_DESIGN_USE_LLM") == "1"
    print("C_DESIGN_USE_LLM forcing LLM: " + str(use_llm))

    result = main.run_intervention(
        design, current, differences, text_answers=None, on_question=lambda q: print("Q:", q)
    )
    print("status: " + str(result["status"]))
    print("hri_result: " + str(result["hri_result"]))
    error = result["error"]
    if error:
        print("error code: " + str(error.get("code")))
        print("error message: " + str(error.get("message")))
    else:
        print("error: none")
    print("questions: " + str(len(result["questions"])))
    if result["design"] is not None:
        print("design_version: " + str(result["design"]["design_version"]))
    return 0 if result["status"] == "OK" else 1


ECHO_SENTENCE = "지금 놓인 블록을 확인했습니다. 1번 또는 2번으로 말씀해 주세요."


def run_echo(_args):
    """speak() → listen()을 voice.py 코드 경로 그대로 1회 실행하고 관측값만 출력한다.

    voice._request와 voice._sounddevice를 감싸 key 변수 이름·응답 크기·재생 시간을 기록할 뿐
    동작은 바꾸지 않는다. 오디오는 메모리에만 있고 파일로 저장하지 않는다.
    """
    _print_key_and_models()
    seen = {"requests": []}
    real_request = voice._request
    real_sounddevice = voice._sounddevice

    def traced_request(url, data, content_type, key_env):
        response = real_request(url, data, content_type, key_env)
        seen["requests"].append({"url": url, "key_env": key_env, "bytes": None if response is None else len(response)})
        if url == voice.TTS_URL and response is not None:
            with wave.open(io.BytesIO(response), "rb") as wav_file:
                rate = wav_file.getframerate()
                frame_bytes = wav_file.getsampwidth() * wav_file.getnchannels()
                n_frames = len(wav_file.readframes(wav_file.getnframes())) // frame_bytes
            seen["tts_rate"] = rate
            seen["tts_seconds"] = n_frames / rate
        return response

    class TracedSD:
        def __init__(self, sd):
            self._sd = sd

        def __getattr__(self, name):
            return getattr(self._sd, name)

        def play(self, frames, samplerate):
            seen["play_start"] = time.monotonic()
            return self._sd.play(frames, samplerate)

        def wait(self):
            result = self._sd.wait()
            seen["wait_return"] = time.monotonic()
            return result

    voice._request = traced_request
    voice._sounddevice = lambda: TracedSD(real_sounddevice())
    try:
        print("sentence: " + ECHO_SENTENCE)
        voice.speak(ECHO_SENTENCE)
        speak_return = time.monotonic()
        speak_error = voice.last_error()
        tts = [r for r in seen["requests"] if r["url"] == voice.TTS_URL]
        for r in tts:
            print(f"TTS request: key env used: {r['key_env']}, response bytes: {r['bytes']}")
        if speak_error or "wait_return" not in seen:
            print("speak failed: " + str(speak_error))
            return 1
        print(f"WAV: {seen['tts_seconds']:.2f} s at {seen['tts_rate']} Hz")
        print(f"play -> sd.wait() returned after {seen['wait_return'] - seen['play_start']:.2f} s")
        print(f"sd.wait() return -> speak() return (POST_SPEAK_DELAY {voice.POST_SPEAK_DELAY} s): "
              f"{speak_return - seen['wait_return']:.2f} s")

        listen_start = time.monotonic()
        print(f"listen() started {listen_start - seen['wait_return']:.2f} s after playback ended")
        text = voice.listen()
        stt = [r for r in seen["requests"] if r["url"] == voice.STT_URL]
        for r in stt:
            print(f"STT request: key env used: {r['key_env']}, response bytes: {r['bytes']}")
    finally:
        voice._request = real_request
        voice._sounddevice = real_sounddevice

    if text is None:
        print("listen failed: " + str(voice.last_error()))
        return 1
    if text == "":
        print("listen result: \"\" (no sound above threshold, STT not called) -> no echo")
        return 0
    ratio = difflib.SequenceMatcher(None, text, ECHO_SENTENCE).ratio()
    print("listen result: " + text)
    print(f"similarity to spoken sentence: {ratio:.2f}")
    return 0


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("stt", help="record and transcribe one utterance from the real mic")

    tts_parser = subparsers.add_parser("tts", help="speak one sentence on the real speaker")
    tts_parser.add_argument("sentence", help="Korean sentence to speak")
    subparsers.add_parser("questions", help="speak the two Stage 2 open-ended Korean questions")

    subparsers.add_parser("dialogue", help="run one run_intervention turn (voice mode, real mic/speaker)")
    subparsers.add_parser("echo", help="speak one fixed sentence, then listen once (echo check)")

    args = parser.parse_args()
    if args.command == "stt":
        return run_stt(args)
    if args.command == "tts":
        return run_tts(args)
    if args.command == "questions":
        return run_questions(args)
    if args.command == "echo":
        return run_echo(args)
    return run_dialogue(args)


if __name__ == "__main__":
    sys.exit(main_cli())
