from copy import deepcopy
import pytest

from app.control_driver import ControlledDriver, execute_step
from app.assembly_step_runner import StepReplayDriver, replay_profile
from app.assembly_step_bridge import build_plan, candidate_profile, load_steps
from app.control_session import ControlSession
from scripts.robot_control_trial import test_session as session_fixture
from test_control_session import setup, verified_sample

CONNECTION=dict(tcp='GripperDA_v4',tool='ToolWeight0')


@pytest.mark.parametrize('owner',['MOTION','CONTACT'])
@pytest.mark.parametrize('change',['fresh','expired','new_sample','cancelled'])
def test_owner_reuses_current_stop_proof_but_rechecks_stale_or_cancelled(owner,change):
    s,plan,_,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    proof=driver.stillness();verified=sum(e=='STILLNESS_WINDOW_VERIFIED' for e,_ in events)
    if change=='expired':clock.sleep(s.value['stillness']['sample_max_duration_s']+.01)
    if change=='new_sample':driver.sample()
    if change=='cancelled':
        s.request_stop()
        with pytest.raises(RuntimeError,match='STOP_REQUESTED'):driver.own(owner,verified_snapshot=proof)
        assert not raw.moves and not raw.grips
        return
    driver.own(owner,verified_snapshot=proof)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,_ in events)==verified+(change!='fresh')
    assert s.owner==owner and driver.last_verified_sample is None


def test_gripper_command_consumes_fresh_owner_stillness_once_without_duplicate_window():
    s,plan,_,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    driver.own('GRIPPER')
    verified=sum(e=='STILLNESS_WINDOW_VERIFIED' for e,_ in events)
    driver.command_gripper(35.,40.)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,_ in events)==verified
    assert raw.grips==[(35.,40.)]
    driver.command_gripper(48.,40.)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,_ in events)==verified+1


@pytest.mark.parametrize('change',['expired','new_sample','monitor','precondition'])
def test_gripper_rechecks_when_owner_proof_is_old_or_human_response_is_needed(change):
    s,plan,_,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    driver.own('GRIPPER');verified=sum(e=='STILLNESS_WINDOW_VERIFIED' for e,_ in events)
    callbacks=[];kwargs={}
    if change=='expired':clock.sleep(s.value['stillness']['sample_max_duration_s']+.01)
    if change=='new_sample':driver.sample()
    if change=='monitor':kwargs['during_stillness']=lambda _:callbacks.append(True)
    if change=='precondition':kwargs['precondition']=lambda:callbacks.append(True)
    driver.command_gripper(35.,40.,**kwargs)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,_ in events)==verified+1
    if change in ('monitor','precondition'):assert callbacks
    assert raw.grips==[(35.,40.)]


def run(s,plan,profile,clock,raw,confirm=lambda *a:True,phase='full',record=None):
    return execute_step(raw,s,CONNECTION,plan,profile,confirm,record or s.record,
                        phase=phase,clock=clock,sleep=clock.sleep)


