"""Pinned conservative SIM STOP mapping only; never a live owner/provider.

No clock, ROS, SDK, FCL, state projection or file publication is performed.
The D's existing verifier remains the authority for STOP/holding/lifecycle.
"""
from copy import deepcopy
from pathlib import Path

import yaml
from plan_only import JOINTS, digest
from isaac_sim.real_execution.native_boundary import (
    _pinned_json, review_conservative_stop, sha,
)

PROFILE = 'CONSERVATIVE_FOREGROUND_STOP_SIM_OWNER_ONLY'
OWNER_OBSERVATIONS = 'D_OWNER_VERIFIED_REPORT_ONLY'
COMPUTE_GEOMETRY = 'COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF'
RAW_KEYS = ('session_id', 'clock_basis', 'clock_epoch', 'state_sequence',
            'q_rad', 'v_rad_s', 'a_rad_s2', 'grip_rad', 'attachment_tcp_to_block')


def _equal(left, right, reason):
    if digest(left) != digest(right):
        raise ValueError(reason)


def _sealed(value):
    result = deepcopy(value)
    result['digest'] = digest({k: v for k, v in result.items() if k != 'digest'})
    return result


def _verify_seal(value):
    _equal(value.get('digest'), digest({k: v for k, v in value.items() if k != 'digest'}),
           'CONSERVATIVE_PACKET_SEAL_CHANGED')


def _source(refs):
    owner = _pinned_json(refs['owner'])
    raw = _pinned_json(refs['state'])
    proof = _pinned_json(refs['proof'])
    accepted = _pinned_json(refs['accepted'])
    policy = _pinned_json(refs['policy'])
    _equal(owner['owner_limits_ref'], refs['policy'], 'CONSERVATIVE_POLICY_REF_CHANGED')
    _equal(owner['stop_verification'], refs['proof'], 'CONSERVATIVE_PROOF_REF_CHANGED')
    for key, name in (('state', 'current_state'), ('accepted', 'accepted'),
                      ('original_request', 'original_request'), ('accepted_wire', 'accepted_wire')):
        _equal(refs[key], proof['evidence'][name], 'CONSERVATIVE_SOURCE_REF_CHANGED:' + key)
    _verify_seal(raw)
    _equal(raw['digest'], owner['state_digest'], 'CONSERVATIVE_RAW_STATE_DIGEST_CHANGED')
    for key in RAW_KEYS:
        _equal(raw[key], owner[key], 'CONSERVATIVE_RAW_STATE_CHANGED:' + key)
    endpoint = raw['source_stamp_s']
    for stamp in (owner['state_stamp_s'], proof['state_stamp_s'], owner['stop_record']['samples'][-1]['stamp_s']):
        _equal(endpoint, stamp, 'CONSERVATIVE_ORIGINAL_ENDPOINT_CHANGED')
    if raw['source_kind'] != 'SIM_SAVED_SNAPSHOT':
        raise ValueError('CONSERVATIVE_SIM_SAVED_SOURCE_REQUIRED')
    if (raw['raw_observed_a_rad_s2'] is not None or
            raw['acceleration_method'] != 'ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE' or
            raw['acceleration_method'] != owner['stop_record']['acceleration_method']):
        raise ValueError('CONSERVATIVE_RAW_NULL_AND_DERIVED_A_REQUIRED')
    if accepted['scope'] != 'ACCEPTED_NATIVE_GOAL_BINDING':
        raise ValueError('CONSERVATIVE_ORIGINAL_ACCEPTED_GOAL_REQUIRED')
    for key in ('session_id', 'clock_basis', 'clock_epoch', 'execution_id', 'execution_version',
                'goal_id', 'goal_version', 'active_wire_digest', 'model_digest', 'model_manifest_sha256',
                'a_context', 'reservation_binding', 'current_revision', 'world_revision', 'replan_sequence'):
        _equal(accepted[key], owner[key], 'CONSERVATIVE_ACCEPTED_OWNER_CHANGED:' + key)
    _equal(accepted['original_request'], refs['original_request'], 'CONSERVATIVE_ORIGINAL_REQUEST_REF_CHANGED')
    _equal(accepted['accepted_wire'], refs['accepted_wire'], 'CONSERVATIVE_ACCEPTED_WIRE_REF_CHANGED')
    wire = _pinned_json(refs['accepted_wire'])
    _equal(digest(wire), owner['active_wire_digest'], 'CONSERVATIVE_ACCEPTED_WIRE_CHANGED')
    request_ref = refs['original_request']
    if sha(request_ref['path']) != request_ref['sha256']:
        raise ValueError('CONSERVATIVE_ORIGINAL_REQUEST_CHANGED')
    request = yaml.safe_load(Path(request_ref['path']).read_text())
    for key in ('a_context', 'reservation_binding', 'current_revision', 'world_revision', 'model_digest'):
        _equal(request[key], owner[key], 'CONSERVATIVE_ORIGINAL_REQUEST_ANCHOR_CHANGED:' + key)
    _equal(request['goal'], owner['original_goal'], 'CONSERVATIVE_ORIGINAL_GOAL_CHANGED')
    _equal(request['model_bundle']['manifest_sha256'], owner['model_manifest_sha256'],
           'CONSERVATIVE_ORIGINAL_MODEL_CHANGED')
    # Historical owner.now_s is used only by the original evidence verifier.
    # This call does not establish a current source clock or live admission.
    review_conservative_stop(owner, policy)
    for ref in refs.values():
        if sha(ref['path']) != ref['sha256']:
            raise ValueError('CONSERVATIVE_SOURCE_CHANGED_DURING_REVIEW')
    return owner, raw, proof, accepted, policy


