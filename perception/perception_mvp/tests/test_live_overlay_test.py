"""Synthetic state test with real-time RGB projection interface, no device motion."""
import numpy as np
import pytest
from perception_mvp.live_view import live_overlay_test_payload
from perception_mvp.visualization import render_comparison_overlay


def inputs():
    k = [[500.,0.,200.],[0.,500.,160.],[0.,0.,1.]]
    calibration = dict(independently_validated=True,image_size=[400,320],view_id='V0',
        pitch_mm=16.,intrinsics=dict(camera_matrix=k),camera_pose=dict(
            R_camera_from_board=np.diag([1.,-1.,-1.]).tolist(),
            t_camera_from_board_mm=[-40.,40.,600.],height_normal_sign=1))
    info = dict(width=400,height=320,k=np.array(k).ravel().tolist(),distortion_model='plumb_bob',d=[0.]*5)
    reference = dict(top_heights_mm=[22.,40.625,59.25,77.875],height_reference_offset_mm=4.)
    return calibration, info, (320,400,3), reference


def test_live_test_uses_actual_stamp_and_flat_datum_without_changing_calibration():
    args = inputs()
    payload = live_overlay_test_payload(*args, [2,2], 'OBSERVING', 123)
    camera = np.linalg.inv(payload['projection']['camera_to_board'])
    assert camera[2,3] == pytest.approx(.604)
    assert args[0]['camera_pose']['t_camera_from_board_mm'][2] == 600.
    assert payload['frame_stamp_ns'] == 123
    assert payload['state']['check_id'] == 'LOCAL-SYNTHETIC-TEST'
    rgb = np.zeros((320,400,3),np.uint8)
    _, report = render_comparison_overlay(rgb,payload,view='V0',frame_stamp_ns=123,
                                         stopped=True,hand_clear=True)
    assert report['overlay_visible']
    after = live_overlay_test_payload(*args,[2,2],'CONFIRMED',124)
    assert len(after['state']['current']['blocks']) == 3


def test_live_test_rejects_wrong_intrinsics():
    args = inputs()
    args[1]['k'][0] = 600.
    with pytest.raises(ValueError,match='intrinsics'):
        live_overlay_test_payload(*args,[2,2],'OBSERVING',123)


def test_live_test_rejects_outside_board_anchor():
    with pytest.raises(ValueError,match='footprint'):
        live_overlay_test_payload(*inputs(),[23,23],'OBSERVING',123)
