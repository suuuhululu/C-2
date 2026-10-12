"""One stopped-camera sample. Does not command the robot or detect hands."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from rgbd_io import save_frame


def camera_info(profile):
    intr = profile.as_video_stream_profile().get_intrinsics()
    return {"width": intr.width, "height": intr.height, "fx": intr.fx, "fy": intr.fy,
            "cx": intr.ppx, "cy": intr.ppy, "model": str(intr.model).split(".")[-1],
            "coefficients": list(intr.coeffs)}


def capture(directory, serial, scene_id, view_id, robot_pose, width, height, fps, timeout_ms,
            *, observation_context=None):
    if not serial or not scene_id or view_id not in ("V0", "D1", "D2", "D3", "D4"):
        raise ValueError("serial, scene and supported view required")
    if min(width, height, fps, timeout_ms) <= 0:
        raise ValueError("positive stream settings and timeout required")
    if not isinstance(robot_pose, dict) or not robot_pose:
        raise ValueError("record robot pose with frame, units and convention")
    if Path(directory).exists():
        raise FileExistsError(directory)
    if observation_context is not None:
        if set(observation_context) != {"check_id", "observation_seq", "calibration_id"}:
            raise ValueError("capture context requires check_id, observation_seq, calibration_id")
        if any(not isinstance(observation_context[k], str) or not observation_context[k]
               for k in ("check_id", "calibration_id")):
            raise ValueError("nonempty observation identifiers required")
        seq = observation_context["observation_seq"]
        if type(seq) is not int or seq < 0:
            raise ValueError("nonnegative bundle-start sequence required")
    import pyrealsense2 as rs
    pipeline = rs.pipeline()
    settings = rs.config()
    settings.enable_device(serial)
    settings.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
    settings.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
    profile = pipeline.start(settings)
    try:
        frames = pipeline.wait_for_frames(timeout_ms)
        raw = frames.get_depth_frame()
        aligned = rs.align(rs.stream.color).process(frames)
        color, depth = aligned.get_color_frame(), aligned.get_depth_frame()
        if not raw or not color or not depth:
            raise RuntimeError("missing RGB or Depth frame")
        metadata = {"scene_id": scene_id, "view_id": view_id, "mode": "REAL",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "robot_pose": robot_pose, "serial": serial,
                    "depth_scale_m": profile.get_device().first_depth_sensor().get_depth_scale(),
                    "camera_info": {"raw": camera_info(raw.profile),
                                    "aligned": camera_info(depth.profile),
                                    "color": camera_info(color.profile)},
                    "depth_to_color_extrinsics": {
                        "rotation": list(raw.profile.get_extrinsics_to(color.profile).rotation),
                        "translation_m": list(raw.profile.get_extrinsics_to(color.profile).translation)},
                    "sensor_timestamps_ms": {"raw": raw.get_timestamp(), "color": color.get_timestamp(),
                                              "aligned": depth.get_timestamp()},
                    "timestamp_domain": str(color.get_frame_timestamp_domain()),
                    "filters": "none", "alignment": "depth_to_color"}
        if observation_context is not None:
            metadata.update(observation_context)
        save_frame(directory, np.asanyarray(color.get_data()).copy(),
                   np.asanyarray(raw.get_data()).copy(), np.asanyarray(depth.get_data()).copy(), metadata)
    finally:
        pipeline.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    for name in ("serial", "scene-id", "view-id", "robot-pose", "mode"):
        parser.add_argument("--" + name, required=True)
    for name in ("width", "height", "fps", "timeout-ms"):
        parser.add_argument("--" + name, type=int, required=True)
    args = parser.parse_args()
    if args.mode != "REAL":
        parser.error("camera capture requires explicit --mode REAL; TEST uses save_frame")
    capture(args.directory, args.serial, args.scene_id, args.view_id,
            json.loads(Path(args.robot_pose).read_text()), args.width, args.height,
            args.fps, args.timeout_ms)


if __name__ == "__main__":
    main()
