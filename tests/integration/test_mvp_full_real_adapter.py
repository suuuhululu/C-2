"""REAL 문서 경계 + 실제 A/C/B 함수. 장치는 별도 MOCK D 프로세스로 교체한다."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from app.mvp_real_trial import FullFeatureRealTrial
from app.robot_process import RobotProcess

from jsonschema import Draft202012Validator, RefResolver
SCHEMAS=Path(__file__).resolve().parents[2]/'interfaces/schemas'
COMMON=json.loads((SCHEMAS/'day4.schema.json').read_text())
HMI=json.loads((SCHEMAS/'hmi.schema.json').read_text())
HMI_VALIDATOR=Draft202012Validator(HMI,resolver=RefResolver.from_schema(HMI,store={COMMON['$id']:COMMON,'https://c-2.invalid/schemas/day4.schema.json':COMMON}))

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),reason='C2_ROBOT_ROOT required')


def validate_real_document(doc):
    code='''
import json,sys
from app.assembly_step_bridge import build_plan
from app.integration_motion_binding import verify_motion
from app.control_session import validate_execution
x=json.load(sys.stdin);p=build_plan(x['step'],x['d_profile'])
validate_execution(p,x['d_profile'],x['session'],'full')
if p['mode']=='ROBOT_GRIP' and p['assistance_kind'] in ('NONE','HOLD'):
 validate_execution(p,x['d_profile'],x['session'],'contact')
verify_motion(x['motion']['motion_proposal'],p,x['d_profile'],x['request']['robot_state'])
'''
    r=subprocess.run([sys.executable,'-c',code],cwd=ROOT,input=json.dumps(doc),text=True,capture_output=True,timeout=10)
    assert r.returncode==0,r.stderr


class MockTransport:
    """Only this test changes admitted REAL sessions to TEST at the transport boundary."""
    def __init__(self,root,**kwargs):
        assert kwargs['mode']=='REAL' and kwargs['gestures']
        self.inner=RobotProcess(root,mode='MOCK')
        self.events=self.inner.events;self.process=self.inner.process
        self.documents=[];self.runtime=None
    def send(self,command,**data):
        if command=='READ_STATE':
            sample=dict(posx=[400.851,8.573,314.981,175.022,-179.595,175.461],
                velx=[0.]*6,tcp='GripperDA_v4',tool='ToolWeight0',robot_state=1,robot_mode=1,
                drl_state=3,motion_status=0,gripper_status=0,gripper_width_mm=55.,query_duration_s=.01)
            if self.runtime and self.runtime.robot_sample:
                sample['posx']=deepcopy(self.runtime.robot_sample['posx'])
            self.events.put(dict(event='STATE_SNAPSHOT',data=dict(captured_unix_s=time.time(),
                physical_commands=0,samples=[deepcopy(sample) for _ in range(3)])))
            return
        if command in ('EXECUTE','RESUME'):
            doc=data['document'];validate_real_document(doc);self.documents.append(deepcopy(doc))
            doc=deepcopy(doc);doc['session'].update(backend='TEST',provenance='SYNTHETIC')
            data['document']=doc
        self.inner.send(command,**data)
    def close(self):self.inner.close()


def install(monkeypatch,tmp_path,design,**kwargs):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    monkeypatch.setattr('app.mvp_integration.RobotProcess',MockTransport)
    r=FullFeatureRealTrial(ROOT,tmp_path,fixture_design=design,c_mode='offline',**kwargs)
    r.robot.runtime=r
    return r


def settle(r,condition,seconds=65,*,receiving=False,on_poll=lambda:None):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        r.poll();HMI_VALIDATOR.validate(r.workflow.snapshot())
        if r.workflow.candidate:r.workflow.preview_ready(r.workflow.candidate['request_id'])
        if r.c_pending:r.answer('좋아 이걸로 하자')
        on_poll()
        request=r.ready_signal
        if request:
            now=time.monotonic_ns()
            r.robot.inner.send('GESTURE_SAMPLE',sample=dict(provenance='SYNTHETIC',
                execution_id=r.last_document['session']['execution_id'],source_epoch=r.last_document['session']['source_epoch'],
                preview_request_id=request['request_id'],received_monotonic_ns=now,source_ns=now+1,frame='TEST_ONLY_CAMERA',
                hands=([dict(pose='OPEN_HAND',center=[100.,100.],palm_size=40.)] if receiving else []) if request['kind']=='RECEIVE' else [dict(pose='THUMBS_UP',center=[100.,100.],palm_size=40.)],
                candidate_event=('OPEN_HAND_HELD_ORIENTATION_UNKNOWN' if receiving else None) if request['kind']=='RECEIVE' else 'THUMBS_UP_HELD',continuity_estimate=True))
        if condition():return
        if r.workflow.status=='HOLD' and r.workflow.check is None:pytest.fail(r.workflow.reason)
        time.sleep(.03)
    pytest.fail(str((r.workflow.status,r.workflow.reason)))


def brick(x=4,layer=1,kind='2x3x1',color='blue',angle=0):
    return dict(brick_type=kind,color=color,x=x,y=4,layer=layer,orientation_deg=angle)


@pytest.mark.parametrize('kind',['2x2x1','2x3x1'])
@pytest.mark.parametrize('color',['yellow','blue'])
@pytest.mark.parametrize('contact_trial',[False,True])
def test_next_supply_slot_prepares_with_stopped_residual_velocity(monkeypatch,tmp_path,kind,color,contact_trial):
    original_send=MockTransport.send
    def send(transport,command,**data):
        if command=='READ_STATE' and transport.documents:
            sample=dict(posx=deepcopy(transport.runtime.robot_sample['posx']),
                velx=[-.0099941483,-.0169404615,0.,-.0000500448,-.0001962454,-.0026575383],
                tcp='GripperDA_v4',tool='ToolWeight0',robot_state=1,robot_mode=1,
                drl_state=3,motion_status=0,gripper_status=0,gripper_width_mm=49.7,query_duration_s=.114)
            transport.events.put(dict(event='STATE_SNAPSHOT',data=dict(captured_unix_s=time.time(),
                physical_commands=0,samples=[deepcopy(sample) for _ in range(3)])))
            return
        original_send(transport,command,**data)
    monkeypatch.setattr(MockTransport,'send',send)
    design=dict(design_version=1,blocks=[brick(4,layer,kind=kind,color=color) for layer in (1,2)])
    r=install(monkeypatch,tmp_path,design,contact_alignment_trial=contact_trial)
    try:
        r.review_preparation(True);assert r.command('START')
        settle(r,lambda:r.workflow.status=='COMPLETE')
        docs=r.robot.documents
        assert [d['step']['reservation']['slot_id'] for d in docs]==[f'{color}_{kind}_01',f'{color}_{kind}_02']
        pickups=[next(iter(d['d_profile']['steps'].values()))['pickup_pose'] for d in docs]
        assert pickups[0]!=pickups[1]
        assert r.slot_indices[(kind,color)]==3
        assert all(d['session']['stillness']['linear_mm_s']==5. for d in docs)
    finally:r.close()


def test_measured_real_adapter_keeps_all_methods_and_actual_a_apis(monkeypatch,tmp_path):
    blocks=[brick(x) for x in (4,6,8)]+[brick(x,2) for x in (5,7,9)]+[brick(10,3)]
    r=install(monkeypatch,tmp_path,dict(design_version=1,blocks=blocks))
    r.workflow.settings['assembly_context']['grip_axes']=['x']
    try:
        assert not r.command('START') and not r.robot.documents
        r.review_preparation(True);assert r.command('START')
        settle(r,lambda:r.workflow.status=='COMPLETE')
        docs=r.robot.documents
        assert len(docs)==7
        assert {d['step']['action']['mode'] for d in docs}=={'ROBOT_GRIP','HUMAN_ASSEMBLY'}
        assert {'NONE','PRESS','PRESS_AND_HOLD','MANUAL_ASSEMBLY'} <= {d['step']['action']['assistance_kind'] for d in docs}
        assert all(d['session']['backend']=='REAL' and d['session']['b_observation_kind']=='SYNTHETIC' for d in docs)
        assert all(not d['motion']['execution_allowed'] for d in docs)
        assert all(d['state_basis']=='SYNTHETIC_B_NOT_CAMERA_CONFIRMED' for d in docs)
        assert all('SYNTHETIC_B_CURRENT:' in d['session']['d_runtime']['current_ref'] for d in docs)
        assert r.workflow.current['current_revision']==7 and not r.auto_gestures
        rows=[json.loads(v) for v in (tmp_path/(r.workflow.job_id+'.jsonl')).read_text().splitlines()]
        ports=[v['result']['port'] for v in rows if v['event']=='MODULE_RESULT']
        assert {'a.whole','a.assess','a.motion','c.review'} <= set(ports)
        assert any(v['event']=='ROBOT_HELP_RELEASE_GUIDANCE' and not v['result']['b_confirmed'] for v in rows)
        with pytest.raises(ValueError,match='SYNTHETIC_GESTURE_CANNOT'):
            r.gesture('THUMBS_UP')
    finally:r.close()


@pytest.mark.parametrize('kind,color,angle',[('2x2x1','yellow',0),('2x3x1','yellow',90),('2x3x1','blue',90),('1x2x1','red',90)])
def test_real_admission_uses_taught_supply_without_manual_robot_alignment(monkeypatch,tmp_path,kind,color,angle):
    r=install(monkeypatch,tmp_path,dict(design_version=1,blocks=[brick(kind=kind,color=color,angle=angle)]))
    try:
        r.review_preparation(True);r.command('START');settle(r,lambda:r.workflow.status=='COMPLETE')
        d=r.robot.documents[0]
        assert d['d_profile']['supply_pose_basis']=='MEASURED'
        s=next(iter(d['d_profile']['steps'].values()))
        if kind=='2x3x1' and angle==90:
            from app.assembly_board_calibration import board_target_pose
            taught=board_target_pose(r.inputs['board_calibration'],d['step']['block'],r.inputs['layers'])
            expected=taught[:];expected[0]+=1.5
            assert s['reference_pose']==pytest.approx(expected)
            assert d['request']['frame_profile']['calculation_profiles']['assembly']['d_onsite_step']['reference_pose']==s['reference_pose']
        assert s['pickup_open_width_mm']==55 and s['pickup_width_mm']==35 and s['release_width_mm']==48
        assert not d['session']['trial_alignment_pending'] and d['session']['alignment_evidence_ref'] is None
        assert d['d_profile']['descent_velocity']==24. and d['d_profile']['transfer_velocity']==276.48
        if s['turn_base_z_deg']:
            bad=deepcopy(d);bad['session'].pop('b_observation_kind')
            code='''
import json,sys
from app.assembly_step_bridge import build_plan
from app.control_session import validate_execution
x=json.load(sys.stdin)
validate_execution(build_plan(x['step'],x['d_profile']),x['d_profile'],x['session'],'full')
'''
            result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,input=json.dumps(bad),capture_output=True,text=True)
            assert result.returncode!=0 and 'ROTATED_GRASP_XY_COMPENSATION_NOT_MEASURED' in result.stderr
    finally:r.close()


def test_stop_before_first_execution_uses_fresh_real_state_not_stop_idle(monkeypatch,tmp_path):
    r=install(monkeypatch,tmp_path,None)
    try:
        r.review_preparation(True);r.command('START')
        end=time.monotonic()+3
        while not r.c_pending and time.monotonic()<end:r.poll();time.sleep(.01)
        old=r.workflow.active['request']['request_id']
        r.robot.events.put(dict(event='GESTURE_STOP_REQUESTED',data=dict(execution_id=None)))
        r.poll()
        assert r.workflow.status=='STOPPED' and r.workflow.reason=='STOP_CONFIRMED'
        assert r.cancelled.is_set() and r.c_pending is None
        assert not r.robot.documents and r.workflow.current['current_revision']==0
        assert r.command('RESUME')
        end=time.monotonic()+3
        while not r.c_pending and time.monotonic()<end:r.poll();time.sleep(.01)
        assert r.workflow.active['request']['request_id']!=old
        assert not r.workflow.receive('c.initial',old,dict(status='OK',design=dict(design_version=1,blocks=[brick()]),hri_result=None))
    finally:r.close()


def test_human_ack_timeout_cannot_be_completed_by_fake_b(monkeypatch,tmp_path):
    r=install(monkeypatch,tmp_path,None)
    try:
        r.robot.events.put(dict(event='ASSEMBLY_CUE_FINISHED',data=dict(received=False,assembly_completion=False)))
        r.poll()
        context=dict(check_kind='STEP',check_id='test-human-timeout',observation_seq=1)
        observation,diagnostic=r.observe(context,lambda:True)
        assert observation['verified_regions']==[] and observation['visible_blocks']==[]
        assert observation['reason']=='SYNTHETIC_B_OCCLUSION'
        assert diagnostic['observation_kind']=='SYNTHETIC_NOT_CAMERA'
        # Explicit reinspection can supply a new synthetic observation without replaying motion.
        observation,_=r.observe(dict(context,check_id='test-human-reinspection',observation_seq=2),lambda:True)
        assert len(observation['verified_regions'])==5 and not r.robot.documents
    finally:r.close()


@pytest.mark.parametrize('port,with_difference,function_name',[
    ('c.initial',False,'create_initial_design'),('c.review',False,'review_design_candidate'),
    ('c.intent',True,'run_intervention'),('c.plan_failure',False,'run_design_change')])
def test_voice_calls_complete_c_boundary_without_text_or_rule_substitution(monkeypatch,tmp_path,port,with_difference,function_name):
    r=install(monkeypatch,tmp_path,None)
    design=dict(design_version=1,blocks=[brick()]);seen=[]
    def voice_function(*args,**kwargs):
        seen.append((args,kwargs))
        if kwargs.get('on_progress'):kwargs['on_progress'](dict(stage='LISTENING',message='테스트 음성 입력'))
        return dict(status='CANCELLED',hri_result=None,design=None,error=dict(code='STOPPED',message='TEST_ONLY'))
    monkeypatch.setattr('app.c_design.main.'+function_name,voice_function)
    try:
        r.c_mode='live';monkeypatch.setenv('C_DESIGN_USE_LLM','1')
        r.workflow.job_id='voice-fixture'
        payload=dict(design=design,candidate=design,kind='initial',previous_design=None,
            current=dict(current_revision=0,blocks=[]),reason='TEST_INTENT',expected=None,observation=None,
            difference=dict(missing=[brick()],unexpected=[],unobservable=[]) if with_difference else None)
        r.workflow.call(port,payload)
        assert r.answer_voice()
        end=time.monotonic()+3
        while r.workflow.active and time.monotonic()<end:r.poll();time.sleep(.01)
        assert len(seen)==1 and 'text_answers' not in seen[0][1] and 'text' not in seen[0][1]
        assert callable(seen[0][1]['should_stop']) and not r.robot.documents
        if with_difference:assert seen[0][1]['inspection_context']['difference']['missing']==[brick()]
    finally:r.close()


def test_trial_option_uses_same_a_d_route_and_reaction_stop_profile(monkeypatch,tmp_path):
    r=install(monkeypatch,tmp_path,dict(design_version=1,blocks=[brick()]),contact_alignment_trial=True)
    try:
        r.review_preparation(True);r.command('START');settle(r,lambda:r.workflow.status=='COMPLETE')
        doc=r.robot.documents[0]
        assert doc['d_profile']['native_press']['alignment_trial']
        assert doc['d_profile']['continuous_transport']
        assert doc['d_profile']['reaction_descent_velocity']==6.
        assert doc['d_profile']['reaction_descent_acceleration']==6.
        assert doc['session']['stillness']['linear_mm_s']==5.
        assert doc['session']['stillness']['angular_deg_s']==5.
        assert doc['session']['stillness']['position_mm']==1.
        assert doc['d_profile']['transport_blending']['relaxed_constraints']
        assert 'PLACE_BOARD_EMPTY' not in [w['label'] for w in doc['motion']['motion_proposal']['segments'][0]['waypoints']]
        assert 'pre_contact_slow_distance_mm' not in doc['d_profile']
        assert doc['d_profile']['palm_handover_before_contact']
        rows=[json.loads(v) for v in (tmp_path/(r.workflow.job_id+'.jsonl')).read_text().splitlines()]
        assert any(v['event']=='ROBOT_PRESS_SEATING_CHECK' and v['result']['seating_goal_verified'] for v in rows)
        pressure=next(v['result'] for v in rows if v['event']=='ROBOT_PRESS_RESULT')
        assert pressure['press_control']=='POSITION_DESCENT_REACTION_STOP'
        assert pressure['native_force_commands']==0 and pressure['force_control_target_n'] is None
        assert pressure['threshold_force_norm_n']>=35. and pressure['stop']['stillness_verified']
        moves=[v['result'] for v in rows if v['event']=='ROBOT_MOVE_STARTED']
        assert not any(v.get('label') in ('LIFT','TARGET_HIGH','ASSEMBLY_APPROACH') for v in moves)
        assert sum(v.get('label')=='PRE_CONTACT' for v in moves)==1
        descents=[v['result'] for v in rows if v['event']=='ROBOT_MOVE_REQUEST' and v['result'].get('segment')=='DESCENT']
        assert len(descents)==3 and descents[-1]['velocity']==[6.,6.]
        assert descents[-1]['acceleration']==[6.,6.]
        batches=[v['result'] for v in rows if v['event']=='ROBOT_SINGLE_WRITER_BLEND']
        assert len(batches)==3 and len(batches[1]['targets'])==5
        assert batches[-1]['targets'][-1][:2]==next(iter(doc['d_profile']['steps'].values()))['pickup_pose'][:2]
    finally:r.close()


def test_real_admission_mock_process_palm_override_keeps_plan_current_and_one_slot(monkeypatch,tmp_path):
    r=install(monkeypatch,tmp_path,dict(design_version=1,blocks=[brick(kind='2x2x1')]))
    sent=[False]
    def inject_palm():
        if not r.last_document or not r.robot_sample:return
        execution=r.workflow.execution or {}
        if execution.get('phase') in ('CONTACT','RELEASE','RETREAT','WAIT_INSPECTION'):return
        now=time.monotonic_ns();s=r.last_document['session']
        r.robot.inner.send('GESTURE_SAMPLE',sample=dict(provenance='SYNTHETIC',execution_id=s['execution_id'],
            source_epoch=s['source_epoch'],preview_request_id=None,received_monotonic_ns=now,source_ns=now+1,
            frame='TEST_ONLY_CAMERA',hands=[dict(pose='OPEN_HAND',center=[100.,100.],palm_size=40.)],
            candidate_event=None,continuity_estimate=True))
        sent[0]=True
    try:
        r.review_preparation(True);r.command('START')
        settle(r,lambda:r.workflow.status=='COMPLETE',receiving=True,on_poll=inject_palm)
        rows=[json.loads(v) for v in (tmp_path/(r.workflow.job_id+'.jsonl')).read_text().splitlines()]
        assert sent[0] and any(v['event']=='ROBOT_HANDOVER_OVERRIDE' for v in rows)
        assert not any(v['event']=='ROBOT_CONTACT_SUCCEEDED' for v in rows)
        assert r.slot_indices[('2x2x1','blue')]==2 and r.workflow.current['current_revision']==1
        assert len(r.robot.documents)==1 and r.robot.documents[0]['step']['action']['mode']=='ROBOT_GRIP'
        assert r.workflow.approved['blocks']==[brick(kind='2x2x1')]
    finally:r.close()
