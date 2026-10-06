"""의도/재계획/사람 정리의 Backend 분기. C/A 알고리즘은 호출 결과로만 받는다."""

from copy import deepcopy
from uuid import uuid4

from app.contracts import _object, _text, validate_design, validate_observed, validate_plan_result
from app.current import _key, _placements, adopt_observation, open_observation_check
from app.completion import _difference, calculate_expected


def same_layout(left: dict, right: dict) -> bool:
    return {_key(block) for block in left["blocks"]} == {_key(block) for block in right["blocks"]}


def begin_replan(backend, design):
    state = backend._state
    request = dict(request_id=str(uuid4()),job_id=state["job_id"],design_version=design["design_version"],
                   base_current_revision=state["current"]["current_revision"],design=deepcopy(design))
    state.update(workflow_status="REPLANNING",planning_request=request,pending_design=deepcopy(design),
                 question_request=None,choice_required=False,correction_request=None,active_check=None,
                 place_check=None,current_check=None,place_status=None,reason=None,planner_errors=[])
    backend._awaiting_assembly = backend._delivery_goal = False
    backend._send("planner",dict(**request,current=state["current"],supported_scope=state["supported_scope"]))
    if state["workflow_status"] == "REPLANNING":
        open_current_check(backend,"REPLAN")


def open_current_check(backend, purpose):
    state = backend._state
    if not backend._at_observe or state["execution_id"] or state["stop_request"] or state["fault"]:
        backend._hold("OBSERVE_POINT_NOT_READY")
        return
    step = backend._next_step()
    context = state["context"]
    check = open_observation_check(str(uuid4()),state["job_id"],context["plan"]["plan_id"] if context else None,
                                    (step["step_id"] if step else "FINAL") if context else None)
    state.update(current_check=check,current_check_purpose=purpose)
    backend._send("vision",dict(check_id=check["check_id"],after=None))


def on_intent(backend, value):
    if not isinstance(value,dict):
        raise ValueError("intent: expected object")
    state, request = backend._state,backend._state["question_request"]
    if (request is None or state["workflow_status"] != "WAIT_INTENT" or
            value.get("request_id") != request["request_id"]):
        return backend._ignored(value.get("request_id"))
    if (request["current_revision"] != state["current"]["current_revision"] or
            request["design_version"] != state["context"]["design"]["design_version"]):
        return backend._ignored(request["request_id"])
    decision = value.get("decision")
    if decision == "UNCLEAR" and state["choice_required"]:
        return backend._ignored(request["request_id"])
    try:
        extra = ("design",) if decision == "REVISE" else ("question",) if decision == "UNCLEAR" else ()
        _object(value,("request_id","decision")+extra,"intent")
        if decision not in ("KEEP","REVISE","UNCLEAR"):
            raise ValueError("intent.decision: unsupported decision")
        design = state["context"]["design"]
        if decision == "REVISE":
            candidate = validate_design(value["design"])
            _placements(candidate["blocks"],"intent.design.blocks",allow_duplicates=False)
            changed = not same_layout(candidate,design)
            if candidate["design_version"] != design["design_version"]+int(changed):
                raise ValueError("intent.design_version: must reflect actual whole Design change")
            design = candidate
        if decision == "UNCLEAR":
            _text(value["question"],"intent.question")
    except ValueError as error:
        backend._hold(f"HRI_INVALID: {error}")
        return True
    if not backend._event("INTENT_RECEIVED",request_id=request["request_id"],result=value):
        return True
    if decision == "UNCLEAR":
        state["unclear_count"] += 1
        state.update(question=value["question"],choice_required=state["unclear_count"]>=2)
        if not state["choice_required"]:
            # 새 안내 질문의 답변을 이전 질문 결과와 구분한다. LLM 자동 재호출은 없다.
            state["question_request"] = {**request,"request_id":str(uuid4())}
            backend._event("QUESTION_OPENED",request_id=state["question_request"]["request_id"],result=value["question"])
    else:
        begin_replan(backend,design)
    return True


def request_correction(backend, reason, conflicts):
    state = backend._state
    state.update(workflow_status="WAIT_CORRECTION",planning_request=None,current_check=None,
                 correction_required=True,correction_reason=reason,correction_conflicts=deepcopy(conflicts),
                 correction_request=dict(request_id=str(uuid4())),reason=reason)
    backend._event("CORRECTION_REQUIRED",request_id=state["correction_request"]["request_id"],
                   result=conflicts,reason=reason)


