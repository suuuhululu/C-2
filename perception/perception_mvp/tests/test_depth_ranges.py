"""Optical-Z geometry bounds and per-View selection, not sensor validation."""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from perception_mvp.depth_grid import depth_ranges_from_board, config_for_view


def test_flat_board_and_top_bound_include_explicit_margin():
    transform = np.diag([1., -1., -1., 1.])
    transform[2, 3] = .504
    calibration = dict(height_reference='BOARD_FLAT_SURFACE_ZERO', views={'V0': transform.tolist()})
    result = depth_ranges_from_board(calibration, [[-.008, .376], [-.008, .376]], .099, margin_m=.005)
    assert result['V0']['min_depth_m'] == pytest.approx(.400)
    assert result['V0']['max_depth_m'] == pytest.approx(.509)


def test_current_three_view_settings_enclose_calculated_bounds():
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / 'perception_mvp/config.yaml').read_text())['geometry']
    calibration = json.loads((root / 'calibration/assembly_runtime_pitch16_flat0_20261013.json').read_text())
    computed = depth_ranges_from_board(calibration, config['board_bounds_m'],
        config['top_heights_m'][-1] + config['height_tolerance_m'], margin_m=config['depth_range_margin_m'])
    assert set(computed) == {'V0', 'D1', 'D3'}
    for view, limits in computed.items():
        adopted = config_for_view(config, view)
        assert 0 <= limits['min_depth_m'] - adopted['min_depth_m'] < .001
        assert 0 <= adopted['max_depth_m'] - limits['max_depth_m'] < .001
        assert adopted['min_depth_m'] < adopted['max_depth_m']


def test_missing_view_never_uses_broad_global_fallback():
    config = dict(min_depth_m=.1, max_depth_m=2., depth_ranges_m={'V0': dict(min_depth_m=.4, max_depth_m=.6)})
    assert config_for_view(config, 'V0')['min_depth_m'] == .4
    assert config['min_depth_m'] == .1
    with pytest.raises(ValueError, match='missing for View'):
        config_for_view(config, 'D1')


def test_legacy_explicit_global_limits_remain_supported():
    config = dict(min_depth_m=.1, max_depth_m=2.)
    assert config_for_view(config, 'V0') is config
