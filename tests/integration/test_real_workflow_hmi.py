from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urljoin

from jsonschema import Draft202012Validator, RefResolver
import pytest
from PyQt5.QtCore import QObject, QProcess, QSize, pyqtSignal
from PyQt5.QtWidgets import QApplication

from app.hmi_contracts import validate_hmi_snapshot
from app.qt_hmi import HmiWindow
from app.real_trial_hmi import RealTrialController
from app.robot_trial import load_trial_config
from workflow_support import WorkflowTrial


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


def event(controller, name, payload):
    path = controller.directory / "driver" / f"{controller._identity}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(dict(execution_id=controller._identity, event=name, payload=payload)) + "\n")


@pytest.fixture
def trial(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = HmiWindow(screen_size=QSize(1920, 1080))
    processes = []

    def factory(parent):
        process = Process(parent)
        processes.append(process)
        return process

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(load_trial_config(ROOT / "interfaces/robot_trial_blue5.json")))
    fixture_path = tmp_path / "c.json"
    fixture_path.write_text((ROOT / "interfaces/fixtures/c_three_blue4.json").read_text())
    controller = RealTrialController(config_path, tmp_path / "driver", brick_type="2x2x1", color="blue",
                                     slot=1, delivery_limit=3, process_factory=factory)
    trial = WorkflowTrial(window, controller, fixture_path, tmp_path / "backend")
    window.show()
    application.processEvents()
    yield application, window, trial, processes
    controller.timer.stop()
    controller._operation = None  # 모의 프로세스만 종료한다. 실제 Robot stop 증거가 아니다.
    window.close()


def ready_and_start(trial):
    application, window, workflow, processes = trial
    assert workflow.controller.check()
    event(workflow.controller, "ROBOT_CHECK_COMPLETE", dict(motion_commands_sent=False))
    processes[-1].finished.emit(0, QProcess.NormalExit)
    application.processEvents()
    window.buttons["START"].click()
    application.processEvents()
    return workflow.backend


def manual(backend, event_name):
    key = "place_check" if event_name == "place_empty" else "active_check"
    return dict(event=event_name, check_id=backend.state[key]["check_id"], confirmed=True)


def finish_delivery(workflow, processes, *, proof=True, success=True, crash=False):
    controller = workflow.controller
    slot = controller.target["slot"]
    if proof:
        event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=slot, next_slot=slot+1))
        event(controller, "ROBOT_RELEASE_CONFIRMED", dict(slot=slot))
        event(controller, "ROBOT_RETURN_CONFIRMED", dict(robot_state=1, motion_status=0))
    event(controller, "ROBOT_TRIAL_RESULT", dict(execution_id=controller._identity, success=success,
                                               reason=None if success else "PICK_FAILED"))
    processes[-1].finished.emit(-6 if crash else 0, QProcess.CrashExit if crash else QProcess.NormalExit)


def test_actual_a_three_steps_use_slots_123_manual_checks_and_same_real_hmi(trial):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    assert len(processes) == 1  # START는 Design/A 계산만 수행한다.
    assert len(backend.state["context"]["plan"]["steps"]) == 3
    assert window._snapshot["manual_trial"] is True and len(window.design_board.blocks) == 3
    schema = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    common = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    store = {common["$id"]: common, urljoin(schema["$id"], "day4.schema.json"): common}
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store=store))
    assert workflow.receive(manual(backend, "place_empty"))
    identities = []
    for index in range(3):
        identities.append(backend.state["execution_id"])
        if index:
            assert not backend.on_robot_result(dict(execution_id=identities[-2], success=True, reason=None))
            assert backend.state["execution_id"] == identities[-1]
        assert workflow.controller.target["slot"] == index+1
        assert len(processes) == index+2
        current = backend.state["current"]
        finish_delivery(workflow, processes)
        assert backend.state["current"] == current
        assert len(backend.state["context"]["confirmed_steps"]) == index
        assert backend.state["workflow_status"] == "WAIT_ASSEMBLY"
        confirmation = manual(backend, "assembly")
        assert workflow.receive(confirmation)
        with pytest.raises(ValueError, match="닫힌"):
            workflow.receive(confirmation)
        assert backend.state["current"]["current_revision"] == index+1
        application.processEvents()
        validator.validate(window._snapshot)
        assert window.buttons["STOP"].isEnabled() == (index < 2)
        assert not window.buttons["RESUME"].isEnabled()
    assert len(set(identities)) == 3
    assert backend.state["workflow_status"] == "COMPLETE"
    assert backend.state["current"]["blocks"] == backend.state["context"]["design"]["blocks"]
    assert window._snapshot["progress"] == dict(completed=3, total=3)
    assert "Camera 미연결" in window.footer.text()
    assert not workflow.command(dict(command="START"))["accepted"]
    assert len(processes) == 4
    assert not workflow.controller.deliver(dict(execution_id="fourth", brick_type="2x2x1", color="blue"))["accepted"]
    assert len(processes) == 4
    records = [json.loads(line) for line in next(Path(workflow.backend._record.directory).glob("*.jsonl")).read_text().splitlines()]
    assert len([row for row in records if row["event"] == "MANUAL_FIELD_CONFIRMATION"]) == 4
    assert len([row for row in records if row["event"] == "STEP_CONFIRMED"]) == 3


