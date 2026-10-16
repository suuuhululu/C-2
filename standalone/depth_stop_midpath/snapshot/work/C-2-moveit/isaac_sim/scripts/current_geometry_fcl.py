"""Separate latest-shape whole-command FCL evidence. Never dispatch or resume.

Calculation files stay immutable. A complete independently pinned owner/world
snapshot is required; missing objects never fall back to calculated poses.
"""
from copy import deepcopy
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import numpy as np
import yaml
from prepare_cpu_model import file_hash,read_model_bundle
from plan_only import BINDING,digest,prepare_d_candidate,validate_trajectory,vector,checked_pose
from prepare_gpu_scene import tcp_fk
from sim_utils import rigid,pose_matrix,error,matrix_pose
from stop_curve import validate_quintic_limits
from stop_fcl import StopScene,check_stop
from bounded_sim_evidence import pinned_json
from held_geometry_inputs import nominal_definition

ARCHIVE='ARCHIVED_SAME_SOURCE_GEOMETRY_FCL_NOT_LIVE'
LIVE='LIVE_CURRENT_GEOMETRY_FCL_CANDIDATE_NOT_D_APPROVAL'
CODEC='ROS2_FLOAT64_PVA_ROUND_SECONDS_TO_NS_IMMEDIATE_EXACT_NUMERIC_V1'


def pin(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=file_hash(path))


def exact_encoded_command(original,wire):
    """Only a representation change. A single changed time needs new curve FCL."""
    fields={'positions_rad','velocities_rad_s','accelerations_rad_s2','time_from_start_s'}
    for curve in (original,wire):
        if set(curve)!={'joint_names','points'}:raise ValueError('EXACT_WIRE_FIELDS_REQUIRED')
        for point in curve['points']:
            if set(point)!=fields:raise ValueError('COMPLETE_WIRE_PVA_TIME_REQUIRED')
            for key in fields:
                values=[point[key]] if key=='time_from_start_s' else point[key]
                if any(type(v) not in (int,float) or not np.isfinite(v) for v in values):
                    raise ValueError('FINITE_NUMERIC_WIRE_NO_BOOL_REQUIRED')
        validate_trajectory(curve)
    if original['joint_names']!=wire['joint_names'] or len(original['points'])!=len(wire['points']):
        raise ValueError('ENCODED_JOINT_OR_POINT_ORDER_CHANGED')
    ns=[]
    for source,actual in zip(original['points'],wire['points']):
        ticks=round(source['time_from_start_s']*10**9)
        if not 0<=ticks<2**31*10**9 or ns and ticks<=ns[-1]:raise ValueError('NATIVE_NS_RANGE_OR_ORDER_CHANGED')
        if (ticks-1)/1e9==ticks/1e9 or (ticks+1)/1e9==ticks/1e9:
            raise ValueError('NATIVE_NS_NOT_UNIQUE_REQUIRE_RAW_DURATION_NEW_PROOF')
        if source['time_from_start_s']!=ticks/1e9 or actual['time_from_start_s']!=ticks/1e9:
            raise ValueError('TIME_QUANTIZATION_CHANGED_CURVE_NEW_CANDIDATE_LIMITS_FULL_FCL_REQUIRED')
        for key in fields-{'time_from_start_s'}:
            if any(type(v) is not float for v in actual[key]) or actual[key]!=source[key]:
                raise ValueError('ENCODED_FLOAT64_PVA_CHANGED')
        if type(actual['time_from_start_s']) is not float:raise ValueError('ENCODED_SECONDS_DOUBLE_REQUIRED')
        ns.append(ticks)
    return dict(codec=CODEC,original_command_digest=digest(original),encoded_command_digest=digest(wire),
        numeric_PVA_time_exact=True,time_quantization_max_error_s=0.,point_count=len(ns),integer_ns_digest=digest(ns),
        changed_curve_reuse_allowed=False)


