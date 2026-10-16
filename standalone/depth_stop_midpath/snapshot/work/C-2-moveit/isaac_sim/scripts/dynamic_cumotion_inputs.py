"""Stopped snapshots -> CPU shape inputs and explicit bounded-SIM admission.

Unknown extents fail closed. Common A/B/D schemas stay unchanged; all new
provenance is a local sidecar, never dispatch or robot execution permission.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import math
import numpy as np
import yaml
from plan_only import BINDING, JOINTS, digest, checked_pose, prepare_request, vector
from prepare_gpu_scene import tcp_fk
from prepare_sim_snapshot import prepare_sim_snapshot
from prepare_cpu_model import file_hash
from sim_utils import rigid, matrix_pose, pose_matrix

OWNER_OBSERVATIONS='D_OWNER_VERIFIED_REPORT_ONLY'
CONSERVATIVE_FOREGROUND_PROFILE='CONSERVATIVE_FOREGROUND_STOP_SIM_OWNER_ONLY'


def conservative_foreground_profile(limits):
    profile=limits.get('owner_packet_profile')
    if profile not in (None,CONSERVATIVE_FOREGROUND_PROFILE):raise ValueError('UNKNOWN_OWNER_PACKET_PROFILE')
    return profile==CONSERVATIVE_FOREGROUND_PROFILE


def owner_observations(limits):
    mode=limits.get('stop_observation_mode','EXPLICIT_NUMERIC_SIM_LIMITS')
    if mode not in ('EXPLICIT_NUMERIC_SIM_LIMITS',OWNER_OBSERVATIONS):raise ValueError('UNKNOWN_STOP_OBSERVATION_MODE')
    return mode==OWNER_OBSERVATIONS


def review_owner_observations(state,limits):
    """Use the selected D verdict; null is never evidence of observed rest."""
    from bounded_sim_evidence import pinned_json
    from isaac_sim.real_execution.native_boundary import review_stop
    from online_cumotion_validity import COMPUTE_GEOMETRY
    if (not owner_observations(limits) or
            limits.get('initial_condition_mode')!='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE' or
            limits.get('geometry_observation_mode')!=COMPUTE_GEOMETRY):
        raise ValueError('OWNER_OBSERVATIONS_REQUIRE_NONEXECUTABLE_PVT_CANDIDATE')
    owner=pinned_json(state['owner_evidence']);owner=owner.get('owner_context',owner)
    selected=pinned_json(limits['owner_review_limits_evidence'])
    for key in ('q_rad','v_rad_s','a_rad_s2'):vector(state[key],6)
    conservative=conservative_foreground_profile(limits)
    policy_ref=owner['owner_limits_ref'] if conservative else owner['owner_review_limits']
    if selected!=limits['owner_review_limits'] or policy_ref!=limits['owner_review_limits_evidence']:
        raise ValueError('ACTUAL_OWNER_SELECTED_OBSERVATION_POLICY_CHANGED')
    # These undefined measured criteria cannot silently become new scalar caps.
    mapping={'max_abs_velocity_rad_s':'max_stop_velocity_rad_s',
        'max_abs_acceleration_rad_s2':'max_stop_acceleration_rad_s2',
        'max_camera_state_joint_error_rad':'q_tolerance_rad'}
    if any(limits[k] is not None or selected[v] is not None for k,v in mapping.items()):
        raise ValueError('EXPLICIT_NULL_OWNER_OBSERVATION_MAPPING_REQUIRED')
    if conservative:
        from conservative_stop_packet import review_conservative_source_packet
        review_conservative_source_packet(state,owner,selected,limits['owner_review_limits_evidence'])
    else:review_stop(owner,selected)
    if (owner['stop_record']['source_kind']!='SIM_OWNER_RECORD' or state['source_kind']!='SIM_SAVED_SNAPSHOT' or
            any(state[k]!=owner[k] for k in ('session_id','clock_basis','state_sequence','cancel_generation',
                'q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block')) or
            state['source_stamp_s']!=owner['state_stamp_s']):
        raise ValueError('NORMALIZED_STATE_NOT_ORIGINAL_RAW_OWNER')
    return owner


def normalize_owner_stop_state(state,limits,model,source_packet_ref):
    """Add only timestamps explicitly present in pinned raw observation/verdict.

    The returned sealed state is derived. The producer's packet and raw state
    remain immutable; q/v/a are copied unchanged, never rest-projected.
    """
    if conservative_foreground_profile(limits):
        from conservative_stop_packet import normalize_conservative_stop_state
        return normalize_conservative_stop_state(state,limits,model,source_packet_ref)
    from bounded_sim_evidence import pinned_json
    from depth_obstacle_envelope import verify_sim_stop
    verify_seal(state)
    packet=pinned_json(source_packet_ref)
    if packet['state']!=state:raise ValueError('STATE_NOT_FROM_PINNED_SOURCE_PACKET')
    owner=review_owner_observations(state,limits)
    verify_sim_stop(state,model,limits)
    proof=pinned_json({k:state['stop_evidence'][k] for k in ('path','sha256')})
    actual=proof['observation']['raw_current_native_PVA'];verdict=pinned_json(owner['stop_verification'])
    if (actual['stamp_s']!=state['source_stamp_s'] or verdict['state_stamp_s']!=state['source_stamp_s'] or
            any(actual[k]!=state[k] for k in ('q_rad','v_rad_s','a_rad_s2'))):
        raise ValueError('RAW_DERIVATIVE_OR_VERDICT_SOURCE_STAMP_NOT_PROVEN')
    result=deepcopy(state)
    times=dict(velocity_stamp_s=actual['stamp_s'],acceleration_stamp_s=actual['stamp_s'],stop_evidence_stamp_s=verdict['state_stamp_s'])
    for key,value in times.items():
        if key in state and state[key]!=value:raise ValueError('EXISTING_STATE_STAMP_CONFLICT:'+key)
        result[key]=value
    result['state_normalization']=dict(scope='DERIVED_FROM_PINNED_RAW_PVA_AND_D_VERDICT_NOT_NEW_OBSERVATION',
        source_packet=source_packet_ref,raw_state_digest=state['digest'],stop_evidence=state['stop_evidence'],
        owner_stop_verification=owner['stop_verification'],
        field_sources=dict(velocity_stamp_s='observation.raw_current_native_PVA.stamp_s',
            acceleration_stamp_s='observation.raw_current_native_PVA.stamp_s',stop_evidence_stamp_s='owner.stop_verification.state_stamp_s'),
        raw_PVA_unchanged=True,execution_allowed=False)
    return sealed(result)


def select_owner_input_limits(owner_ref,sensor_spec_ref,policy_ref,*,
        owner_packet_profile=None,conservative_source_refs=None):
    """Select existing source policies, without assigning new observation caps.

    Each independently proven source sample must remain fresh at the same now.
    This does not admit inputs, choose a job generation or create A context.
    """
    if owner_packet_profile is not None:
        if owner_packet_profile!=CONSERVATIVE_FOREGROUND_PROFILE:
            raise ValueError('UNKNOWN_OWNER_PACKET_PROFILE')
        if (sensor_spec_ref is not None or policy_ref is not None or
                not isinstance(conservative_source_refs,dict) or
                conservative_source_refs.get('owner')!=owner_ref):
            raise ValueError('EXPLICIT_CONSERVATIVE_STOP_ONLY_SOURCE_SELECTION_REQUIRED')
        from conservative_stop_packet import build_conservative_stop_packet
        result=deepcopy(build_conservative_stop_packet(conservative_source_refs)['limits_delta'])
        result.update(selection_scope='CONSERVATIVE_STOP_ONLY_SENSOR_WORLD_POLICY_UNSELECTED',
            full_input_policy_selected=False)
        return result
    from bounded_sim_evidence import pinned_json
    from online_cumotion_validity import COMPUTE_GEOMETRY
    from depth_obstacle_envelope import OUTWARD_PLANNER_BOX
    owner=pinned_json(owner_ref);spec=pinned_json(sensor_spec_ref);policy=pinned_json(policy_ref)
    from depth_obstacle_envelope import evidence_files
    _,paths=evidence_files(spec)
    frame=json.loads(paths['frame'].read_text());sensor=json.loads(paths['limits'].read_text())
    selected=pinned_json(owner['owner_review_limits'])
    if (frame['session_id']!=owner['session_id'] or frame['clock_basis']!=owner['clock_basis'] or
            frame['clock_epoch']!=owner['clock_epoch'] or frame['live_scene_motion_kind']!='STATIC_OBSTACLE' or
            policy['scope']!='EXPLICIT_STATIC_SIM_TRIAL_BUDGETS_NOT_SDK_OBSERVATION_LIMITS'):
        raise ValueError('ACTUAL_SENSOR_OWNER_POLICY_IDENTITY_REQUIRED')
    result=dict(threshold_status='SIM_TEST_PARAMETER',clock_basis=owner['clock_basis'],
        live_scene_motion_kind=frame['live_scene_motion_kind'],world_revision=frame['world_revision'],
        initial_condition_mode='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE',geometry_observation_mode=COMPUTE_GEOMETRY,
        stop_observation_mode=OWNER_OBSERVATIONS,owner_review_limits=selected,
        planner_box_representation=OUTWARD_PLANNER_BOX,
        owner_review_limits_evidence=owner['owner_review_limits'],
        max_state_age_s=selected['max_state_age_s'],max_obstacle_age_s=sensor['max_age_s'],
        max_snapshot_skew_s=max(selected['max_state_age_s'],sensor['max_age_s']),max_pose_skew_s=sensor['max_pose_skew_s'],
        snapshot_skew_basis='MATHEMATICAL_UPPER_BOUND_OF_TWO_INDIVIDUALLY_FRESH_SAMPLES_AT_SAME_NOW',
        min_verified_stop_duration_s=selected['min_stop_observation_s'],
        max_abs_velocity_rad_s=None,max_abs_acceleration_rad_s2=None,
        max_camera_state_joint_error_rad=None,max_start_drift_rad=None,
        source_policy_refs=dict(owner_review=owner['owner_review_limits'],sensor_limits=dict(path=str(paths['limits']),sha256=file_hash(paths['limits'])),
            static_trial=policy_ref),
        selection_scope='INDEPENDENTLY_PROVEN_SAME_SESSION_SAMPLES_NULL_OBSERVATIONS_USE_D_VERDICT_NOT_EXECUTION')
    if any(number(result[k])<=0 for k in ('max_state_age_s','max_obstacle_age_s','max_snapshot_skew_s',
            'max_pose_skew_s','min_verified_stop_duration_s')):raise ValueError('POSITIVE_SOURCE_TIME_POLICY_REQUIRED')
    return result


def sealed(value,key='digest'):
    value=deepcopy(value);value[key]=digest({k:v for k,v in value.items() if k!=key});return value


def verify_seal(value,key='digest'):
    if value.get(key)!=digest({k:v for k,v in value.items() if k!=key}):
        raise ValueError('CANONICAL_DIGEST_MISMATCH')


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Finite number required')
    return value


def sequence(value):
    if type(value) is not int or value<0:raise ValueError('Nonnegative integer sequence required')
    return value


def check_control(control):
    if (control['mode']!='OBSTACLE_HOLD' or control['user_stop_latched'] is not False
            or control['failure_latched'] is not False):raise ValueError('USER_STOP_OR_FAILURE_LATCHED')
    for key in ('session_id','clock_basis'):
        if not isinstance(control[key],str) or not control[key]:raise ValueError('Explicit session/clock required')
    for key in ('replan_sequence','cancel_generation'):sequence(control[key])


def validate_packets(base,state,obstacles,control,limits,now_s,previous):
    check_control(control);number(now_s)
    if limits['threshold_status']!='SIM_TEST_PARAMETER':raise ValueError('Explicit SIM/fixture limits required')
    keys=('max_state_age_s','max_obstacle_age_s','max_snapshot_skew_s','max_pose_skew_s')
    if not owner_observations(limits):keys+=('max_camera_state_joint_error_rad','max_abs_velocity_rad_s','max_abs_acceleration_rad_s2')
    if any(number(limits[k])<=0 for k in keys):raise ValueError('Positive explicit limits required')
    # Observed derivatives use explicit SIM limits, not SDK mathematical rest.
    # Candidate-only mode additionally verifies the owner for a PVT bridge.
    mode=limits.get('initial_condition_mode','STRICT_OBSERVED_REST')
    if mode=='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE':
        from live_cumotion_boundary import verify_owner_state
        verify_owner_state(base,state,control,limits)
    elif mode!='STRICT_OBSERVED_REST':
        raise ValueError('UNKNOWN_INITIAL_CONDITION_MODE')
    # Camera/state coupling uses its explicitly selected source criterion,
    # not a universal SDK observation cap. Binding stamps/sequence still match.
    if state['schema']!='stopped-robot-snapshot/0.1' or obstacles['schema']!='base-obstacle-snapshot/0.1':
        raise ValueError('FULL_OBSTACLE_VOLUME_REQUIRED_NOT_VISIBLE_POINTS')
    for packet in (state,obstacles):
        verify_seal(packet)
        if packet['clock_basis']!=control['clock_basis'] or packet['session_id']!=control['session_id']:
            raise ValueError('SESSION_OR_CLOCK_MISMATCH')
        if packet['execution_allowed'] is not False or packet['hardware_execution_allowed'] is not False:
            raise ValueError('CPU_NON_EXECUTABLE_INPUT_REQUIRED')
        if not number(packet['source_stamp_s'])<=number(packet['received_stamp_s'])<=now_s:
            raise ValueError('FUTURE_OR_REORDERED_RECEIPT_TIME')
    if (limits['clock_basis']!=control['clock_basis'] or
            now_s-state['source_stamp_s']>limits['max_state_age_s'] or
            now_s-obstacles['source_stamp_s']>limits['max_obstacle_age_s']):raise ValueError('STALE_SNAPSHOT')
    if abs(state['source_stamp_s']-obstacles['source_stamp_s'])>limits['max_snapshot_skew_s']:
        raise ValueError('STATE_OBSTACLE_TIMESTAMP_SKEW')
    validate_stopped_state(state,control,limits)
    ids=validate_obstacle_geometry(base,state,obstacles,limits,now_s)
    return monotonic_cursor(base,state,obstacles,control,ids,previous,
        allow_owner_initial_zero=owner_observations(limits))


def validate_stopped_state(state,control,limits):
    if (state['joint_names']!=JOINTS or state['units']!='rad, seconds' or state['source_kind'] not in ('FIXTURE','SIM_SAVED_SNAPSHOT') or
            not state['evidence_ref'] or state['stopped_verified'] is not True or state['holding_confirmed'] is not True
            or state['active_command_count']!=0 or state['pending_command_count']!=0):
        raise ValueError('VERIFIED_STOPPED_HOLDING_STATE_REQUIRED')
    for key in ('active_command_count','pending_command_count'):sequence(state[key])
    conservative=conservative_foreground_profile(limits)
    expected_reason='FRESH_FOREGROUND_CONSERVATIVE_STOP' if conservative else 'OBSTACLE_RESPONSE_HOLD'
    if (sequence(state['cancel_generation'])!=control['cancel_generation'] or state['stop_reason']!=expected_reason):
        raise ValueError('STOP_REASON_OR_CANCEL_GENERATION_MISMATCH')
    for name in ('q_rad','v_rad_s','a_rad_s2'):vector(state[name],6)
    if conservative and not owner_observations(limits):raise ValueError('CONSERVATIVE_PROFILE_REQUIRES_OWNER_REPORT_ONLY_PVT_CANDIDATE')
    if owner_observations(limits):review_owner_observations(state,limits)
    elif (max(map(abs,state['v_rad_s']))>limits['max_abs_velocity_rad_s'] or
            max(map(abs,state['a_rad_s2']))>limits['max_abs_acceleration_rad_s2']):
        raise ValueError('MOVING_OPTIMIZER_START_REJECTED')
    time_error=max(abs(number(state[k])-state['source_stamp_s']) for k in ('velocity_stamp_s','acceleration_stamp_s','stop_evidence_stamp_s'))
    if not state['acceleration_method'] or (time_error!=0 if conservative else time_error>limits['max_pose_skew_s']):
        raise ValueError('STATE_DERIVATIVE_OR_STOP_TIMESTAMP_MISMATCH')
    vector([state['grip_rad']],1);rigid(state['attachment_tcp_to_block'])


def validate_obstacle_geometry(base,state,obstacles,limits,now_s):
    # Until a Depth producer validates hidden volume/free-space, geometry is
    # explicitly FIXTURE. GT/partial depth cannot acquire this label implicitly.
    bounded='depth_bound' in obstacles
    if bounded:
        verify_depth_packet(base,state,obstacles,limits,now_s)
    elif (obstacles['source_kind']!='FIXTURE' or obstacles['coverage']!='FULL_FIXTURE_VOLUME' or
            obstacles['extent_provenance']!='EXPLICIT_FIXTURE' or not obstacles['objects']):
        raise ValueError('UNKNOWN_EXTENT_OR_COVERAGE_HOLD_REQUIRED')
    if obstacles['base_frame_id']!='base_link' or (not bounded and obstacles['mask_status']!='EXPLICIT_FIXTURE'):
        raise ValueError('BASE_GEOMETRY_AND_EXPLICIT_MASK_PROVENANCE_REQUIRED')
    camera=obstacles['camera']
    scopes=('SIM_NOMINAL','SIM_NOMINAL_FROM_REAL_PUBLISHED_TF') if obstacles['source_kind']=='SIM_DEPTH' else ('SIM_FIXTURE',)
    if (camera['tool_frame_id']!='GripperDA_v4_tcp' or not camera['optical_frame_id'] or
            camera['calibration_scope'] not in scopes or not camera['calibration_id']):
        raise ValueError('WRIST_OPTICAL_CALIBRATION_REQUIRED')
    if max(abs(number(camera[k])-obstacles['source_stamp_s'])
            for k in ('transform_stamp_s','robot_state_stamp_s'))>limits['max_pose_skew_s']:
        raise ValueError('WRIST_SOURCE_TIMESTAMP_MISMATCH')
    if owner_observations(limits):
        from live_cumotion_boundary import review_observation_difference
        review_owner_observations(state,limits)
        review_observation_difference(limits['owner_review_limits'],'q_tolerance_rad',
            max(abs(x-y) for x,y in zip(vector(camera['q_rad'],6),state['q_rad'])),applies_to='CAMERA_SOURCE_VS_RAW_OWNER_Q')
        q_changed=False
    else:q_changed=max(abs(x-y) for x,y in zip(vector(camera['q_rad'],6),state['q_rad']))>limits['max_camera_state_joint_error_rad']
    separate_proven_sources=bounded and owner_observations(limits)
    if not separate_proven_sources and (sequence(camera['state_sequence'])!=state['state_sequence'] or
            abs(camera['robot_state_stamp_s']-state['source_stamp_s'])>limits['max_pose_skew_s'] or
            q_changed or
            abs(number(camera['grip_rad'])-state['grip_rad'])>1e-9):
        raise ValueError('WRIST_NOT_BOUND_TO_LATEST_STOPPED_STATE')
    tool=tcp_fk(base['model_bundle'],camera['q_rad'],camera['grip_rad'])
    if not bounded and not np.allclose(tool,rigid(camera['T_base_tool']),atol=1e-8,rtol=0):raise ValueError('WRIST_FK_MISMATCH')
    transform=rigid(camera['T_base_tool'])@rigid(camera['T_tool_camera_optical'])
    if not np.allclose(transform,rigid(camera['T_base_camera_optical']),atol=1e-8,rtol=0):
        raise ValueError('WRIST_OPTICAL_TRANSFORM_MISMATCH')
    ids=[]
    for obj in obstacles['objects']:
        if (not obj['id'].startswith('Dynamic_') or obj['role']!='OTHER_OBSTACLE' or obj['studs'] is not False
                or obj['coordinate_kind']!='SIM_BODY_CENTRE' or not obj['geometry_evidence_ref'].startswith('BOUNDED_DEPTH:' if bounded else 'FIXTURE:')
                or 'mesh_vertices_m' in obj or 'mesh_triangles' in obj):raise ValueError('EXPLICIT_ADDITIVE_FIXTURE_BOX_REQUIRED')
        checked_pose(obj['pose'])
        if min(vector(obj['size_m'],3))<=0:raise ValueError('Positive obstacle volume required')
        ids.append(obj['id'])
    base_ids={o['id'] for o in base['planning_snapshot']['world_objects']}
    if len(set(ids))!=len(ids) or set(ids)&base_ids:raise ValueError('DUPLICATE_OR_STATIC_ID_OVERWRITE')
    return ids


def monotonic_cursor(base,state,obstacles,control,ids,previous,*,allow_owner_initial_zero=False):
    for key,value in [('state_sequence',state['state_sequence']),('obstacle_version',obstacles['version']),('frame_seq',obstacles['frame_seq'])]:sequence(value)
    cursor=dict(schema='dynamic-input-cursor/0.1',**{k:control[k] for k in ('session_id','clock_basis','replan_sequence','cancel_generation')},
        state_sequence=state['state_sequence'],state_stamp_s=state['source_stamp_s'],obstacle_version=obstacles['version'],
        obstacle_stamp_s=obstacles['source_stamp_s'],obstacle_session_id=obstacles['obstacle_session_id'],frame_seq=obstacles['frame_seq'],
        obstacle_ids=ids,base_request_digest=base['planning_request_digest'])
    if not isinstance(cursor['obstacle_session_id'],str) or not cursor['obstacle_session_id']:raise ValueError('Explicit obstacle session required')
    if previous is not None:
        verify_seal(previous)
        if previous['schema']!='dynamic-input-cursor/0.1':raise ValueError('Explicit cursor schema required')
        if any(previous[k]!=cursor[k] for k in ('session_id','clock_basis','obstacle_session_id','base_request_digest')):
            raise ValueError('SESSION_RESET_REQUIRES_EXPLICIT_HANDLING')
        if any(cursor[k]<=previous[k] for k in ('replan_sequence','state_sequence','state_stamp_s','obstacle_version','obstacle_stamp_s','frame_seq')) or cursor['cancel_generation']<previous['cancel_generation']:
            raise ValueError('OLD_DUPLICATE_OR_REORDERED_GENERATION')
        if not set(previous['obstacle_ids'])<=set(ids):raise ValueError('REMOVAL_WITHOUT_FREE_SPACE_EVIDENCE')
    elif control['replan_sequence']!=1 and not (allow_owner_initial_zero and control['replan_sequence']==0):
        raise ValueError('PREVIOUS_CURSOR_REQUIRED_AFTER_FIRST_REPLAN')
    return sealed(cursor)


def capture_documents(base,state,obstacles,*,artifact_created_at=None,known_scene=None):
    docs={k:json.loads(Path(v['path']).read_text()) for k,v in base['simulation_provenance']['files'].items()}
    captured_at=state.get('captured_at')
    if captured_at is None:
        if state.get('state_normalization',{}).get('raw_PVA_unchanged') is not True:
            raise ValueError('EXPLICIT_SOURCE_CAPTURE_OR_NORMALIZED_OWNER_REQUIRED')
        # Legacy shape files require ISO metadata. This is their creation time,
        # never an invented UTC acquisition time for the monotonic raw state.
        if artifact_created_at is None:raise ValueError('EXPLICIT_SHAPE_ARTIFACT_CREATION_TIME_REQUIRED')
        captured_at=artifact_created_at
        for doc in docs.values():doc['adapter_timestamp_provenance']=dict(
            scope='SHAPE_FILE_CREATION_TIME_NOT_SENSOR_OR_OWNER_ACQUISITION',
            original_source_stamp_s=state['source_stamp_s'],clock_basis=state['clock_basis'],
            state_normalization=deepcopy(state['state_normalization']))
    for doc in docs.values():
        doc.update(source_kind='SIM_CONTRACT_FIXTURE',capture_id=f"dynamic-fixture:{state['session_id']}:{state['state_sequence']}",
                   captured_at=captured_at,execution_allowed=False,production_B_confirmed=False)
    if datetime.fromisoformat(captured_at).tzinfo is None:raise ValueError('Fixture ISO timestamp needs timezone')
    scene,robot=docs['scene'],docs['state']
    tcp=tcp_fk(base['model_bundle'],state['q_rad'],state['grip_rad'])
    robot.update({k:deepcopy(state[k]) for k in ('q_rad','grip_rad','attachment_tcp_to_block','holding_confirmed','stopped_verified','active_command_count','pending_command_count')})
    robot['tcp_pose']=matrix_pose(tcp)
    robot['raw_joint_velocity_rad_s']=deepcopy(state['v_rad_s'])
    robot['observation_evidence']=dict(scope='CPU_FIXTURE_NOT_LIVE_STOP_PROOF',state_digest=state['digest'],evidence_ref=state['evidence_ref'])
    if 'depth_bound' in obstacles:
        # Keep legacy shape projection honest. Bounded-SIM admission must
        # independently replay raw capture/state, not relabel these documents.
        for doc in docs.values():doc['cpu_shape_adapter_provenance']=dict(source_kind=obstacles['source_kind'],
            bound_digest=obstacles['depth_bound']['digest'],scope='CPU_SHAPE_PROJECTION_NOT_LEGACY_SAVED_CAPTURE')
    scene['world_objects']=deepcopy(base['planning_snapshot']['world_objects'])
    if known_scene is not None:
        # Explicit generic CPU projection; no inspection of unknown actor GT.
        scene['world_objects']=deepcopy(known_scene['world_objects'])
        scene['frame_alignment']['T_world_base']=deepcopy(known_scene['T_world_base'])
        scene['source_world_projection']=deepcopy(known_scene['provenance'])
    if state.get('state_normalization') and known_scene is None:
        from bounded_sim_evidence import pinned_json
        owner=pinned_json(state['owner_evidence'])
        if (owner['world_observation_stamp_s']!=state['source_stamp_s'] or
                owner['model_manifest_sha256']!=base['model_bundle']['manifest_sha256'] or
                owner['a_context']!=base['a_context'] or owner['reservation_binding']!=base['reservation_binding']):
            raise ValueError('CURRENT_FULL_WORLD_NOT_SAME_A_MODEL_SOURCE')
        actual={o['id']:o for o in owner['world_objects']}
        if len(actual)!=len(owner['world_objects']):raise ValueError('DUPLICATE_CURRENT_WORLD_OBJECT')
        retired=[o for o in scene['world_objects'] if o['id'].startswith('Dynamic_') and o['role']=='OTHER_OBSTACLE']
        if any(not o.get('geometry_evidence_ref','').startswith('BOUNDED_DEPTH:') for o in retired):
            raise ValueError('UNPROVEN_PERCEPTION_VOLUME_REPLACEMENT')
        physical=[o for o in scene['world_objects'] if o not in retired]
        required={o['id'] for o in physical};extra=set(actual)-required
        # This explicit single-cube SIM source is an independent audit object.
        # Its GT pose never becomes the planner's obstacle estimate.
        if required-set(actual) or extra!={'PathBlockingStimulus'}:
            raise ValueError('CURRENT_WORLD_MISSING_OR_UNDECLARED_OBJECT')
        assumptions=obstacles['depth_bound']['assumptions']
        if (assumptions['static_scene_assumption']['scope']!='DECLARED_CURRENT_SIM_FIXED_WORLD_SOURCE_NOT_REAL_OR_GT_POSE' or
                actual['PathBlockingStimulus']['size_m']!=assumptions['size_upper_m']):
            raise ValueError('CONTROLLED_SIM_AUDIT_OBJECT_BINDING_REQUIRED')
        shape=('role','size_m','studs','coordinate_kind','block','slot_index','prim_path')
        if any(any(o.get(k)!=actual[o['id']].get(k) for k in shape) for o in physical):
            raise ValueError('CURRENT_PHYSICAL_SHAPE_OR_ROLE_CHANGED')
        scene['world_objects']=[deepcopy(actual[o['id']]) for o in physical]
        board=actual['SupplyBoard']
        if any(obj['world_pose']['frame_id']!=scene['frame_alignment']['world_frame_id'] for obj in scene['world_objects']):
            raise ValueError('CURRENT_WORLD_FRAME_CHANGED')
        world_base=pose_matrix(board['world_pose'])@np.linalg.inv(checked_pose(board['pose']))
        for obj in scene['world_objects']:
            if not np.allclose(world_base@checked_pose(obj['pose']),pose_matrix(obj['world_pose']),atol=1e-8,rtol=0):
                raise ValueError('CURRENT_WORLD_BASE_POSE_PAIR_INCONSISTENT')
        scene['frame_alignment']['T_world_base']=world_base.tolist()
        scene['frame_alignment']['evidence_ref']='PINNED_CURRENT_WORLD_BASE_POSE_PAIRS:'+state['owner_evidence']['sha256']
        scene['source_world_projection']=dict(owner=state['owner_evidence'],source_stamp_s=owner['world_observation_stamp_s'],
            physical_ids=sorted(required),replaced_old_perception_ids=[o['id'] for o in retired],
            independent_audit_only_ids=sorted(extra),GT_obstacle_pose_used_for_planning=False)
    selected=next(o for o in scene['world_objects'] if o['id']==base['planning_snapshot']['selected_slot_id'])
    held=tcp@rigid(state['attachment_tcp_to_block']);selected['pose']=matrix_pose(held)
    world_base=rigid(scene['frame_alignment']['T_world_base'])
    selected['world_pose']=matrix_pose(world_base@held)
    selected['world_pose']['frame_id']=scene['frame_alignment']['world_frame_id']
    for obj in deepcopy(obstacles['objects']):
        obj['world_pose']=matrix_pose(world_base@checked_pose(obj['pose']))
        obj['world_pose']['frame_id']=scene['frame_alignment']['world_frame_id']
        scene['world_objects'].append(obj)
    return docs


def derived_request(base,motion,result,snapshot):
    request=prepare_request(motion,result,snapshot,base['model_bundle']['bundle_path'])
    # Preserve the original tilt contract instead of drifting it at each stop.
    request['holding_orientation']=deepcopy(base['holding_orientation'])
    request['allow_yaw_reorientation']=base['allow_yaw_reorientation']
    request['planning_request_digest']=digest({k:v for k,v in request.items() if k!='planning_request_digest'})
    return request


def envelope_for(request,inputs,input_sha,request_sha,cursor):
    state,obs,control=(inputs[k] for k in ('state','obstacles','control'))
    audit={k:control[k] for k in ('session_id','replan_sequence','clock_basis')};audit['obstacle_snapshot_digest']=obs['digest']
    value=dict(schema='dynamic-cumotion-envelope/0.1',scope='CPU_FIXTURE_PREPARATION_NOT_GPU_REPLAN',
        audit_context=audit,planner_context=dict(state_digest=state['digest'],state_sequence=state['state_sequence'],
            obstacle_session_id=obs['obstacle_session_id'],obstacle_version=obs['version'],cancel_generation=control['cancel_generation'],
            planning_generation=control['replan_sequence'],planning_request_digest=request['planning_request_digest']),
        binding={k:request[k] for k in BINDING},cursor=cursor,inputs_sha256=input_sha,request_sha256=request_sha,
        state_stamp_s=state['source_stamp_s'],obstacle_stamp_s=obs['source_stamp_s'],
        thresholds_digest=digest(inputs['limits']),
        model_preparation=dict(status='SDK_GEOMETRY_REGEN_REQUIRED_NOT_A_MODEL_MANIFEST',source_model=request['model_bundle'],
            binding={k:request[k] for k in BINDING},grip_rad=state['grip_rad'],attachment=request['attachment'],
            world_geometry_digest=digest(request['planning_snapshot']['world_objects'])),
        execution_allowed=False,hardware_execution_allowed=False,gpu_planning_run=False)
    if 'depth_bound' in obs:
        bound=obs['depth_bound'];value.update(scope='CPU_BOUNDED_DEPTH_PREPARATION_NOT_GPU_REPLAN',perception_valid_until_s=bound['valid_until_s'],
            source_provenance=dict(source_kind=bound['source_kind'],bound_digest=bound['digest'],
                evidence_manifest_sha256=bound['evidence_spec']['manifest_sha256'],coverage=bound['checks']['coverage']))
    if inputs['limits'].get('initial_condition_mode')=='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE':
        value.update(initial_condition_mode='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE',
            solver_initial_model=dict(q_rad=deepcopy(state['q_rad']),v_rad_s=[0.]*6,a_rad_s2=[0.]*6,
                scope='MATHEMATICAL_SDK_POSITION_START_NOT_OBSERVED_ZERO_DERIVATIVES'),
            observed_state_preserved=True,physical_resume_approved=False)
    from online_cumotion_validity import online_contract
    online=online_contract(request,inputs)
    if online is not None:
        if value.get('initial_condition_mode')!='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE':
            raise ValueError('ONLINE_INPUT_REQUIRES_EXPLICIT_SDK_REST_PVT_BRIDGE')
        value['online_validity']=online
    return sealed(value,key='envelope_digest')


def prepare_inputs(base_path,state,obstacles,control,limits,*,now_s,output,previous=None):
    from prepare_cumotion_model import verify_request
    base_path=Path(base_path).resolve(strict=True);output=Path(output).resolve()
    if output.exists():raise ValueError('Never overwrite prepared inputs')
    if (base_path.parent/'dynamic_input.envelope.json').exists():raise ValueError('Use the verified original A anchor')
    base=verify_input_anchor(base_path,limits,allow_fixture_cpu=True)
    cursor=validate_packets(base,state,obstacles,control,limits,now_s,previous)
    shape_created_at=datetime.now(timezone.utc).isoformat() if 'captured_at' not in state else None
    docs=capture_documents(base,state,obstacles,artifact_created_at=shape_created_at)
    inputs=dict(base_request_path=str(base_path),base_request_sha256=file_hash(base_path),state=state,obstacles=obstacles,
                control=control,limits=limits,now_s=now_s,previous_cursor=previous)
    if shape_created_at is not None:inputs['shape_artifact_created_at']=shape_created_at
    output.mkdir(parents=True)
    for key,doc in docs.items():(output/(key+'.json')).write_text(json.dumps(doc,indent=2,allow_nan=False))
    for name in ('motion.request.json','motion.result.json'):(output/name).write_bytes((base_path.parent/name).read_bytes())
    snapshot=prepare_sim_snapshot(output/'scene.json',output/'state.json')
    request=derived_request(base,json.loads((output/'motion.request.json').read_text()),json.loads((output/'motion.result.json').read_text()),snapshot)
    (output/'TRANSPORT.request.yaml').write_text(yaml.safe_dump(request,sort_keys=False,allow_unicode=True))
    (output/'scene_context.json').write_text(json.dumps({k:request[k] for k in BINDING},indent=2))
    (output/'dynamic_inputs.json').write_text(json.dumps(inputs,indent=2,allow_nan=False))
    envelope=envelope_for(request,inputs,file_hash(output/'dynamic_inputs.json'),file_hash(output/'TRANSPORT.request.yaml'),cursor)
    (output/'dynamic_input.envelope.json').write_text(json.dumps(envelope,indent=2,allow_nan=False))
    if 'depth_bound' in obstacles and obstacles['source_kind']=='SIM_DEPTH':
        admission=bounded_sim_admission(output/'TRANSPORT.request.yaml',inputs,envelope)
        (output/'bounded_sim_admission.json').write_text(json.dumps(admission,indent=2,allow_nan=False))
    verify_request(output/'TRANSPORT.request.yaml',allow_fixture_cpu=True)
    return envelope


def verify_prepared(path,request):
    """Rebuild all fixture files, common request and envelope; no SDK escape."""
    from prepare_cumotion_model import verify_request
    folder=path.parent;inputs=json.loads((folder/'dynamic_inputs.json').read_text());base_path=Path(inputs['base_request_path'])
    if (base_path.parent/'dynamic_input.envelope.json').exists() or file_hash(base_path)!=inputs['base_request_sha256']:
        raise ValueError('ORIGINAL_A_ANCHOR_CHANGED')
    base=verify_input_anchor(base_path,inputs['limits'],allow_fixture_cpu=True)
    cursor=validate_packets(base,inputs['state'],inputs['obstacles'],inputs['control'],inputs['limits'],inputs['now_s'],inputs['previous_cursor'])
    for key,expected in capture_documents(base,inputs['state'],inputs['obstacles'],
            artifact_created_at=inputs.get('shape_artifact_created_at')).items():
        if json.loads((folder/(key+'.json')).read_text())!=expected:raise ValueError('DYNAMIC_CAPTURE_CHANGED')
    for name in ('motion.request.json','motion.result.json'):
        if file_hash(folder/name)!=file_hash(base_path.parent/name):raise ValueError('COMMON_A_MOTION_CHANGED')
    derived=derived_request(base,json.loads((folder/'motion.request.json').read_text()),json.loads((folder/'motion.result.json').read_text()),request['source_snapshot'])
    envelope=json.loads((folder/'dynamic_input.envelope.json').read_text())
    expected=envelope_for(derived,inputs,file_hash(folder/'dynamic_inputs.json'),file_hash(path),cursor)
    if envelope!=expected:raise ValueError('DYNAMIC_ENVELOPE_CHANGED')
    return derived


def check_result_context(calculated,latest,control,*,now_s,limits):
    """Context check only, never evidence that a solver or FCL actually passed."""
    check_control(control)
    for envelope in (calculated,latest):
        verify_seal(envelope,'envelope_digest')
        if (envelope['schema']!='dynamic-cumotion-envelope/0.1' or envelope['execution_allowed'] is not False
                or envelope['hardware_execution_allowed'] is not False):raise ValueError('CPU_ENVELOPE_REQUIRED')
    if calculated['envelope_digest']!=latest['envelope_digest']:raise ValueError('LATE_CALCULATION_OR_FCL_CONTEXT_REJECTED')
    for key in ('audit_context','planner_context','binding','inputs_sha256','request_sha256'):
        if calculated[key]!=latest[key]:raise ValueError('LATE_CALCULATION_OR_FCL_CONTEXT_REJECTED')
    for key in ('session_id','clock_basis','replan_sequence'):
        if control[key]!=latest['audit_context'][key]:raise ValueError('ACTIVE_CONTEXT_CHANGED')
    if control['cancel_generation']!=latest['planner_context']['cancel_generation']:raise ValueError('CANCEL_GENERATION_CHANGED')
    if now_s>latest.get('perception_valid_until_s',now_s):raise ValueError('PERCEPTION_BOUND_EXPIRED')
    if (digest(limits)!=latest['thresholds_digest'] or limits['clock_basis']!=control['clock_basis'] or any(not 0<=number(now_s)-latest[k]<=number(limits[limit])
            for k,limit in [('state_stamp_s','max_state_age_s'),('obstacle_stamp_s','max_obstacle_age_s')])):
        raise ValueError('RESULT_SNAPSHOT_EXPIRED')
    return dict(status='LOCAL_CONTEXT_MATCHED_NOT_FCL_OR_DISPATCH_APPROVAL',execution_allowed=False,hardware_execution_allowed=False)


def held_mask_context(base,state):
    obj=next(o for o in base['planning_snapshot']['world_objects'] if o['id']==base['planning_snapshot']['selected_slot_id'])
    return dict(held_geometry={k:obj[k] for k in ('id','size_m','studs','block')},grip_rad=state['grip_rad'],attachment=state['attachment_tcp_to_block'])


def depth_packet(bound,state,version,*,planner_box_representation=None):
    sim=bound['source_kind']=='SIM_DEPTH'
    packet=dict(schema='base-obstacle-snapshot/0.1',source_kind=bound['source_kind'],session_id=state['session_id'],
        obstacle_session_id=bound['source_session_id'],version=sequence(version),frame_seq=bound['frame_seq'],
        source_stamp_s=bound['source_stamp_s'],received_stamp_s=bound['received_stamp_s'],clock_basis=bound['clock_basis'],base_frame_id='base_link',
        coverage='SIM_BOUNDED_BY_DECLARED_PRIOR' if sim else 'FIXTURE_BOUNDED_BY_DECLARED_PRIOR',
        extent_provenance='REPLAYED_DEPTH_WITH_DECLARED_SIZE_ERROR_MOTION_BOUND',mask_status='REPLAYED_MASK_ARRAY_EVIDENCE',
        camera=deepcopy(bound['camera']),objects=[deepcopy(bound['geometry'])],depth_bound=bound,
        execution_allowed=False,hardware_execution_allowed=False)
    if planner_box_representation is not None:
        from depth_obstacle_envelope import planner_box_projection
        geometry,proof=planner_box_projection(bound,planner_box_representation)
        packet.update(objects=[geometry],planner_box_enclosure=proof)
    return sealed(packet)


def verify_depth_packet(base,state,obstacles,limits,now_s):
    from depth_obstacle_envelope import verify_bound,verify_sim_stop
    bound=verify_bound(obstacles['depth_bound'],base['model_bundle'],now_s=now_s)
    if bound['assumptions'].get('usage_scope')=='ARCHIVED_STATIC_SIM_CALCULATION_ONLY':
        raise ValueError('STATIC_CALCULATION_PRIOR_NOT_LIVE_OBSTACLE_HOLD_ADMISSION')
    if 'live_scene_motion_kind' in bound['assumptions']:
        live=bound['online_motion']
        if (type(limits.get('world_revision')) is not int or type(base['world_revision']) is not int or
                any(limits.get(k)!=live[k] for k in ('live_scene_motion_kind','world_revision')) or
                base['world_revision']!=live['world_revision']):
            raise ValueError('PREPARE_SCENE_MOTION_OR_WORLD_REVISION_MISMATCH')
    if owner_observations(limits):
        from online_cumotion_validity import geometry_context_review
        owner=review_owner_observations(state,limits)
        if bound['source_session_id']!=owner['session_id'] or bound['online_motion']['clock_epoch']!=owner['clock_epoch']:
            raise ValueError('SENSOR_CURRENT_OWNER_SESSION_OR_EPOCH_CHANGED')
        geometry_context_review(bound['geometry_context'],held_mask_context(base,state),computation_only=True)
    elif bound['geometry_context']!=held_mask_context(base,state):raise ValueError('BOUND_HELD_MODEL_MISMATCH')
    if obstacles!=depth_packet(bound,state,obstacles['version'],
            planner_box_representation=limits.get('planner_box_representation')):
        raise ValueError('DEPTH_PACKET_RELABELLING_OR_GEOMETRY_CHANGE')
    if bound['source_kind']=='SIM_DEPTH':verify_sim_stop(state,base['model_bundle'],limits)


def prepare_depth_inputs(base_path,state,evidence_spec,prior_path,control,limits,*,now_s,output,expected_source_kind,obstacle_version,previous=None):
    """Explicit evidence path; legacy request files remain CPU shape adapters."""
    from prepare_cumotion_model import verify_request
    from depth_obstacle_envelope import build_envelope
    base=verify_input_anchor(Path(base_path),limits,allow_fixture_cpu=True)
    context=held_mask_context(base,state)
    if owner_observations(limits):
        from depth_obstacle_envelope import evidence_files
        _,paths=evidence_files(evidence_spec)
        context=json.loads(paths['mask_audit'].read_text())['geometry_context']
    bound=build_envelope(evidence_spec,prior_path,base['model_bundle'],context,now_s=now_s)
    if bound['source_kind']!=expected_source_kind:raise ValueError('EXPLICIT_DEPTH_SOURCE_KIND_MISMATCH')
    if expected_source_kind=='SIM_DEPTH':verify_input_anchor(Path(base_path),limits)
    packet=depth_packet(bound,state,obstacle_version,
        planner_box_representation=limits.get('planner_box_representation'))
    return prepare_inputs(base_path,state,packet,control,limits,now_s=now_s,output=output,previous=previous)


def verify_input_anchor(path,limits,*,allow_fixture_cpu=False):
    source=limits.get('initial_moveit_source')
    if source is not None:
        from initial_moveit_source import verify_initial_moveit_source
        if (source.get('scope')!='INITIAL_MOVEIT_SOURCE_ONLY' or
                Path(source['request_ref']['path']).resolve()!=Path(path).resolve()):
            raise ValueError('INITIAL_MOVEIT_ANCHOR_SOURCE_ROLE_OR_PATH_CHANGED')
        return verify_initial_moveit_source(source['request_ref'],source['result_ref'])['initial_request']
    from prepare_cumotion_model import verify_request
    return verify_request(path,allow_fixture_cpu=allow_fixture_cpu,
        allow_geometry_cpu=limits.get('initial_condition_mode')=='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE')


def bounded_sim_admission(path,inputs,envelope):
    """Explicit source sidecar; legacy shape projection keeps its fixture tag."""
    from prepare_cumotion_model import verify_request
    base=verify_input_anchor(Path(inputs['base_request_path']),inputs['limits'])
    obs=inputs['obstacles'];state=inputs['state'];bound=obs['depth_bound']
    if (obs['source_kind']!='SIM_DEPTH' or bound['source_kind']!='SIM_DEPTH' or
            state['source_kind']!='SIM_SAVED_SNAPSHOT' or
            base['simulation_provenance']['source_kind']!='ISAAC_SIM_SAVED_STATE'):
        raise ValueError('BOUNDED_SIM_ADMISSION_CANNOT_PROMOTE_FIXTURE')
    # Replayed by verify_prepared/validate_packets before this function on read.
    return sealed(dict(schema_version='bounded-sim-depth-admission/0.1',source_kind='BOUNDED_SIM_DEPTH_SNAPSHOT',
        request_sha256=file_hash(path),inputs_sha256=file_hash(path.parent/'dynamic_inputs.json'),
        envelope_sha256=file_hash(path.parent/'dynamic_input.envelope.json'),
        source_capture=bound['evidence_spec'],prior_sha256=file_hash(bound['prior_path']),
        model_manifest_sha256=base['model_bundle']['manifest_sha256'],
        audit_context=envelope['audit_context'],planner_context=envelope['planner_context'],
        valid_until_s=bound['valid_until_s'],execution_allowed=False,hardware_execution_allowed=False))


def verify_bounded_sim_admission(path,*,now_s=None):
    inputs=json.loads((path.parent/'dynamic_inputs.json').read_text())
    envelope=json.loads((path.parent/'dynamic_input.envelope.json').read_text())
    actual=json.loads((path.parent/'bounded_sim_admission.json').read_text())
    if actual!=bounded_sim_admission(path,inputs,envelope):raise ValueError('BOUNDED_SIM_ADMISSION_CHANGED')
    from prepare_cumotion_model import verify_request
    base=verify_input_anchor(Path(inputs['base_request_path']),inputs['limits'])
    # At a real worker boundary the caller must supply current source-clock time
    # and active context. Saved now_s supports CPU replay only, not dispatch.
    check_now=inputs['now_s'] if now_s is None else now_s
    validate_packets(base,inputs['state'],inputs['obstacles'],inputs['control'],inputs['limits'],check_now,inputs['previous_cursor'])
    check_result_context(envelope,envelope,inputs['control'],now_s=check_now,limits=inputs['limits'])
    return actual
