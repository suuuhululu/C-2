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


@pytest.mark.parametrize('bind_rejected', [False, True])
def test_real_http_estimated_binds_and_sends_real_generate(tmp_path, monkeypatch, bind_rejected):
    from app import ros_bridge
    calls = []
    class Peer:
        transport = 'ROS2'
        def __init__(self, emit, **kwargs):
            assert kwargs['mode'] == 'REAL'
            self.emit = emit
            self.preparation_client = self.generate_client = self.execute_client = self
        def server_is_ready(self): return True
        async def start(self):
            await self.emit('state', dict(schema_version=2, source_mode='REAL', source_epoch='real-test', seq=1,
                status='IDLE', phase='', stop_state='NONE'))
        async def prepare_raw(self, goal, feedback):
            calls.append(deepcopy(goal))
            result = json.loads((ROOT/'ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())['result']
            result.update({k:v for k,v in goal.items() if k != 'schema_version'})
            result['validity'] = 'ESTIMATED'
            if goal['operation'] == 'BIND_SNAPSHOT':
                result.update(snapshot_bound=not bind_rejected, outcome='FAILED' if bind_rejected else 'SUCCEEDED',
                              error_code='NOT_READY' if bind_rejected else 'NONE', message='상대 BIND 거절' if bind_rejected else 'BIND 완료')
            return result
        async def generate(self, goal, feedback):
            calls.append(deepcopy(goal))
            return None, dict(success=False, error_code='NOT_READY', message='경로 담당 PR 대기')
    monkeypatch.setattr(ros_bridge, 'RosBridge', Peer)
    monkeypatch.setenv('C2_MONITOR_MODE', 'REAL')
    monkeypatch.setenv('C2_MONITOR_TRANSPORT', 'ros')
    path = config_file(tmp_path)
    cfg = json.loads(path.read_text())
    cfg['execution_profile'] = execution_template(cfg)
    path.write_text(json.dumps(cfg))
    monkeypatch.setenv('C2_PREPARATION_CONFIG', str(path))
    with TestClient(create_app(tmp_path/'data')) as c:
        c.headers.update(HEADERS)
        initial = c.get('/api/operator/snapshot').json()
        assert initial['source_mode'] == 'REAL' and initial['connection'] == 'CONNECTED'
        config = initial['preparation']['input_config']
        body = dict(request_id=uid(), input_profile_snapshot_id=config['id'], input_profile_sha256=config['sha256'], height_m=.15)
        assert c.post('/api/operator/preparations', json=body).status_code == 202
        result = wait(c, '/api/operator/preparations/'+body['request_id'], lambda r:r['state'] not in ('ACCEPTED','RUNNING'))
        assert result['result']['observed_state']['measurement']['validity'] == 'ESTIMATED'
        assert [g['operation'] for g in calls] == ['MEASURE', 'BIND_SNAPSHOT']
        assert all(g['source_mode'] == 'REAL' for g in calls)
        # 완료 원장 저장 직후에도 task의 마지막 저장이 끝날 때까지 다음 요청은 잠긴다.
        after = wait(c, '/api/operator/snapshot', lambda s:not s['preparation']['blocks_work'])
        if bind_rejected:
            assert result['state'] == 'FAILED' and result['message'] == '상대 BIND 거절'
            assert not after['preparation']['ready']
            return
        assert result['state'] == 'SUCCEEDED', result
        assert result['binding_status'] == 'BOUND_ROS'
        assert after['preparation']['ready'] and after['path_generation']['execution_enabled']
        profile = after['profile']
        assert profile['payload']['measurement_status'] == 'ESTIMATED'
        assert profile['payload']['contact_calibration']['offset_status'] == 'ESTIMATED'
        from test_path_artifacts import line_png, goal_for
        asset = c.post('/api/operator/assets', files={'file': ('line.png', line_png(), 'image/png')}).json()
        goal = goal_for(dict(id=asset['asset_id'], sha256=asset['asset_sha256']), profile)
        goal['source_mode'] = 'SIMULATION'
        assert c.post('/api/operator/path-generations', json=goal).status_code == 409
        goal['source_mode'] = 'REAL'
        assert c.post('/api/operator/path-generations', json=goal).status_code == 202
        generated = wait(c, '/api/operator/path-generations/'+goal['request_id'], lambda g:g['state']=='FAILED')
        assert generated['result']['message'] == '경로 담당 PR 대기'
        assert calls[-1]['source_mode'] == 'REAL'



@pytest.mark.parametrize('operation', ['BIND_SNAPSHOT', 'GENERATE', 'EXECUTE'])
def test_real_bridge_reaches_server_for_non_measure(operation):
    bridge = RosBridge(None, mode='REAL')
    from types import SimpleNamespace
    bridge.preparation_client = SimpleNamespace(server_is_ready=lambda: False)
    with pytest.raises(ConnectionError, match='서버'):
        asyncio.run(bridge.action(bridge.preparation_client, None,
            dict(schema_version=2, source_mode='REAL', operation=operation)))


def test_real_bridge_rejects_sim_goal():
    bridge = RosBridge(None, mode='REAL')
    with pytest.raises(ValueError, match='모드'):
        asyncio.run(bridge.action(None, None, dict(schema_version=2, source_mode='SIMULATION')))


def execution_template(config):
    from c2_path.pipeline import matching_test_profile_v4
    from c2_path.workcell import MOTION_PROFILE
    value = matching_test_profile_v4()
    # 형식 시험 전용이며 실제 사용값/승인값이 아니다.
    value['tip_calibration']['offset_tool_m'] = config['workcell']['tool_offset_m']
    value['execution_context'].update(
        motion_profiles={name: dict(vel_mm_s=1., acc_mm_s2=1., completion_timeout_s=1.)
                         for name in MOTION_PROFILE.values()},
        tool_profile=dict(tool_id=value['tool_id'], contact_mode='fixed_depth', depth_m=.001, clearance_m=.001),
        stop_profile=dict(mode=1, confirmation_timeout_s=1.))
    for k in ('tcp_id', 'load_id'):
        value[k] = config['workcell'][k]
    config['workcell']['top']['offset_status'] = 'ESTIMATED'
    return value


def test_missing_execution_settings_is_reported_without_promoting_sim(tmp_path):
    from app.ros_preparation import real_bound_profile
    with pytest.raises(ValueError, match='execution_profile'):
        real_bound_profile({}, {}, {'workcell': {}}, {})

@pytest.mark.parametrize('blocked', [None, 'OUT_OF_LIMITS', 'PREVIEW_ONLY', 'test_only'])
def test_real_execute_forwards_bound_candidate_and_preserves_peer_failure(tmp_path, blocked):
    """경로 메타데이터는 전송 시험대역이며 실제 모션에 쓰지 않는다."""
    from types import SimpleNamespace
    from app.monitor_service import MonitorService, DomainError
    store = Storage(tmp_path/'execute')
    service = MonitorService(store, 'ros', mode='REAL')
    profile = store.profile({'source_mode': 'REAL'})
    record = store.put_json({'fixture': 'measurement'}, 'measurement_record', 'test.json')
    cfg = store.put_json({'fixture': 'input'}, 'preparation_config', 'test.json')
    image = store.put_asset(b'fixture', 'image', 'image/png', 'test.png')
    assets = {k: store.put_json({'fixture': k}, kind, 'test.json') for k, kind in (
        ('path_asset_id','path'), ('preview_asset_id','preview'), ('svg_asset_id','svg'), ('validation_report_id','validation'))}
    prepared_id = uid()
    pid = uid()
    payload = dict(request_id=uid(), schema_version=2, source_mode='REAL', asset_id=image['id'], asset_sha256=image['sha256'])
    meta = dict(path_id=pid, path_version=1, path_sha256=assets['path_asset_id']['sha256'],
        source_mode='REAL', test_only=blocked=='test_only', real_execution_allowed=blocked!='test_only',
        validation_passed=True, input=payload, profile_snapshot_id=profile['id'], profile_sha256=profile['sha256'],
        preparation_id=prepared_id, execution_precheck=blocked if blocked=='OUT_OF_LIMITS' else 'WITHIN_LIMITS',
        execution_blocked=blocked if blocked=='PREVIEW_ONLY' else None, **{k:v['id'] for k,v in assets.items()})
    store.create_generation(payload)
    store.finish_generation(payload['request_id'], 'SUCCEEDED', {'success': True}, meta)
    service.profile=profile
    service.fresh=lambda: True
    service.preparation.config=dict(id=cfg['id'], sha256=cfg['sha256'])
    service.preparation.current=dict(state='SUCCEEDED', binding_status='BOUND_ROS', profile_snapshot=profile,
        goal=dict(preparation_id=prepared_id, measurement_id=uid()), measurement_record=dict(id=record['id'],sha256=record['sha256']))
    calls=[]
    class Peer:
        execute_client=SimpleNamespace(server_is_ready=lambda: True)
        def prepare(self, run): pass
        async def execute(self, goal):
            calls.append(goal)
            return dict(run_id=goal['run_id'], outcome='FAILED', error_code='NOT_READY', message='IK 검사 실패 대역')
    service.peer=Peer()
    async def scenario():
        body=dict(schema_version=2, request_id=uid(), source_mode='REAL', path_id=pid, path_version=1,
                  path_sha256=meta['path_sha256'], operator_confirmed_fixture=True)
        if blocked:
            with pytest.raises(DomainError): await service.start_run(body)
            assert not calls
            return
        result=await service.start_run(body)
        await asyncio.gather(*list(service.tasks))
        assert calls[0]['source_mode']=='REAL' and calls[0]['path_sha256']==meta['path_sha256']
        assert service.run['status']=='FAILED' and service.run['message']=='IK 검사 실패 대역'
        assert result['run_id']==calls[0]['run_id']
    asyncio.run(scenario())


@pytest.mark.parametrize('old', [False, True])
def test_real_missing_verification_clears_template(tmp_path, old):
    from app.ros_preparation import real_bound_profile, display_result
    config = json.loads(config_file(tmp_path).read_text())
    config['execution_profile'] = execution_template(config)
    config['execution_profile']['absolute_top_verified'] = old
    goal = dict(preparation_id=uid(), measurement_id=uid(), source_mode='REAL', height_m=.15,
                input_profile_snapshot_id=uid(), input_profile_sha256='a'*64)
    raw = json.loads((ROOT/'ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())['result']
    raw.update(source_mode='REAL', validity='ESTIMATED', preparation_id=goal['preparation_id'], measurement_id=goal['measurement_id'])
    raw.pop('absolute_top_verification_known', None)
    raw.pop('absolute_top_verified', None)
    before = deepcopy(config)
    result = real_bound_profile(goal, display_result(raw, goal), config, dict(id=uid(), sha256='b'*64))
    assert result['absolute_top_verified'] is None
    assert result['measurement_assumptions']['absolute_top_verified'] is None
    assert result['validity'] == 'ESTIMATED'
    assert config == before


def test_static_error_blocks_before_measure(tmp_path):
    from types import SimpleNamespace
    from app.preparation import PreparationService
    from app.monitor_service import DomainError
    store = Storage(tmp_path/'guard')
    owner = SimpleNamespace(mode='REAL', transport='ros', lock=asyncio.Lock(), store=store,
                            peer=SimpleNamespace(preparation_client=object()), fresh=lambda: False)
    service = PreparationService(owner)
    service.config = {'payload': {'workcell': {}}}
    assert 'execution_profile' in service.snapshot()['start_error']
    body = {'request_id': uid()}
    with pytest.raises(DomainError, match='execution_profile'):
        asyncio.run(service.begin(body))
    assert service.task is None


def test_real_contract_gap_is_reported():
    from app.ros_bridge import preparation_result_error
    class InstalledResult:
        @classmethod
        def get_fields_and_field_types(cls): return {'validity': 'string'}
    assert 'absolute_top_verified' in preparation_result_error(InstalledResult)


def test_real_launcher_uses_same_store_and_real_path_mode():
    import importlib.util
    spec = importlib.util.spec_from_file_location('run_monitor', ROOT/'run_monitor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = module.path_node_command('/python', '/shared/data', 'REAL')
    assert 'managed_data_dir:=/shared/data' in command
    assert 'source_mode:=REAL' in command
    assert 'allow_real_execution:=true' in command
    assert 'allow_real_execution:=true' not in module.path_node_command('/python', '/data', 'SIMULATION')


@pytest.mark.parametrize('section,key', [
    ('stop_profile', 'confirmation_timeout_s'), ('tool_profile', 'depth_m'),
    ('tool_profile', 'clearance_m'), ('motion_profiles', 'candle_cut')])
def test_static_nested_omissions_are_rejected(tmp_path, section, key):
    from app.real_execution_config import validate_real_execution_config
    config = json.loads(config_file(tmp_path).read_text())
    config['execution_profile'] = execution_template(config)
    validate_real_execution_config(config)
    del config['execution_profile']['execution_context'][section][key]
    with pytest.raises(ValueError, match=key):
        validate_real_execution_config(config)


@pytest.mark.parametrize('known,verified', [(True, False), (True, True), (False, False)])
def test_current_confidence_overwrites_template(tmp_path, known, verified):
    from app.ros_preparation import real_bound_profile, display_result
    config = json.loads(config_file(tmp_path).read_text())
    config['execution_profile'] = execution_template(config)
    config['execution_profile'].update(absolute_top_verification_known=not known, absolute_top_verified=not verified)
    goal = dict(preparation_id=uid(), measurement_id=uid(), source_mode='REAL', height_m=.15,
                input_profile_snapshot_id=uid(), input_profile_sha256='a'*64)
    raw = json.loads((ROOT/'ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())['result']
    raw.update(source_mode='REAL', validity='ESTIMATED', preparation_id=goal['preparation_id'], measurement_id=goal['measurement_id'],
               absolute_top_verification_known=known, absolute_top_verified=verified)
    result = real_bound_profile(goal, display_result(raw, goal), config, dict(id=uid(), sha256='b'*64))
    for key in ('absolute_top_verification_known', 'absolute_top_verified'):
        assert result[key] is raw[key]
        assert result['measurement_assumptions'][key] is raw[key]
