"""실제 C/A/D/Qt 연결. 마이크·HTTP·ROS 자식 프로세스는 Mock; 장치 실행 없음."""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

import pytest
from jsonschema import Draft202012Validator, RefResolver
from PyQt5.QtCore import QProcess, QSize
from PyQt5.QtWidgets import QApplication

from app.c_design import llm, voice
from app.hmi_contracts import validate_hmi_snapshot
from app.qt_hmi import HmiWindow
from app.real_design_controller import RealDesignController, load_workflow_rows
from app.real_workflow_hmi import WorkflowTrial, main
from app.robot_trial import prepare_plan
from test_c_function_hmi import INITIAL, settled
from test_c_voice_hmi import audio
from test_real_workflow_hmi import Process, event, finish_delivery, manual

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "interfaces/robot_voice_workflow.json"
EVIDENCE = ROOT / "logs/real-voice-preparation"


@pytest.fixture
def create(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    trials = []

    def build(*, voice_mode=False, response=None, manifest=None):
        monkeypatch.setenv("C_DESIGN_USE_LLM", "1" if voice_mode else "0")
        config_path = tmp_path / f"manifest-{len(trials)}.json"
        config_path.write_text(json.dumps(manifest or json.loads(MANIFEST.read_text())))
        directory = tmp_path / str(len(trials))
        fixture = tmp_path / f"c-{len(trials)}.json"
        fixture.write_text(json.dumps(response or INITIAL))
        processes = []

        def factory(parent):
            process = Process(parent)
            processes.append(process)
            return process

        window = HmiWindow(screen_size=QSize(1920, 1080))
        controller = RealDesignController(config_path, directory, process_factory=factory)
        workflow = WorkflowTrial(window, controller, fixture, directory / "backend",
            c_mode="live" if voice_mode else None, c_voice=voice_mode)
        trials.append(workflow)
        window.show()
        assert controller.check()
        event(controller, "ROBOT_CHECK_COMPLETE", dict(motion_commands_sent=False))
        processes[-1].finished.emit(0, QProcess.NormalExit)
        qapp.processEvents()
        assert window.buttons["START"].isEnabled()
        return window, workflow, processes

    yield build
    for workflow in trials:
        if workflow.c_connection:
            workflow.c_connection.close()
            settled(workflow)
        workflow.controller.timer.stop()
        workflow.controller._operation = None  # Mock process cleanup; actual Robot stop 증거 아님.
        workflow.window.close()


def records(workflow):
    return [json.loads(line) for line in next(Path(workflow.backend._record.directory).glob("*.jsonl")).read_text().splitlines()]


def finish_confirmed_delivery(workflow, processes):
    controller = workflow.controller
    slot = controller.target["slot"]
    event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=slot, next_slot=slot+1 if slot < 6 else None))
    event(controller, "ROBOT_RELEASE_CONFIRMED", dict(slot=slot))
    event(controller, "ROBOT_RETURN_CONFIRMED", dict(robot_state=1, motion_status=0))
    finish_delivery(workflow, processes, proof=False)


