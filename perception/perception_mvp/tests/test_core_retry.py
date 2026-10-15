"""Mask-core retry for the top surface (obliquely seen / stacked blocks); synthetic data only."""
import numpy as np
import pytest

from perception_mvp.opencv_live import (TOP_CORE_EROSION_PX, TOP_CORE_MIN_POINTS, core_min_points_for,
                                        top_surface_points_core_retry)

NOT_PARALLEL = 'top_surface_not_board_parallel'


def square(size):
    mask = np.zeros((60, 60), bool)
    mask[4:4 + size, 4:4 + size] = True
    v, u = np.nonzero(mask)
    board = np.column_stack((u.astype(float), v.astype(float), np.full(len(u), 25.)))
    return mask, v, u, board


def fake_selector(first_error=NOT_PARALLEL, retry_ok=True):
    calls = []

    def selector(board, *, minimum_points=50, diagnostics=None, pixels=None):
        calls.append(len(board))
        if len(calls) == 1:
            raise ValueError(first_error)
        if retry_ok:
            return np.ones(len(board), bool)
        raise ValueError(NOT_PARALLEL)
    return selector, calls


def test_minimum_points_scale_down_only_for_blocks_smaller_than_2x2():
    assert TOP_CORE_MIN_POINTS == 150
    assert core_min_points_for('yellow_2x2') == 150
    assert core_min_points_for('blue_2x3') == 150
    assert core_min_points_for('red_2x1') == 75
    assert core_min_points_for(None) == 150
    assert core_min_points_for('not_a_size') == 150


def test_first_selection_that_works_is_returned_unchanged_without_retry():
    mask, v, u, board = square(40)
    # The real selector succeeds on a flat square at the first attempt: radius 0, all points kept.
    keep, radius = top_surface_points_core_retry(board, v, u, mask)
    assert radius == 0 and keep.all() and len(keep) == len(board)


def test_retry_runs_on_the_shrunken_mask_and_maps_back_to_all_points():
    mask, v, u, board = square(40)
    selector, calls = fake_selector()
    diagnostics = {}
    keep, radius = top_surface_points_core_retry(board, v, u, mask, selector=selector,
                                                 diagnostics=diagnostics, part_class='yellow_2x2')
    assert radius == TOP_CORE_EROSION_PX[0]
    assert keep.shape == (len(board),) and keep.dtype == bool
    inner = (v >= 4 + radius) & (v < 4 + 40 - radius) & (u >= 4 + radius) & (u < 4 + 40 - radius)
    assert np.array_equal(keep, inner)  # only core points; rim points stay out
    assert calls == [len(board), int(inner.sum())]
    assert diagnostics['selection_basis'] == 'mask_core_retry' and diagnostics['core_erosion_px'] == radius
    assert diagnostics['core_retry_attempts'][-1]['result'] == 'accepted'


def test_small_blocks_accept_a_smaller_core_than_2x2_blocks():
    mask, v, u, board = square(16)  # core: 100 points at 3px, 36 at 5px, 4 at 7px
    selector, _ = fake_selector()
    keep, radius = top_surface_points_core_retry(board, v, u, mask, selector=selector, part_class='red_2x1')
    assert radius == 3 and keep.sum() == 100
    selector, _ = fake_selector()
    diagnostics = {}
    with pytest.raises(ValueError, match=NOT_PARALLEL):
        top_surface_points_core_retry(board, v, u, mask, selector=selector, diagnostics=diagnostics,
                                      part_class='yellow_2x2')
    assert [row['result'] for row in diagnostics['core_retry_attempts']] == ['core_too_small'] * len(TOP_CORE_EROSION_PX)


def test_other_failures_are_not_retried():
    mask, v, u, board = square(40)
    selector, calls = fake_selector(first_error='top_surface_depth_insufficient')
    with pytest.raises(ValueError, match='top_surface_depth_insufficient'):
        top_surface_points_core_retry(board, v, u, mask, selector=selector)
    assert len(calls) == 1


def test_every_radius_failing_raises_the_original_error_and_records_each_attempt():
    mask, v, u, board = square(40)
    selector, calls = fake_selector(retry_ok=False)
    diagnostics = {}
    with pytest.raises(ValueError, match=NOT_PARALLEL):
        top_surface_points_core_retry(board, v, u, mask, selector=selector, diagnostics=diagnostics)
    attempts = diagnostics['core_retry_attempts']
    assert [row['radius_px'] for row in attempts] == list(TOP_CORE_EROSION_PX)
    assert all(row['result'] == NOT_PARALLEL for row in attempts)


def test_support_below_the_minimum_is_not_accepted():
    mask, v, u, board = square(40)
    calls = []

    def selector(board_points, *, minimum_points=50, diagnostics=None, pixels=None):
        calls.append(len(board_points))
        if len(calls) == 1:
            raise ValueError(NOT_PARALLEL)
        keep = np.zeros(len(board_points), bool)
        keep[:10] = True  # a plane with only 10 points
        return keep

    diagnostics = {}
    with pytest.raises(ValueError, match=NOT_PARALLEL):
        top_surface_points_core_retry(board, v, u, mask, selector=selector, diagnostics=diagnostics)
    assert all(row['result'] == 'support_below_minimum' for row in diagnostics['core_retry_attempts'])
