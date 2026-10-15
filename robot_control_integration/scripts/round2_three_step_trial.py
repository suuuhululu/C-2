"""Three operator trials using the existing supply and held-block popups.

Preview is the default. Replay uses synthetic images and imposed force outcomes.
This local trial does not adopt B Current, approve A plans, or certify assembly.
"""
import argparse
from copy import deepcopy
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

NATIVE = Path(__file__).resolve().parents[1]
ROOT = NATIVE.parent
sys.path[:0] = [str(NATIVE), str(ROOT / 'perception'), str(ROOT)]
from scripts import held_corner_stud_trial as held
from scripts import supply_pick_release_trial as supply
from scripts import held_xy_seating_trial as seating
from scripts.assembly_position_trial import guard
from app.assembly_step_runner import StepReplayDriver

DEFAULT = NATIVE / 'settings/round2_three_step_trial_20261014/scenario.json'


def read(path):
    return json.loads(Path(path).read_text())


def prepare(scenario):
    # Root calibration helpers and the native D package share the name "app".
    # Add the root search path; reuse its adopted teaching and affine calculation.
    import app
    root_app = str(ROOT / 'app')
    if root_app not in app.__path__:
        app.__path__.append(root_app)
    from app.cad_trial import measured_inputs, step_geometry
    from app.round2_grasp_offset_trial import apply_held_offset_trial
    from app.round2_operator_teaching import apply_teaching, apply_supply_pickup_teaching, retarget_assembly_reference
    speed_scale = scenario.get('free_motion_speed_scale', 1.)
    if type(speed_scale) not in (int, float) or speed_scale not in (1., 2.):
        raise ValueError('FREE_MOTION_SPEED_SCALE_MUST_BE_ONE_OR_TWO')
    inputs = measured_inputs(NATIVE)
    base = held.integrated_config(
        supply.load_config(NATIVE / 'settings/held_corner_stud_20261014/config.json'),
        supply.load_config(supply.DEFAULT))
    pad = read(NATIVE / 'settings/held_corner_stud_20261014/operator-pad-top-reference-20261014.json')
    pad_offset = pad['pose'][2] - inputs['layers'][1]['sample']['posx'][2]
    prepared = []
    for case in scenario['steps']:
        target = deepcopy(case['target'])
        _, profile, reservation, correction = step_geometry(
            inputs, dict(after=target, step_id=case['step_id'], operation='PLACE', before=None,
                         prerequisites=[], requires_delivery=True), dict(grip_axis='x'), case['supply_slot'])
        settings = profile['steps']['cad/' + case['step_id']]
        row = dict(color=target['color'], brick_type=target['brick_type'], slot=case['supply_slot'],
                   span=2, close_mm=settings['pickup_width_mm'], pickup_pose=settings['pickup_pose'],
                   pose_source=inputs['supply_teaching_ref'],
                   pose_basis=profile['supply_pose_basis'], axis_basis='ORIGINAL_TAUGHT_TWO_STUD_AXIS')
        cfg = deepcopy(base)
        reference = settings['reference_pose'].copy()
        # Assembly clearance and supply/tray opening have separate reviewed bounds.
        cfg.update(blocks=[row], assembly_target_xy=reference[:2],
                   open_mm=53.,open_feedback_range_mm=[40.,80.],
                   release_width_mm=47., release_feedback_range_mm=[32., 55.],
                   alignment_approach_z_mm=reference[2] + 20., auto_yaw=True,
                   same_xy_press=True, tilt_accuracy_test=False,
                   pad_reference_at_target_physically_verified=False,
                   trial_step=deepcopy(case),
                   alignment_target=dict(target=target, placement_tcp_reference=reference,
                       clearance_mm=20., current_grasp_relation_verified=False,
                       source=profile.get('assembly_teaching_ref', str(NATIVE / 'calibration/layer_records.json'))),
                   integrated_pad_contact_pose=[*reference[:2], reference[2] + pad_offset, *reference[3:]],
                   press_force_stop_n=70.,
                   pad_contact_basis='TRANSFERRED_HEIGHT_OFFSET_OPERATOR_TRIAL_NOT_NEW_MEASUREMENT')
        if case['step_id'] == 'T2':
            cfg['seating_force_stop_n'] = 55.
        if case.get('operator_teaching_file'):
            cfg = apply_teaching(cfg, read(DEFAULT.parent / case['operator_teaching_file']))
            cfg['alignment_use_recorded_attitude'] = True
        elif case.get('raised_z_trial_mm'):
            cfg = apply_held_offset_trial(cfg, case['raised_z_trial_mm'])
        if case.get('operator_pickup_file'):
            if case.get('operator_teaching_file') or case.get('raised_z_trial_mm'):
                raise ValueError('CONFLICTING_PICKUP_TEACHING_OVERRIDES')
            path = Path(case['operator_pickup_file'])
            path = path if path.is_absolute() else ROOT / path
            cfg = apply_supply_pickup_teaching(cfg, read(path), str(path.resolve()))
        if case.get('supply_layout_file'):
            path = Path(case['supply_layout_file'])
            cfg['vision']['layout'] = str((path if path.is_absolute() else ROOT / path).resolve())
        offset_axes = [axis for axis in ('x','y') if f'assembly_board_{axis}_offset_mm' in case]
        if len(offset_axes) > 1:
            raise ValueError('ASSEMBLY_BOARD_OFFSET_AXES_CONFLICT')
        if offset_axes:
            axis = offset_axes[0]
            field = f'assembly_board_{axis}_offset_mm'
            if (type(case[field]) not in (int, float)
                    or case[field] != 1.5
                    or case['step_id'] != 'T2' or case['supply_slot'] != 3
                    or target != dict(brick_type='2x3x1', color='blue', x=13, y=11, layer=2, orientation_deg=0)):
                raise ValueError(f'T2_BOARD_{axis.upper()}_OFFSET_SCOPE_MISMATCH')
            board = inputs['board_calibration']
            if board is None:
                raise ValueError('BOARD_OFFSET_REQUIRES_ADOPTED_BOARD_TEACHING')
            tangent = board['fits']['2x3x1/0'][f'{axis}_step_xyz_mm'][:2]
            norm = math.hypot(*tangent)
            if not math.isfinite(norm) or norm <= 0:
                raise ValueError('BOARD_DIRECTION_INVALID')
            delta = [case[field] * value / norm for value in tangent]
            baseline = cfg['alignment_target']['placement_tcp_reference'].copy()
            reference = [baseline[0] + delta[0], baseline[1] + delta[1], *baseline[2:]]
            cfg = retarget_assembly_reference(cfg, reference)
            cfg['assembly_board_offset'] = dict(frame_id='assembly_board', **{f'board_{axis}_mm':1.5},
                delta_base_xy_mm=delta, baseline_placement_pose=baseline,
                source_ref=board['source_ref'], source_sha256=board['source_sha256'],
                physically_verified=False)
        if speed_scale != 1.:
            for key in ('velocity', 'rise_velocity', 'transit_velocity', 'descent_velocity'):
                cfg[key] *= speed_scale
            cfg['free_motion_speed_scale'] = speed_scale
        cfg['assembly_xy_correction_enabled'] = False
        cfg['vision_xy_alignment'] = False
        if (target['color'],target['brick_type'])==('red','1x2x1'):
            cfg['blocks'][0].update(close_mm=20.,grip_feedback_range_mm=[10.,40.],span=1,
                axis_basis='ORIGINAL_TAUGHT_ONE_STUD_AXIS')
        prepared.append(dict(case=deepcopy(case), config=cfg, reservation=reservation,
                             correction_xy_mm=correction, physical_accuracy_verified=False))
    return prepared


