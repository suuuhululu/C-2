"""Three local draft A endpoints. D owns active registries and execution approval."""
from collections import Counter
from copy import deepcopy
from uuid import uuid4

from jsonschema import Draft202012Validator

from planning_trial.assembly_contract import schema, validate_message, envelope
from planning_trial.assembly_motion import plan_step_motion
from planning_trial.assembly_optimizer import assess_step, option_cost
from planning_trial.assembly_wire import error, normalize_action, comparable_action
from planning_trial.planner import plan_assembly_from_current, block_key, validate_plan
from planning_trial.assembly_profiles import (IMPLEMENTED_MOTION_MODES, validate_profile_reference, validate_supported_modes,
                                             assessment_input_digest)
from planning_trial.planning_bundle import build_planning_bundle


class AdapterInputError(ValueError):
    """No valid correlation context: return an out-of-band call error, not forged IDs."""
    def __init__(self, reason):
        super().__init__(reason)
        self.payload = {'status': 'INVALID_REQUEST', 'execution_allowed': False,
                        'errors': [error('INVALID_INPUT', reason)]}


def _context(request):
    try:
        Draft202012Validator({'$ref': '#/$defs/Context', '$defs': schema()['$defs']}).validate(request['context'])
    except Exception as exc:
        raise AdapterInputError('Valid D correlation context required') from exc


def _check(request, kind):
    _context(request)
    validate_message(request, kind)
    validate_profile_reference(request['context'], request['frame_profile'])
    validate_supported_modes(request['assembly_context'])
    c = request['context']
    current = request.get('latest_current', request.get('current'))
    if c['input_current_revision'] != current['current_revision']:
        raise ValueError('context.input_current_revision differs from input Current')
    design_version = request.get('design', request.get('plan'))['design_version']
    if c['design_version'] != design_version:
        raise ValueError('context Design version differs from input')
    if kind == 'WholePlanRequest':
        if c['plan_id'] is not None or c['step_id'] is not None:
            raise ValueError('Whole request cannot preassign Plan/Step ID')
    elif c['plan_id'] != request['plan']['plan_id'] or c['step_id'] not in [s['step_id'] for s in request['plan']['steps']]:
        raise ValueError('context Plan/Step differs from input Plan')
    if 'policy' in request:
        a, policy = request['assembly_context'], request['policy']
        if (a['finish_layers'] != policy['finish_layers'] or
                a['geometry']['body_height_mm']/1000 != policy['hand_hold_height_m'] or
                a['hold_gripper_nonintrusion_assumption'] != policy['hold_gripper_nonintrusion_assumption']):
            raise ValueError('Policy differs from assembly_context')


def _finish(result, raw, audit):
    validate_message(result)
    if audit is not None: audit['raw_result'] = deepcopy(raw)
    return result


def handle_whole_plan(request, *, audit=None):
    _context(request)
    out = envelope(request, 'WholePlanResult')
    out.update(candidate_id='candidate-'+uuid4().hex, review_state='CANDIDATE_FOR_D_REVIEW',
               provenance='ACTUAL_A_FUNCTIONS_LOCAL_ADAPTER_NO_D_RECEIPT',
               calculation_status='INVALID_CONTEXT', planning_result=None, action_proposals=[], stage_errors=[],
               shared_planning_bundle=None)
    raw = None
    try:
        _check(request, 'WholePlanRequest')
        raw = plan_assembly_from_current(request['design'], request['current'], request['assembly_context'])
        if raw['planning_result'] is not None:
            out.update(calculation_status='COMPLETED', planning_result=deepcopy(raw['planning_result']))
            if raw['planning_result']['status'] == 'READY':
                plan = raw['planning_result']['plan']
                by_id = {a['step_id']: a for a in raw['assembly_actions']}
                out['action_proposals'] = [normalize_action(by_id[s['step_id']], plan, s, request['assembly_context']) for s in plan['steps']]
                out['shared_planning_bundle'] = build_planning_bundle(request['design'], plan, request['current'],
                    request['assembly_context'], request['frame_profile'])
        else:
            out['calculation_status'] = raw['status']
            out['stage_errors'] = [error(raw['status'], e['reason'], e['block']) for e in raw['errors']]
    except ValueError as exc:
        out.update(calculation_status='INVALID_CONTEXT', planning_result=None, action_proposals=[],
                   shared_planning_bundle=None,
                   stage_errors=[error('INVALID_INPUT', exc, getattr(exc, 'block', None))])
    except Exception as exc:
        out.update(calculation_status='CALCULATION_ERROR', planning_result=None, action_proposals=[],
                   shared_planning_bundle=None,
                   stage_errors=[error('CALCULATION_ERROR', str(exc))])
    return _finish(out, raw, audit)


