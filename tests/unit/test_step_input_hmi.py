import io
import json
from pathlib import Path
from threading import Thread

import pytest
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QApplication

from app.qt_hmi import HmiWindow
from app.step_input_hmi import InputBridge, StepInputDemo


FIXTURE = str(Path(__file__).resolve().parents[2] / "interfaces/fixtures/day4.json")


def fixture(event, key):
    return dict(event=event, file=FIXTURE, key=key)


def make_demo(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = HmiWindow(screen_size=QSize(1920, 1080))
    demo = StepInputDemo(window, tmp_path)
    return application, window, demo


def test_manual_inputs_adopt_design_only_with_valid_plan_and_never_auto_execute(tmp_path):
    application, window, demo = make_demo(tmp_path)
    demo.command(dict(command="START"))
    assert demo.backend.state["context"] is None
    demo.receive(dict(event="keyword", text="탑"))
    demo.receive(fixture("design", "design"))
    application.processEvents()
    assert demo.backend.state["context"] is None
    assert window.design_board.blocks == []
    assert "Design 후보" in window.notice.toPlainText()
    demo.receive(fixture("plan", "initial_plan"))
    application.processEvents()
    assert demo.backend.state["context"]["design"]["design_version"] == 1
    assert window.design_board.blocks != []
    assert demo.backend.state["current"] == dict(current_revision=0, blocks=[])
    assert all(not port.startswith("robot.") for port, payload in demo.requests)
    assert "FAKE" in window.windowTitle()
    with pytest.raises(ValueError, match="닫힌"):
        demo.receive(fixture("plan", "initial_plan"))
    window.close()


def test_terminal_thread_delivers_json_to_qt_and_rejects_non_object(tmp_path, monkeypatch, capsys):
    application, window, demo = make_demo(tmp_path)
    demo.command(dict(command="START"))
    values = [dict(event="keyword", text="탑"), fixture("design", "design"), fixture("plan", "initial_plan")]
    monkeypatch.setattr("sys.stdin", io.StringIO('not-json\n[]\n' + '\n'.join(json.dumps(value) for value in values)))
    bridge = InputBridge()
    bridge.received.connect(demo.receive, Qt.QueuedConnection)
    thread = Thread(target=bridge.read)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert demo.backend.state["context"] is None
    application.processEvents()
    application.processEvents()
    assert demo.backend.state["context"]["design"]["design_version"] == 1
    assert window.design_board.blocks != []
    assert all(not port.startswith("robot.") for port, payload in demo.requests)
    assert capsys.readouterr().out.count("입력 오류:") == 2
    window.close()


@pytest.mark.parametrize("stage", ["started", "keyword", "design", "plan"])
def test_stop_resume_buttons_preserve_inputs_and_job_without_delivery(tmp_path, stage):
    application, window, demo = make_demo(tmp_path)
    application.processEvents()
    window.buttons["START"].click()
    if stage != "started":
        demo.receive(dict(event="keyword", text="탑"))
    if stage in ("design", "plan"):
        demo.receive(fixture("design", "design"))
    if stage == "plan":
        demo.receive(fixture("plan", "initial_plan"))
    job = demo.backend.state["job_id"]
    keyword, design = demo.keyword, demo.design
    context = demo.backend.state["context"]
    for _ in range(2):
        application.processEvents()
        old_request = demo.request_id
        window.buttons["STOP"].click()
        assert not window.buttons["RESUME"].isEnabled()
        if context is None:
            with pytest.raises(ValueError, match="닫힌"):
                demo.receive(fixture("plan", "initial_plan"))
        application.processEvents()
        application.processEvents()
        assert demo.backend.state["workflow_status"] == "STOPPED"
        assert window.buttons["RESUME"].isEnabled()
        window.buttons["RESUME"].click()
        application.processEvents()
        application.processEvents()
        assert demo.backend.state["job_id"] == job
        assert demo.backend.state["current"] == dict(current_revision=0, blocks=[])
        assert demo.backend.state["context"] == context
        assert (demo.keyword, demo.design) == (keyword, design)
        assert not window.buttons["RESUME"].isEnabled()
        if context is None:
            assert demo.backend.state["workflow_status"] == "PREPARING"
            assert demo.request_id == demo.backend.state["planning_request"]["request_id"]
            assert demo.request_id != old_request
        else:
            assert demo.backend.state["reason"] == "WAIT_PLACE_EMPTY"
            assert window.design_board.blocks == context["design"]["blocks"]
    if context is None:
        if keyword is None:
            demo.receive(dict(event="keyword", text="탑"))
        if design is None:
            demo.receive(fixture("design", "design"))
        demo.receive(fixture("plan", "initial_plan"))
        assert demo.backend.state["context"] is not None
    assert len([port for port, payload in demo.requests if port == "robot.stop"]) == 2
    resumes = [payload for port, payload in demo.requests if port == "robot.resume"]
    assert len(resumes) == 2 and all(payload["goal"] is None for payload in resumes)
    assert not any(port == "robot.deliver" for port, payload in demo.requests)
    window.close()


@pytest.mark.parametrize("case", ["not_started", "no_keyword", "no_design", "invalid_plan", "bad_file", "duplicate_design"])
def test_failed_manual_input_never_adopts_or_moves(tmp_path, case):
    application, window, demo = make_demo(tmp_path)
    if case != "not_started":
        demo.command(dict(command="START"))
    if case not in ("not_started", "no_keyword"):
        demo.receive(dict(event="keyword", text="탑"))
    if case in ("invalid_plan", "duplicate_design"):
        demo.receive(fixture("design", "design"))
    value = (fixture("design", "design") if case in ("not_started", "no_keyword", "duplicate_design") else
             dict(event="design", file="/missing-fixture.json", key="design") if case == "bad_file" else
             fixture("plan", "invalid_obsolete_design_id") if case == "invalid_plan" else fixture("plan", "initial_plan"))
    with pytest.raises((ValueError, FileNotFoundError)):
        demo.receive(value)
    assert demo.backend.state["context"] is None
    assert all(not port.startswith("robot.") for port, payload in demo.requests)
    window.close()
