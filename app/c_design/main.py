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
    - 음성 모드: voice.speak(질문) 재생이 끝난 뒤 voice.listen()으로 응답을 받는다(WAVE 6).
      listen()이 None(장치·STT 실패)이면 VOICE_IO_FAILED, ""(침묵)이면 계속 기다린다.
    - Day4: 시간 기준 자동 취소 없음. 침묵(빈 발화)은 재질문 없이 계속 기다린다.
    - 설계 생성기: 호출 시점에 환경 변수 C_DESIGN_USE_LLM=1이면 llm(WAVE 5), 아니면 Mock.
      provider 실패는 LLM_CALL_FAILED로 반환한다.
    - design_metadata(2026-10-07): envelope의 design 옆 sibling 키. design 구조({design_version, blocks})는 그대로이며
      design이 None이면 None. Revised(LLM): 설계 의도(intent) → 생성(intent 주입) → judge → judge가 family를 알아볼 수
      없다(recognizable_family False)거나 실루엣이 모호(silhouette_clarity "ambiguous")할 때만 같은 intent + judge 피드백으로
      재생성 최대 METADATA_REGENERATIONS_MAX(1)회 → 재judge. judge 응답 오류·필드 누락은 재생성 없이 끝내고 error에 남긴다.
      metadata 생성 실패는 설계 성공을 FAILED로 바꾸지 않는다. KEEP·실패·취소는 None. Mock은 고정 문자열.

하지 않는 것:
    - 음성 I/O·질문 문장·응답 규칙·LLM 호출·검증 로직 자체 구현(각 모듈에 위임)
    - Current 채택·Difference 판정·사람 조립 순서·NextPart·Robot 제어·화면 표시
    - import 시 녹음·재생·모델 로딩·네트워크 요청

연결:
    dialogue.py, voice.py, designer.py, llm.py(생성기 주입), validator.py(입력 검사·support 판정)를 호출한다.
    외부 모듈은 이 파일의 공개 함수만 호출한다.
