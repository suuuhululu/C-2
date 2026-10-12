#!/usr/bin/env python3
"""Show quick blue/yellow block overlays from a RealSense ROS 2 color topic.

This is a visualization smoke test, not the final RGB-D grid algorithm.
Layer and confidence are intentionally fixed placeholders.
"""

from __future__ import annotations

import argparse

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


class ColorBlockOverlay(Node):
    def __init__(self, topic: str) -> None:
        super().__init__("color_block_overlay_demo")
        self.bridge = CvBridge()
        self.frames = 0
        self.subscription = self.create_subscription(
            Image,
            topic,
            self.on_image,
            qos_profile_sensor_data,
        )
        self.get_logger().info(f"Waiting for images on: {topic}")
        self.get_logger().info("Focus an OpenCV window and press q to quit, s to save.")

    @staticmethod
    def find_colored_blocks(
        frame: np.ndarray,
    ) -> tuple[dict[str, np.ndarray], list[tuple[str, np.ndarray]]]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        kernel = np.ones((5, 5), np.uint8)
        min_area = frame.shape[0] * frame.shape[1] * 0.0003

        ranges = {
            "BLUE": ((90, 80, 40), (140, 255, 255)),
            "YELLOW": ((15, 80, 70), (40, 255, 255)),
        }
        masks: dict[str, np.ndarray] = {}
        detections: list[tuple[str, np.ndarray]] = []

        for color_name, (lower, upper) in ranges.items():
            mask = cv2.inRange(hsv, lower, upper)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            masks[color_name] = mask

            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            valid = [
                contour
                for contour in contours
                if cv2.contourArea(contour) >= min_area
            ]
            valid.sort(key=cv2.contourArea, reverse=True)
            detections.extend((color_name, contour) for contour in valid)

        return masks, detections

    @staticmethod
    def annotate(
        frame: np.ndarray, detections: list[tuple[str, np.ndarray]]
    ) -> np.ndarray:
        output = frame.copy()
        cv2.putText(
            output,
            "REALTIME RGB DEMO",
            (24, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        if not detections:
            cv2.putText(
                output,
                "No blue/yellow block detected",
                (24, 82),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            return output

        color_counts = {"BLUE": 0, "YELLOW": 0}
        draw_colors = {"BLUE": (255, 255, 0), "YELLOW": (0, 255, 255)}

        for color_name, contour in detections:
            color_counts[color_name] += 1
            block_id = color_counts[color_name]
            draw_color = draw_colors[color_name]
            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect).astype(np.int32)
            cx, cy = np.rint(rect[0]).astype(int)
            width, height = rect[1]
            angle = rect[2]
            if width < height:
                angle += 90.0

            cv2.drawContours(output, [box], 0, draw_color, 3)
            cv2.circle(output, (cx, cy), 6, (0, 0, 255), -1)

            x, y, _, _ = cv2.boundingRect(contour)
            lines = [
                f"{color_name} BLOCK #{block_id}",
                "Layer: 1 (demo)",
                f"pixel: ({cx}, {cy})",
                f"angle: {angle:.1f} deg",
            ]
            panel_x = min(max(5, x), max(5, output.shape[1] - 300))
            panel_y = max(100, y - 120)
            overlay = output.copy()
            cv2.rectangle(
                overlay,
                (panel_x, panel_y - 30),
                (panel_x + 290, panel_y + 92),
                (0, 0, 0),
                -1,
            )
            cv2.addWeighted(overlay, 0.65, output, 0.35, 0, output)
            for i, line in enumerate(lines):
                cv2.putText(
                    output,
                    line,
                    (panel_x + 10, panel_y + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    draw_color,
                    2,
                    cv2.LINE_AA,
                )
        return output

    def on_image(self, message: Image) -> None:
        frame = self.bridge.imgmsg_to_cv2(message, desired_encoding="bgr8")
        masks, detections = self.find_colored_blocks(frame)
        output = self.annotate(frame, detections)
        self.frames += 1

        cv2.imshow("RealSense color-block overlay", output)
        cv2.imshow("Blue mask", masks["BLUE"])
        cv2.imshow("Yellow mask", masks["YELLOW"])
        key = cv2.waitKey(1) & 0xFF
        if key == ord("s"):
            cv2.imwrite("realsense_overlay_capture.jpg", output)
            self.get_logger().info("Saved: realsense_overlay_capture.jpg")
        elif key == ord("q"):
            rclpy.shutdown()

    def destroy_node(self) -> bool:
        cv2.destroyAllWindows()
        return super().destroy_node()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--topic",
        default="/camera/camera/color/image_raw",
        help="RealSense color Image topic",
    )
    args = parser.parse_args()

    rclpy.init()
    node = ColorBlockOverlay(args.topic)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        node.destroy_node()


if __name__ == "__main__":
    main()
