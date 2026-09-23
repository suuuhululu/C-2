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
