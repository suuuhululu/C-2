"""Measured 3D correspondences to tilt/yaw corrections and pad contact previews.

Points are labelled body-top features in robot base millimetres. RGB-D and
contact-derived observations use the same geometry; a wrench alone is not a pose.
"""
import math
import warnings

import numpy as np
from scipy.spatial.transform import Rotation


def _points(value):
    points = np.asarray(value, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 4 or not np.isfinite(points).all():
        raise ValueError('FOUR_LABELLED_FINITE_3D_POINTS_REQUIRED')
    if np.linalg.matrix_rank(points - points.mean(axis=0), tol=1e-8) < 2:
        raise ValueError('NONCOLLINEAR_BODY_TOP_POINTS_REQUIRED')
    return points


def _pose(value):
    pose = np.asarray(value, dtype=float)
    if pose.shape != (6,) or not np.isfinite(pose).all():
        raise ValueError('FINITE_TCP_MM_ZYZ_DEG_REQUIRED')
    return pose


def _transform(value):
    matrix = np.asarray(value, dtype=float)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
            or not np.allclose(matrix[3], [0, 0, 0, 1])
            or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-8)
            or not math.isclose(np.linalg.det(matrix[:3, :3]), 1., abs_tol=1e-8)):
        raise ValueError('MEASURED_RIGID_PAD_TRANSFORM_REQUIRED')
    return matrix


def align_top(observation, target, held_tcp, limits):
    """Move a held block about its observed datum, preserving the measured grasp.

First four matched features fit; remaining matched points independently check
the rotation/translation. Target points encode the actual fastening orientation.
"""
    if observation.get('frame') != 'robot_base' or target.get('frame') != 'robot_base':
        raise ValueError('ROBOT_BASE_POINTS_REQUIRED')
    if observation.get('units') != 'mm' or target.get('units') != 'mm':
        raise ValueError('MILLIMETRES_REQUIRED')
    if observation.get('source') not in ('RGBD', 'CONTACT_GEOMETRY'):
        raise ValueError('VISION_OR_MEASURED_CONTACT_GEOMETRY_REQUIRED')
    if observation.get('binding') != target.get('binding') or not observation.get('binding'):
        raise ValueError('MATCHING_ACTIVE_BLOCK_BINDING_REQUIRED')
    ids = observation.get('feature_ids')
    if ids != target.get('feature_ids') or not isinstance(ids, list) or len(ids) < 6 or len(set(ids)) != len(ids):
        raise ValueError('FOUR_FIT_TWO_CHECK_LABELLED_FEATURES_REQUIRED')
    source, expected = _points(observation['points_mm']), _points(target['points_mm'])
    if source.shape != expected.shape or len(source) != len(ids):
        raise ValueError('FEATURE_POINT_COUNT_MISMATCH')
    required = ('max_fit_error_mm', 'max_check_error_mm', 'max_translation_mm', 'max_rotation_deg')
    if any(type(limits.get(k)) not in (int, float) or not math.isfinite(limits[k]) or limits[k] <= 0 for k in required):
        raise ValueError('REVIEWED_ALIGNMENT_LIMITS_REQUIRED')
    a, b = source[:4], expected[:4]
    _points(a); _points(b)
    def normal(points):
        _, _, axes = np.linalg.svd(points-points.mean(axis=0))
        n = axes[-1]
        return n if n[2] >= 0 else -n
    source_normal, target_normal = normal(a), normal(b)
    u, _, vt = np.linalg.svd((a-a.mean(axis=0)).T @ (b-b.mean(axis=0)))
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    translation = b.mean(axis=0) - rotation @ a.mean(axis=0)
    errors = np.linalg.norm(source @ rotation.T + translation - expected, axis=1)
    angle = math.degrees(Rotation.from_matrix(rotation).magnitude())
    pose = _pose(held_tcp)
    corrected_xyz = rotation @ pose[:3] + translation
    if (max(errors[:4]) > limits['max_fit_error_mm'] or max(errors[4:]) > limits['max_check_error_mm']
            or np.linalg.norm(corrected_xyz-pose[:3]) > limits['max_translation_mm']
            or angle > limits['max_rotation_deg']):
        raise ValueError('ALIGNMENT_OUTSIDE_REVIEWED_ENVELOPE')
    # Compose SO(3) around the measured block, never increment controller Euler angles.
    corrected_rotation = rotation @ Rotation.from_euler('ZYZ', pose[3:], degrees=True).as_matrix()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        angles = Rotation.from_matrix(corrected_rotation).as_euler('ZYZ', degrees=True)
    return dict(status='TOP_ALIGNMENT_PREVIEW', binding=observation['binding'],
                aligned_held_tcp_mm_zyz_deg=[*corrected_xyz.tolist(), *angles.tolist()],
                correction_rotation_matrix=rotation.tolist(), correction_translation_mm=translation.tolist(),
                fit_error_mm=float(max(errors[:4])), check_error_mm=float(max(errors[4:])),
                rotation_correction_deg=angle,
                observed_top_normal_base=source_normal.tolist(), target_top_normal_base=target_normal.tolist(),
                observed_tilt_deg=math.degrees(math.acos(float(np.clip(source_normal[2],-1,1)))),
                target_tilt_deg=math.degrees(math.acos(float(np.clip(target_normal[2],-1,1)))),
                execution_allowed=False, physical_commands=0)


