from copy import deepcopy
import json
import pytest
from scripts import held_xy_seating_trial as seating
from scripts import held_corner_stud_trial as held


def config():
    value=json.loads((held.NATIVE/'settings/held_corner_stud_20261014/config.json').read_text())
    value['target_only_motion']=False
    return held.target_layer_approach(value,1)


def test_disabled_assembly_xy_preserves_current_xy_during_vertical_insertion():
    c=config();c.update(assembly_xy_correction_enabled=False,target_only_motion=True)
    pose=[c['assembly_target_xy'][0]+.1,c['assembly_target_xy'][1]-.1,c['alignment_approach_z_mm'],1.,178.,2.]
    sample=dict(posx=pose)
    targets=seating.seating_targets(sample,c)
    assert targets == [[*pose[:2],c['alignment_target']['placement_tcp_reference'][2],*pose[3:]]]
    with pytest.raises(ValueError,match='ASSEMBLY_XY_CORRECTION_DISABLED'):
        seating.xy_target(sample,c)
    with pytest.raises(ValueError,match='ASSEMBLY_XY_CORRECTION_DISABLED'):
        held.visual_xy_target(sample,c,{})


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


@pytest.mark.parametrize('press_limit', [None,56.25,70.])
def test_empty_pad_press_uses_touch_pose_and_existing_reaction_stop(monkeypatch,press_limit):
    from scripts import assembly_press_trial
    d=Driver();reference=d.value['posx'].copy();d.value['posx'][2]+=10.
    calls=[]
    def press(*args,**kwargs):calls.append(kwargs);return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED')
    monkeypatch.setattr(assembly_press_trial,'press',press)
    c=config()
    if press_limit is not None:c['press_force_stop_n']=press_limit
    result=seating.press_from_top_touch(d,c,reference,lambda *_:None,2)
    assert result['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert calls[0]['velocity']==6. and calls[0]['force_stop_n']==(press_limit or 45.)
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


@pytest.mark.parametrize('feedback', [32., 47., 50.3, 55.])
def test_assembly_release_uses_47mm_and_waits_for_bounded_actual_width(feedback):
    c=config();c.update(release_width_mm=47.,release_feedback_range_mm=[32.,55.])
    class ReleaseDriver(Driver):
        def command_gripper(self,width,force):
            self.grips.append((width,force))
            self.value.update(gripper_status=0,gripper_width_mm=feedback)
    d=ReleaseDriver();events=[]
    seating.release(d,c,lambda event,data:events.append((event,data)),operator_seated=True,sleep=lambda _:None)
    assert d.grips==[(47.,40.)] and c['open_mm']==60. and not d.stops
    command=next(data for event,data in events if event=='SEATED_RELEASE_COMMAND')
    assert command['width_mm']==47. and command['feedback_range_mm']==[32.,55.]
    assert events[-1][0]=='SEATED_RELEASE_OPERATOR_CONFIRMED'
    assert events[-1][1]['sample']['gripper_width_mm']==feedback


@pytest.mark.parametrize('feedback', [55.1,61.2])
def test_assembly_release_overwide_feedback_blocks_following_operations(feedback):
    c=config();c.update(release_width_mm=47.,release_feedback_range_mm=[32.,55.])
    class OverwideDriver(Driver):
        def command_gripper(self,width,force):
            self.grips.append((width,force))
            self.value.update(gripper_status=0,gripper_width_mm=feedback)
    d=OverwideDriver();events=[]
    with pytest.raises(RuntimeError,match='SEATED_RELEASE_WIDTH_EXCEEDS_LIMIT'):
        seating.release(d,c,lambda event,data:events.append((event,data)),operator_seated=True,sleep=lambda _:None)
    assert d.grips==[(47.,40.)] and d.stops==1
    assert not any(event=='SEATED_RELEASE_OPERATOR_CONFIRMED' for event,data in events)


@pytest.mark.parametrize('width,bounds', [(60.,[44.,60.]),(48.1,[44.,50.]),
                                        (float('nan'),[44.,50.]),(47.,[44.,60.])])
def test_invalid_assembly_release_policy_sends_no_gripper_command(width,bounds):
    c=config();c.update(release_width_mm=width,release_feedback_range_mm=bounds)
    d=Driver()
    with pytest.raises(ValueError,match='ASSEMBLY_RELEASE_POLICY_INVALID'):
        seating.release(d,c,lambda *_:None,operator_seated=True)
    assert not d.grips and not d.stops


def test_assembly_release_under_32mm_never_confirms_release():
    c=config();c.update(release_width_mm=47.,release_feedback_range_mm=[32.,55.])
    class UnderopenDriver(Driver):
        def command_gripper(self,width,force):
            self.grips.append((width,force))
            self.value.update(gripper_status=0,gripper_width_mm=31.9)
    d=UnderopenDriver();now=[0.];events=[]
    with pytest.raises(TimeoutError,match='SEATED_RELEASE_TIMEOUT'):
        seating.release(d,c,lambda event,data:events.append((event,data)),operator_seated=True,
            sleep=lambda delay:now.__setitem__(0,now[0]+delay),clock=lambda:now[0])
    assert d.grips==[(47.,40.)] and d.stops==1
    assert not any(event=='SEATED_RELEASE_OPERATOR_CONFIRMED' for event,data in events)


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


@pytest.mark.parametrize('fail', [False,True])
def test_p_uses_reaction_60_abort_70_and_never_rises_after_failure(monkeypatch,fail):
    from scripts import assembly_press_trial
    d=Driver();c=config()
    c.update(press_control='POSITION_DESCENT_REACTION_STOP',press_force_target_n=None,press_force_stop_n=60.,press_force_abort_n=70.,
             seating_force_stop_n=50.,press_velocity=3.)
    c['integrated_pad_contact_pose']=d.value['posx'].copy()
    release=d.value['posx'].copy();plan=seating.same_xy_press_plan(release,c)
    calls=[];moves=[]
    def pressure(driver,connection,record,**kwargs):
        calls.append(kwargs)
        if fail:raise RuntimeError('PRESS_FORCE_ABORT_LIMIT_REACHED')
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED',native_force_commands=0)
    def move(driver,c,target,record,**kwargs):
        moves.append(target.copy());driver.value['posx']=target.copy()
    monkeypatch.setattr(assembly_press_trial,'press',pressure)
    if fail:
        with pytest.raises(RuntimeError,match='PRESS_FORCE_ABORT_LIMIT_REACHED'):
            seating.same_xy_press_cycle(d,c,plan,2,lambda *_:None,move)
        assert moves==[plan['above_pose']]
    else:
        seating.same_xy_press_cycle(d,c,plan,2,lambda *_:None,move)
        assert moves==[plan['above_pose'],plan.get('press_rise_pose',plan['rise_pose'])]
    assert calls[0]['force_stop_n']==60. and calls[0]['force_abort_n']==70.
    assert c['seating_force_stop_n']==50. and c['force_stop_n']==45. and not d.grips


def test_top_touch_p_uses_reaction_stop_without_native_force(monkeypatch):
    from scripts import assembly_press_trial
    d=Driver();c=config();reference=d.value['posx'].copy();d.value['posx'][2]+=10.
    c.update(press_control='POSITION_DESCENT_REACTION_STOP',press_force_target_n=None,press_force_stop_n=60.,press_force_abort_n=70.)
    calls=[]
    monkeypatch.setattr(assembly_press_trial,'press',
        lambda *args,**kwargs:calls.append(kwargs) or dict(status='RELEASED'))
    assert seating.press_from_top_touch(d,c,reference,lambda *_:None,2)['status']=='RELEASED'
    assert calls[0]['force_stop_n']==60. and calls[0]['force_abort_n']==70.


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
    c.pop('motion_force_stop_n',None)  # Legacy configs still apply the shared force limit.
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


class ResidualPressureReplay:
    """Construct a MOCK driver with persistent load after pressure STOP."""
    @staticmethod
    def driver(contact,initial,residual,reaction_force_n=48.):
        from app.assembly_step_runner import StepReplayDriver
        class Replay(StepReplayDriver):
            def __init__(self):
                super().__init__(contact,reaction_force_n=reaction_force_n)
                self.after_pressure_stop=False
                self.value.update(posx=initial.copy(),gripper_status=2,gripper_width_mm=9.3)
            def call(self,*args,**kwargs):self.value['robot_mode']=kwargs['robot_mode']
            def stop(self):
                super().stop();self.after_pressure_stop=True;self.value['wrench']=residual.copy()
            def move_line_async(self,target,velocity,acceleration):
                super().move_line_async(target,velocity,acceleration)
                if self.after_pressure_stop:self.value['wrench']=residual.copy()
        return Replay()


@pytest.mark.parametrize('limit,reaction,status', [(56.25,50.,'MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD'),
    (56.25,57.,'FORCE_THRESHOLD_REACHED_STOP_VERIFIED'),(70.,69.,'MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD'),
    (70.,71.,'FORCE_THRESHOLD_REACHED_STOP_VERIFIED')])
def test_P_override_preserves_travel_speed_and_I_force_limit(limit,reaction,status):
    c=config();c['press_force_stop_n']=limit;c['seating_force_stop_n']=55.;c['press_velocity']=12.
    release=c['alignment_target']['placement_tcp_reference'].copy()
    c['integrated_pad_contact_pose']=[*release[:2],release[2]+15.,*release[3:]]
    plan=seating.same_xy_press_plan(release,c)
    d=ResidualPressureReplay.driver(plan['estimated_contact_pose'],plan['rise_pose'],
        [0.,0.,reaction,0.,0.,0.],reaction_force_n=reaction)
    if reaction<limit:
        # Explicit endpoint outcome under a subthreshold load; the generic
        # contact replay otherwise stays at first touch without progressing.
        original_move=d.move_line_async
        def reach_endpoint(target,velocity,acceleration):
            original_move(target,velocity,acceleration)
            d.value['posx']=target.copy()
        d.move_line_async=reach_endpoint
    result=seating.same_xy_press_cycle(d,c,plan,2,lambda *_:None,
        lambda *a,**kw:held.local_held_move(*a,**kw,sleep=lambda _:None))
    assert result['status']==status and result['force_stop_n']==limit
    assert result['max_travel_mm']==12. and not result['assembly_completion']
    assert c['force_stop_n']==45. and c['seating_force_stop_n']==55. and not d.grips
    contact=release.copy();contact[2]+=3.
    first=[*release[:2],c['alignment_approach_z_mm'],*release[3:]]
    insertion=ResidualPressureReplay.driver(contact,first,[0.,0.,56.,0.,0.,0.],reaction_force_n=56.)
    events=[]
    seated=seating.insert(insertion,c,lambda event,data:events.append((event,data)),sleep=lambda _:None)
    assert seated['status']=='FORCE_STOPPED_BEFORE_VERIFIED_SEATING'
    start=next(data for event,data in events if event=='SEATING_TRIAL_START')
    assert start['raw_force_stop_n']==55.


@pytest.mark.parametrize('residual', [
    [0.,0.,48.,0.,0.,0.],
    # Settled wrench from trial-1791942058617563884/PRESS_RESULT; replay is synthetic.
    [-16.34885597229004,.6475402116775513,55.48013687133789,.9723607897758484,-.08659768104553223,.30773189663887024],
    [0.,0.,60.,0.,0.,0.]])
def test_actual_press_then_rise_keeps_45n_contact_cutoff_without_rejecting_residual_load(residual):
    c=config();assert c['motion_force_stop_n'] is None and c['force_stop_n']==45.
    release=c['alignment_target']['placement_tcp_reference'].copy()
    c['integrated_pad_contact_pose']=[*release[:2],release[2]+15.,*release[3:]]
    plan=seating.same_xy_press_plan(release,c)
    d=ResidualPressureReplay.driver(plan['estimated_contact_pose'],plan['rise_pose'],residual)
    events=[]
    result=seating.same_xy_press_cycle(d,c,plan,2,lambda event,data:events.append((event,deepcopy(data))),
        lambda *a,**kw:held.local_held_move(*a,**kw,sleep=lambda _:None))
    assert result['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED' and result['force_stop_n']==45.
    assert result['threshold_force_norm_n']==48. and result['stop']['stillness_verified']
    assert result['final_sample']['wrench']==residual and d.value['wrench']==residual
    assert d.value['posx']==plan['rise_pose'] and d.stops and not d.grips
    assert held.wait_for_held_stop(d,c,lambda *_:None)['wrench']==residual
    assert any(event=='PRESS_RESULT' for event,_ in events) and not result['assembly_completion']


def test_omitted_motion_limit_preserves_legacy_post_pressure_force_abort():
    c=config();c.pop('motion_force_stop_n')
    release=c['alignment_target']['placement_tcp_reference'].copy()
    c['integrated_pad_contact_pose']=[*release[:2],release[2]+15.,*release[3:]]
    plan=seating.same_xy_press_plan(release,c)
    d=ResidualPressureReplay.driver(plan['estimated_contact_pose'],plan['rise_pose'],[0.,0.,60.,0.,0.,0.])
    events=[]
    with pytest.raises(RuntimeError,match='FORCE_NORM_STOP_LIMIT_REACHED'):
        seating.same_xy_press_cycle(d,c,plan,2,lambda event,data:events.append(event),
            lambda *a,**kw:held.local_held_move(*a,**kw,sleep=lambda _:None))
    assert 'PRESS_RESULT' in events and d.value['posx'][2]<plan['rise_pose'][2]


def test_actual_seating_still_stops_at_contact_and_returns_held_result_with_60n_residual():
    c=config();goal=c['alignment_target']['placement_tcp_reference'].copy()
    contact=goal.copy();contact[2]+=3.
    initial=[*goal[:2],c['alignment_approach_z_mm'],*goal[3:]]
    d=ResidualPressureReplay.driver(contact,initial,[0.,0.,60.,0.,0.,0.])
    result=seating.insert(d,c,lambda *_:None,sleep=lambda _:None)
    assert result['status']=='FORCE_STOPPED_BEFORE_VERIFIED_SEATING'
    assert result['final_sample']['wrench'][2]==60. and d.value['gripper_status']==2
    assert not result['assembly_completion'] and not d.grips
    # Separating the force values does not bypass the existing seating-position requirement.
    with pytest.raises(RuntimeError,match='AT_SEATING_TARGET'):
        seating.release(d,c,lambda *_:None,sleep=lambda _:None)
    assert not d.grips


@pytest.mark.parametrize('field,value,error', [
    ('tcp','WrongTCP','TCP_TOOL_MISMATCH'),('gripper_status',1,'ROBOT_OR_GRIP_NOT_READY'),
    ('query_duration_s',.8,'FEEDBACK_TOO_OLD'),('drl_state',2,'DRL_NOT_STOPPED'),
    ('robot_mode',0,'AUTOMATIC_MODE_REQUIRED')])
def test_separated_motion_force_keeps_equipment_and_freshness_guards(field,value,error):
    c=config();d=Driver();d.value['wrench'][2]=60.;d.value[field]=value
    with pytest.raises(RuntimeError,match=error):held.wait_for_held_stop(d,c,lambda *_:None)
    assert not d.grips


def test_target_only_xy_uses_requested_coordinates_from_far_or_low_start():
    d=Driver();c=config();c['target_only_motion']=True
    d.value['posx'][0]+=25.;d.value['posx'][1]-=17.;d.value['posx'][2]-=30.
    before=d.sample()['posx']
    target=seating.xy_target(d.sample(),c)
    assert target[:2]==c['assembly_target_xy'] and target[2:]==before[2:]


@pytest.mark.parametrize('height',['above','below','at_goal'])
def test_target_only_seating_commands_configured_xy_and_z_from_any_position(height):
    d=Driver();c=config();c['target_only_motion']=True
    goal=c['alignment_target']['placement_tcp_reference'][2]
    d.value['posx'][:2]=[100.,-50.]
    d.value['posx'][2]=goal+dict(above=20.,below=-3.,at_goal=0.)[height]
    targets=seating.seating_targets(d.sample(),c)
    assert targets==[[*c['assembly_target_xy'],goal,*d.value['posx'][3:]]]


def test_target_only_insertion_accepts_stopped_velocity_and_pose_jitter_without_ik_gate(monkeypatch):
    c=config();c['target_only_motion']=True;d=Driver();calls=[];now=[0.]
    d.value['velx']=[.02,0.,0.,.01,0.,0.]
    d.value['posx'][0]+=4.;d.value['posx'][2]-=30.
    original_sample=d.sample
    def sample():
        d.value['posx'][0]+=.07;d.value['posx'][2]+=.053
        return original_sample()
    d.sample=sample
    def no_ik(*_):raise AssertionError('target-only trial must not query endpoint IK')
    d.check_pose=no_ik
    def move(driver,connection,target,limit,record,**kwargs):
        calls.append((target.copy(),kwargs));driver.value['posx']=target.copy()
    monkeypatch.setattr(seating,'run',move)
    result=seating.insert(d,c,lambda *_:None,sleep=lambda delay:now.__setitem__(0,now[0]+delay),clock=lambda:now[0])
    assert result['status']=='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED'
    assert calls[0][0][:3]==[*c['assembly_target_xy'],c['alignment_target']['placement_tcp_reference'][2]]
    assert calls[0][1]['target_only_motion'] is True and now[0]==0.
    assert not result['actual_seating_verified'] and not result['assembly_completion'] and not d.grips


def test_target_only_release_accepts_height_offset_and_stopped_velocity():
    c=config();c['target_only_motion']=True;d=Driver();now=[0.]
    d.value['velx']=[.02,0.,0.,0.,0.,0.];d.value['posx'][2]+=3.
    seating.release(d,c,lambda *_:None,sleep=lambda delay:now.__setitem__(0,now[0]+delay),clock=lambda:now[0])
    assert d.grips==[(60.,40.)]


@pytest.mark.parametrize('field,value,error',[
    ('motion_status',1,'AT_SEATING_TARGET'),('tcp','WrongTCP','TCP_TOOL_MISMATCH'),
    ('gripper_status',1,'ROBOT_OR_GRIP_NOT_READY'),('query_duration_s',.8,'FEEDBACK_TOO_OLD'),
])
def test_target_only_release_still_requires_device_and_controller_stop(field,value,error):
    c=config();c['target_only_motion']=True;d=Driver();d.value[field]=value
    with pytest.raises(RuntimeError,match=error):seating.release(d,c,lambda *_:None)
    assert not d.grips


def test_target_only_top_touch_press_forwards_profile_despite_pose_offset(monkeypatch):
    from scripts import assembly_press_trial
    c=config();c['target_only_motion']=True;d=Driver();calls=[]
    reference=d.value['posx'].copy();d.value['posx'][0]+=7.;d.value['posx'][2]+=10.4
    monkeypatch.setattr(assembly_press_trial,'press',lambda *args,**kwargs:calls.append(kwargs) or dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'))
    result=seating.press_from_top_touch(d,c,reference,lambda *_:None,2)
    assert result['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED' and calls[0]['target_only_motion'] is True


def test_target_only_same_xy_press_retains_saved_goals_without_datum_precision_gate(monkeypatch):
    from scripts import assembly_press_trial
    c=config();c['target_only_motion']=True;d=Driver()
    release=d.sample()['posx'];c['integrated_pad_contact_pose']=[*release[:2],release[2]+15.,*release[3:]]
    plan=seating.same_xy_press_plan(release,c);d.value['posx']=plan['rise_pose'].copy()
    d.value['posx'][0]+=3.;d.value['posx'][3]+=2.;moves=[];calls=[]
    def move(driver,config,target,record,**kwargs):
        moves.append(target.copy());driver.value['posx']=target.copy()
    monkeypatch.setattr(assembly_press_trial,'press',lambda *args,**kwargs:calls.append(kwargs) or dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'))
    result=seating.same_xy_press_cycle(d,c,plan,2,lambda *_:None,move)
    assert result['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED' and calls[0]['target_only_motion'] is True
    assert moves==[plan['above_pose'],plan['rise_pose']] and not d.grips
