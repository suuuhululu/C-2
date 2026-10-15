"""Layer height from the flat top-face point between two block studs.

Layer-only diagnostic result. It never produces a position, orientation, grid
cell or verified region; those stay with the existing top-plane/outline path.

Method (RGB finds the studs, Depth only reads the height there):
1. Canny edges + ellipse fit on the gray image inside the instance box find circular
   stud candidates; candidates must lie inside the instance mask.
2. Near-duplicate circles are merged; the pair whose pixel distance is closest to one
   projected stud pitch (focal length * pitch / depth) is taken as two adjacent studs.
3. The Depth points of the instance mask inside a small disc around the pair midpoint
   give the top-face height: median board z, board-baseline corrected, plus the board
   datum offset and one block stud, exactly like the existing reference height.
"""
import itertools
import math

import cv2
import numpy as np

REQUIRED = ('canny_low', 'canny_high', 'minimum_contour_points', 'minimum_diameter_px',
            'maximum_diameter_px', 'minimum_axis_ratio', 'maximum_normalized_residual',
            'merge_px', 'pitch_tolerance_fraction', 'window_radius_px', 'minimum_window_points',
            'mask_dilate_px', 'box_margin_px')


def validate_params(params):
    if not isinstance(params, dict) or set(params) != set(REQUIRED):
        raise ValueError('explicit stud_layer parameters required: ' + ', '.join(REQUIRED))
    for key, value in params.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('positive finite stud_layer parameter required: ' + key)
    if (params['canny_low'] >= params['canny_high'] or params['canny_high'] > 255
            or params['minimum_diameter_px'] >= params['maximum_diameter_px']
            or not 0 < params['minimum_axis_ratio'] <= 1
            or not 0 < params['maximum_normalized_residual'] <= 1
            or not 0 < params['pitch_tolerance_fraction'] < 1
            or params['minimum_contour_points'] < 5):
        raise ValueError('inconsistent stud_layer parameters')


def circle_centers(rgb, mask, params):
    """Centers of ellipse-like edge contours inside the (slightly dilated) mask, merged."""
    ys, xs = np.nonzero(mask)
    margin = int(params['box_margin_px'])
    height, width = mask.shape
    x0, x1 = max(0, int(xs.min()) - margin), min(width, int(xs.max()) + margin + 1)
    y0, y1 = max(0, int(ys.min()) - margin), min(height, int(ys.max()) + margin + 1)
    gray = cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, int(params['canny_low']), int(params['canny_high']))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    size = 2 * int(params['mask_dilate_px']) + 1
    inside = cv2.dilate(mask.astype(np.uint8), np.ones((size, size), np.uint8)) > 0
    centers = []
    for contour in contours:
        if len(contour) < params['minimum_contour_points']:
            continue
        (cx, cy), (axis_a, axis_b), angle = cv2.fitEllipse(contour)
        if (not all(math.isfinite(v) for v in (cx, cy, axis_a, axis_b, angle))
                or min(axis_a, axis_b) < params['minimum_diameter_px']
                or max(axis_a, axis_b) > params['maximum_diameter_px']
                or min(axis_a, axis_b) / max(axis_a, axis_b) < params['minimum_axis_ratio']):
            continue
        points = contour.reshape(-1, 2).astype(float)
        radians = math.radians(angle)
        rotation = np.array([[math.cos(radians), -math.sin(radians)],
                             [math.sin(radians), math.cos(radians)]])
        local = (points - np.array([cx, cy])) @ rotation
        radial = np.sqrt(np.square(local[:, 0] / (axis_a / 2)) + np.square(local[:, 1] / (axis_b / 2)))
        if float(np.mean(np.abs(radial - 1))) > params['maximum_normalized_residual']:
            continue
        u, v = int(round(cx + x0)), int(round(cy + y0))
        if 0 <= v < height and 0 <= u < width and inside[v, u]:
            centers.append((cx + x0, cy + y0))
    groups = []
    for point in centers:
        for group in groups:
            if math.dist(point, np.mean(group, axis=0)) <= params['merge_px']:
                group.append(point)
                break
        else:
            groups.append([point])
    return [np.mean(group, axis=0) for group in groups]


def select_stud_pair(centers, expected_px, tolerance_fraction):
    """Pair closest to one stud pitch in pixels, or None. Also returns how many qualified."""
    allowed = tolerance_fraction * expected_px
    pairs = [pair for pair in itertools.combinations(centers, 2)
             if abs(np.linalg.norm(pair[0] - pair[1]) - expected_px) <= allowed]
    if not pairs:
        return None, 0
    best = min(pairs, key=lambda pair: abs(np.linalg.norm(pair[0] - pair[1]) - expected_px))
    return best, len(pairs)


