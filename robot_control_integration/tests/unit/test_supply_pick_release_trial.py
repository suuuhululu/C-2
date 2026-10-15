from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import supply_pick_release_trial as trial


def config():
    value = json.loads(trial.DEFAULT.read_text())
    # Synthetic endpoint substitutes only for testing the execution sequence.
    for i, row in enumerate(value['blocks']):
        row.update(pickup_pose=[-400., float(i*20), 50., 0., 180., 0.], pose_source='SYNTHETIC_TEST_ONLY')
    return value


def decision(row, recognized=False):
    return dict(slot_id=f"{row['color']}_{row['brick_type']}_{row['slot']:02d}",
                vision_attempted=True, recognized=recognized, reason='no_detection', center_uv=[12., 22.])


def test_fixed_order_rejects_swapped_blocks_and_missing_teaching():
    value = config()
    value['blocks'][0], value['blocks'][1] = value['blocks'][1], value['blocks'][0]
    with pytest.raises(ValueError, match='FIXED_BLOCK_ORDER'):
        trial.validate(value)
    value = config(); value['blocks'][3]['pickup_pose'] = None
    with pytest.raises(ValueError, match='EXACT_SLOT_AXIS_TEACHING'):
        trial.validate(value, True)


def test_vision_not_recognized_or_mapping_unverified_keeps_exact_coordinates():
    row = config()['blocks'][0]
    for recognized in (False, True):
        report = decision(row, recognized)
        assert trial.center_target(row, report) == row['pickup_pose']
        assert not report['center_assist_applied'] and report['fallback_reason']


def test_verified_center_changes_only_xy_and_bound_failure_is_logged():
    row = config()['blocks'][0]
    row['center_mapping'] = dict(independently_verified=True, base_xy_mm_per_pixel=[[.1, 0], [0, .1]],
                                reference_center_uv=[10., 20.], max_shift_mm=1.)
    report = decision(row, True)
    target = trial.center_target(row, report)
    assert target[:2] == pytest.approx([-399.8, .2])
    assert target[2:] == row['pickup_pose'][2:]
    assert report['center_assist_applied']
    report = decision(row, True); report['center_uv'] = [100., 100.]
    assert trial.center_target(row, report) == row['pickup_pose']
    assert report['fallback_reason'] == 'CENTER_OUT_OF_BOUND'


def test_slot_mismatch_aborts_instead_of_coordinate_fallback():
    row = config()['blocks'][0]
    report = decision(row); report['slot_id'] = 'wrong_slot'
    with pytest.raises(ValueError, match='VISION_SLOT_BINDING_MISMATCH'):
        trial.center_target(row, report)


@pytest.mark.parametrize('hold', [False, True])
def test_five_blocks_each_observed_closed_released_then_empty_return(monkeypatch, hold):
    value = config(); calls = []; events = []
    class Driver:
        def __init__(self):
            self.value = dict(posx=value['observation_pose'].copy(), velx=[0.]*6,
                motion_status=0, wrench=[0.]*6, query_duration_s=.01, tcp='GripperDA_v4',
                tool='ToolWeight0', gripper_status=0, gripper_width_mm=62., robot_state=1,
                robot_mode=0, drl_state=3)
            self.stopped = False
        def sample(self): return deepcopy(self.value)
        def check_pose(self, target): return target
        def command_gripper(self, width, force):
            calls.append(('grip', width)); self.value.update(gripper_status=0 if width==60 else 2, gripper_width_mm=width)
        def stop(self): self.stopped = True
    driver = Driver()
    def move(d, connection, target, limit, record, **kwargs):
        calls.append(('move', target.copy()))
        assert d.value['gripper_status'] == 0
        d.value.update(posx=target.copy(), robot_mode=1)
    monkeypatch.setattr(trial, 'run', move)
    def observe(row):
        calls.append(('vision', row['slot']))
        assert driver.value['posx'] == value['observation_pose']
        return decision(row)
    trial.execute(driver, value, lambda event, data: events.append((event, deepcopy(data))), observe, slot=1 if hold else None, hold_at_pickup=hold, sleep=lambda _: None)
    if hold:
        assert [item[1] for item in calls if item[0]=='grip']==[35.]
        assert driver.value['gripper_status']==2
        assert driver.value['posx']==value['blocks'][0]['pickup_pose']
        assert any(event=='PICKUP_COMPLETE_HOLDING' for event,_ in events)
        assert not any(event=='RELEASE_FEEDBACK' for event,_ in events)
        return
    assert [item for item in calls if item[0]=='vision'] == [('vision', i) for i in range(1, 6)]
    assert [item[1] for item in calls if item[0]=='grip'] == [35.,60.,40.,60.,35.,60.,40.,60.,20.,60.]
    assert sum(event=='VISION_DECISION' for event, _ in events) == 5
    assert sum(event=='BLOCK_COMPLETE' for event, _ in events) == 5
    assert not driver.stopped and driver.value['posx'] == value['observation_pose']
    assert sum(event=='OBSERVATION_TO_TRANSIT_HEIGHT' for event,_ in events)==5
    assert sum(event=='EMPTY_RETURN_AT_TRANSIT_HEIGHT' for event,_ in events)==5
    highs=[data['target'] for event,data in events if event=='BLOCK_HIGH']
    assert all(target[2]==value['pickup_clearance_z_mm'] for target in highs)


