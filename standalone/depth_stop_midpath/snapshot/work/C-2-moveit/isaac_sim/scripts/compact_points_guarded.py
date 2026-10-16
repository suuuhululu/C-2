"""Complete immutable point arrays before optional legacy JSON/diagnostics.

Call in the existing worker under its producer-buffer lock after classification.
This packet uses the existing owned-memory transport, with a distinct compact
schema and digest. It is not a generic completed depth-shadow snapshot or a
runtime completion receipt. Main-thread source/owner/link checks remain required.
"""
from copy import deepcopy
from hashlib import sha256
import threading
import time

import numpy as np
from projection_arrays import project_frame_arrays
from isaac_sim.depth_obstacles.novel_depth.geometry import _digest
from isaac_sim.real_execution.novel_depth_consumer import _owned, _content, _read
from plan_only import digest


class OwnedCompactPoints:
    """Distinct packet contract; reuse only the original ownership primitives."""
    __slots__ = ('_payload','_seal')

    def __init__(self,product,frame,parents):
        self._payload = _owned(dict(product=product,frame=frame,parents=list(parents)))
        self._seal = digest(_content(self._payload))

    def verify(self):
        if digest(_content(self._payload)) != self._seal:
            raise ValueError('COMPACT_POINT_PACKET_CHANGED')
        for ref in self._payload['parents']:_read(ref,binary=True)

    def ref(self):
        return dict(path='owned-compact-depth:product',storage='OWNED_COMPACT_DEPTH_POINTS',
            digest_kind='OWNED_NUMPY_ARRAY_CONTENT_SHA256_V1',
            sha256=digest(_content(self._payload['product'])))

    def read(self,ref):
        self.verify()
        if ref != self.ref():raise ValueError('COMPACT_POINT_DESCRIPTOR_CHANGED')
        return self._payload['product']


def timer():return time.perf_counter_ns(),time.thread_time_ns(),threading.get_ident()


def elapsed(start):
    wall,cpu,ident = timer()
    if ident != start[2]:raise ValueError('COMPACT_TIMING_THREAD_CHANGED')
    return dict(wall_s=(wall-start[0])/1e9,thread_CPU_s=(cpu-start[1])/1e9,thread_ident=ident)


