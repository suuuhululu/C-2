#!/usr/bin/env python3
"""Stage 3 Wave 3·4 fake D caller runner (시험용·수동 실행). production 코드는 바꾸지 않는다.

목적: D가 C를 호출하고 response를 받는 흐름을 C 쪽에서 시험한다. 이 스크립트 안의 FakeDCaller는 C public API를 부르고
response를 받아 `[CALLER] PREVIEW_READY (assumed)`를 한 줄 남긴 뒤 다음 API를 부를 뿐이다(C-side caller fixture).
D·HMI·Backend 구현이 아니며 PREVIEW_READY는 caller가 가정한 fake event다(실제 Preview 표시·sleep 없음). 실제 D/HMI
integration은 팀 통합 단계에서 한다. caller는 `approved`(review가 APPROVE를 돌려줄 때만 채택)와 `candidate`(현재 후보와
그 design_metadata)를 따로 들고 있어 Candidate와 Approved를 구분한다.

    python3 scripts/c_stage3_integration_smoke.py                                   # text · full · Mock(규칙만)
    python3 scripts/c_stage3_integration_smoke.py --mode text --scenario review --answers "의자 만들어줘" "좋아 이걸로 하자"
    python3 scripts/c_stage3_integration_smoke.py --mode text --scenario full --out /tmp/s3w3_smoke
    env C_DESIGN_USE_LLM=1 OPENAI_MODEL=gpt-6.1-sol OPENAI_LLM_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" \\
        python3 scripts/c_stage3_integration_smoke.py --mode text --scenario full          # text · LLM
    env C_DESIGN_USE_LLM=1 OPENAI_MODEL=gpt-6.1-sol OPENAI_LLM_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" OPENAI_TTS_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" \\
        python3 scripts/c_stage3_integration_smoke.py --mode fake-voice --scenario full    # fake listen · 실제 TTS
    env C_DESIGN_USE_LLM=1 OPENAI_MODEL=gpt-6.1-sol OPENAI_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" OPENAI_LLM_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" \\
        OPENAI_TTS_API_KEY="$(cat ~/c2_cobot2_API_key.txt)" python3 scripts/c_stage3_integration_smoke.py --mode mic --scenario full

--mode
  text        C API에 텍스트로 답을 준다(음성 없음). C_DESIGN_USE_LLM=1이면 LLM 모드, 아니면 Mock(규칙 해석만).
  fake-voice  이 프로세스 안에서만 voice.listen을 fake로 바꿔 --answers를 listen 호출마다 하나씩 돌려준다(voice.prewarm도
              마이크를 열지 않는 no-op로 바꾼다). voice.speak는 실제 함수 그대로(TTS 키가 없으면 소리 없이 last_error만 남김).
              C API는 음성 모드(text=None·text_answers=None)로 부른다.
  mic         실제 마이크·TTS. C API를 음성 모드로 부르고 listen마다 공통 안내와 [C][STT_RAW] 원문을 출력한다.
--scenario
  initial       create_initial_design만.
  review        Initial → PREVIEW_READY → review(kind="initial")를 MODIFY인 동안 반복(최대 3회) → APPROVE면 채택.
  intervention  Initial 후보를 Approved로 가정 → caller가 Difference 생성 → run_intervention → REVISE면
                PREVIEW_READY → review(kind="revised") 반복.
  full          Initial → PREVIEW_READY → review 반복(APPROVE 채택) → caller Difference → run_intervention →
                PREVIEW_READY → review(kind="revised") 반복.

답(--answers)은 시나리오 전체에서 순서대로 쓴다.
  text 모드: create_initial_design은 답 하나를 text로 받는다(Mock은 목표 문장, 예: "의자 만들어줘"; LLM 되묻기 답은
             --preference로 따로 준다). review 호출마다 다음 답 하나를 text_answers=[답]으로, run_intervention도 다음 답 하나를
             받는다(그래서 C 안의 재질문은 답이 없어 UNCLEAR로 끝난다).
  fake-voice: listen 호출마다 다음 답 하나(C 안의 재질문·되묻기도 답을 하나씩 쓴다). 호출 도중 답이 떨어지면 listen이 None을
             돌려 C가 VOICE_IO_FAILED를 낸다.
  호출 전에 답이 남아 있지 않으면 시나리오를 그 자리에서 멈춘다(로그 한 줄). --answers가 없으면 시나리오별 기본값을 쓴다.
  mic 모드는 --answers를 쓰지 않는다.

Difference(caller가 만든다): Approved의 layer-1 블록 하나를 layer-1 무게중심 바깥쪽으로 1 stud 옮긴다(보드 0..23 안,
다른 layer-1 블록과 겹치지 않음, validator.check_intervention_input == []). Current = layer-1 블록 전체(옮긴 블록 포함),
Difference = [{"expected": 원래 블록, "actual": 옮긴 블록}].

로그: [CALLER] call/response/PREVIEW_READY (assumed)/adopt approved, [C][<STAGE>] 진행(ACK·REVIEW_ACK·KEEP_ACK는 따옴표),
[C][QUESTION], 음성 모드의 [C][STT_RAW]. 마지막에 호출별 lifecycle 요약(status·hri·version·review.round·이전 후보 대비
변경·validator·Current 보존)과 version·round·Current 보존 수열. FAILED envelope이 하나라도 있으면 종료 코드 1.
--out DIR이면 envelope을 DIR/NN_<api>.json, 요약을 DIR/summary.json으로 저장한다(호출별 [C][STAGE] timeline 포함).
--show-preview(명시 옵션)이면 새 Candidate를 받을 때마다 C-side Test Preview 창(scripts/c_voice_e2e_c_only.Viewer, 비차단
QLabel + processEvents)에 그린 뒤에야 다음 review를 부른다: response → PNG 합성 → 창 표시(그려진 뒤) → 로그 →
review(질문 TTS → beep → STT). fake PREVIEW_READY이며 Not D Production HMI다(D Preview integration 아님). Enter 입력 없이
음성만으로 진행하고, 창을 닫아도 흐름은 계속되며 다음 표시 때 다시 뜬다. --render DIR이면 같은 화면을 lifecycle state 이름
PNG로 저장한다: 01_initial_candidate.png, 02_initial_modified_candidate_r<round>.png, 03_revised_candidate.png,
04_revised_modified_candidate_r<round>.png. 후보가 바뀌지 않은 응답(APPROVE·UNCLEAR·CANCEL·KEEP)은 저장·표시하지 않는다.
Initial 후보는 compose_v1(현재 후보), Revised 후보는 compose_v2(Approved v1 | Current+Difference | v2)로 그린다
(scripts/c_design_hmi_render, app/hmi_board.BoardView 재사용). 둘 다 C-side test visualization이며 실제 D Preview가 아니다.
mic 모드는 listen마다 voice._last_capture의 스트림 open/close 시각을 [C][MIC] opened … closed … 한 줄로 출력한다. 키는 환경 변수로만 받고 설정 여부만 출력한다(값은 출력하지 않음).
Mock 모드의 review MODIFY는 후보를 바꾸지 않는다(Stage 3 Wave 2 동작, 오류 아님).
"""

