import builtins
from copy import deepcopy
import json
import socket
import sys
from types import SimpleNamespace as NS

import pytest

from scripts import robot_control_trial as cli
from scripts.integrated_replay import replay_all
from app.assembly_step_bridge import read,ROOT
from app.control_driver import execute_step
from app.control_camera import RequestCamera
from test_control_session import setup


@pytest.fixture
def no_devices(monkeypatch):
    def forbid(*args,**kwargs):raise AssertionError('NO_DEVICES_IN_TEST')
    monkeypatch.setattr(socket,'socket',forbid)
    original=builtins.__import__
    def importing(name,*args,**kwargs):
        if name.startswith(('rclpy','dsr_msgs2','pymodbus','mediapipe')):forbid()
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',importing)


def test_all_original_steps_use_integrated_path_with_no_devices(tmp_path,no_devices):
    report=replay_all(tmp_path)
    assert report['steps']==19 and report['cases']==8
    assert report['device_connections']==report['robot_motion_commands']==report['robot_gripper_commands']==0
    assert all(r['status']=='AWAITING_BACKEND_OBSERVATION' for r in report['results'])
    assert all(not r['assembly_completion'] and not r['current_update'] for r in report['results'])
    assert len(list(tmp_path.glob('*.json')))==20


@pytest.mark.parametrize('command', ['preview','run','template'])
def test_default_commands_never_import_device_stack(tmp_path,no_devices,command):
    assert cli.main([command,'--output',str(tmp_path)])==0
    if command=='template':
        session=read(tmp_path/'session.example.json')
        assert not session['exclusive_control_reviewed']
        assert session['expires_unix_s']==0
        assert all(v is None for v in session['stillness'].values())


@pytest.mark.parametrize('arguments', [
    ['run','--next-pickup-profile','missing.json'],
    ['run','--phase','contact','--next-pickup-profile','a.json','--next-pickup-session','b.json'],
    ['replay','--phase','human-ack','--next-pickup-profile','a.json','--next-pickup-session','b.json'],
])
def test_invalid_next_pickup_arguments_rejected_before_devices(arguments,no_devices):
    with pytest.raises(SystemExit) as exc:
        cli.main(arguments)
    assert exc.value.code==2


def reviewed_session(s,profile):
    v=deepcopy(s.value)
    v.update(backend='REAL',provenance='LOCAL_OPERATOR_TRIAL',source_epoch='LIVE_TODAY',
             expires_unix_s=9_999_999_999,profile_id=profile['profile_id'],
             exclusive_control_reviewed=True,device_feedback_reviewed=True,
             stillness_parameters_reviewed=True,hand_clear_reviewed=True,
             alignment_evidence_ref='onsite-alignment')
    return v


def test_real_unreviewed_candidate_fails_before_ros_import(tmp_path,no_devices):
    assert cli.main(['template','--output',str(tmp_path)])==0
    assert cli.main(['run','--execute','--profile',str(tmp_path/'d-profile.json'),
        '--session',str(tmp_path/'session.example.json'),'--output',str(tmp_path/'attempt')])==1
    assert read(tmp_path/'attempt/failure.json')['status']=='INTEGRATION_TRIAL_FAILED'


def test_rotated_y_misalignment_is_blocked_before_contact():
    setup_value=read(ROOT/'interfaces/assembly_held_11_11_l3_cw90.json')
    profile=setup_value['d_profile'];profile['steps'][setup_value['step']['case_id']+'/S01']['physical_reference_reviewed']=True
    from app.assembly_step_bridge import build_plan
    plan=build_plan(setup_value['step'],profile)
    s,*_=setup();v=reviewed_session(s,profile)
    v.update(**{k:plan[k] for k in ('plan_id','step_id','current_revision')})
    with pytest.raises(ValueError,match='XY_COMPENSATION_NOT_MEASURED'):
        cli.preflight(plan,profile,v,'contact')


def test_release_needs_seating_evidence_even_with_reviewed_width():
    s,plan,profile,*_=setup();plan['settings']['physical_reference_reviewed']=True
    profile['profile_id']='D_LOCAL_REVIEW_FIXTURE'
    v=reviewed_session(s,profile)
    with pytest.raises(ValueError,match='SEATING_EVIDENCE'):
        cli.preflight(plan,profile,v,'release')
    v['seating_evidence_ref']='same-step-onsite-seating'
    cli.preflight(plan,profile,v,'release')


def test_direct_library_real_call_cannot_bypass_preflight():
    s,plan,profile,_,clock=setup()
    raw=NS(mode='REAL',sample=lambda:pytest.fail('no device read'))
    with pytest.raises(ValueError,match='BACKEND'):
        execute_step(raw,s,{},plan,profile,lambda *a:True,lambda *a:None)


