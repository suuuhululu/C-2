"""Local calculated-output draft derived from immutable v4 review schema."""
from copy import deepcopy
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

VERSION = 'assembly-ad-calculation-draft/0.5'
ROOT = Path(__file__).resolve().parent
V4_SCHEMA = ROOT/'connection_contract_review_20261008_v4/schema.json'


def schema():
    s = json.loads(V4_SCHEMA.read_text())
    defs = s['$defs']
    names = ('WholePlanRequest', 'WholePlanResult', 'StepReassessmentRequest',
             'StepReassessmentResult', 'StepMotionRequest', 'StepMotionResult')
    s['oneOf'] = [{'$ref': '#/$defs/'+name} for name in names]
    for name in names:
        props = defs[name]['properties']
        props['schema_version'] = {'const': VERSION}
        props['sample_kind'] = {'const': 'REVIEW_INPUT_NOT_FOR_EXECUTION' if name.endswith('Request') else
                               'CALCULATED_FROM_REVIEW_INPUT_NOT_FOR_EXECUTION'}
    defs['WholePlanResult']['properties']['review_state'] = {'const': 'CANDIDATE_FOR_D_REVIEW'}
    defs['WholePlanResult']['properties']['provenance'] = {'const': 'ACTUAL_A_FUNCTIONS_LOCAL_ADAPTER_NO_D_RECEIPT'}
    defs['HumanAction']['properties']['access_assessment'] = {'const': 'GEOMETRIC_CANDIDATE_NOT_RUNTIME_VERIFIED'}
    defs['ReviewError']['properties']['code']['enum'] += ['INVALID_INPUT', 'REFERENCE_MISMATCH', 'UNSUPPORTED_METHOD']
    defs['AssemblyContext']['properties']['geometry']['properties']['body_height_mm'] = {'type': 'number', 'exclusiveMinimum': 0}
    defs['Policy']['properties']['hand_hold_height_m'] = {'type': 'number', 'exclusiveMinimum': 0}
    defs['Context']['properties']['frame_profile_version'] = {'type': 'string', 'minLength': 1}
    defs['Context']['required'].append('frame_profile_version')
    defs['AssemblyContext']['properties']['supported_modes'] = {
        'type': 'array', 'minItems': 1, 'uniqueItems': True,
        'items': {'enum': ['ROBOT_GRIP', 'HUMAN_ASSEMBLY']}}
    defs['AssemblyContext']['required'].append('supported_modes')
    # Diagnostic placements may be outside the board; do not erase the offending values.
    for name in ('ReviewError', 'LegacyError'):
        defs[name]['properties']['block'] = {'anyOf': [{'type': 'object'}, {'type': 'null'}]}
    fp = defs['FrameProfile']
    fp['properties']['profile_version'] = {'type': 'string', 'minLength': 1}
    fp['required'].append('profile_version')
    fp['properties']['sample_kind'] = {'enum': ['MEASURED_SOURCE_WITH_UNVERIFIED_EXTENSIONS', 'REVIEW_ONLY']}
    fp['properties']['calculation_profiles'] = {
        'type': 'object', 'properties': {
            'supply': {'type': 'object'}, 'assembly': {'type': 'object'},
            'pickup_approach_clearance_mm': {'type': 'number', 'exclusiveMinimum': 0},
            'tray': {'anyOf': [{'type': 'object'}, {'type': 'null'}]},
        }, 'required': ['supply', 'assembly', 'pickup_approach_clearance_mm', 'tray'],
        'additionalProperties': False}
    fp['required'].append('calculation_profiles')
    for name in ('WholePlanRequest', 'StepReassessmentRequest'):
        defs[name]['properties']['frame_profile'] = {'$ref': '#/$defs/FrameProfile'}
        defs[name]['required'].append('frame_profile')
    digest = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
    defs['StepReassessmentResult']['properties']['assessment_input_digest'] = {
        'anyOf': [digest, {'type': 'null'}]}
    defs['StepReassessmentResult']['required'].append('assessment_input_digest')
    defs['StepReassessmentResult']['allOf'][0]['then']['properties']['assessment_input_digest'] = digest
    defs['StepMotionRequest']['properties']['assessment_input_digest'] = digest
    defs['StepMotionRequest']['required'].append('assessment_input_digest')
    defs['PlanningBundle'] = {
        'type': 'object', 'properties': {
            'bundle_id': {'type': 'string', 'minLength': 1}, 'bundle_digest': digest,
            'bundle_schema': {'const': 'a-b-d-planning-bundle-draft/0.1'},
            'contract_status': {'const': 'DRAFT_NOT_FROZEN'}, 'execution_allowed': {'const': False},
            'current_provenance': {'const': 'B_CONFIRMED_D_RELAYED'},
            'expected_state_kind': {'const': 'PLAN_EXPECTATION_NOT_OBSERVATION'},
            'design': {'$ref': '#/$defs/Design'}, 'plan': {'$ref': '#/$defs/Plan'},
            'plan_base_current': {'$ref': '#/$defs/Current'}, 'profile_snapshot': {'$ref': '#/$defs/FrameProfile'},
            'profile_content_digest': digest, 'geometry': {'type': 'object'},
            'expected_steps': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'step_id': {'type': 'string', 'minLength': 1},
                'before_blocks': {'type': 'array', 'items': {'$ref': '#/$defs/Block'}},
                'after_blocks': {'type': 'array', 'items': {'$ref': '#/$defs/Block'}}},
                'required': ['step_id', 'before_blocks', 'after_blocks'], 'additionalProperties': False}},
            'final_expected_blocks': {'type': 'array', 'items': {'$ref': '#/$defs/Block'}},
            'limits': {'type': 'array', 'items': {'type': 'string'}}},
        'required': ['bundle_id', 'bundle_digest', 'bundle_schema', 'contract_status', 'execution_allowed',
                     'current_provenance', 'expected_state_kind', 'design', 'plan', 'plan_base_current',
                     'profile_snapshot', 'profile_content_digest', 'geometry', 'expected_steps',
                     'final_expected_blocks', 'limits'], 'additionalProperties': False}
    defs['WholePlanResult']['properties']['shared_planning_bundle'] = {
        'anyOf': [{'$ref': '#/$defs/PlanningBundle'}, {'type': 'null'}]}
    defs['WholePlanResult']['required'].append('shared_planning_bundle')
    defs['WholePlanResult']['allOf'].append({
        'if': {'properties': {'calculation_status': {'const': 'COMPLETED'},
                             'planning_result': {'type': 'object', 'properties': {'status': {'const': 'READY'}}}}},
        'then': {'properties': {'shared_planning_bundle': {'$ref': '#/$defs/PlanningBundle'}}},
        'else': {'properties': {'shared_planning_bundle': {'type': 'null'}}}})
    motion = defs['StepMotionRequest']
    del motion['properties']['synthetic_geometry']
    motion['required'].remove('synthetic_geometry')
    motion['properties']['assembly_context'] = {'$ref': '#/$defs/AssemblyContext'}
    motion['properties']['assessed_action'] = {'$ref': '#/$defs/Action'}
    motion['properties']['assessment_context'] = {'$ref': '#/$defs/Context'}
    motion['required'] += ['assembly_context', 'assessed_action', 'assessment_context']
    # assessed_action is the D-associated assessment record, not a new A permission.
    defs['DraftMotion'] = {
        'type': 'object', 'properties': {
            'motion_plan_id': {'type': 'string', 'minLength': 1},
            'motion_scope': {'enum': ['PICK_TRANSPORT_TO_PRE_CONTACT', 'PICK_TRANSPORT_TO_HANDOVER_TRAY']},
            'pickup_tcp_pose': {'$ref': '#/$defs/Pose'},
            'segments': {'type': 'array', 'minItems': 2, 'items': {
                'type': 'object', 'properties': {
                    'stage': {'type': 'string'}, 'waypoints': {'type': 'array', 'items': {'$ref': '#/$defs/Waypoint'}},
                    'gripper_event': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                }, 'required': ['stage', 'waypoints', 'gripper_event'], 'additionalProperties': False}},
            'terminal_gripper_policy': {'const': 'HOLD_NO_AUTOMATIC_OPEN'},
            'handoff_to': {'enum': ['D_CONTACT', 'D_HANDOVER_RELEASE_AND_RETREAT']},
            'assembly_completed': {'const': False},
            'validation': {'type': 'object', 'properties': {
                key: {'const': False} for key in ('ik_verified', 'full_path_collision_verified',
                                                 'physical_grasp_verified', 'd_execution_approved')},
                'required': ['ik_verified', 'full_path_collision_verified', 'physical_grasp_verified', 'd_execution_approved'],
                'additionalProperties': False},
            'limits': {'type': 'array', 'items': {'type': 'string'}},
            'speed_profile_ref': {'type': 'object'},
            'profile_id': {'type': 'string'}, 'current_revision': {'type': 'integer', 'minimum': 0},
            'profile_version': {'type': 'string', 'minLength': 1},
        }, 'required': ['motion_plan_id', 'motion_scope', 'pickup_tcp_pose', 'segments',
                        'terminal_gripper_policy', 'handoff_to', 'assembly_completed', 'validation',
                        'limits', 'speed_profile_ref', 'profile_id', 'profile_version', 'current_revision'], 'additionalProperties': False}
    def swap_refs(value):
        if isinstance(value, dict):
            if value.get('$ref') == '#/$defs/Motion': value['$ref'] = '#/$defs/DraftMotion'
            for child in value.values(): swap_refs(child)
        elif isinstance(value, list):
            for child in value: swap_refs(child)
    swap_refs(defs['StepMotionResult'])
    return s


