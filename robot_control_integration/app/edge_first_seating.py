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


def preview(config):
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
