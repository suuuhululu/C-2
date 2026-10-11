"""최종 MVP 표시 확장 검사. 상태 채택·실행 승인·장치 호출은 하지 않는다."""

from .contracts import _block, _blocks, _object, _text, validate_design


MVP_FIELDS = ("design_preview", "dialogue", "execution", "assistance", "completion", "inspection", "user_requests")
USER_REQUESTS = dict(change_design="REQUEST_DESIGN_CHANGE", home="REQUEST_HOME", assistance_ready="ASSISTANCE_READY")


def _choice(value, allowed, path):
    if value not in allowed:
        raise ValueError(f"{path}: unsupported value")


def _nullable_text(value, path):
    if value is not None:
        _text(value, path)


def _step_binding(value, snapshot, path):
    for key in ("plan_id", "step_id"):
        _text(value[key], f"{path}.{key}")
        if value[key] != snapshot["step"][key]:
            raise ValueError(f"{path}.{key}: differs from displayed Step")


def validate_mvp_fields(snapshot):
    """기존 필수 snapshot 검사 후 호출한다. 생략한 확장은 추정하지 않는다."""
    if "design_preview" in snapshot:
        preview = _object(snapshot["design_preview"], ("request_id", "design"), "snapshot.design_preview")
        _text(preview["request_id"], "snapshot.design_preview.request_id")
        validate_design(preview["design"])
    if "dialogue" in snapshot:
        dialogue = _object(snapshot["dialogue"],
            ("request_id", "phase", "user_text", "assistant_text", "reason"), "snapshot.dialogue")
        _text(dialogue["request_id"], "snapshot.dialogue.request_id")
        _choice(dialogue["phase"], ("LISTENING", "GENERATING", "SPEAKING", "REVIEW", "WAIT_APPROVAL", "FAILED"),
                "snapshot.dialogue.phase")
        for key in ("user_text", "assistant_text", "reason"):
            _nullable_text(dialogue[key], f"snapshot.dialogue.{key}")
        if dialogue["phase"] == "FAILED":
            _text(dialogue["reason"], "snapshot.dialogue.reason")
        if "design_preview" in snapshot and snapshot["design_preview"]["request_id"] != dialogue["request_id"]:
            raise ValueError("snapshot.design_preview.request_id: differs from dialogue")
    if "execution" in snapshot:
        execution = _object(snapshot["execution"],
            ("plan_id", "step_id", "motion_plan_id", "method", "phase"), "snapshot.execution")
        _step_binding(execution, snapshot, "snapshot.execution")
        _nullable_text(execution["motion_plan_id"], "snapshot.execution.motion_plan_id")
        _choice(execution["method"], ("ROBOT_GRIP", "HUMAN_ASSEMBLY"), "snapshot.execution.method")
        _choice(execution["phase"], ("APPROACH_PICK", "PICK_AND_CONFIRM", "TRANSPORT_HOLDING", "PRE_CONTACT",
            "CONTACT", "RELEASE", "RETREAT", "WAIT_INSPECTION", "HOLD"), "snapshot.execution.phase")
        if execution["method"] == "HUMAN_ASSEMBLY" and execution["phase"] == "CONTACT":
            raise ValueError("snapshot.execution: human assembly is not Robot Contact")
    if "assistance" in snapshot:
        assistance = _object(snapshot["assistance"],
            ("request_id", "plan_id", "step_id", "kind", "target", "instruction", "phase"), "snapshot.assistance")
        _step_binding(assistance, snapshot, "snapshot.assistance")
        _text(assistance["request_id"], "snapshot.assistance.request_id")
        _text(assistance["instruction"], "snapshot.assistance.instruction")
        _block(assistance["target"], "snapshot.assistance.target")
        _choice(assistance["kind"], ("SUPPORT", "HANDOVER", "HUMAN_ASSEMBLY"), "snapshot.assistance.kind")
        _choice(assistance["phase"], ("REQUESTED", "READY", "MAINTAIN", "RELEASED", "CANCELED"),
                "snapshot.assistance.phase")
        if assistance["phase"] in ("REQUESTED", "READY", "MAINTAIN"):
            if assistance["request_id"] != snapshot["notice"]["request_id"]:
                raise ValueError("snapshot.assistance.request_id: differs from active notice")
    if "completion" in snapshot:
        _completion(snapshot)
    if "inspection" in snapshot:
        _inspection(snapshot)
    if "user_requests" in snapshot:
        _user_requests(snapshot)


def validate_user_request(value):
    request = _object(value, ("command", "job_id", "request_id"), "user_request")
    _choice(request["command"], tuple(USER_REQUESTS.values()), "user_request.command")
    for key in ("job_id", "request_id"):
        _text(request[key], f"user_request.{key}")
    return dict(request)


