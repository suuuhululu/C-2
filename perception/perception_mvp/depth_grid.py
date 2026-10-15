"""Visible top-surface measurement; outputs are internal candidates only."""
from dataclasses import dataclass

import cv2
import numpy as np

from .rgbd_io import load_frame
from .backend_adapter import build_observed
from .contracts import candidate_to_block, LIVE_CLASSES, footprint

CLASSES = LIVE_CLASSES


# --- Layer rule (shared by the team path here and by integrated_view/live_view; unit agnostic) ---
# Default: a height belongs to the nearest layer when within +/- tolerance of that layer's reference.
# Owner decision 2026-10-14: layer 1 is first_layer_min..first_layer_max (6..25mm) when a minimum
# is configured; without a maximum, layer 1 ends at reference + tolerance.
# Owner decision 2026-10-14 (later): when upper_bounds are given, the layers are contiguous bands.
# Layer 1 is first_layer_min..upper_bounds[0]; layer n is upper_bounds[n-2]..upper_bounds[n-1];
# a shared edge belongs to the lower layer; above the last bound (or below first_layer_min) is None.
# Owner decision 2026-10-15: with bounds, first_layer_max (if given) is layer 1's own upper edge and may
# lie below upper_bounds[0]; heights between first_layer_max and upper_bounds[0] belong to no layer (None).
def validate_first_layer_range(first_layer_min, first_layer_max, levels, tolerance=0.):
    if first_layer_min is None and first_layer_max is None:
        return
    levels = np.asarray(levels, float)
    if first_layer_min is not None and (
            not np.isfinite(first_layer_min) or not 0 <= first_layer_min < levels[0]):
        raise ValueError('invalid_first_layer_min')
    if first_layer_max is not None and (
            not np.isfinite(first_layer_max) or first_layer_max < levels[0] or
            (len(levels) > 1 and first_layer_max >= levels[1] - tolerance)):
        raise ValueError('invalid_first_layer_max')


def validate_layer_upper_bounds(upper_bounds, levels, first_layer_min=None):
    """Upper edge per layer: finite, increasing, one per layer, each at or above its own reference."""
    if upper_bounds is None:
        return
    bounds = np.asarray(upper_bounds, float)
    levels = np.asarray(levels, float)
    if (bounds.shape != levels.shape or not np.isfinite(bounds).all() or np.any(np.diff(bounds) <= 0) or
            np.any(bounds < levels) or np.any(bounds[:-1] >= levels[1:])):
        raise ValueError('invalid_layer_upper_bounds')
    if first_layer_min is not None and (not np.isfinite(first_layer_min) or
                                        not 0 <= first_layer_min < bounds[0]):
        raise ValueError('invalid_first_layer_min')


def layer_band_index(height, levels, tolerance, first_layer_min=None, first_layer_max=None,
                     upper_bounds=None):
    """Return the zero-based layer index or None when the height is outside every band."""
    levels = np.asarray(levels, float)
    if upper_bounds is not None:
        validate_layer_upper_bounds(upper_bounds, levels, first_layer_min)
        bounds = np.asarray(upper_bounds, float)
        low = first_layer_min if first_layer_min is not None else bounds[0] - (bounds[1] - bounds[0])
        if height < low and not np.isclose(height, low, rtol=1e-9, atol=0.):
            return None
        if first_layer_max is not None:
            if (not np.isfinite(first_layer_max) or first_layer_max < levels[0] or first_layer_max > bounds[0]
                    or (first_layer_min is not None and first_layer_max <= first_layer_min)):
                raise ValueError('invalid_first_layer_max')
            if (height > first_layer_max and not np.isclose(height, first_layer_max, rtol=1e-9, atol=0.) and
                    (height <= bounds[0] or np.isclose(height, bounds[0], rtol=1e-9, atol=0.)) and
                    first_layer_max < bounds[0]):
                return None  # gap between layer 1's own upper edge and the shared bound
        for index, bound in enumerate(bounds):
            if height <= bound or np.isclose(height, bound, rtol=1e-9, atol=0.):
                return index
        return None
    validate_first_layer_range(first_layer_min, first_layer_max, levels, tolerance)
    index = int(np.argmin(np.abs(levels - height)))
    if index == 0 and (first_layer_min is not None or first_layer_max is not None):
        low = first_layer_min if first_layer_min is not None else levels[0] - tolerance
        high = first_layer_max if first_layer_max is not None else levels[0] + tolerance
    else:
        low, high = levels[index] - tolerance, levels[index] + tolerance
    # Unit conversion can move an exact boundary by a few float bits; never reject it for that.
    inside = ((low <= height or np.isclose(height, low, rtol=1e-9, atol=0.)) and
              (height <= high or np.isclose(height, high, rtol=1e-9, atol=0.)))
    return index if inside else None


