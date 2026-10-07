from copy import deepcopy
import json

import pytest

from app.jsonl_log import JsonlLog
from test_assembly_completion import ACTIVE, DATA, TRIAL, begin, metadata, sample, verification


HUMAN = DATA["human_verification"]


def uncertain(source="vision_verdict", value="UNKNOWN", *, record=None):
    backend, ports = begin(record=record)
    for name in ACTIVE:
        backend.on_assembly_evidence(now=101.5, event=sample(name, value if name == source else None))
    return backend, ports


def open_request(backend, *, proof=None, now=101.5, session_closed=True):
    return backend.open_human_verification(now=now, verification=verification() if proof is None else proof,
        session_closed=session_closed, human_source_epoch=HUMAN["human_source_epoch"],
        timeout=HUMAN["timeout"], response_max_age=HUMAN["response_max_age"])


def opened(*, source="vision_verdict", value="UNKNOWN", record=None):
    backend, ports = uncertain(source, value, record=record)
    assert open_request(backend)["accepted"]
    return backend, ports


def response(backend, *, answer="POSITIVE", inspection="VISUAL_ONLY", stamp=101.75, sequence=0):
    request = backend.assembly_state["human_verification"]
    return dict(metadata=metadata(request["context"], stamp=stamp, sequence=sequence),
                answer=answer, source="HMI", inspection=inspection)


def reply(backend, *, answer="POSITIVE", inspection="VISUAL_ONLY", now=101.75,
          packet=None, physical=None, session_closed=True):
    physical = deepcopy(verification(1)["physical"]) if physical is None else physical
    physical["metadata"]["stamp"] = now
    return backend.on_human_verification_response(now=now,
        response=response(backend, answer=answer, inspection=inspection, stamp=now) if packet is None else packet,
        physical=physical, session_closed=session_closed)


@pytest.mark.parametrize("source", ["vision_verdict", "contact_state"])
def test_visual_positive_commits_once_without_rewriting_unknown(source):
    events = []
    backend, ports = opened(source=source, record=events.append)
    before = backend.state
    request = backend.assembly_state["human_verification"]
    assert request["type"] == "PERCEPTUAL_VERIFICATION"
    assert request["target"] == TRIAL["target"]
    assert request["reference"] == TRIAL["world"]["blocks"][0]
    assert backend.assembly_state["decision"]["reason"] == "WAIT_HUMAN_RESPONSE"
    result = reply(backend)
    assert result["accepted"] and result["committed"]
    state = backend.assembly_state
    assert state["world"] == TRIAL["observed_world"]
    assert state["completion"]["verification_evidence"] == "HUMAN_VERIFIED"
    assert state["completion"]["evidence"][source]["value"] == "UNKNOWN"
    assert state["completion"]["human_response"]["answer"] == "POSITIVE"
    assert state["human_verification"]["status"] == "CLOSED"
    assert backend.state == before and ports == []
    assert [event["event"] for event in events] == ["HUMAN_VERIFY_OPENED", "ASSEMBLY_COMMITTED"]
    old = deepcopy(state)
    assert not reply(backend)["accepted"]
    assert backend.assembly_state == old and len(events) == 2


def test_partial_observation_can_be_confirmed_as_human_evidence_only():
    backend, _ = uncertain(value="PASS")
    proof = verification()
    proof["observation"].update(complete=False, world=dict(world_revision=5, blocks=[]))
    assert open_request(backend, proof=proof)["accepted"]
    assert reply(backend)["committed"]
    assert backend.assembly_state["completion"]["verification_evidence"] == "HUMAN_VERIFIED"
    assert backend.assembly_state["completion"]["human_request"]["verification"]["observation"]["complete"] is False


@pytest.mark.parametrize("field", ["stopped", "execution_ended", "released", "at_observe"])
def test_request_requires_confirmed_physical_facts(field):
    backend, _ = uncertain()
    proof = verification()
    proof["physical"][field] = False
    assert not open_request(backend, proof=proof)["accepted"]
    assert backend.assembly_state["human_verification"] is None
    assert backend.assembly_state["completion"] is None


