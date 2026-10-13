from copy import deepcopy

import numpy as np
import pytest

from supply_vision.request_session import SupplyRequestSession
from test_centers import SETTINGS


@pytest.fixture
def prepared(monkeypatch):
    config={'image_size':[200,180], 'view_id':'SUPPLY_VIEW','config_id':'v1',
            'calibration_id':'c1','rgb_topic':'/camera/color/image_raw',
            'confidence':.8,'candidate_confidence':.2,'surface':SETTINGS,
            'slots':[{'brick_type':'2x3x1','color':'blue','slot':1,
                      'grasp_edge_pair':0,'roi_xyxy':[10,10,150,150]}]}
    request={'request_id':'r1','step_id':'s1','mode':'TEST','brick_type':'2x3x1',
             'color':'blue','view_id':'SUPPLY_VIEW','config_id':'v1',
             'slot_id':'blue_2x3x1_01','stopped':True,'not_before_ns':100,'expires_at_ns':200}
    clock=[120]
    session=SupplyRequestSession(None,config,lambda:clock[0])
    monkeypatch.setattr('supply_vision.request_session.process',lambda *args:
                        {'status':'HOLD','candidates':[],'scope':'LOCAL_ONLY'})
    return session,request,clock


def test_result_once(prepared):
    session,request,clock=prepared
    session.submit(request)
    result=session.observe('r1',np.zeros((180,200,3),np.uint8),110)
    assert result['mode']=='TEST'
    with pytest.raises(ValueError,match='not_active'):
        session.observe('r1',np.zeros((180,200,3),np.uint8),110)
    with pytest.raises(ValueError,match='closed'):
        session.submit(request)


def test_cancel_closes_request(prepared):
    session,request,clock=prepared;session.submit(request)
    assert session.cancel('r1')['status']=='CANCELLED'
    with pytest.raises(ValueError,match='not_active'):
        session.observe('r1',np.zeros((180,200,3),np.uint8),110)


@pytest.mark.parametrize('stamp',[100,99,121])
def test_old_future_frame_rejected_without_closing(prepared,stamp):
    session,request,clock=prepared;session.submit(request)
    with pytest.raises(ValueError,match='frame'):
        session.observe('r1',np.zeros((180,200,3),np.uint8),stamp)
    assert session.cancel('r1')['status']=='CANCELLED'


def test_expire_and_busy(prepared):
    session,request,clock=prepared;session.submit(request)
    other=deepcopy(request);other['request_id']='r2'
    with pytest.raises(ValueError,match='busy'):session.submit(other)
    clock[0]=200
    assert session.expire('r1')['status']=='TIMEOUT'


@pytest.mark.parametrize('mode',[None,'','FAKE'])
def test_mode_not_default_real(prepared,mode):
    session,request,clock=prepared;request['mode']=mode
    with pytest.raises(ValueError,match='mode'):session.submit(request)


def test_cancel_during_inference(prepared,monkeypatch):
    session,request,clock=prepared;session.submit(request)
    def inference(*args):
        session.cancel('r1')
        return {'status':'CANDIDATES'}
    monkeypatch.setattr('supply_vision.request_session.process',inference)
    with pytest.raises(ValueError,match='not_active'):
        session.observe('r1',np.zeros((180,200,3),np.uint8),110)
    other=deepcopy(request);other['request_id']='r2'
    assert session.submit(other)['status']=='WAITING_FOR_RGB'


def test_expiry_during_inference(prepared,monkeypatch):
    session,request,clock=prepared;session.submit(request)
    def inference(*args):clock[0]=200;return {'status':'CANDIDATES'}
    monkeypatch.setattr('supply_vision.request_session.process',inference)
    with pytest.raises(ValueError,match='expired_during'):
        session.observe('r1',np.zeros((180,200,3),np.uint8),110)


def test_inference_error_preserved(prepared,monkeypatch):
    session,request,clock=prepared;session.submit(request)
    def inference(*args):raise RuntimeError('model_failure')
    monkeypatch.setattr('supply_vision.request_session.process',inference)
    with pytest.raises(RuntimeError,match='model_failure'):
        session.observe('r1',np.zeros((180,200,3),np.uint8),110)
    with pytest.raises(ValueError,match='closed'):session.submit(request)
