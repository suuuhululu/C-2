from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import robot_trial as trial


CONFIG_PATH = Path(__file__).resolve().parents[2] / "interfaces/robot_trial.json"
CONFIG = json.loads(CONFIG_PATH.read_text())
COMMANDS = [
    ("joint", "start", [0.] * 6, None),
    ("initial_approach", "approach", [1.] * 6, 2),
    ("grip_close", "close", None, 2),
    ("line_local", "lift", [2.] * 6, 2),
    ("line_transit", "transfer", [3.] * 6, 2),
    ("grip_open", "release", None, 2),
    ("joint", "observe", CONFIG["observe_posj"], None),
]


def test_json_numeric_settings_become_ros_floats_without_changing_values(tmp_path):
    original = deepcopy(CONFIG)
    original["observe_posj"][0] = 0
    original["observe_posx"][0] = 400
    path = tmp_path / "config.json"
    path.write_text(json.dumps(original))
    config = trial.load_trial_config(path)
    assert config == original
    assert type(config["slot"]) is int
    for field, number in original["settings"].items():
        if type(number) in (int, float):
            assert type(config["settings"][field]) is float
    for field in ("observe_posj", "observe_posx"):
        assert all(type(number) is float for number in config[field])
    assert type(original["settings"]["joint_speed"]) is int


def test_blue_supply_uses_recorded_endpoints_and_only_selected_slot():
    config = trial.load_trial_config(CONFIG_PATH.parent / "robot_trial_blue5.json")
    source, settings, commands = trial.prepare_plan(config)
    measured = json.loads(Path(config["pick_line"]["measurements_path"]).read_text())["lines"]["blue_4"]
    assert source.START == measured["start"] and source.END == measured["end"]
    target = next(target for kind, label, target, slot in commands if kind == "line_local")
    assert target[:3] == pytest.approx(measured["blocks"][4]["xyz"])
    assert all(trial.math.isfinite(value) for value in target)
    assert sum(kind == "grip_close" for kind, label, target, slot in commands) == 1
    assert {slot for kind, label, target, slot in commands if slot is not None} == {5}
    assert hashlib.sha256(Path(config["source_path"]).read_bytes()).hexdigest() == config["source_sha256"]


@pytest.mark.parametrize("change", ["endpoint", "hash"])
def test_changed_measurements_never_become_a_motion_plan(change):
    config = trial.load_trial_config(CONFIG_PATH.parent / "robot_trial_blue5.json")
    if change == "endpoint":
        config["pick_line"]["start"][0] += 1
    else:
        config["pick_line"]["measurements_sha256"] = "changed"
    with pytest.raises(ValueError):
        trial.prepare_plan(config)


class Robot:
    def __init__(self, settings=None):
        self.args = SimpleNamespace(**CONFIG["settings"])
        self.calls = []
        self.facts = dict(robot_state=1, status=0, robot_mode=1)

    def call(self, path, kind, **kwargs):
        self.calls.append((path, kwargs))
        values = dict(**self.facts, info=self.args.tcp if "tcp/" in path else self.args.tool,
                      conv_posx=CONFIG["observe_posx"], pos=CONFIG["observe_posj"])
        return SimpleNamespace(**values)

    def movej(self, target):
        self.calls.append(("joint", target))

    def line(self, target, speed):
        self.calls.append(("line", (target, speed)))

    def verify_setup(self):
        return 0

    def check_plan(self, commands, sol):
        return [1.] * 6

    def stop(self):
        self.calls.append(("stop", None))

    def close(self):
        self.calls.append(("close", None))


class Gripper:
    def __init__(self, settings=None):
        self.status = 0
        self.width = 60.
        self.calls = []
        self.hold_status = 2

    def read(self, register):
        self.calls.append(("read", register))
        return self.status if register == 268 else self.width * 10

    def move(self, width, require_grip=False):
        self.calls.append(("move", width, require_grip))
        self.status = self.hold_status if require_grip else 0

    def close(self):
        self.calls.append(("close",))


