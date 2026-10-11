from copy import deepcopy
import json

import pytest

from app.backend import Backend
from app.fake_robot_driver import FakeRobotDriver
from app.jsonl_log import JsonlLog
from app.robot_controller import RobotController
from app.snapshot import make_snapshot
from test_backend import A, B, C, RA, RB, RC, FIXTURES, FakePorts, observation
from test_robot_controller import CONFIG


def connected(tmp_path, *, config=None, record=None, loader=None):
    ports = FakePorts()
    backend = Backend(ports, mode="FAKE", record=JsonlLog(tmp_path) if record is None else record)
    driver = FakeRobotDriver(ready_at_observe=True)
    controller = RobotController(CONFIG if config is None else config, driver, backend.on_robot_result,
        on_stopped=backend.on_stopped, on_event=backend.on_robot_event)
    backend.connect_robot(controller, config_loader=loader)
    assert backend.command(dict(command="START"))["accepted"]
    backend.on_plan(ports.calls("planner")[-1]["request_id"], FIXTURES["design"], FIXTURES["initial_plan"])
    backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    return backend, driver, controller, ports


def returned(backend, driver):
    identity = backend.state["execution_id"]
    for operation in ("pick", "place", "observe"):
        assert driver.confirm(identity, operation)
    return identity


def assembled(backend, blocks, regions):
    observed = observation(backend, blocks, regions)
    backend.on_place(observed["check_id"], 0, "EMPTY")
    backend.on_observation(observed)
    return observed


def stop(backend, driver, block_state):
    assert backend.command(dict(command="STOP", job_id=backend.state["job_id"]))["accepted"]
    assert driver.confirm_stop(backend.state["stop_request"], stopped=True, execution_ended=True,
                               block_state_known=True, block_state=block_state)


def records(tmp_path, job):
    return [json.loads(line) for line in (tmp_path / f"{job}.jsonl").read_text().splitlines()]


def test_normal_three_steps_join_controller_slots_backend_current_snapshot_and_jsonl(tmp_path):
    backend, driver, controller, ports = connected(tmp_path)
    for index, (blocks, regions) in enumerate([([A], [RA]), ([A, B], [RA, RB]), ([C], [RC])]):
        returned(backend, driver)
        assert backend.state["current"]["current_revision"] == index
        assert make_snapshot(backend.state)["progress"]["completed"] == index
        assembled(backend, blocks, regions)
    snapshot = make_snapshot(backend.state)
    assert snapshot["workflow_status"] == "COMPLETE" and snapshot["progress"] == dict(completed=3, total=3)
    assert backend.state["current"]["blocks"] == [A, B, C]
    assert [row["next_slot"] for row in snapshot["monitor"]["supply"]] == [3, 1, 1, 2, 1]
    assert len(driver.calls) == 9 and ports.calls("robot.deliver") == []
    events = records(tmp_path, backend.state["job_id"])
    for event in ("ROBOT_PICK_CONFIRMED", "ROBOT_PLACE_CONFIRMED", "ROBOT_OBSERVE_CONFIRMED", "DELIVERY_RESULT", "STEP_CONFIRMED"):
        assert sum(row["event"] == event for row in events) == 3
    assert next(row["result"] for row in events if row["event"] == "ROBOT_CONFIG_ADOPTED") == CONFIG
    assert {row["step_id"] for row in events if row["event"] == "ROBOT_PICK_CONFIRMED"} == {"S01", "S02", "S03"}


@pytest.mark.parametrize("status", ["OCCUPIED", "UNOBSERVABLE"])
def test_next_delivery_requires_fresh_empty_even_with_confirmed_step(tmp_path, status):
    backend, driver, _, _ = connected(tmp_path)
    returned(backend, driver)
    frame = observation(backend, [A], [RA])
    backend.on_place(frame["check_id"], 0, status, "hand" if status == "UNOBSERVABLE" else None)
    backend.on_observation(frame)
    assert len(driver.calls) == 3
    assert not backend.on_place(frame["check_id"], 1, "EMPTY")
    assert backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    assert len(driver.calls) == 4


