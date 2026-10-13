"""Two descent commands and one asynchronous batch per loaded/empty transit; devices mocked."""
from copy import deepcopy
import pytest
from app.assembly_step_runner import StepReplayDriver,assembly_target_pose
from app.integration_runtime import StepRuntime
from app.assembly_blend_trial import validate_route,segment_radii,run_blend
from scripts.robot_integration_fixture import document
from test_integration_runtime import Clock
from test_auto_handover_blend import blend_state,CONNECTION


def trial(**kwargs):
    d=document(**kwargs);p=d['d_profile'];p['continuous_transport']=True
    p.update(reaction_descent_velocity=6.,reaction_descent_acceleration=6.)
    p['native_press']=dict(enabled=True,review_ref='EXPLICIT_MOCK',force_n=35.,hold_s=3.,seek_above_reference_mm=6.,alignment_trial=True)
    p['transport_blending']=dict(reviewed=True,radius_mm=80.,relaxed_constraints=True)
    d['session']['stillness'].update(linear_mm_s=5.,angular_deg_s=5.,position_mm=1.,orientation_deg=1.)
    clock=Clock();events=[];s=p['steps']['fake/S01'];raw=StepReplayDriver(s['reference_pose'])
    rt=StepRuntime(raw,CONNECTION,lambda e,v:events.append((e,deepcopy(v))),clock=clock,sleep=clock.sleep)
    rt.start(d['step'],p,d['session'])
    return rt,raw,events,clock,d


@pytest.mark.parametrize('brick,color,angle',[('2x2x1','yellow',0),('2x2x1','blue',0),
    ('2x3x1','yellow',0),('2x3x1','yellow',90),('2x3x1','blue',0),('2x3x1','blue',90),
    ('1x2x1','red',0),('1x2x1','red',90)])
@pytest.mark.parametrize('layer',range(1,6))
def test_pickup_approach_then_gentle_press_with_continuous_transit_each_direction(brick,color,angle,layer):
    rt,raw,events,_,d=trial(brick_type=brick,color=color,angle=angle,layer=layer)
    p=d['d_profile'];s=rt.plan['settings']
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert [arg[0] for kind,arg in rt.operations if kind=='move']==['PICKUP_LOWER','PRE_CONTACT']
    # The press routine sends the final line command: straight down to the existing travel bound.
    assert len([e for e,v in events if e=='MOVE_REQUEST' and v.get('segment')!='BLENDED_TRANSIT'])==3
    pressure=[v for e,v in events if e=='MOVE_REQUEST' and v.get('segment')=='DESCENT'][-1]
    assert pressure['velocity']==[6.,6.] and pressure['acceleration']==[6.,6.]
    assert not getattr(raw,'native_force_requests',[]) and rt.contact['threshold_force_norm_n']>=35.
    assert len(raw.blends)==3  # initial empty approach, loaded transit, empty return before B
    loaded=raw.blends[1];back=raw.blends[2]
    assert len(loaded['targets'])==5
    assert loaded['targets'][0][:2]==s['pickup_pose'][:2]
    assert loaded['targets'][0][2]>s['pickup_pose'][2]
    assert loaded['targets'][-1][3:]==assembly_target_pose(s)[3:]
    assert back['targets'][0][:2]==s['reference_pose'][:2]
    assert back['targets'][0][2]>rt.contact['final_sample']['posx'][2]
    assert back['targets'][-1][:2]==s['pickup_pose'][:2]
    assert back['targets'][-1][3:]==s['pickup_pose'][3:]
    for batch in raw.blends:
        assert batch['radius'][-1]==0.  # stop at grip/descent boundary, not intermediate corners
        assert all(0<=v<=80. for v in batch['radius'])
    assert raw.value['gripper_status']==0 and not result['current_update']
    names=[e for e,v in events]
    assert names.index('CONTACT_SUCCEEDED')<max(i for i,e in enumerate(names) if e=='BLEND_COMPLETE')<names.index('INSPECTION_REQUIRED')


