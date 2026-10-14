from copy import deepcopy

import pytest

from history.selection import PROFILES, should_store, sql_condition


def record(name="ROBOT_CAMERA_CANDIDATE", result=None, *, reason=None):
    return dict(event=name, result={} if result is None else result, reason=reason)


@pytest.mark.parametrize("document", [
    record(result=dict(candidate_event=None, reason="SINGLE_KNOWN_SHAPE_REQUIRED",
                       preview_request_id="active-camera-request")),
    record("ROBOT_MOTION_SAMPLE", dict(segment="TRANSIT", sample=dict(wrench=[0] * 6))),
])
def test_routine_frame_and_motion_samples_remain_only_in_raw_archive(document):
    assert should_store(document) is False


@pytest.mark.parametrize("name", [
    "PLAN_ADOPTED", "CHECK_RESULT", "ASSEMBLY_COMPLETED", "ROBOT_STOP_VERIFIED",
    "ROBOT_WAIT_SAMPLE_REJECTED", "ROBOT_CONTACT_SAMPLE", "ROBOT_GRIP_SAMPLE",
    "MOTION_SAMPLE", "CAMERA_CANDIDATE", "FUTURE_DIAGNOSTIC_EVENT",
])
def test_only_the_two_known_diagnostic_names_are_filtered(name):
    assert should_store(record(name)) is True


@pytest.mark.parametrize("name", ["ROBOT_CAMERA_CANDIDATE", "ROBOT_MOTION_SAMPLE"])
@pytest.mark.parametrize("result,reason", [
    ({}, "OPERATOR_CANCELLED"),
    ({"error": "SENSOR_DISCONNECTED"}, None),
    ({"error": {"code": "FAULT"}}, None),
    ({"success": False}, None),
    ({"status": "ERROR"}, None),
    ({"status": "FAILED"}, None),
    ({"status": "REJECTED"}, None),
    ({"status": "STOPPED"}, None),
])
def test_explicit_failure_and_stop_evidence_is_kept(name, result, reason):
    assert should_store(record(name, result, reason=reason)) is True


@pytest.mark.parametrize("candidate", ["THUMBS_UP_HELD", "THUMB_INDEX_HELD", False, {}])
def test_any_nonnull_camera_signal_is_kept(candidate):
    assert should_store(record(result=dict(candidate_event=candidate))) is True


@pytest.mark.parametrize("result", [None, "unknown-format", [], False])
def test_nonobject_diagnostic_results_are_retained_conservatively(result):
    document = dict(event="ROBOT_MOTION_SAMPLE", result=result, reason=None)
    assert should_store(document) is True


@pytest.mark.parametrize("result", [
    {"error": None, "success": True, "status": "OK"},
    {"success": 0, "status": []},
    {"status": {}, "candidate_event": None},
])
def test_optional_values_do_not_invent_failures(result):
    assert should_store(record(result=result)) is False


def test_selection_does_not_rewrite_the_archived_document():
    document = record(result=dict(candidate_event=None, hands=[dict(x=0.5)]))
    original = deepcopy(document)
    should_store(document)
    assert document == original


def test_profiles_and_parameterized_sql_are_available_to_callers():
    assert PROFILES == ("all", "operational-v1")
    sql, params = sql_condition("event_rows")
    assert isinstance(sql, str) and sql
    assert isinstance(params, tuple)
    assert "ROBOT_CAMERA_CANDIDATE" not in sql and "ROBOT_MOTION_SAMPLE" not in sql
    assert "ROBOT_CAMERA_CANDIDATE" in params[0]


@pytest.mark.parametrize("alias", ["", "e;DELETE FROM events", "e.document", "e--", None])
def test_sql_alias_rejects_invalid_identifiers(alias):
    with pytest.raises(ValueError, match="SQL table alias"):
        sql_condition(alias)
