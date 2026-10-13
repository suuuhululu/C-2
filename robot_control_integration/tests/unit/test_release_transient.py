"""Already verified press STOP precedes open; opening transients are not a new arm command."""
import pytest
from test_continuous_transport import trial


@pytest.mark.parametrize('motion_status,velocity',[(0,5.01),(0,20.),(2,0.)])
def test_opening_transient_after_verified_stop_does_not_abort_release(motion_status,velocity):
    rt,raw,events,_,_=trial()
    grip,sample=raw.command_gripper,raw.sample
    remaining=[0]
    def command(width,force):
        grip(width,force)
        if rt.contact is not None:remaining[0]=3
    def feedback():
        value=sample()
        if remaining[0]:
            remaining[0]-=1
            value.update(motion_status=motion_status,velx=[velocity,0.,0.,0.,0.,0.])
            value['wrench'][2]=57.
        return value
    raw.command_gripper=command;raw.sample=feedback
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert rt.contact['stop']['stillness_verified'] and len(raw.grips)==3
    assert len(raw.blends)==2 and raw.value['gripper_status']==0
    names=[e for e,v in events]
    opened=next(i for i,(e,v) in enumerate(events) if e=='GRIP_SUCCEEDED' and v['label']=='SEATED_RELEASE')
    lifted=next(i for i,(e,v) in enumerate(events) if e=='MOVE_SUCCEEDED' and v['label']=='LIFT')
    assert names.index('CONTACT_SUCCEEDED')<opened<lifted<names.index('INSPECTION_REQUIRED')


def test_persistent_arm_movement_after_open_holds_before_return_not_during_open():
    rt,raw,events,_,_=trial();grip=raw.command_gripper
    def command(width,force):
        grip(width,force)
        if rt.contact is not None:
            raw.value.update(motion_status=2,velx=[20.,0.,0.,0.,0.,0.])
    raw.command_gripper=command
    result=rt.run()
    assert result['status']=='RECOVERY_REQUIRED'
    assert any(e=='GRIP_SUCCEEDED' and v['label']=='SEATED_RELEASE' for e,v in events)
    assert len(raw.blends)==2 and raw.value['gripper_status']==0
    assert result['reason']=='STOP_WINDOW_NOT_VERIFIED'


@pytest.mark.parametrize('failure',['not_open','bad_width','fault','stale'])
def test_real_gripper_feedback_failure_remains_hold_after_open_command(failure):
    rt,raw,events,_,_=trial();grip=raw.command_gripper
    def command(width,force):
        grip(width,force)
        if rt.contact is None:return
        if failure=='not_open':raw.value['gripper_status']=2
        if failure=='bad_width':raw.value['gripper_width_mm']=0.
        if failure=='fault':raw.value['gripper_status']=4
        if failure=='stale':raw.value['query_duration_s']=.6
    raw.command_gripper=command
    result=rt.run()
    assert result['status']=='RECOVERY_REQUIRED'
    assert not any(e=='GRIP_SUCCEEDED' and v['label']=='SEATED_RELEASE' for e,v in events)
    assert len(raw.grips)==3 and len(raw.blends)==2
