"""V0 hand-cycle gate. This is not a robot safety interlock or completion detector."""
import math
import time
import json
from pathlib import Path

import cv2
import numpy as np


def load_hand_model(weights):
    if not isinstance(weights, (str, Path)) or not Path(weights).is_file():
        raise FileNotFoundError("separate local hand detector weights required")
    from ultralytics import YOLO
    model = YOLO(str(weights))
    if model.task != "detect" or "hand" not in model.names.values():
        raise ValueError("separate detect model with explicit hand class required")
    return model


def live_hand_components(view, settings):
    """Only stopped V0 uses a hand model; diagonal Views must not load one."""
    if view != 'V0':
        return None, None
    missing = [key for key in ('weights', 'confidence', 'board_roi_v0',
        'min_valid_depth_fraction', 'stable_mean_difference', 'stable_seconds',
        'max_frame_gap_seconds', 'exit_seconds') if settings.get(key) is None]
    if missing:
        raise ValueError('hand settings missing: '+', '.join(missing))
    if settings['exit_seconds'] != 3.0:
        raise ValueError('hand exit must be strictly greater than 3 seconds')
    detector = HandDetector(settings['weights'], settings['confidence'], settings['board_roi_v0'],
        min_valid_depth_fraction=settings['min_valid_depth_fraction'],
        stable_mean_difference=settings['stable_mean_difference'],
        image_size=settings.get('board_image_size'), board_polygon=settings.get('board_polygon_v0'))
    return detector, HandCycle(settings['stable_seconds'], settings['max_frame_gap_seconds'])


def live_hand_event(view, detector, gate, rgb, depth, timestamp, *, usable):
    if view != 'V0':
        return dict(state='DISABLED', presence='NOT_RUN', observation_allowed=False,
                    absent_seconds=0., stable=False, reason='hand_detection_V0_only')
    if detector is None or gate is None:
        return dict(state='HOLD', presence='UNKNOWN', observation_allowed=False,
                    absent_seconds=0., stable=False, reason='hand_configuration_unavailable')
    if usable:
        try:
            presence, stable, quality = detector.detect(rgb, depth)
        except (ValueError, RuntimeError, cv2.error) as error:
            presence, stable, quality = 'UNKNOWN', False, {'reason': str(error)}
    else:
        presence, stable, quality = 'UNKNOWN', False, {'reason': 'stop_or_fresh_synced_frame_missing'}
    event = gate.update(presence, stable, timestamp)
    event.update(presence=presence, stable=stable, quality=quality,
                 absent_seconds=0. if gate.absent_since is None else timestamp-gate.absent_since)
    return event


def monitor_hand(stream, detector, gate, output, context, *, frame_sink=None):
    """Actual live stream consumer shared by local and Backend-context entry points."""
    previous = None
    with Path(output).open("x", encoding="utf-8") as log:
        try:
            for rgb, depth, timestamp in stream:
                presence, stable, quality = detector.detect(rgb, depth)
                event = gate.update(presence, stable, timestamp)
                if frame_sink is not None:
                    frame_sink(rgb, depth, dict(event), dict(quality))
                if event["state"] != previous:
                    event.update(context)
                    event.update(view_id="V0", hand_quality=quality)
                    encoded = json.dumps(event, ensure_ascii=False, allow_nan=False)
                    log.write(encoded + "\n")
                    log.flush()
                    print(encoded, flush=True)
                    previous = event["state"]
        finally:
            stream.close()
            log.write(json.dumps(dict(context, state="HOLD",
                reason="monitor_stopped_no_live_observation_permission")) + "\n")


def wait_for_hand_ready(stream, detector, gate, workflow_valid, *, frame_sink=None):
    """Consume actual stopped-V0 frames for the recheck hook; not a safety detector."""
    try:
        for rgb, depth, timestamp in stream:
            if workflow_valid() is not True:
                raise RuntimeError("hand wait interrupted by STOP/fault/other hold")
            presence, stable, quality = detector.detect(rgb, depth)
            event = gate.update(presence, stable, timestamp)
            if frame_sink is not None:
                frame_sink(rgb, depth, dict(event), dict(quality))
            if workflow_valid() is not True:
                raise RuntimeError("hand wait interrupted by STOP/fault/other hold")
            if event["observation_allowed"]:
                return True
        raise RuntimeError("V0 stream ended before hand exit and stability confirmation")
    except Exception:
        gate.state = "HOLD"
        raise
    finally:
        stream.close()


