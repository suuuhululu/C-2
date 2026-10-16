"""Explicit common-A cuMotion calculation and original-model FCL validation.

Writes calculation evidence only. No OMPL fallback, readiness, D dispatch,
ROS action client or robot execution. Uses an explicitly pinned file checker.
"""
import argparse
import ctypes
import json
from copy import deepcopy
from pathlib import Path
import sys
import shutil
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from benchmark_cumotion import fcl_run, save
from cumotion_timing import (ENGINE, TIMING_ENGINE, retime_sdk_position_path,
                             export_spline_points, final_quintic_jerk)
from plan_only import BINDING, JOINTS, checked_pose, prepare_d_candidate, validate_trajectory, digest
from prepare_cpu_model import file_hash
from prepare_cumotion_model import load_model_yaml, read_cumotion_model, verify_request, make_world, urdf_transforms, TCP
from cumotion_geometry import object_boxes


def solver_fingerprint(request,model):
    """q/goal/dynamic poses are inputs; fixed geometry changes need explicit restart."""
    xrdf=load_model_yaml((model/'robot.xrdf').read_text())
    for name in JOINTS:xrdf['default_joint_positions'].pop(name,None)
    state=request['planning_snapshot']
    from held_geometry_inputs import nominal_definition
    held=next(o for o in state['world_objects'] if o['id']==state['selected_slot_id'])
    fixed=[o for o in state['world_objects'] if o['id']!=state['selected_slot_id'] and not o['id'].startswith('Dynamic_')]
    return digest(dict(model=request['model_bundle'],urdf_sha256=file_hash(model/'robot.urdf'),xrdf=xrdf,
        grip=state['grip_rad'],attachment=request['attachment'],held=nominal_definition(held,request['model_bundle']),
        selected_slot_id=state['selected_slot_id'],static_world=sorted(fixed,key=lambda o:o['id'])))


def update_solver_world(session,request,model):
    """Only the single SDK worker mutates this view, between synchronous solves."""
    if solver_fingerprint(request,model)!=session['fingerprint']:
        raise ValueError('WARM_SOLVER_FIXED_GEOMETRY_CHANGED_EXPLICIT_RESTART_REQUIRED')
    sdk=session['sdk'];world=session['world'];old=session['dynamic'];fresh={};mapping=[]
    for obj in request['planning_snapshot']['world_objects']:
        if not obj['id'].startswith('Dynamic_'):continue
        pieces=object_boxes(obj,checked_pose(obj['pose']),0)
        for i,(size,pose) in enumerate(pieces):
            key=(obj['id'],i);shape=np.asarray(size).tolist()
            if key in old and old[key]['size_m']==shape:
                handle=old[key]['handle'];world.set_pose(handle,sdk.Pose3(pose))
            else:
                if key in old:world.remove_obstacle(old[key]['handle'])
                obstacle=sdk.create_obstacle(sdk.Obstacle.Type.CUBOID)
                obstacle.set_attribute(sdk.Obstacle.Attribute.SIDE_LENGTHS,size)
                handle=world.add_obstacle(obstacle,sdk.Pose3(pose))
            fresh[key]=dict(handle=handle,size_m=shape)
        mapping.append(dict(id=obj['id'],role=obj['role'],primitive_count=len(pieces),padding_m=0))
    for key in old.keys()-fresh.keys():world.remove_obstacle(old[key]['handle'])
    session['dynamic']=fresh
    session['view'].update()
    return session['static_mapping']+mapping


