from copy import deepcopy
import pytest
from app.assembly_step_runner import StepReplayDriver
from app.control_driver import ControlledDriver,execute_step
from app.control_session import ControlSession,validate_session
from app.automatic_stage_trial import check_stage
from test_control_session import setup

CONNECTION=dict(tcp='GripperDA_v4',tool='ToolWeight0')


def automatic():
    session,plan,profile,events,clock=setup()
    plan['settings'].update(turn_base_z_deg=0.,pickup_start_open_range_mm=[47.,110.],release_width_mm=48.,release_feedback_range_mm=[47.,110.])
    plan['mode']='ROBOT_GRIP';plan['assistance_kind']='NONE'
    value=deepcopy(session.value)
    value['automatic_stage_checks']=dict(enabled=True,review_ref='SYNTHETIC_USER_AUTHORIZATION',block=deepcopy(plan['block']),release_after_contact_stop=True)
    value['stillness'].update(window_s=.25,min_samples=3)
    session=ControlSession(value,plan,session.record,clock=clock,wall=lambda:100.)
    return session,plan,profile,events,clock


def test_no_input_full_flow_records_sensor_permission_not_human_or_assembly_completion():
    s,plan,p,events,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=0,gripper_width_mm=48.3)
    result=execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('HMI must not be called'),s.record,phase='full',clock=clock,sleep=clock.sleep)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION'
    assert result['automatic_contact_release_policy_passed'] and not result['operator_seating_confirmed']
    assert not result['assembly_completion'] and not result['current_update'] and not result['physical_verified']
    assert raw.grips[-1]==(48.,40.)
    kinds=[d['kind'] for e,d in events if e=='AUTOMATIC_STAGE_CHECK']
    assert kinds==['START_FULL','PICKUP_ALIGNMENT','GRASP_CONFIRMED','ALIGNMENT_AND_PARALLEL','FULL_SEATING','RELEASE']
    assert not any(e in ('HUMAN_REQUEST_OPENED','HUMAN_RESPONSE') for e,d in events)


@pytest.mark.parametrize('kind',['START_FULL','START_PICKUP'])
def test_empty_gripper_may_start_before_preparation_opens_it(kind):
    s,plan,p,_,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=0,gripper_width_mm=45.6)
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    assert check_stage(driver,kind,plan,p,raw.sample())['decision']=='CONTINUE'
    assert raw.grips==[] and raw.moves==[]


@pytest.mark.parametrize('width',[45.6,47.])
def test_slot_descent_still_requires_prepared_open_clearance(width):
    s,plan,p,_,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    above=plan['settings']['pickup_pose'].copy()
    above[2]=max(p['clearance_z_mm'],plan['settings']['reference_pose'][2]+p['approach_offset_mm'])
    raw.value.update(posx=above,gripper_status=0,gripper_width_mm=width)
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    if width<47.:
        with pytest.raises(RuntimeError,match='AUTOMATIC_PICKUP_NOT_OPEN'):
            check_stage(driver,'PICKUP_ALIGNMENT',plan,p,raw.sample())
    else:
        assert check_stage(driver,'PICKUP_ALIGNMENT',plan,p,raw.sample())['decision']=='CONTINUE'
    assert raw.grips==[] and raw.moves==[]


@pytest.mark.parametrize('mutation',[
    lambda s,p:s['automatic_stage_checks'].update(enabled=False),
    lambda s,p:s['automatic_stage_checks'].update(review_ref=''),
    lambda s,p:s['automatic_stage_checks']['block'].update(x=23),
    lambda s,p:s.update(provenance='LIVE_D_RUNTIME'),
    lambda s,p:p.update(assistance_kind='HOLD'),
    lambda s,p:p['settings'].update(turn_base_z_deg=90),
])
def test_automatic_mode_requires_scoped_local_authorization(mutation):
    s,plan,*_=automatic();v=deepcopy(s.value);mutation(v,plan)
    with pytest.raises(ValueError):validate_session(v,plan,backend=v['backend'])


@pytest.mark.parametrize('kind',['FULL_SEATING','RELEASE'])
def test_force_without_verified_stop_cannot_authorize_open(kind):
    s,plan,p,_,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose']);raw.value.update(gripper_status=2)
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    driver.last_contact_result=dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED',force_stop_n=p['force_stop_n'],stop=dict(requested=True,acknowledged=True,stillness_verified=False))
    with pytest.raises(RuntimeError,match='CONTACT_STOP'):check_stage(driver,kind,plan,p,raw.sample())
    assert not raw.grips


def test_unconfigured_human_assistance_stage_is_never_auto_accepted():
    s,plan,p,_,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    with pytest.raises(RuntimeError,match='NOT_SUPPORTED'):check_stage(driver,'HUMAN_READY',plan,p,raw.sample())


def test_prepared_start_pose_change_blocks_all_gripper_commands():
    s,plan,p,_,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=0,gripper_width_mm=49.8)
    s.value['automatic_start_pose']=raw.value['posx'].copy()
    raw.value['posx'][0]+=2.
    with pytest.raises(RuntimeError,match='POSE_MISMATCH'):
        execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('No HMI'),s.record,
            phase='full',clock=clock,sleep=clock.sleep)
    assert raw.grips==[] and raw.moves==[]


