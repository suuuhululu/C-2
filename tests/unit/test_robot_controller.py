from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.fake_robot_driver import FakeRobotDriver
from app.robot_controller import RobotController, load_robot_config, validate_robot_config


CONFIG_PATH = Path(__file__).resolve().parents[2] / "interfaces/fixtures/robot.json"
CONFIG = json.loads(CONFIG_PATH.read_text())
DAY4 = json.loads((CONFIG_PATH.parent / "day4.json").read_text())
COLUMNS = [(row["brick_type"], row["color"]) for row in CONFIG["supply_rows"]]


def setup_controller(config=None, *, ready=True):
    driver, results = FakeRobotDriver(ready_at_observe=ready), []
    return RobotController(CONFIG if config is None else config, driver, results.append), driver, results


def goal(identity="delivery-1", column=COLUMNS[0]):
    return dict(execution_id=identity, brick_type=column[0], color=column[1])


def supply(controller, column):
    return next(row for row in controller.state["supply"]
                if (row["brick_type"], row["color"]) == column)


def finish(driver, identity):
    for operation in ("pick", "place", "observe"):
        assert driver.confirm(identity, operation)


def test_file_loader_uses_requested_path_and_rejects_missing_or_invalid_json(tmp_path):
    assert load_robot_config(CONFIG_PATH) == CONFIG
    alternate = deepcopy(CONFIG)
    alternate.update(config_id="alternate", observe_point="fake-other-observe", slot_count=2)
    path = tmp_path / "alternate.json"
    path.write_text(json.dumps(alternate))
    assert load_robot_config(path) == alternate
    with pytest.raises(FileNotFoundError):
        load_robot_config(tmp_path / "missing.json")
    path.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        load_robot_config(path)


@pytest.mark.parametrize("field", list(CONFIG))
def test_missing_config_fields_never_default_to_real_or_ready(field):
    config = deepcopy(CONFIG)
    del config[field]
    with pytest.raises(ValueError):
        setup_controller(config)


@pytest.mark.parametrize("field,value", [
    ("mode", "REAL"), ("mode", None), ("slot_count", True), ("slot_count", 0),
    ("slot_count", 7), ("slot_count", 2.5), ("observe_point", None),
    ("place_point", ""), ("config_id", ""), ("supply_rows", {}),
])
def test_invalid_config_cannot_issue_driver_commands(field, value):
    config = deepcopy(CONFIG)
    config[field] = value
    driver = FakeRobotDriver(ready_at_observe=True)
    with pytest.raises(ValueError):
        RobotController(config, driver, lambda result: None)
    assert driver.calls == []


@pytest.mark.parametrize("change", ["missing", "duplicate", "unsupported", "empty_point", "extra"])
def test_supply_configuration_must_match_day4_columns(change):
    config = deepcopy(CONFIG)
    if change == "missing":
        config["supply_rows"].pop()
    elif change == "duplicate":
        config["supply_rows"][-1] = deepcopy(config["supply_rows"][0])
    elif change == "unsupported":
        config["supply_rows"][0]["color"] = "red"
    elif change == "empty_point":
        config["supply_rows"][0]["supply_point"] = ""
    else:
        config["tcp"] = "not-a-real-driver-config"
    with pytest.raises(ValueError):
        validate_robot_config(config)


def test_real_driver_or_nonboolean_fake_readiness_is_rejected():
    driver = FakeRobotDriver(ready_at_observe=True)
    driver.mode = "REAL"
    with pytest.raises(ValueError):
        RobotController(CONFIG, driver, lambda result: None)
    with pytest.raises(ValueError):
        FakeRobotDriver(ready_at_observe=1)


@pytest.mark.parametrize("column", COLUMNS)
def test_one_delivery_consumes_only_after_pick_and_finishes_only_after_observe(column):
    controller, driver, results = setup_controller()
    assert controller.deliver(goal(column=column)) == dict(accepted=True, reason=None)
    assert supply(controller, column)["next_slot"] == 1 and results == []
    assert [operation for operation, _ in driver.calls] == ["pick"]
    assert driver.calls[0][1]["slot"] == 1
    assert driver.calls[0][1]["point"] == next(row["supply_point"] for row in CONFIG["supply_rows"]
        if (row["brick_type"], row["color"]) == column)
    assert driver.confirm("delivery-1", "pick")
    assert supply(controller, column)["next_slot"] == 2 and results == []
    assert driver.confirm("delivery-1", "place")
    assert results == [] and not controller.state["ready_at_observe"]
    assert driver.calls[-1] == ("observe", dict(execution_id="delivery-1", point=CONFIG["observe_point"]))
    assert driver.confirm("delivery-1", "observe")
    assert results == [dict(execution_id="delivery-1", success=True, reason=None)]
    assert controller.state["active_execution"] is None and controller.state["ready_at_observe"]
    assert [operation for operation, _ in driver.calls] == ["pick", "place", "observe"]


