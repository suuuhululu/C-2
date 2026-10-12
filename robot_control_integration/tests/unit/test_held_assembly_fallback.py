from copy import deepcopy
import pytest
from app.control_driver import execute_step, validate_assembly_fallback
from app.assembly_step_runner import StepReplayDriver
from test_control_session import setup
from test_gesture_handover_trial import trial, place_recovery, CONNECTION


@pytest.mark.parametrize('source', ['camera_unavailable','no_signal','camera_lost','relay_lost'])
def test_no_receive_selects_assembly_without_opening(source):
    def camera(row,n,clock):
        if source=='camera_unavailable':return None
        if source=='relay_lost' and n>=3:raise RuntimeError('THEORA_RELAY_EXITED')
        if source=='camera_lost' and n>=3:clock.sleep(.31);return None
        row['candidate_event']=None
        return row
    execute,raw,events,s,plan,*_=place_recovery(camera_change=camera)
    plan['settings']['handover_trial']['no_receive_action']='ASSEMBLE'
    r=execute()
    assert r['status']=='ASSEMBLY_REQUIRED' and r['fresh_assembly_plan_required']
    assert not raw.grips and not any(e=='WAIT_HANDOVER_RELEASE' for e,d in events)
    assert s.request is None and s.lease is None and not s.cancelled
    if source=='camera_unavailable':assert not raw.moves
    if source in ('camera_lost','relay_lost'):assert raw.stops==1


def test_receive_signal_still_hands_over_instead_of_assembling():
    execute,raw,_,_,plan,*_=place_recovery()
    plan['settings']['handover_trial']['no_receive_action']='ASSEMBLE'
    r=execute()
    assert r['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE' and not r.get('assembly_required')


def test_declined_receiving_confirmation_never_turns_into_assembly():
    execute,raw,_,_,plan,*_=trial(release=False)
    plan['settings']['handover_trial']['no_receive_action']='ASSEMBLE'
    r=execute()
    assert r['status']=='PAUSED_HANDOVER_RECEIVING_CONFIRMATION' and not r.get('assembly_required')
    assert not raw.grips


def test_unverified_camera_loss_stop_cannot_fall_back():
    def camera(row,n,clock):
        if n>=3:clock.sleep(.31);return None
        return row
    execute,raw,_,_,plan,*_=trial(camera_change=camera,broken_stop=True)
    plan['settings']['handover_trial']['no_receive_action']='ASSEMBLE'
    with pytest.raises(RuntimeError,match='STOP_NOT_VERIFIED'):execute()
    assert not raw.grips


def test_held_assembly_approaches_presses_releases_without_picking_again():
    s,plan,p,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=2,gripper_width_mm=40.,posx=[*p['place_pose'][:2],p['clearance_z_mm'],*plan['settings']['reference_pose'][3:]])
    r=execute_step(raw,s,CONNECTION,plan,p,lambda *_:True,s.record,phase='assemble-held',start_zone='place',clock=clock,sleep=clock.sleep)
    assert r['status']=='AWAITING_BACKEND_OBSERVATION'
    assert raw.grips==[(plan['settings']['release_width_mm'],p['gripper_force_n'])]
    assert not any(e in ('WAIT_PICKUP_ALIGNMENT','WAIT_GRASP_CONFIRMED') for e,d in events)
    assert any(e=='PRESS_RESULT' for e,d in events)
    assert not r['current_update'] and not r['assembly_completion']


@pytest.mark.parametrize('negative,status', [('ALIGNMENT_AND_PARALLEL','PAUSED_ALIGNMENT'),('FULL_SEATING','PAUSED_FULL_SEATING'),('RELEASE','PAUSED_RELEASE')])
def test_held_assembly_decline_blocks_release(negative,status):
    s,plan,p,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose']);raw.value.update(gripper_status=2,gripper_width_mm=40.)
    r=execute_step(raw,s,CONNECTION,plan,p,lambda req,*_:req['kind']!=negative,s.record,phase='assemble-held',start_zone='place',clock=clock,sleep=clock.sleep)
    assert r['status']==status and not raw.grips


def fallback_binding():
    s,plan,*_=setup()
    r=dict(status='ASSEMBLY_REQUIRED',execution_id='HANDOVER',assembly_start_zone='place')
    v=dict(s.value,allowed_trial_phase='assemble-held',execution_id='ASSEMBLY',handover_parent_execution_id='HANDOVER')
    return r,plan,v


def test_fresh_bound_fallback_accepts_updated_target_of_same_held_block():
    r,held,v=fallback_binding();next_plan=deepcopy(held);next_plan['block']['layer']=3
    validate_assembly_fallback(r,held,next_plan,v)


@pytest.mark.parametrize('change', [dict(execution_id='HANDOVER'),dict(handover_parent_execution_id='other'),dict(allowed_trial_phase='full'),dict(execution_id=None)])
def test_bad_fallback_session_cannot_dispatch(change):
    r,plan,v=fallback_binding();v.update(change)
    with pytest.raises(ValueError,match='FALLBACK_SESSION'):validate_assembly_fallback(r,plan,plan,v)


@pytest.mark.parametrize('field,value', [('color','yellow'),('brick_type','2x3x1')])
def test_fallback_cannot_change_already_held_brick(field,value):
    r,held,v=fallback_binding();next_plan=deepcopy(held);next_plan['block'][field]=value
    with pytest.raises(ValueError,match='HELD_BLOCK'):validate_assembly_fallback(r,held,next_plan,v)