def test_held_approach_uses_bound_start_without_hmi_pickup_or_contact():
    s,plan,p,events,clock=automatic();raw=StepReplayDriver(plan['settings']['pickup_pose'])
    raw.value.update(gripper_status=2,gripper_width_mm=40.6)
    s.value['automatic_start_pose']=raw.value['posx'].copy()
    r=execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('No HMI'),s.record,
        phase='approach',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert r['status']=='PAUSED_APPROACH_REACHED' and raw.moves and not raw.grips
    assert raw.value['posx'][:3]==plan['settings']['reference_pose'][:2]+[plan['settings']['reference_pose'][2]+p['approach_offset_mm']]
    assert not any(e=='PRESS_SESSION' for e,d in events)


@pytest.mark.parametrize('failure',['no_start','changed_start','empty_gripper'])
def test_held_approach_checks_start_and_grip_before_motion(failure):
    s,plan,p,events,clock=automatic();raw=StepReplayDriver(plan['settings']['pickup_pose'])
    raw.value.update(gripper_status=2,gripper_width_mm=40.6)
    if failure!='no_start':s.value['automatic_start_pose']=raw.value['posx'].copy()
    if failure=='changed_start':raw.value['posx'][0]+=2.
    if failure=='empty_gripper':raw.value['gripper_status']=0
    with pytest.raises(RuntimeError):
        execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('No HMI'),s.record,
            phase='approach',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert not raw.grips and not raw.moves


def test_contact_only_uses_reviewed_alignment_and_stops_holding_at_force():
    s,plan,p,events,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    above=plan['settings']['reference_pose'].copy();above[2]+=p['approach_offset_mm']
    raw.value.update(posx=above,gripper_status=2,gripper_width_mm=40.6)
    s.value.update(automatic_start_pose=above,allowed_trial_phase='contact',alignment_evidence_ref='USER_PARALLEL_CONFIRMATION')
    r=execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('No HMI'),s.record,
        phase='contact',clock=clock,sleep=clock.sleep)
    assert r['status']=='PAUSED_SEATED_RELEASE_PENDING' and raw.value['gripper_status']==2
    assert r['contact_evidence']['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert not raw.grips and not r['assembly_completion']


def test_contact_only_without_alignment_cannot_descend():
    s,plan,p,events,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    above=plan['settings']['reference_pose'].copy();above[2]+=p['approach_offset_mm']
    raw.value.update(posx=above,gripper_status=2)
    s.value.update(automatic_start_pose=above,allowed_trial_phase='contact')
    s.value.pop('alignment_evidence_ref',None)
    with pytest.raises(RuntimeError,match='REVIEWED_CONTACT_POSE_REQUIRED'):
        execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('No HMI'),s.record,
            phase='contact',clock=clock,sleep=clock.sleep)
    assert not raw.moves and not raw.grips


def test_contact_stop_at_wrong_xy_never_authorizes_release():
    s,plan,p,_,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(gripper_status=2)
    driver=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    driver.trial_grasp_reference=raw.value['posx'].copy()
    raw.value['posx'][0]+=2.
    driver.last_contact_result=dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED',
        force_stop_n=p['force_stop_n'],stop=dict(requested=True,acknowledged=True,stillness_verified=True),
        final_sample=raw.sample())
    with pytest.raises(RuntimeError,match='CONTACT_TARGET_DRIFT'):
        check_stage(driver,'RELEASE',plan,p,raw.sample())
    assert raw.grips==[]


def test_no_force_threshold_never_opens_in_automatic_trial():
    s,plan,p,_,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose']);raw.value.update(gripper_status=2)
    raw.value['posx'][2]+=p['approach_offset_mm']
    move=raw.move_line_async
    def no_contact(*args):
        move(*args);raw.value['wrench'][2]=0.;raw.value['posx']=args[0].copy()
    raw.move_line_async=no_contact
    result=execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('No HMI'),s.record,phase='assemble-held',clock=clock,sleep=clock.sleep)
    assert result['status']=='PAUSED_MAX_TRAVEL_NO_FORCE' and raw.grips==[]


def test_wait_reuses_only_current_single_use_stillness_proof():
    s,plan,_,events,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose']);d=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    sample=d.stillness();n=sum(e=='STILLNESS_WINDOW_VERIFIED' for e,v in events)
    d.own('WAIT',verified_snapshot=sample)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,v in events)==n
    d.own('WAIT',verified_snapshot=sample)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,v in events)==n+1


@pytest.mark.parametrize('invalidate',['fresh_read','expired','movement_owner'])
def test_stale_or_command_boundary_proof_forces_new_window(invalidate):
    s,plan,_,events,clock=automatic();raw=StepReplayDriver(plan['settings']['reference_pose']);d=ControlledDriver(raw,s,CONNECTION,clock=clock,sleep=clock.sleep)
    sample=d.stillness();n=sum(e=='STILLNESS_WINDOW_VERIFIED' for e,v in events)
    if invalidate=='fresh_read':d.sample()
    if invalidate=='expired':clock.sleep(1.)
    if invalidate=='movement_owner':
        d.own('MOTION',verified_snapshot=sample)
        # A motion command consumes the owner-switch proof; the old window cannot authorize WAIT.
        d.move_line_async(raw.value['posx'].copy(),[1.,1.],[1.,1.])
    d.own('WAIT',verified_snapshot=sample)
    assert sum(e=='STILLNESS_WINDOW_VERIFIED' for e,v in events)==n+1
