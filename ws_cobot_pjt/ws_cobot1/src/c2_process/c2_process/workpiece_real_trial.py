"""현장 단독 시험용 팩터리. 기존 공정 노드와 동시에 실행하지 않는다.

그리퍼 밑면 오프셋 미확인 시 CONTACT_REFERENCE로만 측정하며 geometry_ready=False.
상수 True 검사 콜백 대신 제한된 실험 경로/도구 선분 검사와 장치 상태 재관측을 사용.
전체 로봇/케이블 메시 충돌 검사나 작업셀 인증이 아니다.
"""
import fcntl
import hashlib
import math
from pathlib import Path
import threading
import time
from .measurement_robot_adapter import RosMeasurementIO, GuardedMeasurementAdapter, interpolate
from .robot_adapter import pose_to_posx, posx_to_pose, tool_axis_in_base
from .workpiece_calibration import MeasurementError, rotation_distance


def continuous_target(pose, offset, previous):
    target=pose_to_posx(pose,offset)
    if abs(abs(target[4])-180)<1e-3:
        invariant=target[5]-target[3];target[3]=previous[3]
        target[4]+=360*round((previous[4]-target[4])/360);target[5]=invariant+target[3]
    for axis in (3,5):target[axis]+=360*round((previous[axis]-target[axis])/360)
    return target


def check_trial_scene(steps,w,initial):
    """고정 양초의 기존 검증 영역: 상공 이동, 중심 수직 터치, 원통 외곽.

    새 지그/양초/공구 장착에 일반화할 수 없다. 모든 native TCP 보간점과
    드릴 끝~TCP 선분의 원통 여유를 검사한다. 접촉과 후퇴는 검사된 방사선/수직선만 허용.
    """
    scene=w['trial_scene'];center=w['seed_axis_xy_m'];radius=w['seed_radius_m'];offset=w['tool_offset_m']
    prev=initial['posx'];count=0;minimum=math.inf
    for step in steps:
        target=continuous_target(step['target_pose'],offset,prev)
        n=max(1,math.ceil(math.dist(prev[:3],target[:3])/scene['sample_mm']),
              math.ceil(max(abs(a-b) for a,b in zip(prev[3:],target[3:]))/scene['sample_deg']))
        if n>1000:raise MeasurementError('SCENE_REJECTED','시험 영역 회전/거리 범위 초과')
        for i in range(n+1):
            native=interpolate(prev,target,i/n);tcp=[x/1000 for x in native[:3]]
            tip=posx_to_pose(native,offset);label=step['label']
            if any(not a<=v<=b for v,a,b in zip(tcp,scene['tcp_min_m'],scene['tcp_max_m'])):
                raise MeasurementError('SCENE_REJECTED','검사한 작업대 범위 밖')
            if tool_axis_in_base(tip,'+z')[2]>-math.cos(math.radians(scene['upright_tolerance_deg'])):
                raise MeasurementError('SCENE_REJECTED','그리퍼 수직 자세 범위 초과')
            if min(tcp[2],tip[2])>=scene['overhead_clearance_z_m']:
                count+=1;continue
            dx,dy=tcp[0]-tip[0],tcp[1]-tip[1];den=dx*dx+dy*dy
            t=max(0,min(1,((center[0]-tip[0])*dx+(center[1]-tip[1])*dy)/den)) if den else 0
            gap=math.hypot(tip[0]+t*dx-center[0],tip[1]+t*dy-center[1])-radius
            minimum=min(minimum,gap)
            if label.startswith('home_'):
                h=w['home'];at_home=math.dist(tcp[:2],h['tcp_pose'][:2])<=h['corridor_xy_tolerance_m']
                at_top=math.dist(tcp[:2],center)<=h['corridor_xy_tolerance_m']
                vertical=math.dist(prev[:2],target[:2])<=h['position_tolerance_m']*1000
                if label in ('home_escape_slow','home_escape_outer'):
                    # 같은 높이/자세의 방사선 이탈만 허용. 원통 안 시작점은 거절.
                    a=posx_to_pose(prev,offset);b=posx_to_pose(target,offset)
                    ra=[a[k]-center[k] for k in range(2)];rb=[b[k]-center[k] for k in range(2)]
                    if (gap < -scene['model_tolerance_m'] or abs(prev[2]-target[2])>1e-6 or
                        rotation_distance(a,b)>1e-6 or math.hypot(*rb)<math.hypot(*ra) or
                        abs(ra[0]*rb[1]-ra[1]*rb[0])>1e-8):
                        raise MeasurementError('SCENE_REJECTED','홈 진입 전 방사선 이탈 경로 불일치')
                elif label=='home_down':
                    if not at_home or not vertical or tcp[2]<h['tcp_pose'][2]-h['position_tolerance_m']:
                        raise MeasurementError('SCENE_REJECTED','홈 하강 통로 밖')
                elif label=='home_lift':
                    top_ok=at_top and tcp[2]>=h['top_corridor_min_z_m']
                    home_ok=at_home and tcp[2]>=h['tcp_pose'][2]-h['position_tolerance_m']
                    if not vertical or (not (top_ok or home_ok) and gap<scene['outer_min_gap_m']):
                        raise MeasurementError('SCENE_REJECTED','홈 상승 통로/외곽 여유 부족')
                else:
                    raise MeasurementError('SCENE_REJECTED','홈 수평/자세 변경은 상공에서만 허용')
            elif label.startswith('top_'):
                at_center=math.dist(tcp[:2],center)<=scene['top_xy_tolerance_m']
                if at_center:
                    if label in ('top_entry','top_exit'):
                        # 낮은 위치의 진입/이탈도 반드시 동일 X/Y의 수직선이다.
                        if math.dist(prev[:2],target[:2])>scene['sample_mm']:
                            raise MeasurementError('SCENE_REJECTED','양초 위 낮은 위치에서 수평 이동')
                    if native[2]/1000<scene['top_tcp_min_z_m']:
                        raise MeasurementError('SCENE_REJECTED','검사한 윗면 탐색 하한 초과')
                elif gap<scene['outer_min_gap_m']:
                    raise MeasurementError('SCENE_REJECTED','상공 진입 중 도구/양초 간격 부족')
            else:
                if label in ('orbit','side_entry','side_entry_above') or label.endswith('_outer'):
                    # 바깥으로 빠지는 선분은 시작점이 2 mm 간격이다.
                    limit=w['slow_retract_gap_m']-scene['model_tolerance_m'] if label.endswith('_outer') else scene['outer_min_gap_m']
                elif label.endswith('_approach'):limit=w['start_gap_m']-scene['model_tolerance_m']
                else:limit=-w['inside_limit_m']-scene['model_tolerance_m']
                if gap<limit:raise MeasurementError('SCENE_REJECTED','도구 선분과 양초의 시험 여유 부족')
                inward=[center[0]-tip[0],center[1]-tip[1],0.];norm=math.hypot(*inward[:2])
                axis=tool_axis_in_base(tip,'-y')
                if norm==0 or sum(a*b/norm for a,b in zip(axis,inward))<math.cos(math.radians(scene['facing_tolerance_deg'])):
                    raise MeasurementError('SCENE_REJECTED','드릴 -Y가 양초 중심을 향하지 않음')
            count+=1
        prev=target
    return dict(path_checked=True,probe_envelopes_checked=True,samples=count,
                min_model_shaft_gap_m=minimum if math.isfinite(minimum) else None,
                scope='RECORDED_TRIAL_CORRIDORS_AND_CYLINDER_SHAFT_MODEL',
                full_robot_gripper_cable_mesh_checked=False,
                environment_record_id=scene['environment_record_id'])


