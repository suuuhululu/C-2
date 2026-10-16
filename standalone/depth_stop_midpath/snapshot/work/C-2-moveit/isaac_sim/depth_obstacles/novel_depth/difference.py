"""Foreground residuals and visible uncertain points; no free-space or STOP claim."""
from copy import deepcopy
from hashlib import sha256
import time

import numpy as np

from ..projection import project_frame
from .geometry import _digest
from .qualification import _half_ulp32


def _guard(frame, expected, limits, now):
    if _digest(frame) != _digest(expected['frame_state']):
        raise ValueError('EXPECTED_ACTUAL_FRAME_STATE_MISMATCH')
    if expected['status'] not in ('FIXTURE', 'ACTUAL_SOURCE_TICK', 'ARCHIVED_SOURCE_TICK_REPLAY'):
        return 'INPUT_UNASSOCIATED'
    if limits['clock_basis'] != frame['clock_basis'] or limits['threshold_status'] != 'SIM_TEST_PARAMETER':
        raise ValueError('EXPLICIT_SIM_FRESHNESS_POLICY_REQUIRED')
    stamps = [now, frame['source_stamp_s'], frame['received_stamp_s'], frame['robot_state_stamp_s'], frame['transform_stamp_s']]
    settings = [limits[k] for k in ('max_age_s', 'max_pose_skew_s', 'min_depth_m', 'max_depth_m')]
    if not np.isfinite(stamps + settings).all() or min(settings) <= 0 or settings[2] >= settings[3]:
        raise ValueError('FINITE_STAMPS_AND_POSITIVE_LIMITS_REQUIRED')
    if not stamps[1] <= stamps[2] <= now:
        return 'INVALID_OR_FUTURE_CLOCK'
    if now-stamps[1] > limits['max_age_s']:
        return 'STALE'
    if max(abs(stamps[3]-stamps[1]), abs(stamps[4]-stamps[1])) > limits['max_pose_skew_s']:
        return 'SOURCE_POSE_SKEW'
    previous = limits.get('previous_frame')
    if previous is not None:
        if any(previous[k] != frame[k] for k in ('session_id', 'clock_basis', 'clock_epoch')):
            return 'SESSION_OR_EPOCH_CHANGED'
        if frame['frame_seq'] <= previous['frame_seq'] or frame['source_stamp_s'] <= previous['source_stamp_s']:
            return 'DUPLICATE_OR_REORDERED'
    return None


def _observed_z(depth, frame, rays):
    raw = np.asarray(depth)
    if raw.shape != (rays['height'], rays['width']):
        raise ValueError('RAW_DEPTH_SHAPE_MISMATCH')
    scale = frame['depth_scale_m']
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('FINITE_POSITIVE_DEPTH_SCALE_REQUIRED')
    if frame['depth_unit'] == 'METER':
        if raw.dtype.kind != 'f' or scale != 1:
            raise ValueError('FLOAT_METRES_SCALE_ONE_REQUIRED')
    elif frame['depth_unit'] != 'SENSOR_UNITS' or raw.dtype != np.uint16:
        raise ValueError('EXPLICIT_UINT16_SENSOR_UNITS_REQUIRED')
    z = raw.astype(float) * scale
    if frame['depth_representation'] == 'RAY_RANGE':
        v, u = np.indices(z.shape)
        z /= np.sqrt(1+((u-rays['cx'])/rays['fx'])**2+((v-rays['cy'])/rays['fy'])**2)
    elif frame['depth_representation'] != 'IMAGE_PLANE_Z':
        raise ValueError('EXPLICIT_DEPTH_REPRESENTATION_REQUIRED')
    return z


