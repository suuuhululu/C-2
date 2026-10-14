"""Stage6 independent measured regrasp and partial removal; no device creation."""
from copy import deepcopy
import math
import numpy as np
from app.assembly_motion import pose_error
from app.edge_first_seating import pose_matrix,matrix_pose,preview
from app.yellow4_air_trial import load_runtime
from app.yellow4_seating_trial import positive


def prepare_removal(bundle,settings,measurement=None,seating_evidence=None):
    if settings.get('schema_version')!='yellow4-removal-trial/1':raise ValueError('REMOVAL_SETTINGS_REQUIRED')
    runtime,rates=load_runtime(bundle,{'rates':{}});missing=[]
    c=deepcopy(settings['contact'])
    required=('linear_velocity_mm_s','angular_velocity_deg_s','linear_acceleration_mm_s2',
        'angular_acceleration_deg_s2','force_stop_n','moment_delta_stop_nm','width_drift_stop_mm','axis_registration_tolerance_mm')
    for key in required:
        if c.get(key) is None:missing.append('removal_condition:'+key)
        else:positive(c[key],key)
    if not settings.get('parameter_source'):missing.append('removal_parameter_source')
    clearance=positive(settings['regrasp_clearance_mm'],'regrasp_clearance_mm')
    if not settings.get('clearance_source'):raise ValueError('REGRASP_CLEARANCE_SOURCE_REQUIRED')
    review=settings.get('field_review')
    flags=('current_seated_block_verified','board_fixed','regrasp_relation_checked','removal_axis_checked','conditions_confirmed')
    if not review or not review.get('evidence_ref') or any(review.get(k) is not True for k in flags):
        missing.append('stage6_current_block_axis_conditions_review')
    plan=dict(stage=6,operation='removal',status='PREPARED_MISSING_REMOVAL_INPUTS',execution_ready=False,
        physical_commands=0,target=deepcopy(bundle['target']),connection=deepcopy(bundle['connection']),
        sources=deepcopy(bundle['sources']),runtime=runtime,rates=rates,contact=c,settings=deepcopy(settings),
        grasp_mode=bundle['grasp_mode'],intended_pad_bottom_height_mm=bundle['intended_pad_bottom_height_mm'],
        grasp_id=None,missing_measurements=missing,parameter_source=settings.get('parameter_source'),
        parameter_field_verified=False,removal_conditions_material_limit_verified=False,
        previous_route_stop_evidence=runtime.get('return_high_blocked_reason'),
        automatic_leveling_during_intentional_tilt=False,assembly_completion=False,removal_completion=False,
        release_classifier='OPERATOR_OBSERVATION_NOT_FORCE_DROP',regrasp_clearance_mm=clearance)
    if measurement is None:missing.append('independent_removal_regrasp_pose_relation_axis_and_board_fixation')
    else:
        m=deepcopy(measurement)
        if m.get('schema_version')!='yellow4-removal-measurement/1' or m.get('source_kind')!='OPERATOR_FIELD_MEASUREMENT' or not m.get('evidence_ref'):
            raise ValueError('INDEPENDENT_REMOVAL_MEASUREMENT_EVIDENCE_REQUIRED')
        if m.get('target')!=plan['target'] or any(m.get(k)!=plan['connection'][k] for k in ('tcp','tool')):
            raise ValueError('REMOVAL_TARGET_TCP_TOOL_MISMATCH')
        if (m.get('grasp_mode')!=plan['grasp_mode'] or m.get('pad_bottom_from_block_bottom_mm')!=plan['intended_pad_bottom_height_mm'] or not m.get('grasp_id')):
            raise ValueError('REMOVAL_SELECTED_GRASP_HEIGHT_AND_ID_REQUIRED')
        if m.get('board_fixation_confirmed') is not True:missing.append('removal_board_fixation')
        width=positive(m['close_mm'],'removal_close_mm');tolerance=positive(m['width_tolerance_mm'],'removal_width_tolerance_mm')
        if not 12<width-tolerance<width+tolerance<runtime['open_mm']:
            raise ValueError('REGRASP_WIDTH_MUST_DISTINGUISH_BLOCK_FROM_EMPTY_PAD_AND_OPEN')
        frame=pose_matrix(m['frame_pose_in_base_mm_zyz_deg'])
        tcp=pose_matrix(m['regrasp_tcp_pose_mm_zyz_deg']);block=pose_matrix(m['seated_block_pose_mm_zyz_deg'])
        geometry=dict(schema_version='yellow4-pivot-preview/2',mode='PREVIEW_ONLY',operation='removal',
            source_kind='INDEPENDENT_REMOVAL_FIELD_INPUT_NOT_PARTIAL_RELEASE_VERIFICATION',
            coordinate_frame=m['coordinate_frame'],output_frame='BASE',frame_pose_in_output_mm_zyz_deg=m['frame_pose_in_base_mm_zyz_deg'],
            block=plan['target'],seated_block_pose_mm_zyz_deg=m['seated_block_pose_mm_zyz_deg'],
            tcp_to_block_pose_mm_zyz_deg=matrix_pose(np.linalg.inv(tcp)@block),block_geometry=m['block_geometry'],
            target_studs=m['target_studs'],operations=dict(assembly=None,removal=m['removal']))
        g=preview(geometry,'removal')
        plan.update(grasp_id=m['grasp_id'],measurement=m,geometry_config=geometry,partial_geometry=g,ground_geometry=g,
            regrasp_tcp=matrix_pose(frame@tcp),regrasp_width_mm=width,regrasp_width_tolerance_mm=tolerance,
            remaining_tilt_deg=g['waypoints'][-1]['tilt_deg'])
    if seating_evidence is None:missing.append('stage5_real_seating_run_and_post_release_observation')
    else:
        result=seating_evidence['result'];old=seating_evidence['preview'];events=seating_evidence['events']
        if (result.get('backend')!='REAL' or result.get('status')!='FULL_SEATING_COMMANDS_AND_OPERATOR_REPORT_NOT_INDEPENDENTLY_VERIFIED'
                or result.get('physical_commands',0)<=0 or result.get('operator_reported_seated') is not True
                or result.get('operator_reported_post_release_stable') is not True):
            raise ValueError('STAGE5_REAL_SEATING_AND_RELEASE_REPORT_REQUIRED')
        if (old.get('stage')!=5 or old.get('execution_ready') is not True or old.get('target')!=plan['target']
                or old.get('connection')!=plan['connection']):raise ValueError('STAGE5_READY_SCOPE_AND_EQUIPMENT_REQUIRED')
        if not all(old.get('sources',{}).get(k) for k in ('air_run','partial_run')):
            raise ValueError('STAGE5_STAGE3_AND_STAGE4_PROVENANCE_REQUIRED')
        observed={(e['data'].get('phase'),e['data'].get('answer')) for e in events if e['event']=='OPERATOR_OBSERVATION'}
        if not {('SEATING_RELEASE_INSPECTION','SEATED_READY_TO_RELEASE'),('POST_RELEASE_INSPECTION','POST_RELEASE_STABLE')}<=observed:
            raise ValueError('STAGE5_SEATING_AND_POST_RELEASE_OBSERVATIONS_REQUIRED')
        if measurement is not None:
            g=plan['ground_geometry'];previous=old['ground_geometry']
            if g['block_geometry']!=previous['block_geometry'] or not np.allclose(g['target_stud_centers_mm'],previous['target_stud_centers_mm'],atol=1e-6,rtol=0):
                raise ValueError('REMOVAL_BOARD_STUDS_OR_BLOCK_GEOMETRY_CHANGED')
            plan['current_vs_registered_block_pose_error']=dict(zip(('position_mm','so3_deg'),
                pose_error(g['seated_reference_block_mm_zyz_deg'],previous['seated_reference_block_mm_zyz_deg'])))
        plan['seating_result_does_not_independently_verify_current_block']=True
    plan.update(execution_ready=not missing,status='PARTIAL_REMOVAL_TRIAL_PREVIEW' if not missing else plan['status'])
    return plan


def removal_route(plan,start,start_zone):
    if start_zone not in ('home','supply','assembly'):raise ValueError('EXPLICIT_START_ZONE_REQUIRED')
    reference=plan['regrasp_tcp'];r=plan['runtime'];view=r['observation_pose']
    high=max(start[2],r['pickup_clearance_z_mm'],view[2],reference[2]+plan['regrasp_clearance_mm'])
    route=[('START_VERTICAL_LIFT',[*start[:2],high,*start[3:]])]
    if start_zone in ('home','supply'):
        for label,key in (('SUPPLY_TRANSIT','supply_transit_xy'),('BODY_BYPASS','body_bypass_xy')):
            route.append((label,[*r['startup_route'][key],high,*start[3:]]))
    route.extend([('ASSEMBLY_OBSERVATION',[*reference[:2],high,*reference[3:]]),
        ('REGRASP_ABOVE',[*reference[:2],reference[2]+plan['regrasp_clearance_mm'],*reference[3:]])])
    return route
