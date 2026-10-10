"""C Design 공개 진입점.

목적:
    다른 파트(D Backend·통합)가 C를 호출하는 유일한 입구.
    Initial Design 흐름과 Intervention 대화 흐름을 orchestration한다.
    검증·문장·설계 로직은 validator / dialogue / designer에 위임한다.

구현 범위 (WAVE 4, docs/C_DESIGN_CONTRACT.md §4·§6·§8·§10):
    - create_initial_design(Stage 2 Wave 4b): LLM 모드에서 C가 먼저 인사("오늘 어떤 걸 만들고 싶으세요?")하고 자유 발화를
      한 번 듣는다(voice.listen mode "free"·beep, 침묵이면 재질문 1회; 텍스트 모드는 text). 명시적 "아무거나"류는 LLM 없이
      무작위 family, 그 밖은 llm.interpret_initial_request → 앉는 가구가 아니면 UNSUPPORTED_OBJECT, 모호하면 되묻기 1회
      (음성 또는 preference_text) 후 재해석, 그래도 모호하거나 해석 실패면 "아무거나"(무작위). llm.choose_initial_family
      (CREATIVE면 family 없이 concept) → designer.build_initial_design(family·style_hint·concept 주입) → 설명 → envelope.
      Mock 모드는 질문 없이 기존 흐름 그대로(목표 문장 parse_goal, D 통합 호환).
    - run_intervention: 입력 검사 → dialogue.build_question(주관식) → 응답 턴 반복
      (KEEP / REVISE / UNCLEAR 재질문 / 명시적 취소 / STOP). LLM 모드에서는 Rule이 결정하지 못한 답을
      llm.interpret_intervention_answer로 해석하고, Rule이 REVISE로 정한 답(숫자 답 제외)도 같은 함수로 style_hint만
      받는다(decision은 Rule 그대로). style_hint는 Revised 생성(llm.generate_revised_design)에 직접 넘긴다.
      Revised(LLM)는 designer.revised_min_blocks 이상의 블록을 요구한다(Mock은 검사 없음).
      → REVISE면 designer.build_revised_design(6회) → 탈락 시 §8.11 escalation 질문
      → "계속 찾기"면 4회 더(합계 10회) → 실패면 DESIGN_GENERATION_FAILED
    - Current가 support 후보 기준을 위반하면 재생성 없이 바로 escalation 질문
    - review_design_candidate(Stage 3 Wave 1): D가 Candidate Design의 Preview를 화면에 보인 뒤 부른다. 검토 질문 →
      (음성) free·beep 듣기 → dialogue.parse_review_response(LLM 모드에서만 llm.interpret_review_answer fallback) →
      APPROVE / MODIFY(style_hint까지만, 재생성 없음) / UNCLEAR(재질문 1회) / CANCEL → 확인 문장. design은 입력 candidate를
      바꾸지 않고 그대로 돌려주며, 검토 결과는 design_metadata.review에만 담는다. Intervention의 KEEP/REVISE와 섞지 않는다.
    - 진행 표시(Stage 2 Wave 4c): 두 공개 함수의 on_progress(선택)로 단계 이벤트 {stage, message, at}(PROGRESS_STAGES)를
      보내고, Design 생성 전에 항상 확인(ack) 한 문장(해석 reply 또는 dialogue fallback, KEEP은 keep_ack)을 낸다.
      LLM 음성 모드에서만 ack와 dialogue.PROGRESS_TTS_STAGES 문장을 읽는다. 진행은 envelope·Design에 넣지 않는다.
    - 텍스트 모드(text / text_answers)는 Fake Voice로 쓰인다.
    - 음성 모드: voice.speak(질문) 재생이 끝난 뒤 voice.listen()으로 응답을 받는다(WAVE 6).
      listen()이 None(장치·STT 실패)이면 VOICE_IO_FAILED, ""(침묵)이면 계속 기다린다.
    - Day4: 시간 기준 자동 취소 없음. 침묵(빈 발화)은 재질문 없이 계속 기다린다.
    - 설계 생성기: 호출 시점에 환경 변수 C_DESIGN_USE_LLM=1이면 llm(WAVE 5), 아니면 Mock.
      provider 실패는 LLM_CALL_FAILED로 반환한다.
    - design_metadata(2026-10-07): envelope의 design 옆 sibling 키. design 구조({design_version, blocks})는 그대로이며
      design이 None이면 None. Revised(LLM, Stage 2 Wave 4 After 구조): 생성(답변의 style_hint·min_blocks 직접 전달, 별도 설계
      의도 단계 없음) → validator → judge → judge가 family를 알아볼 수 없다(recognizable_family False)거나 실루엣이
      모호(silhouette_clarity "ambiguous")할 때만 judge 피드백으로 재생성 최대 METADATA_REGENERATIONS_MAX(1)회 → 재judge. Stage 2: 의자로 읽히지 않거나(chair_likeness "not_chair")
      이전보다 풍부하지 않을 때(richer_than_previous False)도 재생성 조건이다. judge 응답 오류·필드 누락은 재생성 없이 끝내고 error에 남긴다.
      metadata 생성 실패는 설계 성공을 FAILED로 바꾸지 않는다. KEEP·실패·취소는 None. Mock은 고정 문자열.
      Revised metadata의 design_intent는 항상 None이다(의도 단계가 없으므로 채우지 않는다).

하지 않는 것:
    - 음성 I/O·질문 문장·응답 규칙·LLM 호출·검증 로직 자체 구현(각 모듈에 위임)
    - Current 채택·Difference 판정·사람 조립 순서·NextPart·Robot 제어·화면 표시
    - import 시 녹음·재생·모델 로딩·네트워크 요청

연결:
    dialogue.py, voice.py, designer.py, llm.py(생성기 주입), validator.py(입력 검사·support 판정)를 호출한다.
    외부 모듈은 이 파일의 공개 함수만 호출한다.
"""

