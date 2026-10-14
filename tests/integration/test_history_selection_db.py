"""Selective imports preserve original logs and existing full archives."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from history import store
from history.records import InputError


@pytest.fixture
def connection():
    dsn = os.environ.get("HISTORY_TEST_DSN")
    if not dsn:
        pytest.skip("set HISTORY_TEST_DSN for actual PostgreSQL integration")
    with store.connect(dsn) as connection:
        database = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        if not database.endswith("_test"):
            pytest.fail("history integration requires a separate database ending in _test")
        store.initialize(connection)
        with connection.transaction(force_rollback=True):
            yield connection


def event(job, name, *, result=None, reason=None):
    return dict(timestamp="2026-10-14T00:00:00+00:00", job_id=job, plan_id=None,
                step_id=None, request_id=None, event=name, result=result, reason=reason)


def write(path, documents):
    raw = "".join(json.dumps(document, ensure_ascii=False) + "\n" for document in documents).encode()
    path.write_bytes(raw)
    return raw


def source():
    return "selection-tests/" + uuid4().hex + ".jsonl"


def snapshot(connection, key):
    return connection.execute("SELECT * FROM c2_history.sources WHERE source_key=%s", (key,)).fetchone()


def assert_archive(state, original):
    archived = Path(state["archive_path"])
    assert archived.read_bytes() == original
    assert state["archive_sha256"] == hashlib.sha256(original).hexdigest()
    assert state["archive_bytes"] == len(original)
    return archived


def test_new_default_selects_operations_and_archives_every_original_byte(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "events.jsonl"
    documents = [event(job, "JOB_STARTED"),
                 event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(frame=1)),
                 event(job, "ROBOT_MOTION_SAMPLE", result=dict(sample=dict(posx=[0] * 6))),
                 event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(candidate_event="THUMBS_UP_HELD")),
                 event(job, "ROBOT_ABORT", result=dict(reason="MOTION_TIMEOUT")),
                 event(job, "FUTURE_MODULE_DIAGNOSTIC", result=dict(message="retain unknown events")),
                 event(job, "JOB_COMPLETED")]
    original = write(path, documents)

    imported = store.ingest(connection, path, key)

    assert imported["inserted"] == 5
    state = snapshot(connection, key)
    assert state["ingest_policy"] == "operational-v1"
    assert state["last_line"] == 7
    assert state["prefix_sha256"] == hashlib.sha256(original).hexdigest()
    archived = assert_archive(state, original)
    assert tmp_path / "history_archive" in archived.parents
    rows = store.timeline(connection, job)
    assert [row["line_number"] for row in rows] == [1, 4, 5, 6, 7]
    assert [row["document"] for row in rows] == [documents[index] for index in (0, 3, 4, 5, 6)]
    assert path.read_bytes() == original


@pytest.mark.parametrize("name", ["ROBOT_CAMERA_CANDIDATE", "ROBOT_MOTION_SAMPLE"])
@pytest.mark.parametrize("marker", ["reason", "error", "success", "status"])
def test_failure_markers_in_diagnostic_events_are_not_filtered(connection, tmp_path, name, marker):
    job, key = str(uuid4()), source()
    document = event(job, name, result={})
    if marker == "reason":
        document["reason"] = "CAMERA_OR_ROBOT_FAILURE"
    elif marker == "error":
        document["result"]["error"] = dict(code="DRIVER_FAILURE")
    elif marker == "success":
        document["result"]["success"] = False
    else:
        document["result"]["status"] = "FAILED"
    path = tmp_path / "diagnostic-failure.jsonl"
    original = write(path, [document])

    assert store.ingest(connection, path, key)["inserted"] == 1
    assert store.timeline(connection, job)[0]["document"] == document
    assert_archive(snapshot(connection, key), original)


def test_explicit_archive_directory_and_pending_tail_preserve_source_snapshot(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "running.jsonl"
    completed = write(path, [event(job, "JOB_STARTED")])
    original = completed + b'{"unfinished":'
    path.write_bytes(original)
    archive_root = tmp_path / "originals"

    imported = store.ingest(connection, path, key, archive_root=archive_root)

    assert imported["inserted"] == 1
    assert imported["pending_line"] == 2
    state = snapshot(connection, key)
    assert state["last_line"] == 1
    assert state["prefix_sha256"] == hashlib.sha256(completed).hexdigest()
    archived = assert_archive(state, original)
    assert archive_root in archived.parents
    assert path.read_bytes() == original


def test_append_keeps_previous_archive_and_adds_only_new_selected_event(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "append.jsonl"
    initial = [event(job, "JOB_STARTED"), event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(frame=1))]
    original = write(path, initial)
    assert store.ingest(connection, path, key)["inserted"] == 1
    prior_archive = assert_archive(snapshot(connection, key), original)
    appended = initial + [event(job, "ROBOT_MOTION_SAMPLE", result=dict(sequence=2)),
                          event(job, "ROBOT_GESTURE_CAMERA_FAILED", result=dict(reason="CAMERA_EXITED"))]
    updated = write(path, appended)

    assert store.ingest(connection, path, key)["inserted"] == 1
    assert store.ingest(connection, path, key)["inserted"] == 0
    state = snapshot(connection, key)
    assert state["last_line"] == 4
    assert state["prefix_sha256"] == hashlib.sha256(updated).hexdigest()
    assert_archive(state, updated)
    assert prior_archive.read_bytes() == original
    assert [row["line_number"] for row in store.timeline(connection, job)] == [1, 4]


def test_change_to_excluded_committed_line_is_rejected_without_advancing_source(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "changed.jsonl"
    documents = [event(job, "JOB_STARTED"), event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(frame=1))]
    original = write(path, documents)
    store.ingest(connection, path, key)
    before = snapshot(connection, key)
    changed = deepcopy(documents)
    changed[1]["result"]["frame"] = 99
    write(path, changed + [event(job, "JOB_COMPLETED")])

    with pytest.raises(InputError, match="line changed"):
        store.ingest(connection, path, key)

    assert snapshot(connection, key) == before
    assert_archive(before, original)
    assert [row["event"] for row in store.timeline(connection, job)] == ["JOB_STARTED"]


def test_truncating_previously_excluded_line_is_rejected(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "truncated.jsonl"
    documents = [event(job, "JOB_STARTED"), event(job, "ROBOT_MOTION_SAMPLE", result=dict(sequence=1))]
    original = write(path, documents)
    store.ingest(connection, path, key)
    before = snapshot(connection, key)
    write(path, documents[:1])

    with pytest.raises(InputError, match="truncated"):
        store.ingest(connection, path, key)

    assert snapshot(connection, key) == before
    assert_archive(before, original)


@pytest.mark.parametrize("first,second", [("all", "operational-v1"), ("operational-v1", "all")])
def test_import_policy_cannot_change_for_existing_source(connection, tmp_path, first, second):
    job, key = str(uuid4()), source()
    path = tmp_path / "policy.jsonl"
    original = write(path, [event(job, "JOB_STARTED")])
    store.ingest(connection, path, key, policy=first)
    before = snapshot(connection, key)

    with pytest.raises(InputError, match="policy"):
        store.ingest(connection, path, key, policy=second)

    assert snapshot(connection, key) == before
    assert_archive(before, original)


def test_archive_contract_cannot_change_for_existing_source(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "contract.jsonl"
    original = write(path, [event(job, "JOB_STARTED")])
    store.ingest(connection, path, key, contract="day4")
    before = snapshot(connection, key)

    with pytest.raises(InputError, match="contract"):
        store.ingest(connection, path, key, contract="final-mvp-20261008")

    assert snapshot(connection, key) == before
    assert_archive(before, original)


def test_malformed_excluded_candidate_rolls_back_and_original_remains_intact(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "malformed.jsonl"
    malformed = event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(frame=1))
    del malformed["timestamp"]
    original = write(path, [event(job, "JOB_STARTED"), malformed])

    with pytest.raises(InputError, match=":2: missing field: timestamp"):
        store.ingest(connection, path, key)

    assert snapshot(connection, key) is None
    assert not store.timeline(connection, job)
    assert connection.execute("SELECT 1 FROM c2_history.jobs WHERE job_id=%s", (job,)).fetchone() is None
    assert path.read_bytes() == original


def test_all_profile_is_retained_on_replay_and_operational_query_keeps_failures(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "legacy-full.jsonl"
    documents = [event(job, "JOB_STARTED"), event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(frame=1)),
                 event(job, "ROBOT_MOTION_SAMPLE", result=dict(sequence=1)),
                 event(job, "ROBOT_MOTION_SAMPLE", result=dict(status="FAILED")),
                 event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(candidate_event="THUMBS_UP_HELD")),
                 event(job, "JOB_COMPLETED")]
    original = write(path, documents)
    assert store.ingest(connection, path, key, policy="all")["inserted"] == 6

    assert store.ingest(connection, path, key)["inserted"] == 0
    full = store.timeline(connection, job)
    operational = store.timeline(connection, job, operational=True)

    assert snapshot(connection, key)["ingest_policy"] == "all"
    assert [row["document"] for row in full] == documents
    assert "".join(row["raw_line"] for row in full).encode() == original
    assert [row["line_number"] for row in operational] == [1, 4, 5, 6]
    assert_archive(snapshot(connection, key), original)


def test_legacy_source_without_prefix_digest_verifies_old_rows_and_keeps_all_policy(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "legacy-prefix.jsonl"
    documents = [event(job, "JOB_STARTED"), event(job, "ROBOT_CAMERA_CANDIDATE", result=dict(frame=1))]
    write(path, documents)
    store.ingest(connection, path, key, policy="all")
    # Sources migrated from full imports do not yet have a whole-prefix digest.
    connection.execute("UPDATE c2_history.sources SET prefix_sha256=NULL WHERE source_key=%s", (key,))
    updated = write(path, documents + [event(job, "ROBOT_MOTION_SAMPLE", result=dict(sequence=2))])

    assert store.ingest(connection, path, key)["inserted"] == 1

    state = snapshot(connection, key)
    assert state["ingest_policy"] == "all"
    assert state["last_line"] == 3
    assert state["prefix_sha256"] == hashlib.sha256(updated).hexdigest()
    assert [row["line_number"] for row in store.timeline(connection, job)] == [1, 2, 3]
    assert_archive(state, updated)


def test_archive_write_failure_keeps_committed_database_and_original_snapshot(connection, tmp_path):
    job, key = str(uuid4()), source()
    path = tmp_path / "archive-failure.jsonl"
    initial = [event(job, "JOB_STARTED")]
    original = write(path, initial)
    store.ingest(connection, path, key)
    before = snapshot(connection, key)
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("existing local file", encoding="utf-8")
    updated = write(path, initial + [event(job, "JOB_COMPLETED")])

    with pytest.raises(OSError):
        store.ingest(connection, path, key, archive_root=blocked_root)

    assert snapshot(connection, key) == before
    assert [row["event"] for row in store.timeline(connection, job)] == ["JOB_STARTED"]
    assert_archive(before, original)
    assert path.read_bytes() == updated


def test_operational_sql_matches_python_for_diagnostic_variants_and_unknown_events(connection, tmp_path):
    from history.selection import should_store

    job, key = str(uuid4()), source()
    path = tmp_path / "selection-parity.jsonl"
    documents = [event(job, "JOB_STARTED"), event(job, "UNKNOWN_DIAGNOSTIC", result=dict(sample=1))]
    for name in ("ROBOT_CAMERA_CANDIDATE", "ROBOT_MOTION_SAMPLE"):
        documents.extend(event(job, name, result=result) for result in (
            {}, None, "driver diagnostic", ["unstructured diagnostic"],
            dict(error=None, success=True, status="OK"),
            dict(error=dict(code="DEVICE_FAILED")), dict(error=False),
            dict(success=False), dict(status="ERROR"), dict(status="FAILED"),
            dict(status="REJECTED"), dict(status="STOPPED"),
            dict(candidate_event=None), dict(candidate_event="THUMBS_UP_HELD"),
            dict(reason="SINGLE_KNOWN_SHAPE_REQUIRED"),
        ))
        documents.append(event(job, name, result={}, reason="DEVICE_FAILURE"))
    original = write(path, documents)
    assert store.ingest(connection, path, key, policy="all")["inserted"] == len(documents)
    expected = [document for document in documents if should_store(document)]

    selected = store.timeline(connection, job, operational=True)

    assert [row["document"] for row in selected] == expected
    assert [row["document"] for row in store.timeline(connection, job)] == documents
    assert any(row["event"] == "UNKNOWN_DIAGNOSTIC" for row in selected)
    assert len(selected) < len(documents)
    assert_archive(snapshot(connection, key), original)
