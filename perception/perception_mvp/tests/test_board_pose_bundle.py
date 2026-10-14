"""Datum conversion tests; no depth/robot measurement accuracy claim."""
from copy import deepcopy

import numpy as np
import pytest

from perception_mvp.depth_grid import board_pose_bundle


def poses():
    return {view: dict(view_id=view, independently_validated=True, rows=24, cols=24,
        pitch_mm=16., reference_plane='plane through reference points, normally empty stud tops',
        camera_pose=dict(R_camera_from_board=np.diag([1., -1., -1.]).tolist(),
                         t_camera_from_board_mm=[10., 20., 500.], height_normal_sign=1))
        for view in ('V0', 'D1', 'D3')}


def test_stud_top_maps_to_four_mm_without_changing_xy_or_original():
    sources = poses()
    previous = deepcopy(sources)
    result = board_pose_bundle(sources, 'flat0-fixture', stud_height_mm=4.)
    transform = np.asarray(result['views']['V0'])
    assert transform @ np.array([.010, .020, .500, 1.]) == pytest.approx([0., 0., .004, 1.])
    assert transform @ np.array([.010, .020, .504, 1.]) == pytest.approx([0., 0., 0., 1.])
    assert sources == previous
    assert result['height_reference'] == 'BOARD_FLAT_SURFACE_ZERO'


@pytest.mark.parametrize('field,value', [('pitch_mm', 17.), ('independently_validated', False),
                                      ('reference_plane', 'unknown')])
def test_incompatible_source_is_rejected(field, value):
    sources = poses()
    sources['D1'][field] = value
    with pytest.raises(ValueError):
        board_pose_bundle(sources, 'fixture', stud_height_mm=4.)


def test_missing_view_or_reflected_height_is_rejected():
    sources = poses()
    sources.pop('D3')
    with pytest.raises(ValueError):
        board_pose_bundle(sources, 'fixture', stud_height_mm=4.)
    sources = poses()
    sources['D3']['camera_pose']['height_normal_sign'] = -1
    with pytest.raises(ValueError):
        board_pose_bundle(sources, 'fixture', stud_height_mm=4.)
