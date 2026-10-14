import numpy as np
import pytest

from supply_vision.main import block_class, slot_id, process
from test_request_session import prepared


def test_weights_resolve_from_config_relative_to_config_file(tmp_path):
    from supply_vision.main import resolve_weights
    config_path = tmp_path / 'cfg' / 'supply.json'
    assert resolve_weights({'weights': '../m/best.pt'}, config_path) == (tmp_path / 'm' / 'best.pt').resolve()
    assert resolve_weights({'weights': '/abs/best.pt'}, config_path).as_posix() == '/abs/best.pt'
    assert resolve_weights({'weights': 'ignored.pt'}, config_path, 'override.pt').name == 'override.pt'


@pytest.mark.parametrize('config', [{}, {'weights': ''}, {'weights': None}])
def test_missing_weights_rejected_without_default(config, tmp_path):
    from supply_vision.main import resolve_weights
    with pytest.raises(ValueError):
        resolve_weights(config, tmp_path / 'supply.json')


def test_red_d_type_maps_without_changing_trained_class():
    assert block_class('red','1x2x1') == 'red_2x1'
    assert slot_id({'color':'red','brick_type':'1x2x1','slot':6}) == 'red_1x2x1_06'
    with pytest.raises(ValueError):
        block_class('red','2x1x1')


@pytest.mark.parametrize('field,value',[('view_id','V0'),('slot_id',None),
    ('slot_id','blue_2x3x1_07'),('slot_id','yellow_2x3x1_01')])
def test_invalid_view_or_reservation_rejected(prepared,field,value):
    session,request,_=prepared
    request[field]=value
    with pytest.raises(ValueError):
        session.submit(request)


def test_other_slot_candidate_not_returned(monkeypatch):
    from test_centers import SETTINGS
    config={'image_size':[200,180],'view_id':'SUPPLY_VIEW','config_id':'v1',
            'calibration_id':'test','surface':SETTINGS,'confidence':.8,
            'slots':[{'brick_type':'2x3x1','color':'blue','slot':n,
                      'grasp_edge_pair':0,'roi_xyxy':roi}
                     for n,roi in [(1,[10,10,90,150]),(2,[100,10,190,150])]]}
    request={'request_id':'r','step_id':'s','view_id':'SUPPLY_VIEW','config_id':'v1',
             'stopped':True,'not_before_ns':100,'expires_at_ns':200,
             'brick_type':'2x3x1','color':'blue','slot_id':'blue_2x3x1_01'}
    monkeypatch.setattr('supply_vision.main.infer_color_candidates',lambda *a:[
        {'box':[110,20,170,100],'confidence':.9,'class_name':'blue_2x3',
         'mask_contours_uv':[[[110,20],[170,20],[170,100],[110,100]]]}])
    monkeypatch.setattr('supply_vision.seg_geometry.geometry_from_mask',
                        lambda *a: pytest.fail('unrequested geometry must not be calculated'))
    result=process(np.zeros((180,200,3),np.uint8),None,config,request,150)
    assert result['status']=='HOLD'
    assert result['candidates']==[]
    assert len(result['slots']) == 1
    assert result['slots'][0]['slot_id'] == 'blue_2x3x1_01'
    assert result['slots'][0]['geometry'] is None
    assert result['slot_id']=='blue_2x3x1_01'
    assert result['view_id']=='SUPPLY_VIEW'
    assert 'observation_id' not in result