import os
import time
from copy import deepcopy

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
    "chair_likeness": ("clear", "weak", "not_chair"),
    "richer_than_previous": (True, False),
}
_HUMAN_STORY_KEYS = ("placed_differently", "interpretation", "imagined_concept", "lego_redesign", "why_final_shape")
_MOCK_NAME, _MOCK_FAMILY, _MOCK_SUMMARY = "Mock 의자", "chair", "Mock 고정 설계(LLM 미사용)"


# next_reply가 침묵 대기 중 STOP을 만났다는 표시(정상 응답 문자열·None과 구분).
_STOP = object()

# on_progress 이벤트 단계(Stage 2 Wave 4c). Initial: LISTENING → UNDERSTANDING → ACK → GENERATING → VALIDATING → DESCRIBING
# → READY. Revised: LISTENING → UNDERSTANDING → ACK(REVISE) 또는 KEEP_ACK(KEEP) → GENERATING_REVISED → VALIDATING → JUDGING
# → (REGENERATING → VALIDATING → JUDGING) → READY_REVISED. 끝이 실패·취소면 FAILED·CANCELLED, escalation 질문은 ESCALATION.
# HRI_INTERPRET(Stage 2 Wave 4e, LLM 모드 Intervention): 답변 결정 직후 decision·source(rule|llm)·reason·style_hint 디버그 이벤트.
# Preview 검토(Stage 3 Wave 1): REVIEW_LISTENING → REVIEW_UNDERSTANDING → HRI_INTERPRET → REVIEW_ACK → REVIEW_READY
# (UNCLEAR·침묵이면 재질문 1회, CANCEL은 REVIEW_ACK 뒤 CANCELLED). 음성으로 읽는 것은 질문·재질문·REVIEW_ACK뿐.
PROGRESS_STAGES = ("LISTENING", "UNDERSTANDING", "HRI_INTERPRET", "ACK", "KEEP_ACK", "GENERATING", "GENERATING_REVISED", "VALIDATING",
                   "DESCRIBING", "JUDGING", "REGENERATING", "ESCALATION", "READY", "READY_REVISED", "FAILED", "CANCELLED",
                   "REVIEW_LISTENING", "REVIEW_UNDERSTANDING", "REVIEW_ACK", "REVIEW_READY")


def _clock():
    now = time.time()
    return time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}"


def _reporter(on_progress, speak):
    """progress(stage, message=None, say=False). speak면 PROGRESS_TTS_STAGES와 say=True 문장만 음성으로 읽는다.

    progress는 Design·envelope에 넣지 않는다(표시·로그 전용). on_progress 예외는 호출자 책임(on_question과 같음).
    """
    def progress(stage, message=None, say=False):
        if message is None:
            message = dialogue.PROGRESS_MESSAGES.get(stage, "")
        if on_progress is not None:
            on_progress({"stage": stage, "message": message, "at": _clock()})
        if speak and (say or stage in dialogue.PROGRESS_TTS_STAGES):
            voice.speak(message)
    return progress


def _report_end(progress, envelope):
    """실패·취소 envelope이면 FAILED·CANCELLED 단계를 사유와 함께 알린다(성공 단계는 각 흐름이 알린다)."""
    if envelope["status"] in ("FAILED", "CANCELLED"):
        error = envelope["error"] or {}
        progress(envelope["status"], f"{error.get('code')}: {error.get('message')}")
    return envelope


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


