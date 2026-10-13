from copy import deepcopy
import pytest
from app.assembly_step_runner import assembly_target_pose,rotate_base_z_pose
from app.integration_runtime import StepRuntime
from scripts.robot_integration_fixture import document


def test_actual_operation_and_resume_use_taught_assembly_pose_without_driver():
    d=document();settings=next(iter(d['d_profile']['steps'].values()))
    target=[136.16897583007812,-179.09410095214844,-132.9127197265625]
    settings['assembly_tcp_zyz_deg']=target
    expected=settings['reference_pose'][:3]+target
    assert assembly_target_pose(settings)==expected
    rt=StepRuntime(None,None,lambda *a:None)
    plan=dict(settings=settings,mode='ROBOT_GRIP',assistance_kind='NONE')
    ops=rt.make_operations(plan,d['d_profile'],'assembly')
    pre=next(v[1] for op,v in ops if op=='move' and v[0]=='PRE_CONTACT')
    assert pre==expected[:2]+[expected[2]+d['d_profile']['approach_offset_mm']]+target
    rt.plan=plan;rt.profile=d['d_profile'];rt.pending='contact';rt.state='STOPPED'
    rt.stopped_sample=dict(posx=pre,gripper_status=2)
    assert rt.can_resume()
    rt.stopped_sample['posx']=pre[:3]+rotate_base_z_pose(settings['pickup_pose'],settings['turn_base_z_deg'])[3:]
    assert not rt.can_resume()


def test_old_settings_keep_pickup_plus_turn():
    d=document();s=next(iter(d['d_profile']['steps'].values()))
    assert assembly_target_pose(s)==s['reference_pose'][:3]+rotate_base_z_pose(s['pickup_pose'],s['turn_base_z_deg'])[3:]


@pytest.mark.parametrize('value',[[1.,2.],[1.,2.,float('nan')],'not-a-pose'])
def test_invalid_explicit_orientation_does_not_fall_back(value):
    d=document();s=next(iter(d['d_profile']['steps'].values()));s['assembly_tcp_zyz_deg']=value
    with pytest.raises(ValueError):assembly_target_pose(s)
