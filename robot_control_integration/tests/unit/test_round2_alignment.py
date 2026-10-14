from copy import deepcopy
import pytest
from tests.unit.test_human_step_raised_press import fixture
from app.round2_alignment import automatic_surface_alignment,validate_alignment_candidate,validate_alignment_observation,virtual_grid_direction_provider
from app.round2_step_controller import binding


def setup():
    plan,p,_,_=fixture('yellow','2x2x1',0)
    p['round2_alignment_limits']=dict(max_translation_mm=3.,max_rotation_deg=2.,max_plane_error_deg=.5,max_center_error_mm=.5)
    sample=dict(posx=[400.,80.,65.,0.,180.,0.])
    candidate=dict(status='SURFACE_ALIGNMENT_CANDIDATE',binding=binding(plan),
        reference_kind='REGISTERED_BLOCK_AND_STUD_PLANES',registration_reviewed=True,frame_stamp_ns=1,
        approach_pose=sample['posx'].copy(),landing_pose=plan['settings']['reference_pose'].copy(),pad_contact_z_mm=60.)
    observed=dict(status='SURFACE_ALIGNMENT_OBSERVATION',binding=binding(plan),reference_kind=candidate['reference_kind'],
        frame_stamp_ns=2,plane_error_deg=.4,center_error_mm=50.,roll_error_deg=.5,pitch_error_deg=-.5,yaw_error_deg=.5)
    return plan,p,sample,candidate,observed


def test_angles_only_do_not_require_stud_center_coincidence():
    plan,p,s,c,o=setup()
    assert validate_alignment_observation(plan,c,o,p)
    o['roll_error_deg']=.5001
    assert not validate_alignment_observation(plan,c,o,p)


def test_registered_loop_can_repeat_more_than_fixed_trial_count():
    plan,p,s,c,o=setup();events=[];counts=[0]
    class Driver:
        def sample(self):return deepcopy(s)
    def provider(stage,*_):
        if stage=='BEFORE':
            out=deepcopy(c);out['frame_stamp_ns']=counts[0]*2+1
            out['approach_pose'][3]=.1;out['landing_pose'][3]=.1
        else:
            counts[0]+=1;out=deepcopy(o);out.update(frame_stamp_ns=counts[0]*2,roll_error_deg=1. if counts[0]<12 else .5)
        return out
    result=automatic_surface_alignment(Driver(),plan,p,provider,lambda *_:None,lambda e,x:events.append((e,x)))
    assert result['iteration']==12 and result['status']=='SURFACE_ALIGNMENT_CONVERGED'


def test_reused_next_frame_never_commands_another_correction():
    plan,p,s,c,o=setup();o['roll_error_deg']=1.;moves=[]
    class Driver:
        def sample(self):return deepcopy(s)
    with pytest.raises(ValueError,match='NEXT_ITERATION_REQUIRES_NEW_FRAME'):
        automatic_surface_alignment(Driver(),plan,p,lambda stage,*_:deepcopy(c if stage=='BEFORE' else o),
            lambda *_:moves.append(True),lambda *_:None)
    assert not moves


def test_existing_grid_yaw_uses_no_plane_registration_or_xy_alignment():
    plan,p,s,c,o=setup()
    c.update(reference_kind='EXISTING_BOARD_PARALLEL_DIRECTIONS',roll_pitch_observed=False,
        stud_center_coincidence_required=False,approach_pose=[400.,80.,65.,.5,180.,0.],landing_pose=[400.,80.,40.,.5,180.,0.])
    c.pop('registration_reviewed');p.pop('round2_alignment_limits')
    validate_alignment_candidate(plan,p,s,c)
    o.update(reference_kind=c['reference_kind'],status='DIRECTION_ALIGNMENT_OBSERVATION',yaw_error_deg=-.5)
    o.pop('plane_error_deg');o.pop('center_error_mm');o.pop('roll_error_deg');o.pop('pitch_error_deg')
    assert validate_alignment_observation(plan,c,o,p)
    bad=deepcopy(c);bad['approach_pose'][0]+=1
    with pytest.raises(ValueError,match='KEEP_XYZ'):validate_alignment_candidate(plan,p,s,bad)


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
    def capture(*_):return dict(frame_bgr=frame,camera_info=info,edge_uv=edge.tolist(),frame_stamp_ns=1)
    provider=virtual_grid_direction_provider(capture,c['virtual_grid'],near_contact_offset_mm=p['near_contact_offset_mm'])
    result=provider('BEFORE',plan,sample)
    assert result['status']=='DIRECTION_ALIGNMENT_CANDIDATE'
    assert abs(result['command_deg'])==.5
    assert result['approach_pose'][:3]==sample['posx'][:3]
    assert not result['projection']['projection_independently_verified']
    validate_alignment_candidate(plan,p,sample,result)
