"""Synthetic geometric and integration checks; these do not certify real accuracy."""
import csv
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geometry import (board_to_pixels, board_to_robot, describe_point, export_grid,
                      fit_calibration, fit_robot_frame, load_intrinsics, perspective,
                      pixel_to_board, write_json)
from lego_grid import aruco_references, detect_candidates, validate_view


BOARD = np.array([[0, 0], [368, 0], [368, 368], [0, 368]], dtype=float)
PIXELS = np.array([[100, 100], [850, 120], [790, 830], [150, 850]], dtype=float)


def simple():
    return fit_calibration(PIXELS, BOARD, [1000, 1000], pitch_mm=16)


def metric():
    k = np.array([[900., 0, 640], [0, 910., 480], [0, 0, 1]])
    d = np.array([-0.09, 0.01, 0.001, -0.002, 0.])
    rvec = np.array([0.2, -0.15, 0.05])
    tvec = np.array([-190., -210., 850.])
    board = np.vstack([BOARD, [[80, 80], [280, 280], [100, 280], [280, 100]]])
    objects = np.c_[board, np.zeros(len(board))]
    pixels = cv2.projectPoints(objects, rvec, tvec, k, d)[0].reshape(-1, 2)
    intr = {"image_size": [1280, 960], "camera_matrix": k.tolist(), "dist_coeffs": d.tolist()}
    c = fit_calibration(pixels, board, [1280, 960], pitch_mm=16, intrinsics=intr)
    return c, k, d, rvec, tvec


