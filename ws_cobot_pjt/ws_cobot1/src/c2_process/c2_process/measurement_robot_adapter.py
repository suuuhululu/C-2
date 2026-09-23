"""양초 측정 전용 어댑터 내부 구현. ROS 노드/Action 서버를 새로 만들지 않는다.

REAL 전제: 실제 TCP/하중/장착 기준, 그리퍼 밑면 오프셋, 전 경로 현장 검사,
공통 모션 소유권을 확인하는 readiness/scene_check를 호출자가 제공한다.
기존 DoosanRobotAdapter를 변경하지 않고 검증된 관측·정지 계약을 분리한다.
"""
import collections
from copy import deepcopy
import json
import logging
import math
import statistics
import threading
import time

from .robot_adapter import StepResult, pose_to_posx, posx_to_pose, tool_axis_in_base
from .workpiece_calibration import (MeasurementError, MoveRecoveryError, PointMeasurementError,
                                    pose, vector, rotation_distance, side_contact_window, side_center_limit)


class RosMeasurementIO:
    """이미 spinning 중인 노드의 작업 스레드에서 사용. nested spin 없음.

    node의 executor는 별도 스레드에서 계속 실행되어야 한다. ROS callback 안에서
    동기 호출하지 않는다. REAL 생성 자체로 모션/TCP/모드 설정을 변경하지 않는다.
    """
    def __init__(self, node, controller_prefix, timeout_s):
        from dsr_msgs2 import srv
        from rclpy.callback_groups import ReentrantCallbackGroup
        self.node=node; self.srv=srv; self.prefix=controller_prefix.rstrip('/')
        if not isinstance(timeout_s,(float,int)) or isinstance(timeout_s,bool) or not 0<timeout_s<=2.:
            raise ValueError('ROS 응답 제한은 0초 초과 2초 이하')
        if not controller_prefix.startswith('/'):
            raise ValueError('제어기 서비스 namespace는 절대 ROS 이름 필요')
        self.timeout=timeout_s; self.clients={}; self.group=ReentrantCallbackGroup()

    def _many(self, requests):
        if self.node.executor is None or not self.node.executor.is_spinning:
            raise ConnectionError("측정 I/O에는 별도 스레드에서 spinning 중인 executor 필요")
        futures=[]; start=time.monotonic()
        for endpoint,typename,fields in requests:
            cls=getattr(self.srv,typename)
            if endpoint not in self.clients:
                self.clients[endpoint]=self.node.create_client(cls,self.prefix+'/'+endpoint,callback_group=self.group)
            client=self.clients[endpoint]
            if not client.wait_for_service(timeout_sec=3.0 if endpoint not in getattr(self,'_discovered',set()) else self.timeout):
                raise ConnectionError(endpoint+": service unavailable")
            if not hasattr(self,'_discovered'):self._discovered=set()
            self._discovered.add(endpoint)
            request=cls.Request()
            for key,value in fields.items():setattr(request,key,value)
            futures.append(client.call_async(request))
        start=time.monotonic()  # 초기 discovery 대기와 응답 제한 시간을 분리
        wake=threading.Event()
        for future in futures:future.add_done_callback(lambda _:wake.set())
        while not all(f.done() for f in futures):
            if time.monotonic()-start>=self.timeout:
                # 요청을 재전송하지 않는다. 특히 이동 timeout은 접수 불명으로 취급.
                for f in futures:
                    if not f.done():f.cancel()
                raise TimeoutError("ROS 응답 제한 시간 초과")
            wake.wait(.005); wake.clear()
        answers=[f.result() for f in futures]
        if any(r is None or not r.success for r in answers):
            raise ConnectionError("ROS 요청 거부/응답 실패")
        return answers

    def call(self,endpoint,typename,**fields):
        return self._many([(endpoint,typename,fields)])[0]

    def read(self):
        r=self._many([
            ('system/get_robot_state','GetRobotState',{}),
            ('motion/check_motion','CheckMotion',{}),
            ('aux_control/get_current_posx','GetCurrentPosx',{'ref':0}),
            ('aux_control/get_current_posj','GetCurrentPosj',{}),
            ('aux_control/get_tool_force','GetToolForce',{'ref':0}),
            ('aux_control/get_desired_posx','GetDesiredPosx',{'ref':0})])
        return dict(robot_state=r[0].robot_state,motion_status=r[1].status,
                    posx=list(r[2].task_pos_info[0].data[:6]),joints_deg=list(r[3].pos),
                    force_n=list(r[4].tool_force[:3]),desired_posx=list(r[5].pos),
                    measured_at_monotonic_s=time.monotonic())

    def metadata(self):
        r=self._many([('tcp/get_current_tcp','GetCurrentTcp',{}),('tool/get_current_tool','GetCurrentTool',{}),
                      ('system/get_robot_mode','GetRobotMode',{}),('system/get_robot_system','GetRobotSystem',{}),
                      ('aux_control/get_current_solution_space','GetCurrentSolutionSpace',{})])
        return dict(tcp_id=r[0].info,load_id=r[1].info,robot_mode=r[2].robot_mode,
                    robot_system=r[3].robot_system,solution_space=r[4].sol_space)

    def ik(self,target,space):
        return list(self.call('motion/ikin','Ikin',pos=target,sol_space=space,ref=0).conv_posj)

    def fk(self,joints):
        return list(self.call('motion/fkin','Fkin',pos=joints,ref=0).conv_posx)

    def move(self,target,speed,acc,angular_speed,angular_acc):
        self.call('motion/move_line','MoveLine',pos=target,vel=[speed,angular_speed],
                  acc=[acc,angular_acc],time=0.,radius=0.,ref=0,mode=0,blend_type=0,sync_type=1)

    def stop(self,mode):
        self.call('motion/move_stop','MoveStop',stop_mode=mode)


