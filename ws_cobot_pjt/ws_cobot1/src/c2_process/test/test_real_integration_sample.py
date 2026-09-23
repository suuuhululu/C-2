"""첫 REAL 통합 기록의 오프라인 회귀 검사. ROS 초기화·서비스·모션 호출 없음."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent/'c2_path')]
from c2_path.pipeline import validate_profile
from c2_process.engraving_workspace import check_path_workspace
from c2_process.entry_planner import generate_entry_candidates, _geometry_check
from c2_process.robot_adapter import apply_tool_offset

SAMPLE = ROOT.parents[2]/'docs/evidence/real_integration_20260923'


def read(name):
    return json.loads((SAMPLE/name).read_text())


def test_record_hashes_and_success_scope():
    for name, sha in read('manifest.json')['files'].items():
        assert hashlib.sha256((SAMPLE/name).read_bytes()).hexdigest() == sha
    result = read('execution-result.json')
    assert result['outcome'] == 'SUCCEEDED'
    assert result['observed_state']['engraving_quality_verified'] is False
    assert result['observed_state']['contact_verified'] is False
    assert result['observed_state']['last_completed_segment_id'] == 'seg-0055'


def test_measured_geometry_and_bound_path_identity():
    profile, path = read('profile.json'), read('path.json')
    measure = read('measurement.json')['result']
    validate_profile(profile)
    assert measure['contact_indices'] == list(range(9))
    assert measure['outcome'] == 'SUCCEEDED' and measure['stop_confirmed']
    assert profile['measurement_id'] == measure['measurement_id']
    assert abs(profile['surface']['radius_mm']/1000-measure['radius_m']) < 1e-12
    assert path['config']['profile_sha256'] == read('run.json')['profile_sha256']
    assert len(path['segments']) == 55
    assert check_path_workspace(path, profile['workcell'].get('engraving_workspace')).ok


def test_saved_entry_geometry_without_robot_or_ik():
    profile, path = read('profile.json'), read('path.json')
    w = profile['workcell']; offset = profile['tip_calibration']['offset_tool_m']
    # 장치 현재값 대신 저장된 HOME으로 계산만 수행한다.
    home = apply_tool_offset(w['home']['tcp_pose'], offset, +1)
    candidates = generate_entry_candidates(path, w, home, offset,
                                           profile['execution_context']['motion_profiles'])
    selected = read('execution-result.json')['observed_state']['entry']['candidate_id']
    candidate = next(c for c in candidates if c['candidate_id'] == selected)
    assert _geometry_check(candidate, w, offset).ok
