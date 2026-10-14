"""Consume A PR50's strategy and refer to D-owned release/press profiles."""
from copy import deepcopy
from hashlib import sha256
import json
import math
from uuid import uuid4

from jsonschema import Draft202012Validator
from planning_trial.assembly_contract import schema, validate_message, VERSION as A_VERSION


VERSION = 'assembly-ad-calculation-draft/0.5.2'
PRODUCER = 'D_RELEASE_PRESS_PROFILE'


def release_press(action):
    return action.get('mode') == 'ROBOT_GRIP' and action.get('assembly_strategy') == 'RELEASE_PRESS'


def validate_a_message(message):
    if message.get('schema_version') == A_VERSION:
        return validate_message(message)
    if message.get('schema_version') not in (VERSION, 'assembly-ad-calculation-draft/0.5.1'):
        return validate_message(message)
    document = schema()
    for name in ('WholePlanRequest', 'WholePlanResult', 'StepReassessmentRequest',
                 'StepReassessmentResult', 'StepMotionRequest', 'StepMotionResult'):
        document['$defs'][name]['properties']['schema_version'] = {'const': message['schema_version']}
    errors = list(Draft202012Validator(document).iter_errors(message))
    if errors:
        raise ValueError('A message does not match the versioned contract: ' + errors[0].message)
    actions = message.get('action_proposals', []) + ([message['action_proposal']]
               if isinstance(message.get('action_proposal'), dict) else [])
    for value in actions:
        if value.get('assembly_strategy') == 'RELEASE_PRESS' and (
                value['mode'] != 'ROBOT_GRIP' or value['gripper']['release_strategy'] != 'RELEASE_PRESS'):
            raise ValueError('A_RELEASE_PRESS_FIELDS_DISAGREE')


def review_a_result(result, request):
    validate_a_message(result)
    validate_a_message(request)
    matches = (result['schema_version'] == request['schema_version'] and
               result['context'] == request['context'] and
               result['message_type'] == request['message_type'].replace('Request', 'Result'))
    if 'assessment_id' in request:
        matches = matches and result.get('assessment_id') == request['assessment_id']
    if 'reservation_binding' in result:
        keys = ('slot_id', 'reservation_id', 'reservation_generation', 'bound_workflow_generation')
        matches = matches and result['reservation_binding'] == {
            key: request['reserved_supply_slot'][key] for key in keys}
    return {'decision': 'STORE_FOR_REVIEW' if matches else 'IGNORE_STALE_RESULT'}


def profile_digest(profile):
    return sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False,
                             allow_nan=False).encode()).hexdigest()


def d_motion(request, profile):
    """Build a D profile reference, never fabricate an A StepMotion response."""
    action = request['assessed_action']
    if not release_press(action):
        raise ValueError('D_RELEASE_PRESS_ACTION_REQUIRED')
    key = 'mvp/' + action['step_id']
    settings = profile['steps'].get(key, {})
    missing = []
    robot_press = action.get('assistance_kind') not in ('PRESS', 'PRESS_AND_HOLD')
    poses = ['pickup_pose', 'reference_pose', 'release_pose']
    widths = ['pickup_width_mm', 'release_width_mm']
    if robot_press:
        poses += ['press_start_pose', 'press_approach_pose']
        widths += ['press_width_mm']
    for name in poses:
        value = settings.get(name)
        if (not isinstance(value, list) or len(value) != 6 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
            missing.append(name)
    for name in widths:
        if type(settings.get(name)) not in (int, float) or not math.isfinite(settings[name]):
            missing.append(name)
    result = dict(message_type='DReleasePressMotionResult', schema_version='d-release-press-motion/1',
                  producer=PRODUCER, status='INPUTS_REQUIRED' if missing else 'CANDIDATE',
                  execution_allowed=False, context=deepcopy(request['context']),
                  assessment_id=request['assessment_id'], motion_proposal=None,
                  errors=[dict(code='D_RELEASE_PRESS_PROFILE_INCOMPLETE', reason=', '.join(missing))] if missing else [])
    if not missing:
        result['motion_proposal'] = dict(motion_plan_id=str(uuid4()),
            motion_scope='D_PICK_TRANSPORT_RELEASE_PRESS', profile_id=profile['profile_id'],
            profile_digest=profile_digest(profile), d_profile_key=key)
    return result


def validate_d_motion(result, request, profile):
    if (result.get('producer') != PRODUCER or result.get('execution_allowed') is not False or
            result.get('message_type') != 'DReleasePressMotionResult' or
            result.get('schema_version') != 'd-release-press-motion/1' or
            result.get('context') != request['context'] or result.get('assessment_id') != request['assessment_id']):
        raise ValueError('D_RELEASE_PRESS_MOTION_BINDING_MISMATCH')
    proposal = result.get('motion_proposal') or {}
    if result.get('status') == 'CANDIDATE' and (
            result.get('errors') or proposal.get('motion_scope') != 'D_PICK_TRANSPORT_RELEASE_PRESS' or
            not proposal.get('motion_plan_id') or
            proposal.get('profile_id') != profile['profile_id'] or
            proposal.get('profile_digest') != profile_digest(profile) or
            proposal.get('d_profile_key') != 'mvp/' + request['assessed_action']['step_id']):
        raise ValueError('D_RELEASE_PRESS_PROFILE_CHANGED')
