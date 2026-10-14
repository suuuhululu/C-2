"""RealSense RGB-only supply diagnostics; no robot commands or Depth."""
import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np

CLASSES = ('yellow_2x2', 'yellow_2x3', 'blue_2x2', 'blue_2x3', 'red_2x1')


CLASS_BY_BLOCK = {
    ('yellow', '2x2x1'): 'yellow_2x2', ('yellow', '2x3x1'): 'yellow_2x3',
    ('blue', '2x2x1'): 'blue_2x2', ('blue', '2x3x1'): 'blue_2x3',
    ('red', '1x2x1'): 'red_2x1',
}


def block_class(color, brick_type):
    try:
        return CLASS_BY_BLOCK[(color, brick_type)]
    except KeyError:
        raise ValueError('unsupported D block type/color') from None


def slot_id(entry):
    return f"{entry['color']}_{entry['brick_type']}_{entry['slot']:02d}"


def intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def validate_layout(layout):
    width, height = layout['image_size']
    if any(type(n) is not int or n <= 0 for n in (width, height)):
        raise ValueError('image_size requires measured positive integer dimensions')
    if not layout['slots']:
        raise ValueError('measured slots required')
    identities = set()
    for entry in layout['slots']:
        identity = (entry['brick_type'], entry['color'], entry['slot'])
        if (block_class(entry['color'], entry['brick_type']) not in CLASSES
                or type(entry['slot']) is not int or not 1 <= entry['slot'] <= 6
                or identity in identities):
            raise ValueError('unique supported brick_type/color/slot required')
        identities.add(identity)
        box = entry['roi_xyxy']
        if (len(box) != 4 or any(type(n) is not int for n in box)
                or not 0 <= box[0] < box[2] <= width
                or not 0 <= box[1] < box[3] <= height):
            raise ValueError('invalid measured ROI')
        if entry['grasp_edge_pair'] not in (0, 1):
            raise ValueError('grasp_edge_pair requires 0 or 1')
    for i, a in enumerate(layout['slots']):
        if any(intersects(a['roi_xyxy'], b['roi_xyxy']) for b in layout['slots'][i+1:]):
            raise ValueError('overlapping slot ROIs')
    return layout


def assign_slots(layout, detections, confidence):
    validate_layout(layout)
    if not np.isfinite(confidence) or not 0 < confidence <= 1:
        raise ValueError('invalid confidence')
    for d in detections:
        b = d['box']
        if (len(b) != 4 or not np.isfinite(b).all() or not b[0] < b[2] or not b[1] < b[3]
                or not np.isfinite(d['confidence']) or not 0 <= d['confidence'] <= 1
                or d['class_name'] not in CLASSES):
            raise ValueError('invalid detection')
    states = []
    for entry in layout['slots']:
        roi = entry['roi_xyxy']
        hits = [d for d in detections if intersects(roi, d['box'])]
        state = {k: entry[k] for k in ('brick_type', 'color', 'slot')}
        state.update(slot_id=slot_id(entry), status='UNKNOWN', confidence=None, reason='no_detection', geometry=None)
        if len(hits) > 1:
            state['reason'] = 'multiple_detections'
        elif hits:
            hit = hits[0]
            x1, y1, x2, y2 = hit['box']
            expected = block_class(entry['color'], entry['brick_type'])
            if not (roi[0] <= x1 < x2 <= roi[2] and roi[1] <= y1 < y2 <= roi[3]):
                state['reason'] = 'detection_crosses_slot'
            elif hit['confidence'] < confidence:
                state['reason'] = 'low_confidence'
            elif hit.get('color_mismatch', False):
                state['reason'] = 'opencv_yolo_color_mismatch'
            elif hit['class_name'] != expected:
                state['reason'] = 'unexpected_class'
            else:
                state.update(status='DETECTED', confidence=hit['confidence'], reason=None,
                             box=hit['box'], mask_contours_uv=hit.get('mask_contours_uv', []),
                             mask_clipped=hit.get('mask_clipped', False))
        states.append(state)
    return states


def load_model(weights):
    path = Path(weights)
    if not path.is_file() or path.suffix != '.pt':
        raise ValueError('local trained segmentation .pt required; no auto-download')
    from ultralytics import YOLO
    model = YOLO(str(path))
    if model.task != 'segment':
        raise ValueError('segmentation model required; detection/OBB rejected')
    if len(model.names) != len(CLASSES) or set(model.names.values()) != set(CLASSES):
        raise ValueError(f'model classes must match {CLASSES}')
    return model


def resolve_weights(config, config_path, override=None):
    """Model path from config (relative paths start at the config file); --weights overrides."""
    if override is not None:
        return Path(override)
    value = config.get('weights')
    if not isinstance(value, str) or not value:
        raise ValueError('segmentation weights required: set config "weights" or pass --weights')
    path = Path(value)
    return path if path.is_absolute() else (Path(config_path).parent / path).resolve()


