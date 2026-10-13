"""Only D argument relay is exercised; no runtime constructor or device/API calls."""
from copy import deepcopy
from queue import Queue
from threading import Event
from types import SimpleNamespace
import pytest
from app.c_design import main as c
from app.mvp_real_trial import FullFeatureRealTrial


@pytest.mark.parametrize('voice',[False,True])
@pytest.mark.parametrize('port',['c.review','c.plan_failure'])
def test_pr30_metadata_and_planning_failure_reach_text_and_voice_calls(monkeypatch,voice,port):
    design=dict(design_version=1,blocks=[])
    failure=dict(failure_code='NO_FEASIBLE_ORDER',redesign_required=True)
    metadata=dict(description='test explanation')
    payload=dict(request_id='test-request',design=design,candidate=design,kind='revised',
        previous_design=design,current=dict(blocks=[]),reason='계획을 찾지 못했습니다.',
        change_reason='계획 변경',design_metadata=metadata,planning_failure=failure)
    calls=[]
    def result(*args,**kwargs):
        calls.append(dict(kwargs));return dict(status='OK',hri_result='KEEP',design=design)
    monkeypatch.setattr(c,'review_design_candidate',result)
    monkeypatch.setattr(c,'run_design_change',result)
    runtime=FullFeatureRealTrial.__new__(FullFeatureRealTrial)
    runtime.c_mode='live';runtime.c_pending=port,deepcopy(payload)
    runtime.workflow=SimpleNamespace(dialogue={});runtime.inbox=Queue()
    runtime.background=lambda p,request,fn:fn(Event())
    assert runtime.answer_voice() if voice else runtime.answer('유지할래')
    assert calls[0]['planning_failure']==failure
    if port=='c.review':assert calls[0]['design_metadata']==metadata
    assert runtime.c_pending is None
