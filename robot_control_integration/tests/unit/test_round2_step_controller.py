"""Three Round2 branches on explicit TEST geometry; no device or physical claims."""
from copy import deepcopy
import pytest
from tests.unit.test_human_step_raised_press import fixture
from app.human_step_raised_press import KINDS
from app.round2_step_controller import prepare_round2_step,run_round2_step
from app.round2_grasp_offset_trial import apply_step_offset_trial,apply_held_offset_trial
from app import assembly_step_runner as runner
from app.control_driver import ControlledDriver
from app.control_session import ControlSession
from app.assembly_step_bridge import validate_physical
from scripts.robot_control_trial import test_session as make_session
from tests.unit.test_control_session import Clock
from tests.unit.test_assembly_strategy import source_case
from app.assembly_step_bridge import build_plan


@pytest.mark.parametrize('assistance',['NONE','HOLD','PRESS','PRESS_AND_HOLD'])
def test_a_release_press_strategy_uses_d_robot_branch_without_changing_source(assistance):
    step,p=source_case(assistance);plan=build_plan(step,p);before=deepcopy((plan,p))
    prepared=prepare_round2_step(plan,p)
    candidate=prepared['execution_candidate']
    assert (plan,p)==before and prepared['source_plan']==plan
    assert prepared['branch']=='ROBOT_RELEASE_PRESS' and prepared['robot_complement_selected']
    assert candidate['mode']=='ROBOT_GRIP' and candidate['assistance_kind']==assistance
    assert candidate['human_actions']==step['action']['human_actions']
    assert candidate['source_action']==step['action'] and candidate['gripper']==step['action']['gripper']
    assert candidate['d_execution_strategy']=='RELEASE_PRESS' and candidate['round2_vertical_top_press']
    assert not prepared['assembly_completion'] and not prepared['current_update']


@pytest.mark.parametrize('force',[40.,45.])
def test_source_release_press_keeps_full_measured_pad_and_supplied_force(force):
    step,p=source_case('NONE');p['force_stop_n']=force
    plan=build_plan(step,p);before=deepcopy((plan,p))
    pad=[402.4,78.3,60.5,13.,176.,11.]
    prepared=prepare_round2_step(plan,p,dict(pad_contact_pose=pad,press_width_mm=4.))
    settings=prepared['execution_candidate']['settings']
    assert settings['release_pose']==plan['settings']['release_pose']
    assert settings['press_start_pose']==[*pad[:2],pad[2]+p['near_contact_offset_mm'],*pad[3:]]
    assert settings['press_approach_pose']==[*pad[:2],pad[2]+p['approach_offset_mm'],*pad[3:]]
    assert prepared['profile']['force_stop_n']==force and (plan,p)==before


def test_legacy_round2_keeps_existing45n_contact_policy():
    plan,p,m,_=fixture('yellow','2x2x1',0)
    plan.update(mode='ROBOT_GRIP',assistance_kind='NONE',human_actions=[])
    p['force_stop_n']=40.
    prepared=prepare_round2_step(plan,p,m)
    assert prepared['profile']['force_stop_n']==45. and p['force_stop_n']==40.


@pytest.mark.parametrize('color,kind',sorted(KINDS))
@pytest.mark.parametrize('orientation',[0,90])
@pytest.mark.parametrize('branch',['robot','support','human'])
def test_all_types_orientations_and_branches_keep_source(color,kind,orientation,branch):
    plan,p,m,_=fixture(color,kind,orientation,support=branch=='support')
    if branch=='robot':plan.update(mode='ROBOT_GRIP',assistance_kind='NONE',human_actions=[])
    before=deepcopy((plan,p))
    out=prepare_round2_step(plan,p,m)
    assert (plan,p)==before
    assert out['branch']==dict(robot='ROBOT_FASTENING',support='HUMAN_SUPPORT_PLACE_BOARD',human='HUMAN_FASTENING_ROBOT_COMPLEMENT')[branch]
    candidate=out['execution_candidate']
    if branch=='support':
        assert candidate['mode']=='HUMAN_ASSEMBLY'
        assert candidate['assistance_kind']=='MANUAL_ASSEMBLY_AND_HOLD'
    else:assert candidate['mode']=='ROBOT_RELEASE_PRESS'
    assert candidate['settings']['pickup_pose']==(m['pickup_pose'] if branch=='human' else plan['settings']['pickup_pose'])
    assert out['profile']['transfer_velocity']==120. and out['profile']['descent_velocity']==12.
    assert not out['assembly_completion'] and not out['physical_execution_ready']


