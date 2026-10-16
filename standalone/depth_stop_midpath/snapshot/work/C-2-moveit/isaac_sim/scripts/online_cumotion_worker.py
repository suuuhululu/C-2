"""Explicit, single-process SDK worker with atomic owner/job/result file IPC.

The native owner never waits for this worker and remains the only action writer.
Import/help/CPU checks do not import cuMotion or create a CUDA context.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parent))
import yaml
from benchmark_cumotion import save
from bounded_sim_evidence import pinned_json
from calculate_cumotion import start_solver,solver_fingerprint,selected_optimizer_parameters
from cumotion_timing import ENGINE as LEGACY_ENGINE
from dynamic_cumotion_inputs import verify_input_anchor,prepare_inputs,depth_packet,sealed
from live_cumotion_boundary import live_context_checker,transition_candidate,check_transition_fcl,review_transition
from online_cumotion_validity import IDENTITY,LIVE_SCOPE,computational_geometry
from plan_cumotion_sim import run_live_calculation
from prepare_cpu_model import file_hash
from prepare_cumotion_model import load_model_yaml,read_cumotion_model,reuse_collision_geometry,reprepare_collision_geometry,verify_request
from plan_only import JOINTS,BINDING,digest


def require_legacy_engine(value):
    if any(value.get(key) not in (None,LEGACY_ENGINE) for key in ('engine','planning_engine')):
        raise ValueError('EXPLICIT_OTHER_ENGINE_REQUIRES_ITS_OWN_ENTRYPOINT')


def ref(path):return dict(path=str(Path(path).resolve()),sha256=file_hash(path))


def bind_solver_parameters(config,grant,job,context):
    """No GPU. Explicit experiment must be selected by all four pinned scopes."""
    parameter_ref=job.get('solver_parameters')
    if any(value.get('solver_parameters')!=parameter_ref for value in (config,grant,context)):
        raise ValueError('SOLVER_PARAMETERS_CONFIG_GRANT_JOB_CONTEXT_MISMATCH')
    selected_optimizer_parameters(parameter_ref)
    if parameter_ref is not None and (config.get('maximum_jobs')!=1 or grant.get('max_api_plan_calls')!=1):
        raise ValueError('EXPLICIT_SINGLE_API_PLAN_ALLOCATION_REQUIRED')
    return parameter_ref


def publish(path,value):
    """Only mutable pointers use replace; all referenced artifacts are exclusive."""
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    save(temporary,value)
    os.replace(temporary,path)


def publish_owner_observation(packet,owner,folder,pointer):
    """Native owner passes actual values; no getters, tick/stop inference or zeros."""
    packet=deepcopy(packet);state=packet['state']
    if any(state[k]!=owner[k] for k in ('q_rad','v_rad_s','a_rad_s2','state_sequence')):
        raise ValueError('PUBLISH_RAW_OWNER_STATE_MISMATCH')
    sequence=packet['observation_sequence']
    if type(sequence) is not int or sequence<0:raise ValueError('OBSERVATION_SEQUENCE_REQUIRED')
    folder=Path(folder)/('observation_'+str(sequence));folder.mkdir(parents=True,exist_ok=False)
    save(folder/'owner.json',owner)
    state['owner_evidence']=ref(folder/'owner.json');packet['state']=sealed(state)
    save(folder/'packet.json',packet)
    publication=dict(schema='live-cumotion-owner-publication/0.1',packet=ref(folder/'packet.json'),
        observation_sequence=sequence,source_now_s=owner['now_s'])
    publish(pointer,publication)
    return publication


def read_owner_publication(path,identity):
    """Read current immutable per-tick packet behind one atomic owner pointer."""
    path=Path(path);raw=path.read_bytes();pointer=json.loads(raw)
    if pointer['schema']!='live-cumotion-owner-publication/0.1':raise ValueError('CURRENT_OWNER_PUBLICATION_REQUIRED')
    packet=pinned_json(pointer['packet'])
    owner=pinned_json(packet['state']['owner_evidence']);owner=owner.get('owner_context',owner)
    if {k:owner[k] for k in IDENTITY}!=identity:raise ValueError('IPC_OWNER_IDENTITY_CHANGED')
    if (pointer['observation_sequence']!=packet['observation_sequence'] or
            pointer['source_now_s']!=owner['now_s'] or packet.get('timeline_running') is not True):
        raise ValueError('IPC_CURRENT_OBSERVATION_OR_TIMELINE_MISMATCH')
    if path.read_bytes()!=raw:raise ValueError('OWNER_PUBLICATION_CHANGED_DURING_READ')
    packet['_source_packet_evidence']=pointer['packet']
    return packet


def prepare_online_request(base_path,packet,limits,output,previous=None):
    """Fresh actual q/Depth; no saved source-now or scene relabelling."""
    from live_cumotion_boundary import verify_owner_state
    from dynamic_cumotion_inputs import owner_observations,normalize_owner_stop_state
    base=verify_input_anchor(base_path,limits)
    if owner_observations(limits):
        packet=deepcopy(packet)
        packet['state']=normalize_owner_stop_state(packet['state'],limits,base['model_bundle'],packet['_source_packet_evidence'])
    owner=verify_owner_state(base,packet['state'],packet['control'],limits)
    for key in ('session_id','clock_basis','clock_epoch'):
        if packet['desired'][key]!=owner[key]:raise ValueError('JOB_DESIRED_SOURCE_IDENTITY_MISMATCH:'+key)
    bound=packet['latest_depth_bound']
    if bound.get('online_motion',{}).get('scope')!=LIVE_SCOPE:
        raise ValueError('FROZEN_OR_UNVERIFIED_BOUND_CANNOT_START_ONLINE_JOB')
    envelope=prepare_inputs(base_path,packet['state'],depth_packet(bound,packet['state'],bound['frame_seq'],
        planner_box_representation=limits.get('planner_box_representation')),
        packet['control'],limits,now_s=owner['now_s'],output=output,previous=previous)
    return envelope


def admit_online_job(job,cache,*,session_fingerprint=None):
    """CPU validation of the exact Rosbridge-frozen job/cache; no SDK import."""
    if job.get('example_only') is True:raise ValueError('PENDING_EXAMPLE_JOB_NOT_EXECUTABLE')
    for key in ('base_request','fcl_binary','fcl_library','cache_request','cache_model_manifest'):
        if ref(job[key]['path'])!=job[key]:raise ValueError('JOB_SELECTED_INPUT_CHANGED:'+key)
    if Path(job['cache_request']['path']).resolve()!=Path(cache['request']).resolve() or Path(job['cache_model_manifest']['path']).parent.resolve()!=Path(cache['model']).resolve():
        raise ValueError('JOB_CACHE_DIFFERS_FROM_STARTED_SESSION')
    request,manifest=read_cumotion_model(Path(cache['model']),Path(cache['request']))
    if set(job['cache_files'])!=set(manifest['files']):raise ValueError('JOB_CACHE_FILE_SET_CHANGED')
    for name,expected in manifest['files'].items():
        if ref(Path(cache['model'])/name)!=job['cache_files'][name] or job['cache_files'][name]['sha256']!=expected:
            raise ValueError('JOB_CACHE_GEOMETRY_CHANGED:'+name)
    fingerprint=solver_fingerprint(request,Path(cache['model']))
    if fingerprint!=job['cache_fingerprint'] or session_fingerprint is not None and session_fingerprint!=fingerprint:
        raise ValueError('JOB_WARM_SESSION_FINGERPRINT_CHANGED')
    if job['limits']['initial_condition_mode']!='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE':raise ValueError('JOB_LIVE_INPUT_MODE_REQUIRED')
    import xml.etree.ElementTree as ET
    base=verify_input_anchor(Path(job['base_request']['path']),job['limits'])
    robot=ET.fromstring(base['model_bundle']['robot_description'])
    bounds=[robot.find(f"joint[@name='{name}']/limit") for name in JOINTS]
    if job['review_args']['lower']!=[float(b.get('lower')) for b in bounds] or job['review_args']['upper']!=[float(b.get('upper')) for b in bounds]:
        raise ValueError('JOB_REVIEW_BOUNDS_DIFFER_FROM_MODEL')
    if job['review_args']['expected_fcl_sha256']!=job['fcl_library']['sha256'] or job['review_args']['next_goal_version']!=job['identity']['goal_version']+1:
        raise ValueError('JOB_LIBRARY_OR_NEXT_VERSION_CHANGED')
    if job.get('previous_cursor'):pinned_json(job['previous_cursor'])
    return dict(cache_fingerprint=fingerprint,selected_input_pins_verified=True,SDK_started=False)


def prepare_online_model(cache,request_path,output,*,session_fingerprint=None):
    """CPU model selection; changed transforms produce NEW files, never warm approval."""
    old_model,old_path=Path(cache['model']),Path(cache['request'])
    request_path,output=Path(request_path),Path(output)
    old,manifest=read_cumotion_model(old_model,old_path);fresh=verify_request(request_path)
    same_transform=(old['attachment']==fresh['attachment'] and
        old['planning_snapshot']['grip_rad']==fresh['planning_snapshot']['grip_rad'])
    if same_transform:
        reuse_collision_geometry(old_model,old_path,request_path,output)
        method='IDENTICAL_GEOMETRY_REUSE'
    else:
        reprepare_collision_geometry(old_model,old_path,request_path,output,manifest['jerk_limits'])
        method='NEW_EXACT_GRIP_ATTACHMENT_FROM_INVARIANT_SOLIDS'
    selected,prepared=read_cumotion_model(output,request_path)
    fingerprint=solver_fingerprint(selected,output)
    restart=session_fingerprint!=fingerprint
    result=dict(status='WAIT_EXPLICIT_SDK_INSPECTION_AND_RESTART' if restart else 'IDENTICAL_MODEL_FOR_EXISTING_SESSION',
        method=method,request=ref(request_path),model_manifest=ref(output/'CUMOTION_MODEL_MANIFEST.json'),
        model_files={name:ref(output/name) for name in prepared['files']},
        source_cache_request=ref(old_path),source_cache_manifest=ref(old_model/'CUMOTION_MODEL_MANIFEST.json'),
        source_cache_fingerprint=solver_fingerprint(old,old_model),new_fingerprint=fingerprint,
        session_fingerprint=session_fingerprint,model_restart_required=restart,
        SDK_inspection='NOT_RUN',SDK_started=False,GPU_started=False,
        calculation_allowed_with_existing_session=not restart,READY=False,apply_allowed=False,
        next_SDK_entry='Explicit allocation -> start_solver(new_request,new_model,new_manifest); new geometry inspection before optimizer; repin actual cache/job and new session',
        native_execution_allowed=False,hardware_execution_allowed=False)
    save(output/'model_preparation.json',result)
    return result


def preflight_config(config):
    """Inspect available real files and dependencies; never starts a worker."""
    allocation=pinned_json(config['allocation'])
    cache=dict(model=Path(config['cache_model']),request=Path(config['cache_request']))
    request,manifest=read_cumotion_model(cache['model'],cache['request'])
    result=dict(status='PENDING_ACTUAL_LIVE_OWNER_JOB_AND_ALLOCATION',GPU_owner=allocation['gpu_owner'],
        concurrent_allocation_present=allocation.get('concurrent_cumotion',{}).get('allowed') is True,
        cache_manifest=ref(cache['model']/'CUMOTION_MODEL_MANIFEST.json'),cache_request=ref(cache['request']),
        cache_fingerprint=solver_fingerprint(request,cache['model']),cache_files={n:ref(cache['model']/n) for n in manifest['files']},
        owner_pointer_exists=Path(config['owner_pointer']).is_file(),job_pointer_exists=Path(config['job_pointer']).is_file(),
        SDK_started=False,GPU_started=False,native_execution_allowed=False,hardware_execution_allowed=False)
    if result['owner_pointer_exists'] and result['job_pointer_exists']:
        job=pinned_json(json.loads(Path(config['job_pointer']).read_text())['job'])
        result['job_admission']=admit_online_job(job,cache)
        packet=read_owner_publication(config['owner_pointer'],job['identity'])
        previous=pinned_json(job['previous_cursor']) if job.get('previous_cursor') else None
        envelope=prepare_online_request(Path(job['base_request']['path']),packet,job['limits'],Path(config['preflight_output']),previous)
        prepared=verify_input_anchor(Path(config['preflight_output'])/'TRANSPORT.request.yaml',job['limits'])
        if solver_fingerprint(prepared,cache['model'])!=result['cache_fingerprint']:
            selection=prepare_online_model(cache,Path(config['preflight_output'])/'TRANSPORT.request.yaml',
                Path(config['preflight_output'])/'next_cumotion_model')
            result.update(status=selection['status'],model_preparation=selection)
            return result
        result.update(status='ACTUAL_INPUT_PREPARED_CPU_ONLY_SDK_AND_APPLY_PENDING',prepared_request=ref(Path(config['preflight_output'])/'TRANSPORT.request.yaml'),
            calculated_context_digest=envelope['envelope_digest'])
    return result


def select_immutable_continuation(selection_ref,context_ref=None,job_ref=None,*,now_s=None,
                                  session_fingerprint=None,expected_identity=None):
    """CPU selection of a frozen calculated snapshot, never a fresh request."""
    from dynamic_cumotion_inputs import verify_seal,number
    selection=pinned_json(selection_ref)
    for item in [selection['request'],selection['model_manifest'],*selection['model_files'].values(),
                 selection['source_cache_request'],selection['source_cache_manifest']]:
        if ref(item['path'])!=item:raise ValueError('CONTINUATION_SOURCE_PIN_CHANGED')
    model=Path(selection['model_manifest']['path']).parent;request_path=Path(selection['request']['path'])
    request,manifest=read_cumotion_model(model,request_path)
    fingerprint=solver_fingerprint(request,model)
    if fingerprint!=selection['new_fingerprint']:raise ValueError('CONTINUATION_MODEL_FINGERPRINT_CHANGED')
    result=dict(scope='IMMUTABLE_CALCULATION_SNAPSHOT_CONTINUATION_NOT_FRESH',
        selection=selection_ref,request=selection['request'],model_manifest=selection['model_manifest'],
        fingerprint=fingerprint,SDK_inspection='NOT_RUN',SDK_started=False,READY=False,apply_allowed=False)
    missing=[name for name,value in [('original_calculated_context',context_ref),('original_selected_job',job_ref)] if value is None]
    if missing:return dict(result,status='WAIT_MISSING_ORIGINAL_CONTINUATION_INPUTS',missing=missing)
    context=pinned_json(context_ref);job=pinned_json(job_ref)
    if context.get('solver_parameters')!=job.get('solver_parameters'):
        raise ValueError('CONTINUATION_SOLVER_PARAMETER_BINDING_CHANGED')
    selected_optimizer_parameters(job.get('solver_parameters'))
    if (('selected_job' in context and context['selected_job']!=job_ref) or
            job.get('D_input_approval') is not None and context.get('selected_job')!=job_ref):
        raise ValueError('CONTINUATION_EXACT_NATIVE_SELECTED_JOB_CONTEXT_REQUIRED')
    envelope=pinned_json(context['envelope']);inputs=pinned_json(context['obstacles']);verify_seal(envelope,'envelope_digest')
    if (context['schema']!='live-cumotion-calculated-context/0.1' or context['identity']!=job['identity'] or
            envelope['online_validity']['scope']!=LIVE_SCOPE or
            envelope['online_validity']['identity']!=job['identity'] or
            any(type(context['identity'][k]) is not type(job['identity'][k]) for k in IDENTITY)):
        raise ValueError('CONTINUATION_JOB_LIFECYCLE_CHANGED')
    if expected_identity is not None and (expected_identity!=job['identity'] or
            any(type(expected_identity[k]) is not type(job['identity'][k]) for k in IDENTITY)):
        raise ValueError('CONTINUATION_CURRENT_LIFECYCLE_CHANGED')
    if not computational_geometry(job['limits']):raise ValueError('CONTINUATION_REQUIRES_COMPUTATIONAL_ONLY_JOB')
    for key in ('base_request','cache_request','cache_model_manifest','fcl_binary','fcl_library'):
        if ref(job[key]['path'])!=job[key]:raise ValueError('CONTINUATION_ORIGINAL_JOB_PIN_CHANGED:'+key)
    for item in job['cache_files'].values():
        if ref(item['path'])!=item:raise ValueError('CONTINUATION_ORIGINAL_CACHE_PIN_CHANGED')
    old_model=Path(job['cache_model_manifest']['path']).parent
    if (job['cache_request']==selection['request'] and
            job['cache_model_manifest']==selection['model_manifest']):
        # Exact same pinned request/model already verified above in this call.
        old_request,old_manifest=request,manifest
        old_fingerprint=fingerprint
    else:
        old_request,old_manifest=read_cumotion_model(old_model,Path(job['cache_request']['path']))
        old_fingerprint=solver_fingerprint(old_request,old_model)
    if (old_fingerprint!=job['cache_fingerprint'] or old_fingerprint!=selection['source_cache_fingerprint'] or
            set(job['cache_files'])!=set(old_manifest['files'])):
        raise ValueError('CONTINUATION_ORIGINAL_CACHE_IDENTITY_CHANGED')
    if (selection['source_cache_request']!=job['cache_request'] or selection['source_cache_manifest']!=job['cache_model_manifest'] or
            inputs['limits']!=job['limits'] or envelope['thresholds_digest']!=digest(job['limits']) or
            inputs['base_request_sha256']!=job['base_request']['sha256'] or
            Path(inputs['base_request_path']).resolve()!=Path(job['base_request']['path']).resolve()):
        raise ValueError('CONTINUATION_SELECTED_JOB_LIMITS_OR_ANCHOR_CHANGED')
    if (envelope['request_sha256']!=selection['request']['sha256'] or
            envelope['inputs_sha256']!=context['obstacles']['sha256'] or
            envelope['binding']!={k:request[k] for k in BINDING}):
        raise ValueError('CONTINUATION_REQUEST_ENVELOPE_CHANGED')
    base=load_model_yaml(Path(job['base_request']['path']).read_text())
    if any(request[key]!=base[key] for key in ('a_context','reservation_binding','goal','model_bundle','motion_input_digest')):
        raise ValueError('CONTINUATION_A_RESERVATION_MODEL_OR_TARGET_CHANGED')
    if session_fingerprint is not None and session_fingerprint!=fingerprint:
        raise ValueError('CONTINUATION_NEW_SESSION_FINGERPRINT_REQUIRED')
    if now_s is not None:
        number(now_s)
        if not envelope['state_stamp_s']<=now_s<=envelope['online_validity']['valid_until_s']:
            raise ValueError('CONTINUATION_CALCULATED_DEPTH_EXPIRED_OR_FUTURE')
    result.update(status='WAIT_ACTUAL_CURRENT_OWNER_AND_AUTHORIZED_NEW_SESSION',job=job_ref,
        calculated_context=context_ref,envelope=context['envelope'],inputs=context['obstacles'],
        motion_request=ref(request_path.parent/'motion.request.json'),motion_result=ref(request_path.parent/'motion.result.json'),
        current_clock_checked=now_s is not None,session_fingerprint_checked=session_fingerprint is not None)
    if job.get('solver_parameters') is not None:result['solver_parameters']=job['solver_parameters']
    return result


def pending_current_geometry(job,request_path,report_path,candidate,suffix,whole,current,events,context_pointer,output):
    """Preserve computed artifacts without producing READY or an apply review."""
    if (whole['success'] is not True or whole['FCL']['success'] is not True or
            candidate['suffix_digest']!=digest(suffix) or
            whole['trajectory_digest']!=digest(candidate['trajectory'])):
        raise ValueError('ORIGINAL_CALCULATION_WHOLE_CURVE_PROOF_REQUIRED')
    artifacts={}
    for key,value in dict(candidate=candidate,suffix=suffix,whole_curve_receipt=whole,
            transition_source=current,context_reviews=events).items():
        path=Path(output)/(key+'.json');save(path,value);artifacts[key]=ref(path)
    artifacts.update(request=ref(request_path),suffix_report=ref(report_path),
        motion_request=ref(Path(request_path).parent/'motion.request.json'))
    index=dict(schema='live-resume-worker-publication/0.1',status='PENDING',
        phase='PENDING_CURRENT_GEOMETRY_PROOF_REQUIRED',identity=job['identity'],artifacts=artifacts,
        calculated_context=ref(context_pointer),current_geometry_proof_required=True,
        original_geometry_FCL_only=True,READY=False,apply_allowed=False,
        missing=['Actual same-source fullgeometry whole-command proof','D latest source/clock/STOP/Depth final review'],
        native_execution_allowed=False,hardware_execution_allowed=False,actual_native_send_called=False)
    save(Path(output)/'index.json',index)
    return index


def run_online_job(job,cache,session,owner_provider,output,*,job_ref=None,continuation_ref=None):
    """One fresh request/solve/FCL/connection. Never sends a native command."""
    import xml.etree.ElementTree as ET
    require_legacy_engine(job)
    begin=time.monotonic();output=Path(output);output.mkdir(parents=True,exist_ok=False)
    continued=pinned_json(continuation_ref) if continuation_ref is not None else None
    admission=(dict(scope='ORIGINAL_SELECTED_JOB_WITH_EXPLICIT_NEW_MODEL_CONTINUATION') if continued else
        admit_online_job(job,cache,session_fingerprint=session['fingerprint']))
    first=deepcopy(owner_provider());limits=job['limits'];events=[]
    owner=pinned_json(first['state']['owner_evidence']);owner=owner.get('owner_context',owner)
    if {k:owner[k] for k in IDENTITY}!=job['identity']:raise ValueError('JOB_FIRST_OWNER_IDENTITY_CHANGED')
    base_path=Path(job['base_request']['path'])
    if file_hash(base_path)!=job['base_request']['sha256']:raise ValueError('JOB_A_ANCHOR_CHANGED')
    if continued:
        if continued['job']!=job_ref or pinned_json(job_ref)!=job:raise ValueError('CONTINUATION_DIFFERENT_SELECTED_JOB')
        selected=select_immutable_continuation(continued['selection'],continued['calculated_context'],job_ref,
            now_s=owner['now_s'],session_fingerprint=session['fingerprint'],expected_identity={k:owner[k] for k in IDENTITY})
        if any(continued[key]!=selected[key] for key in
                ('request','model_manifest','fingerprint','motion_request','motion_result','envelope','inputs')):
            raise ValueError('CONTINUATION_FROZEN_INPUT_PIN_CHANGED')
        if (selected['fingerprint']!=session['fingerprint'] or
                Path(cache['model']).resolve()!=Path(selected['model_manifest']['path']).parent.resolve() or
                Path(cache['request']).resolve()!=Path(selected['request']['path']).resolve()):
            raise ValueError('CONTINUATION_NOT_STARTED_NEW_MODEL')
        if not (session.get('geometry_repreparation_inspection') or {}).get('geometric_start_valid'):
            raise ValueError('CONTINUATION_NEW_MODEL_SDK_INSPECTION_NOT_RUN')
        envelope=pinned_json(selected['envelope']);request_path=Path(selected['request']['path'])
        context_pointer=Path(selected['calculated_context']['path']);inputs_path=Path(selected['inputs']['path'])
    else:
        previous=pinned_json(job['previous_cursor']) if job.get('previous_cursor') else None
        envelope=prepare_online_request(base_path,first,limits,output/'common_A',previous)
        request_path=output/'common_A/TRANSPORT.request.yaml';context_pointer=output/'calculated_context.pointer.json'
        inputs_path=output/'common_A/dynamic_inputs.json'
    input_wall=time.monotonic()-begin
    # Provider must retain this calculated scene while publishing fresh raw
    # owner/Depth. It is not allowed to rewrite envelope provenance per frame.
    if not continued:
        publish(context_pointer,dict(schema='live-cumotion-calculated-context/0.1',
            identity=job['identity'],envelope=ref(output/'common_A/dynamic_input.envelope.json'),obstacles=ref(inputs_path)))
    def latest():
        packet=owner_provider()
        # Worker retains immutable calculated context, with explicit pins.
        # Everything current (state/control/desired/latest bound) stays raw.
        packet=deepcopy(packet)
        if 'envelope' in packet and packet['envelope']!=envelope:
            raise ValueError('PUBLISHED_CALCULATED_CONTEXT_CHANGED')
        packet['envelope']=envelope
        packet['obstacles']=json.loads(inputs_path.read_text())['obstacles']
        return packet
    base=verify_input_anchor(base_path,limits)
    check=live_context_checker(base,envelope,limits,latest)
    def record(phase):
        value=check(phase);events.append(value);return value
    record('MODEL_PREPARE_START')
    model=Path(cache['model']) if continued else output/'cumotion_model';prepare_begin=time.monotonic()
    preparation=({'model_restart_required':False} if continued else
        prepare_online_model(cache,request_path,model,session_fingerprint=session['fingerprint']))
    model_wall=time.monotonic()-prepare_begin
    record('MODEL_PREPARE_FINISHED')
    if preparation['model_restart_required']:
        continuation=(select_immutable_continuation(ref(model/'model_preparation.json'),ref(context_pointer),job_ref)
            if computational_geometry(limits) else dict(status='WAIT_ORIGINAL_COMPUTATIONAL_ONLY_JOB_REQUIRED',
                missing=['Original job did not select computational-only continuation; do not change frozen limits']))
        save(output/'continuation.json',continuation)
        # PENDING is already understood by D's reader. No READY trajectory,
        # in-place session mutation, automatic GPU restart or implicit retry.
        index=dict(schema='live-resume-worker-publication/0.1',status='PENDING',
            phase='WAIT_EXPLICIT_SDK_INSPECTION_AND_RESTART',identity=job['identity'],
            model_preparation=ref(model/'model_preparation.json'),model_restart_required=True,
            calculated_context=ref(context_pointer),job_admission=admission,
            continuation=ref(output/'continuation.json'),
            READY=False,apply_allowed=False,new_model_SDK_started=False,new_model_SDK_inspection='NOT_RUN',
            native_execution_allowed=False,hardware_execution_allowed=False,actual_native_send_called=False)
        save(output/'index.json',index)
        return index
    report_path=run_live_calculation(request_path,model,Path(job['fcl_binary']['path']),output/'calculation',
        expected_fcl_sha256=job['fcl_binary']['sha256'],owner_provider=latest,solver_session=session,context_check=record,selected_job=job_ref)
    report=json.loads(report_path.read_text());request=load_model_yaml(request_path.read_text())
    result=yaml.safe_load(Path(report['artifacts']['fcl_result']['path']).read_text());suffix=result['planned_trajectory']
    current=record('TRANSITION_PREPARE');desired=current['desired']
    if desired is None:raise ValueError('ACTUAL_CURRENT_CONTROLLER_DESIRED_PVT_REQUIRED')
    robot=ET.fromstring(request['model_bundle']['robot_description'])
    bounds=[robot.find(f"joint[@name='{name}']/limit") for name in JOINTS]
    lower=[float(x.get('lower')) for x in bounds];upper=[float(x.get('upper')) for x in bounds]
    candidate=transition_candidate(suffix,desired,current['observed'],duration_s=job['transition_duration_s'],
        limits=job['review_args']['tracking_limits'],lower=lower,upper=upper)
    if job['review_args']['lower']!=lower or job['review_args']['upper']!=upper:
        raise ValueError('OWNER_REVIEW_BOUNDS_DIFFER_FROM_ORIGINAL_MODEL')
    whole_begin=time.monotonic()
    whole=check_transition_fcl(candidate,request,result,Path(job['fcl_library']['path']),job['fcl_library']['sha256'],context_check=record)
    if whole['success'] is not True:raise ValueError('WHOLE_CONNECTION_SUFFIX_FCL_REJECTED')
    if computational_geometry(limits):
        index=pending_current_geometry(job,request_path,report_path,candidate,suffix,whole,current,
            events,context_pointer,output)
        if job_ref is not None:index['original_selected_job']=job_ref
        if continuation_ref is not None:index['immutable_continuation']=continuation_ref
        save(output/'index.json',index)
        return index
    whole_wall=time.monotonic()-whole_begin;review_begin=time.monotonic()
    reviewed=review_transition(candidate,whole,request,record,expected_library_sha256=job['fcl_library']['sha256'])
    review_wall=time.monotonic()-review_begin
    artifacts={}
    for key,value in dict(candidate=candidate,suffix=suffix,whole_curve_receipt=whole,wire_trajectory=reviewed['trajectory'],
                          context_reviews=events,transition_source=current).items():
        p=output/(key+'.json');save(p,value);artifacts[key]=ref(p)
    artifacts.update(request=ref(request_path),suffix_report=ref(report_path),motion_request=ref(request_path.parent/'motion.request.json'))
    pins={k:v['sha256'] for k,v in report['artifacts'].items()};pins.update(receipt=file_hash(report_path),fcl_binary=job['fcl_binary']['sha256'])
    review_args=job['review_args']
    if review_args['expected_fcl_sha256']!=job['fcl_library']['sha256']:raise ValueError('OWNER_WHOLE_FCL_PIN_CHANGED')
    index=dict(schema='live-resume-worker-publication/0.1',status='READY',identity=job['identity'],
        artifacts={k:v for k,v in artifacts.items() if k not in ('wire_trajectory','context_reviews')},
        suffix_receipt_pins=pins,review_args=review_args,additional_artifacts=artifacts,
        calculated_context=ref(context_pointer),job_admission=admission,
        cache_fingerprint=session['fingerprint'],geometry_reuse='FULL_SOLID_GEOMETRY_ONLY_NO_OLD_PATH_OR_WORLD_SUCCESS',
        latency=dict(initial_input_preparation_wall_s=input_wall,modelprepare_wall_s=model_wall,SDK_wall_s=report['solver']['solve_wall_s'],
            retime_export_wall_s=report['solver']['retime_export_wall_s'],suffix_FCL_wall_s=report['final_fcl_wall_s'],
            whole_connection_FCL_wall_s=whole_wall,final_review_wall_s=review_wall,
            total_wall_s=time.monotonic()-begin,
            calculation_SIM_s=events[-1]['source_now_s']-events[0]['source_now_s'],
            stage_SIM_s={label:next(e['source_now_s'] for e in events if e['phase']==end)-next(e['source_now_s'] for e in events if e['phase']==start)
                for label,start,end in [('modelprepare','MODEL_PREPARE_START','MODEL_PREPARE_FINISHED'),
                    ('SDK','SDK_PLAN_START','SDK_PLAN_FINISHED'),('retime_export','SDK_PLAN_FINISHED','RETIME_EXPORT_FINISHED'),
                    ('suffix_FCL','FINAL_FCL_START','FINAL_FCL_FINISHED'),
                    ('whole_FCL','TRANSITION_FCL_START','TRANSITION_FCL_FINISHED'),('final_review','TRANSITION_FCL_FINISHED','D_APPLY_REVIEW')]},
            boundaries=[dict(phase=e['phase'],source_now_s=e['source_now_s'],wall_monotonic_s=e['wall_monotonic_s']) for e in events]),
        native_execution_allowed=False,hardware_execution_allowed=False,actual_native_send_called=False)
    save(output/'index.json',index)
    return index


def serve(config):
    """Explicit start after a new concurrent allocation; one owner/job at a time."""
    require_legacy_engine(config)
    if not sys.flags.isolated or sys.prefix==sys.base_prefix:raise ValueError('ISOLATED_VENV_REQUIRED')
    allocation=pinned_json(config['allocation']);grant=allocation.get('concurrent_cumotion')
    if not isinstance(grant,dict):raise ValueError('NEW_EXPLICIT_CONCURRENT_ISAAC_ALLOCATION_REQUIRED')
    if (grant['allowed'] is not True or grant['isaac_must_remain_running'] is not True or
            grant['owner_pointer']!=config['owner_pointer'] or grant['maximum_jobs']!=config['maximum_jobs']):
        raise ValueError('NEW_EXPLICIT_CONCURRENT_ISAAC_ALLOCATION_REQUIRED')
    # This read-only query and SDK creation occur only after --start/allocation.
    import subprocess
    free=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())
    if free<grant['minimum_free_before_start_mib']:raise ValueError('CONCURRENT_GPU_RESERVATION_UNAVAILABLE_KEEP_ISAAC_RUNNING')
    if type(config['maximum_jobs']) is not int or config['maximum_jobs']<1 or config['idle_timeout_wall_s']<=0:
        raise ValueError('BOUNDED_WORKER_JOB_AND_IDLE_LIMIT_REQUIRED')
    root=Path(config['output']);root.mkdir(parents=True,exist_ok=False)
    # Read-only sampling, in this worker only; exceeding the allocation rejects
    # publication and exits. Never kills or stops the simulator/other processes.
    import threading
    from benchmark_cumotion import sample_memory
    stop_sampling=threading.Event();samples=[]
    sampler=threading.Thread(target=sample_memory,args=(stop_sampling,samples),daemon=True);sampler.start()
    try:
        return serve_allocated(config,grant,allocation,root,samples)
    finally:
        stop_sampling.set();sampler.join(timeout=4)
        save(root/'worker_memory_samples.json',dict(samples=samples,sampling_interval_s=.2,
            sampled_peak_is_lower_bound=True,reservation_mib=grant['max_worker_vram_mib']))


def verify_allocated_isaac_owner(grant):
    """Read-only allocation guard. Never stops or restarts another process."""
    pid=grant['isaac_owner_pid']
    if type(pid) is not int or pid<=0 or str(grant['isaac_ros_domain_id'])!='194':
        raise ValueError('EXPLICIT_SINGLE_SIM194_OWNER_ALLOCATION_REQUIRED')
    process=Path('/proc')/str(pid)
    argv=[p.decode() for p in (process/'cmdline').read_bytes().split(b'\0') if p]
    expected_run=str(Path(grant['owner_pointer']).resolve().parent.parent)
    start=(process/'stat').read_text().rsplit(')',1)[1].split()[19]
    env=dict(p.split(b'=',1) for p in (process/'environ').read_bytes().split(b'\0') if b'=' in p)
    if (not argv or '/isaacsim/' not in argv[0] or expected_run not in argv or
            not any(p.endswith('/run_fixed_depth_native.py') for p in argv) or
            start!=str(grant['isaac_owner_start_ticks']) or env.get(b'ROS_DOMAIN_ID')!=b'194'):
        raise ValueError('ALLOCATED_ISAAC_OWNER_COMMAND_START_OR_DOMAIN_CHANGED')
    found=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:exe=(path/'cmdline').read_bytes().split(b'\0',1)[0].decode()
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
        if '/isaacsim/' in exe and Path(exe).name.startswith(('python','kit')):found.append(int(path.name))
    if sorted(found)!=[pid]:raise ValueError('EXPECTED_SINGLE_ALLOCATED_ISAAC_PROCESS')
    return dict(pid=pid,start_ticks=start,domain=194,command=argv)


def serve_allocated(config,grant,allocation,root,samples):
    if (not isinstance(grant,dict) or pinned_json(config['allocation'])!=allocation or allocation.get('concurrent_cumotion')!=grant or
            grant.get('allowed') is not True):raise ValueError('EXPLICIT_CURRENT_ALLOCATION_REQUIRED_BEFORE_SDK')
    verify_allocated_isaac_owner(grant)
    cache=dict(model=Path(config['cache_model']),request=Path(config['cache_request']))
    continuation_ref=config.get('continuation')
    parameter_ref=None
    if config.get('solver_parameters') is not None and not continuation_ref:
        raise ValueError('EXPLICIT_PARAMETERS_REQUIRE_FRESH_NATIVE_SELECTED_CONTINUATION')
    if continuation_ref:
        continued=pinned_json(continuation_ref)
        if not all(key in continued for key in ('selection','calculated_context','job')):
            raise ValueError('WAIT_MISSING_ORIGINAL_CONTINUATION_INPUTS')
        jobref=continued['job'];job=pinned_json(jobref)
        require_legacy_engine(job)
        parameter_ref=bind_solver_parameters(config,grant,job,pinned_json(continued['calculated_context']))
        if json.loads(Path(config['job_pointer']).read_text())['job']!=jobref:
            raise ValueError('CONTINUATION_CURRENT_SELECTED_JOB_CHANGED')
        def provider():
            verify_allocated_isaac_owner(grant)
            return read_owner_publication(config['owner_pointer'],job['identity'])
        first=provider();owner=pinned_json(first['state']['owner_evidence']);owner=owner.get('owner_context',owner)
        selected=select_immutable_continuation(continued['selection'],continued['calculated_context'],jobref,
            now_s=owner['now_s'],expected_identity={k:owner[k] for k in IDENTITY})
        if any(continued[key]!=selected[key] for key in
                ('request','model_manifest','fingerprint','motion_request','motion_result','envelope','inputs')):
            raise ValueError('CONTINUATION_FROZEN_INPUT_PIN_CHANGED')
        if (Path(cache['model']).resolve()!=Path(selected['model_manifest']['path']).parent.resolve() or
                Path(cache['request']).resolve()!=Path(selected['request']['path']).resolve()):
            raise ValueError('CONTINUATION_CONFIG_NOT_NEW_PREPARED_MODEL')
        envelope=pinned_json(selected['envelope']);inputs=pinned_json(selected['inputs'])
        def before_start():
            packet=deepcopy(provider())
            if 'envelope' in packet and packet['envelope']!=envelope:raise ValueError('PUBLISHED_CALCULATED_CONTEXT_CHANGED')
            packet['envelope']=envelope;packet['obstacles']=inputs['obstacles'];return packet
        base=verify_input_anchor(Path(job['base_request']['path']),job['limits'])
        live_context_checker(base,envelope,job['limits'],before_start)('CONTINUATION_BEFORE_EXPLICIT_SDK_START')
    request,manifest=read_cumotion_model(cache['model'],cache['request'])
    verify_allocated_isaac_owner(grant)
    start=time.monotonic();session=start_solver(request,cache['model'],manifest,solver_parameters=parameter_ref)
    save(root/'worker_started.json',dict(SDK_start_wall_s=time.monotonic()-start,pid=os.getpid(),cache_fingerprint=session['fingerprint'],
        allocation=config['allocation'],solver_parameters=parameter_ref,
        solver_session_fingerprint=session['solver_session_fingerprint'],
        explicit_optimizer_parameters=session['explicit_optimizer_parameters'],
        optimizer_parameter_acceptance=session['optimizer_parameter_acceptance'],
        native_execution_allowed=False,hardware_execution_allowed=False))
    if continuation_ref:
        if pinned_json(config['allocation'])!=allocation:raise ValueError('CONCURRENT_ALLOCATION_CHANGED')
        index=run_online_job(job,cache,session,provider,root/'continued_job_1',job_ref=jobref,continuation_ref=continuation_ref)
        if max((s.get('process_vram_mib',0) for s in samples),default=0)>grant['max_worker_vram_mib']:
            raise ValueError('WORKER_GPU_RESERVATION_EXCEEDED_NO_RESULT_APPLY')
        publish(config['result_pointer'],index)
        save(root/'worker_ended.json',dict(jobs_seen=1,immutable_continuation=continuation_ref,
            native_execution_allowed=False,hardware_execution_allowed=False))
        return
    seen=set();idle=time.monotonic()
    while len(seen)<config['maximum_jobs'] and not Path(config['stop_file']).exists():
        if time.monotonic()-idle>config['idle_timeout_wall_s']:break
        pointer=Path(config['job_pointer'])
        if not pointer.is_file():time.sleep(.05);continue
        publication=json.loads(pointer.read_text())
        if publication['schema']!='live-cumotion-job-publication/0.1':raise ValueError('EXPLICIT_JOB_PUBLICATION_REQUIRED')
        jobref=publication['job']
        if jobref['sha256'] in seen:time.sleep(.05);continue
        seen.add(jobref['sha256']);idle=time.monotonic();job=pinned_json(jobref)
        def provider():
            verify_allocated_isaac_owner(grant)
            return read_owner_publication(config['owner_pointer'],job['identity'])
        publish(config['result_pointer'],dict(schema='live-resume-worker-publication/0.1',identity=job['identity'],status='PENDING'))
        try:
            if pinned_json(config['allocation'])!=allocation:raise ValueError('CONCURRENT_ALLOCATION_CHANGED')
            index=run_online_job(job,cache,session,provider,root/('job_'+str(len(seen))),job_ref=jobref)
            if max((s.get('process_vram_mib',0) for s in samples),default=0)>grant['max_worker_vram_mib']:
                raise ValueError('WORKER_GPU_RESERVATION_EXCEEDED_NO_RESULT_APPLY')
            publish(config['result_pointer'],index)
            if index.get('model_restart_required'):break
        except Exception as error:
            publish(config['result_pointer'],dict(schema='live-resume-worker-publication/0.1',identity=job['identity'],status='FAILED',
                reason=str(error),native_execution_allowed=False,hardware_execution_allowed=False))
            # A failed world mutation/SDK solve must not silently reuse state.
            break
    save(root/'worker_ended.json',dict(jobs_seen=len(seen),pid=os.getpid(),native_execution_allowed=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--start',action='store_true');mode.add_argument('--preflight',action='store_true')
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    config=json.loads(args.config.read_text())
    if args.preflight:
        result=preflight_config(config)
        if args.report:save(args.report,result)
        print(json.dumps(result,ensure_ascii=False));return
    serve(config)


if __name__=='__main__':main()