def infer(model, frame, candidate_confidence):
    result = model.predict(frame, conf=candidate_confidence, device='cpu',
                           retina_masks=True, verbose=False)[0]
    if result.boxes is None:
        raise RuntimeError('missing segmentation boxes')
    boxes = result.boxes.xyxy.cpu().numpy()
    if len(boxes) == 0:
        return []
    if result.masks is None:
        raise RuntimeError('missing segmentation masks')
    masks = result.masks.data.cpu().numpy()
    classes = result.boxes.cls.cpu().numpy()
    scores = result.boxes.conf.cpu().numpy()
    if (len(masks) != len(boxes) or len(classes) != len(boxes)
            or len(scores) != len(boxes) or masks.shape[1:] != frame.shape[:2]):
        raise RuntimeError('segmentation mask/box dimensions mismatch')
    detections = []
    for box, cls, score, mask in zip(boxes, classes, scores, masks):
        binary = (mask > .5).astype(np.uint8)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        clipped = bool(binary[0].any() or binary[-1].any()
                       or binary[:, 0].any() or binary[:, -1].any())
        detections.append({'box': box.tolist(), 'class_name': model.names[int(cls)],
                           'confidence': float(score), 'mask_clipped': clipped,
                           'mask_contours_uv': [c.reshape(-1, 2).tolist() for c in contours]})
    return detections


