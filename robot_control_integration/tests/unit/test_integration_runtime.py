from copy import deepcopy
from uuid import uuid4
import pytest
from app.assembly_step_runner import StepReplayDriver, replay_profile
from app.integration_runtime import StepRuntime
from scripts.robot_integration_fixture import document


class Clock:
    def __init__(self): self.t=0.; self.hook=lambda:None
    def __call__(self): return self.t
    def sleep(self, delay): self.t+=delay; self.hook()


def setup(**kwargs):
    d=document(**kwargs); clock=Clock(); events=[]
    raw=StepReplayDriver(d['d_profile']['steps']['fake/S01']['reference_pose'])
    rt=StepRuntime(raw, dict(tcp='GripperDA_v4',tool='ToolWeight0'),
                   lambda e,v:events.append((e,deepcopy(v))), clock=clock, sleep=clock.sleep)
    rt.start(d['step'],d['d_profile'],d['session'])
    return rt,raw,events,clock,d


def signal(rt, **fields):
    rt.accept_signal(dict(rt.request, sequence=rt.signal_seq+1, source='FAKE',verified=True,**fields))


@pytest.mark.parametrize('brick,color,angle', [('2x2x1','yellow',0),('2x2x1','blue',0),
    ('2x3x1','yellow',0),('2x3x1','yellow',90),('2x3x1','blue',0),('2x3x1','blue',90),
    ('1x2x1','red',0),('1x2x1','red',90)])
@pytest.mark.parametrize('layer',range(1,6))
def test_final_mvp_robot_combinations_wait_for_b(brick,color,angle,layer):
    rt,raw,events,_,_=setup(brick_type=brick,color=color,angle=angle,layer=layer)
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION', result
    assert raw.value['gripper_status']==0 and len(raw.grips)==3
    assert [e for e,_ in events].count('CONTACT_SUCCEEDED')==1
    assert not result['current_update'] and not result['assembly_completion']
    with pytest.raises(RuntimeError,match='INSPECTION_PENDING'):
        rt.start(*[document()[k] for k in ('step','d_profile','session')])


def test_explicit_no_vision_trial_finishes_without_b_current_or_inspection():
    d = document()
    d['step']['current_revision'] = d['session']['current_revision'] = None
    d['session']['no_vision_trial'] = True
    clock, events = Clock(), []
    raw = StepReplayDriver(d['d_profile']['steps']['fake/S01']['reference_pose'])
    rt = StepRuntime(raw, dict(tcp='GripperDA_v4',tool='ToolWeight0'),
        lambda e,v:events.append((e,deepcopy(v))), clock=clock, sleep=clock.sleep)
    rt.start(d['step'],d['d_profile'],d['session'])
    assert rt.run()['status'] == 'IDLE'
    assert raw.value['gripper_status'] == 0
    result = next(v for e,v in events if e == 'TRIAL_STEP_EXECUTED')
    assert result['current_revision'] is None
    assert not result['current_update'] and not result['assembly_completion'] and not result['vision_confirmed']
    assert not any(e in ('B_DECISION','INSPECTION_REQUIRED') for e,_ in events)
    d['session']['execution_id'] = str(uuid4())
    rt.start(d['step'],d['d_profile'],d['session'])
    assert rt.run()['status'] == 'IDLE'


@pytest.mark.parametrize('mode,assistance,revision', [('ROBOT_GRIP','HOLD',None),
    ('HUMAN_ASSEMBLY','MANUAL_ASSEMBLY',None),('ROBOT_GRIP','NONE',0)])
def test_no_vision_trial_rejects_help_or_b_revision_before_motion(mode,assistance,revision):
    d = document(mode=mode,assistance=assistance)
    d['step']['current_revision'] = d['session']['current_revision'] = revision
    d['session']['no_vision_trial'] = True
    raw = StepReplayDriver(d['d_profile']['steps']['fake/S01']['reference_pose'])
    rt = StepRuntime(raw,dict(tcp='GripperDA_v4',tool='ToolWeight0'),lambda *args:None)
    with pytest.raises(ValueError,match='NO_VISION_TRIAL'):
        rt.start(d['step'],d['d_profile'],d['session'])
    assert not raw.moves and not raw.grips


def test_no_vision_stop_does_not_emit_step_completion():
    d = document()
    d['step']['current_revision'] = d['session']['current_revision'] = None
    d['session']['no_vision_trial'] = True
    clock, events = Clock(), []
    raw = StepReplayDriver(d['d_profile']['steps']['fake/S01']['reference_pose'])
    rt = StepRuntime(raw,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
        lambda e,v:events.append((e,deepcopy(v))),clock=clock,sleep=clock.sleep)
    rt.start(d['step'],d['d_profile'],d['session'])
    clock.hook = lambda:rt.session.request_stop() if rt.cursor >= 5 else None
    assert rt.run()['status'] == 'STOPPED'
    assert not any(e=='TRIAL_STEP_EXECUTED' for e,_ in events)


@pytest.mark.parametrize('ready', [True, False])
def test_real_trial_contact_waits_for_actual_alignment_or_holds(monkeypatch, ready):
    # REAL 분기만 replay driver로 검사한다. 장치 생성/연결 없음.
    import app.integration_runtime as module
    rt, raw, events, clock, _ = setup()
    rt.no_vision_trial = True
    rt.session.value.update(no_vision_trial=True, trial_alignment_pending=True)
    raw.mode = 'REAL'
    rt.operations = [('contact',None)]
    validations, contacts = [], []
    monkeypatch.setattr(module,'validate_execution',lambda *a:validations.append(deepcopy(a[2])))
    def pressure(*args, **kwargs):
        contacts.append('contact')
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED',final_sample=raw.sample())
    monkeypatch.setattr(module,'press',pressure)
    def respond():
        if rt.request and ready:
            rt.accept_signal(dict(rt.request,sequence=rt.signal_seq+1,source='HMI',verified=True,
                                  ready=True,observed_monotonic_s=clock()))
    clock.hook = respond
    result = rt.run()
    if ready:
        assert result['status']=='IDLE', result
        assert contacts==['contact'] and len(validations)==1
        assert not validations[0]['trial_alignment_pending']
        assert validations[0]['alignment_evidence_ref']=='THIS_EXECUTION_OPERATOR_ALIGNMENT'
        assert any(e=='TRIAL_STEP_EXECUTED' for e,_ in events)
    else:
        assert result['status']=='RECOVERY_REQUIRED', result
        assert contacts==[] and validations==[]
        assert not any(e=='TRIAL_STEP_EXECUTED' for e,_ in events)


