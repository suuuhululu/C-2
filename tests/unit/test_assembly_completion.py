from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.backend import Backend
from app.jsonl_log import JsonlLog


DATA = json.loads((Path(__file__).resolve().parents[2] /
                   "interfaces/fixtures/assembly_evidence.json").read_text())
COLLECT, TRIAL = DATA["attempt_collection"], DATA["completion_trial"]
ACTIVE = {source: {**COLLECT["common_context"], **settings, "job_id": TRIAL["job_id"]}
          for source, settings in COLLECT["sources"].items()}
PHYSICAL_CONTEXT = {**ACTIVE["execution_result"], **TRIAL["physical_source"]}


def metadata(context, *, stamp, sequence=0, valid=True):
    return {**{key: value for key, value in context.items() if key != "opened_at"},
            "stamp": stamp, "sequence": sequence, "valid": valid}


def sample(source, value=None, sequence=0):
    return dict(source=source, metadata=metadata(ACTIVE[source],
                stamp=TRIAL["stamps"][source], sequence=sequence),
                value=COLLECT["positive_values"][source] if value is None else value)


def verification(sequence=0):
    physical = deepcopy(TRIAL["physical"])
    physical["metadata"] = metadata(PHYSICAL_CONTEXT, stamp=physical.pop("stamp"),
                                    sequence=sequence, valid=physical.pop("valid"))
    physical.pop("sequence")
    return dict(physical=physical, observation=dict(complete=True,
        metadata=sample("vision_verdict")["metadata"], world=deepcopy(TRIAL["observed_world"])))


def begin(*, record=None, **changes):
    ports = []
    backend = Backend(lambda *args: ports.append(args), mode="FAKE", record=record)
    inputs = dict(active=deepcopy(ACTIVE), max_age=deepcopy(COLLECT["max_age"]),
                  physical_context=deepcopy(PHYSICAL_CONTEXT),
                  physical_max_age=TRIAL["physical_max_age"],
                  world=deepcopy(TRIAL["world"]), target=deepcopy(TRIAL["target"]), now=100)
    inputs.update(changes)
    backend.begin_assembly_trial(**inputs)
    return backend, ports


def candidate(*, record=None):
    backend, ports = begin(record=record)
    for source in ACTIVE:
        backend.on_assembly_evidence(now=101.5, event=sample(source))
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["decision"]["reason"] == "WAIT_COMPLETION_VERIFICATION"
    return backend, ports


def test_backend_atomically_commits_world_and_completion_and_never_dispatches_motion():
    events = []
    backend, ports = candidate(record=events.append)
    day4 = backend.state
    result = backend.on_assembly_evidence(now=101.5, verification=verification())
    assert result["committed"] is True
    state = backend.assembly_state
    assert state["world"] == TRIAL["observed_world"]
    assert state["completion"]["verification_evidence"] == "SENSOR_VERIFIED"
    assert state["completion"]["attempt_id"] == ACTIVE["vision_verdict"]["attempt_id"]
    assert state["completion"]["basis_world_revision"] == 5
    assert state["completion"]["observed_world_revision"] == 6
    assert state["completion"]["verification"] == verification()
    assert state["completion"]["evidence"]["contact_state"]["value"] == "SEATED"
    assert backend.state == day4 and ports == []
    assert len(events) == 1 and events[0]["event"] == "ASSEMBLY_COMMITTED"
    old = deepcopy(state)
    assert backend.on_assembly_evidence(now=999, verification=verification())["reason"] == "ALREADY_COMMITTED"
    assert backend.assembly_state == old and len(events) == 1


@pytest.mark.parametrize("field", ["stopped", "execution_ended", "released", "at_observe"])
@pytest.mark.parametrize("value", [False, None])
def test_missing_physical_facts_cannot_commit(field, value):
    backend, _ = candidate()
    proof = verification()
    proof["physical"][field] = value
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["decision"]["reason"] == "WAIT_PHYSICAL_CONFIRMATION"
    assert backend.assembly_state["world"] == TRIAL["world"]


@pytest.mark.parametrize("field,value", [("released_at", 100.25),
    ("released_at", 101.4), ("observe_ready_at", 102), ("observe_ready_at", None)])
def test_capture_must_follow_seated_release_and_observation_readiness(field, value):
    backend, _ = candidate()
    proof = verification()
    proof["physical"][field] = value
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["decision"]["reason"] in ("WAIT_PHYSICAL_CONFIRMATION", "INVALID_COMPLETION_ORDER")


