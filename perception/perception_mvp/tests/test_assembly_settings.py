"""Saved profile reuse and pitch-derived geometry; no physical accuracy claim."""
import json
from pathlib import Path

import pytest
import yaml

from perception_mvp.contracts import candidate_to_block, LIVE_CLASSES
from perception_mvp.live_view import load_live_hand

ROOT = Path(__file__).resolve().parents[2]


def settings():
    return yaml.safe_load((ROOT / 'perception_mvp/config.yaml').read_text())


def test_hand_defaults_reuse_saved_profile_and_resolve_model_without_cwd(monkeypatch):
    profile = json.loads((ROOT / 'recordings/assembly_board_roi/V0/20261012T004735740339Z/hand_config.json').read_text())['hand']
    actual = settings()['hand']
    assert all(actual[key] == value for key, value in profile.items() if key != 'weights')
    captured = []
    monkeypatch.setattr('perception_mvp.hand_cycle.live_hand_components',
        lambda view, values: (captured.append(values) or 'detector', 'gate'))
    assert load_live_hand('V0', None) == ('detector', 'gate', None)
    assert Path(captured[0]['weights']).is_file()
    assert Path(captured[0]['weights']).is_absolute()
    assert load_live_hand('D1', None) == (None, None, None)


@pytest.mark.parametrize('name,orientation', [(name, orientation) for name in LIVE_CLASSES
    for orientation in ((0,) if name.endswith('2x2') else (0, 90))])
def test_pitch_derived_offsets_recover_actual_anchor(name, orientation):
    config = settings()['geometry']
    axis = 0 if name.endswith('2x2') else (90 if orientation == 0 else 0)
    offset = config['center_to_anchor_offsets_stud'][name][str(orientation)]
    center = [3 + offset[0], 5 + offset[1]]
    lattice = config['center_offsets_stud'][name][str(axis)]
    assert all(abs((value - fraction) - round(value - fraction)) < 1e-9
               for value, fraction in zip(center, lattice))
    block = candidate_to_block(dict(status='CANDIDATE', part_class=name, axis_angle_deg=axis,
        grid_center_stud=center, measured_layer_index=0), config['center_to_anchor_offsets_stud'])
    assert (block['x'], block['y'], block['orientation_deg']) == (3, 5, orientation)


def test_trial_geometry_is_complete_and_runtime_id_matches():
    from perception_mvp.depth_grid import validate_config
    config = settings()['geometry']
    assert config['threshold_status'] == 'temporary_test'
    assert config['max_height_spread_m'] == .005
    validate_config(config)
    assert config['depth_range_status'] == 'calibration_derived_trial_not_depth_validated'
    bundle = json.loads((ROOT / 'calibration/assembly_runtime_pitch16_flat0_20261013.json').read_text())
    assert bundle['calibration_id'] == config['calibration_id']
