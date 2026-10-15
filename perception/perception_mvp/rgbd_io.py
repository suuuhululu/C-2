"""Local recording format v1; not a Backend schema. Depth is never colorized."""
import argparse
from collections import deque
import json
from datetime import datetime, timezone
from pathlib import Path
import time

import cv2
import numpy as np


def stream_v0(serial, width, height, fps, timeout_ms):
    """Caller/Controller must confirm stopped V0. No camera restart or robot motion."""
    if not serial or min(width, height, fps, timeout_ms) <= 0:
        raise ValueError("explicit serial and positive stream settings required")
    import pyrealsense2 as rs
    pipeline, settings = rs.pipeline(), rs.config()
    settings.enable_device(serial)
    settings.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
    settings.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
    pipeline.start(settings)
    align = rs.align(rs.stream.color)
    try:
        while True:
            frames = align.process(pipeline.wait_for_frames(timeout_ms))
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            if not color or not depth:
                raise RuntimeError("missing live RGB/Depth; never assume hand absent")
            yield (np.asanyarray(color.get_data()).copy(),
                   np.asanyarray(depth.get_data()).copy(), time.monotonic())
    finally:
        pipeline.stop()


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


def write_cycle_json(path, value):
    """Exclusive evidence writes: never replace earlier recordings or reports."""
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def begin_cycle_archive(root, context, calibration, config, weights, confidence):
    directory = Path(root) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, exist_ok=False)
    write_cycle_json(directory / "context.json", dict(manifest=context,
        calibration=calibration, config=config, weights=str(weights),
        detector_confidence=confidence, scope="OBSERVATION_EVIDENCE_NOT_BACKEND_ACCEPTANCE"))
    return directory


