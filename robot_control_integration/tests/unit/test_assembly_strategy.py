"""A strategy dispatch on deterministic device-free D components."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import pytest

from app.assembly_strategy import is_release_press,validate_d_profile_motion
from app.assembly_step_bridge import build_plan,step_from_messages
from app.assembly_step_runner import StepReplayDriver, run_step
from app.round2_step_controller import prepare_round2_step
from tests.unit.test_control_session import Clock
from tests.unit.test_human_step_raised_press import fixture
from scripts.robot_control_trial import test_session as make_session


@pytest.mark.parametrize('plan,expected',[
    (dict(mode='ROBOT_RELEASE_PRESS'),True),
    (dict(mode='ROBOT_GRIP',assembly_strategy='RELEASE_PRESS'),True),
    (dict(mode='ROBOT_GRIP',assembly_strategy='GRIP_INSERT'),False),
    (dict(mode='ROBOT_GRIP',gripper=dict(release_strategy='RELEASE_PRESS')),False),
    (dict(mode='HUMAN_ASSEMBLY',assembly_strategy='RELEASE_PRESS'),False),
])
def test_release_press_is_explicit_and_keeps_legacy_mode(plan,expected):
    before=deepcopy(plan)
    assert is_release_press(plan) is expected
    assert plan==before


def source_case(assistance):
    plan,profile,measured,_=fixture('yellow','2x2x1',0)
    actions=[dict(action=action,target_block=deepcopy(plan['block']),
                  effect='Source A target '+action) for action in ('HOLD','PRESS')
             if action in assistance]
    source=dict(plan_id=plan['plan_id'],step_id=plan['step_id'],block=deepcopy(plan['block']),
                mode='ROBOT_GRIP',assembly_strategy='RELEASE_PRESS',assistance_kind=assistance,
                human_actions=actions,grip_axis='x',
                gripper=dict(pickup_policy='D_EXISTING_PICKUP',release_strategy='RELEASE_PRESS',
                             release_owner='D',numeric_open_command=None))
    step=dict(case_id='square',step_id=plan['step_id'],plan_id=plan['plan_id'],
              block=deepcopy(plan['block']),current_revision=0,
              reservation=dict(slot_id='yellow_2x2x1_04'),action=source)
    settings=profile['steps'][plan['key']]
    release=deepcopy(settings['reference_pose']);release[2]+=4.5  # Explicit TEST air-release geometry.
    settings.update(release_pose=release,press_width_mm=4.,
                    press_start_pose=[400.,80.,61.,0.,180.,0.],
                    press_approach_pose=[400.,80.,80.,0.,180.,0.])
    profile.update(supply_transit_xy_mm=[-300.,0.],body_bypass_xy_mm=[0.,-200.],
                   place_pose=[400.,-150.,150.,0.,180.,0.])
    return step,profile


def strategy_messages():
    step,profile=source_case('NONE');profile['profile_id']='SYNTHETIC_D_STRATEGY_PROFILE'
    action=deepcopy(step['action'])
    context=dict(plan_id=step['plan_id'],step_id=step['step_id'],request_id='TEST_REQUEST')
    assessment=dict(status='CANDIDATE',errors=[],action_proposal=action,
                    context=deepcopy(context),assessment_id='TEST_ASSESSMENT',
                    assessment_input_digest='TEST_A_INPUT_DIGEST')
    request=dict(assessment_context=deepcopy(context),context=deepcopy(context),
                 assessment_id=assessment['assessment_id'],assessment_input_digest=assessment['assessment_input_digest'],
                 reserved_supply_slot=deepcopy(step['reservation']),latest_current=dict(current_revision=0),
                 assessment_current_revision=0,assessed_action=deepcopy(action),action_proposal=deepcopy(action),
                 robot_state=dict(tcp_pose=dict(frame_id='base_link',xyz_m=[.4,-.2,.15],quaternion_xyzw=[0.,1.,0.,0.])))
    digest=hashlib.sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    motion=dict(message_type='DReleasePressMotionResult',schema_version='d-release-press-motion/1',
                producer='D_RELEASE_PRESS_PROFILE',status='CANDIDATE',execution_allowed=False,
                context=deepcopy(context),assessment_id=assessment['assessment_id'],errors=[],
                motion_proposal=dict(motion_plan_id='TEST_D_PROFILE_MOTION',motion_scope='D_PICK_TRANSPORT_RELEASE_PRESS',
                                     profile_id=profile['profile_id'],profile_digest=digest,d_profile_key='square/S4'))
    return assessment,request,motion,profile


def test_d_profile_motion_is_separate_from_unsupported_a_motion():
    assessment,request,motion,profile=strategy_messages()
    step=step_from_messages(assessment,request,motion,case_id='square')
    assert step['motion_source']=='D_PROFILE' and not step['source_execution_allowed']
    assert validate_d_profile_motion(motion,request,profile,'square/S4')==motion
    blocked=dict(deepcopy(motion),producer=None,message_type='StepMotionResult',status='BLOCKED',
                 motion_proposal=None,errors=[dict(code='UNSUPPORTED_METHOD')])
    with pytest.raises(ValueError,match='MOTION_NOT_CANDIDATE'):
        step_from_messages(assessment,request,blocked,case_id='square')
    changed=deepcopy(profile);changed['steps']['square/S4']['pickup_pose'][0]+=1.
    with pytest.raises(ValueError,match='D_PROFILE_MOTION_BINDING_MISMATCH'):
        validate_d_profile_motion(motion,request,changed,'square/S4')


def test_cli_consumes_d_profile_without_a_segments_and_waits_for_b():
    assessment,request,motion,profile=strategy_messages()
    plan=build_plan(step_from_messages(assessment,request,motion,case_id='square'),profile)
    profile.update(round2=True,max_press_travel_mm=12.)
    digest=hashlib.sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    motion['motion_proposal']['profile_digest']=digest
    document=dict(case_id='square',assessment=assessment,request=request,motion=motion,
                  d_profile=profile,session=make_session(plan),start_zone='supply',
                  motion_source='D_PROFILE',fixture_kind='SYNTHETIC_NO_DEVICE')
    native=Path(__file__).resolve().parents[2]
    env=dict(os.environ,PYTHONPATH=str(native),PYTHONDONTWRITEBYTECODE='1')
    child=subprocess.Popen([sys.executable,'-u',str(native/'scripts/robot_integration_runtime.py'),'--mode','MOCK'],
                           cwd=native,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    events=[]
    try:
        child.stdin.write(json.dumps(dict(command='EXECUTE',document=document))+'\n');child.stdin.flush()
        deadline=time.monotonic()+20.;buffer='';done=False
        while time.monotonic()<deadline:
            if select.select([child.stdout],[],[],.1)[0]:
                chunk=os.read(child.stdout.fileno(),65536)
                if not chunk:break
                buffer+=chunk.decode();lines=buffer.split('\n');buffer=lines.pop()
                for line in lines:
                    value=json.loads(line);events.append(value)
                    if value['event'] in ('INSPECTION_REQUIRED','COMMAND_REJECTED','EXECUTION_HELD'):done=True
                if done:break
        assert any(v['event']=='INSPECTION_REQUIRED' for v in events),events[-5:]
        assert not any(v['event']=='COMMAND_REJECTED' for v in events)
        pressure=next(v['data'] for v in events if v['event']=='PRESS_SESSION')
        assert pressure['force_stop_n']==45. and pressure['max_travel_mm']==12.
        inspection=next(v['data'] for v in events if v['event']=='INSPECTION_REQUIRED')
        assert inspection['robot_press_executed'] and not inspection['assembly_completion'] and not inspection['current_update']
        child.stdin.close();child.wait(timeout=10.)
        assert child.returncode==0,child.stderr.read()
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5.)


@pytest.mark.parametrize('assistance',['NONE','HOLD','PRESS','PRESS_AND_HOLD'])
def test_build_plan_preserves_a_fields_without_a_motion(assistance):
    step,profile=source_case(assistance);before=deepcopy((step,profile))
    plan=build_plan(step,profile)
    assert (step,profile)==before
    assert plan['source_action']==step['action']
    assert plan['mode']=='ROBOT_GRIP' and plan['assistance_kind']==assistance
    assert plan['assembly_strategy']=='RELEASE_PRESS' and plan['d_execution_strategy']=='RELEASE_PRESS'
    assert plan['gripper']==step['action']['gripper']
    assert plan['human_actions']==step['action']['human_actions']
    assert not plan['source_execution_allowed'] and not plan['assembly_completion']
    plan['gripper']['release_strategy']='CHANGED_D_COPY'
    plan['block']['x']+=1
    if plan['human_actions']:plan['human_actions'][0]['target_block']['x']+=1
    assert (step,profile)==before


class StrategyReplay(StepReplayDriver):
    """Switch the imposed contact surface when empty pads close; no physics claim."""
    def __init__(self):
        super().__init__([400.,80.,-100.,0.,180.,0.],reaction_force_n=45.)

    def command_gripper(self,width,force):
        super().command_gripper(width,force)
        if width==4.:
            self.reference[:2]=self.value['posx'][:2]
            self.reference[2]=60.
            self.value.update(gripper_status=2,gripper_width_mm=9.2)


@pytest.mark.parametrize('assistance',['NONE','HOLD','PRESS','PRESS_AND_HOLD'])
def test_new_strategy_full_cycle_preserves_human_press_ownership(assistance):
    step,profile=source_case(assistance)
    plan=build_plan(step,profile)
    prepared=prepare_round2_step(plan,profile)
    driver=StrategyReplay();clock=Clock();events=[];requests=[]
    def confirm(kind,active_plan,sample):
        assert active_plan['mode']=='ROBOT_GRIP'
        assert active_plan['human_actions']==step['action']['human_actions']
        requests.append(kind);return True
    result=run_step(driver,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
                    prepared['execution_candidate'],prepared['profile'],confirm,
                    lambda e,v:events.append((e,deepcopy(v))),
                    phase='full',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION' and result['mode']=='ROBOT_GRIP'
    assert not result['assembly_completion'] and not result['current_update']
    labels=[v['label'] for e,v in events if e=='STEP_MOVE']
    assert 'RELEASE_POSITION' in labels and 'PLACE_BOARD' not in labels
    assert 'ROUND2_ASSEMBLY_OBSERVATION' in labels
    human_press=assistance in ('PRESS','PRESS_AND_HOLD')
    assert result['robot_press_executed'] is (not human_press)
    assert sum(e=='PRESS_SESSION' for e,_ in events)==(0 if human_press else 1)
    if human_press:
        assert result['contact_status']=='HUMAN_REPORTED'
        assert result['human_completion_signal_received']
        assert 'HUMAN_PRESS_AND_HOLD_ACK' in requests
        assert 'PRESS_TOOL_LOWER' not in labels and all(width!=4. for width,_ in driver.grips)
        waits=[v for e,v in events if e=='WAIT_SUPPORT_AND_RELEASE_FOR_HUMAN_PRESS']
        assert waits[0]['human_actions']==step['action']['human_actions']
    else:
        assert labels.index('RELEASE_POSITION')<labels.index('RAISED_EMPTY_VERTICAL_RETREAT')<labels.index('PRESS_TOOL_LOWER')
        assert result['final_gripper_context']==dict(state='EMPTY_PAD_CLOSED',gripper_status=2)
    if assistance=='PRESS':
        assert 'HUMAN_READY' not in requests and 'HUMAN_HOLD_READY' not in requests
    if assistance=='HOLD':assert 'HUMAN_READY' in requests
    if assistance=='PRESS_AND_HOLD':assert 'HUMAN_HOLD_READY' in requests


@pytest.mark.parametrize('assistance,kind',[('HOLD','HUMAN_READY'),('PRESS','SUPPORT_AND_RELEASE_FOR_HUMAN_PRESS'),
                                         ('PRESS_AND_HOLD','HUMAN_HOLD_READY')])
def test_new_strategy_cancelled_readiness_keeps_grasp_and_does_not_press(assistance,kind):
    step,profile=source_case(assistance)
    prepared=prepare_round2_step(build_plan(step,profile),profile)
    driver=StrategyReplay();clock=Clock();events=[]
    result=run_step(driver,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
                    prepared['execution_candidate'],prepared['profile'],lambda stage,*_:stage!=kind,
                    lambda e,v:events.append((e,v)),phase='full',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert result['status'].startswith('PAUSED_')
    assert driver.value['gripper_status']==2 and not result['robot_press_executed']
    assert not any(e=='PRESS_SESSION' for e,_ in events)
    assert not result['assembly_completion'] and not result['current_update']


def test_legacy_release_press_keeps_full_cycle_status():
    step,profile=source_case('NONE')
    step['action']['mode']='ROBOT_RELEASE_PRESS';step['action'].pop('assembly_strategy')
    plan=build_plan(step,profile);plan['round2_vertical_top_press']=True
    profile['round2']=True
    driver=StrategyReplay();clock=Clock()
    result=run_step(driver,dict(tcp='GripperDA_v4',tool='ToolWeight0'),plan,profile,
                    lambda *_:True,lambda *_:None,phase='full',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION' and result['mode']=='ROBOT_RELEASE_PRESS'
    assert result['final_gripper_context']==dict(state='EMPTY_PAD_CLOSED',gripper_status=2)
    assert not result['assembly_completion'] and not result['current_update']


def test_source_strategy_does_not_use_legacy_native_force_profile():
    step,profile=source_case('NONE')
    profile.update(round2=True,native_press=dict(enabled=True,force_n=35.,review_ref='OLD_HELD_FORCE_CONFIGURATION'))
    plan=build_plan(step,profile);driver=StrategyReplay();clock=Clock();events=[]
    result=run_step(driver,dict(tcp='GripperDA_v4',tool='ToolWeight0'),plan,profile,
                    lambda *_:True,lambda e,v:events.append((e,v)),phase='full',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION' and result['robot_press_executed']
    assert not getattr(driver,'native_force_requests',[])
    assert sum(e=='PRESS_SESSION' for e,_ in events)==1
