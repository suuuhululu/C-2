"""Stage7 full-release/recovery and cycle contracts; no device construction."""
from copy import deepcopy
import math
import time
import numpy as np
from app.assembly_motion import pose_error,vector,motion_still
from app.edge_first_seating import pose_matrix,matrix_pose,transform_points,preview
from app.yellow4_air_trial import load_runtime
from app.yellow4_seating_trial import positive


def prepare_recovery(bundle,settings,partial_evidence=None):
    if settings.get('schema_version')!='yellow4-recovery-cycle/1':raise ValueError('RECOVERY_CYCLE_SETTINGS_REQUIRED')
    r=deepcopy(settings['recovery']);runtime,rates=load_runtime(bundle,{'rates':{}});missing=[]
    plan=dict(stage=7,operation='removal',target=deepcopy(bundle['target']),connection=deepcopy(bundle['connection']),
        grasp_mode=bundle['grasp_mode'],intended_pad_bottom_height_mm=bundle['intended_pad_bottom_height_mm'],
        runtime=runtime,rates=rates,sources=deepcopy(bundle['sources']),contact=deepcopy(r['contact']),
        recovery_settings=r,execution_ready=False,physical_commands=0,missing_measurements=missing,
        status='PREPARED_MISSING_RECOVERY_INPUTS',assembly_completion=False,removal_completion=False,
        automatic_leveling_during_intentional_tilt=False,automatic_release_classifier=False)
    for key in ('linear_velocity_mm_s','angular_velocity_deg_s','linear_acceleration_mm_s2','angular_acceleration_deg_s2',
            'force_stop_n','moment_delta_stop_nm','width_drift_stop_mm','axis_registration_tolerance_mm'):
        value=plan['contact'].get(key)
        if value is None:missing.append('completion_condition:'+key)
        else:positive(value,key)
    for key in ('resume_position_tolerance_mm','resume_rotation_tolerance_deg','resume_width_tolerance_mm'):
        positive(r[key],key)
    if not r.get('resume_tolerance_source'):raise ValueError('CONTINUATION_TOLERANCE_SOURCE_REQUIRED')
    if not r.get('parameter_source'):missing.append('completion_parameter_source')
    review=r.get('field_review')
    flags=('partial_contact_state_checked','axis_after_partial_checked','grasp_maintained','board_fixed','conditions_confirmed')
    if not review or not review.get('evidence_ref') or any(review.get(k) is not True for k in flags):missing.append('completion_field_review')
    validation=r.get('release_validation')
    if (not validation or validation.get('method')!='VALIDATED_OPERATOR_OBSERVATION' or not validation.get('evidence_ref')
            or validation.get('validated_on_real_logs') is not True):missing.append('validated_all_studs_release_observation_method')
    if r.get('clearance_mm') is None:missing.append('measured_release_clearance')
    else:positive(r['clearance_mm'],'clearance_mm')
    if not r.get('recovery_route_source') or r.get('recovery_waypoints') is None:missing.append('measured_recovery_route')
    else:
        if not r['recovery_waypoints']:raise ValueError('NONEMPTY_MEASURED_RECOVERY_ROUTE_REQUIRED')
        for point in r['recovery_waypoints']:
            if point.get('frame')!='BASE' or not point.get('evidence_ref'):raise ValueError('MEASURED_BASE_RECOVERY_WAYPOINT_REQUIRED')
            vector(point['tcp_pose_mm_zyz_deg'],6,'recovery pose')
    axis=r.get('completion_axis')
    if axis is None:missing.append('measured_axis_after_partial_release')
    else:
        if axis.get('source_kind')!='OPERATOR_FIELD_MEASUREMENT' or not axis.get('evidence_ref') or not axis.get('coordinate_frame'):
            raise ValueError('INDEPENDENT_COMPLETION_AXIS_EVIDENCE_AND_FRAME_REQUIRED')
        frame=pose_matrix(axis['frame_pose_in_base_mm_zyz_deg'])
        if axis['coordinate_frame']=='BASE' and not np.allclose(frame,np.eye(4),atol=1e-9):raise ValueError('BASE_AXIS_IDENTITY_TRANSFORM_REQUIRED')
        line=transform_points(frame,axis['points_mm']).tolist()
    angle=r.get('rotation_deg');step=r.get('angular_step_deg')
    if angle is None or step is None:missing.append('completion_rotation_and_spacing')
    else:
        if type(angle) not in (float,int) or not math.isfinite(angle) or not 0<abs(angle)<90:raise ValueError('SIGNED_COMPLETION_ROTATION_BELOW90_REQUIRED')
        positive(step,'angular_step_deg')
    if partial_evidence is None:missing.append('stage6_real_partial_holding_run')
    else:
        old=partial_evidence['preview'];result=partial_evidence['result'];events=partial_evidence['events']
        if (result.get('backend')!='REAL' or result.get('physical_commands',0)<=0
                or result.get('status')!='PARTIAL_REMOVAL_COMMANDS_AND_OPERATOR_REPORT_NOT_INDEPENDENTLY_VERIFIED'
                or result.get('operator_release_observation')!='ONE_SIDE_RELEASED_REMAINING_ENGAGED'
                or result.get('gripper_release_commands')!=0 or result.get('automatic_lift_or_return') is not False):
            raise ValueError('STAGE6_REAL_PARTIAL_HOLD_WITH_REMAINING_ENGAGEMENT_REQUIRED')
        if (old.get('stage')!=6 or old.get('execution_ready') is not True or old.get('target')!=plan['target']
                or old.get('connection')!=plan['connection'] or old.get('grasp_mode')!=plan['grasp_mode']):
            raise ValueError('STAGE6_SCOPE_GRASP_OR_EQUIPMENT_CHANGED')
        observed={(e['data'].get('phase'),e['data'].get('answer')) for e in events if e['event']=='OPERATOR_OBSERVATION'}
        if not {('REMOVAL_GRASP_RELATION_CHECK','REMOVAL_GRASP_MATCH'),('PARTIAL_REMOVAL_RESULT','ONE_SIDE_RELEASED_REMAINING_ENGAGED')}<=observed:
            raise ValueError('STAGE6_GRASP_AND_PARTIAL_OBSERVATIONS_REQUIRED')
        reference=result['final_sample'];vector(reference['posx'],6,'recorded partial TCP')
        if (reference.get('gripper_status')!=2 or not motion_still(reference)
                or abs(reference['gripper_width_mm']-old['regrasp_width_mm'])>old['regrasp_width_tolerance_mm']):
            raise ValueError('STAGE6_STOPPED_HOLDING_FEEDBACK_REQUIRED')
        if not old.get('sources',{}).get('seating_run'):raise ValueError('STAGE6_SEATING_RUN_PROVENANCE_REQUIRED')
        plan.update(grasp_id=old['grasp_id'],reference_sample=deepcopy(reference),stage6_geometry=deepcopy(old['partial_geometry']),
            stage6_contact=deepcopy(old['contact']),stage6_regrasp_width_mm=old['regrasp_width_mm'])
        if axis is not None and angle is not None and step is not None:
            g=old['partial_geometry'];grasp=pose_matrix(g['tcp_to_block_pose_mm_zyz_deg'])
            geometry=dict(schema_version='yellow4-pivot-preview/2',mode='PREVIEW_ONLY',operation='removal',
                source_kind='INDEPENDENT_COMPLETION_FIELD_INPUT_NOT_FULL_RELEASE_VERIFICATION',coordinate_frame='BASE',output_frame='BASE',
                frame_pose_in_output_mm_zyz_deg=[0,0,0,0,0,0],block=plan['target'],
                seated_block_pose_mm_zyz_deg=matrix_pose(pose_matrix(reference['posx'])@grasp),
                tcp_to_block_pose_mm_zyz_deg=g['tcp_to_block_pose_mm_zyz_deg'],block_geometry=g['block_geometry'],
                target_studs=dict(frame='BASE',centers_mm=g['target_stud_centers_mm']),
                operations=dict(assembly=None,removal=dict(tilt_deg=angle,angular_step_deg=step,contact_line=dict(frame='BASE',points_mm=line))))
            plan.update(completion_geometry=preview(geometry,'removal'),geometry_config=geometry,partial_geometry=preview(geometry,'removal'))
    plan.update(execution_ready=not missing,status='FULL_REMOVAL_RECOVERY_PREVIEW' if not missing else plan['status'])
    return plan