def classify_depth(actual_depth, expected, frame_state, limits, *, now_source_s):
    """Return foreground and uncertain visible candidates, with cause masks.

    Source/time failure returns projected=None and a guard, never an empty safe
    observation. Malformed inputs raise ValueError/KeyError. Error-model nulls
    retain all unmatched valid points as uncertain; no invented zero bound.
    Returns owned masks and a private deferred projection context. projected is
    None until materialize_projection; this is not a point-consumer packet.
    Keep the result owned by the worker until its deferred export is complete.
    """
    started = time.perf_counter(); f = deepcopy(frame_state)
    guard = _guard(f, expected, limits, now_source_s)
    if f['source_kind'] == 'SIM_DEPTH' and sha256(np.asarray(actual_depth).tobytes()).hexdigest() != f['depth_array_sha256']:
        raise ValueError('RAW_DEPTH_ARRAY_SOURCE_MISMATCH')
    z = _observed_z(actual_depth, f, expected['ray_intrinsics'])
    valid = np.isfinite(z) & (z >= limits['min_depth_m']) & (z <= limits['max_depth_m'])
    visible = valid & expected['expected_valid']
    residual = np.full(z.shape, np.nan)
    residual[visible] = expected['nearest_z_m'][visible] - z[visible]
    if guard is not None:
        return dict(status=guard, guard=True, projected=None, observed_z_m=z, residual_m=residual,
                    map_digest=expected['map_digest'], source_stamp_s=f['source_stamp_s'],
                    compare_wall_s=time.perf_counter()-started, world_clear_allowed=False)
    model = expected['error_model']
    calibrated = model['status'] in ('MEASURED_BASELINE', 'FIXTURE_PARAMETER')
    ea = model.get('depth_error_m') if calibrated else None
    point_error = model.get('point_error_m') if calibrated else None
    for value in (ea, point_error):
        if value is not None and (not np.isfinite(value) or value < 0):
            raise ValueError('FINITE_NONNEGATIVE_MEASURED_ERROR_REQUIRED')
    required_pixel_status = 'FIXTURE_VALIDATED' if f['source_kind'] == 'FIXTURE' else 'BASELINE_VALIDATED'
    pixel_validated = f['pixel_convention']['status'] == required_pixel_status
    scoped=model['status']=='SIM_SCOPED_NUMERICAL_MODEL'
    if scoped:
        if not expected.get('scoped_qualification') or np.asarray(actual_depth).dtype!=np.float32:
            raise ValueError('SCOPED_FLOAT32_DEPTH_AND_EXPECTED_QUALIFICATION_REQUIRED')
        if any(model.get(k) is not None for k in ('expected_error_m','depth_error_m','point_error_m')):
            raise ValueError('SCOPED_ERRORS_ARE_SEPARATE_ARRAYS_POINT_BOUND_UNKNOWN')
        # Raw float32 storage rounding only. This does not bound sensor noise,
        # q/TF error or the 3D position of an unknown foreground surface.
        with np.errstate(invalid='ignore'):
            ea=_half_ulp32(z)
        pixel_validated=expected['effective_pixel_convention']['status']=='SCOPED_SIM_TEST'
    bounded = visible & np.isfinite(expected['z_lower_m']) & np.isfinite(expected['z_upper_m'])
    bounded &= pixel_validated
    bounded &= False if ea is None else np.isfinite(ea)
    edge = valid & (expected['edge_mask'] | expected['occlusion_ambiguous'])
    matched = np.zeros(z.shape, bool); candidate = matched.copy(); farther = matched.copy()
    if ea is not None:
        lower, upper = expected['z_lower_m'], expected['z_upper_m']
        candidate = bounded & (z+ea < lower) & ~edge
        matched = bounded & (z+ea >= lower) & (z-ea <= upper) & ~edge
        farther = bounded & (z-ea > upper)
    uncertain = valid & ~(matched | candidate)
    owner = expected['nearest_component']
    reasons = dict(invalid_actual=~valid, expected_miss=valid & ~expected['expected_valid'],
        edge_or_occlusion=edge, occlusion_ambiguous=valid & expected['occlusion_ambiguous'],
        occlusion_order_unknown=valid & expected['occlusion_order_unknown'],
        occluded_known_static=valid & expected['occluded_static_mask'], uncertainty_unknown=visible & ~bounded,
        farther_or_model_inconsistent=farther, foreground=candidate,
        matched_static=matched & (owner == 0), matched_self=matched & (owner == 1), matched_held=matched & (owner == 2))
    selected = candidate | uncertain
    # The same renderer-derived ray grid is used for Z/range normalization and
    # projection. Preserve the original calibration in the companion metadata.
    projected_frame = dict(f, intrinsics=dict(expected['ray_intrinsics'], model='none'),
        depth_unit='METER', depth_scale_m=1., depth_representation='IMAGE_PLANE_Z',
        self_mask_status='GEOMETRIC_UNVERIFIED', held_mask_status='GEOMETRIC_UNVERIFIED')
    if 'T_base_camera_optical' in expected:
        projected_frame['T_tool_camera_optical'] = (np.linalg.inv(np.asarray(f['T_base_tool'])) @
                                                   np.asarray(expected['T_base_camera_optical'])).tolist()
    v,u=np.nonzero(selected)
    uv=np.column_stack((u,v))
    classification_finished=time.perf_counter()
    point_uncertainty = np.full(len(uv), np.nan if point_error is None else point_error)
    candidate_flags = candidate[uv[:,1], uv[:,0]]
    return dict(status='PARTIAL_VISIBLE_CANDIDATES' if len(uv) else 'NO_UNMATCHED_VISIBLE_POINTS_NOT_WORLD_CLEAR',
        guard=False, projected=None, observed_z_m=z, residual_m=residual, candidate_mask=candidate,
        uncertain_candidate_mask=uncertain, reason_masks=reasons, point_is_foreground=candidate_flags,
        point_uncertainty_m=point_uncertainty, point_uncertainty_bound_m=point_error,
        uncertainty_status='UNMEASURED' if point_error is None else model['status'],
        map_digest=expected['map_digest'], error_model_digest=expected['error_model_digest'],
        source_association=deepcopy(f['source_association']), pixel_convention=deepcopy(f['pixel_convention']),
        effective_pixel_convention=deepcopy(expected.get('effective_pixel_convention',f['pixel_convention'])),
        qualification_ref=deepcopy(model.get('qualification_ref')),
        classification_scope='SIM_NUMERICAL_TRIAL' if scoped else model['status'],
        point_confidence_meaning='point_is_foreground: optical-Z separation within classification scope; point_uncertainty_m: base 3D radius, NaN means unknown and cannot qualify risk/STOP',
        source_refs=deepcopy(f.get('source_refs', [])), original_intrinsics=deepcopy(f['intrinsics']),
        original_T_tool_camera_optical=deepcopy(f['T_tool_camera_optical']),
        counts=dict(observed_valid=int(valid.sum()), foreground=int(candidate.sum()), uncertain=int(uncertain.sum()),
                    matched_static=int(reasons['matched_static'].sum()), matched_self=int(reasons['matched_self'].sum()),
                    matched_held=int(reasons['matched_held'].sum()), invalid=int((~valid).sum())),
        source_age_s=now_source_s-f['source_stamp_s'], render_wall_s=expected['render_wall_s'],
        _projection_inputs=dict(frame=projected_frame,selected=selected,limits=deepcopy(limits),now=now_source_s,
            expected_metadata={k:deepcopy(expected[k]) for k in ('map_digest','error_model_digest','status','map_scope','effective_pixel_convention') if k in expected},
            model=deepcopy(model),scoped=bool(scoped),validation_wall_s=classification_finished-started),
        compare_timings_s=dict(validation_and_masks=classification_finished-started,
            project_frame_including_list_and_initial_digest=0.,metadata_and_second_digest=0.),
        compare_wall_s=time.perf_counter()-started, world_clear_allowed=False,
        full_shape_known=False, execution_allowed=False)


