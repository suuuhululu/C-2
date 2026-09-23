"""탐색 전 비접촉 baseline, 10 mm 전체 접촉, 시작점 후퇴 시험. 실기 검증 아님."""
from copy import deepcopy
from pathlib import Path
import json, math
import pytest
from test_workpiece_guarded_flow_mock import Clock, KinematicIO, SimulatedGuardedAdapter
from test_measurement_point_retry_mock import trial
from c2_process.workpiece_calibration import MeasurementContext, MeasurementError, build_side_plan, side_center_limit
from c2_process.robot_adapter import posx_to_pose, pose_to_posx
from c2_process.workpiece_real_trial import check_trial_scene


def probe(depth=.005, fault=None):
    cfg=json.loads((Path(__file__).resolve().parents[1]/'config/workpiece_real_trial_0921.json').read_text())
    w=cfg['workcell'];w['source_mode']='SIMULATION';clock=Clock();io=KinematicIO(w,clock,True)
    plan=build_side_plan(w,.215);step=next(s for s in plan if s.get('point_index')==1)
    io.p=pose_to_posx(step['start_pose'],w['tool_offset_m']);io.radius=0.
    ctx=MeasurementContext('presearch','preparation','SIMULATION',monotonic=clock)
    bad=False
    def ready(c):return dict(ownership_confirmed=True,control_authority=not bad,measurement_id=c.measurement_id,checked_at_monotonic_s=clock())
    ad=SimulatedGuardedAdapter(io,w['tool_offset_m'],cfg['guards'],ready,check_trial_scene,clock=clock,sleep=clock.sleep)
    ad.preflight_measurement([step],w,cfg['profiles'],ctx)
    traces=[];ad.trace=lambda e,d:traces.append((e,deepcopy(d)))
    original=io.read
    def read():
        nonlocal bad
        result=original()
        if io.active:
            current=posx_to_pose(result['posx'],w['tool_offset_m'])
            travel=sum((current[k]-step['start_pose'][k])*step['direction'][k] for k in range(3))
            delta=1. if depth is not None and travel>=w['side_baseline_lead_in_m']+depth else 0.
            if fault=='transient' and .00006<=travel<=.0003:delta=.966
            # 9/23 실기: 이동 시작과 함께 생기는 일정 오프셋(옆면 1.65 N)은 장애물이 아니라
            # 힘 추정 오차다. 실제 장애물은 단단하면 즉시 크게(hard_obstacle),
            # 밀리는 것이면 파고들수록(soft_obstacle) 힘이 오른다.
            if fault=='constant_offset' and travel>=.00006:delta+=1.65  # 표면 접촉 위에 더해진다
            if fault=='hard_obstacle' and travel>=.00006:delta=6.
            if fault=='soft_obstacle' and travel>=.00006:delta=500.*travel
            if fault=='before_search' and travel>=w['side_baseline_lead_in_m']-.00015:delta=1.
            result['force_n']=[v-delta*d for v,d in zip([1.,2.,3.],step['direction'])]
            if travel>.00006:
                if fault=='absolute':result['force_n']=[20.,0.,0.]
                if fault=='protection':result['robot_state']=3
                if fault=='communication':raise ConnectionError('통신 미확인')
                if fault=='authority':bad=True
                if fault=='deviation':result['posx'][0]+=.5
        return result
    io.read=read
    try: result=ad.execute_measurement_step(step,cfg['profiles']['side_touch'],ctx,60.)
    except Exception as e:result=e
    return result,traces,step,w,io


@pytest.mark.parametrize('depth',[.0001,.003,.008,.0099])
def test_contact_anywhere_inside_search_is_accepted(depth):
    r,traces,step,w,io=probe(depth)
    assert not isinstance(r,Exception),str(r)
    assert r.ok and r.observed_state['stop_confirmed']
    hit=r.observed_state['contact']['tip_pose']
    travel=sum((hit[k]-step['search_start_pose'][k])*step['direction'][k] for k in range(3))
    assert travel==pytest.approx(depth,abs=.00004)
    baseline=[d for e,d in traces if e=='moving_baseline']
    assert len(baseline)==1 and baseline[0]['travel_m']<w['side_baseline_lead_in_m']
    assert len([1 for e,d in traces if e=='command'])==1
    assert len(io.moves)==1  # baseline과 탐색 사이 정지·재가속 명령 없음
    assert not any(e.startswith('early_contact_candidate') for e,d in traces)


def test_startup_transient_is_excluded_from_presearch_baseline():
    r,traces,_,_,_=probe(fault='transient')
    assert not isinstance(r,Exception) and r.ok
    baseline=next(d for e,d in traces if e=='moving_baseline')
    assert baseline['bias_n']==pytest.approx(-2.)


