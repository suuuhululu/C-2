"""Measured raised grasp/landing/pad profile adapter for the existing held trial.

No guessed Z shifts, no motion commands, no reassignment of support responsibility.
"""
from copy import deepcopy
import math
import time


def pose(value,name):
    if not isinstance(value,list) or len(value)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in value):
        raise ValueError('MEASURED_POSE_REQUIRED:'+name)
    return value.copy()


def apply_profile(config,profile,*,support_confirmation=None):
    if profile.get('version')!='raised-grasp-press/1':raise ValueError('RAISED_PROFILE_VERSION_REQUIRED')
    if profile.get('reason') not in ('GRIPPER_COLLISION','GRIPPER_ACCESS'):
        raise ValueError('RAISED_PROFILE_ONLY_FOR_GRIPPER_ACCESS')
    if profile.get('pad_bottom_from_block_bottom_mm') != 15.:
        raise ValueError('RAISED_PAD_BOTTOM_15MM_REQUIRED')
    binding=profile.get('binding',{})
    target=config['alignment_target']['target']
    matches=[r for r in config['blocks'] if all(r.get(k)==binding.get(k) for k in ('color','brick_type','slot','span'))]
    if len(matches)!=1 or target!=profile.get('target') or not binding.get('step_id'):
        raise ValueError('RAISED_GRASP_TARGET_BINDING_MISMATCH')
    if config['connection']['tcp']!=profile.get('tcp') or config['connection']['tool']!=profile.get('tool'):
        raise ValueError('RAISED_TCP_TOOL_MISMATCH')
    for key in ('grasp_stability_verified','neighbor_clearance_verified','landing_support_verified','pad_contact_verified'):
        if profile.get(key) is not True:raise ValueError('RAISED_PHYSICAL_CHECK_REQUIRED:'+key)
    if not isinstance(profile.get('human_support_required'),bool):raise ValueError('EXPLICIT_SUPPORT_REQUIREMENT_REQUIRED')
    if profile['human_support_required']:
        if not support_confirmation or support_confirmation.get('step_id')!=binding['step_id'] or support_confirmation.get('ready') is not True or not support_confirmation.get('request_id') or support_confirmation.get('request_id')!=binding.get('support_request_id') or type(support_confirmation.get('expires_at_unix_s')) not in (int,float) or not math.isfinite(support_confirmation['expires_at_unix_s']) or support_confirmation['expires_at_unix_s']<=time.time():
            raise ValueError('HUMAN_SUPPORT_READY_REQUIRED')
    if not isinstance(profile.get('measurement_ref'),str) or not profile['measurement_ref']:
        raise ValueError('RAISED_MEASUREMENT_REFERENCE_REQUIRED')
    pickup=pose(profile.get('pickup_pose'),'pickup_pose')
    landing=pose(profile.get('landing_pose'),'landing_pose')
    pad=pose(profile.get('pad_contact_pose'),'pad_contact_pose')
    # Retain validated block orientation. A rotated grasp requires separate commissioning.
    row=matches[0]
    if max(abs(a-b) for a,b in zip(pickup[3:],row['pickup_pose'][3:]))>.05 or max(abs(a-b) for a,b in zip(landing[3:],pickup[3:]))>.05:
        raise ValueError('RAISED_EXISTING_GRASP_ORIENTATION_REQUIRED')
    if math.dist(pickup[:2],row['pickup_pose'][:2])>.05 or pickup[2]<=row['pickup_pose'][2]:
        raise ValueError('RAISED_PICKUP_MUST_BE_HIGHER_AT_SAME_XY')
    if math.dist(landing[:2],config['assembly_target_xy'])>.05:
        raise ValueError('RAISED_LANDING_TARGET_XY_MISMATCH')
    if math.dist(pad[:2],landing[:2])>2.:
        raise ValueError('PAD_CONTACT_OUTSIDE_TARGET')
    if max(pickup[2],landing[2],pad[2]+10.)>=config['pickup_clearance_z_mm']:
        raise ValueError('RAISED_POSES_REQUIRE_TRANSPORT_CLEARANCE')
    output=deepcopy(config)
    outrow=next(r for r in output['blocks'] if all(r.get(k)==binding.get(k) for k in ('color','brick_type','slot','span')))
    outrow.update(pickup_pose=pickup,pose_source=profile['measurement_ref'])
    # Existing pixel mapping was registered for the old grasp/view; do not reuse.
    outrow.pop('center_mapping',None)
    output['alignment_target']['placement_tcp_reference']=landing
    output['alignment_target']['current_grasp_relation_verified']=True
    output['alignment_approach_z_mm']=landing[2]+output['alignment_target']['clearance_mm']
    if output['alignment_approach_z_mm']>=output['pickup_clearance_z_mm']:
        raise ValueError('RAISED_APPROACH_EXCEEDS_TRANSPORT')
    output['integrated_pad_contact_pose']=pad
    output['raised_grasp_press']=dict(binding=deepcopy(binding),measurement_ref=profile['measurement_ref'],
        human_support_required=profile['human_support_required'],support_confirmation=deepcopy(support_confirmation),
        reason=profile['reason'],assembly_completion=False)
    return output


def require_landing_before_release(config,seating_result):
    state=config.get('raised_grasp_press')
    if state and state['human_support_required']:
        receipt=state.get('support_confirmation') or {}
        if receipt.get('ready') is not True or receipt.get('expires_at_unix_s',0)<=time.time():
            raise RuntimeError('HUMAN_SUPPORT_READY_REQUIRED_BEFORE_RELEASE')
    if state and (not seating_result or seating_result.get('status')!='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED'):
        raise RuntimeError('RAISED_FORCE_STOP_IS_NOT_LANDING_NO_RELEASE_NO_PRESS')


def run_sequence(config,operations,record):
    """Dependency-injected unit/component seam; callbacks retain existing device guards.

    Caller supplies existing pickup/transfer/align/insert/release/pad-press functions.
    Visual landing confirmation is mandatory before releasing an unfastened block.
    """
    if not config.get('raised_grasp_press'):raise ValueError('RAISED_PROFILE_REQUIRED')
    state=config['raised_grasp_press']
    if state['human_support_required'] and not operations['support_ready'](state['binding']):
        record('HUMAN_SUPPORT_REQUEST',state['binding'])
        return dict(status='WAITING_HUMAN_SUPPORT',assembly_completion=False)
    try:
        for name in ('pickup','transfer','align'):operations[name](config)
        landed=operations['insert'](config)
        require_landing_before_release(config,landed)
        if operations['confirm_landing'](landed) is not True:
            raise RuntimeError('LANDING_CONFIRMATION_REQUIRED')
        if state['human_support_required'] and not operations['support_ready'](state['binding']):
            raise RuntimeError('HUMAN_SUPPORT_NOT_READY_BEFORE_RELEASE')
        operations['release'](config)
        operations['retract_and_close'](config)
        result=operations['press_and_rise'](config)
        record('RAISED_PRESS_TRIAL_RESULT',dict(press=result,assembly_completion=False))
        return dict(status='PRESS_TRIAL_FINISHED',press=result,assembly_completion=False)
    except BaseException:
        operations['stop']();raise
