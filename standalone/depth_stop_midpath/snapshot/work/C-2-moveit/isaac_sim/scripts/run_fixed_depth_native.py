"""Isolated native D: fresh MoveIt baseline or explicitly pinned CU fixture.

Initial setters run only during existing native initialization. Subsequent
motion belongs to the native FJT controller, never viewport animation.
"""
import argparse,json,hashlib,os,sys,uuid,traceback,copy,marshal,time
from pathlib import Path
from types import SimpleNamespace
from collections import deque
import numpy as np
import yaml

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else x.tolist())+'\n')
def check_fixed_physical_world(baseline,objects,gt):
 from d_sim_transport import check_world
 from sim_utils import pose_matrix,error
 regular=[x for x in objects if x['id']!=gt['id']];settling=check_world(baseline,regular)
 actual=next(x for x in objects if x['id']==gt['id'])
 # This fixture is fixed in World, not on a compliant robot base. Base-frame
 # readout changes are retained; they do not move the static World obstacle.
 pe,re=error(pose_matrix(actual['world_pose']),pose_matrix(gt['world_pose']))
 if actual['size_m']!=gt['size_m'] or pe>1e-6 or re>1e-6:raise ValueError('FIXED_GT_WORLD_CHANGED')
 return settling
def source_support_departure(selected_path,board_path,sample,record):
 """Existing pickup support pair, closed permanently by actual contact loss."""
 state=dict(active=False,seen=False,departed=False)
 def event(kind,payload,stamp):
  if kind=='SUBMISSION_INTENT':state['active']=True
  elif kind in ('CANCEL_REQUEST','GOAL_RESULT'):state['active']=False
 def contact(row):
  paths=row['actors']
  if selected_path not in paths or not any(p==board_path or p.startswith(board_path+'/') for p in paths):return False
  if not state['active'] or state['departed']:return False
  observed=sample()
  if row['contact_count']==0:
   if state['seen']:state['departed']=True
   record(dict(scope='SOURCE_SUPPORT_DEPARTURE_CONTACT_LOST',report=row,observation=observed,state=dict(state)));return False
  # D checks grasp continuity after the entire physics/contact batch. A
  # per-contact callback must not add a stricter transient finger-load gate.
  state['seen']=True
  record(dict(scope='PICKUP_SOURCE_SUPPORT_CONTACT_NOT_TRANSPORT_OBSTACLE',report=row,observation=observed,state=dict(state),grasp_guard='EXISTING_D_CHECK_LIVE_AFTER_COMPLETE_PHYSICS_STEP_UNCHANGED',numeric_force_or_penetration_tolerance_added=False))
  return True
 return event,contact
def receive_native_files_csafe(folder,result_path,latest_binding,output_path):
 """Same original candidate validator and guards; C safe YAML parser only."""
 from plan_only import prepare_d_candidate
 from sim_utils import save as save_candidate
 output_path=Path(output_path)
 if output_path.exists():raise ValueError('D candidate output must be new')
 stages=[]
 def mark(name,started):stages.append(dict(stage=name,start_wall_monotonic_s=started,end_wall_monotonic_s=time.monotonic()))
 service=_audit_ui_service;last_service=time.monotonic();service_count=0
 class Reader:
  def __init__(self,stream):self.stream=stream;self.name=stream.name
  def read(self,size=-1):
   nonlocal last_service,service_count
   # LibYAML already requests bounded stream chunks. Service existing UI at
   # those boundaries; keep every original byte and never advance physics.
   if service is not None and time.monotonic()-last_service>=.05:
    service();service_count+=1;last_service=time.monotonic()
   return self.stream.read(size)
 def read_safe(path):
  with Path(path).open() as stream:return yaml.load(Reader(stream),Loader=yaml.CSafeLoader)
 started=time.monotonic();request=read_safe(Path(folder)/'TRANSPORT.request.yaml');mark('REQUEST_CSAFE_LOAD',started)
 started=time.monotonic();result=read_safe(result_path);mark('RESULT_CSAFE_LOAD',started)
 started=time.monotonic();packet=prepare_d_candidate(result,request,latest_binding);mark('UNCHANGED_ORIGINAL_PREPARE_D_CANDIDATE',started)
 started=time.monotonic();save_candidate(output_path,packet);mark('SAVE_ORIGINAL_D_PACKET',started)
 save(Path(folder)/'native_receive_stages.json',dict(stages=stages,parser='yaml.CSafeLoader',render_only_service_calls=service_count,original_validator='plan_only.prepare_d_candidate',validation_or_guards_skipped=False))
 return packet


def wait_pre_obstacle_baseline(app,timeline,tick,sample,statuses,record,model_provider,out,*,wall_budget_s=120.):
 """Resume original native HOLD from capture's pause; never rewrite its clock."""
 from capture_sim_scene import command_counts
 # Apply the queued pause-to-play transition before any unrendered physics tick.
 timeline.play();app.update();deadline=time.monotonic()+wall_budget_s;ready=False;last=None
 while time.monotonic()<deadline and app.is_running():
  tick();last=sample();record(last,statuses)
  if any(command_counts(statuses).values()) or (out/'stop.request').exists() or (out/'shutdown.request').exists():raise ValueError('PRE_OBSTACLE_BASELINE_EXISTING_COMMAND_OR_STOP_GUARD')
  if last['contact_fingers']!=['rg2_left_inner_finger','rg2_right_inner_finger']:raise ValueError('PRE_OBSTACLE_BASELINE_HOLD_CONTACT_LOST')
  model,evidence=model_provider()
  if (out/'pre_obstacle_handoff.json').exists() and model['status']=='SIM_SCOPED_NUMERICAL_MODEL':ready=True;break
 return dict(actual_source_s=last['time_s'] if last else None,explicit_error_model_available=ready,wall_deadline_s=wall_budget_s,actor_created=False,unqualified_remains_unknown=not ready,physics_source_was_advanced=last is not None)


_audit_ui_service=None
_unlabelled_scenario=None

