"""C Design 공개 진입점.

목적:
    다른 파트(D Backend·통합)가 C를 호출하는 유일한 입구.
    Initial Design 흐름과 Intervention 대화 흐름을 orchestration한다.
    검증·문장·설계 로직은 validator / dialogue / designer에 위임한다.

구현 범위 (WAVE 4, docs/C_DESIGN_CONTRACT.md §4·§6·§8·§10):
    - create_initial_design: 목표 문장(텍스트, 또는 voice.listen) → dialogue.parse_goal
      → designer.build_initial_design → 결과 envelope
    - run_intervention: 입력 검사 → dialogue.build_question → 응답 턴 반복
      (KEEP / REVISE / UNCLEAR 재설명 / 명시적 취소 / STOP)
      → REVISE면 designer.build_revised_design(6회) → 탈락 시 §8.11 escalation 질문
      → "계속 찾기"면 4회 더(합계 10회) → 실패면 DESIGN_GENERATION_FAILED
    - Current가 support 후보 기준을 위반하면 재생성 없이 바로 escalation 질문
    - 텍스트 모드(text / text_answers)는 Fake Voice로 쓰인다.
    - 음성 모드: voice provider가 아직 없어(WAVE 6) VOICE_IO_FAILED를 반환한다.
    - Day4: 시간 기준 자동 취소 없음. 침묵(빈 발화)은 재질문 없이 계속 기다린다.

하지 않는 것:
    - 음성 I/O·질문 문장·응답 규칙·LLM 호출·검증 로직 자체 구현(각 모듈에 위임)
    - Current 채택·Difference 판정·사람 조립 순서·NextPart·Robot 제어·화면 표시
    - import 시 녹음·재생·모델 로딩·네트워크 요청

연결:
    dialogue.py, voice.py, designer.py, validator.py(입력 검사·support 판정)를 호출한다.
    외부 모듈은 이 파일의 공개 함수만 호출한다.
"""

from app.c_design import designer, dialogue, validator, voice

# §8.10·§8.11: 연속 6회 탈락하면 escalation 질문, "계속 찾기"면 남은 4회(합계 10회).
FIRST_ATTEMPTS = 6
EXTRA_ATTEMPTS = designer.MAX_ATTEMPTS - FIRST_ATTEMPTS

VOICE_NOT_CONNECTED = "voice provider not connected, WAVE 6"

# next_reply가 침묵 대기 중 STOP을 만났다는 표시(정상 응답 문자열·None과 구분).
_STOP = object()


def _result(status, hri_result=None, design=None, questions=(), code=None, message="", details=()):
    error = None if status == "OK" else {"code": code, "message": message, "details": list(details)}
    return {"status": status, "hri_result": hri_result, "design": design, "questions": list(questions), "error": error}


def _stopped(questions):
    return _result("CANCELLED", questions=questions, code="STOPPED", message="stopped by D/HMI")


def _user_cancel(questions):
    return _result("CANCELLED", questions=questions, code="USER_CANCEL", message="cancelled by user")


def _from_designer(result, hri_result, questions):
    """designer 결과 → envelope. 탈락 한도는 FAILED, should_stop 중단은 CANCELLED(§10)."""
    if result["design"] is not None:
        return _result("OK", hri_result, result["design"], questions)
    if any(reason["rule"] == "stopped" for reason in result["reasons"]):
        return _stopped(questions)
    return _result(
        "FAILED", hri_result, None, questions, "DESIGN_GENERATION_FAILED",
        "no valid design within the attempt limit", result["reasons"],
    )


def create_initial_design(text=None, should_stop=None):
    """목표 문장 → Initial Design (§4.1)."""
    if text is None:
        text = voice.listen()
        if text is None:
            return _result("FAILED", code="VOICE_IO_FAILED", message=VOICE_NOT_CONNECTED)
    elif not isinstance(text, str):
        return _result("FAILED", code="INVALID_INPUT", message="text must be a str or None")

    object_type = dialogue.parse_goal(text)
    if object_type is None:
        return _result("FAILED", code="UNSUPPORTED_OBJECT", message="no supported object in the goal")

    result = designer.build_initial_design(object_type, delay=designer.RETRY_DELAY, should_stop=should_stop)
    return _from_designer(result, None, [])


