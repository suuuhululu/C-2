from copy import deepcopy
import json
from uuid import uuid4

import pytest

from app import robot_pause, robot_trial
from test_robot_trial import Robot, Gripper, CONFIG, COMMANDS


def events(index, *, done=False, picked=False, released=False):
    rows = [dict(event="ROBOT_TRIAL_COMMAND", payload=dict(command_index=index))]
    if done:
        rows.append(dict(event="ROBOT_TRIAL_COMMAND_DONE", payload=dict(command_index=index)))
    if picked:
        rows.append(dict(event="ROBOT_PICK_CONFIRMED", payload=dict(slot=2, next_slot=3)))
    if released:
        rows.append(dict(event="ROBOT_RELEASE_CONFIRMED", payload=dict(slot=2)))
    return rows


@pytest.mark.parametrize("index,done,picked,released,status,state,start", [
    (0, False, False, False, 0, "UNPICKED", 0),
    (2, False, False, False, 0, "UNPICKED", 0),
    (2, True, False, False, 2, "HOLDING", 3),
    (3, False, True, False, 2, "HOLDING", 3),
    (4, True, True, False, 2, "HOLDING", 5),
    (5, True, True, True, 0, "RELEASED", 6),
    (5, False, True, True, 0, "RELEASED", 6),
    (6, False, True, True, 0, "RELEASED", 6),
    (6, True, True, True, 0, "RELEASED", 7),
])
def test_checkpoint_uses_real_block_status_and_existing_command_progress(index, done, picked, released, status, state, start):
    rows = events(index, done=done, picked=picked, released=released)
    before = deepcopy(rows)
    result = robot_pause.resume_checkpoint(COMMANDS, rows, status)
    assert result["block_state"] == state and result["command_index"] == start
    assert result["consumed"] == (state != "UNPICKED") and rows == before


@pytest.mark.parametrize("rows,status", [
    (events(3, picked=True), 0),  # 확인된 집기를 빈 그리퍼로 되돌리지 않음.
    (events(0), 2), (events(5, picked=True), 0),
    (events(5, picked=True, released=True), 2), (events(0), 1),
])
def test_unknown_block_state_cannot_choose_a_recovery_motion(rows, status):
    with pytest.raises(RuntimeError, match="UNKNOWN"):
        robot_pause.resume_checkpoint(COMMANDS, rows, status)


def test_repeated_stop_before_first_resumed_command_preserves_confirmed_checkpoint():
    rows = [dict(event="ROBOT_RESUME_CHECKPOINT", payload=dict(command_index=4)),
            dict(event="ROBOT_PICK_CONFIRMED", payload=dict(slot=2))]
    assert robot_pause.resume_checkpoint(COMMANDS, rows, 2)["command_index"] == 4


@pytest.mark.parametrize("state,start", [("UNPICKED", 0), ("HOLDING", 3), ("RELEASED", 6)])
def test_resumed_commands_never_repeat_confirmed_pick_or_release(state, start):
    robot, gripper, recorded = Robot(), Gripper(), []
    gripper.status = 2 if state == "HOLDING" else 0
    resume = dict(consumed=state != "UNPICKED", released=state == "RELEASED", command_index=start)
    robot_trial.run_commands(COMMANDS, robot, gripper, [1.] * 6, CONFIG,
        lambda name, value: recorded.append((name, value)), resume=resume)
    closes = [c for c in gripper.calls if c[0] == "move" and c[2]]
    opens = [c for c in gripper.calls if c[0] == "move" and not c[2]]
    assert len(closes) == (1 if state == "UNPICKED" else 0)
    assert len(opens) == (0 if state == "RELEASED" else 1)
    assert recorded[-1][0] == "ROBOT_RETURN_CONFIRMED"


def test_stop_marker_blocks_every_following_command_without_fake_return_success():
    robot, gripper, recorded = Robot(), Gripper(), []
    def record(name, value):
        recorded.append(name)
    def cancelled():
        return any(call[0] == "line" for call in robot.calls)
    with pytest.raises(robot_trial.TrialPaused):
        robot_trial.run_commands(COMMANDS, robot, gripper, [1.] * 6, CONFIG, record, cancelled=cancelled)
    assert len([c for c in robot.calls if c[0] == "line"]) == 1
    assert len([c for c in gripper.calls if c[0] == "move"]) == 1
    assert "ROBOT_RETURN_CONFIRMED" not in recorded


@pytest.mark.parametrize("action,failed", [("stop", False), ("stop", True), ("probe", False), ("probe", True)])
def test_pause_cli_stop_ack_is_separate_from_read_only_stopped_probe(tmp_path, monkeypatch, action, failed):
    from types import SimpleNamespace
    robot, gripper = Robot(), Gripper()
    if failed:
        if action == "stop":
            def reject(path, kind, **fields):
                raise RuntimeError("STOP_SERVICE_FAILED")
            robot.call = reject
        else:
            robot.facts["status"] = 1
    source = SimpleNamespace(RowRobot=lambda settings: robot, Gripper=lambda settings: gripper)
    monkeypatch.setattr(robot_pause, "load_trial_config", lambda path: CONFIG)
    monkeypatch.setattr(robot_pause, "prepare_plan", lambda value: (source, robot.args, COMMANDS))
    identity = str(uuid4())
    result = robot_pause.main(["--config", "given", "--request-id", identity, "--log-dir", str(tmp_path), f"--{action}"])
    assert result == (1 if failed else 0)
    records = [json.loads(l) for l in (tmp_path / f"{identity}.jsonl").read_text().splitlines()]
    assert records[-1]["event"] == ("ROBOT_STOP_FAILED" if failed else "ROBOT_STOP_ACK" if action == "stop" else "ROBOT_STOP_PROBE")
    assert not any(c[0] in ("joint", "line") for c in robot.calls)
    assert not any(c[0] == "move" for c in gripper.calls)
    if action == "probe":
        assert all(path != "motion/move_stop" for path, fields in robot.calls)
