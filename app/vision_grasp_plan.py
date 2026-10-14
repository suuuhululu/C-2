"""Reserved Vision geometry to selectable grasp plans; no device calls."""
import math

import numpy as np
from scipy.spatial.transform import Rotation

from supply_vision.seg_backend import block_class
from supply_vision.seg_geometry import geometry_from_mask


def _vector(value, size, name):
    a=np.asarray(value,dtype=float)
    if a.shape!=(size,) or not np.isfinite(a).all():
        raise ValueError('INVALID_'+name)
    return a


def grasp_geometry(observation, request, surface_settings):
    """Select physical span from normalized long/short edges, never image axes."""
    allowed={'2x2x1':{2:0},'2x3x1':{2:0,3:1},'1x2x1':{1:0,2:1}}
    kind=request['brick_type'];span=request['span_studs']
    if type(span) is not int or span not in allowed.get(kind,{}):
        raise ValueError('UNSUPPORTED_KIND_SPAN')
    if type(request['slot_index']) is not int or not 1<=request['slot_index']<=5:
        raise ValueError('RESERVED_SLOT_1_TO_5_REQUIRED')
    expected=block_class(request['color'],kind)
    if observation['status']!='CENTER_CANDIDATE':
        raise ValueError('UNIQUE_VISION_CENTER_REQUIRED')
    if any(observation[key]!=request[key] for key in ('color','brick_type')):
        raise ValueError('VISION_KIND_COLOR_MISMATCH')
    if observation['slot_id']!=f"{request['color']}_{kind}_{request['slot_index']:02d}":
        raise ValueError('VISION_RESERVATION_SLOT_MISMATCH')
    pair=allowed[kind][span]
    # Re-normalize for the requested span rather than retaining the old 2-stud pair.
    g=geometry_from_mask([observation['geometry']['corners_uv']],expected,pair,surface_settings)
    return dict(center_uv=g['center_uv'],closing_midpoints_uv=g['grasp_midpoints_uv'],
                corners_uv=g['corners_uv'],edge_pair=pair,span_studs=span)