def test_unresolved_interference_remains_human_and_support_never_removed():
    plan,p,m,_=fixture('red','1x2x1',90);m['insertion_sweep_verified']=False
    out=prepare_round2_step(plan,p,m)
    assert out['branch']=='HUMAN_FASTENING_FALLBACK'
    assert out['execution_candidate']['mode']=='HUMAN_ASSEMBLY'
    plan,p,m,_=fixture('red','1x2x1',90,support=True)
    out=prepare_round2_step(plan,p,None)
    assert out['branch']=='HUMAN_SUPPORT_PLACE_BOARD'


def test_user_motion_policy_overrides_defaults_and_original_profile_survives():
    plan,p,m,_=fixture('blue','2x3x1',90)
    p['round2_motion']=dict(transfer_velocity=80.,vertical_velocity=6.)
    out=prepare_round2_step(plan,p,m)
    assert out['profile']['transfer_velocity']==80. and out['profile']['descent_velocity']==6.
    assert p['transfer_velocity']==12.


@pytest.mark.parametrize('color,kind',sorted(KINDS))
@pytest.mark.parametrize('orientation',[0,90])
def test_user_plus10_changes_initial_pick_and_landing_not_empty_pad(color,kind,orientation):
    plan,p,m,_=fixture(color,kind,orientation)
    plan['settings']['release_pose']=plan['settings']['reference_pose'].copy()
    plan['settings']['press_start_pose']=m['pad_contact_pose'].copy()
    before=deepcopy(plan)
    out,_=apply_step_offset_trial(plan,p)
    assert out['settings']['pickup_pose'][2]==before['settings']['pickup_pose'][2]+10
    assert out['settings']['reference_pose'][2]==before['settings']['reference_pose'][2]+10
    assert out['settings']['release_pose'][2]==before['settings']['release_pose'][2]+10
    assert out['settings']['press_start_pose']==before['settings']['press_start_pose']
    assert not out['operator_raised_z_trial']['measured_15mm_relation_verified']
    assert plan==before


def test_held_plus10_preserves_empty_pad_top_contact_and_original_config():
    from scripts.held_corner_stud_trial import NATIVE,target_layer_approach
    import json
    c=target_layer_approach(json.loads((NATIVE/'settings/held_corner_stud_20261014/config.json').read_text()),1)
    before=deepcopy(c);out=apply_held_offset_trial(c)
    assert c==before
    assert out['blocks'][0]['pickup_pose'][2]==c['blocks'][0]['pickup_pose'][2]+10
    assert out.get('integrated_pad_contact_pose')==c.get('integrated_pad_contact_pose')


def test_empty_closed_pad_status2_is_used_for_lower_press_and_final_rise(monkeypatch):
    plan,p,m,_=fixture('yellow','2x2x1',0);m['press_width_mm']=4.
    prepared=prepare_round2_step(plan,p,m);plan=prepared['execution_candidate'];p=prepared['profile']
    p.update(supply_transit_xy_mm=[-300.,0.],body_bypass_xy_mm=[0.,-200.],place_pose=[400.,-150.,150.,0.,180.,0.])
    class Pads(runner.StepReplayDriver):
        def command_gripper(self,width,force):
            super().command_gripper(width,force)
            if width==4.:self.value.update(gripper_status=2,gripper_width_mm=9.2)
    d=Pads(plan['settings']['reference_pose']);d.value.update(posx=[400.,80.,65.,0.,180.,0.],gripper_status=2)
    def move(driver,connection,target,*a,**kw):driver.value['posx']=target.copy()
    monkeypatch.setattr(runner,'run',move)
    press_status=[]
    def press(*a,**kw):
        press_status.append(kw['required_gripper_status'])
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr(runner,'press',press)
    events=[]
    result=runner.run_step(d,dict(tcp='GripperDA_v4',tool='ToolWeight0'),plan,p,lambda *_:True,
        lambda e,x:events.append((e,x)),phase='assemble-held',start_zone='supply',sleep=lambda _:None)
    assert press_status==[2]
    lower=[x for e,x in events if e=='STEP_MOVE' and x['label']=='PRESS_TOOL_LOWER']
    assert lower[0]['gripper_status']==2
    assert [x for e,x in events if e=='STEP_MOVE'][-1]['gripper_status']==2
    assert not result['assembly_completion']