def review_encoding_delivery(delivery_ref,wire_ref,snapshot):
    delivery=pinned_json(delivery_ref);owner=pinned_json(snapshot['owner'])
    if (delivery['schema']!='exact-encoded-command-delivery/0.1' or delivery['scope']!=snapshot['scope'] or
            delivery['command']!=wire_ref or delivery['raw_owner']!=snapshot['owner'] or
            type(delivery['wire_header_stamp_ns']) is not int or delivery['wire_header_stamp_ns']!=0 or
            type(delivery['next_goal_version']) is not int or delivery['next_goal_version']!=owner['goal_version']+1):
        raise ValueError('ENCODING_DELIVERY_OWNER_HEADER_VERSION_CHANGED')
    if not delivery['source_pins']:raise ValueError('ACTUAL_ENCODING_SOURCE_PINS_REQUIRED')
    for ref in delivery['source_pins'].values():
        if pin(ref['path'])!=ref:raise ValueError('ENCODING_SOURCE_CHANGED')
    if snapshot['scope']==LIVE:
        from isaac_sim.real_execution.native_boundary import LIVE_IDENTITY
        from uuid import UUID
        if delivery['selected_job']!=snapshot['selected_job']:raise ValueError('ENCODING_SELECTED_JOB_CHANGED')
        job=pinned_json(delivery['selected_job']);reservation=pinned_json(delivery['D_reservation'])
        identity={k:owner[k] for k in LIVE_IDENTITY}
        if (job['identity']!=identity or reservation['identity']!=identity or reservation['single_writer']!='D' or
                reservation['scope']!='D_SERIALIZED_NATIVE_RESERVATION_NOT_SEND' or reservation['native_send_called'] is not False or
                reservation['old_owner_digest']!=digest(owner) or reservation['command_digest']!=digest(pinned_json(wire_ref)) or
                any(reservation[k]!=delivery[k] for k in ('wire_header_stamp_ns','next_goal_version','new_goal_id')) or
                UUID(delivery['new_goal_id']).hex==UUID(owner['goal_id']).hex):
            raise ValueError('ENCODING_D_RESERVED_NEW_GOAL_CHANGED')
    elif delivery['selected_job'] is not None or delivery['D_reservation'] is not None or delivery['new_goal_id'] is not None:
        raise ValueError('ARCHIVE_MUST_NOT_INVENT_LIVE_JOB_OR_RESERVATION')
    return delivery


def encoded_calculation(files):
    receipt=pinned_json(files['command_encoding']);original_files=receipt['original_files']
    if 'command_encoding' in original_files:raise ValueError('ENCODING_CHAIN_NOT_SUPPORTED')
    if (receipt['codec']!=CODEC or receipt['encoded_command']!=files['command'] or
            {k:v for k,v in files.items() if k not in ('command','command_encoding')}!=
            {k:v for k,v in original_files.items() if k!='command'}):
        raise ValueError('ENCODING_CALCULATION_FILES_CHANGED')
    request,candidate,original=load_calculation(original_files)
    wire=pinned_json(files['command']);equality=exact_encoded_command(original,wire)
    if equality!=receipt['equivalence']:raise ValueError('ENCODING_EQUIVALENCE_CHANGED')
    source=pinned_json(receipt['original_geometry_proof'])
    if source['calculation_files']!=original_files:raise ValueError('ENCODING_ORIGINAL_GEOMETRY_PROOF_CHANGED')
    review_encoding_delivery(receipt['delivery'],files['command'],source['snapshot'])
    return request,candidate,wire


