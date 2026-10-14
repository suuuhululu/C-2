"""Layer 1 lower bound (owner decision 2026-10-14). Synthetic heights, no camera, no Depth."""
from pathlib import Path

import numpy as np
import pytest
import yaml

from perception_mvp.depth_grid import layer_band_index as layer_index, validate_first_layer_range
from perception_mvp.live_view import load_layer_reference

LEVELS = [22., 40.625, 59.25, 77.875, 96.5]


def test_layer_one_is_the_configured_range():
    for height in (6., 15.9, 22.6, 25.):
        assert layer_index(height, LEVELS, 5., 6., 25.) == 0
    for height in (5.9, 25.1, 30.):
        assert layer_index(height, LEVELS, 5., 6., 25.) is None


def test_without_a_range_layer_one_keeps_the_symmetric_band():
    assert layer_index(16.9, LEVELS, 5.) is None
    assert layer_index(17., LEVELS, 5.) == 0
    assert layer_index(27., LEVELS, 5.) == 0 and layer_index(27.1, LEVELS, 5.) is None


def test_a_minimum_alone_keeps_the_symmetric_upper_bound():
    assert layer_index(6., LEVELS, 5., 6.) == 0 and layer_index(27., LEVELS, 5., 6.) == 0
    assert layer_index(27.1, LEVELS, 5., 6.) is None


def test_other_layers_keep_the_symmetric_band_even_with_a_range():
    assert layer_index(35.625, LEVELS, 5., 6., 25.) == 1
    assert layer_index(35.5, LEVELS, 5., 6., 25.) is None
    assert layer_index(101.5, LEVELS, 5., 6., 25.) == 4
    assert layer_index(101.6, LEVELS, 5., 6., 25.) is None


def test_invalid_range_is_refused_not_ignored():
    for bad in (-1., np.nan, np.inf, 22., 30.):
        with pytest.raises(ValueError, match='invalid_first_layer_min'):
            validate_first_layer_range(bad, None, LEVELS, 5.)
    for bad in (21., np.nan, 35.625, 40.):  # Below layer 1, or touching layer 2's band.
        with pytest.raises(ValueError, match='invalid_first_layer_max'):
            validate_first_layer_range(6., bad, LEVELS, 5.)
    validate_first_layer_range(None, None, LEVELS)


def test_config_and_live_reference_carry_the_same_range():
    root = Path(__file__).resolve().parents[1]
    geometry = yaml.safe_load((root / 'config.yaml').read_text())['geometry']
    assert geometry['first_layer_min_height_m'] == 0.006
    assert geometry['first_layer_max_height_m'] == 0.025
    reference = load_layer_reference()
    assert reference['first_layer_min_mm'] == pytest.approx(6.)
    assert reference['first_layer_max_mm'] == pytest.approx(25.)