def selected_optimizer_parameters(parameter_ref=None):
    """Explicit task-space experiment only; default zero remains unchanged."""
    parameters={'trajopt/num_geometric_planning_attempts':0,'ik/max_reattempts':0}
    if parameter_ref is not None:
        from bounded_sim_evidence import pinned_json
        selection=pinned_json(parameter_ref)
        expected=dict(schema='cumotion-explicit-taskspace-parameters/0.1',SDK_version='1.1.0',
            optimizer_parameters={**parameters,'trajopt/num_geometric_planning_attempts':1},
            plan_method='plan_to_task_space_target',max_api_plan_calls=1,
            geometric_semantics='SDK_INTERNAL_FALLBACK_AFTER_STANDARD_TRAJECTORY_OPTIMIZATION_FAILURE',
            external_fallback_allowed=False,external_retry_allowed=False,
            target_constraints=dict(translation_terminal_m=.0008,orientation_terminal_rad=.005,path_axis_rad=.15))
        if any(selection.get(k)!=v for k,v in expected.items()):
            raise ValueError('EXPLICIT_TASKSPACE_PARAMETER_SCOPE_CHANGED')
        if any(type(v) is not int for v in selection['optimizer_parameters'].values()):
            raise ValueError('INTEGER_OPTIMIZER_PARAMETERS_REQUIRED')
        sources=selection['source_files']
        if set(sources)!=set(('calculate_cumotion.py','online_cumotion_worker.py','request_cumotion_admission.py')):
            raise ValueError('OPTIMIZER_PARAMETER_SOURCE_SET_CHANGED')
        for name,item in sources.items():
            if Path(item['path']).resolve()!=Path(__file__).resolve().parent/name or file_hash(Path(item['path']))!=item['sha256']:
                raise ValueError('OPTIMIZER_PARAMETER_SOURCE_CHANGED:'+name)
        for item in selection['official_evidence'].values():
            if file_hash(Path(item['path']))!=item['sha256']:raise ValueError('OPTIMIZER_PARAMETER_OFFICIAL_EVIDENCE_CHANGED')
        parameters=deepcopy(selection['optimizer_parameters'])
    return parameters


def configure_optimizer(config,parameter_ref=None):
    parameters=selected_optimizer_parameters(parameter_ref);accepted={}
    for name,value in parameters.items():
        accepted[name]=bool(config.set_param(name,value))
        if not accepted[name]:raise ValueError('EXPLICIT_OPTIMIZER_PARAMETER_REJECTED:'+name)
    return parameters,accepted


def start_solver(request,model,manifest,solver_parameters=None):
    """Explicit GPU start only. Importing this module never imports the SDK."""
    selected_optimizer_parameters(solver_parameters)
    import cumotion
    if (cumotion.__version__!='1.1.0' or not Path(cumotion.__file__).resolve().is_relative_to(Path(sys.prefix))):
        raise ValueError('ISOLATED_STABLE_CUMOTION_1_1_0_REQUIRED')
    geometry_inspection=None
    if manifest.get('geometry_repreparation'):
        from prepare_cumotion_model import inspect_model
        geometry_inspection=inspect_model(model,request,cumotion)
        if (not geometry_inspection['geometric_start_valid'] or
                geometry_inspection['gpu_self_collision_sphere_count']>1024):
            raise ValueError('REPREPARED_GEOMETRY_NEW_MODEL_REJECTED')
    robot=cumotion.load_robot_from_file(model/'robot.xrdf',model/'robot.urdf')
    fixed=deepcopy(request)
    fixed['planning_snapshot']['world_objects']=[o for o in request['planning_snapshot']['world_objects'] if not o['id'].startswith('Dynamic_')]
    world,mapping=make_world(fixed,cumotion);view=world.add_world_view()
    session=dict(sdk=cumotion,robot=robot,world=world,view=view,static_mapping=mapping,dynamic={},
        inspector=cumotion.create_robot_world_inspector(robot,view),
        fingerprint=solver_fingerprint(request,model),uses=0,jerk_limits=manifest['jerk_limits'],
        geometry_repreparation_inspection=geometry_inspection)
    update_solver_world(session,request,model)
    xrdf=load_model_yaml((model/'robot.xrdf').read_text())
    if ([robot.cspace_coord_name(i) for i in range(robot.num_cspace_coords())]!=JOINTS or
            session['inspector'].num_world_collision_spheres()!=sum(map(len,xrdf['geometry']['full_geometry']['spheres'].values()))):
        raise ValueError('WARM_SOLVER_JOINT_ORDER_OR_SPHERES_CHANGED')
    config=cumotion.create_default_trajectory_optimizer_config(robot,TCP,view)
    session['explicit_optimizer_parameters'],session['optimizer_parameter_acceptance']=configure_optimizer(config,solver_parameters)
    session['solver_parameters']=solver_parameters
    session['solver_session_fingerprint']=digest(dict(geometry=session['fingerprint'],solver_parameters=solver_parameters,
        optimizer_parameters=session['explicit_optimizer_parameters']))
    session['optimizer']=cumotion.create_trajectory_optimizer(config)
    return session


