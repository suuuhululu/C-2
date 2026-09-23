"""HMI 사전 검사와 실제 공정 소비자의 정적 계약을 함께 검사한다. 로봇 호출 없음."""
from copy import deepcopy
import json
import sys
import pytest
from test_real_preparation_hmi import ROOT, config_file, execution_template
from app.real_execution_config import validate_real_execution_config

sys.path.insert(0, str(ROOT/'ws_cobot1/src/c2_process'))
from c2_process.node import validate_real_execution_profiles, InputsUnavailable


def config(tmp_path):
    value = json.loads(config_file(tmp_path).read_text())
    value['execution_profile'] = execution_template(value)
    return value


def enable_cut_contact(context, mode):
    context['tool_profile'].update(
        contact_mode='force_touch', clearance_m=.006, touch_extra_m=.008,
        touch_offset_range_m=[-.003, .003], touch_force_n=.8,
        touch_speed_mm_s=1.5, tool_axis='-y', cut_contact=mode,
        force_limit_n=6., air_force_limit_n=15.)
    if mode == 'normal_force_hold':
        context['tool_profile'].update(
            cut_force_n=2., cut_stiffness=[3000.] * 3 + [300.] * 3, ramp_s=.5)
    else:
        context['tool_profile'].update(
            cut_force_min_n=1.5, cut_force_max_n=4., adaptive_step_m=.0003,
            adaptive_chunk_points=20)


@pytest.mark.parametrize('depth', [0., .001])
@pytest.mark.parametrize('clearance', [.002, {'stroke': .002}])
def test_same_fixed_depth_settings_pass_both_without_rewriting(tmp_path, depth, clearance):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    context['tool_profile'].update(depth_m=depth, clearance_m=clearance)
    before = deepcopy(value)
    validate_real_execution_config(value)
    validate_real_execution_profiles(context)
    assert value == before


def test_entry_policy_is_required_before_measurement(tmp_path):
    value = config(tmp_path)
    value['execution_profile']['execution_context'].pop('entry_planning')
    with pytest.raises(ValueError, match='entry_planning.enabled'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='entry_planning.enabled'):
        validate_real_execution_profiles(value['execution_profile']['execution_context'])


@pytest.mark.parametrize(('key', 'bad'), [
    ('tcp_clearance_above_top_range_m', [.12, .10]),
    ('sample_m', 0.),
    ('sample_deg', True),
    ('motion_profile_id', 'missing-profile'),
])
def test_invalid_entry_policy_is_rejected_without_rewriting(tmp_path, key, bad):
    value = config(tmp_path)
    value['execution_profile']['execution_context']['entry_planning'][key] = bad
    before = deepcopy(value)
    with pytest.raises(ValueError, match='entry_planning'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='entry_planning'):
        validate_real_execution_profiles(value['execution_profile']['execution_context'])
    assert value == before


@pytest.mark.parametrize('name', ['candle_approach', 'candle_cut', 'candle_travel', 'candle_retract'])
@pytest.mark.parametrize('bad', [None, 0, -1, True, float('nan')])
def test_position_tolerance_rejected_before_measure_by_both(tmp_path, name, bad):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    context['motion_profiles'][name]['pos_tol_mm'] = bad
    with pytest.raises(ValueError, match='pos_tol_mm'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='pos_tol_mm'):
        validate_real_execution_profiles(context)


@pytest.mark.parametrize('bad', [-.001, None, True, float('inf')])
def test_invalid_depth_rejected_by_both(tmp_path, bad):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    context['tool_profile']['depth_m'] = bad
    with pytest.raises(ValueError, match='depth_m'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='depth_m'):
        validate_real_execution_profiles(context)


def test_additional_profile_is_also_validated(tmp_path):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    context['motion_profiles']['additional'] = {}
    with pytest.raises(ValueError, match='additional'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='additional'):
        validate_real_execution_profiles(context)


