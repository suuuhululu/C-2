"""Stud-midpoint layer wiring tests on synthetic scenes; not evidence of camera accuracy."""
import cv2
import numpy as np
import pytest

from perception_mvp.stud_layer import REQUIRED, select_stud_pair, stud_layer, validate_params
from perception_mvp.integrated_view import process_frame, draw_integrated

PARAMS = dict(canny_low=40, canny_high=120, minimum_contour_points=5, minimum_diameter_px=4.0,
              maximum_diameter_px=80.0, minimum_axis_ratio=0.35, maximum_normalized_residual=0.20,
              merge_px=5.0, pitch_tolerance_fraction=0.10, window_radius_px=6.0,
              minimum_window_points=30, mask_dilate_px=1, box_margin_px=4)
LEVELS = [22., 40.625, 59.25, 77.875, 96.5]
BOUNDS = [26., 43.2, 64., 83., 99.]
SIZE = (240, 320)  # height, width
FX, PITCH_MM, Z0 = 600., 16., 500.


def calibration():
    return dict(pitch_mm=PITCH_MM, camera_pose=dict(
        R_camera_from_board=np.eye(3).tolist(), t_camera_from_board_mm=[0., 0., Z0],
        height_normal_sign=-1))


def info():
    k = [FX, 0., 160., 0., FX, 120., 0., 0., 1.]
    return dict(k=k, width=SIZE[1], height=SIZE[0])


def spacing_at(top_height_mm):
    """One stud pitch in pixels at the depth of the block top."""
    return FX * PITCH_MM / (Z0 - top_height_mm)


def scene(top_height_mm=30., studs=2, duplicate=False):
    """Red block with dark circular studs; top face is top_height_mm above the plate."""
    rgb = np.full((*SIZE, 3), (20, 120, 60), np.uint8)
    block = (slice(70, 170), slice(100, 220))
    rgb[block] = (200, 40, 40)
    spacing = spacing_at(top_height_mm)
    centers = [(160 - spacing / 2, 120), (160 + spacing / 2, 120)][:studs]
    for cx, cy in centers:
        cv2.circle(rgb, (int(round(cx)), int(cy)), 6, (60, 0, 0), -1)
        if duplicate:
            cv2.circle(rgb, (int(round(cx)) + 1, int(cy)), 7, (90, 10, 10), 1)
    mask = np.zeros(SIZE, bool)
    mask[block] = True
    depth = np.full(SIZE, int(Z0), np.uint16)
    depth[block] = int(Z0 - top_height_mm)
    return rgb, mask, depth, centers


def run(rgb, mask, depth, **overrides):
    options = dict(layer_heights_mm=LEVELS, height_tolerance_mm=5., height_reference_offset_mm=4.,
                   block_stud_mm=4., first_layer_min_mm=6., layer_upper_bounds_mm=BOUNDS)
    options.update(overrides)
    return stud_layer(rgb, mask, depth, info(), calibration(), PARAMS, **options)


def test_two_studs_give_height_and_layer_at_their_midpoint():
    rgb, mask, depth, centers = scene(30.)
    result = run(rgb, mask, depth)
    assert result['reason'] is None
    assert result['height_mm'] == pytest.approx(30. + 4. + 4.)
    assert result['layer'] == 2  # 38mm is inside 26..43.2
    np.testing.assert_allclose(result['midpoint_uv'], [160, 120], atol=1.5)
    assert result['scope'] == 'LAYER_ONLY_STUD_MIDPOINT'
    assert result['pair_candidates'] >= 1


def test_height_follows_the_block_top_into_other_layers():
    for top, layer in ((12., 1), (30., 2), (47., 3), (65., 4), (83., 5)):
        rgb, mask, depth, _ = scene(top)
        assert run(rgb, mask, depth)['layer'] == layer


def test_duplicate_edge_circles_do_not_create_a_second_pair():
    rgb, mask, depth, _ = scene(30., duplicate=True)
    result = run(rgb, mask, depth)
    assert result['layer'] == 2
    assert result['height_mm'] == pytest.approx(38.)


