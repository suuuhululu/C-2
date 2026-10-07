"""첫 단일 블록 시험의 복구 제안·재개 검사. 실행 명령이나 안전 리셋은 없다."""

from copy import deepcopy
from math import isfinite

from app.assembly_attempt import IDENTITY
from app.assembly_completion import _physical_guard, _world, prepare_assembly_trial
from app.assembly_evidence import check_evidence_context
from app.assembly_human import close_human_verification
from app.contracts import _integer, _object, _text
from app.current import _key


ACTIONS = ("RETRACT", "RE_OBSERVE", "MICRO_SEARCH", "RE_APPROACH")
FLAGS = ("retract_permitted", "search_permitted", "approach_permitted",
         "dependencies_ready", "motion_plan_valid", "support_ready")
CHECKPOINT = ("physical", "session_closed", "grasp_state", *FLAGS, "new_observation", "plan_binding")


def _plan_binding(context, parameters, checkpoint):
    fields = IDENTITY + ("calibration_id", "basis_world_revision")
    binding = _object(checkpoint["plan_binding"], fields + ("parameters",), "plan_binding")
    for field in fields[:-1]:
        _text(binding[field], f"plan_binding.{field}")
    _integer(binding["basis_world_revision"], 0, None, "plan_binding.basis_world_revision")
    approved = _parameters(binding["parameters"])
    if any(binding[field] != context[field] for field in fields) or approved != parameters:
        return "PLAN_CONTEXT_OR_PARAMETERS_MISMATCH"
    return None


def _parameters(value):
    value = _object(value, ("offset_m", "search_radius_m"), "parameters")
    offset = value["offset_m"]
    if not isinstance(offset, list) or len(offset) != 3:
        raise ValueError("parameters.offset_m: expected xyz metres")
    for number in (*offset, value["search_radius_m"]):
        if type(number) not in (int, float) or not isfinite(number):
            raise ValueError("parameters: expected finite SI numbers")
    if value["search_radius_m"] < 0:
        raise ValueError("parameters.search_radius_m: expected nonnegative metres")
    return deepcopy(value)


def _checkpoint(trial, value, now):
    value = _object(value, CHECKPOINT, "checkpoint")
    for field in FLAGS:
        if value[field] is not None and type(value[field]) is not bool:
            raise ValueError(f"checkpoint.{field}: expected boolean or null")
    for field in ("session_closed", "new_observation"):
        if type(value[field]) is not bool:
            raise ValueError(f"checkpoint.{field}: expected boolean")
    if value["grasp_state"] not in ("HOLDING", "RELEASED", "UNKNOWN"):
        raise ValueError("checkpoint.grasp_state: unsupported state")
    guard = _physical_guard(trial, value["physical"], now)
    if not guard["accepted"]:
        return guard["reason"]
    if not all(value["physical"][field] is True for field in ("stopped", "execution_ended")):
        return "WAIT_STOP_AND_EXECUTION_END"
    if not value["session_closed"]:
        return "SUPPORT_SESSION_NOT_CLOSED"
    if value["grasp_state"] == "HOLDING" and value["physical"]["released"] is not False:
        return "GRASP_EVIDENCE_CONFLICT"
    if value["grasp_state"] == "RELEASED" and value["physical"]["released"] is not True:
        return "GRASP_EVIDENCE_CONFLICT"
    return None


def _budget(trial, limits, now):
    limits = _object(limits, ("max_actions", "max_elapsed_s"), "limits")
    _integer(limits["max_actions"], 1, None, "limits.max_actions")
    seconds = limits["max_elapsed_s"]
    if type(seconds) not in (int, float) or not isfinite(seconds) or seconds <= 0:
        raise ValueError("limits.max_elapsed_s: expected positive finite seconds")
    recovery = trial["recovery"]
    if recovery["limits"] is None:
        recovery.update(limits=deepcopy(limits), started_at=now)
    if recovery["limits"] != limits:
        return "RECOVERY_PROFILE_CHANGED"
    if now < recovery["started_at"]:
        return "CLOCK_RESET"
    if now - recovery["started_at"] >= seconds:
        return "RECOVERY_TIME_BUDGET_EXHAUSTED"
    if len(recovery["reservations"]) + recovery["restart_count"] >= limits["max_actions"]:
        return "RECOVERY_ACTION_BUDGET_EXHAUSTED"
    return None


