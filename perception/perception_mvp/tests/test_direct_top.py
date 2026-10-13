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
