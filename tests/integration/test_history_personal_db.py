"""Actual PostgreSQL V11/V14 coverage; credentials never create HMI/web sessions."""

from contextlib import nullcontext
from copy import deepcopy
import io
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from history import accounts, personal, report, store
from history.final_mvp import CONTRACT
from history.records import InputError


FIXTURE=json.loads((Path(__file__).resolve().parents[2]/"tests/fixtures/history_final_mvp.json").read_text())


@pytest.fixture
def connection():
    dsn=os.environ.get("HISTORY_TEST_DSN")
    if not dsn: pytest.skip("set HISTORY_TEST_DSN for actual PostgreSQL personal history checks")
    with store.connect(dsn) as conn:
        if not conn.execute("SELECT current_database() AS name").fetchone()["name"].endswith("_test"):
            pytest.fail("personal history checks require a separate _test database")
        store.initialize(conn)
        with conn.transaction(force_rollback=True):
            yield conn


@pytest.fixture
def users(connection):
    return [accounts.create_user(connection,"fixture_"+uuid4().hex,"시험 사용자","fixture-password") for _ in range(2)]


def event(name="JOB_STARTED",result=None,*,job=None,plan=None,step=None,request=None):
    return dict(timestamp="2026-10-08T00:00:00+00:00",job_id=job or str(uuid4()),plan_id=plan,
        step_id=step,request_id=request,event=name,result=deepcopy(result),reason=None)


def check(name,job,*,disposition="ACCEPTED"):
    response=FIXTURE["cases"][name]
    return event("CHECK_RESULT",dict(response=response,disposition=disposition,
        disposition_reason="OLD_CHECK" if disposition=="REJECTED" else None),job=job,
        plan=response["plan_id"],step=response["step_id"],request=response["check_id"])


def write(path,docs):
    path.write_text("".join(json.dumps(doc,ensure_ascii=False)+"\n" for doc in docs),encoding="utf-8")


def import_docs(connection,tmp_path,docs,*,contract=CONTRACT,key=None):
    path=tmp_path/(uuid4().hex+".jsonl")
    write(path,docs)
    key=key or "tests/"+path.name
    store.ingest(connection,path,key,contract=contract)
    return path,key


def complete_job(job):
    shared=FIXTURE["shared_plan"]
    adoption=event("PLAN_ADOPTED",dict(design=shared["design"],plan=shared["plan"],
        base_current=shared["plan_base_current"],confirmed_steps=[]),job=job,plan="P1")
    return [event(job=job),adoption,check("normal_step",job),check("lower_layer_occluded",job),
        event("PLAN_WORK_EXHAUSTED",job=job,plan="P1"),check("final",job),
        event("ASSEMBLY_COMPLETED",dict(final_check_id="check-final",design_version=1),job=job,plan="P1")]


def test_initialize_repeat_preserves_existing_rows_hashes_and_unowned_jobs(connection,tmp_path):
    doc=event(); import_docs(connection,tmp_path,[doc],contract="day4")
    before=connection.execute("SELECT * FROM c2_history.events WHERE job_id=%s",(doc["job_id"],)).fetchall()
    accounts_before=connection.execute("SELECT * FROM c2_history.users ORDER BY user_id").fetchall()
    store.initialize(connection); store.initialize(connection)
    assert connection.execute("SELECT * FROM c2_history.events WHERE job_id=%s",(doc["job_id"],)).fetchall()==before
    assert connection.execute("SELECT * FROM c2_history.users ORDER BY user_id").fetchall()==accounts_before
    assert connection.execute("SELECT owner_user_id FROM c2_history.jobs WHERE job_id=%s",(doc["job_id"],)).fetchone()["owner_user_id"] is None