# --- Per-capture board baseline (owner decision 2026-10-14, option A; mm or m, caller's unit) ---
# Depth can read the board plate a few mm away from the calibration datum (measured 2026-10-14:
# about -5mm at V0). Each capture fits the board plane from pixels NOT on a detected block, and a
# block's layer height is taken relative to that plane. The expected plate height comes from the
# caller (flat-board zero: 0, stud-top zero: minus the board stud height). An unreliable fit raises
# ValueError and the block stays UNKNOWN; never a silent fallback. Trial method, not validated.
GEOMETRY_KEYS = ('board_baseline', 'board_baseline_min_points', 'board_baseline_max_tilt_deg',
                 'board_baseline_max_residual_std_m', 'board_baseline_max_correction_m',
                 'board_baseline_exclusion_px', 'board_baseline_z_window_m')


@dataclass(frozen=True)
class BoardPlane:
    a: float
    b: float
    c: float
    expected_plate_z: float
    points: int
    residual_std: float
    tilt_deg: float

    def bias_at(self, x, y):
        """Measured plate height minus its expected height at (x, y); subtract it from heights."""
        return float(self.a * x + self.b * y + self.c - self.expected_plate_z)


def params_from_geometry(config, unit_per_m):
    """Fit parameters from config.geometry, or None when the baseline is not enabled."""
    mode = config.get('board_baseline')
    if mode is None:
        return None
    if mode != 'PLATE_PLANE_FIT':
        raise ValueError('unsupported_board_baseline_mode')
    missing = [key for key in GEOMETRY_KEYS if config.get(key) is None]
    if missing:
        raise ValueError('board_baseline_settings_missing: ' + ', '.join(missing))
    return dict(min_points=int(config['board_baseline_min_points']),
                max_tilt_deg=float(config['board_baseline_max_tilt_deg']),
                max_residual_std=float(config['board_baseline_max_residual_std_m']) * unit_per_m,
                max_correction=float(config['board_baseline_max_correction_m']) * unit_per_m,
                exclusion_px=int(config['board_baseline_exclusion_px']),
                z_window=float(config['board_baseline_z_window_m']) * unit_per_m)


def exclusion_mask(union, pixels):
    """Detected blocks grown by `pixels`, so their edges never enter the board fit."""
    import cv2
    size = 2 * int(pixels) + 1
    return cv2.dilate(union.astype(np.uint8), np.ones((size, size), np.uint8)) > 0


def sampled_pixels(valid, stride=4):
    """Every `stride`-th valid pixel on a regular grid (keeps the fit fast and unbiased)."""
    keep = np.zeros(valid.shape, bool)
    keep[::stride, ::stride] = True
    return np.nonzero(valid & keep)


