"""직접 잡은 노랑 2×2의 (11,11)·3층·시계90° 국소 시험. 기본 동작은 장치 없는 준비."""
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import signal
from uuid import uuid4

from app.assembly_step_bridge import ROOT, build_plan, read, validate_physical
from app.assembly_step_runner import StepReplayDriver, run_step
from app.jsonl_log import JsonlLog
from scripts.assembly_contact_trial import TEMPLATE, real_driver, save

DEFAULT = ROOT / 'interfaces/assembly_held_11_11_l3_cw90.json'
LOCK = Path('/tmp/c2-assembly-dsr01.lock')


def main(argv=None, *, driver_factory=real_driver):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('plan', 'replay', 'probe', 'approach', 'contact', 'release'))
    parser.add_argument('--profile', type=Path, default=DEFAULT)
    parser.add_argument('--start-zone', choices=('supply', 'place', 'assembly'))
    parser.add_argument('--output', type=Path, default=ROOT / 'logs/assembly_held_trial_offline')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-envelope', action='store_true',
                        help='단독 사용·손 뗌·파지·TCP/tool·현재 시작 판/우회 경로·회전 여유·현 교시 기준의 국소 시험 사용 확인')
    args = parser.parse_args(argv)
    setup = read(args.profile)
    profile = setup['d_profile']
    plan = build_plan(setup['step'], profile)
    if args.phase == 'replay':
        driver = StepReplayDriver(plan['settings']['reference_pose'])
        driver.value.update(gripper_status=2, gripper_width_mm=40.)
        driver.value['posx'] = [-323., 58., 93.87, *plan['settings']['reference_pose'][3:]]
        trace = []
        result = run_step(driver, dict(tcp='GripperDA_v4',tool='ToolWeight0'), plan, profile,
                          lambda *args: True, lambda event,data: trace.append(dict(event=event,data=data)),
                          phase='approach', start_zone=args.start_zone or 'supply', sleep=lambda _: None)
        result.update(device_connections=0, robot_motion_commands=0, robot_gripper_commands=0,
                      physical_simulation=False, mock_motion_commands=len(driver.moves))
        save(args.output/'approach.trace.json', trace)
        save(args.output/'approach.result.json', result)
        print(json.dumps(dict(status=result['status'], desired_target=setup['desired_target'],
                              final_mock_tcp=driver.value['posx'], device_connections=0,
                              robot_motion_commands=0, robot_gripper_commands=0,
                              physical_simulation=False),ensure_ascii=False,indent=2))
        return 0
    if args.phase == 'plan' or not args.execute:
        print(json.dumps(dict(status='PREPARED_NO_DEVICE_CONNECTION', desired_target=setup['desired_target'],
                              approach_z_mm=setup['approach_z_mm'],
                              final_absolute_orientation=None, turn_reference='CURRENT_LIVE_GRASP',
                              physical_reference_reviewed=plan['settings']['physical_reference_reviewed'],
                              phase=args.phase, execution=False),ensure_ascii=False,indent=2))
        return 0
    if args.phase == 'approach' and args.start_zone is None:
        parser.error('real approach requires the actual --start-zone')
    if args.confirm_envelope and args.phase not in ('approach', 'contact'):
        parser.error('--confirm-envelope is only for the held approach/contact experiment')
    # Review is an operator assertion for this session, never an automatic physical validation.
    if args.confirm_envelope:
        profile = deepcopy(profile)
        profile['steps'][plan['key']]['physical_reference_reviewed'] = True
        if args.phase == 'approach':
            profile['physical_route_reviewed'] = True
        plan = build_plan(setup['step'], profile)
    if args.phase != 'probe':
        validate_physical(plan, profile, args.phase)
    config = read(TEMPLATE)
    if config['mode'] != 'REAL' or os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_REAL_DOMAIN_REQUIRED')
    config['timing']['service_timeout_s'] = .5
    identity = str(uuid4())
    logger = JsonlLog('logs/assembly_held_trials')
    def record(event, payload):
        logger(dict(job_id=identity,event=event,payload=payload))
    def confirm(kind, plan, sample):
        print(json.dumps(dict(wait=kind,tcp=sample['posx'],target=setup['desired_target']),ensure_ascii=False),flush=True)
        return input('이 단계 확인 yes / 보류 Enter: ').strip().lower() == 'yes'
    def interrupt(signum, frame):
        raise KeyboardInterrupt('SIGNAL_'+str(signum))
    driver = None
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        with LOCK.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            driver = driver_factory(config)
            if driver.robot_system() != 0:
                raise ValueError('PHYSICAL_ROBOT_REQUIRED')
            record('HELD_LOCAL_SESSION',dict(setup=setup,phase=args.phase,current_update=False))
            if args.phase == 'probe':
                sample = driver.sample()
                result = dict(status='HELD_READ_ONLY_PROBE_COMPLETE', sample=sample,
                              robot_motion_commands=0, robot_gripper_commands=0,
                              robot_mode_commands=0, assembly_completion=False, current_update=False)
                record('READ_ONLY_SAMPLE', result)
                save(logger.directory/(identity+'.summary.json'), result)
                print(json.dumps(result,ensure_ascii=False,indent=2))
                return 0
            record('OPERATOR_ENVELOPE_REVIEW',dict(command_line_confirmed=args.confirm_envelope,
                   physical_validation_performed=False,start_zone=args.start_zone,
                   reference_pose=plan['settings']['reference_pose']))
            result = run_step(driver, config['connection'],plan,profile,confirm,record,
                              phase=args.phase,start_zone=args.start_zone or 'assembly')
            save(logger.directory/(identity+'.summary.json'),result)
            print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    finally:
        if driver is not None:
            driver.close()
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
