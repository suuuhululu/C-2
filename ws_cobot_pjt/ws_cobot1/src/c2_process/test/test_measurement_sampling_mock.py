"""공중 IK 간격의 경계 검사. ROS/실기 명령을 실행하지 않는다."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.measurement_robot_adapter import GuardedMeasurementAdapter, ik_sample_indices
from test_measurement_robot_adapter_mock import setup


def inputs():
    guards=dict(ik_step_mm=2.,ik_step_deg=1.,air_ik_step_mm=4.,air_ik_step_deg=2.,max_samples_per_segment=1000)
    w=dict(tool_offset_m=[0.,0.,0.],seed_axis_xy_m=[0.,0.],seed_radius_m=.034,
           trial_scene=dict(overhead_clearance_z_m=.3,outer_min_gap_m=.018,model_tolerance_m=.0005))
    step=dict(kind='MOVE',profile='travel',label='orbit')
    return guards,w,step


def test_air_selects_existing_points_and_keeps_endpoint():
    g,w,step=inputs()
    n,selected=ik_sample_indices([0,0,330,0,180,0],[10,0,330,0,180,5],step,w,g)
    assert n==5 and selected==[2,4,5]
    g.pop('air_ik_step_mm');g.pop('air_ik_step_deg')
    assert ik_sample_indices([0,0,330,0,180,0],[10,0,330,0,180,5],step,w,g)==(5,[1,2,3,4,5])


@pytest.mark.parametrize('kind,profile,label',[
    ('PROBE','side_touch','point_1_touch'),('MOVE','approach','point_1_approach'),
    ('MOVE','retract','point_1_retract'),('MOVE','retract','home_lift'),
    ('MOVE','travel','unknown'),('MOVE','travel','top_exit')])
def test_contact_and_unclassified_steps_keep_dense_grid(kind,profile,label):
    g,w,step=inputs();step.update(kind=kind,profile=profile,label=label)
    assert ik_sample_indices([0,0,330,0,180,0],[12,0,330,0,180,0],step,w,g)==(6,list(range(1,7)))


def test_outer_retreat_stays_dense_until_shaft_is_separated():
    g,w,step=inputs();step.update(label='point_1_outer',profile='escape')
    n,selected=ik_sample_indices([36,0,200,0,180,0],[60,0,200,0,180,0],step,w,g)
    assert n==12 and selected==list(range(1,10))+[11,12]
    assert set(range(1,9))<=set(selected)


def test_shaft_crossing_candle_is_not_air_even_if_both_ends_are_outside():
    g,w,step=inputs();w['tool_offset_m']=[0.,-.1,0.]
    # TCP y=50mm, 끝점 y=-50mm: 양 끝은 바깥이어도 선분은 원통을 통과.
    assert ik_sample_indices([0,50,200,0,180,0],[10,50,200,0,180,0],step,w,g)==(5,[1,2,3,4,5])


@pytest.mark.parametrize('value',[True,float('nan'),0.,5.])
def test_invalid_air_interval_rejected(setup,value):
    ad,io,ctx,c,step,clock=setup;g=deepcopy(ad.g);g['air_ik_step_mm']=value
    with pytest.raises(ValueError,match='공중 IK 간격'):
        GuardedMeasurementAdapter(io,ad.offset,g,ad.readiness,ad.scene_check)


def test_air_sampling_keeps_joint_guard_and_cancel(setup):
    from c2_process.workpiece_calibration import MeasurementError
    from c2_process.robot_adapter import posx_to_pose
    ad,io,ctx,c,step,clock=setup
    ad.g.update(air_ik_step_mm=4.,air_ik_step_deg=2.)
    c['workcell']['trial_scene']=inputs()[1]['trial_scene']
    io.p[2]=330.;step['target_pose']=posx_to_pose([436.,100.,330.,0.,180.,170.],ad.offset)
    before=deepcopy(step)
    result=ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    assert result.ok and ad.last_preflight_metrics['dense_samples']==5
    assert ad.last_preflight_metrics['samples']==3 and ad.last_preflight_metrics['skipped_air_samples']==2
    assert step==before and not io.moves
    io.ik=lambda *args:[0.,20.,60.,0.,90.,20.]
    with pytest.raises(MeasurementError,match='불연속'):
        ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    ctx.cancel.set()
    with pytest.raises(MeasurementError,match='취소'):
        ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    assert not io.moves


@pytest.mark.parametrize('tracking_mm,unstable_force,allowed',[
    (.04,False,True),(.06,False,False),(.04,True,False)])
def test_baseline_tracking_option_keeps_force_window_and_tracking_gate(setup,tracking_mm,unstable_force,allowed):
    from c2_process.robot_adapter import posx_to_pose
    ad,io,ctx,c,_,clock=setup
    ad.g['baseline_tracking_position_m']=.00005
    assert ad.g['skip_position_m']==.00002
    start=posx_to_pose(io.p,ad.offset);end=start[:];end[2]-=.0055
    step=dict(kind='PROBE',start_pose=start,target_pose=end,direction=[0.,0.,-1.],max_m=.0055,
              profile='top_touch',label='top_touch',point_index=0)
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    original=io.read;calls=0
    def read():
        nonlocal calls
        calls+=1;o=original();o['desired_posx']=o['posx'][:];o['desired_posx'][0]+=tracking_mm
        if unstable_force:o['force_n']=[0.,0.,1. if calls%2 else -1.]
        return o
    def move(*args):raise RuntimeError('BASELINE_READY')
    io.read=read;io.move=move
    expected='BASELINE_READY' if allowed else ('기준 힘 안정화 실패' if unstable_force else '실제/지시 TCP 정착 미확인')
    with pytest.raises(Exception,match=expected):
        ad.execute_measurement_step(step,c['profiles']['top_touch'],ctx,60)
    assert clock()>=c['profiles']['top_touch']['baseline_window_s']
    if not allowed:assert clock()>=ad.g['baseline_timeout_s']
    assert not io.moves


@pytest.mark.parametrize('value',[True,float('nan'),0.,.0002])
def test_invalid_baseline_tracking_option(setup,value):
    ad,io,ctx,c,_,clock=setup;g=deepcopy(ad.g);g['baseline_tracking_position_m']=value
    with pytest.raises(ValueError,match='위치 정착 허용폭'):
        GuardedMeasurementAdapter(io,ad.offset,g,ad.readiness,ad.scene_check)
