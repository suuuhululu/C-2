"""Explicit offline inputs. Not defaults for runtime API or evidence of real state."""
from copy import deepcopy
import json
from pathlib import Path

from planning_trial.assembly_contract import VERSION
from planning_trial.assembly_profiles import IMPLEMENTED_MOTION_MODES
from planning_trial.assembly_target import load_assembly_target_profile
from planning_trial.supply_pick import load_supply_profile

ROOT = Path(__file__).resolve().parent


def frame_profile():
    p = {'profile_id': 'D_FIXTURE_FRAME_PROFILE', 'profile_version': 'fixture-v1',
         'calibration_version': 'USER_ORIGIN_CONFIRMED_20261008',
         'tcp_offset_version': 'GripperDA_v4_228mm_SOURCE',
         'tool_geometry_version': 'LOCAL_STUD_RULE_NOT_FULL_MESH', 'base_frame_id': 'base_link',
         'tcp_frame_id': 'GripperDA_v4_tcp', 'tcp_setting_name': 'GripperDA_v4',
         'pose_unit': 'm', 'orientation': 'quaternion_xyzw',
         'speed_profile': {'profile_id': 'D_PROFILE_REQUIRED', 'version': 'UNCONFIRMED', 'verification': 'UNVERIFIED'},
         'verification': 'UNVERIFIED', 'sample_kind': 'MEASURED_SOURCE_WITH_UNVERIFIED_EXTENSIONS',
         'calculation_profiles': {'supply': load_supply_profile(), 'assembly': load_assembly_target_profile(),
                                  'pickup_approach_clearance_mm': 30, 'tray': None}}
    return p


def brick(x=6, y=6, layer=1, color='blue'):
    return {'brick_type': '2x2x1', 'color': color, 'x': x, 'y': y, 'layer': layer, 'orientation_deg': 0}


def whole_request(design=None, current=None, assembly_context=None, profile=None):
    seed = json.loads((ROOT/'connection_contract_review_20261008_v4/examples/01_robot_grip/01_whole.request.json').read_text())
    seed['schema_version'] = VERSION
    seed['sample_kind'] = 'REVIEW_INPUT_NOT_FOR_EXECUTION'
    seed['design'] = deepcopy(design or {'design_version': 1, 'blocks': [brick(), brick(layer=2)]})
    seed['current'] = deepcopy(current or {'current_revision': 0, 'blocks': []})
    seed['assembly_context'] = deepcopy(assembly_context or json.loads((ROOT/'sample_user_rules_5mm_measured_rev2_inputs.json').read_text())['assembly_context'])
    seed['assembly_context'].setdefault('supported_modes', list(IMPLEMENTED_MOTION_MODES))
    seed['policy']['hand_hold_height_m'] = seed['assembly_context']['geometry']['body_height_mm']/1000
    seed['context']['design_version'] = seed['design']['design_version']
    seed['context']['input_current_revision'] = seed['current']['current_revision']
    seed['frame_profile'] = deepcopy(profile or frame_profile())
    seed['context']['frame_profile_id'] = seed['frame_profile']['profile_id']
    seed['context']['frame_profile_version'] = seed['frame_profile']['profile_version']
    return seed


def reassess_request(whole_input, whole_output, current=None, step_index=0):
    plan = whole_output['planning_result']['plan']
    c = deepcopy(current or whole_input['current'])
    ctx = deepcopy(whole_input['context'])
    ctx.update(request_id=f'fixture-reassess-{step_index}-{c["current_revision"]}',
               input_current_revision=c['current_revision'], plan_id=plan['plan_id'], step_id=plan['steps'][step_index]['step_id'])
    return {'schema_version': VERSION, 'contract_status': 'DRAFT_NOT_FROZEN',
            'sample_kind': 'REVIEW_INPUT_NOT_FOR_EXECUTION', 'message_type': 'StepReassessmentRequest',
            'context': ctx, 'design': deepcopy(whole_input['design']), 'plan': deepcopy(plan),
            'plan_base_current': deepcopy(whole_input['current']), 'expected_current_before_step': deepcopy(c),
            'latest_current': c, 'selected_action': deepcopy(whole_output['action_proposals'][step_index]),
            'policy': deepcopy(whole_input['policy']), 'assembly_context': deepcopy(whole_input['assembly_context']),
            'frame_profile': deepcopy(whole_input['frame_profile'])}


def motion_request(reassessment_input, reassessment_output, profile=None):
    p = deepcopy(profile or frame_profile())
    ctx = deepcopy(reassessment_input['context'])
    ctx.update(request_id='fixture-motion-'+ctx['step_id'], frame_profile_id=p['profile_id'],
               frame_profile_version=p['profile_version'])
    action = deepcopy(reassessment_output['action_proposal'])
    step = next(s for s in reassessment_input['plan']['steps'] if s['step_id'] == ctx['step_id'])
    return {'schema_version': VERSION, 'contract_status': 'DRAFT_NOT_FROZEN',
            'sample_kind': 'REVIEW_INPUT_NOT_FOR_EXECUTION', 'message_type': 'StepMotionRequest', 'context': ctx,
            'plan': deepcopy(reassessment_input['plan']), 'selected_step': deepcopy(step),
            'latest_current': deepcopy(reassessment_input['latest_current']),
            'assessment_id': reassessment_output['assessment_id'],
            'assessment_input_digest': reassessment_output['assessment_input_digest'],
            'assessment_context': deepcopy(reassessment_input['context']),
            'assessment_current_revision': ctx['input_current_revision'], 'action_proposal': action,
            'assessed_action': deepcopy(action), 'assembly_context': deepcopy(reassessment_input['assembly_context']),
            'reserved_supply_slot': {'slot_id': action['block']['color']+'_'+action['block']['brick_type']+'_01',
                                     'slot_index': 1, 'brick_type': action['block']['brick_type'], 'color': action['block']['color'],
                                     'reservation_id': 'fixture-reservation-17', 'reservation_generation': 17,
                                     'bound_workflow_generation': ctx['workflow_generation'], 'state': 'RESERVED',
                                     'part_confirmation': 'CONFIRMED', 'valid_until_ref': 'D_RUNTIME_VALIDITY_REQUIRED'},
            'robot_state': {'source_epoch': ctx['source_epoch'], 'state_sequence': 1,
                            'tcp_frame_id': p['tcp_frame_id'], 'tcp_setting_name': p['tcp_setting_name'],
                            'tcp_pose': {'frame_id': 'base_link', 'xyz_m': [0.3, 0, 0.2], 'quaternion_xyzw': [0, 0, 0, 1]},
                            'stopped_verified': True, 'holding_confirmed': False, 'active_command_count': 0,
                            'pending_command_count': 0, 'stop_observation_ref': 'FIXTURE_NOT_DEVICE',
                            'freshness_policy_ref': 'D_RUNTIME_FRESHNESS_REQUIRED'}, 'frame_profile': p}
