"""HMI 입력 내보내기 → 원본 c2_path 계산 → 결과 가져오기. 로봇 비구동."""
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ws_cobot1/src/c2_path'))
pytest.importorskip('skimage')
pytest.importorskip('networkx')
from c2_path.artifacts import ManagedArtifactStore
from c2_path.pipeline import GeneratePipeline, matching_test_profile
from app.file_integration import FileIntegration
from app.monitor import create_app
from app.storage import Storage, digest, encoded
from test_path_artifacts import line_png, goal_for

HEADERS = {'x-c2-monitor': '1'}


def unzip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {i.filename: archive.read(i.filename) for i in archive.infolist()}


def zip_contents(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return data.getvalue()


@pytest.fixture
def exchange(tmp_path):
    app = create_app(tmp_path / 'hmi', tick=.02)
    with TestClient(app, headers=HEADERS) as client:
        profile = matching_test_profile()
        profile.update(tools_config_id='c2_tools', tools_config_version=1,
                       tip_calibration={'status': 'SIM_ONLY', 'custom_field': [1, 2, 3]})
        response = client.post('/api/operator/integration/profiles',
                               files={'file': ('snapshot.json', encoded(profile), 'application/json')})
        assert response.status_code == 201, response.text
        registered = response.json()
        asset = client.post('/api/operator/assets', files={'file': ('line.png', line_png(), 'image/png')}).json()
        goal = goal_for({'id': asset['asset_id'], 'sha256': asset['asset_sha256']}, registered)
        prepared = client.post('/api/operator/integration/inputs', json=goal)
        assert prepared.status_code == 201, prepared.text
        input_zip = client.get(prepared.json()['download_url']).content
        input_files = unzip(input_zip)
        # 같은 PC의 별도 작업 디렉터리에서 파일 전달을 검증한다.
        external = Storage(tmp_path / 'external')
        for item in json.loads(input_files['manifest.json'])['files']:
            external.put_asset(input_files[item['file']], item['kind'], item['mime'], item['file'],
                               item['metadata'], asset_id=item['asset_id'])
        generated = GeneratePipeline(ManagedArtifactStore(external.root)).run(goal)
        result = {**asdict(generated), 'success': True, 'error_code': 'NONE', 'message': '파일 통합 시험',
                  'validation_passed': True}
        path_asset_id = result.pop('path_asset_id')
        # 순수 계산 부가 필드는 ROS GeneratePath.Result 계약에 포함되지 않는다.
        result.pop('execution_precheck', None)
        result.pop('execution_message', None)
        ids = [goal['asset_id'], goal['profile_snapshot_id'], path_asset_id,
               result['svg_asset_id'], result['preview_asset_id'], result['validation_report_id']]
        records = [(external.asset(aid), external.read_asset(aid)) for aid in ids]
        output_zip = FileIntegration._archive(goal, records, result)
        yield client, goal, result, input_zip, output_zip


def import_zip(client, raw):
    return client.post('/api/operator/integration/results', files={'file': ('result.zip', raw, 'application/zip')})


def inventory(client):
    store = client.app.state.store
    with store.db() as db:
        rows = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in ('assets', 'path_versions', 'runs')}
    return rows, {p.name: p.read_bytes() for p in store.files.iterdir()}


def test_full_roundtrip_is_immutable_idempotent_and_preview_only(exchange):
    client, goal, result, input_zip, output_zip = exchange
    original_mode_profile = client.get('/api/operator/snapshot').json()['profile']['id']
    files = unzip(input_zip)
    assert digest(files['snapshot.json']) == goal['profile_sha256']
    assert json.loads(files['snapshot.json'])['tip_calibration']['custom_field'] == [1, 2, 3]
    loaded = import_zip(client, output_zip)
    assert loaded.status_code == 201, loaded.text
    metadata = loaded.json()
    assert metadata['origin'] == 'FILE_BUNDLE' and metadata['execution_enabled'] is False
    assert metadata['profile_snapshot']['id'] == goal['profile_snapshot_id']
    path_url = f'/api/operator/paths/{result["path_id"]}/versions/{result["path_version"]}'
    shown = client.get(path_url)
    assert shown.status_code == 200, shown.text
    assert shown.json()['preview']['contract'] == 'c2-path-preview/1'
    inventory_before = inventory(client)
    assert import_zip(client, output_zip).status_code == 201
    assert inventory(client) == inventory_before
    downloaded = client.get(f'/api/operator/integration/paths/{result["path_id"]}/versions/1/bundle')
    assert downloaded.status_code == 200, downloaded.text
    assert unzip(downloaded.content) == unzip(output_zip)
    assert len(client.get('/api/operator/integration/paths').json()) == 1
    assert client.get('/api/operator/snapshot').json()['profile']['id'] == original_mode_profile
    assert FileIntegration(client.app.state.store).profiles()['selected_id'] == goal['profile_snapshot_id']
    response = client.post('/api/operator/runs', json={
        'schema_version': 2, 'source_mode': 'SIMULATION', 'request_id': goal['request_id'],
        'path_id': result['path_id'], 'path_version': 1, 'path_sha256': result['path_sha256'],
        'operator_confirmed_fixture': True})
    assert response.status_code == 409 and response.json()['error_code'] == 'NOT_READY'
    assert client.get('/api/operator/runs').json() == []


