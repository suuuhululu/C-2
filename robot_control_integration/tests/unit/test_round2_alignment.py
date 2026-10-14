from copy import deepcopy
import pytest
from tests.unit.test_human_step_raised_press import fixture
from app.round2_alignment import automatic_surface_alignment,validate_alignment_candidate,validate_alignment_observation,virtual_grid_direction_provider
from app.round2_step_controller import binding

NOW=10_000_000_000
SOURCE_EPOCH=1_700_000_000_000_000_000


def capture_timing(sample,exposure,now=NOW,*,mapping_error=0):
    return dict(clock_domain='TEST_ROS_CLOCK',clock_now_ns=SOURCE_EPOCH+now,
        pose_clock_domain='TEST_ROS_CLOCK',pose_stamp_ns=SOURCE_EPOCH+exposure,
        pose_posx=deepcopy(sample['posx']),exposure_monotonic_ns=exposure,
        exposure_mapping_error_ns=mapping_error,clock_mapping_ref='TEST_REVIEWED_MAPPING')


def timed(result,sample,exposure,now=NOW):
    result.update(frame_stamp_ns=SOURCE_EPOCH+exposure,capture_timing=capture_timing(sample,exposure,now))
    return result


class FakeClock:
    def __init__(self):self.now=NOW
    def __call__(self):return self.now
    def advance(self,nanoseconds=1_000_000):self.now+=nanoseconds


def setup():
    plan,p,_,_=fixture('yellow','2x2x1',0)
    p['round2_alignment_limits']=dict(max_translation_mm=3.,max_rotation_deg=2.,max_plane_error_deg=.5,max_center_error_mm=.5)
    p['round2_capture_limits']=dict(max_frame_age_ns=100_000_000,max_pose_skew_ns=20_000_000,max_clock_mapping_error_ns=1_000_000)
    sample=dict(posx=[400.,80.,65.,0.,180.,0.])
    candidate=dict(status='SURFACE_ALIGNMENT_CANDIDATE',binding=binding(plan),
        reference_kind='REGISTERED_BLOCK_AND_STUD_PLANES',registration_reviewed=True,frame_stamp_ns=1,
        approach_pose=sample['posx'].copy(),landing_pose=plan['settings']['reference_pose'].copy(),pad_contact_z_mm=60.)
    observed=dict(status='SURFACE_ALIGNMENT_OBSERVATION',binding=binding(plan),reference_kind=candidate['reference_kind'],
        frame_stamp_ns=2,plane_error_deg=.4,center_error_mm=50.,roll_error_deg=.5,pitch_error_deg=-.5,yaw_error_deg=.5)
    timed(candidate,sample,NOW-20_000_000);timed(observed,sample,NOW-10_000_000)
    return plan,p,sample,candidate,observed


def test_angles_only_do_not_require_stud_center_coincidence():
    plan,p,s,c,o=setup()
    args=dict(sample=s,now_monotonic_ns=NOW,not_before_monotonic_ns=NOW-15_000_000)
    assert validate_alignment_observation(plan,c,o,p,**args)
    o['roll_error_deg']=.5001
    assert not validate_alignment_observation(plan,c,o,p,**args)


def test_registered_loop_can_repeat_more_than_fixed_trial_count():
    plan,p,s,c,o=setup();events=[];counts=[0];clock=FakeClock()
    class Driver:
        def sample(self):return deepcopy(s)
    def provider(stage,_,sample):
        clock.advance()
        if stage=='BEFORE':
            out=deepcopy(c)
            out['approach_pose'][3]=.1;out['landing_pose'][3]=.1
        else:
            counts[0]+=1;out=deepcopy(o);out.update(roll_error_deg=1. if counts[0]<12 else .5)
        return timed(out,sample,clock.now,clock.now)
    result=automatic_surface_alignment(Driver(),plan,p,provider,lambda *_:None,lambda e,x:events.append((e,x)),clock=clock)
    assert result['iteration']==12 and result['status']=='SURFACE_ALIGNMENT_CONVERGED'