def _signature(world, parameters, grasp):
    # Revision/ID/시각 증가와 배열 순서 변경은 실제 기하·실행 조건의 변화가 아니다.
    return dict(blocks=sorted(_key(block) for block in world["blocks"]),
                parameters=deepcopy(parameters), grasp_state=grasp)


def _blocked(trial):
    if trial["decision"]["decision"] == "SAFE_STOP" or trial["collection"]["latched"]["motion_permitted"] is False:
        return "SAFE_STOP", "SAFETY_RESET_REQUIRED"
    if trial["collection"]["blocked_reason"]:
        return "HOLD", trial["collection"]["blocked_reason"]
    if trial["blocked_reason"] and trial["blocked_reason"].startswith("LOG_FAILED"):
        return "HOLD", trial["blocked_reason"]
    safety = trial["collection"]["records"]["motion_permitted"]
    if safety is None or safety["value"] is not True:
        return "HOLD", "SAFETY_UNKNOWN"
    if trial["completion"] is not None:
        return "HOLD", "ALREADY_COMMITTED"
    return None


def _action_reason(trial, action, cp, signature):
    reason = trial["blocked_reason"] or trial["decision"]["reason"]
    if reason in ("PHYSICAL_CORRECTION_REQUIRED", "REFERENCE_CHANGED", "UNEXPECTED_WORLD_EFFECT",
                  "WORLD_REVISION_MISMATCH", "EXECUTION_FAILED", "EXECUTION_TIMED_OUT"):
        return "HUMAN_ASSISTANCE_REQUIRED", reason
    if action != "RE_OBSERVE" and cp["grasp_state"] != "HOLDING":
        return "HUMAN_ASSISTANCE_REQUIRED", "REGRASP_REQUIRED"
    if action in ("RETRACT", "MICRO_SEARCH") and reason != "JAMMED":
        return "HOLD", "ACTION_NOT_APPLICABLE_TO_FAILURE"
    required = {"RETRACT":("retract_permitted",), "RE_OBSERVE":(), "MICRO_SEARCH":("search_permitted",),
                "RE_APPROACH":("approach_permitted", "dependencies_ready", "motion_plan_valid", "support_ready")}[action]
    if any(cp[field] is not True for field in required):
        return "HOLD", "RECOVERY_PRECONDITION_UNKNOWN_OR_FALSE"
    if action == "RE_APPROACH":
        baseline = trial["recovery"]["baseline"]
        if baseline is None or not cp["new_observation"] or signature == baseline:
            return "HUMAN_ASSISTANCE_REQUIRED", "NO_MEANINGFUL_CHANGE"
    return None


def _new_context_reason(trial, active):
    previous = [trial["collection"]["active"]] + [item["collection"]["active"] for item in trial["attempt_history"]]
    new, old = active["execution_result"], previous[0]["execution_result"]
    if any(new["attempt_id"] == item["execution_result"]["attempt_id"] for item in previous):
        return "NEW_ATTEMPT_REQUIRED"
    if any(new[field] != old[field] for field in IDENTITY[:-1]):
        return "LOGICAL_STEP_CHANGED"
    if any(active[source]["request_id"] is None or any(active[source]["request_id"] == item[source]["request_id"]
           for item in previous) for source in ("execution_result", "vision_verdict")):
        return "NEW_EXECUTION_AND_VISION_REQUEST_REQUIRED"
    cutoff = trial["recovery"]["started_at"]
    human = trial["human_verification"]
    if human is not None and "response" in human:
        cutoff = max(cutoff, human["response"]["metadata"]["stamp"])
    if any(context["opened_at"] < cutoff for context in active.values()):
        return "NEW_ATTEMPT_WINDOW_REQUIRED"
    return None


