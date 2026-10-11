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
from test_robot_controller import CONFIG


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


def test_planner_multiple_errors_render_in_existing_notice(window, qapp):
    from app.snapshot import make_snapshot
    from test_backend import started

    backend, ports = started()
    errors = [dict(reason="목표가 보드 밖입니다.", block=dict(x=24)),
              dict(reason="설계를 다시 확인해주세요.", block=None)]
    backend.on_plan_result(ports.calls("planner")[-1]["request_id"],
                           dict(status="INVALID", plan=None, errors=errors))
    window.snapshot_received.emit(make_snapshot(backend.state))
    qapp.processEvents()
    text = window.notice.toPlainText()
    assert all(error["reason"] in text for error in errors)
    assert "24" in text
    assert not window.buttons["CONTINUE_AFTER_CORRECTION"].isVisible()


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
    assert len(window.design_board.blocks) == 3
    assert window.target_board.blocks == demo.backend.state["current"]["blocks"]
    assert window.target_board.target is None
    records = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert sum(record["event"]=="STEP_CONFIRMED" for record in records)==3


def test_wider_fixed_frame_and_all_panels_fit_without_main_scroll(window):
    assert window.frameGeometry().width() == 1200 and window.frameGeometry().height() == 900
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


def wait_until(demo, condition):
    for _ in range(300):
        QTest.qWait(5)
        if condition():
            return
    pytest.fail(f"Fake condition was not reached: {demo.backend.state['workflow_status']}")


@pytest.mark.parametrize("stage,next_operation", [("pick","pick"), ("place","place"), ("observe","observe")])
def test_qt_stop_resume_routes_to_controller_without_duplicate_consumption(window, qapp, tmp_path, stage, next_operation):
    demo = FakeDemo(window, tmp_path, delay_ms=15)
    qapp.processEvents(); window.buttons["START"].click()
    wait_until(demo, lambda: (demo.controller.state["active_execution"] or {}).get("stage") == stage)
    old = demo.backend.state["execution_id"]
    window.buttons["STOP"].click()
    wait_for(demo, "STOPPED"); qapp.processEvents()
    assert demo.backend.state["current"]["blocks"] == []
    assert window.buttons["RESUME"].isEnabled()
    window.buttons["RESUME"].click()
    new = demo.backend.state["execution_id"]
    assert new != old and demo.driver.calls[-1][0] == next_operation
    wait_for(demo, "COMPLETE"); qapp.processEvents()
    assert [row["next_slot"] for row in window._snapshot["monitor"]["supply"]] == [3,1,1,2,1]
    assert demo.backend.state["current"]["blocks"] == demo.fixtures["design"]["blocks"]


def test_qt_refill_button_reaches_backend_controller_and_resumes_after_new_empty(window, qapp, tmp_path):
    config_path = tmp_path/"robot.json"
    config_path.write_text(json.dumps({**deepcopy(CONFIG), "slot_count":1}))
    demo = FakeDemo(window, tmp_path/"logs", delay_ms=1, robot_config=config_path)
    qapp.processEvents(); window.buttons["START"].click()
    wait_until(demo, lambda: demo.backend.state["reason"] == "NEEDS_REFILL")
    qapp.processEvents()
    button = window.refill_buttons["2x2x1","yellow"]
    assert button.isVisible() and button.isEnabled() and "보충 필요" in window.supply.text()
    assert demo.backend.state["current"]["current_revision"] == 1
    assert len(demo.driver.calls) == 3
    button.click()
    wait_for(demo, "COMPLETE"); qapp.processEvents()
    assert len([op for op,_ in demo.driver.calls if op == "pick"]) == 3
    assert demo.controller.state["supply"][0]["needs_refill"]


