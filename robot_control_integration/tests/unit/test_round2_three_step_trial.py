"""Local three-cycle orchestration; synthetic observer outcomes are not physics."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import round2_three_step_trial as trial


IDENTITIES=[('yellow','2x2x1',4),('blue','2x3x1',3),('yellow','2x3x1',5)]


@pytest.fixture(scope='module')
def prepared_trial():
    scenario=trial.read(trial.DEFAULT)
    before=deepcopy(scenario)
    prepared=trial.prepare(scenario)
    assert scenario==before
    return scenario,prepared


def test_default_prepare_keeps_three_exact_sources_and_human_robot_trial_policy(prepared_trial):
    scenario,prepared=prepared_trial
    assert len(scenario['preplaced'])==8 and len(prepared)==3
    rows=[item['config']['blocks'][0] for item in prepared]
    assert [tuple(row[key] for key in ('color','brick_type','slot')) for row in rows]==IDENTITIES
    assert [item['case']['human_hold'] for item in prepared]==[False,False,True]
    assert prepared[1]['case']['original_blocked_layout_A']['mode']=='HUMAN_ASSEMBLY'
    assert prepared[1]['case']['raised_z_trial_mm']==0.
    assert prepared[1]['case']['previous_raised_z_trial_mm']==10.
    assert prepared[2]['case']['policy']=='USER_SELECTED_HOLD_LOWER_STRUCTURE'
    assert prepared[2]['case']['source_A']['assistance_kind']=='NONE'
    assert [item['reservation']['slot_id'] for item in prepared]==[
        'yellow_2x2x1_04','blue_2x3x1_03','yellow_2x3x1_05']
    assert [row['pose_basis'] for row in rows]==['INTERPOLATED','OPERATOR_RECORDED_CONTINUOUS_GRASP_PAIR','INTERPOLATED']
    assert all(row['axis_basis']=='ORIGINAL_TAUGHT_TWO_STUD_AXIS' for row in rows)
    for item,row in zip(prepared,rows):
        cfg=item['config']
        assert cfg['alignment_target']['target']==item['case']['target']
        assert cfg['trial_step']==item['case'] and not item['physical_accuracy_verified']
        assert cfg['alignment_approach_z_mm']==pytest.approx(cfg['alignment_target']['placement_tcp_reference'][2]+20.)
        assert cfg['same_xy_press'] and cfg['integrated_cycle']
        assert cfg['vision_xy_alignment']
        assert cfg['pad_contact_basis']==('OPERATOR_RECORDED_PAD_TO_LANDING_RIGID_RELATION'
            if item['case']['step_id']=='T2' else 'TRANSFERRED_HEIGHT_OFFSET_OPERATOR_TRIAL_NOT_NEW_MEASUREMENT')


def test_T2_installs_the_recorded_three_poses_without_another_plus10(prepared_trial):
    _,prepared=prepared_trial
    cfg=prepared[1]['config']
    assert cfg['blocks'][0]['pickup_pose'][2]==pytest.approx(50.55427551269531)
    assert cfg['alignment_target']['placement_tcp_reference'][:3]==pytest.approx(
        [503.7802734375,91.63031005859375,37.008758544921875])
    assert cfg['integrated_pad_contact_pose'][:3]==pytest.approx(
        [504.09613037109375,91.23787689208984,55.559078216552734])
    assert 'operator_raised_z_trial' not in cfg
    assert cfg['operator_teaching']['grasp_height_estimate_mm']==8.
    assert not cfg['operator_teaching']['grasp_height_independently_measured']
    assert cfg['alignment_use_recorded_attitude']


def test_visual_XY_correction_survives_I_and_keeps_fixed_block_pad_target(prepared_trial):
    from scripts.held_xy_seating_trial import seating_targets,same_xy_press_plan
    _,prepared=prepared_trial
    cfg=prepared[1]['config'];reference=cfg['alignment_target']['placement_tcp_reference']
    current=dict(posx=[*reference[:2],reference[2]+20.,*reference[3:]])
    candidate=dict(status='HELD_EDGE_XY_CANDIDATE',delta_base_xy_mm=[3.2,-4.1],physical_accuracy_verified=False)
    move,updated=trial.held.visual_xy_target(current,cfg,candidate)
    assert move[:2]==pytest.approx([reference[0]+3.2,reference[1]-4.1])
    target=seating_targets(dict(posx=move),updated)[0]
    assert target[:2]==move[:2] and target[2]==reference[2] and target[3:]==move[3:]
    assert updated['integrated_pad_contact_pose']==cfg['integrated_pad_contact_pose']
    assert same_xy_press_plan(target,updated)['estimated_contact_pose']==cfg['integrated_pad_contact_pose']
    assert cfg['alignment_target']['placement_tcp_reference']==reference


def test_recorded_landing_attitude_is_used_before_image_yaw(prepared_trial):
    _,prepared=prepared_trial
    cfg=prepared[1]['config'];reference=cfg['alignment_target']['placement_tcp_reference']
    current=dict(posx=[*reference[:2],cfg['pickup_clearance_z_mm'],9.,179.,10.])
    lower,_=trial.held.approach_cycle_targets(current,cfg)
    assert lower[3:]==reference[3:]


def test_replay_camera_runs_actual_stud_detector_for_all_three_requested_blocks(prepared_trial,tmp_path):
    _,prepared=prepared_trial
    for item,identity in zip(prepared,IDENTITIES):
        cfg=item['config'];row=cfg['blocks'][0]
        camera=trial.ReplayVision(trial.TrialReplay(),cfg,tmp_path)
        report=camera.observe(row)
        assert report['slot_id']==f'{identity[0]}_{identity[1]}_{identity[2]:02d}'
        assert report['recognized'] and report['inference_completed']
        assert report['provenance']=='SYNTHETIC_RGB'


def orchestration_replay(monkeypatch,prepared,tmp_path,stop_at=None,stop_status=None):
    """Run real supply/transport/open helpers, inject only camera/UI outcomes."""
    events=[];seen=[];zones=[];observed=[];support=[];finished=[];closed=[];terminal_moves=[]
    driver=trial.TrialReplay()
    class Vision:
        def __init__(self,driver,cfg,directory):self.step=cfg['trial_step']['step_id']
        def display(self,row,decision):pass
        def observe(self,row):
            seen.append(deepcopy(row))
            return dict(slot_id=f"{row['color']}_{row['brick_type']}_{row['slot']:02d}",
                vision_attempted=True,inference_completed=True,recognized=True,center_available=False,
                provenance='SYNTHETIC_UNIT_CAMERA',reason='UNIT_SEQUENCE_ONLY')
        def pump_sleep(self,duration):pass
        def close(self):closed.append(self.step)
    execute=trial.supply.execute
    def traced_execute(*args,**kwargs):
        zones.append(kwargs['start_zone']);return execute(*args,**kwargs)
    monkeypatch.setattr(trial.supply,'execute',traced_execute)
    def ready(cfg):support.append(cfg['trial_step']['step_id']);return True
    def observer(d,cfg,directory,record,**kwargs):
        index=len(observed);observed.append(cfg['trial_step']['step_id'])
        callback=kwargs['support_ready']
        assert (callback is not None)==cfg['trial_step']['human_hold']
        if callback is not None:assert callback(cfg)
        if index==stop_at:
            d.stop();terminal_moves.append(len(d.moves))
            return dict(status=stop_status,released=False,press_done=False,press_result=None,assembly_completion=False)
        # Emulate only the popup's final state, without claiming seating/contact physics.
        d.command_gripper(cfg['open_mm'],cfg['gripper_force_n'])
        d.command_gripper(4.,cfg['gripper_force_n'])
        d.value.update(posx=[*cfg['assembly_target_xy'],cfg['pickup_clearance_z_mm'],
            *cfg['alignment_target']['placement_tcp_reference'][3:]],wrench=[0.,0.,60.,0.,0.,0.])
        return dict(status='CYCLE_COMPLETED',released=True,press_done=True,
            press_result=dict(status='SYNTHETIC_UI_RESULT_ONLY'),assembly_completion=False)
    result=trial.run_sequence(driver,prepared,tmp_path,
        lambda event,data:events.append((event,deepcopy(data))),vision_factory=Vision,
        observe_cycle=observer,support_ready=ready,support_finished=lambda:finished.append(True),
        sleep=lambda _:None)
    return SimpleNamespace(result=result,driver=driver,events=events,seen=seen,zones=zones,
        observed=observed,support=support,finished=finished,closed=closed,terminal_moves=terminal_moves)


def test_three_cycles_use_one_driver_home_then_assembly_and_open_between_steps(monkeypatch,prepared_trial,tmp_path):
    _,prepared=prepared_trial
    replay=orchestration_replay(monkeypatch,prepared,tmp_path)
    ids=[item['case']['step_id'] for item in prepared]
    assert replay.result['status']=='THREE_CYCLES_COMPLETED' and replay.result['completed_steps']==ids
    assert replay.zones==['home','assembly','assembly']
    assert [tuple(row[k] for k in ('color','brick_type','slot')) for row in replay.seen]==IDENTITIES
    assert replay.observed==ids and replay.closed==ids and replay.support==[ids[2]]
    assert replay.finished==[True]
    opens=[data for event,data in replay.events if event=='NEXT_STEP_EMPTY_PAD_OPEN']
    assert len(opens)==2 and all(data['sample']['gripper_status']==2 for data in opens)
    assert all(data['sample']['gripper_width_mm']==9.2 for data in opens)
    begins=[data for event,data in replay.events if event=='THREE_STEP_BEGIN']
    assert [data['step']['step_id'] for data in begins]==ids
    assert all(data['source_A_preserved'] for data in begins)
    assert sum(event=='PICKUP_COMPLETE_HOLDING' for event,_ in replay.events)==3
    assert not replay.result['assembly_completion'] and not replay.result['current_update']


@pytest.mark.parametrize('stop_at',[0,1,2])
@pytest.mark.parametrize('status',['STOPPED_BY_OPERATOR','INCOMPLETE'])
def test_user_stop_or_incomplete_does_not_begin_the_next_pickup(monkeypatch,prepared_trial,tmp_path,stop_at,status):
    _,prepared=prepared_trial
    replay=orchestration_replay(monkeypatch,prepared,tmp_path,stop_at,status)
    ids=[item['case']['step_id'] for item in prepared]
    assert replay.result['status']=='SEQUENCE_STOPPED' and replay.result['result']['status']==status
    assert replay.result['completed_steps']==ids[:stop_at] and replay.result['stopped_step']==ids[stop_at]
    assert len(replay.seen)==stop_at+1 and replay.observed==ids[:stop_at+1]
    assert replay.closed==ids[:stop_at+1] and replay.finished==[]
    assert sum(event=='NEXT_STEP_EMPTY_PAD_OPEN' for event,_ in replay.events)==stop_at
    assert sum(event=='PICKUP_COMPLETE_HOLDING' for event,_ in replay.events)==stop_at+1
    assert len(replay.driver.moves)==replay.terminal_moves[0]
    assert not replay.result['assembly_completion'] and not replay.result['current_update']
