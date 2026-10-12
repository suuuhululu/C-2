from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.contracts import (
    validate_block, validate_design, validate_observed, validate_plan, validate_step,
)


FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / "interfaces/fixtures/day4.json").read_text()
)
VALID = [
    (validate_design, "design"),
    *[(validate_plan, name) for name in ("initial_plan", "remaining_plan", "completed_plan")],
    *[(validate_observed, "observed_" + suffix)
      for suffix in ("match", "mismatch", "empty", "partial", "unobservable")],
]


@pytest.mark.parametrize("consumer,name", VALID)
def test_valid_inputs_preserve_values_and_do_not_share_nested_data(consumer, name):
    payload = deepcopy(FIXTURES[name])
    result = consumer(payload)
    assert result == payload and result is not payload
    if "steps" in payload:
        payload["steps"].clear()
    elif "blocks" in payload:
        payload["blocks"][0]["color"] = "blue"
    else:
        payload["verified_regions"].append({"unexpected": "mutation"})
    assert result == FIXTURES[name]


@pytest.mark.parametrize("brick_type,angle", [("2x2x1", 0), ("2x3x1", 0), ("2x3x1", 90)])
@pytest.mark.parametrize("color", ["yellow", "blue"])
@pytest.mark.parametrize("layer", range(1, 6))
def test_supported_blocks_and_field_boundaries(brick_type, angle, color, layer):
    block = dict(brick_type=brick_type, color=color, x=0, y=23, layer=layer, orientation_deg=angle)
    assert validate_block(block) == block


@pytest.mark.parametrize("field,value", [
    ("brick_type", "2x4x1"), ("color", "red"), ("x", -1), ("y", 24),
    ("x", True), ("y", "5"), ("x", 3.5), ("layer", 0), ("layer", 6),
    ("orientation_deg", 90), ("orientation_deg", 180), ("orientation_deg", False),
])
def test_invalid_block_is_rejected_without_normalization(field, value):
    block = {**FIXTURES["design"]["blocks"][0], field: value}
    original = deepcopy(block)
    with pytest.raises(ValueError, match=field):
        validate_block(block)
    assert block == original


REQUIRED = [
    (validate_block, FIXTURES["design"]["blocks"][0]),
    (validate_design, FIXTURES["design"]),
    (validate_plan, FIXTURES["initial_plan"]),
    (validate_step, FIXTURES["initial_plan"]["steps"][0]),
    (validate_observed, FIXTURES["observed_match"]),
]


@pytest.mark.parametrize("consumer,payload,field", [
    (consumer, payload, field) for consumer, payload in REQUIRED for field in payload
])
def test_missing_required_field_is_named(consumer, payload, field):
    invalid = deepcopy(payload)
    del invalid[field]
    with pytest.raises(ValueError, match=field):
        consumer(invalid)


@pytest.mark.parametrize("consumer,payload", REQUIRED)
@pytest.mark.parametrize("malformed", [None, [], "not an object", 1])
def test_non_object_is_not_a_normal_empty_result(consumer, payload, malformed):
    with pytest.raises(ValueError, match="expected object"):
        consumer(malformed)


@pytest.mark.parametrize("consumer,payload", REQUIRED)
def test_unknown_fields_are_rejected_without_silently_discarding_them(consumer, payload):
    invalid = {**deepcopy(payload), "observation_id": "obsolete", 1: "non-string key"}
    with pytest.raises(ValueError, match="unsupported"):
        consumer(invalid)


@pytest.mark.parametrize("consumer,name,reason", [
    (validate_plan, "invalid_obsolete_design_id", "design_id"),
    (validate_observed, "invalid_legacy_observed", "check_id"),
    (validate_design, "invalid_layer", "layer"),
])
def test_saved_failure_fixtures(consumer, name, reason):
    with pytest.raises(ValueError, match=reason):
        consumer(FIXTURES[name])


