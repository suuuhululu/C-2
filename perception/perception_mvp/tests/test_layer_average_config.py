"""Adopted average-layer model is a trial, not real board depth validation."""
import json

import numpy as np
import pytest

from perception_mvp.live_view import load_layer_reference


def test_default_five_layers_use_endpoint_average_and_nonoverlapping_tolerance():
    settings = load_layer_reference()
    levels = np.asarray(settings['top_heights_mm'])
    assert levels == pytest.approx([22., 40.625, 59.25, 77.875, 96.5])
    assert np.diff(levels) == pytest.approx([18.625] * 4)
    assert settings['tolerance_mm'] == 2.5
    assert np.all(2 * settings['tolerance_mm'] < np.diff(levels))
    assert settings['height_reference_offset_mm'] == 4.
    assert settings['max_height_spread_mm'] == 5.
    assert settings['block_stud_height_mm'] == 4.
    assert settings['status'] == 'trial_average_unvalidated_board_baseline'


def test_explicit_layer_reference_preserves_user_override(tmp_path):
    path = tmp_path / 'layers.json'
    supplied = dict(top_heights_mm=[10, 30, 50, 70, 90], tolerance_mm=2)
    path.write_text(json.dumps(supplied))
    assert load_layer_reference(path) == supplied