@pytest.mark.parametrize('fault',[None,'grip','position','tcp'])
def test_full_trial_automatic_contact_uses_actual_stopped_grasp_without_gesture(monkeypatch,fault):
    import app.integration_runtime as module
    rt,raw,events,clock,_=setup()
    rt.session.value.update(b_observation_kind='SYNTHETIC',operator_review_ref='UNIT_REVIEW',
                            trial_alignment_pending=False,alignment_evidence_ref=None)
    pre=next(args[1] for kind,args in rt.operations if kind=='move' and args[0]=='PRE_CONTACT')
    raw.value.update(posx=pre.copy(),gripper_status=2,gripper_width_mm=40.)
    raw.mode='REAL';rt.operations=[('contact',None)]
    calls=[]
    monkeypatch.setattr(module,'validate_execution',lambda *args:None)
    def pressure(*args,**kwargs):
        calls.append(kwargs)
        return dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED',final_sample=raw.sample())
    monkeypatch.setattr(module,'press',pressure)
    if fault=='grip':raw.value['gripper_status']=0
    if fault=='position':raw.value['posx'][0]+=2.
    if fault=='tcp':raw.value['tcp']='WRONG_TCP'
    result=rt.run()
    assert not [e for e,_ in events if e=='SIGNAL_REQUESTED']
    assert not rt.session.value['alignment_evidence_ref']
    if fault is None:
        assert result['status']=='AWAITING_INSPECTION',result
        assert len(calls)==1 and any(e=='AUTOMATIC_CONTACT_READY' for e,_ in events)
    else:
        assert result['status']=='RECOVERY_REQUIRED',result
        assert not calls and not any(e=='CONTACT_SUCCEEDED' for e,_ in events)


def test_alignment_timeout_can_resume_at_pre_contact_but_started_contact_cannot(monkeypatch):
    import app.integration_runtime as module
    rt,raw,events,clock,d=setup()
    rt.no_vision_trial=True;rt.session.value.update(no_vision_trial=True,trial_alignment_pending=True)
    pre=next(args[1] for kind,args in rt.operations if kind=='move' and args[0]=='PRE_CONTACT')
    raw.value.update(posx=pre.copy(),gripper_status=2,gripper_width_mm=40.)
    raw.mode='REAL'
    rt.operations=[('contact',None)]
    monkeypatch.setattr(module,'validate_execution',lambda *a:None)
    result=rt.run()
    assert result['reason']=='OPERATOR_ALIGNMENT_TIMEOUT'
    assert rt.can_resume() and not rt.contact_started
    assert next(v for e,v in events if e=='EXECUTION_HELD')['resume_allowed']
    rt.contact_started=True
    assert not rt.can_resume()


@pytest.mark.parametrize('source',['HMI','SENSOR'])
def test_fresh_operator_alignment_answer_survives_following_stop_window(source):
    rt,raw,events,clock,d=setup();original=rt.driver.stillness;sent=[]
    def stillness(**kwargs):
        if rt.request and not sent:
            rt.accept_signal(dict(rt.request,sequence=0,source=source,verified=True,ready=True,
                observed_monotonic_s=clock(),confirmation_kind='OPERATOR_GESTURE_NOT_ALIGNMENT_MEASUREMENT'))
            sent.append(True);clock.sleep(.4)
        return original(**kwargs)
    rt.driver.stillness=stillness
    assert rt.wait_signal('ALIGNMENT_READY',2.) is True
    assert sent and rt.request is None


@pytest.mark.parametrize('changed', [False, True])
def test_trial_real_start_is_bound_to_the_pose_used_by_a(monkeypatch, changed):
    import app.integration_runtime as module
    d=document()
    d['step']['current_revision']=d['session']['current_revision']=None
    value=d['session']
    value.update(backend='REAL',provenance='LIVE_D_RUNTIME',source_epoch='LIVE_UNIT_NO_DEVICE',
        no_vision_trial=True,exclusive_control_reviewed=True,device_feedback_reviewed=True,
        stillness_parameters_reviewed=True,hand_clear_reviewed=True,
        d_runtime=dict(execution_id=value['execution_id']))
    raw=StepReplayDriver(d['d_profile']['steps']['fake/S01']['reference_pose'])
    raw.mode='REAL'
    value['planned_start_pose']=raw.value['posx'].copy()
    if changed:value['planned_start_pose'][0]+=.1
    # REAL admission은 C2의 별도 무장치 계약 검사에서 검증한다.
    monkeypatch.setattr(module,'validate_execution',lambda *a:None)
    clock=Clock()
    rt=StepRuntime(raw,dict(tcp='GripperDA_v4',tool='ToolWeight0'),lambda *a:None,
        clock=clock,sleep=clock.sleep)
    if changed:
        with pytest.raises(RuntimeError,match='START_STATE_CHANGED'):
            rt.start(d['step'],d['d_profile'],value)
    else:
        rt.start(d['step'],d['d_profile'],value)
        assert rt.state=='RUNNING'
    assert not raw.moves and not raw.grips


