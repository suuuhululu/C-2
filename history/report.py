"""Evidence-based summaries; missing endpoints remain unknown (None)."""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime


def _time(row):
    value = row["occurred_at"]
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _request(row):
    result = row["document"]["result"]
    return result if row["event"] == "REQUEST_SENT" and isinstance(result, dict) else {}


def _issue(row, request_ports):
    event, result, reason = row["event"], row["document"]["result"], row["reason"]
    if row.get("contract") == "final-mvp-20261008":
        if event == "CHECK_RESULT" and result["disposition"] == "ACCEPTED":
            response = result["response"]
            if response["status"] == "ERROR":
                return "CHECK_ERROR", response["reason"]
            if response["status"] == "UNOBSERVABLE":
                return "UNOBSERVABLE", response["reason"]
        if event == "INTENT_RECEIVED" and result.get("decision") == "REVISE":
            return "DESIGN_CHANGE_WAIT", "WAIT_APPROVED_DESIGN_PLAN"
    if event == "OBSERVATION_HOLD":
        return "UNOBSERVABLE", reason
    if event == "PLACE_STATUS_CHANGED" and result == "UNOBSERVABLE":
        return "UNOBSERVABLE", reason
    if event == "DELIVERY_RESULT" and isinstance(result, dict) and result.get("success") is False:
        return "ROBOT_FAILURE", result["reason"]
    if event == "CALL_FAILED":
        port = request_ports.get((row["job_id"], row["request_id"]), "")
        return ("ROBOT_FAILURE" if port.startswith("robot.") else "MODULE_FAILURE"), reason
    if event == "PLAN_RESULT" and isinstance(result, dict) and result.get("status") == "INVALID":
        reasons = "; ".join(error["reason"] for error in result.get("errors", []))
        return "PLAN_ERROR", reasons or reason
    if _request(row).get("port") == "hri":
        return "INTENT_WAIT", "WAIT_INTENT"
    if event == "CORRECTION_REQUIRED":
        return "CORRECTION_WAIT", reason
    if event == "SUPPLY_WAIT":
        return "SUPPLY_WAIT", reason
    if event == "STOP_STATUS":
        return "STOP_WAIT", reason
    return None


def episodes(rows: list[dict]) -> list[dict]:
    """Repeated evidence for one active condition is one episode, until explicit release."""
    active, output, request_ports = {}, [], {}
    for row in rows:
        job = row["job_id"]
        event = row["event"]
        request = _request(row)
        if request.get("port"):
            request_ports[(job,row["request_id"])] = request["port"]
        close = set()
        if event == "STEP_CONFIRMED":
            close.add("UNOBSERVABLE")
        if event == "STEP_CONFIRMED":
            close.add("ASSEMBLY_WAIT")
        if event == "INTENT_RECEIVED" and row["document"]["result"].get("decision") in ("KEEP", "REVISE"):
            close.add("INTENT_WAIT")
        if event == "PLAN_ADOPTED":
            close.update(("INTENT_WAIT", "CORRECTION_WAIT", "PLAN_ERROR", "DESIGN_CHANGE_WAIT"))
        if row.get("contract") == "final-mvp-20261008" and event == "CHECK_RESULT":
            data = row["document"]["result"]
            response = data["response"]
            if data["disposition"] == "ACCEPTED" and response["status"] == "OK" and not response["difference"]["unobservable"]:
                for category in ("UNOBSERVABLE", "CHECK_ERROR"):
                    key = (job, category, "ASSEMBLY")
                    if key in active and (active[key]["plan_id"], active[key]["step_id"]) == (row["plan_id"], row["step_id"]):
                        _end(active.pop(key), row)
        if event == "SUPPLY_REFILLED":
            close.add("SUPPLY_WAIT")
        if event == "PLACE_STATUS_CHANGED" and row["document"]["result"] in ("EMPTY", "OCCUPIED"):
            # A place-board observation only releases its own place-board hold.
            key = (job, "UNOBSERVABLE", "PLACE")
            if key in active:
                _end(active.pop(key), row)
        if event == "ROBOT_CLEANUP_CONFIRMED":
            close.add("ROBOT_FAILURE")
        if request.get("port") == "robot.resume":
            close.add("STOP_WAIT")
        if event == "JOB_COMPLETED":
            close.update(key[1] for key in active if key[0] == job)
        for key in list(active):
            if key[0] == job and key[1] in close and not (key[1] == "UNOBSERVABLE" and key[2] == "PLACE" and event != "JOB_COMPLETED"):
                _end(active.pop(key), row)
        result = row["document"]["result"]
        issue = _issue(row, request_ports)
        if event == "DELIVERY_RESULT" and isinstance(result, dict) and result.get("success") is True:
            issue = ("ASSEMBLY_WAIT", "DELIVERED_AWAITING_ASSEMBLY") if row["step_id"] is not None else None
        if issue is None:
            continue
        category, reason = issue
        scope = "PLACE" if event == "PLACE_STATUS_CHANGED" else "ASSEMBLY"
        key = (job, category, scope)
        identity = (reason, row["plan_id"], row["step_id"])
        if key in active and active[key]["identity"] == identity:
            active[key]["evidence_count"] += 1
            continue
        if key in active:
            # A changed reason proves a new condition, not the prior condition's recovery.
            active.pop(key)
        item = dict(job_id=job, category=category, reason=reason, scope=scope,
                    plan_id=row["plan_id"], step_id=row["step_id"], started_at=_time(row),
                    ended_at=None, duration_seconds=None, evidence_count=1, identity=identity)
        active[key] = item
        output.append(item)
    return [{key: value for key,value in item.items() if key != "identity"} for item in output]


