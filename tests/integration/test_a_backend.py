"""실제 A + 첨부 C Mock 응답 + D + FakeRobot + Qt/JSONL 연결 시험."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.completion import _current
from app.fake_robot_driver import FakeRobotDriver
from app.jsonl_log import JsonlLog
from app.planning_connection import current_blocks_for_c, on_c_intervention, run_planning_request
from app.qt_hmi import HmiWindow
from app.replan import open_current_check
from app.snapshot import make_snapshot
from planning_trial.planner import plan_from_current


ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "interfaces/fixtures/a_backend_cases.json").read_text())
# 보관된 4층 기준 자료는 유지하고 범위 초과 시험 입력을 6층으로 파생한다.
DATA["cases"]["invalid"]["design"]["blocks"][0]["layer"] = 6
CONFIG = json.loads((ROOT / "interfaces/fixtures/robot.json").read_text())


def connected(tmp_path, *, current=None):
    from app.robot_controller import RobotController

    calls = []
    def emit(port, payload):
        calls.append((port, deepcopy(payload)))
        if port == "planner" and "design" in payload:
            run_planning_request(backend, payload)
    backend = Backend(emit, mode="FAKE", record=JsonlLog(tmp_path))
    driver = FakeRobotDriver(ready_at_observe=True)
    controller = RobotController(CONFIG, driver, backend.on_robot_result,
                                 on_stopped=backend.on_stopped, on_event=backend.on_robot_event)
    backend.connect_robot(controller)
    assert backend.command(dict(command="START"))["accepted"]
    if current is not None:
        # 첨부 Current는 이미 채택한 상태의 Fixture로 주입한다. 카메라 검증과 구분한다.
        backend._state["current"] = _current(current)
        backend._state["planning_request"]["base_current_revision"] = current["current_revision"]
    return backend, driver, calls


def start_design(backend, response=None):
    request = backend.state["planning_request"]["request_id"]
    assert backend.on_initial_design(request, deepcopy(response or DATA["initial_response"]))
    return request


def frame(check, blocks, *, status="OK", seq=0):
    return dict(check_id=check, observation_seq=seq, status=status,
                visible_blocks=deepcopy(blocks) if status == "OK" else [],
                verified_regions=[dict(x=0,y=0,width=24,height=24,layer=layer)
                                  for layer in range(1,5)] if status == "OK" else [],
                reason=None if status == "OK" else "hand occlusion")


def finish_delivery(backend, driver):
    if backend.state["workflow_status"] == "HOLD":
        assert backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
        if backend.state["reason"] == "NEEDS_REFILL":
            # 모의 운영자가 보충을 확인한다. 재계획으로 공급 순서를 초기화하지 않는다.
            target = backend._next_step()["after"]
            current = backend.state["current"]
            assert backend.command(dict(command="SUPPLY_REFILLED",job_id=backend.state["job_id"],
                brick_type=target["brick_type"],color=target["color"]))["accepted"]
            assert backend.state["current"] == current and backend.state["execution_id"] is None
            assert backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    execution = backend.state["execution_id"]
    before = deepcopy(backend.state["current"])
    confirmed = len(backend.state["context"]["confirmed_steps"])
    for operation in ("pick", "place", "observe"):
        assert driver.confirm(execution, operation)
    assert backend.state["current"] == before
    assert len(backend.state["context"]["confirmed_steps"]) == confirmed
    return backend.state["active_check"]["check_id"]


def assemble_next(backend, driver):
    target = backend._next_step()["after"]
    check = finish_delivery(backend, driver)
    actual = backend.state["current"]["blocks"] + [target]
    assert backend.on_observation(frame(check, actual))


def records(tmp_path, backend):
    return [json.loads(line) for line in (tmp_path / (backend.state["job_id"] + ".jsonl")).read_text().splitlines()]


@pytest.mark.parametrize("name", DATA["cases"])
def test_actual_a_reproduces_archived_case_status_and_remaining_count(name):
    case = deepcopy(DATA["cases"][name])
    original = deepcopy(case)
    result = plan_from_current(case["design"], case["current"])
    assert result["status"] == case["expected_status"]
    assert case == original
    if result["status"] == "READY":
        assert result["errors"] == []
        assert len(result["plan"]["steps"]) == case["expected_steps"]
        assert result["plan"]["base_current_revision"] == case["current"]["current_revision"]
    else:
        assert result["plan"] is None and result["errors"]


def test_a_source_preserves_archived_calculation_except_authorized_contract_changes():
    # 보관된 원본 해시는 유지하고 승인된 계약 경계 변경만 역변환해 계산 본문을 대조한다.
    source = (ROOT / "planning_trial/planner.py").read_text()
    source = source.replace("MAX_LAYER = 5", "MAX_LAYER = 4").replace(
        "from 1 to {MAX_LAYER}", "from 1 to 4")
    source = source.replace("The caller relays B-confirmed Current and its B-issued revision through D.",
                            "The caller provides Backend's adopted actual blocks and their revision.")
    source = source.replace('BRICK_SIZES = {"1x2x1": (1, 2), "2x2x1": (2, 2), "2x3x1": (2, 3)}',
                            'BRICK_SIZES = {"2x2x1": (2, 2), "2x3x1": (2, 3)}')
    source = source.replace('if (brick["brick_type"] == "1x2x1" and brick["color"] != "red" or\n'
                            '            brick["brick_type"] != "1x2x1" and brick["color"] not in ("yellow", "blue")):\n'
                            '        raise PlanningError(f"{prefix}: unsupported brick_type/color inventory pair", brick)',
                            'if brick["color"] not in ("yellow", "blue"):\n'
                            '        raise PlanningError(f"{prefix}: color must be yellow or blue", brick)')
    source = source.replace('if not isinstance(values, list) or not 1 <= len(values) <= 40:\n'
                            '        raise ValueError("blocks must contain 1..40 placements")',
                            'if not isinstance(values, list) or not values:\n'
                            '        raise ValueError("blocks must be a nonempty list")')
    assert hashlib.sha256(source.encode()).hexdigest() == DATA["a_source_sha256"]


@pytest.mark.parametrize("name", DATA["cases"])
def test_all_initial_outcomes_connect_to_backend_hmi_and_log(tmp_path, name):
    case = DATA["cases"][name]
    backend, driver, calls = connected(tmp_path, current=case["current"])
    response = {**DATA["initial_response"], "design": case["design"]}
    identity = start_design(backend, response)
    result = next(row["result"] for row in records(tmp_path, backend) if row["event"] == "PLAN_RESULT")
    assert result["status"] == case["expected_status"]
    assert backend.state["current"] == case["current"]
    assert not driver.calls
    snapshot = make_snapshot(backend.state)
    if result["status"] == "READY":
        assert snapshot["progress"] == dict(completed=0, total=case["expected_steps"])
        assert backend.state["context"]["base_current"] == case["current"]
        existing = {frozenset(block.items()) for block in case["current"]["blocks"]}
        assert not existing.intersection(frozenset(step["after"].items()) for step in result["plan"]["steps"])
    else:
        assert backend.state["context"] is None
        assert snapshot["workflow_status"] == ("WAIT_CORRECTION" if name == "needs_correction" else "HOLD")
        assert result["errors"][0]["reason"] in snapshot["notice"]["reason"]
        assert all(error["reason"] in snapshot["notice"]["required_action"] for error in result["errors"])
        if name == "invalid": assert result["errors"][0]["block"]["layer"] == 6
    assert not backend.on_initial_design(identity, response)
    assert len([p for port,p in calls if port == "planner" and "design" in p]) == 1


def test_full_fifteen_step_fake_robot_cycle_needs_observations(tmp_path):
    backend, driver, _ = connected(tmp_path)
    start_design(backend)
    for _ in range(15):
        assemble_next(backend, driver)
    assert backend.state["workflow_status"] == "COMPLETE"
    assert {frozenset(b.items()) for b in backend.state["current"]["blocks"]} == {
        frozenset(b.items()) for b in DATA["initial_response"]["design"]["blocks"]}
    events = records(tmp_path, backend)
    assert sum(row["event"] == "DELIVERY_RESULT" for row in events) == 15
    assert sum(row["event"] == "STEP_CONFIRMED" for row in events) == 15
    assert len(driver.calls) == 45


@pytest.mark.parametrize("revision", [False, True])
def test_actual_a_result_wrong_version_or_revision_is_not_adopted(tmp_path, revision):
    backend, driver, calls = connected(tmp_path)
    request = calls[-1][1]
    result = plan_from_current(DATA["initial_response"]["design"], backend.state["current"])
    result["plan"]["base_current_revision" if revision else "design_version"] += 1
    assert backend.on_plan_result(request["request_id"], result, design=DATA["initial_response"]["design"])
    assert backend.state["workflow_status"] == "HOLD" and backend.state["context"] is None
    assert not driver.calls


def test_actual_current_after_four_observations_is_used_for_remaining(tmp_path):
    from app.replan import begin_replan

    backend, driver, calls = connected(tmp_path)
    start_design(backend)
    for _ in range(4): assemble_next(backend, driver)
    current = backend.state["current"]
    assert current["current_revision"] == 4 and len(current["blocks"]) == 4
    begin_replan(backend, DATA["initial_response"]["design"])
    assert backend.state["context"]["base_current"] == current
    assert len(backend.state["context"]["plan"]["steps"]) == 11
    assert backend.state["context"]["plan"]["base_current_revision"] == 4
    assert calls[-2][1]["current"] == current
    assert len(driver.calls) == 12


def changed_after_four(tmp_path):
    backend, driver, calls = connected(tmp_path)
    start_design(backend)
    for _ in range(4): assemble_next(backend, driver)
    open_current_check(backend, "INTENT")
    moved = DATA["revised_inputs"]["current"]["blocks"]
    check = backend.state["current_check"]["check_id"]
    assert backend.on_observation(frame(check, moved))
    assert backend.state["workflow_status"] == "WAIT_INTENT"
    return backend, driver, calls


def test_c_revised_response_preserves_actual_current_and_adopts_eleven_step_plan(tmp_path):
    backend, driver, calls = changed_after_four(tmp_path)
    hri = next(payload for port,payload in reversed(calls) if port == "hri")
    assert current_blocks_for_c(hri) == backend.state["current"]["blocks"]
    before = backend.state["current"]
    assert on_c_intervention(backend, hri["request_id"], DATA["revised_response"])
    state = backend.state
    assert state["current"] == before and state["context"]["base_current"] == before
    assert state["context"]["design"]["design_version"] == 2
    assert len(state["context"]["plan"]["steps"]) == 11
    assert state["context"]["plan"]["base_current_revision"] == before["current_revision"]
    assert not on_c_intervention(backend, hri["request_id"], DATA["revised_response"])
    assert len(driver.calls) == 12
    for _ in range(11): assemble_next(backend, driver)
    assert backend.state["workflow_status"] == "COMPLETE"


def test_keep_requires_correction_then_observed_cleanup_replans(tmp_path):
    backend, driver, calls = changed_after_four(tmp_path)
    request = backend.state["question_request"]["request_id"]
    assert backend.on_intent(dict(request_id=request, decision="KEEP"))
    assert backend.state["workflow_status"] == "WAIT_CORRECTION"
    backend.command(dict(command="CONTINUE_AFTER_CORRECTION",job_id=backend.state["job_id"],
                         request_id=backend.state["correction_request"]["request_id"]))
    corrected = DATA["cases"]["partial"]["current"]["blocks"]
    assert backend.on_observation(frame(backend.state["current_check"]["check_id"], corrected))
    assert backend.state["context"]["base_current"] == backend.state["current"]
    assert {frozenset(b.items()) for b in backend.state["current"]["blocks"]} == {
        frozenset(b.items()) for b in corrected}
    assert len(backend.state["context"]["plan"]["steps"]) == 11
    assert len(driver.calls) == 12


def test_initial_correction_observes_without_fabricating_a_plan(tmp_path):
    case = DATA["cases"]["needs_correction"]
    backend, driver, _ = connected(tmp_path, current=case["current"])
    start_design(backend)
    current = backend.state["current"]
    backend.command(dict(command="CONTINUE_AFTER_CORRECTION",job_id=backend.state["job_id"],
                         request_id=backend.state["correction_request"]["request_id"]))
    check = backend.state["current_check"]
    assert check["plan_id"] is None and check["step_id"] is None
    assert backend.state["current"] == current
    block = {**case["current"]["blocks"][0], "color": "blue"}
    assert backend.on_observation(frame(check["check_id"], [block]))
    assert backend.state["current"]["current_revision"] == current["current_revision"] + 1
    assert len(backend.state["context"]["plan"]["steps"]) == 14
    assert not driver.calls


def test_unobservable_or_mismatch_does_not_dispatch_next_delivery(tmp_path):
    backend, driver, _ = connected(tmp_path)
    start_design(backend)
    check = finish_delivery(backend, driver)
    assert backend.on_observation(frame(check, [], status="UNOBSERVABLE"))
    assert backend.state["current"]["blocks"] == [] and len(driver.calls) == 3
    target = backend._next_step()["after"]
    assert backend.on_observation(frame(check, [{**target,"color":"yellow"}], seq=1))
    assert backend.state["workflow_status"] == "WAIT_INTENT"
    assert backend.state["current"]["blocks"][0]["color"] == "yellow"
    assert len(driver.calls) == 3


def test_qt_shows_actual_a_invalid_diagnostic(tmp_path):
    qapp = QApplication.instance() or QApplication([])
    backend, driver, _ = connected(tmp_path)
    response = {**DATA["initial_response"], "design":DATA["cases"]["invalid"]["design"]}
    start_design(backend, response)
    window = HmiWindow(screen_size=QSize(1920,1080))
    window.snapshot_received.emit(make_snapshot(backend.state))
    qapp.processEvents()
    reason = backend.state["planner_errors"][0]["reason"]
    assert reason in window.notice.toPlainText() and "5" in window.notice.toPlainText()
    assert not driver.calls
    window.close()


@pytest.mark.parametrize("response", [None, {"status":"CANCELLED"},
                                      {"status":"OK","design":None},
                                      {"status":"OK","design":{"design_version":2,"blocks":[]}}])
def test_unsuccessful_initial_c_response_does_not_call_a(tmp_path, response):
    backend, driver, calls = connected(tmp_path)
    request = backend.state["planning_request"]["request_id"]
    assert backend.on_initial_design(request, response)
    assert backend.state["workflow_status"] == "HOLD"
    assert backend.state["context"] is None and not driver.calls
    assert not any(port == "planner" and "design" in payload for port,payload in calls)


def test_initial_response_after_stop_is_not_used(tmp_path):
    backend, driver, calls = connected(tmp_path)
    request = backend.state["planning_request"]["request_id"]
    backend.command(dict(command="STOP",job_id=backend.state["job_id"]))
    assert driver.confirm_stop(backend.state["stop_request"],stopped=True,execution_ended=True,
                               block_state_known=True,block_state="UNPICKED")
    assert not backend.on_initial_design(request, DATA["initial_response"])
    assert not any(port == "planner" and "design" in payload for port,payload in calls)


def test_c_current_list_is_copied_without_losing_d_revision():
    payload = dict(current=deepcopy(DATA["cases"]["partial"]["current"]))
    before = deepcopy(payload)
    blocks = current_blocks_for_c(payload)
    blocks[0]["x"] = 23
    assert payload == before and payload["current"]["current_revision"] == 1
