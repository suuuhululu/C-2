"""단일 시험의 시각 확인 프로토콜. 상태 채택·화면·실기 제어는 기존 Backend 쪽이다."""

from copy import deepcopy
from math import isfinite

from app.assembly_attempt import IDENTITY
from app.assembly_completion import _check_verification, _decision, _physical_guard
from app.assembly_evidence import check_evidence_context
from app.contracts import _object, _text


def close_human_verification(trial, reason):
    request = trial["human_verification"]
    if request is not None and request["status"] == "OPEN":
        request.update(status="CLOSED", close_reason=reason)


def refresh_human_verification(trial, now):
    """SM가 수집/만료 검사 후 호출한다. 닫힌 요청은 새 ID로만 다시 열 수 있다."""
    result = deepcopy(trial)
    request = result["human_verification"]
    if request is None or request["status"] != "OPEN":
        return result
    records, reason = result["collection"]["records"], None
    if result["collection"]["blocked_reason"]:
        reason = result["collection"]["blocked_reason"]
    elif result["completion"] is not None:
        reason = "COMPLETED_BY_SENSOR"
    elif result["blocked_reason"] or result["decision"]["decision"] in ("SAFE_STOP", "RECOVERY_REQUIRED"):
        reason = result["decision"]["reason"]
    elif now >= request["deadline"]:
        reason = "HUMAN_REQUEST_TIMED_OUT"
    elif any(record is None for record in records.values()):
        reason = "EVIDENCE_EXPIRED_OR_INVALID"
    elif records["vision_verdict"]["metadata"] != request["vision_metadata"] or records["contact_state"]["value"] != request["contact_value"]:
        reason = "EVIDENCE_CHANGED"
    elif records["execution_result"]["value"] != "COMPLETE" or records["motion_permitted"]["value"] is not True:
        reason = result["decision"]["reason"]
    if reason:
        close_human_verification(result, reason)
        if reason == "HUMAN_REQUEST_TIMED_OUT":
            result["decision"] = _decision(reason)
    else:
        result["decision"] = _decision("WAIT_HUMAN_RESPONSE")
    return result


def _physical_ready(physical, session_closed, stamp):
    if type(session_closed) is not bool:
        raise ValueError("session_closed: expected boolean")
    if not session_closed:
        return "SUPPORT_SESSION_NOT_CLOSED"
    if not all(physical[key] is True for key in ("stopped", "execution_ended", "released", "at_observe")):
        return "WAIT_PHYSICAL_CONFIRMATION"
    released, ready = physical["released_at"], physical["observe_ready_at"]
    if released is None or ready is None:
        return "WAIT_PHYSICAL_CONFIRMATION"
    if not released <= ready <= stamp <= physical["metadata"]["stamp"]:
        return "INVALID_COMPLETION_ORDER"
    return None


def _world_conflict(trial, observation):
    expected = trial["world"]["blocks"] + [trial["target"]]
    world = observation["world"]
    if world["world_revision"] not in (trial["world"]["world_revision"], trial["world"]["world_revision"] + 1):
        return "WORLD_REVISION_MISMATCH"
    if trial["target"] in world["blocks"] and world["world_revision"] == trial["world"]["world_revision"]:
        return "WORLD_REVISION_MISMATCH"
    if any(block not in expected for block in world["blocks"]):
        return "UNEXPECTED_WORLD_EFFECT"
    if observation["complete"] and any(block not in world["blocks"] for block in expected):
        return "TARGET_OR_REFERENCE_MISSING"
    return None


def open_human_verification(trial, *, request_id, verification, session_closed,
                            human_source_epoch, timeout, response_max_age, now):
    result = refresh_human_verification(trial, now)
    _text(request_id, "request_id")
    _text(human_source_epoch, "human_source_epoch")
    for name, value in (("timeout", timeout), ("response_max_age", response_max_age)):
        if type(value) not in (int, float) or not isfinite(value) or value <= 0:
            raise ValueError(f"{name}: expected positive finite seconds")
    if not isfinite(now + timeout):
        raise ValueError("timeout: deadline must be finite")
    request = result["human_verification"]
    if request is not None and request["status"] == "OPEN":
        return dict(state=result, accepted=False, reason="HUMAN_REQUEST_ALREADY_OPEN")
    verification = _object(verification, ("physical", "observation"), "verification")
    _object(verification["observation"], ("metadata", "complete", "world"), "observation")
    eligible = result["decision"]["decision"] == "REQUEST_HUMAN_VERIFICATION" or (
        result["decision"]["reason"] == "WAIT_COMPLETION_VERIFICATION" and verification["observation"]["complete"] is False)
    if result["completion"] is not None or result["blocked_reason"] or not eligible:
        return dict(state=result, accepted=False, reason="HUMAN_VERIFY_NOT_APPLICABLE")
    proof, _, guard = _check_verification(result, verification, now)
    reason = None if guard["accepted"] else guard["reason"]
    reason = reason or _physical_ready(proof["physical"], session_closed, proof["observation"]["metadata"]["stamp"])
    records = result["collection"]["records"]
    if reason is None and proof["observation"]["metadata"] != records["vision_verdict"]["metadata"]:
        reason = "VISION_FRAME_MISMATCH"
    capture = proof["observation"]["metadata"]["stamp"]
    if reason is None and (records["execution_result"]["metadata"]["stamp"] > capture or
        (records["contact_state"]["value"] == "SEATED" and
         records["contact_state"]["metadata"]["stamp"] > proof["physical"]["released_at"])):
        reason = "INVALID_COMPLETION_ORDER"
    if reason is None:
        reason = _world_conflict(result, proof["observation"])
        if reason:
            result["blocked_reason"] = reason
    if reason:
        result["decision"] = _decision(reason)
        return dict(state=result, accepted=False, reason=reason)
    context = {**records["vision_verdict"]["metadata"], "request_id":request_id,
               "source_epoch":human_source_epoch, "opened_at":now}
    for field in ("stamp", "sequence", "valid"):
        del context[field]
    result["human_verification"] = dict(context=context, deadline=now + timeout,
        max_age=response_max_age, type="PERCEPTUAL_VERIFICATION", status="OPEN", close_reason=None,
        target=deepcopy(result["target"]), reference=deepcopy(result["world"]["blocks"][0]),
        message="블록을 누르거나 옮기지 않고 기준 블록이 유지되고 목표 블록이 완전히 결착했는지 확인해주세요.",
        vision_metadata=deepcopy(records["vision_verdict"]["metadata"]), contact_value=records["contact_state"]["value"],
        response_sequence=None, response_stamp=None, verification=deepcopy(verification))
    result["decision"] = _decision("WAIT_HUMAN_RESPONSE")
    return dict(state=result, accepted=True, reason="HUMAN_VERIFY_OPENED")


