"""명시된 목표의 위치 이동 시험. Fz 중단값은 작업자 지정이며 힘 제어가 아니다."""

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

from app.assembly_motion import motion_still, pose_error, vector
from app.assembly_motion_ros import AssemblyMotionRos
from app.jsonl_log import JsonlLog


def guard(sample, connection, limit, *, automatic, force_norm_limit=None, required_gripper_status=2):
    vector(sample['wrench'], 6, 'wrench')
    if force_norm_limit is not None:
        if type(force_norm_limit) not in (int, float) or not math.isfinite(force_norm_limit) or force_norm_limit <= 0:
            raise ValueError('POSITIVE_FINITE_FORCE_NORM_LIMIT_REQUIRED')
        if math.dist(sample['wrench'][:3], [0., 0., 0.]) >= force_norm_limit:
            raise RuntimeError('FORCE_NORM_STOP_LIMIT_REACHED')
    if limit is not None and abs(sample['wrench'][2]) >= limit:
        raise RuntimeError('FZ_STOP_LIMIT_REACHED')
    if sample['query_duration_s'] > .5:
        raise RuntimeError('FEEDBACK_TOO_OLD')
    if sample['tcp'] != connection['tcp'] or sample['tool'] != connection['tool']:
        raise RuntimeError('TCP_TOOL_MISMATCH')
    if type(required_gripper_status) is not int or required_gripper_status not in (0, 2):
        raise ValueError('IDLE_RELEASED_OR_HELD_STATUS_REQUIRED')
    if sample['gripper_status'] != required_gripper_status or sample['robot_state'] not in (1, 2):
        raise RuntimeError('ROBOT_OR_GRIP_NOT_READY')
    if sample['drl_state'] != 3:
        raise RuntimeError('DRL_NOT_STOPPED')
    if automatic and sample['robot_mode'] != 1:
        raise RuntimeError('AUTOMATIC_MODE_REQUIRED')


