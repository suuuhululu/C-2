"""TOP_PLANE_PLUS_STUD wiring: measured top plane, physical stud added once. Synthetic inputs."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import yaml

from perception_mvp import opencv_live
from perception_mvp.depth_grid import validate_config
from perception_mvp.integrated_view import measure_instance

LAYERS = [22, 40.625, 59.25, 77.875, 96.5]


def geometry():
    return yaml.safe_load(Path(__file__).resolve().parents[1].joinpath('config.yaml').read_text())['geometry']


def scene(monkeypatch, plane_mm):
    monkeypatch.setattr(opencv_live, 'rgb_top_quad', lambda *args: np.zeros((4, 2)))
    monkeypatch.setattr('perception_mvp.integrated_view.corners_at_height',
        lambda *args: np.array([[59.5, 59.5], [93.5, 59.5], [93.5, 93.5], [59.5, 93.5]]))
    rgb = np.full((30, 30, 3), 200, np.uint8)
    mask = np.ones((30, 30), bool)
    depth = np.full((30, 30), int(round(822 - plane_mm)), np.uint16)  # board height = 822 - depth
    k = [[100., 0., 15.], [0., 100., 15.], [0., 0., 1.]]
    info = dict(width=30, height=30, k=np.array(k).ravel(), d=[0.]*5, distortion_model='plumb_bob')
    calibration = dict(independently_validated=True, image_size=[30, 30], pitch_mm=17,
        intrinsics=dict(camera_matrix=k), camera_pose=dict(R_camera_from_board=np.eye(3),
        t_camera_from_board_mm=[0, 0, 822], height_normal_sign=-1))
    return rgb, mask, depth, info, calibration


def test_default_config_selects_top_plane_plus_stud_and_validates():
    config = geometry()
    assert config['block_surface_height_basis'] == 'TOP_PLANE_PLUS_STUD'
    assert config['block_stud_height_m'] == .004
    validate_config(config)


def test_unknown_basis_is_rejected():
    config = deepcopy(geometry())
    config['block_surface_height_basis'] = 'MAX_PIXEL'
    with pytest.raises(ValueError, match='explicit surface basis'):
        validate_config(config)


def test_live_layer_reference_routes_stud_to_top_plane_not_pair_search():
    from perception_mvp.live_view import load_layer_reference
    reference = load_layer_reference()
    assert reference['top_plane_stud_mm'] == pytest.approx(4.)
    assert reference['block_stud_height_mm'] == 0.  # Legacy body/stud pair search stays off.


def test_integrated_measure_adds_stud_once_to_measured_plane(monkeypatch):
    rgb, mask, depth, info, calibration = scene(monkeypatch, 18.)
    result = measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration, LAYERS, 2.5,
                              top_plane_stud_mm=4.)
    assert result['body_height_mm'] == 18.
    assert result['height_mm'] == 22.
    assert result['block_stud_added_mm'] == 4.
    assert result['layer'] == 1 and result['reason'] is None


def test_integrated_measure_applies_board_datum_and_stud_separately(monkeypatch):
    # Board datum +4mm and block stud +4mm are different operations (never merged or doubled).
    rgb, mask, depth, info, calibration = scene(monkeypatch, 14.)
    result = measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration, LAYERS, 2.5,
                              height_reference_offset_mm=4., top_plane_stud_mm=4.)
    assert result['body_height_mm'] == 18. and result['height_mm'] == 22. and result['layer'] == 1


def test_plane_without_stud_addition_is_not_silently_raised(monkeypatch):
    rgb, mask, depth, info, calibration = scene(monkeypatch, 18.)
    result = measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration, LAYERS, 2.5)
    assert result['height_mm'] == 18. and result['layer'] is None
    assert result['reason'] == 'height_outside_layer_reference'


def test_two_stud_bases_cannot_be_combined(monkeypatch):
    rgb, mask, depth, info, calibration = scene(monkeypatch, 18.)
    with pytest.raises(ValueError, match='one block stud basis'):
        measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration, LAYERS, 2.5,
                         block_stud_height_mm=4., top_plane_stud_mm=4.)


def test_invalid_top_plane_stud_is_rejected(monkeypatch):
    rgb, mask, depth, info, calibration = scene(monkeypatch, 18.)
    with pytest.raises(ValueError, match='top_plane_stud'):
        measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration, LAYERS, 2.5,
                         top_plane_stud_mm=float('nan'))


def test_single_high_outlier_is_still_not_a_top_surface():
    # The selector is unchanged: a lone high pixel never defines the plane.
    x, y = np.meshgrid(np.arange(10), np.arange(10))
    cloud = np.vstack((np.column_stack((x.ravel(), y.ravel(), np.full(100, 18.))), [[0., 0., 100.]]))
    selected = opencv_live.top_surface_points(cloud)
    assert np.median(cloud[selected, 2]) == 18. and not selected[-1]
