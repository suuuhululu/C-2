"""Synthetic ray/volume proofs, not actual camera or final assembly validation."""
import numpy as np
import pytest

from perception_mvp.region_evidence import empty_column_evidence
from perception_mvp.region_evidence import empty_above_block_evidence
from perception_mvp.contracts import region_cells
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


@pytest.mark.parametrize('layer', range(1, 6))
def test_depth_verifies_only_air_above_a_measured_block(layer):
    args = list(inputs())
    args[0][:] = round((.5 - args[4]['top_heights_m'][layer-1]) / args[1])
    occupied = [dict(x=11, y=11, width=2, height=2, layer=layer)]
    evidence = empty_above_block_evidence(*args, occupied_regions=occupied)
    assert region_cells(evidence['verified_regions']) == {
        (x, y, upper) for x in (11, 12) for y in (11, 12) for upper in range(layer+1, 6)}
    if layer < 5:
        assert evidence['verification_basis']['kind'] == 'DEPTH_RAYS_CLEAR_ABOVE_MEASURED_BLOCK'
    else:
        assert evidence['verification_basis'] is None


@pytest.mark.parametrize('depth_value', [0, 100, 1000, 440])
def test_above_block_proof_rejects_missing_out_of_range_or_higher_occluder(depth_value):
    args = list(inputs())
    args[0][:] = depth_value
    evidence = empty_above_block_evidence(*args,
        occupied_regions=[dict(x=11, y=11, width=2, height=2, layer=1)])
    assert evidence['verified_regions'] == []


def test_above_block_proof_keeps_unknown_mask_and_clipped_space_unverified():
    args = list(inputs())
    args[0][:] = 478
    occupied = [dict(x=11, y=11, width=2, height=2, layer=1)]
    unknown = np.ones(args[0].shape, bool)
    assert empty_above_block_evidence(*args, occupied_regions=occupied,
                                     object_mask=unknown)['verified_regions'] == []
    args[2]['cx'] = -100.
    assert empty_above_block_evidence(*args, occupied_regions=occupied)['verified_regions'] == []


def test_no_measured_footprint_proves_no_air_and_hidden_lower_layers_remain_unknown():
    args = list(inputs())
    assert empty_above_block_evidence(*args, occupied_regions=[])['verified_regions'] == []
    args[0][:] = 441
    evidence = empty_above_block_evidence(*args,
        occupied_regions=[dict(x=11, y=11, width=1, height=1, layer=3)])
    assert {cell[2] for cell in region_cells(evidence['verified_regions'])} == {4, 5}


def test_one_missing_depth_ray_cannot_be_replaced_by_known_block_air():
    args = list(inputs())
    args[0][:] = 478
    args[0][190, 190] = 0
    evidence = empty_above_block_evidence(*args,
        occupied_regions=[dict(x=11, y=11, width=2, height=2, layer=1)])
    assert len(region_cells(evidence['verified_regions'])) < 16
    assert evidence['rejection_counts']['missing_depth'] > 0


def test_saved_depth_pipeline_generates_empty_evidence_without_fabricated_detection(tmp_path):
    from pathlib import Path
    import yaml
    from perception_mvp.rgbd_io import save_frame
    from perception_mvp.depth_grid import process_saved
    depth, scale, intrinsics, transform, _ = inputs()
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text())['geometry']
    config.pop('assembly_roi_root')  # Synthetic full-board geometry has no field ROI.
    config.update(calibration_id='synthetic',
                  depth_ranges_m={'V0': dict(min_depth_m=.1, max_depth_m=.8)})
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


@pytest.mark.parametrize('view,unknown,empty_cells', [('V0', False, 16), ('D1', False, 0), ('V0', True, 0)])
def test_saved_pipeline_adds_air_only_above_authority_blocks(tmp_path, monkeypatch, view, unknown, empty_cells):
    from pathlib import Path
    import yaml
    from perception_mvp import depth_grid
    from perception_mvp.rgbd_io import save_frame
    from perception_mvp.view_roles import build_role_view
    depth, scale, intrinsics, transform, _ = inputs()
    depth[:] = 478
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text())['geometry']
    config.pop('assembly_roi_root')  # Synthetic full-board geometry has no field ROI.
    config.update(calibration_id='synthetic',
                  depth_ranges_m={view: dict(min_depth_m=.1, max_depth_m=.8)})
    candidate = dict(status='CANDIDATE', calibration_id='synthetic', part_class='blue_2x2',
                     grid_center_stud=[11.5, 11.5], measured_layer_index=0, axis_angle_deg=0)
    monkeypatch.setattr(depth_grid, 'frame_board_baseline', lambda *a: None)
    monkeypatch.setattr(depth_grid, 'measure_candidate', lambda mask, cls, *a, **kw:
                        dict(candidate) if cls == 'blue_2x2' else
                        dict(status='UNKNOWN', reason='rgb_top_outline_unverified', part_class=cls))
    metadata = dict(scene_id='synthetic', view_id=view, captured_at='synthetic-time',
        camera_info={'aligned': intrinsics}, depth_scale_m=scale, mode='REAL',
        robot_pose={'basis': 'synthetic only'}, check_id='synthetic', calibration_id='synthetic')
    directory = tmp_path / view
    save_frame(directory, np.zeros((*depth.shape, 3), np.uint8), depth, depth, metadata)
    detections = [(np.ones(depth.shape, bool), 'blue_2x2', .9)]
    if unknown:
        detections.append((np.ones(depth.shape, bool), 'red_2x1', .9))
    result = depth_grid.process_saved(directory, detections,
        dict(calibration_id='synthetic', views={view: transform}), config)
    assert len(region_cells(result['empty_regions'])) == empty_cells
    block = dict(brick_type='2x2x1', color='blue', x=11, y=11, layer=1, orientation_deg=0)
    role, _, gating = build_role_view(dict(check_id='c', observation_seq=0, calibration_id='synthetic'),
                                     result, [], lambda c: block)
    assert len(role['visible_blocks']) == (1 if view == 'V0' else 0)
    assert bool(gating) == unknown
    if empty_cells:
        assert result['verification_basis']['above_blocks']['kind'] == 'DEPTH_RAYS_CLEAR_ABOVE_MEASURED_BLOCK'
        assert {cell[2] for cell in region_cells(role['verified_regions'])} == set(range(1, 6))
