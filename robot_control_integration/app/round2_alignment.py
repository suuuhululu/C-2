"""Registered block/stud surface alignment seam; TCP-return tests are not evidence."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import time
import numpy as np
from scipy.spatial.transform import Rotation
from app.assembly_step_bridge import pose
from app.assembly_motion import pose_error


def _binding(plan):
    from app.round2_step_controller import binding
    return binding(plan)


def _capture_timing(sample,result,profile,now_monotonic_ns,not_before_monotonic_ns=None):
    """Source-clock age and pose skew are separate from the mapped exposure clock.

    The capture producer owns the reviewed source-to-process-monotonic mapping.
    A ROS image stamp must never be compared directly with a monotonic barrier.
    """
    limits=profile.get('round2_capture_limits') if profile else None
    required=('max_frame_age_ns','max_pose_skew_ns','max_clock_mapping_error_ns')
    if not isinstance(limits,dict) or any(type(limits.get(k)) is not int or limits[k]<=0 for k in required):
        raise ValueError('ROUND2_REVIEWED_CAPTURE_LIMITS_REQUIRED')
    timing=result.get('capture_timing')
    if not isinstance(timing,dict):raise ValueError('ROUND2_CAPTURE_TIMING_REQUIRED')
    domain=timing.get('clock_domain')
    if not isinstance(domain,str) or not domain.strip() or timing.get('pose_clock_domain')!=domain:
        raise ValueError('ROUND2_CAPTURE_CLOCK_DOMAIN_MISMATCH')
    stamp=result.get('frame_stamp_ns')
    fields=('clock_now_ns','pose_stamp_ns','exposure_monotonic_ns','exposure_mapping_error_ns')
    if (type(stamp) is not int or stamp<=0 or type(now_monotonic_ns) is not int or now_monotonic_ns<0
            or any(type(timing.get(k)) is not int or timing[k]<0 for k in fields)):
        raise ValueError('ROUND2_CAPTURE_CLOCK_VALUES_REQUIRED')
    if not isinstance(timing.get('clock_mapping_ref'),str) or not timing['clock_mapping_ref'].strip():
        raise ValueError('ROUND2_CAPTURE_CLOCK_MAPPING_REQUIRED')
    error=timing['exposure_mapping_error_ns']
    exposure=timing['exposure_monotonic_ns']
    if error>limits['max_clock_mapping_error_ns']:
        raise ValueError('ROUND2_CAPTURE_CLOCK_MAPPING_UNCERTAINTY')
    if (not 0<=timing['clock_now_ns']-stamp<=limits['max_frame_age_ns']
            or exposure+error>now_monotonic_ns
            or now_monotonic_ns-(exposure-error)>limits['max_frame_age_ns']):
        raise ValueError('ROUND2_CAPTURE_OLD_OR_FUTURE_FRAME')
    if sample is None or pose(timing.get('pose_posx'),'capture_pose')!=pose(sample.get('posx'),'current_pose'):
        raise ValueError('ROUND2_CAPTURE_POSE_SAMPLE_MISMATCH')
    if abs(timing['pose_stamp_ns']-stamp)>limits['max_pose_skew_ns']:
        raise ValueError('ROUND2_CAPTURE_POSE_FRAME_SKEW')
    if not_before_monotonic_ns is not None:
        if type(not_before_monotonic_ns) is not int or not_before_monotonic_ns<0:
            raise ValueError('ROUND2_ALIGNMENT_MOTION_BARRIER_REQUIRED')
        if exposure-error<=not_before_monotonic_ns:
            raise ValueError('ROUND2_AFTER_ALIGNMENT_REQUIRES_POST_MOTION_EXPOSURE')


def validate_alignment_candidate(plan,profile,sample,result,*,now_monotonic_ns=None):
    if result.get('binding')!=_binding(plan):raise ValueError('ROUND2_ALIGNMENT_STEP_BINDING_MISMATCH')
    _capture_timing(sample,result,profile,time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns)
    direction_only=result.get('reference_kind')=='EXISTING_BOARD_PARALLEL_DIRECTIONS'
    if direction_only:
        if not isinstance(result.get('edge_id'),str) or not result['edge_id'].strip():
            raise ValueError('ROUND2_PHYSICAL_EDGE_ID_REQUIRED')
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


def validate_alignment_observation(plan,candidate,observed,profile=None,*,sample=None,
                                   now_monotonic_ns=None,not_before_monotonic_ns=None):
    if observed.get('binding')!=_binding(plan) or observed.get('reference_kind')!=candidate.get('reference_kind'):
        raise ValueError('ROUND2_AFTER_ALIGNMENT_REFERENCE_MISMATCH')
    if type(observed.get('frame_stamp_ns')) is not int or observed['frame_stamp_ns']<=candidate['frame_stamp_ns']:
        raise ValueError('ROUND2_AFTER_ALIGNMENT_REQUIRES_NEW_FRAME')
    before_timing=candidate.get('capture_timing');after_timing=observed.get('capture_timing')
    if not isinstance(before_timing,dict) or not isinstance(after_timing,dict):
        raise ValueError('ROUND2_CAPTURE_TIMING_REQUIRED')
    if after_timing.get('clock_domain')!=before_timing.get('clock_domain'):
        raise ValueError('ROUND2_AFTER_ALIGNMENT_CLOCK_DOMAIN_MISMATCH')
    if not_before_monotonic_ns is None:
        raise ValueError('ROUND2_ALIGNMENT_MOTION_BARRIER_REQUIRED')
    _capture_timing(sample,observed,profile,time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns,
                    not_before_monotonic_ns)
    if candidate['reference_kind']=='EXISTING_BOARD_PARALLEL_DIRECTIONS':
        if not isinstance(observed.get('edge_id'),str) or not observed['edge_id'].strip():
            raise ValueError('ROUND2_PHYSICAL_EDGE_ID_REQUIRED')
        if observed.get('edge_id')!=candidate.get('edge_id'):
            raise ValueError('ROUND2_AFTER_ALIGNMENT_EDGE_IDENTITY_MISMATCH')
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
        if not isinstance(data.get('capture_timing'),dict):
            return dict(status='UNAVAILABLE',reason='ROUND2_CAPTURE_TIMING_REQUIRED')
        if data.get('binding')!=_binding(plan) or data.get('registered_for_current_grasp') is not True or not data.get('registration_ref'):
            raise ValueError('ROUND2_CURRENT_GRASP_REGISTRATION_REQUIRED')
        observation,target=data['observation'],data['target']
        if observation.get('binding')!=_binding(plan) or target.get('binding')!=_binding(plan):
            raise ValueError('ROUND2_FEATURE_BINDING_MISMATCH')
        fitted=geometry.align_top(observation,target,sample['posx'],limits)
        common=dict(binding=_binding(plan),reference_kind='REGISTERED_BLOCK_AND_STUD_PLANES',
            frame_stamp_ns=data['frame_stamp_ns'],registration_ref=data['registration_ref'],
            capture_timing=deepcopy(data['capture_timing']))
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

    capture supplies a request-bound image, CameraInfo, capture_timing and two
    labelled/tracked body-top edge endpoints. A nonempty edge_id is required to
    identify the same physical edge across frames. This provider measures yaw
    only, never roll/pitch or XY.
    """
    from supply_vision.virtual_board_grid import VirtualBoardGrid
    grid=VirtualBoardGrid(grid_config)
    state=dict(gain=None,before_error=None,step=None,axis=None,binding=None,edge_id=None)
    def observe(stage,plan,sample):
        packet=capture(stage,deepcopy(plan),deepcopy(sample))
        if packet.get('status')=='UNAVAILABLE':return packet
        active=_binding(plan)
        if packet.get('binding')!=active:raise ValueError('ROUND2_CAPTURE_STEP_BINDING_MISMATCH')
        if not isinstance(packet.get('capture_timing'),dict):
            return dict(status='UNAVAILABLE',reason='ROUND2_CAPTURE_TIMING_REQUIRED')
        edge_id=packet.get('edge_id')
        if not isinstance(edge_id,str) or not edge_id.strip():
            return dict(status='UNAVAILABLE',reason='ROUND2_PHYSICAL_EDGE_ID_REQUIRED')
        if state['binding']!=active or state['edge_id']!=edge_id:
            state.update(gain=None,before_error=None,step=None,axis=None,binding=deepcopy(active),edge_id=edge_id)
        if stage!='BEFORE' and state['step'] is None:
            return dict(status='UNAVAILABLE',reason='ROUND2_DIRECTION_EDGE_CHANGED_AFTER_COMMAND')
        edge=packet.get('edge_uv',[])
        _,report=grid.overlay(packet['frame_bgr'],sample,packet.get('camera_info'),
            layer=plan['block']['layer'],clearance_mm=packet.get('clearance_mm',20.),
            edges=[edge],axis_index=state['axis'],target_xy=(plan['block']['x'],plan['block']['y']))
        error=report.get('relative_angle_deg')
        if error is None:return dict(status='UNAVAILABLE',reason=report.get('reason'))
        state['axis']=report['selected_grid_axis']
        common=dict(binding=_binding(plan),reference_kind='EXISTING_BOARD_PARALLEL_DIRECTIONS',
            frame_stamp_ns=packet['frame_stamp_ns'],roll_pitch_observed=False,
            stud_center_coincidence_required=False,xy_correction=False,projection=report,
            edge_id=edge_id,capture_timing=deepcopy(packet['capture_timing']))
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


