from copy import deepcopy
import pytest

from app.assembly_step_bridge import build_plan,load_steps,candidate_profile,validate_physical
from app.assembly_step_runner import StepReplayDriver,replay_profile
from app.control_session import ControlSession,validate_execution
from app.control_driver import execute_step
from app.human_step_gestures import STAGES,validate_policy
from test_control_session import Clock
from scripts.robot_control_trial import test_session as session_fixture

CONNECTION=dict(tcp='GripperDA_v4',tool='ToolWeight0')


def trial(case='03',change=None):
    step=next(s for s in load_steps() if s['case_id'].startswith(case+'_'))
    p=replay_profile(candidate_profile([step]),[step]);p['clearance_z_mm']=194.73294067382812
    setting=p['steps'][step['case_id']+'/S01']
    if case=='03':setting['reference_pose']=[392.,5.,16.,75.,-177.,75.]
    setting['human_step_gestures']=dict(enabled=True,wait_z_mm=p['clearance_z_mm'],
        handover_width_mm=62.4,handover_feedback_range_mm=[60.,110.])
    plan=build_plan(step,p);clock=Clock();events=[]
    def record(e,d):events.append((e,deepcopy(d)))
    sv=session_fixture(plan);sv.update(expires_unix_s=1000.,human_step_gestures_review_ref='SYNTHETIC_AUTHORIZATION')
    s=ControlSession(sv,plan,record,clock=clock,wall=lambda:100.)
    raw=StepReplayDriver(setting['reference_pose']);hmi=[]
    def confirm(req,*args):
        assert req['kind'] not in STAGES
        hmi.append(req['kind']);return True
    def camera():
        clock.sleep(.05);req=s.request
        shape='OPEN_HAND' if req['kind']=='RECEIVE' else 'THUMBS_UP'
        hold=round((clock()-req['opened_monotonic_s'])*1e9)
        threshold=400_000_000 if shape=='OPEN_HAND' else 800_000_000
        row=dict(**s.binding,execution_id=s.value['execution_id'],source_epoch=s.value['source_epoch'],
            preview_request_id=req['request_id'],received_monotonic_ns=int(clock()*1e9),
            source_ns=round(clock()*1e9)+1,
            candidate_event=('OPEN_HAND_HELD_ORIENTATION_UNKNOWN' if shape=='OPEN_HAND' else 'THUMBS_UP_HELD') if hold>=threshold else None,
            held_ns=hold,continuity_estimate=hold>50_000_000,hands=[dict(pose=shape)],
            pose_verified=False,provenance='SENSOR')
        return change(row,s,raw) if change else row
    def execute(phase='full'):
        if phase=='approach':
            raw.value.update(gripper_status=2,gripper_width_mm=40.)
        if phase in ('human-wait','human-ack'):
            raw.value.update(gripper_status=0 if phase=='human-ack' else 2,
                gripper_width_mm=64.2 if phase=='human-ack' else 40.,
                posx=plan['settings']['reference_pose'][:2]+[p['clearance_z_mm']]+plan['settings']['pickup_pose'][3:])
        return execute_step(raw,s,CONNECTION,plan,p,confirm,record,phase=phase,
            camera_poll=camera,clock=clock,sleep=clock.sleep)
    return execute,raw,events,s,plan,p,hmi


def test_direct_assembly_receives_at_target_high_then_new_request_thumb_completion():
    execute,raw,events,s,plan,p,hmi=trial();r=execute()
    assert r['status']=='AWAITING_BACKEND_OBSERVATION' and r['human_completion_signal_received']
    assert not r['assembly_completion'] and not r['operator_seating_confirmed'] and not r['current_update']
    assert not any(e=='PRESS_SESSION' for e,d in events)
    waits=[(e,d['sample']['posx']) for e,d in events if e in ('WAIT_HUMAN_ASSEMBLY_RECEIVE','WAIT_HUMAN_ASSEMBLY_ACK')]
    assert len(waits)==2 and all(pose[:2]==plan['settings']['reference_pose'][:2] and pose[2]==p['clearance_z_mm'] for e,pose in waits)
    cues=[d for e,d in events if e=='LOCAL_HUMAN_STAGE_GESTURE']
    assert [d['kind'] for d in cues]==['HUMAN_ASSEMBLY_RECEIVE','HUMAN_ASSEMBLY_ACK']
    assert cues[0]['request_id']!=cues[1]['request_id'] and not any(d['verified_gesture'] for d in cues)
    assert raw.grips[-1]==(62.4,40.) and s.request is None
    assert 800_000_000<=cues[1]['candidate']['held_ns']<1_000_000_000


