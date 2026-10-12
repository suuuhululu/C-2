"""Separated-color diagnostic candidates only; never sends Observed or adopts calibration."""
from collections import deque

import cv2
import numpy as np


# Starting values from the color review, not validated deployment thresholds.
HSV_RANGES = {'yellow': ((18, 80, 60), (40, 255, 255)),
              'blue': ((95, 80, 25), (135, 255, 255)),
              'red': ((0, 80, 40), (10, 255, 255))}


def color_mask(hsv, color):
    lower, upper = HSV_RANGES[color]
    mask = cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8))
    if color == 'red':
        # Red wraps around OpenCV's 0..179 hue domain.
        mask |= cv2.inRange(hsv, np.array((170, 80, 40), np.uint8),
                            np.array((179, 255, 255), np.uint8))
    return mask


def grid_anchor(center, size, angle, pitch, tolerance=.25):
    """Diagnostic Grid snapping; systematic calibration error is NOT averaged away."""
    if size == (2, 2):
        spans = np.array([2, 2])
    else:
        spans = np.array([size[1], size[0]] if angle == 0 else [size[0], size[1]])
    continuous = np.asarray(center) / pitch - (spans - 1) / 2
    anchor = np.rint(continuous).astype(int)
    if np.max(np.abs(continuous - anchor)) > tolerance:
        raise ValueError('position_off_grid')
    if np.any(anchor < 0) or np.any(anchor + spans > 24):
        raise ValueError('outside_board')
    return continuous, anchor


def top_surface_points(board, *, band_mm=3., minimum_points=50):
    """Select a supported Board-parallel surface, not the entire side-wall cloud.

    These geometric trial limits are not calibrated deployment thresholds. A
    dense height band alone is insufficient: tilted/line-like patches fail.
    """
    if len(board) < minimum_points or not np.isfinite(board).all():
        raise ValueError('top_surface_depth_insufficient')
    heights = board[:, 2]
    edges = np.arange(np.min(heights)-band_mm, np.max(heights)+band_mm+1., 1.)
    counts, edges = np.histogram(heights, bins=edges)
    support = np.convolve(counts, np.ones(int(2*band_mm)+1), mode='same')
    level = (edges[int(np.argmax(support))]+edges[int(np.argmax(support))+1])/2
    keep = np.abs(heights-level) <= band_mm
    if keep.sum() < minimum_points or keep.mean() < .25:
        raise ValueError('top_surface_depth_insufficient')
    # A visible side sliced by a height band must not masquerade as a top plane.
    patch = board[keep]
    design = np.column_stack((patch[:, :2]-np.mean(patch[:, :2], axis=0), np.ones(len(patch))))
    plane, _, rank, _ = np.linalg.lstsq(design, patch[:, 2], rcond=None)
    if rank < 3 or np.linalg.norm(plane[:2]) > np.tan(np.deg2rad(10.)):
        raise ValueError('top_surface_not_board_parallel')
    level = float(np.median(patch[:, 2]))
    keep = np.abs(heights-level) <= band_mm
    if keep.sum() < minimum_points or keep.mean() < .25:
        raise ValueError('top_surface_depth_insufficient')
    return keep


