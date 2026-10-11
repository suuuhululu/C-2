"""Measure manually reviewed top polygons against a diagnostic empty-board plane."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .empty_board_depth import measure, summary


def review(recording, empty_recording, calibration_path, polygon):
    # Reuse format/camera checks, but do not fit the block scene as an empty board.
    _, _ = measure(recording, calibration_path)
    baseline, _ = measure(empty_recording, calibration_path)
    recording = Path(recording)
    meta = json.loads((recording / "metadata.json").read_text())
    empty_meta = json.loads((Path(empty_recording) / "metadata.json").read_text())
    if meta["view_id"] != empty_meta["view_id"]:
        raise ValueError("block/empty View mismatch")
    calibration = json.loads(Path(calibration_path).read_text())
    rgb = cv2.imread(str(recording / "rgb.png"))
    depth = np.load(recording / "depth_aligned.npy", allow_pickle=False)
    points = np.asarray(polygon)
    if points.shape != (4, 2) or not np.issubdtype(points.dtype, np.integer):
        raise ValueError("four integer pixel corners required")
    if np.any(points < 0) or np.any(points >= [depth.shape[1], depth.shape[0]]):
        raise ValueError("polygon outside image")
    if not cv2.isContourConvex(points.astype(np.int32)):
        raise ValueError("convex top polygon required")
    mask = np.zeros(depth.shape, np.uint8)
    cv2.fillConvexPoly(mask, points.astype(np.int32), 1)
    valid = (mask > 0) & (depth > 0)
    if valid.sum() < 3:
        raise ValueError("insufficient top Depth")
    v, u = np.nonzero(valid)
    z = depth[valid].astype(float) * meta["depth_scale_m"] * 1000
    k = np.asarray(meta["camera_info"]["aligned"]["k"]).reshape(3, 3)
    camera = np.column_stack(((u-k[0, 2])*z/k[0, 0], (v-k[1, 2])*z/k[1, 1], z))
    pose = calibration["camera_pose"]
    board = (camera-np.asarray(pose["t_camera_from_board_mm"])) @ np.asarray(pose["R_camera_from_board"])
    board[:, 2] *= pose["height_normal_sign"]
    a, b, c = baseline["dominant_plane_z_equals_ax_plus_by_plus_c_mm"]
    heights = (board[:, 2]-a*board[:, 0]-b*board[:, 1]-c)/np.sqrt(1+a*a+b*b)
    result = {"view_id": meta["view_id"], "recording": str(recording.resolve()),
        "empty_recording": str(Path(empty_recording).resolve()),
        "calibration": str(Path(calibration_path).resolve()),
        "top_polygon_pixels": points.tolist(), "polygon_origin": "AI visual selection; human review pending",
        "top_pixels": int(mask.sum()), "nonzero_pixels": int(valid.sum()),
        "nonzero_fraction": float(valid.sum()/mask.sum()),
        "camera_optical_z_mm": summary(z), "rgb_pose_board_z_mm": summary(board[:, 2]),
        "height_above_diagnostic_empty_plane_mm": summary(heights),
        "decision": "DIAGNOSTIC_ONLY_NOT_LAYER_VALIDATION",
        "limitations": ["polygon includes stud tops and lower top face; not YOLO training labels",
            "empty plane mixes stud tops and lower board surface; not adopted reference Z=0",
            "no measured block height or agreed layer tolerance provided",
            "one frame per View; pose repeatability not verified"]}
    overlay = rgb.copy()
    overlay[mask > 0] = (overlay[mask > 0]*.6+np.array([255, 0, 0])*.4).astype(np.uint8)
    overlay[(mask > 0) & (depth == 0)] = [0, 0, 255]
    cv2.polylines(overlay, [points.astype(np.int32)], True, (255, 255, 255), 1)
    return result, overlay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    inputs = json.loads(Path(args.inputs).read_text())
    results = [review(**item) for item in inputs]
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    for result, overlay in results:
        if not cv2.imwrite(str(out/f"{result['view_id']}_top_roi.png"), overlay):
            raise RuntimeError("ROI image save failed")
    (out/"block_height_report.json").write_text(json.dumps(
        [r for r, _ in results], ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps([r for r, _ in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