def test_receiving_shape_stays_open_after_preview_continuity_duration_reset():
    def change(row,s,raw):
        if s.owner=='GRIPPER':
            row.update(held_ns=0,continuity_estimate=False,candidate_event=None)
        return row
    execute,raw,*_=trial(change=change)
    assert execute()['human_completion_signal_received'] and raw.grips[-1]==(62.4,40.)


def test_real_logged_point_three_three_second_gap_with_open_hand_does_not_withdraw():
    def change(row,s,raw):
        if s.owner=='GRIPPER':
            s.clock.sleep(.333)
            row.update(held_ns=0,continuity_estimate=False,candidate_event=None,
                received_monotonic_ns=int(s.clock()*1e9),source_ns=int(s.clock()*1e9)+1)
        return row
    execute,raw,_,s,*_=trial(change=change)
    s.value['stillness'].update(max_gap_s=.5,window_s=.25,timeout_s=5.)
    assert execute()['human_completion_signal_received'] and raw.grips[-1]==(62.4,40.)


def test_resume_at_target_only_hands_over_held_block_without_pickup_or_motion():
    execute,raw,events,s,plan,p,hmi=trial()
    plan['settings'].update(turn_base_z_deg=0.,pickup_start_open_range_mm=[47.,110.])
    s.value.update(automatic_start_pose=plan['settings']['reference_pose'][:2]+[p['clearance_z_mm']]+plan['settings']['pickup_pose'][3:],
        automatic_stage_checks=dict(enabled=True,review_ref='SYNTHETIC_RESUME',
            block=deepcopy(plan['block']),release_after_contact_stop=True))
    r=execute('human-wait')
    assert r['human_completion_signal_received'] and not r['assembly_completion']
    assert hmi==[] and raw.moves==[] and raw.grips==[(62.4,40.)]


def test_resume_phase_cannot_bypass_robot_assisted_contact():
    execute,raw,*_=trial('04')
    with pytest.raises(ValueError,match='HUMAN_WAIT_REQUIRES_MANUAL'):execute('human-wait')
    assert raw.grips==[] and raw.moves==[]


def test_real_resume_requires_separate_review_and_cannot_be_reused_for_full_pickup():
    _,_,_,s,plan,p,_=trial()
    p.update(profile_id='ONSITE_HUMAN_RESUME',physical_route_reviewed=True)
    plan['settings']['physical_reference_reviewed']=True
    v=dict(s.value,backend='REAL',provenance='LOCAL_OPERATOR_TRIAL',source_epoch='ONSITE_HUMAN_RESUME',
        profile_id=p['profile_id'],expires_unix_s=10**10,allowed_trial_phase='human-wait',
        exclusive_control_reviewed=True,device_feedback_reviewed=True,stillness_parameters_reviewed=True,hand_clear_reviewed=True)
    with pytest.raises(ValueError,match='RESUME_REQUIRED'):validate_execution(plan,p,v,'human-wait')
    v['human_wait_resume_review_ref']='ONSITE_USER_REQUEST_AND_HELD_READONLY'
    validate_execution(plan,p,v,'human-wait')
    with pytest.raises(ValueError,match='OTHER_PHASES'):validate_execution(plan,p,v,'full')


def test_real_ack_only_requires_separate_handover_review_and_cannot_pick_with_that_session():
    _,_,_,s,plan,p,_=trial()
    p.update(profile_id='ONSITE_HUMAN_ACK_ONLY',physical_route_reviewed=True)
    plan['settings']['physical_reference_reviewed']=True
    v=dict(s.value,backend='REAL',provenance='LOCAL_OPERATOR_TRIAL',source_epoch='ONSITE_HUMAN_ACK_ONLY',
        profile_id=p['profile_id'],expires_unix_s=10**10,allowed_trial_phase='human-ack',
        exclusive_control_reviewed=True,device_feedback_reviewed=True,stillness_parameters_reviewed=True,hand_clear_reviewed=True)
    with pytest.raises(ValueError,match='ACK_RESUME_REQUIRED'):validate_execution(plan,p,v,'human-ack')
    v['human_ack_resume_review_ref']='PREVIOUS_HANDOVER_AND_EMPTY_READONLY'
    validate_execution(plan,p,v,'human-ack')
    with pytest.raises(ValueError,match='OTHER_PHASES'):validate_execution(plan,p,v,'pickup')


