"""Staged original projection, returning arrays before lists/JSON digest.

All original guards and geometry statements are preserved.
"""
import numpy as np
from isaac_sim.depth_obstacles.projection import pinhole_transform

def project_frame_arrays(frame, depth, self_mask, held_mask, *, now_s, limits, previous=None):
    """Transforms are optical->tool->base, stamped in the same clock as Depth.

    Caller supplies explicit masks; their generation is not implemented here.
    A visible point set is never evidence that the rest of the world is empty.
    """
    if frame['schema']!='wrist-depth-frame/0.1':raise ValueError('Unsupported input draft')
    source=frame['source_kind']
    if source not in ('FIXTURE','SIM_DEPTH','REAL_DEPTH'):raise ValueError('Scene GT is not Depth')
    for key in ('session_id','optical_frame_id','tool_frame_id','base_frame_id','calibration_id','clock_basis'):
        if not isinstance(frame[key],str) or not frame[key]:raise ValueError('Missing '+key)
    if type(frame['frame_seq']) is not int or frame['frame_seq']<0:raise ValueError('Invalid sequence')
    if frame['clock_basis']!=limits['clock_basis']:raise ValueError('Clock domains must match')
    if limits['threshold_status']!='SIM_TEST_PARAMETER':raise ValueError('Only explicit SIM/fixture thresholds supported')
    if source=='REAL_DEPTH':raise ValueError('REAL clock mapping/hand-eye acceptance is not implemented')
    if frame['calibration_scope'] not in ('SIM_FIXTURE','SIM_NOMINAL','SIM_NOMINAL_FROM_REAL_PUBLISHED_TF'):
        raise ValueError('Explicit SIM optical hand-eye provenance required')
    if previous is not None and (previous['session_id']!=frame['session_id'] or
            previous['clock_basis']!=frame['clock_basis'] or frame['frame_seq']<=previous['frame_seq'] or
            frame['source_stamp_s']<=previous['source_stamp_s']):
        raise ValueError('Session change, duplicate or reordered frame needs explicit handling')
    stamps=np.asarray([now_s,frame['source_stamp_s'],frame['received_stamp_s'],frame['transform_stamp_s'],frame['robot_state_stamp_s']],float)
    settings=np.asarray([limits[k] for k in ('max_age_s','max_pose_skew_s','min_depth_m','max_depth_m')],float)
    if not np.isfinite(stamps).all() or not np.isfinite(settings).all() or np.any(settings<=0) or settings[2]>=settings[3]:
        raise ValueError('Finite timestamps and explicit positive SIM limits required')
    q=np.asarray(frame['q_rad'],float)
    if q.shape!=(6,) or not np.isfinite(q).all():raise ValueError('Stamped six-joint state required')
    if not stamps[1]<=stamps[2]<=stamps[0]:raise ValueError('Future or inconsistent receipt timestamp')
    if now_s-frame['source_stamp_s']>limits['max_age_s']:raise ValueError('STALE_DEPTH')
    if max(abs(stamps[3:]-stamps[1]))>limits['max_pose_skew_s']:raise ValueError('WRIST_POSE_TIMESTAMP_MISMATCH')
    intr=frame['intrinsics']
    if intr['model']!='none':raise ValueError('This draft requires rectified pinhole intrinsics')
    if type(intr['width']) is not int or type(intr['height']) is not int or min(intr['width'],intr['height'])<=0:
        raise ValueError('Explicit positive image dimensions required')
    depth=np.asarray(depth)
    if depth.shape!=(intr['height'],intr['width']) or depth.ndim!=2 or depth.dtype.kind not in 'fui':
        raise ValueError('Numeric Depth must match its own intrinsics')
    masks=[np.asarray(m) for m in (self_mask,held_mask)]
    if any(m.dtype!=np.bool_ or m.shape!=depth.shape for m in masks):raise ValueError('Explicit matching self/held masks required')
    if any(frame[k] not in ('EXPLICIT_FIXTURE','GEOMETRIC_UNVERIFIED','VALIDATED_SIM')
            for k in ('self_mask_status','held_mask_status')):raise ValueError('Explicit mask provenance required')
    scale=float(frame['depth_scale_m'])
    if frame['depth_unit']=='METER':
        if scale!=1 or depth.dtype.kind!='f':raise ValueError('Meters require floating Depth and scale1')
    elif frame['depth_unit']=='SENSOR_UNITS':
        if depth.dtype!=np.uint16:raise ValueError('Raw units require original uint16')
    else:raise ValueError('Unknown Depth unit')
    tool=pinhole_transform(scale,intr,frame['T_base_tool'])
    optical=pinhole_transform(scale,intr,frame['T_tool_camera_optical'])
    transform=tool@optical
    distance=depth.astype(float)*scale
    v,u=np.indices(depth.shape)
    representation=frame['depth_representation']
    if representation=='RAY_RANGE':
        distance=distance/np.sqrt(1+((u-intr['cx'])/intr['fx'])**2+((v-intr['cy'])/intr['fy'])**2)
    elif representation!='IMAGE_PLANE_Z':raise ValueError('Unknown Depth representation')
    eligible=~(masks[0]|masks[1])
    valid=eligible&np.isfinite(distance)&(distance>=limits['min_depth_m'])&(distance<=limits['max_depth_m'])
    v,u=np.nonzero(valid)
    z=distance[valid]
    camera=np.column_stack(((u-intr['cx'])*z/intr['fx'],(v-intr['cy'])*z/intr['fy'],z))
    base=camera@transform[:3,:3].T+transform[:3,3]
    # Even a complete image covers only visible surfaces. No free-space,
    # disappearing-object or occupancy removal claim is made by this function.
    result=dict(schema='base-visible-depth-candidates/0.1',source_kind=source,
        session_id=frame['session_id'],frame_seq=frame['frame_seq'],source_stamp_s=frame['source_stamp_s'],
        clock_basis=frame['clock_basis'],base_frame_id=frame['base_frame_id'],
        optical_frame_id=frame['optical_frame_id'],tool_frame_id=frame['tool_frame_id'],
        received_stamp_s=frame['received_stamp_s'],transform_stamp_s=frame['transform_stamp_s'],
        robot_state_stamp_s=frame['robot_state_stamp_s'],q_rad=q.tolist(),
        calibration_scope=frame['calibration_scope'],
        calibration_id=frame['calibration_id'],T_base_camera_optical=transform.tolist(),
        points_base_m=base,pixel_uv=np.column_stack((u,v)),
        status='PARTIAL' if len(base) else 'UNOBSERVABLE',
        valid_pixels=int(valid.sum()),eligible_pixels=int(eligible.sum()),
        invalid_or_unseen_pixels=int((eligible&~valid).sum()),
        self_mask_status=frame['self_mask_status'],held_mask_status=frame['held_mask_status'],
        world_clear_allowed=False,planning_execution_allowed=False,hardware_execution_allowed=False,
        scope='OFFLINE_VISIBLE_CANDIDATES_NOT_OBSTACLE_TRACKER_OR_LIVE_SENSOR')
    return result
