from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.contracts import validate_plan_result
from app.jsonl_log import JsonlLog
from app.snapshot import make_snapshot
from test_backend import FIXTURES, started, stop_confirmed
from test_replan import mismatch, intent, remaining, revised


ROOT = Path(__file__).resolve().parents[2]
RESULTS = json.loads((ROOT / "interfaces/fixtures/planner_results.json").read_text())


@pytest.mark.parametrize("name", RESULTS)
def test_result_contract_and_schema_preserve_diagnostics(name):
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    Draft202012Validator(schema).validate(RESULTS[name])
    output = validate_plan_result(RESULTS[name])
    assert output == RESULTS[name]
    output["errors"].append({"reason": "mutation", "block": None})
    assert output != RESULTS[name]


@pytest.mark.parametrize("change", ["missing_errors", "ready_errors", "null_ready_plan",
                                    "failure_plan", "empty_failure", "empty_reason", "bad_block", "legacy"])
def test_malformed_results_hold_without_delivery(change):
    backend, ports = started()
    value = deepcopy(RESULTS["invalid" if change in ("failure_plan", "empty_failure", "empty_reason", "bad_block") else "initial_ready"])
    if change == "missing_errors": value.pop("errors")
    elif change == "ready_errors": value["errors"] = [{"reason": "unexpected", "block": None}]
    elif change == "null_ready_plan": value["plan"] = None
    elif change == "failure_plan": value["plan"] = FIXTURES["initial_plan"]
    elif change == "empty_failure": value["errors"] = []
    elif change == "empty_reason": value["errors"][0]["reason"] = ""
    elif change == "bad_block": value["errors"][0]["block"] = []
    else: value = dict(status="INVALID", reason="legacy")
    request = ports.calls("planner")[-1]["request_id"]
    assert backend.on_plan_result(request, value, design=FIXTURES["design"])
    assert backend.state["workflow_status"] == "HOLD"
    assert backend.state["context"] is None
    assert not ports.calls("robot.deliver")


def test_initial_ready_uses_same_result_entry_and_waits_for_fresh_place():
    backend, ports = started()
    request = ports.calls("planner")[-1]["request_id"]
    assert backend.on_plan_result(request, RESULTS["initial_ready"], design=FIXTURES["design"])
    assert backend.state["context"]["base_current"] == {"current_revision": 0, "blocks": []}
    assert not ports.calls("robot.deliver")
    assert backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    assert len(ports.calls("robot.deliver")) == 1
    assert not backend.on_plan_result(request, RESULTS["initial_ready"], design=FIXTURES["design"])


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize("status", ["NEEDS_CORRECTION", "INVALID"])
def test_initial_and_replan_failures_preserve_all_errors_in_hmi_and_log(tmp_path, initial, status):
    backend, ports = started() if initial else mismatch()
    if not initial: intent(backend, "KEEP")
    backend._record = JsonlLog(tmp_path)
    value = deepcopy(RESULTS["invalid"])
    value["status"] = status
    request = ports.calls("planner")[-1]["request_id"]
    deliveries = len(ports.calls("robot.deliver"))
    current = backend.state["current"]
    assert backend.on_plan_result(request, value, design=FIXTURES["design"] if initial else None)
    assert backend.state["workflow_status"] == ("WAIT_CORRECTION" if status == "NEEDS_CORRECTION" else "HOLD")
    assert backend.state["current"] == current
    assert len(ports.calls("robot.deliver")) == deliveries
    notice = make_snapshot(backend.state)["notice"]
    assert all(error["reason"] in notice["required_action"] for error in value["errors"])
    records = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    result = next(record for record in records if record["event"] == "PLAN_RESULT")
    assert result["request_id"] == request and result["result"] == value
    assert not backend.on_plan_result(request, value)


@pytest.mark.parametrize("field", ["design_version", "base_current_revision"])
def test_initial_ready_wrong_basis_does_not_adopt(field):
    backend, ports = started()
    value = deepcopy(RESULTS["initial_ready"])
    value["plan"][field] += 1
    assert backend.on_plan_result(ports.calls("planner")[-1]["request_id"], value, design=FIXTURES["design"])
    assert backend.state["context"] is None and backend.state["workflow_status"] == "HOLD"
    assert not ports.calls("robot.deliver")


def test_stopped_initial_request_result_is_ignored():
    backend, ports = started()
    old = ports.calls("planner")[-1]["request_id"]
    stop_confirmed(backend)
    assert not backend.on_plan_result(old, RESULTS["initial_ready"], design=FIXTURES["design"])
    assert backend.state["context"] is None and backend.state["workflow_status"] == "STOPPED"


def test_missing_initial_design_is_not_invented():
    backend, ports = started()
    assert backend.on_plan_result(ports.calls("planner")[-1]["request_id"], RESULTS["initial_ready"])
    assert backend.state["context"] is None and backend.state["workflow_status"] == "HOLD"


def test_initial_correction_observation_has_no_adopted_plan():
    backend, ports = started()
    request = ports.calls("planner")[-1]["request_id"]
    backend.on_plan_result(request, RESULTS["needs_correction"], design=FIXTURES["design"])
    command = dict(command="CONTINUE_AFTER_CORRECTION", job_id=backend.state["job_id"],
                   request_id=backend.state["correction_request"]["request_id"])
    assert backend.command(command)["accepted"]
    assert backend.state["workflow_status"] == "HOLD"
    assert backend.state["reason"] == "WAIT_CORRECTION_OBSERVATION"
    assert backend.state["current_check"]["plan_id"] is None
    assert backend.state["current_check"]["step_id"] is None
    assert not ports.calls("robot.deliver")


def test_success_after_correction_clears_old_planner_diagnostics():
    backend, ports = mismatch()
    intent(backend, "KEEP")
    request = ports.calls("planner")[-1]["request_id"]
    backend.on_plan_result(request, RESULTS["needs_correction"])
    # 새 목표 수신을 Fixture로 독립 검증한다. A 알고리즘은 대신 구현하지 않는다.
    from app.replan import begin_replan
    begin_replan(backend, revised(backend))
    request = ports.calls("planner")[-1]["request_id"]
    backend.on_plan_result(request, remaining(backend))
    assert backend.state["planner_errors"] == []