def check_continuation(plan,sample):
    """Compare fresh stopped feedback to this run's saved partial state before any write."""
    r=plan['recovery_settings'];old=plan['reference_sample'];mm,deg=pose_error(sample['posx'],old['posx'])
    if not motion_still(sample) or sample['gripper_status']!=2 or any(sample.get(k)!=plan['connection'][k] for k in ('tcp','tool')):
        raise RuntimeError('CONTINUATION_REQUIRES_STOPPED_SAME_HELD_TOOL')
    if (mm>r['resume_position_tolerance_mm'] or deg>r['resume_rotation_tolerance_deg']
            or abs(sample['gripper_width_mm']-old['gripper_width_mm'])>r['resume_width_tolerance_mm']):
        raise RuntimeError('PARTIAL_STATE_CHANGED_NO_AUTOMATIC_CONTINUATION')
    return dict(position_error_mm=mm,so3_error_deg=deg,width_error_mm=sample['gripper_width_mm']-old['gripper_width_mm'])


def prepare_cycle(settings,seating,removal,recovery):
    if tuple(p.get('stage') for p in (seating,removal,recovery))!=(5,6,7):raise ValueError('CYCLE_REQUIRES_STAGE5_STAGE6_STAGE7')
    c=deepcopy(settings['cycle']);count=c['repeat_count']
    if type(count) is not int or count<1:raise ValueError('POSITIVE_INTEGER_CYCLE_COUNT_REQUIRED')
    if c.get('return_zone') not in ('home','supply','assembly'):raise ValueError('EXPLICIT_RECOVERY_RETURN_ZONE_REQUIRED')
    missing=[f'{name}:{item}' for name,p in [('seating',seating),('removal',removal),('recovery',recovery)] for item in p['missing_measurements']]
    if seating.get('press',{}).get('enabled'):missing.append('cycle_press_terminal_needs_separate_manual_state_review')
    if not c.get('reset_source'):missing.append('cycle_reset_inspection_source')
    if not c.get('return_zone_source'):missing.append('cycle_return_zone_source')
    if any(p['target']!=seating['target'] or p['connection']!=seating['connection'] or p['grasp_mode']!=seating['grasp_mode'] for p in (removal,recovery)):
        raise ValueError('CYCLE_SINGLE_BLOCK_TARGET_TOOL_AND_GRASP_MODE_REQUIRED')
    if removal.get('grasp_id')!=recovery.get('grasp_id'):raise ValueError('CYCLE_REMOVAL_GRASP_RELATION_CHANGED')
    if 'stage6_geometry' in recovery and 'partial_geometry' in removal:
        if recovery['stage6_geometry']!=removal['partial_geometry']:raise ValueError('CYCLE_REMOVAL_QUALIFICATION_GEOMETRY_CHANGED')
        if recovery['stage6_contact']!=removal['contact'] or recovery['stage6_regrasp_width_mm']!=removal['regrasp_width_mm']:
            raise ValueError('CYCLE_PARTIAL_CONTACT_CONDITIONS_CHANGED')
    return dict(stage=7,operation='cycle',target=deepcopy(seating['target']),connection=deepcopy(seating['connection']),
        grasp_mode=seating['grasp_mode'],intended_pad_bottom_height_mm=seating['intended_pad_bottom_height_mm'],
        status='CYCLE_PREVIEW' if not missing else 'PREPARED_MISSING_CYCLE_INPUTS',execution_ready=not missing,
        missing_measurements=missing,physical_commands=0,repeat_count=count,cycle_settings=c,
        seating_plan=deepcopy(seating),removal_plan=deepcopy(removal),recovery_plan=deepcopy(recovery),
        assembly_completion=False,removal_completion=False)


