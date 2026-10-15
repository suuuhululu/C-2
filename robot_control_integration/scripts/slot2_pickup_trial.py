"""Single taught yellow slot2 or red slot1 approach/close/hold. Preview is the default."""
import argparse
from copy import deepcopy
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import sys
import time

NATIVE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(NATIVE), str(NATIVE.parent/'perception')]
from scripts import supply_pick_release_trial as supply
from scripts.capture_supply_depth_reference import reference_config, bind_pickup_record, save
from scripts.assembly_position_trial import guard
from app.assembly_motion import motion_still, pose_error
from app.assembly_motion_ros import AssemblyMotionRos

SLOT_ID = 'yellow_2x2x1_02'
RED_SLOT_ID = 'red_1x2x1_01'


def prepare(path, slot_id=SLOT_ID):
    record = json.loads(path.read_text())
    if slot_id == RED_SLOT_ID:
        return prepare_red(path, record)
    if slot_id != SLOT_ID:
        raise ValueError('UNSUPPORTED_SINGLE_SLOT')
    if (record.get('slot_id') != SLOT_ID
            or record.get('operator_preclose_alignment_confirmed') is not True
            or record.get('physical_grasp_verified') is not True):
        raise ValueError('CONFIRMED_SLOT2_MANUAL_TEACHING_AND_LIFT_REQUIRED')
    base = reference_config('T1')
    keys = ('connection', 'observation_pose', 'pickup_clearance_z_mm', 'teaching_xy_bounds_mm',
            'startup_route', 'force_stop_n', 'open_mm', 'gripper_force_n', 'velocity',
            'acceleration', 'angular_velocity', 'angular_acceleration', 'rise_velocity',
            'transit_velocity', 'rise_acceleration', 'transit_acceleration')
    cfg = {k: deepcopy(base[k]) for k in keys}
    row = dict(color='yellow', brick_type='2x2x1', slot=2, span=2,
               close_mm=base['blocks'][0]['close_mm'], pose_source=str(path.resolve()))
    row['pickup_pose'] = bind_pickup_record(row, cfg['connection'], record)
    supply.validate_teaching_location(cfg, row['pickup_pose'])
    cfg.update(blocks=[row], vision={}, target_only_motion=False,
        scope='ONE_TAUGHT_SLOT2_APPROACH_CLOSE_HOLD_NO_LIFT_NO_ASSEMBLY',
        source_record_sha256=sha256(path.read_bytes()).hexdigest(),
        supply_rgbd_correction_enabled=False, assembly_xy_correction_enabled=False)
    supply.validate_rows(cfg, [row], require_ready=True)
    return cfg


