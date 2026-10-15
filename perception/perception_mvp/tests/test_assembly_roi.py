"""Synthetic ROI wiring; not evidence of field calibration or detector accuracy."""
import json
from types import SimpleNamespace as N

import numpy as np
import pytest

from perception_mvp.assembly_roi import freeze_rois, load_profiles, mask_for_view


def profiles(root, size=(12, 10), polygon=None):
    polygon = polygon or [[2, 2], [9, 2], [2, 8]]
    for view in ('V0', 'D1', 'D3'):
        directory = root / view / '001'
        directory.mkdir(parents=True)
        (directory / 'assembly_roi.json').write_text(json.dumps(dict(
            purpose='ASSEMBLY_BOARD', view_id=view, image_size=list(size), polygon_px=polygon)))
    return root


def test_profiles_are_frozen_and_resolution_is_checked(tmp_path):
    root = profiles(tmp_path / 'roi')
    config = freeze_rois(dict(assembly_roi_root=str(root)))
    mask = mask_for_view(config, 'D3', (10, 12, 3))
    assert mask[2, 2] and not mask[8, 9]
    (root / 'D3/001/assembly_roi.json').write_text('{}')
    assert np.array_equal(mask, mask_for_view(config, 'D3', (10, 12, 3)))
    with pytest.raises(ValueError, match='resolution_mismatch'):
        mask_for_view(config, 'V0', (480, 640, 3))


def test_configured_missing_roi_never_silently_uses_full_frame(tmp_path):
    with pytest.raises(ValueError, match='Missing assembly ROI for V0'):
        freeze_rois(dict(assembly_roi_root=str(tmp_path)))
    root = profiles(tmp_path / 'roi')
    path = root / 'D1/001/assembly_roi.json'
    value = json.loads(path.read_text())
    value['view_id'] = 'D3'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='View mismatch'):
        load_profiles(root)


def test_yolo_crops_rgb_and_restores_full_size_masks(tmp_path, monkeypatch):
    from perception_mvp import yolo_pipeline
    config = freeze_rois(dict(assembly_roi_root=str(profiles(tmp_path))))
    roi = mask_for_view(config, 'V0', (10, 12, 3))
    rgb = np.arange(360, dtype=np.uint16).reshape(10, 12, 3).astype(np.uint8)
    class Tensor:
        def __init__(self, values):
            self.values = np.asarray(values)
        def cpu(self):
            return self
        def numpy(self):
            return self.values
        def __len__(self):
            return len(self.values)
    masks = np.zeros((3, 7, 8), float)
    masks[0, 0, 0] = 1  # inside
    masks[1, 6, 7] = 1  # outside the polygon, but inside its bounding box
    masks[2, 0, 0] = masks[2, 6, 7] = 1  # boundary crossing is retained for UNKNOWN
    class Boxes:
        cls, conf = Tensor([0, 0, 0]), Tensor([.9, .9, .9])
        def __len__(self):
            return 3
    def predict(image, **kwargs):
        assert np.array_equal(image, rgb[2:9, 2:10, ::-1])
        return [N(boxes=Boxes(), masks=N(data=Tensor(masks)))]
    monkeypatch.setattr(yolo_pipeline, 'load_segmentation_model',
                        lambda weights: N(names={0: 'blue_2x2'}, predict=predict))
    detections = yolo_pipeline.infer_masks(rgb, 'synthetic.pt', .25, roi_mask=roi)
    assert len(detections) == 2
    assert all(mask.shape == (10, 12) for mask, _, _ in detections)
    assert detections[0][0][2, 2] and detections[0][0].sum() == 1
    assert detections[1][0][8, 9]  # not silently clipped into a valid smaller brick


@pytest.mark.parametrize('use_default', [False, True])
def test_observer_uses_frozen_roi_without_live_view_cli(tmp_path, monkeypatch, use_default):
    from perception_mvp import main
    root = profiles(tmp_path)
    monkeypatch.setattr('perception_mvp.assembly_roi.DEFAULT_ROOT', root)
    seen = []
    def cycle(*args, **kwargs):
        seen.append(args[7]['assembly_roi_profiles'])
        return {}, {}
    monkeypatch.setattr(main, 'run_observation_cycle', cycle)
    observer = main.make_inspection_observer(None, None, lambda: iter(()), None, None, {},
        ({} if use_default else dict(assembly_roi_root=str(root))), .25, confirm_view=lambda v: True,
        workflow_valid=lambda: True, bundle_valid=lambda: True)
    (root / 'V0/001/assembly_roi.json').write_text('{}')
    observer(dict(check_kind='INITIAL', current=None), lambda: True)
    assert set(seen[0]) == {'V0', 'D1', 'D3'}
    assert seen[0]['V0']['polygon_px'] == [[2, 2], [9, 2], [2, 8]]


