"""One-command entrypoint; --check is CPU-only and never imports SimulationApp."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,shutil,subprocess,sys,time,uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from materialize import materialize,sha
PKG=Path(__file__).resolve().parents[1]

def write(p,d):Path(p).write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
def verify_backup():
 d=json.loads((PKG/'preservation_manifest.json').read_text());bad=[]
 for row in d['files']:
  p=PKG/row['preserved']
  if not p.is_file() or sha(p)!=row['sha256']:bad.append(row['preserved'])
  if p.exists() and p.is_symlink():bad.append('SYMLINK:'+str(p))
 if bad:raise ValueError(('BACKUP_INTEGRITY_FAILED',bad[:10]))
 return d

def config():
 from portable_runtime import resolve
 return resolve()

def check():
 backup=verify_backup();c=config();folder=PKG/'verification'/('cpu_'+uuid.uuid4().hex[:10]);folder.mkdir(parents=True)
 root=materialize(folder/'root')
 env=os.environ.copy();env['PYTHONPATH']=':'.join([str(root/'work/C-2-moveit'),str(root/'work/C-2-moveit/isaac_sim/scripts'),c['python_site'],c['numpy_site'],'/usr/lib/python3/dist-packages']);env['PYTHONDONTWRITEBYTECODE']='1'
 command=[c['kit_python'],str(PKG/'tools/check_cpu.py'),str(root)]
 result=subprocess.run(command,env=env,text=True,capture_output=True)
 (folder/'stdout.log').write_text(result.stdout);(folder/'stderr.log').write_text(result.stderr)
 report=dict(schema='standalone-depth-stop-CPU-check/1',preserved_files=len(backup['files']),preserved_source126_exact=True,preserved_model38_exact=True,dependency_paths_exist=True,cpu_exit_code=result.returncode,CPU_stdout=result.stdout,CPU_stderr=result.stderr,root=str(root),GPU_SIM_started=False,actual_SIM_verified=False)
 write(folder/'result.json',report);print(json.dumps(report,indent=2,ensure_ascii=False))
 return result.returncode

def run(*,exit_after_stop=False):
 verify_backup();c=config()
 if not os.environ.get('DISPLAY'):raise ValueError('GUI_DISPLAY_REQUIRED: run from the receiving PC desktop terminal, or set its actual DISPLAY.')
 lock=open('/tmp/standalone_depth_stop_SIM194.lock','a+')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise ValueError('ANOTHER_STANDALONE_SIM194_RUN_ACTIVE')
 # Refuse competing live simulators/planners. Do not terminate any process.
 conflicts=[]
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
  try:
   args=(proc/'cmdline').read_bytes().split(b'\0');exe=Path(args[0].decode(errors='replace')).name
   if exe in ('moveit_plan_only','isaac-sim','kit') or (exe.startswith('python') and any(b'run_fixed_depth_native.py' in a or b'run_depth_stop_native.py' in a for a in args[1:])):conflicts.append(dict(pid=int(proc.name),executable=exe))
  except (OSError,IndexError):pass
 if conflicts:raise ValueError(('SIM1_PLANNER1_CONFLICT',conflicts))
 gpu=subprocess.run(['nvidia-smi','--query-compute-apps=pid,process_name','--format=csv,noheader'],capture_output=True,text=True)
 if gpu.returncode!=0:raise ValueError('GPU_RESOURCE_QUERY_FAILED')
 if any(line.strip() and not line.split(',')[-1].strip().endswith('/sunshine') for line in gpu.stdout.splitlines()):raise ValueError('GPU_COMPUTE_RESOURCE_BUSY: '+gpu.stdout.strip())
 if shutil.disk_usage(PKG).free<8*1024**3:raise ValueError('NEED_8_GIB_FREE_FOR_FRESH_SIM_EVIDENCE_NO_RECORDS_DELETED')
 session=PKG/'runs'/(datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%dT%H%M%S%z')+'_'+uuid.uuid4().hex);session.mkdir(parents=True,exist_ok=False)
 root=materialize(session/'root');out=session/'native';nonce=uuid.uuid4().hex
 os.environ['DEPTH_STOP_SESSION_NONCE']=nonce
 context=dict(schema='standalone-depth-stop-context/1',mode='SIM_ONLY_DETECTION_STOP',session_nonce=nonce,session_directory=str(session),root=str(root),run=str(out),native_pid=os.getpid(),native_startticks=Path('/proc/self/stat').read_text().split()[21],maximum_starts=1,source='TERMINAL_EXPLICIT_STANDALONE_LAUNCH_NOT_SUPERVISOR_CLAIM',allowed=True,owner='MoveIt-Isaac',scope='SIM_FRESH_FOREGROUND_CONSERVATIVE_STOP_SAME_UUID_NO_REPLAN',detector_cancel_SIM_authorized=True,conservative_stop_max_source_age_SIM_s=.4,current_stop_providers=True,bounded_stop_video=True,command_start_planning=True,new_qualification_required=True,static_fixture_adapter_adopted=False,qualification_output=str(session/'qualification'),qualifier_worker=str(root/'work/C-2-moveit/isaac_sim/scripts/standalone_qualifier_worker.py'),kit_python=c['kit_python'],SDK_execution=False)
 context['keep_open_after_stop']=not exit_after_stop
 context['scenario']='MIDPATH_ACTUAL_BLOCK_CURVE_WITH_KNOWN_REFERENCE_PLATE'
 for key,rel in [('numerical_kernel_manifest','moveit_cpp_kernel_integration_20261015/kernel_manifest.json'),('interval_kernel_manifest','moveit_interval_kernel_integration_20261015/interval_manifest.json'),('stop_owner_limits','moveit_stop_owner_publication_20261015/owner_limits.json')]:
  path=root/'local_records'/rel;context[key]=dict(path=str(path),sha256=sha(path))
 context['qualifier_worker_ref']=dict(path=context['qualifier_worker'],sha256=sha(context['qualifier_worker']))
 write(session/'context.json',context)
 with (session/'start_once.json').open('x') as f:json.dump(dict(nonce=nonce,starts=1,retries=0),f)
 write(session/'implementation_handoff.json',dict(schema='standalone-implementation-context/1',context=dict(path=str(session/'context.json'),sha256=sha(session/'context.json')),historical_evidence_reused_as_current=False,SDK_execution=False))
 args=['--root',str(root),'--out',str(out),'--allocation',str(session/'context.json'),'--fresh-moveit-baseline','--source-depth-baseline','--direct-camera-display','--unlabelled-static-shadow','--fresh-foreground-stop','--foreground-stop-max-source-age-s','.4','--foreground-python-switch-interval-ms','1','--sim-command-profile','SIM_FAST_J20','--source-render-every-physics-steps','4','--current-stop-providers','--bounded-stop-video','--command-start-planning','--bootstrap-gripper-wall-budget-s','120','--show-wrist-camera','--transport-calculator',str(root/'local_records/moveit_observed_support_application_20261016/calculate_moveit.sh'),'--qualification-report-path',str(session/'qualification_report.json'),'--pre-obstacle-handoff-public-path',str(session/'pre_obstacle_handoff.json')]
 for flag,key in [('--cpp-depth-raster-manifest','numerical_kernel_manifest'),('--cpp-depth-interval-manifest','interval_kernel_manifest'),('--sim-stop-owner-limits','stop_owner_limits')]:args.extend([flag,context[key]['path']])
 os.environ['PYTHONPATH']=':'.join([str(root/'work/C-2-moveit'),str(root/'work/C-2-moveit/isaac_sim/scripts'),c['python_site'],c['numpy_site'],'/usr/lib/python3/dist-packages'])
 os.environ['LD_LIBRARY_PATH']=str(Path(c['isaac_root'])/'exts/isaacsim.ros2.core/jazzy/lib')+':'+os.environ.get('LD_LIBRARY_PATH','')
 os.environ['PYTHONDONTWRITEBYTECODE']='1'
 # The parent waits for its own child only and records normal closure.
 write(session/'launch.json',dict(executable=str(Path(c['isaac_root'])/'python.sh'),args=args,root=str(root),native_output=str(out)))
 print('Standalone session:',session,flush=True)
 print('After verified STOP: '+('close automatically.' if exit_after_stop else 'keep IsaacSim paused and open; close its window to exit.'),flush=True)
 with (session/'native.sdk.log').open('xb') as log:
  child=subprocess.Popen([str(Path(c['isaac_root'])/'python.sh'),str(root/'work/C-2-moveit/isaac_sim/scripts/run_depth_stop_native.py'),*args],stdout=log,stderr=subprocess.STDOUT,env=os.environ.copy())
  code=child.wait()
 bound=json.loads((session/'context.json').read_text());stat=Path('/proc/'+str(bound['native_pid'])+'/stat')
 gone=not stat.exists() or stat.read_text().split()[21]!=bound['native_startticks']
 derived=json.loads((session/'derived_manifest.json').read_text())
 unchanged=all(sha(root/x['path'])==x['sha256'] for x in derived['files'])
 summary_path=out/'minimal_recording_summary.json'
 retained=summary_path.is_file() and json.loads(summary_path.read_text()).get('essential_evidence_preserved') is True
 good=code==0 and gone and unchanged and retained and (session/'result_pending.json').is_file() and not (out/'failure.txt').exists() and not (out/'transport_failure.json').exists()
 write(session/'closure.json',dict(wrapper_exit_code=code,owned_native_PID_gone=gone,source_model_bytes_unchanged=unchanged,essential_original_raw_evidence_preserved=retained,normal_closure_verified=good,other_processes_killed=False,SDK_runs=0,automatic_retries=0))
 if not good:raise ValueError('RUN_NOT_VERIFIED: inspect '+str(session/'native.sdk.log'))
 result=json.loads((session/'result_pending.json').read_text());result.update(normal_closure_verified=True,closure=dict(path=str(session/'closure.json'),sha256=sha(session/'closure.json')))
 write(session/'result.json',result);print('Verified STOP and normal closure:',session/'result.json')
 return 0

def main():
 p=argparse.ArgumentParser(description='MIDPATH standalone: obstacle on the actual block route halfway between supply and assembly boards. Conservative depth detection → same UUID cancel once → STOP/hold. SIM only. --check never starts GPU/SIM.')
 group=p.add_mutually_exclusive_group(required=True);group.add_argument('--check',action='store_true',help='Verify independent snapshot, dependencies, derived inputs, CPU imports/FCL/kernel libraries; no simulator.');group.add_argument('--run',action='store_true',help='One fresh session; after verified STOP/source progress, keep IsaacSim paused and open until you close its window. Requires free GPU/SIM1/planner1 resources.')
 p.add_argument('--exit-after-stop',action='store_true',help='With --run, close automatically after verified STOP and raw evidence flush (previous behavior).')
 a=p.parse_args()
 if a.exit_after_stop and not a.run:p.error('--exit-after-stop requires --run')
 return check() if a.check else run(exit_after_stop=a.exit_after_stop)
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(2)