def test_owner_binding_is_explicit_immutable_audited_and_isolates_two_users(connection,users,tmp_path):
    first,second=users; jobs=[str(uuid4()) for _ in range(3)]
    for job in jobs: import_docs(connection,tmp_path,complete_job(job))
    assert personal.user_rows(connection,first["user_id"])==[]
    binding=personal.bind_job(connection,jobs[0],first["username"],"operator verified owner")
    assert personal.bind_job(connection,jobs[0],first["username"],"duplicate request")==binding
    personal.bind_job(connection,jobs[1],second["username"],"operator verified owner")
    with pytest.raises(ValueError,match="another owner"):
        personal.bind_job(connection,jobs[0],second["username"],"cannot transfer")
    assert {row["job_id"] for row in personal.user_rows(connection,first["user_id"])}=={jobs[0]}
    assert {row["job_id"] for row in personal.user_rows(connection,second["user_id"])}=={jobs[1]}
    for job in (jobs[1],jobs[2],str(uuid4())):
        with pytest.raises(ValueError,match="unavailable"):
            personal.bundle(connection,job,first["user_id"])
        with pytest.raises(ValueError,match="unavailable"):
            personal.save_job(connection,job,first["user_id"],uuid4().hex)
    assert len(report.designs(personal.user_rows(connection,first["user_id"])))==1
    result=personal.bundle(connection,jobs[0],first["user_id"])
    assert len(result["checks"])==3 and result["completion"]["assembly"]=="RECORDED"
    assert result["storage"]["status"]=="PENDING"
    assert "password_hash" not in json.dumps(result,default=str)


def test_log_claimed_user_id_never_sets_ownership(connection,users,tmp_path):
    doc=event(); doc["user_id"]=users[0]["user_id"]
    import_docs(connection,tmp_path,[doc])
    assert personal.user_rows(connection,users[0]["user_id"])==[]
    with pytest.raises(ValueError,match="reason"):
        personal.bind_job(connection,doc["job_id"],users[0]["username"],"")
    with pytest.raises(ValueError,match="account not found"):
        personal.bind_job(connection,doc["job_id"],"unknown_"+uuid4().hex,"verified")


def test_archive_contract_change_rolls_back_and_delayed_revise_is_not_adopted(connection,tmp_path):
    job=str(uuid4()); path,key=import_docs(connection,tmp_path,[event(job=job)],contract="day4")
    with pytest.raises(InputError,match="contract differs"):
        store.ingest(connection,path,key,contract=CONTRACT)
    docs=[event("C_INTERVENTION_RESULT",dict(status="OK",hri_result="REVISE"),job=job,request="q1"),
        event("INTENT_RECEIVED",dict(decision="REVISE"),job=job,request="q1"),
        event("DESIGN_PREVIEW",FIXTURE["revised_plan"]["design"],job=job)]
    import_docs(connection,tmp_path,docs)
    assert not store.artifacts(connection,job) and not report.designs(store.timeline(connection,job))
    assert report.hri(store.timeline(connection,job))[0]["intents"][0]["intent"]==dict(decision="REVISE")


def test_invalid_append_is_atomic_and_fixed_retry_preserves_original(connection,tmp_path):
    job=str(uuid4()); first=event(job=job)
    path,key=import_docs(connection,tmp_path,[first]); original=path.read_bytes()
    bad=check("normal_step",job); bad["request_id"]="wrong-check"
    write(path,[first,bad])
    with pytest.raises(InputError,match=":2:.*differs"):
        store.ingest(connection,path,key,contract=CONTRACT)
    assert len(store.timeline(connection,job))==1
    write(path,[first,check("normal_step",job)])
    assert store.ingest(connection,path,key,contract=CONTRACT)["inserted"]==1
    assert store.ingest(connection,path,key,contract=CONTRACT)["inserted"]==0
    assert store.timeline(connection,job)[0]["raw_line"].encode()==original


def test_check_conflict_across_sources_is_rejected_but_rejected_response_is_preserved(connection,tmp_path):
    job=str(uuid4()); accepted=check("normal_step",job)
    import_docs(connection,tmp_path,[accepted])
    conflict=deepcopy(accepted)
    conflict["result"]["response"]["current"]["current_revision"]=99
    with pytest.raises(InputError,match="conflicting accepted check"):
        import_docs(connection,tmp_path,[conflict])
    assert len(store.timeline(connection,job))==1
    conflict["result"].update(disposition="REJECTED",disposition_reason="CONFLICTING_DUPLICATE")
    import_docs(connection,tmp_path,[conflict])
    import_docs(connection,tmp_path,[accepted])
    states=report.currents(store.timeline(connection,job))
    assert [state["current_revision"] for state in states]==[1,1]
    assert len(store.timeline(connection,job))==3


