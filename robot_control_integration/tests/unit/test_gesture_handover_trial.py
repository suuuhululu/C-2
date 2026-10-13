"""Loaded local handover: preview may stop, only post-stop HMI may open."""
from copy import deepcopy
import pytest
from app.assembly_step_runner import StepReplayDriver
from app.control_driver import execute_step
from app.gesture_handover_trial import validate_handover
from test_control_session import setup

CONNECTION=dict(tcp='GripperDA_v4', tool='ToolWeight0')


def trial(candidate=True, camera_change=None, release=True, start=True, grip_change=None, broken_stop=False):
    session,plan,profile,events,clock=setup()
    plan['settings'].update(release_width_mm=62.4, release_feedback_range_mm=[60.,64.2],
        pickup_pose=[-333.,49.,52.,75.,-177.,75.],
        handover_trial=dict(operator_armed_preview_stop_trial=True, observe_route_reviewed=True,
                            observe_pose=[400.851,8.573,314.981,75.,-177.,75.]))
    session.value['allowed_trial_phase']='handover'
    raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(posx=[-333.,49.,52.,75.,-177.,75.],gripper_status=2,gripper_width_mm=40.)
    polls=[]
    def camera():
        assert session.request['kind']=='RECEIVE'
        polls.append(session.request['request_id'])
        row=dict(**session.binding,execution_id=session.value['execution_id'],
                 source_epoch=session.value['source_epoch'],preview_request_id=session.request['request_id'],
                 received_monotonic_ns=round(clock()*1e9),provenance='SENSOR',
                 pose_verified=False,capture_clock_verified=False,
                 candidate_event='OPEN_HAND_HELD_ORIENTATION_UNKNOWN' if candidate and len(polls)>1 else None)
        if camera_change: return camera_change(row, len(polls), clock)
        return row
    if grip_change:
        command=raw.command_gripper
        def grip(*args):command(*args);raw.value.update(grip_change)
        raw.command_gripper=grip
    if broken_stop:
        def stop():raw.stops+=1;raise RuntimeError('STOP_ACK_FAILED')
        raw.stop=stop
    def confirm(req,*args):
        return start if req['kind']=='START_HANDOVER' else release
    def execute():
        return execute_step(raw,session,CONNECTION,plan,profile,confirm,session.record,
                phase='handover',start_zone=session.value.get('handover_start_zone','supply'),
                camera_poll=camera,clock=clock,sleep=clock.sleep)
    return execute,raw,events,session,plan,profile,polls


