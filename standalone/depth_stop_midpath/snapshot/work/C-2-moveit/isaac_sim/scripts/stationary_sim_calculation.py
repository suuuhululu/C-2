"""Archived stationary SIM calculation preparation, never live stop approval.

Raw observed PVT is preserved. Assumed model rest is separate and cannot pass
the live obstacle-hold admission. No SDK, ROS, controller or device calls.
"""
from copy import deepcopy
from pathlib import Path
import ast
import json
import shutil
import numpy as np
from scipy.spatial.transform import Rotation
from bounded_sim_evidence import pinned_json,projection_rays,semantic_scene_binding
from depth_obstacle_envelope import build_envelope,verify_bound
from prepare_cpu_model import file_hash
from prepare_gpu_scene import tcp_fk
from plan_only import digest,prepare_files,checked_pose
from prepare_sim_snapshot import prepare_sim_snapshot
from sim_utils import rigid,matrix_pose


def ref(path):return dict(path=str(Path(path).resolve()),sha256=file_hash(Path(path)))
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def rest_observation(proof_ref,criteria_ref,frame_ref):
    proof,criteria,frame=map(pinned_json,(proof_ref,criteria_ref,frame_ref))
    rows=proof['samples'];t=np.array([r['stamp_s'] for r in rows]);q,v,a=[np.array([r[k] for r in rows],float) for k in ('q_rad','v_rad_s','a_rad_s2')]
    if (frame['source_kind']!='SIM_DEPTH' or frame['clock_basis']!=proof['clock_basis'] or frame['session_id']!=proof['session_id'] or
            frame['source_stamp_s']!=t[-1] or frame['q_rad']!=rows[-1]['q_rad'] or
            len(rows)<4 or np.any(np.diff(t)<=0) or not np.isfinite([q,v,a]).all() or q.shape!=(len(t),6)):
        raise ValueError('ACTUAL_STAMPED_REST_OBSERVATION_REQUIRED')
    if (criteria['scope']!='PREDECLARED_EXISTING_SIM_REST_LIMITS_NO_THRESHOLD_RELAXATION' or
            criteria['max_velocity_rad_s']>.02 or criteria['max_acceleration_rad_s2']>.7 or criteria['minimum_recorded_duration_s']<.5 or
            proof['active_command_count']!=0 or proof['pending_command_count']!=0):raise ValueError('RECORDED_SIM_CRITERIA_AND_COUNTS_REQUIRED')
    difference=np.diff(q,axis=0)/np.diff(t)[:,None]
    integral=np.sum((v[:-1]+v[1:])/2*np.diff(t)[:,None],axis=0)
    passed=(t[-1]-t[0]>=criteria['minimum_recorded_duration_s'] and
            float(abs(v).max())<=criteria['max_velocity_rad_s'] and float(abs(a).max())<=criteria['max_acceleration_rad_s2'])
    return dict(schema_version='stationary-sim-observation-review/0.1',status='RECORDED_SIM_CRITERIA_PASSED' if passed else 'HOLD_RECORDED_SIM_CRITERIA',
        proof=proof_ref,criteria=criteria_ref,frame=frame_ref,duration_s=float(t[-1]-t[0]),
        max_native_v_rad_s=float(abs(v).max()),max_native_a_rad_s2=float(abs(a).max()),max_position_difference_v_rad_s=float(abs(difference).max()),
        observed_delta_q_rad=(q[-1]-q[0]).tolist(),integrated_native_v_rad=integral.tolist(),
        native_integral_minus_delta_q_rad=(integral-(q[-1]-q[0])).tolist(),
        readout_uncertainty=proof['observation'],raw_final_qva={k:rows[-1][k] for k in ('q_rad','v_rad_s','a_rad_s2')},
        stop_reason=proof['stop_reason'],strict_consumer_1e_6_passed=bool(max(abs(v).max(),abs(a).max())<=1e-6),
        SDK_observation_1e_6_requirement_documented=False,zero_model_derivatives_are_observed=False,
        controller_reference_same_clock='NOT_RECORDED_IN_THIS_PROOF',native_resume_allowed=False,execution_allowed=False)