@pytest.mark.parametrize('direct',[False,True])
def test_human_tray_or_direct_then_ten_second_inspection(direct):
    rt,raw,events,clock,_=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    def hook():
        if rt.request and rt.request['kind']=='RECEIVE':
            signal(rt,hand_present=direct,receiving_ready=direct)
    clock.hook=hook
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    labels=[v['label'] for e,v in events if e=='MOVE_STARTED']
    assert ('TRAY_LOWER' in labels) is (not direct)
    assert not [e for e,_ in events if e=='CONTACT_SUCCEEDED']
    assert clock.t>=10. and raw.value['gripper_status']==0
    assert not [e for e,_ in events if e=='HUMAN_ACK_TIMEOUT_CONTINUE']


def test_hand_without_readiness_does_not_descend_or_open_after_timeout():
    rt,raw,events,clock,_=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    opened=[None]
    def hook():
        if rt.request and rt.request['kind']=='RECEIVE':
            if opened[0] is None:opened[0]=clock.t
            signal(rt,hand_present=True,receiving_ready=False)
            if clock.t-opened[0]>5:rt.session.request_stop()
    clock.hook=hook
    result=rt.run()
    assert result['status']=='STOPPED'
    assert raw.value['gripper_status']==2 and len(raw.grips)==2
    assert not [v for e,v in events if e=='MOVE_STARTED' and v['label']=='TRAY_LOWER']


def test_help_requested_after_pre_contact_stillness():
    rt,_,events,clock,_=setup(assistance='HOLD')
    clock.hook=lambda:signal(rt,ready=True) if rt.request else None
    assert rt.run()['status']=='AWAITING_INSPECTION'
    reached=next(i for i,(e,v) in enumerate(events) if e=='MOVE_SUCCEEDED' and v['label']=='PRE_CONTACT')
    help_index=next(i for i,(e,v) in enumerate(events) if e=='SIGNAL_REQUEST' and v['kind']=='HELP_READY')
    assert reached<help_index
    assert any(e=='HELP_MAINTAIN' for e,_ in events)
    assert not any(e=='HELP_RELEASE_GUIDANCE' for e,_ in events)


def test_press_and_hold_waits_for_thumb_then_releases_without_robot_force_press():
    rt,raw,events,clock,_=setup(assistance='PRESS_AND_HOLD')
    clock.hook=lambda:signal(rt,ready=True) if rt.request else None
    assert rt.run()['status']=='AWAITING_INSPECTION'
    labels=[v['label'] for e,v in events if e=='MOVE_SUCCEEDED']
    assert labels.index('PRE_CONTACT') < labels.index('SUPPORTED_NEAR_CONTACT')
    assert not any(e=='CONTACT_SUCCEEDED' for e,_ in events)
    assert any(e=='SIGNAL_REQUEST' and v['kind']=='HELP_READY' for e,v in events)
    assert any(e=='SIGNAL_REQUEST' and v['kind']=='ASSEMBLY_ACK' for e,v in events)
    assert raw.value['gripper_status']==0
    assert not any(e=='HELP_RELEASE_GUIDANCE' for e,_ in events)
    rt.inspection(dict(plan_id=rt.plan['plan_id'],step_id=rt.plan['step_id'],
        execution_id=rt.session.value['execution_id'],decision='KEEP',
        current=dict(current_revision=1,blocks=[rt.plan['block']])))
    assert any(e=='HELP_RELEASE_GUIDANCE' for e,_ in events)


def test_stop_resume_keeps_completed_pickup_and_uses_new_session():
    rt,raw,events,clock,d=setup(); stopped=[False]
    def hook():
        if not stopped[0] and rt.cursor>=10:
            stopped[0]=True;rt.session.request_stop()
    clock.hook=hook
    assert rt.run()['status']=='STOPPED'
    assert raw.value['gripper_status']==2
    grips=len(raw.grips); cursor=rt.cursor
    value=dict(d['session'],execution_id=str(uuid4()),resume_current_revision=d['step']['current_revision'])
    rt.start(d['step'],d['d_profile'],value,resume=True)
    assert rt.cursor==cursor
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert len(raw.grips)==grips+1 # release only; pickup wasn't repeated


def test_stop_inside_gripper_command_requires_recovery():
    rt,raw,_,_,d=setup(); original=raw.command_gripper
    def grip(*args): original(*args);rt.session.request_stop()
    raw.command_gripper=grip
    assert rt.run()['status']=='STOPPED'
    value=dict(d['session'],execution_id=str(uuid4()),resume_current_revision=0)
    with pytest.raises(RuntimeError,match='KNOWN_OPERATION'):rt.start(d['step'],d['d_profile'],value,resume=True)


def test_failed_tray_descent_keeps_block_held():
    rt,raw,_,clock,_=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    clock.hook=lambda:signal(rt,hand_present=False,receiving_ready=False) if rt.request else None
    original=raw.move_line_async
    def move(target,*args):
        if target==rt.profile['place_pose']:raise TimeoutError('LOST_MOVE_ACK')
        return original(target,*args)
    raw.move_line_async=move
    assert rt.run()['status']=='RECOVERY_REQUIRED'
    assert raw.value['gripper_status']==2 and len(raw.grips)==2


def test_reinspection_once_and_b_current_not_modified():
    rt,_,events,_,_=setup(); rt.run()
    b=dict(plan_id=rt.plan['plan_id'],step_id=rt.plan['step_id'],execution_id=rt.session.value['execution_id'],decision='UNOBSERVABLE')
    assert rt.inspection(b,conditions_ready=True)=='AWAITING_INSPECTION'
    assert rt.inspection(b,conditions_ready=True)=='WAIT_REINSPECTION'
    assert sum(e=='INSPECTION_REQUIRED' for e,_ in events)==2
    rt.reinspect()
    current=dict(current_revision=1,blocks=[rt.plan['block']])
    keep=dict(b,decision='KEEP',current=current)
    before=deepcopy(keep)
    assert rt.inspection(keep)=='IDLE' and keep==before