def test_relaxed_route_accepts_ascent_rotation_short_and_collinear_segments_above_old_radius_cap():
    start=[0.,0.,0.,0.,0.,0.]
    points=[[0.,0.,20.,0.,0.,0.],[10.,0.,20.,0.,0.,0.],
        [20.,0.,20.,0.,0.,0.],[30.,0.,20.,90.,0.,0.],[40.,0.,20.,90.,0.,0.]]
    assert validate_route(start,points,80.,relaxed=True)==points
    assert segment_radii(start,points,80.)==[4.9,4.9,4.9,4.9,0.]
    with pytest.raises(ValueError):validate_route(start,points,80.)  # legacy handover policy remains separate


@pytest.mark.parametrize('failure',['force','grip','stop','ack'])
def test_failure_in_continuous_loaded_ascent_never_releases_or_replays(failure):
    rt,raw,events,_,_=trial();original=raw.move_blending_async
    def move(*args):
        original(*args)
        if raw.value['gripper_status']==2:
            if failure=='force':raw.value['wrench'][0]=36.
            if failure=='grip':raw.value['gripper_status']=0
            if failure=='stop':rt.session.request_stop()
            if failure=='ack':raise RuntimeError('LOADED_BLEND_ACK_FAILED')
    raw.move_blending_async=move
    result=rt.run()
    assert result['status'] in ('STOPPED','RECOVERY_REQUIRED')
    assert len(raw.blends)==2 and len(raw.grips)==2 and rt.contact is None
    assert not any(e=='INSPECTION_REQUIRED' for e,v in events)
    assert raw.stops>=1


def test_palm_interrupt_during_loaded_rise_keeps_remaining_bypass_and_requires_receiving_signal():
    rt,raw,events,clock,_=trial();rt.profile['palm_handover_before_contact']=True
    original=raw.move_blending_async
    def move(*args):
        original(*args)
        if raw.value['gripper_status']==2 and len(raw.blends)==2:
            # Stop partway up the first approved vertical segment.
            pick=rt.plan['settings']['pickup_pose']
            raw.value['posx']=[*pick[:2],pick[2]+5.,*pick[3:]]
            assert rt.request_handover()
    raw.move_blending_async=move
    result=rt.run()  # no receiving sensor supplied: hold, never release
    assert result['status']=='RECOVERY_REQUIRED'
    assert not rt.contact and len(raw.grips)==2
    override=next(v for e,v in events if e=='HANDOVER_OVERRIDE')
    assert override['actual_stop_verified'] and not override['current_update']
    transit=[v['target'][:2] for e,v in events if e=='MOVE_STARTED' and v['label']=='HANDOVER_TRANSIT']
    assert rt.profile['body_bypass_xy_mm'] in transit and rt.profile['supply_transit_xy_mm'] in transit


def test_ros_serializes_five_3d_segments_with_individual_corner_radii(monkeypatch):
    import sys
    from types import SimpleNamespace
    from test_assembly_motion_ros import driver
    class Message:pass
    module=SimpleNamespace(Float64MultiArray=Message)
    monkeypatch.setitem(sys.modules,'std_msgs',SimpleNamespace(msg=module))
    monkeypatch.setitem(sys.modules,'std_msgs.msg',module)
    points=[[0.,0.,20.,0.,0.,0.],[10.,0.,20.,0.,0.,0.],
        [20.,0.,20.,0.,0.,0.],[30.,0.,20.,90.,0.,0.],[40.,0.,20.,90.,0.,0.]]
    radii=segment_radii([0.]*6,points,80.)
    raw=driver();raw.move_blending_async(points,radii,[32.,32.],[16.,16.])
    path,kind,fields=raw.calls[-1]
    assert kind=='MoveBlending' and fields['sync_type']==1 and fields['pos_cnt']==5
    assert [v.data[13] for v in fields['segment']]==radii
    assert [v.data[:6] for v in fields['segment']]==points
    assert fields['ref']==0 and fields['mode']==0


