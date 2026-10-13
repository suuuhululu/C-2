"""Gesture waiting and explicit checkpoint resume; all Robot I/O is mocked."""
from copy import deepcopy
from uuid import uuid4
import pytest
from test_integration_runtime import setup,signal
from test_continuous_transport import trial


def resume(rt,document):
    session=deepcopy(document['session'])
    session.update(execution_id=str(uuid4()),resume_current_revision=rt.plan['current_revision'])
    rt.start(document['step'],document['d_profile'],session,resume=True)


def respond(rt):
    if rt.request:
        if rt.request['kind']=='RECEIVE':signal(rt,hand_present=True,receiving_ready=True)
        else:signal(rt,ready=True)


@pytest.mark.parametrize('loss',['shape','stale'])
def test_receive_loss_before_open_waits_again_at_same_pose_and_opens_only_once(loss):
    rt,raw,events,clock,doc=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    record=rt.record;withdrawn=[];waiting=[]
    def observe(event,data):
        record(event,data)
        if event=='GRIP_STARTED' and data['label']=='DIRECT_HANDOVER' and not withdrawn:
            withdrawn.append(True)
            if loss=='shape':signal(rt,hand_present=True,receiving_ready=False)
            else:rt.signal=(rt.signal[0],clock()-rt.session.value['frame_max_age_s']-.01)
        if event=='HANDOVER_RECEIVE_REOPENED':
            waiting.append(deepcopy(raw.value['posx']))
            assert raw.value['gripper_status']==2 and len(raw.grips)==2 and raw.stops==0
    rt.record=observe;clock.hook=lambda:respond(rt)
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert len(waiting)==1 and len(raw.grips)==3 and raw.stops==0
    assert [v['label'] for e,v in events if e=='GRIP_SUCCEEDED'].count('PICKUP_CLOSE')==1
    assert [v['label'] for e,v in events if e=='GRIP_SUCCEEDED'].count('DIRECT_HANDOVER')==1
    assert not any(e=='EXECUTION_HELD' for e,v in events)
    requests=[v['request_id'] for e,v in events if e=='SIGNAL_REQUEST' and v['kind']=='RECEIVE']
    assert len(set(requests))>=3


def test_explicit_stop_before_handover_open_resumes_same_step_without_pickup_or_transport_replay():
    rt,raw,events,clock,doc=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    record=rt.record;stopped=[]
    def observe(event,data):
        record(event,data)
        if event=='GRIP_STARTED' and data['label']=='DIRECT_HANDOVER' and not stopped:
            stopped.append(True);rt.session.request_stop()
    rt.record=observe;clock.hook=lambda:respond(rt)
    result=rt.run()
    assert result['status']=='STOPPED' and rt.can_resume() and not rt.handover_release_sent
    assert len(raw.grips)==2
    moves=deepcopy(raw.moves);requests=[v['request_id'] for e,v in events if e=='SIGNAL_REQUEST']
    resume(rt,doc)
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert raw.moves==moves and len(raw.grips)==3
    assert rt.handover_release_sent
    assert [v['label'] for e,v in events if e=='GRIP_SUCCEEDED'].count('PICKUP_CLOSE')==1
    new_requests=[v['request_id'] for e,v in events if e=='SIGNAL_REQUEST']
    assert len(set(new_requests))==len(new_requests) and len(new_requests)>len(requests)


@pytest.mark.parametrize('kind,reason',[('help','HELP_READY_TIMEOUT'),('ack','ASSEMBLY_ACK_TIMEOUT')])
def test_thumb_timeout_is_resumable_and_never_finishes_with_missing_cue(kind,reason):
    rt,raw,events,clock,doc=setup()
    rt.profile['operator_cue_timeout_holds']=doc['d_profile']['operator_cue_timeout_holds']=True
    rt.operations=[(kind,None)]
    result=rt.run()
    assert result['status']=='RECOVERY_REQUIRED' and result['reason']==reason
    assert rt.can_resume() and rt.cursor==0 and not raw.grips and not raw.moves
    assert not any(e in ('INSPECTION_REQUIRED','ASSEMBLY_CUE_FINISHED') for e,v in events)
    old=next(v['request_id'] for e,v in events if e=='SIGNAL_REQUEST')
    resume(rt,doc)
    # An old thumbs-up cannot confirm the reopened request.
    def fresh():
        if rt.request:
            with pytest.raises(ValueError,match='STALE_SIGNAL'):
                rt.accept_signal(dict(rt.request,request_id=old,sequence=rt.signal_seq+1,
                    source='FAKE',ready=True,verified=True))
            signal(rt,ready=True)
    clock.hook=fresh
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert not raw.moves and not raw.grips and rt.cursor==1


