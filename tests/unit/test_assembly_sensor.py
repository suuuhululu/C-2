from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.assembly_sensor import normalize_sensor_snapshot
from test_assembly_completion import ACTIVE, DATA, TRIAL, begin, candidate, metadata, sample, verification
from test_assembly_human import opened
from test_assembly_recovery import failed, propose, resume_inputs


FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "interfaces/fixtures/assembly_sensor.json").read_text())
CLOCK = "TRIAL_MONOTONIC"


def packet(sequence=0, stamp=101.5, status=72):
    result = deepcopy(FIXTURE["snapshot"])
    result["metadata"] = metadata(ACTIVE["motion_permitted"], stamp=stamp, sequence=sequence)
    result["sample_window"].update(started_at=stamp, finished_at=stamp + 0.1)
    result["gripper"]["status_register"] = status
    return result


def normalize(snapshot=None, **changes):
    kwargs = dict(active=ACTIVE["motion_permitted"], now=101.6,
        max_age=DATA["attempt_collection"]["max_age"]["motion_permitted"],
        last_sequence=None, last_stamp=None, clock_id=CLOCK)
    kwargs.update(changes)
    return normalize_sensor_snapshot(packet() if snapshot is None else snapshot, **kwargs)


def ingest(backend, snapshot=None, **changes):
    kwargs = dict(snapshot=packet() if snapshot is None else snapshot, now=101.6, clock_id=CLOCK)
    kwargs.update(changes)
    return backend.on_assembly_sensor_snapshot(**kwargs)


def test_reported_field_values_are_preserved_without_completion_or_motion():
    snapshot = packet()
    before = deepcopy(snapshot)
    backend, ports = begin()
    day4 = backend.state
    result = ingest(backend, snapshot)
    diagnostic = result["diagnostic"]
    assert result["accepted"] and not result["committed"]
    assert diagnostic["raw"] == before and snapshot == before
    assert diagnostic["wrench_values"] == FIXTURE["snapshot"]["wrench"]["tool_force"]
    assert diagnostic["gripper_width_mm"] == 62.1 and diagnostic["gripper_fault_bits"] == [3, 6]
    assert diagnostic["robot_idle_indication"] is True
    assert all(value is None for value in diagnostic["physical_facts"].values())
    assert diagnostic["execution_result"] is None and diagnostic["contact_state"] == "UNKNOWN"
    assert backend.assembly_state["decision"]["decision"] == "SAFE_STOP"
    assert backend.assembly_state["world"] == TRIAL["world"] and ports == [] and backend.state == day4


@pytest.mark.parametrize("status", [0, 1, 2, 128, 65535])
def test_register_values_never_generate_positive_motion_permission(status):
    result = normalize(packet(status=status))
    assert result["event"]["value"] is not True
    assert result["diagnostic"]["motion_permitted"] is not True
    assert result["event"]["metadata"]["valid"] is (status == 65535)


def test_current_healthy_diagnostic_clears_previous_positive_safety_cache():
    backend, ports = candidate()
    result = ingest(backend, packet(1, status=0))
    assert result["accepted"] and backend.assembly_state["decision"]["reason"] == "SAFETY_UNKNOWN"
    assert backend.assembly_state["collection"]["records"]["motion_permitted"] is None
    assert not backend.on_assembly_evidence(now=101.6, verification=verification())["committed"]
    assert ports == []


def test_safe_stop_latch_survives_later_clear_register_and_blocks_recovery():
    backend, _ = begin()
    ingest(backend)
    ingest(backend, packet(1, 101.7, 0), now=101.8)
    assert backend.assembly_state["decision"]["decision"] == "SAFE_STOP"
    assert backend.assembly_state["collection"]["latched"]["motion_permitted"] is False
    result = propose(backend, cp=None, now=101.8)
    assert result["proposal"]["status"] == "SAFE_STOP"


@pytest.mark.parametrize("field", ["job_id", "plan_id", "step_id", "attempt_id", "request_id", "calibration_id", "source_epoch", "basis_world_revision"])
def test_wrong_context_never_relabels_historical_device_values(field):
    snapshot = packet()
    snapshot["metadata"][field] = 999 if field == "basis_world_revision" else "OLD"
    backend, _ = begin()
    assert not ingest(backend, snapshot)["accepted"]
    assert backend.assembly_state["sensor_snapshot"] is None
    assert backend.assembly_state["collection"]["latched"]["motion_permitted"] is None


