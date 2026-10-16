"""CPU single-object diameter bound from replayed Depth evidence, not a tracker.

All guarantees are conditional on declared SIM object size/error/speed bounds.
No USD/GT object pose is read. Hashes prove artifact consistency, not sensor
authenticity; capture/model/mask provenance remains part of the evidence.
"""
import json
import hashlib
from copy import deepcopy
from fractions import Fraction
import math
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from plan_only import digest
from isaac_sim.depth_obstacles.projection import project_frame
from isaac_sim.depth_obstacles.capture_wrist_sim import select_masks
from prepare_cpu_model import file_hash
from prepare_gpu_scene import tcp_fk
from sim_utils import rigid

FILES=('frame','depth','semantic_ids','semantic_info','self_mask','held_mask','obstacle_mask',
       'geometry_self_mask','geometry_held_mask','mask_audit','pose','candidates','limits','capture_source')

OUTWARD_PLANNER_BOX='OUTWARD_FLOAT64_AABB_V1'


def outward_aabb(low,high):
    """Enclose exact binary64 endpoints in both real and float centre±size/2.

    Directed size rounding is geometric enlargement, never a comparison epsilon.
    JSON/YAML round trips retain these binary64 centre/size values exactly.
    """
    low=np.asarray(low,float);high=np.asarray(high,float)
    if (low.shape!=(3,) or high.shape!=(3,) or not np.isfinite([low,high]).all() or
            np.any(low>=high)):raise ValueError('FINITE_POSITIVE_AABB_REQUIRED')
    centres=[];sizes=[]
    for l,h in zip(low,high):
        l,h=Fraction(float(l)),Fraction(float(h))
        c=float((l+h)/2);cf=Fraction(c)
        required=2*max(cf-l,h-cf)
        try:s=float(required)
        except OverflowError:raise ValueError('FINITE_AABB_REPRESENTATION_UNAVAILABLE') from None
        while True:
            if not math.isfinite(s) or s<=0:raise ValueError('FINITE_AABB_REPRESENTATION_UNAVAILABLE')
            sf=Fraction(s)
            if not math.isfinite(c-s/2) or not math.isfinite(c+s/2):
                raise ValueError('FINITE_AABB_REPRESENTATION_UNAVAILABLE')
            if (cf-sf/2<=l and cf+sf/2>=h and
                    Fraction(c-s/2)<=l and Fraction(c+s/2)>=h):break
            s=math.nextafter(s,math.inf)
        centres.append(c);sizes.append(s)
    return centres,sizes


def planner_box_projection(bound,representation):
    """New consumer geometry only; legacy bound/replay bytes remain unchanged."""
    if representation!=OUTWARD_PLANNER_BOX:raise ValueError('UNKNOWN_PLANNER_BOX_REPRESENTATION')
    motion=bound['online_motion'];geometry=deepcopy(bound['geometry'])
    if (motion.get('live_scene_motion_kind')!='STATIC_OBSTACLE' or
            bound['assumptions']['max_speed_m_s']!=0 or
            geometry['pose']['quaternion_xyzw']!=[0,0,0,1]):
        raise ValueError('OUTWARD_PLANNER_BOX_REQUIRES_STATIC_AABB')
    centre=np.asarray(geometry['pose']['xyz_m']);half=np.asarray(geometry['size_m'])/2
    low=np.minimum(motion['source_box_min_m'],centre-half)
    high=np.maximum(motion['source_box_max_m'],centre+half)
    xyz,size=outward_aabb(low,high)
    geometry['pose']['xyz_m']=xyz;geometry['size_m']=size
    proof=dict(representation=representation,source_bound_digest=bound['digest'],
        enclosure_min_m=low.tolist(),enclosure_max_m=high.tolist(),geometry=deepcopy(geometry),
        scope='NEW_CONSUMER_PLANNER_GEOMETRY_NOT_SOURCE_BOUND_REWRITE',source_bound_modified=False)
    return geometry,proof


