"""Staged LIVE caller contract; no SDK/model admission, dispatcher or Kit calls.

MI must implement both callbacks at its existing synchronized main-thread
boundary. A saved publication is never itself a current source provider.
"""
from copy import deepcopy
from pathlib import Path
import math
import time
import yaml
from bounded_sim_evidence import pinned_json
from prepare_cpu_model import file_hash
from moveit_stop_cumotion_inputs import _prepare_moveit_stop_inputs

LIVE='LIVE_INPUT_PREPARATION_ONLY'
CLOCK='native-current-source-clock/1.0'


def hold(status,**details):
    return dict(status=status,request_draft=None,selected_job=None,selected_cache=None,
        SDK_READY=False,READY=False,apply_allowed=False,execution_allowed=False,
        hardware_execution_allowed=False,live_source_verified=False,**details)


def observed_stop_start(owner):
    return dict(q_rad=deepcopy(owner['q_rad']),grip_rad=owner['grip_rad'],
        attachment_tcp_to_block=deepcopy(owner['attachment_tcp_to_block']),
        raw_observed_v_rad_s=deepcopy(owner['v_rad_s']),raw_or_explicit_derived_a_rad_s2=deepcopy(owner['a_rad_s2']),
        role='LATEST_OBSERVED_STOP_FIELDS_NOT_OLD_INITIAL_COMMAND_OR_NEW_COMMAND_PVT')


def current_clock(provider):
    requested_wall=time.monotonic()
    value=provider()
    returned_wall=time.monotonic()
    if not isinstance(value,dict) or value.get('schema')!=CLOCK or value.get('clock_basis')!='SIM_TIME':
        raise ValueError('CURRENT_NATIVE_CLOCK_PROVIDER_REQUIRED_NOT_SAVED_OWNER_NOW')
    native=value['native_stamp']
    if not isinstance(value.get('session_id'),str) or not value['session_id']:
        raise ValueError('CURRENT_NATIVE_SESSION_REQUIRED')
    for number in (value['source_s'],value['observed_wall_monotonic_s'],native['world_time_s'],
                   native['native_simulation_time_s'],native['wall_monotonic_s']):
        if type(number) not in (float,int) or not math.isfinite(number):raise ValueError('FINITE_CURRENT_NATIVE_CLOCK_REQUIRED')
    if value['source_s']!=native['world_time_s']:raise ValueError('CLOCK_MUST_USE_ORIGINAL_NATIVE_WORLD_TIME')
    if (type(value['clock_epoch']) is not int or type(native['native_physics_step_index']) is not int or
            value['clock_epoch']<0 or native['native_physics_step_index']<0):
        raise ValueError('CURRENT_CLOCK_EPOCH_AND_PHYSICS_SEQUENCE_REQUIRED')
    rational=native['native_current_reference_time']
    if len(rational)!=2 or any(type(v) is not int for v in rational) or rational[1]<=0:
        raise ValueError('ORIGINAL_NATIVE_RATIONAL_TIME_REQUIRED')
    if not native['wall_monotonic_s']<=value['observed_wall_monotonic_s']<=returned_wall:
        raise ValueError('CURRENT_CLOCK_WALL_OBSERVATION_ORDER_CHANGED')
    if native['wall_monotonic_s']<requested_wall:
        raise ValueError('CURRENT_CLOCK_SAMPLE_NOT_FROM_THIS_PROVIDER_READ')
    return value


def review_clock_progress(before,after):
    if any(type(before[k]) is not type(after[k]) or before[k]!=after[k] for k in ('session_id','clock_basis','clock_epoch')):
        raise ValueError('CURRENT_SOURCE_CLOCK_IDENTITY_CHANGED')
    if (after['source_s']<before['source_s'] or
            after['native_stamp']['native_physics_step_index']<before['native_stamp']['native_physics_step_index']):
        raise ValueError('CURRENT_SOURCE_CLOCK_REVERSED')


def review_source_ages(owner,frame,now):
    if not 0<=now-owner['state_stamp_s']<=.12 or not 0<=now-frame['source_stamp_s']<=.12:
        raise ValueError('CURRENT_STOP_OR_CAPTURE_STALE_NOT_HISTORICAL_OWNER_AGE')
    if owner['now_s']>now:raise ValueError('OWNER_PUBLICATION_FROM_FUTURE')