def audit_current_geometry(folder,request,curve,owner_provider,library):
 """Original complete FCL audit; optional render-only UI service never ticks physics."""
 from stop_fcl import StopScene,check_stop
 from plan_only import digest
 from sim_utils import rigid,pose_matrix,matrix_pose,error
 from prepare_gpu_scene import tcp_fk
 folder.mkdir(exist_ok=False);before=copy.deepcopy(owner_provider())
 actual=copy.deepcopy(request);actual['attachment']=before['attachment_tcp_to_block'];actual['planning_snapshot']['grip_rad']=before['grip_rad']
 byid={x['id']:x for x in before['world_objects']}
 # Keep the conservative Depth obstacle and all physical objects, including
 # the independently authored GT cube. Never duplicate the held block.
 objects=[byid.get(x['id'],x) for x in request['planning_snapshot']['world_objects']]
 ids={x['id'] for x in objects};objects.extend(x for x in before['world_objects'] if x['id'] not in ids)
 actual['planning_snapshot']['world_objects']=objects
 save(folder/'owner.before.json',before);save(folder/'measured_request.json',actual);save(folder/'wire_trajectory.json',curve)
 # The observed-state check and curve time zero use different q provenance.
 # Record both explicitly; a later attachment must never be described as a
 # same-source capture of the original planned start. This is report only.
 save(folder/'FCL_input_binding.json',dict(scope='OBSERVED_OWNER_AND_PLANNED_CURVE_INPUT_PROVENANCE_REPORT_ONLY',
  observed_owner_source_s=before['time_s'],observed_q_rad=before['q_rad'],
  curve_time_zero_s=curve['points'][0]['time_from_start_s'],curve_time_is_relative_not_SIM_stamp=True,
  curve_start_q_rad=curve['points'][0]['positions_rad'],planned_snapshot_q_rad=request['planning_snapshot']['q_rad'],
  planned_grip_rad=request['planning_snapshot']['grip_rad'],planned_attachment=request['attachment'],
  applied_grip_rad=actual['planning_snapshot']['grip_rad'],applied_attachment=actual['attachment'],
  applied_world_objects_source='owner.before.json plus unchanged request-only obstacles',
  q_inputs_equal=before['q_rad']==curve['points'][0]['positions_rad'],
  attachment_inputs_equal=request['attachment']==actual['attachment'],
  new_penetration_tolerance_added=False,support_pair_exempted=False))
 started=time.monotonic();stages=[];service=_audit_ui_service
 def mark(name,start):stages.append(dict(stage=name,start_wall_monotonic_s=start,end_wall_monotonic_s=time.monotonic()))
 scene=StopScene(actual,library,sha(library));mark('ORIGINAL_STOP_SCENE_CONSTRUCTION',started)
 original_check=scene.check;last_service=time.monotonic();check_count=0;ui_calls=0
 def checked(q):
  nonlocal last_service,check_count,ui_calls
  if service is not None and time.monotonic()-last_service>=.05:
   begin=time.monotonic();service();mark('RENDER_ONLY_UI_SERVICE_NO_PHYSICS',begin);ui_calls+=1;last_service=time.monotonic()
  check_count+=1;return original_check(q)
 scene.check=checked;checking_started=time.monotonic()
 try:
  observed_hit=scene.check(before['q_rad'])
  audit=dict(success=False,checks=1,reason='ACTUAL_OBSERVED_START_FCL_REJECTED',**observed_hit) if observed_hit else check_stop(scene,curve)
 finally:
  scene.close();mark('OBSERVED_START_AND_ORIGINAL_WHOLE_CURVE_FCL',checking_started)
  save(folder/'main_loop_stages.json',dict(stages=stages,original_scene_check_calls=check_count,render_only_service_calls=ui_calls,physics_ticks_in_service=0,checks_skipped=0,new_worker_or_child=False))
 after=copy.deepcopy(owner_provider());save(folder/'owner.after.json',after);save(folder/'FCL.json',audit)
 if before!=after:raise ValueError('ACTUAL_GEOMETRY_OWNER_CHANGED_DURING_FCL')
 if not audit['success']:raise ValueError('ACTUAL_WHOLE_CURVE_FCL_REJECTED')
 if _unlabelled_scenario is not None:
  _unlabelled_scenario.prepare(actual,curve,before,library,service)
  if before!=owner_provider():raise ValueError('ACTUAL_OWNER_CHANGED_DURING_SEPARATE_PLACEMENT_AUDIT')
 terminal=tcp_fk(request['model_bundle'],curve['points'][-1]['positions_rad'],before['grip_rad'])
 target=pose_matrix(request['goal']);expected_block=target@rigid(request['attachment']);terminal_block=terminal@rigid(before['attachment_tcp_to_block'])
 goal_review=dict(scope='MODEL_TERMINAL_TCP_AND_ACTUAL_ATTACHMENT_BLOCK_POSE_REPORT_NOT_ACTUAL_GOAL_REACHED',TCP_goal_error_m_rad=error(terminal,target),expected_block_at_D_wait=matrix_pose(expected_block),model_terminal_block_with_actual_attachment=matrix_pose(terminal_block),block_goal_error_m_rad=error(terminal_block,expected_block),attachment_difference_m_rad=error(rigid(before['attachment_tcp_to_block']),rigid(request['attachment'])),contract='Existing fixed test is TCP pre-contact wait; block goal differences recorded separately, no new seating tolerance or assembly success claim')
 save(folder/'terminal_block_goal_review.json',goal_review)
 def ref(p):return dict(path=str(p.resolve()),sha256=sha(p))
 receipt=dict(scope='CURRENT_FIXED_OWNER_ACTUAL_GEOMETRY_WHOLE_CURVE_FCL_NOT_NATIVE_APPROVAL',FCL=audit,owner_digest=digest(before),trajectory_digest=digest(curve),original_request_digest=request['planning_request_digest'],model_digest=request['model_digest'],library=ref(library),owner_before=ref(folder/'owner.before.json'),owner_after=ref(folder/'owner.after.json'),measured_request=ref(folder/'measured_request.json'),wire_trajectory=ref(folder/'wire_trajectory.json'),FCL_result=ref(folder/'FCL.json'),terminal_block_goal_review=ref(folder/'terminal_block_goal_review.json'),native_send_called=False,hardware_execution_allowed=False,live_resume_approved=False)
 save(folder/'receipt.json',receipt);return receipt
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--allocation',type=Path);parser.add_argument('--joint-current-inputs',action='store_true');parser.add_argument('--compact-stop-handoff',action='store_true');parser.add_argument('--current-stop-providers',action='store_true');parser.add_argument('--bounded-stop-video',action='store_true');parser.add_argument('--command-start-planning',action='store_true');parser.add_argument('--same-runtime-worker-handoff',type=Path);parser.add_argument('--qualification-report-path',type=Path);parser.add_argument('--pre-obstacle-handoff-public-path',type=Path);parser.add_argument('--unlabelled-static-shadow',action='store_true');parser.add_argument('--root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--direct-camera-display',action='store_true');parser.add_argument('--source-depth-baseline',action='store_true');parser.add_argument('--source-render-every-physics-steps',type=int,choices=(1,4),default=1);parser.add_argument('--sim-command-profile',choices=('conservative','SIM_FAST_J20'),default='conservative');parser.add_argument('--sim-stop-owner-limits',type=Path);parser.add_argument('--cpp-depth-interval-manifest',type=Path);parser.add_argument('--cpp-depth-raster-manifest',type=Path);parser.add_argument('--fresh-foreground-stop',action='store_true');parser.add_argument('--foreground-stop-max-source-age-s',type=float,choices=(.12,.4),default=.12);parser.add_argument('--foreground-python-switch-interval-ms',type=float,choices=(1.,5.));parser.add_argument('--full-diagnostic-budget-mib',type=int);parser.add_argument('--runtime-preflight-only',action='store_true');parser.add_argument('--fresh-moveit-baseline',action='store_true');parser.add_argument('--transport-calculator',type=Path);parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--dynamic-depth-hold',action='store_true');parser.add_argument('--static-depth-replan',action='store_true');parser.add_argument('--obstacle-path-shift-m',type=float,default=0.);parser.add_argument('--bootstrap-gripper-wall-budget-s',type=float,choices=(60.,120.),default=60.);parser.add_argument('--show-wrist-camera',action='store_true');parser.add_argument('--initial-transport-demo-only',action='store_true');args=parser.parse_args();args.dynamic_depth_hold=args.dynamic_depth_hold or args.static_depth_replan;root=args.root.resolve();out=args.out.resolve()
 if (args.sim_command_profile!='conservative' or args.source_render_every_physics_steps!=1) and not (args.fresh_moveit_baseline and args.source_depth_baseline and os.environ.get('ROS_DOMAIN_ID')=='194' and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')=='LOCALHOST'):raise ValueError('FAST_PROFILE_RENDER_CADENCE_EXPLICIT_SIM194_SOURCE_ONLY')
 if args.foreground_stop_max_source_age_s!=.12 and not args.fresh_foreground_stop:raise ValueError('CONSERVATIVE_STOP_AGE_OVERRIDE_EXPLICIT_SIM_ONLY')
 if args.foreground_python_switch_interval_ms is not None and not args.fresh_foreground_stop:raise ValueError('PYTHON_SWITCH_INTERVAL_EXPLICIT_FRESH_STOP_SIM_ONLY')
 if args.full_diagnostic_budget_mib is not None and args.full_diagnostic_budget_mib<=0:raise ValueError('EXPLICIT_POSITIVE_DIAGNOSTIC_BUDGET_REQUIRED')
 recording_minimal=bool(args.fresh_moveit_baseline and args.source_depth_baseline and args.full_diagnostic_budget_mib is None)
 if args.fresh_foreground_stop:
  if not (args.fresh_moveit_baseline and args.source_depth_baseline and args.direct_camera_display and args.unlabelled_static_shadow and args.allocation):raise ValueError('FRESH_FOREGROUND_STOP_EXPLICIT_SOURCE_MODE_REQUIRED')
  adopted=json.loads(args.allocation.read_text())
  if adopted.get('scope')!='SIM_FRESH_FOREGROUND_CONSERVATIVE_STOP_SAME_UUID_NO_REPLAN' or adopted.get('detector_cancel_SIM_authorized') is not True:raise ValueError('FRESH_FOREGROUND_STOP_EXPLICIT_ALLOCATION_REQUIRED')
  if args.foreground_stop_max_source_age_s!=.12 and adopted.get('conservative_stop_max_source_age_SIM_s')!=args.foreground_stop_max_source_age_s:raise ValueError('CONSERVATIVE_STOP_AGE_OVERRIDE_ALLOCATION_MISMATCH')
 if args.joint_current_inputs:
  if not args.fresh_foreground_stop or not args.compact_stop_handoff or not args.current_stop_providers or adopted.get('joint_current_inputs') is not True:
   raise ValueError('JOINT_CURRENT_INPUTS_EXPLICIT_COMPACT_SIM_ALLOCATION_REQUIRED')
 if args.compact_stop_handoff:
  if not args.current_stop_providers or not args.fresh_foreground_stop or adopted.get('compact_stop_handoff') is not True:
   raise ValueError('COMPACT_STOP_HANDOFF_EXPLICIT_CURRENT_PROVIDER_ALLOCATION_REQUIRED')
 if args.current_stop_providers:
  if not args.fresh_foreground_stop or not args.sim_stop_owner_limits or adopted.get('current_stop_providers') is not True:
   raise ValueError('CURRENT_STOP_PROVIDERS_EXPLICIT_FOREGROUND_SIM_ALLOCATION_REQUIRED')
 if args.bounded_stop_video:
  if not recording_minimal or not args.fresh_foreground_stop or adopted.get('bounded_stop_video') is not True:raise ValueError('BOUNDED_VIDEO_EXPLICIT_MINIMAL_SIM_ALLOCATION_REQUIRED')
 if args.command_start_planning:
  if not (args.fresh_moveit_baseline and args.source_depth_baseline and args.fresh_foreground_stop and args.allocation and os.environ.get('ROS_DOMAIN_ID')=='194' and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')=='LOCALHOST'):raise ValueError('COMMAND_START_PLAN_EXPLICIT_SIM194_SOURCE_ONLY')
  if adopted.get('command_start_planning') is not True:raise ValueError('COMMAND_START_PLAN_EXPLICIT_ALLOCATION_REQUIRED')
 if args.sim_stop_owner_limits:
  if not args.fresh_foreground_stop or adopted.get('stop_owner_limits')!=dict(path=str(args.sim_stop_owner_limits.resolve()),sha256=sha(args.sim_stop_owner_limits)):raise ValueError('STOP_OWNER_EXPLICIT_SIM_LIMITS_ALLOCATION_REQUIRED')
  stop_owner_limits=json.loads(args.sim_stop_owner_limits.read_text())
  if stop_owner_limits['max_state_age_s']!=.12 or stop_owner_limits['min_stop_observation_s']<.5:raise ValueError('STOP_OWNER_ORIGINAL_FRESHNESS_WINDOW_REQUIRED')
  if stop_owner_limits.get('scope')!='CPU_D_BOUNDARY_REVIEW_LIMITS':raise ValueError('STOP_OWNER_REVIEW_POLICY_SCOPE_REQUIRED')
  for name in ('max_stop_velocity_rad_s','max_stop_acceleration_rad_s2','q_tolerance_rad','v_tolerance_rad_s','a_tolerance_rad_s2'):
   criterion=stop_owner_limits['criteria_sources'][name]
   if stop_owner_limits[name] is not None or criterion.get('value') is not None or criterion.get('check_mode')!='REPORT_ONLY' or criterion.get('source_category')!='OFFICIAL_NOT_DEFINED':raise ValueError('STOP_OWNER_NULL_REPORT_ONLY_POLICY_REQUIRED')
 kernel_spec=None;kernel_binding=dict(engine='NUMPY_DEFAULT')
 if args.cpp_depth_raster_manifest:
  if not (args.fresh_foreground_stop and os.environ.get('ROS_DOMAIN_ID')=='194' and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')=='LOCALHOST'):raise ValueError('CPP_RASTER_EXPLICIT_SIM_STOP_ONLY')
  manifest_path=args.cpp_depth_raster_manifest.resolve();kernel_spec=json.loads(manifest_path.read_text())
  if kernel_spec.get('scope')!='EXPLICIT_ISOLATED_SIM_NUMERICAL_TRIAL' or adopted.get('numerical_kernel_manifest')!=dict(path=str(manifest_path),sha256=sha(manifest_path)):raise ValueError('CPP_RASTER_ALLOCATION_MANIFEST_MISMATCH')
  expected_names={'expected_depth.py','raster_kernel.py','raster_bbox_f64.cpp','raster_bbox_f64.so'}
  if {Path(p['path']).name for p in kernel_spec['files']}!=expected_names or len(kernel_spec['files'])!=4:raise ValueError('CPP_RASTER_EXACT_FOUR_FILES_REQUIRED')
  canonical=root/'work/C-2-moveit/isaac_sim/depth_obstacles/novel_depth'
  for item in kernel_spec['files']:
   if Path(item['path']).resolve()!=canonical/Path(item['path']).name or sha(item['path'])!=item['sha256']:raise ValueError('CPP_RASTER_SOURCE_OR_LIBRARY_CHANGED')
  compile_ref=kernel_spec['compile_command']
  if sha(compile_ref['path'])!=compile_ref['sha256']:raise ValueError('CPP_RASTER_COMPILE_RECORD_CHANGED')
  flags=json.loads(Path(compile_ref['path']).read_text())['flags']
  if not {'-ffp-contract=off','-fno-fast-math','-fno-associative-math','-fno-tree-vectorize'}<=set(flags):raise ValueError('CPP_RASTER_EXACT_ARITHMETIC_FLAGS_REQUIRED')
 interval_spec=None;interval_binding=dict(engine='NUMPY_DEFAULT')
 if args.cpp_depth_interval_manifest:
  if not kernel_spec or not args.fresh_foreground_stop:raise ValueError('INTERVAL_KERNEL_EXPLICIT_SIM_RASTER_STOP_REQUIRED')
  interval_path=args.cpp_depth_interval_manifest.resolve();interval_spec=json.loads(interval_path.read_text())
  if interval_spec.get('scope')!='EXPLICIT_ISOLATED_SIM_NUMERICAL_TRIAL' or adopted.get('interval_kernel_manifest')!=dict(path=str(interval_path),sha256=sha(interval_path)):raise ValueError('INTERVAL_KERNEL_ALLOCATION_MANIFEST_MISMATCH')
  names={'qualification.py','interval_kernel.py','interval_f64.cpp','interval_f64.so'}
  if len(interval_spec['files'])!=4 or {Path(p['path']).name for p in interval_spec['files']}!=names:raise ValueError('INTERVAL_KERNEL_EXACT_FOUR_FILES_REQUIRED')
  canonical=root/'work/C-2-moveit/isaac_sim/depth_obstacles/novel_depth'
  for item in interval_spec['files']:
   if Path(item['path']).resolve()!=canonical/Path(item['path']).name or sha(item['path'])!=item['sha256']:raise ValueError('INTERVAL_KERNEL_SOURCE_OR_LIBRARY_CHANGED')
  compile_ref=interval_spec['compile_command']
  if sha(compile_ref['path'])!=compile_ref['sha256']:raise ValueError('INTERVAL_KERNEL_COMPILE_RECORD_CHANGED')
  flags=json.loads(Path(compile_ref['path']).read_text())['flags']
  if not {'-ffp-contract=off','-fno-fast-math','-fno-associative-math','-fno-tree-vectorize'}<=set(flags):raise ValueError('INTERVAL_KERNEL_EXACT_ARITHMETIC_FLAGS_REQUIRED')
 if args.same_runtime_worker_handoff and not (args.fresh_moveit_baseline and args.source_depth_baseline):raise ValueError('SAME_RUNTIME_SHADOW_REQUIRES_FRESH_SOURCE_MODE')
 if args.unlabelled_static_shadow and not (args.fresh_moveit_baseline and args.source_depth_baseline and args.direct_camera_display):raise ValueError('UNLABELLED_SHADOW_FRESH_SOURCE_DISPLAY_ONLY')
 if args.direct_camera_display and not args.source_depth_baseline:raise ValueError('MEMORY_DISPLAY_REQUIRES_EXISTING_BOUNDED_SOURCE_EXPORTER')
 if args.fresh_moveit_baseline and (args.dynamic_depth_hold or args.obstacle_path_shift_m or not args.transport_calculator):raise ValueError('FRESH_MOVEIT_BASELINE_REQUIRES_CALCULATOR_NO_DEPTH_STIMULUS')
 if not 0<=args.obstacle_path_shift_m<=.30 or (args.obstacle_path_shift_m and not args.static_depth_replan):raise ValueError('STATIC_DEMO_PATH_SHIFT_0_TO_300MM_ONLY')
 sys.path[:0]=[str(root/'work/C-2-moveit'),str(root/'work/C-2-moveit/isaac_sim/scripts')]
 created_early=False
 if args.dynamic_depth_hold:
  if os.environ.get('ROS_DOMAIN_ID')!='194' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')!='LOCALHOST':raise ValueError('SIM194_LOCALHOST_ONLY')
  out.mkdir(exist_ok=False);created_early=True
  from isaac_sim.depth_obstacles.helper_provenance import freeze
  selected_helpers=('current_geometry_fcl','online_cumotion_validity','dynamic_cumotion_inputs','depth_obstacle_envelope','prepare_cumotion_model','cumotion_timing','robot_control_integration.app.cumotion_transport','isaac_sim.real_execution.engine_receipt','isaac_sim.real_execution.native_boundary')
  if not args.initial_transport_demo_only:selected_helpers+=('cumotion_cspace_engine','cumotion_pose_engine','cumotion_axis_gate')
  freeze(selected_helpers,out/'first_import_helper_provenance',class_methods={'isaac_sim.real_execution.native_boundary':('NativeOnlineIPC.prepare_job','NativeOnlineIPC.commit_prepared_job')})
 hpath=root/'local_records/blocked_path_native25_20261014/handoff.json';handoff=json.loads(hpath.read_text())
 index=root/'local_records/step6_cumotion_20261014/blocked_path_cpu/handoff_to_moveit.json';package=json.loads(Path(json.loads(index.read_text())['package']['path']).read_text());report=package['calculation_report']
 if args.fresh_moveit_baseline:
  request=yaml.safe_load(Path(handoff['baseline_request']['path']).read_text())
  from prepare_gpu_scene import tcp_fk
  from sim_utils import matrix_pose
  packet=dict(start_tcp_pose=matrix_pose(tcp_fk(request['model_bundle'],request['planning_snapshot']['q_rad'],request['planning_snapshot']['grip_rad'])))
 else:
  from isaac_sim.depth_obstacles.fixed_transport_review import receive
  request,packet,_=receive(hpath,Path(report['path']),package['FCL_binary_sha256'])
 if os.environ.get('ROS_DOMAIN_ID')!='194' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')!='LOCALHOST':raise ValueError('SIM194_LOCALHOST_ONLY')
 runtime_sources=[Path(__file__),root/'work/C-2-moveit/isaac_sim/scripts/capture_sim_runtime.py',root/'work/C-2-moveit/isaac_sim/depth_obstacles/native_run_recording.py',root/'work/C-2-moveit/isaac_sim/scripts/d_sim_transport.py',root/'work/C-2-moveit/isaac_sim/scripts/live_cumotion_boundary.py',root/'work/C-2-moveit/isaac_sim/real_execution/native_boundary.py']
 if args.dynamic_depth_hold:runtime_sources.extend(root/'work/C-2-moveit'/p for p in ('isaac_sim/depth_obstacles/live_native_depth_owner.py','isaac_sim/depth_obstacles/camera_preview.py','isaac_sim/depth_obstacles/native_resume_sender.py','isaac_sim/depth_obstacles/resume_monitor.py','isaac_sim/depth_obstacles/prepared_job_selection.py','isaac_sim/depth_obstacles/prepared_admission_ipc.py','isaac_sim/depth_obstacles/helper_provenance.py','isaac_sim/depth_obstacles/live_depth_stop.py','isaac_sim/depth_obstacles/live_sensor_bundle.py','isaac_sim/depth_obstacles/rolling_owner_view.py','isaac_sim/depth_obstacles/prepare_static_prior.py','isaac_sim/config/live_static_depth_trial.policy.json','isaac_sim/depth_obstacles/complete_sensor_bundle.py','isaac_sim/depth_obstacles/bind_native_inventory.py','isaac_sim/real_execution/remaining_volume.py','isaac_sim/scripts/sim_tracking.py'))
 if args.dynamic_depth_hold:runtime_sources.extend(root/'work/C-2-moveit/isaac_sim/scripts'/name for name in ('current_geometry_fcl.py','online_cumotion_validity.py','dynamic_cumotion_inputs.py','depth_obstacle_envelope.py','prepare_cumotion_model.py','cumotion_timing.py'))
 if args.dynamic_depth_hold and not args.initial_transport_demo_only:runtime_sources.extend(root/'work/C-2-moveit/isaac_sim/scripts'/name for name in ('cumotion_cspace_engine.py','cumotion_pose_engine.py','cumotion_axis_gate.py'))
 if args.dynamic_depth_hold:runtime_sources.extend((root/'work/C-2-moveit/robot_control_integration/app/cumotion_transport.py',root/'work/C-2-moveit/isaac_sim/real_execution/engine_receipt.py'))
 if args.fresh_moveit_baseline:runtime_sources.extend([Path(__file__).with_name('run_depth_stop_native.py'),root/'work/C-2-moveit/isaac_sim/depth_obstacles/baseline_camera.py',root/'work/C-2-moveit/isaac_sim/depth_obstacles/camera_preview.py',args.transport_calculator])
 if args.unlabelled_static_shadow:runtime_sources.append(root/'work/C-2-moveit/isaac_sim/depth_obstacles/unlabelled_static_shadow.py')
 if args.current_stop_providers:runtime_sources.append(root/'work/C-2-moveit/isaac_sim/scripts/current_stop_providers.py')
 if args.compact_stop_handoff:runtime_sources.extend(root/'work/C-2-moveit/isaac_sim/scripts'/name for name in ('compact_stop_handoff.py','compact_points_guarded.py','projection_arrays.py'))
 if args.joint_current_inputs:runtime_sources.extend(root/'work/C-2-moveit/isaac_sim/scripts'/name for name in ('joint_compact_caller.py','live_current_cumotion_inputs.py','compact_point_receiver.py','dynamic_cumotion_inputs.py','conservative_stop_packet.py','moveit_stop_cumotion_inputs.py','initial_moveit_source.py','saved_initial_moveit_anchor.py'))
 if args.bounded_stop_video:runtime_sources.append(root/'work/C-2-moveit/isaac_sim/depth_obstacles/bounded_viewport_clip.py')
 if args.command_start_planning:runtime_sources.append(root/'work/C-2-moveit/isaac_sim/scripts/command_start_plan.py')
 if args.fresh_foreground_stop:runtime_sources.extend(root/'work/C-2-moveit'/r for r in ('isaac_sim/depth_obstacles/novel_depth/foreground_stop_notice.py','isaac_sim/real_execution/fresh_foreground_cancel.py'))
 if args.source_depth_baseline:runtime_sources.extend(root/'work/C-2-moveit/isaac_sim/depth_obstacles'/name for name in ('projection.py','novel_depth/geometry.py','novel_depth/qualification.py','novel_depth/interval_kernel.py','novel_depth/expected_depth.py','novel_depth/difference.py','novel_depth/point_bounds.py','novel_depth/replay_saved.py'))
 if args.fresh_moveit_baseline:runtime_sources.extend(root/'work/C-2-moveit/isaac_sim/scripts'/name for name in ('plan_only.py','settled_moveit_source.py','controller_start_observation.py','controller_start_inputs.py','moveit_command_timing.py'))
 if args.fresh_moveit_baseline:
  runtime_sources.extend(root/'work/C-2-moveit/isaac_sim/scripts'/name for name in ('prepare_gpu_scene.py','prepare_cpu_model.py','prepare_cumotion_model.py','cumotion_geometry.py','sim_utils.py','stop_curve.py','stop_fcl.py'))
  runtime_sources.append(root/'local_records/step6_cumotion_20261014/offline_stop_candidate/libstop_fcl.so')
 if kernel_spec:runtime_sources.extend([*(Path(p['path']) for p in kernel_spec['files']),args.cpp_depth_raster_manifest.resolve(),Path(kernel_spec['compile_command']['path'])])
 if args.sim_stop_owner_limits:runtime_sources.extend([root/'work/C-2-moveit/isaac_sim/scripts/sim_stop_owner.py',root/'work/C-2-moveit/isaac_sim/real_execution/conservative_stop_evidence.py',args.sim_stop_owner_limits.resolve()])
 if interval_spec:runtime_sources.extend([*(Path(p['path']) for p in interval_spec['files']),args.cpp_depth_interval_manifest.resolve(),Path(interval_spec['compile_command']['path'])])
 consumer_report=None;consumer_callback=None
 if args.same_runtime_worker_handoff:
  consumer_report=json.loads(args.same_runtime_worker_handoff.read_text())
  if consumer_report['status']!='READY_FOR_MI_SHADOW_INTEGRATION':raise ValueError('SAME_RUNTIME_CONSUMER_NOT_READY')
  for ref in [consumer_report['caller_example'],*consumer_report['api_refs']]:
   if sha(ref['path'])!=ref['sha256']:raise ValueError('SAME_RUNTIME_SOURCE_PIN_CHANGED')
  runtime_sources.extend(Path(ref['path']) for ref in [consumer_report['caller_example'],*consumer_report['api_refs']])
 source_pins={str(p):sha(p) for p in runtime_sources}
 if not created_early:out.mkdir(exist_ok=False)
 (out/'executed_runner.py').write_bytes(Path(__file__).read_bytes());save(out/'input_pins.json',dict(handoff= dict(path=str(hpath),sha256=sha(hpath)),delivery=dict(path=str(index),sha256=sha(index)),package=package,source_sha256=sha(__file__),runtime_source_pins=source_pins,new_D_receipt=None if args.fresh_moveit_baseline else packet,initial_trajectory_source='FRESH_MOVEIT_REQUIRED' if args.fresh_moveit_baseline else 'ARCHIVED_CUMOTION'))
 if not args.fresh_moveit_baseline:save(out/'CPU_receive.json',dict(status='NEW_1087_POINT_SDK_RECEIVED_NATIVE_NOT_STARTED',points=len(packet['trajectory']['points']),trajectory_digest=packet['trajectory_digest'],old_baseline_never_executed=True,hardware_execution_allowed=False))
 if args.prepare_only:return
 allocation_path=args.allocation.resolve() if args.allocation else root/('management/allocations/CAMERA_DIRECT_DISPLAY_FOLLOWUP.json' if args.direct_camera_display else ('management/MOVEIT_DEPTH_STOP_SINGLE_SIM_ALLOCATION.json' if args.fresh_moveit_baseline else 'management/GPU_RESOURCE_HANDOFF.json'))
 allocation=json.loads(allocation_path.read_text())
 if args.allocation and (allocation.get('allowed') is not True or allocation.get('scope') not in ('FRESH_MOVEIT_NO_OBSTACLE_MOVING_WRIST_SOURCE_EXPORT_AND_MEMORY_DISPLAY_SHADOW','CORRECT_SOURCE_PAIR_EVENT_CAPTURE_AND_MAIN_LOOP_WAIT_NO_OBSTACLE_SHADOW','ACTUAL_UNLABELLED_STATIC_FOREGROUND_SHADOW_NO_DETECTOR_CANCEL_NO_REPLAN','SIM_FRESH_FOREGROUND_CONSERVATIVE_STOP_SAME_UUID_NO_REPLAN') or not (args.fresh_moveit_baseline and args.source_depth_baseline and args.direct_camera_display)):raise ValueError('EXPLICIT_ALLOCATION_SCOPE_MISMATCH')
 if args.unlabelled_static_shadow and allocation.get('scope') not in ('ACTUAL_UNLABELLED_STATIC_FOREGROUND_SHADOW_NO_DETECTOR_CANCEL_NO_REPLAN','SIM_FRESH_FOREGROUND_CONSERVATIVE_STOP_SAME_UUID_NO_REPLAN'):raise ValueError('UNLABELLED_STATIC_SCENARIO_NOT_ALLOCATED')
 if not args.unlabelled_static_shadow and allocation.get('scope')=='ACTUAL_UNLABELLED_STATIC_FOREGROUND_SHADOW_NO_DETECTOR_CANCEL_NO_REPLAN':raise ValueError('STATIC_SHADOW_ALLOCATION_REQUIRES_EXPLICIT_SCENARIO')
 if args.direct_camera_display and (allocation.get('allowed') is not True or json.loads((root/'management/GPU_RESOURCE_HANDOFF.json').read_text()).get('gpu_owner')!='MoveIt-Isaac'):raise ValueError('DIRECT_DISPLAY_GPU_ALLOCATION_NOT_ACTIVE')
 if allocation.get('owner' if args.fresh_moveit_baseline else 'gpu_owner')!='MoveIt-Isaac':raise ValueError('MANAGEMENT_GPU_RETURN_REQUIRED')
 if args.dynamic_depth_hold and allocation.get('dynamic_native_producer_allowed') is not True:raise ValueError('DYNAMIC_NATIVE_GPU_SCOPE_NOT_ALLOCATED')
 recorder=None
 native=root/'local_records/design_cycle_stage4_1_20261014/wrist_depth25_native_rest'
 scene_out=out/'scene'
 drive=json.loads((native/'runtime_reference.json').read_text())['gripper_drive']
 runtime=SimpleNamespace(capture_window_title='Seeun / Fixed obstacle / cuMotion native transport',model_bundle=Path(request['model_bundle']['bundle_path']),archive_postures=None,capture_setup=out/'setup.current.json',auto_start=False,capture_scene=scene_out,capture_interactive=True,capture_delay_s=2.,sim_transport=True,depth_owner_test=True,transport_engine='cumotion',wrist_runtime_reference=dict(controller_config_path=out/'controllers.reference.yaml',gripper_drive=drive),fixed_checkpoint=dict(q_rad=request['planning_snapshot']['q_rad'],grip_rad=request['planning_snapshot']['grip_rad']),fixed_obstacle_prim_paths=['/World/Environment/PathBlockingStimulus'])
 runtime.minimal_evidence_recording=recording_minimal
 runtime.command_start_planning=args.command_start_planning
 runtime.fresh_foreground_stop=args.fresh_foreground_stop
 runtime.foreground_stop_max_source_age_s=args.foreground_stop_max_source_age_s
 if args.fresh_moveit_baseline:
  runtime.transport_engine='moveit';runtime.transport_calculator=args.transport_calculator;runtime.fresh_moveit_baseline=True
  runtime.source_render_every_physics_steps=args.source_render_every_physics_steps;runtime.sim_command_profile=args.sim_command_profile
  runtime.source_depth_baseline=args.source_depth_baseline;runtime.source_transport_wall_budget_s=180. if args.source_depth_baseline else None;runtime.fixed_obstacle_prim_paths=[];runtime.auto_start=False;runtime.capture_window_title='Seeun / Fresh MoveIt / Same D / Baseline A'
 session='fixed-native-'+uuid.uuid4().hex;cache={};recording_holder={}
 def check_physical(objects):
  if args.fresh_moveit_baseline:
   from d_sim_transport import check_world
   return check_world(baseline,objects)
  return check_fixed_physical_world(baseline,objects,gt)
 def restore(world,robot,node,sample,tick,goal,statuses):
  # Native constant hold establishes an observed controller reference. This
  # is not execution of the baseline trajectory or an invented zero readout.
  row=sample();goal('arm_controller',['joint_'+str(i) for i in range(1,7)],row['q_rad'],json.loads((out/'setup.current.json').read_text())['initial_q_rad'],1.)
  cfg=json.loads((root/'work/C-2-moveit/isaac_sim/config/contact.sim.json').read_text());goal('gripper_controller',['rg2_finger_joint'],[sample()['grip_rad']],[cfg['gripper']['close_q_rad']],8.,operation_wall_timeout_s=args.bootstrap_gripper_wall_budget_s)
  # Fresh MoveIt begins at the actual closed-gripper pickup state. The
  # historical CU/checkpoint mode retains its dedicated lift/return proof.
  if not args.fresh_moveit_baseline:
   pickup_z=sample()['body_z_m'];setup_doc=json.loads((out/'setup.current.json').read_text())
   from stop_fcl import StopScene,check_stop
   def proof_move(target):
    current=sample();actual_req=copy.deepcopy(request);actual_req['attachment']=current['attachment'];actual_req['planning_snapshot']['grip_rad']=current['grip_rad']
    delta=np.array(target)-current['q_rad'];proof_points=[]
    for t in np.linspace(0,3.,61):
     u=float(t/3.);blend=10*u**3-15*u**4+6*u**5;vel=(30*u**2-60*u**3+30*u**4)/3.;acc=(60*u-180*u**2+120*u**3)/9.
     proof_points.append(dict(time_from_start_s=float(round(t,9)),positions_rad=(np.array(current['q_rad'])+blend*delta).tolist(),velocities_rad_s=(vel*delta).tolist(),accelerations_rad_s2=(acc*delta).tolist()))
    proof_curve=dict(joint_names=['joint_'+str(i) for i in range(1,7)],points=proof_points)
    lib=root/'local_records/step6_cumotion_20261014/offline_stop_candidate/libstop_fcl.so';collision_scene=StopScene(actual_req,lib,sha(lib))
    try:
     # Existing pickup mode permits the selected block's support contact with
     # its own supply board. Keep all meshes/world; retain this phase-specific
     # allowance in the proof record, never in the transport request.
     collision_scene.pairs=[(a,b) for a,b in collision_scene.pairs if not (a['kind']=='held' and b['id']=='SupplyBoard') and not (b['kind']=='held' and a['id']=='SupplyBoard')]
     proof_audit=check_stop(collision_scene,proof_curve);proof_audit['pickup_only_selected_supply_board_support_contact_allowed']=True
    finally:collision_scene.close()
    save(out/('proof_move_'+str(len(list(out.glob('proof_move_*.json'))))+'.json'),proof_audit)
    if not proof_audit['success']:raise ValueError('RESTORE_GRASP_PROOF_FCL_REJECTED')
    goal('arm_controller',proof_curve['joint_names'],current['q_rad'],target,3.)
   proof_move(setup_doc['lift_q_rad'])
   if sample()['body_z_m']-pickup_z<.015:raise ValueError('RESTORED_GRASP_DID_NOT_LIFT_ACTUAL_BODY')
   proof_move(setup_doc['initial_q_rad'])
  samples=deque();end=world.current_time+2.
  while world.current_time<end:
   tick();samples.append(sample())
   while samples[-1]['time_s']-samples[0]['time_s']>1.:samples.popleft()
  if any(command_counts(statuses).values()):raise ValueError('RESTORED_CHECKPOINT_COMMAND_ACTIVE')
  verified_stop(list(samples));check_physical(read_scene_geometry(omni.usd.get_context().get_stage(),seed)[0])
  for row in samples:
   if row['contact_fingers']!=['rg2_left_inner_finger','rg2_right_inner_finger']:raise ValueError('RESTORED_NATIVE_CONTACT_GRASP_UNCONFIRMED')
  save(out/'restore_observations.json',list(samples));cache.update(world=world,robot=robot,node=node)
  grasp_validation=dict(scope='ACTUAL_POSTGRASP_STATIC_CONTACT_STOP_NO_LIFT_PROOF' if args.fresh_moveit_baseline else 'RESTORED_NATIVE_CONTACT_HOLD_OBSERVED_NOT_NEW_LIFT_TEST',initial_lift_return_executed=not args.fresh_moveit_baseline,lift_proof_verified=not args.fresh_moveit_baseline,transport_grasp_continuity='CHECKED_SEPARATELY_BY_EXISTING_D_DURING_TRANSPORT',source_checkpoint=handoff['checkpoint'],checkpoint_role='INITIAL_SETUP_REFERENCE_ONLY_CURRENT_SAMPLE_IS_OBSERVED',sample=samples[-1],evidence_ref=str(out/'restore_observations.json'))
  save(out/'bootstrap_grasp_validation.json',grasp_validation)
  return samples,grasp_validation
 runtime.checkpoint_restore_hook=restore
 def post_grasp(app,stage,world,robot,tick,seed,motion,controls,sample,statuses,folder,model):
  nonlocal recorder
  cache['sample']=sample
  if args.foreground_python_switch_interval_ms is not None:
   cache['python_switch_interval_previous_s']=sys.getswitchinterval()
   requested=args.foreground_python_switch_interval_ms/1000;sys.setswitchinterval(requested)
   save(out/'python_switch_interval_runtime.json',dict(scope='EXPLICIT_FRESH_FOREGROUND_SIM_EXISTING_PYTHON_THREAD_SCHEDULING_ONLY',previous_s=cache['python_switch_interval_previous_s'],requested_s=requested,actual_s=sys.getswitchinterval(),session_id=session,applied_source_s=float(world.current_time),applies_to_all_Python_threads=True,source_clock_or_physics_dt_changed=False,worker_count_changed=False,controller_limits_changed=False,OS_switch_timing_guaranteed=False))
  if args.fresh_moveit_baseline:cache['settled_samples']=deque(copy.deepcopy(controls['position_observations']))
  capture=configure_view(stage,base,gt['pose']['xyz_m'],request['planning_snapshot']['tcp_pose']['xyz_m'] if 'tcp_pose' in request['planning_snapshot'] else packet['start_tcp_pose']['xyz_m'],request['goal']['xyz_m'])
  recorder=NativeRunRecording(out/'native_recording',None if recording_minimal else capture);recording_holder['recorder']=recorder
  if args.bounded_stop_video:
   from isaac_sim.depth_obstacles.bounded_viewport_clip import BoundedViewportClip
   recorder.clip=BoundedViewportClip(recorder.folder/'stop_clip',capture)
  if not args.fresh_moveit_baseline:
   paths=json.loads(Path(package['TCP_paths']['path']).read_text());save(out/'comparison_paths_source.json',paths)
   # Keep calculation/audit data as files; no guide geometry in the sensor Stage.
   old=yaml.safe_load(Path(package['baseline_result']['path']).read_text())
   blockage=json.loads((root/'local_records/blocked_path_native25_20261014/baseline_GT_blockage.json').read_text())
   hit_time=blockage['baseline_checks']['time_s'];checked=old['checked_states']
   nearest=min(range(len(checked)),key=lambda i:abs(checked[i]['time_from_start_s']-hit_time))
   save(out/'baseline_collision_overlay.json',dict(scope='FIRST_FCL_COLLISION_NEIGHBORHOOD_FILE_AUDIT_ONLY_NOT_EXECUTED',stage_geometry_created=False,source=handoff['baseline_request'],first_collision_time_s=hit_time,collision_pair=blockage['baseline_checks']['collision_pair'],highlighted_state_indices=[max(0,nearest-5),min(len(checked),nearest+6)-1]))
  selected=next(o for o in seed['world_objects'] if o['id']==request['planning_snapshot']['selected_slot_id']);source_board=next(o for o in seed['world_objects'] if o['id']=='SupplyBoard')
  def record_support(value):
   with (out/'source_support_observations.jsonl').open('a') as stream:stream.write(json.dumps(value)+'\n')
  support_event,support_contact=source_support_departure(selected['prim_path'],source_board['prim_path'],sample,record_support)
  runtime.source_support_contact=support_contact
  if args.fresh_moveit_baseline:support_event('SUBMISSION_INTENT',{},sample()['time_s'])
  def transport_event(kind,payload,stamp):
   support_event(kind,payload,stamp);recorder.event(kind,payload,stamp)
   if args.unlabelled_static_shadow and _unlabelled_scenario is not None:_unlabelled_scenario.event(kind,payload,stamp)
   if kind=='GOAL_ACCEPTED' and payload.get('accepted') and cache.get('camera') is not None:cache['camera'].recording_accepted_source_s=stamp
   if args.sim_stop_owner_limits:
    if kind=='SUBMISSION_INTENT':
     from sim_stop_owner import SimStopOwnerPublication
     from plan_only import digest
     publication=SimStopOwnerPublication(out/'D_stop_owner',cache['camera'].foreground_stop_binding,out/'transport_plan/TRANSPORT.request.yaml',out/'actual_native_wire.json')
     if digest(publication.request)!=digest(payload['request']) or digest(publication.wire)!=payload['trajectory_digest']:raise ValueError('STOP_OWNER_SELECTED_REQUEST_OR_WIRE_CHANGED')
     cache['stop_publication']=publication
    publication=cache.get('stop_publication')
    if publication is not None:
     if kind=='GOAL_ACCEPTED' and payload.get('accepted'):publication.accepted(payload['goal_id'],stamp)
     elif kind=='CANCEL_REQUEST' and payload.get('conservative_stop') and payload.get('request_issued'):publication.cancel_requested(payload['goal_id'],stamp)
     elif kind=='GOAL_RESULT':publication.terminal_result(payload['goal_id'],payload['status'],payload['error_code'],stamp)

  runtime.transport_hooks=dict(event=transport_event,sample=recorder.sample,stop_requested=lambda:False,completed=recorder.completed)
  from unique_identifier_msgs.msg import UUID
  runtime.transport_hooks['goal_uuid']=UUID(uuid=list(uuid.uuid4().bytes))
  if args.fresh_moveit_baseline:
   from isaac_sim.depth_obstacles.baseline_camera import BaselineCamera
   context=dict(world=world,robot=robot,node=cache['node'],sample=sample,model_bundle=runtime.model_bundle,source_scene=out/'capture/scene.json',source_state=out/'capture/post_grasp_state.json',native_tick=tick) if args.source_depth_baseline else None
   if context and consumer_callback is not None:context['same_runtime_consumer_handoff']=consumer_callback
   if context and args.sim_stop_owner_limits:
    def publish_stopped_source(folder,frame):
     publication=cache.get('stop_publication')
     if publication is None or publication.status_ref is None:return
     try:
      from sim_stop_owner import ref
      from isaac_sim.real_execution.conservative_stop_evidence import build_conservative_stop_owner_evidence
      from capture_sim_scene import verified_stop
      return publication.publish_frame(ref(folder/'frame_input.json'),frame,now_s=cache['camera'].current_source_observation['source_s'],limits=stop_owner_limits,limits_ref=ref(args.sim_stop_owner_limits),builder=build_conservative_stop_owner_evidence,verified_stop=verified_stop)
     except Exception as exc:
      save(folder/'D_stop_owner_HOLD.json',dict(status='HOLD_CURRENT_STOP_OWNER_NOT_PUBLISHED',reason=str(exc),error_type=type(exc).__name__,SDK_READY=False,execution_allowed=False,hardware_execution_allowed=False))
    context['publish_stopped_source']=publish_stopped_source
   if context:context.update(numerical_interval_kernel_binding=interval_binding,numerical_kernel_binding=kernel_binding,minimal_evidence_recording=recording_minimal,evidence_budget_bytes=(args.full_diagnostic_budget_mib or 1024)*1024**2,fresh_foreground_stop=args.fresh_foreground_stop)
   if context and args.unlabelled_static_shadow:context.update(unlabelled_static_shadow=True,qualification_report_path=str(args.qualification_report_path.resolve() if args.qualification_report_path else root/'management/reports/depth_native09_static_shadow_qualification.json'),pre_obstacle_handoff_public_path=str(args.pre_obstacle_handoff_public_path.resolve() if args.pre_obstacle_handoff_public_path else root/'local_records/moveit_native09_unlabelled_static_shadow_20261015/native09/pre_obstacle_handoff.json'))
   cache['camera']=BaselineCamera(app,stage,seed,out,session,source_context=context,direct_display=args.direct_camera_display,detection_only=args.direct_camera_display)
   if args.current_stop_providers:
    from current_stop_providers import CurrentStopProviders
    runtime.transport_hooks['get_stop_publication']=lambda:cache.get('stop_publication')
    cache['current_stop_providers']=CurrentStopProviders(cache['camera'],lambda:cache.get('stop_publication'),
        lambda:runtime.transport_hooks.get('current_stop_readout'),verified_stop,stop_owner_limits)
    # Read-only callbacks become available to the reviewed CU caller. Missing
    # compact point or complete same-source raw link still yields WAIT.
    runtime.current_stop_capture_provider=cache['current_stop_providers'].capture_provider
    runtime.current_stop_source_clock_provider=cache['current_stop_providers'].source_clock_provider
    if args.compact_stop_handoff:
     from compact_stop_handoff import CompactStopHandoff,RUNTIME
     compact=CompactStopHandoff(runtime.current_stop_source_clock_provider,runtime.current_stop_capture_provider,
         scope=RUNTIME,receipt_folder=out/'compact_stop_receipts')
     cache['compact_stop_handoff']=compact
     cache['camera'].source_context['compact_stop_handoff']=compact
     runtime.current_compact_stop_input_provider=compact.current
     if args.joint_current_inputs:
      from joint_compact_caller import JointCompactCaller
      joint=JointCompactCaller(runtime,out/'joint_current_input',lambda:cache.get('joint_initial_source_refs'))
      cache['joint_compact_caller']=joint
      cache['camera'].source_context['joint_compact_input_contact']=joint.poll
   if context:
    runtime.source_render_hooks=cache['camera']
    runtime.source_depth_flush_hook=cache['camera'].flush
    def service_audit_ui():
     # Existing World.render disables playSimulations during app.update. Verify
     # actual counters/time/q too; owner equality and final D guards still run.
     if not app.is_running() or (out/'stop.request').exists() or (out/'shutdown.request').exists():raise ValueError('AUDIT_UI_SERVICE_INTERRUPTED')
     camera=cache['camera'];before=camera.native_stamp();q_before=robot.get_joint_positions().copy()
     camera.before_render();world.render();camera.after_render();after=camera.native_stamp()
     if (before['native_physics_step_index']!=after['native_physics_step_index'] or before['native_simulation_time_s']!=after['native_simulation_time_s'] or before['world_time_s']!=after['world_time_s'] or not np.array_equal(q_before,robot.get_joint_positions())):raise ValueError('AUDIT_RENDER_ONLY_SERVICE_ADVANCED_PHYSICS_OR_STATE')
     camera.source_sample(dict(time_s=float(world.current_time)),{})
    global _audit_ui_service
    _audit_ui_service=service_audit_ui
   from settled_moveit_source import PHASE,publish_settled_source,stop_history_for_readout
   def planning_stamp():
    from isaacsim.core.simulation_manager import SimulationManager
    t=SimulationManager._simulation_manager_interface.get_current_time()
    return dict(native_current_reference_time=[int(t.numerator),int(t.denominator)],native_simulation_time_s=float(SimulationManager.get_simulation_time()),native_physics_step_index=int(SimulationManager.get_num_physics_steps()),world_time_s=float(world.current_time),wall_monotonic_s=time.monotonic())
   from controller_start_inputs import PARAMETER_NAMES,record_controller_parameters,publish_completed_hold_pvt
   runtime.fresh_controller_parameter_names=list(PARAMETER_NAMES)
   def record_parameters(names,values):
    from controller_start_observation import loaded_controller_libraries
    stamp=planning_stamp();serial=cache.get('controller_parameter_sequence',0)+1;cache['controller_parameter_sequence']=serial
    identity=dict(session_id=session,clock_epoch=0,clock_basis='SIM_TIME',source_stamp_s=stamp['world_time_s'],physics_step_index=stamp['native_physics_step_index'],readout_phase='MAIN_LOOP_GET_PARAMETERS_RESPONSE',native_stamp=stamp)
    parent=record_controller_parameters(out/'controller_parameter_observations'/f'{serial:03d}',names,values,identity,loaded_controller_libraries())
    after=planning_stamp()
    if any(stamp[k]!=after[k] for k in ('native_current_reference_time','native_simulation_time_s','native_physics_step_index','world_time_s')):raise ValueError('PARAMETER_RESPONSE_RECORD_ADVANCED_PHYSICS')
    cache['controller_parameter_ref']=parent
    return parent
   runtime.record_fresh_controller_parameters=record_parameters
   def settled_plan_inputs(label):
    # Render/Fabric flush first; all planning fields then come from one main
    # readout bracket with no app.update/tick/spin/worker acquisition inside.
    if _audit_ui_service is not None:_audit_ui_service()
    else:
     flush_before=planning_stamp();q_before=robot.get_joint_positions().copy();world.render();flush_after=planning_stamp()
     if any(flush_before[k]!=flush_after[k] for k in ('native_current_reference_time','native_simulation_time_s','native_physics_step_index','world_time_s')) or not np.array_equal(q_before,robot.get_joint_positions()):raise ValueError('SETTLED_SOURCE_RENDER_FLUSH_ADVANCED_PHYSICS')
    before=planning_stamp();first=sample()
    objects,alignment,tcp=read_scene_geometry(stage,seed)
    last=sample();objects_after,alignment_after,tcp_after=read_scene_geometry(stage,seed);after=planning_stamp()
    value=dict(session_id=session,clock_epoch=0,clock_basis='SIM_TIME',source_stamp_s=first['time_s'],physics_step_index=before['native_physics_step_index'],readout_phase=PHASE,before_stamp=before,after_stamp=after,observation=first,observation_after=last,q_rad=first['q_rad'],grip_rad=first['grip_rad'],tcp_pose=first['tcp_pose'],attachment_tcp_to_block=first['attachment'],world_objects=objects,frame_alignment=alignment,geometry_before=dict(world_objects=objects,frame_alignment=alignment,T_base_tool=tcp.tolist()),geometry_after=dict(world_objects=objects_after,frame_alignment=alignment_after,T_base_tool=tcp_after.tolist()),geometry_readout_T_base_tool=tcp.tolist(),observed_TCP_is_nominal_FK=False,camera_source_event_retagged=False)
    serial=cache.get('settled_source_sequence',0)+1;cache['settled_source_sequence']=serial
    source_folder=out/'settled_planning_sources'/f'{serial:03d}_{label}'
    # Preserve the actual pair before source/STOP validation can reject it.
    # The producer owns history selection for every planner/FCL/send readout;
    # do not run camera/recording hooks twice or substitute an older sample.
    raw_history=list(cache['settled_samples'])
    raw_path=source_folder.with_suffix('.stop_association.raw.json')
    source_folder.parent.mkdir(parents=True,exist_ok=True)
    save(raw_path,dict(label=label,current_readout=value,original_stop_history=raw_history,native_statuses=copy.deepcopy(statuses)))
    try:
     stop_view,selection=stop_history_for_readout(value,raw_history)
     save(source_folder.with_suffix('.stop_association.selection.json'),selection)
     bundle=publish_settled_source(source_folder,value,stop_samples=stop_view,statuses=statuses,seed=seed,motion=motion,model_bundle=model,controls=controls)
    except Exception as exc:
     save(source_folder.with_suffix('.stop_association.failure.json'),dict(error=str(exc),error_type=type(exc).__name__,raw_inputs=dict(path=str(raw_path),sha256=sha(raw_path)),cache_committed=False))
     raise
    cache['settled_samples']=deque(stop_view)
    from controller_start_observation import controller_start_observation,loaded_controller_libraries
    config_path=out/'controllers.reference.yaml'
    start=controller_start_observation(value,yaml.safe_load(config_path.read_text()),dict(path=str(config_path),sha256=sha(config_path)),loaded_controller_libraries())
    save(source_folder/'controller_start_observation.json',start)
    bundle['controller_start_observation_ref']=dict(path=str(source_folder/'controller_start_observation.json'),sha256=sha(source_folder/'controller_start_observation.json'))
    bundle.update(publish_completed_hold_pvt(source_folder,value,bundle,cache.get('controller_parameter_ref'),statuses,loaded_controller_libraries()))
    return bundle
   runtime.settled_fresh_plan_inputs=settled_plan_inputs
   old_sample=runtime.transport_hooks['sample']
   def record_owner_sample(row,statuses):
    old_sample(row,statuses)
    if cache.get('stop_publication') is not None:cache['stop_publication'].observe(recorder.latest_sample,command_counts(statuses))
   def record_frame(row,statuses):
    history=cache['settled_samples']
    if history and row['time_s']<history[-1]['time_s']:raise ValueError('SETTLED_SOURCE_HISTORY_CLOCK_REVERSED')
    if not history or row['time_s']>history[-1]['time_s']:history.append(copy.deepcopy(row))
    while history[-1]['time_s']-history[0]['time_s']>1:history.popleft()
    record_owner_sample(row,statuses)
    cache['camera'].sample(row,statuses)
    if args.unlabelled_static_shadow:_unlabelled_scenario.sample(row)
   runtime.transport_hooks['sample']=record_frame
   if args.sim_stop_owner_limits:cache['camera'].source_context['post_stop_owner_sample']=record_owner_sample
   if args.unlabelled_static_shadow:
    from isaac_sim.depth_obstacles.unlabelled_static_shadow import UnlabelledStaticShadow
    global _unlabelled_scenario
    _unlabelled_scenario=UnlabelledStaticShadow(out,stage,seed,cache['camera'].profile)
    # Publish actual new-session baseline before planner/actor, while original
    # native HOLD/physics/source keep advancing and existing guards remain.
    import omni.timeline
    wait_result=wait_pre_obstacle_baseline(app,omni.timeline.get_timeline_interface(),tick,sample,statuses,record_frame,cache['camera'].shadow_error_model,out)
    save(out/'pre_obstacle_qualification_wait.json',wait_result)
    if args.fresh_foreground_stop:
     cache['camera'].configure_foreground_stop_binding()
     runtime.transport_hooks['foreground_stop_binding']=lambda:dict(cache['camera'].foreground_stop_binding)
     runtime.transport_hooks['foreground_stop_entry']=lambda:cache['camera'].latest_foreground_entry
     def retain_stop_entry(entry,receipt):
      # Strong lease only; no file or array work on the cancel-send path.
      cache['camera'].trigger_evidence_product=entry
      cache['camera'].trigger_stop_receipt=receipt
     runtime.transport_hooks['retain_foreground_stop_entry']=retain_stop_entry
     def post_stop_probe(app,stage,world,robot,tick,seed,motion,controls,sample,statuses,out,model,result):
      if not result.get('conservative_stop_verified'):return
      if args.sim_stop_owner_limits:cache['stop_publication'].verified_stop(out/'transport_status.json')
      from capture_sim_scene import command_counts
      from d_sim_transport import check_live
      from capture_sim_scene import verified_stop
      actual_request=yaml.load((out/'transport_plan/TRANSPORT.request.yaml').read_text(),Loader=yaml.CSafeLoader)
      monitor=dict(binding=result['binding'] if 'binding' in result else json.loads((out/'transport.latest_context.json').read_text()),attachment=actual_request['attachment'])
      start=float(world.current_time);deadline=time.monotonic()+30;frames={}
      loaded={name:start for name in result['final_observation']['contact_fingers']}
      before=planning_stamp()
      # D's finally paused physics after cancel; resume sensor HOLD only.
      # The canceled goal is never resubmitted. Drain the native play barrier
      # before the next non-rendered physics step (same source-order repair).
      import omni.timeline
      omni.timeline.get_timeline_interface().play();app.update()
      while app.is_running() and time.monotonic()<deadline and len(frames)<2:
       tick();row=sample();record_frame(row,statuses)
       for name in row['contact_fingers']:loaded[name]=row['time_s']
       row['contact_last_loaded_s']=dict(loaded)
       if any(command_counts(statuses).values()):raise ValueError('POST_STOP_SOURCE_HOLD_COMMAND_GUARD')
       check_live(monitor,json.loads((out/'transport.latest_context.json').read_text()),row,contact_grace_s=.02)
       latest=cache['camera'].completed[-1] if cache['camera'].completed else None
       if latest and latest['source_associated'] and latest['source_stamp_s']>start:frames[latest['source_stamp_s']]=latest['frame_input']
      after=planning_stamp()
      save(out/'post_stop_source_progress.json',dict(start_source_s=start,end_source_s=float(world.current_time),before_native=before,after_native=after,original_new_frames=list(frames.values()),sensor_and_source_progress_verified=len(frames)>=2 and after['native_physics_step_index']>before['native_physics_step_index'],command_counts=command_counts(statuses),holding_contact_fingers=sample()['contact_fingers'],post_probe_stop_metrics=verified_stop(list(cache['settled_samples'])),automatic_resume=False))
     runtime.after_transport_hook=post_stop_probe

  if args.dynamic_depth_hold:
   from isaac_sim.depth_obstacles.live_native_depth_owner import LiveNativeDepthOwner
   args.mount_profile=root/'work/C-2-moveit/isaac_sim/depth_obstacles/config/rokey_published_raw_depth_nominal.json';args.model_bundle=Path(request['model_bundle']['bundle_path']);args.out=out
   cache['live_owner']=LiveNativeDepthOwner(out,request,packet,session,args.model_bundle,args.mount_profile)
   cache['live_owner'].attach(args,runtime,app,stage,world,robot,tick,seed,motion,controls,sample,statuses,folder,model)
 runtime.wrist_depth_hook=post_grasp
 if args.fresh_moveit_baseline:
  def command_valid_suffix(run,new_request,raw_result_path,raw_packet):
   from moveit_command_timing import retime_moveit_command
   run=Path(run);packet_path=run/'D_candidate.json'
   if json.loads(packet_path.read_text())!=raw_packet:raise ValueError('RAW_MOVEIT_PACKET_PARENT_CHANGED')
   from plan_only import prepare_d_candidate
   if yaml.load((run/'TRANSPORT.request.yaml').read_text(),Loader=yaml.CSafeLoader)!=new_request:raise ValueError('RAW_MOVEIT_REQUEST_PARENT_CHANGED')
   raw_result=yaml.load(Path(raw_result_path).read_text(),Loader=yaml.CSafeLoader)
   if prepare_d_candidate(raw_result,new_request,raw_packet['binding'])!=raw_packet:raise ValueError('RAW_MOVEIT_RESULT_PACKET_LINEAGE_CHANGED')
   parents={name:dict(path=str(Path(path).resolve()),sha256=sha(path)) for name,path in (('request',run/'TRANSPORT.request.yaml'),('result',raw_result_path),('packet',packet_path))}
   artifacts=retime_moveit_command(run/'command_timing',new_request,raw_packet,parents,command_profile=args.sim_command_profile)
   if args.joint_current_inputs:
    # These are actual D retimer input refs selected above, not inferred paths.
    cache['joint_initial_source_refs']=dict(scope='ORIGINAL_MOVEIT_SELECTED_SOURCE_REFS_NOT_CURRENT_OWNER',**parents)
    save(out/'joint_initial_source_refs.json',cache['joint_initial_source_refs'])
   return artifacts
  runtime.command_valid_moveit_suffix=command_valid_suffix
 def receive_prepared(run):
  save(run/'source_calculation.json',report);return request,packet,Path(package['new_FCL']['path'])
 limits=dict(q_tolerance_rad=.002,grip_tolerance_rad=.002,attachment_translation_tolerance_m=.0005,attachment_rotation_tolerance_rad=.005,world_translation_tolerance_m=.0005,world_rotation_tolerance_rad=.005)
 def build_native(row,history,statuses):
  import rclpy
  verify_loaded_functions()
  # Drain queued observations without advancing physics. Preserve message
  # source stamps; do not relabel an old controller sample as current.
  for _ in range(64):rclpy.spin_once(cache['node'],timeout_sec=0)
  row=cache['sample']()
  if len(history)<2:raise ValueError('NEED_ACTUAL_INITIAL_ACCELERATION')
  dt=history[-1]['time_s']-history[-2]['time_s'];v=np.array(row['velocity_rad_s'][:6]);a=(v-np.array(history[-2]['velocity_rad_s'][:6]))/dt
  refs=row.get('tracking',{}).get('controller_states',[])
  desired=None
  if refs:
   latest=refs[-1];r=latest['reference'];names=latest['joint_names'];ix=[names.index('joint_'+str(i)) for i in range(1,7)]
   def values(key):return [r[key][i] for i in ix] if len(r[key])==len(names) else None
   ra=values('accelerations');rv=values('velocities');rq=values('positions')
   if ra is None and len(refs)==2 and rv is not None:
    old=refs[-2];span=(latest['header_ns']-old['header_ns'])/1e9
    if span>0 and len(old['reference']['velocities'])==len(names):ra=((np.array(rv)-np.array([old['reference']['velocities'][i] for i in ix]))/span).tolist()
   if all(x is not None for x in (rq,rv,ra)):desired=dict(session_id=session,clock_basis='SIM_TIME',clock_epoch=0,stamp_s=latest['header_ns']/1e9,q_rad=rq,v_rad_s=rv,a_rad_s2=ra,raw_controller_states=refs)
  reference_association=None
  if desired is not None:
   current_drive=row['tracking']['drive_target_q_rad']
   if not np.array_equal(np.asarray(desired['q_rad'],np.float32),np.asarray(current_drive,np.float32)):raise ValueError('CURRENT_REFERENCE_NOT_CURRENT_NATIVE_DRIVE_TARGET')
   if desired['stamp_s']>row['time_s']:raise ValueError('REFERENCE_SOURCE_CLOCK_ORDER_INVALID')
   reference_association=dict(method='TERMINAL_CONTROLLER_REFERENCE_MATCHES_CURRENT_PHYSX_DRIVE_TARGET_FLOAT32',reference_source_stamp_s=desired['stamp_s'],observed_source_stamp_s=row['time_s'],current_drive_target_q_rad=current_drive,source_stamp_relabelled=False,single_writer='D')
  objects=read_scene_geometry(omni.usd.get_context().get_stage(),seed)[0];check_physical(objects)
  counts=command_counts(statuses);owner=dict(scope='FIXED_SCENE_SIM_OWNER_STATE',single_writer='D',physics_state_observed=True,scene_restored=True,user_stop_latched=(out/'stop.request').exists(),failure_latched=False,outcome_unknown=False,**counts,pending_cancel_count=0,contact_fingers=row['contact_fingers'],checkpoint_sha256=handoff['checkpoint']['sha256'],model_manifest_sha256=request['model_bundle']['manifest_sha256'],current_revision=request['current_revision'],selected_block_id=request['planning_snapshot']['selected_slot_id'],q_rad=row['q_rad'],grip_rad=row['grip_rad'],attachment_tcp_to_block=row['attachment'],world_objects=objects,v_rad_s=v.tolist(),a_rad_s2=a.tolist(),desired=desired,session_id=session,clock_basis='SIM_TIME',state_stamp_s=row['time_s'],now_s=row['time_s'],goal_version=0,clock_epoch=0,reference_association=reference_association)
  save(out/'actual_fixed_owner.json',owner)
  pins=dict(receipt=report['sha256'],fcl_binary=package['FCL_binary_sha256'],request=package['new_request']['sha256'],external=package['new_external_timed']['sha256'],fcl_result=package['new_FCL']['sha256'],model_manifest=package['new_model_manifest']['sha256'])
  def read_current_owner():
   # Re-read native articulation/geometry on each boundary callback. Physics
   # is not advanced during the serialized review and send section.
   current=cache['sample']();value=copy.deepcopy(owner)
   value.update(q_rad=current['q_rad'],grip_rad=current['grip_rad'],attachment_tcp_to_block=current['attachment'],contact_fingers=current['contact_fingers'],v_rad_s=current['velocity_rad_s'][:6],state_stamp_s=current['time_s'],now_s=current['time_s'],world_objects=read_scene_geometry(omni.usd.get_context().get_stage(),seed)[0],user_stop_latched=(out/'stop.request').exists())
   if current['time_s']!=row['time_s']:raise ValueError('FIXED_REVIEW_PHYSICS_ADVANCED_REBUILD_PVT')
   value['a_rad_s2']=((np.array(value['v_rad_s'])-np.array(history[-2]['velocity_rad_s'][:6]))/dt).tolist()
   return value
  from plan_only import digest
  def evidence_ref(path):return dict(path=str(path),sha256=sha(path))
  association_folder=out/'current_reference_association';association_folder.mkdir(exist_ok=True)
  associated_observed=dict(session_id=session,clock_basis='SIM_TIME',clock_epoch=0,stamp_s=row['time_s'],q_rad=row['q_rad'],v_rad_s=v.tolist(),a_rad_s2=a.tolist())
  if desired is not None:
   # Prove a held command interval through actual controller messages and
   # current actuator targets. This never declares observed velocity zero.
   if len(refs)<2 or any(refs[-2]['reference'][field]!=refs[-1]['reference'][field] for field in ('positions','velocities','accelerations')) or any(x!=0 for x in desired['v_rad_s']+desired['a_rad_s2']):raise ValueError('CURRENT_HELD_REFERENCE_INTERVAL_UNCONFIRMED')
   save(association_folder/'clock.json',dict(session_id=session,clock_basis='SIM_TIME',clock_epoch=0,observed_stamp_s=row['time_s'],physics_step=row['tracking']['physics_step'],native_ros_clock_ns=row['tracking']['ros_clock_ns'],controller_headers_ns=[x['header_ns'] for x in refs]))
   save(association_folder/'controller_reference.json',dict(desired=desired,actual_drive_targets=row['tracking'],native_command_counts=counts))
   save(association_folder/'observed_state.json',associated_observed)
   proof=dict(scope='VERIFIED_CONTROLLER_REFERENCE_OBSERVATION_ASSOCIATION',session_id=session,clock_basis='SIM_TIME',clock_epoch=0,desired_stamp_s=desired['stamp_s'],observed_stamp_s=row['time_s'],desired_pvt_digest=digest({k:desired[k] for k in ('q_rad','v_rad_s','a_rad_s2')}),observed_pvt_digest=digest({k:associated_observed[k] for k in ('q_rad','v_rad_s','a_rad_s2')}),valid_from_s=desired['stamp_s'],valid_until_s=row['time_s'],method='CONFIRMED_CONTROLLER_HOLD_INTERVAL',reference_held_confirmed=True,evidence={key:evidence_ref(association_folder/name) for key,name in [('clock','clock.json'),('controller_reference','controller_reference.json'),('observed_state','observed_state.json')]})
   save(association_folder/'proof.json',proof);desired['source_time_association']=evidence_ref(association_folder/'proof.json');owner['desired']=desired
   save(association_folder/'owner.json',owner)
   state=dict(associated_observed,source_stamp_s=row['time_s'],owner_evidence=evidence_ref(association_folder/'owner.json'))
   save(association_folder/'packet.json',dict(desired=desired,state=state))
   owner['clock_association']=dict(clock_epoch=0,packet_evidence=evidence_ref(association_folder/'packet.json'))
  transition=None;whole=None
  first=packet['trajectory']['points'][0]
  if desired is not None and any(desired[k]!=first[field] for k,field in [('q_rad','positions_rad'),('v_rad_s','velocities_rad_s'),('a_rad_s2','accelerations_rad_s2')]):
   from live_cumotion_boundary import check_transition_fcl
   from isaac_sim.real_execution.native_boundary import native_transition_candidate as transition_candidate
   import xml.etree.ElementTree as ET
   model_xml=ET.fromstring(request['model_bundle']['robot_description']);joint_limits=[model_xml.find(f"joint[@name='joint_{i}']/limit") for i in range(1,7)]
   controller_doc=yaml.safe_load((out/'controllers.reference.yaml').read_text())['/sim/m0609/arm_controller']['ros__parameters']
   tracking_limits=dict(q_tolerance_rad=min(controller_doc['constraints']['joint_'+str(i)]['goal'] for i in range(1,7)),v_tolerance_rad_s=controller_doc['constraints']['stopped_velocity_tolerance'],a_tolerance_rad_s2=None,max_reference_skew_s=None,criteria_sources=dict(q_tolerance_rad=dict(source_category='ROBOT_OR_CONTROLLER_CONFIGURATION',reference=str(out/'controllers.reference.yaml')+' constraints.joint_i.goal: completed holding goal'),v_tolerance_rad_s=dict(source_category='ROBOT_OR_CONTROLLER_CONFIGURATION',reference=str(out/'controllers.reference.yaml')+' constraints.stopped_velocity_tolerance: completed holding goal'),a_tolerance_rad_s2=dict(value=None,source_category='OFFICIAL_NOT_DEFINED',check_mode='REPORT_ONLY',reference='cuMotion1.1.0 official API/installed pyi do not define measured acceleration tolerance'),max_reference_skew_s=dict(value=None,source_category='OFFICIAL_NOT_DEFINED',check_mode='REPORT_ONLY',reference='Current terminal reference verified against current physical drive target; source stamps retained')))
   tracking_limits['observation_criteria']={key:dict(value=None,unit=unit,applies_to=usage,source_category='OFFICIAL_NOT_DEFINED',check_mode='REPORT_ONLY',reference='cuMotion1.1.0 official API/installed pyi; no universal measured value',runtime_version='standalone cuMotion1.1.0 / nativeJTC4.42.1') for key,unit,usage in [('a_tolerance_rad_s2','rad/s^2','MEASURED_ACCELERATION_TRACKING_REPORT'),('max_reference_skew_s','s','PINNED_CURRENT_REFERENCE_OBSERVATION_ASSOCIATION')]};save(out/'tracking_criteria_sources.json',tracking_limits)
   observed=dict(session_id=session,clock_basis='SIM_TIME',clock_epoch=0,stamp_s=row['time_s'],q_rad=row['q_rad'],v_rad_s=v.tolist(),a_rad_s2=a.tolist())
   transition=transition_candidate(packet['trajectory'],desired,observed,duration_s=.5,limits=tracking_limits,lower=[float(x.get('lower')) for x in joint_limits],upper=[float(x.get('upper')) for x in joint_limits])
   suffix_result=yaml.safe_load(Path(package['new_FCL']['path']).read_text());lib=root/'local_records/step6_cumotion_20261014/offline_stop_candidate/libstop_fcl.so'
   def context_check(phase):
    current=read_current_owner();return dict(phase=phase,source_now_s=current['now_s'],desired=current['desired'],observed=dict(session_id=session,clock_basis='SIM_TIME',clock_epoch=0,stamp_s=current['state_stamp_s'],**{k:current[k] for k in ('q_rad','v_rad_s','a_rad_s2')}),execution_allowed=False,hardware_execution_allowed=False)
   whole=check_transition_fcl(transition,request,suffix_result,lib,sha(lib),context_check=context_check)
   save(out/'initial_transition.json',transition);save(out/'initial_transition_FCL.json',whole)
  from isaac_sim.real_execution.native_boundary import native_wire_expected
  delivered_curve=native_wire_expected(transition['trajectory'] if transition else packet['trajectory'])
  fresh_folder=out/('actual_geometry_review_'+str(len(list(out.glob('actual_geometry_review_*')))))
  actual_geometry_receipt=audit_current_geometry(fresh_folder,request,delivered_curve,read_current_owner,root/'local_records/step6_cumotion_20261014/offline_stop_candidate/libstop_fcl.so')
  native_goal,delivery_review=receive_fixed_scene_delivery(index,sha(index),input_handoff_path=hpath,input_handoff_sha=sha(hpath),latest_fixed_owner=read_current_owner,header_stamp_ns=0,next_goal_version=1,review_limits=limits,initial_transition=transition,whole_curve_receipt=whole,whole_curve_library_sha256=sha(root/'local_records/step6_cumotion_20261014/offline_stop_candidate/libstop_fcl.so'),tracking_limits=locals().get('tracking_limits'),actual_geometry_receipt=actual_geometry_receipt)
  save(out/'fixed_delivery_review.json',delivery_review)
  review=delivery_review['native_review']
  save(out/'fixed_scene_wire_review.json',review)
  if native_goal is None:raise ValueError('FIXED_SCENE_HOLD:'+review['status'])
  if review['wire_trajectory']!=delivered_curve or actual_geometry_receipt['owner_digest']!=digest(read_current_owner()):raise ValueError('ACTUAL_GEOMETRY_OR_WIRE_CHANGED_AFTER_REVIEW')
  if args.dynamic_depth_hold:cache['live_owner'].prepare_wire(delivered_curve)
  verify_loaded_functions()
  save(out/'runtime_source_review.json',dict(loaded_runtime_code_unchanged=True,loaded_source_pins=str(out/'loaded_runtime_source_pins.json'),current_disk_sources={str(p):sha(p) for p in runtime_sources},disk_changes=[str(p) for p,expected in import_files.items() if sha(p)!=expected],native_command_evidence_checks_unchanged=True))
  return native_goal
 def prepare_start(sample,tick,world):
  import rclpy
  for _ in range(64):rclpy.spin_once(cache['node'],timeout_sec=0)
  row=sample();refs=row.get('tracking',{}).get('controller_states',[])
  if not refs:raise ValueError('ACTUAL_CONTROLLER_REFERENCE_UNOBSERVED')
  if any(len(refs[-1]['reference'][k])!=6 for k in ('positions','velocities','accelerations')):raise ValueError('ACTUAL_REFERENCE_PVT_INCOMPLETE')
  save(out/'actual_start_wait.json',dict(scope='ACTUAL_PVT_FOR_COMPLETE_CONNECTION_NOT_SDK_OBSERVATION_EQUALITY',raw_observation=row,SDK_start_difference_rad=(np.array(row['q_rad'])-packet['trajectory']['points'][0]['positions_rad']).tolist(),controller_source_stamp_s=refs[-1]['header_ns']/1e9,actual_reference_skew_s=row['time_s']-refs[-1]['header_ns']/1e9,sdk_official_measured_start_tolerance=None,official_status='OFFICIAL_NOT_DEFINED',next='CURRENT_DESIRED_TO_UNCHANGED_SDK_SUFFIX_PLUS_WHOLE_FCL'))
 if not args.fresh_moveit_baseline:runtime.prepared_transport=dict(receive=receive_prepared,check_world=check_physical,native_goal=build_native,prepare_start=prepare_start)
 def after(*values):
  if recorder and not args.fresh_moveit_baseline:recorder.completed(values[-1],packet)
 runtime.after_transport_hook=after
 if args.fresh_moveit_baseline:
  from capture_sim_runtime import checkpoint_transport_route
  from d_sim_transport import validate_fresh_moveit_route
  route=checkpoint_transport_route(runtime,194);validate_fresh_moveit_route(runtime,'194','LOCALHOST')
  save(out/'runtime_preflight.json',dict(scope='ACTUAL_RUNNER_RUNTIME_OBJECT_AND_REAL_CALLBACKS_NOT_NATIVE_EXECUTION',restore_route=route,transport_engine=runtime.transport_engine,fresh_moveit_baseline=runtime.fresh_moveit_baseline,prepared_transport_present=hasattr(runtime,'prepared_transport'),restore_callback=runtime.checkpoint_restore_hook.__qualname__,restore_callback_code_sha256=hashlib.sha256(marshal.dumps(runtime.checkpoint_restore_hook.__code__)).hexdigest(),wrist_callback=runtime.wrist_depth_hook.__qualname__,calculator_path=str(runtime.transport_calculator),calculator_sha256=sha(runtime.transport_calculator),original_goal=request['goal'],model_manifest_sha256=request['model_bundle']['manifest_sha256']))
 if args.runtime_preflight_only:return
 if args.fresh_moveit_baseline:
  import time
  save(out/'native_process.json',dict(allocation_id=allocation.get('allocation_id'),allocation_path=str(allocation_path),allocation_sha256=sha(allocation_path),direct_camera_display=args.direct_camera_display,pid=os.getpid(),startticks=Path('/proc/self/stat').read_text().split()[21],wall_started_unix_s=time.time(),ros_domain_id=194,sim_command_profile=args.sim_command_profile,source_render_every_physics_steps=args.source_render_every_physics_steps,hardware_execution_allowed=False,new_obstacle=args.unlabelled_static_shadow,SDK_execution=False))
 if args.fresh_moveit_baseline:
  # Load the complete CPU FCL/SciPy dependency tree before Kit changes sys.path.
  # These are mesh collision helpers; no cuMotion SDK or archived receiver.
  import scipy.ndimage
  import stop_fcl
  from isaac_sim.depth_obstacles.helper_provenance import freeze
  freeze(('settled_moveit_source','controller_start_observation','controller_start_inputs','moveit_command_timing','stop_fcl','prepare_cumotion_model','cumotion_geometry','prepare_cpu_model','prepare_gpu_scene','sim_utils','stop_curve'),out/'settled_source_first_import_pins')
  if args.current_stop_providers:
   provider_proof=freeze(('current_stop_providers',),out/'current_provider_first_import_pins',
       class_methods={'current_stop_providers':('CurrentStopProviders.__init__','CurrentStopProviders.source_clock_provider','CurrentStopProviders._current','CurrentStopProviders.capture_provider','CurrentStopProviders._diagnostic_failure','CurrentStopProviders.diagnostic_status')})['current_stop_providers']
   if (provider_proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or
           provider_proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts/current_stop_providers.py')):
    raise ValueError('CURRENT_PROVIDER_FIRST_IMPORT_SOURCE_PROOF_REQUIRED')
  if args.bounded_stop_video:
   video_proofs=freeze(('isaac_sim.depth_obstacles.bounded_viewport_clip',),out/'video_first_import_pins',class_methods={'isaac_sim.depth_obstacles.bounded_viewport_clip':('BoundedViewportClip.__init__','BoundedViewportClip._record','BoundedViewportClip._complete','BoundedViewportClip.event','BoundedViewportClip.sample','BoundedViewportClip.close')})
   video_proof=video_proofs['isaac_sim.depth_obstacles.bounded_viewport_clip']
   if video_proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or not video_proof.get('source_pin') or video_proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/depth_obstacles/bounded_viewport_clip.py'):raise ValueError('VIDEO_FIRST_IMPORT_SOURCE_PROOF_REQUIRED')
  if args.command_start_planning:
   command_proofs=freeze(('command_start_plan',),out/'command_start_plan_first_import_pins')
   command_proof=command_proofs['command_start_plan']
   if command_proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or not command_proof.get('source_pin') or command_proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts/command_start_plan.py'):raise ValueError('COMMAND_START_PLAN_FIRST_IMPORT_PROOF_REQUIRED')
  if args.joint_current_inputs:
   # native_boundary imports dynamic_cumotion_inputs through planner_bundle.
   # Select all R/CU core bytes together before the STOP-owner import boundary;
   # receiver/joint import later, after the original depth/owned/compact group.
   joint_core=('conservative_stop_packet','dynamic_cumotion_inputs','initial_moveit_source','saved_initial_moveit_anchor','moveit_stop_cumotion_inputs','live_current_cumotion_inputs')
   joint_proofs=freeze(joint_core,out/'joint_core_first_import_pins')
   for module_name,proof in joint_proofs.items():
    if (proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or
            proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts'/(module_name+'.py'))):
     raise ValueError('JOINT_CORE_FIRST_IMPORT_SOURCE_PROOF_REQUIRED:'+module_name)
  if args.sim_stop_owner_limits:
   freeze(('sim_stop_owner','isaac_sim.real_execution.conservative_stop_evidence'),out/'stop_owner_first_import_pins',class_methods={'sim_stop_owner':('SimStopOwnerPublication.__init__','SimStopOwnerPublication.accepted','SimStopOwnerPublication.cancel_requested','SimStopOwnerPublication.terminal_result','SimStopOwnerPublication.observe','SimStopOwnerPublication.verified_stop','SimStopOwnerPublication.publish_frame')})
  if args.source_depth_baseline:
   from isaac_sim.depth_obstacles.helper_provenance import freeze
   # Freeze Python dependencies before configuration imports cache them.
   depth_import_proofs=freeze(('isaac_sim.depth_obstacles.novel_depth.interval_kernel',),out/'interval_kernel_first_import_pins',class_methods={'isaac_sim.depth_obstacles.novel_depth.interval_kernel':('IntervalKernel.__init__','IntervalKernel._inputs','IntervalKernel.finish','IntervalKernel.slab_intersection')})
   if kernel_spec:
    depth_import_proofs.update(freeze(('isaac_sim.depth_obstacles.novel_depth.raster_kernel',),out/'raster_kernel_first_import_pins',class_methods={'isaac_sim.depth_obstacles.novel_depth.raster_kernel':('RasterKernel.__init__','RasterKernel.raster')}))
   depth_import_proofs.update(freeze(tuple('isaac_sim.depth_obstacles.novel_depth.'+n for n in ('geometry','qualification','expected_depth','difference','point_bounds','replay_saved'))+('isaac_sim.depth_obstacles.projection','isaac_sim.depth_obstacles.camera_preview','isaac_sim.depth_obstacles.baseline_camera'),out/'depth_first_import_source_pins',class_methods={'isaac_sim.depth_obstacles.baseline_camera':('BaselineCamera.native_stamp','BaselineCamera.source_sample','BaselineCamera.compute_shadow','BaselineCamera.export_named_link_diagnostic','BaselineCamera.export_shadow_diagnostics','BaselineCamera.poll_shadow_result','BaselineCamera.export_source','BaselineCamera.apply_detection_display','BaselineCamera.refresh_display_label','BaselineCamera.__init__','BaselineCamera.flush','BaselineCamera.close')}))
   required_depth_imports=('interval_kernel','qualification','expected_depth')+(('raster_kernel',) if kernel_spec else ())
   for imported_name in required_depth_imports:
    import_proof=depth_import_proofs['isaac_sim.depth_obstacles.novel_depth.'+imported_name]
    if import_proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or not import_proof.get('source_pin'):
     raise ValueError('RUNTIME_DEPTH_FIRST_IMPORT_SOURCE_PROOF_REQUIRED:'+imported_name)
    canonical_source=root/'work/C-2-moveit/isaac_sim/depth_obstacles/novel_depth'/(imported_name+'.py')
    selected_source=next((pin for spec in (kernel_spec,interval_spec) if spec for pin in spec['files'] if Path(pin['path'])==canonical_source),dict(path=str(canonical_source),sha256=sha(canonical_source)))
    if import_proof['source_pin']['sha256']!=selected_source['sha256'] or sha(canonical_source)!=selected_source['sha256']:
     raise ValueError('RUNTIME_DEPTH_IMPORTED_SOURCE_SHA_MISMATCH:'+imported_name)
   if kernel_spec:
    from isaac_sim.depth_obstacles.novel_depth import expected_depth
    lib=next(p for p in kernel_spec['files'] if Path(p['path']).suffix=='.so')
    loaded=expected_depth.configure_cpp_raster(lib['path'],lib['sha256'],sim_scope=kernel_spec['scope'])
    kernel_binding=dict(engine='CPP_BBOX_F64',load=loaded,manifest=dict(path=str(args.cpp_depth_raster_manifest.resolve()),sha256=sha(args.cpp_depth_raster_manifest)),source_files=kernel_spec['files'],compile_command=kernel_spec['compile_command'])
    save(out/'numerical_kernel_load.json',kernel_binding)
   if interval_spec:
    from isaac_sim.depth_obstacles.novel_depth import qualification
    interval_lib=next(p for p in interval_spec['files'] if Path(p['path']).suffix=='.so')
    interval_loaded=qualification.configure_cpp_intervals(interval_lib['path'],interval_lib['sha256'],sim_scope=interval_spec['scope'])
    interval_binding=dict(engine='CPP_INTERVAL_TAIL_F64',load=interval_loaded,manifest=dict(path=str(args.cpp_depth_interval_manifest.resolve()),sha256=sha(args.cpp_depth_interval_manifest)),source_files=interval_spec['files'],compile_command=interval_spec['compile_command'])
    save(out/'numerical_interval_kernel_load.json',interval_binding)
  if consumer_report is not None:
   from isaac_sim.depth_obstacles.helper_provenance import freeze
   freeze(('isaac_sim.real_execution.novel_depth_consumer','isaac_sim.real_execution.point_product_handoff'),out/'consumer_first_import_source_pins')
   import types
   example=Path(consumer_report['caller_example']['path']);raw=example.read_bytes()
   if hashlib.sha256(raw).hexdigest()!=consumer_report['caller_example']['sha256']:raise ValueError('CONSUMER_EXAMPLE_CHANGED_BEFORE_IMPORT')
   module=types.ModuleType('seeun_same_runtime_shadow_example');sys.modules[module.__name__]=module
   code=compile(raw,str(example),'exec',dont_inherit=True);exec(code,module.__dict__);consumer_callback=module.handoff
   save(out/'consumer_example_loaded.json',dict(source=consumer_report['caller_example'],method='FIRST_SELECTED_SOURCE_BYTES_COMPILE_EXEC_NEW_MODULE_NO_RELOAD_NO_NUMERICAL_PATH_CHANGE',code_sha256=hashlib.sha256(marshal.dumps(consumer_callback.__code__)).hexdigest(),numpy_version=np.__version__,numpy_file=np.__file__,same_process=True))
  if args.compact_stop_handoff:
   compact_proofs=freeze(('compact_stop_handoff','compact_points_guarded','projection_arrays'),out/'compact_stop_first_import_pins',
       class_methods={'compact_stop_handoff':('CompactStopEntry.__init__','CompactStopEntry.read','CompactStopEntry.verify','CompactStopHandoff.__init__','CompactStopHandoff.prepare_worker','CompactStopHandoff._clock','CompactStopHandoff._fresh','CompactStopHandoff._validate_product','CompactStopHandoff.poll','CompactStopHandoff.current','CompactStopHandoff._diagnostic_failure','CompactStopHandoff._failure_context','CompactStopHandoff.diagnostic_status'),
                      'compact_points_guarded':('OwnedCompactPoints.__init__','OwnedCompactPoints.verify','OwnedCompactPoints.ref','OwnedCompactPoints.read')})
   for module_name,proof in compact_proofs.items():
    if (proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or
            proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts'/(module_name+'.py'))):
     raise ValueError('COMPACT_STOP_FIRST_IMPORT_SOURCE_PROOF_REQUIRED:'+module_name)
  if args.joint_current_inputs:
   joint_names=('compact_point_receiver','joint_compact_caller')
   joint_proofs=freeze(joint_names,out/'joint_current_first_import_pins',class_methods={'joint_compact_caller':('JointCompactCaller.__init__','JointCompactCaller.poll')})
   for module_name,proof in joint_proofs.items():
    if (proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or
            proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts'/(module_name+'.py'))):
     raise ValueError('JOINT_CURRENT_FIRST_IMPORT_SOURCE_PROOF_REQUIRED:'+module_name)
  save(out/'CPU_dependency_pins.json',dict(scipy_file=__import__('scipy').__file__,ndimage_file=scipy.ndimage.__file__,numpy_file=np.__file__,stop_fcl_source_sha256=sha(stop_fcl.__file__)))
 from isaacsim import SimulationApp
 app=SimulationApp(dict(headless=False,width=1440,height=900))
 recorder=None
 try:
  from pxr import Usd,UsdGeom,UsdPhysics,Gf
  import omni.timeline,omni.usd
  from sim_utils import matrix_pose,pose_matrix,error
  from capture_sim_scene import command_counts,verified_stop,read_scene_geometry
  from isaac_sim.depth_obstacles.native_run_recording import NativeRunRecording,configure_view
  # Python retains loaded functions when another owner edits the source file.
  # Pin the bytes at the import boundary and the functions actually used;
  # later disk edits are reported separately from runtime code replacement.
  source_folder=out/'loaded_sources';source_folder.mkdir()
  import_files={str(p):sha(p) for p in runtime_sources}
  # The original source qualifier reads this one camera-route snapshot.
  # Preserve that required reader input in minimal mode; skip other duplicates.
  for p in runtime_sources:
   if not recording_minimal or p.name=='baseline_camera.py':(source_folder/p.name).write_bytes(p.read_bytes())
  if args.dynamic_depth_hold:
   # Freeze lazy CPU helper imports at this recorded boundary too. Editing
   # their disk files later must not silently change the running producer.
   import importlib
   for helper in ('live_native_depth_owner','camera_preview','native_resume_sender','resume_monitor','prepared_job_selection','prepared_admission_ipc','helper_provenance','live_depth_stop','live_sensor_bundle','rolling_owner_view','prepare_static_prior','complete_sensor_bundle','bind_native_inventory'):
    importlib.import_module('isaac_sim.depth_obstacles.'+helper)
  import d_sim_transport as D_module
  loaded_modules=(D_module,)
  if not args.fresh_moveit_baseline:
   import isaac_sim.real_execution.native_boundary as boundary_module
   import live_cumotion_boundary as CU_module
   from isaac_sim.real_execution.native_boundary import receive_fixed_scene_delivery
   loaded_modules=(boundary_module,CU_module,D_module)
  if any(sha(p)!=expected for p,expected in import_files.items()):raise ValueError('SOURCE_CHANGED_DURING_MODULE_IMPORT')
  def loaded_fingerprints():
   return {module.__name__:{name:hashlib.sha256(marshal.dumps(value.__code__)).hexdigest() for name,value in vars(module).items() if getattr(value,'__module__',None)==module.__name__ and hasattr(value,'__code__')} for module in loaded_modules}
  loaded_code=loaded_fingerprints();save(out/'loaded_runtime_source_pins.json',dict(source_files=import_files,function_code_sha256=loaded_code,numerical_kernel_binding=kernel_binding,numerical_interval_kernel_binding=interval_binding))
  loaded_functions=[(module,name,value,value.__code__) for module in loaded_modules for name,value in vars(module).items() if getattr(value,'__module__',None)==module.__name__ and hasattr(value,'__code__')]
  def verify_loaded_functions():
   # marshal is evidence serialization, not a canonical live-code identity:
   # its string/reference encoding can change with normal Python execution.
   if any(getattr(module,name,None) is not function or function.__code__ is not code for module,name,function,code in loaded_functions):raise ValueError('LOADED_RUNTIME_FUNCTION_REPLACED')
  from isaac_sim.scripts.capture_sim_runtime import run_capture
  if any(sha(p)!=expected for p,expected in import_files.items()):raise ValueError('SOURCE_CHANGED_DURING_CAPTURE_IMPORT')
  from prepare_gpu_scene import tcp_fk
  baseline=yaml.safe_load(Path(handoff['baseline_request']['path']).read_text());placement=json.loads(Path(handoff['GT_placement']['path']).read_text());scene_out=out/'scene';scene_out.mkdir();prepared_dir=out/'prepared_input';prepared_dir.mkdir()
  native=root/'local_records/design_cycle_stage4_1_20261014/wrist_depth25_native_rest';raw=root/'local_records/blocked_path_native25_20261014/wrist_depth'
  # Use the original zero-reference articulation asset. Reloading a posed
  # physics export changes its joint reference frames on World.reset.
  original_scene=root/'local_records/step4_endpoint_moveit_20261013/empty_current/scene/scene.usda'
  stage=Usd.Stage.Open(str(original_scene))
  for path in sorted([str(p.GetPath()) for p in stage.Traverse() if p.GetTypeName() in ('OmniGraph','RenderProduct')],key=len,reverse=True):stage.RemovePrim(path)
  for path in ('/Stage3Clock','/Replicator'):
   if stage.GetPrimAtPath(path):stage.RemovePrim(path)
  if stage.GetPrimAtPath('/World/PathBlockingStimulus'):stage.RemovePrim('/World/PathBlockingStimulus')
  origin=root/'local_records/step4_endpoint_moveit_20261013/empty_current'
  seed=json.loads((origin/'scene/scene.seed.json').read_text());seed['world_objects']=copy.deepcopy(baseline['planning_snapshot']['world_objects'])
  # USD's saved authored poses need not equal the captured physics poses.
  # Restore each complete physical object's recorded transform once, before
  # World.reset/controller initialization. Subsequent poses are physics-owned.
  for obj in seed['world_objects']:
   prim=stage.GetPrimAtPath(obj['prim_path']);xform=UsdGeom.Xformable(prim);xform.ClearXformOpOrder();xform.AddTransformOp(opSuffix='fixedCheckpoint').Set(Gf.Matrix4d(pose_matrix(obj['world_pose']).T))
   if prim.HasAPI(UsdPhysics.RigidBodyAPI):
    rb=UsdPhysics.RigidBodyAPI(prim);rb.CreateVelocityAttr(Gf.Vec3f(0));rb.CreateAngularVelocityAttr(Gf.Vec3f(0))
  base=np.asarray(json.loads((root/'local_records/blocked_path_native25_20261014/baseline/scene.json').read_text())['frame_alignment']['T_world_base'])
  gt=copy.deepcopy(placement['obstacle'])
  if not args.fresh_moveit_baseline:
   gt=copy.deepcopy(placement['obstacle']);gt['prim_path']='/World/Environment/PathBlockingStimulus';gt['coordinate_kind']='SIM_BODY_CENTRE';gt['geometry_evidence_ref']='FIXED_GT_PLACEMENT_AUDIT_ONLY'
   base=np.asarray(json.loads((root/'local_records/blocked_path_native25_20261014/baseline/scene.json').read_text())['frame_alignment']['T_world_base']);gt['world_pose']=matrix_pose(base@pose_matrix(gt['pose']));gt['world_pose']['frame_id']='world';seed['world_objects'].append(gt)
   obstacle=UsdGeom.Xform.Define(stage,gt['prim_path']);obstacle.AddTransformOp().Set(Gf.Matrix4d((base@pose_matrix(gt['pose'])).T))
   body=UsdGeom.Cube.Define(stage,gt['prim_path']+'/Body');body.CreateSizeAttr(1);body.AddScaleOp().Set(Gf.Vec3d(*gt['size_m']));body.CreateDisplayColorAttr([Gf.Vec3f(1,.2,.05)]);UsdPhysics.CollisionAPI.Apply(body.GetPrim())
  from plan_only import digest
  metadata=dict(stage.GetRootLayer().customLayerData);metadata['seed_digest']=digest(seed);stage.GetRootLayer().customLayerData=metadata
  stage.Export(str(scene_out/'scene.usda'))
  save(scene_out/'scene.seed.json',seed);(prepared_dir/'motion.request.json').write_bytes((Path(handoff['request']['path']).parent/'motion.request.json').read_bytes())
  setup_doc=json.loads((native/'capture.setup.current.json').read_text());setup_doc['seed_digest']=digest(seed);setup_doc['restored_scene_source']=dict(path=str(raw/'captured_scene.usda'),sha256=sha(raw/'captured_scene.usda'));save(out/'setup.current.json',setup_doc);(out/'controllers.reference.yaml').write_bytes((native/'controllers.reference.yaml').read_bytes())
  if args.fresh_moveit_baseline and args.source_depth_baseline and args.direct_camera_display:
   # Local native runner owns the parsing adapter; original D file/validator
   # remains unchanged. Identical archived input/packet checked before launch.
   import d_sim_transport
   d_sim_transport.receive_files=receive_native_files_csafe
   from plan_only import prepare_d_candidate
   save(out/'native_receive_adapter.json',dict(adapter='run_fixed_depth_native.receive_native_files_csafe',adapter_code_sha256=hashlib.sha256(marshal.dumps(receive_native_files_csafe.__code__)).hexdigest(),original_validator='plan_only.prepare_d_candidate',original_validator_code_sha256=hashlib.sha256(marshal.dumps(prepare_d_candidate.__code__)).hexdigest(),parser='yaml.CSafeLoader',source=__file__,source_sha256=sha(__file__),D_source_file_changed=False,validation_or_guards_skipped=False))
  run_capture(app,runtime,out,isolated_domain=194)
 except BaseException:(out/'failure.txt').write_text(traceback.format_exc());raise
 finally:
  try:
   if 'cache' in locals() and cache.get('camera'):cache['camera'].close()
   if recorder:recorder.close()
  finally:
   try:
    if 'cache' in locals() and 'python_switch_interval_previous_s' in cache:
     sys.setswitchinterval(cache['python_switch_interval_previous_s'])
     save(out/'python_switch_interval_restored.json',dict(previous_s=cache['python_switch_interval_previous_s'],actual_s=sys.getswitchinterval(),restored=True))
   finally:app.close()
if __name__=='__main__':main()
