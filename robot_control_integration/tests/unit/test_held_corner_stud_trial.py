from copy import deepcopy
import json
import pytest
from scripts import held_corner_stud_trial as held
from scripts import supply_pick_release_trial as supply


def config():
    value=json.loads((held.NATIVE/'settings/held_corner_stud_20261014/config.json').read_text())
    value['target_only_motion']=False
    return value


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
    c.pop('motion_force_stop_n',None)  # Omitted option retains the original 45N motion policy.
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


@pytest.fixture
def popup_replay(monkeypatch,tmp_path):
    """Synthetic camera/UI and instant robot responses; no ROS/device connection."""
    import sys
    import time
    from types import ModuleType,SimpleNamespace
    import cv2
    import numpy as np
    from supply_vision import virtual_board_grid
    from scripts import held_xy_seating_trial as seating
    c=held.target_layer_approach(supply.load_config(held.NATIVE/'settings/held_corner_stud_20261014/config.json'),1)
    c['alignment_target']['target'].update(color='blue',brick_type='2x3x1')
    c['same_xy_press']=True
    reference=c['alignment_target']['placement_tcp_reference']
    c['integrated_pad_contact_pose']=[*reference[:2],reference[2]+15.,*reference[3:]]
    frame=np.zeros((120,200,3),np.uint8);frame[30:90,50:150]=(255,0,0)
    stamp=time.time_ns()
    header=SimpleNamespace(stamp=SimpleNamespace(sec=stamp//10**9,nanosec=stamp%10**9),frame_id='camera_color_optical_frame')
    rgb=SimpleNamespace(header=header,encoding='bgr8',height=120,width=200,step=600,data=frame.tobytes())
    info=SimpleNamespace(header=header,width=200,height=120,k=[100.,0.,100.,0.,100.,60.,0.,0.,1.],d=[],distortion_model='plumb_bob')
    class Node:
        context=None
        def create_subscription(self,kind,topic,callback,qos):
            if topic.endswith('image_raw') and '/color/' in topic:callback(rgb)
            if topic.endswith('camera_info'):callback(info)
            return None
        def get_clock(self):return SimpleNamespace(now=lambda:SimpleNamespace(nanoseconds=stamp))
        def destroy_node(self):pass
    class Executor:
        def __init__(self,**kwargs):pass
        def add_node(self,node):pass
        def spin(self):pass
        def shutdown(self,**kwargs):pass
    for name,attributes in {
        'sensor_msgs':{},'sensor_msgs.msg':dict(Image=object,CameraInfo=object),
        'rclpy':{},'rclpy.qos':dict(qos_profile_sensor_data=object()),
        'rclpy.executors':dict(SingleThreadedExecutor=Executor)}.items():
        module=ModuleType(name);module.__dict__.update(attributes);monkeypatch.setitem(sys.modules,name,module)
    events=[];labels=[];projected=[];operations=[]
    class Grid:
        def __init__(self,config):pass
        def overlay(self,image,*args,**kwargs):
            projected.append(deepcopy(kwargs['target']))
            return image.copy(),dict(status='UNKNOWN',reason='SYNTHETIC_UI_ONLY',relative_angle_deg=None)
    monkeypatch.setattr(virtual_board_grid,'VirtualBoardGrid',Grid)
    for name in ('namedWindow','resizeWindow','setMouseCallback','imshow','destroyAllWindows'):
        monkeypatch.setattr(cv2,name,lambda *a,**kw:None)
    monkeypatch.setattr(cv2,'putText',lambda image,text,*a,**kw:labels.append(text))
    monkeypatch.setattr(cv2,'getWindowProperty',lambda *_:1.)
    monkeypatch.setattr(held.time,'sleep',lambda _:None)
    class Driver:
        def __init__(self):
            self.ros=SimpleNamespace(create_node=lambda _:Node());self.stops=0
            self.value=dict(posx=[*c['assembly_target_xy'],c['alignment_approach_z_mm'],*reference[3:]],
                velx=[0.]*6,motion_status=0,wrench=[0.]*6,query_duration_s=.01,
                tcp=c['connection']['tcp'],tool=c['connection']['tool'],gripper_status=2,
                gripper_width_mm=40.,robot_state=1,robot_mode=1,drl_state=3)
        def sample(self):return deepcopy(self.value)
        def command_gripper(self,width,force):
            self.value.update(gripper_status=0 if width==c['open_mm'] else 2,gripper_width_mm=width)
        def stop(self):self.stops+=1
    driver=Driver()
    def move(d,config,target,record,**kwargs):d.value['posx']=target.copy();operations.append('move')
    def insert(d,config,record):
        operations.append('insert');d.value['posx'][2]=reference[2]
        return dict(status='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED',assembly_completion=False)
    def press(d,config,plan,status,record,move):
        operations.append('press');move(d,config,plan['rise_pose'],record,required_gripper_status=status)
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED',assembly_completion=False)
    monkeypatch.setattr(held,'local_held_move',move)
    monkeypatch.setattr(seating,'insert',insert)
    monkeypatch.setattr(seating,'same_xy_press_cycle',press)
    def run(keys,support_ready=None):
        commands=iter(keys);monkeypatch.setattr(cv2,'waitKey',lambda _:next(commands))
        return held.observe(driver,c,tmp_path,lambda event,data:events.append((event,deepcopy(data))),
            virtual_grid=True,xy_seat_test=True,support_ready=support_ready)
    return SimpleNamespace(run=run,driver=driver,config=c,events=events,labels=labels,
        projected=projected,operations=operations,directory=tmp_path)


@pytest.mark.parametrize('last,status', [(ord('u'),'CYCLE_COMPLETED'),(27,'STOPPED_BY_OPERATOR')])
def test_popup_keeps_support_through_press_rise_and_distinguishes_stop_after_press(popup_replay,last,status):
    replay=popup_replay;requests=[]
    def ready(config):requests.append(config['alignment_target']['target']);return True
    result=replay.run([32,ord('x'),ord('i'),ord('i'),ord('o'),ord('p'),last],ready)
    assert result['status']==status and result['released'] and result['press_done']
    assert result['press_result']['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert len(requests)==1 and replay.operations.count('insert')==2 and replay.operations.count('press')==1
    assert any('HELD blue 2x3x1' in line for line in replay.labels)
    assert any('keep holding lower structure through press/rise' in line for line in replay.labels)
    assert all(target==replay.config['alignment_target']['target'] for target in replay.projected)
    saved=json.loads(next(replay.directory.glob('assembly-observation-*.json')).read_text())
    assert saved['block']['color']=='blue' and saved['block']['status']=='COLOR_BLOCK_OBSERVATION'
    assert replay.driver.stops==1 and replay.driver.ui_pump is None
    finished=[data for event,data in replay.events if event=='TRIAL_HUMAN_SUPPORT_FINISHED'][0]
    assert finished['may_release_support']==(status=='CYCLE_COMPLETED')


def test_popup_support_cancellation_never_inserts_or_releases(popup_replay):
    replay=popup_replay
    result=replay.run([ord('x'),ord('i')],lambda _:False)
    assert result['status']=='STOPPED_BY_OPERATOR' and result['stop_reason']=='HUMAN_SUPPORT_CANCELLED'
    assert not result['released'] and not result['press_done'] and not result['support_active']
    assert 'insert' not in replay.operations and 'press' not in replay.operations
    assert replay.driver.stops==1


def test_popup_rise_without_press_reports_incomplete(popup_replay):
    result=popup_replay.run([ord('u')])
    assert result['status']=='INCOMPLETE' and not result['press_done'] and result['press_result'] is None
    assert not result['assembly_completion']


def test_target_only_held_stop_accepts_controller_complete_with_small_reported_velocity():
    c=config();c['target_only_motion']=True;events=[]
    sample=dict(posx=[400.,80.,20.,0.,180.,0.],velx=[.02,0.,0.,.01,0.,0.],
        motion_status=0,wrench=[0.]*6,query_duration_s=.01,tcp=c['connection']['tcp'],
        tool=c['connection']['tool'],gripper_status=2,robot_state=1,robot_mode=1,drl_state=3)
    class Driver:
        def sample(self):return deepcopy(sample)
    def no_wait(*_):raise AssertionError('controller-complete sample must not wait on a velocity threshold')
    actual=held.wait_for_held_stop(Driver(),c,lambda event,data:events.append(event),sleep=no_wait)
    assert actual['velx']==sample['velx'] and not events


def test_target_only_transfer_commands_route_despite_pose_jitter_and_skips_ik(monkeypatch):
    c=config();c['target_only_motion']=True;calls=[]
    pose=c['blocks'][0]['pickup_pose'].copy()
    class Driver:
        def __init__(self):
            self.value=dict(posx=pose,velx=[.02,0.,0.,0.,0.,0.],motion_status=0,wrench=[0.]*6,
                query_duration_s=.01,tcp=c['connection']['tcp'],tool=c['connection']['tool'],
                gripper_status=2,robot_state=1,robot_mode=1,drl_state=3)
        def sample(self):
            self.value['posx'][0]+=.07
            return deepcopy(self.value)
        def check_pose(self,*_):raise AssertionError('target-only trial must skip endpoint IK')
    d=Driver()
    def move(driver,connection,target,limit,record,**kwargs):
        calls.append((target.copy(),kwargs));driver.value['posx']=target.copy()
    monkeypatch.setattr(held,'run',move)
    held.transfer(d,c,lambda *_:None,sleep=lambda _:None)
    assert calls[-1][0][:2]==c['assembly_target_xy'] and all(kw['target_only_motion'] is True for _,kw in calls)


def test_target_only_approach_and_yaw_do_not_require_current_target_window():
    c=held.target_layer_approach(config(),1);c['target_only_motion']=True
    sample=dict(posx=[100.,-50.,10.,102.,-176.,104.])
    lower,_=held.approach_cycle_targets(sample,c)
    assert lower[:3]==[*c['assembly_target_xy'],c['alignment_approach_z_mm']]
    held.validate_yaw_trial_pose(sample,c)


def test_target_only_popup_accepts_off_target_pose_and_velocity_diagnostics(popup_replay):
    replay=popup_replay;replay.config['target_only_motion']=True
    replay.driver.value['posx'][0]+=8.;replay.driver.value['posx'][2]-=10.
    replay.driver.value['velx']=[.02,0.,0.,0.,0.,0.]
    result=replay.run([ord('x'),ord('i'),ord('o'),ord('p'),ord('u')])
    assert result['status']=='CYCLE_COMPLETED' and result['press_done'] and result['released']
    assert replay.operations.count('insert')==1 and replay.operations.count('press')==1
    assert not result['assembly_completion']
