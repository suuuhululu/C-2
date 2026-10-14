"""Experimental circular image features, never verified studs or metric pose.

The existing top-mask geometry remains untouched. Ellipse centers do not in
general equal projected physical circle centers under perspective projection.
"""
from collections import Counter
import math

import cv2
import numpy as np

VERSION = 'round2-circular-feature-detector/1'
SCOPE = 'EXPERIMENTAL_PIXEL_ONLY'


def experimental_config():
    """Explicit experiment settings; no model, camera or production defaults."""
    return dict(version=VERSION, scope=SCOPE, color_order='BGR',
                canny_low=40, canny_high=120, minimum_contour_points=5,
                minimum_diameter_px=4.0, maximum_diameter_px=80.0,
                minimum_axis_ratio=0.35, maximum_normalized_residual=0.20,
                clip_margin_px=1.0, ambiguity_distance_px=3.0, max_candidates=800)


def _validate_config(config):
    if (not isinstance(config, dict) or set(config) != set(experimental_config())
            or config['version'] != VERSION or config['scope'] != SCOPE
            or config['color_order'] not in ('BGR', 'RGB', 'GRAY')):
        raise ValueError('explicit versioned experimental pixel config required')
    for key, value in config.items():
        if key not in ('version', 'scope', 'color_order'):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('positive finite nonbool detector parameter required: '+key)
    if (config['canny_low'] >= config['canny_high'] or config['canny_high'] > 255
            or config['minimum_diameter_px'] >= config['maximum_diameter_px']
            or not 0 < config['minimum_axis_ratio'] <= 1
            or not 0 < config['maximum_normalized_residual'] <= 1
            or type(config['minimum_contour_points']) is not int
            or config['minimum_contour_points'] < 5
            or type(config['max_candidates']) is not int):
        raise ValueError('inconsistent detector bounds')


def detect_circular_candidates(frame, *, roi_xyxy, config):
    """Return all unverified contour/ellipse candidates in original image pixels.

    Close or concentric hypotheses are retained and marked ambiguous; no winner
    or lattice cell is selected. Caller owns timestamp/frame/source provenance.
    """
    _validate_config(config)
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
        raise ValueError('original uint8 image required')
    gray_input = config['color_order'] == 'GRAY'
    if ((gray_input and frame.ndim != 2)
            or (not gray_input and (frame.ndim != 3 or frame.shape[2] != 3))
            or not frame.size):
        raise ValueError('image channels disagree with explicit color order')
    height, width = frame.shape[:2]
    if (not isinstance(roi_xyxy, (list, tuple)) or len(roi_xyxy) != 4
            or any(type(v) is not int for v in roi_xyxy)):
        raise ValueError('integer original-image ROI required')
    x0, y0, x1, y1 = roi_xyxy
    if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
        raise ValueError('ROI outside original image')
    patch = frame[y0:y1, x0:x1]
    if gray_input:
        gray = patch
    else:
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY if config['color_order'] == 'BGR'
                            else cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, config['canny_low'], config['canny_high'])
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    candidates, rejected = [], Counter()
    margin = config['clip_margin_px']
    for contour in contours:
        if len(contour) < config['minimum_contour_points']:
            rejected['INSUFFICIENT_CONTOUR_POINTS'] += 1
            continue
        points = contour.reshape(-1, 2).astype(float)
        clipped = bool((points[:, 0] <= margin).any() or (points[:, 1] <= margin).any()
                       or (points[:, 0] >= x1-x0-1-margin).any()
                       or (points[:, 1] >= y1-y0-1-margin).any())
        if clipped:
            rejected['CONTOUR_TOUCHES_ROI_BOUNDARY'] += 1
        (cx, cy), (axis_a, axis_b), angle = cv2.fitEllipse(contour)
        if (not all(math.isfinite(v) for v in (cx, cy, axis_a, axis_b, angle))
                or min(axis_a, axis_b) < config['minimum_diameter_px']
                or max(axis_a, axis_b) > config['maximum_diameter_px']
                or min(axis_a, axis_b)/max(axis_a, axis_b) < config['minimum_axis_ratio']):
            rejected['ELLIPSE_SIZE_OR_AXIS_RATIO'] += 1
            continue
        radians = math.radians(angle)
        rotation = np.array([[math.cos(radians), -math.sin(radians)],
                             [math.sin(radians), math.cos(radians)]])
        local = (points-np.array([cx, cy])) @ rotation
        radial = np.sqrt(np.square(local[:, 0]/(axis_a/2))
                         + np.square(local[:, 1]/(axis_b/2)))
        residual = float(np.mean(np.abs(radial-1)))
        if residual > config['maximum_normalized_residual']:
            rejected['NON_ELLIPTIC_CONTOUR'] += 1
            continue
        if len(candidates) >= config['max_candidates']:
            rejected['CANDIDATE_BUDGET_EXCEEDED'] += 1
            continue
        candidates.append(dict(candidate_id='edge-ellipse-'+str(len(candidates)),
            feature_kind='CIRCULAR_FEATURE_CANDIDATE_UNVERIFIED',
            source='OBSERVED_IMAGE_EDGE_CONTOUR', units='pixel', center_uv=[cx+x0, cy+y0],
            ellipse_axes_px=[axis_a, axis_b], ellipse_angle_deg=angle,
            angle_convention='image_u_right_v_down',
            contour_uv=(points+np.array([x0, y0])).tolist(),
            normalized_fit_residual=residual, fit_residual_px=residual*min(axis_a, axis_b)/2,
            residual_is_physical_uncertainty=False, physical_uncertainty_px=None,
            clipped=clipped, ambiguous=clipped,
            ambiguity_reasons=['CLIPPED_ROI_BOUNDARY'] if clipped else [],
            nearby_candidate_ids=[], lattice_id=None, projected_center_uv=None,
            stud_verified=False, physical_circle_center_verified=False))
    for index, candidate in enumerate(candidates):
        for other in candidates[index+1:]:
            if math.dist(candidate['center_uv'], other['center_uv']) <= config['ambiguity_distance_px']:
                for first, second in ((candidate, other), (other, candidate)):
                    first['ambiguous'] = True
                    reason = 'CONCENTRIC_EDGE_DUPLICATE_OR_NEAR_CENTER_AMBIGUITY'
                    if reason not in first['ambiguity_reasons']:
                        first['ambiguity_reasons'].append(reason)
                    first['nearby_candidate_ids'].append(second['candidate_id'])
    return dict(version=VERSION, scope=SCOPE, units='pixel',
                status='UNKNOWN_CANDIDATE_BUDGET_EXCEEDED' if rejected['CANDIDATE_BUDGET_EXCEEDED']
                else 'CIRCULAR_FEATURE_CANDIDATES_UNVERIFIED' if candidates
                else 'UNKNOWN_NO_CIRCULAR_FEATURES',
                image_size=[width, height], roi_xyxy=list(roi_xyxy), frame_id=None, frame_stamp=None,
                candidates=candidates, rejected_counts=dict(rejected),
                physical_center_note='Ellipse fit center is not a verified projection of a physical 3D circle center',
                actual_studs_verified=False, lattice_assignment_verified=False,
                metric_pose=dict(status='UNKNOWN', position_m=None, quaternion_xyzw=None),
                e_xy_m=None, e_yaw_deg=None, robot_target=None, physical_commands=0,
                execution_allowed=False, physical_gate_passed=False, next_motion_allowed=False)
