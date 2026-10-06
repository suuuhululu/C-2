import json
from uuid import uuid4

import pytest

from app.backend import Backend
from app.jsonl_log import JsonlLog
from app.snapshot import make_snapshot
from test_backend import A, B, C, RA, RB, RC, FakePorts, FIXTURES, observation, robot_success


def logged_backend(tmp_path):
    ports = FakePorts()
    backend = Backend(ports, mode="FAKE", record=JsonlLog(tmp_path))
    backend.controller_ready(ready=True, at_observe_point=True)
    backend.command(dict(command="START"))
    backend.on_plan(ports.calls("planner")[-1]["request_id"], FIXTURES["design"], FIXTURES["initial_plan"])
    return backend, ports


def test_normal_snapshots_and_job_jsonl_trace_delivery_separately_from_assembly(tmp_path):
    backend, ports = logged_backend(tmp_path)
    assert make_snapshot(backend.state)["workflow_status"] == "HOLD"
    backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    for index, (blocks, regions) in enumerate([([A], [RA]), ([A, B], [RA, RB]), ([C], [RC])]):
        assert make_snapshot(backend.state)["monitor"]["robot"]["status"] == "BUSY"
        robot_success(backend)
        snapshot = make_snapshot(backend.state)
        assert snapshot["progress"] == dict(completed=index, total=3)
        assert snapshot["step"]["observed"] is None
        payload = observation(backend, blocks, regions)
        backend.on_place(payload["check_id"], 0, "EMPTY")
        backend.on_observation(payload)
    snapshot = make_snapshot(backend.state)
    assert snapshot["workflow_status"] == "COMPLETE"
    assert snapshot["current"] == dict(current_revision=3, blocks=[A, B, C])
    assert snapshot["progress"] == dict(completed=3, total=3)
    assert "누적 실제 배치 3개 일치" in snapshot["notice"]["reason"]
    assert snapshot["actions"]["start"]["enabled"]
    assert all(column["next_slot"] is None for column in snapshot["monitor"]["supply"])
    path = tmp_path / f"{backend.state['job_id']}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    names = [record["event"] for record in records]
    assert names.count("CURRENT_ADOPTED") == names.count("STEP_CONFIRMED") == 3
    assert names.count("DELIVERY_RESULT") == 3 and names.count("JOB_COMPLETED") == 1
    adopted=[record["result"] for record in records if record["event"]=="CURRENT_ADOPTED"]
    assert [result["current"]["current_revision"] for result in adopted]==[1,2,3]
    assert adopted[-1]["observed"]["visible_blocks"]==[C]
    assert adopted[-1]["observed"]["verified_regions"]==[RC]
    assert adopted[-1]["observed"]["observation_seq"]==0
    assert names.index("DELIVERY_RESULT") < names.index("CURRENT_ADOPTED") < names.index("STEP_CONFIRMED")
    assert {record["step_id"] for record in records if record["event"] == "STEP_CONFIRMED"} == {"S01", "S02", "S03"}
    assert all(set(record) == {"timestamp", "job_id", "plan_id", "step_id", "request_id", "event", "result", "reason"}
               for record in records)
    assert records[-1]["result"]["blocks"] == [A, B, C]
    first_job = backend.state["job_id"]
    old_goal = ports.calls("robot.deliver")[-1]["execution_id"]
    backend.command(dict(command="START"))
    assert backend.state["job_id"] != first_job and len(list(tmp_path.glob("*.jsonl"))) == 2
    assert len(ports.calls("planner")) == 2
    assert not backend.on_robot_result(dict(execution_id=old_goal,success=True,reason=None))
    old_records = [json.loads(line) for line in path.read_text().splitlines()]
    assert old_records[-1]["event"] == "LATE_RESULT_IGNORED"
    assert old_records[-1]["job_id"] == first_job and old_records[-1]["step_id"] == "S03"
    new_records = [json.loads(line) for line in (tmp_path/f"{backend.state['job_id']}.jsonl").read_text().splitlines()]
    assert new_records[-1]["event"]=="REQUEST_SENT"


def test_unknown_idle_snapshot_and_copy_do_not_invent_supply_or_readiness():
    backend = Backend(FakePorts(), mode="FAKE")
    snapshot = make_snapshot(backend.state)
    assert snapshot["design"] is None and snapshot["monitor"]["robot"]["status"] is None
    assert snapshot["current"] == dict(current_revision=0, blocks=[])
    snapshot["current"]["blocks"].append(A)
    assert backend.state["current"]["blocks"] == []
    assert snapshot["monitor"]["place_status"] is None
    snapshot["monitor"]["supply"][0]["next_slot"] = 6
    assert make_snapshot(backend.state)["monitor"]["supply"][0]["next_slot"] is None
    assert backend.command(dict(command="START"))["reason"] == "CONTROLLER_NOT_READY_AT_OBSERVE"


