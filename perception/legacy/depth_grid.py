"""Visible top-surface measurement; outputs are internal candidates only."""
import cv2
import numpy as np

CLASSES = ("yellow_2x2", "yellow_2x3", "blue_2x2", "blue_2x3")


def validate_config(config):
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
    if heights.shape != (4,) or not np.isfinite(heights).all() or np.any(np.diff(heights) <= 0):
        raise ValueError("four increasing measured top heights required")
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
    if intrinsics["model"] != "none":
        raise ValueError("rectified pinhole input required; distortion unsupported")
    if any(not np.isfinite(intrinsics[k]) for k in ("fx", "fy", "cx", "cy")):
        raise ValueError("invalid intrinsics")
    if min(intrinsics["fx"], intrinsics["fy"], scale) <= 0 or not np.isfinite(scale):
        raise ValueError("invalid focal length or scale")
    return transform


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
    camera = np.column_stack(((u - intrinsics["cx"]) * distances / intrinsics["fx"],
                              (v - intrinsics["cy"]) * distances / intrinsics["fy"], distances))
    board = camera @ rotation.T + transform[:3, 3]
    heights = board[:, 2]
    if np.quantile(heights, .95) - np.quantile(heights, .05) > config["max_height_spread_m"]:
        return unknown("surface_height_conflict")
    height = float(np.median(heights))
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
            "top_height_m": height, "measured_layer_index": layer_index,
            "axis_angle_deg": int(axis_angle), "model_confidence": float(confidence),
            "valid_depth_fraction": float(valid.sum() / mask.sum()),
            "threshold_status": config["threshold_status"], "calibration_id": config["calibration_id"]}
