"""Immutable initial-MoveIt provenance only; no current-owner or SDK admission."""
from pathlib import Path
import json
import yaml
from plan_only import BINDING,GATES,digest,prepare_request,prepare_d_candidate
from prepare_sim_snapshot import SIM_KIND
from command_start_plan import validate_controller_command_start,attach_controller_command_start
from prepare_cpu_model import file_hash


def verify_initial_moveit_source(request_ref,result_ref):
    for item in (request_ref,result_ref):
        if file_hash(Path(item['path']))!=item['sha256']:raise ValueError('INITIAL_MOVEIT_SOURCE_PIN_CHANGED')
    path=Path(request_ref['path']);request=yaml.safe_load(path.read_text())
    initial=yaml.safe_load(Path(result_ref['path']).read_text())
    if (request.get('confirmation_kind')!=SIM_KIND or
            request.get('simulation_provenance',{}).get('source_kind')!='ISAAC_SIM_SAVED_STATE' or
            request.get('phase')!='TRANSPORT' or any(request[k] is not False for k in GATES)):
        raise ValueError('INITIAL_SOURCE_REQUIRES_ACTUAL_NONEXECUTABLE_SIM_MOVEIT_TRANSPORT')
    if initial.get('result_provenance')!='MOVEIT_LOCAL_PLANNING_RESULT':
        raise ValueError('INITIAL_MOVEIT_RESULT_SOURCE_REQUIRED')
    motion_path=path.parent/'motion.request.json';result_path=path.parent/'motion.result.json'
    context_path=path.parent/'scene_context.json'
    pins={p:file_hash(p) for p in (motion_path,result_path,context_path)}
    motion=json.loads(motion_path.read_text());assembly=json.loads(result_path.read_text())
    observed_base=prepare_request(motion,assembly,request['source_snapshot'],request['model_bundle']['bundle_path'])
    manifest=json.loads((Path(request['model_bundle']['bundle_path'])/'MODEL_MANIFEST.json').read_text())
    if 'kinematic_alignment' in manifest:
        raise ValueError('Do not mix a REAL aligned model into nominal SIM')
    supply=[o for o in request['planning_snapshot']['world_objects'] if o['role'] in ('SUPPLY_BLOCK','HELD_BLOCK')]
    expected={f'{colour}_{kind}_{slot:02d}' for colour,kind in
        (('yellow','2x2x1'),('yellow','2x3x1'),('blue','2x2x1'),('blue','2x3x1'),('red','1x2x1')) for slot in range(1,6)}
    if len(supply)!=25 or {o['id'] for o in supply}!=expected:
        raise ValueError('Preserve all 25 supply positions with slot6 empty')
    if 'controller_command_start' in request:
        command=validate_controller_command_start(request)
        if command['observed_request_digest']!=observed_base['planning_request_digest']:
            raise ValueError('INITIAL_OBSERVED_BASE_DIGEST_CHANGED')
        rebuilt=attach_controller_command_start(observed_base,
            dict(refs=command['source_refs'],source_identity=command['source_identity']))
    else:rebuilt=observed_base
    if rebuilt!=request or digest(rebuilt)!=digest(request):
        raise ValueError('INITIAL_MOVEIT_REQUEST_RECONSTRUCTION_CHANGED')
    binding={k:request[k] for k in BINDING};context=json.loads(context_path.read_text())
    if any(type(context[k]) is not type(binding[k]) or context[k]!=binding[k] for k in BINDING):
        raise ValueError('INITIAL_MOVEIT_CONTEXT_CHANGED')
    prepare_d_candidate(initial,request,binding)
    for item in (request_ref,result_ref):
        if file_hash(Path(item['path']))!=item['sha256']:raise ValueError('INITIAL_MOVEIT_SOURCE_CHANGED_DURING_REVIEW')
    if any(file_hash(p)!=sha for p,sha in pins.items()):
        raise ValueError('INITIAL_MOVEIT_PREPARATION_SOURCE_CHANGED')
    # Preserve the entire original initial-engine request. Saved preparation
    # emits no CU request/job, and the normal CU model validator is unchanged.
    source_pins=[request_ref,result_ref]+[dict(path=str(p.resolve()),sha256=sha) for p,sha in pins.items()]
    def collect(value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:source_pins.append(dict(path=value['path'],sha256=value['sha256']))
            else:
                for child in value.values():collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    collect(request)
    for name in ('MODEL_MANIFEST.json',*request['model_bundle']['files']):
        p=Path(request['model_bundle']['bundle_path'])/name
        source_pins.append(dict(path=str(p.resolve()),sha256=file_hash(p)))
    return dict(scope='VERIFIED_INITIAL_MOVEIT_SOURCE_ONLY',request_ref=request_ref,result_ref=result_ref,
        source_pins=source_pins,
        initial_request=request,normal_CU_model_request=False,current_owner_verified=False,
        execution_allowed=False,hardware_execution_allowed=False)