def fit_board_plane(points, *, expected_plate_z, bounds, min_points, max_tilt_deg,
                    max_residual_std, max_correction, z_window, **_ignored):
    """Robust plane z = a*x + b*y + c through board-frame points (x, y, z)."""
    points = np.asarray(points, float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError('board_baseline_invalid_points')
    (x0, x1), (y0, y1) = np.asarray(bounds, float)
    inside = ((points[:, 0] >= x0) & (points[:, 0] <= x1) & (points[:, 1] >= y0) &
              (points[:, 1] <= y1) & (abs(points[:, 2] - expected_plate_z) <= z_window))
    points = points[inside]
    if len(points) < min_points:
        raise ValueError('board_baseline_insufficient_points')
    design = np.column_stack((points[:, 0], points[:, 1], np.ones(len(points))))
    keep = np.ones(len(points), bool)
    for _ in range(5):  # Clip the studs/noise tails; the dominant surface is the plate.
        coef = np.linalg.lstsq(design[keep], points[keep, 2], rcond=None)[0]
        residual = points[:, 2] - design @ coef
        spread = residual[keep].std()
        keep = abs(residual) <= 2 * spread + 1e-12
        if keep.sum() < min_points:
            raise ValueError('board_baseline_insufficient_points')
    coef = np.linalg.lstsq(design[keep], points[keep, 2], rcond=None)[0]
    residual = points[keep, 2] - design[keep] @ coef
    tilt = float(np.degrees(np.arctan(np.hypot(coef[0], coef[1]))))
    if tilt > max_tilt_deg:
        raise ValueError('board_baseline_tilted')
    if residual.std() > max_residual_std:
        raise ValueError('board_baseline_noisy')
    plane = BoardPlane(float(coef[0]), float(coef[1]), float(coef[2]), float(expected_plate_z),
                       int(keep.sum()), float(residual.std()), tilt)
    centre = points[:, :2].mean(axis=0)
    if abs(plane.bias_at(*centre)) > max_correction:
        raise ValueError('board_baseline_out_of_range')
    return plane


def board_pose_bundle(calibrations, calibration_id, *, stud_height_mm):
    """Convert existing validated stud-top poses to flat-board metre transforms.

    This changes only the runtime datum, never the original calibration or layer
    measurements. Callers must use top_heights_m measured from that same datum.
    """
    if set(calibrations) != {'V0', 'D1', 'D3'}:
        raise ValueError('three actual View calibrations required')
    if not isinstance(calibration_id, str) or not calibration_id.strip():
        raise ValueError('explicit runtime calibration ID required')
    if not np.isfinite(stud_height_mm) or stud_height_mm <= 0:
        raise ValueError('measured positive board stud height required')
    transforms = {}
    for view, source in calibrations.items():
        if (source['view_id'] != view or source['independently_validated'] is not True or
                source['rows'] != 24 or source['cols'] != 24 or source['pitch_mm'] != 16.):
            raise ValueError('validated 24x24/pitch16 View calibration required')
        if source['reference_plane'] != 'plane through reference points, normally empty stud tops':
            raise ValueError('explicit stud-top source datum required')
        pose = source['camera_pose']
        if pose['height_normal_sign'] != 1:
            raise ValueError('right-handed positive height pose required; no reflection fallback')
        rotation = np.asarray(pose['R_camera_from_board'], dtype=float)
        translation = np.asarray(pose['t_camera_from_board_mm'], dtype=float) / 1000.
        if rotation.shape != (3, 3) or translation.shape != (3,):
            raise ValueError('measured 3x3 rotation and three-component translation required')
        transform = np.eye(4)
        transform[:3, :3] = rotation.T
        transform[:3, 3] = -rotation.T @ translation
        transform[2, 3] += stud_height_mm / 1000.
        # Same rigid-transform validation used by actual Depth processing.
        validate_geometry(.001, dict(model='none', fx=1., fy=1., cx=0., cy=0.), transform)
        transforms[view] = transform.tolist()
    return dict(calibration_id=calibration_id, views=transforms,
                height_reference='BOARD_FLAT_SURFACE_ZERO',
                source_reference='BOARD_STUD_TOP_ZERO', board_stud_height_mm=float(stud_height_mm))


def depth_ranges_from_board(calibration, board_bounds_m, top_height_m, *, margin_m):
    """Camera optical Z bounds of the board-to-top cuboid, not ray length.

    Linear rigid transforms attain extrema at corners. Margin is an explicitly
    chosen trial allowance, not a measured sensor accuracy or safety allowance.
    """
    from itertools import product
    bounds = np.asarray(board_bounds_m, float)
    if (bounds.shape != (2, 2) or not np.isfinite(bounds).all() or
            np.any(bounds[:, 0] >= bounds[:, 1]) or not np.isfinite(top_height_m) or
            top_height_m <= 0 or not np.isfinite(margin_m) or margin_m < 0):
        raise ValueError('finite board bounds, positive top height and nonnegative margin required')
    if calibration.get('height_reference') != 'BOARD_FLAT_SURFACE_ZERO':
        raise ValueError('flat-board zero calibration required')
    corners = np.array(list(product(bounds[0], bounds[1], [0., top_height_m])))
    result = {}
    for view, matrix in calibration['views'].items():
        transform = validate_geometry(.001, dict(model='none', fx=1., fy=1., cx=0., cy=0.), matrix)
        camera = (corners - transform[:3, 3]) @ transform[:3, :3]
        minimum, maximum = float(camera[:, 2].min()) - margin_m, float(camera[:, 2].max()) + margin_m
        if minimum <= 0:
            raise ValueError('board volume is behind/too close to camera: ' + view)
        result[view] = dict(min_depth_m=minimum, max_depth_m=maximum)
    return result


def config_for_view(config, view):
    """Use explicit per-View limits; missing configured View never falls back."""
    ranges = config.get('depth_ranges_m')
    if ranges is None:
        return config  # Existing callers with explicit global limits remain valid.
    if view not in ranges:
        raise ValueError('depth range missing for View: ' + view)
    return dict(config, min_depth_m=ranges[view]['min_depth_m'],
                max_depth_m=ranges[view]['max_depth_m'])


def validate_config(config):
    if config.get('block_surface_height_basis') is not None:
        if (config['block_surface_height_basis'] not in (
                    'BODY_TOP_PLUS_STUD', 'DIRECT_STUD_TOP', 'TOP_PLANE_PLUS_STUD') or
                not np.isfinite(config.get('block_stud_height_m', np.nan)) or
                config['block_stud_height_m'] <= 0):
            raise ValueError('explicit surface basis and positive physical block stud height required')
    missing = [key for key, value in config.items() if value is None]
    if missing:
        raise ValueError("measured geometry settings not provided: " + ", ".join(missing))
    positive = ("stud_pitch_m", "grid_tolerance_stud", "size_tolerance_m",
                "height_tolerance_m", "max_height_spread_m", "min_depth_m",
                "max_depth_m", "angle_tolerance_deg", "min_depth_pixels")
    for key in positive:
        if not np.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"invalid setting: {key}")
    for key in ("min_confidence", "min_valid_fraction"):
        if not 0 < config[key] <= 1:
            raise ValueError(f"invalid setting: {key}")
    heights = np.asarray(config["top_heights_m"], dtype=float)
    if heights.shape not in ((4,), (5,)) or not np.isfinite(heights).all() or np.any(np.diff(heights) <= 0):
        raise ValueError("four or five increasing measured top heights required; fifth layer needs its measured height")
    if config["height_tolerance_m"] * 2 >= np.min(np.diff(heights)):
        raise ValueError("layer tolerance intervals overlap")
    validate_first_layer_range(config.get("first_layer_min_height_m"),
                               config.get("first_layer_max_height_m"), heights, config["height_tolerance_m"])
    validate_layer_upper_bounds(config.get("layer_upper_bounds_m"), heights, config.get("first_layer_min_height_m"))
    if config["min_depth_m"] >= config["max_depth_m"]:
        raise ValueError("invalid depth range")
    if config["threshold_status"] not in ("temporary_test", "validated"):
        raise ValueError("threshold_status required")
    if config["point_reference"] != "visible_surface_center":
        raise ValueError("only internal visible_surface_center is supported")
    if not config["coordinate_rules"] or not config["calibration_id"]:
        raise ValueError("explicit coordinate rules and calibration ID required")


