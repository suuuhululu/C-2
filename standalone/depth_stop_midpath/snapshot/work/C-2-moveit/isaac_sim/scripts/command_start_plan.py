"""Explicit SIM command planning start; raw observed snapshot stays immutable.

Saved input validation proves source consistency only. The D caller still
checks its live clock/state and full actual-geometry wire before sending.
"""
from copy import deepcopy
from plan_only import digest, JOINTS, GATES
from prepare_sim_snapshot import SIM_KIND

SCOPE='SIM_VERIFIED_HOLD_JTC_DESIRED_PLANNING_START'


def _command_payload(request,current):
    from d_sim_transport import connection_command_context,settled_fresh_source
    if (request['confirmation_kind']!=SIM_KIND or request['simulation_provenance']['source_kind']!='ISAAC_SIM_SAVED_STATE' or request['phase']!='TRANSPORT' or
            request['transport_boundary']!='POST_GRASP_TO_PRE_CONTACT_POSE' or
            request['mandatory_waypoint_count']!=0 or any(request[k] is not False for k in GATES)):
        raise ValueError('COMMAND_PLANNING_START_ISOLATED_SIM_TRANSPORT_ONLY')
    current=settled_fresh_source(current['refs'],current['source_identity']['source_stamp_s'],request=request)
    context=connection_command_context(current)
    # This mode requires an actually observed controller HOLD reference. Raw
    # observed velocity and unknown acceleration are neither replaced nor used
    # as command derivatives.
    if any(v!=0 for k in ('v_rad_s','a_rad_s2') for v in context['command'][k]):
        raise ValueError('COMMAND_PLANNING_START_VERIFIED_HOLD_REQUIRED')
    return dict(scope=SCOPE,joint_names=list(JOINTS),command=deepcopy(context['command']),
        observed=deepcopy(context['observed']),source_identity=deepcopy(current['source_identity']),
        controller_pvt_ref=deepcopy(context['pvt_ref']),command_initialization_ref=deepcopy(context['init_ref']),
        controller_parameters_digest=digest(context['params']),source_refs=deepcopy(current['refs']),
        observed_request_digest=request['planning_request_digest'],
        snapshot_scope='ORIGINAL_OBSERVED_Q_GRIP_TCP_ATTACHMENT_WORLD_NOT_COMMAND_Q',
        physical_tracking_criterion=None,native_execution_allowed=False)


def attach_controller_command_start(request,current):
    if 'controller_command_start' in request:raise ValueError('NEW_COMMAND_START_REQUEST_REQUIRED')
    result=deepcopy(request);result['controller_command_start']=_command_payload(request,current)
    result['planning_request_digest']=digest({k:v for k,v in result.items() if k!='planning_request_digest'})
    return result


def validate_controller_command_start(request):
    from d_sim_transport import settled_fresh_source
    payload=request['controller_command_start']
    if payload.get('scope')!=SCOPE:raise ValueError('COMMAND_PLANNING_START_SCOPE_UNSUPPORTED')
    original=deepcopy(request);original.pop('controller_command_start');original['planning_request_digest']=digest({k:v for k,v in original.items() if k!='planning_request_digest'})
    current=settled_fresh_source(payload['source_refs'],payload['source_identity']['source_stamp_s'],request=original)
    if payload!=_command_payload(original,current):raise ValueError('COMMAND_PLANNING_START_SOURCE_OR_PVA_CHANGED')
    return deepcopy(payload)


def review_current_controller_start(request,current):
    from d_sim_transport import connection_command_context
    planned=validate_controller_command_start(request);actual=connection_command_context(current)
    if any(actual['command'][k]!=planned['command'][k] for k in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2')) or digest(actual['params'])!=planned['controller_parameters_digest']:
        raise ValueError('PLANNED_CONTROLLER_COMMAND_CHANGED_NEW_PLAN_REQUIRED')
    before=planned['source_identity'];now=current['source_identity']
    if now['source_stamp_s']<before['source_stamp_s'] or now['physics_step_index']<before['physics_step_index']:
        raise ValueError('COMMAND_PLANNING_SOURCE_ORDER_REVERSED')
    return planned
