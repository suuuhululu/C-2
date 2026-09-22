"""실제 HMI 조립 → 공정 매퍼의 장착 오프셋 연결. 입력은 합성 시험값, 모션 없음."""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'ws_cobot1/src/c2_path'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ros_preparation import real_bound_profile, display_result
from c2_path.pipeline import matching_test_profile_v4
from c2_process.node import resolve_real_execution_settings
from c2_process.robot_adapter import MockRobotAdapter


def inputs():
    package = Path(__file__).resolve().parents[1]
    config = json.loads((package / 'config/workpiece_real_trial_0921.json').read_text())
    template = matching_test_profile_v4()
    template['tip_calibration']['offset_tool_m'] = copy.deepcopy(config['workcell']['tool_offset_m'])
    template['execution_context']['stop_profile']['confirmation_timeout_s'] = 2.
    for name, motion in template['execution_context']['motion_profiles'].items():
        motion.update(id=name, vel_mm_s=5., acc_mm_s2=10., pos_tol_mm=1.,
                      completion_timeout_s=30.)
    template['execution_context']['tool_profile'].update(
        contact_mode='fixed_depth', depth_m=.0003, clearance_m=.002)
    config['execution_profile'] = template
    fixture = json.loads((package / 'test/fixtures/prepare_workpiece_action_samples/success.json').read_text())
    goal = dict(fixture['goal'], source_mode='REAL', height_m=.15)
    # REAL 분기의 수치/계약 시험용 합성 입력. 실제 측정/실기 통과 근거가 아니다.
    raw = dict(fixture['result'], source_mode='REAL', validity='ESTIMATED', absolute_top_verified=False)
    display = display_result(raw, goal)
    record = {'id': 'measurement-record', 'sha256': 'b' * 64}
    return config, goal, display, record


def test_measurement_offset_reaches_execution_unchanged():
    config, goal, display, record = inputs()
    profile = real_bound_profile(goal, display, config, record)
    adapter = MockRobotAdapter()
    settings = resolve_real_execution_settings(profile, {'run_id': 'run', 'source_mode': 'REAL'},
                                                'registered-profile', adapter=adapter)
    assert settings['tool_offset_m'] == config['workcell']['tool_offset_m']
    assert settings['tool_offset_m'] == profile['tip_calibration']['offset_tool_m']
    assert settings['tool_offset_m'] != profile['contact_calibration']['contact_offset_tool_m']
    assert profile['absolute_top_verified'] is False and profile['validity'] == 'ESTIMATED'
    assert not adapter.calls


@pytest.mark.parametrize('mismatch', [[0., -.09, 0.], [0., 0., .02], None])
def test_hmi_rejects_mismatched_or_missing_drill_offset_before_execution(mismatch):
    config, goal, display, record = inputs()
    config['execution_profile']['tip_calibration']['offset_tool_m'] = mismatch
    with pytest.raises(ValueError, match='측정/가공 도구 끝 오프셋 불일치'):
        real_bound_profile(goal, display, config, record)