def bind_identical_geometry(model, old_request_path, fresh_request_path, output):
    """New A motion IDs require new binding, even with identical saved geometry.

    Explicitly copy into a new folder only when the sole A result change is
    its generated motion_plan_id. This never adopts a changed world/goal/grip.
    """
    old, manifest = read_cumotion_model(model, old_request_path)
    fresh = verify_request(fresh_request_path)
    omitted = {'motion_result_digest', 'planning_request_digest'}
    if {k:v for k,v in old.items() if k not in omitted}!={k:v for k,v in fresh.items() if k not in omitted}:
        raise ValueError('MODEL_REBINDING_REQUIRES_IDENTICAL_GEOMETRY_AND_CONTEXT')
    results = [json.loads((p.parent/'motion.result.json').read_text()) for p in
               (old_request_path, fresh_request_path)]
    for result in results:
        result['motion_proposal'].pop('motion_plan_id')
    if results[0]!=results[1]:
        raise ValueError('MODEL_REBINDING_REQUIRES_IDENTICAL_A_MOTION')
    output.mkdir(parents=True, exist_ok=False)
    for name in ('robot.urdf','robot.xrdf','model_checks.json'):
        shutil.copy2(model/name, output/name)
    manifest = deepcopy(manifest)
    manifest.update(source_request=str(fresh_request_path), source_request_sha256=file_hash(fresh_request_path),
        binding={k:fresh[k] for k in BINDING}, same_geometry_rebinding=dict(
            original_model=str(model), original_request=str(old_request_path),
            original_manifest_sha256=file_hash(model/'CUMOTION_MODEL_MANIFEST.json'),
            only_A_generated_motion_plan_id_changed=True, geometry_changed=False))
    save(output/'CUMOTION_MODEL_MANIFEST.json', manifest)
    read_cumotion_model(output, fresh_request_path)
    return output


def loaded_timing_limits(robot,manifest,timing_profile):
    """SDK getters return loaded model limits, not measured-state tolerances."""
    profile={'nominal':(.35,.7,5.),'servo-margin':(.3,.5,3.),'servo-soft':(.3,.5,1.)}[timing_profile]
    kinematics=robot.kinematics()
    loaded={name:[getattr(kinematics,'cspace_coord_'+name+'_limit')(i) for i in range(6)]
            for name in ('velocity','acceleration','jerk')}
    if not np.isfinite(list(loaded.values())).all() or np.any(np.asarray(list(loaded.values()))<=0):
        raise ValueError('INVALID_LOADED_SDK_MODEL_TIMING_LIMITS')
    return dict(velocity_limit=min(profile[0],min(loaded['velocity'])),
        acceleration_limit=min(profile[1],min(loaded['acceleration'])),
        jerk_limits=np.minimum(np.minimum(manifest['jerk_limits'],loaded['jerk']),profile[2]).tolist(),
        loaded_model_limits=loaded,selected_project_profile=dict(name=timing_profile,velocity=profile[0],acceleration=profile[1],jerk=profile[2]),
        loaded_source_category='SDK_SOLVER_PARAMETER',profile_source_category='PROJECT_TEST_PARAMETER',
        reference='cumotion.Kinematics.cspace_coord_{velocity,acceleration,jerk}_limit from loaded URDF/XRDF',
        runtime_version='standalone cuMotion 1.1.0',sdk_official_observation_value=None)


