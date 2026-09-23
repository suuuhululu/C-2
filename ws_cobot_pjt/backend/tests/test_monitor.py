"""새 모니터 계약·DB·모의 실행 시험. 실제 ROS나 장치에 연결하지 않는다."""
import io
import json
import sqlite3
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.monitor import create_app
from app.monitor_contract import now

HEADERS={'x-c2-monitor':'1'}


@pytest.fixture
def client(tmp_path):
    app=create_app(tmp_path/'new-monitor',tick=.025)
    with TestClient(app,headers=HEADERS) as c:
        yield c


def wait(c,url,predicate,timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=c.get(url)
        assert result.status_code==200,result.text
        obj=result.json()
        if predicate(obj):return obj
        time.sleep(.02)
    raise AssertionError(obj)


def generated(c,**overrides):
    state=c.get('/api/operator/snapshot').json()['preparation']
    if state['supported'] and not state['ready']:
        config=state['input_config']
        request_id=str(uuid4())
        response=c.post('/api/operator/preparations',json=dict(request_id=request_id,
            input_profile_snapshot_id=config['id'],input_profile_sha256=config['sha256'],
            height_m=config['payload']['workcell']['height_m']))
        assert response.status_code==202,response.text
        wait(c,'/api/operator/snapshot',lambda s:s['preparation']['ready'] and not s['preparation']['blocks_work'])
    buf=io.BytesIO();Image.new('RGB',(80,120),'white').save(buf,format='PNG')
    upload=c.post('/api/operator/assets',files={'file':('test.png',buf.getvalue(),'image/png')})
    assert upload.status_code==201,upload.text
    a=upload.json();profile=c.get('/api/operator/snapshot').json()['profile']
    body=dict(schema_version=2,request_id=str(uuid4()),source_mode='SIMULATION',asset_id=a['asset_id'],
              asset_sha256=a['asset_sha256'],width_mm=70,height_mm=108,offset_u_mm=0,offset_v_mm=75,
              rotation_deg=0,conversion_preset='simulation_centerline',tool_id='engraving_drill',
              profile_snapshot_id=profile['id'],profile_sha256=profile['sha256'])
    body.update(overrides)
    response=c.post('/api/operator/path-generations',json=body)
    assert response.status_code==202,response.text
    g=wait(c,f'/api/operator/path-generations/{body["request_id"]}',lambda g:g['state'] in ('FAILED','SUCCEEDED'))
    if not g['result']['success']:return body,g
    p=c.get(f'/api/operator/paths/{g["result"]["path_id"]}/versions/1')
    assert p.status_code==200,p.text
    return body,p.json()


def run_body(p):
    return dict(schema_version=2,request_id=str(uuid4()),source_mode='SIMULATION',path_id=p['path_id'],
                path_version=1,path_sha256=p['path_sha256'],operator_confirmed_fixture=True)


def test_upload_generation_version_and_inspection(client):
    c=client;body,p=generated(c)
    assert p['preview']['profile_snapshot_id']==body['profile_snapshot_id']
    assert 'surface' not in p['preview']
    assert p['preview']['path_sha256']==p['path_sha256']
    assert p['preview']['pose_reference']=='tool_tip'
    assert c.get(p['svg_url']).headers['content-type'].startswith('image/svg+xml')
    b=run_body(p);r=c.post('/api/operator/runs',json=b)
    assert r.status_code==202,r.text
    rid=r.json()['run_id']
    assert c.post('/api/operator/runs',json=b).json()['run_id']==rid
    assert c.post('/api/operator/runs',json={**b,'path_sha256':'0'*64}).status_code==409
    done=wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='SUCCEEDED')
    assert done['engraving_progress']==1
    inspection=c.post('/api/operator/inspections',json={'run_id':rid,'verdict':'HOLD','reason':'모의 결과 확인'})
    assert inspection.status_code==201,inspection.text
    assert c.get(f'/api/operator/runs/{rid}').json()['inspections'][0]['verdict']=='HOLD'
    assert len(c.get('/api/operator/runs').json())==1
    assert c.post('/api/operator/path-generations',json=body).json()['result']['path_id']==p['path_id']
    assert c.post('/api/operator/path-generations',json={**body,'width_mm':60}).status_code==409