def test_camera_binds_context_at_reception_and_ignores_frame_from_closed_request():
    s,*_=setup();old=s.open_request('RELEASE')
    camera=RequestCamera.__new__(RequestCamera)
    camera.session=s;camera.latest=None;camera.relay=None;camera.seen=None
    camera.receive(object())
    assert camera.latest[2]['request_id']==old['request_id']
    s.close_request();s.open_request('FULL_SEATING')
    assert camera.poll() is None


def test_real_backend_session_requires_matching_profile():
    s,plan,profile,*_=setup();v=reviewed_session(s,profile);v['profile_id']='other'
    with pytest.raises(ValueError,match='PROFILE_BINDING'):
        cli.preflight(plan,profile,v,'contact')


def test_external_executor_call_waits_for_future_without_nested_spin(monkeypatch):
    from app.assembly_motion_ros import AssemblyMotionRos
    driver=AssemblyMotionRos.__new__(AssemblyMotionRos)
    response=NS(success=True)
    future=NS(done=lambda:True,result=lambda:response)
    driver.client=lambda *a:NS(wait_for_service=lambda **kw:True,call_async=lambda r:future)
    driver.srv=NS(GetRobotState=NS(Request=lambda:NS()))
    driver.config={'timing':{'service_timeout_s':.5}}
    driver.external_executor=True
    driver.ros=NS(spin_until_future_complete=lambda *a,**kw:pytest.fail('no nested spin'))
    assert driver.call('system/get_robot_state','GetRobotState') is response


def test_real_cli_mocked_node_runs_contact_then_keeps_grip(monkeypatch,tmp_path):
    """Actual admission/runner/cleanup, with only ROS/Modbus substituted. No hardware."""
    import io
    from app.assembly_step_runner import StepReplayDriver
    from app import assembly_motion_ros
    s,plan,profile,*_=setup()
    profile['profile_id']='D_ONSITE_FIXTURE_ONLY'
    profile['steps'][plan['key']]['physical_reference_reviewed']=True
    session=reviewed_session(s,profile)
    profile_path=tmp_path/'profile.json';profile_path.write_text(json.dumps(profile))
    session_path=tmp_path/'session.json';session_path.write_text(json.dumps(session))
    raw=StepReplayDriver(plan['settings']['reference_pose']);raw.mode='REAL'
    raw.value.update(gripper_status=2,gripper_width_mm=40.)
    raw.value['posx']=plan['settings']['reference_pose'].copy();raw.value['posx'][2]+=20.1
    closed=[];raw.close=lambda:closed.append(True);raw.robot_system=lambda:0
    state=NS(ok=False,services={},messages=[])
    node=NS(create_service=lambda typ,name,callback:state.services.update({name:callback}),
            create_publisher=lambda *a:NS(publish=lambda msg:state.messages.append(msg)),
            create_timer=lambda *a:None,destroy_node=lambda:None)
    executor=NS(add_node=lambda n:None,spin=lambda:None,shutdown=lambda **kw:None)
    ros=NS(init=lambda **kw:setattr(state,'ok',True),create_node=lambda n:node,
           ok=lambda:state.ok,shutdown=lambda:setattr(state,'ok',False))
    monkeypatch.setitem(sys.modules,'rclpy',ros)
    monkeypatch.setitem(sys.modules,'rclpy.executors',NS(MultiThreadedExecutor=lambda **kw:executor))
    monkeypatch.setitem(sys.modules,'rclpy.signals',NS(SignalHandlerOptions=NS(NO=0)))
    monkeypatch.setitem(sys.modules,'std_srvs.srv',NS(Trigger=object()))
    monkeypatch.setitem(sys.modules,'std_msgs.msg',NS(String=lambda:NS()))
    monkeypatch.setattr(assembly_motion_ros,'AssemblyMotionRos',lambda *a,**kw:raw)
    monkeypatch.setattr(cli,'ROOT',tmp_path)
    monkeypatch.setenv('ROS_DOMAIN_ID','20')
    monkeypatch.setattr(cli.sys,'stdin',io.StringIO('yes\nyes\nyes\n'))
    monkeypatch.setattr(cli.select,'select',lambda *a:([cli.sys.stdin],[],[]))
    assert cli.main(['run','--execute','--profile',str(profile_path),'--session',str(session_path),
                     '--output',str(tmp_path/'attempt')])==0
    result=read(tmp_path/'attempt/result.json')
    assert result['status']=='PAUSED_SEATED_RELEASE_PENDING'
    assert not raw.grips and raw.value['gripper_status']==2
    assert closed and not state.ok and '~/stop' in state.services
    # The persisted execution ID is one-shot even across process-style invocations.
    assert cli.main(['run','--execute','--profile',str(profile_path),'--session',str(session_path),
                     '--output',str(tmp_path/'second')])==1


