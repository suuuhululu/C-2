"""Explicit official pose-planner -> spline engine prototype, never auto-fallback.

CPU import/preflight only by default. Missing producer/official internal-IK
control blocks SDK entry; no ROS/action/driver or D admission writer here.
"""
from pathlib import Path
from contextlib import contextmanager
import argparse,ctypes,json,sys,time,os,subprocess,resource,xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from bounded_sim_evidence import pinned_json
from prepare_cpu_model import file_hash
from prepare_cumotion_model import read_cumotion_model,inspect_model,make_world,TCP
from plan_only import checked_pose,JOINTS,BINDING,digest,prepare_d_candidate,validate_trajectory
from benchmark_cumotion import save,fcl_run
from stop_curve import validate_quintic_limits
from cumotion_timing import export_spline_points,final_quintic_jerk
from cumotion_axis_gate import certify_axis
ENGINE='NVIDIA_MOTION_PLANNER_POSE_CSPACE_GENERATOR_FCL_CALCULATION_ONLY_V1'
INTERNAL_IK_CONTROL='UNKNOWN_NO_DOCUMENTED_PUBLIC_RESTART_OR_ITERATION_BUDGET'
DIRECT_TIMING_PROTOCOL='CUMOTION_NATIVE_NO_TOTG'
DIRECT_TIMING_METADATA_ENGINE='OFFICIAL_CSPACE_TRAJECTORY_GENERATOR_DIRECT_CUBIC_NO_TOTG_V1'

def ref(path):return dict(path=str(Path(path).resolve()),sha256=file_hash(Path(path)))


@contextmanager
def host_interval(phases,name):
    """Host wall only; no CUDA synchronization or extra SDK calls."""
    row=dict(status='RUNNING',monotonic_start_s=time.monotonic(),perf_counter_start_s=time.perf_counter())
    phases[name]=row
    try:
        yield
        row['status']='COMPLETED'
    except BaseException as error:
        row.update(status='FAILED',error_type=type(error).__name__,error=str(error));raise
    finally:
        row.update(monotonic_end_s=time.monotonic(),perf_counter_end_s=time.perf_counter())
        row['host_wall_s']=row['perf_counter_end_s']-row['perf_counter_start_s']


def persist_raw_path(path,found,*,origin,start_q,target_q,source_refs):
    """Snapshot Results.path once; return unchanged typed copies for generator.

    Bytes are authoritative even for NaN/Inf; finite JSON values are readable
    companions. Failure/empty paths are evidence, never valid solutions.
    """
    raw=found.path
    nodes=[] if raw is None else [np.array(q,copy=True) for q in raw]
    rows=[]
    for node in nodes:
        if node.dtype.kind not in 'fiu':raise ValueError('RAW_SDK_PATH_NUMERIC_DTYPE_REQUIRED')
        rows.append(dict(dtype=node.dtype.str,shape=list(node.shape),order='C',bytes_hex=node.tobytes(order='C').hex(),
            values=node.tolist() if np.isfinite(node).all() else None,finite=bool(np.isfinite(node).all())))
    record=dict(schema='cumotion-raw-search-path/0.1',origin=origin,API_property='MotionPlanner.Results.path',
        path_found=bool(found.path_found),path_present=raw is not None,node_count=len(nodes),nodes=rows,
        status=('PATH_RETURNED' if nodes else 'FOUND_EMPTY_PATH') if found.path_found else ('SEARCH_FAILED_WITH_RETURNED_NODES' if nodes else 'SEARCH_FAILED_EMPTY_PATH'),
        joint_names=JOINTS,units='rad',start_q=deepcopy_list(start_q),target_q=deepcopy_list(target_q),source_refs=source_refs,
        resampled=False,retimed=False,execution_allowed=False)
    with Path(path).open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2,allow_nan=False)
    return nodes


def deepcopy_list(value):return None if value is None else np.asarray(value).tolist()


@contextmanager
def validation_stage(report,name):
    """Keep the exact rejection stage without authorizing a diagnostic export."""
    report['validation_stage']=name
    try:
        yield
    except Exception as error:
        report.update(validation_failed_stage=name,validation_error_type=type(error).__name__)
        raise