class TrialLease:
    def __init__(self,node,config,context,io):
        if config.get('standalone_operator_acknowledged') is not True:
            raise ValueError('단독 시험·드릴 OFF·고정 유지·비상정지 대기 확인 필요')
        if 'process_controller_node' in node.get_node_names():
            raise ValueError('공정 제어 노드가 실행 중: 단독 시험 시작 금지')
        self.config=config;self.context=context;self.io=io;self.closed=threading.Event()
        self.meta=None;self.meta_at=0.;self.error=None;self.alarm=None
        lockname=hashlib.sha256(config['controller_prefix'].encode()).hexdigest()[:12]
        self.file=(Path('/tmp')/('c2_workpiece_'+lockname+'.lock')).open('a')
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except Exception:self.file.close();raise ValueError('다른 단독 측정 실행기가 동작 중')
        from dsr_msgs2.msg import RobotError
        def alarm(msg):
            if msg.level>=2:self.alarm=dict(code=msg.code,message=msg.msg1)
        self.subscription=node.create_subscription(RobotError,config['robot_error_topic'],alarm,10)
        self.node=node;self.started=time.monotonic()
        try:self.refresh()
        except Exception:self.close();raise
        self.thread=threading.Thread(target=self.monitor,daemon=True);self.thread.start()

    def refresh(self):
        self.meta=self.io.metadata();self.meta_at=time.monotonic();self.error=None

    def monitor(self):
        while not self.closed.wait(.2):
            try:self.refresh()
            except Exception as exc:self.error=str(exc)

    def readiness(self,context):
        now=time.monotonic();w=self.config['workcell']
        fresh=self.error is None and now-self.meta_at<1.5 and self.alarm is None
        expected=fresh and self.meta['robot_mode']==1 and self.meta['robot_system']==0 and self.meta['tcp_id']==w['tcp_id'] and self.meta['load_id']==w['load_id']
        active=not self.closed.is_set() and context is self.context and context.motion_lock.locked()
        if now-self.started>self.config['operator_ack_valid_s']:active=False
        return dict(measurement_id=context.measurement_id,checked_at_monotonic_s=now,
                    ownership_confirmed=active,drill_off_confirmed=active,mount_fixed=active,
                    control_authority=bool(expected),
                    operator_conditions_source='STANDALONE_OPERATOR_ATTESTATION',
                    controller_condition_source='REAL_AUTO_TCP_LOAD_POLL; native authority is not independently queried')

    def close(self):
        self.closed.set()
        if hasattr(self,'subscription'):self.node.destroy_subscription(self.subscription)
        if not self.file.closed:fcntl.flock(self.file,fcntl.LOCK_UN);self.file.close()


def create_adapter(node,config,context):
    io=RosMeasurementIO(node,config['controller_prefix'],config['service_timeout_s'])
    lease=TrialLease(node,config,context,io)
    try:
        adapter=GuardedMeasurementAdapter(io,config['workcell']['tool_offset_m'],config['guards'],lease.readiness,check_trial_scene)
        adapter.close=lease.close
        trace=getattr(node,'workpiece_trace',None)
        if trace is not None:adapter.trace=trace
        return adapter
    except Exception:
        lease.close();raise
