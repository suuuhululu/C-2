"""Synthetic ray/volume proofs, not actual camera or final assembly validation."""
import numpy as np
import pytest

from perception_mvp.region_evidence import empty_column_evidence
from perception_mvp.backend_adapter import build_observed


def inputs():
    transform = np.diag([1., -1., -1., 1.])
    transform[:3, 3] = [.184, .184, .5]
    intrinsics = dict(model='none', fx=400., fy=400., cx=200., cy=200.)
    config = dict(stud_pitch_m=.016, board_stud_height_m=.004, height_tolerance_m=.0025,
        top_heights_m=[.022, .040625, .05925, .077875, .0965],
        layer_height_reference='BOARD_FLAT_SURFACE_ZERO', min_depth_pixels=50,
        min_depth_m=.1, max_depth_m=.8, calibration_id='synthetic')
    return np.full((400, 400), 500, np.uint16), .001, intrinsics, transform, config


def test_all_rays_past_volume_verify_empty_board_without_yolo_guess():
    evidence = empty_column_evidence(*inputs())
    assert len(evidence['verified_regions']) == 24 * 24 * 5
    assert evidence['verification_basis']['kind'] == 'DEPTH_RAYS_CLEAR_FIVE_LAYER_COLUMN'
    view = dict(check_id='check', observation_seq=0, calibration_id='synthetic', view_id='V0',
                visible_blocks=[], status='OK', reason=None, verified_regions=evidence['verified_regions'])
    observed, _ = build_observed('check', 0, [view], [], None, scene_stable=True, check_kind='INITIAL')
    assert observed['status'] == 'OK'


@pytest.mark.parametrize('distance', [0, 100, 1000])
def test_zero_occluder_or_out_of_range_never_means_empty(distance):
    args = list(inputs())
    args[0][:] = distance
    evidence = empty_column_evidence(*args)
    assert evidence['verified_regions'] == [] and evidence['verification_basis'] is None


def test_detected_or_unknown_object_mask_blocks_empty_claim():
    args = inputs()
    evidence = empty_column_evidence(*args, object_mask=np.ones(args[0].shape, bool))
    assert evidence['verified_regions'] == []


def test_single_missing_ray_keeps_affected_column_unknown():
    args = list(inputs())
    args[0][200, 200] = 0
    evidence = empty_column_evidence(*args)
    assert 0 < len(evidence['verified_regions']) < 24 * 24 * 5
    assert evidence['rejection_counts']['invalid_depth'] > 0


def test_clipped_volume_does_not_verify_whole_board():
    args = list(inputs())
    args[2]['cx'] = -100.
    evidence = empty_column_evidence(*args)
    assert len(evidence['verified_regions']) < 24 * 24 * 5
    assert evidence['rejection_counts']['clipped'] > 0


def test_saved_depth_pipeline_generates_empty_evidence_without_fabricated_detection(tmp_path):
    from pathlib import Path
    import yaml
    from perception_mvp.rgbd_io import save_frame
    from perception_mvp.depth_grid import process_saved
    depth, scale, intrinsics, transform, _ = inputs()
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text())['geometry']
    config.update(calibration_id='synthetic', depth_ranges_m={'V0': dict(min_depth_m=.1, max_depth_m=.8)})
    metadata = dict(scene_id='synthetic', view_id='V0', captured_at='synthetic-time',
        camera_info={'aligned': intrinsics}, depth_scale_m=scale, mode='REAL',
        robot_pose={'basis': 'synthetic only'}, check_id='synthetic', calibration_id='synthetic')
    directory = tmp_path / 'empty'
    save_frame(directory, np.zeros((*depth.shape, 3), np.uint8), depth, depth, metadata)
    result = process_saved(directory, [], dict(calibration_id='synthetic', views={'V0': transform}), config)
    assert result['candidates'] == []
    assert len(result['verified_regions']) == 24 * 24 * 5
    assert result['verification_basis']['occupied'] is None
    assert result['verification_basis']['empty']['kind'] == 'DEPTH_RAYS_CLEAR_FIVE_LAYER_COLUMN'
