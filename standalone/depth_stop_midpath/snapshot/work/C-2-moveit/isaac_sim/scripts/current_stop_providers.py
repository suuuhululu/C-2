"""Staged read-only main-thread providers. No SDK start, tick or admission.

The native camera and D closure are bound by the runner, never supplied through
an input JSON. Complete saved files are provenance; current D/native reads are
independently required on every invocation. No point/geometry grant is returned.
"""
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import json
import math
import marshal
import threading
import time

from isaac_sim.real_execution.preflight import digest

CLOCK = 'native-current-source-clock/1.0'
LIVE = 'native-current-stop-readout/1.0'
CAUSE = 'FRESH_FOREGROUND_CONSERVATIVE_STOP'
IDENTITY = ('session_id', 'clock_basis', 'clock_epoch')
GENERATIONS = ('execution_id', 'execution_version', 'goal_id', 'goal_version',
               'cancel_generation', 'replan_sequence')
CONTEXT = ('a_context', 'reservation_binding', 'current_revision', 'world_revision',
           'model_digest', 'model_manifest_sha256', 'active_wire_digest', 'original_goal')
FINGERS = ['rg2_left_inner_finger', 'rg2_right_inner_finger']


def pin(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())


def pinned(ref):
    if pin(ref['path']) != ref:
        raise ValueError('IMMUTABLE_CAPTURE_PARENT_CHANGED')
    return json.loads(Path(ref['path']).read_text())


def verify_raw(bundle, frame_ref):
    verified = []
    if (bundle['scope'] != 'SELECTED_ORIGINAL_CAPTURE_AFTER_CLASSIFICATION_NOT_RECAPTURE'
            or bundle['payload_retained'] is not True
            or bundle['original_metadata_receipt_unchanged'] is not True
            or bundle['frame_input_ref'] != frame_ref):
        raise ValueError('COMPLETE_ORIGINAL_RAW_BUNDLE_REQUIRED')
    preview = bundle['raw_preview']
    for key in ('receipt', 'rgb', 'depth', 'camera_params'):
        verified.append(preview[key])
        if pin(preview[key]['path']) != preview[key]:
            raise ValueError('RAW_CAPTURE_FILE_CHANGED')
    verified.append(bundle['selected_arrays'])
    arrays = pinned(bundle['selected_arrays'])
    if arrays['source_frame_ref'] != frame_ref or not arrays['arrays_and_images']:
        raise ValueError('SAME_SOURCE_COMPLETE_ARRAYS_REQUIRED')
    for item in arrays['arrays_and_images'].values():
        verified.append(item)
        if pin(item['path']) != item:
            raise ValueError('SELECTED_ARRAY_FILE_CHANGED')
    return verified


def verify_state_capture(owner, state, frame, frame_ref):
    body = dict(state)
    claimed = body.pop('digest')
    if digest(body) != claimed or claimed != owner['state_digest']:
        raise ValueError('ORIGINAL_STATE_BODY_DIGEST_CHANGED')
    if (state['source_kind'] != 'SIM_SAVED_SNAPSHOT'
            or state['frame_input_ref'] != frame_ref
            or any(type(state[k]) is not type(owner[k]) or state[k] != owner[k] for k in IDENTITY)
            or type(state['state_sequence']) is not int or type(owner['state_sequence']) is not int
            or type(frame['source_association']['state_physics_step_index']) is not int
            or state['state_sequence'] != owner['state_sequence']
            or owner['state_sequence'] != frame['source_association']['state_physics_step_index']
            or type(state['source_stamp_s']) is not type(owner['state_stamp_s'])
            or state['source_stamp_s'] != owner['state_stamp_s']
            or owner['state_stamp_s'] != frame['robot_state_stamp_s']
            or frame['robot_state_stamp_s'] != frame['transform_stamp_s']
            or any(type(state[k]) is not type(owner[k]) or digest(state[k]) != digest(owner[k]) for k in
                   ('q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block'))
            or any(owner[k] != frame[k] for k in ('q_rad','grip_rad','attachment_tcp_to_block'))
            or state['raw_observed_a_rad_s2'] is not None
            or state['acceleration_method'] != 'ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE'):
        raise ValueError('SAME_SOURCE_STATE_OWNER_FRAME_PVA_SEQUENCE_REQUIRED')
    if (owner['snapshot_version'] != frame['frame_seq']
            or owner['snapshot_digest'] != sha256(json.dumps(frame, sort_keys=True, allow_nan=False).encode()).hexdigest()):
        raise ValueError('ORIGINAL_OWNER_RAW_CAPTURE_SNAPSHOT_CHANGED')


