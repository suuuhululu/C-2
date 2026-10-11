"""Independent B/D consumer fixtures; these tests do not execute B, C or Robot."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from history import report
from history.final_mvp import CONTRACT, checks, completion
from history.records import InputError, parse_record


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/fixtures/history_final_mvp.json").read_text())
SCHEMA = json.loads((ROOT / "history/final_mvp.schema.json").read_text())
ARCHIVE = json.loads((ROOT / "history/log.schema.json").read_text())
SHARED = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, resolver=jsonschema.RefResolver.from_schema(
    SCHEMA, store={ARCHIVE["$id"]: ARCHIVE, SHARED["$id"]: SHARED,
                   "https://schemas.c2.invalid/day4.schema.json": SHARED}), format_checker=jsonschema.FormatChecker())


def event(name, result=None, *, job=None, plan=None, step=None, request=None):
    return dict(timestamp="2026-10-08T00:00:00+00:00", job_id=job or str(uuid4()),
                plan_id=plan, step_id=step, request_id=request, event=name, result=deepcopy(result), reason=None)


def check(name, *, job=None, disposition="ACCEPTED"):
    response = FIXTURE["cases"][name]
    return event("CHECK_RESULT", dict(response=response, disposition=disposition,
        disposition_reason="CLOSED_CHECK" if disposition == "REJECTED" else None), job=job,
        plan=response["plan_id"], step=response["step_id"], request=response["check_id"])


def adoption(job, shared=None):
    shared = shared or FIXTURE["shared_plan"]
    return event("PLAN_ADOPTED", dict(design=shared["design"], plan=shared["plan"],
        base_current=shared["plan_base_current"], confirmed_steps=[]), job=job, plan=shared["plan"]["plan_id"])


def rows(documents):
    return [dict(document=doc, occurred_at=doc["timestamp"], contract=CONTRACT,
        source_key="fixture.jsonl", line_number=i,
        **{key:doc[key] for key in ("job_id","plan_id","step_id","request_id","event","reason")})
        for i,doc in enumerate(documents,1)]


def parse(doc, contract=CONTRACT):
    return parse_record((json.dumps(doc,ensure_ascii=False)+"\n").encode(), "fixture.jsonl", 1, contract=contract)


@pytest.mark.parametrize("name", list(FIXTURE["cases"]))
def test_document_checks_schema_runtime_and_original_preservation(name):
    doc = check(name, disposition="REJECTED" if name == "old_result" else "ACCEPTED")
    VALIDATOR.check_schema(SCHEMA)
    VALIDATOR.validate(doc)
    assert parse(doc)["document"] == doc
    assert checks(rows([doc]))[0]["response"] == doc["result"]["response"]


@pytest.mark.parametrize("name,data", [
    ("INTENT_RECEIVED",dict(decision="REVISE")),
    ("INTENT_RECEIVED",dict(decision="REVISE",design=None)),
    ("C_INTERVENTION_RESULT",dict(status="OK",hri_result="REVISE")),
    ("C_INTERVENTION_RESULT",dict(status="OK",hri_result="KEEP")),
    ("C_INTERVENTION_RESULT",dict(status="OK",hri_result="UNCLEAR",question="어느 쪽인가요?")),
])
def test_delayed_design_intent_allowed_only_in_explicit_new_contract(name,data):
    doc = event(name,data,request="intent-1")
    VALIDATOR.validate(doc)
    assert parse(doc)["document"] == doc
    with pytest.raises(InputError):
        parse(doc,contract="day4")
    assert not report.designs(rows([doc]))


@pytest.mark.parametrize("change", [
    {"disposition":"UNKNOWN"}, {"disposition":"REJECTED","disposition_reason":None},
    {"response":{}},
])
def test_malformed_check_wrapper_rejected(change):
    doc=check("normal_step")
    doc["result"].update(change)
    assert list(VALIDATOR.iter_errors(doc))
    with pytest.raises(InputError): parse(doc)


@pytest.mark.parametrize("field,value", [
    ("current",None), ("current",dict(current_revision=True,blocks=[])),
    ("comparison","UNOBSERVABLE"), ("observation",None),
    ("step_id",None), ("check_kind","UNKNOWN"),
])
def test_malformed_normal_response_rejected(field,value):
    doc=check("normal_step")
    doc["result"]["response"][field]=value
    assert list(VALIDATOR.iter_errors(doc))
    with pytest.raises(InputError): parse(doc)


def test_target_mismatch_is_not_accepted_or_invented():
    doc=check("normal_step")
    doc["request_id"]="another-check"
    with pytest.raises(InputError,match="differs from response.check_id"): parse(doc)
    doc=check("normal_step")
    doc["result"]["response"]["expected"]["plan_id"]="another-plan"
    with pytest.raises(InputError,match="target differs"): parse(doc)


def test_current_keeps_history_and_excludes_rejected_and_canceled_results():
    job=str(uuid4())
    docs=[adoption(job), check("normal_step",job=job), check("lower_layer_occluded",job=job),
          check("old_result",job=job,disposition="REJECTED"),check("canceled_before_commit",job=job)]
    states=report.currents(rows(docs))
    assert [item["current_revision"] for item in states]==[0,1,2]
    assert len(states[-1]["current"]["blocks"])==2
    assert len(states[-1]["observed"]["visible_blocks"])==1
    assert len(checks(rows(docs)))==4
    output=checks(rows(docs)); output[0]["response"]["current"]["blocks"].clear()
    assert docs[1]["result"]["response"]["current"]["blocks"]


def test_final_matching_is_not_completion_until_d_conclusion_and_work_record():
    job=str(uuid4())
    docs=[adoption(job),check("final",job=job)]
    assert completion(rows(docs))["assembly"]=="NOT_RECORDED"
    done=event("ASSEMBLY_COMPLETED",dict(final_check_id="check-final",design_version=1),job=job,plan="P1")
    VALIDATOR.validate(done); parse(done)
    assert completion(rows(docs+[done]))["assembly"]=="UNVERIFIED_RECORD"
    docs += [event("PLAN_WORK_EXHAUSTED",job=job,plan="P1"),done]
    assert completion(rows(docs))["assembly"]=="RECORDED"
    assert completion(rows(docs))["web_reflection"]=="NOT_CONNECTED"
    assert report.jobs(rows(docs))[0]["result"]=="COMPLETE"
    docs.append(adoption(job))
    assert completion(rows(docs))["assembly"]=="RECORDED"  # Duplicate adoption is not a new target.
    docs.append(adoption(job,FIXTURE["revised_plan"]))
    assert completion(rows(docs))["assembly"]=="NOT_RECORDED"
    docs.append(done)
    assert completion(rows(docs))["assembly"]=="UNVERIFIED_RECORD"


@pytest.mark.parametrize("name,disposition", [("unobservable","ACCEPTED"),("final","REJECTED"),("invalid_input","ACCEPTED")])
def test_unknown_rejected_and_error_final_evidence_never_complete(name,disposition):
    job=str(uuid4()); evidence=check(name,job=job,disposition=disposition)
    done=event("ASSEMBLY_COMPLETED",dict(final_check_id=evidence["request_id"],design_version=1),job=job,plan="P1")
    docs=[adoption(job),event("PLAN_WORK_EXHAUSTED",job=job,plan="P1"),evidence,done]
    assert completion(rows(docs))["assembly"]=="UNVERIFIED_RECORD"
    assert report.jobs(rows(docs))[0]["result"]=="NO_COMPLETION_RECORDED"


def test_legacy_job_completed_does_not_satisfy_final_contract_and_preview_not_adopted():
    job=str(uuid4())
    docs=[event("JOB_COMPLETED",job=job), event("DESIGN_PREVIEW",FIXTURE["revised_plan"]["design"],job=job)]
    assert report.jobs(rows(docs))[0]["result"]=="NO_COMPLETION_RECORDED"
    assert report.designs(rows(docs))==[]


def test_unknown_day4_check_payload_remains_opaque_archive_data():
    doc=event("CHECK_RESULT",dict(response=dict(observation="producer diagnostic")))
    assert parse(doc,contract="day4")["document"]==doc


def test_final_plan_import_does_not_compute_expected(monkeypatch):
    def forbidden(*args):
        raise AssertionError("Expected belongs to B")
    monkeypatch.setattr("app.completion.calculate_expected",forbidden)
    doc=adoption(str(uuid4()))
    VALIDATOR.validate(doc)
    assert parse(doc)["document"]==doc


def test_revise_preview_and_new_adopted_plan_are_separate_wait_boundaries():
    job=str(uuid4())
    docs=[event("REQUEST_SENT",dict(port="hri",payload={}),job=job,request="q1"),
          event("INTENT_RECEIVED",dict(decision="REVISE"),job=job,request="q1",plan="P1"),
          event("DESIGN_PREVIEW",FIXTURE["revised_plan"]["design"],job=job)]
    waits=report.episodes(rows(docs))
    assert [(item["category"],item["ended_at"] is None) for item in waits]==[("INTENT_WAIT",False),("DESIGN_CHANGE_WAIT",True)]
    docs.append(adoption(job,FIXTURE["revised_plan"]))
    assert report.episodes(rows(docs))[-1]["ended_at"] is not None


def test_check_errors_are_separate_from_occlusion_and_rejected_diagnostics():
    job=str(uuid4())
    docs=[check("unobservable",job=job),check("processing_failed",job=job),
          check("processing_failed",job=job,disposition="REJECTED")]
    counts=report.reason_counts(rows(docs))
    assert {item["category"] for item in counts}=={"CHECK_ERROR","UNOBSERVABLE"}
    assert all(item["episodes"]==1 for item in counts)


def test_observation_hold_only_closes_for_same_plan_step_and_readable_response():
    job=str(uuid4())
    docs=[check("unobservable",job=job),check("normal_step",job=job)]
    assert report.episodes(rows(docs))[0]["ended_at"] is None
    docs.append(check("lower_layer_occluded",job=job))
    assert report.episodes(rows(docs))[0]["ended_at"] is not None