def test_revision_change_and_old_signal_are_rejected():
    rt,_,_,_,d=setup()
    rt.request=dict(request_id='new',kind='HELP_READY',execution_id=d['session']['execution_id'],
                    plan_id='FAKE_PLAN',step_id='S01',current_revision=0)
    with pytest.raises(ValueError,match='STALE'):rt.accept_signal(dict(rt.request,request_id='old',source='FAKE',sequence=1,ready=True))
    with pytest.raises(ValueError,match='STALE'):rt.accept_signal(dict(rt.request,current_revision=1,source='FAKE',sequence=1,ready=True))


def test_missing_only_current_step_profile_fails_without_motion():
    d=document();d['d_profile']['steps']['fake/S01']['pickup_pose']=None
    raw=StepReplayDriver([0.,0.,50.,0.,180.,0.]);rt=StepRuntime(raw,{},lambda *a:None)
    with pytest.raises(ValueError,match='pickup_pose'):rt.start(d['step'],d['d_profile'],d['session'])
    assert not raw.grips and not raw.moves


def test_replay_preserves_supplied_measured_widths():
    d=document();d['d_profile']['steps']['fake/S01'].update(pickup_width_mm=35.,release_width_mm=48.)
    p=replay_profile(d['d_profile'],[d['step']])
    assert p['steps']['fake/S01']['pickup_width_mm']==35.
    assert p['steps']['fake/S01']['release_width_mm']==48.


def test_native35_preserves_35_close_48_open_and_contact_cleanup():
    rt,raw,_,_,_=setup()
    # Recreate the runtime to use the supplied widths and native policy, not replay defaults.
    d=document();s=d['d_profile']['steps']['fake/S01'];s.update(pickup_open_width_mm=60.,pickup_width_mm=35.,release_width_mm=48.,
        release_feedback_range_mm=[47.,110.],pickup_start_open_range_mm=[47.,110.])
    d['d_profile']['native_press']=dict(enabled=True,review_ref='FAKE',force_n=35.,seek_above_reference_mm=6.68,hold_s=3.)
    clock=Clock();raw=StepReplayDriver(s['reference_pose']);events=[]
    rt=StepRuntime(raw,dict(tcp='GripperDA_v4',tool='ToolWeight0'),lambda e,v:events.append((e,deepcopy(v))),clock=clock,sleep=clock.sleep)
    rt.start(d['step'],d['d_profile'],d['session'])
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert [g[0] for g in raw.grips]==[60.,35.,48.]
    assert rt.contact['force_released'] and rt.contact['compliance_released']


def test_busy_gripper_is_waited_for_not_mistaken_for_fault():
    rt,raw,_,_,_=setup();sample=raw.sample;count=[0]
    def feedback():
        row=sample()
        if raw.grips and count[0]<2:
            count[0]+=1;row['gripper_status']=1
        return row
    raw.sample=feedback
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert count[0]==2


@pytest.mark.parametrize('actual,accepted', [(45.6,True),(44.1,True),(44.,False)])
def test_release_48_accepts_only_feedback_above_44(actual,accepted):
    rt,raw,events,clock,_=setup()
    rt.plan['settings'].update(release_width_mm=48.,release_feedback_range_mm=[44.1,110.])
    original=raw.command_gripper
    def feedback(width,force):
        original(width,force);raw.value.update(gripper_status=0,gripper_width_mm=actual)
    raw.command_gripper=feedback
    if accepted:
        rt.grip('TRAY_RELEASE',48.,0)
        assert any(e=='GRIP_SUCCEEDED' for e,_ in events)
    else:
        with pytest.raises(TimeoutError,match='GRIP_COMPLETION_NOT_VERIFIED'):
            rt.grip('TRAY_RELEASE',48.,0)
    assert raw.grips==[(48.,40.)]


def test_initial_empty_open_failure_can_resume_but_does_not_repeat_pickup():
    rt,raw,events,clock,d=setup()
    original=raw.command_gripper
    def insufficient(width,force):
        original(width,force);raw.value['gripper_width_mm']=43.9
    raw.command_gripper=insufficient
    assert rt.run()['status']=='RECOVERY_REQUIRED'
    assert rt.cursor==0 and not raw.moves and rt.can_resume()
    assert next(v for e,v in events if e=='EXECUTION_HELD')['resume_allowed']
    raw.command_gripper=original
    value=dict(d['session'],execution_id=str(uuid4()),resume_current_revision=0)
    rt.start(d['step'],d['d_profile'],value,resume=True)
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert [width for width,_ in raw.grips].count(40.)==1


def test_horizontal_blend_and_pickup_rate_are_applied_to_actual_mock_commands():
    d=document();d['d_profile'].update(transport_blending=dict(radius_mm=15.,reviewed=True),
        pickup_descent_velocity=12.,pickup_descent_acceleration=6.)
    clock=Clock();events=[]
    raw=StepReplayDriver(d['d_profile']['steps']['fake/S01']['reference_pose'])
    rt=StepRuntime(raw,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
        lambda e,v:events.append((e,deepcopy(v))),clock=clock,sleep=clock.sleep)
    rt.start(d['step'],d['d_profile'],d['session'])
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert len(raw.blends)==2 and all(b['radius']==15. for b in raw.blends)
    assert all(b['velocity']==[d['d_profile']['transfer_velocity']]*2 for b in raw.blends)
    label=None;rates={}
    for event,data in events:
        if event=='MOVE_STARTED':label=data['label']
        if event=='MOVE_REQUEST' and data['segment']=='DESCENT':rates[label]=data
    assert rates['PICKUP_LOWER']['velocity']==[12.,12.]
    assert rates['PICKUP_LOWER']['acceleration']==[6.,6.]
    assert rates['PRE_CONTACT']['velocity']==[d['d_profile']['descent_velocity']]*2


