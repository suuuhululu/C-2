"""Assembly classification and A wire handoff; no D trajectory or devices."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment, handle_step_motion
from planning_trial.assembly_api_fixtures import whole_request, reassess_request, motion_request
from planning_trial.assembly_contract import validate_message
from planning_trial.assembly_optimizer import mode_options
from planning_trial.assembly_wire import normalize_action
from planning_trial.round2_release_press import assess_release_press


def reference():
    return json.loads((Path(__file__).parent/'fixtures/round2_release_press.synthetic.json').read_text())


def brick(x=6,y=6,layer=1,kind='2x2x1',color='yellow',angle=0):
    return dict(brick_type=kind,color=color,x=x,y=y,layer=layer,orientation_deg=angle)


def evaluate(data):
    return assess_release_press(data['target'],data['current'],data['assembly_context'])


def request_chain(data):
    req=whole_request(dict(design_version=1,blocks=data['current']['blocks']+[data['target']]),
                      data['current'],data['assembly_context'])
    whole=handle_whole_plan(req)
    return req,whole,reassess_request(req,whole)


def test_full_support_classifies_without_measured_release_geometry():
    data=reference();data['assembly_context']['press_contact_model_confirmed']=False
    before=deepcopy(data);result=evaluate(data)
    assert result['status']=='CANDIDATE' and result['assembly_strategy']=='RELEASE_PRESS'
    assert result['action']['mode']=='ROBOT_GRIP' and result['action']['assistance_kind']=='NONE'
    assert result['assessment']['support_studs']==result['assessment']['total_studs']==4
    assert not result['assessment']['ordinary_grip_available']
    assert not result['assessment']['release_press_motion_checked']
    assert result['execution_allowed'] is result['assembly_completed'] is result['current_update'] is False
    assert data==before
    assert not {'release_pose','stage_envelopes_board_mm','waypoints','grasp_height_mm'} & result.keys()


@pytest.mark.parametrize('kind,color,angle,axis',[
    ('2x2x1','yellow',0,'x'),('2x2x1','blue',0,'x'),
    ('2x3x1','yellow',0,'x'),('2x3x1','yellow',90,'y'),
    ('2x3x1','blue',0,'x'),('2x3x1','blue',90,'y'),
    ('1x2x1','red',0,'y'),('1x2x1','red',90,'x')])
def test_types_and_rotations_preserve_axis_and_support_rules(kind,color,angle,axis):
    data=reference();data['target']=brick(kind=kind,color=color,angle=angle)
    w,d=map(int,kind.split('x')[:2])
    if angle==90:w,d=d,w
    data['current']['blocks']=[brick(4,6),brick(6+w,6),brick(6,4),brick(6,6+d)]
    result=evaluate(data)
    assert result['assembly_strategy']=='RELEASE_PRESS' and result['action']['grip_axis']==axis
    assert result['assessment']['support_studs']==w*d


def test_clear_grip_remains_ordinary():
    data=reference();data['current']=dict(current_revision=0,blocks=[])
    result=evaluate(data)
    assert result['status']=='CANDIDATE' and result['assembly_strategy'] is None
    assert result['action']['mode']=='ROBOT_GRIP' and result['action']['release_strategy']=='MINIMAL_OPEN'


@pytest.mark.parametrize('neighbor_layers',[1,5])
def test_neighbor_height_does_not_become_an_a_release_trajectory_gate(neighbor_layers):
    data=reference();neighbors=data['current']['blocks']
    data['current']['blocks']=[b | {'layer':layer}
                              for layer in range(1,neighbor_layers+1) for b in neighbors]
    assert evaluate(data)['assembly_strategy']=='RELEASE_PRESS'


def test_second_layer_uses_all_studs_in_the_immediate_lower_layer():
    data=reference();data['target']=brick(layer=2);neighbors=data['current']['blocks']
    data['current']['blocks']=[brick()]+neighbors+[b | {'layer':2} for b in neighbors]
    result=evaluate(data)
    assert result['assembly_strategy']=='RELEASE_PRESS'
    assert result['assessment']['support_studs']==result['assessment']['total_studs']==4


def test_partial_support_with_blocked_grip_remains_manual():
    data=reference();data['target']=brick(layer=2);data['assembly_context']['grip_axes']=['x']
    data['current']['blocks']=[brick(6,5),brick(4,6),brick(8,6),brick(4,6,2),brick(8,6,2)]
    result=evaluate(data)
    assert result['assessment']['support_studs']==2
    assert result['assembly_strategy'] is None and result['action']['mode']=='HUMAN_ASSEMBLY'


def test_weak_lower_blocks_keep_hold_with_release_press():
    data=reference();data['target']=brick(layer=3);data['assembly_context']['grip_axes']=['x']
    neighbors=[brick(4,6),brick(8,6)]
    data['current']['blocks']=neighbors+[brick(x,6,2) for x in (3,5,7,9)]+[
        b | {'layer':3} for b in neighbors]
    result=evaluate(data)
    assert result['assembly_strategy']=='RELEASE_PRESS',result
    assert result['action']['assistance_kind']=='HOLD'
    assert len(result['action']['support_targets'])==2
    assert {a['action'] for a in result['action']['human_actions']}=={'HOLD'}


def test_disabled_robot_and_wrong_type_axis_are_not_overridden():
    data=reference();data['assembly_context']['supported_modes']=['HUMAN_ASSEMBLY']
    assert evaluate(data)['action']['mode']=='HUMAN_ASSEMBLY'
    data=reference();data['target']=brick(kind='1x2x1',color='red')
    data['current']['blocks']=[brick(4,6),brick(7,6),brick(6,4),brick(6,8)]
    data['assembly_context']['grip_axes']=['x']
    assert evaluate(data)['action']['mode']=='HUMAN_ASSEMBLY'


def test_target_overlap_and_invalid_current_remain_rejected():
    data=reference();data['assembly_context']['obstacles']=[[100,100,5,108,108,10]]
    assert evaluate(data)['status']=='BLOCKED'
    data=reference();data['current']['blocks']=[brick(4,6,2)]
    assert evaluate(data)['status']=='NEEDS_CORRECTION'
    data=reference();data['current']=None
    assert evaluate(data)['status']=='INVALID'


def test_whole_and_reassessment_return_strategy_without_insertion_route():
    _,whole,req=request_chain(reference());before=deepcopy(req)
    action=whole['action_proposals'][0]
    assert whole['planning_result']['status']=='READY'
    assert action['assembly_strategy']=='RELEASE_PRESS' and action['mode']=='ROBOT_GRIP'
    assert action['gripper']['release_strategy']=='RELEASE_PRESS'
    assert action['robot_force_model']=='NOT_ROBOT_INSERTION'
    assessment=handle_step_reassessment(req)
    assert assessment['action_proposal']['assembly_strategy']=='RELEASE_PRESS' and req==before
    motion=handle_step_motion(motion_request(req,assessment))
    assert motion['status']=='BLOCKED' and motion['motion_proposal'] is None
    assert motion['errors'][0]['code']=='UNSUPPORTED_METHOD'
    for result in (whole,assessment,motion):
        validate_message(result)
        assert not result['execution_allowed']


def test_old_manual_selection_is_reclassified():
    data=reference();_,whole,req=request_chain(data)
    plan=whole['planning_result']['plan'];step=plan['steps'][0]
    options,_=mode_options(data['target'],data['current']['blocks'],data['assembly_context'])
    manual=next(o for o in options if o['mode']=='HUMAN_ASSEMBLY')
    req['selected_action']=normalize_action(manual,plan,step,data['assembly_context'])
    assert handle_step_reassessment(req)['action_proposal']['assembly_strategy']=='RELEASE_PRESS'


@pytest.mark.parametrize('change',['missing_strategy','wrong_strategy','manual_mode','wrong_release'])
def test_wire_rejects_inconsistent_strategy(change):
    _,whole,_=request_chain(reference());action=whole['action_proposals'][0]
    if change=='missing_strategy':action.pop('assembly_strategy')
    elif change=='wrong_strategy':action['assembly_strategy']='UNKNOWN'
    elif change=='manual_mode':action['mode']='HUMAN_ASSEMBLY'
    else:action['gripper']['release_strategy']='MINIMAL_OPEN'
    with pytest.raises(ValueError):validate_message(whole)


def test_input_output_are_independent():
    data=reference();before=deepcopy(data);result=evaluate(data)
    result['action']['contacts']['supported_cells'].clear()
    assert data==before


@pytest.mark.parametrize('case_id',[
    'ordinary_robot','release_press','partial_support_manual',
    'robot_hold','robot_press_and_hold','release_press_with_hold'])
def test_full_handoff_examples_replay_with_matching_contract_and_references(case_id):
    data=json.loads((Path(__file__).parent/'fixtures/round2_strategy.examples.json').read_text())
    case=next(c for c in data['examples'] if c['case_id']==case_id);messages=case['messages']
    assert set(messages)=={'whole_request','whole_result','reassessment_request',
                          'reassessment_result','motion_request','motion_result'}
    for message in messages.values():
        validate_message(message)
        if message['message_type'].endswith('Result'):assert message['execution_allowed'] is False
    whole=handle_whole_plan(messages['whole_request'])
    action=whole['action_proposals'][0]
    assert action.get('assembly_strategy')==case['expected_strategy']
    assert action['assistance_kind']==case['expected_assistance_kind']
    assessment=handle_step_reassessment(messages['reassessment_request'])
    assert assessment['action_proposal']==messages['reassessment_result']['action_proposal']
    assert messages['motion_request']['assessed_action']==assessment['action_proposal']
    assert messages['motion_request']['assessment_id']==messages['reassessment_result']['assessment_id']
    assert messages['motion_request']['assessment_input_digest']==assessment['assessment_input_digest']
    motion=handle_step_motion(messages['motion_request'])
    assert motion['status']==messages['motion_result']['status']
    if case['expected_strategy']:
        assert motion['motion_proposal'] is None and motion['errors'][0]['code']=='UNSUPPORTED_METHOD'
    else:assert motion['motion_proposal'] is not None