def stud_layer(rgb, mask, depth, info, calibration, params, *, layer_heights_mm=None,
               height_tolerance_mm=None, height_reference_offset_mm=0., depth_range_m=None,
               block_stud_mm=0., first_layer_min_mm=None, first_layer_max_mm=None,
               layer_upper_bounds_mm=None, board_plane=None):
    """Layer-only result dict. Expected measurement failures return a reason, not an error."""
    validate_params(params)
    result = dict(scope='LAYER_ONLY_STUD_MIDPOINT', layer=None, height_mm=None, reason=None,
                  pair_uv=None, midpoint_uv=None, window_points=None, window_spread_mm=None,
                  expected_pair_px=None, pair_candidates=0)

    def fail(reason):
        result['reason'] = reason
        return result

    if calibration is None or depth is None or info is None:
        raise ValueError('calibration_or_synced_depth_missing')
    if depth.dtype != np.uint16 or depth.shape != mask.shape:
        raise ValueError('aligned_depth_format_mismatch')
    if rgb.shape != (*mask.shape, 3) or rgb.dtype != np.uint8:
        raise ValueError('uint8 aligned RGB required')
    valid = mask & (depth > 0)
    if depth_range_m is not None:
        low, high = depth_range_m
        valid &= (depth.astype(float) * .001 >= low) & (depth.astype(float) * .001 <= high)
    if not valid.any():
        return fail('stud_layer_no_depth')
    k = np.asarray(info['k'], float).reshape(3, 3)
    pitch = float(calibration['pitch_mm'])
    # The studs sit on the top face, which is the part of the mask closest to the camera; the median
    # would include lower faces and make the expected pair distance too small.
    expected_px = float(k[0, 0]) * pitch / float(np.percentile(depth[valid].astype(float), 10))
    result['expected_pair_px'] = expected_px
    centers = circle_centers(rgb, mask, params)
    pair, qualified = select_stud_pair(centers, expected_px, params['pitch_tolerance_fraction'])
    result['pair_candidates'] = qualified
    if pair is None:
        return fail('stud_pair_not_found')
    midpoint = (np.asarray(pair[0]) + np.asarray(pair[1])) / 2
    result['pair_uv'] = [list(map(float, p)) for p in pair]
    result['midpoint_uv'] = list(map(float, midpoint))
    yy, xx = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    radius = float(params['window_radius_px'])
    window = valid & ((xx - midpoint[0]) ** 2 + (yy - midpoint[1]) ** 2 <= radius ** 2)
    v, u = np.nonzero(window)
    result['window_points'] = int(len(u))
    if len(u) < params['minimum_window_points']:
        return fail('stud_window_too_few_depth_points')
    z = depth[v, u].astype(float)
    camera = np.column_stack(((u - k[0, 2]) * z / k[0, 0], (v - k[1, 2]) * z / k[1, 1], z))
    pose = calibration['camera_pose']
    board = (camera - np.asarray(pose['t_camera_from_board_mm'])) @ np.asarray(pose['R_camera_from_board'])
    board[:, 2] *= pose['height_normal_sign']
    spread = float(np.percentile(board[:, 2], 90) - np.percentile(board[:, 2], 10))
    result['window_spread_mm'] = spread
    bias = (board_plane.bias_at(float(np.median(board[:, 0])), float(np.median(board[:, 1])))
            if board_plane is not None else 0.)
    height = float(np.median(board[:, 2])) - bias + height_reference_offset_mm + block_stud_mm
    result['height_mm'] = height
    if layer_heights_mm is None:
        return fail('layer_reference_missing')
    levels = np.asarray(layer_heights_mm, float)
    if (levels.shape not in ((4,), (5,)) or not np.isfinite(levels).all() or np.any(np.diff(levels) <= 0)
            or height_tolerance_mm is None or not np.isfinite(height_tolerance_mm) or height_tolerance_mm <= 0):
        raise ValueError('invalid_or_overlapping_layer_reference')
    from .depth_grid import layer_band_index
    index = layer_band_index(height, levels, height_tolerance_mm, first_layer_min_mm,
                             first_layer_max_mm, upper_bounds=layer_upper_bounds_mm)
    if index is None:
        return fail('height_outside_layer_reference')
    result['layer'] = index + 1
    return result
