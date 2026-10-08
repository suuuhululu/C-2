"""Day4 운영 진입점의 C/A/D 연결. HTTP·음향·B 생산·Robot 프로세스는 Fixture/Mock."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import urljoin

import pytest
from jsonschema import Draft202012Validator, RefResolver
from PyQt5.QtCore import QProcess, QSize
from PyQt5.QtWidgets import QApplication

from app.c_design import llm
from app.hmi_contracts import validate_hmi_snapshot
from app.qt_hmi import HmiWindow
from app.real_design_controller import RealDesignController, load_workflow_rows
from app.real_workflow_hmi import WorkflowTrial, main
from app.robot_trial import prepare_plan
from test_c_function_hmi import INITIAL, settled
from test_c_voice_hmi import audio
from test_real_workflow_hmi import Process, event
from test_real_voice_workflow import finish_confirmed_delivery

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def connected(tmp_path, monkeypatch, audio):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    design = deepcopy(INITIAL["design"])
    for block in design["blocks"]:
        block["color"] = "blue"
    calls = []

    def http(payload, key):
        calls.append(deepcopy(payload))
        return dict(choices=[dict(message=dict(content=json.dumps(design)))])

    monkeypatch.setattr(llm, "_post_json", http)
    manifest = load_workflow_rows(ROOT / "interfaces/robot_voice_workflow.json")[0]
    manifest["supply_rows"][-1]["first_slot"] = 6
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    processes = []

    def factory(parent):
        process = Process(parent)
        processes.append(process)
        return process

    window = HmiWindow(screen_size=QSize(1920, 1080))
    controller = RealDesignController(path, tmp_path / "robot", process_factory=factory,
                                      execution_timeout_seconds=120)
    workflow = WorkflowTrial(window, controller, tmp_path / "backend")
    requests = []
    workflow.vision.bind(requests.append)
    assert controller.check()
    event(controller, "ROBOT_CHECK_COMPLETE", dict(motion_commands_sent=False))
    processes[-1].finished.emit(0, QProcess.NormalExit)
    qapp.processEvents()
    yield workflow, processes, requests, calls
    workflow.c_connection.close()
    settled(workflow)
    controller.timer.stop()
    controller._operation = None
    window.close()


def validate_snapshot(workflow):
    QApplication.instance().processEvents()
    snapshot = workflow.window._snapshot
    validate_hmi_snapshot(snapshot)
    schema = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    common = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    Draft202012Validator(schema, resolver=RefResolver.from_schema(schema,
        store={common["$id"]: common, urljoin(schema["$id"], "day4.schema.json"): common})).validate(snapshot)
    assert snapshot["day4_workflow"] and "manual_trial" not in snapshot and "transfer_target" not in snapshot


def place(workflow, check_id, status="EMPTY", seq=0):
    workflow.vision.submit_place(dict(check_id=check_id, observation_seq=seq, status=status, reason=None))
    QApplication.instance().processEvents()


def observation(workflow, check_id, blocks, *, seq=0):
    workflow.vision.submit_observation(dict(check_id=check_id, observation_seq=seq, status="OK",
        visible_blocks=deepcopy(blocks), verified_regions=[dict(x=0, y=0, width=24, height=24, layer=i)
        for i in range(1, 5)], reason=None))
    QApplication.instance().processEvents()


def start(workflow):
    assert workflow.command(dict(command="START"))["accepted"]
    settled(workflow)
    assert workflow.backend.state["context"] is not None
    validate_snapshot(workflow)


def test_stt_full_plan_human_refill_and_new_start_preserve_supply_and_reject_old_ids(connected, audio):
    workflow, processes, requests, calls = connected
    start(workflow)
    backend = workflow.backend
    old_job = backend.state["job_id"]
    assert audio[1][:2] == ["record", "stt"] and len(calls) == 1
    assert len(workflow.controller.plan_columns) == 15 and len(processes) == 1
    assert requests[-1]["purpose"] == "PLACE" and requests[-1]["after"] is None
    old_check = requests[-1]["check_id"]
    place(workflow, old_check)
    refills = []
    executions = []
    while backend.state["workflow_status"] != "COMPLETE":
        if backend.state["reason"] == "NEEDS_REFILL":
            row = next(row for row in workflow.controller.state["supply"]
                       if row["needs_refill"] and all(row[k] == backend._next_step()["after"][k] for k in ("brick_type", "color")))
            command = dict(command="SUPPLY_REFILLED", job_id=old_job, brick_type=row["brick_type"], color=row["color"])
            count = len(processes)
            assert not workflow.command(dict(command, job_id="old-job"))["accepted"]
            assert workflow.command(command)["accepted"]
            assert not workflow.command(command)["accepted"]
            assert len(processes) == count  # 보충 자체는 이동을 시작하지 않는다.
            assert requests[-1]["purpose"] == "PLACE"
            place(workflow, old_check, seq=999)
            assert len(processes) == count
            place(workflow, requests[-1]["check_id"])
            refills.append((row["brick_type"], row["color"]))
        assert backend.state["workflow_status"] == "DELIVERING"
        assert not workflow.command(dict(command="START"))["accepted"]
        executions.append(backend.state["execution_id"])
        target = deepcopy(backend._next_step()["after"])
        current = backend.state["current"]
        finish_confirmed_delivery(workflow, processes)
        assert backend.state["current"] == current
        assert requests[-1]["purpose"] == "ASSEMBLY" and requests[-1]["after"] == target
        check = requests[-1]["check_id"]
        place(workflow, check)
        observation(workflow, check, current["blocks"] + [target])
        validate_snapshot(workflow)
    assert refills == [("2x3x1", "blue")] * 2
    assert len(processes) == 16 and len(executions) == 15
    assert workflow.window.buttons["START"].isEnabled()
    assert workflow.window._snapshot["progress"] == dict(completed=15, total=15)
    before_supply = deepcopy(workflow.controller.state["supply"])
    audio[0].append("새 의자 만들어줘")
    start(workflow)
    assert backend.state["job_id"] != old_job
    assert backend.state["current"] == dict(current_revision=0, blocks=[])
    assert workflow.controller.state["supply"] == before_supply
    assert len(processes) == 16 and len(calls) == 2
    place(workflow, old_check, seq=1000)
    observation(workflow, check, current["blocks"] + [target], seq=1000)
    assert not backend.on_robot_result(dict(execution_id=executions[-1], success=True, reason=None))
    assert backend.state["current"]["blocks"] == [] and len(processes) == 16
    events = [json.loads(line) for path in Path(workflow.backend._record.directory).glob("*.jsonl")
              for line in path.read_text().splitlines() if json.loads(line)["event"] == "JOB_STARTED"]
    assert len(events) == 2 and all(row["result"]["empty_assembly_board_confirmed"] for row in events)


def test_current_recheck_is_not_place_empty_and_invalid_b_result_holds(connected):
    workflow, processes, requests, _ = connected
    start(workflow)
    from app.replan import open_current_check
    open_current_check(workflow.backend, "REPLAN")
    assert requests[-1]["purpose"] == "CURRENT" and requests[-1]["after"] is None
    check = requests[-1]["check_id"]
    before = deepcopy(workflow.backend.state["current"])
    workflow.vision.submit_observation(dict(check_id=check, status="OK"))
    QApplication.instance().processEvents()
    assert workflow.backend.state["workflow_status"] == "HOLD"
    assert "B_RESULT_INVALID" in workflow.backend.state["reason"]
    assert workflow.backend.state["current"] == before and len(processes) == 1


def test_robot_deadline_sends_one_stop_without_adopting_late_success(connected, monkeypatch):
    workflow, processes, requests, _ = connected
    start(workflow)
    place(workflow, requests[-1]["check_id"])
    controller = workflow.controller
    execution = controller._identity
    monkeypatch.setattr("app.real_trial_hmi.monotonic", lambda: controller._started_at + 121)
    controller._poll()
    state = workflow.backend.state
    stop_id = state["stop_request"]
    assert state["fault"] == "ROBOT_EXECUTION_TIMEOUT" and stop_id
    assert controller.state["stop"]["request_id"] == stop_id
    assert len(processes) == 3 and "--stop" in processes[-1].started[0][1]
    controller._poll()
    assert len(processes) == 3
    assert not workflow.backend.on_robot_result(dict(execution_id=execution, success=True, reason=None))
    assert not workflow.backend.on_stopped("old-stop", stopped=True, execution_ended=True, block_state_known=True)
    workflow.backend.on_stopped(stop_id, stopped=True, execution_ended=False, block_state_known=True)
    assert workflow.backend.state["stop_request"] == stop_id
    workflow.backend.on_stopped(stop_id, stopped=True, execution_ended=True, block_state_known=True)
    assert workflow.backend.state["workflow_status"] == "HOLD"
    assert not workflow.command(dict(command="RESUME", job_id=state["job_id"]))["accepted"]
    assert workflow.backend.state["current"]["blocks"] == [] and len(requests) == 1
    validate_snapshot(workflow)


def test_finish_before_deadline_poll_does_not_invent_timeout(connected, monkeypatch):
    workflow, processes, requests, _ = connected
    start(workflow)
    place(workflow, requests[-1]["check_id"])
    controller = workflow.controller
    monkeypatch.setattr("app.real_trial_hmi.monotonic", lambda: controller._started_at + 121)
    finish_confirmed_delivery(workflow, processes)
    assert not controller._timed_out and controller.state["fault"] is None
    assert workflow.backend.state["workflow_status"] == "WAIT_ASSEMBLY" and len(processes) == 2


def test_repository_relative_configs_survive_relocation_with_identical_measured_files(tmp_path):
    for folder in ("interfaces", "robot_cycles", "supply_board_map"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    manifest, rows = load_workflow_rows(tmp_path / "interfaces/robot_voice_workflow.json")
    assert Path(manifest["base_config"]).is_relative_to(tmp_path)
    for row in rows.values():
        assert Path(row["source_path"]).is_relative_to(tmp_path)
        assert hashlib.sha256(Path(row["source_path"]).read_bytes()).hexdigest() == row["source_sha256"]
        prepare_plan(row)  # 경로/hash 확인뿐이며 ROS 이동 없음.
    assert (tmp_path / "supply_board_map/supply_pick_lines_provisional.json").read_bytes() == \
        (ROOT / "supply_board_map/supply_pick_lines_provisional.json").read_bytes()


@pytest.mark.parametrize("arguments", [["--c-fixture", "saved.json"], ["--c-mode", "offline"],
    ["--robot-timeout-seconds", "nan"], ["--robot-timeout-seconds", "0"]])
def test_runtime_rejects_fixture_offline_and_invalid_timeout_before_devices(arguments):
    with pytest.raises(SystemExit) as error:
        main(["--real-workflow", "--supply-manifest", "unused", "--vision-module", "unused",
              "--robot-timeout-seconds", "120", *arguments])
    assert error.value.code == 2


def test_repeated_one_step_job_uses_next_slot_in_executed_config(connected, audio, monkeypatch):
    workflow, processes, requests, _ = connected
    block = dict(brick_type="2x2x1", color="blue", x=10, y=10, layer=1, orientation_deg=0)
    design = dict(design_version=1, blocks=[block])
    monkeypatch.setattr(llm, "_post_json", lambda payload, key:
        dict(choices=[dict(message=dict(content=json.dumps(design)))]))
    for slot in (1, 2):
        if slot == 2:
            audio[0].append("의자 만들어줘")
        start(workflow)
        place(workflow, requests[-1]["check_id"])
        controller = workflow.controller
        target = deepcopy(workflow.backend._next_step()["after"])
        config_path = Path(processes[-1].started[0][1][3])
        assert controller.target["slot"] == slot
        assert json.loads(config_path.read_text())["slot"] == slot
        finish_confirmed_delivery(workflow, processes)
        check = requests[-1]["check_id"]
        place(workflow, check)
        observation(workflow, check, [target])
        assert workflow.backend.state["workflow_status"] == "COMPLETE"
        validate_snapshot(workflow)
    assert len(processes) == 3


def test_invalid_driver_log_keeps_deadline_active(connected, monkeypatch):
    workflow, processes, requests, _ = connected
    start(workflow)
    place(workflow, requests[-1]["check_id"])
    controller = workflow.controller
    path = controller.directory / "driver" / f"{controller._identity}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json\n")
    controller._poll()
    assert controller.timer.isActive() and controller.state["fault"].startswith("DRIVER_LOG_INVALID")
    monkeypatch.setattr("app.real_trial_hmi.monotonic", lambda: controller._started_at + 121)
    controller._poll()
    assert workflow.backend.state["stop_request"] and len(processes) == 3
    assert workflow.backend.state["fault"] == "ROBOT_EXECUTION_TIMEOUT"


def test_disconnected_b_and_stale_place_failure_cannot_start_or_advance(connected):
    workflow, processes, requests, _ = connected
    handler = workflow.vision.handler
    workflow.vision.handler = None
    assert workflow.command(dict(command="START")) == dict(accepted=False, reason="VISION_NOT_CONNECTED")
    assert workflow.backend.state["job_id"] is None and len(processes) == 1
    workflow.vision.handler = handler
    start(workflow)
    check = requests[-1]["check_id"]
    workflow.vision.submit_failure("closed-check", "CAMERA_FAILED")
    QApplication.instance().processEvents()
    assert workflow.backend.state["place_check"]["check_id"] == check
    workflow.vision.submit_place(dict(check_id=check, observation_seq=0, status="UNOBSERVABLE", reason="CAMERA_FAILED"))
    QApplication.instance().processEvents()
    assert workflow.backend.state["current"]["blocks"] == [] and len(processes) == 1
    assert workflow.backend.state["place_status"] == "UNOBSERVABLE"
    validate_snapshot(workflow)
