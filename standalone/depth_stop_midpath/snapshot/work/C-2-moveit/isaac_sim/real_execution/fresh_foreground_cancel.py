"""SIM conservative-stop gate around the existing D cancel sender.

This is not a 3D risk product or a transport loop. The caller stays on its
existing serialized D thread and supplies its current readout and cancel client.
No clocks, files, SDK objects, background workers or owners are created here.
"""
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite

from isaac_sim.depth_obstacles.novel_depth.foreground_stop_notice import verify_foreground_stop_notice


MAX_SOURCE_AGE_S = .12
SCOPE = 'ISOLATED_SIM_CONSERVATIVE_FOREGROUND_STOP'
BINDING_FIELDS = ('session_id', 'clock_epoch', 'clock_basis', 'map_digest',
                  'model_manifest_sha256', 'qualification_ref', 'qualification_digest',
                  'error_model_digest', 'calibration_digest')


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                             separators=(',', ':')).encode()).hexdigest()


def _finite(value):
    return type(value) in (int, float) and isfinite(value)


def _uuid(value):
    return (type(value) is str and len(value) == 32 and
            all(c in '0123456789abcdef' for c in value) and value != '0' * 32)


def _same(value, expected):
    try:
        return _digest(value) == _digest(expected)
    except (TypeError, ValueError):
        return False


