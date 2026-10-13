"""실물 준비 경계 검사. 실제 RobotProcess/ROS/Modbus는 호출하지 않는다."""
from copy import deepcopy
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
import time

import pytest

from app import cad_real_trial as trial

ROOT = Path(os.environ.get('C2_ROBOT_ROOT', ''))
pytestmark = pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),
    reason='C2_ROBOT_ROOT required')


def design():
    return trial.read('interfaces/fixtures/cad_trial_yellow_blue_stack.json')


def receipt():
    sample = dict(posx=[418.27,-181.19,194.73,125.,-175.,124.], velx=[0.]*6,
        tcp='GripperDA_v4', tool='ToolWeight0', robot_state=1, robot_mode=1, drl_state=3,
        motion_status=0, gripper_status=0, gripper_width_mm=48., query_duration_s=.01)
    return dict(captured_unix_s=time.time(), physical_commands=0,
                samples=[deepcopy(sample) for _ in range(3)])


def test_whole_plan_uses_both_colors_no_rotation_no_b():
    prepared = trial.prepare(design(), ROOT)
    assert prepared['plan']['base_current_revision'] == 0
    assert [r['step']['after']['color'] for r in prepared['preview']] == ['yellow','blue']
    assert [r['slot'] for r in prepared['preview']] == [1,1]
    assert all(r['action']['mode'] == 'ROBOT_GRIP' and r['action']['assistance_kind'] == 'NONE'
               for r in prepared['preview'])


@pytest.mark.parametrize('kind,color,orientation',[
    ('2x2x1','yellow',0),('2x2x1','blue',0),
    ('2x3x1','yellow',0),('2x3x1','blue',0),('1x2x1','red',0),
    ('2x3x1','yellow',90),('2x3x1','blue',90),('1x2x1','red',90)])
def test_c_design_supported_sizes_create_a_routes_and_d_documents(kind,color,orientation):
    value=dict(design_version=1,blocks=[dict(brick_type=kind,color=color,
        x=11,y=11,layer=1,orientation_deg=orientation)])
    p=trial.prepare(value,ROOT)
    docs=trial.preview_routes(p)
    assert p['design']==value and len(docs)==1
    assert docs[0]['step']['block']==value['blocks'][0]
    assert docs[0]['step']['reservation']['slot_id']==f'{color}_{kind}_01'
    assert docs[0]['motion']['status']=='CANDIDATE'
    s=next(iter(docs[0]['d_profile']['steps'].values()))
    assert len(s['pickup_pose'])==len(s['reference_pose'])==6


@pytest.mark.parametrize('change', [('brick_type','4x4x1'),('color','red'),('orientation_deg',90)])
def test_out_of_scope_design_rejected_before_device(change):
    value = design(); value['blocks'][0][change[0]] = change[1]
    with pytest.raises(ValueError,match='노랑/파랑'):
        trial.prepare(value, ROOT)


@pytest.mark.parametrize('field,value', [('robot_mode',0),('motion_status',1),('gripper_status',2),
    ('gripper_width_mm',-1.),('tcp','old'),('query_duration_s',.6),('velx',[5.01]*6)])
def test_bad_live_state_holds(field, value):
    r = receipt(); r['samples'][-1][field] = value
    frame = trial.measured_inputs(ROOT)['frame']
    with pytest.raises(ValueError):
        trial.live_robot_state(r, frame)


def test_old_receipt_and_moving_pose_are_rejected():
    r = receipt(); frame = trial.measured_inputs(ROOT)['frame']
    with pytest.raises(ValueError,match='FRESH_READ'):
        trial.live_robot_state(r, frame, now=r['captured_unix_s']+.51)
    r['samples'][-1]['posx'][0] += 1.01
    with pytest.raises(ValueError,match='NOT_STILL'):
        trial.live_robot_state(r, frame)


