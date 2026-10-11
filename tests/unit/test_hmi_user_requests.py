import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.hmi_contracts import validate_hmi_command, validate_hmi_snapshot
from app.hmi_mvp_contracts import validate_user_reply, validate_user_request
from app.hmi_mvp_demo import MvpFixtureDemo, load_snapshots
from app.qt_hmi import HmiWindow
from test_hmi_remaining import VALIDATOR


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.show()
    yield window
    window.close()


@pytest.mark.parametrize("case,button,command", [("requests_ready", "change_design", "REQUEST_DESIGN_CHANGE"),
    ("requests_ready", "assistance_ready", "ASSISTANCE_READY"), ("requests_stopped", "home", "REQUEST_HOME")])
def test_requests_use_bound_ids_separate_from_legacy_commands_and_no_execution(window, case, button, command):
    snapshot = load_snapshots()[case]
    VALIDATOR.validate(snapshot)
    before = deepcopy(snapshot)
    legacy, emitted = [], []
    window.command_requested.connect(legacy.append)
    window.mvp_request_requested.connect(emitted.append)
    window.render_snapshot(snapshot)
    controls = window.user_request_controls
    controls.buttons[button].click()
    expected = dict(command=command, job_id=snapshot["actions"]["job_id"], request_id=snapshot["user_requests"][button]["request_id"])
    assert emitted == [expected]
    VALIDATOR.validate(expected)
    validate_user_request(expected)
    with pytest.raises(ValueError):
        validate_hmi_command(expected)
    assert "접수 결과 대기" in controls.feedback.toPlainText()
    controls.buttons[button].click()
    assert len(emitted) == 1 and legacy == []
    assert snapshot == before == window._snapshot
    assert controls.receive_reply(dict(**expected, accepted=True, reason=None))
    assert "실행 완료 아님" in controls.feedback.toPlainText()
    assert not controls.receive_reply(dict(**expected, accepted=True, reason=None))


@pytest.mark.parametrize("accepted", [True, False])
def test_fake_interactive_receipt_and_rejection_preserve_all_process_state(window, qapp, accepted):
    case = "requests_ready" if accepted else "requests_rejected"
    demo = MvpFixtureDemo(window, load_snapshots(), case, interactive=True)
    before = deepcopy(window._snapshot)
    window.user_request_controls.buttons["assistance_ready"].click()
    qapp.processEvents()
    assert len(demo.requests) == 1
    assert ("실행 완료 아님" if accepted else "요청 거절") in window.user_request_controls.feedback.toPlainText()
    assert window._snapshot == before
    assert before["assistance"]["phase"] == "REQUESTED"
    assert before["progress"]["completed"] == 2


def test_old_reply_after_request_retirement_job_change_or_duplicate_is_ignored(window):
    snapshot = load_snapshots()["requests_ready"]
    window.render_snapshot(snapshot)
    emitted = []
    window.mvp_request_requested.connect(emitted.append)
    window.user_request_controls.buttons["change_design"].click()
    old = dict(**emitted[-1], accepted=True, reason=None)
    changed = deepcopy(snapshot)
    changed["user_requests"]["change_design"]["request_id"] = "new-request"
    window.render_snapshot(changed)
    assert not window.user_request_controls.receive_reply(old)
    window.user_request_controls.buttons["change_design"].click()
    newer = dict(**emitted[-1], accepted=True, reason=None)
    changed["actions"]["job_id"] = "new-job"
    window.render_snapshot(changed)
    assert not window.user_request_controls.receive_reply(newer)
    window.render_snapshot(load_snapshots()["draft_initial"])
    assert window.user_request_controls.isHidden()
    assert window.user_request_controls.feedback.toPlainText() == ""


@pytest.mark.parametrize("change", ["hidden", "no_id", "old_help", "home_busy", "help_during_contact", "help_after_release"])
def test_invalid_or_unavailable_request_controls_are_rejected(change):
    snapshot = deepcopy(load_snapshots()["requests_ready"])
    if change == "hidden": snapshot["user_requests"]["change_design"]["visible"] = False
    if change == "no_id": snapshot["user_requests"]["change_design"]["request_id"] = None
    if change == "old_help": snapshot["user_requests"]["assistance_ready"]["request_id"] = "old"
    if change == "home_busy": snapshot["user_requests"]["home"]["enabled"] = True
    if change == "help_during_contact": snapshot["execution"]["phase"] = "CONTACT"
    if change == "help_after_release": snapshot["assistance"]["phase"] = "RELEASED"
    with pytest.raises(ValueError): validate_hmi_snapshot(snapshot)


@pytest.mark.parametrize("field,value", [("accepted", 1), ("accepted", None), ("reason", ""), ("command", "START"), ("request_id", None)])
def test_invalid_receipts_are_not_silently_accepted(field, value):
    reply = dict(command="REQUEST_HOME", job_id="fake-job", request_id="fake-home", accepted=False, reason="조건 미충족")
    reply[field] = value
    with pytest.raises(ValueError): validate_user_reply(reply)


def test_readonly_demo_keeps_new_buttons_disabled(window):
    demo = MvpFixtureDemo(window, load_snapshots(), "requests_ready")
    for button in window.user_request_controls.buttons.values():
        assert not button.isEnabled()
        button.click()
    assert demo.requests == []


def test_bad_queued_reply_and_snapshot_are_visible_errors_and_keep_last_good_state(window, qapp):
    snapshot = load_snapshots()["requests_ready"]
    window.render_snapshot(snapshot)
    emitted = []
    window.mvp_request_requested.connect(emitted.append)
    window.user_request_controls.buttons["assistance_ready"].click()
    reply = dict(**emitted[-1], accepted="yes", reason=None)
    window.mvp_reply_received.emit(reply)
    qapp.processEvents()
    assert "요청 응답 오류" in window.footer.text()
    assert window._snapshot == snapshot
    assert window.buttons["STOP"].isEnabled()
    assert not window.user_request_controls.buttons["change_design"].isEnabled()
    bad = deepcopy(snapshot)
    bad["user_requests"]["home"]["enabled"] = True
    window.snapshot_received.emit(bad)
    qapp.processEvents()
    assert "화면 입력 오류" in window.footer.text()
    assert window._snapshot == snapshot
    window.snapshot_received.emit(snapshot)
    qapp.processEvents()
    assert "입력 갱신 오류" not in window.status.text()
