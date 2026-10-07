from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path

import pytest

from app.assembly_attempt import SOURCES, update_attempt_evidence


FIXTURE = json.loads((Path(__file__).resolve().parents[2] /
                     "interfaces/fixtures/assembly_evidence.json").read_text())["attempt_collection"]
ACTIVE = {source: {**FIXTURE["common_context"], **settings}
          for source, settings in FIXTURE["sources"].items()}
LIMITS = FIXTURE["max_age"]


def event(source, *, active=ACTIVE, stamp=100.0, sequence=0, valid=True, value=None):
    metadata = {key: value for key, value in active[source].items() if key != "opened_at"}
    metadata.update(stamp=stamp, sequence=sequence, valid=valid)
    return dict(source=source, metadata=metadata,
                value=FIXTURE["positive_values"][source] if value is None else value)


def update(state=None, *, active=ACTIVE, now=100.0, sample=None):
    return update_attempt_evidence(state, active, now=now, max_age=LIMITS, event=sample)


def complete_attempt():
    result = update()
    for source in SOURCES:
        result = update(result["state"], sample=event(source))
    assert result["decision"]["decision"] == "ASSEMBLED"
    return result["state"]


@pytest.mark.parametrize("order", list(permutations(SOURCES)))
def test_fresh_evidence_completes_only_after_all_sources_arrive(order):
    result = update()
    for index, source in enumerate(order):
        result = update(result["state"], sample=event(source))
        assert result["event_result"]["accepted"]
        assert (result["decision"]["decision"] == "ASSEMBLED") is (index == 3)
    assert result["decision"]["verification_evidence"] == "SENSOR_VERIFIED"


def test_tick_expires_cached_success_and_duplicate_cannot_revive_it():
    expired = update(complete_attempt(), now=103.0)
    assert expired["decision"]["decision"] != "ASSEMBLED"
    assert expired["state"]["records"]["contact_state"] is None
    assert expired["discarded"]["contact_state"] == "STALE_EVIDENCE"
    duplicate = update(expired["state"], now=103.0,
                       sample=event("contact_state", stamp=103.0, sequence=0))
    assert duplicate["event_result"] == {"accepted": False, "reason": "STALE_SEQUENCE"}
    assert duplicate["state"]["records"]["contact_state"] is None


def test_fresh_vision_and_safety_cannot_reuse_expired_contact():
    result = update(complete_attempt(), now=103.0)
    for source in ("motion_permitted", "vision_verdict"):
        result = update(result["state"], now=103.0,
                        sample=event(source, stamp=103.0, sequence=1))
    assert result["decision"] == {"decision": "HOLD", "reason": "WAIT_CONTACT_EVIDENCE",
                                  "verification_evidence": None}


def test_invalid_new_measurement_clears_success_and_consumes_sequence():
    invalid = update(complete_attempt(), sample=event("contact_state", sequence=2, valid=False))
    assert invalid["event_result"]["reason"] == "INVALID_EVIDENCE"
    assert invalid["state"]["records"]["contact_state"] is None
    assert invalid["state"]["seen_sequence"]["contact_state"] == 2
    late = update(invalid["state"], sample=event("contact_state", sequence=1))
    assert late["event_result"]["reason"] == "STALE_SEQUENCE"
    assert late["decision"]["decision"] != "ASSEMBLED"


def test_previous_attempt_result_cannot_destroy_current_success_or_advance_sequence():
    sample = event("vision_verdict", sequence=99)
    sample["metadata"]["attempt_id"] = "old-attempt"
    result = update(complete_attempt(), sample=sample)
    assert result["event_result"]["reason"] == "ATTEMPT_ID_MISMATCH"
    assert result["state"]["seen_sequence"]["vision_verdict"] == 0
    assert result["decision"]["decision"] == "ASSEMBLED"


