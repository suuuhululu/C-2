"""Diagnostic measurement of a real saved empty board; never adopts calibration."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def summary(values):
    return dict(zip(("p05", "median", "p95"), map(float, np.percentile(values, [5, 50, 95]))))


def measure(recording, calibration_path):
    recording = Path(recording)
    metadata = json.loads((recording / "metadata.json").read_text())
    calibration = json.loads(Path(calibration_path).read_text())
    if metadata["recording_format"] != "ros_rgbd_capture_v1":
        raise ValueError("ROS capture format required")
    if metadata["view_id"] != calibration["view_id"]:
        raise ValueError("recording/calibration View mismatch")
    if not calibration["independently_validated"]:
        raise ValueError("independent RGB calibration validation required")
    rgb = np.load(recording / "rgb.npy", allow_pickle=False)
    depth = np.load(recording / "depth_aligned.npy", allow_pickle=False)
    raw = np.load(recording / "depth_raw.npy", allow_pickle=False)
    for name, data in (("rgb", rgb), ("depth_aligned", depth), ("depth_raw", raw)):
        png = cv2.imread(str(recording / f"{name}.png"), cv2.IMREAD_UNCHANGED)
        expected = cv2.cvtColor(data, cv2.COLOR_RGB2BGR) if name == "rgb" else data
        if png is None or not np.array_equal(png, expected):
            raise ValueError(f"PNG/NPY mismatch: {name}")
    h, w = depth.shape
    if depth.dtype != np.uint16 or raw.dtype != np.uint16 or rgb.shape != (h, w, 3):
        raise ValueError("uint16 Depth and matching RGB required")
    info = metadata["camera_info"]["aligned"]
    k = np.asarray(info["k"]).reshape(3, 3)
    dist = np.asarray(info["d"])
    intr = calibration["intrinsics"]
    if ([w, h] != calibration["image_size"] or
            [w, h] != [info["width"], info["height"]] or
            not np.allclose(k, intr["camera_matrix"]) or
            not np.array_equal(dist, intr["dist_coeffs"])):
        raise ValueError("camera settings differ from RGB calibration")
    if info["distortion_model"] != "plumb_bob" or np.any(dist != 0):
        raise ValueError("this diagnostic supports zero-distortion plumb_bob captures only")
    scale = metadata["depth_scale_m"] * 1000
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("positive measured Depth scale required")
    v, u = np.indices((h, w))
    pixels = np.column_stack((u.ravel(), v.ravel(), np.ones(h * w)))
    q = pixels @ np.asarray(calibration["H_board_from_undistorted_pixel"]).T
    if np.any(np.abs(q[:, 2]) < 1e-10):
        raise ValueError("projective horizon in image")
    xy = (q[:, :2] / q[:, 2:3]).reshape(h, w, 2)
    pitch = calibration["pitch_mm"]
    # One stud inset excludes board edges/table; it is not verified_regions.
    limits = np.array([calibration["cols"] - 2, calibration["rows"] - 2]) * pitch
    roi = np.all((xy >= pitch) & (xy <= limits), axis=2)
    valid = roi & (depth > 0)
    if valid.sum() < 3 or roi.sum() == 0:
        raise ValueError("insufficient board Depth pixels")
    z = depth[valid].astype(float) * scale
    camera = np.column_stack(((u[valid] - k[0, 2]) * z / k[0, 0],
                              (v[valid] - k[1, 2]) * z / k[1, 1], z))
    pose = calibration["camera_pose"]
    rotation = np.asarray(pose["R_camera_from_board"])
    translation = np.asarray(pose["t_camera_from_board_mm"])
    if (rotation.shape != (3, 3) or translation.shape != (3,) or
            not np.isfinite(rotation).all() or not np.isfinite(translation).all() or
            not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5)):
        raise ValueError("invalid camera pose")
    board = (camera - translation) @ rotation
    board[:, 2] *= pose["height_normal_sign"]
    design = np.column_stack((board[:, :2], np.ones(len(board))))
    height_center = np.median(board[:, 2])
    height_mad = np.median(np.abs(board[:, 2] - height_center))
    keep = np.abs(board[:, 2] - height_center) <= max(1.0, 3 * 1.4826 * height_mad)
    if keep.sum() < 3:
        raise ValueError("insufficient initial plane samples")
    # MAD trimming describes the dominant surface, not a physical pass threshold.
    for _ in range(4):
        fit, _, rank, _ = np.linalg.lstsq(design[keep], board[keep, 2], rcond=None)
        if rank != 3:
            raise ValueError("board samples do not span a plane")
        residual = board[:, 2] - design @ fit
        center = np.median(residual[keep])
        mad = np.median(np.abs(residual[keep] - center))
        keep = np.abs(residual - center) <= max(1.0, 3 * 1.4826 * mad)
        if keep.sum() < 3:
            raise ValueError("insufficient plane samples")
    fit = np.linalg.lstsq(design[keep], board[keep, 2], rcond=None)[0]
    residual = board[:, 2] - design @ fit
    report = {
        "scope": "EMPTY_BOARD_DEPTH_DIAGNOSTIC", "view_id": metadata["view_id"],
        "recording": str(recording.resolve()), "calibration": str(Path(calibration_path).resolve()),
        "captured_at": metadata["captured_at"], "timestamp_span_ms": metadata["timestamp_span_ms"],
        "roi": "reference stud grid inset one pitch; not verified_regions",
        "roi_pixels": int(roi.sum()), "valid_pixels": int(valid.sum()),
        "valid_fraction": float(valid.sum() / roi.sum()),
        "camera_optical_z_mm": summary(z), "rgb_pose_board_height_mm": summary(board[:, 2]),
        "dominant_plane_z_equals_ax_plus_by_plus_c_mm": fit.tolist(),
        "tilt_from_rgb_reference_deg": float(np.degrees(np.arctan(np.linalg.norm(fit[:2])))),
        "plane_sample_fraction": float(keep.mean()),
        "all_pixel_plane_residual_mm": summary(residual),
        "trimmed_plane_rmse_mm": float(np.sqrt(np.mean(residual[keep] ** 2))),
        "decision": "NOT_VALIDATED_NO_AGREED_DEPTH_THRESHOLD",
        "limitations": ["one frame per View; temporal repeatability not measured",
            "stud tops and lower board surface are mixed; fitted plane is not an adopted Z=0",
            "matching View/intrinsics does not prove identical physical pose",
            "Depth/height acceptance and layer spacing not validated",
            "source capture has no robot pose/calibration ID; manual association only"],
    }
    overlay = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    overlay[roi] = (overlay[roi] * .7 + np.array([0, 180, 0]) * .3).astype(np.uint8)
    overlay[roi & ~valid] = [0, 0, 255]
    cv2.putText(overlay, "Green: analysis ROI / Red: missing Depth (not PASS)",
                (15, 30), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 2)
    return report, overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", required=True)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report, overlay = measure(args.recording, args.calibration)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    if not cv2.imwrite(str(out / "depth_roi_review.png"), overlay):
        raise RuntimeError("failed to save ROI review image")
    (out / "depth_baseline_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