import argparse
import json
import os
import sys
from copy import deepcopy

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPTS_DIR))
sys.path.insert(0, SCRIPTS_DIR)

from app.c_design import dialogue, llm, main, validator, voice  # noqa: E402
import c_voice_review_smoke as review_smoke  # noqa: E402

MAX_REVIEWS = 3  # 한 검토 단계에서 review를 부르는 최대 횟수(MODIFY가 이어질 때)

DEFAULT_ANSWERS = {
    "initial": ["의자 만들어줘"],
    "review": ["의자 만들어줘", "등받이를 더 높게", "좋아 이걸로 하자"],
    "intervention": ["의자 만들어줘", "일부러 그렇게 놨어요", "마음에 들어"],
    # Stage 3 Wave 4 최종 lifecycle: Initial → review MODIFY → APPROVE → Difference REVISE → review(revised) MODIFY → APPROVE
    "full": ["벤치처럼 길고 넓은 의자를 만들고 싶어", "등받이를 조금 더 높게 해줘", "좋아 이걸로 하자",
             "일부러 그렇게 놨어. 조금 더 넓게 만들고 싶어", "조금 더 화려하게 해줘", "마음에 들어. 이걸로 하자"],
}


def _log(line):
    print(line, flush=True)


def on_question(sentence):
    _log(f"[C][QUESTION] {review_smoke._now()} {sentence}")


