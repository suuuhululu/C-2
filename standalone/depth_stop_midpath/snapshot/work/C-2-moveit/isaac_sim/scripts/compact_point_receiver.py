"""Explicit owned-array receiver; provenance checks only, never CU admission.

Legacy projected JSON/digests are not accepted. CPU artifacts are consumed only
by a separately selected CPU scope; they never become runtime completion proof.
"""
from hashlib import sha256
import json
import math
from pathlib import Path

import numpy as np
import yaml
from compact_points_guarded import OwnedCompactPoints
from isaac_sim.real_execution.novel_depth_consumer import _read
from isaac_sim.depth_obstacles.novel_depth.geometry import _digest
from isaac_sim.depth_obstacles.novel_depth.qualification import camera_scope
from moveit_stop_cumotion_inputs import read_known_map_source
from plan_only import digest

RUNTIME='ISOLATED_SIM_COMPACT_STOP_INPUT'
CPU='CPU_SYNTHETIC_NOT_RUNTIME'
KIND='OWNED_NUMPY_ARRAY_CONTENT_SHA256_V1'
STORAGE='OWNED_COMPACT_DEPTH_POINTS'
SOURCE=('session_id','clock_basis','clock_epoch','frame_seq','source_stamp_s')
GENERATION=('session_id','clock_basis','clock_epoch','execution_id','goal_id',
            'goal_version','cancel_generation','replan_sequence')
OWNER=GENERATION+('execution_version','state_digest','state_sequence','snapshot_digest','snapshot_version')
ARRAYS=dict(points_base_m=('float64',3),pixel_uv=('int64',2),
    point_is_foreground=('bool',None),point_is_uncertain=('bool',None),
    point_uncertainty_m=('float64',None))


def wait(status):
    return dict(status=status,payload_verified=False,SDK_READY=False,execution_allowed=False,
        hardware_execution_allowed=False,world_clear_allowed=False,geometry_HOLD=True)


def equal(left,right,reason):
    if digest(left)!=digest(right):raise ValueError(reason)


def refs_read(ref,verified,*,array=False):
    value=_read(ref,array=array);verified.append(ref);return value


def array_contract(product,frame,counts,masks):
    n=product['point_count']
    if type(n) is not int or n<0:raise ValueError('COMPACT_POINT_COUNT_REQUIRED')
    for key,(dtype,columns) in ARRAYS.items():
        a=product[key];shape=(n,) if columns is None else (n,columns)
        if (type(a) is not np.ndarray or a.dtype!=np.dtype(dtype) or a.shape!=shape
                or a.flags.writeable or not a.flags.c_contiguous):
            raise ValueError('COMPACT_ARRAY_CONTRACT_CHANGED:'+key)
    xyz,uv=product['points_base_m'],product['pixel_uv']
    width,height=frame['intrinsics']['width'],frame['intrinsics']['height']
    if (not np.isfinite(xyz).all() or np.any(uv<0) or np.any(uv[:,0]>=width)
            or np.any(uv[:,1]>=height)):
        raise ValueError('COMPACT_POINTS_OR_UV_INVALID')
    if n>1 and not np.all((uv[1:,1]>uv[:-1,1]) |
            ((uv[1:,1]==uv[:-1,1]) & (uv[1:,0]>uv[:-1,0]))):
        raise ValueError('COMPACT_UV_ROWMAJOR_ORDER_CHANGED')
    foreground,uncertain=product['point_is_foreground'],product['point_is_uncertain']
    if not np.all(foreground ^ uncertain) or not np.isnan(product['point_uncertainty_m']).all():
        raise ValueError('COMPACT_FLAGS_OR_UNKNOWN_ERROR_CHANGED')
    for key in ('foreground','uncertain'):
        actual=int(product['point_is_'+key].sum())
        if product[key+'_points']!=actual or actual!=counts[key]:
            raise ValueError('COMPACT_ORIGINAL_CLASSIFICATION_COUNTS_CHANGED')
    if product['foreground_points']+product['uncertain_points']!=n:
        raise ValueError('COMPACT_ALL_POINTS_REQUIRED')
    for key,mask in masks.items():
        seal=product['original_mask_seals'][key]
        if mask.dtype!=np.dtype('bool') or mask.shape!=(height,width):
            raise ValueError('COMPACT_ORIGINAL_MASK_CONTRACT_CHANGED')
        equal(seal,dict(dtype=mask.dtype.str,shape=list(mask.shape),
            sha256=sha256(mask.tobytes(order='C')).hexdigest()),'COMPACT_MASK_SEAL_CHANGED')
    candidate=masks['candidate_mask'];unknown=masks['uncertain_candidate_mask']
    if (np.any(candidate & unknown) or int(candidate.sum())!=product['foreground_points']
            or int(unknown.sum())!=product['uncertain_points']
            or not np.array_equal(candidate[uv[:,1],uv[:,0]],foreground)
            or not np.array_equal(unknown[uv[:,1],uv[:,0]],uncertain)):
        raise ValueError('COMPACT_ORIGINAL_UV_FLAGS_OR_CARDINALITY_CHANGED')


