"""Ordering acceleration must agree with exhaustive feasible orders; no devices."""
from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path

import pytest

from planning_trial import assembly_optimizer as optimizer


def brick(x, y, layer=1, kind='2x2x1', angle=0):
    return dict(brick_type=kind, color='blue', x=x, y=y,
                layer=layer, orientation_deg=angle)


@pytest.fixture
def context():
    data = json.loads(Path(__file__).with_name('sample_user_rules_5mm_measured_rev2_inputs.json').read_text())
    data['assembly_context'].update(supported_modes=['ROBOT_GRIP'], finish_layers=False)
    return data['assembly_context']


def exhaustive_cost(blocks, current, context):
    best = None
    for order in permutations(blocks):
        placed, total = list(current), (0, 0, 0)
        for target in order:
            options, _ = optimizer.mode_options(target, placed, context)
            if not options:
                break
            cost = min(map(optimizer.option_cost, options))
            total = tuple(a + b for a, b in zip(total, cost))
            placed.append(target)
        else:
            best = total if best is None else min(best, total)
    return best


@pytest.mark.parametrize('axes', [['x'], ['y'], ['x', 'y']])
@pytest.mark.parametrize('modes', [['ROBOT_GRIP'], ['ROBOT_GRIP', 'HUMAN_ASSEMBLY']])
@pytest.mark.parametrize('priority', ['COMPLETE_DESIGN_THEN_MIN_HELP', 'MIN_HELP_COMPLETE_DESIGN_SEARCH'])
@pytest.mark.parametrize('blocks', [
    [brick(7, 10, kind='2x3x1', angle=90), brick(7, 12, kind='2x3x1', angle=90)],
    [brick(6, 6), brick(8, 6), brick(6, 8)],
    [brick(6, 6), brick(7, 6, layer=2)],
    [brick(6, 6), brick(9, 6), brick(6, 9), brick(9, 9)],
])
def test_accelerated_plan_agrees_with_exhaustive_orders(context, axes, modes, priority, blocks):
    context.update(grip_axes=axes, supported_modes=modes, planning_priority=priority)
    design = {'design_version': 1, 'blocks': blocks}
    before = deepcopy((design, context))
    expected = exhaustive_cost(blocks, [], context)
    result = optimizer.plan_assembly(design, {'current_revision': 0, 'blocks': []}, context)
    assert (result['status'] == 'CANDIDATE') is (expected is not None)
    if expected is not None:
        assert result['optimization']['cost'] == list(expected)
    else:
        assert result['status'] == 'NO_FEASIBLE_ORDER'
    assert result['execution_allowed'] is False
    assert (design, context) == before


def test_alternative_grip_axis_is_not_pruned(context):
    blocks = [brick(6, 6), brick(8, 6)]
    result = optimizer.plan_assembly({'design_version': 1, 'blocks': blocks},
                                     {'current_revision': 0, 'blocks': []}, context)
    assert result['status'] == 'CANDIDATE'
    assert result['optimization']['cost'] == [0, 0, 0]
    assert all(a['grip_axis'] == 'y' for a in result['assembly_actions'][1:])


def test_existing_current_is_not_reordered_to_clear_a_corridor(context):
    blocks = [brick(7, 10, kind='2x3x1', angle=90), brick(7, 12, kind='2x3x1', angle=90)]
    result = optimizer.plan_assembly({'design_version': 1, 'blocks': blocks},
                                     {'current_revision': 4, 'blocks': blocks[:1]}, context)
    assert result['status'] == 'NO_FEASIBLE_ORDER'
    assert result['optimization']['expanded_states'] == 0
    assert result['optimization']['blocked_candidates'][0]['block'] == blocks[1]


@pytest.mark.parametrize('modes', [['ROBOT_GRIP'], ['HUMAN_ASSEMBLY'],
                                  ['ROBOT_GRIP', 'HUMAN_ASSEMBLY']])
