#!/usr/bin/env python3
"""Full Voice HRI E2E (C-side test harness, Wave 6 2026-10-12). production 코드는 바꾸지 않는다. Robot·Camera·DB·MoveIt 없음.

한 번의 lifecycle 안에서 C가 사용자에게 말을 거는 네 상황을 순서대로 겪는다(모두 실제 C public API):

    1. Initial      create_initial_design(voice) → Candidate v1 → Preview → review → APPROVE → Approved v1
    2. Design Change [NEXT VOICE INPUT] 변경 요청 1회 listen → run_design_change(reason=발화) → REVISE → Candidate v2
                    → Preview → review → APPROVE → Approved v2 (Current = Approved의 1층 블록, 조립 중 가정)
    3. Difference   caller-made Difference(1층 블록 하나 이동, CONTRACT §5.2) → run_intervention → REVISE → Candidate v3
                    → Preview → review → APPROVE → Approved v3 (Current 보존)
    4. Plan failure 실제 A handle_whole_plan(read-only) → NO_FEASIBLE_ORDER(아니면 fixture 주입) → Robot HOLD →
                    run_design_change(planning_failure=…) → REVISE → Candidate v4 → Preview → review → APPROVE → Approved v4
                    → A Replan 1회(read-only) → STOP (robot_calls 0)

    python3 scripts/c_full_voice_hri_e2e.py --mode mic --show-preview --out full_hri_$(date +%Y%m%d_%H%M)
    python3 scripts/c_full_voice_hri_e2e.py --mode text --answers ...9개...        # offline(Mock 또는 stub LLM)

--mode mic: 실제 마이크·Whisper STT·TTS(C의 voice.listen/speak 그대로). 각 stage 직전에 [NEXT VOICE INPUT] 안내를 출력한다.
--mode fake-voice: voice.listen만 --answers로 대체(TTS는 실제). --mode text: C API에 text_answers로 답을 준다(TTS 없음).
--answers 순서(9개): Initial 요청, Initial 검토, 변경 요청, 변경 확인, 변경 검토, Difference 답, Difference 검토,
Planning failure 답, Planning failure 검토. 검토가 MODIFY면 다음 답을 하나 더 쓴다(최대 3회).

출력(--out DIR): events.jsonl(진행·질문·TTS·STT·caller 이벤트), NN_<stage>.json(C envelope), preview_<stage>.png,
summary.json, 그리고 터미널의 === FULL HRI SUMMARY ===. 키는 환경 변수로만 받고 값은 출력하지 않는다.
"""

import argparse
import json
import os
import sys
import time
from copy import deepcopy

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, ROOT)
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.join(ROOT, "tests", "unit", "c_design"))  # c_facing_helper(테스트 전용 판정기)

from app.c_design import dialogue, llm, main, validator, voice  # noqa: E402
import c_facing_helper as facing  # noqa: E402
import c_stage3_integration_smoke as smoke  # noqa: E402

MAX_REVIEWS = 3
STAGES = ("initial", "design_change", "difference", "plan_failure")
SPEECH_GUIDE = [
    ("Initial 질문", "편안한 침대 같은 느낌의 의자를 만들어줘"),
    ("Initial Preview 검토", "좋아, 이대로 해"),
    ("Direct Design Change 요청", "등받이를 조금 더 높이고 싶어"),
    ("변경 확인 질문", "응, 수정해줘"),
    ("Direct Change Preview 검토", "나쁘지 않은 것 같아"),
    ("Difference 질문", "이대로 유지해"),
    ("Difference Revised Preview 검토", "좋아, 이대로 해"),
    ("Planning Failure 질문", "응, 다시 설계해줘"),
    ("Planning Failure Revised Preview 검토", "나쁘지 않은 것 같아"),
]
DEFAULT_ANSWERS = [sentence for _, sentence in SPEECH_GUIDE]


def _now():
    now = time.time()
    return time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}"