@pytest.mark.parametrize("stage", ["unready", "before_start", "moving", "old_check", "not_confirmed"])
def test_manual_input_cannot_start_an_unconfirmed_or_duplicate_delivery(trial, stage):
    application, window, workflow, processes = trial
    if stage in ("unready", "before_start"):
        value = dict(event="place_empty", check_id="not-open", confirmed=True)
        if stage == "unready":
            assert not workflow.command(dict(command="START"))["accepted"]
    else:
        backend = ready_and_start(trial)
        value = manual(backend, "place_empty")
        if stage == "moving":
            assert workflow.receive(value)
        elif stage == "old_check":
            value["check_id"] = "old-check"
        else:
            value["confirmed"] = False
    count = len(processes)
    with pytest.raises(ValueError):
        workflow.receive(value)
    assert len(processes) == count
    assert workflow.backend.state["current"] == dict(current_revision=0, blocks=[])


@pytest.mark.parametrize("failure", ["driver_failure", "missing_proof", "crash", "config_changed"])
def test_failure_or_config_change_blocks_next_pick_and_keeps_current(trial, failure):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    assert workflow.receive(manual(backend, "place_empty"))
    if failure == "config_changed":
        finish_delivery(workflow, processes)
        config = json.loads(workflow.controller.config_path.read_text())
        config["settings"]["joint_speed"] = 19
        workflow.controller.config_path.write_text(json.dumps(config))
        assert workflow.receive(manual(backend, "assembly"))
        assert backend.state["current"]["current_revision"] == 1
    else:
        finish_delivery(workflow, processes, proof=failure != "missing_proof",
                        success=failure != "driver_failure", crash=failure == "crash")
        assert backend.state["current"]["current_revision"] == 0
    assert backend.state["workflow_status"] == "HOLD" and backend.state["fault"]
    assert len(processes) == 2
    assert not workflow.command(dict(command="RESUME", job_id=backend.state["job_id"]))["accepted"]


@pytest.mark.parametrize("change", ["too_many", "wrong_color", "outside_board"])
def test_invalid_design_never_sends_execute(trial, change):
    application, window, workflow, processes = trial
    response = json.loads(workflow.fixture_path.read_text())
    if change == "too_many":
        response["design"]["blocks"].append(deepcopy(response["design"]["blocks"][0]))
    elif change == "wrong_color":
        response["design"]["blocks"][0]["color"] = "yellow"
    else:
        response["design"]["blocks"][-1]["x"] = 23  # 구조 허용 범위지만 실제 A 기하 검사에서 INVALID.
    workflow.fixture_path.write_text(json.dumps(response))
    ready_and_start(trial)
    assert workflow.backend.state["context"] is None
    assert len(processes) == 1


def test_manual_real_contract_does_not_enable_fake_mode_or_second_job(trial):
    application, window, workflow, processes = trial
    ready_and_start(trial)
    snapshot = deepcopy(window._snapshot)
    snapshot["monitor"]["robot"]["mode"] = "FAKE"
    with pytest.raises(ValueError, match="manual_trial"):
        validate_hmi_snapshot(snapshot)


