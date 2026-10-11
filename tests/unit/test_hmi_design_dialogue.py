import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import json
from pathlib import Path

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.hmi_mvp_demo import MvpFixtureDemo
from app.qt_hmi import HmiWindow


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = json.loads((ROOT / "interfaces/fixtures/hmi_mvp.json").read_text())["snapshots"]
LEGACY = json.loads((ROOT / "interfaces/fixtures/hmi.json").read_text())["snapshots"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.show()
    yield window
    window.close()


def test_initial_draft_has_no_approved_design_and_emits_no_commands(window):
    commands = []
    window.command_requested.connect(commands.append)
    window.render_snapshot(SNAPSHOTS["draft_initial"])
    view = window.design_dialogue
    assert view.preview_board.blocks == SNAPSHOTS["draft_initial"]["design_preview"]["design"]["blocks"]
    assert view.approved_board.blocks == window.design_board.blocks == []
    assert "없음" in view.approved_panel.title()
    assert "미승인" in view.preview_panel.title()
    assert commands == []


def test_updated_preview_and_approved_design_stay_separate_without_mutation(window):
    snapshot = deepcopy(SNAPSHOTS["draft_updated"])
    before = deepcopy(snapshot)
    commands = []
    window.command_requested.connect(commands.append)
    window.render_snapshot(snapshot)
    view = window.design_dialogue
    assert view.preview_board.blocks[-1]["color"] == "yellow"
    assert view.approved_board.blocks[-1]["color"] == window.design_board.blocks[-1]["color"] == "blue"
    assert window.target_board.current == before["current"]
    assert window.target_board.target == before["step"]["target"]
    assert "2 / 3" in window.progress.text()
    view.preview_board.blocks.clear()
    assert view.approved_board.blocks == before["design"]["blocks"]
    assert snapshot == before
    assert commands == []


@pytest.mark.parametrize("phase", ["LISTENING", "GENERATING", "SPEAKING", "REVIEW", "WAIT_APPROVAL", "FAILED"])
def test_dialogue_phases_preserve_last_preview_and_show_failure_reason(window, phase):
    snapshot = deepcopy(SNAPSHOTS["draft_updated"])
    snapshot["dialogue"].update(phase=phase, reason="음성 연결 실패" if phase == "FAILED" else None)
    window.render_snapshot(snapshot)
    view = window.design_dialogue
    assert view.preview_board.blocks == snapshot["design_preview"]["design"]["blocks"]
    assert snapshot["dialogue"]["user_text"] in view.conversation.toPlainText()
    assert snapshot["dialogue"]["assistant_text"] in view.conversation.toPlainText()
    assert view.phase.text() and phase not in view.phase.text()
    assert view.reason.toPlainText() == ("진행 사유: 음성 연결 실패" if phase == "FAILED" else "")


def test_missing_extensions_clear_old_preview_dialogue_and_reason(window):
    window.render_snapshot(SNAPSHOTS["dialogue_failed"])
    window.render_snapshot(next(iter(LEGACY.values())))
    view = window.design_dialogue
    assert view.preview_board.blocks == []
    assert view.preview_board.isHidden()
    assert view.phase.text() == "설계 대화 정보 없음"
    assert view.conversation.toPlainText() == "받은 대화 내용이 없습니다."
    assert view.reason.toPlainText() == ""
    assert window.design_dialogue.isVisible()  # 입력 누락도 같은 페이지에서 확인한다.


def test_dialogue_without_preview_and_empty_design_have_explicit_messages(window):
    snapshot = deepcopy(SNAPSHOTS["draft_initial"])
    del snapshot["design_preview"]
    window.render_snapshot(snapshot)
    view = window.design_dialogue
    assert view.preview_board.blocks == []
    assert "받은 설계 초안이 없습니다" in view.preview_caption.text()
    snapshot["design_preview"] = deepcopy(SNAPSHOTS["draft_initial"]["design_preview"])
    snapshot["design_preview"]["design"]["blocks"] = []
    window.render_snapshot(snapshot)
    assert "블록 없음" in view.preview_caption.text()
    assert view.preview_board.isHidden()


def test_invalid_request_does_not_replace_visible_snapshot(window):
    window.render_snapshot(SNAPSHOTS["draft_updated"])
    previous = deepcopy(window._snapshot)
    snapshot = deepcopy(SNAPSHOTS["draft_initial"])
    snapshot["dialogue"]["request_id"] = "wrong-request"
    with pytest.raises(ValueError, match="request_id"):
        window.render_snapshot(snapshot)
    assert window._snapshot == previous
    assert window.design_dialogue.approved_board.blocks[-1]["color"] == "blue"


def test_long_dialogue_is_plain_text_scrollable_and_null_text_is_explicit(window, qapp):
    snapshot = deepcopy(SNAPSHOTS["draft_updated"])
    snapshot["dialogue"]["assistant_text"] = "<b>설명</b> & https://example.invalid/ " * 300
    snapshot["dialogue"]["user_text"] = None
    window.render_snapshot(snapshot)
    qapp.processEvents()
    text = window.design_dialogue.conversation.toPlainText()
    assert snapshot["dialogue"]["assistant_text"] in text
    assert "사용자: 발화 정보 없음" in text
    assert window.design_dialogue.conversation.verticalScrollBar().maximum() > 0
    snapshot["dialogue"]["assistant_text"] = None
    window.render_snapshot(snapshot)
    assert "C: 응답 정보 없음" in window.design_dialogue.conversation.toPlainText()
    assert window.design_dialogue.isVisible()


def test_long_failure_reason_is_readable_without_pushing_controls_outside_window(window, qapp):
    snapshot = deepcopy(SNAPSHOTS["dialogue_failed"])
    snapshot["dialogue"]["reason"] = "연결 실패 사유를 확인해주세요. " * 200
    window.render_snapshot(snapshot)
    qapp.processEvents()
    view = window.design_dialogue
    assert snapshot["dialogue"]["reason"] in view.reason.toPlainText()
    assert view.reason.verticalScrollBar().maximum() > 0
    for widget in (view.preview_board, view.conversation, view.reason, window.footer):
        point = widget.mapTo(window, widget.rect().bottomRight())
        assert 0 <= point.y() < window.height()


@pytest.mark.parametrize("size", [QSize(1200, 900), QSize(1024, 768)])
def test_dialogue_layout_fits_and_renders_on_smaller_screen(qapp, size):
    window = HmiWindow(screen_size=size)
    window.render_snapshot(SNAPSHOTS["draft_updated"])
    window.show()
    qapp.processEvents()
    view = window.design_dialogue
    for widget in (view.preview_board, view.approved_board, view.conversation, view.phase, window.footer):
        point = widget.mapTo(window, widget.rect().bottomRight())
        assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height()
    assert not window.grab().isNull()
    window.close()


def test_fixture_selector_updates_all_cases_and_cannot_issue_process_commands(window, qapp):
    demo = MvpFixtureDemo(window, SNAPSHOTS, "draft_updated")
    commands = []
    window.command_requested.connect(commands.append)
    before = deepcopy(SNAPSHOTS)
    for name, snapshot in SNAPSHOTS.items():
        demo.selector.setCurrentText(name)
        qapp.processEvents()
        assert window._snapshot == snapshot
        assert all(not button.isEnabled() for button in (*window.buttons.values(), *window.refill_buttons.values()))
        for button in window.buttons.values():
            button.click()
    assert commands == []
    assert SNAPSHOTS == before


def test_fixture_viewer_rejects_real_input_before_rendering(window):
    snapshot = deepcopy(next(iter(LEGACY.values())))
    snapshot["monitor"]["robot"]["mode"] = "REAL"
    with pytest.raises(ValueError):
        MvpFixtureDemo(window, {"real": snapshot}, "real")
    assert window._snapshot is None
