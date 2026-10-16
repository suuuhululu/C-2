"""D's pre-SDK approval inputs; native receiver still owns publication/admission."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
import yaml
from plan_only import BINDING
from isaac_sim.real_execution.native_boundary import LIVE_IDENTITY
from held_geometry_inputs import nominal_definition


def pinned(ref):
    p=Path(ref['path'])
    if hashlib.sha256(p.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('PREPARED_SELECTION_PIN_CHANGED')
    return yaml.safe_load(p.read_text())


def approval_inputs(*,job_ref,anchor_ref,phase_ref,observation):
    job=pinned(job_ref);anchor=pinned(anchor_ref);prepared=pinned(job['cache_request']);phase=pinned(phase_ref)
    owner=observation['owner'];identity={k:owner[k] for k in LIVE_IDENTITY}
    if phase.get('scope')!='NATIVE_PREPARED_CALCULATION_BEFORE_SDK' or phase.get('job')!=job_ref or phase.get('SDK_started') is not False or phase.get('FCL_started') is not False:
        raise ValueError('PRE_SDK_SELECTION_REQUIRED_FAILED_OR_STARTED_JOB_NOT_ADMISSIBLE')
    if job['identity']!=identity or job['base_request']!=anchor_ref:raise ValueError('PREPARED_JOB_NOT_D_SELECTED_ORIGINAL_ANCHOR')
    if any(owner[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')) or owner['mode']!='OBSTACLE_HOLD' or owner['holding_confirmed'] is not True:
        raise ValueError('CURRENT_D_NORMAL_HOLD_REQUIRED')
    stable=[k for k in BINDING if k not in ('scene_digest','planning_request_digest')]
    if any(type(anchor[k]) is not type(prepared[k]) or anchor[k]!=prepared[k] for k in stable):raise ValueError('PREPARED_STABLE_A_ANCHOR_CHANGED')
    for key in ('a_context','reservation_binding','goal','model_bundle','trajectory_interpolation','motion_input_digest'):
        if anchor[key]!=prepared[key]:raise ValueError('PREPARED_ORIGINAL_TARGET_MODEL_RESERVATION_CHANGED:'+key)
    selected=anchor['planning_snapshot']['selected_slot_id']
    if selected!=prepared['planning_snapshot']['selected_slot_id'] or owner['selected_block_id']!=selected:raise ValueError('PREPARED_HELD_ID_CHANGED')
    def held(request):return next(o for o in request['planning_snapshot']['world_objects'] if o['id']==selected)
    if nominal_definition(held(anchor),anchor['model_bundle'])!=nominal_definition(held(prepared),prepared['model_bundle']):raise ValueError('PREPARED_HELD_BODY_STUD_PROFILE_CHANGED')
    if job['limits']['geometry_observation_mode']!='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF':raise ValueError('EXPLICIT_PREPARED_COMPUTATIONAL_MODE_REQUIRED')
    if job['limits']['owner_review_limits']!=pinned(owner['owner_review_limits']):raise ValueError('PREPARED_SELECTED_OWNER_LIMITS_CHANGED')
    pins={k:deepcopy(job[k]) for k in ('base_request','cache_request','cache_model_manifest','prepared_inputs','calculated_envelope','fcl_binary','fcl_library','source_owner','source_packet')}
    for ref in pins.values():
        if hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('PREPARED_EXACT_INPUT_PIN_CHANGED')
    return dict(scope='D_PREPARED_CALCULATION_APPROVAL_NOT_READY_OR_APPLY',original_anchor=deepcopy(anchor_ref),
        original_prepared_job=deepcopy(job_ref),before_SDK=deepcopy(phase_ref),identity=identity,
        prepared_geometry_pins=pins,prepared_attachment=deepcopy(prepared['attachment']),
        actual_current_attachment=deepcopy(owner['attachment_tcp_to_block']),limits=deepcopy(job['limits']),
        original_target=deepcopy(anchor['goal']),held_id=selected,READY=False,apply_allowed=False,
        requires_original_full_FCL=True,requires_current_geometry_and_encoded_proof=True)