def make_hri_difference(approved):
    """사람이 1층 블록 하나를 다른 방향(90° 회전, 제자리)으로 놓은 Difference. Current = 1층 블록 전체(회전 블록 포함).

    CONTRACT §5.2를 만족하고(check_intervention_input == []), Current 자체가 support를 지키며, Approved의 나머지 블록을
    그대로 얹어도 유효한(연결·지지 유지) 블록을 고른다. 그런 블록이 없으면 smoke.make_difference(위치 이동)로 돌아간다.
    """
    legs = [b for b in approved["blocks"] if b["layer"] == 1]
    upper = [b for b in approved["blocks"] if b["layer"] != 1]
    for leg in legs:
        if 90 not in validator.ORIENTATIONS.get(leg["brick_type"], ()) or 0 not in validator.ORIENTATIONS.get(leg["brick_type"], ()):
            continue
        rotated = dict(leg, orientation_deg=90 - leg["orientation_deg"])
        current = [rotated if b is leg else dict(b) for b in legs]
        differences = [{"expected": dict(leg), "actual": rotated}]
        if (validator.check_intervention_input(approved, current, differences) == []
                and not validator.current_support_violations(current)
                and validator.validate_revised({"blocks": current + upper}, current) == []):
            return current, differences, "orientation"
    current, differences = smoke.make_difference(approved)
    return current, differences, "position"


class StageStop(Exception):
    """한 stage가 성공으로 끝나지 않아 lifecycle을 멈춘다(Approved·Current 유지, Robot 0)."""