def load_calculation(files):
    if 'command_encoding' in files:return encoded_calculation(files)
    report=pinned_json(files['report'])
    from cumotion_timing import ENGINE
    from cumotion_pose_engine import ENGINE as POSE_ENGINE,check_spec
    from cumotion_cspace_engine import ENGINE as CSPACE_ENGINE,check_spec as check_cspace_spec
    pose_engine=report['engine'] in (POSE_ENGINE,CSPACE_ENGINE)
    if pose_engine:
        expected_status=('POSE_ENGINE_ORIGINAL_FCL_VERIFIED_PENDING_CURRENT_AND_ENCODING' if report['engine']==POSE_ENGINE else 'CSPACE_ENGINE_ORIGINAL_FCL_VERIFIED_PENDING_CURRENT_AND_ENCODING')
        if report['status']!=expected_status:
            raise ValueError('POSE_ENGINE_ORIGINAL_FCL_RECEIPT_REQUIRED')
        (check_spec if report['engine']==POSE_ENGINE else check_cspace_spec)(report['engine_spec'])
    elif report['status']!='CUMOTION_CALCULATION_FCL_VERIFIED' or report['engine']!=ENGINE:
        raise ValueError('ORIGINAL_CUMOTION_FCL_RECEIPT_REQUIRED')
    for key,ref in report['artifacts'].items():
        if file_hash(Path(ref['path']))!=ref['sha256']:raise ValueError('CALCULATION_ARTIFACT_CHANGED:'+key)
    request_ref=report['artifacts']['request']
    request=yaml.safe_load(Path(request_ref['path']).read_text())
    result=yaml.safe_load(Path(report['artifacts']['fcl_result']['path']).read_text())
    prepare_d_candidate(result,request,{k:request[k] for k in BINDING})
    if read_model_bundle(request['model_bundle']['bundle_path'])!=request['model_bundle']:
        raise ValueError('ORIGINAL_MODEL_CHANGED')
    candidate=pinned_json(files['candidate']);wire=pinned_json(files['command'])
    trajectory=validate_trajectory(candidate['trajectory'])
    if wire!=trajectory or candidate['trajectory_digest']!=digest(trajectory):raise ValueError('WHOLE_COMMAND_NOT_CANDIDATE')
    if pose_engine:
        from cumotion_axis_gate import certify_axis
        from prepare_cumotion_model import TCP
        certify_axis(trajectory,request['model_bundle']['robot_description'],TCP,checked_pose(request['planning_snapshot']['tcp_pose'])[:3,2].tolist())
    suffix=result['planned_trajectory']
    if candidate['suffix_digest']!=digest(suffix):raise ValueError('ORIGINAL_SUFFIX_CHANGED')
    if len(trajectory['points'])!=len(suffix['points'])+1:raise ValueError('COMPLETE_CONNECTION_SUFFIX_REQUIRED')
    duration=candidate['transition_duration_s']
    for actual,source in zip(trajectory['points'][1:],suffix['points']):
        expected=dict(source,time_from_start_s=(round(source['time_from_start_s']*1e9)+round(duration*1e9))/1e9)
        if actual!=expected:raise ValueError('COMMAND_CHANGED_ORIGINAL_SUFFIX')
    for key,field in [('q_rad','positions_rad'),('v_rad_s','velocities_rad_s'),('a_rad_s2','accelerations_rad_s2')]:
        if trajectory['points'][0][field]!=candidate['desired'][key]:raise ValueError('COMMAND_NOT_ORIGINAL_DESIRED_PVT')
    if pin(files['fcl_binary']['path'])!=files['fcl_binary'] or report['fcl_binary_sha256']!=files['fcl_binary']['sha256']:
        raise ValueError('OWNER_SELECTED_FCL_BINARY_CHANGED')
    if pin(files['fcl_library']['path'])!=files['fcl_library']:raise ValueError('OWNER_SELECTED_FCL_LIBRARY_CHANGED')
    return request,candidate,trajectory