def validate_geometry(scale, intrinsics, camera_to_board):
    transform = np.asarray(camera_to_board, dtype=float)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("finite 4x4 Camera-to-Board transform required")
    rotation = transform[:3, :3]
    if (not np.allclose(transform[3], [0, 0, 0, 1]) or
            not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5) or
            not np.isclose(np.linalg.det(rotation), 1)):
        raise ValueError("transform must be rigid, right-handed")
    if intrinsics["model"] not in ("none", "brown_conrady", "inverse_brown_conrady"):
        raise ValueError("unsupported RealSense deprojection distortion model")
    if intrinsics["model"] != "none":
        coefficients = np.asarray(intrinsics["coefficients"], dtype=float)
        if coefficients.shape != (5,) or not np.isfinite(coefficients).all():
            raise ValueError("five actual camera distortion coefficients required")
    if any(not np.isfinite(intrinsics[k]) for k in ("fx", "fy", "cx", "cy")):
        raise ValueError("invalid intrinsics")
    if min(intrinsics["fx"], intrinsics["fy"], scale) <= 0 or not np.isfinite(scale):
        raise ValueError("invalid focal length or scale")
    return transform


def deproject_pixels(u, v, distances, intrinsics, width, height):
    if intrinsics["model"] == "none":
        return np.column_stack(((u - intrinsics["cx"]) * distances / intrinsics["fx"],
                                (v - intrinsics["cy"]) * distances / intrinsics["fy"], distances))
    import pyrealsense2 as rs
    intr = rs.intrinsics()
    intr.width, intr.height = width, height
    intr.fx, intr.fy = intrinsics["fx"], intrinsics["fy"]
    intr.ppx, intr.ppy = intrinsics["cx"], intrinsics["cy"]
    intr.model = getattr(rs.distortion, intrinsics["model"])
    intr.coeffs = intrinsics["coefficients"]
    return np.asarray([rs.rs2_deproject_pixel_to_point(intr, [float(x), float(y)], float(z))
                       for x, y, z in zip(u, v, distances)], dtype=float)


def height_spread_within(heights, limit):
    """P95-P5 in caller's units; layer-reference accuracy is a separate check."""
    values = np.asarray(heights, float)
    if (values.ndim != 1 or not values.size or not np.isfinite(values).all() or
            not np.isfinite(limit) or limit <= 0):
        raise ValueError('finite surface heights and positive spread limit required')
    spread = np.quantile(values, .95) - np.quantile(values, .05)
    # Unit conversion can round the exact boundary upward by a few float bits.
    rounding = 4 * np.finfo(float).eps * max(float(np.max(np.abs(values))), limit)
    return bool(spread <= limit + rounding)


