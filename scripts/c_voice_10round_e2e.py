"""사용자 음성 E2E runner (기본 5 Round, 시험용, production 코드 수정 없음).
A/D 통합용 runner입니다. Stage 2 어휘(red·1x2x1·5층)는 A/D 반영 전까지 A planner에서 INVALID가 날 수 있습니다. C 단독 시험은 scripts/c_voice_e2e_c_only.py를 쓰세요.

흐름(Round마다): 마이크 준비 → "지금 말씀하세요" → 사용자가 "의자 만들어줘" → whisper-1 STT → production
main.create_initial_design(text=None): TTS 선호 질문 → 사용자 자유 답변(예: "아무거나", "왕좌처럼 높고 화려한 의자요")
→ family 선택 → Initial → Validator/A Planner → v1 HMI(캡처) → [Enter] → 시험용 Human Error(fixture scenario 순환)
→ production main.run_intervention(..., text_answers=None): TTS 주관식 질문 → 사용자 자유 답변(예: "일부러 그렇게 놨어요",
"좀 더 넓고 화려하게 하고 싶어요") → STT → (자유 답변 해석·style_hint) → Revised(생성 → validator → judge →
조건부 재생성 1회, 별도 설계 의도 단계 없음) → Validator/A Planner → v2 HMI(캡처) → [Enter].
Round마다 selected family·blocks·red·1x2x1·max layer·Current preserved·validator PASS·judge verdict·v2 total latency를
출력하고 metadata.json·summary.md에 남긴다. 사용자가 말할 차례마다 ">>> 지금 말씀하세요" 안내를 낸다.

production 경로 그대로: voice.listen/speak, llm(gpt-6.1-sol), main, validator, planning_trial.planner, app.qt_hmi.
시험용으로만 덧붙인 것: listen() 호출 시 on_ready 안내 출력·STT 결과 기록(voice.listen 래핑), HMI 표시용 5층
허용(planner·contracts 패치는 이 프로세스 안에서만, production A 결과는 따로 기록), HMI notice/footer overlay.

실행(키 값은 명령마다 파일에서 주입, 출력·기록하지 않음):
  cd ~/adaptive_coassembly/C-2 && env C_DESIGN_USE_LLM=1 OPENAI_MODEL=gpt-6.1-sol \
    OPENAI_API_KEY="$(cat ~/C2_OpenAi_API_Key.txt)" OPENAI_LLM_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" \
    OPENAI_TTS_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" python3 scripts/c_voice_10round_e2e.py
옵션: --rounds N(기본 5) --start K(기본 1, 이어서 진행) --out DIR(기본 ~/c_voice_e2e_10runs) --summary(집계만)
      --debug-audio(각 listen/TTS의 시각·보정·게이트·Whisper 원문·no_speech_prob를 터미널에 출력)
"""
import argparse
import hashlib
import json
import os
import select
import sys
import time
from collections import Counter, defaultdict
from copy import deepcopy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.c_design import dialogue, llm, main, validator, voice  # noqa: E402
try:  # Stage 1 이력 모듈은 Stage 2에서 family 선택 구조로 대체된다; 없으면 분류 항목만 비운다
    from app.c_design import history  # noqa: E402
except ImportError:  # pragma: no cover
    history = None
from planning_trial import planner  # noqa: E402

FIELDS = ("brick_type", "color", "x", "y", "layer", "orientation_deg")
INITIAL_PHRASE = "의자 만들어줘"
PREFERENCE_PHRASE = "원하는 의자를 자유롭게(예: 왕좌처럼 높고 화려한 의자요 / 아무거나)"  # Initial 두 번째 listen(선호 답) 안내
REVISION_PHRASE = "일부러 그렇게 놨어요"  # 기록용 예시 답(주관식 질문, REVISE). "2번"도 호환으로 REVISE
TOTAL = {"rounds": 5}  # 안내 출력용(main_cli에서 설정)
DEBUG = {"audio": False}  # --debug-audio
SETTLE_SECONDS = 1.0  # Round 전환(Enter) 직후 발화·환경 변화가 보정에 섞이지 않게 두는 짧은 간격
FAR = [(dx, dy) for dx in range(-3, 4) for dy in range(-3, 4) if 2 <= abs(dx) + abs(dy) <= 3]
ONE = [(1, 0), (-1, 0), (0, 1), (0, -1)]
# (ID, 설명, 역할 태그, 이동 후보, 회전 허용). Round k는 SCENARIOS[(k-1) % 10]부터 시도하고, 그 v1에 유효한 배치가 없으면 다음 ID로 넘어간다.
SCENARIOS = [
    ("S01", "support far outward (받침 2~3 stud 바깥)", ["support", "right"], FAR, False),
    ("S02", "seat block displaced (좌석 블록 2~3 stud 이동·회전)", ["seat"], FAR, True),
    ("S04", "backrest base displaced (등받이 하단 이동·회전)", ["backrest"], FAR, True),
    ("S07", "upper backrest displaced (등받이 상단 이동·회전)", ["backrest_upper"], FAR, True),
    ("S05", "front-left support displaced (앞왼쪽 받침)", ["support", "front", "left"], FAR, False),
    ("S03", "early block displaced (초기 블록 2~3 stud 이동·회전)", ["early"], FAR, True),
    ("S06", "late seat block rotated+displaced (후반 좌석 블록)", ["seat", "late"], FAR, True),
    ("S08", "mid front support displaced (중반 앞 받침)", ["support", "front", "mid"], FAR, False),
    ("S09", "support 1-stud shift (받침 1 stud)", ["support"], ONE, False),
    ("S10", "seat edge 1-stud shift (좌석 가장자리 1 stud)", ["seat", "seat_edge"], ONE, False),
]


