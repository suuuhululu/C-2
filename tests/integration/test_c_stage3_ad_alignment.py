"""C Stage3 승인 경계와 A/D의 5층·최종 재고 연결. 장치·네트워크는 호출하지 않는다."""
from copy import deepcopy
from pathlib import Path
import json

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.c_candidate import open_candidate, on_review, valid_review
from app.c_design import main as c_main, validator
from app.c_text_connection import CTextConnection
from app.contracts import validate_block, validate_design
from app.current import _footprint
from app.fake_robot_driver import FakeRobotDriver
from app.hmi_board import dimensions
from app.hmi_contracts import validate_hmi_snapshot
from app.planning_connection import run_planning_request
from app.qt_hmi import HmiWindow, fields
from app.robot_controller import RobotController, validate_robot_config
from app.snapshot import make_snapshot
from planning_trial.planner import plan_from_current

ROOT = Path(__file__).resolve().parents[2]


def red(layer=1, **changes):
    return dict(brick_type="1x2x1", color="red", x=0, y=0, layer=layer, orientation_deg=0, **changes)


def candidate(blocks=None, version=1):
    return dict(status="OK", hri_result=None, design=dict(design_version=version,
        blocks=blocks or [red(layer) for layer in range(1, 6)]), design_metadata=dict(review=dict(round=1)))


def backend():
    calls = []
    b = Backend(lambda port, payload: calls.append((port, deepcopy(payload))), mode="FAKE")
    b.controller_ready(ready=True, at_observe_point=True)
    assert b.command(dict(command="START"))["accepted"]
    return b, calls


def displayed(b):
    b._state["c_review"]["phase"] = "REVIEW"
    return b.state["c_review"]


def test_c_red_five_layers_crosses_actual_a_d_hmi_boundaries():
    design = candidate()["design"]
    assert validator.validate_design(design) == []
    result = plan_from_current(design, dict(current_revision=0, blocks=[]))
    assert result["status"] == "READY" and len(result["plan"]["steps"]) == 5
    assert validate_design(design) == design
    assert dimensions(red()) == (1, 2)
    rotated = {**red(), "orientation_deg": 90}
    assert dimensions(rotated) == (2, 1)
    assert _footprint(rotated) == {(0, 0, 1), (1, 0, 1)}
    assert fields(red())[:2] == ["2점 (1×2)", "빨강"]


@pytest.mark.parametrize("brick,color", [("1x2x1", "yellow"), ("1x2x1", "blue"), ("2x2x1", "red"), ("2x3x1", "red")])
def test_unavailable_inventory_combinations_remain_invalid(brick, color):
    bad = {**red(), "brick_type": brick, "color": color}
    with pytest.raises(ValueError):
        validate_block(bad)
    assert plan_from_current(dict(design_version=1, blocks=[bad]), dict(current_revision=0, blocks=[]))["status"] == "INVALID"


def test_forty_blocks_are_valid_but_forty_one_are_rejected():
    blocks = [dict(brick_type="2x2x1", color="yellow" if layer % 2 else "blue", x=x, y=0,
                   layer=layer, orientation_deg=0) for layer, xs in
              ((1, range(0, 18, 2)), (2, range(1, 17, 2)), (3, range(1, 17, 2)),
               (4, range(1, 17, 2)), (5, range(1, 15, 2))) for x in xs]
    design = dict(design_version=1, blocks=blocks)
    assert validator.validate_design(design) == []
    assert len(plan_from_current(design, dict(current_revision=0, blocks=[]))["plan"]["steps"]) == 40
    too_many = dict(design_version=1, blocks=blocks + [{**red(), "x": 8}])
    assert plan_from_current(too_many, dict(current_revision=0, blocks=[]))["status"] == "INVALID"
    with pytest.raises(ValueError, match="40"):
        validate_design(too_many)


def test_preview_modify_approve_and_duplicate_gate_actual_a(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "0")
    b, calls = backend()
    source = b.state["planning_request"]
    assert open_candidate(b, "initial", source, candidate())
    assert b.state["context"] is None and len(calls) == 1
    identity = b.state["c_review"]["request_id"]
    assert not open_candidate(b, "initial", source, candidate())
    assert b.state["c_review"]["request_id"] == identity
    snapshot = make_snapshot(b.state)
    assert snapshot["design"] is None and snapshot["design_preview"]["design"] == candidate()["design"]
    first = displayed(b)
    modify = c_main.review_design_candidate(first["design"], kind="initial", text_answers=["수정"])
    assert modify["hri_result"] == "MODIFY"
    assert on_review(b, first, modify)
    assert b.state["c_review"]["phase"] == "PREVIEW" and len(calls) == 1
    assert b.state["c_review"]["design"]["design_version"] == 1
    assert not on_review(b, first, {**modify, "hri_result":"APPROVE"})
    second = displayed(b)
    approved = c_main.review_design_candidate(second["design"], kind="initial", text_answers=["좋아요"])
    assert approved["hri_result"] == "APPROVE"
    assert on_review(b, second, approved)
    assert calls[-1][0] == "planner" and calls[-1][1]["design"] == second["design"]
    assert run_planning_request(b, calls[-1][1])
    assert b.state["context"]["design"] == second["design"]
    count = len(calls)
    assert not on_review(b, second, approved) and len(calls) == count


