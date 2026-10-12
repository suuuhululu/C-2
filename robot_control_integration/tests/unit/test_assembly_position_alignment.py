"""Position-only motion ordering and fault paths; no physical contact claim."""
import json
import time
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from app.assembly_contact_fake import ContactFake,fake_config
from app.assembly_position_alignment import prepare_position_alignment,run_position_alignment
from scripts.assembly_contact_trial import TEMPLATE,main


def fixture():
    c=fake_config(json.loads(TEMPLATE.read_text()));d=ContactFake(c);d.pos[2]=18.
    origin=d.pos.copy()
    def gradient(s):
        delta=Rotation.from_euler('ZYZ',s['posx'][3:],degrees=True)*Rotation.from_euler('ZYZ',origin[3:],degrees=True).inv()
        angles=np.rad2deg(delta.as_rotvec())
        s['wrench']=[float(v) for v in [4*(s['posx'][0]-origin[0]+.25),4*(s['posx'][1]-origin[1]),10.,angles[0]+.2,angles[1],0.]]
    d.modify=gradient
    return c,d


def run(c,d,**kw):
    t=[0.]
    def sleep(n):t[0]+=n
    events=[]
    r=run_position_alignment(d,prepare_position_alignment(c),lambda e,p:events.append((e,p)),
        now=lambda:t[0],sleep=sleep,**kw)
    return r,events


def test_xy_and_tilt_reduce_measured_responses_without_force_or_vertical_commands():
    c,d=fixture();r,events=run(c,d)
    assert r['status']=='POSITION_ALIGNMENT_REVIEW_REQUIRED' and r['probe_count']==12
    assert r['correction'][0]==-.25 and r['correction'][2]==-.2
    assert r['force_commands']==0 and not r['assembled'] and r['stopped']
    assert all(call[0] in ('move','stop') for call in d.calls)
    assert all(call[1][2]==18. for call in d.calls if call[0]=='move')
    assert len([e for e,p in events if e=='POSITION_CORRECTION_SELECTED'])==2


def test_position_mode_needs_floor_and_review_but_not_a_new_free_approach():
    c,d=fixture();c['reference']=None
    assert prepare_position_alignment(c)['status']=='POSITION_ALIGNMENT_READY'
    c['floor_z_mm']=None
    assert prepare_position_alignment(c)['missing']==['floor_z_mm']
    c,d=fixture();c['reference']['captured_at_unix_s']=time.time()-100000
    assert prepare_position_alignment(c)['status']=='POSITION_ALIGNMENT_READY'


@pytest.mark.parametrize('cancel',[False,True])
def test_position_fault_or_cancel_stops_without_force_release_or_retry(cancel):
    c,d=fixture();moving=lambda:any(a[0]=='move' for a in d.calls)
    if not cancel:
        original=d.modify
        def fault(s):
            original(s)
            if moving():s['wrench']=[0.,0.,35.,0.,0.,0.]
        d.modify=fault
    r,e=run(c,d,cancelled=lambda:cancel and moving())
    assert r['reason']==('OPERATOR_CANCELLED' if cancel else 'RAW_FORCE_STOP')
    assert [a[0] for a in d.calls]==['move','stop']


def test_ambiguous_move_ack_stops_without_sending_next_candidate():
    c,d=fixture();original=d.move_line_async
    def lost(*a):original(*a);raise TimeoutError('ACK_TIMEOUT')
    d.move_line_async=lost
    r,e=run(c,d)
    assert r['state_uncertain'] and r['stopped'] is None
    assert [a[0] for a in d.calls]==['move','stop']


def test_default_cli_smoke_uses_no_native_force_and_native_mode_needs_opt_in(tmp_path):
    assert main(['smoke','--log-dir',str(tmp_path)])==0
    events=[json.loads(s) for s in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
    assert any(e['event']=='POSITION_TRIAL_RESULT' for e in events)
    assert not any(e['event']=='CONTACT_COMMAND_ACK' for e in events)
    assert main(['run','--in-contact','--execute','--log-dir',str(tmp_path/'invalid')],
        driver_factory=lambda c:pytest.fail('device created'))==1