def test_no_or_single_stud_is_unknown_not_a_guessed_layer():
    for count in (0, 1):
        rgb, mask, depth, _ = scene(30., studs=count)
        result = run(rgb, mask, depth)
        assert result['layer'] is None and result['height_mm'] is None
        assert result['reason'] == 'stud_pair_not_found'


def test_pair_must_match_one_stud_pitch():
    spacing = spacing_at(30.)
    centers = [np.array([100., 100.]), np.array([100. + 3 * spacing, 100.])]
    assert select_stud_pair(centers, spacing, .10) == (None, 0)
    near = [np.array([100., 100.]), np.array([100. + spacing * 1.05, 100.])]
    pair, count = select_stud_pair(near, spacing, .10)
    assert pair is not None and count == 1


def test_window_without_depth_is_unknown():
    rgb, mask, depth, _ = scene(30.)
    depth[110:131, 150:171] = 0
    result = run(rgb, mask, depth)
    assert result['reason'] == 'stud_window_too_few_depth_points'
    assert result['layer'] is None and result['height_mm'] is None


def test_height_outside_all_layers_is_unknown_but_keeps_the_height():
    rgb, mask, depth, _ = scene(95.)  # 103mm after the datum and stud
    result = run(rgb, mask, depth)
    assert result['layer'] is None
    assert result['reason'] == 'height_outside_layer_reference'
    assert result['height_mm'] == pytest.approx(103.)


def test_board_baseline_bias_is_subtracted():
    class Plane:
        def bias_at(self, x, y):
            return -5.
    rgb, mask, depth, _ = scene(30.)
    result = run(rgb, mask, depth, board_plane=Plane())
    assert result['height_mm'] == pytest.approx(30. + 5. + 4. + 4.)


def test_parameters_must_be_explicit_and_consistent():
    with pytest.raises(ValueError):
        validate_params({key: PARAMS[key] for key in REQUIRED[:-1]})
    for key, value in (('canny_low', 130), ('pitch_tolerance_fraction', 1.2), ('merge_px', 0),
                       ('window_radius_px', True), ('minimum_contour_points', 4)):
        with pytest.raises(ValueError):
            validate_params({**PARAMS, key: value})
    validate_params(PARAMS)


def test_process_frame_adds_layer_only_result_without_changing_other_fields():
    from types import SimpleNamespace

    class Tensor:
        def __init__(self, value):
            self.value = np.asarray(value)

        def cpu(self):
            return self

        def numpy(self):
            return self.value

        def __len__(self):
            return len(self.value)

    class Boxes:
        cls, conf = Tensor([0]), Tensor([.9])

        def __len__(self):
            return 1

    class Model:
        names = {0: 'red_2x1'}

        def predict(self, image, **kwargs):
            mask = np.any(image != 0, axis=2)[None]
            return [SimpleNamespace(boxes=Boxes(), masks=SimpleNamespace(data=Tensor(mask)))]

    rgb, _, depth, _ = scene(30.)
    cal = dict(calibration(), independently_validated=True, image_size=[SIZE[1], SIZE[0]],
               intrinsics=dict(camera_matrix=np.asarray(info()['k']).reshape(3, 3).tolist()))
    camera_info = dict(info(), distortion_model='plumb_bob', d=[0., 0., 0., 0., 0.])
    kwargs = dict(layer_heights_mm=LEVELS, height_tolerance_mm=5., height_reference_offset_mm=4.,
                  top_plane_stud_mm=4., first_layer_min_mm=6., layer_upper_bounds_mm=BOUNDS)
    plain = process_frame(rgb, Model(), .5, depth, camera_info, cal, **kwargs)[0]
    extra = process_frame(rgb, Model(), .5, depth, camera_info, cal, stud_layer_params=PARAMS,
                          stud_layer_stud_mm=4., **kwargs)[0]
    assert 'stud_layer' not in plain
    assert extra['stud_layer']['layer'] == 2
    assert extra['stud_layer']['height_mm'] == pytest.approx(38.)
    for key in plain:
        if key != 'mask':
            assert plain[key] == extra[key]
    canvas = draw_integrated(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [extra])
    assert canvas.shape == rgb.shape
