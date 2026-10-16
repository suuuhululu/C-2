"""CPU preparation for the fixed blocker SIM experiment; never starts a device.

The archived SDK receipt is immutable. Measured initial PVT and an optional
quintic connection are recorded separately and get whole-curve full mesh FCL.
"""
from copy import deepcopy
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from plan_only import BINDING,JOINTS,digest,validate_trajectory
from prepare_cpu_model import file_hash
from sim_utils import error,pose_matrix,rigid
from stop_curve import quintic_intervals,validate_stop
from stop_fcl import StopScene,check_stop
from d_sim_transport import check_world


def read_pin(ref):
    p=Path(ref['path'])
    if file_hash(p)!=ref['sha256']:raise ValueError('FIXED_EXPERIMENT_ARTIFACT_CHANGED')
    return json.loads(p.read_text())


def receive(handoff_path,report_path,expected_fcl_sha256):
    from robot_control_integration.app.cumotion_transport import receive_calculation
    from cumotion_timing import ENGINE
    import yaml
    handoff=json.loads(Path(handoff_path).read_text());report=json.loads(Path(report_path).read_text())
    request_ref=handoff['request'];read_pin(handoff['checkpoint'])
    if file_hash(request_ref['path'])!=request_ref['sha256'] or report['artifacts']['request']!=request_ref:
        raise ValueError('NEW_BLOCKED_REQUEST_REQUIRED_NO_OLD_SDK_REUSE')
    if handoff['status']!='STATIC_IDENTICAL_CONDITIONS_INPUTS_READY_WAIT_CUMOTION_GPU_HANDOFF' or not all(handoff['same_conditions'].values()):
        raise ValueError('SAME_CHECKPOINT_COMPARISON_REQUIRED')
    request=yaml.safe_load(Path(request_ref['path']).read_text())
    motion=json.loads((Path(request_ref['path']).parent/'motion.request.json').read_text())
    packet=receive_calculation(report_path,motion,{k:request[k] for k in BINDING},engine=ENGINE,expected_fcl_sha256=expected_fcl_sha256)
    return request,packet,handoff


def observed_initial(request,observation,world_objects,GT_actual,placement,*,now_s):
    """No invented zero derivatives, no renderer q setter counted as tracking."""
    if (observation['joint_names']!=JOINTS or observation['clock_basis']!='SIM_TIME' or now_s<observation['stamp_s'] or
            observation['pvt_stamp_s']!=observation['stamp_s'] or
            observation['active_command_count']!=0 or observation['pending_command_count']!=0 or
            observation['contact_fingers']!=['rg2_left_inner_finger','rg2_right_inner_finger'] or
            observation['observation_kind']!='NATIVE_PHYSICS_JOINT_READOUT' or
            observation['acceleration_method']!='ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE'):
        raise ValueError('ACTUAL_SAME_CLOCK_NATIVE_HOLD_PVT_REQUIRED')
    q,v,a=[np.asarray(observation[k],float) for k in ('q_rad','v_rad_s','a_rad_s2')]
    if any(x.shape!=(6,) or not np.isfinite(x).all() for x in (q,v,a)):
        raise ValueError('FINITE_ACTUAL_PVT_REQUIRED')
    delta=error(rigid(request['attachment']),rigid(observation['attachment']))
    if delta[0]>.0005 or delta[1]>.005:raise ValueError('ACTUAL_ATTACHMENT_CHANGED_FRESH_CALCULATION_REQUIRED')
    if GT_actual['size_m']!=placement['obstacle']['size_m'] or error(pose_matrix(GT_actual['pose']),pose_matrix(placement['obstacle']['pose']))[0]>1e-8 or error(pose_matrix(GT_actual['pose']),pose_matrix(placement['obstacle']['pose']))[1]>1e-8:
        raise ValueError('FIXED_GT_PLACEMENT_CHANGED')
    original=deepcopy(request);original['planning_snapshot']['world_objects']=[x for x in request['planning_snapshot']['world_objects'] if x['id']!=request['planning_snapshot']['world_objects'][-1]['id']]
    settling=check_world(original,world_objects)
    return dict(raw_observation=deepcopy(observation),q_delta_rad=(q-np.array(request['planning_snapshot']['q_rad'])).tolist(),attachment_drift_m_rad=delta,waiting_supply_settling=settling,
        raw_nonzero_derivatives_preserved=True,execution_allowed=False)


