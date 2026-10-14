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


BOUNDS = [24.3, 43.2, 61.8, 80.4, 99.]


def test_contiguous_bands_follow_the_owner_ranges():
    expected = {6.: 0, 24.3: 0, 24.31: 1, 43.2: 1, 43.21: 2, 61.8: 2, 61.81: 3, 80.4: 3, 80.41: 4, 99.: 4}
    for height, index in expected.items():
        assert layer_index(height, LEVELS, 5., 6., upper_bounds=BOUNDS) == index, height
    for height in (5.9, 99.01, 120.):
        assert layer_index(height, LEVELS, 5., 6., upper_bounds=BOUNDS) is None, height


def test_measured_samples_and_stud_tops_land_in_their_own_layer():
    # 18.6mm blocks, one top stud of 4mm: stud tops 22.6 / 41.2 / 59.8 / 78.4 / 97.0mm.
    for index, top in enumerate((22.6, 41.2, 59.8, 78.4, 97.)):
        assert layer_index(top, LEVELS, 5., 6., upper_bounds=BOUNDS) == index
    assert layer_index(20.5, LEVELS, 5., 6., upper_bounds=BOUNDS) == 0   # measured layer 1 (yellow)
    assert layer_index(40.2, LEVELS, 5., 6., upper_bounds=BOUNDS) == 1   # measured layer 2 (blue)


def test_bounds_ignore_the_symmetric_tolerance_and_first_layer_max():
    assert layer_index(30., LEVELS, 5., 6., 25., upper_bounds=BOUNDS) == 1
    assert layer_index(30., LEVELS, 5., 6., 25.) is None


def test_invalid_bounds_are_refused():
    for bad in ([24.3, 43.2, 61.8, 80.4], [24.3, 43.2, 43.2, 80.4, 99.], [24.3, 43.2, 61.8, 80.4, np.nan],
                [21., 43.2, 61.8, 80.4, 99.], [24.3, 43.2, 61.8, 80.4, 99., 110.],
                [41., 43.2, 61.8, 80.4, 99.]):  # shape, order, NaN, below own level, count, touching next level
        with pytest.raises(ValueError, match='invalid_layer_upper_bounds'):
            layer_index(30., LEVELS, 5., 6., upper_bounds=bad)
    with pytest.raises(ValueError, match='invalid_first_layer_min'):
        layer_index(30., LEVELS, 5., 25., upper_bounds=BOUNDS)


def test_config_and_live_reference_carry_the_same_ranges():
    root = Path(__file__).resolve().parents[1]
    geometry = yaml.safe_load((root / 'config.yaml').read_text())['geometry']
    assert geometry['first_layer_min_height_m'] == 0.006
    assert geometry['layer_upper_bounds_m'] == [0.0243, 0.0432, 0.0618, 0.0804, 0.099]
    assert geometry.get('first_layer_max_height_m') is None
    reference = load_layer_reference()
    assert reference['first_layer_min_mm'] == pytest.approx(6.)
    assert reference['first_layer_max_mm'] is None
    np.testing.assert_allclose(reference['layer_upper_bounds_mm'], BOUNDS)