def interpolate(a,b,f):
    # native TCP 선형 위치 + ZYZ 성분 선형 보간. 실제 제어기 궤적과 별도 실기 대조 필요.
    return [x+f*(y-x) for x,y in zip(a,b)]


def ik_sample_indices(start, target, step, workcell, guards):
    """기존 촘촘한 격자의 부분집합. 분리된 공중 MOVE만 최대 두 칸씩 검사.

    실제 이동 목표/보간과 별도 현장 간섭 검사는 변경하지 않는다. 접근·접촉·
    초기 후퇴는 모든 점을 유지하며, 각 선분의 끝점은 항상 포함한다.
    """
    n=max(1,math.ceil(math.dist(start[:3],target[:3])/guards['ik_step_mm']),
          math.ceil(max(abs(a-b) for a,b in zip(start[3:],target[3:]))/guards['ik_step_deg']))
    if n>guards['max_samples_per_segment']:
        raise MeasurementError('PLAN_TOO_LARGE','ZYZ 회전 또는 경로 분할 범위 초과')
    dense=list(range(1,n+1))
    if (guards.get('air_ik_step_mm',guards['ik_step_mm'])<2*guards['ik_step_mm'] or
        guards.get('air_ik_step_deg',guards['ik_step_deg'])<2*guards['ik_step_deg']):
        return n,dense
    label=step['label']
    eligible=(label in ('orbit','side_entry','side_entry_above','home_lift',
                        'home_align','home_x','home_y','home_escape_outer') or
              (label.startswith('point_') and label.endswith('_outer')))
    scene=workcell.get('trial_scene')
    if not eligible or step['kind']!='MOVE' or step['profile'] in ('approach','retract') or not scene:
        return n,dense
    center=workcell['seed_axis_xy_m'];radius=workcell['seed_radius_m']
    def separated(i):
        native=interpolate(start,target,i/n)
        tcp=[v/1000. for v in native[:3]]
        tip=posx_to_pose(native,workcell['tool_offset_m'])
        if min(tcp[2],tip[2])>=scene['overhead_clearance_z_m']:
            return True
        dx,dy=tcp[0]-tip[0],tcp[1]-tip[1];den=dx*dx+dy*dy
        t=max(0.,min(1.,((center[0]-tip[0])*dx+(center[1]-tip[1])*dy)/den)) if den else 0.
        gap=math.hypot(tip[0]+t*dx-center[0],tip[1]+t*dy-center[1])-radius
        uncertainty=(side_center_limit(workcell)+workcell['max_radius_error_m']
                     if side_contact_window(workcell) is not None else 0.)
        return gap>=scene['outer_min_gap_m']+scene['model_tolerance_m']+uncertainty
    air=[separated(i) for i in range(n+1)]
    selected=[];i=0
    while i<n:
        # 시작·중간·끝점이 모두 분리된 두 구간만 묶는다.
        stride=2 if i+2<=n and all(air[i:i+3]) else 1
        i+=stride;selected.append(i)
    return n,selected


def continuous_target(pose, offset, previous):
    """같은 회전의 ZYZ 두 표현 중 직전 각도와 가까운 것을 선택한다.

    (A,B,C) == (A+180,-B,C+180). 수직 허용오차를 늘리거나 실제 기울기를
    180도로 반올림하지 않는다. 정확한 B=180에서만 C-A 자유도를 맞춘다.
    """
    target=pose_to_posx(pose,offset)
    if rotation_distance(pose,posx_to_pose(previous,offset))<1e-7:
        # 자세 유지 직선은 원래 제어기 각도를 보존한다. 특이점 근처 재변환 오차 방지.
        return target[:3]+list(previous[3:])
    candidates=[target, target[:3]+[target[3]+180.,-target[4],target[5]+180.]]
    if abs(abs(target[4])-180.)<1e-7:
        candidates.append(target[:3]+[previous[3],target[4],target[5]-target[3]+previous[3]])
    for candidate in candidates:
        for axis in (3,4,5):
            candidate[axis]+=360.*round((previous[axis]-candidate[axis])/360.)
    return min(candidates,key=lambda p:sum((p[k]-previous[k])**2 for k in (3,4,5)))



