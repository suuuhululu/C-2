"""Finite-horizon SIM motion envelopes, conditional on explicit sensor priors.

No future pose oracle: full hidden-volume/error/speed bounds are conservative.
An unchanged original planning scene may cover newer observations; its source,
geometry and expiry never change. This module grants no execution authority.
"""
import time
from copy import deepcopy
import numpy as np
from plan_only import digest,checked_pose

LIVE_SCOPE='LIVE_DYNAMIC_SIM_CONDITIONAL_ENVELOPE'
IDENTITY=('session_id','clock_basis','clock_epoch','execution_id','goal_id','goal_version','cancel_generation','replan_sequence')
POLICY=('max_occlusion_s','max_latest_observation_age_s','max_trajectory_duration_s',
        'apply_stop_margin_s','max_sensor_to_apply_wall_s')
COMPUTE_GEOMETRY='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF'
STATIC_SCENE='STATIC_OBSTACLE'
DYNAMIC_SCENE='DYNAMIC_OBSTACLE'


def scene_motion_kind(value):
    kind=value.get('live_scene_motion_kind',DYNAMIC_SCENE)
    if kind not in (STATIC_SCENE,DYNAMIC_SCENE):raise ValueError('UNKNOWN_LIVE_SCENE_MOTION_KIND')
    return kind


def live_motion_assumption(frame,pose,prior,projection_digest=None):
    """Conditional SIM scenario assumption, never a GT pose/shape estimator."""
    kind=scene_motion_kind(prior);speed=float(prior['max_speed_m_s'])
    if not np.isfinite(speed) or speed<0:raise ValueError('FINITE_NONNEGATIVE_MOTION_BOUND_REQUIRED')
    if (kind==DYNAMIC_SCENE and speed<=0) or (kind==STATIC_SCENE and speed!=0):
        raise ValueError('SCENE_MOTION_KIND_SPEED_MISMATCH')
    if 'live_scene_motion_kind' not in prior:return None  # Existing dynamic representation unchanged.
    revision=prior['world_revision']
    if type(revision) is not int or revision<0:raise ValueError('EXPLICIT_SCENE_WORLD_REVISION_REQUIRED')
    if any(value.get('live_scene_motion_kind')!=kind or type(value.get('world_revision')) is not int or
            value['world_revision']!=revision for value in (frame,pose)):
        raise ValueError('LIVE_SOURCE_SCENE_MODE_OR_WORLD_REVISION_CHANGED')
    if not isinstance(projection_digest,str) or not projection_digest:raise ValueError('SCENE_MOTION_PROJECTION_BINDING_REQUIRED')
    assumption=None
    if kind==STATIC_SCENE:
        from prepare_cpu_model import file_hash
        from pathlib import Path
        assumption=prior['static_scene_assumption']
        if (frame['source_kind']!='SIM_DEPTH' or prior.get('usage_scope')!=LIVE_SCOPE or
                assumption['scope']!='DECLARED_CURRENT_SIM_FIXED_WORLD_SOURCE_NOT_REAL_OR_GT_POSE' or
                assumption['source_session_id']!=frame['session_id'] or assumption['clock_epoch']!=frame['clock_epoch'] or
                assumption['obstacle_id']!=prior['obstacle_id'] or assumption['world_revision']!=revision or
                assumption['motion_disabled'] is not True or assumption['fixed_world_geometry'] is not True):
            raise ValueError('CURRENT_SIM_STATIC_SCENARIO_ASSUMPTION_REQUIRED')
        source=assumption['scenario_source']
        if file_hash(Path(source['path']))!=source['sha256']:raise ValueError('STATIC_SCENARIO_SOURCE_CHANGED')
    return dict(live_scene_motion_kind=kind,world_revision=revision,
        scene_motion_assumption_digest=digest(dict(kind=kind,world_revision=revision,assumption=assumption)),
        projection_scene_binding=dict(frame_digest=digest(frame),projection_digest=projection_digest,
            frame_seq=frame['frame_seq'],source_stamp_s=frame['source_stamp_s']))


