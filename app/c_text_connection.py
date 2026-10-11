"""C 텍스트 함수와 명시적 음성 시험 연결. Qt 상태 변경은 호출 thread 밖에서 처리한다."""

from copy import deepcopy
import json
from threading import Event, Thread

from PyQt5.QtCore import QObject, Qt, pyqtSignal

from app.c_design import main as c_main, voice
from app.contracts import _text, validate_block
from app.c_candidate import open_candidate, on_review, valid_review
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

    def voice_call(self, kind, payload, cancelled):
        """C가 TTS→beep→STT 수명주기를 단독 소유한다."""
        if kind == "initial":
            return c_main.create_initial_design(text=None, should_stop=cancelled.is_set,
                on_question=lambda text: self.question_received.emit(payload["request_id"], text),
                on_progress=lambda event: self.progress(payload["request_id"], event, cancelled))
        return c_main.run_intervention(deepcopy(payload["design"]), current_blocks_for_c(payload),
            differences_for_c(payload["difference"]), text_answers=None,
            on_question=lambda text: self.question_received.emit(payload["request_id"], text),
            should_stop=cancelled.is_set,
            on_progress=lambda event: self.progress(payload["request_id"], event, cancelled))

    def progress(self, identity, event, cancelled):
        if cancelled.is_set():
            raise InterruptedError("C_STOPPED")
        if not self.voice_mode:
            return
        if voice.last_error():
            # C가 다음 STT를 열기 전 on_progress 경계에서 실패를 보류한다. D는 음성 I/O를 수행하지 않는다.
            raise ValueError("C_VOICE_IO_FAILED")
        stage, message = event["stage"], event.get("message")
        self.audio(identity, stage, "FAILED" if stage == "FAILED" else "RESULT",
                   message or stage, reason=message if stage == "FAILED" else None)

    def preview_ready(self, identity):
        review = self.backend.state.get("c_review")
        if not review or review["request_id"] != identity or review["phase"] != "PREVIEW":
            return
        if (review["job_id"] != self.backend.state["job_id"] or
                review["base_current_revision"] != self.backend.state["current"]["current_revision"]):
            self.backend._hold("C_REVIEW_CONTEXT_CHANGED")
            self.publish()
            return
        self.backend._state["c_review"]["phase"] = "REVIEW"
        self.start("review", self.backend.state["c_review"])

    def valid(self, kind, payload):
        if kind == "review":
            return valid_review(self.backend, payload)
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
        voice_call = self.voice_mode and kind != "review" and (kind == "initial" or preview)
        if voice_call:
            preview = False

        def call():
            try:
                if kind == "review":
                    context = dict(previous_design=deepcopy(payload["previous_design"]),
                        current=current_blocks_for_c(payload), differences=differences_for_c(payload["difference"])) if payload["kind"] == "revised" else {}
                    response = c_main.review_design_candidate(deepcopy(payload["design"]), kind=payload["kind"],
                        design_metadata=deepcopy(payload["design_metadata"]), **context,
                        text_answers=None if self.voice_mode else list(answers),
                        on_question=lambda text: self.question_received.emit(payload["request_id"], text),
                        should_stop=cancelled.is_set,
                        on_progress=lambda event: self.progress(payload["request_id"], event, cancelled))
                elif voice_call:
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
                audio_error = voice.last_error() if self.voice_mode else None
                code = "STOPPED" if cancelled.is_set() else "VOICE_IO_FAILED" if audio_error else "C_CONNECTION_EXCEPTION"
                message = audio_error or type(error).__name__
                if audio_error:
                    self.audio(payload["request_id"], "VOICE_IO", "FAILED", message, reason=message)
                response = dict(status="CANCELLED" if cancelled.is_set() else "FAILED", error=dict(code=code, message=message),
                                design=None, hri_result=None, questions=[])
            self.result_received.emit((kind, payload, response, preview))

        Thread(target=call, daemon=True).start()

    def question(self, identity, text):
        review = self.backend.state.get("c_review")
        if review and review["request_id"] == identity and valid_review(self.backend, review):
            self.backend._state["c_review"]["question"] = text
            self.backend._state["question"] = text
            self.publish()
            return
        request = self.backend.state["planning_request"]
        if request and request["request_id"] == identity and self.valid("initial", request):
            self.backend._state["question"] = text
            self.publish()
            return
        if self.backend.on_question(identity, text):
            self.publish()

    def finish(self, value):
        kind, payload, response, preview = value
        if (not self.active or self.active[0] != kind or
                self.active[1]["request_id"] != payload["request_id"]):
            self.backend._ignored(payload["request_id"])
            return
        self.active = None
        identity = payload["request_id"]
        if not self.valid(kind, payload):
            self.backend._ignored(identity)
            self.publish()
            return
        if not isinstance(response, dict):
            self.backend._hold("C_RESPONSE_INVALID: expected object")
            self.publish()
            return
        self.backend._event("C_CALL_RESULT", request_id=identity,
                            result=dict(kind=kind, question_preview=preview, response=response))
        if kind == "review":
            on_review(self.backend, payload, response)
            if self.voice_mode and (self.backend.state.get("c_review") or {}).get("phase") == "WAIT_ANSWER":
                self.backend._hold("C_REVIEW_UNCLEAR: 음성 검토에서 승인을 확인하지 못했습니다.")
        elif kind == "initial":
            open_candidate(self.backend, "initial", payload, response)
        elif response.get("status") == "OK" and response.get("hri_result") == "REVISE":
            open_candidate(self.backend, "revised", payload, response)
        elif response.get("status") == "CANCELLED":
            self.backend._hold("C_INTERVENTION_CANCELLED: " + str(response.get("error")))
        elif preview and response.get("status") == "OK":
            # 응답 없이 질문을 표시한 호출은 사용자 의도 결과가 아니다.
            self.backend._event("C_QUESTION_PREVIEW", request_id=identity, result=response)
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
        review = self.backend.state.get("c_review")
        if review:
            if self.active or review["request_id"] != identity or review["phase"] != "WAIT_ANSWER":
                raise ValueError("표시된 활성 후보의 검토 요청 ID를 확인하세요.")
            self.start("review", review, answers=[text])
            return
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
        review = state.get("c_review")
        if review and not self.active and review["phase"] == "WAIT_ANSWER":
            if not self.voice_mode:
                print("C 후보 검토 입력: " + json.dumps(dict(event="answer", request_id=review["request_id"],
                    text="좋아요"), ensure_ascii=False), flush=True)
            return
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
