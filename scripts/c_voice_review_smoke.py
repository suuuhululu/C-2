#!/usr/bin/env python3
"""Preview 검토 HRI smoke (Stage 3 Wave 1, 시험용·수동 실행). production 코드는 바꾸지 않는다.

D가 Candidate Design의 Preview 표시를 끝냈다고 가정하고 main.review_design_candidate를 한 번 실행한다.
후보는 Mock Initial(기본) 또는 --candidate로 준 JSON(저장된 v1.json·v2.json의 envelope 또는 Design 자체)이다.

    python3 scripts/c_voice_review_smoke.py --answers "좋아 이걸로 하자"                 # 텍스트 모드(마이크·스피커 없음)
    python3 scripts/c_voice_review_smoke.py --kind revised --answers "음..." "등받이를 더 높게"
    env C_DESIGN_USE_LLM=1 OPENAI_API_KEY=… OPENAI_LLM_API_KEY=… OPENAI_TTS_API_KEY=… \\
        python3 scripts/c_voice_review_smoke.py --candidate ~/c_voice_e2e_c_only/round01/v1.json   # 음성 모드

로그: [C][QUESTION] 질문, [C][STT_RAW] 음성 인식 원문, [C][<STAGE>] 진행 이벤트(HRI_INTERPRET·REVIEW_ACK 포함),
마지막에 status·hri_result·design_metadata.review. 텍스트 모드에서는 음성을 내지 않는다. Mock 모드(C_DESIGN_USE_LLM ≠ 1)는
규칙 해석만 쓰고 LLM을 부르지 않는다. 키는 환경 변수로만 받으며 값은 출력하지 않는다(설정 여부만).
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.c_design import designer, llm, main, voice  # noqa: E402


def _now():
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


def load_candidate(path):
    """Design 또는 envelope({"design": …}·{"envelope": {"design": …}})에서 (design, design_metadata)를 꺼낸다."""
    if path is None:
        return designer.build_initial_design("CHAIR", delay=0)["design"], {"source": "MOCK"}
    with open(os.path.expanduser(path), encoding="utf-8") as handle:
        data = json.load(handle)
    if "envelope" in data:
        data = data["envelope"]
    if "design" in data and "blocks" not in data:
        return data["design"], data.get("design_metadata") or {}
    return data, {}


def install_listen_log():
    original = voice.listen

    def listen(on_ready=None, mode="short", beep=False):
        def ready():
            print('\n>>> 지금 말씀하세요: "이 디자인이 어떠신지 자유롭게(예: 좋아 이걸로 하자 / 등받이를 더 높게 / 그만할래)"',
                  flush=True)
            if on_ready is not None:
                on_ready()
        text = original(on_ready=ready, mode=mode, beep=beep)
        print(f'[C][STT_RAW] {_now()} "{text if text is not None else ""}"'
              + (f" (last_error {voice.last_error()})" if text in (None, "") else ""), flush=True)
        return text

    voice.listen = listen


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", help="후보 JSON 경로(없으면 Mock Initial)")
    parser.add_argument("--kind", choices=main.REVIEW_KINDS, default="initial")
    parser.add_argument("--answers", nargs="*", help="텍스트 모드 답변(주면 마이크·스피커를 쓰지 않음)")
    args = parser.parse_args()

    use_llm = os.environ.get("C_DESIGN_USE_LLM") == "1"
    voice_mode = args.answers is None
    needed = ([llm.LLM_KEY_ENV] if use_llm else []) + ([voice.STT_KEY_ENV, voice.TTS_KEY_ENV] if voice_mode and use_llm else [])
    for name in needed:
        print(f"{name} {'is configured' if os.environ.get(name) else 'is not set'}", flush=True)
    print(f"mode: {'LLM' if use_llm else 'Mock(규칙만)'} · {'음성' if voice_mode else '텍스트'} · kind {args.kind}", flush=True)

    design, metadata = load_candidate(args.candidate)
    print(f"candidate: design_version {design.get('design_version')} · blocks {len(design.get('blocks', []))} "
          "(Preview 표시 완료를 가정)", flush=True)
    if voice_mode:
        install_listen_log()
        if use_llm:
            voice.prewarm()

    def on_progress(event):
        message = f'"{event["message"]}"' if event["stage"] == "REVIEW_ACK" else event["message"]
        print(f"[C][{event['stage']}] {event['at']} {message}", flush=True)

    started = time.monotonic()
    result = main.review_design_candidate(
        design, kind=args.kind, design_metadata=metadata, text_answers=args.answers,
        on_question=lambda q: print(f"[C][QUESTION] {_now()} {q}", flush=True), on_progress=on_progress,
    )
    print(f"\nstatus {result['status']} · hri_result {result['hri_result']} · error {result['error']} · "
          f"{time.monotonic() - started:.1f}s", flush=True)
    print("review: " + json.dumps((result["design_metadata"] or {}).get("review"), ensure_ascii=False), flush=True)
    print(f"design unchanged: {result['design'] == design}", flush=True)
    return 0 if result["status"] in ("OK", "CANCELLED") else 1


if __name__ == "__main__":
    sys.exit(main_cli())