def computational_geometry(limits):
    mode=limits.get('geometry_observation_mode','EXACT_CALCULATED_GEOMETRY')
    if mode not in ('EXACT_CALCULATED_GEOMETRY',COMPUTE_GEOMETRY):
        raise ValueError('UNKNOWN_GEOMETRY_OBSERVATION_MODE')
    return mode==COMPUTE_GEOMETRY


def geometry_context_review(original,latest,*,computation_only=False):
    """Per-frame masks are already replayed with their own actual transforms.

    Only these two observation values may differ across validated frames.
    Unknown context fields and changed solid definitions are never ignored.
    """
    if not computation_only:
        if latest!=original:raise ValueError('LATEST_DEPTH_SOURCE_OR_MODEL_CHANGED:geometry_context')
        return dict(changed=False,current_geometry_proof_required=False)
    from sim_utils import rigid
    if any(set(value)!={'held_geometry','grip_rad','attachment'} for value in (original,latest)):
        raise ValueError('EXPLICIT_HELD_GEOMETRY_CONTEXT_FIELDS_REQUIRED')
    if original['held_geometry']!=latest['held_geometry']:
        raise ValueError('HELD_SHAPE_OR_ID_CHANGED_NEW_REQUEST_REQUIRED')
    if set(original['held_geometry'])!={'id','size_m','studs','block'}:
        raise ValueError('COMPLETE_HELD_SOLID_DEFINITION_REQUIRED')
    for value in (original,latest):
        if type(value['grip_rad']) not in (float,int) or not np.isfinite(value['grip_rad']):
            raise ValueError('FINITE_ACTUAL_GRIP_REQUIRED')
        rigid(value['attachment'])
    return dict(changed=original!=latest,calculated=deepcopy(original),observed=deepcopy(latest),
        current_geometry_proof_required=True,apply_allowed=False,
        status='COMPUTATION_ONLY_CURRENT_GEOMETRY_PROOF_REQUIRED')


def bound_metadata(frame,pose,prior,points,pixels,shape,*,range_m,fk_error,projection_digest=None):
    from depth_obstacle_envelope import bounded_geometry
    if prior.get('usage_scope')!=LIVE_SCOPE:return None
    if frame['source_kind']!='SIM_DEPTH' or pose['time_sync_scope']!='DYNAMIC_SOURCE_STAMP_VERIFIED':
        raise ValueError('LIVE_BOUND_REQUIRES_ACTUAL_SOURCE_TICK_NOT_FROZEN_ARCHIVE')
    motion=live_motion_assumption(frame,pose,prior,projection_digest)
    values=np.asarray([prior[k] for k in POLICY],float)
    if not np.isfinite(values).all() or np.any(values<=0):raise ValueError('EXPLICIT_POSITIVE_DYNAMIC_PRIOR_REQUIRED')
    if prior['max_latest_observation_age_s']>prior['max_occlusion_s']:
        raise ValueError('OBSERVATION_AGE_EXCEEDS_OCCLUSION_BUDGET')
    if prior['max_trajectory_duration_s']+prior['apply_stop_margin_s']>=prior['max_sensor_to_use_delay_s']:
        raise ValueError('DYNAMIC_HORIZON_HAS_NO_COMPUTE_APPLY_BUDGET')
    wall=float(frame['observation_wall_monotonic_s'])
    if not np.isfinite(wall) or wall<0:raise ValueError('SAME_HOST_MONOTONIC_OBSERVATION_REQUIRED')
    # Recompute source-time hidden volume; don't subtract a guessed margin
    # from an intersection of per-point boxes.
    centre,size,_=bounded_geometry(points,pixels,shape,dict(prior,max_speed_m_s=0.),range_m=range_m,fk_error=fk_error,age_s=0.)
    result=dict(scope=LIVE_SCOPE,policy={k:prior[k] for k in POLICY},source_tick_evidence=pose['source_tick_evidence'],
        clock_epoch=frame['clock_epoch'],
        source_box_min_m=(centre-size/2).tolist(),source_box_max_m=(centre+size/2).tolist(),
        observation_wall_monotonic_s=wall,
        scope_limits='SINGLE_DECLARED_SIM_OBJECT_SPEED_SIZE_ERROR_PRIORS_NOT_REAL_OR_WORLD_CLEAR')
    if motion is not None:result.update(motion)
    return result


