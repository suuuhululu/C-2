from copy import deepcopy
import time
import pytest
from app.raised_grasp_press import apply_profile,run_sequence,require_landing_before_release


def fixture(support=False):
    abc=[0.,180.,0.];target=dict(color='yellow',brick_type='2x2x1',x=11,y=11,layer=1,orientation_deg=0)
    row=dict(color='yellow',brick_type='2x2x1',slot=1,span=2,pickup_pose=[-300,100,50,*abc],center_mapping={'old':True})
    config=dict(connection=dict(tcp='GripperDA_v4',tool='ToolWeight0'),blocks=[row],assembly_target_xy=[470,85],pickup_clearance_z_mm=190,alignment_target=dict(target=target,placement_tcp_reference=[470,85,15,*abc],clearance_mm=20))
    profile=dict(pad_bottom_from_block_bottom_mm=15.,version='raised-grasp-press/1',reason='GRIPPER_COLLISION',binding=dict(color='yellow',brick_type='2x2x1',slot=1,span=2,step_id='S1',support_request_id='help1'),target=target,tcp='GripperDA_v4',tool='ToolWeight0',grasp_stability_verified=True,neighbor_clearance_verified=True,landing_support_verified=True,pad_contact_verified=True,human_support_required=support,measurement_ref='TEST_FIXTURE_ONLY',pickup_pose=[-300,100,55,*abc],landing_pose=[470,85,20,*abc],pad_contact_pose=[470,85,30,*abc])
    return config,profile


def test_profile_updates_both_grasp_and_landing_without_mutating_source():
    c,p=fixture();before=deepcopy(c);out=apply_profile(c,p)
    assert c==before and out['blocks'][0]['pickup_pose']==p['pickup_pose']
    assert out['alignment_target']['placement_tcp_reference']==p['landing_pose']
    assert out['alignment_approach_z_mm']==40 and out['integrated_pad_contact_pose']==p['pad_contact_pose']
    assert 'center_mapping' not in out['blocks'][0]

@pytest.mark.parametrize('field',['pickup_pose','landing_pose','pad_contact_pose','grasp_stability_verified','neighbor_clearance_verified','landing_support_verified','pad_contact_verified'])
def test_missing_measurements_never_admit(field):
    c,p=fixture();p[field]=None
    with pytest.raises(ValueError):apply_profile(c,p)


def test_support_expiry_and_binding():
    c,p=fixture(True);receipt=dict(step_id='S1',request_id='help1',ready=True,expires_at_unix_s=time.time()+60)
    apply_profile(c,p,support_confirmation=receipt)
    for r in (None,dict(receipt,step_id='S2'),dict(receipt,expires_at_unix_s=0)):
        with pytest.raises(ValueError,match='SUPPORT_READY'):apply_profile(c,p,support_confirmation=r)


def operations(log,status='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED',ready=True):
    ops={name:(lambda c,n=name:log.append(n)) for name in ('pickup','transfer','align','release','retract_and_close')}
    ops.update(support_ready=lambda b:ready,insert=lambda c:(log.append('insert') or dict(status=status)),confirm_landing=lambda r:True,press_and_rise=lambda c:(log.append('press_and_rise') or dict(status='REACTION_STOP')),stop=lambda:log.append('stop'))
    return ops


def test_sequence_order():
    c,p=fixture();c=apply_profile(c,p);log=[];r=run_sequence(c,operations(log),lambda *_:None)
    assert log==['pickup','transfer','align','insert','release','retract_and_close','press_and_rise']
    assert not r['assembly_completion']


def test_force_stop_never_releases_or_presses():
    c,p=fixture();c=apply_profile(c,p);log=[]
    with pytest.raises(RuntimeError,match='NO_RELEASE_NO_PRESS'):run_sequence(c,operations(log,'FORCE_STOPPED_BEFORE_VERIFIED_SEATING'),lambda *_:None)
    assert log==['pickup','transfer','align','insert','stop']


def test_support_not_ready_requests_help_without_motion():
    c,p=fixture(True);receipt=dict(step_id='S1',request_id='help1',ready=True,expires_at_unix_s=time.time()+60)
    c=apply_profile(c,p,support_confirmation=receipt);log=[];events=[]
    r=run_sequence(c,operations(log,ready=False),lambda *x:events.append(x))
    assert not log and r['status']=='WAITING_HUMAN_SUPPORT' and events[0][0]=='HUMAN_SUPPORT_REQUEST'


def test_unraised_behavior_unchanged():
    require_landing_before_release({},dict(status='FORCE_STOPPED_BEFORE_VERIFIED_SEATING'))