def test_reused_next_frame_never_commands_another_correction():
    plan,p,s,c,o=setup();o['roll_error_deg']=1.;moves=[];clock=FakeClock();clock.now=NOW-15_000_000
    class Driver:
        def sample(self):return deepcopy(s)
    def provider(stage,*_):
        if stage=='AFTER':clock.now=NOW
        return deepcopy(c if stage=='BEFORE' else o)
    with pytest.raises(ValueError,match='NEXT_ITERATION_REQUIRES_NEW_FRAME'):
        automatic_surface_alignment(Driver(),plan,p,provider,
            lambda *_:moves.append(True),lambda *_:None,clock=clock)
    assert not moves


def test_existing_grid_yaw_uses_no_plane_registration_or_xy_alignment():
    plan,p,s,c,o=setup()
    c.update(reference_kind='EXISTING_BOARD_PARALLEL_DIRECTIONS',roll_pitch_observed=False,
        stud_center_coincidence_required=False,edge_id='body_top:front',
        approach_pose=[400.,80.,65.,.5,180.,0.],landing_pose=[400.,80.,40.,.5,180.,0.])
    c.pop('registration_reviewed');p.pop('round2_alignment_limits')
    validate_alignment_candidate(plan,p,s,c,now_monotonic_ns=NOW)
    o.update(reference_kind=c['reference_kind'],status='DIRECTION_ALIGNMENT_OBSERVATION',yaw_error_deg=-.5,edge_id=c['edge_id'])
    o.pop('plane_error_deg');o.pop('center_error_mm');o.pop('roll_error_deg');o.pop('pitch_error_deg')
    assert validate_alignment_observation(plan,c,o,p,sample=s,now_monotonic_ns=NOW,not_before_monotonic_ns=NOW-15_000_000)
    bad=deepcopy(c);bad['approach_pose'][0]+=1
    with pytest.raises(ValueError,match='KEEP_XYZ'):validate_alignment_candidate(plan,p,s,bad,now_monotonic_ns=NOW)


@pytest.mark.parametrize('layer',[1,2,3,4,5])
def test_provider_uses_existing_layer_grid_without_new_registration(layer):
    from types import SimpleNamespace
    import numpy as np
    from scripts.supply_pick_release_trial import load_config
    from scripts.held_corner_stud_trial import NATIVE
    from supply_vision.virtual_board_grid import VirtualBoardGrid
    c=load_config(NATIVE/'settings/held_corner_stud_20261014/config.json')
    plan,p,_,_,_=setup();plan['block'].update(x=11,y=11,layer=layer)
    plan['settings']['press_start_pose']=[472.,85.,60.,102.,-176.,104.]
    sample=dict(posx=[472.,85.,194.,102.,-176.,104.])
    frame=np.zeros((480,640,3),np.uint8)
    info=SimpleNamespace(width=640,height=480,header=SimpleNamespace(frame_id='camera_color_optical_frame'),
        distortion_model='plumb_bob',k=[600,0,320,0,600,240,0,0,1],d=[0.]*5)
    _,grid=VirtualBoardGrid(c['virtual_grid']).overlay(frame,sample,info,layer,20.)
    edge=np.array(grid['target_hover_outline_uv'][:2])
    center=edge.mean(axis=0);angle=np.radians(1.)
    edge=(edge-center)@np.array([[np.cos(angle),np.sin(angle)],[-np.sin(angle),np.cos(angle)]])+center
    def capture(*_):return dict(frame_bgr=frame,camera_info=info,edge_uv=edge.tolist(),frame_stamp_ns=SOURCE_EPOCH+NOW,
        binding=binding(plan),capture_timing=capture_timing(sample,NOW),edge_id='body_top:front')
    provider=virtual_grid_direction_provider(capture,c['virtual_grid'],near_contact_offset_mm=p['near_contact_offset_mm'])
    result=provider('BEFORE',plan,sample)
    assert result['status']=='DIRECTION_ALIGNMENT_CANDIDATE'
    assert abs(result['command_deg'])==.5
    assert result['approach_pose'][:3]==sample['posx'][:3]
    assert not result['projection']['projection_independently_verified']
    validate_alignment_candidate(plan,p,sample,result,now_monotonic_ns=NOW)