@pytest.mark.parametrize("scenario,slot", [("robot-pick-failure",1), ("robot-return-failure",2), ("robot-timeout",1)])
def test_qt_robot_fault_keeps_slots_and_requires_separate_cleanup_before_new_start(window, qapp, tmp_path, scenario, slot):
    demo = FakeDemo(window, tmp_path, delay_ms=1, scenario=scenario)
    qapp.processEvents(); window.buttons["START"].click()
    wait_until(demo, lambda: demo.backend.state["fault"] is not None)
    assert demo.backend.state["current"]["blocks"] == []
    assert demo.controller.state["supply"][0]["next_slot"] == slot
    qapp.processEvents(); window.buttons["STOP"].click()
    wait_until(demo, lambda: demo.controller.state["stop"]["confirmed"])
    qapp.processEvents()
    assert not window.buttons["RESUME"].isEnabled() and not window.buttons["START"].isEnabled()
    assert demo.confirm_robot_cleanup()
    qapp.processEvents()
    assert window.buttons["START"].isEnabled() and demo.controller.state["supply"][0]["next_slot"] == slot
    old_job = demo.backend.state["job_id"]
    window.buttons["START"].click()
    assert demo.backend.state["job_id"] != old_job
    assert demo.controller.state["supply"][0]["next_slot"] == 1


def test_qt_external_fixture_and_robot_config_paths_are_used_without_live_config_changes(window,qapp,tmp_path):
    fixture_path = tmp_path/"day4.json"
    fixtures = json.loads((Path(__file__).resolve().parents[2]/"interfaces/fixtures/day4.json").read_text())
    for block in fixtures["design"]["blocks"]:
        block["x"] += 1
    for step in fixtures["initial_plan"]["steps"]:
        step["after"]["x"] += 1
    fixture_path.write_text(json.dumps(fixtures))
    config_path = tmp_path/"robot.json"
    config = {**deepcopy(CONFIG), "config_id":"alternate", "observe_point":"fake-custom-observe"}
    config_path.write_text(json.dumps(config))
    demo = FakeDemo(window, tmp_path/"logs", delay_ms=1, fixture_path=fixture_path,robot_config=config_path)
    qapp.processEvents(); window.buttons["START"].click()
    config["observe_point"] = "fake-next-job-observe"
    config_path.write_text(json.dumps(config))
    wait_for(demo,"COMPLETE"); qapp.processEvents()
    assert window.design_board.blocks == fixtures["design"]["blocks"]
    assert {payload["point"] for op,payload in demo.driver.calls if op == "observe"} == {"fake-custom-observe"}
    window.buttons["START"].click()
    wait_for(demo,"COMPLETE")
    assert demo.driver.calls[-1][1]["point"] == "fake-next-job-observe"


def test_closed_fake_vision_timer_cannot_change_simulated_actual_or_current_after_stop(window,qapp,tmp_path):
    demo = FakeDemo(window,tmp_path,delay_ms=15)
    qapp.processEvents(); window.buttons["START"].click()
    wait_for(demo,"WAIT_ASSEMBLY")
    payload = dict(check_id=demo.backend.state["active_check"]["check_id"], after=demo.fixtures["design"]["blocks"][0])
    window.buttons["STOP"].click()
    wait_for(demo,"STOPPED")
    before = deepcopy(demo._actual)
    current = demo.backend.state["current"]
    demo.receive("vision",payload)
    assert demo._actual == before and demo.backend.state["current"] == current
    assert len(demo.driver.calls) == 4


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


@pytest.mark.parametrize("height_ratio", [1.2, .4])
def test_isometric_brick_uses_configured_height_in_stud_units(qapp, height_ratio):
    from app.hmi_board import BoardView

    board = BoardView(isometric=True, brick_height_per_stud=height_ratio)
    origin = board._project(0,0,0)
    # 기본 brick은 폭20/높이24, plate는 폭20/높이8 LDU. 투영 세 축은 같은 축척이다.
    assert (board._project(1,0,0)-origin).x()**2 + (board._project(1,0,0)-origin).y()**2 == pytest.approx(1)
    assert (board._project(0,0,1)-origin).y() == pytest.approx(-height_ratio)
    assert board._project(0,0,4).y() == pytest.approx(-4*height_ratio)


