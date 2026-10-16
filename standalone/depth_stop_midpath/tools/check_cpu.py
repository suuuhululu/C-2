"""CPU integrity, model, import and shared-library closure checks only."""
from pathlib import Path
import ast,ctypes,json,os,subprocess,sys,hashlib,stat
root=Path(sys.argv[1]);repo=root/'work/C-2-moveit';sys.path[:0]=[str(repo),str(repo/'isaac_sim/scripts')]
import numpy,scipy,yaml
import importlib,io
from portable_runtime import python_site
vendor,_=python_site()
for name in ('numpy','scipy','yaml','PIL','jsonschema','referencing','rpds','mpmath'):
 module=importlib.import_module(name)
 assert Path(module.__file__).resolve().is_relative_to(vendor.resolve()),'EXTERNAL_PYTHON_DEPENDENCY:'+name
from PIL import Image
image_bytes=io.BytesIO();Image.new('RGB',(2,2),'green').save(image_bytes,format='PNG')
assert Image.open(io.BytesIO(image_bytes.getvalue())).size==(2,2)
print('PACKAGED_PYTHON_DEPENDENCIES_AND_PNG_CODEC_PASS')
assert numpy.__version__=='2.5.4',numpy.__version__
for p in repo.rglob('*.py'):ast.parse(p.read_text())
from prepare_cpu_model import read_model_bundle
model=read_model_bundle(root/'local_records/step3_gpu_model_20261013/model')
from prepare_taught_sim import prepare_taught_capture_setup
from prepare_gpu_scene import tcp_fk
from plan_only import digest
from isaac_sim.depth_obstacles.novel_depth import expected_depth,qualification
from isaac_sim.depth_obstacles.helper_provenance import freeze
from run_fixed_depth_native import main
from d_sim_transport import validate_fresh_moveit_route
from stop_fcl import StopScene
freeze(('isaac_sim.depth_obstacles.novel_depth.interval_kernel','isaac_sim.depth_obstacles.novel_depth.raster_kernel','isaac_sim.depth_obstacles.novel_depth.qualification','isaac_sim.depth_obstacles.novel_depth.expected_depth'),root.parent/'cpu_first_import_pins')
for rel,fn in [('moveit_cpp_kernel_integration_20261015/kernel_manifest.json',expected_depth.configure_cpp_raster),('moveit_interval_kernel_integration_20261015/interval_manifest.json',qualification.configure_cpp_intervals)]:
 d=json.loads((root/'local_records'/rel).read_text());lib=next(p for p in d['files'] if p['path'].endswith('.so'));fn(lib['path'],lib['sha256'],sim_scope=d['scope'])
ctypes.CDLL(str(root/'local_records/step6_cumotion_20261014/offline_stop_candidate/libstop_fcl.so'))
exe=root/'local_records/moveit_observed_support_contact_guard_20261016/build/moveit_plan_only'
assert exe.resolve()==exe and exe.resolve().is_relative_to(root),'SELECTED_LOCAL_PLANNER_PATH_REQUIRED'
assert hashlib.sha256(exe.read_bytes()).hexdigest()=='9ac53e3196a402e942744765ca64b86fa34c6f046caf8aa85bef0483cbc7e4f4','SELECTED_PLANNER_SHA_REQUIRED'
assert stat.S_ISREG(exe.stat().st_mode) and stat.S_IMODE(exe.stat().st_mode)==0o755,'SELECTED_PLANNER_MODE_0755_REQUIRED'
assert os.access(exe,os.X_OK),'SELECTED_PLANNER_NOT_EXECUTABLE'
assert os.access(root/'local_records/moveit_observed_support_application_20261016/calculate_moveit.sh',os.X_OK),'SELECTED_WRAPPER_NOT_EXECUTABLE'
r=subprocess.run(['ldd',str(exe)],capture_output=True,text=True);assert r.returncode==0 and 'not found' not in r.stdout,r.stdout
# Validate source pin closure and the historical setup against the relocated model.
seed=json.loads((root/'local_records/step4_endpoint_moveit_20261013/empty_current/scene/scene.seed.json').read_text())
setup=json.loads((root/'local_records/design_cycle_stage4_1_20261014/wrist_depth25_native_rest/capture.setup.current.json').read_text())
motion=json.loads((root/'local_records/blocked_path_native25_20261014/blocked_candidate/common_A/motion.request.json').read_text())
seed['motion_input_digest']=digest(motion);setup['seed_digest']=digest(seed)
temp=root.parent/'cpu_setup.json';temp.write_text(json.dumps(setup))
prepare_taught_capture_setup(seed,motion,Path(model['bundle_path']),temp)
# All local USD references and payload layers must be packaged. This is a text
# closure check; actual USD composition is deferred to SIM validation.
import re
usd=0
for p in (repo/'isaac_sim/assets').rglob('*.usda'):
 for name in re.findall(r'@([^@]+)@',p.read_text()):
  ref=Path(name);ref=ref if ref.is_absolute() else p.parent/ref
  assert ref.is_file(),str(ref)
 usd+=1