def test_direction_only_keeps_original_landing_position_validation():
    plan,p,s,c,_=setup()
    c.update(reference_kind='EXISTING_BOARD_PARALLEL_DIRECTIONS',roll_pitch_observed=False,
        stud_center_coincidence_required=False,edge_id='body_top:front',landing_pose=[400.,80.,40.,0.,180.,0.])
    for axis in range(3):
        bad=deepcopy(c);bad['landing_pose'][axis]+=50.
        validate_alignment_candidate(plan,p,s,bad,now_monotonic_ns=NOW)


@pytest.mark.parametrize('change,reason',[
    ('missing_timing','CAPTURE_TIMING_REQUIRED'),
    ('missing_limits','REVIEWED_CAPTURE_LIMITS_REQUIRED'),
    ('wrong_pose_domain','CAPTURE_CLOCK_DOMAIN_MISMATCH'),
    ('old_source_frame','CAPTURE_OLD_OR_FUTURE_FRAME'),
    ('old_mapped_exposure','CAPTURE_OLD_OR_FUTURE_FRAME'),
    ('future_source_frame','CAPTURE_OLD_OR_FUTURE_FRAME'),
    ('future_mapped_exposure','CAPTURE_OLD_OR_FUTURE_FRAME'),
    ('pose_time_skew','CAPTURE_POSE_FRAME_SKEW'),
    ('different_pose','CAPTURE_POSE_SAMPLE_MISMATCH'),
    ('unbounded_clock_mapping','CAPTURE_CLOCK_MAPPING_UNCERTAINTY'),
    ('missing_clock_mapping','CAPTURE_CLOCK_MAPPING_REQUIRED'),
])
def test_capture_requires_reviewed_clocks_freshness_and_same_pose(change,reason):
    plan,p,s,c,_=setup();timing=c['capture_timing']
    if change=='missing_timing':c.pop('capture_timing')
    elif change=='missing_limits':p.pop('round2_capture_limits')
    elif change=='wrong_pose_domain':timing['pose_clock_domain']='MONOTONIC'
    elif change=='old_source_frame':timing['clock_now_ns']=c['frame_stamp_ns']+100_000_001
    elif change=='old_mapped_exposure':timing['exposure_monotonic_ns']=NOW-100_000_001
    elif change=='future_source_frame':timing['clock_now_ns']=c['frame_stamp_ns']-1
    elif change=='future_mapped_exposure':timing['exposure_monotonic_ns']=NOW+1
    elif change=='pose_time_skew':timing['pose_stamp_ns']=c['frame_stamp_ns']+20_000_001
    elif change=='different_pose':timing['pose_posx'][0]+=1
    elif change=='unbounded_clock_mapping':timing['exposure_mapping_error_ns']=1_000_001
    elif change=='missing_clock_mapping':timing.pop('clock_mapping_ref')
    with pytest.raises(ValueError,match=reason):
        validate_alignment_candidate(plan,p,s,c,now_monotonic_ns=NOW)


def test_source_ros_clock_is_not_compared_directly_with_monotonic():
    plan,p,s,c,o=setup()
    assert c['frame_stamp_ns']>NOW*1000
    validate_alignment_candidate(plan,p,s,c,now_monotonic_ns=NOW)
    assert validate_alignment_observation(plan,c,o,p,sample=s,now_monotonic_ns=NOW,
        not_before_monotonic_ns=NOW-15_000_000)


