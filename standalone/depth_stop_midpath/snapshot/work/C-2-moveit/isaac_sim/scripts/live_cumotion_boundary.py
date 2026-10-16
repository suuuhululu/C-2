"""CPU interfaces for obstacle-hold calculation and controller PVT transitions.

No dispatcher, SDK import, ROS client or physical approval. Owner supplies the
existing D record and source clock; absent evidence is never filled with zero.
"""
from copy import deepcopy
import numpy as np
from bounded_sim_evidence import pinned_json
from dynamic_cumotion_inputs import check_control,check_result_context,sealed,verify_seal,number,validate_stopped_state
from plan_only import BINDING,JOINTS,digest,vector,validate_trajectory
from prepare_cpu_model import file_hash
from stop_curve import validate_quintic_limits
import xml.etree.ElementTree as ET
import time


def review_observation_difference(limits,name,error,*,applies_to,error_code='OBSERVED_TRACKING_ERROR'):
    """One explicit comparison, with optional undefined/report-only semantics.

    Missing/null scalars are not implicit opt-outs. This is feedback reporting;
    command/model constraints and source-clock association are separate.
    """
    units=dict(q_tolerance_rad='rad',v_tolerance_rad_s='rad/s',a_tolerance_rad_s2='rad/s^2',max_reference_skew_s='s')
    raw=limits[name];source=deepcopy(limits.get('criteria_sources',{}).get(name,{}))
    if isinstance(raw,dict):source.update(deepcopy(raw));value=source['value']
    else:value=raw
    mode=source.get('check_mode','ENFORCE');category=source.get('source_category','PROJECT_TEST_PARAMETER')
    if source.get('unit',units[name])!=units[name]:raise ValueError('OBSERVATION_CRITERION_UNIT_MISMATCH:'+name)
    measured=number(error)
    if measured<0:raise ValueError('ABSOLUTE_OBSERVATION_DIFFERENCE_REQUIRED')
    if value is None:
        if mode!='REPORT_ONLY' or category!='OFFICIAL_NOT_DEFINED' or not source.get('reference'):
            raise ValueError('EXPLICIT_UNDEFINED_REPORT_ONLY_CRITERION_REQUIRED:'+name)
    else:
        value=number(value)
        if (mode!='ENFORCE' or value<=0 or category not in ('PROJECT_TEST_PARAMETER','ROBOT_OR_CONTROLLER_CONFIGURATION') or
                category=='ROBOT_OR_CONTROLLER_CONFIGURATION' and not source.get('reference')):
            raise ValueError('INVALID_OBSERVATION_CRITERION_SOURCE_OR_MODE:'+name)
        if measured>value:raise ValueError(error_code+':'+name)
    return dict(name=name,value=value,unit=units[name],applies_to=applies_to,source_category=category,
        reference=source.get('reference','Explicit owner-selected project review; not SDK official'),
        runtime_version=source.get('runtime_version','standalone cuMotion1.1.0 / selected native owner'),
        check_mode=mode,raw_absolute_error=measured,criterion_passed=None if value is None else True,
        reason=source.get('reason'),
        sdk_official_observation_value=None,official_status='OFFICIAL_NOT_DEFINED')


