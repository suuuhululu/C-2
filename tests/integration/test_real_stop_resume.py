"""REAL 소비 경로를 Mock QProcess로 검사한다. 실제 장치 명령은 보내지 않는다."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QApplication

from test_real_workflow_hmi import trial, ready_and_start, manual, finish_delivery, event
from test_real_voice_workflow import create

EVIDENCE = Path(__file__).resolve().parents[2] / "logs/real-stop-resume"


def pause_event(controller, name, payload):
    identity = controller._stop["request_id"]
    path = controller.directory / "pause" / f"{identity}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(dict(execution_id=identity, event=name, payload=payload)) + "\n")


def probe(controller, *, block_state="UNPICKED", index=0, at_observe=True):
    pause_event(controller, "ROBOT_STOP_PROBE", dict(stopped=True, at_observe=at_observe,
        checkpoint=dict(block_state=block_state, command_index=index,
                        consumed=block_state != "UNPICKED", released=block_state == "RELEASED")))
    controller._pause_process.finished.emit(0, QProcess.NormalExit)
    QApplication.instance().processEvents()


@pytest.mark.parametrize("stage", ["initial_failure", "place_wait", "assembly_wait", "partial_current"])
def test_stop_resume_keeps_job_design_current_and_refreshes_check_without_motion(trial, stage):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    if stage == "initial_failure":
        backend._state["context"] = None  # C FAILED 뒤 목표 미채택 상태 Fixture.
        backend._hold("CALL_FAILED planner: UNSUPPORTED_OBJECT")
    elif stage in ("assembly_wait", "partial_current"):
        workflow.receive(manual(backend, "place_empty"))
        finish_delivery(workflow, processes)
        if stage == "partial_current":
            workflow.receive(manual(backend, "assembly"))
            finish_delivery(workflow, processes)
    workflow.publish()
    before = backend.state
    assert window.buttons["STOP"].isEnabled()
    window.buttons["STOP"].click()
    application.processEvents()
    assert backend.state["reason"] == "STOP_PENDING"
    assert not window.buttons["RESUME"].isEnabled()
    assert "--probe" in processes[-1].started[0][1] and "--stop" not in processes[-1].started[0][1]
    probe(workflow.controller)
    assert backend.state["workflow_status"] == "STOPPED"
    assert window.buttons["RESUME"].isEnabled() and not window.buttons["STOP"].isEnabled()
    assert backend.state["job_id"] == before["job_id"] and backend.state["current"] == before["current"]
    assert backend.state["context"] == before["context"]
    if before["active_check"]:
        with pytest.raises(ValueError, match="닫힌"):
            workflow.receive(dict(event="assembly", check_id=before["active_check"]["check_id"], confirmed=True))
    count = len(processes)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(EVIDENCE / f"{stage}-stopped.png"))
    window.buttons["RESUME"].click()
    application.processEvents()
    assert backend.state["job_id"] == before["job_id"] and backend.state["current"] == before["current"]
    assert len(processes) == count  # 정지된 조립/음성 대기의 재개에는 새 이동 없음.
    if stage == "initial_failure":
        assert backend.state["context"] is not None and backend.state["place_check"]
    elif before["active_check"]:
        assert backend.state["workflow_status"] == "WAIT_ASSEMBLY"
        assert backend.state["active_check"]["check_id"] != before["active_check"]["check_id"]
    else:
        assert backend.state["place_check"]["check_id"] != before["place_check"]["check_id"]
    assert window.buttons["STOP"].isEnabled() and not window.buttons["RESUME"].isEnabled()


@pytest.mark.parametrize("block_state,index", [("UNPICKED", 0), ("HOLDING", 6), ("RELEASED", 15)])
@pytest.mark.parametrize("finish_first", [False, True])
def test_stop_ack_and_old_process_exit_both_required_before_resume(trial, block_state, index, finish_first):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    workflow.receive(manual(backend, "place_empty"))
    controller = workflow.controller
    old_process, old_id = controller.process, controller._identity
    before = deepcopy(backend.state)
    assert workflow.command(dict(command="STOP", job_id=before["job_id"]))["accepted"]
    assert (controller.directory / f"{old_id}.stop").exists()
    assert "--stop" in controller._pause_process.started[0][1]
    stop_process = controller._pause_process
    if finish_first:
        old_process.finished.emit(2, QProcess.NormalExit)
    pause_event(controller, "ROBOT_STOP_ACK", dict(request_id=controller._stop["request_id"]))
    stop_process.finished.emit(0, QProcess.NormalExit)
    assert not window.buttons["RESUME"].isEnabled()
    if not finish_first:
        assert controller._pause_process is stop_process  # 이전 실행 중에는 확인 probe도 시작 안 함.
        old_process.finished.emit(2, QProcess.NormalExit)
    assert "--probe" in controller._pause_process.started[0][1]
    probe(controller, block_state=block_state, index=index, at_observe=False)
    assert backend.state["workflow_status"] == "STOPPED"
    assert backend.state["current"] == before["current"]
    assert len(backend.state["context"]["confirmed_steps"]) == 0
    assert controller.state["supply"][1]["next_slot"] == (1 if block_state == "UNPICKED" else 2)
    assert not backend.on_robot_result(dict(execution_id=old_id, success=True, reason=None))
    assert workflow.command(dict(command="RESUME", job_id=before["job_id"]))["accepted"]
    new_id = controller._identity
    assert new_id != old_id and "--resume-checkpoint" in processes[-1].started[0][1]
    assert controller.target["slot"] == 1 and controller._attempts == 1
    if block_state == "UNPICKED":
        event(controller, "ROBOT_PICK_CONFIRMED", dict(slot=1, next_slot=2))
    event(controller, "ROBOT_RELEASE_CONFIRMED", dict(slot=1))
    event(controller, "ROBOT_RETURN_CONFIRMED", dict(robot_state=1, motion_status=0))
    event(controller, "ROBOT_TRIAL_RESULT", dict(execution_id=new_id, success=True, reason=None))
    controller.process.finished.emit(0, QProcess.NormalExit)
    application.processEvents()
    assert backend.state["workflow_status"] == "WAIT_ASSEMBLY" and backend.state["current"] == before["current"]
    assert controller.state["supply"][1]["next_slot"] == 2
    assert not workflow.command(dict(command="RESUME", job_id=before["job_id"]))["accepted"]


@pytest.mark.parametrize("failure", ["probe_missing", "probe_failed", "unknown", "old_request"])
def test_unconfirmed_stop_cannot_enable_resume_or_launch_pick(trial, failure):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    before = backend.state
    workflow.command(dict(command="STOP", job_id=before["job_id"]))
    controller = workflow.controller
    if failure == "old_request":
        assert not backend.on_stopped(str(uuid4()), stopped=True, execution_ended=True, block_state_known=True)
    elif failure == "unknown":
        probe(controller, block_state="UNKNOWN")
    else:
        if failure == "probe_failed":
            pause_event(controller, "ROBOT_STOP_FAILED", dict(reason="GRIPPER_STATE_UNREADABLE"))
        controller._pause_process.finished.emit(1 if failure == "probe_failed" else 0, QProcess.NormalExit)
        application.processEvents()
    assert not window.buttons["RESUME"].isEnabled()
    assert not workflow.command(dict(command="RESUME", job_id=before["job_id"]))["accepted"]
    assert backend.state["current"] == before["current"] and len(processes) == 2


def test_short_operator_commands_use_only_open_check_and_log_full_confirmation(trial):
    application, window, workflow, processes = trial
    backend = ready_and_start(trial)
    before = backend.state["place_check"]["check_id"]
    assert workflow.receive(dict(event="place_empty"))
    with pytest.raises(ValueError):
        workflow.receive(dict(event="assembly"))  # 전달 중 확인 불가.
    finish_delivery(workflow, processes)
    assembly_id = backend.state["active_check"]["check_id"]
    assert workflow.receive(dict(event="assembly"))
    assert backend.state["current"]["current_revision"] == 1 and len(processes) == 3
    with pytest.raises(ValueError):
        workflow.receive(dict(event="assembly", check_id=assembly_id, confirmed=True))
    rows = [json.loads(line) for line in next(Path(backend._record.directory).glob("*.jsonl")).read_text().splitlines()]
    confirmations = [r["result"] for r in rows if r["event"] == "MANUAL_FIELD_CONFIRMATION"]
    assert [r["check_id"] for r in confirmations] == [before, assembly_id]
    assert all(r["confirmed"] is True for r in confirmations)


def test_voice_stop_waits_for_old_call_and_resume_listens_again_in_same_job(create, monkeypatch):
    from threading import Event
    from app.c_design import main as c_main, voice
    from test_c_function_hmi import INITIAL, settled
    gate, recording = Event(), Event()
    designs = []
    def listen():
        recording.set()
        assert gate.wait(5)
        return "의자 만들어줘"
    def design(**kwargs):
        designs.append(kwargs["text"])
        return deepcopy(INITIAL)
    monkeypatch.setattr(voice, "listen", listen)
    monkeypatch.setattr(voice, "last_error", lambda: None)
    monkeypatch.setattr(c_main, "create_initial_design", design)
    window, workflow, processes = create(voice_mode=True)
    controller, backend = workflow.controller, workflow.backend
    try:
        workflow.command(dict(command="START"))
        assert recording.wait(2)
        before = backend.state
        workflow.command(dict(command="STOP", job_id=before["job_id"]))
        assert workflow.c_connection.active[2].is_set()
        probe(controller)
        assert window.buttons["RESUME"].isEnabled()
        assert workflow.command(dict(command="RESUME", job_id=before["job_id"]))["reason"] == "C_CALL_STILL_ENDING"
        assert backend.state["workflow_status"] == "STOPPED" and designs == []
        gate.set()
        settled(workflow)
        assert backend.state["context"] is None and designs == []
        assert workflow.command(dict(command="RESUME", job_id=before["job_id"]))["accepted"]
        settled(workflow)
        assert designs == ["의자 만들어줘"] and len(backend.state["context"]["plan"]["steps"]) == 15
        assert backend.state["job_id"] == before["job_id"] and backend.state["current"] == before["current"]
        assert len(processes) == 2  # 처음 check와 STOP 상태 probe뿐. 이동 없음.
    finally:
        gate.set()


def test_preparation_stop_resume_uses_same_buttons_before_job_without_pick(create):
    window, workflow, processes = create()
    controller = workflow.controller
    controller._ready = False  # observe 외 위치를 나타내는 무장치 Fixture.
    workflow.publish()
    QApplication.instance().processEvents()
    window.buttons["PREPARE_OBSERVE"].click()
    QApplication.instance().processEvents()
    before = deepcopy(controller.state["supply"])
    old = controller.process
    assert window.buttons["STOP"].isEnabled()
    window.buttons["STOP"].click()
    QApplication.instance().processEvents()
    pause_event(controller, "ROBOT_STOP_ACK", dict(request_id=controller._stop["request_id"]))
    controller._pause_process.finished.emit(0, QProcess.NormalExit)
    old.finished.emit(2, QProcess.NormalExit)
    probe(controller, at_observe=False)
    assert window.buttons["RESUME"].isEnabled() and workflow.backend.state["job_id"] is None
    window.buttons["RESUME"].click()
    QApplication.instance().processEvents()
    assert "--prepare-observe" in controller.process.started[0][1]
    event(controller, "ROBOT_PREPARE_COMPLETE", dict(ready_at_observe=True, motion_commands_sent=True))
    controller.process.finished.emit(0, QProcess.NormalExit)
    QApplication.instance().processEvents()
    assert window.buttons["START"].isEnabled() and not window.buttons["RESUME"].isEnabled()
    assert controller.state["supply"] == before and workflow.backend.state["job_id"] is None


def test_eight_short_confirmations_use_actual_a_chair_and_do_not_complete_job(create):
    from test_real_voice_workflow import finish_confirmed_delivery
    window, workflow, processes = create()
    workflow.command(dict(command="START"))
    workflow.receive(dict(event="place_empty"))
    for index in range(8):
        finish_confirmed_delivery(workflow, processes)
        assert workflow.backend.state["workflow_status"] == "WAIT_ASSEMBLY"
        assert workflow.receive(dict(event="assembly"))
        assert len(workflow.backend.state["context"]["confirmed_steps"]) == index + 1
    assert workflow.backend.state["current"]["current_revision"] == 8
    assert workflow.backend.state["workflow_status"] == "DELIVERING"  # 8번째 확인은 기존 정책대로 9번째 전달을 시작한다.
