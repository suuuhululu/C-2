from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from history import report
from history.records import InputError, parse_record


ROOT = Path(__file__).resolve().parents[2]
COMMON = json.loads((ROOT / "interfaces/fixtures/day4.json").read_text())
SCHEMA = json.loads((ROOT / "history/log.schema.json").read_text())
SHARED = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, resolver=jsonschema.RefResolver.from_schema(
    SCHEMA, store={"https://schemas.c2.invalid/day4.schema.json": SHARED}), format_checker=jsonschema.FormatChecker())


def event(name, result=None, *, job=None, request=None, plan=None, seconds=0):
    return dict(timestamp=(datetime(2026,10,6,tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat(),
                job_id=job or str(uuid4()), plan_id=plan, step_id=None, request_id=request,
                event=name, result=deepcopy(result), reason=None)


def parse(doc):
    return parse_record((json.dumps(doc)+"\n").encode(), "fixture.jsonl", 4)


def rows(documents):
    return [dict(document=doc, occurred_at=doc["timestamp"], source_key="fixture.jsonl", line_number=i,
                 **{key:doc[key] for key in ("job_id","plan_id","step_id","request_id","event","reason")})
            for i,doc in enumerate(documents,1)]


def adoption(job, *, plan="p1", version=1, revision=0, seconds=0):
    design, planned = deepcopy(COMMON["design"]), deepcopy(COMMON["initial_plan"])
    design["design_version"] = planned["design_version"] = version
    planned.update(plan_id=plan, base_current_revision=revision)
    return event("PLAN_ADOPTED", dict(design=design, plan=planned,
        base_current=dict(current_revision=revision, blocks=[]), confirmed_steps=[]),
        job=job, plan=plan, seconds=seconds)


def current(job, *, seconds=1):
    observed = deepcopy(COMMON["observed_match"])
    return event("CURRENT_ADOPTED", dict(current=dict(current_revision=1,
        blocks=observed["visible_blocks"]), observed=observed), job=job,
        request=observed["check_id"], plan="p1", seconds=seconds)


def hri_request(job, request="q1", *, seconds=1):
    return event("REQUEST_SENT", dict(port="hri", payload=dict(job_id=job, request_id=request,
        design_version=1, current_revision=1, design=COMMON["design"],
        current=dict(current_revision=1,blocks=[]),
        difference=dict(missing=[],unexpected=[],unobservable=[]))),
        job=job, request=request, plan="p1", seconds=seconds)


def test_designs_ignore_candidates_scope_versions_and_keep_all_adoptions():
    first, second = str(uuid4()), str(uuid4())
    documents = [event("INITIAL_DESIGN_RECEIVED", dict(status="OK",design=COMMON["design"]),job=first),
        adoption(first), adoption(first,plan="p2",seconds=2), adoption(second),
        adoption(first,plan="p3",version=2,seconds=3)]
    original = deepcopy(documents)
    output = report.designs(rows(documents))
    assert [(item["job_id"],item["design_version"]) for item in output] == [(first,1),(second,1),(first,2)]
    assert [item["plan_id"] for item in output[0]["adoptions"]] == ["p1","p2"]
    output[0]["design"]["blocks"].clear()
    assert documents == original


def test_current_progress_does_not_supersede_plan_and_completion_is_not_live_activity():
    job = str(uuid4())
    documents = [adoption(job), current(job), event("JOB_COMPLETED",job=job,seconds=2)]
    plans = report.plans(rows(documents))
    assert plans[0]["base_current_revision"] == 0 and plans[0]["superseded_at"] is None
    assert plans[0]["is_last_adopted"] is True and "active" not in plans[0]
    states = report.currents(rows(documents))
    assert [(item["kind"],item["current_revision"]) for item in states] == [("PLAN_BASIS",0),("OBSERVATION_ADOPTED",1)]
    assert states[0]["observed"] is None
    assert states[1]["check_id"] == COMMON["observed_match"]["check_id"]
    assert states[1]["observed"] == COMMON["observed_match"]


def test_revised_and_keep_replans_keep_fixed_bases_and_duplicate_adoption_evidence():
    job = str(uuid4())
    documents = [adoption(job), adoption(job,plan="p2",revision=1,seconds=1),
        adoption(job,plan="p2",revision=1,seconds=2),
        adoption(job,plan="p3",version=2,revision=1,seconds=3)]
    output = report.plans(rows(documents))
    assert [item["design_version"] for item in output] == [1,1,2]
    assert [item["base_current_revision"] for item in output] == [0,1,1]
    assert [item["superseded_by"] for item in output] == ["p2","p3",None]
    assert len(output[1]["adoptions"]) == 2
    assert output[1]["superseded_at"] == datetime.fromisoformat(documents[-1]["timestamp"])


def test_hri_links_only_same_job_request_and_keeps_unknown_context_and_failures():
    job, other = str(uuid4()), str(uuid4())
    response = dict(status="OK",hri_result="REVISE",design={**COMMON["design"],"design_version":2},
                    questions=["바꾸시겠어요?"],error=None)
    documents = [hri_request(job), event("QUESTION_RECEIVED","바꾸시겠어요?",job=job,request="q1"),
        event("C_INTERVENTION_RESULT",response,job=job,request="q1"),
        event("INTENT_RECEIVED",dict(decision="REVISE",design=response["design"]),job=job,request="q1"),
        hri_request(other), event("QUESTION_OPENED","다시 알려주세요",job=job,request="q2"),
        event("CALL_FAILED",job=other,request="q1"),
        event("CALL_FAILED",job=job,request="robot-unrelated")]
    documents[-2]["reason"] = "C 호출 실패"
    output = report.hri(rows(documents))
    assert len(output) == 3
    assert output[0]["record_status"] == "INTENT_RECORDED"
    assert output[0]["current_revision"] == 1 and output[0]["c_responses"][0]["response"] == response
    assert output[1]["record_status"] == "FAILURE_RECORDED"
    assert output[2]["record_status"] == "NO_RESPONSE_RECORDED"
    assert output[2]["current_revision"] is None and output[2]["design"] is None


@pytest.mark.parametrize("doc", [
    adoption(str(uuid4())), current(str(uuid4())), hri_request(str(uuid4())),
    event("INITIAL_DESIGN_RECEIVED",dict(status="OK",design=COMMON["design"])),
    event("PLAN_RESULT",dict(status="INVALID",plan=None,errors=[dict(reason="OUT_OF_BOUNDS",block={"x":99})])),
    event("C_INTERVENTION_RESULT",dict(status="FAILED",design=None,hri_result=None,questions=[],
        error=dict(code="LLM_CALL_FAILED",message="provider failed",details=[])),request="q1"),
    event("C_INTERVENTION_RESULT",dict(status="OK",hri_result="UNCLEAR",questions=["もう一度"]),request="q1"),
    event("INTENT_RECEIVED",dict(decision="KEEP"),request="q1"),
    event("FUTURE_EVENT",dict(arbitrary="preserved")),
])
def test_schema_and_runtime_accept_archive_cases_without_inventing_values(doc):
    VALIDATOR.check_schema(SCHEMA)
    VALIDATOR.validate(doc)
    assert parse(doc)["document"] == doc


@pytest.mark.parametrize("name,result,identity", [
    ("CURRENT_ADOPTED",dict(current=dict(current_revision=True,blocks=[]),observed=COMMON["observed_match"]),"q1"),
    ("CURRENT_ADOPTED",dict(current=dict(current_revision=1,blocks=[]),observed={}),"q1"),
    ("QUESTION_RECEIVED",{},"q1"),
    ("QUESTION_RECEIVED","question",None),
    ("INTENT_RECEIVED",dict(decision="REVISE",design={}),"q1"),
    ("INTENT_RECEIVED",dict(decision="UNCLEAR"),"q1"),
    ("PLAN_RESULT",dict(status="READY",plan=None,errors=[]),None),
    ("C_INTERVENTION_RESULT",dict(status="OK",hri_result="UNCLEAR",questions=[]),"q1"),
    ("C_INTERVENTION_RESULT",dict(status="FAILED",error=None),"q1"),
    ("REQUEST_SENT",dict(port="hri",payload=dict(current_revision="1")),"q1"),
    ("REQUEST_SENT",dict(port="hri",payload=dict(difference=dict(missing=[],unexpected=[]))),"q1"),
])
def test_malformed_query_inputs_rejected_by_schema_and_runtime(name,result,identity):
    doc = event(name,result,request=identity)
    assert list(VALIDATOR.iter_errors(doc))
    with pytest.raises(InputError,match="fixture.jsonl:4:"):
        parse(doc)


def test_cross_document_identifiers_and_context_versions_are_checked():
    doc = current(str(uuid4()))
    doc["request_id"] = "wrong-check"
    with pytest.raises(InputError,match="differs from observed.check_id"):
        parse(doc)
    doc = hri_request(str(uuid4()))
    doc["result"]["payload"]["current_revision"] = 2
    with pytest.raises(InputError,match="differs from current"):
        parse(doc)
    doc["result"]["payload"]["current_revision"] = 1
    doc["result"]["payload"]["job_id"] = str(uuid4())
    with pytest.raises(InputError,match="job_id: differs from event"):
        parse(doc)


def test_invalid_c_candidate_is_preserved_for_diagnostics_but_not_an_adopted_design():
    candidate = deepcopy(COMMON["design"])
    candidate["blocks"][0]["layer"] = 99
    doc = event("INITIAL_DESIGN_RECEIVED",dict(status="OK",design=candidate))
    VALIDATOR.validate(doc)
    assert parse(doc)["document"]["result"]["design"] == candidate
    assert report.designs(rows([doc])) == []
    adopted = adoption(doc["job_id"])
    adopted["result"]["design"] = candidate
    with pytest.raises(InputError,match="layer"):
        parse(adopted)


def test_adoption_confirmation_container_must_match_the_schema():
    doc = adoption(str(uuid4()))
    doc["result"]["confirmed_steps"] = {}
    assert list(VALIDATOR.iter_errors(doc))
    with pytest.raises(InputError,match="confirmed_steps: expected array"):
        parse(doc)
