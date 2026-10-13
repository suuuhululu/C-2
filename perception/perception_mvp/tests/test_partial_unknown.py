"""process_saved_bundle unknown_policy: per-candidate UNKNOWN handling. Synthetic inputs."""
import pytest

from perception_mvp import depth_grid

CAL = {"calibration_id": "cal"}
CONFIG = {"center_to_anchor_offsets_stud": {}}
GOOD = {"status": "CANDIDATE", "part_class": "yellow_2x2"}
BAD = {"status": "UNKNOWN", "part_class": "yellow_2x2", "reason": "top_surface_not_found"}
MEASURED = [dict(x=1, y=1, width=2, height=2, layer=1)]
SUPPLIED = [dict(x=9, y=9, width=1, height=1, layer=1)]


def run(monkeypatch, candidates, **kwargs):
    seen = {}
    monkeypatch.setattr(depth_grid, 'process_saved', lambda *a: dict(
        scene_id='s', view_id='D1', candidates=candidates, verified_regions=list(MEASURED)))
    monkeypatch.setattr(depth_grid, 'candidate_to_block', lambda c, offsets: {'id': id(c)})

    def fake_build(check_id, seq, views, previous, target, *, scene_stable):
        seen['views'] = views
        return {}, {'issues': []}
    monkeypatch.setattr(depth_grid, 'build_observed', fake_build)
    recordings = [dict(directory='x', detections=[], verified_regions=list(SUPPLIED))]
    _, diagnostics = depth_grid.process_saved_bundle(recordings, CAL, CONFIG, 'c', 0, [], None,
                                                    scene_stable=True, **kwargs)
    return seen['views'][0], diagnostics


def test_default_policy_keeps_whole_view_unobservable(monkeypatch):
    view, diagnostics = run(monkeypatch, [GOOD, BAD])
    assert view['status'] == 'UNOBSERVABLE' and view['reason'] == 'unknown_detection'
    assert view['verified_regions'] == [] and len(view['visible_blocks']) == 1
    assert diagnostics['partial_unknown_candidates'] == [] and diagnostics['issues'] == []


def test_candidate_policy_drops_only_the_unknown_candidate(monkeypatch):
    view, diagnostics = run(monkeypatch, [GOOD, BAD], unknown_policy='CANDIDATE')
    assert view['status'] == 'OK' and view['reason'] is None
    assert len(view['visible_blocks']) == 1  # The UNKNOWN candidate never becomes a block.
    assert view['verified_regions'] == MEASURED  # Measured evidence kept.
    assert SUPPLIED[0] not in view['verified_regions']  # Caller regions cannot be cross-checked.
    assert diagnostics['partial_unknown_candidates'] == [
        dict(view_id='D1', reasons=['top_surface_not_found'], measured_candidates=1)]
    assert diagnostics['issues'] == ['D1:partial_unknown_candidates']  # Not silent.


def test_candidate_policy_without_unknown_is_identical_to_default(monkeypatch):
    default, _ = run(monkeypatch, [GOOD])
    candidate, diagnostics = run(monkeypatch, [GOOD], unknown_policy='CANDIDATE')
    assert default == candidate and default['verified_regions'] == SUPPLIED + MEASURED
    assert diagnostics['issues'] == []


def test_all_candidates_unknown_has_no_blocks_but_is_reported(monkeypatch):
    view, diagnostics = run(monkeypatch, [BAD], unknown_policy='CANDIDATE')
    assert view['visible_blocks'] == [] and view['status'] == 'OK'
    assert diagnostics['issues'] == ['D1:partial_unknown_candidates']


def test_invalid_policy_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match='unknown_policy'):
        run(monkeypatch, [GOOD], unknown_policy='DROP')