def test_stop_snapshot_accepts_residual_speed_and_pose_noise():
    r=receipt();frame=trial.measured_inputs(ROOT)['frame']
    r['samples'][0]['velx']=[-.0099941483,-.0169404615,0.,-.0000500448,-.0001962454,-.0026575383]
    r['samples'][1]['posx'][0]+=.5
    assert trial.live_robot_state(r,frame)['stopped_verified']


@pytest.mark.parametrize('axis',[0,3])
def test_stop_snapshot_accepts_reviewed_velocity_boundary(axis):
    r=receipt();frame=trial.measured_inputs(ROOT)['frame']
    r['samples'][-1]['velx'][axis]=5.
    assert trial.live_robot_state(r,frame)['stopped_verified']


def test_real_document_has_new_session_actual_refs_and_contact_gate():
    p = trial.prepare(design(), ROOT)
    state = trial.live_robot_state(receipt(), p['inputs']['frame'])
    d = trial.execution_document(p,p['preview'][0],state, review_ref='UNIT_OPERATOR_REVIEW',
                                receipt_ref='UNIT_FAKE_RECEIPT_NO_DEVICE',start_zone='assembly')
    assert d['session']['backend'] == 'REAL' and d['session']['provenance'] == 'LIVE_D_RUNTIME'
    assert d['session']['trial_alignment_pending'] and d['session']['alignment_evidence_ref'] is None
    assert d['step']['current_revision'] is None
    assert 'MOCK' not in d['d_profile']['profile_id']
    assert not d['motion']['execution_allowed']
    assert d['d_profile']['transport_blending'] == dict(radius_mm=40., reviewed=True)
    assert d['d_profile']['transport_policy'] == 'REVIEWED_HORIZONTAL_BLENDING'
    assert d['session']['transport_blend_review_ref']=='UNIT_OPERATOR_REVIEW'
    # 로봇 저장소의 REAL admission만 검사. 드라이버 생성/실제 명령 없음.
    code = """
import json,sys
from app.assembly_step_bridge import build_plan
from app.control_session import validate_execution
from app.integration_motion_binding import verify_motion
d=json.load(sys.stdin)
p=build_plan(d['step'],d['d_profile'])
verify_motion(d['motion']['motion_proposal'],p,d['d_profile'],d['robot_state'])
validate_execution(p,d['d_profile'],d['session'],'full')
try: validate_execution(p,d['d_profile'],d['session'],'contact')
except ValueError as e: assert str(e)=='FRESH_ALIGNMENT_EVIDENCE_REQUIRED'
else: raise AssertionError('Contact bypassed actual alignment')
d['session']['no_vision_trial']=False
try: validate_execution(p,d['d_profile'],d['session'],'full')
except ValueError as e: assert str(e)=='FRESH_ALIGNMENT_EVIDENCE_REQUIRED'
else: raise AssertionError('Normal full path bypassed alignment')
print('ADMISSION_ONLY_NO_DEVICE_PASS')
"""
    result = subprocess.run([sys.executable,'-c',code],cwd=ROOT,input=json.dumps(d),text=True,
                            capture_output=True,timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'ADMISSION_ONLY_NO_DEVICE_PASS'


def test_prepare_mode_never_creates_robot_process(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'RobotProcess',lambda *a,**k:pytest.fail('REAL connected in prepare'))
    t = trial.Trial(ROOT,tmp_path,lambda *a:None)
    t.run(design(),None)
    assert t.result['status'] == 'PREPARED_NO_DEVICE_CONNECTION'
    assert t.result['completed_steps'] == []


def test_missing_operator_review_never_creates_real_process(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'RobotProcess',lambda *a,**k:pytest.fail('REAL connected without review'))
    t = trial.Trial(ROOT,tmp_path,lambda *a:None,execute=True)
    t.run(design(),None)
    assert t.result['status'] == 'HOLD' and 'ACTUAL_OPERATOR' in t.result['reason']


def test_local_execution_flow_with_fake_device_has_no_b_current_or_final(tmp_path,monkeypatch):
    documents = []
    class FakeRobot:
        def __init__(self,*a,**k): self.q=Queue(); self.process=self
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def poll(self): return 0
        def send(self,command,**data):
            if command=='READ_STATE': self.q.put(dict(event='STATE_SNAPSHOT',data=receipt()))
            elif command=='EXECUTE':
                documents.append(data['document'])
                self.q.put(dict(event='TRIAL_STEP_EXECUTED',data=dict(
                    execution_id=data['document']['session']['execution_id'])))
        def receive(self,timeout): return self.q.get(timeout=timeout)
    monkeypatch.setattr(trial,'RobotProcess',FakeRobot)
    t=trial.Trial(ROOT,tmp_path,lambda *a:None,execute=True)
    t.run(design(),'UNIT_OPERATOR_REVIEW')
    assert t.result['status']=='TRIAL_EXECUTION_FINISHED', t.result
    assert t.result['completed_steps']==['S01','S02'] and len(documents)==2
    assert all(d['step']['current_revision'] is None for d in documents)
    assert not t.result['b_called'] and not t.result['vision_confirmed'] and not t.result['assembly_completion']


def test_stop_before_execution_is_hold_without_device(tmp_path,monkeypatch):
    monkeypatch.setattr(trial,'RobotProcess',lambda *a,**k:pytest.fail('REAL connected after STOP'))
    t=trial.Trial(ROOT,tmp_path,lambda *a:None,execute=True); t.stop()
    t.run(design(),'UNIT_OPERATOR_REVIEW')
    assert t.result['status']=='HOLD' and t.result['reason']=='STOP_REQUESTED'


def test_five_layer_target_order_and_independent_supply_slots():
    value = trial.read('interfaces/fixtures/cad_trial_yellow_blue_five_layers.json')
    prepared = trial.prepare(value, ROOT)
    rows = prepared['preview']
    assert [(r['step']['after']['color'],r['step']['after']['layer'],r['slot']) for r in rows] == [
        ('yellow',1,1),('blue',2,1),('yellow',3,2),('blue',4,2),('yellow',5,3)]
    assert all((r['step']['after']['x'],r['step']['after']['y'],r['step']['after']['orientation_deg'])==(11,11,0) for r in rows)
    routes = trial.preview_routes(prepared)
    assert len(routes)==5


def test_real_preparation_wraps_supply_after_six():
    value = dict(design_version=1, blocks=[dict(brick_type='2x2x1',color='yellow',x=2+i*3,y=6,
        layer=1,orientation_deg=0) for i in range(7)])
    prepared = trial.prepare(value, ROOT)
    assert [r['slot'] for r in prepared['preview']] == [1,2,3,4,5,6,1]


@pytest.mark.parametrize('width', [31.8,35.,44.,44.1,45.6,58.])
def test_empty_gripper_can_start_closed_before_d_prepare_open(width):
    r=receipt()
    for sample in r['samples']:sample['gripper_width_mm']=width
    frame=trial.measured_inputs(ROOT)['frame']
    assert trial.live_robot_state(r,frame)['holding_confirmed'] is False


def test_start_gripper_hold_preserves_approval_and_rechecks_before_execute(tmp_path,monkeypatch):
    commands=[];owner=[None];reads=[0];pauses=[]
    class FakeRobot:
        def __init__(self,*a,**k):self.q=Queue();self.process=self
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def poll(self):return None
        def send(self,command,**data):
            commands.append((command,deepcopy(data)))
            if command=='READ_STATE':
                reads[0]+=1;r=receipt()
                for s in r['samples']:
                    s.update(gripper_status=2 if reads[0]<=2 else 0,gripper_width_mm=31.8)
                self.q.put(dict(event='STATE_SNAPSHOT',data=r))
            elif command=='EXECUTE':
                self.q.put(dict(event='TRIAL_STEP_EXECUTED',data=dict(
                    execution_id=data['document']['session']['execution_id'])))
        def receive(self,timeout):return self.q.get(timeout=timeout)
    def notify(event,data):
        if event=='TRIAL_PAUSED':
            assert not any(c=='EXECUTE' for c,_ in commands)
            assert owner[0].paused and data['stage']=='START_STATE'
            pauses.append(data);owner[0].resume()
    monkeypatch.setattr(trial,'RobotProcess',FakeRobot)
    t=owner[0]=trial.Trial(ROOT,tmp_path,notify,execute=True)
    t.run(design(),'UNIT_OPERATOR_REVIEW')
    assert t.result['status']=='TRIAL_EXECUTION_FINISHED',t.result
    assert t.result['completed_steps']==['S01','S02'] and len(pauses)==2
    assert [c for c,_ in commands]==['READ_STATE']*3+['EXECUTE','READ_STATE','EXECUTE']
    docs=[d['document'] for c,d in commands if c=='EXECUTE']
    assert [d['step']['reservation']['slot_id'] for d in docs]==['yellow_2x2x1_01','blue_2x2x1_01']
    assert all(next(iter(d['d_profile']['steps'].values()))['pickup_open_width_mm']==55. for d in docs)
    assert all(d['session']['operator_review_ref']=='UNIT_OPERATOR_REVIEW' for d in docs)
    assert not t.paused


@pytest.mark.parametrize('executed', [False,True])
def test_saved_approval_only_reused_when_no_execution_was_started(tmp_path,executed):
    approval=dict(status='OK',hri_result='APPROVE',design=design())
    trial.save(tmp_path/'c-review.json',approval)
    trial.save(tmp_path/'result.json',dict(status='HOLD',reason='OPEN_EMPTY_GRIPPER_REQUIRED',completed_steps=[]))
    events=[dict(event='STATE_SNAPSHOT',data=receipt())]
    if executed:events.append(dict(event='STEP_READY',data={}))
    (tmp_path/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n')
    if executed:
        with pytest.raises(ValueError,match='ONLY_PRE_EXECUTION'):
            trial.start_retry_approval(tmp_path)
    else:assert trial.start_retry_approval(tmp_path)==approval


def test_pause_resume_keeps_approved_plan_steps_and_supply_without_new_c_review(tmp_path,monkeypatch):
    commands=[];paused=[False];owner=[None]
    class FakeRobot:
        def __init__(self,*a,**k):self.q=Queue();self.process=self
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def poll(self):return None
        def send(self,command,**data):
            commands.append((command,deepcopy(data)))
            if command=='READ_STATE':self.q.put(dict(event='STATE_SNAPSHOT',data=receipt()))
            elif command in ('EXECUTE','RESUME'):
                doc=data['document'];identity=doc['session']['execution_id']
                if not paused[0]:
                    paused[0]=True
                    self.q.put(dict(event='STOP_VERIFIED',data=dict(actual_stop_verified=True)))
                    self.q.put(dict(event='EXECUTION_HELD',data=dict(execution_id=identity,
                        resume_allowed=True,reason='GRIP_COMPLETION_NOT_VERIFIED')))
                else:self.q.put(dict(event='TRIAL_STEP_EXECUTED',data=dict(execution_id=identity)))
        def receive(self,timeout):return self.q.get(timeout=timeout)
    def notify(event,data):
        if event=='TRIAL_PAUSED':owner[0].resume()
    monkeypatch.setattr(trial,'RobotProcess',FakeRobot)
    t=owner[0]=trial.Trial(ROOT,tmp_path,notify,execute=True)
    t.run(design(),'UNIT_OPERATOR_REVIEW')
    assert t.result['status']=='TRIAL_EXECUTION_FINISHED',t.result
    assert t.result['completed_steps']==['S01','S02']
    docs=[data['document'] for command,data in commands if command in ('EXECUTE','RESUME')]
    assert [d['step']['step_id'] for d in docs]==['S01','S01','S02']
    assert docs[0]['step']==docs[1]['step'] and docs[0]['d_profile']==docs[1]['d_profile']
    assert docs[0]['session']['execution_id']!=docs[1]['session']['execution_id']
    assert docs[1]['session']['resume_current_revision'] is None
    assert docs[1]['session']['trial_alignment_pending']
    assert not t.paused and not t.result['assembly_completion']
