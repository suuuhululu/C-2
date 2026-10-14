"""Actual A PR50 examples consumed by D, without a device connection."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.mvp_fake import execution_document
from app.mvp_workflow import MvpWorkflow
from app.release_press_connection import (d_motion, validate_d_motion,
                                          validate_a_message)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads((ROOT / 'planning_trial/fixtures/round2_strategy.examples.json').read_text())['examples']


def profile(messages):
    # Explicit synthetic release/press geometry. No seated pose is adopted as
    # an air-release pose, and this profile cannot authorize REAL execution.
    action = messages['reassessment_result']['action_proposal']
    settings = dict(pickup_pose=[-300., 50., 50., 0., 180., 0.],
        reference_pose=[400., 80., 40., 0., 180., 0.],
        release_pose=[400., 80., 44.5, 0., 180., 0.],
        press_approach_pose=[400., 80., 70., 0., 180., 0.],
        press_start_pose=[400., 80., 61., 0., 180., 0.],
        pickup_width_mm=35., release_width_mm=62., press_width_mm=4.)
    return dict(profile_id='MOCK_RELEASE_PRESS', steps={'mvp/'+action['step_id']: settings})


@pytest.mark.parametrize('example', EXAMPLES, ids=lambda e: e['case_id'])
def test_all_six_actual_A_examples_have_accepted_full_messages(example):
    for message in example['messages'].values():
        validate_a_message(message)


@pytest.mark.parametrize('case', ['release_press', 'release_press_with_hold'])
def test_actual_A_assessment_dispatches_D_without_calling_A_motion(tmp_path, case):
    messages = next(e['messages'] for e in EXAMPLES if e['case_id'] == case)
    request, result = deepcopy(messages['reassessment_request']), deepcopy(messages['reassessment_result'])
    ports = []
    w = MvpWorkflow(lambda port, value: ports.append((port, value)), {}, tmp_path)
    w.job_id = str(uuid4())
    w.generation = request['context']['workflow_generation']
    w.current = deepcopy(request['latest_current'])
    w.approved = deepcopy(request['design'])
    w.bundle = deepcopy(messages['whole_result']['shared_planning_bundle'])
    w.step_inputs = dict(assessment_request=request, frame_profile=request['frame_profile'],
        slot=messages['motion_request']['reserved_supply_slot'],
        robot_state=messages['motion_request']['robot_state'], d_profile=profile(messages))
    outer = str(uuid4())
    w.active = dict(port='a.assess', request=dict(request_id=outer, input=request),
                    generation=w.generation, current_revision=w.current['current_revision'])
    assert w.receive('a.assess', outer, result)
    port, payload = ports[-1]
    assert port == 'd.release_press'
    assert not any(p == 'a.motion' for p, _ in ports)
    assert messages['motion_result']['status'] == 'BLOCKED'
    generated = d_motion(payload['input'], payload['d_profile'])
    assert generated['status'] == 'CANDIDATE' and generated['producer'] == 'D_RELEASE_PRESS_PROFILE'
    before = deepcopy(w.current)
    assert w.receive(port, payload['request_id'], generated)
    assert ports[-1][0] == 'robot.EXECUTE'
    bundle = ports[-1][1]['bundle']
    assert bundle['assessment']['action_proposal'] == result['action_proposal']
    assert bundle['motion_source'] == 'D_PROFILE'
    document = execution_document(bundle, w.execution_id)
    assert document['motion']['execution_allowed'] is False
    assert document['step']['action']['human_actions'] == result['action_proposal']['human_actions']
    assert w.current == before and not w.completed


def test_missing_release_height_does_not_use_fully_seated_pose_as_release():
    messages = next(e['messages'] for e in EXAMPLES if e['case_id'] == 'release_press')
    p = profile(messages)
    del next(iter(p['steps'].values()))['release_pose']
    result = d_motion(messages['motion_request'], p)
    assert result['status'] == 'INPUTS_REQUIRED' and result['motion_proposal'] is None
    assert 'release_pose' in result['errors'][0]['reason']


def test_human_press_does_not_need_a_second_robot_pad_press_profile():
    messages = deepcopy(next(e['messages'] for e in EXAMPLES if e['case_id'] == 'release_press'))
    messages['motion_request']['assessed_action']['assistance_kind'] = 'PRESS_AND_HOLD'
    p = profile(messages);s=next(iter(p['steps'].values()))
    for key in ('press_start_pose', 'press_approach_pose', 'press_width_mm'):
        del s[key]
    assert d_motion(messages['motion_request'],p)['status'] == 'CANDIDATE'


def test_D_profile_reference_does_not_accept_an_A_unsupported_result():
    messages = next(e['messages'] for e in EXAMPLES if e['case_id'] == 'release_press')
    with pytest.raises(ValueError, match='BINDING_MISMATCH'):
        validate_d_motion(messages['motion_result'], messages['motion_request'], profile(messages))
    p = profile(messages); result = d_motion(messages['motion_request'], p)
    p['steps']['mvp/'+messages['reassessment_result']['action_proposal']['step_id']]['release_pose'][2] += 1.
    with pytest.raises(ValueError, match='PROFILE_CHANGED'):
        validate_d_motion(result, messages['motion_request'], p)


def test_actual_A_contract_rejects_inconsistent_strategy_fields():
    message = deepcopy(next(e['messages']['reassessment_result'] for e in EXAMPLES if e['case_id']=='release_press'))
    message['action_proposal']['gripper']['release_strategy']='MINIMAL_OPEN'
    with pytest.raises(ValueError):
        validate_a_message(message)