class Harness:
    def __init__(self, mode, answers, out_dir, show_preview):
        self.mode = mode
        self.feed = smoke.AnswerFeed(list(answers)) if mode != "mic" else None
        self.out = out_dir
        self.show_preview = show_preview
        self.viewer = self.app = None
        self.events = []
        self.stages = {}
        self.approved = None
        self.current = None
        self.candidate = None  # (design, metadata)
        self.candidate_phase = None
        self.robot_calls = 0
        self.replan_calls = 0
        self.previews = []
        self.n = 0
        self.failed = False
        self.current_stage = None
        os.makedirs(out_dir, exist_ok=True)
        self._events_file = open(os.path.join(out_dir, "events.jsonl"), "a", encoding="utf-8")

    # ---- 로그/이벤트 ---------------------------------------------------------------------------------------------
    def log(self, kind, text, **extra):
        line = f"[{kind}] {_now()} {text}"
        print(line, flush=True)
        self.events.append({"at": _now(), "stage": self.current_stage, "kind": kind, "text": text, **extra})
        self._events_file.write(json.dumps(self.events[-1], ensure_ascii=False) + "\n")
        self._events_file.flush()

    def on_question(self, sentence):
        self.log("C-QUESTION", sentence)

    def on_progress(self, event):
        quoted = event["stage"] in ("ACK", "REVIEW_ACK", "KEEP_ACK")
        self.log("C-" + event["stage"], f'"{event["message"]}"' if quoted else event["message"])

    def install_voice_logging(self):
        """실제 TTS 재생·STT 전사를 이벤트로 남긴다(함수를 감쌀 뿐 production 동작은 그대로)."""
        real_speak, real_listen = voice.speak, voice.listen

        def speak(text):
            self.log("TTS", text)
            return real_speak(text)

        def listen(on_ready=None, mode="short", beep=False):
            text = real_listen(on_ready=on_ready, mode=mode, beep=beep)
            self.log("STT", json.dumps(text, ensure_ascii=False), error=voice.last_error() if text in (None, "") else None)
            return text
        voice.speak, voice.listen = speak, listen

    # ---- 답/안내 ------------------------------------------------------------------------------------------------
    def next_input(self, label, example):
        self.log("NEXT VOICE INPUT", f"{label} → 예: \"{example}\"")

    def answer(self, api):
        """(진행 여부, text 모드 답 또는 None=음성 모드)."""
        if self.mode == "mic" or self.mode == "fake-voice":
            if self.mode == "fake-voice" and self.feed.remaining() == 0:
                self.log("CALLER", f"answers exhausted before {api} → stop")
                return False, None
            return True, None
        if self.feed.remaining() == 0:
            self.log("CALLER", f"answers exhausted before {api} → stop")
            return False, None
        return True, self.feed.take()

    # ---- 기록 -----------------------------------------------------------------------------------------------------
    def save(self, name, obj):
        self.n += 1
        path = os.path.join(self.out, f"{self.n:02d}_{name}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, ensure_ascii=False, indent=2)
        return path

    def facing_of(self, design, current):
        verdict, info = facing.classify_facing(design, current=current)
        return verdict, info.get("dx")

    def record_candidate(self, stage, envelope, current, api):
        design = envelope["design"]
        row = {"api": api, "status": envelope["status"], "hri": envelope["hri_result"], "error": (envelope["error"] or {}).get("code"),
               "questions": envelope["questions"]}
        if design is not None:
            verdict, dx = self.facing_of(design, current)
            row.update(version=design["design_version"], blocks=len(design["blocks"]),
                       validator="PASS" if validator.validate_design(design) == [] else "FAIL",
                       current_preserved=(validator.validate_revised({"blocks": design["blocks"]}, current) == []
                                          and all(b in design["blocks"] for b in current)) if current is not None else None,
                       facing=verdict, facing_dx=dx)
            meta = envelope["design_metadata"] or {}
            row["metadata"] = {k: meta.get(k) for k in ("source", "style_hint", "selected_family", "design_family")}
            row["judge"] = (meta.get("judge") or {}).get("verdict")
        self.stages.setdefault(stage, {})[api] = row
        self.log("CALLER", f"response status={row['status']} hri={row['hri']} version={row.get('version')} "
                           f"validator={row.get('validator')} current_preserved={row.get('current_preserved')} facing={row.get('facing')}")
        return row

    # ---- Preview --------------------------------------------------------------------------------------------------
    def preview(self, stage, design, metadata, round_=None, diff=None):
        import c_design_hmi_render as render
        blocks = design["blocks"]
        meta = metadata or {}
        review = meta.get("review") or {}
        suffix = f"_r{round_}" if round_ else ""
        title = f"C-side Test Preview — {stage}{suffix} — Not D Production HMI"
        lines = [f"design_version {design['design_version']} · review.round {review.get('round', 0)} · {render.counts_line(blocks)}",
                 " · ".join(f"{k} {meta.get(k)}" for k in ("selected_family", "design_family", "style_hint") if meta.get(k)) or "metadata 없음",
                 "fake PREVIEW_READY · C-side test visualization (Not D Production HMI)"]
        path = os.path.join(self.out, f"preview_{stage}{suffix}.png")
        if diff is not None and self.approved is not None:
            captions = [[f"Approved v{self.approved['design_version']}"], ["Current + Difference(actual 주황)"],
                        [f"Candidate v{design['design_version']}"]]
            image = render.compose_v2(title, self.approved["blocks"], self.current, diff["expected"], diff["actual"], blocks,
                                      captions, lines, path)
        else:
            image = render.compose_v1(title, blocks, lines, path)
        if self.viewer is not None:
            self.viewer.show(self.app, image, title)
        self.previews.append({"stage": stage, "round": round_, "png": path, "shown_at": _now()})
        self.candidate_phase = "REVIEW"
        self.log("CALLER", f"PREVIEW_READY candidate v{design['design_version']} blocks {len(blocks)} → {path}")

    # ---- Review loop ---------------------------------------------------------------------------------------------
    def review(self, stage, kind, label, example, extra=None, diff=None):
        """MODIFY면 재생성·재Preview(최대 MAX_REVIEWS). APPROVE면 Approved 교체 후 True. 그 밖은 StageStop."""
        revised_inputs = {}
        if kind == "revised":
            revised_inputs = {"previous_design": self.approved, "current": self.current, "differences": []}
            if extra:
                revised_inputs.update(extra)
        for attempt in range(MAX_REVIEWS):
            if self.candidate_phase != "REVIEW":
                raise RuntimeError("review before PREVIEW_READY")
            self.next_input(label, example)
            go, text = self.answer("review_design_candidate")
            if not go:
                raise StageStop("no answer for review")
            design, metadata = self.candidate
            envelope = main.review_design_candidate(design, kind=kind, design_metadata=metadata,
                                                    text_answers=None if text is None else [text],
                                                    on_question=self.on_question, on_progress=self.on_progress, **revised_inputs)
            self.save(f"{stage}_review", envelope)
            row = self.record_candidate(stage, envelope, self.current if kind == "revised" else None,
                                        f"review_design_candidate#{attempt + 1}")
            if envelope["status"] != "OK":
                raise StageStop(f"review {envelope['status']} {row['error']}")
            if envelope["hri_result"] == dialogue.APPROVE:
                if envelope["design"] != design:
                    raise StageStop("stale APPROVE (design differs from the displayed candidate)")
                self.approved = deepcopy(envelope["design"])
                self.candidate = (envelope["design"], envelope["design_metadata"])
                self.candidate_phase = None
                self.stages[stage]["approved_version"] = self.approved["design_version"]
                self.log("CALLER", f"adopt approved v{self.approved['design_version']} blocks {len(self.approved['blocks'])}")
                return True
            if envelope["hri_result"] != dialogue.MODIFY or envelope["design"] is None:
                raise StageStop(f"review {envelope['hri_result']} (no auto-approve; stage ends)")
            new = envelope["design"]
            self.candidate = (new, envelope["design_metadata"])
            round_ = ((envelope["design_metadata"] or {}).get("review") or {}).get("round")
            self.log("CALLER", f"MODIFY → new candidate v{new['design_version']} round {round_} (not approved)")
            self.preview(stage, new, envelope["design_metadata"], round_=round_, diff=diff)
        raise StageStop(f"{MAX_REVIEWS} reviews without APPROVE")

    # ---- Stages ---------------------------------------------------------------------------------------------------
    def stage_initial(self):
        self.current_stage = "initial"
        self.next_input("Initial 질문(인사 뒤)", SPEECH_GUIDE[0][1])
        go, text = self.answer("create_initial_design")
        if not go:
            raise StageStop("no answer for initial")
        envelope = main.create_initial_design(text=text, on_question=self.on_question, on_progress=self.on_progress)
        self.save("initial", envelope)
        row = self.record_candidate("initial", envelope, None, "create_initial_design")
        if envelope["status"] != "OK" or envelope["design"] is None:
            raise StageStop(f"initial {envelope['status']} {row['error']}")
        self.candidate = (envelope["design"], envelope["design_metadata"])
        self.preview("initial", *self.candidate)
        self.review("initial", "initial", *SPEECH_GUIDE[1])
        # 조립 중 가정: Approved v1의 1층 블록이 실제로 놓였다고 본다(Current).
        self.current = [dict(b) for b in self.approved["blocks"] if b["layer"] == 1]
        self.log("CALLER", f"Current (assumed assembled) = {len(self.current)} layer-1 blocks of approved v{self.approved['design_version']}")

    def stage_design_change(self):
        self.current_stage = "design_change"
        self.next_input("Direct Design Change 요청(beep 뒤 한 문장)", SPEECH_GUIDE[2][1])
        if self.mode == "mic":
            request = voice.listen(mode="free", beep=True)
        else:
            go, request = self.answer("design_change_request")
            if not go:
                raise StageStop("no change request")
            if self.mode == "fake-voice":
                request = voice.listen(mode="free", beep=True)
        if not dialogue.is_meaningful(request or ""):
            raise StageStop("change request not heard")
        self.stages.setdefault("design_change", {})["request"] = request
        self.log("CALLER", f"change request → run_design_change(reason={request!r})")
        self.next_input("변경 확인 질문", SPEECH_GUIDE[3][1])
        go, text = self.answer("run_design_change")
        if not go:
            raise StageStop("no answer for design change")
        envelope = main.run_design_change(self.approved, self.current, reason=request,
                                          text_answers=None if text is None else [text],
                                          on_question=self.on_question, on_progress=self.on_progress)
        self.save("design_change", envelope)
        row = self.record_candidate("design_change", envelope, self.current, "run_design_change")
        if envelope["status"] != "OK" or envelope["hri_result"] != dialogue.REVISE or envelope["design"] is None:
            raise StageStop(f"design change {envelope['status']} {envelope['hri_result']} {row['error']}")
        self.candidate = (envelope["design"], envelope["design_metadata"])
        self.preview("design_change", *self.candidate)
        self.review("design_change", "revised", *SPEECH_GUIDE[4], extra={"change_reason": request})

    def stage_difference(self):
        self.current_stage = "difference"
        current, differences, kind = make_hri_difference(self.approved)
        if current is None:
            raise StageStop("could not build a Difference from the Approved layer-1 blocks")
        self.current, self.differences = current, differences
        diff = differences[0]
        self.stages.setdefault("difference", {})["difference"] = diff
        self.stages["difference"]["difference_kind"] = kind
        self.log("CALLER", f"Difference injected (caller-made {kind}, §5.2): {diff['expected']['brick_type']} "
                           f"({diff['expected']['x']},{diff['expected']['y']},{diff['expected']['orientation_deg']}°) → "
                           f"({diff['actual']['x']},{diff['actual']['y']},{diff['actual']['orientation_deg']}°); Current {len(current)} blocks")
        self.next_input("Difference 질문", SPEECH_GUIDE[5][1])
        go, text = self.answer("run_intervention")
        if not go:
            raise StageStop("no answer for difference")
        envelope = main.run_intervention(self.approved, self.current, self.differences,
                                         text_answers=None if text is None else [text],
                                         on_question=self.on_question, on_progress=self.on_progress)
        self.save("difference", envelope)
        row = self.record_candidate("difference", envelope, self.current, "run_intervention")
        if envelope["status"] != "OK" or envelope["hri_result"] != dialogue.REVISE or envelope["design"] is None:
            raise StageStop(f"difference {envelope['status']} {envelope['hri_result']} {row['error']}")
        self.candidate = (envelope["design"], envelope["design_metadata"])
        self.preview("difference", *self.candidate, diff=diff)
        self.review("difference", "revised", *SPEECH_GUIDE[6], extra={"differences": self.differences}, diff=diff)

    def stage_plan_failure(self):
        self.current_stage = "plan_failure"
        first = smoke.a_whole_plan(self.approved, self.current, generation=1)
        self.stages.setdefault("plan_failure", {})["a_first"] = first
        self.log("A", f"handle_whole_plan(approved v{self.approved['design_version']}) → {first['calculation_status']} "
                      f"plan={first['plan_status']} execution_allowed={first['execution_allowed']}")
        if first["calculation_status"] == "NO_FEASIBLE_ORDER":
            failure = smoke.planning_failure_from(first)
            self.log("CALLER", "planning_failure from the real A result")
        else:
            failure = {"failure_code": "NO_FEASIBLE_ORDER", "redesign_required": True, "retryable": False, "blocked_blocks": [],
                       "detail": f"injected (real A gave {first['calculation_status']})"}
            self.log("CALLER", f"real A gave {first['calculation_status']} → NO_FEASIBLE_ORDER fixture injected for the HRI test")
        self.robot_hold = True
        self.log("CALLER", "Robot HOLD (no execution)")
        self.stages["plan_failure"]["planning_failure"] = failure
        self.next_input("Planning Failure 질문", SPEECH_GUIDE[7][1])
        go, text = self.answer("run_design_change(planning_failure)")
        if not go:
            raise StageStop("no answer for planning failure")
        envelope = main.run_design_change(self.approved, self.current, reason="PLANNING_FAILURE", planning_failure=failure,
                                          text_answers=None if text is None else [text],
                                          on_question=self.on_question, on_progress=self.on_progress)
        self.save("plan_failure", envelope)
        row = self.record_candidate("plan_failure", envelope, self.current, "run_design_change")
        for question in envelope["questions"]:
            if "NO_FEASIBLE_ORDER" in question or "{" in question or "[" in question:
                raise StageStop("planning failure question leaked a machine code")
        if envelope["status"] != "OK" or envelope["hri_result"] != dialogue.REVISE or envelope["design"] is None:
            raise StageStop(f"planning failure {envelope['status']} {envelope['hri_result']} {row['error']}")
        self.candidate = (envelope["design"], envelope["design_metadata"])
        self.preview("plan_failure", *self.candidate)
        self.review("plan_failure", "revised", *SPEECH_GUIDE[8],
                    extra={"change_reason": "PLANNING_FAILURE", "planning_failure": failure})
        self.replan_calls += 1
        replan = smoke.a_whole_plan(self.approved, self.current, generation=2)
        self.stages["plan_failure"]["replan"] = replan
        self.log("A", f"replan handle_whole_plan(approved v{self.approved['design_version']}) → {replan['calculation_status']} "
                      f"plan={replan['plan_status']} steps={replan['steps']} execution_allowed={replan['execution_allowed']}")
        self.log("CALLER", f"STOP: robot_calls={self.robot_calls} replan_calls={self.replan_calls} (Robot not executed)")

    # ---- run / summary --------------------------------------------------------------------------------------------
    def run(self):
        print("=== FULL VOICE HRI E2E ===\n다음 문장을 순서대로 말해주세요(안내용, 정확히 같지 않아도 됩니다):", flush=True)
        for i, (label, sentence) in enumerate(SPEECH_GUIDE, start=1):
            print(f"{i}. {label}: \"{sentence}\"", flush=True)
        print(flush=True)
        try:
            self.stage_initial()
            self.stage_design_change()
            self.stage_difference()
            self.stage_plan_failure()
        except StageStop as stop:
            self.failed = True
            self.log("CALLER", f"lifecycle stopped at stage {self.current_stage}: {stop} (Approved·Current 유지, robot_calls {self.robot_calls})")
        finally:
            if self.viewer is not None:
                self.viewer.close()
        return self.summary()

    def summary(self):
        versions = [self.stages.get(s, {}).get("approved_version") for s in STAGES]
        checks = {
            "all_stages_approved": all(v is not None for v in versions),
            "versions_increase": all(a is not None and b is not None and b == a + 1 for a, b in zip(versions, versions[1:])) if all(versions) else False,
            "validator_all_pass": all(r.get("validator") == "PASS" for s in self.stages.values() for r in s.values()
                                      if isinstance(r, dict) and "validator" in r),
            "current_preserved": all(r.get("current_preserved") is True for s in ("design_change", "difference", "plan_failure")
                                     for k, r in self.stages.get(s, {}).items() if isinstance(r, dict) and "current_preserved" in r),
            "facing_no_fail": all(r.get("facing") != "FAIL" for s in self.stages.values() for r in s.values()
                                  if isinstance(r, dict) and "facing" in r),
            "previews_4": len({p["stage"] for p in self.previews}) == 4,
            "robot_calls_0": self.robot_calls == 0,
            "replan_calls_1": self.replan_calls == 1,
        }
        final = "PASS" if not self.failed and all(checks.values()) else "FAIL"
        lines = ["", "=== FULL HRI SUMMARY ==="]
        for stage, title in zip(STAGES, ("Initial", "Direct Change", "Difference", "Planning Failure")):
            data = self.stages.get(stage, {})
            stt = [e["text"] for e in self.events if e["stage"] == stage and e["kind"] == "STT"]
            lines.append(f"{title}:")
            if stage == "plan_failure" and data.get("a_first"):
                lines.append(f"  A first: {data['a_first']['calculation_status']} · question: natural language")
            if stage == "design_change" and data.get("request"):
                lines.append(f"  request: {data['request']!r}")
            lines.append(f"  STT: {', '.join(stt) if stt else '(text mode)'}")
            for api, row in data.items():
                if isinstance(row, dict) and "status" in row:
                    lines.append(f"  {api}: {row['hri']} v{row.get('version')} validator {row.get('validator')} "
                                 f"current {row.get('current_preserved')} facing {row.get('facing')}")
            lines.append(f"  approved: v{data.get('approved_version')}")
            if stage == "plan_failure" and data.get("replan"):
                lines.append(f"  A replan: {data['replan']['calculation_status']} plan={data['replan']['plan_status']}")
        lines += [f"Version sequence: {versions}", f"Current preserved: {checks['current_preserved']}",
                  f"Facing: {[r.get('facing') for s in self.stages.values() for r in s.values() if isinstance(r, dict) and 'facing' in r]}",
                  f"Robot calls: {self.robot_calls}", f"Replan calls: {self.replan_calls}", f"FINAL: {final}"]
        print("\n".join(lines), flush=True)
        summary = {"mode": self.mode, "final": final, "checks": checks, "versions": versions, "stages": self.stages,
                   "previews": self.previews, "robot_calls": self.robot_calls, "replan_calls": self.replan_calls,
                   "tts": [e["text"] for e in self.events if e["kind"] == "TTS"],
                   "stt": [{"stage": e["stage"], "text": e["text"]} for e in self.events if e["kind"] == "STT"],
                   "hri_interpret": [{"stage": e["stage"], "text": e["text"]} for e in self.events if e["kind"] == "C-HRI_INTERPRET"],
                   "generation_model": os.environ.get("OPENAI_MODEL") or llm.DEFAULT_MODEL,
                   "use_llm": os.environ.get("C_DESIGN_USE_LLM") == "1"}
        with open(os.path.join(self.out, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        self._events_file.close()
        return summary


def main_cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("text", "fake-voice", "mic"), default="mic")
    parser.add_argument("--answers", nargs="*", help="text/fake-voice 모드의 답(순서대로, 기본 SPEECH_GUIDE 문장)")
    parser.add_argument("--out", default=f"full_hri_{time.strftime('%Y%m%d_%H%M%S')}", help="결과 디렉터리")
    parser.add_argument("--show-preview", action="store_true", help="Candidate마다 C-side Test Preview 창 표시(fake PREVIEW_READY)")
    args = parser.parse_args(argv)

    use_llm = os.environ.get("C_DESIGN_USE_LLM") == "1"
    print(f"mode {args.mode} · {'LLM' if use_llm else 'Mock(규칙만)'} · generation model "
          f"{os.environ.get('OPENAI_MODEL') or llm.DEFAULT_MODEL} · judge {os.environ.get(llm.JUDGE_MODEL_ENV) or llm.DEFAULT_JUDGE_MODEL}"
          f" · aux {os.environ.get(llm.AUX_MODEL_ENV) or llm.DEFAULT_AUX_MODEL}", flush=True)
    for name in (llm.LLM_KEY_ENV, voice.STT_KEY_ENV, voice.TTS_KEY_ENV):
        print(f"{name}: {'configured' if os.environ.get(name) else 'not set'}", flush=True)
    if args.mode == "mic" and (not use_llm or (os.environ.get("OPENAI_MODEL") or llm.DEFAULT_MODEL) != "gpt-6.1-sol"):
        print("WARNING: mic E2E는 C_DESIGN_USE_LLM=1 OPENAI_MODEL=gpt-6.1-sol을 전제로 한다. 계속 진행한다.", flush=True)

    answers = args.answers if args.answers is not None else DEFAULT_ANSWERS
    harness = Harness(args.mode, answers, args.out, args.show_preview)
    if args.mode == "fake-voice":
        smoke.install_fake_voice(harness.feed)
    if args.mode in ("mic", "fake-voice"):
        harness.install_voice_logging()
    if args.mode == "mic":
        voice.prewarm()
    if args.show_preview:
        from PyQt5.QtWidgets import QApplication
        from c_voice_e2e_c_only import Viewer
        harness.app = QApplication.instance() or QApplication([])
        harness.viewer = Viewer()
    summary = harness.run()
    print(f"saved to {args.out}", flush=True)
    return 0 if summary["final"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main_cli())
