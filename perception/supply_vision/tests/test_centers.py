import cv2
import numpy as np
import pytest

from supply_vision.top_surface import quad_geometry, top_geometry
from supply_vision.main import process

SETTINGS = {'minimum_area': 100, 'approx_fraction': .02, 'minimum_fill': .9,
            'hsv_ranges': {'yellow': [[[18,80,60],[40,255,255]]],
                           'blue': [[[95,80,25],[135,255,255]]],
                           'red': [[[0,80,40],[10,255,255]],[[170,80,40],[179,255,255]]]}}


def test_perspective_midpoint_not_pixel_average():
    quad = np.float32([[20,20],[120,20],[90,100],[40,100]])
    geometry = quad_geometry(quad, 0)
    # Projective rectangle center is intersection of diagonals, not vertex mean.
    np.testing.assert_allclose(geometry['center_uv'], [66.666667,73.333333], atol=.001)
    np.testing.assert_allclose(geometry['grasp_midpoints_uv'], [[70,20],[65,100]], atol=.001)


def test_color_surface_center():
    frame = np.zeros((180,200,3),np.uint8)
    cv2.rectangle(frame,(40,30),(120,130),(255,0,0),-1)
    geometry = top_geometry(frame,[35,25,125,135],'blue',1,SETTINGS)
    np.testing.assert_allclose(geometry['center_uv'], [80,80], atol=.01)
    np.testing.assert_allclose(geometry['grasp_midpoints_uv'], [[120,80],[40,80]], atol=.01)


def test_clipped_surface_rejected():
    frame = np.full((100,100,3),(255,0,0),np.uint8)
    with pytest.raises(ValueError, match='clipped'):
        top_geometry(frame,[0,0,100,100],'blue',0,SETTINGS)


def test_two_regions_rejected():
    frame = np.zeros((150,150,3),np.uint8)
    cv2.rectangle(frame,(20,20),(50,60),(255,0,0),-1)
    cv2.rectangle(frame,(80,20),(110,60),(255,0,0),-1)
    with pytest.raises(ValueError, match='ambiguous'):
        top_geometry(frame,[10,10,120,80],'blue',0,SETTINGS)


def test_request_gate_before_inference():
    config = {'image_size':[150,150], 'observation_id':'supply', 'config_id':'v1'}
    request = {'observation_id':'supply','config_id':'v1','stopped':True,
               'not_before_ns':100,'expires_at_ns':200}
    frame = np.zeros((150,150,3),np.uint8)
    for stamp in (99,100,201):
        with pytest.raises(ValueError, match='time window'):
            process(frame,None,config,request,stamp)
    request['stopped'] = False
    with pytest.raises(ValueError, match='stop'):
        process(frame,None,config,request,150)


def test_pipeline_candidate_and_no_detection(monkeypatch):
    import supply_vision.main as module
    config = {'image_size':[200,180], 'observation_id':'supply','config_id':'v1',
              'calibration_id':'draft1','confidence':.8,'candidate_confidence':.2,
              'surface':SETTINGS, 'slots':[{'brick_type':'2x3x1','color':'blue','slot':3,
               'grasp_edge_pair':1,'roi_xyxy':[10,10,150,150]}]}
    request = {'request_id':'r1','step_id':'step1','observation_id':'supply',
               'config_id':'v1','stopped':True,'not_before_ns':100,'expires_at_ns':200,
               'brick_type':'2x3x1','color':'blue'}
    frame = np.zeros((180,200,3),np.uint8)
    cv2.rectangle(frame,(40,30),(120,130),(255,0,0),-1)
    monkeypatch.setattr(module,'infer',lambda *a:[{'box':[35,25,125,135],
                        'class_name':'blue_2x3','confidence':.9}])
    result = process(frame,None,config,request,150)
    assert result['status'] == 'CANDIDATES'
    assert result['candidates'][0]['slot'] == 3
    assert result['units'] == 'pixel'
    monkeypatch.setattr(module,'infer',lambda *a:[])
    result = process(frame,None,config,request,160)
    assert result['status'] == 'HOLD'
    assert not result['candidates']
