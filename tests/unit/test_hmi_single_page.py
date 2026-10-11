import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication, QTabWidget, QScrollArea

from app.hmi_mvp_demo import MvpFixtureDemo, load_snapshots
from app.qt_hmi import HmiWindow
from test_hmi_remaining import VALIDATOR


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def assert_unclipped(window, widget):
    assert widget.isVisible(), widget.objectName()
    parent = widget.parentWidget()
    while parent is not None:
        top = widget.mapTo(parent, widget.rect().topLeft())
        bottom = widget.mapTo(parent, widget.rect().bottomRight())
        assert 0 <= top.x() <= bottom.x() < parent.width(), (type(widget).__name__, type(parent).__name__, top, bottom)
        assert 0 <= top.y() <= bottom.y() < parent.height(), (type(widget).__name__, type(parent).__name__, top, bottom)
        if parent is window:
            break
        parent = parent.parentWidget()


def settle(qapp):
    # queued 응답 후 레이아웃 재배치까지 처리한 화면을 검사한다.
    for _ in range(3):
        qapp.processEvents()


@pytest.mark.parametrize("size", [QSize(1200, 900), QSize(1024, 768), QSize(960, 900)])
def test_all_major_information_is_visible_together_without_tabs_or_page_scroll(qapp, size):
    window = HmiWindow(screen_size=size)
    snapshots = load_snapshots()
    before = deepcopy(snapshots["overview_all"])
    VALIDATOR.validate(before)
    demo = MvpFixtureDemo(window, snapshots, "overview_all", interactive=True)
    window.show()
    settle(qapp)
    assert window.findChildren(QTabWidget) == []
    assert window.findChildren(QScrollArea) == []
    items = (window.design_panel, window.design_board, window.design_dialogue.preview_panel,
        window.design_dialogue.preview_board, window.inspection_view.current_board,
        window.inspection_view.expected_board, window.execution_view.method, window.execution_view.phase,
        window.monitor, window.supply, window.step_panel, window.table, window.target_board,
        window.design_dialogue.phase, window.design_dialogue.conversation, window.inspection_view.summary,
        window.inspection_view.details, window.assistance_view.summary, window.assistance_view.target_board,
        window.assistance_view.instruction, *window.completion_view.states.values(), window.notice,
        window.buttons["STOP"], window.user_request_controls.buttons["change_design"])
    for widget in items:
        assert_unclipped(window, widget)
    assert window.table.verticalScrollBar().maximum() == 0
    assert window.design_board.blocks[-1]["color"] == "blue"
    assert window.design_dialogue.preview_board.blocks[-1]["color"] == "yellow"
    assert window.inspection_view.current_board.blocks == before["current"]["blocks"]
    assert window._snapshot == before
    demo.selector.setCurrentText("requests_ready")
    settle(qapp)
    window.user_request_controls.buttons["assistance_ready"].click()
    settle(qapp)
    assert "실행 완료 아님" in window.user_request_controls.feedback.toPlainText()
    for widget in (window.user_request_controls.feedback, window.table, window.notice, window.buttons["STOP"]):
        assert_unclipped(window, widget)
    window.close()


@pytest.mark.parametrize("size", [QSize(1200, 900), QSize(1024, 768)])
def test_case_changes_do_not_hide_other_status_sections_or_mutate_process(qapp, size):
    window = HmiWindow(screen_size=size)
    demo = MvpFixtureDemo(window, load_snapshots(), "overview_all")
    window.show()
    for name, snapshot in demo.snapshots.items():
        demo.selector.setCurrentText(name)
        settle(qapp)
        for view in (window.design_dialogue, window.inspection_view, window.execution_view,
                     window.assistance_view, window.completion_view):
            assert view.isVisible()
        for widget in (window.table, window.buttons["STOP"], window.inspection_view.summary,
                       window.design_dialogue.phase, window.assistance_view.summary,
                       *window.completion_view.states.values(), window.notice):
            assert_unclipped(window, widget)
        assert window._snapshot == snapshot
    window.close()


def test_compact_boards_preserve_dimensions_and_fit_five_layers(qapp, monkeypatch):
    window = HmiWindow(screen_size=QSize(1024, 768))
    snapshot = deepcopy(load_snapshots()["overview_all"])
    snapshot["design"]["blocks"] = [dict(brick_type="2x2x1", color="blue", x=22, y=22, layer=layer, orientation_deg=0)
                                     for layer in range(1, 6)]
    window.render_snapshot(snapshot)
    window.show()
    settle(qapp)
    board = window.design_board
    points = []
    original = board._brick
    def record(painter, block, project, scale):
        points.extend(project(x,y,z) for x in (block["x"],block["x"]+2)
                      for y in (block["y"],block["y"]+2) for z in (block["layer"]-1, block["layer"]+.2))
        original(painter, block, project, scale)
    monkeypatch.setattr(board, "_brick", record)
    assert not board.grab().isNull()
    assert points and all(0 <= p.x() < board.width() and 0 <= p.y() < board.height() for p in points)
    assert board.blocks == snapshot["design"]["blocks"]
    window.close()
