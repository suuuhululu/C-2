"""현장 단독 시험용 팩터리. 기존 공정 노드와 동시에 실행하지 않는다.

그리퍼 밑면 오프셋 미확인 시 CONTACT_REFERENCE로만 측정하며 geometry_ready=False.
상수 True 검사 콜백 대신 제한된 실험 경로/도구 선분 검사와 장치 상태 재관측을 사용.
전체 로봇/케이블 메시 충돌 검사나 작업셀 인증이 아니다.
"""
import fcntl
import hashlib
from pathlib import Path
import threading
import time
from .measurement_robot_adapter import (RosMeasurementIO, GuardedMeasurementAdapter,
                                        check_measurement_scene)

# 기존 import 경로 유지용 별칭. 본문은 measurement_robot_adapter 가 소유한다.
check_trial_scene = check_measurement_scene


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
