"""Math/failure tests only, not a camera or physical calibration acceptance."""
import numpy as np
import pytest

from perception_mvp.live_view import board_point, synchronized_packet
from perception_mvp.live_view import ViewSelection, load_view_calibrations
from perception_mvp.opencv_live import grid_anchor, stabilize, top_surface_points, color_mask


def test_performance_first_integrated_model_selection(tmp_path):
    from perception_mvp.live_view import DEFAULT_INTEGRATED_WEIGHTS, resolve_live_weights
    assert DEFAULT_INTEGRATED_WEIGHTS.name == 'blocks_yolo26s_best.pt'
    assert resolve_live_weights(None, True) == DEFAULT_INTEGRATED_WEIGHTS
    assert resolve_live_weights(None, False) is None
    override = tmp_path / 'other.pt'
    assert resolve_live_weights(override, True) == override


def test_merged_module_compatibility_imports():
    from perception_mvp import rgbd_io, ros_capture, multiview, state_tracking
    from perception_mvp import main, reobservation
    for name in ('image_array', 'info_dict', 'save_capture', 'stamp'):
        assert getattr(ros_capture, name) is getattr(rgbd_io, name)
    assert ros_capture.main is rgbd_io.ros_main
    assert state_tracking.compare_previous is multiview.compare_previous
    assert reobservation.reobserve_once is main.reobserve_once


@pytest.mark.parametrize('extra', [['--view', 'D1'], ['--integrated'], ['--stopped-and-clear']])
def test_hand_rgb_preview_rejects_cycle_and_non_v0_modes(extra, capsys):
    from perception_mvp.live_view import main
    with pytest.raises(SystemExit) as error:
        main(['--view', 'V0', '--output', '/tmp/unused-hand-test',
              '--weights', '/tmp/unused-hand.pt', '--confidence', '.25',
              '--hand-detect-only', *extra])
    assert error.value.code == 2
    assert '--hand-detect-only requires' in capsys.readouterr().err


def test_hand_roi_setup_saves_pixels_size_and_unconfigured_thresholds(tmp_path):
    import json
    from types import SimpleNamespace
    from perception_mvp.live_view import save_hand_roi
    message = SimpleNamespace(header=SimpleNamespace(frame_id='camera_color_optical_frame',
        stamp=SimpleNamespace(sec=1, nanosec=2)))
    rgb = np.zeros((24, 32, 3), np.uint8)
    assert save_hand_roi(tmp_path, rgb, (0, 0, 0, 0), message) is None
    assert not list(tmp_path.iterdir())
    path = save_hand_roi(tmp_path, rgb, (4, 5, 20, 12), message)
    settings = json.loads(path.read_text())
    assert settings['hand']['board_roi_v0'] == [4, 5, 24, 17]
    assert settings['hand']['board_image_size'] == [32, 24]
    assert settings['hand']['exit_seconds'] == 3.0
    assert settings['hand']['stable_seconds'] is None
    assert settings['hand']['min_valid_depth_fraction'] is None
    assert settings['roi_capture']['stamp_ns'] == 1_000_000_002
    assert (path.parent / 'roi_preview.png').is_file()
    other = save_hand_roi(tmp_path, rgb, (4, 5, 20, 12), message)
    assert path != other and path.is_file()
    with pytest.raises(ValueError, match='fit'):
        save_hand_roi(tmp_path, rgb, (30, 0, 10, 10), message)


def test_hand_roi_resolution_mismatch_rejected_before_inference():
    from perception_mvp.hand_cycle import HandDetector
    detector = HandDetector.__new__(HandDetector)
    detector.roi, detector.image_size = [0, 0, 2, 2], [4, 4]
    with pytest.raises(ValueError, match='resolution'):
        detector.detect(np.zeros((8, 8, 3), np.uint8), np.ones((8, 8), np.uint16))


def test_manual_and_controller_share_view_transition_boundary():
    state = ViewSelection('V0',dict(V0='v0',D1='d1',D3='d3'))
    assert not state.stopped
    assert state.update('V0',stopped=True)
    with pytest.raises(ValueError,match='mark moving'):
        state.update('D1',stopped=True)
    assert state.view == 'V0' and state.stopped
    state.update('V0',stopped=False)
    state.update('D1',stopped=False)
    state.update('D1',stopped=True)
    assert state.calibrations[state.view] == 'd1' and state.generation == 4
    assert not state.update('D1',stopped=True)
    # Controller can report moving + new View in one input, never a direct stopped jump.
    state.update('D3',stopped=False)
    assert state.view == 'D3' and not state.stopped
    with pytest.raises(ValueError):
        state.update('D2',stopped=True)
    with pytest.raises(ValueError):
        state.update('D3',stopped=1)


