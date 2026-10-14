"""단계 실행: 기존 위치 이동/35N 누름/그리퍼 어댑터를 재사용한다."""
from copy import deepcopy
import math
import time

from app.assembly_motion import pose_error,motion_still
from app.assembly_step_bridge import pose, release_feedback_range, validate_physical
from app.assembly_strategy import has_source_release_press, is_release_press
from scripts.assembly_position_trial import run, guard, trial_motion_still
from scripts.assembly_press_trial import press
from app.assembly_blend_trial import run_blend


def rotate_base_z_pose(value, degrees):
    """Base Z에서 회전하면 ZYZ 첫 Z(A)에 정확히 더해진다. 관절6 명령이 아니다."""
    result = pose(value, 'rotation_pose')
    if type(degrees) not in (int, float) or not math.isfinite(degrees):
        raise ValueError('FINITE_BASE_Z_TURN_REQUIRED')
    result[3] = (result[3]+degrees+180.) % 360.-180.
    return result


def assembly_target_pose(settings):
    """실측 조립 자세가 있으면 보존하고, 기존 Step은 공급 파지+회전을 사용한다."""
    orientation=settings.get('assembly_tcp_zyz_deg')
    if orientation is None:
        orientation=rotate_base_z_pose(settings['pickup_pose'],settings.get('turn_base_z_deg',0))[3:]
    if not isinstance(orientation,list) or len(orientation)!=3:
        raise ValueError('ASSEMBLY_TCP_ZYZ_TRIPLE_REQUIRED')
    return pose(list(settings['reference_pose'][:3])+orientation,'assembly_target_pose')


