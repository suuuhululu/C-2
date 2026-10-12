"""Saved-frame inference; intentionally cannot certify complete-board Observed."""
import argparse
import json
from pathlib import Path

import numpy as np

from depth_grid import CLASSES, measure_candidate, validate_config, validate_geometry
from rgbd_io import load_frame
from perception_mvp.backend_adapter import build_observed
from perception_mvp.contracts import candidate_to_block


def infer_masks(rgb, weights, detector_confidence):
    if not Path(weights).is_file():
        raise FileNotFoundError("local trained segmentation weights required")
    if not 0 < detector_confidence <= 1:
        raise ValueError("explicit detector threshold in (0,1] required")
    from ultralytics import YOLO
    model = YOLO(str(weights))
    if model.task != "segment" or model.names != dict(enumerate(CLASSES)):
        raise ValueError("segmentation model with exactly the four classes required")
    result = model.predict(rgb[:, :, ::-1].copy(), conf=detector_confidence,
                           retina_masks=True, verbose=False)[0]
    if result.boxes is None:
        raise ValueError("missing segmentation boxes")
    if len(result.boxes) == 0:
        return []
    if result.masks is None or len(result.masks.data) != len(result.boxes):
        raise ValueError("missing or mismatched instance masks")
    masks = result.masks.data.cpu().numpy() > .5
    if masks.shape[1:] != rgb.shape[:2]:
        raise ValueError("mask resolution differs from RGB")
    return [(mask, model.names[int(cls)], float(conf)) for mask, cls, conf in
            zip(masks, result.boxes.cls.cpu().numpy(), result.boxes.conf.cpu().numpy())]


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--detector-confidence", type=float, required=True)
    args = parser.parse_args()
    rgb, _, _, _ = load_frame(args.recording)
    detections = infer_masks(rgb, args.weights, args.detector_confidence)
    result = process_saved(args.recording, detections,
                           json.loads(args.calibration.read_text()),
                           json.loads(args.config.read_text()))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
