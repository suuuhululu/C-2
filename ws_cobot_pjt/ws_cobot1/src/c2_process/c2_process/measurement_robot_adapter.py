"""양초 측정 전용 어댑터 내부 구현. ROS 노드/Action 서버를 새로 만들지 않는다.

REAL 전제: 실제 TCP/하중/장착 기준, 그리퍼 밑면 오프셋, 전 경로 현장 검사,
공통 모션 소유권을 확인하는 readiness/scene_check를 호출자가 제공한다.
기존 DoosanRobotAdapter를 변경하지 않고 검증된 관측·정지 계약을 분리한다.
"""
import collections
from copy import deepcopy
import math
import statistics
import threading
import time

from .robot_adapter import StepResult, pose_to_posx, posx_to_pose, apply_tool_offset
from .workpiece_calibration import MeasurementError, pose, vector, rotation_distance


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
        required=('ownership_confirmed','drill_off_confirmed','mount_fixed','control_authority')
        if any(report.get(k) is not True for k in required) or report.get('measurement_id')!=context.measurement_id:
            raise MeasurementError('NOT_READY','실행 소유권/드릴 OFF/고정/제어권 확인 필요')
        if not 0<=self.clock()-report['checked_at_monotonic_s']<=self.g['max_state_age_s']:
            raise MeasurementError('NOT_READY','준비 조건 확인 만료')

    def preflight_measurement(self,steps,workcell,profiles,context):
        self._ready(context)
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
        self.current_context=context;self.workcell=workcell;self.stop_profile=profiles['stop']
        deadline=self.clock()+min(self.g['preflight_timeout_s'],workcell['runtime_timeout_s'])
        self.expected.clear();self.native_targets.clear()
        if self.offset!=workcell['tool_offset_m']:
            raise MeasurementError('PROFILE_MISMATCH','어댑터/측정 설정 도구 오프셋 불일치')
        metadata=self.io.metadata()
        if metadata['tcp_id']!=workcell['tcp_id'] or metadata['load_id']!=workcell['load_id'] or metadata['robot_mode']!=1 or metadata['robot_system']!=0:
            raise MeasurementError('PROFILE_MISMATCH','실제 장치의 TCP/하중/REAL/AUTO 불일치')
        self.space=metadata['solution_space']
        initial=self._read(); prev=initial['posx']; q=initial['joints_deg'];self._joint_guard(q)
        if initial['robot_state']!=1 or initial['motion_status']!=0:
            raise MeasurementError('NOT_READY','이동 검사 시작 시 정지 미확인')
        # 그리퍼/드릴/철사/양초/작업대의 전체 경로와 접촉 구간 후퇴를 승인하는 검사기.
        # 좌표가 유한하다는 이유만으로 간섭 검사를 통과시키지 않는다.
        scene=self.scene_check(steps,workcell,initial)
        if scene.get('path_checked') is not True or scene.get('probe_envelopes_checked') is not True:
            raise MeasurementError('NOT_READY','진입/원호/접촉/후퇴의 현장 간섭 검사 미완료')
        count=0
        for step in steps:
            target=continuous_target(step['target_pose'],self.offset,prev)
            self.native_targets[tuple(step['target_pose'])]=target[:]
            n=max(1,math.ceil(math.dist(prev[:3],target[:3])/self.g['ik_step_mm']),
                  math.ceil(max(abs(a-b) for a,b in zip(prev[3:],target[3:]))/self.g['ik_step_deg']))
            if n>self.g['max_samples_per_segment']:
                raise MeasurementError('PLAN_TOO_LARGE','ZYZ 회전 또는 경로 분할 범위 초과')
            for i in range(1,n+1):
                self._ready(context)
                if self.clock()>=deadline:raise MeasurementError('TIMEOUT','측정 이동 사전 검사 시간 초과')
                point=interpolate(prev,target,i/n)
                nxt=self.io.ik(point,self.space)
                for axis in (0,3,5):nxt[axis]+=360*round((q[axis]-nxt[axis])/360)
                self._joint_guard(nxt)
                if max(abs(a-b) for a,b in zip(q,nxt))>self.g['max_joint_step_deg']:
                    raise MeasurementError('IK_DISCONTINUITY','IK 해 불연속')
                fk=self.io.fk(nxt)
                if math.dist(fk[:3],point[:3])>self.g['fk_position_mm'] or rotation_distance(posx_to_pose(fk),posx_to_pose(point))>math.radians(self.g['fk_angle_deg']):
                    raise MeasurementError('IK_FK_MISMATCH','IK/FK 대조 실패')
                q=nxt;count+=1
                self._emit_trace("ik_sample",dict(label=step["label"],sample=count,native_tcp=point,joints_deg=q))
            self.expected[tuple(step['target_pose'])]=q[:];prev=target
        self._ready(context)
        return StepResult('SUCCEEDED',observed_state=dict(all_segments_checked=True,probe_envelopes_checked=True,
            ownership_confirmed=True,drill_off_confirmed=True,tcp_load_match=True,
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
                    # 위치 도달 생략 기준과 같은 정밀도로 실제/지시 TCP를 대조한다.
                    vector(desired,6,'desired_posx')
                    tracking_m=math.dist(o['posx'][:3],desired[:3])/1000.
                    tracking_angle=rotation_distance(o['tip_pose'],posx_to_pose(desired,self.offset))
                    if tracking_m>self.g['skip_position_m'] or tracking_angle>math.radians(self.g['skip_angle_deg']):
                        samples.clear()
                        if now-stable_start>=self.g['baseline_timeout_s']:
                            raise MeasurementError('UNSTABLE_BASELINE','기준 힘 수집 전 실제/지시 TCP 정착 미확인')
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
                        self._emit_trace('stationary_baseline',dict(label=step['label'],bias_n=bias,settle_s=now-stable_start))
                        break
                if now-stable_start>=self.g['baseline_timeout_s']:raise MeasurementError('UNSTABLE_BASELINE','기준 힘 안정화 실패')
                self.sleep(self.g['poll_s'])
        elif math.dist(start[:3],target[:3])<=self.g['skip_position_m'] and rotation_distance(start,target)<=math.radians(self.g['skip_angle_deg']) and max(abs(a-b) for a,b in zip(o['joints_deg'],self.expected[tuple(target)]))<=self.g['completion_joint_deg']:
            return StepResult('SUCCEEDED',observed_state={'stop_confirmed':True})
        start_native=o['posx'][:]
        line_limit=self.g['line_error_mm'] if probe else self._move_line_limit(step,start_native,self.native_targets[tuple(target)])
        self._emit_trace('command',dict(step=step,profile=profile,native_target=self.native_targets[tuple(target)],line_error_limit_mm=line_limit))
        self.io.move(self.native_targets[tuple(target)],profile['speed_m_s']*1000,
                     profile['acceleration_m_s2']*1000,self.g['angular_speed_deg_s'],self.g['angular_acc_deg_s2'])
        began=self.clock();moved=False;stable=None;moving_samples=collections.deque();moving_bias=None
        soft_since=None;progress_at=-math.inf
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
                    self._emit_trace('probe_progress',dict(label=step['label'],travel_m=travel,
                        remaining_m=max(0,step['max_m']-travel),phase='BASELINE' if moving_bias is None else 'CONTACT_SEARCH'))
                    progress_at=now
                along=sum(a*b for a,b in zip(step['direction'],o['force_n']))
                if step['profile'] in ('side_touch','top_touch'):
                    if moving_bias is None:
                        # 빈 공간의 이동 기준 수집 한계와 기준 확립 후 접촉 한계를 분리한다.
                        limit=self.g['prebaseline_delta_n']
                        if abs(along-bias)>=limit:raise MeasurementError('FORCE_LIMIT','빈 공간 힘 변화 초과')
                        if travel>=self.g['moving_baseline_start_m']:moving_samples.append((now,along))
                        while moving_samples and now-moving_samples[0][0]>profile['baseline_window_s']+self.g['baseline_window_slack_s']:moving_samples.popleft()
                        if travel>=self.g['moving_baseline_end_m']:
                            if len(moving_samples)<2 or moving_samples[-1][0]-moving_samples[0][0]<profile['baseline_window_s']:
                                raise MeasurementError('UNSTABLE_BASELINE','이동 기준 힘 표본 부족')
                            values=[v for _,v in moving_samples];candidate=statistics.median(values);half=len(values)//2
                            if statistics.median(abs(v-candidate) for v in values)>self.g['moving_mad_n'] or abs(statistics.median(values[:half])-statistics.median(values[half:]))>self.g['baseline_drift_n']:
                                raise MeasurementError('UNSTABLE_BASELINE','이동 기준 힘 불안정')
                            moving_bias=candidate
                            self._emit_trace('moving_baseline',dict(label=step['label'],bias_n=candidate,travel_m=travel))
                        normal=None
                    else:normal=-(along-moving_bias)
                else:normal=-(along-bias)
                if normal is not None:
                    if abs(normal)>=profile['max_force_delta_n']:raise MeasurementError('FORCE_LIMIT','접촉 힘 변화 한계')
                    if normal>=profile['contact_force_n']:
                        stopped=self.stop_measurement(self.stop_profile)
                        if not stopped.ok:raise MeasurementError('STOP_UNCONFIRMED','접촉 후 정지 미확인','UNKNOWN')
                        return StepResult('SUCCEEDED',observed_state=dict(stop_confirmed=True,contact=dict(
                            detected=True,tip_pose=current,frame_id='c2_base',normal_force_n=normal,
                            measured_at_monotonic_s=o['measured_at_monotonic_s'],operator_confirmed=False)))
                if moved and o['motion_status']==0:
                    raise MeasurementError('CONTACT_NOT_FOUND','표면 접촉 없이 탐색 종료')
            else:
                # 제어기 TCP 선분 감시. 회전 중 드릴 끝 궤적은 선형이 아니다.
                a=start_native;b=self.native_targets[tuple(target)];v=[b[k]-a[k] for k in range(3)]
                length=sum(x*x for x in v);fraction=max(0,min(1,sum((o['posx'][k]-a[k])*v[k] for k in range(3))/length)) if length else 0
                line_error=math.dist(o['posx'][:3],[a[k]+fraction*v[k] for k in range(3)])
                if line_error>self.g['line_error_mm']:
                    self._emit_trace('move_deviation',dict(label=step['label'],line_error_mm=line_error,
                        limit_mm=line_limit,start_tcp=a,target_tcp=b,actual_tcp=o['posx'],desired_tcp=o.get('desired_posx')))
                if line_error>line_limit:
                    raise MeasurementError('PATH_DEVIATION',f'이동 선분 이탈: {line_error:.3f} mm > {line_limit:.3f} mm')
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
