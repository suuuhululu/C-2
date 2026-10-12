"""A 경우별 샘플 연결 시험. 기본 preview/replay는 장치에 연결하지 않는다."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

from app.assembly_step_bridge import (FIXTURES, ROOT, build_plan, candidate_profile,
                                      load_steps, read, validate_physical)
from app.assembly_step_runner import StepReplayDriver, replay_profile, run_step
from app.jsonl_log import JsonlLog
from scripts.assembly_contact_trial import TEMPLATE, save


def validate_runtime(plan, runtime, profile, now=None):
    """D runtime receipt: fresh reassessment/reservation must be supplied by the integration owner."""
    now = time.time() if now is None else now
    if runtime.get('sample_kind') != 'LIVE_D_RUNTIME' or 'MOCK' in runtime.get('source_epoch', '').upper():
        raise ValueError('LIVE_D_RUNTIME_REQUIRED')
    if not runtime.get('source_epoch') or runtime.get('valid_until_unix_s', 0) <= now:
        raise ValueError('LIVE_RUNTIME_EXPIRED_OR_SOURCE_MISSING')
    for field in ('plan_id', 'step_id', 'current_revision'):
        if runtime.get(field) != plan[field]:
            raise ValueError('LIVE_RUNTIME_BINDING_MISMATCH:'+field)
    if runtime.get('profile_id') != profile['profile_id'] or not runtime.get('execution_id'):
        raise ValueError('LIVE_PROFILE_AND_EXECUTION_ID_REQUIRED')
    if not runtime.get('reassessment_ref') or runtime.get('reassessed_block') != plan['block']:
        raise ValueError('LIVE_REASSESSMENT_REQUIRED')
    if runtime.get('reassessed_mode') != plan['mode'] or runtime.get('reassessed_assistance_kind') != plan['assistance_kind']:
        raise ValueError('LIVE_REASSESSMENT_MODE_MISMATCH')
    if (not runtime.get('current_ref') or not runtime.get('reservation_ref') or
            not runtime.get('start_pose_ref') or runtime.get('reservation_confirmed') is not True):
        raise ValueError('LIVE_CURRENT_RESERVATION_START_REFS_REQUIRED')
    slot = plan['reservation']
    if slot and runtime.get('slot_id') != slot['slot_id']:
        raise ValueError('LIVE_SLOT_BINDING_MISMATCH')
    if not slot and not runtime.get('slot_id'):
        raise ValueError('LIVE_RELEASE_PRESS_SLOT_REQUIRED')


def replay(steps, profile, output):
    mock_profile = replay_profile(profile, steps)
    results = []
    mock_currents = {}
    for step in steps:
        plan = build_plan(step, mock_profile)
        before = (step['request']['latest_current'] if step['request'] else
                  read(Path(step['source_directory']) / 'reassessment.input.json')['current'])
        if step['case_id'] in mock_currents and mock_currents[step['case_id']] != before:
            raise ValueError('MOCK_CURRENT_CHAIN_MISMATCH')
        driver = StepReplayDriver(plan['settings']['reference_pose'])
        trace = []
        result = run_step(driver, dict(tcp='GripperDA_v4', tool='ToolWeight0'), plan, mock_profile,
                          lambda *args: True, lambda event, data: trace.append(dict(event=event, data=data)),
                          sleep=lambda _: None)
        result.update(driver_mode='MOCK', physical_verified=False, mock_current_only=True,
                      move_commands=len(driver.moves), gripper_commands=len(driver.grips),
                      stop_commands=driver.stops)
        if result['status'] == 'AWAITING_BACKEND_OBSERVATION':
            after = dict(current_revision=before['current_revision']+1,
                         blocks=before['blocks']+[step['block']])
            expected_path = Path(step['source_directory']) / 'expected_mock_current_after.json'
            if expected_path.exists() and read(expected_path)['current'] != after:
                raise ValueError('MOCK_CURRENT_EXPECTATION_MISMATCH')
            mock_currents[step['case_id']] = after
            result['simulated_current_after'] = after
        save(output / (plan['key'].replace('/', '_')+'.trace.json'), trace)
        results.append(result)
    report = dict(status='OFFLINE_WORKFLOW_REPLAY_COMPLETE', steps=len(results), device_connections=0,
                  physical_simulation=False, robot_motion_commands=0, robot_gripper_commands=0,
                  cases=sorted({s['case_id'] for s in steps}), results=results)
    save(output / 'replay-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preview', 'replay', 'template', 'run'))
    parser.add_argument('--samples', type=Path, default=FIXTURES)
    parser.add_argument('--case', help='case folder name or numeric prefix, e.g. 02')
    parser.add_argument('--step', default='S01')
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--runtime', type=Path, help='live D receipt; a sample receipt never authorizes execution')
    parser.add_argument('--output', type=Path, default=ROOT / 'logs/assembly_step_offline')
    parser.add_argument('--phase', choices=('full', 'approach', 'contact', 'release'), default='contact')
    parser.add_argument('--start-zone', choices=('assembly', 'place', 'supply'), default='assembly')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    steps = load_steps(args.samples)
    profile = read(args.profile) if args.profile else candidate_profile(steps)
    if args.case:
        steps = [s for s in steps if s['case_id'] == args.case or s['case_id'].startswith(args.case+'_')]
    if not steps:
        parser.error('no matching case')
    if args.command == 'template':
        args.output.mkdir(parents=True, exist_ok=True)
        save(args.output / 'd-step-profile.json', profile)
        save(args.output / 'runtime.example.json', dict(
            sample_kind='EXAMPLE_NOT_LIVE', source_epoch='REPLACE_WITH_D_LIVE_EPOCH',
            execution_id=None, plan_id=None, step_id=None, current_revision=None,
            profile_id=profile['profile_id'], valid_until_unix_s=0,
            reassessment_ref=None, reassessed_block=None, reassessed_mode=None,
            reassessed_assistance_kind=None, current_ref=None, reservation_ref=None,
            start_pose_ref=None, reservation_confirmed=False, slot_id=None))
        print(str((args.output / 'd-step-profile.json').resolve()))
        return 0
    if args.command == 'replay':
        args.output.mkdir(parents=True, exist_ok=True)
        report = replay(steps, profile, args.output)
        print(json.dumps({k:v for k,v in report.items() if k != 'results'}, ensure_ascii=False, indent=2))
        return 0 if all(r['status'] == 'AWAITING_BACKEND_OBSERVATION' for r in report['results']) else 2
    plans = [build_plan(s, profile) for s in steps if args.command != 'run' or s['step_id'] == args.step]
    if args.command == 'preview' or not args.execute:
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION', plans=plans), ensure_ascii=False, indent=2))
        return 0
    if not args.case or len(plans) != 1 or args.profile is None or args.runtime is None:
        parser.error('real run requires one --case/--step and explicit --profile/--runtime')
    plan = plans[0]
    # Complete all offline checks before creating the ROS/Modbus driver.
    validate_physical(plan, profile, args.phase)
    runtime = read(args.runtime)
    validate_runtime(plan, runtime, profile)
    config = read(TEMPLATE)
    if config['mode'] != 'REAL' or os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_REAL_DOMAIN_REQUIRED')
    config['timing']['service_timeout_s'] = .5
    logger = JsonlLog('logs/assembly_step_trials')
    identity = str(uuid4())
    ledger = logger.directory / ('execution-'+str(runtime['execution_id']).replace('/', '_')+'.json')
    with ledger.open('x') as file:
        json.dump(dict(runtime=runtime, job_id=identity, status='ATTEMPT_STARTED_NO_AUTOMATIC_RETRY'), file)
    def record(event, data):
        if event in ('STEP_MOVE', 'GRIPPER_REQUEST', 'MOVE_REQUEST'):
            validate_runtime(plan, read(args.runtime), profile)
        logger(dict(job_id=identity, event=event, payload=data))
    def confirm(kind, plan, sample):
        print(json.dumps(dict(wait=kind, block=plan['block'], tcp=sample['posx'],
                              human_actions=plan['human_actions']), ensure_ascii=False), flush=True)
        return input('확인되면 yes, 보류하면 Enter: ').strip().lower() == 'yes'
    def interrupt(signum, frame):
        raise KeyboardInterrupt('SIGNAL_'+str(signum))
    driver = None
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        with Path('/tmp/c2-assembly-dsr01.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            from app.assembly_motion_ros import AssemblyMotionRos
            driver = AssemblyMotionRos(config)
            if driver.robot_system() != 0:
                raise ValueError('PHYSICAL_ROBOT_REQUIRED')
            record('STEP_SESSION', dict(plan=plan, runtime=runtime, phase=args.phase))
            result = run_step(driver, config['connection'], plan, profile, confirm, record,
                              phase=args.phase, start_zone=args.start_zone)
            save(logger.directory / (identity+'.summary.json'), result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        if driver:
            driver.close()
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