def rgb_top_quad(rgb, mask, top_mask):
    """RGB edges propose four corners; measured top pixels check their support.

    No rectangle is invented from a partial Depth patch or an occluded contour.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120)  # Temporary camera trial values.
    search = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
    edges[search == 0] = 0
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    color_contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
    options = []
    for contour in contours + color_contours:
        quad = cv2.approxPolyDP(contour, .025*cv2.arcLength(contour, True), True)
        area = cv2.contourArea(quad)
        if len(quad) != 4 or not cv2.isContourConvex(quad) or area < 150:
            continue
        inside = np.zeros(mask.shape, np.uint8)
        cv2.fillConvexPoly(inside, quad, 1)
        pixels = inside.astype(bool)
        if np.count_nonzero(pixels & mask) / pixels.sum() < .85:
            continue
        if np.count_nonzero(pixels & top_mask) / max(1, top_mask.sum()) < .8:
            continue
        interior = cv2.erode(inside, np.ones((3, 3), np.uint8)).astype(bool)
        if not interior.any() or np.count_nonzero(interior & top_mask) / interior.sum() < .55:
            continue
        options.append((area, quad.reshape(4, 2)))
    if not options:
        raise ValueError('rgb_top_outline_unverified')
    return max(options, key=lambda option: option[0])[1]


def corners_at_height(pixels, height_mm, info, calibration):
    """Intersect RGB corner rays with the measured Board-parallel top plane."""
    k = np.asarray(info['k']).reshape(3, 3)
    pose = calibration['camera_pose']
    rotation = np.asarray(pose['R_camera_from_board'])
    origin = -np.asarray(pose['t_camera_from_board_mm']) @ rotation
    rays = np.column_stack((pixels, np.ones(len(pixels)))) @ np.linalg.inv(k).T @ rotation
    denominator = rays[:, 2]
    if np.any(np.abs(denominator) < 1e-8):
        raise ValueError('top_plane_ray_parallel')
    distances = (height_mm / pose['height_normal_sign']-origin[2]) / denominator
    if not np.isfinite(distances).all() or np.any(distances <= 0):
        raise ValueError('top_plane_behind_camera')
    return (origin + distances[:, None]*rays)[:, :2]


def candidates(rgb, depth, info, calibration, *, minimum_area=150):
    """Masks from HSV are NOT guaranteed individual bricks, particularly when touching."""
    from .live_view import board_point
    if rgb.shape[:2] != depth.shape or rgb.dtype != np.uint8 or depth.dtype != np.uint16:
        raise ValueError('RGB/aligned Depth format mismatch')
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, w = depth.shape
    yy, xx = np.indices((h, w))
    rays = np.column_stack((xx.ravel(), yy.ravel(), np.ones(h*w)))
    projected = rays @ np.asarray(calibration['H_board_from_undistorted_pixel']).T
    with np.errstate(divide='ignore', invalid='ignore'):
        xy = projected[:, :2] / projected[:, 2:3]
    pitch = calibration['pitch_mm']
    limits = (np.array([calibration['cols'], calibration['rows']])-.5)*pitch
    # Only a search ROI; NOT verified occupancy, and edge blocks may remain unverified.
    roi = (np.isfinite(xy).all(axis=1) & np.all(xy >= -.5*pitch, axis=1)
           & np.all(xy <= limits, axis=1)).reshape(h, w)
    output = []
    for color in HSV_RANGES:
        mask = color_mask(hsv, color)
        mask[~roi] = 0
        count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
        for index in range(1, count):
            if stats[index, cv2.CC_STAT_AREA] < minimum_area:
                continue
            selected = labels == index
            record = {'color': color, 'mask': selected, 'pixel_center': centers[index],
                      'status': 'UNKNOWN', 'reason': 'insufficient_depth'}
            output.append(record)
            v, u = np.nonzero(selected & (depth > 0))
            if len(u) < 50 or len(u) / np.count_nonzero(selected) < .8:
                continue
            try:
                # Validate CameraInfo/calibration before vectorized deprojection.
                board_point((int(u[0]), int(v[0])), depth, info, calibration)
                k = np.asarray(info['k']).reshape(3, 3)
                z = depth[v, u].astype(float)
                camera = np.column_stack(((u-k[0, 2])*z/k[0, 0],
                                          (v-k[1, 2])*z/k[1, 1], z))
                pose = calibration['camera_pose']
                board = (camera-np.asarray(pose['t_camera_from_board_mm'])) @ np.asarray(
                    pose['R_camera_from_board'])
                board[:, 2] *= pose['height_normal_sign']
                keep = top_surface_points(board)
                points = board[keep]
                top_mask = np.zeros(selected.shape, bool)
                top_mask[v[keep], u[keep]] = True
                record['top_mask'] = top_mask
                record['height_mm'] = float(np.median(points[:, 2]))
                quad = rgb_top_quad(rgb, selected, top_mask)
                record['top_quad'] = quad
                # Estimate height from the supported interior, not boundary/side Depth.
                interior = np.zeros(selected.shape, np.uint8)
                cv2.fillConvexPoly(interior, quad, 1)
                interior = cv2.erode(interior, np.ones((3, 3), np.uint8)).astype(bool)
                supported = keep & interior[v, u]
                if supported.sum() < 50:
                    raise ValueError('top_interior_depth_insufficient')
                record['height_mm'] = float(np.median(board[supported, 2]))
                corners = corners_at_height(quad, record['height_mm'], info, calibration)
                rect = cv2.minAreaRect(corners.astype(np.float32))
                center, sides, angle = rect
                pitch = float(calibration['pitch_mm'])
                sizes = np.asarray(sorted(sides)) / pitch
                supported_sizes = ((1, 2),) if color == 'red' else ((2, 2), (2, 3))
                errors = [np.max(np.abs(sizes - expected)) for expected in supported_sizes]
                size = supported_sizes[int(np.argmin(errors))]
                if min(errors) > .35:
                    raise ValueError('size_unverified_reflection_or_touching')
                if sides[0] < sides[1]:
                    angle += 90
                period = 90 if size == (2, 2) else 180
                angle %= period
                axis = (round(angle / 90)*90) % period
                if abs((angle-axis+period/2) % period-period/2) > 10:
                    raise ValueError('orientation_off_grid')
                record['size_hint'] = f'{size[0]}x{size[1]}'
                record['anchor_mm'] = (np.asarray(center) - (
                    np.array([size[1], size[0]] if axis == 0 else [size[0], size[1]])-1
                )*pitch/2).tolist()
                continuous, anchor = grid_anchor(center, size, axis, pitch)
                record.update(status='CANDIDATE', reason=None, grid_float=continuous,
                              grid=anchor.tolist())
            except (ValueError, KeyError, cv2.error) as error:
                record['reason'] = str(error)
    return output


def stabilize(records, tracks, *, frames=5, max_pixel_distance=30):
    """Track by image proximity for a stopped View only; do not reuse missing detections."""
    next_tracks, used = [], set()
    for record in records:
        eligible = [(np.linalg.norm(record['pixel_center']-old['pixel_center']), index)
                    for index, old in enumerate(tracks)
                    if index not in used and old['color'] == record['color']
                    and old.get('size_hint') == record.get('size_hint')]
        match = min(eligible) if eligible else None
        history = deque(maxlen=frames)
        if match and match[0] <= max_pixel_distance:
            used.add(match[1])
            history.extend(tracks[match[1]]['history'])
        if record['status'] != 'CANDIDATE':
            history.clear()
        else:
            history.append(record['grid_float'].copy())
            record.update(status='UNKNOWN', reason='stabilizing')
            if len(history) == frames:
                values = np.asarray(history)
                if np.max(np.ptp(values, axis=0)) > .15:
                    record['reason'] = 'position_unstable'
                else:
                    # Every frame passed Grid residual checks; require one common integer.
                    rounded = np.rint(values).astype(int)
                    if np.all(rounded == rounded[0]):
                        record.update(status='STABLE_CANDIDATE', reason=None, grid=rounded[0].tolist())
                    else:
                        record['reason'] = 'grid_conflict'
        next_tracks.append({**record, 'history': history})
    return next_tracks


def draw(canvas, records):
    label_boxes = []
    for record in records:
        selected = record['mask']
        color = {'yellow': (0, 220, 255), 'blue': (255, 130, 50),
                 'red': (40, 40, 255)}[record['color']]
        canvas[selected] = (canvas[selected].astype(float)*.65 + np.array(color)*.35).astype(np.uint8)
        contours, _ = cv2.findContours(selected.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 2)
        if 'top_quad' in record:
            cv2.polylines(canvas, [record['top_quad'].astype(np.int32)], True,
                          (255, 255, 0), 2)
        if 'top_mask' in record:
            contours, _ = cv2.findContours(record['top_mask'].astype(np.uint8),
                                          cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(canvas, contours, -1, (255, 255, 0), 1)
        x, y = np.rint(record['pixel_center']).astype(int)
        xy_text = ('(x,y)=' + str(tuple(record['grid'])) + ' TEST'
                   if record['status'] == 'STABLE_CANDIDATE' else '(x,y)=UNKNOWN')
        width = cv2.getTextSize(xy_text, 0, .6, 2)[0][0]
        x = max(2, min(x, canvas.shape[1]-width-4))
        y = max(110, min(y, canvas.shape[0]-8))
        # Move labels, not detections, to avoid text overlap on stacked blocks.
        for candidate_y in range(y, canvas.shape[0]-7, 25):
            box = (x, candidate_y-20, x+width, candidate_y+4)
            if not any(box[0] < old[2] and box[2] > old[0] and
                       box[1] < old[3] and box[3] > old[1] for old in label_boxes):
                y = candidate_y
                break
        label_boxes.append((x, y-20, x+width, y+4))
        cv2.line(canvas, tuple(np.rint(record['pixel_center']).astype(int)),
                 (x, y-10), color, 1)
        cv2.putText(canvas, xy_text, (x, y), 0, .6, (0, 0, 0), 4)
        cv2.putText(canvas, xy_text, (x, y), 0, .6, color, 2)
    return canvas
