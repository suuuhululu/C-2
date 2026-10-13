"""Actual full workflow with native pressure and release; synthetic feedback only."""
import pytest
from app.assembly_step_runner import StepReplayDriver
from app.control_driver import execute_step
from test_automatic_stage_trial import automatic,CONNECTION


def setup_native():
    s,plan,p,events,clock=automatic()
    p['native_press']=dict(enabled=True,force_n=35.,hold_s=3.,seek_above_reference_mm=6.68375129699707,
        review_ref='USER_DIRECT_35N_ONSITE_POLICY')
    raw=StepReplayDriver(plan['settings']['reference_pose'])
    return s,plan,p,events,clock,raw


def run(values):
    s,plan,p,events,clock,raw=values
    return execute_step(raw,s,CONNECTION,plan,p,lambda *_:pytest.fail('No HMI'),s.record,
        phase='full',clock=clock,sleep=clock.sleep)


def test_full_pick_move_native35_release48_retreat_uses_single_writer():
    values=setup_native();s,plan,p,events,clock,raw=values
    result=run(values)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION'
    assert raw.native_force_requests==[dict(force_n=35.,relative=False)]
    assert raw.grips[-1][0]==48. and raw.value['gripper_status']==0
    assert raw.value['posx'][2]>=p['clearance_z_mm'] and not raw.native_compliance
    assert result['contact_evidence']['status']=='NATIVE_FORCE_LIMIT_STOP_VERIFIED'
    assert result['contact_evidence']['force_released'] and result['contact_evidence']['compliance_released']
    assert not any(result[k] for k in ('assembly_completion','current_update','backend_current_committed'))
    assert sum(e=='PRESS_SESSION' for e,_ in events)==1
    assert s.owner=='NONE' and s.lease is None


@pytest.mark.parametrize('failure',['force_ack','cleanup','no_load'])
def test_native_failure_keeps_block_held_and_never_opens_after_failure(failure):
    values=setup_native();raw=values[-1]
    if failure=='force_ack':
        raw.set_downward_force=lambda *a,**k:(_ for _ in ()).throw(TimeoutError('ACK_LOST'))
    elif failure=='cleanup':
        raw.release_compliance=lambda:(_ for _ in ()).throw(RuntimeError('CLEANUP_FAILED'))
    else:
        raw.set_downward_force=lambda *a,**k:None
    with pytest.raises(RuntimeError,match='NATIVE_PRESS_NOT_VERIFIED'):run(values)
    assert raw.value['gripper_status']==2 and len(raw.grips)==2
    assert raw.stops


@pytest.mark.parametrize('change',[dict(force_n=36.),dict(review_ref=''),dict(hold_s=0)])
def test_bad_native_policy_blocks_before_pickup(change):
    values=setup_native();values[2]['native_press'].update(change)
    with pytest.raises(ValueError):run(values)
    assert not values[-1].moves and not values[-1].grips


def test_cleanup_releases_compliance_before_verifying_loaded_creep_has_stopped():
    values=setup_native();raw=values[-1];original=raw.sample
    def sample():
        s=original()
        if getattr(raw,'native_compliance',False):s['velx'][2]=-.02
        return s
    raw.sample=sample
    result=run(values)
    assert result['contact_evidence']['stop']['stillness_verified']
    assert not raw.native_compliance and raw.grips[-1][0]==48.


@pytest.mark.parametrize('kind,turn',[('2x2x1',0),('2x3x1',0),('2x3x1',90),('1x2x1',0),('1x2x1',90)])
def test_supported_trial_sizes_keep_native35_and_release_cleanup(kind,turn):
    from scripts.robot_integration_fixture import document
    from app.integration_runtime import StepRuntime
    from test_integration_runtime import Clock
    d=document(brick_type=kind,color='red' if kind=='1x2x1' else 'blue',angle=turn)
    s=d['d_profile']['steps']['fake/S01'];s.update(turn_base_z_deg=turn,pickup_open_width_mm=55.,
        pickup_width_mm=35.,release_width_mm=48.,pickup_start_open_range_mm=[44.1,110.],
        release_feedback_range_mm=[44.1,110.])
    d['d_profile']['native_press']=dict(enabled=True,force_n=35.,hold_s=3.,
        seek_above_reference_mm=6.68375129699707,review_ref='SYNTHETIC_NEW_SIZES')
    raw=StepReplayDriver(s['reference_pose']);clock=Clock();events=[]
    rt=StepRuntime(raw,CONNECTION,lambda e,v:events.append((e,v)),clock=clock,sleep=clock.sleep)
    rt.start(d['step'],d['d_profile'],d['session'])
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert raw.native_force_requests==[dict(force_n=35.,relative=False)]
    assert raw.grips[-1][0]==48. and not raw.native_compliance
    assert rt.contact['force_released'] and rt.contact['compliance_released']


