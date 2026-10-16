"""D-owned calculation receipt. No ROS, controllers, device SDK or execution."""
from pathlib import Path
import json
import sys

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT/'isaac_sim/scripts'))
from plan_only import BINDING, digest, prepare_d_candidate, validate_trajectory
from prepare_cpu_model import file_hash
from prepare_cumotion_model import read_cumotion_model
from cumotion_timing import ENGINE, TIMING_ENGINE, final_quintic_jerk

CSPACE_ENGINE='NVIDIA_MOTION_PLANNER_CSPACE_FK_CANDIDATE_GENERATOR_FCL_CALCULATION_ONLY_V1'
CSPACE_STATUS='CSPACE_ENGINE_ORIGINAL_FCL_VERIFIED_PENDING_CURRENT_AND_ENCODING'
CSPACE_TIMING='CUMOTION_NATIVE_NO_TOTG'
CSPACE_METADATA='OFFICIAL_CSPACE_TRAJECTORY_GENERATOR_DIRECT_CUBIC_NO_TOTG_V1'


def checked_cspace_timing(external,result):
    """Use pinned external metadata and the unmodified native FCL protocol.

    Raw FCL omits timing metadata/flags for native timing. Exact PVT equality
    binds its checked curve to the direct-generator exporter without aliases.
    """
    from cspace_result_protocol import validate_direct_export
    return final_quintic_jerk(validate_direct_export(external,result))


def _checked_cspace_context(report,*,report_path,expected_report_sha256,expected_engine_spec,
                            expected_selected_job,expected_native_context):
    from cumotion_cspace_engine import check_spec
    from bounded_sim_evidence import pinned_json
    refs=(expected_engine_spec,expected_selected_job,expected_native_context)
    if not expected_report_sha256 or any(ref is None for ref in refs):raise ValueError('D_SELECTED_CSPACE_REPORT_SPEC_JOB_CONTEXT_PINS_REQUIRED')
    if file_hash(Path(report_path))!=expected_report_sha256:raise ValueError('D_SELECTED_CSPACE_REPORT_SHA_CHANGED')
    if (report.get('engine_spec')!=expected_engine_spec or report.get('selected_job')!=expected_selected_job or
            report.get('native_context')!=expected_native_context):raise ValueError('D_SELECTED_CSPACE_ENGINE_SPEC_OR_JOB_CHANGED')
    check_spec(expected_engine_spec)
    job=pinned_json(expected_selected_job);context=pinned_json(expected_native_context)
    if (job.get('planning_engine')!=CSPACE_ENGINE or context.get('planning_engine')!=CSPACE_ENGINE or
            job.get('cspace_engine_spec')!=expected_engine_spec or context.get('cspace_engine_spec')!=expected_engine_spec or
            context.get('selected_job')!=expected_selected_job or digest(context['identity'])!=digest(job['identity']) or not job.get('D_input_approval') or
            context['envelope']!=job['calculated_envelope'] or context['obstacles']!=job['prepared_inputs'] or
            report['artifacts']['request']!=job['cache_request'] or report['artifacts']['model_manifest']!=job['cache_model_manifest']):
        raise ValueError('ACTUAL_CSPACE_SELECTED_JOB_CONTEXT_OR_MODEL_REQUIRED')
    model_manifest=Path(report['model_folder'])/'CUMOTION_MODEL_MANIFEST.json'
    if (set(report['artifacts'])!={'request','external','fcl_result','model_manifest'} or
            report['artifacts']['model_manifest']!={'path':str(model_manifest.resolve()),'sha256':file_hash(model_manifest)} or
            report['fcl_binary_sha256']!=job['fcl_binary']['sha256'] or file_hash(Path(job['fcl_binary']['path']))!=job['fcl_binary']['sha256']):
        raise ValueError('CSPACE_EXACT_SELECTED_FCL_MODEL_PINS_REQUIRED')
    inputs=pinned_json(context['obstacles']);envelope=pinned_json(context['envelope']);approval=pinned_json(job['D_input_approval'])
    from dynamic_cumotion_inputs import verify_seal
    verify_seal(envelope,'envelope_digest')
    if (digest(inputs['limits'])!=digest(job['limits']) or digest(envelope['online_validity']['identity'])!=digest(job['identity']) or
            envelope['thresholds_digest']!=digest(job['limits']) or
            envelope['request_sha256']!=job['cache_request']['sha256'] or
            envelope['inputs_sha256']!=context['obstacles']['sha256'] or
            job['limits']['max_state_age_s']!=.12 or job['limits']['max_obstacle_age_s']!=.12 or
            envelope['online_validity']['policy']['max_sensor_to_apply_wall_s']!=35. or
            digest(approval['identity'])!=digest(job['identity']) or approval.get('READY') is not False or approval.get('apply_allowed') is not False or
            report.get('READY') is not False or report.get('apply_allowed') is not False or report.get('native_execution_allowed') is not False or
            report.get('current_geometry_and_encoded_proof')!='PENDING_REQUIRED_NOT_EXECUTED' or
            report.get('API_calls')!=dict(official_inspection=1,cspace_search=1,trajectory_generation=1) or
            any(type(value) is not int for value in report['API_calls'].values()) or
            report.get('planner_parameter_acceptance')!={k:True for k in ('enable_self_collision_checking','max_iterations','max_sampling','seed')} or
            report['cspace_search'].get('path_found') is not True or report['generation'].get('object_present') is not True):
        raise ValueError('CSPACE_CURRENT_CONTEXT_LIMITS_OR_PENDING_SCOPE_CHANGED')
    return job,context


