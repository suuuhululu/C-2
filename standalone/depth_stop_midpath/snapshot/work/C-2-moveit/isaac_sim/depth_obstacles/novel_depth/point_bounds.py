"""Conditional optical-Z/ray/pose error propagation; no acquisition or policy.

Every radius is conditional on the supplied component bounds and their stated
scope/provenance. Missing components stay unknown. Nothing here admits STOP.
"""
from copy import deepcopy
import numpy as np

from .geometry import _rigid


def _bound(value,n,name):
    if value is None:
        return np.full(n,np.nan)
    a=np.asarray(value,float)
    if a.ndim==0:a=np.full(n,float(a))
    if a.shape!=(n,) or not np.isfinite(a).all() or np.any(a<0):
        raise ValueError('FINITE_NONNEGATIVE_POINT_BOUND_REQUIRED:'+name)
    return a


def propagate_point_bounds(pixel_uv,optical_z_m,ray_intrinsics,T_base_camera_optical,error_input,*,source_identity):
    """Return pointwise base Euclidean radii, preserving input pixel order.

    z uncertainty is in optical metres. r=[(u-cx)/fx,(v-cy)/fy,1] is NOT a
    unit-length ray. Supply either its dimensionless Euclidean error, or six
    absolute pixel/focal errors in intrinsics_error_px. Translation/rotation
    describe the aggregate SAME-source optical->base transform and already
    include q/FK/extrinsics; there is no additional q term.
    """
    uv=np.asarray(pixel_uv);z=np.asarray(optical_z_m,float);k=ray_intrinsics
    if z.ndim!=1:
        raise ValueError('ORDERED_INTEGER_UV_AND_OPTICAL_Z_VECTOR_REQUIRED')
    n=len(z)
    if uv.shape!=(n,2) or uv.dtype.kind not in 'iu':
        raise ValueError('ORDERED_INTEGER_UV_AND_OPTICAL_Z_VECTOR_REQUIRED')
    t=_rigid(T_base_camera_optical);inputs=deepcopy(error_input)
    if inputs['units']!='METRE_RADIAN_PIXEL_OPTICAL_Z_ONE_RAY':
        raise ValueError('POINT_BOUND_UNITS_REQUIRED')
    if any(x in inputs for x in ('q_error_rad','additional_q_error_m')):
        raise ValueError('Q_ERROR_ALREADY_INCLUDED_IN_AGGREGATE_TRANSFORM')
    if (not np.isfinite([k[x] for x in ('fx','fy','cx','cy')]).all() or min(k['fx'],k['fy'])<=0 or
            type(k['width']) is not int or type(k['height']) is not int or min(k['width'],k['height'])<=0):
        raise ValueError('FINITE_POSITIVE_RAY_GRID_REQUIRED')
    missing=[];scope_ok=True
    if inputs.get('source_identity')!=source_identity:missing.append('source_identity');scope_ok=False
    if inputs.get('ray_intrinsics')!=k:missing.append('ray_intrinsics_scope');scope_ok=False
    nominal=inputs.get('T_base_camera_optical')
    if nominal is None or not np.array_equal(np.asarray(nominal),t):missing.append('transform_nominal_scope');scope_ok=False
    domain=inputs.get('depth_domain_m')
    if domain is None:
        missing.append('depth_domain_m');scope_ok=False;domain=[0.,0.]
    elif len(domain)!=2 or not np.isfinite(domain).all() or not 0<domain[0]<domain[1]:
        raise ValueError('FINITE_POSITIVE_DEPTH_DOMAIN_REQUIRED')
    support=(np.isfinite(z)&(z>=domain[0])&(z<=domain[1])&(uv[:,0]>=0)&(uv[:,0]<k['width'])&
             (uv[:,1]>=0)&(uv[:,1]<k['height']))
    r=np.column_stack(((uv[:,0]-k['cx'])/k['fx'],(uv[:,1]-k['cy'])/k['fy'],np.ones(n)))
    ez=_bound(inputs.get('depth_z_error_m'),n,'depth_z_error_m')
    er=_bound(inputs.get('ray_direction_error_norm'),n,'ray_direction_error_norm')
    intr=inputs.get('intrinsics_error_px')
    if intr is not None:
        if inputs.get('ray_direction_error_norm') is not None:
            raise ValueError('RAY_ERROR_OR_INTRINSICS_ERRORS_NOT_BOTH')
        names=('fx','fy','cx','cy','u','v')
        if any(x not in intr for x in names):raise ValueError('SIX_INTRINSICS_PIXEL_ERRORS_REQUIRED')
        b={x:_bound(intr[x],n,'intrinsics_error_px.'+x) for x in names}
        if any(intr[x] is None for x in names):
            missing.append('intrinsics_error_px.components')
        with np.errstate(invalid='ignore',divide='ignore'):
            ex=(b['u']+b['cx']+abs(r[:,0])*b['fx'])/(k['fx']-b['fx'])
            ey=(b['v']+b['cy']+abs(r[:,1])*b['fy'])/(k['fy']-b['fy'])
        er=np.hypot(ex,ey);er[(b['fx']>=k['fx'])|(b['fy']>=k['fy'])]=np.nan
    et=_bound(inputs.get('translation_error_m'),n,'translation_error_m')
    theta=_bound(inputs.get('rotation_error_rad'),n,'rotation_error_rad')
    if np.any(theta>np.pi):raise ValueError('ROTATION_RADIUS_MUST_BE_RAD_0_TO_PI')
    if inputs.get('q_transform_accounting')!='INCLUDED_IN_AGGREGATE_TRANSFORM_ONCE':
        missing.append('q_transform_accounting');scope_ok=False
    refs=inputs.get('source_refs',{})
    for name,a,ref_key in [('depth_z_error_m',ez,'depth'),('ray_or_intrinsics_error',er,'ray'),
                           ('translation_error_m',et,'transform'),('rotation_error_rad',theta,'transform')]:
        if not np.isfinite(a).all():missing.append(name)
        if not refs.get(ref_key):missing.append('source_refs.'+ref_key);a[:]=np.nan
    # ||(z+dz)(r+dr)-zr|| <= ||r||ez + |z|er + ez*er.
    # For rotations, chord <= min(theta,2). Decompose using the true rotation
    # on camera error, so the camera-error term is not counted a second time.
    p_camera=np.column_stack(((uv[:,0]-k['cx'])*z/k['fx'],(uv[:,1]-k['cy'])*z/k['fy'],z))
    eps=np.finfo(float).eps/2;gamma=lambda count:count*eps/(1-count*eps)
    with np.errstate(invalid='ignore',over='ignore'):
        camera_radius=np.linalg.norm(r,axis=1)*ez+abs(z)*er+ez*er
        rotation_radius=np.minimum(theta,2.)*np.linalg.norm(p_camera,axis=1)
        optical_round=np.column_stack(((abs(uv[:,0])+abs(k['cx']))*abs(z)/k['fx'],
            (abs(uv[:,1])+abs(k['cy']))*abs(z)/k['fy'],np.zeros(n)))*gamma(3)
        base_round=gamma(7)*(abs(p_camera)@abs(t[:3,:3]).T+abs(t[:3,3]))
        arithmetic_radius=np.linalg.norm(base_round+optical_round@abs(t[:3,:3]).T,axis=1)
        radius=camera_radius+rotation_radius+et+arithmetic_radius
    # Outward allowance for these binary64 scalar operations, not sensor error.
    radius=np.nextafter(radius*(1+gamma(32)),np.inf)
    known=support&np.isfinite(radius)&scope_ok;radius[~known]=np.nan
    return dict(status='CONDITIONAL_RADII' if known.any() else 'UNKNOWN_POINT_BOUNDS',
        bound_semantics='BASE_FRAME_EUCLIDEAN_RADIUS_M',point_uncertainty_m=radius,known_mask=known,
        outside_support_mask=~support,pixel_uv=uv.copy(),source_identity=deepcopy(source_identity),
        arithmetic_radius_m=arithmetic_radius,
        missing_fields=sorted(set(missing)),source_refs=deepcopy(refs),
        error_input_scope=inputs.get('evidence_scope'),q_transform_accounting=inputs.get('q_transform_accounting'),
        risk_qualified=False,official_tolerance_m=None,official_observation='REPORT_ONLY')