def test_unobservable_and_actual_mismatch_do_not_dispatch_next_robot_pick(tmp_path):
    backend, driver, _, ports = connected(tmp_path)
    returned(backend, driver)
    frame = {**FIXTURES["observed_unobservable"], "check_id":backend.state["active_check"]["check_id"], "observation_seq":0}
    backend.on_observation(frame)
    assert backend.state["current"]["blocks"] == [] and len(driver.calls) == 3
    frame = observation(backend, [{**A, "color":"blue"}], [RA], seq=1)
    backend.on_observation(frame)
    assert backend.state["current"]["blocks"] == [{**A, "color":"blue"}]
    assert backend.state["workflow_status"] == "WAIT_INTENT" and len(ports.calls("hri")) == 1
    assert len(driver.calls) == 3


def test_refill_uses_existing_job_bound_command_and_new_empty_check_before_pick(tmp_path):
    config = {**deepcopy(CONFIG), "slot_count":1}
    backend, driver, controller, _ = connected(tmp_path, config=config)
    returned(backend, driver)
    frame = assembled(backend, [A], [RA])
    assert backend.state["reason"] == "NEEDS_REFILL" and len(driver.calls) == 3
    action = make_snapshot(backend.state)["actions"]["supply_refill"][0]
    assert action == dict(brick_type=A["brick_type"], color=A["color"], visible=True, enabled=True)
    command = dict(command="SUPPLY_REFILLED", job_id="old-job", brick_type=A["brick_type"], color=A["color"])
    assert backend.command(command)["reason"] == "OLD_JOB"
    command["job_id"] = backend.state["job_id"]
    assert backend.command(command)["accepted"]
    assert not backend.command(command)["accepted"]
    assert len(driver.calls) == 3
    assert not backend.on_place(frame["check_id"], 1, "EMPTY")
    backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    assert driver.calls[-1][1]["slot"] == 1 and len(driver.calls) == 4
    events = records(tmp_path, backend.state["job_id"])
    assert sum(row["event"] == "SUPPLY_REFILLED" for row in events) == 1
    assert controller.state["supply"][1]["next_slot"] == 1


@pytest.mark.parametrize("completed,state,remaining", [
    ([], "UNPICKED", ["pick", "place", "observe"]),
    (["pick"], "HOLDING", ["place", "observe"]),
    (["pick", "place"], "RELEASED", ["observe"]),
])
def test_backend_stop_resume_uses_controller_facts_and_ignores_old_requests(tmp_path, completed, state, remaining):
    backend, driver, controller, _ = connected(tmp_path)
    old, job = backend.state["execution_id"], backend.state["job_id"]
    for operation in completed:
        driver.confirm(old, operation)
    stop(backend, driver, state)
    assert make_snapshot(backend.state)["actions"]["resume"]["enabled"]
    assert backend.command(dict(command="RESUME", job_id=job))["accepted"]
    new = backend.state["execution_id"]
    assert new != old and driver.calls[-1][0] == remaining[0]
    old_operations = [operation for operation, payload in driver.calls if payload.get("execution_id") == old]
    for operation in old_operations:
        assert not driver.confirm(old, operation)
    for operation in remaining:
        driver.confirm(new, operation)
    assert backend.state["workflow_status"] == "WAIT_ASSEMBLY"
    assert backend.state["current"]["blocks"] == [] and controller.state["supply"][0]["next_slot"] == 2
    assert backend.state["job_id"] == job


@pytest.mark.parametrize("missing", ["stopped", "execution_ended", "block_state_known"])
def test_incomplete_stop_proof_does_not_enable_backend_resume(tmp_path, missing):
    backend, driver, _, _ = connected(tmp_path)
    backend.command(dict(command="STOP", job_id=backend.state["job_id"]))
    proof = dict(stopped=True, execution_ended=True, block_state_known=True, block_state="UNPICKED")
    proof[missing] = False
    assert not driver.confirm_stop(backend.state["stop_request"], **proof)
    assert backend.state["reason"] == "STOP_UNCONFIRMED"
    assert not backend.command(dict(command="RESUME", job_id=backend.state["job_id"]))["accepted"]
    assert len(driver.calls) == 2


