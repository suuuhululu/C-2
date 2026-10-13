"""Runtime boundary tests use synthetic sensor arrays, never claim device validation."""
import json
from copy import deepcopy

import numpy as np
import pytest

from perception_mvp.rgbd_io import save_frame
from perception_mvp import main as runtime


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    rgb = np.zeros((24, 24, 3), np.uint8)
    depth = np.full((24, 24), 1000, np.uint16)
    mask = np.zeros((24, 24), bool)
    mask[5:16, 5:16] = True
    transform = np.eye(4)
    transform[2, 3] = -.99
    config = {"stud_pitch_m": .01, "grid_tolerance_stud": .1, "size_tolerance_m": .001,
              "height_tolerance_m": .002, "max_height_spread_m": .002,
              "min_depth_m": .1, "max_depth_m": 2., "angle_tolerance_deg": 5.,
              "min_depth_pixels": 10, "min_confidence": .5, "min_valid_fraction": .8,
              "top_heights_m": [.01, .02, .03, .04], "threshold_status": "temporary_test",
              "point_reference": "visible_surface_center", "coordinate_rules": "synthetic only",
              "calibration_id": "fixture", "footprint_sizes_m": {"blue_2x2": [.01, .01]},
              "center_offsets_stud": {"blue_2x2": {"0": [0., 0.]}},
              "center_to_anchor_offsets_stud": {"blue_2x2": {"0": [0., 0.]}},
              "board_bounds_m": [[0., .24], [0., .24]]}
    meta = {"scene_id": "synthetic", "view_id": "V0", "captured_at": "fixture-time",
            "mode": "REAL", "robot_pose": {"basis": "synthetic test only"},
            "depth_scale_m": .001, "check_id": "check", "observation_seq": 0,
            "calibration_id": "fixture", "camera_info": {"aligned": {
                "fx": 1000., "fy": 1000., "cx": 0., "cy": 0., "model": "none"}}}
    directory = tmp_path / "frame"
    save_frame(directory, rgb, depth, depth, meta)
    target = {"brick_type": "2x2x1", "color": "blue", "x": 1, "y": 1,
              "layer": 1, "orientation_deg": 0}
    manifest = {"mode": "REAL", "check_id": "check", "observation_seq": 0,
                "scene_stable": True, "target_after": target,
                "previous_accepted_blocks": [], "recordings": [{"directory": str(directory)}]}
    monkeypatch.setattr(runtime, "infer_masks", lambda *args: [(mask, "blue_2x2", .9)])
    calibration = {"calibration_id": "fixture", "views": {"V0": transform.tolist()}}
    return manifest, config, calibration, meta


def run(inputs, callback=None):
    manifest, config, calibration, _ = inputs
    return runtime.infer_bundle(manifest, "test-weights", calibration, config, .5, callback=callback)


def test_five_measured_levels_are_supported_without_inventing_sixth(inputs):
    from perception_mvp.depth_grid import validate_config
    config = deepcopy(inputs[1])
    config['top_heights_m'].append(.05)  # Synthetic unit-test geometry only.
    validate_config(config)
    config['top_heights_m'].append(.06)
    with pytest.raises(ValueError, match='top heights'):
        validate_config(config)


def test_depth_fifth_layer_reaches_observed_only_with_measured_reference(inputs):
    inputs[0]['target_after']['layer'] = 5
    inputs[2]['views']['V0'][2][3] = -.95  # Synthetic 50 mm surface.
    inputs[1]['top_heights_m'].append(.05)
    observed, _ = run(inputs)
    assert observed['visible_blocks'][0]['layer'] == 5
    inputs[1]['top_heights_m'].pop()
    observed, _ = run(inputs)
    assert observed['visible_blocks'] == [] and observed['status'] == 'UNOBSERVABLE'


def test_actual_geometry_path_without_coverage_stays_unobservable(inputs):
    observed, diagnostics = run(inputs)
    assert observed["visible_blocks"] == [inputs[0]["target_after"]]
    assert observed["status"] == "UNOBSERVABLE"
    assert observed["verified_regions"] == []
    assert diagnostics["capture_context"][0]["coverage_status"] == "unverified"