def static_initial_model(frame_ref,pose_ref):
    frame,pose=map(pinned_json,(frame_ref,pose_ref))
    if (frame['source_kind']!='SIM_DEPTH' or pose['time_sync_scope']!='STATIONARY_POST_RENDER_BRACKET_NOT_DYNAMIC_SOURCE_STAMP' or
            frame['source_stamp_s']!=pose['stamp_s'] or frame['clock_basis']!=pose['clock_basis'] or
            pose['before_stamp_s']!=pose['stamp_s'] or pose['after_stamp_s']!=pose['stamp_s'] or
            pose['before_q_rad']!=pose['q_rad'] or pose['after_q_rad']!=pose['q_rad'] or frame['q_rad']!=pose['q_rad']):
        raise ValueError('FROZEN_ARCHIVED_SIM_MODEL_ONLY')
    return dict(scope='ASSUMED_STATIC_ARCHIVED_SIM_POSITION_MODEL_NOT_OBSERVED_REST',q_rad=frame['q_rad'],
        model_v_rad_s=[0.]*6,model_a_rad_s2=[0.]*6,frame=frame_ref,pose=pose_ref,
        raw_state_overwritten=False,observation_uncertainty_is_physical_bound=False,native_resume_allowed=False,execution_allowed=False)


def serialize_static_depth(raw,model,context,output,trial):
    raw,output=Path(raw),Path(output)
    if output.exists():raise ValueError('NEVER_OVERWRITE_STATIC_DEPTH_EVIDENCE')
    if (trial['scope']!='DECLARED_STATIC_ARCHIVED_SIM_TRIAL_NOT_LIVE' or trial['max_speed_m_s']!=0 or
            not np.isfinite(trial['extra_renderer_error_m']) or trial['extra_renderer_error_m']<0 or
            not np.isfinite(trial['source_validity_s']) or trial['source_validity_s']<=0):raise ValueError('EXPLICIT_STATIC_SIM_ASSUMPTIONS_REQUIRED')
    frame=json.loads((raw/'frame.json').read_text());pose=json.loads((raw/'pose.json').read_text());audit=json.loads((raw/'mask_audit.json').read_text())
    # Require the producer's terminal capture result and completed model binding.
    terminal=json.loads((raw/'status.json').read_text());binding=json.loads((raw/'inventory_binding_result.json').read_text())
    if terminal['capture_success'] is not True or binding['status']!='ORIGINAL_MODEL_AND_NATIVE_HELD_PIECES_VERIFIED':raise ValueError('COMPLETED_NATIVE_CAPTURE_BINDING_REQUIRED')
    if frame['source_kind']!='SIM_DEPTH' or frame['depth_unit']!='METER':raise ValueError('NOMINAL_SIM_METER_DEPTH_REQUIRED')
    tree=ast.parse((raw/'capture_source.py').read_text())
    sizes=[ast.literal_eval(n.args[0]) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and
        n.func.attr=='CreateSizeAttr' and isinstance(n.func.value,ast.Name) and n.func.value.id=='cube']
    if len(sizes)!=1 or not isinstance(sizes[0],(int,float)) or sizes[0]<=0:raise ValueError('PINNED_CONTROLLED_CUBE_SIZE_DECLARATION_REQUIRED')
    peak=semantic_scene_binding(audit,dict(semantic_ids=raw/'semantic_ids.npy',capture_source=raw/'capture_source.py'),frame,model,context)
    tcp=tcp_fk(model,frame['q_rad'],pose['grip_rad']);actual=rigid(frame['T_base_tool'])
    peak=np.maximum(peak,[np.linalg.norm(tcp[:3,3]-actual[:3,3]),Rotation.from_matrix(tcp[:3,:3].T@actual[:3,:3]).magnitude()])
    output.mkdir(parents=True)
    names=['frame.json','pose.json','depth.npy','semantic_ids.npy','semantic_info.json','self_mask.npy','held_mask.npy',
           'obstacle_mask.npy','mask_audit.json','limits.json','candidates.json','capture_source.py','capture_profile.json','camera_params.json']
    sources={n:ref(raw/n) for n in names}
    for n in names:shutil.copyfile(raw/n,output/n)
    intr=frame['intrinsics'];W,H=intr['width'],intr['height'];uv=np.array([[0,0],[W-1,0],[0,H-1],[W-1,H-1],[intr['cx'],intr['cy']]],float)
    # Keep the consumer's integer-pixel deprojection unchanged. Budget the
    # producer's actual half-pixel renderer convention, not only matrix rounding.
    convention=Path(__file__).resolve().parents[1]/'depth_obstacles/complete_sensor_bundle.py'
    capture=convention.read_text().replace(' ','')
    if 'uv[:,0]+.5' not in capture or 'uv[:,1]+.5' not in capture:
        raise ValueError('PINNED_RENDERER_HALF_PIXEL_CONVENTION_REQUIRED')
    shutil.copyfile(convention,output/'pixel_convention_source.py')
    params=json.loads((output/'camera_params.json').read_text());directions=projection_rays(params,uv+.5)
    residual=float(np.linalg.norm(directions[:,:2]-(uv-[intr['cx'],intr['cy']])/[intr['fx'],intr['fy']],axis=1).max())+64*np.finfo(float).eps
    depth=np.load(output/'depth.npy',allow_pickle=False);mask=np.load(output/'obstacle_mask.npy',allow_pickle=False)
    if depth.dtype!=np.float32:raise ValueError('ORIGINAL_FLOAT32_DEPTH_REPRESENTATION_REQUIRED')
    z=depth[mask];v,u=np.nonzero(mask)
    if not np.isfinite(z).all() or not len(z):raise ValueError('FINITE_OBSERVED_CUBE_DEPTH_REQUIRED')
    ray_norm=np.sqrt(1+((u-intr['cx'])/intr['fx'])**2+((v-intr['cy'])/intr['fy'])**2)
    z_quant=float((np.spacing(z.astype(np.float32))/2*ray_norm).max())
    ray_error=float((z*ray_norm).max())*residual
    point_error=z_quant+ray_error+trial['extra_renderer_error_m']+64*np.finfo(float).eps
    reserve=8*float(np.finfo(np.float32).eps)
    profile=json.loads((output/'capture_profile.json').read_text())
    published=next((path,sha) for path,sha in profile['source_evidence'].items() if path.endswith('live_capture.json'))
    calibration=dict(profile=ref(output/'capture_profile.json'),published_messages=dict(path=str(Path(trial['source_root'])/published[0]),sha256=published[1]),
        source_root=trial['source_root'],model_urdf_sha256=file_hash(Path(model['bundle_path'])/'robot.urdf'),capture_source_sha256=file_hash(output/'capture_source.py'),
        ray_validation=dict(scope='SIM_RENDERER_PIXEL_RAY_VALIDATION',method='INVERT_PINNED_RTX_PROJECTION_NOT_DEPTH_OR_HAND_EYE_PROBE',
            profile_sha256=file_hash(output/'capture_profile.json'),capture_source_sha256=file_hash(output/'capture_source.py'),projection_ref=ref(output/'camera_params.json'),
            pixel_uv=uv.tolist(),renderer_pixel_offset_uv=[.5,.5],consumer_pixel_offset_uv=[0.,0.],
            pixel_convention_source=ref(output/'pixel_convention_source.py'),
            renderer_optical_directions=directions.tolist(),max_normalized_ray_error=residual))
    save(output/'calibration.json',calibration)
    basis=dict(scope='DECLARED_SINGLE_SIM_OBJECT_AND_ERROR_MODEL',source_kind='SIM_DEPTH',size_upper_m=[float(sizes[0])]*3,
        point_error_m=point_error,pose_translation_error_m=float(peak[0]+reserve),pose_rotation_error_rad=float(peak[1]+reserve),
        max_speed_m_s=0.,max_sensor_to_use_delay_s=trial['source_validity_s'],usage_scope='ARCHIVED_STATIC_SIM_CALCULATION_ONLY',
        trial_assumptions=trial,raw_sources=sources,producer_terminal=ref(raw/'status.json'),producer_binding=ref(raw/'inventory_binding_result.json'),
        budget=dict(float32_depth_quantization_point_m=z_quant,projection_ray_difference_unitless=residual,
            projection_point_error_m=ray_error,max_observed_depth_z_m=float(z.max()),
            pixel_convention_scope='HALF_PIXEL_RENDERER_VS_INTEGER_CONSUMER_COVERED_BY_RANGE_TIMES_RAY_ERROR',
            extra_renderer_error_m=trial['extra_renderer_error_m'],extra_renderer_error_scope='DECLARED_SIM_TRIAL_ASSUMPTION_NOT_MEASURED_BOUND',
            measured_same_frame_pose_error_m_rad=peak.tolist(),pose_representation_reserve=reserve,
            motion_scope='CONTROLLED_STATIC_CUBE_IN_FROZEN_ARCHIVE_NOT_MOVING_OBSTACLE',wall_sensor_to_apply_measured=False))
    save(output/'basis.json',basis)
    prior={k:basis[k] for k in ('size_upper_m','point_error_m','pose_translation_error_m','pose_rotation_error_rad','max_speed_m_s','max_sensor_to_use_delay_s')}
    prior.update(scope='DECLARED_SIM_SINGLE_OBJECT_BOUNDS_NOT_REAL',usage_scope=basis['usage_scope'],basis_ref='PINNED_NATIVE_STATIC_CUBE_AND_RTX_NUMERIC_MODEL_WITH_DECLARED_RESIDUAL',
        basis_evidence=ref(output/'basis.json'),obstacle_id='Dynamic_archived_controlled_cube',min_visible_pixels=3,min_pixel_span=2)
    save(output/'prior.json',prior)
    complete=dict(status='COMPLETE',scope='CPU_FROZEN_NORMALIZATION_NOT_LIVE_PLANNING_APPROVAL',source_kind='SIM_DEPTH',
        session_id=frame['session_id'],capture_source_sha256=file_hash(output/'capture_source.py'),frames=[dict(frame_seq=frame['frame_seq'],frame_sha256=file_hash(output/'frame.json'))],raw_sources=sources)
    save(output/'capture_complete.json',complete)
    keys=['frame','pose','depth','semantic_ids','semantic_info','self_mask','held_mask','obstacle_mask','mask_audit','limits','candidates','capture_source','calibration']
    manifest=dict(schema='single-object-depth-evidence/0.1',source_kind='SIM_DEPTH',annotator='distance_to_image_plane',
        calibration_scope=frame['calibration_scope'],mask_evidence_kind='SEMANTIC_FULL_SCENE_BINDING',completion=ref(output/'capture_complete.json'),
        files={k:dict(path=k+('.npy' if k in ('depth','semantic_ids','self_mask','held_mask','obstacle_mask') else '.py' if k=='capture_source' else '.json'),sha256='') for k in keys})
    for value in manifest['files'].values():value['sha256']=file_hash(output/value['path'])
    save(output/'manifest.json',manifest)
    spec=dict(folder=str(output.resolve()),manifest_sha256=file_hash(output/'manifest.json'),capture_source_kind='SIM_DEPTH',
        capture_source_sha256=file_hash(output/'capture_source.py'),prior_sha256=file_hash(output/'prior.json'),
        source_frames={k:frame[k] for k in ('base_frame_id','tool_frame_id','optical_frame_id')})
    save(output/'evidence_spec.json',spec)
    bound=build_envelope(spec,output/'prior.json',model,context,now_s=frame['source_stamp_s'])
    save(output/'bound.json',bound)
    if any(file_hash(Path(value['path']))!=value['sha256'] for value in sources.values()):raise ValueError('RAW_CAPTURE_CHANGED_DURING_NORMALIZATION')
    return bound