def consume_human_response(trial, *, response, physical, session_closed, now):
    result = refresh_human_verification(trial, now)
    response = _object(response, ("metadata", "answer", "source", "inspection"), "response")
    if response["answer"] not in ("POSITIVE", "NEGATIVE", "UNKNOWN") or response["source"] != "HMI" or response["inspection"] not in ("VISUAL_ONLY", "PHYSICAL_CORRECTION"):
        raise ValueError("response: unsupported answer/source/inspection")
    request = result["human_verification"]
    if result["completion"] is not None or request is None or request["status"] != "OPEN":
        return dict(state=result, accepted=False, reason="NO_OPEN_HUMAN_REQUEST")
    meta = response["metadata"]
    guard = check_evidence_context(request["context"], meta, now=now,
        max_age=request["max_age"], last_sequence=request["response_sequence"])
    ordered = guard["accepted"]
    if guard["reason"] == "INVALID_EVIDENCE":
        ordered = check_evidence_context(request["context"], {**meta, "valid":True}, now=now,
            max_age=request["max_age"], last_sequence=request["response_sequence"])["accepted"]
    if ordered:
        if request["response_stamp"] is not None and meta["stamp"] < request["response_stamp"]:
            return dict(state=result, accepted=False, reason="OUT_OF_ORDER_STAMP")
        request["response_sequence"], request["response_stamp"] = meta["sequence"], meta["stamp"]
    if not guard["accepted"]:
        return dict(state=result, accepted=False, reason=guard["reason"])
    physical_guard = _physical_guard(result, physical, now)
    reason = None if physical_guard["accepted"] else physical_guard["reason"]
    reason = reason or _physical_ready(physical, session_closed, meta["stamp"])
    if reason:
        if physical_guard["accepted"]:
            close_human_verification(result, reason)
            result["decision"] = _decision(reason)
        return dict(state=result, accepted=False, reason=reason)
    request["response"] = deepcopy(response)
    return _accept_human_response(result, response, physical, now)


def _accept_human_response(result, response, physical, now):
    request = result["human_verification"]
    if response["inspection"] == "PHYSICAL_CORRECTION" or response["answer"] == "NEGATIVE":
        reason = "PHYSICAL_CORRECTION_REQUIRED" if response["inspection"] == "PHYSICAL_CORRECTION" else "HUMAN_NEGATIVE"
        result.update(blocked_reason=reason, decision=_decision(reason,
            "RECOVERY_REQUIRED" if reason == "HUMAN_NEGATIVE" else "HOLD"))
        close_human_verification(result, reason)
        return dict(state=result, accepted=True, reason=reason)
    if response["answer"] == "UNKNOWN":
        return dict(state=result, accepted=False, reason="HUMAN_RESPONSE_UNKNOWN")
    close_human_verification(result, "HUMAN_VERIFIED")
    context = request["context"]
    completion = {key:context[key] for key in IDENTITY + ("calibration_id", "basis_world_revision")}
    observed = dict(world_revision=result["world"]["world_revision"] + 1,
                    blocks=deepcopy(result["world"]["blocks"] + [result["target"]]))
    completion.update(observed_world_revision=observed["world_revision"], committed_at=now,
        verification_evidence="HUMAN_VERIFIED", evidence=deepcopy(result["collection"]["records"]),
        human_request=deepcopy(request), human_response=deepcopy(response), physical=deepcopy(physical))
    result.update(world=observed, completion=completion,
        decision=dict(decision="ASSEMBLED", reason="HUMAN_VERIFIED", verification_evidence="HUMAN_VERIFIED"))
    return dict(state=result, accepted=True, reason="HUMAN_VERIFIED")
