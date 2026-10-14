"""Replay reporting boundary only; actual-model replay is recorded separately."""
import json

import numpy as np
import pytest

from perception_mvp import assembly_replay as replay


def test_unobservable_replay_preserves_reason_and_never_claims_d_result(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    np.save(source / 'rgb.npy', np.zeros((4, 4, 3), np.uint8))
    np.save(source / 'depth_aligned.npy', np.full((4, 4), 1000, np.uint16))
    (source / 'metadata.json').write_text(json.dumps(dict(view_id='V0', captured_at='synthetic',
        camera_info={'aligned': {}})))
    monkeypatch.setattr(replay, 'load_view_calibrations', lambda root: {'V0': (None, {})})
    monkeypatch.setattr(replay, 'load_segmentation_model', lambda *args, **kwargs: object())
    monkeypatch.setattr(replay, 'process_frame', lambda *args, **kwargs: [dict(
        mask=np.ones((4, 4), bool), part_class='yellow_2x2', layer=None,
        reason='body_stud_surfaces_unverified')])
    output = tmp_path / 'result'
    args = ['--recording', str(source), '--weights', str(tmp_path / 'fixture.pt'),
            '--calibration-root', str(tmp_path), '--output', str(output)]
    replay.main(args)
    report = json.loads((output / 'report.json').read_text())
    assert report['scope'] == 'DIAGNOSTIC_REPLAY_NOT_VALIDATION'
    assert report['frames'][0]['records'][0]['reason'] == 'body_stud_surfaces_unverified'
    assert report['frames'][0]['records'][0]['layer'] is None
    assert 'mask' not in report['frames'][0]['records'][0]
    with pytest.raises(FileExistsError):
        replay.main(args)


def test_failed_frame_reports_error_instead_of_empty_normal_result(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, 'load_view_calibrations', lambda root: {})
    monkeypatch.setattr(replay, 'load_segmentation_model', lambda *args, **kwargs: object())
    output = tmp_path / 'result'
    with pytest.raises(RuntimeError, match='replays failed'):
        replay.main(['--recording', str(tmp_path / 'missing'), '--weights', 'fixture.pt',
                     '--calibration-root', str(tmp_path), '--output', str(output)])
    row = json.loads((output / 'report.json').read_text())['frames'][0]
    assert 'error' in row and 'records' not in row
