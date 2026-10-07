"""첫 2x2 연구 시험의 완료 조건. 순수 함수의 상태를 기존 Backend가 소유한다.

physical은 Controller가 확인한 사실이며 명령 ACK가 아니다. observation.complete는
제한된 시험 영역 전체의 관측 가능 여부다. 실측 임계값·보정·센서 생산자는 별도다.
"""

from copy import deepcopy
from math import isfinite

from app.assembly_attempt import IDENTITY, update_attempt_evidence
from app.assembly_evidence import check_evidence_context
from app.contracts import _integer, _object, validate_block
from app.current import _placements


def _decision(reason, decision="HOLD"):
    return dict(decision=decision, reason=reason, verification_evidence=None)


def _world(value):
    world = _object(value, ("world_revision", "blocks"), "world")
    _integer(world["world_revision"], 0, None, "world.world_revision")
    _placements(world["blocks"], "world.blocks", allow_duplicates=False)
    return deepcopy(world)


def prepare_assembly_trial(*, active, max_age, physical_context, physical_max_age,
                           world, target, now):
    collection = update_attempt_evidence(None, active, now=now, max_age=max_age)
    world, target = _world(world), validate_block(target)
    context = collection["state"]["active"]["execution_result"]
    if world["world_revision"] != context["basis_world_revision"]:
        raise ValueError("world: differs from frozen attempt basis")
    if len(world["blocks"]) != 1:
        raise ValueError("trial: requires exactly one fixed reference brick")
    reference = world["blocks"][0]
    if (reference["brick_type"], reference["layer"]) != ("2x2x1", 1):
        raise ValueError("trial: requires a layer-1 2x2 reference")
    if target != {**reference, "color":target["color"], "layer":2}:
        raise ValueError("trial: requires a 2x2 target directly over the reference")
    guard = check_evidence_context(physical_context,
        {**{k:v for k,v in physical_context.items() if k != "opened_at"},
         "stamp":now, "sequence":0, "valid":True},
        now=now, max_age=physical_max_age, last_sequence=None)
    if not guard["accepted"]:
        raise ValueError(f'physical_context: {guard["reason"]}')
    for key in IDENTITY + ("calibration_id", "basis_world_revision"):
        if physical_context[key] != context[key]:
            raise ValueError(f"physical_context.{key}: inconsistent attempt")
    return dict(collection=collection["state"], max_age=deepcopy(max_age),
                world=world, target=target, physical_context=deepcopy(physical_context),
                physical_max_age=physical_max_age, physical_sequence=None, physical_stamp=None,
                blocked_reason=None, completion=None, decision=collection["decision"], human_verification=None,
                recovery=dict(limits=None, started_at=None, baseline=None, reservations=[], restart_count=0, proposal=None),
                attempt_history=[], sensor_clock_id=None, sensor_snapshot=None)


def _physical_guard(trial, physical, now):
    fields = ("metadata", "stopped", "execution_ended", "released", "at_observe",
              "released_at", "observe_ready_at")
    physical = _object(physical, fields, "physical")
    for key in fields[1:5]:
        if physical[key] is not None and type(physical[key]) is not bool:
            raise ValueError(f"physical.{key}: expected boolean or null, not command ACK")
    for key in fields[5:]:
        value = physical[key]
        if value is not None and (type(value) not in (int, float) or not isfinite(value) or value < 0):
            raise ValueError(f"physical.{key}: expected finite nonnegative seconds or null")
    context, meta = trial["physical_context"], physical["metadata"]
    kwargs = dict(now=now, max_age=trial["physical_max_age"], last_sequence=trial["physical_sequence"])
    guard = check_evidence_context(context, meta, **kwargs)
    ordered = guard["accepted"]
    if guard["reason"] == "INVALID_EVIDENCE":
        ordered = check_evidence_context(context, {**meta, "valid":True}, **kwargs)["accepted"]
    if ordered:
        if trial["physical_stamp"] is not None and meta["stamp"] < trial["physical_stamp"]:
            return dict(accepted=False, reason="OUT_OF_ORDER_STAMP")
        trial["physical_sequence"], trial["physical_stamp"] = meta["sequence"], meta["stamp"]
    return guard