def _same_blocks(a, b):
    return Counter(map(block_key, a)) == Counter(map(block_key, b))


def handle_step_reassessment(request, *, audit=None):
    _context(request)
    out = envelope(request, 'StepReassessmentResult')
    out.update(assessment_id='assessment-'+uuid4().hex, status='INVALID', action_proposal=None, errors=[],
               assessment_input_digest=None)
    raw = None
    try:
        _check(request, 'StepReassessmentRequest')
        plan, baseline, current = request['plan'], request['plan_base_current'], request['latest_current']
        validate_plan(request['design'], baseline['blocks'], baseline['current_revision'], plan,
                      finish_layers=request['assembly_context']['finish_layers'])
        index = next(i for i, s in enumerate(plan['steps']) if s['step_id'] == request['context']['step_id'])
        step = plan['steps'][index]
        already = block_key(step['after']) in {block_key(b) for b in current['blocks']}
        prefix = baseline['blocks']+[s['after'] for s in plan['steps'][:index+int(already)]]
        expected = request['expected_current_before_step']
        if (not _same_blocks(prefix, current['blocks']) or not _same_blocks(prefix, expected['blocks']) or
                expected['current_revision'] != current['current_revision']):
            out.update(status='BLOCKED', errors=[error('CURRENT_MISMATCH', 'Current does not equal confirmed Plan prefix', step['after'])])
            return _finish(out, raw, audit)
        raw = assess_step(request['design'], plan, step['step_id'], current, request['assembly_context'])
        out['status'] = raw['status']
        if raw['status'] == 'CANDIDATE':
            previous = request['selected_action']
            if previous is not None and previous['mode'] not in request['assembly_context']['supported_modes']:
                code = 'UNSUPPORTED_METHOD' if previous['mode'] not in IMPLEMENTED_MOTION_MODES else 'NO_FEASIBLE_METHOD'
                out.update(status='BLOCKED', errors=[error(code,
                    'Previously selected method is not enabled; request a new supported selection/Plan, no automatic substitution',
                    step['after'])])
                return _finish(out, raw, audit)
            options = [normalize_action(o, plan, step, request['assembly_context'])
                       for o in sorted(raw['options'], key=lambda o: (option_cost(o), o['mode'], o['grip_axis'] or '', o['release_strategy'] or ''))]
            out['action_proposal'] = next((a for a in options if previous is not None and comparable_action(a) == comparable_action(previous)), options[0])
            out['assessment_input_digest'] = assessment_input_digest(request['frame_profile'], request['assembly_context'])
        else:
            if raw['status'] == 'NO_FEASIBLE_METHOD':
                out.update(status='BLOCKED', errors=[error('NO_FEASIBLE_METHOD', raw['assessment']['reason'], step['after'])])
            else:
                out['errors'] = [error('INPUTS_REQUIRED' if raw['status'] == 'INPUTS_REQUIRED' else 'PLAN_NOT_VALID', e['reason'], e['block']) for e in raw['errors']]
    except ValueError as exc:
        out.update(status='INVALID', action_proposal=None, errors=[error('INVALID_INPUT', exc)])
    except Exception as exc:
        out.update(status='BLOCKED', action_proposal=None, errors=[error('CALCULATION_ERROR', exc)])
    return _finish(out, raw, audit)