@pytest.mark.parametrize('mode', ['normal_force_hold', 'chunk_adaptive'])
def test_cut_contact_settings_pass_both_validators_without_rewriting(tmp_path, mode):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    enable_cut_contact(context, mode)
    before = deepcopy(value)
    validate_real_execution_config(value)
    validate_real_execution_profiles(context)
    assert value == before


@pytest.mark.parametrize(('mode', 'key', 'bad'), [
    ('normal_force_hold', 'cut_stiffness', [3000.] * 5),
    ('normal_force_hold', 'ramp_s', 1.1),
    ('chunk_adaptive', 'cut_force_min_n', 5.),
    ('chunk_adaptive', 'adaptive_step_m', 0.),
    ('chunk_adaptive', 'adaptive_chunk_points', 81),
])
def test_invalid_cut_contact_settings_rejected_by_both(tmp_path, mode, key, bad):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    enable_cut_contact(context, mode)
    context['tool_profile'][key] = bad
    with pytest.raises(ValueError, match=key):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match=key):
        validate_real_execution_profiles(context)


def test_fixed_depth_rejects_cut_contact_by_both(tmp_path):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    context['tool_profile']['cut_contact'] = 'normal_force_hold'
    with pytest.raises(ValueError, match='force_touch'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='force_touch'):
        validate_real_execution_profiles(context)


def test_cut_contact_requires_explicit_tool_axis_by_both(tmp_path):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    enable_cut_contact(context, 'normal_force_hold')
    context['tool_profile'].pop('tool_axis')
    with pytest.raises(ValueError, match='tool_axis'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='tool_axis'):
        validate_real_execution_profiles(context)


@pytest.mark.parametrize(('key', 'bad'), [
    ('workcell_version', 2), ('workcell_id', 'other-cell'),
    ('tools_config_version', 99), ('tool_version', 99),
    ('tcp_version', 99), ('load_version', 99),
    ('contract', 'c2-path-test-profile/2'),
])
def test_path_identity_mismatch_rejected_by_hmi(tmp_path, key, bad):
    value = config(tmp_path)
    value['execution_profile'][key] = bad
    with pytest.raises(ValueError, match=key):
        validate_real_execution_config(value)


def test_deployed_profile_measurement_assembly_passes_path_consumer(tmp_path):
    from app.ros_preparation import real_bound_profile, display_result
    from app.monitor_contract import uid
    from c2_path.pipeline import validate_profile
    directory = ROOT/'ws_cobot1/src/c2_process'
    value = json.loads((directory/'config/workpiece_real_trial_0921.json').read_text())
    value['execution_profile'] = json.loads((directory/'config/real_execution_profile_20260923.json').read_text())
    validate_real_execution_config(value)
    goal = dict(request_id=uid(), preparation_id=uid(), measurement_id=uid(), source_mode='REAL',
                height_m=.15, input_profile_snapshot_id=uid(), input_profile_sha256='a'*64)
    raw = json.loads((directory/'test/fixtures/prepare_workpiece_action_samples/success.json').read_text())['result']
    raw.update(source_mode='REAL', validity='FORCE_CONTACT_ESTIMATE',
               preparation_id=goal['preparation_id'], measurement_id=goal['measurement_id'])
    profile = real_bound_profile(goal, display_result(raw, goal), value, dict(id=uid(), sha256='b'*64))
    validate_profile(profile)
    assert profile['surface']['radius_mm'] == raw['radius_m'] * 1000
    assert profile['workcell_version'] == 1


@pytest.mark.parametrize('bad', [
    {'frame_id': 'other', 'waypoint_min_z_m': .05},
    {'frame_id': 'c2_base', 'waypoint_min_z_m': .049},
    {'frame_id': 'c2_base', 'waypoint_min_z_m': float('nan')},
])
def test_engraving_workspace_rejected_by_both_consumers(tmp_path, bad):
    value = config(tmp_path)
    context = value['execution_profile']['execution_context']
    context['engraving_workspace'] = bad
    with pytest.raises(ValueError, match='engraving_workspace'):
        validate_real_execution_config(value)
    with pytest.raises(InputsUnavailable, match='engraving_workspace'):
        validate_real_execution_profiles(context)