@pytest.mark.parametrize("change", ["stop", "revision", "job"])
def test_late_review_never_plans_or_delivers(change):
    b, calls = backend()
    open_candidate(b, "initial", b.state["planning_request"], candidate())
    review = displayed(b)
    if change == "stop":
        b.command(dict(command="STOP", job_id=b.state["job_id"]))
    elif change == "revision":
        b._state["current"]["current_revision"] += 1
    else:
        b._state["job_id"] = "new-job"
    assert not valid_review(b, review)
    assert not on_review(b, review, {**candidate(), "hri_result":"APPROVE"})
    assert not any(port == "planner" and "design" in payload or port == "robot.deliver" for port, payload in calls)


@pytest.mark.parametrize("status,decision", [("FAILED", None), ("CANCELLED", "CANCEL"), ("OK", "KEEP")])
def test_failed_cancelled_and_invalid_review_hold_without_adoption(status, decision):
    b, calls = backend()
    open_candidate(b, "initial", b.state["planning_request"], candidate())
    review = displayed(b)
    on_review(b, review, {**candidate(), "status":status, "hri_result":decision})
    assert b.state["workflow_status"] == "HOLD" and b.state["context"] is None
    assert b.state["c_review"] is None and len(calls) == 1


def test_approve_cannot_replace_the_displayed_candidate():
    b, calls = backend()
    open_candidate(b, "initial", b.state["planning_request"], candidate())
    review = displayed(b)
    different = candidate([{**red(), "x": 2}])
    different["hri_result"] = "APPROVE"
    on_review(b, review, different)
    assert b.state["workflow_status"] == "HOLD" and len(calls) == 1


def test_revised_candidate_preserves_b_current_and_does_not_change_approved():
    b, calls = backend()
    initial = candidate([red()])["design"]
    b.on_initial_design(b.state["planning_request"]["request_id"], dict(status="OK", hri_result=None, design=initial))
    run_planning_request(b, calls[-1][1])
    b._state.update(workflow_status="WAIT_INTENT", current=dict(current_revision=1, blocks=[red()]),
        difference=dict(missing=[], unexpected=[red()], unobservable=[]),
        question_request=dict(request_id="hri-revise", job_id=b.state["job_id"], design_version=1, current_revision=1))
    source = b.state["question_request"]
    assert open_candidate(b, "revised", source, candidate([red(), red(2)], 2))
    assert b.state["context"]["design"] == initial and b.state["current"]["current_revision"] == 1
    modified = candidate([{**red(), "x": 1}], 2)
    on_review(b, displayed(b), {**modified, "hri_result":"MODIFY"})
    assert b.state["workflow_status"] == "HOLD"
    assert b.state["current"]["blocks"] == [red()] and b.state["context"]["design"] == initial


def test_red_fake_supply_exhausts_refills_and_legacy_config_rejects_without_io():
    config = json.loads((ROOT / "interfaces/fixtures/robot.json").read_text())
    driver = FakeRobotDriver(ready_at_observe=True)
    robot = RobotController(config, driver, lambda result: None)
    for index in range(6):
        identity = str(index)
        assert robot.deliver(dict(execution_id=identity, brick_type="1x2x1", color="red"))["accepted"]
        for operation in ("pick", "place", "observe"):
            driver.confirm(identity, operation)
    assert robot.deliver(dict(execution_id="seventh", brick_type="1x2x1", color="red")) == dict(accepted=False, reason="NEEDS_REFILL")
    assert robot.supply_refilled("1x2x1", "red")["accepted"]
    assert robot.deliver(dict(execution_id="seventh", brick_type="1x2x1", color="red"))["accepted"]
    legacy = deepcopy(config);legacy["supply_rows"].pop()
    validate_robot_config(legacy)
    other = FakeRobotDriver(ready_at_observe=True)
    old = RobotController(legacy, other, lambda result: None)
    assert old.deliver(dict(execution_id="red", brick_type="1x2x1", color="red"))["reason"] == "UNCONFIGURED_SUPPLY_COLUMN"
    assert other.calls == []


