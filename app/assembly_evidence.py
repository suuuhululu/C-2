"""로봇 직접 조립 연구의 증거 조합 정책. 상태 채택이나 장치 명령을 수행하지 않는다.

입출력 계약: interfaces/schemas/assembly_evidence.schema.json의 input/output.
이 함수는 State Manager 연결 전의 순수 판단 helper다. 호출자는 동일 attempt,
증거 유효성/최신성, world/calibration, 실제 정지·해제·관측 조건을 검사해야 한다.
아래 context guard는 증거별 문맥을 검사한다. 구조 변화·정지·해제 조건의 검사와
실제 센서/Backend 연결은 후속 작업이며, 이 결과만으로 완료 commit하지 않는다.
"""

from math import isfinite

from app.contracts import _integer, _object, _text


def evaluate_assembly_evidence(*, execution_result: str | None,
                               contact_state: str | None,
                               vision_verdict: str | None,
                               motion_permitted: bool | None) -> dict:
    """None은 증거 미수신이다. UNKNOWN은 생산자가 판별 불가라고 보고한 결과다.

    ASSEMBLED는 SENSOR_VERIFIED 완료 후보이며 SM만 최종 기록할 수 있다.
    RECOVERY_REQUIRED는 원인 평가 요청으로 자동 재시도/후퇴 명령이 아니다.
    REQUEST_HUMAN_VERIFICATION은 판단 후보이며 사람 응답을 소비하지 않는다.
    잘못된 필드 값은 ValueError로 거절하고 성공/UNKNOWN으로 변환하지 않는다.
    """
    for field, value, allowed in (
        ("execution_result", execution_result, ("COMPLETE", "FAILED", "CANCELED", "TIMED_OUT")),
        ("contact_state", contact_state, ("FREE", "CONTACT", "ALIGNING", "INSERTING",
                                          "SNAP_CANDIDATE", "SEATED", "JAMMED", "UNKNOWN")),
        ("vision_verdict", vision_verdict, ("PASS", "FAIL", "UNKNOWN")),
    ):
        if value is not None and (not isinstance(value, str) or value not in allowed):
            raise ValueError(f"{field}: unsupported evidence value")
    if motion_permitted is not None and type(motion_permitted) is not bool:
        raise ValueError("motion_permitted: expected boolean or None")

    decision, reason, evidence = "HOLD", "WAIT_EXECUTION_RESULT", None
    # 안전 차단과 명확한 실패를 긍정 증거로 덮으면 잘못된 완료/사람 요청이 된다.
    if motion_permitted is False:
        decision, reason = "SAFE_STOP", "SAFETY_STOP"
    elif motion_permitted is None:
        reason = "SAFETY_UNKNOWN"
    elif execution_result in ("FAILED", "TIMED_OUT"):
        decision, reason = "RECOVERY_REQUIRED", f"EXECUTION_{execution_result}"
    elif contact_state == "JAMMED":
        decision, reason = "RECOVERY_REQUIRED", "JAMMED"
    elif vision_verdict == "FAIL":
        decision, reason = "RECOVERY_REQUIRED", "VISION_FAIL"
    elif execution_result == "CANCELED":
        reason = "EXECUTION_CANCELED"
    elif execution_result != "COMPLETE":
        reason = "WAIT_EXECUTION_RESULT"
    elif contact_state not in ("SEATED", "UNKNOWN"):
        reason = "WAIT_CONTACT_EVIDENCE"
    elif vision_verdict is None:
        reason = "WAIT_VISION_EVIDENCE"
    elif contact_state == "SEATED" and vision_verdict == "PASS":
        decision, reason, evidence = "ASSEMBLED", "SEATED_AND_VISION_PASS", "SENSOR_VERIFIED"
    else:
        decision, reason = "REQUEST_HUMAN_VERIFICATION", "ASSEMBLY_UNCERTAIN"
    return dict(decision=decision, reason=reason, verification_evidence=evidence)


def check_evidence_context(active: object, evidence: object, *, now: float,
                           max_age: float, last_sequence: int | None) -> dict:
    """증거 하나의 사용 가능 여부. now/opened_at/stamp/max_age는 동일 시계의 초다.

    active는 SM가 source/request별로 동결한 문맥이다. request 없는 접촉은 None을
    명시한다. last_sequence는 같은 문맥에서 처리한 순번의 하한, 첫 수신이면 None.
    최신 무효 샘플로 캐시를 비운 경우도 소비 순번을 유지해 옛 성공의 재사용을 막는다.
    basis는 attempt 시작 기준이며 관측 world revision으로 덮어쓰지 않는다.
    실제 reference 불변 여부·시계 감독·sequence 채택 기록은 호출자의 책임이다.
    """
    fields = ("job_id", "plan_id", "step_id", "attempt_id", "request_id",
              "calibration_id", "source_epoch", "basis_world_revision")
    active = _object(active, fields + ("opened_at",), "active")
    evidence = _object(evidence, fields + ("stamp", "sequence", "valid"), "evidence")
    for path, value in (("active", active), ("evidence", evidence)):
        for field in fields[:-1]:
            if field != "request_id" or value[field] is not None:
                _text(value[field], f"{path}.{field}")
        _integer(value["basis_world_revision"], 0, None, f"{path}.basis_world_revision")
    _integer(evidence["sequence"], 0, None, "evidence.sequence")
    if last_sequence is not None:
        _integer(last_sequence, 0, None, "last_sequence")
    if type(evidence["valid"]) is not bool:
        raise ValueError("evidence.valid: expected boolean")
    for field, value in (("now", now), ("max_age", max_age),
                         ("opened_at", active["opened_at"]), ("stamp", evidence["stamp"])):
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError(f"{field}: expected finite nonnegative seconds")
    if max_age == 0:
        raise ValueError("max_age: expected positive seconds")

    for field in fields:
        if evidence[field] != active[field]:
            return dict(accepted=False, reason=f"{field.upper()}_MISMATCH")
    if not evidence["valid"]:
        reason = "INVALID_EVIDENCE"
    elif now < active["opened_at"]:
        reason = "CLOCK_RESET"
    elif evidence["stamp"] < active["opened_at"]:
        reason = "BEFORE_REQUEST_WINDOW"
    elif evidence["stamp"] > now:
        reason = "FUTURE_EVIDENCE"
    elif now - evidence["stamp"] > max_age:
        reason = "STALE_EVIDENCE"
    elif last_sequence is not None and evidence["sequence"] <= last_sequence:
        reason = "STALE_SEQUENCE"
    else:
        return dict(accepted=True, reason="EVIDENCE_ACCEPTED")
    return dict(accepted=False, reason=reason)
