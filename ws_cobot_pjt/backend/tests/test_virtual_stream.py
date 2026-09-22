"""가상 실행기 포트에서 HTTP/실시간 스트림이 같은 Origin 규칙을 사용한다."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.monitor import create_app

@pytest.mark.parametrize('port',[8020,8025])
def test_virtual_browser_stream_and_http_origin(tmp_path,monkeypatch,port):
    origin=f'http://127.0.0.1:{port}'
    monkeypatch.setenv('C2_VIRTUAL_CELL','1')
    monkeypatch.setenv('C2_VIRTUAL_ORIGIN',origin)
    monkeypatch.setenv('C2_MONITOR_MODE','SIMULATION')
    monkeypatch.setenv('C2_MONITOR_TRANSPORT','mock')
    with TestClient(create_app(tmp_path)) as client:
        with client.websocket_connect('/api/operator/stream',headers={'origin':origin}) as ws:
            first=ws.receive_json();second=ws.receive_json()
            assert first['type']==second['type']=='snapshot'
            assert second['data']['connection']=='CONNECTED'
        assert client.post('/api/operator/preparations',json={},headers={'origin':origin,'x-c2-monitor':'1'}).status_code==422
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/operator/stream',headers={'origin':'http://untrusted.invalid'}):pass