def _state(refs, owner, raw, proof):
    result = deepcopy(raw)
    result.update(schema='stopped-robot-snapshot/0.1', joint_names=deepcopy(JOINTS), units='rad, seconds',
        owner_packet_profile=PROFILE, owner_evidence=deepcopy(refs['owner']),
        evidence_ref=refs['owner']['path'], stop_evidence=deepcopy(refs['proof']),
        stop_reason=owner['stop_record']['stop_reason'], cancel_generation=owner['cancel_generation'],
        stopped_verified=proof['stop_verified'], holding_confirmed=proof['holding_confirmed'],
        active_command_count=owner['active_command_count'], pending_command_count=owner['pending_command_count'],
        velocity_stamp_s=raw['source_stamp_s'], acceleration_stamp_s=raw['source_stamp_s'],
        stop_evidence_stamp_s=proof['state_stamp_s'], execution_allowed=False, hardware_execution_allowed=False,
        state_normalization=dict(scope='PINNED_CONSERVATIVE_STOP_FIELDS_NOT_CURRENT_OBSERVATION',
            source_refs=deepcopy(refs), raw_state_digest=raw['digest'], raw_PVA_unchanged=True,
            field_sources=dict(velocity_stamp_s='current_state.source_stamp_s',
                acceleration_stamp_s='current_state.source_stamp_s',
                stop_evidence_stamp_s='D_conservative_stop_verification.state_stamp_s'),
            execution_allowed=False))
    return _sealed(result)


def _limits(refs, policy):
    return dict(owner_packet_profile=PROFILE, stop_observation_mode=OWNER_OBSERVATIONS,
        initial_condition_mode='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE', geometry_observation_mode=COMPUTE_GEOMETRY,
        owner_review_limits=deepcopy(policy), owner_review_limits_evidence=deepcopy(refs['policy']),
        max_state_age_s=policy['max_state_age_s'], min_verified_stop_duration_s=policy['min_stop_observation_s'],
        max_abs_velocity_rad_s=None, max_abs_acceleration_rad_s2=None,
        max_camera_state_joint_error_rad=None, max_start_drift_rad=None)


