"""C 단독 음성 E2E runner (기본 5 Round, 시험용, production 코드 수정 없음). A planner·Backend·Robot·D contracts 미사용.

흐름(Round마다): production main.create_initial_design(text=None): C가 먼저 TTS 인사("안녕하세요. 오늘 어떤 걸 만들고
싶으세요?") → beep → 자유 발화(예: "사과 같은 의자", "벤치처럼 길고 넓은 의자", "아무거나") → whisper STT → 한 문장 해석
(mode/family/style_hint·concept, 필요할 때만 follow-up 1회) → v1 → C validator → v1 화면(PNG) → [Enter]
→ 시험용 Current/Difference(A planner 없이: v1의 layer-1 블록 전부 중 하나를 설계 중심 바깥으로 1~3 stud 옮김,
판 안·겹침 없음·validator.check_intervention_input 통과) → production main.run_intervention(..., text_answers=None):
TTS 질문 → beep → 자유 발화(예: "일부러 그렇게 놨어요", "제가 잘못 놨어요") → KEEP/REVISE/UNCLEAR → v2 → validator·
Current preserved(multiset)·judge → [v1 | Current+Difference | v2] 한 화면(PNG) → Round 요약.
v1·v2 화면은 생성 직후 HMI 스타일(app/hmi_board.BoardView 투영 + 완성 확대 + 층별 평면 + metadata, scripts/c_design_hmi_render.py)로
즉시 창에 띄운다(사후 rerender 불필요; 필요하면 python3 scripts/c_design_hmi_render.py --out DIR로 다시 그릴 수 있다).
말할 차례마다 ">>> 지금 말씀하세요" 안내를 낸다. Round마다 roundNN/v1.png·screen.png·metadata.json·transcript.json,
끝에 summary.md를 남긴다.

production 경로 그대로: main, voice.listen/speak(자유 발화 모드·beep는 main이 정함), llm, validator.
시험용으로만 덧붙인 것: voice.listen/speak 래핑(안내 출력·STT 기록, 인자는 그대로 전달), HMI 스타일 표시 전용 렌더러
(c_design_hmi_render: BoardView 재사용, Stage 2 어휘는 프로세스 안 표시 패치), 시험용 Current/Difference 생성.
A/D 통합 시험은 scripts/c_voice_10round_e2e.py를 쓴다(Stage 2 어휘는 A 반영 전 INVALID 가능).

실행(키 값은 명령마다 파일에서 주입, 출력·기록하지 않음):
  cd ~/adaptive_coassembly/C-2 && env C_DESIGN_USE_LLM=1 OPENAI_MODEL=gpt-6.1-sol \
    OPENAI_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" OPENAI_LLM_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" \
    OPENAI_TTS_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" python3 scripts/c_voice_e2e_c_only.py
옵션: --rounds N(기본 5) --start K(기본 1, 이어서 진행) --out DIR(기본 ~/c_voice_e2e_c_only) --summary(집계만)
      --debug-audio(각 listen/TTS의 시각·보정·게이트·Whisper 원문·no_speech_prob·avg_logprob를 터미널에 출력)
결과 넘겨보기: python3 scripts/c_voice_e2e_c_only_gallery.py

진행 로그(Stage 2 Wave 4c·4e): listen마다 [C][STT_RAW] "…", main의 on_progress 이벤트를 "[C][STAGE] HH:MM:SS.mmm message"로 출력하고
(ACK는 문장 인용, Intervention 해석은 [C][HRI_INTERPRET] decision=… source=… reason=… style_hint=…)
metadata의 v1/v2 "progress"에 남긴다. 첫 확인(ack) TTS의 실제 재생 시작 시각(voice._last_speak)과 마지막 listen 종료 시각을
transcript "ack_tts"에 남겨 첫 응답 latency를 잴 수 있게 한다.
"""
import argparse
import inspect
import json
import os
import select
import sys
import time
from collections import Counter
from copy import deepcopy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # c_design_hmi_render(같은 scripts/ 폴더)

from app.c_design import dialogue, llm, main, validator, voice  # noqa: E402