def test_relaxed_arrival_accepts_realistic_submillimeter_endpoint_with_fresh_stopped_feedback():
    d,p,raw,events,c,points=blend_state()
    p['transport_blending']['relaxed_constraints']=True
    original=raw.move_blending_async
    def move(*args):
        original(*args);raw.value['posx'][0]+=.4
    raw.move_blending_async=move
    sample=run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert sample['posx'][0]==points[-1][0]+.4
    final=next(v for e,v in events if e=='BLEND_COMPLETE')
    assert final['position_tolerance_mm']==1. and final['endpoint_verified']
    assert not raw.stops


def test_verified_stop_opens_with_persistent_reaction_then_transits_only_after_unloading():
    rt,raw,events,_,_=trial()
    # Physical STOP need not unload a tool pressed against a surface.
    raw.stop=lambda:setattr(raw,'stops',raw.stops+1)
    sample,grip=raw.sample,raw.command_gripper
    remaining=[0]
    def open_grip(width,force):
        grip(width,force)
        if rt.contact is not None and width==rt.plan['settings']['release_width_mm']:remaining[0]=2
    def feedback():
        value=sample()
        if remaining[0]:
            value['wrench'][2]=35.16;remaining[0]-=1
        return value
    raw.sample=feedback;raw.command_gripper=open_grip
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert rt.contact['final_sample']['wrench'][2]>=35.
    assert len(raw.grips)==3 and len(raw.blends)==3
    assert raw.value['wrench'][2]<35. and raw.value['gripper_status']==0


@pytest.mark.parametrize('velocity',[.002,1.,5.])
def test_nonzero_feedback_within_large_stillness_tolerance_never_blocks_grip_or_release(velocity):
    rt,raw,events,_,_=trial()
    raw.value['velx']=[velocity,0.,0.,0.,velocity,0.]
    # A stopped arm can keep residual load; do not assume STOP unloads the contact.
    raw.stop=lambda:setattr(raw,'stops',raw.stops+1)
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert raw.grips[-1][0]==rt.plan['settings']['release_width_mm']
    assert rt.contact['stop']['stillness_verified'] and len(raw.blends)==3


def test_motion_above_large_tolerance_does_not_claim_stopped_or_open():
    rt,raw,events,_,_=trial()
    raw.value['velx'][0]=5.01
    rt.driver.sample()  # observe the changed feedback; invalidate the earlier stopped proof
    result=rt.run()
    assert result['status']=='RECOVERY_REQUIRED'
    assert not raw.grips and not raw.blends


@pytest.mark.parametrize('z_offset,xy_offset',[(10.001,0.),(0.,2.01)])
def test_after_35n_stop_height_and_xy_diagnostics_never_block_opening(z_offset,xy_offset):
    rt,raw,events,_,_=trial();move=raw.move_line_async
    def downward(target,*args):
        pressing=raw.value['gripper_status']==2 and target[2]<raw.reference[2]
        move(target,*args)
        if pressing:
            raw.value['posx'][2]=raw.reference[2]+z_offset
            raw.value['posx'][0]=raw.reference[0]+xy_offset
            raw.value['wrench'][2]=35.2
    raw.move_line_async=downward
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert rt.contact['seating_goal_verified'] is False
    assert rt.contact['release_after_verified_reaction_stop']
    assert len(raw.grips)==3 and len(raw.blends)==3 and raw.value['gripper_status']==0
    diagnostic=next(v for e,v in events if e=='PRESS_SEATING_CHECK')
    assert diagnostic['diagnostic_only'] and not diagnostic['release_blocked_by_height_or_xy']


