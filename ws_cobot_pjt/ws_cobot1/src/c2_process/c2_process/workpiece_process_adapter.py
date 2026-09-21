"""공정 노드 내부 측정 어댑터 구성. 새 노드/서비스/Action을 만들지 않는다.

작업 스레드에서 생성·호출하고 공정 노드 executor는 별도로 계속 spin해야 한다.
측정 함수가 공정의 공유 motion_lock을 획득한다. 호출자가 먼저 같은 Lock을 잡지 않는다.
"""
import math
import re
import time
from .measurement_robot_adapter import GuardedMeasurementAdapter, RosMeasurementIO
from .workpiece_calibration import MeasurementError


_PROCESS_LABEL = re.compile(
    r"(?:home_(?:escape_slow|escape_outer|down|lift|align|x|y)"
    r"|top_(?:entry|approach|touch|retract|exit)"
    r"|side_entry(?:_above)?|orbit|point_[1-9][0-9]*_(?:approach|touch|retract|outer))\Z"
)


def check_process_scene(steps, workcell, initial_state):
    """승인된 현장 모델로 준비 측정의 모든 진입·접촉·후퇴 구간을 검사한다.

    좌표계와 m 단위 필드 형식을 먼저 fail-closed로 확인한 뒤, 현장 시험에서
    검증한 통로·원통/도구 선분 검사기를 호출한다. 전체 로봇 메시 충돌 검사는
    별도 범위이며, 승인 기록이나 모델이 없으면 경로를 허용하지 않는다.
    """
    def finite(value):
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value))

    def vector(value, size, name, *, absolute_limit=None):
        if not isinstance(value, (list, tuple)) or len(value) != size or not all(map(finite, value)):
            raise MeasurementError('NOT_READY', f'현장 검사 {name} 형식/유한값 오류')
        if absolute_limit is not None and any(abs(v) > absolute_limit for v in value):
            raise MeasurementError('NOT_READY', f'현장 검사 {name} m 단위 범위 오류')
        return value

    if not isinstance(workcell, dict) or workcell.get('source_mode') != 'REAL':
        raise MeasurementError('NOT_READY', 'REAL 작업셀 설정 없음')
    if workcell.get('frame_id') != 'c2_base':
        raise MeasurementError('SCENE_REJECTED', '현장 검사는 c2_base 좌표계만 허용')
    vector(workcell.get('seed_axis_xy_m'), 2, 'seed_axis_xy_m', absolute_limit=5.)
    vector(workcell.get('tool_offset_m'), 3, 'tool_offset_m', absolute_limit=1.)
    radius = workcell.get('seed_radius_m')
    if not finite(radius) or not 0 < radius <= 1.:
        raise MeasurementError('NOT_READY', 'seed_radius_m의 m 단위 범위 오류')

    scene = workcell.get('trial_scene')
    if not isinstance(scene, dict) or not isinstance(scene.get('environment_record_id'), str) or not scene['environment_record_id'].strip():
        raise MeasurementError('NOT_READY', '승인된 현장 환경 기록과 trial_scene 필요')
    low = vector(scene.get('tcp_min_m'), 3, 'trial_scene.tcp_min_m', absolute_limit=5.)
    high = vector(scene.get('tcp_max_m'), 3, 'trial_scene.tcp_max_m', absolute_limit=5.)
    if any(a >= b for a, b in zip(low, high)):
        raise MeasurementError('NOT_READY', '현장 TCP 작업 범위 최소/최대 오류')
    for key in ('sample_mm', 'sample_deg', 'upright_tolerance_deg',
                'overhead_clearance_z_m', 'top_xy_tolerance_m', 'top_tcp_min_z_m',
                'outer_min_gap_m', 'model_tolerance_m', 'facing_tolerance_deg'):
        value = scene.get(key)
        if not finite(value) or value <= 0:
            raise MeasurementError('NOT_READY', f'현장 검사 설정 오류: {key}')

    if not isinstance(initial_state, dict):
        raise MeasurementError('NOT_READY', '현장 검사 시작 상태 없음')
    vector(initial_state.get('posx'), 6, 'initial_state.posx')
    if not isinstance(steps, (list, tuple)) or not steps:
        raise MeasurementError('NOT_READY', '검사할 측정 경로 없음')
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get('kind') not in {'MOVE', 'PROBE'}:
            raise MeasurementError('SCENE_REJECTED', f'지원하지 않는 측정 구간: {index}')
        label = step.get('label')
        if not isinstance(label, str) or _PROCESS_LABEL.fullmatch(label) is None:
            raise MeasurementError('SCENE_REJECTED', f'승인되지 않은 측정 구간 label: {label}')
        pose = vector(step.get('target_pose'), 7, f'steps[{index}].target_pose',
                      absolute_limit=5.)
        norm = math.sqrt(sum(v*v for v in pose[3:]))
        if not math.isclose(norm, 1., rel_tol=0., abs_tol=1e-6):
            raise MeasurementError('SCENE_REJECTED', f'측정 자세 quaternion 오류: {label}')
        if step['kind'] == 'PROBE':
            vector(step.get('start_pose'), 7, f'steps[{index}].start_pose',
                   absolute_limit=5.)
            vector(step.get('direction'), 3, f'steps[{index}].direction')
            distance = step.get('max_m')
            if not finite(distance) or not 0 < distance <= 0.1:
                raise MeasurementError('SCENE_REJECTED', f'접촉 탐색 거리의 m 단위 범위 오류: {label}')

    # 기존 현장 시험에서 검증된 실제 통로 모델을 공정에서도 동일하게 사용한다.
    from .workpiece_real_trial import check_trial_scene
    report = check_trial_scene(steps, workcell, initial_state)
    if (not isinstance(report, dict) or report.get('path_checked') is not True
            or report.get('probe_envelopes_checked') is not True
            or report.get('environment_record_id') != scene['environment_record_id']):
        raise MeasurementError('NOT_READY', '현장 경로 검사 결과 또는 승인 기록 불일치')
    return report


