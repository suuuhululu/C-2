"""Explicit C-space path search to a fresh-FK-qualified historical q candidate.

No pose-target IK, goal substitution, replayed path or automatic fallback.
CPU preflight is safe; actual SDK needs a fresh native selection/allocation.
"""
from pathlib import Path
import argparse,json
import numpy as np
from scipy.spatial.transform import Rotation
from bounded_sim_evidence import pinned_json
from plan_only import JOINTS,checked_pose,vector
from prepare_cumotion_model import urdf_transforms,TCP
import xml.etree.ElementTree as ET
import cumotion_pose_engine as shared
ENGINE='NVIDIA_MOTION_PLANNER_CSPACE_FK_CANDIDATE_GENERATOR_FCL_CALCULATION_ONLY_V1'
INTERNAL_IK_CONTROL='NONE_CSPACE_RRT_CONNECT_HAS_EXPLICIT_Q_TARGET'

def check_spec(item):
    spec=pinned_json(item)
    if (spec['schema']!='cumotion-explicit-cspace-candidate-engine/0.1' or spec['engine']!=ENGINE or
            spec['API_budget']!=dict(official_inspection=1,cspace_search=1,trajectory_generation=1,external_IK=0,external_OMPL=0,external_retry=0) or
            spec['target_limits']!=dict(translation_m=.0008,orientation_rad=.005,path_axis_rad=.15) or
            spec['command_limits']!=dict(velocity_rad_s=.35,acceleration_rad_s2=.7,temporary_jerk_rad_s3=5.) or
            spec['internal_IK_control']!=INTERNAL_IK_CONTROL or spec['auto_fallback'] is not False):
        raise ValueError('EXPLICIT_CSPACE_CANDIDATE_SPEC_CHANGED')
    for name,ref in spec['source_files'].items():
        if Path(ref['path']).resolve()!=Path(__file__).resolve().parent/name or shared.ref(ref['path'])!=ref:
            raise ValueError('CSPACE_ENGINE_SOURCE_CHANGED:'+name)
    if spec['endpoint_candidate'].get('joint_order')!=JOINTS or spec['endpoint_candidate'].get('units')!='rad':raise ValueError('CANDIDATE_JOINT_ORDER_UNITS_REQUIRED')
    pinned_json(spec['endpoint_candidate']['source'])
    return spec

def qualify_endpoint(request,spec):
    source=pinned_json(spec['endpoint_candidate']['source'])
    if spec['endpoint_candidate']['field']!='final_observation.q_rad':raise ValueError('ONE_EXACT_ENDPOINT_FIELD_REQUIRED')
    q=vector(source['final_observation']['q_rad'],6);robot=ET.fromstring(request['model_bundle']['robot_description'])
    for n,value in zip(JOINTS,q):
        limits=robot.find(f"joint[@name='{n}']/limit")
        if not float(limits.get('lower'))<=value<=float(limits.get('upper')):raise ValueError('CANDIDATE_ENDPOINT_JOINT_LIMIT')
    actual=urdf_transforms(robot,q,request['planning_snapshot']['grip_rad'])[TCP];goal=checked_pose(request['goal'])
    p=float(np.linalg.norm(actual[:3,3]-goal[:3,3]));r=float(Rotation.from_matrix(actual[:3,:3].T@goal[:3,:3]).magnitude())
    axis=checked_pose(request['planning_snapshot']['tcp_pose'])[:3,2];a=float(np.arccos(np.clip(actual[:3,2]@axis/np.linalg.norm(axis),-1,1)))
    if p>.0008 or r>.005 or a>.15:raise ValueError(f'CANDIDATE_NOT_QUALIFIED_FOR_FRESH_ORIGINAL_GOAL p={p} r={r} axis={a}')
    return dict(q_rad=q,source=spec['endpoint_candidate']['source'],field='final_observation.q_rad',
        fresh_original_goal=request['goal'],fresh_grip_rad=request['planning_snapshot']['grip_rad'],fresh_attachment=request['attachment'],
        FK_TCP_pose=actual.tolist(),translation_error_m=p,orientation_error_rad=r,endpoint_axis_error_rad=a,
        endpoint_collision_checked=False,scope='CPU_FK_CANDIDATE_ONLY_NOT_CURRENT_STATE_OR_PATH_PROOF')

def selected_inputs(config):
    values=shared._selected_inputs_core(config,check_spec,ENGINE,'cspace_engine_spec')
    qualify_endpoint(values[3],values[0]);return values

def preflight(config):
    if config.get('engine')!=ENGINE:raise ValueError('EXPLICIT_CSPACE_ENGINE_REQUIRED')
    check_spec(config['engine_spec']);missing=[k for k in ('selected_job','native_context','D_response','allocation','owner_pointer') if not config.get(k)]
    blockers=['WAIT_ACTUAL_FRESH_PRODUCER_FIELDS:'+','.join(missing)] if missing else []
    if not missing:selected_inputs(config)
    return dict(status='WAIT_FRESH_NATIVE_INPUTS_BEFORE_SDK' if blockers else 'CPU_BOUND_INPUTS_ONLY_NOT_LIVE_START_APPROVAL',engine=ENGINE,
        blockers=blockers,internal_IK=INTERNAL_IK_CONTROL,SDK_imported=False,SDK_started=False,READY=False,apply_allowed=False)

def run(config):
    result=preflight(config)
    if result['blockers']:raise ValueError(';'.join(result['blockers']))
    spec,job,context,request,manifest,path,model=selected_inputs(config)
    from online_cumotion_worker import read_owner_publication,verify_allocated_isaac_owner
    from dynamic_cumotion_inputs import verify_input_anchor
    from live_cumotion_boundary import live_context_checker
    from copy import deepcopy
    grant=pinned_json(config['allocation'])['concurrent_cumotion'];envelope=pinned_json(context['envelope']);inputs=pinned_json(context['obstacles'])
    def latest():
        verify_allocated_isaac_owner(grant);packet=deepcopy(read_owner_publication(config['owner_pointer'],job['identity']))
        if 'envelope' in packet and packet['envelope']!=envelope:raise ValueError('CURRENT_CONTEXT_NOT_THIS_CALCULATION')
        packet['envelope']=envelope;packet['obstacles']=inputs['obstacles'];return packet
    base=verify_input_anchor(Path(job['base_request']['path']),job['limits'])
    check=live_context_checker(base,envelope,job['limits'],latest)
    return shared._calculate_selected(config,check)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--start',action='store_true');a=p.parse_args();config=json.loads(a.config.read_text())
    print(json.dumps(preflight(config),ensure_ascii=False,indent=2))
    if a.start:print(run(config))

if __name__=='__main__':main()
