"""Pure XY candidates from an operator identified body TOP edge.

No visible-mask centre or centred-grasp assumption is used. The caller owns
RGB/pose freshness and physical edge identity; this module never commands a
robot or promotes the provisional projection to a verified measurement.
"""
import cv2
import numpy as np


def _array(value, shape, reason):
    result = np.asarray(value, dtype=float)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(reason)
    return result


def _transform(value):
    result = _array(value, (4, 4), 'RIGID_BASE_TRANSFORM_REQUIRED')
    rotation = result[:3, :3]
    if (not np.allclose(result[3], [0., 0., 0., 1.]) or
            not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or
            not np.isclose(np.linalg.det(rotation), 1.)):
        raise ValueError('RIGID_BASE_TRANSFORM_REQUIRED')
    return result


def _camera(info):
    if info is None:
        raise ValueError('CAMERA_INFO_REQUIRED')
    if isinstance(info, dict):
        get = info.get
        frame_id = get('frame_id', (get('header') or {}).get('frame_id'))
    else:
        get = lambda key, default=None: getattr(info, key, default)
        frame_id = getattr(get('header'), 'frame_id', None)
    width, height = get('width'), get('height')
    if (type(width) is not int or type(height) is not int or min(width, height) <= 0 or
            not isinstance(frame_id, str) or not frame_id):
        raise ValueError('CAMERA_SIZE_AND_FRAME_REQUIRED')
    if get('distortion_model') not in ('plumb_bob', 'rational_polynomial', 'none'):
        raise ValueError('UNSUPPORTED_DISTORTION_MODEL')
    k = np.asarray(get('k'), dtype=float).reshape(3, 3)
    d = np.asarray(get('d'), dtype=float).reshape(-1)
    if (not np.isfinite(k).all() or not np.isfinite(d).all() or
            min(k[0, 0], k[1, 1]) <= 0 or
            not np.allclose(k[2], [0., 0., 1.]) or d.size not in (0, 4, 5, 8, 12, 14)):
        raise ValueError('FINITE_PINHOLE_INTRINSICS_REQUIRED')
    return k, d, width, height, frame_id


def _depth_points(depth, scale, stamps, frame_id, camera_frame, edge, rays, camera, size):
    rgb_stamp, depth_stamp = stamps
    if (type(rgb_stamp) is not int or type(depth_stamp) is not int or
            min(rgb_stamp, depth_stamp) <= 0 or abs(rgb_stamp-depth_stamp) > 50_000_000):
        raise ValueError('DEPTH_RGB_PAIR_TIMING_UNAVAILABLE')
    if frame_id != camera_frame:
        raise ValueError('DEPTH_RGB_REGISTRATION_FRAME_MISMATCH')
    if type(scale) not in (int, float) or not np.isfinite(scale) or scale <= 0:
        raise ValueError('DEPTH_SCALE_MM_REQUIRED')
    array = np.asarray(depth)
    width, height = size
    if array.shape != (height, width) or not np.issubdtype(array.dtype, np.number):
        raise ValueError('REGISTERED_DEPTH_IMAGE_REQUIRED')
    # Read only the selected endpoints. Neighbour averaging can mix a body
    # corner with the board behind it and fabricate a top-surface height.
    uv = np.floor(edge + .5).astype(int)
    if (uv[:, 0] >= width).any() or (uv[:, 1] >= height).any():
        raise ValueError('DEPTH_ENDPOINT_OUTSIDE_IMAGE')
    z = array[uv[:, 1], uv[:, 0]].astype(float) * scale
    if not np.isfinite(z).all() or (z <= 0).any():
        raise ValueError('VALID_DEPTH_AT_BOTH_ENDPOINTS_REQUIRED')
    optical = rays * z[:, None]
    return optical @ camera[:3, :3].T + camera[:3, 3]


