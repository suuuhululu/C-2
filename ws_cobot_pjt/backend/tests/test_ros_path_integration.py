"""C2_RUN_ROS_TESTS=1에서만 실제 Jazzy 액션 + HMI HTTP 통합. 로봇 API 없음."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.getenv('C2_RUN_ROS_TESTS') != '1', reason='실제 로컬 DDS 시험은 명시적으로 활성화')
pytest.importorskip('c2_interfaces.action')
from app.monitor import create_app
from app.storage import Storage
from test_path_artifacts import line_png


@pytest.fixture
def ros_client(tmp_path, monkeypatch):
    for key, value in dict(C2_MONITOR_TRANSPORT='ros', C2_MONITOR_MODE='SIMULATION',
                           ROS_DOMAIN_ID='174', ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
                           ROS_STATIC_PEERS='', RMW_IMPLEMENTATION='rmw_fastrtps_cpp',
                           ROS_LOG_DIR=str(tmp_path / 'ros_logs')).items():
        monkeypatch.setenv(key, value)
    directory = tmp_path / 'managed'
    Storage(directory)
    source = Path(__file__).resolve().parents[2] / 'ws_cobot1/src/c2_path'
    env = dict(os.environ)
    env['PYTHONPATH'] = str(source) + os.pathsep + env.get('PYTHONPATH', '')
    with (tmp_path / 'path_node.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'c2_path.node', '--ros-args',
                                    '-p', f'managed_data_dir:={directory}'], env=env, stdout=log, stderr=log)
        try:
            with TestClient(create_app(directory), headers={'x-c2-monitor': '1'}) as client:
                deadline = time.monotonic() + 15
                while not client.get('/api/operator/snapshot').json()['path_generation']['ready']:
                    assert process.poll() is None, (tmp_path / 'path_node.log').read_text()
                    assert time.monotonic() < deadline, '경로 서버 탐색 시간 초과'
                    time.sleep(.1)
                yield client, process
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)


def request_goal(client, **changes):
    snapshot = client.get('/api/operator/snapshot').json()
    assert snapshot['transport'] == 'ROS2' and snapshot['scenario'] is None
    assert snapshot['connection'] == 'STALE' and snapshot['state'] is None
    assert not snapshot['path_generation']['execution_enabled']
    upload = client.post('/api/operator/assets', files={'file': ('line.png', line_png(), 'image/png')})
    assert upload.status_code == 201
    a, p = upload.json(), snapshot['profile']
    goal = dict(schema_version=2, request_id=str(uuid4()), source_mode='SIMULATION',
                asset_id=a['asset_id'], asset_sha256=a['asset_sha256'],
                **snapshot['path_generation']['default_placement'],
                conversion_preset=snapshot['path_generation']['preset'], tool_id='engraving_drill',
                profile_snapshot_id=p['id'], profile_sha256=p['sha256'])
    goal.update(changes)
    return goal


def finish(client, goal):
    r = client.post('/api/operator/path-generations', json=goal)
    assert r.status_code == 202, r.text
    deadline = time.monotonic() + 20
    while True:
        generation = client.get('/api/operator/path-generations/' + goal['request_id']).json()
        if generation['state'] in ('SUCCEEDED', 'FAILED'):
            return generation
        assert time.monotonic() < deadline, generation
        time.sleep(.05)


def test_http_upload_ros_generation_preview_and_execution_block(ros_client):
    client, _ = ros_client
    goal = request_goal(client)
    generation = finish(client, goal)
    assert generation['state'] == 'SUCCEEDED', generation
    r = generation['result']
    assert r['success'] and r['segment_count'] == 3 and r['cut_length_m'] == .024
    response = client.get(f'/api/operator/paths/{r["path_id"]}/versions/{r["path_version"]}')
    assert response.status_code == 200, response.text
    p = response.json()
    assert p['preview']['contract'] == 'c2-path-preview/1'
    assert len(p['preview']['segments']) == 3 and 'strokes' not in p['preview']
    assert p['test_only'] and p['validation_not_checked'] == ['J6_RANGE']
    assert p['profile_snapshot']['sha256'] == goal['profile_sha256']
    for url in ('path_url', 'svg_url', 'validation_url'):
        assert client.get(p[url]).status_code == 200
    assert finish(client, goal)['result'] == r
    assert client.post('/api/operator/path-generations', json={**goal, 'width_mm': 25}).status_code == 409
    run = client.post('/api/operator/runs', json=dict(schema_version=2, source_mode='SIMULATION',
        request_id=str(uuid4()), path_id=r['path_id'], path_version=r['path_version'],
        path_sha256=r['path_sha256'], operator_confirmed_fixture=True))
    assert run.status_code == 409 and run.json()['error_code'] == 'NOT_READY'
    assert 'test_only' in run.json()['message']
    with client.app.state.store.db() as db:
        assert db.execute('SELECT count(*) FROM path_versions').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
    # 등록 뒤 파일/DB 해시를 함께 바꿔도 등록 당시 해시와 다르면 HTTP 조회 거절.
    store = client.app.state.store
    aid = p['preview_asset_id']
    rec = store.asset(aid)
    (store.files / rec['storage_key']).write_bytes(b'{}')
    import hashlib
    with store.db() as db:
        db.execute('UPDATE assets SET sha256=? WHERE id=?', (hashlib.sha256(b'{}').hexdigest(), aid))
    rejected = client.get(f'/api/operator/paths/{r["path_id"]}/versions/{r["path_version"]}')
    assert rejected.status_code == 409 and rejected.json()['error_code'] == 'HASH_MISMATCH'


def test_ros_mapping_failure_never_registers_path_and_mock_preset_is_rejected(ros_client):
    client, process = ros_client
    goal = request_goal(client, offset_v_mm=50.0)
    generation = finish(client, goal)
    assert generation['state'] == 'FAILED'
    assert generation['result']['error_code'] == 'VALIDATION_FAILED'
    assert not generation['result']['path_id']
    with client.app.state.store.db() as db:
        assert db.execute('SELECT count(*) FROM path_versions').fetchone()[0] == 0
    r = client.post('/api/operator/path-generations', json={**goal, 'request_id': str(uuid4()),
                                                         'conversion_preset': 'simulation_centerline'})
    assert r.status_code == 422 and r.json()['error_code'] == 'UNSUPPORTED_FORMAT'
    process.send_signal(signal.SIGINT)
    process.wait(timeout=8)
    deadline = time.monotonic() + 15
    while client.get('/api/operator/snapshot').json()['path_generation']['ready']:
        assert time.monotonic() < deadline, '종료한 경로 노드가 여전히 연결 상태로 표시됨'
        time.sleep(.1)
    disconnected = finish(client, {**goal, 'request_id': str(uuid4()), 'offset_v_mm': 107.5})
    assert disconnected['state'] == 'FAILED' and disconnected['result']['error_code'] == 'NOT_READY'