def test_presearch_obstacle_is_not_absorbed_into_baseline():
    """탐색 시작 전 비접촉 구간에서 잡힌 접촉은 그대로 거절한다 (기존 계약 유지)."""
    r,traces,_,_,_=probe(fault='before_search')
    assert isinstance(r,MeasurementError) and r.code=='CONTACT_OUT_OF_RANGE'
    assert not any(e=='search_entered' for e,d in traces)


@pytest.mark.parametrize('fault,code,retryable',[
    ('hard_obstacle','FORCE_LIMIT',False),      # 빈 공간 힘 한계 5 N
    ('soft_obstacle','UNSTABLE_BASELINE',True), # 이동 기준힘 MAD/drift
])
def test_real_obstacle_in_the_lead_in_still_stops_the_probe(fault,code,retryable):
    """장애물은 '일정한 크기'가 아니라 '힘이 오르는 모양'으로 잡는다.

    9/23 실기에서 일정 오프셋은 정상 신호로 확인됐으므로, 크기만으로 거절하지 않는다.
    """
    r,traces,_,_,_=probe(fault=fault)
    assert isinstance(r,MeasurementError) and r.code==code
    assert not any(e=='search_entered' for e,d in traces)
    assert not any(e=='moving_baseline' for e,d in traces)
    assert (type(r).__name__=='PointMeasurementError')==retryable


def test_constant_motion_offset_is_absorbed_into_the_moving_baseline():
    """9/23 실기 파형(옆면 1.65 N): 이동 중 일정 오프셋은 기준힘이 흡수하고 측정은 계속된다."""
    r,traces,step,w,_=probe(fault='constant_offset')
    assert not isinstance(r,Exception),str(r)
    assert r.ok and r.observed_state['stop_confirmed']
    baseline=next(d for e,d in traces if e=='moving_baseline')
    assert baseline['travel_m']<w['side_baseline_lead_in_m']
    assert any(e=='search_entered' for e,d in traces)
    hit=r.observed_state['contact']['tip_pose']
    travel=sum((hit[k]-step['search_start_pose'][k])*step['direction'][k] for k in range(3))
    assert travel==pytest.approx(.005,abs=.00005)   # 주입한 표면 위치를 그대로 찾는다


def test_no_contact_by_end_is_not_a_success():
    r,traces,step,_,_=probe(depth=None)
    assert isinstance(r,MeasurementError) and r.code=='CONTACT_NOT_FOUND'
    assert step['max_m']==pytest.approx(.01405)


@pytest.mark.parametrize('fault,code',[('absolute','FORCE_LIMIT'),('protection','NOT_READY'),('authority','NOT_READY'),('deviation','CONTACT_OUT_OF_RANGE')])
def test_existing_guards_still_stop_before_search(fault,code):
    r,*_=probe(fault=fault)
    assert isinstance(r,MeasurementError) and r.code==code


def test_communication_failure_is_not_converted_to_contact():
    r,*_=probe(fault='communication')
    assert isinstance(r,ConnectionError)


def test_plan_retreat_is_outward_for_every_possible_contact():
    _,_,_,w,_=probe()
    plan=build_side_plan(w,.215)
    for p in [s for s in plan if s['kind']=='PROBE']:
        retreat=next(s for s in plan if s['label']==f"point_{p['point_index']}_retract")
        assert retreat['target_pose']==p['start_pose']
        assert math.dist(p['search_start_pose'][:3],p['target_pose'][:3])==pytest.approx(.01)
        for distance in [.0001,.003,.008,.0099]:
            hit=[p['search_start_pose'][k]+distance*p['direction'][k] for k in range(3)]
            assert sum((retreat['target_pose'][k]-hit[k])*p['direction'][k] for k in range(3))<0
    assert side_center_limit(w)==pytest.approx(.0037)


@pytest.mark.parametrize('scenario',['baseline','moving_baseline'])
def test_quality_remeasurement_still_finishes_eight_points(scenario):
    r,attempts,steps,_,_=trial(scenario,before_search=True)
    assert r.ok,(r.error_code,r.message)
    assert attempts[2]==2 and len(r.observed_state['measurement']['points'])==8


def test_repeated_quality_failure_uses_same_point_budget():
    r,attempts,steps,_,_=trial('baseline_repeat',before_search=True)
    assert r.error_code=='RECOVERY_REQUIRED' and attempts[2]==3 and attempts[3]==0
    assert r.observed_state['stop_confirmed']