def frame_board_baseline(detections, depth, scale, intrinsics, transform, config, *, roi_mask=None):
    """Fit this capture's board plate plane (m, flat-board-zero frame) away from detected blocks."""
    params = params_from_geometry(config, 1.)
    if params is None:
        return None
    if config.get('layer_height_reference') != 'BOARD_FLAT_SURFACE_ZERO':
        raise ValueError('board_baseline_requires_flat_board_zero')
    union = np.zeros(depth.shape, bool)
    if roi_mask is not None:
        union |= ~roi_mask
    for mask, _, _ in detections:
        union |= mask
    z = depth.astype(float) * scale
    valid = ((depth > 0) & (z >= config['min_depth_m']) & (z <= config['max_depth_m']) &
             ~exclusion_mask(union, params['exclusion_px']))
    v, u = sampled_pixels(valid)
    if not len(u):
        raise ValueError('board_baseline_insufficient_points')
    camera = deproject_pixels(u, v, z[v, u], intrinsics, depth.shape[1], depth.shape[0])
    board = camera @ transform[:3, :3].T + transform[:3, 3]
    return fit_board_plane(board, expected_plate_z=0., bounds=config['board_bounds_m'], **params)


def measure_candidate(mask, part_class, confidence, depth, scale, intrinsics,
                      camera_to_board, config, *, rgb=None, board_plane=None):
    validate_config(config)
    transform = validate_geometry(scale, intrinsics, camera_to_board)
    rotation = transform[:3, :3]
    if mask.dtype != np.bool_ or mask.shape != depth.shape or depth.dtype != np.uint16:
        raise ValueError("boolean mask must match uint16 aligned depth")
    unknown = lambda reason: {"status": "UNKNOWN", "reason": reason, "part_class": part_class}
    if part_class not in CLASSES or not np.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("invalid detection class or confidence")
    if confidence < config["min_confidence"]:
        return unknown("low_model_confidence")
    z = depth.astype(float) * scale
    valid = mask & (depth > 0) & (z >= config["min_depth_m"]) & (z <= config["max_depth_m"])
    if (valid.sum() < config["min_depth_pixels"] or
            valid.sum() / max(1, mask.sum()) < config["min_valid_fraction"]):
        return unknown("insufficient_depth")
    v, u = np.nonzero(valid)
    distances = z[valid]
    camera = deproject_pixels(u, v, distances, intrinsics, depth.shape[1], depth.shape[0])
    board = camera @ rotation.T + transform[:3, 3]
    stud_increment = 0.
    if config.get('block_surface_height_basis') == 'BODY_TOP_PLUS_STUD':
        from .opencv_live import body_surface_points
        stud_increment = config['block_stud_height_m']
        try:
            body = body_surface_points(board * 1000., stud_height_mm=stud_increment * 1000.,
                                       minimum_points=config['min_depth_pixels'])
        except ValueError as error:
            return unknown(str(error))
        board = board[body]
    height_board = board
    outline = None
    surface_basis = config.get('block_surface_height_basis')
    if surface_basis in ('DIRECT_STUD_TOP', 'TOP_PLANE_PLUS_STUD'):
        from .opencv_live import top_surface_points, rgb_top_quad
        if surface_basis == 'TOP_PLANE_PLUS_STUD':
            # The measured plane is the block top face; the physical stud is added once
            # for layer comparison only. No second surface is required.
            stud_increment = config['block_stud_height_m']
        if rgb is None:
            return unknown('rgb_outline_input_missing')
        if rgb.shape != (*mask.shape, 3) or rgb.dtype != np.uint8:
            raise ValueError('uint8 aligned RGB required for outline')
        try:
            from .opencv_live import top_surface_points_core_retry
            selected, _ = top_surface_points_core_retry(board * 1000., v, u, mask,
                                                        minimum_points=config['min_depth_pixels'],
                                                        part_class=part_class)
            height_board = board[selected]
        except ValueError as error:
            return unknown(str(error))
        support_mask = np.zeros(mask.shape, bool)
        support_mask[v[selected], u[selected]] = True
        try:
            outline = rgb_top_quad(rgb, mask, support_mask)
        except ValueError as error:
            return unknown(str(error))
    heights = height_board[:, 2]
    if not height_spread_within(heights, config["max_height_spread_m"]):
        return unknown("surface_height_conflict")
    body_height = float(np.median(heights))
    # The board baseline only corrects the layer height; body_height still feeds the outline plane.
    bias = (board_plane.bias_at(float(np.median(height_board[:, 0])), float(np.median(height_board[:, 1])))
            if board_plane is not None else 0.)
    height = body_height - bias + stud_increment
    layer_index = layer_band_index(height, config["top_heights_m"], config["height_tolerance_m"],
                                  config.get("first_layer_min_height_m"), config.get("first_layer_max_height_m"),
                                  upper_bounds=config.get("layer_upper_bounds_m"))
    if layer_index is None:
        return unknown("height_not_in_measured_layer")
    footprint_points = board[:, :2]
    if outline is not None:
        # Unit-depth deprojection gives camera rays including lens distortion.
        rays = deproject_pixels(outline[:, 0], outline[:, 1], np.ones(4),
                                intrinsics, depth.shape[1], depth.shape[0]) @ rotation.T
        origin = transform[:3, 3]
        if np.any(np.abs(rays[:, 2]) < 1e-8):
            return unknown('top_plane_ray_parallel')
        # RGB corners are intersected with the measured plane, never the +stud height.
        distances = (body_height-origin[2])/rays[:, 2]
        if not np.isfinite(distances).all() or np.any(distances <= 0):
            return unknown('top_plane_behind_camera')
        footprint_points = (origin + distances[:, None]*rays)[:, :2]
    rect = cv2.minAreaRect(footprint_points.astype(np.float32))
    center, sides, angle = rect
    pitch = config["stud_pitch_m"]
    expected = np.asarray(config["footprint_sizes_m"][part_class], dtype=float)
    if expected.shape != (2,) or not np.isfinite(expected).all() or np.any(expected <= 0):
        raise ValueError("measured footprint dimensions required")
    if np.max(np.abs(np.sort(sides) - np.sort(expected))) > config["size_tolerance_m"]:
        return unknown("partial_or_invalid_footprint")
    period = 90 if part_class.endswith("2x2") else 180
    if sides[0] < sides[1]:
        angle += 90
    angle %= period
    axis_angle = (round(angle / 90) * 90) % period
    if abs((angle - axis_angle + period / 2) % period - period / 2) > config["angle_tolerance_deg"]:
        return unknown("orientation_off_grid")
    # Center lattice offsets differ for even/odd stud spans; callers supply them.
    offset = np.asarray(config["center_offsets_stud"][part_class][str(int(axis_angle))])
    if offset.shape != (2,) or not np.isfinite(offset).all():
        raise ValueError("two finite center offsets required")
    grid = np.asarray(center) / pitch
    snapped = np.rint(grid - offset) + offset
    if np.max(np.abs(grid - snapped)) > config["grid_tolerance_stud"]:
        return unknown("position_off_grid")
    bounds = np.asarray(config["board_bounds_m"], dtype=float)
    if bounds.shape != (2, 2) or not np.isfinite(bounds).all() or np.any(bounds[:, 0] >= bounds[:, 1]):
        raise ValueError("explicit board bounds required")
    corners = cv2.boxPoints(rect)
    if np.any(corners < bounds[:, 0]) or np.any(corners > bounds[:, 1]):
        return unknown("outside_board")
    return {"status": "CANDIDATE", "part_class": part_class,
            "surface_center_m": list(map(float, center)), "grid_center_stud": snapped.tolist(),
            "top_height_m": height,
            "board_baseline_bias_m": (bias if board_plane is not None else None),
            "surface_height_basis": config.get('block_surface_height_basis', 'LEGACY'),
            "body_surface_height_m": body_height if stud_increment else None,
            "block_stud_added_m": stud_increment, "measured_layer_index": layer_index,
            "axis_angle_deg": int(axis_angle), "model_confidence": float(confidence),
            "valid_depth_fraction": float(valid.sum() / mask.sum()),
            "threshold_status": config["threshold_status"], "calibration_id": config["calibration_id"]}