def review_symbolic_unknown(geometry_ref,depth_ref,frame_ref,map_digest):
    if geometry_ref is None:return None
    g=pinned_json(geometry_ref)
    if g.get('schema')!='depth-symbolic-unknown-occupancy/1.0':return None
    if any(g.get(k)!=v for k,v in dict(detector_ref=depth_ref,frame_ref=frame_ref,map_digest=map_digest).items()):
        raise ValueError('SYMBOLIC_UNKNOWN_SOURCE_CHANGED')
    if (g.get('unknown_occupancy')!='ALL_UNCERTIFIED_SPACE' or g.get('objects') is not None or
            g.get('proven_free_region_count')!=0 or
            g.get('unknown_is_free') is not False or g.get('clearance_query_status')!='UNKNOWN_BLOCKED' or
            any(g.get(k) is not False for k in ('SDK_READY','READY','apply_allowed','execution_allowed','risk_qualified','world_clear_allowed'))):
        raise ValueError('SYMBOLIC_UNKNOWN_CANNOT_PROMOTE_TO_FREE_OR_OCCUPIED_CERTIFICATE')
    if g.get('query_domain_ref') is not None:pinned_json(g['query_domain_ref'])
    return hold('WAIT_UNKNOWN_OCCUPANCY_NO_CLEARANCE_CERTIFICATE',collision_confirmed=False,
        unknown_occupancy='ALL_UNCERTIFIED_SPACE',geometry_ref=geometry_ref,query_domain_ref=g.get('query_domain_ref'))


def prepare_conservative_stop_contact(config):
    """Consume the existing pinned R helper packet; no LIVE or world admission."""
    from dynamic_cumotion_inputs import (CONSERVATIVE_FOREGROUND_PROFILE,
        select_owner_input_limits,normalize_owner_stop_state,validate_stopped_state,
        verify_seal,check_control)
    from plan_only import digest
    if config.get('owner_packet_profile')!=CONSERVATIVE_FOREGROUND_PROFILE:
        raise ValueError('EXPLICIT_CONSERVATIVE_CALLER_PROFILE_REQUIRED')
    packet_ref=config.get('conservative_stop_packet_ref')
    if packet_ref is None:return hold('WAIT_PINNED_CONSERVATIVE_STOP_SOURCE_PACKET')
    packet=pinned_json(packet_ref);verify_seal(packet)
    if (packet.get('schema')!='conservative-stop-source-mapping/1.0' or
            packet.get('scope')!='SAVED_STOP_MAPPING_ONLY_NOT_LIVE_ADMISSION'):
        raise ValueError('CONSERVATIVE_SOURCE_MAPPING_ROLE_REQUIRED')
    source_refs=packet['source_refs'];refs=config['refs']
    for source,key in (('owner','owner'),('policy','owner_limits'),('accepted','accepted'),
            ('original_request','anchor_request'),('accepted_wire','accepted_wire')):
        if source_refs[source]!=refs[key]:raise ValueError('CONSERVATIVE_CALLER_SOURCE_REF_CHANGED:'+source)
    if packet['state']['frame_input_ref']!=refs['depth_frame']:
        raise ValueError('CONSERVATIVE_CALLER_FRAME_CHANGED')
    owner=pinned_json(refs['owner'])
    from online_cumotion_validity import IDENTITY
    expected=config['expected_identity']
    if set(expected)!=set(IDENTITY) or any(type(owner[k]) is not type(expected[k]) or owner[k]!=expected[k] for k in IDENTITY):
        raise ValueError('EXPECTED_CURRENT_OWNER_IDENTITY_CHANGED')
    if (digest(packet['source_owner_context'])!=digest(owner) or
            digest(packet['original_accepted'])!=digest(pinned_json(refs['accepted']))):
        raise ValueError('CONSERVATIVE_CALLER_ORIGINAL_OWNER_OR_ACCEPTED_CHANGED')
    limits=select_owner_input_limits(refs['owner'],None,None,
        owner_packet_profile=config['owner_packet_profile'],conservative_source_refs=source_refs)
    model=yaml.safe_load(Path(refs['anchor_request']['path']).read_text())['model_bundle']
    state=normalize_owner_stop_state(packet['state'],limits,model,packet_ref)
    control=packet['control'];check_control(control)
    if any(digest(value)!=digest(owner[key]) for key,value in control.items()):
        raise ValueError('CONSERVATIVE_CALLER_CONTROL_CHANGED')
    validate_stopped_state(state,control,limits)
    if file_hash(packet_ref['path'])!=packet_ref['sha256']:
        raise ValueError('CONSERVATIVE_CALLER_PACKET_CHANGED_DURING_READ')
    return hold('CONSERVATIVE_STOP_PACKET_CONTACT_CHECKED_NOT_LIVE_ADMISSION',
        normalized_state=state,control=deepcopy(control),limits_delta=limits,
        source_packet_ref=deepcopy(packet_ref),raw_state_digest=state['state_normalization']['raw_state_digest'],
        full_input_policy_selected=False)


