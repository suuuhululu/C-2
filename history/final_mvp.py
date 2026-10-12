"""Offline archive mapping for the 2026-10-08 contract, not a live B/D adapter."""

from copy import deepcopy

from app.completion import _current
from app.contracts import validate_block, validate_observed


CONTRACT = "final-mvp-20261008"


def _object(value, fields, name):
    if not isinstance(value, dict) or not set(fields) <= value.keys():
        raise ValueError(f"{name}: missing object fields {', '.join(fields)}")
    return value


def _text(value, name, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: nonempty text required")


def _blocks(value):
    if not isinstance(value, list):
        raise ValueError("blocks: expected array")
    for block in value:
        validate_block(block)


def validate_event(document):
    name, data = document["event"], document["result"]
    if name == "CHECK_RESULT":
        _object(data, ("response", "disposition", "disposition_reason"), name)
        if data["disposition"] not in ("ACCEPTED", "REJECTED"):
            raise ValueError("CHECK_RESULT.disposition: unsupported value")
        _text(data["disposition_reason"], "disposition_reason", nullable=data["disposition"] == "ACCEPTED")
        validate_response(data["response"])
        for outer, inner in (("request_id", "check_id"), ("plan_id", "plan_id"), ("step_id", "step_id")):
            if document[outer] != data["response"][inner]:
                raise ValueError(f"CHECK_RESULT.{outer}: differs from response.{inner}")
    elif name in ("PLAN_WORK_EXHAUSTED", "ASSEMBLY_COMPLETED"):
        _text(document["plan_id"], f"{name}.plan_id")
        if document["step_id"] is not None:
            raise ValueError(f"{name}.step_id: expected null")
        if name == "ASSEMBLY_COMPLETED":
            _object(data, ("final_check_id", "design_version"), name)
            _text(data["final_check_id"], "final_check_id")
            if type(data["design_version"]) is not int or data["design_version"] < 1:
                raise ValueError("design_version: positive integer required")


def validate_response(response):
    value = _object(response, ("check_id", "check_kind", "plan_id", "step_id", "status",
        "comparison", "current", "expected", "difference", "observation", "reason"), "response")
    _text(value["check_id"], "check_id")
    kind, status = value["check_kind"], value["status"]
    if kind not in ("INITIAL", "STEP", "FINAL") or status not in ("OK", "UNOBSERVABLE", "ERROR", "CANCELED"):
        raise ValueError("response: unsupported check kind or status")
    for field in ("plan_id", "step_id", "reason"):
        _text(value[field], field, nullable=True)
    if status in ("ERROR", "CANCELED"):
        if any(value[field] is not None for field in ("comparison", "current", "expected", "difference", "observation")):
            raise ValueError("error/canceled response: state and comparison must be null")
        _text(value["reason"], "reason")
        return  # Invalid request targets are preserved as diagnostics, not normal data.
    if kind == "INITIAL":
        if any(value[field] is not None for field in ("plan_id", "step_id", "expected", "comparison")):
            raise ValueError("INITIAL: plan, step, expected and comparison must be null")
    else:
        _text(value["plan_id"], "plan_id")
        _text(value["step_id"], "step_id", nullable=kind == "FINAL")
        if kind == "FINAL" and value["step_id"] is not None:
            raise ValueError("FINAL.step_id: expected null")
        expected = _object(value["expected"], ("plan_id", "step_id", "blocks"), "expected")
        if any(expected[field] != value[field] for field in ("plan_id", "step_id")):
            raise ValueError("expected: target differs from response")
        _blocks(expected["blocks"])
        if value["comparison"] not in (("MATCH", "MISMATCH") if status == "OK" else ("UNOBSERVABLE",)):
            raise ValueError("response.comparison: differs from status")
    _current(value["current"])
    difference = _object(value["difference"], ("missing", "unexpected", "unobservable"), "difference")
    for blocks in (difference[field] for field in ("missing", "unexpected", "unobservable")):
        _blocks(blocks)
    observation = _object(value["observation"], ("observation_seq", "visible_blocks", "verified_regions", "reason"), "observation")
    validate_observed(dict(observation, check_id=value["check_id"], status="OK"))
    if status == "UNOBSERVABLE":
        _text(value["reason"], "reason")


def check_conflict(connection, document):
    """Only mutually accepted conflicting responses reject import. Rejections stay raw."""
    if document["result"]["disposition"] != "ACCEPTED":
        return
    rows = connection.execute("""SELECT e.document FROM c2_history.events e
        JOIN c2_history.sources s USING(source_key)
        WHERE e.job_id=%s AND e.request_id=%s AND e.event='CHECK_RESULT'
        AND s.contract=%s AND e.document->'result'->>'disposition'='ACCEPTED'""",
        (document["job_id"], document["request_id"], CONTRACT)).fetchall()
    if any(row["document"]["result"]["response"] != document["result"]["response"] for row in rows):
        raise ValueError("conflicting accepted check result; original retained")


def checks(rows):
    output = []
    for row in rows:
        if row.get("contract") != CONTRACT or row["event"] != "CHECK_RESULT":
            continue
        data = row["document"]["result"]
        output.append(dict(job_id=row["job_id"], occurred_at=row["occurred_at"],
            source_key=row.get("source_key"), line_number=row.get("line_number"), **data))
    return deepcopy(output)


def completion(rows):
    """Link D's recorded conclusion to B evidence; never compare spatial states again."""
    rows = [row for row in rows if row.get("contract") == CONTRACT]
    adopted = {}
    accepted = {}
    exhausted = set()
    conclusion = None
    latest_plan = None
    for row in rows:
        data = row["document"]["result"]
        if row["event"] == "PLAN_ADOPTED":
            adopted[row["plan_id"]] = data["design"]["design_version"]
            if row["plan_id"] != latest_plan:
                conclusion = None  # A new target needs its own D completion record.
            latest_plan = row["plan_id"]
        elif row["event"] == "CHECK_RESULT" and data["disposition"] == "ACCEPTED":
            accepted[row["request_id"]] = data["response"]
        elif row["event"] == "PLAN_WORK_EXHAUSTED":
            exhausted.add(row["plan_id"])
        elif row["event"] == "ASSEMBLY_COMPLETED":
            final = accepted.get(data["final_check_id"], {})
            linked = (final.get("check_kind") == "FINAL" and final.get("status") == "OK"
                and final.get("comparison") == "MATCH" and final.get("plan_id") == row["plan_id"]
                and adopted.get(row["plan_id"]) == data["design_version"]
                and row["plan_id"] == latest_plan
                and row["plan_id"] in exhausted)
            conclusion = dict(recorded_at=row["occurred_at"], plan_id=row["plan_id"],
                final_check_id=data["final_check_id"], evidence_linked=linked)
    return dict(work_exhaustion="RECORDED" if latest_plan in exhausted else "NOT_RECORDED",
        assembly="RECORDED" if conclusion and conclusion["evidence_linked"] else
            "UNVERIFIED_RECORD" if conclusion else "NOT_RECORDED",
        assembly_evidence=conclusion, web_reflection="NOT_CONNECTED")
