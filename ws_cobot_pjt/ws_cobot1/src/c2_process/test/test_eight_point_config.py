"""8점 원본과 배포 설정의 연결·계획 기하 검사. ROS/로봇 호출 없음."""
import hashlib
import json
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[2]
sys.path[:0] = [str(ROOT), str(ROOT.parent/'c2_path'), str(PROJECT/'backend')]
from c2_process.robot_adapter import apply_tool_offset, pose_to_posx
from c2_process.workpiece_calibration import (
    MeasurementContext, _validate, fit_circle, build_top_plan, build_side_plan, build_home_plan)
from c2_process.workpiece_real_trial import check_trial_scene
from c2_process.measurement_robot_adapter import continuous_target
from c2_process.node import validate_real_execution_profiles
from app.real_execution_config import validate_real_execution_config


def inputs():
    config = json.loads((ROOT/'config/workpiece_real_trial_0921.json').read_text())
    profile = json.loads((ROOT/'config/real_execution_profile_20260923.json').read_text())
    evidence = PROJECT/'docs/evidence/workpiece_20260923_1502/prepare_workpiece_result_20260923_1502.json'
    raw = evidence.read_bytes()
    return config, profile, json.loads(raw), raw


def test_eight_point_source_and_geometry_are_preserved():
    config, profile, result, raw = inputs()
    obs = result['observed_state']; m = obs['measurement']
    assert result['outcome'] == 'SUCCEEDED' and result['error_code'] == 'NONE'
    assert obs['stop_confirmed'] and obs['home_return_confirmed'] and obs['partial'] is False
    assert {p['point_index'] for p in m['points']} == set(range(1, 9))
    fit = fit_circle([p['tip_pose'][:3] for p in m['points']])
    assert fit['axis_xy_m'] == pytest.approx(m['axis_xy_m'], abs=1e-10)
    assert fit['radius_m'] == pytest.approx(m['radius_m'], abs=1e-10)
    assert config['workcell']['seed_axis_xy_m'] == m['axis_xy_m']
    assert config['workcell']['seed_radius_m'] == m['radius_m']
    assert profile['surface']['axis_origin_m'] == [*m['axis_xy_m'], m['bottom_z_m']]
    assert profile['surface']['radius_mm'] == m['radius_m'] * 1000
    assert profile['provenance']['measurement_record_sha256'] == hashlib.sha256(raw).hexdigest()
    assert profile['provenance']['independent_accuracy_verified'] is False


def test_updated_config_passes_consumers_and_whole_measurement_scene():
    config, profile, result, _ = inputs()
    config['execution_profile'] = profile
    validate_real_execution_config(config)
    validate_real_execution_profiles(profile['execution_context'])
    w = config['workcell']; m = result['observed_state']['measurement']
    _validate(w, config['profiles'], MeasurementContext('config-test', 'config-preparation', 'REAL', profile_snapshot_id='config', profile_sha256='a'*64))
    tip = apply_tool_offset(w['home']['tcp_pose'], w['tool_offset_m'])
    native = pose_to_posx(tip, w['tool_offset_m'])
    top = build_top_plan(w, tip)
    side = build_side_plan(w, m['top_z_m'])
    home = build_home_plan(w, side[-1]['target_pose'])
    # 실기 추종 오차·IK를 포함하지 않고 명령 끝점을 다음 구간에 전달한다.
    for steps in (top, side, home):
        assert check_trial_scene(steps, w, {'posx': native})['path_checked']
        for step in steps:
            native = continuous_target(step['target_pose'], w['tool_offset_m'], native)
    assert native[:3] == pytest.approx([v*1000 for v in w['home']['tcp_pose'][:3]])