def capture_generated_pvt(curve,path,report,*,source_refs,origin):
    """Persist existing exporter output before approval, never evaluate it twice.

    Typed bytes describe the exported Python values (not SDK array storage).
    This diagnostic is separate from raw search nodes and the FCL/D input.
    An export exception exposes no completed return value; do not invent one.
    """
    record=dict(schema='cumotion-generated-pvt-diagnostic/0.1',origin=origin,
        source_refs=source_refs,joint_names=list(JOINTS),
        units=dict(positions_rad='rad',velocities_rad_s='rad/s',accelerations_rad_s2='rad/s^2',time_from_start_s='s'),
        time_basis='ELAPSED_FROM_GENERATOR_DOMAIN_LOWER_EXISTING_EXPORTER_NANOSECOND_QUANTIZATION',
        representation='EXISTING_EXPORT_SPLINE_POINTS_RETURN_VALUES_NOT_SERIALIZED_SDK_OBJECT',
        SDK_object_present=curve is not None,export_complete=False,point_count=0,
        READY=False,apply_allowed=False,execution_allowed=False,hardware_execution_allowed=False,native_execution_allowed=False,
        validated=False,resampled_after_export=False,retimed_after_export=False)
    def persist():
        with Path(path).open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2,allow_nan=False)
        report['generated_pvt_diagnostic']=ref(path)
        report['generated_pvt_export_status']=record['status']
    if curve is None:
        record['status']='NO_TRAJECTORY_OBJECT';persist()
        raise ValueError('OFFICIAL_TRAJECTORY_GENERATION_FAILED_NO_RETRY')
    try:
        points,metadata=export_spline_points(curve)
    except Exception as error:
        record.update(status='EXPORT_FAILED_NO_COMPLETE_PVT_RETURNED',error_type=type(error).__name__,error=str(error))
        persist();raise
    fields=('positions_rad','velocities_rad_s','accelerations_rad_s2','time_from_start_s')
    typed=[];finite=True
    for point in points:
        row={}
        for name in fields:
            array=np.asarray(point[name])
            if array.dtype.kind not in 'fiu':raise ValueError('EXPORTED_PVT_NUMERIC_DTYPE_REQUIRED')
            ok=bool(np.isfinite(array).all());finite=finite and ok
            row[name]=dict(dtype=array.dtype.str,shape=list(array.shape),order='C',bytes_hex=array.tobytes(order='C').hex(),
                values=array.tolist() if ok else None,finite=ok)
        typed.append(row)
    record.update(status='EXPORTED_COMPLETE_UNVALIDATED',export_complete=True,point_count=len(points),
        exported_points=points if finite else None,all_fields_finite=finite,typed_exported_points=typed,export_metadata=metadata)
    persist()
    return points,metadata


def export_and_validate_generated(curve,output,report,request,lower,upper,*,source_refs,origin,current):
    """One export; immutable PVT precedes every trajectory/axis/endpoint gate."""
    report['generated_pvt_export_status']='NOT_STARTED'
    with validation_stage(report,'POST_GENERATION_CURRENT_CHECK'):
        # Retain the allocation/resource guard before further SDK evaluations.
        # A missing object requires no further SDK evaluation.
        if curve is not None:current('TRAJECTORY_GENERATION_FINISHED')
    with validation_stage(report,'GENERATED_PVT_EXPORT_AND_PERSIST'):
        points,metadata=capture_generated_pvt(curve,output/'generated_pvt.diagnostic.json',report,source_refs=source_refs,origin=origin)
    with validation_stage(report,'TRAJECTORY_STRUCTURE'):
        trajectory=validate_trajectory(dict(joint_names=JOINTS,points=points))
    with validation_stage(report,'FINAL_QUINTIC_VA_LIMITS'):
        report['limits']=validate_quintic_limits(trajectory,lower,upper)
    with validation_stage(report,'FINAL_QUINTIC_JERK'):
        final_quintic_jerk(trajectory)
    with validation_stage(report,'CONTINUOUS_ORIGINAL_AXIS'):
        axis=checked_pose(request['planning_snapshot']['tcp_pose'])[:3,2].tolist();t=time.perf_counter()
        report['axis_certificate']=certify_axis(trajectory,request['model_bundle']['robot_description'],TCP,axis)
        report['axis_wall_s']=time.perf_counter()-t
        report['axis_certificate']['trajectory_digest']=digest(trajectory)
    with validation_stage(report,'POST_AXIS_CURRENT_CHECK'):
        current('FINAL_AXIS_CERTIFICATE_FINISHED')
    with validation_stage(report,'ORIGINAL_ENDPOINT_POSE'):
        endpoint=np.array(curve.eval(curve.domain().upper,0));from prepare_cumotion_model import urdf_transforms
        xml=ET.fromstring(request['model_bundle']['robot_description'])
        actual=urdf_transforms(xml,endpoint,request['planning_snapshot']['grip_rad'])[TCP];goal=checked_pose(request['goal'])
        if np.linalg.norm(actual[:3,3]-goal[:3,3])>.0008 or Rotation.from_matrix(actual[:3,:3].T@goal[:3,:3]).magnitude()>.005:
            raise ValueError('ORIGINAL_A_POSE_GOAL_REJECTED')
    with validation_stage(report,'ORIGINAL_32S_HORIZON'):
        if points[-1]['time_from_start_s']>32:raise ValueError('ORIGINAL32S_TRAJECTORY_HORIZON_EXCEEDED')
    return trajectory,metadata