def verify_original_stop_proof(owner, publication, latest, frame, frame_ref, pub):
    proof_ref = owner['stop_verification']
    if proof_ref != publication['stop_verification_ref']:
        raise ValueError('ORIGINAL_OWNER_PROOF_REFERENCE_CHANGED')
    proof = pinned(proof_ref)
    keys = IDENTITY + ('execution_id','goal_id','goal_version','cancel_generation','replan_sequence')
    if (proof['scope'] != 'VERIFIED_D_CONSERVATIVE_FOREGROUND_STOP_AND_HOLDING_NOT_RESUME_APPROVAL'
            or proof['verification_method'] != 'ORIGINAL_D_POSITION_HISTORY_STOP_AND_SAME_UUID_TERMINAL'
            or proof['stop_verified'] is not True or proof['holding_confirmed'] is not True
            or proof['identity'] != {k:owner[k] for k in keys}
            or any(type(proof['identity'][k]) is not type(owner[k]) for k in keys)
            or type(proof['state_stamp_s']) is not type(owner['state_stamp_s'])
            or proof['state_stamp_s'] != owner['state_stamp_s']
            or proof['stop_record_digest'] != owner['stop_record']['record_digest']
            or proof['samples_digest'] != digest(owner['stop_record']['samples'])):
        raise ValueError('ORIGINAL_STOP_PROOF_IDENTITY_OR_ENDPOINT_CHANGED')
    endpoint = owner['stop_record']['samples'][-1]
    if (type(endpoint['stamp_s']) is not type(owner['state_stamp_s'])
            or endpoint['stamp_s'] != owner['state_stamp_s']
            or any(digest(endpoint[k]) != digest(owner[k]) for k in ('q_rad','v_rad_s','a_rad_s2'))):
        raise ValueError('ORIGINAL_STOP_RECORD_PVA_ENDPOINT_CHANGED')
    expected = dict(current_state=latest['state_ref'],frame=frame_ref,accepted=pub.accepted_ref,
                    original_request=pub.request_ref,accepted_wire=pub.wire_ref)
    expected.update({'frame_source_' + str(i):ref for i,ref in enumerate(frame['source_refs'])})
    if any(proof['evidence'].get(k) != ref for k,ref in expected.items()):
        raise ValueError('ORIGINAL_STOP_PROOF_SOURCE_REFS_MIXED')
    evidence = proof['evidence']
    for item in evidence.values():
        if pin(item['path']) != item:
            raise ValueError('ORIGINAL_STOP_PROOF_EVIDENCE_CHANGED')
    controller = pinned(evidence['controller_stop'])
    if (controller['source_status_ref'] != pub.status_ref
            or controller['state_stamp_s'] != owner['state_stamp_s']):
        raise ValueError('ORIGINAL_D_STATUS_SOURCE_CHANGED')
    return [proof_ref, *evidence.values()]


