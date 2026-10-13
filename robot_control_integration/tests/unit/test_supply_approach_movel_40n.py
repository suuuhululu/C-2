"""Supply serial MoveL and 40 N reaction stop, with isolated synthetic feedback."""
from copy import deepcopy
from uuid import uuid4
import pytest
from app.assembly_step_runner import StepReplayDriver
from app.integration_runtime import StepRuntime
from scripts.robot_integration_fixture import document
from test_blend_slot6_tolerances import TRANSIT
from test_integration_runtime import Clock, signal
from test_integrated_native_press import setup_native, run, position_reaction


@pytest.mark.parametrize('kind,color', [('2x2x1','yellow'),('2x2x1','blue'),('2x3x1','yellow'),('2x3x1','blue')])
@pytest.mark.parametrize('mode,assistance', [('ROBOT_GRIP','NONE'),('HUMAN_ASSEMBLY','MANUAL_ASSEMBLY')])
def test_supply_movel_slot_cycle_never_blends_empty_or_visits_previous_slot(kind,color,mode,assistance):
    doc=document(brick_type=kind,color=color,mode=mode,assistance=assistance)
    p=doc['d_profile'];p.update(continuous_transport=True,empty_return_skip_place=True,
        supply_approach_blending=False,noncontact_force_guard=False,force_stop_n=40.)
    if mode=='ROBOT_GRIP':
        p['native_press']=dict(enabled=True,force_n=40.,alignment_trial=True,hold_s=3.,
            seek_above_reference_mm=6.,review_ref='SYNTHETIC_40N')
    p['transport_blending']=dict(reviewed=True,radius_mm=40.,**TRANSIT)
    raw=StepReplayDriver(p['steps']['fake/S01']['reference_pose'],reaction_force_n=40.)
    clock=Clock();events=[];blend_grips=[]
    blend=raw.move_blending_async
    def loaded_blend(*args):
        blend_grips.append(raw.value["gripper_status"])
        return blend(*args)
    raw.move_blending_async=loaded_blend
    rt=StepRuntime(raw,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
        lambda e,v:events.append((e,deepcopy(v))),clock=clock,sleep=clock.sleep)
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
        start=len(events)
        rt.start(doc['step'],p,doc['session'])
        assert rt.run()['status']=='AWAITING_INSPECTION'
        rows=events[start:]
        batch=[v for e,v in rows if e=='SINGLE_WRITER_BLEND']
        assert len(batch)==1 and blend_grips[-1]==2
        pick=next(v for e,v in rows if e=='MOVE_SUCCEEDED' and v['label']=='PICKUP_LOWER')
        assert pick['sample']['posx'][:2]==pickup[:2]
        high=next(v for e,v in rows if e=='MOVE_STARTED' and v['label']=='PICKUP_HIGH')
        assert high['target'][:2]==pickup[:2]
        if previous is not None:
            incoming=[]
            for e,v in rows:
                if e=='MOVE_STARTED' and v['label']=='PICKUP_LOWER':break
                if e=='MOVE_STARTED' and v['label']!='LIFT':incoming.append(v['target'][:2])
            assert previous not in incoming
        previous=pickup[:2].copy()
    assert len(raw.grips)==21 and blend_grips==[2]*7


@pytest.mark.parametrize('force,accepted',[(39.9,False),(40.,True),(40.1,True)])
def test_reaction_40n_requires_threshold_and_verified_stop_before_release(force,accepted):
    values=setup_native();p=values[2];raw=values[-1]
    p['force_stop_n']=40.;p['native_press'].update(force_n=40.,alignment_trial=True)
    position_reaction(values,wrench=(0.,0.,force))
    if not accepted:
        move=raw.move_line_async
        def below_threshold(target,*args,**kwargs):
            move(target,*args,**kwargs)
            if target[2]<raw.reference[2]:raw.value["posx"]=target.copy()
        raw.move_line_async=below_threshold
    if accepted:
        evidence=run(values)['contact_evidence']
        assert evidence['threshold_force_norm_n']==pytest.approx(force)
        assert evidence['stop']['stillness_verified'] and raw.grips[-1][0]==48.
        assert evidence['force_control_target_n'] is None
    else:
        with pytest.raises(RuntimeError,match='PRESS_THRESHOLD_NOT_REACHED'):run(values)
        assert raw.value['gripper_status']==2 and len(raw.grips)==2
    assert not getattr(raw,'native_force_requests',[])


@pytest.mark.parametrize('reaction,threshold',[(False,40.),(True,35.)])
def test_40n_policy_rejects_native_force_command_or_mismatched_stop_threshold(reaction,threshold):
    values=setup_native();values[2]['force_stop_n']=threshold
    values[2]['native_press'].update(force_n=40.,alignment_trial=reaction)
    with pytest.raises(ValueError):run(values)
    assert not values[-1].moves and not values[-1].grips