def test_requested_trial_rates_and_larger_radius_reach_motion_commands():
    d=document();d['d_profile'].update(transport_blending=dict(radius_mm=40.,reviewed=True),
        transfer_velocity=230.4,pickup_descent_velocity=24.,pickup_descent_acceleration=6.,
        assembly_approach_velocity=24.,assembly_approach_acceleration=6.,
        descent_velocity=24.,descent_acceleration=6.,pre_contact_slow_distance_mm=10.)
    clock=Clock();events=[];raw=StepReplayDriver(d['d_profile']['steps']['fake/S01']['reference_pose'])
    rt=StepRuntime(raw,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
        lambda e,v:events.append((e,deepcopy(v))),clock=clock,sleep=clock.sleep)
    rt.start(d['step'],d['d_profile'],d['session'])
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert len(raw.blends)==2 and all(b['radius']==40. and b['velocity']==[230.4]*2 for b in raw.blends)
    label=None;rates={}
    for event,data in events:
        if event=='MOVE_STARTED':label=data['label']
        if event=='MOVE_REQUEST' and data['segment']=='DESCENT':rates[label]=data
    for label in ('PICKUP_LOWER','ASSEMBLY_APPROACH','PRE_CONTACT'):
        assert rates[label]['velocity']==[24.]*2 and rates[label]['acceleration']==[6.]*2
    assert d['d_profile']['force_stop_n']==35.


def test_stop_mid_blend_does_not_restart_the_batch_or_repick():
    rt,raw,events,clock,d=setup()
    rt.profile['transport_blending']=dict(radius_mm=15.,reviewed=True)
    original=raw.move_blending_async
    def interrupted(*args):
        original(*args);rt.session.request_stop()
    raw.move_blending_async=interrupted
    rt.operations=[('blend',([[40.,0.,112.,0.,180.,0.],[40.,40.,112.,0.,180.,0.]],0))]
    raw.value['posx']=[0.,0.,112.,0.,180.,0.]
    assert rt.run()['status']=='STOPPED'
    assert not rt.can_resume() and not raw.grips
    assert next(v for e,v in events if e=='EXECUTION_HELD')['resume_allowed'] is False


@pytest.mark.parametrize('dx,dy,accepted', [(1.182,0.,True),(2.,0.,True),(0.,2.,True),
    (2.01,0.,False),(1.5,1.5,False)])
def test_seated_release_target_xy_tolerance_is_two_mm_radial(dx,dy,accepted):
    rt,raw,events,_,_=setup()
    pose=rt.plan['settings']['reference_pose'].copy()
    pose[0]+=dx;pose[1]+=dy
    raw.value.update(posx=pose,gripper_status=2)
    rt.contact=dict(final_sample=raw.sample())
    width=rt.plan['settings']['release_width_mm']
    if accepted:
        rt.grip('SEATED_RELEASE',width,0)
        assert raw.grips==[(width,40.)]
        assert any(e=='GRIP_SUCCEEDED' for e,_ in events)
    else:
        with pytest.raises(RuntimeError,match='CONTACT_TARGET_DRIFT'):
            rt.grip('SEATED_RELEASE',width,0)
        assert not raw.grips


def test_stop_resume_rejects_changed_actual_pose_or_b_revision():
    rt,raw,_,clock,d=setup();trigger=[False]
    def hook():
        if rt.cursor>=10 and not trigger[0]:trigger[0]=True;rt.session.request_stop()
    clock.hook=hook
    assert rt.run()['status']=='STOPPED'
    value=dict(d['session'],execution_id=str(uuid4()),resume_current_revision=1)
    with pytest.raises(RuntimeError,match='CURRENT_CHECK'):rt.start(d['step'],d['d_profile'],value,resume=True)
    raw.value['posx'][0]+=10
    value.update(execution_id=str(uuid4()),resume_current_revision=0)
    with pytest.raises(RuntimeError,match='STATE_CHANGED'):rt.start(d['step'],d['d_profile'],value,resume=True)


def test_mismatch_waits_for_c_and_unchanged_plan_cannot_continue():
    rt,_,_,_,d=setup();rt.run()
    result=dict(plan_id=rt.plan['plan_id'],step_id=rt.plan['step_id'],execution_id=d['session']['execution_id'],
                decision='CALL_C',current=dict(current_revision=1,blocks=[]))
    assert rt.inspection(result)=='WAIT_C'
    value=dict(d['session'],execution_id=str(uuid4()))
    with pytest.raises(RuntimeError,match='C_APPROVED_NEW_PLAN'):rt.start(d['step'],d['d_profile'],value)


def test_unreviewed_fake_template_is_rejected_by_real_validation_without_device():
    from app.assembly_step_bridge import build_plan
    from app.control_session import validate_execution
    from scripts.robot_integration_fixture import real_template
    d=document();d['session'].update(backend='REAL',provenance='LIVE_D_RUNTIME')
    with pytest.raises(ValueError):validate_execution(build_plan(d['step'],d['d_profile']),d['d_profile'],d['session'],'full')
    template=real_template()
    assert template['d_profile']['steps']['FILL_CASE_ID/S01']['pickup_pose'] is None
    assert template['session']['expires_unix_s']==0


def test_stop_rejects_inspection_result_even_when_robot_already_finished():
    rt,_,_,_,d=setup();rt.run();rt.session.request_stop()
    result=dict(plan_id='FAKE_PLAN',step_id='S01',execution_id=d['session']['execution_id'],decision='KEEP',
                current=dict(current_revision=1,blocks=[d['step']['block']]))
    with pytest.raises(RuntimeError,match='STOP_REQUESTED'):rt.inspection(result)
    assert rt.state=='AWAITING_INSPECTION'


