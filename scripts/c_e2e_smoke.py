#!/usr/bin/env python3
"""C-only end-to-end smoke test: real mic -> STT -> dialogue -> real LLM -> validator -> TTS.

Run from the repo root, one subcommand at a time. Each one needs a person at the mic:

    python3 scripts/c_e2e_smoke.py initial
    python3 scripts/c_e2e_smoke.py revise --scenario color
    python3 scripts/c_e2e_smoke.py revise --scenario leg
    python3 scripts/c_e2e_smoke.py revise --scenario leg --force-reject

What each subcommand checks:
  initial           main.create_initial_design(text=None): you say the goal ("의자 만들어줘"),
                    STT -> dialogue.parse_goal -> LLM -> validator. Saves the envelope to
                    /tmp/c_design_initial_result.json.
  revise --scenario color
                    main.run_intervention(text_answers=None): the first layer-2 block's color is
                    swapped (yellow <-> blue) in Current. The question is spoken through TTS; you
                    answer "2번" (REVISE) -> LLM Revised Design. Prints whether every Current block
                    is preserved. Saves to /tmp/c_design_revised_color_result.json.
  revise --scenario leg
                    Same, with the back leg moved y+1, through the real LLM. The outcome is not
                    deterministic: a valid Revised Design (REVISE, Current preserved), or 6
                    rejected candidates -> escalation question -> you answer "1번" -> KEEP.
                    Saves to /tmp/c_design_revised_leg_result.json.
  revise --scenario leg --force-reject
                    Deterministic escalation test (TEST 3). Inside this script process only,
                    llm.generate_revised_design is replaced by a fake that returns Current with
                    the moved block put back at its original position, so validator rejects every
                    candidate with assembled_not_preserved. No LLM API request is made. Expected:
                    you answer "2번" -> REVISE -> 6 rejections -> escalation question (real TTS)
                    -> you answer "1번" -> MOVE_BACK -> OK / KEEP, the input Design unchanged,
                    error null. Saves to /tmp/c_design_escalation_result.json.

  --design-json PATH  (revise only) use the "design" of a saved envelope (e.g. the initial
                      result file) instead of the Mock CHAIR.

This E2E assumes the real LLM: set C_DESIGN_USE_LLM=1 (a warning is printed otherwise).
STT uses OPENAI_API_KEY and TTS uses OPENAI_TTS_API_KEY. This script never prints a key value,
an Authorization header or a response body; it only reports whether each variable is set.
Supply the keys for that one command, not exported into your shell:

    OPENAI_TTS_API_KEY="$(tr -d '[:space:]' < ~/c2_cobot2_API_key.txt)" \\
    OPENAI_API_KEY="$(tr -d '[:space:]' < ~/C2_OpenAi_API_Key.txt)" \\
    C_DESIGN_USE_LLM=1 OPENAI_MODEL=gpt-4o \\
        python3 scripts/c_e2e_smoke.py initial

Do not `export` either key. Only the result envelope is written (to /tmp, never inside the
repository). Audio stays in memory and is never saved.
"""

import argparse
import copy
import io
import json
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.c_design import designer, dialogue, llm, main, validator, voice  # noqa: E402

RESULT_PATHS = {
    "initial": "/tmp/c_design_initial_result.json",
    "color": "/tmp/c_design_revised_color_result.json",
    "leg": "/tmp/c_design_revised_leg_result.json",
    "escalation": "/tmp/c_design_escalation_result.json",
}


