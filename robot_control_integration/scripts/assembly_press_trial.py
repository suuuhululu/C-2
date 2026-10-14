"""정렬 확인 후 수직 누름: raw 합력 임계값 STOP, Z는 이동 한도에만 사용."""
import argparse
from copy import deepcopy
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

from scripts.assembly_contact_trial import TEMPLATE, save
from scripts.assembly_position_trial import run, guard, trial_motion_still
from app.assembly_motion import motion_still
from app.jsonl_log import JsonlLog


def press(driver, connection, record, *, max_travel_mm=5., force_stop_n=35.,
          velocity=2., acceleration=1., required_gripper_status=2,
          angular_velocity=None, angular_acceleration=None,
          ik_fk_position_tolerance_mm=.05, ik_fk_orientation_tolerance_deg=.05,
          target_only_motion=False, clock=time.monotonic, sleep=time.sleep):
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
           for v in (max_travel_mm, force_stop_n, velocity, acceleration)):
        raise ValueError('POSITIVE_FINITE_PRESS_PARAMETERS_REQUIRED')
    stopped=trial_motion_still if target_only_motion else motion_still
    latest = {}
    stillness_policy=getattr(getattr(driver,'session',None),'value',{}).get('stillness',{})
    def capture(event, payload):
        latest[event] = deepcopy(payload)
        if event in ('INITIAL_SAMPLE', 'INITIAL_STILL_WAIT_SAMPLE'):
            latest['guard_sample'] = deepcopy(payload)
        elif event in ('PRE_MOVE_SAMPLE', 'PRE_MOVE_STILL_WAIT_SAMPLE', 'MOTION_SAMPLE'):
            latest['guard_sample'] = deepcopy(payload['sample'])
        record(event, payload)
    first = driver.sample()
    endpoint = first['posx'].copy()
    endpoint[2] -= max_travel_mm
    capture('PRESS_SESSION', dict(initial_sample=first, travel_endpoint_posx=endpoint,
                                 max_travel_mm=max_travel_mm, force_stop_n=force_stop_n,
                                 endpoint_is_seating_target=False))
    try:
        result = run(driver, connection, endpoint, force_stop_n, capture,
                     transfer_rate=velocity, descent_rate=velocity,
                     transfer_acceleration=acceleration, descent_acceleration=acceleration,
                     angular_velocity=angular_velocity,angular_acceleration=angular_acceleration,
                     set_automatic_mode=False, force_norm_stop_n=force_stop_n,
                     required_gripper_status=required_gripper_status,
                     ik_fk_position_tolerance_mm=ik_fk_position_tolerance_mm,
                     ik_fk_orientation_tolerance_deg=ik_fk_orientation_tolerance_deg,
                     target_only_motion=target_only_motion, clock=clock, sleep=sleep)
        result['status'] = 'MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD'
    except RuntimeError as error:
        if str(error) not in ('FORCE_NORM_STOP_LIMIT_REACHED', 'FZ_STOP_LIMIT_REACHED'):
            raise
        stop = latest['ABORT']['stop']
        if not stop['requested']:
            driver.stop()
            stop = dict(requested=True, acknowledged=True, stillness_verified=False)
        if not stop['acknowledged']:
            raise RuntimeError('FORCE_STOP_NOT_ACKNOWLEDGED')
        deadline = clock()+5.
        while not stop['stillness_verified']:
            feedback = driver.motion_feedback()
            capture('STOP_SETTLING_FEEDBACK', feedback)
            stop.update(feedback=feedback, stillness_verified=stopped(feedback,stillness_policy))
            if stop['stillness_verified']:
                break
            if clock() >= deadline:
                raise RuntimeError('FORCE_STOP_NOT_VERIFIED')
            sleep(.05)
        threshold = latest['guard_sample']
        final = driver.sample()
        # A force threshold must not hide grip loss, a wrong TCP or stale feedback.
        # Pressure is already stopped; check equipment without re-testing that same threshold.
        for sample in (threshold, final):
            guard(sample, connection, math.inf, automatic=True,
                  required_gripper_status=required_gripper_status)
        result = dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED', stop=stop,
                      threshold_sample=threshold,
                      threshold_force_norm_n=math.dist(threshold['wrench'][:3], [0., 0., 0.]),
                      final_sample=final)
    result.update(assembly_completion=False, calibration_adopted=False,
                  gripper_commands=0, native_force_commands=0,
                  max_travel_mm=max_travel_mm, force_stop_n=force_stop_n)
    capture('PRESS_RESULT', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-travel-mm', type=float, default=5.)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not math.isfinite(args.max_travel_mm) or args.max_travel_mm <= 0:
        parser.error('max-travel-mm must be positive finite')
    policy = dict(force_stop_n=35., max_travel_mm=args.max_travel_mm,
                  velocity_mm_s=2., acceleration_mm_s2=1., execute=args.execute,
                  endpoint_is_seating_target=False, operator_alignment_required=True)
    print(json.dumps(policy, ensure_ascii=False), flush=True)
    if not args.execute:
        return 0
    from app.assembly_motion_ros import AssemblyMotionRos
    config = json.loads(TEMPLATE.read_text())
    if config['mode'] != 'REAL' or os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_REAL_DOMAIN_REQUIRED')
    config['timing']['service_timeout_s'] = .5
    identity = str(uuid4())
    logger = JsonlLog('logs/assembly_layer_trials')
    def record(event, payload):
        logger(dict(job_id=identity, event=event, payload=payload))
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f'SIGNAL_{signum}')
    previous = signal.signal(signal.SIGTERM, interrupt)
    driver = None
    try:
        with Path('/tmp/c2-assembly-dsr01.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            driver = AssemblyMotionRos(config)
            if driver.robot_system() != 0:
                raise ValueError('PHYSICAL_ROBOT_REQUIRED')
            result = press(driver, config['connection'], record, max_travel_mm=args.max_travel_mm)
            save(logger.directory / (identity+'.summary.json'), result)
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result['status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED' else 2
    finally:
        if driver is not None:
            driver.close()
        signal.signal(signal.SIGTERM, previous)
        print(f'LOG_ID={identity}', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