def _review_snapshot(snapshot,request,candidate,duration,*,metadata_only=False):
    if snapshot['schema']!='current-geometry-fcl-input/0.1' or snapshot['scope'] not in (ARCHIVE,LIVE):
        raise ValueError('EXPLICIT_CURRENT_GEOMETRY_SOURCE_REQUIRED')
    owner=pinned_json(snapshot['owner']);world=pinned_json(snapshot['world'])
    for ref in snapshot['source_pins'].values():
        if pin(ref['path'])!=ref:raise ValueError('CURRENT_GEOMETRY_SOURCE_PIN_CHANGED')
    if not snapshot['source_pins']:raise ValueError('INDEPENDENT_GEOMETRY_SOURCE_PINS_REQUIRED')
    if (world['schema']!='same-source-full-world-inventory/0.1' or world['owner']!=snapshot['owner'] or
            world['source_stamp_s']!=owner['state_stamp_s'] or world['objects']!=owner['world_objects']):
        raise ValueError('WORLD_NOT_SAME_SOURCE_OWNER')
    if (owner['model_manifest_sha256']!=request['model_bundle']['manifest_sha256'] or
            owner['selected_block_id']!=request['planning_snapshot']['selected_slot_id'] or
            owner['current_revision']!=request['current_revision']):raise ValueError('CURRENT_MODEL_CURRENT_OR_HELD_CHANGED')
    if owner['single_writer']!='D' or any(owner[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):
        raise ValueError('CURRENT_STOP_FAILURE_UNKNOWN')
    if any(type(owner[k]) is not int or owner[k]!=0 for k in ('active_command_count','pending_command_count','pending_cancel_count')):
        raise ValueError('CURRENT_COMMANDS_PENDING')
    if not {'rg2_left_inner_finger','rg2_right_inner_finger'}<=set(owner['contact_fingers']):raise ValueError('CURRENT_HOLDING_NOT_OBSERVED')
    if not metadata_only:
        for key in ('session_id','clock_basis','clock_epoch'):
            if owner[key]!=candidate['desired'][key] or type(owner[key]) is not type(candidate['desired'][key]):raise ValueError('CURRENT_COMMAND_CLOCK_IDENTITY_CHANGED')
        if any(owner['desired'][k]!=candidate['desired'][k] for k in ('q_rad','v_rad_s','a_rad_s2')):
            raise ValueError('CURRENT_REFERENCE_CHANGED_REBUILD_CANDIDATE')
    for key in ('q_rad','v_rad_s','a_rad_s2'):vector(owner[key],6)
    vector([owner['grip_rad']],1);rigid(owner['attachment_tcp_to_block'])
    planned={o['id']:o for o in request['planning_snapshot']['world_objects'] if not o['id'].startswith('Dynamic_')}
    actual={o['id']:o for o in world['objects']}
    if len(actual)!=len(world['objects']):raise ValueError('DUPLICATE_CURRENT_WORLD_ID')
    context={};controlled_static=False
    if snapshot['scope']==LIVE:
        from dynamic_cumotion_inputs import owner_observations,normalize_owner_stop_state,check_control,validate_stopped_state
        from live_cumotion_boundary import verify_owner_state
        from online_cumotion_worker import admit_online_job
        from online_cumotion_validity import current_owner_world_metadata,computational_geometry
        from prepare_cumotion_model import load_model_yaml
        packet=pinned_json(snapshot['packet']);limits=pinned_json(snapshot['limits']);calculated=pinned_json(snapshot['calculated_envelope'])
        original_owner=pinned_json(snapshot['calculation_owner']);job=pinned_json(snapshot['selected_job'])
        if not metadata_only and job.get('D_input_approval') is not None:
            if pinned_json(snapshot['calculation_report']).get('selected_job')!=snapshot['selected_job']:
                raise ValueError('CURRENT_GEOMETRY_EXACT_CALCULATED_NATIVE_JOB_REQUIRED')
        if metadata_only and not owner_observations(limits):raise ValueError('CONTROLLED_OWNER_METADATA_MODE_REQUIRED')
        if owner_observations(limits):
            if snapshot['owner'] not in snapshot['source_pins'].values() or snapshot['packet'] not in snapshot['source_pins'].values():
                raise ValueError('CURRENT_INDEPENDENT_RAW_SOURCE_PINS_REQUIRED')
            if (limits!=job['limits'] or snapshot['calculated_envelope']!=job['calculated_envelope'] or
                    snapshot['calculation_owner']!=job['source_owner'] or
                    request!=load_model_yaml(Path(job['cache_request']['path']).read_text())):
                raise ValueError('CURRENT_GEOMETRY_NOT_EXACT_SELECTED_PREPARED_INPUTS')
            context['selected_inputs']=admit_online_job(job,dict(request=Path(job['cache_request']['path']),
                model=Path(job['cache_model_manifest']['path']).parent))
            inputs=pinned_json(job['prepared_inputs'])
            if (inputs['state']['owner_evidence']!=snapshot['calculation_owner'] or
                    calculated['inputs_sha256']!=job['prepared_inputs']['sha256'] or
                    inputs['state']['state_normalization']['source_packet']!=job['source_packet'] or
                    pinned_json(job['source_packet'])['state']['owner_evidence']!=snapshot['calculation_owner']):
                raise ValueError('CURRENT_GEOMETRY_CALCULATION_SOURCE_CHANGED')
            if (packet['state']['owner_evidence']!=snapshot['owner'] or
                    packet['state']['source_stamp_s']!=owner['state_stamp_s'] or
                    any(packet['state'][k]!=owner[k] for k in ('q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block'))):
                raise ValueError('CURRENT_PACKET_NOT_RAW_OWNER')
            packet=deepcopy(packet)
            if not computational_geometry(limits):raise ValueError('CURRENT_RAW_METADATA_REQUIRES_COMPUTE_ONLY')
            metadata,world_proof=current_owner_world_metadata(request,packet,owner,calculated['online_validity'])
            controlled_static=True
            packet['state']=normalize_owner_stop_state(packet['state'],limits,request['model_bundle'],snapshot['packet'])
            check_control(packet['control']);validate_stopped_state(packet['state'],packet['control'],limits)
            if any(packet[key] is not False or packet['state'][key] is not False for key in ('execution_allowed','hardware_execution_allowed')):
                raise ValueError('CURRENT_RAW_PACKET_MUST_NOT_GRANT_EXECUTION')
            from dynamic_cumotion_inputs import depth_packet,verify_depth_packet
            verify_depth_packet(request,packet['state'],depth_packet(packet['latest_depth_bound'],packet['state'],
                packet['latest_depth_bound']['frame_seq'],planner_box_representation=limits.get('planner_box_representation')),
                limits,owner['now_s'])
            if (packet['latest_depth']['digest']!=packet['latest_depth_bound']['candidate_digest'] or
                    packet['normalized_bound_replay_pending'] is not False or packet['timeline_running'] is not True or
                    packet['obstacle_motion_policy']!='CONTINUE_WHILE_ROBOT_HOLDS' or packet['desired']!=owner['desired']):
                raise ValueError('CURRENT_DEPTH_OR_RAW_OWNER_SOURCE_NOT_READY')
            context['world_metadata']=dict(derived=metadata,proof=world_proof,
                scope='TEMPORARY_RAW_OWNER_DERIVATION_NOT_SOURCE_REWRITE',FCL_required=True)
            verify_owner_state(request,packet['state'],packet['control'],limits)
            for key,value in (('envelope',calculated),('obstacles',inputs['obstacles'])):
                if key in packet and packet[key]!=value:raise ValueError('CURRENT_PACKET_CALCULATED_CONTEXT_CHANGED')
                packet[key]=value
    extra=set(actual)-set(planned);audit=set(snapshot['independent_audit_ids'])
    if len(audit)!=len(snapshot['independent_audit_ids']):raise ValueError('DUPLICATE_CURRENT_AUDIT_ID')
    if controlled_static and audit!={'PathBlockingStimulus'}:
        raise ValueError('CONTROLLED_STATIC_AUDIT_OBJECT_REQUIRED')
    if set(planned)-set(actual) or extra!=audit or (snapshot['scope']==LIVE and audit and not controlled_static):
        raise ValueError('MISSING_OR_NEW_CURRENT_WORLD_OBJECT_HOLD')
    shape_keys=('id','role','size_m','studs','coordinate_kind','block','slot_index','prim_path')
    for oid,obj in planned.items():
        if any(obj.get(k)!=actual[oid].get(k) for k in shape_keys):raise ValueError('CURRENT_SHAPE_TOPOLOGY_CHANGED_NEW_MODEL_REQUIRED')
    if controlled_static:
        source_objects={obj['id']:obj for obj in original_owner['world_objects']}
        stimulus=actual['PathBlockingStimulus'];source=source_objects['PathBlockingStimulus']
        if (any(stimulus.get(key)!=source.get(key) for key in shape_keys) or
                stimulus['role']!='OTHER_OBSTACLE' or stimulus['studs'] is not False or
                stimulus['coordinate_kind']!='SIM_BODY_CENTRE'):
            raise ValueError('CONTROLLED_STATIC_AUDIT_SHAPE_CHANGED')
        context['collision_roles']=dict(physical_world_ids=sorted(actual),
            actual_extra_FCL_only_ids=['PathBlockingStimulus'],
            immutable_planner_Depth_ids=[obj['id'] for obj in inputs['obstacles']['objects']],
            actual_extra_omitted=False,GT_pose_used_for_planning=False,
            scope='FULL_CURRENT_PHYSICAL_WORLD_PLUS_IMMUTABLE_DEPTH_ENVELOPE_UNION_NO_DEDUPLICATION')
    for obj in actual.values():
        if obj['pose']['frame_id']!='base_link':raise ValueError('CURRENT_WORLD_FRAME_CHANGED')
        pose_matrix(obj['pose'])
        if min(vector(obj['size_m'],3))<=0:raise ValueError('POSITIVE_CURRENT_GEOMETRY_REQUIRED')
    held=actual[owner['selected_block_id']]
    if nominal_definition(held,request['model_bundle'])!=nominal_definition(planned[held['id']],request['model_bundle']):
        raise ValueError('CURRENT_HELD_BODY_STUD_DEFINITION_CHANGED')
    if snapshot['scope']==LIVE:
        from isaac_sim.real_execution.native_boundary import review_stop,LIVE_IDENTITY
        from live_cumotion_boundary import verify_reference_time_association,review_observation_difference
        from online_cumotion_validity import check_online_context
        if any(owner[k]!=original_owner[k] or type(owner[k]) is not type(original_owner[k]) for k in LIVE_IDENTITY):
            raise ValueError('CURRENT_UUID_CANCEL_OR_REPLAN_CHANGED')
        if ({k:owner[k] for k in LIVE_IDENTITY}!=job['identity'] or
                job['fcl_binary']!=snapshot['selected_fcl_binary'] or
                job['fcl_library']!=snapshot['selected_fcl_library']):raise ValueError('CURRENT_SELECTED_JOB_OR_FCL_CHANGED')
        tracking=job['review_args']['tracking_limits'] if metadata_only else candidate['tracking_limits']
        if tracking!=job['review_args']['tracking_limits']:
            raise ValueError('CURRENT_OWNER_TRACKING_CRITERIA_CHANGED')
        if owner['a_context']!=request['a_context'] or owner['reservation_binding']!=request['reservation_binding']:
            raise ValueError('CURRENT_A_RESERVATION_CHANGED')
        state=packet['state']
        if (state['owner_evidence']!=snapshot['owner'] or state['source_stamp_s']!=owner['state_stamp_s'] or
                any(state[k]!=owner[k] for k in ('q_rad','v_rad_s','a_rad_s2','grip_rad')) or
                state['attachment_tcp_to_block']!=owner['attachment_tcp_to_block']):raise ValueError('CURRENT_PACKET_NOT_RAW_OWNER')
        context['stop']=review_stop(owner,limits['owner_review_limits'])
        observed=dict(stamp_s=owner['state_stamp_s'],**{k:owner[k] for k in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2')})
        context['clock']=verify_reference_time_association(owner['desired'],observed,now_s=owner['now_s'])
        context['tracking']=[review_observation_difference(tracking,'max_reference_skew_s',
            abs(owner['now_s']-owner['desired']['stamp_s']),applies_to='LATEST_GEOMETRY_REFERENCE_AGE')]
        for key,criterion in (('q_rad','q_tolerance_rad'),('v_rad_s','v_tolerance_rad_s'),('a_rad_s2','a_tolerance_rad_s2')):
            context['tracking'].append(review_observation_difference(tracking,criterion,
                max(abs(a-b) for a,b in zip(owner[key],owner['desired'][key])),applies_to='LATEST_GEOMETRY_RAW_VS_REFERENCE:'+key))
        static=[o for oid,o in actual.items() if oid!=owner['selected_block_id']]
        if not controlled_static and packet['static_world_digest']!=digest(sorted(static,key=lambda x:x['id'])):
            raise ValueError('CURRENT_STATIC_WORLD_DIGEST_NOT_ACTUAL_INVENTORY')
        if metadata_only:
            context.update(scope='METADATA_AND_RAW_SOURCE_REVIEW_ONLY_NOT_LIVE_ELIGIBILITY_OR_FCL',
                selected_job_native_publication_verified=False,SDK_trajectory_verified=False,FCL_executed=False,
                current_live_TTL_and_wall_check='NOT_RUN_NO_TRAJECTORY',READY=False,apply_allowed=False)
        else:
            context['dynamic']=check_online_context(request,calculated,packet,owner,limits)
            if duration>context['dynamic']['max_trajectory_duration_s']:raise ValueError('WHOLE_COMMAND_EXCEEDS_DEPTH_HORIZON')
    return owner,actual,planned,context


def review_current_geometry_inputs(snapshot,request):
    """Candidate-free metadata subset; never an FCL or live apply proof."""
    if snapshot['scope']!=LIVE:raise ValueError('LIVE_RAW_METADATA_SCOPE_REQUIRED')
    return _review_snapshot(snapshot,request,None,None,metadata_only=True)


def review_snapshot(snapshot,request,candidate,duration):
    if candidate is None or duration is None:raise ValueError('ACTUAL_WHOLE_COMMAND_REQUIRED')
    return _review_snapshot(snapshot,request,candidate,duration)


def current_collision_inputs(request,owner,actual,audit_ids):
    """Geometry-only derivative after review; never a replacement A request.

    Keep calculated Depth volumes AND every independently observed physical
    object, including the controlled audit stimulus. No GT enters planning.
    """
    current=deepcopy(request);current['attachment']=deepcopy(owner['attachment_tcp_to_block'])
    current['planning_snapshot']['grip_rad']=owner['grip_rad']
    current['planning_snapshot']['world_objects']=[deepcopy(actual[obj['id']]) if not obj['id'].startswith('Dynamic_') else deepcopy(obj)
        for obj in request['planning_snapshot']['world_objects']]
    return current,[deepcopy(actual[oid]) for oid in audit_ids]


def produce_current_geometry_proof(files,snapshot_provider,output):
    """Single attempt. Provider must keep physics running; any changed record rejects.

    Controlled-static raw metadata is derived from pinned owner observations.
    Full live context checks and complete physical-world FCL remain mandatory.
    """
    if 'command_encoding' in files:raise ValueError('USE_SEPARATE_EXACT_ENCODED_PROOF_PRODUCER')
    output=Path(output)
    if output.exists():raise FileExistsError('New current-geometry proof folder required')
    before=deepcopy(snapshot_provider());request,candidate,trajectory=load_calculation(files)
    if before['scope']==LIVE and before['calculation_report']!=files['report']:raise ValueError('CURRENT_REPORT_NOT_THIS_CALCULATION')
    if before['scope']==LIVE and (before['selected_fcl_binary']!=files['fcl_binary'] or before['selected_fcl_library']!=files['fcl_library']):
        raise ValueError('CURRENT_CALCULATION_FCL_NOT_OWNER_SELECTED')
    owner,actual,planned,context=review_snapshot(before,request,candidate,trajectory['points'][-1]['time_from_start_s'])
    current,extras=current_collision_inputs(request,owner,actual,before['independent_audit_ids'])
    robot=ET.fromstring(request['model_bundle']['robot_description']);bounds=[robot.find(f"joint[@name='joint_{i}']/limit") for i in range(1,7)]
    lower=[float(b.get('lower')) for b in bounds];upper=[float(b.get('upper')) for b in bounds]
    limits=validate_quintic_limits(trajectory,lower,upper)
    if any(q<lo or q>hi for q,lo,hi in zip(owner['q_rad'],lower,upper)):raise ValueError('RAW_CURRENT_START_BOUNDS')
    endpoint=tcp_fk(request['model_bundle'],trajectory['points'][-1]['positions_rad'],owner['grip_rad'])
    target=pose_matrix(request['goal']);endpoint_error=error(endpoint,target)
    # Existing MoveIt file endpoint criteria; not observed-state tolerances.
    if endpoint_error[0]>.0008 or endpoint_error[1]>.005:raise ValueError('CURRENT_MODEL_PRECONTACT_ENDPOINT_REJECTED')
    scene=StopScene(current,Path(files['fcl_library']['path']),files['fcl_library']['sha256'],extra_obstacles=extras)
    try:
        raw_hit=scene.check(owner['q_rad'])
        result=dict(success=False,checks=1,reason='RAW_CURRENT_START_FCL_REJECTED',**raw_hit) if raw_hit else check_stop(scene,trajectory)
        metadata=deepcopy(scene.metadata)
    finally:scene.close()
    after=deepcopy(snapshot_provider())
    if after!=before:raise ValueError('CURRENT_GEOMETRY_OR_CONTEXT_CHANGED_DURING_FCL_REVALIDATE')
    review_snapshot(after,request,candidate,trajectory['points'][-1]['time_from_start_s'])
    load_calculation(files)  # Recheck all immutable input pins after CPU work.
    output.mkdir(parents=True,exist_ok=False)
    audit=dict(scope=before['scope'],success=result['success'],calculation_files=deepcopy(files),snapshot=before,
        snapshot_digest=digest(before),actual_geometry_request_digest=digest(current),
        actual_geometry=dict(grip_rad=owner['grip_rad'],attachment=owner['attachment_tcp_to_block'],world_digest=digest(actual)),
        original_request_digest=request['planning_request_digest'],whole_command_digest=digest(trajectory),
        original_suffix_digest=candidate['suffix_digest'],raw_current_PVT={k:owner[k] for k in ('q_rad','v_rad_s','a_rad_s2','state_stamp_s')},
        raw_start_FCL=dict(checked=True,collision=raw_hit),whole_command_FCL=result,analytic_command_limits=limits,FCL_geometry=metadata,
        endpoint=dict(TCP_error_m_rad=endpoint_error,expected_precontact=request['goal'],
            actual_attachment_block_error_vs_original_m_rad=error(endpoint@rigid(owner['attachment_tcp_to_block']),target@rigid(request['attachment'])),
            model_block_at_wait=matrix_pose(endpoint@rigid(owner['attachment_tcp_to_block'])),criterion='EXISTING_TCP_PRECONTACT_0.0008m_0.005rad_NOT_ASSEMBLY_SUCCESS'),
        live_context_checks=context,calculation_provenance_modified=False,
        current_geometry_checked=True,actual_live_source_verified=False,native_execution_allowed=False,hardware_execution_allowed=False,live_resume_approved=False)
    (output/'current_geometry_FCL.json').write_text(json.dumps(audit,indent=2,allow_nan=False)+'\n')
    return audit


def review_current_geometry_proof(proof_ref,files,snapshot_provider):
    """Final read-only recheck; changed source requires a new proof, never retagging."""
    proof=pinned_json(proof_ref);request,candidate,trajectory=load_calculation(files)
    if 'command_encoding' in files:
        receipt=pinned_json(files['command_encoding'])
        review_current_geometry_proof(receipt['original_geometry_proof'],receipt['original_files'],snapshot_provider)
        source=pinned_json(receipt['original_geometry_proof'])
        expected=encoded_geometry_audit(source,files,receipt)
        if proof!=expected:raise ValueError('ENCODED_PROOF_NOT_EXACT_DERIVATION')
    if proof['calculation_files']!=files or proof['whole_command_digest']!=digest(trajectory):raise ValueError('PROOF_FOR_DIFFERENT_COMMAND')
    current=deepcopy(snapshot_provider())
    if current!=proof['snapshot'] or digest(current)!=proof['snapshot_digest']:raise ValueError('CURRENT_GEOMETRY_PROOF_STALE_REVALIDATE')
    review_snapshot(current,request,candidate,trajectory['points'][-1]['time_from_start_s'])
    if proof['success'] is not True or proof['whole_command_FCL']['success'] is not True:raise ValueError('LATEST_GEOMETRY_FCL_REJECTED_HOLD')
    return dict(scope=proof['scope'],current_geometry_proof=proof_ref,live_resume_approved=False,native_execution_allowed=False)


def encoded_geometry_audit(source,files,receipt):
    audit=deepcopy(source)
    audit.update(calculation_files=deepcopy(files),whole_command_digest=receipt['equivalence']['encoded_command_digest'],
        command_encoding=deepcopy(files['command_encoding']),original_geometry_proof=receipt['original_geometry_proof'],
        original_whole_command_digest=source['whole_command_digest'],
        FCL_reuse_basis='EXACT_SAME_NUMERIC_CONTINUOUS_CURVE_SAME_RAW_SOURCE_GEOMETRY',new_FCL_executed=False)
    return audit


def produce_encoded_geometry_proof(original_proof_ref,original_files,wire_ref,delivery_ref,snapshot_provider,output):
    """Additional proof for exact encoding only. Original FCL/SDK remain pinned.

    No geometric/temporal approximation or execution grant. Quantized changed
    curves require new candidate+limits+full FCL through a separate request.
    """
    output=Path(output)
    if output.exists():raise FileExistsError('New encoded proof folder required')
    before=deepcopy(snapshot_provider())
    review_current_geometry_proof(original_proof_ref,original_files,lambda:before)
    source=pinned_json(original_proof_ref);_,_,original=load_calculation(original_files)
    equality=exact_encoded_command(original,pinned_json(wire_ref))
    review_encoding_delivery(delivery_ref,wire_ref,before)
    receipt=dict(codec=CODEC,original_geometry_proof=original_proof_ref,original_files=deepcopy(original_files),
        encoded_command=wire_ref,delivery=delivery_ref,equivalence=equality)
    if snapshot_provider()!=before:raise ValueError('ENCODING_CURRENT_SOURCE_CHANGED')
    output.mkdir(parents=True,exist_ok=False)
    (output/'command_encoding.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    files=dict(original_files,command=wire_ref,command_encoding=pin(output/'command_encoding.json'))
    load_calculation(files)
    audit=encoded_geometry_audit(source,files,receipt)
    (output/'current_geometry_FCL.json').write_text(json.dumps(audit,indent=2,allow_nan=False)+'\n')
    review_current_geometry_proof(pin(output/'current_geometry_FCL.json'),files,snapshot_provider)
    return audit
