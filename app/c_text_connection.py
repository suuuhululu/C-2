"""C 텍스트 함수와 명시적 음성 시험 연결. Qt 상태 변경은 호출 thread 밖에서 처리한다."""

from copy import deepcopy
import json
from threading import Event, Thread

from PyQt5.QtCore import QObject, Qt, pyqtSignal

from app.c_design import main as c_main, voice
from app.contracts import _text, validate_block
from app.planning_connection import current_blocks_for_c, on_c_intervention


def differences_for_c(value):
    """같은 좌표·층의 유일한 쌍만 비교용으로 묶는다. 이동/물리 ID를 추정하지 않는다."""
    if not isinstance(value, dict) or value.get("unobservable"):
        raise ValueError("C intervention requires a readable D Difference")
    missing = [validate_block(b) for b in value["missing"]]
    unexpected = [validate_block(b) for b in value["unexpected"]]
    origin = lambda b: (b["x"], b["y"], b["layer"])
    pairs, used = [], set()
    for expected in missing:
        matches = [i for i, actual in enumerate(unexpected) if origin(actual) == origin(expected)]
        unique = sum(origin(b) == origin(expected) for b in missing) == 1
        index = matches[0] if unique and len(matches) == 1 else None
        pairs.append(dict(expected=expected, actual=unexpected[index] if index is not None else None))
        if index is not None:
            used.add(index)
    pairs.extend(dict(expected=None, actual=b) for i, b in enumerate(unexpected) if i not in used)
    if not pairs:
        raise ValueError("C intervention requires a nonempty Difference")
    return deepcopy(pairs)


