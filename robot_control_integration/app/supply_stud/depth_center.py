"""Opt-in RGB-D supply correction. Coordinates are mm in the robot Base frame."""
from hashlib import sha256
import json
from pathlib import Path

import cv2
import numpy as np

from app.assembly_motion import vector
from supply_vision.held_xy_alignment import _camera, _transform
from supply_vision.virtual_board_grid import pose_matrix


def packet_age_limit_ns(profile):
    value = profile.get('max_packet_age_ms', 300.)
    if type(value) not in (int, float) or not np.isfinite(value) or not 0 < value <= 310:
        raise ValueError('SUPPLY_DEPTH_PACKET_AGE_LIMIT_INVALID')
    return int(value*1_000_000)


def _validate_t2_educational_binding(profile, config):
    accepted = profile['educational_acceptance']
    rows = config.get('blocks', [])
    refs = profile.get('references', [])
    if (config.get('scope') != 'T2_SUPPLY_APPROACH_CLOSE_HOLD_ONLY'
            or config.get('operator_accepted_t2_educational_profile') is not True
            or config.get('vision', {}).get('allow_educational_t2_depth_profile') is not True
            or config.get('assembly_xy_correction_enabled') is not False
            or config.get('automatic_lift') is not False
            or config.get('trial_step', {}).get('step_id') != 'T2'
            or accepted.get('approval_mechanism') != 'EXPLICIT_RUNNER_T2_EDUCATIONAL_FLAG'
            or not accepted.get('evidence_ref')
            or len(rows) != 1 or len(refs) != 1
            or tuple(rows[0].get(k) for k in ('color', 'brick_type', 'slot', 'span'))
                != ('blue', '2x3x1', 3, 2)
            or refs[0].get('slot_id') != 'blue_2x3x1_03'
            or refs[0].get('pickup_pose') != rows[0]['pickup_pose']):
        raise ValueError('SUPPLY_DEPTH_T2_EXPLICIT_SINGLE_SUPPLY_SCOPE_REQUIRED')


def load_profile(path, layout_path, config):
    profile = json.loads(Path(path).read_text())
    if (profile.get('schema_version') != 'supply-depth-center/1'
            or not isinstance(profile.get('calibration_ref'), str) or not profile['calibration_ref'].strip()):
        raise ValueError('SUPPLY_DEPTH_CALIBRATION_NOT_VERIFIED')
    if profile.get('independently_verified') is not True:
        if profile.get('educational_acceptance', {}).get('scope') == 'APPROVED_EDUCATIONAL_SUPPLY_REGISTRY':
            from app.supply_stud.execution_profile import bound_depth_profile
            profile = bound_depth_profile(path, profile, config)
        elif profile.get('educational_acceptance', {}).get('scope') == 'T2_BLUE_2X3_SLOT3_SUPPLY_ONLY':
            _validate_t2_educational_binding(profile, config)
        else:
            accepted = profile.get('educational_acceptance', {})
            step = config.get('trial_step', {})
            expected = dict(color='yellow', brick_type='2x2x1', x=9, y=9, layer=2, orientation_deg=0)
            rows = config.get('blocks', [])
            residual = accepted.get('measured_residual_xy_mm')
            if (config.get('vision', {}).get('allow_educational_depth_profile') is not True
                    or accepted.get('operator_accepted') is not True
                    or accepted.get('scope') != 'FIXED_T1_YELLOW_2X2_SLOT4_ONLY'
                    or not isinstance(accepted.get('evidence_ref'), str) or not accepted['evidence_ref']
                    or type(residual) not in (int, float) or not np.isfinite(residual) or residual <= 0
                    or step.get('step_id') != 'T1' or step.get('target') != expected
                    or len(rows) != 1
                    or (rows[0]['color'], rows[0]['brick_type'], rows[0]['slot']) != ('yellow', '2x2x1', 4)):
                raise ValueError('SUPPLY_DEPTH_CALIBRATION_NOT_VERIFIED')
            refs = profile.get('references', [])
            if (len(refs) != 1 or refs[0].get('slot_id') != 'yellow_2x2x1_04'
                    or refs[0].get('pickup_pose') != rows[0]['pickup_pose']):
                raise ValueError('SUPPLY_DEPTH_EDUCATIONAL_REFERENCE_BINDING_MISMATCH')
    required = {'connection', 'observation_pose', 'layout_sha256', 'T_tcp_camera_mm', 'input_size',
                'camera_frame', 'max_shift_mm', 'max_height_error_mm', 'max_depth_spread_mm',
                'depth_range_mm', 'references'}
    if not required <= profile.keys():
        raise ValueError('SUPPLY_DEPTH_PROFILE_FIELDS_REQUIRED')
    if (profile['connection'] != {k: config['connection'][k] for k in ('robot_id', 'tcp', 'tool')}
            or profile['observation_pose'] != config['observation_pose']
            or profile['layout_sha256'] != sha256(Path(layout_path).read_bytes()).hexdigest()):
        raise ValueError('SUPPLY_DEPTH_SETUP_BINDING_MISMATCH')
    packet_age_limit_ns(profile)
    _transform(profile['T_tcp_camera_mm'])
    if profile['input_size'] not in ([640, 480], [1280, 720]):
        raise ValueError('SUPPLY_DEPTH_INPUT_SIZE_UNSUPPORTED')
    if not isinstance(profile['camera_frame'], str) or not profile['camera_frame']:
        raise ValueError('SUPPLY_DEPTH_CAMERA_FRAME_REQUIRED')
    for key in ('max_shift_mm', 'max_height_error_mm', 'max_depth_spread_mm'):
        value = profile[key]
        if type(value) not in (int, float) or not np.isfinite(value) or value <= 0:
            raise ValueError('SUPPLY_DEPTH_POSITIVE_LIMIT_REQUIRED:' + key)
    low, high = vector(profile['depth_range_mm'], 2, 'depth_range_mm')
    if not 0 < low < high:
        raise ValueError('SUPPLY_DEPTH_RANGE_INVALID')
    layout = json.loads(Path(layout_path).read_text())
    if layout['image_size'] != [640, 480]:
        raise ValueError('SUPPLY_DEPTH_PROCESSING_SIZE_REQUIRED')
    return profile


