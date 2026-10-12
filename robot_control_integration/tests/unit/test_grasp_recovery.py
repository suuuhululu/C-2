from copy import deepcopy
import json
from pathlib import Path
import time
import pytest
from app.assembly_step_bridge import build_plan, validate_physical
from app.assembly_step_runner import StepReplayDriver
from app.control_driver import execute_step
from app.control_session import ControlSession, validate_execution
from scripts.robot_control_trial import test_session as synthetic_session

ROOT=Path(__file__).resolve().parents[2]
CONNECTION=dict(tcp='GripperDA_v4',tool='ToolWeight0')


def setup():
    value=json.loads((ROOT/'settings/onsite_blue_slot1_6_6_l3_20261011/pickup-openhand-48382c79-5354-48f6-8924-1a6df5c58812.profile.json').read_text())
    p=value['d_profile'];s=next(iter(p['steps'].values()))
    s.update(grasp_recovery_reviewed=True,grasp_recovery_start_pose=s['pickup_pose'].copy(),
             grasp_recovery_start_width_range_mm=[39.3,40.3],pickup_width_mm=39.)
    plan=build_plan(value['step'],p);ticks=[0.];events=[]
    clock=lambda:ticks[0]
    def sleep(seconds):ticks[0]+=seconds
    record=lambda e,d:events.append((e,deepcopy(d)))
    session=ControlSession(synthetic_session(plan),plan,record,clock=clock,wall=time.time)
    raw=StepReplayDriver(s['reference_pose']);raw.value.update(posx=s['pickup_pose'].copy(),gripper_status=0,gripper_width_mm=39.8)
    def close(width,force):
        raw.grips.append((width,force));raw.value.update(gripper_status=2,gripper_width_mm=39.7)
    raw.command_gripper=close
    return p,plan,raw,session,events,clock,sleep


def execute(state,confirm=lambda *_:True,zone='supply'):
    p,plan,raw,session,_,clock,sleep=state
    return execute_step(raw,session,CONNECTION,plan,p,confirm,session.record,
                        phase='grasp-recovery',start_zone=zone,clock=clock,sleep=sleep)


def test_closes_once_without_opening_or_robot_movement():
    state=setup();r=execute(state)
    assert state[2].grips==[(39.,40.)] and not state[2].moves
    assert r['status']=='PAUSED_PICKUP_COMPLETE_HOLDING'
    assert not r['physical_verified'] and not r['current_update'] and not r['assembly_completion']
    assert len([e for e,_ in state[4] if e=='GRIPPER_FEEDBACK'])==3
    assert state[3].lease is None and state[3].request is None


def test_start_decline_does_not_write():
    state=setup();assert execute(state,lambda *_:False)['status']=='PAUSED_START'
    assert not state[2].grips and not state[2].moves


@pytest.mark.parametrize('change',[{'gripper_status':1},{'gripper_status':2},{'gripper_status':4},
    {'gripper_width_mm':38.},{'gripper_width_mm':float('nan')},{'tcp':'wrong'},
    {'query_duration_s':.6},{'motion_status':2},{'wrench':[0,0,36,0,0,0]}])
def test_invalid_start_has_no_gripper_or_movement_write(change):
    state=setup();state[2].value.update(change)
    with pytest.raises((RuntimeError,TimeoutError)):execute(state)
    assert not state[2].grips and not state[2].moves


def test_pose_change_during_hmi_blocks_closing():
    state=setup()
    def confirm(*_):state[2].value['posx'][0]+=.1;return True
    with pytest.raises(RuntimeError,match='START_CHANGED'):execute(state,confirm)
    assert not state[2].grips and not state[2].moves


def test_status_zero_after_write_never_becomes_verified_grasp():
    state=setup();raw=state[2]
    raw.command_gripper=lambda w,f:raw.grips.append((w,f))
    with pytest.raises(TimeoutError,match='COMPLETION_NOT_VERIFIED'):execute(state)
    assert raw.grips==[(39.,40.)] and not raw.moves


def test_fault_after_command_stops_without_transport():
    state=setup();raw=state[2]
    def close(w,f):raw.grips.append((w,f));raw.value['gripper_status']=4
    raw.command_gripper=close
    with pytest.raises(RuntimeError,match='STATUS_FAULT'):execute(state)
    assert not raw.moves and raw.stops


@pytest.mark.parametrize('field,value',[
    ('grasp_recovery_reviewed',False),('pickup_width_mm',37.),('pickup_width_mm',40.),
    ('grasp_recovery_start_width_range_mm',[40,39]),('grasp_recovery_start_width_range_mm',[39,float('inf')])])
def test_unreviewed_or_unbounded_closure_is_rejected(field,value):
    state=setup();state[1]['settings'][field]=value
    with pytest.raises(ValueError):validate_physical(state[1],state[0],'grasp-recovery')


def test_wrong_zone_never_writes():
    state=setup()
    with pytest.raises(ValueError,match='SUPPLY_START_ZONE'):execute(state,zone='assembly')
    assert not state[2].grips and not state[2].moves


def test_real_recovery_session_requires_evidence_and_cannot_transport():
    p,plan,_,s,*_=setup();v=dict(s.value,backend='REAL',provenance='LOCAL_OPERATOR_TRIAL',
        source_epoch='ONSITE_RECOVERY',profile_id=p['profile_id'],allowed_trial_phase='grasp-recovery',
        exclusive_control_reviewed=True,device_feedback_reviewed=True,stillness_parameters_reviewed=True,hand_clear_reviewed=True)
    with pytest.raises(ValueError,match='EXPLICIT_LOCAL_GRASP'):validate_execution(plan,p,v,'grasp-recovery')
    v['recovery_evidence_ref']='read-only-recovery.json';validate_execution(plan,p,v,'grasp-recovery')
    with pytest.raises(ValueError,match='CANNOT_EXECUTE_OTHER_PHASES'):validate_execution(plan,p,v,'handover')