@pytest.mark.parametrize('value',[0.,.1,float('nan'),6.])
def test_invalid_human_thumb_duration_rejected(value):
    _,_,_,s,plan,p,_=trial()
    plan['settings']['human_step_gestures']['thumb_hold_seconds']=value
    with pytest.raises(ValueError,match='THUMB_HOLD'):validate_policy(plan,p,s.value)


@pytest.mark.parametrize('case',['03','04'])
def test_routine_sensor_checks_leave_only_human_stage_gestures(case):
    execute,raw,events,s,plan,p,hmi=trial(case)
    plan['settings'].update(turn_base_z_deg=0.,pickup_start_open_range_mm=[47.,110.])
    s.value['automatic_stage_checks']=dict(enabled=True,review_ref='SYNTHETIC_REQUEST',
        block=deepcopy(plan['block']),release_after_contact_stop=True)
    r=execute()
    assert r['status']=='AWAITING_BACKEND_OBSERVATION' and hmi==[]
    assert any(e=='LOCAL_HUMAN_STAGE_GESTURE' for e,d in events)
    assert not r['assembly_completion'] and not r['operator_seating_confirmed']


@pytest.mark.parametrize('case,ready',[('04','HUMAN_READY'),('05','HUMAN_HOLD_READY')])
def test_assistance_thumb_wait_precedes_approach_descent(case,ready):
    execute,raw,events,s,plan,p,_=trial(case)
    r=execute('approach');assert r['status']=='PAUSED_APPROACH_REACHED'
    names=[e for e,d in events]
    index=names.index('WAIT_'+ready)
    assert events[index][1]['sample']['posx'][2]==p['clearance_z_mm']
    lower=next(i for i,(e,d) in enumerate(events) if e=='STEP_MOVE' and d['label']=='TARGET_APPROACH_20MM')
    assert index<lower and sum(e=='WAIT_'+ready for e,d in events)==1


@pytest.mark.parametrize('case',['04','05'])
def test_assistance_full_flow_preserves_force_or_human_press_and_empty_retreat(case):
    execute,raw,events,s,plan,p,_=trial(case);r=execute()
    assert r['status']=='AWAITING_BACKEND_OBSERVATION' and not r['assembly_completion']
    assert raw.value['gripper_status']==0 and raw.value['posx'][2]==p['clearance_z_mm']
    assert any(e=='PRESS_SESSION' for e,d in events)
    if case=='05':assert r['human_completion_signal_received']


@pytest.mark.parametrize('case,stage',[('03','HUMAN_ASSEMBLY_RECEIVE'),('04','HUMAN_READY'),('05','HUMAN_HOLD_READY')])
@pytest.mark.parametrize('loss',['missing','wrong_shape','stale','duplicate','too_short','duplicate_source'])
def test_missing_or_invalid_signal_keeps_grip_above_target(case,stage,loss):
    def change(row,s,raw):
        if loss=='missing':return None
        if loss=='wrong_shape':row.update(hands=[dict(pose='FIST')])
        if loss=='stale':row['received_monotonic_ns']=0
        if loss=='duplicate':row['received_monotonic_ns']=round(s.request['opened_monotonic_s']*1e9)+1
        if loss=='duplicate_source':row['source_ns']=1
        if loss=='too_short':row['held_ns']=399_999_999
        return row
    execute,raw,events,s,plan,p,_=trial(case,change)
    assert execute()['status']=='PAUSED_'+stage
    assert raw.value['gripper_status']==2 and raw.value['posx'][2]==p['clearance_z_mm']
    assert raw.grips==[(62.,40.),(40.,40.)]
    assert not any(e=='PRESS_SESSION' for e,d in events)


