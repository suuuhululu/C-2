import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urljoin

import pytest
from PyQt5.QtCore import QObject, QProcess, QSize, pyqtSignal
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.jsonl_log import JsonlLog
from app.hmi_contracts import validate_hmi_snapshot
from app.qt_hmi import HmiWindow
from app.real_trial_hmi import RealTrialController
from app.snapshot import make_snapshot


ROOT = Path(__file__).resolve().parents[2]


class Process(QObject):
    finished = pyqtSignal(int, object)
    errorOccurred = pyqtSignal(object)
    readyReadStandardOutput = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.started = []

    def setWorkingDirectory(self, path):
        self.cwd = path

    def setProcessChannelMode(self, mode):
        pass

    def start(self, executable, args):
        self.started.append((executable, args))

    def readAllStandardOutput(self):
        return b""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_trial(tmp_path, *, color="blue", slot=5, record=None):
    path = tmp_path / "config.json"
    source = ROOT / ("interfaces/robot_trial_blue5.json" if color == "blue" else "interfaces/robot_trial.json")
    path.write_text(source.read_text())
    processes = []

    def factory(parent):
        process = Process(parent)
        processes.append(process)
        return process

    controller = RealTrialController(path, tmp_path / "driver", brick_type="2x2x1", color=color,
                                     slot=slot, process_factory=factory)
    emitted = []
    backend = Backend(lambda port, payload: emitted.append((port, payload)), mode="REAL",
                      single_trial=True, record=record)
    backend.connect_robot(controller)
    controller.on_result, controller.on_event = backend.on_robot_result, backend.on_robot_event

    def refresh():
        if backend.state["job_id"] is None:
            ready = controller.state["ready_at_observe"]
            backend.controller_ready(ready=ready, at_observe_point=ready)

    controller.changed.connect(refresh)
    return backend, controller, processes, emitted


def event(controller, name, payload, identity=None):
    identity = identity or controller._identity
    path = controller.directory / "driver" / f"{controller._identity}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(dict(execution_id=identity, event=name, payload=payload)) + "\n")


def ready(controller, processes):
    assert controller.check()
    assert "--check" in processes[-1].started[0][1]
    event(controller, "ROBOT_CHECK_COMPLETE", dict(motion_commands_sent=False))
    processes[-1].finished.emit(0, QProcess.NormalExit)


def complete(controller, processes, *, success=True, proof=True, code=0):
    if proof:
        event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=controller.target["slot"], next_slot=6))
        event(controller, "ROBOT_RELEASE_CONFIRMED", dict(slot=controller.target["slot"]))
        event(controller, "ROBOT_RETURN_CONFIRMED", dict(robot_state=1, motion_status=0))
    event(controller, "ROBOT_TRIAL_RESULT", dict(execution_id=controller._identity, success=success,
                                               reason=None if success else "PICK_HOLD_UNCONFIRMED"))
    processes[-1].finished.emit(code, QProcess.NormalExit if code == 0 else QProcess.CrashExit)


def test_probe_and_one_start_use_same_goal_and_never_fake_assembly(qapp, tmp_path):
    backend, controller, processes, emitted = make_trial(tmp_path, record=JsonlLog(tmp_path / "backend"))
    assert not backend.command(dict(command="START"))["accepted"]
    assert processes == []
    ready(controller, processes)
    assert controller.configuration["trial"]["confirmations"]["empty_place_and_slot"] is False
    assert backend.command(dict(command="START"))["accepted"]
    assert len(processes) == 2 and "--execute" in processes[-1].started[0][1]
    assert "--require-observe-start" in processes[-1].started[0][1]
    assert controller.configuration["trial"]["confirmations"]["empty_place_and_slot"] is True
    identity = backend.state["execution_id"]
    assert processes[-1].started[0][1][processes[-1].started[0][1].index("--execution-id") + 1] == identity
    assert not backend.command(dict(command="START"))["accepted"]
    complete(controller, processes)
    state = backend.state
    assert state["workflow_status"] == "HOLD" and state["reason"] == "REAL_TRANSFER_DONE_ASSEMBLY_UNVERIFIED"
    assert state["current"] == dict(current_revision=0, blocks=[])
    assert state["context"] is None and emitted == []
    assert not backend.command(dict(command="START"))["accepted"]
    snapshot = make_snapshot(state)
    assert snapshot["monitor"]["robot"]["mode"] == "REAL"
    assert snapshot["progress"] == dict(completed=0, total=0)
    assert not snapshot["actions"]["stop"]["enabled"] and not snapshot["actions"]["resume"]["enabled"]
    assert next(row for row in snapshot["monitor"]["supply"] if row["color"] == "blue" and row["brick_type"] == "2x2x1")["next_slot"] == 6
    records = [json.loads(line) for line in next((tmp_path / "backend").glob("*.jsonl")).read_text().splitlines()]
    assert len([record for record in records if record["event"] == "DELIVERY_RESULT"]) == 1
    assert not any(record["event"] in ("STEP_CONFIRMED", "JOB_COMPLETED") for record in records)