def held_edge_xy_candidate(edge_uv, edge_index, camera_info, projection, *,
                           depth=None, depth_scale_mm=None, rgb_stamp_ns=None,
                           depth_stamp_ns=None, depth_frame_id=None):
    """Return the Base XY translation that aligns the same physical top edge.

    ``edge_index`` explicitly identifies the corresponding consecutive pair in
    ``target_hover_outline_base_mm``; endpoints may be selected in either order.
    Without usable paired depth, both rays intersect the target hover plane.
    This height assumption remains explicit even when a candidate is returned.
    Depth provides two endpoint positions, not a full roll/pitch plane estimate.
    """
    result = dict(status='UNAVAILABLE', reason=None, delta_base_xy_mm=None,
                  physical_accuracy_verified=False, execution_allowed=False,
                  physical_commands=0, roll_pitch_observed=False,
                  edge_identity_source='OPERATOR_SELECTED_PHYSICAL_TOP_EDGE')
    try:
        if type(edge_index) is not int or not 0 <= edge_index <= 3:
            raise ValueError('PHYSICAL_TARGET_EDGE_SELECTION_REQUIRED')
        edge = _array(edge_uv, (2, 2), 'TWO_PHYSICAL_TOP_ENDPOINTS_REQUIRED')
        if np.linalg.norm(edge[1]-edge[0]) <= 1e-9:
            raise ValueError('DISTINCT_PHYSICAL_TOP_ENDPOINTS_REQUIRED')
        k, d, width, height, frame_id = _camera(camera_info)
        if (edge < 0).any() or (edge >= [width, height]).any():
            raise ValueError('TOP_ENDPOINT_OUTSIDE_RGB')
        camera = _transform(projection['T_base_from_camera_mm'])
        board = _transform(projection['T_base_from_board_mm'])
        outline = _array(projection['target_hover_outline_base_mm'], (4, 3),
                         'TARGET_HOVER_BODY_OUTLINE_REQUIRED')
        normal = board[:3, 2]
        plane_offsets = outline @ normal
        if np.ptp(plane_offsets) > 1e-6:
            raise ValueError('TARGET_BODY_OUTLINE_PLANE_REQUIRED')
        target_edge = outline[[edge_index, (edge_index+1) % 4]]
        if np.linalg.norm(target_edge[1]-target_edge[0]) <= 1e-9:
            raise ValueError('DISTINCT_TARGET_TOP_ENDPOINTS_REQUIRED')
        normalized = cv2.undistortPoints(edge.reshape(2, 1, 2), k, d).reshape(2, 2)
        if not np.isfinite(normalized).all():
            raise ValueError('FINITE_UNDISTORTED_TOP_RAYS_REQUIRED')
        rays = np.column_stack((normalized, np.ones(2)))
        directions = rays @ camera[:3, :3].T
        origin = camera[:3, 3]
        divisor = directions @ normal
        if (np.abs(divisor) <= 1e-12).any():
            raise ValueError('TOP_RAY_PARALLEL_TO_TARGET_PLANE')
        distances = (plane_offsets[0]-origin @ normal)/divisor
        if (distances <= 0).any():
            raise ValueError('TARGET_BODY_PLANE_BEHIND_CAMERA')
        observed = origin + distances[:, None]*directions
        source = 'TARGET_HOVER_HEIGHT_ASSUMED'
        depth_reason = None
        if depth is not None:
            try:
                observed = _depth_points(depth, depth_scale_mm, (rgb_stamp_ns, depth_stamp_ns),
                    depth_frame_id, frame_id, edge, rays, camera, (width, height))
                source = 'PAIRED_DEPTH_ENDPOINTS_UNVERIFIED'
            except (ValueError, TypeError, OverflowError) as error:
                depth_reason = str(error)
        observed_midpoint = observed.mean(axis=0)
        target_midpoint = target_edge.mean(axis=0)
        delta = target_midpoint-observed_midpoint
        if not np.isfinite(delta).all():
            raise ValueError('FINITE_EDGE_TRANSLATION_REQUIRED')
        result.update(status='HELD_EDGE_XY_CANDIDATE', edge_index=edge_index,
            observed_edge_uv=edge.tolist(), observed_edge_base_mm=observed.tolist(),
            observed_edge_midpoint_base_mm=observed_midpoint.tolist(),
            target_edge_midpoint_base_mm=target_midpoint.tolist(),
            delta_base_xy_mm=delta[:2].tolist(),
            observed_endpoint_height_offsets_mm=(observed @ normal-plane_offsets[0]).tolist(),
            height_source=source, height_assumed=source == 'TARGET_HOVER_HEIGHT_ASSUMED',
            depth_reason=depth_reason, centred_grasp_assumed=False,
            projection_independently_verified=projection.get('projection_independently_verified') is True,
            assumptions=['OPERATOR_IDENTIFIED_SAME_PHYSICAL_TOP_EDGE',
                         'TARGET_HOVER_PLANE_ASSUMED' if source == 'TARGET_HOVER_HEIGHT_ASSUMED'
                         else 'REGISTERED_DEPTH_ENDPOINTS_NOT_INDEPENDENTLY_VALIDATED',
                         'PURE_XY_TRANSLATION_YAW_HANDLED_SEPARATELY'])
    except (ValueError, TypeError, KeyError, OverflowError, cv2.error) as error:
        result['reason'] = str(error)
    return result
