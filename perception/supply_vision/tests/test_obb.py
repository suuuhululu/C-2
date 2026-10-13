import sys
from types import SimpleNamespace

import numpy as np
import pytest

from supply_vision.obb_geometry import geometry_from_obb
from supply_vision.main import infer, load_model


def test_rotated_center_midpoints_and_angle():
    g = geometry_from_obb([100,80,60,30,np.pi/6],'blue_2x3',0)
    np.testing.assert_allclose(g['center_uv'],[100,80])
    np.testing.assert_allclose(np.mean(g['corners_uv'],axis=0),[100,80])
    np.testing.assert_allclose(np.mean(g['grasp_midpoints_uv'],axis=0),[100,80])
    assert g['orientation_deg'] == pytest.approx(30)
    assert g['orientation_period_deg'] == 180


def test_swapped_width_angle_same_long_axis():
    a=geometry_from_obb([100,80,60,30,.3],'blue_2x3',0)
    b=geometry_from_obb([100,80,30,60,.3-np.pi/2],'blue_2x3',0)
    np.testing.assert_allclose(a['corners_uv'],b['corners_uv'],atol=1e-8)
    assert a['orientation_deg'] == pytest.approx(b['orientation_deg'])


def test_square_equivalence_explicit():
    a=geometry_from_obb([50,50,30,30,.2],'yellow_2x2',0)
    b=geometry_from_obb([50,50,30,30,.2+np.pi/2],'yellow_2x2',0)
    assert a['orientation_deg'] == pytest.approx(b['orientation_deg'])
    assert a['orientation_period_deg'] == 90
    assert a['orientation_basis'] == 'square_equivalent_axes'


@pytest.mark.parametrize('values',[[0,0,0,2,0],[0,0,2,-1,0],[0,0,2,1,float('nan')]])
def test_invalid_obb(values):
    with pytest.raises(ValueError):
        geometry_from_obb(values,'blue_2x3',0)


@pytest.mark.parametrize('task',['detect','obb'])
def test_non_segment_model_rejected(monkeypatch,tmp_path,task):
    weights=tmp_path/'best.pt';weights.write_bytes(b'fixture')
    monkeypatch.setitem(sys.modules,'ultralytics',SimpleNamespace(YOLO=lambda path:SimpleNamespace(task=task)))
    with pytest.raises(ValueError,match='segmentation model required'):
        load_model(weights)
