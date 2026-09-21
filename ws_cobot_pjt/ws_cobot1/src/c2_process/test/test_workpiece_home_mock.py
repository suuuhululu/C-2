"""홈 경유의 모델/호출 순서 검증. 실제 이동은 실행하지 않는다."""
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.workpiece_calibration import build_home_plan, build_top_plan, home_matches, measure_workpiece, MeasurementContext, MeasurementError
from c2_process.robot_adapter import posx_to_pose,apply_tool_offset,StepResult
from c2_process.workpiece_real_trial import check_trial_scene
from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter

ROOT=Path(__file__).resolve().parents[1]

def config(name='real_trial_0921'):
    return json.loads((ROOT/'config'/f'workpiece_{name}.json').read_text())

@pytest.mark.parametrize('native',[
    [329.028564453125,98.4632568359375,214.83985900878906,87.84613800048828,-179.9999542236328,42.846153259277344], # 실기 중단 위치의 수직 자세 유지
    [426.2233,.04564,243.8246,0.,180.,0.], # 직전 사용자의 윗면 시험 중단 위치
    [427.1273,155.9008,214.7045,0.,180.,0.], # 이전 8점 종료 위치
    [421.8,.1,264.4,0.,180.,0.], # 이미 홈
    [426.24,.047,330.,0.,180.,30.], # 상공, 다른 드릴 방향
])
def test_home_paths_use_checked_corridors(native):
    w=config()['workcell'];p=build_home_plan(w,posx_to_pose(native,w['tool_offset_m']))
    assert check_trial_scene(p,w,dict(posx=native))['path_checked']
    assert home_matches(w,p[-1]['target_pose'])


def test_side_near_surface_retracts_before_lifting():
    w=config()['workcell'];cx,cy=w['seed_axis_xy_m'];r=w['seed_radius_m']
    tcp=[(cx+.00085)*1000,(cy+r+.09955+.0004)*1000,214.7,0,180,0]
    p=build_home_plan(w,posx_to_pose(tcp,w['tool_offset_m']))
    assert [x['label'] for x in p[:3]]==['home_escape_slow','home_escape_outer','home_lift']
    assert check_trial_scene(p,w,dict(posx=tcp))['path_checked']


def test_unknown_low_pose_is_not_guessed_safe():
    w=config()['workcell'];tcp=[426.24,50.,200.,0,180,0]
    with pytest.raises(MeasurementError,match='自|자동'):
        build_home_plan(w,posx_to_pose(tcp,w['tool_offset_m']))


def test_home_failure_blocks_probe_and_stops():
    c=config('simulation');ctx=MeasurementContext('home-test','prepare','SIMULATION')
    ad=SimulatedWorkpieceAdapter(c['workcell'],clock=ctx.monotonic)
    original=ad.execute_measurement_step
    def fail(step,*args):
        if step['label']=='home_x':return StepResult('FAILED','TEST_HOME_FAILED')
        return original(step,*args)
    ad.execute_measurement_step=fail
    r=measure_workpiece(ad,c['workcell'],c['profiles'],ctx)
    assert r.error_code=='TEST_HOME_FAILED' and r.observed_state['stop_confirmed']
    assert not any(k=='execute' and step['kind']=='PROBE' for k,step in ad.calls)


def test_already_home_is_verified_before_top():
    c=config('simulation');ctx=MeasurementContext('home-test','prepare','SIMULATION')
    ad=SimulatedWorkpieceAdapter(c['workcell'],clock=ctx.monotonic)
    ad.pose=apply_tool_offset(c['workcell']['home']['tcp_pose'],c['workcell']['tool_offset_m'])
    events=[];r=measure_workpiece(ad,c['workcell'],c['profiles'],ctx,events.append)
    assert r.ok
    assert r.observed_state['home_move_skipped'] is True
    assert not any(k=='execute' and step['label'].startswith('home_') for k,step in ad.calls)
    assert [e['stage'] for e in events].index('HOME_READY')<[e['stage'] for e in events].index('TOP_APPROACH')
    assert home_matches(c['workcell'],r.observed_state['home_state']['tip_pose'])