def prepare_red(path, source):
    key = 'supply/red/1x2x1/1'
    base = reference_config('T1')
    manual = source.get('schema_version') == 'supply-preclose-teaching-record/1'
    if manual:
        row_identity = dict(color='red', brick_type='1x2x1', slot=1)
        pose = bind_pickup_record(row_identity, base['connection'], source)
        review = json.loads((path.parent/'manual-grasp-review.json').read_text())
        if (review.get('pickup_record_sha256') != sha256(path.read_bytes()).hexdigest()
                or review.get('operator_preclose_alignment_confirmed') is not True
                or review.get('operator_exact_grasp_confirmed') is not True
                or review.get('operator_manual_lift_confirmed') is not True
                or review.get('post_lift_holding_signal_verified') is not True
                or review.get('grasp_basis') != 'TWO_STUD_SIDE_AXIS'):
            raise ValueError('RED_SLOT1_MANUAL_GRASP_LIFT_REVIEW_REQUIRED')
        for evidence in review['evidence']:
            evidence_path = path.parent/evidence['file']
            if sha256(evidence_path.read_bytes()).hexdigest() != evidence['sha256']:
                raise ValueError('MANUAL_GRASP_EVIDENCE_CHANGED')
        if not review['evidence']:
            raise ValueError('MANUAL_GRASP_EVIDENCE_REQUIRED')
    else:
        row_source = source['records'][key]
        if (source.get('sample_kind') != 'OPERATOR_TAUGHT_READ_ONLY'
                or any(source.get(k) != base['connection'][k] for k in ('tcp', 'tool'))
                or tuple(row_source.get(k) for k in
                         ('case_id', 'section', 'color', 'brick_type', 'slot_index'))
                    != (key, 'supply', 'red', '1x2x1', 1)
                or row_source.get('source') != 'READ_ONLY_DEVICE_QUERY'
                or row_source.get('operator_confirmed') is not True
                or row_source['receipt']['physical_commands'] != 0):
            raise ValueError('EXACT_OPERATOR_TAUGHT_RED_SLOT1_REQUIRED')
        pose = deepcopy(row_source['tcp_pose_mm_zyz_deg'])
    # Use only the existing red closing width, never slot5's trial rotation/XY.
    settings = json.loads((NATIVE/'settings/supply_sequence_20261014/config.json').read_text())
    red = next(r for r in settings['blocks']
               if r['color'] == 'red' and r['brick_type'] == '1x2x1')
    keys = ('connection', 'observation_pose', 'pickup_clearance_z_mm', 'teaching_xy_bounds_mm',
            'startup_route', 'force_stop_n', 'open_mm', 'gripper_force_n', 'velocity',
            'acceleration', 'angular_velocity', 'angular_acceleration', 'rise_velocity',
            'transit_velocity', 'rise_acceleration', 'transit_acceleration')
    cfg = {k: deepcopy(base[k]) for k in keys}
    row = dict(color='red', brick_type='1x2x1', slot=1, span=1,
               close_mm=red['close_mm'], pose_source=str(path.resolve())+('' if manual else '#'+key),
               pickup_pose=pose)
    supply.validate_teaching_location(cfg, row['pickup_pose'])
    cfg.update(blocks=[row], vision={}, target_only_motion=False,
        scope='ONE_TAUGHT_RED_SLOT1_APPROACH_CLOSE_HOLD_NO_LIFT_NO_ASSEMBLY',
        source_record_sha256=sha256(path.read_bytes()).hexdigest(),
        source_grasp_review_sha256=(sha256((path.parent/'manual-grasp-review.json').read_bytes()).hexdigest()
                                    if manual else None),
        prior_physical_grasp_verified=manual,
        supply_rgbd_correction_enabled=False, assembly_xy_correction_enabled=False)
    supply.validate_rows(cfg, [row], require_ready=True)
    return cfg


def waypoints(cfg):
    view = cfg['observation_pose'].copy()
    low = view.copy(); low[2] = cfg['pickup_clearance_z_mm']
    pick = cfg['blocks'][0]['pickup_pose'].copy()
    high = pick.copy(); high[2] = low[2]
    slot = cfg['blocks'][0]['slot']
    return [('observation', view), ('observation_low', low),
            (f'slot{slot}_high', high), (f'slot{slot}_pickup', pick)]


def preflight(driver, cfg):
    if driver.robot_system() != 0:
        raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
    samples = [driver.sample() for _ in range(3)]
    for sample in samples:
        guard(sample, cfg['connection'], cfg['force_stop_n'], automatic=False,
              force_norm_limit=cfg['force_stop_n'], required_gripper_status=0)
        if (not motion_still(sample) or sample['gripper_width_mm'] < supply.MIN_START_OPEN_MM
                or any(v > .5 for v in pose_error(sample['posx'], cfg['observation_pose']))):
            raise RuntimeError('STOPPED_OBSERVATION_AND_EMPTY_OPEN_50MM_REQUIRED')
    checks = []
    for label, target in waypoints(cfg):
        fk = driver.check_pose(target)
        error = pose_error(fk, target)
        checks.append(dict(label=label, target=target, fk=fk, error_mm_deg=list(error)))
        if any(v > .05 for v in error):
            raise RuntimeError('ENDPOINT_IK_FK_MISMATCH:'+label)
    return dict(status='READ_ONLY_PREFLIGHT_READY', samples=samples, endpoints=checks,
                collision_clearance_verified=False, physical_commands=0)


def taught_observation(row):
    # This is an explicitly selected taught-coordinate mode, never a failure fallback.
    slot_id = f"{row['color']}_{row['brick_type']}_{row['slot']:02d}"
    return dict(slot_id=slot_id, vision_attempted=False, recognized=False,
                center_available=False, reason='EXPLICIT_TAUGHT_COORDINATES_RGBD_AND_XY_DISABLED')