def compare_replay(replayed,stored):
    checksum=hashlib.sha256(json.dumps({k:v for k,v in stored.items() if k!='digest'},sort_keys=True,allow_nan=False).encode()).hexdigest()
    if checksum!=stored['digest']:raise ValueError('STORED_CANDIDATE_DIGEST_CHANGED')
    for key in replayed.keys()-{'points_base_m','T_base_camera_optical','digest'}:
        if replayed[key]!=stored[key]:raise ValueError('DEPTH_REPLAY_METADATA_MISMATCH')
    a,b=np.asarray(replayed['points_base_m']),np.asarray(stored['points_base_m'])
    if a.shape!=b.shape:raise ValueError('DEPTH_REPLAY_POINT_COUNT_MISMATCH')
    error=float(np.max(abs(a-b))) if a.size else 0.
    # CPU NumPy/BLAS vs Isaac's NumPy differ by 1e-16m in a 3D matrix product.
    # Preserve original hashes; tolerate only float64 arithmetic, not geometry.
    tolerance=64*np.finfo(float).eps*max(1.,float(np.max(abs(b))) if b.size else 1.)
    if error>tolerance:raise ValueError('DEPTH_REPLAY_NUMERIC_MISMATCH')
    # The transform is also a float64 matrix product, not categorical metadata.
    ta,tb=[np.asarray(x['T_base_camera_optical'],float) for x in (replayed,stored)]
    if ta.shape!=(4,4) or tb.shape!=(4,4) or not np.isfinite([ta,tb]).all():
        raise ValueError('DEPTH_REPLAY_TRANSFORM_INVALID')
    transform_error=float(np.max(abs(ta-tb)))
    transform_tolerance=64*np.finfo(float).eps*max(1.,float(np.max(abs(tb))))
    if transform_error>transform_tolerance:raise ValueError('DEPTH_REPLAY_TRANSFORM_MISMATCH')
    return dict(max_replay_error_m=error,float64_replay_tolerance_m=tolerance,
                max_transform_replay_error=transform_error,float64_transform_tolerance=transform_tolerance)


def evidence_files(spec):
    folder=Path(spec['folder']).resolve(strict=True);manifest=folder/'manifest.json'
    if file_hash(manifest)!=spec['manifest_sha256']:raise ValueError('DEPTH_MANIFEST_CHANGED')
    data=json.loads(manifest.read_text())
    if data['schema']!='single-object-depth-evidence/0.1' or data['source_kind'] not in ('FIXTURE','SIM_DEPTH'):
        raise ValueError('EXPLICIT_DEPTH_EVIDENCE_REQUIRED')
    if data['source_kind']!=spec['capture_source_kind']:raise ValueError('CAPTURE_SOURCE_KIND_MISMATCH')
    if data['source_kind']=='SIM_DEPTH' and data['annotator'] not in ('distance_to_image_plane','distance_to_camera'):
        raise ValueError('ACTUAL_SIM_DEPTH_ANNOTATOR_REQUIRED')
    paths={};keys=set(FILES)
    if data.get('mask_evidence_kind')=='SEMANTIC_FULL_SCENE_BINDING':
        keys-=set(('geometry_self_mask','geometry_held_mask'))
    if data.get('calibration_scope')=='SIM_NOMINAL_FROM_REAL_PUBLISHED_TF':keys.add('calibration')
    for key in keys:
        ref=data['files'][key];path=(folder/ref['path']).resolve(strict=True)
        if not path.is_relative_to(folder) or file_hash(path)!=ref['sha256']:
            raise ValueError('DEPTH_EVIDENCE_CHANGED:'+key)
        paths[key]=path
    if file_hash(paths['capture_source'])!=spec['capture_source_sha256']:
        raise ValueError('CAPTURE_SOURCE_PIN_MISMATCH')
    if data['source_kind']=='SIM_DEPTH':
        from bounded_sim_evidence import pinned_json
        completed=pinned_json(data['completion'])
        frame=json.loads(paths['frame'].read_text())
        if (completed['status']!='COMPLETE' or completed['source_kind']!='SIM_DEPTH' or
                completed['session_id']!=frame['session_id'] or completed['capture_source_sha256']!=spec['capture_source_sha256'] or
                dict(frame_seq=frame['frame_seq'],frame_sha256=file_hash(paths['frame'])) not in completed['frames']):
            raise ValueError('COMPLETE_PINNED_SIM_CAPTURE_REQUIRED')
    return data,paths