def execute_cycle(driver,plan,start_zone,record,observe_supply,operator,set_phase,*,sleep=time.sleep):
    from app.yellow4_contact_trial import execute
    if not plan['execution_ready']:raise ValueError('CYCLE_FIELD_INPUTS_REQUIRED')
    try:
        results=[];zone=start_zone
        for index in range(plan['repeat_count']):
            for name,key in [('seating','seating_plan'),('removal','removal_plan'),('recovery','recovery_plan')]:
                active=deepcopy(plan[key]);events=[]
                if name=='recovery':active['reference_sample']=deepcopy(partial['final_sample'])
                # Retain phase geometry snapshots so asynchronous image workers cannot see the next phase.
                set_phase(active)
                record('CYCLE_PHASE',dict(iteration=index+1,phase=name,preview=active))
                def phase_record(event,data):
                    events.append(dict(event=event,data=deepcopy(data)))
                    record(event,dict(data,cycle_iteration=index+1,cycle_phase=name))
                result=execute(driver,active,zone,phase_record,observe_supply,operator,sleep=sleep)
                results.append(dict(iteration=index+1,phase=name,result=result))
                if name=='seating':
                    if (not result.get('operator_reported_post_release_stable') or result.get('press_result') is not None):
                        raise RuntimeError('CYCLE_SEATING_NOT_READY_FOR_REGRASP')
                    zone='assembly'
                elif name=='removal':
                    if result.get('operator_release_observation')!='ONE_SIDE_RELEASED_REMAINING_ENGAGED':
                        raise RuntimeError('CYCLE_PARTIAL_STATE_NOT_QUALIFIED_FOR_COMPLETION')
                    partial=result
            zone=plan['cycle_settings']['return_zone']
            if index+1<plan['repeat_count']:
                def poll():
                    from scripts.assembly_position_trial import guard
                    s=driver.sample();r=plan['recovery_plan']['runtime']
                    guard(s,plan['connection'],None,automatic=True,force_norm_limit=r['force_stop_n'],required_gripper_status=0)
                    if not motion_still(s) or s['gripper_width_mm']<r['open_mm']-1:raise RuntimeError('CYCLE_RESET_EMPTY_STOPPED_REQUIRED')
                    record('OPERATOR_WAIT_SAMPLE',dict(phase='CYCLE_RESET_INSPECTION',sample=s,iteration=index+1));return s
                answer=operator('CYCLE_RESET_INSPECTION',('SAME_BLOCK_SUPPLY_READY_TARGET_EMPTY_HAND_CLEAR',),poll)
                record('OPERATOR_OBSERVATION',dict(phase='CYCLE_RESET_INSPECTION',answer=answer,sample=poll(),iteration=index+1))
                if answer!='SAME_BLOCK_SUPPLY_READY_TARGET_EMPTY_HAND_CLEAR':raise RuntimeError('CYCLE_RESET_UNKNOWN_NO_RETRY')
        result=dict(status='CYCLE_COMMANDS_AND_OPERATOR_REPORTS_NOT_INDEPENDENTLY_VERIFIED',backend=driver.mode,
            completed_iterations=plan['repeat_count'],physical_commands=sum(x['result']['physical_commands'] for x in results),
            results=results,assembly_completion=False,removal_completion=False)
        record('CYCLE_RESULT',result);return result
    except BaseException as error:
        # Inner motion faults already request STOP. Phase boundaries are stopped;
        # do not resend an unknown STOP or invent an automatic recovery here.
        try:record('CYCLE_ABORT',dict(reason=str(error),assembly_completion=False,removal_completion=False,automatic_open_or_retry=False))
        except Exception as failure:error.add_note('CYCLE_ABORT_LOGGING_FAILED: '+str(failure))
        raise
