"""Visible top-surface measurement; outputs are internal candidates only."""
import cv2
import numpy as np

from .rgbd_io import load_frame
from .backend_adapter import build_observed
from .contracts import candidate_to_block, LIVE_CLASSES

CLASSES = LIVE_CLASSES


def validate_config(config):
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


def process_saved(directory, detections, calibration, config):
    validate_config(config)
    _, _, depth, metadata = load_frame(directory)
    if calibration["calibration_id"] != config["calibration_id"]:
        raise ValueError("calibration/config versions differ")
    transform = calibration["views"][metadata["view_id"]]
    validate_geometry(metadata["depth_scale_m"], metadata["camera_info"]["aligned"], transform)
    results = [measure_candidate(mask, cls, conf, depth, metadata["depth_scale_m"],
                                metadata["camera_info"]["aligned"], transform, config)
               for mask, cls, conf in detections]
    return {"internal_format": "visible_candidates_v1", "status": "PARTIAL",
            "scene_id": metadata["scene_id"], "view_id": metadata["view_id"],
            "captured_at": metadata["captured_at"], "candidates": results,
            "reason": "whole_board_coverage_and_occlusion_not_verified"}


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
                      "verified_regions": [] if unknown else recording["verified_regions"],
                      "status": "UNOBSERVABLE" if unknown else "OK",
                      "reason": "unknown_detection" if unknown else None})
        source_diagnostics.append(result)
    if len(scene_ids) > 1:
        raise ValueError("recordings must belong to one static scene")
    observed, diagnostics = build_observed(check_id, observation_seq, views,
        previous_accepted_blocks, target_after, scene_stable=scene_stable)
    diagnostics["source_measurements"] = source_diagnostics
    return observed, diagnostics