def test_support_session_must_be_closed_before_request_and_response():
    backend, _ = uncertain()
    assert not open_request(backend, session_closed=False)["accepted"]
    assert open_request(backend, proof=verification(1))["accepted"]
    result = reply(backend, physical=verification(2)["physical"], session_closed=False)
    assert not result["accepted"] and not result["committed"]
    assert backend.assembly_state["human_verification"]["status"] == "CLOSED"


@pytest.mark.parametrize("answer,inspection,decision,reason", [
    ("NEGATIVE", "VISUAL_ONLY", "RECOVERY_REQUIRED", "HUMAN_NEGATIVE"),
    ("POSITIVE", "PHYSICAL_CORRECTION", "HOLD", "PHYSICAL_CORRECTION_REQUIRED")])
def test_negative_or_physical_correction_closes_request_without_completion(answer, inspection, decision, reason):
    backend, ports = opened()
    assert reply(backend, answer=answer, inspection=inspection)["accepted"]
    state = backend.assembly_state
    assert state["decision"]["decision"] == decision and state["decision"]["reason"] == reason
    assert state["world"] == TRIAL["world"] and state["completion"] is None
    assert state["human_verification"]["status"] == "CLOSED" and ports == []
    backend.on_assembly_evidence(now=101.8)
    assert backend.assembly_state["decision"]["reason"] == reason
    assert not reply(backend, now=101.8)["accepted"]


@pytest.mark.parametrize("field,value", [("request_id", "old"), ("attempt_id", "old"),
    ("job_id", "old"), ("plan_id", "old"), ("step_id", "old"), ("calibration_id", "old"),
    ("source_epoch", "old"), ("basis_world_revision", 6), ("stamp", 101.4),
    ("stamp", 101.9), ("valid", False)])
def test_wrong_or_early_future_invalid_response_cannot_complete(field, value):
    backend, _ = opened()
    packet = response(backend)
    packet["metadata"][field] = value
    result = reply(backend, packet=packet)
    assert not result["accepted"] and not result["committed"]
    assert backend.assembly_state["completion"] is None


def test_unknown_consumes_sequence_but_keeps_request_open():
    backend, _ = opened()
    result = reply(backend, answer="UNKNOWN")
    assert not result["accepted"] and result["reason"] == "HUMAN_RESPONSE_UNKNOWN"
    assert backend.assembly_state["human_verification"]["status"] == "OPEN"
    assert reply(backend)["reason"] == "STALE_SEQUENCE"
    assert reply(backend, packet=response(backend, sequence=1), physical=verification(2)["physical"])["committed"]


@pytest.mark.parametrize("source,value", [("motion_permitted", False), ("vision_verdict", "FAIL"),
    ("contact_state", "JAMMED"), ("execution_result", "FAILED"), ("execution_result", "CANCELED")])
def test_failure_closes_request_and_late_positive_does_not_override_it(source, value):
    backend, _ = opened()
    old = response(backend)
    backend.on_assembly_evidence(now=101.6, event=sample(source, value, 1))
    assert backend.assembly_state["human_verification"]["status"] == "CLOSED"
    assert not reply(backend, packet=old)["committed"]
    assert backend.assembly_state["world"] == TRIAL["world"]


def test_new_frame_invalidates_old_request_even_when_value_is_still_unknown():
    backend, _ = opened()
    old = response(backend)
    backend.on_assembly_evidence(now=101.6, event=sample("vision_verdict", "UNKNOWN", 1))
    assert backend.assembly_state["human_verification"]["close_reason"] == "EVIDENCE_CHANGED"
    assert not reply(backend, packet=old)["accepted"]


@pytest.mark.parametrize("now,reason", [(102.5, "HUMAN_REQUEST_TIMED_OUT"), (100.9, "CLOCK_RESET"),
                                      (103.6, "HUMAN_REQUEST_TIMED_OUT")])
def test_tick_closes_expired_or_clock_invalid_request(now, reason):
    backend, _ = opened()
    backend.on_assembly_evidence(now=now)
    request = backend.assembly_state["human_verification"]
    assert request["status"] == "CLOSED" and request["close_reason"] == reason
    assert not reply(backend, now=max(now,101.75))["committed"]


