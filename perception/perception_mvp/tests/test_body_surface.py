"""Synthetic body/stud plane separation; no real-camera performance claim."""
import numpy as np
import pytest

from perception_mvp.opencv_live import body_surface_points


def plane(height):
    x, y = np.meshgrid(np.arange(10), np.arange(10))
    return np.column_stack((x.ravel(), y.ravel(), np.full(100, height)))


@pytest.mark.parametrize('top', [22., 40.625, 59.25, 77.875, 96.5])
def test_each_observed_top_body_gets_one_four_mm_increment(top):
    cloud = np.vstack((plane(top - 4.), plane(top)))
    keep = body_surface_points(cloud)
    assert np.median(cloud[keep, 2]) + 4. == pytest.approx(top)
    assert keep[:100].all() and not keep[100:].any()


def test_only_highest_supported_pair_is_selected_not_layer_times_studs():
    cloud = np.vstack((plane(18.), plane(22.), plane(55.25), plane(59.25)))
    keep = body_surface_points(cloud)
    assert np.median(cloud[keep, 2]) + 4. == pytest.approx(59.25)


def test_top_support_includes_body_and_studs_but_height_excludes_studs():
    cloud = np.vstack((plane(18.), plane(22.)[:50], np.tile(plane(0.), (4, 1))))
    diagnostics = {}
    body, studs = body_surface_points(cloud, return_pair=True, diagnostics=diagnostics)
    assert body.sum() == 100 and studs.sum() == 50
    assert body.mean() < .25 and (body | studs).mean() >= .25
    assert np.median(cloud[body, 2]) == 18.
    assert diagnostics['body_height_mm'] == 18.
    assert diagnostics['joint_top_fraction'] >= .25


def test_insufficient_joint_top_support_still_rejects():
    cloud = np.vstack((plane(18.), plane(22.)[:50], np.tile(plane(0.), (6, 1))))
    with pytest.raises(ValueError, match='unverified'):
        body_surface_points(cloud)


def test_supported_sloping_pair_collects_plane_not_horizontal_slice():
    x, y = np.meshgrid(np.linspace(0, 30, 20), np.linspace(0, 30, 20))
    body = np.column_stack((x.ravel(), y.ravel(), 18. + .12 * x.ravel()))
    studs = body.copy()
    studs[:, 2] += 4.
    cloud = np.vstack((body, studs))
    details = {}
    keep, upper = body_surface_points(cloud, return_pair=True, diagnostics=details)
    assert keep[:400].sum() >= 380 and not keep[400:].any()
    assert upper[400:].sum() >= 380 and not upper[:400].any()
    assert details['stud_separation_on_body_plane_mm'] == pytest.approx(4.)
    assert details['body_plane_slope'] == pytest.approx(.12)


def test_above_ten_degree_pair_remains_unverified():
    cloud = np.vstack((plane(18.), plane(22.)))
    cloud[:, 2] += .3 * cloud[:, 0]
    with pytest.raises(ValueError, match='unverified'):
        body_surface_points(cloud)


def test_individually_supported_nonparallel_surfaces_do_not_form_stud_pair():
    body, upper = plane(18.), plane(22.)
    upper[:, 2] += .1 * upper[:, 0]
    with pytest.raises(ValueError, match='unverified'):
        body_surface_points(np.vstack((body, upper)))


@pytest.mark.parametrize('cloud', [plane(22.), np.vstack((plane(18.), plane(25.)))])
def test_lone_surface_or_wrong_gap_is_unobservable(cloud):
    with pytest.raises(ValueError, match='body_stud_surfaces_unverified'):
        body_surface_points(cloud)
