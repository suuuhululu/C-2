"""Standalone session provenance and automatic original baseline qualifier dispatch."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
_WORKER=None

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return dict(path=str(Path(p).resolve()),sha256=sha(p))
def atomic(p,value,*,before_replace=None):
 p=Path(p);temp=p.with_name(p.name+'.tmp')
 with temp.open('x') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 if before_replace is not None:before_replace()
 temp.replace(p)

def validate_pending_publication(publication,expected,qualification,error,checks):
 """Pure metadata contract; callers separately verify actual file hashes."""
 required=dict(schema='depth-native12-source-qualification/1.0',status='SCOPED_PRE_OBSTACLE_QUALIFICATION_READY',
     run=expected['run'],session_id=expected['session_id'],clock_epoch=expected['clock_epoch'],
     previous_session_substituted=False,old_session_scope_copied=False,observation='REPORT_ONLY',
     point_error_m=None,official_tolerance_m=None,risk_qualified=False,stop_intent=False,
     source_clock_retimed=False,execution_allowed=False,world_clear_allowed=False)
 for name,value in required.items():
  if name not in publication or type(publication[name]) is not type(value) or publication[name]!=value:raise ValueError('PUBLICATION_EXACT_FIELD_REQUIRED:'+name)
 if publication.get('qualification_ref')!=publication.get('qualified_ref') or publication.get('error_ref')!=publication.get('error_model_ref'):raise ValueError('PUBLICATION_ALIAS_MISMATCH')
 if not publication.get('qualification_ref') or not publication.get('error_ref'):raise ValueError('PUBLICATION_ALIASES_REQUIRED')
 if (qualification.get('schema')!='depth-scoped-qualification/1.0' or qualification.get('scope')!='SIM_TEST_REPORT_ONLY' or
     qualification.get('capture_sessions')!=[expected['session_id']] or qualification.get('model_manifest_sha256')!=expected['model_manifest_sha256'] or
     qualification.get('official_observation')!='REPORT_ONLY' or qualification.get('future_guarantee') is not False or
     qualification.get('offset_uv')!=[.5,.5] or qualification.get('same_face_footprint_px')!=5):raise ValueError('QUALIFICATION_EXACT_REPORT_ONLY_SCOPE_REQUIRED')
 if qualification.get('source_refs')!=expected['source_refs'] or error.get('source_refs')!=expected['source_refs']:raise ValueError('CURRENT_SELECTED_SOURCE_REFS_REQUIRED')
 if (error.get('status')!='SIM_SCOPED_NUMERICAL_MODEL' or error.get('decision')!='REPORT_ONLY' or
     error.get('official_observation_status')!='OFFICIAL_NOT_DEFINED' or error.get('qualification_ref')!=publication['qualification_ref']):raise ValueError('ERROR_MODEL_REPORT_ONLY_SCOPE_REQUIRED')
 for name in ('expected_error_m','depth_error_m','point_error_m','point_bound_semantics','official_tolerance_m'):
  if name not in error or error[name] is not None:raise ValueError('ERROR_MODEL_NULL_REQUIRED:'+name)
 if len(checks)!=2 or [x.get('source_frame_ref') for x in checks]!=expected['baseline_frame_refs']:raise ValueError('EXACT_CURRENT_BASELINE2_REFS_REQUIRED')
 if any(type(x['counts']['foreground']) is not int or x['counts']['foreground']!=0 or x['counts']['matched_static']<=0 for x in checks):raise ValueError('BASELINE2_NUMERICAL_CHECKS_REQUIRED')
 return True

def publication_commit_eligible(session,out):
 """Runs on native main, immediately before atomic replace; no app/tick calls."""
 session=Path(session);out=Path(out);context=read(session/'context.json')
 verify_context(session/'context.json',context['root'],out)
 for name in ('failure.txt','transport_failure.json','capture_failure.json','stop.request','shutdown.request'):
  if (out/name).exists():raise ValueError('PUBLICATION_BLOCKED_NATIVE_STATE:'+name)

def publish_pending(publication,expected,qualification,error,checks,session,out):
 validate_pending_publication(publication,expected,qualification,error,checks)
 publication_commit_eligible(session,out)
 atomic(Path(session)/'qualification_report.json',publication,before_replace=lambda:publication_commit_eligible(session,out))
def bind_native_context(path,root,out):
 p=Path(path).resolve();d=read(p)
 if d.get('schema')!='standalone-depth-stop-context/1' or d.get('session_nonce')!=os.environ.get('DEPTH_STOP_SESSION_NONCE') or d.get('root')!=str(root) or d.get('run')!=str(out):raise ValueError('STANDALONE_NATIVE_BINDING_INVALID')
 parent=Path('/proc/'+str(os.getppid())+'/stat')
 ancestor=os.getppid() if os.getppid()==d['native_pid'] else int(parent.read_text().split()[3])
 ancestor_stat=Path('/proc/'+str(ancestor)+'/stat')
 if ancestor!=d['native_pid'] or ancestor_stat.read_text().split()[21]!=d['native_startticks']:raise ValueError('STANDALONE_EXPECTED_ISAAC_WRAPPER_PARENT_REQUIRED')
 with (p.parent/'native_bound_once.json').open('x') as f:json.dump(dict(nonce=d['session_nonce'],pid=os.getpid()),f)
 d.update(native_pid=os.getpid(),native_startticks=Path('/proc/self/stat').read_text().split()[21])
 atomic(p,d)

def verify_context(path,root,out):
 p=Path(path).resolve();d=read(p);out=Path(out).resolve();root=Path(root).resolve()
 if (d.get('schema')!='standalone-depth-stop-context/1' or d.get('mode')!='SIM_ONLY_DETECTION_STOP' or
     d.get('root')!=str(root) or d.get('run')!=str(out) or d.get('maximum_starts')!=1 or
     d.get('SDK_execution') is not False or d.get('session_nonce')!=os.environ.get('DEPTH_STOP_SESSION_NONCE') or
     Path(d['session_directory']).resolve()!=out.parent or p!=out.parent/'context.json'):
  raise ValueError('STANDALONE_CONTEXT_PROVENANCE_MISMATCH')
 if os.environ.get('ROS_DOMAIN_ID')!='194' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')!='LOCALHOST':raise ValueError('STANDALONE_SIM194_LOCALHOST_REQUIRED')
 if Path('/proc/self/stat').read_text().split()[21]!=d.get('native_startticks') or os.getpid()!=d.get('native_pid'):raise ValueError('STANDALONE_SINGLE_PROCESS_BINDING_REQUIRED')
 if read(out.parent/'start_once.json')['nonce']!=d['session_nonce']:raise ValueError('STANDALONE_SINGLE_START_REQUIRED')
 return d

def qualify_once(out):
 global _WORKER
 out=Path(out).resolve();session=out.parent;context=read(session/'context.json')
 verify_context(session/'context.json',context['root'],out)
 marker=session/'qualification_once.json';pending=session/'qualification_pending.json';public=session/'qualification_report.json'
 if _WORKER is None:
  if marker.exists():raise ValueError('QUALIFICATION_ALREADY_DISPATCHED_NO_RETRY')
  pre=read(out/'pre_obstacle_handoff.json')
  if len(pre.get('frames',[]))!=2:raise ValueError('EXACT_ORIGINAL_BASELINE2_REQUIRED')
  if pre.get('new_unknown_actor_created') is not False or pre.get('scope')!='NEW_SESSION_ACTUAL_PRE_OBSTACLE_BASELINE':raise ValueError('PRE_OBSTACLE_BASELINE2_REQUIRED')
  with (session/'qualifier_source_handoff.json').open('xb') as f:f.write((out/'pre_obstacle_handoff.json').read_bytes())
  with marker.open('x') as f:json.dump(dict(session_id=pre['session_id'],clock_epoch=pre['clock_epoch'],nonce=context['session_nonce'],pre_handoff=pin(out/'pre_obstacle_handoff.json'),automatic_retries=0),f)
  script=Path(context['qualifier_worker']);log=(session/'qualification.log').open('xb')
  bootstrap="""from pathlib import Path