def recorded_sdk_plan(optimizer,q,target,cuda,success_status,diagnostics,*,path=None,context_check=None):
    """Persist SDK status and synchronized call time before any later rejection.

    1.1.0 Results exposes status/target_index/trajectory only. Failed trajectory
    validity and failed target_index validity are unspecified; neither is read.
    """
    sequence=0
    def store():
        nonlocal sequence
        if path is not None:
            sequence+=1
            save(path.with_name(f'{path.stem}.{sequence:02d}.{diagnostics["phase"]}{path.suffix}'),diagnostics)
    diagnostics.update(phase='BEFORE_CURRENT_REVIEW',plan_invoked=False,solve_wall_s=None)
    store();begin=None
    try:
        if context_check:context_check('SDK_PLAN_START')
        diagnostics.update(phase='PLAN_IN_PROGRESS',plan_invoked=True);store()
        begin=time.perf_counter()
        result=optimizer.plan_to_task_space_target(q,target)
        if cuda.cuCtxSynchronize()!=0:raise RuntimeError('CUDA_SYNCHRONIZATION_FAILED')
        diagnostics['solve_wall_s']=time.perf_counter()-begin
        status=result.status();success=status==success_status
        diagnostics.update(phase='SDK_RETURNED',SDK_status=dict(text=str(status),name=status.name,value=int(status.value)),
            SDK_success=success,target_index=None,target_index_scope='NOT_READ_ON_FAILURE_VALIDITY_UNSPECIFIED',
            unavailable_public_1_1_0_Results_fields=['cost','feasibility','failed_constraint','iteration_count','IK_subresult'],
            trajectory_read_by_diagnostic=False)
        if success:
            try:diagnostics.update(target_index=int(result.target_index()),target_index_scope='SUCCESS_ONLY')
            except Exception as error:
                diagnostics.update(target_index_scope='SUCCESS_GETTER_FAILED_NOT_PLAN_FAILURE',target_index_diagnostic_error=str(error))
        store()
        if context_check:context_check('SDK_PLAN_FINISHED')
        if not success:raise ValueError('CUMOTION_PLAN_FAILED:'+str(status))
        diagnostics['phase']='SDK_SUCCESS_CURRENT_REVIEW_PASSED';store()
        return result,diagnostics['solve_wall_s']
    except Exception as error:
        diagnostics.update(phase='REJECTED',exception=dict(type=type(error).__name__,reason=str(error)))
        if begin is not None:diagnostics['attempt_until_exception_wall_s']=time.perf_counter()-begin
        store()
        raise
    finally:
        if path is not None:save(path,diagnostics)


