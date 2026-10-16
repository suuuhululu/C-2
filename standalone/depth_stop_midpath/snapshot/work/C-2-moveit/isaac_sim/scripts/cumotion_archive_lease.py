"""One-shot archive resource lease, independent of live D/STOP/owner state."""
import json,math,os,subprocess,time
from pathlib import Path
from bounded_sim_evidence import pinned_json
from plan_only import digest
from prepare_cpu_model import file_hash


def ref(path):return dict(path=str(Path(path).resolve()),sha256=file_hash(Path(path)))


def process_start(pid):return (Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[19]


def review(config,spec):
    allocation=pinned_json(config['allocation']);g=allocation['archive_cumotion']
    if (allocation['schema']!='cumotion-archive-lease/0.1' or g.get('allowed') is not True or
            g.get('scope')!='ARCHIVED_OFFLINE_CALCULATION' or g.get('engine')!=config['engine'] or
            g.get('engine_spec')!=config['engine_spec'] or g.get('archived_job')!=config['archived_job'] or
            g.get('config_digest_without_allocation')!=digest({k:v for k,v in config.items() if k!='allocation'}) or
            g.get('API_budget')!=spec['API_budget'] or g.get('maximum_jobs')!=1 or g.get('maximum_FCL_calls')!=1 or
            g.get('maximum_FCL_workers')!=1 or g.get('maximum_compute_threads')!=1):
        raise ValueError('EXACT_ONE_SHOT_ARCHIVE_LEASE_REQUIRED')
    for k in ('maximum_jobs','maximum_FCL_calls','maximum_FCL_workers','maximum_compute_threads'):
        if type(g.get(k)) is not int or g[k]!=1:raise ValueError('SINGLE_ARCHIVE_RESOURCE_COUNT_REQUIRED')
    if not isinstance(g.get('gpu_uuid'),str) or not g['gpu_uuid'].startswith('GPU-') or not isinstance(g.get('allowed_baseline_compute_processes'),list):
        raise ValueError('EXPLICIT_GPU_AND_BASELINE_PROCESS_IDENTITIES_REQUIRED')
    for k in ('not_before_monotonic_s','expires_monotonic_s'):
        if type(g.get(k)) not in (int,float) or not math.isfinite(g[k]):raise ValueError('FINITE_ARCHIVE_LEASE_WINDOW_REQUIRED')
    for k in ('max_worker_vram_mib','worker_host_ram_mib','reserved_sim_vram_mib','reserved_sim_host_ram_mib','minimum_free_before_start_mib'):
        if type(g.get(k)) is not int or g[k]<=0:raise ValueError('EXPLICIT_RESOURCE_RESERVATIONS_REQUIRED:'+k)
    if g['minimum_free_before_start_mib']<g['max_worker_vram_mib']+g['reserved_sim_vram_mib']:
        raise ValueError('ARCHIVE_MUST_PRESERVE_SIM_HEADROOM')
    # A new grant must cite actual management release, not the mere absence of
    # an old SIM PID. The current MI allocation remains exclusive until released.
    job=pinned_json(config['archived_job'])
    if g.get('fcl_binary')!=job['fcl_binary'] or g.get('fcl_library')!=job['fcl_library']:
        raise ValueError('ARCHIVE_ORIGINAL_FCL_RESERVATION_CHANGED')
    if ref(g['sim_allocation_path'])!=g['sim_allocation']:raise ValueError('SIM_ALLOCATION_CHANGED')
    release=pinned_json(g['sim_allocation_release'])
    if (release.get('allocation')!=g['sim_allocation'] or release.get('released') is not True or
            release.get('concurrent_SDK_allowed') is not True):raise ValueError('WAIT_MI_EXCLUSIVE_RESERVATION_RELEASE')
    if (g['boot_id']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip() or
            not g['not_before_monotonic_s']<=time.monotonic()<g['expires_monotonic_s']):
        raise ValueError('ARCHIVE_LEASE_NOT_ACTIVE_ON_THIS_BOOT')
    if Path(g['stop_request']).exists():raise ValueError('ARCHIVE_LEASE_STOP_REQUESTED')
    return g


def resources(g,*,before_start):
    """Runtime only, after a valid grant. Never terminate foreign processes."""
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==os.getpid():continue
        try:argv=(p/'cmdline').read_bytes().split(b'\0');exe=argv[0].decode()
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
        if '/isaacsim/' in exe and Path(exe).name.startswith(('python','kit')):
            raise ValueError('WAIT_EXCLUSIVE_SIM_PROCESS_PRESENT')
    raw=subprocess.check_output(['nvidia-smi','--query-gpu=uuid,memory.free','--format=csv,noheader,nounits'],text=True,timeout=3).strip().splitlines()
    if len(raw)!=1:raise ValueError('EXACT_SINGLE_GPU_REQUIRED')
    uuid,free=map(str.strip,raw[0].split(','));free=int(free)
    if uuid!=g['gpu_uuid']:raise ValueError('ALLOCATED_GPU_CHANGED')
    apps=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,used_gpu_memory','--format=csv,noheader,nounits'],text=True,timeout=3)
    allowed={x['pid']:str(x['start_ticks']) for x in g['allowed_baseline_compute_processes']};own=0
    for row in apps.splitlines():
        pid,used=map(int,row.split(','))
        if pid==os.getpid():own+=used
        elif pid not in allowed or process_start(pid)!=allowed[pid]:raise ValueError('UNALLOCATED_COMPUTE_PROCESS_PRESENT')
    if own>g['max_worker_vram_mib'] or free<(g['minimum_free_before_start_mib'] if before_start else g['reserved_sim_vram_mib']):
        raise ValueError('ARCHIVE_VRAM_RESERVATION_REJECTED')
    mem=Path('/proc/meminfo').read_text();available=int(mem.split('MemAvailable:')[1].split()[0])//1024
    if available<g['reserved_sim_host_ram_mib']+(g['worker_host_ram_mib'] if before_start else 0):
        raise ValueError('ARCHIVE_HOST_RESERVATION_REJECTED')
    return dict(pid=os.getpid(),start_ticks=process_start(os.getpid()),gpu_uuid=uuid,free_VRAM_MiB=free,
        own_VRAM_MiB=own,host_available_MiB=available,monotonic_s=time.monotonic())


def claim(config,spec):
    g=review(config,spec)
    if Path(g['claim_path']).exists():raise ValueError('ARCHIVE_LEASE_ALREADY_CONSUMED')
    snapshot=resources(g,before_start=True)
    record=dict(schema='cumotion-archive-lease-use/0.1',allocation=config['allocation'],pid=os.getpid(),
        start_ticks=process_start(os.getpid()),snapshot=snapshot,status='CONSUMED_SINGLE_ATTEMPT_NO_RETRY')
    with Path(g['claim_path']).open('x') as f:json.dump(record,f,indent=2)
    return record



def owned_claim(config,g):
    record=json.loads(Path(g['claim_path']).read_text())
    if (record['allocation']!=config['allocation'] or record['pid']!=os.getpid() or
            record['start_ticks']!=process_start(os.getpid())):
        raise ValueError('ARCHIVE_LEASE_NOT_CLAIMED_BY_THIS_PROCESS')
    return record


def finish(config,record,error=None):
    g=pinned_json(config['allocation'])['archive_cumotion']
    # CUDA context may still exist here. Only a later process-exit check can
    # confirm release; a returned Python function does not release the GPU.
    with Path(g['finish_path']).open('x') as f:json.dump(dict(claim=ref(g['claim_path']),
        status='WORK_FINISHED_PROCESS_EXIT_AND_GPU_RELEASE_PENDING',pid=record['pid'],
        start_ticks=record['start_ticks'],error=error,execution_allowed=False),f,indent=2)


def confirm_release(allocation_ref):
    allocation=pinned_json(allocation_ref);g=allocation['archive_cumotion']
    if allocation.get('schema')!='cumotion-archive-lease/0.1' or g.get('allowed') is not True or g.get('scope')!='ARCHIVED_OFFLINE_CALCULATION':
        raise ValueError('RELEASE_REQUIRES_ORIGINAL_GRANTED_ARCHIVE_LEASE')
    claim_record=json.loads(Path(g['claim_path']).read_text())
    if claim_record['allocation']!=allocation_ref:raise ValueError('RELEASE_WRONG_LEASE')
    try:
        if process_start(claim_record['pid'])==claim_record['start_ticks']:raise ValueError('OWN_ARCHIVE_WORKER_STILL_ALIVE')
    except (FileNotFoundError,ProcessLookupError):pass
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:argv=(p/'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
        if argv and argv[0].decode()==g['fcl_binary']['path']:raise ValueError('ARCHIVE_FCL_CHILD_STILL_ALIVE')
    raw=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'],text=True,timeout=3)
    if str(claim_record['pid']) in raw.split():raise ValueError('WORKER_STILL_IN_GPU_PROCESS_LIST')
    result=dict(status='ARCHIVE_WORKER_EXIT_AND_GPU_RELEASE_CONFIRMED',allocation=allocation_ref,claim=ref(g['claim_path']),
        worker_pid=claim_record['pid'],worker_start_ticks=claim_record['start_ticks'],execution_allowed=False)
    with Path(g['release_path']).open('x') as f:json.dump(result,f,indent=2)
    return result