def test_teaching_rejects_assembly_pose_before_saving():
    value = config()
    with pytest.raises(ValueError, match='공급판 교시 범위 밖'):
        trial.validate_teaching_location(value, [454.397,85.854,45.632,0.,180.,0.])
    trial.validate_teaching_location(value, [-393.677,134.999,45.749,0.,180.,0.])


def test_single_slot_trial_does_not_require_later_slot_teaching():
    value = config()
    value['blocks'][3].update(pickup_pose=None, pose_source=None)
    value['blocks'][4].update(pickup_pose=None, pose_source=None)
    assert [r['slot'] for r in trial.selected_blocks(value, 1)] == [1]
    with pytest.raises(ValueError, match='실제 파지 교시'):
        trial.selected_blocks(value, 4)
    with pytest.raises(ValueError, match='실제 파지 교시'):
        trial.selected_blocks(value)


def test_actual_config_preserves_all_existing_slot_xyz_and_separates_axis_turn():
    value = json.loads(trial.DEFAULT.read_text())
    assert len(trial.selected_blocks(value)) == 5
    for row in value['blocks']:
        assert row['pickup_pose'][:2] == pytest.approx([a+b for a,b in zip(row['original_slot_pose'][:2],row['axis_xy_correction_mm'])])
        assert row['pickup_pose'][2] == row['original_slot_pose'][2]
        assert row['pickup_pose'][4:] == row['original_slot_pose'][4:]
        assert row['axis_base_z_turn_deg'] == (90 if row['span'] in (1,3) else 0)


def test_startup_from_assembly_lifts_before_corridor_and_observation():
    value = config()
    current = [454., 86., 45., 123., -178., 124.]
    targets = trial.startup_targets(value, current, 'assembly')
    assert [label for label, _ in targets] == ['START_VERTICAL_LIFT', 'START_PLACE_HIGH',
        'START_BODY_BYPASS', 'START_SUPPLY_TRANSIT', 'START_OBSERVATION_HIGH']
    assert targets[0][1][:2] == current[:2]
    assert targets[0][1][3:] == current[3:]
    assert all(target[2] >= value['observation_pose'][2] for _, target in targets)
    assert targets[-1][1] == value['observation_pose']


def test_startup_already_at_view_skips_moves_and_high_start_lowers_last():
    value = config()
    assert trial.startup_targets(value, value['observation_pose'], 'supply') == []
    current = value['observation_pose'].copy(); current[2] += 20
    targets = trial.startup_targets(value, current, 'supply')
    assert targets[-1] == ('START_OBSERVATION_LOWER', value['observation_pose'])


def test_segment_rates_separate_rise_transit_descent_and_rotation():
    value = config()
    current = [1.,2.,50.,0.,180.,0.]
    assert trial.segment_rates(value, current, [1.,2.,374.,0.,180.,0.]) == (24.,48.)
    assert trial.segment_rates(value, current, [100.,2.,50.,0.,180.,0.]) == (120.,48.)
    assert trial.segment_rates(value, current, [1.,2.,40.,0.,180.,0.]) == (24.,48.)
    assert trial.segment_rates(value, current, [1.,2.,50.,90.,180.,0.]) == (120.,48.)
    assert value['angular_velocity'] == 6. and value['angular_acceleration'] == 3.