def source_contract(product,frame,owner,capture,config,verified,classification):
    refs=config['refs'];projected=product['projected_metadata']
    if (projected['schema']!='base-visible-depth-candidates/0.1'
            or projected['detector_kind']!='EXPECTED_ACTUAL_DEPTH_DIFFERENCE'
            or projected['source_kind']!=frame['source_kind']
            or any(k in projected for k in ('digest','points_base_m','pixel_uv'))
            or any(projected[k] is not False for k in ('execution_allowed','world_clear_allowed',
                'planning_execution_allowed','hardware_execution_allowed'))):
        raise ValueError('COMPACT_ORIGINAL_PROJECTED_METADATA_CONTRACT_CHANGED')
    equal(product['source_frame_ref'],refs['depth_frame'],'COMPACT_FRAME_REF_CHANGED')
    equal(product['source_frame_digest'],_digest(frame),'COMPACT_SOURCE_FRAME_DIGEST_CHANGED')
    for key in SOURCE+('q_rad','robot_state_stamp_s','transform_stamp_s','received_stamp_s',
            'base_frame_id','tool_frame_id','optical_frame_id','calibration_id','calibration_scope'):
        equal(projected[key],frame[key],'COMPACT_PROJECTED_SOURCE_CHANGED:'+key)
    for key in ('q_rad','grip_rad','attachment_tcp_to_block'):
        equal(owner[key],frame[key],'COMPACT_CURRENT_OWNER_FRAME_CHANGED:'+key)
    equal(owner['state_stamp_s'],frame['robot_state_stamp_s'],'COMPACT_OWNER_ENDPOINT_CHANGED')
    equal(product['map_ref'],refs['known_map'],'COMPACT_MAP_REF_CHANGED')
    verified.append(product['map_ref']);known=read_known_map_source(product['map_ref'])
    equal(projected['map_digest'],known['digest'],'COMPACT_MAP_DIGEST_CHANGED')
    equal(known['digest'],config['expected_known_map_digest'],'COMPACT_EXPECTED_MAP_CHANGED')
    for key in ('session_id','clock_epoch','model_manifest_sha256'):
        equal(known['metadata'][key],owner[key],'COMPACT_KNOWN_MAP_OWNER_CHANGED')
    equal(product['model_ref']['sha256'],owner['model_manifest_sha256'],'COMPACT_MODEL_CHANGED')
    request=yaml.safe_load(_read(refs['anchor_request'],binary=True));verified.append(refs['anchor_request'])
    equal(product['model_ref'],dict(path=str((Path(request['model_bundle']['bundle_path'])/'MODEL_MANIFEST.json').resolve()),
        sha256=request['model_bundle']['manifest_sha256']),'COMPACT_ORIGINAL_MODEL_REF_CHANGED')
    refs_read(product['model_ref'],verified)
    error=refs_read(product['error_model_ref'],verified)
    equal(projected['error_model_digest'],_digest(error),'COMPACT_ERROR_MODEL_DIGEST_CHANGED')
    equal(error['qualification_ref'],projected['qualification_ref'],'COMPACT_QUALIFICATION_REF_CHANGED')
    qualification=refs_read(projected['qualification_ref'],verified)
    equal(qualification['model_manifest_sha256'],owner['model_manifest_sha256'],
        'COMPACT_QUALIFICATION_MODEL_CHANGED')
    if frame['session_id'] not in qualification['capture_sessions']:
        raise ValueError('COMPACT_QUALIFICATION_SESSION_CHANGED')
    if qualification['scope']!='SIM_TEST_REPORT_ONLY' or qualification['future_guarantee'] is not False:
        raise ValueError('COMPACT_QUALIFICATION_SCOPE_CHANGED')
    # Original qualification excludes the per-frame cameraViewTransform. Its
    # actual pose remains bound through the complete original frame digest.
    equal(qualification['camera_scope'],camera_scope(frame),'COMPACT_QUALIFICATION_CAMERA_CHANGED')
    equal(projected['effective_pixel_convention']['qualification_ref'],projected['qualification_ref'],
        'COMPACT_PIXEL_QUALIFICATION_CHANGED')
    equal(projected['effective_pixel_convention']['offset_uv'],qualification['offset_uv'],
        'COMPACT_PIXEL_CONVENTION_CHANGED')
    if (error['point_error_m'] is not None or product['point_error_m'] is not None
            or product['valid_until_s'] is not None or product['motion_bound_ref'] is not None
            or product['observability_ref'] is not None or projected['point_uncertainty_bound_m'] is not None):
        raise ValueError('COMPACT_UNKNOWN_BOUND_PROMOTION_REJECTED')
    for parent in error['source_refs']+qualification['source_refs']+frame['source_refs']:
        _read(parent,binary=True);verified.append(parent)
    bundle=refs_read(capture['selected_raw_bundle'],verified)
    index=refs_read(bundle['selected_arrays'],verified)
    equal(index['source_frame_ref'],refs['depth_frame'],'COMPACT_MASK_FRAME_CHANGED')
    equal(index['map_ref'],product['map_ref'],'COMPACT_MASK_MAP_CHANGED')
    equal(index['error_model_ref'],product['error_model_ref'],'COMPACT_MASK_ERROR_MODEL_CHANGED')
    names=('candidate_mask','uncertain_candidate_mask','matched_self','matched_held')
    masks={k:refs_read(index['arrays_and_images'][k],verified,array=True) for k in names}
    array_contract(product,frame,classification['counts'],masks)


