from copy import deepcopy
import json
import pytest
from scripts import held_corner_stud_trial as held
from scripts import supply_pick_release_trial as supply


def config():
    return json.loads((held.NATIVE/'settings/held_corner_stud_20261014/config.json').read_text())


def test_loaded_route_preserves_grasp_orientation_and_stays_at_existing_height():
    c=config();start=c['blocks'][0]['pickup_pose']
    route=held.loaded_route(c,start)
    assert [label for label,_ in route]==['HELD_VERTICAL_LIFT','HELD_SUPPLY','HELD_BODY_BYPASS','HELD_PLACE','ASSEMBLY_TARGET_HIGH']
    assert route[0][1][:2]==start[:2]
    assert all(target[2]==c['pickup_clearance_z_mm'] and target[3:]==start[3:] for _,target in route)
    assert route[-1][1][:2]==c['assembly_target_xy']


def test_rejects_start_above_transport_without_implicit_loaded_descent():
    c=config();start=c['blocks'][0]['pickup_pose'].copy();start[2]=374.
    with pytest.raises(ValueError,match='BELOW_TRANSPORT'):
        held.loaded_route(c,start)


def test_endpoint_failure_issues_no_loaded_move(monkeypatch):
    c=config();target=c['blocks'][0]['pickup_pose']
    class Driver:
        def sample(self):
            return dict(posx=target,velx=[0.]*6,motion_status=0,wrench=[0.]*6,query_duration_s=.01,tcp='GripperDA_v4',tool='ToolWeight0',gripper_status=2,robot_state=1,robot_mode=1,drl_state=3)
        def check_pose(self,pose):
            wrong=pose.copy();wrong[0]+=1.;return wrong
    moves=[]
    monkeypatch.setattr(held,'run',lambda *a,**kw:moves.append(a))
    with pytest.raises(RuntimeError,match='HELD_ENDPOINT_IK_FK'):
        held.transfer(Driver(),c,lambda *_:None)
    assert not moves


def test_observation_clock_skew_is_preserved_and_never_grants_motion():
    result=held.observation_frame_timing(9_000_000_000,10_000_000_000,5.,5.1)
    assert result['receive_fresh'] and not result['timestamp_verified']
    assert not result['motion_authority']
    stale=held.observation_frame_timing(10_000_000_000,10_100_000_000,5.,6.)
    assert not stale['receive_fresh']


def test_near_approach_precedes_observation_preserves_xy_orientation():
    c=config();sample=dict(posx=[*c['assembly_target_xy'],c['pickup_clearance_z_mm'],102.,-176.,104.])
    lower,high=held.approach_cycle_targets(sample,c)
    assert lower[2]==100. and high==c['pickup_clearance_z_mm']
    assert lower[:2]==sample['posx'][:2] and lower[3:]==sample['posx'][3:]
    with pytest.raises(ValueError,match='APPROACH_BELOW_TARGET_CLEARANCE'):
        held.approach_cycle_targets(sample,c,approach_z_mm=35.)
    short,_=held.approach_cycle_targets(sample,c,descend_mm=20.)
    assert short[2]==pytest.approx(high-20.)


def test_local_yaw_response_requires_measured_sign_and_gain():
    assert held.observed_yaw_gain(3.,2.5,.5)==-1.
    assert held.observed_yaw_gain(3.,3.5,.5)==1.
    with pytest.raises(ValueError,match='UNUSABLE'):
        held.observed_yaw_gain(3.,3.,.5)


def test_target_layer_approach_uses_selected_existing_tcp_plus20():
    c=held.target_layer_approach(config(),2)
    assert c['alignment_approach_z_mm']==pytest.approx(33.63553237915039+20.)
    pose=[*c['assembly_target_xy'],c['pickup_clearance_z_mm'],102.,-176.,104.]
    lower,high=held.approach_cycle_targets(dict(posx=pose),c)
    assert lower[:2]==c['assembly_target_xy'] and lower[2]==c['alignment_approach_z_mm']
    assert lower[3:]==pose[3:]
    with pytest.raises(ValueError,match='CLEARANCE_AT_LEAST'):
        held.target_layer_approach(config(),2,5.)