def checked_pose_and_masks(frame,paths,model,geometry_context,spec):
    pose=json.loads(paths['pose'].read_text());audit=json.loads(paths['mask_audit'].read_text())
    expected_manifest=file_hash(Path(model['bundle_path'])/'MODEL_MANIFEST.json')
    if pose['model_manifest_sha256']!=expected_manifest or audit['model_manifest_sha256']!=expected_manifest:
        raise ValueError('DEPTH_MODEL_BINDING_CHANGED')
    if audit['held_geometry_digest']!=digest(geometry_context):raise ValueError('HELD_MASK_GEOMETRY_CHANGED')
    allowed='EXPLICIT_FIXTURE' if frame['source_kind']=='FIXTURE' else 'VALIDATED_SIM'
    scopes=('SIM_FIXTURE',) if allowed=='EXPLICIT_FIXTURE' else ('SIM_NOMINAL','SIM_NOMINAL_FROM_REAL_PUBLISHED_TF')
    if frame['calibration_scope'] not in scopes:
        raise ValueError('UNKNOWN_SIM_CALIBRATION')
    statuses={allowed}
    if frame['source_kind']=='SIM_DEPTH' and audit['scope']=='SEMANTIC_FULL_SCENE_BINDING':
        # Native producer may honestly leave these pending. Accept only after
        # raw masks and the complete scene/model inventory below are verified.
        statuses.add('GEOMETRIC_UNVERIFIED')
    if any(frame[k] not in statuses for k in ('self_mask_status','held_mask_status')):
        raise ValueError('SELF_HELD_MASK_UNVERIFIED')
    if frame['source_kind']=='SIM_DEPTH':
        from bounded_sim_evidence import stationary_pose,published_calibration
        stationary_pose(pose,frame,paths)
        if (frame['tool_frame_id'].split('/')[-1]!='GripperDA_v4_tcp' or
                frame['base_frame_id'].split('/')[-1]!='base_link'):raise ValueError('EXPLICIT_SIM_BASE_TCP_MAPPING_REQUIRED')
        if pose['capture_source_sha256']!=spec['capture_source_sha256']:raise ValueError('POSE_CAPTURE_SOURCE_CHANGED')
        if frame['calibration_scope']=='SIM_NOMINAL_FROM_REAL_PUBLISHED_TF':
            calibration=published_calibration(frame,dict(path=str(paths['calibration']),sha256=file_hash(paths['calibration'])),model)
            if calibration['capture_source_sha256']!=spec['capture_source_sha256']:raise ValueError('CALIBRATION_CAPTURE_SOURCE_CHANGED')
    if any(frame[k]!=spec['source_frames'][k] for k in ('base_frame_id','tool_frame_id','optical_frame_id')):
        raise ValueError('SOURCE_FRAME_MAPPING_MISMATCH')
    stamps=[frame['source_stamp_s'],frame['robot_state_stamp_s'],frame['transform_stamp_s'],pose['stamp_s']]
    selected_skew=json.loads(paths['limits'].read_text())['max_pose_skew_s']
    if not np.isfinite(selected_skew) or selected_skew<=0:raise ValueError('EXPLICIT_CAPTURE_SKEW_CRITERION_REQUIRED')
    if not np.isfinite(stamps).all() or np.ptp(stamps)>selected_skew:raise ValueError('DEPTH_POSE_CLOCK_SKEW')
    if pose['clock_basis']!=frame['clock_basis']:raise ValueError('DEPTH_POSE_CLOCK_MISMATCH')
    q=np.asarray(frame['q_rad'],float)
    if (q.shape!=(6,) or not np.isfinite(q).all() or
            not np.allclose(pose['q_rad'],q,atol=1e-12,rtol=0) or
            (pose.get('time_sync_scope')!='DYNAMIC_SOURCE_STAMP_VERIFIED' and
             max(np.max(abs(np.asarray(pose[k])-q)) for k in ('before_q_rad','after_q_rad'))>1e-6)):
        raise ValueError('NONSTATIONARY_RENDER_BRACKET')
    predicted=tcp_fk(model,q.tolist(),pose['grip_rad']);actual=rigid(frame['T_base_tool'])
    error=[float(np.linalg.norm(predicted[:3,3]-actual[:3,3])),
           float(Rotation.from_matrix(predicted[:3,:3].T@actual[:3,:3]).magnitude())]
    # PROJECT_TEST_PARAMETER: legacy nominal model/calibration consistency,
    # not SDK observation acceptance. The source matrix records this scope;
    # no physical model alignment is granted by changing a sensor tolerance.
    if error[0]>.0008 or error[1]>.005:raise ValueError('STAMPED_DEPTH_FK_MISMATCH')
    load=lambda key:np.load(paths[key],allow_pickle=False)
    own,held,obstacle,_=select_masks(load('semantic_ids'),json.loads(paths['semantic_info'].read_text()))
    for key,computed in [('self_mask',own),('held_mask',held),('obstacle_mask',obstacle)]:
        supplied=load(key)
        if supplied.dtype!=np.bool_ or not np.array_equal(supplied,computed):raise ValueError('SEMANTIC_MASK_ARRAY_MISMATCH')
    if audit['scope']=='SEMANTIC_FULL_SCENE_BINDING':
        from bounded_sim_evidence import semantic_scene_binding
        error=np.maximum(error,semantic_scene_binding(audit,paths,frame,model,geometry_context)).tolist()
    elif audit['scope']=='FULL_MODEL_MASK_ARRAY_EVIDENCE':
        if frame['source_kind']=='SIM_DEPTH':
            from bounded_sim_evidence import semantic_scene_binding
            error=np.maximum(error,semantic_scene_binding(audit,paths,frame,model,geometry_context)).tolist()
        for key,mask in [('geometry_self_mask',own),('geometry_held_mask',held)]:
            geometry=load(key)
            if geometry.dtype!=np.bool_ or geometry.shape!=mask.shape or np.any(geometry&~mask):
                raise ValueError('FULL_MODEL_MASK_COVERAGE_MISMATCH')
    else:raise ValueError('SELF_HELD_MASK_UNVERIFIED')
    labels=json.loads(paths['semantic_info'].read_text())['idToLabels']
    moving=[v for v in labels.values() if 'moving_obstacle' in ','.join(str(x) for x in v.values()).split(',')]
    if len(moving)!=1:raise ValueError('SINGLE_OBSERVABLE_OBJECT_REQUIRED')
    return pose,own,held,obstacle,error


