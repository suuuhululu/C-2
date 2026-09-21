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