@pytest.mark.parametrize('color,kind',sorted(KINDS))
@pytest.mark.parametrize('orientation',[0,90])
def test_first_pickup_does_not_wait_for_later_surface_measurements(color,kind,orientation,monkeypatch):
    plan,p,m,_=fixture(color,kind,orientation)
    width=20. if kind=='1x2x1' else 40. if kind=='2x3x1' else 35.
    m['pickup_width_mm']=width
    p.update(supply_transit_xy_mm=[-300.,0.],body_bypass_xy_mm=[0.,-200.],place_pose=[400.,-150.,150.,0.,180.,0.])
    out=prepare_round2_step(plan,p,m)
    out['profile']['round2_supply_observation_pose']=[-350.,30.,200.,0.,180.,0.]
    d=runner.StepReplayDriver(out['execution_candidate']['settings']['reference_pose'],grasp_width_mm=width)
    observed=[]
    def pickup(plan,sample):
        observed.append(sample['posx'])
        return dict(status='VISION_GRASP_PLAN_FOR_REVIEW',policy='COORDINATE_FIRST_WITH_OPTIONAL_CENTER',
            candidate_tcp_mm_zyz_deg=plan['settings']['pickup_pose'].copy(),center_assist_applied=False,
            vision_attempted=True,recognized=False,fallback_reason='TEST_NO_DETECTION')
    result=run_round2_step(d,dict(tcp='GripperDA_v4',tool='ToolWeight0'),out,lambda *_:True,lambda *_:None,
        pickup_center=pickup,phase='pickup',start_zone='supply',sleep=lambda _:None)
    assert observed==[out['profile']['round2_supply_observation_pose']]
    assert d.value['posx']==m['pickup_pose']
    assert d.grips[-1][0]==width and d.value['gripper_status']==2
    assert result['status']=='PAUSED_PICKUP_COMPLETE_HOLDING'


def controlled_case():
    plan,p,m,_=fixture('yellow','2x2x1',0);plan['current_revision']=0
    p.update(supply_transit_xy_mm=[-300.,0.],body_bypass_xy_mm=[0.,-200.],
        place_pose=[400.,-150.,150.,0.,180.,0.])
    prepared=prepare_round2_step(plan,p,m);clock=Clock();events=[]
    session=ControlSession(make_session(prepared['execution_candidate']),prepared['execution_candidate'],
        lambda e,v:events.append((e,deepcopy(v))),clock=clock)
    raw=runner.StepReplayDriver(prepared['execution_candidate']['settings']['reference_pose'])
    driver=ControlledDriver(raw,session,dict(tcp='GripperDA_v4',tool='ToolWeight0'),clock=clock,sleep=clock.sleep)
    return prepared,raw,driver,session,clock,events


def no_center(plan,sample):
    return dict(status='VISION_GRASP_PLAN_FOR_REVIEW',policy='COORDINATE_FIRST_WITH_OPTIONAL_CENTER',
        candidate_tcp_mm_zyz_deg=deepcopy(plan['settings']['pickup_pose']),center_assist_applied=False)