def test_rejections_and_failed_path_never_runs(client):
    c=client
    assert c.post('/api/operator/assets',files={'file':('bad.png',b'bad','image/png')}).status_code==415
    _,p=generated(c)
    b=run_body(p)
    assert c.post('/api/operator/runs',json={**b,'source_mode':'REAL'}).status_code==409
    assert c.post('/api/operator/runs',json={**b,'operator_confirmed_fixture':False}).status_code==422
    assert c.post('/api/operator/runs',json={**b,'path_sha256':'0'*64}).status_code==409
    c.post('/api/operator/simulation/scenario',json={'scenario':'generation_failure'})
    body,g=generated(c)
    assert g['state']=='FAILED' and 'path_id' not in g['result']
    with sqlite3.connect(c.app.state.store.db_path) as db:
        assert db.execute('SELECT count(*) FROM path_versions').fetchone()[0]==1


def test_stop_preempts_db_lock_and_never_advances(client):
    c=client;_,p=generated(c)
    r=c.post('/api/operator/runs',json=run_body(p)).json();rid=r['run_id']
    with sqlite3.connect(c.app.state.store.db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        start=time.monotonic()
        body={'request_id':str(uuid4()),'reason':'정지 시험'}
        stopped=c.post(f'/api/operator/runs/{rid}/stop',json=body)
        assert stopped.status_code==202,stopped.text
        assert time.monotonic()-start<.2
        assert stopped.json()['accepted'] and stopped.json()['stop_state']=='ACCEPTED'
        assert c.post(f'/api/operator/runs/{rid}/stop',json=body).json()==stopped.json()
        db.rollback()
    done=wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='STOPPED')
    assert done['engraving_progress']<1
    assert c.post(f'/api/operator/runs/{uuid4()}/stop',json={'request_id':str(uuid4())}).status_code==409


def test_grip_failure_and_unknown_stop_blocking(client):
    c=client;_,p=generated(c)
    c.post('/api/operator/simulation/scenario',json={'scenario':'grip_failure'})
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    done=wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='FAILED')
    assert done['phase']=='PRECHECK' and done['engraving_progress']==0
    wait(c,'/api/operator/alarms',lambda a:bool(a))
    c.post('/api/operator/simulation/scenario',json={'scenario':'stop_unknown'})
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    c.post(f'/api/operator/runs/{rid}/stop',json={'request_id':str(uuid4())})
    wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='UNKNOWN')
    c.post(f'/api/operator/runs/{rid}/stop',json={'request_id':str(uuid4())})
    assert c.get(f'/api/operator/runs/{rid}').json()['status']=='UNKNOWN'
    assert c.post('/api/operator/runs',json=run_body(p)).status_code==409
    assert c.post('/api/operator/inspections',json={'run_id':rid,'verdict':'PASS','reason':'미확인'}).status_code==409


def test_asset_tampering_and_stale_connection(client):
    c=client;_,p=generated(c)
    c.post('/api/operator/simulation/scenario',json={'scenario':'communication_loss'})
    wait(c,'/api/operator/snapshot',lambda s:s['connection']=='STALE',timeout=3)
    assert c.post('/api/operator/runs',json=run_body(p)).status_code==409
    c.post('/api/operator/simulation/scenario',json={'scenario':'normal'})
    wait(c,'/api/operator/snapshot',lambda s:s['connection']=='CONNECTED')
    assert c.post('/api/operator/runs',json=run_body(p)).json()['error_code']=='NOT_READY'
    assert not c.get('/api/operator/snapshot').json()['preparation']['ready']
    _,p=generated(c)  # 재연결 뒤 새 준비와 새 경로가 필요하다.
    asset=c.app.state.store.asset(p['path_asset_id'])
    (c.app.state.store.files/asset['storage_key']).write_text('{}')
    response=c.post('/api/operator/runs',json=run_body(p))
    assert response.status_code==409 and response.json()['error_code']=='HASH_MISMATCH'


def test_db_persists_and_restarts_do_not_replay(tmp_path):
    folder=tmp_path/'monitor'
    with TestClient(create_app(folder,tick=.08),headers=HEADERS) as c:
        _,p=generated(c)
        rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    with TestClient(create_app(folder,tick=.01),headers=HEADERS) as c:
        assert c.get(f'/api/operator/runs/{rid}').json()['status']=='UNKNOWN'
        assert c.post('/api/operator/runs',json=run_body(p)).status_code==409
        assert c.get('/api/operator/snapshot').json()['state']['run_id']==''


def test_local_post_guard(client):
    assert client.post('/api/operator/simulation/reset',headers={'x-c2-monitor':'0'},json={}).status_code==403


def test_failed_diagnostic_cannot_become_a_path(client):
    c=client;_,g=generated(c,offset_v_mm=160)
    result=g['result']
    assert g['state']=='FAILED' and 'path_id' not in result
    assert result['diagnostic_only'] and result['issues'][0]['reason']=='OUT_OF_MOCK_BOUNDS'
    aid=result['diagnostic_asset_id']
    assert c.get(f'/api/operator/assets/{aid}/content').status_code==200
    assert c.get(f'/api/operator/paths/{aid}/versions/1').status_code==404