def open_empty_pad(driver, cfg, record, *, sleep=time.sleep, clock=time.monotonic):
    """Open after this sequence's completed release/press/vertical retreat."""
    current = driver.sample()
    motion_limit = supply.motion_force_limit(cfg)
    guard(current, cfg['connection'], motion_limit, automatic=False,
          force_norm_limit=motion_limit, required_gripper_status=current['gripper_status'])
    width=cfg['release_width_mm'];bounds=cfg['release_feedback_range_mm']
    record('NEXT_STEP_EMPTY_PAD_OPEN', dict(sample=current, width_mm=width,feedback_range_mm=bounds))
    driver.command_gripper(width, cfg['gripper_force_n'])
    deadline = clock() + 10.
    while True:
        sample = driver.sample()
        guard(dict(sample, gripper_status=0), cfg['connection'], motion_limit, automatic=False,
              force_norm_limit=motion_limit, required_gripper_status=0)
        if sample['gripper_status'] not in (0, 1, 2):
            raise RuntimeError('GRIPPER_FAULT')
        if sample['gripper_status'] == 0 and supply.width_in_range(sample,bounds) and held.motion_completed(sample,cfg):
            return
        if clock() >= deadline:
            raise TimeoutError('GRIPPER_FEEDBACK_TIMEOUT')
        sleep(.1)