def online_contract(request,inputs):
    bound=inputs['obstacles'].get('depth_bound',{})
    live=bound.get('online_motion')
    if live is None:return None
    from bounded_sim_evidence import pinned_json
    owner=pinned_json(inputs['state']['owner_evidence']);owner=owner.get('owner_context',owner)
    state=request['planning_snapshot']
    fixed=[o for o in state['world_objects'] if o['id']!=state['selected_slot_id'] and not o['id'].startswith('Dynamic_')]
    result=dict(scope=LIVE_SCOPE,identity={k:owner[k] for k in IDENTITY},bound_digest=bound['digest'],
        policy=live['policy'],obstacle_id=bound['geometry']['id'],valid_until_s=bound['valid_until_s'],
        static_world_digest=digest(sorted(fixed,key=lambda o:o['id'])),model_digest=request['model_digest'],
        observation_wall_monotonic_s=live['observation_wall_monotonic_s'])
    if 'live_scene_motion_kind' in bound['assumptions']:
        if (inputs['limits'].get('live_scene_motion_kind')!=live['live_scene_motion_kind'] or
                type(inputs['limits'].get('world_revision')) is not int or type(request['world_revision']) is not int or
                inputs['limits'].get('world_revision')!=live['world_revision'] or request['world_revision']!=live['world_revision']):
            raise ValueError('OWNER_SELECTED_SCENE_MOTION_OR_WORLD_REVISION_REQUIRED')
        result.update({key:live[key] for key in ('live_scene_motion_kind','world_revision','scene_motion_assumption_digest')})
    from dynamic_cumotion_inputs import owner_observations
    if owner_observations(inputs['limits']):result['static_world_shape_digest']=world_shape_digest(fixed)
    if 'planner_box_enclosure' in inputs['obstacles']:
        from depth_obstacle_envelope import planner_box_projection
        geometry,proof=planner_box_projection(bound,inputs['limits']['planner_box_representation'])
        actual=next(obj for obj in state['world_objects'] if obj['id']==geometry['id'])
        actual={key:value for key,value in actual.items() if key!='world_pose'}
        if inputs['obstacles']['objects']!=[geometry] or actual!=geometry or inputs['obstacles']['planner_box_enclosure']!=proof:
            raise ValueError('OUTWARD_PLANNER_GEOMETRY_NOT_BOUND_TO_REQUEST')
        result['planner_box_enclosure']=proof
    return result


def world_shape_digest(objects):
    return digest(sorted(({k:v for k,v in obj.items() if k not in ('pose','world_pose','geometry_evidence_ref')}
        for obj in objects),key=lambda obj:obj['id']))


