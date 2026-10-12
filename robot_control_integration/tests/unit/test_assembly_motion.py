"""합성 비접촉 실행 계약 검사. 실제 로봇·물리 안전 검증을 대신하지 않는다."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.assembly_motion import CONFIRMATIONS, checked_sample, prepare_motion, run_noncontact
from scripts.assembly_noncontact_trial import main


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = json.loads((ROOT/"interfaces/assembly_noncontact_trial.json").read_text())


def configuration():
    data = deepcopy(TEMPLATE)
    data.update(mode="FAKE", start_posx=[1, 2, 100, 0, 180, 0],
                waypoints=[[11, 2, 100, 0, 180, 0], [11, 12, 100, 0, 180, 0]],
                velocity=[1, 1], acceleration=[1, 1])
    data["connection"]["ros_domain_id"] = 0
    data["timing"] = dict(service_timeout_s=.01, sample_max_duration_s=.05, poll_interval_s=.01,
                          motion_timeout_s=1, stop_timeout_s=.1, hold_s=.02)
    data["limits"] = dict(position_tolerance_mm=.01, orientation_tolerance_deg=.01,
                          linear_still_mm_s=.01, angular_still_deg_s=.01, force_delta_n=5,
                          moment_delta_nm=.5, path_min_clearance_mm=20)
    data["confirmations"] = dict.fromkeys(CONFIRMATIONS, True)
    return data


class Clock:
    def __init__(self):
        self.time = 1000.

    def now(self):
        return self.time

    def sleep(self, seconds):
        self.time += seconds


class FakeDriver:
    def __init__(self, config):
        self.mode, self.config = config["mode"], config
        self.pos = config["start_posx"].copy()
        self.moves, self.checks, self.samples, self.stops = [], [], 0, 0
        self.pending, self.busy_samples, self.closed = None, 0, False
        self.stuck, self.stop_works, self.move_error = False, True, False
        self.modify = lambda sample: None

    def motion_feedback(self):
        return dict(posx=self.pos.copy(), motion_status=2 if self.pending else 0,
                    velx=[1, 0, 0, 0, 0, 0] if self.pending else [0]*6, query_duration_s=.001)

    def sample(self):
        self.samples += 1
        if self.pending and not self.stuck and self.busy_samples == 1:
            self.pos, self.pending = self.pending, None
        sample = self.motion_feedback()
        if self.pending:
            self.busy_samples += 1
        sample.update(robot_state=2 if self.pending else 1, robot_mode=1, drl_state=3,
                      tcp=self.config["connection"]["tcp"], tool=self.config["connection"]["tool"],
                      wrench=[0]*6, gripper_status=2, gripper_width_mm=32)
        self.modify(sample)
        return sample

    def check_pose(self, pose):
        self.checks.append(pose)
        return pose.copy()

    def move_line_async(self, pose, velocity, acceleration):
        self.moves.append(pose.copy())
        self.pending, self.busy_samples = pose.copy(), 0
        if self.move_error:
            raise TimeoutError("move acknowledgement timeout")

    def stop(self):
        self.stops += 1
        if self.stop_works:
            self.pending = None

    def close(self):
        self.closed = True


def run(driver=None, *, record=None, cancelled=lambda: False):
    plan = prepare_motion(configuration())
    driver = FakeDriver(plan["config"]) if driver is None else driver
    events, clock = [], Clock()
    result = run_noncontact(driver, plan, lambda event, data: events.append((event, data))
        if record is None else record(event, data), cancelled=cancelled, now=clock.now, sleep=clock.sleep)
    return result, driver, events


def test_approach_hold_reverse_route_and_return_are_confirmed_without_assembly_or_grip_commands():
    result, driver, events = run()
    assert result["status"] == "NONCONTACT_TRIAL_COMPLETE" and result["returned_to_start"]
    assert result["assembled"] is False and result["gripper_commands"] == 0
    c = configuration()
    assert driver.moves == c["waypoints"] + [c["waypoints"][0], c["start_posx"]]
    assert driver.pos == c["start_posx"] and driver.stops == 0
    assert len(driver.checks) == 3
    assert any(event == "NONCONTACT_HOLD_FEEDBACK" for event, _ in events)
    assert all(event != "ASSEMBLY_COMMITTED" for event, _ in events)


@pytest.mark.parametrize("flag", CONFIRMATIONS)
def test_unconfirmed_condition_blocks_even_a_complete_pose_plan(flag):
    config = configuration()
    config["confirmations"][flag] = False
    plan = prepare_motion(config)
    assert plan["status"] == "NOT_READY" and plan["route"] == []
    driver = FakeDriver(config)
    result = run_noncontact(driver, plan, lambda *args: None)
    assert result["status"] == "NONCONTACT_FAILED" and driver.moves == [] and driver.stops == 0


@pytest.mark.parametrize("change", [{"mode": None}, {"velocity": [0, 1]}, {"acceleration": [True, 1]},
    {"waypoints": [[0]*5]}, {"waypoints": [[11, 2, 100, 0, 170, 0]]},
    {"start_posx": [float("nan")]*6}])
def test_malformed_or_changed_orientation_plan_is_rejected(change):
    config = configuration()
    config.update(change)
    with pytest.raises(ValueError):
        prepare_motion(config)


def test_taught_orientation_uses_reviewed_tolerance_and_missing_tolerance_cannot_execute():
    config = configuration()
    config["waypoints"][0][3] += .005
    assert prepare_motion(config)["status"] == "PLAN_READY"
    config["limits"]["orientation_tolerance_deg"] = .001
    with pytest.raises(ValueError, match="orientation difference"):
        prepare_motion(config)
    config["limits"]["orientation_tolerance_deg"] = None
    pending = prepare_motion(config)
    assert pending["status"] == "NOT_READY" and pending["route"] == []
    assert "limits.orientation_tolerance_deg" in pending["missing"]


@pytest.mark.parametrize("field,value,reason", [("gripper_status", 0, "GRASP_NOT"),
    ("gripper_status", 66, "GRASP_NOT"), ("tcp", "OTHER", "TCP_TOOL"), ("tool", "OTHER", "TCP_TOOL"),
    ("robot_mode", 0, "ROBOT_STATE"), ("drl_state", 0, "ROBOT_STATE"),
    ("query_duration_s", 1, "QUERY_TOO_SLOW"), ("gripper_width_mm", float("nan"), "WIDTH_INVALID")])
def test_readiness_failure_does_not_send_move_or_stop_to_another_active_robot(field, value, reason):
    driver = FakeDriver(configuration())
    driver.modify = lambda sample: sample.update({field: value})
    result, driver, _ = run(driver)
    assert reason in result["reason"] and driver.moves == [] and driver.stops == 0


def test_start_pose_or_ik_fk_mismatch_never_moves():
    driver = FakeDriver(configuration())
    driver.pos[0] += 1
    assert "START_NOT" in run(driver)[0]["reason"]
    driver = FakeDriver(configuration())
    driver.check_pose = lambda pose: [pose[0]+1, *pose[1:]]
    assert run(driver)[0]["reason"] == "IK_FK_MISMATCH"
    assert driver.moves == []


def test_prepared_route_cannot_be_replaced_after_validation():
    plan = prepare_motion(configuration())
    plan["route"][0] = [0.]*6
    driver = FakeDriver(plan["config"])
    result = run_noncontact(driver, plan, lambda *args: None)
    assert result["reason"] == "NONCONTACT_PLAN_CHANGED" and driver.moves == []


def test_pose_change_during_read_only_preflight_does_not_start_a_different_segment():
    driver = FakeDriver(configuration())
    driver.modify = lambda sample: sample["posx"].__setitem__(0, 2) if driver.samples == 2 else None
    result, driver, _ = run(driver)
    assert result["reason"] == "TAUGHT_SEGMENT_START_LOST" and driver.moves == []


def test_arrival_read_after_motion_deadline_is_not_accepted():
    config, clock = configuration(), Clock()
    config["timing"]["motion_timeout_s"] = .02
    plan = prepare_motion(config)
    driver = FakeDriver(config)
    def late_read(sample):
        if driver.moves and driver.pending is None:
            clock.sleep(.02)
            sample["query_duration_s"] = .02
    driver.modify = late_read
    result = run_noncontact(driver, plan, lambda *args: None, now=clock.now, sleep=clock.sleep)
    assert result["reason"] == "MOTION_TIMEOUT" and len(driver.moves) == 1


@pytest.mark.parametrize("field,value", [("wrench", [5, 0, 0, 0, 0, 0]),
    ("wrench", [0, 0, 0, .5, 0, 0]), ("gripper_status", 0),
    ("tcp", "CHANGED"), ("query_duration_s", 1)])
def test_runtime_fault_stops_without_automatic_return(field, value):
    driver = FakeDriver(configuration())
    driver.modify = lambda sample: sample.update({field: value}) if driver.moves else None
    result, driver, _ = run(driver)
    assert result["status"] == "NONCONTACT_FAILED" and result["stopped"] is True
    assert driver.stops == 1 and len(driver.moves) == 1 and not result["returned_to_start"]


def test_cancel_during_asynchronous_motion_requests_and_confirms_stop():
    driver = FakeDriver(configuration())
    result, driver, _ = run(driver, cancelled=lambda: bool(driver.moves))
    assert result["reason"] == "OPERATOR_CANCELLED" and result["stop_ack"] and result["stopped"]
    assert len(driver.moves) == 1


@pytest.mark.parametrize("stop_works", [True, False])
def test_motion_timeout_and_stop_ack_are_not_arrival_or_stop_proof(stop_works):
    driver = FakeDriver(configuration())
    driver.stuck, driver.stop_works = True, stop_works
    result, driver, _ = run(driver)
    assert result["reason"] == "MOTION_TIMEOUT" and result["stop_ack"] is True
    assert result["stopped"] is (True if stop_works else None)
    assert len(driver.moves) == 1


def test_unacknowledged_move_remains_unknown_even_after_idle_stop_sample():
    driver = FakeDriver(configuration())
    driver.move_error = True
    result, driver, _ = run(driver)
    assert driver.stops == 1 and result["stop_ack"] is True and result["stopped"] is None
    assert result["stop_confirmation_error"] == "MOVE_ACK_UNCONFIRMED"


@pytest.mark.parametrize("event", ["NONCONTACT_MOVE_REQUEST", "NONCONTACT_FEEDBACK"])
def test_log_failure_blocks_progress_and_stops_if_a_move_was_requested(event):
    def record(name, data):
        if name == event:
            raise OSError("disk full")
    result, driver, _ = run(record=record)
    assert result["reason"] == "disk full"
    assert len(driver.moves) == driver.stops == (0 if event == "NONCONTACT_MOVE_REQUEST" else 1)


def test_default_and_incomplete_execute_do_not_construct_a_device(tmp_path, capsys):
    path = tmp_path/"pending.json"
    path.write_text(json.dumps(TEMPLATE))
    def forbidden(config):
        raise AssertionError("must not construct a device")
    assert main(["--config", str(path)], driver_factory=forbidden) == 0
    assert main(["--config", str(path), "--execute"], driver_factory=forbidden) == 2
    assert "NOT_READY" in capsys.readouterr().out


def test_read_only_cli_checks_full_mock_contract_without_motion(tmp_path, monkeypatch):
    config = configuration()
    config["mode"] = "REAL"  # REAL 소비 경계에만 Fake transport를 주입한다.
    path = tmp_path/"ready.json"
    path.write_text(json.dumps(config))
    driver = FakeDriver(config)
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")
    code = main(["--config", str(path), "--check", "--log-dir", str(tmp_path/"logs")], driver_factory=lambda c: driver)
    assert code == 0 and driver.moves == [] and driver.stops == 0 and driver.closed


@pytest.mark.parametrize("status", [0, 2, 3])
def test_probe_accepts_pending_input_without_adopting_pose_or_dispatching(tmp_path, monkeypatch, capsys, status):
    config = deepcopy(TEMPLATE)
    path = tmp_path/"pending.json"
    original = json.dumps(config)
    path.write_text(original)
    driver = FakeDriver(configuration())
    driver.modify = lambda sample: sample.update(gripper_status=status)
    captured = []
    def factory(value):
        captured.append(value)
        return driver
    monkeypatch.setenv("ROS_DOMAIN_ID", str(config["connection"]["ros_domain_id"]))
    assert main(["--config", str(path), "--probe", "--read-timeout", "2",
                 "--log-dir", str(tmp_path/"logs")], driver_factory=factory) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "READ_ONLY_PROBE_COMPLETE"
    assert result["grip_detected"] == bool(status & 2)
    assert result["execution_gripper_condition_met"] == (status == 2)
    assert result["start_pose_adopted"] is result["execution_preflight_passed"] is False
    assert result["missing_execution_inputs"] and captured[0]["timing"]["service_timeout_s"] == 2
    assert driver.closed and driver.moves == [] and driver.checks == [] and driver.stops == 0
    assert path.read_text() == original


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_probe_invalid_read_timeout_blocks_device_creation(tmp_path, monkeypatch, timeout):
    path = tmp_path/"pending.json"
    path.write_text(json.dumps(TEMPLATE))
    monkeypatch.setenv("ROS_DOMAIN_ID", str(TEMPLATE["connection"]["ros_domain_id"]))
    def forbidden(config):
        raise AssertionError("must not construct a device")
    assert main(["--config", str(path), "--probe", "--read-timeout", timeout], driver_factory=forbidden) == 1


def test_continuous_probe_records_manual_motion_without_dispatching_or_adopting(tmp_path, monkeypatch):
    import scripts.assembly_noncontact_trial as cli
    config = deepcopy(TEMPLATE)
    path = tmp_path/"pending.json"
    text = json.dumps(config)
    path.write_text(text)
    monkeypatch.setenv("ROS_DOMAIN_ID", str(config["connection"]["ros_domain_id"]))
    clock = Clock()
    monkeypatch.setattr(cli.time, "monotonic", clock.now)
    monkeypatch.setattr(cli.time, "sleep", clock.sleep)
    driver = FakeDriver(configuration())
    driver.modify = lambda sample: sample.update(robot_mode=0, robot_state=4, velx=[.5, 0, 0, 0, 0, 0],
        wrench=[float(driver.samples), 0., 0., 0., 0., 0.])
    directory = tmp_path/"logs"
    assert main(["--config", str(path), "--probe", "--probe-seconds", ".025", "--probe-interval", ".01",
                 "--log-dir", str(directory)], driver_factory=lambda c: driver) == 0
    rows = [json.loads(line) for p in directory.glob("*.jsonl") for line in p.read_text().splitlines()]
    samples = [r["payload"] for r in rows if r["event"] == "NONCONTACT_READ_ONLY_PROBE_SAMPLE"]
    assert len(samples) == 3 and [s["sample_index"] for s in samples] == [0, 1, 2]
    assert [s["force_delta_norm_n"] for s in samples] == [0., 1., 2.]
    assert rows[-1]["payload"]["sample_count"] == 3
    assert rows[0]["payload"]["probe_duration_s"] == .025
    assert driver.closed and driver.moves == [] and driver.checks == [] and driver.stops == 0
    assert path.read_text() == text


@pytest.mark.parametrize("duration", ["0", "-1", "nan", "inf"])
def test_continuous_probe_invalid_duration_blocks_device(tmp_path, monkeypatch, duration):
    path = tmp_path/"pending.json"
    path.write_text(json.dumps(TEMPLATE))
    def forbidden(config):
        raise AssertionError("must not construct a device")
    assert main(["--config", str(path), "--probe", "--probe-seconds", duration], driver_factory=forbidden) == 1


def test_continuous_probe_interrupt_keeps_samples_and_does_not_stop_robot(tmp_path, monkeypatch):
    config = deepcopy(TEMPLATE)
    path = tmp_path/"pending.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("ROS_DOMAIN_ID", str(config["connection"]["ros_domain_id"]))
    driver = FakeDriver(configuration())
    driver.modify = lambda sample: sample.update(robot_mode=0)
    original = driver.sample
    def read():
        if driver.samples == 1:
            raise KeyboardInterrupt()
        return original()
    driver.sample = read
    directory = tmp_path/"logs"
    assert main(["--config", str(path), "--probe", "--probe-seconds", "1",
                 "--log-dir", str(directory)], driver_factory=lambda c: driver) == 1
    rows = [json.loads(line) for p in directory.glob("*.jsonl") for line in p.read_text().splitlines()]
    assert sum(r["event"] == "NONCONTACT_READ_ONLY_PROBE_SAMPLE" for r in rows) == 1
    assert rows[-1]["event"] == "NONCONTACT_SESSION_ERROR"
    assert driver.closed and driver.stops == 0 and driver.moves == []


def test_continuous_manual_recording_rejects_automatic_mode_without_changing_it(tmp_path, monkeypatch):
    path = tmp_path/"pending.json"
    path.write_text(json.dumps(TEMPLATE))
    monkeypatch.setenv("ROS_DOMAIN_ID", str(TEMPLATE["connection"]["ros_domain_id"]))
    driver = FakeDriver(configuration())
    assert main(["--config", str(path), "--probe", "--probe-seconds", "1",
                 "--log-dir", str(tmp_path/"logs")], driver_factory=lambda c: driver) == 1
    assert driver.closed and driver.stops == 0 and driver.moves == [] and driver.samples == 1


def test_real_cli_requires_explicit_domain_and_stop_marker_before_device_creation(tmp_path, monkeypatch):
    config = configuration()
    config["mode"] = "REAL"
    path = tmp_path/"ready.json"
    path.write_text(json.dumps(config))
    def forbidden(config):
        raise AssertionError("must not construct a device")
    monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
    assert main(["--config", str(path), "--execute"], driver_factory=forbidden) == 1
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")
    assert main(["--config", str(path), "--execute"], driver_factory=forbidden) == 1
    stop = tmp_path/"STOP"
    stop.touch()
    assert main(["--config", str(path), "--execute", "--stop-file", str(stop)], driver_factory=forbidden) == 1


def test_execute_cli_mock_returns_to_start_and_records_without_assembly_commit(tmp_path, monkeypatch):
    config = configuration()
    config["mode"] = "REAL"
    path = tmp_path/"ready.json"
    path.write_text(json.dumps(config))
    driver = FakeDriver(config)
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")
    log_dir = tmp_path/"logs"
    code = main(["--config", str(path), "--execute", "--stop-file", str(tmp_path/"STOP"),
                 "--log-dir", str(log_dir), "--gripper-force-setting-n", "20"], driver_factory=lambda c: driver)
    assert code == 0 and driver.closed and driver.pos == config["start_posx"]
    rows = [json.loads(line) for p in log_dir.glob("*.jsonl") for line in p.read_text().splitlines()]
    assert rows[-1]["event"] == "NONCONTACT_COMPLETE"
    assert rows[-1]["payload"]["assembled"] is False
    session = rows[0]["payload"]
    assert session["gripper_force_setting_n"] == 20
    assert session["gripper_force_setting_source"] == "OPERATOR_REPORTED"
    assert session["gripper_force_measured_n"] is None and session["contact_force_verified"] is False
    assert session["route"] == configuration()["waypoints"] + [configuration()["waypoints"][0], configuration()["start_posx"]]
    assert all(row["schema_version"] == 1 and row["elapsed_s"] >= 0 for row in rows)
    samples = [row["payload"] for row in rows if row["event"] == "NONCONTACT_SAMPLE"]
    assert {sample["phase"] for sample in samples} == {"PREFLIGHT", "BEFORE_MOVE", "MOVE", "HOLD"}
    assert all(sample["wrench_delta"] == [0.]*6 for sample in samples if sample["phase"] != "PREFLIGHT")
    requests = [row["payload"] for row in rows if row["event"] == "NONCONTACT_MOVE_REQUEST"]
    assert all(request["velocity"] == [1., 1.] and request["acceleration"] == [1., 1.] for request in requests)
    assert len([row for row in rows if row["event"] == "NONCONTACT_MOVE_ACK"]) == len(requests)


def test_force_trip_sample_is_recorded_before_rejection():
    config = configuration()
    driver = FakeDriver(config)
    driver.modify = lambda sample: sample.update(wrench=[6., 0., 0., 0., .25, 0.])
    events = []
    with pytest.raises(RuntimeError, match="UNEXPECTED_WRENCH_CHANGE"):
        checked_sample(driver, config, [0.]*6, record=lambda event, data: events.append((event, data)))
    assert len(events) == 1 and events[0][0] == "NONCONTACT_SAMPLE"
    data = events[0][1]
    assert data["force_delta_norm_n"] == 6 and data["moment_delta_norm_nm"] == .25
    assert data["baseline_wrench"] == [0.]*6 and data["wrench_delta"] == data["wrench"]
    assert data["contact_force_verified"] is False


def test_probe_query_failure_keeps_session_error_log_and_closes_driver(tmp_path, monkeypatch):
    config = deepcopy(TEMPLATE)
    path = tmp_path/"pending.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("ROS_DOMAIN_ID", str(config["connection"]["ros_domain_id"]))
    driver = FakeDriver(configuration())
    def fail():
        raise TimeoutError("query failed")
    driver.sample = fail
    log_dir = tmp_path/"logs"
    assert main(["--config", str(path), "--probe", "--log-dir", str(log_dir)], driver_factory=lambda c: driver) == 1
    rows = [json.loads(line) for p in log_dir.glob("*.jsonl") for line in p.read_text().splitlines()]
    assert rows[-1]["event"] == "NONCONTACT_SESSION_ERROR" and rows[-1]["payload"]["reason"] == "query failed"
    assert driver.closed and driver.stops == 0 and driver.moves == []


@pytest.mark.parametrize("event", ["NONCONTACT_SAMPLE", "NONCONTACT_MOVE_ACK"])
def test_telemetry_log_failure_still_requests_stop_after_motion(event):
    def record(kind, data):
        if kind == event and (kind == "NONCONTACT_MOVE_ACK" or data.get("phase") == "MOVE"):
            raise OSError("telemetry disk full")
    result, driver, _ = run(record=record)
    assert result["status"] == "NONCONTACT_FAILED" and driver.stops == 1
