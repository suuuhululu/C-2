"""Fake camera rows only; no ROS, camera model or robot construction."""
from types import SimpleNamespace

from app.integration_gestures import OperatorGestureInput


def setup():
    req=dict(request_id='R1',kind='ALIGNMENT_READY',execution_id='E1',plan_id='P1',step_id='S1',current_revision=None)
    accepted=[];stops=[];events=[]
    r=SimpleNamespace(plan=dict(plan_id='P1',step_id='S1',current_revision=None),
        session=SimpleNamespace(value=dict(execution_id='E1',source_epoch='LIVE1',frame_max_age_s=.3)),
        request=req,state='RUNNING',signal_seq=-1,accept_signal=accepted.append,stop=lambda:stops.append(True))
    gate=OperatorGestureInput(r,lambda e,d:events.append((e,d)))
    return r,gate,accepted,stops,events


def row(t,pose='THUMBS_UP',request='R1'):
    return dict(provenance='SENSOR',received_monotonic_ns=t,source_ns=t+1,
        frame='camera',hands=[dict(pose=pose,center=[100.,100.],palm_size=40.)],
        execution_id='E1',source_epoch='LIVE1',preview_request_id=request,
        candidate_event='THUMBS_UP_HELD',continuity_estimate=True,pose_verified=False)


def test_thumb_only_confirms_active_request_once_without_claiming_alignment_measurement():
    r,g,accepted,stops,events=setup()
    g.gesture(row(1_000_000_000),1_100_000_000)
    g.gesture(row(1_200_000_000),1_300_000_000)
    assert len(accepted)==1 and not stops
    assert accepted[0]['confirmation_kind']=='OPERATOR_GESTURE_NOT_ALIGNMENT_MEASUREMENT'
    assert events[-1][1]['pose_verified'] is False
    r.request=dict(r.request,request_id='R2')
    g.gesture(row(1_400_000_000),1_500_000_000)
    assert len(accepted)==1


def test_stale_and_duplicate_thumb_do_not_confirm():
    r,g,accepted,stops,events=setup()
    g.gesture(row(1_000_000_000),1_400_000_000)
    assert not accepted


def test_request_closed_during_camera_response_is_ignored_without_stopping():
    r,g,accepted,stops,events=setup()
    def closed(value):raise RuntimeError('NO_ACTIVE_SIGNAL_REQUEST')
    r.accept_signal=closed
    g.gesture(row(1_000_000_000),1_100_000_000)
    assert not stops and events[-1][0]=='GESTURE_RESPONSE_IGNORED'
    g.gesture(row(2_000_000_000,request='old'),2_100_000_000)
    g.gesture(row(2_000_000_000),2_100_000_000)
    assert not accepted


def test_open_hand_without_handover_capability_never_becomes_stop():
    r,g,accepted,stops,events=setup();r.request=None
    for n in range(12):
        t=1_000_000_000+n*100_000_000
        sample=row(t,'OPEN_HAND');sample['candidate_event']=None
        g.gesture(sample,t)
    assert not stops and not accepted
    assert events[-1][0]=='GESTURE_HANDOVER_UNAVAILABLE'


def test_interrupted_or_stale_open_hand_does_not_stop():
    r,g,accepted,stops,events=setup();r.request=None
    for n in range(5):
        t=1_000_000_000+n*100_000_000
        g.gesture(row(t,'OPEN_HAND'),t)
    g.gesture(row(1_500_000_000,'FIST'),1_500_000_000)
    g.gesture(row(2_000_000_000,'OPEN_HAND'),2_500_000_000)
    assert not stops and not accepted


import pytest


@pytest.mark.parametrize('kind',['ALIGNMENT_READY','HELP_READY','ASSEMBLY_ACK'])
def test_thumb_confirms_each_active_stage_and_never_reuses_old_request(kind):
    r,g,accepted,stops,events=setup();r.request['kind']=kind
    g.gesture(row(1_000_000_000),1_100_000_000)
    assert len(accepted)==1 and accepted[0]['ready'] and not stops
    r.request=dict(r.request,request_id='R2')
    g.gesture(row(1_200_000_000),1_300_000_000)
    assert len(accepted)==1
    g.gesture(row(1_400_000_000,request='R2'),1_500_000_000)
    assert len(accepted)==2


def test_open_palm_receives_only_during_handover_and_presence_stays_fresh():
    r,g,accepted,stops,events=setup();r.request['kind']='RECEIVE'
    sample=row(1_000_000_000,'OPEN_HAND')
    sample['candidate_event']='OPEN_HAND_HELD_ORIENTATION_UNKNOWN'
    g.gesture(sample,1_100_000_000)
    assert accepted[-1]['receiving_ready'] and not stops
    sample=row(1_200_000_000,'OPEN_HAND');sample['candidate_event']=None
    g.gesture(sample,1_300_000_000)
    assert accepted[-1]['receiving_ready']
    sample=row(1_400_000_000);sample['hands']=[]
    g.gesture(sample,1_500_000_000)
    assert not accepted[-1]['hand_present'] and not accepted[-1]['receiving_ready']
    sample=row(1_600_000_000,'OPEN_HAND');sample['candidate_event']=None
    g.gesture(sample,1_700_000_000)
    assert not accepted[-1]['receiving_ready'] and not stops


def test_missing_or_stale_hand_does_not_authorize_release_or_absence():
    r,g,accepted,_,_=setup();r.request['kind']='RECEIVE'
    sample=row(1_000_000_000);sample['hands']=[]
    g.gesture(sample,1_400_000_000)
    assert not accepted
    sample=row(2_000_000_000,'OPEN_HAND',request='old')
    sample['candidate_event']='OPEN_HAND_HELD_ORIENTATION_UNKNOWN'
    g.gesture(sample,2_100_000_000)
    assert not accepted


def test_fake_camera_sample_is_never_accepted_as_real_sensor():
    r,g,accepted,_,_=setup();r.raw=SimpleNamespace(mode='REAL')
    sample=row(1_000_000_000);sample['provenance']='SYNTHETIC'
    g.gesture(sample,1_100_000_000)
    assert not accepted
    r.raw.mode='MOCK';sample=row(1_200_000_000);sample['provenance']='SYNTHETIC'
    g.gesture(sample,1_300_000_000)
    assert accepted[-1]['source']=='FAKE'


def test_open_palm_during_eligible_loaded_motion_requests_handover_instead_of_stop():
    r,g,accepted,stops,events=setup();r.request=None;requested=[]
    r.request_handover=lambda:requested.append(True) or True
    for n in range(12):
        t=1_000_000_000+n*100_000_000
        sample=row(t,'OPEN_HAND');sample['candidate_event']=None
        g.gesture(sample,t)
    assert requested==[True] and not stops and not accepted
    assert events[-1][0]=='GESTURE_HANDOVER_REQUESTED'


def test_held_palm_is_not_reinterpreted_as_stop_during_committed_handover():
    r,g,accepted,stops,events=setup();r.request=None;r.handover_active=True
    for n in range(15):
        t=1_000_000_000+n*100_000_000
        g.gesture(row(t,'OPEN_HAND'),t)
    assert not stops and not accepted