def save_cycle_view(directory, view, rgb, raw, aligned, metadata, source):
    target = Path(directory) / view
    save_frame(target, rgb, raw, aligned, metadata)
    for name, array in (("rgb.png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)),
                        ("depth_raw.png", raw), ("depth_aligned.png", aligned)):
        if not cv2.imwrite(str(target / name), array):
            raise OSError("failed to save cycle " + name)
    write_cycle_json(target / "source.json", dict(directory=str(Path(source).resolve())))
    return target


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


def stamp(message):
    return message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec


def image_array(message):
    """Preserve 16-bit values, endianness and ROS row padding; never normalize Depth."""
    formats = {"rgb8": (np.dtype("u1"), 3), "bgr8": (np.dtype("u1"), 3),
               "16UC1": (np.dtype(">u2" if message.is_bigendian else "<u2"), 1)}
    if message.encoding not in formats:
        raise ValueError("unsupported image encoding: " + message.encoding)
    dtype, channels = formats[message.encoding]
    row_bytes = message.width * channels * dtype.itemsize
    if (message.width <= 0 or message.height <= 0 or message.step < row_bytes or
            len(message.data) != message.step * message.height):
        raise ValueError("invalid image dimensions/step/data")
    rows = np.frombuffer(bytes(message.data), np.uint8).reshape(message.height, message.step)
    result = rows[:, :row_bytes].copy().view(dtype).reshape(
        (message.height, message.width, channels) if channels == 3 else (message.height, message.width))
    if channels == 1:
        return result.astype(np.uint16)
    return result[:, :, ::-1].copy() if message.encoding == "bgr8" else result


def info_dict(message):
    return {"width": message.width, "height": message.height,
            "frame_id": message.header.frame_id, "distortion_model": message.distortion_model,
            "d": list(message.d), "k": list(message.k), "r": list(message.r), "p": list(message.p)}


def save_capture(directory, messages, infos, topics, view, max_delta_ms, *, context=None):
    """Save ROS evidence; optional context binds a real inspection, not coverage."""
    from copy import deepcopy
    context = deepcopy(context)
    if context is not None:
        required = {"scene_id", "robot_pose", "calibration_id", "check_id", "observation_seq"}
        if set(context) != required:
            raise ValueError("inspection capture context requires scene/pose/calibration/check/sequence")
        for key in ("scene_id", "calibration_id", "check_id"):
            if not isinstance(context[key], str) or not context[key].strip():
                raise ValueError("nonempty capture context required: " + key)
        if not isinstance(context["robot_pose"], dict) or not context["robot_pose"]:
            raise ValueError("actual robot pose metadata required")
        if type(context["observation_seq"]) is not int or context["observation_seq"] < 0:
            raise ValueError("nonnegative observation sequence required")
    rgb, raw, aligned = [image_array(messages[k]) for k in ("rgb", "raw", "aligned")]
    if messages["rgb"].encoding not in ("rgb8", "bgr8") or any(
            messages[k].encoding != "16UC1" for k in ("raw", "aligned")):
        raise ValueError("RGB8/BGR8 and original 16UC1 Depth required")
    if rgb.shape[:2] != aligned.shape:
        raise ValueError("aligned Depth dimensions differ from RGB")
    for key, array in (("rgb", rgb), ("raw", raw), ("aligned", aligned)):
        info = infos[key]
        if ((info.height, info.width) != array.shape[:2] or
                info.header.frame_id != messages[key].header.frame_id):
            raise ValueError("camera_info dimensions/frame mismatch: " + key)
    timestamps = {k: stamp(v) for k, v in messages.items()}
    delta = (max(timestamps.values()) - min(timestamps.values())) / 1e6
    if delta > max_delta_ms or not any(timestamps.values()):
        raise ValueError("image timestamp synchronization unavailable")
    if not np.count_nonzero(aligned):
        raise ValueError("aligned Depth is entirely invalid (zero); capture rejected")
    metadata = {"recording_format": "ros_rgbd_capture_v1", "mode": "REAL",
        "scope": "CAPTURE_ONLY", "view_id": view, "captured_at": datetime.now(timezone.utc).isoformat(),
        "topics": topics, "sensor_timestamps_ns": timestamps, "timestamp_span_ms": delta,
        "synchronization": {"max_delta_ms": max_delta_ms, "threshold_status": "temporary_test"},
        "camera_info": {k: info_dict(v) for k, v in infos.items()},
        "depth_scale_m": .001, "depth_unit_basis": "RealSense ROS published 16UC1 millimeters",
        "valid_aligned_depth_fraction": float(np.count_nonzero(aligned) / aligned.size),
        "robot_pose": None, "calibration_id": None,
        "limitations": ["pose_and_board_calibration_not_recorded", "not_ready_for_board_geometry",
                        "ROS_driver_filters_not_verified", "not_backend_observation"]}
    if context is not None:
        # Preserve ROS CameraInfo and expose deprojection fields used by depth_grid.
        for key, info in infos.items():
            model = {"plumb_bob": "brown_conrady", "": "none"}.get(info.distortion_model)
            if model is None:
                raise ValueError("unsupported ROS distortion model: " + info.distortion_model)
            coefficients = list(info.d)
            if model == "brown_conrady" and len(coefficients) != 5:
                raise ValueError("five measured distortion coefficients required")
            metadata["camera_info"][key].update(fx=info.k[0], fy=info.k[4],
                cx=info.k[2], cy=info.k[5], model=model, coefficients=coefficients)
        metadata.update(context)
        metadata["scope"] = "INSPECTION_CAPTURE_NOT_VERIFIED_OCCUPANCY"
        metadata["limitations"] = ["ROS_driver_filters_not_verified", "not_backend_observation",
                                   "verified_regions_require_separate_occupancy_evidence"]
        validate_frame(rgb, raw, aligned, metadata)
    encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2)
    directory.mkdir(parents=True, exist_ok=False)
    # Raw and aligned are distinct arrays; never copy aligned values into the raw file.
    np.save(directory / "rgb.npy", rgb, allow_pickle=False)
    np.save(directory / "depth_raw.npy", raw, allow_pickle=False)
    np.save(directory / "depth_aligned.npy", aligned, allow_pickle=False)
    for name, array in (("rgb.png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)),
                        ("depth_raw.png", raw), ("depth_aligned.png", aligned)):
        if not cv2.imwrite(str(directory / name), array):
            raise OSError("failed to save " + name)
    (directory / "metadata.json").write_text(encoded, encoding="utf-8")
    print("저장 완료: " + str(directory.resolve()))
    print("RGB + 원본/정렬 16-bit Depth + camera_info 저장. 유효 Depth 비율: "
          + f"{metadata['valid_aligned_depth_fraction']:.1%}")


def ros_main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("V0", "D1", "D2", "D3", "D4"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stopped-and-clear", action="store_true", required=True,
                        help="User confirms actual Robot stop and hand absence; not an interlock")
    parser.add_argument("--timeout", type=float, default=15., help="One-shot wait timeout seconds")
    parser.add_argument("--max-delta-ms", type=float, default=50., help="Temporary trial sync limit")
    defaults = {"rgb": "/camera/color/image_raw", "raw": "/camera/depth/image_rect_raw",
                "aligned": "/camera/aligned_depth_to_color/image_raw",
                "rgb-info": "/camera/color/camera_info", "raw-info": "/camera/depth/camera_info",
                "aligned-info": "/camera/aligned_depth_to_color/camera_info"}
    for key, topic in defaults.items():
        parser.add_argument("--" + key + "-topic", default=topic)
    args = parser.parse_args(argv)
    if (not np.isfinite(args.timeout) or args.timeout <= 0 or
            not np.isfinite(args.max_delta_ms) or args.max_delta_ms <= 0):
        parser.error("positive finite timeout and synchronization limit required")
    # Every invocation creates a unique frame; repeated capture never overwrites data.
    directory = args.output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import Image, CameraInfo
    rclpy.init(args=[])
    node = rclpy.create_node("perception_rgbd_save")
    image_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
    queues = {k: deque(maxlen=10) for k in ("rgb", "raw", "aligned")}
    infos, topics, subscriptions = {}, {}, []
    try:
        for key in queues:
            topic = getattr(args, key + "_topic")
            topics[key] = topic
            subscriptions.append(node.create_subscription(Image, topic,
                lambda msg, k=key: queues[k].append(msg), image_qos))
            topic = getattr(args, key + "_info_topic")
            topics[key + "_info"] = topic
            subscriptions.append(node.create_subscription(CameraInfo, topic,
                lambda msg, k=key: infos.update({k: msg}), qos_profile_sensor_data))
        print("실행 중인 ROS 카메라의 RGB·Depth 수신 대기…", flush=True)
        deadline = time.monotonic() + args.timeout
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
            if len(infos) != 3 or not all(queues.values()):
                continue
            rgb = queues["rgb"][-1]
            messages = {"rgb": rgb, **{k: min(queues[k], key=lambda m: abs(stamp(m) - stamp(rgb)))
                                        for k in ("raw", "aligned")}}
            stamps = [stamp(m) for m in messages.values()]
            if (max(stamps) - min(stamps)) / 1e6 <= args.max_delta_ms:
                save_capture(directory, messages, infos, topics, args.view, args.max_delta_ms)
                return
        missing = [topics[k] for k, queue in queues.items() if not queue]
        missing += [topics[k + "_info"] for k in queues if k not in infos]
        raise TimeoutError("수신하지 못한 토픽: " + ", ".join(missing) if missing else
                           "RGB/Depth timestamps could not be synchronized")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    ros_main()