@pytest.mark.parametrize("field,value,reason", [("attempt_id", "OLD", "ATTEMPT_ID_MISMATCH"),
    ("calibration_id", "OLD", "CALIBRATION_ID_MISMATCH"), ("source_epoch", "OLD", "SOURCE_EPOCH_MISMATCH"),
    ("request_id", "OLD", "REQUEST_ID_MISMATCH"), ("basis_world_revision", 6, "BASIS_WORLD_REVISION_MISMATCH"),
    ("stamp", 99, "BEFORE_REQUEST_WINDOW"), ("stamp", 102, "FUTURE_EVIDENCE"),
    ("valid", False, "INVALID_EVIDENCE")])
def test_invalid_physical_context_never_commits(field, value, reason):
    backend, _ = candidate()
    proof = verification()
    proof["physical"]["metadata"][field] = value
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["decision"]["reason"] == reason


def test_stale_physical_snapshot_is_rejected_with_fresh_sensor_evidence():
    backend, _ = begin(physical_max_age=0.1)
    for source in ACTIVE:
        backend.on_assembly_evidence(now=101.75, event=sample(source))
    backend.on_assembly_evidence(now=101.75, verification=verification())
    assert backend.assembly_state["decision"]["reason"] == "STALE_EVIDENCE"
    assert backend.assembly_state["completion"] is None


def test_latest_invalid_physical_report_consumes_sequence_and_blocks_old_positive():
    backend, _ = candidate()
    proof = verification(2)
    proof["physical"]["metadata"]["valid"] = False
    backend.on_assembly_evidence(now=101.5, verification=proof)
    backend.on_assembly_evidence(now=101.5, verification=verification(1))
    assert backend.assembly_state["decision"]["reason"] == "STALE_SEQUENCE"
    assert backend.assembly_state["completion"] is None
    backend.on_assembly_evidence(now=101.5, verification=verification(3))
    assert backend.assembly_state["completion"] is not None


def test_observation_and_pass_must_be_the_same_frame():
    backend, _ = candidate()
    proof = verification()
    proof["observation"]["metadata"]["sequence"] = 1
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["decision"]["reason"] == "VISION_FRAME_MISMATCH"
    assert backend.assembly_state["completion"] is None


def test_observation_metadata_is_validated_before_matching_pass():
    backend, _ = candidate()
    proof, before = verification(), backend.assembly_state
    proof["observation"]["metadata"]["valid"] = 1
    with pytest.raises(ValueError, match="valid"):
        backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state == before


def test_early_invalid_physical_report_prevents_replaying_older_success():
    backend, _ = begin()
    proof = verification(2)
    proof["physical"]["metadata"]["valid"] = False
    backend.on_assembly_evidence(now=101.5, verification=proof)
    for source in ACTIVE:
        backend.on_assembly_evidence(now=101.5, event=sample(source))
    backend.on_assembly_evidence(now=101.5, verification=verification(1))
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["decision"]["reason"] == "STALE_SEQUENCE"


def test_expired_contact_and_clock_rewind_do_not_commit_cached_candidate():
    backend, _ = candidate()
    backend.on_assembly_evidence(now=104, verification=verification())
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["world"] == TRIAL["world"]
    backend.on_assembly_evidence(now=101.5, verification=verification(1))
    assert backend.assembly_state["decision"]["reason"] == "CLOCK_RESET"


def test_physical_higher_sequence_cannot_reintroduce_older_capture():
    backend, _ = candidate()
    proof = verification()
    proof["physical"]["released"] = False
    backend.on_assembly_evidence(now=101.5, verification=proof)
    proof = verification(1)
    proof["physical"]["metadata"]["stamp"] = 101.4
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["decision"]["reason"] == "OUT_OF_ORDER_STAMP"
    assert backend.assembly_state["completion"] is None


def test_physical_confirmation_before_capture_cannot_prove_safe_observation():
    backend, _ = candidate()
    proof = verification()
    proof["physical"]["metadata"]["stamp"] = 101.4
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["decision"]["reason"] == "INVALID_COMPLETION_ORDER"
    assert backend.assembly_state["completion"] is None


def test_partial_view_requests_human_verification_without_changing_world():
    backend, _ = candidate()
    proof = verification()
    proof["observation"]["complete"] = False
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["decision"]["decision"] == "REQUEST_HUMAN_VERIFICATION"
    assert backend.assembly_state["world"] == TRIAL["world"]