def build_conservative_stop_packet(refs):
    """Return a sealed saved mapping and partial limits; missing LIVE inputs WAIT.

    No received timestamp or sensor/skew policy is invented. The original owner
    and accepted record retain their distinct state digests/cancel generations.
    """
    refs = deepcopy(refs)
    owner, raw, proof, accepted, policy = _source(refs)
    limits = _limits(refs, policy)
    control = {k: deepcopy(owner[k]) for k in ('session_id', 'clock_basis', 'clock_epoch', 'execution_id',
        'goal_id', 'goal_version', 'mode', 'user_stop_latched', 'failure_latched', 'outcome_unknown',
        'cancel_generation', 'replan_sequence')}
    return _sealed(dict(schema='conservative-stop-source-mapping/1.0',
        status='WAIT_CURRENT_PROVIDER_CLOCK_AND_COMPLETE_GEOMETRY_INPUTS',
        scope='SAVED_STOP_MAPPING_ONLY_NOT_LIVE_ADMISSION', state=_state(refs, owner, raw, proof),
        control=control, limits_delta=limits, source_owner_context=owner, original_accepted=accepted,
        source_refs=refs, current_clock=None, runtime_capture_ref=None, received_stamp_s=None,
        required_external_inputs=['actual current owner/capture provider and causal clock',
            'independently selected sensor/pose/world policy', 'fresh complete Depth and geometry proof'],
        SDK_READY=False, READY=False, execution_allowed=False, hardware_execution_allowed=False,
        automatic_resume=False))


def review_conservative_source_packet(state, owner, selected, policy_ref):
    """Exact signature used by CU CPU09's explicit profile branch."""
    _verify_seal(state)
    if state.get('owner_packet_profile') != PROFILE:
        raise ValueError('EXPLICIT_CONSERVATIVE_PACKET_PROFILE_REQUIRED')
    refs = state['state_normalization']['source_refs']
    actual, raw, proof, _, policy = _source(refs)
    _equal(owner, actual, 'CONSERVATIVE_SELECTED_OWNER_CHANGED')
    _equal(selected, policy, 'CONSERVATIVE_SELECTED_POLICY_CHANGED')
    _equal(policy_ref, refs['policy'], 'CONSERVATIVE_SELECTED_POLICY_REF_CHANGED')
    expected = _state(refs, actual, raw, proof)
    for key, value in expected.items():
        if key != 'digest':
            _equal(state[key], value, 'CONSERVATIVE_MAPPED_STATE_CHANGED:' + key)
    return deepcopy(actual)


def normalize_conservative_stop_state(state, limits, model, source_packet_ref):
    """Separate real-proof shape; never synthesize old observation.raw_PVA."""
    if (limits.get('owner_packet_profile') != PROFILE or
            limits.get('stop_observation_mode') != OWNER_OBSERVATIONS or
            limits.get('initial_condition_mode') != 'Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE' or
            limits.get('geometry_observation_mode') != COMPUTE_GEOMETRY):
        raise ValueError('EXPLICIT_CONSERVATIVE_NONEXECUTABLE_PROFILE_REQUIRED')
    packet = _pinned_json(source_packet_ref)
    _equal(packet['state'], state, 'CONSERVATIVE_STATE_NOT_PINNED_SOURCE_PACKET')
    owner = _pinned_json(state['owner_evidence'])
    review_conservative_source_packet(state, owner, limits['owner_review_limits'],
                                      limits['owner_review_limits_evidence'])
    refs = state['state_normalization']['source_refs']
    for key, value in _limits(refs, _pinned_json(refs['policy'])).items():
        _equal(limits[key], value, 'CONSERVATIVE_LIMIT_MAPPING_CHANGED:' + key)
    if (model['manifest_sha256'] != owner['model_manifest_sha256'] or
            sha(Path(model['bundle_path']) / 'MODEL_MANIFEST.json') != owner['model_manifest_sha256']):
        raise ValueError('CONSERVATIVE_NORMALIZATION_ORIGINAL_MODEL_CHANGED')
    if sha(source_packet_ref['path']) != source_packet_ref['sha256']:
        raise ValueError('CONSERVATIVE_SOURCE_PACKET_CHANGED_DURING_REVIEW')
    return deepcopy(state)
