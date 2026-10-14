import numpy as np
import pytest
from perception_mvp.opencv_live import top_surface_points


def test_direct_top_does_not_require_body_or_add_four_mm():
    x, y = np.meshgrid(np.arange(10), np.arange(10))
    top = np.column_stack((x.ravel(), y.ravel(), np.full(100, 22.)))
    selected = top_surface_points(top)
    assert selected.all()
    assert np.median(top[selected, 2]) == 22.
    body = top.copy()
    body[:, 2] = 18.
    cloud = np.vstack((body, top, [[0., 0., 100.]]))
    selected = top_surface_points(cloud)
    assert np.median(cloud[selected, 2]) == 22.
    assert not selected[-1]  # Single high outlier is not a top surface.


def test_diagnostics_do_not_change_selection_or_claim_confirmation():
    x, y = np.meshgrid(np.arange(10), np.arange(10))
    top = np.column_stack((x.ravel(), y.ravel(), np.full(100, 22.)))
    details = {}
    np.testing.assert_array_equal(top_surface_points(top), top_surface_points(top, diagnostics=details))
    assert details['best_parallel_points'] == 100
    assert details['best_parallel_fraction'] == 1.
    assert 'layer' not in details


def test_sloping_top_refines_to_converged_plane_with_same_residual_limit():
    x, y = np.meshgrid(np.linspace(0, 30, 30), np.linspace(0, 30, 30))
    top = np.column_stack((x.ravel(), y.ravel(), 22. + .12*x.ravel()))
    details = {}
    selected = top_surface_points(top, diagnostics=details)
    assert selected.all()
    assert 1 <= details['selected_refinement_iterations'] <= 20
    assert details['best_parallel_slope'] == pytest.approx(.12)


def noisy_top(seed, sigma, slope=0.):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, 32, (3000, 2))
    return np.column_stack((xy, 50. + slope*(xy[:, 0]-16) + rng.normal(0, sigma, 3000)))


def test_noisy_top_without_fixed_point_uses_bounded_fallback_and_says_so():
    # sigma 1.3mm noise: membership never reaches a fixed point, yet one plane carries the points.
    cloud = noisy_top(0, 1.3, .12)
    details = {}
    selected = top_surface_points(cloud, diagnostics=details)
    assert details['selection_basis'] == 'bounded_consensus_no_fixed_point'
    assert selected.mean() >= .25 and details['selected_slope'] <= np.tan(np.deg2rad(10.))
    assert abs(np.median(cloud[selected, 2]) - 50.) < 1.


def test_converged_plane_is_not_replaced_by_fallback():
    x, y = np.meshgrid(np.arange(10), np.arange(10))
    top = np.column_stack((x.ravel(), y.ravel(), np.full(100, 22.)))
    details = {}
    top_surface_points(top, diagnostics=details)
    assert details['selection_basis'] == 'converged_plane'


def test_fallback_still_rejects_spread_cloud_and_steep_plane():
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 32, (3000, 2))
    with pytest.raises(ValueError, match='top_surface'):
        top_surface_points(np.column_stack((xy, rng.uniform(40, 52, 3000))))  # 12mm spread, no plane
    with pytest.raises(ValueError, match='top_surface_not_board_parallel'):
        top_surface_points(np.column_stack((xy, 50. + .36*xy[:, 0])))  # about 20 degrees