class CTextConnection(QObject):
    question_received = pyqtSignal(str, str)
    result_received = pyqtSignal(object)
    voice_received = pyqtSignal(str, object)

    def __init__(self, backend, publish, *, initial_text, voice_mode=False):
        super().__init__()
        self.backend, self.publish = backend, publish
        _text(initial_text, "c.initial_text")
        self.initial_text = initial_text
        if type(voice_mode) is not bool:
            raise ValueError("c.voice_mode: expected boolean")
        self.voice_mode = voice_mode
        self.voice_status = "시작 후 마이크로 목표를 말해주세요." if voice_mode else None
        self.active = None
        self.question_received.connect(self.question, Qt.QueuedConnection)
        self.result_received.connect(self.finish, Qt.QueuedConnection)
        self.voice_received.connect(self.voice_event, Qt.QueuedConnection)

    def voice_event(self, identity, value):
        if not self.active or identity != self.active[1]["request_id"] or not self.valid(*self.active[:2]):
            self.backend._ignored(identity)
            return
        self.voice_status = value["notice"]
        self.backend._event("C_VOICE_" + value["status"], request_id=identity, result=value)
        print(value["notice"], flush=True)
        self.publish()

    def audio(self, identity, phase, status, notice, *, text=None, reason=None):
        self.voice_received.emit(identity, dict(phase=phase, status=status, notice=notice,
                                               text=text, reason=reason))

    def listen(self, identity, phase, cancelled):
        if cancelled.is_set():
            return None
        self.audio(identity, phase, "STARTED", f"마이크 녹음 시작 · {voice.WAIT_SECONDS:g}초 안에 말해주세요.")
        text = voice.listen()
        reason = (voice.last_error() or "VOICE_IO_FAILED") if text is None else "SILENCE" if not text.strip() else None
        self.audio(identity, phase, "FAILED" if reason else "RESULT",
                   "음성 입력 실패: " + reason if reason else "인식한 문장: " + text,
                   text=text, reason=reason)
        return text

    def voice_call(self, kind, payload, cancelled):
        """C 음성 I/O만 재사용한다. 무한 음성 재질문 대신 D의 의도 정책을 유지한다."""
        identity = payload["request_id"]
        questions = []

        def fail(reason):
            return dict(status="FAILED", hri_result=None, design=None, questions=questions,
                        error=dict(code="VOICE_IO_FAILED", message=reason, details=[]))

        def intervene(answers):
            return c_main.run_intervention(deepcopy(payload["design"]), current_blocks_for_c(payload),
                differences_for_c(payload["difference"]), text_answers=answers,
                on_question=lambda text: self.question_received.emit(identity, text),
                should_stop=cancelled.is_set)

        if kind != "initial":
            if payload.get("question"):
                questions = [payload["question"]]
                self.question_received.emit(identity, questions[-1])
            else:
                preview = intervene([])
                questions = preview.get("questions", [])
                if preview.get("status") != "OK" or cancelled.is_set():
                    return preview
            if cancelled.is_set():
                return fail("STOPPED")
            if not questions:
                return fail("C 질문이 없어 음성 응답을 요청하지 않습니다.")
            self.audio(identity, "TTS_QUESTION", "STARTED", "질문 음성 재생 중 · AI 생성 음성")
            voice.speak(questions[-1])
            error = voice.last_error()
            self.audio(identity, "TTS_QUESTION", "FAILED" if error else "RESULT",
                       "질문 음성 실패: " + error if error else "질문 음성 재생 완료", reason=error)
            if error:
                return fail(error)
        text = self.listen(identity, "STT_GOAL" if kind == "initial" else "STT_ANSWER", cancelled)
        if cancelled.is_set():
            return dict(status="CANCELLED", hri_result=None, design=None, questions=questions,
                        error=dict(code="STOPPED", message="stopped by D/HMI", details=[]))
        if text is None or not text.strip():
            return fail(voice.last_error() or "SILENCE: 음성 입력이 없어 진행을 보류합니다.")
        if kind == "initial":
            return c_main.create_initial_design(text=text, should_stop=cancelled.is_set)
        return intervene([text])

    def valid(self, kind, payload):
        state = self.backend.state
        key = "planning_request" if kind == "initial" else "question_request"
        request = state[key]
        workflow = "PREPARING" if kind == "initial" else "WAIT_INTENT"
        revision = payload["base_current_revision"] if kind == "initial" else payload["current_revision"]
        return bool(request and request["request_id"] == payload["request_id"]
                    and state["workflow_status"] == workflow and not state["stop_request"]
                    and state["job_id"] == payload["job_id"]
                    and state["current"]["current_revision"] == revision
                    and request["design_version"] == payload["design_version"])

    def sync(self):
        if self.active and not self.valid(self.active[0], self.active[1]):
            self.active[2].set()

    def start(self, kind, payload, *, answers=(), preview=False):
        if self.active:
            self.sync()
            self.backend.on_failure("planner" if kind == "initial" else "hri", payload["request_id"],
                                    "C_CALL_BUSY: previous call has not ended")
            return
        payload, cancelled = deepcopy(payload), Event()
        if not self.valid(kind, payload):
            self.backend._ignored(payload["request_id"])
            return
        self.active = (kind, payload, cancelled)
        self.backend._event("C_CALL_STARTED", request_id=payload["request_id"],
                            result=dict(kind=kind, question_preview=preview, voice_mode=self.voice_mode))
        voice_call = self.voice_mode and (kind == "initial" or preview)
        if voice_call:
            preview = False

        def call():
            try:
                if voice_call:
                    response = self.voice_call(kind, payload, cancelled)
                elif kind == "initial":
                    response = c_main.create_initial_design(text=self.initial_text, should_stop=cancelled.is_set)
                else:
                    response = c_main.run_intervention(
                        deepcopy(payload["design"]), current_blocks_for_c(payload),
                        differences_for_c(payload["difference"]), text_answers=list(answers),
                        on_question=lambda text: self.question_received.emit(payload["request_id"], text),
                        should_stop=cancelled.is_set)
            except Exception as error:
                # 예상 밖 callback/provider 예외도 성공·UNCLEAR로 숨기지 않는다. secret 본문은 기록하지 않는다.
                response = dict(status="FAILED", error=dict(code="C_CONNECTION_EXCEPTION",
                                message=type(error).__name__), design=None, hri_result=None, questions=[])
            self.result_received.emit((kind, payload, response, preview))

        Thread(target=call, daemon=True).start()

    def question(self, identity, text):
        if self.backend.on_question(identity, text):
            self.publish()

    def finish(self, value):
        kind, payload, response, preview = value
        self.active = None
        identity = payload["request_id"]
        if not self.valid(kind, payload):
            self.backend._ignored(identity)
            self.publish()
            return
        self.backend._event("C_CALL_RESULT", request_id=identity,
                            result=dict(kind=kind, question_preview=preview, response=response))
        if preview and response.get("status") == "OK":
            # 응답 없이 질문을 표시한 호출은 사용자 의도 결과가 아니다.
            self.backend._event("C_QUESTION_PREVIEW", request_id=identity, result=response)
        elif kind == "initial":
            self.backend.on_initial_design(identity, response)
        else:
            on_c_intervention(self.backend, identity, response)
            state = self.backend.state
            request = state["question_request"]
            if (self.voice_mode and response.get("hri_result") == "UNCLEAR" and request
                    and request["request_id"] != identity and not state["choice_required"]
                    and state["workflow_status"] == "WAIT_INTENT"):
                # D가 연 새 설명 질문만 한 번 발화한다. 계속 불명확하면 기존 선택 버튼을 기다린다.
                self.start("intervention", dict(**request, question=state["question"],
                    design=state["context"]["design"], current=state["current"],
                    difference=state["difference"]), preview=True)
        self.publish()

    def answer(self, value):
        if self.voice_mode:
            raise ValueError("음성 시험은 질문 재생 후 마이크 응답을 받습니다. 텍스트 답변은 혼합하지 않습니다.")
        identity, text = value["request_id"], value["text"]
        _text(text, "c.answer.text")
        if not text.strip():
            raise ValueError("빈 답변은 의도 선택으로 처리하지 않습니다.")
        state, request = self.backend.state, self.backend.state["question_request"]
        if self.active or request is None or request["request_id"] != identity or state["choice_required"]:
            raise ValueError("활성 질문 ID를 확인하세요. C 호출 중이거나 명시 선택 대기 중입니다.")
        payload = dict(**request, design=state["context"]["design"], current=state["current"],
                       difference=state["difference"])
        if not self.valid("intervention", payload):
            raise ValueError("닫힌 질문에는 답변을 채택하지 않습니다.")
        self.start("intervention", payload, answers=[text])

    def show_next_input(self):
        state = self.backend.state
        request = state["question_request"]
        if not self.active and request and state["workflow_status"] == "WAIT_INTENT":
            if state["choice_required"]:
                print("계속 불명확합니다. HMI의 KEEP/REVISE 명시 선택을 기다립니다.", flush=True)
            else:
                if self.voice_mode:
                    print("음성 의도 확인 종료. HMI 사유/선택을 확인하세요.", flush=True)
                    return
                print("C 질문에 답할 입력: " + json.dumps(dict(event="answer", request_id=request["request_id"],
                                                          text="2번"), ensure_ascii=False), flush=True)

    def close(self):
        if self.active:
            self.active[2].set()