@pytest.mark.parametrize('field',['execution_id','source_epoch','plan_id','step_id','preview_request_id'])
def test_other_context_signal_never_opens(field):
    execute,raw,*_=trial(change=lambda row,s,r:dict(row,**{field:'OLD'}))
    with pytest.raises(RuntimeError,match='MISMATCH'):execute()
    assert raw.grips==[(62.,40.),(40.,40.)]


def test_receive_withdrawal_during_gripper_window_blocks_open():
    def change(row,s,raw):
        if s.owner=='GRIPPER':row.update(hands=[dict(pose='FIST')])
        return row
    execute,raw,*_=trial(change=change)
    assert execute()['status']=='PAUSED_HUMAN_ASSEMBLY_RECEIVE'
    assert raw.grips==[(62.,40.),(40.,40.)]


@pytest.mark.parametrize('loss',['unknown','missing','multiple','no_frame'])
def test_brief_post_acceptance_recognition_loss_waits_for_fresh_open_then_opens(loss):
    lost=[False]
    def change(row,s,raw):
        if s.owner=='GRIPPER':
            row.update(held_ns=0,continuity_estimate=False,candidate_event=None)
            if not lost[0]:
                lost[0]=True
                if loss=='no_frame':
                    s.clock.sleep(.31)
                    return None
                row['hands']=({'unknown':[dict(pose='UNKNOWN')],'missing':[],
                    'multiple':[dict(pose='OPEN_HAND'),dict(pose='UNKNOWN')]}[loss])
        return row
    execute,raw,events,*_=trial(change=change)
    assert execute()['human_completion_signal_received']
    assert raw.grips[-1]==(62.4,40.)
    assert any(e=='HUMAN_RECEIVING_CUE_REACQUIRED' for e,d in events)


@pytest.mark.parametrize('loss',['unknown','missing','no_frame'])
def test_persistent_post_acceptance_loss_pauses_holding_without_open_or_error(loss):
    def change(row,s,raw):
        if s.owner=='GRIPPER':
            if loss=='no_frame':return None
            row['hands']=[dict(pose='UNKNOWN')] if loss=='unknown' else []
        return row
    execute,raw,events,s,*_=trial(change=change)
    r=execute()
    assert r['status']=='PAUSED_HUMAN_ASSEMBLY_RECEIVE' and raw.value['gripper_status']==2
    assert r['recoverable_interruption'] and r['interruption_scope']=='HUMAN_RECEIVE_STAGE'
    assert r['completed_physical_actions_preserved'] and r['resume_phase']=='human-wait'
    assert not r['gripper_open_command_sent'] and not r['assembly_completion']
    assert raw.grips==[(62.,40.),(40.,40.)] and s.request is None
    assert not any(e in ('STEP_ERROR','SINGLE_WRITER_GRIPPER') and
        (e=='STEP_ERROR' or d.get('width_mm')==62.4) for e,d in events)


def test_palm_cannot_report_manual_assembly_completion():
    def change(row,s,raw):
        if s.request['kind']=='HUMAN_ASSEMBLY_ACK':row.update(hands=[dict(pose='OPEN_HAND')])
        return row
    execute,raw,events,*_=trial(change=change)
    r=execute();assert r['status']=='HUMAN_ACK_TIMEOUT_CONTINUE'
    assert raw.value['gripper_status']==0 and not r['assembly_completion']
    assert not r['human_completion_signal_received'] and not r['current_update']
    assert r['advance_to_next_step'] and r['human_assembly_observation_pending']
    assert not any(e in ('STEP_ERROR','SINGLE_WRITER_STOP') for e,d in events)


def test_ack_only_timeout_preserves_release_and_requests_next_step_without_commands():
    execute,raw,events,s,plan,p,hmi=trial(change=lambda *a:None)
    plan['settings']['turn_base_z_deg']=0.
    s.value.update(automatic_start_pose=plan['settings']['reference_pose'][:2]+[p['clearance_z_mm']]+plan['settings']['pickup_pose'][3:],
        automatic_stage_checks=dict(enabled=True,review_ref='SYNTHETIC_ACK',
            block=deepcopy(plan['block']),release_after_contact_stop=True))
    r=execute('human-ack')
    assert r['status']=='HUMAN_ACK_TIMEOUT_CONTINUE' and r['advance_to_next_step']
    assert not raw.moves and not raw.grips and not raw.blends
    assert not r['human_completion_signal_received'] and not r['assembly_completion']
    assert s.request is None and not s.cancelled


