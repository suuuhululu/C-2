"""RGB quadrilateral candidates; visible side faces remain a real-data limitation."""
import cv2
import numpy as np


def validate_surface(settings):
    for key in ('minimum_area', 'approx_fraction', 'minimum_fill'):
        value = settings[key]
        if type(value) not in (int, float) or not np.isfinite(value) or value <= 0:
            raise ValueError(f'surface.{key} requires a measured positive value')
    if not settings['approx_fraction'] < .1 or not settings['minimum_fill'] <= 1:
        raise ValueError('invalid surface approximation/fill limits')
    for color in ('yellow', 'blue', 'red'):
        bands = settings['hsv_ranges'][color]
        if not bands:
            raise ValueError('explicit HSV bands required')
        for lower, upper in bands:
            if (len(lower) != 3 or len(upper) != 3
                    or any(type(n) is not int for n in lower + upper)
                    or not all(0 <= a <= b <= limit for a, b, limit
                               in zip(lower, upper, (179, 255, 255)))):
                raise ValueError('invalid OpenCV HSV band')


def quad_geometry(points, edge_pair):
    """Project unit-rectangle midpoints; pixel arithmetic midpoints skew in perspective."""
    points = np.asarray(points, np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all() or edge_pair not in (0, 1):
        raise ValueError('invalid quad or edge pair')
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1]-center[1], points[:, 0]-center[0])
    quad = points[np.argsort(angles)]
    quad = np.roll(quad, -np.argmin(quad.sum(axis=1)), axis=0)
    if not cv2.isContourConvex(quad) or cv2.contourArea(quad) < 1:
        raise ValueError('degenerate_quad')
    transform = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]), quad)
    midpoints = [[.5,0],[.5,1]] if edge_pair == 0 else [[1,.5],[0,.5]]
    mapped = cv2.perspectiveTransform(np.float32([midpoints + [[.5,.5]]]), transform)[0]
    if not np.isfinite(mapped).all():
        raise ValueError('invalid_projected_center')
    return {'corners_uv': quad.tolist(), 'grasp_midpoints_uv': mapped[:2].tolist(),
            'center_uv': mapped[2].tolist(), 'grasp_edge_pair': edge_pair,
            'method': 'rgb_quad_projective_candidate'}


def top_geometry(frame, box, color, edge_pair, settings):
    validate_surface(settings)
    h, w = frame.shape[:2]
    x1, y1 = np.floor(box[:2]).astype(int)
    x2, y2 = np.ceil(box[2:]).astype(int)
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError('box_outside_frame')
    # Padding avoids accepting an outline manufactured by the YOLO crop boundary.
    left, top = max(0, x1-3), max(0, y1-3)
    right, bottom = min(w, x2+3), min(h, y2+3)
    hsv = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], np.uint8)
    for lower, upper in settings['hsv_ranges'][color]:
        mask |= cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    significant = [c for c in contours if cv2.contourArea(c) >= settings['minimum_area']]
    if len(significant) != 1:
        raise ValueError('missing_or_ambiguous_surface')
    contour = significant[0]
    quad = cv2.approxPolyDP(contour, settings['approx_fraction'] * cv2.arcLength(contour, True), True)
    if len(quad) != 4 or not cv2.isContourConvex(quad):
        raise ValueError('surface_not_four_corners')
    points = quad.reshape(4,2)
    if (np.any(points[:,0] <= 0) or np.any(points[:,0] >= mask.shape[1]-1)
            or np.any(points[:,1] <= 0) or np.any(points[:,1] >= mask.shape[0]-1)):
        raise ValueError('surface_clipped')
    if cv2.contourArea(contour) / cv2.contourArea(quad) < settings['minimum_fill']:
        raise ValueError('surface_outline_unreliable')
    return quad_geometry(points + [left, top], edge_pair)