def test_new_attempt_drops_all_old_evidence_and_latches():
    old = complete_attempt()
    old = update(old, sample=event("motion_permitted", sequence=1, value=False))["state"]
    active = {source: {**context, "attempt_id": "A02", "opened_at": 101.0}
              for source, context in ACTIVE.items()}
    result = update(old, active=active, now=101.0, sample=event("vision_verdict", stamp=101.0))
    assert result["event_result"]["reason"] == "ATTEMPT_ID_MISMATCH"
    assert all(record is None for record in result["state"]["records"].values())
    assert all(value is None for value in result["state"]["latched"].values())
    assert result["decision"]["reason"] == "SAFETY_UNKNOWN"
    for source in SOURCES:
        result = update(result["state"], active=active, now=101.0,
                        sample=event(source, active=active, stamp=101.0))
    assert result["decision"]["decision"] == "ASSEMBLED"


def test_new_vision_request_requires_new_frame_but_keeps_fresh_contact():
    active = deepcopy(ACTIVE)
    active["vision_verdict"].update(request_id="V02", opened_at=101.0)
    result = update(complete_attempt(), active=active, now=101.0, sample=event("vision_verdict", stamp=101.0))
    assert result["event_result"]["reason"] == "REQUEST_ID_MISMATCH"
    assert result["state"]["records"]["vision_verdict"] is None
    assert result["state"]["records"]["contact_state"] is not None
    result = update(result["state"], active=active, now=101.0,
                    sample=event("vision_verdict", active=active, stamp=101.0))
    assert result["decision"]["decision"] == "ASSEMBLED"


def test_producer_restart_requires_new_epoch_evidence():
    active = deepcopy(ACTIVE)
    active["contact_state"].update(source_epoch="FT02", opened_at=101.0)
    result = update(complete_attempt(), active=active, now=101.0, sample=event("contact_state", stamp=101.0))
    assert result["event_result"]["reason"] == "SOURCE_EPOCH_MISMATCH"
    assert result["decision"]["decision"] != "ASSEMBLED"
    result = update(result["state"], active=active, now=101.0,
                    sample=event("contact_state", active=active, stamp=101.0))
    assert result["decision"]["decision"] == "ASSEMBLED"


@pytest.mark.parametrize("source,value", [("execution_result", "FAILED"), ("execution_result", "TIMED_OUT"),
    ("execution_result", "CANCELED"), ("contact_state", "JAMMED"), ("vision_verdict", "FAIL"),
    ("motion_permitted", False)])
def test_known_failure_or_stop_cannot_be_overwritten_by_later_success(source, value):
    failed = update(complete_attempt(), sample=event(source, sequence=1, value=value))
    result = update(failed["state"], sample=event(source, sequence=2))
    assert result["decision"]["decision"] != "ASSEMBLED"
    assert result["state"]["latched"][source] == value


def test_known_safety_stop_survives_expiration_and_fresh_normal_snapshot():
    stopped = update(complete_attempt(), sample=event("motion_permitted", sequence=1, value=False))
    result = update(stopped["state"], now=103.0, sample=event("motion_permitted", stamp=103.0, sequence=2))
    assert result["decision"]["decision"] == "SAFE_STOP"


def test_expired_known_jam_still_blocks_completion_after_new_safe_snapshot():
    failed = update(complete_attempt(), sample=event("contact_state", sequence=1, value="JAMMED"))
    result = update(failed["state"], now=103.0, sample=event("motion_permitted", stamp=103.0, sequence=1))
    assert result["state"]["records"]["contact_state"] is None
    assert result["decision"]["decision"] == "RECOVERY_REQUIRED"
    assert result["decision"]["reason"] == "JAMMED"


@pytest.mark.parametrize("source", ["contact_state", "vision_verdict"])
def test_unknown_evidence_requests_human_verification_without_false_completion(source):
    result = update(complete_attempt(), sample=event(source, sequence=1, value="UNKNOWN"))
    assert result["decision"]["decision"] == "REQUEST_HUMAN_VERIFICATION"
    assert result["decision"]["verification_evidence"] is None