def replay_candidates(spec,model,geometry_context,*,now_s):
    manifest,paths=evidence_files(spec);frame=json.loads(paths['frame'].read_text())
    if frame['source_kind']!=manifest['source_kind']:raise ValueError('SOURCE_KIND_RELABELLING_REJECTED')
    if manifest['source_kind']=='SIM_DEPTH':
        representation={'distance_to_image_plane':'IMAGE_PLANE_Z','distance_to_camera':'RAY_RANGE'}[manifest['annotator']]
        if frame['depth_representation']!=representation or frame['depth_unit']!='METER' or frame['depth_scale_m']!=1:
            raise ValueError('RTX_DEPTH_UNIT_OR_REPRESENTATION_MISMATCH')
    pose,own,held,mask,error=checked_pose_and_masks(frame,paths,model,geometry_context,spec)
    depth=np.load(paths['depth'],allow_pickle=False)
    if depth.shape!=mask.shape:raise ValueError('DEPTH_MASK_SHAPE_MISMATCH')
    candidates=project_frame(frame,np.where(mask,depth,np.nan),own,held,now_s=now_s,
                             limits=json.loads(paths['limits'].read_text()))
    compare_replay(candidates,json.loads(paths['candidates'].read_text()))
    return frame,pose,candidates,mask,error