def on_progress(event):
    quoted = event["stage"] in ("ACK", "REVIEW_ACK", "KEEP_ACK")
    message = f'"{event["message"]}"' if quoted else event["message"]
    _log(f"[C][{event['stage']}] {event['at']} {message}")


class AnswerFeed:
    """--answers를 순서대로 내준다(text 모드는 caller가, fake-voice는 fake listen이 꺼낸다)."""

    def __init__(self, items):
        self.items = list(items)
        self.used = 0

    def remaining(self):
        return len(self.items) - self.used

    def take(self):
        if self.remaining() == 0:
            return None
        self.used += 1
        return self.items[self.used - 1]


def install_fake_voice(feed):
    """이 프로세스 안에서만 voice.listen(답 순서대로)·voice.prewarm(no-op)을 바꾼다. voice.speak는 그대로 둔다."""

    def listen(on_ready=None, mode="short", beep=False):
        if on_ready is not None:
            on_ready()
        text = feed.take()
        if text is None:
            _log("[CALLER] fake-voice answers exhausted during listen → None (C는 VOICE_IO_FAILED로 끝난다)")
            return None
        _log(f'[C][STT_RAW] {review_smoke._now()} "{text}" (fake listen mode={mode} beep={beep})')
        return text

    voice.listen = listen
    voice.prewarm = lambda: True


def install_mic_log():
    """mic 모드: 실제 voice.listen을 감싸 단계에 맞지 않는 검토용 안내 대신 공통 안내와 [C][STT_RAW]만 출력한다."""
    original = voice.listen

    def listen(on_ready=None, mode="short", beep=False):
        def ready():
            _log(">>> 지금 말씀하세요(알림음 뒤에 자유롭게 답해 주세요).")
            if on_ready is not None:
                on_ready()
        text = original(on_ready=ready, mode=mode, beep=beep)
        capture = getattr(voice, "_last_capture", None) or {}
        opened, closed = capture.get("stream_opened_at"), capture.get("stream_closed_at")
        if opened or closed:  # 마이크 스트림이 이번 listen에서 열리고 닫혔는지(voice.record가 남긴 시각, 있는 것만)
            _log("[C][MIC]" + (f" opened {opened}" if opened else "") + (f" closed {closed}" if closed else ""))
        shown = text if text is not None else ""
        _log(f'[C][STT_RAW] {review_smoke._now()} "{shown}"' + (f" (last_error {voice.last_error()})" if text in (None, "") else ""))
        detail = voice.last_http_error() if text in (None, "") else None
        if detail:  # STT HTTP 실패의 세부(429 유형 진단용; key·헤더 비밀값 없음)
            _log("[C][STT_ERROR] " + " ".join(f"{key}={detail.get(key)}" for key in ("http_status", "type", "code", "retry_after"))
                 + f" message={detail.get('message')!r}")
        return text

    voice.listen = listen


