"""사용자가 제공한 실제 C 저장 응답을 실제 A/D/Qt와 Fake 의존성으로 검사한다."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.abd_input_hmi import AbdInputDemo
from app.planning_connection import on_c_intervention
from app.qt_hmi import HmiWindow
from planning_trial.planner import plan_from_current
from test_abd_input_hmi import records, transfer, wait_for


ROOT = Path(__file__).resolve().parents[2]
INITIAL_PATH = ROOT / "interfaces/fixtures/c_design_initial_result.json"
REVISED_PATH = ROOT / "interfaces/fixtures/c_design_revised_result.json"
INITIAL = json.loads(INITIAL_PATH.read_text())
REVISED = json.loads(REVISED_PATH.read_text())


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def connected(qapp, tmp_path):
    window = HmiWindow(screen_size=QSize(1920, 1080))
    demo = AbdInputDemo(window, tmp_path, initial_result=INITIAL_PATH, revised_result=REVISED_PATH, delay_ms=1)
    window.show()
    qapp.processEvents()
    window.buttons["START"].click()
    qapp.processEvents()
    assert window.design_board.blocks == INITIAL["design"]["blocks"]
    assert "조립 확인 0 / 15" in window.progress.text() and not demo.driver.calls
    yield window, demo
    window.close()


def assemble(demo, *, actual=None):
    transfer(demo)
    value = dict(event="observe")
    if actual is not None:
        value["actual"] = actual
    demo.receive(value)


def changed_after_eight(demo, *, x=9):
    for _ in range(8):
        assemble(demo)
    target = demo.backend._next_step()["after"]
    assert target == dict(brick_type="2x3x1",color="yellow",x=9,y=9,layer=2,orientation_deg=90)
    assemble(demo, actual={**target, "color": "blue", "x": x})
    assert demo.backend.state["workflow_status"] == "WAIT_INTENT"
    assert demo.backend.state["current"]["current_revision"] == 9
    assert len(demo.backend.state["context"]["confirmed_steps"]) == 8
    assert len(demo.driver.calls) == 27


@pytest.mark.parametrize("path,sha,count", [
    (INITIAL_PATH, "5213f1d01b5bdc3abfeed1c330e3dc975ceb3bc45465fdac5d50f90c8334432b", 15),
    (REVISED_PATH, "5c60d6d514ec08852f02f4713c1b4ba2491b0254a33ab64205efe6bcefd6588f", 19),
])
def test_saved_c_source_bytes_and_actual_a_empty_current(path, sha, count):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    response = json.loads(path.read_text())
    before = deepcopy(response)
    result = plan_from_current(response["design"], dict(current_revision=0, blocks=[]))
    assert result["status"] == "READY" and result["errors"] == []
    assert len(result["plan"]["steps"]) == count and response == before


@pytest.mark.parametrize("count", [0, 4, 8])
def test_actual_a_partial_initial_excludes_already_assembled_placements(count):
    full = plan_from_current(INITIAL["design"],dict(current_revision=0,blocks=[]))["plan"]
    current = dict(current_revision=count, blocks=[step["after"] for step in full["steps"][:count]])
    result = plan_from_current(INITIAL["design"], current)
    assert result["status"] == "READY" and len(result["plan"]["steps"]) == 15-count
    assert result["plan"]["base_current_revision"] == count
    assert not any(step["after"] in current["blocks"] for step in result["plan"]["steps"])


def test_initial_saved_response_full_fifteen_steps_qt_and_jsonl(connected, qapp, tmp_path):
    window, demo = connected
    assert window.grab().save(str(tmp_path / "initial-adopted.png"))
    for index in range(15):
        transfer(demo)
        qapp.processEvents()
        assert len(demo.backend.state["context"]["confirmed_steps"]) == index
        assert demo.backend.state["workflow_status"] == "WAIT_ASSEMBLY"
        assert f"조립 확인 {index} / 15" in window.progress.text()
        demo.receive(dict(event="observe"))
    qapp.processEvents()
    assert window.status.text() == "전체 조립 완료"
    assert demo.backend.state["current"]["current_revision"] == 15
    assert len(demo.driver.calls) == 45
    rows = records(demo)
    assert next(r for r in rows if r["event"] == "INITIAL_DESIGN_RECEIVED")["result"] == INITIAL
    assert sum(r["event"] == "STEP_CONFIRMED" for r in rows) == 15
    assert sum(r["event"] == "JOB_COMPLETED" for r in rows) == 1
    assert window.grab().save(str(tmp_path / "initial-complete.png"))


def test_revised_c_response_after_synthetic_color_mismatch_preserves_current_and_finishes(connected, qapp, tmp_path):
    window, demo = connected
    changed_after_eight(demo)
    qapp.processEvents()
    assert REVISED["questions"][0] in window.notice.toPlainText()
    assert window.grab().save(str(tmp_path / "mismatch-before-revise.png"))
    current = demo.backend.state["current"]
    demo.receive(dict(event="revise"))
    qapp.processEvents()
    context = demo.backend.state["context"]
    assert context["design"] == REVISED["design"]
    assert context["base_current"] == current and demo.backend.state["current"] == current
    assert context["plan"]["base_current_revision"] == 9
    assert len(context["plan"]["steps"]) == 10 and context["confirmed_steps"] == []
    assert not any(s["after"] in current["blocks"] for s in context["plan"]["steps"])
    assert len(demo.driver.calls) == 27
    assert "조립 확인 0 / 10" in window.progress.text()
    assert window.design_board.blocks == REVISED["design"]["blocks"]
    assert window.grab().save(str(tmp_path / "revised-adopted.png"))
    with pytest.raises(ValueError):
        demo.receive(dict(event="revise"))
    for index in range(10):
        transfer(demo)
        assert len(demo.backend.state["context"]["confirmed_steps"]) == index
        demo.receive(dict(event="observe"))
    qapp.processEvents()
    assert window.status.text() == "전체 조립 완료"
    assert "조립 확인 10 / 10" in window.progress.text()
    assert len(demo.backend.state["current"]["blocks"]) == 19
    assert demo.backend.state["current"]["current_revision"] == 19
    assert len(demo.driver.calls) == 57  # 8 정상 + 1 불일치 전달 + 10 새 Plan 전달.
    rows = records(demo)
    assert sum(r["event"] == "STEP_CONFIRMED" for r in rows) == 18
    assert next(r for r in rows if r["event"] == "C_INTERVENTION_RESULT")["result"] == REVISED
    results = [r["result"] for r in rows if r["event"] == "PLAN_RESULT"]
    assert [len(r["plan"]["steps"]) for r in results] == [15, 10]
    assert window.grab().save(str(tmp_path / "revised-complete.png"))


def test_revised_file_does_not_overwrite_incompatible_actual_current(connected, qapp, tmp_path):
    window, demo = connected
    changed_after_eight(demo, x=7)
    current = demo.backend.state["current"]
    demo.receive(dict(event="revise"))
    qapp.processEvents()
    assert demo.backend.state["workflow_status"] == "WAIT_CORRECTION"
    assert demo.backend.state["current"] == current
    assert demo.backend.state["context"]["design"] == INITIAL["design"]
    result = [r["result"] for r in records(demo) if r["event"] == "PLAN_RESULT"][-1]
    assert result["status"] == "NEEDS_CORRECTION" and result["plan"] is None
    assert result["errors"] and len(demo.driver.calls) == 27
    assert window.grab().save(str(tmp_path / "incompatible-current-hold.png"))


def test_revised_before_intent_is_rejected_without_dispatch(connected):
    _, demo = connected
    before = demo.backend.state
    with pytest.raises(ValueError):
        demo.receive(dict(event="revise"))
    assert demo.backend.state == before and not demo.driver.calls


@pytest.mark.parametrize("actual", [dict(brick_type="2x3x1",color="red",x=9,y=9,layer=2,orientation_deg=90),
                                    dict(brick_type="2x3x1",color="blue",x=True,y=9,layer=2,orientation_deg=90)])
def test_invalid_actual_input_does_not_change_current_or_sequence(connected, actual):
    _, demo = connected
    transfer(demo)
    before = demo.backend.state
    with pytest.raises(ValueError):
        demo.receive(dict(event="observe",actual=actual))
    assert demo.backend.state == before and demo.sequences.get(before["active_check"]["check_id"]) is None


def test_closed_c_question_result_is_not_adopted(connected):
    window, demo = connected
    changed_after_eight(demo)
    request = demo.backend.state["question_request"]["request_id"]
    current = demo.backend.state["current"]
    window.buttons["STOP"].click()
    wait_for(demo, "STOPPED")
    assert not on_c_intervention(demo.backend, request, deepcopy(REVISED))
    assert demo.backend.state["current"] == current
    assert demo.backend.state["context"]["design"] == INITIAL["design"]
    assert sum(r["event"] == "PLAN_RESULT" for r in records(demo)) == 1


def test_cli_revised_requires_initial_and_files_use_explicit_fake(tmp_path):
    bad = subprocess.run([sys.executable,"-m","app.abd_input_hmi","--synthetic-b","--revised-result",str(REVISED_PATH)],
                         cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert bad.returncode == 2
    good = subprocess.run([sys.executable,"-m","app.abd_input_hmi","--synthetic-b",
                           "--initial-result",str(INITIAL_PATH),"--revised-result",str(REVISED_PATH),"--log-dir",str(tmp_path)],
                          cwd=ROOT,input="",capture_output=True,text=True,timeout=10)
    assert good.returncode == 0 and "C 저장 응답" in good.stdout
    assert not list(tmp_path.glob("*.jsonl"))