def test_qt_preview_ready_precedes_review_and_only_approval_opens_plan(monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "0")
    qapp = QApplication.instance() or QApplication([])
    b, calls = backend()
    window = HmiWindow(screen_size=QSize(1920, 1080))
    def publish():
        window.snapshot_received.emit(make_snapshot(b.state))
    connection = CTextConnection(b, publish, initial_text="의자 만들어줘")
    window.preview_ready.connect(connection.preview_ready)
    monkeypatch.setattr(c_main, "create_initial_design", lambda **kwargs: candidate())
    connection.start("initial", b.state["planning_request"])
    for _ in range(300):
        QTest.qWait(2)
        if (b.state.get("c_review") or {}).get("phase") == "WAIT_ANSWER" and not connection.active:
            break
    review = b.state["c_review"]
    assert review["phase"] == "WAIT_ANSWER"
    assert window._snapshot["design_preview"]["design"] == review["design"]
    assert b.state["context"] is None and len(calls) == 1
    connection.answer(dict(request_id=review["request_id"], text="좋아요"))
    for _ in range(300):
        QTest.qWait(2)
        if not connection.active:
            break
    assert calls[-1][0] == "planner" and "design" in calls[-1][1]
    assert b.state["c_review"] is None
    assert b.state["approved_design"] == review["design"] and b.state["context"] is None
    connection.close();window.close()


@pytest.mark.parametrize("response", [None, [], "invalid"])
def test_malformed_c_review_is_held_without_plan(response):
    b, calls = backend()
    open_candidate(b, "initial", b.state["planning_request"], candidate())
    on_review(b, displayed(b), response)
    assert b.state["workflow_status"] == "HOLD" and len(calls) == 1
    assert b.state["approved_design"] is None


def test_json_schemas_accept_red_preview_five_supply_rows_and_reject_invalid_stock():
    from jsonschema import Draft202012Validator, RefResolver
    day4 = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    hmi = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    Draft202012Validator.check_schema(day4)
    Draft202012Validator.check_schema(hmi)
    block_validator = Draft202012Validator(day4)
    block_validator.validate(red())
    for brick, color in (("1x2x1", "yellow"), ("2x2x1", "red")):
        assert not block_validator.is_valid({**red(), "brick_type": brick, "color": color})
    b, _ = backend()
    open_candidate(b, "initial", b.state["planning_request"], candidate())
    snapshot = make_snapshot(b.state)
    snapshot["monitor"]["supply"].append(dict(brick_type="1x2x1", color="red", next_slot=1, needs_refill=False))
    validate_hmi_snapshot(snapshot)
    resolver = RefResolver(hmi["$id"], hmi, store={"https://c-2.invalid/schemas/day4.schema.json": day4})
    Draft202012Validator(hmi, resolver=resolver).validate(snapshot)
    with pytest.raises(ValueError):
        validate_hmi_snapshot({**snapshot, "monitor": {**snapshot["monitor"], "supply": snapshot["monitor"]["supply"] + [snapshot["monitor"]["supply"][-1]]}})


def test_stop_before_approval_resume_restarts_c_request_without_old_candidate():
    calls = []
    b = Backend(lambda port, payload: calls.append((port, deepcopy(payload))), mode="FAKE")
    driver = FakeRobotDriver(ready_at_observe=True)
    robot = RobotController(json.loads((ROOT / "interfaces/fixtures/robot.json").read_text()), driver,
        b.on_robot_result, on_stopped=b.on_stopped)
    b.connect_robot(robot)
    b.command(dict(command="START"))
    source = b.state["planning_request"]
    open_candidate(b, "initial", source, candidate())
    review = displayed(b)
    b.command(dict(command="STOP", job_id=b.state["job_id"]))
    driver.confirm_stop(b.state["stop_request"], stopped=True, execution_ended=True,
                        block_state_known=True, block_state="UNPICKED")
    assert b.state["workflow_status"] == "STOPPED"
    assert b.command(dict(command="RESUME", job_id=b.state["job_id"]))["accepted"]
    assert driver.calls[-1][0] == "observe"
    driver.confirm(b.state["execution_id"], "observe")
    assert b.state["workflow_status"] == "PREPARING"
    assert b.state["planning_request"]["request_id"] != source["request_id"]
    assert b.state["approved_design"] is None and b.state["c_review"] is None
    assert not on_review(b, review, {**candidate(), "hri_result":"APPROVE"})
    assert not any(operation == "pick" for operation, _ in driver.calls)
