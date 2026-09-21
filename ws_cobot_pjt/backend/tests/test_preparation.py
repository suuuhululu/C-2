"""HMI 준비 API/기록/차단 시험. 제어 ROS 수신부나 로봇을 호출하지 않는다."""
import asyncio
from copy import deepcopy
from datetime import datetime
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.monitor import create_app
from app.monitor_contract import now
from app.preparation import PreparationService, measured_profile
from test_monitor import HEADERS, client, generated, run_body, wait


def body(c, **changes):
    config=c.get('/api/operator/snapshot').json()['preparation']['input_config']
    return dict(request_id=str(uuid4()),input_profile_snapshot_id=config['id'],input_profile_sha256=config['sha256'],
                height_m=.15,**changes)


def prepare(c, request=None):
    request=request or body(c)
    response=c.post('/api/operator/preparations',json=request)
    assert response.status_code==202,response.text
    record=wait(c,'/api/operator/preparations/'+request['request_id'],
                lambda p:p['state'] not in ('ACCEPTED','RUNNING','CANCELING'))
    wait(c,'/api/operator/snapshot',lambda s:not s['preparation']['blocks_work'] or record['state']=='UNKNOWN')
    return record


def test_preparation_ids_settings_and_geometry_follow_same_path(client):
    c=client;b=body(c);p=prepare(c,b)
    assert p['state']=='SUCCEEDED' and p['binding_status']=='BOUND_MOCK'
    assert len({p['request_id'],p['goal']['preparation_id'],p['goal']['measurement_id']})==3
    assert not any(k.startswith('operator_confirmed') for k in p['goal'])
    assert 'confirmed_at' not in p['goal']
    stages=[f['stage'] for f in p['feedback']]
    assert stages.index('HOME_CHECK') < stages.index('HOME_MOVE') < stages.index('HOME_RECHECK') < stages.index('TOP_TOUCH')
    current=c.get('/api/operator/snapshot').json()
    profile=current['profile'];s=profile['payload']['surface']
    assert s['axis_origin_m']==pytest.approx([.4264,.0001,.0847])
    assert s['valid_v_range_mm']==pytest.approx([10,140])
    assert s['height_reference']=='bottom' and s['v_direction']=='up'
    assert c.post('/api/operator/preparations',json=b).json()['goal']==p['goal']
    assert len(c.get('/api/operator/preparations').json())==1
    _,path=generated(c)
    assert path['measurement_id']==p['goal']['measurement_id']
    for stroke in path['preview']['strokes']:
        for xyz,uv in zip(stroke['points_m'],stroke['points_uv_mm']):
            assert (xyz[2]-s['axis_origin_m'][2])*1000==pytest.approx(uv[1])
    response=c.post('/api/operator/runs',json=run_body(path))
    assert response.status_code==202,response.text
    assert response.json()['preparation_id']==p['goal']['preparation_id']
    wait(c,'/api/operator/runs/'+response.json()['run_id'],lambda r:r['status']=='SUCCEEDED')


@pytest.mark.parametrize('field,value',[
    ('operator_confirmed_drill_off',False),('operator_confirmed_drill_fixed',False),
    ('operator_confirmed_gripper_closed',False),('operator_confirmed_drill_off',True),
    ('operator_confirmed_drill_on',True),
    ('source_mode','REAL'),('schema_version',2),('height_m',0),
    ('confirmed_at','2026-09-21T10:00:00')])
def test_invalid_operator_inputs_are_not_defaulted(client,field,value):
    b=body(client);b[field]=value
    assert client.post('/api/operator/preparations',json=b).status_code==422
    assert client.get('/api/operator/preparations').json()==[]


def test_config_height_hash_conflict_and_duplicate(client):
    c=client;b=body(c)
    for change in ({'height_m':.2},{'input_profile_sha256':'0'*64}):
        assert c.post('/api/operator/preparations',json={**b,**change}).json()['error_code']=='PROFILE_MISMATCH'
    p=prepare(c,b)
    assert c.post('/api/operator/preparations',json={**b,'height_m':.2}).json()['error_code']=='REQUEST_CONFLICT'
    cfg=c.app.state.service.preparation.config
    asset=c.app.state.store.asset(cfg['id'])
    (c.app.state.store.files/asset['storage_key']).write_text('{}')
    assert c.post('/api/operator/preparations',json={**b,'request_id':str(uuid4())}).json()['error_code']=='HASH_MISMATCH'
    assert c.get('/api/operator/preparations/'+p['request_id']).json()['state']=='SUCCEEDED'