def test_full_integration_uses_one_driver_and_leaves_current_for_backend():
    s,plan,profile,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    result=run(s,plan,profile,clock,raw)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION'
    assert not result['assembly_completion'] and not result['current_update']
    assert not result['backend_current_committed'] and not result['physical_verified']
    assert raw.grips and raw.moves and raw.stops
    assert s.owner=='NONE' and s.lease is None and s.request is None
    owners={d['owner'] for e,d in events if e=='ADAPTER_LEASE_APPLIED'}
    assert owners=={'WAIT','MOTION','CONTACT','GRIPPER'}
    assert result['contact_evidence']['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert sum(e=='SINGLE_WRITER_GRIPPER' for e,_ in events)==len(raw.grips)


@pytest.mark.parametrize('speed',[.017,1.,5.])
def test_pickup_uses_session_stop_tolerances_for_start_grip_and_wait(speed):
    s,plan,profile,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    s.value['stillness'].update(linear_mm_s=5.,angular_deg_s=5.,position_mm=1.,orientation_deg=1.)
    original=raw.sample
    def sample():
        row=original();row['velx']=[speed,0.,0.,0.,speed,0.];return row
    raw.sample=sample
    result=run(s,plan,profile,clock,raw,phase='pickup')
    assert result['status']=='PAUSED_PICKUP_COMPLETE_HOLDING'
    assert raw.grips[-1]==(plan['settings']['pickup_width_mm'],profile['gripper_force_n'])
    assert not raw.stops


@pytest.mark.parametrize('settling_speed',[.001,.02])
def test_grasp_confirmation_waits_for_reviewed_stillness_after_grip_feedback(settling_speed):
    s,plan,profile,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    original=raw.sample;feedback=[0];injected=[False];confirmed=[]
    def record(event,data):
        events.append((event,deepcopy(data)))
        if event=='GRIPPER_FEEDBACK' and data['gripper_status']==2:feedback[0]+=1
    s.record=record
    def sample():
        row=original()
        if feedback[0]>=3 and not injected[0]:
            injected[0]=True
            return dict(row,velx=[settling_speed,0.,0.,0.,0.,0.])
        return row
    raw.sample=sample
    def confirm(req,*args):
        confirmed.append(req['kind']);return True
    result=run(s,plan,profile,clock,raw,confirm,phase='pickup',record=record)
    assert injected[0] and result['status']=='PAUSED_PICKUP_COMPLETE_HOLDING'
    assert 'GRASP_CONFIRMED' in confirmed
    grip_index=max(i for i,(event,data) in enumerate(events) if event=='GRIPPER_FEEDBACK')
    wait_index=next(i for i,(event,data) in enumerate(events) if event=='WAIT_GRASP_CONFIRMED')
    assert any(event=='STILLNESS_WINDOW_VERIFIED' for event,data in events[grip_index+1:wait_index])
    assert not raw.stops


def test_persistent_post_grasp_motion_blocks_confirmation_and_keeps_gripper_closed():
    s,plan,profile,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    original=raw.sample;feedback=[0];confirmed=[]
    def record(event,data):
        events.append((event,deepcopy(data)))
        if event=='GRIPPER_FEEDBACK' and data['gripper_status']==2:feedback[0]+=1
    s.record=record
    raw.sample=lambda:dict(original(),velx=[.02,0.,0.,0.,0.,0.]) if feedback[0]>=3 else original()
    with pytest.raises(TimeoutError,match='STOP_WINDOW_NOT_VERIFIED'):
        run(s,plan,profile,clock,raw,lambda req,*a:confirmed.append(req['kind']) or True,phase='pickup',record=record)
    assert 'GRASP_CONFIRMED' not in confirmed and raw.value['gripper_status']==2
    assert len(raw.grips)==2 and raw.grips[-1][0]==40.
    assert raw.stops and s.cancelled


def test_verified_gesture_replaces_only_the_active_support_reply():
    steps=load_steps();step=next(x for x in steps if x['case_id'].startswith('04_'))
    profile=replay_profile(candidate_profile(steps),[step]);plan=build_plan(step,profile)
    s,_,_,events,clock=setup()
    value=session_fixture(plan);value['expires_unix_s']=1000
    s=ControlSession(value,plan,lambda e,d:events.append((e,deepcopy(d))),clock=clock,wall=lambda:100)
    raw=StepReplayDriver(plan['settings']['reference_pose'])
    def answer(req,plan,sample,active):
        if req['kind']!='HUMAN_READY':return True
        for i in range(21):
            t=1_000_000_000+i*100_000_000
            result=active.gesture(verified_sample(active,req,t),t)
        return result
    result=run(s,plan,profile,clock,raw,answer)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION'
    replies=[d for e,d in events if e=='HUMAN_RESPONSE']
    assert sum(d['source']=='VERIFIED_GESTURE' for d in replies)==1
    assert not result['current_update']


def test_negative_seating_reply_never_opens_or_retreats():
    s,plan,profile,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=2,gripper_width_mm=40.)
    raw.value['posx']=plan['settings']['reference_pose'].copy();raw.value['posx'][2]+=20.1
    result=run(s,plan,profile,clock,raw,lambda req,*a:req['kind']!='FULL_SEATING',phase='contact')
    assert result['status']=='PAUSED_FULL_SEATING'
    assert not raw.grips and raw.value['gripper_status']==2