"""

import os

from app.c_design import designer, dialogue, llm, validator, voice

# §8.10·§8.11: 연속 6회 탈락하면 escalation 질문, "계속 찾기"면 남은 4회(합계 10회).
FIRST_ATTEMPTS = 6
EXTRA_ATTEMPTS = designer.MAX_ATTEMPTS - FIRST_ATTEMPTS
# judge 결과에 따른 설계 재생성 상한(요청 하나당). provider 재시도(llm.RETRY_BACKOFF)·후보 재생성(designer 시도 수)과 별개다.
METADATA_REGENERATIONS_MAX = 1
# judge 응답에서 재생성·verdict 판단에 꼭 필요한 필드와 허용 값. 하나라도 어긋나면 judge_error(재생성 없음).
_JUDGE_REQUIRED = {
    "recognizable_family": (True, False),
    "silhouette_clarity": ("clear", "ambiguous"),
    "reads_as_seating": (True, False),
    "explanation_required_to_understand": (True, False),
}
_HUMAN_STORY_KEYS = ("placed_differently", "interpretation", "imagined_concept", "lego_redesign", "why_final_shape")
_MOCK_NAME, _MOCK_FAMILY, _MOCK_SUMMARY = "Mock 의자", "chair", "Mock 고정 설계(LLM 미사용)"


# next_reply가 침묵 대기 중 STOP을 만났다는 표시(정상 응답 문자열·None과 구분).
_STOP = object()


def _voice_failure():
    # voice.last_error()는 실패 종류만 담고 key·응답 본문은 담지 않는다.
    return f"voice I/O failed: {voice.last_error() or 'unknown'}"


def _result(status, hri_result=None, design=None, questions=(), code=None, message="", details=(), design_metadata=None):
    error = None if status == "OK" else {"code": code, "message": message, "details": list(details)}
    return {"status": status, "hri_result": hri_result, "design": design,
            "design_metadata": design_metadata if design is not None else None,
            "questions": list(questions), "error": error}


def _llm_error_kind(result):
    return result["llm_error"]["kind"] if isinstance(result, dict) and "llm_error" in result else None


def _meta_error(kind, detail):
    return {"kind": kind, "message": str(detail)}


def _initial_metadata(described):
    """Initial(LLM) design_metadata. described는 llm.describe_initial_design 결과(dict 또는 llm_error)."""
    error = None
    if _llm_error_kind(described):
        error, described = _meta_error("describe_error", described["llm_error"]), {}
    return {
        "design_name": described.get("design_name"), "design_family": described.get("design_family"),
        "design_summary": described.get("design_summary"), "visible_features": list(described.get("visible_features") or []),
        "human_interpretation": None,
        "judge": None if error else {key: described.get(key) for key in ("silhouette_clarity", "recognizable_family", "completeness_score")},
        "source": "LLM", "error": error,
    }


def _mock_metadata(revised):
    metadata = {"design_name": _MOCK_NAME, "design_family": _MOCK_FAMILY, "design_summary": _MOCK_SUMMARY,
                "visible_features": [], "human_interpretation": None, "judge": None, "source": "MOCK", "error": None}
    if revised:
        metadata.update(change_summary=[], interpretation_status=None, design_intent=None, regenerations=0)
    return metadata


def _judge_problem(judge):
    """judge 응답이 재생성·verdict 판단에 쓸 수 있으면 None, 아니면 오류 설명."""
    if _llm_error_kind(judge):
        return judge["llm_error"]
    bad = [key for key, allowed in _JUDGE_REQUIRED.items() if key not in judge or judge[key] not in allowed
           or (allowed == (True, False) and not isinstance(judge[key], bool))]
    return f"missing or invalid judge fields: {bad}" if bad else None


def _needs_regeneration(judge):
    # 사용자 기준: family를 알아볼 수 없거나 실루엣이 모호할 때만. awkward·weakly visible·feature mismatch만으로는 하지 않는다.
    return judge["recognizable_family"] is False or judge["silhouette_clarity"] == "ambiguous"


def _verdict(judge):
    showcase = (judge["reads_as_seating"] and judge["recognizable_family"] and judge["silhouette_clarity"] == "clear"
                and judge["explanation_required_to_understand"] is False)
    return "SHOWCASE" if showcase else "NOT_YET"


def _revised_metadata(intent, judge, regenerations, error):
    """Revised(LLM) design_metadata. judge는 판단 가능한 응답 또는 None, intent는 dict 또는 None."""
    seen, planned = judge or {}, intent or {}
    story = seen.get("human_story")
    return {
        "design_name": seen.get("design_name") or planned.get("concept_name"),
        "design_family": seen.get("design_family") or planned.get("design_family"),
        "design_summary": seen.get("why_it_is_complete"),
        "visible_features": list(seen.get("visible_features") or []),
        "human_interpretation": {key: story.get(key) for key in _HUMAN_STORY_KEYS} if isinstance(story, dict) else None,
        "change_summary": list(seen.get("change_summary") or []),
        "interpretation_status": seen.get("interpretation_status"),
        "judge": None if judge is None else {
            "recognizable_family": judge["recognizable_family"], "family_confidence": judge.get("family_confidence"),
            "silhouette_clarity": judge["silhouette_clarity"],
            "explanation_required_to_understand": judge["explanation_required_to_understand"],
            "layer5_meaningful": judge.get("layer5_meaningful"), "completeness_score": judge.get("completeness_score"),
            "awkward": judge.get("awkward"), "verdict": _verdict(judge),
        },
        "design_intent": intent, "regenerations": regenerations, "source": "LLM", "error": error,
    }


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
    for reason in result["reasons"]:
        if reason["rule"] == "llm_call_failed":
            return _result("FAILED", hri_result, None, questions, "LLM_CALL_FAILED", reason["message"])
    return _result(
        "FAILED", hri_result, None, questions, "DESIGN_GENERATION_FAILED",
        "no valid design within the attempt limit", result["reasons"],
    )


def _use_llm():
    # import 시점이 아니라 호출 시점에 읽는다: 테스트·D 통합이 실행 중에 바꿀 수 있다.
    return os.environ.get("C_DESIGN_USE_LLM") == "1"


def create_initial_design(text=None, should_stop=None):
    """목표 문장 → Initial Design (§4.1)."""
    if text is None:
        text = voice.listen()
        if text is None:
            return _result("FAILED", code="VOICE_IO_FAILED", message=_voice_failure())
    elif not isinstance(text, str):
        return _result("FAILED", code="INVALID_INPUT", message="text must be a str or None")

    object_type = dialogue.parse_goal(text)
    if object_type is None:
        return _result("FAILED", code="UNSUPPORTED_OBJECT", message="no supported object in the goal")

    generate = None
    if _use_llm():
        def generate(object_type, reasons):
            return llm.generate_initial_design(object_type, reasons, should_stop=should_stop)
    result = designer.build_initial_design(
        object_type, generate=generate, delay=designer.RETRY_DELAY, should_stop=should_stop
    )
    if result["design"] is None:
        return _from_designer(result, None, [])
    if generate is None:
        return _result("OK", None, result["design"], design_metadata=_mock_metadata(revised=False))
    described = llm.describe_initial_design(result["design"], should_stop=should_stop)
    if _llm_error_kind(described) == "stopped":
        return _stopped([])
    return _result("OK", None, result["design"], design_metadata=_initial_metadata(described))


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
        """다음 의미 있는 응답. None이면 텍스트 응답 소진 또는 음성 I/O 실패, _STOP이면 STOP."""
        while True:
            reply = voice.listen() if voice_mode else next(answers, None)
            if reply is None or dialogue.is_meaningful(reply):
                return reply
            # 침묵·빈 발화: Day4는 시간 기준 재질문·취소 없이 계속 기다리되 STOP은 확인한다(§4.3).
            if stop_requested():
                return _STOP

    def no_reply():
        if voice_mode:
            return _result("FAILED", questions=questions, code="VOICE_IO_FAILED", message=_voice_failure())
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

    use_llm = _use_llm()
    # LLM 모드에서 설계 의도·metadata 오류를 요청 단위로 모은다(error는 마지막 오류).
    state = {"intent": None, "error": None}

    def make_generate(feedback=None):
        if not use_llm:
            return None

        def generate(design, current, differences, reasons):
            return llm.generate_revised_design(design, current, differences, reasons, should_stop=should_stop,
                                               intent=state["intent"], feedback=feedback)
        return generate

    def build(max_attempts, feedback=None):
        return designer.build_revised_design(
            design, current, differences, generate=make_generate(feedback), max_attempts=max_attempts,
            delay=designer.RETRY_DELAY, should_stop=should_stop,
        )

    def decide_intent():
        """설계 의도를 정한다. STOP이면 envelope, 그 밖의 실패는 intent 없이 진행(None 반환)."""
        intent = llm.generate_design_intent(design, current, differences, should_stop=should_stop)
        kind = _llm_error_kind(intent)
        if kind == "stopped":
            return _stopped(questions)
        if kind:
            state["error"] = _meta_error("intent_error", intent["llm_error"])
            return None
        missing = [key for key in llm.INTENT_KEYS if key not in intent]
        if missing:
            state["error"] = _meta_error("intent_error", f"missing intent keys: {missing}")
            return None
        state["intent"] = intent
        return None

    def finish(result):
        """설계 결과 → envelope. LLM이면 judge 후 조건이 맞을 때만 재생성(최대 METADATA_REGENERATIONS_MAX회)."""
        if result["design"] is None:
            return _from_designer(result, dialogue.REVISE, questions)
        if not use_llm:
            return _result("OK", dialogue.REVISE, result["design"], questions, design_metadata=_mock_metadata(revised=True))
        final = result["design"]
        regenerations = 0
        usable_judge = None
        while True:
            judge = llm.judge_revised_design(state["intent"], design, final, current, differences, should_stop=should_stop)
            if _llm_error_kind(judge) == "stopped":
                return _stopped(questions)
            problem = _judge_problem(judge)
            if problem is not None:
                state["error"] = _meta_error("judge_error", problem)  # 재생성하지 않고 그대로 끝낸다
                break
            usable_judge = judge
            if regenerations >= METADATA_REGENERATIONS_MAX or not _needs_regeneration(judge):
                break
            regenerations += 1
            again = build(FIRST_ATTEMPTS, feedback=llm.judge_feedback_text(judge))
            if again["design"] is None:
                if any(r["rule"] == "stopped" for r in again["reasons"]):
                    return _stopped(questions)
                state["error"] = _meta_error("regeneration_failed", [r["rule"] for r in again["reasons"]])
                break  # 첫 설계와 그 judge를 그대로 쓴다
            final = again["design"]
        metadata = _revised_metadata(state["intent"], usable_judge, regenerations, state["error"])
        return _result("OK", dialogue.REVISE, final, questions, design_metadata=metadata)

    def revise():
        if validator.current_support_violations(current):
            # Current를 그대로 보존하면 어떤 후보도 support를 통과할 수 없다(§8.11 즉시 진입).
            return escalate(can_redesign=False)
        if use_llm:
            stopped = decide_intent()
            if stopped is not None:
                return stopped
        result = build(FIRST_ATTEMPTS)
        # 설계 성공·STOP·provider 실패는 escalation 대상이 아니다(후보 탈락만 escalation).
        if result["design"] is not None or any(r["rule"] in ("stopped", "llm_call_failed") for r in result["reasons"]):
            return finish(result)
        ended = escalate(can_redesign=True)
        if ended is not None:
            return ended
        if stop_requested():
            return _stopped(questions)
        return finish(build(EXTRA_ATTEMPTS))

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