def prepare_static_candidate(anchor_path,bound,output):
    from prepare_cumotion_model import verify_request
    from dynamic_cumotion_inputs import held_mask_context
    base=verify_request(Path(anchor_path),allow_geometry_cpu=True)
    verify_bound(bound,base['model_bundle'],now_s=bound['source_stamp_s'])
    state_path=Path(base['simulation_provenance']['files']['state']['path']);state=json.loads(state_path.read_text())
    snapshot=state['observation_evidence']['snapshot_binding']['snapshot']
    if (bound['assumptions']['usage_scope']!='ARCHIVED_STATIC_SIM_CALCULATION_ONLY' or bound['source_session_id']!=snapshot['session_id'] or
            bound['source_stamp_s']!=snapshot['stamp_s'] or bound['geometry_context']!=held_mask_context(base,state)):
        raise ValueError('STATIC_CALCULATION_SNAPSHOT_MISMATCH')
    scene=json.loads(Path(base['simulation_provenance']['files']['scene']['path']).read_text());scene=deepcopy(scene);state=deepcopy(state)
    if Path(output).exists():raise ValueError('NEVER_OVERWRITE_STATIC_CANDIDATE')
    output=Path(output);output.mkdir(parents=True)
    for doc in (scene,state):doc['capture_id']='static-depth-calculation:'+bound['digest']
    obstacle=deepcopy(bound['geometry']);world_base=rigid(scene['frame_alignment']['T_world_base'])
    obstacle['world_pose']=matrix_pose(world_base@checked_pose(obstacle['pose']));obstacle['world_pose']['frame_id']='world';scene['world_objects'].append(obstacle)
    model=static_initial_model(ref(Path(bound['evidence_spec']['folder'])/'frame.json'),ref(Path(bound['evidence_spec']['folder'])/'pose.json'))
    state['optimizer_initial_model']=model
    save(output/'scene.json',scene);save(output/'state.json',state);save(output/'bound.json',bound)
    motion=json.loads((Path(anchor_path).parent/'motion.request.json').read_text())
    request=prepare_files(output/'common_A',motion,prepare_sim_snapshot(output/'scene.json',output/'state.json'),base['model_bundle']['bundle_path'])
    path=output/'common_A/TRANSPORT.request.yaml';verify_request(path,allow_geometry_cpu=True)
    envelope=dict(schema_version='static-sim-calculation-preparation/0.1',status='CPU_STATIC_MODEL_PREPARED_NATIVE_RESUME_BLOCKED',
        calculation_scope='ARCHIVED_STATIC_SIM_CALCULATION_ONLY',anchor_request=ref(anchor_path),
        numeric_replay_numpy_version=np.__version__,
        request=ref(path),bound=ref(output/'bound.json'),solver_initial_model=model,raw_state_preserved=True,
        source_clock_replay_at_s=bound['source_stamp_s'],valid_until_s=bound['valid_until_s'],current_revision=request['current_revision'],
        planning_request_digest=request['planning_request_digest'],control_mode_preserved='GOAL_COMPLETE_NOT_OBSTACLE_HOLD',
        dynamic_obstacle_handoff_ready=False,SDK_FCL_result_generated=False,execution_allowed=False,hardware_execution_allowed=False)
    save(output/'static_calculation.envelope.json',envelope)
    save(path.parent/'static_calculation.admission.json',dict(scope='ARCHIVED_STATIC_SIM_CALCULATION_ONLY',
        envelope=ref(output/'static_calculation.envelope.json')))
    verify_request(path)
    return envelope


