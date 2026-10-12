"""Single writer wrapping the original driver; STOP remains possible after faults."""
from copy import deepcopy
import math
import time

from app.assembly_motion import pose_error, vector
from app.assembly_step_runner import run_step
from app.control_session import validate_execution


class ControlledDriver:
    def __init__(self, raw, session, connection, *, clock=time.monotonic, sleep=time.sleep):
        self.raw, self.session, self.connection = raw, session, connection
        self.clock, self.sleep, self.mode = clock, sleep, raw.mode
        if self.mode not in ('MOCK', 'FAKE', 'REAL'):
            raise ValueError('UNKNOWN_DRIVER_BACKEND')
        if (self.mode == 'REAL') != (session.value['backend'] == 'REAL'):
            raise ValueError('DRIVER_SESSION_BACKEND_MISMATCH')
        self.snapshot = None
        self.last_contact_result = None
        self.command_outcome_unknown = False
        self.last_verified_sample = None
        self.verified_at, self.verified_sequence = None, None
        self.automatic_confirmation = session.value.get('automatic_stage_checks') is not None
        self.trial_grasp_reference = None
        self.native_force_active = False

    def sample(self):
        self.session.check()
        s = self.raw.sample()
        self.session.state_sequence += 1
        self.snapshot = deepcopy(s)
        return s

    def motion_feedback(self):
        return self.raw.motion_feedback()

    def check_pose(self, *args, **kwargs):
        self.session.check()
        return self.raw.check_pose(*args, **kwargs)

    def robot_system(self):return self.raw.robot_system()

    def check_contact_services(self, **kwargs):return self.raw.check_contact_services(**kwargs)

    def _force_write(self,name,*args,cleanup=False,**kwargs):
        if not cleanup:
            self.session.require_lease(self.session.lease,'CONTACT')
            self.session.check()
        if name=='enable_compliance':self.native_force_active=True
        try:
            result=getattr(self.raw,name)(*args,**kwargs)
            if name=='release_compliance':self.native_force_active=False
            return result
        except Exception:
            self.command_outcome_unknown=True
            raise

    def enable_compliance(self,stiffness,transition):
        return self._force_write('enable_compliance',stiffness,transition)

    def set_downward_force(self,force,transition,*,relative=True):
        return self._force_write('set_downward_force',force,transition,relative=relative)

    def release_force(self,transition):return self._force_write('release_force',transition,cleanup=True)

    def release_compliance(self):return self._force_write('release_compliance',cleanup=True)

    def stillness(self, *, allow_cancelled=False, during_stillness=None):
        p = self.session.value['stillness']
        begin, first, count, previous = None, None, 0, None
        deadline = self.clock()+p['timeout_s']
        while self.clock() < deadline:
            if not allow_cancelled:
                self.session.check()
            s = self.raw.sample()
            if during_stillness is not None:
                during_stillness(s)
            now = self.clock()
            self.session.state_sequence += 1
            speed = vector(s['velx'], 6, 'stillness velocity')
            duration = s.get('query_duration_s')
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= p['sample_max_duration_s']:
                raise RuntimeError('STALE_STOP_SAMPLE')
            if s['tcp'] != self.connection['tcp'] or s['tool'] != self.connection['tool']:
                raise RuntimeError('TCP_TOOL_MISMATCH')
            if s['robot_state'] not in (1, 2) or s['robot_mode'] != 1 or s['drl_state'] != 3:
                raise RuntimeError('ROBOT_NOT_READY_FOR_HANDOFF')
            if s.get('gripper_status') not in (0, 2):
                raise RuntimeError('GRIPPER_NOT_STILL')
            still = (s['motion_status'] == 0 and max(map(abs, speed[:3])) <= p['linear_mm_s']
                     and max(map(abs, speed[3:])) <= p['angular_deg_s'])
            if first is not None:
                mm, deg = pose_error(s['posx'], first['posx'])
                still = still and mm <= p['position_mm'] and deg <= p['orientation_deg']
            if not still or (previous is not None and now-previous > p['max_gap_s']):
                begin, first, count = None, None, 0
            if still:
                if first is None:
                    begin, first = now, deepcopy(s)
                count += 1
                if count >= p['min_samples'] and now-begin >= p['window_s']:
                    self.snapshot = deepcopy(s)
                    self.last_verified_sample = s
                    self.verified_at, self.verified_sequence = now, self.session.state_sequence
                    self.session.record('STILLNESS_WINDOW_VERIFIED', dict(sample=s, samples=count,
                        window_s=now-begin, state_sequence=self.session.state_sequence,
                        pending_commands=0, queue_scope='THIS_SINGLE_WRITER_ONLY',
                        measurement_timestamp_available=False))
                    return s
            previous = now
            self.sleep(.05)
        raise TimeoutError('STOP_WINDOW_NOT_VERIFIED')

    def own(self, owner, *, during_stillness=None, verified_snapshot=None):
        self.session.check()
        reuse = (owner=='WAIT' and during_stillness is None and verified_snapshot is not None and
                 verified_snapshot is self.last_verified_sample and
                 self.verified_sequence == self.session.state_sequence and
                 self.clock()-self.verified_at <= self.session.value['stillness']['sample_max_duration_s'])
        sample = verified_snapshot if reuse else self.stillness(during_stillness=during_stillness)
        self.last_verified_sample = None  # A proof can skip only one duplicate WAIT window.
        self.session.check()
        return self.session.switch_owner(owner, sample, recheck=True)

    def move_line_async(self, target, velocity, acceleration):
        self.session.require_lease(self.session.lease, 'MOTION', 'CONTACT')
        self.session.record('SINGLE_WRITER_MOVE', dict(lease=self.session.lease, target=target))
        self.session.check()
        try:
            return self.raw.move_line_async(target, velocity, acceleration)
        except Exception:
            self.command_outcome_unknown = True
            raise

    def command_gripper(self, width_mm, force_n, *, precondition=None, during_stillness=None):
        self.session.require_lease(self.session.lease, 'GRIPPER')
        monitor = getattr(self, 'human_receive_monitor', None)
        if monitor is not None:
            during_stillness = monitor
        self.stillness(during_stillness=during_stillness)
        if precondition is not None:
            precondition()
        self.session.check()
        if monitor is not None:
            monitor(self.snapshot)
        self.session.record('SINGLE_WRITER_GRIPPER', dict(lease=self.session.lease,
                            width_mm=width_mm, force_n=force_n, transport='DIRECT_MODBUS'))
        self.session.check()
        try:
            return self.raw.command_gripper(width_mm, force_n)
        except Exception:
            self.command_outcome_unknown = True
            raise
        finally:
            if monitor is not None:
                self.human_receive_monitor = None
                self.session.close_request()

    def move_blending_async(self, targets, radius, velocity, acceleration):
        self.session.require_lease(self.session.lease, 'MOTION')
        self.session.record('SINGLE_WRITER_BLEND', dict(lease=self.session.lease,
                            targets=targets, radius_mm=radius))
        self.session.check()
        try:
            return self.raw.move_blending_async(targets, radius, velocity, acceleration)
        except Exception:
            self.command_outcome_unknown = True
            raise

    def stop(self):
        self.raw.stop()
        if self.native_force_active:
            # Native cleanup releases force/compliance next, then verifies STOP.
            # Waiting here would wait for stillness while force is maintained.
            self.session.record('STOP_ACK_FORCE_CLEANUP_PENDING',dict(actual_stop_verified=False))
            return
        # Query even when cancelled. ACK is recorded separately from the observation window.
        try:
            self.session.record('STOP_ACK', dict(actual_stop_verified=False))
        finally:
            sample = self.stillness(allow_cancelled=True)
        self.session.record('STOP_WINDOW_RESULT', dict(actual_stop_verified=not self.command_outcome_unknown,
            stillness_window_verified=True, pending_command_outcome_unknown=self.command_outcome_unknown, sample=sample))
        if self.command_outcome_unknown:
            raise RuntimeError('STOP_WINDOW_ONLY_PENDING_COMMAND_OUTCOME_UNKNOWN')


