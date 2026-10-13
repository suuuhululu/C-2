"""(2,2) first-layer local trial: unload, capture, native force probes, hold."""
from copy import deepcopy
from contextlib import nullcontext
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

from app.assembly_contact_alignment import prepare_contact, run_contact, still, validate_sample, validate_pressure_stages
from app.assembly_motion import pose_error
from app.jsonl_log import JsonlLog
from scripts.assembly_contact_trial import real_driver, save
from scripts.assembly_position_trial import run as move_position

ROOT = Path(__file__).resolve().parents[1]
PREPARATION = ROOT/'settings/onsite_ack_continue_blue_slot2_2_2_l1_20261011/native-force-readonly.json'


def require_drcf2_runtime(proc=Path('/proc')):
    expected = Path(os.environ.get('C2_DRIVER_ROOT', ROOT/'runtime/drcf2')).resolve()/'install'
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process/'cmdline').read_bytes().split(b'\0')
            if not args or not args[0].endswith(b'/ros2_control_node') or b'__ns:=/dsr01' not in args:
                continue
            maps = (process/'maps').read_text()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        libraries = [str(expected/package/'lib'/f'lib{package}.so')
                     for package in ('dsr_controller2', 'dsr_hardware2')]
        if not all(path in maps for path in libraries):
            raise RuntimeError('DRCF2_DRIVER_RESTART_REQUIRED: restart bringup with selected DRCF2 overlay: '+str(expected))
        return int(process.name)
    raise RuntimeError('LOCAL_DSR01_DRIVER_NOT_RUNNING')


def trial_config(preparation):
    c = json.loads((ROOT/'interfaces/assembly_contact_trial.json').read_text())
    c.update(reviewed=True, floor_z_mm=preparation['floor_z_mm'],
             force_window_mm=preparation['seek_z_mm']-preparation['floor_z_mm'],
             xy_limit_mm=.25, rotation_limit_deg=.2)
    prepare_contact(c)  # Validate parameters before any movement; reference comes after unloading.
    return c