print(json.dumps(dict(status='CPU_IMPORT_MODEL_SETUP_KERNEL_FCL_LINK_PASS',numpy=numpy.__version__,scipy=scipy.__version__,model_manifest_sha256=model['manifest_sha256'],whole_model_mesh_count=len(json.loads((Path(model['bundle_path'])/'MODEL_MANIFEST.json').read_text())['meshes']),usd_text_layers=usd,planner_ldd_exit=r.returncode,SimulationApp_imported=False,GPU_SIM_started=False),indent=2))
# Execute the actual derived runner's pre-SimulationApp route with a disposable
# CPU context. Binding/pin/callback checks run; no SIM/GPU start occurs.
import uuid
session=root.parent;out=session/'native_cpu_preflight';nonce=uuid.uuid4().hex
context=dict(schema='standalone-depth-stop-context/1',mode='SIM_ONLY_DETECTION_STOP',session_nonce=nonce,session_directory=str(session),root=str(root),run=str(out),native_pid=os.getpid(),native_startticks=Path('/proc/self/stat').read_text().split()[21],maximum_starts=1,CPU_preflight_only=True,allowed=True,owner='MoveIt-Isaac',scope='SIM_FRESH_FOREGROUND_CONSERVATIVE_STOP_SAME_UUID_NO_REPLAN',detector_cancel_SIM_authorized=True,conservative_stop_max_source_age_SIM_s=.4,current_stop_providers=True,bounded_stop_video=True,command_start_planning=True,SDK_execution=False)
from standalone_context import sha,pin
for key,rel in [('numerical_kernel_manifest','moveit_cpp_kernel_integration_20261015/kernel_manifest.json'),('interval_kernel_manifest','moveit_interval_kernel_integration_20261015/interval_manifest.json'),('stop_owner_limits','moveit_stop_owner_publication_20261015/owner_limits.json')]:context[key]=pin(root/'local_records'/rel)
(session/'context.json').write_text(json.dumps(context));(session/'start_once.json').write_text(json.dumps(dict(nonce=nonce)))
env=os.environ.copy();env['DEPTH_STOP_SESSION_NONCE']=nonce
args=['--runtime-preflight-only','--fresh-moveit-baseline','--root',str(root),'--out',str(out),'--allocation',str(session/'context.json'),'--source-depth-baseline','--direct-camera-display','--unlabelled-static-shadow','--fresh-foreground-stop','--foreground-stop-max-source-age-s','.4','--foreground-python-switch-interval-ms','1','--sim-command-profile','SIM_FAST_J20','--source-render-every-physics-steps','4','--current-stop-providers','--bounded-stop-video','--command-start-planning','--transport-calculator',str(root/'local_records/moveit_observed_support_application_20261016/calculate_moveit.sh')]
for flag,key in [('--cpp-depth-raster-manifest','numerical_kernel_manifest'),('--cpp-depth-interval-manifest','interval_kernel_manifest'),('--sim-stop-owner-limits','stop_owner_limits')]:args.extend([flag,context[key]['path']])
r=subprocess.run([sys.executable,str(repo/'isaac_sim/scripts/run_depth_stop_native.py'),*args],env=env,capture_output=True,text=True)
(session/'runner_preflight.stdout.log').write_text(r.stdout);(session/'runner_preflight.stderr.log').write_text(r.stderr)
assert r.returncode==0,r.stderr
print('ACTUAL_DERIVED_RUNNER_CPU_PREFLIGHT_PASS_NO_SIMULATIONAPP')