def test_body_measurement_adds_stud_once_before_layer_classification(inputs, tmp_path):
    from perception_mvp.rgbd_io import load_frame, save_frame
    from perception_mvp.depth_grid import process_saved
    rgb, raw, aligned, meta = load_frame(inputs[0]['recordings'][0]['directory'])
    aligned[7:10, 7:11] = 1004  # Synthetic two planes: body10mm and studs14mm.
    path = tmp_path / 'body_studs'
    save_frame(path, rgb, raw, aligned, meta)
    mask = np.zeros((24, 24), bool)
    mask[5:16, 5:16] = True
    config = deepcopy(inputs[1])
    config.update(block_surface_height_basis='BODY_TOP_PLUS_STUD', block_stud_height_m=.004,
                  top_heights_m=[.014, .024, .034, .044])
    result = process_saved(path, [(mask, 'blue_2x2', .9)], inputs[2], config)
    candidate = result['candidates'][0]
    assert candidate['status'] == 'CANDIDATE'
    assert candidate['body_surface_height_m'] == pytest.approx(.010)
    assert candidate['top_height_m'] == pytest.approx(.014)
    assert candidate['block_stud_added_m'] == .004
    assert candidate['measured_layer_index'] == 0
    assert result['verified_regions'] == [dict(x=1, y=1, width=2, height=2, layer=1)]
    assert result['verification_basis']['kind'] == 'MEASURED_OCCUPIED_FOOTPRINT_ONLY'
    inputs[0]['recordings'][0]['directory'] = str(path)
    inputs[1].update(config)
    observed, _ = run(inputs)
    assert observed['status'] == 'OK'
    assert observed['visible_blocks'] == [inputs[0]['target_after']]
    assert observed['verified_regions'] == result['verified_regions']


def test_saved_processing_uses_view_specific_depth_limits(inputs):
    from perception_mvp.depth_grid import process_saved
    mask = np.ones((24, 24), bool)
    inputs[1]['depth_ranges_m'] = {'V0': dict(min_depth_m=1.1, max_depth_m=1.2)}
    result = process_saved(inputs[0]['recordings'][0]['directory'], [(mask, 'blue_2x2', .9)],
                           inputs[2], inputs[1])
    assert result['candidates'][0]['reason'] == 'insufficient_depth'


def test_verified_evidence_and_callback(inputs):
    record = inputs[0]["recordings"][0]
    record.update(verified_regions=[{"x": 1, "y": 1, "width": 2, "height": 2, "layer": 1}],
                  verification_basis="synthetic independent coverage proof")
    received = []
    observed, _ = run(inputs, received.append)
    assert observed["status"] == "OK" and received == [observed]
    assert set(received[0]) == {"check_id", "observation_seq", "status", "visible_blocks",
                                "verified_regions", "reason"}


@pytest.mark.parametrize("field,value", [("check_id", "other"), ("observation_seq", 2),
                                         ("mode", "TEST"), ("scene_stable", "true"),
                                         ("target_after", None)])
def test_invalid_context_not_delivered(inputs, field, value):
    inputs[0][field] = value
    received = []
    with pytest.raises((ValueError, TypeError)):
        run(inputs, received.append)
    assert received == []


