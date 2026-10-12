from copy import deepcopy
from types import SimpleNamespace
import sys
import pytest
from app.assembly_blend_trial import run_blend,validate_route
from app.assembly_step_runner import StepReplayDriver
from app.control_driver import ControlledDriver
from app.control_session import validate_execution
from app.gesture_handover_trial import validate_handover
from test_control_session import setup
from test_gesture_handover_trial import trial,CONNECTION
from test_assembly_motion_ros import driver as ros_driver


def auto_trial(change=None,blend=False,broken_stop=False):
    def camera(row,n,clock):
        clock.sleep(.01)
        row.update(received_monotonic_ns=round(clock()*1e9),held_ns=1_200_000_000,
                   continuity_estimate=True,hands=[dict(pose='OPEN_HAND')])
        return change(row,n,clock) if change else row
    state=trial(camera_change=camera,broken_stop=broken_stop)
    execute,raw,events,s,plan,p,*_=state
    plan['settings']['handover_trial']['release_policy']='AUTO_AFTER_STOP'
    s.value.update(automatic_handover_release_reviewed=True,automatic_handover_review_ref='human-review')
    if blend:p['transport_blending']=dict(reviewed=True,radius_mm=5.)
    return state


def test_auto_stop_then_fresh_receiving_cue_then_open_without_release_hmi():
    execute,raw,events,s,plan,*_=auto_trial()
    r=execute();assert r['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'
    assert r['motion_stop_verified'] and r['automatic_receiving_signal_confirmed']
    assert not r['release_requires_post_stop_hmi'] and not r['operator_receiving_confirmed']
    assert not any(e=='WAIT_HANDOVER_RELEASE' for e,d in events)
    names=[e for e,d in events]
    assert names.index('STOP_WINDOW_RESULT')<names.index('AUTOMATIC_HANDOVER_RELEASE_AUTHORIZED')<names.index('SINGLE_WRITER_GRIPPER')
    assert raw.grips==[(62.4,40.)] and raw.stops==1
    assert len({d['request_id'] for e,d in events if e=='HUMAN_REQUEST_OPENED' and d['kind']=='RECEIVE'})==3
    assert s.request is None and s.lease is None


def test_auto_handover_uses_one_loaded_batch_and_separate_incoming_segment():
    execute,raw,events,*_=auto_trial(blend=True)
    assert execute()['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'
    assert len(raw.blends)==1 and len(raw.blends[0]['targets'])==3
    assert len([e for e,d in events if e=='SINGLE_WRITER_BLEND'])==1
    assert any(e=='STEP_MOVE' and d['label']=='HANDOVER_INCOMING' for e,d in events)


def test_faster_transit_preserves_separate_receiving_speed():
    execute,raw,events,s,plan,p,*_=auto_trial(blend=True)
    p.update(transfer_velocity=96.,transfer_acceleration=48.)
    plan['settings']['handover_trial'].update(incoming_velocity=32.,incoming_acceleration=16.)
    assert execute()['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'
    assert raw.blends[0]['velocity']==[96.,96.]
    assert raw.blends[0]['acceleration']==[48.,48.]
    label=None
    incoming=[]
    for event,data in events:
        if event=='STEP_MOVE':label=data['label']
        if event=='MOVE_REQUEST' and label=='HANDOVER_INCOMING':incoming.append(data)
    assert incoming and all(d['velocity']==[32.,32.] and d['acceleration']==[16.,16.] for d in incoming)


@pytest.mark.parametrize('value',[0.,-1.,float('nan'),True])
def test_invalid_incoming_speed_rejected_before_motion(value):
    execute,raw,events,s,plan,p,*_=auto_trial()
    plan['settings']['handover_trial']['incoming_velocity']=value
    with pytest.raises(ValueError,match='INVALID_HANDOVER_PARAMETER'):execute()
    assert not raw.moves and not raw.grips


def test_short_hold_shared_by_auto_release_consumer():
    execute,raw,events,s,plan,*_=auto_trial(lambda row,n,c:dict(row,held_ns=400_000_000))
    plan['settings']['handover_trial']['open_hold_seconds']=.4
    assert execute()['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'
    assert raw.grips==[(62.4,40.)]


def test_below_short_hold_never_opens_even_with_candidate_label():
    execute,raw,events,s,plan,*_=auto_trial(lambda row,n,c:dict(row,held_ns=399_999_999))
    plan['settings']['handover_trial']['open_hold_seconds']=.4
    with pytest.raises(RuntimeError,match='SIGNAL_WITHDRAWN'):execute()
    assert not raw.grips


@pytest.mark.parametrize('hold',[.39,5.01,float('nan'),True])
def test_invalid_local_hold_rejected_before_motion(hold):
    execute,raw,events,s,plan,*_=auto_trial()
    plan['settings']['handover_trial']['open_hold_seconds']=hold
    with pytest.raises(ValueError,match='INVALID_HANDOVER_OPEN_HOLD'):execute()
    assert not raw.moves and not raw.grips


def test_fifteen_mm_blend_still_requires_long_enough_segments():
    start=[0.,0.,100.,0.,0.,0.]
    points=[[40.,0.,100.,0.,0.,0.],[40.,40.,100.,0.,0.,0.]]
    assert validate_route(start,points,15.)==points
    with pytest.raises(ValueError,match='SEGMENT_TOO_SHORT'):
        validate_route(start,[[30.,0.,100.,0.,0.,0.],points[1]],15.)


def test_thirty_mm_blend_requires_more_than_sixty_mm_segments():
    start=[0.,0.,100.,0.,0.,0.]
    points=[[61.,0.,100.,0.,0.,0.],[61.,61.,100.,0.,0.,0.]]
    assert validate_route(start,points,30.)==points
    with pytest.raises(ValueError,match='SEGMENT_TOO_SHORT'):
        validate_route(start,[[60.,0.,100.,0.,0.,0.],points[1]],30.)


def test_old_stop_cue_without_post_stop_camera_does_not_open():
    requests=[]
    def change(row,n,clock):
        if row['preview_request_id'] not in requests:requests.append(row['preview_request_id'])
        return None if len(requests)==3 else row
    execute,raw,events,*_=auto_trial(change)
    assert execute()['status']=='PAUSED_HANDOVER_NO_FRESH_RECEIVING_SIGNAL'
    assert not raw.grips and not any(e=='SINGLE_WRITER_GRIPPER' for e,d in events)


def test_withdrawal_during_gripper_lease_stillness_does_not_open():
    holder=[]
    def change(row,n,clock):
        if holder[0].owner=='GRIPPER':row.update(hands=[dict(pose='FIST')],held_ns=0)
        return row
    state=auto_trial(change);holder.append(state[3])
    with pytest.raises(RuntimeError,match='SIGNAL_WITHDRAWN'):state[0]()
    assert not state[1].grips and state[1].stops>=1


def test_auto_unverified_stop_never_opens():
    execute,raw,*_=auto_trial(broken_stop=True)
    with pytest.raises(RuntimeError,match='STOP_NOT_VERIFIED'):execute()
    assert not raw.grips


@pytest.mark.parametrize('change',[dict(automatic_handover_release_reviewed=False),dict(automatic_handover_review_ref=None)])
def test_auto_policy_requires_explicit_session_review(change):
    _,_,_,s,plan,p,*_=auto_trial();s.value.update(change)
    with pytest.raises(ValueError,match='AUTOMATIC_HANDOVER_REVIEW'):validate_handover(plan,p,s.value)


def blend_state():
    s,plan,p,events,clock=setup();p.update(transport_blending=dict(reviewed=True,radius_mm=5.),transfer_velocity=32.,transfer_acceleration=16.)
    raw=StepReplayDriver([0.,0.,20.,0.,0.,0.]);raw.value.update(posx=[0.,0.,100.,0.,0.,0.],gripper_status=2,gripper_width_mm=39.5)
    d=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep);d.own('MOTION')
    points=[[20.,0.,100.,0.,0.,0.],[20.,20.,100.,0.,0.,0.],[40.,20.,100.,0.,0.,0.]]
    return d,p,raw,events,clock,points


def test_batch_has_one_ack_and_endpoint_feedback_before_next_operation():
    d,p,raw,events,c,points=blend_state()
    sample=run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert sample['posx']==points[-1] and len(raw.blends)==1 and not raw.grips
    assert any(e=='BLEND_COMPLETE' for e,d in events)
    assert raw.blends[0]['velocity']==[32.,32.] and raw.blends[0]['radius']==5.


def test_blend_accepts_tiny_feedback_velocity_after_reviewed_stillness_window():
    d,p,raw,events,c,points=blend_state()
    raw.value['velx']=[.002,0.,-.001,0.,.0003,0.]
    run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert len(raw.blends)==1 and any(e=='BLEND_START_RECHECK' for e,v in events)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,v in events)>=3


@pytest.mark.parametrize('failure',['speed','height','force'])
def test_blend_rechecks_after_ik_without_dispatching_changed_start(failure):
    d,p,raw,events,c,points=blend_state();check=raw.check_pose
    def changed(target):
        if failure=='speed':raw.value['velx'][0]=.1
        if failure=='height':raw.value['posx'][2]+=1.
        if failure=='force':raw.value['wrench'][2]=36.
        return check(target)
    raw.check_pose=changed
    with pytest.raises((RuntimeError,TimeoutError,ValueError)):
        run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert raw.blends==[] and raw.grips==[]


def test_blend_uses_fresh_start_after_ik_instead_of_rejecting_position_difference():
    d,p,raw,events,c,points=blend_state();check=raw.check_pose
    def settled_pose(target):
        raw.value['posx'][0]=.1
        return check(target)
    raw.check_pose=settled_pose
    run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert len(raw.blends)==1
    recheck=next(v for e,v in events if e=='BLEND_START_RECHECK')
    assert recheck['position_drift_mm']>.05 and recheck['current_sample']['posx'][0]==.1


@pytest.mark.parametrize('changes',[
    dict(radius=0),dict(radius=31),dict(radius=float('nan')),
    dict(points=[[20.,0.,100.,0.,0.,0.]]),
    dict(points=[[20.,0.,90.,0.,0.,0.],[20.,20.,90.,0.,0.,0.]]),
    dict(points=[[20.,0.,100.,0.,0.,0.],[40.,0.,100.,0.,0.,0.]]),
    dict(points=[[5.,0.,100.,0.,0.,0.],[5.,20.,100.,0.,0.,0.]])])
def test_invalid_geometry_is_rejected(changes):
    d,p,raw,events,c,points=blend_state()
    with pytest.raises(ValueError):validate_route(raw.value['posx'],changes.get('points',points),changes.get('radius',5.))
    assert not raw.blends


@pytest.mark.parametrize('failure',['force','grip','corridor','ack'])
def test_blend_failure_stops_without_another_move_or_gripper(failure):
    d,p,raw,events,c,points=blend_state();original=raw.move_blending_async
    def command(*args):
        original(*args)
        if failure=='force':raw.value['wrench'][2]=36.
        if failure=='grip':raw.value['gripper_status']=0
        if failure=='corridor':raw.value['posx'][:3]=[90.,90.,100.]
        if failure=='ack':raise RuntimeError('ACK_FAILED')
    raw.move_blending_async=command
    with pytest.raises(RuntimeError):run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert len(raw.blends)==1 and raw.stops==1 and not raw.grips
    if failure=='ack':assert d.command_outcome_unknown


@pytest.mark.parametrize('radius',[5.,15.,30.])
def test_ros_serialization_is_14_fields_per_line_and_async_base_absolute(monkeypatch,radius):
    class Message:pass
    module=SimpleNamespace(Float64MultiArray=Message)
    monkeypatch.setitem(sys.modules,'std_msgs',SimpleNamespace(msg=module));monkeypatch.setitem(sys.modules,'std_msgs.msg',module)
    raw=ros_driver();points=[[20.,0.,100.,0.,0.,0.],[20.,20.,100.,0.,0.,0.]]
    raw.move_blending_async(points,radius,[32.,32.],[16.,16.])
    path,kind,fields=raw.calls[-1]
    assert (path,kind)==('motion/move_blending','MoveBlending')
    assert fields['sync_type']==1 and fields['ref']==0 and fields['mode']==0 and fields['pos_cnt']==2
    assert fields['segment'][0].data==[*points[0],*([0.]*6),0.,radius]
    assert fields['vel']==[32.,32.] and fields['acc']==[16.,16.]


def test_batch_requires_local_review_reference_before_real_dispatch():
    s,plan,p,events,c=setup();p.update(transport_blending=dict(reviewed=True,radius_mm=5.))
    plan['settings']['physical_reference_reviewed']=True;p['profile_id']='ONSITE_PROFILE';p['physical_route_reviewed']=True
    v=dict(s.value,backend='REAL',provenance='LOCAL_OPERATOR_TRIAL',source_epoch='ONSITE_BLEND',profile_id=p['profile_id'],expires_unix_s=10**12,
        exclusive_control_reviewed=True,device_feedback_reviewed=True,stillness_parameters_reviewed=True,hand_clear_reviewed=True)
    with pytest.raises(ValueError,match='TRANSPORT_BLEND_REVIEW'):validate_execution(plan,p,v,'pickup')
    v['transport_blend_review_ref']='human-route-review';validate_execution(plan,p,v,'pickup')