@pytest.mark.parametrize('failure',['ack_unknown','completion_unverified'])
def test_handover_open_already_sent_is_not_replayed_when_result_is_uncertain(failure):
    rt,raw,events,clock,doc=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    command=raw.command_gripper
    def uncertain(width,force):
        command(width,force)
        if rt.operations[rt.cursor][0]=='handover':
            if failure=='ack_unknown':raise RuntimeError('OPEN_ACK_UNKNOWN')
            raw.value['gripper_width_mm']=40.
    raw.command_gripper=uncertain;clock.hook=lambda:respond(rt)
    assert rt.run()['status']=='RECOVERY_REQUIRED'
    assert rt.handover_release_sent and not rt.can_resume() and len(raw.grips)==3
    with pytest.raises(RuntimeError,match='STEP_BUSY_OR_INSPECTION_PENDING'):resume(rt,doc)
    assert len(raw.grips)==3


@pytest.mark.parametrize('change',['pose','current'])
def test_resume_rejects_changed_robot_pose_or_current_before_any_open(change):
    rt,raw,events,clock,doc=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    record=rt.record
    def stop(event,data):
        record(event,data)
        if event=='GRIP_STARTED' and data['label']=='DIRECT_HANDOVER':rt.session.request_stop()
    rt.record=stop;clock.hook=lambda:respond(rt)
    assert rt.run()['status']=='STOPPED' and rt.can_resume()
    session=deepcopy(doc['session']);session.update(execution_id=str(uuid4()),resume_current_revision=rt.plan['current_revision'])
    if change=='pose':raw.value['posx'][0]+=2.
    else:session['resume_current_revision']+=1
    with pytest.raises(RuntimeError,match='RESUME_STATE_CHANGED|RESUME_REQUIRES_LATEST_CURRENT'):
        rt.start(doc['step'],doc['d_profile'],session,resume=True)
    assert len(raw.grips)==2


def test_known_near_end_blend_timeout_resume_finishes_current_endpoint_without_old_waypoints():
    rt,raw,events,clock,doc=trial(noncontact_force_guard=False)
    config=dict(transit_position_tolerance_mm=10.,transit_orientation_tolerance_deg=5.,finish_endpoint=True)
    rt.profile['transport_blending'].update(config);doc['d_profile']['transport_blending'].update(config)
    targets=deepcopy(rt.operations[1][1][0]);held=rt.operations[1][1][1]
    rt.cursor=1;rt.pending='blend';rt.blend_command_sent=True
    rt.state='RECOVERY_REQUIRED';rt.recovery_reason='BLEND_MOTION_TIMEOUT'
    raw.value.update(posx=targets[-1].copy(),gripper_status=held)
    raw.value['posx'][0]+=6.2
    rt.driver.stop();rt.stopped_sample=deepcopy(rt.driver.snapshot)
    assert rt.can_resume()
    resume(rt,doc)
    assert rt.operations[1][0]=='move' and rt.operations[1][1][0]=='BLEND_RESUME_ENDPOINT'
    assert rt.operations[1][1][1]==targets[-1]
    before=len(raw.moves)
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert raw.moves[before]==targets[-1]
    assert raw.moves[before][:2]!=targets[0][:2]


def test_known_moveline_timeout_can_resume_but_unknown_ack_cannot():
    rt,raw,events,clock,doc=setup()
    target=raw.value['posx'].copy();target[0]+=20.
    rt.operations=[('move',('KNOWN_TARGET',target,0,False))]
    rt.pending='move';rt.state='RECOVERY_REQUIRED';rt.recovery_reason='MOTION_TIMEOUT'
    rt.driver.stop();rt.stopped_sample=deepcopy(rt.driver.snapshot)
    assert rt.can_resume()
    rt.driver.command_outcome_unknown=True
    assert not rt.can_resume()
    rt.driver.command_outcome_unknown=False
    resume(rt,doc)
    assert rt.run()['status']=='AWAITING_INSPECTION' and raw.moves[-1]==target


