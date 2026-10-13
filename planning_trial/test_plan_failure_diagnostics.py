"""Recorded approved design and current unlimited-hand assistance policy."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess

import pytest
from planning_trial.assembly_api_fixtures import whole_request, reassess_request, motion_request
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment, handle_step_motion
from planning_trial.assembly_contract import validate_message
from planning_trial.assembly_optimizer import plan_assembly, mode_options, validate_candidate

CASE = json.loads((Path(__file__).parent/'fixtures/planning_failure_9a091aa3.json').read_text())


@pytest.fixture(autouse=True)
def no_devices(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Planning diagnostics must not open devices or launch processes')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)


def request():
    return whole_request(deepcopy(CASE['design']), deepcopy(CASE['current']),
                         deepcopy(CASE['assembly_context']), deepcopy(CASE['frame_profile']))


def revised(req):
    req = deepcopy(req)
    req['design']['design_version'] = 2
    req['context']['design_version'] = 2
    for x in (8,14):
        for y in (8,10,12):
            req['design']['blocks'].append(dict(brick_type='2x2x1',color='yellow',x=x,y=y,layer=1,orientation_deg=0))
    return req


def test_recorded_design_completes_without_changing_design_or_current():
    req = request(); before = deepcopy(req); audit = {}
    result = handle_whole_plan(req, audit=audit)
    validate_message(result)
    assert req == before
    assert result['calculation_status'] == 'COMPLETED'
    assert result['planning_result']['status'] == 'READY'
    assert len(result['action_proposals']) == 24 and result['execution_allowed'] is False
    assert audit['raw_result']['optimization']['state_limit_applied'] is False
    assert max(a['human_hands_used'] for a in result['action_proposals']) == 3
    assert all(a['human_hands_used'] == len(a['human_actions']) for a in result['action_proposals'])


def test_required_holds_and_three_hand_actions_are_kept_without_a_cap():
    lower = [b for b in CASE['design']['blocks'] if b['layer'] < 3]
    targets = [b for b in CASE['design']['blocks'] if b['layer']==3 and
               b['brick_type']=='2x3x1' and b['x'] in (8,12,14)]
    for target in targets:
        options, assessment = mode_options(target, lower, CASE['assembly_context'])
        checks = {c['mode']:c for c in assessment['mode_checks']}
        assert checks['ROBOT_GRIP']['enabled'] and checks['HUMAN_ASSEMBLY']['enabled']
        assert checks['ROBOT_RELEASE_PRESS']['enabled'] is False
        assert all(c['human_hand_limit'] is None and c['human_hand_limit_applied'] is False for c in checks.values())
        manual = [o for o in options if o['mode']=='HUMAN_ASSEMBLY']
        assert manual and all(len(o['human_actions']) == 3 for o in manual)
        assert all(sum(a['action']=='HOLD' for a in o['human_actions']) == 2 for o in manual)
        assert assessment['human_access_space_checked'] is False and assessment['robot_ik_full_path_checked'] is False


@pytest.mark.parametrize('revision', [0,4])
def test_revised_design_returns_a_complete_plan_preserving_same_current(revision):
    req = request()
    if revision:
        req['current'] = dict(current_revision=revision,blocks=deepcopy(req['design']['blocks'][:4]))
        req['context']['input_current_revision'] = revision
    saved = deepcopy(req['current'])
    original = handle_whole_plan(req)
    assert original['calculation_status'] == 'COMPLETED'
    amended = revised(req); result = handle_whole_plan(amended)
    validate_message(result)
    assert result['calculation_status']=='COMPLETED' and result['planning_result']['status']=='READY'
    plan = result['planning_result']['plan']
    assert plan['base_current_revision']==revision and len(plan['steps'])==30-len(saved['blocks'])
    assert amended['current']==saved and req['current']==saved and result['execution_allowed'] is False


def test_an_unsupported_floating_design_is_not_turned_into_a_plan():
    req = request()
    req['design']['blocks'] = [dict(brick_type='2x2x1',color='blue',x=0,y=0,layer=2,orientation_deg=0)]
    result = handle_whole_plan(req)
    assert result['planning_result']['status']=='INVALID' and result['planning_result']['plan'] is None
    assert result['action_proposals']==[] and result['execution_allowed'] is False


def test_static_collision_returns_block_and_replayable_failure_state():
    req = request(); req['assembly_context']['obstacles'] = [[152,152,-1,184,184,24]]
    audit = {}; result = handle_whole_plan(req,audit=audit)
    validate_message(result)
    assert result['calculation_status']=='NO_FEASIBLE_ORDER' and result['action_proposals']==[]
    assert result['stage_errors'] and all(e['block'] is not None for e in result['stage_errors'])
    assert 'static obstacle' in result['stage_errors'][0]['reason']
    state = audit['raw_result']['optimization']['diagnostic_state']
    assert len(state['placed_blocks'])+len(state['remaining_blocks'])==24
    assert state['scope']=='ONE_DEEPEST_DEAD_END_NOT_PER_BLOCK_GLOBAL_IMPOSSIBILITY'
    for c in audit['raw_result']['optimization']['blocked_candidates']:
        options, assessment = mode_options(c['block'],state['placed_blocks'],req['assembly_context'])
        assert not options and assessment==c['assessment']
    assert result['execution_allowed'] is False


def test_alternate_help_search_keeps_failure_diagnostics():
    req = request(); req['assembly_context']['obstacles'] = [[152,152,-1,184,184,24]]
    req['assembly_context']['planning_priority'] = 'MIN_HELP_COMPLETE_DESIGN_SEARCH'
    audit = {}; result = handle_whole_plan(req,audit=audit)
    assert result['calculation_status']=='NO_FEASIBLE_ORDER'
    assert audit['raw_result']['optimization']['diagnostic_state'] is not None
    assert result['stage_errors'][0]['block'] is not None


def test_three_hands_pass_whole_reassessment_and_motion_contracts():
    req = request(); whole = handle_whole_plan(req)
    index = next(i for i,a in enumerate(whole['action_proposals']) if a['human_hands_used']==3)
    current = dict(current_revision=index,blocks=[deepcopy(a['block']) for a in whole['action_proposals'][:index]])
    reassessment = reassess_request(req,whole,current=current,step_index=index)
    checked = handle_step_reassessment(reassessment)
    assert checked['status']=='CANDIDATE' and checked['action_proposal']['human_hands_used']==3
    motion = handle_step_motion(motion_request(reassessment,checked,profile=req['frame_profile']))
    assert motion['status']=='CANDIDATE' and motion['execution_allowed'] is False
    for result in [whole,checked,motion]:validate_message(result)


def test_hand_count_consistency_is_still_validated():
    raw = plan_assembly(CASE['design'],CASE['current'],CASE['assembly_context'])
    actions = deepcopy(raw['assembly_actions'])
    action = next(a for a in actions if a['human_hands_used']==3)
    action['human_hands_used']=2
    with pytest.raises(ValueError):
        validate_candidate(CASE['design'],CASE['current'],CASE['assembly_context'],raw['planning_result']['plan'],actions)
