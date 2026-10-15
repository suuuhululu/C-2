"""Reviewed location-specific jaw commands with synthetic device feedback only."""
from copy import deepcopy

import pytest

from app import round3_stack_five as stack


def test_all_25_prepared_slots_separate_assembly_supply_and_red_grasp():
    cases=[]
    for color,kind in [('yellow','2x2x1'),('yellow','2x3x1'),('blue','2x2x1'),
                       ('blue','2x3x1'),('red','1x2x1')]:
        for slot in range(1,6):
            cases.append(dict(step_id=f'JAW{len(cases)+1:02d}',supply_slot=slot,human_hold=False,
                target=dict(color=color,brick_type=kind,x=13,y=11,layer=1,orientation_deg=0)))
    prepared=stack.prepare_scenario(dict(preplaced=[],steps=cases,free_motion_speed_scale=2.))
    for item in prepared:
        cfg=item['config'];row=cfg['blocks'][0]
        assert cfg['open_mm']==53. and cfg['open_feedback_range_mm']==[40.,80.]
        assert cfg['release_width_mm']==47. and cfg['release_feedback_range_mm']==[32.,55.]
        assert cfg['seating_force_stop_n']==50. and cfg['press_force_stop_n']==60.
        assert cfg['press_force_abort_n']==70. and cfg['seating_velocity']==cfg['press_velocity']==3.
        if row['color']=='red':
            assert row['close_mm']==20. and row['grip_feedback_range_mm']==[10.,40.] and row['span']==1
        else:
            assert row['close_mm']==35. and 'grip_feedback_range_mm' not in row


@pytest.mark.parametrize('feedback,grip_status,open_feedback,accepted',[
    (10.,2,None,True),(25.,2,None,True),(40.,2,None,True),
    (9.9,2,None,False),(40.1,2,None,False),(float('nan'),2,None,False),
    (25.,0,None,False),(25.,1,None,False),
    (25.,2,40.,True),(25.,2,80.,True),(25.,2,39.9,False),(25.,2,80.1,False)])
def test_supply_red_grasp_and_nonassembly_release_bounds(monkeypatch,feedback,grip_status,open_feedback,accepted):
    trial=stack.native().supply
    cfg=trial.load_config(trial.DEFAULT)
    cfg.update(open_mm=53.,open_feedback_range_mm=[40.,80.])
    row=cfg['blocks'][-1]
    row.update(pickup_pose=[-400.,0.,50.,0.,180.,0.],pose_source='SYNTHETIC_TEST_ONLY',
               close_mm=20.,grip_feedback_range_mm=[10.,40.])
    class Driver:
        def __init__(self):
            self.value=dict(posx=cfg['observation_pose'].copy(),velx=[0.]*6,motion_status=0,
                wrench=[0.]*6,query_duration_s=.01,tcp='GripperDA_v4',tool='ToolWeight0',
                gripper_status=0,gripper_width_mm=53.,robot_state=1,robot_mode=1,drl_state=3)
            self.grips=[];self.stops=0
        def sample(self):return deepcopy(self.value)
        def check_pose(self,target):return target
        def command_gripper(self,width,force):
            self.grips.append(width)
            self.value.update(gripper_status=grip_status if width==20. else 0,
                              gripper_width_mm=feedback if width==20. else open_feedback)
        def stop(self):self.stops+=1
    driver=Driver();events=[];now=[0.]
    def move(d,connection,target,*args,**kwargs):d.value['posx']=target.copy()
    monkeypatch.setattr(trial,'run',move)
    def sleep(seconds):now[0]+=seconds
    def execute():
        return trial.execute(driver,cfg,lambda e,d:events.append((e,d)),
            lambda r:dict(slot_id='red_1x2x1_05',recognized=False,reason='EXPLICIT_MOCK'),
            trial_row=row,start_zone='supply',hold_at_pickup=open_feedback is None,sleep=sleep,clock=lambda:now[0])
    if accepted:
        execute()
        expected_event='PICKUP_COMPLETE_HOLDING' if open_feedback is None else 'TRIAL_COMPLETE'
        assert any(e==expected_event for e,d in events) and driver.stops==0
    else:
        with pytest.raises(TimeoutError,match='FEEDBACK_TIMEOUT'):execute()
        assert not any(e=='PICKUP_COMPLETE_HOLDING' for e,d in events) and driver.stops==1
    assert driver.grips==([20.] if open_feedback is None else [20.,53.])


@pytest.mark.parametrize('bounds,command', [([32.,55.],47.),([40.,80.],53.)])
def test_release_helper_keeps_both_reviewed_endpoints(bounds,command):
    stack.native()
    from app.assembly_step_bridge import release_feedback_range
    from scripts.supply_pick_release_trial import width_in_range
    actual=release_feedback_range(dict(release_feedback_range_mm=bounds),command)
    assert actual==bounds
    for width,expected in [(bounds[0],True),(50.3,True),(bounds[1],True),
                           (bounds[0]-.1,False),(bounds[1]+.1,False),(float('nan'),False)]:
        assert width_in_range(dict(gripper_width_mm=width),actual) is expected