def test_yaw_trial_uses_measured_sign_caps_each_step_and_total():
    assert held.yaw_trial_step(-1.25,None,0.)==.5
    assert held.yaw_trial_step(-1.25,-1.,.5)==-.5
    assert held.yaw_trial_step(-1.25,1.,.5)==.5
    assert held.yaw_trial_step(.2,-1.,0.) is None
    with pytest.raises(ValueError,match='LIMIT_2DEG'):
        held.yaw_trial_step(2.,-1.,2.)
    with pytest.raises(ValueError,match='UNUSABLE'):
        held.yaw_trial_step(2.,.1,0.)


def test_half_degree_boundaries_are_already_aligned():
    assert held.yaw_trial_step(.5,-1.,0.) is None
    assert held.yaw_trial_step(-.5,1.,0.) is None
    assert held.yaw_trial_step(3.,-1.,25.,total_limit_deg=None)==.5


def test_integrated_preview_uses_existing_direction_for_automatic_yaw(capsys):
    assert held.main(['--integrated-cycle','--start-zone','home','--target-x','17','--target-y','17'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['auto_correction'] is True
    assert report['correction_scope']=='YAW_DIRECTION_ONLY'
    assert report['roll_pitch_observed'] is False
    assert report['physical_commands']==0
    assert report['pad_contact_at_target_physically_verified'] is False


def test_yaw_pose_guard_rejects_below_clearance_or_wrong_target():
    c=held.target_layer_approach(config(),1)
    position=[*c['assembly_target_xy'],c['alignment_approach_z_mm'],102.,-176.,104.]
    held.validate_yaw_trial_pose(dict(posx=position),c)
    bad=position.copy();bad[2]-=1
    with pytest.raises(ValueError,match='CLEARANCE_AND_XY'):
        held.validate_yaw_trial_pose(dict(posx=bad),c)
    bad=position.copy();bad[0]+=10
    with pytest.raises(ValueError,match='CLEARANCE_AND_XY'):
        held.validate_yaw_trial_pose(dict(posx=bad),c)


def test_initial_rotation_only_at_high_preserves_xyz_and_other_angles():
    c=held.target_layer_approach(config(),1)
    pose=[*c['assembly_target_xy'],c['pickup_clearance_z_mm'],102.,-176.,104.]
    rotated=held.initial_yaw_target(dict(posx=pose),c,1.)
    assert rotated[:3]==pose[:3] and rotated[4:]==pose[4:]
    assert rotated[3]==pytest.approx(103.)
    low=pose.copy();low[2]=c['alignment_approach_z_mm']
    with pytest.raises(RuntimeError,match='START_AT_ASSEMBLY_HIGH'):
        held.initial_yaw_target(dict(posx=low),c,1.)
    with pytest.raises(ValueError,match='WITHIN_2DEG'):
        held.initial_yaw_target(dict(posx=pose),c,3.)


def test_local_motion_uses_configured_force_for_both_axial_and_combined(monkeypatch):
    c=config();c['force_stop_n']=45.;pose=c['blocks'][0]['pickup_pose'].copy()
    calls=[]
    class Driver:
        def sample(self):return dict(posx=pose)
        def check_pose(self,p):return p
    monkeypatch.setattr(held,'wait_for_held_stop',lambda *a,**kw:dict(posx=pose))
    monkeypatch.setattr(held,'run',lambda *a,**kw:calls.append((a,kw)))
    held.local_held_move(Driver(),c,pose.copy(),lambda *_:None)
    assert calls[0][0][3]==45.
    assert calls[0][1]['force_norm_stop_n']==45.


def test_return_high_from_supply_retains_start_height_then_corridor_no_pick():
    c=config();sample=dict(posx=c['observation_pose'])
    targets=held.return_high_targets(c,sample,'supply')
    assert targets[0][1][:2]==c['observation_pose'][:2]
    assert all(target[2]==c['pickup_clearance_z_mm'] for _,target in targets)
    assert targets[-1][1][:2]==c['assembly_target_xy']
    assert targets[-1][1][3:]==c['blocks'][0]['pickup_pose'][3:]
    wrong=sample['posx'].copy();wrong[0]+=20
    with pytest.raises(ValueError,match='START_AT_SUPPLY'):
        held.return_high_targets(c,dict(posx=wrong),'supply')


def test_disabled_force_stop_route_rejects_before_any_device_operation():
    class NoDevice:
        def sample(self):raise AssertionError('Must not access device before route rejection')
    c=config();c['return_high_enabled']=False
    with pytest.raises(RuntimeError,match='DISABLED_AFTER_FORCE_STOP'):
        held.return_high(NoDevice(),c,lambda *_:None,'supply')


def test_home_return_uses_direct_high_route_preserves_current_grasp_and_avoids_old_corridor():
    c=config()
    pose=[367.,3.,194.733,89.7,179.98,90.06]
    sample=dict(posx=pose,posj=[0.,0.,90.,0.,90.,0.])
    targets=held.return_high_targets(c,sample,'home')
    assert len(targets)==1 and targets[0][0]=='HOME_TARGET_HIGH'
    assert targets[0][1][:2]==c['assembly_target_xy']
    assert targets[0][1][2:]==pose[2:]
    sample['posj'][0]=1
    with pytest.raises(ValueError,match='CURRENT_HOME'):
        held.return_high_targets(c,sample,'home')


def test_stable_angle_history_is_json_serializable_python_bool():
    import numpy as np
    result=held.stable_angle_history([(i,np.float64(.2)) for i in range(5)])
    assert type(result) is bool and result
    assert json.dumps(dict(stable=result),allow_nan=False)=='{"stable": true}'
    assert not held.stable_angle_history([(0,.2)]*5)


def test_measured_base_z_uses_so3_near_gimbal_not_euler_a_difference():
    before=[472.,85.,194.,85.87816619873047,179.9778289794922,86.2439956665039]
    after=[472.,85.,194.,90.08495330810547,179.97816467285156,89.44681549072266]
    assert held.measured_base_z_rotation(before,after)==pytest.approx(1.00397,abs=.001)
    assert held.measured_base_z_rotation(after,before)==pytest.approx(-1.00397,abs=.001)


def test_observation_waits_for_residual_velocity_instead_of_aborting():
    c=config();now=[0.];events=[]
    sample=dict(posx=[472.,85.,35.5,90.,179.,90.],velx=[.02,0.,0.,0.,0.,0.],
        motion_status=0,wrench=[0.,0.,3.,0.,0.,0.],query_duration_s=.01,
        tcp=c['connection']['tcp'],tool=c['connection']['tool'],gripper_status=2,
        robot_state=1,robot_mode=1,drl_state=3)
    class Driver:
        def sample(self):
            value=deepcopy(sample)
            if now[0]>=.1:value['velx']=[0.]*6
            return value
    result=held.wait_for_held_stop(Driver(),c,lambda event,data:events.append(event),
        sleep=lambda delay:now.__setitem__(0,now[0]+delay),clock=lambda:now[0])
    assert result['velx']==[0.]*6 and len(events)==2
    now[0]=0.
    with pytest.raises(RuntimeError,match='STOP_WAIT_TIMEOUT'):
        held.wait_for_held_stop(Driver(),c,lambda *_:None,
            sleep=lambda delay:None,clock=iter([0.,6.]).__next__)


def test_target17_uses_existing_anchored_affine_and_preserves_original_record():
    original=config();before=deepcopy(original)
    c=held.target_layer_approach(original,1,target_x=17,target_y=17)
    reference=c['alignment_target']['placement_tcp_reference']
    assert reference[:3]==pytest.approx([568.1645578931725,181.06953312086023,15.88146609430728])
    assert c['alignment_approach_z_mm']==pytest.approx(35.88146609430728)
    assert c['alignment_target']['target']['x']==17 and c['alignment_target']['target']['y']==17
    assert not c['alignment_target']['target_directly_taught']
    assert original==before
