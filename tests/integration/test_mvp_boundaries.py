"""별도 MOCK Robot + 실제 B 판정. 외부 장치/API/DB 호출 없음."""
from copy import deepcopy
import json
import os
from pathlib import Path
import time
import pytest
from app.mvp_integration import MvpIntegration

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),reason='C2_ROBOT_ROOT required')
BLOCK=dict(brick_type='2x2x1',color='blue',x=6,y=6,layer=1,orientation_deg=0)


def settle(r,condition,seconds=25,approve=False):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        r.poll();r.workflow.snapshot()
        if approve:
            if r.workflow.candidate:r.workflow.preview_ready(r.workflow.candidate['request_id'])
            if r.c_pending and r.c_pending[0]=='c.review':r.answer('좋아 이걸로 하자')
        if condition():return
        time.sleep(.02)
    pytest.fail(str((r.workflow.status,r.workflow.reason)))


def log_rows(r,directory):
    return [json.loads(line) for line in (directory/(r.workflow.job_id+'.jsonl')).read_text().splitlines()]


@pytest.mark.parametrize('fault',['UNOBSERVABLE','ERROR'])
def test_manual_reinspection_runs_new_b_check_without_consuming_or_replaying_robot(tmp_path,monkeypatch,fault):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    r=MvpIntegration(ROOT,tmp_path,fixture_design=dict(design_version=1,blocks=[BLOCK]))
    original=r.observe;state={'fault':True}
    def observe(context,active):
        if context['check_kind']=='STEP' and state['fault']:
            if fault=='ERROR':raise RuntimeError('injected transient capture failure')
            return dict(status='OK',visible_blocks=[],verified_regions=[],reason='injected occlusion',
                        check_id=context['check_id'],observation_seq=context['observation_seq']),{}
        return original(context,active)
    r.observe=observe
    try:
        r.command('START');settle(r,lambda:r.workflow.status=='HOLD',approve=True)
        old=deepcopy(r.workflow.inspection);current=deepcopy(r.workflow.current)
        assert old['status']==fault and current==r.b.inspection.current
        assert not r.workflow.completed and r.slot_indices[('2x2x1','blue')]==2
        for _ in range(10):r.poll();time.sleep(.02)
        state['fault']=False
        assert r.command('REINSPECT')
        settle(r,lambda:r.workflow.status=='COMPLETE')
        assert r.slot_indices[('2x2x1','blue')]==2 and len(r.scene)==1
        assert len(r.workflow.completed)==1 and r.workflow.current==r.b.inspection.current
        assert r.workflow.completed[0]['check_id']!=old['check_id']
        rows=log_rows(r,tmp_path)
        assert sum(x['event']=='ROBOT_GRIP_STARTED' and x['result']['label']=='PICKUP_CLOSE' for x in rows)==1
        assert sum(x['event']=='ROBOT_CONTACT_SUCCEEDED' for x in rows)==1
        assert not any(x['event']=='ROBOT_COMMAND_REJECTED' for x in rows)
        if fault=='ERROR':
            assert any(x['event']=='CHECK_RESULT' and x['result']['response']['status']=='ERROR' for x in rows)
    finally:r.close()


def test_stop_during_mismatch_dialogue_resumes_fresh_intent_without_robot_replay(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    r=MvpIntegration(ROOT,tmp_path,fixture_design=dict(design_version=1,blocks=[BLOCK]))
    original=r.observe
    def observe(context,active):
        value,diagnostics=original(context,active)
        if context['check_kind']=='STEP':value['visible_blocks']=[dict(BLOCK,color='yellow')]
        return value,diagnostics
    r.observe=observe
    try:
        r.command('START');settle(r,lambda:r.workflow.status=='WAIT_INTENT',approve=True)
        before=deepcopy(r.workflow.approved);current=deepcopy(r.workflow.current)
        old=deepcopy(r.workflow.active)
        r.scene=deepcopy(current['blocks'])
        assert r.command('STOP')
        settle(r,lambda:r.workflow.status=='STOPPED')
        assert r.workflow.execution_id is None
        assert r.command('RESUME')
        settle(r,lambda:r.workflow.status=='WAIT_INTENT' and r.workflow.active is not None)
        assert r.workflow.active['request']['request_id']!=old['request']['request_id']
        assert r.workflow.approved==before and r.workflow.current==current
        assert not r.workflow.receive(old['port'],old['request']['request_id'],dict(status='OK',hri_result='KEEP',design=before))
        rows=log_rows(r,tmp_path)
        assert sum(x['event']=='ROBOT_GRIP_STARTED' and x['result']['label']=='PICKUP_CLOSE' for x in rows)==1
        assert any(x['event']=='ROBOT_STOP_VERIFIED' for x in rows)
        assert not any(x['event']=='ROBOT_COMMAND_REJECTED' for x in rows)
    finally:r.close()


def test_stop_in_initial_dialogue_checks_mock_idle_and_restarts_fresh_c_request(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    r=MvpIntegration(ROOT,tmp_path)
    try:
        assert r.command('START')
        settle(r,lambda:r.c_pending is not None)
        old=r.workflow.active['request']['request_id']
        assert r.command('STOP');settle(r,lambda:r.workflow.status=='STOPPED')
        assert r.workflow.reason=='NO_MOCK_MOTION_PENDING'
        assert r.command('RESUME');settle(r,lambda:r.c_pending is not None)
        assert r.workflow.active['request']['request_id']!=old
        assert r.workflow.approved is None and r.workflow.current['current_revision']==0
        assert not any(x['event']=='ROBOT_EXECUTION_STARTED' for x in log_rows(r,tmp_path))
    finally:r.close()