FIELDS = validator.BLOCK_FIELDS
BOARD_MAX = validator.BOARD_RANGE[-1]
INITIAL_PHRASE = "오늘 만들고 싶은 것을 자유롭게(예: 사과 같은 의자 / 벤치처럼 길고 넓은 의자 / 아무거나)"
INITIAL_AGAIN_PHRASE = "다시 한 번 자유롭게 말씀해 주세요"  # 침묵 재질문·follow-up 답
INTERVENTION_PHRASE = "자유롭게 답하세요(예: 일부러 그렇게 놨어요 / 제가 잘못 놨어요)"
TOTAL = {"rounds": 5}  # 안내 출력용(main_cli에서 설정)
DEBUG = {"audio": False}  # --debug-audio
SETTLE_SECONDS = 1.0  # Round 전환(Enter) 직후 발화·환경 변화가 보정에 섞이지 않게 두는 짧은 간격
SHIFT_MAGNITUDES = (1, 2, 3)  # 시험용 Difference: 바깥쪽으로 옮기는 stud 수


# ---------------------------------------------------------------- 시험용 Current/Difference (A planner 없음)
def _centre(blocks):
    cells = [c for b in blocks for c in validator.footprint(b)]
    return sum(x for x, _ in cells) / len(cells), sum(y for _, y in cells) / len(cells)


def _sign(v):
    return (v > 0) - (v < 0)


def _outward_shifts(block, centre, k):
    """설계 중심에서 멀어지는 방향의 (dx, dy) 후보. 주축(중심에서 더 먼 축) 먼저, 크기 순서는 Round마다 돌린다."""
    bx, by = _centre([block])
    ex, ey = bx - centre[0], by - centre[1]
    axes = []
    if _sign(ex):
        axes.append((_sign(ex), 0))
    if _sign(ey):
        axes.append((0, _sign(ey)))
    if not axes:  # 중심 위 블록: 네 방향 모두
        axes = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    elif abs(ey) > abs(ex):
        axes.reverse()
    r = (k - 1) % len(SHIFT_MAGNITUDES)
    mags = SHIFT_MAGNITUDES[r:] + SHIFT_MAGNITUDES[:r]
    return [(ux * m, uy * m) for m in mags for ux, uy in axes]


def _on_board_without_overlap(blocks):
    seen = set()
    for b in blocks:
        for x, y in validator.footprint(b):
            if not (0 <= x <= BOARD_MAX and 0 <= y <= BOARD_MAX) or (b["layer"], x, y) in seen:
                return False
            seen.add((b["layer"], x, y))
    return True


def make_scenario(design, k):
    """Current = v1의 layer-1 블록 전부, 그중 하나만 바깥으로 옮긴다. 블록 순서·이동 크기를 Round k마다 돌려 결정론적으로
    첫 유효 배치를 고른다. 이동만으로 없으면 1x2x1/2x3x1 회전(0↔90)도 허용한다. 없으면 None."""
    base = [{f: b[f] for f in FIELDS} for b in design["blocks"] if b["layer"] == 1]
    if not base:
        return None
    centre = _centre(design["blocks"])
    start = (k - 1) % len(base)
    order = [(start + i) % len(base) for i in range(len(base))]
    for allow_rotate in (False, True):
        for idx in order:
            target = base[idx]
            rots = [target["orientation_deg"]]
            if allow_rotate:
                if target["brick_type"] not in ("1x2x1", "2x3x1"):
                    continue
                rots = [90 if target["orientation_deg"] == 0 else 0]
            for rot in rots:
                for dx, dy in _outward_shifts(target, centre, k):
                    moved = dict(target, x=target["x"] + dx, y=target["y"] + dy, orientation_deg=rot)
                    current = [moved if i == idx else b for i, b in enumerate(base)]
                    diffs = [{"expected": target, "actual": moved}]
                    if not _on_board_without_overlap(current) or validator.check_intervention_input(design, current, diffs):
                        continue
                    return {"index": idx, "dx": dx, "dy": dy, "rotated": rot != target["orientation_deg"],
                            "expected": target, "actual": moved, "current": current, "differences": diffs}
    return None


# ---------------------------------------------------------------- 화면(스크립트 안 QPainter 렌더러, 위에서 본 판)
from c_design_hmi_render import compose_v1, compose_v2, counts_line  # noqa: E402  표시 전용(HMI 스타일, A/D 미호출)