def current_owner_world_metadata(base,packet,owner,contract):
    """Derive summaries from pinned native records, never from calculated poses.

    This is the explicitly controlled single-cube SIM trial. Unknown objects,
    changed topology/model/context reject. No GT cube pose enters planning.
    """
    from bounded_sim_evidence import pinned_json
    actual_owner=pinned_json(packet['state']['owner_evidence']);actual_owner=actual_owner.get('owner_context',actual_owner)
    if actual_owner!=owner:raise ValueError('WORLD_METADATA_NOT_PINNED_CURRENT_OWNER')
    if (owner['source_kind']!='SIM_OWNER_RECORD' or owner['world_observation_stamp_s']!=owner['state_stamp_s'] or
            owner['model_manifest_sha256']!=base['model_bundle']['manifest_sha256'] or
            owner['a_context']!=base['a_context'] or owner['reservation_binding']!=base['reservation_binding']):
        raise ValueError('CURRENT_WORLD_MODEL_A_OR_SOURCE_CHANGED')
    objects=owner['world_objects'];actual={obj['id']:obj for obj in objects}
    physical=[obj for obj in base['planning_snapshot']['world_objects'] if not
        (obj['id'].startswith('Dynamic_') and obj['role']=='OTHER_OBSTACLE')]
    ids={obj['id'] for obj in physical}
    if len(actual)!=len(objects) or set(actual)-ids!={'PathBlockingStimulus'} or ids-set(actual):
        raise ValueError('CURRENT_WORLD_UNKNOWN_OR_MISSING_OBJECT')
    bound=packet['latest_depth_bound'];prior=bound['assumptions']
    if (scene_motion_kind(prior)!=STATIC_SCENE or prior['static_scene_assumption']['scope']!=
            'DECLARED_CURRENT_SIM_FIXED_WORLD_SOURCE_NOT_REAL_OR_GT_POSE' or
            actual['PathBlockingStimulus']['size_m']!=prior['size_upper_m']):
        raise ValueError('EXPLICIT_SINGLE_STATIC_SIM_OBJECT_REQUIRED')
    fixed=[actual[oid] for oid in ids if oid!=base['planning_snapshot']['selected_slot_id']]
    shape=world_shape_digest(fixed)
    if shape!=contract['static_world_shape_digest']:raise ValueError('CURRENT_WORLD_SHAPE_OR_TOPOLOGY_CHANGED')
    result=dict(static_world_digest=digest(sorted(fixed,key=lambda obj:obj['id'])),model_digest=base['model_digest'],
        dynamic_inventory_complete=True,observed_dynamic_ids=[bound['geometry']['id']],occluded=False)
    for key,value in result.items():
        if key in packet and packet[key]!=value:raise ValueError('CURRENT_RAW_WORLD_SUMMARY_CONFLICT:'+key)
    return result,dict(owner_evidence=packet['state']['owner_evidence'],source_stamp_s=owner['world_observation_stamp_s'],
        shape_digest=shape,current_world_digest=result['static_world_digest'],calculated_world_digest=contract['static_world_digest'],
        poses_changed=result['static_world_digest']!=contract['static_world_digest'],original_scene_modified=False,
        inventory_scope='DECLARED_SINGLE_SIM_OBJECT_AND_COMPLETE_KNOWN_NATIVE_WORLD_NOT_WORLD_CLEAR',
        current_full_world_geometry_FCL_required=True,apply_allowed=False)


def fixed_object_observation_intersection(original,latest):
    """O⊆E0 and O⊆E1 for the same audited fixed object imply O⊆E0∩E1.

    Bounds stay immutable. This does not apply to moving objects, other source
    epochs or changed hypotheses. No GT position is read by this operation.
    """
    from bounded_sim_evidence import pinned_json
    refs=[]
    for bound in (original,latest):
        prior=bound['assumptions']
        if scene_motion_kind(prior)!=STATIC_SCENE or prior['max_speed_m_s']!=0:
            raise ValueError('FIXED_OBJECT_OBSERVATION_PROOF_REQUIRED')
        basis=pinned_json(prior['basis_evidence']);ref=basis['source_motion_audit'];audit=pinned_json(ref)
        if (audit['scope']!='FIXED_WORLD_AUDIT_NO_PLANNER_COORDINATES' or audit['constant_position_verified'] is not True or
                type(audit['samples']) is not int or audit['samples']<2 or
                audit['scenario_source']!=prior['static_scene_assumption']['scenario_source'] or
                not audit['first_stamp_s']<=original['source_stamp_s']<=bound['source_stamp_s']<=audit['last_stamp_s']):
            raise ValueError('SAME_FIXED_OBJECT_SOURCE_INTERVAL_NOT_AUDITED')
        refs.append(ref)
    low=np.maximum(original['online_motion']['source_box_min_m'],latest['online_motion']['source_box_min_m'])
    high=np.minimum(original['online_motion']['source_box_max_m'],latest['online_motion']['source_box_max_m'])
    if np.any(low>high):raise ValueError('FIXED_OBJECT_OBSERVATIONS_CONTRADICTORY_REPLAN_REQUIRED')
    return low,high,dict(scope='INTERSECTION_OF_TWO_INDEPENDENT_FULL_OBJECT_BOUNDS_FOR_SAME_AUDITED_FIXED_OBJECT',
        fixed_source_audits=refs,proof='O subset E0 and O subset E1 and fixed O imply O subset intersection(E0,E1)',
        original_and_latest_bounds_modified=False,GT_pose_used=False,apply_allowed=False)