def test_stop_during_human_wait_stops_without_open_or_motion():
    s,plan,profile,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    def cancel(req,plan,sample,active):
        active.request_stop();return True
    with pytest.raises(RuntimeError):run(s,plan,profile,clock,raw,cancel)
    assert not raw.moves and not raw.grips and raw.stops>=1
    assert s.cancelled and s.lease is None


def test_gripper_service_write_ack_without_width_change_never_retreats():
    s,plan,profile,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=2,gripper_width_mm=40.)
    raw.command_gripper=lambda *a:None
    with pytest.raises(TimeoutError,match='COMPLETION_NOT_VERIFIED'):
        run(s,plan,profile,clock,raw,phase='release')
    assert not raw.moves and raw.stops>=1 and s.cancelled


@pytest.mark.parametrize('change', [dict(velx=None),dict(query_duration_s=1.),dict(tcp='wrong'),
                                  dict(gripper_status=1),dict(robot_mode=0)])
def test_invalid_stop_signals_block_handoff_before_motion(change):
    s,plan,_,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(change)
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    with pytest.raises((ValueError,RuntimeError,TimeoutError)):
        driver.own('CONTACT')
    assert s.lease is None and not raw.moves and not raw.grips


def test_a_single_still_sample_is_not_a_window():
    s,plan,_,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    count=[0]
    old=raw.sample
    def sample():
        count[0]+=1;row=old()
        if count[0]>1:row['velx'][0]=10
        return row
    raw.sample=sample
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    with pytest.raises(TimeoutError,match='STOP_WINDOW'):
        driver.own('CONTACT')
    assert count[0]>1 and s.lease is None


def test_log_failure_blocks_gripper_write_but_stop_still_sent():
    s,plan,profile,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=2,gripper_width_mm=40.)
    def journal(event,data):
        if event=='SINGLE_WRITER_GRIPPER':raise OSError('DISK_FULL')
    s.record=journal
    with pytest.raises(OSError,match='DISK_FULL'):
        run(s,plan,profile,clock,raw,phase='release',record=journal)
    assert not raw.grips and raw.stops>=1


def test_unowned_write_is_rejected_and_stale_lease_cannot_execute():
    s,plan,_,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    with pytest.raises(RuntimeError,match='LEASE'):
        driver.command_gripper(62,40)
    driver.own('MOTION')
    with pytest.raises(RuntimeError,match='LEASE'):
        driver.command_gripper(62,40)
    assert not raw.grips


def test_one_execution_object_cannot_replay_the_same_step():
    s,plan,profile,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    run(s,plan,profile,clock,raw)
    before=(len(raw.moves),len(raw.grips))
    with pytest.raises(RuntimeError,match='EXECUTION_ALREADY_CLAIMED'):
        run(s,plan,profile,clock,raw)
    assert before==(len(raw.moves),len(raw.grips))


def test_stop_during_stillness_check_is_observed_before_handoff():
    s,plan,_,_,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    def sleep(t):
        clock.sleep(t);s.request_stop()
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=sleep)
    with pytest.raises(RuntimeError,match='STOP_REQUESTED'):
        driver.own('CONTACT')
    assert not raw.moves and not raw.grips and s.lease is None


def test_lost_command_ack_cannot_be_hidden_by_an_idle_stop_window():
    s,plan,_,events,clock=setup();raw=StepReplayDriver(plan['settings']['reference_pose'])
    def lost(*args):raise TimeoutError('MOVE_ACK_LOST')
    raw.move_line_async=lost
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    driver.own('MOTION')
    with pytest.raises(TimeoutError):driver.move_line_async([0]*6,[1,1],[1,1])
    s.request_stop()
    with pytest.raises(RuntimeError,match='PENDING_COMMAND_OUTCOME_UNKNOWN'):
        driver.stop()
    result=next(d for e,d in events if e=='STOP_WINDOW_RESULT')
    assert result['stillness_window_verified'] and not result['actual_stop_verified']
    assert result['pending_command_outcome_unknown']
