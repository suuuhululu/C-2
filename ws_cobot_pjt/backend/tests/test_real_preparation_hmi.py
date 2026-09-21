"""REAL 통신 모드의 HMI 시험. Action/관측 상대는 대역이며 로봇에 연결하지 않는다."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'ws_cobot1/src/c2_path'))
from app.monitor import create_app
from app.monitor_contract import uid
from app.preparation import real_input_config
from app.ros_bridge import RosBridge
from app.storage import Storage
from test_monitor import HEADERS, wait


def config_file(tmp_path):
    # 테스트용 원본: 현장 승인이나 실제 모션에 사용하지 않는다.
    source = ROOT/'ws_cobot1/src/c2_process/config/workpiece_real_trial_0921.json'
    path = tmp_path/'test-real.json'
    path.write_bytes(source.read_bytes())
    return path


def test_real_config_requires_explicit_real_file_and_keeps_native_values(tmp_path):
    store = Storage(tmp_path/'store')
    with pytest.raises(ValueError): real_input_config(store, None)
    sim = ROOT/'ws_cobot1/src/c2_process/config/workpiece_simulation.json'
    with pytest.raises(ValueError): real_input_config(store, sim)
    path = config_file(tmp_path)
    original = json.loads(path.read_bytes())
    rec = real_input_config(store, path)
    assert rec['payload']['workcell'] == original['workcell']
    assert rec['payload']['profiles'] == original['profiles']
    assert rec['payload']['source_mode'] == 'REAL'
    assert json.loads(store.read_asset(rec['id'], rec['sha256'])) == rec['payload']


def test_real_http_measure_result_never_binds_or_generates(tmp_path, monkeypatch):
    from app import ros_bridge
    calls = []
    class Peer:
        transport = 'ROS2'
        def __init__(self, emit, **kwargs):
            assert kwargs['mode'] == 'REAL'
            self.emit = emit
            self.preparation_client = self.generate_client = self
        def server_is_ready(self): return True
        async def start(self):
            await self.emit('state', dict(schema_version=2, source_mode='REAL', source_epoch='real-test', seq=1,
                status='IDLE', phase='', stop_state='NONE'))
        async def prepare_raw(self, goal, feedback):
            calls.append(deepcopy(goal))
            result = json.loads((ROOT/'ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())['result']
            result.update({k:v for k,v in goal.items() if k != 'schema_version'})
            result['validity'] = 'ESTIMATED'
            return result
    monkeypatch.setattr(ros_bridge, 'RosBridge', Peer)
    monkeypatch.setenv('C2_MONITOR_MODE', 'REAL')
    monkeypatch.setenv('C2_MONITOR_TRANSPORT', 'ros')
    monkeypatch.setenv('C2_PREPARATION_CONFIG', str(config_file(tmp_path)))
    with TestClient(create_app(tmp_path/'data')) as c:
        c.headers.update(HEADERS)
        initial = c.get('/api/operator/snapshot').json()
        assert initial['source_mode'] == 'REAL' and initial['connection'] == 'CONNECTED'
        config = initial['preparation']['input_config']
        body = dict(request_id=uid(), input_profile_snapshot_id=config['id'], input_profile_sha256=config['sha256'], height_m=.15)
        assert c.post('/api/operator/preparations', json=body).status_code == 202
        result = wait(c, '/api/operator/preparations/'+body['request_id'], lambda r:r['state'] not in ('ACCEPTED','RUNNING'))
        assert result['state'] == 'SUCCEEDED', result
        assert result['binding_status'] == 'MEASUREMENT_ONLY'
        assert result['result']['observed_state']['measurement']['validity'] == 'ESTIMATED'
        assert [g['operation'] for g in calls] == ['MEASURE']
        assert calls[0]['source_mode'] == 'REAL'
        after = c.get('/api/operator/snapshot').json()
        assert not after['preparation']['ready'] and not after['path_generation']['execution_enabled']
        assert after['profile'] == initial['profile']
        service = c.app.state.service
        from app.monitor_service import DomainError
        with pytest.raises(DomainError): asyncio.run(service.generate({}))
        with pytest.raises(DomainError): asyncio.run(service.start_run({}))


@pytest.mark.parametrize('operation', ['BIND_SNAPSHOT', 'GENERATE', 'EXECUTE'])
def test_real_bridge_blocks_non_measure_before_contacting_server(operation):
    bridge = RosBridge(None, mode='REAL')
    bridge.preparation_client = object()
    with pytest.raises(ValueError, match='MEASURE'):
        asyncio.run(bridge.action(bridge.preparation_client, None,
            dict(schema_version=2, source_mode='REAL', operation=operation)))


def test_real_bridge_rejects_sim_goal():
    bridge = RosBridge(None, mode='REAL')
    with pytest.raises(ValueError, match='모드'):
        asyncio.run(bridge.action(None, None, dict(schema_version=2, source_mode='SIMULATION')))
