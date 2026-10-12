"""Local HSV -> original-RGB crop -> YOLO -> Board diagnostics; no Backend adoption."""
import cv2
import numpy as np

from .opencv_live import color_mask, HSV_RANGES, top_surface_points, corners_at_height, grid_anchor

LIVE_CLASSES = {'yellow_2x2', 'yellow_2x3', 'blue_2x2', 'blue_2x3', 'red_2x1'}


def color_crop(rgb, roi_mask=None):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    masks = {color: color_mask(hsv, color).astype(bool) for color in HSV_RANGES}
    if roi_mask is not None:
        if roi_mask.shape != rgb.shape[:2] or roi_mask.dtype != bool:
            raise ValueError('ROI must match RGB resolution')
        masks = {color: mask & roi_mask for color, mask in masks.items()}
    union = np.logical_or.reduce(list(masks.values()))
    ys, xs = np.nonzero(union)
    if not len(xs):
        return masks, None
    # One padded crop preserves reflections and avoids duplicate predictions in overlapping crops.
    height, width = union.shape
    box = (max(0, int(xs.min())-16), max(0, int(ys.min())-16),
           min(width, int(xs.max())+17), min(height, int(ys.max())+17))
    return masks, box


def measure_instance(rgb, mask, part_class, depth, info, calibration, layer_heights_mm=None,
                     height_tolerance_mm=None):
    from .live_view import board_point
    if calibration is None or depth is None or info is None:
        raise ValueError('calibration_or_synced_depth_missing')
    if depth.dtype != np.uint16 or depth.shape != mask.shape:
        raise ValueError('aligned_depth_format_mismatch')
    v, u = np.nonzero(mask & (depth > 0))
    if len(u) < 50 or len(u)/max(1, mask.sum()) < .8:
        raise ValueError('insufficient_depth')
    board_point((int(u[0]), int(v[0])), depth, info, calibration)
    k = np.asarray(info['k']).reshape(3, 3)
    z = depth[v, u].astype(float)
    camera = np.column_stack(((u-k[0, 2])*z/k[0, 0], (v-k[1, 2])*z/k[1, 1], z))
    pose = calibration['camera_pose']
    board = (camera-np.asarray(pose['t_camera_from_board_mm'])) @ np.asarray(pose['R_camera_from_board'])
    board[:, 2] *= pose['height_normal_sign']
    keep = top_surface_points(board)
    height = float(np.median(board[keep, 2]))
    top = np.zeros(mask.shape, bool)
    top[v[keep], u[keep]] = True
    # Use the YOLO instance boundary, not an HSV component that could join touching bricks.
    from .opencv_live import rgb_top_quad
    quad = rgb_top_quad(rgb, mask, top)
    corners = corners_at_height(quad, height, info, calibration)
    center, sides, angle = cv2.minAreaRect(corners.astype(np.float32))
    size = tuple(sorted(map(int, part_class.split('_')[1].split('x'))))
    pitch = float(calibration['pitch_mm'])
    if np.max(np.abs(np.sort(sides)/pitch-size)) > .35:
        raise ValueError('partial_or_invalid_footprint')
    if sides[0] < sides[1]:
        angle += 90
    period = 90 if size == (2, 2) else 180
    angle %= period
    axis = round(angle/90)*90 % period
    if abs((angle-axis+period/2) % period-period/2) > 10:
        raise ValueError('orientation_off_grid')
    _, anchor = grid_anchor(center, size, axis, pitch)
    result = dict(grid=anchor.tolist(), axis_angle_deg=axis, height_mm=height,
                  layer=None, reason='layer_reference_missing')
    if layer_heights_mm is not None:
        levels = np.asarray(layer_heights_mm, float)
        if (levels.shape not in ((4,), (5,)) or not np.isfinite(levels).all() or
                np.any(np.diff(levels) <= 0) or height_tolerance_mm is None or
                not np.isfinite(height_tolerance_mm) or height_tolerance_mm <= 0 or
                2*height_tolerance_mm >= np.min(np.diff(levels))):
            raise ValueError('invalid_or_overlapping_layer_reference')
        index = int(np.argmin(abs(levels-height)))
        if abs(levels[index]-height) <= height_tolerance_mm:
            result.update(layer=index+1, reason=None)
        else:
            result['reason'] = 'height_outside_layer_reference'
    return result