def _end(item, row):
    end = _time(row)
    if end >= item["started_at"]:
        item.update(ended_at=end, duration_seconds=(end-item["started_at"]).total_seconds())


def reason_counts(rows: list[dict]) -> list[dict]:
    counts = Counter((item["category"], item["reason"]) for item in episodes(rows))
    return [dict(category=category, reason=reason, episodes=count)
            for (category,reason),count in sorted(counts.items(), key=lambda pair: (pair[0][0], pair[0][1] or ""))]


def jobs(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["job_id"]].append(row)
    output = []
    for job_id, events in groups.items():
        from history.final_mvp import CONTRACT, completion
        final_mvp = any(row.get("contract") == CONTRACT for row in events)
        stages = completion(events) if final_mvp else None
        starts = [row for row in events if row["event"] == "JOB_STARTED"]
        ends = [row for row in events if row["event"] == "JOB_COMPLETED"] if not final_mvp else []
        start, end = (_time(starts[0]) if starts else None), (_time(ends[-1]) if ends else None)
        if stages and stages["assembly"] == "RECORDED":
            end = stages["assembly_evidence"]["recorded_at"]
            end = end if isinstance(end, datetime) else datetime.fromisoformat(end)
        issues = episodes(events)
        unresolved = [item for item in issues if item["ended_at"] is None]
        output.append(dict(job_id=job_id, started_at=start, ended_at=end,
                           result="COMPLETE" if end else "NO_COMPLETION_RECORDED",
                           duration_seconds=(end-start).total_seconds() if start and end and end >= start else None,
                           last_event=events[-1]["event"], last_seen_at=_time(events[-1]),
                           event_count=len(events), unresolved_conditions=unresolved,
                           completion=stages))
    return output


def durations(rows: list[dict]) -> list[dict]:
    pending, output = {}, []
    for row in rows:
        request = _request(row)
        if request.get("port") in ("robot.deliver", "robot.resume"):
            pending.setdefault((row["job_id"],row["request_id"]), row)
        elif row["event"] == "DELIVERY_RESULT":
            key = (row["job_id"],row["request_id"])
            start = pending.pop(key, None)
            delta = (_time(row)-_time(start)).total_seconds() if start else None
            output.append(dict(kind="ROBOT_REQUEST_TO_RESULT", job_id=row["job_id"],
                               plan_id=row["plan_id"], step_id=row["step_id"], request_id=row["request_id"],
                               duration_seconds=delta if delta is not None and delta >= 0 else None))
    for (job,request), row in pending.items():
        output.append(dict(kind="ROBOT_REQUEST_TO_RESULT", job_id=job, plan_id=row["plan_id"],
                           step_id=row["step_id"], request_id=request, duration_seconds=None))
    return output


def _evidence(row):
    return dict(occurred_at=_time(row), source_key=row.get("source_key"),
                line_number=row.get("line_number"))


def designs(rows: list[dict]) -> list[dict]:
    """Only jointly adopted Design/Plan contexts are library entries, never candidates."""
    output = {}
    for row in rows:
        if row["event"] != "PLAN_ADOPTED":
            continue
        design = row["document"]["result"]["design"]
        key = (row["job_id"], design["design_version"])
        if key not in output:
            output[key] = dict(job_id=key[0], design_version=key[1],
                               adopted_at=_time(row), design=design, adoptions=[])
        output[key]["adoptions"].append(dict(**_evidence(row), plan_id=row["plan_id"],
                                             request_id=row["request_id"]))
    return deepcopy(list(output.values()))