def test_preview_tampering_and_non_image_input(client):
    c=client;body,p=generated(c)
    bad={**body,'request_id':str(uuid4()),'asset_id':p['preview_asset_id']}
    assert c.post('/api/operator/path-generations',json=bad).status_code==415
    a=c.app.state.store.asset(p['preview_asset_id'])
    (c.app.state.store.files/a['storage_key']).write_text('{}')
    assert c.get(f'/api/operator/paths/{p["path_id"]}/versions/1').status_code==409
    assert c.post('/api/operator/runs',json=run_body(p)).status_code==409


def test_ros_serialization_replaces_non_finite_values():
    from app.ros_bridge import json_values
    assert json_values({'tcp':[0.0,float('nan'),float('inf')]})=={'tcp':[0.0,None,None]}


@pytest.mark.parametrize('wrong_id',[False,True])
def test_late_success_and_mismatched_result_stay_unknown(client,wrong_id):
    c=client;_,p=generated(c);peer=c.app.state.service.peer
    async def late_result(goal):
        await peer.stop_event.wait()
        return dict(run_id=str(uuid4()) if wrong_id else goal['run_id'],outcome='SUCCEEDED',error_code='NONE',message='늦은 성공')
    peer.execute=late_result
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    c.post(f'/api/operator/runs/{rid}/stop',json={'request_id':str(uuid4())})
    wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='UNKNOWN')
    assert c.post('/api/operator/runs',json=run_body(p)).status_code==409


def test_accepted_stop_without_confirmation_times_out(client):
    import asyncio
    c=client;_,p=generated(c);s=c.app.state.service
    s.stop_confirmation_timeout=.12
    async def no_result(goal):await asyncio.Future()
    s.peer.execute=no_result
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    body={'request_id':str(uuid4())}
    accepted=c.post(f'/api/operator/runs/{rid}/stop',json=body)
    assert accepted.json()['accepted']
    r=wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='UNKNOWN')
    assert r['error_code']=='STOP_UNCONFIRMED'
    assert c.post(f'/api/operator/runs/{rid}/stop',json=body).json()==accepted.json()
    assert c.get(f'/api/operator/runs/{rid}').json()['status']=='UNKNOWN'


def test_quality_failure_is_separate_from_motion_and_is_persisted(client):
    c=client;_,p=generated(c)
    c.post('/api/operator/simulation/scenario',json={'scenario':'cut_quality_failure'})
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    r=wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='FAILED')
    assert r['phase']=='ENGRAVE'
    preview=r['execution_preview']
    assert preview['path_sha256']==p['path_sha256']
    observations=preview['observations']
    assert len([o for o in observations if o['verdict']=='PASSED'])==5
    failed=[o for o in observations if o['verdict']=='FAILED']
    assert len(failed)==1 and failed[0]['motion_status']=='COMPLETED'
    assert failed[0]['pressure_n'] is None
    assert failed[0]['reason']=='SIMULATED_PRESSURE_NOT_CONFIRMED'
    assert len([o for o in observations if o['verdict']=='PENDING'])==11
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        stored=c.app.state.store.run(rid)
        if stored.get('execution_preview')==preview:break
        time.sleep(.01)
    assert stored['execution_preview']==preview


def test_interrupted_segment_is_unknown_not_passed(client):
    c=client;_,p=generated(c)
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    wait(c,f'/api/operator/runs/{rid}',lambda r:any(o['verdict']=='IN_PROGRESS' for o in r.get('execution_preview',{}).get('observations',[])))
    c.post(f'/api/operator/runs/{rid}/stop',json={'request_id':str(uuid4())})
    r=wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='STOPPED')
    assert any(o['verdict']=='UNKNOWN' for o in r['execution_preview']['observations'])


def observe_peer(client):
    """실제 UI 전송 경계의 상태·이벤트를 모아 금지 단계와 열기 여부를 검사한다."""
    from copy import deepcopy
    peer=client.app.state.service.peer
    emit=peer.emit
    packets=[]
    async def capture(kind,data):
        packets.append((kind,deepcopy(data)))
        await emit(kind,data)
    peer.emit=capture
    return packets