import sys,json
session=Path(sys.argv[1]);context=json.loads((session/'context.json').read_text())
from isaac_sim.depth_obstacles.helper_provenance import freeze
proof=freeze(('standalone_qualifier_worker',),session/'worker_adapter_first_import_pins')['standalone_qualifier_worker']
if proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or proof['source_pin']['sha256']!=context['qualifier_worker_ref']['sha256']:raise ValueError('WORKER_SELECTED_CODE_REQUIRED')
import standalone_qualifier_worker
standalone_qualifier_worker.main(str(session))
"""
  try:_WORKER=subprocess.Popen([context['kit_python'],'-c',bootstrap,str(session)],stdout=log,stderr=subprocess.STDOUT,env=os.environ.copy())
  finally:log.close()
  return
 code=_WORKER.poll()
 if code is None:return
 exit_receipt=session/'qualification_worker_exit.json'
 if not exit_receipt.exists():atomic(exit_receipt,dict(schema='standalone-actual-worker-poll-exit/1',worker_pid=_WORKER.pid,return_code=code,scope='ACTUAL_NATIVE_PARENT_POPEN_POLL_RETURN_VALUE',automatic_retry=False))
 if public.exists():return
 if code!=0 or not pending.exists():raise ValueError('FRESH_BASELINE2_QUALIFIER_FAILED_NO_RETRY')
 publication=read(pending);identity=read(marker);pre=read(out/'pre_obstacle_handoff.json')
 if (publication.get('status')!='SCOPED_PRE_OBSTACLE_QUALIFICATION_READY' or publication.get('session_id')!=pre['session_id'] or
     publication.get('clock_epoch')!=pre['clock_epoch'] or publication.get('run')!=str(out) or
     publication['session_id']!=identity['session_id'] or publication.get('old_session_scope_copied') is not False):raise ValueError('QUALIFICATION_SAME_SESSION_READY_REQUIRED')
 if (out/'failure.txt').exists() or (out/'transport_failure.json').exists():raise ValueError('QUALIFICATION_FAILED_NATIVE_SESSION')
 for name in ('qualification_ref','error_model_ref','scope_review_ref','pre_baseline_checks_ref'):
  r=publication[name];f=Path(r['path']).resolve()
  if not f.is_relative_to(session/'qualification') or sha(f)!=r['sha256']:raise ValueError('QUALIFICATION_NEW_OUTPUT_PIN_REQUIRED')
 q=read(publication['qualification_ref']['path']);error=read(publication['error_model_ref']['path']);checks=read(publication['pre_baseline_checks_ref']['path'])
 sources=[publication['scope_review_ref'],pin(out/'pre_obstacle_handoff.json'),pin(out/'baseline_camera_profile.json'),pin(out/'loaded_sources/baseline_camera.py'),pin(out/'loaded_runtime_source_pins.json')]
 sources.extend(pre['known_map'][name] for name in ('map_snapshot','held_definition','approved_static_ids','source_refs'))
 for r in sources:
  if sha(r['path'])!=r['sha256']:raise ValueError('QUALIFICATION_ORIGINAL_SOURCE_PIN_CHANGED')
 binding_path=session/'qualifier_executed_source_binding.json';binding=read(binding_path)
 if (binding.get('schema')!='standalone-qualifier-executed-code-binding/1' or
     binding.get('status')!='SELECTED_BYTES_FUNCTION_CODE_IDENTITY_VERIFIED_BEFORE_NUMERICAL_CALL' or
     binding.get('q_code_identity_verified') is not True or binding.get('configurator_code_identity_verified') is not True or
     binding.get('numerical_calls_before_binding')!=0 or binding.get('session_id')!=pre['session_id'] or binding.get('clock_epoch')!=pre['clock_epoch']):raise ValueError('QUALIFIER_EXECUTED_SOURCE_BINDING_REQUIRED')
 root=Path(context['root'])
 for name,relative in [('original_q_source','local_records/depth_native11_latency_stage03_20261015/unit01/qualify_native12_v2.py'),('original_configurators_source','local_records/depth_joint_compact_source_qualification_20261016/qualify_joint_candidate06_unit24.py')]:
  if binding[name]!=pin(root/relative):raise ValueError('QUALIFIER_SELECTED_SOURCE_REF_MISMATCH')
 for name in ('native_adapter_first_import','worker_first_import','dependency_first_import'):
  if pin(binding[name]['path'])!=binding[name]:raise ValueError('QUALIFIER_FIRST_IMPORT_RECEIPT_CHANGED')
 expected=dict(run=str(out),session_id=pre['session_id'],clock_epoch=pre['clock_epoch'],source_refs=sources,baseline_frame_refs=[x['frame_input'] for x in pre['frames']],model_manifest_sha256=sha(Path(pre['known_map']['model_bundle'])/'MODEL_MANIFEST.json'))
 publish_pending(publication,expected,q,error,checks,session,out)
 atomic(session/'qualification_dispatch_receipt.json',dict(status='NEW_SESSION_BASELINE2_ONCE_PARENT_ATOMIC_PUBLICATION',worker_exit=code,qualifier_invocations=1,marker=pin(marker),publication=pin(public),executed_source_binding=pin(binding_path),native_session_id=pre['session_id'],old_session_reused=False))

def finish_stop(out,result):
 out=Path(out);session=out.parent;progress=read(out/'post_stop_source_progress.json')
 status=read(out/'transport_status.json');accepted=read(out/'D_stop_owner/accepted.json');ack=read(out/'foreground_cancel_ack.json')
 if not (result.get('conservative_stop_verified') is True and status.get('stop_verified') is True and status.get('holding_confirmed') is True and status.get('gripper_open_issued') is False and status.get('contact_execution_issued') is False):raise ValueError('ACTUAL_STOP_HOLDING_PROOF_REQUIRED')
 if progress.get('sensor_and_source_progress_verified') is not True or any(progress['command_counts'].values()) or len(progress['original_new_frames'])<2:raise ValueError('STOP_SOURCE_PROGRESS_COUNT0_REQUIRED')
 # Native D already validates one UUID/cancel-once, raw ACK and CANCELED.
 # Retain those complete original records, and require terminal CANCELED here.
 terminal=status['native_action_result']
 uuid=accepted['goal_id']
 if (status.get('cancel_request_count')!=1 or status.get('cancel_bound_uuid')!=uuid or terminal['status']!=5 or terminal.get('error_code')!=0 or ack.get('done') is not True or ack.get('return_code')!=0 or ack.get('goals_canceling_count')!=1 or ack.get('goals_canceling_ids')!=[uuid] or any(status['native_command_counts'].values())):raise ValueError('SAME_UUID_CANCEL_ONCE_ACK_CANCELED_COUNT0_REQUIRED')
 atomic(session/'result_pending.json',dict(status='DETECTION_CANCEL_STOP_HOLD_SOURCE_PROGRESS_VERIFIED',scope='CONSERVATIVE_FOREGROUND_ANYNEW_STOP_ONLY',transport_status=pin(out/'transport_status.json'),accepted=pin(out/'D_stop_owner/accepted.json'),cancel_ack=pin(out/'foreground_cancel_ack.json'),post_stop_source_progress=pin(out/'post_stop_source_progress.json'),qualification_dispatch=pin(session/'qualification_dispatch_receipt.json'),SDK_execution=False,replan=False,resume=False,gripper_open=False,postSTOP_completion_deadline_s=None,legacy_012_comparison='REPORT_ONLY; live controller/reference health still enforced separately'))
 # Source/clock remain live through the postSTOP proof; evidence flush follows.

def begin_stop_inspection(out,success):
 """Enter paused inspection only after the native STOP proof and raw flush."""
 if not success:return False
 out=Path(out).resolve();session=out.parent;context=read(session/'context.json')
 if context.get('keep_open_after_stop') is not True:return False
 verify_context(session/'context.json',context['root'],out)
 if read(session/'result_pending.json').get('status')!='DETECTION_CANCEL_STOP_HOLD_SOURCE_PROGRESS_VERIFIED':raise ValueError('INSPECTION_REQUIRES_VERIFIED_STOP')
 if read(out/'minimal_recording_summary.json').get('essential_evidence_preserved') is not True:raise ValueError('INSPECTION_REQUIRES_RAW_EVIDENCE_FLUSH')
 for name in ('failure.txt','transport_failure.json','capture_failure.json'):
  if (out/name).exists():raise ValueError('INSPECTION_BLOCKED_NATIVE_FAILURE:'+name)
 atomic(session/'inspection_status.json',dict(status='STOP_VERIFIED_PAUSED_WINDOW_OPEN',paused=True,stop_verified=True,raw_evidence_flushed=True,normal_closure_pending=True,resume=False,gripper_open=False))
 print('STOP verified; IsaacSim stays paused and open. Close the window to exit normally.',flush=True)
 return True

def end_stop_inspection(out,*,window_closed):
 path=Path(out).resolve().parent/'inspection_status.json';status=read(path)
 status.update(status='WINDOW_CLOSED' if window_closed else 'SHUTDOWN_REQUESTED',normal_closure_pending=True)
 atomic(path,status)