def validate_message(value, message_type=None):
    def finite(node):
        if isinstance(node, float) and not math.isfinite(node): raise ValueError('Non-finite JSON number')
        if isinstance(node, dict):
            if 'quaternion_xyzw' in node:
                q = node['quaternion_xyzw']
                if (not isinstance(q, list) or len(q) != 4 or
                        any(type(v) not in (int, float) or not math.isfinite(v) for v in q) or
                        abs(sum(v*v for v in q)-1) > 1e-6):
                    raise ValueError('Normalized quaternion_xyzw required')
            for item in node.values(): finite(item)
        elif isinstance(node, list):
            for item in node: finite(item)
    finite(value)
    if message_type and (not isinstance(value, dict) or value.get('message_type') != message_type):
        raise ValueError('Expected '+message_type)
    try:
        contract = schema()
        kind = message_type or (value.get('message_type') if isinstance(value, dict) else None)
        allowed = {r['$ref'].split('/')[-1] for r in contract['oneOf']}
        if kind in allowed:
            contract = {'$ref': '#/$defs/'+kind, '$defs': contract['$defs']}
        Draft202012Validator(contract).validate(value)
    except Exception as exc:
        problem = ValueError('Draft schema mismatch: '+str(exc).split('\n')[0])
        path = list(getattr(exc, 'absolute_path', []))
        if 'blocks' in path:
            index = path.index('blocks')
            if index+1 < len(path) and type(path[index+1]) is int:
                node = value
                for key in path[:index+2]: node = node[key]
                problem.block = deepcopy(node)
        raise problem from exc
    if isinstance(value, dict) and value.get('shared_planning_bundle') is not None:
        from planning_trial.planning_bundle import validate_planning_bundle
        b = validate_planning_bundle(value['shared_planning_bundle'])
        c = value['context']
        if (b['plan'] != value['planning_result']['plan'] or
                b['plan_base_current']['current_revision'] != c['input_current_revision'] or
                b['design']['design_version'] != c['design_version'] or
                b['profile_snapshot']['profile_id'] != c['frame_profile_id'] or
                b['profile_snapshot']['profile_version'] != c['frame_profile_version']):
            raise ValueError('Shared planning bundle references differ from calculation result')
    return value


def envelope(request, result_type):
    return {'schema_version': VERSION, 'contract_status': 'DRAFT_NOT_FROZEN',
            'sample_kind': 'CALCULATED_FROM_REVIEW_INPUT_NOT_FOR_EXECUTION',
            'message_type': result_type, 'context': deepcopy(request['context']),
            'execution_allowed': False}