def processing_frame(frame, input_size):
    """Keep the full field of view: uniform scale, then vertical padding."""
    if list(frame.shape[1::-1]) != input_size:
        raise ValueError('SUPPLY_DEPTH_INPUT_SIZE_MISMATCH')
    if input_size == [640, 480]:
        return frame.copy()
    if input_size != [1280, 720]:
        raise ValueError('SUPPLY_DEPTH_INPUT_SIZE_UNSUPPORTED')
    resized = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
    return cv2.copyMakeBorder(resized, 60, 60, 0, 0, cv2.BORDER_CONSTANT, value=0)


def source_pixels(points, input_size):
    points = np.asarray(points, dtype=float)
    if input_size == [1280, 720]:
        # Invert OpenCV's pixel-centre resize convention, including padding.
        return (points - [0., 60.] + .5) * 2. - .5
    return points.copy()


def rgbd_target(row, decision, depth_msg, info, rgb_msg, sample, profile, now_ns, bounds):
    """Use measured displacement from a taught surface centre, never its Z as TCP Z."""
    if (decision.get('recognized') is not True or decision.get('center_basis') != 'STUD_ARRAY'
            or decision.get('center_available') is not True):
        raise ValueError('SUPPLY_DEPTH_STUD_CENTER_REQUIRED')
    slot_id = f"{row['color']}_{row['brick_type']}_{row['slot']:02d}"
    if decision.get('slot_id') != slot_id:
        raise ValueError('SUPPLY_DEPTH_SLOT_MISMATCH')
    matches = [r for r in profile['references'] if r['slot_id'] == slot_id]
    if len(matches) != 1 or matches[0]['pickup_pose'] != row['pickup_pose']:
        raise ValueError('SUPPLY_DEPTH_TAUGHT_REFERENCE_MISMATCH')
    reference = np.asarray(vector(matches[0]['surface_center_base_mm'], 3, 'surface_reference'))
    k, distortion, width, height, camera_frame = _camera(info)
    if ([width, height] != profile['input_size'] or [rgb_msg.width, rgb_msg.height] != [width, height]
            or [depth_msg.width, depth_msg.height] != [width, height]
            or camera_frame != profile['camera_frame']
            or rgb_msg.header.frame_id != camera_frame or depth_msg.header.frame_id != camera_frame):
        raise ValueError('SUPPLY_DEPTH_REGISTERED_FRAME_REQUIRED')
    def stamp(message):
        return message.header.stamp.sec * 10**9 + message.header.stamp.nanosec
    stamps = [stamp(m) for m in (rgb_msg, depth_msg, info)]
    if (any(not 0 <= now_ns - s <= packet_age_limit_ns(profile) for s in stamps)
            or max(stamps) - min(stamps) > 50_000_000):
        raise ValueError('SUPPLY_DEPTH_FRESH_SYNCHRONIZED_PACKET_REQUIRED '
                         f'ages_ms={[(now_ns-s)/1e6 for s in stamps]} '
                         f'skew_ms={(max(stamps)-min(stamps))/1e6:.3f}')
    if depth_msg.encoding != '16UC1' or depth_msg.step < width * 2 or depth_msg.step % 2:
        raise ValueError('SUPPLY_DEPTH_16UC1_MM_REQUIRED')
    dtype = np.dtype('>u2' if depth_msg.is_bigendian else '<u2')
    depth = np.frombuffer(depth_msg.data, dtype).reshape(height, depth_msg.step // 2)[:, :width]
    center = source_pixels(vector(decision['center_uv'], 2, 'center_uv'), profile['input_size'])
    if not np.isfinite(center).all():
        raise ValueError('SUPPLY_DEPTH_FINITE_CENTER_REQUIRED')
    x, y = np.floor(center + .5).astype(int)
    if not (1 <= x < width - 1 and 1 <= y < height - 1):
        raise ValueError('SUPPLY_DEPTH_CENTER_OUTSIDE_IMAGE')
    contour = source_pixels(decision['contour_uv'], profile['input_size']).astype(np.float32)
    # A small patch must lie entirely on the detected block; never fill holes
    # from surrounding background, where the supply board may be visible.
    if any(cv2.pointPolygonTest(contour, (float(u), float(v)), False) < 0
           for v in range(y-1, y+2) for u in range(x-1, x+2)):
        raise ValueError('SUPPLY_DEPTH_PATCH_OUTSIDE_BLOCK')
    patch = depth[y-1:y+2, x-1:x+2].astype(float)
    low, high = profile['depth_range_mm']
    if (not np.isfinite(patch).all() or (patch < low).any() or (patch > high).any()
            or np.ptp(patch) > profile['max_depth_spread_mm']):
        raise ValueError('SUPPLY_DEPTH_SURFACE_UNAVAILABLE '
                         f'zero_pixels={int((patch == 0).sum())}/9 '
                         f'min_mm={float(np.min(patch)):.1f} max_mm={float(np.max(patch)):.1f} '
                         f'spread_mm={float(np.ptp(patch)):.1f} '
                         f'allowed_depth_mm={low}..{high} '
                         f'allowed_spread_mm={profile["max_depth_spread_mm"]}')
    z = float(np.median(patch))
    ray = cv2.undistortPoints(center.reshape(1, 1, 2), k, distortion).reshape(2)
    camera_point = np.array([ray[0]*z, ray[1]*z, z, 1.])
    base_point = (pose_matrix(sample['posx']) @ _transform(profile['T_tcp_camera_mm']) @ camera_point)[:3]
    delta = base_point - reference
    if (not np.isfinite(delta).all() or np.linalg.norm(delta[:2]) > profile['max_shift_mm']
            or abs(delta[2]) > profile['max_height_error_mm']):
        raise ValueError('SUPPLY_DEPTH_DISPLACEMENT_OUT_OF_BOUND')
    target = vector(row['pickup_pose'], 6, 'pickup_pose')
    target[:2] = (np.asarray(target[:2]) + delta[:2]).tolist()
    if any(not a <= value <= b for value, (a, b) in zip(target[:2], bounds)):
        raise ValueError('SUPPLY_DEPTH_TARGET_OUTSIDE_TEACHING_BOUNDS')
    return dict(status='READY', target=target, source_pickup_pose=row['pickup_pose'].copy(),
        center_source_uv=center.tolist(), surface_center_base_mm=base_point.tolist(),
        reference_surface_center_base_mm=reference.tolist(), depth_patch_mm=patch.tolist(),
        camera_info=dict(k=list(info.k), d=list(info.d), width=width, height=height),
        delta_xy_mm=delta[:2].tolist(), depth_mm=z, frame_stamp_ns=stamps[0],
        calibration_ref=profile['calibration_ref'], max_shift_mm=profile['max_shift_mm'],
        verification_basis=('INDEPENDENTLY_VERIFIED' if profile.get('independently_verified') is True
                            else ('OPERATOR_CONDITIONALLY_APPROVED_SUPPLY_MODEL'
                                  if profile.get('educational_acceptance', {}).get('scope') == 'APPROVED_EDUCATIONAL_SUPPLY_REGISTRY'
                                  else 'OPERATOR_ACCEPTED_EDUCATIONAL_T2_SUPPLY_ONLY'
                                  if profile.get('educational_acceptance', {}).get('scope') == 'T2_BLUE_2X3_SLOT3_SUPPLY_ONLY'
                                  else 'OPERATOR_ACCEPTED_EDUCATIONAL_T1')),
        educational_residual_xy_mm=profile.get('educational_acceptance', {}).get('measured_residual_xy_mm'))
