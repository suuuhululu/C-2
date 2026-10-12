#!/usr/bin/env python3
"""Capture, calibrate, validate and locate objects on a fixed LEGO board."""
import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from geometry import (board_to_pixels, check_image_size, describe_point, export_grid,
                      fit_calibration, fit_robot_frame, load_intrinsics, pixel_to_board,
                      points_array, read_json, write_json)


def read_image(path):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    return image


def save_image(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise ValueError(f"Cannot save image: {path}")


def click_points(image, labels, context=None):
    """Display raw pixels at 1:1 scale; no unaccounted UI rescaling."""
    selected = []
    window = "Reference points - ENTER accept, U undo, ESC cancel"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)

    def mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(selected) < len(labels):
            selected.append([float(x), float(y)])

    cv2.setMouseCallback(window, mouse)
    try:
        while True:
            shown = image.copy()
            for i, point in enumerate(selected):
                p = tuple(map(int, point))
                cv2.circle(shown, p, 5, (0, 0, 255), 2)
                short_label = labels[i].split(" | ", 1)[0]
                cv2.putText(shown, short_label, (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
                cv2.putText(shown, short_label, (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            message = f"Click {labels[len(selected)]}" if len(selected) < len(labels) else "ENTER to accept"
            for text, y in ((message, 25), (context, 50)):
                if text:
                    cv2.putText(shown, text, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
                    cv2.putText(shown, text, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            cv2.imshow(window, shown)
            key = cv2.waitKey(30) & 0xFF
            if key == 27 or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                raise ValueError("Point selection cancelled")
            if key in (ord("u"), ord("U")) and selected:
                selected.pop()
            if key in (10, 13) and len(selected) == len(labels):
                return selected
    finally:
        cv2.destroyWindow(window)


def aruco_references(image, layout):
    if not hasattr(cv2, "aruco"):
        raise ValueError("ArUco requires OpenCV contrib; use manual points or opencv-contrib-python")
    name = layout.get("dictionary", "DICT_4X4_50")
    if not name.startswith("DICT_") or not hasattr(cv2.aruco, name):
        raise ValueError("Unknown ArUco dictionary")
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if hasattr(cv2.aruco, "ArucoDetector"):
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        corners, ids, _ = cv2.aruco.ArucoDetector(dictionary, parameters).detectMarkers(gray)
    else:
        parameters = cv2.aruco.DetectorParameters_create()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        corners, ids, _ = cv2.aruco.detectMarkers(gray, dictionary, parameters=parameters)
    if ids is None:
        raise ValueError("No ArUco markers detected")
    ids = ids.ravel().tolist()
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate marker IDs in image")
    detected = dict(zip(ids, corners))
    pixels, board = [], []
    # Every configured marker is mandatory; no partial fit from one small marker.
    for marker in layout["markers"]:
        marker_id = int(marker["id"])
        if marker_id not in detected:
            raise ValueError(f"Required marker ID {marker_id} is not visible")
        xy = points_array(marker["corners_board_xy_mm"], 2, 4)
        if xy.shape != (4, 2):
            raise ValueError("Each marker needs exactly four measured corners in decoded marker order")
        pixels.extend(detected[marker_id].reshape(4, 2).tolist())
        board.extend(xy.tolist())
    return pixels, board


def draw_grid(calibration, image):
    output = image.copy()
    p = calibration["pitch_mm"]
    for row in range(calibration["rows"]):
        xy = [[col * p, row * p] for col in range(calibration["cols"])]
        uv = np.rint(board_to_pixels(calibration, xy)).astype(np.int32)
        cv2.polylines(output, [uv], False, (200, 200, 200), 1)
        for point in uv:
            cv2.circle(output, tuple(point), 2, (0, 0, 255), -1)
    for col in range(calibration["cols"]):
        uv = np.rint(board_to_pixels(calibration, [[col * p, row * p] for row in range(calibration["rows"])])).astype(np.int32)
        cv2.polylines(output, [uv], False, (200, 200, 200), 1)
    for label, xy in (
            ("A (x=0,y=0)", [0, 0]),
            (f"B (x={calibration['cols'] - 1},y=0)",
            [(calibration["cols"] - 1) * p, 0]),
            (f"C (x={calibration['cols'] - 1},y={calibration['rows'] - 1})",
            [(calibration["cols"] - 1) * p, (calibration["rows"] - 1) * p]),
            (f"D (x=0,y={calibration['rows'] - 1})",
         [  0, (calibration["rows"] - 1) * p]),
    ):
        uv = tuple(np.rint(board_to_pixels(calibration, [xy])[0]).astype(int))
        cv2.putText(output, label, uv, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    return output


def calibrate(args):
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory is not empty; use a new run directory")
    image = read_image(args.image)
    size = [image.shape[1], image.shape[0]]
    intrinsics = load_intrinsics(args.intrinsics, size)
    p = args.pitch_mm
    if args.points:
        refs = read_json(args.points)
        pixels, board = refs["pixel_xy"], refs["board_xy_mm"]
    elif args.markers:
        pixels, board = aruco_references(image, read_json(args.markers))
    else:
        board = [[0, 0], [(args.cols - 1) * p, 0],
                 [(args.cols - 1) * p, (args.rows - 1) * p], [0, (args.rows - 1) * p]]
        pixels = click_points(image, ["A: row1 col1 stud CENTRE", f"B: row1 col{args.cols} stud CENTRE",
                                      f"C: row{args.rows} col{args.cols} stud CENTRE", f"D: row{args.rows} col1 stud CENTRE"])
        if not cv2.isContourConvex(np.array(pixels, dtype=np.float32).reshape(-1, 1, 2)):
            raise ValueError("A-B-C-D must form a convex quadrilateral in that order")
    c = fit_calibration(pixels, board, size, args.rows, args.cols, p, intrinsics, args.max_error_mm)
    if args.robot_points:
        robot = read_json(args.robot_points)
        c["robot"] = fit_robot_frame(robot["board_xy_mm"], robot["base_xyz_mm"],
                                     args.max_error_mm, robot.get("normal_sign"))
    c["view_id"] = args.view_id
    c["coordinate_convention"] = {
        "origin": "A: red-marked corner stud centre",
        "positive_x": "A to B along the physical +X marking; increasing column index",
        "positive_y": "A to D along the physical +Y marking; increasing row index",
        "index_base": 1,
        "note": "Orientation is established by reference point identities, not image screen position"}
    c["source_image"] = str(Path(args.image).resolve())
    c["baseline_file"] = "empty.png"
    if args.markers:
        c["marker_layout"] = read_json(args.markers)
    write_json(out / "calibration.json", c)
    save_image(out / "empty.png", image)
    save_image(out / "grid_overlay.png", draw_grid(c, image))
    export_grid(c, out / "stud_coordinates.csv")
    print(f"Saved {args.rows * args.cols} stud coordinates to {out / 'stud_coordinates.csv'}")
    print(f"Fit max error: {c['max_fit_error_mm']:.4f} mm (training fit, NOT independent accuracy)")
    print("Next: verify with independent points. All results remain provisional until physical validation.")


def validate_view(calibration, image, max_error_mm):
    """Marker-based camera/board movement guard, when a layout is configured."""
    check_image_size(calibration, image)
    if "marker_layout" not in calibration:
        return {"status": "unmonitored", "note": "Confirm the recorded wrist view before using coordinates"}
    pixels, board = aruco_references(image, calibration["marker_layout"])
    errors = np.linalg.norm(pixel_to_board(calibration, pixels) - board, axis=1)
    if errors.max() > max_error_mm:
        raise ValueError(f"Reference markers shifted: max {errors.max():.3f} mm. Restore view or recalibrate.")
    return {"status": "marker_checked", "max_error_mm": float(errors.max())}


def query(args):
    c = read_json(args.calibration)
    image = read_image(args.image)
    guard = validate_view(c, image, args.max_error_mm)
    pixels = args.pixel
    if not pixels:
        pixels = click_points(image, ["object TOP surface point"])
    pts = points_array(pixels, 2)
    if np.any(pts < 0) or np.any(pts >= c["image_size"]):
        raise ValueError("Query pixels are outside image")
    xy = pixel_to_board(c, pts, args.surface_height_mm)
    results = [{"pixel_xy": pixel, **describe_point(c, point, args.surface_height_mm)}
               for pixel, point in zip(pts.tolist(), xy)]
    payload = {"view_check": guard, "independently_validated": c["independently_validated"], "points": results}
    write_json(args.out, payload)
    print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))


def verify(args):
    c = read_json(args.calibration)
    refs = read_json(args.points)
    if "image_size" in refs and refs["image_size"] != c["image_size"]:
        raise ValueError("Verification reference image resolution differs from calibration")
    pixels = points_array(refs["pixel_xy"], 2, 5)
    board = points_array(refs["board_xy_mm"], 2, 5)
    if len(pixels) != len(board):
        raise ValueError("Verification point counts differ")
    if np.any(pixels < 0) or np.any(pixels >= c["image_size"]):
        raise ValueError("Verification pixels outside image")
    # Held-out measurements must not reuse calibration references.
    trained = np.asarray(c["reference_board_xy_mm"])
    if np.any(np.linalg.norm(board[:, None] - trained[None], axis=2).min(axis=1) < 0.01):
        raise ValueError("Verification points must be separate from calibration reference points")
    span = np.array([c["cols"] - 1, c["rows"] - 1]) * c["pitch_mm"]
    if np.any(np.ptp(board, axis=0) < span * 0.5):
        raise ValueError("Validation points must span at least half the board in X and Y")
    height = float(refs.get("surface_height_mm", 0))
    errors = np.linalg.norm(pixel_to_board(c, pixels, height) - board, axis=1)
    report = {"source": str(Path(args.points).resolve()), "surface_height_mm": height,
              "count": len(errors), "errors_mm": errors.tolist(), "max_error_mm": float(errors.max()),
              "rmse_mm": float(np.sqrt(np.mean(errors ** 2))), "threshold_mm": args.max_error_mm,
              "passed": bool(errors.max() <= args.max_error_mm)}
    write_json(args.out, report)
    # Store every outcome, so a later failed check invalidates an earlier pass.
    c["independently_validated"] = report["passed"]
    c["last_validation"] = report
    write_json(args.calibration, c)
    print(__import__("json").dumps(report, indent=2))
    if not report["passed"]:
        raise ValueError("Independent validation failed; inspect references, distortion, view and height")


def detect_candidates(c, empty, frame, surface_height_mm=0, threshold=35,
                      min_area_mm2=20, blur_size=5, close_size=5,
                      mode="hybrid", green_hue=(35, 90), green_sat_min=45):
    """Baseline difference produces candidate regions, not guaranteed block instances."""
    check_image_size(c, empty)
    check_image_size(c, frame)
    if not 0 < threshold <= 255 or min_area_mm2 <= 0:
        raise ValueError("Invalid detection threshold/area")
    for size in (blur_size, close_size):
        if size < 1 or size % 2 != 1:
            raise ValueError("Blur/morphology sizes must be positive odd integers")
    if mode not in ("difference", "hybrid") or not 0 <= green_hue[0] < green_hue[1] <= 179:
        raise ValueError("Invalid detector mode or OpenCV HSV green hue interval")
    if not 0 <= green_sat_min <= 255:
        raise ValueError("Invalid green saturation threshold")
    p, rows, cols = c["pitch_mm"], c["rows"], c["cols"]
    # Curved distorted edges are sampled, rather than approximated by four corners.
    limits = [-p / 2, (cols - 0.5) * p, (rows - 0.5) * p]
    left, right, bottom = limits
    edges = (np.c_[np.linspace(left, right, 50), np.full(50, left)],
             np.c_[np.full(50, right), np.linspace(left, bottom, 50)],
             np.c_[np.linspace(right, left, 50), np.full(50, bottom)],
             np.c_[np.full(50, left), np.linspace(bottom, left, 50)])
    uv = np.rint(board_to_pixels(c, np.vstack(edges))).astype(np.int32)
    roi = np.zeros(frame.shape[:2], np.uint8)
    cv2.fillPoly(roi, [uv], 255)
    a = cv2.GaussianBlur(empty, (blur_size, blur_size), 0)
    b = cv2.GaussianBlur(frame, (blur_size, blur_size), 0)
    score = np.max(cv2.absdiff(a, b), axis=2)
    mask = np.where((score >= threshold) & (roi > 0), 255, 0).astype(np.uint8)
    if mode == "hybrid":
        hsv = cv2.cvtColor(b, cv2.COLOR_BGR2HSV)
        green = ((hsv[:, :, 0] >= green_hue[0]) & (hsv[:, :, 0] <= green_hue[1])
                 & (hsv[:, :, 1] >= green_sat_min))
        mask[green] = 0
    kernel = np.ones((close_size, close_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask[roi == 0] = 0
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
    results = []
    overlay = frame.copy()
    for contour in contours:
        if len(contour) < 3:
            continue
        mapped = pixel_to_board(c, contour.reshape(-1, 2), surface_height_mm).astype(np.float32)
        moments = cv2.moments(mapped.reshape(-1, 1, 2))
        if moments["m00"] < min_area_mm2:
            continue
        xy = [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]]
        info = describe_point(c, xy, surface_height_mm)
        if not info["inside_board"]:
            continue
        pixel = board_to_pixels(c, [xy], surface_height_mm)[0]
        candidate_id = len(results) + 1
        results.append({"candidate_id": candidate_id, "pixel_xy": pixel.tolist(),
                        "area_mm2": moments["m00"], **info})
        cv2.drawContours(overlay, [contour], -1, (0, 0, 255), 2)
        pt = tuple(np.rint(pixel).astype(int))
        cv2.circle(overlay, pt, 4, (255, 255, 255), -1)
        cv2.putText(overlay, f"{candidate_id}: r{info['row_continuous']:.2f} c{info['col_continuous']:.2f}",
                    pt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    return results, overlay, mask, float(np.count_nonzero(mask) / max(1, np.count_nonzero(roi)))


def detect(args):
    c = read_json(args.calibration)
    frame = read_image(args.image)
    guard = validate_view(c, frame, args.max_error_mm)
    baseline = Path(args.calibration).parent / c["baseline_file"]
    result, overlay, mask, changed = detect_candidates(c, read_image(baseline), frame,
                                                      args.surface_height_mm, args.threshold,
                                                      args.min_area_mm2, args.blur_size, args.close_size,
                                                      args.mode, args.green_hue, args.green_sat_min)
    payload = {"view_check": guard, "independently_validated": c["independently_validated"],
               "status": "scene_changed_too_much" if changed > 0.5 else "candidates_require_inspection",
               "changed_fraction": changed, "detector_mode": args.mode,
               "note": "Reflections, shadows, hands and connected blocks can give false or merged candidates. No occupancy inferred.",
               "candidates": result}
    out = Path(args.out)
    write_json(out / "candidates.json", payload)
    save_image(out / "overlay.png", overlay)
    save_image(out / "mask.png", mask)
    print(f"Saved {len(result)} candidates to {out}; changed_fraction={changed:.3f}")


def capture(args):
    if args.width is not None and args.width <= 0 or args.height is not None and args.height <= 0:
        raise ValueError("Capture size must be positive")
    cap = cv2.VideoCapture(args.device)
    if args.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    if args.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        raise ValueError("Cannot open camera device")
    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok:
                raise ValueError("Cannot acquire camera image")
            cv2.imshow("Capture: S save; ESC cancel", frame)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("s"), ord("S")):
                save_image(args.out, frame)
                print(f"Saved {frame.shape[1]}x{frame.shape[0]} image: {args.out}")
                return
            if key == 27:
                raise ValueError("Capture cancelled")
        raise ValueError("Capture timed out")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def make_markers(args):
    if not hasattr(cv2, "aruco"):
        raise ValueError("OpenCV ArUco module unavailable")
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if args.pixels < 100:
        raise ValueError("Marker size must be at least 100 pixels")
    for marker_id in range(4):
        if hasattr(cv2.aruco, "generateImageMarker"):
            marker = cv2.aruco.generateImageMarker(dictionary, marker_id, args.pixels)
        else:
            marker = cv2.aruco.drawMarker(dictionary, marker_id, args.pixels)
        pad = args.pixels // 4
        save_image(Path(args.out) / f"DICT_4X4_50_id{marker_id}.png",
                   cv2.copyMakeBorder(marker, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255))
    print("Print without scaling distortion. Measure the black square, excluding white border.")


def collect_points(args):
    if not np.isfinite(args.pitch_mm) or args.pitch_mm <= 0:
        raise ValueError("Pitch must be positive and finite")
    if not np.isfinite(args.surface_height_mm) or args.surface_height_mm < 0:
        raise ValueError("Height must be nonnegative and finite")
    image = read_image(args.image)
    studs = points_array(args.stud, 2)
    index_base = args.index_base
    if np.any(studs < index_base) or np.any(studs > np.array([args.rows, args.cols]) - 1 + index_base):
        raise ValueError("Stud row/column are outside board")
    labels = [f"row={row:g} col={col:g} CENTRE | From A: +Y {row - index_base:g} gaps, +X {col - index_base:g} gaps"
              for row, col in studs]
    context = f"A origin = row {index_base}, col {index_base}. ROW follows physical +Y; COL follows physical +X."
    print(context)
    for index, label in enumerate(labels, 1):
        print(f"{index}. {label}")
    pixels = click_points(image, labels, context=context)
    xy = [[(col - index_base) * args.pitch_mm, (row - index_base) * args.pitch_mm] for row, col in studs]
    write_json(args.out, {"pixel_xy": pixels, "board_xy_mm": xy,
                          "input_index_base": index_base,
                          "surface_height_mm": args.surface_height_mm,
                          "image_size": [image.shape[1], image.shape[0]],
                          "source_image": str(Path(args.image).resolve()),
                          "note": "Physically identify stud/centre positions; do not derive reference pixels from the predicted grid"})
    print(f"Saved {len(pixels)} measured reference points to {args.out}")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("capture", help="Capture a raw USB image (no robot movement)")
    a.add_argument("--device", type=int, default=0)
    a.add_argument("--width", type=int)
    a.add_argument("--height", type=int)
    a.add_argument("--timeout", type=float, default=120)
    a.add_argument("--out", required=True)
    a.set_defaults(func=capture)
    a = sub.add_parser("calibrate", help="Generate fixed-view board mapping and stud CSV")
    a.add_argument("--image", required=True, help="Empty board image")
    a.add_argument("--out", required=True, help="New empty run directory")
    a.add_argument("--pitch-mm", type=float, required=True, help="Measured stud centre spacing, not stud diameter")
    a.add_argument("--rows", type=int, default=24)
    a.add_argument("--cols", type=int, default=24)
    a.add_argument("--view-id", default="fixed_wrist_view")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--points", help="JSON pixel_xy and board_xy_mm; otherwise click four stud centres")
    g.add_argument("--markers", help="Measured coplanar ArUco marker layout JSON")
    a.add_argument("--intrinsics", help="JSON pinhole camera matrix and distortion")
    a.add_argument("--robot-points", help="Optional measured board/robot XYZ JSON")
    a.add_argument("--max-error-mm", type=float, default=2.0,
                   help="Provisional error limit in mm (default: 2.0); not a device accuracy guarantee")
    a.set_defaults(func=calibrate)
    for name, func in (("query", query), ("detect", detect), ("verify", verify)):
        a = sub.add_parser(name)
        a.add_argument("--calibration", required=True)
        a.add_argument("--out", required=True)
        a.add_argument("--max-error-mm", type=float, default=2.0,
                       help="Provisional error limit in mm (default: 2.0); not a device accuracy guarantee")
        if name == "verify":
            a.add_argument("--points", required=True)
        else:
            a.add_argument("--image", required=True)
            a.add_argument("--surface-height-mm", type=float, default=0)
        if name == "query":
            a.add_argument("--pixel", type=float, nargs=2, action="append", metavar=("U", "V"))
        if name == "detect":
            a.add_argument("--mode", choices=("hybrid", "difference"), default="hybrid")
            a.add_argument("--green-hue", type=int, nargs=2, default=[35, 90], metavar=("MIN", "MAX"))
            a.add_argument("--green-sat-min", type=int, default=45)
            a.add_argument("--threshold", type=int, default=35)
            a.add_argument("--min-area-mm2", type=float, default=20)
            a.add_argument("--blur-size", type=int, default=5)
            a.add_argument("--close-size", type=int, default=5)
        a.set_defaults(func=func)
    a = sub.add_parser("make-markers")
    a.add_argument("--out", required=True)
    a.add_argument("--pixels", type=int, default=400)
    a.set_defaults(func=make_markers)
    a = sub.add_parser("collect-points", help="Click independently identified stud centres for calibration/validation JSON")
    a.add_argument("--image", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--pitch-mm", type=float, required=True)
    a.add_argument("--rows", type=int, default=24)
    a.add_argument("--cols", type=int, default=24)
    a.add_argument("--stud", type=float, nargs=2, action="append", required=True, metavar=("ROW", "COL"))
    a.add_argument("--index-base", type=int, choices=(0, 1), default=1,
                   help="Use 0 when the origin stud is numbered (0,0); default is (1,1)")
    a.add_argument("--surface-height-mm", type=float, default=0)
    a.set_defaults(func=collect_points)
    return p


def main():
    args = parser().parse_args()
    try:
        if hasattr(args, "max_error_mm") and (not np.isfinite(args.max_error_mm) or args.max_error_mm <= 0):
            raise ValueError("Error threshold must be finite and positive")
        args.func(args)
    except (ValueError, KeyError, OSError, cv2.error) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
