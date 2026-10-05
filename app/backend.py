"""명시적인 FAKE 모드의 Backend 흐름. emit은 비동기 요청을 전달하는 연결부다."""

from copy import deepcopy
from uuid import uuid4

from app.completion import evaluate_job_completion, evaluate_observation, freeze_plan_basis
from app.contracts import _integer, _object, _text, validate_observed
from app.current import open_observation_check
from app.hmi_contracts import validate_hmi_command
from app import replan


class Backend:
    def __init__(self, emit, *, mode: str, record=None):
        if mode != "FAKE":
            raise ValueError("Backend: explicit FAKE mode required")
        self._emit = emit
        self._record = record
        self._request_owners = {}
        self._state = dict(mode=mode, supported_scope=dict(operations=["PLACE"],
                           brick_types=["2x2x1","2x3x1"],colors=["yellow","blue"],
                           board_width=24,board_height=24,max_layer=4),workflow_status="IDLE", job_id=None,
                           current=dict(current_revision=0, blocks=[]), context=None,
                           planning_request=None, execution_id=None, active_check=None,
                           place_check=None, place_status=None, question_request=None, question=None,
                           stop_request=None, reason=None, fault=None, comparison="WAITING", difference=None,
                           last_observation=None, step_observation=None, pending_design=None,
                           current_check=None,current_check_purpose=None,current_check_blocked=False,
                           choice_required=False,unclear_count=0,
                           correction_request=None,correction_required=False,correction_reason=None,
                           correction_conflicts=[])
        self._ready = self._at_observe = self._awaiting_assembly = self._delivery_goal = False
        self._place_seq = self._paused_execution = None

    @property
    def state(self) -> dict:
        """내부 상태의 읽기용 복사본. Qt snapshot 형식으로 해석하지 않는다."""
        return deepcopy(dict(**self._state, controller_ready=self._ready,
                             at_observe_point=self._at_observe))

    def _event(self, event: str, *, request_id=None, result=None, reason=None, owner=None) -> bool:
        state, context = self._state, self._state["context"]
        step = self._next_step() if context else None
        if self._record is None or state["job_id"] is None:
            return True
        try:
            metadata = owner or dict(job_id=state["job_id"],plan_id=context["plan"]["plan_id"] if context else None,
                                     step_id=step["step_id"] if step else None)
            if event == "QUESTION_OPENED":
                self._request_owners[request_id] = metadata
            self._record(dict(**metadata,request_id=request_id,event=event,result=deepcopy(result),reason=reason))
            return True
        except (OSError, ValueError) as error:
            state["fault"] = f"LOG_FAILED: {error}"
            self._hold(state["fault"])
            return False

    def _ignored(self, request_id: str) -> bool:
        _text(request_id,"result.request_id")
        self._event("LATE_RESULT_IGNORED", request_id=request_id,owner=self._request_owners.get(request_id))
        return False

    def controller_ready(self, *, ready: bool, at_observe_point: bool) -> None:
        if type(ready) is not bool or type(at_observe_point) is not bool:
            raise ValueError("controller readiness: expected booleans")
        if self._state["workflow_status"] not in ("IDLE", "COMPLETE"):
            raise ValueError("startup readiness cannot relabel an active execution")
        self._ready, self._at_observe = ready, at_observe_point

    def _hold(self, reason: str) -> None:
        self._state.update(workflow_status="HOLD", reason=reason, active_check=None,
                           place_check=None, planning_request=None, question_request=None,
                           current_check=None,correction_request=None,choice_required=False)

    def _send(self, port: str, payload: dict) -> None:
        identity = payload.get("request_id", payload.get("execution_id", payload.get("check_id")))
        context = self._state["context"]
        step = self._next_step() if context else None
        self._request_owners[identity] = dict(job_id=self._state["job_id"],
            plan_id=context["plan"]["plan_id"] if context else None,step_id=step["step_id"] if step else None)
        if not self._event("REQUEST_SENT", request_id=identity, result=dict(port=port, payload=payload)):
            if port != "robot.stop":
                return
        try:
            self._emit(port, deepcopy(payload))
        except Exception as error:
            # 호출 실패를 정상 반환/빈 Plan으로 바꾸거나 자동으로 재시도하지 않는다.
            if port.startswith("robot."):
                self._state["fault"] = str(error)
                self._ready = self._at_observe = False
            self._hold(f"CALL_FAILED {port}: {error}")
            self._event("CALL_FAILED", request_id=identity, reason=self._state["reason"])

    def command(self, value: object) -> dict:
        command, state = validate_hmi_command(value), self._state
        name = command["command"]
        if name != "START" and command["job_id"] != state["job_id"]:
            return dict(accepted=False, reason="OLD_JOB")
        if name not in ("START", "STOP", "RESUME"):
            return replan.exception_command(self,command)
        if name == "START":
            if state["workflow_status"] not in ("IDLE", "COMPLETE"):
                return dict(accepted=False, reason="JOB_ACTIVE")
            if not self._ready or not self._at_observe:
                return dict(accepted=False, reason="CONTROLLER_NOT_READY_AT_OBSERVE")
            state.update(job_id=str(uuid4()), current=dict(current_revision=0, blocks=[]),
                         context=None, comparison="WAITING", difference=None, question=None, fault=None,
                         last_observation=None, step_observation=None,pending_design=None,current_check=None,
                         correction_request=None,correction_required=False,current_check_blocked=False,
                         choice_required=False,unclear_count=0)
            self._awaiting_assembly = self._delivery_goal = False
            if not self._event("JOB_STARTED"):
                return dict(accepted=False, reason=state["reason"])
            self._request_plan()
        elif name == "STOP":
            if state["workflow_status"] in ("IDLE", "COMPLETE", "STOPPED") or state["stop_request"]:
                return dict(accepted=False, reason="STOP_NOT_APPLICABLE")
            self._paused_execution = state["execution_id"]
            self._at_observe = False
            self._hold("STOP_PENDING")
            state["stop_request"] = str(uuid4())
            self._send("robot.stop", dict(request_id=state["stop_request"], execution_id=self._paused_execution))
        else:
            if state["workflow_status"] != "STOPPED" or state["fault"]:
                return dict(accepted=False, reason="RESUME_NOT_APPLICABLE")
            state.update(workflow_status="DELIVERING", reason=None, execution_id=str(uuid4()))
            step = self._next_step() if state["context"] is not None else None
            goal = (dict(execution_id=state["execution_id"], brick_type=step["after"]["brick_type"],
                         color=step["after"]["color"]) if self._delivery_goal else None)
            self._send("robot.resume", dict(execution_id=state["execution_id"], goal=goal,
                                             previous_execution_id=self._paused_execution))
        return dict(accepted=True, reason=state["reason"])

    def _request_plan(self) -> None:
        request = dict(request_id=str(uuid4()), job_id=self._state["job_id"], design_version=1,
                       base_current_revision=self._state["current"]["current_revision"])
        self._state.update(workflow_status="PREPARING", planning_request=request, reason=None)
        self._send("planner", dict(**request, current=self._state["current"],
                                   supported_scope=self._state["supported_scope"]))

    def on_plan(self, request_id: str, design: object, plan: object) -> bool:
        request, state = self._state["planning_request"], self._state
        if state["workflow_status"] not in ("PREPARING","REPLANNING") or request is None or request_id != request["request_id"]:
            return self._ignored(request_id)
        try:
            context = freeze_plan_basis(design, plan, state["current"])
            if (context["design"]["design_version"] != request["design_version"] or
                    context["plan"]["base_current_revision"] != request["base_current_revision"]):
                raise ValueError("Plan differs from active request basis")
            if "design" in request and not replan.same_layout(context["design"],request["design"]):
                raise ValueError("Design differs from pending candidate")
        except ValueError as error:
            self._hold(f"PLAN_INVALID: {error}")
            return True
        if state["current_check_blocked"]:
            if "ready_result" in request:
                return self._ignored(request_id)
            request["ready_result"] = dict(design=deepcopy(design),plan=deepcopy(plan))
            state["reason"] = "CURRENT_RECHECK_REQUIRED"
            self._event("PLAN_WAITING_OBSERVATION",request_id=request_id,reason=state["reason"])
            return True
        state.update(context=context, planning_request=None,pending_design=None,current_check=None,
                     correction_required=False,correction_request=None,question_request=None,question=None,
                     choice_required=False,difference=None,comparison="WAITING",step_observation=None)
        self._awaiting_assembly = self._delivery_goal = False
        if not self._event("PLAN_ADOPTED", request_id=request_id, result=context):
            return True
        if not context["plan"]["steps"]:
            result = evaluate_job_completion(context, state["current"])
            if result["job_complete"]:
                state.update(workflow_status="COMPLETE", reason="JOB_CONFIRMED")
                self._event("JOB_COMPLETED", result=state["current"])
            else:
                state.update(difference=result["difference"], workflow_status="WAIT_INTENT")
                self._request_question()
        else:
            self._open_vision()
        return True

    def _next_step(self) -> dict | None:
        context = self._state["context"]
        index = len(context["confirmed_steps"])
        return context["plan"]["steps"][index] if index < len(context["plan"]["steps"]) else None

    def _open_vision(self) -> None:
        state = self._state
        if not self._at_observe or state["execution_id"] is not None or state["stop_request"] or state["fault"]:
            self._hold("OBSERVE_POINT_NOT_READY")
            return
        check_id, self._place_seq = str(uuid4()), None
        state.update(place_status=None, place_check=None, active_check=None, step_observation=None)
        step = self._next_step()
        if self._awaiting_assembly:
            state.update(workflow_status="WAIT_ASSEMBLY", reason=None)
            state["active_check"] = open_observation_check(check_id, state["job_id"],
                                                           state["context"]["plan"]["plan_id"], step["step_id"])
        else:
            state.update(workflow_status="HOLD", reason="WAIT_PLACE_EMPTY",
                         place_check=dict(check_id=check_id))
        self._send("vision", dict(check_id=check_id, after=step["after"] if self._awaiting_assembly else None))

    def _deliver(self) -> None:
        state = self._state
        if (state["place_status"] != "EMPTY" or state["execution_id"] is not None or
                state["stop_request"] or state["fault"] or not self._at_observe or self._awaiting_assembly):
            return
        step = self._next_step()
        if step is None:
            return
        state.update(workflow_status="DELIVERING", execution_id=str(uuid4()), reason=None,
                     active_check=None, place_check=None, place_status=None, comparison="WAITING")
        state["step_observation"] = None
        self._at_observe = False
        self._delivery_goal = True
        self._send("robot.deliver", dict(execution_id=state["execution_id"],
                                         brick_type=step["after"]["brick_type"], color=step["after"]["color"]))

    def on_robot_result(self, value: object) -> bool:
        result = _object(value, ("execution_id", "success", "reason"), "robot.result")
        _text(result["execution_id"], "robot.result.execution_id")
        if type(result["success"]) is not bool:
            raise ValueError("robot.result.success: expected boolean")
        if not result["success"] or result["reason"] is not None:
            _text(result["reason"], "robot.result.reason")
        state = self._state
        if state["workflow_status"] != "DELIVERING" or result["execution_id"] != state["execution_id"]:
            return self._ignored(result["execution_id"])
        if not self._event("DELIVERY_RESULT", request_id=result["execution_id"], result=result):
            return True
        state["execution_id"] = None
        if not result["success"]:
            state["fault"] = result["reason"]
            self._ready = self._at_observe = False
            self._hold(result["reason"])
        else:
            self._ready = self._at_observe = True
            self._awaiting_assembly = self._awaiting_assembly or self._delivery_goal
            self._delivery_goal = False
            if state["correction_required"]:
                replan.request_correction(self,state["correction_reason"],state["correction_conflicts"])
            elif state["pending_design"] is not None:
                replan.begin_replan(self,state["pending_design"])
            elif state["context"] is None:
                self._request_plan()
            elif state["difference"] is not None:
                state["workflow_status"] = "WAIT_INTENT"
                self._request_question()
            else:
                self._open_vision()
        return True

    def on_place(self, check_id: str, observation_seq: int, status: str, reason=None) -> bool:
        _integer(observation_seq, 0, None, "place.observation_seq")
        if status not in ("EMPTY", "OCCUPIED", "UNOBSERVABLE"):
            raise ValueError("place.status: unsupported status")
        if status == "UNOBSERVABLE" or reason is not None:
            _text(reason, "place.reason")
        state = self._state
        active = state["active_check"] or state["place_check"]
        if (not self._at_observe or state["stop_request"] or active is None or
                check_id != active["check_id"] or self._place_seq is not None and observation_seq <= self._place_seq):
            return self._ignored(check_id)
        self._place_seq = observation_seq
        if state["place_status"] != status:
            state["place_status"] = status
            if not self._event("PLACE_STATUS_CHANGED", request_id=check_id, result=status, reason=reason):
                return True
        if not self._awaiting_assembly:
            state["reason"] = reason or f"WAIT_PLACE_{status}"
            self._deliver()
        return True

    def on_observation(self, value: object) -> bool:
        observation, state = validate_observed(value), self._state
        if state["current_check"] is not None:
            return replan.on_current_observation(self,observation)
        if not self._at_observe or state["active_check"] is None or state["stop_request"]:
            return self._ignored(observation["check_id"])
        result = evaluate_observation(state["context"], state["current"], state["active_check"], observation)
        if result["disposition"] == "IGNORED":
            return self._ignored(observation["check_id"])
        previous = (state["workflow_status"], state["reason"])
        state.update(last_observation=observation, step_observation=observation)
        if result["current"] != state["current"]:
            if not self._event("CURRENT_ADOPTED", request_id=observation["check_id"],
                               result=dict(current=result["current"],observed=observation)):
                state["current"] = result["current"]
                return True
        if result["step_confirmed"]:
            if not self._event("STEP_CONFIRMED", request_id=observation["check_id"],
                               result=dict(observation_seq=observation["observation_seq"])):
                state["current"] = result["current"]
                return True
        state.update(context=result["context"], current=result["current"], active_check=result["active_check"],
                     comparison=result["comparison"], difference=result["difference"], reason=result["reason"])
        if result["requires_intent"]:
            state.update(workflow_status="WAIT_INTENT", active_check=None, place_check=None)
            self._request_question()
        elif result["job_complete"]:
            state.update(workflow_status="COMPLETE", active_check=None, place_check=None)
            self._event("JOB_COMPLETED", result=state["current"])
        elif result["step_confirmed"]:
            self._awaiting_assembly = False
            if state["place_status"] == "EMPTY":
                self._deliver()
            else:
                self._open_vision()
        else:
            state["workflow_status"] = "HOLD"
            if previous != ("HOLD", state["reason"]):
                self._event("OBSERVATION_HOLD", request_id=observation["check_id"], reason=state["reason"])
        return True

    def _request_question(self) -> None:
        state = self._state
        request = dict(request_id=str(uuid4()), job_id=state["job_id"],
                       design_version=state["context"]["design"]["design_version"],
                       current_revision=state["current"]["current_revision"])
        state.update(question_request=request, question=None, reason="WAIT_INTENT",choice_required=False,unclear_count=0)
        self._send("hri", dict(**request, design=state["context"]["design"],
                               current=state["current"], difference=state["difference"],
                               supported_scope=state["supported_scope"]))
        if state["workflow_status"] == "WAIT_INTENT":
            replan.open_current_check(self,"INTENT")

    def on_intent(self, value: object) -> bool:
        return replan.on_intent(self,value)

    def on_plan_result(self, request_id: str, value: object) -> bool:
        return replan.on_plan_result(self,request_id,value)

    def on_failure(self, port: str, request_id: str, reason: str) -> bool:
        _text(reason,"failure.reason")
        request = {"planner":self._state["planning_request"],"hri":self._state["question_request"],
                   "vision":self._state["active_check"] or self._state["current_check"] or self._state["place_check"]}.get(port)
        if request is None or request_id != request.get("request_id",request.get("check_id")):
            return self._ignored(request_id)
        if port == "planner" and "ready_result" in request:
            return self._ignored(request_id)
        self._hold(f"CALL_FAILED {port}: {reason}")
        self._event("CALL_FAILED",request_id=request_id,reason=reason)
        return True

    def on_question(self, request_id: str, question: str) -> bool:
        _text(question, "question")
        request = self._state["question_request"]
        if request is None or request_id != request["request_id"] or self._state["workflow_status"] != "WAIT_INTENT":
            return self._ignored(request_id)
        self._state["question"] = question
        self._event("QUESTION_RECEIVED", request_id=request_id, result=question)
        return True

    def on_stopped(self, request_id: str, *, stopped: bool, execution_ended: bool,
                   block_state_known: bool) -> bool:
        if any(type(flag) is not bool for flag in (stopped, execution_ended, block_state_known)):
            raise ValueError("stop confirmation: expected booleans")
        state = self._state
        if request_id != state["stop_request"] or state["stop_request"] is None:
            return self._ignored(request_id)
        if not (stopped and execution_ended and block_state_known):
            state["reason"] = "STOP_UNCONFIRMED"
        else:
            state.update(stop_request=None, execution_id=None,
                         workflow_status="HOLD" if state["fault"] else "STOPPED",
                         reason=state["fault"] or "STOP_CONFIRMED")
        self._event("STOP_STATUS", request_id=request_id, result=self._state["workflow_status"],
                    reason=state["reason"])
        return True
