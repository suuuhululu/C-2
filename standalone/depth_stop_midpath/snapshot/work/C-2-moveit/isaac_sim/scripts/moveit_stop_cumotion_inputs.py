"""File-only generic MoveIt-stop CU preparation; no complete-world inference.

Produces a KNOWN_ONLY request draft and explicit missing-geometry reasons.
It cannot admit a job, run SDK/FCL or authorize execution.
"""
from copy import deepcopy
from datetime import datetime,timezone
import argparse,hashlib,json,math
from pathlib import Path
import yaml
from bounded_sim_evidence import pinned_json
from plan_only import BINDING,JOINTS,digest,prepare_d_candidate,vector
from prepare_cpu_model import file_hash
from sim_utils import rigid
from dynamic_cumotion_inputs import capture_documents,derived_request,sealed
from prepare_sim_snapshot import prepare_sim_snapshot

SAVED_SCOPE='SAVED_ACTUAL_SIM_CPU_PREPARATION'


def saved_actual_evaluation(config,now_source_s):
    """Use a pinned original submission or actual owner publication clock."""
    receipt_ref=config.get('saved_actual_evaluation_ref')
    if receipt_ref is None:raise ValueError('SAVED_ACTUAL_ORIGINAL_EVALUATION_REF_REQUIRED')
    receipt=pinned_json(receipt_ref)
    frame_ref=config['refs']['depth_frame'];frame=pinned_json(frame_ref)
    if receipt_ref==config['refs'].get('owner'):
        if (receipt['snapshot_version']!=frame['frame_seq'] or receipt['snapshot_digest']!=spaced_digest(frame) or
                any(type(receipt[k]) is not type(frame[k]) or receipt[k]!=frame[k] for k in ('session_id','clock_basis','clock_epoch')) or
                receipt['state_stamp_s']!=frame['robot_state_stamp_s'] or receipt['state_stamp_s']!=frame['transform_stamp_s']):
            raise ValueError('SAVED_ACTUAL_OWNER_EVALUATION_FRAME_CHANGED')
        recorded_now=receipt['now_s'];basis='ORIGINAL_D_OWNER_PUBLICATION_CLOCK'
    else:
        if receipt['frame_input']!=frame_ref or receipt.get('source_associated') is not True or receipt['source_stamp_s']!=frame['source_stamp_s']:
            raise ValueError('SAVED_ACTUAL_EVALUATION_FRAME_CHANGED')
        recorded_now=receipt['submitted_source_s'];basis='ORIGINAL_PROJECTION_SUBMISSION_CLOCK'
    if type(recorded_now) is not type(now_source_s) or recorded_now!=now_source_s:
        raise ValueError('SAVED_ACTUAL_ORIGINAL_EVALUATION_TIME_REQUIRED')
    if not 0<=now_source_s-frame['source_stamp_s']<=.12:
        raise ValueError('SAVED_ACTUAL_ORIGINAL_DEPTH_STALE')
    return dict(scope=SAVED_SCOPE,evaluation_ref=receipt_ref,frame_ref=frame_ref,
        historical_evaluation_source_s=now_source_s,evaluation_basis=basis,current_live_freshness_claim=False)


def review_saved_conservative_stop(config,owner,limits):
    """Load only the explicitly pinned R stage, without replacing live imports."""
    from importlib.util import spec_from_file_location,module_from_spec
    item=config.get('staged_stop_review_source')
    if item is None:raise ValueError('PINNED_R_STAGED_REVIEW_SOURCE_REQUIRED')
    if ref(item['path'])!=item:raise ValueError('R_STAGED_REVIEW_SOURCE_CHANGED')
    spec=spec_from_file_location('isaac_sim.real_execution._cu_saved_stop_review',item['path'])
    module=module_from_spec(spec);spec.loader.exec_module(module)
    return module.review_conservative_stop(owner,limits)


def review_actual_source_tick(frame,state_stamp_s):
    """Compare raw world-state stamps and actual counters; keep image time separate."""
    a=frame['source_association']
    steps=[a[k] for k in ('physics_step_index','state_physics_step_index','tf_physics_step_index','image_physics_step_index')]
    if (a.get('same_tick_verified') is not True or a.get('physical_source_pair_verified') is not True or
            any(type(v) is not int or v!=steps[0] for v in steps)):
        raise ValueError('SAVED_ACTUAL_SAME_PHYSICS_TICK_REQUIRED')
    if state_stamp_s!=frame['robot_state_stamp_s'] or state_stamp_s!=frame['transform_stamp_s']:
        raise ValueError('SAVED_ACTUAL_ORIGINAL_WORLD_STATE_STAMP_REQUIRED')