def bounded_geometry(points,pixels,shape,prior,*,range_m,fk_error,age_s):
    """For every point p: object lies in p±(diameter+error). Intersect boxes.

    Unknown orientation is covered by the diagonal of declared side limits.
    Hidden size cannot be learned from one front face: the prior is mandatory.
    """
    if prior['scope']!='DECLARED_SIM_SINGLE_OBJECT_BOUNDS_NOT_REAL':raise ValueError('UNKNOWN_EXTENT')
    keys=('point_error_m','pose_translation_error_m','pose_rotation_error_rad','max_speed_m_s','max_sensor_to_use_delay_s')
    values=np.array([prior[k] for k in keys],float);size=np.asarray(prior['size_upper_m'],float)
    if (size.shape!=(3,) or not np.isfinite(size).all() or np.any(size<=0) or values[2]>np.pi or
            not np.isfinite(values).all() or np.any(values<0) or values[-1]<=0):raise ValueError('UNKNOWN_EXTENT_OR_ERROR_BOUNDS')
    if prior['pose_translation_error_m']<fk_error[0] or prior['pose_rotation_error_rad']<fk_error[1]:
        raise ValueError('POSE_ERROR_EXCEEDS_DECLARED_BOUND')
    if not 0<=age_s<=prior['max_sensor_to_use_delay_s']:raise ValueError('LATENCY_BOUND_EXPIRED')
    points=np.asarray(points,float);pixels=np.asarray(pixels,int)
    if points.ndim!=2 or points.shape[1:]!=(3,) or not len(points) or not np.isfinite(points).all():raise ValueError('UNOBSERVABLE')
    minimum=prior['min_visible_pixels'];span=prior['min_pixel_span']
    if type(minimum) is not int or minimum<1 or type(span) is not int or span<1:raise ValueError('EXPLICIT_VISIBILITY_LIMITS_REQUIRED')
    if (len(points)<minimum or pixels.shape!=(len(points),2) or np.any(np.ptp(pixels,axis=0)<span) or
            pixels[:,0].min()<=0 or pixels[:,1].min()<=0 or pixels[:,0].max()>=shape[1]-1 or pixels[:,1].max()>=shape[0]-1):
        raise ValueError('INSUFFICIENT_OR_CLIPPED_VISIBILITY')
    diameter=float(np.linalg.norm(size))
    error=prior['point_error_m']+prior['pose_translation_error_m']+2*np.sin(prior['pose_rotation_error_rad']/2)*range_m
    if np.any(np.ptp(points,axis=0)>diameter+2*error):raise ValueError('OBSERVED_SIZE_EXCEEDS_PRIOR')
    radius=diameter+error+prior['max_speed_m_s']*prior['max_sensor_to_use_delay_s']
    lower=np.minimum(points.max(0)-radius,points.min(0)-error)
    upper=np.maximum(points.min(0)+radius,points.max(0)+error)
    return (lower+upper)/2,upper-lower,dict(diameter_bound_m=diameter,point_pose_error_bound_m=float(error),
        motion_margin_m=prior['max_speed_m_s']*prior['max_sensor_to_use_delay_s'],
        coverage='PARTIAL_VISIBLE_CONDITIONALLY_BOUNDED_HIDDEN_VOLUME',orientation_estimated=False,
        hidden_extent_verified_by_sensor=False,guarantee_scope='DECLARED_SINGLE_SIM_OBJECT_ONLY')


