"""Algorithm wiring tests; not evidence of trained-model or camera accuracy."""
from types import SimpleNamespace
import numpy as np
import pytest

from perception_mvp.integrated_view import process_frame, color_crop, draw_integrated


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
        self.input = image.copy()
        mask = np.any(image != 0, axis=2)[None]
        return [SimpleNamespace(boxes=Boxes(), masks=SimpleNamespace(data=Tensor(mask)))]


def test_crop_preserves_pixels_restores_mask_and_missing_depth():
    rgb = np.zeros((100, 150, 3), np.uint8)
    rgb[40:60, 70:100] = [255, 0, 0]
    rgb[45:50, 80:85] = [255, 255, 255]  # Reflection must survive HSV preprocessing.
    colors, box = color_crop(rgb)
    model = Model()
    records = process_frame(rgb, model, .5)
    x0, y0, x1, y1 = box
    np.testing.assert_array_equal(model.input, rgb[y0:y1, x0:x1, ::-1])
    assert records[0]['mask'].shape == rgb.shape[:2]
    assert records[0]['mask'][46, 81]
    assert records[0]['color'] == 'red'
    assert records[0]['reason'] == 'calibration_or_synced_depth_missing'
    assert records[0]['layer'] is None
    assert draw_integrated(rgb[:, :, ::-1].copy(), records).shape == rgb.shape


def test_color_conflict_is_not_geometry_success():
    rgb = np.zeros((100, 150, 3), np.uint8)
    rgb[40:60, 70:100] = [0, 0, 255]
    record = process_frame(rgb, Model(), .5)[0]
    assert record['color'] == 'blue'
    assert record['reason'] == 'color_missing_or_conflict'
    assert 'grid' not in record


def test_no_color_does_not_infer_or_claim_empty_board():
    assert process_frame(np.zeros((50, 50, 3), np.uint8), None, .5) == []


def test_roi_excludes_outside_candidates():
    rgb = np.zeros((100, 150, 3), np.uint8)
    rgb[10:20, 10:20] = [255, 0, 0]
    roi = np.zeros((100, 150), bool)
    roi[40:80, 60:120] = True
    assert process_frame(rgb, None, .25, roi_mask=roi) == []
    rgb[50:60, 80:90] = [255, 0, 0]
    record = process_frame(rgb, Model(), .25, roi_mask=roi)[0]
    assert record['mask'][55, 85] and not record['mask'][15, 15]


def test_roi_boundary_is_not_valid_geometry():
    rgb = np.zeros((100, 150, 3), np.uint8)
    rgb[40:60, 70:100] = [255, 0, 0]
    roi = np.zeros((100, 150), bool)
    roi[:, :85] = True
    record = process_frame(rgb, Model(), .25, roi_mask=roi)[0]
    assert record['reason'] == 'instance_crosses_roi_boundary'
    assert 'grid' not in record and record['layer'] is None
    assert not record['mask'][:, 85:].any()


def test_roi_resolution_mismatch_blocks_inference():
    with pytest.raises(ValueError, match='resolution'):
        process_frame(np.zeros((100, 150, 3), np.uint8), None, .25,
                      roi_mask=np.ones((50, 50), bool))


def test_insufficient_depth_stays_unknown():
    rgb = np.zeros((100, 150, 3), np.uint8)
    rgb[40:60, 70:100] = [255, 0, 0]
    result = process_frame(rgb, Model(), .5, np.zeros((100, 150), np.uint16), {}, {})
    assert result[0]['reason'] == 'insufficient_depth'


def test_invalid_confidence_fails():
    with pytest.raises(ValueError, match='confidence'):
        process_frame(np.zeros((50, 50, 3), np.uint8), None, float('nan'))


@pytest.mark.parametrize('known,expected',[
    (True,'yellow 2x3 | (8, 10) | L2'),
    (False,'yellow 2x3 | XY:? | L:?')])
def test_block_label_only_kind_grid_layer(monkeypatch,known,expected):
    from copy import deepcopy
    texts = []
    monkeypatch.setattr('perception_mvp.integrated_view.cv2.putText',
                        lambda image,text,*args: texts.append(text))
    mask = np.zeros((120,320),bool)
    mask[40:60,280:300] = True
    record = dict(mask=mask,part_class='yellow_2x3',color='yellow',confidence=.93,
        axis_angle_deg=90.,height_mm=42.,layer=2 if known else None,
        reason=None if known else 'calibration_or_synced_depth_missing')
    if known:
        record['grid'] = [8,10]
    before = deepcopy(record)
    draw_integrated(np.zeros((120,320,3),np.uint8),[record])
    assert texts == [expected]
    assert all(record[key] == before[key] for key in record if key != 'mask')
    np.testing.assert_array_equal(record['mask'],before['mask'])


def test_color_conflict_not_displayed_as_confirmed_color(monkeypatch):
    texts = []
    monkeypatch.setattr('perception_mvp.integrated_view.cv2.putText',
                        lambda image,text,*args: texts.append(text))
    draw_integrated(np.zeros((40,300,3),np.uint8),[dict(mask=np.ones((40,300),bool),
        part_class='blue_2x2',reason='color_missing_or_conflict',layer=None)])
    assert texts == ['color? 2x2 | XY:? | L:?']


def test_geometry_and_explicit_layer_reference(monkeypatch):
    from perception_mvp.integrated_view import measure_instance
    from perception_mvp import opencv_live
    monkeypatch.setattr(opencv_live, 'rgb_top_quad', lambda *args: np.zeros((4, 2)))
    monkeypatch.setattr('perception_mvp.integrated_view.corners_at_height',
        lambda *args: np.array([[59.5, 59.5], [93.5, 59.5], [93.5, 93.5], [59.5, 93.5]]))
    rgb = np.full((30, 30, 3), 200, np.uint8)
    mask = np.ones((30, 30), bool)
    depth = np.full((30, 30), 800, np.uint16)
    k = [[100., 0., 15.], [0., 100., 15.], [0., 0., 1.]]
    info = dict(width=30, height=30, k=np.array(k).ravel(), d=[0.]*5, distortion_model='plumb_bob')
    calibration = dict(independently_validated=True, image_size=[30, 30], pitch_mm=17,
        intrinsics=dict(camera_matrix=k), camera_pose=dict(R_camera_from_board=np.eye(3),
        t_camera_from_board_mm=[0, 0, 822], height_normal_sign=-1))
    result = measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration, [22, 42, 62, 82], 2)
    assert result['grid'] == [4, 4]
    assert result['height_mm'] == 22
    assert result['layer'] == 1 and result['reason'] is None
    result = measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration)
    assert result['layer'] is None and result['reason'] == 'layer_reference_missing'
    with pytest.raises(ValueError, match='overlapping'):
        measure_instance(rgb, mask, 'yellow_2x2', depth, info, calibration, [22, 42, 62, 82], 11)