def test_recorded_blue_slot2_route_omits_reached_rise_before_controller_dispatch():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/blend-slot2-20261013.json').read_text())
    d,p,raw,events,c,_=blend_state()
    p['transport_blending'].update(radius_mm=40.,relaxed_constraints=True)
    d.session.value['stillness'].update(linear_mm_s=5.,angular_deg_s=5.,position_mm=1.,orientation_deg=1.)
    raw.value.update(deepcopy(fixture['first']))
    check=raw.check_pose
    def ik(target):
        raw.value.update(deepcopy(fixture['current']))
        return check(target)
    raw.check_pose=ik
    command=raw.move_blending_async
    def firmware(targets,radii,*args):
        assert all(r>1. for r in radii[:-1]), 'controller 1205: radius must exceed 1 mm'
        command(targets,radii,*args)
    raw.move_blending_async=firmware
    points=fixture['request']['targets']
    result=run_blend(d,CONNECTION,points,p,d.session.record,held=0,clock=c,sleep=c.sleep)
    assert result['posx']==points[-1]
    assert len(raw.blends)==1 and raw.blends[0]['targets']==points[1:]
    assert raw.blends[0]['radius']==[40.,40.,0.]
    # The replay driver records each blend waypoint in moves as well.
    assert raw.moves==points[1:] and not raw.grips and not raw.stops


def test_rise_reached_during_ik_is_removed_again_using_fresh_start():
    d,p,raw,events,c,_=blend_state()
    p['transport_blending'].update(radius_mm=40.,relaxed_constraints=True)
    points=[[0.,0.,102.,0.,0.,0.],[30.,0.,102.,0.,0.,0.],[30.,30.,102.,0.,0.,0.]]
    check=raw.check_pose
    def settled(target):
        raw.value['posx'][2]=101.99
        return check(target)
    raw.check_pose=settled
    run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert raw.blends[0]['targets']==points[1:]
    assert all(r>1. for r in raw.blends[0]['radius'][:-1])
    assert any(e=='BLEND_START_POINTS_OMITTED' and v['stage']=='COMMAND_START' for e,v in events)


def test_reached_start_with_one_remaining_endpoint_uses_single_line():
    d,p,raw,events,c,_=blend_state();p['transport_blending']['relaxed_constraints']=True
    points=[[.02,0.,100.,0.,0.,0.],[20.,20.,100.,0.,0.,0.]]
    result=run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert result['posx']==points[-1] and len(raw.moves)==1 and not raw.blends
    assert not raw.grips and not raw.stops


def test_reached_final_endpoint_does_not_send_another_motion():
    d,p,raw,events,c,_=blend_state();p['transport_blending']['relaxed_constraints']=True
    points=[[.02,0.,100.,0.,0.,0.],[.04,0.,100.,0.,0.,0.]]
    result=run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert abs(result['posx'][0]-points[-1][0])<=1.
    assert not raw.moves and not raw.blends and not raw.grips and not raw.stops
    assert any(e=='BLEND_COMPLETE' and v['endpoint_verified'] for e,v in events)


@pytest.mark.parametrize('distance',[.1,1.,2.])
def test_required_short_corner_fails_before_dispatch_with_radius_reason(distance):
    d,p,raw,events,c,_=blend_state();p['transport_blending']['relaxed_constraints']=True
    points=[[30.,0.,100.,0.,0.,0.],[30.,distance,100.,0.,0.,0.],[60.,distance,100.,0.,0.,0.]]
    with pytest.raises(ValueError,match='BLEND_RADIUS_BELOW_CONTROLLER_MINIMUM'):
        run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert not raw.moves and not raw.blends and not raw.grips and not raw.stops
    assert next(v for e,v in events if e=='ABORT')['stop']['requested'] is False


def test_fresh_start_below_clearance_keeps_original_rise_and_its_ik_check():
    d,p,raw,events,c,_=blend_state();p['transport_blending']['relaxed_constraints']=True
    points=[[0.,0.,100.1,0.,0.,0.],[30.,0.,100.1,0.,0.,0.],[30.,30.,100.1,0.,0.,0.]]
    check=raw.check_pose
    def settled(target):
        raw.value['posx'][2]=97.
        return check(target)
    raw.check_pose=settled
    run_blend(d,CONNECTION,points,p,d.session.record,clock=c,sleep=c.sleep)
    assert raw.blends[0]['targets']==points
    assert [v['target'] for e,v in events if e=='IK_FK_CHECK']==points
    assert all(r>1. for r in raw.blends[0]['radius'][:-1])
