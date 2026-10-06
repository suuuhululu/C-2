"""C 응답과 실제 A 함수를 기존 Backend 요청에 연결한다. 장치는 호출하지 않는다."""

from copy import deepcopy

from planning_trial.planner import plan_from_current

from app.contracts import _integer, _object


def on_initial_design(backend, request_id: str, response: object) -> bool:
    state, request = backend._state, backend._state["planning_request"]
    if request is None or request_id != request["request_id"] or state["workflow_status"] != "PREPARING":
        return backend._ignored(request_id)
    if "design" in request:
        return backend._ignored(request_id)
    try:
        if not isinstance(response, dict) or response.get("status") != "OK":
            raise ValueError(f"C Initial did not succeed: {response}")
        if response.get("hri_result") is not None:
            raise ValueError("Initial response cannot contain an intervention decision")
        design = _object(response.get("design"), ("design_version", "blocks"), "c.design")
        _integer(design["design_version"], 1, 1, "c.initial.design_version")
        # 개별 블록의 제약 위반은 A의 INVALID 결과로 진단을 보존한다.
    except ValueError as error:
        return backend.on_failure("planner", request_id, str(error))
    if request["base_current_revision"] != state["current"]["current_revision"]:
        return backend.on_failure("planner", request_id, "Current changed before Initial Design was received")
    request["design"] = deepcopy(design)
    if not backend._event("INITIAL_DESIGN_RECEIVED", request_id=request_id, result=response):
        return True
    backend._send("planner", dict(**request, current=state["current"], supported_scope=state["supported_scope"]))
    return True


def run_planning_request(backend, payload: dict, *, planner=plan_from_current) -> bool:
    """emit의 planner 경로에서 호출한다. request_id는 호출 당시 값을 그대로 사용한다."""
    request = backend._state["planning_request"]
    identity = payload["request_id"]
    if request is None or identity != request["request_id"]:
        return backend._ignored(identity)
    if "design" not in payload:
        raise ValueError("Planner requires the successful C Design; do not substitute a sample")
    result = planner(deepcopy(payload["design"]), deepcopy(payload["current"]))
    return backend.on_plan_result(identity, result)


def current_blocks_for_c(payload: dict) -> list[dict]:
    """C run_intervention에는 목록, A에는 같은 Current 전체를 전달한다. revision은 D가 보관한다."""
    return deepcopy(payload["current"]["blocks"])


def on_c_intervention(backend, request_id: str, response: object) -> bool:
    request = backend._state["question_request"]
    if request is None or request_id != request["request_id"]:
        return backend._ignored(request_id)
    if not isinstance(response, dict) or response.get("status") != "OK":
        return backend.on_failure("hri", request_id, f"C intervention did not succeed: {response}")
    decision = response.get("hri_result")
    value = dict(request_id=request_id, decision=decision)
    if decision == "REVISE":
        value["design"] = response.get("design")
    elif decision == "UNCLEAR":
        questions = response.get("questions")
        if not isinstance(questions, list) or not questions:
            return backend.on_failure("hri", request_id, "C UNCLEAR response requires a question")
        value["question"] = questions[-1]
    if not backend._event("C_INTERVENTION_RESULT", request_id=request_id, result=response):
        return True
    return backend.on_intent(value)