def support_popup(cfg):
    lower = cfg['trial_step']['hold_lower']
    return support_dialog('Step 3 - support ready', [
        f"HOLD lower {lower['color']} {lower['brick_type']}",
        f"Grid ({lower['x']},{lower['y']}) / layer {lower['layer']}",
        'Keep holding during seating, release, press and rise.',
        'ENTER: ready / ESC: pause'])


def support_finished_popup():
    support_dialog('Step 3 - support finished', [
        'Robot press and vertical rise finished.',
        'You can release the lower structure.', 'ENTER: close'])


def trial_step_popup(case, index, total):
    return support_dialog('Round3 - next physical step', [
        f"Step {index+1}/{total}: {case['step_id']} {case['target']['color']} {case['target']['brick_type']}",
        'Check placement, supply, empty HOME and clear route.',
        'This is a trial; B has NOT confirmed assembly.',
        'ENTER: execute this step / ESC: end trial'])


def trial_return_home(driver, cfg, record, review_ref):
    from app.inspection_motion import InspectionMotion
    from app.round3_initial_inspection import DEFAULT as initial_settings, load_settings
    empty = driver.sample()
    if (empty['gripper_status'] != 2 or not 0 <= empty['gripper_width_mm'] <= 12.
            or not held.motion_completed(empty, cfg)):
        raise RuntimeError('TRIAL_STOPPED_EMPTY_CLOSED_PAD_REQUIRED')
    record('TRIAL_EMPTY_PAD_VERIFIED', dict(step_id=cfg['trial_step']['step_id'], sample=empty))
    open_empty_pad(driver, cfg, record)
    settings = load_settings(initial_settings)
    settings['route_reviewed'] = True
    motion = InspectionMotion(driver, cfg['connection'])
    receipt = motion.confirm('THREE_STEP_HOME_' + cfg['trial_step']['step_id'], 'HOME', settings, review_ref)
    if receipt['stopped_verified'] is not True:
        raise RuntimeError('TRIAL_HOME_NOT_VERIFIED')
    record('TRIAL_HOME_RETURNED', dict(step_id=cfg['trial_step']['step_id'], receipt=receipt))
    return receipt


def confirm_bound_step(case, index, total, document_path, config, scenario, profile, binding,
                       *, popup=trial_step_popup):
    if popup(case, index, total) is not True:
        return False
    # Operator review can outlast the short approval lease. Recheck after ENTER,
    # before any pickup motion, so a waiting popup cannot revive an expired Step.
    from app.round3_approved_step import validate_binding
    if validate_binding(read(document_path), config, scenario, profile) != binding:
        raise ValueError('REAL_B_STEP_BINDING_CHANGED_DURING_CONFIRMATION')
    return True


def support_dialog(title, lines):
    import cv2
    import numpy as np
    canvas = np.zeros((230, 680, 3), np.uint8)
    for index, line in enumerate(lines):
        cv2.putText(canvas, line, (20, 40 + index * 42), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 1)
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    try:
        cv2.imshow(title, canvas)
        while cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) >= 1:
            key = cv2.waitKey(30) & 255
            if key in (10, 13):
                return True
            if key == 27:
                return False
        return False
    finally:
        cv2.destroyWindow(title)


