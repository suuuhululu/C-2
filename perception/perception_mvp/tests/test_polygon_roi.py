from types import SimpleNamespace as N
import json

import numpy as np
import pytest

from perception_mvp import hand_cycle
from perception_mvp.supply_roi import save_roi


def test_concave_polygon_saved_without_convex_hull(tmp_path):
    points = [[1, 1], [10, 1], [10, 4], [4, 4], [4, 10], [1, 10]]
    message = N(header=N(stamp=N(sec=1, nanosec=2), frame_id='camera'))
    folder = save_roi(tmp_path, np.zeros((12, 12, 3), np.uint8), points, message,
                      board='assembly', view='D1')
    assert json.loads((folder / 'assembly_roi.json').read_text())['polygon_px'] == points
    assert hand_cycle.validate_polygon(points[::-1]).tolist() == points[::-1]


@pytest.mark.parametrize('points', [
    [[0, 0], [10, 10], [10, 0], [0, 10]],
    [[0, 0], [10, 0], [10, 10], [0, 0]],
    [[0, 0], [10, 0], [5, 0], [5, 10]],
    [[0, 0], [5, 0], [10, 0]],
])
def test_invalid_polygon_rejected_before_save(tmp_path, points):
    with pytest.raises(ValueError):
        save_roi(tmp_path, np.zeros((12, 12, 3), np.uint8), points, None)
    assert list(tmp_path.iterdir()) == []


def test_concave_hand_roi_excludes_notch(tmp_path, monkeypatch):
    weights = tmp_path / 'hand.pt'
    weights.touch()
    boxes = [[6, 6, 9, 9]]
    def tensor(value):
        return N(cpu=lambda: N(numpy=lambda: np.asarray(value)))
    model = N(names={0: 'hand'}, predict=lambda *a, **k: [
        N(boxes=N(xyxy=tensor(boxes), cls=tensor([0])))])
    monkeypatch.setattr(hand_cycle, 'load_hand_model', lambda _: model)
    detector = hand_cycle.HandDetector(weights, .25, [1, 1, 11, 11],
        min_valid_depth_fraction=1., stable_mean_difference=1.,
        board_polygon=[[1, 1], [10, 1], [10, 4], [4, 4], [4, 10], [1, 10]])
    rgb = np.zeros((12, 12, 3), np.uint8)
    depth = np.ones((12, 12), np.uint16)
    depth[6:10, 6:10] = 0
    assert detector.detect(rgb, depth)[0] == 'ABSENT'
    rgb[6:10, 6:10] = 255
    assert detector.detect(rgb, depth)[1] is True
    boxes[:] = [[2, 6, 3, 9]]
    assert detector.detect(rgb, depth)[0] == 'PRESENT'


def test_assembly_polygon_save(tmp_path):
    message = N(header=N(stamp=N(sec=1, nanosec=2), frame_id='camera'))
    points = [[5, 0], [10, 5], [5, 10], [0, 5]]
    folder = save_roi(tmp_path, np.zeros((12, 12, 3), np.uint8), points, message,
                      board='assembly')
    hand = json.loads((folder / 'hand_config.json').read_text())['hand']
    assert hand['board_polygon_v0'] == points
    assert hand['board_roi_v0'] == [0, 0, 11, 11]
    assert hand['confidence'] is None
    assert hand['weights'].endswith('/models/hand_yolo11n_added_20261012/weights/best.pt')
    assert json.loads((folder / 'assembly_roi.json').read_text())['purpose'] == 'ASSEMBLY_BOARD'


def test_diagonal_roi_does_not_create_hand_settings(tmp_path):
    message = N(header=N(stamp=N(sec=1, nanosec=2), frame_id='camera'))
    for view in ('D1', 'D3'):
        folder = save_roi(tmp_path, np.zeros((12, 12, 3), np.uint8),
                          [[1, 1], [10, 1], [10, 10], [1, 10]], message,
                          board='assembly', view=view)
        assert json.loads((folder / 'assembly_roi.json').read_text())['view_id'] == view
        assert not (folder / 'hand_config.json').exists()


def test_polygon_excludes_background_for_depth_stability_and_hand(tmp_path, monkeypatch):
    weights = tmp_path / 'hand.pt'
    weights.touch()
    boxes = [[0, 0, 1, 1]]  # In bounding rectangle, outside diamond.
    def tensor(value):
        return N(cpu=lambda: N(numpy=lambda: np.asarray(value)))
    model = N(names={0: 'hand'}, predict=lambda *a, **k: [
        N(boxes=N(xyxy=tensor(boxes), cls=tensor([0])))])
    monkeypatch.setattr(hand_cycle, 'load_hand_model', lambda _: model)
    detector = hand_cycle.HandDetector(weights, .25, [0, 0, 11, 11],
        min_valid_depth_fraction=1., stable_mean_difference=1., image_size=[12, 12],
        board_polygon=[[5, 0], [10, 5], [5, 10], [0, 5]])
    rgb = np.zeros((12, 12, 3), np.uint8)
    depth = np.ones((12, 12), np.uint16)
    depth[0, 0] = 0
    assert detector.detect(rgb, depth)[0] == 'ABSENT'
    rgb[0, 0] = 255
    state, stable, _ = detector.detect(rgb, depth)
    assert state == 'ABSENT' and stable
    boxes[:] = [[4, 4, 6, 6]]
    assert detector.detect(rgb, depth)[0] == 'PRESENT'