def completion_contract(receipt,classification,selected,frame,scope,current):
    if (receipt['schema']!='depth-compact-point-completion/1.0' or receipt['scope']!=scope
            or classification['schema']!='depth-compact-classification-delivery/1.0'
            or classification['scope']!=scope or classification['guard'] is not False):
        raise ValueError('EXPLICIT_COMPACT_COMPLETION_SCHEMA_SCOPE_REQUIRED')
    source={k:frame[k] for k in SOURCE}
    for value in (receipt,classification):
        equal(value['frame_input'],selected['frame_input'],'COMPACT_COMPLETION_FRAME_CHANGED')
        equal(value['source_identity'],source,'COMPACT_COMPLETION_SOURCE_CHANGED')
        if any(value[k] is not True for k in ('completion_fresh','identity_verified','source_order_verified')):
            raise ValueError('COMPACT_COMPLETION_NOT_FRESH_OR_ORDERED')
        observation=value['completion_observation']
        equal({k:observation[k] for k in SOURCE[:3]}, {k:frame[k] for k in SOURCE[:3]},
            'COMPACT_COMPLETION_CLOCK_IDENTITY_CHANGED')
        if (not 0<=observation['source_s']-frame['source_stamp_s']<=.12
                or value['completion_source_age_s']!=observation['source_s']-frame['source_stamp_s']
                or observation['source_s']>current['source_s']):
            raise ValueError('COMPACT_COMPLETION_SOURCE_AGE_CHANGED')
        native=observation['native_stamp'];rational=native['native_current_reference_time']
        if (observation['schema']!='native-current-source-clock/1.0'
                or observation['source_s']!=native['world_time_s']
                or any(type(x) not in (int,float) or not math.isfinite(x) for x in
                    (native['world_time_s'],native['native_simulation_time_s'],native['wall_monotonic_s'],
                     observation['observed_wall_monotonic_s']))
                or type(native['native_physics_step_index']) is not int
                or not frame['source_association']['state_physics_step_index']<=native['native_physics_step_index']
                    <=current['native_stamp']['native_physics_step_index']
                or len(rational)!=2 or any(type(x) is not int for x in rational) or rational[1]<=0
                or not native['wall_monotonic_s']<=observation['observed_wall_monotonic_s']
                    <=current['observed_wall_monotonic_s']):
            raise ValueError('COMPACT_COMPLETION_NATIVE_CLOCK_INVALID')
    equal(receipt['classification_completion_observation'],classification['completion_observation'],
        'COMPACT_CLASSIFICATION_OBSERVATION_CHANGED')
    equal(receipt['classification_completion_source_age_s'],classification['completion_source_age_s'],
        'COMPACT_CLASSIFICATION_AGE_CHANGED')
    if receipt['classification_completion_fresh'] is not True:
        raise ValueError('COMPACT_CLASSIFICATION_NOT_FRESH')
    if any(receipt.get(k) is not False for k in ('SDK_READY','execution_allowed','hardware_execution_allowed',
            'risk_qualified','world_clear_allowed')):
        raise ValueError('COMPACT_COMPLETION_CANNOT_GRANT_ADMISSION')
    if not (receipt['classification_completed_wall_monotonic_s']==classification['completed_wall_monotonic_s']
            <=receipt['point_completed_wall_monotonic_s']<=receipt['carrier_published_wall_monotonic_s']
            <=receipt['main_received_wall_monotonic_s']
            <=classification['completion_observation']['native_stamp']['wall_monotonic_s']
            <=receipt['completion_observation']['native_stamp']['wall_monotonic_s']):
        raise ValueError('COMPACT_CLASSIFICATION_POINT_MAIN_ORDER_CHANGED')
    if classification['completion_observation']['source_s']>receipt['completion_observation']['source_s']:
        raise ValueError('COMPACT_CLASSIFICATION_POINT_SOURCE_ORDER_CHANGED')
    if classification['completion_observation']['native_stamp']['native_physics_step_index']>receipt['completion_observation']['native_stamp']['native_physics_step_index']:
        raise ValueError('COMPACT_CLASSIFICATION_POINT_NATIVE_ORDER_CHANGED')