def test_c_saved_chair_actual_a_fifteen_manual_steps_and_column_slots(create):
    window, workflow, processes = create()
    assert workflow.command(dict(command="START"))["accepted"]
    backend = workflow.backend
    schema = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    common = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema,
        store={common["$id"]: common, urljoin(schema["$id"], "day4.schema.json"): common}))
    assert backend.state["context"]["design"] == INITIAL["design"]
    assert len(backend.state["context"]["plan"]["steps"]) == 15
    assert len(processes) == 1 and not backend.state["current"]["blocks"]
    assert workflow.receive(manual(backend, "place_empty"))
    used = Counter()
    for index in range(15):
        target = backend._next_step()["after"]
        column = target["brick_type"], target["color"]
        used[column] += 1
        assert workflow.controller.target == dict(brick_type=column[0], color=column[1], slot=used[column])
        adopted_path = Path(processes[-1].started[0][1][3])
        adopted = json.loads(adopted_path.read_text())
        assert adopted["pick_line"]["brick_type"] == column[0]
        assert adopted["pick_line"]["color"] == column[1] and adopted["slot"] == used[column]
        assert adopted["settings"] == json.loads((ROOT / "interfaces/robot_trial_blue5.json").read_text())["settings"]
        current = backend.state["current"]
        finish_confirmed_delivery(workflow, processes)
        assert backend.state["current"] == current
        assert len(backend.state["context"]["confirmed_steps"]) == index
        assert backend.state["workflow_status"] == "WAIT_ASSEMBLY"
        value = manual(backend, "assembly")
        if index == 0:
            QApplication.instance().processEvents()
            EVIDENCE.mkdir(parents=True, exist_ok=True)
            assert window.grab().save(str(EVIDENCE / "chair-awaiting-first-assembly.png"))
        workflow.receive(value)
        QApplication.instance().processEvents()
        validate_hmi_snapshot(window._snapshot)
        validator.validate(window._snapshot)
        assert len(backend.state["context"]["confirmed_steps"]) == index + 1
        with pytest.raises(ValueError, match="닫힌"):
            workflow.receive(value)
        assert window.buttons["STOP"].isEnabled() == (index < 14)
        assert not window.buttons["RESUME"].isEnabled()
    assert backend.state["workflow_status"] == "COMPLETE"
    assert "15회 전달" in window.notice.toPlainText() and "3회 전달" not in window.notice.toPlainText()
    assert used == Counter({("2x3x1", "blue"): 6, ("2x3x1", "yellow"): 6, ("2x2x1", "blue"): 3})
    assert len(processes) == 16  # 1 check + 15 execute 요청; 실제 프로세스/ROS 실행은 없음.
    # Design 입력 순서와 A의 조립 순서는 다르다. 배치 여섯 필드와 개수를 비교한다.
    assert Counter(tuple(sorted(block.items())) for block in backend.state["current"]["blocks"]) == \
        Counter(tuple(sorted(block.items())) for block in backend.state["context"]["design"]["blocks"])
    supply = {(row["brick_type"], row["color"]): row["next_slot"] for row in window._snapshot["monitor"]["supply"]}
    assert supply == {("2x2x1", "yellow"): 1, ("2x2x1", "blue"): 4,
                      ("2x3x1", "yellow"): None, ("2x3x1", "blue"): None}
    log = records(workflow)
    assert sum(row["event"] == "STEP_CONFIRMED" for row in log) == 15
    assert any(row["event"] == "REAL_PLAN_PREFLIGHT" and row["result"]["robot_plan_accepted"] for row in log)
    (EVIDENCE / "mock-fifteen-step.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in log) + "\n")
    (EVIDENCE / "completed.snapshot.json").write_text(json.dumps(window._snapshot, ensure_ascii=False, indent=2))
    assert window.grab().save(str(EVIDENCE / "chair-complete.png"))


def test_voice_initial_uses_real_c_stt_llm_actual_a_but_waits_for_manual_empty(create, audio, monkeypatch):
    calls = []

    def http(payload, key):
        calls.append(deepcopy(payload))
        return dict(choices=[dict(message=dict(content=json.dumps(INITIAL["design"])))])

    monkeypatch.setattr(llm, "_post_json", http)
    window, workflow, processes = create(voice_mode=True)
    window.buttons["START"].click()
    settled(workflow)
    assert audio[1] == ["record", "stt"] and len(calls) == 1
    assert len(workflow.backend.state["context"]["plan"]["steps"]) == 15
    assert len(processes) == 1 and workflow.backend.state["place_check"] is not None
    assert window.design_board.blocks == INITIAL["design"]["blocks"]
    assert "STT/TTS LIVE" in window.notice.toPlainText()
    assert not any(row["event"].startswith("SYNTHETIC") for row in records(workflow))
    assert "mock-stt-secret" not in json.dumps(records(workflow))
    with pytest.raises(ValueError):
        workflow.receive(dict(event="observe"))
    assert len(processes) == 1
    workflow.receive(manual(workflow.backend, "place_empty"))
    assert len(processes) == 2
    for index in range(15):
        finish_confirmed_delivery(workflow, processes)
        assert len(workflow.backend.state["context"]["confirmed_steps"]) == index
        workflow.receive(manual(workflow.backend, "assembly"))
    assert workflow.backend.state["workflow_status"] == "COMPLETE" and len(processes) == 16
    log = records(workflow)
    assert sum(row["event"] == "STEP_CONFIRMED" for row in log) == 15
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "mock-voice-fifteen-step.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in log) + "\n")


@pytest.mark.parametrize("failure", ["silence", "provider"])
def test_initial_voice_failure_never_starts_movement(create, audio, monkeypatch, failure):
    if failure == "silence":
        audio[0][:] = [""]
    else:
        monkeypatch.setattr(voice, "listen", lambda: None)
    window, workflow, processes = create(voice_mode=True)
    window.buttons["START"].click()
    settled(workflow)
    assert workflow.backend.state["workflow_status"] == "HOLD"
    assert workflow.backend.state["context"] is None
    assert workflow.backend.state["current"]["blocks"] == [] and len(processes) == 1


@pytest.mark.parametrize("failure", ["too_few_slots", "geometry"])
def test_whole_plan_rejected_before_first_delivery_with_a_diagnosis_preserved(create, failure):
    manifest, response = json.loads(MANIFEST.read_text()), deepcopy(INITIAL)
    if failure == "too_few_slots":
        manifest["supply_rows"][-1]["first_slot"] = 5
    else:
        response["design"]["blocks"][0]["x"] = 23
    window, workflow, processes = create(manifest=manifest, response=response)
    workflow.command(dict(command="START"))
    assert workflow.backend.state["context"] is None and len(processes) == 1
    log = next(row["result"] for row in records(workflow) if row["event"] == "REAL_PLAN_PREFLIGHT")
    assert log["design"] == response["design"] and not log["robot_plan_accepted"]
    if failure == "too_few_slots":
        assert log["a_result"]["status"] == "READY" and "NEEDS_REFILL" in log["reason"]
    else:
        assert log["a_result"]["status"] == "INVALID" and log["a_result"]["errors"]


@pytest.mark.parametrize("failure", ["missing_return", "misplaced", "manifest_changed"])
def test_error_or_mismatch_preserves_actual_state_and_blocks_next_real_request(create, failure):
    window, workflow, processes = create()
    workflow.command(dict(command="START"))
    backend = workflow.backend
    workflow.receive(manual(backend, "place_empty"))
    if failure == "missing_return":
        event(workflow.controller, "ROBOT_PICK_CONFIRMED", dict(slot=1, next_slot=2))
        event(workflow.controller, "ROBOT_RELEASE_CONFIRMED", dict(slot=1))
        finish_delivery(workflow, processes, proof=False)
    else:
        finish_delivery(workflow, processes)
        confirmation = manual(backend, "assembly")
        if failure == "misplaced":
            target = backend._next_step()["after"]
            confirmation.update(confirmed=False, actual=dict(target, color="yellow"))
        else:
            changed = json.loads(workflow.controller.manifest_path.read_text())
            changed["config_id"] = "changed-after-start"
            workflow.controller.manifest_path.write_text(json.dumps(changed))
        workflow.receive(confirmation)
    assert backend.state["workflow_status"] == "HOLD" and len(processes) == 2
    assert len(backend.state["context"]["confirmed_steps"]) == (1 if failure == "manifest_changed" else 0)
    assert backend.state["current"]["current_revision"] == (0 if failure == "missing_return" else 1)
    assert not workflow.command(dict(command="RESUME", job_id=backend.state["job_id"]))["accepted"]


def test_all_four_rows_all_slots_use_measured_sources_without_mutating_them():
    manifest, rows = load_workflow_rows(MANIFEST)
    base = rows["2x2x1", "blue"]
    source_path = Path(base["source_path"])
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    measured = json.loads(Path(manifest["measurements_path"]).read_text())["lines"]
    for (brick, color), original in rows.items():
        line = measured[f"{color}_{4 if brick == '2x2x1' else 6}"]
        for slot in range(1, 7):
            config = dict(deepcopy(original), slot=slot)
            source, settings, commands = prepare_plan(config)
            assert source.START == line["start"] and source.END == line["end"]
            assert sum(kind == "grip_close" for kind, label, target, number in commands) == 1
            assert {number for kind, label, target, number in commands if number is not None} == {slot}
            pick = next(target for kind, label, target, number in commands if kind == "line_local")
            assert pick[:3] == pytest.approx(line["blocks"][slot-1]["xyz"])
            assert commands[-1][2] == config["observe_posj"]
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before


def test_wrong_goal_duplicate_pick_and_execution_cannot_switch_or_consume_other_row(create):
    window, workflow, processes = create()
    workflow.command(dict(command="START"))
    backend, controller = workflow.backend, workflow.controller
    wrong = dict(execution_id="wrong", brick_type="2x2x1", color="yellow")
    assert controller.deliver(wrong) == dict(accepted=False, reason="PLAN_TARGET_MISMATCH")
    assert len(processes) == 1
    workflow.receive(manual(backend, "place_empty"))
    identity = backend.state["execution_id"]
    goal = dict(execution_id=identity, brick_type="2x3x1", color="blue")
    assert controller.deliver(goal) == dict(accepted=False, reason="DUPLICATE")
    assert controller.deliver(dict(goal, execution_id="another")) == dict(accepted=False, reason="BUSY")
    event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=1, next_slot=2))
    event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=1, next_slot=3))
    controller._poll()
    slots = {(row["brick_type"], row["color"]): row["next_slot"] for row in controller.state["supply"]}
    assert slots == {("2x2x1", "yellow"): 1, ("2x2x1", "blue"): 1,
                     ("2x3x1", "yellow"): 1, ("2x3x1", "blue"): 2}
    assert len(processes) == 2 and backend.state["current"]["blocks"] == []


