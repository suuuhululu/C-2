"""Stage5 measured-input preparation; no device construction or commands."""
from copy import deepcopy
import math
import numpy as np
from app.assembly_motion import pose_error,vector
from app.edge_first_seating import pose_matrix
from app.yellow4_contact_trial import prepare_contact


def positive(value,name):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
        raise ValueError('POSITIVE_FINITE_SEATING_PARAMETER_REQUIRED:'+name)
    return value


def prepare_seating(bundle,contact_settings,settings,air_evidence=None,partial_evidence=None):
    if settings.get('schema_version')!='yellow4-seating-trial/1':raise ValueError('SEATING_SETTINGS_REQUIRED')
    clearance=positive(settings['post_release_clearance_mm'],'post_release_clearance_mm')
    if not settings.get('post_release_clearance_source'):raise ValueError('RELEASE_CLEARANCE_SOURCE_REQUIRED')
    plan=prepare_contact(bundle,contact_settings,air_evidence);missing=plan['missing_measurements']
    review=settings.get('partial_trial_review');flags=('contact_axis_observed','rotation_direction_confirmed','grip_maintained','board_fixed','conditions_confirmed')
    reviewed=bool(review and review.get('evidence_ref') and all(review.get(key) is True for key in flags))
    if not reviewed:missing.append('stage4_operator_contact_and_conditions_review')
    if partial_evidence is None:missing.append('stage4_real_partial_run')
    else:
        old=partial_evidence['preview'];result=partial_evidence['result'];events=partial_evidence['events']
        if (result.get('backend')!='REAL' or result.get('status')!='PARTIAL_PIVOT_COMMANDS_COMPLETED_OPERATOR_REPORT_NOT_SEATING'
                or result.get('physical_commands',0)<=0 or result.get('gripper_release_commands')!=0 or result.get('press_commands')!=0):
            raise ValueError('STAGE4_REAL_PARTIAL_HOLDING_RUN_REQUIRED')
        if any(old.get(key)!=plan.get(key) for key in ('target','connection','grasp_mode','grasp_id','pickup_tcp','contact','remaining_tilt_deg')):
            raise ValueError('STAGE4_SCOPE_GRASP_OR_CONTACT_CONDITIONS_CHANGED')
        if 'ground_geometry' not in plan:raise ValueError('STAGE4_MEASURED_GEOMETRY_REQUIRED')
        g=plan['ground_geometry'];previous=old['ground_geometry']
        for key in ('tcp_to_block_pose_mm_zyz_deg','seated_reference_tcp_mm_zyz_deg'):
            if max(pose_error(g[key],previous[key]))>1e-6:raise ValueError('STAGE4_REGISTERED_GEOMETRY_CHANGED')
        for key in ('contact_line_points_mm','target_stud_centers_mm'):
            if not np.allclose(g[key],previous[key],atol=1e-6,rtol=0):raise ValueError('STAGE4_REGISTERED_GEOMETRY_CHANGED')
        if g['block_geometry']!=previous['block_geometry'] or g['waypoints'][0]['tilt_deg']!=previous['waypoints'][0]['tilt_deg']:
            raise ValueError('STAGE4_BLOCK_OR_DIRECTION_CHANGED')
        if old['geometry_config']['operations']['assembly']!=plan['geometry_config']['operations']['assembly']:
            raise ValueError('STAGE4_ROTATION_SAMPLING_CHANGED')
        observed={(e['data'].get('phase'),e['data'].get('answer')) for e in events if e['event']=='OPERATOR_OBSERVATION'}
        if not {('STUD_ENGAGEMENT_CHECK','STUD_ENGAGED'),('PARTIAL_RESULT_INSPECTION','PARTIAL_OBSERVED')}<=observed:
            raise ValueError('STAGE4_ENGAGEMENT_AND_PARTIAL_OBSERVATIONS_REQUIRED')
    press=deepcopy(settings['press'])
    if type(press.get('enabled')) is not bool:raise ValueError('EXPLICIT_OPTIONAL_PRESS_SELECTION_REQUIRED')
    if press['enabled']:
        p=press.get('profile')
        if p is None:missing.append('measured_closed_pad_press_profile')
        else:
            if not p.get('evidence_ref') or p.get('pad_contact_verified') is not True or p.get('frame')!='BASE':
                raise ValueError('MEASURED_CLOSED_PAD_CONTACT_REQUIRED')
            if p.get('target')!=plan['target'] or p.get('grasp_id')!=plan['grasp_id'] or any(p.get(k)!=plan['connection'][k] for k in ('tcp','tool')):
                raise ValueError('PAD_TARGET_TOOL_GRASP_BINDING_MISMATCH')
            contact_pose=vector(p['contact_tcp_pose_mm_zyz_deg'],6,'measured closed pad TCP')
            for key in ('near_contact_offset_mm','max_travel_mm','velocity_mm_s','acceleration_mm_s2','empty_width_mm','empty_width_tolerance_mm'):
                positive(p[key],key)
            if p['empty_width_mm']>12 or p['empty_width_tolerance_mm']>12-p['empty_width_mm']:
                raise ValueError('CLOSED_EMPTY_PAD_WIDTH_RANGE_REQUIRED')
            if not p.get('parameter_ref') or p.get('force_stop_n')!=45:raise ValueError('PRESS_SOURCE_AND_USER45N_STOP_REQUIRED')
            if 'ground_geometry' not in plan:missing.append('pad_registered_block_plane')
            else:
                reference=plan['ground_geometry']['seated_reference_tcp_mm_zyz_deg']
                if math.dist(reference[:2],contact_pose[:2])>.05 or pose_error(reference,contact_pose)[1]>.05:
                    raise ValueError('PAD_CONTACT_SAME_RELEASE_XY_AND_ATTITUDE_REQUIRED')
                press_targets(plan,reference,p,clearance)
    plan.update(stage=5,seating_settings=deepcopy(settings),press=press,post_release_clearance_mm=clearance,
        contact_conditions_review_status='OPERATOR_REVIEW_OF_PARTIAL_RUN' if reviewed else 'UNCONFIRMED',
        contact_conditions_material_limit_verified=False,execution_ready=not missing,
        status='FULL_SEATING_TRIAL_PREVIEW' if not missing else 'PREPARED_MISSING_SEATING_INPUTS')
    if 'ground_geometry' in plan:plan['seating_geometry']=deepcopy(plan['ground_geometry'])
    return plan


def press_targets(plan,released_pose,profile,clearance):
    """Keep actual XY/attitude; solve Z using the measured touch and registered block plane."""
    measured=profile['contact_tcp_pose_mm_zyz_deg']
    if pose_error(released_pose,measured)[1]>.05:raise ValueError('RELEASE_ATTITUDE_DIFFERS_FROM_PAD_CALIBRATION')
    normal=pose_matrix(plan['ground_geometry']['seated_reference_block_mm_zyz_deg'])[:3,2]
    if abs(normal[2])<1e-6:raise ValueError('REGISTERED_PLANE_CANNOT_SUPPORT_VERTICAL_PRESS')
    delta=np.array(released_pose[:2])-measured[:2]
    touch_z=measured[2]-float(normal[:2]@delta/normal[2])
    start=released_pose.copy();start[2]=touch_z+profile['near_contact_offset_mm']
    high=released_pose.copy();high[2]=max(released_pose[2]+clearance,start[2]+clearance)
    return dict(high=high,start=start,measured_touch_z_at_actual_xy_mm=touch_z,
        basis='MEASURED_PAD_TOUCH_WITH_REGISTERED_PLANE_XY_SHIFT',actual_block_plane_independently_verified=False)