@pytest.mark.parametrize('kind,signal_kind',[('help','HELP_READY'),('ack','ASSEMBLY_ACK'),('contact','ALIGNMENT_READY')])
def test_button_confirms_missing_thumb_after_timeout_without_robot_stop_or_new_request(kind,signal_kind):
    rt,raw,events,clock,doc=setup()
    rt.profile['operator_cue_buttons']=True
    # Alignment is exercised as the same operator wait, without sending contact motion.
    if kind!='contact':rt.operations=[(kind,None)]
    record=rt.record;confirmed=[]
    def click(event,data):
        record(event,data)
        if event=='OPERATOR_CONFIRMATION_REQUIRED':
            assert data['kind']==signal_kind and raw.stops==0 and not raw.grips and not raw.moves
            assert not any(e=='INSPECTION_REQUIRED' for e,v in events)
            confirmed.append(data['request_id']);rt.confirm_operator(data['request_id'])
    rt.record=click
    if kind=='contact':assert rt.wait_signal(signal_kind,1.) is True
    else:assert rt.run()['status']=='AWAITING_INSPECTION'
    assert len(confirmed)==1 and raw.stops==0 and not raw.moves and not raw.grips
    rows=[v for e,v in events if e=='OPERATOR_CONFIRMATION_ACCEPTED']
    assert rows[0]['source']=='HMI' and not rows[0]['assembly_completion'] and not rows[0]['current_update']
    assert not any(e=='EXECUTION_HELD' for e,v in events)


def test_receive_button_opens_once_even_with_unknown_camera_and_no_hand_sensor_confirmation():
    rt,raw,events,clock,doc=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    rt.profile['operator_cue_buttons']=True
    record=rt.record;clicked=[]
    def click(event,data):
        record(event,data)
        if event=='SIGNAL_REQUEST':
            if data['kind']=='RECEIVE':
                assert raw.value['gripper_status']==2 and len(raw.grips)==2
                clicked.append(data['request_id']);rt.confirm_operator(data['request_id'])
            else:rt.confirm_operator(data['request_id'])
        if event=='GRIP_STARTED' and data['label']=='DIRECT_HANDOVER':
            # The explicit human answer remains valid when camera classification is UNKNOWN.
            assert rt.operator_receive_confirmed
            if rt.request:signal(rt,hand_present=True,receiving_ready=False)
    rt.record=click
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert len(clicked)==1 and len(raw.grips)==3 and raw.stops==0
    assert not rt.operator_receive_confirmed
    assert [v['label'] for e,v in events if e=='GRIP_SUCCEEDED'].count('DIRECT_HANDOVER')==1
    assert [v['label'] for e,v in events if e=='GRIP_SUCCEEDED'].count('PICKUP_CLOSE')==1
    assert not any(e=='EXECUTION_HELD' for e,v in events)


def test_receive_button_is_explicit_scoped_and_not_reused_after_stop_or_for_another_request():
    rt,raw,events,clock,doc=setup()
    rt.request=dict(request_id='active',kind='RECEIVE',execution_id=rt.session.value['execution_id'],
        **{k:rt.plan[k] for k in ('plan_id','step_id','current_revision')})
    with pytest.raises(RuntimeError,match='OPERATOR_CUE_BUTTONS_DISABLED'):rt.confirm_operator('active')
    rt.profile['operator_cue_buttons']=doc['d_profile']['operator_cue_buttons']=True
    with pytest.raises(ValueError,match='STALE_SIGNAL'):rt.confirm_operator('old')
    assert not rt.operator_receive_confirmed
    rt.confirm_operator('active')
    assert rt.operator_receive_confirmed
    rt.operations=[('help',None)];rt.pending='help';rt.session.request_stop()
    assert rt.run()['status']=='STOPPED'
    with pytest.raises(RuntimeError,match='NO_ACTIVE_SIGNAL_REQUEST'):rt.confirm_operator('active')
    resume(rt,doc)
    assert not rt.operator_receive_confirmed
