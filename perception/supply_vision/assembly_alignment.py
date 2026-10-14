"""Offline body-corner/socket alignment estimates; never motion or 6D poses."""
from copy import deepcopy
from itertools import combinations
import math

import cv2
import numpy as np

from .top_surface import quad_geometry

VERSION = 'round2-assembly-alignment/1'
SCOPES = {'SYNTHETIC_ONLY_TEST', 'OFFLINE_EVIDENCE'}
IDENTITIES = ('request_id', 'job_id', 'plan_id', 'step_id', 'reservation_id', 'grasp_id',
              'profile_version', 'teaching_version', 'calibration_id', 'setup_id',
              'rgb_frame_id', 'board_frame')
GENERATIONS = ('reservation_generation', 'workflow_generation', 'epoch', 'slot_index')
BOTTOM = 'BODY_BOTTOM_ASSEMBLY_SUPPORT'
TOP = 'VISIBLE_BLOCK_TOP'
STUD_TOP = 'VISIBLE_BLOCK_STUD_TOP'
BLOCK_KEYS = {'color', 'brick_type', 'x', 'y', 'layer', 'orientation_deg'}
LIMIT_KEYS = {'max_age_ns', 'max_tilt_deg', 'max_outliers', 'max_fit_residual_m',
              'max_heldout_residual_m', 'max_xy_uncertainty_m', 'max_yaw_uncertainty_deg',
              'max_candidate_xy_m', 'max_candidate_yaw_deg'}
AUTHORITY_KEYS = {'execution_allowed', 'physical_gate_passed', 'next_motion_allowed',
                  'actual_alignment_verified', 'actual_assembly_confirmed', 'b_current_changed',
                  'actual_prerequisites_passed', 'actual_stop_verified'}


def _same(a, b):
    if type(a) is not type(b): return False
    if isinstance(a, dict): return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list): return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _require(condition, reason):
    if not condition: raise ValueError(reason)


def _deny_authority(value):
    if isinstance(value, dict):
        for key, item in value.items():
            _require(key not in AUTHORITY_KEYS or item is False, 'INPUT_AUTHORITY_PROMOTION')
            _require(key != 'robot_target' or item is None, 'INPUT_ROBOT_TARGET_PROMOTION')
            _require(key not in ('physical_commands', 'slot_consumption')
                     or (type(item) is int and item == 0), 'INPUT_PHYSICAL_COMMAND_OR_CONSUMPTION')
            _deny_authority(item)
    elif isinstance(value, list):
        for item in value: _deny_authority(item)


def _points(value, count=None):
    _require(isinstance(value, list) and bool(value), 'POINTS_MISSING')
    _require(all(isinstance(p, list) and len(p) == 2 and all(_finite(v) for v in p) for p in value),
             'POINTS_INVALID_NONFINITE_OR_BOOL')
    array = np.asarray(value, float)
    _require(count is None or len(array) == count, 'POINT_COUNT_MISMATCH')
    return array


def _block(block):
    _require(set(block) == BLOCK_KEYS, 'COMMON_BLOCK_FIELDS_MISMATCH')
    kind, color = block['brick_type'], block['color']
    _require(kind in ('1x2x1', '2x2x1', '2x3x1') and
             (color == 'red' if kind == '1x2x1' else color in ('blue', 'yellow')), 'BLOCK_KIND_COLOR')
    _require(all(type(block[k]) is int for k in ('x', 'y', 'layer', 'orientation_deg')), 'BLOCK_INTEGER_FIELDS')
    _require(block['orientation_deg'] in ((0,) if kind == '2x2x1' else (0, 90)), 'REPRESENTATIVE_ORIENTATION')
    width, depth = map(int, kind.split('x')[:2])
    if block['orientation_deg'] == 90: width, depth = depth, width
    _require(0 <= block['x'] <= 24-width and 0 <= block['y'] <= 24-depth
             and 1 <= block['layer'] <= 5, 'BLOCK_GRID_RANGE')
    return width * depth