def materialize_projection(detection):
    """Complete the original full point/list/digest output, without file I/O.

    Consume classify_depth's owned result in the same worker. Publish the
    classification before optional projection/diagnostic export if appropriate;
    consumers that require points must wait for this step. No risk admission is
    implied. This is idempotent and does not re-read source or recompute masks.
    """
    if detection['guard'] or '_projection_inputs' not in detection:
        return detection
    started=time.perf_counter();pending=detection['_projection_inputs']
    f=projected_frame=pending['frame'];selected=pending['selected']
    z=detection['observed_z_m'];reasons=detection['reason_masks'];limits=pending['limits'];now_source_s=pending['now']
    expected=pending['expected_metadata'];model=pending['model'];scoped=pending['scoped']
    projection_started = time.perf_counter()
    projected = project_frame(projected_frame, np.where(selected, z, np.nan), reasons['matched_self'],
                              reasons['matched_held'], now_s=now_source_s, limits=limits)
    projection_finished = time.perf_counter()
    projected.pop('digest')
    projected.update(clock_epoch=f['clock_epoch'], detector_kind='EXPECTED_ACTUAL_DEPTH_DIFFERENCE',
        map_digest=expected['map_digest'], error_model_digest=expected['error_model_digest'],
        source_association_scope=expected['status'], map_scope=expected['map_scope'], execution_allowed=False)
    if scoped:
        projected.update(qualification_ref=deepcopy(model['qualification_ref']),
            effective_pixel_convention=deepcopy(expected['effective_pixel_convention']),
            classification_scope='SIM_NUMERICAL_TRIAL_NOT_POINT_POSITION_BOUND',
            point_uncertainty_bound_m=None)
    digest_started = time.perf_counter()
    projected['digest'] = _digest(projected)
    digest_finished = time.perf_counter()
    # Same nonzero row-major order as project_frame; no point was filtered.
    uv=np.asarray(projected['pixel_uv'],int).reshape(-1,2)
    if len(uv)!=len(detection['point_is_foreground']) or not np.array_equal(
            detection['point_is_foreground'],detection['candidate_mask'][uv[:,1],uv[:,0]]):
        raise ValueError('DEFERRED_PROJECTION_POINT_ORDER_MISMATCH')
    detection['projected']=projected
    detection['compare_timings_s']=dict(validation_and_masks=pending['validation_wall_s'],
        project_frame_including_list_and_initial_digest=projection_finished-projection_started,
        metadata_and_second_digest=digest_finished-digest_started)
    detection['compare_wall_s']+=time.perf_counter()-started
    del detection['_projection_inputs']
    return detection


def compare_depth(actual_depth, expected, frame_state, limits, *, now_source_s):
    """Compatibility API: original complete classification and full point output."""
    return materialize_projection(classify_depth(actual_depth,expected,frame_state,limits,now_source_s=now_source_s))
