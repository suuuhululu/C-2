"""Opt-in actual PostgreSQL tests; only a explicitly named test DB is accepted."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from history.mock_record import generate
from history.records import InputError
from history import report


@pytest.fixture
def connection():
    dsn = os.environ.get("HISTORY_TEST_DSN")
    if not dsn:
        pytest.skip("set HISTORY_TEST_DSN for actual PostgreSQL integration")
    from history import store
    with store.connect(dsn) as conn:
        database = conn.execute("SELECT current_database() AS name").fetchone()["name"]
        if not database.endswith("_test"):
            pytest.fail("history integration requires a separate database ending in _test")
        store.initialize(conn)
        yield conn


def source():
    return "tests/"+str(uuid4())+".jsonl"


def simple(job=None, name="JOB_STARTED"):
    return dict(timestamp="2026-10-06T00:00:00+00:00",job_id=job or str(uuid4()),plan_id=None,
                step_id=None,request_id=None,event=name,result=None,reason=None)


def write(path,documents):
    path.write_text("".join(json.dumps(doc,ensure_ascii=False)+"\n" for doc in documents),encoding="utf-8")


def test_mock_full_flow_raw_timeline_materials_and_duplicate_import(connection,tmp_path):
    from history import store
    result = generate(tmp_path)
    path = Path(result["path"])
    original, key = path.read_bytes(),source()
    imported = store.ingest(connection,path,key)
    assert imported["inserted"] > 0
    assert store.ingest(connection,path,key) == dict(source=key,inserted=0,skipped=imported["inserted"],pending_line=None)
    rows = store.timeline(connection,result["job_id"])
    assert "".join(row["raw_line"] for row in rows).encode() == original
    assert [row["document"] for row in rows] == [json.loads(line) for line in original.splitlines()]
    assert report.jobs(rows)[0]["result"] == "COMPLETE"
    assert len(store.artifacts(connection,result["job_id"])) == 3
    assert path.read_bytes() == original


def test_same_v1_across_jobs_and_revised_versions_are_separate(connection,tmp_path):
    from history import store
    jobs = [generate(tmp_path),generate(tmp_path,revise=True)]
    for job in jobs:
        store.ingest(connection,Path(job["path"]),source())
    versions = [[item["design_version"] for item in store.artifacts(connection,job["job_id"]) if item["kind"]=="DESIGN"] for job in jobs]
    assert versions == [[1],[1,2]]
    original = [json.loads(line) for line in Path(jobs[1]["path"]).read_text().splitlines()]
    stored = store.artifacts(connection,jobs[1]["job_id"])
    for event in [doc for doc in original if doc["event"] == "PLAN_ADOPTED"]:
        for kind,field in [("DESIGN","design"),("PLAN","plan"),("BASE_CURRENT","base_current")]:
            item = next(row for row in stored if row["kind"]==kind and
                        (row["design_version"]==event["result"]["design"]["design_version"] if kind=="DESIGN"
                         else row["plan_id"]==event["plan_id"]))
            assert item["document"] == event["result"][field]


def test_identical_content_distinct_lines_but_same_source_replay_is_deduplicated(connection,tmp_path):
    from history import store
    doc = simple()
    path,key = tmp_path/"events.jsonl",source()
    write(path,[doc,doc])
    assert store.ingest(connection,path,key)["inserted"] == 2
    assert store.ingest(connection,path,key)["skipped"] == 2
    assert len(store.timeline(connection,doc["job_id"])) == 2


def test_bad_append_preserves_committed_prefix_and_retry_adds_once(connection,tmp_path):
    from history import store
    first = simple()
    path,key = tmp_path/"events.jsonl",source()
    write(path,[first])
    store.ingest(connection,path,key)
    with path.open("a") as stream: stream.write('{bad}\n')
    with pytest.raises(InputError,match=":2:"):
        store.ingest(connection,path,key)
    assert len(store.timeline(connection,first["job_id"])) == 1
    write(path,[first,simple(first["job_id"],"JOB_COMPLETED")])
    assert store.ingest(connection,path,key)["inserted"] == 1
    assert store.ingest(connection,path,key)["skipped"] == 2


def test_actual_sql_failure_rolls_back_event_job_artifact_and_source(connection,tmp_path,monkeypatch):
    from history import store
    mock = generate(tmp_path)
    path,key = Path(mock["path"]),source()
    documents = [json.loads(line) for line in path.read_text().splitlines()]
    adoption_line = next(index+1 for index,doc in enumerate(documents) if doc["event"]=="PLAN_ADOPTED")
    original = store._save_event
    def fail_after_adoption(conn,record):
        result = original(conn,record)
        if record["line"] == adoption_line:
            conn.execute("SELECT 1/0")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(store,"_save_event",fail_after_adoption)
        with pytest.raises(InputError,match=rf":{adoption_line}: DB write failed \(22012\)"):
            store.ingest(connection,path,key)
    assert not store.timeline(connection,mock["job_id"])
    assert not store.artifacts(connection,mock["job_id"])
    assert connection.execute("SELECT * FROM c2_history.jobs WHERE job_id=%s",(mock["job_id"],)).fetchone() is None
    assert connection.execute("SELECT * FROM c2_history.sources WHERE source_key=%s",(key,)).fetchone() is None
    assert store.ingest(connection,path,key)["inserted"] == len(documents)


def test_changed_line_and_truncation_are_rejected_without_overwrite(connection,tmp_path):
    from history import store
    doc = simple()
    path,key = tmp_path/"events.jsonl",source()
    write(path,[doc,doc])
    store.ingest(connection,path,key)
    write(path,[{**doc,"reason":"changed"},doc])
    with pytest.raises(InputError,match="line changed"):
        store.ingest(connection,path,key)
    write(path,[doc])
    with pytest.raises(InputError,match="truncated"):
        store.ingest(connection,path,key)
    assert len(store.timeline(connection,doc["job_id"])) == 2


def test_partial_tail_is_deferred_then_imported_when_terminated(connection,tmp_path):
    from history import store
    doc = simple()
    path,key = tmp_path/"events.jsonl",source()
    write(path,[doc])
    data = path.read_bytes()
    path.write_bytes(data+data[:-1])
    assert store.ingest(connection,path,key)["pending_line"] == 2
    with path.open("ab") as stream: stream.write(b"\n")
    assert store.ingest(connection,path,key)["inserted"] == 1
    assert store.ingest(connection,path,key)["inserted"] == 0


def test_immutable_adopted_version_conflict_rolls_back_new_file(connection,tmp_path):
    from history import store
    generated = generate(tmp_path)
    path = Path(generated["path"])
    store.ingest(connection,path,source())
    adopted = next(json.loads(line) for line in path.read_text().splitlines() if json.loads(line)["event"]=="PLAN_ADOPTED")
    altered = deepcopy(adopted)
    altered["result"]["design"]["blocks"][0]["color"] = "blue"
    conflict = tmp_path/"conflict.jsonl"
    write(conflict,[altered])
    key = source()
    with pytest.raises(InputError,match="immutable DESIGN conflict"):
        store.ingest(connection,conflict,key)
    assert connection.execute("SELECT * FROM c2_history.sources WHERE source_key=%s",(key,)).fetchone() is None
    assert next(row for row in store.artifacts(connection,generated["job_id"]) if row["kind"]=="DESIGN")["document"] == adopted["result"]["design"]


def test_concurrent_replay_imports_only_once(connection,tmp_path):
    from history import store
    doc = simple()
    path,key = tmp_path/"events.jsonl",source()
    write(path,[doc,doc])
    def run():
        with store.connect(os.environ["HISTORY_TEST_DSN"]) as conn:
            return store.ingest(conn,path,key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:run(),range(2)))
    assert sorted(item["inserted"] for item in results) == [0,2]
    assert len(store.timeline(connection,doc["job_id"])) == 2


def test_cli_failure_is_explicit_and_does_not_expose_credentials(connection,monkeypatch,capsys):
    from history.__main__ import main
    monkeypatch.setenv("HISTORY_DATABASE_DSN","postgresql://c2_history:private-marker@127.0.0.1:1/c2_history_test")
    assert main(["jobs"]) == 1
    output = capsys.readouterr()
    assert "DB connection/query failed" in output.err
    assert "private-marker" not in output.err and not output.out


def test_cli_report_round_trip_and_located_input_failure(connection,tmp_path,monkeypatch,capsys):
    from history import store
    from history.__main__ import main
    monkeypatch.setenv("HISTORY_DATABASE_DSN",os.environ["HISTORY_TEST_DSN"])
    generated = generate(tmp_path)
    path=Path(generated["path"])
    assert main(["ingest","--source-root",str(tmp_path),str(path)]) == 0
    capsys.readouterr()
    output=tmp_path/"report.json"
    assert main(["report",generated["job_id"],"--output",str(output)]) == 0
    result=json.loads(output.read_text())
    assert result["jobs"][0]["result"] == "COMPLETE"
    assert [row["document"] for row in result["timeline"]] == [json.loads(line) for line in path.read_text().splitlines()]
    assert len(result["artifacts"]) == 3
    assert main(["reasons","--job-id",generated["job_id"]]) == 0
    capsys.readouterr()
    broken=tmp_path/"broken.jsonl"
    broken.write_text('{bad}\n')
    assert main(["ingest","--source-root",str(tmp_path),str(broken)]) == 1
    assert "broken.jsonl:1:" in capsys.readouterr().err


def test_semantic_cli_views_and_report_use_same_recorded_evidence(connection,tmp_path,monkeypatch,capsys):
    from history import store
    from history.__main__ import main
    monkeypatch.setenv("HISTORY_DATABASE_DSN",os.environ["HISTORY_TEST_DSN"])
    generated = generate(tmp_path,revise=True)
    path,key = Path(generated["path"]),source()
    store.ingest(connection,path,key)
    summaries = {}
    for command in ("designs","currents","plans","hri"):
        assert main([command,generated["job_id"]]) == 0
        summaries[command] = json.loads(capsys.readouterr().out)
        assert main([command,str(uuid4())]) == 0
        assert json.loads(capsys.readouterr().out) == []
    assert [item["design_version"] for item in summaries["designs"]] == [1,2]
    plans = summaries["plans"]
    assert [item["base_current_revision"] for item in plans] == [0,1]
    assert plans[0]["superseded_by"] == "mock-revised-plan" and plans[1]["is_last_adopted"]
    assert [item["current_revision"] for item in summaries["currents"]] == [0,1,1,2,3]
    question = summaries["hri"][0]
    assert question["current_revision"] == 1 and question["design_version"] == 1
    assert question["intents"][0]["intent"]["decision"] == "REVISE"
    assert question["c_responses"] == [] and question["questions"] == []
    output = tmp_path/"views.json"
    assert main(["report",generated["job_id"],"--output",str(output)]) == 0
    capsys.readouterr()
    exported = json.loads(output.read_text())
    assert all(exported[command] == summary for command,summary in summaries.items())
    assert store.ingest(connection,path,key)["inserted"] == 0


def test_hri_raw_c_failure_and_partial_context_are_preserved(connection,tmp_path):
    from history import store
    job,key = str(uuid4()),source()
    failure = dict(status="FAILED",hri_result=None,design=None,questions=["질문"],
        error=dict(code="LLM_CALL_FAILED",message="provider failed",details=[{"diagnostic":99}]))
    documents = [dict(simple(job,"REQUEST_SENT"),request_id="q1",result=dict(port="hri",payload={})),
        dict(simple(job,"C_INTERVENTION_RESULT"),request_id="q1",result=failure),
        dict(simple(job,"QUESTION_OPENED"),request_id="q2",result="다시 알려주세요")]
    path = tmp_path/"hri.jsonl"
    write(path,documents)
    store.ingest(connection,path,key)
    output = report.hri(store.timeline(connection,job))
    assert output[0]["c_responses"][0]["response"] == failure
    assert output[0]["record_status"] == "C_RESPONSE_RECORDED"
    assert output[1]["record_status"] == "NO_RESPONSE_RECORDED"
    assert output[1]["current"] is None and output[1]["design_version"] is None


def test_new_current_validation_failure_rolls_back_append_and_retry(connection,tmp_path):
    from history import store
    fixture = json.loads((Path(__file__).resolve().parents[2]/"interfaces/fixtures/day4.json").read_text())
    job,key = str(uuid4()),source()
    first = simple(job)
    observed = fixture["observed_match"]
    question = dict(simple(job,"QUESTION_OPENED"),request_id="q1",result="確認しますか？")
    current = dict(simple(job,"CURRENT_ADOPTED"),request_id="wrong-check",result=dict(
        current=dict(current_revision=1,blocks=observed["visible_blocks"]),observed=observed))
    path = tmp_path/"append.jsonl"
    write(path,[first])
    store.ingest(connection,path,key)
    write(path,[first,question,current])
    with pytest.raises(InputError,match=":3:.*differs from observed.check_id"):
        store.ingest(connection,path,key)
    assert len(store.timeline(connection,job)) == 1
    current["request_id"] = observed["check_id"]
    write(path,[first,question,current])
    assert store.ingest(connection,path,key)["inserted"] == 2
    assert store.ingest(connection,path,key)["skipped"] == 3
    assert len(report.currents(store.timeline(connection,job))) == 1
