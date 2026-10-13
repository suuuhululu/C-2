"""Recorded S06 feedback and slot-cycle replay; no physical controller simulation."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.assembly_blend_trial import run_blend
from app.assembly_step_runner import StepReplayDriver
from app.integration_runtime import StepRuntime
from scripts.robot_integration_fixture import document
from test_auto_handover_blend import blend_state, CONNECTION
from test_integration_runtime import Clock, signal


TRANSIT = dict(relaxed_constraints=True,transit_position_tolerance_mm=10.,
    transit_orientation_tolerance_deg=5.,corridor_margin_mm=40.,timeout_floor_s=45.,finish_endpoint=True)
RECORDED = json.loads((Path(__file__).parent/'fixtures/blend-slot6-20261013.json').read_text())


def recorded_trial(expanded=True):
    d,p,raw,events,clock,_=blend_state()
    p['noncontact_force_guard']=False
    p['transport_blending'].update(radius_mm=40.,relaxed_constraints=True)
    if expanded:p['transport_blending'].update(TRANSIT)
    raw.value.update(posx=RECORDED['start'].copy(),gripper_status=0,gripper_width_mm=56.4)
    original=raw.move_blending_async
    def move(*args):
        original(*args)
        raw.value['posx']=RECORDED['stopped'].copy()
    raw.move_blending_async=move
    return d,p,raw,events,clock,deepcopy(RECORDED['targets'])


def execute(state):
    d,p,raw,events,clock,points=state
    return run_blend(d,CONNECTION,points,p,d.session.record,held=0,clock=clock,sleep=clock.sleep)


def test_recorded_slot6_with_old_arrival_policy_reproduces_timeout():
    state=recorded_trial(False)
    with pytest.raises(TimeoutError,match='BLEND_MOTION_TIMEOUT'):execute(state)
    assert len(state[2].blends)==1 and state[2].stops==1 and not state[2].grips


def test_recorded_slot6_finishes_unchanged_endpoint_once_without_waypoint_replay():
    state=recorded_trial();d,p,raw,events,clock,points=state
    sample=execute(state)
    assert sample['posx']==points[-1] and raw.moves==[*points,points[-1]]
    assert len(raw.blends)==1 and not raw.grips and not raw.stops
    transit=next(v for e,v in events if e=='BLEND_TRANSIT_COMPLETE')
    assert 6.<transit['position_error_mm']<6.3
    final=next(v for e,v in events if e=='BLEND_COMPLETE')
    assert final['endpoint_verified'] and final['endpoint_finish_sent']
    assert final['position_tolerance_mm']==1.
    assert clock.t<5.


@pytest.mark.parametrize('fault',['finish_short','far','robot','grip','stale','invalid_force'])
def test_failed_or_invalid_endpoint_never_authorizes_pickup(fault):
    state=recorded_trial();d,p,raw,events,clock,points=state
    if fault=='finish_short':
        move=raw.move_line_async
        def finish(*args):
            move(*args);raw.value['posx'][0]+=2.
        raw.move_line_async=finish
    else:
        move=raw.move_blending_async
        def broken(*args):
            move(*args)
            if fault=='far':raw.value['posx'][0]+=20.
            if fault=='robot':raw.value['robot_state']=3
            if fault=='grip':raw.value['gripper_status']=2
            if fault=='stale':raw.value['query_duration_s']=1.
            if fault=='invalid_force':raw.value['wrench'][0]=float('nan')
        raw.move_blending_async=broken
    with pytest.raises((RuntimeError,ValueError,TimeoutError)):execute(state)
    assert not any(e=='BLEND_COMPLETE' for e,v in events)
    assert raw.stops>=1 and not raw.grips
    assert len([v for e,v in events if e=='MOVE_REQUEST' and v['segment']=='BLEND_ENDPOINT_FINISH'])==(1 if fault=='finish_short' else 0)
    if fault=='far':assert clock.t>=45.


@pytest.mark.parametrize('offset,success',[(60.,True),(81.,False)])
def test_intermediate_corridor_allows_reviewed_margin_but_not_unbounded_drift(offset,success):
    d,p,raw,events,clock,points=recorded_trial()
    # The intermediate sample is outside the old 40.5 mm corridor. The final
    # sample returns to the recorded destination; it must not be skipped.
    move=raw.move_blending_async;sample=raw.sample;pending=[]
    def command(*args):
        move(*args)
        value=sample();value['posx']=[*points[0][:2],points[0][2]+offset,*points[0][3:]]
        value.update(motion_status=1,velx=[1.,0.,0.,0.,0.,0.]);pending.append(value)
    raw.move_blending_async=command
    raw.sample=lambda:pending.pop(0) if pending else sample()
    state=d,p,raw,events,clock,points
    if success:assert execute(state)['posx']==points[-1]
    else:
        with pytest.raises(RuntimeError,match='BLEND_LEFT_REVIEWED_CORRIDOR'):execute(state)
        assert not any(e=='BLEND_TRANSIT_COMPLETE' for e,v in events)


def test_exact_blend_arrival_does_not_add_endpoint_command():
    state=recorded_trial();raw=state[2]
    raw.move_blending_async=StepReplayDriver.move_blending_async.__get__(raw)
    execute(state)
    assert raw.moves==state[-1]
    assert not any(e=='BLEND_TRANSIT_COMPLETE' for e,v in state[3])


@pytest.mark.parametrize('kind,color',[('2x2x1','yellow'),('2x2x1','blue'),('2x3x1','yellow'),('2x3x1','blue')])
@pytest.mark.parametrize('mode,assistance',[('ROBOT_GRIP','NONE'),('HUMAN_ASSEMBLY','MANUAL_ASSEMBLY')])
def test_near_stopped_blend_runs_slots_1_through_6_then_1_for_robot_and_human(kind,color,mode,assistance):
    doc=document(brick_type=kind,color=color,mode=mode,assistance=assistance)
    p=doc['d_profile'];p.update(continuous_transport=True,empty_return_skip_place=True,
        noncontact_force_guard=False,motion_position_tolerance_mm=1.,motion_orientation_tolerance_deg=1.)
    p['transport_blending']=dict(reviewed=True,radius_mm=40.,**TRANSIT)
    doc['session']['stillness'].update(linear_mm_s=5.,angular_deg_s=5.,position_mm=1.,orientation_deg=1.)
    raw=StepReplayDriver(p['steps']['fake/S01']['reference_pose']);clock=Clock();events=[]
    rt=StepRuntime(raw,CONNECTION,lambda e,v:events.append((e,deepcopy(v))),clock=clock,sleep=clock.sleep)
    blend=raw.move_blending_async
    def near(*args):
        blend(*args);raw.value['posx'][0]+=6.2
    raw.move_blending_async=near
    def respond():
        if rt.request:
            if rt.request['kind']=='RECEIVE':signal(rt,hand_present=False,receiving_ready=False)
            else:signal(rt,ready=True)
    clock.hook=respond
    previous=None
    for index,slot in enumerate([1,2,3,4,5,6,1]):
        if index:rt.inspection(dict(plan_id=rt.plan['plan_id'],step_id=rt.plan['step_id'],
            execution_id=rt.session.value['execution_id'],decision='KEEP',current={}))
        doc['session']['execution_id']=str(uuid4())
        doc['step']['reservation']['slot_id']=f'{color}_{kind}_{slot:02}'
        pickup=p['steps']['fake/S01']['pickup_pose'];pickup[0]=-300.-(slot-1)*60.
        rt.start(doc['step'],p,doc['session'])
        before=len(raw.blends);event_start=len(events)
        result=rt.run()
        assert result['status']=='AWAITING_INSPECTION',result
        assert raw.blends[before]['targets'][-1][:2]==pickup[:2]
        if previous is not None:assert previous not in [point[:2] for point in raw.blends[before]['targets']]
        step_events=events[event_start:]
        finished=[v for e,v in step_events if e=='BLEND_COMPLETE']
        assert len(finished)==len(raw.blends)-before and all(v['endpoint_finish_sent'] for v in finished)
        final_pick=next(v for e,v in step_events if e=='MOVE_SUCCEEDED' and v['label']=='PICKUP_LOWER')
        assert final_pick['sample']['posx'][:2]==pickup[:2]
        previous=pickup[:2].copy()
    assert len(raw.grips)==21


@pytest.mark.parametrize('change',[dict(transit_position_tolerance_mm=float('nan')),
    dict(transit_orientation_tolerance_deg=-1.),dict(corridor_margin_mm=-1.),
    dict(timeout_floor_s=True),dict(finish_endpoint=False)])
def test_invalid_expanded_criteria_never_dispatch_motion(change):
    state=recorded_trial();state[1]['transport_blending'].update(change)
    with pytest.raises(ValueError,match='INVALID_BLEND_TRANSIT_TOLERANCES'):execute(state)
    assert not state[2].moves and not state[2].grips


def test_final_move_accepts_small_feedback_error_without_repeated_finish():
    state=recorded_trial();raw=state[2];move=raw.move_line_async
    def small_error(*args):
        move(*args);raw.value['posx'][0]+=.4
    raw.move_line_async=small_error
    sample=execute(state)
    assert sample['posx'][0]==state[-1][-1][0]+.4
    assert len([v for e,v in state[3] if e=='MOVE_REQUEST' and v['segment']=='BLEND_ENDPOINT_FINISH'])==1
