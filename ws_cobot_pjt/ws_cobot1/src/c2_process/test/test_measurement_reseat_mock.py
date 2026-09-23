"""기하·가감속·힘 가짜 I/O로 재장착 오차를 재현. 실기 검증 아님."""
import json, math
from copy import deepcopy
from pathlib import Path
import pytest
from test_workpiece_guarded_flow_mock import Clock, KinematicIO, SimulatedGuardedAdapter
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece, side_contact_window, build_side_plan
from c2_process.workpiece_real_trial import check_trial_scene
from c2_process.robot_adapter import posx_to_pose


def run_case(shift=(0.,0.), scenario=None, config_edit=None):
    config=json.loads((Path(__file__).resolve().parents[1]/'config/workpiece_real_trial_0921.json').read_text())
    w=config['workcell'];w['source_mode']='SIMULATION'
    if config_edit:config_edit(config)
    clock=Clock();io=KinematicIO(w,clock,True)
    io.center=[a+b for a,b in zip(w['seed_axis_xy_m'],shift)];io.radius=w['seed_radius_m']
    ctx=MeasurementContext('reseat','prepare','SIMULATION',monotonic=clock)
    def ready(c):return dict(ownership_confirmed=True,control_authority=True,measurement_id=c.measurement_id,checked_at_monotonic_s=clock())
    ad=SimulatedGuardedAdapter(io,w['tool_offset_m'],config['guards'],ready,check_trial_scene,clock=clock,sleep=clock.sleep)
    raw_read=io.read;raw_execute=ad.execute_measurement_step;active_step=None;logs=[]
    ad.trace=lambda event,data:logs.append((event,deepcopy(data)))
    def execute(step,*args):
        nonlocal active_step
        active_step=step
        io.radius=w['seed_radius_m']+(.0015 if scenario=='outlier' and step.get('point_index')==4 else (.0002 if scenario=='larger_candle' else 0.))
        return raw_execute(step,*args)
    ad.execute_measurement_step=execute
    def read():
        result=raw_read()
        if active_step and active_step['kind']=='PROBE' and active_step.get('point_index')==2:
            if scenario=='baseline_large':result['force_n']=[20.,0.,0.]
            if scenario=='obstacle' and io.active:
                tip=posx_to_pose(result['posx'],w['tool_offset_m'])
                travel=sum((tip[k]-active_step['start_pose'][k])*active_step['direction'][k] for k in range(3))
                if travel>=.001:
                    result['force_n']=[result['force_n'][k]-active_step['direction'][k] for k in range(3)]
        return result
    io.read=read
    def feedback(event):
        if scenario=='slip' and event['stage']=='SIDE_TOUCH' and event['status']=='SUCCEEDED' and event['point_index']==4:
            io.center[0]+=.002
    result=measure_workpiece(ad,w,config['profiles'],ctx,feedback)
    return result,io,logs,config


@pytest.mark.parametrize('shift',[(0.,0.),(-.00127,.00127),(.0018,0.),(-.0018,0.)])
def test_eight_points_accept_stationary_initial_shift(shift):
    r,io,logs,c=run_case(shift)
    assert r.ok,(r.error_code,r.message)
    m=r.observed_state['measurement']
    assert len(m['points'])==8 and m['axis_xy_m']==pytest.approx(io.center,abs=.00004)
    assert r.observed_state['home_return_confirmed']
    commands=[d['step'] for e,d in logs if e=='command' and d['step']['profile']=='side_touch']
    assert len(commands)==8
    assert all(s['max_m']==pytest.approx(.0115) for s in commands)
    baselines=[d for e,d in logs if e=='moving_baseline' and d['label'].startswith('point_')]
    assert len(baselines)==8
    assert all(d['travel_m']<side_contact_window(c['workcell'])[0] for d in baselines)


