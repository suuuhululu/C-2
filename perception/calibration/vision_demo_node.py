#!/usr/bin/env python3
"""ROS 2 candidate publisher example; does not command a robot or gripper."""
import json
import math
import time

import cv2

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge, CvBridgeError

from lego_grid import detect_candidates, read_image, validate_view
from vision_coordinates import BoardCoordinateMapper


class LegoVisionDemo(Node):
    def __init__(self):
        super().__init__("lego_vision_demo")
        defaults = {"calibration_file": "runs/view01/calibration.json",
                    "image_topic": "/camera/camera/color/image_raw",
                    "expected_camera_frame": "camera_color_optical_frame",
                    "surface_height_mm": 0.0, "allow_unvalidated": False,
                    "process_period_sec": 0.5, "marker_max_error_mm": 1.5}
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        get = lambda key: self.get_parameter(key).value
        self.mapper = BoardCoordinateMapper(get("calibration_file"), get("allow_unvalidated"))
        self.c = self.mapper.calibration
        self.empty = read_image(self.mapper.path.parent / self.c["baseline_file"])
        self.height = float(get("surface_height_mm"))
        self.period = float(get("process_period_sec"))
        if not math.isfinite(self.height) or not math.isfinite(self.period) or self.height < 0 or self.period <= 0:
            raise ValueError("Invalid height or processing period")
        self.expected_frame = get("expected_camera_frame")
        self.marker_max_error = float(get("marker_max_error_mm"))
        self.bridge = CvBridge()
        self.publisher = self.create_publisher(String, "/lego/board_candidates", 10)
        self.subscription = self.create_subscription(Image, get("image_topic"), self.callback,
                                                      qos_profile_sensor_data)
        self.last_processed = 0.0
        self.last_error = 0.0
        self.get_logger().info("Publishing candidate regions in lego_board frame, mm. Confirm the fixed wrist view.")
        if not self.mapper.validated:
            self.get_logger().warn("Provisional calibration: messages are explicitly labelled unvalidated.")

    def callback(self, msg):
        now = time.monotonic()
        if now - self.last_processed < self.period:
            return
        self.last_processed = now
        try:
            if self.expected_frame and msg.header.frame_id != self.expected_frame:
                raise ValueError("Unexpected camera frame ID")
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            view = validate_view(self.c, image, self.marker_max_error)
            candidates, _, _, changed = detect_candidates(self.c, self.empty, image, self.height)
            for item in candidates:
                item["row_index_0based"] = item["row_continuous"] - 1
                item["col_index_0based"] = item["col_continuous"] - 1
            payload = {"stamp": {"sec": msg.header.stamp.sec, "nanosec": msg.header.stamp.nanosec},
                       "frame_id": "lego_board", "source_camera_frame": msg.header.frame_id,
                       "length_unit": "mm", "independently_validated": self.mapper.validated,
                       "view_check": view, "surface_height_mm": self.height,
                       "status": "scene_changed_too_much" if changed > 0.5 else "candidates_require_inspection",
                       "changed_fraction": changed, "candidates": candidates}
            output = String()
            output.data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            self.publisher.publish(output)
        except (ValueError, KeyError, RuntimeError, CvBridgeError, cv2.error) as error:
            if now - self.last_error > 5:
                self.get_logger().error(f"Frame rejected: {error}")
                self.last_error = now


def main():
    rclpy.init()
    node = None
    try:
        node = LegoVisionDemo()
        rclpy.spin(node)
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