class HandCycle:
    def __init__(self, stable_seconds, max_frame_gap_seconds):
        if not all(math.isfinite(x) and x > 0 for x in (stable_seconds, max_frame_gap_seconds)):
            raise ValueError("measured positive stability and frame-gap thresholds required")
        self.stable_seconds = stable_seconds
        self.max_gap = max_frame_gap_seconds
        self.state = "WAIT_ENTRY"
        self.last_time = None
        self.absent_since = None
        self.stable_since = None
        self.entry_seen = False

    def update(self, hand, stable, timestamp):
        if hand not in ("PRESENT", "ABSENT", "UNKNOWN") or type(stable) is not bool:
            raise ValueError("hand state and explicit stability evidence required")
        if not math.isfinite(timestamp) or (self.last_time is not None and timestamp <= self.last_time):
            raise ValueError("strictly increasing monotonic frame time required")
        gap = self.last_time is not None and timestamp - self.last_time > self.max_gap
        self.last_time = timestamp
        if hand == "PRESENT":
            interrupted = self.state in ("READY", "OBSERVING")
            self.entry_seen = True
            self.absent_since = self.stable_since = None
            self.state = "HAND_PRESENT"
            reason = "hand_reentry_observation_invalidated" if interrupted else "hand_entry_confirmed"
        elif hand == "UNKNOWN" or gap:
            self.absent_since = self.stable_since = None
            self.state = "HOLD" if self.entry_seen else "WAIT_ENTRY"
            reason = "hand_unknown_or_frame_gap"
        elif not self.entry_seen:
            self.state = "WAIT_ENTRY"
            reason = "hand_entry_not_confirmed"
        else:
            if self.absent_since is None:
                self.absent_since = timestamp
            if stable:
                if self.stable_since is None:
                    self.stable_since = timestamp
            else:
                self.stable_since = None
            ready = (timestamp - self.absent_since > 3.0 and self.stable_since is not None and
                     timestamp - self.stable_since >= self.stable_seconds)
            if self.state != "OBSERVING":
                self.state = "READY" if ready else "WAIT_EXIT_STABLE"
            elif not ready:
                self.state = "HOLD"
            reason = "observation_allowed_not_step_complete" if ready else "exit_or_stability_pending"
        return {"state": self.state, "observation_allowed": self.state == "READY",
                "reason": reason, "monotonic_time": timestamp,
                "exit_seconds_required_strictly_greater_than": 3.0}

    def begin_observation(self):
        if (self.state != "READY" or self.last_time is None or
                time.monotonic() - self.last_time > self.max_gap):
            raise RuntimeError("hand exit and stability not confirmed")
        self.state = "OBSERVING"

    def reset_for_reobservation(self):
        """Call only after external confirmation of a safe stopped V0."""
        self.state = "WAIT_ENTRY"
        self.last_time = None
        self.entry_seen = False
        self.absent_since = self.stable_since = None

    def finish_observation(self):
        if (self.state != "OBSERVING" or self.last_time is None or
                time.monotonic() - self.last_time > self.max_gap):
            raise RuntimeError("observation interrupted; do not finalize this bundle")
        self.state = "WAIT_ENTRY"
        self.entry_seen = False
        self.absent_since = self.stable_since = None


def validate_polygon(points):
    """Accept simple convex/concave pixel polygons; reject touching/crossing edges."""
    polygon = np.asarray(points)
    if (polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3 or
            not np.issubdtype(polygon.dtype, np.integer)):
        raise ValueError('At least three integer polygon corners required')
    polygon = polygon.astype(np.int32)
    if len(set(map(tuple, polygon.tolist()))) != len(polygon):
        raise ValueError('Repeated corners: do not click the first corner again')
    def cross(a, b, c):
        ax, ay = map(int, a)
        bx, by = map(int, b)
        cx, cy = map(int, c)
        return (bx-ax)*(cy-ay) - (by-ay)*(cx-ax)
    def on_segment(a, b, c):
        return (min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and
                min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))
    count = len(polygon)
    for i in range(count):
        a, b = polygon[i], polygon[(i+1) % count]
        c = polygon[(i+2) % count]
        if cross(a, b, c) == 0 and (on_segment(a, b, c) or on_segment(b, c, a)):
            raise ValueError('Polygon edges overlap')
        for j in range(i+1, count):
            if j == i+1 or (i == 0 and j == count-1):
                continue
            c, d = polygon[j], polygon[(j+1) % count]
            ab_c, ab_d, cd_a, cd_b = cross(a,b,c), cross(a,b,d), cross(c,d,a), cross(c,d,b)
            if ((ab_c*ab_d < 0 and cd_a*cd_b < 0) or
                    (ab_c == 0 and on_segment(a,b,c)) or (ab_d == 0 and on_segment(a,b,d)) or
                    (cd_a == 0 and on_segment(c,d,a)) or (cd_b == 0 and on_segment(c,d,b))):
                raise ValueError('Polygon edges cross/touch; click corners in perimeter order')
    if cv2.contourArea(polygon) <= 0:
        raise ValueError('Polygon must enclose an area')
    return polygon


