"""B 계약 Fixture → D 표시 봉투 → HMI/DB. 실제 B·Robot·실행 채택은 호출하지 않는다."""

from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.hmi_contracts import validate_hmi_snapshot
from app.qt_hmi import HmiWindow
from history.final_mvp import CONTRACT, checks, validate_response
from history.records import parse_record
from test_hmi_remaining import VALIDATOR

ROOT = Path(__file__).resolve().parents[2]


def five_layer_result():
    snapshot = json.loads((ROOT / "interfaces/fixtures/hmi.json").read_text())["snapshots"]["mismatch"]
    blocks = [dict(brick_type="2x3x1", color="blue", x=21, y=22, layer=n,
                   orientation_deg=90) for n in range(1, 6)]
    actual = deepcopy(blocks)
    actual[-1]["color"] = "yellow"
    # B가 발급한 revision을 그대로 표시·보관하며 D에서 다시 비교하지 않는다.
    response = dict(check_id="round1-check-five", check_kind="STEP",
        plan_id="round1-plan", step_id="S05", status="OK", comparison="MISMATCH",
        current=dict(current_revision=17, blocks=actual),
        expected=dict(plan_id="round1-plan", step_id="S05", blocks=blocks),
        difference=dict(missing=blocks[-1:], unexpected=actual[-1:], unobservable=[]),
        observation=dict(observation_seq=9, visible_blocks=actual[-1:],
            verified_regions=[dict(x=21, y=22, width=3, height=2, layer=5)], reason=None),
        reason="B confirmed color difference")
    snapshot["actions"]["job_id"] = str(uuid4())
    snapshot["design"] = dict(design_version=1, blocks=deepcopy(blocks))
    snapshot["current"] = deepcopy(response["current"])
    snapshot["progress"] = dict(completed=4, total=5)
    snapshot["step"] = dict(plan_id=response["plan_id"], step_id=response["step_id"],
        target=deepcopy(blocks[-1]), comparison=response["comparison"],
        observed=dict(response["observation"], check_id=response["check_id"], status=response["status"]))
    snapshot["monitor"]["observation"] = dict(status="OK", check_id=response["check_id"],
        observation_seq=9, reason=None)
    snapshot["inspection"] = {key: deepcopy(response[key]) for key in
        ("check_id", "check_kind", "plan_id", "step_id", "status", "comparison", "expected", "difference", "reason")}
    return snapshot, response


def test_b_five_layer_mismatch_keeps_revision_hidden_layers_and_raw_db_evidence(tmp_path):
    snapshot, response = five_layer_result()
    original = deepcopy((snapshot, response))
    validate_response(response)
    VALIDATOR.validate(snapshot)
    validate_hmi_snapshot(snapshot)
    app = QApplication.instance() or QApplication([])
    window = HmiWindow(screen_size=QSize(1024, 768))
    commands = []
    window.command_requested.connect(commands.append)
    try:
        window.render_snapshot(snapshot)
        window.show()
        app.processEvents()
        assert window.inspection_view.current_board.blocks == response["current"]["blocks"]
        assert window.inspection_view.expected_board.blocks == response["expected"]["blocks"]
        assert "Current r17" in window.inspection_view.summary.text()
        assert window._snapshot["progress"] == dict(completed=4, total=5)
        assert commands == []
        assert window.grab().save(str(tmp_path / "five-layer-mismatch.png"))
    finally:
        window.close()
    document = dict(timestamp="2026-10-11T03:00:00+00:00", job_id=snapshot["actions"]["job_id"],
        plan_id=response["plan_id"], step_id=response["step_id"], request_id=response["check_id"],
        event="CHECK_RESULT", result=dict(response=response, disposition="ACCEPTED", disposition_reason=None), reason=None)
    raw = (json.dumps(document, ensure_ascii=False) + "\n").encode()
    parsed = parse_record(raw, "round1.jsonl", 1, contract=CONTRACT)
    rows = [dict(parsed, occurred_at=parsed["timestamp"], job_id=document["job_id"],
                 event="CHECK_RESULT", source_key="round1.jsonl", line_number=1)]
    assert checks(rows)[0]["response"] == response
    assert parsed["raw"] == raw.decode()
    assert (snapshot, response) == original


def test_ok_cannot_be_displayed_as_unobservable_in_hmi_or_db():
    snapshot, response = five_layer_result()
    snapshot["inspection"]["comparison"] = "UNOBSERVABLE"
    with pytest.raises(ValueError, match="OK cannot"):
        validate_hmi_snapshot(snapshot)
    response["comparison"] = "UNOBSERVABLE"
    with pytest.raises(ValueError, match="comparison"):
        validate_response(response)


@pytest.mark.parametrize("comparison", ["MISMATCH", "UNOBSERVABLE"])
def test_completion_match_cannot_override_b_final_inspection(comparison):
    snapshot = json.loads((ROOT / "interfaces/fixtures/hmi_mvp.json").read_text())["snapshots"]["complete"]
    snapshot["monitor"]["observation"]["check_id"] = "round1-final"
    snapshot["inspection"] = dict(check_id="round1-final", check_kind="FINAL",
        plan_id=snapshot["step"]["plan_id"], step_id=None,
        status="OK" if comparison == "MISMATCH" else "UNOBSERVABLE", comparison=comparison,
        expected=dict(plan_id=snapshot["step"]["plan_id"], step_id=None, blocks=snapshot["current"]["blocks"]),
        difference=dict(missing=[], unexpected=[], unobservable=[]), reason="B final check did not match")
    with pytest.raises(ValueError, match="conflicts with final inspection"):
        validate_hmi_snapshot(snapshot)


def test_b_five_layer_result_round_trip_actual_postgresql(tmp_path):
    from history import accounts, personal, store

    dsn = os.environ.get("HISTORY_TEST_DSN")
    if not dsn:
        pytest.skip("HISTORY_TEST_DSN required for actual PostgreSQL round-trip")
    snapshot, response = five_layer_result()
    job = snapshot["actions"]["job_id"]
    document = dict(timestamp="2026-10-11T03:00:00+00:00", job_id=job,
        plan_id=response["plan_id"], step_id=response["step_id"], request_id=response["check_id"],
        event="CHECK_RESULT", result=dict(response=response, disposition="ACCEPTED", disposition_reason=None), reason=None)
    path = tmp_path / "b-five.jsonl"
    path.write_text(json.dumps(document) + "\n")
    with store.connect(dsn) as connection:
        assert connection.execute("SELECT current_database() AS name").fetchone()["name"].endswith("_test")
        store.initialize(connection)
        with connection.transaction(force_rollback=True):
            account = accounts.create_user(connection, "round1_" + uuid4().hex, "시험 사용자", "fixture-password")
            assert store.ingest(connection, path, "round1/" + job, contract=CONTRACT)["inserted"] == 1
            assert store.ingest(connection, path, "round1/" + job, contract=CONTRACT)["inserted"] == 0
            personal.bind_job(connection, job, account["username"], "fixture owner verified")
            bundle = personal.bundle(connection, job, account["user_id"])
            assert bundle["checks"][0]["response"] == response
            assert bundle["checks"][0]["response"]["current"]["current_revision"] == 17
            receipt = personal.save_job(connection, job, account["user_id"], "save-" + job)
            assert personal.save_job(connection, job, account["user_id"], "save-" + job) == receipt
            result = personal.bundle(connection, job, account["user_id"])
            assert result["storage"]["status"] == "SAVED"
            assert result["storage"]["web_reflection"] == "NOT_CONNECTED"
            assert result["completion"]["assembly"] == "NOT_RECORDED"
