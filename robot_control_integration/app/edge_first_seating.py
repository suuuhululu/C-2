"""Yellow 2x2 fixed-contact-line geometry preview; never a live motion controller."""
from copy import deepcopy
import math
import warnings
import numpy as np
from scipy.spatial.transform import Rotation
from app.assembly_step_bridge import pose
from app.contracts import validate_block


def rotate_about_contact_line(reference_tcp,line,angle_deg):
    reference=pose(reference_tcp,'seated_reference_tcp')
    edge=np.asarray(line,dtype=float)
    if edge.shape!=(2,3) or not np.isfinite(edge).all():
        raise ValueError('TWO_FINITE_CONTACT_LINE_POINTS_REQUIRED')
    axis=edge[1]-edge[0];length=float(np.linalg.norm(axis))
    if length<1e-6:raise ValueError('CONTACT_LINE_MUST_HAVE_LENGTH')
    if type(angle_deg) not in (int,float) or not math.isfinite(angle_deg):
        raise ValueError('FINITE_CONTACT_ROTATION_REQUIRED')
    if angle_deg==0:return reference
    turn=Rotation.from_rotvec(axis/length*angle_deg,degrees=True)
    # The contact line is the rotation axis, rather than the TCP origin.
    xyz=edge[0]+turn.apply(np.asarray(reference[:3])-edge[0])
    rotation=turn*Rotation.from_euler('ZYZ',reference[3:],degrees=True)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        abc=rotation.as_euler('ZYZ',degrees=True).tolist()
    return [*xyz.tolist(),*abc]


def preview(config,operation=None):
    if config.get('schema_version')=='yellow4-pivot-preview/2':
        return pivot_preview(config,config.get('operation') if operation is None else operation)
    if operation not in (None,'assembly'):
        raise ValueError('SEPARATE_REMOVAL_INPUT_REQUIRES_V2_CONFIG')
    if config.get('schema_version')!='yellow4-edge-first-preview/1' or config.get('mode')!='PREVIEW_ONLY':
        raise ValueError('EDGE_FIRST_PREVIEW_ONLY_CONFIG_REQUIRED')
    block=config['block']
    if not isinstance(block,dict) or (block.get('color'),block.get('brick_type'))!=('yellow','2x2x1'):
        raise ValueError('ONLY_SINGLE_YELLOW_FOUR_STUD_BLOCK_SUPPORTED')
    block=validate_block(block)
    angle=config['initial_tilt_deg'];step=config['angular_step_deg']
    if type(angle) not in (int,float) or not math.isfinite(angle) or not 0<abs(angle)<90:
        raise ValueError('NONZERO_EDGE_FIRST_TILT_BELOW_90DEG_REQUIRED')
    if type(step) not in (int,float) or not math.isfinite(step) or step<=0:
        raise ValueError('POSITIVE_ANGULAR_STEP_REQUIRED')
    reference=pose(config['seated_reference_tcp_mm_zyz_deg'],'seated_reference_tcp')
    line=config['contact_line_points_mm']
    count=math.ceil(abs(angle)/step)
    angles=[math.copysign(max(0.,abs(angle)-i*step),angle) for i in range(count+1)]
    points=[dict(remaining_tilt_deg=a,tcp_mm_zyz_deg=rotate_about_contact_line(reference,line,a)) for a in angles]
    return dict(status='EDGE_FIRST_GEOMETRY_PREVIEW',block=block,coordinate_frame=config['coordinate_frame'],
        source_kind=config['source_kind'],contact_line_points_mm=deepcopy(line),waypoints=points,
        max_tcp_translation_from_seated_mm=max(math.dist(p['tcp_mm_zyz_deg'][:3],reference[:3]) for p in points),
        scope='SINGLE_YELLOW_2X2_EXPERIMENT',model='FIXED_CONTACT_LINE_WITH_RIGID_GRASP',
        sequence=['ALIGN_ABOVE_TARGET','INTENTIONAL_ROLL_OR_PITCH_TILT','FIRST_CONTACT',
            'CONFIRM_STUD_ENGAGEMENT','COUPLED_TCP_TRANSLATION_AND_ROTATION','VERIFY_SEATING',
            'RELEASE','OPTIONAL_EXISTING_CLOSED_PAD_PRESS'],
        automatic_plane_leveling_during_intentional_tilt=False,
        pivot_physically_verified=False,stud_engagement_observed=False,
        execution_allowed=False,physical_commands=0,assembly_completion=False)


def pose_matrix(value,name='pose'):
    p=pose(value,name);matrix=np.eye(4)
    matrix[:3,:3]=Rotation.from_euler('ZYZ',p[3:],degrees=True).as_matrix()
    matrix[:3,3]=p[:3]
    return matrix


def matrix_pose(matrix):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        abc=Rotation.from_matrix(matrix[:3,:3]).as_euler('ZYZ',degrees=True).tolist()
    return [*matrix[:3,3].tolist(),*abc]


def _points(value,name,count):
    points=np.asarray(value,dtype=float)
    if points.shape!=(count,3) or not np.isfinite(points).all():
        raise ValueError(f'{name}: {count}_FINITE_XYZ_POINTS_REQUIRED')
    return points


def transform_points(matrix,points):
    return np.asarray(points)@matrix[:3,:3].T+matrix[:3,3]


def _tilt_samples(angle,step,operation):
    if type(angle) not in (int,float) or not math.isfinite(angle) or not 0<abs(angle)<90:
        raise ValueError('NONZERO_PIVOT_TILT_BELOW_90DEG_REQUIRED')
    if type(step) not in (int,float) or not math.isfinite(step) or step<=0:
        raise ValueError('POSITIVE_ANGULAR_STEP_REQUIRED')
    # Removal samples outwards independently, including a possibly shorter last step.
    count=math.ceil(abs(angle)/step)
    return [math.copysign(max(0.,abs(angle)-i*step) if operation=='assembly'
            else min(abs(angle),i*step),angle) for i in range(count+1)]