def test_excess_center_shift_fails_final_geometry():
    r,io,logs,c=run_case((.0026,0.))
    assert not r.ok and r.error_code=='INVALID_MEASUREMENT',(r.error_code,r.message)
    assert r.observed_state['stop_confirmed']


def test_obstacle_before_window_fails_without_next_point():
    r,io,logs,c=run_case(scenario='obstacle')
    assert r.error_code=='CONTACT_OUT_OF_RANGE' and '빈 공간' in r.message
    assert len(r.observed_state['measurement']['points'])==1
    assert r.observed_state['stop_confirmed']
    assert not any(e=='command' and d['step']['label']=='point_3_touch' for e,d in logs)


def test_overlap_is_rejected_before_motion():
    def edit(c):c['workcell']['start_gap_m']=.0065
    r,io,logs,c=run_case(config_edit=edit)
    assert not r.ok and '중첩' in r.message and not io.moves


def test_motion_during_measurement_not_treated_as_initial_shift():
    r,io,logs,c=run_case(scenario='slip')
    assert not r.ok and r.error_code=='INVALID_MEASUREMENT',(r.error_code,r.message)
    assert r.observed_state['stop_confirmed']


def test_one_bad_point_fails_circle_residual():
    r,io,logs,c=run_case(scenario='outlier')
    assert not r.ok and r.error_code=='RECOVERY_REQUIRED',(r.error_code,r.message)
    assert r.observed_state['point_attempts'][4]==3
    assert r.observed_state['rejected_fit']['residual_max_m']>c['workcell']['max_fit_residual_m']


def test_large_baseline_is_not_zeroed_out():
    r,io,logs,c=run_case(scenario='baseline_large')
    assert r.error_code=='FORCE_LIMIT' and r.observed_state['stop_confirmed']
    assert not any(e=='command' and d['step']['label']=='point_2_touch' for e,d in logs)


def test_planned_intervals_and_retreat():
    _,_,_,c=run_case();w=c['workcell'];steps=build_side_plan(w,.215)
    assert side_contact_window(w)==pytest.approx([.0047,.0113])
    assert c['guards']['moving_baseline_end_m']+c['guards']['max_state_age_s']*c['profiles']['side_touch']['speed_m_s']<.0047
    for s in steps:
        if s['label'].endswith('_retract'):
            assert math.dist(s['target_pose'][:2],w['seed_axis_xy_m'])-w['seed_radius_m']==pytest.approx(.005)


def test_old_overlap_reproduces_unstable_baseline_at_real_contact():
    def edit(c):
        w=c['workcell'];w['side_contact_window_enabled']=False;w['side_point_max_attempts']=1
        w.update(start_gap_m=.005,inside_limit_m=.0005,slow_retract_gap_m=.002)
    r,io,logs,c=run_case((-.002/math.sqrt(2),.002/math.sqrt(2)),scenario='larger_candle',config_edit=edit)
    assert not r.ok and r.error_code=='UNSTABLE_BASELINE',(r.error_code,r.message)


def test_same_second_point_reproduction_succeeds_with_separated_window():
    r,io,logs,c=run_case((-.00198/math.sqrt(2),.00198/math.sqrt(2)),scenario='larger_candle')
    assert r.ok,(r.error_code,r.message)
    assert len(r.observed_state['measurement']['points'])==8
    p=r.observed_state['measurement']['points'][1]['tip_pose']
    assert math.dist(p[:2],io.center)==pytest.approx(io.radius,abs=.00004)


def test_legacy_real_configuration_is_not_silently_accepted():
    c=json.loads((Path(__file__).resolve().parents[1]/'config/workpiece_real_trial_0921.json').read_text())
    w=c['workcell'];w.pop('side_contact_window_enabled');w.update(start_gap_m=.005,inside_limit_m=.0005,slow_retract_gap_m=.002)
    from c2_process.workpiece_calibration import _validate
    ctx=MeasurementContext('real-config','prep','REAL')
    with pytest.raises(ValueError,match='범위 부족'):_validate(w,c['profiles'],ctx)