def on_plan_result(backend, request_id, value, *, design=None):
    state, request = backend._state,backend._state["planning_request"]
    if request is None or request_id != request["request_id"] or state["workflow_status"] not in ("PREPARING", "REPLANNING"):
        return backend._ignored(request_id)
    if "ready_result" in request:
        return backend._ignored(request_id)
    try:
        result = validate_plan_result(value)
        candidate = request.get("design") if result["status"] != "INVALID" else None
        if design is not None and result["status"] != "INVALID":
            received = validate_design(design)
            if candidate is not None and received != candidate:
                raise ValueError("Design differs from pending candidate")
            candidate = received
        if candidate is not None and candidate["design_version"] != request["design_version"]:
            raise ValueError("Design differs from active request version")
        if result["status"] in ("READY", "NEEDS_CORRECTION") and candidate is None:
            raise ValueError("Initial result requires the Design used for planning")
    except ValueError as error:
        backend._hold(f"PLAN_INVALID: {error}")
        return True
    if not backend._event("PLAN_RESULT",request_id=request_id,result=result):
        return True
    state["planner_errors"] = deepcopy(result["errors"])
    if candidate is not None:
        state["pending_design"] = deepcopy(candidate)
    if result["status"] == "READY":
        return backend.on_plan(request_id,candidate,result["plan"])
    reason = result["errors"][0]["reason"]
    if result["status"] == "NEEDS_CORRECTION":
        conflicts = [error["block"] for error in result["errors"] if error["block"] is not None]
        request_correction(backend,reason,conflicts)
    else:
        backend._hold(f"PLAN_INVALID: {reason}")
    return True


def exception_command(backend, command):
    state = backend._state
    name = command["command"]
    if name == "CHOOSE_INTENT":
        request = state["question_request"]
        if (state["workflow_status"] != "WAIT_INTENT" or not state["choice_required"] or
                request is None or command["request_id"] != request["request_id"]):
            return dict(accepted=False,reason="NO_ACTIVE_CHOICE")
        if command["choice"] == "KEEP":
            on_intent(backend,dict(request_id=request["request_id"],decision="KEEP"))
        else:
            # 명시적 수정 선택도 전체 Design 생성은 C에게 맡긴다.
            state.update(choice_required=False,question_request={**request,"request_id":str(uuid4())})
            backend._send("hri",dict(**state["question_request"],choice="REVISE",
                design=state["context"]["design"],current=state["current"],difference=state["difference"],
                supported_scope=state["supported_scope"]))
        return dict(accepted=True,reason=state["reason"])
    if name == "CONTINUE_AFTER_CORRECTION":
        request = state["correction_request"]
        if (state["workflow_status"] != "WAIT_CORRECTION" or request is None or
                command["request_id"] != request["request_id"]):
            return dict(accepted=False,reason="NO_ACTIVE_CORRECTION")
        state.update(correction_request=None,workflow_status="HOLD",reason="WAIT_CORRECTION_OBSERVATION")
        open_current_check(backend,"CORRECTION")
        return dict(accepted=True,reason=state["reason"])
    return dict(accepted=False,reason="CONTROLLER_NOT_CONNECTED")


def on_current_observation(backend, value):
    observation = validate_observed(value)
    state = backend._state
    if not backend._at_observe or state["current_check"] is None or state["stop_request"]:
        return backend._ignored(observation["check_id"])
    result = adopt_observation(state["current"],state["current_check"],observation)
    if result["disposition"] == "IGNORED":
        return backend._ignored(observation["check_id"])
    previous_reason = state["reason"]
    state.update(current=result["current"],current_check=result["active_check"],last_observation=observation,
                 step_observation=observation if backend._next_step() else None)
    if result["disposition"] == "ADOPTED":
        if not backend._event("CURRENT_ADOPTED",request_id=observation["check_id"],
                              result=dict(current=state["current"],observed=observation)):
            return True
    if result["disposition"] == "HOLD":
        state["reason"] = result["reason"]
        state["current_check_blocked"] = True
        state["comparison"] = "UNOBSERVABLE"
        if previous_reason != state["reason"]:
            backend._event("OBSERVATION_HOLD",request_id=observation["check_id"],reason=state["reason"])
        return True
    state["current_check_blocked"] = False
    purpose = state["current_check_purpose"]
    if observation["status"] == "OK" and state["comparison"] == "UNOBSERVABLE":
        state["comparison"] = "WAITING"
    if purpose == "CORRECTION":
        if result["disposition"] != "ADOPTED":
            request_correction(backend,"정리 후 실제 배치 변화가 확인되지 않았습니다.",state["correction_conflicts"])
        else:
            state["correction_required"] = False
            begin_replan(backend,state["pending_design"])
    elif result["disposition"] == "ADOPTED":
        if purpose == "REPLAN":
            begin_replan(backend,state["pending_design"])
        else:
            state["difference"] = _difference(calculate_expected(state["context"])["blocks"],state["current"]["blocks"])
            state["workflow_status"] = "WAIT_INTENT"
            backend._request_question()
    elif purpose == "REPLAN" and state["planning_request"] and "ready_result" in state["planning_request"]:
        request = state["planning_request"]
        ready = request["ready_result"]
        backend.on_plan(request["request_id"],ready["design"],ready["plan"])
    return True