def plan_pick(observation, request, reference, parameters, surface_settings):
    result=dict(status='BLOCKED',execution_allowed=False,physical_commands=0,
                robot_target=None,actions=None,physical_accuracy_verified=False)
    try:
        if request.get('stop_requested') or request.get('cancelled'):
            raise ValueError('STOP_OR_CANCELLED')
        geometry=grasp_geometry(observation,request,surface_settings)
        result.update(grasp=geometry,selected_profile={key:request[key] for key in
                      ('color','brick_type','slot_index','span_studs','height_mode')})
        if request['height_mode'] not in ('BASELINE','RAISED'):
            raise ValueError('EXPLICIT_HEIGHT_MODE_REQUIRED')
        identity=('color','brick_type','slot_index')
        if any(reference[key]!=request[key] for key in identity):
            raise ValueError('REFERENCE_RESERVATION_MISMATCH')
        jac=np.asarray(reference['jacobian_base_xy_mm_per_pixel'],dtype=float)
        if jac.shape!=(2,2) or not np.isfinite(jac).all() or abs(np.linalg.det(jac))<1e-9:
            raise ValueError('REGISTERED_XY_MAPPING_REQUIRED')
        nominal=_vector(reference['nominal_tcp_mm_zyz_deg'],6,'NOMINAL_TCP')
        center=_vector(reference['center_uv'],2,'REFERENCE_CENTER')
        before=np.asarray(reference['closing_midpoints_uv'],dtype=float)
        after=np.asarray(geometry['closing_midpoints_uv'],dtype=float)
        if before.shape!=(2,2) or not np.isfinite(before).all():
            raise ValueError('REFERENCE_CLOSING_AXIS_REQUIRED')
        v0,v1=jac@(before[1]-before[0]),jac@(after[1]-after[0])
        if min(np.linalg.norm(v0),np.linalg.norm(v1))<1e-9:
            raise ValueError('DEGENERATE_CLOSING_AXIS')
        yaw=(math.degrees(math.atan2(v1[1],v1[0])-math.atan2(v0[1],v0[0]))+90)%180-90
        xy_delta=jac@(_vector(geometry['center_uv'],2,'CURRENT_CENTER')-center)
        result.update(vision_xy_delta_mm=xy_delta.tolist(),vision_yaw_delta_deg=yaw)
        # This is per-profile geometry. A 2-stud datum is not silently reused at 1/3 studs.
        missing=[key for key in ('reference_tcp_to_body_xy_mm','new_tcp_to_body_xy_mm')
                 if reference.get(key) is None]
        missing += [key for key in ('open_width_mm','close_width_mm','gripper_force_n','height_delta_mm')
                    if parameters.get(key) is None]
        if missing:
            result.update(reason='PROFILE_PARAMETERS_REQUIRED',pending=missing)
            return result
        old_offset=_vector(reference['reference_tcp_to_body_xy_mm'],2,'REFERENCE_BODY_OFFSET')
        new_offset=_vector(reference['new_tcp_to_body_xy_mm'],2,'NEW_BODY_OFFSET')
        for key in ('open_width_mm','close_width_mm','gripper_force_n','height_delta_mm'):
            value=parameters[key]
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError('FINITE_PROFILE_PARAMETER_REQUIRED')
        opened,closed=parameters['open_width_mm'],parameters['close_width_mm']
        force=parameters['gripper_force_n'];dz=parameters['height_delta_mm']
        if not 0<=closed<opened<=110 or not 0<force<=40:
            raise ValueError('INVALID_GRIPPER_COMMAND_RANGE')
        if (request['height_mode']=='BASELINE' and dz!=0) or (request['height_mode']=='RAISED' and dz<=0):
            raise ValueError('HEIGHT_MODE_DELTA_MISMATCH')
        turn=Rotation.from_euler('z',yaw,degrees=True)
        rotated_offset=turn.apply([*new_offset,0])[:2]
        target=nominal.copy();target[:2]+=xy_delta+old_offset-rotated_offset;target[2]+=dz
        target[3:]=(turn*Rotation.from_euler('ZYZ',nominal[3:],degrees=True)).as_euler('ZYZ',degrees=True)
        approach=target.copy();approach[2]+=parameters['approach_offset_mm']
        if not math.isfinite(parameters['approach_offset_mm']) or parameters['approach_offset_mm']<20:
            raise ValueError('APPROACH_OFFSET_AT_LEAST_20MM_REQUIRED')
        result.update(status='VISION_GRASP_PLAN_FOR_REVIEW',reason=None,
                      candidate_tcp_mm_zyz_deg=target.tolist(),
                      pivot_xy_compensation_mm=(old_offset-rotated_offset).tolist(),
                      actions=[dict(kind='open',width_mm=opened,force_n=force),
                               dict(kind='approach',pose_mm_zyz_deg=approach.tolist()),
                               dict(kind='descend',pose_mm_zyz_deg=target.tolist()),
                               dict(kind='close',width_mm=closed,force_n=force)],
                      metric_basis=reference['metric_basis'],
                      note='Actions require live reservation, geometry validation and operator motion admission')
    except (ValueError,KeyError,TypeError) as error:
        result['reason']=str(error)
    return result


