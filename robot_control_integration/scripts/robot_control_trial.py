"""Integrated trial: safe offline default; REAL requires reviewed local session files."""
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import sys
import threading
import time
from uuid import uuid4

from app.assembly_step_bridge import ROOT, build_plan, candidate_profile, load_steps, read, validate_physical
from app.assembly_step_runner import StepReplayDriver, replay_profile
from app.control_driver import ControlledDriver, execute_step, validate_assembly_fallback
from app.control_session import ControlSession, validate_execution
from scripts.assembly_contact_trial import TEMPLATE, save


def test_session(plan):
    return dict(backend='TEST', provenance='SYNTHETIC', execution_id=str(uuid4()),
        source_epoch='TEST_LOCAL', frame_profile_id='SYNTHETIC_BASE',
        **{k:plan[k] for k in ('plan_id', 'step_id', 'current_revision')},
        expires_unix_s=time.time()+600, request_timeout_s=30, frame_max_age_s=.3,
        frame_max_gap_s=.3, inference_max_latency_s=.3,
        stillness=dict(window_s=.1, max_gap_s=.25, timeout_s=3, min_samples=3,
                       sample_max_duration_s=.5, position_mm=.05, orientation_deg=.05,
                       linear_mm_s=.01, angular_deg_s=.01))


def prepare(args):
    steps = load_steps()
    selected = [s for s in steps if s['case_id'].startswith(args.case+'_') or s['case_id'] == args.case]
    if args.held_profile:
        setup = read(args.held_profile)
        step, profile = setup['step'], setup['d_profile']
    else:
        step = next((s for s in selected if s['step_id'] == args.step), None)
        if step is None:
            raise ValueError('CASE_STEP_NOT_FOUND')
        profile = read(args.profile) if args.profile else candidate_profile(steps)
    if args.command == 'replay':
        profile = replay_profile(profile, [step])
    return build_plan(step, profile), profile


