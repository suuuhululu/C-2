"""HMI 작업 영역 설정과 기존 ROS 스냅샷을 구분하는 모의 시험."""
from copy import deepcopy

from fastapi.testclient import TestClient

from app.monitor import create_app
from app.mock_peer import PROFILE, artifacts
from app.storage import Storage
from app.work_area import load_policy, mock_profile_with_policy, register_policy


def test_policy_snapshot_is_persisted_without_mutating_path_profile(tmp_path):
    store = Storage(tmp_path)
    before = deepcopy(PROFILE)
    policy = register_policy(store)
    assert policy == register_policy(store)
    assert policy['payload']['top_exclusion_mm'] == 10
    assert policy['payload']['bottom_exclusion_mm'] == 10
    value = mock_profile_with_policy(PROFILE, policy['payload'])
    assert value['surface']['valid_v_range_mm'] == [10, 140]
    assert PROFILE == before


def test_http_distinguishes_policy_from_path_profile(tmp_path):
    with TestClient(create_app(tmp_path, tick=.01)) as c:
        value = c.get('/api/operator/snapshot').json()
        policy = value['work_area_policy']
        assert policy['id'] != value['profile']['id']
        assert value['profile']['payload']['surface']['valid_v_range_mm'] == [10, 140]
        assert c.get(f"/api/operator/assets/{policy['id']}/content").json() == policy['payload']


def test_mock_validation_uses_snapshot_and_diagnostic_uses_same_bounds(tmp_path):
    store = Storage(tmp_path)
    raw = deepcopy(PROFILE)
    raw['surface']['height_mm'] = 200
    raw['surface']['valid_v_range_mm'] = [40, 180]
    profile = store.profile(raw)
    goal = dict(asset_id='image', asset_sha256='0'*64, tool_id='engraving_drill',
                width_mm=20, height_mm=20, offset_u_mm=0, offset_v_mm=160, rotation_deg=0)
    metadata, result = artifacts(goal, profile, store)
    assert result['success']  # 기존 140mm 고정 제한과 달리 현재 스냅샷에서는 유효한 배치.
    _, failed = artifacts({**goal, 'offset_v_mm': 30}, profile, store)
    assert failed['success'] is False
    svg = store.read_asset(failed['diagnostic_asset_id']).decode()
    assert 'y="20"' in svg and 'height="140"' in svg


def test_mock_policy_handles_asymmetric_exclusions():
    policy = {**load_policy(), 'top_exclusion_mm': 10, 'bottom_exclusion_mm': 20}
    assert mock_profile_with_policy(PROFILE, policy)['surface']['valid_v_range_mm'] == [20, 140]