def verify_reference_time_association(desired,observed,*,now_s=None):
    """Consume an owner-produced pinned clock/reference association receipt.

    REPORT_ONLY age is not permission to use an unassociated clock/sample.
    Owner must substantiate same source tick or a confirmed held-reference
    interval with actual clock/controller/observation evidence, never a flag
    synthesized from an SDK result. Native consumers still check freshness.
    """
    proof=pinned_json(desired['source_time_association'])
    if proof['scope']!='VERIFIED_CONTROLLER_REFERENCE_OBSERVATION_ASSOCIATION':raise ValueError('VERIFIED_SOURCE_TIME_ASSOCIATION_REQUIRED')
    for key in ('session_id','clock_basis','clock_epoch'):
        if type(desired[key]) is not type(observed[key]) or type(proof[key]) is not type(desired[key]) or desired[key]!=observed[key] or proof[key]!=desired[key]:
            raise ValueError('SOURCE_TIME_ASSOCIATION_IDENTITY_MISMATCH')
    if type(proof['clock_epoch']) is not int or proof['clock_epoch']<0:raise ValueError('SOURCE_CLOCK_EPOCH_REQUIRED')
    if proof['desired_stamp_s']!=number(desired['stamp_s']) or proof['observed_stamp_s']!=number(observed['stamp_s']):
        raise ValueError('SOURCE_TIME_ASSOCIATION_STAMP_MISMATCH')
    for key,value in (('desired',desired),('observed',observed)):
        if proof[key+'_pvt_digest']!=digest({k:vector(value[k],6) for k in ('q_rad','v_rad_s','a_rad_s2')}):
            raise ValueError('SOURCE_TIME_ASSOCIATION_PVT_MISMATCH')
    start=number(proof['valid_from_s']);end=number(proof['valid_until_s'])
    times=[desired['stamp_s'],observed['stamp_s']]+([] if now_s is None else [number(now_s)])
    if now_s is not None and max(desired['stamp_s'],observed['stamp_s'])>now_s:raise ValueError('SOURCE_TIME_ASSOCIATION_FUTURE_SAMPLE')
    if not start<=min(times)<=max(times)<=end:raise ValueError('SOURCE_TIME_ASSOCIATION_EXPIRED')
    method=proof['method']
    if method=='SAME_SOURCE_TICK':
        if any(type(proof[k]) is not int or proof[k]<0 for k in ('source_step','desired_source_step','observed_source_step')) or proof['desired_source_step']!=proof['source_step'] or proof['observed_source_step']!=proof['source_step']:
            raise ValueError('SOURCE_TIME_ASSOCIATION_STEP_MISMATCH')
    elif method!='CONFIRMED_CONTROLLER_HOLD_INTERVAL' or proof.get('reference_held_confirmed') is not True:
        raise ValueError('SOURCE_TIME_ASSOCIATION_METHOD_REQUIRED')
    for key in ('clock','controller_reference','observed_state'):
        evidence=proof['evidence'][key]
        if file_hash(evidence['path'])!=evidence['sha256']:raise ValueError('SOURCE_TIME_ASSOCIATION_EVIDENCE_CHANGED')
    return dict(receipt=deepcopy(desired['source_time_association']),method=method,valid_from_s=start,valid_until_s=end,
        source_clock_verified_by_owner_evidence=True,native_execution_allowed=False)


def verify_owner_state(base,state,control,limits):
    from isaac_sim.real_execution.native_boundary import same_owner,review_stop
    owner=pinned_json(state['owner_evidence'])
    if 'owner_context' in owner:owner=owner['owner_context']
    if not isinstance(owner,dict):raise ValueError('COMPLETE_D_OBSTACLE_HOLD_OWNER_REQUIRED')
    if not isinstance(owner.get('stop_record'),dict):raise ValueError('COMPLETE_D_OBSTACLE_HOLD_OWNER_REQUIRED')
    same_owner(owner,owner)
    if owner['stop_record']['source_kind']!='SIM_OWNER_RECORD' or state['source_kind']!='SIM_SAVED_SNAPSHOT':
        raise ValueError('ACTUAL_SIM_OWNER_RECORD_REQUIRED')
    review=limits['owner_review_limits']
    # The selected owner/controller review defines observed rest. SDK1.1.0
    # defines no universal observed v/a/window; don't add a second fixed cap.
    if owner['stop_record']['stop_reason']=='FRESH_FOREGROUND_CONSERVATIVE_STOP':
        from isaac_sim.real_execution.native_boundary import review_conservative_stop
        review_conservative_stop(owner,review)
    else:
        review_stop(owner,review)
    if ('a_context' in owner and 'reservation_binding' in owner):
        matches=all(owner[k]==base[k] for k in ('a_context','reservation_binding'))
    else:matches=owner['binding']=={k:base[k] for k in BINDING}
    if not matches:raise ValueError('OWNER_COMMON_A_CURRENT_RESERVATION_CHANGED')
    if (any(owner[k]!=control[k] for k in ('session_id','clock_basis','cancel_generation','replan_sequence')) or
            owner['state_sequence']!=state['state_sequence'] or owner['state_stamp_s']!=state['source_stamp_s'] or
            owner['stop_record']['acceleration_method']!=state['acceleration_method'] or
            any(owner[k]!=state[k] for k in ('q_rad','v_rad_s','a_rad_s2'))):
        raise ValueError('OWNER_RAW_STATE_OR_CONTROL_MISMATCH')
    return owner


