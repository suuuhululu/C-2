"""No devices, HTTP or DB: isolate retries at the existing storage boundaries."""
from contextlib import contextmanager
from queue import Queue
import sys
from types import SimpleNamespace

import pytest

from app.mvp_integration import MvpIntegration


def runtime(tmp_path, monkeypatch, *, database_failure=False):
    value=object.__new__(MvpIntegration)
    value.workflow=SimpleNamespace(status='COMPLETE',storage='NOT_STARTED',web='NOT_STARTED',
        job_id='fixture-job',log_directory=tmp_path,save_reason=None,assembly='MATCH')
    value.job_creator=dict(username='owner',user_id='user')
    value.owner_state='SUCCEEDED'
    value.save_receipt=value.saved_owner=None
    value.inbox, value.workers=Queue(), []
    value.robot=SimpleNamespace(events=Queue())
    value.auto_gestures=False
    calls=dict(db=0,web=0)
    @contextmanager
    def connect(*args):
        calls['db']+=1
        yield object()
    def save(*args, **kwargs):
        if database_failure and calls['db']==1:raise ValueError('TEST_DB_FAILURE')
        assert kwargs['expected_user_id']=='user'
        return dict(receipt=dict(manifest_sha256='TEST_RECEIPT'),owner=dict(username='owner',user_id='user'))
    def web(*args):
        calls['web']+=1
        if calls['web']==1:raise ValueError('TEST_WEB_FAILURE')
        assert args[-1]==dict(manifest_sha256='TEST_RECEIPT')
    import history
    store=SimpleNamespace(connect=connect)
    saving=SimpleNamespace(save_current_job=save,verify_web_job=web)
    monkeypatch.setitem(sys.modules,'history.store',store)
    monkeypatch.setattr(history,'store',store,raising=False)
    monkeypatch.setitem(sys.modules,'history.mvp_save',saving)
    monkeypatch.setattr(history,'mvp_save',saving,raising=False)
    return value,calls


def drain(value):
    for worker in value.workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    value.poll()


def test_web_retry_preserves_database_receipt_and_never_repeats_storage(tmp_path, monkeypatch):
    value,calls=runtime(tmp_path,monkeypatch)
    assert value.save('test','owner','fixture-password')
    drain(value)
    assert value.workflow.storage=='SUCCEEDED' and value.workflow.web=='FAILED'
    assert value.workflow.status=='COMPLETE' and value.workflow.assembly=='MATCH'
    assert not value.save('test','someone-else','fixture-password')
    assert value.save('test','owner','fixture-password')
    assert not value.save('test','owner','fixture-password')  # Verification already pending.
    drain(value)
    assert calls==dict(db=1,web=2)
    assert value.workflow.storage==value.workflow.web=='SUCCEEDED'


def test_database_failure_retries_storage_then_web_only(tmp_path, monkeypatch):
    value,calls=runtime(tmp_path,monkeypatch,database_failure=True)
    assert value.save('test','owner','fixture-password')
    drain(value)
    assert value.workflow.storage=='FAILED' and value.workflow.status=='COMPLETE'
    assert value.save('test','owner','fixture-password')
    drain(value)
    assert value.workflow.storage=='SUCCEEDED' and value.workflow.web=='FAILED'
    assert value.save('test','owner','fixture-password')
    drain(value)
    assert calls==dict(db=2,web=2)


@pytest.mark.parametrize('status', ['HOLD','WAIT_ASSEMBLY','STOPPED'])
def test_only_confirmed_completion_can_start_saving(tmp_path, monkeypatch, status):
    value,calls=runtime(tmp_path,monkeypatch)
    value.workflow.status=status
    assert not value.save('test','owner','fixture-password')
    assert calls==dict(db=0,web=0)


@pytest.mark.parametrize('web_only',[False,True])
def test_missing_storage_runtime_is_reported_without_hanging_pending(tmp_path, monkeypatch, web_only):
    value,_=runtime(tmp_path,monkeypatch)
    if web_only:
        value.workflow.storage='SUCCEEDED'
        value.save_receipt=dict(manifest_sha256='TEST_RECEIPT')
        value.saved_owner=dict(username='owner')
    monkeypatch.setitem(sys.modules,'history.mvp_save',None)
    assert value.save('test','owner','fixture-password')
    drain(value)
    assert value.workflow.status=='COMPLETE'
    assert (value.workflow.web if web_only else value.workflow.storage)=='FAILED'
