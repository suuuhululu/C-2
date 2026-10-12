"""Local D-side request and lease checks; no device imports or Current commits."""
from copy import deepcopy
import math
import time
from uuid import uuid4

from app.handover_gesture import GestureGate


def positive(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('POSITIVE_FINITE_REQUIRED:'+name)
    return value


def validate_session(value, plan, *, backend):
    s = deepcopy(value)
    if s.get('backend') != backend or backend not in ('TEST', 'REAL'):
        raise ValueError('EXPLICIT_BACKEND_REQUIRED')
    for key in ('execution_id', 'source_epoch', 'frame_profile_id', 'plan_id', 'step_id'):
        if not isinstance(s.get(key), str) or not s[key]:
            raise ValueError('SESSION_ID_REQUIRED:'+key)
    for key in ('plan_id', 'step_id', 'current_revision'):
        if s.get(key) != plan[key]:
            raise ValueError('SESSION_BINDING_MISMATCH:'+key)
    revision = s.get('current_revision')
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ValueError('INVALID_CURRENT_REVISION')
    if backend == 'TEST' and s.get('provenance') != 'SYNTHETIC':
        raise ValueError('TEST_PROVENANCE_MUST_BE_SYNTHETIC')
    positive(s.get('expires_unix_s'), 'expires_unix_s')
    for key in ('request_timeout_s', 'frame_max_age_s', 'frame_max_gap_s', 'inference_max_latency_s'):
        positive(s.get(key), key)
    p = s.get('stillness', {})
    for key in ('window_s', 'max_gap_s', 'timeout_s', 'sample_max_duration_s',
                'position_mm', 'orientation_deg', 'linear_mm_s', 'angular_deg_s'):
        positive(p.get(key), 'stillness.'+key)
    if type(p.get('min_samples')) is not int or p['min_samples'] < 2:
        raise ValueError('STILLNESS_REQUIRES_MULTIPLE_SAMPLES')
    if p['window_s'] >= p['timeout_s'] or p['max_gap_s'] > p['timeout_s']:
        raise ValueError('INVALID_STILLNESS_WINDOWS')
    if backend == 'REAL':
        if s.get('provenance') not in ('LOCAL_OPERATOR_TRIAL', 'LIVE_D_RUNTIME'):
            raise ValueError('LIVE_SESSION_PROVENANCE_REQUIRED')
        if any(s.get(k) is not True for k in ('exclusive_control_reviewed',
                'device_feedback_reviewed', 'stillness_parameters_reviewed', 'hand_clear_reviewed')):
            raise ValueError('ONSITE_REVIEW_REQUIRED')
        if 'MOCK' in s['source_epoch'].upper() or 'TEST' in s['source_epoch'].upper():
            raise ValueError('TEST_EPOCH_CANNOT_EXECUTE_REAL')
    from app.automatic_stage_trial import validate_policy
    validate_policy(s, plan)
    return s


def validate_execution(plan, profile, session, phase):
    """Library callers and CLI share the same pre-device REAL admission checks."""
    from app.assembly_step_bridge import validate_physical
    from scripts.assembly_step_trial import validate_runtime
    validate_session(session, plan, backend='REAL')
    if time.time() >= session['expires_unix_s']:
        raise ValueError('SESSION_EXPIRED')
    if session.get('profile_id') != profile['profile_id']:
        raise ValueError('SESSION_PROFILE_BINDING_MISMATCH')
    if session.get('allowed_trial_phase') == 'retreat' and phase != 'retreat':
        raise ValueError('RETREAT_RECOVERY_SESSION_CANNOT_EXECUTE_OTHER_PHASES')
    if session.get('allowed_trial_phase') == 'pickup' and phase != 'pickup':
        raise ValueError('PICKUP_SESSION_CANNOT_EXECUTE_OTHER_PHASES')
    if session.get('allowed_trial_phase') == 'handover' and phase != 'handover':
        raise ValueError('HANDOVER_SESSION_CANNOT_EXECUTE_OTHER_PHASES')
    if session.get('allowed_trial_phase') == 'assemble-held' and phase != 'assemble-held':
        raise ValueError('HELD_ASSEMBLY_SESSION_CANNOT_EXECUTE_OTHER_PHASES')
    if session.get('allowed_trial_phase') == 'grasp-recovery' and phase != 'grasp-recovery':
        raise ValueError('GRASP_RECOVERY_SESSION_CANNOT_EXECUTE_OTHER_PHASES')
    validate_physical(plan, profile, phase)
    from app.human_step_gestures import validate_policy as validate_human_policy
    validate_human_policy(plan, profile, session)
    if phase=='human-wait' and (session.get('provenance')!='LOCAL_OPERATOR_TRIAL' or
            session.get('allowed_trial_phase')!=phase or not session.get('human_wait_resume_review_ref')):
        raise ValueError('EXPLICIT_LOCAL_HUMAN_WAIT_RESUME_REQUIRED')
    if session.get('allowed_trial_phase')=='human-wait' and phase!='human-wait':
        raise ValueError('HUMAN_WAIT_SESSION_CANNOT_EXECUTE_OTHER_PHASES')
    if phase=='human-ack' and (session.get('provenance')!='LOCAL_OPERATOR_TRIAL' or
            session.get('allowed_trial_phase')!=phase or not session.get('human_ack_resume_review_ref')):
        raise ValueError('EXPLICIT_LOCAL_HUMAN_ACK_RESUME_REQUIRED')
    if session.get('allowed_trial_phase')=='human-ack' and phase!='human-ack':
        raise ValueError('HUMAN_ACK_SESSION_CANNOT_EXECUTE_OTHER_PHASES')
    if profile.get('transport_blending') is not None and (
            session.get('provenance') not in ('LOCAL_OPERATOR_TRIAL', 'LIVE_D_RUNTIME') or
            not session.get('transport_blend_review_ref')):
        raise ValueError('EXPLICIT_LOCAL_TRANSPORT_BLEND_REVIEW_REQUIRED')
    if phase == 'grasp-recovery' and (session.get('provenance') != 'LOCAL_OPERATOR_TRIAL' or
            session.get('allowed_trial_phase') != phase or not session.get('recovery_evidence_ref')):
        raise ValueError('EXPLICIT_LOCAL_GRASP_RECOVERY_SESSION_REQUIRED')
    if phase == 'handover':
        from app.gesture_handover_trial import validate_handover
        validate_handover(plan, profile, session)
    if phase == 'retreat' and (session.get('provenance') != 'LOCAL_OPERATOR_TRIAL' or
            session.get('allowed_trial_phase') != 'retreat' or not session.get('recovery_evidence_ref')):
        raise ValueError('EXPLICIT_LOCAL_RETREAT_RECOVERY_SESSION_REQUIRED')
    if session.get('provenance') == 'LIVE_D_RUNTIME':
        validate_runtime(plan, session['d_runtime'], profile)
    if phase == 'release' and not session.get('seating_evidence_ref'):
        raise ValueError('FRESH_SEATING_EVIDENCE_REQUIRED_FOR_RELEASE')
    settings = plan['settings']
    if phase in ('contact', 'full', 'assemble-held') and settings.get('turn_base_z_deg') and settings.get('xy_grasp_rotation_compensation_measured') is not True:
        raise ValueError('ROTATED_GRASP_XY_COMPENSATION_NOT_MEASURED')
    pending_trial_alignment = (phase == 'full' and session.get('no_vision_trial') is True
                               and session.get('trial_alignment_pending') is True)
    if phase in ('contact', 'full', 'assemble-held') and plan['assistance_kind'] == 'NONE' and not session.get('alignment_evidence_ref') and not pending_trial_alignment:
        raise ValueError('FRESH_ALIGNMENT_EVIDENCE_REQUIRED')


class ControlSession:
    """One active human request and one physical owner per execution."""
    def __init__(self, session, plan, record, *, clock=time.monotonic, wall=time.time):
        self.value = validate_session(session, plan, backend=session.get('backend'))
        self.binding = {k: plan[k] for k in ('plan_id', 'step_id', 'current_revision')}
        self.record, self.clock, self.wall = record, clock, wall
        self.cancelled, self.cancel_reason = False, None
        self.request, self.owner, self.lease = None, 'NONE', None
        self.used_requests = set()
        self.state_sequence = 0
        self.execution_claimed = False
        self.preview_candidate = None
        self.started = clock()
        self.duration = self.value['expires_unix_s']-wall()
        self.gate = GestureGate(max_age_ns=round(self.value['frame_max_age_s']*1e9),
                                max_gap_ns=round(self.value['frame_max_gap_s']*1e9),
                                max_latency_ns=round(self.value['inference_max_latency_s']*1e9))
        self.check()

    def check(self):
        if self.cancelled:
            raise RuntimeError(self.cancel_reason)
        if self.wall() >= self.value['expires_unix_s'] or self.clock()-self.started >= self.duration:
            raise RuntimeError('SESSION_EXPIRED')

    def request_stop(self, reason='STOP_REQUESTED'):
        self.cancelled, self.cancel_reason = True, reason
        self.request, self.preview_candidate = None, None
        self.owner, self.lease = 'NONE', None

    def claim_execution(self):
        self.check()
        if self.execution_claimed:
            raise RuntimeError('EXECUTION_ALREADY_CLAIMED')
        self.execution_claimed = True

    def switch_owner(self, owner, snapshot, *, recheck):
        self.check()
        if owner not in ('MOTION', 'CONTACT', 'GRIPPER', 'WAIT') or recheck is not True:
            raise RuntimeError('D_CONDITION_RECHECK_REQUIRED')
        old = self.lease
        self.owner, self.lease = 'NONE', None
        new = str(uuid4())
        self.record('ADAPTER_LEASE_APPLIED', dict(old_lease=old, new_lease=new, owner=owner,
                    state_sequence=self.state_sequence, snapshot=snapshot,
                    scope='LOCAL_TRIAL_IN_PROCESS_ACK_NOT_EXTERNAL_D_ACK'))
        self.owner, self.lease = owner, new
        return new

    def require_lease(self, lease, *owners):
        self.check()
        if lease is None or lease != self.lease or self.owner not in owners:
            raise RuntimeError('STALE_OR_WRONG_CONTROL_LEASE')

    def open_request(self, kind):
        self.check()
        if self.request is not None:
            raise RuntimeError('REQUEST_ALREADY_ACTIVE')
        mode = 'RECEIVE' if kind == 'RECEIVE' else 'QUESTION'
        now = self.clock()
        self.request = dict(request_id=str(uuid4()), kind=kind, mode=mode, **self.binding,
                            execution_id=self.value['execution_id'], source_epoch=self.value['source_epoch'],
                            opened_monotonic_s=now, deadline_monotonic_s=now+self.value['request_timeout_s'])
        self.preview_candidate = None
        self.record('HUMAN_REQUEST_OPENED', self.request.copy())
        return self.request.copy()

    def close_request(self):
        if self.request:
            self.record('HUMAN_REQUEST_CLOSED', self.request.copy())
            self.used_requests.add(self.request['request_id'])
        self.request, self.preview_candidate = None, None

    def respond(self, request_id, positive_response, *, source):
        self.check()
        if (self.request is None or request_id != self.request['request_id']
                or request_id in self.used_requests):
            raise RuntimeError('INACTIVE_OR_OLD_HUMAN_REQUEST')
        if self.clock() > self.request['deadline_monotonic_s']:
            self.close_request()
            raise TimeoutError('HUMAN_RESPONSE_TIMEOUT')
        if type(positive_response) is not bool or source not in ('HMI', 'VERIFIED_GESTURE'):
            raise ValueError('EXPLICIT_RESPONSE_SOURCE_REQUIRED')
        self.record('HUMAN_RESPONSE', dict(request=self.request.copy(),
                    positive=positive_response, source=source,
                    preview_candidate=self.preview_candidate, assembly_completion=False))
        self.close_request()
        return positive_response

    def gesture(self, sample, now_ns):
        self.check()
        if self.request is None:
            return None
        for key in ('execution_id', 'source_epoch', *self.binding):
            expected = self.binding[key] if key in self.binding else self.value[key]
            if sample.get(key) != expected:
                raise RuntimeError('GESTURE_CONTEXT_MISMATCH:'+key)
        # A camera preview never satisfies the strict Gate's verified evidence contract.
        if sample.get('candidate_event'):
            if sample.get('preview_request_id') == self.request['request_id']:
                self.preview_candidate = deepcopy(sample)
                self.record('UNVERIFIED_GESTURE_CANDIDATE', sample)
            return None
        result = self.gate.evaluate(sample, now_ns, mode=self.request['mode'],
                                    request_id=self.request['request_id'])
        event = result['event']
        if event is None:
            return None
        return self.respond(self.request['request_id'], event != 'NO', source='VERIFIED_GESTURE')
