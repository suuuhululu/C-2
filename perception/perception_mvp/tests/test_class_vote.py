"""Synthetic associations; tolerances are fixtures, not adopted device settings."""
from copy import deepcopy
import pytest

from perception_mvp.multiview import merge_views


def bundle(classes):
    views = []
    for view, name in zip(('V0', 'D1', 'D3'), classes):
        block = dict(brick_type='2x3x1' if name == 'yellow_2x3' else '2x2x1',
                     color='yellow', x=3, y=5, layer=1, orientation_deg=0)
        views.append(dict(view_id=view, check_id='c', observation_seq=0, calibration_id='g',
            status='OK' if name else 'UNOBSERVABLE', reason=None if name else 'depth_missing',
            visible_blocks=[block] if name else [],
            verified_regions=[dict(x=3, y=5, width=2, height=3 if name == 'yellow_2x3' else 2, layer=1)] if name else [],
            measured_candidates=[dict(status='CANDIDATE', part_class=name, block=block,
                surface_center_m=[.08, .1], top_height_m=.02)] if name else
                [dict(status='UNKNOWN', reason='insufficient_depth')]))
    return views


def fuse(views, **kw):
    return merge_views(views, scene_stable=True,
                       vote_policy=dict(center_tolerance_m=.002, height_tolerance_m=.003), **kw)


def test_majority_selects_without_fabricating_loser_evidence():
    views = bundle(['yellow_2x3', 'yellow_2x2', 'yellow_2x2'])
    before = deepcopy(views)
    result = fuse(views)
    assert [b['brick_type'] for b in result['visible_blocks']] == ['2x2x1']
    assert result['block_evidence'][0]['views'] == ['D1', 'D3']
    assert result['class_vote_log'][0]['votes'] == {'yellow_2x3': 1, 'yellow_2x2': 2}
    assert views == before


def test_single_valid_two_abstentions_retains_valid_block_not_whole_completion():
    result = fuse(bundle(['yellow_2x2', None, None]))
    assert len(result['visible_blocks']) == 1
    assert sum(x['decision'] == 'ABSTAIN' for x in result['class_vote_log']) == 2
    assert result['issues']  # Other unverified evidence is not turned into whole-board OK.


def test_tie_and_geometry_conflict_withhold_occupancy():
    views = bundle(['yellow_2x3', 'yellow_2x2', None])
    result = fuse(views)
    assert not result['visible_blocks'] and not result['verified_regions']
    assert 'class_vote:TIE' in result['issues']
    views = bundle(['yellow_2x2']*3)
    views[0]['measured_candidates'][0]['geometry_conflict'] = True
    assert not fuse(views)['visible_blocks']


def test_duplicate_view_association_and_chain_are_ambiguous():
    views = bundle(['yellow_2x2']*3)
    views[0]['measured_candidates'].append(deepcopy(views[0]['measured_candidates'][0]))
    # A duplicate detection is invalid; no vote may turn it into two votes.
    with pytest.raises(ValueError):
        fuse(views)


def test_stale_context_stability_partial_and_policy_validation():
    views = bundle(['yellow_2x2']*3)
    views[2]['check_id'] = 'old'
    with pytest.raises(ValueError, match='mixed'):
        fuse(views)
    views[2]['check_id'] = 'c'
    assert not merge_views(views, scene_stable=False)['visible_blocks']
    assert not fuse(views[:2])['class_vote_log']
    with pytest.raises(ValueError, match='tolerance'):
        merge_views(views, scene_stable=True,
                    vote_policy=dict(center_tolerance_m=0, height_tolerance_m=.003))


def test_three_agree_all_abstain_and_chain_association():
    assert len(fuse(bundle(['yellow_2x2']*3))['visible_blocks']) == 1
    assert not fuse(bundle([None]*3))['visible_blocks']
    views = bundle(['yellow_2x2']*3)
    for i, view in enumerate(views):
        view['measured_candidates'][0]['surface_center_m'][0] += i*.0015
    result = fuse(views)
    assert not result['visible_blocks']
    assert 'class_vote:AMBIGUOUS_ASSOCIATION' in result['issues']
