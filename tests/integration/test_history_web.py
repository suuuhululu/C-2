"""HTTP boundary checks with real PostgreSQL fixtures and rollback isolation."""

from contextlib import nullcontext
from copy import deepcopy
from http.client import HTTPConnection
from html.parser import HTMLParser
import json
import os
from pathlib import Path
from threading import Thread
import time
from urllib.parse import unquote, urljoin, urlsplit
from uuid import uuid4

import pytest

from history import accounts, personal, store
from history.web import ASSETS, COOKIE, HistoryServer
from history.final_mvp import CONTRACT


FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/history_final_mvp.json").read_text())


def request(server, path, data=None, *, cookie=None, origin=None, body=None, host=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    headers = {}
    if host:
        headers["Host"] = host
    if cookie:
        headers["Cookie"] = cookie
    if data is not None or body is not None:
        headers.update({"Origin": origin or server.origin, "Content-Type": "application/json"})
        connection.request("POST", path, body=body if body is not None else json.dumps(data), headers=headers)
    else:
        connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    result = json.loads(raw) if "application/json" in response.getheader("Content-Type", "") else raw
    output = response.status, dict(response.getheaders()), result
    connection.close()
    return output


@pytest.fixture
def server():
    with HistoryServer(("127.0.0.1", 0), "") as instance:
        thread = Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        yield instance
        instance.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def db(server, monkeypatch, tmp_path):
    dsn = os.environ.get("HISTORY_TEST_DSN")
    if not dsn:
        pytest.skip("set HISTORY_TEST_DSN for real PostgreSQL HTTP checks")
    with store.connect(dsn) as connection:
        assert connection.execute("SELECT current_database() AS name").fetchone()["name"].endswith("_test")
        store.initialize(connection)
        with connection.transaction(force_rollback=True):
            users = [accounts.create_user(connection, "web_" + uuid4().hex, "웹 시험 사용자", "fixture-password") for _ in range(2)]
            jobs = [str(uuid4()) for _ in range(3)]
            shared = FIXTURE["shared_plan"]
            for index, job in enumerate(jobs):
                def event(name, data=None, *, request_id=None):
                    return dict(timestamp="2026-10-11T00:00:00+00:00", job_id=job, plan_id="P1",
                                step_id=None, request_id=request_id, event=name, result=deepcopy(data), reason=None)
                documents = [event("JOB_STARTED"), event("PLAN_ADOPTED", dict(design=shared["design"], plan=shared["plan"], base_current=shared["plan_base_current"], confirmed_steps=[]))]
                if index == 0:
                    documents.extend([event("PLAN_WORK_EXHAUSTED"), event("CHECK_RESULT",dict(response=FIXTURE["cases"]["final"],disposition="ACCEPTED",disposition_reason=None),request_id="check-final"), event("ASSEMBLY_COMPLETED", dict(final_check_id="check-final",design_version=1))])
                path = tmp_path / f"{job}.jsonl"
                path.write_text("".join(json.dumps(doc) + "\n" for doc in documents))
                store.ingest(connection,path,"web-test/"+job,contract=CONTRACT)
                if index < 2:
                    personal.bind_job(connection,job,users[index]["username"],"HTTP fixture verified owner")
            monkeypatch.setattr(store,"connect",lambda dsn:nullcontext(connection))
            yield connection, users, jobs


def login(server, user):
    status, headers, result = request(server,"/api/login",dict(username=user["username"],password="fixture-password"))
    assert status == 200 and "password_hash" not in result
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    return headers["Set-Cookie"].split(";",1)[0]


def test_static_allowlist_no_directory_listing_and_no_public_binding(server):
    for path in ("/", "/index.html", "/style.css", "/app.js"):
        status, headers, body = request(server,path)
        assert status == 200 and body
        assert headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    for path in ("/../accounts.py", "/web_assets/", "/api/users", "/api/bind-job"):
        assert request(server,path)[0] == 404
    with pytest.raises(ValueError,match="127.0.0.1"):
        HistoryServer(("0.0.0.0",0),"")


def test_file_preview_resolves_styles_and_scripts_beside_html():
    class AssetLinks(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "link" and attrs.get("rel") == "stylesheet":
                self.urls.append(attrs["href"])
            elif tag == "script":
                self.urls.append(attrs["src"])

    page = ASSETS / "index.html"
    links = AssetLinks()
    links.feed(page.read_text())
    assert len(links.urls) == 2
    for reference in links.urls:
        resolved = urlsplit(urljoin(page.as_uri(), reference))
        assert resolved.scheme == "file"
        asset = Path(unquote(resolved.path))
        assert asset.parent == ASSETS and asset.is_file()


def test_auth_required_expiry_logout_and_session_rotation(server, db):
    _, users, _ = db
    assert request(server,"/api/library")[0] == 401
    first = login(server,users[0])
    second = login(server,users[0])
    # Re-authentication in the same browser rotates its previous token.
    status, headers, _ = request(server,"/api/login",dict(username=users[0]["username"],password="fixture-password"),cookie=first)
    assert status == 200 and request(server,"/api/me",cookie=first)[0] == 401
    current = headers["Set-Cookie"].split(";",1)[0]
    assert request(server,"/api/me",cookie=current)[2] == users[0] | {"created_at":users[0]["created_at"].isoformat()}
    token = current.split("=",1)[1]
    server.sessions[token] = (users[0],time.monotonic()-1)
    assert request(server,"/api/library",cookie=current)[0] == 401
    assert request(server,"/api/logout",{},cookie=second)[0] == 200
    assert request(server,"/api/me",cookie=second)[0] == 401


def test_bad_login_cross_origin_and_rebinding_do_not_create_session(server, db):
    _, users, _ = db
    data = dict(username=users[0]["username"],password="wrong-password")
    assert request(server,"/api/login",data)[0] == 401
    assert request(server,"/api/login",data,origin="https://cargo.site")[0] == 403
    assert request(server,"/api/login",data,host="attacker.example")[0] == 403
    assert request(server,"/api/login",body="{")[0] == 400
    assert request(server,"/api/login",body="[]")[0] == 400
    assert request(server,"/api/login",dict(data,user_id=users[0]["user_id"]))[0] == 400
    assert not server.sessions


def test_library_detail_export_isolate_owner_and_unowned_jobs(server, db):
    _, users, jobs = db
    cookie = login(server,users[0])
    status, _, library = request(server,"/api/library",cookie=cookie)
    assert status == 200 and [job["job_id"] for job in library["jobs"]] == [jobs[0]]
    assert [design["job_id"] for design in library["designs"]] == [jobs[0]]
    status, _, detail = request(server,"/api/jobs/"+jobs[0],cookie=cookie)
    assert status == 200 and detail["completion"]["assembly"] == "RECORDED"
    assert detail["storage"]["status"] == "PENDING"
    assert detail["completion"]["web_reflection"] == "NOT_CONNECTED"
    assert "password" not in json.dumps(detail)
    for job in [jobs[1],jobs[2],str(uuid4())]:
        assert request(server,"/api/jobs/"+job,cookie=cookie)[0] == 404
        assert request(server,"/api/jobs/"+job+"/save",dict(save_key=uuid4().hex),cookie=cookie)[0] == 404


def test_storage_receipt_idempotent_and_never_changes_assembly(server, db):
    _, users, jobs = db
    cookie = login(server,users[1]); path="/api/jobs/"+jobs[1]
    key=uuid4().hex
    first=request(server,path+"/save",dict(save_key=key),cookie=cookie)
    assert first[0] == 200
    assert request(server,path+"/save",dict(save_key=key),cookie=cookie)[2] == first[2]
    detail=request(server,path,cookie=cookie)[2]
    assert detail["storage"]["status"] == "SAVED" and detail["completion"]["assembly"] == "NOT_RECORDED"
    assert request(server,"/api/gallery")[2]["designs"] == []
    assert request(server,path+"/save",dict(save_key=key,user_id=users[0]["user_id"]),cookie=cookie)[0] == 400


def test_db_failure_is_explicit_without_diagnostics_or_fake_empty_success(server, db, monkeypatch):
    import psycopg
    _, users, _ = db
    cookie=login(server,users[0])
    def unavailable(dsn):
        raise psycopg.OperationalError("fixture secret DSN/password")
    monkeypatch.setattr(store,"connect",unavailable)
    status, _, body=request(server,"/api/library",cookie=cookie)
    assert status == 503 and "DB" in body["error"] and "secret" not in json.dumps(body)
    assert request(server,"/api/gallery")[0] == 503


def test_public_gallery_requires_no_login_but_only_explicit_publication(server, db):
    _, users, jobs = db
    assert request(server,"/api/gallery")[2]["designs"] == []
    path=f"/api/designs/{jobs[1]}/1/publication"
    assert request(server,path,dict(published=True))[0] == 401
    cookie=login(server,users[1])
    before=request(server,"/api/jobs/"+jobs[1],cookie=cookie)[2]
    assert request(server,path,dict(published=True),cookie=cookie)[0] == 200
    _, _, gallery=request(server,"/api/gallery")
    assert len(gallery["designs"]) == 1 and gallery["jobs"] == []
    design=gallery["designs"][0]
    assert set(design) == {"job_id","design_version","design","creator","published_at"}
    assert design["creator"] == dict(username=users[1]["username"],display_name=users[1]["display_name"])
    assert design["design"] == FIXTURE["shared_plan"]["design"]
    assert request(server,"/api/jobs/"+jobs[1])[0] == 401
    after=request(server,"/api/jobs/"+jobs[1],cookie=cookie)[2]
    assert after["storage"] == before["storage"] and after["completion"] == before["completion"]
    assert request(server,path,dict(published=False),cookie=cookie)[0] == 200
    assert request(server,"/api/gallery")[2]["designs"] == []
    assert request(server,"/api/library",cookie=cookie)[2]["designs"][0]["published"] is False


def test_publication_cannot_impersonate_claim_other_jobs_or_bypass_origin(server, db):
    _, users, jobs = db
    cookie=login(server,users[0])
    for job in jobs[1:]+[str(uuid4())]:
        assert request(server,f"/api/designs/{job}/1/publication",dict(published=True),cookie=cookie)[0] == 404
    path=f"/api/designs/{jobs[0]}/1/publication"
    assert request(server,path,dict(published=True,user_id=users[1]["user_id"]),cookie=cookie)[0] == 400
    assert request(server,path,dict(published="true"),cookie=cookie)[0] == 400
    assert request(server,path,dict(published=True),cookie=cookie,origin="https://cargo.site")[0] == 403
    assert request(server,f"/api/designs/{jobs[0]}/99/publication",dict(published=True),cookie=cookie)[0] == 404
    assert request(server,"/api/gallery")[2]["designs"] == []


def test_two_creators_share_gallery_but_manage_only_their_own_designs(server, db):
    _, users, jobs = db
    cookies=[login(server,user) for user in users]
    for index in range(2):
        path=f"/api/designs/{jobs[index]}/1/publication"
        first=request(server,path,dict(published=True),cookie=cookies[index])
        assert first[0] == 200
        assert request(server,path,dict(published=True),cookie=cookies[index])[2] == first[2]
        assert request(server,path,dict(published=False),cookie=cookies[1-index])[0] == 404
        own=request(server,"/api/library",cookie=cookies[index])[2]["designs"]
        assert len(own) == 1 and own[0]["published"] is True
    shared=request(server,"/api/gallery")[2]["designs"]
    assert {d["creator"]["username"] for d in shared} == {u["username"] for u in users}


def test_new_imported_version_stays_unpublished_and_published_snapshot_is_stable(server, db, tmp_path):
    connection, users, jobs = db
    cookie=login(server,users[0])
    path=f"/api/designs/{jobs[0]}/1/publication"
    assert request(server,path,dict(published=True),cookie=cookie)[0] == 200
    public_before=request(server,"/api/gallery")[2]["designs"]
    shared=deepcopy(FIXTURE["shared_plan"])
    shared["design"]["design_version"]=2
    shared["plan"].update(plan_id="P2",design_version=2)
    shared["design"]["blocks"][1]["color"]="yellow"
    shared["plan"]["steps"][1]["after"]["color"]="yellow"
    document=dict(timestamp="2026-10-12T00:00:00+00:00",job_id=jobs[0],plan_id="P2",step_id=None,
                  request_id=None,event="PLAN_ADOPTED",reason=None,
                  result=dict(design=shared["design"],plan=shared["plan"],base_current=shared["plan_base_current"],confirmed_steps=[]))
    source=tmp_path/"new-version.jsonl"
    source.write_text(json.dumps(document)+"\n")
    store.ingest(connection,source,"new-version/"+uuid4().hex,contract=CONTRACT)
    assert request(server,"/api/gallery")[2]["designs"] == public_before
    own=request(server,"/api/library",cookie=cookie)[2]["designs"]
    assert {d["design_version"]:d["published"] for d in own} == {1:True,2:False}
    assert request(server,f"/api/designs/{jobs[0]}/2/publication",dict(published=True),cookie=cookie)[0] == 200
    assert len(request(server,"/api/gallery")[2]["designs"]) == 2