def build_envelope(spec,prior_path,model,geometry_context,*,now_s):
    prior_path=Path(prior_path).resolve(strict=True);prior=json.loads(prior_path.read_text())
    if file_hash(prior_path)!=spec['prior_sha256'] or not prior['basis_ref']:raise ValueError('BOUND_PRIOR_CHANGED_OR_MISSING')
    if not {'size_upper_m','point_error_m','pose_translation_error_m','pose_rotation_error_rad',
            'max_speed_m_s','max_sensor_to_use_delay_s','basis_evidence'}<=prior.keys():raise ValueError('UNKNOWN_EXTENT_OR_ERROR_BASIS')
    frame,pose,candidates,mask,error=replay_candidates(spec,model,geometry_context,now_s=now_s)
    ref=prior['basis_evidence'];basis_path=Path(ref['path'])
    if file_hash(basis_path)!=ref['sha256']:raise ValueError('SIZE_ERROR_ASSUMPTION_EVIDENCE_CHANGED')
    basis=json.loads(basis_path.read_text())
    keys=('size_upper_m','point_error_m','pose_translation_error_m','pose_rotation_error_rad','max_speed_m_s','max_sensor_to_use_delay_s')
    if (basis['source_kind']!=frame['source_kind'] or basis['scope']!='DECLARED_SINGLE_SIM_OBJECT_AND_ERROR_MODEL' or
            any(basis[k]!=prior[k] for k in keys)):
        raise ValueError('UNKNOWN_EXTENT_OR_UNSUPPORTED_ERROR_ASSUMPTIONS')
    from online_cumotion_validity import LIVE_SCOPE,POLICY,scene_motion_kind,STATIC_SCENE
    kind=scene_motion_kind(prior)
    if kind==STATIC_SCENE and prior.get('usage_scope')!=LIVE_SCOPE:
        raise ValueError('STATIC_SCENE_REQUIRES_FRESH_LIVE_SIM_PRIOR')
    if 'live_scene_motion_kind' in prior and any(basis.get(k)!=prior.get(k) for k in
            ('live_scene_motion_kind','world_revision','static_scene_assumption')):
        raise ValueError('SCENE_MOTION_ASSUMPTION_BASIS_CHANGED')
    if prior.get('usage_scope')==LIVE_SCOPE and (basis.get('usage_scope')!=LIVE_SCOPE or any(basis[k]!=prior[k] for k in POLICY)):
        raise ValueError('LIVE_DYNAMIC_POLICY_BASIS_REQUIRED')
    points=np.asarray(candidates['points_base_m']);camera=np.asarray(candidates['T_base_camera_optical'])
    distance=float(np.linalg.norm(points-camera[:3,3],axis=1).max()) if len(points) else 0.
    if frame['calibration_scope']=='SIM_NOMINAL_FROM_REAL_PUBLISHED_TF':
        from bounded_sim_evidence import pinned_json
        manifest,paths=evidence_files(spec);calibration=pinned_json(dict(path=str(paths['calibration']),sha256=file_hash(paths['calibration'])))
        if prior['point_error_m']<calibration['ray_validation']['max_normalized_ray_error']*distance:
            raise ValueError('RAY_ERROR_NOT_COVERED_BY_POINT_BOUND')
    centre,size,checks=bounded_geometry(points,candidates['pixel_uv'],mask.shape,prior,range_m=distance,fk_error=error,age_s=now_s-frame['source_stamp_s'])
    if not prior['obstacle_id'].startswith('Dynamic_'):raise ValueError('Explicit stable obstacle ID required')
    result=dict(schema='bounded-depth-obstacle/0.1',source_kind=frame['source_kind'],status='REPLAYED_CONDITIONAL_BOUND_NOT_EXECUTION_APPROVAL',
        source_session_id=frame['session_id'],frame_seq=frame['frame_seq'],source_stamp_s=frame['source_stamp_s'],received_stamp_s=frame['received_stamp_s'],
        clock_basis=frame['clock_basis'],source_frames=spec['source_frames'],valid_until_s=frame['source_stamp_s']+prior['max_sensor_to_use_delay_s'],
        geometry=dict(id=prior['obstacle_id'],role='OTHER_OBSTACLE',size_m=size.tolist(),studs=False,coordinate_kind='SIM_BODY_CENTRE',
            geometry_evidence_ref='BOUNDED_DEPTH:'+file_hash(Path(spec['folder'])/'manifest.json'),
            pose=dict(frame_id='base_link',xyz_m=centre.tolist(),quaternion_xyzw=[0,0,0,1])),
        camera=dict(tool_frame_id='GripperDA_v4_tcp',optical_frame_id=frame['optical_frame_id'],calibration_scope=frame['calibration_scope'],calibration_id=frame['calibration_id'],
            q_rad=frame['q_rad'],grip_rad=pose['grip_rad'],state_sequence=pose['state_sequence'],robot_state_stamp_s=frame['robot_state_stamp_s'],transform_stamp_s=frame['transform_stamp_s'],
            T_base_tool=frame['T_base_tool'],T_tool_camera_optical=frame['T_tool_camera_optical'],T_base_camera_optical=camera.tolist()),
        checks=checks,assumptions=prior,evidence_spec=spec,prior_path=str(prior_path),geometry_context=geometry_context,
        mask_validation_scope='HASHED_SEMANTIC_AND_PRODUCER_GEOMETRY_MASK_ARRAY_CONSISTENCY',
        candidate_digest=candidates['digest'],execution_allowed=False,hardware_execution_allowed=False,world_clear_allowed=False)
    from online_cumotion_validity import bound_metadata
    live=bound_metadata(frame,pose,prior,points,candidates['pixel_uv'],mask.shape,range_m=distance,fk_error=error,
        projection_digest=candidates['digest'])
    if live is not None:
        result['online_motion']=live
        low=np.asarray(live['source_box_min_m']);high=np.asarray(live['source_box_max_m'])
        growth=prior['max_speed_m_s']*prior['max_sensor_to_use_delay_s']
        result['geometry']['pose']['xyz_m']=((low+high)/2).tolist()
        result['geometry']['size_m']=(high-low+2*growth).tolist()
        result['checks']['motion_construction']='SOURCE_HIDDEN_VOLUME_PLUS_FULL_HORIZON_MINKOWSKI_SPEED_BOUND'
    result['digest']=digest(result);return result


