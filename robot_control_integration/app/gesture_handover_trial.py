"""Local moving handover: verified STOP precedes the explicitly reviewed release policy."""
import math
import time

from app.assembly_motion import pose_error,motion_still
from app.assembly_step_bridge import pose, release_feedback_range
from scripts.assembly_position_trial import guard, run
from app.assembly_blend_trial import run_blend


class MotionReceiveStop(RuntimeError):
    """Unwind the active position move through its existing verified STOP path."""


def validate_handover(plan, profile, session):
    config = plan['settings'].get('handover_trial', {})
    if (plan['mode'] != 'ROBOT_GRIP' or plan['assistance_kind'] != 'NONE' or
            config.get('operator_armed_preview_stop_trial') is not True or
            config.get('observe_route_reviewed') is not True or
            (session.get('backend') == 'REAL' and session.get('provenance') != 'LOCAL_OPERATOR_TRIAL') or
            session.get('allowed_trial_phase') != 'handover'):
        raise ValueError('EXPLICIT_LOCAL_HANDOVER_TRIAL_REVIEW_REQUIRED')
    observe = pose(config.get('observe_pose'), 'observe_pose')
    hold = config.get('open_hold_seconds', 1.)
    if type(hold) not in (int, float) or not .4 <= hold <= 5:
        raise ValueError('INVALID_HANDOVER_OPEN_HOLD_SECONDS')
    for name in ('incoming_velocity', 'incoming_acceleration'):
        value = config.get(name, profile['transfer_velocity' if name == 'incoming_velocity' else 'transfer_acceleration'])
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('INVALID_HANDOVER_PARAMETER:'+name)
    if observe[2] <= profile['clearance_z_mm']:
        raise ValueError('OBSERVE_MUST_BE_ABOVE_TRANSPORT_CLEARANCE')
    zone = session.get('handover_start_zone', 'supply')
    if zone not in ('supply', 'place'):
        raise ValueError('HANDOVER_START_ZONE_INVALID')
    if zone == 'place':
        start = pose(session.get('handover_start_pose'), 'handover_start_pose')
        if (not session.get('recovery_evidence_ref') or
                math.dist(start[:2], profile['place_pose'][:2]) > .05 or
                abs(start[2]-profile['clearance_z_mm']) > .05):
            raise ValueError('REVIEWED_PLACE_HANDOVER_RECOVERY_REQUIRED')
    release_feedback_range(plan['settings'], plan['settings']['release_width_mm'])
    if config.get('no_receive_action', 'HOLD') not in ('HOLD', 'ASSEMBLE'):
        raise ValueError('INVALID_NO_RECEIVE_ACTION')
    policy = config.get('release_policy', 'HMI')
    if policy not in ('HMI', 'AUTO_AFTER_STOP'):
        raise ValueError('INVALID_HANDOVER_RELEASE_POLICY')
    if policy == 'AUTO_AFTER_STOP' and (
            session.get('automatic_handover_release_reviewed') is not True or
            not session.get('automatic_handover_review_ref')):
        raise ValueError('EXPLICIT_AUTOMATIC_HANDOVER_REVIEW_REQUIRED')


