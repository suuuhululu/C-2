"""Create derived path-only runtime inputs, leaving historical snapshot bytes intact."""
from pathlib import Path
import json,shutil,hashlib,difflib,os,stat
from urllib.parse import quote
PKG=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def reviewed_reference_roster(raw):
 """Extend only the authenticated comparison roster; never alter old evidence."""
 expected='d800e23eda9b574ef31c739130f5ff39169bc9307539a4266f2ae5cadfe978ed'
 if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('ORIGINAL_REVIEWED_STATIC_ROSTER_SHA_REQUIRED')
 original=json.loads(raw);ids=original['approved_static_ids']
 if (len(ids)!=len(set(ids)) or 'MidpathReferencePlate' in ids or original['selected_held_excluded'] in ids or original['unknown_actor_created'] is not False):raise ValueError('ORIGINAL_PRE_OBSTACLE_ROSTER_REQUIRED')
 result=json.loads(json.dumps(original));result['approved_static_ids']=[name for name in ids if name!='HandoverTray']+['MidpathReferencePlate']
 result.update(scope='DERIVED_REVIEWED_STATIC_ROSTER_WITH_EXPLICIT_REFERENCE_PLATE_COMPARISON_ONLY',historical_original_checksum='sha256:'+expected,historical_original_unchanged=True,removed_unused_static_ids=['HandoverTray'],extension=dict(id='MidpathReferencePlate',role='OTHER_OBSTACLE',size_m=[.045,.045,.004],appearance='OBSTACLE_COLOR_SMALL_SUPPORT',authoring_module='standalone_reference_plate',authoring_source_sha256=sha(Path(__file__).with_name('standalone_reference_plate.py')),known_before_current_baseline=True,unknown_actor_included=False))
 return result
def rebase_held_comparison(original,derived,*,source_path,model_manifest_sha256):
 """Path-only derived comparison repair; immutable originals are never edited."""
 def canonical_digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
 if original.get('schema_version')!='held-geometry-definition/0.1' or original.get('scope')!='NOMINAL_SIM_ONLY':raise ValueError('ORIGINAL_NOMINAL_HELD_COMPARISON_REQUIRED')
 if original['profile_digest']!=canonical_digest(original['profile']):raise ValueError('ORIGINAL_HELD_PROFILE_DIGEST_INVALID')
 if derived['profile']['source_path']!=source_path or derived['model_manifest_sha256']!=model_manifest_sha256:raise ValueError('EXACT_DERIVED_SOURCE_MODEL_PATH_BINDING_REQUIRED')
 before=json.loads(json.dumps(original));after=json.loads(json.dumps(derived))
 # Every geometry piece, source byte SHA, scope and nonexecution value must be
 # identical. Only the source path and model manifest's path-derived SHA move.
 before['profile']['source_path']=source_path
 before['model_manifest_sha256']=model_manifest_sha256
 before.pop('profile_digest');after.pop('profile_digest')
 if before!=after:raise ValueError('HELD_COMPARISON_REBASE_WOULD_CHANGE_SOURCE_OR_GEOMETRY')
 result=dict(derived);result['profile_digest']=canonical_digest(derived['profile'])
 return result

