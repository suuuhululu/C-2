import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver
import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.hmi_contracts import validate_hmi_snapshot
from app.hmi_mvp_demo import load_snapshots
from app.qt_hmi import HmiWindow


ROOT = Path(__file__).resolve().parents[2]
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


@pytest.mark.parametrize("name", ["b_mismatch", "b_unobservable", "b_error", "b_canceled"])
def test_b_results_schema_render_without_spatial_recomparison_or_commands(window, name):
    snapshot = load_snapshots()[name]
    before = deepcopy(snapshot)
    commands = []
    window.command_requested.connect(commands.append)
    VALIDATOR.validate(snapshot)
    window.render_snapshot(snapshot)
    view = window.inspection_view
    assert view.current_board.blocks == snapshot["current"]["blocks"]
    expected = snapshot["inspection"]["expected"]
    assert view.expected_board.blocks == (expected["blocks"] if expected else [])
    assert snapshot == before == window._snapshot
    assert window._snapshot["progress"] == {"completed": 2, "total": 3}
    assert commands == []


def test_b_mismatch_preserves_actual_color_and_lower_layers(window):
    snapshot = load_snapshots()["b_mismatch"]
    window.render_snapshot(snapshot)
    assert window.inspection_view.current_board.blocks[-1]["color"] == "yellow"
    assert window.inspection_view.expected_board.blocks[-1]["color"] == "blue"
    assert len(window.inspection_view.current_board.blocks) == 3
    text = window.inspection_view.details.toPlainText()
    assert "확인된 목표 누락: 1개" in text and "확인된 예상 밖 배치: 1개" in text
    window.render_snapshot(load_snapshots()["b_unobservable"])
    assert len(window.inspection_view.current_board.blocks) == 2
    assert "확인된 목표 누락: 0개" in window.inspection_view.details.toPlainText()


def test_missing_b_result_clears_expected_instead_of_rebuilding_from_design(window):
    window.render_snapshot(load_snapshots()["b_mismatch"])
    window.render_snapshot(load_snapshots()["draft_updated"])
    assert window.inspection_view.expected_board.blocks == []
    assert "미수신" in window.inspection_view.summary.text()
    assert "목표 일치를 판단하지 않습니다" in window.inspection_view.details.toPlainText()


@pytest.mark.parametrize("key,value", [("check_id", "old"), ("step_id", "old"), ("plan_id", "old"),
    ("status", "READY"), ("comparison", "MATCH"), ("expected", None), ("difference", None)])
def test_invalid_b_display_context_is_rejected_without_mutation(key, value):
    snapshot = deepcopy(load_snapshots()["b_mismatch"])
    snapshot["inspection"][key] = value
    before = deepcopy(snapshot)
    with pytest.raises(ValueError):
        validate_hmi_snapshot(snapshot)
    assert snapshot == before


def test_initial_unobservable_has_no_plan_expected_and_final_has_no_step(window):
    initial = deepcopy(load_snapshots()["draft_initial"])
    initial["monitor"]["observation"]["check_id"] = "fake-initial"
    initial["inspection"] = dict(check_id="fake-initial", check_kind="INITIAL", plan_id=None, step_id=None,
        status="UNOBSERVABLE", comparison=None, expected=None,
        difference=dict(missing=[], unexpected=[], unobservable=[]), reason="촬영 불가")
    validate_hmi_snapshot(initial)
    window.render_snapshot(initial)
    assert "관측 불가" in window.inspection_view.summary.text()
    final = deepcopy(load_snapshots()["complete"])
    final["monitor"]["observation"]["check_id"] = "fake-final"
    final["inspection"] = dict(check_id="fake-final", check_kind="FINAL", plan_id=final["step"]["plan_id"], step_id=None,
        status="OK", comparison="MATCH", expected=dict(plan_id=final["step"]["plan_id"], step_id=None, blocks=final["current"]["blocks"]),
        difference=dict(missing=[], unexpected=[], unobservable=[]), reason=None)
    VALIDATOR.validate(final)
    validate_hmi_snapshot(final)


@pytest.mark.parametrize("phase", ["REQUESTED", "READY", "MAINTAIN", "RELEASED", "CANCELED"])
def test_assistance_phases_display_given_lower_block_without_completion(window, phase):
    snapshot = deepcopy(load_snapshots()["support_requested"])
    snapshot["assistance"]["phase"] = phase
    before = deepcopy(snapshot)
    window.render_snapshot(snapshot)
    assert window.assistance_view.target_board.blocks == [snapshot["current"]["blocks"][0]]
    assert window.assistance_view.target_board.blocks != [snapshot["step"]["target"]]
    assert snapshot["assistance"]["instruction"] in window.assistance_view.instruction.toPlainText()
    assert snapshot == before == window._snapshot
    assert window._snapshot["progress"]["completed"] == 2
    if phase == "READY":
        assert "실행 확인 별도" in window.assistance_view.summary.text()
    if phase == "CANCELED":
        assert "손을 놓으라는 뜻은 아닙니다" in window.assistance_view.instruction.toPlainText()