@pytest.mark.parametrize("change", ["mode", "route", "duplicate", "hash"])
def test_unverified_or_changed_row_setup_is_rejected_before_process_creation(tmp_path, change):
    value = json.loads(MANIFEST.read_text())
    if change == "mode":
        value["mode"] = "FAKE"
    elif change == "route":
        value["supply_rows"][-1]["return_route_verified"] = False
    elif change == "duplicate":
        value["supply_rows"][-1] = value["supply_rows"][0]
    else:
        value["measurements_sha256"] = "changed"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_workflow_rows(path)


@pytest.mark.parametrize("arguments", [
    ["--c-mode", "offline"],
    ["--supply-manifest", str(MANIFEST), "--first-slot", "2"],
    ["--supply-manifest", str(MANIFEST), "--c-mode", "live", "--c-fixture", "ignored.json"],
])
def test_ambiguous_real_scope_or_slot_flags_fail_before_window_and_device(arguments):
    with pytest.raises(SystemExit) as error:
        main(["--real-workflow", "--config", str(ROOT / "interfaces/robot_trial_blue5.json"), *arguments])
    assert error.value.code == 2


def test_failed_observe_start_check_is_visible_and_cannot_enable_start(create):
    window, workflow, processes = create()
    controller = workflow.controller
    assert controller.check()
    event(controller, "ROBOT_TRIAL_RESULT", dict(execution_id=controller._identity,
                                                success=False, reason="OBSERVE_POSE_MISMATCH"))
    processes[-1].finished.emit(1, QProcess.NormalExit)
    QApplication.instance().processEvents()
    assert not controller.state["ready_at_observe"]
    assert controller.state["fault"] == "OBSERVE_POSE_MISMATCH"
    assert "OBSERVE_POSE_MISMATCH" in window.notice.toPlainText()
    assert window._snapshot["notice"]["reason"] == "OBSERVE_POSE_MISMATCH"
    assert window._snapshot["monitor"]["robot"]["status"] == "ERROR"
    assert not window.buttons["START"].isEnabled()
    assert not workflow.command(dict(command="START"))["accepted"]
    assert workflow.backend.state["job_id"] is None and len(processes) == 2
    assert all("--check" in process.started[0][1] for process in processes)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(EVIDENCE / "observe-start-failed.png"))


