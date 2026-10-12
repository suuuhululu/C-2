"""취소 ACK/실제 정지/실제 수신을 분리하는 0단계 FAKE 검증."""

import pytest

from app.handover import handover_capabilities
from app.handover_demo import CONFIG, create_demo, start_transport
from app.fake_robot_driver import FakeRobotDriver
from app.robot_controller import RobotController, load_robot_config


def setup_transport():
    controller, driver = create_demo()
    assert start_transport(controller, driver)["accepted"]
    identity = controller.state["active_execution"]["execution_id"]
    return controller, driver, identity


def ask(controller, execution, identity="handover-1"):
    return controller.request_handover(dict(request_id=identity, execution_id=execution))


def stopped(driver, identity="handover-1", **changes):
    evidence = dict(stopped=True, execution_ended=True, block_state_known=True, block_state="HOLDING")
    evidence.update(changes)
    return driver.confirm_stop(identity, **evidence)


def test_stop_ack_does_not_complete_or_open_and_late_place_is_ignored():
    controller, driver, execution = setup_transport()
    assert ask(controller, execution)["accepted"]
    assert controller.handover["status"] == "STOP_PENDING"
    assert not driver.confirm(execution, "place")
    assert [call[0] for call in driver.calls] == ["pick", "place", "stop"]
    assert stopped(driver)
    assert controller.handover["status"] == "WAIT_RECEIVER"
    assert not driver.confirm(execution, "place")
    assert len(driver.calls) == 3


@pytest.mark.parametrize("evidence", [dict(stopped=False), dict(execution_ended=False),
    dict(block_state_known=False), dict(block_state="UNKNOWN")])
def test_unconfirmed_stop_never_enters_wait_or_resumes(evidence):
    controller, driver, execution = setup_transport()
    ask(controller, execution)
    assert not stopped(driver, **evidence)
    assert controller.handover["status"] == "STOP_PENDING"
    assert controller.handover["reason"] == "STOP_UNCONFIRMED"
    goal = dict(execution_id="new", brick_type="2x2x1", color="yellow")
    assert not controller.resume(dict(execution_id="new", previous_execution_id=execution, goal=goal))["accepted"]
    assert len(driver.calls) == 3


def test_communication_exception_is_visible_and_cannot_later_restore_wait(monkeypatch):
    controller, driver, execution = setup_transport()

    def fail(*args):
        raise RuntimeError("injected communication failure")

    monkeypatch.setattr(driver, "stop", fail)
    reply = ask(controller, execution)
    assert not reply["accepted"]
    assert "communication failure" in reply["reason"]
    assert controller.handover["status"] == "CHECK_REQUIRED"
    assert not driver.confirm(execution, "place")
    controller.on_stop_confirmation("handover-1", stopped=True, execution_ended=True,
        block_state_known=True, block_state="HOLDING")
    assert controller.handover["status"] == "CHECK_REQUIRED"
    assert len(driver.calls) == 2


def test_disabled_preserves_complete_board_path():
    driver, results = FakeRobotDriver(ready_at_observe=True), []
    controller = RobotController(load_robot_config(CONFIG), driver, results.append)
    controller.deliver(dict(execution_id="board", brick_type="2x2x1", color="yellow"))
    driver.confirm("board", "pick")
    assert ask(controller, "board")["reason"] == "HANDOVER_DISABLED"
    for operation in ("place", "observe"):
        assert driver.confirm("board", operation)
    assert results == [dict(execution_id="board", success=True, reason=None)]
    assert [call[0] for call in driver.calls] == ["pick", "place", "observe"]


def test_request_only_applies_to_transport_and_later_stages_stay_disabled():
    controller, driver = create_demo()
    assert ask(controller, "transport")["reason"] == "OLD_EXECUTION"
    controller.deliver(dict(execution_id="transport", brick_type="2x2x1", color="yellow"))
    assert ask(controller, "transport")["reason"] == "NOT_TRANSPORTING_BLOCK"
    assert controller.handover["stages"] == {str(stage): stage == 0 for stage in range(13)}
    driver.confirm("transport", "pick")
    driver.confirm("transport", "place")
    assert ask(controller, "transport")["reason"] == "NOT_TRANSPORTING_BLOCK"
    driver.confirm("transport", "observe")
    assert ask(controller, "transport")["reason"] == "OLD_EXECUTION"
    assert [call[0] for call in driver.calls] == ["pick", "place", "observe"]


