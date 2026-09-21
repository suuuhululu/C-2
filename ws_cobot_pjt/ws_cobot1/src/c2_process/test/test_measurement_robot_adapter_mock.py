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
@pytest.mark.parametrize('startup_offset_n',[0.,1.0])
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
