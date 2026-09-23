"""점 재취득의 가짜 I/O 시험. ROS/실기 도달성·충돌 시험은 아님."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_workpiece_guarded_flow_mock import Clock, KinematicIO, SimulatedGuardedAdapter
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece, MeasurementError
from c2_process.robot_adapter import StepResult, posx_to_pose
from c2_process.workpiece_real_trial import check_trial_scene


def trial(scenario):
    cfg=json.loads((Path(__file__).resolve().parents[1]/'config/workpiece_real_trial_0921.json').read_text())
    w=cfg['workcell'];w['source_mode']='SIMULATION'
    clock=Clock();io=KinematicIO(w,clock,True)
    io.center=w['seed_axis_xy_m'][:];io.radius=w['seed_radius_m']
    ctx=MeasurementContext('retry','prep','SIMULATION',monotonic=clock)
    attempts=Counter();steps=[];events=[];traces=[];active=None;read_no=0
    def ready(c):return dict(ownership_confirmed=True,control_authority=True,measurement_id=c.measurement_id,checked_at_monotonic_s=clock())
    ad=SimulatedGuardedAdapter(io,w['tool_offset_m'],cfg['guards'],ready,check_trial_scene,clock=clock,sleep=clock.sleep)
    ad.trace=lambda e,d:traces.append((e,deepcopy(d)))
    raw_exec=ad.execute_measurement_step;raw_read=io.read;raw_stop=ad.stop_measurement
    def execute(step,*args):
        nonlocal active
        active=step;steps.append((step['label'],deepcopy(step)))
        if step['kind']=='PROBE':
            index=step['point_index'];attempts[index]+=1
            io.radius=w['seed_radius_m']
            if scenario in ('outlier','persistent_outlier') and index==4 and (attempts[index]==1 or scenario=='persistent_outlier'):
                io.radius+=.0015
            if scenario in ('early','early_repeat') and index==2 and (attempts[index]==1 or scenario=='early_repeat'):
                io.radius+=.0042  # baseline 확보 뒤 허용 접촉 구간보다 앞에서 접촉
            if scenario=='late' and index==2 and attempts[index]==1:
                io.radius-=.004
            if index==2:
                if scenario=='communication':raise ConnectionError('응답 미확인')
                if scenario=='tcp':raise MeasurementError('PROFILE_MISMATCH','TCP 변경')
                if scenario=='authority':raise MeasurementError('NOT_READY','제어권 상실')
                if scenario=='timeout':raise TimeoutError('응답 기한 초과')
        if scenario=='retract_failure' and step['label']=='point_2_retract':
            raise MeasurementError('FORCE_LIMIT','후퇴 중 힘 한계')
        return raw_exec(step,*args)
    def read():
        nonlocal read_no
        result=raw_read();read_no+=1
        if active and active.get('point_index')==2:
            unstable=scenario in ('baseline','baseline_repeat','stop_unknown','cancel','retract_failure') and (attempts[2]==1 or scenario=='baseline_repeat')
            if unstable and not io.active:
                result['force_n'][0]+=.35 if read_no%2 else -.35
            if scenario=='moving_baseline' and attempts[2]==1 and io.active:
                tip=posx_to_pose(result['posx'],w['tool_offset_m'])
                travel=sum((tip[k]-active['start_pose'][k])*active['direction'][k] for k in range(3))
                if .002<=travel<=.0033:
                    result['force_n'][0]+=.35 if read_no%2 else -.35
            if scenario=='absolute_force':result['force_n']=[20.,0.,0.]
            if scenario=='protection':result['robot_state']=3
        return result
    def stop(profile):
        if active and active.get('point_index')==2:
            if scenario=='stop_unknown':return StepResult('UNKNOWN','STOP_UNCONFIRMED',observed_state={'stop_confirmed':False})
            if scenario=='cancel':ctx.cancel.set()
        return raw_stop(profile)
    ad.execute_measurement_step=execute;io.read=read;ad.stop_measurement=stop
    result=measure_workpiece(ad,w,cfg['profiles'],ctx,events.append)
    return result,attempts,steps,events,traces


@pytest.mark.parametrize('scenario',['baseline','moving_baseline','early','late'])
def test_same_point_reacquired_then_remaining_seven_preserved(scenario):
    r,attempts,steps,events,traces=trial(scenario)
    assert r.ok,(r.error_code,r.message)
    assert attempts==Counter({0:1,1:1,2:2,3:1,4:1,5:1,6:1,7:1,8:1})
    labels=[label for label,_ in steps]
    first=labels.index('point_2_touch');second=labels.index('point_2_touch',first+1)
    assert labels[first+1:second]==['point_2_retract','point_2_approach']
    assert steps[first+1][1]['profile']=='retract'
    assert steps[first+1][1]['target_pose']==steps[first][1]['start_pose']
    assert len(r.observed_state['measurement']['points'])==8
    assert [p['point_index'] for p in r.observed_state['measurement']['points']]==list(range(1,9))
    assert r.observed_state['home_return_confirmed']
    assert any(e=='stationary_baseline' and d['label']=='point_2_touch' for e,d in traces)


def test_single_fit_outlier_reacquires_only_that_point():
    r,attempts,steps,events,_=trial('outlier')
    assert r.ok,(r.error_code,r.message)
    assert attempts[4]==2 and all(attempts[i]==1 for i in (0,1,2,3,5,6,7,8))
    assert len(r.observed_state['measurement']['points'])==8
    assert len(r.observed_state['superseded_points'])==1
    assert any(e['stage']=='FIT' and e['point_index']==4 for e in events)
    labels=[x[0] for x in steps];last=labels.index('point_8_outer');again=labels.index('point_4_approach',last)
    assert all(label=='orbit' for label in labels[last+1:again])


@pytest.mark.parametrize('scenario',['baseline_repeat','early_repeat','persistent_outlier'])
def test_repeat_failure_has_three_total_attempts_and_confirmed_stop(scenario):
    r,attempts,steps,_,_=trial(scenario)
    assert r.error_code=='RECOVERY_REQUIRED',(r.error_code,r.message)
    index=4 if scenario=='persistent_outlier' else 2
    assert attempts[index]==3
    assert r.observed_state['stop_confirmed'] and not r.observed_state['home_return_confirmed']
    assert steps[-1][0]==('point_2_retract' if index==2 else 'point_4_outer')
    if index==2:assert attempts[3]==0


@pytest.mark.parametrize('scenario,code',[('absolute_force','FORCE_LIMIT'),('protection','NOT_READY'),('communication','COMMUNICATION_LOST'),('tcp','PROFILE_MISMATCH'),('authority','NOT_READY'),('timeout','TIMEOUT'),('stop_unknown','STOP_UNCONFIRMED'),('cancel','CANCELLED')])
def test_fatal_or_uncertain_failure_never_reapproaches(scenario,code):
    r,attempts,steps,_,_=trial(scenario)
    assert not r.ok and r.error_code==code,(r.error_code,r.message)
    assert attempts[2]==1 and attempts[3]==0
    assert steps[-1][0]=='point_2_touch'
    if scenario=='stop_unknown':assert r.outcome=='UNKNOWN' and r.observed_state['stop_confirmed'] is False


def test_recovery_motion_failure_is_not_retried():
    r,attempts,steps,_,_=trial('retract_failure')
    assert r.error_code=='FORCE_LIMIT'
    assert attempts[2]==1 and steps[-1][0]=='point_2_retract'
