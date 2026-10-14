"""Held-block alignment, seating and operator-taught closed-pad pressing trial."""
import argparse
from copy import deepcopy
import fcntl
import importlib.util
import json
import math
from collections import deque
import os
from pathlib import Path
import signal
import sys
import time
import threading

NATIVE=Path(__file__).resolve().parents[1]
ROOT=NATIVE.parent
sys.path[:0]=[str(NATIVE),str(ROOT/'perception')]
from app.assembly_motion import motion_still, pose_error
from app.assembly_motion_ros import AssemblyMotionRos
from scripts.assembly_position_trial import guard,run,trial_motion_still
from scripts import supply_pick_release_trial as supply


def motion_completed(sample,config):
    stopped=trial_motion_still if config.get('target_only_motion',False) else motion_still
    return stopped(sample)


def loaded_route(config, current):
    height=config['pickup_clearance_z_mm']
    if current[2]>height:
        if not config.get('target_only_motion',False) and (not config.get('integrated_cycle') or current[2]>height+.5):
            raise ValueError('PICKUP_START_BELOW_TRANSPORT_HEIGHT_REQUIRED')
        height=current[2]
    route=config['startup_route']
    result=[('HELD_VERTICAL_LIFT',[*current[:2],height,*current[3:]])]
    waypoints=[('HELD_SUPPLY',route['supply_transit_xy']),
                     ('HELD_BODY_BYPASS',route['body_bypass_xy']),
                     ('HELD_PLACE',route['place_xy']),
                     ('ASSEMBLY_TARGET_HIGH',config['assembly_target_xy'])]
    if config.get('integrated_cycle'):
        waypoints=[('HELD_SUPPLY',route['supply_transit_xy']),('HELD_BODY_BYPASS',route['body_bypass_xy']),
                   ('HELD_ASSEMBLY_OBSERVATION',config['assembly_target_xy'])]
    for label,xy in waypoints:
        result.append((label,[*xy,height,*current[3:]]))
    return result


def return_high_targets(config,sample,start_zone):
    if start_zone=='home':
        joints=sample.get('posj',[])
        if not config.get('target_only_motion',False) and (len(joints)!=6 or max(abs(a-b) for a,b in zip(joints,[0.,0.,90.,0.,90.,0.]))>.05):
            raise ValueError('CURRENT_HOME_0_0_90_0_90_0_REQUIRED')
        current=sample['posx'];height=max(current[2],config['pickup_clearance_z_mm'])
        targets=[]
        if height-current[2]>.05:
            targets.append(('HOME_VERTICAL_LIFT',[*current[:2],height,*current[3:]]))
        targets.append(('HOME_TARGET_HIGH',[*config['assembly_target_xy'],height,*current[3:]]))
        return targets
    if start_zone!='supply' or (not config.get('target_only_motion',False) and max(pose_error(sample['posx'],config['observation_pose']))>.5):
        raise ValueError('RETURN_HIGH_START_AT_SUPPLY_OBSERVATION_REQUIRED')
    current=sample['posx'];height=config['pickup_clearance_z_mm'];route=config['startup_route']
    targets=[('RETURN_SUPPLY_LOWER',[*current[:2],height,*current[3:]])]
    for label,xy in [('RETURN_SUPPLY_TRANSIT',route['supply_transit_xy']),
                     ('RETURN_BODY_BYPASS',route['body_bypass_xy']),('RETURN_PLACE',route['place_xy'])]:
        targets.append((label,[*xy,height,*current[3:]]))
    orientation=config['blocks'][0]['pickup_pose'][3:]
    targets.append(('RETURN_PLACE_ORIENTATION',[*route['place_xy'],height,*orientation]))
    targets.append(('RETURN_TARGET_HIGH',[*config['assembly_target_xy'],height,*orientation]))
    return targets


def return_high(driver,config,record,start_zone):
    if not config.get('target_only_motion',False) and start_zone!='home' and config.get('return_high_enabled') is False:
        raise RuntimeError('RETURN_HIGH_ROUTE_DISABLED_AFTER_FORCE_STOP: '+config.get('return_high_blocked_reason','review required'))
    limit=supply.motion_force_limit(config)
    first=driver.sample();status=first['gripper_status']
    guard(first,config['connection'],limit,automatic=False,force_norm_limit=limit,required_gripper_status=status)
    if not motion_completed(first,config):raise RuntimeError('RETURN_HIGH_REQUIRES_STOPPED_ROBOT')
    if not config.get('target_only_motion',False) and start_zone=='home' and math.dist(first['wrench'][:3],[0,0,0])>=10.:
        raise RuntimeError('HOME_RESIDUAL_FORCE_TOO_HIGH')
    targets=return_high_targets(config,first,start_zone)
    if not config.get('target_only_motion',False):
        for label,target in targets:
            fk=driver.check_pose(target);error=pose_error(fk,target)
            record('RETURN_ENDPOINT_CHECK',dict(label=label,target=target,fk=fk,error=error))
            if max(error)>.05:raise RuntimeError('RETURN_HIGH_ENDPOINT_IK_FK_MISMATCH:'+label)
    fresh=driver.sample()
    if (fresh['gripper_status']!=status or not motion_completed(fresh,config) or
            (not config.get('target_only_motion',False) and
             (max(pose_error(fresh['posx'],first['posx']))>.05 or
              max(abs(a-b) for a,b in zip(fresh['posj'],first['posj']))>.05))):
        raise RuntimeError('RETURN_HIGH_START_CHANGED')
    try:
        for label,target in targets:
            current=driver.sample()['posx'];rate=config.get('rise_velocity',24.) if abs(target[2]-current[2])>.05 else config.get('transit_velocity',120.)
            record(label,dict(target=target,gripper_status=status))
            run(driver,config['connection'],target,limit,record,clearance_z=target[2] if target[2]>current[2]+.05 else None,
                transfer_only=target[2]>=current[2],required_gripper_status=status,force_norm_stop_n=limit,
                transfer_rate=rate,descent_rate=config.get('descent_velocity',6.),transfer_acceleration=48.,descent_acceleration=48.,
                target_only_motion=config.get('target_only_motion',False),angular_velocity=6.,angular_acceleration=3.)
        record('RETURN_HIGH_COMPLETE',dict(sample=driver.sample(),gripper_commands=0,assembly_completion=False))
        target=config.get('alignment_target',{}).get('target',dict(x=11,y=11))
        print(f"복귀 완료: ({target['x']},{target['y']}) 상공 / 그리퍼 조작 없음",flush=True)
    except BaseException:
        driver.stop();raise


def transfer(driver,config,record,sleep=time.sleep):
    limit=supply.motion_force_limit(config)
    first=wait_for_held_stop(driver,config,record,sleep=sleep)
    guard(first,config['connection'],limit,automatic=True,force_norm_limit=limit,required_gripper_status=2)
    if not motion_completed(first,config): raise RuntimeError('STOPPED_HELD_START_REQUIRED')
    route=loaded_route(config,first['posx'])
    if not config.get('target_only_motion',False):
        for label,target in route:
            fk=driver.check_pose(target);error=pose_error(fk,target)
            record('HELD_ENDPOINT_CHECK',dict(label=label,target=target,fk=fk,error=error))
            if max(error)>.05: raise RuntimeError('HELD_ENDPOINT_IK_FK_MISMATCH:'+label)
    fresh=driver.sample()
    if not motion_completed(fresh,config) or (not config.get('target_only_motion',False) and max(pose_error(first['posx'],fresh['posx']))>.05):
        raise RuntimeError('HELD_START_CHANGED')
    try:
        for label,target in route:
            rate=config.get('rise_velocity',24.) if label=='HELD_VERTICAL_LIFT' else config.get('transit_velocity',120.)
            record(label,dict(target=target,velocity_mm_s=rate))
            clearance=target[2] if label=='HELD_VERTICAL_LIFT' and target[2]>driver.sample()['posx'][2]+.05 else None
            run(driver,config['connection'],target,limit,record,clearance_z=clearance,transfer_only=True,
                force_norm_stop_n=limit,required_gripper_status=2,transfer_rate=rate,descent_rate=6.,
                transfer_acceleration=48.,descent_acceleration=48.,target_only_motion=config.get('target_only_motion',False),angular_velocity=6.,angular_acceleration=3.,sleep=sleep)
        record('ASSEMBLY_HIGH_REACHED_HOLDING',driver.sample())
    except BaseException:
        driver.stop();raise


def observation_frame_timing(stamp_ns, now_ros_ns, received_monotonic, now_monotonic):
    return dict(receive_age_s=now_monotonic-received_monotonic,
        camera_header_age_s=(now_ros_ns-stamp_ns)/1e9,
        receive_fresh=0<=now_monotonic-received_monotonic<=.5,
        timestamp_verified=0<=now_ros_ns-stamp_ns<=500_000_000,
        motion_authority=False)