class HandDetector:
    def __init__(self, weights, confidence, board_roi, *, min_valid_depth_fraction,
                 stable_mean_difference, image_size=None, board_polygon=None):
        if not isinstance(weights, (str, Path)) or not Path(weights).is_file():
            raise FileNotFoundError("separate local hand detector weights required")
        if (not math.isfinite(confidence) or not 0 < confidence <= 1 or
                not math.isfinite(min_valid_depth_fraction) or not 0 < min_valid_depth_fraction <= 1 or
                not math.isfinite(stable_mean_difference) or stable_mean_difference <= 0):
            raise ValueError("measured hand/quality/stability settings required")
        if (len(board_roi) != 4 or any(type(v) is not int for v in board_roi) or
                not 0 <= board_roi[0] < board_roi[2] or not 0 <= board_roi[1] < board_roi[3]):
            raise ValueError("V0 board ROI [left,top,right,bottom] required")
        self.model = load_hand_model(weights)
        self.confidence, self.roi = confidence, board_roi
        self.min_depth = min_valid_depth_fraction
        self.max_difference = stable_mean_difference
        if image_size is not None and (len(image_size) != 2 or
                any(type(v) is not int or v <= 0 for v in image_size)):
            raise ValueError('ROI image size must be positive width/height')
        self.image_size = image_size
        self.polygon = None
        if board_polygon is not None:
            polygon = validate_polygon(board_polygon)
            if ((polygon[:, 0] < board_roi[0]).any() or (polygon[:, 0] >= board_roi[2]).any() or
                    (polygon[:, 1] < board_roi[1]).any() or (polygon[:, 1] >= board_roi[3]).any()):
                raise ValueError('Polygon must fit V0 bounding ROI')
            self.polygon = polygon
        self.previous = None

    def reset(self):
        # Do not compare a newly returned V0 image with stale pre-correction RGB.
        self.previous = None

    def detect(self, rgb, depth):
        if (rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or
                depth.dtype != np.uint16 or depth.shape != rgb.shape[:2]):
            raise ValueError("original RGB and aligned uint16 Depth required")
        x0, y0, x1, y1 = self.roi
        if self.image_size is not None and list(self.image_size) != [rgb.shape[1], rgb.shape[0]]:
            raise ValueError('RGB resolution differs from saved V0 ROI')
        if x1 > rgb.shape[1] or y1 > rgb.shape[0]:
            raise ValueError("V0 board ROI outside image")
        crop = rgb[y0:y1, x0:x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        area = np.ones(gray.shape, dtype=np.uint8)
        if getattr(self, 'polygon', None) is not None:
            area[:] = 0
            cv2.fillPoly(area, [self.polygon - np.array([x0, y0], np.int32)], 1)
        selected = area.astype(bool)
        gray = gray[selected]
        usable = np.count_nonzero(depth[y0:y1, x0:x1][selected]) / gray.size >= self.min_depth
        difference = None if self.previous is None else float(np.mean(
            np.abs(gray.astype(float) - self.previous.astype(float))))
        self.previous = gray.copy() if usable else None
        if not usable:
            return "UNKNOWN", False, {"reason": "insufficient_roi_depth"}
        result = self.model.predict(rgb[:, :, ::-1].copy(), conf=self.confidence,
                                    verbose=False, device="cpu")[0]
        if result.boxes is None:
            raise RuntimeError("hand detector returned no box structure")
        present = False
        for box, cls in zip(result.boxes.xyxy.cpu().numpy(), result.boxes.cls.cpu().numpy()):
            left, top, right, bottom = box
            if (self.model.names[int(cls)] == "hand" and left < x1 and right > x0 and
                    top < y1 and bottom > y0):
                if getattr(self, 'polygon', None) is None:
                    present = True
                elif right > left and bottom > top:
                    # Use the same raster area as Depth/stability, including concave exclusions.
                    bx0, by0 = max(x0, int(np.ceil(left))), max(y0, int(np.ceil(top)))
                    bx1, by1 = min(x1, int(np.ceil(right))), min(y1, int(np.ceil(bottom)))
                    present = present or bool(np.any(area[by0-y0:by1-y0, bx0-x0:bx1-x0]))
        stable = difference is not None and difference <= self.max_difference
        return ("PRESENT" if present else "ABSENT"), stable, {
            "roi_mean_difference": difference, "basis": "separate_hand_model_and_roi_depth",
            "limitation": "missed_detections_require_real_validation_not_safety_proof"}