@pytest.mark.parametrize("missing", ["pick", "release", "return"])
def test_first_delivery_proof_cannot_complete_second_delivery(trial, missing):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    workflow.receive(manual(backend, "place_empty"))
    finish_delivery(workflow, processes)
    workflow.receive(manual(backend, "assembly"))
    controller = workflow.controller
    proofs = dict(pick=("ROBOT_PICK_CONFIRMED", dict(slot=2, next_slot=3)),
                  release=("ROBOT_RELEASE_CONFIRMED", dict(slot=2)),
                  return_=("ROBOT_RETURN_CONFIRMED", dict(robot_state=1, motion_status=0)))
    for name, (kind, payload) in proofs.items():
        if name.rstrip("_") != missing:
            event(controller, kind, payload)
    finish_delivery(workflow, processes, proof=False)
    assert backend.state["workflow_status"] == "HOLD"
    assert backend.state["fault"] == "DELIVERY_EVIDENCE_MISSING"
    assert backend.state["current"]["current_revision"] == 1
    assert len(processes) == 3


def test_manual_confirmation_log_failure_prevents_next_delivery(trial):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    workflow.receive(manual(backend, "place_empty"))
    finish_delivery(workflow, processes)

    def broken_log(record):
        raise OSError("disk unavailable")

    backend._record = broken_log
    assert workflow.receive(manual(backend, "assembly")) is False
    assert backend.state["workflow_status"] == "HOLD"
    assert "LOG_FAILED" in backend.state["fault"]
    assert backend.state["current"]["current_revision"] == 0
    assert len(processes) == 2


@pytest.mark.parametrize("previous_steps", [0, 1, 2])
@pytest.mark.parametrize("with_actual", [False, True])
def test_wrong_placement_report_logs_holds_and_displays_goal_without_next_pick(trial, previous_steps, with_actual, capsys):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    workflow.receive(manual(backend, "place_empty"))
    for _ in range(previous_steps):
        finish_delivery(workflow, processes)
        workflow.receive(manual(backend, "assembly"))
    finish_delivery(workflow, processes)
    state = backend.state
    value = manual(backend, "assembly")
    value["confirmed"] = False
    target = deepcopy(state["context"]["plan"]["steps"][previous_steps]["after"])
    if with_actual:
        value["actual"] = dict(target, x=9)
    assert workflow.receive(value)
    application.processEvents()
    current = backend.state
    assert current["workflow_status"] == "HOLD" and current["reason"] == "MANUAL_ASSEMBLY_MISMATCH"
    assert len(current["context"]["confirmed_steps"]) == previous_steps
    assert current["context"]["base_current"] == state["context"]["base_current"]
    assert len(processes) == previous_steps + 2
    assert window._snapshot["step"]["target"] == target
    assert '"next_delivery": false' in capsys.readouterr().out
    if with_actual:
        assert current["current"]["current_revision"] == state["current"]["current_revision"] + 1
        assert current["current"]["blocks"] == state["current"]["blocks"] + [value["actual"]]
        assert current["comparison"] == "MISMATCH"
        assert current["difference"]["missing"] == [target]
        assert current["difference"]["unexpected"] == [value["actual"]]
        assert window.table.item(2,1).text() == f"({target['x']}, {target['y']})"
        assert window.table.item(2,2).text() == "(9, 5)"
        assert window.table.horizontalHeaderItem(2).text() == "현장 입력"
        assert window.target_board.reported_placement == value["actual"]
        assert "Camera 미연결" in window.footer.text()
        schema = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
        common = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
        store = {common["$id"]:common, urljoin(schema["$id"], "day4.schema.json"):common}
        Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store=store)).validate(window._snapshot)
    else:
        assert current["current"] == state["current"]
        assert current["last_observation"] == state["last_observation"]
        assert "reported_placement" not in window._snapshot
    with pytest.raises(ValueError, match="닫힌"):
        workflow.receive(value)
    value["confirmed"] = True
    value.pop("actual", None)
    with pytest.raises(ValueError, match="닫힌"):
        workflow.receive(value)
    assert not backend.on_robot_result(dict(execution_id="late", success=True, reason=None))
    assert len(processes) == previous_steps + 2
    records=[json.loads(line) for line in next(Path(backend._record.directory).glob('*.jsonl')).read_text().splitlines()]
    assert len([row for row in records if row["event"] == "MANUAL_ASSEMBLY_MISMATCH"]) == 1
    assert not any(row["event"] == "JOB_COMPLETED" for row in records)


