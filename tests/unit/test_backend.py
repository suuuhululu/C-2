from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.backend import Backend


FIXTURES = json.loads((Path(__file__).resolve().parents[2] / "interfaces/fixtures/day4.json").read_text())
A, B, C = FIXTURES["design"]["blocks"]
RA = dict(x=3, y=5, width=2, height=2, layer=1)
RB = dict(x=5, y=5, width=2, height=2, layer=1)
RC = dict(x=3, y=5, width=3, height=2, layer=2)


class FakePorts:
    def __init__(self):
        self.requests = []
        self.fail = None

    def __call__(self, port, payload):
        self.requests.append((port, deepcopy(payload)))
        if port == self.fail:
            raise RuntimeError("fixture call failed")

    def calls(self, port):
        return [payload for name, payload in self.requests if name == port]


def started():
    ports = FakePorts()
    backend = Backend(ports, mode="FAKE")
    backend.controller_ready(ready=True, at_observe_point=True)
    assert backend.command({"command": "START"})["accepted"]
    return backend, ports


def planned():
    backend, ports = started()
    assert backend.on_plan(ports.calls("planner")[-1]["request_id"], FIXTURES["design"], FIXTURES["initial_plan"])
    return backend, ports


def delivering():
    backend, ports = planned()
    place = backend.state["place_check"]["check_id"]
    assert backend.on_place(place, 0, "EMPTY")
    return backend, ports


def robot_success(backend):
    execution = backend.state["execution_id"]
    assert backend.on_robot_result(dict(execution_id=execution, success=True, reason=None))
    return execution


def observation(backend, blocks, regions, seq=0):
    return {**deepcopy(FIXTURES["observed_match"]), "check_id": backend.state["active_check"]["check_id"],
            "observation_seq": seq, "visible_blocks": deepcopy(blocks), "verified_regions": deepcopy(regions)}


def stop_confirmed(backend):
    assert backend.command(dict(command="STOP", job_id=backend.state["job_id"]))["accepted"]
    request = backend.state["stop_request"]
    assert backend.on_stopped(request, stopped=True, execution_ended=True, block_state_known=True)


def test_normal_three_steps_need_delivery_return_actual_assembly_and_fresh_place_empty():
    backend, ports = delivering()
    for index, (blocks, regions) in enumerate([([A], [RA]), ([A, B], [RA, RB]), ([C], [RC])]):
        robot_success(backend)
        assert backend.state["current"]["current_revision"] == index
        assert len(backend.state["context"]["confirmed_steps"]) == index
        payload = observation(backend, blocks, regions)
        assert backend.on_place(payload["check_id"], 0, "EMPTY")
        assert backend.on_observation(payload)
    assert backend.state["workflow_status"] == "COMPLETE"
    assert backend.state["current"]["blocks"] == [A, B, C]
    assert len(ports.calls("robot.deliver")) == 3
    assert len(ports.calls("planner")) == 1 and ports.calls("hri") == []
    assert all(set(goal) == {"execution_id", "brick_type", "color"} for goal in ports.calls("robot.deliver"))


@pytest.mark.parametrize("status", ["OCCUPIED", "UNOBSERVABLE"])
def test_initial_unknown_or_occupied_place_never_dispatches_delivery(status):
    backend, ports = planned()
    assert ports.calls("robot.deliver") == []
    check = backend.state["place_check"]["check_id"]
    assert backend.on_place(check, 1, status, "hand" if status == "UNOBSERVABLE" else None)
    assert ports.calls("robot.deliver") == []
    assert backend.on_place(check, 2, "EMPTY")
    assert len(ports.calls("robot.deliver")) == 1
    assert not backend.on_place(check, 3, "EMPTY")


def test_step_confirmation_without_empty_opens_new_automatic_place_check():
    backend, ports = delivering()
    robot_success(backend)
    payload = observation(backend, [A], [RA])
    assert backend.on_observation(payload)
    assert len(backend.state["context"]["confirmed_steps"]) == 1
    assert len(ports.calls("robot.deliver")) == 1
    check = backend.state["place_check"]["check_id"]
    assert check != payload["check_id"]
    assert not backend.on_place(payload["check_id"], 1, "EMPTY")
    assert backend.on_place(check, 0, "EMPTY")
    assert len(ports.calls("robot.deliver")) == 2
    assert not backend.on_observation(payload)