@pytest.mark.parametrize("case", ["stale", "future", "sequence", "stamp", "clock", "window", "receipt"])
def test_acquisition_window_rejects_stale_reordered_or_wrong_clock_samples(case):
    snapshot, changes = packet(), {}
    if case == "stale": changes["now"] = 104
    if case == "future": changes["now"] = 101
    if case == "sequence": changes["last_sequence"] = 0
    if case == "stamp": changes["last_stamp"] = 101.6
    if case == "clock": snapshot["sample_window"]["clock_id"] = "CAMERA_ROS"
    if case == "window": snapshot["sample_window"]["finished_at"] = 101
    if case == "receipt": snapshot["metadata"]["stamp"] = 101.6
    result = normalize(snapshot, **changes)
    assert not result["accepted"] and result["event"] is None and result["diagnostic"] is None


def test_new_invalid_snapshot_consumes_sequence_and_cannot_raise_safety_fault():
    backend, _ = candidate()
    snapshot = packet(1)
    snapshot["metadata"]["valid"] = False
    result = ingest(backend, snapshot)
    assert not result["accepted"] and not result["diagnostic"]["rgbd_metadata_usable"]
    assert backend.assembly_state["collection"]["seen_sequence"]["motion_permitted"] == 1
    assert backend.assembly_state["collection"]["latched"]["motion_permitted"] is None
    assert not ingest(backend, packet(0, status=0))["accepted"]


@pytest.mark.parametrize("query", ["robot", "wrench", "gripper", "camera"])
def test_query_failure_is_preserved_and_cannot_become_success(query):
    snapshot = packet(status=0)
    snapshot[query]["success"] = False
    result = normalize(snapshot)
    diagnostic = result["diagnostic"]
    assert result["accepted"] and result["event"]["value"] is None
    assert diagnostic["raw"][query]["success"] is False
    if query == "wrench": assert diagnostic["wrench_values"] is None
    if query == "robot": assert diagnostic["robot_idle_indication"] is None
    if query == "gripper": assert diagnostic["gripper_width_mm"] is None
    if query == "camera": assert not diagnostic["rgbd_metadata_usable"]


def test_failed_register_query_does_not_use_stale_fault_bits():
    snapshot = packet()
    snapshot["gripper"]["success"] = False
    assert normalize(snapshot)["event"]["value"] is None


@pytest.mark.parametrize("case", ["stamp", "frame", "encoding", "alignment", "size", "unit"])
def test_camera_metadata_failure_keeps_safety_fault_but_never_reports_vision_pass(case):
    snapshot = packet()
    camera = snapshot["camera"]
    if case == "stamp": camera["depth_stamp"]["nanosec"] += 1
    if case == "frame": camera["depth_frame"] = "native_depth"
    if case == "encoding": camera["depth_encoding"] = "32FC1"
    if case == "alignment": camera["aligned_to_rgb"] = False
    if case == "size": camera["width"] = None
    if case == "unit": camera["depth_unit"] = "UNKNOWN"
    diagnostic = normalize(snapshot)["diagnostic"]
    assert not diagnostic["rgbd_metadata_usable"] and diagnostic["motion_permitted"] is False
    assert diagnostic["vision_verdict"] == "UNKNOWN" and not diagnostic["image_content_verified"]
    if case in ("encoding", "unit"): assert diagnostic["depth_unit"] is None


def test_camera_clock_and_human_clock_are_preserved_without_attempt_clock_conversion():
    snapshot = packet(status=0)
    snapshot["camera"]["depth_zero_count"] = 1280 * 720
    snapshot["human_confirmation"]["stopped"] = True
    diagnostic = normalize(snapshot)["diagnostic"]
    assert diagnostic["raw"]["camera"]["rgb_stamp"]["sec"] == 1000
    assert diagnostic["raw"]["human_confirmation"]["released"] is True
    assert all(value is None for value in diagnostic["physical_facts"].values())
    assert diagnostic["depth_zero_scope"] == "FULL_FRAME" and diagnostic["depth_zero_meaning"] == "MISSING_MEASUREMENT"