def prepare_live_current_inputs(config,*,initial_source_review=None,capture_provider=None,source_clock_provider=None,
        compact_point_provider=None,compact_reader_scope='ISOLATED_SIM_COMPACT_STOP_INPUT',output):
    """Use pure historical source review, then independently current STOP inputs.

    capture_provider() must return ref|None ONLY while current D UUID/version,
    Current/reservation/model/goal, STOP/holding/count0/latches still match it.
    clock_provider() must sample native time through MI, never owner.now_s.
    Providers do not exist on the current foreground route until MI integrates
    and R reviews them. Their contract is not certified by passing a lambda.
    """
    if config.get('scope')!=LIVE:raise ValueError('EXPLICIT_LIVE_CALLER_SCOPE_REQUIRED')
    profile=config.get('owner_packet_profile')
    if profile is not None:
        from dynamic_cumotion_inputs import CONSERVATIVE_FOREGROUND_PROFILE
        if profile!=CONSERVATIVE_FOREGROUND_PROFILE:raise ValueError('UNKNOWN_OWNER_PACKET_PROFILE')
    if not callable(capture_provider) or not callable(source_clock_provider):
        return hold('WAIT_MI_CURRENT_PROVIDER_BINDING')
    # Check the clock product shape before any historical source work.
    before=current_clock(source_clock_provider)
    review=initial_source_review
    if review is None:return hold('WAIT_SEPARATE_INITIAL_MOVEIT_PROVENANCE_REVIEW')
    refs=config['refs']
    if (review.get('scope')!='VERIFIED_INITIAL_MOVEIT_SOURCE_ONLY' or review.get('normal_CU_model_request') is not False or
            review['request_ref']!=refs['anchor_request'] or review['result_ref']!=refs['initial_result']):
        raise ValueError('HISTORICAL_SOURCE_ROLE_IS_NOT_A_NEW_CU_MODEL_REQUEST')
    for item in review['source_pins']:
        if file_hash(item['path'])!=item['sha256']:raise ValueError('INITIAL_SOURCE_REVIEW_INPUT_CHANGED')
    if review['initial_request']!=yaml.safe_load(Path(refs['anchor_request']['path']).read_text()):
        raise ValueError('INITIAL_SOURCE_REVIEW_BODY_CHANGED')
    capture_ref=capture_provider()
    if capture_ref is None:return hold('WAIT_CURRENT_COMPLETE_STOPPED_CAPTURE')
    capture=pinned_json(capture_ref)
    if capture['scope']!='SAME_ORIGINAL_CAPTURE_FOR_NONEXECUTABLE_STOP_OWNER' or capture['recaptured'] is not False:
        raise ValueError('ORIGINAL_CURRENT_CAPTURE_REQUIRED')
    publication=pinned_json(capture['owner_publication']);bundle=pinned_json(capture['selected_raw_bundle'])
    owner=pinned_json(publication['owner_ref']);frame=pinned_json(capture['frame_input'])
    if (publication['owner_ref']!=refs['owner'] or publication['owner_limits_ref']!=refs['owner_limits'] or
            capture['frame_input']!=refs['depth_frame'] or bundle['frame_input_ref']!=refs['depth_frame']):
        return hold('WAIT_COHERENT_CURRENT_SOURCE_SELECTION')
    now=current_clock(source_clock_provider);review_clock_progress(before,now)
    if any(now[k]!=owner[k] for k in ('session_id','clock_basis','clock_epoch')):
        raise ValueError('LIVE_OWNER_CURRENT_CLOCK_IDENTITY_CHANGED')
    if now['native_stamp']['native_physics_step_index']<owner['state_sequence']:
        raise ValueError('LIVE_OWNER_FROM_FUTURE_NATIVE_STEP')
    review_source_ages(owner,frame,now['source_s'])
    if profile is not None:
        contact=prepare_conservative_stop_contact(config)
        after=current_clock(source_clock_provider);review_clock_progress(now,after)
        if capture_provider()!=capture_ref:return hold('WAIT_CURRENT_D_BINDING_OR_CAPTURE_CHANGED')
        review_source_ages(owner,frame,after['source_s'])
        if contact['status']!='CONSERVATIVE_STOP_PACKET_CONTACT_CHECKED_NOT_LIVE_ADMISSION':return contact
        from compact_point_receiver import review_current_compact_input
        compact=review_current_compact_input(config,compact_point_provider=compact_point_provider,
            capture_provider=capture_provider,source_clock_provider=source_clock_provider,scope=compact_reader_scope)
        final=current_clock(source_clock_provider);review_clock_progress(after,final)
        if capture_provider()!=capture_ref:return hold('WAIT_CURRENT_D_BINDING_OR_CAPTURE_CHANGED')
        review_source_ages(owner,frame,final['source_s'])
        if not compact['payload_verified']:
            return hold(compact['status'],stop_packet_contact=contact,compact_input_review=compact)
        return hold('WAIT_CURRENT_WORLD_GEOMETRY_ADMISSION',
            stop_packet_contact=contact,compact_input_review=compact,source_checks_at_s=final['source_s'],
            pending_start_fields=observed_stop_start(owner),
            remaining=['independent sensor/pose/world policy and current full geometry proof',
                'actual runtime providers/receipt evidence; CPU scope is never LIVE readiness'])
    receipt_ref=config.get('runtime_point_completion_ref')
    if receipt_ref is None:return hold('WAIT_RUNTIME_PROJECTED_DEPTH_PRODUCT_NOT_OFFLINE_POINTS')
    point=pinned_json(receipt_ref);depth=pinned_json(refs['depth'])
    if (point['frame_input']!=refs['depth_frame'] or point['summary'].get('projected_digest')!=depth['digest'] or
            point['summary'].get('projected_available') is not True or point.get('completion_fresh') is not True or
            point.get('identity_verified') is not True or point.get('source_order_verified') is not True or
            point['summary'].get('guard') is not False or
            any(type(point[k]) is not type(frame[k]) or point[k]!=frame[k] for k in ('session_id','clock_epoch','frame_seq','source_stamp_s')) or
            any(point['completion_observation'][k]!=now[k] for k in ('session_id','clock_basis','clock_epoch')) or
            point['completion_observation']['source_s']>now['source_s'] or
            not 0<=now['source_s']-point['source_stamp_s']<=.12):
        raise ValueError('LIVE_RUNTIME_POINT_PRODUCT_STALE_MISMATCHED_OR_UNAVAILABLE')
    result=_prepare_moveit_stop_inputs(config,now_source_s=now['source_s'],output=output,initial_source_review=review)
    after=current_clock(source_clock_provider);review_clock_progress(now,after)
    if capture_provider()!=capture_ref:return hold('WAIT_CURRENT_D_BINDING_OR_CAPTURE_CHANGED')
    review_source_ages(owner,frame,after['source_s'])
    symbolic=review_symbolic_unknown(refs.get('obstacle_geometry'),refs['depth'],refs['depth_frame'],config['expected_known_map_digest'])
    if symbolic is not None:result=symbolic
    # Even populated generic geometry is still WAIT_GENERIC_... in the original
    # gate. It cannot authorize capture_documents/prepare_inputs/SDK jobs here.
    result.update(request_draft=None,selected_job=None,selected_cache=None,live_source_verified=False,
        source_role='INITIAL_MOVEIT_PROVENANCE_SEPARATE_FROM_NEW_CU_REQUEST',
        pending_start_fields=observed_stop_start(owner),
        source_checks_at_s=after['source_s'],SDK_READY=False,READY=False,apply_allowed=False,execution_allowed=False)
    return result