def solve(request, model, manifest, timing_profile='nominal',solver_session=None,context_check=None,diagnostics_path=None,selected_job=None):
    if timing_profile not in ('nominal','servo-margin','servo-soft'):
        raise ValueError('Unknown explicit timing profile')
    prepared_begin=time.perf_counter()
    from bounded_sim_evidence import pinned_json
    parameter_ref=pinned_json(selected_job).get('solver_parameters') if selected_job is not None else None
    parameters=selected_optimizer_parameters(parameter_ref)
    session=solver_session if solver_session is not None else start_solver(request,model,manifest,solver_parameters=parameter_ref)
    if (session.get('solver_parameters')!=parameter_ref or session.get('explicit_optimizer_parameters')!=parameters):
        raise ValueError('SELECTED_JOB_SOLVER_PARAMETERS_NOT_STARTED_SESSION')
    cumotion=session['sdk'];inspector=session['inspector'];optimizer=session['optimizer']
    if manifest['jerk_limits']!=session['jerk_limits']:raise ValueError('WARM_SOLVER_JERK_LIMITS_CHANGED')
    mapping=update_solver_world(session,request,model)
    prepared_wall=time.perf_counter()-prepared_begin
    q = np.array(request['planning_snapshot']['q_rad'], float)
    original = ET.fromstring(request['model_bundle']['robot_description'])
    bounds = [original.find(f"joint[@name='{name}']/limit") for name in JOINTS]
    if any(not float(b.get('lower'))<=v<=float(b.get('upper')) for b,v in zip(bounds,q)):
        raise ValueError('CUMOTION_START_BOUNDS')
    expected = checked_pose(request['planning_snapshot']['tcp_pose'])
    actual = urdf_transforms(original, q, request['planning_snapshot']['grip_rad'])[TCP]
    if not np.allclose(actual, expected, atol=.0008, rtol=0):
        raise ValueError('CUMOTION_START_FK_MISMATCH')
    if (inspector.num_self_collision_spheres()>1024 or inspector.frames_in_self_collision(q) or
            inspector.in_collision_with_obstacle(q)):
        raise ValueError('CUMOTION_START_COLLISION_OR_SPHERE_LIMIT')
    goal = checked_pose(request['goal'])
    target = cumotion.TrajectoryOptimizer.TaskSpaceTarget(
        cumotion.TrajectoryOptimizer.TranslationConstraint.target(goal[:3,3], .0008),
        cumotion.TrajectoryOptimizer.OrientationConstraint.terminal_target_and_path_axis(
            cumotion.Rotation3.from_matrix(goal[:3,:3]), np.array([0.,0.,1.]),
            expected[:3,2], .005, .15))
    cuda = ctypes.CDLL('libcuda.so.1')
    if cuda.cuInit(0)!=0 or cuda.cuCtxSynchronize()!=0:
        raise RuntimeError('CUDA_SYNCHRONIZATION_FAILED')
    diagnostics=dict(scope='ACTUAL_SDK_CALL_DIAGNOSTICS_NOT_EXECUTION_APPROVAL',selected_job=selected_job,SDK_version=cumotion.__version__,binding=manifest['binding'],
        source_request_sha256=manifest['source_request_sha256'],cache_fingerprint=session['fingerprint'],
        model_manifest=dict(path=str(model/'CUMOTION_MODEL_MANIFEST.json'),sha256=file_hash(model/'CUMOTION_MODEL_MANIFEST.json')),
        model_files=manifest['files'],start_q_rad=q.tolist(),goal=deepcopy(request['goal']),tool_frame=TCP,
        grip_rad=request['planning_snapshot']['grip_rad'],attachment=deepcopy(request['attachment']),
        world_geometry_digest=digest(request['planning_snapshot']['world_objects']),world_mapping=mapping,
        target_constraints=dict(translation_terminal_m=.0008,orientation_terminal_rad=.005,path_axis_rad=.15,
            tool_axis=[0.,0.,1.],world_path_axis=expected[:3,2].tolist()),
        explicit_optimizer_parameters=session.get('explicit_optimizer_parameters'),
        solver_parameters=parameter_ref,solver_session_fingerprint=session.get('solver_session_fingerprint'),
        optimizer_parameter_acceptance=session.get('optimizer_parameter_acceptance'),max_api_plan_calls=1,
        random_seed=dict(value=None,scope='NOT_SET_BY_PROJECT_SDK_DEFAULT_NOT_READ'),
        READY=False,apply_allowed=False)
    result,solve_wall=recorded_sdk_plan(optimizer,q,target,cuda,cumotion.TrajectoryOptimizer.Results.Status.SUCCESS,
        diagnostics,path=diagnostics_path,context_check=context_check)
    retime_begin=time.perf_counter()
    timing_limits=loaded_timing_limits(session['robot'],manifest,timing_profile)
    spline, metadata = retime_sdk_position_path(result.trajectory(),
        [float(b.get('lower')) for b in bounds], [float(b.get('upper')) for b in bounds],
        timing_limits['jerk_limits'], cumotion,
        velocity_limit=timing_limits['velocity_limit'],acceleration_limit=timing_limits['acceleration_limit'])
    metadata['explicit_timing_profile']=timing_profile
    metadata['model_runtime_timing_limits']=timing_limits
    points, export_metadata = export_spline_points(spline)
    metadata.update(export_metadata)
    trajectory = validate_trajectory(dict(joint_names=JOINTS, points=points))
    final_quintic_jerk(trajectory)
    retime_wall=time.perf_counter()-retime_begin
    if context_check:context_check('RETIME_EXPORT_FINISHED')
    prior_uses=session['uses'];session['uses']+=1
    return dict(scope='FILE_ONLY_EXTERNAL_CUMOTION_TIMED', execution_allowed=False,
        hardware_execution_allowed=False, binding=manifest['binding'], trajectory=trajectory,
        timing_engine=TIMING_ENGINE, native_timing_changed=True,
        timing_metadata=metadata, cuMotion_model_files=manifest['files']), dict(
        solve_wall_s=solve_wall, retime_export_wall_s=retime_wall,
        prepared_world_wall_s=prepared_wall,solver_session_reused=solver_session is not None,prior_session_solves=prior_uses,
        cache_fingerprint=session['fingerprint'],world_view_updated=True,
        world_mapping=mapping, sphere_count=inspector.num_self_collision_spheres(),
        geometry_repreparation_inspection=session.get('geometry_repreparation_inspection'),
        fixed_path_axis_tolerance_rad=.15, native_derivatives_used=False,
        geometric_attempts=parameters['trajopt/num_geometric_planning_attempts'], ik_reattempts=parameters['ik/max_reattempts'],
        solver_parameters=parameter_ref,solver_session_fingerprint=session.get('solver_session_fingerprint'))


