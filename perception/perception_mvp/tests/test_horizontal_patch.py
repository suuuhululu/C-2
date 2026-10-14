"""Third top-surface pass: locally horizontal points first (oblique-view masks). Synthetic inputs."""
import numpy as np
import pytest

from perception_mvp.opencv_live import _horizontal_patch_points, top_surface_points

SIZE, PITCH_MM = 30, .7


def cloud(z_of_row):
    v, u = np.mgrid[0:SIZE, 0:SIZE]
    v, u = v.ravel(), u.ravel()
    board = np.column_stack((u * PITCH_MM, v * PITCH_MM, [z_of_row(r) for r in v]))
    return board, (v, u, (SIZE, SIZE))


def top_with_wall(row):
    # 20% flat top (rows 0-5), then a steep side wall (slope above 1) down to the board.
    return 18. if row < 6 else 18. - (row - 5) * .72


def test_top_face_is_selected_when_a_steep_wall_dominates_the_mask():
    board, pixels = cloud(top_with_wall)
    diagnostics = {}
    keep = top_surface_points(board, pixels=pixels, diagnostics=diagnostics)
    assert diagnostics['selection_basis'] == 'horizontal_patch'
    assert keep.sum() >= 50
    assert np.all(board[keep, 2] > 17.)  # Only the top face, never the wall.
    assert np.median(board[keep, 2]) == pytest.approx(18.)


def test_without_pixels_the_same_cloud_is_still_rejected():
    board, _ = cloud(top_with_wall)
    with pytest.raises(ValueError):
        top_surface_points(board)


def lower_block_beside(top_rows):
    def rows(row):
        if row < top_rows:
            return 18.
        if row < 18:
            return 18. - (row - top_rows + 1) * 1.5
        return 0.
    return rows


def test_highest_flat_level_wins_over_a_larger_lower_flat_level():
    board, pixels = cloud(lower_block_beside(10))  # Large top, wall, then a lower flat top.
    keep = _horizontal_patch_points(board, pixels)
    assert np.median(board[keep, 2]) == pytest.approx(18.)


def test_small_top_face_is_rejected_instead_of_falling_to_the_lower_plane():
    # Too few flat top points to trust, but enough to be a real higher patch: reject, never
    # report the larger lower flat plane (that would be a silently wrong, lower layer).
    board, pixels = cloud(lower_block_beside(6))
    with pytest.raises(ValueError):
        _horizontal_patch_points(board, pixels)


def test_fully_tilted_surface_is_rejected():
    board, pixels = cloud(lambda row: row * PITCH_MM * .8)  # About 39 degrees everywhere.
    with pytest.raises(ValueError):
        _horizontal_patch_points(board, pixels)


def test_pixel_arrays_must_match_points():
    board, (v, u, shape) = cloud(lambda row: 18.)
    with pytest.raises(ValueError, match='top_surface_depth_insufficient'):
        _horizontal_patch_points(board, (v[:-1], u[:-1], shape))