@pytest.mark.parametrize("change,reason", [("reference", "REFERENCE_CHANGED"),
    ("extra", "UNEXPECTED_WORLD_EFFECT"), ("revision", "WORLD_REVISION_MISMATCH"),
    ("target", "TARGET_NOT_ASSEMBLED")])
def test_unexpected_world_effect_latches_until_new_attempt(change, reason):
    backend, _ = candidate()
    proof = verification()
    world = proof["observation"]["world"]
    if change == "reference":
        world["blocks"][0]["color"] = "yellow"
    elif change == "extra":
        world["blocks"].append({**TRIAL["target"], "x":10, "layer":1})
    elif change == "revision":
        world["world_revision"] = 7
    else:
        world["blocks"][1]["x"] = 10
    backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state["decision"]["reason"] == reason
    backend.on_assembly_evidence(now=101.5, verification=verification(1))
    assert backend.assembly_state["decision"]["reason"] == reason
    assert backend.assembly_state["decision"]["decision"] == ("RECOVERY_REQUIRED" if change == "target" else "HOLD")
    assert backend.assembly_state["completion"] is None


@pytest.mark.parametrize("source,value", [("motion_permitted", False),
    ("contact_state", "JAMMED"), ("vision_verdict", "FAIL"), ("execution_result", "CANCELED")])
def test_physical_and_visual_success_cannot_override_known_failure(source, value):
    backend, _ = candidate()
    backend.on_assembly_evidence(now=101.5, event=sample(source, value, 1), verification=verification())
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["world"] == TRIAL["world"]


def test_logger_failure_prevents_both_commits_and_cannot_be_retried_as_success():
    def broken(event):
        raise OSError("disk full")
    backend, _ = candidate(record=broken)
    backend.on_assembly_evidence(now=101.5, verification=verification())
    assert backend.assembly_state["decision"]["reason"].startswith("LOG_FAILED")
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["world"] == TRIAL["world"]
    backend.on_assembly_evidence(now=101.5, verification=verification(1))
    assert backend.assembly_state["completion"] is None


def test_actual_jsonl_logger_records_complete_evidence_once(tmp_path):
    backend, _ = candidate(record=JsonlLog(tmp_path))
    backend.on_assembly_evidence(now=101.5, verification=verification())
    lines = (tmp_path / f'{TRIAL["job_id"]}.jsonl').read_text().splitlines()
    event = json.loads(lines[0])
    assert len(lines) == 1
    assert event["result"]["completion"] == backend.assembly_state["completion"]
    assert event["result"]["world"] == backend.assembly_state["world"]


@pytest.mark.parametrize("case", TRIAL["invalid_cases"])
def test_bad_physical_values_raise_without_partial_backend_mutation(case):
    backend, _ = candidate()
    proof, before = verification(), backend.assembly_state
    proof["physical"][case["field"]] = case["value"]
    with pytest.raises(ValueError):
        backend.on_assembly_evidence(now=101.5, verification=proof)
    assert backend.assembly_state == before


def test_trial_is_explicit_isolated_and_copies_inputs_and_outputs():
    backend, ports = begin()
    assert backend.command({"command":"START"}) == {"accepted":False, "reason":"RESEARCH_TRIAL_ACTIVE"}
    with pytest.raises(ValueError, match="trial"):
        backend.begin_assembly_trial(active=ACTIVE, max_age=COLLECT["max_age"],
            physical_context=PHYSICAL_CONTEXT, physical_max_age=2,
            world=TRIAL["world"], target=TRIAL["target"], now=100)
    state = backend.assembly_state
    state["world"]["blocks"].clear()
    assert backend.assembly_state["world"] == TRIAL["world"] and ports == []


def test_real_backend_cannot_enter_research_fixture_trial():
    backend = Backend(lambda *args: None, mode="REAL", single_trial=True)
    with pytest.raises(ValueError, match="FAKE"):
        backend.begin_assembly_trial(active=ACTIVE, max_age=COLLECT["max_age"],
            physical_context=PHYSICAL_CONTEXT, physical_max_age=2,
            world=TRIAL["world"], target=TRIAL["target"], now=100)
    assert backend.assembly_state is None


@pytest.mark.parametrize("changes", [{"target":{**TRIAL["target"],"x":4}},
    {"world":{**TRIAL["world"],"world_revision":6}}, {"physical_max_age":0},
    {"physical_context":{**PHYSICAL_CONTEXT,"calibration_id":"OLD"}}])
def test_begin_rejects_unapproved_geometry_or_inconsistent_context(changes):
    with pytest.raises(ValueError):
        begin(**changes)