def run_step(driver, connection, plan, profile, confirm, record, *, phase='full',
             start_zone='assembly', pickup_center=None, assembly_alignment=None, clock=time.monotonic, sleep=time.sleep):
    if phase not in ('full', 'pickup', 'approach', 'contact', 'release', 'retreat', 'assemble-held', 'grasp-recovery', 'human-wait', 'human-ack') or start_zone not in ('assembly', 'place', 'supply'):
        raise ValueError('INVALID_PHASE_OR_START_ZONE')
    angular={name:profile[name] for name in ('angular_velocity','angular_acceleration')
             if profile.get(name) is not None} if profile.get('round2') else {}
    if getattr(driver, 'mode', None) == 'REAL':
        validate_physical(plan, profile, phase)
    settings = deepcopy(plan['settings'])
    release_press = is_release_press(plan)
    human_release_press = has_source_release_press(plan) and plan['assistance_kind'] in ('PRESS', 'PRESS_AND_HOLD')
    stillness_policy=getattr(getattr(driver,'session',None),'value',{}).get('stillness',{})
    result = dict(key=plan['key'], phase=phase, mode=plan['mode'],
                  assembly_completion=False, current_update=False, automatic_retry=False,
                  operator_seating_confirmed=False, status='STARTED')
    if has_source_release_press(plan):
        result.update(assembly_strategy=plan['assembly_strategy'],
                      d_execution_strategy='RELEASE_PRESS',robot_press_executed=False)
    force = profile['force_stop_n']
    source_release_press=has_source_release_press(plan)
    motion_force=(None if profile.get('noncontact_force_guard') is False else
                  profile.get('motion_force_stop_n',force)) if source_release_press else force
    target_only=source_release_press and profile.get('target_only_motion',False)
    motion_options=dict(angular)
    if target_only:motion_options['target_only_motion']=True
    stopped=trial_motion_still if target_only else motion_still
    reference = pose(settings['reference_pose'], 'reference_pose')
    height = max(profile['clearance_z_mm'], reference[2]+profile['approach_offset_mm'])
    human_config = settings.get('human_step_gestures')
    if human_config:
        if driver.mode=='REAL' and not hasattr(driver,'session'):
            raise ValueError('HUMAN_GESTURE_CONTROLLED_DRIVER_REQUIRED')
        height = max(height,human_config['wait_z_mm'])
    if phase in ('human-wait','human-ack') and (not human_config or plan['mode']!='HUMAN_ASSEMBLY' or
            plan['assistance_kind']!='MANUAL_ASSEMBLY'):
        raise ValueError('HUMAN_WAIT_REQUIRES_MANUAL_TARGET_HIGH_HANDOVER')
    events = []
    device=getattr(driver,'raw',driver)
    last_context=getattr(device,'last_step_gripper_context',None)
    reuse_empty_pad=bool(profile.get('round2')) and bool(last_context) and last_context.get('state')=='EMPTY_PAD_CLOSED'
    empty_pad_status=last_context['gripper_status'] if reuse_empty_pad else 0

    def emit(event, data):
        events.append(event)
        record(event, data)

    def wait(kind):
        # The controlled driver verifies pose/velocity over the reviewed window;
        # one extra exact-zero read can reject settling after a successful grasp.
        verify = getattr(driver, 'stillness', None)
        sample = verify() if callable(verify) else driver.sample()
        if not callable(verify) and not stopped(sample,stillness_policy):
            emit('WAIT_SAMPLE_REJECTED', dict(kind=kind, sample=sample))
            raise RuntimeError('WAIT_REQUIRES_STOPPED_ROBOT')
        emit('WAIT_'+kind, dict(key=plan['key'], block=plan['block'], sample=sample,
                              human_actions=plan['human_actions']))
        return confirm(kind, plan, sample) is True

    def move(label, target, held=2, speed=None, acceleration=None):
        current = driver.sample()['posx']
        target = pose(target, label)
        if profile.get('round2'):
            vertical_rate=profile['descent_velocity'] if speed is None else speed
            horizontal_rate=profile['transfer_velocity'] if speed is None else speed
            vertical_acc=profile['descent_acceleration'] if acceleration is None else acceleration
            horizontal_acc=profile['transfer_acceleration'] if acceleration is None else acceleration
            emit('STEP_MOVE',dict(label=label,target=target,gripper_status=held))
            vertical_only=math.dist(current[:2],target[:2])<=.05
            if target[2]>current[2]+.05 and not vertical_only:
                lifted=[*current[:2],target[2],*current[3:]]
                run(driver,connection,lifted,motion_force,emit,clearance_z=target[2],lift_only=True,
                    transfer_rate=vertical_rate,descent_rate=vertical_rate,
                    transfer_acceleration=vertical_acc,descent_acceleration=vertical_acc,
                    set_automatic_mode=False,force_norm_stop_n=motion_force,required_gripper_status=held,
                    clock=clock,sleep=sleep,**motion_options)
                current=driver.sample()['posx']
            rising=target[2]>current[2]+.05
            run(driver,connection,target,motion_force,emit,clearance_z=target[2] if rising else None,
                transfer_only=target[2]>=current[2]-.05,
                transfer_rate=vertical_rate if rising and vertical_only else horizontal_rate,
                descent_rate=vertical_rate,
                transfer_acceleration=vertical_acc if rising and vertical_only else horizontal_acc,
                descent_acceleration=vertical_acc,set_automatic_mode=False,
                force_norm_stop_n=motion_force,required_gripper_status=held,clock=clock,sleep=sleep,**motion_options)
            return
        rate = profile['transfer_velocity'] if speed is None else speed
        if acceleration is None:
            acceleration = profile['transfer_acceleration'] if speed is None else profile['descent_acceleration']
        upward = target[2] >= current[2]
        emit('STEP_MOVE', dict(label=label, target=target, gripper_status=held))
        run(driver, connection, target, motion_force, emit,
            clearance_z=(target[2] if target[2]>current[2]+.05 else None) if profile.get('round2') else max(current[2], target[2]),
            transfer_only=target[2]>=current[2]-.05 if profile.get('round2') else upward,
            transfer_rate=rate, descent_rate=rate, transfer_acceleration=acceleration,
            descent_acceleration=acceleration, set_automatic_mode=False,
            force_norm_stop_n=motion_force, required_gripper_status=held, clock=clock, sleep=sleep,
            **({'target_only_motion':True} if target_only else {}))

    def lift(held=2):
        current = driver.sample()['posx']
        target = current.copy()
        target[2] = max(height, current[2])
        move('LIFT', target, held)

    def transit(label, xy, orientation, held=2):
        move(label, [*xy, height, *orientation], held)

    def transits(route, orientation, held=2):
        if profile.get('transport_blending') and len(route) >= 2:
            targets = [[*xy, height, *orientation] for _,xy in route]
            emit('STEP_MOVE', dict(label='BLENDED_TRANSIT', targets=targets, gripper_status=held))
            run_blend(driver, connection, targets, profile, emit, held=held, clock=clock, sleep=sleep)
        else:
            for label,xy in route:
                transit(label, xy, orientation, held)

    def grip(width, expected, feedback_bounds=None, *, empty_pad=False):
        if type(width) not in (int, float) or not math.isfinite(width) or not 0 <= width <= 110:
            raise ValueError('D_MEASURED_GRIPPER_WIDTH_REQUIRED')
        bounds = (release_feedback_range(settings, width) if expected == 0 and
                  width == settings['release_width_mm'] else [max(0., width-1.), min(110., width+1.)])
        if feedback_bounds is not None:
            bounds = feedback_bounds
        initial = driver.sample()
        if empty_pad and (expected!=0 or initial['gripper_status']!=0 or width>12.):
            raise ValueError('EMPTY_PAD_CLOSE_REQUIRES_RELEASED_GRIPPER')
        if not stopped(initial,stillness_policy):
            verify=getattr(driver,'stillness',None)
            if callable(verify):initial=verify()
            else:raise RuntimeError('GRIPPER_COMMAND_REQUIRES_STOPPED_ROBOT')
        emit('GRIPPER_REQUEST', dict(width_mm=width, force_n=profile['gripper_force_n'],
                                    expected_status=expected, feedback_range_mm=bounds))
        device.last_step_gripper_context=None
        driver.command_gripper(width, profile['gripper_force_n'])
        deadline = clock()+10.
        # A write ACK and a pre-command idle sample do not establish opening/closing completion.
        sleep(.1)
        completed_samples = 0
        while True:
            feedback = driver.sample()
            emit('GRIPPER_FEEDBACK', feedback)
            if feedback['robot_state'] not in (1, 2) or feedback['robot_mode'] != 1:
                raise RuntimeError('ROBOT_NOT_READY_DURING_GRIPPER_COMMAND')
            if feedback['query_duration_s'] > .5:
                raise RuntimeError('FEEDBACK_TOO_OLD')
            if feedback['tcp'] != connection['tcp'] or feedback['tool'] != connection['tool']:
                raise RuntimeError('TCP_TOOL_MISMATCH')
            if feedback['drl_state'] != 3:
                raise RuntimeError('DRL_NOT_STOPPED')
            actual_width = feedback['gripper_width_mm']
            if type(actual_width) not in (int, float) or not math.isfinite(actual_width):
                raise RuntimeError('INVALID_GRIPPER_WIDTH_FEEDBACK')
            # RG2 status bits 0/1 are busy/grip. Any higher bit is a safety fault.
            if feedback['gripper_status'] not in (0, 1, 2, 3):
                raise RuntimeError('GRIPPER_SAFETY_OR_STATUS_FAULT')
            if not 0 <= actual_width <= 110:
                raise RuntimeError('INVALID_GRIPPER_WIDTH_FEEDBACK')
            empty_complete=(empty_pad and feedback['gripper_status'] in (0,2) and actual_width<=12.)
            complete = ((empty_complete or feedback['gripper_status'] == expected) and
                        stopped(feedback,stillness_policy) and
                        (empty_complete or expected == 2 or bounds[0] <= actual_width <= bounds[1]))
            completed_samples = completed_samples+1 if complete else 0
            if completed_samples >= 3:
                return feedback['gripper_status']
            if clock() >= deadline:
                raise TimeoutError('GRIPPER_COMPLETION_NOT_VERIFIED')
            sleep(.05)

    def press_down(travel, held=2):
        if profile.get('native_press') and not has_source_release_press(plan):
            from app.assembly_native_press import native_press
            if held!=2:raise ValueError('NATIVE_PRESS_REQUIRES_HELD_BLOCK')
            return native_press(driver,connection,plan,profile,travel,emit,clock=clock,sleep=sleep)
        return press(driver, connection, emit, max_travel_mm=travel,
                     force_stop_n=force, velocity=profile['descent_velocity'],
                     acceleration=profile['descent_acceleration'], required_gripper_status=held,
                     clock=clock, sleep=sleep,**motion_options)

    def paused(kind):
        result.update(status='PAUSED_'+kind, events=events)
        emit('STEP_RESULT', result)
        return result

    def ack_timeout():
        # Only the post-handover completion cue can time out into another Step.
        # Missing receiving/readiness cues still keep the current block held.
        sample = driver.stillness() if hasattr(driver, 'stillness') else driver.sample()
        guard(sample, connection, motion_force, automatic=True, force_norm_limit=motion_force,
              required_gripper_status=0)
        result.update(status='HUMAN_ACK_TIMEOUT_CONTINUE', events=events,
                      human_completion_signal_received=False,
                      completed_physical_actions_preserved=True,
                      human_assembly_observation_pending=True,
                      advance_to_next_step=True, next_step_reason='HUMAN_ASSEMBLY_ACK_TIMEOUT')
        emit('HUMAN_ACK_TIMEOUT_CONTINUE', dict(assembly_completion=False,
             current_update=False, next_action='NEXT_STEP_PICKUP', sample=sample))
        emit('STEP_RESULT', result)
        return result

    def check_recovery(sample):
        start = pose(settings.get('recovery_start_pose'), 'recovery_start_pose')
        distance, angle = pose_error(sample['posx'], start)
        bounds = release_feedback_range(settings, settings['release_width_mm'])
        width = sample['gripper_width_mm']
        if sample['gripper_status'] != 0 or not bounds[0] <= width <= bounds[1]:
            raise RuntimeError('RECOVERY_REQUIRES_VERIFIED_OPEN_GRIPPER')
        if distance > .05 or angle > .05:
            raise RuntimeError('RECOVERY_START_POSE_CHANGED')
        if not 0 < height-sample['posx'][2] <= 30.:
            raise RuntimeError('RECOVERY_REQUIRES_UPWARD_TRAVEL_AT_MOST_30MM')

    def check_grasp_recovery(sample):
        guard(sample, connection, motion_force, automatic=True, force_norm_limit=motion_force,
              required_gripper_status=0)
        bounds = settings['grasp_recovery_start_width_range_mm']
        width = sample['gripper_width_mm']
        mm, deg = pose_error(sample['posx'], settings['grasp_recovery_start_pose'])
        if (not motion_still(sample,stillness_policy) or mm > .05 or deg > .05 or
                type(width) not in (int, float) or not math.isfinite(width) or
                not bounds[0] <= width <= bounds[1]):
            raise RuntimeError('GRASP_RECOVERY_START_CHANGED')

    try:
        if phase == 'grasp-recovery':
            validate_physical(plan, profile, phase)
            if start_zone != 'supply':
                raise ValueError('GRASP_RECOVERY_REQUIRES_SUPPLY_START_ZONE')
            check_grasp_recovery(driver.sample())
            if not wait('START_GRASP_RECOVERY'):
                return paused('START')
            check_grasp_recovery(driver.sample())
            grip(settings['pickup_width_mm'], 2)
            if not wait('GRASP_CONFIRMED'):
                return paused('GRASP_CONFIRMED')
            return paused('PICKUP_COMPLETE_HOLDING')
        first = driver.sample()
        empty_start=reuse_empty_pad and phase in ('full','pickup')
        reuse_release=reuse_empty_pad and phase=='release' and release_press
        guard(first, connection, motion_force, automatic=True, force_norm_limit=None,
              required_gripper_status=(empty_pad_status if empty_start or reuse_release else 0 if phase in ('full', 'pickup', 'retreat', 'human-ack') or
                  (phase == 'release' and release_press) else 2))
        if not stopped(first,stillness_policy):
            raise RuntimeError('START_NOT_STILL')
        if phase == 'retreat':
            check_recovery(first)
        if not wait('START_'+phase.upper()):
            return paused('START')
        if phase=='human-ack':
            if not wait('HUMAN_ASSEMBLY_ACK'):
                return ack_timeout()
            result.update(human_completion_signal_received=True,status='AWAITING_BACKEND_OBSERVATION',events=events)
            emit('STEP_RESULT',result)
            return result
        if phase == 'retreat':
            sample = driver.sample()
            check_recovery(sample)
            target = sample['posx'].copy()
            target[2] = height
            emit('STEP_MOVE', dict(label='RECOVERY_VERTICAL_RETREAT', target=target, gripper_status=0))
            run(driver, connection, target, motion_force, emit, clearance_z=height, lift_only=True,
                transfer_rate=profile['descent_velocity'], descent_rate=profile['descent_velocity'],
                transfer_acceleration=profile['descent_acceleration'], set_automatic_mode=False,
                force_norm_stop_n=motion_force, required_gripper_status=0, clock=clock, sleep=sleep,**motion_options)
            result.update(status='RECOVERY_RETREAT_COMPLETE', events=events)
            emit('STEP_RESULT', result)
            return result
        if phase in ('full', 'pickup'):
            pickup = pose(settings['pickup_pose'], 'pickup_pose')
            if empty_start:
                grip(settings['release_width_mm'],0)
            elif phase == 'pickup' and 'pickup_start_open_range_mm' in settings:
                # An already-open gripper need not receive another width command.
                # Keep this admission range separate from seated-block release feedback.
                bounds = settings['pickup_start_open_range_mm']
                for _ in range(3):
                    sample = driver.sample()
                    guard(sample, connection, motion_force, automatic=True, force_norm_limit=motion_force,
                          required_gripper_status=0)
                    if (not stopped(sample,stillness_policy) or
                            not bounds[0] <= sample['gripper_width_mm'] <= bounds[1]):
                        raise RuntimeError('PICKUP_OPEN_START_NOT_VERIFIED')
                    emit('PICKUP_START_OPEN_VERIFIED', dict(sample=sample, range_mm=bounds))
                    sleep(.05)
            else:
                grip(settings['release_width_mm'], 0)
            lift(0)
            # Empty return and loaded outbound both use place -> body bypass -> supply(20,0).
            route = []
            if start_zone == 'assembly':
                # Merge only a horizontal route whose existing grasp orientation
                # already matches; other starts keep the reviewed separate turn.
                current=driver.sample()['posx']
                if (profile.get('transport_blending') and
                        pose_error(current,current[:3]+pickup[3:])[1]<=.1 and
                        math.dist(current[:2],profile['place_pose'][:2])>2*profile['transport_blending']['radius_mm']):
                    route.append(('PLACE_BOARD_EMPTY',profile['place_pose'][:2]))
                else:
                    transit('PLACE_BOARD_EMPTY', profile['place_pose'][:2], pickup[3:], 0)
            if start_zone != 'supply':
                route += [('BODY_BYPASS_EMPTY', profile['body_bypass_xy_mm']),
                          ('SUPPLY_20_0_EMPTY', profile['supply_transit_xy_mm'])]
            if profile.get('round2_supply_observation_pose') is not None:
                transits(route,pickup[3:],0)
                move('ROUND2_SUPPLY_OBSERVATION',pose(profile['round2_supply_observation_pose'],'supply_observation'),0)
                route=[]
            route.append(('PICKUP_APPROACH', pickup[:2]))
            if profile.get('round2_supply_observation_pose') is None:
                transits(route, pickup[3:], 0)
            if not wait('PICKUP_ALIGNMENT'):
                return paused('PICKUP_ALIGNMENT')
            if pickup_center is not None:
                # Capture at the stopped approach, never reuse a correction from
                # an earlier slot. Provider failures propagate through STOP.
                sample = driver.sample()
                correction = pickup_center(deepcopy(plan), deepcopy(sample))
                if not isinstance(correction, dict):
                    raise ValueError('INVALID_PICKUP_CENTER_RESULT')
                if correction.get('status') != 'VISION_GRASP_PLAN_FOR_REVIEW':
                    raise ValueError('PICKUP_CENTER_BLOCKED:'+str(correction.get('reason')))
                if correction.get('policy') != 'COORDINATE_FIRST_WITH_OPTIONAL_CENTER':
                    raise ValueError('COORDINATE_FIRST_PICKUP_POLICY_REQUIRED')
                target = pose(correction.get('candidate_tcp_mm_zyz_deg'), 'vision_pickup_pose')
                if target[2:] != pickup[2:]:
                    raise ValueError('PICKUP_CENTER_MUST_PRESERVE_Z_ORIENTATION')
                assisted = correction.get('center_assist_applied')
                if assisted is not True and target != pickup:
                    raise ValueError('PICKUP_FALLBACK_MUST_PRESERVE_TAUGHT_POSE')
                if assisted is True:
                    limit = settings.get('pickup_center_max_shift_mm')
                    if (type(limit) not in (int, float) or not math.isfinite(limit)
                            or limit <= 0 or math.dist(target[:2], pickup[:2]) > limit):
                        raise ValueError('PICKUP_CENTER_OUTSIDE_REVIEWED_BOUND')
                    # Correct laterally at clearance; lower vertically afterward.
                    transit('PICKUP_CENTER_ALIGN', target[:2], pickup[3:], 0)
                emit('PICKUP_CENTER_DECISION', correction)
                pickup = target
            if profile.get('round2_supply_observation_pose') is not None:
                transit('PICKUP_APPROACH',pickup[:2],pickup[3:],0)
            move('PICKUP_LOWER', pickup, 0,
                 speed=profile.get('pickup_descent_velocity',profile['descent_velocity']),
                 acceleration=profile.get('pickup_descent_acceleration',profile['descent_acceleration']))
            grip(settings['pickup_width_mm'], 2)
            if not wait('GRASP_CONFIRMED'):
                return paused('GRASP_CONFIRMED')
            start_zone = 'supply'
            # Separate the first real slot grasp from loaded transport and seating.
            if phase == 'pickup':
                return paused('PICKUP_COMPLETE_HOLDING')
        if phase in ('full', 'approach', 'assemble-held'):
            turn = settings.get('turn_base_z_deg')
            if turn is not None:
                # Capture once: transport preserves this grasp; yaw is applied above the target.
                rotation_start = driver.sample()['posx']
                transport_orientation = rotation_start[3:]
                target_orientation = rotate_base_z_pose(rotation_start, turn)[3:]
                if 'assembly_tcp_zyz_deg' in settings:
                    target_orientation=assembly_target_pose(settings)[3:]
                emit('TURN_REFERENCE', dict(start_pose=rotation_start, turn_base_z_deg=turn,
                                          reference='CURRENT_SESSION_GRASP_BASE_Z',
                                          xy_grasp_offset_compensation_measured=False))
            else:
                transport_orientation = target_orientation = reference[3:]
            lift()
            route = []
            if start_zone == 'supply':
                route += [('SUPPLY_20_0', profile['supply_transit_xy_mm']),
                          ('BODY_BYPASS', profile['body_bypass_xy_mm'])]
            if start_zone in ('supply', 'place'):
                route.append(('ROUND2_ASSEMBLY_OBSERVATION',reference[:2]) if (profile.get('round2') or has_source_release_press(plan)) and plan['mode']!='HUMAN_ASSEMBLY' else ('PLACE_BOARD', profile['place_pose'][:2]))
            merged_human_target=(bool(human_config) and bool(profile.get('transport_blending')) and
                start_zone=='supply' and
                math.dist(profile['place_pose'][:2],reference[:2])>2*profile['transport_blending']['radius_mm'] and
                pose_error([0.,0.,0.,*transport_orientation],[0.,0.,0.,*target_orientation])[1]<=.1)
            if merged_human_target:
                route.append(('TARGET_HIGH_HUMAN_WAIT',reference[:2]))
            transits(route, transport_orientation)
            if human_config:
                if not merged_human_target:
                    transit('TARGET_HIGH_HUMAN_WAIT',reference[:2],target_orientation)
                if plan['mode'] != 'HUMAN_ASSEMBLY':
                    ready='HUMAN_READY' if plan['assistance_kind']=='HOLD' else 'HUMAN_HOLD_READY'
                    if not wait(ready):
                        return paused(ready)
            if plan['mode'] == 'HUMAN_ASSEMBLY':
                if not human_config:
                    destination = pose(profile['place_pose'], 'place_pose')
                    destination[2] += profile['approach_offset_mm']
                    move('TRAY_APPROACH_20MM', destination)
            else:
                if turn is not None:
                    transit('TARGET_HIGH_BEFORE_TURN', reference[:2], transport_orientation)
                    transit('TURN_AT_TARGET_CLEARANCE', reference[:2], target_orientation)
                target = [*reference[:3], *target_orientation]
                target[2] += profile['approach_offset_mm']
                move('TARGET_APPROACH_20MM', target)
            if phase == 'approach':
                return paused('APPROACH_REACHED')
        if phase in ('full', 'contact', 'assemble-held', 'human-wait'):
            if plan['mode'] == 'HUMAN_ASSEMBLY':
                if human_config:
                    if not wait('HUMAN_ASSEMBLY_RECEIVE'):
                        return paused('HUMAN_ASSEMBLY_RECEIVE')
                    try:
                        grip(human_config['handover_width_mm'],0,human_config['handover_feedback_range_mm'])
                    except TimeoutError as error:
                        if str(error)!='HUMAN_RECEIVING_CUE_REACQUIRE_TIMED_OUT':raise
                        driver.human_receive_monitor=None
                        driver.session.close_request()
                        result.update(recoverable_interruption=True,interruption_scope='HUMAN_RECEIVE_STAGE',
                            resume_phase='human-wait',resume_requires_fresh_session=True,
                            completed_physical_actions_preserved=True,gripper_open_command_sent=False)
                        emit('HUMAN_RECEIVE_STAGE_PAUSED',dict(reason='RECEIVING_SIGNAL_NOT_REACQUIRED',
                            recoverable=True,robot_commands_retried=False,assembly_completion=False))
                        return paused('HUMAN_ASSEMBLY_RECEIVE')
                    if not wait('HUMAN_ASSEMBLY_ACK'):
                        return ack_timeout()
                    result.update(human_completion_signal_received=True,status='AWAITING_BACKEND_OBSERVATION',events=events)
                    emit('STEP_RESULT',result)
                    return result
                gap = driver.sample()['posx'][2]-profile['place_pose'][2]
                if gap > .05:
                    contact = press_down(gap)
                    result['tray_contact_status'] = contact['status']
                if not wait('TRAY_RELEASE'):
                    return paused('TRAY_RELEASE')
                grip(settings['release_width_mm'], 0)
                lift(0)
                if not wait('HUMAN_ASSEMBLY_ACK'):
                    return paused('HUMAN_ASSEMBLY_ACK')
            else:
                if not wait('ALIGNMENT_AND_PARALLEL'):
                    return paused('ALIGNMENT')
                if assembly_alignment is not None:
                    from app.round2_alignment import automatic_surface_alignment
                    aligned=automatic_surface_alignment(driver,plan,profile,assembly_alignment,move,emit)
                    if aligned['status']!='SURFACE_ALIGNMENT_CONVERGED':
                        return paused('SURFACE_ALIGNMENT_MEASUREMENT')
                    correction=aligned['candidate']
                    # Registered producer supplies landing/press Z for this aligned grasp.
                    previous_reference=reference.copy()
                    reference=pose(correction['landing_pose'],'aligned_landing')
                    if has_source_release_press(plan):
                        from app.round2_operator_teaching import retarget_pose
                        release=pose(settings['release_pose'],'release_pose')
                        corrected_release=retarget_pose(previous_reference,release,reference)
                        # This is a held-TCP compensation. Preserve the explicit
                        # Base air-release offset; the empty pad target stays on
                        # the original measured block, independent of this grasp.
                        corrected_release[:3]=[release[i]+reference[i]-previous_reference[i] for i in range(3)]
                        settings.update(reference_pose=reference.copy(),release_pose=corrected_release,
                            assembly_tcp_zyz_deg=reference[3:])
                    else:
                        settings.update(reference_pose=reference.copy(),release_pose=reference.copy(),
                            assembly_tcp_zyz_deg=reference[3:])
                        settings['press_start_pose']=[*reference[:2],correction['pad_contact_z_mm']+profile['near_contact_offset_mm'],*reference[3:]]
                        settings['press_approach_pose']=[*reference[:2],correction['pad_contact_z_mm']+profile['approach_offset_mm'],*reference[3:]]
                if not human_config and plan['assistance_kind'] in ('HOLD', 'PRESS_AND_HOLD'):
                    ready = 'HUMAN_READY' if plan['assistance_kind'] == 'HOLD' else 'HUMAN_HOLD_READY'
                    if not wait(ready):
                        return paused(ready)
                if human_release_press:
                    # A's human PRESS still acts on its original target. Release
                    # from D's taught landing; do not add a held insertion or pad press.
                    move('RELEASE_POSITION',settings['release_pose'],speed=profile['descent_velocity'])
                    if not wait('SUPPORT_AND_RELEASE_FOR_HUMAN_PRESS'):
                        return paused('HUMAN_SUPPORT')
                    grip(settings['release_width_mm'],0)
                    lift(0)
                    if not wait('HUMAN_PRESS_AND_HOLD_ACK'):
                        return paused('HUMAN_PRESS_AND_HOLD_ACK')
                    result.update(contact_status='HUMAN_REPORTED',human_completion_signal_received=True,
                                  robot_press_executed=False)
                elif plan['assistance_kind'] == 'PRESS_AND_HOLD':
                    # Place/release on verified support, retreat, then let humans press.
                    # A human PRESS has no numeric force; never issue a second robot press.
                    human_pose = reference.copy()
                    human_pose[2] += profile['near_contact_offset_mm']
                    gap = driver.sample()['posx'][2]-human_pose[2]
                    if gap > .05:
                        press_down(gap)
                    if not wait('SUPPORT_AND_RELEASE_FOR_HUMAN_PRESS'):
                        return paused('HUMAN_SUPPORT')
                    grip(settings['release_width_mm'], 0)
                    lift(0)
                    if not wait('HUMAN_PRESS_AND_HOLD_ACK'):
                        return paused('HUMAN_PRESS_AND_HOLD_ACK')
                    if human_config:
                        result['human_completion_signal_received'] = True
                    result['contact_status'] = 'HUMAN_REPORTED'
                elif release_press:
                    move('RELEASE_POSITION', settings['release_pose'], speed=profile['descent_velocity'])
                    if not wait('RELEASE_FOR_TOP_PRESS'):
                        return paused('RELEASE_FOR_TOP_PRESS')
                    grip(settings['release_width_mm'], 0)
                    if plan.get('raised_human_step') or plan.get('round2_vertical_top_press'):
                        released_pose=driver.sample()['posx'].copy()
                        empty_high=released_pose.copy()
                        empty_high[2]=max(height,settings['press_approach_pose'][2])
                        move('RAISED_EMPTY_VERTICAL_RETREAT',empty_high,0)
                        empty_pad_status=grip(settings['press_width_mm'],0,empty_pad=bool(profile.get('round2')))
                        replay_reference=getattr(device,'use_press_tool_reference',None)
                        if has_source_release_press(plan) and driver.mode=='MOCK' and callable(replay_reference):
                            contact_reference=settings['press_start_pose'].copy()
                            contact_reference[2]=settings['press_start_pose'][2]-profile['near_contact_offset_mm']
                            replay_reference(contact_reference)
                        if profile.get('round2'):
                            device.last_step_gripper_context=dict(state='EMPTY_PAD_CLOSED',gripper_status=empty_pad_status)
                            result['final_gripper_context']=deepcopy(device.last_step_gripper_context)
                            emit('EMPTY_PAD_CLOSED_CONTEXT',result['final_gripper_context'])
                        if has_source_release_press(plan):
                            press_start=pose(settings['press_start_pose'],'press_start_pose')
                            # Reposition only after the open-gripper vertical
                            # retreat, then descend at the taught pad XY/attitude.
                            move('PRESS_TOOL_APPROACH',[*press_start[:2],empty_high[2],*press_start[3:]],empty_pad_status)
                        else:
                            press_start=released_pose.copy()
                            press_start[2]=settings['press_start_pose'][2]
                        if press_start[2]>=empty_high[2]:
                            raise ValueError('TOP_PRESS_REQUIRES_DOWNWARD_START')
                        emit('CENTERED_VERTICAL_PRESS',dict(center_xy=press_start[:2],
                            force_stop_n=force,force_control_target_n=None))
                        move('PRESS_TOOL_LOWER',press_start,empty_pad_status,profile['descent_velocity'])
                    else:
                        move('PRESS_TOOL_APPROACH', settings['press_approach_pose'], 0)
                        grip(settings['press_width_mm'], 0)
                        move('PRESS_TOOL_LOWER', settings['press_start_pose'], 0, profile['descent_velocity'])
                    contact = press_down(profile['max_press_travel_mm'], empty_pad_status)
                    result['contact_status'] = contact['status']
                    if has_source_release_press(plan):result['robot_press_executed']=True
                else:
                    # Grasp height changes the contact Z. Monitor force continuously;
                    # preserve the old lowest endpoint, never extend it on a resumed attempt.
                    lowest_z = reference[2]+profile['near_contact_offset_mm']-profile['max_press_travel_mm']
                    travel = driver.sample()['posx'][2]-lowest_z
                    emit('CONTACT_ENVELOPE', dict(lowest_tcp_z_mm=lowest_z,
                                                remaining_travel_mm=travel, force_stop_n=force))
                    if travel <= .05:
                        return paused('CONTACT_TRAVEL_EXHAUSTED')
                    contact = press_down(travel)
                    result['contact_status'] = contact['status']
                if result['contact_status'] == 'MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD':
                    return paused('MAX_TRAVEL_NO_FORCE')
                if not wait('FULL_SEATING'):
                    return paused('FULL_SEATING')
                automatic=getattr(driver,'automatic_confirmation',False)
                result['operator_seating_confirmed'] = not automatic
                if automatic:result['automatic_contact_release_policy_passed'] = True
                # Contact trials end holding; release is a separate operator-approved phase.
                if phase == 'contact':
                    if profile.get('round2') and release_press and not human_release_press:
                        return paused('TOP_PRESS_RETREAT_PENDING')
                    return paused('HUMAN_SEATED_OBSERVATION_PENDING' if human_release_press or plan['assistance_kind'] == 'PRESS_AND_HOLD'
                                  else 'SEATED_RELEASE_PENDING')
        if phase == 'release' or (phase in ('full', 'assemble-held') and plan['mode'] != 'HUMAN_ASSEMBLY'
                                and plan['assistance_kind'] != 'PRESS_AND_HOLD' and not human_release_press):
            if not release_press:
                if not wait('RELEASE'):
                    return paused('RELEASE')
                grip(settings['release_width_mm'], 0)
            lift(empty_pad_status if release_press else 0)
        if profile.get('round2') and getattr(device,'last_step_gripper_context',None):
            result['final_gripper_context']=deepcopy(device.last_step_gripper_context)
        result.update(status='AWAITING_BACKEND_OBSERVATION', events=events)
        emit('STEP_RESULT', result)
        return result
    except BaseException as error:
        device.last_step_gripper_context=None
        try:
            driver.stop()
        except Exception as stop_error:
            emit('STEP_STOP_FAILED', dict(error=str(stop_error)))
        emit('STEP_ERROR', dict(error=str(error), current_update=False, automatic_retry=False))
        raise