def _check_verification(trial, verification, now):
    proof = _object(verification, ("physical", "observation"), "verification")
    physical, observation = proof["physical"], proof["observation"]
    observation = _object(observation, ("metadata", "complete", "world"), "observation")
    if type(observation["complete"]) is not bool:
        raise ValueError("observation.complete: expected boolean")
    observed = _world(observation["world"])
    guard = _physical_guard(trial, physical, now)
    vision_guard = check_evidence_context(trial["collection"]["active"]["vision_verdict"],
        observation["metadata"], now=now, max_age=trial["max_age"]["vision_verdict"], last_sequence=None)
    return proof, observed, guard if not guard["accepted"] else vision_guard


def _completion_gate(trial, proof, observed, guard):
    physical, observation = proof["physical"], proof["observation"]
    if not guard["accepted"]:
        return _decision(guard["reason"]), None
    records = trial["collection"]["records"]
    if observation["metadata"] != records["vision_verdict"]["metadata"]:
        return _decision("VISION_FRAME_MISMATCH"), None
    if not all(physical[key] is True for key in ("stopped", "execution_ended", "released", "at_observe")):
        return _decision("WAIT_PHYSICAL_CONFIRMATION"), None
    released, ready = physical["released_at"], physical["observe_ready_at"]
    if released is None or ready is None:
        return _decision("WAIT_PHYSICAL_CONFIRMATION"), None
    capture = observation["metadata"]["stamp"]
    if not (records["contact_state"]["metadata"]["stamp"] <= released <= ready <= capture
            and capture <= physical["metadata"]["stamp"]
            and records["execution_result"]["metadata"]["stamp"] <= capture):
        return _decision("INVALID_COMPLETION_ORDER"), None
    if not observation["complete"]:
        return _decision("PARTIAL_OBSERVATION", "REQUEST_HUMAN_VERIFICATION"), None
    reference, target = trial["world"]["blocks"][0], trial["target"]
    reason = None
    if reference not in observed["blocks"]:
        reason = "REFERENCE_CHANGED"
    elif target not in observed["blocks"]:
        reason = "TARGET_NOT_ASSEMBLED"
    elif len(observed["blocks"]) != 2:
        reason = "UNEXPECTED_WORLD_EFFECT"
    elif observed["world_revision"] != trial["world"]["world_revision"] + 1:
        reason = "WORLD_REVISION_MISMATCH"
    if reason:
        trial["blocked_reason"] = reason
        return _decision(reason, "RECOVERY_REQUIRED" if reason == "TARGET_NOT_ASSEMBLED" else "HOLD"), None
    return dict(decision="ASSEMBLED", reason="COMPLETION_VERIFIED", verification_evidence="SENSOR_VERIFIED"), observed


def advance_assembly_trial(trial, *, now, event=None, verification=None):
    """Backend 전용 계산. 반환 후보의 world+completion은 Owner가 한 번에 채택한다.

    verification은 완료 후보와 함께 있을 때만 완료 근거다. 먼저 온 proof도 문맥/순번을
    검사하되 자동 재사용하지 않는다. 재제출에는 새 Controller 순번이 필요하다.
    상태는 디스크 복원 형식이 아니다.
    """
    result = deepcopy(trial)
    collection = update_attempt_evidence(result["collection"], result["collection"]["active"],
        now=now, max_age=result["max_age"], event=event)
    result.update(collection=collection["state"], decision=collection["decision"])
    checked = _check_verification(result, verification, now) if verification is not None else None
    if result["blocked_reason"] and result["decision"]["decision"] != "SAFE_STOP":
        reason = result["blocked_reason"]
        result["decision"] = _decision(reason, "RECOVERY_REQUIRED" if reason in ("TARGET_NOT_ASSEMBLED", "HUMAN_NEGATIVE") else "HOLD")
    if result["decision"]["decision"] != "ASSEMBLED":
        return result
    result["decision"] = _decision("WAIT_COMPLETION_VERIFICATION")
    if checked is None:
        return result
    result["decision"], observed = _completion_gate(result, *checked)
    if observed is not None:
        context = result["collection"]["active"]["execution_result"]
        completion = {key:context[key] for key in IDENTITY + ("calibration_id", "basis_world_revision")}
        completion.update(observed_world_revision=observed["world_revision"], committed_at=now,
                          verification_evidence="SENSOR_VERIFIED",
                          evidence=deepcopy(result["collection"]["records"]), verification=deepcopy(verification))
        result.update(world=observed, completion=completion)
    return result
