from copy import deepcopy
import json
import pytest
from scripts import held_xy_seating_trial as seating
from scripts import held_corner_stud_trial as held


def config():
    value=json.loads((held.NATIVE/'settings/held_corner_stud_20261014/config.json').read_text())
    return held.target_layer_approach(value,1)


class Driver:
    def __init__(self):
        c=config()
        self.value=dict(posx=[*c['assembly_target_xy'],c['alignment_approach_z_mm'],102.,-176.,104.],
            velx=[0.]*6,motion_status=0,wrench=[0.,0.,3.,0.,0.,0.],query_duration_s=.01,
            tcp='GripperDA_v4',tool='ToolWeight0',gripper_status=2,gripper_width_mm=40.,
            robot_state=1,robot_mode=1,drl_state=3)
        self.stops=0;self.grips=[]
    def sample(self):return deepcopy(self.value)
    def check_pose(self,target):return target
    def stop(self):self.stops+=1
    def command_gripper(self,width,force):
        self.grips.append((width,force));self.value.update(gripper_status=0,gripper_width_mm=62.)


def test_xy_correction_preserves_z_and_orientation_rejects_large_offset():
    d=Driver();c=config();d.value['posx'][0]+=1
    target=seating.xy_target(d.sample(),c)
    assert target[:2]==c['assembly_target_xy'] and target[2:]==d.value['posx'][2:]
    d.value['posx'][0]+=3
    with pytest.raises(ValueError,match='OUTSIDE_2MM'):
        seating.xy_target(d.sample(),c)


def test_seating_stages_end_exactly_at_reference_without_xyz_turn_changes():
    d=Driver();c=config();targets=seating.seating_targets(d.sample(),c)
    assert len(targets)==20
    assert targets[-1][2]==c['alignment_target']['placement_tcp_reference'][2]
    assert all(target[:2]==d.value['posx'][:2] and target[3:]==d.value['posx'][3:] for target in targets)
    with pytest.raises(ValueError,match='POSITIVE_SEATING_STEP'):
        seating.seating_targets(d.sample(),c,0.)


def test_contact_stops_early_preserves_hold_and_never_claims_completion(monkeypatch):
    d=Driver();events=[]
    def move(driver,connection,target,limit,record,**kwargs):
        halfway=target.copy();halfway[2]=(driver.value['posx'][2]+target[2])/2
        driver.value['posx']=halfway;driver.value['wrench'][2]=45.
        record('MOTION_SAMPLE',dict(sample=driver.sample()))
        raise RuntimeError('FORCE_NORM_STOP_LIMIT_REACHED')
    monkeypatch.setattr(seating,'run',move)
    # Actual stop settles below threshold before equipment validation.
    original_stop=d.stop
    def stop():
        original_stop();d.value['wrench'][2]=44.
    d.stop=stop
    result=seating.insert(d,config(),lambda event,data:events.append(event),sleep=lambda _:None)
    assert result['status']=='FORCE_STOPPED_BEFORE_VERIFIED_SEATING'
    assert d.stops and not d.grips and d.value['gripper_status']==2
    assert not result['assembly_completion']
    with pytest.raises(RuntimeError,match='AT_SEATING_TARGET'):
        seating.release(d,config(),lambda *_:None)


def test_full_descent_does_not_open_until_separate_release(monkeypatch):
    d=Driver()
    def move(driver,connection,target,limit,record,**kwargs):
        driver.value['posx']=target.copy();record('MOTION_SAMPLE',dict(sample=driver.sample()))
    monkeypatch.setattr(seating,'run',move)
    result=seating.insert(d,config(),lambda *_:None,sleep=lambda _:None)
    assert result['status']=='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED'
    assert not d.grips and not result['actual_seating_verified']
    seating.release(d,config(),lambda *_:None,sleep=lambda _:None)
    assert d.grips==[(60.,40.)]


def test_wrong_xy_or_height_blocks_seating_before_commands():
    d=Driver();d.value['posx'][0]+=1
    with pytest.raises(ValueError,match='TARGET_XY'):
        seating.insert(d,config(),lambda *_:None)
    assert not d.grips and not d.stops


def test_repeated_descent_accepts_settling_drift_without_extra_lift():
    class SettlingDriver(Driver):
        def __init__(self):
            super().__init__();self.pending=False;self.moves=[]
        def call(self,*args,**kwargs):self.value['robot_mode']=1
        def sample(self):
            if self.pending:
                self.value['posx'][2]+=.07;self.pending=False
            return super().sample()
        def move_line_async(self,target,velocity,acceleration):
            self.moves.append(target.copy());self.value['posx']=target.copy()
    d=SettlingDriver()
    def record(event,data):
        if event=='RESULT':d.pending=True
    result=seating.insert(d,config(),record,sleep=lambda _:None)
    assert len(d.moves)==1
    assert d.moves[-1][2]==config()['alignment_target']['placement_tcp_reference'][2]
    assert result['status']=='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED'
    assert not d.grips and not d.stops


