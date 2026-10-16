"""Offline worker for a fresh, paused SIM; no native action or robot driver."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmark_cumotion import fcl_run, save
from prepare_cumotion_model import prepare_model, verify_request,static_model_source
from calculate_cumotion import calculate
from cumotion_timing import ENGINE
from prepare_cpu_model import file_hash


def worker_preflight(request_path,*,source_now_s=None,active_control=None,latest_envelope=None):
    request=verify_request(request_path)
    if (request_path.parent/'bounded_sim_admission.json').exists():
        from dynamic_cumotion_inputs import verify_bounded_sim_admission,check_result_context
        if source_now_s is None or active_control is None or latest_envelope is None:
            raise ValueError('CURRENT_SOURCE_TIME_CONTROL_AND_LATEST_ENVELOPE_REQUIRED')
        verify_bounded_sim_admission(request_path,now_s=source_now_s)
        envelope=json.loads((request_path.parent/'dynamic_input.envelope.json').read_text())
        check_result_context(envelope,latest_envelope,active_control,now_s=source_now_s,
            limits=json.loads((request_path.parent/'dynamic_inputs.json').read_text())['limits'])
    static=static_model_source(request_path,request)
    return dict(status='CPU_INPUT_VALIDATED_MODEL_SDK_FCL_PENDING',request_sha256=file_hash(request_path),
        archived_static_source=static,dynamic_input_ready=False,native_execution_allowed=False,
        live_freshness_verified=False,
        bounded_sim_source=(request_path.parent/'bounded_sim_admission.json').exists(),
        model_regeneration_required=True,sdk_result_generated=False,fcl_result_generated=False,
        model_regeneration_scope='NEW_MANIFEST_AND_WORLD_CHECK_GEOMETRY_REUSE_REQUIRES_EXACT_IDENTITY',
        execution_allowed=False,hardware_execution_allowed=False)


def run_live_calculation(request_path,model,binary,output,*,expected_fcl_sha256,owner_provider,timing_profile='nominal',solver_session=None,context_check=None,selected_job=None):
    """Owner callback entry; no CLI clock replay or action/automatic resume."""
    from live_cumotion_boundary import live_context_checker
    from dynamic_cumotion_inputs import verify_input_anchor
    data=json.loads((request_path.parent/'dynamic_inputs.json').read_text())
    envelope=json.loads((request_path.parent/'dynamic_input.envelope.json').read_text())
    if envelope.get('initial_condition_mode')!='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE':
        raise ValueError('EXPLICIT_LIVE_CANDIDATE_CONTRACT_REQUIRED')
    base=verify_input_anchor(Path(data['base_request_path']),data['limits'])
    checker=context_check or live_context_checker(base,envelope,data['limits'],owner_provider)
    return calculate(request_path,model,binary,output,engine=ENGINE,expected_fcl_sha256=expected_fcl_sha256,
        timing_profile=timing_profile,context_check=checker,solver_session=solver_session,selected_job=selected_job)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('request','run'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--fcl-binary',type=Path)
    parser.add_argument('--fcl-sha256')
    parser.add_argument('--validate-input-only',action='store_true')
    parser.add_argument('--source-now-s',type=float)
    parser.add_argument('--active-control',type=Path)
    parser.add_argument('--latest-envelope',type=Path)
    parser.add_argument('--timing-profile',choices=['nominal','servo-margin','servo-soft'],default='nominal')
    args=parser.parse_args()
    control=json.loads(args.active_control.read_text()) if args.active_control else None
    latest=json.loads(args.latest_envelope.read_text()) if args.latest_envelope else None
    report=worker_preflight(args.request,source_now_s=args.source_now_s,active_control=control,latest_envelope=latest)
    if args.validate_input_only:
        args.run.mkdir(parents=True,exist_ok=False)
        save(args.run/'input_preflight.json',report)
        return
    side=args.request.parent/'dynamic_input.envelope.json'
    if side.exists() and json.loads(side.read_text()).get('initial_condition_mode')=='Q_ONLY_CANDIDATE_REQUIRES_PVT_BRIDGE':
        raise ValueError('USE_OWNER_CALLBACK_ENTRYPOINT_FOR_LIVE_CALCULATION')
    if args.fcl_binary is None or args.fcl_sha256 is None:raise ValueError('PINNED_FILE_CHECKER_REQUIRED')
    if file_hash(args.fcl_binary)!=args.fcl_sha256:
        raise ValueError('PINNED_FILE_CHECKER_REQUIRED')
    args.run.mkdir(parents=True,exist_ok=False)
    # Default fixtures stay rejected; only independently replayed bounded-SIM
    # provenance may admit a legacy shape projection before reference/SDK work.
    verify_request(args.request)
    # Independent OMPL reference only refines conservative sphere partitions.
    # No reference waypoint/goal joint vector is fed to the GPU planner.
    entry,_=fcl_run(args.fcl_binary,args.request,args.run,'model_reference')
    save(args.run/'model_reference.summary.json',entry)
    if not entry['plan_success']:
        raise ValueError('FRESH_REFERENCE_REJECTED_NO_GPU_OR_EXECUTION')
    if args.active_control:control=json.loads(args.active_control.read_text())
    if args.latest_envelope:latest=json.loads(args.latest_envelope.read_text())
    worker_preflight(args.request,source_now_s=args.source_now_s,active_control=control,latest_envelope=latest)
    model=args.run/'cumotion_model'
    prepare_model(args.request,model,[5.]*6,
                  [[args.request,args.run/'model_reference.fcl.yaml']],100)
    calculate(args.request,model,args.fcl_binary,args.run/'cumotion_calculation',
              engine=ENGINE,expected_fcl_sha256=args.fcl_sha256,timing_profile=args.timing_profile)


if __name__=='__main__':main()