def test_repeated_unobservable_only_logs_hold_entry_and_late_result(tmp_path):
    backend, _ = logged_backend(tmp_path)
    backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    robot_success(backend)
    check = backend.state["active_check"]["check_id"]
    for sequence in (10, 11, 12):
        backend.on_observation({**FIXTURES["observed_unobservable"], "check_id": check,
                                "observation_seq": sequence})
    snapshot = make_snapshot(backend.state)
    assert snapshot["step"]["comparison"] == "UNOBSERVABLE"
    assert snapshot["monitor"]["observation"]["observation_seq"] == 12
    assert not backend.on_observation({**FIXTURES["observed_unobservable"], "check_id": check,
                                       "observation_seq": 11})
    records = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert sum(record["event"] == "OBSERVATION_HOLD" for record in records) == 1
    assert records[-1]["event"] == "LATE_RESULT_IGNORED"
    assert not any(record["event"] == "CURRENT_ADOPTED" for record in records)


def test_mismatch_snapshot_contains_actual_and_source_question(tmp_path):
    backend, ports = logged_backend(tmp_path)
    backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    robot_success(backend)
    backend.on_observation(observation(backend, [{**A, "color": "blue"}], [RA]))
    backend.on_question(ports.calls("hri")[-1]["request_id"], "원래 목표를 유지할까요?")
    snapshot = make_snapshot(backend.state)
    assert snapshot["step"]["target"]["color"] == "yellow"
    assert snapshot["current"] == dict(current_revision=1, blocks=[{**A, "color": "blue"}])
    assert snapshot["step"]["observed"]["visible_blocks"][0]["color"] == "blue"
    assert snapshot["notice"]["question"] == "원래 목표를 유지할까요?"
    assert not snapshot["actions"]["intent_choice"]["visible"]


def test_stop_pending_and_confirmed_snapshot_do_not_claim_stop_on_request(tmp_path):
    backend, _ = logged_backend(tmp_path)
    backend.command(dict(command="STOP", job_id=backend.state["job_id"]))
    assert make_snapshot(backend.state)["monitor"]["robot"]["status"] == "STOP_PENDING"
    assert not make_snapshot(backend.state)["actions"]["resume"]["enabled"]
    backend.on_stopped(backend.state["stop_request"], stopped=True, execution_ended=True, block_state_known=True)
    assert make_snapshot(backend.state)["actions"]["resume"]["enabled"]
    assert make_snapshot(backend.state)["monitor"]["robot"]["status"] == "STOPPED"


def test_log_failure_blocks_request_but_does_not_block_emergency_stop(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_text("preserve")
    ports = FakePorts()
    backend = Backend(ports, mode="FAKE", record=JsonlLog(path))
    backend.controller_ready(ready=True, at_observe_point=True)
    assert not backend.command(dict(command="START"))["accepted"]
    assert ports.requests == [] and "LOG_FAILED" in backend.state["reason"]
    assert backend.command(dict(command="STOP", job_id=backend.state["job_id"]))["accepted"]
    assert len(ports.calls("robot.stop")) == 1
    assert path.read_text() == "preserve"


def test_step_record_failure_keeps_actual_current_and_blocks_next_delivery():
    def record(value):
        if value["event"]=="STEP_CONFIRMED":
            raise OSError("disk full fixture")
    ports=FakePorts();backend=Backend(ports,mode="FAKE",record=record)
    backend.controller_ready(ready=True,at_observe_point=True)
    backend.command(dict(command="START"))
    backend.on_plan(ports.calls("planner")[-1]["request_id"],FIXTURES["design"],FIXTURES["initial_plan"])
    backend.on_place(backend.state["place_check"]["check_id"],0,"EMPTY");robot_success(backend)
    payload=observation(backend,[A],[RA]);backend.on_place(payload["check_id"],0,"EMPTY")
    assert backend.on_observation(payload)
    assert backend.state["workflow_status"]=="HOLD" and "disk full fixture" in backend.state["reason"]
    assert backend.state["current"]==dict(current_revision=1,blocks=[A])
    assert backend.state["context"]["confirmed_steps"]==[] and len(ports.calls("robot.deliver"))==1


@pytest.mark.parametrize("job_id", ["../escape", "bad", str(uuid4()).upper()])
def test_log_rejects_path_and_noncanonical_job_ids(tmp_path, job_id):
    with pytest.raises(ValueError):
        JsonlLog(tmp_path)(dict(job_id=job_id))
    assert list(tmp_path.iterdir()) == []