def verify_bound(bound,model,*,now_s):
    expected=build_envelope(bound['evidence_spec'],bound['prior_path'],model,bound['geometry_context'],now_s=now_s)
    if expected!=bound:raise ValueError('BOUND_DOES_NOT_REPLAY_FROM_EVIDENCE')
    return bound


def verify_sim_stop(state,model,limits):
    """Require recorded same-clock q/v/a history; no missing-a or zero filling."""
    ref=state['stop_evidence'];path=Path(ref['path'])
    if file_hash(path)!=ref['sha256'] or file_hash(ref['capture_source_path'])!=ref['capture_source_sha256']:
        raise ValueError('STOP_EVIDENCE_CHANGED')
    proof=json.loads(path.read_text())
    if (state['source_kind']!='SIM_SAVED_SNAPSHOT' or proof['scope']!='ACTUAL_SIM_STOP_RECORD' or
            proof['model_manifest_sha256']!=file_hash(Path(model['bundle_path'])/'MODEL_MANIFEST.json')):
        raise ValueError('ACTUAL_SIM_STOP_EVIDENCE_REQUIRED')
    observation=proof['observation']
    if (observation['velocity_method']!='PHYSX_NATIVE_JOINT_VELOCITY' or
            observation['acceleration_method']!=state['acceleration_method'] or
            not observation['acceleration_method'] or proof['holding_confirmed'] is not True):
        raise ValueError('NATIVE_STOP_OBSERVATION_METHOD_REQUIRED')
    uncertainty=np.asarray([observation[k] for k in ('q_uncertainty_rad','v_uncertainty_rad_s','a_uncertainty_rad_s2')],float)
    if not np.isfinite(uncertainty).all() or np.any(uncertainty<0):raise ValueError('STOP_OBSERVATION_UNCERTAINTY_REQUIRED')
    duration=limits['min_verified_stop_duration_s']
    if not np.isfinite(duration) or duration<=0 or proof['active_command_count']!=0 or proof['pending_command_count']!=0:
        raise ValueError('EXPLICIT_COMPLETED_STOP_DURATION_REQUIRED')
    if proof['grip_rad']!=state['grip_rad'] or proof['attachment_digest']!=digest(state['attachment_tcp_to_block']):
        raise ValueError('STOP_ATTACHMENT_MISMATCH')
    for key in ('session_id','clock_basis','state_sequence','cancel_generation','stop_reason'):
        if proof[key]!=state[key]:raise ValueError('STOP_EVIDENCE_CONTEXT_MISMATCH')
    rows=proof['samples'];time=np.asarray([r['stamp_s'] for r in rows],float)
    q,v,a=[np.asarray([r[k] for r in rows],float) for k in ('q_rad','v_rad_s','a_rad_s2')]
    if (len(rows)<4 or any(x.shape!=(len(rows),6) or not np.isfinite(x).all() for x in (q,v,a)) or
            not np.isfinite(time).all() or np.any(np.diff(time)<=0) or
            time[-1]-time[0]<duration or time[-1]!=state['source_stamp_s']):
        raise ValueError('COMPLETE_STAMPED_STOP_HISTORY_REQUIRED')
    from dynamic_cumotion_inputs import owner_observations,review_owner_observations
    if owner_observations(limits):review_owner_observations(state,limits)
    elif (np.max(abs(v))+uncertainty[1]>limits['max_abs_velocity_rad_s'] or np.max(abs(a))+uncertainty[2]>limits['max_abs_acceleration_rad_s2'] or
            np.max(abs(np.diff(q,axis=0)/np.diff(time)[:,None]))>limits['max_abs_velocity_rad_s']):
        raise ValueError('STOP_HISTORY_IS_MOVING')
    if any(not np.allclose(x[-1],state[k],atol=1e-12,rtol=0) for x,k in [(q,'q_rad'),(v,'v_rad_s'),(a,'a_rad_s2')]):
        raise ValueError('STOP_END_STATE_MISMATCH')


