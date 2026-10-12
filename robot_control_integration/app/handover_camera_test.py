"""Existing ROS RGB-D subscriptions only; no device opening, publishers or robot calls."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

from app.handover_vision import landmark_hand

CASES = {
    "palm": "편 손바닥을 카메라에 보여주세요",
    "back": "편 손등을 카메라에 보여주세요",
    "side": "손을 옆으로 돌려 보여주세요",
    "withdrawn": "손을 화면 밖으로 빼주세요",
    "occluded": "손 일부를 가려주세요",
}


def image_array(message, *, depth=False):
    import numpy as np
    formats = {"16UC1": ("u2", 1), "32FC1": ("f4", 1)} if depth else {
        "rgb8": ("u1", 3), "bgr8": ("u1", 3)}
    if message.encoding not in formats:
        raise ValueError(f"unsupported image encoding: {message.encoding}")
    dtype, channels = formats[message.encoding]
    dtype = np.dtype(dtype).newbyteorder(">" if message.is_bigendian else "<")
    row_bytes = message.width * channels * dtype.itemsize
    if min(message.width, message.height) <= 0 or message.step < row_bytes or len(message.data) != message.step * message.height:
        raise ValueError("invalid image dimensions/stride/data length")
    raw = np.frombuffer(bytes(message.data), dtype=np.uint8).reshape(message.height, message.step)
    array = raw[:, :row_bytes].copy().view(dtype).reshape(message.height, message.width, channels)
    if depth:
        return array[:, :, 0]
    return array[:, :, ::-1].copy() if message.encoding == "bgr8" else array


def frame_metadata(message, received_ns):
    return dict(source_ns=message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec,
                received_monotonic_ns=received_ns, frame=message.header.frame_id,
                width=message.width, height=message.height)


def inspect_frame(rgb, depth, landmarks):
    """Open shape is diagnostic evidence; surface/identity/scale remain unverified."""
    hands = []
    for points in landmarks:
        hand = landmark_hand(points, None, depth, processed_size=(rgb.shape[1], rgb.shape[0]),
                             processed_to_raw=[[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        values = hand.pop("interior_depth")
        valid = [v for v in values if v > 0 and math.isfinite(v)]
        hand.update(depth_valid_fraction=len(valid) / len(values) if values else 0,
                    landmarks=points, depth_m=None)
        hands.append(hand)
    return dict(hands=hands, hand_count=len(hands), ready=False,
                reason="RECEIVING_ORIENTATION_TRACKING_AND_SCALE_UNVERIFIED",
                real_output_enabled=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rgb-topic", required=True)
    parser.add_argument("--depth-topic", required=True)
    parser.add_argument("--info-topic", required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--case", choices=("unlabeled", *CASES), default="unlabeled")
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--no-window", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 60 or (not args.probe_only and args.model is None):
        parser.error("seconds must be 1..60; inference requires --model")
    args.output.mkdir(parents=True, exist_ok=False)
    import cv2
    import numpy as np
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, CameraInfo
    from rosidl_runtime_py.convert import message_to_ordereddict
    model = node = None
    latest, counts = {}, dict(rgb=0, depth=0, info=0)
    status = dict(status="UNKNOWN", reason="NO_COMPLETE_FRESH_RGBD", frames=0,
                  real_output_enabled=False, motion_commands_sent=False,
                  hand_frames=0, open_hand_frames=0, no_hand_frames=0, multiple_hand_frames=0)
    output = (args.output / "frames.jsonl").open("x", encoding="utf-8")

    def receive(name, message):
        latest[name] = (message, time.monotonic_ns())
        counts[name] += 1

    try:
        if not args.probe_only:
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            model = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model)), num_hands=2))
            status["model_sha256"] = hashlib.sha256(args.model.read_bytes()).hexdigest()
        rclpy.init(args=[])
        node = rclpy.create_node("handover_readonly_camera_test")
        for name, typename, topic in (("rgb", Image, args.rgb_topic), ("depth", Image, args.depth_topic),
                                      ("info", CameraInfo, args.info_topic)):
            node.create_subscription(typename, topic, lambda msg, key=name: receive(key, msg), qos_profile_sensor_data)
        deadline, next_frame, seen = time.monotonic() + args.seconds, 0, set()
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            now = time.monotonic_ns()
            if len(latest) < 3 or time.monotonic() < next_frame:
                continue
            if any(now - received > 1_000_000_000 for _, received in latest.values()):
                continue
            rgb_msg, rgb_received = latest["rgb"]
            depth_msg, depth_received = latest["depth"]
            info_msg, _ = latest["info"]
            rgb_meta, depth_meta = frame_metadata(rgb_msg, rgb_received), frame_metadata(depth_msg, depth_received)
            identity = (rgb_meta["source_ns"], depth_meta["source_ns"])
            if identity in seen or min(identity) <= 0 or abs(identity[0] - identity[1]) > 100_000_000:
                continue
            if not rgb_meta["frame"] or rgb_meta["frame"] != depth_meta["frame"] or info_msg.header.frame_id != rgb_meta["frame"]:
                raise ValueError("RGB/aligned depth/CameraInfo frame mismatch")
            rgb, depth = image_array(rgb_msg), image_array(depth_msg, depth=True)
            if depth.shape != rgb.shape[:2] or (info_msg.height, info_msg.width) != rgb.shape[:2]:
                raise ValueError("RGB/aligned depth/CameraInfo dimensions mismatch")
            seen.add(identity)
            next_frame = time.monotonic() + 1  # Bounded diagnostic samples, not the control-loop rate.
            index = status["frames"]
            event = dict(provenance="SENSOR", expected_case=args.case, source_clock="ros_stamp_unverified",
                         received_clock="local_monotonic", rgb=rgb_meta, depth=depth_meta,
                         stamp_difference_ns=abs(identity[0] - identity[1]), clock_mapping_verified=False,
                         depth_scale_m=None, alignment_verified=False)
            if model is not None:
                points = model.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
                landmarks = [[dict(x=p.x, y=p.y, z=p.z) for p in hand] for hand in points.hand_landmarks]
                event.update(inspect_frame(rgb, depth, landmarks))
                status["hand_frames"] += int(event["hand_count"] > 0)
                status["no_hand_frames"] += int(event["hand_count"] == 0)
                status["multiple_hand_frames"] += int(event["hand_count"] > 1)
                status["open_hand_frames"] += int(any(hand["open_hand"] for hand in event["hands"]))
            else:
                event.update(ready=False, real_output_enabled=False)
            png = args.output / f"rgb-{index:03d}.png"
            if not cv2.imwrite(str(png), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
                raise OSError("RGB snapshot write failed")
            depth_path = args.output / f"depth-{index:03d}.npy"
            np.save(depth_path, depth, allow_pickle=False)
            event.update(rgb_file=png.name, rgb_sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
                         depth_file=depth_path.name, depth_sha256=hashlib.sha256(depth_path.read_bytes()).hexdigest())
            output.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            output.flush()
            if index == 0:
                (args.output / "camera_info.json").write_text(json.dumps(message_to_ordereddict(info_msg)), encoding="utf-8")
            status["frames"] += 1
            print(f"{args.case}: frame={index} hands={event.get('hand_count', 'probe')} ready=False", flush=True)
            if not args.no_window:
                display = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                cv2.putText(display, f"{args.case}: hands={event.get('hand_count', '-')} / READ ONLY / ready=False",
                            (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                for hand in event.get("hands", []):
                    for p in hand["landmarks"]:
                        cv2.circle(display, (int(p["x"] * rgb.shape[1]), int(p["y"] * rgb.shape[0])), 3, (0, 255, 0), -1)
                cv2.imshow("Handover sensor test", display)
                if cv2.waitKey(1) & 255 == ord("q"):
                    raise KeyboardInterrupt()
        if status["frames"] >= 2:
            status.update(status="CAPTURED", reason=None)
    except (Exception, KeyboardInterrupt) as exc:
        status.update(status="FAIL" if not isinstance(exc, KeyboardInterrupt) else "UNKNOWN",
                      reason=str(exc) or "INTERRUPTED")
        print(f"카메라 시험 보류: {status['reason']}", flush=True)
    finally:
        output.close()
        if model is not None:
            model.close()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if not args.no_window:
            cv2.destroyAllWindows()
        status.update(received_counts=counts, expected_case=args.case, inference_enabled=not args.probe_only,
                      recognition_verdict="UNKNOWN", orientation_verified=False, depth_scale_m=None)
        (args.output / "result.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if status["status"] == "CAPTURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
