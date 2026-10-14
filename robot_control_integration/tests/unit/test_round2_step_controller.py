"""Three Round2 branches on explicit TEST geometry; no device or physical claims."""
from copy import deepcopy
import pytest
from tests.unit.test_human_step_raised_press import fixture
from app.human_step_raised_press import KINDS
from app.round2_step_controller import prepare_round2_step,run_round2_step
from app.round2_grasp_offset_trial import apply_step_offset_trial,apply_held_offset_trial
from app import assembly_step_runner as runner


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