def calculate(request_path, model, binary, output, *, engine, expected_fcl_sha256,timing_profile='nominal',context_check=None,solver_session=None,selected_job=None):
    if engine!=ENGINE or file_hash(binary)!=expected_fcl_sha256:
        raise ValueError('EXPLICIT_ENGINE_AND_PINNED_FCL_REQUIRED')
    if not sys.flags.isolated or sys.prefix==sys.base_prefix:
        raise ValueError('USE_ISOLATED_CUMOTION_VENV_PYTHON')
    request, manifest = read_cumotion_model(model, request_path)
    if selected_job is not None:
        from bounded_sim_evidence import pinned_json
        selected=pinned_json(selected_job)
        if (selected['cache_request']!=dict(path=str(request_path.resolve()),sha256=file_hash(request_path)) or
                selected['cache_model_manifest']!=dict(path=str((model/'CUMOTION_MODEL_MANIFEST.json').resolve()),sha256=file_hash(model/'CUMOTION_MODEL_MANIFEST.json'))):
            raise ValueError('CALCULATION_NOT_EXACT_SELECTED_JOB_INPUTS')
        selected_optimizer_parameters(selected.get('solver_parameters'))
    live_envelope=request_path.parent/'dynamic_input.envelope.json'
    if live_envelope.exists() and json.loads(live_envelope.read_text()).get('initial_condition_mode')=='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE' and context_check is None:
        raise ValueError('LIVE_OWNER_CALLBACK_REQUIRED_NOT_FIXED_CLI_TIME')
    owner_checks=[]
    if context_check:owner_checks.append(context_check('CALCULATION_START'))
    if manifest['jerk_limits']!=[5.]*6:
        raise ValueError('APPROVED_TEMPORARY_JERK_REQUIRED')
    output.mkdir(parents=True, exist_ok=False)
    begin = time.perf_counter()
    report = dict(status='CUMOTION_CALCULATION_FAILED', engine=engine,
        execution_allowed=False, hardware_execution_allowed=False, auto_fallback=False,
        archived_static_source=manifest.get('archived_static_source'),
        owner_context_checks=owner_checks,
        dynamic_input_ready=False,native_execution_allowed=False,live_freshness_verified=False,
        model_folder=str(model), fcl_binary_sha256=expected_fcl_sha256,selected_job=selected_job,
        solver_parameters=selected.get('solver_parameters') if selected_job is not None else None)
    try:
        if manifest.get('geometry_reuse',{}).get('new_world_inspection_required') and solver_session is None:
            import cumotion
            from prepare_cumotion_model import inspect_model
            report['new_world_model_inspection']=inspect_model(model,request,cumotion)
            if (not report['new_world_model_inspection']['geometric_start_valid'] or
                    report['new_world_model_inspection']['gpu_self_collision_sphere_count']>1024):
                raise ValueError('REUSED_GEOMETRY_NEW_WORLD_REJECTED')
        def solver_check(phase):
            if context_check:owner_checks.append(context_check(phase))
        external, report['solver'] = solve(request, model, manifest,timing_profile,solver_session=solver_session,
            context_check=solver_check if context_check else None,diagnostics_path=output/'solver_attempt.json',selected_job=selected_job)
        if live_envelope.exists():
            online=json.loads(live_envelope.read_text()).get('online_validity')
            if online and external['trajectory']['points'][-1]['time_from_start_s']>online['policy']['max_trajectory_duration_s']:
                raise ValueError('SDK_SUFFIX_EXCEEDS_DYNAMIC_HORIZON')
        if context_check:owner_checks.append(context_check('SDK_FINISHED'))
        external_path = output/'external_timed.input.json'
        save(external_path, external)
        if context_check:owner_checks.append(context_check('FINAL_FCL_START'))
        fcl_begin=time.perf_counter()
        summary, result = fcl_run(binary, request_path, output, 'final', external_path)
        report['final_fcl_wall_s']=time.perf_counter()-fcl_begin
        report['fcl'] = summary
        if context_check:owner_checks.append(context_check('FINAL_FCL_FINISHED'))
        if not summary['plan_success']:
            raise ValueError('FINAL_QUINTIC_FCL_REJECTED:'+str(summary['error']))
        prepare_d_candidate(result, request, {k:request[k] for k in BINDING})
        # Source, saved observation and model must still match after GPU/FCL.
        read_cumotion_model(model, request_path)
        if context_check:owner_checks.append(context_check('RESULT_READY'))
        if file_hash(binary)!=expected_fcl_sha256:
            raise ValueError('FCL_BINARY_CHANGED_DURING_CALCULATION')
        artifacts = dict(request=request_path, external=external_path,
                         fcl_result=output/'final.fcl.yaml',
                         model_manifest=model/'CUMOTION_MODEL_MANIFEST.json')
        report.update(status='CUMOTION_CALCULATION_FCL_VERIFIED',
            artifacts={k:dict(path=str(v),sha256=file_hash(v)) for k,v in artifacts.items()},
            source_files={str(Path(__file__).parent/n):file_hash(Path(__file__).parent/n)
                          for n in ('calculate_cumotion.py','cumotion_timing.py')})
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if (output/'solver_attempt.json').exists():
            report['solver_attempt']=dict(path=str(output/'solver_attempt.json'),sha256=file_hash(output/'solver_attempt.json'))
        report['wall_s'] = time.perf_counter()-begin
        save(output/'calculation_report.json', report)
    return output/'calculation_report.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('request','model','fcl-binary','output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--engine', choices=[ENGINE], required=True)
    parser.add_argument('--fcl-sha256', required=True)
    args = parser.parse_args()
    path = calculate(args.request.resolve(), args.model.resolve(), args.fcl_binary.resolve(),
                     args.output.resolve(), engine=args.engine, expected_fcl_sha256=args.fcl_sha256)
    print(path)


if __name__=='__main__':
    main()
