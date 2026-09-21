"""공정 노드 내부 측정 어댑터 구성. 새 노드/서비스/Action을 만들지 않는다.

작업 스레드에서 생성·호출하고 공정 노드 executor는 별도로 계속 spin해야 한다.
측정 함수가 공정의 공유 motion_lock을 획득한다. 호출자가 먼저 같은 Lock을 잡지 않는다.
"""
import math
import time
from .measurement_robot_adapter import GuardedMeasurementAdapter, RosMeasurementIO
from .workpiece_calibration import MeasurementError


class ProcessMeasurementReadiness:
    """준비 요청에 귀속된 실제 관측 근거와 제어기 설정을 재확인한다."""
    def __init__(self, io, workcell, context, motion_lock, cancel, evidence_provider,
                 evidence_max_age_s, *, clock=time.monotonic):
        if context.source_mode!='REAL' or context.motion_lock is not motion_lock or context.cancel is not cancel:
            raise ValueError('REAL context에 공정의 동일 공유 잠금·취소 Event 필요')
        if not callable(evidence_provider):raise ValueError('실제 준비 관측 공급 함수 필요')
        for key in ('control_authority','mount_fixed','drill_off_confirmed'):
            value=evidence_max_age_s.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('근거별 유효기간(초)을 명시해야 함: '+key)
        self.io=io;self.w=workcell;self.ctx=context;self.lock=motion_lock;self.cancel=cancel
        self.provider=evidence_provider;self.ages=dict(evidence_max_age_s);self.clock=clock
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
                    ownership_confirmed=True,control_authority=True,mount_fixed=True,
                    drill_off_confirmed=True,evidence=sources)

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