def complete_owned_point_arrays(detection, source_frame, *, source_frame_ref,
                                map_ref, error_model_ref, model_ref, origin_refs=(), saved_cpu=False):
    """No raw copy, clock sampling, file write, queue overwrite or early receipt.

    The existing classifier must already have validated/owned Depth and masks.
    Its deferred frame retains the effective projection-derived K/optical TF.
    Keep every original foreground OR uncertain point in its original order.
    """
    input_started = timer()
    if detection['guard'] or detection.get('projected') is not None or '_projection_inputs' not in detection:
        raise ValueError('COMPACT_ORIGINAL_DEFERRED_CLASSIFICATION_REQUIRED')
    pending = detection['_projection_inputs']; frame = pending['frame']
    for key in ('session_id','clock_epoch','clock_basis','frame_seq','source_stamp_s',
                'robot_state_stamp_s','transform_stamp_s','q_rad','grip_rad','attachment_tcp_to_block','T_base_tool'):
        if type(frame[key]) is not type(source_frame[key]) or frame[key] != source_frame[key]:
            raise ValueError('COMPACT_ORIGINAL_SOURCE_CHANGED:'+key)
    expected = pending['expected_metadata']; model = pending['model']
    candidate = detection['candidate_mask']; uncertain = detection['uncertain_candidate_mask']
    selected = pending['selected']; reasons = detection['reason_masks']
    if (candidate.dtype != np.bool_ or uncertain.dtype != np.bool_ or selected.dtype != np.bool_
            or candidate.shape != uncertain.shape or selected.shape != candidate.shape
            or np.any(candidate & uncertain) or not np.array_equal(selected,candidate | uncertain)):
        raise ValueError('COMPACT_ORIGINAL_MASK_UNION_REQUIRED')
    input_timing = elapsed(input_started)
    start = timer()
    projected = project_frame_arrays(frame,np.where(selected,detection['observed_z_m'],np.nan),
        reasons['matched_self'],reasons['matched_held'],now_s=pending['now'],limits=pending['limits'])
    projection_timing = elapsed(start)
    start = timer()
    projected.update(clock_epoch=frame['clock_epoch'],detector_kind='EXPECTED_ACTUAL_DEPTH_DIFFERENCE',
        map_digest=expected['map_digest'],error_model_digest=expected['error_model_digest'],
        source_association_scope=expected['status'],map_scope=expected['map_scope'],execution_allowed=False)
    if pending['scoped']:
        projected.update(qualification_ref=deepcopy(model['qualification_ref']),
            effective_pixel_convention=deepcopy(expected['effective_pixel_convention']),
            classification_scope='SIM_NUMERICAL_TRIAL_NOT_POINT_POSITION_BOUND',point_uncertainty_bound_m=None)
    uv = projected.pop('pixel_uv'); xyz = projected.pop('points_base_m')
    u,v = uv[:,0],uv[:,1]; foreground = candidate[v,u]; uncertain_flags = uncertain[v,u]
    if (not np.array_equal(foreground,detection['point_is_foreground'])
            or not np.all(foreground ^ uncertain_flags)):
        raise ValueError('COMPACT_ORIGINAL_ROWMAJOR_FLAGS_REQUIRED')
    compact = dict(schema='depth-compact-point-product/1.0',
        digest_kind='OWNED_NUMPY_ARRAY_CONTENT_SHA256_V1',projected_metadata=projected,
        points_base_m=xyz,pixel_uv=uv,point_is_foreground=foreground,
        point_is_uncertain=uncertain_flags,point_uncertainty_m=np.full(len(uv),np.nan),
        source_frame_ref=source_frame_ref,source_frame_digest=_digest(source_frame),
        map_ref=map_ref,error_model_ref=error_model_ref,model_ref=model_ref,
        original_mask_seals={k:dict(dtype=a.dtype.str,shape=list(a.shape),sha256=sha256(a.tobytes(order='C')).hexdigest())
            for k,a in [('candidate_mask',candidate),('uncertain_candidate_mask',uncertain),('matched_self',reasons['matched_self']),('matched_held',reasons['matched_held'])]},
        point_count=len(uv),foreground_points=int(foreground.sum()),uncertain_points=int(uncertain_flags.sum()),
        scope='SAVED_CPU_REPLAY_NOT_RUNTIME' if saved_cpu else 'SOURCE_WORKER_ARRAYS_COMPLETE_NOT_CURRENT_CLOCK_OBSERVED',
        runtime_point_ref=None,runtime_projected_digest=None,completion_observation=None,
        point_error_m=None,observability_ref=None,motion_bound_ref=None,valid_until_s=None,
        risk_qualified=False,world_clear_allowed=False,execution_allowed=False,SDK_READY=False)
    metadata_timing = elapsed(start)
    start = timer()
    # No generic shadow packet: it would imply a full raw/detection contract.
    packet = OwnedCompactPoints(compact,source_frame,
        [source_frame_ref,map_ref,error_model_ref,model_ref,*origin_refs])
    packing_timing = elapsed(start)
    start = timer(); compact_ref = packet.ref(); handoff_timing = elapsed(start)
    return dict(packet=packet,compact_ref=compact_ref,
        timings=dict(input_checks=input_timing,projection=projection_timing,metadata=metadata_timing,packing=packing_timing,handoff=handoff_timing),
        complete=True,completion_receipt=None,current_clock=None,runtime_point_ref=None,runtime_projected_digest=None)


def legacy_projected_after_handoff(product):
    """Optional later compatibility export; its digest is never the compact SHA."""
    packet = product['packet'];packet.verify(); compact = packet.read(product['compact_ref'])
    result = deepcopy(compact['projected_metadata'])
    start = timer()
    result.update(points_base_m=compact['points_base_m'].tolist(),pixel_uv=compact['pixel_uv'].tolist())
    list_timing = elapsed(start);start = timer();result['digest'] = _digest(result)
    digest_timing = elapsed(start)
    packet.verify()
    return result,dict(legacy_list_conversion=list_timing,legacy_JSON_digest=digest_timing)