def _rigid(record, source, target):
    _require(isinstance(record, dict), 'RIGID_TRANSFORM_MISSING')
    _require(record['from_frame'] == source and record['to_frame'] == target and record['units'] == 'm',
             'TRANSFORM_FRAME_OR_UNIT_MISMATCH')
    raw = record['matrix']
    _require(isinstance(raw, list) and len(raw) == 4 and all(isinstance(r, list) and len(r) == 4
             and all(_finite(v) for v in r) for r in raw), 'RIGID_TRANSFORM_MISSING')
    matrix = np.asarray(raw, float)
    rotation = matrix[:3, :3]
    _require(np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-10, rtol=0)
             and np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-10, rtol=0)
             and np.isclose(np.linalg.det(rotation), 1, atol=1e-10, rtol=0), 'RIGID_TRANSFORM_NOT_PROPER')
    return matrix


def _fit_se2(expected, observed):
    _require(np.linalg.matrix_rank(expected-expected.mean(axis=0), tol=1e-10) == 2,
             'FIT_POINTS_UNDERCONSTRAINED')
    u, _, vt = np.linalg.svd((expected-expected.mean(axis=0)).T @ (observed-observed.mean(axis=0)))
    rotation = vt.T @ u.T
    _require(np.linalg.det(rotation) > 0, 'REFLECTION_OR_AXIS_SWAP')
    return rotation, observed.mean(axis=0)-rotation @ expected.mean(axis=0)


def _robust_fit(expected, observed, threshold, max_outliers):
    best = None
    for subset in combinations(range(len(expected)), 3):
        try:
            rotation, translation = _fit_se2(expected[list(subset)], observed[list(subset)])
        except ValueError:
            continue
        residual = np.linalg.norm(expected @ rotation.T + translation - observed, axis=1)
        inliers = residual <= threshold
        score = (int(inliers.sum()), -float(np.sum(residual[inliers])))
        if best is None or score > best[0]: best = score, inliers
    _require(best is not None and len(expected)-best[0][0] <= max_outliers, 'FIT_OUTLIERS_EXCEED_REVIEWED_LIMIT')
    inliers = best[1]
    rotation, translation = _fit_se2(expected[inliers], observed[inliers])
    residual = np.linalg.norm(expected @ rotation.T + translation - observed, axis=1)
    _require(np.isfinite(residual).all() and (residual[inliers] <= threshold).all(), 'FIT_RESIDUAL_INVALID')
    return rotation, translation, residual, inliers