@pytest.mark.parametrize("outcome", ["success", "failure", "missing_proof"])
def test_prepare_button_goes_through_backend_without_job_pick_or_refill(create, outcome):
    window, workflow, processes = create()
    schema = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    common = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema,
        store={common["$id"]: common, urljoin(schema["$id"], "day4.schema.json"): common}))
    command_validator = Draft202012Validator({**schema, "$ref": "#/$defs/command"}, resolver=validator.resolver)
    command_validator.validate(dict(command="PREPARE_OBSERVE"))
    assert not command_validator.is_valid(dict(command="PREPARE_OBSERVE", job_id="unused"))
    controller = workflow.controller
    assert controller.check()
    event(controller, "ROBOT_TRIAL_RESULT", dict(execution_id=controller._identity,
                                                success=False, reason="OBSERVE_POSE_MISMATCH"))
    processes[-1].finished.emit(1, QProcess.NormalExit)
    QApplication.instance().processEvents()
    before = deepcopy(controller.state["supply"])
    assert window.buttons["PREPARE_OBSERVE"].isVisible()
    assert window.buttons["PREPARE_OBSERVE"].isEnabled()
    validator.validate(window._snapshot)
    window.buttons["PREPARE_OBSERVE"].click()
    QApplication.instance().processEvents()
    assert "--prepare-observe" in processes[-1].started[0][1]
    assert not window.buttons["START"].isEnabled() and not window.buttons["PREPARE_OBSERVE"].isEnabled()
    assert window._snapshot["monitor"]["robot"]["status"] == "BUSY"
    validator.validate(window._snapshot)
    if outcome == "success":
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(EVIDENCE / "prepare-observe-moving.png"))
    assert not workflow.command(dict(command="PREPARE_OBSERVE"))["accepted"]
    if outcome == "success":
        event(controller, "ROBOT_PREPARE_COMPLETE", dict(ready_at_observe=True, motion_commands_sent=True))
    elif outcome == "failure":
        event(controller, "ROBOT_TRIAL_RESULT", dict(execution_id=controller._identity,
                                                    success=False, reason="PREPARE_MOTION_FAILED"))
    processes[-1].finished.emit(1 if outcome == "failure" else 0, QProcess.NormalExit)
    QApplication.instance().processEvents()
    assert controller.state["supply"] == before
    assert workflow.backend.state["job_id"] is None and workflow.backend.state["current"]["blocks"] == []
    assert window.buttons["START"].isEnabled() == (outcome == "success")
    assert not window.buttons["PREPARE_OBSERVE"].isEnabled()
    validator.validate(window._snapshot)
    assert not workflow.command(dict(command="PREPARE_OBSERVE"))["accepted"]
    if outcome == "success":
        assert "사전 이동 HOME→observe 도착/대기 확인 완료" in window.notice.toPlainText()
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(EVIDENCE / "prepare-observe-ready.png"))
        window.buttons["START"].click()
        QApplication.instance().processEvents()
        assert workflow.backend.state["job_id"] is not None
        assert not window.buttons["PREPARE_OBSERVE"].isVisible()
        assert len(processes) == 3  # 두 check + 사전 이동; 블록 전달은 아직 없음.
    else:
        assert "사전 이동 실패:" in window.notice.toPlainText()
        assert window._snapshot["monitor"]["robot"]["status"] == "ERROR"
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(EVIDENCE / f"prepare-observe-{outcome}.png"))


def test_prepare_action_rejected_in_fake_snapshot_and_after_real_job(create):
    window, workflow, processes = create()
    snapshot = deepcopy(window._snapshot)
    snapshot["monitor"]["robot"]["mode"] = "FAKE"
    with pytest.raises(ValueError):
        validate_hmi_snapshot(snapshot)
    workflow.command(dict(command="START"))
    assert not workflow.command(dict(command="PREPARE_OBSERVE"))["accepted"]
    assert len(processes) == 1
