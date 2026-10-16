"""One CPU-only request to the running same-D prepared-input admission IPC.

Never starts SDK/FCL or writes a native job/result. No request retry or fallback.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json,time,uuid
from bounded_sim_evidence import pinned_json
from online_cumotion_worker import (ref,publish,read_owner_publication,select_immutable_continuation)
from calculate_cumotion import selected_optimizer_parameters
from dynamic_cumotion_inputs import verify_input_anchor
from live_cumotion_boundary import live_context_checker


def write_new(path,value):
    with Path(path).open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
    return ref(path)


def check_response(response,request_ref,request):
    if (response['schema']!='same-d-prepared-admission-response/0.1' or response['request']!=request_ref or
            response['attempt_id']!=request['attempt_id'] or any(response[key] is not False for key in
            ('READY','apply_allowed','SDK_started','native_send_called'))):
        raise ValueError('ADMISSION_RESPONSE_NOT_EXACT_ATTEMPT_OR_SCOPE')
    if response['status']!='NATIVE_SELECTED_INPUT_BEFORE_SDK_NOT_READY_OR_APPLY':
        raise ValueError('D_ADMISSION_REJECTED:'+response.get('reason',response['status']))
    selected_ref=response['selected_native_job'];selected=pinned_json(selected_ref);private=pinned_json(request['prepared_job'])
    if any(key not in selected or selected[key]!=value for key,value in private.items()):
        raise ValueError('NATIVE_SELECTION_CHANGED_PRIVATE_INPUTS')
    expected={'D_input_approval','stop_observation_review','observation_criteria','prepared_input_admission'}
    if set(selected)-set(private)!=expected:raise ValueError('NATIVE_SELECTION_UNEXPECTED_D_FIELDS')
    approval=pinned_json(selected['D_input_approval']);receipt=selected['prepared_input_admission']
    if (approval['original_prepared_job']!=request['prepared_job'] or approval['before_SDK']!=request['before_SDK_phase'] or
            approval['identity']!=request['identity'] or approval['READY'] is not False or approval['apply_allowed'] is not False):
        raise ValueError('NATIVE_D_APPROVAL_NOT_ORIGINAL_REQUEST')
    source_keys={'base_request','cache_request','cache_model_manifest','source_owner','source_packet','prepared_inputs','calculated_envelope'}
    if (receipt['scope']!='PREPARED_INPUT_ADMISSION_NOT_SDK_OR_NATIVE_APPROVAL' or
            receipt['identity']!=request['identity'] or set(receipt['source_refs'])!=source_keys or
            any(receipt['source_refs'][k]!=private[k] for k in source_keys) or
            receipt['current_geometry_proof_required'] is not True or receipt['encoded_current_proof_required'] is not True or
            receipt['READY'] is not False or receipt['apply_allowed'] is not False):
        raise ValueError('NATIVE_PREPARED_ADMISSION_RECEIPT_CHANGED')
    return selected_ref,selected


def check_engine_binding(job,context):
    from cumotion_cspace_engine import ENGINE as CS_ENGINE,check_spec
    if job.get('planning_engine')==CS_ENGINE:
        if context.get('planning_engine')!=CS_ENGINE or job.get('cspace_engine_spec')!=context.get('cspace_engine_spec'):
            raise ValueError('CSPACE_ENGINE_OR_SPEC_BINDING_CHANGED')
        check_spec(job['cspace_engine_spec']);return CS_ENGINE
    if job.get('planning_engine')!=context.get('planning_engine') or job.get('planning_engine') not in (None,'CUMOTION_SDK_SPLINE_FCL_CALCULATION_ONLY'):
        raise ValueError('UNKNOWN_OR_CHANGED_PLANNING_ENGINE')
    if job.get('cspace_engine_spec') is not None or context.get('cspace_engine_spec') is not None:
        raise ValueError('CSPACE_SPEC_WITHOUT_EXPLICIT_CSPACE_ENGINE')
    selected_optimizer_parameters(job.get('solver_parameters'));return None



def cspace_entry_config(run,selected,selected_ref,native_context_ref,response_ref,output):
    """Build a non-startable entry only after exact native selection validation.

    selected_inputs rechecks D response, source pins and fresh endpoint FK.
    Allocation remains absent: producing config never permits SDK execution.
    """
    from cumotion_cspace_engine import ENGINE,selected_inputs
    config=dict(schema='cumotion-explicit-cspace-engine-entry/0.1',engine=ENGINE,
        engine_spec=selected['cspace_engine_spec'],selected_job=selected_ref,
        native_context=native_context_ref,D_response=response_ref,allocation=None,
        owner_pointer=str(Path(run)/'live_ipc/owner.pointer.json'),
        output=str(Path(output)/'CS_ENGINE_NOT_STARTED'),READY=False,apply_allowed=False)
    selected_inputs(config)
    return config


def request_admission(run,job_ref,context_ref,output):
    run=Path(run).resolve(strict=True);output=Path(output).resolve();output.mkdir(exist_ok=False)
    endpoint=run/'live_ipc/prepared_admission'
    if not (run/'canonical_sensor.pointer.json').is_file() or not (run/'live_ipc/owner.pointer.json').is_file():
        raise ValueError('WAIT_ACTUAL_CANONICAL_SENSOR_AND_OWNER_POINTERS:'+str(run))
    if not endpoint.is_dir():raise ValueError('WAIT_PREPARED_ADMISSION_ENDPOINT_NOT_ACTIVE:'+str(endpoint))
    job=pinned_json(job_ref);context=pinned_json(context_ref);envelope=pinned_json(context['envelope']);inputs=pinned_json(context['obstacles'])
    if context.get('solver_parameters')!=job.get('solver_parameters'):
        raise ValueError('PREPARED_ADMISSION_SOLVER_PARAMETER_BINDING_CHANGED')
    selected_engine=check_engine_binding(job,context)
    base=verify_input_anchor(Path(job['base_request']['path']),job['limits'])
    def current():
        packet=deepcopy(read_owner_publication(run/'live_ipc/owner.pointer.json',job['identity']))
        if 'envelope' in packet and packet['envelope']!=envelope:raise ValueError('CURRENT_ALREADY_BOUND_TO_OTHER_CONTEXT')
        packet['envelope']=envelope;packet['obstacles']=inputs['obstacles'];return packet
    check=live_context_checker(base,envelope,job['limits'],current)
    before=check('BEFORE_PREPARED_D_ADMISSION_REQUEST')
    # One outstanding request only. Never supersede an unacknowledged attempt.
    pointer=endpoint/'request.pointer.json';sequence=1
    if pointer.exists():
        previous=json.loads(pointer.read_text());old=pinned_json(previous['request'])
        response_pointer=endpoint/'response.pointer.json'
        if not response_pointer.exists() or pinned_json(json.loads(response_pointer.read_text())['response'])['request']!=previous['request']:
            raise ValueError('WAIT_PREVIOUS_ADMISSION_ATTEMPT_UNANSWERED')
        if type(old['sequence']) is not int:raise ValueError('INVALID_PREVIOUS_ADMISSION_SEQUENCE')
        sequence=old['sequence']+1
    phase_ref=write_new(output/'before_SDK_phase.json',dict(scope='NATIVE_PREPARED_CALCULATION_BEFORE_SDK',job=job_ref,SDK_started=False,FCL_started=False,READY=False,apply_allowed=False))
    attempt=uuid.uuid4().hex
    request=dict(schema='same-d-prepared-admission-request/0.1',attempt_id=attempt,sequence=sequence,
        identity=job['identity'],prepared_job=job_ref,before_SDK_phase=phase_ref)
    request_ref=write_new(output/'request.json',request);started=time.monotonic()
    publish(pointer,dict(schema='same-d-prepared-admission-request-pointer/0.1',request=request_ref))
    deadline=envelope['online_validity']['observation_wall_monotonic_s']+envelope['online_validity']['policy']['max_sensor_to_apply_wall_s']
    result=dict(status='WAIT_D_ADMISSION_RESPONSE',request=request_ref,attempt_id=attempt,before=before,selected_native_job=None,
        SDK_started=False,FCL_started=False,READY=False,apply_allowed=False)
    try:
        while time.monotonic()<=deadline:
            rp=endpoint/'response.pointer.json'
            if rp.exists():
                response_pointer=json.loads(rp.read_text())
                if response_pointer['schema']!='same-d-prepared-admission-response-pointer/0.1':raise ValueError('ADMISSION_RESPONSE_POINTER_SCHEMA')
                response=pinned_json(response_pointer['response'])
                if response.get('attempt_id')==attempt:
                    result['response']=response_pointer['response'];result['response_value']=response
                    selected_ref,selected=check_response(response,request_ref,request)
                    if not Path(selected_ref['path']).resolve().is_relative_to(run/'live_ipc/jobs'):
                        raise ValueError('RETURNED_JOB_NOT_NATIVE_RUN_PUBLICATION')
                    native_pointer=json.loads((run/'live_ipc/job.pointer.json').read_text())
                    if native_pointer['schema']!='live-cumotion-job-publication/0.1' or native_pointer['job']!=selected_ref:
                        raise ValueError('RETURNED_NATIVE_JOB_NOT_CURRENT_NATIVE_POINTER')
                    result['selected_native_job']=selected_ref
                    result['after']=check('AFTER_PREPARED_D_ADMISSION_RESPONSE')
                    # Bind the native selected ref explicitly. No job copying or aliasing.
                    native_context=dict(context,selected_job=selected_ref)
                    context_path=run/'live_ipc/calculated_context.pointer.json'
                    if context_path.exists():raise ValueError('NATIVE_CALCULATED_CONTEXT_ALREADY_EXISTS')
                    publish(context_path,native_context);native_context_ref=ref(context_path)
                    if selected_engine is not None:
                        config=cspace_entry_config(run,selected,selected_ref,native_context_ref,response_pointer['response'],output)
                        continuation_ref=None
                    else:
                        private_cont=pinned_json(ref(Path(context_ref['path']).parent/'prepared_cache_continuation.json'))
                        continued=select_immutable_continuation(private_cont['selection'],native_context_ref,selected_ref)
                        continuation_ref=write_new(output/'native_continuation.json',continued)
                        config=dict(allocation=None,cache_request=selected['cache_request']['path'],cache_model=str(Path(selected['cache_model_manifest']['path']).parent),
                            continuation=continuation_ref,owner_pointer=str(run/'live_ipc/owner.pointer.json'),job_pointer=str(run/'live_ipc/job.pointer.json'),
                            maximum_jobs=1,idle_timeout_wall_s=1.,stop_file=str(output/'worker.stop_NOT_CREATED'),output=str(output/'GPU_NOT_STARTED'),
                            result_pointer=str(run/'live_ipc/result.pointer.json'),READY=False,apply_allowed=False)
                        if selected.get('solver_parameters') is not None:config['solver_parameters']=selected['solver_parameters']
                    result.update(status='NATIVE_SELECTED_INPUT_BEFORE_SDK_NOT_READY_OR_APPLY',native_context=native_context_ref,
                        config=write_new(output/'worker.PENDING_ALLOCATION.config.json',config),continuation=continuation_ref)
                    result['final']=check('NATIVE_SELECTION_DOWNSTREAM_CONFIG_FINISHED')
                    break
            time.sleep(.2)
        else:raise ValueError('ADMISSION_RESPONSE_WAIT_EXCEEDED_ORIGINAL_WALL_BUDGET')
    except Exception as error:result.update(status='HOLD_ADMISSION_OR_CURRENT_REVIEW_REJECTED',reason=str(error))
    result.update(response_wait_and_selection_wall_s=time.monotonic()-started,original_deadline_wall_monotonic_s=deadline,
        original_input_age_wall_s=time.monotonic()-envelope['online_validity']['observation_wall_monotonic_s'])
    write_new(output/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--job-ref',type=Path,required=True)
    parser.add_argument('--context-ref',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=request_admission(args.run,ref(args.job_ref),ref(args.context_ref),args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