def run_sequence(driver, prepared, directory, record, *, start_zone='home', vision_factory=supply.LiveVision,
                 observe_cycle=held.observe, support_ready=support_popup, support_finished=support_finished_popup,
                 sleep=time.sleep, clock=time.monotonic, step_ready=None, home_after_step=None):
    completed, home_returns = [], []
    for index, item in enumerate(prepared):
        cfg = deepcopy(item['config'])
        case = item['case']
        if step_ready is not None:
            record('TRIAL_STEP_CONFIRMATION_REQUIRED', dict(step=case, index=index, total=len(prepared), completed_steps=completed.copy()))
            if step_ready(case, index, len(prepared)) is not True:
                return dict(status='SEQUENCE_STOPPED', completed_steps=completed,
                    stopped_step=case['step_id'], home_returns=home_returns, assembly_completion=False, current_update=False)
        record('THREE_STEP_BEGIN', dict(step=case, index=index, total=len(prepared), row=cfg['blocks'][0], source_A_preserved=True))
        step_dir = directory / case['step_id']
        step_dir.mkdir(parents=True, exist_ok=True)
        if index and home_after_step is None:
            open_empty_pad(driver, cfg, record, sleep=sleep, clock=clock)
            cfg['startup_route']['place_xy'] = driver.sample()['posx'][:2]
        vision = vision_factory(driver, cfg, step_dir)
        try:
            vision.display(cfg['blocks'][0], dict(reason='PREPARING_PICKUP'))
            supply.execute(driver, cfg, record, vision.observe, trial_row=cfg['blocks'][0],
                           start_zone='home' if home_after_step is not None else start_zone if index == 0 else 'assembly',
                           display=vision.display, hold_at_pickup=True, sleep=vision.pump_sleep, clock=clock,
                           **(dict(finalize_observation=vision.finalize_depth)
                              if cfg['vision'].get('defer_depth_pose_validation') else {}))
            held.transfer(driver, cfg, record, sleep=vision.pump_sleep)
        finally:
            vision.close()
        result = observe_cycle(driver, cfg, step_dir, record, approach_cycle=True,
                               virtual_grid=True, yaw_test=True, xy_seat_test=True,
                               support_ready=support_ready if case['human_hold'] else None)
        record('THREE_STEP_RESULT', dict(step_id=case['step_id'], index=index, total=len(prepared), result=result))
        if (result['status'] != 'CYCLE_COMPLETED'
                or home_after_step is not None and (result.get('released') is not True or result.get('press_done') is not True)):
            return dict(status='SEQUENCE_STOPPED', completed_steps=completed,
                        stopped_step=case['step_id'], result=result, assembly_completion=False, current_update=False)
        completed.append(case['step_id'])
        if case['human_hold']:
            support_finished()
        if home_after_step is not None:
            home_returns.append(home_after_step(driver, cfg, record))
    return dict(status='THREE_CYCLES_COMPLETED', completed_steps=completed,
                home_returns=home_returns, assembly_completion=False, current_update=False)


class TrialReplay(StepReplayDriver):
    """Ideal endpoints and imposed contact forces; no collision/contact physics."""
    def __init__(self):
        super().__init__([0., 0., 0., 0., 180., 0.], reaction_force_n=45.)
        self.empty_closed = False
        self.value.update(posj=[0., 0., 90., 0., 90., 0.], gripper_width_mm=60.)

    def command_gripper(self, width, force):
        super().command_gripper(width, force)
        self.empty_closed = width == 4.
        if self.empty_closed:
            self.value.update(gripper_status=2, gripper_width_mm=9.2)

    def call(self, path, kind, **fields):
        from types import SimpleNamespace
        if kind != 'SetRobotMode':
            raise NotImplementedError('Unsupported replay service: ' + kind)
        self.value['robot_mode'] = fields['robot_mode']
        return SimpleNamespace(success=True)

    def move_line_async(self, target, velocity, acceleration):
        if self.empty_closed:
            super().move_line_async(target, velocity, acceleration)
        else:
            self.moves.append(target.copy())
            self.value.update(posx=target.copy(), wrench=[0., 0., 5., 0., 0., 0.])


