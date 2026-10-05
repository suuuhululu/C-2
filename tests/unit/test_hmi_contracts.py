from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.hmi_contracts import validate_hmi_command, validate_hmi_snapshot


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "interfaces/fixtures/hmi.json").read_text())
COMMON = json.loads((ROOT / "interfaces/fixtures/day4.json").read_text())


def replace(payload, path, value):
    result = deepcopy(payload)
    item = result
    for field in path[:-1]:
        item = item[field]
    item[path[-1]] = value
    return result


@pytest.mark.parametrize("name", FIXTURES["snapshots"])
def test_snapshot_fixtures_are_preserved_and_nested_data_are_detached(name):
    payload = deepcopy(FIXTURES["snapshots"][name])
    result = validate_hmi_snapshot(payload)
    assert result == payload and result is not payload
    payload["monitor"]["supply"].clear()
    payload["actions"]["stop"]["enabled"] = None
    assert result == FIXTURES["snapshots"][name]


@pytest.mark.parametrize("name", FIXTURES["commands"])
def test_command_fixtures_are_preserved_without_execution(name):
    payload = deepcopy(FIXTURES["commands"][name])
    assert validate_hmi_command(payload) == payload
    assert validate_hmi_command(payload) is not payload


@pytest.mark.parametrize("name", FIXTURES["invalid_snapshots"])
def test_saved_invalid_snapshots_are_rejected(name):
    with pytest.raises(ValueError):
        validate_hmi_snapshot(FIXTURES["invalid_snapshots"][name])


@pytest.mark.parametrize("name", FIXTURES["invalid_commands"])
def test_saved_invalid_commands_are_rejected(name):
    with pytest.raises(ValueError):
        validate_hmi_command(FIXTURES["invalid_commands"][name])


@pytest.mark.parametrize("name,enabled", [
    ("idle", ["start"]), ("waiting", ["stop"]), ("complete", ["start"]),
    ("stopped", ["resume"]), ("stop_pending", ["stop"]),
    ("unobservable", ["stop"]), ("mismatch", ["stop"]), ("robot_error", ["stop"]),
])
def test_basic_buttons_follow_macro_state_without_vision_or_place_restrictions(name, enabled):
    payload = deepcopy(FIXTURES["snapshots"][name])
    payload["monitor"]["place_status"] = "UNOBSERVABLE"
    result = validate_hmi_snapshot(payload)
    assert [key for key in ("start", "stop", "resume") if result["actions"][key]["enabled"]] == enabled
    for key in ("start", "stop", "resume"):
        wrong = replace(payload, ("actions", key, "enabled"), not payload["actions"][key]["enabled"])
        with pytest.raises(ValueError, match="basic button table"):
            validate_hmi_snapshot(wrong)


@pytest.mark.parametrize("path,value,reason", [
    (("workflow_status",), "UNKNOWN", "workflow_status"),
    (("progress", "completed"), True, "completed"),
    (("progress", "completed"), 4, "completed"),
    (("progress", "total"), -1, "total"),
    (("progress", "total"), 3.0, "total"),
    (("monitor", "robot", "mode"), None, "mode"),
    (("monitor", "robot", "status"), "SUCCESS", "robot.status"),
    (("monitor", "place_status"), "SAFE", "place_status"),
    (("monitor", "observation", "status"), "MATCH", "observation.status"),
    (("monitor", "observation", "observation_seq"), True, "observation_seq"),
    (("monitor", "observation", "observation_seq"), 1, "capture sequence"),
    (("monitor", "observation", "status"), "OK", "capture identity"),
    (("monitor", "supply", 0, "next_slot"), 0, "next_slot"),
    (("monitor", "supply", 0, "next_slot"), True, "next_slot"),
    (("monitor", "supply", 0, "needs_refill"), 0, "needs_refill"),
    (("monitor", "supply", 0, "color"), "red", "color"),
    (("monitor", "supply"), [], "four supply columns"),
    (("actions", "job_id"), None, "job_id"),
    (("actions", "stop", "visible"), False, "hidden button"),
    (("actions", "stop", "enabled"), 1, "boolean"),
    (("notice", "question"), "", "question"),
    (("design",), None, "adopted Design"),
    (("step", "plan_id"), None, "plan_id"),
    (("step", "target", "orientation_deg"), 180, "orientation_deg"),
    (("step", "comparison"), "MATCH", "missing observation"),
])
def test_malformed_snapshot_is_rejected_with_reason_without_mutating_input(path, value, reason):
    payload = replace(FIXTURES["snapshots"]["waiting"], path, value)
    before = deepcopy(payload)
    with pytest.raises(ValueError, match=reason):
        validate_hmi_snapshot(payload)
    assert payload == before


@pytest.mark.parametrize("consumer,payload", [
    (validate_hmi_snapshot, FIXTURES["snapshots"]["waiting"]),
    *[(validate_hmi_command, payload) for payload in FIXTURES["commands"].values()],
])
def test_required_fields_and_unknown_fields_are_not_silently_dropped(consumer, payload):
    for field in payload:
        invalid = deepcopy(payload)
        del invalid[field]
        with pytest.raises(ValueError, match=field):
            consumer(invalid)
    with pytest.raises(ValueError, match="unsupported"):
        consumer({**payload, "hmi_version": 99})


@pytest.mark.parametrize("consumer", [validate_hmi_snapshot, validate_hmi_command])
@pytest.mark.parametrize("value", [None, [], "{}", 1])
def test_non_object_is_not_converted_to_an_idle_screen_or_start_request(consumer, value):
    with pytest.raises(ValueError):
        consumer(value)


