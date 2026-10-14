"""Offline supply slot centerline experiment. No ROS or robot interface."""
import cv2
import numpy as np



def detect(image, config):
    height, width = image.shape[:2]
    if [width, height] != config['image_size']:
        raise ValueError('Image size differs from ROI configuration; configure ROIs for this view')
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masks = {}
    for color, ranges in config['hsv_ranges'].items():
        mask = np.zeros((height, width), np.uint8)
        for low, high in ranges:
            mask |= cv2.inRange(hsv, np.array(low, np.uint8), np.array(high, np.uint8))
        masks[color] = mask
    results = []
    for slot in config['slots']:
        x0, y0, x1, y1 = slot['roi_xyxy']
        if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
            raise ValueError('Invalid ROI: ' + slot['id'])
        mask = masks[slot['color']][y0:y1, x0:x1].copy()
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        row = dict(id=slot['id'], slot=slot['slot'], instance=slot['instance'],
                   color=slot['color'], brick_type=slot['brick_type'],
                   kind_source='SLOT_CONFIG_VERIFIED_BY_COLOR_AND_GEOMETRY',
                   roi_xyxy=slot['roi_xyxy'], success=False, reason='NO_VALID_COLOR_CONTOUR',
                   center_uv=None, lines_uv=None, execution_allowed=False)
        candidates = []
        rejected = []
        for contour in contours:
            if cv2.contourArea(contour) < slot['min_area_px']:
                continue
            bx, by, bw, bh = cv2.boundingRect(contour)
            rect = cv2.minAreaRect(contour)
            short, long = sorted(rect[1])
            if short <= 0:
                continue
            reason = None
            if bx <= 0 or by <= 0 or bx+bw >= x1-x0 or by+bh >= y1-y0:
                reason = 'ROI_EDGE_CLIPPED'
            elif not slot['short_side_px'][0] <= short <= slot['short_side_px'][1]:
                reason = 'SIZE_MISMATCH'
            elif not slot['long_side_px'][0] <= long <= slot['long_side_px'][1]:
                reason = 'SIZE_MISMATCH'
            elif not slot['aspect_range'][0] <= long/short <= slot['aspect_range'][1]:
                reason = 'ASPECT_MISMATCH'
            elif cv2.contourArea(contour)/(short*long) < .65:
                reason = 'INCOMPLETE_OR_IRREGULAR_OUTLINE'
            if reason:
                rejected.append(reason)
            else:
                candidates.append((contour, rect, (bx, by, bw, bh)))
        if len(candidates) == 1:
            contour, rect, (bx, by, bw, bh) = candidates[0]
            box = cv2.boxPoints(rect) + np.array([x0, y0])
            center = np.array(rect[0]) + [x0, y0]
            mids = (box + np.roll(box, -1, axis=0))/2
            rotated = [[mids[0].tolist(), mids[2].tolist()], [mids[1].tolist(), mids[3].tolist()]]
            # Continuous pixel coordinates: last included pixel is x+w-1.
            cx, cy = x0+bx+(bw-1)/2, y0+by+(bh-1)/2
            axis = [[[x0+bx, cy], [x0+bx+bw-1, cy]],
                    [[cx, y0+by], [cx, y0+by+bh-1]]]
            row.update(success=True, reason='VISIBLE_OUTLINE_ACCEPTED', center_uv=center.tolist(),
                       axis_center_uv=[cx, cy], bbox_xywh=[x0+bx, y0+by, bw, bh],
                       rotated_box_uv=box.tolist(), lines_uv=dict(screen=axis, block=rotated),
                       contour_uv=(contour.reshape(-1, 2)+[x0, y0]).tolist(),
                       full_body_center_verified=False, metric_alignment_verified=False)
        elif len(candidates) > 1:
            row['reason'] = 'AMBIGUOUS_MULTIPLE_BLOCKS'
        elif rejected:
            row['reason'] = rejected[0]
        results.append(row)
    return results, masks