def inspect_incomplete_capture(folder,model):
    """Keep failed actual captures rejected; never generate replacement Depth."""
    folder=Path(folder)
    if (folder/'pose_01').exists():folder=folder/'pose_01'
    diagnostic=folder/'fk_diagnostic.json'
    if (folder/'frame.json').exists() and not diagnostic.exists():
        return dict(status='HOLD',reason='STAMPED_FK_EVIDENCE_REQUIRED',depth_accepted=False)
    if diagnostic.exists():
        d=json.loads(diagnostic.read_text());predicted=tcp_fk(model,d['q'],d['measured_grip']);actual=np.asarray(d['usd_T_base_tool'])
        error=[float(np.linalg.norm(predicted[:3,3]-actual[:3,3])),float(Rotation.from_matrix(predicted[:3,:3].T@actual[:3,:3]).magnitude())]
        if error[0]>.0008 or error[1]>.005:return dict(status='HOLD',reason='STAMPED_DEPTH_FK_MISMATCH',fk_error_m_rad=error,
            evidence_sha256=file_hash(diagnostic),depth_accepted=False)
    if (folder/'frame.json').exists():
        frame=json.loads((folder/'frame.json').read_text())
        if frame['source_kind']!='SIM_DEPTH':raise ValueError('Actual capture inspection requires SIM_DEPTH')
        depth=np.load(folder/'depth.npy',allow_pickle=False);mask=np.load(folder/'obstacle_mask.npy',allow_pickle=False)
        own=np.load(folder/'self_mask.npy',allow_pickle=False);held=np.load(folder/'held_mask.npy',allow_pickle=False)
        if not np.array_equal(np.where(mask,depth,np.nan),np.load(folder/'obstacle_pixels_depth.npy',allow_pickle=False),equal_nan=True):
            raise ValueError('STORED_OBSTACLE_DEPTH_MISMATCH')
        replay=project_frame(frame,np.where(mask,depth,np.nan),own,held,now_s=frame['received_stamp_s'],
            limits=json.loads((folder/'limits.json').read_text()))
        replay_check=compare_replay(replay,json.loads((folder/'candidates.json').read_text()))
        reasons=[]
        if any(frame[k]!='VALIDATED_SIM' for k in ('self_mask_status','held_mask_status')):reasons.append('SELF_HELD_MASK_UNVERIFIED')
        required=['manifest.json','semantic_ids.npy','mask_audit.json','pose.json']
        audit=json.loads((folder/'mask_audit.json').read_text()) if (folder/'mask_audit.json').exists() else {}
        if audit.get('scope')=='FULL_MODEL_MASK_ARRAY_EVIDENCE':required+=['geometry_self_mask.npy','geometry_held_mask.npy']
        elif audit.get('scope')!='SEMANTIC_FULL_SCENE_BINDING':reasons.append('FULL_MODEL_SEMANTIC_PROVENANCE_UNVERIFIED')
        missing=[k for k in required if not (folder/k).exists()]
        if missing:reasons.append('COMPLETE_HASHED_MASK_POSE_EVIDENCE_REQUIRED')
        return dict(status='HOLD',reason=reasons or ['DECLARED_SIZE_ERROR_MOTION_PRIOR_AND_STOP_EVIDENCE_REQUIRED'],
            fk_error_m_rad=error,actual_depth_replayed=True,visible_pixels=replay['valid_pixels'],replay_check=replay_check,
            held_mask_pixels=int(held.sum()),held_mask_status=frame['held_mask_status'],missing_files=missing,
            time_sync_scope='STATIONARY_RECONSTRUCTION_NOT_DYNAMIC_CAPTURE',
            source_hashes={str(p):file_hash(p) for p in folder.iterdir() if p.is_file()},depth_accepted=False)
    return dict(status='HOLD',reason='COMPLETE_HASHED_DEPTH_MASK_POSE_EVIDENCE_REQUIRED',depth_accepted=False)