def test_home_then_top_entry_passes_model():
    w=config()['workcell'];native=[426.2233,.04564,243.8246,0,180,0]
    plan=build_home_plan(w,posx_to_pose(native,w['tool_offset_m']))
    plan+=build_top_plan(w,plan[-1]['target_pose'])
    assert check_trial_scene(plan,w,dict(posx=native))['path_checked']


def test_inside_home_tolerance_never_sends_home_move():
    c=config('simulation');ctx=MeasurementContext('home-tolerance','prepare','SIMULATION')
    ad=SimulatedWorkpieceAdapter(c['workcell'],clock=ctx.monotonic)
    tcp=c['workcell']['home']['tcp_pose'][:];tcp[0]+=.0002
    ad.pose=apply_tool_offset(tcp,c['workcell']['tool_offset_m'])
    r=measure_workpiece(ad,c['workcell'],c['profiles'],ctx)
    assert r.ok and r.observed_state['home_move_skipped']
    assert not any(k=='execute' and step['label'].startswith('home_') for k,step in ad.calls)


def test_measured_home_negative_179_99_does_not_flip_in_top_plan():
    w=config()['workcell']
    current=[421.692291,.110563926,264.339752,.928778,-179.9901886,.927056]
    p=build_top_plan(w,posx_to_pose(current,w['tool_offset_m']))
    assert check_trial_scene(p,w,dict(posx=current))['path_checked']


@pytest.mark.parametrize('native,q6',[
    ([524.65,-99.56,214.91,0.,180.,135.],-236.5),
    (None,-314.5),
])
def test_home_rotation_avoids_extra_winding_after_side_orbit(native,q6):
    import math
    from c2_process.robot_adapter import tool_axis_in_base
    w=config()['workcell']
    if native is None:
        from c2_process.workpiece_calibration import facing_pose
        from c2_process.robot_adapter import pose_to_posx
        native=pose_to_posx(facing_pose(w['seed_axis_xy_m'],w['seed_radius_m']+w['outer_gap_m'],.21491,405),w['tool_offset_m'])
    tip=posx_to_pose(native,w['tool_offset_m'])
    plan=build_home_plan(w,tip,[0,0,1,0,1.5,math.radians(q6)])
    assert check_trial_scene(plan,w,dict(posx=native))['path_checked']
    angles=[]
    for step in plan:
        if step['label'] in ('home_lift','home_align'):
            axis=tool_axis_in_base(step['target_pose'],'+y')
            angles.append(math.degrees(math.atan2(axis[1],axis[0])))
    changes=[(b-a+180)%360-180 for a,b in zip(angles,angles[1:])]
    assert all(abs(a)<=90.001 for a in changes)
    predicted=q6-sum(changes)
    assert abs(predicted)<90
    from c2_process.workpiece_calibration import rotation_distance
    for a,b in zip(plan,plan[1:]):
        x,y=a['target_pose'],b['target_pose']
        assert math.dist(x[:3],y[:3])>1e-9 or rotation_distance(x,y)>1e-7
    assert home_matches(w,plan[-1]['target_pose'])


def test_home_already_clear_uses_outward_profile_without_contact_retract():
    from c2_process.workpiece_calibration import facing_pose, build_side_plan
    w=config()['workcell']
    tip=facing_pose(w['seed_axis_xy_m'],w['seed_radius_m']+.007,.21491,315)
    plan=build_home_plan(w,tip)
    assert plan[0]['label']=='home_escape_outer'
    assert plan[0]['profile']=='escape'
    side=build_side_plan(w,.23491)
    assert all(s['profile']=='escape' for s in side if s['label'].endswith('_outer'))
    assert all(s['profile']=='retract' for s in side if s['label'].endswith('_retract'))


def test_start_near_top_retracts_with_contact_profile_before_air_lift():
    w=config()['workcell'];cx,cy=w['seed_axis_xy_m']
    native=[cx*1000,cy*1000,234.7,0.,180.,0.]
    plan=build_home_plan(w,posx_to_pose(native,w['tool_offset_m']))
    assert [s['profile'] for s in plan[:2]]==['retract','travel']
    assert check_trial_scene(plan,w,dict(posx=native))['path_checked']
