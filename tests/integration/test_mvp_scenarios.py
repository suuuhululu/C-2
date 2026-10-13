"""A/B/C actual functions + MOCK D/gesture camera. No hardware or external API."""
from copy import deepcopy
import json
import os
from pathlib import Path
import time
import pytest
from app.mvp_integration import MvpIntegration

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),reason='C2_ROBOT_ROOT required')


def block(x=4,y=4,layer=1,kind='2x3x1'):
    return dict(brick_type=kind,color='blue',x=x,y=y,layer=layer,orientation_deg=0)


def mixed_blocks():
    return [block(x=x,layer=1) for x in (4,6,8)]+[block(x=x,layer=2) for x in (5,7,9)]+[block(x=10,layer=3)]


def poll_until(r,condition,seconds=65,answer=True):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        r.poll();r.workflow.snapshot()
        if r.workflow.candidate:r.workflow.preview_ready(r.workflow.candidate['request_id'])
        if answer and r.c_pending:r.answer('좋아 이걸로 하자')
        if condition():return
        if r.workflow.status=='HOLD' and r.workflow.reason!='STOP_PENDING' and r.workflow.check is None:pytest.fail(r.workflow.reason)
        time.sleep(.02)
    pytest.fail('scenario timeout: '+str(r.workflow.status)+' '+str(r.workflow.reason))


def rows(path):
    return [json.loads(s) for s in next(path.glob('*.jsonl')).read_text().splitlines()]


@pytest.mark.parametrize('direct',[False,True])
def test_single_plan_mixes_direct_assisted_manual_and_gestures_then_b_final(tmp_path,monkeypatch,direct):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    design=dict(design_version=1,blocks=mixed_blocks())
    r=MvpIntegration(ROOT,tmp_path,fixture_design=design)
    # This fixture represents an x-grip-only robot and accessible human y corridor.
    r.workflow.settings['assembly_context']['grip_axes']=['x'];r.direct_handover=direct
    try:
        r.command('START');poll_until(r,lambda:r.workflow.status=='COMPLETE')
        assert r.workflow.current==r.b.inspection.current
        assert r.workflow.current['current_revision']==len(design['blocks'])
        actions=r.workflow.whole_result['action_proposals']
        assert {a['mode'] for a in actions}=={'ROBOT_GRIP','HUMAN_ASSEMBLY'}
        assert {'NONE','PRESS','PRESS_AND_HOLD','MANUAL_ASSEMBLY'} <= {a['assistance_kind'] for a in actions}
        log=rows(tmp_path);names=[row['event'] for row in log]
        assert names.count('ROBOT_CONTACT_SUCCEEDED')==3
        cues=[row['result'] for row in log if row['event']=='ROBOT_GESTURE_READY_CONFIRMED']
        assert {'HELP_READY','ASSEMBLY_ACK','RECEIVE'} <= {c['kind'] for c in cues}
        assert all(c['source']=='FAKE' for c in cues)
        labels=[row['result']['label'] for row in log if row['event']=='ROBOT_GRIP_STARTED']
        assert ('DIRECT_HANDOVER' in labels) is direct
        assert ('TRAY_RELEASE' in labels) is (not direct)
        assert names.count('ROBOT_HELP_RELEASE_GUIDANCE')==2
        assert names.count('ASSEMBLY_COMPLETED')==1
        assert r.workflow.bundle['plan']['base_current_revision']==0
        assert not any(row['event']=='ROBOT_COMMAND_REJECTED' for row in log)
    finally:r.close()


def test_stop_at_help_resume_keeps_design_and_pickup_but_requires_new_thumb(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    r=MvpIntegration(ROOT,tmp_path,fixture_design=dict(design_version=1,blocks=[block(),block(x=5,layer=2),block(x=6,layer=3)]))
    r.auto_gestures=False
    try:
        r.command('START');poll_until(r,lambda:r.ready_signal is not None and r.ready_signal['kind']=='HELP_READY')
        before=deepcopy(r.workflow.approved);old=deepcopy(r.ready_signal)
        assert r.workflow.current['current_revision']==1
        r.command('STOP');poll_until(r,lambda:r.workflow.status=='STOPPED')
        assert r.command('RESUME')
        poll_until(r,lambda:r.ready_signal is not None and r.ready_signal['request_id']!=old['request_id'])
        assert r.ready_signal['kind']=='HELP_READY'
        assert r.workflow.approved==before
        assert r.workflow.current['current_revision']==1
        r.auto_gestures=True
        poll_until(r,lambda:r.workflow.status=='COMPLETE')
        log=rows(tmp_path)
        assert sum(row['event']=='ROBOT_GRIP_STARTED' and row['result']['label']=='PICKUP_CLOSE' for row in log)==3
        assert sum(row['event']=='MODULE_RESULT' and row['result'].get('port')=='c.review' for row in log)<=1
        assert r.workflow.current==r.b.inspection.current
    finally:r.close()


def test_unobservable_b_keeps_current_until_new_mock_observation(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    r=MvpIntegration(ROOT,tmp_path,fixture_design=dict(design_version=1,blocks=[block()]))
    real_observe=r.observe;seen=[]
    def observe(context,active):
        if context['check_kind']=='STEP' and not seen:
            seen.append(True)
            return dict(status='OK',visible_blocks=[],verified_regions=[],reason=None,
                check_id=context['check_id'],observation_seq=context['observation_seq']),{}
        return real_observe(context,active)
    r.observe=observe
    try:
        r.command('START')
        end=time.monotonic()+20
        while time.monotonic()<end:
            r.poll()
            if r.workflow.candidate:r.workflow.preview_ready(r.workflow.candidate['request_id'])
            if r.c_pending:r.answer('좋아 이걸로 하자')
            if r.workflow.status=='HOLD':break
            time.sleep(.02)
        assert r.workflow.status=='HOLD'
        assert r.workflow.current['current_revision']==0 and not r.workflow.completed
        assert not r.workflow.status=='COMPLETE'
        assert r.command('REINSPECT')
        poll_until(r,lambda:r.workflow.status=='COMPLETE')
        assert r.workflow.current==r.b.inspection.current
    finally:r.close()