def execute_one(driver, cfg, record):
    supply.execute(driver, cfg, record, taught_observation, trial_row=cfg['blocks'][0],
                   start_zone='supply', hold_at_pickup=True)


def interrupted(*_):
    raise KeyboardInterrupt('OPERATOR_STOP')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preview', 'check', 'run'), nargs='?', default='preview')
    parser.add_argument('--pickup-record', type=Path, required=True,
                        help='Pickup teaching record, or original operator_supply.json for red')
    parser.add_argument('--slot-id', choices=(SLOT_ID, RED_SLOT_ID), default=SLOT_ID)
    parser.add_argument('--confirm-red-slot1-ready', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-slot2-ready', action='store_true')
    parser.add_argument('--confirm-hand-clear', action='store_true')
    args = parser.parse_args(argv)
    cfg = prepare(args.pickup_record, args.slot_id)
    if args.command == 'preview' or (args.command == 'run' and not args.execute):
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION', config=cfg,
              waypoints=waypoints(cfg), physical_commands=0), ensure_ascii=False, indent=2))
        return 0
    ready = args.confirm_red_slot1_ready if args.slot_id == RED_SLOT_ID else args.confirm_slot2_ready
    if args.command == 'run' and not (ready and args.confirm_hand_clear):
        parser.error('run requires the selected slot readiness flag and --confirm-hand-clear')
    if os.environ.get('ROS_DOMAIN_ID') != str(cfg['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_ROS_DOMAIN_REQUIRED')
    log_group = 'supply-red-slot1-trial' if args.slot_id == RED_SLOT_ID else 'supply-slot2-reapproach'
    directory = args.output or NATIVE.parent/'logs'/log_group/str(time.time_ns())
    directory.mkdir(parents=True, exist_ok=False)
    save(directory/'config-snapshot.json', cfg)
    with Path('/tmp/c2-assembly-'+cfg['connection']['robot_id']+'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        driver = AssemblyMotionRos(dict(mode='REAL', connection=cfg['connection'],
                                       timing=dict(service_timeout_s=3.)))
        handlers = {}
        try:
            with (directory/'events.jsonl').open('x') as journal:
                def record(event, data):
                    journal.write(json.dumps(dict(event=event, data=data, unix_s=time.time()),
                                  ensure_ascii=False, allow_nan=False)+'\n')
                    journal.flush()
                check = preflight(driver, cfg)
                save(directory/'precheck.json', check)
                if args.command == 'check':
                    print('무동작 검사 통과:', directory, '(장치 동작 0)')
                    return 0
                if sha256(args.pickup_record.read_bytes()).hexdigest() != cfg['source_record_sha256']:
                    raise RuntimeError('TEACHING_CHANGED_AFTER_PREFLIGHT')
                if cfg.get('source_grasp_review_sha256'):
                    fresh = prepare(args.pickup_record, args.slot_id)
                    if fresh != cfg:
                        raise RuntimeError('MANUAL_GRASP_REVIEW_CHANGED_AFTER_PREFLIGHT')
                for sig in (signal.SIGINT, signal.SIGTERM):
                    handlers[sig] = signal.signal(sig, interrupted)
                record('EXPLICIT_MANUAL_TEACHING_MODE', dict(slot_id=args.slot_id, supply_rgbd=False,
                       assembly_xy=False, source=str(args.pickup_record.resolve())))
                execute_one(driver, cfg, record)
                save(directory/'result.json', dict(status='APPROACH_GRIP_SIGNAL_HOLDING_NO_LIFT_TEST',
                    sample=driver.sample(), source_slot_id=args.slot_id, automatic_lift=False,
                    actual_block_lift_operator_confirmed=False, assembly_completion=False,
                    B_actual_assembly_confirmed=False, final_DB_saved=False))
                print(args.slot_id, '접근·파지 감지 후 정지. 블록을 잡은 상태입니다. 기록:', directory)
        except BaseException as exc:
            save(directory/'error.json', dict(error=str(exc), assembly_completion=False,
                 automatic_recovery=False))
            raise
        finally:
            for sig, handler in handlers.items(): signal.signal(sig, handler)
            driver.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, TimeoutError, OSError, KeyboardInterrupt) as exc:
        print('시험 중단:', exc, file=sys.stderr)
        raise SystemExit(2)