def connection_candidate(request,packet,observation,world_objects,GT_actual,placement,library,library_sha256,*,now_s):
    initial=observed_initial(request,observation,world_objects,GT_actual,placement,now_s=now_s)
    original=validate_trajectory(packet['trajectory']);first=original['points'][0]
    robot=ET.fromstring(request['model_bundle']['robot_description']);bounds=[robot.find(f"joint[@name='joint_{i}']/limit") for i in range(1,7)]
    lower=[float(x.get('lower')) for x in bounds];upper=[float(x.get('upper')) for x in bounds]
    # Only this local experiment's physics observation changes collision state.
    # It does not mutate/rebind the archived SDK request or source receipt.
    actual_request=deepcopy(request);actual_request['planning_snapshot']['grip_rad']=observation['grip_rad'];actual_request['attachment']=observation['attachment']
    actual_by_id={x['id']:x for x in world_objects}
    actual_request['planning_snapshot']['world_objects']=[deepcopy(actual_by_id.get(x['id'],x)) for x in request['planning_snapshot']['world_objects']]
    failures=[]
    for duration in (.5,1.,2.,4.):
        left=dict(time_from_start_s=0.,positions_rad=observation['q_rad'],velocities_rad_s=observation['v_rad_s'],accelerations_rad_s2=observation['a_rad_s2'])
        right=deepcopy(first);right['time_from_start_s']=duration
        _,h,c=next(quintic_intervals(dict(joint_names=original['joint_names'],points=[left,right])))
        prefix=[]
        for u in np.linspace(0,1,int(round(duration/.01))+1):
            prefix.append(dict(time_from_start_s=float(round(u*duration,9)),positions_rad=np.polynomial.polynomial.polyval(u,c).tolist(),velocities_rad_s=(np.polynomial.polynomial.polyval(u,np.arange(1,6)[:,None]*c[1:])/h).tolist(),accelerations_rad_s2=(np.polynomial.polynomial.polyval(u,(np.arange(2,6)*np.arange(1,5))[:,None]*c[2:])/h**2).tolist()))
        prefix[0]=left;prefix[-1]=right
        suffix=[dict(p,time_from_start_s=round(p['time_from_start_s']+duration,9)) for p in original['points'][1:]]
        curve=dict(joint_names=original['joint_names'],points=prefix+suffix)
        try:
            checks=validate_stop(curve,lower,upper)
            scene=StopScene(actual_request,library,library_sha256)
            try:collision=check_stop(scene,curve)
            finally:scene.close()
            if not collision['success']:raise ValueError('WHOLE_CURVE_FCL_REJECTED:'+json.dumps(collision))
        except ValueError as exc:failures.append(dict(duration_s=duration,reason=str(exc)));continue
        return dict(scope='FIXED_SIM_MEASURED_INITIAL_CONNECTION_FULL_FCL_NOT_NATIVE_APPROVAL',status='CPU_FULL_CURVE_REVIEWED_NO_SEND',initial=initial,trajectory=curve,trajectory_digest=digest(curve),original_sdk_trajectory_digest=digest(original),original_sdk_receipt_preserved=True,
            connection_duration_s=duration,checks=checks,whole_curve_FCL=collision,whole_curve_library_sha256=library_sha256,measured_collision_request=actual_request,failures=failures,execution_allowed=False,hardware_execution_allowed=False)
    raise ValueError('NO_VALID_INITIAL_CONNECTION:'+json.dumps(failures))