def checked_timing(external, result):
    """Bind the exact FCL curve to the explicit, boundary-aware export."""
    metadata = external['timing_metadata']
    if (external['scope']!='FILE_ONLY_EXTERNAL_CUMOTION_TIMED' or
            external['execution_allowed'] is not False or external['hardware_execution_allowed'] is not False or
            external['timing_engine']!=TIMING_ENGINE or external['native_timing_changed'] is not True or
            metadata['engine']!=TIMING_ENGINE or metadata['native_derivatives_used'] is not False or
            metadata['collision_aware'] is not False or metadata['final_quintic_fcl_required'] is not True or
            metadata['spline_segment_boundaries_included'] is not True or
            metadata['timestamps_quantized_to_nanoseconds'] is not True or
            not 0<metadata['max_export_interval_s']<=.010000001 or
            not 0<=metadata['sampled_position_fit_error_rad']<=1e-9 or
            not 0<=metadata['sampled_acceleration_fit_error_rad_s2']<=1e-9 or
            result['result_provenance']!='CUMOTION_STANDALONE_WITH_FCL_POSTCHECK' or
            result['timing_engine']!=TIMING_ENGINE or result['native_timing_changed'] is not True or
            result['timing_metadata']!=metadata or external['binding']!=result['binding']):
        raise ValueError('EXPLICIT_SPLINE_FCL_PROVENANCE_REQUIRED')
    raw = validate_trajectory(external['trajectory'])
    checked = validate_trajectory(result['planned_trajectory'])
    if len(raw['points'])!=len(checked['points']):
        raise ValueError('FCL_TIMED_CURVE_CHANGED')
    clock = np.array([p['time_from_start_s'] for p in raw['points']])
    if (np.max(np.diff(clock))>.010000001 or
            np.max(abs(clock*1e9-np.rint(clock*1e9)))>.00001):
        raise ValueError('BOUNDARY_AWARE_NANOSECOND_EXPORT_REQUIRED')
    for before, after in zip(raw['points'], checked['points']):
        if abs(before['time_from_start_s']-after['time_from_start_s'])>1e-9:
            raise ValueError('FCL_TIMED_CURVE_CHANGED')
        for key in ('positions_rad', 'velocities_rad_s', 'accelerations_rad_s2'):
            if not np.allclose(before[key], after[key], atol=1e-12, rtol=0):
                raise ValueError('FCL_TIMED_CURVE_CHANGED')
    return final_quintic_jerk(checked)