def test_production_drops_outside_candidates_and_never_verifies_outside_roi(tmp_path, monkeypatch):
    import yaml
    from pathlib import Path
    from perception_mvp import depth_grid
    from perception_mvp.rgbd_io import save_frame
    from perception_mvp.contracts import region_cells
    root = profiles(tmp_path / 'roi', (400, 400), [[160, 160], [240, 160], [240, 240], [160, 240]])
    config = yaml.safe_load(Path(depth_grid.__file__).with_name('config.yaml').read_text())['geometry']
    config.update(assembly_roi_root=str(root), calibration_id='synthetic',
                  depth_ranges_m={'V0': dict(min_depth_m=.1, max_depth_m=.8)})
    transform = np.diag([1., -1., -1., 1.])
    transform[:3, 3] = [.184, .184, .5]
    depth = np.full((400, 400), 500, np.uint16)
    meta = dict(scene_id='synthetic', view_id='V0', captured_at='synthetic',
        camera_info={'aligned': dict(model='none', fx=400., fy=400., cx=200., cy=200.)},
        depth_scale_m=.001, mode='REAL', robot_pose={'basis': 'synthetic only'})
    save_frame(tmp_path / 'capture', np.zeros((400, 400, 3), np.uint8), depth, depth, meta)
    monkeypatch.setattr(depth_grid, 'frame_board_baseline', lambda *a, **kw: None)
    measured = []
    def measure(mask, cls, *args, **kwargs):
        measured.append(cls)
        return dict(status='CANDIDATE', calibration_id='synthetic', part_class=cls,
                    grid_center_stud=[11.5, 11.5], measured_layer_index=0, axis_angle_deg=0)
    monkeypatch.setattr(depth_grid, 'measure_candidate', measure)
    masks = [np.zeros(depth.shape, bool) for _ in range(3)]
    masks[0][195:205, 195:205] = True
    masks[1][:5, :5] = True
    masks[2][150:170, 150:170] = True
    result = depth_grid.process_saved(tmp_path / 'capture', [(m, 'blue_2x2', .9) for m in masks],
        dict(calibration_id='synthetic', views={'V0': transform}), config)
    assert measured == ['blue_2x2']
    assert [c['status'] for c in result['candidates']] == ['CANDIDATE', 'UNKNOWN']
    assert result['candidates'][1]['reason'] == 'instance_crosses_roi_boundary'
    assert result['assembly_roi']['dropped_outside_candidates'] == 1
    cells = region_cells(result['verified_regions'])
    assert (0, 0, 1) not in cells
    assert len(cells) < 24*24*5


def test_three_view_cycle_passes_roi_to_inference_and_archives_it(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    from perception_mvp import main
    from perception_mvp.rgbd_io import save_frame
    root = profiles(tmp_path / 'roi')
    seen = []
    def infer(rgb, weights, confidence, *, roi_mask):
        assert roi_mask.shape == rgb.shape[:2] and roi_mask[2, 2] and not roi_mask[0, 0]
        seen.append(roi_mask)
        return []
    monkeypatch.setattr(main, 'infer_masks', infer)
    monkeypatch.setattr(main, 'process_saved', lambda directory, *args: dict(
        scene_id='synthetic', view_id=Path(directory).name, candidates=[],
        occupied_regions=[], empty_regions=[], verified_regions=[], verification_basis=None))
    def capture(view):
        directory = tmp_path / 'captures' / view
        rgb = np.zeros((10, 12, 3), np.uint8)
        depth = np.full((10, 12), 500, np.uint16)
        meta = dict(mode='REAL', scene_id='synthetic', view_id=view, captured_at='synthetic',
                    check_id='c', observation_seq=0, calibration_id='cal',
                    depth_scale_m=.001, camera_info={'aligned': {}}, robot_pose={'basis': 'synthetic'})
        save_frame(directory, rgb, depth, depth, meta)
        return dict(directory=str(directory), verified_regions=[])
    gate = N(state='IDLE', begin_observation=lambda: None,
             freeze_capture=lambda: None, finish_observation=lambda: None)
    main.observe_cycle(gate, capture, dict(mode='REAL', view_order=['V0', 'D1', 'D3'],
        check_id='c', observation_seq=0, check_kind='INITIAL', target_after=None, previous_accepted_blocks=[]),
        'synthetic.pt', dict(calibration_id='cal'), dict(assembly_roi_root=str(root)), .25,
        callback=lambda value: None, confirm_view=lambda v: True, bundle_valid=lambda: True,
        output_root=tmp_path / 'cycles')
    assert len(seen) == 3
    archives = list((tmp_path / 'cycles').iterdir())
    assert len(archives) == 1
    for view in ('V0', 'D1', 'D3'):
        profile = json.loads((archives[0] / view / 'assembly_roi.json').read_text())
        assert profile['view_id'] == view and profile['image_size'] == [12, 10]
    assert capsys.readouterr().out.count('조립판 ROI 적용') == 3
