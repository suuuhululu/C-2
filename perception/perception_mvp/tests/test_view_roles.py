"""V0 owns layers; D1/D3 are auxiliary. Synthetic inputs, no Depth."""
import pytest

from perception_mvp import depth_grid
from perception_mvp.view_roles import build_role_view, cross_check, finalize

IDENTITY = dict(check_id='c', observation_seq=0, calibration_id='cal')
GOOD = {'status': 'CANDIDATE', 'tag': 'good'}
BAD = {'status': 'UNKNOWN', 'reason': 'top_surface_not_board_parallel'}
OCCUPIED = [dict(x=1, y=1, width=2, height=2, layer=3)]
EMPTY = [dict(x=9, y=9, width=1, height=1, layer=1), dict(x=9, y=9, width=1, height=1, layer=2)]
SUPPLIED = [dict(x=20, y=20, width=1, height=1, layer=1)]
BLOCK = dict(brick_type='2x2x1', color='yellow', x=1, y=1, layer=3, orientation_deg=0)


def result(view_id, candidates):
    return dict(view_id=view_id, candidates=candidates, occupied_regions=list(OCCUPIED),
                empty_regions=list(EMPTY))


def to_block(candidate):
    return dict(BLOCK)


def test_v0_keeps_layer_blocks_and_occupied_regions_when_one_candidate_is_unknown():
    view, notes, gating = build_role_view(IDENTITY, result('V0', [GOOD, BAD]), SUPPLIED, to_block)
    assert view['status'] == 'OK' and view['reason'] is None
    assert view['visible_blocks'] == [BLOCK]
    assert view['verified_regions'] == OCCUPIED + EMPTY  # Supplied regions dropped beside UNKNOWN.
    assert gating == ['V0:partial_unknown_candidates']
    assert notes['unknown_reasons'] == ['top_surface_not_board_parallel']


def test_v0_without_unknown_keeps_supplied_regions_and_is_not_gated():
    view, _, gating = build_role_view(IDENTITY, result('V0', [GOOD]), SUPPLIED, to_block)
    assert view['verified_regions'] == SUPPLIED + OCCUPIED + EMPTY and gating == []


def test_auxiliary_view_contributes_no_blocks_and_no_occupied_layers():
    view, notes, gating = build_role_view(IDENTITY, result('D1', [GOOD, BAD]), SUPPLIED, to_block)
    assert view['visible_blocks'] == []
    assert view['verified_regions'] == EMPTY  # Clear-column evidence only.
    assert view['status'] == 'OK' and gating == []  # An auxiliary UNKNOWN never gates MATCH.
    assert notes['auxiliary_blocks'] == [BLOCK] and notes['dropped_occupied_regions'] == 1


def test_auxiliary_view_without_unknown_keeps_supplied_regions():
    view, _, _ = build_role_view(IDENTITY, result('D3', [GOOD]), SUPPLIED, to_block)
    assert view['verified_regions'] == SUPPLIED + EMPTY


def notes_for(aux_block):
    return {'V0': dict(visible_blocks=[BLOCK]), 'D1': dict(auxiliary_blocks=[aux_block])}


def test_cross_check_agreement_is_reported_without_gating():
    gating, report = cross_check(notes_for(dict(BLOCK)))
    assert gating == [] and report[0]['result'] == 'AGREES_WITH_V0'


def test_cross_check_other_layer_is_information_only():
    gating, report = cross_check(notes_for(dict(BLOCK, layer=2)))
    assert gating == [] and report[0]['result'] == 'NO_SAME_LAYER_V0_BLOCK'


def test_cross_check_same_layer_disagreement_gates():
    for changed in (dict(color='blue'), dict(brick_type='2x3x1'), dict(x=2), dict(y=2)):
        gating, report = cross_check(notes_for(dict(BLOCK, **changed)))
        assert gating == ['D1:disagrees_with_V0_same_layer']
        assert report[0]['result'] == 'DISAGREES_WITH_V0'


def test_finalize_adds_each_issue_once_and_keeps_blocks_out_of_the_report():
    diagnostics = dict(issues=['V0:partial_unknown_candidates'])
    notes = dict(V0=dict(view_id='V0', visible_blocks=[BLOCK]), D1=dict(view_id='D1'))
    finalize(diagnostics, notes, ['V0:partial_unknown_candidates'])
    assert diagnostics['issues'] == ['V0:partial_unknown_candidates']
    assert all('visible_blocks' not in n for n in diagnostics['view_roles'])


def test_bundle_with_roles_survives_a_failed_d1_candidate(monkeypatch):
    results = {'V0': result('V0', [GOOD]), 'D1': result('D1', [GOOD, BAD])}
    for value in results.values():
        value['scene_id'] = 's'
    queue = [results['V0'], results['D1']]
    monkeypatch.setattr(depth_grid, 'process_saved', lambda *args: queue.pop(0))
    monkeypatch.setattr(depth_grid, 'candidate_to_block', lambda c, offsets: dict(BLOCK))
    seen = {}

    def fake_build(check_id, seq, views, previous, target, *, scene_stable):
        seen['views'] = views
        return {}, {'issues': []}
    monkeypatch.setattr(depth_grid, 'build_observed', fake_build)
    recordings = [dict(directory='x', detections=[], verified_regions=[]),
                  dict(directory='y', detections=[], verified_regions=[])]
    _, diagnostics = depth_grid.process_saved_bundle(
        recordings, dict(calibration_id='cal'), dict(center_to_anchor_offsets_stud={}), 'c', 0, [], None,
        scene_stable=True, unknown_policy='ROLES')
    v0, d1 = seen['views']
    assert v0['visible_blocks'] == [BLOCK] and d1['visible_blocks'] == []
    assert d1['status'] == 'OK' and diagnostics['issues'] == []
    assert [n['role'] for n in diagnostics['view_roles']] == ['AUTHORITY', 'AUXILIARY']
