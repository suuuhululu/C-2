"""Pixel geometry of predicted top-face OBB; never a robot pose."""
import numpy as np


def geometry_from_obb(xywhr, class_name, edge_pair):
    values = np.asarray(xywhr, dtype=float)
    if values.shape != (5,) or not np.isfinite(values).all():
        raise ValueError('invalid_obb_values')
    cx, cy, width, height, angle = values
    if width <= 0 or height <= 0 or edge_pair not in (0, 1):
        raise ValueError('invalid_obb_size_or_edge_pair')
    # Ultralytics predictions may use the short edge as width.
    if width < height:
        width, height = height, width
        angle += np.pi / 2
    angle %= np.pi
    along = np.array([np.cos(angle), np.sin(angle)]) * width / 2
    across = np.array([-np.sin(angle), np.cos(angle)]) * height / 2
    center = np.array([cx, cy])
    corners = np.array([center-along-across, center+along-across,
                        center+along+across, center-along+across])
    mids = [center-across, center+across] if edge_pair == 0 else [center+along, center-along]
    square = class_name.endswith('_2x2')
    period = 90 if square else 180
    return {'center_uv': center.tolist(), 'corners_uv': corners.tolist(),
            'grasp_midpoints_uv': [p.tolist() for p in mids], 'grasp_edge_pair': edge_pair,
            'orientation_deg': float(np.degrees(angle) % period),
            'orientation_period_deg': period,
            'orientation_basis': 'square_equivalent_axes' if square else 'long_edge',
            'angle_convention': 'image_positive_u_clockwise_v_down',
            'method': 'yolo_top_face_obb_candidate'}