def test_duplicate_conflicting_and_busy_goals_do_not_repick_or_finish_original():
    controller, driver, results = setup_controller()
    original = goal()
    assert controller.deliver(original)["accepted"]
    original["color"] = "blue"
    assert controller.deliver(goal())["reason"] == "DUPLICATE"
    assert controller.deliver(goal(column=COLUMNS[1]))["reason"] == "EXECUTION_ID_CONFLICT"
    assert controller.deliver(goal("delivery-2"))["reason"] == "BUSY"
    assert len(driver.calls) == 1 and results == []
    finish(driver, "delivery-1")
    assert controller.deliver(goal())["reason"] == "DUPLICATE"
    assert controller.deliver(goal(column=COLUMNS[1]))["reason"] == "EXECUTION_ID_CONFLICT"
    assert len(driver.calls) == 3 and len(results) == 1


def test_duplicate_out_of_order_and_old_confirmations_do_not_consume_or_progress_twice():
    controller, driver, results = setup_controller()
    controller.deliver(goal())
    assert not controller.on_confirmation("delivery-1", "observe")
    assert not controller.on_confirmation("other", "pick")
    assert supply(controller, COLUMNS[0])["next_slot"] == 1 and len(driver.calls) == 1
    for operation in ("pick", "place", "observe"):
        assert driver.confirm("delivery-1", operation)
        assert not driver.confirm("delivery-1", operation)
    assert len(results) == 1 and len(driver.calls) == 3
    controller.deliver(goal("delivery-2"))
    for operation in ("pick", "place", "observe"):
        assert not driver.confirm("delivery-1", operation)
    assert not controller.state["ready_at_observe"] and not driver.ready_at_observe
    assert len(driver.calls) == 4 and supply(controller, COLUMNS[0])["next_slot"] == 2
    finish(driver, "delivery-2")
    assert [result["execution_id"] for result in results] == ["delivery-1", "delivery-2"]
    assert supply(controller, COLUMNS[0])["next_slot"] == 3


@pytest.mark.parametrize("column", COLUMNS)
def test_six_slots_then_refill_only_that_row_without_reusing_execution_ids(column):
    controller, driver, results = setup_controller()
    for slot in range(1, 7):
        identity = f"delivery-{slot}"
        assert controller.deliver(goal(identity, column))["accepted"]
        assert driver.calls[-1][1]["slot"] == slot
        finish(driver, identity)
    assert supply(controller, column) == dict(brick_type=column[0], color=column[1],
                                              next_slot=None, needs_refill=True)
    assert controller.deliver(goal("overflow", column))["reason"] == "NEEDS_REFILL"
    assert len(driver.calls) == 18 and len(results) == 6
    untouched = next(other for other in COLUMNS if other != column)
    assert controller.supply_refilled(*untouched)["reason"] == "REFILL_NOT_REQUIRED"
    assert controller.supply_refilled(*column)["accepted"]
    assert controller.deliver(goal("delivery-6", column))["reason"] == "DUPLICATE"
    assert controller.deliver(goal("after-refill", column))["accepted"]
    assert driver.calls[-1][1]["slot"] == 1
    assert all(supply(controller, other)["next_slot"] == 1 for other in COLUMNS if other != column)


def test_day4_plan_fixture_uses_independent_supply_rows_without_reset_between_goals():
    controller, driver, results = setup_controller()
    for step in DAY4["initial_plan"]["steps"]:
        after = step["after"]
        controller.deliver(goal(step["step_id"], (after["brick_type"], after["color"])))
        finish(driver, step["step_id"])
    picks = [request for operation, request in driver.calls if operation == "pick"]
    assert [(pick["brick_type"], pick["color"], pick["slot"]) for pick in picks] == [
        ("2x2x1", "yellow", 1), ("2x2x1", "yellow", 2), ("2x3x1", "blue", 1)]
    assert len(results) == 3


def test_injected_config_is_frozen_and_smaller_fake_slot_count_is_observed():
    config = deepcopy(CONFIG)
    config.update(slot_count=2, place_point="fake-alternate-place", observe_point="fake-alternate-observe")
    config["supply_rows"][0]["supply_point"] = "fake-alternate-supply"
    controller, driver, results = setup_controller(config)
    config.update(slot_count=6, place_point="changed", observe_point="changed")
    config["supply_rows"][0]["supply_point"] = "changed"
    for identity in ("one", "two"):
        controller.deliver(goal(identity))
        finish(driver, identity)
    assert [request["point"] for _, request in driver.calls] == [
        "fake-alternate-supply", "fake-alternate-place", "fake-alternate-observe"]*2
    assert supply(controller, COLUMNS[0])["needs_refill"]
    snapshot = controller.state
    snapshot["supply"][0]["next_slot"] = 6
    assert supply(controller, COLUMNS[0])["next_slot"] is None
    assert len(results) == 2