def run(driver, connection, target, limit, record, *, clearance_z=None,
        transfer_rate=6., descent_rate=6., finish_lift=False,
        lift_only=False, transfer_only=False, set_automatic_mode=True, force_norm_stop_n=None,
        required_gripper_status=2,
        transfer_acceleration=None, descent_acceleration=None,
        ik_fk_position_tolerance_mm=.05, ik_fk_orientation_tolerance_deg=.05,
        position_tolerance_mm=.05, orientation_tolerance_deg=.05,
        clock=time.monotonic, sleep=time.sleep):
    attempted = False
    stillness_policy=getattr(getattr(driver,'session',None),'value',{}).get('stillness',{})
    try:
        if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=1 for v in (ik_fk_position_tolerance_mm,ik_fk_orientation_tolerance_deg)):
            raise ValueError('INVALID_IK_FK_TOLERANCES')
        if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=1
               for v in (position_tolerance_mm,orientation_tolerance_deg)):
            raise ValueError('INVALID_MOTION_ARRIVAL_TOLERANCES')
        if transfer_only and (lift_only or finish_lift):
            raise ValueError('INVALID_TRANSFER_ONLY_REQUEST')
        if any(not math.isfinite(v) or v <= 0 for v in (transfer_rate, descent_rate)):
            raise ValueError('POSITIVE_FINITE_MOTION_RATES_REQUIRED')
        accelerations = (transfer_rate if transfer_acceleration is None else transfer_acceleration,
                         descent_rate if descent_acceleration is None else descent_acceleration)
        if any(not math.isfinite(v) or v <= 0 for v in accelerations):
            raise ValueError('POSITIVE_FINITE_ACCELERATIONS_REQUIRED')
        if finish_lift and clearance_z is None:
            raise ValueError('FINISH_LIFT_REQUIRES_CLEARANCE_HEIGHT')
        first = driver.sample()
        record('INITIAL_SAMPLE', first)
        guard(first, connection, limit, automatic=not set_automatic_mode, force_norm_limit=force_norm_stop_n,
              required_gripper_status=required_gripper_status)
        still_deadline = clock()+5.
        while not motion_still(first,stillness_policy):
            if clock() >= still_deadline:
                raise RuntimeError('START_NOT_STILL')
            sleep(.05)
            first = driver.sample()
            record('INITIAL_STILL_WAIT_SAMPLE', first)
            guard(first, connection, limit, automatic=not set_automatic_mode,
                  force_norm_limit=force_norm_stop_n, required_gripper_status=required_gripper_status)
        if not lift_only and not transfer_only and clearance_z is None and first['posx'][2] <= target[2]:
            raise RuntimeError('START_NOT_ABOVE_TARGET')
        height = first['posx'][2] if clearance_z is None else clearance_z
        if not math.isfinite(height) or height < first['posx'][2]-.05 or (not lift_only and not transfer_only and height <= target[2]):
            raise RuntimeError('INVALID_TRANSFER_HEIGHT')
        above = [*target[:2], height, *target[3:]]
        route = [('DESCENT', target)]
        above_distance, above_angle = pose_error(first['posx'], above)
        if above_distance > .05 or above_angle > .05:
            route.insert(0, ('ABOVE_TARGET', above))
        if clearance_z is not None and height-first['posx'][2] > .05:
            lifted = [*first['posx'][:2], height, *first['posx'][3:]]
            # A pure vertical lift already reaches ABOVE_TARGET. Do not send
            # a destination already within arrival tolerance and repeat its stop checks.
            if route[0][0] == 'ABOVE_TARGET' and max(pose_error(lifted,above)) <= .05:
                route.pop(0)
            route.insert(0, ('LIFT', lifted))
        if finish_lift:
            route.append(('LIFT_OUT', above))
        if lift_only:
            if clearance_z is None or height <= first['posx'][2] or finish_lift:
                raise ValueError('INVALID_LIFT_ONLY_REQUEST')
            route = [('LIFT', [*first['posx'][:2], height, *first['posx'][3:]])]
        if transfer_only:
            route = [(label, pose) for label, pose in route if label != 'DESCENT']
        for _, pose in route:
            fk = driver.check_pose(pose)
            mm, deg = pose_error(fk, pose)
            record('IK_FK_CHECK', dict(target=pose, fk=fk, position_error_mm=mm, orientation_error_deg=deg))
            if mm > ik_fk_position_tolerance_mm or deg > ik_fk_orientation_tolerance_deg:
                raise RuntimeError('IK_FK_ROUNDTRIP_MISMATCH')
            if mm > .05 or deg > .05:
                record('IK_FK_NUMERICAL_WARNING', dict(target=pose, fk=fk, position_error_mm=mm, orientation_error_deg=deg))
        if set_automatic_mode:
            driver.call('system/set_robot_mode', 'SetRobotMode', robot_mode=1)
        contact_sample = None
        sample = first
        for label, pose in route:
            sample = driver.sample()
            record('PRE_MOVE_SAMPLE', dict(segment=label, sample=sample))
            guard(sample, connection, limit, automatic=True, force_norm_limit=force_norm_stop_n,
                  required_gripper_status=required_gripper_status)
            still_deadline = clock()+5.
            while not motion_still(sample,stillness_policy):
                if clock() >= still_deadline:
                    raise RuntimeError('PRE_MOVE_NOT_STILL')
                sleep(.05)
                sample = driver.sample()
                record('PRE_MOVE_STILL_WAIT_SAMPLE', dict(segment=label, sample=sample))
                guard(sample, connection, limit, automatic=True, force_norm_limit=force_norm_stop_n,
                      required_gripper_status=required_gripper_status)
            rate = descent_rate if label == 'DESCENT' else transfer_rate
            acceleration = accelerations[1 if label == 'DESCENT' else 0]
            deadline = clock() + math.dist(sample['posx'][:3], pose[:3])/rate*3 + 10
            record('MOVE_REQUEST', dict(segment=label, target=pose, velocity=[rate, rate], acceleration=[acceleration, acceleration]))
            attempted = True  # ACK 실패도 명령 전달 가능성이 있어 STOP을 요청한다.
            driver.move_line_async(pose, [rate, rate], [acceleration, acceleration])
            while True:
                sample = driver.sample()
                record('MOTION_SAMPLE', dict(segment=label, sample=sample))
                guard(sample, connection, limit, automatic=True, force_norm_limit=force_norm_stop_n,
                      required_gripper_status=required_gripper_status)
                distance, angle = pose_error(sample['posx'], pose)
                if motion_still(sample,stillness_policy) and distance <= position_tolerance_mm and angle <= orientation_tolerance_deg:
                    break
                if clock() >= deadline:
                    raise TimeoutError('MOTION_TIMEOUT')
                sleep(.05)
            if label == 'DESCENT':
                contact_sample = sample
        result = dict(status=('ABOVE_TARGET_REACHED_NO_DESCENT' if transfer_only else
                              'CLEARANCE_REACHED_NO_DESCENT' if lift_only else 'POSITION_TARGET_REACHED_SEATING_NOT_VERIFIED'), final_sample=sample,
                      contact_sample=contact_sample, returned_to_clearance=finish_lift,
                      gripper_commands=0, target_posx=target)
        record('RESULT', result)
        return result
    except BaseException as error:
        stop = dict(requested=attempted, acknowledged=False, stillness_verified=False)
        if attempted:
            try:
                driver.stop()
                stop['acknowledged'] = True
                feedback = driver.motion_feedback()
                stop['feedback'] = feedback
                stop['stillness_verified'] = motion_still(feedback,stillness_policy)
            except Exception as stop_error:
                stop['error'] = str(stop_error)
        record('ABORT', dict(reason=str(error) or type(error).__name__, stop=stop))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, help='reachability JSON with target_posx')
    parser.add_argument('--fz-stop-n', required=True, type=float)
    parser.add_argument('--clearance-z-mm', type=float, help='사전에 사용한 실측 전이 높이; 먼저 수직 상승')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    target = vector(json.loads(Path(args.target).read_text())['target_posx'], 6, 'target')
    if not math.isfinite(args.fz_stop_n) or args.fz_stop_n <= 0:
        parser.error('fz-stop-n must be positive finite')
    print(json.dumps(dict(target_posx=target, velocity=[6, 6], acceleration=[6, 6],
                         fz_stop_n=args.fz_stop_n, clearance_z_mm=args.clearance_z_mm,
                         execute=args.execute), ensure_ascii=False), flush=True)
    if not args.execute:
        return 0
    config = json.loads(Path('logs/assembly_noncontact_onsite/config.json').read_text())
    if config['mode'] != 'REAL' or os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_REAL_DOMAIN_REQUIRED')
    config['timing']['service_timeout_s'] = .5
    identity = str(uuid4())
    logger = JsonlLog('logs/assembly_position_trials')
    started = time.monotonic()
    def record(event, payload):
        logger(dict(job_id=identity, event=event, payload=payload, elapsed_s=time.monotonic()-started))
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f'SIGNAL_{signum}')
    previous = signal.signal(signal.SIGTERM, interrupt)
    driver = None
    try:
        with open('/tmp/c2-assembly-dsr01.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record('SESSION', dict(target=target, fz_stop_n=args.fz_stop_n,
                                  force_semantics='absolute raw BASE Fz; user selected double last centre Fz'))
            driver = AssemblyMotionRos(config)
            print(json.dumps(run(driver, config['connection'], target, args.fz_stop_n, record,
                                 clearance_z=args.clearance_z_mm), ensure_ascii=False), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f'시험 중단: {str(error) or type(error).__name__}', flush=True)
        return 1
    finally:
        if driver is not None:
            driver.close()
        signal.signal(signal.SIGTERM, previous)
        print(f'로그: {logger.directory.resolve()}/{identity}.jsonl', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
