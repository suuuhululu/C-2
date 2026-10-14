"""Per-capture board baseline (owner decision 2026-10-14). Synthetic depth, no camera, no YOLO."""
import numpy as np
import pytest

from perception_mvp import depth_grid
from perception_mvp.depth_grid import fit_board_plane, params_from_geometry
from perception_mvp.integrated_view import frame_board_baseline

BOUNDS = [[-1000., 1000.], [-1000., 1000.]]
PARAMS = dict(min_points=2000, max_tilt_deg=3., max_residual_std=5., max_correction=15.,
              exclusion_px=15, z_window=30.)


def plate_points(z=-9.3, slope=(0., 0.), noise=0., n=6000, seed=1):
    rng = np.random.default_rng(seed)
    x, y = rng.uniform(0, 376, n), rng.uniform(0, 376, n)
    return np.column_stack((x, y, z + slope[0]*x + slope[1]*y + rng.normal(0, noise, n)))


def fit(points, expected=-4., **override):
    return fit_board_plane(points, expected_plate_z=expected, bounds=[[0, 376], [0, 376]],
                           **dict(PARAMS, **override))


def test_measured_plate_below_the_datum_gives_a_negative_bias_to_subtract():
    plane = fit(plate_points(-9.3, noise=1.))
    assert plane.bias_at(100, 100) == pytest.approx(-5.3, abs=.3)
    assert 21.9 == pytest.approx(16.6 - plane.bias_at(100, 100), abs=.4)  # Measured 2026-10-14 case.


def test_flat_datum_expects_a_zero_plate_and_a_tilted_plate_is_followed():
    plane = fit(plate_points(-3., slope=(.01, 0.), noise=.5), expected=0.)
    assert plane.bias_at(0, 100) == pytest.approx(-3., abs=.3)
    assert plane.bias_at(300, 100) == pytest.approx(0., abs=.3)


def test_stud_and_noise_tails_do_not_pull_the_plate_plane():
    points = plate_points(-9.3, noise=1.)
    points[::5, 2] += 4.  # A fifth of the pixels sit on stud tops.
    assert fit(points).bias_at(100, 100) == pytest.approx(-5.3, abs=.3)  # Known limit: ~40% studs pulls ~1.5mm.


@pytest.mark.parametrize('points,override,reason', [
    (plate_points(n=500), {}, 'board_baseline_insufficient_points'),
    (plate_points(slope=(.1, 0.)), {}, 'board_baseline_tilted'),
    (plate_points(noise=8.), {}, 'board_baseline_noisy'),
    (plate_points(-40.), dict(z_window=60., max_residual_std=9.), 'board_baseline_out_of_range'),
])
def test_unreliable_fits_are_refused_not_defaulted(points, override, reason):
    with pytest.raises(ValueError, match=reason):
        fit(points, **override)


def test_params_follow_config_and_missing_or_unknown_settings_are_refused():
    config = dict(board_baseline='PLATE_PLANE_FIT', board_baseline_min_points=2000,
                  board_baseline_max_tilt_deg=3., board_baseline_max_residual_std_m=.005,
                  board_baseline_max_correction_m=.015, board_baseline_exclusion_px=15,
                  board_baseline_z_window_m=.03)
    assert params_from_geometry(config, 1000.)['max_residual_std'] == pytest.approx(5.)
    assert params_from_geometry({}, 1000.) is None
    with pytest.raises(ValueError, match='unsupported'):
        params_from_geometry(dict(config, board_baseline='OTHER'), 1.)
    del config['board_baseline_min_points']
    with pytest.raises(ValueError, match='settings_missing'):
        params_from_geometry(config, 1.)


def live_inputs(plate_depth_mm=500, block_depth_mm=485):
    depth = np.full((720, 1280), plate_depth_mm, np.uint16)
    block = np.zeros(depth.shape, bool)
    block[300:360, 600:660] = True
    depth[block] = block_depth_mm  # A raised block that must not enter the plate fit.
    info = dict(k=[500., 0, 640., 0, 500., 360., 0, 0, 1], width=1280, height=720,
                distortion_model='plumb_bob', d=[0., 0., 0., 0., 0.])
    calibration = dict(independently_validated=True, image_size=[1280, 720],
        intrinsics=dict(camera_matrix=[[500., 0, 640.], [0, 500., 360.], [0, 0, 1]]),
        camera_pose=dict(t_camera_from_board_mm=[0., 0., 490.7], R_camera_from_board=np.eye(3).tolist(),
                         height_normal_sign=-1))
    return depth, info, calibration, block


def test_live_path_fits_the_plate_from_pixels_away_from_detected_blocks():
    depth, info, calibration, block = live_inputs()
    plane = frame_board_baseline(depth, info, calibration, block, PARAMS, BOUNDS, -4.)
    # Plate z = 490.7 - 500 = -9.3 in the board frame; stud-top datum expects -4.
    assert plane.bias_at(0, 0) == pytest.approx(-5.3, abs=.05)
    assert plane.residual_std < .5


def test_live_path_without_enough_plate_pixels_is_refused():
    depth, info, calibration, block = live_inputs()
    with pytest.raises(ValueError, match='board_baseline_insufficient_points'):
        frame_board_baseline(depth, info, calibration, np.ones(depth.shape, bool), PARAMS, BOUNDS, -4.)


def pinhole(u, v, distances, intrinsics, width, height):
    return np.column_stack(((np.asarray(u)-640.)*distances/500., (np.asarray(v)-360.)*distances/500.,
                            distances))


def test_team_path_fits_in_metres_against_a_flat_zero_datum(monkeypatch):
    monkeypatch.setattr(depth_grid, 'deproject_pixels', pinhole)
    depth, _, _, block = live_inputs()
    transform = np.eye(4)
    transform[2, 2], transform[1, 1] = -1., -1.  # Board z = 0.4953 - camera z (rigid, right-handed).
    transform[2, 3] = .4953
    config = dict(board_baseline='PLATE_PLANE_FIT', board_baseline_min_points=2000,
                  board_baseline_max_tilt_deg=3., board_baseline_max_residual_std_m=.005,
                  board_baseline_max_correction_m=.015, board_baseline_exclusion_px=15,
                  board_baseline_z_window_m=.03, layer_height_reference='BOARD_FLAT_SURFACE_ZERO',
                  min_depth_m=.3, max_depth_m=.6, board_bounds_m=[[-1., 1.], [-1., 1.]])
    plane = depth_grid.frame_board_baseline([(block, 'yellow_2x2', .9)], depth, .001, {}, transform, config)
    assert plane.bias_at(0, 0) == pytest.approx(-.0047, abs=1e-4)  # 0.4953 - 0.5: plate is 4.7mm low.
    with pytest.raises(ValueError, match='requires_flat_board_zero'):
        depth_grid.frame_board_baseline([], depth, .001, {}, transform,
                                        dict(config, layer_height_reference='STUD_TOP'))
    assert depth_grid.frame_board_baseline([], depth, .001, {}, transform,
                                           {k: v for k, v in config.items()
                                            if not k.startswith('board_baseline')}) is None
