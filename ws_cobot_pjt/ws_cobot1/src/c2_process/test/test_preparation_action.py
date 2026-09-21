"""PrepareWorkpiece typed contract: 실제 SIM 측정 + 명시적 모의 홈 콜백. 실물 없음."""
import copy
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.preparation_action import (AssetResolver, PreparationActionHandler, GOAL_FIELDS,
    make_measurement_runner, make_simulation_runner_factory, result_from_step, encoded)
from c2_process.robot_adapter import StepResult
from test_node import _workpiece_connection


def fixture(tmp_path, home_result=None):
    coordinator,args=_workpiece_connection()
    _,status,measurement,w,p,evidence,_=args
    status._read_tool_tcp=lambda: ('GripperDA_v1','sim-load')
    config=dict(contract='prepare-workpiece-config/1',source_mode='SIMULATION',tool_id='engraving_drill',
                tcp_id='GripperDA_v1',load_id='sim-load',workcell=w,profiles=p)
    assets={}
    def save(value):
        id=str(uuid4());raw=encoded(value);assets[id]=raw
        return id,hashlib.sha256(raw).hexdigest()
    id,sha=save(config)
    goal=dict(schema_version=2,operation='MEASURE',request_id=str(uuid4()),preparation_id=str(uuid4()),
              measurement_id=str(uuid4()),source_mode='SIMULATION',input_profile_snapshot_id=id,input_profile_sha256=sha,
              measurement_record_id='',measurement_record_sha256='',profile_snapshot_id='',profile_sha256='')
    homes=[]
    def home(ctx,w,p,progress):
        homes.append(ctx.preparation_id)
        progress({'stage':'HOME_CHECK'})
        # 실제 홈 구현이 아니다. 홈에서 정지한 조건의 함수 연결 대역.
        return home_result or StepResult('SUCCEEDED',observed_state={'stop_confirmed':True})
    runner=make_measurement_runner(coordinator,status_adapter=status,
        measurement_adapter_factory=lambda c: measurement,evidence_factory=lambda g,c: evidence,home_fn=home)
    handler=PreparationActionHandler(coordinator,AssetResolver(fetch=lambda id,timeout:assets[id]),tmp_path/'journal.db',runner)
    return handler,goal,assets,save,measurement,homes


def bind_goal(goal,result,save):
    record=dict(contract='prepare-workpiece-result/1',result=result)
    rid,rsha=save(record)
    g=dict(goal,operation='BIND_SNAPSHOT',request_id=str(uuid4()),measurement_record_id=rid,measurement_record_sha256=rsha)
    h=result['height_m'];lo,hi=result['work_v_range_m']
    profile={k:g[k] for k in ('preparation_id','measurement_id','source_mode','input_profile_snapshot_id','input_profile_sha256',
                              'measurement_record_id','measurement_record_sha256')}
    profile.update(tool_id='engraving_drill',tcp_id='GripperDA_v1',load_id='sim-load',surface=dict(
        radius_mm=result['radius_m']*1000,height_mm=h*1000,axis_origin_m=[*result['axis_xy_m'],result['bottom_z_m']],
        axis_direction=[0,0,1],height_reference='bottom',v_direction='up',valid_v_range_mm=[(h-hi)*1000,(h-lo)*1000]))
    pid,psha=save(profile);g.update(profile_snapshot_id=pid,profile_sha256=psha)
    return g,profile,record


def test_actual_sim_measure_typed_result_bind_and_replay(tmp_path):
    h,g,assets,save,ad,homes=fixture(tmp_path)
    events=[];r=h.execute(g,events.append)
    assert r['outcome']=='SUCCEEDED',r
    assert r['contact_indices']==list(range(9)) and len(r['contact_tip_poses'])==9
    assert r['stop_confirmed'] and not r['partial'] and r['geometry_ready'] and not r['snapshot_bound']
    assert r['work_v_range_m']==pytest.approx([.01,.14]) and r['height_source']=='OPERATOR_RULER'
    assert r['contact_received_at'][0]['sec']>0 and r['contact_monotonic_s'][0]>0
    assert r['frame_id']=='c2_base' and r['validity']=='SIMULATED'
    stages=[e['stage'] for e in events]
    assert stages.index('ROBOT_CHECK')<stages.index('HOME_CHECK')<stages.index('HOME_RECHECK')<stages.index('TOP_TOUCH')
    assert events[-1]['stage']=='COMPLETE' and events[-1]['completed_side_points']==8
    calls=len(ad.calls)
    assert h.execute(g)==r and len(ad.calls)==calls and len(homes)==1
    bg,profile,record=bind_goal(g,r,save)
    bound=h.execute(bg)
    assert bound['outcome']=='SUCCEEDED' and bound['snapshot_bound'],bound
    assert bound['contact_indices']==[] and len(ad.calls)==calls
    assert h.coordinator._preparation_bindings[g['preparation_id']]==(bg['profile_snapshot_id'],bg['profile_sha256'])
    assert not h.cancel(bg)