def execute_step(raw, session, connection, plan, profile, confirm, record, *, phase='contact',
                 start_zone='assembly', camera_poll=None, clock=time.monotonic, sleep=time.sleep):
    from app.human_step_gestures import validate_policy as validate_human_policy, STAGES, wait_stage
    validate_human_policy(plan, profile, session.value)
    from app.assembly_native_press import validate_native_press
    validate_native_press(plan,profile)
    if raw.mode == 'REAL':
        validate_execution(plan, profile, session.value, phase)
        if profile.get('native_press'):
            from scripts.onsite_slot2_force_trial import require_drcf2_runtime
            require_drcf2_runtime()
            raw.check_contact_services(native_force=True)
    session.claim_execution()
    driver = ControlledDriver(raw, session, connection, clock=clock, sleep=sleep)

    def emit(event, data):
        session.check()
        if event == 'STEP_MOVE':
            driver.own('MOTION')
        elif event == 'PRESS_SESSION':
            driver.own('CONTACT')
        elif event == 'GRIPPER_REQUEST':
            driver.own('GRIPPER', during_stillness=getattr(driver,'human_receive_monitor',None))
        elif event == 'PRESS_RESULT':
            driver.last_contact_result = deepcopy(data)
        elif event == 'TURN_REFERENCE':
            driver.trial_grasp_reference = deepcopy(data['start_pose'])
        record(event, data)

    def answer(kind, active_plan, sample):
        driver.own('WAIT', verified_snapshot=sample)
        if active_plan['settings'].get('human_step_gestures') and kind in STAGES:
            return wait_stage(driver,active_plan,profile,kind,camera_poll)
        if driver.automatic_confirmation:
            from app.automatic_stage_trial import check_stage
            evidence = check_stage(driver,kind,active_plan,profile,driver.snapshot)
            record('AUTOMATIC_STAGE_CHECK',evidence)
            return True
        req = session.open_request(kind)
        try:
            response = confirm(req, active_plan, sample, session)
            session.check()
            # A verified gesture may have consumed the request while the UI was waiting.
            if session.request is None:
                return response is True
            return session.respond(req['request_id'], response, source='HMI')
        finally:
            session.close_request()

    try:
        driver.own('WAIT')
        if phase == 'handover':
            if start_zone != session.value.get('handover_start_zone', 'supply'):
                raise ValueError('HANDOVER_START_ZONE_SESSION_MISMATCH')
            from app.gesture_handover_trial import run_handover
            result = run_handover(driver, connection, plan, profile, answer, emit,
                                  camera_poll, clock=clock, sleep=sleep)
        else:
            result = run_step(driver, connection, plan, profile, answer, emit,
                              phase=phase, start_zone=start_zone, clock=clock, sleep=sleep)
        session.check()
        result.update(execution_id=session.value['execution_id'], backend=session.value['backend'],
                      final_state_sequence=session.state_sequence, physical_verified=False,
                      backend_current_committed=False, contact_evidence=driver.last_contact_result,
                      integration_scope='LOCAL_TRIAL_NOT_LIVE_A_B_D_CONTRACT')
        record('INTEGRATED_EXECUTION_RESULT', result)
        return result
    except BaseException:
        session.request_stop('EXECUTION_FAILED_OR_CANCELLED')
        try:
            driver.stop()
        except Exception as error:
            record('STOP_UNVERIFIED', dict(reason=str(error), actual_stop_verified=False))
        raise
    finally:
        session.close_request()
        session.owner, session.lease = 'NONE', None


def validate_assembly_fallback(handover_result, held_plan, plan, session):
    """No interaction cue is not an assembly approval; require a new bound execution."""
    if (handover_result.get('status') != 'ASSEMBLY_REQUIRED' or
            session.get('allowed_trial_phase') != 'assemble-held' or
            session.get('handover_parent_execution_id') != handover_result.get('execution_id') or
            not session.get('execution_id') or
            session['execution_id'] == handover_result.get('execution_id')):
        raise ValueError('FRESH_BOUND_ASSEMBLY_FALLBACK_SESSION_REQUIRED')
    if any(plan['block'][key] != held_plan['block'][key] for key in ('brick_type', 'color')):
        raise ValueError('FALLBACK_CANNOT_CHANGE_HELD_BLOCK')
    if handover_result.get('assembly_start_zone') not in ('supply', 'place', 'assembly'):
        raise ValueError('FALLBACK_START_ZONE_REQUIRED')
