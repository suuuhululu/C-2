"""별도 PostgreSQL 시험 DB에서 완료 후 인증·소유권·웹 조회를 검사한다."""
from contextlib import nullcontext
import json
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest
from history import personal, store
from history.mvp_save import link_current_job, save_current_job, verify_web_job
from history.web import HistoryServer
from test_history_personal_db import connection, users, complete_job, write


def test_completed_guest_job_login_save_web_and_other_owner_rejected(connection,users,tmp_path,monkeypatch):
    job=str(uuid4());key=str(uuid4())
    write(tmp_path/(job+'.jsonl'),complete_job(job))
    user,other=users
    with pytest.raises(ValueError,match='AUTHENTICATION_FAILED'):
        save_current_job(connection,tmp_path,job,user['username'],'wrong',key)
    assert store.timeline(connection,job)==[]
    saved=save_current_job(connection,tmp_path,job,user['username'],'fixture-password',key)
    again=save_current_job(connection,tmp_path,job,user['username'],'fixture-password',key)
    assert again==saved
    assert personal.bundle(connection,job,user['user_id'])['completion']['assembly']=='RECORDED'
    with pytest.raises(ValueError,match='another owner'):
        save_current_job(connection,tmp_path,job,other['username'],'fixture-password',str(uuid4()))
    assert personal.bundle(connection,job,user['user_id'])['storage']['status']=='SAVED'
    monkeypatch.setattr(store,'connect',lambda dsn:nullcontext(connection))
    with HistoryServer(('127.0.0.1',0),'') as server:
        worker=Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            viewed=verify_web_job(server.origin,job,user['username'],'fixture-password',saved['receipt'])
            assert viewed['completion']['assembly']=='RECORDED'
            assert viewed['owner']['owner_user_id']==user['user_id']
            with pytest.raises(ValueError,match='WEB_JOB_UNAVAILABLE'):
                verify_web_job(server.origin,job,other['username'],'fixture-password',saved['receipt'])
        finally:server.shutdown();worker.join(timeout=2)


def test_before_final_confirmation_never_binds_or_saves(connection,users,tmp_path):
    job=str(uuid4());user=users[0]
    write(tmp_path/(job+'.jsonl'),complete_job(job)[:-1])
    with pytest.raises(ValueError,match='FINAL_ASSEMBLY_NOT_CONFIRMED'):
        save_current_job(connection,tmp_path,job,user['username'],'fixture-password',str(uuid4()))
    assert store.timeline(connection,job)==[]


def test_creator_link_at_start_preserves_incomplete_job_and_never_publishes(connection,users,tmp_path):
    from history import gallery
    job=str(uuid4());path=tmp_path/(job+'.jsonl')
    documents=complete_job(job)
    write(path,documents[:2])
    binding=link_current_job(connection,tmp_path,job,users[0])
    assert binding['owner_user_id']==users[0]['user_id']
    assert link_current_job(connection,tmp_path,job,users[0])==binding
    own=personal.bundle(connection,job,users[0]['user_id'])
    assert own['storage']['status']=='PENDING' and own['completion']['assembly']=='NOT_RECORDED'
    assert len(gallery.creator_library(connection,users[0])['designs'])==1
    assert gallery.public_designs(connection)==[]
    with pytest.raises(ValueError,match='another owner'):
        link_current_job(connection,tmp_path,job,users[1])
    with pytest.raises(ValueError,match='CREATOR_ACCOUNT_UNAVAILABLE'):
        link_current_job(connection,tmp_path,job,dict(users[0],user_id=users[1]['user_id']))
    assert path.read_text().count('\n')==2


def test_save_checks_frozen_creator_before_import(connection,users,tmp_path):
    job=str(uuid4());write(tmp_path/(job+'.jsonl'),complete_job(job))
    with pytest.raises(ValueError,match='JOB_CREATOR_DIFFERS'):
        save_current_job(connection,tmp_path,job,users[1]['username'],'fixture-password',str(uuid4()),
                         expected_user_id=users[0]['user_id'])
    assert store.timeline(connection,job)==[]