def test_unready_controller_and_refill_during_delivery_do_not_issue_commands_or_reset_slots():
    controller, driver, results = setup_controller(ready=False)
    assert controller.deliver(goal())["reason"] == "NOT_READY_AT_OBSERVE"
    assert driver.calls == [] and results == []
    driver.ready_at_observe = True  # 모의 준비 확인이며 실제 장치 증거가 아니다.
    controller.deliver(goal())
    driver.confirm("delivery-1", "pick")
    assert controller.supply_refilled(*COLUMNS[0])["reason"] == "NOT_READY_AT_OBSERVE"
    assert supply(controller, COLUMNS[0])["next_slot"] == 2


@pytest.mark.parametrize("change", ["missing", "extra", "id", "color", "brick_type"])
def test_invalid_goals_do_not_start_or_consume(change):
    controller, driver, results = setup_controller()
    request = goal()
    if change == "missing":
        del request["execution_id"]
    elif change == "extra":
        request["slot"] = 1
    elif change == "id":
        request["execution_id"] = ""
    else:
        request[change] = "unsupported"
    with pytest.raises(ValueError):
        controller.deliver(request)
    assert driver.calls == [] and results == []
    assert all(row["next_slot"] == 1 for row in controller.state["supply"])


def stop_controller(controller, driver, block_state, *, request_id="stop-1"):
    identity = controller.state["active_execution"]["execution_id"] if controller.state["active_execution"] else None
    assert controller.stop(dict(request_id=request_id, execution_id=identity))["accepted"]
    assert driver.confirm_stop(request_id, stopped=True, execution_ended=True,
                               block_state_known=True, block_state=block_state)


def resume_goal(previous="delivery-1", identity="resumed", *, delivery=True):
    return dict(execution_id=identity, previous_execution_id=previous,
                goal=goal(identity) if delivery else None)


@pytest.mark.parametrize("completed,block_state,remaining", [
    ([], "UNPICKED", ["pick", "place", "observe"]),
    (["pick"], "HOLDING", ["place", "observe"]),
    (["pick", "place"], "RELEASED", ["observe"]),
])
def test_resume_uses_new_id_and_confirmed_block_state_without_extra_consumption(completed, block_state, remaining):
    controller, driver, results = setup_controller()
    controller.deliver(goal())
    for operation in completed:
        driver.confirm("delivery-1", operation)
    stop_controller(controller, driver, block_state)
    before = len(driver.calls)
    assert not controller.deliver(goal("unexpected"))["accepted"]
    assert controller.resume(resume_goal())["accepted"]
    assert driver.calls[-1][0] == remaining[0]
    for operation in remaining:
        assert driver.confirm("resumed", operation)
    assert [operation for operation, _ in driver.calls[before:]] == remaining
    assert supply(controller, COLUMNS[0])["next_slot"] == 2
    assert results == [dict(execution_id="resumed", success=True, reason=None)]
    for operation, payload in driver.calls[:before]:
        if operation != "stop":
            assert not driver.confirm(payload["execution_id"], operation)
    assert supply(controller, COLUMNS[0])["next_slot"] == 2 and len(results) == 1


@pytest.mark.parametrize("flags,state", [
    ((False, True, True), "UNPICKED"), ((True, False, True), "UNPICKED"),
    ((True, True, False), "UNPICKED"), ((True, True, True), "UNKNOWN"),
])
def test_stop_ack_or_incomplete_evidence_blocks_callbacks_and_resume(flags, state):
    controller, driver, results = setup_controller()
    controller.deliver(goal())
    controller.stop(dict(request_id="stop-1", execution_id="delivery-1"))
    assert not driver.confirm_stop("stop-1", stopped=flags[0], execution_ended=flags[1],
                                   block_state_known=flags[2], block_state=state)
    assert not controller.resume(resume_goal())["accepted"]
    assert not driver.confirm("delivery-1", "pick")
    assert supply(controller, COLUMNS[0])["next_slot"] == 1 and results == []
    assert len(driver.calls) == 2
    assert driver.confirm_stop("stop-1", stopped=True, execution_ended=True,
                               block_state_known=True, block_state="UNPICKED")
    assert controller.resume(resume_goal())["accepted"]