def test_concurrent_preparation_and_generation_execution_are_rejected(client):
    c=client;goal,path=generated(c)
    c.app.state.service.peer.tick=.08
    b=body(c)
    assert c.post('/api/operator/preparations',json=b).status_code==202
    assert c.post('/api/operator/preparations',json=b).status_code==202
    assert c.post('/api/operator/preparations',json=body(c)).json()['error_code']=='BUSY'
    assert c.post('/api/operator/path-generations',json={**goal,'request_id':str(uuid4())}).json()['error_code']=='BUSY'
    assert c.post('/api/operator/runs',json=run_body(path)).json()['error_code']=='BUSY'
    assert c.post('/api/operator/preparations/'+b['request_id']+'/cancel',json={}).status_code==202
    final=wait(c,'/api/operator/preparations/'+b['request_id'],lambda r:r['state']=='STOPPED')
    assert final['result']['observed_state']['partial'] is True
    assert not c.get('/api/operator/snapshot').json()['preparation']['ready']
    assert c.post('/api/operator/runs',json=run_body(path)).status_code==409


@pytest.mark.parametrize('scenario', ['preparation_failure','measurement_reference_only'])
def test_failed_or_reference_measurement_preserves_raw_without_profile(client,scenario):
    c=client;original=c.get('/api/operator/snapshot').json()['profile']['id']
    assert c.post('/api/operator/simulation/scenario',json={'scenario':scenario}).status_code==200
    p=prepare(c)
    assert p['state']=='FAILED' and 'profile_snapshot' not in p
    raw=c.get('/api/operator/assets/'+p['measurement_record']['id']+'/content').json()
    assert raw['outcome']=='FAILED'
    assert c.get('/api/operator/snapshot').json()['profile']['id']==original
    if scenario=='preparation_failure':
        assert raw['observed_state']['measurement'] is None
        assert raw['observed_state']['stop_confirmed'] is None
    else:
        assert raw['observed_state']['measurement']['validity']=='REFERENCE_ONLY'


def test_timeout_with_confirmed_stop_is_failure(client):
    c=client;c.app.state.service.preparation.timeout_s=.07
    c.post('/api/operator/simulation/scenario',json={'scenario':'preparation_timeout'})
    p=prepare(c)
    assert p['state']=='FAILED' and p['error_code']=='TIMEOUT'
    assert p['result']['observed_state']['stop_confirmed'] is True


def test_unconfirmed_stop_persists_across_restart(tmp_path):
    directory=tmp_path/'data'
    with TestClient(create_app(directory,tick=.06),headers=HEADERS) as c:
        c.post('/api/operator/simulation/scenario',json={'scenario':'stop_unknown'})
        b=body(c);c.post('/api/operator/preparations',json=b)
        wait(c,'/api/operator/preparations/'+b['request_id'],lambda p:p['state']=='RUNNING')
        c.post('/api/operator/preparations/'+b['request_id']+'/cancel',json={})
        wait(c,'/api/operator/preparations/'+b['request_id'],lambda p:p['state']=='UNKNOWN')
        assert c.post('/api/operator/preparations',json=body(c)).json()['error_code']=='BUSY'
    with TestClient(create_app(directory,tick=.001),headers=HEADERS) as c:
        s=c.get('/api/operator/snapshot').json()['preparation']
        assert s['blocks_work'] and s['current']['state']=='UNKNOWN'
        assert c.post('/api/operator/preparations',json=body(c)).json()['error_code']=='BUSY'
        assert c.post('/api/operator/simulation/reset',json={}).status_code==200
        assert not c.get('/api/operator/snapshot').json()['preparation']['ready']


def test_cancel_without_final_reply_and_late_success_fail_closed(client):
    c=client;s=c.app.state.service
    original=s.peer.prepare_workpiece
    async def late_success(goal,config,feedback,cancel):
        return await original(goal,config,feedback,asyncio.Event())
    s.peer.prepare_workpiece=late_success
    b=body(c);c.post('/api/operator/preparations',json=b)
    c.post('/api/operator/preparations/'+b['request_id']+'/cancel',json={})
    p=wait(c,'/api/operator/preparations/'+b['request_id'],lambda p:p['state']=='UNKNOWN')
    assert 'profile_snapshot' not in p
    assert not c.get('/api/operator/snapshot').json()['preparation']['ready']


def test_missing_terminal_response_blocks(client):
    c=client;s=c.app.state.service
    s.preparation.timeout_s=.04;s.preparation.cancel_timeout_s=.03
    async def never(*args):await asyncio.Future()
    s.peer.prepare_workpiece=never
    p=prepare(c)
    assert p['state']=='UNKNOWN' and 'profile_snapshot' not in p


@pytest.mark.parametrize('failure', ['binding_mismatch','record_storage'])
def test_binding_or_record_failure_never_activates_profile(client,monkeypatch,failure):
    c=client;s=c.app.state.service
    old_profile=s.profile['id']
    if failure=='binding_mismatch':
        async def wrong_binding(*args):return {}
        monkeypatch.setattr(s.peer,'bind_preparation_snapshot',wrong_binding)
    else:
        original=s.store.put_json
        def fail_record(value,kind,name):
            if kind=='measurement_record':raise OSError('test disk failure')
            return original(value,kind,name)
        monkeypatch.setattr(s.store,'put_json',fail_record)
    p=prepare(c)
    snapshot=c.get('/api/operator/snapshot').json()
    assert p['state']=='UNKNOWN' and not snapshot['preparation']['ready']
    assert snapshot['profile']['id']==old_profile
    assert c.post('/api/operator/preparations',json=body(c)).json()['error_code']=='BUSY'