def test_save_key_deduplicates_snapshot_not_source_lines_and_new_data_requires_new_key(connection,users,tmp_path):
    user=users[0]; job=str(uuid4()); docs=complete_job(job)
    path,key=import_docs(connection,tmp_path,docs)
    personal.bind_job(connection,job,user["username"],"test verified owner")
    original=path.read_bytes(); save_key=uuid4().hex
    receipt=personal.save_job(connection,job,user["user_id"],save_key)
    assert personal.save_job(connection,job,user["user_id"],save_key)==receipt
    assert store.ingest(connection,path,key,contract=CONTRACT)["inserted"]==0
    assert personal.bundle(connection,job,user["user_id"])["storage"]["status"]=="SAVED"
    import_docs(connection,tmp_path,[event("AUDIT_NOTE",dict(message="additional evidence"),job=job)])
    assert personal.bundle(connection,job,user["user_id"])["storage"]["status"]=="PENDING"
    with pytest.raises(ValueError,match="content conflict"):
        personal.save_job(connection,job,user["user_id"],save_key)
    new=personal.save_job(connection,job,user["user_id"],uuid4().hex)
    assert new["event_count"]==receipt["event_count"]+1
    result=personal.bundle(connection,job,user["user_id"])
    assert result["storage"]["status"]=="SAVED" and result["completion"]["assembly"]=="RECORDED"
    assert result["completion"]["web_reflection"]=="NOT_CONNECTED"
    assert path.read_bytes()==original


def test_failed_job_can_be_saved_without_becoming_assembly_complete_and_receipt_rolls_back(connection,users,tmp_path):
    import psycopg
    user=users[0]; job=str(uuid4())
    import_docs(connection,tmp_path,[event(job=job),check("processing_failed",job)])
    personal.bind_job(connection,job,user["username"],"verified")
    save_key=uuid4().hex
    with pytest.raises(psycopg.errors.DivisionByZero):
        with connection.transaction():
            personal.save_job(connection,job,user["user_id"],save_key)
            connection.execute("SELECT 1/0")
    assert personal.bundle(connection,job,user["user_id"])["storage"]["status"]=="PENDING"
    personal.save_job(connection,job,user["user_id"],save_key)
    result=personal.bundle(connection,job,user["user_id"])
    assert result["storage"]["status"]=="SAVED" and result["completion"]["assembly"]=="NOT_RECORDED"
    assert result["checks"][0]["response"]["status"]=="ERROR"


def test_authenticated_cli_cannot_read_or_save_another_users_job(connection,users,tmp_path,monkeypatch,capsys):
    from history.__main__ import main
    job=str(uuid4()); import_docs(connection,tmp_path,complete_job(job))
    personal.bind_job(connection,job,users[0]["username"],"verified")
    monkeypatch.setenv("HISTORY_DATABASE_DSN",os.environ["HISTORY_TEST_DSN"])
    monkeypatch.setattr("history.store.connect",lambda dsn:nullcontext(connection))
    def run(args,password="fixture-password"):
        monkeypatch.setattr("sys.stdin",io.StringIO(password+"\n"))
        code=main(args+["--password-stdin"])
        return code,capsys.readouterr()
    for command in ("my-jobs","my-designs"):
        code,out=run([command,users[1]["username"]]); assert code==0 and json.loads(out.out)==[]
    for command in ("my-job","save-job"):
        args=[command,users[1]["username"],job]
        if command=="save-job": args += ["--save-key",uuid4().hex]
        code,out=run(args)
        assert code==1 and "unavailable" in out.err and not out.out
    code,out=run(["my-job",users[0]["username"],job],"wrong-password")
    assert code==1 and "invalid username or password" in out.err and not out.out
    assert "wrong-password" not in out.err
    code,out=run(["save-job",users[0]["username"],job,"--save-key",uuid4().hex]); assert code==0
    code,out=run(["my-job",users[0]["username"],job]); assert code==0
    result=json.loads(out.out)
    assert result["storage"]["status"]=="SAVED" and result["completion"]["assembly"]=="RECORDED"
    assert "password" not in out.out
    assert main(["checks",job])==0
    assert len(json.loads(capsys.readouterr().out))==3