def test_old_empty_robot_duplicates_and_frames_during_motion_do_not_progress():
    backend, ports = planned()
    old = backend.state["place_check"]["check_id"]
    backend.on_place(old, 0, "EMPTY")
    execution = backend.state["execution_id"]
    payload = {**FIXTURES["observed_match"], "check_id": old, "observation_seq": 99}
    assert not backend.on_observation(payload)
    robot_success(backend)
    assert backend.state["place_status"] is None
    assert not backend.on_robot_result(dict(execution_id=execution, success=True, reason=None))
    assert not backend.on_place(old, 100, "EMPTY")
    assert len(ports.calls("robot.deliver")) == 1


def test_mismatch_adopts_actual_and_requests_one_question_without_next_delivery():
    backend, ports = delivering()
    robot_success(backend)
    wrong = {**A, "color": "blue"}
    payload = observation(backend, [wrong], [RA])
    backend.on_observation(payload)
    assert backend.state["current"]["blocks"] == [wrong]
    assert backend.state["context"]["confirmed_steps"] == []
    assert backend.state["workflow_status"] == "WAIT_INTENT"
    assert len(ports.calls("hri")) == 1 and len(ports.calls("robot.deliver")) == 1
    assert not backend.on_observation(payload)
    question = ports.calls("hri")[-1]
    assert backend.on_question(question["request_id"], "원래 목표를 유지할까요?")
    assert not backend.on_question("old-question", "늦은 질문")
    assert question["current"]["blocks"] == [wrong]


def test_unobservable_and_old_frame_do_not_confirm_or_dispatch_again():
    backend, ports = delivering()
    robot_success(backend)
    check = backend.state["active_check"]["check_id"]
    payload = {**FIXTURES["observed_unobservable"], "check_id": check}
    assert backend.on_observation(payload)
    assert backend.state["comparison"] == "UNOBSERVABLE"
    assert backend.state["current"]["blocks"] == []
    late = observation(backend, [A], [RA], 15)
    assert not backend.on_observation(late)
    assert len(ports.calls("robot.deliver")) == 1


@pytest.mark.parametrize("confirmed", [(False, True, True), (True, False, True), (True, True, False)])
def test_stop_request_or_incomplete_confirmation_cannot_resume(confirmed):
    backend, ports = delivering()
    job = backend.state["job_id"]
    backend.command(dict(command="STOP", job_id=job))
    request = backend.state["stop_request"]
    assert not backend.command(dict(command="RESUME", job_id=job))["accepted"]
    assert backend.on_stopped(request, stopped=confirmed[0], execution_ended=confirmed[1], block_state_known=confirmed[2])
    assert backend.state["workflow_status"] == "HOLD"
    assert not backend.command(dict(command="RESUME", job_id=job))["accepted"]
    assert ports.calls("robot.resume") == []


def test_delivery_stop_resume_uses_new_execution_and_ignores_old_success():
    backend, ports = delivering()
    old, job = backend.state["execution_id"], backend.state["job_id"]
    stop_confirmed(backend)
    assert backend.state["current"]["blocks"] == []
    assert backend.command(dict(command="RESUME", job_id=job))["accepted"]
    new = backend.state["execution_id"]
    assert old != new and backend.state["job_id"] == job
    resume = ports.calls("robot.resume")[-1]
    assert resume["previous_execution_id"] == old and resume["goal"]["execution_id"] == new
    assert not backend.on_robot_result(dict(execution_id=old, success=True, reason=None))
    robot_success(backend)
    assert backend.state["workflow_status"] == "WAIT_ASSEMBLY"
    assert len(ports.calls("robot.deliver")) == 1


def test_assembly_stop_resume_requires_return_confirmation_then_new_check():
    backend, ports = delivering()
    robot_success(backend)
    old = observation(backend, [A], [RA])
    stop_confirmed(backend)
    backend.command(dict(command="RESUME", job_id=backend.state["job_id"]))
    assert ports.calls("robot.resume")[-1]["goal"] is None
    assert not backend.on_observation(old)
    robot_success(backend)
    assert backend.state["active_check"]["check_id"] != old["check_id"]
    assert not backend.on_observation(old)
    assert len(ports.calls("robot.deliver")) == 1