# 9/23 이동: workpiece_real_trial.check_trial_scene 본문. 로직 변경 없음.
# 단독 시험 전용이 아니라 공정 경로(workpiece_process_adapter)도 호출하는 운영 검사기다.
def check_measurement_scene(steps,w,initial):
    """승인된 현장 모델로 측정 경로 전체를 검사한다. 단독 시험·공정 양쪽이 쓴다.

    고정 양초의 기존 검증 영역: 상공 이동, 중심 수직 터치, 원통 외곽.

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
                    home_ok=any(math.dist(tcp[:2],p[:2])<=h['corridor_xy_tolerance_m'] and tcp[2]>=p[2]-h['position_tolerance_m']
                                for p in [h['tcp_pose'],*h.get('entry_tcp_poses',[])])
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


class GuardedMeasurementAdapter:
    measurement_contract_version=1
    source_mode="REAL"

    def __init__(self, io, tool_offset_m, guards, readiness, scene_check, *, clock=time.monotonic, sleep=time.sleep):
        self.io=io; self.offset=vector(tool_offset_m,3,"tool_offset_m")
        self.g=deepcopy(guards); self.readiness=readiness; self.scene_check=scene_check
        required=('angular_acc_deg_s2', 'angular_speed_deg_s', 'baseline_drift_n', 'baseline_position_m', 'baseline_timeout_s', 'baseline_window_slack_s', 'completion_joint_deg', 'completion_stable_s', 'fk_angle_deg', 'fk_position_mm', 'ik_step_deg', 'ik_step_mm', 'j3_margin_deg', 'j5_margin_deg', 'joint_max_deg', 'joint_min_deg', 'line_error_mm', 'max_joint_step_deg', 'max_samples_per_segment', 'max_state_age_s', 'movement_start_deg', 'movement_start_m', 'movement_start_timeout_s', 'moving_baseline_end_m', 'moving_baseline_start_m', 'moving_mad_n', 'poll_s', 'prebaseline_delta_n', 'preflight_timeout_s', 'skip_angle_deg', 'skip_position_m', 'stationary_mad_n', 'stop_stable_s')
        for key in required:
            value=self.g[key]
            if key.startswith('joint_'):
                vector(value,6,key)
            elif isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('잘못된 측정 가드: '+key)
        for key,base in (('air_ik_step_mm','ik_step_mm'),('air_ik_step_deg','ik_step_deg')):
            value=self.g.get(key,self.g[base])
            if (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)
                    or not self.g[base]<=value<=2*self.g[base]):
                raise ValueError('공중 IK 간격은 기존 간격 이상, 두 배 이하: '+key)
        hard_line=self.g.get('hard_line_error_mm')
        if hard_line is not None:
            if (isinstance(hard_line,bool) or not isinstance(hard_line,(int,float))
                    or not math.isfinite(hard_line)
                    or hard_line<max(self.g['line_error_mm'],self.g.get('overhead_line_error_mm',0.))):
                raise ValueError('이동 선분 즉시 중단 한계는 감지/상공 허용폭 이상이어야 함: hard_line_error_mm')
        baseline_tracking=self.g.get('baseline_tracking_position_m',self.g['skip_position_m'])
        if (isinstance(baseline_tracking,bool) or not isinstance(baseline_tracking,(int,float))
                or not math.isfinite(baseline_tracking)
                or not 0<baseline_tracking<=self.g['baseline_position_m']):
            raise ValueError('기준 힘 수집 전 위치 정착 허용폭 오류')
        if any(a>=b for a,b in zip(self.g['joint_min_deg'],self.g['joint_max_deg'])):
            raise ValueError('관절 최소/최대 범위 오류')
        if self.g['moving_baseline_start_m']>=self.g['moving_baseline_end_m']:
            raise ValueError('이동 기준 힘 구간 순서 오류')
        if not callable(readiness) or not callable(scene_check):
            raise ValueError('소유권/현장 간섭 검사 콜백 필요')
        self.clock=clock; self.sleep=sleep; self.expected={}; self.space=None
        self.current_context=None; self.workcell=None; self.native_targets={}
        self.stop_profile=None; self.trace=lambda event, data:None; self.trace_error=None

    def _emit_trace(self,event,data):
        try:self.trace(event,data)
        except Exception as exc:self.trace_error=str(exc)

    def _read(self):
        o=self.io.read()
        vector(o['posx'],6,'posx');vector(o['joints_deg'],6,'joints_deg');vector(o['force_n'],3,'force_n')
        if 'desired_posx' in o:vector(o['desired_posx'],6,'desired_posx')
        age=self.clock()-o['measured_at_monotonic_s']
        if not 0<=age<=self.g['max_state_age_s']:
            raise MeasurementError('STALE_DATA','측정 관측 시각 만료')
        o['tip_pose']=posx_to_pose(o['posx'],self.offset)
        self._emit_trace('observation',o)
        return o

    def observe_measurement(self):
        o=self._read()
        return dict(tip_pose=o['tip_pose'],joints_rad=[math.radians(v) for v in o['joints_deg']],
                    measured_at_monotonic_s=o['measured_at_monotonic_s'],frame_id='c2_base',quality='VALID',
                    robot_state=o['robot_state'],motion_status=o['motion_status'])

    def _joint_guard(self,q):
        vector(q,6,'IK joints')
        if any(not low<=v<=high for v,low,high in zip(q,self.g['joint_min_deg'],self.g['joint_max_deg'])):
            raise MeasurementError('JOINT_LIMIT','측정 이동 관절 범위 초과')
        if min(abs(q[4]),abs(180-abs(q[4])))<self.g['j5_margin_deg'] or abs(q[2])<self.g['j3_margin_deg']:
            raise MeasurementError('SINGULARITY_MARGIN','측정 이동 특이점 여유 부족')

    def _ready(self,context):
        if self.trace_error is not None:raise MeasurementError("TELEMETRY_LOST",self.trace_error)
        if context.cancel.is_set():raise MeasurementError('CANCELLED','측정 취소','STOPPED')
        report=self.readiness(context)
        required=('ownership_confirmed','control_authority')
        if any(report.get(k) is not True for k in required) or report.get('measurement_id')!=context.measurement_id:
            raise MeasurementError('NOT_READY','실행 소유권/제어권 확인 필요')
        if not 0<=self.clock()-report['checked_at_monotonic_s']<=self.g['max_state_age_s']:
            raise MeasurementError('NOT_READY','준비 조건 확인 만료')

    def preflight_measurement(self,steps,workcell,profiles,context):
        """계측은 로컬 로그에만 남기고 계산 캐시는 이번 검사 안에서만 사용한다."""
        metrics=dict(measurement_id=context.measurement_id,segments=len(steps),
                     samples=0,dense_samples=0,skipped_air_samples=0,
                     ik_cache_hits=0,fk_cache_hits=0,calls={},seconds={})
        self.last_preflight_metrics=metrics
        started=time.perf_counter()
        def timed(name, function, *args):
            began=time.perf_counter()
            metrics['calls'][name]=metrics['calls'].get(name,0)+1
            try:return function(*args)
            finally:metrics['seconds'][name]=metrics['seconds'].get(name,0.)+time.perf_counter()-began
        try:
            result=self._preflight_measurement(steps,workcell,profiles,context,metrics,timed)
            metrics['outcome']=result.outcome
            return result
        except Exception as exc:
            metrics['outcome']=getattr(exc,'outcome','FAILED')
            metrics['error_code']=getattr(exc,'code',type(exc).__name__)
            raise
        finally:
            metrics['elapsed_s']=time.perf_counter()-started
            # 상태/Action 필드나 별도 토픽을 추가하지 않는다. 기존 ROS 로그로 계측.
            node=getattr(self.io,'node',None)
            logger=node.get_logger() if node is not None else logging.getLogger(__name__)
            logger.info('measurement_preflight '+json.dumps(metrics,sort_keys=True))

    def _preflight_measurement(self,steps,workcell,profiles,context,metrics,timed):
        timed('readiness',self._ready,context)
        for profile_name in dict.fromkeys(('travel','approach','retract','top_touch','side_touch',workcell.get('outer_move_profile','approach'))):
            profile=profiles[profile_name]
            if 'soft_force_n' in profile:
                if not 0<profile['soft_force_n']<profile['hard_force_n'] or profile.get('soft_force_hold_s',0)<=0:
                    raise ValueError('이동 힘 soft/hard 설정 오류')
        if not 0<self.g['moving_baseline_end_m']<min(workcell['start_gap_m'],workcell['top']['max_probe_m']):
            raise ValueError('이동 기준 힘 수집 구간이 예상 표면에 도달함')
        top=workcell['top']
        if 'expected_tcp_z_range_m' in top:
            if top['approach_tcp_pose'][2]-self.g['moving_baseline_end_m']<=top['expected_tcp_z_range_m'][1]+workcell['pose_tolerance_m']:
                raise ValueError('윗면 이동 기준 힘 구간에 접촉 가능: 시작 위치/측정 범위 재확인 필요')
        contact_range=side_contact_window(workcell)
        if contact_range is not None:
            # 관측 지연 중 전진 가능 거리까지 baseline 끝과 접촉 범위 사이에 확보한다.
            margin=profiles['side_touch']['speed_m_s']*self.g['max_state_age_s']
            if self.g['moving_baseline_end_m']+margin>=contact_range[0]:
                raise ValueError('옆면 이동 baseline 구간과 접촉 가능 구간 중첩')
            for step in steps:
                if step['kind']=='PROBE' and step['profile']=='side_touch':
                    if step.get('contact_travel_range_m')!=contact_range or step['max_m']<contact_range[1]:
                        raise ValueError('옆면 접촉 구간/최대 탐색 계획 불일치')
                    if 'side_search_m' in workcell:
                        expected=[step['start_pose'][k]+step['direction'][k]*contact_range[0] for k in range(3)]+step['start_pose'][3:]
                        if step.get('baseline_before_search') is not True or step.get('search_start_pose')!=expected:
                            # 삼각함수 왕복 계산의 부동소수점 오차만 허용한다.
                            supplied=step.get('search_start_pose')
                            if step.get('baseline_before_search') is not True or supplied is None or math.dist(pose(supplied)[:3],expected[:3])>1e-12 or rotation_distance(supplied,expected)>1e-7:
                                raise ValueError('탐색 전 baseline/탐색 시작 자세 불일치')
        self.current_context=context;self.workcell=workcell;self.stop_profile=profiles['stop']
        deadline=self.clock()+min(self.g['preflight_timeout_s'],workcell['runtime_timeout_s'])
        self.expected.clear();self.native_targets.clear()
        if self.offset!=workcell['tool_offset_m']:
            raise MeasurementError('PROFILE_MISMATCH','어댑터/측정 설정 도구 오프셋 불일치')
        metadata=timed('metadata',self.io.metadata)
        if metadata['tcp_id']!=workcell['tcp_id'] or metadata['load_id']!=workcell['load_id'] or metadata['robot_mode']!=1 or metadata['robot_system']!=0:
            raise MeasurementError('PROFILE_MISMATCH','실제 장치의 TCP/하중/REAL/AUTO 불일치')
        self.space=metadata['solution_space']
        initial=timed('observation',self._read); prev=initial['posx']; q=initial['joints_deg'];self._joint_guard(q)
        if initial['robot_state']!=1 or initial['motion_status']!=0:
            raise MeasurementError('NOT_READY','이동 검사 시작 시 정지 미확인')
        # 그리퍼/드릴/철사/양초/작업대의 전체 경로와 접촉 구간 후퇴를 승인하는 검사기.
        # 좌표가 유한하다는 이유만으로 간섭 검사를 통과시키지 않는다.
        scene=timed('scene',self.scene_check,steps,workcell,initial)
        if scene.get('path_checked') is not True or scene.get('probe_envelopes_checked') is not True:
            raise MeasurementError('NOT_READY','진입/원호/접촉/후퇴의 현장 간섭 검사 미완료')
        count=0
        # TCP/해 공간/설정이 다른 다음 검사에는 재사용하지 않는다. 좌표 반올림 금지.
        ik_cache={};fk_cache={}
        for step in steps:
            target=continuous_target(step['target_pose'],self.offset,prev)
            self.native_targets[tuple(step['target_pose'])]=target[:]
            n,indices=ik_sample_indices(prev,target,step,workcell,self.g)
            metrics['dense_samples']+=n
            metrics['skipped_air_samples']+=n-len(indices)
            for i in indices:
                timed('readiness',self._ready,context)
                if self.clock()>=deadline:raise MeasurementError('TIMEOUT','측정 이동 사전 검사 시간 초과')
                point=interpolate(prev,target,i/n)
                ik_key=(self.space,tuple(point))
                if ik_key in ik_cache:
                    raw=ik_cache[ik_key]
                    metrics['ik_cache_hits']+=1
                else:
                    raw=tuple(vector(timed('ik',self.io.ik,point,self.space),6,'IK joints'))
                    ik_cache[ik_key]=raw
                # 같은 IK 결과도 직전 관절에 맞춘 회전수·연속성 검사는 다시 수행.
                nxt=list(raw)
                for axis in (0,3,5):nxt[axis]+=360*round((q[axis]-nxt[axis])/360)
                self._joint_guard(nxt)
                if max(abs(a-b) for a,b in zip(q,nxt))>self.g['max_joint_step_deg']:
                    raise MeasurementError('IK_DISCONTINUITY','IK 해 불연속')
                fk_key=(tuple(point),tuple(nxt))
                if fk_key in fk_cache:
                    fk=fk_cache[fk_key]
                    metrics['fk_cache_hits']+=1
                else:
                    fk=tuple(vector(timed('fk',self.io.fk,nxt),6,'FK pose'))
                    fk_cache[fk_key]=fk
                if math.dist(fk[:3],point[:3])>self.g['fk_position_mm'] or rotation_distance(posx_to_pose(fk),posx_to_pose(point))>math.radians(self.g['fk_angle_deg']):
                    raise MeasurementError('IK_FK_MISMATCH','IK/FK 대조 실패')
                q=nxt;count+=1;metrics['samples']=count
                self._emit_trace("ik_sample",dict(label=step["label"],sample=count,native_tcp=point,joints_deg=q))
            self.expected[tuple(step['target_pose'])]=q[:];prev=target
        timed('readiness',self._ready,context)
        return StepResult('SUCCEEDED',observed_state=dict(all_segments_checked=True,probe_envelopes_checked=True,
            ownership_confirmed=True,tcp_load_match=True,
            validation_level='SAMPLED_CONTROLLER_IK_FK_AND_EXTERNAL_SCENE_CHECK',sample_count=count,
            scene_record=scene,full_continuous_collision_checked=False))

    def _check(self,o,profile,context,deadline):
        self._ready(context)
        if self.clock()>=deadline:raise MeasurementError('TIMEOUT','측정 동작 제한 시간 초과')
        if o['robot_state'] not in (1,2) or o['motion_status'] not in (0,1,2):
            raise MeasurementError('NOT_READY','이동 중 제어기 상태 변경')
        self._joint_guard(o['joints_deg'])
        if math.sqrt(sum(v*v for v in o['force_n']))>=profile['hard_force_n']:
            raise MeasurementError('FORCE_LIMIT','원신호 힘 한계 초과')

    def stop_measurement(self,profile):
        """정지 접수 뒤 새 관측의 위치·자세·관절 안정까지 확인한다.

        보호정지 상태에서도 정지 자체는 확인할 수 있으나, 이 결과가
        공정의 정지 latch 해제나 다음 동작 허용을 뜻하지는 않는다.
        """
        deadline=self.clock()+profile['timeout_s']
        try:
            self._emit_trace('stop_requested',dict(mode=profile['mode']))
            self.io.stop(profile['mode'])
            accepted_at=self.clock()
            anchor=None
            last_stamp=None
            while self.clock()<deadline:
                o=self._read()
                if self.clock()>=deadline:break
                stamp=o['measured_at_monotonic_s']
                if stamp<accepted_at or (last_stamp is not None and stamp<=last_stamp):
                    # 같은 캐시를 반복 읽은 시간으로 안정 구간을 채우지 않는다.
                    if last_stamp is None or stamp<last_stamp:anchor=None
                elif o['motion_status']==0 and o['robot_state'] in (1,3,5,6,9,10):
                    stable=(anchor is not None and
                            math.dist(o['tip_pose'][:3],anchor['tip_pose'][:3])<=self.g['movement_start_m'] and
                            rotation_distance(o['tip_pose'],anchor['tip_pose'])<=math.radians(self.g['movement_start_deg']) and
                            max(abs(a-b) for a,b in zip(o['joints_deg'],anchor['joints_deg']))<=self.g['movement_start_deg'])
                    if not stable:anchor=deepcopy(o)
                    elif stamp-anchor['measured_at_monotonic_s']>=self.g['stop_stable_s']:
                        self._emit_trace('stop_confirmed',o)
                        return StepResult('SUCCEEDED',observed_state={'stop_confirmed':True})
                else:anchor=None
                last_stamp=stamp if last_stamp is None else max(last_stamp,stamp)
                self.sleep(self.g['poll_s'])
        except Exception:
            pass
        return StepResult('UNKNOWN','STOP_UNCONFIRMED',observed_state={'stop_confirmed':False})

    def _deviation_error(self, step, o, line_error, line_limit, start_native, target_native, fraction):
        """선분 이탈을 자동 복구 후보와 즉시 중단으로 나눈다 (9/23 R1).

        허용치를 넓히지 않는다. 감지 기준은 그대로 두고, 아래 셋을 모두 만족할
        때만 복구 후보로 올린다. 하나라도 어긋나면 종전처럼 즉시 중단한다.
          1) 이탈이 즉시 중단 한계(hard_line_error_mm) 미만
          2) 제어기 지시 TCP 자체는 계획 선분 위 (명령/계획은 정상)
          3) 실제와 지시 TCP 의 추종 오차가 즉시 중단 한계 미만
        실제 정지·현재 위치 재관측·남은 계획 재검사는 호출자(measure_workpiece)가 한다.
        """
        text=f'이동 선분 이탈: {line_error:.3f} mm > {line_limit:.3f} mm'
        hard=self.g.get('hard_line_error_mm')
        desired=o.get('desired_posx')
        evidence=dict(label=step['label'],line_error_mm=line_error,limit_mm=line_limit,
                      hard_limit_mm=hard,actual_tcp=list(o['posx']),
                      desired_tcp=None if desired is None else list(desired),
                      start_tcp=list(start_native),target_tcp=list(target_native),fraction=fraction)
        if hard is None:
            return MeasurementError('PATH_DEVIATION',f'{text}: 즉시 중단 한계 미설정')
        if line_error>hard:
            return MeasurementError('PATH_DEVIATION',f'{text}: 즉시 중단 한계 {hard:.3f} mm 초과')
        if desired is None:
            return MeasurementError('PATH_DEVIATION',f'{text}: 지시 TCP 없음, 명령 경로 확인 불가')
        vector(desired,6,'desired_posx')
        v=[target_native[k]-start_native[k] for k in range(3)]
        length=sum(x*x for x in v)
        share=max(0,min(1,sum((desired[k]-start_native[k])*v[k] for k in range(3))/length)) if length else 0
        desired_error=math.dist(desired[:3],[start_native[k]+share*v[k] for k in range(3)])
        tracking=math.dist(o['posx'][:3],desired[:3])
        evidence.update(desired_line_error_mm=desired_error,tracking_error_mm=tracking)
        self._emit_trace('move_deviation_verdict',dict(evidence))
        if desired_error>self.g['line_error_mm']:
            return MeasurementError('PATH_DEVIATION',
                f'{text}: 제어기 지시 TCP 자체가 선분 이탈 {desired_error:.3f} mm')
        if tracking>hard:
            return MeasurementError('PATH_DEVIATION',
                f'{text}: 실제/지시 TCP 추종 오차 {tracking:.3f} mm 가 즉시 중단 한계 초과')
        return MoveRecoveryError('PATH_DEVIATION',
            f'{text} (지시 TCP 는 선분 위 {desired_error:.3f} mm, 추종 오차 {tracking:.3f} mm): 재정렬 후 재시도',
            evidence=evidence)

    def _move_line_limit(self, step, start_native, target_native):
        """상공의 자세 유지 이동만 별도 편차 허용. 표면 접근/회전에는 적용하지 않는다."""
        strict=self.g['line_error_mm']
        limit=self.g.get('overhead_line_error_mm',strict)
        if isinstance(limit,bool) or not isinstance(limit,(int,float)) or not math.isfinite(limit) or limit<strict:
            raise MeasurementError('PROFILE_MISMATCH','상공 선분 허용폭 설정 오류')
        scene=self.workcell.get('trial_scene')
        if not scene or step['kind']!='MOVE' or step['profile']!='travel':return strict
        start=posx_to_pose(start_native,self.offset);target=posx_to_pose(target_native,self.offset)
        if rotation_distance(start,target)>self.workcell['angle_tolerance_rad']:return strict
        # 자세 변화의 도구 끝 회전 반경까지 포함한 여유가 있어야 허용폭을 넓힌다.
        margin=limit/1000.+math.dist(self.offset,[0.,0.,0.])*self.workcell['angle_tolerance_rad']
        for native,tip in ((start_native,start),(target_native,target)):
            tcp=[v/1000. for v in native[:3]]
            if min(tcp[2],tip[2])-margin<scene['overhead_clearance_z_m']:return strict
            if any(not low+margin<=v<=high-margin for v,low,high in zip(tcp,scene['tcp_min_m'],scene['tcp_max_m'])):return strict
        return limit

    def execute_measurement_step(self,step,profile,context,timeout_s):
        deadline=self.clock()+min(profile['timeout_s'],timeout_s)
        o=self._read();self._check(o,profile,context,deadline)
        if o['robot_state']!=1 or o['motion_status']!=0:
            raise MeasurementError('NOT_READY','이동 시작 전 정지 미확인')
        target=step['target_pose']
        if tuple(target) not in self.expected:
            raise MeasurementError('NOT_READY','사전 검사하지 않은 목표')
        probe=step['kind']=='PROBE';start=o['tip_pose'];last_t=None
        before_search=probe and step.get('baseline_before_search') is True
        contact_range=step.get('contact_travel_range_m')
        if probe and step['profile']=='side_touch' and side_contact_window(self.workcell) is not None:
            if contact_range!=side_contact_window(self.workcell):
                raise MeasurementError('PROFILE_MISMATCH','검사한 접촉 구간과 실행 구간 불일치')
            if before_search != ('side_search_m' in self.workcell):
                raise MeasurementError('PROFILE_MISMATCH','검사한 baseline 위치와 실행 모드 불일치')

        if probe:
            if math.dist(start[:3],step['start_pose'][:3])>self.workcell['pose_tolerance_m']:
                raise MeasurementError('NOT_READY','접촉 시작 위치 불일치')
            samples=collections.deque();stable_start=self.clock();settle_anchor=start[:]
            while True:
                o=self._read();self._check(o,profile,context,deadline);now=self.clock()
                if o['motion_status']!=0:
                    raise MeasurementError('UNSTABLE_BASELINE','기준 힘 측정 중 실제 이동 상태')
                if (math.dist(o['tip_pose'][:3],step['start_pose'][:3])>self.workcell['pose_tolerance_m'] or
                    rotation_distance(o['tip_pose'],step['start_pose'])>self.workcell['angle_tolerance_rad']):
                    raise MeasurementError('UNSTABLE_BASELINE','기준 힘 수집 중 검사한 시작 위치/자세 이탈')
                if math.dist(o['tip_pose'][:3],settle_anchor[:3])>self.g['baseline_position_m']:
                    # 정지 상태의 작은 정착 변화는 창을 다시 수집한다. 전체 10초 제한은 유지.
                    samples.clear();settle_anchor=o['tip_pose'][:]
                    self._emit_trace('baseline_resettle',dict(label=step['label'],tip_pose=settle_anchor))
                desired=o.get('desired_posx')
                if desired is not None:
                    # 힘이 안정돼도 직전 이동의 서보 정착이 끝나지 않았을 수 있다.
                    # 기준 힘 수집의 정착 허용폭은 이동 생략 기준과 분리한다.
                    # 설정이 없으면 종전 기준을 사용한다. 힘 안정성/창 길이는 유지.
                    vector(desired,6,'desired_posx')
                    tracking_m=math.dist(o['posx'][:3],desired[:3])/1000.
                    tracking_angle=rotation_distance(o['tip_pose'],posx_to_pose(desired,self.offset))
                    tracking_limit=self.g.get('baseline_tracking_position_m',self.g['skip_position_m'])
                    if tracking_m>tracking_limit or tracking_angle>math.radians(self.g['skip_angle_deg']):
                        samples.clear()
                        if now-stable_start>=self.g['baseline_timeout_s']:
                            raise PointMeasurementError('UNSTABLE_BASELINE','기준 힘 수집 전 실제/지시 TCP 정착 미확인')
                        self.sleep(self.g['poll_s'])
                        continue
                along=sum(a*b for a,b in zip(step['direction'],o['force_n']))
                samples.append((now,along))
                while samples and now-samples[0][0]>profile['baseline_window_s']+self.g['baseline_window_slack_s']:samples.popleft()
                if now-samples[0][0]>=profile['baseline_window_s']:
                    values=[v for _,v in samples];bias=statistics.median(values)
                    half=len(values)//2
                    if half and statistics.median(abs(v-bias) for v in values)<=self.g['stationary_mad_n'] and abs(statistics.median(values[:half])-statistics.median(values[half:]))<=self.g['baseline_drift_n']:
                        start=o['tip_pose'][:]
                        self._emit_trace('stationary_baseline',dict(label=step['label'],bias_n=bias,settle_s=now-stable_start,
                            tracking_limit_m=self.g.get('baseline_tracking_position_m',self.g['skip_position_m'])))
                        break
                if now-stable_start>=self.g['baseline_timeout_s']:raise PointMeasurementError('UNSTABLE_BASELINE','기준 힘 안정화 실패')
                self.sleep(self.g['poll_s'])
        elif math.dist(start[:3],target[:3])<=self.g['skip_position_m'] and rotation_distance(start,target)<=math.radians(self.g['skip_angle_deg']) and max(abs(a-b) for a,b in zip(o['joints_deg'],self.expected[tuple(target)]))<=self.g['completion_joint_deg']:
            return StepResult('SUCCEEDED',observed_state={'stop_confirmed':True})
        start_native=o['posx'][:]
        line_limit=self.g['line_error_mm'] if probe else self._move_line_limit(step,start_native,self.native_targets[tuple(target)])
        self._emit_trace('command',dict(step=step,profile=profile,native_target=self.native_targets[tuple(target)],line_error_limit_mm=line_limit))
        self.io.move(self.native_targets[tuple(target)],profile['speed_m_s']*1000,
                     profile['acceleration_m_s2']*1000,self.g['angular_speed_deg_s'],self.g['angular_acc_deg_s2'])
        began=self.clock();moved=False;stable=None;moving_samples=collections.deque();moving_bias=None
        soft_since=None;progress_at=-math.inf;search_entered=False
        while True:
            o=self._read();self._check(o,profile,context,deadline);now=self.clock()
            if last_t is not None and o['measured_at_monotonic_s']<=last_t:
                raise MeasurementError('STALE_DATA','중복/역행 관측 시각')
            last_t=o['measured_at_monotonic_s']
            raw_norm=math.sqrt(sum(v*v for v in o['force_n']))
            if 'soft_force_n' in profile and raw_norm>=profile['soft_force_n']:
                if soft_since is None:soft_since=now
                if now-soft_since>=profile['soft_force_hold_s']:raise MeasurementError('FORCE_LIMIT','이동 중 힘 지속 한계')
            else:soft_since=None
            current=o['tip_pose'];excursion=math.dist(current[:3],start[:3])
            moved |= (o['motion_status']!=0 or excursion>self.g['movement_start_m'] or rotation_distance(current,start)>math.radians(self.g['movement_start_deg']))
            if not moved and now-began>self.g['movement_start_timeout_s']:
                raise MeasurementError('MOTION_NOT_STARTED','이동 시작 미확인; 재전송 없음')
            if probe:
                d=[current[k]-start[k] for k in range(3)]
                travel=sum(d[k]*step['direction'][k] for k in range(3))
                lateral=math.sqrt(sum((d[k]-travel*step['direction'][k])**2 for k in range(3)))
                if travel < -self.workcell['pose_tolerance_m'] or travel>step['max_m']+self.workcell['pose_tolerance_m'] or lateral>self.workcell['pose_tolerance_m'] or rotation_distance(current,start)>self.workcell['angle_tolerance_rad']:
                    self._emit_trace('probe_deviation',dict(label=step['label'],travel_m=travel,
                        lateral_m=lateral,angle_rad=rotation_distance(current,start),
                        start_tip_pose=start,actual_tip_pose=current,
                        actual_tcp=o['posx'],desired_tcp=o.get('desired_posx')))
                    raise MeasurementError('CONTACT_OUT_OF_RANGE',
                        f'접촉 탐색 선분/자세 이탈: 횡오차 {lateral*1000:.3f} mm')
                if now-progress_at>=2.:
                    phase=('BASELINE' if moving_bias is None else
                           'PRESEARCH' if before_search and travel<contact_range[0] else 'CONTACT_SEARCH')
                    self._emit_trace('probe_progress',dict(label=step['label'],travel_m=travel,
                        remaining_m=max(0,step['max_m']-travel),phase=phase))
                    progress_at=now
                along=sum(a*b for a,b in zip(step['direction'],o['force_n']))
                # 위치/기준힘 오류가 힘 한계 초과를 가려 재시도로 바뀌면 안 된다.
                reference_bias=bias if moving_bias is None else moving_bias
                limit=self.g['prebaseline_delta_n'] if moving_bias is None else profile['max_force_delta_n']
                if abs(along-reference_bias)>=limit:
                    raise MeasurementError('FORCE_LIMIT','빈 공간 힘 변화 초과' if moving_bias is None else '접촉 힘 변화 한계')
                if contact_range is not None:
                    if travel>contact_range[1]:
                        raise PointMeasurementError('CONTACT_NOT_FOUND','허용 접촉 구간 끝까지 표면 미검출')
                    if moving_bias is None and travel>=contact_range[0]:
                        # 접촉 후보를 baseline 표본으로 흡수하거나 정지 기준으로 대체하지 않는다.
                        raise PointMeasurementError('UNSTABLE_BASELINE','접촉 구간 진입 전 이동 baseline 확보 실패')
                    candidate_force=-(along-reference_bias)
                    if before_search:
                        if moving_bias is not None and travel<contact_range[0] and candidate_force>=profile['contact_force_n']:
                            raise MeasurementError('CONTACT_OUT_OF_RANGE','탐색 시작 전 비접촉 구간의 접촉: 재영점/재접근 금지')
                        if travel>=contact_range[0] and not search_entered:
                            search_entered=True
                            self._emit_trace('search_entered',dict(label=step['label'],travel_m=travel,
                                search_length_m=contact_range[1]-contact_range[0],frozen_bias_n=moving_bias))
                    elif travel<contact_range[0] and candidate_force>=profile['contact_force_n']:
                        # 구형 설정은 기존 접촉 창 계약을 유지한다. 새 10 mm 모드는 위 분기.
                        error=MeasurementError if moving_bias is None else PointMeasurementError
                        raise error('CONTACT_OUT_OF_RANGE','빈 공간 구간에서 접촉: 장애물 또는 초기 위치 범위 초과')
                if step['profile'] in ('side_touch','top_touch'):
                    if moving_bias is None:
                        if travel>=self.g['moving_baseline_start_m']:moving_samples.append((now,along))
                        while moving_samples and now-moving_samples[0][0]>profile['baseline_window_s']+self.g['baseline_window_slack_s']:moving_samples.popleft()
                        if travel>=self.g['moving_baseline_end_m']:
                            if len(moving_samples)<2 or moving_samples[-1][0]-moving_samples[0][0]<profile['baseline_window_s']:
                                raise PointMeasurementError('UNSTABLE_BASELINE','이동 기준 힘 표본 부족')
                            values=[v for _,v in moving_samples];candidate=statistics.median(values);half=len(values)//2
                            if statistics.median(abs(v-candidate) for v in values)>self.g['moving_mad_n'] or abs(statistics.median(values[:half])-statistics.median(values[half:]))>self.g['baseline_drift_n']:
                                raise PointMeasurementError('UNSTABLE_BASELINE','이동 기준 힘 불안정')
                            moving_bias=candidate
                            self._emit_trace('moving_baseline',dict(label=step['label'],bias_n=candidate,travel_m=travel))
                        normal=None
                    else:normal=-(along-moving_bias)
                else:normal=-(along-bias)
                if before_search and travel<contact_range[0]:normal=None
                if normal is not None:
                    if abs(normal)>=profile['max_force_delta_n']:raise MeasurementError('FORCE_LIMIT','접촉 힘 변화 한계')
                    if normal>=profile['contact_force_n']:
                        stopped=self.stop_measurement(self.stop_profile)
                        if not stopped.ok:raise MeasurementError('STOP_UNCONFIRMED','접촉 후 정지 미확인','UNKNOWN')
                        return StepResult('SUCCEEDED',observed_state=dict(stop_confirmed=True,contact=dict(
                            detected=True,tip_pose=current,frame_id='c2_base',normal_force_n=normal,
                            measured_at_monotonic_s=o['measured_at_monotonic_s'],operator_confirmed=False)))
                if moved and o['motion_status']==0:
                    raise PointMeasurementError('CONTACT_NOT_FOUND','표면 접촉 없이 탐색 종료')
            else:
                # 제어기 TCP 선분 감시. 회전 중 드릴 끝 궤적은 선형이 아니다.
                a=start_native;b=self.native_targets[tuple(target)];v=[b[k]-a[k] for k in range(3)]
                length=sum(x*x for x in v);fraction=max(0,min(1,sum((o['posx'][k]-a[k])*v[k] for k in range(3))/length)) if length else 0
                line_error=math.dist(o['posx'][:3],[a[k]+fraction*v[k] for k in range(3)])
                if line_error>self.g['line_error_mm']:
                    self._emit_trace('move_deviation',dict(label=step['label'],line_error_mm=line_error,
                        limit_mm=line_limit,start_tcp=a,target_tcp=b,actual_tcp=o['posx'],desired_tcp=o.get('desired_posx')))
                if line_error>line_limit:
                    raise self._deviation_error(step,o,line_error,line_limit,a,b,fraction)
                if line_limit>self.g['line_error_mm']:
                    # 넓힌 허용폭 안에서도 실제 자세와 목표 사이의 도구/양초 통과를 재검사한다.
                    checked=self.scene_check([step],self.workcell,o)
                    if checked.get('path_checked') is not True or checked.get('probe_envelopes_checked') is not True:
                        raise MeasurementError('SCENE_REJECTED','상공 실제 위치에서 남은 이동 간섭 검사 실패')
                joint_error=max(abs(a-b) for a,b in zip(o['joints_deg'],self.expected[tuple(target)]))
                complete=moved and o['robot_state']==1 and o['motion_status']==0 and math.dist(current[:3],target[:3])<=self.workcell['pose_tolerance_m'] and rotation_distance(current,target)<=self.workcell['angle_tolerance_rad'] and joint_error<=self.g['completion_joint_deg']
                if complete:
                    if stable is None:stable=now
                    if now-stable>=self.g['completion_stable_s']:
                        self._emit_trace('stop_confirmed',o)
                        return StepResult('SUCCEEDED',observed_state={'stop_confirmed':True})
                else:stable=None
            self.sleep(self.g['poll_s'])
