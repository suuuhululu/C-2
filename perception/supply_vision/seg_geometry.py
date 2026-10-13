"""Top-mask quadrilateral geometry in pixels; never a robot pose."""
import cv2
import numpy as np

from .top_surface import quad_geometry, validate_surface


def geometry_from_mask(contours, class_name, edge_pair, settings, clipped=False):
    validate_surface(settings)
    if clipped:
        raise ValueError('surface_clipped')
    significant = []
    for points in contours:
        contour = np.asarray(points, np.float32)
        if (contour.ndim != 2 or contour.shape[1] != 2
                or len(contour) < 3 or not np.isfinite(contour).all()):
            raise ValueError('invalid_mask_contour')
        if cv2.contourArea(contour) >= settings['minimum_area']:
            significant.append(contour)
    if len(significant) != 1:
        raise ValueError('missing_or_ambiguous_surface')
    contour = significant[0]
    quad = cv2.approxPolyDP(contour, settings['approx_fraction'] * cv2.arcLength(contour, True), True)
    if len(quad) != 4 or not cv2.isContourConvex(quad):
        raise ValueError('surface_not_four_corners')
    area = cv2.contourArea(quad)
    if area < 1 or min(area, cv2.contourArea(contour)) / max(area, cv2.contourArea(contour)) < settings['minimum_fill']:
        raise ValueError('surface_outline_unreliable')
    geometry = quad_geometry(quad.reshape(4, 2), 0)
    corners = np.asarray(geometry['corners_uv'], np.float32)
    # Pair 0 always denotes opposing long edges, matching the former OBB contract.
    lengths = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    if lengths[1] + lengths[3] > lengths[0] + lengths[2]:
        corners = np.roll(corners, -1, axis=0)
    transform = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]), corners)
    mids = [[.5,0],[.5,1]] if edge_pair == 0 else [[1,.5],[0,.5]]
    if edge_pair not in (0, 1):
        raise ValueError('invalid_edge_pair')
    mapped = cv2.perspectiveTransform(np.float32([mids + [[0,.5],[1,.5]]]), transform)[0]
    axis = mapped[3] - mapped[2]
    square = class_name.endswith('_2x2')
    period = 90 if square else 180
    geometry.update(corners_uv=corners.tolist(), grasp_midpoints_uv=mapped[:2].tolist(),
                    grasp_edge_pair=edge_pair, orientation_deg=float(np.degrees(np.arctan2(axis[1], axis[0])) % period),
                    orientation_period_deg=period,
                    orientation_basis='square_equivalent_axes' if square else 'long_edge',
                    angle_convention='image_positive_u_clockwise_v_down',
                    method='yolo_top_mask_projective_candidate', mask_contour_uv=contour.tolist())
    return geometry
