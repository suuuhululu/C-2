"""Yellow4 contact trials; partial/full seating and independent partial removal."""
from copy import deepcopy
import math
import time
import numpy as np
from app.assembly_motion import motion_still,pose_error,vector
from app.edge_first_seating import preview,rotate_about_contact_line,pose_matrix,transform_points
from app.yellow4_air_trial import load_runtime
from scripts.assembly_position_trial import guard
from scripts.supply_pick_release_trial import startup_targets


def prepare_contact(bundle,settings,air_evidence=None):
    if settings.get('schema_version')!='yellow4-contact-trial/1' or not settings.get('parameter_source'):
        raise ValueError('CONTACT_SETTINGS_WITH_PARAMETER_SOURCE_REQUIRED')
    c=deepcopy(settings['contact'])
    for key,value in c.items():
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
            raise ValueError('POSITIVE_FINITE_CONTACT_PARAMETER_REQUIRED:'+key)
    if not c['entry_clearance_mm']<c['approach_clearance_mm'] or c['descent_step_mm']>c['entry_clearance_mm']+c['search_below_nominal_mm']:
        raise ValueError('CONTACT_ENTRY_AND_SEARCH_INTERVAL_INVALID')
    runtime,rates=load_runtime(bundle,{'rates':{}})
    runtime['startup_route']['place_xy']=bundle['selected_seated_tcp_candidate'][:2].copy()
    missing=[v for v in bundle['missing_measurements'] if v!='removal_contact_axis']
    review=settings.get('air_trial_review')
    if not review or not review.get('evidence_ref') or review.get('arc_observed') is not True or review.get('grip_maintained') is not True:
        missing.append('stage3_operator_arc_and_grasp_review')
    if air_evidence is None:missing.append('stage3_real_air_run')
    pickup=bundle['selected_pickup_tcp_candidate'].copy();measured=settings.get('measured_supply_pickup')
    if measured is not None:
        if not measured.get('evidence_ref') or bundle.get('measurement') is None or any(measured.get(k)!=bundle['measurement'].get(k)
                for k in ('grasp_id','grasp_mode','pad_bottom_from_block_bottom_mm')):
            raise ValueError('SUPPLY_PICKUP_SAME_MEASURED_GRASP_REQUIRED')
        pickup=vector(measured['tcp_pose_mm_zyz_deg'],6,'measured supply pickup')
    elif bundle['grasp_mode']=='HUMAN_REPLACEMENT':missing.append('measured_human15_supply_pickup')
    plan=dict(status='PREPARED_MISSING_CONTACT_INPUTS',execution_ready=False,physical_commands=0,
        target=deepcopy(bundle['target']),connection=deepcopy(bundle['connection']),sources=deepcopy(bundle['sources']),
        grasp_mode=bundle['grasp_mode'],intended_pad_bottom_height_mm=bundle['intended_pad_bottom_height_mm'],
        grasp_id=None if bundle.get('measurement') is None else bundle['measurement']['grasp_id'],
        pickup_tcp=pickup,supply_row=deepcopy(bundle['supply_row']),runtime=runtime,rates=rates,contact=c,
        parameter_source=settings['parameter_source'],parameter_field_verified=False,settings=deepcopy(settings),
        previous_route_stop_evidence=runtime.get('return_high_blocked_reason'),operation='assembly',
        missing_measurements=missing,assembly_completion=False,automatic_leveling_during_intentional_tilt=False,
        engagement_classifier='OPERATOR_OBSERVATION_NOT_FORCE_THRESHOLD',gripper_release_commands=0)
    geometry=bundle.get('geometry_config')
    if geometry is None or geometry['operations'].get('assembly') is None:return plan
    g=preview(geometry,'assembly');angle=g['waypoints'][0]['tilt_deg']
    if c['partial_rotation_deg']>=abs(angle):raise ValueError('STAGE4_MUST_STOP_BEFORE_FULL_SEATING')
    remaining=angle-math.copysign(c['partial_rotation_deg'],angle)
    step=geometry['operations']['assembly']['angular_step_deg'];count=math.ceil(c['partial_rotation_deg']/step)
    angles=np.linspace(angle,remaining,count+1).tolist();partial=deepcopy(g);partial['waypoints']=[]
    seated=g['waypoints'][-1];reference=g['seated_reference_tcp_mm_zyz_deg'];axis=g['contact_line_points_mm']
    for a in angles:
        tcp=rotate_about_contact_line(reference,axis,a)
        block=rotate_about_contact_line(g['seated_reference_block_mm_zyz_deg'],axis,a)
        transform=pose_matrix(block)@np.linalg.inv(pose_matrix(seated['block_mm_zyz_deg']))
        partial['waypoints'].append(dict(tilt_deg=a,tcp_mm_zyz_deg=tcp,block_mm_zyz_deg=block,
            block_corners_mm=transform_points(transform,seated['block_corners_mm']).tolist()))
    partial['sequence']=['OPERATOR_STUD_ENGAGEMENT','PARTIAL_PIVOT','INSPECT_REMAINING_TILT']
    partial['chord_error_bound_mm']=g['tcp_orbit_radius_mm']*(1-math.cos(math.radians(c['partial_rotation_deg']/count)/2))
    if air_evidence is not None:
        result=air_evidence['result'];old=air_evidence['preview'];context=air_evidence['context']
        if (result.get('backend')!='REAL' or result.get('status')!='AIR_ROUTE_COMMANDS_COMPLETED_NOT_INDEPENDENTLY_VERIFIED'
                or result.get('physical_commands',0)<=0 or context.get('empty_gripper_trial') is not False):
            raise ValueError('STAGE3_REAL_HELD_AIR_RUN_REQUIRED')
        if old['operation']!='assembly' or old['target']!=plan['target'] or old['connection']!=plan['connection'] or old['grasp_mode']!=plan['grasp_mode']:
            raise ValueError('STAGE3_SCOPE_OR_EQUIPMENT_MISMATCH')
        old_g=old['ground_geometry']
        if (max(pose_error(old_g['tcp_to_block_pose_mm_zyz_deg'],g['tcp_to_block_pose_mm_zyz_deg']))>1e-6
                or max(pose_error(old_g['seated_reference_tcp_mm_zyz_deg'],reference))>1e-6
                or not np.allclose(old_g['contact_line_points_mm'],axis,atol=1e-6,rtol=0)
                or old_g['block_geometry']!=g['block_geometry']
                or not np.allclose(old_g['target_stud_centers_mm'],g['target_stud_centers_mm'],atol=1e-6,rtol=0)
                or old_g['waypoints'][0]['tilt_deg']!=angle):raise ValueError('STAGE3_GRASP_OR_ASSEMBLY_AXIS_CHANGED')
    runtime['startup_route']['place_xy']=reference[:2].copy()
    tilt_path=[dict(p,tcp_mm_zyz_deg=[*p['tcp_mm_zyz_deg'][:2],p['tcp_mm_zyz_deg'][2]+c['approach_clearance_mm'],*p['tcp_mm_zyz_deg'][3:]])
        for p in reversed(g['waypoints'])]
    entry=partial['waypoints'][0]['tcp_mm_zyz_deg'].copy();entry[2]+=c['entry_clearance_mm']
    plan.update(partial_geometry=partial,ground_geometry=g,geometry_config=deepcopy(geometry),
        intentional_tilt_waypoints=tilt_path,contact_entry_tcp=entry,remaining_tilt_deg=remaining,
        execution_ready=not missing,status='PARTIAL_CONTACT_TRIAL_PREVIEW' if not missing else plan['status'])
    return plan