def estimate_alignment(observation, expected, calibration, binding, *, now_ns):
    """Estimate observed-minus-expected XY/yaw about the expected body centre.

    Explicit mapped metric inputs are mandatory. Original RGB corners remain
    image candidates and cannot manufacture body-bottom metric points.
    """
    output = dict(schema_version=VERSION, status='UNKNOWN', reason=None, scope='OFFLINE_ALIGNMENT_DIAGNOSTIC',
                  binding=deepcopy(binding), e_xy_m=None, e_yaw_deg=None, residuals=None,
                  observed_center_uv=None, projected_expected_center_uv=None,
                  metric_pose=None, robot_target=None, execution_allowed=False,
                  physical_gate_passed=False, next_motion_allowed=False, actual_alignment_verified=False,
                  actual_assembly_confirmed=False, b_current_changed=False, physical_commands=0)
    output.update(projection_consistency_verified=False, registered_mapping_physically_verified=False,
                  limitations=['NO_SOURCE_ARTIFACT_CONTENT_VERIFICATION',
                               'NO_RAW_DEPTH_REPROJECTION_VALIDATION', 'NO_PHYSICAL_CALIBRATION_VALIDATION'])
    try:
        _deny_authority([observation, expected, calibration, binding])
        _require(set(binding) == set(IDENTITIES + GENERATIONS) | {'target_block'}, 'BINDING_FIELDS')
        _require(all(isinstance(binding[k], str) and bool(binding[k].strip()) for k in IDENTITIES), 'BINDING_IDS')
        _require(all(type(binding[k]) is int and binding[k] >= (0 if k == 'epoch' else 1)
                     for k in GENERATIONS) and binding['slot_index'] <= 5, 'RESERVATION_SLOT_OR_GENERATION')
        count = _block(binding['target_block'])
        for record in (observation, expected, calibration):
            _require(record['schema_version'] == VERSION and _same(record['binding'], binding), 'REQUEST_RESERVATION_VERSION_MISMATCH')
        _require(type(now_ns) is int and now_ns >= 0 and type(observation['stamp_ns']) is int
                 and observation['stamp_ns'] >= 0
                 and type(binding['epoch']) is int, 'CLOCK_TYPE')
        _require(calibration['status'] == 'VALID_REGISTERED_COMMON_PLANE', 'CALIBRATION_PENDING')
        _require(calibration['scope'] in SCOPES and observation['scope'] == expected['scope'] == calibration['scope'], 'OFFLINE_SCOPE_MISMATCH')
        _require(observation['frame_id'] == expected['projection_frame_id'] == binding['rgb_frame_id']
                 and observation['pixel_units'] == expected['pixel_units'] == 'pixel'
                 and observation['image_coordinates'] == expected['image_coordinates'] == 'ORIGINAL', 'ORIGINAL_IMAGE_FRAME_OR_UNITS')
        _require(calibration['board_frame'] == binding['board_frame'] and calibration['units'] == 'm'
                 and calibration['axes'] == 'RIGHT_HANDED_XY_Z_NORMAL', 'METRIC_FRAME_UNITS_OR_AXES')
        limits = calibration['reviewed_limits']
        _require(isinstance(limits, dict) and set(limits) == LIMIT_KEYS
                 and all(_finite(v) and v > 0 for k, v in limits.items() if k != 'max_outliers')
                 and type(limits['max_age_ns']) is int
                 and type(limits['max_outliers']) is int and 0 <= limits['max_outliers'] <= 1, 'REVIEWED_LIMITS_INVALID')
        _require(0 <= now_ns-observation['stamp_ns'] <= limits['max_age_ns'], 'OLD_OR_FUTURE_IMAGE')
        _require(observation['occluded'] is False and observation['tilt_verified'] is True
                 and _finite(observation['tilt_deg']) and abs(observation['tilt_deg']) <= limits['max_tilt_deg'], 'OCCLUSION_OR_TILT_UNKNOWN')
        _require(observation['symmetry_resolved'] is True
                 and observation['corner_identity_source'] == 'EXPLICIT_IDENTIFIED_BODY_CORNERS', 'SYMMETRY_OR_CORNER_IDENTITY_UNRESOLVED')
        _require(observation['pixel_plane'] == expected['pixel_plane'] == TOP
                 and expected['projection_source'] == 'HEIGHT_AWARE_VISIBLE_TOP_BODY_MODEL', 'PIXEL_TOP_BOTTOM_PLANE_MISMATCH')
        _require(observation['stud_pixel_plane'] == expected['stud_pixel_plane'] == STUD_TOP,
                 'PIXEL_STUD_BODY_PLANE_MISMATCH')
        observed_uv = _points(observation['corner_uv'], 4)
        projected_uv = _points(expected['projected_corner_uv'], 4)
        observed_studs = _points(observation['stud_uv'], count)
        projected_studs = _points(expected['projected_stud_uv'], count)
        size = observation['image_size']
        _require(isinstance(size, list) and len(size) == 2 and all(type(v) is int and v > 0 for v in size)
                 and _same(size, expected['image_size']) and _same(size, calibration['image_size']), 'ORIGINAL_IMAGE_SIZE_MISMATCH')
        _require(isinstance(observation['clock_domain'], str) and observation['clock_domain'].strip()
                 and observation['clock_domain'] == expected['clock_domain'] == calibration['clock_domain'],
                 'CLOCK_DOMAIN_MISMATCH')
        _require(all((points >= 0).all() and (points < size).all()
                     for points in (observed_uv, projected_uv, observed_studs, projected_studs)), 'ORIGINAL_PIXEL_OUTSIDE_IMAGE')
        output['observed_center_uv'] = quad_geometry(observed_uv, 0)['center_uv']
        output['projected_expected_center_uv'] = quad_geometry(projected_uv, 0)['center_uv']
        _require(_same(expected['block'], binding['target_block']), 'OTHER_GRID_CELL_OR_TARGET')
        depth = calibration['registered_depth']
        _require(isinstance(depth, dict) and depth.get('status') == 'REGISTERED_TO_ORIGINAL_RGB'
                 and type(depth.get('stamp_ns')) is int and depth['stamp_ns'] == observation['stamp_ns']
                 and _finite(depth.get('scale_m_per_unit')) and depth['scale_m_per_unit'] > 0, 'REGISTERED_DEPTH_MISSING')
        raw_intrinsic = calibration['K']
        _require(isinstance(raw_intrinsic, list) and len(raw_intrinsic) == 3
                 and all(isinstance(row, list) and len(row) == 3 and all(_finite(v) for v in row)
                         for row in raw_intrinsic), 'CAMERA_INTRINSICS_INVALID')
        intrinsic = np.asarray(raw_intrinsic, float)
        _require(intrinsic.shape == (3, 3) and np.isfinite(intrinsic).all()
                 and intrinsic[0, 0] > 0 and intrinsic[1, 1] > 0
                 and np.allclose(intrinsic[2], [0, 0, 1]), 'CAMERA_INTRINSICS_INVALID')
        distortion = calibration['distortion']
        _require(isinstance(distortion, dict) and distortion.get('status') == 'ACCOUNTED_BY_HEIGHT_AWARE_PROVIDER'
                 and distortion.get('model') in ('plumb_bob', 'equidistant', 'rational_polynomial')
                 and isinstance(distortion.get('D'), list)
                 and len(distortion['D']) == {'plumb_bob': 5, 'equidistant': 4, 'rational_polynomial': 8}[distortion['model']]
                 and all(_finite(v) for v in distortion['D']), 'DISTORTION_EVIDENCE_MISSING_OR_INVALID')
        mapping = calibration['height_aware_mapping']
        _require(isinstance(mapping, dict) and mapping.get('status') == 'VALIDATED_INDEPENDENT_BODY_DATUM'
                 and mapping['method'] == 'REGISTERED_DEPTH_HEIGHT_AWARE_BODY_DATUM'
                 and mapping['from_plane'] == TOP and mapping['to_plane'] == BOTTOM
                 and mapping['source_id'] and mapping['version'], 'HEIGHT_AWARE_MAPPING_MISSING_OR_HOMOGRAPHY_ONLY')
        _rigid(calibration['T_board_from_camera'], binding['rgb_frame_id'], binding['board_frame'])
        _rigid(calibration['T_bottom_from_top'], TOP, BOTTOM)
        _rigid(calibration['T_bottom_from_stud_top'], STUD_TOP, BOTTOM)
        fit_captures, held_captures = calibration['fit_capture_ids'], calibration['heldout_capture_ids']
        _require(all(isinstance(values, list) and values
                     and all(isinstance(v, str) and v.strip() for v in values)
                     and len(values) == len(set(values))
                     for values in (fit_captures, held_captures, calibration['source_artifact_ids']))
                 and not set(fit_captures) & set(held_captures), 'INDEPENDENT_CALIBRATION_VALIDATION_MISSING')
        _require(observation['metric_plane'] == expected['metric_plane'] == BOTTOM
                 and observation['metric_source'] == 'HEIGHT_AWARE_MAPPED_BODY_AND_SOCKET_AXIS'
                 and expected['metric_source'] == 'REGISTERED_TARGET_BODY_AND_STUD_MODEL', 'METRIC_DATUM_OR_PLANE_MISMATCH')
        observed = {p['id']: p for p in observation['metric_points']}
        projected = {p['id']: p for p in expected['metric_points']}
        corner_ids = [f'corner:{i}' for i in range(4)]
        stud_ids = [f'stud:{i}' for i in range(count)]
        ids = corner_ids + stud_ids
        _require(len(observed) == len(observation['metric_points']) == len(ids)
                 and len(projected) == len(expected['metric_points']) == len(ids)
                 and set(observed) == set(projected) == set(ids), 'METRIC_POINTS_MISSING_OR_DUPLICATED')
        _require(calibration['fit_feature_ids'] == corner_ids and calibration['heldout_feature_ids'] == stud_ids,
                 'FIT_HELDOUT_FEATURE_ROLES_MISMATCH')
        for key in ids:
            _require(observed[key]['role'] == ('BODY_BOTTOM_CORNER' if key in corner_ids else 'BLOCK_SOCKET_AXIS')
                     and projected[key]['role'] == ('BODY_BOTTOM_CORNER' if key in corner_ids else 'TARGET_STUD_CENTER'),
                     'FEATURE_ROLE_OR_INDEX_MISMATCH')
        x = _points([projected[k]['xy_m'] for k in ids])
        y = _points([observed[k]['xy_m'] for k in ids])
        _require(cv2.isContourConvex(x[:4].astype(np.float32)) and cv2.isContourConvex(y[:4].astype(np.float32))
                 and cv2.contourArea(x[:4].astype(np.float32), oriented=True) *
                     cv2.contourArea(y[:4].astype(np.float32), oriented=True) > 0, 'REFLECTION_OR_CORNER_ORDER')
        uncertainty = observation['metric_uncertainty']
        _require(_finite(uncertainty['xy_m']) and 0 <= uncertainty['xy_m'] <= limits['max_xy_uncertainty_m']
                 and _finite(uncertainty['yaw_deg']) and 0 <= uncertainty['yaw_deg'] <= limits['max_yaw_uncertainty_deg'], 'OBSERVATION_UNCERTAINTY_TOO_HIGH_OR_MISSING')
        rotation, translation, residual, inliers = _robust_fit(x[:4], y[:4], limits['max_fit_residual_m'], limits['max_outliers'])
        held_residual = np.linalg.norm(x[4:] @ rotation.T + translation - y[4:], axis=1)
        _require(np.isfinite(held_residual).all() and (held_residual <= limits['max_heldout_residual_m']).all(), 'HELDOUT_SOCKET_STUD_MISMATCH')
        centre = x[:4].mean(axis=0)
        error = rotation @ centre + translation - centre
        yaw = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
        _require(np.isfinite(error).all() and np.linalg.norm(error) <= limits['max_candidate_xy_m']
                 and abs(yaw) <= limits['max_candidate_yaw_deg'], 'OTHER_GRID_CELL_OR_SYMMETRIC_AXIS')
        output.update(status='OFFLINE_ALIGNMENT_ESTIMATE', reason='OFFLINE_RELATIVE_ERROR_ONLY_NOT_EXECUTION',
                      source_scope=calibration['scope'], e_xy_m=error.tolist(), e_yaw_deg=yaw,
                      error_definition='OBSERVED_MINUS_EXPECTED_ABOUT_EXPECTED_BODY_CENTRE',
                      residuals=dict(fit_m=residual.tolist(), inlier_corner_ids=[corner_ids[i] for i in range(4) if inliers[i]],
                                     excluded_corner_ids=[corner_ids[i] for i in range(4) if not inliers[i]],
                                     heldout_m=held_residual.tolist(), heldout_stud_ids=stud_ids))
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, np.linalg.LinAlgError, cv2.error) as error:
        output['reason'] = str(error)
    return output


