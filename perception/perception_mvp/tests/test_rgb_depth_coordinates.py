"""Synthetic RGB corner projection, not device calibration evidence."""
from pathlib import Path
import numpy as np
import yaml
from perception_mvp.depth_grid import measure_candidate


def inputs(top_mm=18., basis=None):
    config = yaml.safe_load(Path(__file__).resolve().parents[1].joinpath('config.yaml').read_text())['geometry']
    config = dict(config, min_depth_m=.1, max_depth_m=2.)
    if basis is not None:
        config['block_surface_height_basis'] = basis
    mask = np.zeros((100, 100), bool)
    mask[24:57, 24:57] = True
    rgb = np.zeros((100, 100, 3), np.uint8)
    rgb[mask] = [230, 40, 40]
    depth = np.full(mask.shape, 1000, np.uint16)
    transform = np.eye(4)
    transform[2, 3] = -(1. - top_mm / 1000.)  # Measured flat-board height of the top plane.
    intrinsics = dict(fx=1000., fy=1000., cx=0., cy=0., model='none')
    return mask, rgb, depth, transform, intrinsics, config


def test_production_coordinates_use_rgb_corners_at_measured_top():
    # Default basis TOP_PLANE_PLUS_STUD: plane at 18mm + one 4mm stud = layer 1 (22mm).
    mask, rgb, depth, transform, intrinsics, config = inputs()
    assert config['block_surface_height_basis'] == 'TOP_PLANE_PLUS_STUD'
    result = measure_candidate(mask, 'yellow_2x2', .9, depth, .001, intrinsics,
                               transform, config, rgb=rgb)
    assert result['status'] == 'CANDIDATE'
    np.testing.assert_allclose(result['grid_center_stud'], [2.5, 2.5])
    assert result['measured_layer_index'] == 0
    assert result['block_stud_added_m'] == .004
    np.testing.assert_allclose(result['top_height_m'], .022)
    np.testing.assert_allclose(result['body_surface_height_m'], .018)


def test_direct_basis_still_adds_no_stud():
    mask, rgb, depth, transform, intrinsics, config = inputs(22., 'DIRECT_STUD_TOP')
    result = measure_candidate(mask, 'yellow_2x2', .9, depth, .001, intrinsics,
                               transform, config, rgb=rgb)
    assert result['status'] == 'CANDIDATE' and result['measured_layer_index'] == 0
    assert result['block_stud_added_m'] == 0.


def test_outline_is_projected_on_measured_plane_not_stud_height():
    # Same camera-to-plane distance in both cases, so the footprint must be identical.
    # Projecting at the +4mm height would shift XY by the 0.4% perspective scale.
    plus = inputs(18.)
    direct = inputs(22., 'DIRECT_STUD_TOP')
    results = [measure_candidate(m, 'yellow_2x2', .9, d, .001, i, t, c, rgb=r)
               for m, r, d, t, i, c in (plus, direct)]
    np.testing.assert_allclose(results[0]['surface_center_m'], results[1]['surface_center_m'],
                               rtol=0, atol=1e-9)


def test_plane_plus_stud_outside_layer_tolerance_stays_unknown():
    # A plane at 22mm would become 26mm after the stud: 4mm from layer 1, outside +/-2.5mm.
    mask, rgb, depth, transform, intrinsics, config = inputs(22.)
    result = measure_candidate(mask, 'yellow_2x2', .9, depth, .001, intrinsics,
                               transform, config, rgb=rgb)
    assert result['status'] == 'UNKNOWN' and result['reason'] == 'height_not_in_measured_layer'


def test_direct_mode_never_falls_back_to_depth_only_outline():
    mask, _, depth, transform, intrinsics, config = inputs()
    result = measure_candidate(mask, 'yellow_2x2', .9, depth, .001, intrinsics, transform, config)
    assert result['status'] == 'UNKNOWN' and result['reason'] == 'rgb_outline_input_missing'