def test_wire_binding_rejects_pose_mismatch_and_accepts_matching_scoped_route():
    from app.integration_motion_binding import verify_motion
    from scipy.spatial.transform import Rotation
    rt,_,_,_,_=setup()
    p=rt.profile;s=rt.plan['settings'];pick=s['pickup_pose'];ref=s['reference_pose'];h=p['clearance_z_mm']
    points=[('LIFT_HOLDING',pick[:2]+[h]+pick[3:])]
    points += [(label,xy+[h]+pick[3:]) for label,xy in [('SUPPLY_20_0',p['supply_transit_xy_mm']),
        ('BODY_BYPASS',p['body_bypass_xy_mm']),('PLACE_BOARD',p['place_pose'][:2])]]
    points += [('TARGET_HIGH',ref[:2]+[h]+pick[3:]),('PRE_CONTACT_HOLDING',ref[:2]+[ref[2]+p['approach_offset_mm']]+pick[3:])]
    def wire(value):return dict(frame_id='base_link',xyz_m=[v/1000 for v in value[:3]],
                               quaternion_xyzw=Rotation.from_euler('ZYZ',value[3:],degrees=True).as_quat().tolist())
    proposal=dict(pickup_tcp_pose=wire(pick),segments=[{}, {},dict(waypoints=[dict(label=l,tcp_pose=wire(v)) for l,v in points])])
    verify_motion(proposal,rt.plan,p)
    proposal['segments'][2]['waypoints'][-1]['tcp_pose']['xyz_m'][2]+=.001
    with pytest.raises(ValueError,match='POSE_DIFFERS'):verify_motion(proposal,rt.plan,p)


def test_motion_timeout_does_not_trigger_next_operation_or_release():
    rt,raw,events,_,_=setup();old=raw.move_line_async
    def move(target,*args):
        if raw.value['gripper_status']==2:raise TimeoutError('MOVE_TIMED_OUT')
        return old(target,*args)
    raw.move_line_async=move
    result=rt.run()
    assert result['status']=='RECOVERY_REQUIRED' and raw.value['gripper_status']==2
    assert not any(e=='INSPECTION_REQUIRED' for e,_ in events)


def test_stop_after_delivery_resumes_inspection_without_another_pickup():
    rt,raw,_,_,d=setup();rt.run();counts=(len(raw.moves),len(raw.grips))
    rt.stop();assert rt.state=='STOPPED'
    value=dict(d['session'],execution_id=str(uuid4()),resume_current_revision=0)
    rt.start(d['step'],d['d_profile'],value,resume=True)
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert counts==(len(raw.moves),len(raw.grips))


def test_withdrawn_hand_before_open_keeps_gripper_closed():
    rt,raw,events,clock,_=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    record=rt.record
    def observe(event,data):
        record(event,data)
        if event=='GRIP_STARTED' and data['label']=='DIRECT_HANDOVER':
            signal(rt,hand_present=True,receiving_ready=False)
        if event=='HANDOVER_RECEIVE_REOPENED':
            assert len(raw.grips)==2 and raw.value['gripper_status']==2
            rt.session.request_stop()
    rt.record=observe
    clock.hook=lambda:signal(rt,hand_present=True,receiving_ready=True) if rt.request else None
    result=rt.run()
    assert result['status']=='STOPPED' and result['reason']=='STOP_REQUESTED'
    assert rt.can_resume() and not rt.handover_release_sent
    assert len(raw.grips)==2 and raw.value['gripper_status']==2
    assert any(e=='HANDOVER_RECEIVE_REOPENED' for e,v in events)


def test_new_hand_before_tray_descent_reopens_receive_and_hands_over_once():
    rt,raw,events,clock,_=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    reopened=[False]
    def hook():
        reopened[0]=any(e=='HANDOVER_RECEIVE_REOPENED' for e,_ in events)
        if rt.request:
            if rt.request['kind']=='RECEIVE':
                signal(rt,hand_present=rt.pending=='tray' or reopened[0],receiving_ready=reopened[0])
            else:signal(rt,ready=True)
    clock.hook=hook
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    assert reopened[0] and raw.value['gripper_status']==0
    labels=[v.get('label') for e,v in events if e=='GRIP_SUCCEEDED']
    assert labels.count('PICKUP_CLOSE')==1 and labels.count('DIRECT_HANDOVER')==1
    assert 'TRAY_RELEASE' not in labels and not any(e=='EXECUTION_HELD' for e,_ in events)
    assert rt.profile['place_pose'] not in raw.moves  # 새 손 감지 후 트레이 하강은 실행하지 않는다.
    requests=[v['request_id'] for e,v in events if e=='SIGNAL_REQUEST' and v['kind']=='RECEIVE']
    assert len(set(requests))>=2


def test_stop_during_tray_descent_resume_requests_fresh_hand_observation():
    rt,raw,events,clock,d=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    stopped=[False]
    def hook():
        if rt.request and rt.request['kind']=='RECEIVE':
            signal(rt,hand_present=False,receiving_ready=False)
        if rt.pending=='tray' and not stopped[0]:
            stopped[0]=True;rt.session.request_stop()
    clock.hook=hook
    assert rt.run()['status']=='STOPPED'
    grips=len(raw.grips)
    value=dict(d['session'],execution_id=str(uuid4()),resume_current_revision=0)
    rt.start(d['step'],d['d_profile'],value,resume=True)
    assert rt.operations[rt.cursor][0]=='receive'
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert len(raw.grips)==grips+1


@pytest.mark.parametrize('mode,assistance',[
    ('ROBOT_GRIP','PRESS'), ('ROBOT_GRIP','HOLD'), ('ROBOT_GRIP','PRESS_AND_HOLD'),
    ('HUMAN_ASSEMBLY','MANUAL_ASSEMBLY'), ('HUMAN_ASSEMBLY','MANUAL_ASSEMBLY_AND_HOLD')])