def propose_recovery(trial, *, action, parameters, limits, checkpoint, now):
    if action not in ACTIONS:
        raise ValueError("action: only four bounded recovery actions are supported")
    result, parameters = deepcopy(trial), _parameters(parameters)
    budget_reason = _budget(result, limits, now)
    cp_reason = _checkpoint(result, checkpoint, now)
    cp_reason = cp_reason or _plan_binding(result["collection"]["active"]["execution_result"], parameters, checkpoint)
    signature = _signature(result["world"], parameters, checkpoint["grasp_state"])
    recovery = result["recovery"]
    blocked = _blocked(result)
    failure = result["blocked_reason"] or result["decision"]["reason"]
    applicable = result["decision"]["decision"] in ("RECOVERY_REQUIRED", "REQUEST_HUMAN_VERIFICATION") or result["blocked_reason"]
    issue = blocked or (("HOLD", cp_reason) if cp_reason else None) or (("HUMAN_ASSISTANCE_REQUIRED", budget_reason) if budget_reason else None)
    if issue is None and not applicable:
        issue = ("HOLD", "RECOVERY_NOT_APPLICABLE")
    if issue is None:
        issue = _action_reason(result, action, checkpoint, signature)
    if issue is None and any(item["failure"] == failure and item["action"] == action and item["signature"] == signature for item in recovery["reservations"]):
        issue = ("HUMAN_ASSISTANCE_REQUIRED", "NO_MEANINGFUL_CHANGE")
    if recovery["baseline"] is None and cp_reason is None:
        recovery["baseline"] = deepcopy(signature)
    status, reason = issue or ("PROPOSED", "GUARDS_PASSED_NOT_EXECUTED")
    proposal = dict(status=status, reason=reason, action=action if status == "PROPOSED" else None)
    recovery["proposal"] = proposal
    if status == "PROPOSED":
        recovery["reservations"].append(dict(failure=failure, action=action, signature=signature, proposed_at=now))
        close_human_verification(result, "RECOVERY_PROPOSED")
    return dict(state=result, accepted=status == "PROPOSED", reason=reason, proposal=deepcopy(proposal))


def check_resume(trial, *, active, max_age, physical_context, physical_max_age,
                 world, target, observation, parameters, limits, checkpoint, now):
    result, parameters = deepcopy(trial), _parameters(parameters)
    budget_reason = _budget(result, limits, now)
    cp_reason = _checkpoint(result, checkpoint, now)
    blocked = _blocked(result)
    reason = blocked[1] if blocked else cp_reason or budget_reason
    if reason:
        return dict(state=result, accepted=False, reason=reason)
    if result["decision"]["decision"] not in ("RECOVERY_REQUIRED", "REQUEST_HUMAN_VERIFICATION") and not result["blocked_reason"]:
        return dict(state=result, accepted=False, reason="RESUME_NOT_APPLICABLE")
    prepared = prepare_assembly_trial(active=active, max_age=max_age, physical_context=physical_context,
        physical_max_age=physical_max_age, world=world, target=target, now=now)
    new = prepared["collection"]["active"]["execution_result"]
    reason = _plan_binding(new, parameters, checkpoint) or _new_context_reason(result, active)
    if reason is None and (checkpoint["grasp_state"] != "HOLDING" or not checkpoint["new_observation"] or any(checkpoint[field] is not True for field in ("approach_permitted", "dependencies_ready", "motion_plan_valid", "support_ready"))):
        reason = "RESUME_PRECONDITION_UNKNOWN_OR_FALSE"
    observation = _object(observation, ("metadata", "complete", "world"), "observation")
    if type(observation["complete"]) is not bool:
        raise ValueError("observation.complete: expected boolean")
    observed = _world(observation["world"])
    guard = check_evidence_context(active["vision_verdict"], observation["metadata"], now=now,
                                   max_age=max_age["vision_verdict"], last_sequence=None)
    if reason is None and not guard["accepted"]:
        reason = guard["reason"]
    if reason is None and observation["metadata"]["stamp"] < checkpoint["physical"]["metadata"]["stamp"]:
        reason = "REOBSERVATION_BEFORE_CHECKPOINT"
    if reason is None and not observation["complete"]:
        reason = "REOBSERVATION_INCOMPLETE"
    if reason is None and target in observed["blocks"]:
        reason = "POST_CORRECTION_VERIFICATION_REQUIRED"
    if reason is None and observed != world:
        reason = "OBSERVED_WORLD_MISMATCH"
    signature = _signature(world, parameters, checkpoint["grasp_state"])
    if reason is None and (result["recovery"]["baseline"] is None or signature == result["recovery"]["baseline"]):
        reason = "NO_MEANINGFUL_CHANGE"
    if reason:
        return dict(state=result, accepted=False, reason=reason)
    close_human_verification(result, "NEW_ATTEMPT_OPENED")
    archive = {key:deepcopy(value) for key,value in result.items() if key != "attempt_history"}
    prepared["attempt_history"] = deepcopy(result["attempt_history"]) + [archive]
    prepared["recovery"] = deepcopy(result["recovery"])
    prepared["recovery"]["restart_count"] += 1
    prepared["recovery"]["baseline"] = signature
    return dict(state=prepared, accepted=True, reason="RESUME_CHECK_PASSED_NO_MOTION")
