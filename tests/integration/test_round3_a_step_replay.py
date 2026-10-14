"""Real A functions and stdio native round2 runner; all devices remain MOCK."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.mvp_integration import MvpIntegration

ROOT = Path(__file__).resolve().parents[2]
ROBOT = ROOT/'robot_control_integration'
BLOCK = dict(brick_type='2x2x1', color='blue', x=6, y=6, layer=1, orientation_deg=0)


def install(tmp_path, monkeypatch, *, missing=None, stop=False):
    monkeypatch.setenv('C_DESIGN_USE_LLM', '0')
    runtime = MvpIntegration(ROBOT, tmp_path, fixture_design=dict(design_version=1, blocks=[BLOCK]),
        round3_step_replay=dict(provenance='SYNTHETIC'))
    emit = runtime.emit
    documents = []
    def connect(port, payload):
        if port == 'robot.EXECUTE':
            profile = payload['bundle']['d_profile']
            settings = next(iter(profile['steps'].values()))
            reference = settings['reference_pose']
            # Explicit synthetic measurement for the actual A-selected block;
            # this is not operator teaching or camera calibration.
            runtime.round3_step_replay = dict(provenance='SYNTHETIC', providers=['pickup','alignment'],
                measured=dict(block=deepcopy(BLOCK), pad_contact_pose=deepcopy(reference),
                    press_width_mm=4., landing_support_verified=True, release_sweep_verified=True,
                    press_sweep_verified=True, measurement_ref='SYNTHETIC_TEST_ONLY'))
            if missing == 'measured':runtime.round3_step_replay.pop('measured')
            if missing == 'provider':runtime.round3_step_replay['providers']=['pickup']
            if missing == 'block':runtime.round3_step_replay['measured']['block']['x']=7
        emit(port, payload)
        if port == 'robot.EXECUTE':
            documents.append(deepcopy(runtime.last_document))
            if stop:runtime.command('STOP')
    runtime.workflow.emit = connect
    return runtime, documents


def settle(runtime, condition):
    deadline = time.monotonic()+20
    while time.monotonic() < deadline:
        runtime.poll()
        if runtime.workflow.candidate:
            runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
        if runtime.c_pending:runtime.answer('좋아 이걸로 하자')
        if condition():return
        time.sleep(.01)
    pytest.fail(str((runtime.workflow.status, runtime.workflow.reason)))


@pytest.mark.parametrize('missing', [None,'measured','provider','block'])
def test_actual_a_step_reaches_round2_or_holds_without_current_commit(tmp_path, monkeypatch, missing):
    runtime, documents = install(tmp_path, monkeypatch, missing=missing)
    try:
        assert runtime.command('START')
        settle(runtime, lambda:runtime.workflow.status=='HOLD')
        assert len(documents)==1
        doc=documents[0]
        assert doc['assessment']['status']=='CANDIDATE' and doc['motion']['status']=='CANDIDATE'
        assert doc['request']['selected_step']['after']==BLOCK
        rows=[json.loads(line) for line in (tmp_path/(runtime.workflow.job_id+'.jsonl')).read_text().splitlines()]
        events=[row['event'] for row in rows]
        if missing is None:
            assert runtime.workflow.reason=='ROUND3_STEP_REPLAY_FINISHED_NOT_ASSEMBLY_CONFIRMED'
            assert 'ROBOT_ROUND2_STEP_BRANCH' in events
            assert 'ROBOT_PRESS_RESULT' in events
            assert 'ROBOT_ROUND3_STEP_REPLAY_RESULT' in events
            assert runtime.slot_indices[('2x2x1','blue')]==2
        else:
            assert 'ROBOT_EXECUTION_STARTED' not in events
            assert 'ROBOT_ROUND3_STEP_REPLAY_RESULT' not in events
        assert 'ROBOT_INSPECTION_REQUIRED' not in events
        assert runtime.workflow.current==dict(current_revision=0,blocks=[])
        assert runtime.workflow.completed==[] and runtime.workflow.storage=='NOT_STARTED'
        runtime.workflow.snapshot()
    finally:runtime.close()


def test_stop_after_execute_never_adopts_replay_success(tmp_path, monkeypatch):
    runtime, documents=install(tmp_path, monkeypatch, stop=True)
    try:
        assert runtime.command('START')
        settle(runtime, lambda:runtime.workflow.status=='STOPPED')
        identity=runtime.workflow.execution_id
        assert not runtime.workflow.robot_event(dict(event='ROUND3_STEP_REPLAY_RESULT',
            data=dict(execution_id=identity,provenance='SYNTHETIC')))
        assert runtime.workflow.status=='STOPPED'
        assert runtime.workflow.current['blocks']==[] and runtime.workflow.completed==[]
    finally:runtime.close()


def test_real_constructor_rejects_replay_before_transport(monkeypatch,tmp_path):
    def forbidden(*args,**kwargs):raise AssertionError('transport must not start')
    monkeypatch.setattr('app.mvp_integration.RobotProcess',forbidden)
    with pytest.raises(ValueError,match='MOCK_ONLY'):
        MvpIntegration(ROBOT,tmp_path,robot_mode='REAL',round3_step_replay={})


def test_native_stop_at_first_move_prevents_all_later_writes(tmp_path,monkeypatch):
    runtime, documents=install(tmp_path,monkeypatch)
    try:
        assert runtime.command('START')
        settle(runtime,lambda:runtime.workflow.status=='HOLD')
        document=documents[0]
    finally:runtime.close()
    code='''
import json,sys
from app.round3_step_replay import Round3StepReplay
rows=[];grips_at_stop=[]
def record(event,data):
    rows.append(event)
    if event=='STEP_MOVE':
        grips_at_stop.append(len(runtime.raw.grips))
        runtime.stop()
runtime=Round3StepReplay(json.load(sys.stdin),record)
runtime.start();runtime.run()
assert runtime.state=='STOPPED'
assert runtime.raw.moves==[]
assert len(runtime.raw.grips)==grips_at_stop[0]
assert rows.count('STEP_MOVE')==1
assert 'ROUND3_STEP_REPLAY_RESULT' not in rows
assert 'STOP_VERIFIED' in rows
assert not runtime.can_resume()
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROBOT,
        input=json.dumps(document),text=True,capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_native_real_mode_rejects_new_route_before_device_import(tmp_path,monkeypatch):
    runtime,documents=install(tmp_path,monkeypatch)
    try:
        assert runtime.command('START')
        settle(runtime,lambda:runtime.workflow.status=='HOLD')
    finally:runtime.close()
    # REAL session values cannot turn synthetic providers into live permission.
    doc=deepcopy(documents[0]);doc['session']['backend']='REAL'
    message=json.dumps(dict(command='EXECUTE',document=doc))+'\n'+json.dumps(dict(command='CLOSE'))+'\n'
    result=subprocess.run([sys.executable,'-m','scripts.robot_integration_runtime','--mode','REAL'],
        cwd=ROBOT,input=message,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    rows=[json.loads(line) for line in result.stdout.splitlines()]
    rejected=next(row for row in rows if row['event']=='COMMAND_REJECTED')
    assert rejected['data']['reason']=='ROUND3_STEP_REPLAY_IS_MOCK_EXECUTE_ONLY'
    assert not any(row['event']=='EXECUTION_STARTED' for row in rows)


def test_documented_fixture_uses_actual_a_with_no_runtime_injection(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    config=json.loads((ROOT/'interfaces/fixtures/round3_step_replay.json').read_text())
    design=json.loads((ROOT/'interfaces/fixtures/cad_trial_blue_single.json').read_text())
    runtime=MvpIntegration(ROBOT,tmp_path,fixture_design=design,round3_step_replay=config)
    try:
        assert runtime.command('START')
        settle(runtime,lambda:runtime.workflow.status=='HOLD')
        assert runtime.workflow.reason=='ROUND3_STEP_REPLAY_FINISHED_NOT_ASSEMBLY_CONFIRMED'
        assert runtime.last_document['request']['selected_step']['after']==config['measured']['block']
        assert runtime.last_document['round2_replay']==config
    finally:runtime.close()