@pytest.mark.parametrize('case', ['hash', 'missing', 'extra', 'traversal', 'preview_reference',
                                 'profile_changed', 'request_changed', 'duplicate_id', 'missing_result_field'])
def test_bad_bundles_leave_no_partial_data(exchange, case):
    client, goal, result, _, raw = exchange
    files = unzip(raw)
    manifest = json.loads(files['manifest.json'])
    if case == 'hash':
        files['path.json'] += b' '
    elif case == 'missing':
        del files['preview.json']
    elif case == 'extra':
        files['unexpected.txt'] = b'not registered'
    elif case == 'traversal':
        files['../outside.txt'] = b'never extracted'
    elif case == 'duplicate_id':
        manifest['files'][3]['asset_id'] = manifest['files'][2]['asset_id']
    elif case in ('preview_reference', 'profile_changed'):
        name = 'preview.json' if case == 'preview_reference' else 'snapshot.json'
        value = json.loads(files[name])
        value['profile_sha256' if case == 'preview_reference' else 'frame_id'] = 'different'
        files[name] = encoded(value)
        next(e for e in manifest['files'] if e['file'] == name)['sha256'] = digest(files[name])
    elif case == 'request_changed':
        value = json.loads(files['goal.json']); value['width_mm'] += 1
        files['goal.json'] = encoded(value)
        manifest['goal']['sha256'] = digest(files['goal.json'])
    elif case == 'missing_result_field':
        value = json.loads(files['result.json']); value.pop('error_code')
        files['result.json'] = encoded(value)
        manifest['result']['sha256'] = digest(files['result.json'])
    files['manifest.json'] = encoded(manifest)
    before = inventory(client)
    response = import_zip(client, zip_contents(files))
    assert response.status_code == 409, response.text
    assert inventory(client) == before
    assert client.app.state.store.generation(goal['request_id'])['state'] == 'EXPORTED'


def test_asset_collision_rolls_back_files_written_before_collision(exchange):
    client, _, result, _, raw = exchange
    client.app.state.store.put_asset(b'old file', 'svg', 'image/svg+xml', 'old.svg',
                                    asset_id=result['preview_asset_id'])
    before = inventory(client)
    response = import_zip(client, raw)
    assert response.status_code == 409 and response.json()['error_code'] == 'ASSET_CONFLICT'
    assert inventory(client) == before


def test_database_failure_rolls_back_new_files(exchange):
    client, _, _, _, raw = exchange
    with client.app.state.store.db() as db:
        db.execute("CREATE TRIGGER fail_path BEFORE INSERT ON path_versions BEGIN SELECT RAISE(ABORT,'test failure'); END")
    before = inventory(client)
    assert import_zip(client, raw).status_code == 503
    assert inventory(client) == before


def test_registration_deduplicates_content_and_preserves_extensions(exchange):
    client, goal, _, _, _ = exchange
    store = client.app.state.store
    raw = store.read_asset(goal['profile_snapshot_id'])
    value = json.loads(raw)
    pretty = json.dumps(value, indent=2).encode()
    same = client.post('/api/operator/integration/profiles', files={'file': ('same.json', pretty)})
    assert same.status_code == 201 and same.json()['id'] == goal['profile_snapshot_id']
    value['tip_calibration']['custom_field'].append(4)
    updated = client.post('/api/operator/integration/profiles', files={'file': ('new.json', encoded(value))})
    assert updated.status_code == 201 and updated.json()['id'] != goal['profile_snapshot_id']
    assert updated.json()['sha256'] != goal['profile_sha256']
    assert store.read_asset(goal['profile_snapshot_id']) == raw


@pytest.mark.parametrize('raw', [b'[]', b'{"source_mode":"SIMULATION","schema_version":2,"x":NaN}',
                               b'{"schema_version":2,"schema_version":2,"source_mode":"SIMULATION"}',
                               b'{"schema_version":2,"source_mode":"REAL"}',
                               b'{"schema_version":2,"source_mode":"SIMULATION","allow_real":true}'])
def test_invalid_profiles_are_rejected_without_registration(exchange, raw):
    client, _, _, _, _ = exchange
    before = inventory(client)
    response = client.post('/api/operator/integration/profiles', files={'file': ('bad.json', raw)})
    assert response.status_code == 409
    assert inventory(client) == before


def test_active_generation_blocks_profile_and_bundle_mutations(exchange):
    client, goal, _, _, raw = exchange
    client.app.state.service.generating = 'active-request'
    assert client.post(f'/api/operator/integration/profiles/{goal["profile_snapshot_id"]}/select', json={}).status_code == 409
    response = import_zip(client, raw)
    assert response.status_code == 409 and response.json()['error_code'] == 'BUSY'
    assert client.get('/api/operator/integration/profiles').status_code == 200
    client.app.state.service.generating = None


def test_malformed_zip_is_a_readable_error(exchange):
    client, _, _, _, _ = exchange
    before = inventory(client)
    response = import_zip(client, b'not a ZIP')
    assert response.status_code == 409 and response.json()['error_code'] == 'INVALID_INPUT'
    assert inventory(client) == before