def process_frame(rgb, model, confidence, depth=None, info=None, calibration=None,
                  layer_heights_mm=None, height_tolerance_mm=None, *, roi_mask=None):
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('uint8 RGB required')
    if not np.isfinite(confidence) or not 0 < confidence <= 1:
        raise ValueError('explicit confidence in (0,1] required')
    colors, box = color_crop(rgb, roi_mask)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    crop = rgb[y0:y1, x0:x1]
    result = model.predict(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR), conf=confidence,
                           retina_masks=True, device='cpu', verbose=False)[0]
    if result.boxes is None:
        raise ValueError('missing_segmentation_boxes')
    if not len(result.boxes):
        return []
    if result.masks is None or len(result.masks.data) != len(result.boxes):
        raise ValueError('missing_instance_masks')
    masks = result.masks.data.cpu().numpy() > .5
    if masks.shape[1:] != crop.shape[:2]:
        raise ValueError('mask_resolution_mismatch')
    records = []
    for small, cls, score in zip(masks, result.boxes.cls.cpu().numpy(), result.boxes.conf.cpu().numpy()):
        name = model.names[int(cls)]
        if name not in LIVE_CLASSES:
            raise ValueError('unsupported_live_class')
        mask = np.zeros(rgb.shape[:2], bool)
        mask[y0:y1, x0:x1] = small
        if not mask.any():
            raise ValueError('empty_instance_mask')
        boundary = False
        if roi_mask is not None:
            if not np.any(mask & roi_mask):
                continue
            boundary = bool(np.any(mask & ~roi_mask))
            mask &= roi_mask
        votes = {color: int(np.count_nonzero(mask & candidate)) for color, candidate in colors.items()}
        winners = [color for color, count in votes.items() if count == max(votes.values()) and count > 0]
        color = winners[0] if len(winners) == 1 else 'UNKNOWN'
        record = dict(mask=mask, part_class=name, color=color, confidence=float(score),
                      reason='color_missing_or_conflict', layer=None)
        if boundary:
            record['reason'] = 'instance_crosses_roi_boundary'
        elif color == name.split('_')[0]:
            try:
                record.update(measure_instance(rgb, mask, name, depth, info, calibration,
                                              layer_heights_mm, height_tolerance_mm))
            except (ValueError, KeyError, cv2.error) as error:
                record['reason'] = str(error)
        records.append(record)
    return records


def draw_integrated(canvas, records, *, show_height=False):
    for record in records:
        mask = record['mask']
        tint = np.array((80, 220, 80) if record['reason'] is None else (0, 180, 255))
        canvas[mask] = (.7*canvas[mask]+.3*tint).astype(np.uint8)
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, tuple(map(int, tint)), 1)
        ys, xs = np.nonzero(mask)
        if not xs.size:
            continue
        # OpenCV's built-in font is ASCII-only; keep diagnostics in records,
        # not in the per-block display. Unknown values must remain explicit.
        kind = record['part_class'].replace('_', ' ')
        if record['reason'] == 'color_missing_or_conflict':
            kind = 'color? ' + record['part_class'].split('_', 1)[1]
        grid = record.get('grid')
        xy = f"({grid[0]}, {grid[1]})" if grid is not None else 'XY:?'
        layer = f"L{record['layer']}" if record.get('layer') is not None else 'L:?'
        line = f'{kind} | {xy} | {layer}'
        if show_height and record.get('height_mm') is not None:
            line += f" | H:{record['height_mm']:.1f}mm"
        (width, height), baseline = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, .4, 1)
        x = max(0, min(int(xs.min()), canvas.shape[1]-width-4))
        y = min(canvas.shape[0]-baseline-2, int(ys.max())+height+6)
        if y-height <= int(ys.max()):
            y = max(height+2, int(ys.min())-6)
        cv2.putText(canvas, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .4, (255,255,255), 1)
    return canvas
