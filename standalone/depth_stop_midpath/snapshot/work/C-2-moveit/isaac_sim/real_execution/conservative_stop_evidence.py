"""File-only raw conservative STOP evidence export, never CU admission.

The single D supplies measured/sealed state, lifecycle refs and versions.
This function samples no clock, derives no acceleration or geometry, and
changes no command/state fields. Only the verification receipt is added.
"""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import json
from math import isfinite
import yaml

from .native_boundary import (_pinned_json, _exclusive_json, LIVE_IDENTITY,
                              review_conservative_stop)
from .preflight import digest


CAUSE = 'FRESH_FOREGROUND_CONSERVATIVE_STOP'
PROOF_SCOPE = 'VERIFIED_D_CONSERVATIVE_FOREGROUND_STOP_AND_HOLDING_NOT_RESUME_APPROVAL'


def build_conservative_stop_owner_evidence(folder, owner, limits, *, evidence,
        accepted_ref, original_request_ref, dispatch_ref, current_state_ref,
        frame_ref, accepted_wire_ref, observation_scope):
    """Validate supplied raw STOP and publish a non-executable owner ref.

    ``owner`` already contains the original cause, stop_record, current state,
    desired-reference association, identity/version/A/reservation/model fields.
    ``evidence`` is the D's five original or explicitly derived/pinned verdicts:
    cancel_ack, terminal_result, command_counts, holding, controller_stop.
    ``current_state_ref`` is a sealed SIM snapshot tied to ``frame_ref``'s
    actual q/TF tick, with raw/derived acceleration meanings kept separate.
    Archive scope is historical evidence only, never a current owner claim.
    """
    if observation_scope not in ('ARCHIVED_CPU_STOP_EVIDENCE', 'CURRENT_D_STOP_OBSERVATION_EXPORT_ONLY'):
        raise ValueError('EXPLICIT_NONEXECUTABLE_STOP_EXPORT_SCOPE_REQUIRED')
    if 'stop_verification' in owner:
        raise ValueError('FRESH_STOP_VERIFICATION_EXPORT_REQUIRED')
    value = deepcopy(owner)
    record = value['stop_record']
    if record['stop_reason'] != CAUSE:
        raise ValueError('ORIGINAL_CONSERVATIVE_CAUSE_REQUIRED')
    accepted = _pinned_json(accepted_ref)
    wire = _pinned_json(accepted_wire_ref)
    if digest(wire) != value['active_wire_digest']:
        raise ValueError('ACCEPTED_TYPED_WIRE_CHANGED')
    request_path = Path(original_request_ref['path'])
    if sha256(request_path.read_bytes()).hexdigest() != original_request_ref['sha256']:
        raise ValueError('ORIGINAL_REQUEST_CHANGED')
    request = yaml.safe_load(request_path.read_text())
    dispatch = _pinned_json(dispatch_ref)
    state = _pinned_json(current_state_ref)
    frame = _pinned_json(frame_ref)
    if accepted.get('scope') != 'ACCEPTED_NATIVE_GOAL_BINDING' or accepted.get('original_request') != original_request_ref:
        raise ValueError('ACCEPTED_ORIGINAL_REQUEST_LINK_REQUIRED')
    for key in ('session_id', 'clock_basis', 'clock_epoch', 'goal_id', 'goal_version',
                'active_wire_digest', 'model_digest'):
        if type(accepted[key]) is not type(value[key]) or accepted[key] != value[key]:
            raise ValueError('ACCEPTED_STOP_OWNER_CHANGED:' + key)
    for key in ('a_context', 'reservation_binding', 'current_revision', 'world_revision', 'model_digest'):
        if digest(value[key]) != digest(request[key]):
            raise ValueError('ORIGINAL_REQUEST_ANCHOR_CHANGED:' + key)
    if (value['original_goal'] != request['goal'] or
            value['model_manifest_sha256'] != request['model_bundle']['manifest_sha256']):
        raise ValueError('ORIGINAL_GOAL_OR_MODEL_CHANGED')
    if (dispatch.get('scope') != 'ISOLATED_SIM_CONSERVATIVE_FOREGROUND_STOP' or
            dispatch.get('decision') != 'SCOPED_CANCEL_CALL_RETURNED' or
            dispatch.get('cancel_request_issued') is not True or
            dispatch.get('bound_goal_uuid') != value['goal_id'] or
            dispatch.get('active_wire_digest') != value['active_wire_digest']):
        raise ValueError('SAME_UUID_CONSERVATIVE_DISPATCH_REQUIRED')
    if (state.get('source_kind') != 'SIM_SAVED_SNAPSHOT' or
            state.get('frame_input_ref') != frame_ref or
            state.get('digest') != digest({k:v for k,v in state.items() if k != 'digest'}) or
            value['state_digest'] != state['digest']):
        raise ValueError('SEALED_ORIGINAL_STATE_FRAME_REQUIRED')
    for key in ('session_id', 'clock_basis', 'clock_epoch', 'state_sequence',
                'q_rad', 'v_rad_s', 'a_rad_s2', 'grip_rad', 'attachment_tcp_to_block'):
        if digest(state[key]) != digest(value[key]):
            raise ValueError('RAW_STOP_STATE_CHANGED:' + key)
    if (state['source_stamp_s'] != value['state_stamp_s'] or
            state['source_stamp_s'] != frame['robot_state_stamp_s'] or
            frame['transform_stamp_s'] != frame['robot_state_stamp_s']):
        raise ValueError('RAW_STATE_NOT_FRAME_QTF_SOURCE_TICK')
    for key in ('session_id', 'clock_basis', 'clock_epoch', 'q_rad', 'grip_rad', 'attachment_tcp_to_block'):
        if digest(frame[key]) != digest(value[key]):
            raise ValueError('SOURCE_FRAME_OWNER_CHANGED:' + key)
    association = frame['source_association']
    if association.get('same_tick_verified') is not True or association.get('physical_source_pair_verified') is not True:
        raise ValueError('ACTUAL_FRAME_QTF_ASSOCIATION_REQUIRED')
    source_refs = frame['source_refs']
    if not source_refs:
        raise ValueError('ORIGINAL_FRAME_SOURCE_REFS_REQUIRED')
    for source in source_refs:
        if sha256(Path(source['path']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('FRAME_SOURCE_PARENT_CHANGED')
    state_sources = [r for r in source_refs if Path(r['path']).name == 'source_state.json']
    if len(state_sources) != 1:
        raise ValueError('ORIGINAL_RENDER_QTF_STATE_REF_REQUIRED')
    render_source = _pinned_json(state_sources[0])['source']
    for key in ('q_rad', 'grip_rad', 'attachment_tcp_to_block', 'T_world_base', 'T_base_tool', 'T_world_camera'):
        if digest(render_source[key]) != digest(frame[key]) or digest(association[key]) != digest(frame[key]):
            raise ValueError('ORIGINAL_RENDER_QTF_VALUE_CHANGED:' + key)
    if (frame['frame_seq'] != value['snapshot_version'] or
            sha256(json.dumps(frame, sort_keys=True, allow_nan=False).encode()).hexdigest() != value['snapshot_digest']):
        raise ValueError('RAW_FRAME_SNAPSHOT_IDENTITY_CHANGED')
    if ('raw_observed_a_rad_s2' not in state or
            state['raw_observed_a_rad_s2'] is None and
            state.get('acceleration_method') != 'ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE'):
        raise ValueError('EXPLICIT_RAW_NULL_VS_DERIVED_ACCELERATION_REQUIRED')
    raw_a = state['raw_observed_a_rad_s2']
    if raw_a is not None and (not isinstance(raw_a, list) or len(raw_a) != 6 or
            any(type(v) not in (int, float) or not isfinite(v) for v in raw_a)):
        raise ValueError('FINITE_SIX_RAW_ACCELERATIONS_OR_EXPLICIT_NULL_REQUIRED')
    if record['acceleration_method'] != state.get('acceleration_method'):
        raise ValueError('RAW_STOP_ACCELERATION_PROVENANCE_CHANGED')
    controller = _pinned_json(evidence['controller_stop'])
    held = _pinned_json(evidence['holding'])
    # The original common verifier reads every evidence SHA again and checks
    # UUID ACK/CANCELED/counts/holding/current reference-clock association.
    proof = dict(scope=PROOF_SCOPE, identity={k:value[k] for k in LIVE_IDENTITY},
        stop_record_digest=record['record_digest'], samples_digest=digest(record['samples']),
        state_stamp_s=value['state_stamp_s'], stop_verified=controller['stop_verified'],
        holding_confirmed=held['holding_confirmed'], verification_method=controller['verification_method'],
        evidence=dict(evidence, accepted=accepted_ref, original_request=original_request_ref,
                      dispatch=dispatch_ref, current_state=current_state_ref, frame=frame_ref,
                      accepted_wire=accepted_wire_ref))
    proof['evidence'].update({'frame_source_'+str(i):r for i,r in enumerate(source_refs)})
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    value['stop_verification'] = _exclusive_json(folder/'D_conservative_stop_verification.json', proof)
    observation_report = {}
    review_conservative_stop(value, limits, observation_report=observation_report)
    owner_ref = _exclusive_json(folder/'owner.json', value)
    return dict(status='RAW_CONSERVATIVE_STOP_OWNER_VERIFIED_WAIT_OBSTACLE_GEOMETRY',
        owner_ref=owner_ref, stop_verification_ref=value['stop_verification'],
        observation_scope=observation_scope, snapshot_digest_scope='RAW_QTF_FRAME_NOT_OCCUPIED_OBSTACLE_VOLUME',
        observation_report=observation_report, SDK_READY=False, READY=False,
        apply_allowed=False, execution_allowed=False, hardware_execution_allowed=False,
        automatic_resume=False)