@pytest.mark.parametrize("operation,completed,state", [
    ("pick", [], "UNPICKED"), ("place", ["pick"], "HOLDING"),
    ("observe", ["pick", "place"], "RELEASED"),
])
def test_fault_requires_stop_cleanup_and_explicit_new_start_preserving_old_logs(tmp_path, operation, completed, state):
    backend, driver, controller, ports = connected(tmp_path)
    old, old_job = backend.state["execution_id"], backend.state["job_id"]
    for done in completed:
        driver.confirm(old, done)
    driver.fail(old, operation, "TIMEOUT")
    assert not backend.command(dict(command="START"))["accepted"]
    assert not backend.on_robot_cleanup(old_job)
    stop(backend, driver, state)
    assert not backend.command(dict(command="RESUME", job_id=old_job))["accepted"]
    assert not backend.command(dict(command="STOP", job_id=old_job))["accepted"]
    assert backend.state["stop_request"] is None
    old_supply = controller.state["supply"]
    driver.confirm_cleanup(ready_at_observe=False, gripper_empty=True)
    assert not backend.on_robot_cleanup(old_job)
    driver.confirm_cleanup(ready_at_observe=True, gripper_empty=False)
    assert not backend.on_robot_cleanup(old_job)
    driver.confirm_cleanup(ready_at_observe=True, gripper_empty=True)
    assert not backend.on_robot_cleanup("old-other-job")
    assert backend.on_robot_cleanup(old_job)
    assert not backend.on_robot_cleanup(old_job)
    assert controller.state["supply"] == old_supply and backend.state["fault"] == "TIMEOUT"
    assert backend.command(dict(command="START"))["accepted"]
    assert backend.state["job_id"] != old_job and backend.state["fault"] is None
    assert all(row["next_slot"] == 1 for row in controller.state["supply"])
    before = backend.state
    assert not driver.confirm(old, operation)
    assert backend.state == before and len(ports.calls("planner")) == 2
    assert records(tmp_path, old_job)[-1]["event"] == "ROBOT_CLEANUP_CONFIRMED"


@pytest.mark.parametrize("event", ["ROBOT_PICK_CONFIRMED", "ROBOT_PLACE_CONFIRMED", "ROBOT_OBSERVE_CONFIRMED"])
def test_robot_log_failure_prevents_next_motion_and_preserves_stop_path(tmp_path, event):
    def record(value):
        if value["event"] == event:
            raise OSError("fixture disk full")
    backend, driver, controller, _ = connected(tmp_path, record=record)
    identity = backend.state["execution_id"]
    for operation, logged in (("pick", "ROBOT_PICK_CONFIRMED"), ("place", "ROBOT_PLACE_CONFIRMED"), ("observe", "ROBOT_OBSERVE_CONFIRMED")):
        driver.confirm(identity, operation)
        if logged == event:
            break
    count = len(driver.calls)
    assert "LOG_FAILED" in backend.state["reason"] and controller.state["supply"][0]["next_slot"] == 2
    assert backend.state["current"]["blocks"] == []
    assert backend.command(dict(command="STOP", job_id=backend.state["job_id"]))["accepted"]
    assert len(driver.calls) == count + 1 and driver.calls[-1][0] == "stop"


def test_changed_config_is_adopted_only_on_next_job_and_invalid_config_cannot_reset_state(tmp_path):
    selected = deepcopy(CONFIG)
    backend, driver, controller, _ = connected(tmp_path, loader=lambda:deepcopy(selected))
    selected.update(config_id="next-job", observe_point="fake-other-observe", slot_count=2)
    returned(backend, driver)
    assert driver.calls[-1][1]["point"] == CONFIG["observe_point"]
    assembled(backend, [A], [RA])
    returned(backend, driver); assembled(backend, [A, B], [RA, RB])
    returned(backend, driver); assembled(backend, [C], [RC])
    before = backend.state
    selected["mode"] = "REAL"
    assert "ROBOT_CONFIG_INVALID" in backend.command(dict(command="START"))["reason"]
    assert backend.state == before
    selected["mode"] = "FAKE"
    assert backend.command(dict(command="START"))["accepted"]
    assert controller.configuration == selected
    assert next(row["result"] for row in records(tmp_path, backend.state["job_id"])
                if row["event"] == "ROBOT_CONFIG_ADOPTED")["config_id"] == "next-job"


def test_next_step_stop_before_pick_does_not_reuse_previous_released_block_state(tmp_path):
    backend, driver, controller, _ = connected(tmp_path)
    returned(backend, driver)
    assembled(backend, [A], [RA])
    assert driver.block_state == "UNPICKED"
    stop(backend, driver, driver.block_state)
    assert backend.command(dict(command="RESUME", job_id=backend.state["job_id"]))["accepted"]
    assert driver.calls[-1][0] == "pick" and driver.calls[-1][1]["slot"] == 2
    returned(backend, driver)
    assert controller.state["supply"][0]["next_slot"] == 3
    assert backend.state["current"]["blocks"] == [A]
    assert len(backend.state["context"]["confirmed_steps"]) == 1
