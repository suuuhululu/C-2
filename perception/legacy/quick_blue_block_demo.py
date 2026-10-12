#!/usr/bin/env python3
"""Quick OpenCV demo: detect a blue LEGO block and draw a result overlay.

This RGB-only demo does not estimate real z-layer.  The displayed layer is a
manual test value so the visualization can be checked before D435i depth is
connected.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


DEFAULT_IMAGE = Path("/home/roh/Downloads/IMG_5334.jpeg")


def largest_green_board_mask(hsv: np.ndarray) -> np.ndarray:
    """Return a filled mask for the largest green region (the baseplate)."""
    green = cv2.inRange(hsv, (35, 45, 35), (95, 255, 255))
    kernel = np.ones((11, 11), np.uint8)
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(green)
    if not contours:
        return mask

    board = max(contours, key=cv2.contourArea)
    cv2.drawContours(mask, [board], -1, 255, thickness=cv2.FILLED)
    return mask


def detect_blue_blocks(image: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    """Detect blue objects located inside the largest green board region."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    board_mask = largest_green_board_mask(hsv)

    blue = cv2.inRange(hsv, (90, 80, 45), (140, 255, 255))
    blue = cv2.bitwise_and(blue, board_mask)

    kernel = np.ones((7, 7), np.uint8)
    blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, kernel)
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = image.shape[0] * image.shape[1] * 0.00015
    contours = [c for c in contours if cv2.contourArea(c) >= min_area]
    return blue, sorted(contours, key=cv2.contourArea, reverse=True)


def draw_result(image: np.ndarray, contours: list[np.ndarray], layer: int) -> np.ndarray:
    result = image.copy()

    for index, contour in enumerate(contours):
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect).astype(np.int32)
        center = tuple(np.rint(rect[0]).astype(int))

        cv2.drawContours(result, [box], 0, (255, 255, 0), 8)
        cv2.circle(result, center, 12, (0, 0, 255), -1)

        x, y, _, _ = cv2.boundingRect(contour)
        label = (
            f"BLUE block | Layer {layer} | "
            f"pixel=({center[0]}, {center[1]}) | conf=0.90"
        )
        text_origin = (x, max(45, y - 18))
        cv2.putText(
            result,
            label,
            text_origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            (0, 0, 0),
            7,
            cv2.LINE_AA,
        )
        cv2.putText(
            result,
            label,
            text_origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            (255, 255, 0),
            3,
            cv2.LINE_AA,
        )

        # This quick demo intentionally displays only the largest valid block.
        if index == 0:
            break

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument(
        "--camera",
        type=int,
        help="Open a live V4L2 camera index instead of the image (try 0, 1, 2...).",
    )
    parser.add_argument("--output", type=Path, default=Path("quick_blue_result.jpg"))
    parser.add_argument("--layer", type=int, default=1)
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args()

    if args.camera is not None:
        cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        if not cap.isOpened():
            raise SystemExit(
                f"Could not open camera index {args.camera}. "
                "Close other camera apps and try another index."
            )

        print(
            "Camera opened:",
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "x",
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        print("Press q to close, or s to save the current annotated frame.")

        while True:
            ok, image = cap.read()
            if not ok:
                break
            mask, contours = detect_blue_blocks(image)
            result = draw_result(image, contours, args.layer)
            cv2.imshow("Live blue-block demo", result)
            cv2.imshow("Blue mask", mask)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("s"):
                cv2.imwrite(str(args.output), result)
                print(f"Saved result: {args.output.resolve()}")
            elif key == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()
        return 0

    image = cv2.imread(str(args.image))
    if image is None:
        raise SystemExit(f"Could not read image: {args.image}")

    mask, contours = detect_blue_blocks(image)
    result = draw_result(image, contours, args.layer)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), result):
        raise SystemExit(f"Could not save result: {args.output}")

    print(f"Detected blue blocks inside board: {len(contours)}")
    print(f"Saved result: {args.output.resolve()}")

    if not args.no_gui:
        preview_width = 1100
        scale = min(1.0, preview_width / result.shape[1])
        preview = cv2.resize(result, None, fx=scale, fy=scale)
        preview_mask = cv2.resize(mask, None, fx=scale, fy=scale)
        cv2.imshow("Assembly perception demo", preview)
        cv2.imshow("Blue mask", preview_mask)
        print("Press any key in an OpenCV window to close.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