def check_spec(item):
    spec=pinned_json(item)
    if (spec['schema']!='cumotion-explicit-pose-path-engine/0.1' or spec['engine']!=ENGINE or
            spec['API_budget']!=dict(official_inspection=1,pose_search=1,trajectory_generation=1,external_IK=0,external_OMPL=0,external_retry=0) or
            spec['target_limits']!=dict(translation_m=.0008,orientation_rad=.005,path_axis_rad=.15) or
            spec['command_limits']!=dict(velocity_rad_s=.35,acceleration_rad_s2=.7,temporary_jerk_rad_s3=5.) or
            spec['internal_IK_control']!=INTERNAL_IK_CONTROL or spec['auto_fallback'] is not False):
        raise ValueError('EXPLICIT_POSE_ENGINE_SPEC_CHANGED')
    for name,item in spec['source_files'].items():
        if Path(item['path']).resolve()!=Path(__file__).resolve().parent/name or ref(item['path'])!=item:
            raise ValueError('POSE_ENGINE_SOURCE_CHANGED:'+name)
    return spec

def selected_inputs(config):
    """Exact returned native job/context and request, never a private selection."""
    return _selected_inputs_core(config,check_spec,ENGINE,'pose_engine_spec')

def _selected_inputs_core(config,spec_check,engine,binding_field):
    spec=spec_check(config['engine_spec']);job=pinned_json(config['selected_job']);context=pinned_json(config['native_context'])
    if (job.get('planning_engine')!=engine or context.get('planning_engine')!=engine or
            job.get(binding_field)!=config['engine_spec'] or context.get(binding_field)!=config['engine_spec'] or
            context.get('selected_job')!=config['selected_job'] or job.get('D_input_approval') is None):
        raise ValueError('ACTUAL_NATIVE_SELECTED_POSE_ENGINE_BINDING_REQUIRED')
    from request_cumotion_admission import check_response
    response=pinned_json(config['D_response']);request_ref=response['request'];admission=pinned_json(request_ref)
    selected,value=check_response(response,request_ref,admission)
    if selected!=config['selected_job'] or value!=job:raise ValueError('POSE_ENGINE_NOT_EXACT_D_SELECTED_RESPONSE')
    path=Path(job['cache_request']['path']);model=Path(job['cache_model_manifest']['path']).parent
    if ref(path)!=job['cache_request'] or ref(model/'CUMOTION_MODEL_MANIFEST.json')!=job['cache_model_manifest']:
        raise ValueError('POSE_ENGINE_CACHE_PIN_CHANGED')
    prepared,manifest=read_cumotion_model(model,path)
    inputs=pinned_json(context['obstacles']);envelope=pinned_json(context['envelope'])
    if (inputs['limits']!=job['limits'] or envelope['request_sha256']!=job['cache_request']['sha256'] or
            context['identity']!=job['identity'] or job['identity']!=envelope['online_validity']['identity']):
        raise ValueError('POSE_ENGINE_ORIGINAL_CONTEXT_CHANGED')
    if manifest['jerk_limits']!=[5.]*6:raise ValueError('APPROVED_TEST_JERK_REQUIRED')
    return spec,job,context,prepared,manifest,path,model