# ---------------------------------------------------------------- scenario (A plan 역할 기반, 시험용)
def _cells(block):
    return {(c[0], c[1]) for c in validator.footprint(block)}


def block_roles(design, plan):
    by_layer = defaultdict(list)
    for b in design["blocks"]:
        by_layer[b["layer"]].append(b)
    cells = {L: set().union(*(_cells(b) for b in bs)) for L, bs in by_layer.items()}
    layers = sorted(by_layer)
    seat = max((L for L in layers if L >= 2), key=lambda L: len(cells[L]), default=None)
    s = cells[seat] if seat else set()
    sx = [x for x, _ in s] or [0]; sy = [y for _, y in s] or [0]
    steps = plan["steps"]; roles = []
    for i, st in enumerate(steps):
        b = st["after"]; fp = _cells(b); bx = [x for x, _ in fp]; by = [y for _, y in fp]; tags = []
        if seat is None or b["layer"] < seat:
            tags.append("support")
            if min(by) <= min(sy): tags.append("front")
            if max(by) >= max(sy): tags.append("rear")
            if min(bx) <= min(sx): tags.append("left")
            if max(bx) >= max(sx): tags.append("right")
        elif b["layer"] == seat:
            tags.append("seat")
            if min(bx) == min(sx) or max(bx) == max(sx) or min(by) == min(sy) or max(by) == max(sy): tags.append("seat_edge")
        else:
            tags.append("backrest" if b["layer"] == seat + 1 else "backrest_upper")
        tags.append("early" if i < len(steps) // 3 else "mid" if i < 2 * len(steps) // 3 else "late")
        roles.append({"index": i, "step_id": st["step_id"], "block": b, "tags": tags})
    return roles


def make_scenario(design, plan, want_tags, shifts, rotate):
    """want_tags에 맞는 첫 Step을 골라 shifts(회전 선택) 중 유효한 배치(판 안·겹침 없음·Current 지지 규칙·입력 검사)를
    v1 중심에서 가장 먼 것으로 택한다. 없으면 None."""
    steps = plan["steps"]; blocks = design["blocks"]
    cx = sum(b["x"] for b in blocks) / len(blocks); cy = sum(b["y"] for b in blocks) / len(blocks)
    for r in block_roles(design, plan):
        if not all(t in r["tags"] for t in want_tags):
            continue
        idx = r["index"]; target = r["block"]
        placed = [{f: steps[j]["after"][f] for f in FIELDS} for j in range(idx)]
        best = None
        for dx, dy in shifts:
            for rot in ((0, 90) if rotate and target["brick_type"] == "2x3x1" else (target["orientation_deg"],)):
                moved = dict(target, x=target["x"] + dx, y=target["y"] + dy, orientation_deg=rot)
                if tuple(moved[f] for f in FIELDS) == tuple(target[f] for f in FIELDS):
                    continue
                current = placed + [moved]
                seen = set(); ok = True
                for b in current:
                    for c in validator.footprint(b):
                        if not (0 <= c[0] <= validator.BOARD_RANGE[-1] and 0 <= c[1] <= validator.BOARD_RANGE[-1]) or (b["layer"], c[0], c[1]) in seen:
                            ok = False
                        seen.add((b["layer"], c[0], c[1]))
                diffs = [{"expected": target, "actual": moved}]
                if not ok or validator.current_support_violations(current) or validator.check_intervention_input(design, current, diffs):
                    continue
                dist = abs(moved["x"] - cx) + abs(moved["y"] - cy)
                if best is None or dist > best[0]:
                    best = (dist, moved, current, diffs)
        if best:
            _, moved, current, diffs = best
            return {"a_step": r["step_id"], "tags": r["tags"], "expected": target, "actual": moved, "placed_before": len(placed),
                    "current": {"current_revision": idx + 1, "blocks": current}, "differences": diffs}
    return None


# ---------------------------------------------------------------- A planner (production 값 + 표시용 5층)
def plan_both(design, current):
    prod = planner.plan_from_current(design, current)
    saved = planner.MAX_LAYER
    planner.MAX_LAYER = max(saved, validator.MAX_LAYER)
    try:
        shown = planner.plan_from_current(design, current)
    finally:
        planner.MAX_LAYER = saved
    return prod, shown


def _allow_layer5_in_hmi():
    """HMI 표시 전용: D contracts의 layer 1..4 검사를 이 프로세스에서만 validator.MAX_LAYER까지 허용."""
    from app import contracts
    if getattr(contracts, "_voice_e2e_patched", False):
        return
    orig = contracts._integer

    def _integer(value, minimum, maximum, path):
        if path.endswith(".layer") and maximum == 4:
            maximum = validator.MAX_LAYER
        return orig(value, minimum, maximum, path)
    contracts._integer = _integer; contracts._voice_e2e_patched = True


# ---------------------------------------------------------------- HMI
def build_snapshot(design, plan, current):
    from uuid import uuid4
    from app.backend import Backend
    from app.completion import freeze_plan_basis
    from app.snapshot import make_snapshot
    state = Backend(lambda port, payload: None, mode="FAKE").state
    state.update(job_id=str(uuid4()), context=freeze_plan_basis(design, plan, current), current=deepcopy(current),
                 workflow_status="WAIT_ASSEMBLY", controller_ready=True, at_observe_point=True)  # current: 이미 놓인 블록을 HMI "Current rN · 채택 N개"에 반영
    return make_snapshot(state)


def _wait_enter(app, prompt):
    """터미널 Enter를 기다리는 동안 Qt 창은 계속 그린다. 입력 줄(소문자)을 돌려준다."""
    print(prompt, flush=True)
    while True:
        app.processEvents()
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if ready:
            return sys.stdin.readline().strip().lower()


def show_hmi(app, window, design, plan, current, title, footer, notice_lines, png_path):
    _allow_layer5_in_hmi()
    snap = build_snapshot(design, plan, current)
    window.render_snapshot(snap)
    window.design_panel.setTitle(title)
    window.notice.setPlainText("\n".join(notice_lines) + "\n\n" + window.notice.toPlainText())
    window.footer.setText(footer)
    window.setWindowTitle(title); window.show(); window.raise_()
    for _ in range(5):
        app.processEvents(); time.sleep(0.05)
    saved = window.grab().save(png_path)
    return saved


# ---------------------------------------------------------------- voice wrapper (안내·기록만, STT 로직은 production)
def _now():
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


def _print_audio_debug(round_no, stage, entry):
    cap = entry.get("capture_stats") or {}; tl = cap.get("timeline") or {}; dbg = entry.get("debug") or {}
    lines = [f"[Round {round_no} STT DEBUG · {stage}]",
             f"listen start {entry.get('listen_started_at')} · stream opened {cap.get('stream_opened_at')}",
             f"warmup done +{tl.get('warmup_done')}s · calibration done +{tl.get('calibration_done')}s · on_ready +{tl.get('on_ready')}s ({entry.get('on_ready_at')})",
             f"noise_floor={cap.get('noise_floor')} threshold={cap.get('threshold')} calibration min/median/max={cap.get('calibration_min')}/{cap.get('calibration_median')}/{cap.get('calibration_max')} "
             f"calibration_unstable={cap.get('calibration_unstable')} retries={cap.get('calibration_retries')} still_unstable={cap.get('calibration_still_unstable')}",
             f"capture_duration={cap.get('capture_seconds')}s voiced={cap.get('voiced_seconds')}s trimmed={cap.get('trimmed_seconds')}s reason={cap.get('reason')}",
             f"stt_called={dbg.get('stt_called')} wav duration={dbg.get('duration')}s peak={dbg.get('peak')} rms={dbg.get('rms')} weak_input={dbg.get('weak_input')}",
             f"whisper raw={dbg.get('whisper_text')!r} no_speech_prob={dbg.get('no_speech_probs')} debug reason={dbg.get('reason')}",
             f"final_text={entry.get('stt_text')!r} last_error={entry.get('last_error')} · stream closed {cap.get('stream_closed_at')} · listen end {entry.get('listen_ended_at')} ({entry.get('seconds')}s)"]
    print("    " + "\n    ".join(lines), flush=True)


class ListenRecorder:
    def __init__(self):
        self.original = voice.listen
        self.original_speak = voice.speak
        self.events = []
        self.phrase = ""
        self.debug_dir = None
        self.stage = "initial"
        self.round_no = 0
        self.ready_at = None
        self.tts_log = []

    def install(self):
        rec = self

        def listen(on_ready=None):
            # Initial은 목표 → 선호 답 두 번 듣는다. 두 번째는 선호 질문에 대한 자유 답변 안내를 낸다.
            phrase = PREFERENCE_PHRASE if rec.stage == "initial" and rec.events else rec.phrase

            def ready():
                rec.ready_at = _now()
                print(f"\n>>> 지금 말씀하세요: \"{phrase}\"", flush=True)
                if on_ready is not None:
                    on_ready()
            if rec.debug_dir:
                os.makedirs(rec.debug_dir, exist_ok=True); os.environ[voice.DEBUG_DIR_ENV] = rec.debug_dir
            print("마이크 보정 중입니다. '지금 말씀하세요'가 나온 뒤 말씀해주세요.", flush=True)
            rec.ready_at = None; started_at = _now(); t = time.monotonic()
            text = rec.original(on_ready=ready)
            entry = {"stage": rec.stage, "expected_phrase": phrase, "stt_text": text, "last_error": voice.last_error(), "seconds": round(time.monotonic() - t, 1),
                     "listen_started_at": started_at, "on_ready_at": rec.ready_at, "listen_ended_at": _now(), "capture_stats": deepcopy(voice._last_capture)}
            if rec.debug_dir and os.path.exists(os.path.join(rec.debug_dir, "latest_input.json")):
                try:
                    entry["debug"] = json.load(open(os.path.join(rec.debug_dir, "latest_input.json")))
                except ValueError:
                    pass
            rec.events.append(entry)
            print(f"    STT: {text!r}" + (f" (last_error {voice.last_error()})" if text in (None, "") else ""), flush=True)
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
            rec.tts_log.append({"stage": rec.stage, "started_at": t0, "ended_at": t1, "chars": len(text)})
            if DEBUG["audio"]:
                print(f"    [TTS DEBUG] playback start {t0} · end {t1} (POST_SPEAK_DELAY {voice.POST_SPEAK_DELAY}s 포함)", flush=True)
        voice.speak = speak

    def uninstall(self):
        voice.listen = self.original
        voice.speak = self.original_speak


# ---------------------------------------------------------------- per-round
def fingerprint(blocks):
    return hashlib.sha256(json.dumps(sorted(tuple(b[f] for f in FIELDS) for b in blocks)).encode()).hexdigest()[:16]


def shape(blocks):
    layers = Counter(b["layer"] for b in blocks)
    xs = [c[0] for b in blocks for c in validator.footprint(b)]; ys = [c[1] for b in blocks for c in validator.footprint(b)]
    return {"blocks": len(blocks), "max_layer": max(layers), "layers": dict(sorted(layers.items())), "footprint": [max(xs) - min(xs) + 1, max(ys) - min(ys) + 1],
            "red": sum(b["color"] == "red" for b in blocks), "1x2x1": sum(b["brick_type"] == "1x2x1" for b in blocks)}


def contains_current(blocks, current):
    """Current의 여섯 값 multiset이 Design에 모두 들어 있는가(validator와 별개로 표시용 재확인)."""
    have = Counter(tuple(b[f] for f in FIELDS) for b in blocks)
    return not (Counter(tuple(b[f] for f in FIELDS) for b in current) - have)


def stats_line(label, family, sh, valid, extra=""):
    return (f"{label}: family {family} · blocks {sh['blocks']} · red {sh['red']} · 1x2x1 {sh['1x2x1']} · max layer {sh['max_layer']} · "
            f"validator {'PASS' if valid == [] else valid}{extra}")


def run_round(k, out, app, window, rec):
    rdir = os.path.join(out, f"round{k:02d}"); os.makedirs(rdir, exist_ok=True)
    meta = {"round": k, "status": "RUNNING", "model": os.environ.get("OPENAI_MODEL"), "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    transcript = {"initial": None, "revision": [], "question": None, "tts": []}

    def fail(stage, why):
        meta.update(status="FAILED", failed_stage=stage, reason=why)
        print(f"\n!!! Round {k} FAILED at {stage}: {why}", flush=True)
        return meta

    def dump():
        json.dump(meta, open(os.path.join(rdir, "metadata.json"), "w"), ensure_ascii=False, indent=2, default=str)
        json.dump(transcript, open(os.path.join(rdir, "transcript.json"), "w"), ensure_ascii=False, indent=2, default=str)

    print(f"\n=== [Round {k}/{TOTAL['rounds']}] ===\n마이크 준비 중... 마이크 보정 중입니다. '지금 말씀하세요'가 나온 뒤 말씀해주세요.\n"
          "목표를 말한 뒤 TTS 선호 질문이 나오면 원하는 의자를 자유롭게 말씀하세요(없으면 '아무거나').", flush=True)
    time.sleep(SETTLE_SECONDS)  # Enter 직후 발화·키 소리가 보정에 섞이지 않게
    rec.round_no, rec.stage, rec.tts_log = k, "initial", []
    rec.phrase, rec.debug_dir, rec.events = INITIAL_PHRASE, os.path.join(rdir, "stt_initial"), []
    t = time.monotonic(); v1 = main.create_initial_design(text=None); dt = time.monotonic() - t
    transcript["initial"] = rec.events[0] if rec.events else None
    transcript["preference"] = rec.events[1] if len(rec.events) > 1 else None
    json.dump(v1, open(os.path.join(rdir, "v1.json"), "w"), ensure_ascii=False, indent=2)
    meta["v1"] = {"status": v1["status"], "error": v1["error"], "seconds": round(dt, 1)}
    if v1["status"] != "OK" or not v1["design"]:
        dump(); return fail("v1", f"{v1['status']} {v1['error']}")
    d1 = v1["design"]; m1 = v1["design_metadata"] or {}
    plan1_prod, plan1 = plan_both(d1, {"current_revision": 0, "blocks": []})
    c1 = history.classify(d1["blocks"]) if history else {"support_style": None, "category": None, "seat_dims": [None, None], "footprint": None}
    meta["v1"].update(shape=shape(d1["blocks"]), validator=validator.validate_design(d1), a_production=plan1_prod["status"],
                      a_shown=plan1["status"], fingerprint=fingerprint(d1["blocks"]), design_name=m1.get("design_name"), design_family=m1.get("design_family"),
                      judge=m1.get("judge"), metadata_error=m1.get("error"),
                      selected_family=m1.get("selected_family"), family_source=m1.get("family_source"),
                      preference=m1.get("preference"), style_hint=m1.get("style_hint"), family_design_match=m1.get("family_design_match"),
                      family_key=m1.get("family_key") or (history.family_key(c1) if history else None), shape_key=m1.get("shape_key") or (history.shape_key(d1["blocks"]) if history else None),
                      support=c1["support_style"], category=c1["category"], seat=c1["seat_dims"], footprint=c1["footprint"],
                      history_summary_used=m1.get("history_summary_used"), recent_family_count=m1.get("recent_family_count"),
                      diversity_hint_applied=m1.get("diversity_hint_applied"), history_entries=len(history.recent()) if history else None)
    print(f"v1: {meta['v1']['shape']} | validator {meta['v1']['validator']} | A production {plan1_prod['status']} / 표시용(5층) {plan1['status']} | "
          f"{m1.get('design_name')} [{m1.get('design_family')}] family_key {meta['v1']['family_key']} | history summary {m1.get('history_summary_used')} "
          f"hint {m1.get('diversity_hint_applied')} recent_family_count {m1.get('recent_family_count')} entries {len(history.recent()) if history else '-'} {dt:.1f}s", flush=True)
    print(stats_line("v1", f"{m1.get('selected_family')} ({m1.get('family_source')})", meta["v1"]["shape"], meta["v1"]["validator"],
                     f" · 선호 답 {(transcript['preference'] or {}).get('stt_text')!r} · style_hint {m1.get('style_hint')}"), flush=True)
    if not plan1["plan"]:
        dump(); return fail("v1_plan", f"A planner: {plan1.get('errors')}")
    s1 = meta["v1"]["shape"]
    notice = [f"[v1 Initial · LIVE_LLM · voice mode] design_name: {m1.get('design_name')} / family: {m1.get('design_family')}",
              f"STT: {transcript['initial'] and transcript['initial'].get('stt_text')!r}",
              f"요약: {m1.get('design_summary')}", "보이는 특징: " + " / ".join(m1.get("visible_features") or []),
              f"judge: {m1.get('judge')} / metadata error: {m1.get('error')}",
              f"diversity: family_key {meta['v1']['family_key']} · history_summary_used {m1.get('history_summary_used')} · recent_family_count {m1.get('recent_family_count')} · diversity_hint_applied {m1.get('diversity_hint_applied')}"]
    footer = (f"Round {k} v1 · {c1['category']}/{c1['support_style']} seat {c1['seat_dims'][0]}x{c1['seat_dims'][1]} · history {'used' if m1.get('history_summary_used') else 'none'}{' +hint' if m1.get('diversity_hint_applied') else ''} · Design v{d1['design_version']} · blocks {s1['blocks']} · max layer {s1['max_layer']} · "
              f"A production {plan1_prod['status']} / 표시 {plan1['status']} Remaining {len(plan1['plan']['steps'])} · source=LIVE_LLM · voice")
    saved = show_hmi(app, window, d1, plan1["plan"], {"current_revision": 0, "blocks": []}, f"Round {k} · v1 · {m1.get('design_name')}", footer, notice, os.path.join(rdir, "v1_hmi.png"))
    meta["v1"]["hmi_png"] = saved
    _wait_enter(app, "\nv1 HMI 표시 중. [Enter] 다음 단계(Human Error → TTS 질문)")

    # Human error scenario (fixture, 순환)
    sc = None
    for off in range(len(SCENARIOS)):
        sid, desc, tags, shifts, rot = SCENARIOS[(k - 1 + off) % len(SCENARIOS)]
        sc = make_scenario(d1, plan1["plan"], tags, shifts, rot)
        if sc:
            sc.update(id=sid, description=desc, requested=SCENARIOS[(k - 1) % len(SCENARIOS)][0]); break
    if not sc:
        dump(); return fail("scenario", "no valid human-error placement for this v1")
    meta["scenario"] = {kk: sc[kk] for kk in ("id", "description", "requested", "a_step", "tags", "expected", "actual", "placed_before")}
    e, a = sc["expected"], sc["actual"]
    print(f"Human Error {sc['id']} ({sc['description']}): Step {sc['a_step']} expected ({e['x']},{e['y']}) L{e['layer']} {e['orientation_deg']}° → actual ({a['x']},{a['y']}) L{a['layer']} {a['orientation_deg']}° | Current {len(sc['current']['blocks'])}블록", flush=True)
    print("TTS 질문이 재생된 뒤 안내가 나오면 자유롭게 답하세요(예: \"일부러 그렇게 놨어요\", \"좀 더 넓고 화려하게 하고 싶어요\").", flush=True)

    rec.stage = "revision"
    rec.phrase, rec.debug_dir, rec.events = REVISION_PHRASE, os.path.join(rdir, "stt_revision"), []
    questions = []
    t = time.monotonic()
    v2 = main.run_intervention(d1, sc["current"]["blocks"], sc["differences"], text_answers=None, on_question=lambda q: (questions.append(q), print(f"\n[TTS 질문]\n{q}", flush=True)))
    dt = time.monotonic() - t
    transcript["revision"] = rec.events; transcript["question"] = questions; transcript["tts"] = list(rec.tts_log)
    for ev in rec.events:
        ev["interpreted"] = dialogue.parse_response(ev["stt_text"]) if isinstance(ev.get("stt_text"), str) else None
    json.dump({"envelope": v2, "current": sc["current"], "differences": sc["differences"], "v1": d1}, open(os.path.join(rdir, "v2.json"), "w"), ensure_ascii=False, indent=2)
    meta["v2"] = {"status": v2["status"], "hri_result": v2["hri_result"], "error": v2["error"], "seconds": round(dt, 1), "questions": len(questions),
                  "style_hint": (v2["design_metadata"] or {}).get("style_hint")}
    if v2["status"] != "OK" or v2["hri_result"] != dialogue.REVISE or not v2["design"]:
        dump(); return fail("v2", f"{v2['status']} {v2['hri_result']} {v2['error']}")
    d2 = v2["design"]; m2 = v2["design_metadata"] or {}; cur = sc["current"]
    plan2_prod, plan2 = plan_both(d2, cur)
    preserved_multiset = contains_current(d2["blocks"], cur["blocks"])
    preserved = validator.validate_revised({"blocks": d2["blocks"]}, cur["blocks"]) == [] and preserved_multiset
    j = m2.get("judge") or {}
    meta["v2"].update(shape=shape(d2["blocks"]), validator=validator.validate_design(d2), preserved=preserved, a_production=plan2_prod["status"], a_shown=plan2["status"],
                      preserved_multiset=preserved_multiset, verdict=j.get("verdict"), chair_likeness=j.get("chair_likeness"),
                      richer_than_previous=j.get("richer_than_previous"), total_latency_s=round(dt, 1),
                      fingerprint=fingerprint(d2["blocks"]), design_name=m2.get("design_name"), design_family=m2.get("design_family"), judge=j,
                      regenerations=m2.get("regenerations"), interpretation_status=m2.get("interpretation_status"), metadata_error=m2.get("error"), design_version=d2["design_version"])
    print(f"v2: {meta['v2']['shape']} | validator {meta['v2']['validator']} | preserved {preserved} | A production {plan2_prod['status']} / 표시 {plan2['status']} | "
          f"{m2.get('design_name')} [{m2.get('design_family')}] verdict {j.get('verdict')} regen {m2.get('regenerations')} {dt:.1f}s", flush=True)
    print(stats_line("v2", m2.get("design_family"), meta["v2"]["shape"], meta["v2"]["validator"],
                     f" · Current preserved {preserved} · judge {j.get('verdict')} (chair {j.get('chair_likeness')}, richer {j.get('richer_than_previous')})"
                     f" · style_hint {m2.get('style_hint')} · v2 total {dt:.1f}s"), flush=True)
    if not plan2["plan"]:
        dump(); return fail("v2_plan", f"A planner: {plan2.get('errors')}")
    s2 = meta["v2"]["shape"]; hi = m2.get("human_interpretation") or {}
    notice = [f"[v2 Revised · LIVE_LLM · voice mode] design_name: {m2.get('design_name')} / family: {m2.get('design_family')}",
              f"Human Error {sc['id']}: Step {sc['a_step']} expected ({e['x']},{e['y']})L{e['layer']} → actual ({a['x']},{a['y']})L{a['layer']} · Current preserved {preserved}",
              f"STT 응답: {[ev.get('stt_text') for ev in rec.events]} → {[ev.get('interpreted') for ev in rec.events]}",
              "사람 해석: " + " / ".join(f"{kk}: {hi.get(kk)}" for kk in ("placed_differently", "interpretation", "imagined_concept", "lego_redesign", "why_final_shape")),
              "보이는 특징: " + " / ".join(m2.get("visible_features") or []),
              f"judge: verdict {j.get('verdict')} · recognizable_family {j.get('recognizable_family')} · family_confidence {j.get('family_confidence')} · silhouette {j.get('silhouette_clarity')} · "
              f"explanation_required {j.get('explanation_required_to_understand')} · score {j.get('completeness_score')} · regenerations {m2.get('regenerations')} · status {m2.get('interpretation_status')} · error {m2.get('error')}",
              f"chair_likeness {j.get('chair_likeness')} · richer_than_previous {j.get('richer_than_previous')} ({j.get('richer_why')}) · style_hint {m2.get('style_hint')} · "
              f"red {s2['red']} · 1x2x1 {s2['1x2x1']} · v2 total {dt:.1f}s"]
    footer = (f"Round {k} v2 · {sc['id']} exp ({e['x']},{e['y']})L{e['layer']}→act ({a['x']},{a['y']})L{a['layer']} · Current {len(cur['blocks'])}블록 · Design v{d2['design_version']} · blocks {s2['blocks']} · max layer {s2['max_layer']} · "
              f"preserved {preserved} · A production {plan2_prod['status']} / 표시 {plan2['status']} Remaining {len(plan2['plan']['steps'])} · {j.get('verdict')} · regen {m2.get('regenerations')} · source=LIVE_LLM · voice")
    saved = show_hmi(app, window, d2, plan2["plan"], cur, f"Round {k} · v2 · {m2.get('design_name')}", footer, notice, os.path.join(rdir, "v2_hmi.png"))
    meta["v2"]["hmi_png"] = saved
    meta["status"] = "OK"; dump()
    return meta


# ---------------------------------------------------------------- summary
def summarize(out, rounds):
    rows = []; agg = Counter(); fams = Counter(); sups = Counter(); fps = Counter(); shapes = Counter(); v2fams = Counter()
    for k in range(1, rounds + 1):
        p = os.path.join(out, f"round{k:02d}", "metadata.json"); tp = os.path.join(out, f"round{k:02d}", "transcript.json")
        if not os.path.exists(p):
            rows.append([k, "-", "미실행"] + [""] * 15); continue
        m = json.load(open(p)); tr = json.load(open(tp)) if os.path.exists(tp) else {}
        v1, v2, sc = m.get("v1") or {}, m.get("v2") or {}, m.get("scenario") or {}
        stt1 = (tr.get("initial") or {}).get("stt_text"); rev = tr.get("revision") or []
        stt2 = " / ".join(str(ev.get("stt_text")) for ev in rev); interp = [ev.get("interpreted") for ev in rev]
        j = v2.get("judge") or {}
        err = f"{sc.get('id')} {sc.get('a_step')} ({(sc.get('expected') or {}).get('x')},{(sc.get('expected') or {}).get('y')})L{(sc.get('expected') or {}).get('layer')}→({(sc.get('actual') or {}).get('x')},{(sc.get('actual') or {}).get('y')})" if sc else ""
        s1, s2 = v1.get("shape") or {}, v2.get("shape") or {}
        pref = (tr.get("preference") or {}).get("stt_text")

        def counts(sh):
            return f"{sh.get('blocks')}/{sh.get('red')}/{sh.get('1x2x1')}/L{sh.get('max_layer')}" if sh else ""

        rows.append([k, stt1, pref, v1.get("status"), v1.get("selected_family") or v1.get("design_family"), counts(s1),
                     "PASS" if v1.get("validator") == [] else v1.get("validator"), err,
                     stt2 + (f" → {interp}" if interp else ""), v2.get("style_hint"), j.get("design_family") or v2.get("design_family"), counts(s2),
                     v2.get("preserved"), "PASS" if v2.get("validator") == [] else v2.get("validator"), j.get("verdict"),
                     f"{j.get('chair_likeness')}/{j.get('richer_than_previous')}", v2.get("regenerations"), v2.get("total_latency_s", v2.get("seconds"))])
        agg["rounds"] += 1
        agg["initial_stt_ok"] += bool(stt1 and "의자" in stt1); agg["v1_ok"] += v1.get("status") == "OK"
        agg["history_used"] += bool(v1.get("history_summary_used")); agg["hint_applied"] += bool(v1.get("diversity_hint_applied"))
        if v1.get("family_key"): fams[v1["family_key"]] += 1
        if v1.get("support"): sups[v1["support"]] += 1
        if v1.get("fingerprint"): fps[v1["fingerprint"]] += 1
        if v1.get("shape_key"): shapes[v1["shape_key"]] += 1
        agg["revision_stt_ok"] += any(i == dialogue.REVISE for i in interp)
        agg["v2_ok"] += v2.get("status") == "OK" and m.get("status") == "OK"
        agg["preserved"] += bool(v2.get("preserved")); agg["validator_pass_v2"] += v2.get("validator") == []
        agg["a_ready_production"] += v2.get("a_production") == "READY"; agg["a_ready_shown"] += v2.get("a_shown") == "READY"
        agg["showcase"] += j.get("verdict") == "SHOWCASE"; agg["not_yet"] += j.get("verdict") == "NOT_YET"
        agg["regen0"] += v2.get("regenerations") == 0; agg["regen1"] += v2.get("regenerations") == 1
        if v2.get("design_family"): v2fams[v2["design_family"]] += 1
    head = ("| Round | Initial STT | 선호 답 | v1 status | v1 selected family | v1 blocks/red/1x2x1/max layer | v1 validator | Human Error | "
            "Revision STT | style_hint | v2 family (judge) | v2 blocks/red/1x2x1/max layer | Current preserved | v2 validator | Judge verdict | "
            "chair/richer | Regen | v2 total s |")
    lines = [head, "|" + "---|" * 18] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    n = agg["rounds"] or 1
    dup_exact = sum(c - 1 for c in fps.values() if c > 1); dup_shape = sum(c - 1 for c in shapes.values() if c > 1)
    lines += ["", f"실행된 Round: {agg['rounds']}/{rounds}", "", "Initial:",
              f"- STT 성공('의자' 포함): {agg['initial_stt_ok']}/{n}", f"- v1 생성 성공: {agg['v1_ok']}/{n}",
              f"- family 수: {len(fams)} {dict(fams)}", f"- support style 수: {len(sups)} {dict(sups)}",
              f"- exact duplicate: {dup_exact}", f"- shape duplicate(shape_key): {dup_shape}",
              f"- history_summary_used 횟수: {agg['history_used']}", f"- diversity_hint_applied 횟수: {agg['hint_applied']}", "", "Revised:",
              f"- 답변 STT가 REVISE로 해석: {agg['revision_stt_ok']}/{n}", f"- v2 생성 성공: {agg['v2_ok']}/{n}", f"- Current preserved: {agg['preserved']}/{n}",
              f"- Validator PASS(v2): {agg['validator_pass_v2']}/{n}", f"- A READY(production 4층): {agg['a_ready_production']}/{n} · A READY(표시용 5층): {agg['a_ready_shown']}/{n}",
              f"- SHOWCASE {agg['showcase']} / NOT_YET {agg['not_yet']}", f"- regeneration 0회 {agg['regen0']} / 1회 {agg['regen1']}", f"- v2 family: {dict(v2fams)}"]
    text = "\n".join(lines)
    open(os.path.join(out, "summary.md"), "w").write(text + "\n")
    print("\n" + text); print(f"\nsummary saved: {os.path.join(out, 'summary.md')}")


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5); ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--out", default=os.path.expanduser("~/c_voice_e2e_10runs")); ap.add_argument("--summary", action="store_true")
    ap.add_argument("--debug-audio", action="store_true", help="listen/TTS마다 시각·보정·게이트·Whisper 원문·no_speech_prob 출력")
    args = ap.parse_args(); DEBUG["audio"] = args.debug_audio
    os.makedirs(args.out, exist_ok=True); TOTAL["rounds"] = args.rounds
    if args.summary:
        summarize(args.out, args.rounds); return
    missing = [name for name in (voice.STT_KEY_ENV, llm.LLM_KEY_ENV, voice.TTS_KEY_ENV) if not os.environ.get(name)]
    if os.environ.get("C_DESIGN_USE_LLM") != "1" or missing:
        sys.exit(f"환경 확인: C_DESIGN_USE_LLM=1 필요, 미설정 key env: {missing} (값은 출력하지 않음)")
    print(f"production 경로 · model {os.environ.get('OPENAI_MODEL') or llm.DEFAULT_MODEL} · STT {os.environ.get('OPENAI_STT_MODEL') or voice.DEFAULT_STT_MODEL} · "
          f"keys {voice.STT_KEY_ENV}/{llm.LLM_KEY_ENV}/{voice.TTS_KEY_ENV} configured · validator MAX_LAYER {validator.MAX_LAYER} MAX_BLOCKS {validator.MAX_BLOCKS} · "
          f"planner MAX_LAYER {planner.MAX_LAYER}(production) · LLM timeout {llm.TIMEOUT_SECONDS}s · out {args.out} · "
          f"history {('dir ' + (os.environ.get(history.HISTORY_DIR_ENV) or '(메모리만)') + ' · entries ' + str(len(history.recent()))) if history else '(모듈 없음)'}", flush=True)
    from PyQt5.QtCore import QSize
    from PyQt5.QtWidgets import QApplication
    from app.qt_hmi import HmiWindow
    app = QApplication.instance() or QApplication([])
    window = HmiWindow(screen_size=QSize(1600, 1000))
    rec = ListenRecorder(); rec.install()
    try:
        k = args.start
        while k <= args.rounds:
            meta = run_round(k, args.out, app, window, rec)
            if meta.get("status") == "OK":
                ans = _wait_enter(app, f"\nRound {k} 완료 · v2 HMI 표시 중. [Enter] 다음 Round / r 이 Round 다시 / q 종료")
            else:
                ans = _wait_enter(app, f"\nRound {k} FAILED ({meta.get('failed_stage')}: {meta.get('reason')}). [Enter] 다음 Round로 / r 이 Round 다시 / q 종료")
            if ans == "q":
                break
            if ans != "r":
                k += 1
    finally:
        rec.uninstall(); window.close()
    summarize(args.out, args.rounds)


if __name__ == "__main__":
    main_cli()
