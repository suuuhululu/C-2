"""Local recording format v1; not a Backend schema. Depth is never colorized."""
import json
from pathlib import Path

import numpy as np


def validate_frame(rgb, depth_raw, depth_aligned, metadata):
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("rgb must be uint8 RGB HxWx3")
    for depth in (depth_raw, depth_aligned):
        if depth.dtype != np.uint16 or depth.ndim != 2:
            raise ValueError("depth must be original uint16 sensor units")
    if depth_aligned.shape != rgb.shape[:2]:
        raise ValueError("aligned depth and RGB shapes differ")
    for key in ("scene_id", "view_id", "captured_at", "camera_info",
                "depth_scale_m", "robot_pose", "mode"):
        if key not in metadata:
            raise ValueError(f"missing metadata: {key}")
    if metadata["mode"] not in ("TEST", "REAL"):
        raise ValueError("explicit TEST or REAL mode required")
    if metadata["mode"] == "REAL" and not metadata["robot_pose"]:
        raise ValueError("REAL recording requires measured robot pose metadata")
    if metadata["view_id"] not in ("V0", "D1", "D2", "D3", "D4"):
        raise ValueError("unsupported view_id")
    if not np.isfinite(metadata["depth_scale_m"]) or metadata["depth_scale_m"] <= 0:
        raise ValueError("invalid depth scale")
    if any(not metadata[k] for k in ("scene_id", "captured_at", "camera_info")):
        raise ValueError("scene, timestamp and camera_info cannot be empty")


def save_frame(directory, rgb, depth_raw, depth_aligned, metadata):
    validate_frame(rgb, depth_raw, depth_aligned, metadata)
    encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    np.save(directory / "rgb.npy", rgb, allow_pickle=False)
    np.save(directory / "depth_raw.npy", depth_raw, allow_pickle=False)
    np.save(directory / "depth_aligned.npy", depth_aligned, allow_pickle=False)
    (directory / "metadata.json").write_text(encoded, encoding="utf-8")


def load_frame(directory):
    directory = Path(directory)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    arrays = [np.load(directory / name, allow_pickle=False) for name in
              ("rgb.npy", "depth_raw.npy", "depth_aligned.npy")]
    validate_frame(*arrays, metadata)
    return (*arrays, metadata)
