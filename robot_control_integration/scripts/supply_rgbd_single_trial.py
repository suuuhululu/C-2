"""Explicit fixed-slot T1/T2 supply RGB-D approach/close/hold; no assembly or automatic lift."""
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
from scripts.slot2_pickup_trial import preflight, waypoints, interrupted
from scripts.capture_supply_depth_reference import save
from app.assembly_motion import pose_error
from app.assembly_motion_ros import AssemblyMotionRos
from app.supply_stud.depth_center import load_profile

SLOT_ID = 'yellow_2x2x1_04'


def prepare(path, accept_t2_educational_profile=False, execution_profile=None):
    cfg = json.loads(path.read_text())
    if execution_profile is not None:
        from app.supply_stud.execution_profile import bind
        if (cfg.get('schema_version') != 'educational-supply-single-trial/1'
                or cfg.get('scope') != 'EDUCATIONAL_APPROACH_CLOSE_HOLD_ONLY'
                or cfg.get('automatic_lift') is not False
                or cfg.get('target_only_motion') is not False):
            raise ValueError('EDUCATIONAL_SINGLE_SUPPLY_SCOPE_REQUIRED')
        cfg = bind(cfg, execution_profile)
        supply.validate_rows(cfg, cfg['blocks'], require_ready=True)
        supply.validate_teaching_location(cfg, cfg['blocks'][0]['pickup_pose'])
        if cfg['vision'].get('depth_center_profile'):
            load_profile(cfg['vision']['depth_center_profile'], cfg['vision']['layout'], cfg)
        return cfg
    if (cfg.get('schema_version') != 'supply-rgbd-single-trial/1'
            or cfg.get('scope') not in ('FIXED_T1_SUPPLY_APPROACH_CLOSE_HOLD_ONLY', 'T2_SUPPLY_APPROACH_CLOSE_HOLD_ONLY')
            or cfg.get('assembly_xy_correction_enabled') is not False
            or cfg.get('automatic_lift') is not False
            or cfg.get('target_only_motion') is not False
            or len(cfg.get('blocks', [])) != 1):
        raise ValueError('EXPLICIT_SUPPLY_ONLY_SINGLE_T1_PROFILE_REQUIRED')
    row = cfg['blocks'][0]
    is_t2 = cfg['scope'] == 'T2_SUPPLY_APPROACH_CLOSE_HOLD_ONLY'
    expected = ('blue', '2x3x1', 3, 2) if is_t2 else ('yellow', '2x2x1', 4, 2)
    if tuple(row[k] for k in ('color', 'brick_type', 'slot', 'span')) != expected:
        raise ValueError('EXACT_PROFILE_SLOT_REQUIRED')
    flag = 'allow_educational_t2_depth_profile' if is_t2 else 'allow_educational_depth_profile'
    if cfg['vision'].get(flag) is not True:
        raise ValueError('EXPLICIT_SLOT_SCOPED_EDUCATIONAL_PROFILE_REQUIRED')
    if is_t2:
        cfg['operator_accepted_t2_educational_profile'] = bool(accept_t2_educational_profile)
    if not cfg.get('source_sha256'):
        raise ValueError('PROFILE_SOURCE_BINDINGS_REQUIRED')
    for source, expected in cfg['source_sha256'].items():
        if sha256(Path(source).read_bytes()).hexdigest() != expected:
            raise ValueError('PROFILE_SOURCE_CHANGED:'+source)
    supply.validate_rows(cfg, [row], require_ready=True)
    supply.validate_teaching_location(cfg, row['pickup_pose'])
    if is_t2 and not accept_t2_educational_profile:
        return cfg  # Preview only; check/run must opt in before connecting.
    profile = load_profile(cfg['vision']['depth_center_profile'], cfg['vision']['layout'], cfg)
    if profile.get('independently_verified') is not False:
        raise ValueError('KEEP_ORIGINAL_EDUCATIONAL_VERIFICATION_SCOPE')
    return cfg


