import numpy as np
import pytest

from depth_grid import measure_candidate
from rgbd_io import load_frame, save_frame
from saved_perception import process_saved, process_saved_bundle


@pytest.fixture
def sample():
    rgb = np.zeros((24, 24, 3), np.uint8)
    depth = np.full((24, 24), 1000, np.uint16)
    mask = np.zeros((24, 24), bool)
    mask[5:16, 5:16] = True
    intr = {"fx": 1000., "fy": 1000., "cx": 0., "cy": 0., "model": "none"}
    transform = np.eye(4)
    transform[2, 3] = -.99
    config = {"stud_pitch_m": .01, "grid_tolerance_stud": .1, "size_tolerance_m": .001,
              "height_tolerance_m": .002, "max_height_spread_m": .002,
              "min_depth_m": .1, "max_depth_m": 2., "angle_tolerance_deg": 5.,
              "min_depth_pixels": 10, "min_confidence": .5, "min_valid_fraction": .8,
              "top_heights_m": [.01, .02, .03, .04], "threshold_status": "temporary_test",
              "point_reference": "visible_surface_center", "coordinate_rules": "synthetic fixture only",
              "calibration_id": "fixture", "footprint_sizes_m": {"blue_2x2": [.01, .01]},
              "center_offsets_stud": {"blue_2x2": {"0": [0., 0.]}},
              "board_bounds_m": [[0., .24], [0., .24]]}
    meta = {"scene_id": "synthetic", "view_id": "V0", "captured_at": "fixture-time",
            "mode": "TEST", "robot_pose": None, "depth_scale_m": .001,
            "camera_info": {"aligned": intr}}
    return rgb, depth, mask, intr, transform, config, meta


def test_roundtrip_and_no_overwrite(tmp_path, sample):
    rgb, depth, _, _, _, _, meta = sample
    directory = tmp_path / "frame"
    save_frame(directory, rgb, depth, depth, meta)
    loaded = load_frame(directory)
    for actual, expected in zip(loaded[:3], (rgb, depth, depth)):
        np.testing.assert_array_equal(actual, expected)
    assert loaded[3] == meta
    with pytest.raises(FileExistsError):
        save_frame(directory, rgb, depth, depth, meta)


def test_candidate(sample):
    _, depth, mask, intr, transform, config, _ = sample
    result = measure_candidate(mask, "blue_2x2", .9, depth, .001, intr, transform, config)
    assert result["status"] == "CANDIDATE"
    assert result["measured_layer_index"] == 0
    assert result["grid_center_stud"] == [1., 1.]


@pytest.mark.parametrize("failure", ["no_depth", "low_conf", "height", "partial", "off_grid"])
def test_unknown(sample, failure):
    _, depth, mask, intr, transform, config, _ = sample
    conf = .9
    if failure == "no_depth":
        depth[:] = 0
    elif failure == "low_conf":
        conf = .1
    elif failure == "height":
        transform[2, 3] = -.5
    elif failure == "partial":
        mask[:, 10:] = False
    else:
        transform[0, 3] = .003
    assert measure_candidate(mask, "blue_2x2", conf, depth, .001, intr, transform, config)["status"] == "UNKNOWN"


def test_invalid_calibration(sample):
    _, depth, mask, intr, transform, config, _ = sample
    transform[0, 0] = 2
    with pytest.raises(ValueError, match="rigid"):
        measure_candidate(mask, "blue_2x2", .9, depth, .001, intr, transform, config)


def test_empty_detection_is_not_empty_board(tmp_path, sample):
    rgb, depth, _, _, transform, config, meta = sample
    save_frame(tmp_path / "frame", rgb, depth, depth, meta)
    calibration = {"calibration_id": "fixture", "views": {"V0": transform.tolist()}}
    result = process_saved(tmp_path / "frame", [], calibration, config)
    assert result["status"] == "PARTIAL"
    assert result["candidates"] == []


def test_missing_mode_rejected(tmp_path, sample):
    rgb, depth, _, _, _, _, meta = sample
    del meta["mode"]
    with pytest.raises(ValueError, match="mode"):
        save_frame(tmp_path / "frame", rgb, depth, depth, meta)


@pytest.mark.parametrize("failure", ["distortion", "overlap", "nonfinite"])
def test_invalid_measurement_settings(sample, failure):
    _, depth, mask, intr, transform, config, _ = sample
    if failure == "distortion":
        intr["model"] = "brown_conrady"
    elif failure == "overlap":
        config["height_tolerance_m"] = .02
    else:
        transform[0, 3] = float("nan")
    with pytest.raises(ValueError):
        measure_candidate(mask, "blue_2x2", .9, depth, .001, intr, transform, config)


def test_surface_conflict(sample):
    _, depth, mask, intr, transform, config, _ = sample
    depth[5:10] = 990
    assert measure_candidate(mask, "blue_2x2", .9, depth, .001, intr, transform, config)["reason"] == "surface_height_conflict"


@pytest.mark.parametrize("missing_depth", [False, True])
def test_saved_calculation_to_common_observed(tmp_path, sample, missing_depth):
    rgb, depth, mask, _, transform, config, meta = sample
    if missing_depth:
        depth[:] = 0
    save_frame(tmp_path / "frame", rgb, depth, depth, meta)
    config["center_to_anchor_offsets_stud"] = {"blue_2x2": {"0": [0., 0.]}}
    calibration = {"calibration_id": "fixture", "views": {"V0": transform.tolist()}}
    target = {"brick_type": "2x2x1", "color": "blue", "x": 1, "y": 1,
              "layer": 1, "orientation_deg": 0}
    records = [{"directory": tmp_path / "frame", "detections": [(mask, "blue_2x2", .9)],
                "verified_regions": [{"x": 1, "y": 1, "width": 2, "height": 2, "layer": 1}]}]
    observed, diagnostics = process_saved_bundle(records, calibration, config, "check", 0,
                                                 [], target, scene_stable=True)
    assert observed["status"] == ("UNOBSERVABLE" if missing_depth else "OK")
    assert observed["visible_blocks"] == ([] if missing_depth else [target])
    assert diagnostics["source_measurements"]


def test_invalid_empty_frame_calibration_rejected(tmp_path, sample):
    rgb, depth, _, _, transform, config, meta = sample
    save_frame(tmp_path / "frame", rgb, depth, depth, meta)
    transform[0, 0] = 2
    with pytest.raises(ValueError, match="rigid"):
        process_saved(tmp_path / "frame", [],
                      {"calibration_id": "fixture", "views": {"V0": transform.tolist()}}, config)