def test_deployed_simulation_runner_uses_goal_config(tmp_path):
    h,g,assets,save,_,_=fixture(tmp_path)
    h.runner=make_simulation_runner_factory()(h.coordinator)
    result=h.execute(g)
    assert result['outcome']=='SUCCEEDED',(result['error_code'],result['message'])
    assert result['contact_indices']==list(range(9))
    assert result['stop_confirmed'] and result['geometry_ready']


@pytest.mark.parametrize('defect',['path_hash','mode','input_schema','uuid','operation','record','radius','direction','metadata','tool'])
def test_bad_contract_and_binding_never_moves(tmp_path,defect):
    h,g,assets,save,ad,_=fixture(tmp_path)
    if defect in ('record','radius','direction','metadata','tool'):
        r=h.execute(g);bg,profile,record=bind_goal(g,r,save);g=bg
        if defect=='record':
            record['result']['radius_m']+=.001
            g['measurement_record_id'],g['measurement_record_sha256']=save(record)
            profile.update(measurement_record_id=g['measurement_record_id'],measurement_record_sha256=g['measurement_record_sha256'])
        elif defect=='radius': profile['surface']['radius_mm']+=1
        elif defect=='direction': profile['surface']['v_direction']='down'
        elif defect=='metadata': profile['measurement_id']=str(uuid4())
        elif defect=='tool': profile['tool_id']='other'
        g['profile_snapshot_id'],g['profile_sha256']=save(profile)
    elif defect=='path_hash': g['input_profile_sha256']='0'*64
    elif defect=='mode': g['source_mode']='REAL'
    elif defect=='uuid': g['request_id']='invalid'
    elif defect=='operation': g['operation']='HOME'
    else:
        c=json.loads(assets[g['input_profile_snapshot_id']]);c['contract']='old-mock'
        g['input_profile_snapshot_id'],g['input_profile_sha256']=save(c)
    before=len(ad.calls)
    result=h.execute(g)
    assert result['outcome']=='FAILED' and len(ad.calls)==before,result
    assert not result['snapshot_bound']


def test_missing_home_does_not_measure(tmp_path):
    h,g,assets,save,ad,_=fixture(tmp_path,StepResult('FAILED','NOT_READY','home blocked'))
    result=h.execute(g)
    assert result['outcome']=='FAILED' and not ad.calls


def test_home_arrival_unconfirmed_blocks_measurement(tmp_path):
    h,g,assets,save,ad,_=fixture(tmp_path,StepResult('SUCCEEDED',observed_state={'stop_confirmed':False}))
    result=h.execute(g)
    assert result['outcome']=='UNKNOWN' and not ad.calls


def test_cancel_before_start_preserves_unknown_stop(tmp_path):
    h,g,assets,save,ad,_=fixture(tmp_path)
    assert h.cancel(g)
    r=h.execute(g)
    assert r['outcome']=='STOPPED' and r['stop_confirmed'] is False and not ad.calls


def test_cancel_after_contact_has_partial_result_and_no_next_point(tmp_path):
    h,g,assets,save,ad,_=fixture(tmp_path)
    def event(e):
        if e['completed_side_points']==1: h.cancel(g)
    r=h.execute(g,event)
    assert r['outcome']=='STOPPED' and r['stop_confirmed'] and r['partial'],r
    assert r['contact_indices']==[0,1] and not r['geometry_ready']
    assert not h.coordinator._preparation_bindings


def test_binding_cancel_before_commit_never_registers(tmp_path):
    h,g,assets,save,ad,_=fixture(tmp_path)
    r=h.execute(g);bg,_,_=bind_goal(g,r,save)
    fetch=h.resolver.fetch
    def cancelled(id,timeout):
        h.cancel(bg);return fetch(id,timeout)
    h.resolver.fetch=cancelled
    out=h.execute(bg)
    assert out['outcome']=='STOPPED' and not out['snapshot_bound']
    assert not h.coordinator._preparation_bindings