@pytest.mark.parametrize('fail_owner',[False,True])
def test_hmi_creator_login_start_owner_save_and_next_creator(connection,users,tmp_path,monkeypatch,fail_owner):
    import os
    import time
    from app.mvp_integration import MvpIntegration, render_creator
    from app.qt_hmi import HmiWindow
    from PyQt5.QtCore import QSize
    from PyQt5.QtWidgets import QApplication
    from history import gallery
    root=Path(os.environ.get('C2_ROBOT_ROOT',''))
    if not (root/'scripts/robot_integration_runtime.py').is_file():pytest.skip('C2_ROBOT_ROOT required')
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    fail_next=[False]
    def connect(dsn):
        if fail_next[0]:
            import psycopg
            fail_next[0]=False
            raise psycopg.OperationalError('fixture secret DSN/password')
        return nullcontext(connection)
    monkeypatch.setattr(store,'connect',connect)
    with_server=HistoryServer(('127.0.0.1',0),'')
    web_thread=Thread(target=with_server.serve_forever,daemon=True);web_thread.start()
    block=dict(brick_type='2x2x1',color='blue',x=6,y=6,layer=1,orientation_deg=0)
    runtime=MvpIntegration(root,tmp_path,fixture_design=dict(design_version=1,blocks=[block]),
                           history_dsn='',web_url='http://127.0.0.1:1' if fail_owner else with_server.origin)
    app=QApplication.instance() or QApplication([])
    window=HmiWindow(screen_size=QSize(1920,1080))
    window.creator_bar.show()
    def settle(predicate):
        end=time.monotonic()+25
        while time.monotonic()<end:
            runtime.poll()
            if predicate():return
            time.sleep(.02)
        pytest.fail('creator workflow did not settle')
    try:
        assert not runtime.command('START') and runtime.workflow.job_id is None
        assert runtime.login(users[0]['username'],'wrong')
        settle(lambda:not runtime.login_pending)
        assert runtime.creator is None and runtime.creator_reason
        assert not runtime.command('START')
        assert runtime.login(users[0]['username'],'fixture-password')
        settle(lambda:not runtime.login_pending)
        assert runtime.creator['user_id']==users[0]['user_id']
        fail_next[0]=fail_owner
        assert runtime.command('START')
        job=runtime.workflow.job_id
        assert not runtime.logout() and not runtime.login(users[1]['username'],'fixture-password')
        settle(lambda:runtime.owner_state!='PENDING')
        if fail_owner:
            assert runtime.owner_state=='FAILED' and 'secret' not in runtime.creator_reason
            assert runtime.job_creator['user_id']==users[0]['user_id']
            assert store.timeline(connection,job)==[]
        else:
            assert runtime.owner_state=='SUCCEEDED',runtime.creator_reason
            assert personal.bundle(connection,job,users[0]['user_id'])['owner']['owner_user_id']==users[0]['user_id']
        def finished():
            if runtime.workflow.candidate:runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
            if runtime.c_pending:runtime.answer('좋아 이걸로 하자')
            assert runtime.workflow.status!='HOLD',runtime.workflow.reason
            return runtime.workflow.status=='COMPLETE'
        settle(finished)
        current=json.loads(json.dumps(runtime.workflow.current))
        assert not runtime.save('',users[1]['username'],'fixture-password')
        assert runtime.logout() and not runtime.save_logged_in()
        assert runtime.login(users[1]['username'],'fixture-password')
        settle(lambda:not runtime.login_pending)
        assert not runtime.save_logged_in()
        assert runtime.login(users[0]['username'],'fixture-password')
        settle(lambda:not runtime.login_pending)
        assert runtime.save_logged_in()
        settle(lambda:runtime.workflow.storage!='PENDING' and runtime.workflow.web!='PENDING')
        assert runtime.workflow.storage=='SUCCEEDED'
        assert runtime.workflow.web==('FAILED' if fail_owner else 'SUCCEEDED')
        assert runtime.owner_state=='SUCCEEDED' and runtime.creator_reason is None
        assert runtime.workflow.current==current and runtime.workflow.status=='COMPLETE'
        assert personal.bundle(connection,job,users[0]['user_id'])['storage']['status']=='SAVED'
        assert gallery.public_designs(connection)==[]
        window.render_snapshot(runtime.workflow.snapshot());render_creator(window,runtime);app.processEvents()
        window.heading.setText('협동 조립 · 최종 MVP · FAKE Robot/Camera/제스처 · A/B 실제 계산')
        assert users[0]['username'] in window.creator_identity.text()
        assert users[0]['username'] in window.creator_job.text()
        assert window.buttons['START'].isEnabled()
        output=Path('logs/history_web/hmi-creator');output.mkdir(parents=True,exist_ok=True)
        window.grab().save(str(output/('creator-completed-retry.png' if fail_owner else 'creator-completed-success.png')))
        small=HmiWindow(screen_size=QSize(960,900),window_size=QSize(960,900))
        small.creator_bar.show();small.render_snapshot(runtime.workflow.snapshot());render_creator(small,runtime)
        app.processEvents()
        assert small.creator_login.geometry().right()<=small.creator_bar.width()
        assert small.creator_logout.geometry().right()<=small.creator_bar.width()
        small.close()
        log=(tmp_path/(job+'.jsonl')).read_text()
        assert 'fixture-password' not in log and 'password_hash' not in log
        assert runtime.logout() and runtime.login(users[1]['username'],'fixture-password')
        settle(lambda:not runtime.login_pending)
        assert runtime.command('START')
        next_job=runtime.workflow.job_id
        settle(lambda:runtime.owner_state!='PENDING')
        assert runtime.owner_state=='SUCCEEDED'
        assert runtime.job_creator['user_id']==users[1]['user_id']
        assert personal.bundle(connection,next_job,users[1]['user_id'])['owner']['owner_user_id']==users[1]['user_id']
        with pytest.raises(ValueError,match='unavailable'):
            personal.bundle(connection,job,users[1]['user_id'])
    finally:
        runtime.close();window.close()
        with_server.shutdown();web_thread.join(timeout=2);with_server.server_close()