def run_trial(driver, config, start, record, *, pressure_stages=None, now=time.monotonic, sleep=time.sleep, utc=time.time):
    c = deepcopy(config)
    validate_pressure_stages(pressure_stages,c)
    s = driver.sample()
    validate_sample(s, c)
    mm, deg = pose_error(s['posx'], start)
    if not still(s) or mm > 1. or deg > 1.:
        raise RuntimeError('FORCE_TRIAL_START_CHANGED')
    if driver.mode != c['mode']:
        raise RuntimeError('DRIVER_MODE_MISMATCH')
    if driver.mode == 'REAL' and driver.robot_system() != 0:
        raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
    driver.check_contact_services(native_force=True)
    target = s['posx'].copy()
    target[2]=max(target[2]+4.,c['floor_z_mm']+c['force_window_mm']+.5)
    print(f"현재 자리에서 {target[2]-s['posx'][2]:.2f}mm 상승해 하중을 풀고 기준 힘을 측정합니다.", flush=True)
    move_position(driver, c['connection'], target, 35., record, clearance_z=target[2],
                  lift_only=True, set_automatic_mode=False, transfer_rate=2., descent_rate=2.,
                  transfer_acceleration=1., descent_acceleration=1., force_norm_stop_n=35.,
                  clock=now, sleep=sleep)
    try:
        free = [driver.sample() for _ in range(3)]
        for sample in free:
            record('UNLOADED_REFERENCE_SAMPLE', sample)
            validate_sample(sample, c)
            mm, deg = pose_error(sample['posx'], target)
            if (not still(sample) or mm > .05 or deg > .05 or
                    math.hypot(*sample['wrench'][:3]) >= c['free_force_max_n'] or
                    abs(sample['gripper_width_mm']-s['gripper_width_mm']) > c['width_drift_mm']):
                raise RuntimeError('UNLOADED_REFERENCE_NOT_CONFIRMED')
        last = free[-1]
        c['reference'] = dict(posx=last['posx'], width_mm=last['gripper_width_mm'],
                              captured_at_unix_s=utc(), source='LOCAL_UNLOAD_MEASURED_REFERENCE',
                              noncontact_verified=True)
        plan = prepare_contact(c, utc=utc)
        if plan['status'] != 'CONTACT_PLAN_READY':
            raise RuntimeError('FRESH_FORCE_PLAN_NOT_READY')
        record('FRESH_FORCE_PLAN', plan)
        print('XY·자세 보정 없이 '+ ' → '.join(f'{v:g}N' for v in pressure_stages)+
              '으로 각 최대 3초 누릅니다. 합력 35N 도달 시 정지합니다. 그리퍼는 계속 잡습니다.' if pressure_stages
              else '20N 힘 제어로 XY ±0.25mm·자세 ±0.2° 후보를 비교합니다. 그리퍼는 계속 잡습니다.', flush=True)
        result = run_contact(driver, plan, record, finish_contact=True, pressure_stages=pressure_stages,
                             now=now, sleep=sleep, utc=utc)
        return dict(result, assembly_completion=False, current_update=False,
                    physical_verified=False, backend_current_committed=False,
                    integration_scope='LOCAL_TRIAL_NOT_LIVE_A_B_D_CONTRACT')
    except BaseException:
        # Native runner owns its force cleanup. This path covers capture failures after the lift.
        driver.stop()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--press-only', action='store_true')
    args = parser.parse_args(argv)
    if args.execute and args.replay:
        parser.error('execute and replay are mutually exclusive')
    p = json.loads(PREPARATION.read_text()); c = trial_config(p)
    stages=(35.,) if args.press_only else None
    if stages:c['probe_force_n']=30.
    start = p['samples'][-1]['posx']
    if not args.execute and not args.replay:
        unload_mm=max(4.,p['seek_z_mm']+.5-start[2])
        print(json.dumps(dict(status='LOCAL_FORCE_TRIAL_PREVIEW', start=start, unload_mm=unload_mm,
                              seek_z_mm=p['seek_z_mm'], floor_z_mm=c['floor_z_mm'],
                              probe_force_n=c['probe_force_n'], pressure_stages_n=stages,
                              raw_force_stop_n=35., gripper_commands=0)))
        return 0
    identity = str(uuid4()); directory = ROOT/'logs/onsite_slot2_native_force'/identity
    logger = JsonlLog(directory); driver = None; previous = {}
    def record(event, payload):
        logger(dict(job_id=identity, event=event, payload=payload))
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f'SIGNAL_{signum}')
    try:
        if args.execute and os.environ.get('ROS_DOMAIN_ID') != str(c['connection']['ros_domain_id']):
            raise RuntimeError('MATCHING_ROS_DOMAIN_REQUIRED')
        if args.execute:
            require_drcf2_runtime()
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, interrupt)
        with (open('/tmp/c2-assembly-dsr01.lock', 'a') if args.execute else nullcontext()) as lock:
            if args.execute:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record('SESSION', dict(execution_id=identity, config=c, start=start, replay=args.replay,pressure_stages_n=stages))
            if args.replay:
                from app.assembly_contact_fake import ContactFake
                c['mode'] = 'FAKE'
                c['reference'] = dict(posx=p['unload_pose'], width_mm=40.6,
                                      captured_at_unix_s=time.time(), source='SYNTHETIC_REPLAY', noncontact_verified=True)
                driver = ContactFake(c); driver.pos = start.copy()
            else:
                claim = ROOT/'logs/executions'/f'{hashlib.sha256(identity.encode()).hexdigest()}.json'
                claim.parent.mkdir(parents=True, exist_ok=True)
                with claim.open('x') as stream:
                    json.dump(dict(execution_id=identity, phase='native-force-local'), stream)
                driver = real_driver(c)
            result = run_trial(driver, c, start, record, pressure_stages=stages)
        save(directory/'result.json', dict(result, execution_id=identity, backend=driver.mode))
        print(json.dumps(dict(status=result['status'], correction=result.get('correction'),
                              reason=result.get('reason'), stopped=result.get('stopped'), backend=driver.mode,
                              probe_count=result['probe_count'], assembly_completion=False,
                              gripper_commands=0, output=str(directory)), ensure_ascii=False), flush=True)
        return 1 if result['status'] == 'CONTACT_TRIAL_ABORTED' else 0
    except (Exception, KeyboardInterrupt) as error:
        result = dict(status='LOCAL_FORCE_TRIAL_FAILED', reason=str(error) or 'INTERRUPTED',
                      assembly_completion=False, output=str(directory))
        save(directory/'result.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 1
    finally:
        if driver is not None:
            driver.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