def test_missing_observation_empty_verified_area_and_occlusion_remain_distinct():
    missing = validate_hmi_snapshot(FIXTURES["snapshots"]["waiting"])
    empty = validate_hmi_snapshot(FIXTURES["snapshots"]["empty"])
    occluded = validate_hmi_snapshot(FIXTURES["snapshots"]["unobservable"])
    assert missing["step"]["observed"] is None
    assert empty["step"]["observed"] == COMMON["observed_empty"]
    assert empty["step"]["observed"]["verified_regions"] and empty["step"]["comparison"] == "MISMATCH"
    assert occluded["step"]["comparison"] == "UNOBSERVABLE"
    with pytest.raises(ValueError, match="observation status"):
        validate_hmi_snapshot(replace(occluded, ("step", "comparison"), "WAITING"))
    partial = validate_hmi_snapshot(FIXTURES["snapshots"]["partial"])
    assert partial["step"]["observed"] == COMMON["observed_partial"]
    assert partial["step"]["observed"]["status"] == "OK"
    assert partial["step"]["comparison"] == "UNOBSERVABLE"


def test_monitor_capture_identity_must_belong_to_displayed_step_observation():
    payload = FIXTURES["snapshots"]["mismatch"]
    for field, wrong in [("check_id", "closed-check"), ("observation_seq", 0), ("status", None)]:
        with pytest.raises(ValueError):
            validate_hmi_snapshot(replace(payload, ("monitor", "observation", field), wrong))


def test_exception_actions_are_linked_to_displayed_request_and_supply_column():
    for name, action in [("choice", "intent_choice"), ("correction", "correction_continue")]:
        payload = FIXTURES["snapshots"][name]
        for wrong in (None, "another-request"):
            with pytest.raises(ValueError, match="request_id"):
                validate_hmi_snapshot(replace(payload, ("actions", action, "request_id"), wrong))
    refill = validate_hmi_snapshot(FIXTURES["snapshots"]["refill"])
    assert refill["actions"]["supply_refill"] == [{"brick_type": "2x2x1", "color": "yellow", "visible": True, "enabled": True}]
    with pytest.raises(ValueError, match="refill-needed column"):
        validate_hmi_snapshot(replace(refill, ("actions", "supply_refill", 0, "color"), "blue"))
    duplicate = deepcopy(refill)
    duplicate["monitor"]["supply"][1] = deepcopy(duplicate["monitor"]["supply"][0])
    with pytest.raises(ValueError, match="duplicate supply column"):
        validate_hmi_snapshot(duplicate)
    duplicate = deepcopy(refill)
    duplicate["actions"]["supply_refill"].append(deepcopy(duplicate["actions"]["supply_refill"][0]))
    with pytest.raises(ValueError, match="duplicate supply column"):
        validate_hmi_snapshot(duplicate)
    choice = FIXTURES["snapshots"]["choice"]
    with pytest.raises(ValueError, match="displayed question"):
        validate_hmi_snapshot(replace(choice, ("notice", "question"), None))
    correction = {"visible": True, "enabled": True, "request_id": choice["notice"]["request_id"]}
    with pytest.raises(ValueError, match="both be displayed"):
        validate_hmi_snapshot(replace(choice, ("actions", "correction_continue"), correction))


@pytest.mark.parametrize("brick_type", ["2x2x1", "2x3x1"])
@pytest.mark.parametrize("color", ["yellow", "blue"])
def test_refill_command_identifies_one_column_without_resetting_slots(brick_type, color):
    command = {"command": "SUPPLY_REFILLED", "job_id": "J01", "brick_type": brick_type, "color": color}
    assert validate_hmi_command(command) == command
    with pytest.raises(ValueError, match="next_slot"):
        validate_hmi_command({**command, "next_slot": 1})


@pytest.mark.parametrize("slot", [None, 1, 6])
def test_unknown_or_boundary_slot_is_preserved_without_inventory_inference(slot):
    payload = replace(FIXTURES["snapshots"]["waiting"], ("monitor", "supply", 0, "next_slot"), slot)
    assert validate_hmi_snapshot(payload)["monitor"]["supply"][0]["next_slot"] == slot


@pytest.mark.parametrize("name,field", [("stop", "job_id"), ("resume", "job_id"), ("keep", "request_id"), ("correction", "request_id")])
@pytest.mark.parametrize("value", [None, "", True])
def test_command_identity_is_required_as_text(name, field, value):
    with pytest.raises(ValueError, match=field):
        validate_hmi_command({**FIXTURES["commands"][name], field: value})


def test_delivery_success_and_stop_request_are_not_assembly_or_stop_confirmation():
    waiting = validate_hmi_snapshot(FIXTURES["snapshots"]["waiting"])
    assert waiting["progress"] == {"completed": 2, "total": 3}
    assert waiting["step"]["comparison"] == "WAITING"
    pending = validate_hmi_snapshot(FIXTURES["snapshots"]["stop_pending"])
    assert pending["monitor"]["robot"]["status"] == "STOP_PENDING"
    assert not pending["actions"]["resume"]["enabled"]
    with pytest.raises(ValueError, match="not confirmed STOPPED"):
        validate_hmi_snapshot(replace(FIXTURES["snapshots"]["stopped"], ("monitor", "robot", "status"), "STOP_PENDING"))


def test_structural_acceptance_does_not_execute_commands_adopt_design_or_prove_freshness():
    payload = deepcopy(FIXTURES["snapshots"]["choice"])
    assert validate_hmi_command({"command": "STOP", "job_id": "old-job"})["job_id"] == "old-job"
    revise = validate_hmi_command(FIXTURES["commands"]["revise"])
    assert revise["choice"] == "REVISE" and payload == FIXTURES["snapshots"]["choice"]
    assert payload["design"] == COMMON["design"] and payload["progress"]["completed"] == 2