@pytest.mark.parametrize("ref,force_frame,moment_frame", [(0,"BASE","TOOL"),(1,"TOOL","TOOL")])
def test_frame_reports_and_device_timestamp_still_do_not_create_contact_classification(ref, force_frame, moment_frame):
    snapshot = packet(status=0)
    snapshot["wrench"].update(ref=ref,force_frame=force_frame,moment_frame=moment_frame,
        frames_verified=True,device_stamp=999999,device_clock_id="HARDWARE_CLOCK")
    diagnostic = normalize(snapshot)["diagnostic"]
    assert diagnostic["raw"]["wrench"]["moment_frame"] == moment_frame
    assert diagnostic["wrench_time_basis"] == "DEVICE_UNBOUND" and not diagnostic["wrench_contact_usable"]
    assert diagnostic["contact_state"] == "UNKNOWN"


@pytest.mark.parametrize("field,value", [("tool_force",[0]*5),("tool_force",[True]*6),("tool_force",[float('nan')]*6),("ref",True),("device_stamp",1)])
def test_malformed_wrench_is_rejected_without_mutating_backend(field, value):
    backend, _ = begin()
    before = backend.assembly_state
    snapshot = packet()
    snapshot["wrench"][field] = value
    with pytest.raises(ValueError): ingest(backend, snapshot)
    assert backend.assembly_state == before


@pytest.mark.parametrize("case", ["register", "utc", "human", "pixels", "extra"])
def test_malformed_projection_is_rejected(case):
    snapshot = packet()
    if case == "register": snapshot["gripper"]["status_register"] = 65536
    if case == "utc": snapshot["sample_window"]["request_utc"] = "2026-10-07T12:00:00"
    if case == "human": snapshot["human_confirmation"]["operator"] = None
    if case == "pixels": snapshot["camera"]["depth_zero_count"] = 1280 * 720 + 1
    if case == "extra": snapshot["release_completed"] = True
    with pytest.raises(ValueError): normalize(snapshot)


def test_sensor_update_closes_pending_human_request_without_completing_it():
    backend, _ = opened()
    result = ingest(backend, packet(1, status=0))
    assert result["accepted"] and backend.assembly_state["human_verification"]["status"] == "CLOSED"
    assert backend.assembly_state["completion"] is None


def test_diagnostic_is_logged_with_raw_values_and_log_failure_preserves_safe_stop():
    events = []
    backend, _ = begin(record=events.append)
    ingest(backend)
    assert events[-1]["event"] == "SENSOR_SNAPSHOT_EVALUATED"
    assert events[-1]["result"]["diagnostic"]["raw"] == packet()
    def fail(event): raise OSError("disk full")
    backend, _ = begin(record=fail)
    result = ingest(backend)
    assert not result["accepted"] and result["reason"].startswith("LOG_FAILED")
    assert backend.assembly_state["decision"]["decision"] == "SAFE_STOP"


def test_clock_binding_is_frozen_and_read_only_state_cannot_change_source_values():
    backend, _ = begin()
    ingest(backend, packet(status=0))
    state = backend.assembly_state
    state["sensor_snapshot"]["raw"]["gripper"]["status_register"] = 72
    assert backend.assembly_state["sensor_snapshot"]["raw"]["gripper"]["status_register"] == 0
    with pytest.raises(ValueError, match="frozen"):
        ingest(backend, packet(1), clock_id="NEW_CLOCK")


def test_new_attempt_clears_sensor_diagnostics_and_rejects_old_snapshot():
    backend, _ = failed()
    ingest(backend, packet(1, status=0))
    safety = sample("motion_permitted", True, 2)
    safety["metadata"]["stamp"] = 101.7
    backend.on_assembly_evidence(now=101.7, event=safety)
    assert backend.assembly_state["sensor_snapshot"] is not None
    assert propose(backend, now=101.7)["accepted"]
    assert backend.resume_assembly_trial(**resume_inputs(stamp=101.8))["accepted"]
    assert backend.assembly_state["sensor_clock_id"] is None and backend.assembly_state["sensor_snapshot"] is None
    assert backend.assembly_state["attempt_history"][-1]["sensor_snapshot"] is not None
    assert not ingest(backend, packet(1), now=101.8)["accepted"]


def test_host_clock_rewind_blocks_sensor_ingestion_until_new_attempt():
    backend, _ = begin()
    ingest(backend, packet(status=0))
    result = ingest(backend, packet(1, 101.3, 0), now=101.4)
    assert not result["accepted"] and result["reason"] == "CLOCK_RESET"
    result = ingest(backend, packet(2, 101.7, 0), now=101.8)
    assert not result["accepted"] and result["reason"] == "CLOCK_RESET"
