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


BOUNDS = [26., 43.2, 64., 83., 103.]


def test_contiguous_bands_follow_the_owner_ranges():
    expected = {6.: 0, 24.3: 0, 26.: 0, 26.01: 1, 43.2: 1, 43.21: 2, 64.: 2, 64.01: 3, 83.: 3, 83.01: 4, 103.: 4}
    for height, index in expected.items():
        assert layer_index(height, LEVELS, 5., 6., upper_bounds=BOUNDS) == index, height
    for height in (5.9, 103.01, 120.):
        assert layer_index(height, LEVELS, 5., 6., upper_bounds=BOUNDS) is None, height


def test_measured_samples_and_stud_tops_land_in_their_own_layer():
    # 18.6mm blocks, one top stud of 4mm: stud tops 22.6 / 41.2 / 59.8 / 78.4 / 97.0mm.
    for index, top in enumerate((22.6, 41.2, 59.8, 78.4, 97.)):
        assert layer_index(top, LEVELS, 5., 6., upper_bounds=BOUNDS) == index
    assert layer_index(20.5, LEVELS, 5., 6., upper_bounds=BOUNDS) == 0   # measured layer 1 (yellow)
    assert layer_index(40.2, LEVELS, 5., 6., upper_bounds=BOUNDS) == 1   # measured layer 2 (blue)
    # 2026-10-14 stack captures (stud-midpoint heights): 3rd layer 61.2..62.9, 4th layer 79.5..82.6.
    for height, index in ((21.6, 0), (24.3, 0), (25.6, 0), (36.9, 1), (61.2, 2), (62.4, 2), (62.9, 2), (63.4, 2), (64., 2), (64.1, 3), (79.5, 3), (80.6, 3), (82.6, 3)):
        assert layer_index(height, LEVELS, 5., 6., upper_bounds=BOUNDS) == index, height


def test_bounds_ignore_the_symmetric_tolerance_and_first_layer_max():
    assert layer_index(30., LEVELS, 5., 6., 25., upper_bounds=BOUNDS) == 1
    assert layer_index(30., LEVELS, 5., 6., 25.) is None


def test_invalid_bounds_are_refused():
    for bad in ([26., 43.2, 64., 83.], [26., 43.2, 43.2, 83., 103.], [26., 43.2, 64., 83., np.nan],
                [21., 43.2, 64., 83., 103.], [26., 43.2, 64., 83., 103., 115.],
                [41., 43.2, 64., 83., 103.]):  # shape, order, NaN, below own level, count, touching next level
        with pytest.raises(ValueError, match='invalid_layer_upper_bounds'):
            layer_index(30., LEVELS, 5., 6., upper_bounds=bad)
    with pytest.raises(ValueError, match='invalid_first_layer_min'):
        layer_index(30., LEVELS, 5., 27., upper_bounds=BOUNDS)


def test_config_and_live_reference_carry_the_same_ranges():
    root = Path(__file__).resolve().parents[1]
    geometry = yaml.safe_load((root / 'config.yaml').read_text())['geometry']
    assert geometry['first_layer_min_height_m'] == 0.006
    assert geometry['layer_upper_bounds_m'] == [0.026, 0.0432, 0.064, 0.083, 0.103]
    assert geometry.get('first_layer_max_height_m') is None
    reference = load_layer_reference()
    assert reference['first_layer_min_mm'] == pytest.approx(6.)
    assert reference['first_layer_max_mm'] is None
    np.testing.assert_allclose(reference['layer_upper_bounds_mm'], BOUNDS)