def preflight(config):
    if config.get('engine')!=ENGINE:raise ValueError('EXPLICIT_POSE_ENGINE_REQUIRED')
    check_spec(config['engine_spec']);missing=[k for k in ('selected_job','native_context','D_response','allocation') if not config.get(k)]
    blockers=['WAIT_OFFICIAL_INTERNAL_IK_CONTROL:'+INTERNAL_IK_CONTROL]
    if missing:blockers.append('WAIT_ACTUAL_FRESH_PRODUCER_FIELDS:'+','.join(missing))
    if not missing:selected_inputs(config)
    return dict(status='BLOCKED_BEFORE_SDK',engine=ENGINE,blockers=blockers,SDK_imported=False,SDK_started=False,READY=False,apply_allowed=False)

def _calculate_selected(config,check):
    """Shared explicit-mode compute body; Pose remains blocked on its IK contract.

    Live checks re-read original owner/Depth. Explicit archive checks only its
    independent lease/resources and never claim current D/STOP approval.
    """
    worker_started=(time.monotonic(),time.perf_counter())
    if not sys.flags.isolated or sys.prefix==sys.base_prefix:raise ValueError('ISOLATED_VENV_REQUIRED_BEFORE_SDK')
    engine=config.get('engine');entry_preflight=preflight;entry_inputs=selected_inputs;qualification=None;search_key='pose_search'
    if engine!=ENGINE:
        from cumotion_cspace_engine import ENGINE as CS_ENGINE,preflight as cs_preflight,selected_inputs as cs_inputs,qualify_endpoint
        if engine!=CS_ENGINE:raise ValueError('EXPLICIT_SUPPORTED_ENGINE_REQUIRED')
        entry_preflight=cs_preflight;entry_inputs=cs_inputs;search_key='cspace_search'
    archive=config.get('scope')=='ARCHIVED_OFFLINE_CALCULATION'
    if archive:
        if search_key!='cspace_search':raise ValueError('ARCHIVE_REQUIRES_EXPLICIT_CSPACE_ENGINE')
        from cspace_offline_engine import preflight as entry_preflight,archived_inputs as entry_inputs
    validation=entry_preflight(config)
    if validation['blockers']:raise ValueError(';'.join(validation['blockers']))
    spec,job,context,request,manifest,path,model=entry_inputs(config)
    if search_key=='cspace_search':qualification=qualify_endpoint(request,spec)
    allocation=pinned_json(config['allocation'])
    if archive:
        from cumotion_archive_lease import review as review_archive_lease,owned_claim
        grant=review_archive_lease(config,spec);owned_claim(config,grant)
    else:
        grant=allocation['concurrent_cumotion']
        if grant.get('allowed') is not True or grant.get('engine')!=engine or grant.get('engine_spec')!=config['engine_spec'] or grant.get('selected_job')!=config.get('selected_job'):
            raise ValueError('NEW_EXACT_POSE_ENGINE_ALLOCATION_REQUIRED')
        from online_cumotion_worker import verify_allocated_isaac_owner
        if grant.get('API_budget')!=spec['API_budget'] or grant.get('maximum_jobs')!=1 or grant.get('owner_pointer')!=config.get('owner_pointer'):
            raise ValueError('EXACT_ENGINE_API_BUDGET_AND_OWNER_REQUIRED')
        verify_allocated_isaac_owner(grant)
        apps=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,process_name,used_gpu_memory','--format=csv,noheader,nounits'],text=True)
        if any('python' in row.lower() and int(row.split(',')[0])!=grant['isaac_owner_pid'] for row in apps.splitlines()):
            raise ValueError('ANOTHER_CUDA_WORKER_PRESENT_NO_CONCURRENT_ENGINE_START')
        free=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())
        if free<grant['minimum_free_before_start_mib']:raise ValueError('ALLOCATED_MEMORY_UNAVAILABLE')
    output=Path(config['output']);output.mkdir(parents=True,exist_ok=False)
    report=dict(engine=engine,status='EXPLICIT_PATH_ENGINE_CALCULATION_FAILED',selected_job=config.get('selected_job'),engine_spec=config['engine_spec'],
        native_context=config.get('native_context'),D_response=config.get('D_response'),model_folder=str(model),fcl_binary_sha256=job['fcl_binary']['sha256'],auto_fallback=False,execution_allowed=False,hardware_execution_allowed=False,READY=False,apply_allowed=False)
    if archive:report.update(scope='ARCHIVED_OFFLINE_CALCULATION',archived_job=config['archived_job'])
    phases={name:dict(status='NOT_STARTED') for name in ('sdk_import','official_inspection','robot_load','world_setup','planner_setup')}
    report['host_initialization_intervals']=phases
    calls=dict(official_inspection=0,trajectory_generation=0);calls[search_key]=0;events=[];sampler=None
    if qualification is not None:report['fresh_endpoint_candidate_qualification']=qualification
    def current(phase):
        if pinned_json(config['allocation'])!=allocation:raise ValueError('ENGINE_ALLOCATION_CHANGED')
        events.append(check(phase));return events[-1]
    try:
        sampler=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('cumotion_memory_sampler.py')),'--pid',str(os.getpid()),'--output',str(output/'memory.jsonl'),'--stop',str(output/'sampler.stop')],stdout=subprocess.DEVNULL,stderr=(output/'sampler.stderr.txt').open('x'))
        report['sampler_pid']=sampler.pid
        current('EXPLICIT_PATH_ENGINE_BEFORE_SDK')
        with host_interval(phases,'sdk_import'):
            import cumotion
            if cumotion.__version__!='1.1.0' or not Path(cumotion.__file__).resolve().is_relative_to(Path(sys.prefix)):raise ValueError('ISOLATED_SDK1_1_0_REQUIRED')
        with host_interval(phases,'official_inspection'):
            calls['official_inspection']+=1;report['inspection']=inspect_model(model,request,cumotion)
            if not report['inspection']['geometric_start_valid'] or report['inspection']['gpu_self_collision_sphere_count']>1024:raise ValueError('FRESH_POSE_ENGINE_MODEL_REJECTED')
        with host_interval(phases,'robot_load'):
            robot=cumotion.load_robot_from_file(model/'robot.xrdf',model/'robot.urdf')
        with host_interval(phases,'world_setup'):
            world,mapping=make_world(request,cumotion);view=world.add_world_view();view.update()
        if [robot.cspace_coord_name(i) for i in range(robot.num_cspace_coords())]!=JOINTS:raise ValueError('POSE_ENGINE_JOINT_ORDER_CHANGED')
        with host_interval(phases,'planner_setup'):
            cfg=cumotion.create_default_motion_planner_config(robot,TCP,view)
            params=({'enable_self_collision_checking':True,'task_space_planning_params/translation_target_final_tolerance':.0008,'task_space_planning_params/orientation_target_final_tolerance':.005} if qualification is None else {'enable_self_collision_checking':True,'max_iterations':10000,'max_sampling':10000,'seed':1234})
            report['planner_parameter_acceptance']={}
            for name,value in params.items():
                accepted=bool(cfg.set_param(name,value));report['planner_parameter_acceptance'][name]=accepted
                if not accepted:raise ValueError('OFFICIAL_PATH_PLANNER_PARAMETER_REJECTED:'+name)
            planner=cumotion.create_motion_planner(cfg);cuda=ctypes.CDLL('libcuda.so.1')
        def synchronize():
            if cuda.cuInit(0)!=0 or cuda.cuCtxSynchronize()!=0:raise ValueError('POSE_ENGINE_CUDA_SYNC_FAILED')
        current('PATH_SEARCH_START');synchronize();t=time.perf_counter();calls[search_key]+=1
        if qualification is None:found=planner.plan_to_pose_target(np.array(request['planning_snapshot']['q_rad']),cumotion.Pose3(checked_pose(request['goal'])),True)
        else:found=planner.plan_to_cspace_target(np.array(request['planning_snapshot']['q_rad']),np.array(qualification['q_rad']),True)
        synchronize();report[search_key]=dict(wall_s=time.perf_counter()-t,path_found=bool(found.path_found));save(output/'path_search_status.json',report[search_key])
        if qualification is not None:
            nodes=persist_raw_path(output/'raw_sdk_path.json',found,
                origin=dict(kind='ACTUAL_SDK_CALL_RESULT',version=cumotion.__version__,API='MotionPlanner.plan_to_cspace_target',call_index=calls[search_key],generate_interpolated_path=True),
                start_q=request['planning_snapshot']['q_rad'],target_q=qualification['q_rad'],
                source_refs=dict(request=job['cache_request'],model_manifest=job['cache_model_manifest'],engine_spec=config['engine_spec']))
            report['raw_sdk_path']=ref(output/'raw_sdk_path.json')
        else:nodes=[np.array(q,copy=True) for q in found.path]
        current('PATH_SEARCH_FINISHED')
        if not found.path_found:raise ValueError('OFFICIAL_PATH_NOT_FOUND_NO_RETRY')
        if len(nodes)<2:raise ValueError('OFFICIAL_PATH_HAS_INSUFFICIENT_NODES')
        generator=cumotion.create_cspace_trajectory_generator(robot.kinematics());xml=ET.fromstring(request['model_bundle']['robot_description'])
        bounds=[xml.find(f"joint[@name='{n}']/limit") for n in JOINTS];lower=np.array([float(b.get('lower')) for b in bounds]);upper=np.array([float(b.get('upper')) for b in bounds])
        generator.set_position_limits(lower,upper);generator.set_velocity_limits(np.full(6,.35));generator.set_acceleration_limits(np.full(6,.7));generator.set_jerk_limits(np.full(6,5.))
        with validation_stage(report,'OFFICIAL_TRAJECTORY_GENERATION'):
            current('TRAJECTORY_GENERATION_START');synchronize();t=time.perf_counter();calls['trajectory_generation']+=1;curve=generator.generate_trajectory(nodes);synchronize()
        report['generation']=dict(wall_s=time.perf_counter()-t,object_present=curve is not None)
        trajectory,metadata=export_and_validate_generated(curve,output,report,request,lower,upper,
            source_refs=dict(request=job['cache_request'],model_manifest=job['cache_model_manifest'],engine_spec=config['engine_spec'],
                raw_sdk_path=report.get('raw_sdk_path'),archived_job=config.get('archived_job'),selected_job=config.get('selected_job')),
            origin=dict(kind='ACTUAL_GENERATOR_EXPORT',version=cumotion.__version__,API='CSpaceTrajectoryGenerator.generate_trajectory',
                call_index=calls['trajectory_generation']),current=current)
        metadata.update(engine=DIRECT_TIMING_METADATA_ENGINE,source_API='CSpaceTrajectoryGenerator.generate_trajectory',native_derivatives_used=True,collision_aware=False,final_quintic_fcl_required=True,continuous_original_axis_required=True,position_fit_performed=False,sampled_position_fit_error_rad=None,position_fit_status='NOT_APPLICABLE_DIRECT_GENERATOR_NO_FIT',used_velocity_limit_rad_s=.35,used_acceleration_limit_rad_s2=.7,used_jerk_limits_rad_s3=[5.]*6)
        external=dict(scope='FILE_ONLY_EXTERNAL_CUMOTION_TIMED',execution_allowed=False,hardware_execution_allowed=False,binding=manifest['binding'],trajectory=trajectory,
            engine=engine,timing_engine=DIRECT_TIMING_PROTOCOL,native_timing_changed=False,timing_metadata=metadata,cuMotion_model_files=manifest['files'])
        with validation_stage(report,'EXTERNAL_FCL_INPUT_AND_CURRENT'):
            save(output/'external_timed.input.json',external);current('FINAL_ORIGINAL_FCL_START')
        with validation_stage(report,'ORIGINAL_FULL_FCL'):
            if ref(job['fcl_binary']['path'])!=job['fcl_binary']:raise ValueError('ORIGINAL_FCL_BINARY_CHANGED')
            summary,result=fcl_run(Path(job['fcl_binary']['path']),path,output,'final',output/'external_timed.input.json');report['FCL']=summary
            if not summary['plan_success']:raise ValueError('FINAL_ORIGINAL_FCL_REJECTED')
        with validation_stage(report,'DIRECT_RESULT_PROTOCOL'):
            if search_key=='cspace_search':
                from cspace_result_protocol import validate_direct_export
                validate_direct_export(external,result)
        with validation_stage(report,'D_CANDIDATE_AND_FINAL_CURRENT'):
            prepare_d_candidate(result,request,{k:request[k] for k in BINDING});current('FINAL_ORIGINAL_FCL_FINISHED');entry_inputs(config)
        report.update(status=('POSE_ENGINE_ORIGINAL_FCL_VERIFIED_PENDING_CURRENT_AND_ENCODING' if engine==ENGINE else 'CSPACE_ENGINE_ORIGINAL_FCL_VERIFIED_PENDING_CURRENT_AND_ENCODING'),artifacts={k:ref(v) for k,v in dict(request=path,external=output/'external_timed.input.json',fcl_result=output/'final.fcl.yaml',model_manifest=model/'CUMOTION_MODEL_MANIFEST.json').items()},world_mapping=mapping)
        if archive:report['status']='ARCHIVED_CSPACE_ORIGINAL_FCL_VERIFIED_NOT_LIVE_OR_D_APPROVAL'
    except Exception as e:report['error']=str(e)
    finally:
        if sampler is not None:
            (output/'sampler.stop').write_text('Normal own sampler completion\n');sampler.wait(timeout=10)
            samples=[json.loads(s) for s in (output/'memory.jsonl').read_text().splitlines()] if (output/'memory.jsonl').exists() else []
            report['memory']=dict(samples=len(samples),sample_errors=sum('error' in s for s in samples),sampled_VRAM_lower_bound_MiB=max((s.get('worker_VRAM_MiB',0) for s in samples),default=None),peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,max_sample_gap_s=max((b['start_monotonic_s']-a['start_monotonic_s'] for a,b in zip(samples,samples[1:])),default=None))
            if not any('worker_VRAM_MiB' in sample for sample in samples):report.update(status='ENGINE_MEMORY_OBSERVATION_UNAVAILABLE',error='No actual worker VRAM sample; no result adoption')
            if any(s.get('worker_VRAM_MiB',0)>grant['max_worker_vram_mib'] for s in samples) or report['memory']['peak_RSS_KiB']>grant['worker_host_ram_mib']*1024:report.update(status='ENGINE_MEMORY_RESERVATION_REJECTED',error='Observed allocated worker memory exceeded')
        ended=(time.monotonic(),time.perf_counter())
        report['calculation_body_host_interval']=dict(monotonic_start_s=worker_started[0],perf_counter_start_s=worker_started[1],
            monotonic_end_s=ended[0],perf_counter_end_s=ended[1],host_wall_s=ended[1]-worker_started[1],
            scope='CALCULATION_BODY_ENTRY_TO_REPORT_ASSEMBLY_EXCLUDES_CLI_BOOTSTRAP_AND_PROCESS_EXIT')
        if phases['sdk_import']['status']!='NOT_STARTED':
            end=max(row.get('perf_counter_end_s',phases['sdk_import']['perf_counter_start_s']) for row in phases.values())
            report['cold_initialization_host_span']=dict(host_wall_s=end-phases['sdk_import']['perf_counter_start_s'],
                status='COMPLETED' if phases['planner_setup']['status']=='COMPLETED' else 'INCOMPLETE',
                scope='HOST_IMPORT_TO_PLANNER_END_INCLUDES_INSPECTION_AND_GUARDS_NO_ADDED_CUDA_SYNC_NOT_SUM_OF_CHILD_TIMERS')
        report.update(API_calls=calls,live_owner_checks=events,current_geometry_and_encoded_proof='PENDING_REQUIRED_NOT_EXECUTED',native_execution_allowed=False);save(output/'calculation_report.json',report)
    return output/'calculation_report.json'

def run(config):
    result=preflight(config)
    # No bypass flag: public MotionPlanner internal IK limits/retries are not yet
    # documented/bound to this prototype's allocation contract.
    raise ValueError(';'.join(result['blockers']))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--start',action='store_true');a=p.parse_args();config=json.loads(a.config.read_text())
    print(json.dumps(preflight(config),ensure_ascii=False,indent=2))
    if a.start:run(config)

if __name__=='__main__':main()
