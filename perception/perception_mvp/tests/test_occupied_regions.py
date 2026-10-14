"""Measured positive footprints do not verify empty space or hidden layers."""
import pytest

from perception_mvp.depth_grid import occupied_region_evidence
from perception_mvp.contracts import region_cells
from perception_mvp.backend_adapter import build_observed


def config():
    return dict(calibration_id='fixture', center_to_anchor_offsets_stud={
        'blue_2x3': {'0': [.5, 1.], '90': [1., .5]}})


def candidate(layer=3, axis=90):
    return dict(status='CANDIDATE', calibration_id='fixture', part_class='blue_2x3',
                grid_center_stud=[3.5, 6.] if axis == 90 else [4., 5.5],
                measured_layer_index=layer - 1, axis_angle_deg=axis)


@pytest.mark.parametrize('layer', range(1, 6))
@pytest.mark.parametrize('axis,width,height', [(90, 2, 3), (0, 3, 2)])
def test_positive_region_matches_rotated_footprint_only_at_observed_layer(layer, axis, width, height):
    evidence = occupied_region_evidence([candidate(layer, axis)], config())
    assert evidence['verified_regions'] == [dict(x=3, y=5, width=width, height=height, layer=layer)]
    cells = region_cells(evidence['verified_regions'])
    assert len(cells) == 6 and {cell[2] for cell in cells} == {layer}
    assert evidence['verification_basis']['kind'] == 'MEASURED_OCCUPIED_FOOTPRINT_ONLY'


def test_no_detection_or_unknown_does_not_become_verified_empty():
    for candidates in ([], [dict(status='UNKNOWN', reason='insufficient_depth')]):
        evidence = occupied_region_evidence(candidates, config())
        assert evidence['verified_regions'] == [] and evidence['verification_basis'] is None


def test_wrong_calibration_is_rejected():
    value = candidate()
    value['calibration_id'] = 'old'
    with pytest.raises(ValueError, match='matching calibration'):
        occupied_region_evidence([value], config())


def test_positive_region_never_establishes_full_initial_state():
    evidence = occupied_region_evidence([candidate()], config())
    view = dict(check_id='check', observation_seq=0, calibration_id='fixture', view_id='V0',
                visible_blocks=[dict(brick_type='2x3x1', color='blue', x=3, y=5,
                                     layer=3, orientation_deg=0)],
                status='OK', reason=None, verified_regions=evidence['verified_regions'])
    observed, _ = build_observed('check', 0, [view], [], None, scene_stable=True, check_kind='INITIAL')
    assert observed['status'] == 'UNOBSERVABLE'


def test_confirmed_lower_layer_is_not_removed_by_upper_occupied_evidence():
    from perception_mvp.multiview import compare_previous
    evidence = occupied_region_evidence([candidate(3)], config())
    old = dict(brick_type='2x3x1', color='blue', x=3, y=5, layer=1, orientation_deg=0)
    upper = dict(old, layer=3)
    result = compare_previous([upper], [old], evidence['verified_regions'])
    assert result['removed_candidates'] == []
    assert result['tracked_blocks'][0]['placement'] == old
