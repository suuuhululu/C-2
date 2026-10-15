"""B plus the real stdio adapter; D and camera samples are explicit fixtures."""
import json
from queue import Queue

import pytest

from app import round3_live_inspection as live
from app import round3_initial_inspection as initial
from perception.perception_mvp.team_connection import connect_inspection
from test_round3_initial_inspection import install


def make(tmp_path, monkeypatch, fault='normal'):
    settings, cancelled, motion = install(tmp_path, monkeypatch, fault)
    monkeypatch.setattr(live, 'open_motion', initial.open_motion)
    monkeypatch.setattr(live, 'DockerBObserver', initial.DockerBObserver)
    observer = live.LiveInspectionObserver(tmp_path, settings, tmp_path/'logs/camera', 'TEST_OPERATOR')
    inbox = Queue()
    base = dict(current_revision=0, blocks=[])
    block = dict(brick_type='2x2x1',color='blue',x=6,y=6,layer=1,orientation_deg=0)
    plan = dict(plan_id='plan',design_version=1,base_current_revision=0,steps=[dict(
        step_id='step',operation='PLACE',before=None,after=block,prerequisites=[],requires_delivery=True)])
    b = connect_inspection(inbox.put, initial_current=base, geometry_reference='TEST_GEOMETRY',
        observe=lambda context, valid:observer(context, lambda:valid() and not cancelled.is_set()))
    b.load_plan(dict(design_version=1,blocks=[block]),plan,base,geometry_reference='TEST_GEOMETRY')
    return observer, inbox, motion, b


def test_step_then_separate_final_use_real_b_owner_and_release_d_before_result(tmp_path, monkeypatch):
    observer, inbox, motion, b = make(tmp_path, monkeypatch)
    try:
        for kind in ('STEP', 'FINAL'):
            b.request(dict(check_id=kind,check_kind=kind,plan_id='plan',step_id='step' if kind=='STEP' else None))
            result = inbox.get(timeout=5)
            assert result['status']=='OK' and result['comparison']=='MATCH'
            assert result['current']['current_revision']==1
            assert motion.released and observer.outcomes[kind]['writer_released']
            assert observer.outcomes[kind]['home_return_verified']
            assert json.loads((observer.output/kind/'d-result.json').read_text())['status']=='CAPTURED_HOME_RETURNED'
        assert motion.views==['START_HOME','V0','D1','D3','HOME']*2 and motion.stops==0
    finally:b.close()


@pytest.mark.parametrize('fault', ['d3_motion', 'home', 'wrong_id', 'cancel', 'handoff'])
def test_camera_or_d_failure_preserves_b_current_and_records_real_stop_boundary(tmp_path, monkeypatch, fault):
    observer, inbox, motion, b = make(tmp_path, monkeypatch, fault)
    try:
        b.request(dict(check_id='check',check_kind='STEP',plan_id='plan',step_id='step'))
        result=inbox.get(timeout=5)
        assert result['status']=='ERROR' and result['current'] is None
        assert b.inspection.current==dict(current_revision=0,blocks=[])
        outcome=observer.outcomes['check']
        assert outcome['status']=='HOLD' and outcome['writer_released'] and outcome['actual_stop_verified']
        assert motion.stops==1
        if fault!='home': assert 'HOME' not in motion.views
        if fault=='handoff':
            assert motion.views==['START_HOME']
            assert not (observer.output/'check'/'cycles').exists()
    finally:b.close()


def test_geometry_failure_never_connects_d(tmp_path, monkeypatch):
    observer, _, motion, b=make(tmp_path, monkeypatch)
    try:
        with pytest.raises(ValueError,match='GEOMETRY'):
            observer(dict(check_id='wrong',check_kind='STEP',geometry_reference='OTHER'),lambda:True)
        assert motion.views==[] and not motion.released
    finally:b.close()