def position_reaction(values,*,z_offset=.2,wrench=(0.,0.,35.16156)):
    raw=values[-1];values[2]['native_press']['alignment_trial']=True
    move=raw.move_line_async
    def downward(target,*args,**kwargs):
        pressing=raw.value['gripper_status']==2 and target[2]<raw.reference[2]
        move(target,*args,**kwargs)
        if pressing:
            raw.value['wrench'][:3]=list(wrench)
            if sum(v*v for v in wrench)>=35.**2:raw.value['posx'][2]=raw.reference[2]+z_offset
            else:raw.value['posx']=target.copy()
    raw.move_line_async=downward


@pytest.mark.parametrize('z_offset',[-3.,-.501,.2,1.5,10.,10.001])
def test_alignment_trial_reports_height_but_opens_after_verified_reaction_stop(z_offset):
    values=setup_native();s,plan,p,events,clock,raw=values
    position_reaction(values,z_offset=z_offset)
    result=run(values)
    evidence=result['contact_evidence']
    assert evidence['seating_goal_verified'] is (z_offset<=10.)
    assert evidence['release_after_verified_reaction_stop']
    assert evidence['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert evidence['native_force_commands']==0 and evidence['force_control_target_n'] is None
    assert raw.grips[-1][0]==48.
    assert getattr(raw,'native_force_requests',[])==[] and not getattr(raw,'native_compliance',False)


@pytest.mark.parametrize('final_fz',[34.49,34.99])
def test_alignment_requires_measured_35n_even_inside_user_height(final_fz):
    values=setup_native();raw=values[-1]
    position_reaction(values,wrench=(0.,0.,final_fz))
    with pytest.raises(RuntimeError,match='PRESS_THRESHOLD_NOT_REACHED'):run(values)
    assert raw.value['gripper_status']==2 and len(raw.grips)==2
    assert not getattr(raw,'native_compliance',False)


def test_logged_s03_total_force_35n_accepts_completed_press_and_cleanup():
    values=setup_native();raw=values[-1]
    position_reaction(values,wrench=(-3.914994955062866,-.17576441168785095,34.932762145996094))
    result=run(values)
    assert result['contact_evidence']['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert result['contact_evidence']['threshold_force_norm_n']==pytest.approx(35.15189823857769)
    assert result['contact_evidence']['stop']['stillness_verified'] and raw.stops>=1
    assert getattr(raw,'native_force_requests',[])==[]
    assert raw.grips[-1][0]==48. and not getattr(raw,'native_compliance',False)


def test_total_force_below_35n_keeps_grasp_even_with_lateral_force():
    values=setup_native();raw=values[-1]
    position_reaction(values,wrench=(3.,.1,34.))
    with pytest.raises(RuntimeError,match='PRESS_THRESHOLD_NOT_REACHED'):run(values)
    assert raw.value['gripper_status']==2 and len(raw.grips)==2
    assert not getattr(raw,'native_compliance',False)


def test_current_trial_uses_one_descent_and_no_force_targets_or_xy_search():
    values=setup_native();s,plan,p,events,clock,raw=values
    position_reaction(values)
    result=run(values)
    assert result['contact_evidence']['seating_goal_verified']
    assert getattr(raw,'native_force_requests',[])==[]
    assert not any(e in ('CONTACT_OBSERVATION','CONTACT_MOVE_REQUEST','PRESSURE_STAGE') for e,_ in events)
    sessions=[v for e,v in events if e=='PRESS_SESSION']
    assert len(sessions)==1 and sessions[0]['press_control']=='POSITION_DESCENT_REACTION_STOP'
    assert sessions[0]['force_control_target_n'] is None
    assert sessions[0]['travel_endpoint_posx'][2]==pytest.approx(plan['settings']['reference_pose'][2]+
        p['near_contact_offset_mm']-p['max_press_travel_mm'])
    assert raw.grips[-1][0]==48. and not getattr(raw,'native_compliance',False)