def selected_planner_execution_mode(root):
 """Restore execution only for the byte-exact selected derived ELF; no launch."""
 root=Path(root).resolve();binary=root/'local_records/moveit_observed_support_contact_guard_20261016/build/moveit_plan_only'
 if binary.is_symlink() or not binary.is_file():raise ValueError('SELECTED_LOCAL_PLANNER_FILE_REQUIRED')
 if binary.resolve()!=binary or not binary.resolve().is_relative_to(root) or not stat.S_ISREG(binary.stat().st_mode) or binary.stat().st_nlink!=1:raise ValueError('SELECTED_INDEPENDENT_DERIVED_REGULAR_PLANNER_REQUIRED')
 expected='9ac53e3196a402e942744765ca64b86fa34c6f046caf8aa85bef0483cbc7e4f4'
 if sha(binary)!=expected:raise ValueError('SELECTED_PLANNER_BINARY_SHA_CHANGED')
 with binary.open('rb') as stream:
  header=stream.read(64)
  if len(header)!=64 or header[:7]!=b'\x7fELF\x02\x01\x01' or int.from_bytes(header[18:20],'little')!=62 or int.from_bytes(header[52:54],'little')!=64:raise ValueError('SELECTED_PLANNER_ELF64_X86_64_REQUIRED')
 before=stat.S_IMODE(binary.stat().st_mode);binary.chmod(0o755)
 if not os.access(binary,os.X_OK) or sha(binary)!=expected:raise ValueError('DERIVED_PLANNER_EXECUTION_MODE_REQUIRED')
 return dict(path=str(binary),sha256=expected,mode_before=oct(before),mode_after=oct(stat.S_IMODE(binary.stat().st_mode)),binary_executed=False)