@pytest.mark.parametrize("enabled", [None, 1, "true"])
def test_feature_flag_requires_explicit_boolean(enabled):
    driver = FakeRobotDriver(ready_at_observe=True)
    with pytest.raises(ValueError):
        RobotController(load_robot_config(CONFIG), driver, lambda result: None,
                        handover_enabled=enabled)
    assert driver.calls == []


def test_duplicate_requests_and_old_stop_cannot_affect_new_job():
    controller, driver, execution = setup_transport()
    ask(controller, execution)
    assert ask(controller, execution)["reason"] == "DUPLICATE"
    assert not controller.on_stop_confirmation("old-stop", stopped=True, execution_ended=True,
        block_state_known=True, block_state="HOLDING")
    assert stopped(driver)
    controller.cancel_handover("handover-1")
    assert not controller.new_job()["accepted"]
    driver.confirm_cleanup(ready_at_observe=True, gripper_empty=True)
    assert controller.new_job()["accepted"]
    assert start_transport(controller, driver)["accepted"]
    new = controller.state["active_execution"]["execution_id"]
    assert ask(controller, new)["reason"] == "DUPLICATE"
    assert ask(controller, execution, "new-attempt")["reason"] == "OLD_EXECUTION"
    assert ask(controller, new, "new-attempt")["accepted"]
    assert not stopped(driver)
    assert controller.handover["status"] == "STOP_PENDING"
    assert stopped(driver, "new-attempt")


@pytest.mark.parametrize("action", ["cancel", "receipt"])
def test_cancel_or_receipt_report_never_releases_or_returns(action):
    controller, driver, execution = setup_transport()
    ask(controller, execution)
    assert stopped(driver)
    method = controller.cancel_handover if action == "cancel" else controller.report_handover_receipt
    assert not method("old-request")["accepted"]
    assert method("handover-1")["accepted"]
    assert not method("handover-1")["accepted"]
    assert controller.handover["status"] == "CHECK_REQUIRED"
    assert controller.handover["receipt_reported"] is (action == "receipt")
    assert len(driver.calls) == 3


def test_cancel_before_stop_cannot_be_revived_by_late_evidence():
    controller, driver, execution = setup_transport()
    ask(controller, execution)
    controller.cancel_handover("handover-1")
    assert stopped(driver)
    assert controller.handover["status"] == "CHECK_REQUIRED"


@pytest.mark.parametrize("reason", ["PROTECTIVE_STOP", "EMERGENCY_STOP", "ROBOT_FAULT"])
def test_safety_dominates_late_stop_receipt_cancel_and_new_job(reason):
    controller, driver, execution = setup_transport()
    ask(controller, execution)
    controller.on_handover_safety(reason)
    assert stopped(driver)
    assert controller.handover["status"] == "SAFETY_HOLD"
    assert not controller.cancel_handover("handover-1")["accepted"]
    assert not controller.report_handover_receipt("handover-1")["accepted"]
    driver.confirm_cleanup(ready_at_observe=True, gripper_empty=True)
    assert controller.new_job()["reason"] == "SAFETY_RECOVERY_UNAVAILABLE"
    assert len(driver.calls) == 3


def test_nonholding_evidence_cannot_enter_wait():
    controller, driver, execution = setup_transport()
    ask(controller, execution)
    assert stopped(driver, block_state="RELEASED")
    assert controller.handover["status"] == "CHECK_REQUIRED"


@pytest.mark.parametrize("mode", ["FAKE", "REPLAY", "REAL"])
def test_modes_never_claim_actual_outputs_available(mode):
    facts = handover_capabilities(mode)
    assert facts["real_output_enabled"] is False
    assert all(facts[name] == "unavailable" for name in ("approach", "release", "confirm_release", "confirm_receipt", "read_force"))
    if mode != "FAKE":
        assert facts["request_stop"] == facts["confirm_stop"] == "unavailable"


@pytest.mark.parametrize("mode", [None, "", "real", "SIM"])
def test_unspecified_or_unsupported_mode_does_not_default_to_real(mode):
    with pytest.raises(ValueError):
        handover_capabilities(mode)