class CurrentStopProviders:
    def __init__(self, camera, publication, read_d, verified_stop, limits):
        self.camera = camera
        self.native_method = camera.native_stamp
        self.native_function = getattr(self.native_method, '__func__', self.native_method)
        self.native_code = self.native_function.__code__
        self.bound_read_d = None
        self.publication = publication  # Getter: actual publisher can appear later.
        self.read_d = read_d            # Actual D closure getter; never saved status.
        self.verified_stop = verified_stop
        self.limits = deepcopy(limits)
        if self.limits['max_state_age_s'] != .12:
            raise ValueError('ORIGINAL_CU_CURRENT_SOURCE_TTL_012_REQUIRED')
        self.identity = dict(session_id=camera.session, clock_basis='SIM_TIME', clock_epoch=0)
        self.previous_clock = None
        self.last_reason = 'WAIT_CURRENT_STOP_AND_COMPLETE_CAPTURE'
        self.creation_thread_ident = threading.get_ident()
        self.bound_native_code = dict(module=self.native_function.__module__,
            qualname=self.native_function.__qualname__,filename=self.native_code.co_filename,
            first_line=self.native_code.co_firstlineno,
            code_sha256=sha256(marshal.dumps(self.native_code)).hexdigest())
        self._diagnostics = {key:dict(failure_count=0,first_failure=None,last_call_result=None)
                             for key in ('source_clock','capture')}

    def _diagnostic_failure(self, boundary, exc, context):
        item = self._diagnostics[boundary]
        item['failure_count'] += 1
        item['last_call_result'] = 'RETURNED_NONE_UNCHANGED_REJECTION'
        if item['first_failure'] is None:
            item['first_failure'] = dict(reason=self.last_reason,
                exception_type=type(exc).__name__ if exc is not None else None,
                context=deepcopy(context),bound_identity=deepcopy(self.identity),
                bound_native_code=deepcopy(self.bound_native_code))

    def diagnostic_status(self):
        # Pure saved Python state only. Never call camera/clock/D/Kit here.
        return dict(schema='current-stop-provider-diagnostic/1',
            scope='FIRST_REJECTION_AND_COUNTERS_NOT_CURRENT_ADMISSION',
            original_last_reason=self.last_reason,bound_creation_thread_ident=self.creation_thread_ident,
            boundaries=deepcopy(self._diagnostics),SDK_READY=False,execution_allowed=False)

    def source_clock_provider(self):
        caller = threading.get_ident();main = threading.main_thread().ident
        context = dict(phase='MAIN_THREAD_CHECK',caller_thread_ident=caller,
            main_thread_ident=main,bound_creation_thread_ident=self.creation_thread_ident,
            native_read_attempted=False,native_read=None)
        if caller != main:
            self.last_reason = 'WAIT_MAIN_THREAD_NATIVE_CLOCK'
            self._diagnostic_failure('source_clock',None,context)
            return None  # Do not touch camera/Kit on a worker.
        start = time.monotonic();context['call_started_wall_s']=start
        native = None
        try:
            context['phase']='CAMERA_LIFECYCLE'
            closed = getattr(self.camera, 'capture_closed', False)
            context['camera_closed_type']=type(closed).__name__;context['camera_closed_repr']=repr(closed)
            if closed:
                raise ValueError('CURRENT_CAMERA_CLOSED')
            epoch = self.camera.source_epoch
            context['camera_epoch_type']=type(epoch).__name__;context['camera_epoch_repr']=repr(epoch)
            if type(epoch) is not int or epoch != self.identity['clock_epoch']:
                raise ValueError('CURRENT_CAMERA_EPOCH_CHANGED')
            session = self.camera.session
            context['camera_session_repr']=repr(session);context['bound_identity']=deepcopy(self.identity)
            if session != self.identity['session_id']:
                raise ValueError('CURRENT_CAMERA_SESSION_CHANGED')
            context['phase']='NATIVE_FUNCTION_BINDING'
            method = self.camera.native_stamp
            function = getattr(method, '__func__', method)
            context['function_same_as_bound']=function is self.native_function
            context['code_same_as_bound']=self.native_function.__code__ is self.native_code
            if (function is not self.native_function
                    or self.native_function.__code__ is not self.native_code):
                raise ValueError('CURRENT_NATIVE_STAMP_FUNCTION_CHANGED')
            context['phase']='NATIVE_STAMP_CALL';context['native_read_attempted']=True
            native = self.native_method()  # Original one native read inside this call.
            observed = time.monotonic();context['returned_wall_s']=observed
            # Only the fixed primitive native-clock fields already returned by
            # that read. Invalid/nonfinite values remain typed diagnostic text.
            def field(value):
                if type(value) in (str,int,bool,type(None)):return value
                if type(value) is float:return value if math.isfinite(value) else dict(nonfinite=repr(value))
                if type(value) in (list,tuple):return ([field(v) for v in value] if len(value)<=8 else dict(length=len(value),first8=[field(v) for v in value[:8]]))
                return dict(python_type=type(value).__name__)
            context['native_read'] = ({k:field(native[k]) for k in
                ('native_current_reference_time','native_simulation_time_s','native_physics_step_index','world_time_s','wall_monotonic_s')
                if k in native} if type(native) is dict else dict(python_type=type(native).__name__))
            context['phase']='FINITE_NATIVE_CLOCK'
            for key in ('native_simulation_time_s', 'world_time_s', 'wall_monotonic_s'):
                if type(native[key]) not in (int, float) or not math.isfinite(native[key]):
                    raise ValueError('FINITE_NATIVE_CLOCK_REQUIRED')
            context['phase']='RATIONAL_AND_CAUSAL_NATIVE_CLOCK'
            rational = native['native_current_reference_time']
            if (len(rational) != 2 or any(type(x) is not int for x in rational)
                    or rational[1] <= 0 or type(native['native_physics_step_index']) is not int
                    or native['native_physics_step_index'] < 0
                    or not start <= native['wall_monotonic_s'] <= observed):
                raise ValueError('NEW_CAUSAL_NATIVE_CLOCK_READ_REQUIRED')
            value = dict(schema=CLOCK, **self.identity, source_s=native['world_time_s'],
                         native_stamp=deepcopy(native), observed_wall_monotonic_s=observed)
            previous = self.previous_clock
            context['phase']='MONOTONIC_NATIVE_CLOCK'
            context['previous_source_s']=previous['source_s'] if previous is not None else None
            context['previous_native_stamp']=deepcopy(previous['native_stamp']) if previous is not None else None
            if previous is not None and (
                    value['source_s'] < previous['source_s']
                    or native['native_physics_step_index'] < previous['native_stamp']['native_physics_step_index']
                    or native['native_simulation_time_s'] < previous['native_stamp']['native_simulation_time_s']
                    or Fraction(*rational) < Fraction(*previous['native_stamp']['native_current_reference_time'])):
                raise ValueError('CURRENT_NATIVE_CLOCK_REVERSED')
            self.previous_clock = deepcopy(value)
            self._diagnostics['source_clock']['last_call_result']='RETURNED_ORIGINAL_CURRENT_CLOCK'
            return value
        except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
            self.last_reason = str(exc)
            self._diagnostic_failure('source_clock',exc,context)
            return None

    def _current(self, owner, accepted, now):
        pub = self.publication()
        read = self.read_d()
        if callable(read):
            if self.bound_read_d is None:
                self.bound_read_d = (read, read.__code__)
            elif read is not self.bound_read_d[0] or read.__code__ is not self.bound_read_d[1]:
                raise ValueError('CURRENT_D_READOUT_FUNCTION_CHANGED')
        current = read() if callable(read) else None
        if pub is None or not isinstance(current, dict) or current.get('schema') != LIVE:
            raise ValueError('WAIT_CURRENT_D_STOP_READOUT')
        if pub.accepted_ref is None or pub.status_ref is None or pub.terminal is None:
            raise ValueError('WAIT_ACTUAL_ACCEPTED_AND_VERIFIED_STOP')
        for k in IDENTITY:
            if owner[k] != now[k] or pub.identity[k] != owner[k]:
                raise ValueError('CURRENT_D_SOURCE_IDENTITY_CHANGED')
        if (any(accepted[k] != owner[k] for k in IDENTITY +
                ('execution_id', 'execution_version', 'goal_id', 'goal_version', 'replan_sequence'))
                or accepted['cancel_generation'] != 0 or owner['cancel_generation'] != 1
                or accepted['original_request'] != pub.request_ref or accepted['accepted_wire'] != pub.wire_ref):
            raise ValueError('ORIGINAL_ACCEPTED_GOAL_AND_CANCEL_LINEAGE_CHANGED')
        for k in GENERATIONS:
            if getattr(pub, k) != owner[k]:
                raise ValueError('CURRENT_D_EXECUTION_GENERATION_CHANGED:' + k)
        if (current['goal_id'] != owner['goal_id'] or current['goal_accepted'] is not True
                or current['terminal_status'] != 5 or current['terminal_error_code'] != 0
                or current['cancel_ack_goal_ids'] != [owner['goal_id']]
                or current['cancel_ack_return_code'] != 0
                or current['cancel_request_count'] != 1
                or current['mode'] != 'OBSTACLE_HOLD'
                or any(current[k] is not False for k in
                       ('user_stop_latched', 'failure_latched', 'outcome_unknown'))
                or current['command_counts'] != dict(active_command_count=0, pending_command_count=0,
                                                       pending_cancel_count=0)):
            raise ValueError('CURRENT_D_STOP_HOLD_COUNTS_OR_LATCH_CHANGED')
        if digest(current['current_context']) != digest(pub.context) or digest(accepted['binding']) != digest(pub.context):
            raise ValueError('CURRENT_A_WORLD_RESERVATION_CONTEXT_CHANGED')
        if pin(pub.request_ref['path']) != pub.request_ref or pin(pub.wire_ref['path']) != pub.wire_ref:
            raise ValueError('CURRENT_REQUEST_OR_WIRE_CHANGED')
        expected = dict(**{k:pub.request[k] for k in
                             ('a_context', 'reservation_binding', 'current_revision', 'world_revision', 'model_digest')},
                        model_manifest_sha256=pub.request['model_bundle']['manifest_sha256'],
                        original_goal=pub.request['goal'], active_wire_digest=digest(pub.wire))
        for k in CONTEXT:
            if digest(owner[k]) != digest(expected[k]) or digest(current[k]) != digest(expected[k]):
                raise ValueError('CURRENT_REQUEST_MODEL_OR_GOAL_CHANGED:' + k)
        if pub.accepted_ref != current['accepted_ref'] or pinned(pub.accepted_ref) != accepted:
            raise ValueError('CURRENT_ACCEPTED_SOURCE_CHANGED')
        status = pinned(pub.status_ref)
        if (status['error'] != CAUSE or status['conservative_stop_verified'] is not True
                or status['stop_verified'] is not True or status['holding_confirmed'] is not True
                or status['cancel_bound_uuid'] != owner['goal_id']
                or status['cancel_send_outcome_unknown'] is not False
                or status['cancel_request_count'] != 1):
            raise ValueError('ORIGINAL_VERIFIED_CONSERVATIVE_STOP_CHANGED')
        if (pub.terminal['goal_id'] != owner['goal_id'] or pub.terminal['status'] != 5
                or pub.terminal['error_code'] != 0):
            raise ValueError('CURRENT_D_TERMINAL_CHANGED')
        row = current['observation']
        controller = row['tracking']['controller_states'][-1]
        expected_joints = ['joint_' + str(i) for i in range(1, 7)]
        reference = controller['reference']
        if (controller['joint_names'] != expected_joints
                or not 0 <= now['source_s'] - controller['header_ns'] / 1e9 <= self.limits['max_state_age_s']
                or not controller['header_ns'] / 1e9 <= controller['received_world_time_s'] <= now['source_s']
                or any(reference[field] != owner['desired'][key] for field, key in
                       [('positions', 'q_rad'), ('velocities', 'v_rad_s'), ('accelerations', 'a_rad_s2')])):
            raise ValueError('CURRENT_NATIVE_HOLD_REFERENCE_CHANGED_OR_STALE')
        history = list(pub.history)
        if (not history or row['time_s'] != now['source_s'] or history[-1]['stamp_s'] != row['time_s']
                or row['contact_fingers'] != FINGERS):
            raise ValueError('CURRENT_MEASURED_STOP_SAMPLE_MISSING')
        window = [x for x in history if max(pub.terminal['source_s'], now['source_s'] - 1.) <= x['stamp_s'] <= now['source_s']]
        if (not window or window[-1]['stamp_s'] - window[0]['stamp_s'] < self.limits['min_stop_observation_s']
                or any(any(x['command_counts'].values()) or x['contact_fingers'] != FINGERS for x in window)):
            raise ValueError('CURRENT_STOP_HISTORY_HOLD_CHANGED')
        self.verified_stop([dict(time_s=x['stamp_s'], q_rad=x['q_rad'], grip_rad=x['grip_rad']) for x in window],
                           list(row['q_rad']) + [row['grip_rad']])
        return pub

    def capture_provider(self):
        if threading.get_ident() != threading.main_thread().ident:
            self.last_reason = 'WAIT_MAIN_THREAD_CURRENT_CAPTURE'
            self._diagnostic_failure('capture',None,dict(phase='MAIN_THREAD_CHECK',caller_thread_ident=threading.get_ident(),main_thread_ident=threading.main_thread().ident))
            return None
        try:
            before = self.source_clock_provider()
            if before is None:
                self._diagnostic_failure('capture',None,dict(phase='SOURCE_CLOCK_RETURNED_NONE'))
                return None
            pub = self.publication()
            if pub is None:
                raise ValueError('WAIT_ACTUAL_D_PUBLISHER')
            latest_path = pub.folder / 'latest.json'  # Discovery only, never a live clock.
            latest = json.loads(latest_path.read_text())
            frame_ref = latest['frame_ref']
            capture_path = Path(frame_ref['path']).parent / 'stopped_owner_capture.json'
            capture_ref = pin(capture_path)
            capture = pinned(capture_ref)
            if (capture['scope'] != 'SAME_ORIGINAL_CAPTURE_FOR_NONEXECUTABLE_STOP_OWNER'
                    or capture['recaptured'] is not False
                    or capture['frame_input'] != frame_ref or capture['owner_publication'] != latest['publication']):
                raise ValueError('WAIT_COMPLETE_SAME_CAPTURE_LINK')
            publication = pinned(capture['owner_publication'])
            if publication['owner_ref'] != latest['owner_ref'] or publication['owner_limits_ref'] != latest['owner_limits_ref']:
                raise ValueError('CAPTURE_OWNER_PARENT_CHANGED')
            if pinned(publication['owner_limits_ref']) != self.limits:
                raise ValueError('CURRENT_OWNER_LIMITS_CHANGED')
            frame = pinned(frame_ref)
            owner = pinned(publication['owner_ref'])
            if latest['accepted_ref'] != pub.accepted_ref:
                raise ValueError('CURRENT_ACCEPTED_REFERENCE_CHANGED')
            accepted = pinned(latest['accepted_ref'])
            state = pinned(latest['state_ref'])
            verify_state_capture(owner, state, frame, frame_ref)
            verified_proof = verify_original_stop_proof(owner, publication, latest, frame, frame_ref, pub)
            bundle = pinned(capture['selected_raw_bundle'])
            if (bundle['frame_seq'] != frame['frame_seq']
                    or bundle['source_stamp_s'] != frame['source_stamp_s']
                    or bundle['raw_preview']['session_id'] != frame['session_id']
                    or bundle['raw_preview']['source_stamp_s'] != frame['source_stamp_s']):
                raise ValueError('RAW_CAPTURE_SOURCE_IDENTITY_CHANGED')
            verified_raw = verify_raw(bundle, frame_ref)
            first_pub = self._current(owner, accepted, before)
            for item in verified_raw + verified_proof + [capture['owner_publication'], capture['selected_raw_bundle'],
                                        frame_ref, publication['owner_ref'], latest['state_ref'], latest['accepted_ref']]:
                if pin(item['path']) != item:
                    raise ValueError('CAPTURE_PARENT_CHANGED_BEFORE_RETURN')
            after = self.source_clock_provider()
            if after is None or first_pub is not self._current(owner, accepted, after):
                raise ValueError('CURRENT_D_OWNER_CHANGED_DURING_READ')
            for k in IDENTITY:
                if frame[k] != after[k]:
                    raise ValueError('CURRENT_CAPTURE_IDENTITY_CHANGED')
            if (not 0 <= after['source_s'] - frame['source_stamp_s'] <= self.limits['max_state_age_s']
                    or not 0 <= after['source_s'] - owner['state_stamp_s'] <= self.limits['max_state_age_s']
                    or owner['now_s'] > after['source_s']
                    or after['native_stamp']['native_physics_step_index'] < owner['state_sequence']):
                raise ValueError('WAIT_FRESH_CURRENT_CAPTURE_NOT_ARCHIVED_OWNER_NOW')
            if pub.folder != latest_path.parent or json.loads(latest_path.read_text()) != latest or pin(capture_path) != capture_ref:
                raise ValueError('SELECTED_CAPTURE_CHANGED_DURING_READ')
            self.last_reason = 'CURRENT_SOURCE_LINK_VERIFIED_INPUT_ONLY_NOT_SDK_OR_GEOMETRY_ADMISSION'
            self._diagnostics['capture']['last_call_result']='RETURNED_ORIGINAL_CURRENT_CAPTURE'
            return deepcopy(capture_ref)
        except (KeyError, TypeError, ValueError, OSError, RuntimeError, AttributeError, IndexError) as exc:
            self.last_reason = str(exc)
            self._diagnostic_failure('capture',exc,dict(phase='ORIGINAL_CAPTURE_VALIDATION'))
            return None
