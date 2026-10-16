"""File-only direct-generator curve review. Never runs SDK/FCL or submits D.

Native FCL protocol has no timing metadata. Keep direct generator metadata
in the pinned external artifact; do not invent missing FCL fields.
"""
import argparse,json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import yaml
from scipy.spatial.transform import Rotation
from bounded_sim_evidence import pinned_json
from plan_only import BINDING,checked_pose,digest,prepare_d_candidate,validate_trajectory
from prepare_cpu_model import file_hash
from stop_curve import validate_quintic_limits

TIMING='CUMOTION_NATIVE_NO_TOTG'
METADATA='OFFICIAL_CSPACE_TRAJECTORY_GENERATOR_DIRECT_CUBIC_NO_TOTG_V1'
ENGINE='NVIDIA_MOTION_PLANNER_CSPACE_FK_CANDIDATE_GENERATOR_FCL_CALCULATION_ONLY_V1'


def ref(path):return dict(path=str(Path(path).resolve()),sha256=file_hash(Path(path)))


def validate_direct_export(external,result):
    """Protocol/curve integrity only; this alone is not an FCL success proof."""
    m=external['timing_metadata']
    exact=dict(engine=METADATA,source_API='CSpaceTrajectoryGenerator.generate_trajectory',
        native_derivatives_used=True,collision_aware=False,final_quintic_fcl_required=True,
        continuous_original_axis_required=True,position_fit_performed=False,
        sampled_position_fit_error_rad=None,position_fit_status='NOT_APPLICABLE_DIRECT_GENERATOR_NO_FIT',
        used_velocity_limit_rad_s=.35,used_acceleration_limit_rad_s2=.7,used_jerk_limits_rad_s3=[5.]*6)
    fields=set(exact)|{'segment_boundary_count','acceleration_boundary_probe_count',
        'sampled_acceleration_fit_error_rad_s2','spline_segment_boundaries_included',
        'timestamps_quantized_to_nanoseconds','max_export_interval_s'}
    if (external.get('engine')!=ENGINE or external.get('scope')!='FILE_ONLY_EXTERNAL_CUMOTION_TIMED' or
            external.get('execution_allowed') is not False or external.get('hardware_execution_allowed') is not False or
            external.get('timing_engine')!=TIMING or external.get('native_timing_changed') is not False or
            set(m)!=fields or any(m[k]!=v or type(m[k]) is not type(v) for k,v in exact.items())):
        raise ValueError('DIRECT_GENERATOR_PROTOCOL_OR_METADATA_CHANGED')
    if (type(m['segment_boundary_count']) is not int or m['segment_boundary_count']<2 or
            type(m['acceleration_boundary_probe_count']) is not int or m['acceleration_boundary_probe_count']!=16385 or
            m['spline_segment_boundaries_included'] is not True or m['timestamps_quantized_to_nanoseconds'] is not True):
        raise ValueError('DIRECT_GENERATOR_BOUNDARY_EXPORT_REQUIRED')
    for name in ('sampled_acceleration_fit_error_rad_s2','max_export_interval_s'):
        if type(m[name]) not in (int,float) or not np.isfinite(m[name]):raise ValueError('NONFINITE_EXPORT_METADATA')
    if not 0<=m['sampled_acceleration_fit_error_rad_s2']<=1e-9 or not 0<m['max_export_interval_s']<=.010000001:
        raise ValueError('DIRECT_SPLINE_EXPORT_REPRESENTATION_REJECTED')
    if (result.get('result_provenance')!='CUMOTION_STANDALONE_WITH_FCL_POSTCHECK' or
            result.get('timing_engine')!=TIMING or 'timing_metadata' in result or 'native_timing_changed' in result or
            external['binding']!=result['binding']):
        raise ValueError('ORIGINAL_NATIVE_FCL_PROTOCOL_REQUIRED_NO_INVENTED_METADATA')
    curve=validate_trajectory(external['trajectory']);checked=validate_trajectory(result['planned_trajectory'])
    if curve!=checked:raise ValueError('FCL_PVA_TIME_CHANGED')
    clock=np.array([p['time_from_start_s'] for p in curve['points']])
    if (clock[-1]>32 or np.max(np.diff(clock))>.010000001 or
            np.max(abs(clock*1e9-np.rint(clock*1e9)))>.00001 or
            abs(float(np.max(np.diff(clock)))-m['max_export_interval_s'])>1e-12):
        raise ValueError('FINAL_CURVE_TIME_OR_HORIZON_REJECTED')
    return curve


