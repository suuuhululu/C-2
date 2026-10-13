"""Visible top-surface measurement; outputs are internal candidates only."""
import cv2
import numpy as np

from .rgbd_io import load_frame
from .backend_adapter import build_observed
from .contracts import candidate_to_block, LIVE_CLASSES, footprint

CLASSES = LIVE_CLASSES


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
        if (config['block_surface_height_basis'] != 'BODY_TOP_PLUS_STUD' or
                not np.isfinite(config.get('block_stud_height_m', np.nan)) or
                config['block_stud_height_m'] <= 0):
            raise ValueError('explicit body-top basis and positive block stud height required')
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


def measure_candidate(mask, part_class, confidence, depth, scale, intrinsics,
                      camera_to_board, config):
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
    heights = board[:, 2]
    if not height_spread_within(heights, config["max_height_spread_m"]):
        return unknown("surface_height_conflict")
    body_height = float(np.median(heights))
    height = body_height + stud_increment
    layer_index = int(np.argmin(np.abs(np.asarray(config["top_heights_m"]) - height)))
    if abs(config["top_heights_m"][layer_index] - height) > config["height_tolerance_m"]:
        return unknown("height_not_in_measured_layer")
    rect = cv2.minAreaRect(board[:, :2].astype(np.float32))
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
            "top_height_m": height, "body_surface_height_m": body_height,
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
    detections = tuple(detections)
    _, _, depth, metadata = load_frame(directory)
    config = config_for_view(config, metadata['view_id'])
    validate_config(config)
    if calibration["calibration_id"] != config["calibration_id"]:
        raise ValueError("calibration/config versions differ")
    transform = calibration["views"][metadata["view_id"]]
    validate_geometry(metadata["depth_scale_m"], metadata["camera_info"]["aligned"], transform)
    results = [measure_candidate(mask, cls, conf, depth, metadata["depth_scale_m"],
                                metadata["camera_info"]["aligned"], transform, config)
               for mask, cls, conf in detections]
    result = {"internal_format": "visible_candidates_v1", "status": "PARTIAL",
            "scene_id": metadata["scene_id"], "view_id": metadata["view_id"],
            "captured_at": metadata["captured_at"], "candidates": results,
            "reason": "whole_board_coverage_and_occlusion_not_verified"}
    if config.get('block_surface_height_basis') == 'BODY_TOP_PLUS_STUD':
        result.update(occupied_region_evidence(results, config))
        if (config.get('layer_height_reference') == 'BOARD_FLAT_SURFACE_ZERO' and
                len(config['top_heights_m']) == 5):
            from .region_evidence import empty_column_evidence
            exclusion = np.zeros(depth.shape, bool)
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
            result['verification_basis'] = dict(occupied=result['verification_basis'],
                empty=empty['verification_basis'] if empty_regions else None) if result['verified_regions'] else None
            result['empty_column_diagnostics'] = empty['rejection_counts']
    return result


def process_saved_bundle(recordings, calibration, config, check_id, observation_seq,
                         previous_accepted_blocks, target_after, *, scene_stable):
    """recordings: directory/detections/verified_regions, independently verified inputs.

    Existing single-frame CLI remains a candidate preview. This function connects
    its actual calculations to common Observed without treating ROI as verified.
    """
    views, source_diagnostics, scene_ids = [], [], set()
    for recording in recordings:
        result = process_saved(recording["directory"], recording["detections"], calibration, config)
        scene_ids.add(result["scene_id"])
        candidates = result["candidates"]
        unknown = any(c["status"] == "UNKNOWN" for c in candidates)
        blocks = [candidate_to_block(c, config["center_to_anchor_offsets_stud"])
                  for c in candidates if c["status"] == "CANDIDATE"]
        views.append({"check_id": check_id, "observation_seq": observation_seq,
                      "calibration_id": calibration["calibration_id"],
                      "view_id": result["view_id"], "visible_blocks": blocks,
                      "verified_regions": [] if unknown else (
                          recording["verified_regions"] + result.get('verified_regions', [])),
                      "status": "UNOBSERVABLE" if unknown else "OK",
                      "reason": "unknown_detection" if unknown else None})
        source_diagnostics.append(result)
    if len(scene_ids) > 1:
        raise ValueError("recordings must belong to one static scene")
    observed, diagnostics = build_observed(check_id, observation_seq, views,
        previous_accepted_blocks, target_after, scene_stable=scene_stable)
    diagnostics["source_measurements"] = source_diagnostics
    return observed, diagnostics