def test_sensor_expiry_and_missing_safety_prevent_human_completion():
    backend, _ = opened()
    # Before the Human deadline: new invalid Safety consumes sequence and clears permission.
    event = sample("motion_permitted", sequence=1)
    event["metadata"]["valid"] = False
    backend.on_assembly_evidence(now=101.6, event=event)
    assert backend.assembly_state["human_verification"]["status"] == "CLOSED"
    assert not reply(backend)["committed"]


def test_request_is_unique_and_closed_id_is_not_reused():
    backend, _ = opened()
    old = response(backend)
    assert open_request(backend)["reason"] == "HUMAN_REQUEST_ALREADY_OPEN"
    backend.on_assembly_evidence(now=102.5)
    for name in ACTIVE:
        event = sample(name, "UNKNOWN" if name == "vision_verdict" else None, 1)
        event["metadata"]["stamp"] = 102.5
        backend.on_assembly_evidence(now=102.5, event=event)
    proof = verification(1)
    proof["observation"]["metadata"] = sample("vision_verdict", "UNKNOWN", 1)["metadata"]
    proof["observation"]["metadata"]["stamp"] = 102.5
    proof["physical"].update(released_at=102.5, observe_ready_at=102.5)
    proof["physical"]["metadata"]["stamp"] = 102.5
    assert open_request(backend, proof=proof, now=102.5)["accepted"]
    assert backend.assembly_state["human_verification"]["context"]["request_id"] != old["metadata"]["request_id"]
    assert not reply(backend, packet=old, now=102.6)["committed"]


@pytest.mark.parametrize("case", HUMAN["invalid_cases"])
def test_malformed_response_is_rejected_without_mutating_backend(case):
    backend, _ = opened()
    packet, before = response(backend), backend.assembly_state
    packet[case["field"]] = case["value"]
    with pytest.raises(ValueError):
        reply(backend, packet=packet)
    assert backend.assembly_state == before


def test_log_failure_cannot_commit_human_confirmed_world(tmp_path):
    logger = JsonlLog(tmp_path)
    def record(event):
        if event["event"] == "ASSEMBLY_COMMITTED":
            raise OSError("disk full")
        logger(event)
    backend, _ = opened(record=record)
    assert not reply(backend)["committed"]
    state = backend.assembly_state
    assert state["decision"]["reason"].startswith("LOG_FAILED")
    assert state["world"] == TRIAL["world"] and state["completion"] is None
    assert state["human_verification"]["status"] == "CLOSED"
    rows = [json.loads(line) for line in (tmp_path / f'{TRIAL["job_id"]}.jsonl').read_text().splitlines()]
    assert [row["event"] for row in rows] == ["HUMAN_VERIFY_OPENED"]


@pytest.mark.parametrize("source,value", [("motion_permitted", False), ("execution_result", "FAILED"),
    ("contact_state", "JAMMED"), ("vision_verdict", "FAIL"), ("vision_verdict", "PASS")])
def test_request_cannot_override_failure_or_replace_automatic_verification(source, value):
    backend, _ = uncertain(source, value)
    assert not open_request(backend)["accepted"]
    assert backend.assembly_state["human_verification"] is None
    assert backend.assembly_state["completion"] is None


@pytest.mark.parametrize("field", ["stopped", "execution_ended", "released", "at_observe"])
def test_lost_physical_confirmation_closes_request_and_prevents_late_positive(field):
    backend, _ = opened()
    physical = verification(1)["physical"]
    physical[field] = False
    assert not reply(backend, physical=physical)["committed"]
    assert backend.assembly_state["human_verification"]["status"] == "CLOSED"
    assert backend.assembly_state["decision"]["reason"] == "WAIT_PHYSICAL_CONFIRMATION"
    assert not reply(backend, physical=verification(2)["physical"])["committed"]


def test_response_age_is_checked_before_deadline():
    backend, _ = opened()
    old = response(backend, stamp=101.5)
    result = reply(backend, now=102.25, packet=old)
    assert result["reason"] == "STALE_EVIDENCE" and not result["committed"]
    assert backend.assembly_state["human_verification"]["status"] == "OPEN"