def test_all_assistance_actions_wait_for_scoped_input_and_b_before_release_guidance(mode,assistance):
    rt,raw,events,clock,d=setup(mode=mode,assistance=assistance)
    def respond():
        if rt.request:
            signal(rt,hand_present=False,receiving_ready=False) if rt.request['kind']=='RECEIVE' else signal(rt,ready=True)
    clock.hook=respond
    assert rt.run()['status']=='AWAITING_INSPECTION'
    requests=[v['kind'] for e,v in events if e=='SIGNAL_REQUEST']
    assisted=assistance!='MANUAL_ASSEMBLY'
    assert ('HELP_READY' in requests) is assisted
    if assistance in ('PRESS','PRESS_AND_HOLD'):
        assert 'ASSEMBLY_ACK' in requests
        assert not any(e=='CONTACT_SUCCEEDED' for e,_ in events)
    if assistance=='HOLD':assert any(e=='CONTACT_SUCCEEDED' for e,_ in events)
    assert not any(e=='HELP_RELEASE_GUIDANCE' for e,_ in events)
    assert rt.inspection(dict(plan_id=rt.plan['plan_id'],step_id='S01',
        execution_id=d['session']['execution_id'],decision='KEEP',
        current=dict(current_revision=1,blocks=[rt.plan['block']])))=='IDLE'
    assert any(e=='HELP_RELEASE_GUIDANCE' for e,_ in events) is assisted


def test_unanswered_help_holds_without_lowering_release_or_contact():
    rt,raw,events,clock,d=setup(assistance='PRESS')
    result=rt.run()
    assert result['status']=='RECOVERY_REQUIRED' and result['reason']=='HELP_READY_TIMEOUT'
    assert not any(e=='CONTACT_SUCCEEDED' for e,_ in events)
    assert not any(e=='INSPECTION_REQUIRED' for e,_ in events)
    assert not any(e=='GRIP_STARTED' and v['label']=='SUPPORTED_RELEASE' for e,v in events)
    assert raw.value['gripper_status']==2


def test_wait_c_stop_uses_driver_stop_and_fresh_stillness_evidence():
    rt,raw,events,_,d=setup()
    rt.run()
    rt.inspection(dict(decision='CALL_C',current=dict(current_revision=1,blocks=[]),
        plan_id=d['step']['plan_id'],step_id=d['step']['step_id'],execution_id=d['session']['execution_id']))
    assert rt.state=='WAIT_C'
    rt.stop()
    assert rt.state=='STOPPED' and rt.stopped_sample is not None
    result=next(v for e,v in events if e=='STOP_VERIFIED')
    assert result['previous_state']=='WAIT_C' and result['actual_stop_verified']
    assert any(e=='STOP_WINDOW_RESULT' and v['stillness_window_verified'] for e,v in events)


def test_processing_error_requires_explicit_reinspection_and_preserves_reason():
    rt,raw,events,_,d=setup()
    rt.run();grips=len(raw.grips);cursor=rt.cursor
    rt.inspection(dict(decision='ERROR',reason='PROCESSING_FAILED',
        plan_id=d['step']['plan_id'],step_id=d['step']['step_id'],execution_id=d['session']['execution_id']),conditions_ready=True)
    assert rt.state=='WAIT_REINSPECTION'
    assert [e for e,_ in events].count('INSPECTION_REQUIRED')==1
    waiting=next(v for e,v in events if e=='REINSPECTION_WAIT')
    assert waiting['inspection_status']=='ERROR' and waiting['reason']=='PROCESSING_FAILED'
    rt.reinspect()
    assert rt.state=='AWAITING_INSPECTION' and rt.cursor==cursor and len(raw.grips)==grips
    assert [e for e,_ in events].count('INSPECTION_REQUIRED')==2


def test_small_fk_roundtrip_difference_is_warning_and_large_difference_is_hold():
    for error,expected in ((.1,'AWAITING_INSPECTION'),(1.,'RECOVERY_REQUIRED')):
        rt,raw,events,clock,d=setup()
        rt.profile['ik_fk_position_tolerance_mm']=.5;rt.profile['ik_fk_orientation_tolerance_deg']=.5
        def fk(p,**kwargs):return [p[0]+error,*p[1:]] if raw.value['gripper_status']==0 else p.copy()
        raw.check_pose=fk
        result=rt.run()
        assert result['status']==expected,result
        assert any(e=='IK_FK_CHECK' and v['position_error_mm']>=error-.001 for e,v in events)
        if error==.1:assert any(e=='IK_FK_NUMERICAL_WARNING' for e,_ in events)
        else:assert not raw.grips[1:] and result['reason']=='IK_FK_ROUNDTRIP_MISMATCH'


def test_empty_return_skips_place_and_loaded_blend_ends_above_assembly():
    rt,raw,events,clock,d=setup()
    p=deepcopy(rt.profile);p.update(empty_return_skip_place=True,transport_blending=dict(radius_mm=15.,reviewed=True))
    ops=rt.make_operations(rt.plan,p,'assembly')
    assert ops[2][0]=='move' and ops[2][1][0]=='BODY_EMPTY'
    assert not any(k=='move' and a[0]=='PLACE_EMPTY' for k,a in ops)
    loaded=next(a[0] for k,a in ops if k=='blend' and a[1]==2)
    assert loaded[-2][:2]==p['place_pose'][:2]
    assert loaded[-1][:2]==rt.plan['settings']['reference_pose'][:2]
    assert not any(k=='move' and a[0]=='TARGET_HIGH' for k,a in ops)