def receive_calculation(report_path, latest_motion_request, latest_binding, *,
                        engine, expected_fcl_sha256,expected_report_sha256=None,expected_engine_spec=None,
                        expected_selected_job=None,expected_native_context=None):
    """Receive using D's latest inputs, never report-supplied current authority."""
    cspace=engine==CSPACE_ENGINE
    if cspace:
        if not expected_report_sha256:raise ValueError('D_SELECTED_CSPACE_REPORT_SPEC_JOB_CONTEXT_PINS_REQUIRED')
        from bounded_sim_evidence import pinned_json
        report=pinned_json(dict(path=str(report_path),sha256=expected_report_sha256))
    else:report=json.loads(Path(report_path).read_text())
    if cspace and report.get('scope')=='ARCHIVED_OFFLINE_CALCULATION':
        raise ValueError('ARCHIVED_CSPACE_RESULT_NOT_LIVE_D_RECEIPT')
    status=CSPACE_STATUS if cspace else 'CUMOTION_CALCULATION_FCL_VERIFIED'
    if (engine not in (ENGINE,CSPACE_ENGINE) or report['engine']!=engine or report['status']!=status or
            report['execution_allowed'] is not False or report['hardware_execution_allowed'] is not False or
            report['auto_fallback'] is not False or report['fcl_binary_sha256']!=expected_fcl_sha256):
        raise ValueError('EXPLICIT_CALCULATION_ENGINE_AND_PINNED_FCL_REQUIRED')
    selected=None;selected_context=None
    if cspace:
        selected,selected_context=_checked_cspace_context(report,report_path=report_path,expected_report_sha256=expected_report_sha256,
            expected_engine_spec=expected_engine_spec,expected_selected_job=expected_selected_job,expected_native_context=expected_native_context)
    for artifact in report['artifacts'].values():
        if file_hash(Path(artifact['path']))!=artifact['sha256']:
            raise ValueError('CALCULATION_ARTIFACT_CHANGED')
    request_path = Path(report['artifacts']['request']['path'])
    request, manifest = read_cumotion_model(Path(report['model_folder']), request_path)
    if manifest['jerk_limits']!=[5.]*6:
        raise ValueError('APPROVED_TEMPORARY_JERK_REQUIRED')
    if (set(latest_binding)!=set(BINDING) or
            any(type(latest_binding[k]) is not type(request[k]) or latest_binding[k]!=request[k] for k in BINDING) or
            digest(latest_motion_request)!=request['motion_input_digest']):
        raise ValueError('STALE_CUMOTION_CURRENT_REQUEST_OR_RESERVATION')
    external = json.loads(Path(report['artifacts']['external']['path']).read_text())
    result = yaml.load(Path(report['artifacts']['fcl_result']['path']).read_text(), Loader=yaml.CSafeLoader)
    packet = prepare_d_candidate(result, request, latest_binding)
    audit = checked_cspace_timing(external,result) if cspace else checked_timing(external, result)
    if external['cuMotion_model_files']!=manifest['files']:
        raise ValueError('FCL_CUMOTION_MODEL_CHANGED')
    extra={}
    if cspace:
        from cumotion_cspace_engine import check_spec,qualify_endpoint
        from cumotion_axis_gate import certify_axis
        from prepare_cumotion_model import TCP,urdf_transforms
        from plan_only import checked_pose
        from stop_curve import validate_quintic_limits
        import xml.etree.ElementTree as ET
        spec=check_spec(expected_engine_spec)
        if report['fresh_endpoint_candidate_qualification']!=qualify_endpoint(request,spec):raise ValueError('CSPACE_FRESH_ORIGINAL_GOAL_QUALIFICATION_CHANGED')
        if set(selected['cache_files'])!=set(manifest['files']):raise ValueError('CSPACE_SELECTED_CACHE_FILES_CHANGED')
        for name,sha in manifest['files'].items():
            ref=selected['cache_files'][name];path=Path(report['model_folder'])/name
            if ref!={'path':str(path.resolve()),'sha256':sha} or file_hash(path)!=sha:raise ValueError('CSPACE_SELECTED_CACHE_GEOMETRY_CHANGED')
        curve=packet['trajectory'];robot=ET.fromstring(request['model_bundle']['robot_description'])
        bounds=[robot.find(f"joint[@name='{name}']/limit") for name in curve['joint_names']]
        limits=validate_quintic_limits(curve,[float(b.get('lower')) for b in bounds],[float(b.get('upper')) for b in bounds])
        if report['limits']!=limits:raise ValueError('CSPACE_FINAL_CURVE_VAJ_REPORT_CHANGED')
        actual=urdf_transforms(robot,curve['points'][-1]['positions_rad'],request['planning_snapshot']['grip_rad'])[TCP]
        goal=checked_pose(request['goal'])
        from scipy.spatial.transform import Rotation
        if np.linalg.norm(actual[:3,3]-goal[:3,3])>.0008 or Rotation.from_matrix(actual[:3,:3].T@goal[:3,:3]).magnitude()>.005:
            raise ValueError('CSPACE_FINAL_CURVE_ORIGINAL_TCP_GOAL_REJECTED')
        axis=certify_axis(curve,request['model_bundle']['robot_description'],TCP,checked_pose(request['planning_snapshot']['tcp_pose'])[:3,2].tolist())
        axis['trajectory_digest']=digest(curve)
        if report['axis_certificate']!=axis:raise ValueError('CSPACE_FINAL_CURVE_AXIS_CERTIFICATE_CHANGED')
        refs=list(report['artifacts'].values())+[expected_engine_spec,expected_selected_job,expected_native_context,
            selected_context['envelope'],selected_context['obstacles'],selected['D_input_approval']]
        if (file_hash(Path(report_path))!=expected_report_sha256 or any(file_hash(Path(ref['path']))!=ref['sha256'] for ref in refs)):
            raise ValueError('CSPACE_RECEIPT_CHANGED_DURING_REVIEW')
        check_spec(expected_engine_spec)
        extra=dict(engine_spec=expected_engine_spec,selected_job=expected_selected_job,native_context=expected_native_context,
            current_geometry_and_encoded_proof_required=True,READY=False,apply_allowed=False,native_execution_allowed=False,
            actual_STOP_clock_Depth_review='REQUIRED_IN_EXISTING_D_FINAL_PATH_NOT_PERFORMED_BY_RECEIPT_ADAPTER',
            official_generator_export='EXACT_PVA_QUINTIC_EXPORT_NOT_LEGACY_POSITION_RETIMING',final_axis=axis,final_quintic_limits=limits)
    packet.update(status='D_RECEIVED_CSPACE_CALCULATION_ONLY_PENDING_CURRENT_AND_ENCODING' if cspace else 'D_RECEIVED_CUMOTION_CALCULATION_ONLY', calculation_engine=engine,
        timing_engine=CSPACE_TIMING if cspace else TIMING_ENGINE, timing_metadata=external['timing_metadata'],
        verification=dict(final_quintic=audit, artifacts=report['artifacts'],
                          fcl_binary_sha256=expected_fcl_sha256),
        d_receipt_scope='CALCULATION_ONLY_NOT_EXECUTION', execution_issued=False,**extra)
    return packet