def occupied_region_evidence(candidates, config):
    """Positive measured footprints only; no empty cells or hidden-layer claims."""
    regions = []
    for candidate in candidates:
        if candidate['status'] == 'UNKNOWN':
            continue
        if candidate['status'] != 'CANDIDATE' or candidate['calibration_id'] != config['calibration_id']:
            raise ValueError('measured candidate and matching calibration required')
        block = candidate_to_block(candidate, config['center_to_anchor_offsets_stud'])
        cells = footprint(block)
        xs, ys = [cell[0] for cell in cells], [cell[1] for cell in cells]
        region = dict(x=min(xs), y=min(ys), width=max(xs) - min(xs) + 1,
                      height=max(ys) - min(ys) + 1, layer=block['layer'])
        if region not in regions:
            regions.append(region)
    return dict(verified_regions=regions, verification_basis=(dict(
        kind='MEASURED_OCCUPIED_FOOTPRINT_ONLY', calibration_id=config['calibration_id'],
        excludes=['empty-space inference', 'hidden layers', 'whole-board coverage']) if regions else None))


def process_saved(directory, detections, calibration, config):
    from .assembly_roi import freeze_rois, mask_for_view
    detections = tuple(detections)
    rgb, _, depth, metadata = load_frame(directory)
    config = freeze_rois(config)
    config = config_for_view(config, metadata['view_id'])
    roi_mask = mask_for_view(config, metadata['view_id'], rgb.shape)
    outside_count = 0
    if roi_mask is not None:
        kept = []
        for mask, cls, conf in detections:
            if mask.dtype != bool or mask.shape != roi_mask.shape:
                raise ValueError('boolean mask must match assembly ROI resolution')
            if np.any(mask & roi_mask):
                kept.append((mask, cls, conf))
            else:
                outside_count += 1
        detections = tuple(kept)
    validate_config(config)
    if calibration["calibration_id"] != config["calibration_id"]:
        raise ValueError("calibration/config versions differ")
    transform = calibration["views"][metadata["view_id"]]
    matrix = validate_geometry(metadata["depth_scale_m"], metadata["camera_info"]["aligned"], transform)
    board_plane, baseline_error = None, None
    try:
        board_plane = frame_board_baseline(detections, depth, metadata["depth_scale_m"],
                                           metadata["camera_info"]["aligned"], matrix, config,
                                           **({'roi_mask': roi_mask} if roi_mask is not None else {}))
    except ValueError as error:
        if str(error) == 'board_baseline_requires_flat_board_zero':
            raise  # Configuration error, not a per-capture measurement failure.
        baseline_error = str(error)  # Blocks stay UNKNOWN; never an uncorrected layer.
    results = [dict(status='UNKNOWN', reason='instance_crosses_roi_boundary', part_class=cls)
               if roi_mask is not None and np.any(mask & ~roi_mask) else
               dict(status="UNKNOWN", reason=baseline_error, part_class=cls) if baseline_error else
               measure_candidate(mask, cls, conf, depth, metadata["depth_scale_m"],
                                 metadata["camera_info"]["aligned"], transform, config, rgb=rgb,
                                 board_plane=board_plane)
               for mask, cls, conf in detections]
    result = {"internal_format": "visible_candidates_v1", "status": "PARTIAL",
            "scene_id": metadata["scene_id"], "view_id": metadata["view_id"],
            "captured_at": metadata["captured_at"], "candidates": results,
            "reason": "whole_board_coverage_and_occlusion_not_verified"}
    if roi_mask is not None:
        result['assembly_roi'] = dict(config['assembly_roi_profiles'][metadata['view_id']],
                                      dropped_outside_candidates=outside_count)
    if config.get('block_surface_height_basis') in (
            'BODY_TOP_PLUS_STUD', 'DIRECT_STUD_TOP', 'TOP_PLANE_PLUS_STUD'):
        result.update(occupied_region_evidence(results, config))
        # Kept separately so a View role can use clear-column evidence without occupied layers.
        result['occupied_regions'] = list(result['verified_regions'])
        result['empty_regions'] = []
        if (config.get('layer_height_reference') == 'BOARD_FLAT_SURFACE_ZERO' and
                len(config['top_heights_m']) == 5):
            from .region_evidence import empty_column_evidence, empty_above_block_evidence
            exclusion = np.zeros(depth.shape, bool)
            # The RGB ROI outlines the board image, not the projection of its
            # five-layer volume. Side-view rays may leave that polygon. The ray
            # engine bounds them to calibrated board columns and tests real Depth;
            # removing the 2D clipping does not mark pixels outside the ROI empty.
            for mask, _, _ in detections:
                exclusion |= mask
            empty = empty_column_evidence(depth, metadata['depth_scale_m'],
                metadata['camera_info']['aligned'], transform, config, object_mask=exclusion)
            occupied_columns = {(x, y) for region in result['verified_regions']
                                for x in range(region['x'], region['x'] + region['width'])
                                for y in range(region['y'], region['y'] + region['height'])}
            empty_regions = [region for region in empty['verified_regions']
                             if (region['x'], region['y']) not in occupied_columns]
            result['verified_regions'] += empty_regions
            result['empty_regions'] = list(empty_regions)
            result['verification_basis'] = dict(occupied=result['verification_basis'],
                empty=empty['verification_basis'] if empty_regions else None) if result['verified_regions'] else None
            result['empty_column_diagnostics'] = empty['rejection_counts']
            # Only V0's occupied layers are authoritative. Auxiliary measured
            # layers must not generate free-space claims above a borrowed height.
            if metadata['view_id'] == 'V0' and result['occupied_regions']:
                unknown_mask = np.zeros(depth.shape, bool)
                for (mask, _, _), candidate in zip(detections, results):
                    if candidate['status'] != 'CANDIDATE':
                        unknown_mask |= mask
                above = empty_above_block_evidence(depth, metadata['depth_scale_m'],
                    metadata['camera_info']['aligned'], transform, config,
                    occupied_regions=result['occupied_regions'], object_mask=unknown_mask)
                result['verified_regions'] += above['verified_regions']
                result['empty_regions'] += above['verified_regions']
                result['verification_basis']['above_blocks'] = above['verification_basis']
                result['above_block_diagnostics'] = above['rejection_counts']
    return result