@pytest.mark.parametrize('turn',[0,90])
def test_full_trial_passes_place_in_one_loaded_blend_and_rotates_only_at_target(turn):
    rt,raw,events,clock,d=setup(brick_type='2x3x1',angle=turn)
    rt.profile.update(empty_return_skip_place=True,transport_blending=dict(radius_mm=15.,reviewed=True))
    rt.operations=rt.make_operations(rt.plan,rt.profile,'assembly')
    result=rt.run()
    assert result['status']=='AWAITING_INSPECTION',result
    loaded=raw.blends[-1]['targets']
    assert len(loaded)==4
    assert loaded[-2][:2]==rt.profile['place_pose'][:2]
    assert loaded[-1][:2]==rt.plan['settings']['reference_pose'][:2]
    assert not any(e=='MOVE_STARTED' and v.get('label')=='PLACE_LOADED' for e,v in events)
    rotations=[v for e,v in events if e=='MOVE_STARTED' and v.get('label')=='TARGET_HIGH']
    assert len(rotations)==(1 if turn else 0)


def test_blend_rejection_before_command_can_resume_but_sent_motion_cannot():
    rt,raw,events,clock,d=setup();original=raw.check_pose
    rt.profile['transport_blending']=dict(radius_mm=15.,reviewed=True)
    d['d_profile']=deepcopy(rt.profile)
    rt.operations=rt.make_operations(rt.plan,rt.profile,'assembly')
    def bad(p,**kwargs):
        if p[:2]==rt.profile['body_bypass_xy_mm']:return [p[0]+1.,*p[1:]]
        return original(p,**kwargs)
    raw.check_pose=bad
    result=rt.run()
    assert result['status']=='RECOVERY_REQUIRED' and rt.can_resume()
    assert not raw.blends and not rt.blend_command_sent
    raw.check_pose=original
    session=deepcopy(d['session']);session.update(execution_id=str(uuid4()),resume_current_revision=rt.plan['current_revision'])
    rt.start(d['step'],d['d_profile'],session,resume=True)
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert len(raw.grips)==3


def test_palm_loaded_override_releases_only_after_new_receive_then_requires_thumb():
    rt,raw,events,clock,d=setup();rt.profile['palm_handover_before_contact']=True
    requested=[False]
    def hook():
        if not requested[0] and rt.pending=='move' and rt.operations[rt.cursor][1][0]=='TARGET_HIGH':
            requested[0]=rt.request_handover()
        if rt.request:
            if rt.request['kind']=='RECEIVE':signal(rt,hand_present=True,receiving_ready=True)
            else:signal(rt,ready=True)
    clock.hook=hook
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert requested[0] and raw.grips[-1][0]==rt.plan['settings']['release_width_mm']
    assert not rt.contact_started and rt.contact is None
    assert any(e=='HANDOVER_OVERRIDE' and v['actual_stop_verified'] for e,v in events)
    assert [v['kind'] for e,v in events if e=='SIGNAL_REQUEST']==['RECEIVE','ASSEMBLY_ACK']
    assert [v['label'] for e,v in events if e=='GRIP_SUCCEEDED'].count('PICKUP_CLOSE')==1
    assert rt.plan['mode']=='ROBOT_GRIP' and not any(e=='CONTACT_SUCCEEDED' for e,_ in events)
    assert not rt.request_handover()


def test_early_palm_intent_is_deferred_until_pickup_and_contact_cannot_be_overridden():
    rt,raw,events,clock,d=setup();rt.profile['palm_handover_before_contact']=True
    assert rt.request_handover() and rt.handover_intent_pending
    assert not rt.session.handover_requested and not raw.grips
    def hook():
        if rt.request:
            if rt.request['kind']=='RECEIVE':signal(rt,hand_present=True,receiving_ready=True)
            else:signal(rt,ready=True)
    clock.hook=hook
    assert rt.run()['status']=='AWAITING_INSPECTION'
    assert raw.grips[-1][0]==rt.plan['settings']['release_width_mm'] and not rt.contact_started
    rt.state='RUNNING';rt.contact_started=True;rt.handover_active=False
    assert not rt.request_handover()


def test_stop_during_override_receive_does_not_open_or_emit_inspection():
    rt,raw,events,clock,d=setup();rt.profile['palm_handover_before_contact']=True
    rt.request_handover()
    def hook():
        if rt.request and rt.request['kind']=='RECEIVE':rt.session.request_stop()
    clock.hook=hook
    assert rt.run()['status']=='STOPPED'
    assert raw.value['gripper_status']==2 and len(raw.grips)==2
    assert not any(e=='INSPECTION_REQUIRED' for e,_ in events)


def test_stop_after_pre_descent_recovery_confirms_stop_and_resume_rechecks_receiver():
    rt,raw,events,clock,d=setup(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')
    # 직전 버전에서 하강 전 손 감지로 종료된 상태를 재현한다.
    rt.state='RECOVERY_REQUIRED';rt.pending='tray';rt.recovery_reason='HAND_PRESENT_BEFORE_LOWER'
    raw.value['gripper_status']=2;raw.value['gripper_width_mm']=40.
    rt.stopped_sample=deepcopy(raw.value)
    rt.cursor=next(i for i,(kind,_) in enumerate(rt.operations) if kind=='tray')
    counts=(len(raw.moves),len(raw.grips));events.clear()
    rt.stop()
    assert rt.state=='RECOVERY_REQUIRED' and rt.pending=='tray' and rt.can_resume()
    assert counts==(len(raw.moves),len(raw.grips)) and raw.value['gripper_status']==2
    verified=next(v for e,v in events if e=='STOP_VERIFIED')
    assert verified['actual_stop_verified'] and verified['previous_state']=='RECOVERY_REQUIRED'
    held=next(v for e,v in events if e=='EXECUTION_HELD')
    assert held['resume_allowed'] is True
    value=dict(d['session'],execution_id=str(uuid4()),resume_current_revision=0)
    rt.start(d['step'],d['d_profile'],value,resume=True)
    assert rt.operations[rt.cursor][0]=='receive'
    assert counts==(len(raw.moves),len(raw.grips))
    assert not any(e=='INSPECTION_REQUIRED' for e,_ in events)