def pad_approach(contact_frame_base_mm, tcp_from_closed_pad_mm, clearance_mm):
    """A independently measured empty-pad datum determines TCP, including tilt.

Contact frame +Z is the outward normal; clearance moves along that normal.
This computes a preview only. The current force runner presses along Base -Z.
"""
    contact, pad = _transform(contact_frame_base_mm), _transform(tcp_from_closed_pad_mm)
    if type(clearance_mm) not in (int, float) or not math.isfinite(clearance_mm) or clearance_mm <= 0:
        raise ValueError('MEASURED_POSITIVE_CLEARANCE_REQUIRED')
    contact = contact.copy()
    contact[:3, 3] += contact[:3, 2] * clearance_mm
    tcp = contact @ np.linalg.inv(pad)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        angles = Rotation.from_matrix(tcp[:3, :3]).as_euler('ZYZ', degrees=True)
    return dict(status='CLOSED_PAD_APPROACH_PREVIEW',
                tcp_mm_zyz_deg=[*tcp[:3, 3].tolist(), *angles.tolist()],
                surface_normal_base=contact[:3, 2].tolist(), execution_allowed=False, physical_commands=0)


def align_visible_edge(observation, target, held_tcp, limits):
    """Two corresponding visible corners plus depth-plane normals determine SE(3).

The Step identifies the physical edge. Normals come from registered depth on
the coloured body top and target support. Neither a visible-mask centroid nor
an assumption that the gripper holds the exact centre is needed.
"""
    if (observation.get('frame')!='robot_base' or target.get('frame')!='robot_base'
            or observation.get('units')!='mm' or target.get('units')!='mm'
            or not observation.get('binding') or observation.get('binding')!=target.get('binding')
            or not observation.get('edge_id') or observation.get('edge_id')!=target.get('edge_id')):
        raise ValueError('MATCHING_STEP_EDGE_BASE_MM_REQUIRED')
    edges=[];bases=[]
    for record in (observation,target):
        edge=np.asarray(record['points_mm'],float);normal=np.asarray(record['top_normal_base'],float)
        if (edge.shape!=(2,3) or normal.shape!=(3,) or not np.isfinite(edge).all()
                or not np.isfinite(normal).all() or not math.isclose(np.linalg.norm(normal),1.,abs_tol=1e-6)):
            raise ValueError('TWO_OBSERVED_CORNERS_AND_UNIT_TOP_NORMAL_REQUIRED')
        direction=edge[1]-edge[0];direction-=normal*np.dot(direction,normal)
        if np.linalg.norm(direction)<1e-8:
            raise ValueError('DEGENERATE_VISIBLE_EDGE')
        direction/=np.linalg.norm(direction)
        bases.append(np.column_stack([direction,np.cross(normal,direction),normal]));edges.append(edge)
    for key in ('max_fit_error_mm','max_translation_mm','max_rotation_deg'):
        if type(limits.get(key)) not in (int,float) or not math.isfinite(limits[key]) or limits[key]<=0:
            raise ValueError('REVIEWED_EDGE_ALIGNMENT_LIMITS_REQUIRED')
    rotation=bases[1]@bases[0].T
    translation=edges[1].mean(axis=0)-rotation@edges[0].mean(axis=0)
    residual=np.linalg.norm(edges[0]@rotation.T+translation-edges[1],axis=1)
    pose=_pose(held_tcp);xyz=rotation@pose[:3]+translation
    angle=math.degrees(Rotation.from_matrix(rotation).magnitude())
    if (max(residual)>limits['max_fit_error_mm'] or np.linalg.norm(xyz-pose[:3])>limits['max_translation_mm']
            or angle>limits['max_rotation_deg']):
        raise ValueError('VISIBLE_EDGE_ALIGNMENT_OUTSIDE_ENVELOPE')
    tcp_rotation=rotation@Rotation.from_euler('ZYZ',pose[3:],degrees=True).as_matrix()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        angles=Rotation.from_matrix(tcp_rotation).as_euler('ZYZ',degrees=True)
    return dict(status='VISIBLE_EDGE_DEPTH_ALIGNMENT_PREVIEW',binding=observation['binding'],
        edge_id=observation['edge_id'],visible_corner_count=2,centred_grasp_assumed=False,
        aligned_held_tcp_mm_zyz_deg=[*xyz.tolist(),*angles.tolist()],
        correction_rotation_matrix=rotation.tolist(),correction_translation_mm=translation.tolist(),
        edge_fit_error_mm=float(max(residual)),independent_accuracy_verified=False,
        requires_registered_stud_target_and_body_top_normal=True,
        execution_allowed=False,physical_commands=0)