@pytest.mark.parametrize('mapping_error',[0,1_000_000])
def test_newer_after_frame_must_be_exposed_after_completed_motion(mapping_error):
    plan,p,s,c,o=setup()
    o['capture_timing']['exposure_mapping_error_ns']=mapping_error
    barrier=o['capture_timing']['exposure_monotonic_ns']-mapping_error
    assert o['frame_stamp_ns']>c['frame_stamp_ns']
    with pytest.raises(ValueError,match='POST_MOTION_EXPOSURE'):
        validate_alignment_observation(plan,c,o,p,sample=s,now_monotonic_ns=NOW,
            not_before_monotonic_ns=barrier)


def test_after_cannot_change_clock_domain_or_omit_motion_barrier():
    plan,p,s,c,o=setup()
    with pytest.raises(ValueError,match='MOTION_BARRIER_REQUIRED'):
        validate_alignment_observation(plan,c,o,p,sample=s,now_monotonic_ns=NOW)
    o['capture_timing'].update(clock_domain='OTHER_ROS_CLOCK',pose_clock_domain='OTHER_ROS_CLOCK')
    with pytest.raises(ValueError,match='CLOCK_DOMAIN_MISMATCH'):
        validate_alignment_observation(plan,c,o,p,sample=s,now_monotonic_ns=NOW,
            not_before_monotonic_ns=NOW-15_000_000)


def direction_fixture():
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import numpy as np
    from supply_vision.virtual_board_grid import VirtualBoardGrid
    root=Path(__file__).resolve().parents[2]
    config=json.loads((root/'settings/held_corner_stud_20261014/config.json').read_text())
    plan,p,_,_,_=setup();plan['block'].update(x=11,y=11,layer=1)
    plan['settings']['press_start_pose']=[472.,85.,60.,102.,-176.,104.]
    sample=dict(posx=[472.,85.,194.,102.,-176.,104.])
    frame=np.zeros((480,640,3),np.uint8)
    info=SimpleNamespace(width=640,height=480,header=SimpleNamespace(frame_id='camera_color_optical_frame'),
        distortion_model='plumb_bob',k=[600,0,320,0,600,240,0,0,1],d=[0.]*5)
    _,grid=VirtualBoardGrid(config['virtual_grid']).overlay(frame,sample,info,1,20.)
    packet=dict(frame_bgr=frame,camera_info=info,frame_stamp_ns=SOURCE_EPOCH+NOW,
        capture_timing=capture_timing(sample,NOW),binding=binding(plan),edge_uv=grid['target_hover_outline_uv'][:2],
        edge_id='body_top:front')
    return plan,p,sample,config,packet,grid['target_hover_outline_uv'][1:3]


@pytest.mark.parametrize('change',['new_binding_same_edge_id','new_edge_id_same_binding'])
def test_reused_provider_reselects_parallel_axis_for_new_step_or_edge(change):
    plan,p,s,config,packet,perpendicular=direction_fixture()
    def capture(stage,current,sample):
        out=deepcopy(packet);out['binding']=binding(current)
        return out
    provider=virtual_grid_direction_provider(capture,config['virtual_grid'],near_contact_offset_mm=p['near_contact_offset_mm'])
    first=provider('BEFORE',plan,s)
    assert first['projection']['selected_grid_axis']==0 and first['command_deg']==0
    packet['edge_uv']=perpendicular
    if change=='new_edge_id_same_binding':packet['edge_id']='body_top:right'
    else:plan.update(key='square/S5',step_id='S5')
    second=provider('BEFORE',plan,s)
    assert second['projection']['selected_grid_axis']==1
    assert abs(second['yaw_error_deg'])<1e-8 and second['command_deg']==0


