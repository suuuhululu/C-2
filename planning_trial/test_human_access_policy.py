"""User-excluded hand access checks and layer-first current workflow; no devices."""
from copy import deepcopy
import json
from pathlib import Path

from planning_trial import assembly_geometry as geometry
from planning_trial.assembly_api_fixtures import whole_request, reassess_request
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment
from planning_trial.assembly_optimizer import validate_candidate


def reference():
    return json.loads((Path(__file__).parent/'fixtures/search_limit_26blocks_20261012.json').read_text())


def test_human_hold_place_and_press_never_call_spatial_checks(monkeypatch):
    data = reference()
    context = data['assembly_context']
    target = data['design']['blocks'][0]
    context['obstacles'] = [[0, 0, 0, 1000, 1000, 1000]]

    def forbidden(*args, **kwargs):
        raise AssertionError('Human help must not call a spatial-clearance check')

    monkeypatch.setattr(geometry, 'free_boxes', forbidden)
    monkeypatch.setattr(geometry, 'intersects', forbidden)
    held = geometry.hand_options(target, [], context)
    placed = geometry.hand_options(target, [], context, assembly=True)
    pressed = geometry.human_press_options(target, [], context,
                                           {'supported_cells': [[target['x'], target['y']]]}, [])
    supported = geometry.support_assignments([{'block': target}], target, [], context,
                                              [(0, 0, 0, 1000, 1000, 1000)])
    assert held and placed and pressed and supported
    assert all(h['access_assessment'] == 'HUMAN_ACCESS_NOT_CHECKED'
               and h['boxes'] == [] for h in held + placed + pressed + supported[0])


def test_current_workflow_defaults_to_complete_lower_layers():
    request = whole_request()
    assert request['assembly_context']['finish_layers'] is True
    assert request['policy']['finish_layers'] is True
    assert request['policy']['hand_clearance_pitch_per_side'] is None


def test_approved_26_blocks_complete_with_human_help_and_lower_layers():
    data = reference()
    data['assembly_context'].update(supported_modes=['ROBOT_GRIP', 'HUMAN_ASSEMBLY'],
                                    finish_layers=True)
    before = deepcopy(data)
    audit = {}
    request = whole_request(data['design'], data['current'], data['assembly_context'])
    result = handle_whole_plan(request, audit=audit)
    assert result['calculation_status'] == 'COMPLETED'
    assert result['execution_allowed'] is False
    actions = result['action_proposals']
    assert len(actions) == 26
    layers = [a['block']['layer'] for a in actions]
    assert layers == sorted(layers)
    assert any(a['mode'] == 'HUMAN_ASSEMBLY' for a in actions)
    assert all(h['access_assessment'] == 'HUMAN_ACCESS_NOT_CHECKED'
               for a in actions for h in a['human_actions'])
    assert all(a['human_hands_used'] == len(a['human_actions']) for a in actions)
    raw = audit['raw_result']
    assert validate_candidate(data['design'], data['current'], data['assembly_context'],
                              raw['planning_result']['plan'], raw['assembly_actions']) == raw['optimization']['cost']
    manual_index = next(i for i, a in enumerate(actions) if a['mode'] == 'HUMAN_ASSEMBLY')
    current = {'current_revision': manual_index,
               'blocks': [a['block'] for a in actions[:manual_index]]}
    step_request = reassess_request(request, result, current=current, step_index=manual_index)
    step_result = handle_step_reassessment(step_request)
    assert step_result['status'] == 'CANDIDATE'
    assert step_result['execution_allowed'] is False
    assert step_result['action_proposal']['mode'] == 'HUMAN_ASSEMBLY'
    assert all(h['access_assessment'] == 'HUMAN_ACCESS_NOT_CHECKED'
               for h in step_result['action_proposal']['human_actions'])
    assert data == before