def test_missing_probe_record_or_crash_never_enables_start(qapp, tmp_path):
    backend, controller, processes, _ = make_trial(tmp_path)
    assert controller.check()
    processes[-1].finished.emit(0, QProcess.NormalExit)
    assert not backend.command(dict(command="START"))["accepted"]
    assert controller.check()
    event(controller, "ROBOT_CHECK_COMPLETE", dict(motion_commands_sent=False))
    processes[-1].finished.emit(-6, QProcess.CrashExit)
    assert not controller.state["ready_at_observe"]


@pytest.mark.parametrize("case", ["failure", "missing_proof", "crash", "missing_result", "malformed_log"])
def test_failed_real_trial_stays_held_with_no_retry_or_fake_progress(qapp, tmp_path, case):
    backend, controller, processes, emitted = make_trial(tmp_path)
    ready(controller, processes)
    assert backend.command(dict(command="START"))["accepted"]
    if case in ("missing_result", "malformed_log"):
        if case == "malformed_log":
            event(controller, "ROBOT_TRIAL_RESULT", dict(execution_id=controller._identity, success="true", reason=None))
        processes[-1].finished.emit(0, QProcess.NormalExit)
    else:
        complete(controller, processes, success=case != "failure", proof=case != "missing_proof", code=-6 if case == "crash" else 0)
    assert backend.state["workflow_status"] == "HOLD"
    assert backend.state["fault"] is not None
    assert emitted == [] and len(processes) == 2
    assert not backend.command(dict(command="START"))["accepted"]
    assert not controller.check()


def test_changed_config_or_wrong_supply_row_never_spawns_execute(qapp, tmp_path):
    backend, controller, processes, _ = make_trial(tmp_path)
    ready(controller, processes)
    config = json.loads(controller.config_path.read_text())
    config["settings"]["joint_speed"] = 19
    controller.config_path.write_text(json.dumps(config))
    assert not backend.command(dict(command="START"))["accepted"]
    assert len(processes) == 1 and backend.state["job_id"] is None
    controller.target["color"] = "yellow"
    assert not controller.check() and len(processes) == 1


def test_duplicate_pick_closed_result_and_single_job_guards(qapp, tmp_path):
    backend, controller, processes, _ = make_trial(tmp_path)
    ready(controller, processes)
    assert backend.command(dict(command="START"))["accepted"]
    identity = backend.state["execution_id"]
    reply = controller.deliver(dict(execution_id=identity, brick_type="2x2x1", color="blue"))
    assert not reply["accepted"] and reply["reason"] == "DUPLICATE"
    event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=5, next_slot=6))
    event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=5, next_slot=1))
    controller._poll()
    assert controller._next_slot == 6
    assert backend.state["workflow_status"] == "DELIVERING"
    complete(controller, processes)
    assert not backend.on_robot_result(dict(execution_id=identity, success=True, reason=None))
    processes[-1].finished.emit(0, QProcess.NormalExit)
    assert len(processes) == 2 and backend.state["workflow_status"] == "HOLD"