def test_manual_calibrations_require_all_matching_validated_views(tmp_path):
    import json
    for view in ('V0','D1','D3'):
        directory = tmp_path/('board_calibration_'+view)/view/'run'
        directory.mkdir(parents=True)
        (directory/'calibration.json').write_text(json.dumps(dict(view_id=view,independently_validated=True)))
    assert set(load_view_calibrations(tmp_path)) == {'V0','D1','D3'}
    path = tmp_path/'board_calibration_D1'/'D1'/'run'/'calibration.json'
    path.write_text(json.dumps(dict(view_id='V0',independently_validated=True)))
    with pytest.raises(ValueError,match='mismatch'):
        load_view_calibrations(tmp_path)


def test_rgb_outline_and_height_ray_projection():
    from perception_mvp.opencv_live import rgb_top_quad, corners_at_height
    rgb = np.zeros((80, 100, 3), np.uint8)
    rgb[20:60, 20:80] = [240, 30, 30]
    mask = np.zeros((80, 100), bool)
    mask[20:60, 20:80] = True
    quad = rgb_top_quad(rgb, mask, mask)
    assert quad.shape == (4, 2)
    info = dict(k=np.eye(3).ravel())
    calibration = dict(camera_pose=dict(R_camera_from_board=np.eye(3),
                        t_camera_from_board_mm=[0, 0, 100], height_normal_sign=-1))
    xy = corners_at_height(np.array([[1., 2.], [3., 4.]]), 20, info, calibration)
    np.testing.assert_allclose(xy, [[80, 160], [240, 320]])
    with pytest.raises(ValueError, match='behind_camera'):
        corners_at_height(np.array([[1., 2.]]), 120, info, calibration)


def test_rgb_outline_rejects_small_depth_patch_inside_whole_mask():
    from perception_mvp.opencv_live import rgb_top_quad
    rgb = np.zeros((80, 100, 3), np.uint8)
    rgb[20:60, 20:80] = [240, 30, 30]
    mask = np.zeros((80, 100), bool)
    mask[20:60, 20:80] = True
    top = np.zeros_like(mask)
    top[30:40, 30:40] = True
    with pytest.raises(ValueError, match='outline_unverified'):
        rgb_top_quad(rgb, mask, top)


def test_red_hue_wrap_excludes_other_colors_and_low_saturation():
    hsv = np.array([[[0, 200, 200], [179, 200, 200], [30, 200, 200],
                     [110, 200, 200], [0, 0, 200]]], dtype=np.uint8)
    np.testing.assert_array_equal(color_mask(hsv, 'red'), [[255, 255, 0, 0, 0]])


def test_red_two_by_one_anchor_both_orientations():
    for center, angle in (([14.5*16, 5*16], 0), ([14*16, 5.5*16], 90)):
        floating, integer = grid_anchor(center, (1, 2), angle, 16)
        np.testing.assert_allclose(floating, [14, 5])
        np.testing.assert_array_equal(integer, [14, 5])
    with pytest.raises(ValueError, match='outside_board'):
        grid_anchor([23.5*16, 5*16], (1, 2), 0, 16)


def test_top_surface_excludes_lower_side_depth():
    x, y = np.meshgrid(np.linspace(0, 34, 20), np.linspace(0, 34, 20))
    top = np.column_stack((x.ravel(), y.ravel(), np.full(x.size, 40.)))
    side = np.column_stack((np.linspace(0, 34, 200), np.zeros(200),
                            np.linspace(20, 36, 200)))
    points = np.vstack((top, side))
    keep = top_surface_points(points)
    assert keep[:len(top)].all()
    assert not keep[len(top):].any()
    assert np.median(points[keep, 2]) == 40


def test_top_surface_rejects_side_patch_and_missing_depth():
    with pytest.raises(ValueError, match='insufficient'):
        top_surface_points(np.zeros((20, 3)))
    x, y = np.meshgrid(np.linspace(0, 5, 20), np.linspace(0, 30, 20))
    tilted = np.column_stack((x.ravel(), y.ravel(), 40+x.ravel()))
    with pytest.raises(ValueError, match='not_board_parallel'):
        top_surface_points(tilted)


def test_point_and_missing_depth():
    k = [[100., 0., 1.], [0., 100., 1.], [0., 0., 1.]]
    info = dict(width=3, height=3, k=np.asarray(k).ravel(), d=[0.]*5,
                distortion_model='plumb_bob')
    calibration = dict(independently_validated=True, image_size=[3, 3],
                       intrinsics=dict(camera_matrix=k), camera_pose=dict(
                           R_camera_from_board=np.eye(3), t_camera_from_board_mm=[0., 0., 900.],
                           height_normal_sign=-1))
    depth = np.full((3, 3), 880, np.uint16)
    np.testing.assert_allclose(board_point((1, 1), depth, info, calibration), [0, 0, 20])
    depth[1, 1] = 0
    with pytest.raises(ValueError, match='missing'):
        board_point((1, 1), depth, info, calibration)
    calibration['independently_validated'] = False
    with pytest.raises(ValueError, match='validated'):
        board_point((1, 1), depth, info, calibration)