def opencv_corner_stud_comparison(frame, bundle):
    """No training: body outline plus nearby registered stud image correspondences.

These pixel correspondences feed the registered RGB-D alignment step. A stud
plane homography does not by itself calibrate a raised block's robot pose.
"""
    import cv2
    from scipy.optimize import linear_sum_assignment
    from supply_vision.top_surface import top_geometry
    from supply_vision.stud_observation import detect_circular_candidates
    from supply_vision.assembly_alignment import _fit_se2
    result=dict(status='UNKNOWN',execution_allowed=False,physical_commands=0,
                requires_registered_depth=True,robot_target=None)
    try:
        limits=bundle['limits']
        for key in ('max_stud_match_px','max_heldout_error_px','max_corner_error_px'):
            if type(limits.get(key)) not in (int,float) or not math.isfinite(limits[key]) or limits[key]<=0:
                raise ValueError('EXPLICIT_PIXEL_MATCH_LIMITS_REQUIRED')
        geometry=top_geometry(frame,bundle['block_roi_xyxy'],bundle['color'],0,bundle['surface_settings'])
        circles=detect_circular_candidates(frame,roi_xyxy=bundle['stud_roi_xyxy'],config=bundle['detector_config'])
        expected=np.asarray(bundle['expected_visible_stud_centers_uv'],dtype=float)
        corners=np.asarray(bundle['expected_block_corners_uv'],dtype=float)
        if (expected.ndim!=2 or expected.shape[1]!=2 or len(expected)<6 or corners.shape!=(4,2)
                or not np.isfinite(expected).all() or not np.isfinite(corners).all()
                or np.linalg.matrix_rank(expected[:4]-expected[:4].mean(axis=0))<2):
            raise ValueError('FOUR_FIT_TWO_CHECK_REGISTERED_VISIBLE_STUDS_REQUIRED')
        spacing=np.linalg.norm(expected[:,None]-expected[None,:],axis=2)
        np.fill_diagonal(spacing,np.inf)
        if limits['max_stud_match_px']>=float(spacing.min())/2:
            raise ValueError('MATCH_WINDOW_COULD_SELECT_ADJACENT_STUD_CELL')
        # Canny often observes both edges of one stud. Merge their image
        # hypotheses for matching while retaining the original evidence IDs.
        groups=[];radius=bundle['detector_config']['ambiguity_distance_px']
        for candidate in circles['candidates']:
            if candidate['clipped']:continue
            center=np.asarray(candidate['center_uv'],float)
            group=next((g for g in groups if np.linalg.norm(center-np.mean(g,axis=0))<=radius),None)
            if group is None:groups.append([center])
            else:group.append(center)
        observed=np.asarray([np.mean(g,axis=0) for g in groups],float)
        if len(observed)<len(expected):raise ValueError('VISIBLE_STUD_FEATURES_INSUFFICIENT')
        costs=np.linalg.norm(expected[:,None]-observed[None,:],axis=2)
        rows,cols=linear_sum_assignment(costs)
        matched=observed[cols]
        if not np.array_equal(rows,np.arange(len(expected))) or np.max(costs[rows,cols])>limits['max_stud_match_px']:
            raise ValueError('REGISTERED_STUD_CELL_MATCH_FAILED')
        homography,_=cv2.findHomography(expected[:4],matched[:4],method=0)
        if homography is None or not np.isfinite(homography).all():raise ValueError('STUD_PLANE_FIT_FAILED')
        projected=cv2.perspectiveTransform(expected[None].astype(np.float64),homography)[0]
        residual=np.linalg.norm(projected[4:]-matched[4:],axis=1)
        if max(residual)>limits['max_heldout_error_px']:raise ValueError('INDEPENDENT_VISIBLE_STUD_CHECK_FAILED')
        # The supplied block corners are projected in the current camera at the
        # block-top height. Warping them with a stud-plane homography would mix
        # two different depth planes and invent a correction.
        target=corners
        observed_corners=np.asarray(geometry['corners_uv'],float)
        rotation,translation=_fit_se2(observed_corners,target)
        corner_error=np.linalg.norm(observed_corners@rotation.T+translation-target,axis=1)
        if max(corner_error)>limits['max_corner_error_px']:raise ValueError('BODY_CORNER_ORDER_OR_SHAPE_MISMATCH')
        result.update(status='OPENCV_CORNER_STUD_PIXEL_COMPARISON',
            block_corners_uv=observed_corners.tolist(),body_center_uv=geometry['center_uv'],
            expected_visible_stud_centers_uv=expected.tolist(),observed_visible_stud_centers_uv=matched.tolist(),
            stud_heldout_error_px=residual.tolist(),target_corner_pixel_preview=target.tolist(),
            stud_plane_homography_diagnostic=homography.tolist(),
            pixel_center_error=(target.mean(axis=0)-observed_corners.mean(axis=0)).tolist(),
            pixel_yaw_error_deg=math.degrees(math.atan2(rotation[1,0],rotation[0,0])),
            source='OPENCV_CONTOUR_AND_ELLIPSE_NO_TRAINING',
            note='Pixel diagnostic only; registered Depth and separate block/stud plane datums required before robot correction')
    except (ValueError,KeyError,TypeError,cv2.error,np.linalg.LinAlgError) as error:
        result['reason']=str(error)
    return result


