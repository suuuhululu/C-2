"""Unloaded roll/pitch return-to-operator-reference trial, not surface leveling."""
import math
import warnings
from scipy.spatial.transform import Rotation
from app.assembly_motion import pose_error


def rotation_error(reference,current):
    delta=Rotation.from_euler('ZYZ',current[3:],degrees=True)*Rotation.from_euler('ZYZ',reference[3:],degrees=True).inv()
    vector=delta.as_rotvec(degrees=True).tolist()
    return dict(base_x_deg=vector[0],base_y_deg=vector[1],base_z_deg=vector[2],
                rotation_error_deg=float(delta.magnitude()*180/math.pi),position_error_mm=math.dist(reference[:3],current[:3]))


def perturbed_pose(reference,x_deg,y_deg):
    if not all(math.isfinite(v) and abs(v)<=1. for v in (x_deg,y_deg)):
        raise ValueError('TILT_ACCURACY_PROBE_MAX1DEG_PER_AXIS')
    rotation=Rotation.from_rotvec([x_deg,y_deg,0.],degrees=True)*Rotation.from_euler('ZYZ',reference[3:],degrees=True)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        angles=rotation.as_euler('ZYZ',degrees=True).tolist()
    return [*reference[:3],*angles]


def accuracy_result(reference,actual, *, tolerance_deg=.05):
    result=rotation_error(reference,actual)
    result.update(status='TCP_REFERENCE_RETURN_PASS' if result['rotation_error_deg']<=tolerance_deg and result['position_error_mm']<=.1 else 'TCP_REFERENCE_RETURN_OUTSIDE_TOLERANCE',
        tolerance_deg=tolerance_deg,independent_block_plane_verified=False,
        reference_kind='OPERATOR_SELECTED_TCP_ATTITUDE',loaded_alignment=False)
    return result