def verify_files(config):
    """Review archived artifacts only, without claiming new FCL execution."""
    from cumotion_cspace_engine import check_spec,qualify_endpoint
    from prepare_cumotion_model import read_cumotion_model,urdf_transforms,TCP
    from cumotion_axis_gate import certify_axis
    if config.get('scope')!='ARCHIVED_OFFLINE_CALCULATION':raise ValueError('EXPLICIT_ARCHIVE_REVIEW_SCOPE_REQUIRED')
    spec=check_spec(config['engine_spec'])
    required=('request','model_manifest','external','fcl_result','fcl_binary')
    missing=[k for k in required if not config.get(k)]
    if missing:return dict(status='WAIT_ARCHIVED_ARTIFACTS',missing=missing,SDK_started=False,FCL_executed=False,READY=False,apply_allowed=False)
    for k in required:
        if ref(config[k]['path'])!=config[k]:raise ValueError('ARCHIVED_ARTIFACT_SHA_CHANGED:'+k)
    request_path=Path(config['request']['path']);model=Path(config['model_manifest']['path']).parent
    request,manifest=read_cumotion_model(model,request_path)
    if manifest['binding']!={k:request[k] for k in BINDING}:raise ValueError('ORIGINAL_MODEL_BINDING_CHANGED')
    external=pinned_json(config['external']);result=yaml.safe_load(Path(config['fcl_result']['path']).read_text())
    if external.get('cuMotion_model_files')!=manifest['files']:raise ValueError('ORIGINAL_FULL_MODEL_FILES_CHANGED')
    curve=validate_direct_export(external,result)
    prepare_d_candidate(result,request,{k:request[k] for k in BINDING})
    qualification=qualify_endpoint(request,spec)
    if curve['points'][-1]['positions_rad']!=qualification['q_rad']:
        # Generator may use representationally different endpoint values. The
        # original TCP goal remains authority, not exact candidate float bytes.
        endpoint_candidate_equal=False
    else:endpoint_candidate_equal=True
    robot=ET.fromstring(request['model_bundle']['robot_description']);limits=[robot.find(f"joint[@name='{n}']/limit") for n in curve['joint_names']]
    analytic=validate_quintic_limits(curve,[float(x.get('lower')) for x in limits],[float(x.get('upper')) for x in limits])
    axis=checked_pose(request['planning_snapshot']['tcp_pose'])[:3,2].tolist()
    certificate=certify_axis(curve,request['model_bundle']['robot_description'],TCP,axis)
    actual=urdf_transforms(robot,curve['points'][-1]['positions_rad'],request['planning_snapshot']['grip_rad'])[TCP]
    goal=checked_pose(request['goal']);p=float(np.linalg.norm(actual[:3,3]-goal[:3,3]));r=float(Rotation.from_matrix(actual[:3,:3].T@goal[:3,:3]).magnitude())
    if p>.0008 or r>.005:raise ValueError('ORIGINAL_TCP_GOAL_REJECTED')
    return dict(status='ARCHIVED_FILE_CURVE_REVIEWED_NOT_LIVE_OR_D_APPROVAL',scope=config['scope'],
        refs={k:config[k] for k in required},engine_spec=config['engine_spec'],trajectory_digest=digest(curve),
        analytic=analytic,continuous_axis=certificate,endpoint_error_m_rad=[p,r],candidate_float_equal=endpoint_candidate_equal,
        FCL_evidence='PINNED_EXISTING_RESULT_REVIEWED_NOT_REEXECUTED_OR_INDEPENDENT_BINARY_RUN_ATTESTATION',
        SDK_started=False,FCL_executed=False,current_geometry_and_encoded_proof='PENDING',READY=False,apply_allowed=False,
        execution_allowed=False,hardware_execution_allowed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    config=json.loads(args.config.read_text())
    try:result=verify_files(config)
    except Exception as error:result=dict(status='ARCHIVED_FILE_REVIEW_REJECTED',reason=str(error),SDK_started=False,FCL_executed=False,READY=False,apply_allowed=False)
    with args.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['status']=='ARCHIVED_FILE_REVIEW_REJECTED':raise SystemExit(1)


if __name__=='__main__':main()
