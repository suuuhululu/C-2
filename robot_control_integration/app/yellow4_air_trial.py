"""Air-translated pivot trial using the existing MoveL backend; no grip commands."""
from copy import deepcopy
import math
import time
import numpy as np
from app.assembly_motion import motion_still,pose_error
from app.edge_first_seating import preview
from scripts.assembly_position_trial import guard
from scripts.held_corner_stud_trial import integrated_config
from scripts import supply_pick_release_trial as supply


def load_runtime(bundle,settings):
    held=supply.load_config(bundle['sources']['held_config']['path'])
    supplied=supply.load_config(bundle['sources']['supply_config']['path'])
    runtime=integrated_config(held,supplied)
    rates=dict(transit=runtime['transit_velocity'],vertical=runtime['velocity'],
        linear_acceleration=runtime['transit_acceleration'],angular=runtime['angular_velocity'],angular_acceleration=runtime['angular_acceleration'])
    for key,value in settings.get('rates',{}).items():
        if key not in rates:raise ValueError('UNKNOWN_RATE:'+key)
        rates[key]=value
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in rates.values()):raise ValueError('POSITIVE_FINITE_TRIAL_RATES_REQUIRED')
    return runtime,rates


def prepare_air(bundle,settings,operation='assembly'):
    if settings.get('schema_version')!='yellow4-air-trial/1' or operation not in ('assembly','removal'):
        raise ValueError('AIR_TRIAL_SETTINGS_AND_OPERATION_REQUIRED')
    for key in ('minimum_block_clearance_mm','sample_max_duration_s','position_tolerance_mm','rotation_tolerance_deg','motion_timeout_margin_s'):
        if type(settings[key]) not in (int,float) or not math.isfinite(settings[key]) or settings[key]<=0:raise ValueError('POSITIVE_SETTING_REQUIRED:'+key)
    runtime,rates=load_runtime(bundle,settings)
    result=dict(status='PREPARED_MISSING_FIELD_GEOMETRY',target=deepcopy(bundle['target']),grasp_mode=bundle['grasp_mode'],
        intended_pad_bottom_height_mm=bundle['intended_pad_bottom_height_mm'],connection=deepcopy(bundle['connection']),
        rates=rates,rate_basis='EXISTING_HELD_INTEGRATED_USER120_VERTICAL12_WITH_EXPLICIT_OVERRIDES',
        force_stop_n=runtime['force_stop_n'],operation=operation,sources=deepcopy(bundle['sources']),
        route_xy=deepcopy(runtime['startup_route']),supply_observation_pose=runtime['observation_pose'],
        transport_height_mm=runtime['pickup_clearance_z_mm'],air_tcp_z_mm=runtime['pickup_clearance_z_mm'] if settings.get('air_tcp_z_mm') is None else settings['air_tcp_z_mm'],
        previous_route_stop_evidence=runtime.get('return_high_blocked_reason'),
        settings=deepcopy(settings),execution_ready=False,physical_commands=0,assembly_completion=False,
        air_motion_physically_verified=False,collision_free_verified=False,missing_measurements=deepcopy(bundle['missing_measurements']))
    geometry=bundle.get('geometry_config')
    if geometry is None or geometry['operations'].get(operation) is None:return result
    ground=preview(geometry,operation)
    height=result['air_tcp_z_mm']
    if type(height) not in (int,float) or not math.isfinite(height):raise ValueError('FINITE_AIR_TCP_HEIGHT_REQUIRED')
    shift=np.array([0.,0.,height-ground['seated_reference_tcp_mm_zyz_deg'][2]])
    if shift[2]<=0:raise ValueError('AIR_TRIAL_MUST_RAISE_WHOLE_GEOMETRY')
    air=deepcopy(geometry)
    air['operation']=operation
    air['source_kind']='DERIVED_AIR_TRANSLATION_OF_FIELD_GEOMETRY_NOT_CONTACT_VERIFIED'
    # This translates the whole experiment; it never changes the grasp transform.
    air['seated_block_pose_mm_zyz_deg'][:3]=(np.array(air['seated_block_pose_mm_zyz_deg'][:3])+shift).tolist()
    for value in air['operations'].values():
        if value is not None:value['contact_line']['points_mm']=(np.array(value['contact_line']['points_mm'])+shift).tolist()
    air['target_studs']['centers_mm']=(np.array(air['target_studs']['centers_mm'])+shift).tolist()
    orbit=preview(air,operation)
    minimum=min(p[2] for point in orbit['waypoints'] for p in point['block_corners_mm'])
    surface=max(p[2] for p in ground['target_stud_centers_mm'])
    clearance=minimum-surface-orbit['chord_error_bound_mm']
    if clearance<=settings['minimum_block_clearance_mm']:raise ValueError('AIR_BLOCK_CLEARANCE_INSUFFICIENT')
    result.update(status='AIR_PIVOT_TRIAL_PREVIEW',execution_ready=True,ground_geometry=ground,air_geometry=orbit,
        air_config=air,air_translation_xyz_mm=shift.tolist(),minimum_block_clearance_mm=clearance,
        virtual_air_studs_are_physical_studs=False,grasp_relation_changed=False)
    return result