def test_duplicate_view_rejected(inputs):
    inputs[0]["recordings"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        run(inputs)


def test_coverage_without_evidence_rejected(inputs):
    inputs[0]["recordings"][0]["verified_regions"] = [
        {"x": 1, "y": 1, "width": 2, "height": 2, "layer": 1}]
    with pytest.raises(ValueError, match="verification_basis"):
        run(inputs)


def test_missing_model_does_not_return_fixture(inputs, monkeypatch):
    from perception_mvp.yolo_pipeline import infer_masks
    monkeypatch.setattr(runtime, "infer_masks", infer_masks)
    with pytest.raises(FileNotFoundError, match="weights"):
        run(inputs)


def test_backend_exception_propagates(inputs):
    def broken(payload):
        raise RuntimeError("Backend unavailable")
    with pytest.raises(RuntimeError, match="Backend unavailable"):
        run(inputs, broken)


def test_cli_output_and_no_overwrite(inputs, tmp_path):
    manifest, config, calibration, _ = inputs
    manifest["recordings"][0]["directory"] = "frame"
    for name, value in (("manifest", manifest), ("config", config), ("calibration", calibration)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    args = ["infer", "--manifest", str(tmp_path / "manifest.json"),
            "--config", str(tmp_path / "config.json"), "--calibration",
            str(tmp_path / "calibration.json"), "--weights", "unused-test-weights",
            "--detector-confidence", ".5", "--output", str(tmp_path / "result")]
    runtime.main(args)
    observed = json.loads((tmp_path / "result/observed.json").read_text())
    assert observed["status"] == "UNOBSERVABLE"
    assert (tmp_path / "result/diagnostics.json").is_file()
    with pytest.raises(FileExistsError):
        runtime.main(args)


def test_capture_cli_context_forwarded(tmp_path, monkeypatch):
    pose = tmp_path / "pose.json"
    pose.write_text('{"basis":"synthetic pose"}')
    captured = []
    monkeypatch.setattr(runtime, "capture", lambda *args, **kwargs: captured.append(kwargs))
    runtime.main(["capture", str(tmp_path / "frame"), "--serial", "fixture",
                  "--scene-id", "scene", "--view-id", "V0", "--robot-pose", str(pose),
                  "--mode", "REAL", "--stopped-and-clear", "--calibration-id", "cal",
                  "--check-id", "check", "--observation-seq", "0", "--width", "640",
                  "--height", "480", "--fps", "30", "--timeout-ms", "1000"])
    assert captured == [{"observation_context": {
        "check_id": "check", "observation_seq": 0, "calibration_id": "cal"}}]


@pytest.mark.parametrize("order", [["V0", "D3", "D1"], ["V0", "D2", "D4"]])
def test_live_cycle_rejects_nonagreed_order(inputs, order):
    manifest, config, calibration, _ = inputs
    manifest["view_order"] = order
    with pytest.raises(ValueError, match="V0 -> D1 -> D3"):
        runtime.observe_cycle(None, None, manifest, None, calibration, config, .5,
                              callback=None, confirm_view=None, bundle_valid=None)


@pytest.mark.parametrize('kind,full,status', [('INITIAL', True, 'OK'),
    ('INITIAL', False, 'UNOBSERVABLE'), ('FINAL', True, 'OK'),
    ('FINAL', False, 'UNOBSERVABLE')])
def test_cycle_initial_final_capture_archive_and_no_fake_target(inputs, monkeypatch, tmp_path,
                                                               kind, full, status):
    import time
    from perception_mvp.hand_cycle import HandCycle
    manifest, config, calibration, meta = inputs
    manifest.update(check_kind=kind, target_after=None, view_order=['V0', 'D1', 'D3'])
    gate = HandCycle(.2, 10.)
    gate.state, gate.last_time = 'READY', time.monotonic()
    captured, delivered = [], []
    regions = [dict(x=0, y=0, width=24, height=24, layer=i) for i in range(1, 6)] if full else []
    def capture(view):
        captured.append(view)
        return dict(directory=view, verified_regions=regions, verification_basis='synthetic fixture')
    monkeypatch.setattr(runtime, 'load_frame', lambda view:
        (np.zeros((2, 2, 3), np.uint8), np.full((2, 2), 1000, np.uint16),
         np.full((2, 2), 1000, np.uint16), dict(meta, view_id=view)))
    monkeypatch.setattr(runtime, 'process_saved', lambda *args: dict(candidates=[]))
    observed, _ = runtime.observe_cycle(gate, capture, manifest, None, calibration, config, .25,
        callback=delivered.append, confirm_view=lambda v: True, bundle_valid=lambda: True,
        output_root=tmp_path/'cycles')
    assert captured == ['V0', 'D1', 'D3']
    assert observed['status'] == status and delivered == [observed]
    archive = next((tmp_path/'cycles').iterdir())
    saved = json.loads((archive/'observed.json').read_text())
    assert saved == observed and observed['visible_blocks'] == []


def test_v0_offline_analysis_delay_does_not_expire_hand_gate(inputs, monkeypatch, tmp_path):
    from perception_mvp.hand_cycle import HandCycle
    manifest, config, calibration, meta = inputs
    manifest.update(check_kind='FINAL', target_after=None, view_order=['V0', 'D1', 'D3'])
    clock = [10.]
    monkeypatch.setattr('perception_mvp.hand_cycle.time.monotonic', lambda: clock[0])
    gate = HandCycle(.2, 1.)
    gate.state, gate.last_time = 'READY', 10.
    def capture(view):
        return dict(directory=view, verified_regions=[], verification_basis=None)
    monkeypatch.setattr(runtime, 'load_frame', lambda view:
        (np.zeros((2, 2, 3), np.uint8), np.full((2, 2), 1000, np.uint16),
         np.full((2, 2), 1000, np.uint16), dict(meta, view_id=view)))
    def analyze(*args):
        clock[0] += 1.1
        return dict(candidates=[])
    monkeypatch.setattr(runtime, 'process_saved', analyze)
    observed, _ = runtime.observe_cycle(gate, capture, manifest, None, calibration, config, .25,
        callback=lambda value: None, confirm_view=lambda v: True, bundle_valid=lambda: True,
        output_root=tmp_path/'delay-cycles')
    assert observed['status'] == 'UNOBSERVABLE'
    assert gate.state == 'WAIT_ENTRY'


def test_low_quality_v0_is_complemented_without_correction(inputs, monkeypatch, tmp_path):
    from perception_mvp.hand_cycle import HandCycle
    manifest, config, calibration, meta = inputs
    manifest["view_order"] = ["V0", "D1", "D3"]
    gate = HandCycle(.2, 10.)
    import time
    gate.state, gate.last_time = "READY", time.monotonic()
    captured, received = [], []

    def capture(view):
        captured.append(view)
        return {"directory": view, "verification_basis": "synthetic coverage proof",
                "verified_regions": [{"x": 1, "y": 1, "width": 2, "height": 2, "layer": 1}]}

    monkeypatch.setattr(runtime, "load_frame", lambda view:
        (np.zeros((2, 2, 3), np.uint8), np.full((2, 2), 1000, np.uint16),
         np.full((2, 2), 1000, np.uint16), dict(meta, view_id=view)))
    monkeypatch.setattr(runtime, "process_saved", lambda view, *args:
        {"candidates": [{"status": "UNKNOWN" if view == "V0" else "CANDIDATE"}]})
    monkeypatch.setattr(runtime, "candidate_to_block", lambda *args: manifest["target_after"])
    observed, _ = runtime.observe_cycle(gate, capture, manifest, None, calibration,
        config, .5, callback=received.append, confirm_view=lambda view: True,
        bundle_valid=lambda: True, output_root=tmp_path / "cycles")
    assert captured == ["V0", "D1", "D3"]
    assert observed["status"] == "OK" and received == [observed]
    bundles = list((tmp_path / "cycles").iterdir())
    assert len(bundles) == 1
    for view in ("V0", "D1", "D3"):
        folder = bundles[0] / view
        for name in ("rgb.npy", "depth_raw.npy", "depth_aligned.npy", "metadata.json",
                     "rgb.png", "depth_raw.png", "depth_aligned.png", "measurement.json",
                     "view_result.json", "diagnostics.json"):
            assert (folder / name).is_file()
        assert json.loads((folder / "metadata.json").read_text())["view_id"] == view
        assert np.load(folder / "depth_aligned.npy").dtype == np.uint16
    assert json.loads((bundles[0] / "observed.json").read_text()) == observed
    assert (bundles[0] / "submission.json").is_file()


def test_cycle_archives_unique_and_never_overwrite(inputs, tmp_path):
    from perception_mvp.rgbd_io import begin_cycle_archive, write_cycle_json
    manifest, config, calibration, _ = inputs
    root = tmp_path / "cycles"
    first = begin_cycle_archive(root, manifest, calibration, config, "weights.pt", .25)
    second = begin_cycle_archive(root, manifest, calibration, config, "weights.pt", .25)
    assert first != second
    snapshot = (first / "context.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_cycle_json(first / "context.json", {})
    assert (first / "context.json").read_bytes() == snapshot


def test_cycle_save_failure_holds_and_never_sends_result(inputs, monkeypatch, tmp_path):
    from perception_mvp.hand_cycle import HandCycle
    import time
    manifest, config, calibration, _ = inputs
    manifest["view_order"] = ["V0", "D1", "D3"]
    gate = HandCycle(.2, 10.)
    gate.state, gate.last_time = "READY", time.monotonic()
    captured, delivered = [], []
    def capture(view):
        captured.append(view)
        return inputs[0]["recordings"][0]
    def failed(*args):
        raise OSError("disk full")
    monkeypatch.setattr(runtime, "save_cycle_view", failed)
    with pytest.raises(OSError, match="disk full"):
        runtime.observe_cycle(gate, capture, manifest, None, calibration, config, .5,
            callback=delivered.append, confirm_view=lambda view: True,
            bundle_valid=lambda: True, output_root=tmp_path / "cycles")
    assert captured == ["V0"] and not delivered and gate.state == "HOLD"
    bundle = next((tmp_path / "cycles").iterdir())
    assert json.loads((bundle / "failure.json").read_text())["reason"] == "disk full"