def test_grid_residual_is_not_hidden_by_rounding():
    floating, integer = grid_anchor([14.5*17, 5.5*17], (2, 2), 0, 17)
    np.testing.assert_allclose(floating, [14, 5])
    np.testing.assert_array_equal(integer, [14, 5])
    with pytest.raises(ValueError, match='off_grid'):
        grid_anchor([14.5*17, 6.04*17], (2, 2), 0, 17)
    with pytest.raises(ValueError, match='outside_board'):
        grid_anchor([23.5*17, 5.5*17], (2, 2), 0, 17)


def test_stabilization_requires_fresh_candidates_and_clears_missing():
    tracks = []
    for index in range(5):
        record = dict(color='yellow', pixel_center=np.array([100., 100.]),
                      status='CANDIDATE', size_hint='2x2', grid_float=np.array([14.02, 5.01]))
        tracks = stabilize([record], tracks)
        assert tracks[0]['status'] == ('STABLE_CANDIDATE' if index == 4 else 'UNKNOWN')
    assert tracks[0]['grid'] == [14, 5]
    assert stabilize([], tracks) == []
    record['status'], record['reason'] = 'UNKNOWN', 'insufficient_depth'
    assert len(stabilize([record], tracks)[0]['history']) == 0


def test_buffered_rgb_pair_without_raw_depth():
    from collections import deque
    from types import SimpleNamespace
    def message(ms):
        return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(
            sec=1, nanosec=ms*1_000_000)))
    earlier, latest, aligned = message(100), message(200), message(105)
    queues = dict(rgb=deque([earlier, latest]), aligned=deque([aligned]), raw=deque())
    packet = synchronized_packet(queues)
    assert packet == {'rgb': earlier, 'aligned': aligned}
    queues['raw'].append(message(400))
    assert 'raw' not in synchronized_packet(queues)
    queues['aligned'].clear()
    assert synchronized_packet(queues) is None


def test_unmatched_depth_is_not_used():
    from collections import deque
    from types import SimpleNamespace
    def message(seconds):
        return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=seconds, nanosec=0)))
    assert synchronized_packet(dict(rgb=deque([message(3)]), aligned=deque([message(1)]),
                                    raw=deque())) is None


def test_live_hand_v0_requires_entry_strict_exit_and_resets():
    from perception_mvp.hand_cycle import HandCycle, live_hand_event
    class Detector:
        presence = 'ABSENT'
        def detect(self, rgb, depth):
            return self.presence, True, {}
    detector, gate = Detector(), HandCycle(.2, 2.)
    def update(t, usable=True):
        return live_hand_event('V0', detector, gate, None, None, t, usable=usable)
    assert update(0)['state'] == 'WAIT_ENTRY'
    detector.presence = 'PRESENT'
    update(1)
    detector.presence = 'ABSENT'
    update(2)
    update(3)
    update(4)
    assert not update(5)['observation_allowed']  # Exactly 3 seconds is not enough.
    assert update(5.01)['observation_allowed']
    assert not update(5.02, False)['observation_allowed']
    assert gate.absent_since is None
    update(6)
    detector.presence = 'PRESENT'
    assert update(7)['absent_seconds'] == 0


def test_diagonal_views_never_load_or_execute_hand_detector():
    from perception_mvp.hand_cycle import live_hand_components, live_hand_event
    class Detector:
        def detect(self, *args):
            raise AssertionError('must not detect at diagonal View')
    for view in ('D1', 'D3'):
        assert live_hand_components(view, {}) == (None, None)
        event = live_hand_event(view, Detector(), None, None, None, 0, usable=True)
        assert event['presence'] == 'NOT_RUN' and event['state'] == 'DISABLED'


def test_live_hand_missing_settings_hold_and_detection_failure_reset():
    from perception_mvp.hand_cycle import HandCycle, live_hand_components, live_hand_event
    with pytest.raises(ValueError, match='settings missing'):
        live_hand_components('V0', {})
    event = live_hand_event('V0', None, None, None, None, 1, usable=True)
    assert event['presence'] == 'UNKNOWN' and not event['observation_allowed']
    class BrokenDetector:
        def detect(self, *args):
            raise RuntimeError('device detection failed')
    gate = HandCycle(.2, 2.)
    gate.update('PRESENT', True, 0)
    gate.update('ABSENT', True, 1)
    event = live_hand_event('V0', BrokenDetector(), gate, None, None, 2, usable=True)
    assert event['state'] == 'HOLD' and gate.absent_since is None
