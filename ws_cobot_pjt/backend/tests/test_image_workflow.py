"""운영자 이미지 한 장 → 기존 준비/생성/공정 API. ZIP 없음."""
import sys
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'ws_cobot1/src/c2_path'))
from app.monitor import create_app
from test_monitor import HEADERS, wait, run_body
from test_preparation import prepare
from test_path_artifacts import line_png

@pytest.fixture
def image_client(tmp_path, monkeypatch):
    monkeypatch.setenv('C2_IMAGE_WORKFLOW','1')
    monkeypatch.setenv('C2_MONITOR_TRANSPORT','mock')
    monkeypatch.setenv('C2_MONITOR_MODE','SIMULATION')
    with TestClient(create_app(tmp_path,tick=.005),headers=HEADERS) as c:
        yield c


def generate(c):
    asset=c.post('/api/operator/assets',files={'file':('line.png',line_png(),'image/png')}).json()
    snapshot=c.get('/api/operator/snapshot').json();p=snapshot['profile']
    goal=dict(schema_version=2,request_id=str(uuid4()),source_mode='SIMULATION',asset_id=asset['asset_id'],
        asset_sha256=asset['asset_sha256'],profile_snapshot_id=p['id'],profile_sha256=p['sha256'],
        tool_id='engraving_drill',conversion_preset='raster_centerline_bezier',
        width_mm=15.,height_mm=15.,offset_u_mm=0.,offset_v_mm=75.,rotation_deg=0.)
    response=c.post('/api/operator/path-generations',json=goal)
    assert response.status_code==202,response.text
    g=wait(c,'/api/operator/path-generations/'+goal['request_id'],lambda g:g['state'] in ('SUCCEEDED','FAILED','UNKNOWN'))
    assert g['state']=='SUCCEEDED',g
    r=g['result']
    path=c.get(f"/api/operator/paths/{r['path_id']}/versions/{r['path_version']}").json()
    return goal,path


def test_one_image_preparation_preview_run_and_history(image_client):
    c=image_client
    p=prepare(c);assert p['state']=='SUCCEEDED',p
    goal,path=generate(c)
    assert path['preview']['contract']=='c2-path-preview/1'
    assert path['input']['asset_id']==goal['asset_id']
    assert path['preparation_id']==p['goal']['preparation_id']
    assert c.get('/api/operator/snapshot').json()['path_generation']['test_only_execution']
    response=c.post('/api/operator/runs',json=run_body(path));assert response.status_code==202,response.text
    run=wait(c,'/api/operator/runs/'+response.json()['run_id'],lambda r:r['status'] in ('SUCCEEDED','FAILED','UNKNOWN'))
    assert run['status']=='SUCCEEDED',run
    assert run['path_sha256']==path['path_sha256']


def test_remeasurement_invalidates_previous_image_path(image_client):
    c=image_client;assert prepare(c)['state']=='SUCCEEDED'
    _,path=generate(c)
    assert prepare(c)['state']=='SUCCEEDED'
    response=c.post('/api/operator/runs',json=run_body(path))
    assert response.status_code==409 and response.json()['error_code']=='PROFILE_MISMATCH'


def test_process_connection_uses_existing_requests_and_displays_peer_failure(tmp_path, monkeypatch):
    """전송 시험대역. 준비는 main 공정 handler, 실행은 상대 실패 응답을 전달한다."""
    import asyncio
    from types import SimpleNamespace
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ws_cobot1/src/c2_process'))
    from app.image_peer import ImageMockPeer
    from c2_process.node import ProcessCoordinator
    from c2_process.preparation_action import AssetResolver, PreparationActionHandler, make_simulation_runner_factory
    calls=[]
    class HandlerBridge(ImageMockPeer):
        transport='ROS2'
        def __init__(self,emit,artifact_loader,mode):
            from c2_path.pipeline import matching_test_profile
            store=artifact_loader.store
            super().__init__(store,store.profile(matching_test_profile()),emit,.005)
            self.generate_client=self.execute_client=self.preparation_client=SimpleNamespace(server_is_ready=lambda:True)
            coordinator=ProcessCoordinator()
            self.handler=PreparationActionHandler(coordinator,
                AssetResolver(fetch=lambda aid,timeout:store.read_asset(aid)),tmp_path/'process.db',
                make_simulation_runner_factory()(coordinator))
        async def prepare_raw(self,goal,feedback):
            calls.append(goal['operation'])
            events=[]
            result=await asyncio.to_thread(self.handler.execute,goal,events.append)
            for e in events:await feedback(e)
            return result
        async def generate(self,goal,feedback):
            calls.append('GeneratePath')
            meta,result=await super().generate(goal,feedback)
            if meta:meta.pop('execution_backend')
            return meta,result
        async def execute(self,goal):
            calls.append(('ExecuteProcess',goal))
            return dict(run_id=goal['run_id'],outcome='FAILED',error_code='NOT_READY',
                        message='공정 실행 입력 로더 미연결',last_completed_segment_id='',log_id='')
        async def close(self):
            await super().close()
            self.handler.db.close()
    monkeypatch.setattr('app.ros_bridge.RosBridge',HandlerBridge)
    monkeypatch.setenv('C2_MONITOR_TRANSPORT','ros')
    monkeypatch.setenv('C2_MONITOR_MODE','SIMULATION')
    monkeypatch.setenv('C2_ROS_EXECUTION_SIM','1')
    monkeypatch.setenv('C2_IMAGE_WORKFLOW','1')
    with TestClient(create_app(tmp_path/'hmi',tick=.005),headers=HEADERS) as c:
        prep=prepare(c);assert prep['binding_status']=='BOUND_ROS',prep
        _,path=generate(c)
        response=c.post('/api/operator/runs',json=run_body(path));assert response.status_code==202,response.text
        run=wait(c,'/api/operator/runs/'+response.json()['run_id'],lambda r:r['status']=='FAILED')
        assert run['message']=='공정 실행 입력 로더 미연결'
        assert calls[:3]==['MEASURE','BIND_SNAPSHOT','GeneratePath']
        assert calls[3][0]=='ExecuteProcess'
        assert calls[3][1]['path_sha256']==path['path_sha256']
        assert calls[3][1]['source_mode']=='SIMULATION'
