import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver
import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.hmi_mvp_demo import MvpFixtureDemo, load_snapshots
from app.qt_hmi import HmiWindow


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = load_snapshots()
SCHEMA = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
COMMON = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, resolver=RefResolver.from_schema(SCHEMA, store={
    SCHEMA["$id"]: SCHEMA, COMMON["$id"]: COMMON, "https://c-2.invalid/schemas/day4.schema.json": COMMON}))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.show()
    yield window
    window.close()


@pytest.mark.parametrize("name", SNAPSHOTS)
def test_fixture_schema_and_display_preserve_current_progress_and_commands(window, name):
    snapshot = deepcopy(SNAPSHOTS[name])
    before = deepcopy(snapshot)
    commands = []
    window.command_requested.connect(commands.append)
    VALIDATOR.validate(snapshot)
    window.render_snapshot(snapshot)
    view = window.execution_view
    assert window._snapshot == before == snapshot
    assert window.target_board.current == before["current"]
    assert window.design_board.blocks == (before["design"]["blocks"] if before["design"] else [])
    if "execution" in snapshot:
        assert window.execution_view.isVisible()
        assert "보고 단계" in view.phase.text()
        assert "완료 이력이 아닙니다" in view.description.toPlainText()
        assert snapshot["execution"]["motion_plan_id"] not in view.description.toPlainText()
    else:
        assert window.execution_view.isVisible()
        assert view.phase.text() == "실행 단계 정보 없음"
    assert commands == []


def test_robot_contact_release_retreat_and_inspection_wait_do_not_confirm_assembly(window):
    for name in ("robot_contact", "robot_release", "robot_retreat", "inspection_wait"):
        window.render_snapshot(SNAPSHOTS[name])
        assert "2 / 3" in window.progress.text()
        assert window._snapshot["step"]["comparison"] == "WAITING"
        assert len(window.target_board.current["blocks"]) == 2
        assert "전체 조립 완료" not in window.status.text()
    assert "비전 확인 대기" in window.execution_view.description.toPlainText()


def test_robot_and_human_routes_distinguish_contact_and_tray(window):
    window.render_snapshot(SNAPSHOTS["robot_pre_contact"])
    assert "결착 전 대기" in window.execution_view.phase.text()
    assert "로봇 직접 조립" in window.status.text()
    window.render_snapshot(SNAPSHOTS["human_transport"])
    assert "전달판" in window.status.text()
    assert "이번 Step 담당: 로봇" in window.execution_view.description.toPlainText()
    assert "→ 결착 →" not in window.execution_view.description.toPlainText()
    window.render_snapshot(SNAPSHOTS["human_assembly"])
    assert "사람 조립 / 비전 확인 대기" in window.execution_view.description.toPlainText()


@pytest.mark.parametrize("workflow,robot,heading", [
    ("HOLD", "STOP_PENDING", "정지 확인 대기"), ("STOPPED", "STOPPED", "정지 확인"),
    ("DELIVERING", "ERROR", "로봇 오류 · 진행 보류"), ("HOLD", "BUSY", "진행 보류"),
    ("REPLANNING", "IDLE", "재계획 검증 중")])
def test_stop_error_hold_and_replanning_override_last_phase(window, workflow, robot, heading):
    snapshot = deepcopy(SNAPSHOTS["stopped"] if workflow == "STOPPED" else SNAPSHOTS["robot_contact"])
    snapshot["execution"] = deepcopy(SNAPSHOTS["robot_contact"]["execution"])
    snapshot["workflow_status"] = workflow
    snapshot["monitor"]["robot"]["status"] = robot
    window.render_snapshot(snapshot)
    assert window.status.text() == heading
    assert "직전 보고 단계" in window.execution_view.phase.text()
    assert "공정 보류" in window.execution_view.description.toPlainText()
    assert window._snapshot["progress"] == {"completed": 2, "total": 3}


def test_missing_execution_clears_ids_and_keeps_device_and_execution_visible(window):
    window.render_snapshot(SNAPSHOTS["robot_contact"])
    window.execution_view.details_button.click()
    assert "fake-motion-01" in window.execution_view.description.toPlainText()
    window.render_snapshot(SNAPSHOTS["robot_retreat"])
    assert window.monitor.isVisible() and window.execution_view.isVisible()
    window.render_snapshot(SNAPSHOTS["draft_initial"])
    assert "fake-motion-01" not in window.execution_view.description.toPlainText()
    assert not window.execution_view.details_button.isChecked()
    assert not window.execution_view.details_button.isEnabled()


def test_developer_details_with_null_or_long_ids_are_plain_text(window, qapp):
    snapshot = deepcopy(SNAPSHOTS["robot_contact"])
    snapshot["execution"]["motion_plan_id"] = None
    window.render_snapshot(snapshot)
    window.execution_view.details_button.click()
    assert "경로: 미발급" in window.execution_view.description.toPlainText()
    snapshot["execution"]["motion_plan_id"] = "<b>path</b>" * 200
    window.render_snapshot(snapshot)
    qapp.processEvents()
    assert snapshot["execution"]["motion_plan_id"] in window.execution_view.description.toPlainText()
    assert window.execution_view.description.verticalScrollBar().maximum() > 0


def test_wrong_step_does_not_replace_display_and_rendering_does_not_issue_approval(window):
    window.render_snapshot(SNAPSHOTS["robot_contact"])
    snapshot = deepcopy(SNAPSHOTS["robot_pre_contact"])
    snapshot["execution"]["step_id"] = "old-step"
    with pytest.raises(ValueError, match="step_id"):
        window.render_snapshot(snapshot)
    assert "로봇 결착 단계" in window.execution_view.phase.text()
    assert window._snapshot == SNAPSHOTS["robot_contact"]


@pytest.mark.parametrize("size", [QSize(1200, 900), QSize(1024, 768)])
def test_fake_execution_and_devices_are_simultaneously_visible_without_losing_table_fields(qapp, size):
    window = HmiWindow(screen_size=size)
    demo = MvpFixtureDemo(window, SNAPSHOTS, "robot_pre_contact")
    window.show()
    qapp.processEvents()
    assert window.table.verticalScrollBar().maximum() == 0
    for widget in (window.execution_view, window.monitor, window.supply, window.table, window.notice, window.footer):
        top = widget.mapTo(window, widget.rect().topLeft())
        bottom = widget.mapTo(window, widget.rect().bottomRight())
        assert widget.isVisible()
        assert 0 <= top.y() <= bottom.y() < window.height()
        assert 0 <= top.x() <= bottom.x() < window.width()
    assert window.table.mapTo(window.step_panel, window.table.rect().bottomRight()).y() < window.step_panel.height()
    for name in SNAPSHOTS:
        demo.selector.setCurrentText(name)
        assert all(not button.isEnabled() for button in window.buttons.values())
    window.close()