def test_box_center_selects_requested_class_and_keeps_competition_evidence(monkeypatch):
    import numpy as np
    from supply_vision import seg_backend
    layout=dict(image_size=[100,100], confidence=.3, slots=[dict(color='blue',brick_type='2x2x1',slot=3,roi_xyxy=[10,10,90,90],grasp_edge_pair=0)])
    detections=[dict(class_name='blue_2x3',confidence=.92,box=[20.,20.,60.,60.]),dict(class_name='blue_2x2',confidence=.68,box=[22.,22.,58.,58.])]
    monkeypatch.setattr(seg_backend,'infer_color_candidates',lambda *_: deepcopy(detections))
    report=trial.box_observation(np.zeros((100,100,3),np.uint8),None,layout,dict(slot_id='blue_2x2x1_03',color='blue',brick_type='2x2x1'),100)
    assert report['center_uv']==[40.,40.]
    assert report['competing_class_count']==1 and len(report['raw_detections'])==2
    assert report['slots'][0]['status']=='BOX_CENTER_CANDIDATE'
    assert not report['execution_allowed']


def test_two_expected_boxes_stay_ambiguous(monkeypatch):
    import numpy as np
    from supply_vision import seg_backend
    layout=dict(image_size=[100,100], confidence=.3, slots=[dict(color='red',brick_type='1x2x1',slot=5,roi_xyxy=[10,10,90,90],grasp_edge_pair=0)])
    detection=dict(class_name='red_2x1',confidence=.5,box=[20.,20.,40.,40.])
    monkeypatch.setattr(seg_backend,'infer_color_candidates',lambda *_: [deepcopy(detection),deepcopy(detection)])
    report=trial.box_observation(np.zeros((100,100,3),np.uint8),None,layout,dict(slot_id='red_1x2x1_05',color='red',brick_type='1x2x1'),100)
    assert report['center_uv'] is None
    assert report['slots'][0]['reason']=='multiple_detections'


def test_home_start_uses_existing_three_waypoints_in_reverse_then_supply_observation():
    c=config();c['integrated_cycle']=True;c['startup_route']['place_xy']=[472.,85.]
    current=[367.,4.,194.,90.,180.,90.]
    route=trial.startup_targets(c,current,'home')
    assert [name for name,_ in route]==['START_VERTICAL_LIFT','START_BODY_BYPASS','START_SUPPLY_TRANSIT','START_OBSERVATION_HIGH']
    assert [p[:2] for _,p in route[1:3]]==[c['startup_route']['body_bypass_xy'],c['startup_route']['supply_transit_xy']]
    assert route[-1][1]==c['observation_pose']
    assert all(p[2]==c['observation_pose'][2] for _,p in route)


@pytest.mark.parametrize('color,kind,slot,span,close', [
    ('yellow','2x2x1',4,2,35.),('blue','2x3x1',3,3,40.),('yellow','2x3x1',5,3,40.)])
@pytest.mark.parametrize('start_width', [49.9, 50., 55., 60.])
def test_explicit_trial_row_picks_exact_identity_without_changing_legacy_order(monkeypatch,color,kind,slot,span,close,start_width):
    value=config();events=[];commands=[];seen=[]
    row=dict(color=color,brick_type=kind,slot=slot,span=span,close_mm=close,
        pickup_pose=[-410.,slot*20.,50.,0.,180.,0.],pose_source='SYNTHETIC_TEST_ONLY')
    before=deepcopy(row)
    class Driver:
        def __init__(self):
            self.value=dict(posx=value['observation_pose'].copy(),velx=[0.]*6,motion_status=0,
                wrench=[0.]*6,query_duration_s=.01,tcp='GripperDA_v4',tool='ToolWeight0',
                gripper_status=0,gripper_width_mm=start_width,robot_state=1,robot_mode=1,drl_state=3)
        def sample(self):return deepcopy(self.value)
        def check_pose(self,target):return target
        def command_gripper(self,width,force):
            commands.append((width,force));self.value.update(gripper_status=2,gripper_width_mm=width)
        def stop(self):raise AssertionError('Successful explicit pick must not stop')
    driver=Driver()
    def move(d,connection,target,limit,record,**kwargs):d.value['posx']=target.copy()
    def observe(selected):seen.append(deepcopy(selected));return decision(selected)
    monkeypatch.setattr(trial,'run',move)
    if start_width < 50.:
        with pytest.raises(RuntimeError, match='START_WITH_OPEN_AT_LEAST_50MM'):
            trial.execute(driver,value,lambda event,data:events.append(event),observe,
                trial_row=row,hold_at_pickup=True,sleep=lambda _:None)
        assert commands == [] and seen == []
        assert driver.value['posx'] == value['observation_pose']
        return
    trial.execute(driver,value,lambda event,data:events.append(event),observe,
        trial_row=row,hold_at_pickup=True,sleep=lambda _:None)
    assert seen==[before] and row==before
    assert commands==[(close,value['gripper_force_n'])]
    assert driver.value['posx']==row['pickup_pose'] and driver.value['gripper_status']==2
    assert 'PICKUP_COMPLETE_HOLDING' in events and 'RELEASE_FEEDBACK' not in events
    assert [tuple(r[k] for k in ('color','brick_type','slot','span')) for r in value['blocks']]==trial.ORDER


