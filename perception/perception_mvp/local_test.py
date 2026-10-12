"""Standalone trials with real sensors/data. No HMI IDs, fixtures or Backend writes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

from .main import read_json
from .rgbd_io import capture, load_frame, stream_v0
from .yolo_pipeline import infer_masks
from .depth_grid import process_saved, validate_config
from .contracts import candidate_to_block, placement_key
from .multiview import merge_local_views, compare_previous
from .visualization import render_observation

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).with_name("config.yaml")


def require_values(values, section):
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise ValueError(f"fill actual {section} settings: {', '.join(missing)}")


def new_path(category):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return ROOT / category / stamp


def write_image(path, rgb):
    if not cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
        raise OSError(f"cannot write image: {path}")


def write_report(output, report):
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
    output.mkdir(parents=True, exist_ok=False)
    (output / "local_result.json").write_text(encoded, encoding="utf-8")


def recording_report(directory):
    rgb, raw, aligned, meta = load_frame(directory)
    if meta["mode"] != "REAL":
        raise ValueError("standalone trials require actual REAL recordings")
    valid = aligned > 0
    timestamps = meta.get("sensor_timestamps_ms", {})
    delta = (abs(timestamps["raw"] - timestamps["color"])
             if "raw" in timestamps and "color" in timestamps else None)
    report = {"scope": "LOCAL_ONLY", "directory": str(Path(directory).resolve()),
              "scene_id": meta["scene_id"], "view_id": meta["view_id"],
              "captured_at": meta["captured_at"],
              "rgb_shape": list(rgb.shape), "raw_depth_shape": list(raw.shape),
              "aligned_depth_shape": list(aligned.shape), "depth_scale_m": meta["depth_scale_m"],
              "valid_aligned_depth_fraction": float(valid.mean()),
              "median_camera_distance_m": float(np.median(aligned[valid]) * meta["depth_scale_m"]) if valid.any() else None,
              "rgb_raw_depth_timestamp_difference_ms": delta,
              "timestamp_domain": meta.get("timestamp_domain"),
              "limitations": ["format_check_not_board_calibration", "no_backend_completion"]}
    return rgb, report


def list_devices():
    import pyrealsense2 as rs
    devices = []
    for device in rs.context().query_devices():
        profiles = {rs.stream.color: set(), rs.stream.depth: set()}
        for sensor in device.query_sensors():
            for profile in sensor.get_stream_profiles():
                kind = profile.stream_type()
                if kind in profiles and profile.format() == (rs.format.rgb8 if kind == rs.stream.color else rs.format.z16):
                    video = profile.as_video_stream_profile()
                    profiles[kind].add((video.width(), video.height(), profile.fps()))
        devices.append({"name": device.get_info(rs.camera_info.name),
                        "serial": device.get_info(rs.camera_info.serial_number),
                        "common_rgb8_z16_width_height_fps": sorted(profiles[rs.stream.color] & profiles[rs.stream.depth])})
    if not devices:
        raise RuntimeError("no actual RealSense device found")
    print(json.dumps(devices, ensure_ascii=False, indent=2))


def measure_recordings(args):
    settings = read_json(args.config)
    config = settings["geometry"] if "geometry" in settings else settings
    validate_config(config)
    calibration = read_json(args.calibration)
    if calibration["calibration_id"] != config["calibration_id"]:
        raise ValueError("actual calibration and config IDs differ")
    evidence = read_json(args.regions) if args.regions else {}
    views, measurements, previews, scenes = [], [], {}, set()
    for directory in args.recordings:
        rgb, _ = recording_report(directory)
        _, _, _, meta = load_frame(directory)
        if meta.get("calibration_id") not in (None, calibration["calibration_id"]):
            raise ValueError("recorded calibration differs; do not relabel capture context")
        scenes.add(meta["scene_id"])
        if meta["view_id"] in previews:
            raise ValueError("one recording per View required in a local bundle")
        detections = infer_masks(rgb, args.weights, args.detector_confidence)
        result = process_saved(directory, detections, calibration, config)
        candidates = result["candidates"]
        unknown = any(c["status"] == "UNKNOWN" for c in candidates)
        blocks = [candidate_to_block(c, config["center_to_anchor_offsets_stud"])
                  for c in candidates if c["status"] == "CANDIDATE"]
        proof = evidence.get(meta["view_id"], {})
        regions = proof.get("verified_regions", [])
        if regions and not proof.get("verification_basis"):
            raise ValueError("actual region verification_basis required, not camera ROI")
        views.append({"view_id": meta["view_id"], "calibration_id": calibration["calibration_id"],
                      "visible_blocks": blocks, "verified_regions": [] if unknown else regions,
                      "status": "UNOBSERVABLE" if unknown else "OK",
                      "reason": "unknown_detection" if unknown else None})
        measurements.append(result)
        previews[meta["view_id"]] = render_observation(rgb, detections, candidates)
    if len(scenes) != 1:
        raise ValueError("all actual recordings must represent one static scene")
    merged = merge_local_views(views, scene_stable=args.scene_stable)
    report = {"scope": "LOCAL_ONLY", "scene_stable_confirmed": args.scene_stable,
              "measurements": measurements, "fusion": merged,
              "limitations": ["not_observed_dto", "no_backend_adoption_or_robot_permission",
                              "coverage_requires_independent_evidence"]}
    if args.previous_accepted:
        previous = read_json(args.previous_accepted)
        report["tracking"] = compare_previous(merged["visible_blocks"], previous, merged["verified_regions"])
        report["previous_source"] = str(args.previous_accepted.resolve())
    if args.ground_truth:
        truth = read_json(args.ground_truth)
        report["human_ground_truth_comparison"] = {
            "exact_visible_placement_match": Counter(map(placement_key, merged["visible_blocks"])) == Counter(map(placement_key, truth)),
            "unknown_candidates": sum(c["status"] == "UNKNOWN" for m in measurements for c in m["candidates"]),
            "ground_truth_source": str(args.ground_truth.resolve()),
            "not_backend_completion": True}
    output = args.output or new_path("local_results")
    write_report(output, report)
    for view_id, rgb in previews.items():
        write_image(output / f"{view_id}_measurement.png", rgb)
    print(f"Local measurement results: {output}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="Report installed packages; no install/device motion")
    commands.add_parser("devices", help="List actual serials and advertised stream settings")
    camera = commands.add_parser("capture", help="Capture without Backend/calibration identifiers")
    camera.add_argument("--config", type=Path, default=CONFIG)
    camera.add_argument("--robot-pose", type=Path, required=True)
    camera.add_argument("--view-id", choices=["V0", "D1", "D2", "D3", "D4"], default="V0")
    camera.add_argument("--scene-id", help="Reuse actual scene ID across its View recordings")
    camera.add_argument("--output", type=Path)
    camera.add_argument("--stopped-and-clear", action="store_true", required=True)
    check = commands.add_parser("check-recording", help="Check saved real arrays and Depth availability")
    check.add_argument("recording", type=Path)
    check.add_argument("--output", type=Path, help="Optional new result directory for RGB preview/report")
    rgb = commands.add_parser("infer-rgb", help="Actual YOLO before Board calibration is available")
    rgb.add_argument("recording", type=Path)
    measurement = commands.add_parser("measure", help="Actual geometry/fusion/optional accepted-state tracking")
    measurement.add_argument("recordings", nargs="+", type=Path)
    measurement.add_argument("--config", type=Path, default=CONFIG)
    measurement.add_argument("--calibration", type=Path, required=True)
    measurement.add_argument("--scene-stable", action="store_true", help="External actual scene stability confirmation")
    measurement.add_argument("--regions", type=Path, help="Actual per-View verification evidence, optional")
    measurement.add_argument("--previous-accepted", type=Path, help="Actual previous accepted placement list")
    measurement.add_argument("--ground-truth", type=Path, help="Human-checked actual placement list, not Expected")
    for command in (rgb, measurement):
        command.add_argument("--weights", type=Path, required=True)
        command.add_argument("--detector-confidence", type=float, required=True)
        command.add_argument("--output", type=Path)
    hand = commands.add_parser("watch-hand", help="Real V0 detector/gate without Backend IDs")
    hand.add_argument("--config", type=Path, default=CONFIG)
    hand.add_argument("--output", type=Path)
    hand.add_argument("--at-stopped-v0", action="store_true", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        print(json.dumps({"scope": "LOCAL_ONLY", "packages": {name: importlib.util.find_spec(name) is not None
              for name in ("numpy", "cv2", "yaml", "ultralytics", "pyrealsense2")},
              "device_or_model_validation": "not_performed"}, indent=2))
    elif args.command == "devices":
        list_devices()
    elif args.command == "capture":
        camera = read_json(args.config)["camera"]
        require_values(camera, "camera")
        output = args.output or new_path("recordings")
        scene = args.scene_id or output.name
        capture(output, camera["serial"], scene, args.view_id, read_json(args.robot_pose),
                camera["width"], camera["height"], camera["fps"], camera["timeout_ms"])
        original, report = recording_report(output)
        write_image(output / "rgb.png", original)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "check-recording":
        original, report = recording_report(args.recording)
        if args.output:
            write_report(args.output, report)
            write_image(args.output / "rgb.png", original)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "infer-rgb":
        original, source = recording_report(args.recording)
        detections = infer_masks(original, args.weights, args.detector_confidence)
        output = args.output or new_path("local_results")
        report = {"scope": "LOCAL_ONLY", "source": source,
                  "detections": [{"class": name, "model_confidence": confidence,
                                  "mask_file": f"mask_{i}.npy"}
                                 for i, (_, name, confidence) in enumerate(detections)],
                  "board_coordinates_or_layer": "not_computed", "not_empty_board_proof": True}
        write_report(output, report)
        overlay = original.copy()
        for i, (mask, _, _) in enumerate(detections):
            np.save(output / f"mask_{i}.npy", mask, allow_pickle=False)
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(overlay, contours, -1, (255, 0, 0), 2)
        write_image(output / "rgb.png", original)
        write_image(output / "mask_overlay.png", overlay)
        print(f"Actual RGB model results: {output}")
    elif args.command == "measure":
        measure_recordings(args)
    else:
        from .hand_cycle import HandCycle, HandDetector, monitor_hand
        settings = read_json(args.config)
        camera, hand = settings["camera"], settings["hand"]
        require_values(camera, "camera")
        require_values(hand, "hand")
        if hand["exit_seconds"] != 3.0:
            raise ValueError("hand exit must be strictly more than 3 seconds")
        detector = HandDetector(hand["weights"], hand["confidence"], hand["board_roi_v0"],
            min_valid_depth_fraction=hand["min_valid_depth_fraction"],
            stable_mean_difference=hand["stable_mean_difference"],
            image_size=hand.get("board_image_size"), board_polygon=hand.get("board_polygon_v0"))
        gate = HandCycle(hand["stable_seconds"], hand["max_frame_gap_seconds"])
        output = args.output or new_path("local_results").with_suffix(".jsonl")
        output.parent.mkdir(parents=True, exist_ok=True)
        stream = stream_v0(camera["serial"], camera["width"], camera["height"], camera["fps"], camera["timeout_ms"])
        monitor_hand(stream, detector, gate, output, {"scope": "LOCAL_ONLY"})


if __name__ == "__main__":
    main()