def automatic_surface_alignment(driver,plan,profile,provider,move,record,*,clock=time.monotonic_ns):
    """No fixed retry count; each move requires fresh registered surface evidence."""
    iteration=0;last_stamp=None;last_domain=None
    while True:
        sample=driver.sample()
        candidate=provider('BEFORE',deepcopy(plan),deepcopy(sample))
        record('ROUND2_ALIGNMENT_BEFORE',candidate)
        if candidate.get('status') not in ('SURFACE_ALIGNMENT_CANDIDATE','DIRECTION_ALIGNMENT_CANDIDATE'):
            return dict(status='WAITING_SURFACE_MEASUREMENT',reason=candidate.get('reason'),iteration=iteration)
        timing=candidate.get('capture_timing')
        domain=timing.get('clock_domain') if isinstance(timing,dict) else None
        if last_domain is not None and domain!=last_domain:
            raise ValueError('ROUND2_NEXT_ITERATION_CLOCK_DOMAIN_MISMATCH')
        if last_stamp is not None and candidate.get('frame_stamp_ns',0)<=last_stamp:
            raise ValueError('ROUND2_NEXT_ITERATION_REQUIRES_NEW_FRAME')
        validate_alignment_candidate(plan,profile,sample,candidate,now_monotonic_ns=clock())
        distance,angle=pose_error(sample['posx'],candidate['approach_pose'])
        if max(distance,angle)>1e-6:
            move('ROUND2_SURFACE_ALIGNMENT',candidate['approach_pose'],2,profile['descent_velocity'])
        completed=clock()
        actual=deepcopy(driver.sample())
        actual['round2_capture_not_before_monotonic_ns']=completed
        observed=provider('AFTER',deepcopy(plan),deepcopy(actual))
        record('ROUND2_ALIGNMENT_AFTER',observed)
        if observed.get('status')=='UNAVAILABLE':
            return dict(status='WAITING_SURFACE_MEASUREMENT',reason=observed.get('reason'),iteration=iteration+1)
        done=validate_alignment_observation(plan,candidate,observed,profile,sample=actual,
            now_monotonic_ns=clock(),not_before_monotonic_ns=completed)
        last_stamp=observed['frame_stamp_ns']
        last_domain=observed['capture_timing']['clock_domain']
        iteration+=1
        record('ROUND2_ALIGNMENT_ITERATION',dict(iteration=iteration,converged=done,
            roll_error_deg=observed['roll_error_deg'],pitch_error_deg=observed['pitch_error_deg'],
            yaw_error_deg=observed['yaw_error_deg'],angle_tolerance_deg=.5,
            correction_scope='YAW_DIRECTION_ONLY' if candidate['reference_kind']=='EXISTING_BOARD_PARALLEL_DIRECTIONS' else 'ROLL_PITCH_YAW'))
        if done:return dict(status='SURFACE_ALIGNMENT_CONVERGED',candidate=candidate,observed=observed,iteration=iteration)
