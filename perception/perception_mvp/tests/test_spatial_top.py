import cv2
import numpy as np
import pytest
from perception_mvp.opencv_live import rgb_top_quad, distributed_top_support


def masks():
    mask = np.zeros((100, 100), bool)
    mask[10:90, 10:90] = True
    top = np.zeros_like(mask)
    for x in (30, 70):
        for y in (30, 70):
            top[y-5:y+5, x-5:x+5] = True
    rgb = np.zeros((100, 100, 3), np.uint8)
    rgb[mask] = [230, 40, 40]
    return rgb, mask, top


def test_sparse_distributed_stud_points_can_support_rgb_outline():
    rgb, mask, top = masks()
    assert top.sum()/mask.sum() < .55
    assert rgb_top_quad(rgb, mask, top).shape == (4, 2)


@pytest.mark.parametrize('kind', ['one_side', 'central', 'missing_quadrant', 'too_few'])
def test_sparse_support_does_not_accept_missing_geometry(kind):
    rgb, mask, top = masks()
    if kind == 'one_side':
        top[:, 50:] = False
    elif kind == 'central':
        top[:] = False
        top[45:55, 45:55] = True
    elif kind == 'missing_quadrant':
        top[50:, 50:] = False
    else:
        top[:] = False
        top[30:35, 30:35] = True
    with pytest.raises(ValueError, match='outline_unverified'):
        rgb_top_quad(rgb, mask, top)


def test_rotated_spatial_domain_is_supported_without_filling_depth_gaps():
    _, _, top = masks()
    quad = np.array([[10, 10], [89, 10], [89, 89], [10, 89]], np.float32)
    assert distributed_top_support(top, quad)
    rotated_quad = np.column_stack((99-quad[:, 1], quad[:, 0])).astype(np.float32)
    assert distributed_top_support(np.rot90(top, -1), rotated_quad)
    assert not distributed_top_support(np.zeros_like(top), quad)


def test_occluded_instance_cannot_use_enclosing_rgb_rectangle():
    rgb, mask, top = masks()
    mask[10:90, 10:50] = False
    with pytest.raises(ValueError, match='outline_unverified'):
        rgb_top_quad(rgb, mask, top)
