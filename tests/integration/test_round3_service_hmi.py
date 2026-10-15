"""GUI opens empty, separates C approval/B review, and never reruns D on save."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime,timezone
import json
from uuid import uuid4

import pytest
from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QApplication

from app import round3_service_hmi as hmi


@pytest.fixture(scope='module')
def qapp():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp,monkeypatch):
    monkeypatch.delenv('C2_SIXPART_USERNAME',raising=False)
    monkeypatch.delenv('C2_SIXPART_PASSWORD',raising=False)
    w=hmi.ServiceWindow();w.show();qapp.processEvents()
    yield w
    w.active=False;w.close();qapp.processEvents()


def creator():return dict(user_id=str(uuid4()),username='fixture',display_name='시험 사용자')


def test_empty_hmi_requires_login_and_preparation_and_live_c_key(window,monkeypatch):
    assert not window.active and window.process.state()==QProcess.NotRunning
    assert window.layers.rowCount()==0 and window.document['scenario']['steps']==[]
    window.ready.setChecked(True);assert not window.buttons['START'].isEnabled()
    window.creator=creator();window.refresh_creator();assert window.buttons['START'].isEnabled()
    monkeypatch.delenv('OPENAI_LLM_API_KEY',raising=False)
    launches=[];monkeypatch.setattr(QProcess,'start',lambda *a:launches.append(a))
    window.start_run();assert not launches and not window.used
    monkeypatch.setenv('C_DESIGN_USE_LLM','1');monkeypatch.setenv('OPENAI_LLM_API_KEY','fixture-never-sent')
    window.start_run();window.start_run()
    assert len(launches)==1 and 'app.round3_service' in launches[0][2]
    config=json.loads(window.plan_path.read_text())
    assert config['creator']==window.creator and 'fixture-never-sent' not in window.plan_path.read_text()


def test_each_b_failure_checkbox_is_unchecked_and_c_text_never_approves_d(window,monkeypatch):
    window.active=True;writes=[]
    monkeypatch.setattr(QProcess,'write',lambda self,b:writes.append(json.loads(bytes(b))))
    for i in range(2):
        window.handle_event('REQUEST',dict(request_id=str(i),kind='B_FAILURE',check_kind='INITIAL',failure=dict(reason='TEST_ONLY')))
        assert not window.review_check.isChecked() and not window.continue_button.isEnabled()
        window.reply(True);assert len(writes)==i
        window.review_check.setChecked(True);window.reply(True)
        assert writes[-1]==dict(request_id=str(i),answer=True)
    window.handle_event('REQUEST',dict(request_id='C',kind='C_TEXT',prompt='미리보기 승인?'))
    window.dialogue_input.setText('수정해줘');window.answer_text()
    assert writes[-1]==dict(request_id='C',answer='수정해줘')
    assert window.current is None


def test_login_filters_datetime_and_private_columns_before_child_config(window,monkeypatch):
    from history import accounts,store
    class Immediate:
        def __init__(self,target,**kw):self.target=target
        def start(self):self.target()
    identity=dict(creator(),created_at=datetime.now(timezone.utc),password_hash='never-log')
    window.history_dsn='fixture-only'
    monkeypatch.setattr(hmi,'Thread',Immediate)
    monkeypatch.setattr(store,'connect',lambda *a:nullcontext(None))
    monkeypatch.setattr(accounts,'authenticate',lambda *a:identity)
    assert window.login('fixture','fixture-password')
    window.poll_accounts()
    assert set(window.creator)=={'user_id','username','display_name'}
    assert 'never-log' not in json.dumps(window.creator)


def test_dynamic_plan_rows_change_request_and_stop(window,monkeypatch):
    window.active=True
    blocks=[dict(brick_type='2x2x1',color='blue',x=11,y=11,layer=i+1,orientation_deg=0) for i in range(3)]
    window.handle_event('SERVICE_A_PLAN',dict(state_basis='B_INITIAL',plan=dict(steps=[dict(step_id=f'S{i}',after=b) for i,b in enumerate(blocks)])))
    assert window.layers.rowCount()==3
    writes=[];monkeypatch.setattr(QProcess,'write',lambda self,b:writes.append(json.loads(bytes(b))))
    window.request_change()
    window.handle_event('REQUEST',dict(request_id='step',kind='STEP_READY',index=0,total=3,case=dict(target=blocks[0],supply_slot=1)))
    assert writes==[dict(request_id='step',answer='CHANGE')]
    monkeypatch.setattr(QProcess,'processId',lambda self:0)
    window.request_stop()
    window.handle_event('REQUEST',dict(request_id='late',kind='STEP_READY'))
    assert window.pending is None and window.stop_requested


def test_handover_and_human_completion_each_require_a_fresh_checkbox_without_current_change(window,monkeypatch):
    window.active=True;writes=[]
    monkeypatch.setattr(QProcess,'write',lambda self,b:writes.append(json.loads(bytes(b))))
    target=dict(brick_type='2x3x1',color='yellow',x=11,y=11,layer=2,orientation_deg=90)
    for kind in ('HANDOVER_READY','HUMAN_ASSEMBLY_DONE'):
        window.handle_event('REQUEST',dict(request_id=kind,kind=kind,case=dict(target=target),human_actions=[]))
        assert not window.review_check.isChecked() and not window.continue_button.isEnabled()
        before=len(writes);window.reply(True);assert len(writes)==before
        window.review_check.setChecked(True);window.reply(True)
        assert writes[-1]==dict(request_id=kind,answer=True)
        assert window.current is None


def test_web_retry_reuses_db_receipt_and_never_starts_robot(window,monkeypatch):
    from history import store,personal,mvp_save
    class Immediate:
        def __init__(self,target,**kw):self.target=target
        def start(self):self.target()
    window.creator=creator();window.credentials=('fixture','fixture-password')
    hmi.stack.save(window.plan_path,dict(creator=window.creator))
    window.final_result=dict(job_id=window.job_id,history_directory='fixture-only',physical_completion=False)
    count=dict(db=0,web=0)
    receipt=dict(receipt_id=str(uuid4()))
    def connect(*a):count['db']+=1;return nullcontext(None)
    def web(*a):
        count['web']+=1
        if count['web']==1:raise ConnectionError('EXPLICIT_WEB_ONLY_FAILURE')
    monkeypatch.setattr(hmi,'Thread',Immediate)
    monkeypatch.setattr(store,'connect',connect)
    monkeypatch.setattr(mvp_save,'link_current_job',lambda *a:None)
    monkeypatch.setattr(personal,'save_job',lambda *a:receipt)
    monkeypatch.setattr(mvp_save,'verify_web_job',web)
    monkeypatch.setattr(QProcess,'start',lambda *a:pytest.fail('storage retry must never start D'))
    assert window.save_history()
    old_job=window.job_id;window.new_plan();assert window.job_id==old_job
    window.poll_accounts();assert window.archive_receipt==receipt
    assert window.save_history();window.poll_accounts()
    assert count==dict(db=1,web=2) and '조립 완료 미확인' in window.creator_notice.text()
