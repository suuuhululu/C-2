import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import json
from pathlib import Path

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.fake_demo import FakeDemo
from app.qt_hmi import HmiWindow


HMI = json.loads((Path(__file__).resolve().parents[2]/"interfaces/fixtures/hmi.json").read_text())


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    window = HmiWindow(screen_size=QSize(1920,1080))
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def test_fake_demo_qt_signals_finish_normal_three_steps_and_write_job_log(window, qapp, tmp_path):
    demo = FakeDemo(window,tmp_path,delay_ms=1)
    qapp.processEvents()
    window.buttons["START"].click()
    for _ in range(70):
        QTest.qWait(5)
        if demo.backend.state["workflow_status"] == "COMPLETE":
            break
    qapp.processEvents()
    assert demo.backend.state["workflow_status"] == "COMPLETE"
    assert window.status.text() == "전체 조립 완료"
    assert "조립 확인 3 / 3" in window.progress.text()
    assert "누적 실제 배치 3개 일치" in window.notice.toPlainText()
    assert window.buttons["START"].isEnabled() and not window.buttons["STOP"].isEnabled()
    assert len(window.design_board.blocks) == 3 and window.target_board.blocks == []
    records = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert sum(record["event"]=="STEP_CONFIRMED" for record in records)==3


def test_half_width_frame_and_all_panels_fit_without_main_scroll(window):
    assert window.frameGeometry().width() == 960 and window.frameGeometry().height() == 900
    for widget in (window.design_panel,window.step_panel,window.notice,window.monitor,window.supply,
                   window.footer, *window.buttons.values()):
        if widget.isVisible():
            point = widget.mapTo(window,widget.rect().bottomRight())
            assert 0<=point.x()<window.width() and 0<=point.y()<window.height()
    assert window.minimumSize() == window.maximumSize()


def test_all_existing_hmi_fixture_snapshots_render_and_commands_use_bound_ids(window):
    commands=[]
    window.command_requested.connect(commands.append)
    snapshots = HMI["snapshots"]
    for snapshot in snapshots.values():
        window.render_snapshot(snapshot)
        assert window.design_board.blocks == (snapshot["design"]["blocks"] if snapshot["design"] else [])
        for button,field in (("START","start"),("STOP","stop"),("RESUME","resume")):
            assert window.buttons[button].isEnabled()==snapshot["actions"][field]["enabled"]
        if snapshot["actions"]["intent_choice"]["visible"]:
            window.buttons["KEEP"].click()
            assert commands[-1] == dict(command="CHOOSE_INTENT",choice="KEEP",
                job_id=snapshot["actions"]["job_id"],request_id=snapshot["notice"]["request_id"])
        for action in snapshot["actions"]["supply_refill"]:
            if action["visible"] and action["enabled"]:
                window.refill_buttons[action["brick_type"],action["color"]].click()
                assert commands[-1]==dict(command="SUPPLY_REFILLED",job_id=snapshot["actions"]["job_id"],
                                         brick_type=action["brick_type"],color=action["color"])
    assert window._snapshot is not snapshots[list(snapshots)[-1]]


def test_long_question_remains_available_without_changing_backend_snapshot(window, qapp):
    snapshot=deepcopy(next(iter(HMI["snapshots"].values())))
    snapshot["notice"]["question"]="선택의 결과와 확인할 상태를 설명합니다. "*100
    before=deepcopy(snapshot)
    window.render_snapshot(snapshot)
    qapp.processEvents()
    assert snapshot==before
    assert snapshot["notice"]["question"] in window.notice.toPlainText()
    assert window.notice.verticalScrollBar().maximum()>0


def wait_for(demo, status):
    for _ in range(160):
        QTest.qWait(5)
        if demo.backend.state["workflow_status"]==status:
            return
    pytest.fail(f"Fake did not reach {status}: {demo.backend.state['workflow_status']}")


