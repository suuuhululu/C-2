"""D의 Step 실행. 기존 이동/파지/체결 함수를 호출하며 B의 Current를 쓰지 않는다."""
from copy import deepcopy
import math
import time
import threading
from uuid import uuid4

from app.assembly_motion import pose_error
from app.assembly_blend_trial import run_blend
from app.assembly_step_bridge import build_plan, pose, release_feedback_range
from app.assembly_step_runner import rotate_base_z_pose
from app.control_driver import ControlledDriver
from app.control_session import ControlSession, validate_execution
from scripts.assembly_position_trial import run, guard
from scripts.assembly_press_trial import press


class StepRuntime:
    def __init__(self, raw, connection, record, *, clock=time.monotonic,
                 sleep=time.sleep, wall=time.time):
        self.raw, self.connection, self.record = raw, connection, record
        self.clock, self.sleep, self.wall = clock, sleep, wall
        self.session = self.driver = self.plan = None
        self.cursor = 0
        self.operations = []
        self.pending = None
        self.state = 'IDLE'
        self.signal = None
        self.signal_seq = -1
        self.request = None
        self.signal_lock = threading.Lock()
        self.contact = self.stopped_sample = None
        self.contact_started = False
        self.used_executions = set()
        self.inspection_attempt = 0

    def emit(self, event, data):
        # STOP evidence must still be emitted after the execution is cancelled.
        self.record(event, dict(data, execution_id=self.session.value['execution_id'] if self.session else None,
                               plan_id=self.plan['plan_id'] if self.plan else None,
                               step_id=self.plan['step_id'] if self.plan else None,
                               current_revision=self.plan['current_revision'] if self.plan else None))

    def start(self, step, profile, value, *, resume=False, start_zone='assembly'):
        if (resume and self.state != 'STOPPED' and not self.can_resume()) or (not resume and self.state not in ('IDLE', 'WAIT_C')):
            raise RuntimeError('STEP_BUSY_OR_INSPECTION_PENDING')
        plan = build_plan(step, profile)
        trial = value.get('no_vision_trial', False)
        if type(trial) is not bool:
            raise ValueError('EXPLICIT_NO_VISION_TRIAL_BOOLEAN_REQUIRED')
        if trial and (plan['mode'] != 'ROBOT_GRIP' or plan['assistance_kind'] != 'NONE'
                      or plan['current_revision'] is not None):
            raise ValueError('NO_VISION_TRIAL_REQUIRES_UNASSISTED_ROBOT_AND_NO_B_REVISION')
        if self.state == 'WAIT_C' and plan['plan_id'] == self.plan['plan_id']:
            raise RuntimeError('WAIT_FOR_C_APPROVED_NEW_PLAN')
        block = plan['block']
        permitted = ((block['color'] in ('yellow', 'blue') and block['brick_type'] in ('2x2x1', '2x3x1'))
                     or (block['color'] == 'red' and block['brick_type'] == '1x2x1'))
        if not permitted or (block['brick_type'] == '2x2x1' and block['orientation_deg'] != 0):
            raise ValueError('UNSUPPORTED_FINAL_MVP_BLOCK')
        if plan['mode'] not in ('ROBOT_GRIP', 'HUMAN_ASSEMBLY') or plan['assistance_kind'] not in ('NONE', 'HOLD', 'PRESS_AND_HOLD', 'MANUAL_ASSEMBLY'):
            raise ValueError('UNSUPPORTED_METHOD')
        if start_zone not in ('assembly', 'place', 'supply'):
            raise ValueError('INVALID_START_ZONE')
        for key in ('pickup_pose', 'reference_pose'):
            pose(plan['settings'][key], key)
        pose(profile['place_pose'], 'place_pose')
        for key in ('pickup_width_mm', 'release_width_mm', 'pickup_open_width_mm'):
            if key == 'pickup_open_width_mm' and key not in plan['settings']:
                continue
            width = plan['settings'][key]
            if type(width) not in (int, float) or not math.isfinite(width) or not 0 <= width <= 110:
                raise ValueError('STEP_GRIPPER_WIDTH_REQUIRED:'+key)
        if plan['settings']['pickup_width_mm'] >= plan['settings']['release_width_mm']:
            raise ValueError('OPEN_WIDTH_MUST_EXCEED_CLOSE_WIDTH')
        if ('pickup_open_width_mm' in plan['settings'] and
                plan['settings']['pickup_open_width_mm'] <= plan['settings']['pickup_width_mm']):
            raise ValueError('PICKUP_OPEN_WIDTH_MUST_EXCEED_CLOSE_WIDTH')
        if value.get('automatic_stage_checks') or plan['settings'].get('human_step_gestures'):
            raise ValueError('USE_INTEGRATION_SIGNALS_NOT_LOCAL_TRIAL_POLICY')
        if value['execution_id'] in self.used_executions:
            raise ValueError('EXECUTION_ALREADY_USED')
        if self.raw.mode == 'REAL':
            validate_execution(plan, profile, value, 'full')
            if profile.get('native_press'):
                from scripts.onsite_slot2_force_trial import require_drcf2_runtime
                require_drcf2_runtime()
                self.raw.check_contact_services(native_force=True)
        if self.raw.mode == 'REAL' and (value.get('provenance') != 'LIVE_D_RUNTIME' or value['d_runtime'].get('execution_id') != value['execution_id']):
            raise ValueError('MATCHING_LIVE_D_EXECUTION_REQUIRED')
        session = ControlSession(value, plan, self.emit, clock=self.clock, wall=self.wall)
        driver = ControlledDriver(self.raw, session, self.connection, clock=self.clock, sleep=self.sleep)
        if resume:
            initial_open = self.state == 'RECOVERY_REQUIRED' and self.cursor == 0 and self.operations[0][1][0] == 'PREPARE_OPEN'
            waiting_contact = self.pending == 'contact' and self.can_resume()
            if plan != self.plan or profile != self.profile or (self.pending in ('grip', 'contact', 'blend') and not (initial_open or waiting_contact)) or self.stopped_sample is None:
                raise RuntimeError('RESUME_REQUIRES_UNCHANGED_STEP_AND_KNOWN_OPERATION')
            sample = driver.stillness()
            mm, deg = pose_error(sample['posx'], self.stopped_sample['posx'])
            if (mm > 1 or deg > 1 or sample['gripper_status'] != self.stopped_sample['gripper_status']
                    or abs(sample['gripper_width_mm']-self.stopped_sample['gripper_width_mm']) > 1):
                raise RuntimeError('RESUME_STATE_CHANGED_REQUIRES_RECOVERY')
            if value.get('resume_current_revision') != plan['current_revision']:
                raise RuntimeError('RESUME_REQUIRES_LATEST_CURRENT_CHECK')
            if self.cursor < len(self.operations) and self.operations[self.cursor][0] == 'tray':
                # STOP으로 닫힌 수신 관측은 재사용하지 않는다. 하강 전 새 관측/준비를 요청한다.
                self.operations.insert(self.cursor, ('receive', None))
        else:
            sample = driver.stillness()
            guard(sample, self.connection, profile['force_stop_n'], automatic=True, required_gripper_status=0)
            if self.raw.mode == 'REAL' and trial:
                expected = pose(value.get('planned_start_pose'), 'planned_start_pose')
                mm, deg = pose_error(sample['posx'], expected)
                if mm > value['stillness']['position_mm'] or deg > value['stillness']['orientation_deg']:
                    raise RuntimeError('START_STATE_CHANGED_RECALCULATION_REQUIRED')
            self.operations = self.make_operations(plan, profile, start_zone)
            self.cursor = 0
            self.contact = None
            self.contact_started = False
            self.inspection_attempt = 0
        session.claim_execution()
        self.used_executions.add(value['execution_id'])
        self.session, self.driver, self.plan, self.profile = session, driver, plan, deepcopy(profile)
        self.no_vision_trial = trial
        driver.automatic_confirmation = True
        self.signal, self.signal_seq, self.request = None, -1, None
        self.pending, self.state = None, 'RUNNING'
        self.emit('EXECUTION_STARTED', dict(resume=resume, cursor=self.cursor, physical_verified=False))

    def can_resume(self):
        if self.stopped_sample is None:
            return False
        if self.pending == 'contact' and not self.contact_started and self.stopped_sample['gripper_status'] == 2:
            s = self.plan['settings']
            target = [*s['reference_pose'][:3], *rotate_base_z_pose(s['pickup_pose'],s.get('turn_base_z_deg',0))[3:]]
            target[2] += self.profile['approach_offset_mm']
            mm,deg = pose_error(self.stopped_sample['posx'],target)
            return self.state in ('STOPPED','RECOVERY_REQUIRED') and mm <= 1 and deg <= 1
        if self.state == 'STOPPED':
            return self.pending not in ('grip', 'contact', 'blend')
        # Opening an empty gripper before any arm motion can be reissued explicitly.
        # Pickup close/contact/release must never be replayed when their outcome is unknown.
        return (self.state == 'RECOVERY_REQUIRED' and self.cursor == 0 and self.pending == 'grip'
                and bool(self.operations) and self.operations[0][1][0] == 'PREPARE_OPEN'
                and self.stopped_sample['gripper_status'] == 0)

    def make_operations(self, plan, profile, zone):
        s = plan['settings']; pickup = s['pickup_pose']; reference = s['reference_pose']
        height = max(profile['clearance_z_mm'], reference[2]+profile['approach_offset_mm'],
                     pickup[2]+profile['approach_offset_mm'], profile['place_pose'][2]+profile['approach_offset_mm'])
        # Pickup clearance and post-contact release are separate D commands.
        opening = s.get('pickup_open_width_mm', s['release_width_mm'])
        ops = [('grip', ('PREPARE_OPEN', opening, 0)), ('lift', (height, 0))]
        route = []
        if zone == 'assembly':
            # Establish the pickup orientation/height before horizontal blending.
            ops.append(('move', ('PLACE_EMPTY', [*profile['place_pose'][:2], height, *pickup[3:]], 0, False)))
        if zone != 'supply': route += [('BODY_EMPTY', profile['body_bypass_xy_mm']), ('SUPPLY_EMPTY', profile['supply_transit_xy_mm'])]
        route.append(('PICKUP_HIGH', pickup[:2]))
        if profile.get('transport_blending') and len(route) >= 2:
            ops.append(('blend', ([[*xy, height, *pickup[3:]] for _,xy in route], 0)))
        else:
            ops += [('move', (label, [*xy, height, *pickup[3:]], 0, False)) for label, xy in route]
        ops += [('move', ('PICKUP_LOWER', pickup, 0, True)), ('grip', ('PICKUP_CLOSE', s['pickup_width_mm'], 2)),
                ('lift', (height, 2))]
        loaded = [('SUPPLY_LOADED', profile['supply_transit_xy_mm']), ('BODY_LOADED', profile['body_bypass_xy_mm']), ('PLACE_LOADED', profile['place_pose'][:2])]
        if profile.get('transport_blending'):
            ops.append(('blend', ([[*xy, height, *pickup[3:]] for _,xy in loaded], 2)))
        else:
            for label, xy in loaded:
                ops.append(('move', (label, [*xy, height, *pickup[3:]], 2, False)))
        if plan['mode'] == 'HUMAN_ASSEMBLY':
            tray = profile['place_pose']; high = [*tray[:2], height, *tray[3:]]
            ops += [('move', ('TRAY_HIGH', high, 2, False)), ('receive', None), ('tray', tray), ('ack', None)]
        else:
            orientation = rotate_base_z_pose(pickup, s.get('turn_base_z_deg', 0))[3:]
            target = [*reference[:3], *orientation]; target[2] += profile['approach_offset_mm']
            ops.append(('move', ('TARGET_HIGH', [*target[:2], height, *orientation], 2, False)))
            if 'pre_contact_slow_distance_mm' in profile:
                distance = profile['pre_contact_slow_distance_mm']
                if type(distance) not in (int, float) or not math.isfinite(distance) or distance <= 0:
                    raise ValueError('POSITIVE_SLOW_APPROACH_DISTANCE_REQUIRED')
                if height > target[2]+distance:
                    ops.append(('move', ('ASSEMBLY_APPROACH', [*target[:2], target[2]+distance, *orientation], 2, False)))
            ops.append(('move', ('PRE_CONTACT', target, 2, True)))
            assisted = plan['assistance_kind'] in ('HOLD', 'PRESS_AND_HOLD')
            if assisted: ops.append(('help', None))
            if plan['assistance_kind'] == 'PRESS_AND_HOLD':
                # 기존 D 계약: 사람이 누를 수 있도록 near-contact에서 놓고 후퇴한다.
                # 이 방식에 Robot force press를 덧붙이지 않는다.
                near = [*reference[:3], *orientation]
                near[2] += profile['near_contact_offset_mm']
                ops += [('move', ('SUPPORTED_NEAR_CONTACT', near, 2, True)),
                        ('grip', ('SUPPORTED_RELEASE', s['release_width_mm'], 0)),
                        ('lift', (height, 0)), ('ack', None)]
            else:
                ops += [('contact', None), ('grip', ('SEATED_RELEASE', s['release_width_mm'], 0)), ('lift', (height, 0))]
            if assisted: ops.append(('help_release', None))
        return ops

    def accept_signal(self, value):
        with self.signal_lock:
            if self.state != 'RUNNING' or self.request is None:
                raise RuntimeError('NO_ACTIVE_SIGNAL_REQUEST')
            if any(value.get(k) != self.request[k] for k in ('request_id', 'execution_id', 'plan_id', 'step_id', 'current_revision')):
                raise ValueError('STALE_SIGNAL')
            seq = value.get('sequence')
            if type(seq) is not int or seq <= self.signal_seq:
                raise ValueError('OLD_SIGNAL_SEQUENCE')
            if value.get('source') not in ('SENSOR', 'HMI', 'FAKE') or (self.raw.mode == 'REAL' and value['source'] == 'FAKE'):
                raise ValueError('INVALID_SIGNAL_SOURCE')
            if self.request['kind'] == 'RECEIVE':
                if value['source'] == 'HMI' or type(value.get('hand_present')) is not bool or type(value.get('receiving_ready')) is not bool:
                    raise ValueError('HAND_PRESENCE_SENSOR_REQUIRED')
                if value['receiving_ready'] and (not value['hand_present'] or value.get('verified') is not True):
                    raise ValueError('RECEIVING_READINESS_NOT_VERIFIED')
            elif type(value.get('ready')) is not bool or (value['ready'] and value.get('verified') is not True):
                raise ValueError('READINESS_NOT_VERIFIED')
            observed = value.get('observed_monotonic_s', self.clock() if self.raw.mode != 'REAL' else None)
            if (type(observed) not in (int, float) or not math.isfinite(observed) or
                    not 0 <= self.clock()-observed <= self.session.value['frame_max_age_s']):
                raise ValueError('STALE_SIGNAL_OBSERVATION')
            self.signal_seq, self.signal = seq, (deepcopy(value), observed)

    def wait_signal(self, kind, timeout=None, *, keep=False):
        self.driver.own('WAIT')
        with self.signal_lock:
            self.request = dict(request_id=str(uuid4()), kind=kind, execution_id=self.session.value['execution_id'],
                                **{k:self.plan[k] for k in ('plan_id', 'step_id', 'current_revision')})
            self.signal = None
        self.emit('SIGNAL_REQUEST', dict(self.request, timeout_s=timeout))
        begin = self.clock()
        retaining = False
        try:
            while True:
                self.session.check()
                self.driver.stillness()
                with self.signal_lock:
                    row = self.signal
                fresh = row is not None and self.clock()-row[1] <= self.session.value['frame_max_age_s']
                # Alignment is a one-time operator answer, accepted while fresh.
                # A subsequent stop window must not age that answer out before
                # it can be consumed. Continuous hand-presence cues stay fresh-only.
                operator_answer = (kind == 'ALIGNMENT_READY' and row is not None and
                    (row[0]['source'] == 'HMI' or
                     row[0].get('confirmation_kind') == 'OPERATOR_GESTURE_NOT_ALIGNMENT_MEASUREMENT'))
                if kind == 'RECEIVE':
                    if fresh and row[0]['hand_present'] and row[0]['receiving_ready']:
                        retaining = keep
                        return True
                    if timeout is not None and self.clock()-begin >= timeout and fresh and not row[0]['hand_present']:
                        retaining = keep
                        return False
                    # Missing or stale observations never prove the lowering zone is clear.
                elif (fresh or operator_answer) and row[0]['ready']:
                    retaining = keep
                    return True
                elif timeout is not None and self.clock()-begin >= timeout:
                    return False
                self.sleep(.05)
        finally:
            if not retaining: self.close_signal_request()

    def close_signal_request(self):
        with self.signal_lock:
            request = self.request
            self.request, self.signal = None, None
        if request: self.emit('SIGNAL_REQUEST_CLOSED', dict(request_id=request['request_id']))

    def check_receive_signal(self, *, ready):
        self.session.check()
        with self.signal_lock:
            row = self.signal
        if row is None or self.clock()-row[1] > self.session.value['frame_max_age_s']:
            raise RuntimeError('RECEIVE_OBSERVATION_STALE')
        if ready and not (row[0]['hand_present'] and row[0]['receiving_ready']):
            raise RuntimeError('HANDOVER_READINESS_LOST')
        if not ready and row[0]['hand_present']:
            raise RuntimeError('HAND_PRESENT_BEFORE_LOWER')

    def move(self, label, target, held, slow=False):
        self.driver.own('MOTION')
        current = self.driver.sample()['posx']; p = self.profile
        descent = p.get('pickup_descent_velocity', p['descent_velocity']) if label == 'PICKUP_LOWER' else p['descent_velocity']
        descent_acc = p.get('pickup_descent_acceleration', p['descent_acceleration']) if label == 'PICKUP_LOWER' else p['descent_acceleration']
        if label == 'ASSEMBLY_APPROACH':
            descent, descent_acc = p['assembly_approach_velocity'], p['assembly_approach_acceleration']
        self.emit('MOVE_STARTED', dict(label=label, target=target))
        def record(event, data):
            if label == 'TRAY_LOWER' and event == 'MOVE_REQUEST' and data['segment'] == 'DESCENT':
                self.check_receive_signal(ready=False)
            self.emit(event, data)
        run(self.driver, self.connection, target, p['force_stop_n'], record,
            clearance_z=max(current[2], target[2]), transfer_only=target[2]>=current[2],
            transfer_rate=descent if slow else p['transfer_velocity'],
            descent_rate=descent,
            transfer_acceleration=descent_acc if slow else p['transfer_acceleration'],
            descent_acceleration=descent_acc,
            set_automatic_mode=False, force_norm_stop_n=p['force_stop_n'], required_gripper_status=held,
            clock=self.clock, sleep=self.sleep)
        sample = self.driver.stillness()
        mm, deg = pose_error(sample['posx'], target)
        if mm > 1 or deg > 1: raise RuntimeError('TARGET_NOT_REACHED')
        self.emit('MOVE_SUCCEEDED', dict(label=label, sample=sample, actual_stop_verified=True))

    def grip(self, label, width, status, *, precondition=None):
        if label == 'SEATED_RELEASE':
            current = self.driver.stillness()
            if not self.contact or max(pose_error(current['posx'], self.contact['final_sample']['posx'])) > 1:
                raise RuntimeError('CONTACT_POSE_CHANGED')
            # The user allows up to 2mm of target XY variation from the grasp/contact.
            if math.dist(current['posx'][:2], self.plan['settings']['reference_pose'][:2]) > 2:
                raise RuntimeError('CONTACT_TARGET_DRIFT')
        self.driver.own('GRIPPER')
        self.emit('GRIP_STARTED', dict(label=label))
        self.driver.command_gripper(width, self.profile['gripper_force_n'], precondition=precondition)
        bounds = release_feedback_range(self.plan['settings'], width) if status == 0 else [0, 110]
        if label == 'PREPARE_OPEN' and 'pickup_start_open_range_mm' in self.plan['settings']:
            bounds = self.plan['settings']['pickup_start_open_range_mm']
        deadline = self.clock()+10
        count = 0
        while self.clock() < deadline:
            sample = self.driver.sample()
            if sample['gripper_status'] not in (0, 1, 2, 3):
                raise RuntimeError('GRIPPER_SAFETY_OR_STATUS_FAULT')
            # Busy feedback is allowed while awaiting completion; equipment/force guards still apply.
            guard(dict(sample, gripper_status=status), self.connection, self.profile['force_stop_n'],
                  automatic=True, required_gripper_status=status)
            if type(sample['gripper_width_mm']) not in (int, float) or not math.isfinite(sample['gripper_width_mm']):
                raise RuntimeError('INVALID_GRIPPER_WIDTH_FEEDBACK')
            count = count+1 if (sample['gripper_status'] == status and bounds[0] <= sample['gripper_width_mm'] <= bounds[1]
                               and sample['motion_status'] == 0 and not any(sample['velx'])) else 0
            if count >= 3:
                self.emit('GRIP_SUCCEEDED', dict(label=label, sample=sample))
                return
            self.sleep(.05)
        raise TimeoutError('GRIP_COMPLETION_NOT_VERIFIED')

    def run(self):
        try:
            while self.cursor < len(self.operations):
                self.session.check()
                self.pending, argument = self.operations[self.cursor]
                kind = self.pending
                if kind == 'move': self.move(*argument)
                elif kind == 'blend':
                    self.driver.own('MOTION')
                    targets, held = argument
                    self.emit('MOVE_STARTED', dict(label='BLENDED_TRANSIT', targets=targets, gripper_status=held))
                    run_blend(self.driver, self.connection, targets, self.profile, self.emit,
                        held=held, clock=self.clock, sleep=self.sleep)
                elif kind == 'grip': self.grip(*argument)
                elif kind == 'lift':
                    target = self.driver.sample()['posx']; target[2] = max(target[2], argument[0])
                    self.move('LIFT', target, argument[1])
                elif kind == 'receive':
                    direct = self.wait_signal('RECEIVE', 3., keep=True)
                    # Replace the remaining tray operation once, keeping the cursor valid on STOP.
                    if direct:
                        self.close_signal_request()
                        self.operations[self.cursor+1] = ('handover', None)
                elif kind == 'tray':
                    try:
                        self.move('TRAY_LOWER', argument, 2, True)
                    finally:
                        self.close_signal_request()
                    # Descent is complete and stopped before opening; separate checkpoint avoids replaying it.
                    self.operations[self.cursor+1:self.cursor+1] = [
                        ('grip', ('TRAY_RELEASE', self.plan['settings']['release_width_mm'], 0)),
                        ('lift', (self.profile['clearance_z_mm'], 0))]
                elif kind == 'handover':
                    self.wait_signal('RECEIVE', keep=True)
                    self.pending = 'grip'
                    try:
                        self.grip('DIRECT_HANDOVER', self.plan['settings']['release_width_mm'], 0,
                                  precondition=lambda:self.check_receive_signal(ready=True))
                    finally:
                        self.close_signal_request()
                elif kind == 'ack':
                    received = self.wait_signal('ASSEMBLY_ACK', 10.)
                    self.emit('ASSEMBLY_CUE_FINISHED', dict(received=received, assembly_completion=False))
                elif kind == 'help':
                    self.wait_signal('HELP_READY')
                elif kind == 'help_release':
                    # Robot has released and retreated. Structural confirmation belongs to D/B.
                    self.emit('HELP_MAINTAIN', dict(until='B_CONFIRMED_STRUCTURE', automatic_release=False))
                elif kind == 'contact':
                    if self.raw.mode == 'REAL' and self.no_vision_trial:
                        # 접촉 전 사람의 실제 정렬 확인을 새 요청으로 받는다.
                        # 테스트 신호/계산 TCP가 물리 정렬 근거를 대신하지 않는다.
                        if not self.wait_signal('ALIGNMENT_READY', self.session.value['request_timeout_s']):
                            raise TimeoutError('OPERATOR_ALIGNMENT_TIMEOUT')
                        self.session.value['trial_alignment_pending'] = False
                        self.session.value['alignment_evidence_ref'] = 'THIS_EXECUTION_OPERATOR_ALIGNMENT'
                        validate_execution(self.plan, self.profile, self.session.value, 'contact')
                    self.contact_started = True
                    self.driver.own('CONTACT')
                    reference = self.plan['settings']['reference_pose']
                    travel = self.driver.sample()['posx'][2]-(reference[2]+self.profile['near_contact_offset_mm']-self.profile['max_press_travel_mm'])
                    if self.profile.get('native_press'):
                        from app.assembly_native_press import native_press
                        self.contact = native_press(self.driver, self.connection, self.plan, self.profile, travel,
                                                    self.emit, clock=self.clock, sleep=self.sleep)
                    else:
                        self.contact = press(self.driver, self.connection, self.emit, max_travel_mm=travel,
                            force_stop_n=self.profile['force_stop_n'], velocity=self.profile['descent_velocity'],
                            acceleration=self.profile['descent_acceleration'], clock=self.clock, sleep=self.sleep)
                    if self.contact['status'] not in ('FORCE_THRESHOLD_REACHED_STOP_VERIFIED', 'NATIVE_FORCE_LIMIT_STOP_VERIFIED', 'NATIVE_FORCE_LOAD_HOLD_VERIFIED'):
                        raise RuntimeError('CONTACT_NOT_VERIFIED')
                    self.driver.stillness()
                    self.emit('CONTACT_SUCCEEDED', dict(status=self.contact['status'], assembly_completion=False))
                self.cursor += 1
                self.pending = None
                self.emit('CHECKPOINT', dict(cursor=self.cursor))
            self.session.check()
            if self.no_vision_trial:
                self.state = 'IDLE'
                self.emit('TRIAL_STEP_EXECUTED', dict(vision_confirmed=False,
                    assembly_completion=False, current_update=False))
                return dict(status=self.state, vision_confirmed=False,
                            assembly_completion=False, current_update=False)
            self.state = 'AWAITING_INSPECTION'
            self.emit('INSPECTION_REQUIRED', dict(purpose='STEP', assembly_completion=False, current_update=False))
            return dict(status=self.state, assembly_completion=False, current_update=False)
        except Exception as error:
            stopped = self.session.cancelled
            self.session.request_stop('STOP_REQUESTED' if stopped else 'EXECUTION_FAILED')
            try:
                self.driver.stop()
                self.stopped_sample = deepcopy(self.driver.snapshot)
                self.state = 'STOPPED' if stopped else 'RECOVERY_REQUIRED'
                self.emit('STOP_VERIFIED', dict(sample=self.stopped_sample, actual_stop_verified=True))
            except Exception as stop_error:
                self.stopped_sample = None
                self.state = 'RECOVERY_REQUIRED'
                self.emit('STOP_UNVERIFIED', dict(reason=str(stop_error), actual_stop_verified=False))
            self.emit('EXECUTION_HELD', dict(status=self.state, reason=str(error), pending=self.pending,
                                           cursor=self.cursor, resume_allowed=self.can_resume(),
                                           assembly_completion=False, current_update=False))
            return dict(status=self.state, reason=str(error), current_update=False)
        finally:
            self.close_signal_request()
            self.session.owner, self.session.lease = 'NONE', None

    def stop(self):
        if self.session is None: return
        previous = self.state
        self.session.request_stop('STOP_REQUESTED')
        if previous in ('AWAITING_INSPECTION', 'WAIT_REINSPECTION'):
            try:
                self.driver.stop()
                self.stopped_sample = deepcopy(self.driver.snapshot)
                self.state, self.pending = 'STOPPED', None
                self.emit('STOP_VERIFIED', dict(sample=self.stopped_sample, actual_stop_verified=True))
            except Exception as error:
                self.state, self.stopped_sample = 'RECOVERY_REQUIRED', None
                self.emit('STOP_UNVERIFIED', dict(reason=str(error), actual_stop_verified=False))
            self.emit('EXECUTION_HELD', dict(status=self.state, cursor=self.cursor,
                                           assembly_completion=False, current_update=False))

    def inspection(self, result, *, conditions_ready=False):
        if self.state not in ('AWAITING_INSPECTION', 'WAIT_REINSPECTION'):
            raise RuntimeError('NO_INSPECTION_PENDING')
        self.session.check()
        if any(result.get(k) != self.plan[k] for k in ('plan_id', 'step_id')):
            raise ValueError('STALE_INSPECTION')
        if result.get('execution_id') != self.session.value['execution_id']:
            raise ValueError('STALE_INSPECTION')
        decision = result['decision']
        if decision in ('KEEP', 'CALL_C') and not isinstance(result.get('current'), dict):
            raise ValueError('B_CONFIRMED_CURRENT_REQUIRED')
        if decision == 'UNOBSERVABLE':
            self.state = 'WAIT_REINSPECTION'
            if conditions_ready and self.inspection_attempt == 0:
                self.inspection_attempt += 1
                self.state = 'AWAITING_INSPECTION'
                self.emit('INSPECTION_REQUIRED', dict(purpose='STEP', automatic_reinspection=True, current_update=False))
            else:
                self.emit('REINSPECTION_WAIT', dict(hmi_request_needed=True, current_update=False))
        elif decision in ('KEEP', 'CALL_C'):
            self.state = 'IDLE' if decision == 'KEEP' else 'WAIT_C'
            if decision == 'KEEP' and self.plan['assistance_kind'] in ('HOLD', 'PRESS_AND_HOLD'):
                self.emit('HELP_RELEASE_GUIDANCE', dict(b_confirmed=True))
            self.emit('B_DECISION', dict(result=result, next_step_allowed=decision == 'KEEP', current_update=False))
        else:
            raise ValueError('UNKNOWN_B_DECISION')
        return self.state

    def reinspect(self):
        if self.state != 'WAIT_REINSPECTION': raise RuntimeError('NO_REINSPECTION_PENDING')
        self.session.check()
        self.state = 'AWAITING_INSPECTION'
        self.emit('INSPECTION_REQUIRED', dict(purpose='STEP', automatic_reinspection=False, current_update=False))