def test_homography_grid_roundtrip_and_576_csv(tmp_path):
    c = simple()
    xy = np.array([[16 * col, 16 * row] for row in range(24) for col in range(24)])
    np.testing.assert_allclose(pixel_to_board(c, board_to_pixels(c, xy)), xy, atol=1e-8)
    export_grid(c, tmp_path / "studs.csv")
    with (tmp_path / "studs.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 576
    assert float(rows[-1]["x_mm"]) == float(rows[-1]["y_mm"]) == 368
    assert rows[-1]["base_x_mm"] == ""


def test_block_centre_is_fractional_not_false_stud():
    d = describe_point(simple(), [8, 8])
    assert d["row_continuous"] == d["col_continuous"] == 1.5
    assert d["robot_xyz_mm"] is None
    assert not describe_point(simple(), [-9, 0])["inside_board"]
    assert describe_point(simple(), [-7.9, 0])["nearest_stud"] == {"row": 1, "col": 1}


def test_unknown_height_rejected_without_intrinsics():
    with pytest.raises(ValueError, match="intrinsics"):
        pixel_to_board(simple(), [[500, 500]], 20)


def test_lens_distortion_and_tilted_known_height_recovered():
    c, k, d, rvec, tvec = metric()
    xy = np.array([[50., 40.], [190., 220.], [340., 300.]])
    # The reference board normal points away from an overhead camera, so top has negative board Z.
    pixels = cv2.projectPoints(np.c_[xy, np.full(3, -32.)], rvec, tvec, k, d)[0].reshape(-1, 2)
    recovered = pixel_to_board(c, pixels, 32)
    np.testing.assert_allclose(recovered, xy, atol=0.01)
    assert np.max(np.linalg.norm(pixel_to_board(c, pixels) - xy, axis=1)) > 4
    np.testing.assert_allclose(board_to_pixels(c, xy, 32), pixels, atol=0.01)


@pytest.mark.parametrize("height", [-1, float("nan"), 1000])
def test_invalid_heights_rejected(height):
    c = metric()[0]
    with pytest.raises(ValueError):
        pixel_to_board(c, [[640, 480]], height)


def test_robot_registration_tilt_and_height(tmp_path):
    c = simple()
    r = cv2.Rodrigues(np.array([0.1, 0.2, -0.3]))[0]
    t = np.array([300, -200, 50])
    base = np.c_[BOARD, np.zeros(4)] @ r.T + t
    c["robot"] = fit_robot_frame(BOARD, base)
    np.testing.assert_allclose(board_to_robot(c, [[80, 112]], 32)[0],
                               r @ [80, 112, 32] + t, atol=1e-8)
    export_grid(c, tmp_path / "robot_grid.csv")
    assert (tmp_path / "robot_grid.csv").read_text().count("\n") == 577


def test_robot_normal_can_be_opposite_xy_cross():
    c = simple()
    r = np.diag([1., -1., -1.])
    base = np.c_[BOARD, np.zeros(4)] @ r.T + [0, 400, 20]
    c["robot"] = fit_robot_frame(BOARD, base)
    assert c["robot"]["height_normal_sign"] == -1
    np.testing.assert_allclose(board_to_robot(c, [[0, 0]], 30)[0], [0, 400, 50])


def test_robot_registration_rejects_wrong_scale_and_collinear():
    with pytest.raises(ValueError, match="registration"):
        fit_robot_frame(BOARD, np.c_[BOARD * 2, np.zeros(4)])
    with pytest.raises(ValueError, match="collinear"):
        fit_robot_frame([[0, 0], [16, 0], [32, 0]], [[0, 0, 0], [16, 0, 0], [32, 0, 0]])


def test_intrinsics_resolution_and_model_validation(tmp_path):
    path = tmp_path / "camera.json"
    intr = metric()[0]["intrinsics"]
    write_json(path, intr)
    with pytest.raises(ValueError, match="resolution"):
        load_intrinsics(path, [640, 480])
    intr["distortion_model"] = "equidistant"
    write_json(path, intr)
    with pytest.raises(ValueError, match="Unsupported"):
        load_intrinsics(path, [1280, 960])


def test_calibration_rejects_bad_correspondences_and_poor_spread():
    wrong = np.vstack([BOARD, [184, 184]])
    with pytest.raises(ValueError, match="fit error"):
        fit_calibration(np.vstack([PIXELS, [400, 200]]), wrong, [1000, 1000], pitch_mm=16)
    with pytest.raises(ValueError, match="span"):
        fit_calibration(PIXELS, BOARD / 10, [1000, 1000], pitch_mm=16)


def test_detection_non_green_block_and_stationary_red_reference():
    c = simple()
    empty = np.full((1000, 1000, 3), [30, 150, 30], dtype=np.uint8)
    cv2.circle(empty, (180, 180), 20, (0, 0, 200), -1)
    frame = empty.copy()
    # Known physical rectangle centre is exactly [104, 136] mm.
    polygon = np.rint(board_to_pixels(c, [[80, 112], [128, 112], [128, 160], [80, 160]])).astype(np.int32)
    cv2.fillPoly(frame, [polygon], (0, 0, 230))
    result, _, _, changed = detect_candidates(c, empty, frame)
    assert len(result) == 1
    np.testing.assert_allclose(result[0]["board_xy_mm"], [104, 136], atol=1)
    assert changed < 0.1
    assert not detect_candidates(c, empty, empty)[0]
    with pytest.raises(ValueError, match="resolution"):
        detect_candidates(c, empty, frame[:500])


def test_hybrid_suppresses_green_brightness_change():
    c = simple()
    empty = np.full((1000, 1000, 3), [0, 120, 0], dtype=np.uint8)
    frame = np.full((1000, 1000, 3), [0, 190, 0], dtype=np.uint8)
    assert not detect_candidates(c, empty, frame, mode="hybrid")[0]
    assert detect_candidates(c, empty, frame, mode="difference")[0]


def marker_fixture():
    if not hasattr(cv2, "aruco"):
        pytest.skip("ArUco unavailable")
    image = np.full((1000, 1000, 3), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    markers = []
    for i, (x, y) in enumerate([(120, 120), (760, 120), (760, 760), (120, 760)]):
        if hasattr(cv2.aruco, "generateImageMarker"):
            marker = cv2.aruco.generateImageMarker(dictionary, i, 120)
        else:
            marker = cv2.aruco.drawMarker(dictionary, i, 120)
        image[y:y + 120, x:x + 120] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        xy = np.array([[x, y], [x + 119, y], [x + 119, y + 119], [x, y + 119]]) * 0.5 - 60
        markers.append({"id": i, "corners_board_xy_mm": xy.tolist()})
    return image, {"dictionary": "DICT_4X4_50", "markers": markers}


def test_marker_detection_and_camera_motion_guard():
    image, layout = marker_fixture()
    uv, xy = aruco_references(image, layout)
    c = fit_calibration(uv, xy, [1000, 1000], pitch_mm=16)
    c["marker_layout"] = layout
    assert validate_view(c, image, 1.5)["status"] == "marker_checked"
    shifted = cv2.warpAffine(image, np.array([[1., 0., 12.], [0., 1., 0.]]), (1000, 1000), borderValue=(255, 255, 255))
    with pytest.raises(ValueError, match="shifted"):
        validate_view(c, shifted, 1.5)
    missing = image.copy()
    missing[100:260, 100:260] = 255
    with pytest.raises(ValueError, match="not visible"):
        validate_view(c, missing, 1.5)


def run_cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "lego_grid.py"), *map(str, args)], capture_output=True, text=True)