def test_new_invalid_response_prevents_old_positive_reuse():
    backend, _ = opened()
    packet = response(backend, sequence=2)
    packet["metadata"]["valid"] = False
    assert not reply(backend, packet=packet)["accepted"]
    assert reply(backend, packet=response(backend, sequence=1))["reason"] == "STALE_SEQUENCE"
    assert backend.assembly_state["completion"] is None


def test_even_partial_observation_of_changed_structure_blocks_request():
    backend, _ = uncertain()
    proof = verification()
    proof["observation"]["complete"] = False
    proof["observation"]["world"]["blocks"][0]["x"] = 10
    assert not open_request(backend, proof=proof)["accepted"]
    assert backend.assembly_state["blocked_reason"] == "UNEXPECTED_WORLD_EFFECT"
    assert not open_request(backend, proof=verification(1))["accepted"]


def test_sensor_completion_closes_pending_human_session_and_preserves_history():
    events = []
    backend, _ = opened(record=events.append)
    old = response(backend)
    proof = verification(1)
    proof["observation"]["metadata"] = sample("vision_verdict", "PASS", 1)["metadata"]
    assert backend.on_assembly_evidence(now=101.6, event=sample("vision_verdict", "PASS", 1),
                                        verification=proof)["committed"]
    state = backend.assembly_state
    assert state["completion"]["verification_evidence"] == "SENSOR_VERIFIED"
    assert state["human_verification"]["close_reason"] == "COMPLETED_BY_SENSOR"
    assert events[-1]["result"]["human_verification"]["status"] == "CLOSED"
    assert not reply(backend, packet=old)["committed"]
    assert backend.assembly_state == state


def test_request_storage_failure_never_exposes_an_active_request():
    def broken(event):
        raise ValueError("invalid log storage")
    backend, _ = uncertain(record=broken)
    result = open_request(backend)
    assert not result["accepted"] and result["request"] is None
    assert backend.assembly_state["human_verification"]["status"] == "CLOSED"
    assert backend.assembly_state["blocked_reason"].startswith("LOG_FAILED")


def test_actual_jsonl_success_records_unknown_and_human_confirmation(tmp_path):
    backend, _ = opened(record=JsonlLog(tmp_path))
    assert reply(backend)["committed"]
    rows = [json.loads(line) for line in (tmp_path / f'{TRIAL["job_id"]}.jsonl').read_text().splitlines()]
    assert len(rows) == 2
    completion = rows[-1]["result"]["completion"]
    assert completion["verification_evidence"] == "HUMAN_VERIFIED"
    assert completion["evidence"]["vision_verdict"]["value"] == "UNKNOWN"
    assert completion["human_request"]["context"]["request_id"] == rows[0]["request_id"]


def test_deadline_does_not_mask_active_safety_stop():
    backend, _ = opened()
    event = sample("motion_permitted", False, 1)
    event["metadata"]["stamp"] = 102.5
    backend.on_assembly_evidence(now=102.5, event=event)
    state = backend.assembly_state
    assert state["decision"]["decision"] == "SAFE_STOP"
    assert state["human_verification"]["close_reason"] == "SAFETY_STOP"
    assert not reply(backend, now=102.5)["committed"]
    assert backend.assembly_state["decision"]["decision"] == "SAFE_STOP"


def test_unknown_answer_with_physical_correction_still_requires_new_attempt():
    backend, _ = opened()
    result = reply(backend, answer="UNKNOWN", inspection="PHYSICAL_CORRECTION")
    assert result["accepted"] and not result["committed"]
    assert backend.assembly_state["blocked_reason"] == "PHYSICAL_CORRECTION_REQUIRED"


def test_log_failure_during_request_close_preserves_safety_stop():
    def record(event):
        if event["event"] == "HUMAN_VERIFY_CLOSED":
            raise OSError("disk full")
    backend, _ = opened(record=record)
    backend.on_assembly_evidence(now=101.6, event=sample("motion_permitted", False, 1))
    state = backend.assembly_state
    assert state["decision"]["decision"] == "SAFE_STOP"
    assert state["human_verification"]["status"] == "CLOSED"
    assert state["blocked_reason"].startswith("LOG_FAILED")
    assert not reply(backend)["committed"]
    assert backend.assembly_state["decision"]["decision"] == "SAFE_STOP"