def currents(rows: list[dict]) -> list[dict]:
    """Basis snapshots and observation adoptions remain distinct evidence, even at one revision."""
    output = []
    for row in rows:
        data = row["document"]["result"]
        if row["event"] == "PLAN_ADOPTED":
            current, observed, kind = data["base_current"], None, "PLAN_BASIS"
        elif row["event"] == "CURRENT_ADOPTED" and row.get("contract") != "final-mvp-20261008":
            current, observed, kind = data["current"], data["observed"], "OBSERVATION_ADOPTED"
        elif row.get("contract") == "final-mvp-20261008" and row["event"] == "CHECK_RESULT":
            response = data["response"]
            if data["disposition"] != "ACCEPTED" or response["current"] is None:
                continue
            current, observed, kind = response["current"], response["observation"], "B_CONFIRMED"
        else:
            continue
        output.append(dict(**_evidence(row), job_id=row["job_id"], plan_id=row["plan_id"],
                           step_id=row["step_id"], kind=kind,
                           current_revision=current["current_revision"], current=current,
                           check_id=(row["request_id"] if kind == "B_CONFIRMED" else observed["check_id"]) if observed else None,
                           observation_seq=observed["observation_seq"] if observed else None,
                           observed=observed))
    return deepcopy(output)


def plans(rows: list[dict]) -> list[dict]:
    """Last adopted is a history fact, not a claim about live Backend activity."""
    output, last = {}, {}
    for row in rows:
        if row["event"] != "PLAN_ADOPTED":
            continue
        context = row["document"]["result"]
        job, plan = row["job_id"], context["plan"]
        key = (job, plan["plan_id"])
        previous = last.get(job)
        if previous is not None and previous != key:
            output[previous].update(is_last_adopted=False, superseded_at=_time(row),
                                    superseded_by=plan["plan_id"])
        if key not in output:
            output[key] = dict(job_id=job, plan_id=plan["plan_id"],
                design_version=plan["design_version"], base_current_revision=plan["base_current_revision"],
                adopted_at=_time(row), plan=plan, base_current=context["base_current"], adoptions=[])
        output[key].update(is_last_adopted=True, superseded_at=None, superseded_by=None)
        output[key]["adoptions"].append(dict(**_evidence(row), request_id=row["request_id"]))
        last[job] = key
    return deepcopy(list(output.values()))


def hri(rows: list[dict]) -> list[dict]:
    """Join by Job/request only. A new question without a context keeps its basis unknown."""
    output = {}
    for row in rows:
        event, data = row["event"], row["document"]["result"]
        request = _request(row)
        key = (row["job_id"], row["request_id"])
        relevant = request.get("port") == "hri" or event in (
            "QUESTION_OPENED", "QUESTION_RECEIVED", "C_INTERVENTION_RESULT", "INTENT_RECEIVED")
        if not relevant and not (event == "CALL_FAILED" and key in output):
            continue
        if key not in output:
            output[key] = dict(job_id=key[0], request_id=key[1], first_recorded_at=_time(row),
                design_version=None, current_revision=None, design=None, current=None, difference=None,
                requests=[], questions=[], c_responses=[], intents=[], failures=[])
        item, evidence = output[key], _evidence(row)
        if request.get("port") == "hri":
            payload = request["payload"]
            if not item["requests"]:
                item.update(design_version=payload.get("design_version"),
                    current_revision=payload.get("current_revision"), design=payload.get("design"),
                    current=payload.get("current"), difference=payload.get("difference"))
            item["requests"].append(dict(**evidence, payload=payload))
        elif event in ("QUESTION_OPENED", "QUESTION_RECEIVED"):
            item["questions"].append(dict(**evidence, question=data))
        elif event == "C_INTERVENTION_RESULT":
            item["c_responses"].append(dict(**evidence, response=data))
        elif event == "INTENT_RECEIVED":
            item["intents"].append(dict(**evidence, intent=data))
        else:
            item["failures"].append(dict(**evidence, reason=row["reason"]))
    for item in output.values():
        item["record_status"] = ("INTENT_RECORDED" if item["intents"] else
            "C_RESPONSE_RECORDED" if item["c_responses"] else
            "FAILURE_RECORDED" if item["failures"] else "NO_RESPONSE_RECORDED")
    return deepcopy(list(output.values()))