def test_back_view_axes_match_design_and_current_without_swapping_coordinates(window, qapp):
    snapshot = deepcopy(HMI["snapshots"]["waiting"])
    before = deepcopy(snapshot)
    window.render_snapshot(snapshot)
    qapp.processEvents()
    for board in (window.design_board, window.target_board):
        origin = board._project(3, 5, 1)
        x_forward = board._project(4, 5, 1) - origin
        y_forward = board._project(3, 6, 1) - origin
        layer_up = board._project(3, 5, 2) - origin
        assert x_forward.x() < 0 and x_forward.y() > 0  # +X: 화면 왼쪽 아래
        assert y_forward.x() > 0 and y_forward.y() > 0  # +Y: 화면 오른쪽 아래
        assert layer_up.x() == 0 and layer_up.y() < 0
    assert "X ↙ / Y ↘" in window.comparison.text()
    assert "등받이 뒤쪽 시점" in window.design_caption.text()
    assert window.design_board.blocks == snapshot["design"]["blocks"]
    assert window.target_board.current == snapshot["current"]
    assert window.target_board.target == snapshot["step"]["target"]
    assert snapshot == before
    assert not window.grab().isNull()


@pytest.mark.parametrize("x,y,width,height", [(0,0,420,155), (21,0,420,260),
                                              (0,21,420,260), (21,21,280,155)])
@pytest.mark.parametrize("layers", [4, 5])
def test_layer_preview_and_zoom_fit_with_studs_and_preserve_input(qapp, monkeypatch, tmp_path, x,y,width,height,layers):
    from app.hmi_board import BoardView, dimensions, STUD_HEIGHT

    board = BoardView(isometric=True)
    blocks = [dict(brick_type="2x3x1",color="blue",x=x,y=y,layer=layer,orientation_deg=90)
              for layer in range(1,layers+1)]
    before = deepcopy(blocks)
    board.resize(width,height)
    board.set_blocks(blocks)
    draws=[]
    original = board._brick

    def draw(painter, block, project, scale):
        w,d = dimensions(block)
        points=[project(px,py,z) for px in (block["x"],block["x"]+w)
                for py in (block["y"],block["y"]+d)
                for z in (block["layer"]-1,block["layer"]+STUD_HEIGHT/board.brick_height_per_stud)]
        draws.append(points)
        original(painter,block,project,scale)

    monkeypatch.setattr(board,"_brick",draw)
    board.show();qapp.processEvents()
    assert board.grab().save(str(tmp_path/f"{layers}-layer-{x}-{y}.png"))
    assert draws and len(draws)%(layers*2)==0
    for group in range(0,len(draws),layers*2):
        for index,points in enumerate(draws[group:group+layers*2]):
            left,right=(0,width*.6) if index<layers else (width*.6,width)
            assert all(left < point.x() < right and 22 < point.y() < height-10 for point in points)
    assert blocks == before and board.blocks == before
    board.close()


@pytest.mark.parametrize('width', [960,1200])
def test_explicit_window_size_preserves_fixed_frame_and_panels(qapp, width):
    window=HmiWindow(screen_size=QSize(1920,1080),window_size=QSize(width,900))
    window.render_snapshot(HMI['snapshots']['waiting'])
    window.show();qapp.processEvents()
    assert window.frameGeometry().size()==QSize(width,900)
    assert window.minimumSize()==window.maximumSize()
    assert window.table.verticalScrollBar().maximum()==0
    for widget in (window.target_board,window.target_caption,window.table,window.monitor,
                   window.supply,window.notice,window.footer,*window.buttons.values()):
        if widget.isVisible():
            corner=widget.mapTo(window,widget.rect().bottomRight())
            assert 0<=corner.x()<window.width() and 0<=corner.y()<window.height()
    window.close()
