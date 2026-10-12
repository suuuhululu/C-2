"""No state cutoff; the 30-second window can return complete plans only."""
from copy import deepcopy

import pytest

from planning_trial import assembly_optimizer as optimizer
from planning_trial.assembly_api_fixtures import whole_request, reassess_request
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment


def symbols(n):
    return [dict(brick_type='2x2x1', color='blue', x=i, y=0,
                 layer=1, orientation_deg=0) for i in range(n)]


def option(help_count=0, manual=False):
    return dict(mode='HUMAN_ASSEMBLY' if manual else 'ROBOT_GRIP',
                release_strategy='NORMAL_OPEN',
                human_actions=[dict(action='MANUAL_PLACE' if manual else 'HOLD')
                               for _ in range(help_count)])


def test_complete_search_passes_10000_states_without_abandoning_witness(monkeypatch):
    # Synthetic subset graph: the last symbol must be first; earlier branches
    # visit over 10,000 dead subsets. This tests search policy, not geometry.
    blocks=symbols(15)

    def methods(target, placed, context):
        return ([], {}) if target==blocks[-1] and placed else ([option()], {})

    monkeypatch.setattr(optimizer, 'mode_options', methods)
    path, info=optimizer._complete_plan_first(blocks, [], {'finish_layers':False, 'max_states':1})
    assert info['expanded_states']>10000
    assert [index for index, _ in path]==[14]+list(range(14))
    assert 'reason' not in info


def test_help_search_also_has_no_state_count_cutoff(monkeypatch):
    blocks=symbols(14)
    monkeypatch.setattr(optimizer, 'mode_options', lambda *args: ([option(1)], {}))
    monkeypatch.setattr(optimizer, 'monotonic', lambda: 0.)
    path, info=optimizer._minimize_help_search(blocks, [], {'finish_layers':False, 'max_states':1}, deadline=30.)
    assert len(path)==14 and info['expanded_states']>10000
    assert info['optimal'] is True and info['cost']==[14,0,14]


def test_first_complete_after_window_returns_without_further_optimization(monkeypatch):
    blocks=symbols(2);now=[0.]
    witness=[(0,option(1)), (1,option())]

    def first(*args):
        now[0]=35.
        return witness, {'expanded_states':12001}

    monkeypatch.setattr(optimizer, 'monotonic', lambda:now[0])
    monkeypatch.setattr(optimizer, '_order_precedence', lambda *args: ([0,0],None))
    monkeypatch.setattr(optimizer, '_complete_plan_first', first)
    monkeypatch.setattr(optimizer, '_minimize_help_search', lambda *args,**kwargs:pytest.fail('Window already ended'))
    path, info=optimizer.order_search(blocks, [], {})
    assert path==witness and info['complete_plan_found'] is True
    assert info['selection']=='FIRST_COMPLETE_PLAN_AFTER_WINDOW'
    assert info['optimal'] is False and info['help_optimization_expanded_states']==0
    assert info['state_limit_applied'] is False


def test_window_returns_better_complete_plan_found_during_optimization(monkeypatch):
    blocks=symbols(2);now=[0.]
    incumbent=[(0,option(1,manual=True)), (1,option(1,manual=True))]

    def methods(target, placed, context):
        if placed:
            now[0]=31.
            return [option(1)], {}
        return [option()], {}

    monkeypatch.setattr(optimizer, 'monotonic', lambda:now[0])
    monkeypatch.setattr(optimizer, 'mode_options', methods)
    path, info=optimizer._minimize_help_search(blocks, [], {'finish_layers':False}, incumbent_path=incumbent, deadline=30.)
    assert len(path)==2 and info['cost']==[1,0,1]
    assert info['optimal'] is False
    assert info['optimization_stop_reason']=='HELP_OPTIMIZATION_WINDOW_ELAPSED'


def test_no_complete_plan_at_window_keeps_searching_until_first_full_order(monkeypatch):
    blocks=symbols(3)
    monkeypatch.setattr(optimizer, 'monotonic', lambda:35.)
    monkeypatch.setattr(optimizer, 'mode_options', lambda *args: ([option(1)],{}))
    path, info=optimizer._minimize_help_search(blocks, [], {'finish_layers':False}, deadline=30.)
    assert len(path)==3 and {i for i,_ in path}=={0,1,2}
    assert 'reason' not in info


def test_infeasible_search_after_window_returns_proof_without_partial_plan(monkeypatch):
    monkeypatch.setattr(optimizer, 'monotonic', lambda:35.)
    monkeypatch.setattr(optimizer, 'mode_options', lambda *args:([],{'reason':'blocked'}))
    path, info=optimizer._minimize_help_search(symbols(2), [], {'finish_layers':False}, deadline=30.)
    assert path is None and info['reason']=='NO_FEASIBLE_ORDER'
    assert info['blocked_candidates']


@pytest.mark.parametrize('legacy', ['absent', None, 1, 10000])
def test_current_api_accepts_no_limit_and_legacy_inputs(legacy):
    request=whole_request()
    assert 'max_states' not in request['assembly_context']
    if legacy!='absent':request['assembly_context']['max_states']=legacy
    before=deepcopy(request);audit={}
    result=handle_whole_plan(request,audit=audit)
    assert result['calculation_status']=='COMPLETED'
    assert result['planning_result']['status']=='READY'
    assert len(result['action_proposals'])==2 and result['execution_allowed'] is False
    assert audit['raw_result']['optimization']['state_limit_applied'] is False
    assessment=handle_step_reassessment(reassess_request(request,result))
    assert assessment['status']=='CANDIDATE' and assessment['execution_allowed'] is False
    assert request==before