def bound_detection_points(detection,expected,frame_state,error_input):
    """Companion to existing detection, never overwrites its points/confidence."""
    from .geometry import _digest
    if _digest(frame_state)!=_digest(expected['frame_state']):
        raise ValueError('POINT_BOUND_EXPECTED_SOURCE_MISMATCH')
    if detection['guard'] or detection['projected'] is None:
        return dict(status='DETECTION_GUARD',point_uncertainty_m=None,risk_qualified=False)
    p=detection['projected'];uv=np.asarray(p['pixel_uv'],int).reshape(-1,2)
    if (any(p[k]!=frame_state[k] for k in ('session_id','clock_epoch','frame_seq','source_stamp_s')) or
            detection['map_digest']!=expected['map_digest']):
        raise ValueError('POINT_BOUND_DETECTION_SOURCE_OR_MAP_MISMATCH')
    z=detection['observed_z_m'][uv[:,1],uv[:,0]]
    k=expected['ray_intrinsics'];t=np.asarray(p['T_base_camera_optical'])
    camera=np.column_stack(((uv[:,0]-k['cx'])*z/k['fx'],(uv[:,1]-k['cy'])*z/k['fy'],z))
    if not np.array_equal(camera@t[:3,:3].T+t[:3,3],np.asarray(p['points_base_m']).reshape(-1,3)):
        raise ValueError('POINT_BOUND_PROJECTED_POINTS_OR_RAY_GRID_MISMATCH')
    identity={k:frame_state[k] for k in ('session_id','clock_epoch','frame_seq','source_stamp_s','calibration_id')}
    result=propagate_point_bounds(uv,z,expected['ray_intrinsics'],p['T_base_camera_optical'],error_input,source_identity=identity)
    result.update(projected_digest=p['digest'],point_is_foreground=detection['point_is_foreground'].copy(),
        original_point_uncertainty_m=detection['point_uncertainty_m'].copy(),
        effective_pixel_convention=deepcopy(expected['effective_pixel_convention']),
        qualification_ref=deepcopy(detection.get('qualification_ref')),classification_scope=detection['classification_scope'])
    return result