def test_new_request_invalidates_old_binding_and_restart_cannot_bind(tmp_path):
    h,g,assets,save,ad,_=fixture(tmp_path)
    r=h.execute(g);bg,_,_=bind_goal(g,r,save)
    assert h.execute(bg)['snapshot_bound']
    new=dict(g,request_id=str(uuid4()),preparation_id=str(uuid4()),measurement_id=str(uuid4()))
    h.runner=None
    assert h.execute(new)['outcome']=='FAILED'
    assert not h.execute(bg)['snapshot_bound']
    h2=PreparationActionHandler(h.coordinator,h.resolver,tmp_path/'journal.db',None)
    bg['request_id']=str(uuid4())
    assert h2.execute(bg)['error_code']=='NOT_READY'
    old_calls=len(ad.calls)
    assert h2.execute(g)==r and len(ad.calls)==old_calls


def test_duplicate_conflict_and_busy_do_not_invoke_runner_twice(tmp_path):
    h,g,assets,save,ad,_=fixture(tmp_path)
    entered=threading.Event();release=threading.Event();calls=[]
    def run(*args):
        calls.append(1);entered.set();assert release.wait(2)
        return StepResult('FAILED','NOT_READY')
    h.runner=run
    results=[]
    t=threading.Thread(target=lambda:results.append(h.execute(g)));t.start();assert entered.wait(1)
    t2=threading.Thread(target=lambda:results.append(h.execute(g)));t2.start()
    other=dict(g,request_id=str(uuid4()),preparation_id=str(uuid4()),measurement_id=str(uuid4()))
    assert h.execute(other)['error_code']=='BUSY'
    assert h.coordinator.execute(dict(schema_version=2,source_mode='SIMULATION',request_id='execute',run_id='run')) .error_code in ('BUSY','NOT_READY')
    changed=dict(g,measurement_id=str(uuid4()))
    assert h.execute(changed)['error_code']=='REQUEST_CONFLICT'
    release.set();t.join(2);t2.join(2)
    assert results[0]==results[1] and calls==[1]


@pytest.mark.parametrize('confirmed',[True,False])
def test_timeout_retains_stop_confirmation(tmp_path,confirmed):
    h,g,assets,save,ad,_=fixture(tmp_path)
    c=json.loads(assets[g['input_profile_snapshot_id']]);c['workcell']['runtime_timeout_s']=.02
    g['input_profile_snapshot_id'],g['input_profile_sha256']=save(c)
    def run(goal,c,cancel,feedback):
        assert cancel.wait(1)
        return StepResult('STOPPED','NONE',observed_state={'stop_confirmed':confirmed,'partial':True})
    h.runner=run
    r=h.execute(g)
    assert r['outcome']==('FAILED' if confirmed else 'UNKNOWN') and r['error_code']=='TIMEOUT'


def test_bad_config_cannot_make_contact_time_or_stop_true(tmp_path):
    _,g,*_=fixture(tmp_path)
    out=result_from_step(g,StepResult('FAILED','NOT_READY',observed_state={'stop_confirmed':None}))
    assert not out['stop_confirmed'] and out['measured_at']=={'sec':0,'nanosec':0}


def test_unexpected_runner_exception_is_not_claimed_stopped(tmp_path):
    h,g,_,_,_,_=fixture(tmp_path)
    def broken(*args): raise RuntimeError('runner lost')
    h.runner=broken
    r=h.execute(g)
    assert r['outcome']=='UNKNOWN' and not r['stop_confirmed']
    assert h.coordinator._motion_uncertain