@pytest.mark.parametrize('wrapped',[False,True])
def test_round2_controlled_pickup_uses_existing_requests_and_leases(wrapped):
    prepared,raw,driver,session,clock,events=controlled_case();requests=[]
    def confirm(kind,plan,sample):
        assert session.request['kind']==kind
        requests.append(kind);return True
    result=run_round2_step(driver if wrapped else raw,driver.connection,prepared,confirm,session.record,
        session=session,pickup_center=no_center,phase='pickup',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert result['status']=='PAUSED_PICKUP_COMPLETE_HOLDING' and session.execution_claimed
    assert requests==['START_PICKUP','PICKUP_ALIGNMENT','GRASP_CONFIRMED']
    assert {'WAIT','MOTION','GRIPPER'}=={v['owner'] for e,v in events if e=='ADAPTER_LEASE_APPLIED'}
    assert session.owner=='NONE' and session.lease is None and session.request is None


def test_explicit_round2_session_is_used_with_existing_controlled_raw():
    prepared,raw,driver,old_session,clock,_=controlled_case()
    plan=prepared['execution_candidate']
    session=ControlSession(make_session(plan),plan,old_session.record,clock=clock)
    def confirm(kind,plan,sample):
        assert session.request['kind']==kind
        return True
    result=run_round2_step(driver,driver.connection,prepared,confirm,session.record,session=session,
        pickup_center=no_center,phase='pickup',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert result['execution_id']==session.value['execution_id'] and session.execution_claimed
    assert not old_session.execution_claimed and raw.grips


def test_round2_alignment_is_forwarded_through_controlled_execution(monkeypatch):
    prepared,raw,driver,session,clock,events=controlled_case();aligned=[]
    raw.reference[2]=-100.
    raw.value.update(posx=prepared['execution_candidate']['settings']['pickup_pose'].copy(),
        gripper_status=2,gripper_width_mm=40.6)
    def align(driver,plan,profile,provider,move,emit):
        aligned.append(provider)
        return dict(status='SURFACE_ALIGNMENT_CONVERGED',candidate=dict(
            landing_pose=deepcopy(plan['settings']['reference_pose']),pad_contact_z_mm=60.))
    def press(driver,connection,emit,**kwargs):
        emit('PRESS_SESSION',{});emit('PRESS_RESULT',dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'))
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr('app.round2_alignment.automatic_surface_alignment',align)
    monkeypatch.setattr(runner,'press',press)
    provider=lambda *_:None
    result=run_round2_step(driver,driver.connection,prepared,lambda *_:True,session.record,pickup_center=no_center,
        assembly_alignment=provider,phase='assemble-held',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert aligned==[provider] and result['status']=='AWAITING_BACKEND_OBSERVATION'
    assert any(e=='ADAPTER_LEASE_APPLIED' and v['owner']=='CONTACT' for e,v in events)
    assert not result['assembly_completion'] and not result['current_update']


def test_round2_held_mode_keeps_original_none_assistance_requirement():
    prepared,_,_,_,_,_=controlled_case();plan=prepared['execution_candidate'];p=prepared['profile']
    p.update(profile_id='D_UNIT_CASE',physical_route_reviewed=True)
    plan['settings']['physical_reference_reviewed']=True
    validate_physical(plan,p,'assemble-held')
    plan['assistance_kind']='HOLD'
    with pytest.raises(ValueError,match='HELD_ASSEMBLY_REQUIRES_UNASSISTED_ROBOT_GRIP'):
        validate_physical(plan,p,'assemble-held')


def test_round2_support_drops_native_press_but_keeps_source_profile():
    plan,p,m,_=fixture('blue','2x3x1',90,support=True)
    p['native_press']=dict(enabled=True,force_n=35.,review_ref='TEST_ONLY')
    original=deepcopy(p);prepared=prepare_round2_step(plan,p,m)
    assert 'native_press' not in prepared['profile'] and p==original


def test_two_round2_steps_continue_from_closed_empty_pad_context(monkeypatch):
    prepared,_,first_driver,first_session,clock,events=controlled_case()
    class EmptyPads(runner.StepReplayDriver):
        def command_gripper(self,width,force):
            super().command_gripper(width,force)
            if width==4.:self.value.update(gripper_status=2,gripper_width_mm=9.2)
    prepared['execution_candidate']['settings']['press_width_mm']=4.
    raw=EmptyPads([400.,80.,-100.,0.,180.,0.])
    first_driver=ControlledDriver(raw,first_session,first_driver.connection,clock=clock,sleep=clock.sleep)
    def align(driver,plan,profile,provider,move,emit):
        return dict(status='SURFACE_ALIGNMENT_CONVERGED',candidate=dict(
            landing_pose=deepcopy(plan['settings']['reference_pose']),pad_contact_z_mm=60.))
    def press(driver,connection,emit,**kwargs):
        emit('PRESS_SESSION',{});emit('PRESS_RESULT',dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'))
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr('app.round2_alignment.automatic_surface_alignment',align)
    monkeypatch.setattr(runner,'press',press)
    first=run_round2_step(first_driver,first_driver.connection,prepared,lambda *_:True,first_session.record,
        pickup_center=no_center,assembly_alignment=lambda *_:None,phase='full',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert first['status']=='AWAITING_BACKEND_OBSERVATION' and raw.value['gripper_status']==2
    plan,p,m,_=fixture('yellow','2x2x1',0)
    plan.update(key='square/S5',step_id='S5',current_revision=1)
    plan['block']['x']+=4;plan['settings']['pickup_pose'][0]-=25;plan['settings']['reference_pose'][0]+=76
    m.update(key=plan['key'],press_width_mm=4.)
    m['pickup_pose'][0]-=25;m['landing_pose'][0]+=76;m['pad_contact_pose'][0]+=76
    p.update(supply_transit_xy_mm=[-300.,0.],body_bypass_xy_mm=[0.,-200.],place_pose=[400.,-150.,150.,0.,180.,0.],
        steps={plan['key']:deepcopy(plan['settings'])})
    second=prepare_round2_step(plan,p,m)
    session=ControlSession(make_session(second['execution_candidate']),second['execution_candidate'],first_session.record,clock=clock)
    driver=ControlledDriver(raw,session,first_driver.connection,clock=clock,sleep=clock.sleep)
    before=len(raw.grips)
    result=run_round2_step(driver,driver.connection,second,lambda *_:True,session.record,
        pickup_center=no_center,assembly_alignment=lambda *_:None,phase='full',start_zone='assembly',clock=clock,sleep=clock.sleep)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION'
    assert raw.grips[before][0]==second['execution_candidate']['settings']['release_width_mm']
    assert session.owner=='NONE' and session.lease is None and session.request is None
    assert not result['assembly_completion'] and not result['current_update']