def test_cli_camera_unavailable_switches_to_fresh_held_assembly(monkeypatch,tmp_path):
    import io
    from app.assembly_step_runner import StepReplayDriver
    from app import assembly_motion_ros, control_camera
    from test_control_session import Clock
    s,plan,profile,*_=setup();clock=Clock()
    profile['profile_id']='D_LOCAL_CAMERA_FALLBACK_FIXTURE';profile['physical_route_reviewed']=True
    setting=profile['steps'][plan['key']];setting.update(physical_reference_reviewed=True,
        handover_trial=dict(operator_armed_preview_stop_trial=True,observe_route_reviewed=True,
                            observe_pose=[400.,8.,315.,75.,-177.,75.],no_receive_action='ASSEMBLE'))
    primary=reviewed_session(s,profile);primary['allowed_trial_phase']='handover'
    fallback=deepcopy(primary);fallback.update(execution_id='FRESH_HELD_ASSEMBLY_EXECUTION',
        allowed_trial_phase='assemble-held',handover_parent_execution_id=primary['execution_id'],
        alignment_evidence_ref='LOCAL_SOURCE_ALIGNMENT_REVIEWED_ACTUAL_GOAL_ALIGNMENT_WAIT_REQUIRED')
    held={'step':{'case_id':plan['key'].split('/')[0], 'step_id':plan['step_id'],
        'plan_id':plan['plan_id'], 'block':plan['block'], 'action':dict(mode='ROBOT_GRIP',assistance_kind='NONE'),
        'current_revision':plan['current_revision'],'reservation':None,'summary':{}},'d_profile':profile}
    files={}
    for name,v in [('held',held),('primary',primary),('fallback',fallback)]:
        path=tmp_path/(name+'.json');path.write_text(json.dumps(v));files[name]=path
    raw=StepReplayDriver(setting['reference_pose']);raw.mode='REAL'
    raw.value.update(gripper_status=2,gripper_width_mm=40.,posx=setting['pickup_pose'].copy())
    closed=[];raw.close=lambda:closed.append('driver');raw.robot_system=lambda:0
    state=NS(ok=False)
    node=NS(create_service=lambda *a:None,create_publisher=lambda *a:NS(publish=lambda msg:None),
            create_timer=lambda *a:None,destroy_node=lambda:None)
    executor=NS(add_node=lambda n:None,spin=lambda:None,shutdown=lambda **kw:None)
    ros=NS(init=lambda **kw:setattr(state,'ok',True),create_node=lambda n:node,
           ok=lambda:state.ok,shutdown=lambda:setattr(state,'ok',False))
    for name,module in [('rclpy',ros),('rclpy.executors',NS(MultiThreadedExecutor=lambda **kw:executor)),
        ('rclpy.signals',NS(SignalHandlerOptions=NS(NO=0))),('std_srvs.srv',NS(Trigger=object())),
        ('std_msgs.msg',NS(String=lambda:NS()))]:monkeypatch.setitem(sys.modules,name,module)
    monkeypatch.setattr(assembly_motion_ros,'AssemblyMotionRos',lambda *a,**kw:raw)
    monkeypatch.setattr(control_camera,'RequestCamera',lambda *a,**kw:NS(poll=lambda:None,close=lambda:closed.append('camera')))
    original=cli.execute_step
    def execute(raw,session,*args,**kw):
        session.clock=clock;session.started=clock()
        return original(raw,session,*args,**kw,clock=clock,sleep=clock.sleep)
    monkeypatch.setattr(cli,'execute_step',execute)
    monkeypatch.setattr(cli.time,'monotonic',clock)
    monkeypatch.setattr(cli,'ROOT',tmp_path);monkeypatch.setenv('ROS_DOMAIN_ID','20')
    monkeypatch.setattr(cli.sys,'stdin',io.StringIO('yes\n'*6))
    monkeypatch.setattr(cli.select,'select',lambda *a:([cli.sys.stdin],[],[]))
    output=tmp_path/'output'
    assert cli.main(['run','--execute','--held-profile',str(files['held']),
        '--session',str(files['primary']),'--phase','handover','--start-zone','supply','--camera',
        '--assembly-fallback-profile',str(files['held']),'--assembly-fallback-session',str(files['fallback']),
        '--output',str(output)])==0
    assert read(output/'handover-result.json')['status']=='ASSEMBLY_REQUIRED'
    result=read(output/'result.json')
    assert result['status']=='AWAITING_BACKEND_OBSERVATION' and result['execution_id']==fallback['execution_id']
    assert len(raw.grips)==1 and not result['current_update'] and not result['assembly_completion']
    assert len(list((tmp_path/'logs/executions').glob('*.json')))==2
    rows=[json.loads(x) for f in output.glob('trial-*.jsonl') for x in f.read_text().splitlines()]
    start=next(i for i,r in enumerate(rows) if r['event']=='ASSEMBLY_FALLBACK_STARTED')
    assert not any(r['event']=='SINGLE_WRITER_MOVE' for r in rows[:start])
    assert all(r['execution_id']==fallback['execution_id'] for r in rows[start:])
    assert closed==['camera','driver']