@pytest.mark.parametrize('edge_id',[None,'',' ',42])
def test_missing_physical_edge_identity_waits_before_command_and_after_reuse(edge_id):
    plan,p,s,config,packet,perpendicular=direction_fixture();moves=[]
    class Driver:
        def sample(self):return deepcopy(s)
    provider=virtual_grid_direction_provider(lambda *_:deepcopy(packet),config['virtual_grid'],
        near_contact_offset_mm=p['near_contact_offset_mm'])
    first=provider('BEFORE',plan,s)
    assert first['projection']['selected_grid_axis']==0
    packet.update(edge_id=edge_id,edge_uv=perpendicular)
    after=provider('AFTER',plan,s)
    assert after['status']=='UNAVAILABLE' and after['reason']=='ROUND2_PHYSICAL_EDGE_ID_REQUIRED'
    result=automatic_surface_alignment(Driver(),plan,p,provider,lambda *_:moves.append(True),lambda *_:None,clock=lambda:NOW)
    assert result['status']=='WAITING_SURFACE_MEASUREMENT' and result['reason']=='ROUND2_PHYSICAL_EDGE_ID_REQUIRED'
    assert not moves


def test_custom_direction_candidate_cannot_omit_physical_edge_identity():
    plan,p,s,c,_=setup()
    c.update(reference_kind='EXISTING_BOARD_PARALLEL_DIRECTIONS',roll_pitch_observed=False,
        stud_center_coincidence_required=False,landing_pose=[400.,80.,40.,0.,180.,0.])
    with pytest.raises(ValueError,match='PHYSICAL_EDGE_ID_REQUIRED'):
        validate_alignment_candidate(plan,p,s,c,now_monotonic_ns=NOW)


def test_edge_identity_change_after_command_cannot_verify_previous_correction():
    plan,p,s,config,packet,_=direction_fixture();packet['edge_id']='body_top:front'
    provider=virtual_grid_direction_provider(lambda *_:deepcopy(packet),config['virtual_grid'],
        near_contact_offset_mm=p['near_contact_offset_mm'])
    assert provider('BEFORE',plan,s)['status']=='DIRECTION_ALIGNMENT_CANDIDATE'
    packet['edge_id']='body_top:right'
    result=provider('AFTER',plan,s)
    assert result['status']=='UNAVAILABLE' and result['reason']=='ROUND2_DIRECTION_EDGE_CHANGED_AFTER_COMMAND'


def test_missing_provider_capture_timing_waits_without_moving():
    plan,p,s,config,packet,_=direction_fixture();packet.pop('capture_timing');moves=[]
    class Driver:
        def sample(self):return deepcopy(s)
    provider=virtual_grid_direction_provider(lambda *_:deepcopy(packet),config['virtual_grid'],
        near_contact_offset_mm=p['near_contact_offset_mm'])
    result=automatic_surface_alignment(Driver(),plan,p,provider,lambda *_:moves.append(True),lambda *_:None,clock=lambda:NOW)
    assert result['status']=='WAITING_SURFACE_MEASUREMENT' and result['reason']=='ROUND2_CAPTURE_TIMING_REQUIRED'
    assert not moves


def test_generic_alignment_provides_and_enforces_post_motion_barrier():
    plan,p,s,c,o=setup();clock=FakeClock();moves=[];barriers=[]
    class Driver:
        def sample(self):return deepcopy(s)
    def move(*_):
        moves.append(True);clock.advance(30_000_000)
    def provider(stage,_,sample):
        if stage=='BEFORE':
            result=deepcopy(c);result['approach_pose'][3]=.1;result['landing_pose'][3]=.1
        else:
            barriers.append(sample['round2_capture_not_before_monotonic_ns'])
            result=deepcopy(o)
        clock.advance()
        return timed(result,sample,clock.now,clock.now)
    result=automatic_surface_alignment(Driver(),plan,p,provider,move,lambda *_:None,clock=clock)
    assert moves==[True] and barriers==[NOW+31_000_000]
    assert result['status']=='SURFACE_ALIGNMENT_CONVERGED'