def contained_motion(original,latest,*,now_s,required_until_s,computation_only=False,planning_geometry=None):
    """New source volume plus all motion to the required horizon must fit.

    Exact AABB containment is conservative; no collision margin is reduced to
    make a result fit. Original geometry/TTL and receipt remain immutable.
    """
    if original.get('online_motion',{}).get('scope')!=LIVE_SCOPE or latest.get('online_motion',{}).get('scope')!=LIVE_SCOPE:
        raise ValueError('ARCHIVE_OR_UNVERIFIED_DYNAMIC_PRIOR_NOT_LIVE')
    if scene_motion_kind(original['assumptions'])!=scene_motion_kind(latest['assumptions']):
        raise ValueError('SCENE_MOTION_KIND_CHANGED_NEW_REQUEST_REQUIRED')
    for key in ('live_scene_motion_kind','world_revision','scene_motion_assumption_digest'):
        if original['online_motion'].get(key)!=latest['online_motion'].get(key):raise ValueError('LIVE_SCENE_ASSUMPTION_CHANGED:'+key)
    for key in ('source_session_id','clock_basis','source_frames'):
        if latest[key]!=original[key]:raise ValueError('LATEST_DEPTH_SOURCE_OR_MODEL_CHANGED:'+key)
    geometry_review=geometry_context_review(original['geometry_context'],latest['geometry_context'],computation_only=computation_only)
    if original['online_motion']['clock_epoch']!=latest['online_motion']['clock_epoch']:
        raise ValueError('LATEST_DEPTH_CLOCK_EPOCH_CHANGED')
    old_prior,new_prior=deepcopy(original['assumptions']),deepcopy(latest['assumptions'])
    if computation_only and scene_motion_kind(old_prior)==STATIC_SCENE:
        # Both bounds independently replayed their own pinned per-frame basis.
        # Changing proof files is not changing the exact declared hypotheses.
        old_prior.pop('basis_evidence',None);new_prior.pop('basis_evidence',None)
    if latest['geometry']['id']!=original['geometry']['id'] or new_prior!=old_prior:
        raise ValueError('NEW_OBJECT_OR_DYNAMIC_PRIOR_CHANGED')
    if latest['frame_seq']<original['frame_seq'] or latest['source_stamp_s']<original['source_stamp_s']:
        raise ValueError('LATEST_DYNAMIC_OBSERVATION_REVERSED')
    prior=original['assumptions'];policy=original['online_motion']['policy']
    age=now_s-latest['source_stamp_s']
    if not 0<=age<=min(policy['max_latest_observation_age_s'],policy['max_occlusion_s']):
        raise ValueError('LATEST_DYNAMIC_OBSERVATION_STALE_OR_OCCLUDED')
    if not latest['source_stamp_s']<=latest['received_stamp_s']<=now_s:
        raise ValueError('LATEST_DYNAMIC_RECEIPT_TIME_INVALID')
    if not now_s<=required_until_s<=min(original['valid_until_s'],latest['valid_until_s']):
        raise ValueError('DYNAMIC_ENVELOPE_TTL_INSUFFICIENT_FOR_WHOLE_CURVE')
    geometry=original['geometry'] if planning_geometry is None else planning_geometry
    local=checked_pose(geometry['pose'])
    if not np.array_equal(local[:3,:3],np.eye(3)):raise ValueError('AXIS_ALIGNED_DYNAMIC_ENVELOPE_REQUIRED')
    low=local[:3,3]-np.asarray(geometry['size_m'])/2
    high=local[:3,3]+np.asarray(geometry['size_m'])/2
    growth=prior['max_speed_m_s']*(required_until_s-latest['source_stamp_s'])
    newlow=np.asarray(latest['online_motion']['source_box_min_m'])-growth
    newhigh=np.asarray(latest['online_motion']['source_box_max_m'])+growth
    fixed_proof=None
    if computation_only and scene_motion_kind(prior)==STATIC_SCENE:
        newlow,newhigh,fixed_proof=fixed_object_observation_intersection(original,latest)
    if np.any(newlow<low) or np.any(newhigh>high):
        raise ValueError('LATEST_MOTION_OUTSIDE_VALIDATED_ENVELOPE_REPLAN_REQUIRED')
    result=dict(status='NEW_OBSERVATION_MOTION_CONTAINED_IN_IMMUTABLE_SCENE',
        calculated_bound_digest=original['digest'],latest_bound_digest=latest['digest'],
        calculated_frame_seq=original['frame_seq'],latest_frame_seq=latest['frame_seq'],
        observation_age_sim_s=age,required_until_s=required_until_s,original_valid_until_s=original['valid_until_s'],
        minimum_containment_margin_m=float(min((newlow-low).min(),(high-newhigh).min())),
        scene_provenance_modified=False,execution_allowed=False,geometry_observation=geometry_review)
    if fixed_proof is not None:result['fixed_object_observation_proof']=fixed_proof
    return result