@pytest.mark.parametrize("scenario",["keep","revise","unclear","hri-failure"])
def test_fake_qt_exception_routes_stop_next_delivery_and_follow_user_choice(window,qapp,tmp_path,scenario):
    demo=FakeDemo(window,tmp_path,delay_ms=1,scenario=scenario)
    qapp.processEvents();window.buttons["START"].click()
    if scenario=="revise":
        wait_for(demo,"COMPLETE")
        assert demo.backend.state["context"]["design"]["design_version"]==2
        assert demo.backend.state["current"]["blocks"][2]["color"]=="yellow"
    elif scenario=="hri-failure":
        wait_for(demo,"HOLD")
        # 초기 HOLD는 전달판 확인 대기이므로 HRI 실패까지 기다린다.
        for _ in range(160):
            QTest.qWait(5)
            if "CALL_FAILED hri" in (demo.backend.state["reason"] or ""):break
        assert "모의 HRI 호출 실패" in demo.backend.state["reason"]
    else:
        if scenario=="unclear":
            wait_for(demo,"WAIT_INTENT")
            for _ in range(40):
                QTest.qWait(5)
                if demo.backend.state["choice_required"]:break
            qapp.processEvents()
            assert window.buttons["KEEP"].isVisible() and window.buttons["REVISE"].isVisible()
            assert not window.buttons["CONTINUE_AFTER_CORRECTION"].isVisible()
            window.buttons["KEEP"].click()
        wait_for(demo,"WAIT_CORRECTION")
        qapp.processEvents()
        assert window.buttons["CONTINUE_AFTER_CORRECTION"].isVisible()
        before=demo.backend.state["current"]
        window.buttons["CONTINUE_AFTER_CORRECTION"].click()
        assert demo.backend.state["current"]==before
        wait_for(demo,"COMPLETE")
        assert demo.backend.state["context"]["design"]["design_version"]==1
        assert demo.backend.state["current"]["blocks"][2]["color"]=="blue"
    qapp.processEvents()
    records=[json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    goals=[record for record in records if record["event"]=="REQUEST_SENT" and record["result"]["port"]=="robot.deliver"]
    assert len(goals)==(4 if scenario in ("keep","unclear") else 3)
    assert sum(record["event"]=="JOB_COMPLETED" for record in records)==(0 if scenario=="hri-failure" else 1)


def test_unclear_revise_button_finishes_with_atomic_new_design(window,qapp,tmp_path):
    demo=FakeDemo(window,tmp_path,delay_ms=1,scenario="unclear")
    qapp.processEvents();window.buttons["START"].click();wait_for(demo,"WAIT_INTENT")
    for _ in range(40):
        QTest.qWait(5)
        if demo.backend.state["choice_required"]:break
    qapp.processEvents();assert window.buttons["REVISE"].isVisible()
    window.buttons["REVISE"].click();wait_for(demo,"COMPLETE");qapp.processEvents()
    assert window.design_board.blocks[2]["color"]=="yellow"
    assert demo.backend.state["context"]["design"]["design_version"]==2
    assert demo.backend.state["current"]["current_revision"]==3


@pytest.mark.parametrize("scene",["waiting","choice"])
def test_three_visible_blocks_keep_all_fields_visible_without_table_vertical_scroll(window,qapp,scene):
    snapshot=deepcopy(HMI["snapshots"][scene])
    snapshot["step"]["observed"]={"check_id":"three-visible","observation_seq":1,"status":"OK",
        "visible_blocks":deepcopy(snapshot["design"]["blocks"]),
        "verified_regions":[dict(x=3,y=5,width=4,height=2,layer=1),dict(x=3,y=5,width=3,height=2,layer=2)],"reason":None}
    snapshot["step"]["comparison"]="MATCH"
    snapshot["monitor"]["observation"]=dict(status="OK",check_id="three-visible",observation_seq=1,reason=None)
    window.render_snapshot(snapshot);qapp.processEvents()
    assert window.table.columnCount()==5
    assert window.table.item(4,4).text()=="90°"
    assert window.table.verticalScrollBar().maximum()==0