def test_third_delivery_and_waiting_ui_never_complete_before_manual_confirmation(trial):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    workflow.receive(manual(backend, "place_empty"))
    for _ in range(2):
        finish_delivery(workflow, processes)
        workflow.receive(manual(backend, "assembly"))
    before = backend.state["current"]
    finish_delivery(workflow, processes)
    application.processEvents()
    assert backend.state["current"] == before
    assert window._snapshot["workflow_status"] == "WAIT_ASSEMBLY"
    assert window._snapshot["progress"] == dict(completed=2, total=3)
    assert window._snapshot["step"]["target"]["x"] == 7
    assert window.status.text() == "사람 조립 관측 대기"
    assert "완료" not in window.status.text()
    records = [json.loads(line) for line in next(Path(backend._record.directory).glob('*.jsonl')).read_text().splitlines()]
    assert not any(row["event"] == "JOB_COMPLETED" for row in records)
    workflow.receive(manual(backend, "assembly"))
    application.processEvents()
    assert window._snapshot["progress"] == dict(completed=3, total=3)
    assert window.status.text() == "전체 조립 완료"


@pytest.mark.parametrize("change", ["bad_bool", "place_false", "same_goal", "outside", "overlap", "actual_with_true"])
def test_invalid_wrong_placement_report_changes_neither_current_nor_check(trial, change):
    application, window, workflow, processes = trial
    backend=ready_and_start(trial)
    workflow.receive(manual(backend,"place_empty"))
    finish_delivery(workflow,processes)
    workflow.receive(manual(backend,"assembly"))
    finish_delivery(workflow,processes)
    before=backend.state
    value=manual(backend,"assembly")
    value["confirmed"]=False
    target=before["context"]["plan"]["steps"][1]["after"]
    if change=="bad_bool": value["confirmed"]=0
    elif change=="place_false": value["event"]="place_empty"
    elif change=="same_goal": value["actual"]=target
    elif change=="outside": value["actual"]=dict(target,x=23)
    elif change=="overlap": value["actual"]=dict(target,x=3)
    else:
        value.update(confirmed=True,actual=dict(target,x=10))
    with pytest.raises(ValueError): workflow.receive(value)
    assert backend.state==before
    assert len(processes)==3


def test_wrong_report_log_failure_cannot_adopt_actual_or_issue_next_pick(trial):
    application,window,workflow,processes=trial
    backend=ready_and_start(trial)
    workflow.receive(manual(backend,"place_empty"))
    finish_delivery(workflow,processes)
    value=manual(backend,"assembly")
    value.update(confirmed=False,actual=dict(backend._next_step()["after"],x=10))
    def fail(record): raise OSError("report disk failure")
    backend._record=fail
    assert not workflow.receive(value)
    assert backend.state["current"]==dict(current_revision=0,blocks=[])
    assert backend.state["workflow_status"]=="HOLD" and backend.state["fault"]
    assert len(processes)==2


def test_same_position_wrong_color_displays_color_difference_and_keeps_design(trial):
    application,window,workflow,processes=trial
    backend=ready_and_start(trial)
    workflow.receive(manual(backend,"place_empty"))
    finish_delivery(workflow,processes)
    value=manual(backend,"assembly")
    value.update(confirmed=False,actual=dict(backend._next_step()["after"],color="yellow"))
    assert workflow.receive(value)
    application.processEvents()
    assert window.table.item(1,1).text()=="파랑" and window.table.item(1,2).text()=="노랑"
    assert backend.state["context"]["design"]["blocks"][0]["color"]=="blue"
    assert backend.state["current"]["blocks"][0]["color"]=="yellow"
    assert len(processes)==2


@pytest.mark.parametrize("invalid", ["fake_mode", "no_manual", "no_observed", "match", "unreported_block"])
def test_reported_placement_display_rejects_wrong_source_or_observation(trial,invalid):
    application,window,workflow,processes=trial
    backend=ready_and_start(trial)
    workflow.receive(manual(backend,"place_empty"))
    finish_delivery(workflow,processes)
    value=manual(backend,"assembly")
    value.update(confirmed=False,actual=dict(backend._next_step()["after"],x=10))
    workflow.receive(value)
    application.processEvents()
    snapshot=deepcopy(window._snapshot)
    if invalid=="fake_mode": snapshot["monitor"]["robot"]["mode"]="FAKE"
    elif invalid=="no_manual": snapshot.pop("manual_trial")
    elif invalid=="no_observed": snapshot["step"]["observed"]=None
    elif invalid=="match": snapshot["step"]["comparison"]="MATCH"
    else: snapshot["reported_placement"]["x"]=12
    with pytest.raises(ValueError): validate_hmi_snapshot(snapshot)
