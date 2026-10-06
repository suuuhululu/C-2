"""Parse existing Backend logs without inventing producer fields."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from uuid import UUID

from app.completion import _current, freeze_plan_basis
from app.contracts import validate_block, validate_design, validate_observed, validate_plan_result


class InputError(ValueError):
    pass


def _text(value, field, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError(f"{field}: expected nonempty text")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def parse_record(raw: bytes, source: str, line: int) -> dict:
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                              parse_constant=_constant)
        if not isinstance(document, dict):
            raise ValueError("record: expected object")
        for key in ("timestamp", "job_id", "plan_id", "step_id", "request_id", "event", "result", "reason"):
            if key not in document:
                raise ValueError(f"missing field: {key}")
        for key in ("timestamp", "job_id", "event"):
            _text(document[key], key)
        if str(UUID(document["job_id"])) != document["job_id"]:
            raise ValueError("job_id: expected canonical UUID")
        timestamp = datetime.fromisoformat(document["timestamp"])
        if timestamp.utcoffset() is None:
            raise ValueError("timestamp: timezone required")
        for key in ("plan_id", "step_id", "request_id", "reason"):
            _text(document[key], key, nullable=True)
        # PostgreSQL JSONB cannot represent NUL or nonfinite numbers anywhere.
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False)
        if "\\u0000" in encoded or "\0" in encoded:
            raise ValueError("JSON contains NUL")
        _validate_event_result(document)
        if document["event"] == "PLAN_ADOPTED":
            context = document["result"]
            if not isinstance(context, dict) or "confirmed_steps" not in context:
                raise ValueError("PLAN_ADOPTED.result: expected adoption context")
            if not isinstance(context["confirmed_steps"], list):
                raise ValueError("PLAN_ADOPTED.result.confirmed_steps: expected array")
            freeze_plan_basis(context.get("design"), context.get("plan"), context.get("base_current"))
            if document["plan_id"] != context["plan"]["plan_id"]:
                raise ValueError("PLAN_ADOPTED.plan_id: differs from result.plan")
        metadata = event_fields(document)
        return dict(source=source, line=line, timestamp=timestamp, document=document,
                    raw=raw.decode("utf-8"), digest=hashlib.sha256(raw).hexdigest(), **metadata)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise InputError(f"{source}:{line}: {error}") from error



def _validate_event_result(document):
    name, result = document["event"], document["result"]
    consumed = ("REQUEST_SENT", "DELIVERY_RESULT", "INTENT_RECEIVED", "PLAN_RESULT",
                "CURRENT_ADOPTED", "INITIAL_DESIGN_RECEIVED", "C_INTERVENTION_RESULT",
                "QUESTION_OPENED", "QUESTION_RECEIVED")
    if name not in consumed:
        return
    if name in ("QUESTION_OPENED", "QUESTION_RECEIVED"):
        _text(result, f"{name}.result")
        _text(document["request_id"], f"{name}.request_id")
        return
    if not isinstance(result, dict):
        raise ValueError(f"{name}.result: expected object")
    if name == "REQUEST_SENT":
        _text(result.get("port"), "REQUEST_SENT.result.port")
        if not isinstance(result.get("payload"), dict):
            raise ValueError("REQUEST_SENT.result.payload: expected object")
        if result["port"] == "hri":
            _text(document["request_id"], "REQUEST_SENT.request_id")
            _validate_hri_payload(result["payload"], document)
    elif name == "DELIVERY_RESULT":
        if type(result.get("success")) is not bool:
            raise ValueError("DELIVERY_RESULT.result.success: expected boolean")
        if "reason" not in result:
            raise ValueError("DELIVERY_RESULT.result.reason: missing field")
        _text(result["reason"], "DELIVERY_RESULT.result.reason", nullable=result["success"])
    elif name == "INTENT_RECEIVED":
        if result.get("decision") not in ("KEEP", "REVISE", "UNCLEAR"):
            raise ValueError("INTENT_RECEIVED.result.decision: unsupported decision")
        _text(document["request_id"], "INTENT_RECEIVED.request_id")
        if "request_id" in result and result["request_id"] != document["request_id"]:
            raise ValueError("INTENT_RECEIVED.request_id: differs from result.request_id")
        if result["decision"] == "REVISE":
            validate_design(result.get("design"))
        elif result["decision"] == "UNCLEAR":
            _text(result.get("question"), "INTENT_RECEIVED.result.question")
    elif name == "PLAN_RESULT" and result.get("status") == "INVALID":
        errors = result.get("errors")
        if not isinstance(errors, list) or not errors:
            raise ValueError("PLAN_RESULT.result.errors: expected nonempty list for INVALID")
        for error in errors:
            if not isinstance(error, dict):
                raise ValueError("PLAN_RESULT.result.errors: expected error object")
            _text(error.get("reason"), "PLAN_RESULT.result.errors.reason")
    if name == "PLAN_RESULT":
        validate_plan_result(result)
    elif name == "CURRENT_ADOPTED":
        _current(result.get("current"))
        observed = validate_observed(result.get("observed"))
        if document["request_id"] != observed["check_id"]:
            raise ValueError("CURRENT_ADOPTED.request_id: differs from observed.check_id")
    elif name in ("INITIAL_DESIGN_RECEIVED", "C_INTERVENTION_RESULT"):
        _validate_c_result(result, intervention=name == "C_INTERVENTION_RESULT")
        if name == "C_INTERVENTION_RESULT":
            _text(document["request_id"], "C_INTERVENTION_RESULT.request_id")


def _validate_hri_payload(payload, document):
    # Older logs can omit context fields. Present fields must be usable, not guessed.
    for field in ("job_id", "request_id"):
        if field in payload and payload[field] != document[field]:
            raise ValueError(f"REQUEST_SENT.payload.{field}: differs from event")
    for field, minimum in (("design_version", 1), ("current_revision", 0)):
        if field in payload and (type(payload[field]) is not int or payload[field] < minimum):
            raise ValueError(f"REQUEST_SENT.payload.{field}: expected integer >= {minimum}")
    for field, validate in (("design", validate_design), ("current", _current)):
        if field in payload:
            validate(payload[field])
    for field, nested in (("design_version", "design"), ("current_revision", "current")):
        if field in payload and nested in payload and payload[field] != payload[nested][field]:
            raise ValueError(f"REQUEST_SENT.payload.{field}: differs from {nested}")
    if "difference" in payload:
        difference = payload["difference"]
        if not isinstance(difference, dict):
            raise ValueError("REQUEST_SENT.payload.difference: expected object")
        for field in ("missing", "unexpected", "unobservable"):
            if not isinstance(difference.get(field), list):
                raise ValueError(f"REQUEST_SENT.payload.difference.{field}: expected array")
            for block in difference[field]:
                validate_block(block)


def _validate_c_result(result, *, intervention):
    if result.get("status") not in ("OK", "FAILED", "CANCELLED"):
        raise ValueError("C result.status: unsupported status")
    if "questions" in result:
        if not isinstance(result["questions"], list):
            raise ValueError("C result.questions: expected array")
        for question in result["questions"]:
            _text(question, "C result.questions[]")
    decision = result.get("hri_result")
    if decision not in (None, "KEEP", "REVISE", "UNCLEAR"):
        raise ValueError("C result.hri_result: unsupported decision")
    if result["status"] == "OK":
        if result.get("error") is not None:
            raise ValueError("C result.error: OK requires null")
        if not intervention and decision is not None:
            raise ValueError("C result.hri_result: Initial requires null")
        if intervention and decision is None:
            raise ValueError("C result.hri_result: Intervention requires a decision")
        if not intervention or decision in ("KEEP", "REVISE"):
            # C responses are candidates. Preserve invalid placements for A/D diagnostics;
            # only PLAN_ADOPTED/INTENT_RECEIVED documents get the accepted-data contract.
            candidate = result.get("design")
            if not isinstance(candidate, dict) or not isinstance(candidate.get("blocks"), list):
                raise ValueError("C result.design: expected candidate object with blocks array")
            version = candidate.get("design_version")
            if type(version) is not int or version < 1:
                raise ValueError("C result.design.design_version: expected positive integer")
        elif not result.get("questions"):
            raise ValueError("C result.questions: UNCLEAR requires a question")
    else:
        error = result.get("error")
        if not isinstance(error, dict):
            raise ValueError("C result.error: failure requires an object")
        _text(error.get("code"), "C result.error.code")
        _text(error.get("message"), "C result.error.message")
        if not isinstance(error.get("details"), list):
            raise ValueError("C result.error.details: expected array")


def event_fields(document: dict) -> dict:
    result = document["result"]
    data = result if isinstance(result, dict) else {}
    basis = data.get("plan") if document["event"] == "PLAN_ADOPTED" else data
    if document["event"] == "REQUEST_SENT":
        basis = data.get("payload", {})
    basis = basis if isinstance(basis, dict) else {}
    observed = data.get("observed", data)
    observed = observed if isinstance(observed, dict) else {}
    outcome = data.get("status")
    if type(data.get("success")) is bool:
        outcome = "SUCCESS" if data["success"] else "FAILURE"
    if isinstance(result, str):
        outcome = result
    return dict(design_version=basis.get("design_version"),
                base_current_revision=basis.get("base_current_revision"),
                observation_seq=observed.get("observation_seq"),
                outcome=outcome if isinstance(outcome, str) else None)


def read_source(path: Path, source: str) -> tuple[list[dict], int | None]:
    """Read a bounded snapshot; defer any last line without a newline, even valid JSON."""
    _text(source, "source")
    records, pending = [], None
    with path.open("rb") as stream:
        stream.seek(0, 2)
        remaining = stream.tell()
        stream.seek(0)
        line = 0
        while remaining:
            raw = stream.readline(remaining)
            if not raw:
                raise InputError(f"{source}:{line + 1}: file truncated while reading")
            remaining -= len(raw)
            line += 1
            if not raw.endswith(b"\n"):
                pending = line
                break
            records.append(parse_record(raw, source, line))
    return records, pending


def adopted_artifacts(record: dict) -> list[dict]:
    document = record["document"]
    if document["event"] != "PLAN_ADOPTED":
        return []
    context = document["result"]
    plan, design = context["plan"], context["design"]
    common = dict(job_id=document["job_id"], design_version=design["design_version"])
    return [dict(**common, kind="DESIGN", key=str(design["design_version"]),
                 plan_id=None, base_current_revision=None, document=design),
            dict(**common, kind="PLAN", key=plan["plan_id"], plan_id=plan["plan_id"],
                 base_current_revision=plan["base_current_revision"], document=plan),
            dict(**common, kind="BASE_CURRENT", key=plan["plan_id"], plan_id=plan["plan_id"],
                 base_current_revision=plan["base_current_revision"], document=context["base_current"])]