class Viewer:
    """저장한 화면을 비차단 창에 띄운다(Enter 대기 중 processEvents로 갱신)."""

    def __init__(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QLabel
        self.label = QLabel(); self.label.setAlignment(Qt.AlignCenter); self.label.resize(1600, 1000)

    def show(self, app, img, title):
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QImage, QPixmap
        data = img.convert("RGB").tobytes("raw", "RGB")
        pm = QPixmap.fromImage(QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy())
        screen = app.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            if pm.width() > avail.width() * 0.95 or pm.height() > avail.height() * 0.9:
                pm = pm.scaled(int(avail.width() * 0.95), int(avail.height() * 0.9), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(pm); self.label.resize(pm.size()); self.label.setWindowTitle(title)
        self.label.show(); self.label.raise_()
        for _ in range(5):
            app.processEvents(); time.sleep(0.05)

    def close(self):
        self.label.close()


def _wait_enter(app, prompt):
    """터미널 Enter를 기다리는 동안 Qt 창은 계속 그린다. 입력 줄(소문자)을 돌려준다."""
    print(prompt, flush=True)
    while True:
        app.processEvents()
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if ready:
            return sys.stdin.readline().strip().lower()


# ---------------------------------------------------------------- voice wrapper (안내·기록만, STT 로직은 production)
def _now():
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


def _print_audio_debug(round_no, stage, entry):
    cap = entry.get("capture_stats") or {}; tl = cap.get("timeline") or {}; dbg = entry.get("debug") or {}
    lines = [f"[Round {round_no} STT DEBUG · {stage} · mode {entry.get('mode')} beep {entry.get('beep')}]",
             f"listen start {entry.get('listen_started_at')} · stream opened {cap.get('stream_opened_at')}",
             f"warmup done +{tl.get('warmup_done')}s · calibration done +{tl.get('calibration_done')}s · on_ready +{tl.get('on_ready')}s ({entry.get('on_ready_at')})",
             f"noise_floor={cap.get('noise_floor')} threshold={cap.get('threshold')} calibration min/median/max={cap.get('calibration_min')}/{cap.get('calibration_median')}/{cap.get('calibration_max')} "
             f"calibration_unstable={cap.get('calibration_unstable')} retries={cap.get('calibration_retries')} still_unstable={cap.get('calibration_still_unstable')}",
             f"capture_duration={cap.get('capture_seconds')}s voiced={cap.get('voiced_seconds')}s trimmed={cap.get('trimmed_seconds')}s reason={cap.get('reason')}",
             f"stt_called={dbg.get('stt_called')} wav duration={dbg.get('duration')}s peak={dbg.get('peak')} rms={dbg.get('rms')} weak_input={dbg.get('weak_input')}",
             f"whisper raw={dbg.get('whisper_text')!r} no_speech_prob={dbg.get('no_speech_probs')} avg_logprob={dbg.get('avg_logprobs')} debug reason={dbg.get('reason')}",
             f"final_text={entry.get('stt_text')!r} last_error={entry.get('last_error')} · stream closed {cap.get('stream_closed_at')} · listen end {entry.get('listen_ended_at')} ({entry.get('seconds')}s)"]
    print("    " + "\n    ".join(lines), flush=True)


class ListenRecorder:
    def __init__(self):
        self.original = voice.listen
        self.original_speak = voice.speak
        self.events = []
        self.debug_dir = None
        self.stage = "initial"
        self.round_no = 0
        self.ready_at = None
        self.tts_log = []

    def install(self):
        rec = self
        # voice.listen이 mode/beep를 아직 받지 않는 판이면 on_ready만 넘긴다(설치 시 한 번 확인).
        params = inspect.signature(rec.original).parameters
        forwards_mode = "mode" in params or any(p.kind == p.VAR_KEYWORD for p in params.values())

        def listen(on_ready=None, mode="short", beep=False):
            first = rec.stage == "initial" and not rec.events
            phrase = INITIAL_PHRASE if first else INITIAL_AGAIN_PHRASE if rec.stage == "initial" else INTERVENTION_PHRASE

            def ready():
                rec.ready_at = _now()
                print(f"\n>>> 지금 말씀하세요: \"{phrase}\"", flush=True)
                if on_ready is not None:
                    on_ready()
            if rec.debug_dir:
                os.makedirs(rec.debug_dir, exist_ok=True); os.environ[voice.DEBUG_DIR_ENV] = rec.debug_dir
            print("마이크 보정 중입니다. 삐 소리와 '지금 말씀하세요'가 나온 뒤 말씀해주세요.", flush=True)
            rec.ready_at = None; started_at = _now(); t = time.monotonic()
            text = rec.original(on_ready=ready, mode=mode, beep=beep) if forwards_mode else rec.original(on_ready=ready)
            entry = {"stage": rec.stage, "phrase": phrase, "mode": mode, "beep": beep, "forwarded_mode": forwards_mode,
                     "stt_text": text, "last_error": voice.last_error(), "seconds": round(time.monotonic() - t, 1),
                     "listen_started_at": started_at, "on_ready_at": rec.ready_at, "listen_ended_at": _now(),
                     "capture_stats": deepcopy(getattr(voice, "_last_capture", None))}
            latest = os.path.join(rec.debug_dir, "latest_input.json") if rec.debug_dir else None
            if latest and os.path.exists(latest):
                try:
                    with open(latest, encoding="utf-8") as f:
                        entry["debug"] = json.load(f)
                except ValueError:
                    pass
            rec.events.append(entry)
            print(f"    STT: {text!r}" + (f" (last_error {voice.last_error()})" if text in (None, "") else ""), flush=True)
            print(f"[C][STT_RAW] {_now()} \"{text if text is not None else ''}\"", flush=True)  # whisper 최종 텍스트 그대로
            dbg = entry.get("debug") or {}
            if dbg.get("stt_called") and dbg.get("weak_input"):
                print("    !!! 마이크 입력이 약합니다. 마이크에 조금 더 가까이/크게 말씀해주세요. "
                      f"(peak {dbg.get('peak')} < {voice.WEAK_INPUT_PEAK}, rms {dbg.get('rms')}) — STT 결과는 그대로 둡니다.", flush=True)
            if DEBUG["audio"]:
                _print_audio_debug(rec.round_no, rec.stage, entry)
            return text
        voice.listen = listen

        def speak(text):
            t0 = _now(); rec.original_speak(text); t1 = _now()
            played = getattr(voice, "_last_speak", None) or {}  # 실제 재생 시작/끝(TTS 응답 대기 뒤)
            rec.tts_log.append({"stage": rec.stage, "text": text, "started_at": t0, "ended_at": t1, "chars": len(text),
                                "play_started_at": played.get("play_started_at"), "play_ended_at": played.get("play_ended_at")})
            if DEBUG["audio"]:
                print(f"    [TTS DEBUG] playback start {t0} · end {t1} (POST_SPEAK_DELAY {voice.POST_SPEAK_DELAY}s 포함)", flush=True)
        voice.speak = speak

    def uninstall(self):
        voice.listen = self.original
        voice.speak = self.original_speak


# ---------------------------------------------------------------- per-round
def shape(blocks):
    layers = Counter(b["layer"] for b in blocks)
    return {"blocks": len(blocks), "max_layer": max(layers) if layers else 0, "layers": dict(sorted(layers.items())),
            "red": sum(b["color"] == "red" for b in blocks), "1x2x1": sum(b["brick_type"] == "1x2x1" for b in blocks)}


def contains_current(blocks, current):
    """Current의 여섯 값 multiset이 Design에 모두 들어 있는가(validator와 별개로 표시용 재확인)."""
    have = Counter(tuple(b[f] for f in FIELDS) for b in blocks)
    return not (Counter(tuple(b[f] for f in FIELDS) for b in current) - have)


def _validator_text(reasons):
    if reasons is None:
        return "-"
    return "PASS" if reasons == [] else "FAIL " + "; ".join(str(r.get("rule") if isinstance(r, dict) else r) for r in reasons[:3])


def _counts(sh):
    return f"{sh.get('blocks')}/{sh.get('red')}/{sh.get('1x2x1')}/L{sh.get('max_layer')}" if sh else "-"


def _interpretation(m1):
    pref = m1.get("preference") or {}
    mode = pref.get("preference")
    concept = pref.get("style_hint") if mode == "CREATIVE" else None
    return {"mode": mode, "object": pref.get("object"), "family": pref.get("family"), "style_hint": m1.get("style_hint"),
            "concept": concept, "sufficient": pref.get("sufficient"), "follow_up": pref.get("follow_up"), "reply": pref.get("reply")}


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def screen_lines(meta):
    """화면 아래 텍스트(§12 항목)."""
    v1, v2, sc = meta.get("v1") or {}, meta.get("v2") or {}, meta.get("scenario") or {}
    it = v1.get("interpretation") or {}
    lines = [f"Round {meta['round']} · status {meta.get('status')}" + (f" · failed {meta.get('failed_stage')}: {meta.get('reason')}" if meta.get("failed_stage") else ""),
             f"[Initial] raw STT: {v1.get('stt')} · mode {it.get('mode')} · family {it.get('family')} · concept {it.get('concept')} · "
             f"style_hint {it.get('style_hint')} · family_source {v1.get('family_source')} · selected_family {v1.get('selected_family')}",
             f"[v1] {v1.get('design_name')} [{v1.get('design_family')}] · blocks/red/1x2x1/max layer {_counts(v1.get('shape'))} · "
             f"validator {_validator_text(v1.get('validator'))} · generation {v1.get('seconds')} s"]
    if sc:
        e, a = sc["expected"], sc["actual"]
        lines.append(f"[Difference] {e['brick_type']} {e['color']} expected ({e['x']},{e['y']}) L{e['layer']} {e['orientation_deg']}° → "
                     f"actual ({a['x']},{a['y']}) L{a['layer']} {a['orientation_deg']}° (dx {sc['dx']}, dy {sc['dy']}, rotated {sc['rotated']}) · "
                     f"Current {sc['current_blocks']}블록(layer 1)")
    if v2:
        lines += [f"[Intervention] raw STT: {v2.get('stt')} · result {v2.get('hri_result')} ({v2.get('status')}) · style_hint {v2.get('style_hint')} · "
                  f"Current preserved {v2.get('preserved')}",
                  f"[v2] {v2.get('design_name')} [{v2.get('design_family')}] · blocks/red/1x2x1/max layer {_counts(v2.get('shape'))} · "
                  f"validator {_validator_text(v2.get('validator'))} · judge {v2.get('verdict')} (chair {v2.get('chair_likeness')}, "
                  f"richer {v2.get('richer_than_previous')}) · v2 latency {v2.get('seconds')} s"]
    return lines


def run_round(k, out, app, viewer, rec):
    rdir = os.path.join(out, f"round{k:02d}"); os.makedirs(rdir, exist_ok=True)
    meta = {"round": k, "status": "RUNNING", "model": os.environ.get("OPENAI_MODEL"), "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    transcript = {"initial": [], "intervention": [], "questions": {"initial": [], "intervention": []}, "tts": [],
                  "ack_tts": {}}

    def dump():
        transcript["tts"] = list(rec.tts_log)
        _write_json(os.path.join(rdir, "metadata.json"), meta)
        _write_json(os.path.join(rdir, "transcript.json"), transcript)

    def fail(stage, why):
        meta.update(status="FAILED", failed_stage=stage, reason=why)
        print(f"\n!!! Round {k} FAILED at {stage}: {why}", flush=True)
        dump()
        return meta

    def on_question(stage):
        def show(q):
            transcript["questions"][stage].append(q)
            print(f"\n[TTS] {q}", flush=True)
        return show

    progress = {"initial": [], "intervention": []}

    def on_progress(stage):
        def log(event):
            progress[stage].append(event)
            message = f"\"{event['message']}\"" if event["stage"] in ("ACK", "KEEP_ACK") else event["message"]
            print(f"[C][{event['stage']}] {event['at']} {message}", flush=True)
        return log

    def ack_tts(stage):
        """그 단계의 첫 ACK/KEEP_ACK 문장이 실제로 재생되기 시작한 시각(첫 응답 latency 측정용)."""
        acks = [e["message"] for e in progress[stage] if e["stage"] in ("ACK", "KEEP_ACK")]
        spoken = [t for t in rec.tts_log if t["stage"] == stage and acks and t["text"] == acks[0]]
        listened = [ev.get("listen_ended_at") for ev in rec.events if ev.get("listen_ended_at")]
        return {"text": acks[0] if acks else None, "play_started_at": spoken[0].get("play_started_at") if spoken else None,
                "last_listen_ended_at": listened[-1] if listened else None}

    print(f"\n=== [Round {k}/{TOTAL['rounds']}] ===\nC가 먼저 인사합니다(TTS). 삐 소리와 '지금 말씀하세요'가 나오면 "
          "오늘 만들고 싶은 의자를 자유롭게 말씀하세요.", flush=True)
    time.sleep(SETTLE_SECONDS)  # Enter 직후 발화·키 소리가 보정에 섞이지 않게
    rec.round_no, rec.stage, rec.tts_log = k, "initial", []
    rec.debug_dir, rec.events = os.path.join(rdir, "stt_initial"), []
    t = time.monotonic()
    env1 = main.create_initial_design(text=None, on_question=on_question("initial"), on_progress=on_progress("initial"))
    dt = time.monotonic() - t
    transcript["initial"] = rec.events
    transcript["ack_tts"]["initial"] = ack_tts("initial")
    _write_json(os.path.join(rdir, "v1.json"), env1)
    m1 = env1.get("design_metadata") or {}
    meta["v1"] = {"status": env1["status"], "error": env1["error"], "seconds": round(dt, 1),
                  "stt": [ev.get("stt_text") for ev in rec.events], "interpretation": _interpretation(m1),
                  "family_source": m1.get("family_source"), "selected_family": m1.get("selected_family"),
                  "design_name": m1.get("design_name"), "design_family": m1.get("design_family"),
                  "family_design_match": m1.get("family_design_match"), "design_metadata": m1,
                  "progress": progress["initial"], "ack_tts": transcript["ack_tts"]["initial"]}
    print(f"Initial raw STT: {meta['v1']['stt']}", flush=True)
    it = meta["v1"]["interpretation"]
    print(f"해석: mode {it['mode']} · family {it['family']} · style_hint {it['style_hint']} · concept {it['concept']} · "
          f"family_source {m1.get('family_source')} · selected_family {m1.get('selected_family')} · metadata error {m1.get('error')}", flush=True)
    if env1["status"] != "OK" or not env1["design"]:
        return fail("v1", f"{env1['status']} {env1['error']} ({dt:.1f}s)")
    d1 = env1["design"]
    meta["v1"].update(shape=shape(d1["blocks"]), validator=validator.validate_design(d1))
    print(f"v1: {m1.get('design_name')} [{m1.get('design_family')}] · blocks/red/1x2x1/max layer {_counts(meta['v1']['shape'])} · "
          f"validator {_validator_text(meta['v1']['validator'])} · generation {dt:.1f}s", flush=True)
    meta["screen_lines"] = screen_lines(meta)
    img = compose_v1(f"Round {k} · v1 · {m1.get('design_name')}", d1["blocks"], meta["screen_lines"], os.path.join(rdir, "v1.png"))
    viewer.show(app, img, f"Round {k} · v1")
    dump()
    ans = _wait_enter(app, "\nv1 화면 표시 중. [Enter] 다음 단계(시험용 Difference → TTS 질문) / r 이 Round 다시 / q 종료")
    if ans in ("r", "q"):
        meta["status"] = "RETRY" if ans == "r" else "QUIT"; dump()
        return meta

    sc = make_scenario(d1, k)
    if not sc:
        return fail("scenario", "no valid layer-1 displacement for this v1")
    meta["scenario"] = {kk: sc[kk] for kk in ("index", "dx", "dy", "rotated", "expected", "actual")}
    meta["scenario"].update(current_blocks=len(sc["current"]), current=sc["current"], differences=sc["differences"])
    e, a = sc["expected"], sc["actual"]
    print(f"시험용 Difference: {e['brick_type']} {e['color']} ({e['x']},{e['y']}) L1 {e['orientation_deg']}° → ({a['x']},{a['y']}) L1 "
          f"{a['orientation_deg']}° · Current {len(sc['current'])}블록(layer 1)", flush=True)
    print("TTS 질문이 끝나고 삐 소리 뒤 안내가 나오면 자유롭게 답하세요(예: \"일부러 그렇게 놨어요\", \"제가 잘못 놨어요\").", flush=True)

    rec.stage = "intervention"
    rec.debug_dir, rec.events = os.path.join(rdir, "stt_intervention"), []
    t = time.monotonic()
    env2 = main.run_intervention(d1, sc["current"], sc["differences"], text_answers=None, on_question=on_question("intervention"),
                                 on_progress=on_progress("intervention"))
    dt = time.monotonic() - t
    transcript["intervention"] = rec.events
    transcript["ack_tts"]["intervention"] = ack_tts("intervention")
    _write_json(os.path.join(rdir, "v2.json"), {"envelope": env2, "current": sc["current"], "differences": sc["differences"], "v1": d1})
    m2 = env2.get("design_metadata") or {}; j = m2.get("judge") or {}; d2 = env2.get("design")
    meta["v2"] = {"status": env2["status"], "hri_result": env2["hri_result"], "error": env2["error"], "seconds": round(dt, 1),
                  "stt": [ev.get("stt_text") for ev in rec.events], "style_hint": m2.get("style_hint"),
                  "design_name": m2.get("design_name"), "design_family": m2.get("design_family"),
                  "verdict": j.get("verdict"), "chair_likeness": j.get("chair_likeness"), "richer_than_previous": j.get("richer_than_previous"),
                  "regenerations": m2.get("regenerations"), "design_metadata": m2,
                  "progress": progress["intervention"], "ack_tts": transcript["ack_tts"]["intervention"]}
    if d2:
        preserved_multiset = contains_current(d2["blocks"], sc["current"])
        meta["v2"].update(shape=shape(d2["blocks"]), validator=validator.validate_design(d2), preserved_multiset=preserved_multiset,
                          preserved=validator.validate_revised({"blocks": d2["blocks"]}, sc["current"]) == [] and preserved_multiset)
    v2 = meta["v2"]
    print(f"Intervention raw STT: {v2['stt']} · result {v2['hri_result']} ({v2['status']}) · style_hint {v2['style_hint']}", flush=True)
    print(f"v2: {v2['design_name']} [{v2['design_family']}] · blocks/red/1x2x1/max layer {_counts(v2.get('shape'))} · "
          f"validator {_validator_text(v2.get('validator'))} · Current preserved {v2.get('preserved')} · judge {v2['verdict']} "
          f"(chair {v2['chair_likeness']}, richer {v2['richer_than_previous']}) · v2 latency {dt:.1f}s", flush=True)
    if env2["status"] == "OK" and env2["hri_result"] == dialogue.REVISE and d2:
        meta["status"] = "OK"
    elif env2["status"] == "OK":
        meta["status"] = str(env2["hri_result"])  # KEEP·UNCLEAR 등: 실패가 아니라 Revised 없음으로 기록
    else:
        meta.update(status="FAILED", failed_stage="v2", reason=f"{env2['status']} {env2['hri_result']} {env2['error']}")
    v2_title = f"v2 · {v2['design_name']}" if d2 else f"v2 없음 ({env2['status']} {env2['hri_result']})"
    meta["screen_lines"] = screen_lines(meta)
    captions = [[f"v1 · {m1.get('design_name')}", counts_line(d1["blocks"])],
                ["Current + Difference", "실선: Current(놓인 블록) · 주황: 사람이 옮긴 블록(actual) · 점선: 원래 Design 위치(expected)",
                 f"expected ({e['x']},{e['y']}) L{e['layer']} {e['orientation_deg']}° → actual ({a['x']},{a['y']}) L{a['layer']} {a['orientation_deg']}°"],
                [v2_title, counts_line(d2["blocks"]) if d2 else "",
                 f"result {v2['hri_result']} · style_hint {v2['style_hint']} · Current preserved {v2.get('preserved')} · judge {v2['verdict']} "
                 f"(chair {v2['chair_likeness']}, richer {v2['richer_than_previous']}) · v2 latency {dt:.1f}s"]]
    img = compose_v2(f"Round {k} · v1 | Current+Difference | v2", d1["blocks"], sc["current"], e, a, d2["blocks"] if d2 else None,
                     captions, meta["screen_lines"], os.path.join(rdir, "screen.png"))
    viewer.show(app, img, f"Round {k} · v1 | Current+Difference | v2")
    dump()
    return meta


# ---------------------------------------------------------------- summary
def _cell(value):
    return str(value).replace("|", "/").replace("\n", " ")


def summarize(out, rounds):
    rows = []; agg = Counter(); modes = Counter(); fams = Counter()
    for k in range(1, rounds + 1):
        p = os.path.join(out, f"round{k:02d}", "metadata.json")
        if not os.path.exists(p):
            rows.append([k, "미실행"] + [""] * 17); continue
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        v1, v2, sc = m.get("v1") or {}, m.get("v2") or {}, m.get("scenario") or {}
        it = v1.get("interpretation") or {}
        diff = (f"({sc['expected']['x']},{sc['expected']['y']})→({sc['actual']['x']},{sc['actual']['y']})"
                + (" rot" if sc.get("rotated") else "")) if sc else "-"
        status = m.get("status") + (f" @{m.get('failed_stage')}" if m.get("failed_stage") else "")
        rows.append([k, status, " / ".join(str(s) for s in v1.get("stt") or []), it.get("mode"),
                     it.get("concept") or it.get("family"), v1.get("family_source"), v1.get("selected_family"), _counts(v1.get("shape")),
                     _validator_text(v1.get("validator")), v1.get("seconds"), diff,
                     " / ".join(str(s) for s in v2.get("stt") or []), v2.get("hri_result"), v2.get("style_hint"), v2.get("preserved"),
                     _counts(v2.get("shape")), _validator_text(v2.get("validator")), v2.get("verdict"), v2.get("seconds")])
        agg["rounds"] += 1
        agg["v1_ok"] += v1.get("status") == "OK"; agg["v1_pass"] += v1.get("validator") == []
        agg["revise"] += v2.get("hri_result") == dialogue.REVISE; agg["v2_pass"] += v2.get("validator") == []
        agg["preserved"] += bool(v2.get("preserved")); agg["showcase"] += v2.get("verdict") == "SHOWCASE"
        if it.get("mode"): modes[it["mode"]] += 1
        if v1.get("selected_family") or it.get("concept"): fams[v1.get("selected_family") or f"concept:{it['concept']}"] += 1
    head = ("| Round | status | Initial raw STT | mode | family/concept | family_source | selected_family | v1 blocks/red/1x2x1/max layer | "
            "v1 validator | v1 s | Difference | Intervention raw STT | result | style_hint | Current preserved | "
            "v2 blocks/red/1x2x1/max layer | v2 validator | judge verdict | v2 s |")
    lines = [head, "|" + "---|" * 19] + ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    n = agg["rounds"] or 1
    lines += ["", f"실행된 Round: {agg['rounds']}/{rounds}",
              f"- v1 생성 성공 {agg['v1_ok']}/{n} · v1 validator PASS {agg['v1_pass']}/{n} · mode {dict(modes)} · family/concept {dict(fams)}",
              f"- REVISE {agg['revise']}/{n} · v2 validator PASS {agg['v2_pass']}/{n} · Current preserved {agg['preserved']}/{n} · SHOWCASE {agg['showcase']}/{n}"]
    text = "\n".join(lines)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\n" + text); print(f"\nsummary saved: {os.path.join(out, 'summary.md')}")
    return text


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5); ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--out", default=os.path.expanduser("~/c_voice_e2e_c_only")); ap.add_argument("--summary", action="store_true")
    ap.add_argument("--debug-audio", action="store_true", help="listen/TTS마다 시각·보정·게이트·Whisper 원문·no_speech_prob·avg_logprob 출력")
    args = ap.parse_args(); DEBUG["audio"] = args.debug_audio
    os.makedirs(args.out, exist_ok=True); TOTAL["rounds"] = args.rounds
    if args.summary:
        summarize(args.out, args.rounds); return
    missing = [name for name in (voice.STT_KEY_ENV, llm.LLM_KEY_ENV, voice.TTS_KEY_ENV) if not os.environ.get(name)]
    if os.environ.get("C_DESIGN_USE_LLM") != "1" or missing:
        sys.exit(f"환경 확인: C_DESIGN_USE_LLM=1 필요, 미설정 key env: {missing} (값은 출력하지 않음)")
    print(f"C 단독 E2E · model {os.environ.get('OPENAI_MODEL') or llm.DEFAULT_MODEL} · STT {os.environ.get('OPENAI_STT_MODEL') or voice.DEFAULT_STT_MODEL} · "
          f"keys {voice.STT_KEY_ENV}/{llm.LLM_KEY_ENV}/{voice.TTS_KEY_ENV} configured · validator MAX_LAYER {validator.MAX_LAYER} "
          f"MAX_BLOCKS {validator.MAX_BLOCKS} · LLM timeout {llm.TIMEOUT_SECONDS}s · out {args.out} · A planner/Backend/Robot 미사용", flush=True)
    prewarm = getattr(voice, "prewarm", None)
    if prewarm is not None:
        print(f"voice.prewarm(): {prewarm()}", flush=True)
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    viewer = Viewer()
    rec = ListenRecorder(); rec.install()
    try:
        k = args.start
        while k <= args.rounds:
            meta = run_round(k, args.out, app, viewer, rec)
            status = meta.get("status")
            if status == "QUIT":
                break
            if status == "RETRY":
                continue
            if status == "FAILED":
                ans = _wait_enter(app, f"\nRound {k} FAILED ({meta.get('failed_stage')}: {meta.get('reason')}). [Enter] 다음 Round / r 이 Round 다시 / q 종료")
            else:
                ans = _wait_enter(app, f"\nRound {k} 완료({status}) · 화면 표시 중. [Enter] 다음 Round / r 이 Round 다시 / q 종료")
            if ans == "q":
                break
            if ans != "r":
                k += 1
    finally:
        rec.uninstall(); viewer.close()
    summarize(args.out, args.rounds)


if __name__ == "__main__":
    main_cli()
