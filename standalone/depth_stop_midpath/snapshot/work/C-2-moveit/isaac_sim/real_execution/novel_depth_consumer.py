"""Read-only adapter for pinned compare_depth outputs, never a detector/sender.

Array pins use original NPY bytes, including NaNs; JSON contains refs and nulls.
Scalar point errors need an explicit base-frame bound meaning in the pinned
error model. A matching-error scalar or an unspecified optical-Z error is not
silently a three-axis point bound.
"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json

import numpy as np
from plan_only import digest


def _read(ref, *, array=False, binary=False):
    raw=Path(ref['path']).read_bytes()
    if sha256(raw).hexdigest()!=ref['sha256']:
        raise ValueError('NOVEL_SOURCE_CHANGED:'+ref['path'])
    if binary:return raw
    return np.load(BytesIO(raw),allow_pickle=False) if array else json.loads(raw)


def _same_array(value,ref,read=_read):
    a=np.asarray(value);b=read(ref,array=True)
    if a.dtype!=b.dtype or a.shape!=b.shape or not np.array_equal(a,b,equal_nan=True):
        raise ValueError('NOVEL_ARRAY_CHANGED:'+ref['path'])


def _qualification_support_refs(producer):
    """Accept existing export layouts without letting one override another."""
    names=('support_mask','face_id','expected_error_m');refs={}
    def add(name,ref):
        if (not isinstance(ref,dict) or not isinstance(ref.get('path'),str) or not ref['path'] or
                not isinstance(ref.get('sha256'),str) or len(ref['sha256'])!=64 or
                any(c not in '0123456789abcdef' for c in ref['sha256'])):
            raise ValueError('NOVEL_SUPPORT_REF_INVALID:'+name)
        if name in refs and refs[name]!=ref:
            raise ValueError('NOVEL_SUPPORT_REF_CONFLICT:'+name)
        refs[name]=ref
    for name in names:
        if name in producer:add(name,producer[name])
    for key in ('arrays','arrays_and_images'):
        if key not in producer:continue
        if not isinstance(producer[key],dict):raise ValueError('NOVEL_SUPPORT_LAYOUT_INVALID:'+key)
        for name in names:
            if name in producer[key]:add(name,producer[key][name])
    if 'support_artifacts' in producer:
        if not isinstance(producer['support_artifacts'],list):
            raise ValueError('NOVEL_SUPPORT_LAYOUT_INVALID:support_artifacts')
        for ref in producer['support_artifacts']:
            if not isinstance(ref,dict) or not isinstance(ref.get('path'),str):
                raise ValueError('NOVEL_SUPPORT_REF_INVALID:support_artifacts')
            name=Path(ref['path']).stem
            if name in names:add(name,ref)
    for name in names:
        if name not in refs:raise ValueError('NOVEL_SUPPORT_REF_MISSING:'+name)
    return refs


def adapt_novel_depth_detection(detection,expected,frame_state,owner,*,source_refs,
                                model_bundle,max_age_s,max_pose_skew_s):
    """Validate full detection, return foreground-only projection + companion.

    source_refs: detection=result.json (existing replay diagnostic layout),
    map=geometry_inventory.json, raw_depth=original depth.npy. result.json pins
    source_frame_ref, error_model_ref, arrays_and_images including projected.
    owner=None verifies a saved input only: no current owner is invented and
    no risk projection is returned. No input mutation, writes or robot commands.
    """
    return _validate_detection(detection,expected,frame_state,owner,source_refs=source_refs,
        model_bundle=model_bundle,max_age_s=max_age_s,max_pose_skew_s=max_pose_skew_s,read=_read)


def _validate_detection(detection,expected,frame_state,owner,*,source_refs,
                        model_bundle,max_age_s,max_pose_skew_s,read):
    # One validation path: saved wrapper supplies byte-pinned file reads;
    # the shadow wrapper supplies only its owned field descriptors plus pinned parents.
    from isaac_sim.depth_obstacles.novel_depth.expected_depth import _association_status, _camera
    from isaac_sim.depth_obstacles.novel_depth.difference import _observed_z
    from isaac_sim.depth_obstacles.novel_depth.geometry import _digest as depth_digest
    from isaac_sim.depth_obstacles.novel_depth.qualification import load_qualification

    d=detection;f=frame_state;e=expected
    record=read(source_refs['detection']);mapping=read(source_refs['map'])
    original_frame=read(record['source_frame_ref']);error=read(record['error_model_ref'])
    if digest(f)!=digest(original_frame) or digest(e['frame_state'])!=digest(f):
        raise ValueError('NOVEL_SOURCE_FRAME_CHANGED')
    if depth_digest(error)!=e['error_model_digest'] or digest(error)!=digest(e['error_model']):
        raise ValueError('NOVEL_ERROR_MODEL_CHANGED')
    if error['status']=='FIXTURE_PARAMETER' and f['source_kind']!='FIXTURE':
        raise ValueError('NOVEL_FIXTURE_ERROR_CANNOT_APPROVE_SIM')
    if error['status']=='MEASURED_BASELINE':
        if not error['source_refs']:raise ValueError('NOVEL_MEASURED_ERROR_REFS_REQUIRED')
        for ref in error['source_refs']:read(ref,binary=True)
    metadata=mapping['metadata'];map_digest=mapping['map_digest']
    record_map_digest=record.get('map_digest')
    if record_map_digest is None:
        if record['map_ref']!=source_refs['map']:raise ValueError('NOVEL_RECORD_MAP_REF_CHANGED')
        record_map_digest=read(record['map_ref'])['map_digest']
    if depth_digest(metadata)!=map_digest or any(v!=map_digest for v in
            (e['map_digest'],d['map_digest'],record_map_digest)) or (owner is not None and owner['known_geometry_digest']!=map_digest):
        raise ValueError('NOVEL_KNOWN_MAP_CHANGED')
    if (owner is not None and digest(model_bundle)!=owner['model_digest']) or metadata['model_manifest_sha256']!=model_bundle['manifest_sha256']:
        raise ValueError('NOVEL_MODEL_MAP_BINDING_CHANGED')
    manifest=Path(model_bundle['bundle_path'])/'MODEL_MANIFEST.json'
    if sha256(manifest.read_bytes()).hexdigest()!=metadata['model_manifest_sha256']:
        raise ValueError('NOVEL_MODEL_MANIFEST_CHANGED')
    if owner is not None and metadata['held_definition']['geometry']['id']!=owner['selected_block_id']:
        raise ValueError('NOVEL_HELD_MAP_BINDING_CHANGED')
    # Reuse the producer's pinned session/camera/render/model qualification.
    # Original frame metadata is never rewritten to the effective convention.
    qualification=load_qualification(f,mapping,error)
    scoped=error['status']=='SIM_SCOPED_NUMERICAL_MODEL'
    if scoped and qualification is None:raise ValueError('NOVEL_SCOPED_QUALIFICATION_REQUIRED')
    effective=deepcopy(f['pixel_convention']);support_refs={}
    if qualification is not None:
        if any(error.get(k) is not None for k in ('expected_error_m','depth_error_m','point_error_m')):
            raise ValueError('NOVEL_SCOPED_ERRORS_REQUIRE_SEPARATE_POINT_COMPANION')
        effective=dict(offset_uv=qualification['offset_uv'],status='SCOPED_SIM_TEST',qualification_ref=qualification['input_ref'])
        if e.get('effective_pixel_convention')!=effective:
            raise ValueError('NOVEL_EFFECTIVE_PIXEL_CONVENTION_CHANGED')
        proof=e.get('scoped_qualification',{})
        if proof.get('qualification_digest')!=qualification['digest'] or proof.get('qualification_ref')!=qualification['input_ref']:
            raise ValueError('NOVEL_EXPECTED_QUALIFICATION_CHANGED')
        companion_ref=source_refs.get('qualification_companion',source_refs.get('point_bounds_companion'))
        if companion_ref is None:raise ValueError('NOVEL_QUALIFICATION_COMPANION_REQUIRED')
        producer=read(companion_ref)
        if (producer['qualification_ref']!=qualification['input_ref'] or producer['map_ref']!=source_refs['map'] or
                producer['error_model_ref']!=record['error_model_ref'] or
                producer.get('source_frame_ref',producer.get('raw_frame_ref'))!=record['source_frame_ref']):
            raise ValueError('NOVEL_QUALIFICATION_PARENT_CHANGED')
        support_refs=_qualification_support_refs(producer)
        for name in ('support_mask','face_id','expected_error_m'):
            try:_same_array(proof[name],support_refs[name],read)
            except OSError as exc:
                raise ValueError('NOVEL_SUPPORT_ARRAY_UNREADABLE:'+name) from exc
    h,w,camera,_,_=_camera(f,None if qualification is None else qualification['offset_uv'])
    if (e['ray_intrinsics']['width']!=w or e['ray_intrinsics']['height']!=h or
            tuple(e['ray_intrinsics'][k] for k in ('fx','fy','cx','cy'))!=camera):
        raise ValueError('NOVEL_EXPECTED_RAY_GRID_CHANGED')
    if any(metadata[k]!=f[k] for k in ('session_id','clock_epoch')) or (owner is not None and
            (any(type(owner[k]) is not type(f[k]) or owner[k]!=f[k] for k in ('session_id','clock_epoch')) or owner['clock_basis']!=f['clock_basis'])):
        raise ValueError('NOVEL_SESSION_OR_EPOCH_CHANGED')
    raw=read(source_refs['raw_depth'],array=True)
    if f['source_kind']=='SIM_DEPTH' and sha256(raw.tobytes()).hexdigest()!=f['depth_array_sha256']:
        raise ValueError('NOVEL_RAW_DEPTH_SOURCE_CHANGED')
    parent_refs=deepcopy(dict(source_refs,frame=record['source_frame_ref'],error=record['error_model_ref'],
        source_association=f['source_association'].get('source_refs',[]),frame_sources=f.get('source_refs',[]),
        map_sources=metadata['source_refs'],error_sources=error['source_refs']))
    for ref in parent_refs['map_sources']+parent_refs['frame_sources']+parent_refs['source_association']:
        read(ref,binary=True)
    companion=dict(detector_kind='EXPECTED_ACTUAL_DEPTH_DIFFERENCE',parent_refs=parent_refs,
        known_geometry_digest=map_digest,map_digest=map_digest,model_digest=digest(model_bundle),
        error_model_digest=depth_digest(error),source_identity=None if owner is None else {k:deepcopy(owner[k]) for k in
            ('session_id','clock_basis','clock_epoch','goal_id','goal_version','active_wire_digest','model_digest','selected_block_id','known_geometry_digest')},
        import_scope='SAVED_INPUT_NO_CURRENT_ACCEPTED_OWNER' if owner is None else 'CURRENT_OWNER_BOUND_INPUT',
        source_stamp_s=f['source_stamp_s'],source_scope=e['status'],map_scope=metadata['map_scope'],
        pixel_convention=deepcopy(f['pixel_convention']),error_model_status=error['status'],
        effective_pixel_convention=effective,qualified_grid_verified=qualification is not None,
        qualification_ref=None if qualification is None else deepcopy(qualification['input_ref']),
        qualification_scope=None if qualification is None else qualification['scope'],
        classification_scope=d.get('classification_scope',error['status']),
        uncertainty_status='UNMEASURED' if error['status']=='UNMEASURED' or error.get('point_error_m') is None else error['status'],
        execution_allowed=False,world_clear_allowed=False,live_intent_eligible=False)
    reasons=[]
    if d['guard']:
        if d['projected'] is not None:raise ValueError('NOVEL_GUARD_HAS_PROJECTION')
        reasons.append(d['status'])
    association=_association_status(f)
    if association!=e['status'] or association=='INPUT_UNASSOCIATED':reasons.append('INPUT_UNASSOCIATED')
    stamp=f['source_stamp_s']
    now=None if owner is None else owner['now_s']
    values=[stamp,f['robot_state_stamp_s'],f['transform_stamp_s'],f['received_stamp_s'],max_age_s,max_pose_skew_s]+([] if now is None else [now])
    if not np.isfinite(values).all() or min(max_age_s,max_pose_skew_s)<=0:raise ValueError('NOVEL_FINITE_CLOCK_POLICY_REQUIRED')
    if f['received_stamp_s']<stamp or (now is not None and f['received_stamp_s']>now):reasons.append('INVALID_OR_FUTURE_CLOCK')
    if now is not None and not 0<=now-stamp<=max_age_s:reasons.append('STALE')
    if stamp<metadata['freeze_source_time']:reasons.append('SOURCE_BEFORE_MAP_FREEZE')
    if max(abs(stamp-f[k]) for k in ('robot_state_stamp_s','transform_stamp_s'))>max_pose_skew_s:reasons.append('SOURCE_POSE_SKEW')
    if owner is None:reasons.append('SAVED_INPUT_NO_CURRENT_ACCEPTED_OWNER')
    elif any(owner[k]!=f[k] for k in ('q_rad','grip_rad','attachment_tcp_to_block')) or owner['state_stamp_s']!=f['robot_state_stamp_s']:
        reasons.append('SOURCE_Q_GRIP_ATTACHMENT_UNASSOCIATED')
    if owner is not None and (owner['now_s']!=owner['state_stamp_s'] or owner['now_s']!=owner['progress_stamp_s']):
        reasons.append('CURRENT_SOURCE_TICK_REQUIRED')
    source_guards=list(dict.fromkeys(reasons))
    if d['guard']:
        confidence=[]
        if error['status']=='UNMEASURED':confidence.append('UNMEASURED_ERROR')
        if f['pixel_convention']['status'] not in ('BASELINE_VALIDATED','FIXTURE_VALIDATED'):confidence.append('UNVERIFIED_PIXEL_CONVENTION')
        companion.update(status='GUARD',guard_reasons=list(dict.fromkeys(reasons)),
            confidence_reasons=confidence,unresolved_observation=True)
        companion['digest']=digest(companion)
        return dict(projected=None,companion=companion)

    p=d['projected'];arrays=record['arrays_and_images'];original=read(arrays['projected'])
    if d['status']!=record['status'] or d['counts']!=record['counts']:
        raise ValueError('NOVEL_DETECTION_REPORT_CHANGED')
    for k in ('observed_z_m','residual_m','candidate_mask','uncertain_candidate_mask','point_is_foreground','point_uncertainty_m'):
        if not isinstance(d[k],np.ndarray):raise ValueError('NOVEL_ORIGINAL_ARRAY_REQUIRED:'+k)
    if p!=original or depth_digest({k:v for k,v in p.items() if k!='digest'})!=p['digest']:
        raise ValueError('NOVEL_ORIGINAL_PROJECTION_CHANGED')
    if p.get('detector_kind')!='EXPECTED_ACTUAL_DEPTH_DIFFERENCE' or p['map_digest']!=map_digest or p['error_model_digest']!=depth_digest(error):
        raise ValueError('NOVEL_DETECTOR_OR_PROJECTION_PARENT_CHANGED')
    if any(p[k]!='GEOMETRIC_UNVERIFIED' for k in ('self_mask_status','held_mask_status')):
        raise ValueError('NOVEL_SEMANTIC_PROJECTION_CANNOT_BE_PROMOTED')
    if d['source_association']!=f['source_association'] or d['pixel_convention']!=f['pixel_convention']:
        raise ValueError('NOVEL_SOURCE_COMPANION_CHANGED')
    if d['source_refs']!=f.get('source_refs',[]) or d['original_intrinsics']!=f['intrinsics'] or d['original_T_tool_camera_optical']!=f['T_tool_camera_optical']:
        raise ValueError('NOVEL_ORIGINAL_CALIBRATION_CHANGED')
    for k in ('session_id','clock_basis','clock_epoch','frame_seq','q_rad','source_stamp_s','robot_state_stamp_s','transform_stamp_s'):
        if p[k]!=f[k]:raise ValueError('NOVEL_PROJECTED_SOURCE_CHANGED:'+k)
    if p['source_association_scope']!=association or p['map_scope']!=metadata['map_scope'] or e['map_scope']!=metadata['map_scope']:
        raise ValueError('NOVEL_SOURCE_OR_MAP_SCOPE_CHANGED')
    if d['error_model_digest']!=depth_digest(error):raise ValueError('NOVEL_DETECTION_ERROR_MODEL_CHANGED')
    if qualification is not None:
        if (d.get('effective_pixel_convention')!=effective or p.get('effective_pixel_convention')!=effective or
                d.get('qualification_ref')!=qualification['input_ref'] or p.get('qualification_ref')!=qualification['input_ref'] or
                d.get('classification_scope')!='SIM_NUMERICAL_TRIAL' or
                p.get('classification_scope')!='SIM_NUMERICAL_TRIAL_NOT_POINT_POSITION_BOUND'):
            raise ValueError('NOVEL_CLASSIFICATION_OR_QUALIFICATION_SCOPE_CHANGED')
    for k,v in d.items():
        if isinstance(v,np.ndarray):_same_array(v,arrays[k],read)
    for k,v in d['reason_masks'].items():_same_array(v,arrays[k],read)
    # Unique expected array names in the existing diagnostic record. Diagnostic
    # reason masks share a few other names; never treat those as expected pins.
    for k in ('nearest_z_m','nearest_component','expected_valid','z_lower_m','z_upper_m','edge_mask'):
        _same_array(e[k],arrays[k],read)
    if not np.array_equal(_observed_z(raw,f,e['ray_intrinsics']),d['observed_z_m'],equal_nan=True):
        raise ValueError('NOVEL_OBSERVED_RAW_Z_CHANGED')
    tool=np.asarray(f['T_base_tool'],float)
    if f['source_kind']=='SIM_DEPTH':
        base_camera=np.linalg.inv(np.asarray(f['T_world_base']))@np.asarray(f['T_world_camera'])@np.diag([1.,-1.,-1.,1.])
        if not np.array_equal(e['T_base_camera_optical'],base_camera):raise ValueError('NOVEL_EXPECTED_TF_UNASSOCIATED')
        transform=tool@(np.linalg.inv(tool)@base_camera)
    else:transform=tool@np.asarray(f['T_tool_camera_optical'])
    if not np.array_equal(p['T_base_camera_optical'],transform):raise ValueError('NOVEL_PROJECTED_TF_UNASSOCIATED')
    uv=np.asarray(p['pixel_uv']);points=np.asarray(p['points_base_m'],float)
    uv=uv.reshape(-1,2);points=points.reshape(-1,3)
    if len(points)!=len(uv) or (len(uv) and uv.dtype.kind not in 'iu') or np.any(uv<0) or np.any(uv[:,0]>=w) or np.any(uv[:,1]>=h):
        raise ValueError('NOVEL_PIXEL_POINT_ORDER_INVALID')
    for mask in (d['candidate_mask'],d['uncertain_candidate_mask'],*d['reason_masks'].values()):
        if mask.dtype!=np.bool_ or mask.shape!=(h,w):raise ValueError('NOVEL_MASK_DTYPE_OR_SHAPE_CHANGED')
    if d['point_is_foreground'].dtype!=np.bool_:raise ValueError('NOVEL_FOREGROUND_FLAGS_DTYPE_CHANGED')
    selected=d['candidate_mask']|d['uncertain_candidate_mask'];v,u=np.nonzero(selected)
    if not np.array_equal(uv,np.column_stack((u,v))) or not np.array_equal(d['point_is_foreground'],d['candidate_mask'][v,u]):
        raise ValueError('NOVEL_PIXEL_FOREGROUND_ORDER_CHANGED')
    if np.any(d['candidate_mask'] & d['uncertain_candidate_mask']) or not np.array_equal(d['candidate_mask'],d['reason_masks']['foreground']):
        raise ValueError('NOVEL_FOREGROUND_UNCERTAIN_MASK_CHANGED')
    if d['counts']['foreground']!=int(d['candidate_mask'].sum()) or d['counts']['uncertain']!=int(d['uncertain_candidate_mask'].sum()):
        raise ValueError('NOVEL_DETECTION_COUNTS_CHANGED')
    scalar=np.asarray(d['point_uncertainty_m'],float);bound=error.get('point_error_m') if error['status']!='UNMEASURED' else None
    point_status='UNMEASURED' if bound is None else error['status']
    if scalar.shape!=(len(points),) or d['point_uncertainty_bound_m']!=bound or d['uncertainty_status']!=point_status:
        raise ValueError('NOVEL_POINT_BOUND_PARENT_CHANGED')
    if bound is None:
        if not np.isnan(scalar).all():raise ValueError('NOVEL_UNKNOWN_POINT_BOUND_CHANGED')
    elif not np.isfinite(bound) or bound<0 or not np.array_equal(scalar,np.full(len(points),bound)):
        raise ValueError('NOVEL_POINT_BOUND_CHANGED')
    # A Euclidean base-frame radius bounds each base-axis coordinate. No optical
    # Z/matching-error scalar is accepted as this without an explicit definition.
    meaning=error.get('point_bound_semantics')
    bounded=bound is not None and meaning=='BASE_FRAME_EUCLIDEAN_RADIUS_M'
    required_pixel='FIXTURE_VALIDATED' if f['source_kind']=='FIXTURE' else 'BASELINE_VALIDATED'
    pixel_ok=qualification is not None or f['pixel_convention']['status']==required_pixel
    radii=np.full(len(points),np.nan if not bounded else bound);known_bounds=np.isfinite(radii)
    point_source='FIXED_MODEL_SCALAR' if bounded else 'UNKNOWN'
    point_ref=source_refs.get('point_bounds_companion');propagated=None
    if point_ref is not None:
        from isaac_sim.depth_obstacles.novel_depth.point_bounds import bound_detection_points
        point_record=read(point_ref);error_input=read(point_record['error_input_ref'])
        if (point_record['projected_digest']!=p['digest'] or point_record['raw_frame_ref']!=record['source_frame_ref'] or
                point_record['map_ref']!=source_refs['map'] or point_record['error_model_ref']!=record['error_model_ref']):
            raise ValueError('NOVEL_POINT_PROPAGATION_PARENT_CHANGED')
        for refs in error_input.get('source_refs',{}).values():
            for ref in refs:read(ref,binary=True)
        for ref in error_input.get('nominal_input_refs',{}).values():read(ref,binary=True)
        propagated=bound_detection_points(d,e,f,error_input)
        for key,value in propagated.items():
            if isinstance(value,np.ndarray):_same_array(value,point_record['arrays']['bound_'+key],read)
        for key in ('status','bound_semantics','source_identity','missing_fields','source_refs','error_input_scope',
                    'q_transform_accounting','projected_digest','effective_pixel_convention','qualification_ref','classification_scope'):
            if propagated[key]!=point_record[key]:raise ValueError('NOVEL_POINT_PROPAGATION_CHANGED:'+key)
        if point_record['risk_qualified'] is not False or point_record['official_tolerance_m'] is not None or point_record['official_observation']!='REPORT_ONLY':
            raise ValueError('NOVEL_CONDITIONAL_POINT_BOUND_CANNOT_ADMIT_INTENT')
        if propagated['bound_semantics']!='BASE_FRAME_EUCLIDEAN_RADIUS_M':raise ValueError('NOVEL_POINT_BOUND_SEMANTICS_CHANGED')
        radii=propagated['point_uncertainty_m'];known_bounds=propagated['known_mask'];meaning=propagated['bound_semantics']
        point_source='CONDITIONAL_PROPAGATION'
        reasons.append('CONDITIONAL_POINT_BOUNDS_REPORT_ONLY')
    if not pixel_ok:reasons.append('UNVERIFIED_PIXEL_CONVENTION')
    if error['status']=='UNMEASURED':reasons.append('UNMEASURED_ERROR')
    elif bound is None:reasons.append('UNMEASURED_POINT_BOUND')
    if not known_bounds.all() or (point_ref is None and not bounded):reasons.append('POINT_BOUND_UNKNOWN_OR_UNSPECIFIED')
    if d['counts']['observed_valid']==0:reasons.append('NO_VISIBLE_POINTS')
    if qualification is not None and np.any(d['candidate_mask'] & ~e['scoped_qualification']['support_mask']):
        raise ValueError('NOVEL_SCOPED_FOREGROUND_OUTSIDE_SUPPORT')
    keep=d['point_is_foreground'] & known_bounds & pixel_ok
    indices=np.flatnonzero(keep)
    uncertainty=[[float(radii[i])]*3 for i in indices]
    if len(points)!=len(indices):reasons.append('UNRESOLVED_VISIBLE_POINTS')
    parent_arrays={k:deepcopy(arrays[k]) for k,v in d.items() if isinstance(v,np.ndarray)}
    parent_arrays.update({k:deepcopy(arrays[k]) for k in d['reason_masks']})
    companion.update(status='FOREGROUND_READY' if len(indices) else ('UNKNOWN' if reasons else 'NO_UNMATCHED_VISIBLE_POINTS_NOT_WORLD_CLEAR'),
        guard_reasons=list(dict.fromkeys(reasons)),unresolved_observation=bool(reasons),
        original_projection_ref=deepcopy(arrays['projected']),original_projection_digest=p['digest'],
        parent_array_refs=parent_arrays,original_counts=deepcopy(d['counts']),
        original_point_count=len(points),selected_original_indices=indices.tolist(),
        selected_foreground_count=len(indices),excluded_unresolved_count=len(points)-len(indices),
        original_uncertainty_array_ref=deepcopy(arrays['point_uncertainty_m']),
        normalized_original_point_bounds_m=[[float(radii[i])]*3 if known_bounds[i] and pixel_ok else None for i in range(len(points))],
        scalar_bound_semantics=meaning,point_bound_source=point_source,point_bounds_ref=deepcopy(point_ref),
        point_bounds_risk_qualified=False if point_ref is not None else None,
        point_bounds_status=None if propagated is None else propagated['status'],
        point_bounds_scope=None if propagated is None else propagated['error_input_scope'],
        point_bounds_missing_fields=[] if propagated is None else propagated['missing_fields'],
        point_bound_conversion='EUCLIDEAN_RADIUS_TO_ENCLOSING_AXIS_HALF_WIDTHS' if known_bounds.any() else 'UNKNOWN_PRESERVED',
        live_intent_eligible=(association=='ACTUAL_SOURCE_TICK' and metadata['map_scope']=='PRE_OBSTACLE_APPROVED' and
            error['status']=='MEASURED_BASELINE' and pixel_ok and bounded and point_ref is None and qualification is None))
    if source_guards:
        companion.update(status='SAVED_INPUT_VERIFIED' if owner is None else 'GUARD',source_guard_reasons=source_guards,live_intent_eligible=False)
        companion['digest']=digest(companion)
        return dict(projected=None,companion=companion)
    out=deepcopy(p);out.pop('digest')
    out.update(points_base_m=points[indices].tolist(),pixel_uv=uv[indices].tolist(),
        point_uncertainty_m=uncertainty,known_geometry_digest=map_digest,
        valid_pixels=len(indices),status='FOREGROUND_ONLY_WITH_UNRESOLVED_COMPANION',
        scope='DERIVED_NOVEL_FOREGROUND_POINTS_NOT_WORLD_CLEAR')
    companion['selected_points_digest']=digest({k:out[k] for k in ('points_base_m','pixel_uv','point_uncertainty_m')})
    companion['digest']=digest(companion)
    out['novel_depth_companion']=deepcopy(companion);out['digest']=depth_digest(out)
    return dict(projected=out,companion=companion)


def _owned(value):
    """Capture under the producer's lock; bytes-backed arrays cannot be reused."""
    if isinstance(value,np.ndarray):
        if value.dtype.hasobject:raise ValueError('SHADOW_OBJECT_ARRAY_FORBIDDEN')
        return np.frombuffer(value.tobytes(order='C'),dtype=value.dtype).reshape(value.shape)
    if isinstance(value,dict):return {k:_owned(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_owned(v) for v in value]
    return deepcopy(value)


def _content(value):
    if isinstance(value,np.ndarray):
        return dict(dtype=value.dtype.str,shape=list(value.shape),bytes_sha256=sha256(value.tobytes(order='C')).hexdigest())
    if isinstance(value,dict):return {k:_content(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_content(v) for v in value]
    return value


class _OwnedDepthShadow:
    """One owned producer packet, not a file/blob registry or live credential.

    Seals catch post-capture metadata changes; read-only bytes own each array.
    Parent pins and all semantic/source checks still run at consumption. Capturing
    arbitrary unproven data never grants execution or native-intent eligibility.
    """
    __slots__=('_payload','_seal','_descriptors')

    def __init__(self,payload):
        self._payload=_owned(payload);self._seal=digest(_content(self._payload));self._descriptors=None

    def verify(self):
        if digest(_content(self._payload))!=self._seal:raise ValueError('SHADOW_SNAPSHOT_CHANGED')
        for ref in self._payload['origin_refs']:_read(ref,binary=True)

    def field(self,name):
        p=self._payload
        if name in ('raw','f'):return p[name]
        if name=='projected':return p['d']['projected']
        if name=='point_input':return p['point_error_input']
        if ':' in name:
            kind,key=name.split(':',1)
            if kind in ('d','e'):return p[kind][key]
            if kind=='reason':return p['d']['reason_masks'][key]
            if kind=='support':return p['e']['scoped_qualification'][key]
            if kind=='point':return p['point_bounds'][key]
        if name=='record':
            arrays={k:self.ref('e:'+k) for k,v in p['e'].items() if isinstance(v,np.ndarray)}
            arrays.update({k:self.ref('d:'+k) for k,v in p['d'].items() if isinstance(v,np.ndarray)})
            arrays.update({k:self.ref('reason:'+k) for k in p['d'].get('reason_masks',{})})
            if p['d']['projected'] is not None:arrays['projected']=self.ref('projected')
            return dict(map_digest=p['e']['map_digest'],source_frame_ref=self.ref('f'),error_model_ref=p['error_ref'],
                status=p['d']['status'],counts=p['d'].get('counts'),arrays_and_images=arrays)
        if name=='qualification_companion':
            return dict(qualification_ref=p['e']['error_model']['qualification_ref'],map_ref=p['map_ref'],
                error_model_ref=p['error_ref'],source_frame_ref=self.ref('f'),
                arrays={k:self.ref('support:'+k) for k in ('support_mask','face_id','expected_error_m')})
        if name=='point_record':
            bound=p['point_bounds'];row={k:v for k,v in bound.items() if not isinstance(v,np.ndarray)}
            return dict(row,error_input_ref=self.ref('point_input'),raw_frame_ref=self.ref('f'),map_ref=p['map_ref'],
                error_model_ref=p['error_ref'],arrays={'bound_'+k:self.ref('point:'+k) for k,v in bound.items() if isinstance(v,np.ndarray)})
        raise ValueError('SHADOW_FIELD_UNSUPPORTED:'+name)

    def ref(self,name):
        # Reuse only immutable checksum strings within ONE sealed validation.
        # Return a fresh descriptor dict: caller mutations cannot poison reuse.
        cache=self._descriptors
        if cache is None or name not in cache:
            checksum=digest(_content(self.field(name)))
            if cache is not None:cache[name]=checksum
        else:checksum=cache[name]
        return dict(path='owned-depth:'+name,storage='OWNED_DEPTH_SHADOW',field=name,sha256=checksum)

    def read(self,ref,*,array=False,binary=False):
        if ref.get('storage')!='OWNED_DEPTH_SHADOW':return _read(ref,array=array,binary=binary)
        if binary:raise ValueError('SHADOW_FIELD_IS_NOT_A_FILE')
        value=self.field(ref['field'])
        if ref!=self.ref(ref['field']):raise ValueError('SHADOW_FIELD_DESCRIPTOR_CHANGED')
        if array and not isinstance(value,np.ndarray):raise ValueError('SHADOW_ARRAY_REQUIRED')
        return value


def snapshot_depth_shadow_inputs(raw,detection,expected,frame_state,*,map_ref,error_model_ref,
                                 model_bundle,point_bounds=None,point_error_input=None,origin_refs=()):
    """Call under the producer lock immediately after its original APIs return.

    Copy raw/frame/expected/detection and optional bound_detection_points output.
    No writes or reads here. Files are NOT replaced by a trust boolean: the
    consumer still pins map/error/qualification/source-event/manifest parents.
    Optional origin_refs pin existing archived artifacts, never require saving a
    new result/NPY/projected file. This packet is shadow/report-only for its life.
    """
    if (point_bounds is None)!=(point_error_input is None):raise ValueError('SHADOW_POINT_INPUT_PAIR_REQUIRED')
    return _OwnedDepthShadow(dict(raw=raw,d=detection,e=expected,f=frame_state,map_ref=map_ref,
        error_ref=error_model_ref,model=model_bundle,point_bounds=point_bounds,
        point_error_input=point_error_input,origin_refs=list(origin_refs)))


def adapt_depth_shadow_snapshot(snapshot,current_owner,*,source_owner=None,max_age_s,max_pose_skew_s):
    """Source capture and latest D owner are separate, never merged/restamped.

    Both owners must be real independent atomic snapshots when supplied. The
    existing exact source-q/state guard remains: advanced current q/stamp yields
    diagnostics only until a separate moving-source risk contract is qualified.
    source_owner is NOT inferred from frame or copied from a new owner. owner=None
    imports source evidence only. This API ALWAYS disables native intent.
    """
    if type(snapshot) is not _OwnedDepthShadow:raise ValueError('OWNED_DEPTH_SHADOW_PACKET_REQUIRED')
    snapshot.verify()
    if snapshot._descriptors is not None:raise ValueError('SHADOW_VALIDATION_ALREADY_ACTIVE')
    snapshot._descriptors={}
    try:
        return _adapt_depth_shadow_snapshot(snapshot,current_owner,source_owner=source_owner,
            max_age_s=max_age_s,max_pose_skew_s=max_pose_skew_s)
    finally:
        try:snapshot.verify()
        finally:snapshot._descriptors=None


def _adapt_depth_shadow_snapshot(snapshot,current_owner,*,source_owner,max_age_s,max_pose_skew_s):
    p=snapshot._payload
    sources=dict(detection=snapshot.ref('record'),raw_depth=snapshot.ref('raw'),map=p['map_ref'])
    if p['e'].get('scoped_qualification'):
        sources['qualification_companion']=snapshot.ref('qualification_companion')
    if p['point_bounds'] is not None:sources['point_bounds_companion']=snapshot.ref('point_record')
    # Copies keep caller-owned current/source snapshots independent through work.
    current=deepcopy(current_owner);source=deepcopy(source_owner)
    result=_validate_detection(p['d'],p['e'],p['f'],current,source_refs=sources,model_bundle=p['model'],
        max_age_s=max_age_s,max_pose_skew_s=max_pose_skew_s,read=snapshot.read)
    companion=result['companion'];reasons=[]
    if source is None:reasons.append('SOURCE_D_OWNER_NOT_SUPPLIED')
    elif (any(source[k]!=p['f'][k] for k in ('q_rad','grip_rad','attachment_tcp_to_block','session_id','clock_epoch','clock_basis')) or
            source['state_stamp_s']!=p['f']['robot_state_stamp_s']):reasons.append('SOURCE_D_OWNER_FRAME_MISMATCH')
    if source is not None and current is not None:
        from .remaining_volume import IDENTITY
        for key in IDENTITY+tuple(k for k in ('known_geometry_digest','cancel_generation') if k in source or k in current):
            if key not in source or key not in current or type(source[key]) is not type(current[key]) or source[key]!=current[key]:reasons.append('SOURCE_CURRENT_IDENTITY_CHANGED:'+key)
    if reasons:
        companion.update(status='GUARD' if current is not None else companion['status'],
            guard_reasons=list(dict.fromkeys(companion['guard_reasons']+reasons)),unresolved_observation=True)
        result['projected']=None
    companion.update(live_intent_eligible=False,shadow_only=True,owned_snapshot_digest=snapshot._seal,
        source_owner_digest=None if source is None else digest(source),
        calculation_owner_digest=None if current is None else digest(current),
        source_state_stamp_s=p['f']['robot_state_stamp_s'],
        calculation_state_stamp_s=None if current is None else current['state_stamp_s'])
    companion.pop('digest',None);companion['digest']=digest(companion)
    if result['projected'] is not None:
        from isaac_sim.depth_obstacles.novel_depth.geometry import _digest
        result['projected']['novel_depth_companion']=deepcopy(companion)
        result['projected']['digest']=_digest({k:v for k,v in result['projected'].items() if k!='digest'})
    return result