class Observer:
    """공개 함수가 부르는 voice / dialogue / llm / validator 함수를 감싸 기록만 한다(동작 변경 없음)."""

    def __init__(self, hint, escalation_hint=None, escalation_question=None):
        self.hint = hint
        self.escalation_hint = escalation_hint
        self.escalation_question = escalation_question
        self.last_question = None
        self.prompted_for = object()
        self.llm_calls = 0
        self.llm_api_requests = 0
        self.llm_label = "LLM call"
        self.log = []
        self.tts = {}
        self._saved = []

    def _wrap(self, module, name, make):
        original = getattr(module, name)
        self._saved.append((module, name, original))
        setattr(module, name, make(original))

    def install(self):
        self._wrap(voice, "listen", self._listen)
        self._wrap(voice, "speak", self._speak)
        self._wrap(voice, "_request", self._request)
        self._wrap(voice, "_sounddevice", self._sounddevice)
        for name in ("parse_goal", "parse_response", "parse_escalation_response"):
            self._wrap(dialogue, name, self._parser(name))
        for name in ("generate_initial_design", "generate_revised_design"):
            self._wrap(llm, name, self._llm(name))
        for name in ("validate_design", "validate_revised"):
            self._wrap(validator, name, self._validator(name))
        self._wrap(llm, "_post_json", self._api)

    def _api(self, original):
        def post_json(*args, **kwargs):
            # Chat Completions로 실제 나가는 요청 수(가짜 생성기 경로에서는 0이어야 한다).
            self.llm_api_requests += 1
            return original(*args, **kwargs)
        return post_json

    def restore(self):
        for module, name, original in reversed(self._saved):
            setattr(module, name, original)
        self._saved = []

    def _listen(self, original):
        def listen():
            if self.prompted_for is not self.last_question:
                self.prompted_for = self.last_question
                hint = self.hint
                if self.escalation_question is not None and self.last_question == self.escalation_question:
                    hint = self.escalation_hint
                print(f"\n>>> 지금 말씀하세요: {hint}")
            text = original()
            if text is None:
                print(f"STT: 실패 ({voice.last_error()})")
            elif text == "":
                print("STT: (침묵, STT 호출 없음) 계속 기다립니다")
            else:
                print(f"STT: {text!r}")
            return text
        return listen

    def _speak(self, original):
        def speak(sentence):
            self.last_question = sentence
            self.tts = {}
            original(sentence)
            error = voice.last_error()
            if error:
                print(f"TTS: 실패 ({error})")
            else:
                print(f"TTS: 성공, {self.tts.get('bytes')} bytes, WAV {self.tts.get('seconds', 0):.2f} s, "
                      f"sd.wait() 반환까지 {self.tts.get('played', 0):.2f} s")
        return speak

    def _request(self, original):
        def request(url, data, content_type, key_env):
            response = original(url, data, content_type, key_env)
            if url == voice.TTS_URL and response is not None:
                with wave.open(io.BytesIO(response), "rb") as wav_file:
                    rate = wav_file.getframerate()
                    frame_bytes = wav_file.getsampwidth() * wav_file.getnchannels()
                    frames = len(wav_file.readframes(wav_file.getnframes())) // frame_bytes
                self.tts.update(bytes=len(response), seconds=frames / rate)
            return response
        return request

    def _sounddevice(self, original):
        observer = self

        class TimedPlayback:
            def __init__(self, sd):
                self._sd = sd

            def __getattr__(self, name):
                return getattr(self._sd, name)

            def play(self, frames, samplerate):
                observer.tts["play_start"] = time.monotonic()
                return self._sd.play(frames, samplerate)

            def wait(self):
                result = self._sd.wait()
                observer.tts["played"] = time.monotonic() - observer.tts.get("play_start", time.monotonic())
                return result

        return lambda: TimedPlayback(original())

    def _parser(self, name):
        def make(original):
            def parse(text, *args, **kwargs):
                result = original(text, *args, **kwargs)
                print(f"dialogue.{name}({text!r}) -> {result!r}")
                return result
            return parse
        return make

    def _llm(self, name):
        def make(original):
            def generate(*args, **kwargs):
                self.llm_calls += 1
                started = time.monotonic()
                candidate = original(*args, **kwargs)
                outcome = "llm_error " + str(candidate["llm_error"]["kind"]) if isinstance(candidate, dict) and "llm_error" in candidate else "candidate"
                print(f"{self.llm_label} #{self.llm_calls} ({name}): {outcome}, {time.monotonic() - started:.1f} s")
                return candidate
            return generate
        return make

    def _validator(self, name):
        def make(original):
            def validate(*args, **kwargs):
                reasons = original(*args, **kwargs)
                rules = sorted({reason["rule"] for reason in reasons})
                if self.llm_calls:
                    print(f"  validator.{name} after {self.llm_label} #{self.llm_calls}: {rules or 'PASS'}")
                self.log.append({"llm_call": self.llm_calls, "check": name, "rules": rules})
                return reasons
            return validate
        return make


