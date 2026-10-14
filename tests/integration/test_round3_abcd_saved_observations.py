"""Actual C review, A planning, native round2 MOCK and B comparison; stored inputs."""
from copy import deepcopy
import json
from pathlib import Path
from threading import Event
import time

import pytest

from app.mvp_integration import MvpIntegration

ROOT = Path(__file__).resolve().parents[2]


def load():
    config=json.loads((ROOT/'interfaces/fixtures/round3_abcd_replay.json').read_text())
    design=json.loads((ROOT/'interfaces/fixtures/round3_abcd_design.json').read_text())
    return config,design


def make_runtime(tmp_path,monkeypatch,config,design):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    return MvpIntegration(ROOT/'robot_control_integration',tmp_path,
        fixture_design=design,round3_step_replay=config)


def settle(runtime,condition):
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        runtime.poll()
        if runtime.workflow.candidate:
            runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
        if runtime.c_pending:runtime.answer('좋아 이걸로 하자')
        if condition():return
        time.sleep(.01)
    pytest.fail(str((runtime.workflow.status,runtime.workflow.reason)))


def rows(runtime,tmp_path):
    return [json.loads(line) for line in (tmp_path/(runtime.workflow.job_id+'.jsonl')).read_text().splitlines()]


def test_two_actual_a_steps_only_advance_after_b_matches(tmp_path,monkeypatch):
    config,design=load();before=deepcopy(config)
    runtime=make_runtime(tmp_path,monkeypatch,config,design)
    try:
        assert runtime.command('START')
        settle(runtime,lambda:runtime.workflow.status in ('COMPLETE','HOLD'))
        assert runtime.workflow.status=='COMPLETE',runtime.workflow.reason
        assert len(runtime.workflow.completed)==2
        assert runtime.workflow.current['blocks']==design['blocks']
        assert runtime.workflow.current['current_revision']==2
        log=rows(runtime,tmp_path)
        checks=[r for r in log if r['event']=='CHECK_RESULT' and r['result']['disposition']=='ACCEPTED']
        assert [r['result']['response']['check_kind'] for r in checks]==['INITIAL','STEP','STEP','FINAL']
        assert [r['result']['response']['comparison'] for r in checks[1:]]==['MATCH']*3
        executions=[i for i,r in enumerate(log) if r['event']=='ROBOT_EXECUTION_STARTED']
        assert len(executions)==2
        first_match=next(i for i,r in enumerate(log) if r['event']=='CHECK_RESULT'
            and r['result']['response']['check_kind']=='STEP')
        assert executions[0]<first_match<executions[1]
        assert any(r['event']=='MODULE_RESULT' and r['result']['port']=='c.review' for r in log)
        assert sum(r['event']=='ROBOT_PRESS_RESULT' for r in log)==2
        assert runtime.saved_observation_index==4 and config==before
        assert runtime.workflow.storage=='NOT_STARTED'
        assert not runtime.command('REINSPECT')
        assert not runtime.command('REQUEST_DESIGN_CHANGE')
        runtime.workflow.snapshot()
    finally:runtime.close()


@pytest.mark.parametrize('kind',['MISMATCH','UNOBSERVABLE'])
@pytest.mark.parametrize('index',[1,2,3])
def test_fault_in_saved_step_or_final_holds_without_replan(tmp_path,monkeypatch,kind,index):
    config,design=load()
    observation=config['saved_observations'][index]['observation']
    if kind=='MISMATCH':
        observation['visible_blocks'][-1]['color']='yellow'
    else:
        observation.update(status='UNOBSERVABLE',visible_blocks=[],verified_regions=[],reason='SAVED_OCCLUSION')
    runtime=make_runtime(tmp_path,monkeypatch,config,design)
    try:
        assert runtime.command('START')
        settle(runtime,lambda:runtime.workflow.status in ('HOLD','COMPLETE'))
        assert runtime.workflow.status=='HOLD'
        assert runtime.workflow.inspection['comparison']==kind
        assert len(runtime.workflow.completed)==min(index-1,2)
        log=rows(runtime,tmp_path)
        assert sum(r['event']=='ROBOT_EXECUTION_STARTED' for r in log)==min(index,2)
        assert not any(r['event']=='MODULE_RESULT' and r['result']['port']=='c.intent' for r in log)
        if kind=='UNOBSERVABLE':
            assert runtime.workflow.current['blocks']==design['blocks'][:min(index-1,2)]
        else:
            assert runtime.workflow.current['blocks'][-1]['color']=='yellow'
        assert runtime.workflow.storage=='NOT_STARTED'
    finally:runtime.close()


@pytest.mark.parametrize('fault',['missing','wrong_step','wrong_kind'])
def test_saved_input_errors_never_fall_back_to_generated_match(tmp_path,monkeypatch,fault):
    config,design=load()
    if fault=='missing':config['saved_observations']=config['saved_observations'][:1]
    elif fault=='wrong_step':config['saved_observations'][1]['target_block']['x']=10
    else:config['saved_observations'][1]['check_kind']='FINAL'
    runtime=make_runtime(tmp_path,monkeypatch,config,design)
    try:
        assert runtime.command('START')
        settle(runtime,lambda:runtime.workflow.status=='HOLD')
        assert runtime.workflow.inspection['status']=='ERROR'
        assert 'SAVED_OBSERVATION_' in runtime.workflow.reason
        assert runtime.workflow.completed==[] and runtime.workflow.current['blocks']==[]
        assert sum(r['event']=='ROBOT_EXECUTION_STARTED' for r in rows(runtime,tmp_path))==1
    finally:runtime.close()


def test_stop_while_b_observes_rejects_late_observation(tmp_path,monkeypatch):
    config,design=load()
    runtime=make_runtime(tmp_path,monkeypatch,config,design)
    entered,release=Event(),Event()
    observe=runtime.observe
    def delayed(context,active):
        if context['check_kind']=='STEP':
            entered.set()
            if not release.wait(10):raise RuntimeError('TEST_OBSERVER_TIMEOUT')
        return observe(context,active)
    runtime.observe=delayed
    try:
        assert runtime.command('START')
        settle(runtime,entered.is_set)
        check=deepcopy(runtime.workflow.check)
        assert not runtime.workflow.robot_event(dict(event='ROUND3_STEP_REPLAY_RESULT', data=dict(
            execution_id=runtime.workflow.execution_id, provenance='SYNTHETIC', saved_observation_flow=True)))
        assert runtime.workflow.check==check
        assert runtime.command('STOP')
        release.set()
        settle(runtime,lambda:runtime.workflow.status=='STOPPED')
        assert runtime.workflow.completed==[] and runtime.workflow.current['blocks']==[]
        assert not runtime.command('RESUME')
        assert runtime.workflow.check is None
        assert sum(r['event']=='ROBOT_EXECUTION_STARTED' for r in rows(runtime,tmp_path))==1
    finally:
        release.set()
        runtime.close()


def test_saved_mode_rejects_unmarked_input_before_transport(tmp_path,monkeypatch):
    config,design=load();config['provenance']='LIVE'
    def forbidden(*a,**kw):raise AssertionError('must not initialize transport')
    monkeypatch.setattr('app.mvp_integration.RobotProcess',forbidden)
    with pytest.raises(ValueError,match='REQUIRES_SYNTHETIC'):
        make_runtime(tmp_path,monkeypatch,config,design)