def make_difference(approved):
    """Approved의 layer-1 블록 하나를 바깥쪽으로 1 stud 옮긴 (Current, Difference). 만들 수 없으면 (None, None)."""
    layer1 = [{key: block[key] for key in validator.BLOCK_FIELDS} for block in approved["blocks"] if block["layer"] == 1]
    if not layer1:
        return None, None
    studs = [stud for block in layer1 for stud in validator.footprint(block)]
    cx = sum(x for x, _ in studs) / len(studs)
    cy = sum(y for _, y in studs) / len(studs)

    def center(block):
        fp = validator.footprint(block)
        return sum(x for x, _ in fp) / len(fp), sum(y for _, y in fp) / len(fp)

    def sign(value):
        return (value > 0) - (value < 0)

    def distance(block):
        bx, by = center(block)
        return (bx - cx) ** 2 + (by - cy) ** 2

    for index in sorted(range(len(layer1)), key=lambda i: -distance(layer1[i])):
        target = layer1[index]
        bx, by = center(target)
        directions = []
        for direction in ((sign(bx - cx), 0), (0, sign(by - cy)), (1, 0), (-1, 0), (0, 1), (0, -1)):
            if direction != (0, 0) and direction not in directions:
                directions.append(direction)
        others = set()
        for i, block in enumerate(layer1):
            if i != index:
                others |= validator.footprint(block)
        for dx, dy in directions:
            moved = dict(target, x=target["x"] + dx, y=target["y"] + dy)
            fp = validator.footprint(moved)
            if any(x not in validator.BOARD_RANGE or y not in validator.BOARD_RANGE for x, y in fp) or fp & others:
                continue
            current = [dict(moved) if i == index else dict(block) for i, block in enumerate(layer1)]
            differences = [{"expected": dict(target), "actual": dict(moved)}]
            if validator.check_intervention_input(approved, current, differences) == []:
                return current, differences
    return None, None


