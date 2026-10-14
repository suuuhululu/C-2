"""observe_cycle with fake capture/inference: V0 owns layers, a failed D1 candidate does not void D1.
No camera, robot or YOLO; synthetic frames only. Not a device or team integration result."""
import json
import tempfile
from pathlib import Path

import numpy as np

from perception_mvp import main

BLOCK = dict(brick_type='2x2x1', color='yellow', x=1, y=1, layer=3, orientation_deg=0)
OCCUPIED = [dict(x=1, y=1, width=2, height=2, layer=3)]
EMPTY = [dict(x=9, y=9, width=1, height=1, layer=layer) for layer in range(1, 6)]


class Gate:
    state = 'IDLE'

    def begin_observation(self): pass

    def freeze_capture(self): pass

    def finish_observation(self): pass


def make_capture(root):
    def capture_view(view_id):
        directory = Path(root) / 'captures' / view_id
        directory.mkdir(parents=True)
        np.save(directory / 'rgb.npy', np.zeros((8, 8, 3), np.uint8))
        np.save(directory / 'depth_raw.npy', np.zeros((8, 8), np.uint16))
        np.save(directory / 'depth_aligned.npy', np.zeros((8, 8), np.uint16))
        (directory / 'metadata.json').write_text(json.dumps(dict(
            scene_id='s', view_id=view_id, captured_at='t', camera_info={'aligned': {}},
            depth_scale_m=.001, robot_pose={'x': 0}, mode='REAL', check_id='c',
            observation_seq=0, calibration_id='cal')))
        return dict(directory=str(directory), verified_regions=[])
    return capture_view


def fake_result(view_id):
    # V0 measures one block; D1 measures one block and fails one candidate; D3 measures nothing.
    candidates = {'V0': [dict(status='CANDIDATE')],
                  'D1': [dict(status='CANDIDATE'), dict(status='UNKNOWN', reason='top_surface_not_board_parallel')],
                  'D3': [dict(status='UNKNOWN', reason='top_surface_not_board_parallel')]}[view_id]
    return dict(scene_id='s', view_id=view_id, candidates=candidates,
                occupied_regions=list(OCCUPIED), empty_regions=list(EMPTY),
                verified_regions=OCCUPIED + EMPTY, verification_basis=None)


def run(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setattr(main, 'infer_masks', lambda *args: [])
        monkeypatch.setattr(main, 'process_saved',
                            lambda directory, *args: fake_result(Path(directory).name))
        monkeypatch.setattr(main, 'candidate_to_block', lambda c, offsets: dict(BLOCK))
        manifest = dict(view_order=['V0', 'D1', 'D3'], mode='REAL', check_id='c', observation_seq=0,
                        check_kind='FINAL', target_after=None, previous_accepted_blocks=[])
        delivered = []
        observed, diagnostics = main.observe_cycle(
            Gate(), make_capture(root), manifest, 'weights', dict(calibration_id='cal'),
            dict(center_to_anchor_offsets_stud={}), .25, callback=delivered.append,
            confirm_view=lambda view: True, bundle_valid=lambda: True, output_root=Path(root) / 'out')
    return observed, diagnostics, delivered


def test_v0_layer_blocks_are_delivered_and_d1_d3_failures_do_not_void_the_cycle(monkeypatch):
    observed, diagnostics, delivered = run(monkeypatch)
    assert observed['status'] == 'OK' and observed['reason'] is None
    assert observed['visible_blocks'] == [BLOCK]  # V0 only; D1's measured block is auxiliary.
    assert delivered == [observed]


def test_auxiliary_failures_do_not_gate_and_roles_are_recorded(monkeypatch):
    _, diagnostics, _ = run(monkeypatch)
    assert diagnostics['issues'] == []  # No D1/D3 UNKNOWN gate; D1's block agrees with V0 on layer 3.
    roles = {n['view_id']: n for n in diagnostics['view_roles']}
    assert roles['V0']['role'] == 'AUTHORITY' and roles['D1']['role'] == 'AUXILIARY'
    assert roles['D1']['unknown_reasons'] == ['top_surface_not_board_parallel']
    assert diagnostics['cross_check'][0]['result'] == 'AGREES_WITH_V0'
    assert any(r['x'] == 9 for r in observed_regions(diagnostics))


def observed_regions(diagnostics):
    # Clear-column evidence from D1/D3 is still merged (layer independent).
    return [r for evidence in diagnostics['source_measurements'] for r in evidence['empty_regions']]