@pytest.mark.parametrize("field,value", [
    ("mode", None), ("mode", "FAKE"), ("slot", True), ("slot", 0), ("slot", 7),
    ("observe_posj", None), ("observe_posx", [1] * 5), ("observe_posj", [float("nan")] * 6),
])
def test_invalid_input_never_constructs_a_device(tmp_path, field, value):
    config = deepcopy(CONFIG)
    config[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        trial.load_trial_config(path)


def test_missing_mode_and_invalid_settings_rejected(tmp_path):
    config = deepcopy(CONFIG)
    del config["mode"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        trial.load_trial_config(path)
    config = deepcopy(CONFIG)
    config["settings"]["joint_speed"] = 0
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        trial.load_trial_config(path)


def test_bounds_the_source_sequence_to_one_slot_without_new_route(tmp_path):
    path = tmp_path / "taught.py"
    path.write_text('''PLACE = [0.] * 6
def picks(): return [PLACE]
def plan(args):
    return [('joint', 'start', [1.] * 6, None),
            ('grip_close', 'selected', None, args.start_block),
            ('line_local', 'lift', [2.] * 6, args.start_block),
            ('grip_open', 'place', None, args.start_block),
            ('clear_place', 'operator', None, args.start_block),
            ('grip_close', 'next slot', None, args.start_block + 1),
            ('joint', 'home', [3.] * 6, None)]
''')
    config = deepcopy(CONFIG)
    config.update(source_path=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    _, settings, commands = trial.prepare_plan(config)
    assert settings.start_block == 2
    assert [step[3] for step in commands] == [None, 2, 2, 2, None, None]
    assert commands[0][2] == [1.] * 6 and commands[-2][2] == [3.] * 6
    assert commands[-1][2] == CONFIG["observe_posj"]
    path.write_text("raise AssertionError('changed source must never execute')")
    with pytest.raises(ValueError, match="changed source"):
        trial.prepare_plan(config)


def test_normal_commands_pick_once_after_lift_return_then_succeed():
    robot, gripper, events = Robot(), Gripper(), []
    trial.run_commands(COMMANDS, robot, gripper, [1.] * 6, CONFIG,
                       lambda event, payload: events.append((event, payload)))
    assert [c for c in gripper.calls if c[0] == "move"] == [("move", 2, True), ("move", 60, False)]
    assert [payload for event, payload in events if event == "ROBOT_PICK_CONFIRMED"] == [dict(slot=2, next_slot=3)]
    assert events[-1][0] == "ROBOT_RETURN_CONFIRMED"
    assert [c for c in robot.calls if c[0] == "line"] == [
        ("line", ([2.] * 6, 40)), ("line", ([3.] * 6, 80))]


def test_no_hold_after_lift_never_consumes_or_places():
    robot, gripper, events = Robot(), Gripper(), []
    gripper.hold_status = 0
    with pytest.raises(RuntimeError, match="PICK_HOLD_UNCONFIRMED"):
        trial.run_commands(COMMANDS, robot, gripper, [1.] * 6, CONFIG,
                           lambda event, payload: events.append(event))
    assert "ROBOT_PICK_CONFIRMED" not in events
    assert len([c for c in robot.calls if c[0] == "line"]) == 1
    assert [c for c in gripper.calls if c[0] == "move"] == [("move", 2, True)]


@pytest.mark.parametrize("failure", ["place", "return"])
def test_failure_after_confirmed_pick_preserves_consumption_and_has_no_return_success(monkeypatch, failure):
    robot, gripper, events = Robot(), Gripper(), []
    if failure == "place":
        original = gripper.move

        def failed_place(width, require_grip=False):
            if not require_grip:
                raise TimeoutError("release timeout")
            original(width, require_grip=require_grip)

        monkeypatch.setattr(gripper, "move", failed_place)
    else:
        original = robot.movej

        def failed_return(target):
            if target == CONFIG["observe_posj"]:
                raise TimeoutError("return timeout")
            original(target)

        monkeypatch.setattr(robot, "movej", failed_return)
    with pytest.raises(TimeoutError):
        trial.run_commands(COMMANDS, robot, gripper, [1.] * 6, CONFIG,
                           lambda event, payload: events.append((event, payload)))
    assert len([event for event, _ in events if event == "ROBOT_PICK_CONFIRMED"]) == 1
    assert "ROBOT_RETURN_CONFIRMED" not in [event for event, _ in events]
    assert len([c for c in gripper.calls if c[0] == "move" and c[2]]) == 1


@pytest.mark.parametrize("field,value", [("robot_state", 2), ("status", 2), ("robot_mode", 0)])
def test_read_only_probe_rejects_busy_or_wrong_mode_without_motion(field, value):
    robot, gripper = Robot(), Gripper()
    robot.facts[field] = value
    with pytest.raises(RuntimeError, match="ROBOT_NOT_IDLE"):
        trial.read_status(robot, gripper, CONFIG)
    assert all(path not in ("joint", "line", "stop") for path, _ in robot.calls)
    assert all(call[0] == "read" for call in gripper.calls)


def test_wrong_tcp_or_held_gripper_is_not_ready():
    robot, gripper = Robot(), Gripper()
    config = deepcopy(CONFIG)
    config["settings"]["tcp"] = "different"
    with pytest.raises(RuntimeError, match="TCP_TOOL_MISMATCH"):
        trial.read_status(robot, gripper, config)
    gripper.status = 2
    with pytest.raises(RuntimeError, match="GRIPPER_NOT_EMPTY_IDLE"):
        trial.read_status(robot, gripper, CONFIG)


def test_observe_mismatch_cannot_be_a_success():
    robot = Robot()
    config = deepcopy(CONFIG)
    config["observe_posx"][0] += 100
    with pytest.raises(RuntimeError, match="OBSERVE_POSE_MISMATCH"):
        trial.verify_observe_pose(robot, config, config["observe_posj"])


@pytest.mark.parametrize("action", ["offline", "check", "execute", "unconfirmed", "failure"])
def test_cli_mode_logging_and_no_automatic_retries(tmp_path, monkeypatch, action):
    config = deepcopy(CONFIG)
    config["confirmations"] = {key: action != "unconfirmed" for key in config["confirmations"]}
    robot, gripper = Robot(), Gripper()
    created = []

    def make_robot(settings):
        created.append("robot")
        return robot

    source = SimpleNamespace(RowRobot=make_robot, Gripper=lambda settings: gripper)
    monkeypatch.setattr(trial, "load_trial_config", lambda path: config)
    monkeypatch.setattr(trial, "prepare_plan", lambda value: (source, robot.args, COMMANDS))
    monkeypatch.setattr(trial, "check_motion_messages", lambda source, settings, commands, initial: 4)
    if action == "failure":
        gripper.hold_status = 0
    argv = ["--config", "given.json", "--log-dir", str(tmp_path)]
    if action != "offline":
        argv.append("--check" if action == "check" else "--execute")
    assert trial.main(argv) == (1 if action in ("unconfirmed", "failure") else 0)
    if action in ("offline", "unconfirmed"):
        assert created == []
    if action == "check":
        assert all(c[0] not in ("joint", "line", "stop") for c in robot.calls)
        assert all(c[0] != "move" for c in gripper.calls)
    if action == "failure":
        assert len([c for c in robot.calls if c[0] == "stop"]) == 1
        assert len([c for c in gripper.calls if c[0] == "move"]) == 1
    logs = list(tmp_path.glob("*.jsonl"))
    if action == "execute":
        records = [json.loads(line) for line in logs[0].read_text().splitlines()]
        assert records[-1]["payload"]["success"] is True
        assert len({r["execution_id"] for r in records}) == 1
        assert "STEP_CONFIRMED" not in [r["event"] for r in records]


def test_log_failure_prevents_next_command():
    robot, gripper = Robot(), Gripper()

    def failed_log(event, payload):
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        trial.run_commands(COMMANDS, robot, gripper, [1.] * 6, CONFIG, failed_log)
    assert robot.calls == [] and gripper.calls == []