class FakeDCaller:
    """D 역할의 fake caller. C API 호출 → response 수신 → PREVIEW_READY 가정 → 다음 호출 → lifecycle 기록만 한다."""

    def __init__(self, mode, feed, preference, out_dir, render_dir=None, viewer=None, app=None):
        self.mode = mode
        self.feed = feed
        self.preference = preference
        self.out_dir = out_dir
        self.render_dir = render_dir
        self.viewer = viewer  # --show-preview: C-side Test Preview 창(Viewer), 없으면 None
        self.app = app
        self.previews = []  # [{"state", "png", "shown_at"}] — 표시·저장한 후보 상태
        self.timeline = []  # 지금 호출의 [C][STAGE] 이벤트(호출이 끝나면 그 행에 붙이고 비운다)
        self.approved = None  # Approved Design: review가 APPROVE를 돌려줄 때만 채택
        self.candidate = None  # (Candidate Design, design_metadata): 다음 review에 그대로 넘긴다
        self.current = None
        self.differences = None
        self.rows = []
        self.failed = False

    # ---- 답 배분 -------------------------------------------------------------------------------------------------
    def _slot(self, api):
        """(진행 여부, text 모드 답 또는 None=음성 모드)."""
        if self.mode == "mic":
            return True, None
        if self.feed.remaining() == 0:
            _log(f"[CALLER] answers exhausted before {api} → scenario stops here")
            return False, None
        if self.mode == "fake-voice":
            return True, None
        return True, self.feed.take()

    def progress(self, event):
        on_progress(event)
        self.timeline.append({"stage": event["stage"], "at": event["at"], "message": event["message"]})

    # ---- 기록 -----------------------------------------------------------------------------------------------------
    def _record(self, api, kind, envelope, previous, revised):
        design = envelope["design"]
        review = (envelope["design_metadata"] or {}).get("review") or {}
        error = envelope["error"] or {}
        _log(f"[CALLER] response status={envelope['status']} hri={envelope['hri_result']} "
             f"version={design['design_version'] if design else None} blocks={len(design['blocks']) if design else None} "
             f"error={error.get('code')}{(' ' + error.get('message', '')) if error else ''}")
        row = {
            "n": len(self.rows) + 1, "api": api, "kind": kind, "status": envelope["status"],
            "hri": envelope["hri_result"], "design_version": design["design_version"] if design else None,
            "round": review.get("round"),
            "changed": (design != previous) if design is not None and previous is not None else None,
            "validator": ("PASS" if validator.validate_design(design) == [] else "FAIL") if design else None,
            "current_preserved": None, "error": error.get("code"), "timeline": self.timeline,
        }
        self.timeline = []
        if revised and design is not None and self.current is not None:
            row["current_preserved"] = validator.validate_revised({"blocks": design["blocks"]}, self.current) == []
        self.rows.append(row)
        if envelope["status"] == "FAILED":
            self.failed = True
            details = error.get("details") or []
            if details:  # 마지막 생성 시도의 validator 탈락 사유(규칙별 개수와 첫 메시지, 좌표는 envelope JSON에)
                counts = {}
                for reason in details:
                    counts[reason.get("rule")] = counts.get(reason.get("rule"), 0) + 1
                _log("[CALLER] last rejection: " + ", ".join(f"{rule}×{count}" for rule, count in counts.items())
                     + f" · e.g. {str(details[0].get('message', ''))[:120]!r}")
        if self.out_dir:
            path = os.path.join(self.out_dir, f"{row['n']:02d}_{api}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, ensure_ascii=False, indent=2)
        if self.render_dir or self.viewer is not None:
            state = self._preview_state(api, kind, envelope, previous)
            if state is None:
                if design is not None:
                    _log("[CALLER] candidate unchanged (not re-saved)")
            else:
                self._present(row, state, envelope, review)

    @staticmethod
    def _preview_state(api, kind, envelope, previous):
        """새 Candidate를 받은 응답이면 lifecycle state 이름, 후보가 그대로면 None."""
        design = envelope["design"]
        if envelope["status"] != "OK" or design is None:
            return None
        if api == "create_initial_design":
            return "initial_candidate"
        if api == "run_intervention":
            return "revised_candidate" if envelope["hri_result"] == dialogue.REVISE else None
        if envelope["hri_result"] == dialogue.MODIFY and design != previous:
            round_ = ((envelope["design_metadata"] or {}).get("review") or {}).get("round")
            return f"{kind}_modified_candidate_r{round_}"
        return None

    def _present(self, row, state, envelope, review):
        """C-side Test Preview: PNG 합성 → (--show-preview) 창에 그린 뒤 → 로그. 실제 D Preview·HMI가 아니다."""
        import c_design_hmi_render as render
        design, metadata = envelope["design"], envelope["design_metadata"] or {}
        blocks = design["blocks"]
        title = f"C-side Test Preview — {state} — Not D Production HMI"
        detail = [f"{key} {metadata.get(key) or review.get(key)}" for key in ("selected_family", "style_hint", "scope", "concept")
                  if metadata.get(key) or review.get(key)]
        lines = [f"design_version {design['design_version']} · review.round {review.get('round', '-')} · {render.counts_line(blocks)}"
                 f" · validator {row['validator']}",
                 " · ".join(detail) if detail else "family/concept/style_hint 없음",
                 "fake PREVIEW_READY · C-side test visualization (Not D Production HMI)"]
        prefix = {"initial_candidate": "01", "revised_candidate": "03"}.get(state) or ("02" if state.startswith("initial") else "04")
        directory = self.render_dir or self._scratch_dir()
        path = os.path.join(directory, f"{prefix}_{state}.png")
        if state.startswith("revised"):
            diff = self.differences[0]
            captions = [[f"Approved v{self.approved['design_version']}"], ["Current + Difference(actual 주황)"],
                        [f"Candidate v{design['design_version']}"]]
            image = render.compose_v2(title, self.approved["blocks"], self.current, diff["expected"], diff["actual"], blocks,
                                      captions, lines, path)
        else:
            image = render.compose_v1(title, blocks, lines, path)
        entry = {"state": state, "png": path if self.render_dir else None, "shown_at": None}
        if self.viewer is not None:
            reopened = not self.viewer.label.isVisible() and bool(self.previews)
            self.viewer.show(self.app, image, title)  # processEvents로 실제 그려진 뒤 돌아온다
            entry["shown_at"] = review_smoke._now()
            if reopened:
                _log("[CALLER] C-side Test Preview window had been closed → shown again")
            _log(f"[CALLER] C-side Test Preview shown: {state} (fake PREVIEW_READY, Not D Production HMI)")
        if self.render_dir:
            _log(f"[CALLER] C-side Test Preview png → {path}")
        self.previews.append(entry)
        row["preview"] = entry

    def _scratch_dir(self):
        """--render 없이 --show-preview만 줄 때 합성 PNG를 둘 임시 폴더(보고·저장 대상 아님)."""
        if not getattr(self, "_tmp", None):
            import tempfile
            self._tmp = tempfile.mkdtemp(prefix="c_stage3_preview_")
        return self._tmp
    @staticmethod
    def _preview_ready(design):
        _log(f"[CALLER] PREVIEW_READY (assumed) candidate v{design['design_version']} blocks {len(design['blocks'])}")

    # ---- C public API 호출 ----------------------------------------------------------------------------------------
    def initial(self):
        go, text = self._slot("create_initial_design")
        if not go:
            return False
        preference = self.preference if self.mode == "text" else None
        _log(f"[CALLER] call create_initial_design kind=- input={'text' if text is not None else 'voice'}")
        envelope = main.create_initial_design(text=text, preference_text=preference, on_question=on_question,
                                              on_progress=self.progress)
        self._record("create_initial_design", None, envelope, None, revised=False)
        if envelope["status"] != "OK" or envelope["design"] is None:
            _log("[CALLER] no Initial candidate → scenario stops")
            return False
        self.candidate = (envelope["design"], envelope["design_metadata"])
        self._preview_ready(envelope["design"])
        return True

    def review(self, kind):
        """MODIFY인 동안 review를 다시 부른다(최대 MAX_REVIEWS). APPROVE면 approved 채택 후 True."""
        revised_inputs = {}
        if kind == "revised":
            revised_inputs = {"previous_design": self.approved, "current": self.current, "differences": self.differences}
        for _ in range(MAX_REVIEWS):
            go, answer = self._slot("review_design_candidate")
            if not go:
                return False
            design, metadata = self.candidate
            _log(f"[CALLER] call review_design_candidate kind={kind} candidate v{design['design_version']} "
                 f"round={((metadata or {}).get('review') or {}).get('round')}")
            envelope = main.review_design_candidate(
                design, kind=kind, design_metadata=metadata, text_answers=None if answer is None else [answer],
                on_question=on_question, on_progress=self.progress, **revised_inputs)
            self._record("review_design_candidate", kind, envelope, design, revised=kind == "revised")
            if envelope["status"] != "OK":
                _log(f"[CALLER] review ended with status {envelope['status']} → scenario stops")
                return False
            hri = envelope["hri_result"]
            if hri == dialogue.APPROVE:
                self.approved = deepcopy(envelope["design"])
                self.candidate = (envelope["design"], envelope["design_metadata"])
                _log(f"[CALLER] adopt approved v{self.approved['design_version']} blocks {len(self.approved['blocks'])}")
                return True
            if hri != dialogue.MODIFY:
                _log(f"[CALLER] review {hri} → caller stops (C 내부 재질문은 이미 끝남)")
                return False
            new = envelope["design"]
            if new == design:
                if os.environ.get("C_DESIGN_USE_LLM") == "1":
                    _log("[CALLER] WARNING: MODIFY returned the same candidate in LLM mode (designer는 같은 블록을 "
                         "unchanged_candidate로 탈락시켜야 한다)")
                else:
                    _log("[CALLER] MODIFY returned the same candidate (Mock: 재생성 없음, Stage 3 Wave 2 동작)")
            else:
                _log(f"[CALLER] MODIFY returned a NEW candidate v{new['design_version']} (not approved)")
            # 이전 response의 design_metadata를 그대로 다음 review에 넘긴다(review.round가 이어진다).
            self.candidate = (new, envelope["design_metadata"])
            self._preview_ready(new)
        _log(f"[CALLER] {MAX_REVIEWS} reviews without APPROVE → scenario stops")
        return False

    def intervention(self):
        self.current, self.differences = make_difference(self.approved)
        if self.current is None:
            _log("[CALLER] could not make a Difference from the Approved layer-1 blocks → scenario stops")
            return False
        diff = self.differences[0]
        _log(f"[CALLER] Difference (caller-made): {diff['expected']['brick_type']} "
             f"({diff['expected']['x']},{diff['expected']['y']}) → ({diff['actual']['x']},{diff['actual']['y']}) · "
             f"Current {len(self.current)} layer-1 blocks")
        go, answer = self._slot("run_intervention")
        if not go:
            return False
        _log(f"[CALLER] call run_intervention kind=- approved v{self.approved['design_version']}")
        envelope = main.run_intervention(self.approved, self.current, self.differences,
                                         text_answers=None if answer is None else [answer],
                                         on_question=on_question, on_progress=self.progress)
        self._record("run_intervention", None, envelope, self.approved, revised=envelope["hri_result"] == dialogue.REVISE)
        if envelope["status"] != "OK":
            _log(f"[CALLER] intervention ended with status {envelope['status']} → scenario stops")
            return False
        if envelope["hri_result"] != dialogue.REVISE or envelope["design"] is None:
            _log(f"[CALLER] intervention {envelope['hri_result']} → no Revised candidate (Approved 유지)")
            return False
        self.candidate = (envelope["design"], envelope["design_metadata"])
        self._preview_ready(envelope["design"])
        return True

    def assume_initial_approved(self):
        self.approved = deepcopy(self.candidate[0])
        _log(f"[CALLER] approved (assumed for intervention scenario) v{self.approved['design_version']}")


def run_scenario(caller, scenario):
    if not caller.initial() or scenario == "initial":
        return
    if scenario == "intervention":
        caller.assume_initial_approved()
    elif not caller.review("initial") or scenario == "review":
        return
    if caller.intervention():
        caller.review("revised")


def _cell(value):
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def print_summary(caller):
    columns = (("n", 3), ("api", 24), ("kind", 8), ("status", 10), ("hri", 8), ("design_version", 7), ("round", 6),
               ("changed", 8), ("validator", 9), ("current_preserved", 10), ("error", 0))
    headers = {"design_version": "version", "current_preserved": "Current"}
    _log("\n=== lifecycle summary (fake D caller, PREVIEW_READY assumed) ===")
    _log(" ".join(headers.get(name, name).ljust(width) for name, width in columns).rstrip())
    for row in caller.rows:
        _log(" ".join(_cell(row[name]).ljust(width) for name, width in columns).rstrip())
    approved = caller.approved
    candidate = caller.candidate[0] if caller.candidate else None
    _log(f"approved: {'v' + str(approved['design_version']) if approved else 'none'} · "
         f"candidate: {'v' + str(candidate['design_version']) if candidate else 'none'} · "
         f"candidate is approved: {candidate is not None and candidate == approved}")
    _log("version sequence: " + json.dumps([row["design_version"] for row in caller.rows]))
    _log("round sequence:   " + json.dumps([row["round"] for row in caller.rows]))
    _log("Current preserved: " + json.dumps([row["current_preserved"] for row in caller.rows]))


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("text", "fake-voice", "mic"), default="text")
    parser.add_argument("--scenario", choices=("initial", "review", "intervention", "full"), default="full")
    parser.add_argument("--answers", nargs="*", help="시나리오 전체 답(순서대로). 없으면 시나리오별 기본값")
    parser.add_argument("--preference", help="text 모드 LLM Initial 되묻기 답(preference_text, 기본 None)")
    parser.add_argument("--out", help="envelope JSON·summary.json 저장 디렉터리")
    parser.add_argument("--render", help="새 Candidate마다 C-side Test Preview PNG를 lifecycle state 이름으로 저장할 디렉터리"
                                         "(c_design_hmi_render compose_v1/compose_v2, 실제 D Preview 아님)")
    parser.add_argument("--show-preview", action="store_true",
                        help="새 Candidate를 C-side Test Preview 창에 그린 뒤 다음 review를 부른다(fake PREVIEW_READY, "
                             "Not D Production HMI)")
    args = parser.parse_args()

    use_llm = os.environ.get("C_DESIGN_USE_LLM") == "1"
    flag = os.environ.get("C_DESIGN_USE_LLM")
    _log(f"mode {args.mode} · scenario {args.scenario} · {'LLM' if use_llm else 'Mock(규칙만)'}")
    _log(f"C_DESIGN_USE_LLM: {'1' if use_llm else ('unset' if flag is None else 'set (not 1 → Mock)')}")
    missing = []
    for name in (llm.LLM_KEY_ENV, voice.STT_KEY_ENV, voice.TTS_KEY_ENV):
        configured = bool(os.environ.get(name))
        _log(f"{name}: {'configured' if configured else 'not set'}")
        if not configured:
            missing.append(name)
    if use_llm:
        generation_model = os.environ.get("OPENAI_MODEL") or llm.DEFAULT_MODEL
        _log(f"models: generation {generation_model} · judge {os.environ.get(llm.JUDGE_MODEL_ENV) or llm.DEFAULT_JUDGE_MODEL}"
             f" · aux {os.environ.get(llm.AUX_MODEL_ENV) or llm.DEFAULT_AUX_MODEL}")
        if not os.environ.get("OPENAI_MODEL"):
            # 2026-10-11 actual mic E2E: OPENAI_MODEL 없이 실행 → 기본 gpt-4o-mini가 10회 모두 support/overlap/connectivity 탈락
            _log(f"WARNING: OPENAI_MODEL이 없어 기본 {llm.DEFAULT_MODEL}로 생성한다. 실측상 유효 후보를 만들지 못하므로 "
                 "OPENAI_MODEL=gpt-6.1-sol을 함께 주는 것을 권장한다. 계속 진행한다.")
    if use_llm and llm.LLM_KEY_ENV in missing:
        _log(f"WARNING: LLM 모드인데 {llm.LLM_KEY_ENV}가 없다(LLM 호출이 실패로 끝난다). 계속 진행한다.")
    if args.mode != "text" and use_llm and (voice.TTS_KEY_ENV in missing or (args.mode == "mic" and voice.STT_KEY_ENV in missing)):
        _log("WARNING: 음성 모드인데 TTS/STT 키가 없다(TTS는 소리 없이 넘어가고 STT는 실패한다). 계속 진행한다.")
    if args.mode == "fake-voice" and not use_llm:
        _log("note: Mock 음성 모드에서는 run_intervention 질문만 voice.speak로 읽는다(TTS 키가 없으면 소리 없이 넘어간다).")

    feed = None
    if args.mode != "mic":
        answers = args.answers if args.answers is not None else DEFAULT_ANSWERS[args.scenario]
        feed = AnswerFeed(answers)
        _log("answers: " + json.dumps(answers, ensure_ascii=False))
    if args.mode == "fake-voice":
        install_fake_voice(feed)
    elif args.mode == "mic":
        install_mic_log()
        voice.prewarm()
    for directory in (args.out, args.render):
        if directory:
            os.makedirs(directory, exist_ok=True)
    app = viewer = None
    if args.show_preview or args.render:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    if args.show_preview:
        from c_voice_e2e_c_only import Viewer  # Stage 2 C 단독 runner의 비차단 창 재사용
        viewer = Viewer()
    _log(f"preview: {'C-side Test Preview (window, Not D Production HMI)' if viewer else 'none'} / "
         f"png: {args.render or 'none'}")

    caller = FakeDCaller(args.mode, feed, args.preference, args.out, args.render, viewer=viewer, app=app)
    try:
        run_scenario(caller, args.scenario)
    finally:
        if viewer is not None:
            viewer.close()
    print_summary(caller)
    exit_code = 1 if caller.failed else 0
    if args.out:
        summary = {"mode": args.mode, "scenario": args.scenario, "use_llm": use_llm, "rows": caller.rows,
                   "approved_version": caller.approved["design_version"] if caller.approved else None,
                   "answers_used": feed.used if feed else None, "exit_code": exit_code,
                   "version_sequence": [row["design_version"] for row in caller.rows],
                   "round_sequence": [row["round"] for row in caller.rows],
                   "current_preserved_sequence": [row["current_preserved"] for row in caller.rows],
                   "previews": caller.previews}
        with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        _log(f"saved envelopes and summary.json to {args.out}")
    _log(f"exit {exit_code} ({'FAILED envelope present' if caller.failed else 'no FAILED envelope'})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main_cli())