def test_stop_then_fresh_hmi_then_open_then_observe():
    execute,raw,events,s,plan,_,polls=trial()
    result=execute()
    assert result['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'
    assert result['motion_stop_verified'] and result['observe_point_verified']
    assert result['release_requires_post_stop_hmi'] and not result['preview_is_verified_gesture']
    assert not result['physical_verified'] and not result['assembly_completion'] and not result['current_update']
    names=[e for e,d in events]
    stop=names.index('HANDOVER_PREVIEW_REQUESTED_STOP')
    assert stop<names.index('STOP_WINDOW_RESULT')<names.index('WAIT_HANDOVER_RELEASE')<names.index('SINGLE_WRITER_GRIPPER')
    labels=[d['label'] for e,d in events if e=='STEP_MOVE']
    assert labels==['HANDOVER_LIFT','SUPPLY_20_0','BODY_BYPASS','PLACE_BOARD','HANDOVER_INCOMING',
                    'HANDOVER_EMPTY_PLACE','OBSERVE_HEIGHT_LIFT','OBSERVE_POINT']
    replies=[d for e,d in events if e=='HUMAN_RESPONSE']
    assert len(replies)==2 and all(d['source']=='HMI' for d in replies)
    assert raw.grips==[(62.4,40.)] and raw.stops==1
    assert raw.value['posx']==plan['settings']['handover_trial']['observe_pose']
    assert s.request is None and s.lease is None and s.owner=='NONE'
    assert len(set(polls))==2
    assert names.index('HANDOVER_CAMERA_READY_BEFORE_MOTION')<names.index('SINGLE_WRITER_MOVE')


@pytest.mark.parametrize('speed',[.017,5.])
def test_handover_release_uses_session_stop_tolerance(speed):
    execute,raw,events,s,*_=trial()
    s.value['stillness'].update(linear_mm_s=5.,angular_deg_s=5.,position_mm=1.,orientation_deg=1.)
    original=raw.sample
    def sample():
        row=original();row['velx']=[speed,0.,0.,0.,speed,0.];return row
    raw.sample=sample
    assert execute()['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'
    assert raw.grips==[(62.4,40.)]


@pytest.mark.parametrize('start,release,status', [(False,True,'PAUSED_START'),
    (True,False,'PAUSED_HANDOVER_RECEIVING_CONFIRMATION')])
def test_hmi_decline_never_opens_or_returns(start, release, status):
    execute,raw,events,*_=trial(start=start,release=release)
    assert execute()['status']==status
    assert not raw.grips
    assert not any(e=='STEP_MOVE' and d['label'].startswith('OBSERVE') for e,d in events)
    if not start:assert not raw.moves


def test_no_gesture_finishes_holding_without_return():
    execute,raw,events,*_=trial(candidate=False)
    assert execute()['status']=='PAUSED_HANDOVER_NO_GESTURE_HOLDING'
    assert not raw.grips and raw.stops==0
    assert not any(e=='WAIT_HANDOVER_RELEASE' for e,d in events)


@pytest.mark.parametrize('field,value,error', [('execution_id','old','CONTEXT_MISMATCH'),
    ('source_epoch','old','CONTEXT_MISMATCH'),('plan_id','old','CONTEXT_MISMATCH'),
    ('step_id','old','CONTEXT_MISMATCH'),('current_revision',99,'CONTEXT_MISMATCH'),
    ('preview_request_id','old','REQUEST_MISMATCH')])
def test_wrong_camera_context_cannot_open(field,value,error):
    def change(row,*_):return dict(row,**{field:value})
    execute,raw,events,*_=trial(camera_change=change)
    with pytest.raises(RuntimeError,match=error):execute()
    assert not raw.grips and raw.stops>=1
    assert not any(e=='STEP_MOVE' and d['label']=='HANDOVER_INCOMING' for e,d in events)


@pytest.mark.parametrize('bad', ['missing','old','future','duplicate'])
def test_camera_loss_during_incoming_stops_without_open(bad):
    def change(row,n,clock):
        if n<=2:return row
        clock.sleep(.31)
        if bad=='missing':return None
        return dict(row,received_monotonic_ns=0 if bad=='duplicate' else round((clock()+ (1 if bad=='future' else -1))*1e9))
    execute,raw,events,*_=trial(camera_change=change)
    with pytest.raises(RuntimeError,match='CAMERA_STALE'):execute()
    assert raw.stops>=1 and not raw.grips
    assert any(e=='STEP_MOVE' and d['label']=='HANDOVER_INCOMING' for e,d in events)


def test_camera_not_ready_blocks_incoming():
    execute,raw,events,*_=trial(camera_change=lambda *_:None)
    with pytest.raises(RuntimeError,match='CAMERA_NOT_READY'):execute()
    assert not raw.grips
    assert not raw.moves
    assert not any(e=='STEP_MOVE' and d['label']=='HANDOVER_INCOMING' for e,d in events)


def test_unacknowledged_stop_never_opens():
    execute,raw,events,*_=trial(broken_stop=True)
    with pytest.raises(RuntimeError,match='HANDOVER_STOP_NOT_VERIFIED'):execute()
    assert not raw.grips and not any(e=='WAIT_HANDOVER_RELEASE' for e,d in events)


@pytest.mark.parametrize('change', [dict(gripper_status=1),dict(gripper_status=4),
    dict(gripper_width_mm=40.),dict(gripper_width_mm=float('nan')),
    dict(query_duration_s=.6),dict(tcp='wrong')])
def test_gripper_completion_fault_blocks_observe(change):
    execute,raw,events,*_=trial(grip_change=change)
    with pytest.raises((RuntimeError,TimeoutError)):execute()
    assert raw.grips and not any(e=='STEP_MOVE' and d['label'].startswith('OBSERVE') for e,d in events)


@pytest.mark.parametrize('width', [60.,64.2,64.4,72.])
def test_opening_above_old_limit_is_accepted(width):
    execute,raw,*_=trial(grip_change=dict(gripper_width_mm=width))
    assert execute()['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'


@pytest.mark.parametrize('field', ['operator_armed_preview_stop_trial','observe_route_reviewed'])
def test_handover_review_required(field):
    _,_,_,s,plan,profile,_=trial()
    plan['settings']['handover_trial'][field]=False
    with pytest.raises(ValueError,match='REVIEW_REQUIRED'):validate_handover(plan,profile,s.value)


def test_handover_cannot_start_at_assembly_instead_of_source_slot():
    execute,raw,*_=trial()
    raw.value['posx'][0]+=10.
    with pytest.raises(RuntimeError,match='REVIEWED_START_POSE'):execute()
    assert not raw.moves and not raw.grips


def test_force_fault_during_incoming_takes_priority_over_open_hand():
    execute,raw,events,*_=trial()
    original=raw.move_line_async
    def move(*args):
        original(*args)
        if len(raw.moves)==5:raw.value['wrench'][2]=36.
    raw.move_line_async=move
    with pytest.raises(RuntimeError,match='FORCE_NORM_STOP'):execute()
    assert not raw.grips and not any(e=='WAIT_HANDOVER_RELEASE' for e,d in events)


def place_recovery(camera_change=None):
    state=trial(camera_change=camera_change)
    execute,raw,events,s,plan,profile,polls=state
    start=[*profile['place_pose'][:2],profile['clearance_z_mm'],*raw.value['posx'][3:]]
    raw.value['posx']=start.copy()
    s.value.update(handover_start_zone='place',handover_start_pose=start.copy(),
                   recovery_evidence_ref='READONLY_LOCAL_PLACE_RECOVERY')
    return state


def test_reviewed_place_recovery_skips_supply_route():
    execute,raw,events,*_=place_recovery()
    assert execute()['status']=='LOCAL_HANDOVER_OBSERVE_COMPLETE'
    labels=[d['label'] for e,d in events if e=='STEP_MOVE']
    assert labels==['HANDOVER_INCOMING','HANDOVER_EMPTY_PLACE','OBSERVE_HEIGHT_LIFT','OBSERVE_POINT']
    assert raw.grips==[(62.4,40.)] and raw.stops==1


def test_place_recovery_with_no_camera_never_moves():
    execute,raw,*_=place_recovery(camera_change=lambda *_:None)
    with pytest.raises(RuntimeError,match='CAMERA_NOT_READY'):execute()
    assert not raw.moves and not raw.grips


@pytest.mark.parametrize('change', [dict(recovery_evidence_ref=None),
    dict(handover_start_pose=[0.,0.,200.,75.,-177.,75.]),dict(handover_start_zone='assembly')])
def test_unreviewed_place_recovery_is_rejected(change):
    _,raw,_,s,plan,profile,_=place_recovery()
    s.value.update(change)
    with pytest.raises(ValueError):validate_handover(plan,profile,s.value)
    assert not raw.moves and not raw.grips


def test_robot_changed_from_reviewed_place_pose_cannot_resume():
    execute,raw,*_=place_recovery()
    raw.value['posx'][0]+=10.
    with pytest.raises(RuntimeError,match='HANDOVER_REQUIRES'):execute()
    assert not raw.moves and not raw.grips


def test_start_pose_is_rechecked_after_camera_warmup():
    def change(row,n,*_):
        if n==1:raw.value['posx'][0]+=10.
        return row
    execute,raw,*_=trial(camera_change=change)
    with pytest.raises(RuntimeError,match='REVIEWED_START_POSE'):execute()
    assert not raw.moves and not raw.grips


@pytest.mark.parametrize('requested', ['assembly','supply'])
def test_place_session_cannot_run_a_different_start_zone(requested):
    _,raw,_,s,plan,profile,_=place_recovery()
    clock=s.clock
    with pytest.raises(ValueError,match='START_ZONE_SESSION_MISMATCH'):
        execute_step(raw,s,CONNECTION,plan,profile,lambda *_:True,s.record,
                     phase='handover',start_zone=requested,camera_poll=lambda:None,
                     clock=clock,sleep=clock.sleep)
    assert not raw.moves and not raw.grips
