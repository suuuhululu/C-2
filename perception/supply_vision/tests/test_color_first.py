import cv2
import numpy as np

from supply_vision.main import infer_color_candidates, assign_slots
from test_centers import SETTINGS


def config():
    return {'image_size':[200,180], 'surface':SETTINGS, 'candidate_confidence':.2,
            'slots':[{'brick_type':'2x3x1','color':'blue','slot':1,
                      'grasp_edge_pair':1,'roi_xyxy':[10,10,150,150]}]}


def test_no_color_skips_yolo(monkeypatch):
    def unexpected(*args):
        raise AssertionError('YOLO must not run without OpenCV color candidates')
    monkeypatch.setattr('supply_vision.main.infer', unexpected)
    assert infer_color_candidates(None,np.zeros((180,200,3),np.uint8),config()) == []


def test_original_crop_and_full_image_box(monkeypatch):
    frame = np.zeros((180,200,3),np.uint8)
    cv2.rectangle(frame,(40,30),(120,130),(255,0,0),-1)
    calls = []
    def detector(model, crop, confidence):
        calls.append(crop.copy())
        np.testing.assert_array_equal(crop,frame[27:134,37:124])
        return [{'box':[3,3,84,104],'class_name':'blue_2x3','confidence':.9}]
    monkeypatch.setattr('supply_vision.main.infer',detector)
    detections = infer_color_candidates(None,frame,config())
    assert len(calls) == 1
    assert detections[0]['box'] == [40,30,121,131]
    assert detections[0]['opencv_color'] == 'blue'
    assert not detections[0]['color_mismatch']


def test_color_disagreement_held(monkeypatch):
    frame = np.zeros((180,200,3),np.uint8)
    cv2.rectangle(frame,(40,30),(120,130),(0,255,255),-1)
    monkeypatch.setattr('supply_vision.main.infer',lambda *a:
                        [{'box':[3,3,84,104],'class_name':'blue_2x3','confidence':.9}])
    detections = infer_color_candidates(None,frame,config())
    state = assign_slots(config(),detections,.8)[0]
    assert state['status'] == 'UNKNOWN'
    assert state['reason'] == 'opencv_yolo_color_mismatch'
