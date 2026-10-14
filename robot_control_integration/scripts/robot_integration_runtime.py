"""한 줄 JSON 명령을 받는 Robot 실행 프로세스. 기본 MOCK; REAL은 명시적으로만 연결."""
import argparse
from contextlib import redirect_stdout
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from app.assembly_step_bridge import build_plan, step_from_messages
from app.assembly_step_runner import StepReplayDriver
from app.integration_runtime import StepRuntime
from app.assembly_strategy import has_source_release_press, validate_d_profile_motion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('MOCK', 'REAL'), default='MOCK')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--gestures', action='store_true')
    args = parser.parse_args()
    lock = threading.Lock()
    runtime, worker, resources = None, None, []
    camera = None
    fake_gestures = None
    round3_used_executions = set()
    def ensure_camera():
        nonlocal camera
        if args.gestures:
            if args.mode != 'REAL':raise ValueError('GESTURE_CAMERA_REQUIRES_REAL_MODE')
            if camera is None:
                from app.integration_gestures import IntegrationGestureCamera
                from app.assembly_step_bridge import ROOT
                output = ROOT/'logs/gesture-integration'/str(time.time_ns())
                output.mkdir(parents=True)
                camera = IntegrationGestureCamera(runtime.raw.node,runtime,emit,output)
                resources.append(camera)
            if camera.error:raise RuntimeError('GESTURE_CAMERA_FAILED:'+camera.error)
    output = sys.stdout
    def emit(event, data):
        with lock:
            output.write(json.dumps(dict(event=event, data=data), ensure_ascii=False, allow_nan=False)+'\n')
            output.flush()
    def stop(*_):
        emit('STOP_ACCEPTED', dict(actual_stop_verified=False))
        if runtime: runtime.stop()
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, stop)
    def execute():
        # ROS diagnostics cannot corrupt the local JSON channel.
        with redirect_stdout(sys.stderr):
            runtime.run()
    def connect_real():
        if resources:
            raise RuntimeError('DEVICE_INITIALIZATION_FAILED_RESTART_REQUIRED')
        if args.config is None: raise ValueError('REAL_CONFIG_REQUIRED')
        config = json.loads(args.config.read_text())
        if config.get('mode') != 'REAL' or os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
            raise ValueError('EXPLICIT_REAL_DOMAIN_REQUIRED')
        physical_lock = Path('/tmp/c2-assembly-'+config['connection']['robot_id']+'.lock')
        handle = physical_lock.open('a'); resources.append(handle)
        fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.signals import SignalHandlerOptions
        rclpy.init(args=[], signal_handler_options=SignalHandlerOptions.NO)
        node = rclpy.create_node('d_robot_integration')
        executor = MultiThreadedExecutor(num_threads=2); executor.add_node(node)
        thread = threading.Thread(target=executor.spin, daemon=True); thread.start()
        resources.append((executor, thread, node, rclpy))
        from app.assembly_motion_ros import AssemblyMotionRos
        with redirect_stdout(sys.stderr): raw = AssemblyMotionRos(config, node=node)
        resources.append(raw)
        if raw.robot_system() != 0: raise ValueError('PHYSICAL_ROBOT_REQUIRED')
        return raw, config['connection']
    try:
        emit('PROCESS_READY', dict(mode=args.mode, device_connections=0))
        for line in sys.stdin:
            message = None
            try:
                message = json.loads(line)
                command = message['command']
                if command == 'STOP':
                    stop()
                    if runtime is None or runtime.state not in ('RUNNING', 'STOPPED', 'RECOVERY_REQUIRED'):
                        emit('STOP_IDLE', dict(actual_stop_verified=False, physical_commands=0))
                    continue
                if command == 'STATE':
                    emit('STATE', dict(status=runtime.state if runtime else 'IDLE',
                                       request=runtime.request if runtime else None))
                    continue
                if command == 'CLOSE': break
                if command == 'READ_STATE':
                    if args.mode != 'REAL': raise ValueError('REAL_READ_STATE_REQUIRED')
                    if worker and worker.is_alive(): raise RuntimeError('EXECUTION_BUSY')
                    with redirect_stdout(sys.stderr):
                        if runtime is None:
                            raw, connection = connect_real()
                            runtime = StepRuntime(raw, connection, emit)
                        ensure_camera()
                        samples = []
                        for _ in range(3):
                            samples.append(runtime.raw.sample())
                            time.sleep(.05)
                    emit('STATE_SNAPSHOT',dict(samples=samples,captured_unix_s=time.time(),physical_commands=0,
                        last_step_gripper_context=deepcopy(getattr(runtime.raw,'last_step_gripper_context',None))))
                    continue
                if command in ('EXECUTE', 'RESUME'):
                    if worker and worker.is_alive(): raise RuntimeError('EXECUTION_BUSY')
                    document = message['document']
                    if 'round2_replay' in document and (args.mode != 'MOCK' or command != 'EXECUTE'):
                        raise ValueError('ROUND3_STEP_REPLAY_IS_MOCK_EXECUTE_ONLY')
                    step = (step_from_messages(document['assessment'], document['request'], document['motion'],
                                               case_id=document['case_id']) if 'assessment' in document else document['step'])
                    profile, session = document['d_profile'], document['session']
                    plan = build_plan(step, profile)
                    if 'assessment' in document:
                        if has_source_release_press(plan) and step.get('motion_source')=='D_PROFILE':
                            validate_d_profile_motion(document['motion'],document['request'],profile,plan['key'])
                        else:
                            from app.integration_motion_binding import verify_motion
                            verify_motion(document['motion']['motion_proposal'], plan, profile, document['request']['robot_state'])
                    elif session.get('no_vision_trial') is True:
                        from app.integration_motion_binding import verify_motion
                        verify_motion(document['motion']['motion_proposal'], plan, profile, document['robot_state'])
                    if 'round2_replay' in document:
                        from app.round3_step_replay import Round3StepReplay
                        if runtime is not None and not (isinstance(runtime, Round3StepReplay)
                                and runtime.state == 'AWAITING_INSPECTION'
                                and runtime.config.get('saved_observation_flow') is True
                                and document['round2_replay'].get('saved_observation_flow') is True):
                            raise RuntimeError('ROUND3_SINGLE_STEP_REPLAY_RESTART_REQUIRED')
                        if session['execution_id'] in round3_used_executions:
                            raise ValueError('ROUND3_EXECUTION_ALREADY_USED')
                        runtime = Round3StepReplay(document, emit)
                        round3_used_executions.add(session['execution_id'])
                        runtime.start()
                        worker = threading.Thread(target=execute, daemon=False); worker.start()
                        continue
                    if args.mode == 'MOCK' and session.get('backend') != 'TEST': raise ValueError('MOCK_REQUIRES_TEST_SESSION')
                    if args.mode == 'REAL':
                        from app.control_session import validate_execution
                        validate_execution(plan, profile, session, 'full')
                        if session.get('provenance') != 'LIVE_D_RUNTIME': raise ValueError('LIVE_D_RUNTIME_REQUIRED')
                    if runtime is None:
                        connection = dict(tcp='GripperDA_v4', tool='ToolWeight0')
                        if args.mode == 'MOCK':
                            raw = StepReplayDriver(plan['settings']['reference_pose'],reaction_force_n=profile['force_stop_n'])
                            if 'request' in document or session.get('no_vision_trial') is True:
                                from scipy.spatial.transform import Rotation
                                start=(document['request']['robot_state'] if 'request' in document
                                       else document['robot_state'])['tcp_pose']
                                # 명시적인 MOCK 시작 상태. REAL feedback은 이 값으로 덮어쓰지 않는다.
                                raw.value['posx']=[v*1000 for v in start['xyz_m']]+Rotation.from_quat(start['quaternion_xyzw']).as_euler('ZYZ',degrees=True).tolist()
                        else:
                            raw, connection = connect_real()
                        runtime = StepRuntime(raw, connection, emit)
                    elif args.mode == 'MOCK' and command != 'RESUME':
                        runtime.raw.reference = plan['settings']['reference_pose'].copy()
                        runtime.raw.reaction_force_n = profile['force_stop_n']
                    if args.mode == 'REAL':
                        from app.assembly_step_bridge import ROOT
                        import hashlib
                        ledger = ROOT/'logs/executions'; ledger.mkdir(parents=True, exist_ok=True)
                        identity = hashlib.sha256(session['execution_id'].encode()).hexdigest()
                        with (ledger/(identity+'.json')).open('x') as claim:
                            json.dump(dict(session=session,status='CLAIMED_NO_AUTOMATIC_RETRY'), claim)
                    with redirect_stdout(sys.stderr): ensure_camera()
                    runtime.start(step, profile, session, resume=command=='RESUME', start_zone=document.get('start_zone', 'assembly'))
                    worker = threading.Thread(target=execute, daemon=False); worker.start()
                elif command == 'GESTURE_SAMPLE':
                    if args.mode != 'MOCK': raise ValueError('SYNTHETIC_GESTURE_REQUIRES_MOCK')
                    if runtime is None: raise RuntimeError('NO_RUNTIME')
                    if fake_gestures is None:
                        from app.integration_gestures import OperatorGestureInput
                        fake_gestures = OperatorGestureInput(runtime, emit)
                    if message['sample'].get('provenance') != 'SYNTHETIC':
                        raise ValueError('SYNTHETIC_GESTURE_REQUIRED')
                    fake_gestures.gesture(message['sample'], time.monotonic_ns())
                elif command == 'SIGNAL':
                    if runtime is None: raise RuntimeError('NO_RUNTIME')
                    runtime.accept_signal(message['signal'])
                    emit('SIGNAL_ACCEPTED', dict(request_id=message['signal']['request_id']))
                elif command == 'OPERATOR_CONFIRM':
                    if runtime is None:raise RuntimeError('NO_RUNTIME')
                    if message.get('ready') is not True:raise ValueError('EXPLICIT_OPERATOR_CONFIRMATION_REQUIRED')
                    runtime.confirm_operator(message.get('request_id'))
                elif command == 'ALIGNMENT_CONFIRM':
                    if runtime is None or not getattr(runtime, 'no_vision_trial', False) or not runtime.request or runtime.request['kind'] != 'ALIGNMENT_READY':
                        raise RuntimeError('NO_OPERATOR_ALIGNMENT_PENDING')
                    if message.get('ready') is not True or message.get('request_id') != runtime.request['request_id']:
                        raise ValueError('INACTIVE_OPERATOR_ALIGNMENT_REQUEST')
                    # HMI 버튼을 누른 사람의 응답 수신 시각은 D 호스트에서 기록한다.
                    runtime.accept_signal(dict(runtime.request,sequence=runtime.signal_seq+1,
                        source='HMI',verified=True,ready=True,observed_monotonic_s=runtime.clock()))
                    emit('SIGNAL_ACCEPTED',dict(request_id=message['request_id']))
                elif command == 'INSPECTION':
                    runtime.inspection(message['result'], conditions_ready=message.get('conditions_ready') is True)
                elif command == 'REINSPECT': runtime.reinspect()
                else: raise ValueError('UNKNOWN_COMMAND')
            except Exception as error:
                emit('COMMAND_REJECTED', dict(reason=str(error), command=message.get('command') if isinstance(message,dict) else None, current_update=False))
    finally:
        if runtime and runtime.state == 'RUNNING': stop()
        if worker: worker.join(timeout=10)
        if worker and worker.is_alive():
            emit('PROCESS_EXIT_BLOCKED', dict(reason='STOP_NOT_FINISHED', actual_stop_verified=False))
            worker.join()
        if runtime and hasattr(runtime.raw, 'close') and runtime.raw not in resources: runtime.raw.close()
        for resource in reversed(resources):
            if isinstance(resource, tuple):
                executor, thread, node, ros = resource
                executor.shutdown(); thread.join(timeout=2); node.destroy_node(); ros.shutdown()
            else: resource.close()
    return 0


if __name__ == '__main__': raise SystemExit(main())
