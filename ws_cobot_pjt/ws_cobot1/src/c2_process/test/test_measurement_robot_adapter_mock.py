"""새 실기 어댑터를 가짜 I/O로 검사. ROS 연결/실기 시험 아님."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.measurement_robot_adapter import GuardedMeasurementAdapter
from c2_process.robot_adapter import posx_to_pose
from c2_process.workpiece_calibration import MeasurementContext, MeasurementError


class Clock:
    def __init__(self):self.t=0.
    def __call__(self):return self.t
    def sleep(self,t):self.t+=t


class IO:
    def __init__(self,clock):
        self.clock=clock;self.p=[426.,100.,250.,0.,180.,170.];self.q=[0.,20.,60.,0.,90.,0.]
        self.motion=0;self.moves=[];self.stops=[];self.last_ik=None;self.target=None
        self.force=[0.,0.,0.];self.start_delay=0
    def read(self):
        if self.target is not None:
            if self.start_delay>0:self.start_delay-=1
            else:self.p=self.target;self.target=None;self.motion=0
        return dict(posx=self.p[:],joints_deg=self.q[:],force_n=self.force[:],robot_state=1,
                    motion_status=self.motion,measured_at_monotonic_s=self.clock())
    def metadata(self):return dict(tcp_id='tcp',load_id='load',robot_mode=1,robot_system=0,solution_space=2)
    def ik(self,p,space):self.last_ik=p;return self.q[:]
    def fk(self,q):return self.last_ik[:]
    def move(self,p,*args):self.moves.append(p[:]);self.target=p[:]
    def stop(self,mode):self.stops.append(mode);self.motion=0;self.target=None


@pytest.fixture
def setup():
    root=Path(__file__).resolve().parents[1]
    guards=json.loads((root/'config/workpiece_trial_guards.json').read_text())['guards']
    config=json.loads((root/'config/workpiece_simulation.json').read_text())
    w=config['workcell'];w.update(tcp_id='tcp',load_id='load')
    clock=Clock();io=IO(clock);ctx=MeasurementContext('adapter-test','preparation-test','REAL',monotonic=clock)
    def ready(c):return dict(ownership_confirmed=True,drill_off_confirmed=True,mount_fixed=True,control_authority=True,measurement_id=c.measurement_id,checked_at_monotonic_s=clock())
    ad=GuardedMeasurementAdapter(io,w['tool_offset_m'],guards,ready,lambda *a:dict(path_checked=True,probe_envelopes_checked=True),clock=clock,sleep=clock.sleep)
    target=posx_to_pose([436.,100.,250.,0.,180.,-170.],w['tool_offset_m'])
    step=dict(kind='MOVE',target_pose=target,profile='travel',label='orbit')
    return ad,io,ctx,config,step,clock


def test_preflight_checks_short_singular_rotation(setup):
    ad,io,ctx,c,step,clock=setup
    r=ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    assert r.ok and r.observed_state['sample_count']==20
    assert ad.native_targets[tuple(step['target_pose'])][5]==pytest.approx(190.)
    assert io.moves==[]


def test_ack_without_motion_is_not_success_or_retried(setup):
    ad,io,ctx,c,step,clock=setup
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    io.start_delay=10000
    with pytest.raises(MeasurementError,match='이동 시작 미확인'):
        ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10)
    assert len(io.moves)==1


def test_motion_completion_waits_for_stability(setup):
    ad,io,ctx,c,step,clock=setup
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    r=ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10)
    assert r.ok and clock.t>=ad.g['completion_stable_s']
    assert r.observed_state['stop_confirmed']


def test_cancel_before_send(setup):
    ad,io,ctx,c,step,clock=setup
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx);ctx.cancel.set()
    with pytest.raises(MeasurementError,match='취소'):ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10)
    assert not io.moves


def test_invalid_scene_fails_before_ik_or_move(setup):
    ad,io,ctx,c,step,clock=setup;ad.scene_check=lambda *a:dict(path_checked=False)
    with pytest.raises(MeasurementError,match='간섭 검사'):ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    assert io.last_ik is None and not io.moves


def test_mismatched_tcp_never_moves(setup):
    ad,io,ctx,c,step,clock=setup;c['workcell']['tcp_id']='another-tcp'
    with pytest.raises(MeasurementError,match='TCP'):ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    assert not io.moves


def test_ik_limit_rejects(setup):
    ad,io,ctx,c,step,clock=setup;io.ik=lambda *a:[0.,200.,60.,0.,90.,0.]
    with pytest.raises(MeasurementError,match='관절 범위'):ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    assert not io.moves


def test_stop_response_is_not_stop_confirmation(setup):
    ad,io,ctx,c,step,clock=setup;io.motion=2;io.stop=lambda mode:None
    r=ad.stop_measurement(c['profiles']['stop'])
    assert r.outcome=='UNKNOWN' and r.observed_state['stop_confirmed'] is False


def test_stop_observed_stable(setup):
    ad,io,ctx,c,step,clock=setup
    r=ad.stop_measurement(c['profiles']['stop'])
    assert r.ok and clock.t>=ad.g['stop_stable_s']


@pytest.mark.parametrize('drift',['position','orientation','joint'])
def test_idle_status_with_actual_drift_is_not_stop_confirmation(setup,drift):
    ad,io,ctx,c,step,clock=setup
    original=io.read
    def read():
        if drift=='position':io.p[0]+=.1
        elif drift=='orientation':io.p[5]+=.1
        else:io.q[0]+=.1
        return original()
    io.read=read
    r=ad.stop_measurement(c['profiles']['stop'])
    assert r.outcome=='UNKNOWN' and not r.observed_state['stop_confirmed']
    assert io.stops==[c['profiles']['stop']['mode']] and not io.moves


def test_stop_waits_for_full_stable_interval_after_drift(setup):
    ad,io,ctx,c,step,clock=setup
    original=io.read
    def read():
        if clock()<.3:io.p[0]+=.1
        return original()
    io.read=read
    r=ad.stop_measurement(c['profiles']['stop'])
    assert r.ok and clock()>=.28+ad.g['stop_stable_s']


@pytest.mark.parametrize('state',[0,2,4,7,8,11,12,13,14,15,99])
def test_unknown_or_nonstationary_robot_state_is_not_stop_confirmation(setup,state):
    ad,io,ctx,c,step,clock=setup
    original=io.read
    def read():return dict(original(),robot_state=state)
    io.read=read
    assert ad.stop_measurement(c['profiles']['stop']).outcome=='UNKNOWN'


@pytest.mark.parametrize('state',[3,5,6,9,10])
def test_protective_stop_can_confirm_no_motion_without_recovery_command(setup,state):
    ad,io,ctx,c,step,clock=setup
    original=io.read
    def read():return dict(original(),robot_state=state)
    io.read=read
    r=ad.stop_measurement(c['profiles']['stop'])
    assert r.ok and r.observed_state=={'stop_confirmed':True}
    assert io.stops==[c['profiles']['stop']['mode']] and not io.moves


@pytest.mark.parametrize('failure',['cached','stale','disconnected','late','rejected'])
def test_stop_requires_fresh_observations_before_deadline(setup,failure):
    ad,io,ctx,c,step,clock=setup
    original=io.read
    def read():
        if failure=='disconnected':raise ConnectionError('lost')
        if failure=='late':clock.sleep(c['profiles']['stop']['timeout_s'])
        o=original()
        if failure=='cached':o['measured_at_monotonic_s']=0.
        if failure=='stale':o['measured_at_monotonic_s']=-10.
        return o
    io.read=read
    if failure=='rejected':
        def stop(mode):raise ConnectionError('stop rejected')
        io.stop=stop
    r=ad.stop_measurement(c['profiles']['stop'])
    assert r.outcome=='UNKNOWN' and r.error_code=='STOP_UNCONFIRMED'
    assert not r.observed_state['stop_confirmed'] and not io.moves


def test_raw_force_limit_prevents_send(setup):
    ad,io,ctx,c,step,clock=setup
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx);io.force=[100.,0.,0.]
    with pytest.raises(MeasurementError,match='힘 한계'):ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10)
    assert not io.moves


def test_unknown_target_prevents_send(setup):
    ad,io,ctx,c,step,clock=setup
    with pytest.raises(MeasurementError,match='검사하지 않은'):ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10)
    assert not io.moves


@pytest.mark.parametrize('kind,direction',[('side_touch',[-1.,0.,0.]),('top_touch',[0.,0.,-1.])])
@pytest.mark.parametrize('startup_offset_n',[0.,1.0,2.1])
def test_probe_collects_force_candidate_and_confirms_stop(setup,kind,direction,startup_offset_n):
    from c2_process.robot_adapter import pose_to_posx
    from c2_process.workpiece_calibration import facing_pose
    ad,io,ctx,c,_,clock=setup
    start=facing_pose([.426,0.],.039,.2,0.)
    end=start[:]
    for k in range(3):end[k]+=direction[k]*.0055
    io.p=pose_to_posx(start,ad.offset)
    step=dict(kind='PROBE',start_pose=start,target_pose=end,direction=direction,max_m=.0055,
              profile=kind,label='probe',point_index=1 if kind=='side_touch' else 0)
    original_read=io.read
    command={}
    def move(target,speed,*args):
        io.moves.append(target)
        command.update(t=clock(),start=io.p[:],speed=speed,active=True)
    def read():
        if command.get('active'):
            travel=min(4.8,(clock()-command['t'])*command['speed'])
            io.p=[command['start'][k]+travel*direction[k] for k in range(3)]+command['start'][3:]
            io.motion=2
            # 시작 직후 1 N 변화가 있어도 빈 공간의 이동 기준 힘으로 재설정한다.
            io.force=[-v*(startup_offset_n+(.9 if travel>=4.8 else 0.)) for v in direction]
        return original_read()
    def stop(mode):
        command['active']=False;io.stops.append(mode);io.motion=0
    io.move=move;io.read=read;io.stop=stop
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    r=ad.execute_measurement_step(step,c['profiles'][kind],ctx,60)
    assert r.ok and r.observed_state['stop_confirmed']
    assert r.observed_state['contact']['normal_force_n']==pytest.approx(.9)
    assert r.observed_state['contact']['operator_confirmed'] is False
    assert sum((r.observed_state['contact']['tip_pose'][k]-start[k])*direction[k] for k in range(3))==pytest.approx(.0048)
    assert io.stops==[1] and len(io.moves)==1


def test_negative_near_180_keeps_vertical_interpolation(setup):
    from c2_process.robot_adapter import posx_to_pose
    ad,io,ctx,c,step,clock=setup
    io.p[4]=-179.99992
    step['target_pose']=posx_to_pose([io.p[0],io.p[1],330.,*io.p[3:]],ad.offset)
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    assert ad.native_targets[tuple(step['target_pose'])][4]==pytest.approx(-180.,abs=.001)


def test_recording_failure_cannot_prevent_stop_command(setup):
    ad,io,ctx,c,step,clock=setup
    def broken(*args):raise OSError('disk full')
    ad.trace=broken
    r=ad.stop_measurement(c['profiles']['stop'])
    assert io.stops==[1] and r.observed_state['stop_confirmed']


@pytest.mark.parametrize('b',[-179.99,-179.8,-170.,-90.,-.2,.2,90.,170.,179.8,179.99,180.,-180.])
def test_zyz_equivalent_branch_preserves_pose_without_long_rotation(b):
    from c2_process.measurement_robot_adapter import continuous_target
    from c2_process.workpiece_calibration import rotation_distance
    native=[421.7,.1,264.34,.928,b,.927]
    pose=posx_to_pose(native)
    target=continuous_target(pose,None,native)
    assert max(abs(a-c) for a,c in zip(target[3:],native[3:]))<.002
    assert rotation_distance(pose,posx_to_pose(target))<1e-6


@pytest.mark.parametrize('drift_mm,expected',[(.12,'BASELINE_SETTLED'),(.5,'시작 위치/자세 이탈')])
def test_baseline_waits_for_small_settling_but_rejects_large_drift(setup,drift_mm,expected):
    from c2_process.robot_adapter import pose_to_posx
    ad,io,ctx,c,_,clock=setup
    start=posx_to_pose(io.p,ad.offset);end=start[:];end[2]-=.0055
    step=dict(kind='PROBE',start_pose=start,target_pose=end,direction=[0.,0.,-1.],max_m=.0055,profile='top_touch',label='top_touch',point_index=0)
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    original=io.read;origin=io.p[:]
    def read():
        io.p[0]=origin[0]+drift_mm*min(1.,clock()/1.5)
        io.force=[0.,0.,min(1.2,clock()*.8)]
        return original()
    def move(*args):raise RuntimeError('BASELINE_SETTLED')
    io.read=read;io.move=move
    with pytest.raises(Exception,match=expected):
        ad.execute_measurement_step(step,c['profiles']['top_touch'],ctx,60)
    if drift_mm==.12:assert clock()>=2.


def test_recorded_second_probe_deviation_is_rejected_and_logged(setup):
    """0.304 mm 실측 이탈을 진동으로 무시하거나 성공 접촉으로 처리하지 않는다."""
    ad,io,ctx,c,_,clock=setup
    raw=json.loads((Path(__file__).parent/'fixtures/workpiece_supervised_0921.json').read_text())['deviation']
    io.p=raw['start']['posx'][:];io.q=raw['start']['joints_deg'][:]
    step=raw['step'];events=[];ad.trace=lambda event,data:events.append((event,data))
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    original=io.read;moving=False
    def move(target,*args):
        nonlocal moving
        moving=True;io.moves.append(target)
    def read():
        if moving:
            io.p=raw['last_before_stop']['posx'][:];io.motion=2
        return original()
    io.move=move;io.read=read
    with pytest.raises(MeasurementError,match='횡오차 0.304 mm') as error:
        ad.execute_measurement_step(step,raw['profile'],ctx,60)
    assert error.value.code=='CONTACT_OUT_OF_RANGE'
    event=next(data for name,data in events if name=='probe_deviation')
    assert event['lateral_m']==pytest.approx(raw['lateral_m'])
    assert event['desired_tcp'] is None  # 당시 기록에 없던 목표를 만들어 넣지 않는다.
    assert len(io.moves)==1


def test_desired_tcp_is_diagnostic_and_does_not_replace_measured_tcp():
    from types import SimpleNamespace as N
    from c2_process.measurement_robot_adapter import RosMeasurementIO
    io=object.__new__(RosMeasurementIO)
    def many(requests):
        assert requests[-1]==('aux_control/get_desired_posx','GetDesiredPosx',{'ref':0})
        return [N(robot_state=1),N(status=0),N(task_pos_info=[N(data=[1,2,3,0,180,0])]),
                N(pos=[0]*6),N(tool_force=[0]*6),N(pos=[4,5,6,0,180,0])]
    io._many=many
    observed=io.read()
    assert observed['posx'][:3]==[1,2,3]
    assert observed['desired_posx'][:3]==[4,5,6]


@pytest.mark.parametrize('settles',[True,False])
def test_probe_waits_for_controller_tracking_even_when_force_is_constant(setup,settles):
    ad,io,ctx,c,_,clock=setup
    start=posx_to_pose(io.p,ad.offset);end=start[:];end[2]-=.0055
    step=dict(kind='PROBE',start_pose=start,target_pose=end,direction=[0.,0.,-1.],max_m=.0055,
              profile='top_touch',label='top_touch',point_index=0)
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    original=io.read
    def read():
        o=original();o['desired_posx']=o['posx'][:]
        if not settles or clock()<2.:o['desired_posx'][0]+=.05
        return o
    def move(*args):raise RuntimeError('TRACKING_SETTLED')
    io.read=read;io.move=move
    expected='TRACKING_SETTLED' if settles else '실제/지시 TCP 정착 미확인'
    with pytest.raises(Exception,match=expected):ad.execute_measurement_step(step,c['profiles']['top_touch'],ctx,60)
    assert clock()>=3. if settles else clock()>=ad.g['baseline_timeout_s']
    assert not io.moves


@pytest.mark.parametrize('profile_name,force_n,allowed',[
    ('travel',12.5,True),('escape',12.5,True),
    ('travel',15.,False),('escape',15.,False),
    ('approach',10.,False),('retract',10.,False),('top_touch',10.,False),('side_touch',10.,False),
])
def test_real_air_and_contact_force_policy(setup,profile_name,force_n,allowed):
    ad,io,ctx,c,step,clock=setup
    root=Path(__file__).resolve().parents[1]
    profile=json.loads((root/'config/workpiece_real_trial_0921.json').read_text())['profiles'][profile_name]
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    io.force=[force_n,0.,0.]
    if allowed:
        assert 'soft_force_n' not in profile
        # 높은 공중 힘 기준 미만 신호는 이동의 완료 안정화 동안 지속되어도 중단하지 않는다.
        assert ad.execute_measurement_step(step,profile,ctx,10).ok
    else:
        with pytest.raises(MeasurementError,match='힘 한계'):
            ad.execute_measurement_step(step,profile,ctx,10)
        assert not io.moves


def test_nonfinite_desired_pose_is_not_accepted_as_settled(setup):
    ad,io,ctx,c,step,clock=setup;original=io.read
    def read():
        result=original();result['desired_posx']=[float('nan'),0.,0.,0.,0.,0.];return result
    io.read=read
    with pytest.raises(ValueError):ad.observe_measurement()
    assert not io.moves


def overhead_replay(setup, *, limit=1., extra_error_mm=0.):
    """기록된 0.647mm 편차까지 재생 후 목표 도달만 합성한다."""
    ad,io,ctx,c,_,clock=setup
    root=Path(__file__).resolve().parents[1]
    recording=json.loads((root/'test/fixtures/workpiece_home_x_deviation_0921.json').read_text())
    real=json.loads((root/'config/workpiece_real_trial_0921.json').read_text())
    c['workcell']['trial_scene']=real['workcell']['trial_scene']
    ad.g['overhead_line_error_mm']=limit
    io.p=recording['start_tcp'][:];step=recording['step']
    from c2_process.workpiece_real_trial import check_trial_scene
    ad.scene_check=check_trial_scene
    ad.preflight_measurement([step],c['workcell'],c['profiles'],ctx)
    recorded=[p[:] for p in recording['observed_tcp']]
    recorded[-1][2]-=extra_error_mm
    original=io.read
    def read():
        if io.target is not None and recorded:
            io.p=recorded.pop(0)
            return dict(posx=io.p[:],joints_deg=io.q[:],force_n=[0.,0.,0.],robot_state=1,
                        motion_status=2,measured_at_monotonic_s=clock())
        return original()
    io.read=read
    return ad,io,ctx,c,step,clock


def test_recorded_overhead_deviation_continues_without_resending(setup):
    ad,io,ctx,c,step,clock=overhead_replay(setup)
    result=ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10.)
    assert result.ok and result.observed_state['stop_confirmed']
    assert len(io.moves)==1 and io.stops==[]


def test_recorded_overhead_deviation_reproduces_old_failure(setup):
    ad,io,ctx,c,step,clock=overhead_replay(setup,limit=.5)
    with pytest.raises(MeasurementError,match='이동 선분 이탈'):
        ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10.)
    assert len(io.moves)==1


def test_overhead_bound_exceeded_still_fails(setup):
    ad,io,ctx,c,step,clock=overhead_replay(setup,extra_error_mm=.5)
    with pytest.raises(MeasurementError,match='이동 선분 이탈'):
        ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10.)
    assert len(io.moves)==1


@pytest.mark.parametrize('change',['low','approach','rotation','missing_scene','box_edge'])
def test_overhead_allowance_never_applies_to_close_or_unverified_motion(setup,change):
    ad,io,ctx,c,step,clock=overhead_replay(setup)
    start=io.p[:];target=ad.native_targets[tuple(step['target_pose'])][:]
    if change=='low':start[2]=target[2]=250.
    elif change=='approach':step['profile']='approach'
    elif change=='rotation':target[5]+=30.
    elif change=='missing_scene':ad.workcell.pop('trial_scene')
    elif change=='box_edge':start[2]=target[2]=334.9
    assert ad._move_line_limit(step,start,target)==ad.g['line_error_mm']


def test_overhead_actual_scene_rejection_never_resends(setup):
    ad,io,ctx,c,step,clock=overhead_replay(setup)
    ad.scene_check=lambda *a:dict(path_checked=False)
    with pytest.raises(MeasurementError,match='간섭 검사 실패'):
        ad.execute_measurement_step(step,c['profiles']['travel'],ctx,10.)
    assert len(io.moves)==1
