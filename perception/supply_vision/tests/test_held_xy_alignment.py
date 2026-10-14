from copy import deepcopy
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from supply_vision.held_xy_alignment import held_edge_xy_candidate


def scene():
    board = np.eye(4)
    board[:3, :3] = Rotation.from_euler('xy', [19., -13.], degrees=True).as_matrix()
    board[:3, 3] = [20., 30., 900.]
    camera = np.eye(4)
    camera[:3, :3] = Rotation.from_euler('xy', [4., -5.], degrees=True).as_matrix()
    camera[:3, 3] = [45., -30., 80.]
    local = np.array([[-16., -24., 20.], [16., -24., 20.],
                      [16., 24., 20.], [-16., 24., 20.]])
    outline = local @ board[:3, :3].T + board[:3, 3]
    info = dict(width=640, height=480, frame_id='camera_color_optical_frame',
                distortion_model='plumb_bob', k=[510., 0., 320., 0., 505., 240., 0., 0., 1.],
                d=[.07, -.025, .001, -.002, .008])
    projection = dict(T_base_from_camera_mm=camera.tolist(), T_base_from_board_mm=board.tolist(),
                      target_hover_outline_base_mm=outline.tolist(), projection_independently_verified=False)
    return board, camera, outline, info, projection


def pixels(points, camera, info):
    optical = (points-camera[:3, 3]) @ camera[:3, :3]
    return cv2.projectPoints(optical, np.zeros(3), np.zeros(3),
                             np.array(info['k']).reshape(3, 3), np.array(info['d']))[0].reshape(-1, 2)


@pytest.mark.parametrize('edge_index', range(4))
def test_perspective_inverse_recovers_known_planar_shift_and_endpoint_order(edge_index):
    board, camera, outline, info, projection = scene()
    shift = board[:3, :3] @ np.array([8., -5., 0.])
    actual = outline[[edge_index, (edge_index+1) % 4]] + shift
    edge = pixels(actual, camera, info)
    for observed in (edge, edge[::-1]):
        result = held_edge_xy_candidate(observed, edge_index, info, projection)
        assert result['status'] == 'HELD_EDGE_XY_CANDIDATE'
        assert result['delta_base_xy_mm'] == pytest.approx(-shift[:2], abs=1e-6)
        assert result['observed_edge_midpoint_base_mm'] == pytest.approx(actual.mean(axis=0), abs=1e-6)
        assert result['height_assumed'] and not result['physical_accuracy_verified']
        assert not result['execution_allowed'] and result['physical_commands'] == 0


def test_correction_is_invariant_to_where_tcp_grips_the_block():
    board, camera, outline, info, projection = scene()
    actual = outline[:2] + board[:3, :3] @ [9., 7., 0.]
    result = held_edge_xy_candidate(pixels(actual, camera, info), 0, info, projection)
    for tcp_offset in ([0., 0., 30.], [12., -8., 45.]):
        tcp = actual.mean(axis=0) + tcp_offset
        corrected_tcp = tcp.copy(); corrected_tcp[:2] += result['delta_base_xy_mm']
        assert (corrected_tcp-np.array(tcp_offset))[:2] == pytest.approx(outline[:2].mean(axis=0)[:2])
    assert not result['centred_grasp_assumed']


def test_paired_endpoint_depth_removes_wrong_height_parallax_without_claiming_plane_tilt():
    board, camera, outline, info, projection = scene()
    actual = outline[:2] + board[:3, :3] @ [8., -5., 35.]
    edge = pixels(actual, camera, info)
    depth = np.zeros((480, 640), dtype=float)
    optical = (actual-camera[:3, 3]) @ camera[:3, :3]
    uv = np.floor(edge+.5).astype(int); depth[uv[:, 1], uv[:, 0]] = optical[:, 2]
    assumed = held_edge_xy_candidate(edge, 0, info, projection)
    result = held_edge_xy_candidate(edge, 0, info, projection, depth=depth, depth_scale_mm=1.,
        rgb_stamp_ns=1_000_000_000, depth_stamp_ns=1_000_000_000, depth_frame_id=info['frame_id'])
    expected = (outline[:2].mean(axis=0)-actual.mean(axis=0))[:2]
    assert result['delta_base_xy_mm'] == pytest.approx(expected, abs=1e-6)
    assert np.linalg.norm(np.array(assumed['delta_base_xy_mm'])-expected) > .1
    assert result['observed_endpoint_height_offsets_mm'] == pytest.approx([35., 35.], abs=1e-6)
    assert not result['height_assumed'] and not result['roll_pitch_observed']
    assert result['height_source'] == 'PAIRED_DEPTH_ENDPOINTS_UNVERIFIED'


