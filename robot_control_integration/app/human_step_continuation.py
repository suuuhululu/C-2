"""Local post-handover timeout continuation; never adopts an unobserved assembly."""
from app.control_driver import execute_step


def validate_next_pickup(previous_plan, previous_session, plan, session):
    binding = dict(execution_id=previous_session['execution_id'],
                   plan_id=previous_plan['plan_id'], step_id=previous_plan['step_id'],
                   key=previous_plan['key'])
    if (session.get('previous_step') != binding or
            session['execution_id'] == previous_session['execution_id'] or
            plan['plan_id'] != previous_plan['plan_id'] or
            plan['step_id'] == previous_plan['step_id'] or
            session.get('allowed_trial_phase') != 'pickup' or
            session.get('requires_confirmed_previous_step') is not False or
            session.get('required_previous_step_observations') != []):
        raise ValueError('EXPLICIT_INDEPENDENT_NEXT_PICKUP_REQUIRED')
    if any(s.get('provenance') not in ('LOCAL_OPERATOR_TRIAL', 'SYNTHETIC')
           for s in (previous_session, session)):
        raise ValueError('NEXT_PICKUP_CHAIN_IS_LOCAL_TRIAL_ONLY')


def execute_next_pickup(raw, previous_session, previous_plan, result, session,
                        connection, plan, profile, confirm, record, **timing):
    validate_next_pickup(previous_plan, previous_session.value, plan, session.value)
    previous_session.check()
    if (result.get('status') != 'HUMAN_ACK_TIMEOUT_CONTINUE' or
            result.get('advance_to_next_step') is not True or
            result.get('execution_id') != previous_session.value['execution_id'] or
            result.get('key') != previous_plan['key'] or
            result.get('assembly_completion') is not False or
            result.get('current_update') is not False):
        raise ValueError('POST_HANDOVER_ACK_TIMEOUT_REQUIRED')
    record('NEXT_STEP_PICKUP_STARTED', dict(previous_step=session.value['previous_step'],
        previous_assembly_observation_pending=True, block=plan['block'],
        assembly_completion=False, current_update=False))
    # execute_step verifies an empty, stopped gripper before any pickup command.
    next_result = execute_step(raw, session, connection, plan, profile, confirm,
                               record, phase='pickup', start_zone='assembly', **timing)
    next_result.update(previous_step=session.value['previous_step'],
                       previous_assembly_observation_pending=True)
    return next_result