def process_saved_bundle(recordings, calibration, config, check_id, observation_seq,
                         previous_accepted_blocks, target_after, *, scene_stable,
                         unknown_policy='VIEW'):
    """recordings: directory/detections/verified_regions, independently verified inputs.

    Existing single-frame CLI remains a candidate preview. This function connects
    its actual calculations to common Observed without treating ROI as verified.

    unknown_policy:
      'VIEW' (default, unchanged): any UNKNOWN candidate makes the whole view UNOBSERVABLE
          with empty verified regions.
      'CANDIDATE': an UNKNOWN candidate only drops itself. Measured candidates and
          measured evidence of the same view are kept. The UNKNOWN candidate never becomes a
          block and its cells are never added as verified: occupied evidence skips it and
          empty-column evidence excludes every detection mask and requires Depth rays to
          pass the whole column. Regions supplied by the caller cannot be cross-checked
          against an unmeasured candidate, so they are dropped for that view. The partial
          failure stays visible as an issue (so MATCH is not reached silently) and in
          diagnostics['partial_unknown_candidates'].
      'ROLES': V0 owns layers (blocks and occupied footprints); D1/D3 are auxiliary and only
          add clear-column evidence and a same-layer cross-check (see view_roles). A D1/D3
          UNKNOWN candidate is not gating; a V0 one is. Live observe_cycle uses this policy.
    """
    if unknown_policy not in ('VIEW', 'CANDIDATE', 'ROLES'):
        raise ValueError("unknown_policy must be VIEW, CANDIDATE or ROLES")
    views, source_diagnostics, scene_ids, partial = [], [], set(), []
    role_notes, role_gating = {}, []
    for recording in recordings:
        result = process_saved(recording["directory"], recording["detections"], calibration, config)
        scene_ids.add(result["scene_id"])
        candidates = result["candidates"]
        if unknown_policy == 'ROLES':
            from .view_roles import build_role_view
            identity = {"check_id": check_id, "observation_seq": observation_seq,
                        "calibration_id": calibration["calibration_id"]}
            view, notes, gating = build_role_view(identity, result, recording["verified_regions"],
                lambda c: candidate_to_block(c, config["center_to_anchor_offsets_stud"]))
            role_notes[result["view_id"]] = notes
            role_gating += gating
            views.append(view)
            source_diagnostics.append(result)
            continue
        unknown = any(c["status"] == "UNKNOWN" for c in candidates)
        blocks = [candidate_to_block(c, config["center_to_anchor_offsets_stud"])
                  for c in candidates if c["status"] == "CANDIDATE"]
        view = {"check_id": check_id, "observation_seq": observation_seq,
                "calibration_id": calibration["calibration_id"],
                "view_id": result["view_id"], "visible_blocks": blocks}
        if unknown and unknown_policy == 'CANDIDATE':
            view.update(verified_regions=list(result.get('verified_regions', [])),
                        status="OK", reason=None)
            partial.append(dict(view_id=result["view_id"],
                reasons=[c.get("reason") for c in candidates if c["status"] == "UNKNOWN"],
                measured_candidates=len(blocks)))
        else:
            view.update(verified_regions=[] if unknown else (
                            recording["verified_regions"] + result.get('verified_regions', [])),
                        status="UNOBSERVABLE" if unknown else "OK",
                        reason="unknown_detection" if unknown else None)
        views.append(view)
        source_diagnostics.append(result)
    if len(scene_ids) > 1:
        raise ValueError("recordings must belong to one static scene")
    observed, diagnostics = build_observed(check_id, observation_seq, views,
        previous_accepted_blocks, target_after, scene_stable=scene_stable)
    diagnostics["source_measurements"] = source_diagnostics
    diagnostics["partial_unknown_candidates"] = partial
    diagnostics["issues"].extend(f"{p['view_id']}:partial_unknown_candidates" for p in partial)
    if unknown_policy == 'ROLES':
        from .view_roles import finalize
        finalize(diagnostics, role_notes, role_gating)
    return observed, diagnostics