def test_insertion_precedence_covers_all_modes_and_higher_layers(context, modes):
    # The rotated upper block covers the lower footprint even across a layer gap.
    lower = brick(6, 6)
    upper = brick(6, 6, layer=3, kind='2x3x1', angle=90)
    disjoint = brick(15, 15)
    context.update(supported_modes=modes)
    required, blocked = optimizer._order_precedence([upper, disjoint, lower], [], context)
    assert blocked is None
    assert required[0] & (1 << 2)
    assert not required[0] & (1 << 1)
    assert not required[1] & (1 << 0)


@pytest.mark.parametrize('priority', ['COMPLETE_DESIGN_THEN_MIN_HELP',
                                    'MIN_HELP_COMPLETE_DESIGN_SEARCH'])
def test_mixed_mode_search_skips_lower_insertion_after_upper(context, priority, monkeypatch):
    base, lower, upper, distant = brick(6, 6), brick(8, 6), brick(7, 6, layer=2), brick(15, 15)
    blocks = [lower, upper, distant]
    context.update(supported_modes=['ROBOT_GRIP', 'HUMAN_ASSEMBLY'], planning_priority=priority)
    expected = exhaustive_cost(blocks, [base], context)
    checks = []
    original = optimizer.mode_options

    def observed(target, placed, rules):
        checks.append((target, list(placed)))
        return original(target, placed, rules)

    monkeypatch.setattr(optimizer, 'mode_options', observed)
    result = optimizer.plan_assembly({'design_version': 1, 'blocks': [base] + blocks},
                                     {'current_revision': 1, 'blocks': [base]}, context)
    assert expected is not None
    assert result['status'] == 'CANDIDATE'
    assert result['optimization']['cost'] == list(expected)
    assert result['execution_allowed'] is False
    assert not any(target == lower and upper in placed for target, placed in checks)


def test_approved_26_block_reference_fails_before_subset_search():
    data = json.loads((Path(__file__).parent/'fixtures/search_limit_26blocks_20261012.json').read_text())
    result = optimizer.plan_assembly(data['design'], data['current'], data['assembly_context'])
    assert result['status'] == 'NO_FEASIBLE_ORDER'
    assert result['optimization']['expanded_states'] == 0
    assert result['planning_result'] is None
    blocked = result['optimization']['blocked_candidates']
    for target in data['design']['blocks'][:4]:
        assert any(item['block'] == target for item in blocked)


def test_proven_failure_reaches_adapter_with_raw_audit():
    from planning_trial.assembly_adapter import handle_whole_plan
    from planning_trial.assembly_api_fixtures import whole_request
    from planning_trial.assembly_contract import validate_message
    data = json.loads((Path(__file__).parent/'fixtures/search_limit_26blocks_20261012.json').read_text())
    request = whole_request(data['design'], data['current'], data['assembly_context'])
    request['policy']['finish_layers'] = data['assembly_context']['finish_layers']
    audit = {}
    response = handle_whole_plan(request, audit=audit)
    validate_message(response)
    assert response['calculation_status'] == 'NO_FEASIBLE_ORDER'
    assert response['planning_result'] is None
    assert response['action_proposals'] == []
    assert response['execution_allowed'] is False
    assert audit['raw_result']['optimization']['selection'] == 'PROVEN_GRIP_ORDERING_CONFLICT'
    assert audit['raw_result']['optimization']['blocked_candidates']


def test_lazy_search_avoids_unused_siblings_on_40_block_complete_plan(context, monkeypatch):
    blocks = [brick(x, y) for y in range(0, 15, 3) for x in range(0, 24, 3)]
    original = optimizer.mode_options
    checks = []

    def observed(*args):
        checks.append(1)
        return original(*args)

    monkeypatch.setattr(optimizer, 'mode_options', observed)
    result = optimizer.plan_assembly({'design_version': 1, 'blocks': blocks},
                                     {'current_revision': 0, 'blocks': []}, context)
    assert result['status'] == 'CANDIDATE'
    assert len(result['assembly_actions']) == 40
    assert result['optimization']['cost'] == [0, 0, 0]
    assert result['optimization']['feasibility_expanded_states'] == 40
    # 40 checks to find the witness plus independent final replay of every Step.
    assert len(checks) == 80