def run_intervention(design, current, differences, text_answers=None, on_question=None, should_stop=None):
    """실제 차이에 대한 사용자 의도 확인 (§4.2). 예외를 밖으로 던지지 않는다(on_question 제외)."""
    reasons = validator.check_intervention_input(design, current, differences)
    if reasons:
        return _result("FAILED", code="INVALID_INPUT", message="invalid intervention input", details=reasons)

    questions = []
    voice_mode = text_answers is None
    answers = None if voice_mode else iter(text_answers)

    def ask(sentence):
        questions.append(sentence)
        if on_question is not None:
            on_question(sentence)
        if voice_mode:
            voice.speak(sentence)

    def next_reply():
        """다음 의미 있는 응답. None이면 텍스트 응답 소진 또는 음성 미연결, _STOP이면 STOP."""
        while True:
            reply = voice.listen() if voice_mode else next(answers, None)
            if reply is None or dialogue.is_meaningful(reply):
                return reply
            # 침묵·빈 발화: Day4는 시간 기준 재질문·취소 없이 계속 기다리되 STOP은 확인한다(§4.3).
            if stop_requested():
                return _STOP

    def no_reply():
        if voice_mode:
            return _result("FAILED", questions=questions, code="VOICE_IO_FAILED", message=VOICE_NOT_CONNECTED)
        return _result("OK", dialogue.UNCLEAR, None, questions)

    def stop_requested():
        return should_stop is not None and should_stop()

    def escalate(can_redesign):
        """§8.11 escalation 질문. 종료 envelope 또는 None(계속 재설계)을 돌려준다."""
        question = dialogue.escalation_question(differences)
        ask(question)
        while True:
            if stop_requested():
                return _stopped(questions)
            reply = next_reply()
            if reply is _STOP:
                return _stopped(questions)
            if reply is None:
                return no_reply()
            choice = dialogue.parse_escalation_response(reply)
            if choice == dialogue.MOVE_BACK:
                return _result("OK", dialogue.KEEP, design, questions)
            if choice == dialogue.CANCEL:
                return _user_cancel(questions)
            if choice == dialogue.KEEP_SEARCHING and can_redesign:
                return None
            # UNCLEAR, 또는 재설계할 수 없는데 "계속 찾기": 같은 질문으로 명시 선택을 기다린다.
            ask(question)

    def revise():
        if validator.current_support_violations(current):
            # Current를 그대로 보존하면 어떤 후보도 support를 통과할 수 없다(§8.11 즉시 진입).
            return escalate(can_redesign=False)
        result = designer.build_revised_design(
            design, current, differences, max_attempts=FIRST_ATTEMPTS,
            delay=designer.RETRY_DELAY, should_stop=should_stop,
        )
        if result["design"] is not None or any(r["rule"] == "stopped" for r in result["reasons"]):
            return _from_designer(result, dialogue.REVISE, questions)
        ended = escalate(can_redesign=True)
        if ended is not None:
            return ended
        if stop_requested():
            return _stopped(questions)
        result = designer.build_revised_design(
            design, current, differences, max_attempts=EXTRA_ATTEMPTS,
            delay=designer.RETRY_DELAY, should_stop=should_stop,
        )
        return _from_designer(result, dialogue.REVISE, questions)

    question = dialogue.build_question(design, current, differences)
    ask(question)
    while True:
        if stop_requested():
            return _stopped(questions)
        reply = next_reply()
        if reply is _STOP:
            return _stopped(questions)
        if reply is None:
            return no_reply()
        choice = dialogue.parse_response(reply)
        if choice == dialogue.KEEP:
            return _result("OK", dialogue.KEEP, design, questions)
        if choice == dialogue.CANCEL:
            return _user_cancel(questions)
        if choice == dialogue.REVISE:
            return revise()
        ask(dialogue.build_reask(question))