class ReplayVision:
    def __init__(self, driver, cfg, directory):
        self.layout = read(cfg['vision']['layout'])

    def display(self, row, decision):
        pass

    def pump_sleep(self, duration):
        pass

    def close(self):
        pass

    def observe(self, row):
        import cv2
        import numpy as np
        from app.supply_stud.backend import observe
        width, height = self.layout['image_size']
        frame = np.zeros((height, width, 3), np.uint8)
        entry = next(s for s in self.layout['slots'] if all(s[k] == row[k] for k in ('color', 'brick_type', 'slot')))
        x0, y0, x1, y1 = entry['roi_xyxy']
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        rows = int(row['brick_type'].split('x')[1])
        half_height = 19 if rows == 2 else 29
        color = (0, 255, 255) if row['color'] == 'yellow' else (255, 0, 0)
        rim = (0, 60, 60) if row['color'] == 'yellow' else (60, 0, 0)
        cv2.rectangle(frame, (cx - 19, cy - half_height), (cx + 19, cy + half_height), color, -1)
        for dx in (-8, 8):
            for n in range(rows):
                cv2.circle(frame, (cx + dx, cy + int((n - (rows - 1) / 2) * 16)), 3, rim, 1)
        decision = observe(frame, self.layout, row, time.monotonic_ns())
        decision['provenance'] = 'SYNTHETIC_RGB'
        return decision


