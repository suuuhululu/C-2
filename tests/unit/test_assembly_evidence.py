from copy import deepcopy
from itertools import product
import json
from pathlib import Path

import pytest

from app.assembly_evidence import check_evidence_context, evaluate_assembly_evidence


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "interfaces/fixtures/assembly_evidence.json").read_text())
SCHEMA = json.loads((ROOT / "interfaces/schemas/assembly_evidence.schema.json").read_text())


@pytest.mark.parametrize("case", FIXTURES["valid"], ids=lambda case: case["name"])
def test_evidence_combinations(case):
    payload = {**FIXTURES["base_input"], **case["changes"]}
    original = deepcopy(payload)
    assert evaluate_assembly_evidence(**payload) == {
        key: case[key] for key in ("decision", "reason", "verification_evidence")
    }
    assert payload == original


@pytest.mark.parametrize("case", FIXTURES["invalid"],
                         ids=lambda case: f"{case['field']}={case['value']!r}")
def test_invalid_input_is_rejected_without_normalization(case):
    payload = {**FIXTURES["base_input"], case["field"]: case["value"]}
    with pytest.raises(ValueError, match=case["field"]):
        evaluate_assembly_evidence(**payload)


@pytest.mark.parametrize("field", SCHEMA["$defs"]["input"]["required"])
def test_missing_input_is_not_given_a_success_default(field):
    payload = dict(FIXTURES["base_input"])
    del payload[field]
    with pytest.raises(TypeError, match=field):
        evaluate_assembly_evidence(**payload)


def test_unexpected_input_is_rejected():
    with pytest.raises(TypeError, match="human_response"):
        evaluate_assembly_evidence(**FIXTURES["base_input"], human_response="POSITIVE")


def test_all_declared_combinations_preserve_completion_and_safety_invariants():
    fields = SCHEMA["$defs"]["input"]["required"]
    properties = SCHEMA["$defs"]["input"]["properties"]
    values = [properties[field]["enum"] for field in fields[:3]] + [[None, False, True]]
    output = SCHEMA["$defs"]["output"]
    for combination in product(*values):
        payload = dict(zip(fields, combination))
        result = evaluate_assembly_evidence(**payload)
        assert set(result) == set(output["required"])
        assert result["decision"] in output["properties"]["decision"]["enum"]
        assert isinstance(result["reason"], str) and result["reason"]
        assert result["verification_evidence"] in output["properties"]["verification_evidence"]["enum"]
        if payload["motion_permitted"] is False:
            assert result["decision"] == "SAFE_STOP"
        if payload["motion_permitted"] is None:
            assert result["decision"] == "HOLD"
        if result["decision"] == "ASSEMBLED":
            assert payload == FIXTURES["base_input"]
            assert result["verification_evidence"] == "SENSOR_VERIFIED"
        else:
            assert result["verification_evidence"] is None


GUARD = FIXTURES["context_guard"]


@pytest.mark.parametrize("case", GUARD["cases"], ids=lambda case: case["name"])
def test_context_and_capture_freshness(case):
    active = {**GUARD["active"], **case.get("active", {})}
    evidence = {**GUARD["evidence"], **case.get("evidence", {})}
    runtime = {**GUARD["runtime"], **case.get("runtime", {})}
    original = deepcopy((active, evidence, runtime))
    assert check_evidence_context(active, evidence, **runtime) == {
        "accepted": case["accepted"], "reason": case["reason"]
    }
    assert (active, evidence, runtime) == original


@pytest.mark.parametrize("target,field,value", [
    ("active", "attempt_id", ""), ("evidence", "request_id", 1),
    ("evidence", "sequence", True), ("evidence", "sequence", -1),
    ("evidence", "valid", 1), ("evidence", "basis_world_revision", True),
    ("evidence", "stamp", float("nan")), ("evidence", "stamp", float("inf")),
    ("evidence", "stamp", True), ("active", "opened_at", -1),
    ("runtime", "now", float("inf")), ("runtime", "now", "102"),
    ("runtime", "max_age", 0), ("runtime", "max_age", -1),
    ("runtime", "max_age", float("nan")), ("runtime", "max_age", True),
    ("runtime", "last_sequence", True), ("runtime", "last_sequence", -1),
])
def test_malformed_metadata_and_time_are_rejected(target, field, value):
    inputs = {name: deepcopy(GUARD[name]) for name in ("active", "evidence", "runtime")}
    inputs[target][field] = value
    with pytest.raises(ValueError, match=field):
        check_evidence_context(inputs["active"], inputs["evidence"], **inputs["runtime"])


@pytest.mark.parametrize("target,definition", [
    ("active", "active_evidence_context"), ("evidence", "evidence_metadata"),
])
def test_guard_requires_all_context_fields_and_rejects_extra_fields(target, definition):
    for field in SCHEMA["$defs"][definition]["required"]:
        inputs = {name: deepcopy(GUARD[name]) for name in ("active", "evidence")}
        del inputs[target][field]
        with pytest.raises(ValueError, match=field):
            check_evidence_context(**inputs, **GUARD["runtime"])
    inputs = {name: deepcopy(GUARD[name]) for name in ("active", "evidence")}
    inputs[target]["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected"):
        check_evidence_context(**inputs, **GUARD["runtime"])


def test_accepted_sequence_is_owned_by_caller_and_not_advanced_on_rejection():
    accepted = check_evidence_context(GUARD["active"], GUARD["evidence"], **GUARD["runtime"])
    assert accepted["accepted"]
    runtime = {**GUARD["runtime"], "last_sequence": GUARD["evidence"]["sequence"]}
    duplicate = check_evidence_context(GUARD["active"], GUARD["evidence"], **runtime)
    assert duplicate == {"accepted": False, "reason": "STALE_SEQUENCE"}
    assert runtime["last_sequence"] == 4


def test_missing_age_limit_is_not_silently_defaulted():
    with pytest.raises(TypeError, match="max_age"):
        check_evidence_context(GUARD["active"], GUARD["evidence"], now=102.0)


def test_missing_sequence_history_is_not_silently_treated_as_first_observation():
    with pytest.raises(TypeError, match="last_sequence"):
        check_evidence_context(GUARD["active"], GUARD["evidence"], now=102.0, max_age=2.0)
