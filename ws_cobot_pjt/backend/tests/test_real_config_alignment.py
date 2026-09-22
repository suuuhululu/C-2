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