def test_ack_timeout_executes_bound_independent_next_pickup():
    from app.human_step_continuation import execute_next_pickup
    execute,raw,events,s,plan,p,hmi=trial(change=lambda *a:None)
    raw.value.update(gripper_status=0,gripper_width_mm=64.2)
    plan['settings']['turn_base_z_deg']=0.
    s.value.update(automatic_start_pose=plan['settings']['reference_pose'][:2]+[p['clearance_z_mm']]+plan['settings']['pickup_pose'][3:],
        automatic_stage_checks=dict(enabled=True,review_ref='SYNTHETIC_ACK',
            block=deepcopy(plan['block']),release_after_contact_stop=True))
    r=execute('human-ack')
    next_plan=deepcopy(plan);next_plan.update(step_id='S02',key=plan['key'].replace('/S01','/S02'))
    next_plan['settings']=deepcopy(plan['settings'])
    next_plan['settings']['pickup_pose'][0]-=64.
    next_plan['settings']['turn_base_z_deg']=0.
    next_plan['settings']['pickup_start_open_range_mm']=[47.,110.]
    sv=session_fixture(next_plan);sv.update(expires_unix_s=1000.,allowed_trial_phase='pickup',
        previous_step=dict(execution_id=s.value['execution_id'],plan_id=plan['plan_id'],step_id=plan['step_id'],key=plan['key']),
        requires_confirmed_previous_step=False,required_previous_step_observations=[],
        human_step_gestures_review_ref='SYNTHETIC',
        automatic_stage_checks=dict(enabled=True,review_ref='SYNTHETIC_NEXT',
            block=deepcopy(next_plan['block']),release_after_contact_stop=True))
    ns=ControlSession(sv,next_plan,lambda e,d:events.append((e,deepcopy(d))),clock=s.clock,wall=lambda:100.)
    result=execute_next_pickup(raw,s,plan,r,ns,CONNECTION,next_plan,p,
        lambda *a:pytest.fail('No HMI'),lambda e,d:events.append((e,deepcopy(d))),clock=s.clock,sleep=s.clock.sleep)
    assert result['status']=='PAUSED_PICKUP_COMPLETE_HOLDING'
    assert raw.value['gripper_status']==2 and raw.value['posx']==next_plan['settings']['pickup_pose']
    assert not result['assembly_completion'] and result['previous_assembly_observation_pending']
    assert any(e=='NEXT_STEP_PICKUP_STARTED' for e,d in events)


@pytest.mark.parametrize('change', ['same_execution','wrong_parent','dependent_step'])
def test_unconfirmed_assembly_cannot_enable_unbound_or_dependent_next_pickup(change):
    from app.human_step_continuation import validate_next_pickup
    _,_,_,s,plan,_,_=trial()
    np=deepcopy(plan);np['step_id']='S02'
    nv=deepcopy(s.value);nv.update(execution_id='NEXT',allowed_trial_phase='pickup',
        previous_step=dict(execution_id=s.value['execution_id'],plan_id=plan['plan_id'],step_id=plan['step_id'],key=plan['key']),
        requires_confirmed_previous_step=False,required_previous_step_observations=[])
    if change=='same_execution':nv['execution_id']=s.value['execution_id']
    if change=='wrong_parent':nv['previous_step']['step_id']='OTHER'
    if change=='dependent_step':nv['required_previous_step_observations']=[plan['key']]
    with pytest.raises(ValueError,match='INDEPENDENT_NEXT_PICKUP'):
        validate_next_pickup(plan,s.value,np,nv)


