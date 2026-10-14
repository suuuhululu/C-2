"""Opt-in RGB-D supply correction. Coordinates are mm in the robot Base frame."""
from hashlib import sha256
import json
from pathlib import Path

import cv2
import numpy as np

from app.assembly_motion import vector
from supply_vision.held_xy_alignment import _camera, _transform
from supply_vision.virtual_board_grid import pose_matrix


def load_profile(path, layout_path, config):
    profile = json.loads(Path(path).read_text())
    if (profile.get('schema_version') != 'supply-depth-center/1'
            or profile.get('independently_verified') is not True
            or not isinstance(profile.get('calibration_ref'), str) or not profile['calibration_ref'].strip()):
        raise ValueError('SUPPLY_DEPTH_CALIBRATION_NOT_VERIFIED')
    required = {'connection', 'observation_pose', 'layout_sha256', 'T_tcp_camera_mm', 'input_size',
                'camera_frame', 'max_shift_mm', 'max_height_error_mm', 'max_depth_spread_mm',
                'depth_range_mm', 'references'}
    if not required <= profile.keys():
        raise ValueError('SUPPLY_DEPTH_PROFILE_FIELDS_REQUIRED')
    if (profile['connection'] != {k: config['connection'][k] for k in ('robot_id', 'tcp', 'tool')}
            or profile['observation_pose'] != config['observation_pose']
            or profile['layout_sha256'] != sha256(Path(layout_path).read_bytes()).hexdigest()):
        raise ValueError('SUPPLY_DEPTH_SETUP_BINDING_MISMATCH')
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
    if (any(not 0 <= now_ns - s <= 300_000_000 for s in stamps)
            or max(stamps) - min(stamps) > 50_000_000):
        raise ValueError('SUPPLY_DEPTH_FRESH_SYNCHRONIZED_PACKET_REQUIRED')
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
        raise ValueError('SUPPLY_DEPTH_SURFACE_UNAVAILABLE')
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
        calibration_ref=profile['calibration_ref'], max_shift_mm=profile['max_shift_mm'])