def replay_cycle(driver, cfg, directory, record, **kwargs):
    """Replay seating/press helpers. Live pixel-yaw UI is not simulated here."""
    driver.reference = cfg['integrated_pad_contact_pose'].copy()
    lower, _ = held.approach_cycle_targets(driver.sample(), cfg)
    held.local_held_move(driver, cfg, lower, record, sleep=lambda _: None)
    if cfg.get('assembly_xy_correction_enabled', True):
        held.local_held_move(driver, cfg, seating.xy_target(driver.sample(), cfg), record, sleep=lambda _: None)
    else:
        record('ASSEMBLY_XY_CORRECTION_DISABLED',dict(reason='OPERATOR_REQUEST',
            assembly_target_xy=cfg['assembly_target_xy'],supply_xy_correction_changed=False))
    callback = kwargs.get('support_ready')
    if callback is not None:
        record('TRIAL_HUMAN_SUPPORT_REQUEST', cfg['trial_step'])
        if callback(cfg) is not True:
            return dict(status='INCOMPLETE', released=False, press_done=False, assembly_completion=False)
        record('TRIAL_HUMAN_SUPPORT_READY', dict(step_id=cfg['trial_step']['step_id'], provenance='SYNTHETIC_READY'))
    seated = seating.insert(driver, cfg, record, sleep=lambda _: None)
    release_pose = driver.sample()['posx']
    press_plan = seating.same_xy_press_plan(release_pose, cfg)
    seating.release(driver, cfg, record, operator_seated=True, sleep=lambda _: None)
    held.local_held_move(driver, cfg, press_plan['rise_pose'], record, sleep=lambda _: None, required_gripper_status=0)
    driver.command_gripper(4., cfg['gripper_force_n'])
    pressure = seating.same_xy_press_cycle(driver, cfg, press_plan, 2, record,
        lambda *a, **kw: held.local_held_move(*a, **kw, sleep=lambda _: None))
    high = driver.sample()['posx']; high[2] = cfg['pickup_clearance_z_mm']
    held.local_held_move(driver, cfg, high, record, sleep=lambda _: None, required_gripper_status=2)
    driver.stop()
    return dict(status='CYCLE_COMPLETED', released=True, press_done=True, press_result=pressure,
                seating_result=seated, image_yaw_replayed=False, support_active=callback is not None,
                assembly_completion=False)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('preview', 'replay', 'run'), nargs='?', default='preview')
    p.add_argument('--scenario', type=Path, default=DEFAULT)
    p.add_argument('--output', type=Path)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--confirm-hand-clear', action='store_true')
    p.add_argument('--start-zone', choices=('home', 'assembly', 'supply'), default='home')
    p.add_argument('--tilt-accuracy-test', action='store_true')
    p.add_argument('--only-step', choices=('T1', 'T2', 'T3'), help='One native case; T2/T3 require an approved A step binding')
    p.add_argument('--execution-profile', type=Path, help='Conditionally approved educational 25-slot supply registry')
    p.add_argument('--approved-step-document', type=Path, help='D approved design/A step binding for the matching native skill')
    p.add_argument('--three-step-trial', action='store_true', help='Approved camera-free three-step trial, manual confirmation and HOME after each step')
    p.add_argument('--return-home-after-step', action='store_true', help='Real B sequence: one bound Step, empty opening and verified HOME before releasing the writer')
    p.add_argument('--supply-depth-profile', type=Path, help='Verified RGB-D supply XY correction profile')
    p.add_argument('--educational-depth-demo', action='store_true',
                   help='Explicitly use an operator-accepted educational profile for fixed T1 only')
    args = p.parse_args(argv)
    if args.return_home_after_step and (not args.only_step or not args.approved_step_document or args.three_step_trial):
        p.error('--return-home-after-step requires one approved --only-step')
    if args.educational_depth_demo and (args.only_step != 'T1' or not args.supply_depth_profile
                                       or args.command == 'replay'):
        p.error('--educational-depth-demo requires --only-step T1 and --supply-depth-profile; no replay')
    if args.execution_profile and (args.supply_depth_profile or args.educational_depth_demo or args.command == 'replay'):
        p.error('--execution-profile cannot be combined with older depth options or synthetic replay')
    if args.only_step in ('T2', 'T3') and not args.approved_step_document:
        p.error('T2/T3 single-step requires --approved-step-document')
    if args.three_step_trial and (args.only_step or not args.approved_step_document or not args.execution_profile or args.command == 'replay'):
        p.error('--three-step-trial requires an approved sequence/profile and cannot use --only-step/replay')
    if args.approved_step_document and (not (args.only_step or args.three_step_trial) or not args.execution_profile or args.command == 'replay'):
        p.error('--approved-step-document requires --only-step and --execution-profile; no replay')
    scenario = read(args.scenario)
    prepared = prepare(scenario)
    if args.only_step:
        if not args.approved_step_document and prepared[0]['case']['step_id'] != args.only_step:
            raise ValueError('FIXED_STEP_MUST_BE_FIRST_ON_ORIGINAL_BASELINE')
        prepared = [item for item in prepared if item['case']['step_id'] == args.only_step]
        if len(prepared) != 1:
            raise ValueError('EXACT_NATIVE_STEP_REQUIRED')
    for item in prepared:
        item['config']['tilt_accuracy_test'] = args.tilt_accuracy_test
        if args.execution_profile:
            from app.supply_stud.execution_profile import bind
            item['config'] = bind(item['config'], args.execution_profile)
            cfg = item['config']
            if cfg['vision'].get('depth_center_profile'):
                from app.supply_stud.depth_center import load_profile
                load_profile(cfg['vision']['depth_center_profile'], cfg['vision']['layout'], cfg)
        if args.supply_depth_profile:
            if args.command == 'replay':
                raise ValueError('SUPPLY_DEPTH_REAL_PROFILE_NOT_FOR_SYNTHETIC_REPLAY')
            cfg = item['config']
            if args.educational_depth_demo:
                cfg['vision']['allow_educational_depth_profile'] = True
            cfg['vision']['depth_center_profile'] = str(args.supply_depth_profile.resolve())
            from app.supply_stud.depth_center import load_profile
            load_profile(cfg['vision']['depth_center_profile'], cfg['vision']['layout'], cfg)
    service_binding = None
    if args.approved_step_document:
        from app.round3_approved_step import validate_binding, validate_trial_sequence
        if args.three_step_trial:
            prepared, service_binding = validate_trial_sequence(read(args.approved_step_document), prepared,
                                                               scenario, args.execution_profile)
        else:
            document = read(args.approved_step_document)
            if bool(document.get('execution_scope') == 'ROUND3_REAL_B_THREE_STEP') != args.return_home_after_step:
                raise ValueError('REAL_B_SEQUENCE_REQUIRES_HOME_HANDOFF')
            service_binding = validate_binding(document, prepared[0]['config'],
                                               scenario, args.execution_profile)
    if args.command == 'preview' or (args.command == 'run' and not args.execute):
        result = dict(status='PREVIEW_NO_DEVICE_CONNECTION', physical_commands=0,
                      total_cycles=len(prepared), preplaced=scenario['preplaced'], steps=prepared)
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / 'preview.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'run' and not args.confirm_hand_clear:
        p.error('--confirm-hand-clear required for the existing live trial startup')
    if args.command == 'run' and os.environ.get('ROS_DOMAIN_ID') != '20':
        raise ValueError('ROS_DOMAIN_ID20_REQUIRED')
    directory = (args.output or NATIVE / 'logs/round2_three_step_trial') / str(time.time_ns())
    directory.mkdir(parents=True, exist_ok=True)
    events = []
    with (directory / 'events.jsonl').open('x') as journal:
        def record(event, data):
            entry = dict(event=event, data=deepcopy(data), unix_s=time.time())
            events.append(entry)
            journal.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + '\n'); journal.flush()
            if event in ('TRIAL_STEP_CONFIRMATION_REQUIRED','THREE_STEP_BEGIN','THREE_STEP_RESULT','TRIAL_HOME_RETURNED'):
                pending = directory / 'progress.pending.json'
                pending.write_text(json.dumps(entry, ensure_ascii=False, allow_nan=False))
                pending.replace(directory / 'progress.json')
            if event == 'THREE_STEP_BEGIN':
                print(event, json.dumps(data['step'], ensure_ascii=False), flush=True)
            elif event == 'THREE_STEP_RESULT':
                print(event, data['step_id'], data['result']['status'], flush=True)
            elif event == 'TRIAL_HUMAN_SUPPORT_REQUEST':
                print(event, json.dumps(data, ensure_ascii=False), flush=True)
        if args.command == 'replay':
            import socket
            def blocked(*a, **kw):
                raise RuntimeError('OFFLINE_REPLAY_NETWORK_DISABLED')
            socket.socket.connect = socket.socket.connect_ex = socket.create_connection = blocked
            driver = TrialReplay()
            result = run_sequence(driver, prepared, directory, record, start_zone=args.start_zone,
                                  vision_factory=ReplayVision, observe_cycle=replay_cycle,
                                  support_ready=lambda cfg: True, support_finished=lambda: None,
                                  sleep=lambda _: None)
            result.update(provenance='SYNTHETIC', backend='MOCK', physics_not_validated=True,
                          physical_commands=0, image_yaw_replayed=False)
        else:
            from app.assembly_motion_ros import AssemblyMotionRos
            old = {}
            with open('/tmp/c2-assembly-dsr01.lock', 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                driver = AssemblyMotionRos(dict(mode='REAL', connection=prepared[0]['config']['connection'],
                    timing=dict(service_timeout_s=3., stopped_sample_retry_window_s=5.),
                    stale_retry_force_stop_n=supply.motion_force_limit(prepared[0]['config']),
                    target_only_motion=prepared[0]['config'].get('target_only_motion',False)))
                try:
                    if service_binding is not None:
                        # Claim before any motion. An interrupted execution requires a new review.
                        claims = NATIVE / 'logs/approved-step-claims'
                        claims.mkdir(parents=True, exist_ok=True)
                        from hashlib import sha256
                        claim = sha256(service_binding['execution_id'].encode()).hexdigest()
                        with (claims / (claim + '.json')).open('x') as stream:
                            json.dump(service_binding, stream)
                        record('APPROVED_A_STEP_BOUND', service_binding)
                    if driver.robot_system() != 0:
                        raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
                    def interrupt(*_):
                        raise KeyboardInterrupt('OPERATOR_STOP')
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        old[sig] = signal.signal(sig, interrupt)
                    driver.feedback_record = record
                    result = run_sequence(driver, prepared, directory, record, start_zone=args.start_zone,
                        **(dict(step_ready=(lambda case,i,n:confirm_bound_step(case,i,n,
                            args.approved_step_document, prepared[0]['config'], scenario,
                            args.execution_profile, service_binding)) if args.return_home_after_step else trial_step_popup,
                            home_after_step=lambda d,c,r:trial_return_home(d,c,r,read(args.approved_step_document)['operator_review_ref']))
                           if args.three_step_trial or args.return_home_after_step else {}))
                except BaseException:
                    driver.stop()
                    raise
                finally:
                    for sig, handler in old.items():
                        signal.signal(sig, handler)
                    driver.close()
        if args.only_step and result['status'] == 'THREE_CYCLES_COMPLETED':
            result['status'] = 'FIXED_STEP_EXECUTED'
        if args.command == 'run':
            result.update(provenance='LIVE_D_RUNTIME', backend='REAL')
        if service_binding is not None:
            result['service_binding'] = service_binding
        result['output_directory'] = str(directory.resolve())
        (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] in ('THREE_CYCLES_COMPLETED', 'FIXED_STEP_EXECUTED') else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, TimeoutError) as error:
        print('시험 중단:', error, file=sys.stderr)
        raise SystemExit(2)
