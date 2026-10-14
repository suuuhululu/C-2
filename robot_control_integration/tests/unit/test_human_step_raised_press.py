from copy import deepcopy
import pytest
from app.human_step_raised_press import KINDS,adapt_human_step,square_last_block
from app.assembly_step_bridge import trial_footprint
from app import assembly_step_runner as runner


def fixture(color,kind,orientation,support=False):
    square=square_last_block(color,kind,orientation);block=square['target'];abc=[0.,180.,0.]
    settings=dict(pickup_pose=[-300,100,50,*abc],reference_pose=[400,80,40,*abc],pickup_width_mm=35.,release_width_mm=62.)
    plan=dict(key='square/S4',plan_id='square',step_id='S4',mode='HUMAN_ASSEMBLY',assistance_kind='MANUAL_ASSEMBLY_AND_HOLD' if support else 'MANUAL_ASSEMBLY',human_actions=['MANUAL_ASSEMBLY'],block=block,settings=settings,trial_footprint=trial_footprint(block),source_execution_allowed=False)
    profile=dict(steps={plan['key']:settings},clearance_z_mm=150.,approach_offset_mm=20.,near_contact_offset_mm=1.,force_stop_n=45.,max_press_travel_mm=5.,transfer_velocity=12.,transfer_acceleration=2.,descent_velocity=2.,descent_acceleration=1.,gripper_force_n=35.)
    measured=dict(key=plan['key'],block=block,reason='GRIPPER_COLLISION',pad_bottom_from_block_bottom_mm=15.,body_height_mm=19.6,human_support_required=support,grasp_stability_verified=True,insertion_sweep_verified=True,release_sweep_verified=True,press_sweep_verified=True,landing_support_verified=True,measurement_ref='TEST_FIXTURE_NOT_REAL',pickup_pose=[-300,100,55,*abc],landing_pose=[400,80,45,*abc],pad_contact_pose=[400,80,60,*abc],pickup_width_mm=35.,release_width_mm=62.,press_width_mm=0.)
    return plan,profile,measured,square

@pytest.mark.parametrize('color,kind',sorted(KINDS))
@pytest.mark.parametrize('orientation',[0,90])
@pytest.mark.parametrize('support',[False,True])
def test_every_block_and_direction_in_last_square_step(color,kind,orientation,support):
    plan,profile,m,square=fixture(color,kind,orientation,support);original=deepcopy((plan,profile))
    out,p=adapt_human_step(plan,profile,m)
    assert (plan,profile)==original
    assert out['mode']=='ROBOT_RELEASE_PRESS'
    assert out['assistance_kind']==('HOLD' if support else 'NONE')
    assert out['settings']['pickup_pose'][2]==55 and out['settings']['reference_pose'][2]==45
    assert out['source_mode']=='HUMAN_ASSEMBLY' and not out['source_execution_allowed']
    assert len(square['current'])==3 and square['target']['orientation_deg']==orientation
    occupied=[]
    for b in square['current']+[square['target']]:
        a,c=map(int,b['brick_type'].split('x')[:2])
        if b['orientation_deg']==90:a,c=c,a
        cells={(b['x']+i,b['y']+j) for i in range(a) for j in range(c)}
        assert not any(cells & prev for prev in occupied)
        occupied.append(cells)

@pytest.mark.parametrize('field',['insertion_sweep_verified','release_sweep_verified','press_sweep_verified','landing_support_verified','grasp_stability_verified'])
def test_unresolved_clearance_remains_human(field):
    plan,p,m,_=fixture('blue','2x3x1',90);m[field]=False
    with pytest.raises(ValueError,match='CLEARANCE_REQUIRED'):adapt_human_step(plan,p,m)
    assert plan['mode']=='HUMAN_ASSEMBLY'


def test_support_cannot_be_removed_and_five_mm_is_not_raised():
    plan,p,m,_=fixture('red','1x2x1',0,True);m['human_support_required']=False
    with pytest.raises(ValueError,match='SUPPORT'):adapt_human_step(plan,p,m)
    m['human_support_required']=True;m['pad_bottom_from_block_bottom_mm']=5
    with pytest.raises(ValueError,match='15MM'):adapt_human_step(plan,p,m)


def test_existing_runner_releases_then_vertical_retreat_then_press(monkeypatch):
    plan,p,m,_=fixture('yellow','2x2x1',0);plan,p=adapt_human_step(plan,p,m)
    d=runner.StepReplayDriver(plan['settings']['reference_pose'],reaction_force_n=45.)
    d.value.update(posx=[400.,80.,65.,0.,180.,0.],gripper_status=2,gripper_width_mm=40.6)
    def move(driver,connection,target,*a,**kw):driver.value['posx']=target.copy()
    monkeypatch.setattr(runner,'run',move)
    monkeypatch.setattr(runner,'press',lambda *a,**kw:dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'))
    events=[]
    r=runner.run_step(d,dict(tcp='GripperDA_v4',tool='ToolWeight0'),plan,p,lambda *_:True,lambda e,x:events.append((e,x)),phase='contact',sleep=lambda _:None)
    labels=[x['label'] for e,x in events if e=='STEP_MOVE']
    assert labels.index('RELEASE_POSITION')<labels.index('RAISED_EMPTY_VERTICAL_RETREAT')<labels.index('PRESS_TOOL_LOWER')
    assert 'PRESS_TOOL_APPROACH' not in labels
    vertical=[x['target'] for e,x in events if e=='STEP_MOVE' and x['label'] in ('RAISED_EMPTY_VERTICAL_RETREAT','PRESS_TOOL_LOWER')]
    assert all(t[:2]==[400.,80.] and t[3:]==[0.,180.,0.] for t in vertical)
    assert vertical[0][2]>vertical[1][2]
    assert p['force_stop_n']==45.
    assert not r['assembly_completion']


def test_press_uses_landing_xy_and45_regardless_of_old_press_xy():
    plan,p,m,_=fixture('blue','2x3x1',90)
    p['force_stop_n']=35.
    m['pad_contact_pose']=[999,999,60,10,20,30]
    out,p=adapt_human_step(plan,p,m)
    assert out['settings']['press_start_pose']==[400,80,61,0.,180.,0.]
    assert p['force_stop_n']==45. and p['force_control_target_n'] is None