def test_first_contact_does_not_abort_continuous_seating(monkeypatch):
    d=Driver();requests=[]
    def move(driver,connection,target,limit,record,**kwargs):
        midway=target.copy();midway[2]+=3.
        driver.value['posx']=midway;driver.value['wrench'][2]=10.
        record('MOTION_SAMPLE',dict(sample=driver.sample()))
        driver.value['posx']=target.copy();requests.append((limit,kwargs))
    monkeypatch.setattr(seating,'run',move)
    result=seating.insert(d,config(),lambda *_:None,sleep=lambda _:None)
    assert result['status']=='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED'
    assert len(requests)==1 and requests[0][0]==45.
    assert requests[0][1]['descent_rate']==6. and not d.stops


def test_empty_pad_press_uses_touch_pose_and_existing_reaction_stop(monkeypatch):
    from scripts import assembly_press_trial
    d=Driver();reference=d.value['posx'].copy();d.value['posx'][2]+=10.
    calls=[]
    def press(*args,**kwargs):calls.append(kwargs);return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr(assembly_press_trial,'press',press)
    result=seating.press_from_top_touch(d,config(),reference,lambda *_:None,2)
    assert result['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert calls[0]['velocity']==6. and calls[0]['force_stop_n']==45.
    assert calls[0]['required_gripper_status']==2 and calls[0]['max_travel_mm']==12.
    d.value['posx'][0]+=1.
    with pytest.raises(RuntimeError,match='CAPTURED_TOP'):
        seating.press_from_top_touch(d,config(),reference,lambda *_:None,2)
    assert len(calls)==1


def test_operator_release_records_height_without_claiming_seating():
    d=Driver();d.value['posx'][2]=config()['alignment_target']['placement_tcp_reference'][2]+3.
    events=[]
    seating.release(d,config(),lambda event,data:events.append((event,data)),operator_seated=True,sleep=lambda _:None)
    diagnostic=next(data for event,data in events if event=='RELEASE_HEIGHT_DIAGNOSTIC')
    assert diagnostic['z_error_mm']==3. and diagnostic['operator_seated']
    assert not diagnostic['assembly_completion'] and d.grips==[(60.,40.)]


def test_saved_pad_contact_runs_only_lift_press_lift(monkeypatch,tmp_path):
    d=Driver();d.value['gripper_width_mm']=9.2;d.value['robot_mode']=0
    reference=d.value['posx'].copy()
    p=tmp_path/'contact.json';p.write_text(json.dumps(dict(pose=reference,samples=[d.sample()])))
    moves=[];modes=[]
    def move(driver,c,target,record,**kwargs):
        assert target[2]==reference[2]+10.
        moves.append(target.copy());driver.value['posx']=target.copy()
    monkeypatch.setattr(held,'local_held_move',move)
    def press(*args,**kwargs):return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr(seating,'press_from_top_touch',press)
    d.call=lambda *args,**kwargs:modes.append(kwargs)
    held.saved_pad_press(d,config(),p,lambda *_:None)
    assert len(moves)==2 and modes==[dict(robot_mode=1)] and not d.grips
    d.value['posx'][0]+=1.
    with pytest.raises(RuntimeError,match='POSITION_CHANGED'):
        held.saved_pad_press(d,config(),p,lambda *_:None)
    assert len(moves)==2


def test_integrated_config_uses_current_supply_detector_without_mutating_sources():
    base=config();source=deepcopy(base)
    source['vision']=dict(backend='opencv_studs',center_basis='STUD_ARRAY')
    result=held.integrated_config(base,source)
    assert result['vision']==source['vision'] and result['velocity']==12.
    assert result['integrated_cycle'] and 'integrated_cycle' not in base
    result['vision']['backend']='changed'
    assert source['vision']['backend']=='opencv_studs'


def test_integrated_pad_cycle_goes_via_high_then_presses_and_returns_high(monkeypatch):
    d=Driver();reference=d.value['posx'].copy();reference[2]=34.43
    c=config();moves=[];calls=[];events=[]
    def move(driver,c,target,record,**kwargs):
        moves.append(target.copy());driver.value['posx']=target.copy()
        assert kwargs['required_gripper_status']==2
    def press(driver,c,ref,record,status):
        calls.append((ref.copy(),status));driver.value['posx']=ref.copy()
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr(held,'local_held_move',move)
    monkeypatch.setattr(seating,'press_from_top_touch',press)
    held.closed_pad_cycle(d,c,reference,2,lambda event,data:events.append((event,data)))
    assert [p[2] for p in moves]==[c['pickup_clearance_z_mm'],44.43,44.43,c['pickup_clearance_z_mm']]
    assert all(p[:2]==reference[:2] and p[3:]==reference[3:] for p in moves)
    assert calls==[(reference,2)] and not d.grips
    assert not events[-1][1]['assembly_completion']


def test_integrated_loaded_route_replaces_third_waypoint_without_fourth():
    c=held.integrated_config(config(),config())
    start=c['blocks'][0]['pickup_pose']
    route=held.loaded_route(c,start)
    assert [name for name,_ in route]==['HELD_VERTICAL_LIFT','HELD_SUPPLY','HELD_BODY_BYPASS','HELD_ASSEMBLY_OBSERVATION']
    assert [p[:2] for _,p in route[1:]]==[c['startup_route']['supply_transit_xy'],c['startup_route']['body_bypass_xy'],c['assembly_target_xy']]
    assert all(p[3:]==start[3:] for _,p in route)
    assert c['startup_route']['place_xy']==c['assembly_target_xy']


def test_integrated_local_rates_horizontal120_vertical12(monkeypatch):
    d=Driver();c=held.integrated_config(config(),config());calls=[]
    def run(driver,connection,target,limit,record,**kwargs):
        calls.append(kwargs);driver.value['posx']=target.copy()
    monkeypatch.setattr(held,'run',run)
    target=d.value['posx'].copy();target[0]+=1.
    held.local_held_move(d,c,target,lambda *_:None)
    target=target.copy();target[2]+=10.
    held.local_held_move(d,c,target,lambda *_:None)
    target=target.copy();target[2]-=10.
    held.local_held_move(d,c,target,lambda *_:None)
    assert [v['transfer_rate'] for v in calls]==[120.,12.,120.]
    assert all(v['descent_rate']==12. for v in calls)
    assert calls[-1]['clearance_z'] is None and not calls[-1]['transfer_only']


def test_integrated_transfer_accepts_recorded_lift_settling_and_uses_fresh_level_height(monkeypatch):
    d=Driver();c=held.integrated_config(config(),config())
    d.value['posx']=[*c['blocks'][0]['pickup_pose'][:2],c['pickup_clearance_z_mm']+.053,*c['blocks'][0]['pickup_pose'][3:]]
    calls=[]
    def move(driver,connection,target,limit,record,**kwargs):
        calls.append((target.copy(),kwargs))
        # run transfer_only with clearance None holds its freshly read Z.
        level=driver.value['posx'][2] if kwargs['clearance_z'] is None else kwargs['clearance_z']
        driver.value['posx']=[*target[:2],level,*target[3:]]
    monkeypatch.setattr(held,'run',move)
    held.transfer(d,c,lambda *_:None,sleep=lambda _:None)
    assert d.value['posx'][:2]==c['assembly_target_xy']
    assert all(options['clearance_z'] is None for _,options in calls)
    assert d.value['posx'][2]==c['pickup_clearance_z_mm']+.053
    assert not d.grips and not d.stops


def test_user45n_combined_force_policy_allows36_and_stops45_before_move(monkeypatch):
    d=Driver();c=config();assert c['force_stop_n']==45.
    d.value['wrench']=[0.,0.,36.,0.,0.,0.]
    assert held.wait_for_held_stop(d,c,lambda *_:None)['wrench'][2]==36.
    d.value['wrench'][2]=45.
    with pytest.raises(RuntimeError,match='FORCE_NORM_STOP_LIMIT_REACHED'):
        held.wait_for_held_stop(d,c,lambda *_:None)
    assert not d.grips


def test_same_xy_plan_uses_release_center_and_attitude_not_old_pad_xy():
    c=config();c['integrated_pad_contact_pose']=[455.,86.,34.43,10.,-179.,9.]
    release=[568.,181.,16.,103.,-176.,104.]
    plan=seating.same_xy_press_plan(release,c)
    for key in ('estimated_contact_pose','above_pose','rise_pose'):
        assert plan[key][:2]==release[:2] and plan[key][3:]==release[3:]
    assert plan['rise_pose'][2]>=release[2]+40.
    assert not plan['contact_height_physically_verified']


def test_same_xy_pressure_sequence_descends_and_rises_without_gripper_or_rotation(monkeypatch):
    from scripts import assembly_press_trial
    d=Driver();c=config();c['integrated_pad_contact_pose']=[455.,86.,34.43,10.,-179.,9.]
    c['press_velocity']=12.
    release=d.value['posx'].copy();release[2]=16.
    plan=seating.same_xy_press_plan(release,c);d.value['posx']=plan['rise_pose'].copy()
    moves=[];presses=[]
    def move(driver,c,target,record,**kwargs):
        moves.append(target.copy());driver.value['posx']=target.copy()
    def press(driver,connection,record,**kwargs):
        presses.append(kwargs);return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr(assembly_press_trial,'press',press)
    seating.same_xy_press_cycle(d,c,plan,2,lambda *_:None,move)
    assert moves==[plan['above_pose'],plan['rise_pose']]
    assert presses[0]['force_stop_n']==45. and presses[0]['velocity']==12.
    assert not d.grips
    d.value['posx'][0]+=1.
    with pytest.raises(RuntimeError,match='DATUM_CHANGED'):
        seating.same_xy_press_cycle(d,c,plan,2,lambda *_:None,move)
    assert len(presses)==1