def map_owner_state(template,owner_ref,control,base,limits):
    """Template carries original grasp/stop sensor proof; D supplies lifecycle.

    No session/goal relabelling: the raw template must already match the owner.
    Counts/reason/derivatives are checked, never synthesized from a goal result.
    """
    state=deepcopy(template);state['owner_evidence']=deepcopy(owner_ref)
    verify_owner_state(base,state,control,limits)
    return sealed(state)


def live_context_checker(base,calculated,limits,owner_provider):
    """Call the real owner at start, SDK/FCL finish and immediately before apply.

    The owner adapter, not this closure or CLI, reads the source clock. Changed
    world/cancel, stale TTL/state, latched stop/failure or drifting q reject.
    """
    if not callable(owner_provider):raise ValueError('LIVE_OWNER_PROVIDER_REQUIRED')
    from online_cumotion_validity import computational_geometry
    computation_only=computational_geometry(limits)
    if computation_only and 'online_validity' not in calculated:
        raise ValueError('COMPUTATION_ONLY_REQUIRES_VERIFIED_ONLINE_SOURCE')
    last=[None];initial=[None];previous_observation=[None];previous_depth=[None]
    def check(phase):
        packet=deepcopy(owner_provider());state=packet['state'];control=packet['control']
        from dynamic_cumotion_inputs import owner_observations,normalize_owner_stop_state
        if owner_observations(limits):
            state=normalize_owner_stop_state(state,limits,base['model_bundle'],packet['_source_packet_evidence'])
            packet['state']=state
        verify_seal(state)
        check_control(control);owner=verify_owner_state(base,state,control,limits);now=number(owner['now_s'])
        if last[0] is not None and now<last[0]:raise ValueError('OWNER_SOURCE_CLOCK_REVERSED')
        advanced=last[0] is None or now>last[0]
        last[0]=now
        dynamic_review=None
        if 'online_validity' in calculated:
            from online_cumotion_validity import check_online_context
            validate_stopped_state(state,control,limits)
            dynamic_review=check_online_context(base,calculated,packet,owner,limits)
            depth=(dynamic_review['latest_frame_seq'],dynamic_review['latest_source_stamp_s'],dynamic_review['latest_bound_digest'])
            if previous_depth[0] is not None:
                old=previous_depth[0]
                if depth[0]<old[0] or depth[1]<old[1] or (depth[0]==old[0] and depth[2]!=old[2]):
                    raise ValueError('ONLINE_DEPTH_REVERSED_OR_SAME_FRAME_REWRITTEN')
            previous_depth[0]=depth
            observation=packet['observation_sequence']
            if type(observation) is not int or observation<0 or (previous_observation[0] is not None and observation<previous_observation[0]):
                raise ValueError('ONLINE_OBSERVATION_SEQUENCE_REVERSED')
            previous_observation[0]=observation
            if initial[0] is None:initial[0]=(now,observation)
            if phase in ('SDK_FINISHED','FINAL_FCL_FINISHED','TRANSITION_FCL_FINISHED','D_APPLY_REVIEW') and (now<=initial[0][0] or observation<=initial[0][1]):
                raise ValueError('ONLINE_CALCULATION_REQUIRES_ADVANCING_PHYSICS_SENSOR_TICKS')
        else:
            check_result_context(calculated,packet['envelope'],control,now_s=now,limits=limits)
        if not 0<=now-state['source_stamp_s']<=limits['max_state_age_s']:raise ValueError('LATEST_OWNER_STATE_EXPIRED')
        drift=max(abs(a-b) for a,b in zip(vector(state['q_rad'],6),calculated['solver_initial_model']['q_rad']))
        from dynamic_cumotion_inputs import owner_observations
        if owner_observations(limits):
            if limits['max_start_drift_rad'] is not None:raise ValueError('OWNER_SELECTED_NULL_START_OBSERVATION_REQUIRED')
            review_observation_difference(limits['owner_review_limits'],'q_tolerance_rad',drift,
                applies_to='LATEST_RAW_OWNER_VS_CALCULATED_Q_REQUIRES_CURRENT_GEOMETRY_FCL')
        elif drift>number(limits['max_start_drift_rad']):raise ValueError('LATEST_OWNER_START_DRIFT')
        preparation=calculated['model_preparation']
        changed=(state['grip_rad']!=preparation['grip_rad'] or state['attachment_tcp_to_block']!=preparation['attachment'])
        if (state['holding_confirmed'] is not True or state['active_command_count']!=0 or state['pending_command_count']!=0 or
                changed and not computation_only):
            raise ValueError('LATEST_HOLD_GRIP_ATTACHMENT_OR_COUNTS_CHANGED')
        geometry_observation=None
        if computation_only:
            from dynamic_cumotion_inputs import held_mask_context
            from sim_utils import rigid
            if (state['grip_rad']!=owner['grip_rad'] or
                    state['attachment_tcp_to_block']!=owner['attachment_tcp_to_block']):
                raise ValueError('COMPUTATION_RAW_GEOMETRY_NOT_CURRENT_OWNER')
            number(state['grip_rad']);rigid(state['attachment_tcp_to_block'])
            if packet['latest_depth_bound']['geometry_context']['held_geometry']!=held_mask_context(base,state)['held_geometry']:
                raise ValueError('CURRENT_HELD_SHAPE_OR_ID_CHANGED')
            import xml.etree.ElementTree as ET
            robot=ET.fromstring(base['model_bundle']['robot_description'])
            for name,q in zip(state['joint_names'],state['q_rad']):
                bound=robot.find(f"joint[@name='{name}']/limit")
                if not float(bound.get('lower'))<=q<=float(bound.get('upper')):raise ValueError('CURRENT_RAW_Q_OUTSIDE_MODEL_LIMITS')
            grip_bound=robot.find("joint[@name='rg2_finger_joint']/limit")
            if not float(grip_bound.get('lower'))<=state['grip_rad']<=float(grip_bound.get('upper')):
                raise ValueError('CURRENT_GRIP_OUTSIDE_MODEL_LIMITS')
            geometry_observation=dict(changed=changed,calculated_grip_rad=preparation['grip_rad'],
                calculated_attachment=deepcopy(preparation['attachment']),observed_grip_rad=state['grip_rad'],
                observed_attachment=deepcopy(state['attachment_tcp_to_block']),
                current_geometry_proof_required=True,apply_allowed=False)
            if phase=='D_APPLY_REVIEW':raise ValueError('CURRENT_GEOMETRY_PROOF_AND_D_FINAL_REVIEW_REQUIRED')
        return dict(phase=phase,source_now_s=now,wall_monotonic_s=time.monotonic(),state_digest=state['digest'],owner_digest=digest(owner),
            owner_evidence=deepcopy(state['owner_evidence']),source_packet_evidence=packet.get('_source_packet_evidence'),
            envelope_digest=packet['envelope']['envelope_digest'],status=('COMPUTATION_ONLY_CURRENT_GEOMETRY_PROOF_REQUIRED'
                if computation_only else 'CONTEXT_MATCHED_NOT_RESUME_APPROVAL'),
            geometry_observation=geometry_observation,current_geometry_proof_required=computation_only,apply_allowed=False,
            owner_provider_called=True,source_clock_advanced=advanced,
            observed=dict(stamp_s=state['source_stamp_s'],**{k:deepcopy(state[k]) for k in ('session_id','clock_basis','q_rad','v_rad_s','a_rad_s2')},
                **({'clock_epoch':owner['clock_epoch']} if 'clock_epoch' in owner else {})),
            desired=packet.get('desired'),
            dynamic_validity=dynamic_review,
            native_execution_allowed=False,hardware_execution_allowed=False)
    return check


