"""생성 취소의 접수/완료·새 화면 상태 복원·미확인 시 재진입 차단."""
import asyncio
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from app.monitor import create_app
from test_monitor import HEADERS, wait


def begin(c):
    import io
    from PIL import Image
    b=io.BytesIO();Image.new('RGB',(60,60),'white').save(b,format='PNG')
    a=c.post('/api/operator/assets',files={'file':('line.png',b.getvalue(),'image/png')}).json()
    p=c.get('/api/operator/snapshot').json()['profile']
    goal=dict(schema_version=2,request_id=str(uuid4()),source_mode='SIMULATION',
        asset_id=a['asset_id'],asset_sha256=a['asset_sha256'],width_mm=24,height_mm=24,
        offset_u_mm=0,offset_v_mm=75,rotation_deg=0,conversion_preset='simulation_centerline',
        tool_id='engraving_drill',profile_snapshot_id=p['id'],profile_sha256=p['sha256'])
    assert c.post('/api/operator/path-generations',json=goal).status_code==202
    return goal


def test_cancel_snapshot_reconnect_repeated_cancel_and_next_generation(tmp_path):
    with TestClient(create_app(tmp_path,tick=.03),headers=HEADERS) as c:
        g=begin(c);rid=g['request_id']
        # 새 화면은 메모리의 로컬 generating 대신 snapshot에서 진행 요청을 복원한다.
        assert c.get('/api/operator/snapshot').json()['generation']['request_id']==rid
        response=c.post(f'/api/operator/path-generations/{rid}/cancel')
        assert response.status_code==202
        assert response.json()['state']=='CANCELING'
        done=wait(c,f'/api/operator/path-generations/{rid}',lambda x:x['state']=='FAILED')
        assert done['result']['error_code']=='CANCELED'
        assert c.post(f'/api/operator/path-generations/{rid}/cancel').json()==done
        assert c.get('/api/operator/snapshot').json()['generation']==done
        with c.app.state.store.db() as db:
            assert db.execute('select count(*) from path_versions').fetchone()[0]==0
        # 같은 ID 재전송도 새 계산을 만들지 않는다.
        assert c.post('/api/operator/path-generations',json=g).json()['state']=='FAILED'
        next_goal=begin(c)
        next_result=wait(c,f'/api/operator/path-generations/{next_goal["request_id"]}',lambda x:x['state']=='SUCCEEDED')
        # 성공 확정 뒤 취소는 이미 완성된 결과를 유지한다.
        assert c.post(f'/api/operator/path-generations/{next_goal["request_id"]}/cancel').json()==next_result


def test_timeout_requests_cancel_and_confirms_before_releasing(tmp_path):
    with TestClient(create_app(tmp_path,tick=.03),headers=HEADERS) as c:
        c.app.state.service.generation_timeout=.02
        g=begin(c)
        done=wait(c,f'/api/operator/path-generations/{g["request_id"]}',lambda x:x['state']=='FAILED')
        assert done['result']['error_code']=='TIMEOUT'
        assert c.app.state.service.generating is None


def test_unconfirmed_cancel_keeps_busy_and_ignores_late_feedback(tmp_path):
    with TestClient(create_app(tmp_path,tick=.03),headers=HEADERS) as c:
        service=c.app.state.service
        service.generation_timeout=.02;service.generation_cancel_timeout=.02
        async def no_result(goal,feedback):
            await asyncio.sleep(30)
        async def no_confirmation(rid):
            return None
        service.peer.generate=no_result;service.peer.cancel_generation=no_confirmation
        g=begin(c)
        done=wait(c,f'/api/operator/path-generations/{g["request_id"]}',lambda x:x['state']=='UNKNOWN')
        assert done['result']['error_code']=='COMMUNICATION_LOST'
        assert service.generating==g['request_id']
        assert c.post('/api/operator/path-generations',json={**g,'request_id':str(uuid4())}).status_code==409
        assert c.post(f'/api/operator/path-generations/{g["request_id"]}/cancel').json()['state']=='UNKNOWN'


def test_cancel_before_ros_goal_acceptance_is_forwarded_after_acceptance():
    from types import SimpleNamespace
    from app.ros_bridge import RosBridge
    async def scenario():
        loop=asyncio.get_running_loop()
        result=loop.create_future()
        class Handle:
            accepted=True
            cancel_count=0
            def get_result_async(self):return result
            def cancel_goal_async(self):
                self.cancel_count+=1
                if not result.done():
                    result.set_result(SimpleNamespace(result={'success':False,'error_code':'CANCELED'}))
                response=loop.create_future();response.set_result(None);return response
        handle=Handle()
        class Goal:
            def get_fields_and_field_types(self):
                return {'schema_version':'uint16','source_mode':'string','request_id':'string'}
        class Client:
            def server_is_ready(self):return True
            def send_goal_async(self,goal,feedback_callback):
                accepted=loop.create_future()
                loop.call_later(.03,accepted.set_result,handle)
                return accepted
        bridge=RosBridge(None);bridge.loop=loop;bridge.convert=lambda x:x
        bridge.generate_client=Client()
        operation=asyncio.create_task(bridge.action(bridge.generate_client,SimpleNamespace(Goal=Goal),
            {'schema_version':2,'source_mode':'SIMULATION','request_id':'pending'}))
        await asyncio.sleep(0)
        await bridge.cancel_generation('pending')
        assert handle.cancel_count==0
        assert (await operation)['error_code']=='CANCELED'
        assert handle.cancel_count==1
        assert 'pending' not in bridge.handles
    asyncio.run(scenario())