def coordinate_first_pick(observation, request, reference, parameters, surface_settings):
    """Use exact-axis teaching; optional validated vision changes only Base XY.

The user explicitly chose this policy for the current lightly trained model.
Missing recognition/calibration leaves the taught pose intact, never STOP or a
reservation/profile mismatch. No image-derived yaw, Z or new body datum is used.
"""
    result=dict(status='BLOCKED',execution_allowed=False,physical_commands=0,actions=None,
                center_assist_applied=False,physical_accuracy_verified=False)
    try:
        if request.get('stop_requested') or request.get('cancelled'):
            raise ValueError('STOP_OR_CANCELLED')
        allowed={'2x2x1':{2},'2x3x1':{2,3},'1x2x1':{1,2}}
        kind,span=request['brick_type'],request['span_studs']
        block_class(request['color'],kind)
        if type(span) is not int or span not in allowed.get(kind,set()):
            raise ValueError('UNSUPPORTED_KIND_SPAN')
        if type(request['slot_index']) is not int or not 1<=request['slot_index']<=5:
            raise ValueError('RESERVED_SLOT_1_TO_5_REQUIRED')
        for key in ('color','brick_type','slot_index','span_studs','height_mode'):
            if reference.get(key)!=request.get(key):
                raise ValueError('EXACT_TAUGHT_AXIS_REFERENCE_REQUIRED')
        if reference.get('taught_coordinate_verified') is not True:
            raise ValueError('VERIFIED_TAUGHT_COORDINATE_REQUIRED')
        if request['height_mode'] not in ('BASELINE','RAISED'):
            raise ValueError('EXPLICIT_HEIGHT_MODE_REQUIRED')
        target=_vector(reference['nominal_tcp_mm_zyz_deg'],6,'NOMINAL_TCP').copy()
        for key in ('open_width_mm','close_width_mm','gripper_force_n','approach_offset_mm'):
            if type(parameters.get(key)) not in (int,float) or not math.isfinite(parameters[key]):
                raise ValueError('FINITE_PROFILE_PARAMETER_REQUIRED')
        opened,closed,force=(parameters[k] for k in ('open_width_mm','close_width_mm','gripper_force_n'))
        if not 0<=closed<opened<=110 or not 0<force<=40 or parameters['approach_offset_mm']<20:
            raise ValueError('INVALID_GRIPPER_OR_APPROACH_PARAMETERS')
        reason='VISION_NOT_RECOGNIZED_USE_TAUGHT_COORDINATE'
        if observation.get('status')=='CENTER_CANDIDATE':
            if (any(observation.get(key)!=request[key] for key in ('color','brick_type'))
                    or observation.get('slot_id')!=f"{request['color']}_{kind}_{request['slot_index']:02d}"):
                raise ValueError('VISION_RESERVATION_SLOT_MISMATCH')
            try:
                geometry=grasp_geometry(observation,request,surface_settings)
            except (ValueError,KeyError,TypeError):
                geometry=None;reason='CENTER_GEOMETRY_UNUSABLE_USE_TAUGHT_COORDINATE'
            if geometry is not None and (reference.get('mapping_independently_verified') is True
                    and reference.get('center_reference_pairing_verified') is True):
                try:
                    jac=np.asarray(reference['jacobian_base_xy_mm_per_pixel'],dtype=float)
                    if jac.shape!=(2,2) or not np.isfinite(jac).all() or abs(np.linalg.det(jac))<1e-9:
                        raise ValueError('INVALID_XY_MAPPING')
                    delta=jac@(_vector(geometry['center_uv'],2,'CURRENT_CENTER')-_vector(reference['center_uv'],2,'REFERENCE_CENTER'))
                except (ValueError,KeyError,TypeError):
                    delta=None;reason='CENTER_MAPPING_UNUSABLE_USE_TAUGHT_COORDINATE'
                limit=parameters.get('max_center_shift_mm')
                if delta is None:
                    pass
                elif type(limit) not in (int,float) or not math.isfinite(limit) or limit<=0:
                    reason='CENTER_BOUND_UNSET_USE_TAUGHT_COORDINATE'
                elif np.linalg.norm(delta)>limit:
                    reason='CENTER_OUT_OF_BOUND_USE_TAUGHT_COORDINATE'
                else:
                    target[:2]+=delta;reason=None
                    result.update(center_assist_applied=True,vision_xy_delta_mm=delta.tolist())
            elif geometry is not None:
                reason='CENTER_MAPPING_UNVERIFIED_USE_TAUGHT_COORDINATE'
        approach=target.copy();approach[2]+=parameters['approach_offset_mm']
        result.update(status='VISION_GRASP_PLAN_FOR_REVIEW',reason=reason,
            policy='COORDINATE_FIRST_WITH_OPTIONAL_CENTER',candidate_tcp_mm_zyz_deg=target.tolist(),
            z_and_orientation_preserved=True,metric_basis='EXACT_AXIS_OPERATOR_TEACHING',
            actions=[dict(kind='open',width_mm=opened,force_n=force),
                     dict(kind='approach',pose_mm_zyz_deg=approach.tolist()),
                     dict(kind='descend',pose_mm_zyz_deg=target.tolist()),
                     dict(kind='close',width_mm=closed,force_n=force)])
    except (ValueError,KeyError,TypeError) as error:
        result['reason']=str(error)
    return result
