from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator, RefResolver, ValidationError
import pytest

from app.hmi_contracts import validate_hmi_snapshot


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "interfaces/fixtures/hmi_mvp.json").read_text())
SCHEMA = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
COMMON = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
RESOLVER = RefResolver.from_schema(SCHEMA, store={SCHEMA["$id"]: SCHEMA,
    COMMON["$id"]: COMMON, "https://c-2.invalid/schemas/day4.schema.json": COMMON})
VALIDATOR = Draft202012Validator(SCHEMA, resolver=RESOLVER)


@pytest.mark.parametrize("name", FIXTURES["snapshots"])
def test_synthetic_snapshots_validate_in_schema_and_consumer_without_mutation(name):
    payload = deepcopy(FIXTURES["snapshots"][name])
    before = deepcopy(payload)
    VALIDATOR.validate(payload)
    result = validate_hmi_snapshot(payload)
    assert payload == before == result
    assert result is not payload
    payload["current"]["blocks"].clear()
    assert result == before


@pytest.mark.parametrize("case", FIXTURES["invalid_cases"], ids=lambda c: c["name"])
def test_wrong_request_step_unsupported_method_and_false_completion_are_rejected(case):
    payload = deepcopy(FIXTURES["snapshots"][case["base"]])
    node = payload
    for key in case["path"][:-1]:
        node = node[key]
    node[case["path"][-1]] = case["value"]
    before = deepcopy(payload)
    with pytest.raises(ValueError, match=case["error"]):
        validate_hmi_snapshot(payload)
    if case["schema_rejected"]:
        with pytest.raises(ValidationError):
            VALIDATOR.validate(payload)
    assert payload == before


def test_preview_revision_does_not_replace_approved_design_current_or_progress():
    payload = FIXTURES["snapshots"]["draft_updated"]
    result = validate_hmi_snapshot(payload)
    assert result["design_preview"]["design"]["blocks"][-1]["color"] == "yellow"
    assert result["design"]["blocks"][-1]["color"] == "blue"
    assert result["progress"] == {"completed": 2, "total": 3}
    result["design_preview"]["design"]["blocks"].clear()
    assert payload["design_preview"]["design"]["blocks"]
    assert result["current"] == payload["current"]


def test_motion_support_ready_and_handover_do_not_confirm_placement():
    for name in ("robot_contact", "support_maintain", "handover_requested", "human_assembly"):
        result = validate_hmi_snapshot(FIXTURES["snapshots"][name])
        assert result["step"]["comparison"] == "WAITING"
        assert result["progress"]["completed"] == 2
        assert len(result["current"]["blocks"]) == 2
    ready = deepcopy(FIXTURES["snapshots"]["support_requested"])
    ready["assistance"]["phase"] = "READY"
    assert validate_hmi_snapshot(ready)["progress"]["completed"] == 2


def test_storage_and_web_failure_preserve_physical_completion_and_existing_actions():
    for name in ("saving", "storage_failed", "web_pending", "web_failed", "complete"):
        result = validate_hmi_snapshot(FIXTURES["snapshots"][name])
        assert result["workflow_status"] == "COMPLETE"
        assert result["completion"]["assembly"] == "MATCH"
        assert result["progress"] == {"completed": 3, "total": 3}
        assert result["current"] == FIXTURES["snapshots"]["complete"]["current"]
        assert not result["actions"]["resume"]["enabled"]


def test_existing_fake_and_real_gates_are_not_relaxed_by_display_extensions():
    legacy = json.loads((ROOT / "interfaces/fixtures/hmi.json").read_text())
    for payload in legacy["snapshots"].values():
        VALIDATOR.validate(payload)
        assert validate_hmi_snapshot(payload) == payload
    real = deepcopy(FIXTURES["snapshots"]["robot_contact"])
    real["monitor"]["robot"]["mode"] = "REAL"
    with pytest.raises(ValueError, match="single transfer"):
        validate_hmi_snapshot(real)
    with pytest.raises(ValidationError):
        VALIDATOR.validate(real)


@pytest.mark.parametrize("field", ("design_preview", "dialogue", "execution", "assistance", "completion"))
def test_present_extensions_require_objects_and_known_fields(field):
    source = next(s for s in FIXTURES["snapshots"].values() if field in s)
    for bad in (None, [], {**source[field], "approved": True}):
        payload = deepcopy(source)
        payload[field] = bad
        with pytest.raises(ValueError):
            validate_hmi_snapshot(payload)
        with pytest.raises(ValidationError):
            VALIDATOR.validate(payload)


def test_no_device_fixture_checker_is_reproducible_and_rejects_unknown_case():
    result = subprocess.run([sys.executable, "-m", "app.hmi_mvp_contracts"], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("PASS ") == len(FIXTURES["snapshots"])
    wrong = subprocess.run([sys.executable, "-m", "app.hmi_mvp_contracts", "--case", "unknown"],
                           cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert wrong.returncode == 2 and "invalid choice" in wrong.stderr


def test_schema_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_existing_qt_accepts_extensions_without_rendering_draft_as_approved(qapp):
    from app.qt_hmi import HmiWindow
    window = HmiWindow()
    try:
        for payload in FIXTURES["snapshots"].values():
            window.render_snapshot(payload)
            assert window._snapshot == payload
            assert window.design_board.blocks == (payload["design"]["blocks"] if payload["design"] else [])
    finally:
        window.close()