def _print_environment():
    for name in (voice.STT_KEY_ENV, voice.TTS_KEY_ENV):
        print(f"{name} is configured" if os.environ.get(name) else f"{name} is not set")
    if os.environ.get("C_DESIGN_USE_LLM") != "1":
        print("WARNING: C_DESIGN_USE_LLM is not 1 -> the Mock designer is used, not the real LLM. "
              "This E2E assumes C_DESIGN_USE_LLM=1.")
    print(f"OPENAI_MODEL: {os.environ.get('OPENAI_MODEL') or llm.DEFAULT_MODEL + ' (default)'}")
    print(f"STT model: {os.environ.get('OPENAI_STT_MODEL') or voice.DEFAULT_STT_MODEL}, "
          f"TTS model: {os.environ.get('OPENAI_TTS_MODEL') or voice.DEFAULT_TTS_MODEL}")


def _save(result, key):
    path = RESULT_PATHS[key]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(f"envelope saved: {path}")


def _print_envelope(result, observer, elapsed):
    print("\n=== result ===")
    print(f"status: {result['status']}")
    print(f"hri_result: {result['hri_result']}")
    print(f"error: {result['error']['code'] + ' - ' + result['error']['message'] if result['error'] else 'none'}")
    if result["design"] is not None:
        print(f"design_version: {result['design']['design_version']}, blocks: {len(result['design']['blocks'])}")
    print(f"questions asked: {len(result['questions'])}")
    print(f"{observer.llm_label} count: {observer.llm_calls}, LLM API requests: {observer.llm_api_requests}")
    print(f"elapsed: {elapsed:.1f} s")


def run_initial(_args):
    _print_environment()
    # create_initial_design은 listen()을 한 번만 부른다: 시작 대기(voice.WAIT_SECONDS) 안에 말하지 않으면
    # 침묵("")이 parse_goal로 가서 UNSUPPORTED_OBJECT가 된다(Intervention과 달리 계속 기다리지 않음).
    observer = Observer(hint=f'"의자 만들어줘" ({voice.WAIT_SECONDS:.0f}초 안에 말하기 시작)')
    observer.last_question = "goal"
    observer.install()
    started = time.monotonic()
    try:
        result = main.create_initial_design(text=None)
    finally:
        observer.restore()
    _print_envelope(result, observer, time.monotonic() - started)
    if result["design"] is not None:
        print(f"validator.validate_design(final) rules: {sorted({r['rule'] for r in validator.validate_design(result['design'])}) or 'PASS'}")
    _save(result, "initial")
    return 0 if result["status"] == "OK" else 1


def _load_design(path):
    if path is None:
        return designer.build_initial_design("CHAIR")["design"]
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    design = data.get("design", data) if isinstance(data, dict) else None
    if not isinstance(design, dict) or "blocks" not in design:
        raise SystemExit(f"{path}: no design with blocks (status {data.get('status') if isinstance(data, dict) else '?'})")
    return design


def _color_scenario(design):
    target = next(block for block in design["blocks"] if block["layer"] == 2)
    changed = dict(target, color="blue" if target["color"] == "yellow" else "yellow")
    current = [dict(changed) if block is target else dict(block) for block in design["blocks"]]
    return current, [{"expected": dict(target), "actual": changed}]


def _leg_scenario(design):
    legs = [block for block in design["blocks"] if block["layer"] == 1]
    back_leg = max(legs, key=lambda block: block["y"])
    moved = dict(back_leg, y=back_leg["y"] + 1)
    current = [dict(moved) if block is back_leg else dict(block) for block in design["blocks"]]
    return current, [{"expected": dict(back_leg), "actual": moved}]


def _same_design(a, b):
    """design_version과 blocks multiset(여섯 값)이 같은지."""
    def key(block):
        return tuple(block[field] for field in validator.BLOCK_FIELDS)
    return (
        a is not None and b is not None and a["design_version"] == b["design_version"]
        and sorted(map(key, a["blocks"])) == sorted(map(key, b["blocks"]))
    )


