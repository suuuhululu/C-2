"""Synthetic ROS service/future sequences. Never imports ROS or operates devices."""
import sys
from types import SimpleNamespace as NS

import pytest

from app import handover_gesture_gripper as module


@pytest.fixture
def rig(monkeypatch):
    state = NS(now=0, ready=True, pending=False, feedback=1, system=0, robot_state=1,
               fail_step=None, send_exception=None, future_exception=False, response_none=False,
               calls=[], records=[], futures=[])
    monkeypatch.setattr(module, "time", NS(monotonic_ns=lambda: state.now))
    service = NS(Request=lambda: NS())
    monkeypatch.setitem(sys.modules, "dsr_msgs2.srv", NS(GetRobotSystem=service,
                       GetRobotState=service, SetCtrlBoxDigitalOutput=service,
                       GetCtrlBoxDigitalInput=service))

    def send(path, request):
        step = state.records[-1]["step"]
        assert state.records[-1]["kind"] == "REQUEST"  # Intent is durable before call.
        state.calls.append((path, vars(request).copy()))
        if step == state.send_exception:
            raise RuntimeError("synthetic send failure")
        response = NS(success=step != state.fail_step, robot_system=state.system,
                      robot_state=state.robot_state, value=state.feedback)

        def result():
            if state.future_exception:
                raise RuntimeError("synthetic future failure")
            return None if state.response_none else response

        future = NS(cancelled=False, done=lambda: not state.pending, result=result)
        future.cancel = lambda: setattr(future, "cancelled", True)
        state.futures.append(future)
        return future

    node = NS(create_client=lambda srv, path: NS(service_is_ready=lambda: state.ready,
              call_async=lambda request: send(path, request)))
    gripper = module.WebLogicGripper(node, "/dsr01/dsr_controller2", state.records.append)
    return gripper, state


def tick(gripper, state, eligible=True, age=0):
    state.now += 100_000_000
    gripper.advance(eligible, state.now-age)


def drive(gripper, state):
    for _ in range(60):
        tick(gripper, state)
        if not gripper.busy:
            return
    pytest.fail("sequence did not terminate")


def test_open_sequence_and_one_command_pair_per_request(rig):
    g, s = rig
    tick(g, s)
    assert s.calls == []  # Constructing the adapter never sends a command.
    g.start("open1"); drive(g, s)
    assert g.state == "OPEN_FEEDBACK_CONFIRMED" and g.output_commands_attempted == 2
    assert [path.split("/")[-1] for path, request in s.calls] == [
        "get_robot_system", "get_robot_state", "set_ctrl_box_digital_output",
        "set_ctrl_box_digital_output", "get_ctrl_box_digital_input"]
    assert [request for path, request in s.calls[2:]] == [
        {"index": 1, "value": 0}, {"index": 2, "value": 1}, {"index": 2}]
    g.start("open1"); tick(g, s)
    assert len(s.calls) == 5
    g.start("open2"); drive(g, s)
    assert len(s.calls) == 10 and g.output_commands_attempted == 4


@pytest.mark.parametrize("field,value,reason", [
    ("system", 1, "REAL_ROBOT_REQUIRED"),
    ("robot_state", 2, "ROBOT_NOT_STANDBY"),
    ("ready", False, "GRIPPER_SERVICES_UNAVAILABLE"),
])
def test_output_refused_for_virtual_moving_or_unavailable_robot(rig, field, value, reason):
    g, s = rig; setattr(s, field, value)
    g.start("refused"); drive(g, s)
    assert g.state == "FAIL" and g.reason == reason
    assert g.output_commands_attempted == 0
    assert not any("set_ctrl" in path for path, _ in s.calls)


@pytest.mark.parametrize("step,expected_attempts", [
    ("SYSTEM", 0), ("STANDBY", 0), ("CLOSE_OFF", 1), ("OPEN_ON", 2), ("FEEDBACK", 2),
])
def test_failed_response_latches_and_never_retries_or_closes(rig, step, expected_attempts):
    g, s = rig; s.fail_step = step
    g.start("fail"); drive(g, s)
    assert g.state == "FAIL" and g.reason == "SERVICE_FAILED"
    assert g.output_commands_attempted == expected_attempts
    count = len(s.calls)
    g.start("another"); drive(g, s)
    assert len(s.calls) == count
    assert all(req != {"index": 1, "value": 1} for _, req in s.calls)


@pytest.mark.parametrize("age", [0, 300_000_001, -1])
def test_loss_or_stale_frame_cancels_pending_future_before_outputs(rig, age):
    g, s = rig; s.pending = True
    g.start("lost"); tick(g, s)
    tick(g, s, eligible=age != 0, age=age)
    assert g.state == "FAIL" and g.reason == "OPEN_HAND_LOST_OR_STALE"
    assert s.futures[0].cancelled and g.output_commands_attempted == 0
    s.pending = False; g.start("new"); tick(g, s)
    assert len(s.calls) == 1


def test_context_change_after_close_off_prevents_open_on(rig):
    g, s = rig; g.start("old")
    for _ in range(3): tick(g, s)
    assert g.state == "CLOSE_OFF" and g.output_commands_attempted == 1
    g.abort("OPERATOR_CONTEXT_CHANGED"); tick(g, s)
    assert s.futures[-1].cancelled and g.state == "FAIL"
    assert len(s.calls) == 3


@pytest.mark.parametrize("pending", [True, False])
def test_timeout_during_read_or_unconfirmed_feedback_has_no_rollback(rig, pending):
    g, s = rig; s.pending = pending; s.feedback = 0
    g.start("timeout"); drive(g, s)
    assert g.state == "FAIL" and g.reason == "GRIPPER_SEQUENCE_TIMEOUT"
    assert g.output_commands_attempted == (0 if pending else 2)
    assert all(req != {"index": 1, "value": 1} for _, req in s.calls)


@pytest.mark.parametrize("failure", ["future_exception", "response_none"])
def test_failed_future_is_not_success(rig, failure):
    g, s = rig; setattr(s, failure, True)
    g.start("future"); drive(g, s)
    assert g.state == "FAIL" and g.output_commands_attempted == 0


def test_send_exception_counts_possible_output_and_stops(rig):
    g, s = rig; s.send_exception = "OPEN_ON"
    g.start("send"); drive(g, s)
    assert g.state == "FAIL" and g.reason.startswith("SERVICE_SEND_EXCEPTION")
    assert g.output_commands_attempted == 2 and len(s.calls) == 4


def test_journal_failure_prevents_hardware_write(rig):
    g, s = rig; g.start("journal")
    tick(g, s); tick(g, s)
    original = g.record

    def record(row):
        if row["kind"] == "REQUEST" and row["step"] == "CLOSE_OFF":
            raise OSError("synthetic disk failure")
        original(row)

    g.record = record
    with pytest.raises(OSError): tick(g, s)
    assert g.output_commands_attempted == 0 and len(s.calls) == 2