def test_generation_and_execution_prevent_new_preparation(client):
    c=client;goal,path=generated(c)
    c.app.state.service.peer.tick=.04
    goal={**goal,'request_id':str(uuid4())}
    assert c.post('/api/operator/path-generations',json=goal).status_code==202
    assert c.post('/api/operator/preparations',json=body(c)).json()['error_code']=='BUSY'
    wait(c,'/api/operator/path-generations/'+goal['request_id'],lambda p:p['state']=='SUCCEEDED')
    response=c.post('/api/operator/runs',json=run_body(path))
    assert response.status_code==202,response.text
    assert c.post('/api/operator/preparations',json=body(c)).json()['error_code']=='BUSY'
    wait(c,'/api/operator/runs/'+response.json()['run_id'],lambda r:r['status']=='SUCCEEDED')


def test_bound_profile_is_invalidated_by_new_measurement_or_restart(tmp_path):
    directory=tmp_path/'data'
    with TestClient(create_app(directory,tick=.002),headers=HEADERS) as c:
        _,path=generated(c)
        old_profile=path['profile_snapshot_id']
        prepare(c)
        assert c.get('/api/operator/snapshot').json()['profile']['id']!=old_profile
        assert c.post('/api/operator/runs',json=run_body(path)).json()['error_code']=='PROFILE_MISMATCH'
    with TestClient(create_app(directory,tick=.002),headers=HEADERS) as c:
        state=c.get('/api/operator/snapshot').json()['preparation']
        assert state['current']['state']=='SUCCEEDED' and not state['ready']
        assert state['current']['binding_status']=='REPREPARATION_REQUIRED'


def test_snapshot_conversion_rejects_missing_absolute_geometry_and_swapped_ranges(client):
    c=client;p=prepare(c);base=c.get('/api/operator/snapshot').json()['profile']['payload']
    result=deepcopy(p['result']);m=result['observed_state']['measurement']
    m['work_v_range_m']=[.01,.13];m['work_z_range_m']=[m['top_z_m']-.13,m['top_z_m']-.01]
    profile=measured_profile(base,p['goal'],result)
    assert profile['surface']['valid_v_range_mm']==pytest.approx([20,140])
    m['top_z_m']=None
    with pytest.raises(ValueError):measured_profile(base,p['goal'],result)


def test_corrupt_measurement_record_prevents_execution(client):
    c=client;_,path=generated(c)
    p=c.get('/api/operator/snapshot').json()['preparation']['current']
    record=c.app.state.store.asset(p['measurement_record']['id'])
    (c.app.state.store.files/record['storage_key']).write_text('{}')
    assert c.post('/api/operator/runs',json=run_body(path)).json()['error_code']=='HASH_MISMATCH'


def test_ros_preparation_is_explicitly_unavailable(client):
    c=client;b=body(c);s=c.app.state.service
    s.transport='ros'
    try:
        r=c.post('/api/operator/preparations',json=b)
        assert r.status_code==409 and r.json()['error_code']=='NOT_READY'
        assert c.get('/api/operator/preparations').json()==[]
    finally:s.transport='mock'


def test_progress_save_cannot_overwrite_terminal_result():
    started,release,terminal_write=Event(),Event(),Event()
    persisted=[]
    def save(record):
        if record['state']=='RUNNING':
            started.set()
            assert release.wait(2)
        else:terminal_write.set()
        persisted.append(record['state'])
    async def race():
        service=PreparationService(SimpleNamespace(store=SimpleNamespace(save_preparation=save)))
        service.current={'state':'RUNNING'}
        first=asyncio.create_task(service.save())
        assert await asyncio.to_thread(started.wait,2)
        service.current={'state':'UNKNOWN'}
        final=asyncio.create_task(service.save())
        # 진행 저장이 느린 상태에서 종료 저장이 먼저 끝나면 DB 상태가 역전된다.
        premature=await asyncio.to_thread(terminal_write.wait,.05)
        release.set()
        await asyncio.gather(first,final)
        assert not premature and persisted==['RUNNING','UNKNOWN']
    asyncio.run(race())


@pytest.mark.parametrize('state', ['RUNNING','SUCCEEDED'])
def test_control_connection_change_revokes_preparation(state):
    saved=[]
    owner=SimpleNamespace(transport='mock',peer=SimpleNamespace(bound_preparation='old'),
                          store=SimpleNamespace(save_preparation=lambda value:saved.append(value)))
    service=PreparationService(owner)
    service.current=dict(state=state,binding_status='BOUND_MOCK')
    service.cancel=asyncio.Event()
    asyncio.run(service.invalidate_connection())
    assert owner.peer.bound_preparation is None
    assert service.current['state']==('UNKNOWN' if state=='RUNNING' else 'INVALIDATED')
    assert service.cancel.is_set()==(state=='RUNNING')
    assert saved[-1]['binding_status']=='UNCONFIRMED'
