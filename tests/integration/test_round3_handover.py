"""Existing delivery runner with synthetic feedback; ROS/Modbus never connect."""
from contextlib import contextmanager
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import round3_service as service
from app import round3_handover as handover
from test_round3_service import state


@pytest.fixture
def item():
    design=dict(design_version=1,blocks=[dict(brick_type='2x3x1',color='blue',x=11,y=11,layer=1,orientation_deg=0),
        dict(brick_type='2x3x1',color='yellow',x=11,y=11,layer=2,orientation_deg=90)])
    settings=service.service_settings()
    whole,result,bundle=service.plan_design(design,dict(current_revision=0,blocks=[]),settings,str(uuid4()),1)
    case=dict(step_id=bundle['plan']['steps'][1]['step_id'],target=design['blocks'][1],supply_slot=1,human_hold=False)
    prepared,binding=service.prepare_step(whole,result,dict(current_revision=1,blocks=[design['blocks'][0]]),1,case,settings,state())
    assert binding['assessment']['action_proposal']['mode']=='HUMAN_ASSEMBLY'
    return prepared


@pytest.mark.parametrize('failure',[None,'delivery','stop','home','width'])
@pytest.mark.parametrize('release_feedback',[40.,50.3,80.])
def test_existing_tray_release_retreat_then_home_or_hold_without_assembly(item,tmp_path,monkeypatch,failure,release_feedback):
    trial=service.stack.native()
    from app import assembly_step_runner as runner
    raw=runner.StepReplayDriver(item['handover']['profile']['place_pose'],reaction_force_n=40.)
    raw.config=dict(timing={});events=[];confirmations=[]
    original_grip=raw.command_gripper
    def grip(width,force):
        original_grip(width,force)
        raw.value['gripper_width_mm']=80.1 if failure=='width' else release_feedback
    raw.command_gripper=grip
    @contextmanager
    def opened(*a):
        def confirm(check,view,*a,**kw):
            confirmations.append(check)
            return dict(stopped_verified=failure!='home' or check!='HANDOVER_HOME')
        yield SimpleNamespace(raw=raw,confirm=confirm)
    class Vision:
        def __init__(self,*a):pass
        def observe(self,*a):return {}
        def display(self,*a):pass
        def pump_sleep(self,*a):pass
        def finalize_depth(self,*a):pass
        def close(self):pass
    pickups=[]
    def pickup(driver,cfg,record,observe,**kwargs):
        assert kwargs['hold_at_pickup'] and kwargs['start_zone']=='home'
        pickups.append(True);driver.value.update(posx=deepcopy(cfg['blocks'][0]['pickup_pose']),gripper_status=2,gripper_width_mm=40.)
    original=runner.run_step
    def run(*args,**kw):
        if failure in ('delivery','stop'):raise RuntimeError('EXPLICIT_DELIVERY_FAILURE')
        if failure=='width':
            now=[0.]
            def clock():now[0]+=.1;return now[0]
            return original(*args,**kw,sleep=lambda _:None,clock=clock)
        return original(*args,**kw,sleep=lambda _:None)
    if failure=='stop':
        def stop():raise RuntimeError('EXPLICIT_STOP_FAILURE')
        raw.stop=stop
    monkeypatch.setattr(handover,'open_motion',opened)
    monkeypatch.setattr(trial.supply,'LiveVision',Vision)
    monkeypatch.setattr(trial.supply,'execute',pickup)
    monkeypatch.setattr(runner,'run_step',run)
    def record(event,data):events.append((event,data))
    if failure:
        with pytest.raises((ValueError,RuntimeError,TimeoutError)):
            handover.execute(item,tmp_path/'run',record,{},'explicit-mock-review',Event())
        if failure!='home':assert confirmations==['HANDOVER_START']
        if failure=='stop':assert any(e=='STOP_FAILED' and d['actual_stop_verified'] is False for e,d in events)
        if failure=='width':
            release=next(i for i,(e,d) in enumerate(events) if e=='GRIPPER_REQUEST')
            assert not any(e=='STEP_MOVE' for e,d in events[release:])
    else:
        result=handover.execute(item,tmp_path/'run',record,{},'explicit-mock-review',Event())
        assert result['status']=='PLACE_BOARD_DELIVERED_HOME_RETURNED'
        assert not result['assembly_completion'] and not result['current_update'] and not result['human_assembly_confirmed']
        assert result['released'] and result['actual_stop_verified'] and result['writer_released']
        labels=[d['label'] for e,d in events if e=='STEP_MOVE']
        assert all(label in labels for label in ['SUPPLY_20_0','BODY_BYPASS','PLACE_BOARD','TRAY_APPROACH_20MM'])
        assert 'TARGET_APPROACH_20MM' not in labels
        assert raw.grips==[(53.,item['config']['gripper_force_n'])]
        assert confirmations==['HANDOVER_START','HANDOVER_HOME']
        assert all(d['feedback_range_mm']==[40.,80.] for e,d in events if e=='GRIPPER_REQUEST')
    assert pickups==[True]


def test_new_handover_phase_cannot_execute_robot_assembly_or_old_held_phase(item):
    service.stack.native()
    from app.assembly_step_bridge import validate_physical,build_plan
    from app.assembly_step_runner import run_step,StepReplayDriver
    value=deepcopy(item['handover']);profile=value['profile']
    profile['physical_route_reviewed']=True
    for s in profile['steps'].values():s['physical_reference_reviewed']=True
    plan=build_plan(value['step'],profile)
    with pytest.raises(ValueError,match='HELD_ASSEMBLY_REQUIRES_UNASSISTED_ROBOT_GRIP'):
        validate_physical(plan,profile,'assemble-held')
    wrong=deepcopy(plan);wrong['mode']='ROBOT_GRIP'
    with pytest.raises(ValueError,match='REVIEWED_PLACE_BOARD_HANDOVER_REQUIRED'):
        validate_physical(wrong,profile,'handover-held')
    driver=StepReplayDriver(profile['place_pose'])
    with pytest.raises(ValueError,match='HANDOVER_HELD_REQUIRES_PLACE_BOARD_MANUAL_DELIVERY'):
        run_step(driver,{},plan,profile,lambda *a:True,lambda *a:None,phase='handover-held',start_zone='assembly')
    assert not driver.moves and not driver.grips