def validate_user_reply(value):
    reply = _object(value, ("command", "job_id", "request_id", "accepted", "reason"), "user_reply")
    validate_user_request({key: reply[key] for key in ("command", "job_id", "request_id")})
    if type(reply["accepted"]) is not bool:
        raise ValueError("user_reply.accepted: expected boolean")
    _nullable_text(reply["reason"], "user_reply.reason")
    if not reply["accepted"]:
        _text(reply["reason"], "user_reply.reason")
    return dict(reply)


def _user_requests(snapshot):
    requests = _object(snapshot["user_requests"], tuple(USER_REQUESTS), "snapshot.user_requests")
    for name, value in requests.items():
        control = _object(value, ("visible", "enabled", "request_id"), f"snapshot.user_requests.{name}")
        if any(type(control[key]) is not bool for key in ("visible", "enabled")):
            raise ValueError("snapshot.user_requests: expected boolean controls")
        _nullable_text(control["request_id"], "snapshot.user_requests.request_id")
        if control["enabled"] and not control["visible"]:
            raise ValueError("snapshot.user_requests: hidden request cannot be enabled")
        if control["visible"] and (snapshot["actions"]["job_id"] is None or control["request_id"] is None):
            raise ValueError("snapshot.user_requests: visible request requires Job/request")
    if requests["home"]["enabled"]:
        if (snapshot["monitor"]["robot"]["status"] not in ("IDLE", "STOPPED") or
                snapshot["workflow_status"] not in ("IDLE", "HOLD", "STOPPED", "COMPLETE")):
            raise ValueError("snapshot.user_requests.home: motion/stop confirmation is pending")
    if requests["assistance_ready"]["enabled"]:
        help_request = snapshot.get("assistance")
        if (not help_request or help_request["phase"] != "REQUESTED" or
                help_request["request_id"] != requests["assistance_ready"]["request_id"] or
                snapshot["monitor"]["robot"]["status"] != "IDLE" or
                snapshot["workflow_status"] in ("HOLD", "STOPPED", "REPLANNING")):
            raise ValueError("snapshot.user_requests.assistance_ready: requires current ready request")
        if help_request["kind"] == "SUPPORT" and snapshot.get("execution", {}).get("phase") != "PRE_CONTACT":
            raise ValueError("snapshot.user_requests.assistance_ready: support requires pre-contact")


def _inspection(snapshot):
    result = _object(snapshot["inspection"], ("check_id", "check_kind", "plan_id", "step_id", "status",
        "comparison", "expected", "difference", "reason"), "snapshot.inspection")
    _text(result["check_id"], "snapshot.inspection.check_id")
    _choice(result["check_kind"], ("INITIAL", "STEP", "FINAL"), "snapshot.inspection.check_kind")
    _choice(result["status"], ("OK", "UNOBSERVABLE", "ERROR", "CANCELED"), "snapshot.inspection.status")
    for key in ("plan_id", "step_id", "reason"):
        _nullable_text(result[key], f"snapshot.inspection.{key}")
    if result["check_id"] != snapshot["monitor"]["observation"]["check_id"]:
        raise ValueError("snapshot.inspection.check_id: differs from displayed check")
    if result["check_kind"] == "INITIAL":
        if result["plan_id"] is not None or result["step_id"] is not None:
            raise ValueError("snapshot.inspection: INITIAL requires null Plan/Step")
    else:
        _text(result["plan_id"], "snapshot.inspection.plan_id")
        if result["plan_id"] != snapshot["step"]["plan_id"]:
            raise ValueError("snapshot.inspection.plan_id: differs from displayed Plan")
        if result["check_kind"] == "STEP":
            _step_binding(result, snapshot, "snapshot.inspection")
        elif result["step_id"] is not None:
            raise ValueError("snapshot.inspection: FINAL requires null Step")
    if result["status"] in ("ERROR", "CANCELED"):
        if any(result[key] is not None for key in ("comparison", "expected", "difference")):
            raise ValueError("snapshot.inspection: failed/canceled check has no normal result")
        _text(result["reason"], "snapshot.inspection.reason")
        return
    comparison = result["comparison"]
    _choice(comparison, (None,) if result["check_kind"] == "INITIAL" else ("MATCH", "MISMATCH", "UNOBSERVABLE"),
            "snapshot.inspection.comparison")
    if result["status"] == "UNOBSERVABLE":
        if comparison != (None if result["check_kind"] == "INITIAL" else "UNOBSERVABLE"):
            raise ValueError("snapshot.inspection: unobservable check requires UNOBSERVABLE")
        _text(result["reason"], "snapshot.inspection.reason")
    elif comparison == "UNOBSERVABLE":
        raise ValueError("snapshot.inspection: OK cannot report UNOBSERVABLE comparison")
    if result["check_kind"] == "STEP" and comparison != snapshot["step"]["comparison"]:
        raise ValueError("snapshot.inspection.comparison: differs from displayed Step")
    expected = result["expected"]
    if result["check_kind"] == "INITIAL":
        if expected is not None:
            raise ValueError("snapshot.inspection.expected: INITIAL has no Plan expected")
    else:
        expected = _object(expected, ("plan_id", "step_id", "blocks"), "snapshot.inspection.expected")
        if any(expected[key] != result[key] for key in ("plan_id", "step_id")):
            raise ValueError("snapshot.inspection.expected: differs from check Plan/Step")
        _blocks(expected["blocks"], "snapshot.inspection.expected.blocks")
    difference = _object(result["difference"], ("missing", "unexpected", "unobservable"), "snapshot.inspection.difference")
    for key in difference:
        _blocks(difference[key], f"snapshot.inspection.difference.{key}")
    if comparison == "MATCH" and (difference["missing"] or difference["unexpected"]):
        raise ValueError("snapshot.inspection: MATCH conflicts with confirmed differences")