def review_current_compact_input(config,*,compact_point_provider,capture_provider,
        source_clock_provider,scope=RUNTIME):
    from live_current_cumotion_inputs import current_clock,review_clock_progress,review_source_ages
    if scope not in (RUNTIME,CPU):raise ValueError('EXPLICIT_COMPACT_READER_SCOPE_REQUIRED')
    if not callable(compact_point_provider):return wait('WAIT_MI_CURRENT_COMPACT_PROVIDER_BINDING')
    if not callable(capture_provider) or not callable(source_clock_provider):
        return wait('WAIT_MI_CURRENT_PROVIDER_BINDING')
    before=current_clock(source_clock_provider);selected=compact_point_provider()
    if selected is None:return wait('WAIT_CURRENT_COMPLETE_COMPACT_POINT_PRODUCT')
    packet=selected['packet']
    if type(packet) is not OwnedCompactPoints:raise ValueError('PINNED_OWNED_COMPACT_CLASS_REQUIRED')
    if selected['scope']!=scope:raise ValueError('COMPACT_PROVIDER_SCOPE_CHANGED')
    compact_ref=selected['compact_ref']
    if (compact_ref['path']!='owned-compact-depth:product' or compact_ref['storage']!=STORAGE
            or compact_ref['digest_kind']!=KIND):raise ValueError('EXPLICIT_COMPACT_STORAGE_DIGEST_REQUIRED')
    packet.verify();product=packet.read(compact_ref)
    expected_scope='SAVED_CPU_REPLAY_NOT_RUNTIME' if scope==CPU else 'SOURCE_WORKER_ARRAYS_COMPLETE_NOT_CURRENT_CLOCK_OBSERVED'
    if (product['schema']!='depth-compact-point-product/1.0' or product['digest_kind']!=KIND
            or product['scope']!=expected_scope):raise ValueError('COMPACT_PRODUCT_SCHEMA_SCOPE_CHANGED')
    if any(product.get(k) is not False for k in ('SDK_READY','execution_allowed','risk_qualified','world_clear_allowed')):
        raise ValueError('COMPACT_PRODUCT_CANNOT_GRANT_ADMISSION')
    verified=[];receipt=refs_read(selected['compact_completion_ref'],verified)
    capture_ref=capture_provider()
    if capture_ref is None:return wait('WAIT_CURRENT_COMPLETE_STOPPED_CAPTURE')
    equal(capture_ref,selected['complete_capture_ref'],'COMPACT_CURRENT_CAPTURE_CHANGED')
    equal(receipt['complete_capture_ref'],capture_ref,'COMPACT_RECEIPT_CAPTURE_CHANGED')
    equal(receipt['compact_ref'],compact_ref,'COMPACT_RECEIPT_DESCRIPTOR_CHANGED')
    if (receipt['compact_digest_kind']!=KIND or receipt['compact_digest']!=compact_ref['sha256']
            or receipt['point_count']!=product['point_count']):
        raise ValueError('COMPACT_RECEIPT_DIGEST_OR_COUNT_CHANGED')
    capture=refs_read(capture_ref,verified)
    if capture['scope']!='SAME_ORIGINAL_CAPTURE_FOR_NONEXECUTABLE_STOP_OWNER' or capture['recaptured'] is not False:
        raise ValueError('COMPACT_ORIGINAL_COMPLETE_CAPTURE_REQUIRED')
    equal(capture['frame_input'],config['refs']['depth_frame'],'COMPACT_CAPTURE_FRAME_CHANGED')
    publication=refs_read(capture['owner_publication'],verified)
    equal(publication['owner_ref'],config['refs']['owner'],'COMPACT_CAPTURE_OWNER_CHANGED')
    equal(receipt['owner_ref'],publication['owner_ref'],'COMPACT_RECEIPT_OWNER_REF_CHANGED')
    owner=refs_read(publication['owner_ref'],verified)
    equal({k:owner[k] for k in GENERATION},config['expected_identity'],'COMPACT_OWNER_GENERATION_CHANGED')
    equal(receipt['owner_identity'],{k:owner[k] for k in OWNER},'COMPACT_RECEIPT_OWNER_IDENTITY_CHANGED')
    frame=refs_read(config['refs']['depth_frame'],verified)
    classification=refs_read(receipt['classification_completion_ref'],verified)
    selected_frame=dict(selected,frame_input=config['refs']['depth_frame'])
    source_contract(product,frame,owner,capture,config,verified,classification)
    packet.verify()
    after=current_clock(source_clock_provider);review_clock_progress(before,after)
    review_source_ages(owner,frame,after['source_s'])
    completion_contract(receipt,classification,selected_frame,frame,scope,after)
    if capture_provider()!=capture_ref:raise ValueError('COMPACT_D_CAPTURE_CHANGED_DURING_READ')
    latest=compact_point_provider()
    if latest is None:return wait('WAIT_CURRENT_COMPLETE_COMPACT_POINT_PRODUCT')
    if latest['packet'] is not packet or any(latest[k]!=selected[k] for k in
            ('compact_ref','compact_completion_ref','complete_capture_ref','scope')):
        raise ValueError('COMPACT_SELECTION_CHANGED_DURING_READ')
    for parent in verified:_read(parent,binary=True)
    packet.verify()
    final=current_clock(source_clock_provider);review_clock_progress(after,final)
    review_source_ages(owner,frame,final['source_s'])
    if capture_provider()!=capture_ref:raise ValueError('COMPACT_FINAL_D_CAPTURE_CHANGED')
    last=compact_point_provider()
    if last is None or last['packet'] is not packet or any(last[k]!=selected[k] for k in
            ('compact_ref','compact_completion_ref','complete_capture_ref','scope')):
        raise ValueError('COMPACT_FINAL_SELECTION_CHANGED')
    return dict(status='COMPACT_PAYLOAD_VERIFIED_INPUT_ONLY_WORLD_GEOMETRY_PENDING',payload_verified=True,
        scope=scope,frame_input=config['refs']['depth_frame'],compact_ref=compact_ref,
        compact_completion_ref=selected['compact_completion_ref'],complete_capture_ref=capture_ref,
        point_count=product['point_count'],foreground_points=product['foreground_points'],
        uncertain_points=product['uncertain_points'],point_error_m=None,observability_ref=None,
        motion_bound_ref=None,valid_until_s=None,world_clear_allowed=False,geometry_HOLD=True,
        SDK_READY=False,execution_allowed=False,hardware_execution_allowed=False,
        original_received_stamp_s=frame['received_stamp_s'],current_source_s=final['source_s'])