def color_candidates(frame, config):
    """HSV proposes crops only; it never assigns a YOLO block class."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    candidates = []
    for entry in config['slots']:
        x1, y1, x2, y2 = entry['roi_xyxy']
        for color, bands in config['surface']['hsv_ranges'].items():
            mask = np.zeros((y2-y1, x2-x1), np.uint8)
            for lower, upper in bands:
                mask |= cv2.inRange(hsv[y1:y2, x1:x2], np.array(lower, np.uint8),
                                    np.array(upper, np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if cv2.contourArea(contour) < config['surface']['minimum_area']:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                # Original RGB with context; no mask/labels painted into model input.
                candidates.append({'color': color, 'crop_xyxy': [
                    max(x1, x1+x-3), max(y1, y1+y-3),
                    min(x2, x1+x+w+3), min(y2, y1+y+h+3)]})
    return candidates


def infer_color_candidates(model, frame, config):
    candidates = color_candidates(frame, config)
    if not candidates:
        return []
    detections = []
    # Training used full board images. Preserve that scale/context after HSV gating.
    for detection in infer(model, frame, config['candidate_confidence']):
        colors = {c['color'] for c in candidates if intersects(c['crop_xyxy'], detection['box'])}
        if not colors:
            continue
        expected_color = detection['class_name'].split('_')[0]
        detections.append({**detection, 'opencv_color': expected_color if colors == {expected_color} else None,
                           'color_mismatch': colors != {expected_color}})
    return detections


def process(frame, model, config, request, stamp_ns):
    from .seg_geometry import geometry_from_mask
    if list(frame.shape[1::-1]) != config['image_size']:
        raise ValueError('frame resolution differs from slot configuration')
    if (request['view_id'] != config['view_id']
            or request['config_id'] != config['config_id'] or request['stopped'] is not True):
        raise ValueError('observation/config mismatch or stop not confirmed')
    if not request['not_before_ns'] < stamp_ns <= request['expires_at_ns']:
        raise ValueError('frame outside active request time window')
    requested_slots = [entry for entry in config['slots']
                       if slot_id(entry) == request['slot_id']
                       and (entry['brick_type'], entry['color']) ==
                           (request['brick_type'], request['color'])]
    if len(requested_slots) != 1:
        raise ValueError('reserved slot_id must match configured D block/slot')
    target_config = {**config, 'slots': requested_slots}
    detections = infer_color_candidates(model, frame, target_config)
    states = assign_slots(target_config, detections, config['confidence'])
    for state, entry in zip(states, requested_slots):
        if state['status'] == 'DETECTED':
            try:
                state['geometry'] = geometry_from_mask(state['mask_contours_uv'],
                    block_class(state['color'], state['brick_type']), entry['grasp_edge_pair'],
                    config['surface'], state['mask_clipped'])
                state.update(status='CENTER_CANDIDATE')
            except ValueError as error:
                state.update(slot_id=slot_id(entry), status='UNKNOWN', reason=str(error))
    target = (request['brick_type'], request['color'])
    matches = [s for s in states if (s['brick_type'], s['color']) == target
               and s['slot_id'] == request['slot_id'] and s['status'] == 'CENTER_CANDIDATE']
    return {'scope': 'LOCAL_ONLY', 'request_id': request['request_id'], 'step_id': request['step_id'],
            'view_id': config['view_id'], 'slot_id': request['slot_id'], 'config_id': config['config_id'],
            'calibration_id': config['calibration_id'], 'frame_stamp_ns': stamp_ns,
            'coordinate_frame': 'rgb_image', 'units': 'pixel',
            'status': 'CANDIDATES' if matches else 'HOLD', 'slots': states, 'candidates': matches}


def validate_config(config, request):
    validate_layout(config)
    from .top_surface import validate_surface
    validate_surface(config['surface'])
    for key in ('config_id', 'view_id', 'calibration_id', 'rgb_topic'):
        if not isinstance(config[key], str) or not config[key]:
            raise ValueError(f'{key} must be supplied')
    if config['view_id'] != 'SUPPLY_VIEW' or request.get('view_id') != 'SUPPLY_VIEW':
        raise ValueError('view_id must be SUPPLY_VIEW')
    if not 0 < config['candidate_confidence'] <= config['confidence'] <= 1:
        raise ValueError('explicit candidate/confidence thresholds required')
    for key in ('request_id', 'step_id'):
        if not isinstance(request[key], str) or not request[key]:
            raise ValueError(f'{key} required')
    if block_class(request['color'], request['brick_type']) not in CLASSES:
        raise ValueError('unsupported requested block')
    requested_slots = [entry for entry in config['slots']
                       if slot_id(entry) == request.get('slot_id')
                       and (entry['brick_type'], entry['color']) ==
                           (request['brick_type'], request['color'])]
    if len(requested_slots) != 1:
        raise ValueError('reserved slot_id must match configured D block/slot')
    for key in ('not_before_ns', 'expires_at_ns'):
        if type(request[key]) is not int or request[key] < 0:
            raise ValueError('request timestamps require ROS integer nanoseconds')
    if request['not_before_ns'] >= request['expires_at_ns']:
        raise ValueError('invalid request window')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--request', required=True, help='local draft request JSON; not a Service server')
    parser.add_argument('--weights', help='override config "weights" (local segmentation .pt)')
    parser.add_argument('--output', required=True, help='new result JSON; no overwrite')
    parser.add_argument('--timeout', required=True, type=float)
    args = parser.parse_args(argv)
    if not np.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('positive timeout required')
    if Path(args.output).exists():
        parser.error('output already exists')
    config = json.loads(Path(args.config).read_text())
    request = json.loads(Path(args.request).read_text())
    validate_config(config, request)
    model = load_model(resolve_weights(config, args.config, args.weights))
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    rclpy.init()
    node = rclpy.create_node('supply_rgb_center_diagnostic')
    packet = []

    def receive(msg):
        stamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
        if not request['not_before_ns'] < stamp <= request['expires_at_ns']:
            return
        if msg.encoding not in ('rgb8', 'bgr8'):
            raise ValueError('RGB8/BGR8 required')
        rows = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.step)
        frame = rows[:, :msg.width*3].reshape(msg.height, msg.width, 3).copy()
        if msg.encoding == 'rgb8':
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        packet[:] = [(frame, stamp)]

    subscription = node.create_subscription(Image, config['rgb_topic'], receive, qos_profile_sensor_data)
    try:
        from .request_session import SupplyRequestSession
        session = SupplyRequestSession(model, config, lambda: node.get_clock().now().nanoseconds)
        session.submit(request)
        deadline = time.monotonic() + args.timeout
        while not packet and time.monotonic() < deadline and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=.05)
        if not packet:
            raise RuntimeError('no post-request RGB frame before timeout')
        frame, stamp = packet[0]
        result = session.observe(request['request_id'], frame, stamp)
        if node.get_clock().now().nanoseconds > request['expires_at_ns']:
            raise RuntimeError('request expired during inference')
        with Path(args.output).open('x') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
        canvas = frame.copy()
        for state in result['candidates']:
            geometry = state['geometry']
            cv2.polylines(canvas, [np.int32(geometry['corners_uv'])], True, (0,255,0), 2)
            points = np.rint(geometry['corners_uv']).astype(int)
            cv2.line(canvas, tuple(points[0]), tuple(points[2]), (255,255,255), 1)
            cv2.line(canvas, tuple(points[1]), tuple(points[3]), (255,255,255), 1)
            for point in geometry['grasp_midpoints_uv'] + [geometry['center_uv']]:
                cv2.circle(canvas, tuple(np.rint(point).astype(int)), 4, (0,0,255), -1)
        cv2.namedWindow('Supply RGB Centers', cv2.WINDOW_AUTOSIZE)
        cv2.imshow('Supply RGB Centers', canvas)
        cv2.waitKey(0)
    finally:
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