def route(plan,start,start_zone):
    if not plan['execution_ready']:raise ValueError('FIELD_GRASP_RELATION_AND_SELECTED_AXIS_REQUIRED')
    if start_zone not in ('home','supply','assembly'):raise ValueError('EXPLICIT_START_ZONE_REQUIRED')
    orbit=plan['air_geometry'];reference=orbit['seated_reference_tcp_mm_zyz_deg']
    maximum=max(p['tcp_mm_zyz_deg'][2] for p in orbit['waypoints'])
    high=max(start[2],plan['transport_height_mm'],maximum)
    result=[]
    if start_zone=='home':
        # Visit the actual supply observation before the three held transport points.
        view=plan['supply_observation_pose'];high=max(high,view[2])
        result.extend([('START_VERTICAL_LIFT',[*start[:2],high,*start[3:]]),
            ('TO_SUPPLY_TRANSIT',[*plan['route_xy']['supply_transit_xy'],high,*start[3:]]),
            ('SUPPLY_OBSERVATION',[*view[:2],high,*view[3:]])])
    else:result.append(('START_VERTICAL_LIFT',[*start[:2],high,*start[3:]]))
    if start_zone in ('home','supply'):
        for label,xy in [('SUPPLY_TRANSIT',plan['route_xy']['supply_transit_xy']),
                ('BODY_BYPASS',plan['route_xy']['body_bypass_xy']),('ASSEMBLY_OBSERVATION',reference[:2])]:
            result.append((label,[*xy,high,*reference[3:]]))
    else:result.append(('ASSEMBLY_OBSERVATION',[*reference[:2],high,*reference[3:]]))
    result.append(('AIR_REFERENCE',reference))
    result.extend((f'PIVOT_{i:03d}',p['tcp_mm_zyz_deg']) for i,p in enumerate(orbit['waypoints']))
    result.append(('AIR_RETURN_REFERENCE',reference))
    return result