def ref(path):return dict(path=str(Path(path).resolve()),sha256=file_hash(Path(path)))

def spaced_digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def write(path,value):
    with Path(path).open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)


def read_known_map_source(item):
    """Read either existing CU view or Depth's saved consumer inventory.

    Preserve the producer's file/ref/digest. Only the in-memory key spelling is
    adapted; metadata-only exports without a bound digest are not sufficient.
    """
    source=pinned_json(item)
    if 'metadata' not in source:raise ValueError('KNOWN_MAP_CONSUMER_METADATA_AND_DIGEST_REQUIRED')
    declared=[source[k] for k in ('digest','map_digest') if k in source]
    if not declared or any(v!=declared[0] for v in declared) or spaced_digest(source['metadata'])!=declared[0]:
        raise ValueError('KNOWN_MAP_DIGEST_CHANGED')
    return dict(metadata=source['metadata'],digest=declared[0])


def geometry_wait(geometry_ref,depth_ref,frame_ref,map_digest,now_s):
    if geometry_ref is None:
        return 'WAIT_MISSING_OBSTACLE_GEOMETRY',[
            'obstacle_geometry_ref: depth-derived conservative occupied collision objects',
            'coverage/observability/hidden-volume evidence refs',
            'uncertainty bound and independent motion_bound_ref',
            'source frame/detection/map refs and valid_until_s']
    g=pinned_json(geometry_ref)
    if g.get('detector_ref')!=depth_ref or g.get('frame_ref')!=frame_ref or g.get('map_digest')!=map_digest:
        raise ValueError('OBSTACLE_GEOMETRY_SOURCE_CHANGED')
    if (g.get('source_kind')!='DEPTH_DERIVED_OCCUPIED_GEOMETRY' or
            g.get('coverage')!='CONSERVATIVE_OCCUPIED_VOLUME_WITH_OCCLUSION_MODEL' or not g.get('objects')):
        return 'WAIT_PARTIAL_OBSTACLE_GEOMETRY',['full conservative occupied volume; visible points are insufficient']
    missing=[k for k in ('observability_ref','uncertainty_ref','motion_bound_ref','valid_until_s') if g.get(k) is None]
    if missing:return ('WAIT_MISSING_INDEPENDENT_MOTION_BOUND' if 'motion_bound_ref' in missing else 'WAIT_MISSING_OBSTACLE_GEOMETRY_BOUNDS'),missing
    for k in ('observability_ref','uncertainty_ref'):pinned_json(g[k])
    motion=pinned_json(g['motion_bound_ref']);speed=motion.get('max_speed_m_s')
    if (type(speed) not in (int,float) or not math.isfinite(speed) or speed<0 or
            motion.get('basis_kind') not in ('OBSERVED_MOTION_AND_OCCLUSION_BOUND','INDEPENDENT_PHYSICAL_CONSTRAINT') or
            not motion.get('evidence_refs')):
        return 'WAIT_MISSING_INDEPENDENT_MOTION_BOUND',['motion_bound_ref.max_speed_m_s/basis_kind/evidence_refs; no scenario speed0 default']
    for item in motion['evidence_refs']:
        if ref(item['path'])!=item:raise ValueError('MOTION_SOURCE_CHANGED')
    if speed==0 and motion['basis_kind']!='INDEPENDENT_PHYSICAL_CONSTRAINT':
        return 'WAIT_UNPROVEN_ZERO_SPEED_BOUND',['independent physical constraint evidence for zero upper bound']
    if type(g['valid_until_s']) not in (int,float) or not math.isfinite(g['valid_until_s']) or g['valid_until_s']<=now_s:
        return 'WAIT_OBSTACLE_GEOMETRY_EXPIRED',['current source-clock valid_until_s']
    # Full producer proof/replay and generic live admission are not implemented
    # by this file. A bag of objects plus declared bounds cannot bypass them.
    return 'WAIT_GENERIC_GEOMETRY_PROOF_AND_D_ADMISSION',[
        'independent replay of occupied volume/uncertainty/occlusion proof',
        'generic latest-world FCL/encoded validation and same-D selected job']