def _completion(snapshot):
    completion = _object(snapshot["completion"],
        ("blocks_used", "assembly", "storage", "web", "reason"), "snapshot.completion")
    if type(completion["blocks_used"]) is not bool:
        raise ValueError("snapshot.completion.blocks_used: expected boolean")
    _choice(completion["assembly"], ("PENDING", "MATCH", "MISMATCH", "UNOBSERVABLE"), "snapshot.completion.assembly")
    for key in ("storage", "web"):
        _choice(completion[key], ("NOT_STARTED", "PENDING", "SUCCEEDED", "FAILED"), f"snapshot.completion.{key}")
    _nullable_text(completion["reason"], "snapshot.completion.reason")
    if completion["assembly"] != "PENDING" and not completion["blocks_used"]:
        raise ValueError("snapshot.completion: final inspection requires blocks used")
    if completion["assembly"] == "MATCH" and snapshot["progress"]["completed"] != snapshot["progress"]["total"]:
        raise ValueError("snapshot.completion: final MATCH requires confirmed Steps")
    if snapshot["workflow_status"] == "COMPLETE" and completion["assembly"] != "MATCH":
        raise ValueError("snapshot.completion: COMPLETE requires final MATCH")
    inspection = snapshot.get("inspection")
    if completion["assembly"] == "MATCH" and inspection is not None:
        if (inspection["check_kind"] != "FINAL" or inspection["status"] != "OK"
                or inspection["comparison"] != "MATCH"
                or inspection["difference"]["unobservable"]):
            raise ValueError("snapshot.completion: assembly MATCH conflicts with final inspection")
    if completion["storage"] != "NOT_STARTED" and completion["assembly"] != "MATCH":
        raise ValueError("snapshot.completion: storage requires final MATCH")
    if completion["web"] != "NOT_STARTED" and completion["storage"] != "SUCCEEDED":
        raise ValueError("snapshot.completion: web requires saved record")
    if completion["assembly"] in ("MISMATCH", "UNOBSERVABLE") or "FAILED" in (completion["storage"], completion["web"]):
        _text(completion["reason"], "snapshot.completion.reason")


def main():
    """가짜 자료의 계약만 확인한다. Qt·Backend·ROS를 실행하지 않는다."""
    import argparse
    import json
    from pathlib import Path
    from .hmi_contracts import validate_hmi_snapshot

    fixtures = json.loads((Path(__file__).resolve().parents[1] / "interfaces/fixtures/hmi_mvp.json").read_text())
    parser = argparse.ArgumentParser(description="FAKE HMI 입력 계약 확인 (화면/장치 실행 없음)")
    parser.add_argument("--case", choices=fixtures["snapshots"])
    args = parser.parse_args()
    selected = {args.case: fixtures["snapshots"][args.case]} if args.case else fixtures["snapshots"]
    for name, payload in selected.items():
        if payload["monitor"]["robot"]["mode"] != "FAKE":
            raise ValueError("Fixture checker requires explicit FAKE")
        result = validate_hmi_snapshot(payload)
        print(f"PASS {name} · FAKE · 계약 검사만 수행")
        if args.case:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"{len(selected)}개 입력 확인 · 로봇/Camera/LLM/DB 호출 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
