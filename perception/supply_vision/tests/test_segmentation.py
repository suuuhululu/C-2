from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from supply_vision.main import infer
from supply_vision.seg_geometry import geometry_from_mask
from test_centers import SETTINGS


class Tensor:
    def __init__(self, values): self.values = np.asarray(values)
    def cpu(self): return self
    def numpy(self): return self.values


def test_adapter_preserves_mask_and_rejects_missing_mask():
    mask = np.zeros((1,80,100),np.uint8)
    mask[0,20:61,30:81] = 1
    boxes = SimpleNamespace(xyxy=Tensor([[30,20,81,61]]), cls=Tensor([0]), conf=Tensor([.9]))
    result = SimpleNamespace(boxes=boxes,masks=SimpleNamespace(data=Tensor(mask)))
    class Model:
        names = {0:'blue_2x3'}
        def predict(self,*args,**kwargs):
            assert kwargs['retina_masks'] is True
            return [result]
    detection = infer(Model(), np.zeros((80,100,3),np.uint8), .2)[0]
    assert detection['class_name'] == 'blue_2x3'
    g = geometry_from_mask(detection['mask_contours_uv'],'blue_2x3',0,SETTINGS)
    np.testing.assert_allclose(g['center_uv'],[55,40])
    result.masks = None
    with pytest.raises(RuntimeError,match='missing segmentation masks'):
        infer(Model(),np.zeros((80,100,3),np.uint8),.2)


def test_rotated_mask_center_long_edge_and_grasp_pair():
    corners = cv2.boxPoints(((100,80),(60,30),30)).tolist()
    a = geometry_from_mask([corners],'blue_2x3',0,SETTINGS)
    b = geometry_from_mask([corners],'blue_2x3',1,SETTINGS)
    np.testing.assert_allclose(a['center_uv'],[100,80],atol=.001)
    assert a['orientation_deg'] == pytest.approx(30,abs=.001)
    assert np.linalg.norm(np.subtract(*a['grasp_midpoints_uv'])) == pytest.approx(30,abs=.001)
    assert np.linalg.norm(np.subtract(*b['grasp_midpoints_uv'])) == pytest.approx(60,abs=.001)


def test_mask_perspective_center_and_square_equivalence():
    corners = [[20,20],[120,20],[90,100],[40,100]]
    g = geometry_from_mask([corners],'yellow_2x2',0,SETTINGS)
    np.testing.assert_allclose(g['center_uv'],[66.666667,73.333333],atol=.001)
    assert g['orientation_period_deg'] == 90


@pytest.mark.parametrize('contours,clipped,reason',[
    ([],False,'missing_or_ambiguous'),
    ([[[10,10],[40,10],[40,40],[10,40]]],True,'surface_clipped'),
    ([[[10,10],[40,10],[40,40],[10,40]],[[50,50],[80,50],[80,80],[50,80]]],False,'ambiguous'),
    ([[[10,10],[60,10],[60,30],[30,30],[30,60],[10,60]]],False,'four_corners')])
def test_unreliable_mask_held(contours,clipped,reason):
    with pytest.raises(ValueError,match=reason):
        geometry_from_mask(contours,'blue_2x3',0,SETTINGS,clipped)