def pivot_preview(config,operation):
    """T_output_block = T_output_frame @ T_frame_block; T_tcp_block is rigid grasp."""
    if config.get('schema_version')!='yellow4-pivot-preview/2' or config.get('mode')!='PREVIEW_ONLY':
        raise ValueError('EDGE_FIRST_PREVIEW_ONLY_CONFIG_REQUIRED')
    block=config['block']
    if not isinstance(block,dict) or (block.get('color'),block.get('brick_type'))!=('yellow','2x2x1'):
        raise ValueError('ONLY_SINGLE_YELLOW_FOUR_STUD_BLOCK_SUPPORTED')
    block=validate_block(block)
    if operation not in ('assembly','removal'):
        raise ValueError('ASSEMBLY_OR_REMOVAL_OPERATION_REQUIRED')
    for key in ('coordinate_frame','output_frame','source_kind'):
        if not isinstance(config.get(key),str) or not config[key].strip():
            raise ValueError(f'{key}: NAMED_FRAME_OR_SOURCE_REQUIRED')
    selected=config['operations'][operation]
    line_input=selected['contact_line']
    studs_input=config['target_studs']
    if any(item['frame']!=config['coordinate_frame'] for item in (line_input,studs_input)):
        raise ValueError('EXPLICIT_FRAME_TRANSFORM_REQUIRED_FOR_AXIS_AND_STUDS')
    frame=pose_matrix(config['frame_pose_in_output_mm_zyz_deg'],'frame_pose_in_output')
    if config['coordinate_frame']==config['output_frame'] and not np.allclose(frame,np.eye(4),atol=1e-9):
        raise ValueError('SAME_NAMED_FRAME_REQUIRES_IDENTITY_TRANSFORM')
    seated_block=frame@pose_matrix(config['seated_block_pose_mm_zyz_deg'],'seated_block_pose')
    grasp=pose_matrix(config['tcp_to_block_pose_mm_zyz_deg'],'tcp_to_block_pose')
    seated_tcp=seated_block@np.linalg.inv(grasp)
    line=transform_points(frame,_points(line_input['points_mm'],'contact_line',2))
    studs=transform_points(frame,_points(studs_input['centers_mm'],'target_studs',4))
    geometry=config['block_geometry']
    bottom=_points(geometry['bottom_corners_in_block_mm'],'bottom_corners',4)
    height=geometry['height_mm']
    if type(height) not in (int,float) or not math.isfinite(height) or height<=0:
        raise ValueError('POSITIVE_BLOCK_HEIGHT_REQUIRED')
    corners=np.concatenate((bottom,bottom+[0,0,height]))
    angles=_tilt_samples(selected['tilt_deg'],selected['angular_step_deg'],operation)
    reference=matrix_pose(seated_tcp);waypoints=[]
    for angle in angles:
        tcp=rotate_about_contact_line(reference,line,angle)
        actual_block=pose_matrix(tcp)@grasp
        waypoints.append(dict(tilt_deg=angle,tcp_mm_zyz_deg=tcp,
            block_mm_zyz_deg=matrix_pose(actual_block),
            block_corners_mm=transform_points(actual_block,corners).tolist()))
    axis=(line[1]-line[0])/np.linalg.norm(line[1]-line[0])
    radius=float(np.linalg.norm(np.cross(seated_tcp[:3,3]-line[0],axis)))
    max_step=max(abs(b-a) for a,b in zip(angles,angles[1:]))
    return dict(status='YELLOW4_PIVOT_GEOMETRY_PREVIEW',schema_version='yellow4-pivot-preview-result/2',
        operation=operation,block=block,input_frame=config['coordinate_frame'],
        coordinate_frame=config['output_frame'],source_kind=config['source_kind'],
        model='FIXED_CONTACT_LINE_WITH_RIGID_GRASP',
        contact_line_points_mm=line.tolist(),target_stud_centers_mm=studs.tolist(),
        contact_line_points_in_block_mm=transform_points(np.linalg.inv(seated_block),line).tolist(),
        seated_reference_tcp_mm_zyz_deg=reference,seated_reference_block_mm_zyz_deg=matrix_pose(seated_block),
        tcp_to_block_pose_mm_zyz_deg=deepcopy(config['tcp_to_block_pose_mm_zyz_deg']),
        block_geometry=deepcopy(geometry),waypoints=waypoints,tcp_orbit_radius_mm=radius,
        max_tcp_translation_from_seated_mm=max(math.dist(p['tcp_mm_zyz_deg'][:3],reference[:3]) for p in waypoints),
        chord_error_bound_mm=radius*(1-math.cos(math.radians(max_step)/2)),
        chord_error_model='LINEAR_TCP_XYZ_AND_SHORTEST_SO3_INTERPOLATION_NOT_CONTROLLER_VERIFIED',
        sequence=(['INTENTIONAL_TILT','ASSUMED_STUD_ENGAGEMENT','PIVOT_TO_SEATED','INSPECT_SEATING']
                  if operation=='assembly' else ['ASSUMED_SEATED_GRASP','PIVOT_PARTIAL_RELEASE','INSPECT_REMAINING_ENGAGEMENT']),
        pivot_physically_verified=False,stud_engagement_observed=False,all_studs_released=False,
        automatic_plane_leveling_during_intentional_tilt=False,
        execution_allowed=False,physical_commands=0,assembly_completion=False,removal_completion=False)
