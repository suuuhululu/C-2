#!/usr/bin/env python3
"""두 터미널 단독 시험 수신부. 팀 공통 Action/운영 노드가 아니다.

터미널 1: python3 test/workpiece_test_node.py --mode SIMULATION
터미널 2: ros2 service call /workpiece_test/start std_srvs/srv/Trigger '{}'

REAL: --mode REAL --operator-ready. 현장 시험 설정과 내장 팩터리를 사용한다.
팩터리 create_adapter(node, config, context)는 준비/환경 검사까지 연결한
GuardedMeasurementAdapter를 반환해야 한다. 미완성 설정을 SIM 값으로 대체하지 않는다.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import sys
import signal
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c2_process.robot_adapter import StepResult
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece, _validate
from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter


class TrialSession:
    """ROS와 무관한 시험 수신/취소/중복 실행 처리. 실제 측정 함수를 호출한다."""
    def __init__(self, config, mode, adapter_factory, emit, config_sha256):
        self.config=deepcopy(config); self.mode=mode; self.adapter_factory=adapter_factory
        self.emit=emit; self.config_sha256=config_sha256
        self._state_lock=threading.RLock(); self.motion_lock=threading.Lock()
        self.thread=None; self.context=None; self.adapter=None
        self.state=dict(status='IDLE',source_mode=mode,measurement_id=None,result=None)
        _validate(self.config['workcell'],self.config['profiles'],self._context('startup-validation'))

    def _context(self,ident):
        return MeasurementContext(ident,'unit-test-preparation-'+ident,self.mode,
            motion_lock=self.motion_lock,profile_snapshot_id='local-test-config-'+self.config_sha256[:12],
            profile_sha256=self.config_sha256)

    def start(self):
        with self._state_lock:
            if self.state['status']=='UNKNOWN':
                return False,'이전 시험 정지 미확인. 상태 확인 전 재시작 금지'
            if self.thread is not None and self.thread.is_alive():
                return False,'BUSY: 이미 측정 중'
            ident='workpiece-test-'+uuid.uuid4().hex
            self.context=self._context(ident)
            self.state=dict(status='STARTING',source_mode=self.mode,measurement_id=ident,result=None)
            self.thread=threading.Thread(target=self._run,args=(self.context,),daemon=False)
            self.thread.start()
            return True,json.dumps(dict(accepted=True,source_mode=self.mode,measurement_id=ident,
                                        note='접수만 완료. 최종 결과는 /workpiece_test/result 또는 status 확인'),ensure_ascii=False)

    def _run(self,ctx):
        try:
            # 서비스 callback 밖 작업 스레드에서 생성/실행. executor는 계속 통신 처리.
            adapter=self.adapter_factory(ctx)
            self.adapter=adapter
            if self.mode=='REAL':
                self.emit('feedback',dict(measurement_id=ctx.measurement_id,sequence=0,stage='ANNOUNCE',
                                         status='RUNNING',message='드릴 OFF 단독 측정을 시작합니다. 2초 후 사전 검사합니다.'))
                ctx.cancel.wait(2.)
            result=measure_workpiece(adapter,self.config['workcell'],self.config['profiles'],ctx,
                                     lambda event:self.emit('feedback',event))
        except Exception as exc:
            # 팩터리는 로봇을 이동시키지 않아야 한다. 예외 시 성공으로 응답하지 않는다.
            result=StepResult('UNKNOWN','TEST_BACKEND_ERROR',str(exc),'workpiece_test')
        if result.outcome!='UNKNOWN' and self.adapter is not None and callable(getattr(self.adapter,'close',None)):
            self.adapter.close()
        payload=asdict(result)
        with self._state_lock:
            self.state['status']=result.outcome; self.state['result']=payload
        self.emit('result',dict(measurement_id=ctx.measurement_id,source_mode=self.mode,**payload))

    def cancel(self):
        with self._state_lock:
            if self.thread is None or not self.thread.is_alive():return False,'실행 중인 측정 없음'
            self.context.cancel.set()
            return True,'CANCEL_REQUESTED: 실제 정지 결과는 result/status에서 확인'

    def status(self):
        with self._state_lock:return deepcopy(self.state)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['SIMULATION','REAL'],default='SIMULATION')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--operator-ready',action='store_true',help='REAL: 드릴 OFF, 고정/주변 공간 유지, 단독 제어 및 비상정지 대기 확인')
    parser.add_argument('--output-dir',type=Path,default=Path('/tmp/workpiece-unit-test'))
    parser.add_argument('--backend-factory',help='REAL 전용: module:function, 인자는 (node, config, context)')
    args=parser.parse_args(argv)
    if args.mode=='REAL' and not args.operator_ready:
        parser.error('REAL은 --operator-ready로 현장 단독 시험 조건을 확인해야 합니다.')
    if args.mode=='REAL':
        args.config=args.config or Path(__file__).resolve().parents[1]/'config/workpiece_real_trial_0921.json'
        args.backend_factory=args.backend_factory or 'c2_process.workpiece_real_trial:create_adapter'
    config_path=args.config or Path(__file__).resolve().parents[1]/'config/workpiece_simulation.json'
    raw=config_path.read_bytes();config=json.loads(raw);digest=hashlib.sha256(raw).hexdigest()
    if args.mode=='REAL':config['standalone_operator_acknowledged']=args.operator_ready
    args.output_dir.mkdir(parents=True,exist_ok=True)
    trace_path=args.output_dir/('workpiece_'+uuid.uuid4().hex+'.jsonl')
    trace_file=trace_path.open('x'); trace_lock=threading.Lock()
    real_factory=None
    if args.mode=='REAL':
        module_name,separator,function_name=args.backend_factory.partition(':')
        if not separator:parser.error('--backend-factory는 module:function 형식')
        real_factory=getattr(importlib.import_module(module_name),function_name)
        if not callable(real_factory):parser.error('backend factory가 함수가 아님')
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
    from std_msgs.msg import String
    from std_srvs.srv import Trigger
    from rclpy.signals import SignalHandlerOptions
    rclpy.init(args=[],signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGINT,signal.default_int_handler)
    node=rclpy.create_node('workpiece_test')
    executor=MultiThreadedExecutor(num_threads=2);executor.add_node(node)
    qos=QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE,
                   durability=DurabilityPolicy.TRANSIENT_LOCAL)
    feedback_pub=node.create_publisher(String,'/workpiece_test/feedback',qos)
    result_pub=node.create_publisher(String,'/workpiece_test/result',qos)
    telemetry_pub=node.create_publisher(String,'/workpiece_test/telemetry',10)
    def emit(kind,data):
        msg=String();msg.data=json.dumps(data,ensure_ascii=False,allow_nan=False)
        {'feedback':feedback_pub,'result':result_pub,'telemetry':telemetry_pub}[kind].publish(msg)
        with trace_lock:
            trace_file.write(json.dumps(dict(channel=kind,data=data),ensure_ascii=False,allow_nan=False)+'\n');trace_file.flush()
        if kind!='telemetry':node.get_logger().info(data.get('message') or f"{kind}: {data.get('outcome','')}")
    def trace(event,data):
        emit('telemetry',dict(event=event,source_mode=args.mode,measurement_id=session.context.measurement_id if session.context else None,**data))
        if event=='probe_progress':
            phase='이동 기준 힘 수집 중' if data['phase']=='BASELINE' else '접촉 탐색 중'
            node.get_logger().info(f"{data['label']}: {phase}, 이동 {data['travel_m']*1000:.2f} mm / 남은 탐색 {data['remaining_m']*1000:.2f} mm")
    node.workpiece_trace=trace
    def create_adapter(ctx):
        if args.mode=='SIMULATION':
            return SimulatedWorkpieceAdapter(config['workcell'],clock=ctx.monotonic)
        return real_factory(node,deepcopy(config),ctx)
    session=TrialSession(config,args.mode,create_adapter,emit,digest)
    def start(_request,response):response.success,response.message=session.start();return response
    def cancel(_request,response):response.success,response.message=session.cancel();return response
    def status(_request,response):
        response.success=True;response.message=json.dumps(session.status(),ensure_ascii=False,allow_nan=False);return response
    services=[node.create_service(Trigger,'/workpiece_test/start',start),
              node.create_service(Trigger,'/workpiece_test/cancel',cancel),
              node.create_service(Trigger,'/workpiece_test/status',status)]
    node.get_logger().info(f'대기 중: mode={args.mode}; /workpiece_test/start 호출 시 측정 함수 실행. 기록: {trace_path}')
    if args.mode=='SIMULATION':node.get_logger().info('SIMULATION: 실제 로봇에 연결하거나 움직이지 않습니다.')
    spin_thread=threading.Thread(target=executor.spin,daemon=True)
    spin_thread.start()
    try:
        while spin_thread.is_alive():spin_thread.join(.2)
    except KeyboardInterrupt:
        session.cancel()
        # 정지 확인이 끝날 때까지 ROS 응답 executor를 살려 둔다.
        if session.thread is not None:
            while session.thread.is_alive():session.thread.join(.1)
    finally:
        executor.shutdown();spin_thread.join(2);node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        trace_file.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