def prepare_moveit_stop_inputs(config,*,now_source_s,output):
    if config.get('scope')=='LIVE_INPUT_PREPARATION_ONLY':
        raise ValueError('LIVE_CURRENT_SOURCE_CALLER_REQUIRED_NOT_SAVED_NOW')
    evaluation=None
    if config.get('scope')==SAVED_SCOPE:
        evaluation=saved_actual_evaluation(config,now_source_s)
    result=_prepare_moveit_stop_inputs(config,now_source_s=now_source_s,output=output)
    if evaluation is not None:
        result.update(scope=SAVED_SCOPE,saved_actual_evaluation=evaluation,live_job_eligible=False,request_draft=None)
        for key in ('SDK_READY','READY','apply_allowed','execution_allowed','hardware_execution_allowed'):
            if result.get(key) is not False:raise ValueError('SAVED_ACTUAL_NONEXECUTABLE_RESULT_REQUIRED:'+key)
    return result


def _prepare_moveit_stop_inputs(config,*,now_source_s,output,initial_source_review=None):
    if type(now_source_s) not in (int,float) or not math.isfinite(now_source_s):raise ValueError('FINITE_CURRENT_SOURCE_CLOCK_REQUIRED')
    if config.get('max_depth_age_s')!=.12:raise ValueError('ORIGINAL_DEPTH_FRESHNESS_POLICY_REQUIRED')
    scope=config['scope']
    if scope not in ('CPU_FIXTURE_PREPARATION','ARCHIVED_OFFLINE_CALCULATION','LIVE_INPUT_PREPARATION_ONLY',SAVED_SCOPE):
        raise ValueError('EXPLICIT_NONEXECUTABLE_INPUT_SCOPE_REQUIRED')
    refs=config['refs'];needed=('anchor_request','initial_result','accepted','accepted_wire','owner','owner_limits','known_map','depth','depth_frame')
    missing=[k for k in needed if not refs.get(k)]
    if missing:return dict(status='WAIT_MISSING_MOVEIT_STOP_INPUT_REFS',missing=missing,SDK_READY=False,READY=False,apply_allowed=False,execution_allowed=False,hardware_execution_allowed=False)
    for key in needed:
        if ref(refs[key]['path'])!=refs[key]:raise ValueError('SOURCE_CHANGED:'+key)
    from prepare_cumotion_model import verify_request
    if initial_source_review is not None:
        if (scope!='LIVE_INPUT_PREPARATION_ONLY' or initial_source_review.get('scope')!='VERIFIED_INITIAL_MOVEIT_SOURCE_ONLY' or
                initial_source_review['request_ref']!=refs['anchor_request'] or initial_source_review['result_ref']!=refs['initial_result']):
            raise ValueError('LIVE_INITIAL_SOURCE_REVIEW_ROLE_OR_PIN_CHANGED')
        base=initial_source_review['initial_request']
    elif scope==SAVED_SCOPE and 'controller_command_start' in yaml.safe_load(Path(refs['anchor_request']['path']).read_text()):
        from saved_initial_moveit_anchor import verify_saved_initial_moveit_anchor
        base=verify_saved_initial_moveit_anchor(refs['anchor_request'],refs['initial_result'],scope=scope)
    else:
        base=verify_request(Path(refs['anchor_request']['path']),allow_fixture_cpu=scope=='CPU_FIXTURE_PREPARATION',allow_geometry_cpu=True)
    initial=yaml.safe_load(Path(refs['initial_result']['path']).read_text())
    if initial.get('result_provenance')!='MOVEIT_LOCAL_PLANNING_RESULT':raise ValueError('FRESH_MOVEIT_INITIAL_RESULT_REQUIRED')
    if initial_source_review is None:prepare_d_candidate(initial,base,{k:base[k] for k in BINDING})
    accepted=pinned_json(refs['accepted']);owner=pinned_json(refs['owner']);limits=pinned_json(refs['owner_limits'])
    if accepted.get('original_request')!=refs['anchor_request']:
        return dict(status='WAIT_MISSING_MOVEIT_ACCEPTED_REQUEST_LINK',missing=['accepted.original_request exact path+SHA; current accepted binding does not publish this yet'],SDK_READY=False,READY=False,apply_allowed=False,execution_allowed=False,hardware_execution_allowed=False)
    if accepted.get('scope')!='ACCEPTED_NATIVE_GOAL_BINDING' or accepted['model_digest']!=base['model_digest'] or accepted['active_wire_digest']!=digest(pinned_json(refs['accepted_wire'])):
        raise ValueError('MOVEIT_ACCEPTED_WIRE_MODEL_CHANGED')
    for k in ('session_id','clock_basis','clock_epoch','goal_id','goal_version'):
        if type(owner[k]) is not type(accepted[k]) or owner[k]!=accepted[k]:raise ValueError('STOP_NOT_SAME_ACCEPTED_UUID_OR_CLOCK:'+k)
    from online_cumotion_validity import IDENTITY
    if set(config['expected_identity'])!=set(IDENTITY) or any(type(owner[k]) is not type(config['expected_identity'][k]) or owner[k]!=config['expected_identity'][k] for k in IDENTITY):raise ValueError('EXPECTED_CURRENT_OWNER_IDENTITY_CHANGED')
    if owner['a_context']!=base['a_context'] or owner['reservation_binding']!=base['reservation_binding']:
        raise ValueError('ORIGINAL_A_CURRENT_RESERVATION_CHANGED')
    from isaac_sim.real_execution.native_boundary import review_stop
    for k in ('max_stop_velocity_rad_s','max_stop_acceleration_rad_s2','q_tolerance_rad','v_tolerance_rad_s','a_tolerance_rad_s2'):
        v=limits.get(k)
        if not (v is None or isinstance(v,dict) and v.get('value') is None and v.get('check_mode')=='REPORT_ONLY' and v.get('source_category')=='OFFICIAL_NOT_DEFINED'):
            raise ValueError('GENERIC_OBSERVATIONS_REQUIRE_EXPLICIT_NULL_REPORT_ONLY:'+k)
        if k not in limits:raise ValueError('MISSING_OWNER_OBSERVATION_POLICY:'+k)
    if limits['max_state_age_s']!=.12:raise ValueError('ORIGINAL_OWNER_STATE_FRESHNESS_POLICY_REQUIRED')
    if scope==SAVED_SCOPE:
        if owner['stop_record'].get('stop_reason')!='FRESH_FOREGROUND_CONSERVATIVE_STOP':
            raise ValueError('SAVED_ACTUAL_CONSERVATIVE_STOP_CAUSE_REQUIRED')
        review_saved_conservative_stop(config,owner,limits)
    elif owner['stop_record'].get('stop_reason')=='FRESH_FOREGROUND_CONSERVATIVE_STOP':
        from isaac_sim.real_execution.native_boundary import review_conservative_stop
        review_conservative_stop(owner,limits)
    else:review_stop(owner,limits)
    if not 0<=now_source_s-owner['state_stamp_s']<=limits['max_state_age_s']:raise ValueError('CURRENT_STOP_STATE_STALE')
    allowed_map={'CPU_FIXTURE_PREPARATION':('FIXTURE',),'ARCHIVED_OFFLINE_CALCULATION':('ARCHIVED_SUBSET_REPLAY_ONLY','PRE_OBSTACLE_APPROVED'),'LIVE_INPUT_PREPARATION_ONLY':('PRE_OBSTACLE_APPROVED',),SAVED_SCOPE:('PRE_OBSTACLE_APPROVED',)}[scope]
    known=read_known_map_source(refs['known_map']);m=known['metadata']
    if (known['digest']!=config['expected_known_map_digest'] or m['session_id']!=owner['session_id'] or
            m['clock_epoch']!=owner['clock_epoch'] or m['model_manifest_sha256']!=base['model_bundle']['manifest_sha256'] or
            m['map_scope'] not in allowed_map):
        raise ValueError('KNOWN_MAP_OWNER_OR_ORIGINAL_MODEL_CHANGED')
    if not m['source_refs']:raise ValueError('PINNED_KNOWN_MAP_SOURCE_INVENTORY_REQUIRED')
    if not m['freeze_source_time']<=owner['state_stamp_s']:raise ValueError('KNOWN_MAP_FREEZE_FROM_FUTURE')
    for item in m['source_refs']:
        if ref(item['path'])!=item:raise ValueError('KNOWN_MAP_SOURCE_CHANGED')
    from held_geometry_inputs import nominal_definition
    selected=next(o for o in base['planning_snapshot']['world_objects'] if o['id']==base['planning_snapshot']['selected_slot_id'])
    if m['held_definition']!=nominal_definition(selected,base['model_bundle']):raise ValueError('KNOWN_MAP_SELECTED_HELD_GEOMETRY_CHANGED')
    physical={o['id']:o for o in base['planning_snapshot']['world_objects'] if o['id']!=base['planning_snapshot']['selected_slot_id']}
    current={o['id']:o for o in m['static_objects']}
    if len(current)!=len(m['static_objects']) or set(current)!=set(physical) or set(m['approved_static_ids'])!=set(physical):
        raise ValueError('KNOWN_PHYSICAL_INVENTORY_MISSING_OR_EXTRA')
    for name,obj in physical.items():
        if any(obj.get(k)!=current[name].get(k) for k in ('role','size_m','studs','block','slot_index','prim_path')):
            raise ValueError('KNOWN_PHYSICAL_GEOMETRY_CHANGED:'+name)
    depth=pinned_json(refs['depth']);frame=pinned_json(refs['depth_frame'])
    if depth.get('schema')!='base-visible-depth-candidates/0.1' or depth.get('world_clear_allowed') is not False:raise ValueError('EXPLICIT_PARTIAL_DEPTH_CANDIDATES_REQUIRED')
    if depth['digest']!=spaced_digest({k:v for k,v in depth.items() if k!='digest'}):raise ValueError('DEPTH_PROJECTED_DIGEST_CHANGED')
    if depth['map_digest']!=known['digest'] or depth.get('detector_kind')!='EXPECTED_ACTUAL_DEPTH_DIFFERENCE':raise ValueError('DEPTH_NOT_THIS_UNLABELLED_KNOWN_MAP')
    for v in (depth,frame):
        if any(type(v[k]) is not type(owner[k]) or v[k]!=owner[k] for k in ('session_id','clock_basis','clock_epoch')):raise ValueError('DEPTH_OWNER_CLOCK_CHANGED')
    if depth['frame_seq']!=frame['frame_seq'] or depth['source_stamp_s']!=frame['source_stamp_s']:raise ValueError('DEPTH_FRAME_VERSION_CHANGED')
    if type(frame['frame_seq']) is not int or frame['frame_seq']<0 or type(config.get('expected_depth_frame_seq')) is not int or frame['frame_seq']!=config['expected_depth_frame_seq']:
        raise ValueError('EXPECTED_LATEST_DEPTH_VERSION_CHANGED')
    if depth['q_rad']!=frame['q_rad']:raise ValueError('PROJECTED_DEPTH_RAW_STATE_CHANGED')
    if (not 0<=now_source_s-frame['source_stamp_s']<=config['max_depth_age_s'] or
            frame['source_stamp_s']<owner['stop_record']['cancel_terminal_stamp_s']):
        raise ValueError('DEPTH_STALE_OR_PRE_CANCEL')
    association=frame.get('source_association',{})
    expected_association={'CPU_FIXTURE_PREPARATION':'FIXTURE','ARCHIVED_OFFLINE_CALCULATION':'ARCHIVED_SOURCE_TICK_REPLAY','LIVE_INPUT_PREPARATION_ONLY':'ACTUAL_SOURCE_TICK',SAVED_SCOPE:'ACTUAL_SOURCE_TICK'}[scope]
    if association.get('scope')!=expected_association or association.get('same_tick_verified') is not True:
        return dict(status='WAIT_UNASSOCIATED_DEPTH_STATE',missing=['depth_frame.source_association '+expected_association+' proof'],SDK_READY=False,READY=False,apply_allowed=False,execution_allowed=False,hardware_execution_allowed=False)
    from isaac_sim.depth_obstacles.novel_depth.expected_depth import _association_status
    if _association_status(frame)!=expected_association or depth.get('source_association_scope')!=expected_association or depth.get('map_scope')!=m['map_scope']:
        raise ValueError('DEPTH_RENDER_SOURCE_ASSOCIATION_CHANGED')
    if not association['source_refs']:raise ValueError('DEPTH_ASSOCIATION_SOURCE_REFS_REQUIRED')
    for item in association['source_refs']:
        if ref(item['path'])!=item:raise ValueError('DEPTH_ASSOCIATION_SOURCE_CHANGED')
    for k in ('q_rad','grip_rad','attachment_tcp_to_block'):
        if frame[k]!=owner[k] or association[k]!=frame[k]:raise ValueError('DEPTH_RAW_STATE_SOURCE_BINDING_CHANGED:'+k)
    if scope in (SAVED_SCOPE,'LIVE_INPUT_PREPARATION_ONLY'):review_actual_source_tick(frame,owner['state_stamp_s'])
    elif frame['source_stamp_s']!=owner['state_stamp_s']:raise ValueError('DEPTH_OWNER_NOT_SAME_SOURCE_TICK')
    for k in ('T_base_tool','T_tool_camera_optical','T_world_base'):rigid(frame[k])
    for k in ('q_rad','v_rad_s','a_rad_s2'):vector(owner[k],6)
    if scope in (SAVED_SCOPE,'LIVE_INPUT_PREPARATION_ONLY'):
        status,gaps=geometry_wait(refs.get('obstacle_geometry'),refs['depth'],refs['depth_frame'],known['digest'],now_source_s)
        for key in needed:
            if ref(refs[key]['path'])!=refs[key]:raise ValueError('SOURCE_CHANGED_DURING_PREPARATION:'+key)
        return dict(status=status,missing=gaps,source_refs=refs,request_draft=None,
            pending_start_fields=dict(q_rad=deepcopy(owner['q_rad']),grip_rad=owner['grip_rad'],
                attachment_tcp_to_block=deepcopy(owner['attachment_tcp_to_block']),
                raw_observed_v_rad_s=deepcopy(owner['v_rad_s']),raw_or_explicit_derived_a_rad_s2=deepcopy(owner['a_rad_s2']),
                role='OBSERVED_STOP_INPUTS_NOT_COMMAND_PVT_OR_SDK_REQUEST'),
            SDK_READY=False,READY=False,apply_allowed=False,execution_allowed=False,
            hardware_execution_allowed=False,incomplete_world=True,not_a_priority_STOP_prerequisite=True)
    state=sealed(dict(**{k:deepcopy(owner[k]) for k in ('q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block')},
        joint_names=JOINTS,source_stamp_s=owner['state_stamp_s'],clock_basis=owner['clock_basis'],session_id=owner['session_id'],state_sequence=owner['state_sequence'],
        holding_confirmed=True,stopped_verified=True,active_command_count=0,pending_command_count=0,evidence_ref=refs['owner']['path'],
        state_normalization=dict(raw_PVA_unchanged=True,source_owner=refs['owner'])))
    held=next(o for o in base['planning_snapshot']['world_objects'] if o['id']==base['planning_snapshot']['selected_slot_id'])
    scene=dict(world_objects=list(current.values())+[held],T_world_base=m['T_world_base'],
        provenance=dict(scope='GENERIC_KNOWN_MAP_CPU_PROJECTION_NOT_FULL_WORLD',known_map=refs['known_map'],map_digest=known['digest'],unknown_GT_used=False))
    docs=capture_documents(base,state,dict(objects=[]),artifact_created_at=datetime.now(timezone.utc).isoformat(),known_scene=scene)
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    for key,doc in docs.items():write(out/(key+'.json'),doc)
    snapshot=prepare_sim_snapshot(out/'scene.json',out/'state.json')
    motion=json.loads((Path(refs['anchor_request']['path']).parent/'motion.request.json').read_text());result=json.loads((Path(refs['anchor_request']['path']).parent/'motion.result.json').read_text())
    draft=derived_request(base,motion,result,snapshot)
    draft['goal']=deepcopy(base['goal']);draft['expected_precontact']=deepcopy(base['expected_precontact'])
    draft['planning_request_digest']=digest({k:v for k,v in draft.items() if k!='planning_request_digest'})
    draft_path=out/'KNOWN_ONLY.request.DRAFT.yaml';draft_path.write_text(yaml.safe_dump(draft,sort_keys=False))
    status,gaps=geometry_wait(refs.get('obstacle_geometry'),refs['depth'],refs['depth_frame'],known['digest'],now_source_s)
    review=dict(status=status,scope=scope,branch='GENERIC_UNLABELLED_KNOWN_MAP_CPU_ONLY',missing=gaps,source_refs=refs,
        request_draft=ref(draft_path),original_goal=base['goal'],observed_state=state,known_map_digest=known['digest'],depth_frame_seq=frame['frame_seq'],
        initial_engine='MOVEIT_LOCAL_PLANNING_RESULT',SDK_READY=False,READY=False,apply_allowed=False,execution_allowed=False,hardware_execution_allowed=False,
        current_geometry_and_encoded_proof='PENDING',candidate_endpoint_FK='REQUIRED_ON_NEW_ORIGINAL_GOAL_GRIP_MODEL_BEFORE_SDK',
        incomplete_world=True,not_a_priority_STOP_prerequisite=True)
    for key in needed:
        if ref(refs[key]['path'])!=refs[key]:raise ValueError('SOURCE_CHANGED_DURING_PREPARATION:'+key)
    write(out/'result.json',review);return review


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--now-source-s',type=float,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare_moveit_stop_inputs(json.loads(a.config.read_text()),now_source_s=a.now_source_s,output=a.output),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