def execute(driver,plan,start_zone,record,observe_supply,operator,*,sleep=time.sleep,clock=time.monotonic):
    if not plan['execution_ready']:raise ValueError('CONTACT_FIELD_INPUTS_AND_AIR_REVIEW_REQUIRED')
    c=plan['contact'];runtime=plan['runtime'];rates=plan['rates'];connection=plan['connection']
    expected=0;attempted=False;contact=False;baseline=None;width=None;last=None;moves=0;grips=0
    press_terminal=False;pad_phase=False;nested_stop=None;releases=0;pad_closes=0;pad_moves=0
    def sample(automatic=True,busy=False):
        nonlocal last
        while True:
            last=driver.sample();force=45 if pad_phase else c['force_stop_n'] if contact else runtime['force_stop_n']
            status=last['gripper_status']
            if busy and status not in (0,1,2,3):raise RuntimeError('GRIPPER_FAULT')
            checked=dict(last,gripper_status=expected if busy else status)
            if not press_terminal and math.hypot(*last['wrench'][:3])>=force:raise RuntimeError('FORCE_NORM_STOP_LIMIT_REACHED')
            if contact:
                delta=math.dist(last['wrench'][3:],baseline[3:])
                if delta>=c['moment_delta_stop_nm']:raise RuntimeError('CONTACT_MOMENT_DELTA_STOP')
            if width is not None and abs(last['gripper_width_mm']-width)>=c['width_drift_stop_mm']:
                raise RuntimeError('GRASP_WIDTH_DRIFT_STOP')
            if last['query_duration_s']<=.5:
                guard(checked,connection,None,automatic=automatic,force_norm_limit=None if press_terminal else force,required_gripper_status=expected)
                return last
            guard(dict(checked,query_duration_s=.5),connection,None,automatic=automatic,force_norm_limit=None if press_terminal else force,required_gripper_status=expected)
            if not motion_still(last):raise RuntimeError('STALE_MOVING_FEEDBACK')
            record('FEEDBACK_REFRESH_WAIT',dict(sample=last,motion_command_resent=False));sleep(.02)
    def stopped(automatic=True):
        while True:
            s=sample(automatic)
            if motion_still(s):return s
            record('SETTLING_WAIT',s);sleep(.02)
    def preflight(target):
        mm,deg=pose_error(driver.check_pose(target),target)
        if max(mm,deg)>.05:raise RuntimeError('IK_FK_TARGET_MISMATCH')
    def move(label,target,*,loaded_contact=False):
        nonlocal moves,attempted
        if press_terminal:raise RuntimeError('PRESS_TERMINAL_INSPECTION_ONLY_NO_AUTOMATIC_MOTION')
        before=stopped();preflight(target);mm,deg=pose_error(before['posx'],target)
        if max(mm,deg)<=.05:return before
        vertical=math.dist(before['posx'][:2],target[:2])<=.05
        velocity=[c['linear_velocity_mm_s'],c['angular_velocity_deg_s']] if loaded_contact else [rates['vertical'] if vertical else rates['transit'],rates['angular']]
        acceleration=[c['linear_acceleration_mm_s2'],c['angular_acceleration_deg_s2']] if loaded_contact else [rates['linear_acceleration'],rates['angular_acceleration']]
        record('MOVE_REQUEST',dict(label=label,target=target,velocity=velocity,acceleration=acceleration))
        attempted=True;driver.move_line_async(target,velocity,acceleration);moves+=1
        deadline=clock()+max(mm/velocity[0],deg/velocity[1])*3+10
        while True:
            s=sample();mm,deg=pose_error(s['posx'],target)
            record('MOTION_SAMPLE',dict(label=label,target=target,sample=s,position_error_mm=mm,so3_error_deg=deg,
                gripper_width_drift_mm=None if width is None else s['gripper_width_mm']-width,
                moment_delta_norm_nm=None if baseline is None else math.dist(s['wrench'][3:],baseline[3:])))
            if motion_still(s) and max(mm,deg)<=.05:break
            if clock()>deadline:raise TimeoutError('MOTION_TIMEOUT')
            sleep(.02)
        record('WAYPOINT_REACHED',dict(label=label,target=target,sample=s,position_error_mm=mm,so3_error_deg=deg));return s
    def ask(phase,allowed,*,automatic=True):
        def poll():
            s=stopped(automatic);record('OPERATOR_WAIT_SAMPLE',dict(phase=phase,sample=s));return s
        answer=operator(phase,allowed,poll)
        record('OPERATOR_INPUT',dict(phase=phase,answer=answer,last_sample=last,operator_report_not_automatic_classifier=True))
        s=stopped(automatic);record('OPERATOR_OBSERVATION',dict(phase=phase,answer=answer,sample=s,
            operator_report_not_automatic_classifier=True))
        if answer not in allowed:raise RuntimeError('OPERATOR_OBSERVATION_UNKNOWN_OR_STOP:'+str(answer))
        return answer,s
    def post_release_grip(width_mm,*,empty_pad=False):
        nonlocal expected,attempted,releases,pad_closes
        stopped();record('GRIP_REQUEST',dict(width_mm=width_mm,force_n=runtime['gripper_force_n'],
            context='EMPTY_CLOSED_PAD' if empty_pad else 'OBSERVED_SEATING_RELEASE'))
        attempted=True;driver.command_gripper(width_mm,runtime['gripper_force_n'])
        if empty_pad:pad_closes+=1
        else:releases+=1
        deadline=clock()+10;stable=0
        while True:
            s=sample(busy=True);status=s['gripper_status'];actual=s['gripper_width_mm']
            complete=(status in (0,2) and abs(actual-width_mm)<=plan['press']['profile']['empty_width_tolerance_mm']) if empty_pad else status==0 and actual>=width_mm-1
            stable=stable+1 if complete and motion_still(s) else 0
            record('GRIP_FEEDBACK',dict(sample=s,empty_pad_context=empty_pad))
            if stable>=3:expected=status;return s
            if clock()>deadline:raise TimeoutError('GRIPPER_FEEDBACK_TIMEOUT')
            sleep(.1)
    try:
        if plan.get('stage')==6:
            from app.yellow4_removal_trial import removal_route
            # status2 also describes closed empty pads; establish the physical context first.
            initial=driver.sample();expected=initial['gripper_status']
            if expected not in (0,2):raise RuntimeError('INITIAL_GRIPPER_NOT_IDLE')
            first=stopped(False)
            record('START',dict(sample=first,grasp_mode=plan['grasp_mode'],grasp_id=plan['grasp_id'],
                operation='removal',block_held_is_not_inferred_from_status2=True))
            answer,_=ask('INITIAL_EMPTY_GRIPPER_CHECK',('OPEN_EMPTY','CLOSED_EMPTY_PAD'),automatic=False)
            if (answer=='OPEN_EMPTY' and (expected!=0 or first['gripper_width_mm']<runtime['open_mm']-1)
                    or answer=='CLOSED_EMPTY_PAD' and first['gripper_width_mm']>12):
                raise RuntimeError('OPERATOR_EMPTY_STATE_AND_WIDTH_MISMATCH')
            segments=removal_route(plan,first['posx'],start_zone)
            for _,target in segments:preflight(target)
            preflight(plan['regrasp_tcp'])
            for p in plan['partial_geometry']['waypoints']:preflight(p['tcp_mm_zyz_deg'])
            def removal_grip(width_mm,holding):
                nonlocal attempted,expected,grips
                record('GRIP_REQUEST',dict(width_mm=width_mm,force_n=runtime['gripper_force_n'],
                    context='REMOVAL_REGRASP' if holding else 'OBSERVED_EMPTY_PAD_OPEN'))
                attempted=True;driver.command_gripper(width_mm,runtime['gripper_force_n']);grips+=1
                deadline=clock()+10;stable=0
                while True:
                    s=sample(busy=True)
                    complete=(s['gripper_status']==2 and abs(s['gripper_width_mm']-width_mm)<=plan['regrasp_width_tolerance_mm']) if holding else s['gripper_status']==0 and s['gripper_width_mm']>=width_mm-1
                    stable=stable+1 if complete and motion_still(s) else 0
                    record('GRIP_FEEDBACK',dict(sample=s,regrasp_context=holding))
                    if stable>=3:expected=s['gripper_status'];return s
                    if clock()>deadline:raise TimeoutError('REMOVAL_GRIPPER_FEEDBACK_TIMEOUT')
                    sleep(.1)
            driver.call('system/set_robot_mode','SetRobotMode',robot_mode=1)
            if answer=='CLOSED_EMPTY_PAD':removal_grip(runtime['open_mm'],False)
            for label,target in segments:move(label,target)
            ask('SEATED_BLOCK_CURRENT_CHECK',('CURRENT_BLOCK_SEATED_AND_BOARD_FIXED',))
            baseline=stopped()['wrench'];contact=True
            record('CONTACT_BASELINE',dict(sample=last,baseline_wrench=baseline,force_is_release_classifier=False))
            move('REMOVAL_REGRASP_DESCEND',plan['regrasp_tcp'],loaded_contact=True)
            s=removal_grip(plan['regrasp_width_mm'],True);width=s['gripper_width_mm']
            ask('REMOVAL_GRASP_RELATION_CHECK',('REMOVAL_GRASP_MATCH',))
            _,s=ask('PARTIAL_REMOVAL_READY',('REMOVAL_PIVOT_READY',))
            mm,deg=pose_error(s['posx'],plan['regrasp_tcp'])
            if mm>c['axis_registration_tolerance_mm'] or deg>.05:
                raise RuntimeError('REMOVAL_REGRASP_OUTSIDE_REGISTERED_AXIS_REMEASURE_REQUIRED')
            origin=s['posx'].copy();axis=plan['partial_geometry']['contact_line_points_mm']
            record('REMOVAL_AXIS_CHECK',dict(sample=s,axis=axis,position_error_mm=mm,so3_error_deg=deg,
                contact_axis_physically_verified=False))
            for i,p in enumerate(plan['partial_geometry']['waypoints'][1:]):
                move(f'PARTIAL_REMOVAL_{i:03d}',rotate_about_contact_line(origin,axis,p['tilt_deg']),loaded_contact=True)
            answer,final=ask('PARTIAL_REMOVAL_RESULT',('ONE_SIDE_RELEASED_REMAINING_ENGAGED','ALL_RELEASED_OBSERVED','NO_RELEASE_OBSERVED'))
            result=dict(status='PARTIAL_REMOVAL_COMMANDS_AND_OPERATOR_REPORT_NOT_INDEPENDENTLY_VERIFIED',backend=driver.mode,
                physical_commands=moves+grips+1 if driver.mode=='REAL' else 0,move_line_requests=moves,
                gripper_close_commands=1,empty_pad_open_commands=grips-1,gripper_release_commands=0,press_commands=0,
                operator_release_observation=answer,final_sample=final,final_model_tilt_deg=plan['remaining_tilt_deg'],
                actual_block_rpy_deg=None,removal_completion=False,assembly_completion=False,
                all_studs_released_independently_verified=False,automatic_lift_or_return=False,
                automatic_leveling_during_intentional_tilt=False,force_drop_is_release_classifier=False)
            record('RESULT',result);return result
        first=stopped(False)
        if first['gripper_width_mm']<runtime['open_mm']-1:raise RuntimeError('START_WITH_OPEN_EMPTY_GRIPPER_REQUIRED')
        start=startup_targets(runtime,first['posx'],start_zone)
        for _,target in start:preflight(target)
        record('START',dict(sample=first,grasp_mode=plan['grasp_mode'],grasp_id=plan['grasp_id'],route=[dict(label=l,tcp=t) for l,t in start]))
        driver.call('system/set_robot_mode','SetRobotMode',robot_mode=1)
        for label,target in start:move(label,target)
        record('VISION_OBSERVATION_BEGIN',dict(sample=stopped(),vision_attempted=False,stage='WAIT_RGB_AND_ANALYSIS'))
        report=observe_supply(stopped);pickup=vector(report['pickup_tcp_candidate'],6,'vision supply pickup')
        # A measured human15 pose overrides only the taught pose; metric assistance is XY only.
        pickup=[pickup[0]+plan['pickup_tcp'][0]-plan['supply_row']['pickup_pose'][0],
            pickup[1]+plan['pickup_tcp'][1]-plan['supply_row']['pickup_pose'][1],*plan['pickup_tcp'][2:]]
        record('VISION_DECISION',dict(**report['supply_decision'],commanded_pickup_pose=pickup))
        high=pickup.copy();high[2]=runtime['pickup_clearance_z_mm']
        view=runtime['observation_pose'];low_view=[*view[:2],high[2],*view[3:]]
        for target in (low_view,high,pickup):preflight(target)
        if max(pose_error(stopped()['posx'],view))>.5:raise RuntimeError('SUPPLY_OBSERVATION_POSE_CHANGED')
        move('SUPPLY_OBSERVATION_LOWER',low_view);move('SUPPLY_BLOCK_HIGH',high);move('SUPPLY_BLOCK_DESCEND',pickup)
        record('GRIP_REQUEST',dict(width_mm=plan['supply_row']['close_mm'],force_n=runtime['gripper_force_n']))
        attempted=True;driver.command_gripper(plan['supply_row']['close_mm'],runtime['gripper_force_n']);grips+=1
        deadline=clock()+10;stable=0
        while True:
            s=sample(busy=True);stable=stable+1 if s['gripper_status']==2 and motion_still(s) else 0
            if stable>=3:break
            if clock()>deadline:raise TimeoutError('GRIPPER_FEEDBACK_TIMEOUT')
            sleep(.1)
        expected=2;width=s['gripper_width_mm']
        ask('GRASP_RELATION_CHECK',('GRASP_MATCH',));move('LOADED_SUPPLY_RISE',high)
        ref=plan['ground_geometry']['seated_reference_tcp_mm_zyz_deg'];transfer=max(view[2],high[2],ref[2]+c['approach_clearance_mm'])
        move('LOADED_VERTICAL_LIFT',[*high[:2],transfer,*high[3:]])
        for label,xy in [('SUPPLY_TRANSIT',runtime['startup_route']['supply_transit_xy']),('BODY_BYPASS',runtime['startup_route']['body_bypass_xy']),('ASSEMBLY_OBSERVATION',ref[:2])]:
            move(label,[*xy,transfer,*ref[3:]])
        aligned=[*ref[:2],ref[2]+c['approach_clearance_mm'],*ref[3:]]
        move('ALIGN_ABOVE_TARGET',aligned);ask('ALIGNMENT_CHECK',('ALIGNED',))
        # No leveling/yaw/XY loop runs after the operator accepts alignment.
        for i,p in enumerate(plan['intentional_tilt_waypoints']):move(f'INTENTIONAL_TILT_{i:03d}',p['tcp_mm_zyz_deg'],loaded_contact=True)
        baseline=stopped()['wrench'];contact=True
        record('CONTACT_BASELINE',dict(sample=last,baseline_wrench=baseline,force_is_engagement_classifier=False))
        s=move('CONTACT_ENTRY',plan['contact_entry_tcp'],loaded_contact=True)
        floor=plan['partial_geometry']['waypoints'][0]['tcp_mm_zyz_deg'][2]-c['search_below_nominal_mm']
        while True:
            answer,s=ask('STUD_ENGAGEMENT_CHECK',('NO_ENGAGEMENT_NEXT','STUD_ENGAGED'))
            if answer=='STUD_ENGAGED':break
            if s['posx'][2]<=floor+.05:raise RuntimeError('CONTACT_SEARCH_EXHAUSTED_WITHOUT_ENGAGEMENT')
            target=s['posx'].copy();target[2]=max(floor,target[2]-c['descent_step_mm'])
            move('CONTACT_DESCENT_STEP',target,loaded_contact=True)
        nominal=plan['partial_geometry']['waypoints'][0]['tcp_mm_zyz_deg'];mm,deg=pose_error(s['posx'],nominal)
        record('ENGAGEMENT_AXIS_CHECK',dict(sample=s,position_error_mm=mm,so3_error_deg=deg,
            axis=plan['ground_geometry']['contact_line_points_mm'],axis_physically_verified=False))
        if mm>c['axis_registration_tolerance_mm'] or deg>.05:raise RuntimeError('ENGAGEMENT_OUTSIDE_REGISTERED_AXIS_REMEASURE_REQUIRED')
        ask('PARTIAL_PIVOT_READY',('PIVOT_READY',));engaged=stopped()['posx']
        start_angle=plan['partial_geometry']['waypoints'][0]['tilt_deg'];axis=plan['ground_geometry']['contact_line_points_mm']
        for i,p in enumerate(plan['partial_geometry']['waypoints'][1:]):
            move(f'PARTIAL_PIVOT_{i:03d}',rotate_about_contact_line(engaged,axis,p['tilt_deg']-start_angle),loaded_contact=True)
        _,final=ask('PARTIAL_RESULT_INSPECTION',('PARTIAL_OBSERVED',))
        if plan.get('stage')==5:
            from app.yellow4_seating_trial import press_targets
            ask('FULL_PIVOT_READY',('FULL_PIVOT_READY',))
            partial_angle=plan['remaining_tilt_deg'];partial_tcp=stopped()['posx']
            remainder=[p for p in plan['seating_geometry']['waypoints'] if abs(p['tilt_deg'])<abs(partial_angle)]
            for i,p in enumerate(remainder):
                move(f'FULL_PIVOT_{i:03d}',rotate_about_contact_line(partial_tcp,axis,p['tilt_deg']-partial_angle),loaded_contact=True)
            # User observation precedes the one intentional release, never a force-stop recovery.
            ask('SEATING_RELEASE_INSPECTION',('SEATED_READY_TO_RELEASE',))
            before_release=stopped()['posx'];clearance=plan['post_release_clearance_mm'];p=plan['press']['profile']
            targets=press_targets(plan,before_release,p,clearance) if plan['press']['enabled'] else None
            high=targets['high'] if targets else [*before_release[:2],before_release[2]+clearance,*before_release[3:]]
            preflight(high)
            if targets:preflight(targets['start'])
            contact=False;width=None
            post_release_grip(runtime['open_mm'])
            released=stopped()['posx'].copy()
            record('ACTUAL_RELEASE_POSE',dict(sample=last,released_pose=released,block_rpy_deg=None,block_position_independently_verified=False))
            targets=press_targets(plan,released,p,clearance) if plan['press']['enabled'] else None
            high=targets['high'] if targets else [*released[:2],released[2]+clearance,*released[3:]]
            move('POST_RELEASE_VERTICAL_RISE',high)
            ask('POST_RELEASE_INSPECTION',('POST_RELEASE_STABLE',))
            pressed=None
            if plan['press']['enabled']:
                from scripts.assembly_press_trial import press
                ask('CLOSED_PAD_PRESS_READY',('PRESS_READY',))
                pad_phase=True
                post_release_grip(p['empty_width_mm'],empty_pad=True)
                record('CENTERED_VERTICAL_PRESS',dict(released_pose=released,targets=targets,
                    empty_pad_status=expected,force_stop_n=45,constant_force_control=False))
                baseline=stopped()['wrench'];contact=True
                move('CLOSED_PAD_VERTICAL_LOWER',targets['start'],loaded_contact=True)
                press_baseline=baseline
                pad_target=None
                def press_record(event,data):
                    nonlocal pad_moves,nested_stop,pad_target,last
                    if event=='MOVE_REQUEST':pad_moves+=1;pad_target=data['target']
                    if event=='ABORT':nested_stop=data['stop']
                    s=data.get('sample') if isinstance(data,dict) else None
                    if event in ('INITIAL_SAMPLE','INITIAL_STILL_WAIT_SAMPLE'):s=data
                    if s is not None and 'wrench' in s:
                        last=s
                        delta=math.dist(s['wrench'][3:],press_baseline[3:])
                        record('PAD_WRENCH_SAMPLE',dict(sample=s,moment_delta_norm_nm=delta))
                        if delta>=c['moment_delta_stop_nm']:raise RuntimeError('PAD_MOMENT_DELTA_STOP')
                    if event=='MOTION_SAMPLE' and pad_target is not None:
                        mm,deg=pose_error(s['posx'],pad_target)
                        data=dict(data,target=pad_target,position_error_mm=mm,so3_error_deg=deg)
                    record('PAD_'+event,data)
                previous_stop=driver.stop
                def pad_stop():
                    previous_pump=getattr(driver,'ui_pump',None)
                    if hasattr(driver,'stop_ui_pump'):driver.ui_pump=driver.stop_ui_pump
                    try:return previous_stop()
                    finally:
                        if hasattr(driver,'stop_ui_pump'):driver.ui_pump=previous_pump
                driver.stop=pad_stop
                try:
                    pressed=press(driver,connection,press_record,max_travel_mm=p['max_travel_mm'],force_stop_n=45,
                        velocity=p['velocity_mm_s'],acceleration=p['acceleration_mm_s2'],required_gripper_status=expected,
                        clock=clock,sleep=sleep)
                finally:driver.stop=previous_stop
                # A verified pressure stop permits passive inspection only; no automatic retreat/release.
                contact=False;press_terminal=True
                _,final=ask('POST_PRESS_INSPECTION',('POST_PRESS_OBSERVED',))
            else:final=stopped()
            result=dict(status='FULL_SEATING_COMMANDS_AND_OPERATOR_REPORT_NOT_INDEPENDENTLY_VERIFIED',backend=driver.mode,
                physical_commands=moves+grips+releases+pad_closes+pad_moves+1 if driver.mode=='REAL' else 0,
                move_line_requests=moves+pad_moves,gripper_close_commands=grips+pad_closes,gripper_release_commands=releases,
                press_commands=pad_moves,press_result=pressed,remaining_tilt_deg=0,final_sample=final,
                operator_reported_seated=True,operator_reported_post_release_stable=True,
                block_position_independently_verified=False,block_rpy_deg=None,assembly_completion=False,constant_force_control=False)
            record('RESULT',result);return result
        result=dict(status='PARTIAL_PIVOT_COMMANDS_COMPLETED_OPERATOR_REPORT_NOT_SEATING',backend=driver.mode,
            physical_commands=moves+grips+1 if driver.mode=='REAL' else 0,move_line_requests=moves,gripper_close_commands=grips,
            gripper_release_commands=0,press_commands=0,remaining_tilt_deg=plan['remaining_tilt_deg'],final_sample=final,
            assembly_completion=False,loaded_pivot_physically_verified=False,operator_report_received=True)
        record('RESULT',result);return result
    except BaseException as error:
        failure=None;feedback=None
        if attempted and not (nested_stop and nested_stop.get('requested')):
            previous=getattr(driver,'ui_pump',None)
            if hasattr(driver,'stop_ui_pump'):driver.ui_pump=driver.stop_ui_pump
            try:driver.stop();feedback=driver.motion_feedback()
            except Exception as stop_error:failure=str(stop_error)
            finally:
                if hasattr(driver,'stop_ui_pump'):driver.ui_pump=previous
        try:
            record('ABORT',dict(reason=str(error),sample=last,operation=plan['operation'],assembly_completion=False,
                removal_completion=False,release_observation='UNKNOWN',automatic_open_or_retry=False))
            if feedback is not None:record('STOP_FEEDBACK',feedback)
            if failure is not None:record('STOP_FAILED',dict(reason=failure))
            if nested_stop is not None:record('PAD_STOP_STATE',nested_stop)
        except Exception as log_error:error.add_note('ABORT_LOGGING_FAILED: '+str(log_error))
        if failure is not None:error.add_note('STOP_FAILED: '+failure)
        raise