def check_corrected_endpoint(driver, cfg, decision):
    if not decision.get('depth_center_required'):
        raise ValueError('RGBD_CORRECTION_REQUIRED_NO_TEACHING_FALLBACK')
    target = supply.center_target(cfg['blocks'][0], deepcopy(decision))
    checked = deepcopy(cfg); checked['blocks'][0]['pickup_pose'] = target
    endpoints = []
    for label, point in waypoints(checked)[2:]:
        fk = driver.check_pose(point)
        gap = pose_error(fk, point)
        if any(v > .05 for v in gap):
            raise RuntimeError('CORRECTED_ENDPOINT_IK_FK_MISMATCH:'+label)
        endpoints.append(dict(label=label, target=point, error_mm_deg=list(gap)))
    return endpoints


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preview', 'check', 'run'), nargs='?', default='preview')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--execution-profile', type=Path)
    parser.add_argument('--confirm-slot-ready', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-slot4-ready', action='store_true')
    parser.add_argument('--confirm-slot3-ready', action='store_true')
    parser.add_argument('--accept-t2-educational-profile', action='store_true')
    parser.add_argument('--confirm-hand-clear', action='store_true')
    args = parser.parse_args(argv)
    import cv2
    cv2.setNumThreads(1)
    cfg = prepare(args.config, args.accept_t2_educational_profile, args.execution_profile)
    is_t2 = cfg['scope'] == 'T2_SUPPLY_APPROACH_CLOSE_HOLD_ONLY'
    slot_id = f"{cfg['blocks'][0]['color']}_{cfg['blocks'][0]['brick_type']}_{cfg['blocks'][0]['slot']:02d}"
    config_hash = sha256(args.config.read_bytes()).hexdigest()
    if args.command == 'preview' or (args.command == 'run' and not args.execute):
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION', config=cfg,
                             nominal_waypoints=waypoints(cfg), physical_commands=0), ensure_ascii=False, indent=2))
        return 0
    if is_t2 and not args.accept_t2_educational_profile:
        parser.error('T2 check/run requires --accept-t2-educational-profile')
    ready = (args.confirm_slot_ready if args.execution_profile else
             (args.confirm_slot3_ready if is_t2 else args.confirm_slot4_ready))
    if args.command == 'run' and not (ready and args.confirm_hand_clear):
        parser.error('run requires the selected slot ready flag and --confirm-hand-clear')
    if os.environ.get('ROS_DOMAIN_ID') != str(cfg['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_ROS_DOMAIN_REQUIRED')
    group = ('educational-supply-trial' if args.execution_profile else
             ('supply-rgbd-T2-slot3-trial' if is_t2 else 'supply-rgbd-slot4-trial'))
    out = args.output or NATIVE.parent/'logs'/group/str(time.time_ns())
    out.mkdir(parents=True, exist_ok=False)
    save(out/'config-snapshot.json', cfg)
    with Path('/tmp/c2-assembly-'+cfg['connection']['robot_id']+'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        driver = AssemblyMotionRos(dict(mode='REAL', connection=cfg['connection'], timing=dict(service_timeout_s=3.)))
        vision = None; handlers = {}; decisions = []
        try:
            with (out/'events.jsonl').open('x') as journal:
                def record(event, data):
                    if event == 'VISION_DECISION': decisions.append(data)
                    journal.write(json.dumps(dict(event=event, data=data, unix_s=time.time()),
                                             ensure_ascii=False, allow_nan=False)+'\n'); journal.flush()
                save(out/'precheck.json', preflight(driver, cfg))
                camera_cfg = deepcopy(cfg)
                camera_cfg['vision']['show_window'] = args.command == 'run'
                camera_cfg['vision']['defer_depth_evidence'] = True
                vision = supply.LiveVision(driver, camera_cfg, out)
                if args.command == 'check':
                    decision = vision.observe(cfg['blocks'][0])
                    endpoints = (check_corrected_endpoint(driver, cfg, decision)
                                 if cfg['vision'].get('depth_center_profile') else [])
                    save(out/'live-check.json', dict(status='READ_ONLY_SUPPLY_READY', decision=decision,
                                                   corrected_endpoints=endpoints, physical_commands=0))
                    print('실시간 공급 무동작 검사 통과:', out)
                    print('공급 모드:', cfg.get('educational_supply_binding', {}).get('execution_mode', 'RGBD_XY'))
                    if decision.get('depth_center'): print('현재 XY 보정(mm):', decision['depth_center']['delta_xy_mm'])
                    return 0
                if config_hash != sha256(args.config.read_bytes()).hexdigest() or prepare(args.config, args.accept_t2_educational_profile, args.execution_profile) != cfg:
                    raise ValueError('EXECUTION_PROFILE_CHANGED_AFTER_PREFLIGHT')
                for sig in (signal.SIGINT, signal.SIGTERM):
                    handlers[sig] = signal.signal(sig, interrupted)
                supply.execute(driver, cfg, record, vision.observe, trial_row=cfg['blocks'][0],
                    start_zone='supply', hold_at_pickup=True, display=None, sleep=vision.pump_sleep)
                if decisions: vision.display(cfg['blocks'][0], decisions[-1])
                save(out/'result.json', dict(status='APPROACH_GRIP_SIGNAL_HOLDING_NO_LIFT_TEST',
                    supply_mode=cfg.get('educational_supply_binding', {}).get('execution_mode', 'RGBD_XY'),
                    source_slot_id=slot_id, sample=driver.sample(), automatic_lift=False,
                    operator_exact_grasp_confirmed=False, assembly_completion=False,
                    B_actual_assembly_confirmed=False, final_DB_saved=False))
                print(slot_id, 'RGB-D 접근·파지 후 정지. 자동 상승 없음. 기록:', out)
        except BaseException as exc:
            save(out/'error.json', dict(error=str(exc), automatic_recovery=False, assembly_completion=False))
            raise
        finally:
            for sig, handler in handlers.items(): signal.signal(sig, handler)
            try:
                if vision is not None: vision.close()
            finally:
                driver.close()
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, RuntimeError, TimeoutError, OSError, KeyboardInterrupt) as exc:
        print('시험 중단:', exc, file=sys.stderr)
        raise SystemExit(2)
