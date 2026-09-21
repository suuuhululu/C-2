"""실물 연결 경계 시험: 장치 I/O와 측정 반환은 대역. 로봇 연결 없음."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import threading
import time
import pytest
from c2_process.node import ProcessCoordinator
from c2_process.robot_adapter import StepResult
from c2_process.preparation_action import make_real_measurement_runner, result_from_step
from c2_process.measurement_robot_adapter import GuardedMeasurementAdapter
from test_node import real_fixture
from test_preparation_action import fixture


@pytest.mark.parametrize('outcome',['SUCCEEDED','FAILED','STOPPED','UNKNOWN','exception'])
def test_real_factory_passes_shared_objects_and_always_closes(tmp_path,monkeypatch,outcome):
    import c2_process.workpiece_process_adapter as process_adapter
    import c2_process.node as node
    h,g,assets,save,_,_=fixture(tmp_path)
    measured=h.execute(g)
    original=copy.deepcopy(h.coordinator._preparations[g['preparation_id']][0])
    data=original.observed_state['measurement']
    data.update(source_mode='REAL',validity='ESTIMATED',absolute_top_verified=False)
    cfg=copy.deepcopy(h.config);cfg.update(source_mode='REAL',load_id='ToolWeight_1')
    _,_,status=real_fixture()
    coordinator=ProcessCoordinator(runtime_mode='REAL',real_adapter=status,measurement_only=True)
    assert coordinator.execute({'schema_version':2}).error_code=='NOT_READY'
    cancel=threading.Event();calls=[]
    adapter=object.__new__(GuardedMeasurementAdapter)
    adapter.close=lambda:calls.append('close')
    def create(n,c,ctx,**kwargs):
        assert kwargs['motion_lock'] is coordinator.motion_lock is ctx.motion_lock
        assert kwargs['cancel'] is cancel is ctx.cancel
        assert kwargs['scene_check'] is process_adapter.check_process_scene
        assert not ctx.motion_lock.locked()
        calls.append('create');return adapter
    monkeypatch.setattr(process_adapter,'create_process_measurement_adapter',create)
    def measure(a,w,p,ctx,on_progress):
        assert a is adapter and ctx.source_mode=='REAL'
        calls.append('measure')
        if outcome=='exception':raise RuntimeError('I/O failed')
        result=copy.deepcopy(original);result.outcome=outcome
        result.observed_state['stop_confirmed']=outcome!='UNKNOWN'
        return result
    monkeypatch.setattr(node,'measure_workpiece',measure)
    evidence=lambda ctx:dict(measurement_id=ctx.measurement_id,control_authority=dict(value=True,valid=True,
        source='CONTROLLER_ACCESS_CONTROL',observed_at_monotonic_s=time.monotonic()))
    recorded=[]
    runner=make_real_measurement_runner(coordinator,object(),evidence_provider=evidence,
        evidence_max_age_s={'control_authority':1.},stop_latched_provider=lambda ctx:False,
        stop_latch_recorder=lambda result,event:recorded.append((result.outcome,event is cancel)))
    result=runner(dict(g,source_mode='REAL'),cfg,cancel,lambda event:None)
    assert calls==['create','measure','close']
    assert result.outcome==('UNKNOWN' if outcome=='exception' else outcome),result
    assert recorded == [(('UNKNOWN' if outcome=='exception' else outcome),True)]
    if outcome=='SUCCEEDED':
        output=result_from_step(dict(g,source_mode='REAL'),result)
        assert output['outcome']=='SUCCEEDED' and output['validity']=='ESTIMATED'
        assert '절대 높이 미검증' in output['message']
    assert not coordinator.motion_lock.locked()


@pytest.mark.parametrize('bad',['missing','stale','wrong_source','false'])
def test_authority_missing_or_invalid_blocks_measure_and_closes(tmp_path,monkeypatch,bad):
    import c2_process.workpiece_process_adapter as process_adapter
    import c2_process.node as node
    h,g,_,_,_,_=fixture(tmp_path);h.execute(g)
    _,_,status=real_fixture()
    coordinator=ProcessCoordinator(runtime_mode='REAL',real_adapter=status,measurement_only=True)
    cfg=copy.deepcopy(h.config);cfg.update(source_mode='REAL',load_id='ToolWeight_1')
    adapter=object.__new__(GuardedMeasurementAdapter);closed=[];adapter.close=lambda:closed.append(True)
    monkeypatch.setattr(process_adapter,'create_process_measurement_adapter',lambda *a,**k:adapter)
    monkeypatch.setattr(node,'measure_workpiece',lambda *a,**k:pytest.fail('미확인 제어권으로 측정 호출'))
    item=dict(value=True,valid=True,source='CONTROLLER_ACCESS_CONTROL',observed_at_monotonic_s=time.monotonic())
    if bad=='stale':item['observed_at_monotonic_s']-=10
    if bad=='wrong_source':item['source']='AUTO'
    if bad=='false':item['value']=False
    provider=lambda ctx:dict(measurement_id=ctx.measurement_id,control_authority={} if bad=='missing' else item)
    runner=make_real_measurement_runner(coordinator,object(),evidence_provider=provider,
        evidence_max_age_s={'control_authority':1.},scene_check=lambda *a:None,stop_latched_provider=lambda ctx:False)
    result=runner(dict(g,source_mode='REAL'),cfg,threading.Event(),lambda e:None)
    assert result.outcome=='FAILED' and closed==[True]



def test_real_runner_rejects_controller_prefix_mismatch_before_adapter(tmp_path, monkeypatch):
    import c2_process.workpiece_process_adapter as process_adapter
    h, goal, _, _, _, _ = fixture(tmp_path)
    h.execute(goal)
    _, _, status = real_fixture()
    coordinator = ProcessCoordinator(runtime_mode='REAL', real_adapter=status, measurement_only=True)
    config = copy.deepcopy(h.config)
    config.update(source_mode='REAL', load_id='ToolWeight_1',
                  controller_prefix='/other/controller')
    monkeypatch.setattr(process_adapter, 'create_process_measurement_adapter',
                        lambda *a, **k: pytest.fail('prefix 불일치 후 어댑터 생성'))
    provider = lambda ctx: {}
    runner = make_real_measurement_runner(
        coordinator, object(), evidence_provider=provider,
        evidence_max_age_s={'control_authority': 1.},
        stop_latched_provider=lambda ctx: None,
        controller_prefix='/dsr01/dsr_controller2')
    result = runner(dict(goal, source_mode='REAL'), config, threading.Event(), lambda event: None)
    assert (result.outcome, result.error_code) == ('FAILED', 'PROFILE_MISMATCH')
