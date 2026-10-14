"""Operational history selection; detailed sensor samples remain in the raw archive."""

import re


PROFILES = ("all", "operational-v1")
DIAGNOSTIC_EVENTS = ("ROBOT_CAMERA_CANDIDATE", "ROBOT_MOTION_SAMPLE")
FAILURE_STATUSES = ("ERROR", "FAILED", "REJECTED", "STOPPED")


def should_store(document: dict) -> bool:
    """Keep unknown events and explicit failures, excluding only routine diagnostics."""
    if document["event"] not in DIAGNOSTIC_EVENTS or document.get("reason") is not None:
        return True
    result = document["result"]
    if not isinstance(result, dict):
        return True
    if (result.get("error") is not None or result.get("success") is False
            or result.get("status") in FAILURE_STATUSES):
        return True
    # Camera result.reason describes ordinary frame eligibility, not a workflow failure.
    return (document["event"] == "ROBOT_CAMERA_CANDIDATE"
            and result.get("candidate_event") is not None)


def sql_condition(alias: str = "e") -> tuple[str, tuple]:
    """Equivalent operational selection for SQL reads before loading large JSON payloads."""
    if not isinstance(alias, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias) is None:
        raise ValueError("history selection: expected SQL table alias")
    result = f"{alias}.document->'result'"
    condition = f"""(
        NOT ({alias}.event = ANY(%s))
        OR {alias}.reason IS NOT NULL
        OR jsonb_typeof({result}) IS DISTINCT FROM 'object'
        OR COALESCE({result}->'error', 'null'::jsonb) <> 'null'::jsonb
        OR {result}->'success' = 'false'::jsonb
        OR {result}->>'status' = ANY(%s)
        OR ({alias}.event = %s
            AND COALESCE({result}->'candidate_event', 'null'::jsonb) <> 'null'::jsonb)
    )"""
    return condition, (list(DIAGNOSTIC_EVENTS), list(FAILURE_STATUSES), "ROBOT_CAMERA_CANDIDATE")