def transition_candidate(suffix,desired,observed,*,duration_s,limits,lower,upper):
    """Connect the same-tick controller desired PVT to the SDK rest suffix.

    The bridge starts at desired PVT and ends at the unmodified suffix PVT.
    Observed PVT is compared to the selected tracking criteria and preserved;
    it is neither a fabricated command endpoint nor SDK mathematical rest.
    Caller selects duration. Rejection never increases it or changes limits.
    """
    suffix=validate_trajectory(suffix);duration=number(duration_s)
    if duration<=0 or round(duration*1e9)!=duration*1e9:raise ValueError('POSITIVE_NANOSECOND_TRANSITION_REQUIRED')
    for key in ('session_id','clock_basis'):
        if desired[key]!=observed[key]:raise ValueError('PVT_SESSION_CLOCK_MISMATCH')
    if 'clock_epoch' in desired or 'clock_epoch' in observed:
        if any(type(value.get('clock_epoch')) is not int or value['clock_epoch']<0 for value in (desired,observed)) or desired['clock_epoch']!=observed['clock_epoch']:
            raise ValueError('PVT_CLOCK_EPOCH_MISMATCH')
    criteria=[review_observation_difference(limits,'max_reference_skew_s',abs(number(desired['stamp_s'])-number(observed['stamp_s'])),
        applies_to='DESIRED_VS_OBSERVED_SOURCE_STAMPS',error_code='DESIRED_OBSERVED_PVT_NOT_SAME_TICK')]
    association=verify_reference_time_association(desired,observed) if criteria[0]['check_mode']=='REPORT_ONLY' else None
    errors={}
    fields=(('q_rad','positions_rad','q_tolerance_rad'),('v_rad_s','velocities_rad_s','v_tolerance_rad_s'),('a_rad_s2','accelerations_rad_s2','a_tolerance_rad_s2'))
    first=suffix['points'][0]
    for key,field,tolerance in fields:
        errors[key]=max(abs(a-b) for a,b in zip(vector(desired[key],6),vector(observed[key],6)))
        criteria.append(review_observation_difference(limits,tolerance,errors[key],applies_to='DESIRED_VS_RAW_OBSERVED_'+key,
            error_code='INITIAL_REFERENCE_TRACKING_ERROR'))
    observed_to_suffix=[a-b for a,b in zip(observed['q_rad'],first['positions_rad'])]
    if max(abs(x) for x in first['velocities_rad_s']+first['accelerations_rad_s2'])>1e-6:
        raise ValueError('SDK_SUFFIX_REQUIRES_EXPLICIT_REST_MODEL')
    start=dict(time_from_start_s=0.,**{field:deepcopy(desired[key]) for key,field,_ in fields})
    points=[start]+[dict(p,time_from_start_s=(round(p['time_from_start_s']*1e9)+round(duration*1e9))/1e9) for p in suffix['points']]
    trajectory=dict(joint_names=JOINTS,points=points)
    extrema=validate_quintic_limits(trajectory,lower,upper)
    if max(abs(x) for x in trajectory['points'][-1]['velocities_rad_s'])>1e-6:
        raise ValueError('NONZERO_PRECONTACT_TERMINAL_VELOCITY')
    return dict(scope='CONTROLLER_PVT_TO_SDK_REST_TRANSITION_NOT_PHYSICAL_APPROVAL',trajectory=trajectory,
        trajectory_digest=digest(trajectory),desired=deepcopy(desired),observed=deepcopy(observed),tracking_error=errors,
        suffix_digest=digest(suffix),transition_duration_s=duration,checks=extrema,
        tracking_limits=deepcopy(limits),
        initial_connection=dict(start='EXACT_CONTROLLER_DESIRED_PVT',end='EXACT_SDK_SUFFIX_FIRST_PVT',
            observed_used_as_command_endpoint=False,observed_minus_suffix_q_rad=observed_to_suffix,
            sdk_official_measured_start_tolerance=None,official_status='OFFICIAL_NOT_DEFINED'),
        observation_criteria=criteria,source_time_association=association,
        collision_checked=False,whole_curve_FCL_required=True,
        physical_velocity_definition_verified=False,native_execution_allowed=False,hardware_execution_allowed=False)