def test_handover_tray_assembly_stop_and_missing_help_remain_distinct(window):
    window.render_snapshot(load_snapshots()["handover_requested"])
    assert "손으로 블록 받기" in window.assistance_view.summary.text()
    assert "전달판 경로만으로" in window.assistance_view.instruction.toPlainText()
    window.render_snapshot(load_snapshots()["human_assembly"])
    assert "사람 직접 조립" in window.assistance_view.summary.text()
    snapshot = deepcopy(load_snapshots()["support_maintain"])
    snapshot["workflow_status"] = "HOLD"
    snapshot["monitor"]["robot"]["status"] = "STOP_PENDING"
    window.render_snapshot(snapshot)
    assert "직전 요청" in window.assistance_view.summary.text()
    assert "손을 놓으라는 뜻은 아닙니다" in window.assistance_view.instruction.toPlainText()
    window.render_snapshot(load_snapshots()["draft_initial"])
    assert window.assistance_view.target_board.blocks == []
    assert "없음" in window.assistance_view.summary.text()


@pytest.mark.parametrize("case", ["final_wait", "final_unobservable", "saving", "storage_failed", "web_pending", "web_failed", "complete"])
def test_completion_stages_preserve_physical_current_and_do_not_reexecute(window, case):
    snapshot = load_snapshots()[case]
    before = deepcopy(snapshot)
    commands = []
    window.command_requested.connect(commands.append)
    VALIDATOR.validate(snapshot)
    window.render_snapshot(snapshot)
    view = window.completion_view
    assert "필요 블록" in view.states["blocks_used"].text()
    assert "최종 조립 확인" in view.states["assembly"].text()
    assert "기록 저장" in view.states["storage"].text()
    assert "개인 웹 반영" in view.states["web"].text()
    assert snapshot == before == window._snapshot
    assert commands == []
    if case in ("storage_failed", "web_failed"):
        assert "조립 완료" in window.status.text() and "실패" in window.status.text()
        assert view.states["assembly"].text().endswith("일치 확인")
    if case in ("final_wait", "final_unobservable"):
        assert "전체 조립 완료" not in window.status.text()


def test_missing_completion_clears_prior_success_and_failures(window):
    window.render_snapshot(load_snapshots()["storage_failed"])
    window.render_snapshot(load_snapshots()["draft_initial"])
    assert all("미수신" in item.text() for item in window.completion_view.states.values())
    assert "실패" not in window.completion_view.summary.text()


@pytest.mark.parametrize("size", [QSize(1200, 900), QSize(1024, 768)])
@pytest.mark.parametrize("case", ["b_mismatch", "requests_ready", "complete"])
def test_remaining_panels_and_feedback_fit_small_screens(qapp, size, case):
    from app.hmi_mvp_demo import MvpFixtureDemo
    window = HmiWindow(screen_size=size)
    demo = MvpFixtureDemo(window, load_snapshots(), case, interactive=True)
    window.show()
    if case == "requests_ready":
        window.user_request_controls.buttons["assistance_ready"].click()
    qapp.processEvents()
    for view, children in ((window.inspection_view, (window.inspection_view.current_board, window.inspection_view.details)),
        (window.assistance_view, (window.assistance_view.target_board, window.assistance_view.instruction)),
        (window.completion_view, (*window.completion_view.states.values(), window.completion_view.reason))):
        qapp.processEvents()
        for child in children:
            if child.isVisible():
                top = child.mapTo(window, child.rect().topLeft())
                bottom = child.mapTo(window, child.rect().bottomRight())
                assert top.y() >= 0 and bottom.y() < window.height()
        assert not window.grab().isNull()
    window.close()


def test_b_report_is_not_replaced_by_hmi_spatial_judgement(window):
    snapshot = deepcopy(load_snapshots()["b_mismatch"])
    # 비교된 배치의 의미 검증은 B 책임이다. HMI는 반환 판정을 다시 계산하지 않는다.
    snapshot["inspection"]["expected"]["blocks"] = deepcopy(snapshot["current"]["blocks"])
    window.render_snapshot(snapshot)
    assert "차이 있음" in window.inspection_view.summary.text()
    assert window._snapshot["inspection"]["comparison"] == "MISMATCH"
    assert window._snapshot["current"]["current_revision"] == 3


def test_unknown_fields_and_failure_results_with_normal_expected_are_rejected():
    snapshot = deepcopy(load_snapshots()["b_error"])
    snapshot["inspection"]["expected"] = load_snapshots()["b_mismatch"]["inspection"]["expected"]
    with pytest.raises(ValueError): validate_hmi_snapshot(snapshot)
    snapshot = deepcopy(load_snapshots()["b_mismatch"])
    snapshot["inspection"]["invented"] = True
    with pytest.raises(ValueError): validate_hmi_snapshot(snapshot)


def test_final_mismatch_and_web_failure_are_separate_from_finished_block_use(window):
    snapshot = deepcopy(load_snapshots()["final_unobservable"])
    snapshot["completion"].update(assembly="MISMATCH", reason="최종 구조 차이")
    window.render_snapshot(snapshot)
    assert "차이 있음" in window.completion_view.states["assembly"].text()
    assert "완료" in window.completion_view.states["blocks_used"].text()
    assert window._snapshot["workflow_status"] != "COMPLETE"


def test_matching_current_step_still_displays_changes_elsewhere_on_board(window):
    snapshot = load_snapshots()["b_existing_changed"]
    VALIDATOR.validate(snapshot)
    window.render_snapshot(snapshot)
    assert snapshot["current"]["blocks"][-1] == snapshot["step"]["target"]
    assert "차이 있음" in window.inspection_view.summary.text()
    assert "(3, 5) · 1층" in window.inspection_view.details.toPlainText()
    assert window._snapshot["progress"]["completed"] == 2
