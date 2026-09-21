"""실물 ROS 수치형을 측정 반환 경계에서 정규화하고 기존 Action 검사를 통과한다."""
import json
import math

import numpy as np
import pytest

from test_preparation_action import fixture


def typed_contact_adapter(adapter, monkeypatch, bad_force=None):
    execute = adapter.execute_measurement_step
    def run(*args, **kwargs):
        result = execute(*args, **kwargs)
        hit = result.observed_state.get('contact')
        if hit:
            hit['normal_force_n'] = np.float64(hit['normal_force_n']) if bad_force is None else bad_force
            hit['measured_at_monotonic_s'] = np.float64(hit['measured_at_monotonic_s'])
            hit['tip_pose'] = [np.float64(v) for v in hit['tip_pose']]
        return result
    monkeypatch.setattr(adapter, 'execute_measurement_step', run)


def test_numpy_contacts_reach_existing_action_result(tmp_path, monkeypatch):
    handler, goal, _, _, adapter, _ = fixture(tmp_path)
    typed_contact_adapter(adapter, monkeypatch)
    output = handler.execute(goal)
    assert output['outcome'] == 'SUCCEEDED', output
    assert output['contact_indices'] == list(range(9))
    assert output['stop_confirmed'] and not output['partial']
    assert output['radius_m'] > 0 and output['height_m'] > 0
    for name in ('contact_normal_force_n', 'contact_monotonic_s'):
        assert all(type(v) is float and math.isfinite(v) for v in output[name])
    json.dumps(output, allow_nan=False)


@pytest.mark.parametrize('bad_force', [np.float64('nan'), np.float64('inf'), True])
def test_invalid_contact_force_is_still_rejected(tmp_path, monkeypatch, bad_force):
    handler, goal, _, _, adapter, _ = fixture(tmp_path)
    typed_contact_adapter(adapter, monkeypatch, bad_force)
    output = handler.execute(goal)
    assert output['outcome'] != 'SUCCEEDED'
    assert not output['geometry_ready']