def check_transition_fcl(candidate,request,suffix_result,library,expected_sha256,*,context_check):
    """Independent original triangle mesh/stud sampling of the *whole* curve.

    This handles a desired/observed q difference without weakening the standard
    A suffix start check. It is a separate transition receipt for D review.
    """
    from stop_fcl import StopScene,check_stop
    from plan_only import prepare_d_candidate
    before=context_check('TRANSITION_FCL_START')
    if before.get('dynamic_validity') and candidate['trajectory']['points'][-1]['time_from_start_s']>before['dynamic_validity']['max_trajectory_duration_s']:
        raise ValueError('WHOLE_CONNECTION_SUFFIX_EXCEEDS_DYNAMIC_HORIZON')
    prepare_d_candidate(suffix_result,request,{k:request[k] for k in BINDING})
    if digest(suffix_result['planned_trajectory'])!=candidate['suffix_digest']:
        raise ValueError('TRANSITION_SUFFIX_NOT_VALIDATED_SDK_RESULT')
    if digest(candidate['trajectory'])!=candidate['trajectory_digest']:raise ValueError('TRANSITION_CURVE_CHANGED')
    robot=ET.fromstring(request['model_bundle']['robot_description'])
    bounds=[robot.find(f"joint[@name='{name}']/limit") for name in JOINTS]
    lower=[float(b.get('lower')) for b in bounds];upper=[float(b.get('upper')) for b in bounds]
    validate_quintic_limits(candidate['trajectory'],lower,upper)
    observed=vector(candidate['observed']['q_rad'],6)
    if any(not low<=q<=high for q,low,high in zip(observed,lower,upper)):
        raise ValueError('OBSERVED_START_OUTSIDE_ORIGINAL_MODEL_BOUNDS')
    scene=StopScene(request,library,expected_sha256)
    try:
        observed_hit=scene.check(observed)
        result=(dict(success=False,checks=1,reason='RAW_OBSERVED_START_FCL_REJECTED',**observed_hit)
                if observed_hit else check_stop(scene,candidate['trajectory']))
    finally:scene.close()
    prepare_d_candidate(suffix_result,request,{k:request[k] for k in BINDING})
    if file_hash(library)!=expected_sha256:raise ValueError('TRANSITION_FCL_LIBRARY_CHANGED')
    after=context_check('TRANSITION_FCL_FINISHED')
    return dict(scope='WHOLE_TRANSITION_AND_SUFFIX_FCL_NOT_D_APPROVAL',success=result['success'],FCL=result,
        owner_context_checks=[before,after],
        observed_start_FCL=dict(q_rad=deepcopy(observed),collision=observed_hit,checked=True),
        trajectory_digest=candidate['trajectory_digest'],request_digest=request['planning_request_digest'],
        model_digest=request['model_digest'],binding={k:request[k] for k in BINDING},
        library_sha256=expected_sha256,native_execution_allowed=False,hardware_execution_allowed=False)