def test_stop_holding_proof_consumes_unreported_pick_once_and_conflicting_proof_holds():
    controller, driver, results = setup_controller()
    controller.deliver(goal())
    stop_controller(controller, driver, "HOLDING")
    assert supply(controller, COLUMNS[0])["next_slot"] == 2
    assert not driver.confirm_stop("stop-1", stopped=True, execution_ended=True,
                                   block_state_known=True, block_state="HOLDING")
    assert controller.resume(resume_goal())["accepted"]
    assert driver.calls[-1][0] == "place"
    assert not driver.confirm("delivery-1", "pick")
    controller.stop(dict(request_id="stop-2", execution_id="resumed"))
    assert not driver.confirm_stop("stop-2", stopped=True, execution_ended=True,
                                   block_state_known=True, block_state="UNPICKED")
    assert not controller.resume(resume_goal("resumed", "third"))["accepted"]
    assert results == [] and supply(controller, COLUMNS[0])["next_slot"] == 2


@pytest.mark.parametrize("operation,completed,block_state,slot", [
    ("pick", [], "UNPICKED", 1), ("place", ["pick"], "HOLDING", 2),
    ("observe", ["pick", "place"], "RELEASED", 2),
])
@pytest.mark.parametrize("reason", ["fixture failure", "TIMEOUT"])
def test_failure_or_timeout_emits_once_preserves_consumption_and_requires_manual_cleanup(operation, completed, block_state, slot, reason):
    controller, driver, results = setup_controller()
    controller.deliver(goal())
    for done in completed:
        driver.confirm("delivery-1", done)
    before = len(driver.calls)
    assert driver.fail("delivery-1", operation, reason)
    assert not driver.fail("delivery-1", operation, reason)
    assert not driver.confirm("delivery-1", operation)
    assert results == [dict(execution_id="delivery-1", success=False, reason=reason)]
    assert supply(controller, COLUMNS[0])["next_slot"] == slot
    assert not controller.deliver(goal("next"))["accepted"]
    assert len(driver.calls) == before
    stop_controller(controller, driver, block_state)
    assert not controller.resume(resume_goal())["accepted"]


def test_stop_without_delivery_resumes_only_observe_and_never_picks():
    controller, driver, results = setup_controller()
    stop_controller(controller, driver, "UNPICKED")
    assert controller.resume(resume_goal(None, delivery=False))["accepted"]
    assert driver.calls[-1][0] == "observe"
    driver.confirm("resumed", "observe")
    assert all(row["next_slot"] == 1 for row in controller.state["supply"])
    assert len(results) == 1


def test_driver_call_exception_is_reported_as_failure_without_retry(monkeypatch):
    controller, driver, results = setup_controller()
    def fail_call(*args, **kwargs):
        raise OSError("fixture transport down")
    monkeypatch.setattr(driver, "request", fail_call)
    assert controller.deliver(goal())["accepted"]
    assert len(results) == 1 and not results[0]["success"]
    assert "fixture transport down" in results[0]["reason"]
    assert supply(controller, COLUMNS[0])["next_slot"] == 1
    assert not controller.deliver(goal("next"))["accepted"]


def test_return_only_resume_can_be_stopped_and_resumed_again_without_supply_effect():
    controller, driver, results = setup_controller()
    stop_controller(controller, driver, "UNPICKED")
    assert controller.resume(resume_goal(None, delivery=False))["accepted"]
    stop_controller(controller, driver, "RELEASED", request_id="stop-2")
    assert controller.resume(resume_goal("resumed", "again", delivery=False))["accepted"]
    assert not driver.confirm("resumed", "observe")
    assert not driver.confirm_stop("stop-1", stopped=True, execution_ended=True,
                                   block_state_known=True, block_state="UNPICKED")
    assert driver.confirm("again", "observe")
    assert all(row["next_slot"] == 1 for row in controller.state["supply"])
    assert results == [dict(execution_id="again", success=True, reason=None)]


def test_invalid_failure_reason_does_not_replace_valid_pending_confirmation():
    controller, driver, results = setup_controller()
    controller.deliver(goal())
    with pytest.raises(ValueError):
        driver.fail("delivery-1", "pick", "")
    assert driver.confirm("delivery-1", "pick") and driver.block_state == "HOLDING"
    assert controller.state["fault"] is None and results == []


def test_ready_point_with_holding_or_unknown_block_state_cannot_start_new_pick():
    controller, driver, results = setup_controller()
    for state in ("HOLDING", "UNKNOWN"):
        driver.block_state = state
        assert controller.deliver(goal())["reason"] == "NOT_READY_AT_OBSERVE"
        assert not controller.state["ready_at_observe"]
    assert driver.calls == [] and results == []