@pytest.mark.parametrize('noise',['drift','velocity'])
def test_small_wait_change_renews_stop_window_without_repeating_physical_actions(noise):
    changed=[False];pending=[False]
    def change(row,s,raw):
        if s.request['kind']=='RECEIVE' and not changed[0]:
            changed[0]=True
            if noise=='drift':raw.value['posx'][0]+=.06
            else:pending[0]=True
        return row
    execute,raw,events,*_=trial(change=change)
    sample=raw.sample
    def noisy_sample():
        value=sample()
        if pending[0]:
            pending[0]=False;value['velx'][0]=.02
        return value
    raw.sample=noisy_sample
    assert execute()['human_completion_signal_received']
    assert raw.grips==[(62.,40.),(40.,40.),(62.4,40.)]
    names=[e for e,d in events]
    assert names.index('HUMAN_WAIT_STABILITY_RECHECK')<names.index('HUMAN_WAIT_STABILITY_RECONFIRMED')


@pytest.mark.parametrize('fault',['motion','target','orientation'])
def test_actual_human_wait_motion_or_target_departure_is_logged_and_never_opens(fault):
    def change(row,s,raw):
        if s.request['kind']=='RECEIVE':
            if fault=='motion':raw.value['motion_status']=2
            elif fault=='target':raw.value['posx'][0]+=2.
            else:raw.value['posx'][4]+=2.
        return row
    execute,raw,events,*_=trial(change=change)
    with pytest.raises(RuntimeError,match='NOT_STILL_ABOVE_TARGET'):execute()
    assert raw.grips==[(62.,40.),(40.,40.)]
    assert any(e=='HUMAN_WAIT_REJECTED' and d['reasons'] for e,d in events)


@pytest.mark.parametrize('start',['target','near_place'])
def test_human_transport_blends_through_place_board_both_directions(start):
    execute,raw,events,s,plan,p,_=trial()
    p['transport_blending']=dict(reviewed=True,radius_mm=15.)
    plan['settings']['turn_base_z_deg']=0.
    raw.value['posx'][3:]=plan['settings']['pickup_pose'][3:]
    if start=='target':raw.value['posx'][:2]=plan['settings']['reference_pose'][:2]
    assert execute()['human_completion_signal_received']
    assert [len(batch['targets']) for batch in raw.blends]==[4 if start=='target' else 3,4]
    if start=='target':assert raw.blends[0]['targets'][0][:2]==p['place_pose'][:2]
    assert raw.blends[1]['targets'][-1][:2]==plan['settings']['reference_pose'][:2]
    assert not any(e=='STEP_MOVE' and d['label']=='TARGET_HIGH_HUMAN_WAIT' for e,d in events)
    if start=='target':assert not any(e=='STEP_MOVE' and d['label']=='PLACE_BOARD_EMPTY' for e,d in events)


def test_pickup_rate_is_independent_of_robot_contact_rate():
    execute,raw,events,s,plan,p,_=trial('04')
    p.update(pickup_descent_velocity=12.,pickup_descent_acceleration=6.)
    assert execute()['status']=='AWAITING_BACKEND_OBSERVATION'
    pickup=[d for e,d in events if e=='MOVE_REQUEST' and d.get('target')==plan['settings']['pickup_pose']]
    assert pickup and pickup[-1]['velocity']==[12.,12.] and pickup[-1]['acceleration']==[6.,6.]
    endpoints=[d['travel_endpoint_posx'] for e,d in events if e=='PRESS_SESSION']
    press_moves=[d for e,d in events if e=='MOVE_REQUEST' and d.get('segment')=='DESCENT' and
                 d.get('target') in endpoints]
    assert press_moves and all(d['velocity']==[p['descent_velocity']]*2 and
        d['acceleration']==[p['descent_acceleration']]*2 for d in press_moves)


@pytest.mark.parametrize('failure',['near','not_reviewed','live','mixed_automatic','contact_bypass'])
def test_human_policy_does_not_allow_near_wait_or_bypass(failure):
    _,_,_,s,plan,p,_=trial('04')
    if failure=='near':plan['settings']['human_step_gestures']['wait_z_mm']=plan['settings']['reference_pose'][2]+20.1
    if failure=='not_reviewed':s.value['human_step_gestures_review_ref']=''
    if failure=='live':s.value['provenance']='LIVE_D_RUNTIME'
    if failure=='mixed_automatic':s.value['automatic_stage_checks']={'enabled':True}
    with pytest.raises(ValueError):
        if failure=='contact_bypass':validate_physical(plan,p,'contact')
        else:validate_policy(plan,p,s.value)