def materialize(root):
 root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
 manifest=json.loads((PKG/'preservation_manifest.json').read_text());origin=manifest['source_root']; oldnew={};paths=[]
 keep={'dependency','joint06_original_source126','joint06_original_model38','joint06_runtime_pinned_support','support_import_closure_current_readonly','fixed_runtime_or_qualification_input','runtime_configuration','qualification_comparison_only','USD_asset_closure','model_source_pin','coordinate_provenance_dependency'}
 for row in manifest['files']:
  if row['role'] not in keep:continue
  src=PKG/row['preserved'];rel=Path(row['original']).relative_to(origin) if row['role']!='joint06_original_source126' else src.relative_to(PKG/'snapshot')
  dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest);dest.chmod(dest.stat().st_mode|0o200);paths.append(dest)
 def strings(v):
  if isinstance(v,str):return v.replace(origin,str(root)).replace(quote(origin),quote(str(root)))
  if isinstance(v,list):return [strings(x) for x in v]
  if isinstance(v,dict):return {strings(k):strings(x) for k,x in v.items()}
  return v
 docs={}
 for p in paths:
  if p.suffix=='.json':
   try:docs[p]=strings(json.loads(p.read_text()))
   except (ValueError,UnicodeDecodeError):pass
  elif p.suffix in ('.py','.sh','.yaml','.urdf','.srdf','.usda'):
   try:p.write_text(p.read_text().replace(origin,str(root)).replace(quote(origin),quote(str(root))))
   except UnicodeDecodeError:pass
 roster=Path('local_records/moveit_native09_unlabelled_static_shadow_20261015/native09_corrective02/known_depth_map/approved_static_ids.json')
 docs[root/roster]=reviewed_reference_roster((PKG/'snapshot'/roster).read_bytes())
 for p,d in docs.items():p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
 # Only derived inputs are relinked. Every hash is computed from actual copied
 # bytes. Historical reports remain exclusively in snapshot and are never repinned.
 aliases={}
 for iteration in range(16):
  mapping={}
  for row in manifest['files']:
   candidate=root/(PKG/row['preserved']).relative_to(PKG/'snapshot')
   if candidate.is_file():
    aliases.setdefault(str(candidate),set()).update((row['sha256'],sha(candidate)))
    for previous in aliases[str(candidate)]:mapping[previous]=sha(candidate)
  def repair(v,parent):
   if isinstance(v,list):return [repair(x,parent) for x in v]
   if isinstance(v,dict):
    d={k:repair(x,parent) for k,x in v.items()}
    if isinstance(d.get('path'),str) and 'sha256' in d and Path(d['path']).is_file():d['sha256']=sha(d['path'])
    for key in ('source_files','meshes','files'):
     if isinstance(d.get(key),dict):
      for name,h in list(d[key].items()):
       f=Path(name) if Path(name).is_absolute() else parent/name
       if isinstance(h,str) and len(h)==64 and f.is_file():d[key][name]=sha(f)
    return d
   if isinstance(v,str):return mapping.get(v,v)
   return v
  changed=False
  for p in docs:
   d=repair(json.loads(p.read_text()),p.parent)
   comparison=Path('local_records/moveit_native09_unlabelled_static_shadow_20261015/native09_corrective02/known_depth_map/held_definition.json')
   if p==root/comparison and d['model_manifest_sha256']==sha(root/'local_records/step3_gpu_model_20261013/model/MODEL_MANIFEST.json'):
    original=json.loads((PKG/'snapshot'/comparison).read_text())
    d=rebase_held_comparison(original,d,source_path=str(root/'work/C-2-moveit/isaac_sim/scripts/cumotion_geometry.py'),model_manifest_sha256=sha(root/'local_records/step3_gpu_model_20261013/model/MODEL_MANIFEST.json'))
   raw=json.dumps(d,indent=2,ensure_ascii=False)+'\n'
   if raw!=p.read_text():p.write_text(raw);changed=True
  if not changed:break
 else:raise ValueError('DERIVED_INPUT_HASH_LINKS_DID_NOT_CONVERGE')
 comparison=Path('local_records/moveit_native09_unlabelled_static_shadow_20261015/native09_corrective02/known_depth_map/held_definition.json')
 original=json.loads((PKG/'snapshot'/comparison).read_text());derived=json.loads((root/comparison).read_text())
 if derived!=rebase_held_comparison(original,derived,source_path=str(root/'work/C-2-moveit/isaac_sim/scripts/cumotion_geometry.py'),model_manifest_sha256=sha(root/'local_records/step3_gpu_model_20261013/model/MODEL_MANIFEST.json')):raise ValueError('DERIVED_HELD_PROFILE_DIGEST_REPAIR_REQUIRED')
 # The package launcher and adapter are the only new behavior.
 adapter=Path(__file__).with_name('standalone_context.py');shutil.copy2(adapter,root/'work/C-2-moveit/isaac_sim/scripts/standalone_context.py')
 worker=root/'work/C-2-moveit/isaac_sim/scripts/standalone_qualifier_worker.py'
 shutil.copy2(Path(__file__).with_name('qualifier_worker.py'),worker)
 scenario=root/'work/C-2-moveit/isaac_sim/scripts/standalone_midpath_scenario.py'
 shutil.copy2(Path(__file__).with_name('standalone_midpath_scenario.py'),scenario)
 reference_plate=root/'work/C-2-moveit/isaac_sim/scripts/standalone_reference_plate.py'
 shutil.copy2(Path(__file__).with_name('standalone_reference_plate.py'),reference_plate)
 run=root/'work/C-2-moveit/isaac_sim/scripts/run_fixed_depth_native.py'
 before=run.read_text();text=before
 def change(a,b):
  nonlocal text
  if text.count(a)!=1:raise ValueError(('PATCH_ANCHOR_NOT_UNIQUE',a,text.count(a)))
  text=text.replace(a,b)
 change("if args.direct_camera_display and (allocation.get('allowed') is not True or json.loads((root/'management/GPU_RESOURCE_HANDOFF.json').read_text()).get('gpu_owner')!='MoveIt-Isaac'):raise ValueError('DIRECT_DISPLAY_GPU_ALLOCATION_NOT_ACTIVE')", "if args.direct_camera_display:\n  from standalone_context import verify_context\n  verify_context(args.allocation,root,out)")
 change(" recording_minimal=bool(args.fresh_moveit_baseline and args.source_depth_baseline and args.full_diagnostic_budget_mib is None)"," from isaac_sim.depth_obstacles.helper_provenance import freeze\n adapter_proof=freeze(('standalone_context',),out.parent/'native_adapter_first_import_pins')['standalone_context']\n if adapter_proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or adapter_proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts/standalone_context.py'):raise ValueError('STANDALONE_ADAPTER_EXECUTED_SOURCE_BINDING_REQUIRED')\n from standalone_context import bind_native_context\n bind_native_context(args.allocation,root,out)\n recording_minimal=bool(args.fresh_moveit_baseline and args.source_depth_baseline and args.full_diagnostic_budget_mib is None)")
 # Run the original qualifier once after at least two actual baseline frames.
 change("if (out/'pre_obstacle_handoff.json').exists() and model['status']=='SIM_SCOPED_NUMERICAL_MODEL':ready=True;break", "if (out/'pre_obstacle_handoff.json').exists():\n   from standalone_context import qualify_once\n   qualify_once(out)\n   model,evidence=model_provider()\n   if model['status']=='SIM_SCOPED_NUMERICAL_MODEL':ready=True;break")
 change("if not result.get('conservative_stop_verified'):return", "if not result.get('conservative_stop_verified'):raise ValueError('STANDALONE_EXPECTED_CONSERVATIVE_STOP_NOT_VERIFIED')")
 # No fixed deadline for calculations after proven STOP. Source/hold checks
 # remain active and the original raw source is never retimed.
 change("while app.is_running() and time.monotonic()<deadline and len(frames)<2:","while app.is_running() and not (out/'shutdown.request').exists() and len(frames)<2:")
 needle="     runtime.after_transport_hook=post_stop_probe"
 change(needle,"      from standalone_context import finish_stop\n      finish_stop(out,result)\n"+needle)
 change("if args.unlabelled_static_shadow:runtime_sources.append(root/'work/C-2-moveit/isaac_sim/depth_obstacles/unlabelled_static_shadow.py')", "if args.unlabelled_static_shadow:runtime_sources.extend([root/'work/C-2-moveit/isaac_sim/depth_obstacles/unlabelled_static_shadow.py',root/'work/C-2-moveit/isaac_sim/scripts/standalone_midpath_scenario.py',root/'work/C-2-moveit/isaac_sim/scripts/standalone_reference_plate.py'])")
 change("    from isaac_sim.depth_obstacles.unlabelled_static_shadow import UnlabelledStaticShadow", "    from isaac_sim.depth_obstacles.helper_provenance import freeze\n    freeze(('isaac_sim.depth_obstacles.unlabelled_static_shadow',),out/'original_scenario_first_import_pins',class_methods={'isaac_sim.depth_obstacles.unlabelled_static_shadow':('UnlabelledStaticShadow.__init__','UnlabelledStaticShadow.event','UnlabelledStaticShadow.sample')})\n    scenario_proof=freeze(('standalone_midpath_scenario',),out/'midpath_scenario_first_import_pins',class_methods={'standalone_midpath_scenario':('MidpathStaticShadow.prepare',)})['standalone_midpath_scenario']\n    if scenario_proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or scenario_proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts/standalone_midpath_scenario.py'):raise ValueError('MIDPATH_SCENARIO_SOURCE_BINDING_REQUIRED')\n    from standalone_midpath_scenario import MidpathStaticShadow as UnlabelledStaticShadow")
 change("  metadata=dict(stage.GetRootLayer().customLayerData);metadata['seed_digest']=digest(seed);stage.GetRootLayer().customLayerData=metadata", "  from isaac_sim.depth_obstacles.helper_provenance import freeze\n  plate_proof=freeze(('standalone_reference_plate',),out/'reference_plate_first_import_pins')['standalone_reference_plate']\n  if plate_proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' or plate_proof['source_pin']['sha256']!=sha(root/'work/C-2-moveit/isaac_sim/scripts/standalone_reference_plate.py'):raise ValueError('REFERENCE_PLATE_SOURCE_BINDING_REQUIRED')\n  from standalone_reference_plate import add_reference_plate, baseline_with_reference_plate, style_scene\n  baseline=style_scene(stage,seed,baseline,out)\n  reference_plate_object=add_reference_plate(stage,seed,base,out)\n  baseline=baseline_with_reference_plate(baseline,reference_plate_object)\n  save(out/'initial_world_baseline_with_reference_plate.json',baseline)\n  metadata=dict(stage.GetRootLayer().customLayerData);metadata['seed_digest']=digest(seed);stage.GetRootLayer().customLayerData=metadata")
 run.write_text(text)
 capture=root/'work/C-2-moveit/isaac_sim/scripts/capture_sim_runtime.py';cbefore=capture.read_text();ct=cbefore
 a="while app.is_running() and not (out/'shutdown.request').exists():"
 assert ct.count(a)==1
 ct=ct.replace(a,"from standalone_context import begin_stop_inspection, end_stop_inspection\n            inspect_stop=begin_stop_inspection(out,success)\n            if inspect_stop: phase_label.text='STOP verified. Simulation paused. Close IsaacSim window to exit.'\n            while inspect_stop and app.is_running() and not (out/'shutdown.request').exists():")
 tail="                app.update(); time.sleep(1/60)\n    contact_trace ="
 assert ct.count(tail)==1
 ct=ct.replace(tail,"                app.update(); time.sleep(1/60)\n            if inspect_stop: end_stop_inspection(out,window_closed=not app.is_running())\n    contact_trace =")
 # Fresh native route already starts automatically; the historical initial
 # setters remain before controller ownership, and no gripper-open is sent.
 capture.write_text(ct)
 diffs=[]
 for p,a in [(run,before),(capture,cbefore)]:
  diffs.extend(difflib.unified_diff(a.splitlines(True),p.read_text().splitlines(True),fromfile='joint06/'+p.name,tofile='standalone/'+p.name))
 (root.parent/'adapter.diff').write_text(''.join(diffs))
 camera=root/'work/C-2-moveit/isaac_sim/depth_obstacles/baseline_camera.py';camera_before=camera.read_text()
 old="while (self.future is not None or self.waiting_image is not None or self.consumer_pending is not None) and time.monotonic()<deadline and app.is_running():"
 assert camera_before.count(old)==1
 camera.write_text(camera_before.replace(old,"while (self.future is not None or self.waiting_image is not None or self.consumer_pending is not None) and app.is_running() and not (self.out/'shutdown.request').exists():"))
 with (root.parent/'adapter.diff').open('a') as f:f.writelines(difflib.unified_diff(camera_before.splitlines(True),camera.read_text().splitlines(True),fromfile='joint06/baseline_camera.py',tofile='standalone/baseline_camera.py'))
 # Relative calculator wrapper selects the exact preserved 9ac binary.
 calc=root/'local_records/moveit_observed_support_application_20261016/calculate_moveit.sh'
 calc.write_text('#!/bin/bash\nset -eo pipefail\nunset LD_LIBRARY_PATH PYTHONPATH AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH SEEUN_CHAIR_PLANNING_SECONDS SEEUN_CHAIR_PLANNING_FRACTION\nsource /opt/ros/jazzy/setup.bash\nTASK_CALC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\nexec "$TASK_CALC_DIR/../moveit_observed_support_contact_guard_20261016/build/moveit_plan_only" "$@"\n');calc.chmod(0o755)
 execution_mode=selected_planner_execution_mode(root)
 (root.parent/'derived_manifest.json').write_text(json.dumps(dict(schema='derived-standalone-path-rebase/1',scenario='MIDPATH_ACTUAL_BLOCK_CURVE_WITH_KNOWN_REFERENCE_PLATE',selected_planner_execution_mode=execution_mode,historical_hashes_unchanged=True,path_root_before=origin,path_root_after=str(root),model_manifest_sha256=sha(root/'local_records/step3_gpu_model_20261013/model/MODEL_MANIFEST.json'),files=[dict(path=str(p.relative_to(root)),sha256=sha(p)) for p in [*paths,root/'work/C-2-moveit/isaac_sim/scripts/standalone_context.py',worker,scenario,reference_plate]],adapter_diff_sha256=sha(root.parent/'adapter.diff')),indent=2)+'\n')
 return root