def test_fixed_drill_finishes_without_pick_clean_place_or_open(client):
    c=client;_,p=generated(c);packets=observe_peer(c)
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='SUCCEEDED')
    phases=[v['phase'] for k,v in packets if k=='event' and v['event_type']=='PHASE_CHANGED']
    assert phases==['PRECHECK','ENTRY','ENGRAVE','RETURN_HOME','FINISH']
    states=[v for k,v in packets if k=='state']
    assert not any(s['grip_state'] in ('OPEN','OPENING') for s in states)
    assert states[-1]['mounted_tool_id']=='engraving_drill' and states[-1]['grip_state']=='GRIPPED'
    snapshot=c.get('/api/operator/snapshot').json()
    assert snapshot['schema_version']==2
    assert snapshot['profile']['payload']['gripper_open_allowed'] is False
    assert p['preview']['frame_id']=='c2_base'


def test_calibration_failure_does_not_rewrite_path_or_advance(client):
    c=client;_,p=generated(c);packets=observe_peer(c)
    before=c.app.state.store.read_asset(p['path_asset_id'])
    c.post('/api/operator/simulation/scenario',json={'scenario':'calibration_failure'})
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    done=wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='FAILED')
    assert done['phase']=='PRECHECK' and done['engraving_progress']==0
    assert done['error_code']=='PROFILE_MISMATCH'
    assert c.app.state.store.read_asset(p['path_asset_id'])==before
    assert not any(v.get('phase') in ('ENTRY','ENGRAVE','RETURN_HOME') for _,v in packets)
    assert not any(v.get('grip_state') in ('OPEN','OPENING') for _,v in packets)


def test_stop_during_entry_never_enters_engraving_or_opens(client):
    c=client;_,p=generated(c);packets=observe_peer(c)
    c.app.state.service.peer.tick=.10
    rid=c.post('/api/operator/runs',json=run_body(p)).json()['run_id']
    wait(c,f'/api/operator/runs/{rid}',lambda r:r['phase']=='ENTRY')
    c.post(f'/api/operator/runs/{rid}/stop',json={'schema_version':2,'request_id':str(uuid4())})
    wait(c,f'/api/operator/runs/{rid}',lambda r:r['status']=='STOPPED')
    assert not any(v.get('phase') in ('ENGRAVE','RETURN_HOME') for _,v in packets)
    assert not any(v.get('grip_state') in ('OPEN','OPENING') for _,v in packets)


def test_v1_requests_and_stored_paths_cannot_start_new_execution(client):
    c=client;goal,p=generated(c)
    assert c.post('/api/operator/path-generations',json={**goal,'schema_version':1,'request_id':str(uuid4())}).status_code==422
    assert c.post('/api/operator/path-generations',json={**goal,'tool_id':'engraving_knife','request_id':str(uuid4())}).status_code==422
    assert c.post('/api/operator/runs',json={**run_body(p),'schema_version':1}).status_code==422
    # v1 과거 경로가 남은 DB를 재현한다. 조회는 유지하고 v2 새 실행만 차단한다.
    with sqlite3.connect(c.app.state.store.db_path) as db:
        row=db.execute('SELECT payload FROM path_versions WHERE path_id=?',(p['path_id'],)).fetchone()
        old=json.loads(row[0]);old['input']['schema_version']=1
        db.execute('UPDATE path_versions SET payload=? WHERE path_id=?',(json.dumps(old),p['path_id']))
    assert c.get(f'/api/operator/paths/{p["path_id"]}/versions/1').status_code==200
    response=c.post('/api/operator/runs',json=run_body(p))
    assert response.status_code==409 and response.json()['error_code']=='UNSUPPORTED_SCHEMA_VERSION'
    assert c.get('/api/operator/snapshot').json()['state']['run_id']==''


def test_v1_state_is_not_treated_as_fresh_v2(client):
    c=client;s=c.app.state.service
    s.peer.scenario='communication_loss'
    c.portal.call(s.receive,'state',{**s.peer.state,'schema_version':1,'seq':999})
    snapshot=c.get('/api/operator/snapshot').json()
    assert snapshot['connection']=='STALE' and 'v2' in snapshot['contract_status']


def test_stroke_span_over_180_degrees_is_diagnostic_only(client,monkeypatch):
    # U=-60..60 mm는 양쪽 이음매 ±106.8 안이지만 한 획의 180° 범위를 초과한다.
    monkeypatch.setattr('app.mock_peer.sample_strokes',lambda:[[(-.5,0),(.5,0)]])
    c=client;_,g=generated(c,width_mm=120,height_mm=50)
    assert g['state']=='FAILED'
    assert any(i['reason']=='MOCK_STROKE_SPAN_EXCEEDED' for i in g['result']['issues'])
    assert 'path_id' not in g['result']