@pytest.mark.parametrize("field,value", [
    ("operation", "MOVE"), ("operation", "REMOVE"), ("before", {}),
    ("after", None), ("requires_delivery", False), ("requires_delivery", 1),
    ("prerequisites", "S01"), ("prerequisites", ["S01", "S01"]),
])
def test_step_rejects_unsupported_effects_and_malformed_references(field, value):
    step = {**FIXTURES["initial_plan"]["steps"][0], field: value}
    with pytest.raises(ValueError):
        validate_step(step)


@pytest.mark.parametrize("reference", ["missing", "S03", "S02"])
def test_prerequisites_must_reference_earlier_steps_in_same_plan(reference):
    plan = deepcopy(FIXTURES["initial_plan"])
    plan["steps"][1]["prerequisites"] = [reference]
    with pytest.raises(ValueError, match="prerequisites"):
        validate_plan(plan)


def test_duplicate_step_identifier_is_rejected():
    plan = deepcopy(FIXTURES["initial_plan"])
    plan["steps"][1]["step_id"] = "S01"
    with pytest.raises(ValueError, match="step_id"):
        validate_plan(plan)


@pytest.mark.parametrize("consumer,name,field,value", [
    (validate_design, "design", "design_version", 0),
    (validate_design, "design", "blocks", None),
    (validate_plan, "initial_plan", "plan_id", ""),
    (validate_plan, "initial_plan", "base_current_revision", -1),
    (validate_plan, "initial_plan", "design_version", True),
    (validate_plan, "initial_plan", "steps", {}),
    (validate_observed, "observed_match", "check_id", ""),
    (validate_observed, "observed_match", "observation_seq", -1),
    (validate_observed, "observed_match", "observation_seq", True),
    (validate_observed, "observed_match", "status", "MATCH"),
    (validate_observed, "observed_match", "visible_blocks", None),
    (validate_observed, "observed_match", "verified_regions", None),
    (validate_observed, "observed_unobservable", "reason", None),
    (validate_observed, "observed_unobservable", "reason", ""),
])
def test_invalid_envelope_fields(consumer, name, field, value):
    payload = {**FIXTURES[name], field: value}
    with pytest.raises(ValueError, match=field):
        consumer(payload)


@pytest.mark.parametrize("field,value", [("width", 0), ("height", -1), ("x", 23), ("layer", 6)])
def test_invalid_verified_region_is_rejected(field, value):
    observed = deepcopy(FIXTURES["observed_match"])
    observed["verified_regions"][0][field] = value
    with pytest.raises(ValueError, match="verified_regions"):
        validate_observed(observed)


def test_required_region_field_and_nested_error_path():
    observed = deepcopy(FIXTURES["observed_match"])
    del observed["verified_regions"][0]["height"]
    with pytest.raises(ValueError, match=r"observed.verified_regions\[0\].*height"):
        validate_observed(observed)
    observed = deepcopy(FIXTURES["observed_match"])
    observed["visible_blocks"][0]["color"] = "red"
    with pytest.raises(ValueError, match=r"observed.visible_blocks\[0\].color"):
        validate_observed(observed)


def test_capture_sequence_zero_and_transport_id_are_not_rewritten():
    observed = {**FIXTURES["observed_match"], "check_id": "capture-token", "observation_seq": 0}
    assert validate_observed(observed) == observed


def test_consumer_validation_does_not_claim_planner_geometry_or_completion():
    # 기준 좌표가 범위 안이어도 footprint는 벗어날 수 있다. 전체 기하는 Planner 책임이다.
    plan = deepcopy(FIXTURES["initial_plan"])
    plan["steps"][2]["after"].update(x=23, layer=4)
    assert validate_plan(plan) == plan
    empty = validate_plan(FIXTURES["completed_plan"])
    assert empty["steps"] == [] and "completed" not in empty
    # OK의 빈 목록·색상 차이·부분 영역은 유효한 관측 형식이며 목표 일치를 뜻하지 않는다.
    for suffix in ("empty", "mismatch", "partial"):
        result = validate_observed(FIXTURES["observed_" + suffix])
        assert result["status"] == "OK" and "completed" not in result