preflight = validate_execution


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('preview', 'replay', 'template', 'doctor', 'run'))
    p.add_argument('--case', default='02')
    p.add_argument('--step', default='S01')
    p.add_argument('--phase', choices=('full', 'pickup', 'approach', 'contact', 'release', 'retreat', 'handover', 'assemble-held', 'grasp-recovery', 'human-wait', 'human-ack'), default='contact')
    p.add_argument('--start-zone', choices=('assembly', 'place', 'supply'), default='assembly')
    p.add_argument('--profile', type=Path)
    p.add_argument('--held-profile', type=Path)
    p.add_argument('--session', type=Path)
    p.add_argument('--assembly-fallback-profile', type=Path)
    p.add_argument('--assembly-fallback-session', type=Path)
    p.add_argument('--next-pickup-profile', type=Path)
    p.add_argument('--next-pickup-session', type=Path)
    p.add_argument('--config', type=Path, default=TEMPLATE)
    p.add_argument('--output', type=Path, default=ROOT/'logs/integration')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--camera', action='store_true')
    p.add_argument('--rgb-topic', default='/camera/color/image_raw')
    p.add_argument('--rgb-transport', choices=('raw', 'theora'), default='theora')
    p.add_argument('--model', type=Path, default=ROOT/'logs/handover/stage02/hand_landmarker.task')
    local_deps=ROOT/'logs/handover/model-deps'
    p.add_argument('--model-deps', type=Path, default=local_deps if local_deps.is_dir()
                   else ROOT.parent/'robot_gesture_dev_20261008/logs/handover/model-deps')
    args = p.parse_args(argv)
    if bool(args.assembly_fallback_profile) != bool(args.assembly_fallback_session):
        p.error('assembly fallback requires both profile and session')
    if args.assembly_fallback_profile and args.phase != 'handover':
        p.error('assembly fallback is only valid with handover')
    if bool(args.next_pickup_profile) != bool(args.next_pickup_session):
        p.error('next pickup requires both profile and session')
    if args.next_pickup_profile and (args.phase not in ('full','human-wait','human-ack') or
                                    args.command != 'run'):
        p.error('next pickup requires a human assembly run phase')
    if args.execute and args.command != 'run':
        p.error('--execute is only valid with run')
    if args.phase == 'handover' and args.command != 'preview' and (not args.camera or args.start_zone not in ('supply', 'place')):
        p.error('handover requires --camera and reviewed supply/place start zone; use unit fixtures for offline replay')
    plan, profile = prepare(args)
    if args.command == 'template':
        save(args.output/'d-profile.json', profile)
        s = test_session(plan)
        s.update(backend='REAL', provenance='LOCAL_OPERATOR_TRIAL', source_epoch='',
                 execution_id='', frame_profile_id='', expires_unix_s=0,
                 profile_id=profile['profile_id'],
                 exclusive_control_reviewed=False, device_feedback_reviewed=False,
                 stillness_parameters_reviewed=False, hand_clear_reviewed=False,
                 seating_evidence_ref=None, alignment_evidence_ref=None)
        s['stillness'] = {k:None for k in s['stillness']}
        save(args.output/'session.example.json', s)
        print('Unarmed profile/session templates:', args.output.resolve())
        return 0
    if args.command == 'preview' or (args.command == 'run' and not args.execute):
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION', plan=plan,
                              physical_ready=False), ensure_ascii=False, indent=2))
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    journal = (args.output/('trial-'+uuid4().hex+'.jsonl')).open('x')
    execution_ref = [None]
    def record(event, data):
        journal.write(json.dumps(dict(event=event, data=data, monotonic_s=time.monotonic(),
            execution_id=execution_ref[0], plan_id=plan['plan_id'], step_id=plan['step_id']),
                                 ensure_ascii=False, allow_nan=False)+'\n')
        journal.flush()
        if plan['settings'].get('human_step_gestures'):
            if event=='HUMAN_REQUEST_OPENED':
                if data['kind']=='RECEIVE':print('인계 대기: 받을 준비가 되면 편 손을 0.4초 유지하세요.',flush=True)
                elif data['kind']=='HUMAN_ASSEMBLY_ACK':print('결착 완료 대기: 직접 결착한 뒤 엄지척을 0.8초 유지하세요.',flush=True)
            elif event=='HUMAN_RECEIVING_CUE_REACQUIRE_WAIT':print('편 손 인식을 다시 확인하고 있습니다.',flush=True)
            elif event=='HUMAN_RECEIVING_CUE_REACQUIRED':print('편 손 확인됨. 인계를 계속합니다.',flush=True)
    if args.command == 'replay':
        raw = StepReplayDriver(plan['settings']['reference_pose'])
        if args.phase not in ('full', 'pickup'):
            if args.phase == 'retreat':
                raw.value.update(gripper_status=0, gripper_width_mm=plan['settings']['release_width_mm'],
                                 posx=plan['settings']['recovery_start_pose'].copy())
            else:
                raw.value.update(gripper_status=2, gripper_width_mm=40.)
                raw.value['posx'] = plan['settings']['reference_pose'].copy()
                raw.value['posx'][2] += profile['approach_offset_mm']
        session = ControlSession(test_session(plan), plan, record)
        execution_ref[0] = session.value['execution_id']
        try:
            result = execute_step(raw, session, dict(tcp='GripperDA_v4', tool='ToolWeight0'),
                                  plan, profile, lambda *a: True, record, phase=args.phase,
                                  start_zone=args.start_zone)
            result.update(device_connections=0, robot_motion_commands=0, robot_gripper_commands=0,
                          physical_simulation=False, mock_moves=len(raw.moves), mock_grips=len(raw.grips))
            save(args.output/'result.json', result)
            print(json.dumps({k:v for k,v in result.items() if k not in ('events','contact_evidence')}, ensure_ascii=False, indent=2))
            return 0
        finally:
            journal.close()
    raw = camera = node = executor = spin_thread = lock = None
    ros = None
    handlers = {}
    try:
        session = None
        next_plan = next_profile = next_value = None
        if args.command == 'run':
            if args.session is None:
                raise ValueError('EXPLICIT_SESSION_REQUIRED')
            initial_session = read(args.session)
            preflight(plan, profile, initial_session, args.phase)
            session = ControlSession(initial_session, plan, record)
            execution_ref[0] = session.value['execution_id']
            if args.next_pickup_profile:
                from app.human_step_continuation import validate_next_pickup
                setup = read(args.next_pickup_profile)
                next_profile = setup['d_profile']
                next_plan = build_plan(setup['step'], next_profile)
                next_value = read(args.next_pickup_session)
                validate_next_pickup(plan, initial_session, next_plan, next_value)
                preflight(next_plan, next_profile, next_value, 'pickup')
        config = read(args.config)
        if config['mode'] != 'REAL' or os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
            raise ValueError('EXPLICIT_REAL_DOMAIN_REQUIRED')
        # Claim once per execution before connection. A process restart cannot replay an old ID.
        if args.command == 'run':
            ledger = ROOT/'logs/executions'
            ledger.mkdir(parents=True, exist_ok=True)
            import hashlib
            identity = hashlib.sha256(session.value['execution_id'].encode()).hexdigest()
            try:
                with (ledger/(identity+'.json')).open('x') as f:
                    json.dump(dict(session=initial_session, status='CLAIMED_NO_AUTOMATIC_RETRY'), f)
            except FileExistsError as error:
                raise ValueError('EXECUTION_ALREADY_CLAIMED_NEW_SESSION_REQUIRED') from error
            if next_value is not None:
                identity = hashlib.sha256(next_value['execution_id'].encode()).hexdigest()
                try:
                    with (ledger/(identity+'.json')).open('x') as f:
                        json.dump(dict(session=next_value, status='CLAIMED_NO_AUTOMATIC_RETRY'), f)
                except FileExistsError as error:
                    raise ValueError('NEXT_EXECUTION_ALREADY_CLAIMED_NEW_SESSION_REQUIRED') from error
        lock = Path('/tmp/c2-assembly-'+config['connection']['robot_id']+'.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        import rclpy as ros
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.signals import SignalHandlerOptions
        from std_srvs.srv import Trigger
        from std_msgs.msg import String
        ros.init(args=[], signal_handler_options=SignalHandlerOptions.NO)
        node = ros.create_node('robot_control_integrated_trial')
        def stop_request(request, response):
            session.request_stop()
            response.success, response.message = True, 'STOP_REQUESTED_ACTUAL_STOP_PENDING'
            return response
        if session is not None:
            node.create_service(Trigger, '~/stop', stop_request)
        publisher = node.create_publisher(String, '~/state', 5)
        def publish_state():
            msg = String()
            if session is None:
                msg.data = json.dumps(dict(status='READ_ONLY_DOCTOR', assembly_completion=False))
                publisher.publish(msg)
                return
            msg.data = json.dumps(dict(execution_id=session.value['execution_id'], owner=session.owner,
                lease=session.lease, cancelled=session.cancelled, state_sequence=session.state_sequence,
                request=session.request, assembly_completion=False))
            publisher.publish(msg)
        node.create_timer(.2, publish_state)
        executor = MultiThreadedExecutor(num_threads=2)
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()
        from app.assembly_motion_ros import AssemblyMotionRos
        raw = AssemblyMotionRos(config, node=node)
        if raw.robot_system() != 0:
            raise ValueError('PHYSICAL_ROBOT_REQUIRED')
        if args.command == 'doctor':
            sample = raw.sample()
            record('READ_ONLY_DOCTOR', sample)
            print(json.dumps(dict(status='READ_ONLY_DOCTOR_COMPLETE', sample=sample,
                                  robot_motion_commands=0, robot_gripper_commands=0), ensure_ascii=False, indent=2))
            return 0
        if args.camera:
            from app.control_camera import RequestCamera
            camera = RequestCamera(node, session, model=args.model, model_deps=args.model_deps,
                topic=args.rgb_topic, transport=args.rgb_transport, record=record, output=args.output,
                open_hold_seconds=(.4 if plan['settings'].get('human_step_gestures') else
                    plan['settings'].get('handover_trial', {}).get('open_hold_seconds', 1.)),
                question_hold_seconds=(plan['settings'].get('human_step_gestures',{}).get('thumb_hold_seconds',.8)
                    if plan['settings'].get('human_step_gestures') else 2.))
        def confirm(req, plan, sample, active):
            print(json.dumps(dict(wait=req, tcp=sample['posx']), ensure_ascii=False), flush=True)
            auto_start = (req['kind'] == 'START_HANDOVER' and
                plan['settings'].get('handover_trial', {}).get('release_policy') == 'AUTO_AFTER_STOP')
            print('자동 인계 시작 확인 yes / 보류 Enter' if auto_start else
                  '현장 확인 yes / 보류 Enter; 영상 후보는 자동 승인하지 않습니다.', flush=True)
            if req['kind'] == 'HANDOVER_RELEASE':
                print('로봇 정지 후 블록을 받을 준비·개방 간섭 없음 확인. 손을 그리퍼 사이에 넣지 마세요.', flush=True)
            if auto_start:
                print('자동 인계 시험: 이동 중 편 손 감지 → 정지 확인 → 편 손 유지 확인 → 자동 개방입니다. 블록을 받을 준비가 된 상태에서 편 손을 보여주세요.', flush=True)
            while time.monotonic() <= req['deadline_monotonic_s']:
                active.check()
                if camera:
                    row = camera.poll()
                    if row and row.get('candidate_event'):
                        print('미검증 후보:', row['candidate_event'], '현장 확인 후 yes', flush=True)
                ready, _, _ = select.select([sys.stdin], [], [], .05)
                if ready:
                    return sys.stdin.readline().strip().lower() == 'yes'
            raise TimeoutError('HUMAN_RESPONSE_TIMEOUT')
        def guarded_record(event, data):
            if event in ('SINGLE_WRITER_MOVE', 'SINGLE_WRITER_GRIPPER', 'SINGLE_WRITER_BLEND'):
                if read(args.session) != initial_session:
                    raise RuntimeError('SESSION_FILE_CHANGED_NEW_EXECUTION_REQUIRED')
                preflight(plan, profile, initial_session, args.phase)
            record(event, data)
        session.record = guarded_record
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, lambda *_: session.request_stop('OPERATOR_STOP'))
        result = execute_step(raw, session, config['connection'], plan, profile, confirm, record,
                              phase=args.phase, start_zone=args.start_zone,
                              camera_poll=camera.poll if camera is not None else None)
        if result['status'] == 'HUMAN_ACK_TIMEOUT_CONTINUE' and next_value is not None:
            from app.human_step_continuation import execute_next_pickup
            save(args.output/'previous-step-result.json', result)
            if camera:
                camera.close()
                camera = None
            if read(args.next_pickup_profile) != setup or read(args.next_pickup_session) != next_value:
                raise RuntimeError('NEXT_PICKUP_FILES_CHANGED_NEW_SESSION_REQUIRED')
            previous_session, previous_plan = session, plan
            plan, profile, initial_session = next_plan, next_profile, next_value
            args.session, args.phase = args.next_pickup_session, 'pickup'
            execution_ref[0] = next_value['execution_id']
            session = ControlSession(next_value, plan, guarded_record)
            print('엄지척 대기 시간 종료: 이전 결착은 미확인으로 남기고 다음 블록을 집습니다.', flush=True)
            result = execute_next_pickup(raw, previous_session, previous_plan, result, session,
                config['connection'], plan, profile, confirm, record)
        elif result['status'] == 'HUMAN_ACK_TIMEOUT_CONTINUE':
            print('다음 Step 집기 요청됨: 연결된 다음 Step 입력이 없어 결과만 저장합니다.', flush=True)
        if result['status'] == 'ASSEMBLY_REQUIRED' and args.assembly_fallback_profile:
            save(args.output/'handover-result.json', result)
            setup = read(args.assembly_fallback_profile)
            fallback_profile = setup['d_profile']
            fallback_plan = build_plan(setup['step'], fallback_profile)
            fallback_value = read(args.assembly_fallback_session)
            validate_assembly_fallback(result, plan, fallback_plan, fallback_value)
            preflight(fallback_plan, fallback_profile, fallback_value, 'assemble-held')
            identity = hashlib.sha256(fallback_value['execution_id'].encode()).hexdigest()
            with (ledger/(identity+'.json')).open('x') as f:
                json.dump(dict(session=fallback_value, status='CLAIMED_NO_AUTOMATIC_RETRY'), f)
            if camera:
                camera.close()
                camera = None
            plan, profile, initial_session = fallback_plan, fallback_profile, fallback_value
            args.session, args.phase = args.assembly_fallback_session, 'assemble-held'
            execution_ref[0] = fallback_value['execution_id']
            session = ControlSession(fallback_value, plan, guarded_record)
            record('ASSEMBLY_FALLBACK_STARTED', dict(parent_execution_id=result['execution_id'],
                    reason=result['assembly_reason'], target=plan['block']))
            print('인계 신호 없음: 현재 파지 블록으로 조립 흐름에 전환합니다.', flush=True)
            result = execute_step(raw, session, config['connection'], plan, profile, confirm, record,
                                  phase='assemble-held', start_zone=result['assembly_start_zone'])
        save(args.output/'result.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        result = dict(status='INTEGRATION_TRIAL_FAILED', reason=str(error), assembly_completion=False)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        save(args.output/'failure.json', result)
        save(args.output/'result.json', result)
        # Each journal is unique: a later failure must not erase the first cause.
        record('INTEGRATION_TRIAL_FAILURE', result)
        return 1
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if camera:
            camera.close()
        if raw:
            raw.close()
        if executor:
            executor.shutdown(timeout_sec=2)
        if spin_thread:
            spin_thread.join(timeout=2)
        if node:
            node.destroy_node()
        if ros and ros.ok():
            ros.shutdown()
        if lock:
            lock.close()
        journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