def test_failure_after_cancel_is_reported_as_failure():
    canceled = update(complete_attempt(), sample=event("execution_result", sequence=1, value="CANCELED"))
    failed = update(canceled["state"], sample=event("execution_result", sequence=2, value="FAILED"))
    assert failed["decision"]["reason"] == "EXECUTION_FAILED"


@pytest.mark.parametrize("field,value", [("calibration_id", "C02"), ("basis_world_revision", 6)])
def test_changed_basis_or_calibration_closes_attempt_even_if_context_is_reverted(field, value):
    active = {source: {**context, field: value} for source, context in ACTIVE.items()}
    changed = update(complete_attempt(), active=active)
    assert changed["decision"]["reason"] == "ATTEMPT_CONTEXT_CHANGED"
    assert all(record is None for record in changed["state"]["records"].values())
    reverted = update(changed["state"])
    assert reverted["decision"]["reason"] == "ATTEMPT_CONTEXT_CHANGED"


def test_clock_rewind_after_opening_invalidates_attempt_until_new_attempt():
    state = update(complete_attempt(), now=101.5)["state"]
    reset = update(state, now=101.0)
    assert reset["decision"]["reason"] == "CLOCK_RESET"
    assert all(record is None for record in reset["state"]["records"].values())
    assert update(reset["state"], now=101.5)["decision"]["reason"] == "CLOCK_RESET"


def test_higher_sequence_with_older_capture_cannot_replace_current_evidence():
    state = update(complete_attempt(), now=101.0,
                   sample=event("vision_verdict", stamp=101.0, sequence=1))["state"]
    result = update(state, now=101.0, sample=event("vision_verdict", stamp=100.5, sequence=2))
    assert result["event_result"]["reason"] == "OUT_OF_ORDER_STAMP"
    assert result["state"]["seen_sequence"]["vision_verdict"] == 1
    assert result["decision"]["decision"] == "ASSEMBLED"


def test_inputs_are_not_mutated_and_cached_event_is_copied():
    state, active, sample = complete_attempt(), deepcopy(ACTIVE), event("contact_state", sequence=1)
    original = deepcopy((state, active, sample))
    result = update(state, active=active, sample=sample)
    assert (state, active, sample) == original
    sample["metadata"]["valid"] = False
    assert result["state"]["records"]["contact_state"]["metadata"]["valid"] is True


@pytest.mark.parametrize("target,field,value", [("context", "attempt_id", "A02"),
    ("context", "request_id", None), ("limits", "contact_state", 0),
    ("limits", "vision_verdict", True), ("limits", "motion_permitted", float("nan"))])
def test_inconsistent_context_or_bad_profile_is_rejected(target, field, value):
    active, limits = deepcopy(ACTIVE), deepcopy(LIMITS)
    if target == "context":
        active["vision_verdict"][field] = value
    else:
        limits[field] = value
    with pytest.raises(ValueError, match=field if target == "context" else "max_age"):
        update_attempt_evidence(None, active, now=100.0, max_age=limits)


def test_changing_frozen_window_without_new_request_or_epoch_is_rejected():
    active = deepcopy(ACTIVE)
    active["vision_verdict"]["opened_at"] = 99.0
    with pytest.raises(ValueError, match="opened_at"):
        update(complete_attempt(), active=active)


@pytest.mark.parametrize("source,value", [("contact_state", "SNAPPED"), ("vision_verdict", "OK"),
                                         ("motion_permitted", 1), ("unknown", "PASS")])
def test_bad_event_is_rejected_without_altering_caller_state(source, value):
    state = complete_attempt()
    original = deepcopy(state)
    sample = event("vision_verdict")
    sample.update(source=source, value=value)
    with pytest.raises(ValueError):
        update(state, sample=sample)
    assert state == original