def execute(driver,plan,start_zone,record,*,expected_gripper_status=2,clock=time.monotonic,sleep=time.sleep):
    if not plan['execution_ready']:raise ValueError('FIELD_GRASP_RELATION_AND_SELECTED_AXIS_REQUIRED')
    settings=plan['settings'];connection=plan['connection'];commands=0;attempted=False
    def sample(automatic):
        while True:
            value=driver.sample()
            # Refresh slow stopped reads without issuing another physical command.
            if value['query_duration_s']<=min(settings['sample_max_duration_s'],.5):
                guard(value,connection,None,automatic=automatic,force_norm_limit=plan['force_stop_n'],required_gripper_status=expected_gripper_status)
                return value
            if math.dist(value['wrench'][:3],[0.,0.,0.])>=plan['force_stop_n']:raise RuntimeError('FORCE_NORM_STOP_LIMIT_REACHED')
            if (value['tcp']!=connection['tcp'] or value['tool']!=connection['tool'] or value['gripper_status']!=expected_gripper_status
                or value['robot_state'] not in (1,2) or value['drl_state']!=3 or automatic and value['robot_mode']!=1):
                raise RuntimeError('STALE_SAMPLE_EQUIPMENT_NOT_READY')
            record('FEEDBACK_REFRESH_WAIT',dict(sample=value,motion_command_resent=False))
            if not motion_still(value):raise RuntimeError('STALE_MOVING_FEEDBACK')
            sleep(.02)
    def stopped(automatic):
        while True:
            value=sample(automatic)
            if motion_still(value):return value
            record('SETTLING_WAIT',value);sleep(.02)
    try:
        first=stopped(False);segments=route(plan,first['posx'],start_zone)
        record('START',dict(sample=first,route=[dict(label=l,tcp=p) for l,p in segments],grasp_mode=plan['grasp_mode']))
        for label,target in segments:
            error=pose_error(driver.check_pose(target),target)
            record('IK_FK_CHECK',dict(label=label,target=target,position_error_mm=error[0],so3_error_deg=error[1]))
            if error[0]>settings['position_tolerance_mm'] or error[1]>settings['rotation_tolerance_deg']:
                raise RuntimeError('IK_FK_TARGET_MISMATCH')
        driver.call('system/set_robot_mode','SetRobotMode',robot_mode=1)
        for label,target in segments:
            before=stopped(True);error=pose_error(before['posx'],target)
            if error[0]<=settings['position_tolerance_mm'] and error[1]<=settings['rotation_tolerance_deg']:
                record('ALREADY_AT_TARGET',dict(label=label,sample=before));continue
            rates=plan['rates'];vertical=math.dist(before['posx'][:2],target[:2])<=settings['position_tolerance_mm'] and abs(target[2]-before['posx'][2])>settings['position_tolerance_mm']
            speed=rates['vertical'] if vertical or label.startswith('PIVOT_') or label=='AIR_RETURN_REFERENCE' else rates['transit']
            deadline=clock()+max(error[0]/speed,error[1]/rates['angular'])*3+settings['motion_timeout_margin_s']
            record('MOVE_REQUEST',dict(label=label,target=target,velocity=[speed,rates['angular']],acceleration=[rates['linear_acceleration'],rates['angular_acceleration']]))
            attempted=True;driver.move_line_async(target,[speed,rates['angular']],[rates['linear_acceleration'],rates['angular_acceleration']]);commands+=1
            while True:
                actual=sample(True);mm,deg=pose_error(actual['posx'],target)
                record('MOTION_SAMPLE',dict(label=label,target=target,sample=actual,position_error_mm=mm,so3_error_deg=deg,
                    gripper_width_drift_mm=actual['gripper_width_mm']-first['gripper_width_mm']))
                if motion_still(actual) and mm<=settings['position_tolerance_mm'] and deg<=settings['rotation_tolerance_deg']:break
                if clock()>deadline:raise TimeoutError('MOTION_TIMEOUT')
                sleep(.02)
            record('WAYPOINT_REACHED',dict(label=label,target=target,sample=actual,position_error_mm=mm,so3_error_deg=deg))
        result=dict(status='AIR_ROUTE_COMMANDS_COMPLETED_NOT_INDEPENDENTLY_VERIFIED',backend=driver.mode,
            physical_commands=commands+1 if driver.mode=='REAL' else 0,move_line_requests=commands,mode_requests=1,
            gripper_commands=0,final_sample=stopped(True),block_plane_alignment_verified=False,
            contact_axis_maintained_physically_verified=False,assembly_completion=False)
        record('RESULT',result);return result
    except BaseException as error:
        stop_feedback=None;stop_failure=None
        if attempted:
            previous=getattr(driver,'ui_pump',None)
            if hasattr(driver,'stop_ui_pump'):driver.ui_pump=driver.stop_ui_pump
            try:driver.stop();stop_feedback=driver.motion_feedback()
            except Exception as stop_error:stop_failure=str(stop_error)
            finally:
                if hasattr(driver,'stop_ui_pump'):driver.ui_pump=previous
        # A failed journal or closed popup must not prevent the stop request.
        try:
            record('ABORT',dict(reason=str(error),motion_attempted=attempted,assembly_completion=False))
            if stop_feedback is not None:record('STOP_FEEDBACK',stop_feedback)
            if stop_failure is not None:record('STOP_FAILED',dict(reason=stop_failure))
        except Exception as logging_error:error.add_note('ABORT_LOGGING_FAILED: '+str(logging_error))
        if stop_failure is not None:error.add_note('STOP_FAILED: '+stop_failure)
        raise