def verify_calculated_live_bound(bound,model,*,now_s):
    """Replay immutable source at its receipt, not as a newly received image.

    Current usability is a separate finite horizon + fresh observation check.
    Replaying old raw Depth with current projection max_age would otherwise
    reject every long computation even when its conservative scene is valid.
    """
    from depth_obstacle_envelope import verify_bound
    if bound.get('online_motion',{}).get('scope')!=LIVE_SCOPE:
        raise ValueError('ARCHIVED_STATIC_BOUND_NOT_LIVE_CALCULATED_SCENE')
    if not bound['source_stamp_s']<=now_s<=bound['valid_until_s']:
        raise ValueError('CALCULATED_DYNAMIC_BOUND_EXPIRED')
    return verify_bound(bound,model,now_s=bound['received_stamp_s'])


def check_online_context(base,calculated,packet,owner,limits):
    from dynamic_cumotion_inputs import verify_seal,check_control
    from depth_obstacle_envelope import verify_bound
    verify_seal(calculated,'envelope_digest');check_control(packet['control'])
    contract=calculated['online_validity'];now=owner['now_s']
    from dynamic_cumotion_inputs import owner_observations
    owner_mode=owner_observations(limits);world_observation=None;metadata=packet
    if owner_mode:
        if not computational_geometry(limits):raise ValueError('RAW_WORLD_OBSERVATIONS_REQUIRE_COMPUTATION_ONLY')
        metadata,world_observation=current_owner_world_metadata(base,packet,owner,contract)
    if scene_motion_kind(limits)!=scene_motion_kind(contract):raise ValueError('OWNER_SCENE_MOTION_MODE_CHANGED')
    if 'live_scene_motion_kind' in contract and (type(limits.get('world_revision')) is not int or
            limits['world_revision']!=contract['world_revision']):
        raise ValueError('OWNER_SCENE_WORLD_REVISION_CHANGED')
    if contract['scope']!=LIVE_SCOPE:raise ValueError('EXPLICIT_ONLINE_VALIDITY_REQUIRED')
    if any(owner[k]!=contract['identity'][k] or type(owner[k]) is not type(contract['identity'][k]) for k in IDENTITY):
        raise ValueError('LIVE_OWNER_EXECUTION_EPOCH_CANCEL_OR_REPLAN_CHANGED')
    if packet['envelope']!=calculated:raise ValueError('CALCULATED_SCENE_PROVENANCE_MUST_REMAIN_IMMUTABLE')
    if digest(limits)!=calculated['thresholds_digest']:raise ValueError('ONLINE_LIMITS_CHANGED')
    if packet.get('timeline_running') is not True or packet.get('obstacle_motion_policy')!='CONTINUE_WHILE_ROBOT_HOLDS':
        raise ValueError('LIVE_PHYSICS_SENSOR_OBSTACLE_MUST_CONTINUE')
    if (metadata.get('dynamic_inventory_complete') is not True or metadata.get('observed_dynamic_ids')!=[contract['obstacle_id']] or
            metadata.get('occluded') is not False):raise ValueError('NEW_UNOBSERVED_OR_OCCLUDED_OBJECT_HOLD')
    if (metadata['model_digest']!=contract['model_digest'] or
            not owner_mode and metadata['static_world_digest']!=contract['static_world_digest']):
        raise ValueError('CURRENT_STATIC_WORLD_OR_MODEL_CHANGED')
    original=verify_calculated_live_bound(packet['obstacles']['depth_bound'],base['model_bundle'],now_s=now)
    latest=verify_bound(packet['latest_depth_bound'],base['model_bundle'],now_s=now)
    for bound in (original,latest):
        if scene_motion_kind(bound['assumptions'])!=scene_motion_kind(contract):raise ValueError('SCENE_BOUND_MODE_NOT_CALCULATED_MODE')
        if 'live_scene_motion_kind' in contract and any(bound['online_motion'].get(k)!=contract[k] for k in
                ('live_scene_motion_kind','world_revision','scene_motion_assumption_digest')):
            raise ValueError('SCENE_BOUND_ASSUMPTION_NOT_CALCULATED_SOURCE')
    if any(b['online_motion']['clock_epoch']!=owner['clock_epoch'] for b in (original,latest)):
        raise ValueError('DEPTH_OWNER_CLOCK_EPOCH_MISMATCH')
    if packet['latest_depth']['digest']!=latest['candidate_digest']:
        raise ValueError('LATEST_PROJECTION_NOT_FROM_LATEST_BOUND_EVIDENCE')
    if original['digest']!=contract['bound_digest']:raise ValueError('CALCULATED_BOUND_CHANGED')
    planning_geometry=None
    if 'planner_box_enclosure' in contract:
        from depth_obstacle_envelope import planner_box_projection
        planning_geometry,proof=planner_box_projection(original,limits['planner_box_representation'])
        if (contract['planner_box_enclosure']!=proof or packet['obstacles'].get('planner_box_enclosure')!=proof or
                packet['obstacles']['objects']!=[planning_geometry]):
            raise ValueError('OUTWARD_PLANNER_GEOMETRY_PROVENANCE_CHANGED')
    policy=contract['policy'];wall=time.monotonic()
    wall_age=wall-contract['observation_wall_monotonic_s']
    latest_wall_age=wall-latest['online_motion']['observation_wall_monotonic_s']
    if owner_mode:
        # max_occlusion_s is measured on the SIM source clock by contained_motion.
        # The separately declared wall budget covers observation through apply.
        # An actual newer frame must also be newer on this host's monotonic clock.
        wall_ok=(0<=latest_wall_age<=wall_age<=policy['max_sensor_to_apply_wall_s'])
    else:wall_ok=(0<=wall_age<=policy['max_sensor_to_apply_wall_s'] and 0<=latest_wall_age<=policy['max_occlusion_s'])
    if not wall_ok:
        raise ValueError('DYNAMIC_OBSERVE_COMPUTE_REVIEW_APPLY_WALL_BUDGET_EXPIRED:'+str(dict(
            original_age_wall_s=wall_age,latest_age_wall_s=latest_wall_age,total_wall_budget_s=policy['max_sensor_to_apply_wall_s'],
            source_occlusion_budget_sim_s=policy['max_occlusion_s'])))
    required=now+policy['max_trajectory_duration_s']+policy['apply_stop_margin_s']
    result=contained_motion(original,latest,now_s=now,required_until_s=required,
        computation_only=computational_geometry(limits),planning_geometry=planning_geometry)
    result.update(sensor_to_review_wall_s=wall_age,latest_observation_age_wall_s=latest_wall_age,
        source_now_s=now,latest_frame_seq=latest['frame_seq'],latest_source_stamp_s=latest['source_stamp_s'],
        max_trajectory_duration_s=policy['max_trajectory_duration_s'])
    if world_observation is not None:result['current_world_observation']=world_observation
    return result