def wait_for_held_stop(driver,config,record,required_gripper_status=2, *, sleep=time.sleep,clock=time.monotonic,automatic=True):
    limit=supply.motion_force_limit(config)
    deadline=clock()+5.
    while True:
        sample=driver.sample()
        guard(sample,config['connection'],limit,automatic=automatic,force_norm_limit=limit,
              required_gripper_status=required_gripper_status)
        if motion_completed(sample,config):return sample
        record('ALIGNMENT_SETTLING_WAIT',sample)
        if clock()>=deadline:raise RuntimeError('ALIGNMENT_STOP_WAIT_TIMEOUT')
        sleep(.05)


def local_held_move(driver,config,target,record,sleep=time.sleep,required_gripper_status=2):
    limit=supply.motion_force_limit(config)
    sample=wait_for_held_stop(driver,config,record,required_gripper_status,sleep=sleep)
    if not config.get('target_only_motion',False):
        error=pose_error(driver.check_pose(target),target)
        if max(error)>.05:raise RuntimeError('LOCAL_ALIGNMENT_ENDPOINT_IK_FK_MISMATCH')
    dz=target[2]-sample['posx'][2]
    # Let run read the settled starting height for descent and level correction.
    run(driver,config['connection'],target,limit,record,
        clearance_z=target[2] if dz>.05 else None,transfer_only=dz>=-.05,
        required_gripper_status=required_gripper_status,force_norm_stop_n=limit,
        transfer_rate=config.get('rise_velocity',24.) if dz>.05 else config.get('transit_velocity',120.),
        descent_rate=config.get('descent_velocity',6.),
        transfer_acceleration=48.,descent_acceleration=48.,target_only_motion=config.get('target_only_motion',False),angular_velocity=6.,angular_acceleration=3.,sleep=sleep)


def target_layer_approach(config,layer,clearance_mm=20.,target_x=11,target_y=11):
    if type(layer) is not int or not 1<=layer<=5:
        raise ValueError('TARGET_LAYER_1_TO_5_REQUIRED')
    if type(clearance_mm) not in (int,float) or not math.isfinite(clearance_mm) or clearance_mm<20.:
        raise ValueError('ALIGNMENT_CLEARANCE_AT_LEAST_20MM_REQUIRED')
    source=Path(config['assembly_target_source'])
    if not source.is_absolute():source=ROOT/source
    rows=json.loads(source.read_text())
    target=dict(color='yellow',brick_type='2x2x1',x=11,y=11,layer=layer,orientation_deg=0)
    from supply_vision.virtual_board_grid import layer_reference
    reference=layer_reference(rows,target)['sample']['posx'].copy()
    if any(type(v) is not int or not 0<=v<=22 for v in (target_x,target_y)):
        raise ValueError('YELLOW2X2_MINIMUM_STUD_TARGET_0_TO22_REQUIRED')
    delta=[0.,0.,0.]
    model_source=None
    if (target_x,target_y)!=(11,11):
        # Same anchored affine grid calculation used by app/cad_trial.py.
        model_source=config['virtual_grid']['board_calibration']
        model_path=Path(model_source)
        if not model_path.is_absolute():model_path=ROOT/model_path
        affine=json.loads(model_path.read_text())['affine_comparison']
        delta=[(target_x-11)*affine['x_step_xyz_mm'][j]+(target_y-11)*affine['y_step_xyz_mm'][j] for j in range(3)]
        reference[:3]=[v+d for v,d in zip(reference[:3],delta)]
    target.update(x=target_x,y=target_y)
    result=deepcopy(config)
    result['assembly_target_xy']=reference[:2]
    if result.get('integrated_cycle'):
        result['startup_route']['place_xy']=reference[:2].copy()
        if 'integrated_pad_contact_pose' in result:
            result['integrated_pad_contact_pose'][:3]=[v+d for v,d in zip(result['integrated_pad_contact_pose'][:3],delta)]
            result['pad_reference_at_target_physically_verified']=(target_x,target_y)==(11,11) and result.get('pad_reference_at_target_physically_verified',False)
    result['alignment_approach_z_mm']=reference[2]+clearance_mm
    result['alignment_target']=dict(target=target,placement_tcp_reference=reference,
        clearance_mm=clearance_mm,source=str(source),current_grasp_relation_verified=False,grid_delta_xyz_mm=delta,grid_model_source=model_source,target_directly_taught=(target_x,target_y)==(11,11))
    return result


def approach_cycle_targets(sample,config,descend_mm=None,approach_z_mm=None):
    current=sample['posx']
    if not config.get('target_only_motion',False) and (math.dist(current[:2],config['assembly_target_xy'])>2.
            or abs(current[2]-config['pickup_clearance_z_mm'])>.5):
        raise RuntimeError('APPROACH_CYCLE_START_AT_ASSEMBLY_HIGH_REQUIRED')
    if descend_mm is not None:
        if type(descend_mm) not in (int,float) or not math.isfinite(descend_mm) or not 0<descend_mm<=20:
            raise ValueError('INCREMENTAL_DESCENT_MUST_BE_WITHIN_20MM')
        target_z=current[2]-descend_mm
    else:
        if approach_z_mm is None:
            approach_z_mm=config.get('alignment_approach_z_mm',100.)
        if type(approach_z_mm) not in (int,float) or not math.isfinite(approach_z_mm):
            raise ValueError('FINITE_APPROACH_Z_REQUIRED')
        target_z=approach_z_mm
    minimum=config.get('alignment_approach_z_mm',100.)
    if not config.get('target_only_motion',False) and not minimum<=target_z<current[2]:
        raise ValueError('APPROACH_BELOW_TARGET_CLEARANCE_OR_ABOVE_HIGH')
    lower=current.copy();lower[:2]=config['assembly_target_xy'];lower[2]=target_z
    if config.get('alignment_use_recorded_attitude'):
        lower[3:]=config['alignment_target']['placement_tcp_reference'][3:]
    return lower,current[2]


def visual_xy_target(sample,config,candidate):
    """Correct a misgrasp's TCP goal while keeping the block/pad world target."""
    if candidate.get('status')!='HELD_EDGE_XY_CANDIDATE':
        raise ValueError('VISUAL_XY_CANDIDATE_REQUIRED')
    delta=candidate['delta_base_xy_mm']
    if len(delta)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in delta):
        raise ValueError('FINITE_VISUAL_XY_TRANSLATION_REQUIRED')
    target=sample['posx'].copy();target[:2]=[target[i]+delta[i] for i in range(2)]
    landing=config['alignment_target']['placement_tcp_reference'].copy()
    landing[:2]=target[:2];landing[3:]=target[3:]
    updated=deepcopy(config)
    updated['alignment_target']['placement_tcp_reference']=landing
    updated['assembly_target_xy']=landing[:2]
    # The block is being aligned to the same fixed target. Moving the empty-pad
    # goal by the grasp correction would press away from that block's centre.
    updated['vision_xy_pad_basis']='FIXED_OPERATOR_PAD_TARGET_AFTER_GRASP_COMPENSATION'
    updated['vision_xy_result']=deepcopy(candidate)
    return target,updated


def initial_yaw_target(sample,config,degrees):
    if type(degrees) not in (int,float) or not math.isfinite(degrees) or not 0<abs(degrees)<=2.:
        raise ValueError('INITIAL_YAW_MUST_BE_WITHIN_2DEG')
    approach_cycle_targets(sample,config)
    target=sample['posx'].copy();target[3]=(target[3]+degrees+180)%360-180
    return target


def measured_base_z_rotation(before,after):
    from scipy.spatial.transform import Rotation
    first=Rotation.from_euler('ZYZ',before[3:],degrees=True)
    last=Rotation.from_euler('ZYZ',after[3:],degrees=True)
    # Near B=180deg, A and C vary together: use the base-frame SO(3) delta.
    return float(math.degrees((last*first.inv()).as_rotvec()[2]))


def stable_angle_history(history):
    import numpy as np
    return bool(len(history)==5 and len({value[0] for value in history})==5
                and np.ptp([value[1] for value in history])<=.5)


def observed_yaw_gain(before_error,after_error,probe_deg):
    change=(after_error-before_error+90)%180-90
    gain=change/probe_deg
    if not .5<=abs(gain)<=2.:
        raise ValueError('IMAGE_YAW_RESPONSE_UNUSABLE')
    return gain


def yaw_trial_step(error,gain,total,*,total_limit_deg=2.):
    if not all(type(value) in (int,float) and math.isfinite(value) for value in (error,total)):
        raise ValueError('FINITE_YAW_TRIAL_VALUES_REQUIRED')
    if abs(error)<=.5:return None
    if gain is not None and (not math.isfinite(gain) or not .5<=abs(gain)<=2.):
        raise ValueError('IMAGE_YAW_RESPONSE_UNUSABLE')
    step=.5 if gain is None else max(-.5,min(.5,-error/gain))
    if total_limit_deg is not None and abs(total+step)>total_limit_deg:raise ValueError('YAW_TRIAL_LIMIT_2DEG')
    return step


