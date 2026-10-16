"""Allocation/pin gate and boot metadata only; never grants a SIM start."""
from pathlib import Path
import hashlib,json,sys
HERE=Path(__file__).resolve().parent
mode,allocation_arg=sys.argv[1:];assert mode in ('preflight','run')
def ref(path):
 path=Path(path).resolve();return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
def read(path):return json.loads(Path(path).read_text())
p=read(HERE/'candidate_proposal.json');a_path=Path(allocation_arg).resolve();a=read(a_path)
assert p['status']=='LAUNCH_METADATA_CPU_VERIFIED_NOT_ALLOCATED'
assert a['allowed'] is True and a['owner']=='MoveIt-Isaac'
assert a['scope']=='SIM_FRESH_FOREGROUND_CONSERVATIVE_STOP_SAME_UUID_NO_REPLAN'
assert a['detector_cancel_SIM_authorized'] is True
assert a['maximum_new_native_runs']==a['maximum_sim_processes']==a['maximum_simultaneous_planners']==1
assert a['real_hardware_allowed'] is False and a['concurrent_SDK_allowed'] is False
assert a['ros_domain_id']==194 and a['ros_localhost_only'] is True
for flag in ('joint_current_inputs','compact_stop_handoff','current_stop_providers','bounded_stop_video','command_start_planning'):assert a[flag] is True
assert a['conservative_stop_max_source_age_SIM_s']==.4
assert a['joint_source_manifest']==p['source_manifest'] and a['joint_canonical_application']==p['canonical_application']
assert a['prior_MI_release']==p['prior_release']
for item in p['sources']+p['model_files']+[p['model_manifest'],p['FCL_binary'],p['launcher'],p['input_preparer'],p['source_manifest'],p['canonical_source_manifest'],p['canonical_application'],p['canonical_cold_preflight'],p['R_review']]:assert ref(item['path'])==item
if mode=='preflight':
 print('NEW_ALLOCATION_AND_CURRENT_JOINT_CPU_PINS_VERIFIED_NOT_SDK_EXECUTION');sys.exit(0)
claim_path=Path(a['claim_path']);claim=read(claim_path);pins_path=Path(a['final_pins_path']);pins=read(pins_path)
assert claim['allocation']==ref(a_path) and claim['final_pins']==ref(pins_path)
assert claim['run']==pins['run']==str(HERE/'native_joint02') and a['run']==str(HERE/'native_joint02')
assert claim['maximum_starts']==claim['starts_used']==1
assert claim['remaining_after_attempt']==claim['starts_remaining']==0
assert pins['sources']==p['sources'] and pins['model_files']==p['model_files']
assert pins['launcher']==p['launcher'] and pins['input_preparer']==ref(__file__)
for item in pins['sources']+pins['model_files']+[pins['model_manifest'],pins['FCL_binary']]:assert ref(item['path'])==item
# The preceding candidate exited1 in the observer guard before any SDK child.
# Its consumed claim and original result remain distinct from native32 exit143.
accept=read(a['prior_MI_release_acceptance']['path']);assert ref(a['prior_MI_release_acceptance']['path'])==a['prior_MI_release_acceptance']
assert a['prior_release_exit_code']==1 and a['prior_release_is_normal_success'] is False
value=dict(schema='mi-current-run-display-implementation-handoff/1',scope='BOOT_METADATA_NOT_NATIVE_OBSERVATION_OR_QUALIFICATION',run=str(HERE/'native_joint02'),allocation=ref(a_path),claim=ref(claim_path),final_pins=ref(pins_path),source_pins=pins['sources'],owner_reviews=pins['owner_review_snapshots'],model_manifest=pins['model_manifest'],FCL_binary=pins['FCL_binary'],native_session_id=None,new_source_qualification_verified=False,raw_observations_reused=False,SDK_execution=False)
with (HERE/'implementation_handoff.json').open('x') as f:f.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print('CURRENT_RUN_JOINT_DISPLAY_BOOT_INPUT_PINNED_NOT_START_PERMISSION')
