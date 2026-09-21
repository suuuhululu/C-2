"""실기 설정의 전체 호출 흐름을 운동/힘 가짜 I/O로 검사한다.

ROS/로봇 연결 없음. IK/FK는 상수 관절/입력 반향이므로 물리적 도달성이나
실제 서보 추종 오차는 검증하지 않는다. 이 모형의 시간은 실기 기록이 아니다.
"""
import json
import math
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.measurement_robot_adapter import GuardedMeasurementAdapter, interpolate
from c2_process.robot_adapter import posx_to_pose, pose_to_posx
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece
from c2_process.workpiece_real_trial import check_trial_scene


class Clock:
    def __init__(self):self.t=0.
    def __call__(self):return self.t
    def sleep(self,dt):self.t+=dt


class KinematicIO:
    """직선 가감속/공간 접촉 모형. 서보 오차/진동/마찰/보호 기능 모형 아님."""
    def __init__(self,w,clock,at_home):
        self.w=w;self.clock=clock;self.moves=[];self.stops=[];self.active=None;self.contact=None
        self.p=pose_to_posx(w['home']['tcp_pose'])
        if not at_home:self.p[2]=330.
        self.q=[0.,20.,60.,0.,90.,0.];self.ik_target=None
        self.center=[w['seed_axis_xy_m'][0]+.00005,w['seed_axis_xy_m'][1]-.00005]
        self.radius=w['seed_radius_m']+.0001
        self.top_contact_tcp_z=.23485
        self.fail_probe=None;self.probe_index=None

    def metadata(self):
        return dict(tcp_id=self.w['tcp_id'],load_id=self.w['load_id'],robot_mode=1,robot_system=0,solution_space=2)

    def ik(self,p,space):self.ik_target=p[:];return self.q[:]
    def fk(self,q):return self.ik_target[:]

    def move(self,target,speed,acc,angular_speed,angular_acc):
        self.moves.append(target[:])
        # 위치/각도에 같은 보간 진행률을 적용하는 시험 모형.
        distance=math.dist(self.p[:3],target[:3]);angle=max(abs(a-b) for a,b in zip(self.p[3:],target[3:]))
        duration=max(self.duration(distance,speed,acc),self.duration(angle,angular_speed,angular_acc),.02)
        self.active=dict(start=self.p[:],target=target[:],t=self.clock(),duration=duration,
                         distance=distance,speed=speed,acc=acc)

    @staticmethod
    def duration(distance,speed,acc):
        return 2*math.sqrt(distance/acc) if distance<speed*speed/acc else distance/speed+speed/acc

    def read(self):
        motion=0
        if self.active:
            m=self.active;t=self.clock()-m['t'];d=m['distance'];speed=m['speed'];acc=m['acc']
            duration=m['duration'];fraction=min(1.,t/duration)
            if d>1e-8 and abs(duration-self.duration(d,speed,acc))<1e-8:
                ta=min(speed/acc,math.sqrt(d/acc));peak=acc*ta
                if t<ta:travel=.5*acc*t*t
                elif t<duration-ta:travel=.5*acc*ta*ta+peak*(t-ta)
                else:travel=d-.5*acc*max(0,duration-t)**2
                fraction=max(0,min(1,travel/d))
            self.p=interpolate(m['start'],m['target'],fraction)
            if self.fail_probe is not None and self.probe_index==self.fail_probe and t>1.2:
                self.p[2]+=.35  # 힘 접촉보다 먼저 횡방향 추종 오차를 주입한다.
            if t>=duration:self.active=None
            else:motion=2
        tip=posx_to_pose(self.p,self.w['tool_offset_m']);force=[1.,2.,3.]
        if self.contact:
            kind,direction=self.contact
            touched=(self.p[2]/1000<=self.top_contact_tcp_z if kind=='top_touch'
                     else math.dist(tip[:2],self.center)<=self.radius)
            if touched:force=[force[k]-direction[k]*1. for k in range(3)]
        return dict(posx=self.p[:],desired_posx=self.p[:],joints_deg=self.q[:],force_n=force,
                    robot_state=2 if motion else 1,motion_status=motion,measured_at_monotonic_s=self.clock())

    def stop(self,mode):self.stops.append(mode);self.active=None


class SimulatedGuardedAdapter(GuardedMeasurementAdapter):
    source_mode='SIMULATION'
    def execute_measurement_step(self,step,*args):
        self.io.contact=(step['profile'],step['direction']) if step['kind']=='PROBE' else None
        self.io.probe_index=step.get('point_index') if step['kind']=='PROBE' else None
        return super().execute_measurement_step(step,*args)


@pytest.mark.parametrize('at_home,fail_probe',[(True,None),(False,None),(False,2)])
def test_full_guarded_flow_home_top_eight_points_and_retreat(at_home,fail_probe):
    root=Path(__file__).resolve().parents[1]
    config=json.loads((root/'config/workpiece_real_trial_0921.json').read_text())
    w=deepcopy(config['workcell']);w['source_mode']='SIMULATION';clock=Clock()
    io=KinematicIO(w,clock,at_home);ctx=MeasurementContext('model-run','model-prep','SIMULATION',monotonic=clock)
    def ready(c):
        return dict(ownership_confirmed=True,drill_off_confirmed=True,mount_fixed=True,
                    control_authority=True,measurement_id=c.measurement_id,checked_at_monotonic_s=clock())
    adapter=SimulatedGuardedAdapter(io,w['tool_offset_m'],config['guards'],ready,check_trial_scene,
                                  clock=clock,sleep=clock.sleep)
    io.fail_probe=fail_probe
    commands=[]
    adapter.trace=lambda event,data:commands.append(data['step']['label']) if event=='command' else None
    events=[];result=measure_workpiece(adapter,w,config['profiles'],ctx,events.append)
    observed=result.observed_state;m=observed['measurement']
    if fail_probe is not None:
        assert result.outcome=='FAILED' and result.error_code=='CONTACT_OUT_OF_RANGE'
        assert observed['stop_confirmed'] and observed['partial']
        assert len(m['points'])==1 and m['validity']=='INCOMPLETE'
        assert commands[-1]=='point_2_touch'  # 실패 후 후퇴·다음 점·홈을 호출하지 않는다.
        assert len(io.stops)==3 and io.active is None
        assert not any(e['stage']=='COMPLETE' for e in events)
        return
    assert result.ok,(result.error_code,result.message)
    assert observed['home_move_skipped'] is at_home
    assert len(m['points'])==8 and observed['stop_confirmed'] and not observed['partial']
    assert m['axis_xy_m']==pytest.approx(io.center,abs=.00004)
    assert m['radius_m']==pytest.approx(io.radius,abs=.00004)
    assert m['top_tcp_contact_z_m']==pytest.approx(io.top_contact_tcp_z,abs=.00001)
    assert m['top_z_m'] is None and m['geometry_ready'] is False
    assert [e['point_index'] for e in events if e['stage']=='SIDE_TOUCH' and e['status']=='SUCCEEDED']==list(range(1,9))
    assert len(io.stops)==9 and io.active is None
    assert observed['elapsed_s']<w['runtime_timeout_s']
