"""9/20 하트 성공 방식 이관의 핵심 회귀 검사. 로봇/ROS 접속 없음."""
import copy
import math
import sys
import threading
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c2_process.engraving import ExecutionContext, prepare_execution_path, execution_path_digest, execute_path
from c2_process.robot_adapter import MockRobotAdapter, StepResult, MotionCompletion, DoosanRobotAdapter


def inputs(source='SIMULATION'):
    prof=dict(vel_mm_s=5.,acc_mm_s2=10.,completion_timeout_s=90.,angular_vel_deg_s=5.,
              angular_acc_deg_s2=10.,pos_tol_mm=.15,angle_tol_deg=.15,force_limit_n=10.,
              start_timeout_s=3.,completion_settle_s=.2)
    ctx=ExecutionContext('test',source,threading.Event(),{'cut':prof,'travel':prof},
        dict(contact_mode='fixed_depth',tool_axis='-y',depth_m=.0003,clearance_m=.010,
             tool_offset_m=[.00085,-.09955,0.]),{'mode':1,'confirmation_timeout_s':2.})
    p=dict(schema_version=2,source_mode=source,path_id='heart',path_version=1,frame_id='c2_base',
           position_unit='m',orientation='quaternion_xyzw',validation={'passed':True}, segments=[
        dict(segment_id='a',kind='APPROACH',motion_profile_id='travel',waypoints=[[.45,.010,.15,0.,0.,0.,1.]]),
        dict(segment_id='c',kind='CUT',motion_profile_id='cut',waypoints=[
            [.45,0.,.15,0.,0.,0.,1.],[.4502,0.,.15,0.,0.,0.,1.],[.45,0.,.15,0.,0.,0.,1.]]),
        dict(segment_id='r',kind='RETRACT',motion_profile_id='travel',waypoints=[[.45,.010,.15,0.,0.,0.,1.]])])
    return p,ctx


def approved(source='SIMULATION'):
    p,c=inputs(source); final=prepare_execution_path(p,c)
    c.prechecked_execution_sha256=execution_path_digest(final)
    ad=MockRobotAdapter();ad.tool_offset_m=c.tool_profile['tool_offset_m'][:]
    return final,c,ad


def test_depth_once_original_unchanged_and_every_point_executed():
    p,c=inputs(); original=copy.deepcopy(p); final=prepare_execution_path(p,c)
    assert p==original and final['path_id']==p['path_id'] and final['path_version']==1
    assert final['validation']['passed'] is False
    assert final['segments'][1]['waypoints'][0][1]==pytest.approx(-.0003)
    with pytest.raises(ValueError,match='중복'): prepare_execution_path(final,c)
    c.prechecked_execution_sha256=execution_path_digest(final);ad=MockRobotAdapter()
    r=execute_path(final,c,adapter=ad)
    assert r.ok
    assert [x['pose'] for x in ad.calls if x['fn']=='move']==[w for seg in final['segments'] for w in seg['waypoints']]
    assert not any(x['fn'] in ('probe_touch','move_spline') for x in ad.calls)


@pytest.mark.parametrize('change',['point','profile','offset','unprepared'])
def test_real_rejects_changed_plan_before_motion(change):
    p,c,ad=approved('REAL')
    if change=='point': p['segments'][1]['waypoints'][0][0]+=.001
    if change=='profile': c.motion_profiles['cut']['vel_mm_s']=20.
    if change=='offset': ad.tool_offset_m=[0.,-.10,0.]
    if change=='unprepared': p.pop('execution_plan')
    r=execute_path(p,c,adapter=ad)
    assert not r.ok and not ad.calls


def test_callback_cannot_change_running_path_or_settings():
    p,c,ad=approved();expected=[w[:] for seg in p['segments'] for w in seg['waypoints']]
    def callback(_):
        p['segments'][1]['waypoints'][0][0]=99.
        c.motion_profiles['cut']['vel_mm_s']=999.
    assert execute_path(p,c,callback,ad).ok
    assert [x['pose'] for x in ad.calls if x['fn']=='move']==expected


def test_failure_preserves_stop_evidence_and_never_retreats():
    p,c,ad=approved()
    def move(*args):
        ad.calls.append({'fn':'move'})
        return StepResult('UNKNOWN','STOP_UNCONFIRMED','no reply','move',{'stop_confirmed':False})
    ad.move=move
    r=execute_path(p,c,adapter=ad)
    assert r.outcome=='UNKNOWN' and r.observed_state['stop_confirmed'] is False
    assert len(ad.calls)==1 and r.observed_state['last_completed_segment_id']==''


@pytest.mark.parametrize('confirmed',[False,True])
def test_cancel_requires_actual_stop_confirmation(confirmed):
    p,c,ad=approved();c.cancel.set()
    ad.stop=lambda *args: StepResult('SUCCEEDED',observed_state={'stop_confirmed':confirmed})
    r=execute_path(p,c,adapter=ad)
    assert r.outcome==('STOPPED' if confirmed else 'UNKNOWN') and not ad.calls


def test_motion_guard_closed_loop_and_initial_standby():
    start=[0.,0.,0.,0.,0.,0.];g=MotionCompletion(start,start,0.,{})
    assert not g.update(.01,start,1,0)
    assert not g.update(.2,[2.,0.,0.,0.,0.,0.],2,2)
    assert not g.update(.4,start,1,0)
    assert g.update(.7,start,1,0)


def test_motion_guard_rotation_and_invalid_state():
    start=[0.]*6;end=[0.,0.,0.,0.,0.,30.];g=MotionCompletion(start,end,0.,{})
    assert not g.update(.1,start,1,0)
    assert not g.update(.2,end,2,2)
    assert not g.update(.3,end,1,0)
    assert g.update(.6,end,1,0)
    with pytest.raises(ValueError): g.update(.7,end,3,0)
    with pytest.raises(ValueError): g.update(.8,[math.nan]*6,1,0)
    with pytest.raises(TimeoutError): MotionCompletion(start,end,0.,{}).update(3.1,start,1,0)


def test_motion_command_response_loss_stops_without_resend():
    ad=object.__new__(DoosanRobotAdapter);ad.frame_id='c2_base';ad.tool_offset_m=None
    ad._motion_sample=lambda: ([0.]*6,1,0,[0.]*3)
    issued=[]
    def request(*args,**kwargs): issued.append(args[0]);raise RuntimeError('reply lost')
    ad._request=request
    ad.stop=lambda *args: StepResult('UNKNOWN','STOP_UNCONFIRMED',observed_state={'stop_confirmed':False})
    r=ad.move([.01,0.,0.,0.,0.,0.,1.],'c2_base',{'vel_mm_s':5.,'acc_mm_s2':10.},10.,None)
    assert r.outcome=='UNKNOWN' and issued==['motion/move_line']


def test_nonfinite_and_adaptive_rejected_before_preparation():
    p,c=inputs();c.tool_profile['adaptive_max_m']=.001
    with pytest.raises(ValueError): prepare_execution_path(p,c)
    c.tool_profile.pop('adaptive_max_m');p['segments'][1]['waypoints'][0][0]=math.nan
    with pytest.raises(ValueError): prepare_execution_path(p,c)


def test_cancel_stop_exception_is_unknown():
    p,c,ad=approved();c.cancel.set()
    def stop(*args): raise RuntimeError('stop connection lost')
    ad.stop=stop
    r=execute_path(p,c,adapter=ad)
    assert r.outcome=='UNKNOWN' and r.observed_state['stop_confirmed'] is False
    assert not ad.calls
