"""One owned launch, bounded /proc diagnostics; never signal/retry any process."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,subprocess,time


def pid_snapshot(pid):
    root=Path('/proc')/str(pid)
    try:
        stat=root.joinpath('stat').read_text().rsplit(')',1)[1].split()
        status={k:v.strip() for line in root.joinpath('status').read_text().splitlines() if ':' in line for k,v in [line.split(':',1)] if k in ('Name','VmRSS','VmHWM','Threads')}
        return dict(pid=pid,startticks=stat[19],exe=str(root.joinpath('exe').resolve(strict=True)),cgroup=root.joinpath('cgroup').read_text().strip(),status=status)
    except (OSError,ValueError,IndexError):return None


def memory_snapshot():
    return {k:int(v.split()[0]) for line in Path('/proc/meminfo').read_text().splitlines() for k,v in [line.split(':',1)] if k in ('MemAvailable','SwapFree','MemTotal')}


def cgroup_snapshot(identity):
    if not identity:return []
    relative=next((line.split('::',1)[1] for line in identity['cgroup'].splitlines() if '::' in line),None)
    if relative is None:return []
    path=Path('/sys/fs/cgroup');rows=[]
    for part in ['',*Path(relative).parts[1:]]:
        if part:path=path/part
        values={}
        for name in ('memory.max','memory.high','memory.current','memory.events','memory.pressure'):
            try:values[name]=(path/name).read_text().strip()
            except OSError:values[name]=None
        rows.append(dict(path=str(path),values=values))
    return rows


def gpu_snapshot():
    try:
        p=subprocess.run(['nvidia-smi','--query-gpu=uuid,memory.total,memory.used,memory.free','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
        return dict(returncode=p.returncode,summary=p.stdout.strip())
    except (OSError,subprocess.TimeoutExpired) as exc:return dict(unavailable=type(exc).__name__)


def child_python(wrapper_pid,expected):
    try:children=(Path('/proc')/str(wrapper_pid)/'task'/str(wrapper_pid)/'children').read_text().split()
    except OSError:return None
    for pid in children:
        value=pid_snapshot(int(pid))
        if value and Path(value['exe'])==expected:return value
    return None


def observe(command,folder,log_path,*,scope,expected_python,interval_s=1.,native_process_path=None):
    if scope not in ('CPU_LAUNCH_DIAGNOSTIC_TEST','EXPLICIT_ISOLATED_SIM_STARTUP_DIAGNOSTIC'):raise ValueError('EXPLICIT_LAUNCH_DIAGNOSTIC_SCOPE_REQUIRED')
    if scope=='EXPLICIT_ISOLATED_SIM_STARTUP_DIAGNOSTIC':
        if (os.environ.get('ROS_DOMAIN_ID')!='194' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')!='LOCALHOST' or
                Path(command[0]).resolve()!=Path('/home/ms-02/isaacsim/python.sh') or interval_s!=1.):
            raise ValueError('EXISTING_SIM194_SDK_WRAPPER_ONLY')
        def option(name):
            if command.count(name)!=1:raise ValueError('PINNED_NATIVE_COMMAND_OPTION_REQUIRED:'+name)
            return Path(command[command.index(name)+1]).resolve()
        allocation_path=option('--allocation');run=option('--out')
        allocation=json.loads(allocation_path.read_text());claim_path=Path(allocation['claim_path']);pins_path=Path(allocation['final_pins_path'])
        claim=json.loads(claim_path.read_text());pins=json.loads(pins_path.read_text())
        def ref(path):return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        script=Path(command[1]).resolve()
        if (script.name!='run_depth_stop_native.py' or script.parent.name!='scripts' or
                allocation.get('allowed') is not True or allocation.get('owner')!='MoveIt-Isaac' or
                allocation.get('scope')!='SIM_FRESH_FOREGROUND_CONSERVATIVE_STOP_SAME_UUID_NO_REPLAN' or
                claim.get('allocation')!=ref(allocation_path) or claim.get('final_pins')!=ref(pins_path) or
                claim.get('maximum_starts')!=1 or claim.get('starts_used')!=1 or claim.get('remaining_after_attempt')!=0 or
                pins.get('maximum_starts')!=1 or Path(claim['run']).resolve()!=run or Path(pins['run']).resolve()!=run or
                ref(Path(__file__)) not in pins['sources'] or ref(script) not in pins['sources']):
            raise ValueError('EXISTING_FROZEN_MAX1_NATIVE_CLAIM_REQUIRED')
        if Path(folder).resolve().is_relative_to(run) or log_path.resolve().is_relative_to(run):
            raise ValueError('LAUNCH_DIAGNOSTICS_MUST_NOT_CREATE_NATIVE_OUTPUT')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);log_path=Path(log_path);expected_python=Path(expected_python).resolve(strict=True)
    started=time.monotonic();errors=[];events=[]
    def event(kind,**values):
        value=dict(kind=kind,wall_monotonic_s=time.monotonic(),**values);events.append(value)
        try:
            with (folder/'events.jsonl').open('a') as f:f.write(json.dumps(value)+'\n')
        except OSError as exc:errors.append(type(exc).__name__)
    own=pid_snapshot(os.getpid());baseline=dict(memory_KiB=memory_snapshot(),memory_pressure=Path('/proc/pressure/memory').read_text(),cgroups=cgroup_snapshot(own),GPU=gpu_snapshot() if scope!='CPU_LAUNCH_DIAGNOSTIC_TEST' else None)
    event('BEFORE_LAUNCH',observer=own,resources=baseline)
    child=None;child_first=None;minimum_available=baseline['memory_KiB']['MemAvailable'];peak_rss_KiB=None;samples=0;native_match=None
    with log_path.open('xb') as log:
        proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        wrapper=pid_snapshot(proc.pid);event('WRAPPER_STARTED',wrapper=wrapper,wrapper_pid=proc.pid)
        while True:
            if child is None:
                child=child_python(proc.pid,expected_python)
                if child:
                    child_first=child;event('PYTHON_CHILD_OBSERVED',child=child,cgroups=cgroup_snapshot(child))
            if child:
                current=pid_snapshot(child['pid'])
                if current and current['startticks']==child['startticks']:
                    child=current;rss=child['status'].get('VmRSS');peak_rss_KiB=max(peak_rss_KiB or 0,int(rss.split()[0])) if rss else peak_rss_KiB
            if native_match is None and native_process_path and Path(native_process_path).is_file():
                try:
                    native=json.loads(Path(native_process_path).read_text())
                    native_match=bool(child and native['pid']==child['pid'] and str(native['startticks'])==child['startticks'])
                    event('NATIVE_RECORD_PID_COMPARISON',matches=native_match,record_path=str(native_process_path),record_pid=native['pid'])
                except (OSError,ValueError,KeyError):pass
            minimum_available=min(minimum_available,memory_snapshot()['MemAvailable']);samples+=1
            try:rc=proc.wait(timeout=interval_s);break
            except subprocess.TimeoutExpired:continue
    after=dict(memory_KiB=memory_snapshot(),memory_pressure=Path('/proc/pressure/memory').read_text(),child_cgroups=cgroup_snapshot(child_first),observer_cgroups=cgroup_snapshot(own),GPU=gpu_snapshot() if scope!='CPU_LAUNCH_DIAGNOSTIC_TEST' else None)
    with log_path.open('rb') as f:f.seek(max(0,log_path.stat().st_size-65536));tail=f.read()
    shell_killed=bool(child and (str(child['pid'])+' Killed').encode() in tail)
    event('WRAPPER_EXIT',raw_wrapper_returncode=rc,child_signal_from_shell_log='SIGKILL' if shell_killed else None,resources=after)
    result=dict(schema='owned-launch-diagnostics/1',scope=scope,wrapper=wrapper,wrapper_pid=proc.pid,raw_wrapper_returncode=rc,conventional_exit_code=128-rc if rc<0 else rc,child_first=child_first,child_last_observed=child,child_raw_wait_status=None,native_process_record_matches_child=native_match,child_signal_from_shell_log='SIGKILL' if shell_killed else None,wrapper_signal=(-rc if rc<0 else None),root_cause=None,root_cause_note='Exit signal, cgroup counters and operator evidence are distinct; no sender/OOM attribution inferred.',resources_before=baseline,resources_after=after,minimum_observed_MemAvailable_KiB=minimum_available,peak_observed_child_RSS_KiB=peak_rss_KiB,sampling_interval_wall_s=interval_s,samples=samples,event_count=len(events),duration_wall_s=time.monotonic()-started,log=dict(path=str(log_path.resolve()),sha256=hashlib.sha256(log_path.read_bytes()).hexdigest()),diagnostic_errors=errors,automatic_retry=False,signals_sent=False,unrelated_processes_touched=False,SDK_ready_inferred=False)
    try:(folder/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    except OSError as exc:print('LAUNCH_DIAGNOSTIC_RESULT_WRITE_FAILED',type(exc).__name__)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scope',required=True,choices=('EXPLICIT_ISOLATED_SIM_STARTUP_DIAGNOSTIC',));parser.add_argument('--out',type=Path,required=True);parser.add_argument('--sdk-log',type=Path,required=True);parser.add_argument('--expected-python',type=Path,default=Path('/home/ms-02/isaacsim/kit/python/bin/python3'));parser.add_argument('--native-process-record',type=Path);parser.add_argument('command',nargs=argparse.REMAINDER);args=parser.parse_args();command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:raise ValueError('ONE_OWNED_COMMAND_REQUIRED')
    result=observe(command,args.out,args.sdk_log,scope=args.scope,expected_python=args.expected_python,native_process_path=args.native_process_record)
    print('OWNED_LAUNCH_FINISHED',result['raw_wrapper_returncode'],'CAUSE_UNATTRIBUTED');return result['conventional_exit_code']
if __name__=='__main__':raise SystemExit(main())