@pytest.mark.parametrize('depth_case', ['zero', 'old', 'wrong_frame', 'no_scale', 'wrong_size'])
def test_unusable_optional_depth_reports_target_height_assumption(depth_case):
    _, camera, outline, info, projection = scene()
    edge = pixels(outline[:2], camera, info)
    options = dict(depth=np.zeros((480, 640)), depth_scale_mm=1., rgb_stamp_ns=1_000_000_000,
                   depth_stamp_ns=1_000_000_000, depth_frame_id=info['frame_id'])
    if depth_case == 'old': options['depth_stamp_ns'] -= 50_000_001
    if depth_case == 'wrong_frame': options['depth_frame_id'] = 'camera_depth_optical_frame'
    if depth_case == 'no_scale': options['depth_scale_mm'] = None
    if depth_case == 'wrong_size': options['depth'] = np.zeros((10, 10))
    result = held_edge_xy_candidate(edge, 0, info, projection, **options)
    assert result['status'] == 'HELD_EDGE_XY_CANDIDATE' and result['height_assumed']
    assert result['depth_reason'] and not result['physical_accuracy_verified']


@pytest.mark.parametrize('edge_index', [None, -1, 4, True, [0, 2]])
def test_no_automatic_guess_for_ambiguous_or_missing_physical_edge(edge_index):
    _, camera, outline, info, projection = scene()
    result = held_edge_xy_candidate(pixels(outline[:2], camera, info), edge_index, info, projection)
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'PHYSICAL_TARGET_EDGE_SELECTION_REQUIRED'


def test_camera_info_object_and_inputs_are_preserved():
    _, camera, outline, info, projection = scene(); before = deepcopy(projection)
    message = SimpleNamespace(**{k: v for k, v in info.items() if k != 'frame_id'},
                              header=SimpleNamespace(frame_id=info['frame_id']))
    result = held_edge_xy_candidate(pixels(outline[:2], camera, info), 0, message, projection)
    assert result['delta_base_xy_mm'] == pytest.approx([0., 0.], abs=1e-6)
    assert projection == before


@pytest.mark.parametrize('case', ['missing_info', 'same_endpoint', 'outside_image', 'bad_transform', 'missing_outline', 'nonplanar_outline'])
def test_invalid_visual_geometry_cannot_create_a_candidate(case):
    _, camera, outline, info, projection = scene(); edge = pixels(outline[:2], camera, info)
    if case == 'missing_info': info = None
    if case == 'same_endpoint': edge[1] = edge[0]
    if case == 'outside_image': edge[0, 0] = 640.
    if case == 'bad_transform': projection['T_base_from_camera_mm'][0][0] = 2.
    if case == 'missing_outline': projection.pop('target_hover_outline_base_mm')
    if case == 'nonplanar_outline': projection['target_hover_outline_base_mm'][3][2] += 1.
    result = held_edge_xy_candidate(edge, 0, info, projection)
    assert result['status'] == 'UNAVAILABLE' and result['delta_base_xy_mm'] is None


@pytest.mark.parametrize('case', ['parallel', 'behind'])
def test_ray_must_intersect_the_visible_side_of_the_target_plane(case):
    _, _, _, info, _ = scene()
    board = np.eye(4)
    local = np.array([[-16., -24., 0.], [16., -24., 0.], [16., 24., 0.], [-16., 24., 0.]])
    if case == 'parallel':
        board[:3, :3] = Rotation.from_euler('y', 90., degrees=True).as_matrix()
        board[:3, 3] = [100., 0., 800.]
    else:
        board[:3, 3] = [0., 0., -100.]
    projection = dict(T_base_from_camera_mm=np.eye(4).tolist(), T_base_from_board_mm=board.tolist(),
        target_hover_outline_base_mm=(local @ board[:3, :3].T + board[:3, 3]).tolist())
    info['d'] = []
    result = held_edge_xy_candidate([[320., 220.], [320., 260.]], 0, info, projection)
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == ('TOP_RAY_PARALLEL_TO_TARGET_PLANE' if case == 'parallel'
                                else 'TARGET_BODY_PLANE_BEHIND_CAMERA')
