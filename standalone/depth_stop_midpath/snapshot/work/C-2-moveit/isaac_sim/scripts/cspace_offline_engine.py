"""Explicit archived calculation entry; never native D selection or approval.

Preflight needs no SDK. --start additionally requires a new exact archive
exclusive archive resource lease; no SIM/D/STOP owner is required.
"""
import argparse,json
from pathlib import Path
from bounded_sim_evidence import pinned_json
from cumotion_cspace_engine import ENGINE,check_spec,qualify_endpoint
from prepare_cumotion_model import read_cumotion_model
from cumotion_pose_engine import ref

SCOPE='ARCHIVED_OFFLINE_CALCULATION'


def archived_inputs(config):
    if config.get('scope')!=SCOPE or config.get('engine')!=ENGINE:raise ValueError('EXPLICIT_ARCHIVED_CSPACE_ENGINE_REQUIRED')
    if any(config.get(k) is not None for k in ('selected_job','native_context','D_response')):
        raise ValueError('ARCHIVE_CANNOT_CLAIM_NATIVE_SELECTION')
    spec=check_spec(config['engine_spec']);job=pinned_json(config['archived_job'])
    path=Path(job['cache_request']['path']);model=Path(job['cache_model_manifest']['path']).parent
    for key in ('cache_request','cache_model_manifest','fcl_binary','fcl_library'):
        if ref(job[key]['path'])!=job[key]:raise ValueError('ARCHIVE_INPUT_CHANGED:'+key)
    for item in job['cache_files'].values():
        if ref(item['path'])!=item:raise ValueError('ARCHIVE_MODEL_FILE_CHANGED')
    request,manifest=read_cumotion_model(model,path)
    if manifest['files']!={name:item['sha256'] for name,item in job['cache_files'].items()}:
        raise ValueError('ARCHIVE_MODEL_MANIFEST_FILES_CHANGED')
    qualify_endpoint(request,spec)
    return spec,job,{},request,manifest,path,model


def preflight(config):
    if config.get('scope')!=SCOPE or config.get('engine')!=ENGINE:raise ValueError('EXPLICIT_ARCHIVED_CSPACE_ENGINE_REQUIRED')
    check_spec(config['engine_spec'])
    missing=[k for k in ('archived_job','allocation','output') if not config.get(k)]
    if not missing:
        spec=check_spec(config['engine_spec'])
        from cumotion_archive_lease import review
        review(config,spec)
        archived_inputs(config)
    return dict(status='WAIT_ARCHIVE_INPUTS_OR_NEW_ALLOCATION' if missing else 'ARCHIVE_CPU_INPUTS_NOT_START_APPROVAL',
        blockers=['WAIT:'+','.join(missing)] if missing else [],SDK_imported=False,SDK_started=False,READY=False,apply_allowed=False)


def run(config):
    ready=preflight(config)
    if ready['blockers']:raise ValueError(';'.join(ready['blockers']))
    from cumotion_archive_lease import review,resources,claim,finish,owned_claim
    spec=check_spec(config['engine_spec'])
    import os,sys
    if not sys.flags.isolated or sys.prefix==sys.base_prefix:raise ValueError('ISOLATED_VENV_REQUIRED_BEFORE_RESOURCE_PROBE')
    if any(os.environ.get(k)!='1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')):
        raise ValueError('ARCHIVE_NUMERICAL_THREAD_ENV_MUST_BE_ONE_BEFORE_PROCESS_START')
    record=claim(config,spec);error=None
    claim_ref=ref(review(config,spec)['claim_path'])
    def preserve(phase):
        g=review(config,spec);owned_claim(config,g)
        if ref(g['claim_path'])!=claim_ref:raise ValueError('ARCHIVE_CLAIM_CHANGED_DURING_RUN')
        return dict(phase=phase,scope='ARCHIVE_RESOURCE_CHECK_NOT_LIVE_STATE',**resources(g,before_start=False))
    from cumotion_pose_engine import _calculate_selected
    try:return _calculate_selected(config,preserve)
    except Exception as exc:
        error=str(exc);raise
    finally:finish(config,record,error)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--start',action='store_true');p.add_argument('--confirm-release',action='store_true')
    a=p.parse_args();config=json.loads(a.config.read_text())
    if a.confirm_release:
        if a.start:raise ValueError('RELEASE_IS_SEPARATE_FROM_START')
        from cumotion_archive_lease import confirm_release
        print(json.dumps(confirm_release(config['allocation']),indent=2));return
    print(json.dumps(preflight(config),indent=2))
    if a.start:print(run(config))


if __name__=='__main__':main()