def test_actual_five_layer_mock_log_is_savable_without_current_rewrite(connection,users,tmp_path):
    path=Path('logs/mvp-integration-verification/five-layer.jsonl')
    if not path.is_file():pytest.skip('run the five-layer mock integration first')
    lines=path.read_text();old=json.loads(lines.splitlines()[0])['job_id'];job=str(uuid4())
    write_path=tmp_path/(job+'.jsonl');write_path.write_text(lines.replace(old,job))
    result=save_current_job(connection,tmp_path,job,users[0]['username'],'fixture-password',str(uuid4()))
    bundle=personal.bundle(connection,job,users[0]['user_id'])
    assert bundle['storage']['status']=='SAVED' and result['receipt']['event_count']>100
    accepted=[c for c in bundle['checks'] if c['disposition']=='ACCEPTED']
    assert len(accepted)==7
    assert accepted[-1]['response']['current']['current_revision']==5
    assert bundle['completion']['assembly']=='RECORDED'
    assert write_path.read_text()==lines.replace(old,job)


def test_hmi_save_failure_and_web_failure_preserve_completed_current(connection,users,tmp_path,monkeypatch):
    import os
    import time
    from copy import deepcopy
    from app.mvp_integration import MvpIntegration
    root=Path(os.environ.get('C2_ROBOT_ROOT',''))
    if not (root/'scripts/robot_integration_runtime.py').is_file():pytest.skip('C2_ROBOT_ROOT required')
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    monkeypatch.setattr(store,'connect',lambda dsn:nullcontext(connection))
    runtime=MvpIntegration(root,tmp_path)
    job=str(uuid4());write(tmp_path/(job+'.jsonl'),complete_job(job))
    final=json.loads(Path('tests/fixtures/history_final_mvp.json').read_text())['cases']['final']['current']
    runtime.workflow.job_id=job
    runtime.workflow.current=deepcopy(final)
    runtime.workflow.status='COMPLETE';runtime.workflow.assembly='MATCH'
    current=deepcopy(runtime.workflow.current)
    def settle():
        end=time.monotonic()+10
        while time.monotonic()<end:
            runtime.poll()
            if runtime.workflow.storage!='PENDING' and runtime.workflow.web!='PENDING':return
            time.sleep(.02)
        pytest.fail('save worker did not settle')
    try:
        assert runtime.save('',users[0]['username'],'wrong',web_url='http://127.0.0.1:1')
        settle()
        assert runtime.workflow.storage=='FAILED' and runtime.workflow.status=='COMPLETE'
        assert runtime.workflow.current==current and runtime.workflow.assembly=='MATCH'
        assert runtime.save('',users[0]['username'],'fixture-password',web_url='http://127.0.0.1:1')
        settle()
        assert runtime.workflow.storage=='SUCCEEDED' and runtime.workflow.web=='FAILED'
        assert runtime.workflow.current==current and runtime.workflow.status=='COMPLETE'
        rows=store.timeline(connection,job)
        assert not any(r['event']=='ROBOT_EXECUTION_STARTED' for r in rows)
    finally:runtime.close()
