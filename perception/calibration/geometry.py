"""Fixed-camera LEGO grid geometry. All physical lengths are millimetres.

No robot drivers or motion commands are imported by this module.
"""
import csv
import json
from pathlib import Path

import cv2
import numpy as np


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False,
                                   allow_nan=False) + "\n", encoding="utf-8")


def points_array(value, dimensions, minimum=1):
    a = np.asarray(value, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != dimensions or len(a) < minimum:
        raise ValueError(f"Expected at least {minimum} points with {dimensions} values each")
    if not np.isfinite(a).all():
        raise ValueError("Coordinates must be finite")
    return a


def perspective(points, matrix):
    a = points_array(points, 2)
    m = np.asarray(matrix, dtype=np.float64)
    q = np.c_[a, np.ones(len(a))] @ m.T
    if np.any(np.abs(q[:, 2]) < 1e-10):
        raise ValueError("Point lies on projective horizon")
    return q[:, :2] / q[:, 2:3]


def load_intrinsics(path, image_size):
    if path is None:
        return None
    d = read_json(path)
    if list(d["image_size"]) != list(image_size):
        raise ValueError("Camera intrinsics resolution differs from image resolution")
    if d.get("distortion_model", "plumb_bob") not in ("plumb_bob", "rational_polynomial", "none"):
        raise ValueError("Unsupported distortion model (fisheye/equidistant must be converted first)")
    k = np.asarray(d["camera_matrix"], dtype=float)
    dist = np.asarray(d["dist_coeffs"], dtype=float).reshape(-1)
    if k.shape != (3, 3) or not np.isfinite(k).all() or not np.isfinite(dist).all():
        raise ValueError("Invalid camera matrix/distortion coefficients")
    if k[0, 0] <= 0 or k[1, 1] <= 0 or not np.allclose(k[2], [0, 0, 1]):
        raise ValueError("Invalid camera focal lengths or homogeneous row")
    if abs(k[0, 1]) > 1e-8 or abs(k[1, 0]) > 1e-8 or dist.size not in (0, 4, 5, 8, 12, 14):
        raise ValueError("Expected OpenCV pinhole intrinsics with zero skew")
    return {"image_size": list(image_size), "camera_matrix": k.tolist(),
            "dist_coeffs": dist.tolist(), "distortion_model": d.get("distortion_model", "plumb_bob")}


def undistort_pixels(points, intrinsics):
    pts = points_array(points, 2)
    if intrinsics is None:
        return pts
    k = np.asarray(intrinsics["camera_matrix"], dtype=float)
    d = np.asarray(intrinsics["dist_coeffs"], dtype=float)
    return cv2.undistortPoints(pts.reshape(-1, 1, 2), k, d, P=k).reshape(-1, 2)


def fit_robot_frame(board_xy, base_xyz, max_error_mm=1.5, normal_sign=None):
    """Rigid point registration; translation, rotation, no scale or shear.

    normal_sign sets the physical upward normal relative to cross(X,Y).
    If omitted choose the normal with positive robot base Z (horizontal board).
    """
    xy = points_array(board_xy, 2, 3)
    xyz = points_array(base_xyz, 3, 3)
    if len(xy) != len(xyz):
        raise ValueError("Robot point counts differ")
    src = np.c_[xy, np.zeros(len(xy))]
    a, b = src - src.mean(0), xyz - xyz.mean(0)
    for values in (a, b):
        s = np.linalg.svd(values, compute_uv=False)
        if s[1] < 1e-6 or s[1] / s[0] < 0.05:
            raise ValueError("Robot reference points must be well spread and non-collinear")
    u, _, vt = np.linalg.svd(a.T @ b)
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(vt.T @ u.T)
    r = vt.T @ correction @ u.T
    t = xyz.mean(0) - r @ src.mean(0)
    residual = np.linalg.norm(src @ r.T + t - xyz, axis=1)
    if residual.max() > max_error_mm:
        raise ValueError(f"Robot registration max error {residual.max():.3f} mm exceeds {max_error_mm}")
    if normal_sign is None:
        if abs(r[2, 2]) < 0.5:
            raise ValueError("Board is steeply tilted: explicitly specify robot normal_sign (+1 or -1)")
        normal_sign = 1 if r[2, 2] > 0 else -1
    if normal_sign not in (-1, 1):
        raise ValueError("normal_sign must be +1 or -1")
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = r, t
    return {"T_base_from_board": transform.tolist(), "height_normal_sign": normal_sign,
            "fit_errors_mm": residual.tolist(), "max_error_mm": float(residual.max()),
            "note": "Robot XYZ is a measured geometric point, not a TCP motion target"}


def fit_calibration(pixel_xy, board_xy, image_size, rows=24, cols=24,
                    pitch_mm=8.0, intrinsics=None, max_error_mm=2.0):
    pixels = points_array(pixel_xy, 2, 4)
    board = points_array(board_xy, 2, 4)
    if len(pixels) != len(board):
        raise ValueError("Image and board point counts differ")
    if rows < 2 or cols < 2 or pitch_mm <= 0 or not np.isfinite(pitch_mm):
        raise ValueError("Grid dimensions/pitch are invalid")
    if max_error_mm <= 0 or not np.isfinite(max_error_mm):
        raise ValueError("Error threshold must be positive and finite")
    width, height = image_size
    if np.any(pixels < 0) or np.any(pixels >= [width, height]):
        raise ValueError("Reference pixels are outside the image")
    span = np.array([cols - 1, rows - 1]) * pitch_mm
    if np.any(np.ptp(board, axis=0) < span * 0.5):
        raise ValueError("Reference points must span at least half the grid in both axes")
    hull_area = cv2.contourArea(cv2.convexHull(board.astype(np.float32)))
    if hull_area < np.prod(span) * 0.25:
        raise ValueError("Reference points are too narrow or collinear")
    undistorted = undistort_pixels(pixels, intrinsics)
    # Fit all supplied points: never silently accept RANSAC outliers with wrong identities.
    h, _ = cv2.findHomography(undistorted, board, method=0)
    if h is None or not np.isfinite(h).all() or np.linalg.matrix_rank(h) < 3:
        raise ValueError("Cannot fit a non-singular homography")
    errors = np.linalg.norm(perspective(undistorted, h) - board, axis=1)
    if errors.max() > max_error_mm:
        raise ValueError(f"Calibration max fit error {errors.max():.3f} mm exceeds {max_error_mm}")
    corners = np.array([[0, 0], [span[0], 0], span, [0, span[1]]])
    denominator = (np.c_[corners, np.ones(4)] @ np.linalg.inv(h).T)[:, 2]
    if np.min(denominator) * np.max(denominator) <= 0:
        raise ValueError("Grid crosses projective horizon; check reference order")
    result = {"schema_version": 1, "image_size": list(image_size), "rows": rows,
              "cols": cols, "pitch_mm": float(pitch_mm),
              "origin": "stud(row=1,col=1) centre; X increasing columns, Y increasing rows",
              "reference_plane": "plane through reference points, normally empty stud tops",
              "H_board_from_undistorted_pixel": h.tolist(), "intrinsics": intrinsics,
              "reference_pixels": pixels.tolist(), "reference_board_xy_mm": board.tolist(),
              "fit_errors_mm": errors.tolist(), "max_fit_error_mm": float(errors.max()),
              "independently_validated": False, "robot": None, "camera_pose": None}
    if intrinsics is not None:
        objects = np.c_[board, np.zeros(len(board))]
        k = np.asarray(intrinsics["camera_matrix"], dtype=float)
        d = np.asarray(intrinsics["dist_coeffs"], dtype=float)
        ok, rvec, tvec = cv2.solvePnP(objects, pixels, k, d, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            raise ValueError("Camera pose estimation failed")
        r = cv2.Rodrigues(rvec)[0]
        camera_z = (-r.T @ tvec).ravel()[2]
        if abs(camera_z) < 1e-6 or np.min((objects @ r.T + tvec.ravel())[:, 2]) <= 0:
            raise ValueError("Invalid camera pose")
        projection = cv2.projectPoints(objects, rvec, tvec, k, d)[0].reshape(-1, 2)
        pose_errors = np.linalg.norm(projection - pixels, axis=1)
        pose_error_mm = np.linalg.norm(perspective(undistort_pixels(projection, intrinsics), h) - board, axis=1)
        if pose_error_mm.max() > max_error_mm:
            raise ValueError("Metric PnP pose disagrees with references; check intrinsics, pitch, plane")
        result["camera_pose"] = {"R_camera_from_board": r.tolist(), "t_camera_from_board_mm": tvec.ravel().tolist(),
                                 "height_normal_sign": 1 if camera_z > 0 else -1,
                                 "reprojection_errors_px": pose_errors.tolist()}
    return result


def pixel_to_board(calibration, pixels, surface_height_mm=0.0):
    pts = points_array(pixels, 2)
    if surface_height_mm < 0 or not np.isfinite(surface_height_mm):
        raise ValueError("Surface height must be finite and nonnegative")
    uv = undistort_pixels(pts, calibration["intrinsics"])
    if surface_height_mm == 0:
        return perspective(uv, calibration["H_board_from_undistorted_pixel"])
    pose = calibration["camera_pose"]
    if pose is None:
        raise ValueError("Height correction requires camera intrinsics and calibrated PnP pose")
    r = np.asarray(pose["R_camera_from_board"], dtype=float)
    t = np.asarray(pose["t_camera_from_board_mm"], dtype=float)
    k = np.asarray(calibration["intrinsics"]["camera_matrix"], dtype=float)
    centre = -r.T @ t
    z = pose["height_normal_sign"] * surface_height_mm
    if surface_height_mm >= abs(centre[2]):
        raise ValueError("Surface is at or above the camera's height above the board")
    rays = (np.c_[uv, np.ones(len(uv))] @ np.linalg.inv(k).T) @ r
    if np.any(np.abs(rays[:, 2]) < 1e-9):
        raise ValueError("Camera ray is parallel to surface plane")
    scale = (z - centre[2]) / rays[:, 2]
    if np.any(scale <= 0):
        raise ValueError("Surface intersection is behind camera")
    return (centre + scale[:, None] * rays)[:, :2]


def board_to_pixels(calibration, xy, surface_height_mm=0.0):
    xy = points_array(xy, 2)
    pose, intr = calibration["camera_pose"], calibration["intrinsics"]
    if surface_height_mm < 0 or not np.isfinite(surface_height_mm):
        raise ValueError("Invalid surface height")
    if pose is not None:
        r = np.asarray(pose["R_camera_from_board"], dtype=float)
        t = np.asarray(pose["t_camera_from_board_mm"], dtype=float)
        centre = -r.T @ t
        if surface_height_mm >= abs(centre[2]):
            raise ValueError("Surface is above camera height")
        z = pose["height_normal_sign"] * surface_height_mm
        xyz = np.c_[xy, np.full(len(xy), z)]
        if np.min((xyz @ r.T + t)[:, 2]) <= 0:
            raise ValueError("Projected point is behind camera")
        return cv2.projectPoints(xyz, cv2.Rodrigues(r)[0], t,
                                 np.asarray(intr["camera_matrix"], dtype=float),
                                 np.asarray(intr["dist_coeffs"], dtype=float))[0].reshape(-1, 2)
    if surface_height_mm != 0:
        raise ValueError("Height correction requires intrinsics")
    return perspective(xy, np.linalg.inv(calibration["H_board_from_undistorted_pixel"]))


def board_to_robot(calibration, xy, surface_height_mm=0):
    robot = calibration["robot"]
    if robot is None:
        return None
    if surface_height_mm < 0 or not np.isfinite(surface_height_mm):
        raise ValueError("Invalid surface height")
    xy = points_array(xy, 2)
    xyz = np.c_[xy, np.full(len(xy), robot["height_normal_sign"] * surface_height_mm), np.ones(len(xy))]
    return (xyz @ np.asarray(robot["T_base_from_board"]).T)[:, :3]


def describe_point(calibration, xy, surface_height_mm=0):
    x, y = map(float, xy)
    p, rows, cols = calibration["pitch_mm"], calibration["rows"], calibration["cols"]
    inside = -p / 2 <= x < (cols - 0.5) * p and -p / 2 <= y < (rows - 0.5) * p
    col, row = x / p + 1, y / p + 1
    nearest = None
    if inside:
        nearest = {"row": min(rows, max(1, int(np.floor(row + 0.5)))),
                   "col": min(cols, max(1, int(np.floor(col + 0.5))))}
    robot_xyz = board_to_robot(calibration, [[x, y]], surface_height_mm)
    return {"board_xy_mm": [x, y], "row_continuous": row, "col_continuous": col,
            "inside_board": inside, "nearest_stud": nearest,
            "surface_height_mm": float(surface_height_mm),
            "robot_xyz_mm": None if robot_xyz is None else robot_xyz[0].tolist(),
            "coordinate_kind": "reference_plane_projection" if surface_height_mm == 0 else "known_height_surface"}


def export_grid(calibration, path):
    p = calibration["pitch_mm"]
    indices = [(row, col) for row in range(1, calibration["rows"] + 1)
               for col in range(1, calibration["cols"] + 1)]
    xy = np.array([[(col - 1) * p, (row - 1) * p] for row, col in indices])
    pixels, base = board_to_pixels(calibration, xy), board_to_robot(calibration, xy)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["row", "col", "x_mm", "y_mm", "u_px", "v_px", "base_x_mm", "base_y_mm", "base_z_mm"])
        for i, (row, col) in enumerate(indices):
            writer.writerow([row, col, *xy[i], *pixels[i], *(base[i] if base is not None else ["", "", ""])])


def check_image_size(calibration, image):
    if [image.shape[1], image.shape[0]] != calibration["image_size"]:
        raise ValueError("Image resolution differs from calibration; recalibrate instead of resizing")
