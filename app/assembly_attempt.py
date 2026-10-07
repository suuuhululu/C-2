"""한 attempt의 증거 수집→문맥/만료 검사→판정 후보. 상태 Owner는 호출하는 SM다.

장치 명령·완료 commit·정지/해제/기하 확인은 수행하지 않는다. same-clock now와
source별 검증된 max_age를 받아 매 호출마다 저장된 증거도 재검사한다.
latched는 이미 확인한 실패/정지를 같은 attempt의 늦은 성공으로 덮지 않기 위한
기록이며 센서 최신값이 아니다. 새로운 attempt도 장치 safety reset을 수행하지 않는다.
"""

from copy import deepcopy
from math import isfinite

from app.assembly_evidence import check_evidence_context, evaluate_assembly_evidence
from app.contracts import _integer, _object, _text


SOURCES = ("execution_result", "contact_state", "vision_verdict", "motion_permitted")
IDENTITY = ("job_id", "plan_id", "step_id", "attempt_id")
CONTEXT = IDENTITY + ("request_id", "calibration_id", "source_epoch", "basis_world_revision", "opened_at")
STATE_FIELDS = ("active", "records", "seen_sequence", "seen_stamp", "latched", "blocked_reason", "evaluated_at")


def _prepare_attempt(state, active, now, max_age):
    active, max_age = _object(active, SOURCES, "active"), _object(max_age, SOURCES, "max_age")
    for source in SOURCES:
        context = _object(active[source], CONTEXT, f"active.{source}")
        for field in CONTEXT[:-2]:
            if field != "request_id" or context[field] is not None:
                _text(context[field], f"active.{source}.{field}")
        if source == "vision_verdict":
            _text(context["request_id"], "active.vision_verdict.request_id")
        _integer(context["basis_world_revision"], 0, None, "basis_world_revision")
        for field, value in (("now", now), ("opened_at", context["opened_at"]), ("max_age", max_age[source])):
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError(f"{field}: expected finite nonnegative seconds")
        if max_age[source] == 0:
            raise ValueError("max_age: expected positive seconds for every source")
        for field in IDENTITY + ("calibration_id", "basis_world_revision"):
            if context[field] != active[SOURCES[0]][field]:
                raise ValueError(f"active.{source}.{field}: inconsistent attempt context")
    if state is not None:
        _object(state, STATE_FIELDS, "state")
        _object(state["active"], SOURCES, "state.active")
    if state is None or any(state["active"][SOURCES[0]][key] != active[SOURCES[0]][key] for key in IDENTITY):
        empty = dict.fromkeys(SOURCES)
        return dict(active=deepcopy(active), records=dict(empty), seen_sequence=dict(empty),
                    seen_stamp=dict(empty), latched=dict(empty), blocked_reason=None, evaluated_at=now)
    result = deepcopy(state)
    for field in ("records", "seen_sequence", "seen_stamp", "latched"):
        _object(result[field], SOURCES, f"state.{field}")
    if now < result["evaluated_at"]:
        result["blocked_reason"] = "CLOCK_RESET"
    for source in SOURCES:
        old, new = result["active"][source], active[source]
        if any(old[key] != new[key] for key in ("calibration_id", "basis_world_revision")):
            result["blocked_reason"] = "ATTEMPT_CONTEXT_CHANGED"
        if old != new:
            if (old["request_id"], old["source_epoch"]) == (new["request_id"], new["source_epoch"]) and old["opened_at"] != new["opened_at"]:
                raise ValueError("opened_at: frozen window requires a new request or source_epoch")
            for field in ("records", "seen_sequence", "seen_stamp"):
                result[field][source] = None
    if result["blocked_reason"]:
        result["records"] = dict.fromkeys(SOURCES)
    result.update(active=deepcopy(active), evaluated_at=now)
    return result


def _consume_evidence(state, event, now, max_age):
    event = _object(event, ("source", "metadata", "value"), "event")
    source = event["source"]
    if not isinstance(source, str) or source not in SOURCES:
        raise ValueError("event.source: unsupported evidence source")
    # 기존 조합 함수의 값 계약을 재사용하되 여기서는 판정 결과를 채택하지 않는다.
    evaluate_assembly_evidence(**{**dict.fromkeys(SOURCES), source: event["value"]})
    guard = check_evidence_context(state["active"][source], event["metadata"], now=now,
                                   max_age=max_age[source], last_sequence=state["seen_sequence"][source])
    if state["blocked_reason"]:
        return dict(accepted=False, reason=state["blocked_reason"])
    ordered = guard["accepted"]
    if guard["reason"] == "INVALID_EVIDENCE":
        # 새 invalid 샘플도 순서/시각이 유효하면 이전 성공을 무효화한다. 성공으로 채택하지 않는다.
        ordered = check_evidence_context(state["active"][source], {**event["metadata"], "valid": True},
                    now=now, max_age=max_age[source], last_sequence=state["seen_sequence"][source])["accepted"]
    if not ordered:
        return guard
    stamp = event["metadata"]["stamp"]
    if state["seen_stamp"][source] is not None and stamp < state["seen_stamp"][source]:
        return dict(accepted=False, reason="OUT_OF_ORDER_STAMP")
    state["seen_sequence"][source], state["seen_stamp"][source] = event["metadata"]["sequence"], stamp
    state["records"][source] = deepcopy(event) if guard["accepted"] else None
    negative = ((source == "execution_result" and event["value"] in ("FAILED", "TIMED_OUT", "CANCELED")) or
                (source == "contact_state" and event["value"] == "JAMMED") or
                (source == "vision_verdict" and event["value"] == "FAIL") or
                (source == "motion_permitted" and event["value"] is False))
    previous = state["latched"][source]
    if guard["accepted"] and negative and (previous is None or previous == "CANCELED"):
        state["latched"][source] = event["value"]
    return guard


def update_attempt_evidence(state: object, active: object, *, now: float,
                             max_age: object, event: object = None) -> dict:
    """SM가 반환 state를 보관한다. event=None인 주기 재평가도 만료를 제거한다.

    source/request별 창·epoch가 바뀌면 해당 캐시와 순번을 비운다. 같은 attempt에서
    보정/기준 구조가 바뀌거나 시계가 역행하면 새 attempt까지 완료 판단을 보류한다.
    새 시도의 fresh 안전/실행/접촉/Vision 증거를 모두 모아야 완료 후보가 생긴다.
    SM는 실제 reference·정지·해제·관측 조건을 별도로 확인한 뒤만 commit할 수 있다.
    """
    result = _prepare_attempt(state, active, now, max_age)
    event_result = _consume_evidence(result, event, now, max_age) if event is not None else None
    values, discarded = dict.fromkeys(SOURCES), {}
    for source, record in result["records"].items():
        if record is not None:
            guard = check_evidence_context(active[source], record["metadata"], now=now,
                                           max_age=max_age[source], last_sequence=None)
            if guard["accepted"]:
                values[source] = record["value"]
            else:
                result["records"][source] = None
                discarded[source] = guard["reason"]
        if result["latched"][source] is not None:
            values[source] = result["latched"][source]
    decision = evaluate_assembly_evidence(**values)
    if result["blocked_reason"] and decision["decision"] != "SAFE_STOP":
        decision = dict(decision="HOLD", reason=result["blocked_reason"], verification_evidence=None)
    return dict(state=result, decision=decision, event_result=event_result, discarded=discarded)
