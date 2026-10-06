from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest

from history import report
from history.mock_record import generate
from history.records import InputError, adopted_artifacts, parse_record, read_source


FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "interfaces/fixtures/day4.json").read_text())


def event(name="JOB_STARTED", *, job=None, seconds=0, result=None, reason=None, plan=None, step=None, request=None):
    return dict(timestamp=(datetime(2026,10,6,tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat(),
                job_id=job or str(uuid4()),plan_id=plan,step_id=step,request_id=request,
                event=name,result=result,reason=reason)


def raw(doc):
    return (json.dumps(doc,ensure_ascii=False,allow_nan=False)+"\n").encode()


def rows(documents):
    return [dict(job_id=doc["job_id"],plan_id=doc["plan_id"],step_id=doc["step_id"],request_id=doc["request_id"],
                 event=doc["event"],reason=doc["reason"],occurred_at=doc["timestamp"],document=doc)
            for doc in documents]


def adopted(*, job=None, plan_id="test-plan", version=1):
    design, plan = deepcopy(FIXTURE["design"]), deepcopy(FIXTURE["initial_plan"])
    design["design_version"] = plan["design_version"] = version
    plan["plan_id"] = plan_id
    return event("PLAN_ADOPTED",job=job,plan=plan_id,
                 result=dict(design=design,plan=plan,base_current=dict(current_revision=0,blocks=[]),confirmed_steps=[]))


def test_existing_fields_and_raw_content_are_preserved():
    document = adopted()
    record = parse_record(raw(document),"job.jsonl",7)
    assert record["document"] == document and record["raw"].encode() == raw(document)
    assert record["design_version"] == 1 and record["base_current_revision"] == 0
    items = adopted_artifacts(record)
    assert [item["kind"] for item in items] == ["DESIGN","PLAN","BASE_CURRENT"]
    assert items[0]["document"] == document["result"]["design"]


@pytest.mark.parametrize("field", ["timestamp","job_id","plan_id","step_id","request_id","event","result","reason"])
def test_missing_field_reports_source_line_and_field(field):
    document = event()
    del document[field]
    with pytest.raises(InputError,match=rf"job.jsonl:4: missing field: {field}"):
        parse_record(raw(document),"job.jsonl",4)


@pytest.mark.parametrize("data,reason", [
    (b'{bad}\n',"Expecting"),(b'[]\n',"expected object"),
    (b'{"event":NaN}\n',"nonfinite"),(b'{"a":1,"a":2}\n',"duplicate JSON key"),
    (b'\xff\n',"decode"),
])
def test_invalid_json_is_located(data,reason):
    with pytest.raises(InputError,match=rf"input:2: .*{reason}"):
        parse_record(data,"input",2)


@pytest.mark.parametrize("change,reason", [
    ({"timestamp":"2026-10-06T00:00:00"},"timezone"),
    ({"job_id":"not-uuid"},"UUID"), ({"reason":""},"reason"),
    ({"result":{"invalid":"\0"}},"NUL"),
])
def test_invalid_values(change,reason):
    with pytest.raises(InputError,match=reason):
        parse_record(raw({**event(),**change}),"input",1)


def test_candidate_design_is_not_adopted_artifact():
    candidate = event("INITIAL_DESIGN_RECEIVED",result=dict(status="OK",design=FIXTURE["design"]))
    assert not adopted_artifacts(parse_record(raw(candidate),"input",1))


def test_plan_identifier_mismatch_is_rejected():
    document = adopted()
    document["plan_id"] = "other-plan"
    with pytest.raises(InputError,match="differs"):
        parse_record(raw(document),"input",1)


def test_identical_events_in_different_lines_are_distinct(tmp_path):
    data = raw(event())
    path = tmp_path / "events.jsonl"
    path.write_bytes(data*2)
    records,pending = read_source(path,"events.jsonl")
    assert pending is None and len(records) == 2
    assert records[0]["digest"] == records[1]["digest"]
    assert records[0]["line"] != records[1]["line"]


@pytest.mark.parametrize("tail", [b'{"part":', raw(event()).rstrip(b"\n")])
def test_unfinished_last_line_is_deferred_and_source_not_modified(tmp_path,tail):
    path = tmp_path / "events.jsonl"
    original = raw(event())+tail
    path.write_bytes(original)
    records,pending = read_source(path,"events.jsonl")
    assert len(records) == 1 and pending == 2
    assert path.read_bytes() == original


def test_repeated_hold_is_one_episode_until_confirmed():
    job = str(uuid4())
    documents = [event("OBSERVATION_HOLD",job=job,seconds=i,reason="TARGET_UNVERIFIED",plan="p",step="s") for i in range(3)]
    documents += [event("STEP_CONFIRMED",job=job,seconds=5,plan="p",step="s"),
                  event("OBSERVATION_HOLD",job=job,seconds=6,reason="TARGET_UNVERIFIED",plan="p",step="s2")]
    result = report.episodes(rows(documents))
    assert len(result) == 2 and result[0]["evidence_count"] == 3
    assert result[0]["duration_seconds"] == 5 and result[1]["duration_seconds"] is None
    assert report.reason_counts(rows(documents)) == [dict(category="UNOBSERVABLE",reason="TARGET_UNVERIFIED",episodes=2)]


def test_partial_current_does_not_prove_target_observation_recovered():
    job = str(uuid4())
    documents = [event("OBSERVATION_HOLD",job=job,reason="TARGET_UNVERIFIED"),
                 event("CURRENT_ADOPTED",job=job,seconds=2,result=dict(current={},observed={}))]
    assert report.episodes(rows(documents))[0]["ended_at"] is None


def test_delivery_and_intent_wait_are_not_counted_as_errors():
    job = str(uuid4())
    documents = [event("DELIVERY_RESULT",job=job,result=dict(success=True,reason=None),plan="p",step="s"),
                 event("REQUEST_SENT",job=job,seconds=2,result=dict(port="hri",payload={}),plan="p",step="s"),
                 event("INTENT_RECEIVED",job=job,seconds=5,result=dict(decision="KEEP")),
                 event("STEP_CONFIRMED",job=job,seconds=10,plan="p",step="s")]
    result = report.episodes(rows(documents))
    assert {item["category"] for item in result} == {"ASSEMBLY_WAIT","INTENT_WAIT"}
    assert [item["duration_seconds"] for item in result] == [10,3]


def test_failed_robot_delivery_is_not_job_completion():
    job = str(uuid4())
    documents = [event(job=job),event("DELIVERY_RESULT",job=job,seconds=5,result=dict(success=False,reason="TIMEOUT"))]
    assert report.reason_counts(rows(documents)) == [dict(category="ROBOT_FAILURE",reason="TIMEOUT",episodes=1)]
    assert report.jobs(rows(documents))[0]["result"] == "NO_COMPLETION_RECORDED"
    assert report.jobs(rows(documents))[0]["duration_seconds"] is None


def test_unknown_and_measured_duration_are_distinct():
    job = str(uuid4())
    documents = [event("REQUEST_SENT",job=job,seconds=1,request="r",result=dict(port="robot.deliver",payload={})),
                 event("DELIVERY_RESULT",job=job,seconds=4,request="r",result=dict(success=True)),
                 event("REQUEST_SENT",job=job,seconds=5,request="pending",result=dict(port="robot.resume",payload={}))]
    assert [item["duration_seconds"] for item in report.durations(rows(documents))] == [3,None]
    assert report.jobs(rows([event("JOB_COMPLETED",job=job,seconds=10)]))[0]["duration_seconds"] is None


@pytest.mark.parametrize("revise", [False,True])
def test_mock_process_generates_adopted_documents_and_separate_confirmation(tmp_path,revise):
    result = generate(tmp_path,revise=revise)
    records,pending = read_source(Path(result["path"]),Path(result["path"]).name)
    assert result["status"] == "COMPLETE" and pending is None
    documents = [record["document"] for record in records]
    assert sum(doc["event"] == "DELIVERY_RESULT" for doc in documents) == 3
    assert sum(doc["event"] == "STEP_CONFIRMED" for doc in documents) == (2 if revise else 3)
    versions = [doc["result"]["design"]["design_version"] for doc in documents if doc["event"] == "PLAN_ADOPTED"]
    assert versions == ([1,2] if revise else [1])
    assert documents[-1]["event"] == "JOB_COMPLETED"


def test_same_observation_hold_and_place_hold_have_independent_recovery():
    job = str(uuid4())
    documents = [event("OBSERVATION_HOLD",job=job,reason="TARGET_UNVERIFIED"),
                 event("PLACE_STATUS_CHANGED",job=job,seconds=1,result="UNOBSERVABLE",reason="hand"),
                 event("PLACE_STATUS_CHANGED",job=job,seconds=2,result="EMPTY"),
                 event("STEP_CONFIRMED",job=job,seconds=3)]
    result=report.episodes(rows(documents))
    assert [item["duration_seconds"] for item in result] == [3,1]


def test_reason_change_starts_new_episode_without_assuming_prior_recovery():
    job = str(uuid4())
    documents=[event("OBSERVATION_HOLD",job=job,reason="TARGET_UNVERIFIED"),
               event("OBSERVATION_HOLD",job=job,seconds=1,reason="UNOBSERVABLE")]
    assert len(report.episodes(rows(documents)))==2
    assert all(item["duration_seconds"] is None for item in report.episodes(rows(documents)))


def test_robot_call_failure_uses_original_request_port_for_classification():
    job=str(uuid4())
    documents=[event("REQUEST_SENT",job=job,request="r",result=dict(port="robot.deliver",payload={})),
               event("CALL_FAILED",job=job,seconds=1,request="r",reason="timeout")]
    assert report.reason_counts(rows(documents)) == [dict(category="ROBOT_FAILURE",reason="timeout",episodes=1)]


@pytest.mark.parametrize("name,result,field", [
    ("DELIVERY_RESULT",dict(success=False),"reason"),
    ("DELIVERY_RESULT",dict(success=False,reason=None),"reason"),
    ("DELIVERY_RESULT",dict(success="true",reason=None),"success"),
    ("REQUEST_SENT",dict(port=7,payload={}),"port"),
    ("REQUEST_SENT",dict(port="robot.deliver",payload=None),"payload"),
    ("INTENT_RECEIVED",None,"result"),
    ("INTENT_RECEIVED",dict(decision="INVALID"),"decision"),
    ("PLAN_RESULT",dict(status="INVALID",errors=[{}]),"reason"),
])
def test_missing_result_fields_used_by_reports_are_located(name,result,field):
    with pytest.raises(InputError,match=rf"input:3: {name}.*{field}"):
        parse_record(raw(event(name,result=result)),"input",3)
