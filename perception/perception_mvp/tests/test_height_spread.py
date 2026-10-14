"""Surface consistency limits, independent from the reference layer height."""
import numpy as np
import pytest

from perception_mvp.depth_grid import height_spread_within


@pytest.mark.parametrize('difference,allowed', [(2., True), (5., True), (5.1, False), (20., False)])
def test_trial_five_mm_spread_boundary(difference, allowed):
    heights = np.r_[np.full(50, 60.), np.full(50, 60. + difference)]
    assert height_spread_within(heights, 5.) is allowed
    assert height_spread_within(heights / 1000., .005) is allowed


def test_quantiles_ignore_fewer_than_five_percent_outliers():
    assert height_spread_within(np.r_[np.full(98, 60.), -100., 200.], 5.)
    # This is a quality gate only: a uniform, wrong height still passes spread.
    assert height_spread_within(np.full(100, 1000.), 5.)


@pytest.mark.parametrize('values,limit', [([], 5.), ([np.nan], 5.), ([1.], 0.)])
def test_missing_invalid_height_is_not_success(values, limit):
    with pytest.raises(ValueError):
        height_spread_within(values, limit)