def test_cli_calibrate_verify_query_detection(tmp_path):
    empty = np.full((1000, 1000, 3), [20, 140, 20], dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "empty.png"), empty)
    write_json(tmp_path / "reference.json", {"pixel_xy": PIXELS.tolist(), "board_xy_mm": BOARD.tolist()})
    run = tmp_path / "run"
    result = run_cli("calibrate", "--image", tmp_path / "empty.png", "--points", tmp_path / "reference.json",
                     "--pitch-mm", 16, "--out", run)
    assert result.returncode == 0, result.stderr
    assert (run / "stud_coordinates.csv").exists()
    assert run_cli("calibrate", "--image", tmp_path / "empty.png", "--points", tmp_path / "reference.json",
                   "--pitch-mm", 16, "--out", run).returncode != 0
    c = __import__("json").loads((run / "calibration.json").read_text())
    xy = [[32, 32], [336, 32], [184, 184], [32, 336], [336, 336]]
    write_json(tmp_path / "heldout.json", {"pixel_xy": board_to_pixels(c, xy).tolist(), "board_xy_mm": xy})
    result = run_cli("verify", "--calibration", run / "calibration.json", "--points", tmp_path / "heldout.json",
                     "--out", tmp_path / "validation.json")
    assert result.returncode == 0, result.stderr
    result = run_cli("query", "--calibration", run / "calibration.json", "--image", tmp_path / "empty.png",
                     "--pixel", 500, 500, "--out", tmp_path / "query.json")
    assert result.returncode == 0, result.stderr
    result = run_cli("detect", "--calibration", run / "calibration.json", "--image", tmp_path / "empty.png",
                     "--out", tmp_path / "detection")
    assert result.returncode == 0, result.stderr
    # Independent failures must revoke the saved validation flag.
    uv = board_to_pixels(c, xy) + [50, 0]
    write_json(tmp_path / "wrong.json", {"pixel_xy": uv.tolist(), "board_xy_mm": xy})
    result = run_cli("verify", "--calibration", run / "calibration.json", "--points", tmp_path / "wrong.json",
                     "--out", tmp_path / "failed.json")
    assert result.returncode != 0
    assert not __import__("json").loads((run / "calibration.json").read_text())["independently_validated"]


@pytest.mark.parametrize("index_base,ordinal", [(0, 3), (1, 4)])
def test_collect_points_zero_and_one_numbering_same_physical_stud(tmp_path, monkeypatch, index_base, ordinal):
    from argparse import Namespace
    import lego_grid
    image = tmp_path / "empty.png"
    cv2.imwrite(str(image), np.zeros((720, 1280, 3), dtype=np.uint8))
    captured_context = []

    def fake_click(image, labels, context=None):
        captured_context.append(context)
        return [[465., 607.]]

    monkeypatch.setattr(lego_grid, "click_points", fake_click)
    out = tmp_path / "points.json"
    lego_grid.collect_points(Namespace(image=str(image), pitch_mm=16.75, surface_height_mm=0,
                                      stud=[[ordinal, ordinal]], rows=24, cols=24,
                                      index_base=index_base, out=str(out)))
    saved = __import__("json").loads(out.read_text())
    assert saved["board_xy_mm"] == [[50.25, 50.25]]
    assert saved["pixel_xy"] == [[465., 607.]]
    assert saved["input_index_base"] == index_base
    assert f"row {index_base}, col {index_base}" in captured_context[0]