class StepReplayDriver:
    """장치·네트워크·물리 lock을 사용하지 않는 결정론적 workflow 대역. 물리 시뮬레이터가 아니다."""
    mode = 'MOCK'

    def __init__(self, reference, *, reaction_force_n=35.,grasp_width_mm=None,stop_force_z_n=25.):
        self.reaction_force_n=reaction_force_n
        if stop_force_z_n is not None and (type(stop_force_z_n) not in (int,float) or not math.isfinite(stop_force_z_n) or stop_force_z_n<0):
            raise ValueError('FINITE_NONNEGATIVE_REPLAY_STOP_FORCE_REQUIRED')
        self.stop_force_z_n=stop_force_z_n
        self.grasp_widths=(35.,40.) if grasp_width_mm is None else (grasp_width_mm,)
        self.reference = reference.copy()
        self.value = dict(posx=[418., -181., 112., *reference[3:]], velx=[0.]*6,
                          motion_status=0, query_duration_s=0., tcp='GripperDA_v4', tool='ToolWeight0',
                          gripper_status=0, gripper_width_mm=62., robot_state=1, robot_mode=1,
                          drl_state=3, wrench=[0., 0., 5., 0., 0., 0.])
        self.moves, self.grips, self.stops = [], [], 0
        self.blends = []

    def sample(self):
        return deepcopy(self.value)

    def motion_feedback(self):
        return self.sample()

    def check_pose(self, target, **kwargs):
        return target.copy()

    def use_press_tool_reference(self,reference):
        """Explicit replay geometry for the empty tool, not measured contact."""
        self.reference=reference.copy()

    def check_contact_services(self,**kwargs):return []

    def enable_compliance(self,stiffness,transition):self.native_compliance=True

    def set_downward_force(self,force,transition,*,relative=True):
        self.native_force_requests=getattr(self,'native_force_requests',[])+[dict(force_n=force,relative=relative)]
        self.value['posx'][2]=self.reference[2]+.2
        self.value['wrench'][2]=force

    def release_force(self,transition):self.value['wrench'][2]=5.

    def release_compliance(self):self.native_compliance=False

    def move_line_async(self, target, velocity, acceleration):
        self.moves.append(target.copy())
        self.value['wrench'][2] = 5.
        current = self.value['posx']
        if (math.dist(target[:2], self.reference[:2]) < .01 and
                target[2] < self.reference[2]+.2 <= current[2]):
            self.value['posx'] = [*target[:2], self.reference[2]+.2, *target[3:]]
            self.value['wrench'][2] = self.reaction_force_n
        else:
            self.value['posx'] = target.copy()

    def command_gripper(self, width, force):
        self.grips.append((width, force))
        self.value.update(gripper_status=2 if width in self.grasp_widths else 0,
                          gripper_width_mm=40.6 if width==35. else width)
        self.value['wrench'][2] = 5.

    def move_blending_async(self, targets, radius, velocity, acceleration):
        self.blends.append(deepcopy(dict(targets=targets, radius=radius, velocity=velocity, acceleration=acceleration)))
        self.moves.extend(deepcopy(targets))
        self.value['posx'] = targets[-1].copy()

    def stop(self):
        self.stops += 1
        # The default preserves the legacy springback fixture; None leaves the
        # stop load unchanged. These selectable outcomes are not contact physics.
        if self.stop_force_z_n is not None:self.value['wrench'][2]=self.stop_force_z_n


def replay_profile(profile, steps):
    """Fixture numeric commands are exclusively MOCK. They are never real teaching values."""
    mock = deepcopy(profile)
    mock['profile_id'] = 'MOCK_ONLY_NEVER_PHYSICAL_TEACHING'
    for step in steps:
        s = mock['steps'][step['case_id']+'/'+step['step_id']]
        if s['reference_pose'] is None:
            s['reference_pose'] = [392., 5., 16., 75., -177., 75.]
        s['pickup_pose'] = s['pickup_pose'] or [-323., 58., 50., 63., -180., 64.]
        if s.get('pickup_width_mm') is None: s['pickup_width_mm'] = 40.
        if s.get('release_width_mm') is None: s['release_width_mm'] = 62.
        s['release_pose'] = s['reference_pose'].copy()
        s['release_pose'][2] += 1.
        s['press_approach_pose'] = s['reference_pose'].copy()
        s['press_approach_pose'][2] += 20.1
        s['press_start_pose'] = s['reference_pose'].copy()
        s['press_start_pose'][2] += 1.
        s['press_width_mm'] = 0.
    return mock