def handle_step_motion(request, *, audit=None):
    _context(request)
    out = envelope(request, 'StepMotionResult')
    slot = request.get('reserved_supply_slot', {})
    # Invalid reservation identity is a call error, never a fabricated binding.
    keys = ('slot_id', 'reservation_id', 'reservation_generation', 'bound_workflow_generation')
    try:
        binding = {k: slot[k] for k in keys}
        Draft202012Validator({'$ref': '#/$defs/ReservationBinding', '$defs': schema()['$defs']}).validate(binding)
    except Exception as exc:
        raise AdapterInputError('Valid reservation correlation required') from exc
    if not isinstance(request.get('assessment_id'), str) or not request['assessment_id'].strip():
        raise AdapterInputError('Assessment correlation required')
    out.update(assessment_id=request['assessment_id'], reservation_binding=deepcopy(binding),
               status='BLOCKED', motion_proposal=None, errors=[])
    raw = None
    try:
        _check(request, 'StepMotionRequest')
        if request['selected_step'] != next(s for s in request['plan']['steps'] if s['step_id'] == request['context']['step_id']):
            raise ValueError('Selected Step differs from Plan body')
        if request['assessment_current_revision'] != request['latest_current']['current_revision']:
            raise ValueError('Assessment and Current revisions differ')
        for key in request['context']:
            if key != 'request_id' and request['context'][key] != request['assessment_context'][key]:
                raise ValueError('Assessment context differs from motion context: '+key)
        if comparable_action(request['assessed_action']) != comparable_action(request['action_proposal']):
            raise ValueError('Selected action differs from associated assessment record')
        if request['assessment_input_digest'] != assessment_input_digest(request['frame_profile'], request['assembly_context']):
            out['errors'] = [error('FRAME_PROFILE_CHANGED', 'Profile content or assembly_context changed since assessment')]
            return _finish(out, raw, audit)
        if slot['bound_workflow_generation'] != request['context']['workflow_generation']:
            raise ValueError('Slot is bound to a different workflow')
        if request['context']['frame_profile_id'] != request['frame_profile']['profile_id']:
            raise ValueError('Context and profile references differ')
        if request['robot_state']['source_epoch'] != request['context']['source_epoch']:
            raise ValueError('Robot snapshot belongs to another source epoch')
        raw = plan_step_motion(plan=request['plan'], step_id=request['context']['step_id'],
                               latest_current=request['latest_current'], action=request['action_proposal'],
                               supply_slot=slot, robot_state=request['robot_state'],
                               frame_profile=request['frame_profile'], assembly_context=request['assembly_context'])
        out.update(status=raw['status'], motion_proposal=raw['motion_proposal'], errors=raw['errors'])
    except ValueError as exc:
        out['errors'] = [error('REFERENCE_MISMATCH', exc)]
    except Exception as exc:
        out['errors'] = [error('CALCULATION_ERROR', exc)]
    return _finish(out, raw, audit)


def receive_result_for_review(result, active_request):
    """Local consumer fixture only: not Suhyun's D implementation."""
    validate_message(result)
    try:
        validate_message(active_request)
    except ValueError as exc:
        return {'decision': 'REJECT_INVALID_ACTIVE_REQUEST', 'reason': str(exc),
                'execution_allowed': False, 'robot_commands_issued': 0,
                'scope': 'LOCAL_CONSUMER_FIXTURE_NOT_ACTUAL_D'}
    matching = result['context'] == active_request['context']
    if result['message_type'] != active_request['message_type'].replace('Request', 'Result'):
        matching = False
    if 'assessment_id' in active_request:
        matching &= result.get('assessment_id') == active_request['assessment_id']
    if 'reservation_binding' in result:
        keys = ('slot_id', 'reservation_id', 'reservation_generation', 'bound_workflow_generation')
        matching &= result['reservation_binding'] == {k: active_request['reserved_supply_slot'][k] for k in keys}
    return {'decision': 'STORE_FOR_REVIEW' if matching else 'IGNORE_STALE_RESULT',
            'execution_allowed': False, 'robot_commands_issued': 0,
            'scope': 'LOCAL_CONSUMER_FIXTURE_NOT_ACTUAL_D'}