@pytest.mark.parametrize('change,error', [
    ('above_view','OBSERVATION_MUST_BE_ABOVE_PICKUP'),('missing_source','EXACT_SLOT_AXIS_TEACHING_REQUIRED'),
    ('force','EXISTING_FORCE_LIMIT_EXCEEDED')])
def test_explicit_row_retains_existing_checks_before_accessing_driver(change,error):
    value=config();row=deepcopy(value['blocks'][0]);row['slot']=4
    if change=='above_view':row['pickup_pose'][2]=value['observation_pose'][2]
    if change=='missing_source':row['pose_source']=None
    if change=='force':value['force_stop_n']=46.
    class NoDevice:
        def sample(self):raise AssertionError('No device access before existing validation')
    with pytest.raises(ValueError,match=error):
        trial.execute(NoDevice(),value,lambda *_:None,lambda _:None,trial_row=row,hold_at_pickup=True)


@pytest.mark.parametrize('stale_after_vision',[False,True])
def test_target_only_supply_accepts_controller_stopped_pose_drift_but_rejects_stale_feedback(stale_after_vision):
    from app.assembly_step_runner import StepReplayDriver
    value=config();value.update(target_only_motion=True,motion_force_stop_n=None)
    class Replay(StepReplayDriver):
        def __init__(self):
            super().__init__([-400.,0.,-100.,0.,180.,0.])
            self.value.update(posx=value['observation_pose'].copy(),posj=[10.]*6,gripper_status=0,
                gripper_width_mm=60.,velx=[.002]*6)
            self.value['posx'][0]+=1.
        def check_pose(self,target):raise AssertionError('No numeric endpoint preflight for target-only trial')
        def call(self,*a,**kw):self.value['robot_mode']=1
        def move_line_async(self,target,velocity,acceleration):
            super().move_line_async(target,velocity,acceleration)
            self.value['posx'][0]+=1.;self.value['posx'][3]+=2.
    driver=Replay();events=[]
    def observe(row):
        assert max(trial.pose_error(driver.value['posx'],value['observation_pose']))>.5
        if stale_after_vision:driver.value['query_duration_s']=.8
        return decision(row)
    execute=lambda:trial.execute(driver,value,lambda event,data:events.append(event),observe,
        slot=1,hold_at_pickup=True,start_zone='home',sleep=lambda _:None)
    if stale_after_vision:
        with pytest.raises(RuntimeError,match='FEEDBACK_TOO_OLD'):execute()
        assert not driver.grips and driver.stops
    else:
        execute()
        assert driver.moves[-1]==value['blocks'][0]['pickup_pose']
        assert driver.value['posx'][0]==value['blocks'][0]['pickup_pose'][0]+1.
        assert driver.grips==[(35.,value['gripper_force_n'])] and 'PICKUP_COMPLETE_HOLDING' in events


def test_live_supply_camera_still_rejects_old_images_in_target_only_mode(monkeypatch):
    from types import SimpleNamespace
    camera=trial.LiveVision.__new__(trial.LiveVision)
    message=SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=0,nanosec=0)))
    camera.node=SimpleNamespace(get_clock=lambda:SimpleNamespace(now=lambda:SimpleNamespace(nanoseconds=1_000_000_000)))
    camera.ros=SimpleNamespace(spin_once=lambda *a,**kw:setattr(camera,'message',message))
    camera.display=lambda *a:None;camera.pump_sleep=lambda _:None
    camera.config=dict(target_only_motion=True)
    clock=iter([0.,1.,2.,3.,4.,6.]);monkeypatch.setattr(trial.time,'monotonic',lambda:next(clock))
    report=camera.observe(config()['blocks'][0])
    assert report['reason']=='NO_FRESH_RGB' and not report['inference_completed'] and not report['recognized']
