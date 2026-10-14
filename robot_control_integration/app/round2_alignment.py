"""Registered block/stud surface alignment seam; TCP-return tests are not evidence."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from app.assembly_step_bridge import pose
from app.assembly_motion import pose_error


def _binding(plan):
    from app.round2_step_controller import binding
    return binding(plan)


def validate_alignment_candidate(plan,profile,sample,result):
    if result.get('binding')!=_binding(plan):raise ValueError('ROUND2_ALIGNMENT_STEP_BINDING_MISMATCH')
    direction_only=result.get('reference_kind')=='EXISTING_BOARD_PARALLEL_DIRECTIONS'
    if direction_only:
        approach=pose(result.get('approach_pose'),'aligned_approach')
        landing=pose(result.get('landing_pose'),'aligned_landing')
        if approach[:3]!=sample['posx'][:3] or pose_error(sample['posx'],approach)[1]>.501:
            raise ValueError('ROUND2_DIRECTION_CORRECTION_MUST_KEEP_XYZ_AND_STEP_HALF_DEGREE')
        delta=Rotation.from_euler('ZYZ',approach[3:],degrees=True)*Rotation.from_euler('ZYZ',sample['posx'][3:],degrees=True).inv()
        if np.linalg.norm(delta.as_rotvec()[:2])>1e-7:
            raise ValueError('ROUND2_DIRECTION_CORRECTION_MUST_BE_BASE_Z_ONLY')
        if result.get('roll_pitch_observed') is not False or result.get('stud_center_coincidence_required') is not False:
            raise ValueError('ROUND2_DIRECTION_SCOPE_REQUIRED')
        if type(result.get('frame_stamp_ns')) is not int or result['frame_stamp_ns']<=0:
            raise ValueError('ROUND2_ALIGNMENT_FRAME_REQUIRED')
        if pose_error(approach,[*approach[:3],*landing[3:]])[1]>.05:
            raise ValueError('ROUND2_LANDING_MUST_PRESERVE_ALIGNED_ATTITUDE')
        if type(result.get('pad_contact_z_mm')) not in (int,float) or not math.isfinite(result['pad_contact_z_mm']):
            raise ValueError('ROUND2_ALIGNED_PAD_CONTACT_Z_REQUIRED')
        return result
    if result.get('reference_kind')!='REGISTERED_BLOCK_AND_STUD_PLANES' or result.get('registration_reviewed') is not True:
        raise ValueError('ROUND2_REAL_SURFACE_REFERENCE_REQUIRED')
    if type(result.get('frame_stamp_ns')) is not int or result['frame_stamp_ns']<=0:
        raise ValueError('ROUND2_ALIGNMENT_FRAME_REQUIRED')
    limits=profile.get('round2_alignment_limits')
    required=('max_translation_mm','max_rotation_deg','max_plane_error_deg','max_center_error_mm')
    if not limits or any(type(limits.get(k)) not in (int,float) or not math.isfinite(limits[k]) or limits[k]<=0 for k in required):
        raise ValueError('ROUND2_REVIEWED_ALIGNMENT_LIMITS_REQUIRED')
    approach=pose(result.get('approach_pose'),'aligned_approach')
    landing=pose(result.get('landing_pose'),'aligned_landing')
    distance,angle=pose_error(sample['posx'],approach)
    if distance>limits['max_translation_mm'] or angle>limits['max_rotation_deg']:
        raise ValueError('ROUND2_ALIGNMENT_OUTSIDE_REGISTERED_SWEEP')
    z=result.get('pad_contact_z_mm')
    if type(z) not in (int,float) or not math.isfinite(z):raise ValueError('ROUND2_ALIGNED_PAD_CONTACT_Z_REQUIRED')
    if approach[2]<=landing[2] or z+profile['near_contact_offset_mm']>=max(profile['clearance_z_mm'],z+profile['approach_offset_mm']):
        raise ValueError('ROUND2_ALIGNMENT_CLEARANCE_REQUIRED')
    if pose_error(approach,[*approach[:3],*landing[3:]])[1]>.05:
        raise ValueError('ROUND2_LANDING_MUST_PRESERVE_ALIGNED_ATTITUDE')
    return result


def validate_alignment_observation(plan,candidate,observed,profile=None):
    if observed.get('binding')!=_binding(plan) or observed.get('reference_kind')!=candidate.get('reference_kind'):
        raise ValueError('ROUND2_AFTER_ALIGNMENT_REFERENCE_MISMATCH')
    if type(observed.get('frame_stamp_ns')) is not int or observed['frame_stamp_ns']<=candidate['frame_stamp_ns']:
        raise ValueError('ROUND2_AFTER_ALIGNMENT_REQUIRES_NEW_FRAME')
    if candidate['reference_kind']=='EXISTING_BOARD_PARALLEL_DIRECTIONS':
        yaw=observed.get('yaw_error_deg')
        if type(yaw) not in (int,float) or not math.isfinite(yaw):raise ValueError('ROUND2_MEASURED_YAW_REQUIRED')
        return observed.get('status')=='DIRECTION_ALIGNMENT_OBSERVATION' and abs(yaw)<=.5
    for key in ('plane_error_deg','center_error_mm'):
        value=observed.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise ValueError('ROUND2_AFTER_ALIGNMENT_ERROR_REQUIRED')
    for key in ('roll_error_deg','pitch_error_deg','yaw_error_deg'):
        v=observed.get(key)
        if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('ROUND2_MEASURED_RPY_REQUIRED')
    tolerance=.5 if profile is None else profile.get('round2_angle_tolerance_deg',.5)
    return observed.get('status')=='SURFACE_ALIGNMENT_OBSERVATION' and all(abs(observed[k])<=tolerance for k in ('roll_error_deg','pitch_error_deg','yaw_error_deg'))


def registered_surface_provider(capture,limits):
    """capture returns actual paired registered 3D features and aligned grasp geometry.

    RAW capture ownership stays with the vision/contact producer. No preview
    authority, static screenshot or command-generated target is a live measurement.
    """
    source=Path(__file__).resolve().parents[2]/'app/top_press_alignment.py'
    spec=importlib.util.spec_from_file_location('round2_registered_top_geometry',source)
    geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry)
    def normal(points):
        points=np.asarray(points,float);_,_,axes=np.linalg.svd(points-points.mean(axis=0))
        n=axes[-1];return n if n[2]>=0 else -n
    def observe(stage,plan,sample):
        data=capture(stage,deepcopy(plan),deepcopy(sample))
        if data.get('status')=='UNAVAILABLE':return dict(status='UNAVAILABLE',reason=data.get('reason'))
        if data.get('binding')!=_binding(plan) or data.get('registered_for_current_grasp') is not True or not data.get('registration_ref'):
            raise ValueError('ROUND2_CURRENT_GRASP_REGISTRATION_REQUIRED')
        observation,target=data['observation'],data['target']
        if observation.get('binding')!=_binding(plan) or target.get('binding')!=_binding(plan):
            raise ValueError('ROUND2_FEATURE_BINDING_MISMATCH')
        fitted=geometry.align_top(observation,target,sample['posx'],limits)
        common=dict(binding=_binding(plan),reference_kind='REGISTERED_BLOCK_AND_STUD_PLANES',
            frame_stamp_ns=data['frame_stamp_ns'],registration_ref=data['registration_ref'])
        if stage=='BEFORE':
            if data.get('target_at_alignment_clearance') is not True:
                raise ValueError('ROUND2_ALIGNMENT_TARGET_MUST_BE_AT_CLEARANCE')
            return dict(common,status='SURFACE_ALIGNMENT_CANDIDATE',registration_reviewed=True,
                approach_pose=fitted['aligned_held_tcp_mm_zyz_deg'],landing_pose=data['aligned_landing_pose'],
                pad_contact_z_mm=data['aligned_pad_contact_z_mm'],fit=fitted)
        a=normal(observation['points_mm'][:4]);b=normal(target['points_mm'][:4])
        plane=math.degrees(math.acos(float(np.clip(np.dot(a,b),-1,1))))
        center=math.dist(np.mean(observation['points_mm'][:4],axis=0)[:2],np.mean(target['points_mm'][:4],axis=0)[:2])
        angles=Rotation.from_matrix(fitted['correction_rotation_matrix']).as_euler('xyz',degrees=True).tolist()
        return dict(common,status='SURFACE_ALIGNMENT_OBSERVATION',plane_error_deg=plane,center_error_mm=center,
            roll_error_deg=angles[0],pitch_error_deg=angles[1],yaw_error_deg=angles[2],
            within_reviewed_tolerance=all(abs(v)<=.5 for v in angles) and center<=limits['max_center_error_mm'])
    return observe


def virtual_grid_direction_provider(capture,grid_config,*,near_contact_offset_mm):
    """Use existing calibration for direction; no stud-center registration required.

    capture supplies a fresh image, CameraInfo and two labelled/tracked body-top
    edge endpoints. This provider measures yaw only, never roll/pitch or XY.
    """
    from supply_vision.virtual_board_grid import VirtualBoardGrid
    grid=VirtualBoardGrid(grid_config)
    state=dict(gain=None,before_error=None,step=None,axis=None)
    def observe(stage,plan,sample):
        packet=capture(stage,deepcopy(plan),deepcopy(sample))
        if packet.get('status')=='UNAVAILABLE':return packet
        edge=packet.get('edge_uv',[])
        _,report=grid.overlay(packet['frame_bgr'],sample,packet.get('camera_info'),
            layer=plan['block']['layer'],clearance_mm=packet.get('clearance_mm',20.),
            edges=[edge],axis_index=state['axis'],target_xy=(plan['block']['x'],plan['block']['y']))
        error=report.get('relative_angle_deg')
        if error is None:return dict(status='UNAVAILABLE',reason=report.get('reason'))
        state['axis']=report['selected_grid_axis']
        common=dict(binding=_binding(plan),reference_kind='EXISTING_BOARD_PARALLEL_DIRECTIONS',
            frame_stamp_ns=packet['frame_stamp_ns'],roll_pitch_observed=False,
            stud_center_coincidence_required=False,xy_correction=False,projection=report)
        if stage=='BEFORE':
            gain=state['gain']
            step=0. if abs(error)<=.5 else .5 if gain is None else float(np.clip(-error/gain,-.5,.5))
            approach=pose(sample['posx'],'current_pose');approach[3]=(approach[3]+step+180)%360-180
            landing=pose(plan['settings']['reference_pose'],'landing');landing[3:]=approach[3:]
            state.update(before_error=error,step=step)
            return dict(common,status='DIRECTION_ALIGNMENT_CANDIDATE',approach_pose=approach,
                landing_pose=landing,pad_contact_z_mm=plan['settings']['press_start_pose'][2]-near_contact_offset_mm,
                yaw_error_deg=error,command_deg=step)
        if state['step']:
            gain=((error-state['before_error']+90)%180-90)/state['step']
            if not .5<=abs(gain)<=2.:
                return dict(common,status='UNAVAILABLE',reason='IMAGE_YAW_RESPONSE_UNUSABLE')
            state['gain']=gain
        return dict(common,status='DIRECTION_ALIGNMENT_OBSERVATION',yaw_error_deg=error,
            roll_error_deg=None,pitch_error_deg=None)
    return observe


def automatic_surface_alignment(driver,plan,profile,provider,move,record):
    """No fixed retry count; each move requires fresh registered surface evidence."""
    iteration=0;last_stamp=None
    while True:
        sample=driver.sample()
        candidate=provider('BEFORE',deepcopy(plan),deepcopy(sample))
        record('ROUND2_ALIGNMENT_BEFORE',candidate)
        if candidate.get('status') not in ('SURFACE_ALIGNMENT_CANDIDATE','DIRECTION_ALIGNMENT_CANDIDATE'):
            return dict(status='WAITING_SURFACE_MEASUREMENT',iteration=iteration)
        if last_stamp is not None and candidate.get('frame_stamp_ns',0)<=last_stamp:
            raise ValueError('ROUND2_NEXT_ITERATION_REQUIRES_NEW_FRAME')
        validate_alignment_candidate(plan,profile,sample,candidate)
        if max(pose_error(sample['posx'],candidate['approach_pose']))>1e-6:
            move('ROUND2_SURFACE_ALIGNMENT',candidate['approach_pose'],2,profile['descent_velocity'])
        actual=driver.sample()
        observed=provider('AFTER',deepcopy(plan),deepcopy(actual))
        record('ROUND2_ALIGNMENT_AFTER',observed)
        if observed.get('status')=='UNAVAILABLE':
            return dict(status='WAITING_SURFACE_MEASUREMENT',iteration=iteration+1)
        done=validate_alignment_observation(plan,candidate,observed,profile)
        last_stamp=observed['frame_stamp_ns']
        iteration+=1
        record('ROUND2_ALIGNMENT_ITERATION',dict(iteration=iteration,converged=done,
            roll_error_deg=observed['roll_error_deg'],pitch_error_deg=observed['pitch_error_deg'],
            yaw_error_deg=observed['yaw_error_deg'],angle_tolerance_deg=.5,
            correction_scope='YAW_DIRECTION_ONLY' if candidate['reference_kind']=='EXISTING_BOARD_PARALLEL_DIRECTIONS' else 'ROLL_PITCH_YAW'))
        if done:return dict(status='SURFACE_ALIGNMENT_CONVERGED',candidate=candidate,observed=observed,iteration=iteration)