def test_ros_prepare_measure_bind_round_trip(tmp_path):
    import os
    if os.environ.get('C2_RUN_PREPARE_ROS')!='1':
        pytest.skip('PrepareWorkpiece ROS 왕복은 Jazzy source 후 C2_RUN_PREPARE_ROS=1로 별도 실행')
    assert os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')=='LOCALHOST'
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rosidl_runtime_py.set_message import set_message_fields
    from rosidl_runtime_py.convert import message_to_ordereddict
    from c2_interfaces.action import PrepareWorkpiece
    from c2_process.node import create_ros_node
    h,g,assets,save,_,_=fixture(tmp_path)
    _,args=_workpiece_connection()
    _,status,measurement,w,p,evidence,_=args
    status._read_tool_tcp=lambda: ('GripperDA_v1','sim-load')
    def factory(coordinator):
        return make_measurement_runner(coordinator,status_adapter=status,
            measurement_adapter_factory=lambda cfg: measurement,evidence_factory=lambda g,c:evidence,
            home_fn=lambda *a:StepResult('SUCCEEDED',observed_state={'stop_confirmed':True}))
    rclpy.init(args=[])
    server=create_ros_node(preparation_runner_factory=factory,preparation_resolver=h.resolver,
                           preparation_journal_path=tmp_path/'ros.db')
    client=rclpy.create_node('prepare_contract_test')
    executor=MultiThreadedExecutor(num_threads=4)
    executor.add_node(server);executor.add_node(client)
    thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    action=ActionClient(client,PrepareWorkpiece,'/c2/prepare_workpiece',
                       feedback_sub_qos_profile=QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE))
    events=[]
    def wait(future):
        done=threading.Event();future.add_done_callback(lambda _:done.set())
        assert done.wait(15),'ROS response timeout'
        return future.result()
    def send(goal):
        msg=PrepareWorkpiece.Goal();set_message_fields(msg,goal)
        handle=wait(action.send_goal_async(msg,feedback_callback=lambda m:events.append(m.feedback.stage)))
        assert handle.accepted
        reply=wait(handle.get_result_async())
        # OrderedDict와 array를 JSON 표준 타입으로 직렬화한다.
        raw=json.loads(json.dumps(message_to_ordereddict(reply.result)))
        assert reply.status==4 and raw['outcome']=='SUCCEEDED',raw
        return raw
    try:
        assert action.wait_for_server(timeout_sec=5)
        measured=send(g)
        assert measured['contact_indices']==list(range(9)) and not measured['snapshot_bound']
        bg,_,_=bind_goal(g,measured,save)
        bound=send(bg)
        # Feedback는 Result보다 늦게 도착하거나 Goal 수락 경계에서 놓칠 수 있다.
        # 완료 판단은 Result, 전송 자체는 장시간 측정 Feedback으로 검증한다.
        assert bound['snapshot_bound'] and events  # Feedback 수신과 최종 Result 왕복
    finally:
        executor.shutdown(timeout_sec=3);thread.join(3)
        action.destroy();client.destroy_node();server.destroy_node();rclpy.shutdown()


@pytest.mark.parametrize("case", ["home", "away", "failure", "cancel", "stale"])
def test_action_uses_team_home_and_observation_flow(tmp_path, case):
    from c2_process.robot_adapter import apply_tool_offset
    h,g,assets,save,ad,_=fixture(tmp_path)
    _,args=_workpiece_connection()
    _,status,_,w,p,evidence,_=args
    status._read_tool_tcp=lambda: ('GripperDA_v1','sim-load')
    if case=='home':
        ad.pose=apply_tool_offset(w['home']['tcp_pose'],w['tool_offset_m'])
    if case=='failure':
        execute=ad.execute_measurement_step
        def fail(step,*a):
            if step['label']=='home_x':return StepResult('FAILED','TEST_HOME_FAILED')
            return execute(step,*a)
        ad.execute_measurement_step=fail
    if case=='stale':
        observe=ad.observe_measurement
        def stale():
            value=observe();value['measured_at_monotonic_s']-=100
            return value
        ad.observe_measurement=stale
    h.runner=make_measurement_runner(h.coordinator,status_adapter=status,
        measurement_adapter_factory=lambda _:ad,evidence_factory=lambda *a:evidence,
        measurement_owns_home=True)
    events=[]
    def progress(e):
        events.append(e['stage'])
        if case=='cancel' and e['stage']=='HOME_MOVE':assert h.cancel(g)
    result=h.execute(g,progress)
    motions=[v for k,v in ad.calls if k=='execute']
    if case in ('failure','cancel','stale'):
        assert result['outcome'] in ('FAILED','STOPPED'),result
        assert not any(x['kind']=='PROBE' for x in motions)
        assert not h.coordinator._preparations
    else:
        assert result['outcome']=='SUCCEEDED',result
        first=next(i for i,x in enumerate(motions) if x['kind']=='PROBE')
        home_moves=[x for x in motions[:first] if x['label'].startswith('home_')]
        assert bool(home_moves)==(case=='away')
        assert events.index('HOME_CHECK')<events.index('HOME_RECHECK')<events.index('TOP_TOUCH')
        assert 'RETRACT' in events
        assert result['contact_indices']==list(range(9))


def test_action_contract_samples_have_exact_goal_feedback_and_result_fields():
    from c2_process.preparation_action import result_base, validate_goal
    root = Path(__file__).parent / 'fixtures' / 'prepare_workpiece_action_samples'
    feedback_fields = {
        'request_id','preparation_id','measurement_id','operation','stage','progress',
        'completed_side_points','total_side_points','elapsed_s','message'}
    for name in ('success','failure','cancel','timeout','communication_lost'):
        sample = json.loads((root / (name + '.json')).read_text())
        validate_goal(sample['goal'])
        assert set(sample['result']) == set(result_base(sample['goal']))
        assert all(set(item) == feedback_fields for item in sample['feedback'])
        assert sample['real_robot_capture'] is False
    success = json.loads((root / 'success.json').read_text())['result']
    assert success['contact_indices'] == list(range(9))
    assert success['geometry_ready'] and not success['partial'] and success['stop_confirmed']
