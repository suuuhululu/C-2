"""PR #10의 실제 합성 callback + 실제 A + D. Camera/Robot/C는 장치 연결 아님."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.completion import calculate_expected
from app.fake_robot_driver import FakeRobotDriver
from app.jsonl_log import JsonlLog
from app.planning_connection import on_c_intervention, run_planning_request
from app.replan import begin_replan
from app.robot_controller import RobotController
from app.snapshot import make_snapshot
from app.qt_hmi import HmiWindow
from planning_trial.planner import plan_from_current


ROOT = Path(__file__).resolve().parents[2]
B_DIR = Path(__file__).parent / "perception_backend_callback_examples"
SPEC = importlib.util.spec_from_file_location("b_pr10_callback", B_DIR / "callback_examples.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
CONFIG = json.loads((ROOT / "interfaces/fixtures/robot.json").read_text())
YELLOW = B.block()
UPPER = B.block("blue", 2)
NEXT = {**B.block("blue"), "x": 10}


def connected(tmp_path, *, blocks=None, current=None):
    calls, planning, received = [], [], []

    def actual_a(design, adopted):
        result = plan_from_current(design, adopted)
        planning.append(deepcopy(dict(design=design, current=adopted, result=result)))
        return result

    def emit(port, payload):
        calls.append((port, deepcopy(payload)))
        if port == "planner" and "design" in payload:
            run_planning_request(backend, payload, planner=actual_a)

    backend = Backend(emit, mode="FAKE", record=JsonlLog(tmp_path))
    driver = FakeRobotDriver(ready_at_observe=True)
    backend.connect_robot(RobotController(CONFIG, driver, backend.on_robot_result,
        on_stopped=backend.on_stopped, on_event=backend.on_robot_event))
    assert backend.command(dict(command="START"))["accepted"]
    if current is not None:
        # 독립 사례의 이미 채택된 사전 Current이며 B가 추적값을 새 관측으로 보내는 것이 아니다.
        backend._state["current"] = deepcopy(current)
        backend._state["planning_request"]["base_current_revision"] = current["current_revision"]
    response = dict(status="OK", hri_result=None,
                    design=dict(design_version=1, blocks=deepcopy(blocks or [YELLOW, NEXT])))
    assert backend.on_initial_design(backend.state["planning_request"]["request_id"], response)
    return dict(backend=backend, driver=driver, calls=calls, planning=planning,
                received=received, directory=tmp_path, checkpoints=[])


def stored_case(name, check_id, seq=0):
    observed = json.loads((B_DIR / "fixtures" / f"{name}.observed.json").read_text())
    diagnostics = json.loads((B_DIR / "fixtures" / f"{name}.diagnostics.json").read_text())
    # 합성 묶음을 시작할 때만 설명용 ID를 실제 D 발급 ID에 연결한다. 도착 시 재식별하지 않는다.
    observed.update(check_id=check_id, observation_seq=seq)
    details = diagnostics["proposed_diagnostics"]
    details.update(check_id=check_id, observation_seq=seq)
    return dict(vision_result=observed, vision_diagnostics=details)


def deliver(harness, case, *, place=None, assembly=True):
    backend = harness["backend"]
    identity = case["vision_result"]
    details = case.get("vision_diagnostics", {})
    delivery = details.get("delivery_board") if place is None else dict(state=place, reason=None)
    if delivery is not None:
        # B에는 별도 진단 전달 함수가 없다. 시험용 최소 변환이며 공통 진단 계약이 아니다.
        assert details.get("check_id", identity["check_id"]) == identity["check_id"]
        assert details.get("observation_seq", identity["observation_seq"]) == identity["observation_seq"]
        result = backend.on_place(identity["check_id"], identity["observation_seq"],
                                  delivery["state"], delivery.get("reason"))
        harness["received"].append(dict(path="test_place_mapping", input=deepcopy(delivery),
                                       check_id=identity["check_id"], seq=identity["observation_seq"], accepted=result))
    if not assembly:
        return result

    def callback(payload):
        assert set(payload) == {"check_id", "observation_seq", "status", "visible_blocks", "verified_regions", "reason"}
        result = backend.on_observation(payload)
        harness["received"].append(dict(path="B.deliver_example -> D.on_observation",
                                       input=deepcopy(payload), accepted=result))
        return result

    return B.deliver_example(case, callback)


def checkpoint(harness, label):
    backend, directory = harness["backend"], harness["directory"]
    context = backend.state["context"]
    value = dict(label=label, current=backend.state["current"], snapshot=make_snapshot(backend.state),
                 plan_context=context, expected=calculate_expected(context) if context else None,
                 driver_calls=deepcopy(harness["driver"].calls))
    harness["checkpoints"].append(value)
    (directory / "result.json").write_text(json.dumps(dict(
        scope="synthetic JSON callback, actual A/D, Fake Robot, Mock C, no devices",
        checkpoints=harness["checkpoints"], planner_calls=harness["planning"],
        callback_calls=harness["received"], requests=harness["calls"]), ensure_ascii=False, indent=2))
    return value["snapshot"]


def finish_transfer(harness):
    backend, driver = harness["backend"], harness["driver"]
    check = backend.state["place_check"]["check_id"]
    assert harness["calls"][-1] == ("vision", dict(check_id=check, after=None))
    assert deliver(harness, B.examples(check, 0)[0], place="EMPTY", assembly=False)
    before = backend.state["current"]
    confirmed = len(backend.state["context"]["confirmed_steps"])
    execution = backend.state["execution_id"]
    for operation in ("pick", "place", "observe"):
        assert driver.confirm(execution, operation)
    assert backend.state["current"] == before
    assert len(backend.state["context"]["confirmed_steps"]) == confirmed
    assert backend.state["workflow_status"] == "WAIT_ASSEMBLY"
    checkpoint(harness, "Robot success without assembly confirmation")
    return backend.state["active_check"]["check_id"]


def events(harness):
    path = harness["directory"] / (harness["backend"].state["job_id"] + ".jsonl")
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("name,comparison,completed,revision", [
    ("normal_match", "MATCH", 1, 1),
    ("mismatch", "MISMATCH", 0, 1),
    ("verified_empty", "MISMATCH", 0, 0),
    ("occlusion_or_low_quality", "UNOBSERVABLE", 0, 1),
    ("lower_layer_only_occluded", "MATCH", 1, 2),
    ("delivery_unobservable", "MATCH", 1, 1),
])
def test_b_stored_json_via_actual_callback_with_a_d_hmi_jsonl(tmp_path, name, comparison, completed, revision):
    lower = name in ("occlusion_or_low_quality", "lower_layer_only_occluded")
    current = dict(current_revision=1, blocks=[YELLOW]) if lower else None
    harness = connected(tmp_path, blocks=[YELLOW, UPPER, {**YELLOW, "layer": 3}] if lower else None, current=current)
    backend, driver = harness["backend"], harness["driver"]
    assert backend._next_step()["after"] == (UPPER if lower else YELLOW)
    check = finish_transfer(harness)
    expected_before = deepcopy(backend.state["context"]["base_current"])
    fixed_expected = calculate_expected(backend.state["context"])
    case = stored_case(name, check)
    assert deliver(harness, case)
    assert len(driver.calls) == 3  # 이전 EMPTY나 Robot 성공만으로 다음 pick을 시작하지 않는다.
    assert len(backend.state["context"]["confirmed_steps"]) == completed
    assert backend.state["comparison"] == comparison
    assert backend.state["current"]["current_revision"] == revision
    assert backend.state["context"]["base_current"] == expected_before
    if not completed:
        assert calculate_expected(backend.state["context"]) == fixed_expected
    if lower:
        assert YELLOW in backend.state["current"]["blocks"]
    if name == "mismatch":
        assert backend.state["current"]["blocks"] == [B.block("blue")]
        assert backend.state["workflow_status"] == "WAIT_INTENT"
        assert backend.state["question_request"] is not None
        assert any(port == "hri" for port, _ in harness["calls"])
    elif name == "verified_empty":
        assert backend.state["current"]["blocks"] == []
        assert backend.state["workflow_status"] == "WAIT_INTENT"
    elif name == "occlusion_or_low_quality":
        assert backend.state["current"] == current
        assert backend.state["workflow_status"] == "HOLD"
    else:
        assert backend.state["reason"] == "WAIT_PLACE_EMPTY"
    snapshot = checkpoint(harness, name)
    assert snapshot["progress"] == dict(completed=completed, total=2)
    rows = events(harness)
    assert sum(row["event"] == "STEP_CONFIRMED" for row in rows) == completed
    assert sum(row["event"] == "CURRENT_ADOPTED" for row in rows) == revision - (1 if lower else 0)
    if name == "delivery_unobservable":
        row = next(row for row in rows if row["event"] == "PLACE_STATUS_CHANGED" and row["result"] == "UNOBSERVABLE")
        assert row["reason"] == "camera_view_occluded"
        assert len(driver.calls) == 3
    qapp = QApplication.instance() or QApplication([])
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.snapshot_received.emit(snapshot)
    qapp.processEvents()
    assert window.design_board.blocks == backend.state["context"]["design"]["blocks"]
    assert f"조립 확인 {completed} / 2" in window.progress.text()
    assert window.notice.toPlainText()
    assert window.grab().save(str(tmp_path / "hmi.png"))
    window.close()


def test_empty_applies_only_verified_region_and_layer(tmp_path):
    outside, covered = {**NEXT, "x": 16}, {**YELLOW, "layer": 2}
    current = dict(current_revision=3, blocks=[YELLOW, covered, outside])
    harness = connected(tmp_path, blocks=[YELLOW, covered, outside, {**NEXT, "x": 20}], current=current)
    backend = harness["backend"]
    # 초기 전달 전 Current 재확인 문맥: 사람 정리/의도 연결의 기존 경로를 사용한다.
    from app.replan import open_current_check
    open_current_check(backend, "INTENT")
    check = backend.state["current_check"]["check_id"]
    assert deliver(harness, stored_case("verified_empty", check))
    assert backend.state["current"] == dict(current_revision=4, blocks=[covered, outside])
    assert not harness["driver"].calls
    checkpoint(harness, "verified empty preserves other regions and layers")


def test_new_empty_proof_required_and_unobservable_place_independent(tmp_path):
    harness = connected(tmp_path)
    backend, driver = harness["backend"], harness["driver"]
    check = finish_transfer(harness)
    assert deliver(harness, stored_case("delivery_unobservable", check))
    assert len(driver.calls) == 3 and len(backend.state["context"]["confirmed_steps"]) == 1
    fresh = backend.state["place_check"]["check_id"]
    assert fresh != check and harness["calls"][-1][1]["after"] is None
    assert not deliver(harness, stored_case("normal_match", check), place="EMPTY", assembly=False)
    assert len(driver.calls) == 3
    blocked = stored_case("delivery_unobservable", fresh)
    assert deliver(harness, blocked, assembly=False)
    snapshot = checkpoint(harness, "place UNOBSERVABLE independently holds after completed Step")
    assert snapshot["monitor"]["place_status"] == "UNOBSERVABLE"
    assert "camera_view_occluded" in snapshot["notice"]["reason"]
    assert len(driver.calls) == 3
    qapp = QApplication.instance() or QApplication([])
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.snapshot_received.emit(snapshot)
    qapp.processEvents()
    assert "camera_view_occluded" in window.notice.toPlainText()
    assert window.grab().save(str(tmp_path / "place-unobservable-hmi.png"))
    window.close()
    assert deliver(harness, B.examples(fresh, 1)[0], place="EMPTY", assembly=False)
    assert len(driver.calls) == 4 and driver.calls[-1][0] == "pick"
    checkpoint(harness, "fresh EMPTY starts exactly one next transfer")


def test_b_observed_and_place_same_new_bundle_allow_next_transfer(tmp_path):
    harness = connected(tmp_path)
    backend, driver = harness["backend"], harness["driver"]
    check = finish_transfer(harness)
    assert deliver(harness, stored_case("normal_match", check), place="EMPTY")
    assert len(backend.state["context"]["confirmed_steps"]) == 1
    assert len(driver.calls) == 4
    assert not deliver(harness, stored_case("normal_match", check), place="EMPTY")
    assert len(driver.calls) == 4
    checkpoint(harness, "same new assembly bundle EMPTY is fresh evidence")


@pytest.mark.parametrize("revised", [False, True])
def test_actual_a_remaining_from_b_adopted_partial_or_mock_revised(tmp_path, revised):
    harness = connected(tmp_path)
    backend = harness["backend"]
    check = finish_transfer(harness)
    assert deliver(harness, stored_case("mismatch" if revised else "normal_match", check))
    current = backend.state["current"]
    if revised:
        design = dict(design_version=2, blocks=current["blocks"] + [NEXT])
        request = backend.state["question_request"]["request_id"]
        assert on_c_intervention(backend, request, dict(status="OK", hri_result="REVISE", design=design))
    else:
        design = backend.state["context"]["design"]
        begin_replan(backend, design)
    assert len(harness["planning"]) == 2
    call = harness["planning"][-1]
    assert call["design"] == design and call["current"] == current
    assert call["result"]["status"] == "READY"
    assert backend.state["context"]["base_current"] == current
    assert backend.state["current"] == current
    assert [step["after"] for step in backend.state["context"]["plan"]["steps"]] == [NEXT]
    assert backend.state["context"]["plan"]["base_current_revision"] == current["current_revision"]
    assert len(harness["driver"].calls) == 3
    checkpoint(harness, "actual A Revised" if revised else "actual A partial Remaining")


def test_b_closed_duplicate_reverse_results_keep_original_identity(tmp_path):
    harness = connected(tmp_path, blocks=[YELLOW, UPPER, {**YELLOW, "layer": 3}])
    backend, driver = harness["backend"], harness["driver"]
    first = finish_transfer(harness)
    bundles = B.sequence_examples()["bundles_in_start_order"]
    # check A를 촬영 묶음 시작 시 발급된 ID로 연결. A/1 먼저 완료, A/0는 지연된 채 보관.
    for bundle in bundles[:2]:
        bundle["vision_result"]["check_id"] = first
        bundle["vision_diagnostics"]["check_id"] = first
    assert deliver(harness, bundles[1])
    assert len(backend.state["context"]["confirmed_steps"]) == 1
    second = finish_transfer(harness)
    for bundle in bundles[2:]:
        replacement = B.examples(second, bundle["vision_result"]["observation_seq"])[3]
        bundle.update(replacement)
    assert deliver(harness, bundles[2])  # check B/0 resets and is accepted (target unreadable).
    assert backend.state["active_check"]["last_observation_seq"] == 0
    assert not deliver(harness, bundles[0])  # late A/0 is never re-tagged B.
    assert deliver(harness, bundles[3])
    before = deepcopy(backend.state)
    assert not deliver(harness, bundles[3])
    assert not deliver(harness, bundles[2])
    assert backend.state == before and len(driver.calls) == 6
    assert harness["received"][-4]["input"]["check_id"] == first
    assert sum(row["event"] == "STEP_CONFIRMED" for row in events(harness)) == 1
    checkpoint(harness, "A1 B0 lateA0 B1 duplicateB1 reverseB0")


def test_place_reverse_duplicate_and_old_check_do_not_dispatch(tmp_path):
    harness = connected(tmp_path)
    backend, driver = harness["backend"], harness["driver"]
    check = backend.state["place_check"]["check_id"]
    assert deliver(harness, B.examples(check, 1)[0], place="OCCUPIED", assembly=False)
    before = deepcopy(backend.state)
    assert not deliver(harness, B.examples(check, 0)[0], place="EMPTY", assembly=False)
    assert not deliver(harness, B.examples(check, 1)[0], place="EMPTY", assembly=False)
    assert backend.state == before and not driver.calls
    assert deliver(harness, B.examples(check, 2)[0], place="EMPTY", assembly=False)
    assert len(driver.calls) == 1
    assert not deliver(harness, B.examples(check, 3)[0], place="EMPTY", assembly=False)
    assert len(driver.calls) == 1
    checkpoint(harness, "place sequence 1 occupied, old 0 and duplicate 1, fresh 2, closed 3")


@pytest.mark.parametrize("status", ["NEEDS_CORRECTION", "INVALID"])
def test_actual_a_errors_hold_before_robot_dispatch(tmp_path, status):
    current = dict(current_revision=1, blocks=[B.block("blue")]) if status == "NEEDS_CORRECTION" else None
    blocks = [YELLOW] if current else [{**YELLOW, "layer": 6}]
    harness = connected(tmp_path, blocks=blocks, current=current)
    result = harness["planning"][0]["result"]
    assert result["status"] == status and result["plan"] is None and result["errors"]
    assert harness["backend"].state["context"] is None and not harness["driver"].calls
    assert checkpoint(harness, status)["notice"]["required_action"]


def test_three_steps_only_observed_confirmation_completes_job(tmp_path):
    harness = connected(tmp_path, blocks=[YELLOW, UPPER, NEXT])
    backend, driver = harness["backend"], harness["driver"]
    for index in range(3):
        target = backend._next_step()["after"]
        check = finish_transfer(harness)
        assert len(backend.state["context"]["confirmed_steps"]) == index
        assert make_snapshot(backend.state)["workflow_status"] != "COMPLETE"
        if target == YELLOW:
            case = stored_case("normal_match", check)
        elif target == UPPER:
            case = stored_case("lower_layer_only_occluded", check)
        else:
            # 추가 위치의 목표는 D 작성 합성 프레임. B 제공 전달 함수는 실제로 거친다.
            case = dict(vision_result=dict(check_id=check, observation_seq=0, status="OK",
                visible_blocks=backend.state["current"]["blocks"] + [target],
                verified_regions=[B.region(layer=1), B.region(layer=2)], reason=None))
        assert deliver(harness, case)
        snapshot = checkpoint(harness, f"observed Step {index + 1}")
        assert snapshot["progress"] == dict(completed=index + 1, total=3)
    assert snapshot["workflow_status"] == "COMPLETE"
    assert len(driver.calls) == 9
    assert sum(row["event"] == "STEP_CONFIRMED" for row in events(harness)) == 3
    assert sum(row["event"] == "JOB_COMPLETED" for row in events(harness)) == 1
    assert not deliver(harness, case)
    assert backend.state["current"]["current_revision"] == 3
