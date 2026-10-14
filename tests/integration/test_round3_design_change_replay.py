"""C intent/review + A replan + native D + B; no API/audio/robot/camera."""
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest

from app.mvp_integration import MvpIntegration

ROOT=Path(__file__).resolve().parents[2]


def inputs(case):
    fixture='round3_difference_replay.json' if case=='mismatch' else 'round3_design_change_replay.json'
    config=json.loads((ROOT/'interfaces/fixtures'/fixture).read_text())
    design=json.loads((ROOT/'interfaces/fixtures/round3_abcd_design.json').read_text())
    return config,design


def logs(runtime,path):
    return [json.loads(line) for line in (path/(runtime.workflow.job_id+'.jsonl')).read_text().splitlines()]


def make_runtime(config,design,path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    # Persist each test's observations/candidate inputs, just as the CLI reads JSON.
    (path/'scenario.json').write_text(json.dumps(config))
    runtime=MvpIntegration(ROOT/'robot_control_integration',path,fixture_design=design,
        round3_step_replay=json.loads((path/'scenario.json').read_text()))
    return runtime


def drive(runtime,case,condition,*,review=None):
    requested=False;deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        runtime.poll()
        if case=='user' and not requested and runtime.workflow.execution is not None:
            assert runtime.command('REQUEST_DESIGN_CHANGE')
            requested=True
        if case=='deferred' and not requested and runtime.workflow.reason=='DESIGN_CHANGE_REPLAY_AWAITING_USER_REQUEST':
            assert runtime.workflow.current['blocks'] and runtime.workflow.execution_id is None
            assert runtime.command('REQUEST_DESIGN_CHANGE')
            requested=True
        if runtime.workflow.candidate:
            runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
        if runtime.c_pending:
            port,payload=runtime.c_pending
            if port=='c.review' and payload['candidate']['design_version']==2 and review:
                if review(runtime,payload):return
            assert runtime.answer('바꿔줘' if port=='c.intent' else '좋아 이걸로 하자')
        if condition():return
        time.sleep(.01)
    pytest.fail(str((runtime.workflow.status,runtime.workflow.reason)))


@pytest.mark.parametrize('case',['user','deferred','mismatch'])
def test_revised_approval_replans_only_remaining_block(tmp_path,monkeypatch,case):
    config,design=inputs(case)
    expected=deepcopy(config['revised_candidates'][1 if case=='mismatch' else 0])
    runtime=make_runtime(config,design,tmp_path,monkeypatch)
    reviewed=[]
    def review(r,payload):
        log=logs(r,tmp_path)
        assert r.workflow.approved==design
        assert r.workflow.current['blocks']==expected['current']
        assert sum(row['event']=='PLAN_ADOPTED' for row in log)==1
        assert sum(row['event']=='ROBOT_EXECUTION_STARTED' for row in log)==1
        reviewed.append(True)
        return False
    try:
        assert runtime.command('START')
        drive(runtime,case,lambda:runtime.workflow.status in ('COMPLETE','HOLD'),review=review)
        assert runtime.workflow.status=='COMPLETE',runtime.workflow.reason
        assert reviewed==[True]
        assert runtime.workflow.approved==dict(design_version=2,blocks=expected['blocks'])
        assert runtime.workflow.current['blocks']==expected['blocks']
        log=logs(runtime,tmp_path)
        plans=[row for row in log if row['event']=='PLAN_ADOPTED']
        assert len(plans)==2
        assert plans[1]['result']['base_current']['blocks']==expected['current']
        assert len(plans[1]['result']['plan']['steps'])==1
        assert plans[1]['result']['plan']['steps'][0]['after']==expected['blocks'][1]
        starts=[row['result'] for row in log if row['event']=='ROBOT_EXECUTION_STARTED']
        assert len(starts)==2 and starts[0]['execution_id']!=starts[1]['execution_id']
        assert starts[0]['plan_id']!=starts[1]['plan_id']
        assert sum(row['event']=='ROBOT_GRIP_SUCCEEDED' for row in log)==2
        assert runtime.workflow.storage=='NOT_STARTED'
        cresults=[row['result'] for row in log if row['event']=='MODULE_RESULT' and row['result']['port']=='c.intent']
        assert cresults[0]['response']['hri_result']=='REVISE'
        runtime.workflow.snapshot()
    finally:runtime.close()


@pytest.mark.parametrize('case',['user','mismatch'])
def test_stop_before_revised_approval_rejects_late_c_result(tmp_path,monkeypatch,case):
    config,design=inputs(case);runtime=make_runtime(config,design,tmp_path,monkeypatch)
    try:
        assert runtime.command('START')
        drive(runtime,case,lambda:False,review=lambda *_:True)
        port,payload=deepcopy(runtime.c_pending)
        before=deepcopy(runtime.workflow.current)
        assert runtime.command('STOP')
        deadline=time.monotonic()+5
        while runtime.workflow.status!='STOPPED' and time.monotonic()<deadline:
            runtime.poll();time.sleep(.01)
        assert runtime.workflow.status=='STOPPED'
        assert not runtime.workflow.receive(port,payload['request_id'],dict(status='OK',hri_result='APPROVE',design=payload['candidate']))
        assert runtime.workflow.current==before and runtime.workflow.approved==design
        assert sum(row['event']=='PLAN_ADOPTED' for row in logs(runtime,tmp_path))==1
        assert not runtime.command('RESUME')
    finally:runtime.close()


@pytest.mark.parametrize('fault',['remove_current','missing_candidate','missing_measurement','old_observation'])
def test_replan_faults_never_replace_confirmed_current(tmp_path,monkeypatch,fault):
    config,design=inputs('user')
    expected_current=deepcopy(config['revised_candidates'][0]['current'])
    monkeypatch.setattr('app.c_design.designer.RETRY_DELAY',0.)
    if fault=='remove_current':config['revised_candidates'][0]['blocks']=config['revised_candidates'][0]['blocks'][1:]
    elif fault=='missing_candidate':config['revised_candidates']=[]
    elif fault=='missing_measurement':config['measurements']=config['measurements'][:2]
    else:config['saved_observations'][2]['design_version']=1
    runtime=make_runtime(config,design,tmp_path,monkeypatch)
    try:
        assert runtime.command('START')
        drive(runtime,'user',lambda:runtime.workflow.status in ('HOLD','COMPLETE'))
        assert runtime.workflow.status=='HOLD'
        assert runtime.workflow.current['blocks']==expected_current
        log=logs(runtime,tmp_path)
        assert sum(row['event']=='ROBOT_EXECUTION_STARTED' for row in log)==(2 if fault=='old_observation' else 1)
        assert sum(row['event']=='PLAN_ADOPTED' for row in log)==(2 if fault in ('missing_measurement','old_observation') else 1)
        if fault=='old_observation':assert 'DESIGN_VERSION_MISMATCH' in runtime.workflow.reason
        assert runtime.workflow.storage=='NOT_STARTED'
    finally:runtime.close()


@pytest.mark.parametrize('mode,answers',[('0',None),('1',['바꿔줘'])])
def test_replay_candidate_provider_cannot_enter_audio_or_live_llm(monkeypatch,mode,answers):
    from app.c_design.main import run_design_change
    monkeypatch.setenv('C_DESIGN_USE_LLM',mode)
    config,design=inputs('user')
    def forbidden(*a,**kw):raise AssertionError('replay provider must not be called')
    result=run_design_change(design,config['revised_candidates'][0]['current'],
        reason='USER_DESIGN_CHANGE',text_answers=answers,revised_generator=forbidden)
    assert result['status']=='FAILED'
    assert result['error']['code']=='REPLAY_GENERATOR_TEXT_ONLY'