class ProcessMeasurementReadiness:
    """준비 요청에 귀속된 실제 관측 근거와 제어기 설정을 재확인한다."""
    def __init__(self, io, workcell, context, motion_lock, cancel, evidence_provider,
                 evidence_max_age_s, *, clock=time.monotonic):
        if context.source_mode!='REAL' or context.motion_lock is not motion_lock or context.cancel is not cancel:
            raise ValueError('REAL context에 공정의 동일 공유 잠금·취소 Event 필요')
        if not callable(evidence_provider):raise ValueError('실제 준비 관측 공급 함수 필요')
        for key in ('control_authority',):
            value=evidence_max_age_s.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('근거별 유효기간(초)을 명시해야 함: '+key)
        self.io=io;self.w=workcell;self.ctx=context;self.lock=motion_lock;self.cancel=cancel
        self.provider=evidence_provider;self.ages={'control_authority':evidence_max_age_s['control_authority']};self.clock=clock
        self.metadata=None;self.metadata_at=-math.inf;self.closed=False

    def __call__(self, context):
        if self.closed or context is not self.ctx or context.motion_lock is not self.lock or context.cancel is not self.cancel or not self.lock.locked():
            raise MeasurementError('NOT_READY','공정 측정 소유권/공유 잠금 불일치')
        now=self.clock();evidence=self.provider(context)
        if not isinstance(evidence,dict) or evidence.get('measurement_id')!=context.measurement_id:
            raise MeasurementError('NOT_READY','준비 관측의 측정 ID 불일치')
        sources={}
        for key in self.ages:
            item=evidence.get(key,{})
            stamp=item.get('observed_at_monotonic_s')
            if (item.get('value') is not True or item.get('valid') is not True or
                not isinstance(stamp,(float,int)) or isinstance(stamp,bool) or not math.isfinite(stamp) or
                not 0<=now-stamp<=self.ages[key] or not isinstance(item.get('source'),str) or not item['source']):
                raise MeasurementError('NOT_READY','근거 누락·만료·미확인: '+key)
            if key=='control_authority' and item['source']!='CONTROLLER_ACCESS_CONTROL':
                raise MeasurementError('NOT_READY','제어권은 실제 access-control 근거 필요; AUTO/TCP 상태로 대체 불가')
            sources[key]=dict(item)
        # 많은 IK 표본마다 같은 ROS 설정 조회를 반복하지 않는다. 실패한 조회는 즉시 전파.
        if now-self.metadata_at>=.2:
            self.metadata=self.io.metadata();self.metadata_at=self.clock()
        meta=self.metadata
        if meta['robot_mode']!=1 or meta['robot_system']!=0 or meta['tcp_id']!=self.w['tcp_id'] or meta['load_id']!=self.w['load_id']:
            raise MeasurementError('PROFILE_MISMATCH','공정 측정의 AUTO/REAL/TCP/하중 설정 불일치')
        return dict(measurement_id=context.measurement_id,checked_at_monotonic_s=self.clock(),
                    ownership_confirmed=True,control_authority=True,evidence=sources)

    def close(self):
        self.closed=True  # 공정 노드·공유 잠금·취소 Event는 종료하거나 해제하지 않는다.


def create_process_measurement_adapter(node, config, context, *, motion_lock, cancel,
                                       evidence_provider, evidence_max_age_s, scene_check):
    """공정 노드에서 호출. 생성만으로 로봇 이동/설정 변경/제어권 요청을 하지 않는다.

    scene_check(steps, workcell, initial_state)는 현장 승인된 경로 검사기를 주입한다.
    단독 시험 TrialLease나 별도 파일 잠금, 공정 노드 존재 거절은 사용하지 않는다.
    """
    io=RosMeasurementIO(node,config['controller_prefix'],config['service_timeout_s'])
    readiness=ProcessMeasurementReadiness(io,config['workcell'],context,motion_lock,cancel,
                                        evidence_provider,evidence_max_age_s)
    adapter=GuardedMeasurementAdapter(io,config['workcell']['tool_offset_m'],config['guards'],readiness,scene_check)
    adapter.close=readiness.close
    trace=getattr(node,'workpiece_trace',None)
    if trace is not None:adapter.trace=trace
    return adapter