def verify_static_request(path,request):
    """Replay archived data and exactly the two allowed source transformations.

    This is a mathematical q-only calculation contract, not a stopped-state
    measurement or obstacle-response/live admission. No fixture bypass.
    """
    side=pinned_json(ref(path.parent/'static_calculation.admission.json'))
    env=pinned_json(side['envelope'])
    if env.get('numeric_replay_numpy_version',np.__version__)!=np.__version__:
        raise ValueError('STATIC_CALCULATION_NUMERIC_RUNTIME_MISMATCH_REGENERATE_FROM_RAW')
    if (side['scope']!='ARCHIVED_STATIC_SIM_CALCULATION_ONLY' or env['calculation_scope']!=side['scope'] or
            env['request']!=ref(path) or env['status']!='CPU_STATIC_MODEL_PREPARED_NATIVE_RESUME_BLOCKED' or
            any(env[k] is not False for k in ('dynamic_obstacle_handoff_ready','SDK_FCL_result_generated','execution_allowed','hardware_execution_allowed')) or
            env['raw_state_preserved'] is not True or env['control_mode_preserved']!='GOAL_COMPLETE_NOT_OBSTACLE_HOLD' or
            (path.parent/'dynamic_input.envelope.json').exists() or (path.parent/'bounded_sim_admission.json').exists()):
        raise ValueError('ARCHIVED_STATIC_CALCULATION_ONLY_NO_LIVE_ADMISSION')
    from prepare_cumotion_model import verify_request
    from dynamic_cumotion_inputs import held_mask_context
    anchor=Path(env['anchor_request']['path'])
    if file_hash(anchor)!=env['anchor_request']['sha256'] or (anchor.parent/'static_calculation.admission.json').exists():
        raise ValueError('STATIC_ANCHOR_CHANGED_OR_RECURSIVE')
    base=verify_request(anchor,allow_geometry_cpu=True)
    bound=pinned_json(env['bound']);verify_bound(bound,base['model_bundle'],now_s=env['source_clock_replay_at_s'])
    basis=pinned_json(bound['assumptions']['basis_evidence'])
    trial=basis['trial_assumptions']
    if (bound['assumptions']['usage_scope']!=side['scope'] or basis['usage_scope']!=side['scope'] or
            trial['scope']!='DECLARED_STATIC_ARCHIVED_SIM_TRIAL_NOT_LIVE' or trial['max_speed_m_s']!=0 or
            bound['assumptions']['max_speed_m_s']!=0 or env['valid_until_s']!=bound['valid_until_s']):
        raise ValueError('EXPLICIT_STATIC_PRIOR_REQUIRED')
    for name,source in basis['raw_sources'].items():
        if file_hash(Path(source['path']))!=source['sha256'] or file_hash(Path(bound['evidence_spec']['folder'])/name)!=source['sha256']:
            raise ValueError('RAW_STATIC_CAPTURE_CHANGED')
    if (pinned_json(basis['producer_terminal'])['capture_success'] is not True or
            pinned_json(basis['producer_binding'])['status']!='ORIGINAL_MODEL_AND_NATIVE_HELD_PIECES_VERIFIED'):
        raise ValueError('COMPLETED_NATIVE_CAPTURE_BINDING_REQUIRED')
    raw={k:pinned_json(base['simulation_provenance']['files'][k]) for k in ('state','scene')}
    folder=Path(bound['evidence_spec']['folder'])
    if any(env['solver_initial_model'][k]!=ref(folder/(k+'.json')) for k in ('frame','pose')):
        raise ValueError('STATIC_INITIAL_MODEL_MUST_USE_BOUND_SOURCE')
    frame=pinned_json(env['solver_initial_model']['frame'])
    snapshot=raw['state']['observation_evidence']['snapshot_binding']['snapshot']
    if (bound['source_session_id']!=snapshot['session_id'] or bound['source_stamp_s']!=snapshot['stamp_s'] or
            bound['geometry_context']!=held_mask_context(base,raw['state']) or frame['source_stamp_s']!=snapshot['stamp_s'] or
            frame['session_id']!=snapshot['session_id'] or base['model_bundle']!=request['model_bundle']):
        raise ValueError('STATIC_CALCULATION_SNAPSHOT_MISMATCH')
    initial=static_initial_model(env['solver_initial_model']['frame'],env['solver_initial_model']['pose'])
    if initial!=env['solver_initial_model'] or initial['q_rad']!=raw['state']['q_rad']:
        raise ValueError('STATIC_INITIAL_MODEL_CHANGED')
    for doc in raw.values():doc['capture_id']='static-depth-calculation:'+bound['digest']
    raw['state']['optimizer_initial_model']=initial
    obstacle=deepcopy(bound['geometry'])
    obstacle['world_pose']=matrix_pose(rigid(raw['scene']['frame_alignment']['T_world_base'])@checked_pose(obstacle['pose']))
    obstacle['world_pose']['frame_id']='world';raw['scene']['world_objects'].append(obstacle)
    if any(pinned_json(request['simulation_provenance']['files'][k])!=raw[k] for k in raw):
        raise ValueError('STATIC_SOURCE_TRANSFORMATION_CHANGED')
    if (json.loads((anchor.parent/'motion.request.json').read_text())!=json.loads((path.parent/'motion.request.json').read_text()) or
            env['current_revision']!=request['current_revision'] or env['planning_request_digest']!=request['planning_request_digest']):
        raise ValueError('STATIC_GOAL_OR_COMMON_A_CONTEXT_CHANGED')
    return dict(scope=side['scope'],admission=ref(path.parent/'static_calculation.admission.json'),envelope=side['envelope'],
        bound=env['bound'],source_session_id=bound['source_session_id'],source_stamp_s=bound['source_stamp_s'],
        initial_model=initial,dynamic_input_ready=False,native_execution_allowed=False,hardware_execution_allowed=False)
