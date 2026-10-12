#!/usr/bin/env python3
"""Read-only ROS 2 color capture + matching CameraInfo. Never imports a robot driver."""
import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from geometry import load_intrinsics, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-topic", default="/camera/color/image_raw")
    parser.add_argument("--info-topic", default="/camera/color/camera_info")
    parser.add_argument("--out", required=True, help="Image PNG path; matching .intrinsics.json also saved")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, CameraInfo
    from cv_bridge import CvBridge

    rclpy.init()
    node = rclpy.create_node("lego_readonly_capture")
    bridge = CvBridge()
    received = {}

    def image_callback(msg):
        received["image"] = msg
        received["image_time"] = time.monotonic()

    def info_callback(msg):
        received["info"] = msg

    image_sub = node.create_subscription(Image, args.image_topic, image_callback, qos_profile_sensor_data)
    info_sub = node.create_subscription(CameraInfo, args.info_topic, info_callback, qos_profile_sensor_data)
    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if "image" not in received or "info" not in received:
                continue
            msg, info = received["image"], received["info"]
            if msg.header.frame_id != info.header.frame_id:
                continue
            if [msg.width, msg.height] != [info.width, info.height]:
                continue
            if time.monotonic() - received["image_time"] > 1.0:
                continue
            # Dynamic CameraInfo should match closely. Timestamp 0 is allowed for static calibration.
            image_ns = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
            info_ns = info.header.stamp.sec * 10**9 + info.header.stamp.nanosec
            if info_ns and abs(image_ns - info_ns) > 200_000_000:
                continue
            frame = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            intrinsic = {"image_size": [info.width, info.height],
                         "camera_matrix": np.asarray(info.k).reshape(3, 3).tolist(),
                         "dist_coeffs": list(info.d), "distortion_model": info.distortion_model or "none",
                         "frame_id": info.header.frame_id, "image_topic": args.image_topic,
                         "info_topic": args.info_topic, "image_stamp_ns": image_ns}
            out = Path(args.out)
            intrinsic_path = out.with_suffix(".intrinsics.json")
            # Check supported camera model before writing a usable capture.
            out.parent.mkdir(parents=True, exist_ok=True)
            write_json(intrinsic_path, intrinsic)
            load_intrinsics(intrinsic_path, [frame.shape[1], frame.shape[0]])
            if not cv2.imwrite(str(out), frame):
                raise RuntimeError(f"Cannot save {out}")
            print(f"Saved {out} and {intrinsic_path}")
            return
        raise RuntimeError("No compatible color/CameraInfo pair within timeout; check topics, frame IDs and timestamps")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