def synthetic_alignment_case(*, brick_type='2x2x1', color='blue', orientation_deg=0,
                             translation_error_m=(.001, -.0005), yaw_error_deg=.5,
                             scope='SYNTHETIC_ONLY_TEST'):
    """Artificial independent corner/stud fixture, not Lego metrology or live pose."""
    block = dict(color=color, brick_type=brick_type, x=4, y=6, layer=1, orientation_deg=orientation_deg)
    count = _block(block)
    width, depth = map(int, brick_type.split('x')[:2])
    if orientation_deg == 90: width, depth = depth, width
    origin = np.array([.04, .06])
    # Deliberately artificial spacing; never a physical stud pitch or block dimension.
    extent = np.array([width, depth]) * .01
    corners = origin + np.array([[0, 0], [extent[0], 0], extent, [0, extent[1]]])
    studs = origin + np.array([[(i+.5)*.01, (j+.5)*.01] for j in range(depth) for i in range(width)])
    centre = corners.mean(axis=0)
    angle = math.radians(yaw_error_deg)
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    observed = (np.vstack([corners, studs])-centre) @ rotation.T + centre + translation_error_m
    expected_points = [dict(id=f'corner:{i}', role='BODY_BOTTOM_CORNER', xy_m=p.tolist()) for i, p in enumerate(corners)]
    expected_points += [dict(id=f'stud:{i}', role='TARGET_STUD_CENTER', xy_m=p.tolist()) for i, p in enumerate(studs)]
    observed_points = [dict(id=p['id'], role='BODY_BOTTOM_CORNER' if i < 4 else 'BLOCK_SOCKET_AXIS',
                            xy_m=observed[i].tolist()) for i, p in enumerate(expected_points)]
    binding = {key: 'synthetic:'+key for key in IDENTITIES}
    binding.update(reservation_generation=1, workflow_generation=1, epoch=1, slot_index=2, target_block=block)
    uv = [[100., 100.], [210., 100.], [200., 220.], [95., 210.]]
    obs = dict(schema_version=VERSION, scope=scope, binding=deepcopy(binding), stamp_ns=145,
               frame_id=binding['rgb_frame_id'], pixel_units='pixel', image_coordinates='ORIGINAL', image_size=[640, 480],
               clock_domain='SYNTHETIC_NS', pixel_plane=TOP, stud_pixel_plane=STUD_TOP, corner_uv=uv, stud_uv=[[120.+i*5, 140.] for i in range(count)],
               occluded=False, tilt_verified=True, tilt_deg=0., symmetry_resolved=True,
               corner_identity_source='EXPLICIT_IDENTIFIED_BODY_CORNERS', metric_plane=BOTTOM,
               metric_source='HEIGHT_AWARE_MAPPED_BODY_AND_SOCKET_AXIS', metric_points=observed_points,
               metric_uncertainty=dict(xy_m=.00001, yaw_deg=.01))
    exp = dict(schema_version=VERSION, scope=scope, binding=deepcopy(binding), block=deepcopy(block),
               projection_frame_id=binding['rgb_frame_id'], pixel_units='pixel', image_coordinates='ORIGINAL',
               image_size=[640, 480], clock_domain='SYNTHETIC_NS', pixel_plane=TOP, stud_pixel_plane=STUD_TOP, projection_source='HEIGHT_AWARE_VISIBLE_TOP_BODY_MODEL',
               projected_corner_uv=deepcopy(uv), projected_stud_uv=deepcopy(obs['stud_uv']),
               metric_plane=BOTTOM, metric_source='REGISTERED_TARGET_BODY_AND_STUD_MODEL', metric_points=expected_points)
    matrix = np.eye(4)
    top_bottom = np.eye(4); top_bottom[2, 3] = -.02
    stud_bottom = np.eye(4); stud_bottom[2, 3] = -.023
    calibration = dict(schema_version=VERSION, scope=scope, binding=deepcopy(binding),
        status='VALID_REGISTERED_COMMON_PLANE', board_frame=binding['board_frame'], units='m',
        image_size=[640, 480], clock_domain='SYNTHETIC_NS',
        axes='RIGHT_HANDED_XY_Z_NORMAL', K=[[600., 0., 320.], [0., 600., 240.], [0., 0., 1.]],
        distortion=dict(status='ACCOUNTED_BY_HEIGHT_AWARE_PROVIDER', model='plumb_bob', D=[0.]*5),
        registered_depth=dict(status='REGISTERED_TO_ORIGINAL_RGB', stamp_ns=145, scale_m_per_unit=.001),
        height_aware_mapping=dict(status='VALIDATED_INDEPENDENT_BODY_DATUM',
            method='REGISTERED_DEPTH_HEIGHT_AWARE_BODY_DATUM', from_plane=TOP, to_plane=BOTTOM,
            source_id='synthetic-independent-body-datum', version='synthetic-mapping/1'),
        T_board_from_camera=dict(from_frame=binding['rgb_frame_id'], to_frame=binding['board_frame'], units='m', matrix=matrix.tolist()),
        T_bottom_from_top=dict(from_frame=TOP, to_frame=BOTTOM, units='m', matrix=top_bottom.tolist()),
        T_bottom_from_stud_top=dict(from_frame=STUD_TOP, to_frame=BOTTOM, units='m', matrix=stud_bottom.tolist()),
        fit_capture_ids=['synthetic-cal-fit'], heldout_capture_ids=['synthetic-cal-heldout'],
        source_artifact_ids=['synthetic-K-depth-transform-body-datum'],
        fit_feature_ids=[f'corner:{i}' for i in range(4)], heldout_feature_ids=[f'stud:{i}' for i in range(count)],
        reviewed_limits=dict(max_age_ns=20, max_tilt_deg=.1, max_outliers=1,
            max_fit_residual_m=.0001, max_heldout_residual_m=.0001, max_xy_uncertainty_m=.0001,
            max_yaw_uncertainty_deg=.1, max_candidate_xy_m=.005, max_candidate_yaw_deg=5.))
    return dict(observation=obs, expected=exp, calibration=calibration, binding=binding, now_ns=150)