def _initial_metadata(described, choice):
    """Initial(LLM) design_metadata. described는 llm.describe_initial_design 결과(dict 또는 llm_error),
    choice는 _family_choice 결과(요청 해석·고른 family 또는 concept·요청 해석 오류)."""
    error = choice["error"]
    if _llm_error_kind(described):
        error, described = _meta_error("describe_error", described["llm_error"]), {}
    return {
        "design_name": described.get("design_name"), "design_family": described.get("design_family"),
        "design_summary": described.get("design_summary"), "visible_features": list(described.get("visible_features") or []),
        "human_interpretation": None,
        "judge": None if not described else {
            key: described.get(key) for key in ("silhouette_clarity", "recognizable_family", "completeness_score")},
        "preference": choice["preference"], "selected_family": choice["family"], "family_source": choice["source"],
        "style_hint": choice["style_hint"], "family_design_match": described.get("family_design_match"),
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
    # 사용자 기준: family를 알아볼 수 없거나 실루엣이 모호할 때, Stage 2부터 의자로 읽히지 않거나 이전보다 풍부하지
    # 않을 때. awkward·weakly visible·feature mismatch만으로는 하지 않는다.
    return (judge["recognizable_family"] is False or judge["silhouette_clarity"] == "ambiguous"
            or judge["chair_likeness"] == "not_chair" or judge["richer_than_previous"] is False)


def _verdict(judge):
    showcase = (judge["reads_as_seating"] and judge["recognizable_family"] and judge["silhouette_clarity"] == "clear"
                and judge["explanation_required_to_understand"] is False
                and judge["chair_likeness"] != "not_chair" and judge["richer_than_previous"] is True)
    return "SHOWCASE" if showcase else "NOT_YET"


def _revised_metadata(judge, regenerations, error, style_hint):
    """Revised(LLM) design_metadata. 설명은 judge(판단 가능한 응답 또는 None)에서만 온다."""
    seen = judge or {}
    story = seen.get("human_story")
    return {
        "design_name": seen.get("design_name"),
        "design_family": seen.get("design_family"),
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
            "awkward": judge.get("awkward"), "chair_likeness": judge["chair_likeness"],
            "richer_than_previous": judge["richer_than_previous"], "richer_why": judge.get("richer_why"),
            "verdict": _verdict(judge),
        },
        "design_intent": None, "regenerations": regenerations, "style_hint": style_hint, "source": "LLM", "error": error,
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


_UNSUPPORTED = object()  # Initial 요청이 앉는 가구가 아닌 사물을 분명히 요구했다는 표시


def _interpret_request(text, should_stop):
    """llm.interpret_initial_request → (요청 dict 또는 None, 오류 또는 None) 또는 _STOP.

    해석 실패·REQUEST_KEYS 누락은 (None, request_error)로 돌려 "아무거나"로 진행하게 한다(설계는 계속).
    """
    interpreted = llm.interpret_initial_request(text, should_stop=should_stop)
    kind = _llm_error_kind(interpreted)
    if kind == "stopped":
        return _STOP
    if kind:
        return None, _meta_error("request_error", interpreted["llm_error"])
    missing = [key for key in llm.REQUEST_KEYS if key not in interpreted]
    if missing:
        return None, _meta_error("request_error", f"missing request keys: {missing}")
    return interpreted, None


def _needs_follow_up(request):
    return request["object"] == "UNCLEAR" or request["sufficient"] is not True


def _family_choice(request, error):
    """해석된 요청(또는 None = 아무거나) → {family, source, preference, style_hint, concept, error}.

    CREATIVE는 카탈로그 family로 환원하지 않고(family None) style_hint 전체를 concept로 생성에 넘긴다.
    """
    family = llm.choose_initial_family(request)
    mode = request.get("preference") if request is not None else None
    style_hint = request.get("style_hint") if request is not None else None
    style_hint = style_hint if isinstance(style_hint, str) and style_hint else None
    if mode == "CREATIVE":
        source = "creative"
    elif mode == "SPECIFIC" and family is not None and request.get("family") == family:
        source = "preference"
    else:
        source = "random"
    return {"family": family, "source": source, "preference": request, "style_hint": style_hint,
            "concept": style_hint if mode == "CREATIVE" else None, "error": error}


def _revised_builder(approved, current, differences, make_generate, min_blocks, should_stop):
    """approved(Revised 버전 기준 Design)·Current를 보존하는 Revised 후보 생성 함수 build(max_attempts, feedback=None)."""
    def build(max_attempts, feedback=None):
        return designer.build_revised_design(
            approved, current, differences, generate=make_generate(feedback), max_attempts=max_attempts,
            delay=designer.RETRY_DELAY, should_stop=should_stop, min_blocks=min_blocks,
        )
    return build


def _finish_revised(result, *, approved, current, differences, build, use_llm, should_stop, progress, questions, hri_result,
                    style_hint):
    """Revised 설계 결과 → envelope. LLM이면 judge 후 조건이 맞을 때만 재생성(최대 METADATA_REGENERATIONS_MAX회).

    run_intervention(REVISE)과 review_design_candidate(Revised 후보 MODIFY)가 같이 쓴다.
    """
    if result["design"] is None:
        return _from_designer(result, hri_result, questions)
    progress("VALIDATING")
    if not use_llm:
        progress("READY_REVISED")
        return _result("OK", hri_result, result["design"], questions, design_metadata=_mock_metadata(revised=True))
    final = result["design"]
    regenerations, usable_judge, error = 0, None, None
    while True:
        progress("JUDGING")
        judge = llm.judge_revised_design(approved, final, current, differences, should_stop=should_stop)
        if _llm_error_kind(judge) == "stopped":
            return _stopped(questions)
        problem = _judge_problem(judge)
        if problem is not None:
            error = _meta_error("judge_error", problem)  # 재생성하지 않고 그대로 끝낸다
            break
        usable_judge = judge
        if regenerations >= METADATA_REGENERATIONS_MAX or not _needs_regeneration(judge):
            break
        regenerations += 1
        progress("REGENERATING")
        again = build(FIRST_ATTEMPTS, feedback=llm.judge_feedback_text(judge))
        if again["design"] is None:
            if any(r["rule"] == "stopped" for r in again["reasons"]):
                return _stopped(questions)
            error = _meta_error("regeneration_failed", [r["rule"] for r in again["reasons"]])
            break  # 첫 설계와 그 judge를 그대로 쓴다
        final = again["design"]
        progress("VALIDATING")
    progress("READY_REVISED")
    metadata = _revised_metadata(usable_judge, regenerations, error, style_hint)
    return _result("OK", hri_result, final, questions, design_metadata=metadata)


def create_initial_design(text=None, should_stop=None, preference_text=None, on_question=None, on_progress=None):
    """첫 자유 발화 → (LLM 모드) 요청 해석·필요 시 되묻기 1회·확인(ack)·family 또는 concept 선택 → Initial Design (§4.1).

    text: 첫 자유 발화 전체(None이면 음성 모드: C가 인사하고 듣는다). Mock 모드에서는 목표 문장(parse_goal).
    preference_text: 텍스트 모드에서 되묻기(follow-up)에 대한 답(None이면 되묻지 않고 "아무거나"로 진행).
    on_question: C가 질문(인사·재질문·되묻기)을 낼 때 그 문장으로 호출(HMI 표시용, 예외는 호출자 책임).
    on_progress: 진행 단계마다 {"stage", "message", "at"}로 호출(PROGRESS_STAGES, 표시·로그용, 예외는 호출자 책임).
    """
    speak = text is None and _use_llm()  # 진행 음성은 LLM 음성 모드에서만(Mock·텍스트 모드는 콜백·로그만)
    progress = _reporter(on_progress, speak)
    return _report_end(progress, _initial(text, should_stop, preference_text, on_question, progress))


def _initial(text, should_stop, preference_text, on_question, progress):
    voice_mode = text is None
    if not voice_mode and not isinstance(text, str):
        return _result("FAILED", code="INVALID_INPUT", message="text must be a str or None")
    if preference_text is not None and not isinstance(preference_text, str):
        return _result("FAILED", code="INVALID_INPUT", message="preference_text must be a str or None")

    if not _use_llm():
        # Mock: 기존 흐름 그대로(목표 문장 한 번, 질문 없음). D 통합·계약 테스트가 이 경로를 쓴다.
        if voice_mode:
            text = voice.listen()
            if text is None:
                return _result("FAILED", code="VOICE_IO_FAILED", message=_voice_failure())
        object_type = dialogue.parse_goal(text)
        if object_type is None:
            return _result("FAILED", code="UNSUPPORTED_OBJECT", message="no supported object in the goal")
        progress("GENERATING")
        result = designer.build_initial_design(object_type, delay=designer.RETRY_DELAY, should_stop=should_stop)
        if result["design"] is None:
            return _from_designer(result, None, [])
        progress("VALIDATING")
        progress("READY")
        return _result("OK", None, result["design"], design_metadata=_mock_metadata(revised=False))

    questions = []

    def ask(sentence):
        questions.append(sentence)
        if on_question is not None:
            on_question(sentence)
        if voice_mode:
            voice.speak(sentence)

    def say(sentence):
        if voice_mode:
            voice.speak(sentence)  # 안내·되읽기(질문이 아니므로 questions에는 넣지 않는다)

    def stop_requested():
        return should_stop is not None and should_stop()

    def hear():
        progress("LISTENING")
        return voice.listen(mode="free", beep=True)

    def voice_failed():
        return _result("FAILED", questions=questions, code="VOICE_IO_FAILED", message=_voice_failure())

    if voice_mode:
        voice.prewarm()  # 첫 listen의 장치 준비 지연을 인사 TTS 전에 치른다(실패해도 listen에서 다시 드러남)
        if stop_requested():
            return _stopped(questions)
        ask(dialogue.build_greeting())
        text = hear()
        if text is None:
            return voice_failed()
        if not dialogue.is_meaningful(text):
            if stop_requested():
                return _stopped(questions)
            ask(dialogue.SILENCE_REASK)  # 침묵은 한 번만 다시 묻고, 그래도 없으면 "아무거나"로 진행한다
            text = hear()
            if text is None:
                return voice_failed()

    request, error, fallback = None, None, False
    if stop_requested():
        return _stopped(questions)
    progress("UNDERSTANDING")
    if not dialogue.is_meaningful(text):
        fallback = True
    elif dialogue.is_unsupported_request(text):  # "자동차 만들어줘": LLM 호출 없이 지원 밖(Mock parse_goal과 같은 보장)
        request = _UNSUPPORTED
    elif dialogue.parse_initial_request(text) is None:  # 명시적 "아무거나"는 해석·되묻기 없이 무작위
        interpreted = _interpret_request(text, should_stop)
        if interpreted is _STOP:
            return _stopped(questions)
        request, error = interpreted
        if request is None:
            fallback = True
        elif request["object"] == "UNSUPPORTED":
            request = _UNSUPPORTED
        elif _needs_follow_up(request):
            follow_up = request["follow_up"] if isinstance(request["follow_up"], str) else ""
            answer = None
            if follow_up.strip() and (voice_mode or preference_text is not None):
                if stop_requested():
                    return _stopped(questions)
                ask(follow_up)
                answer = hear() if voice_mode else preference_text
                if answer is None:
                    return voice_failed()
                progress("UNDERSTANDING")
            request = None
            if not dialogue.is_meaningful(answer):
                fallback = True
            elif dialogue.is_unsupported_request(answer):
                request = _UNSUPPORTED
            elif dialogue.parse_initial_request(answer) is None:
                interpreted = _interpret_request(f"{text} / {answer}", should_stop)
                if interpreted is _STOP:
                    return _stopped(questions)
                request, error = interpreted
                if request is not None and request["object"] == "UNSUPPORTED":
                    request = _UNSUPPORTED
                elif request is None or _needs_follow_up(request):
                    request, fallback = None, True  # 두 번째도 모호하면 더 묻지 않고 무작위
    if request is _UNSUPPORTED:
        say(dialogue.UNSUPPORTED_REPLY)
        return _result("FAILED", questions=questions, code="UNSUPPORTED_OBJECT",
                       message="the request is not seating furniture")

    choice = _family_choice(request, error)
    # 생성 전에 항상 요청을 되짚는다(ack). 해석의 reply가 있으면 그것, 없으면(규칙 "아무거나"·침묵·해석 실패·되묻기 뒤
    # 무작위) 확인 문장. 음성 모드에서는 바로 읽어 첫 응답이 Design 생성을 기다리지 않게 한다.
    reply = None if fallback else (request or {}).get("reply")
    if not (isinstance(reply, str) and reply.strip()):
        reply = dialogue.initial_ack_fallback(family=choice["family"], concept=choice["concept"])
    progress("ACK", reply, say=True)
    progress("GENERATING")

    def generate(object_type, reasons):
        return llm.generate_initial_design(object_type, reasons, should_stop=should_stop, family=choice["family"],
                                           style_hint=choice["style_hint"], concept=choice["concept"])
    result = designer.build_initial_design("CHAIR", generate=generate, delay=designer.RETRY_DELAY, should_stop=should_stop)
    if result["design"] is None:
        return _from_designer(result, None, questions)
    progress("VALIDATING")
    progress("DESCRIBING")
    described = llm.describe_initial_design(result["design"], should_stop=should_stop, family=choice["family"],
                                            concept=choice["concept"])
    if _llm_error_kind(described) == "stopped":
        return _stopped(questions)
    progress("READY")
    return _result("OK", None, result["design"], questions, design_metadata=_initial_metadata(described, choice))


def run_intervention(design, current, differences, text_answers=None, on_question=None, should_stop=None, on_progress=None):
    """실제 차이에 대한 사용자 의도 확인 (§4.2). 예외를 밖으로 던지지 않는다(on_question·on_progress 제외).

    on_progress: 진행 단계마다 {"stage", "message", "at"}로 호출(PROGRESS_STAGES, 표시·로그용).
    """
    progress = _reporter(on_progress, text_answers is None and _use_llm())
    return _report_end(progress, _intervention(design, current, differences, text_answers, on_question, should_stop,
                                               progress))


def _intervention(design, current, differences, text_answers, on_question, should_stop, progress):
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

    use_llm = _use_llm()

    def next_reply():
        """다음 의미 있는 응답. None이면 텍스트 응답 소진 또는 음성 I/O 실패, _STOP이면 STOP."""
        while True:
            if voice_mode and use_llm:
                progress("LISTENING")
            reply = voice.listen(mode="free", beep=True) if voice_mode else next(answers, None)
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
        if use_llm:
            progress("ESCALATION")
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
                return keep()
            if choice == dialogue.CANCEL:
                return _user_cancel(questions)
            if choice == dialogue.KEEP_SEARCHING and can_redesign:
                return None
            # UNCLEAR, 또는 재설계할 수 없는데 "계속 찾기": 같은 질문으로 명시 선택을 기다린다.
            ask(question)

    # LLM 모드에서 답변의 style_hint와 확인 문장(reply)을 요청 단위로 모은다.
    state = {"style_hint": None, "reply": None, "reason": None, "stopped": False, "interpreted": False}
    # Revised(LLM)는 이전 Design보다 풍부해야 한다(§8.13). Mock 후보는 결정론적 이동뿐이라 검사하지 않는다.
    min_blocks = designer.revised_min_blocks(design) if use_llm else None

    def ask_answer_llm(text):
        """llm 답변 해석 1회. 쓸 수 있는 dict 또는 None(STOP이면 state["stopped"], 실패·키 누락이면 그냥 None)."""
        state["interpreted"] = True
        answer = llm.interpret_intervention_answer(text, differences, should_stop=should_stop)
        kind = _llm_error_kind(answer)
        if kind == "stopped":
            state["stopped"] = True
        if kind or any(key not in answer for key in llm.INTERVENTION_ANSWER_KEYS):
            return None
        state["reason"] = answer["reason"] if isinstance(answer["reason"], str) else None
        return answer

    def usable_hint(answer):
        hint = answer["style_hint"] if answer is not None else None
        return hint if isinstance(hint, str) and hint else None

    def interpret_answer(text):
        """Rule이 결정하지 못한 답(LLM 모드만) → KEEP/REVISE/UNCLEAR/CANCEL. 해석 실패·키 누락은 UNCLEAR(재질문)."""
        answer = ask_answer_llm(text)
        if answer is None:
            return dialogue.UNCLEAR
        revise = answer["decision"] == dialogue.REVISE
        state["style_hint"] = usable_hint(answer) if revise else None
        state["reply"] = usable_reply(answer) if revise else None
        return answer["decision"]

    def usable_reply(answer):
        reply = answer.get("reply") if answer is not None else None  # reply 키는 Wave 4c llm(A)부터
        return reply if isinstance(reply, str) and reply.strip() else None

    def keep():
        if use_llm:
            progress("KEEP_ACK", dialogue.keep_ack(), say=True)
        return _result("OK", dialogue.KEEP, design, questions)

    def make_generate(feedback=None):
        if not use_llm:
            return None

        def generate(design, current, differences, reasons):
            return llm.generate_revised_design(design, current, differences, reasons, should_stop=should_stop,
                                               feedback=feedback, min_blocks=min_blocks, style_hint=state["style_hint"])
        return generate

    build = _revised_builder(design, current, differences, make_generate, min_blocks, should_stop)

    def finish(result):
        return _finish_revised(result, approved=design, current=current, differences=differences, build=build,
                               use_llm=use_llm, should_stop=should_stop, progress=progress, questions=questions,
                               hri_result=dialogue.REVISE, style_hint=state["style_hint"])

    def revise():
        if validator.current_support_violations(current):
            # Current를 그대로 보존하면 어떤 후보도 support를 통과할 수 없다(§8.11 즉시 진입).
            return escalate(can_redesign=False)
        if use_llm:
            # 생성 전에 항상 확인(ack): 해석 reply(LLM이 REVISE로 해석한 경우) 또는 확인 문장(숫자 답·해석 실패).
            progress("ACK", state["reply"] or dialogue.revise_ack_fallback(state["style_hint"]), say=True)
        progress("GENERATING_REVISED")
        result = build(FIRST_ATTEMPTS)
        # 설계 성공·STOP·provider 실패는 escalation 대상이 아니다(후보 탈락만 escalation).
        if result["design"] is not None or any(r["rule"] in ("stopped", "llm_call_failed") for r in result["reasons"]):
            return finish(result)
        ended = escalate(can_redesign=True)
        if ended is not None:
            return ended
        if stop_requested():
            return _stopped(questions)
        progress("GENERATING_REVISED")
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
        state["interpreted"], state["reason"] = False, None
        if use_llm:
            progress("UNDERSTANDING")
        choice = dialogue.parse_response(reply, interpret_answer if use_llm else None)
        source = "llm" if state["interpreted"] else "rule"  # decision을 정한 쪽(아래 style_hint 전용 호출과 무관)
        if (use_llm and choice == dialogue.REVISE and not state["interpreted"]
                and not dialogue.is_number_answer(reply)):
            # Rule이 REVISE로 정한 자유 답변("일부러 놨어요. 팔걸이로 살려주세요")에서 바람만 받는다. decision은 Rule 그대로,
            # 해석 실패는 힌트 없이 진행한다(재질문 없음). LLM decision이 REVISE일 때만 그 reply를 확인 문장으로 쓴다.
            answer = ask_answer_llm(reply)
            state["style_hint"] = usable_hint(answer)
            state["reply"] = usable_reply(answer) if answer is not None and answer["decision"] == dialogue.REVISE else None
        if state["stopped"]:
            return _stopped(questions)
        if use_llm:
            # 디버그 전용(음성 없음): 사람이 한 말이 어떻게 해석됐는지 ACK/KEEP_ACK·재질문 전에 남긴다.
            progress("HRI_INTERPRET", f"decision={choice} source={source} reason={state['reason'] or ''} "
                                      f"style_hint={state['style_hint'] or ''}")
        if choice == dialogue.KEEP:
            return keep()
        if choice == dialogue.CANCEL:
            return _user_cancel(questions)
        if choice == dialogue.REVISE:
            return revise()
        ask(dialogue.build_reask(question))



REVIEW_KINDS = ("initial", "revised")
REVIEW_SCOPES = ("patch", "redesign", "concept_change")  # MODIFY 재생성 방식(내부 값, metadata.review.scope에만 기록)


def review_design_candidate(candidate, *, kind, design_metadata=None, previous_design=None, current=None, differences=None,
                            text_answers=None, on_question=None, should_stop=None, on_progress=None):
    """Preview가 표시된 Candidate Design에 대한 사용자 검토 (§4.4, Stage 3 Wave 1·2). 예외를 밖으로 던지지 않는다(콜백 제외).

    kind: "initial" 또는 "revised"(질문 문장·LLM 해석 문맥). design_metadata: 후보의 metadata(복사해 review를 붙여 돌려줌).
    previous_design·current·differences: kind="revised"일 때 필수(Approved Design·Current 블록·Difference, Revised 재생성 기준).
    text_answers: 텍스트 모드 답변(None이면 음성 모드). 결과 hri_result는 APPROVE / MODIFY / UNCLEAR, CANCEL이면 status CANCELLED.
    LLM 모드의 MODIFY는 새 Candidate를 만들어 design에 담는다(Approved 아님, 승인은 다음 검토의 APPROVE·채택은 D).
    """
    use_llm = _use_llm()
    progress = _reporter(on_progress, text_answers is None and use_llm)  # REVIEW_* 단계는 읽지 않고 ack·생성 진행만 읽는다
    return _report_end(progress, _review(candidate, kind, design_metadata, previous_design, current, differences,
                                         text_answers, on_question, should_stop, progress, use_llm))


def _candidate_concept(metadata):
    """후보가 따르는 concept: 앞선 검토가 갱신한 concept, 아니면 CREATIVE Initial의 style_hint(=concept)."""
    review = metadata.get("review") if isinstance(metadata.get("review"), dict) else {}
    if isinstance(review.get("concept"), str) and review["concept"]:
        return review["concept"]
    if metadata.get("family_source") == "creative" and isinstance(metadata.get("style_hint"), str):
        return metadata["style_hint"] or None
    return None


def _review(candidate, kind, design_metadata, previous_design, current, differences, text_answers, on_question,
            should_stop, progress, use_llm):
    if kind not in REVIEW_KINDS:
        return _result("FAILED", code="INVALID_INPUT", message=f"kind must be one of {list(REVIEW_KINDS)}")
    reasons = validator.validate_design(candidate)
    if reasons:
        return _result("FAILED", code="INVALID_INPUT", message="invalid candidate design", details=reasons)
    if design_metadata is not None and not isinstance(design_metadata, dict):
        return _result("FAILED", code="INVALID_INPUT", message="design_metadata must be a dict or None")
    if kind == "revised":
        if previous_design is None or current is None or differences is None:
            return _result("FAILED", code="INVALID_INPUT",
                           message="kind 'revised' needs previous_design, current and differences")
        reasons = validator.check_intervention_input(previous_design, current, differences)
        if reasons:
            return _result("FAILED", code="INVALID_INPUT", message="invalid revised review input", details=reasons)
    design = deepcopy(candidate)  # 후보는 읽기 전용: 같은 내용을 새 객체로 돌려준다
    metadata = deepcopy(design_metadata) if design_metadata is not None else {}
    previous_review = metadata.get("review") if isinstance(metadata.get("review"), dict) else {}
    base_round = previous_review.get("round") if isinstance(previous_review.get("round"), int) else 0
    context = {"family": metadata.get("selected_family"), "concept": _candidate_concept(metadata)}

    questions = []
    voice_mode = text_answers is None
    answers = None if voice_mode else iter(text_answers)
    state = {"style_hint": None, "scope": None, "concept": None, "reply": None, "reason": None, "stopped": False,
             "interpreted": False, "answers": 0}

    def ask(sentence):
        questions.append(sentence)
        if on_question is not None:
            on_question(sentence)
        if voice_mode and use_llm:  # Mock은 음성 없이 규칙만(질문은 on_question·questions로 전달)
            voice.speak(sentence)

    def stop_requested():
        return should_stop is not None and should_stop()

    def ask_review_llm(text):
        """llm 검토 해석 1회. 쓸 수 있는 dict 또는 None(STOP이면 state["stopped"])."""
        state["interpreted"] = True
        answer = llm.interpret_review_answer(text, kind, should_stop=should_stop, context=context)
        kind_error = _llm_error_kind(answer)
        if kind_error == "stopped":
            state["stopped"] = True
        if kind_error or any(key not in answer for key in llm.REVIEW_KEYS):
            return None
        state["reason"] = answer["reason"] if isinstance(answer["reason"], str) else None
        return answer

    def text_of(answer, key):
        value = answer.get(key) if answer is not None else None
        return value if isinstance(value, str) and value.strip() else None

    def interpret(text):
        """Rule이 정하지 못한 검토 답(LLM 모드만). 해석 실패·키 누락은 UNCLEAR."""
        answer = ask_review_llm(text)
        if answer is None:
            return dialogue.UNCLEAR
        modify = answer["decision"] == dialogue.MODIFY
        take_modify(answer if modify else None)
        state["reply"] = text_of(answer, "reply")
        return answer["decision"]

    def take_modify(answer):
        """MODIFY 해석에서 바꿀 방향·재생성 방식·갱신 concept을 받는다(없으면 None)."""
        state["style_hint"] = text_of(answer, "style_hint")
        scope = text_of(answer, "scope")
        state["scope"] = scope if scope in REVIEW_SCOPES else None
        state["concept"] = text_of(answer, "concept")

    def review_of(decision, source, round_):
        return {"kind": kind, "decision": decision, "style_hint": state["style_hint"], "scope": state["scope"],
                "concept": state["concept"], "round": round_, "answers": state["answers"], "source": source,
                "reply": state["reply"]}

    def outcome(decision, source):
        return dict(metadata, review=review_of(decision, source, base_round))

    def regenerate(source):
        """LLM 모드 MODIFY: 새 Candidate를 만든다(Initial은 version 1, Revised는 Approved + 1). envelope 또는 실패."""
        scope = state["scope"] or "patch"  # 해석이 방식을 주지 못하면 현재 후보를 살린 부분 수정
        state["scope"] = scope
        hint = state["style_hint"]
        review = review_of(dialogue.MODIFY, source, base_round + 1)
        if kind == "revised":
            min_blocks = designer.revised_min_blocks(previous_design)

            def make_generate(feedback=None):
                def generate(design_, current_, differences_, reasons_):
                    return llm.generate_revised_design(design_, current_, differences_, reasons_, should_stop=should_stop,
                                                       feedback=feedback, min_blocks=min_blocks, style_hint=hint,
                                                       previous_candidate=candidate, scope=scope)
                return generate

            build = _revised_builder(previous_design, current, differences, make_generate, min_blocks, should_stop)
            progress("GENERATING_REVISED")
            envelope = _finish_revised(build(designer.MAX_ATTEMPTS), approved=previous_design, current=current,
                                       differences=differences, build=build, use_llm=use_llm, should_stop=should_stop,
                                       progress=progress, questions=questions, hri_result=dialogue.MODIFY, style_hint=hint)
        else:
            family, concept = None, None
            if scope == "patch":
                family = metadata.get("selected_family")
                concept = state["concept"] or context["concept"]
                previous_hint = metadata.get("style_hint")
                # 이전 요청의 방향은 이어 붙이되, CREATIVE 후보의 style_hint(=이전 concept)는 concept로 따로 다룬다.
                if isinstance(previous_hint, str) and previous_hint and previous_hint not in (concept, context["concept"]):
                    hint = " / ".join(part for part in (previous_hint, hint) if part)
            elif scope == "concept_change":
                concept = state["concept"]
            choice = {"family": family, "source": scope, "preference": metadata.get("preference"), "style_hint": hint,
                      "concept": concept, "error": None}

            def generate(object_type, reasons_):
                return llm.generate_initial_design(object_type, reasons_, should_stop=should_stop, family=family,
                                                   style_hint=hint, concept=concept, previous_candidate=candidate,
                                                   scope=scope)
            progress("GENERATING")
            result = designer.build_initial_design("CHAIR", generate=generate, delay=designer.RETRY_DELAY,
                                                   should_stop=should_stop)
            if result["design"] is None:
                return _from_designer(result, dialogue.MODIFY, questions)
            progress("VALIDATING")
            progress("DESCRIBING")
            described = llm.describe_initial_design(result["design"], should_stop=should_stop, family=family, concept=concept)
            if _llm_error_kind(described) == "stopped":
                return _stopped(questions)
            progress("READY")
            envelope = _result("OK", dialogue.MODIFY, result["design"], questions,
                               design_metadata=_initial_metadata(described, choice))
        if envelope["status"] == "OK":
            envelope["design_metadata"] = dict(envelope["design_metadata"], review=review)
        return envelope

    question = dialogue.build_review_question(kind)
    for attempt in range(2):  # 첫 질문 + 불명확·침묵일 때 재질문 1회
        if stop_requested():
            return _stopped(questions)
        progress("REVIEW_LISTENING")
        ask(question if attempt == 0 else dialogue.build_review_reask())
        reply = voice.listen(mode="free", beep=True) if voice_mode else next(answers, None)
        if reply is None:
            if voice_mode:
                return _result("FAILED", questions=questions, code="VOICE_IO_FAILED", message=_voice_failure())
            break  # 텍스트 답변 소진
        if not dialogue.is_meaningful(reply):
            continue  # 침묵: 한 번만 다시 묻는다
        state["answers"] += 1
        state.update(style_hint=None, scope=None, concept=None, reply=None, reason=None, interpreted=False)
        progress("REVIEW_UNDERSTANDING")
        decision = dialogue.parse_review_response(reply, interpret if use_llm else None)
        source = "llm" if state["interpreted"] else "rule"
        if use_llm and decision == dialogue.MODIFY and not state["interpreted"]:
            # Rule이 MODIFY로 정한 답에서 바꾸고 싶은 방향만 받는다(decision은 Rule 그대로, 실패면 힌트 없이 진행).
            answer = ask_review_llm(reply)
            take_modify(answer)
            state["reply"] = text_of(answer, "reply") if answer is not None and answer["decision"] == dialogue.MODIFY else None
        if state["stopped"]:
            return _stopped(questions)
        progress("HRI_INTERPRET", f"decision={decision} source={source} reason={state['reason'] or ''} "
                                  f"style_hint={state['style_hint'] or ''}")
        if decision == dialogue.UNCLEAR:
            continue
        if decision == dialogue.APPROVE:
            ack = state["reply"] or dialogue.approve_ack()
        elif decision == dialogue.MODIFY:
            ack = state["reply"] or dialogue.modify_ack_fallback(state["style_hint"])
        else:
            ack = state["reply"] or dialogue.cancel_ack()
        state["reply"] = ack
        progress("REVIEW_ACK", ack, say=True)
        if decision == dialogue.CANCEL:
            return _result("CANCELLED", "CANCEL", design, questions, code="USER_CANCEL", message="cancelled by user",
                           design_metadata=outcome(decision, source))
        if decision == dialogue.MODIFY and use_llm:
            if stop_requested():
                return _stopped(questions)
            return regenerate(source)  # ack 뒤에 바로 새 Candidate(Mock은 Wave 1처럼 후보 그대로)
        progress("REVIEW_READY")
        return _result("OK", decision, design, questions, design_metadata=outcome(decision, source))
    state["reply"] = None
    progress("REVIEW_READY")
    return _result("OK", dialogue.UNCLEAR, design, questions,
                   design_metadata=outcome(dialogue.UNCLEAR, "llm" if state["interpreted"] else "rule"))
