from copy import deepcopy
import math

import pytest

from app.control_session import ControlSession, validate_session
from app.assembly_step_bridge import build_plan, candidate_profile, load_steps
from app.assembly_step_runner import replay_profile
from scripts.robot_control_trial import test_session as session_fixture


class Clock:
    def __init__(self):
        self.t = 0.
    def __call__(self):
        return self.t
    def sleep(self, seconds):
        self.t += seconds


def setup():
    steps = load_steps()
    step = next(s for s in steps if s['case_id'].startswith('02_'))
    profile = replay_profile(candidate_profile(steps), [step])
    plan = build_plan(step, profile)
    events, clock = [], Clock()
    record = lambda e,d: events.append((e, deepcopy(d)))
    value = session_fixture(plan)
    value['expires_unix_s'] = 1000.
    session = ControlSession(value, plan, record, clock=clock, wall=lambda:100.)
    return session, plan, profile, events, clock


def verified_sample(session, request, t, pose='THUMBS_UP'):
    return dict(**session.binding, execution_id=session.value['execution_id'],
        source_epoch=session.value['source_epoch'], request_id=request['request_id'],
        source_ns=t, inference_ns=t, clock_verified=True, frame='synthetic-camera',
        hands=[dict(track_id='one', track_confirmed=True, pose_confirmed=True,
                    pose=pose, surface='back', orientation_confirmed=True)])


@pytest.mark.parametrize('field,value', [('backend',None),('backend','SIM'),('execution_id',''),
    ('source_epoch',None),('expires_unix_s',math.nan),('request_timeout_s',True),
    ('frame_max_age_s',0),('step_id','other'),('current_revision',-1)])
def test_session_rejects_bad_contract_before_devices(field, value):
    s, plan, *_ = setup()
    with pytest.raises(ValueError):
        validate_session(dict(s.value, **{field:value}), plan, backend='TEST')


@pytest.mark.parametrize('value', [None,0,True,math.inf])
def test_missing_or_invalid_stillness_policy_is_not_a_stopped_result(value):
    s, plan, *_ = setup()
    v = deepcopy(s.value); v['stillness']['window_s'] = value
    with pytest.raises(ValueError):
        validate_session(v, plan, backend='TEST')


def test_local_real_review_and_provenance_cannot_be_inferred_from_test():
    s, plan, *_ = setup()
    v = dict(s.value, backend='REAL')
    with pytest.raises(ValueError, match='PROVENANCE'):
        validate_session(v, plan, backend='REAL')
    v.update(provenance='LOCAL_OPERATOR_TRIAL',source_epoch='LIVE_1')
    with pytest.raises(ValueError, match='ONSITE_REVIEW'):
        validate_session(v, plan, backend='REAL')


def test_stop_invalidates_request_and_lease_and_late_yes_is_rejected():
    s, _, _, events, _ = setup()
    lease = s.switch_owner('MOTION', {}, recheck=True)
    req = s.open_request('HUMAN_READY')
    s.request_stop()
    with pytest.raises(RuntimeError, match='STOP_REQUESTED'):
        s.respond(req['request_id'],True,source='HMI')
    with pytest.raises(RuntimeError):
        s.require_lease(lease,'MOTION')
    assert s.request is None and s.lease is None


def test_old_lease_is_rejected_after_applied_local_handoff():
    s, *_ = setup()
    old = s.switch_owner('MOTION',{},recheck=True)
    new = s.switch_owner('CONTACT',{},recheck=True)
    with pytest.raises(RuntimeError,match='LEASE'):
        s.require_lease(old,'MOTION')
    s.require_lease(new,'CONTACT')


def test_human_request_is_one_shot_and_previous_answer_cannot_answer_new_request():
    s, *_ = setup()
    old = s.open_request('HUMAN_READY')
    assert s.respond(old['request_id'],True,source='HMI')
    new = s.open_request('FULL_SEATING')
    with pytest.raises(RuntimeError,match='OLD_HUMAN_REQUEST'):
        s.respond(old['request_id'],True,source='HMI')
    assert s.request['request_id'] == new['request_id']
    assert s.respond(new['request_id'],False,source='HMI') is False


def test_timeout_closes_request_and_does_not_authorize():
    s, _, _, _, clock = setup()
    req = s.open_request('RELEASE')
    clock.t = s.value['request_timeout_s']+1
    with pytest.raises(TimeoutError):
        s.respond(req['request_id'],True,source='HMI')
    assert s.request is None


@pytest.mark.parametrize('pose,answer', [('THUMBS_UP',True),('L',False)])
def test_real_gesture_gate_timing_is_consumed_once_per_question(pose,answer):
    s, _, _, _, clock = setup()
    req = s.open_request('HUMAN_READY')
    outcome = None
    for i in range(22):
        t = 1_000_000_000+i*100_000_000
        clock.t = i*.1
        outcome = s.gesture(verified_sample(s,req,t,pose),t)
        if outcome is not None:
            break
    assert outcome is answer
    assert s.request is None
    assert s.gesture(verified_sample(s,req,t,pose),t) is None


def test_unverified_camera_candidate_is_audit_only_even_after_hold():
    s, _, _, events, _ = setup()
    req = s.open_request('RELEASE')
    row = dict(**s.binding,execution_id=s.value['execution_id'],source_epoch=s.value['source_epoch'],
               preview_request_id=req['request_id'],candidate_event='OPEN_HAND_HELD_ORIENTATION_UNKNOWN',
               pose_verified=False,orientation_verified=False,event=None)
    assert s.gesture(row,10) is None
    assert s.request is not None and s.owner == 'NONE'
    assert any(e == 'UNVERIFIED_GESTURE_CANDIDATE' for e,_ in events)


@pytest.mark.parametrize('field', ['source_epoch','execution_id','step_id','plan_id','current_revision'])
def test_gesture_from_other_execution_or_step_is_rejected(field):
    s, *_ = setup(); req=s.open_request('HUMAN_READY')
    row=verified_sample(s,req,1_000_000_000); row[field]='OLD'
    with pytest.raises(RuntimeError,match='CONTEXT_MISMATCH'):
        s.gesture(row,1_000_000_000)


def test_monotonic_expiry_still_blocks_when_wall_clock_moves_backward():
    s, _, _, _, clock = setup()
    s.wall=lambda:0.
    clock.t=901.
    with pytest.raises(RuntimeError,match='SESSION_EXPIRED'):
        s.check()


def test_fist_to_verified_palm_is_receive_request_and_never_closes_gripper():
    s,_,_,events,_=setup();req=s.open_request('RECEIVE')
    fist=verified_sample(s,req,1_000_000_000,'FIST')
    assert s.gesture(fist,1_000_000_000) is None
    palm=verified_sample(s,req,1_100_000_000,'OPEN_PALM')
    palm['hands'][0]['surface']='palm'
    assert s.gesture(palm,1_100_000_000) is True
    assert s.owner=='NONE' and s.lease is None
    replies=[d for e,d in events if e=='HUMAN_RESPONSE']
    assert replies[-1]['request']['kind']=='RECEIVE'
    assert not replies[-1]['assembly_completion']