def test_stop_during_planning_closes_old_request_and_resumes_with_fresh_basis_request():
    backend, ports = started()
    old = ports.calls("planner")[-1]["request_id"]
    stop_confirmed(backend)
    assert not backend.on_plan(old, FIXTURES["design"], FIXTURES["initial_plan"])
    backend.command(dict(command="RESUME", job_id=backend.state["job_id"]))
    robot_success(backend)
    assert len(ports.calls("planner")) == 2
    assert ports.calls("planner")[-1]["request_id"] != old
    assert not backend.on_plan(old, FIXTURES["design"], FIXTURES["initial_plan"])


def test_stop_closes_question_and_old_job_commands_are_rejected():
    backend, ports = delivering()
    robot_success(backend)
    backend.on_observation(observation(backend, [{**A, "color": "blue"}], [RA]))
    question = ports.calls("hri")[-1]["request_id"]
    before = backend.state
    assert not backend.command(dict(command="STOP", job_id="old-job"))["accepted"]
    assert backend.state == before
    stop_confirmed(backend)
    assert not backend.on_question(question, "old question")
    backend.command(dict(command="RESUME", job_id=backend.state["job_id"]))
    robot_success(backend)
    assert len(ports.calls("hri")) == 2
    assert ports.calls("hri")[-1]["request_id"] != question


def test_robot_failure_holds_without_retry_or_step_completion():
    backend, ports = delivering()
    backend.on_robot_result(dict(execution_id=backend.state["execution_id"], success=False, reason="return failed"))
    assert backend.state["workflow_status"] == "HOLD"
    assert backend.state["fault"] == "return failed"
    stop_confirmed(backend)
    assert backend.state["workflow_status"] == "HOLD"
    assert not backend.command(dict(command="RESUME", job_id=backend.state["job_id"]))["accepted"]
    assert backend.state["current"]["blocks"] == [] and len(ports.calls("robot.deliver")) == 1


@pytest.mark.parametrize("port", ["planner", "vision", "robot.deliver", "hri"])
def test_dependency_call_failure_is_not_success_or_automatic_retry(port):
    backend, ports = started()
    if port == "planner":
        stop_confirmed(backend)
        ports.fail = port
        backend.command(dict(command="RESUME", job_id=backend.state["job_id"]))
        robot_success(backend)
    else:
        ports.fail = port if port != "hri" else None
        backend.on_plan(ports.calls("planner")[-1]["request_id"], FIXTURES["design"], FIXTURES["initial_plan"])
        if port in ("robot.deliver", "hri"):
            backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
        if port == "hri":
            robot_success(backend)
            ports.fail = port
            backend.on_observation(observation(backend, [{**A, "color": "blue"}], [RA]))
    assert backend.state["workflow_status"] == "HOLD"
    assert "CALL_FAILED" in backend.state["reason"]
    assert backend.state["planning_request"] is None and backend.state["active_check"] is None


@pytest.mark.parametrize("field,value", [("design_version", 2), ("base_current_revision", 1)])
def test_plan_basis_mismatch_is_not_executed(field, value):
    backend, ports = started()
    backend.on_plan(ports.calls("planner")[-1]["request_id"], FIXTURES["design"], {**FIXTURES["initial_plan"], field: value})
    assert backend.state["workflow_status"] == "HOLD" and ports.calls("robot.deliver") == []


def test_start_requires_explicit_fake_controller_readiness_and_single_job():
    ports = FakePorts()
    with pytest.raises(ValueError, match="FAKE"):
        Backend(ports, mode="REAL")
    backend = Backend(ports, mode="FAKE")
    assert not backend.command({"command": "START"})["accepted"]
    assert backend.state["job_id"] is None and ports.requests == []
    backend.controller_ready(ready=True, at_observe_point=True)
    backend.command({"command": "START"})
    before = backend.state
    assert not backend.command({"command": "START"})["accepted"]
    assert backend.state == before and len(ports.calls("planner")) == 1


def test_state_and_outgoing_payloads_are_copies():
    backend, ports = planned()
    before = backend.state
    copy = backend.state
    copy["context"]["design"]["blocks"].clear()
    ports.calls("planner")[0]["current"]["blocks"].append(C)
    assert backend.state == before