class FreshForegroundCancelGate:
    """One accepted UUID, one cancel attempt; construct anew for a new goal.

    ``dispatch`` first verifies the Depth-owned immutable notice, then invokes
    ``read_current``. That readout and ``send_same_uuid`` must run consecutively
    on the same D thread without advancing physics or awaiting UI/file work.
    ``send_same_uuid(uuid)`` uses the caller's ORIGINAL scoped CancelGoal client.
    Its returned future is handed to the existing ACK/result/STOP procedure.
    The reservation stays consumed even if sending raises: no automatic retry.
    """

    def __init__(self, *, goal_uuid, active_wire_digest, source_binding,
                 sim_conservative_stop_authorized=False,
                 max_source_age_SIM_s=MAX_SOURCE_AGE_S):
        if sim_conservative_stop_authorized is not True or not _uuid(goal_uuid):
            raise ValueError('EXPLICIT_SIM_AUTHORIZATION_AND_UUID_REQUIRED')
        if not _finite(max_source_age_SIM_s) or max_source_age_SIM_s not in (.12, .4):
            raise ValueError('EXPLICIT_CONSERVATIVE_STOP_AGE_POLICY_REQUIRED')
        if (type(active_wire_digest) is not str or len(active_wire_digest) != 64 or
                any(c not in '0123456789abcdef' for c in active_wire_digest)):
            raise ValueError('ACTIVE_WIRE_DIGEST_REQUIRED')
        self._binding = {k: deepcopy(source_binding[k]) for k in BINDING_FIELDS}
        if (self._binding['clock_basis'] != 'SIM_TIME' or
                type(self._binding['clock_epoch']) is not int):
            raise ValueError('ACTUAL_SIM_CLOCK_BINDING_REQUIRED')
        _digest(self._binding)  # Reject nonfinite/nonserializable binding inputs.
        self._goal_uuid = goal_uuid
        self._wire_digest = active_wire_digest
        self._max_source_age_s = max_source_age_SIM_s
        self._reserved = False
        self.last_receipt = None

    def dispatch(self, notice, *, read_current, send_same_uuid):
        receipt = dict(scope=SCOPE, conservative_stop=False,
            cancel_request_issued=False, decision='NOT_REQUESTED', reasons=[],
            bound_goal_uuid=self._goal_uuid, active_wire_digest=self._wire_digest,
            source_age_SIM_s=None, max_source_age_SIM_s=self._max_source_age_s,
            age_policy_scope='CONSERVATIVE_STOP_ONLY_NOT_PRODUCER_OR_RISK_FRESHNESS',
            risk=None, risk_qualified=False, point3D_error_m=None,
            world_clear_allowed=False, hardware_execution_allowed=False,
            automatic_resume=False)
        self.last_receipt = receipt
        if self._reserved:
            receipt.update(decision='DUPLICATE_CANCEL_SUPPRESSED')
            return receipt, None
        if notice is None:
            receipt.update(decision='NO_FOREGROUND_NOTICE')
            return receipt, None
        try:
            metadata = verify_foreground_stop_notice(notice)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            receipt.update(decision='NOTICE_REJECTED', reasons=[str(exc)])
            return receipt, None
        # Sample AFTER notice integrity review. Never use a worker-exit or
        # provider-upload observation as the actual cancel-send clock.
        current = read_current()
        receipt.update(notice_metadata=metadata, actual_cancel_boundary=deepcopy(current))
        reasons = receipt['reasons']
        if (current.get('scope') != SCOPE or current.get('ros_domain_id') != 194 or
                current.get('localhost_only') is not True):
            reasons.append('EXPLICIT_SIM194_LOCALHOST_BOUNDARY_REQUIRED')
        for key in BINDING_FIELDS:
            if (key not in metadata or key not in current or
                    not _same(metadata[key], self._binding[key]) or
                    not _same(current[key], self._binding[key])):
                reasons.append('SOURCE_BINDING_CHANGED:' + key)
        if (current.get('active_goal_uuid') != self._goal_uuid or
                current.get('active_wire_digest') != self._wire_digest):
            reasons.append('ACTIVE_UUID_OR_WIRE_CHANGED')
        if (current.get('goal_accepted') is not True or
                current.get('goal_terminal') is not False or
                type(current.get('active_command_count')) is not int or
                current.get('active_command_count') != 1 or
                type(current.get('pending_command_count')) is not int or
                current.get('pending_command_count') != 0):
            reasons.append('ONE_CURRENT_ACCEPTED_ACTIVE_GOAL_REQUIRED')
        source = metadata.get('source_stamp_s')
        now = current.get('source_s')
        accepted = current.get('accepted_source_s')
        wall = current.get('observed_wall_monotonic_s')
        if not all(_finite(v) for v in (source, now, accepted, wall)):
            reasons.append('FINITE_ACTUAL_CANCEL_CLOCK_REQUIRED')
        else:
            age = now - source
            receipt['source_age_SIM_s'] = age
            # Preserve the default guard exactly. The explicit .4 policy uses
            # an inclusive source deadline: subtraction at e.g. 10.4-10 can
            # round above .4. No epsilon, source retag or age rewriting is used.
            within_age = 0 <= age <= MAX_SOURCE_AGE_S
            if self._max_source_age_s == .4:
                deadline = source + self._max_source_age_s
                receipt['source_deadline_SIM_s'] = deadline
                within_age = source <= now <= deadline
            if not within_age:
                reasons.append('STALE_OR_FUTURE_AT_CANCEL_SEND')
            if not accepted <= source <= now:
                reasons.append('SOURCE_NOT_FROM_ACCEPTED_GOAL_INTERVAL')
        count = metadata.get('counts', {}).get('foreground')
        if (type(count) is not int or count <= 0 or
                metadata.get('qualified_foreground_observed') is not True or
                metadata.get('risk_qualified') is not False or
                metadata.get('point_error_m') is not None):
            reasons.append('QUALIFIED_FOREGROUND_REQUIRED')
        completed = metadata.get('completed_source_observation', {})
        completion_source = completed.get('source_s')
        completion_wall = completed.get('wall_monotonic_s', completed.get('observed_wall_monotonic_s'))
        if (not all(_finite(v) for v in (source, completion_source, completion_wall, now, wall)) or
                not source <= completion_source <= now or completion_wall > wall):
            reasons.append('ACTUAL_COMPLETION_CANCEL_CLOCK_ORDER_REQUIRED')
        if reasons:
            receipt.update(decision='CANCEL_NOT_ADMITTED')
            return receipt, None
        self._reserved = True
        receipt.update(conservative_stop=True, decision='CANCEL_RESERVED')
        try:
            future = send_same_uuid(self._goal_uuid)
        except Exception as exc:
            receipt.update(decision='CANCEL_SEND_OUTCOME_UNKNOWN', send_error=str(exc),
                           send_error_type=type(exc).__name__)
            raise
        receipt.update(decision='SCOPED_CANCEL_CALL_RETURNED', cancel_request_issued=True)
        return receipt, future
