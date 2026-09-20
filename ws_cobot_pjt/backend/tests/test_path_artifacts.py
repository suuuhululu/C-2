"""PR #38 원본 파이프라인 산출물을 사용한 결과 로더 검증. ROS·로봇 비구동."""
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ws_cobot1/src/c2_path'))
pytest.importorskip('skimage')
pytest.importorskip('networkx')
import cv2
import numpy as np
from c2_path.artifacts import ManagedArtifactStore
from c2_path.pipeline import GeneratePipeline, matching_test_profile
from app.artifact_loader import ArtifactLoadError, PathArtifactLoader
from app.storage import Storage


def line_png():
    image = np.full((200, 200), 255, np.uint8)
    cv2.line(image, (20, 100), (180, 100), 0, 5, cv2.LINE_AA)
    okay, raw = cv2.imencode('.png', image)
    assert okay
    return raw.tobytes()


def goal_for(asset, profile):
    return dict(schema_version=2, request_id=str(uuid4()), source_mode='SIMULATION',
                asset_id=asset['id'], asset_sha256=asset['sha256'], width_mm=24.0, height_mm=24.0,
                offset_u_mm=0.0, offset_v_mm=105.0, rotation_deg=0.0,
                conversion_preset='raster_centerline_bezier', tool_id='engraving_drill',
                profile_snapshot_id=profile['id'], profile_sha256=profile['sha256'])


@pytest.fixture
def bundle(tmp_path):
    store = Storage(tmp_path / 'managed')
    asset = store.put_asset(line_png(), 'image', 'image/png', 'line.png')
    profile = store.profile(matching_test_profile())
    goal = goal_for(asset, profile)
    generated = GeneratePipeline(ManagedArtifactStore(store.root)).run(goal)
    result = {**asdict(generated), 'success': True, 'validation_passed': True, 'error_code': 'NONE', 'message': '시험'}
    result.pop('path_asset_id')  # 실제 GeneratePath Result에는 없는 필드.
    return store, goal, result


def rewrite_json(store, aid, modify):
    """해시만으로 잡히지 않는 의미상 불일치도 거절하는지 검사한다."""
    value = json.loads(store.read_asset(aid))
    modify(value)
    raw = json.dumps(value, ensure_ascii=False).encode()
    rec = store.asset(aid)
    (store.files / rec['storage_key']).write_bytes(raw)
    with store.db() as db:
        db.execute('UPDATE assets SET sha256=?,size_bytes=? WHERE id=?',
                   (hashlib.sha256(raw).hexdigest(), len(raw), aid))


def test_pipeline_result_loads_without_changing_canonical_files(bundle):
    store, goal, result = bundle
    before = store.read_asset(result['preview_asset_id'])
    metadata = asyncio.run(PathArtifactLoader(store)(goal, result))
    assert metadata['path_asset_id'] != result['path_id']
    assert metadata['test_only'] and metadata['real_execution_allowed'] is False
    assert metadata['validation_not_checked'] == ['J6_RANGE']
    assert metadata['profile_snapshot']['payload'] == matching_test_profile()
    assert store.read_asset(result['preview_asset_id']) == before
    assert json.loads(before)['contract'] == 'c2-path-preview/1'
    with store.db() as db:
        assert db.execute('SELECT count(*) FROM path_versions').fetchone()[0] == 0


@pytest.mark.parametrize('field', ['svg_asset_id', 'preview_asset_id', 'validation_report_id'])
def test_changed_file_bytes_are_rejected(bundle, field):
    store, goal, result = bundle
    rec = store.asset(result[field])
    target = store.files / rec['storage_key']
    target.write_bytes(target.read_bytes() + b'tamper')
    with pytest.raises(ArtifactLoadError, match='검증 실패') as error:
        PathArtifactLoader(store).load(goal, result)
    assert error.value.code == 'HASH_MISMATCH'


@pytest.mark.parametrize('modify', [
    lambda p: p.update(path_id=str(uuid4())),
    lambda p: p.update(profile_sha256='0' * 64),
    lambda p: p['segments'][0]['points_m'][0].__setitem__(0, 100.0),
    lambda p: p['segments'][1]['points_uv_mm'][0].__setitem__(0, 100.0),
    lambda p: p['segments'][0].update(connect_to_next=True),
    lambda p: p['segments'].pop(),
])
def test_wrong_preview_is_rejected_even_with_updated_asset_hash(bundle, modify):
    store, goal, result = bundle
    rewrite_json(store, result['preview_asset_id'], modify)
    with pytest.raises(ArtifactLoadError):
        PathArtifactLoader(store).load(goal, result)


def test_other_requests_report_is_rejected(bundle):
    store, goal, result = bundle
    rewrite_json(store, result['validation_report_id'], lambda r: r.update(request_id=str(uuid4())))
    with pytest.raises(ArtifactLoadError, match='request_id'):
        PathArtifactLoader(store).load(goal, result)


def test_path_hash_from_ros_result_is_required(bundle):
    store, goal, result = bundle
    with pytest.raises(ArtifactLoadError) as error:
        PathArtifactLoader(store).load(goal, {**result, 'path_sha256': '0' * 64})
    assert error.value.code == 'HASH_MISMATCH'


def test_ambiguous_logical_path_is_rejected(bundle):
    store, goal, result = bundle
    meta = PathArtifactLoader(store).load(goal, result)
    store.put_asset(store.read_asset(meta['path_asset_id']), 'path', 'application/json', 'duplicate.json',
                    {'path_id': result['path_id'], 'path_version': result['path_version']})
    with pytest.raises(ArtifactLoadError, match='유일하게'):
        PathArtifactLoader(store).load(goal, result)


def test_path_traversal_is_rejected(bundle):
    store, goal, result = bundle
    with store.db() as db:
        db.execute('UPDATE assets SET storage_key=? WHERE id=?', ('../outside.json', result['preview_asset_id']))
    with pytest.raises(ArtifactLoadError, match='저장 경로'):
        PathArtifactLoader(store).load(goal, result)


def test_failure_result_is_never_loaded(bundle):
    store, goal, result = bundle
    with pytest.raises(ArtifactLoadError):
        PathArtifactLoader(store).load(goal, {**result, 'success': False})