def visible_colored_block(frame, roi, color, surface_settings):
    """Keep partially visible block evidence; require no complete quadrilateral.

The Step supplies type/color. A visible-mask centroid is not the full body's
centre and image/ROI boundaries are never reported as physical block edges.
"""
    import cv2
    from supply_vision.top_surface import validate_surface
    validate_surface(surface_settings)
    if color not in ('yellow','blue','red'):
        raise ValueError('STEP_BLOCK_COLOR_REQUIRED')
    height,width=frame.shape[:2]
    if len(roi)!=4 or any(type(v) is not int for v in roi):
        raise ValueError('ORIGINAL_IMAGE_ROI_REQUIRED')
    x0,y0,x1,y1=roi
    if not 0<=x0<x1<=width or not 0<=y0<y1<=height:
        raise ValueError('ORIGINAL_IMAGE_ROI_REQUIRED')
    hsv=cv2.cvtColor(frame[y0:y1,x0:x1],cv2.COLOR_BGR2HSV)
    mask=np.zeros(hsv.shape[:2],np.uint8)
    for low,high in surface_settings['hsv_ranges'][color]:
        mask|=cv2.inRange(hsv,np.array(low,np.uint8),np.array(high,np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    contours=[c for c in contours if cv2.contourArea(c)>=surface_settings['minimum_area']]
    result=dict(status='UNKNOWN',source='STEP_COLOR_OPENCV_NO_TRAINING',color=color,
        roi_xyxy=list(roi),physical_commands=0,execution_allowed=False,
        full_body_center_uv=None,full_body_pose_verified=False)
    if len(contours)!=1:
        result['reason']='NO_COLOR_COMPONENT' if not contours else 'MULTIPLE_COLOR_COMPONENTS'
        return result
    contour=contours[0];polygon=cv2.approxPolyDP(contour,
        surface_settings['approx_fraction']*cv2.arcLength(contour,True),True).reshape(-1,2)
    local=contour.reshape(-1,2)
    clipped=bool((local[:,0]<=1).any() or (local[:,1]<=1).any()
        or (local[:,0]>=x1-x0-2).any() or (local[:,1]>=y1-y0-2).any())
    def boundary(point):
        return point[0]<=1 or point[1]<=1 or point[0]>=x1-x0-2 or point[1]>=y1-y0-2
    offset=np.array([x0,y0]);edges=[]
    for first,second in zip(polygon,np.roll(polygon,-1,axis=0)):
        if not boundary(first) and not boundary(second):
            edges.append([(first+offset).tolist(),(second+offset).tolist()])
    moments=cv2.moments(contour)
    result.update(status='PARTIAL_COLOR_BLOCK_OBSERVATION' if clipped else 'COLOR_BLOCK_OBSERVATION',
        clipped_or_occluded_at_image_boundary=clipped,
        visible_contour_uv=(local+offset).tolist(),visible_edges_uv=edges,
        edge_semantics='VISIBLE_COLOR_CONTOUR_SEGMENTS_NOT_VERIFIED_BODY_EDGES',
        visible_mask_centroid_uv=[moments['m10']/moments['m00']+x0,moments['m01']/moments['m00']+y0],
        centroid_is_full_body_center=False,
        next_step='Match visible edges to the Step footprint and registered target studs; use Depth for tilt')
    return result


def main():
    import argparse
    import json
    from pathlib import Path
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'perception'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('align', 'align-edge', 'pad-approach', 'opencv-compare', 'opencv-visible'))
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    bundle = json.loads(args.input.read_text())
    if args.command == 'align':
        result = align_top(bundle['observation'], bundle['target'], bundle['held_tcp_mm_zyz_deg'], bundle['limits'])
    elif args.command == 'align-edge':
        result = align_visible_edge(bundle['observation'],bundle['target'],bundle['held_tcp_mm_zyz_deg'],bundle['limits'])
    elif args.command == 'pad-approach':
        result = pad_approach(bundle['contact_frame_base_mm'], bundle['tcp_from_closed_pad_mm'], bundle['clearance_mm'])
    else:
        import cv2
        frame=cv2.imread(bundle['image_path'])
        if frame is None:raise ValueError('ORIGINAL_RGB_REQUIRED')
        if args.command=='opencv-visible':
            result=visible_colored_block(frame,bundle['block_roi_xyxy'],bundle['color'],bundle['surface_settings'])
        else:
            result=opencv_corner_stud_comparison(frame,bundle)
    with args.out.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(status=result['status'], output=str(args.out.resolve()), physical_commands=0)))


if __name__ == '__main__':
    main()