def _force_reject_generator(differences):
    """항상 assembled_not_preserved로 거부되는 후보: Current의 옮겨진 블록을 원래 위치로 되돌린다."""
    moved, original = differences[0]["actual"], differences[0]["expected"]

    def generate_revised_design(design, current, differences, reasons=None, should_stop=None):
        blocks = [dict(original) if block == moved else dict(block) for block in current]
        return {"blocks": blocks}
    return generate_revised_design


def _current_preserved(result, current):
    # validate_revised의 후보에는 design_version을 넣지 않는다(unknown_key 방지).
    lost = validator.validate_revised({"blocks": result["design"]["blocks"]}, current)
    print(f"Current preserved: {lost == []} {sorted({r['rule'] for r in lost}) if lost else ''}")
    return lost == []


def run_revise(args):
    _print_environment()
    design = _load_design(args.design_json)
    original = copy.deepcopy(design)
    build = _color_scenario if args.scenario == "color" else _leg_scenario
    current, differences = build(design)
    print(f"scenario: {args.scenario}{' --force-reject' if args.force_reject else ''}, "
          f"input design_version {design['design_version']}, {len(design['blocks'])} blocks")
    print(f"difference: {differences[0]['expected']} -> {differences[0]['actual']}")

    observer = Observer(
        hint='"2번" (재설계)',
        escalation_hint='"1번" (블록을 원래 자리로 되돌림)',
        escalation_question=dialogue.escalation_question(differences),
    )
    real_generate = llm.generate_revised_design
    if args.force_reject:
        # 이 스크립트 프로세스 안에서만 바꿔치기한다(production 코드·설정은 그대로). 실행 후 원복.
        llm.generate_revised_design = _force_reject_generator(differences)
        observer.llm_label = "forced-reject fake call (no API)"
        print("force-reject: llm.generate_revised_design -> fake candidate (moved block put back), "
              "expected rejection rule: assembled_not_preserved")
    observer.install()
    started = time.monotonic()
    try:
        result = main.run_intervention(
            design, current, differences, text_answers=None, on_question=lambda q: print(f"\nQ: {q}")
        )
    finally:
        observer.restore()
        llm.generate_revised_design = real_generate
    _print_envelope(result, observer, time.monotonic() - started)

    if args.scenario == "color":
        preserved = result["design"] is not None and _current_preserved(result, current)
        _save(result, "color")
        return 0 if result["status"] == "OK" and result["hri_result"] == dialogue.REVISE and preserved else 1

    rejections = [entry["rules"] for entry in observer.log if entry["check"] == "validate_revised" and entry["rules"]]
    print(f"rejected candidates: {len(rejections)}")
    for number, rules in enumerate(rejections, 1):
        print(f"  attempt {number}: {rules}")
    asked_escalation = observer.escalation_question in result["questions"]
    print(f"escalation question asked: {asked_escalation}")
    if asked_escalation:
        print(f"escalation question:\n{observer.escalation_question}")
    identical = _same_design(result["design"], original)
    print(f"returned design identical to input (design_version + blocks multiset): {identical}")

    keep_ok = (
        result["status"] == "OK" and result["hri_result"] == dialogue.KEEP
        and identical and result["error"] is None
    )
    if args.force_reject:
        _save(result, "escalation")
        return 0 if keep_ok and asked_escalation and observer.llm_api_requests == 0 else 1
    revise_ok = (
        result["status"] == "OK" and result["hri_result"] == dialogue.REVISE
        and result["design"] is not None and _current_preserved(result, current)
    )
    _save(result, "leg")
    return 0 if keep_ok or revise_ok else 1


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initial", help="speak the goal; real STT + LLM Initial Design")
    revise = subparsers.add_parser("revise", help="voice-mode run_intervention with a scripted Current")
    revise.add_argument("--scenario", choices=("color", "leg"), required=True)
    revise.add_argument("--design-json", help="envelope or design JSON to use instead of the Mock CHAIR")
    revise.add_argument(
        "--force-reject", action="store_true",
        help="leg only: replace the Revised generator with a fake that is always rejected (escalation test)",
    )
    args = parser.parse_args()
    if args.command == "initial":
        return run_initial(args)
    if args.force_reject and args.scenario != "leg":
        parser.error("--force-reject is only for --scenario leg")
    return run_revise(args)

if __name__ == "__main__":
    sys.exit(main_cli())
