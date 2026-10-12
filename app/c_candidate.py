"""C Stage3 후보의 표시·승인 경계. B의 Current는 읽기만 한다."""

from collections import Counter
from copy import deepcopy
from uuid import uuid4

from app.contracts import validate_design
from app.replan import begin_replan
from planning_trial.planner import block_key, validate_design as validate_geometry


def valid_review(backend, payload):
    state, review = backend.state, backend.state.get("c_review")
    return bool(review and review["request_id"] == payload["request_id"]
                and review["phase"] in ("REVIEW", "WAIT_ANSWER")
                and state["job_id"] == payload["job_id"] and not state["stop_request"]
                and state["workflow_status"] == ("PREPARING" if payload["kind"] == "initial" else "WAIT_INTENT")
                and state["current"]["current_revision"] == payload["base_current_revision"])


def _candidate(backend, kind, response):
    design = validate_design(response.get("design"))
    validate_geometry(design)
    state = backend.state
    previous = state["context"]["design"] if kind == "revised" else None
    version = previous["design_version"] + 1 if previous else 1
    if design["design_version"] != version:
        raise ValueError("Candidate version differs from the Approved Design")
    if previous:
        target = Counter(block_key(b) for b in design["blocks"])
        actual = Counter(block_key(b) for b in state["current"]["blocks"])
        if actual - target:
            raise ValueError("Revised Candidate must preserve every B-confirmed Current placement")
    metadata = response.get("design_metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("Candidate metadata must be an object or null")
    return design


def open_candidate(backend, kind, source, response):
    state = backend._state
    key = "planning_request" if kind == "initial" else "question_request"
    request = state[key]
    if state.get("c_review"):
        return backend._ignored(source["request_id"])
    revision = source.get("base_current_revision", source.get("current_revision"))
    if (not request or request["request_id"] != source["request_id"] or state["stop_request"]
            or state["current"]["current_revision"] != revision
            or state["job_id"] != source["job_id"]
            or state["workflow_status"] != ("PREPARING" if kind == "initial" else "WAIT_INTENT")):
        return backend._ignored(source["request_id"])
    try:
        if not isinstance(response, dict):
            raise ValueError("C response must be an object")
        if response.get("status") != "OK":
            raise ValueError("C Candidate failed: " + str(response.get("error")))
        design = _candidate(backend, kind, response)
    except ValueError as error:
        backend._hold("C_CANDIDATE_INVALID: " + str(error))
        return True
    # 생성과 검토의 요청 ID를 분리해 지연 결과가 다른 후보를 승인하지 않게 한다.
    review = dict(request_id=str(uuid4()), job_id=state["job_id"], kind=kind,
                  base_current_revision=revision, design_version=design["design_version"],
                  design=design, design_metadata=deepcopy(response.get("design_metadata")),
                  source=deepcopy(source), phase="PREVIEW", question=None)
    if kind == "revised":
        review.update(previous_design=deepcopy(state["context"]["design"]),
                      current=deepcopy(state["current"]), difference=deepcopy(state["difference"]))
    state.update(c_review=review, choice_required=False, question=None)
    backend._event("C_CANDIDATE_PREVIEW", request_id=review["request_id"], result=deepcopy(review))
    return True


def on_review(backend, payload, response):
    if not valid_review(backend, payload):
        return backend._ignored(payload["request_id"])
    state, review = backend._state, backend._state["c_review"]
    backend._event("C_REVIEW_RESULT", request_id=payload["request_id"], result=response)
    if state["c_review"] is None:  # 기록 실패로 HOLD된 경우
        return True
    try:
        if not isinstance(response, dict):
            raise ValueError("C response must be an object")
        if response.get("status") != "OK":
            raise ValueError("C review failed/cancelled: " + str(response.get("error")))
        decision = response.get("hri_result")
        if decision not in ("APPROVE", "MODIFY", "UNCLEAR"):
            raise ValueError("Unsupported C review decision")
        if decision == "UNCLEAR":
            questions = response.get("questions")
            if not isinstance(questions, list) or not questions or not isinstance(questions[-1], str):
                raise ValueError("UNCLEAR requires a question")
            state["question"] = questions[-1]
            review.update(request_id=str(uuid4()), phase="WAIT_ANSWER", question=questions[-1],
                          design_metadata=deepcopy(response.get("design_metadata", review["design_metadata"])))
            return True
        design = _candidate(backend, review["kind"], response)
        if decision == "APPROVE" and design != review["design"]:
            raise ValueError("APPROVE must match the displayed Candidate")
    except ValueError as error:
        backend._hold("C_REVIEW_INVALID: " + str(error))
        return True
    if decision == "MODIFY":
        state["question"] = None
        review.update(request_id=str(uuid4()), phase="PREVIEW", question=None,
                      design=design, design_metadata=deepcopy(response.get("design_metadata")))
        return True
    state.update(c_review=None, approved_design=deepcopy(design), question=None)
    backend._event("C_DESIGN_APPROVED", request_id=payload["request_id"], result=response)
    if state["workflow_status"] == "HOLD":
        return True
    if review["kind"] == "initial":
        backend.on_initial_design(review["source"]["request_id"],
                                  dict(status="OK", hri_result=None, design=design))
    else:
        begin_replan(backend, design)
    return True