def run_handover(driver, connection, plan, profile, confirm, record, camera_poll,
                 *, clock=time.monotonic, sleep=time.sleep):
    if camera_poll is None:
        raise ValueError('MOVING_HANDOVER_CAMERA_REQUIRED')
    session = driver.session
    validate_handover(plan, profile, session.value)
    settings = plan['settings']
    observe = pose(settings['handover_trial']['observe_pose'], 'observe_pose')
    height, force = profile['clearance_z_mm'], profile['force_stop_n']
    automatic_release = settings['handover_trial'].get('release_policy', 'HMI') == 'AUTO_AFTER_STOP'
    hold_ns = round(settings['handover_trial'].get('open_hold_seconds', 1.)*1_000_000_000)
    zone = session.value.get('handover_start_zone', 'supply')
    expected = session.value['handover_start_pose'] if zone == 'place' else settings['pickup_pose']
    def check_start(sample):
        guard(sample, connection, force, automatic=True, force_norm_limit=force)
        distance, angle = pose_error(sample['posx'], pose(expected, 'handover_start_pose'))
        if distance > 1. or angle > 1.:
            raise RuntimeError('HANDOVER_REQUIRES_REVIEWED_START_POSE')
    check_start(driver.sample())
    result = dict(key=plan['key'], phase='handover', mode=plan['mode'],
                  assembly_completion=False, current_update=False, automatic_retry=False,
                  operator_seating_confirmed=False, preview_is_verified_gesture=False,
                  release_requires_post_stop_hmi=not automatic_release,
                  automatic_release_policy='AUTO_AFTER_VERIFIED_STOP_AND_FRESH_CUE' if automatic_release else None)

    def finish(status):
        result['status'] = status
        record('STEP_RESULT', result.copy())
        return result

    def no_receive(reason, assembly_start_zone):
        if settings['handover_trial'].get('no_receive_action') == 'ASSEMBLE':
            result.update(assembly_required=True, assembly_reason=reason,
                          assembly_start_zone=assembly_start_zone,
                          fresh_assembly_plan_required=True)
            record('ASSEMBLY_FALLBACK_REQUIRED', result.copy())
            return finish('ASSEMBLY_REQUIRED')
        if reason == 'NO_RECEIVE_SIGNAL':
            return finish('PAUSED_HANDOVER_NO_GESTURE_HOLDING')
        raise RuntimeError(reason)

    def wait(kind):
        sample = driver.stillness()
        record('WAIT_'+kind, dict(sample=sample, block=plan['block']))
        return confirm(kind, plan, sample) is True

    def move(label, target, held=2, monitor=None):
        record('STEP_MOVE', dict(label=label, target=target, gripper_status=held))
        current = driver.sample()['posx']
        config = settings['handover_trial']
        rate = config.get('incoming_velocity', profile['transfer_velocity']) if monitor else profile['transfer_velocity']
        acceleration = config.get('incoming_acceleration', profile['transfer_acceleration']) if monitor else profile['transfer_acceleration']
        run(driver, connection, target, force, monitor or record,
            clearance_z=max(current[2], target[2]), transfer_only=target[2] >= current[2],
            transfer_rate=rate, descent_rate=profile['descent_velocity'],
            transfer_acceleration=acceleration,
            descent_acceleration=profile['descent_acceleration'], set_automatic_mode=False,
            force_norm_stop_n=force, required_gripper_status=held, clock=clock, sleep=sleep)

    request = None
    stop = None
    candidate = None
    last_frame = None

    def fresh(row):
        nonlocal last_frame
        if row is None:
            return False
        for key in ('execution_id', 'source_epoch', *session.binding):
            expected = session.binding[key] if key in session.binding else session.value[key]
            if row.get(key) != expected:
                raise RuntimeError('HANDOVER_CAMERA_CONTEXT_MISMATCH:'+key)
        if row.get('preview_request_id') != request['request_id']:
            raise RuntimeError('HANDOVER_CAMERA_REQUEST_MISMATCH')
        received = row.get('received_monotonic_ns')
        if (type(received) is not int or
                not 0 <= clock()*1e9-received <= session.value['frame_max_age_s']*1e9):
            return False
        if last_frame is not None and received <= last_frame:
            return False
        last_frame = received
        return True

    def await_camera():
        deadline = clock()+8.
        while not fresh(camera_poll()):
            if clock() >= deadline:
                raise RuntimeError('HANDOVER_CAMERA_NOT_READY')
            sleep(.05)

    if not wait('START_HANDOVER'):
        return finish('PAUSED_START')
    # Check the actual decoded frame before any loaded travel, not just DDS discovery.
    request = session.open_request('RECEIVE')
    try:
        try:
            await_camera()
        except RuntimeError as error:
            if str(error) not in ('HANDOVER_CAMERA_NOT_READY', 'THEORA_RELAY_EXITED'):
                raise
            return no_receive(str(error), zone)
        record('HANDOVER_CAMERA_READY_BEFORE_MOTION', dict(received_monotonic_ns=last_frame))
    finally:
        session.close_request()
    current = driver.sample()
    check_start(current)
    start = current['posx']
    orientation = start[3:]
    if zone == 'supply':
        move('HANDOVER_LIFT', [*start[:2], max(height, start[2]), *orientation])
        route = [('SUPPLY_20_0', profile['supply_transit_xy_mm']),
                 ('BODY_BYPASS', profile['body_bypass_xy_mm']),
                 ('PLACE_BOARD', profile['place_pose'][:2])]
        if profile.get('transport_blending'):
            targets = [[*xy, height, *orientation] for _,xy in route]
            record('STEP_MOVE', dict(label='BLENDED_LOADED_TRANSIT', targets=targets, gripper_status=2))
            run_blend(driver, connection, targets, profile, record, held=2, clock=clock, sleep=sleep)
        else:
            for label,xy in route:
                move(label, [*xy, height, *orientation])

    # Only the reviewed final incoming segment is armed. Supply travel cannot release.
    request = session.open_request('RECEIVE')
    last_frame = None

    def monitor(event, data):
        nonlocal stop, candidate
        record(event, data)
        if event == 'ABORT':
            stop = data['stop']
        if event != 'MOTION_SAMPLE':
            return
        guard(data['sample'], connection, force, automatic=True, force_norm_limit=force)
        row = camera_poll()
        if fresh(row) and row.get('candidate_event') == 'OPEN_HAND_HELD_ORIENTATION_UNKNOWN':
            candidate = row
            record('HANDOVER_PREVIEW_REQUESTED_STOP', dict(candidate=row,
                   automatic_release_authorized=False, verified_gesture=False))
            raise MotionReceiveStop('OPEN_HAND_PREVIEW_REQUESTED_STOP')
        if clock()*1e9-last_frame > session.value['frame_max_age_s']*1e9:
            raise RuntimeError('HANDOVER_CAMERA_STALE')

    try:
        try:
            await_camera()
        except RuntimeError as error:
            if str(error) not in ('HANDOVER_CAMERA_NOT_READY', 'THEORA_RELAY_EXITED'):
                raise
            return no_receive(str(error), 'place')
        target = [*settings['reference_pose'][:2], height, *orientation]
        try:
            move('HANDOVER_INCOMING', target, monitor=monitor)
        except MotionReceiveStop:
            if (stop is None or stop.get('acknowledged') is not True or
                    stop.get('stillness_verified') is not True or
                    driver.command_outcome_unknown):
                raise RuntimeError('HANDOVER_STOP_NOT_VERIFIED')
            driver.own('WAIT')
        except RuntimeError as error:
            if str(error) not in ('HANDOVER_CAMERA_STALE', 'THEORA_RELAY_EXITED'):
                raise
            if (stop is None or stop.get('acknowledged') is not True or
                    stop.get('stillness_verified') is not True or driver.command_outcome_unknown):
                raise RuntimeError('HANDOVER_STOP_NOT_VERIFIED')
            driver.own('WAIT')
            return no_receive(str(error), 'place')
        else:
            driver.own('WAIT')
            return no_receive('NO_RECEIVE_SIGNAL', 'assembly')
    finally:
        session.close_request()

    result['motion_stop_verified'] = True
    result['stop_candidate'] = candidate
    if not automatic_release and not wait('HANDOVER_RELEASE'):
        return finish('PAUSED_HANDOVER_RECEIVING_CONFIRMATION')
    guard(driver.sample(), connection, force, automatic=True, force_norm_limit=force)

    auto_cue = None
    def observe_auto(sample):
        nonlocal auto_cue
        guard(sample, connection, force, automatic=True, force_norm_limit=force)
        row = camera_poll()
        if fresh(row):
            hands = row.get('hands', [])
            if (len(hands) != 1 or hands[0].get('pose') != 'OPEN_HAND' or
                    row.get('held_ns', 0) < hold_ns or
                    row.get('continuity_estimate') is not True):
                raise RuntimeError('HANDOVER_RECEIVING_SIGNAL_WITHDRAWN')
            auto_cue = row
        if auto_cue is None or clock()*1e9-auto_cue['received_monotonic_ns'] > session.value['frame_max_age_s']*1e9:
            raise RuntimeError('HANDOVER_AUTO_RELEASE_CAMERA_STALE')

    def check_auto_release():
        observe_auto(driver.snapshot)
        record('AUTOMATIC_HANDOVER_RELEASE_AUTHORIZED', dict(fresh_candidate=auto_cue,
               stop_verified=True, receiver_position_verified=False,
               authorization='EXPLICIT_LOCAL_OPERATOR_ARMED_TRIAL', hmi_response_fabricated=False))

    if automatic_release:
        # Reset the one-shot preview context after STOP; withdrawn hands cannot open.
        request = session.open_request('RECEIVE')
        last_frame = None
        deadline = clock()+2.5
        try:
            while clock() < deadline:
                guard(driver.sample(), connection, force, automatic=True, force_norm_limit=force)
                row = camera_poll()
                if fresh(row) and row.get('candidate_event') == 'OPEN_HAND_HELD_ORIENTATION_UNKNOWN':
                    auto_cue = row
                    break
                sleep(.05)
            if auto_cue is None:
                return finish('PAUSED_HANDOVER_NO_FRESH_RECEIVING_SIGNAL')
            observe_auto(driver.sample())
        except BaseException:
            session.close_request()
            raise

    width = settings['release_width_mm']
    bounds = release_feedback_range(settings, width)
    try:
        if automatic_release:
            driver.own('GRIPPER', during_stillness=observe_auto)
        record('AUTO_GRIPPER_REQUEST' if automatic_release else 'GRIPPER_REQUEST',
               dict(width_mm=width, force_n=profile['gripper_force_n'], expected_status=0, feedback_range_mm=bounds))
        driver.command_gripper(width, profile['gripper_force_n'],
            **(dict(precondition=check_auto_release, during_stillness=observe_auto) if automatic_release else {}))
    finally:
        if automatic_release:
            session.close_request()
    deadline, consecutive = clock()+10., 0
    sleep(.1)
    while True:
        sample = driver.sample()
        record('GRIPPER_FEEDBACK', sample)
        actual = sample['gripper_width_mm']
        if (sample['query_duration_s'] > .5 or sample['tcp'] != connection['tcp'] or
                sample['tool'] != connection['tool'] or sample['robot_mode'] != 1 or
                sample['robot_state'] not in (1, 2) or sample['drl_state'] != 3):
            raise RuntimeError('INVALID_HANDOVER_GRIPPER_FEEDBACK')
        if (type(actual) not in (int, float) or not math.isfinite(actual) or
                sample['gripper_status'] not in (0, 1, 2, 3)):
            raise RuntimeError('HANDOVER_GRIPPER_SAFETY_OR_STATUS_FAULT')
        if not 0 <= actual <= 110:
            raise RuntimeError('INVALID_GRIPPER_WIDTH_FEEDBACK')
        complete = (sample['gripper_status'] == 0 and bounds[0] <= actual <= bounds[1] and
                    motion_still(sample,session.value['stillness']))
        consecutive = consecutive+1 if complete else 0
        if consecutive >= 3:
            break
        if clock() >= deadline:
            raise RuntimeError('GRIPPER_COMPLETION_NOT_VERIFIED')
        sleep(.05)
    driver.own('WAIT')
    # Rejoin the reviewed place transit before ascending to the taught observe height.
    current = driver.sample()['posx']
    move('HANDOVER_EMPTY_PLACE', [*profile['place_pose'][:2], max(height, current[2]),
                                *current[3:]], 0)
    current = driver.sample()['posx']
    move('OBSERVE_HEIGHT_LIFT', [*current[:2], observe[2], *current[3:]], 0)
    move('OBSERVE_POINT', observe, 0)
    driver.own('WAIT')
    final = driver.snapshot
    distance, angle = pose_error(final['posx'], observe)
    if distance > .05 or angle > .05:
        raise RuntimeError('OBSERVE_POINT_NOT_VERIFIED')
    result.update(final_sample=final, observe_point_verified=True,
                  operator_receiving_confirmed=not automatic_release,
                  automatic_receiving_signal_confirmed=automatic_release)
    return finish('LOCAL_HANDOVER_OBSERVE_COMPLETE')