def review_transition(candidate,receipt,request,context_check,*,expected_library_sha256):
    """D calls again immediately before apply; this function never dispatches."""
    if (receipt['scope']!='WHOLE_TRANSITION_AND_SUFFIX_FCL_NOT_D_APPROVAL' or receipt['success'] is not True or
            receipt['library_sha256']!=expected_library_sha256 or receipt['FCL']['success'] is not True or receipt['FCL']['checks']<=0 or
            receipt['trajectory_digest']!=digest(candidate['trajectory']) or
            receipt['request_digest']!=request['planning_request_digest'] or receipt['model_digest']!=request['model_digest'] or
            receipt['binding']!={k:request[k] for k in BINDING}):raise ValueError('WHOLE_CURVE_FRESH_FCL_RECEIPT_REQUIRED')
    current=context_check('D_APPLY_REVIEW')
    if current.get('current_geometry_proof_required'):
        raise ValueError('CURRENT_GEOMETRY_PROOF_AND_D_FINAL_REVIEW_REQUIRED')
    desired=current.get('desired')
    if desired is None:raise ValueError('CURRENT_CONTROLLER_REFERENCE_REQUIRED_AT_APPLY')
    criteria=[review_observation_difference(candidate['tracking_limits'],'max_reference_skew_s',abs(number(current['source_now_s'])-number(desired['stamp_s'])),
        applies_to='CURRENT_REFERENCE_SOURCE_AGE',error_code='APPLY_CONTROLLER_REFERENCE_EXPIRED')]
    if criteria[0]['check_mode']=='REPORT_ONLY':
        observed=deepcopy(current['observed'])
        if 'original_owner' in current:
            owner=current['original_owner']
            for key in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2'):
                if key in observed and observed[key]!=owner[key]:raise ValueError('APPLY_SOURCE_OWNER_OBSERVATION_MISMATCH')
                observed[key]=deepcopy(owner[key])
            if 'stamp_s' in observed and observed['stamp_s']!=owner['state_stamp_s']:raise ValueError('APPLY_SOURCE_OWNER_STAMP_MISMATCH')
            observed['stamp_s']=owner['state_stamp_s']
        verify_reference_time_association(desired,observed,now_s=current['source_now_s'])
    if any(desired[k]!=candidate['desired'][k] for k in ('session_id','clock_basis','q_rad','v_rad_s','a_rad_s2')):
        raise ValueError('CONTROLLER_REFERENCE_CHANGED_REBUILD_TRANSITION')
    if 'clock_epoch' in candidate['desired'] and desired.get('clock_epoch')!=candidate['desired']['clock_epoch']:
        raise ValueError('CONTROLLER_REFERENCE_EPOCH_CHANGED')
    for key,unit in (('q_rad','q_tolerance_rad'),('v_rad_s','v_tolerance_rad_s'),('a_rad_s2','a_tolerance_rad_s2')):
        error=max(abs(a-b) for a,b in zip(vector(current['observed'][key],6),vector(desired[key],6)))
        criteria.append(review_observation_difference(candidate['tracking_limits'],unit,error,applies_to='APPLY_DESIRED_VS_RAW_OBSERVED_'+key,
            error_code='APPLY_TRACKING_ERROR'))
    return dict(status='FULL_CURVE_VALIDATED_D_PHYSICAL_REVIEW_REQUIRED',context=current,
        trajectory=candidate['trajectory'],desired=candidate['desired'],observed=candidate['observed'],
        observation_criteria=criteria,
        dispatch_intent=None,native_execution_allowed=False,hardware_execution_allowed=False)