def validate_yaw_trial_pose(sample,config):
    if 'alignment_approach_z_mm' not in config:
        raise ValueError('SELECT_TARGET_LAYER_FOR_YAW_TEST')
    z=sample['posx'][2]
    if not config.get('target_only_motion',False) and (math.dist(sample['posx'][:2],config['assembly_target_xy'])>2.
            or not config['alignment_approach_z_mm']-.05<=z<=config['pickup_clearance_z_mm']+.5):
        raise ValueError('YAW_TEST_REQUIRES_TARGET_CLEARANCE_AND_XY')


def observe(driver,config,directory,record, *, approach_cycle=False, descend_mm=None, approach_z_mm=None, virtual_grid=False, yaw_test=False, initial_yaw_deg=0., xy_seat_test=False, support_ready=None):
    import cv2
    import numpy as np
    from sensor_msgs.msg import Image,CameraInfo
    from rclpy.qos import qos_profile_sensor_data
    from supply_vision.edge_grid_angles import compare_edge_grid,track_visible_edge
    from supply_vision.stud_observation import detect_circular_candidates,experimental_config
    spec=importlib.util.spec_from_file_location('stage3_top_geometry',ROOT/'app/top_press_alignment.py')
    geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry)
    surface=json.loads(Path(config['vision']['layout']).read_text())['surface']
    projector=None
    if virtual_grid:
        from supply_vision.virtual_board_grid import VirtualBoardGrid
        projector=VirtualBoardGrid(config['virtual_grid'])
    node=driver.ros.create_node('held_corner_stud_observation')
    messages={};subscriptions=[]
    for key,topic,kind in [('rgb','/camera/color/image_raw',Image),('depth','/camera/aligned_depth_to_color/image_raw',Image),('info','/camera/color/camera_info',CameraInfo)]:
        subscriptions.append(node.create_subscription(kind,topic,lambda msg,key=key:messages.update({key:(msg,time.monotonic())}),qos_profile_sensor_data))
    from rclpy.executors import SingleThreadedExecutor
    camera_executor=SingleThreadedExecutor(context=node.context)
    camera_executor.add_node(node)
    camera_thread=threading.Thread(target=camera_executor.spin,daemon=True)
    camera_thread.start()
    xy_aligned=False;seating_result=None;released=False;pad_reference=None;pad_status=None;press_done=False
    press_result=None;support_active=False;operator_stopped=False;stop_reason=None
    motion_limit=supply.motion_force_limit(config)
    block_target=config['alignment_target']['target']
    block_label=f"{block_target['color']} {block_target['brick_type']}"
    tilt_reference=None;tilt_probe_done=False;tilt_result=None;center_press_plan=None
    auto_yaw=bool(config.get('auto_yaw'));auto_yaw_paused=False;yaw_converged_logged=False
    cycle_high_z=None;yaw_total=0.;yaw_gain=None;pending_probe=None;history=deque(maxlen=5);direction_confirmed=auto_yaw
    window='Held block / studs - B/S ROI, R rotate trial, U rise/finish, ESC stop'
    cv2.namedWindow(window,cv2.WINDOW_NORMAL);cv2.resizeWindow(window,1000,800)
    pending_keys=deque()
    previous_pump=getattr(driver,'ui_pump',None)
    def pump_ui():
        key=cv2.waitKey(1)&255
        if key==27:raise KeyboardInterrupt('OPERATOR_STOP')
        if key!=255:pending_keys.append(key)
    driver.ui_pump=pump_ui
    manual_edge=[];edge_selection=dict(active=False);edge_gray=None;edge_stamp=None
    target_edge_index=None;xy_candidate=None
    def edge_click(event,x,y,flags,param):
        nonlocal edge_gray,edge_stamp
        if event==cv2.EVENT_LBUTTONDOWN and edge_selection['active'] and y>=225:
            manual_edge.append([int(x),int(y-225)])
            if len(manual_edge)==2:
                edge_selection['active']=False
                edge_gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);edge_stamp=stamp
    cv2.setMouseCallback(window,edge_click)
    block_roi=stud_roi=None;axis_index=None;roi_notice='';last_saved=0;last_rgb_time=time.monotonic()
    try:
        if yaw_test or xy_seat_test:
            validate_yaw_trial_pose(driver.sample(),config)
            cycle_high_z=config['pickup_clearance_z_mm']
        if approach_cycle:
            first=driver.sample()
            lower,cycle_high_z=approach_cycle_targets(first,config,descend_mm,approach_z_mm)
            perturb=initial_yaw_target(first,config,initial_yaw_deg) if initial_yaw_deg else None
            if perturb is not None:lower[3:]=perturb[3:]
            aligned_high=lower.copy();aligned_high[2]=cycle_high_z
            if not config.get('target_only_motion',False):
                for target in ([perturb] if perturb is not None else [])+[aligned_high,lower]:
                    if max(pose_error(driver.check_pose(target),target))>.05:
                        raise RuntimeError('APPROACH_CYCLE_ENDPOINT_IK_FK_MISMATCH')
                if max(pose_error(first['posx'],driver.sample()['posx']))>.05:
                    raise RuntimeError('INITIAL_YAW_START_CHANGED')
            if perturb is not None:
                record('INITIAL_YAW_COMMAND',dict(before_pose=first['posx'],target=perturb,command_deg=initial_yaw_deg))
                local_held_move(driver,config,perturb,record)
                after=driver.sample()['posx']
                record('INITIAL_YAW_COMPLETED',dict(command_deg=initial_yaw_deg,
                    actual_base_z_deg=measured_base_z_rotation(first['posx'],after),
                    before_pose=first['posx'],after_pose=after,so3_rotation_deg=pose_error(first['posx'],after)[1]))
            if max(pose_error(driver.sample()['posx'],aligned_high))>.05:
                local_held_move(driver,config,aligned_high,record)
            record('ALIGNMENT_APPROACH_DESCENT',dict(target=lower,return_high_z_mm=cycle_high_z,approach_is_contact_target=False))
            local_held_move(driver,config,lower,record)
        while True:
            # Camera callbacks run independently of slow robot service queries.
            time.sleep(.02)
            sample=wait_for_held_stop(driver,config,record,(pad_status if pad_status is not None else 0) if released else 2,automatic=pad_status is None)
            packet=messages.get('rgb')
            if packet is None:
                if time.monotonic()-last_rgb_time>5:raise TimeoutError('NO_ASSEMBLY_RGB')
                continue
            msg,received=packet
            stamp=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
            timing=observation_frame_timing(stamp,node.get_clock().now().nanoseconds,received,time.monotonic())
            if not timing['receive_fresh']:
                if time.monotonic()-last_rgb_time>5:
                    raise RuntimeError('ASSEMBLY_RGB_RECEIVE_STALLED')
                continue
            last_rgb_time=time.monotonic()
            if msg.encoding not in ('rgb8','bgr8'):raise ValueError('RGB_ENCODING_REQUIRED')
            pixels=np.frombuffer(msg.data,np.uint8).reshape(msg.height,msg.step)[:,:msg.width*3].reshape(msg.height,msg.width,3).copy()
            frame=cv2.cvtColor(pixels,cv2.COLOR_RGB2BGR) if msg.encoding=='rgb8' else pixels
            if len(manual_edge)==2 and edge_gray is not None and stamp!=edge_stamp:
                gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                tracked=track_visible_edge(edge_gray,gray,manual_edge) if stamp>edge_stamp else None
                if tracked is None:
                    manual_edge.clear();history.clear();yaw_gain=None;pending_probe=None
                    roi_notice='Top edge tracking lost. E: select the two top corners again.'
                    record('TOP_EDGE_TRACKING_LOST',dict(frame_stamp_ns=stamp,automatic_motion=False))
                else:manual_edge[:]=tracked
                edge_gray=gray;edge_stamp=stamp
            h,w=frame.shape[:2];full=[0,0,w,h]
            block=geometry.visible_colored_block(frame,block_roi or full,block_target['color'],surface)
            if virtual_grid:
                studs=dict(candidates=[],scope='VIRTUAL_BOARD_GRID_NO_CIRCLE_DETECTION')
                info=messages.get('info',(None,None))[0]
                layer=config.get('alignment_target',{}).get('target',{}).get('layer',1)
                clearance=config.get('alignment_target',{}).get('clearance_mm',20.)
                projected_canvas,angles=projector.overlay(frame,sample,info,layer,clearance,
                    ([manual_edge] if len(manual_edge)==2 else []),axis_index,target_xy=tuple(block_target[k] for k in ('x','y')),target=block_target)
                if len(manual_edge)!=2:
                    angles['reason']='CLICK_TWO_VISIBLE_TOP_EDGE_ENDPOINTS'
                    angles['relative_angle_deg']=None
                elif auto_yaw and axis_index is None and angles.get('relative_angle_deg') is not None:
                    axis_index=angles['selected_grid_axis']
                if config.get('vision_xy_alignment'):
                    from supply_vision.held_xy_alignment import held_edge_xy_candidate
                    depth_msg=messages.get('depth',(None,None))[0];depth_array=None;depth_stamp=None;depth_frame=None
                    if depth_msg is not None and depth_msg.encoding=='16UC1':
                        depth_array=np.frombuffer(depth_msg.data,np.dtype('<u2' if not depth_msg.is_bigendian else '>u2')).reshape(depth_msg.height,depth_msg.step//2)[:,:depth_msg.width]
                        depth_stamp=depth_msg.header.stamp.sec*10**9+depth_msg.header.stamp.nanosec
                        depth_frame=depth_msg.header.frame_id
                    xy_candidate=held_edge_xy_candidate(manual_edge,target_edge_index,info,angles,
                        depth=depth_array,depth_scale_mm=1.,rgb_stamp_ns=stamp,
                        depth_stamp_ns=depth_stamp,depth_frame_id=depth_frame)
                    outline=angles.get('target_hover_outline_uv',[])
                    if len(outline)==4 and all(all(v is not None for v in point) for point in outline):
                        for edge_index in range(4):
                            midpoint=np.mean([outline[edge_index],outline[(edge_index+1)%4]],axis=0).astype(int)
                            cv2.putText(projected_canvas,str(edge_index+1),tuple(midpoint),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),2)
            else:
                hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
                green=cv2.inRange(hsv,np.array([35,40,30],np.uint8),np.array([90,255,255],np.uint8))
                gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                gray=cv2.createCLAHE(clipLimit=2.,tileGridSize=(8,8)).apply(gray)
                gray[green==0]=0
                detector=experimental_config();detector.update(color_order='GRAY',canny_low=10,canny_high=30,minimum_diameter_px=8.,maximum_diameter_px=40.)
                studs=detect_circular_candidates(gray,roi_xyxy=stud_roi or full,config=detector)
                centers=[feature['center_uv'] for feature in studs['candidates'] if not feature['clipped']]
                if block_roi:
                    x0,y0,x1,y1=block_roi
                    centers=[point for point in centers if not (x0<=point[0]<=x1 and y0<=point[1]<=y1)]
                angles=compare_edge_grid(block.get('visible_edges_uv',[]),centers,axis_index) if len(centers) else dict(status='UNKNOWN',reason='NO_STUD_CENTERS',grid={})
                if block_roi is None or stud_roi is None:
                    angles.update(status='UNKNOWN',reason='SELECT_HELD_BLOCK_AND_TARGET_STUD_ROIS',relative_angle_deg=None)
            canvas=projected_canvas if virtual_grid else frame.copy()
            if block.get('visible_contour_uv'):
                contour=np.asarray(block['visible_contour_uv'],np.int32).reshape(-1,1,2)
                cv2.polylines(canvas,[contour],True,(0,255,255),2)
            for first,second in block.get('visible_edges_uv',[]):
                cv2.line(canvas,tuple(first),tuple(second),(0,0,255),2)
            for feature in studs['candidates']:
                center=tuple(int(round(v)) for v in feature['center_uv'])
                cv2.circle(canvas,center,3,(255,0,255),1)
            if angles['status']=='EDGE_GRID_RELATIVE_ANGLE_CANDIDATE':
                edge=np.asarray(angles['block_edge_uv'],int)
                cv2.line(canvas,tuple(edge[0]),tuple(edge[1]),(0,255,255),3)
                origin=np.asarray(angles['grid']['origin_uv'])
                for i,angle in enumerate(angles['grid']['axes_deg']):
                    radians=np.radians(angle);vector=np.array([np.cos(radians),np.sin(radians)])*80
                    cv2.line(canvas,tuple((origin-vector).astype(int)),tuple((origin+vector).astype(int)),(255,255,0) if i==angles['selected_grid_axis'] else (255,100,0),2)
            if angles.get('relative_angle_deg') is not None and timing['timestamp_verified']:
                history.append((stamp,angles['relative_angle_deg']))
            else:
                history.clear()
            stable=stable_angle_history(history)
            if pending_probe is not None and stable:
                try:
                    yaw_gain=observed_yaw_gain(pending_probe, float(np.median([v[1] for v in history])), .5)
                    record('LOCAL_IMAGE_YAW_GAIN_MEASURED',dict(gain=yaw_gain,probe_deg=.5,reference='VIRTUAL_PROJECTION' if virtual_grid else 'IMAGE_DETECTION',physical_transfer_verified=False))
                    roi_notice=f'Yaw response {yaw_gain:+.2f}. '+('Automatic correction active.' if auto_yaw else 'R: next bounded correction; U: rise.')
                except ValueError:
                    yaw_gain=None;auto_yaw_paused=True
                    roi_notice='Rotation response unclear. E: reselect top edge; U: rise.'
                pending_probe=None
            if auto_yaw and stable and abs(float(np.median([v[1] for v in history])))<=.5 and not yaw_converged_logged:
                record('AUTO_YAW_CONVERGED',dict(relative_angle_deg=float(np.median([v[1] for v in history])),
                    tolerance_deg=.5,frame_stamp_ns=stamp,stud_center_coincidence_required=False,
                    roll_pitch_observed=False,assembly_completion=False))
                yaw_converged_logged=True;roi_notice='Yaw aligned. 1-4: corresponding target edge, X: visual XY, I: insert.' if config.get('vision_xy_alignment') else 'Yaw within +/-0.50 deg. X: taught XY, I: insert, U: rise.'
            panel=np.zeros((225,w,3),np.uint8)
            if config.get('tilt_accuracy_test') and tilt_reference is not None:
                from scripts.held_tilt_accuracy import rotation_error
                tilt=rotation_error(tilt_reference,sample['posx'])
                roi_notice=f"Tilt X {tilt['base_x_deg']:+.3f} Y {tilt['base_y_deg']:+.3f} deg | "+(tilt_result['status'] if tilt_result else 'J inject, K correct')
            for i,text in enumerate([f"HELD {block_label} | target ({block_target['x']},{block_target['y']}) | Z "+f"{sample['posx'][2]:.1f}mm",
                ('XY '+(f"dX {xy_candidate['delta_base_xy_mm'][0]:+.2f} dY {xy_candidate['delta_base_xy_mm'][1]:+.2f}mm | "+xy_candidate['height_source'] if xy_candidate and xy_candidate['status']=='HELD_EDGE_XY_CANDIDATE' else str((xy_candidate or {}).get('reason','Select E top edge + 1-4'))) if config.get('vision_xy_alignment') else 'Reference: EXISTING GRID DIRECTION | XY registration not used' if virtual_grid else 'Block: '+block['status']+' | circular candidates: '+str(len(studs['candidates']))),
                ('E: click top-edge endpoints | B: block ROI | SPACE: save' if virtual_grid else 'B: select HELD block | S: target studs | SPACE: capture'),
                ('O: release/vertical rise/close | P: '+('MEASURED PAD target' if config.get('operator_teaching') else 'SAME XY press') if config.get('same_xy_press') else 'O: release/close | T teach TOP | P press' if config.get('integrated_cycle') and not config.get('pad_reference_at_target_physically_verified',True) else 'O: checked release then saved-pad PRESS + rise' if config.get('integrated_cycle') else 'Coordinate XY / insertion armed; O releases only after your check' if xy_seat_test else 'Candidate view; R: local yaw trial, no release / press'),
                'Angle difference: '+(f"{angles['relative_angle_deg']:+.2f} deg" if angles.get('relative_angle_deg') is not None else str(angles.get('reason'))),
                ('AUTO yaw +/-0.50 deg | Roll/pitch: not measured by this edge' if auto_yaw else 'A: switch grid axis | local pixel angle, not robot yaw'),
                ('HUMAN SUPPORT: keep holding lower structure through press/rise | ' if support_active else '')+(roi_notice or ('Cyan: grid | Yellow: hover outline | Magenta: seated outline' if virtual_grid else 'S: include 3+ rows AND columns, not a single stud')),
                'Camera time: '+('verified' if timing['timestamp_verified'] else 'UNVERIFIED - preview only'),
                ('H reference | J tilt+0.5XY | K correct | X/I/O | U rise' if config.get('tilt_accuracy_test') else 'X: XY | I: insert | O: release/lift/close | T: pad touch | P: press | U: rise' if xy_seat_test else 'G: confirm grid DIRECTION | R: 0.5deg trial | U: rise' if yaw_test else 'R: bounded yaw trial | U: rise / finish | ESC: STOP')]):
                cv2.putText(panel,text,(5,20+24*i),cv2.FONT_HERSHEY_SIMPLEX,.46,(255,255,255),1)
            cv2.imshow(window,np.vstack((panel,canvas)))
            key=pending_keys.popleft() if pending_keys else cv2.waitKey(1)&255
            if key==27 or cv2.getWindowProperty(window,cv2.WND_PROP_VISIBLE)<1:
                operator_stopped=True;stop_reason='ESC_OR_WINDOW_CLOSED';break
            automatic_request=(auto_yaw and not auto_yaw_paused and key==255 and stable and pending_probe is None
                and len(manual_edge)==2 and seating_result is None and not released
                and abs(float(np.median([v[1] for v in history])))>.5)
            if automatic_request:key=ord('r')
            if key==ord('e'):
                manual_edge.clear();edge_selection['active']=True
                edge_gray=None;edge_stamp=None
                auto_yaw_paused=False;yaw_converged_logged=False
                history.clear();yaw_gain=None;pending_probe=None;direction_confirmed=auto_yaw
                xy_aligned=False
                if config.get('vision_xy_alignment'):
                    axis_index=target_edge_index%2 if target_edge_index is not None else None
                roi_notice='Click TWO visible body TOP edge endpoints (not front/bottom).'
                continue
            if config.get('vision_xy_alignment') and key in (ord('1'),ord('2'),ord('3'),ord('4')):
                selected_edge_index=key-ord('1')
                if target_edge_index is not None and selected_edge_index!=target_edge_index:
                    manual_edge.clear();edge_gray=None;edge_stamp=None
                    edge_selection['active']=False
                target_edge_index=selected_edge_index;xy_aligned=False
                axis_index=target_edge_index%2;history.clear();yaw_gain=None;pending_probe=None
                auto_yaw_paused=False;yaw_converged_logged=False
                roi_notice=f'Target edge {target_edge_index+1} selected. E: same physical TOP edge endpoints; X: apply XY.'
                continue
            if key==ord('u'):
                if cycle_high_z is not None:
                    target=driver.sample()['posx'].copy();target[2]=cycle_high_z
                    record('ALIGNMENT_RETURN_RISE',dict(target=target))
                    local_held_move(driver,config,target,record,required_gripper_status=(pad_status if pad_status is not None else 0) if released else 2)
                break
            if key==ord('g'):
                if not yaw_test or len(manual_edge)!=2 or not stable:
                    roi_notice='Select top edge with E; wait for a stable angle before G.'
                    continue
                direction_confirmed=True
                record('GRID_DIRECTION_OPERATOR_REVIEW',dict(frame_stamp_ns=stamp,axes_deg=angles.get('axes_deg'),basis='OPERATOR_VISUAL_PARALLELISM_ONLY',xy_registration_verified=False))
                roi_notice='Direction review recorded. R: first 0.5deg probe.'
            if key==ord('x'):
                if not xy_seat_test or released or seating_result is not None:
                    roi_notice='XY/seat trial not armed, or insertion already attempted.'
                    continue
                if config.get('vision_xy_alignment'):
                    if not timing['timestamp_verified'] or not xy_candidate or xy_candidate['status']!='HELD_EDGE_XY_CANDIDATE':
                        roi_notice='Fresh image, camera info and E top edge + matching 1-4 target edge are needed for XY.'
                        continue
                    target,updated=visual_xy_target(sample,config,xy_candidate)
                    record('VISUAL_XY_CORRECTION',dict(candidate=xy_candidate,target=target,vision_xy_used=True,
                        physical_accuracy_verified=False,frame_stamp_ns=stamp))
                    local_held_move(driver,config,target,record)
                    config=updated;messages.pop('rgb',None);last_rgb_time=time.monotonic()
                    history.clear();yaw_gain=None;pending_probe=None;yaw_converged_logged=False
                    record('VISUAL_XY_LANDING_PRESERVED',dict(landing=config['alignment_target']['placement_tcp_reference'],
                        pad_contact=config['integrated_pad_contact_pose'],
                        pad_basis=config['vision_xy_pad_basis'],assembly_completion=False))
                    xy_aligned=True;roi_notice='Visual XY applied; I preserves corrected XY. Projection is unverified; review the new image.'
                else:
                    from scripts.held_xy_seating_trial import xy_target
                    target=xy_target(driver.sample(),config)
                    record('COORDINATE_XY_CORRECTION',dict(target=target,vision_xy_used=False))
                    local_held_move(driver,config,target,record)
                    xy_aligned=True;roi_notice='Taught XY reached. Review yaw; I attempts slow insertion.'
            if key in (ord('h'),ord('j'),ord('k')) and config.get('tilt_accuracy_test'):
                if (seating_result is not None and not released) or (released and pad_reference is None):
                    roi_notice='Tilt before insertion, or after T has lifted empty pads10mm.';continue
                tilt_status=pad_status if released else 2
                fresh=wait_for_held_stop(driver,config,record,tilt_status)
                if released:
                    if not config.get('target_only_motion',False) and fresh['posx'][2]<pad_reference[2]+9.5:
                        roi_notice='Empty-pad tilt requires T rise10mm.';continue
                else:validate_yaw_trial_pose(fresh,config)
                from scripts.held_tilt_accuracy import perturbed_pose,rotation_error,accuracy_result
                if key==ord('h'):
                    tilt_reference=fresh['posx'].copy();tilt_probe_done=False;tilt_result=None
                    record('TILT_OPERATOR_REFERENCE',dict(pose=tilt_reference,absolute_surface_level_verified=False,scope='EMPTY_PAD_UNLOADED' if released else 'HELD_BLOCK_UNLOADED'))
                    roi_notice='Reference saved. J injects +0.5deg about base X/Y; K corrects.'
                elif tilt_reference is None:
                    roi_notice='H records an operator-selected reference first.'
                elif key==ord('j'):
                    if not config.get('target_only_motion',False) and math.dist(fresh['posx'][:3],tilt_reference[:3])>.1:
                        roi_notice='Position changed. Record H again.';continue
                    goal=perturbed_pose(tilt_reference,.5,.5)
                    local_held_move(driver,config,goal,record,required_gripper_status=tilt_status)
                    actual=wait_for_held_stop(driver,config,record,tilt_status)['posx']
                    record('TILT_PROBE_COMPLETED',dict(command_base_x_deg=.5,command_base_y_deg=.5,actual=actual,error=rotation_error(tilt_reference,actual),command_tracking_error_deg=pose_error(actual,goal)[1],unloaded=True))
                    tilt_probe_done=True;tilt_result=None
                else:
                    if not tilt_probe_done:
                        roi_notice='J injects the tilt before K correction.';continue
                    goal=[*fresh['posx'][:3],*tilt_reference[3:]]
                    local_held_move(driver,config,goal,record,required_gripper_status=tilt_status)
                    actual=wait_for_held_stop(driver,config,record,tilt_status)['posx']
                    tilt_result=accuracy_result(tilt_reference,actual)
                    record('TILT_ACCURACY_RESULT',tilt_result)
                    roi_notice=tilt_result['status']+' | visually check; then P press.' if released else tilt_result['status']+' | visually check block; then X/I.'
                continue
            if key==ord('i'):
                if not xy_seat_test or not xy_aligned or released:
                    roi_notice='I requires taught XY correction X and a held block.'
                    continue
                if support_ready is not None and not support_active:
                    record('TRIAL_HUMAN_SUPPORT_REQUEST',dict(target=deepcopy(block_target),policy='USER_SELECTED_HOLD_LOWER_STRUCTURE_DURING_ROBOT_FASTENING'))
                    if support_ready(config) is not True:
                        operator_stopped=True;stop_reason='HUMAN_SUPPORT_CANCELLED';break
                    support_active=True
                    record('TRIAL_HUMAN_SUPPORT_READY',dict(target=deepcopy(block_target),maintain_through='SEATING_PRESS_AND_RISE'))
                from scripts.held_xy_seating_trial import insert
                seating_result=insert(driver,config,record)
                roi_notice=seating_result['status']+' | O: visually checked release/lift/close; U: rise'
            if key==ord('o'):
                if not xy_seat_test or released or not seating_result or seating_result['status'] not in ('SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED','FORCE_STOPPED_BEFORE_VERIFIED_SEATING'):
                    roi_notice='O requires insertion result and your visual release check.'
                    continue
                from scripts.held_xy_seating_trial import release
                from app.raised_grasp_press import require_landing_before_release
                require_landing_before_release(config,seating_result)
                if config.get('same_xy_press'):
                    from scripts.held_xy_seating_trial import same_xy_press_plan
                    release_pose=wait_for_held_stop(driver,config,record)['posx']
                    center_press_plan=same_xy_press_plan(release_pose,config)
                    record('RELEASE_CENTER_DATUM_SAVED',center_press_plan)
                release(driver,config,record,operator_seated=True);released=True
                if center_press_plan is not None:target=center_press_plan['rise_pose']
                else:
                    target=driver.sample()['posx'].copy();target[2]=cycle_high_z or config['pickup_clearance_z_mm']
                local_held_move(driver,config,target,record,required_gripper_status=0)
                driver.command_gripper(4.,config['gripper_force_n'])
                deadline=time.monotonic()+10.
                while True:
                    closed=driver.sample()
                    guard(dict(closed,gripper_status=0),config['connection'],motion_limit,automatic=True,force_norm_limit=motion_limit,required_gripper_status=0)
                    if closed['gripper_status'] not in (0,1,2):raise RuntimeError('GRIPPER_FAULT')
                    if closed['gripper_status'] in (0,2) and closed['gripper_width_mm']<=12. and motion_completed(closed,config):break
                    if time.monotonic()>=deadline:raise TimeoutError('EMPTY_PAD_CLOSE_TIMEOUT')
                    time.sleep(.05)
                pad_status=closed['gripper_status']
                record('EMPTY_PAD_CLOSED_AFTER_RELEASE',dict(sample=closed,close_command_mm=4.,empty_by_release_sequence=True))
                if center_press_plan is not None:
                    roi_notice='Same release XY/attitude saved. P: straight descent/press/rise; no T needed.'
                    continue
                if config.get('integrated_cycle') and config.get('pad_reference_at_target_physically_verified',True):
                    press_result=closed_pad_cycle(driver,config,config['integrated_pad_contact_pose'],pad_status,record)
                    press_done=True
                    break
                roi_notice='Pads closed. Touch TOP manually, stop, return AUTO, then T records/lifts.'
            if key==ord('t'):
                if not released or pad_status is None:
                    roi_notice='T requires O release/lift/close first.';continue
                press_done=False
                pad_reference=wait_for_held_stop(driver,config,record,pad_status)['posx'].copy()
                record('EMPTY_PAD_TOP_TOUCH_OPERATOR_CAPTURE',dict(pose=pad_reference,operator_asserted_top_contact=True,
                    target=config['alignment_target']['target'],automatic_geometry_verified=False))
                target=pad_reference.copy();target[2]+=10.
                local_held_move(driver,config,target,record,required_gripper_status=pad_status)
                roi_notice=f"Top-touch recorded; lifted10mm. P presses to{config['force_stop_n']:g}N reaction then rises."
            if key==ord('p'):
                if center_press_plan is not None:
                    if press_done:
                        roi_notice='Same-XY pressure trial already executed.';continue
                    from scripts.held_xy_seating_trial import same_xy_press_cycle
                    result=same_xy_press_cycle(driver,config,center_press_plan,pad_status,record,local_held_move)
                    press_result=result;press_done=True;roi_notice='Same-XY trial: '+result['status']+' | U rise/finish'
                    continue
                if pad_reference is None or press_done:
                    roi_notice='P requires T top-touch capture; pressing already done requires fresh T.';continue
                from scripts.held_xy_seating_trial import press_from_top_touch
                start=wait_for_held_stop(driver,config,record,pad_status)
                if not config.get('target_only_motion',False) and max(pose_error(start['posx'],[*pad_reference[:2],pad_reference[2]+10.,*pad_reference[3:]]))>.1:
                    roi_notice='Pose changed: touch TOP and record with T again.';continue
                result=press_from_top_touch(driver,config,pad_reference,record,pad_status)
                press_done=True
                target=driver.sample()['posx'].copy();target[2]=pad_reference[2]+10.
                local_held_move(driver,config,target,record,required_gripper_status=pad_status)
                record('EMPTY_PAD_PRESS_AND_RISE_RESULT',dict(result=result,assembly_completion=False,automatic_tilt_alignment=False))
                press_result=result
                roi_notice='Press/rise finished: '+result['status']
            if key==ord('r'):
                if seating_result is not None or released:
                    roi_notice='No rotation after insertion. U to rise.'
                    continue
                record('YAW_REQUEST',dict(stable=stable,direction_confirmed=direction_confirmed,relative_angle_deg=angles.get('relative_angle_deg'),manual_edge_points=len(manual_edge)))
                if virtual_grid and (not yaw_test or not direction_confirmed):
                    roi_notice='Yaw test requires E top edge + G direction review.'
                    record('YAW_SKIPPED',dict(reason='DIRECTION_REVIEW_REQUIRED'))
                    continue
                roi_ready=(len(manual_edge)==2) if virtual_grid else (block_roi is not None and stud_roi is not None)
                if cycle_high_z is None or not stable or not roi_ready or pending_probe is not None:
                    roi_notice='R requires approach cycle + stable selected edge/grid.'
                    record('YAW_SKIPPED',dict(reason='STABLE_REFERENCE_REQUIRED',stable=stable,pending_probe=pending_probe))
                    continue
                error=float(np.median([v[1] for v in history]))
                if abs(error)<=.5:
                    roi_notice=f'No rotation: {error:+.3f}deg is within 0.5deg. U to rise.'
                    record('YAW_SKIPPED',dict(reason='WITHIN_0_5DEG',relative_angle_deg=error))
                    continue
                try:
                    step=yaw_trial_step(error,yaw_gain,yaw_total,total_limit_deg=None if auto_yaw else 2.)
                except ValueError as failure:
                    if automatic_request:auto_yaw_paused=True
                    roi_notice=str(failure)+'. U to rise.'
                    continue
                if step is None:continue
                validate_yaw_trial_pose(driver.sample(),config)
                before=driver.sample()['posx'].copy()
                target=before.copy();target[3]=(target[3]+step+180)%360-180
                record('LOCAL_YAW_TRIAL',dict(target=target,step_deg=step,error_px_angle_deg=error,gain=yaw_gain,operator_key='AUTO' if automatic_request else 'R',reference='VIRTUAL_GRID' if virtual_grid else 'DETECTED_CIRCULAR_GRID',xy_correction=False,roll_pitch_observed=False))
                local_held_move(driver,config,target,record)
                after=driver.sample()['posx'].copy()
                actual=measured_base_z_rotation(before,after)
                record('YAW_COMPLETED',dict(command_deg=step,actual_base_z_deg=actual,before_pose=before,after_pose=after,so3_rotation_deg=pose_error(before,after)[1]))
                roi_notice=f'Rotated: command {step:+.3f}deg / actual {actual:+.3f}deg'
                yaw_total+=step
                yaw_converged_logged=False
                xy_aligned=False
                if yaw_gain is None:pending_probe=error
                history.clear();messages.pop('rgb',None);last_rgb_time=time.monotonic()
            if key==ord('a'):
                axis_index=1-angles.get('selected_grid_axis',0)
                if config.get('vision_xy_alignment'):
                    target_edge_index=None;xy_aligned=False
                auto_yaw_paused=False;yaw_converged_logged=False
                history.clear();yaw_gain=None;pending_probe=None;direction_confirmed=auto_yaw
            if key in (ord('b'),ord('s')):
                box=cv2.selectROI('Select HELD block' if key==ord('b') else 'Select TARGET studs',frame,False,False)
                cv2.destroyWindow('Select HELD block' if key==ord('b') else 'Select TARGET studs')
                x,y,rw,rh=map(int,box)
                messages.pop('rgb',None);last_rgb_time=time.monotonic()
                if key==ord('s') and (rw<60 or rh<60):
                    roi_notice='Stud ROI too small: select several rows and columns'
                    print('stud 하나가 아닌 여러 행/열 영역을 선택하세요. 최소60x60픽셀.',flush=True)
                    continue
                if rw and rh:
                    roi_notice=''
                    history.clear();yaw_gain=None;pending_probe=None
                    roi=[x,y,x+rw,y+rh]
                    if key==ord('b'):block_roi=roi
                    else:stud_roi=roi
            if key==32 and stamp!=last_saved:
                base=directory/('assembly-observation-'+str(time.time_ns()))
                if not cv2.imwrite(str(base)+'.png',frame):raise OSError('RGB_SAVE_FAILED')
                if not cv2.imwrite(str(base)+'-overlay.png',canvas):raise OSError('OVERLAY_SAVE_FAILED')
                depth=messages.get('depth',(None,None))[0];info=messages.get('info',(None,None))[0];paired=False
                if depth is not None and depth.encoding=='16UC1' and depth.width==w and depth.height==h:
                    ds=depth.header.stamp.sec*10**9+depth.header.stamp.nanosec
                    paired=abs(ds-stamp)<=50_000_000 and depth.header.frame_id==msg.header.frame_id
                    if paired:
                        array=np.frombuffer(depth.data,np.dtype('<u2' if not depth.is_bigendian else '>u2')).reshape(h,depth.step//2)[:,:w]
                        np.save(str(base)+'-depth.npy',array,allow_pickle=False)
                report=dict(block=block,stud_candidates=studs,edge_grid_angle=angles,frame_timing=timing,sample=sample,rgb_stamp_ns=stamp,rgb_frame_id=msg.header.frame_id,
                    rgb_depth_paired=paired,depth_stamp_ns=(ds if depth is not None and depth.encoding=='16UC1' and depth.width==w and depth.height==h else None),
                    camera_info=(dict(k=list(info.k),d=list(info.d),width=info.width,height=info.height,distortion_model=info.distortion_model,frame_id=info.header.frame_id) if info else None),
                    target_cell=[config['alignment_target']['target'][k] for k in ('x','y')],block_roi=block_roi,stud_roi=stud_roi,manual_top_edge_uv=manual_edge.copy(),automatic_stud_cell_identity=False,
                    metric_alignment_verified=False,robot_correction=None,assembly_completion=False,physical_commands=0)
                Path(str(base)+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
                record('HELD_ALIGNMENT_OBSERVATION_SAVED',dict(output=str(base),block_status=block['status'],candidates=len(studs['candidates'])))
                print('관측 저장:',base,flush=True);last_saved=stamp
    except KeyboardInterrupt as failure:
        operator_stopped=True;stop_reason=str(failure) or 'OPERATOR_INTERRUPT'
    finally:
        active_error=sys.exc_info()[1]
        driver.ui_pump=previous_pump
        try:
            driver.trial_stop_attempted=True
            driver.stop()
        except Exception as stop_error:
            record('TRIAL_CLEANUP_STOP_FAILED',dict(reason=str(stop_error),original_reason=str(active_error) if active_error else None))
            if active_error is None:raise
        finally:
            camera_executor.shutdown(timeout_sec=2.)
            camera_thread.join(timeout=2.)
            cv2.destroyAllWindows();node.destroy_node()
    result=dict(status='STOPPED_BY_OPERATOR' if operator_stopped else 'CYCLE_COMPLETED' if press_done else 'INCOMPLETE',
        released=released,press_done=press_done,press_result=press_result,support_active=support_active,
        stop_reason=stop_reason,assembly_completion=False)
    record('HELD_OBSERVATION_RESULT',result)
    if support_active:
        record('TRIAL_HUMAN_SUPPORT_FINISHED',dict(status=result['status'],released=released,press_done=press_done,
            may_release_support=result['status']=='CYCLE_COMPLETED'))
    return result


def integrated_config(config,supply_config):
    value=deepcopy(config)
    value['vision']=deepcopy(supply_config['vision'])
    value['blocks']=deepcopy(supply_config['blocks'])
    value['velocity']=12.
    value['rise_velocity']=12.
    value['transit_velocity']=120.
    value['press_velocity']=12.
    value['seating_velocity']=12.
    value['descent_velocity']=12.
    value['startup_route']['place_xy']=value['assembly_target_xy'].copy()
    value['integrated_cycle']=True
    return value


def closed_pad_cycle(driver,config,reference,status,record):
    from scripts.held_xy_seating_trial import press_from_top_touch
    current=wait_for_held_stop(driver,config,record,status)
    high=reference.copy();high[2]=max(current['posx'][2],config['pickup_clearance_z_mm'])
    above=reference.copy();above[2]+=10.
    if not config.get('target_only_motion',False):
        for target in (high,above):
            if max(pose_error(driver.check_pose(target),target))>.05:
                raise RuntimeError('PAD_CYCLE_ENDPOINT_IK_FK_MISMATCH')
    record('CLOSED_PAD_CYCLE_START',dict(contact_reference=reference,automatic_tilt_alignment=False))
    local_held_move(driver,config,high,record,required_gripper_status=status)
    local_held_move(driver,config,above,record,required_gripper_status=status)
    result=press_from_top_touch(driver,config,reference,record,status)
    local_held_move(driver,config,above,record,required_gripper_status=status)
    local_held_move(driver,config,high,record,required_gripper_status=status)
    record('INTEGRATED_CYCLE_RESULT',dict(press=result,assembly_completion=False,
        result_kind='MOTION_TRIAL_ONLY',automatic_tilt_alignment=False))
    print('통합 시험 이동 완료 / 누르기 결과:',result['status'],flush=True)
    return result


def saved_pad_press(driver,config,path,record):
    from scripts.held_xy_seating_trial import press_from_top_touch
    saved=json.loads(Path(path).read_text())
    reference=saved['pose']
    captured=saved['samples'][-1]
    current=driver.sample()
    status=current['gripper_status']
    limit=supply.motion_force_limit(config)
    guard(current,config['connection'],limit,automatic=False,force_norm_limit=limit,required_gripper_status=status)
    if status not in (0,2) or current['gripper_width_mm']>12. or abs(current['gripper_width_mm']-captured['gripper_width_mm'])>1.:
        raise RuntimeError('CAPTURED_EMPTY_CLOSED_PAD_STATE_CHANGED')
    if not motion_completed(current,config) or (not config.get('target_only_motion',False) and max(pose_error(current['posx'],reference))>.5):
        raise RuntimeError('CURRENT_PAD_TOUCH_POSITION_CHANGED')
    record('SAVED_PAD_TOUCH_ADOPTED_FOR_OPERATOR_TRIAL',dict(source=str(path),pose=reference,
        automatic_geometry_verified=False,empty_pad_context='OPERATOR_CURRENT_CAPTURE_AFTER_RELEASE'))
    driver.call('system/set_robot_mode','SetRobotMode',robot_mode=1)
    above=reference.copy();above[2]+=10.
    local_held_move(driver,config,above,record,required_gripper_status=status)
    result=press_from_top_touch(driver,config,reference,record,status)
    local_held_move(driver,config,above,record,required_gripper_status=status)
    record('EMPTY_PAD_PRESS_AND_RISE_RESULT',dict(result=result,assembly_completion=False,automatic_tilt_alignment=False))
    print('누르기 결과:',result['status'],'/ 10mm 상승 완료',flush=True)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true');p.add_argument('--confirm-hand-clear',action='store_true')
    p.add_argument('--start-zone',choices=('assembly','supply','home'),default='supply')
    p.add_argument('--observe-only',action='store_true')
    p.add_argument('--go-high-only',action='store_true')
    p.add_argument('--rise-only',action='store_true')
    p.add_argument('--pad-press-only',action='store_true')
    p.add_argument('--integrated-cycle',action='store_true')
    p.add_argument('--raised-grasp-profile',type=Path)
    p.add_argument('--support-confirmation',type=Path)
    p.add_argument('--resume-assembly',action='store_true')
    p.add_argument('--resume-transfer',action='store_true')
    p.add_argument('--pad-reference',type=Path,default=NATIVE/'settings/held_corner_stud_20261014/operator-pad-top-reference-20261014.json')
    p.add_argument('--virtual-grid',action='store_true')
    p.add_argument('--yaw-test',action='store_true')
    p.add_argument('--auto-yaw',action='store_true',help='기존 가상 격자의 방향으로 yaw를 +/-0.50도까지 자동 보정')
    p.add_argument('--xy-seat-test',action='store_true')
    p.add_argument('--initial-yaw-deg',type=float,default=0.)
    p.add_argument('--approach-cycle',action='store_true')
    p.add_argument('--confirm-target-empty',action='store_true')
    p.add_argument('--descend-mm',type=float)
    p.add_argument('--approach-z-mm',type=float)
    p.add_argument('--target-layer',type=int,choices=range(1,6))
    p.add_argument('--target-x',type=int,default=11)
    p.add_argument('--target-y',type=int,default=11)
    p.add_argument('--tilt-accuracy-test',action='store_true')
    p.add_argument('--same-xy-press',action='store_true')
    p.add_argument('--raised-grasp-z-offset-mm',type=float,default=0.)
    p.add_argument('--config',type=Path,default=NATIVE/'settings/held_corner_stud_20261014/config.json')
    args=p.parse_args(argv);config=supply.load_config(args.config);supply.validate(config)
    config['tilt_accuracy_test']=args.tilt_accuracy_test
    config['same_xy_press']=args.same_xy_press
    config['auto_yaw']=args.auto_yaw or args.integrated_cycle
    if args.same_xy_press and not args.integrated_cycle:p.error('--same-xy-press requires --integrated-cycle')
    if args.raised_grasp_z_offset_mm and (not args.integrated_cycle or args.resume_transfer or args.resume_assembly or args.raised_grasp_profile):
        p.error('높이 보정 시험은 새 공급판 파지부터 시작하며 측정 raised profile/기존 파지 재개와 함께 쓰지 않습니다.')
    if args.raised_grasp_z_offset_mm not in (0.,10.):p.error('이번 사용자 지정 높이 시험은 +10mm만 지원합니다.')
    if args.resume_transfer and not args.integrated_cycle:p.error('--resume-transfer requires --integrated-cycle')
    if args.resume_transfer and args.resume_assembly:p.error('Choose one resume stage')
    if args.resume_assembly and not args.integrated_cycle:p.error('--resume-assembly requires --integrated-cycle')
    if args.integrated_cycle:
        if args.pad_press_only or args.rise_only or args.go_high_only:p.error('통합 시험과 이동 전용 옵션은 함께 사용하지 않습니다.')
        args.target_layer=1 if args.target_layer is None else args.target_layer
        if args.target_layer!=1:p.error('저장한 패드 접촉점은 (11,11) 1층 시험용입니다.')
        args.observe_only=args.resume_assembly or args.resume_transfer;args.virtual_grid=True;args.yaw_test=True;args.xy_seat_test=True;args.approach_cycle=not args.resume_assembly
        if args.resume_assembly:args.start_zone='assembly'
        if args.resume_transfer:args.start_zone='supply'
        source=supply.load_config(NATIVE/'settings/supply_sequence_20261014/config.json')
        config=integrated_config(config,source)
        supply.validate(config)
        if not args.raised_grasp_profile:
            saved=json.loads(args.pad_reference.read_text())
            config['integrated_pad_contact_pose']=saved['pose']
            config['integrated_pad_contact_source']=str(args.pad_reference)
            config['pad_reference_at_target_physically_verified']=saved.get('automatic_geometry_verified') is True
    if not math.isfinite(args.initial_yaw_deg) or abs(args.initial_yaw_deg)>2.:
        p.error('--initial-yaw-deg must be finite and within +/-2 degrees')
    if args.initial_yaw_deg and not (args.approach_cycle and args.yaw_test):
        p.error('--initial-yaw-deg requires --approach-cycle and --yaw-test')
    if args.xy_seat_test and not (args.yaw_test and args.virtual_grid and args.target_layer is not None):
        p.error('--xy-seat-test requires --yaw-test --virtual-grid --target-layer')
    if args.yaw_test and (not args.virtual_grid or args.target_layer is None):
        p.error('--yaw-test requires --virtual-grid and --target-layer')
    if args.auto_yaw and not args.yaw_test:p.error('--auto-yaw requires --yaw-test')
    if args.target_layer is not None:
        config=target_layer_approach(config,args.target_layer,target_x=args.target_x,target_y=args.target_y)
    if args.raised_grasp_profile:
        if not args.integrated_cycle or args.resume_transfer or args.resume_assembly or args.observe_only:
            p.error('raised profile requires new integrated pickup, not resume/observe-only')
        from app.raised_grasp_press import apply_profile
        profile=json.loads(args.raised_grasp_profile.read_text())
        if any(profile.get('binding',{}).get(k)!=config['blocks'][0].get(k) for k in ('color','brick_type','slot','span')):
            p.error('current integrated trial supports only first yellow2x2 slot1')
        support=json.loads(args.support_confirmation.read_text()) if args.support_confirmation else None
        config=apply_profile(config,profile,support_confirmation=support)
        config['integrated_pad_contact_source']=profile['measurement_ref']
    if args.raised_grasp_z_offset_mm:
        from app.round2_grasp_offset_trial import apply_held_offset_trial
        config=apply_held_offset_trial(config,args.raised_grasp_z_offset_mm)
    if not args.execute and args.pad_press_only:
        saved=json.loads(args.pad_reference.read_text())
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION',pad_contact_pose=saved['pose'],
            sequence=['AUTO','RISE_10MM','REACTION_STOP_PRESS','RISE_10MM'],descent_mm_s=6.,
            force_stop_n=config['force_stop_n'],force_control_target_n=None,physical_commands=0),ensure_ascii=False,indent=2))
        return 0
    if not args.execute:
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION',source_slot=1,block='yellow2x2/span2',target=[args.target_x,args.target_y],
            held_transport_height_mm=config['pickup_clearance_z_mm'],auto_correction=config['auto_yaw'],correction_scope='YAW_DIRECTION_ONLY',roll_pitch_observed=False,initial_yaw_deg=args.initial_yaw_deg,approach_cycle=args.approach_cycle,approach_z_mm=(args.approach_z_mm if args.approach_z_mm is not None else config.get('alignment_approach_z_mm',100.)) if args.approach_cycle else None,release=args.integrated_cycle,pressure=args.integrated_cycle,tilt_accuracy_test=args.tilt_accuracy_test,
            force_stop_n=config['force_stop_n'],motion_force_stop_n=supply.motion_force_limit(config),target_only_motion=config.get('target_only_motion',False),pad_contact_at_target_physically_verified=config.get('pad_reference_at_target_physically_verified',True),vision_backend=config['vision'].get('backend','YOLO'),integrated_cycle=args.integrated_cycle,
            transit_mm_s=config.get('transit_velocity'),rise_descent_mm_s=config.get('velocity'),
            loaded_waypoints=([config['startup_route']['supply_transit_xy'],config['startup_route']['body_bypass_xy'],config['assembly_target_xy']] if args.integrated_cycle else None),physical_commands=0),indent=2));return 0
    if not args.confirm_hand_clear:p.error('--confirm-hand-clear required')
    if (args.approach_cycle or args.xy_seat_test) and args.target_layer==1 and not args.confirm_target_empty:
        p.error(f'({args.target_x},{args.target_y})1층을 비운 뒤 --confirm-target-empty로 접근하세요.')
    if os.environ.get('ROS_DOMAIN_ID')!='20':raise ValueError('ROS_DOMAIN_ID20_REQUIRED')
    if not (args.go_high_only or args.rise_only or args.pad_press_only) and not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):raise RuntimeError('DESKTOP_DISPLAY_REQUIRED')
    directory=args.config.parent/('trial-'+str(time.time_ns()));directory.mkdir()
    with open('/tmp/c2-assembly-dsr01.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        driver=AssemblyMotionRos(dict(mode='REAL',connection=config['connection'],timing=dict(service_timeout_s=3.,stopped_sample_retry_window_s=5.),stale_retry_force_stop_n=supply.motion_force_limit(config),target_only_motion=config.get('target_only_motion',False)))
        old={}
        try:
            if driver.robot_system()!=0:raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
            def interrupt(*_):raise KeyboardInterrupt('OPERATOR_STOP')
            for sig in (signal.SIGINT,signal.SIGTERM):old[sig]=signal.signal(sig,interrupt)
            with (directory/'events.jsonl').open('x') as journal:
                def record(event,data):
                    journal.write(json.dumps(dict(event=event,data=data,unix_s=time.time()),ensure_ascii=False,allow_nan=False)+'\n');journal.flush()
                    if event in ('TILT_OPERATOR_REFERENCE','TILT_PROBE_COMPLETED','TILT_ACCURACY_RESULT','INITIAL_YAW_COMMAND','INITIAL_YAW_COMPLETED','YAW_REQUEST','YAW_SKIPPED','YAW_COMPLETED','LOCAL_IMAGE_YAW_GAIN_MEASURED','COORDINATE_XY_CORRECTION','SEATING_TRIAL_RESULT','SEATED_RELEASE_OPERATOR_CONFIRMED'):
                        print(event,json.dumps(data,ensure_ascii=False),flush=True)
                driver.feedback_record=record
                try:
                    if args.pad_press_only:
                        saved_pad_press(driver,config,args.pad_reference,record)
                        return 0
                    if args.rise_only:
                        sample=driver.sample()
                        if not config.get('target_only_motion',False) and math.dist(sample['posx'][:2],config['assembly_target_xy'])>2.:
                            raise RuntimeError('RISE_ONLY_REQUIRES_TARGET_XY')
                        if sample['gripper_status'] not in (0,2):
                            raise RuntimeError('RISE_ONLY_GRIPPER_STATUS_REQUIRED')
                        target=sample['posx'].copy()
                        target[2]=max(target[2],config['pickup_clearance_z_mm'])
                        local_held_move(driver,config,target,record,required_gripper_status=sample['gripper_status'])
                        print('수직 상승 완료 / XY·방향 유지 / 그리퍼 조작 없음',flush=True)
                        return 0
                    if args.go_high_only or (args.start_zone=='home' and not args.integrated_cycle):
                        return_high(driver,config,record,args.start_zone)
                        if args.go_high_only:return 0
                    if not args.observe_only and (args.start_zone!='home' or args.integrated_cycle):
                        vision=supply.LiveVision(driver,config,directory)
                        try:
                            vision.display(config['blocks'][0],dict(reason='PREPARING_PICKUP'))
                            supply.execute(driver,config,record,vision.observe,slot=1,start_zone=args.start_zone,
                                display=vision.display,hold_at_pickup=True,sleep=vision.pump_sleep)
                            transfer(driver,config,record,sleep=vision.pump_sleep)
                        finally:vision.close()
                    if args.resume_transfer:
                        current=wait_for_held_stop(driver,config,record)
                        if not config.get('target_only_motion',False) and (math.dist(current['posx'][:2],config['blocks'][0]['pickup_pose'][:2])>2. or abs(current['posx'][2]-config['pickup_clearance_z_mm'])>.5):
                            raise RuntimeError('RESUME_TRANSFER_REQUIRES_HELD_AT_PICKUP_HIGH')
                        record('RESUME_HELD_TRANSFER',dict(sample=current,repeat_pickup=False))
                        transfer(driver,config,record)
                    observe(driver,config,directory,record,approach_cycle=args.approach_cycle,descend_mm=args.descend_mm,approach_z_mm=args.approach_z_mm,virtual_grid=args.virtual_grid,yaw_test=args.yaw_test,initial_yaw_deg=args.initial_yaw_deg,xy_seat_test=args.xy_seat_test)
                except BaseException as error:
                    record('TRIAL_ABORTED',dict(reason=str(error),assembly_completion=False))
                    if not getattr(driver,'trial_stop_attempted',False):
                        try:driver.stop()
                        except Exception as stop_error:record('TRIAL_STOP_FAILED',dict(reason=str(stop_error)))
                    raise
        finally:
            for sig,handler in old.items():signal.signal(sig,handler)
            driver.close()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,RuntimeError,TimeoutError) as error:
        print('시험 중단:',error,file=sys.stderr);raise SystemExit(2)