def test_hmi_mode_buttons_and_window_close_while_trial_active(qapp, tmp_path):
    backend, controller, processes, _ = make_trial(tmp_path)
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.installEventFilter(controller)
    window.command_requested.connect(backend.command)
    window.render_snapshot(make_snapshot(backend.state))
    assert "REAL" in window.windowTitle() and not window.buttons["START"].isEnabled()
    ready(controller, processes)
    window.render_snapshot(make_snapshot(backend.state))
    assert window.buttons["START"].isEnabled()
    window.buttons["START"].click()
    window.render_snapshot(make_snapshot(backend.state))
    assert not window.buttons["START"].isEnabled() and not window.buttons["STOP"].isEnabled()
    window.show()
    window.close()
    assert window.isVisible()
    complete(controller, processes)
    window.render_snapshot(make_snapshot(backend.state))
    assert "REAL" in window.footer.text() and window.design_board.blocks == []
    window.close()


def test_unsupported_controls_are_not_sent_to_robot(qapp, tmp_path):
    backend, controller, processes, emitted = make_trial(tmp_path)
    ready(controller, processes)
    assert backend.command(dict(command="START"))["accepted"]
    for name in ("STOP", "RESUME"):
        assert not backend.command(dict(command=name, job_id=backend.state["job_id"]))["accepted"]
    assert len(processes) == 2 and emitted == []
    complete(controller, processes)


def test_transfer_picture_uses_selected_slot_and_never_invents_assembly(qapp, tmp_path):
    from jsonschema import Draft202012Validator, RefResolver

    backend, controller, processes, _ = make_trial(tmp_path)
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.show()
    common = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    schema = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    store = {common["$id"]: common, urljoin(schema["$id"], "day4.schema.json"): common}
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store=store))
    for phase in ("before_check", "ready", "moving", "complete"):
        if phase == "ready":
            ready(controller, processes)
        elif phase == "moving":
            assert backend.command(dict(command="START"))["accepted"]
            controller._notice = "픽업 위치로 하강"
        elif phase == "complete":
            complete(controller, processes)
        snapshot = make_snapshot(backend.state)
        assert snapshot["transfer_target"] == dict(brick_type="2x2x1", color="blue", slot=5)
        validator.validate(snapshot)
        window.render_snapshot(snapshot)
        qapp.processEvents()
        assert window.target_board.transfer_target == snapshot["transfer_target"]
        assert window.target_board.blocks == [] and window.design_board.blocks == []
        assert window.table.item(0, 1).text() == "4점 (2×2)"
        assert window.table.item(1, 1).text() == "파랑"
        assert all(window.table.item(row, 1).text() == "미채택" for row in (2, 3, 4))
        assert "5번" in window.step_panel.title() and "조립 Plan 미채택" in window.progress.text()
        assert "파랑 4점 5번" in window.notice.toPlainText()
        assert backend.state["context"] is None and backend.state["current"]["current_revision"] == 0
        image = window.target_board.grab().toImage()
        assert any(image.pixelColor(x, y).name() == "#699bde" for x in range(image.width()) for y in range(image.height()))
    fake = json.loads((ROOT / "interfaces/fixtures/hmi.json").read_text())["snapshots"]["idle"]
    window.render_snapshot(fake)
    assert window.target_board.transfer_target is None
    window.close()


@pytest.mark.parametrize("change", ["bad_slot", "wrong_color", "placement_field", "fake_mode"])
def test_transfer_metadata_rejects_invalid_target_or_mode(qapp, tmp_path, change):
    backend, controller, processes, _ = make_trial(tmp_path)
    snapshot = make_snapshot(backend.state)
    if change == "fake_mode":
        snapshot = deepcopy(json.loads((ROOT / "interfaces/fixtures/hmi.json").read_text())["snapshots"]["idle"])
        snapshot["transfer_target"] = deepcopy(controller.target)
    elif change == "bad_slot":
        snapshot["transfer_target"]["slot"] = 7
    elif change == "wrong_color":
        snapshot["transfer_target"]["color"] = "red"
    else:
        snapshot["transfer_target"]["x"] = 0
    with pytest.raises(ValueError, match="transfer_target"):
        validate_hmi_snapshot(snapshot)
