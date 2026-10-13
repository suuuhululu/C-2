"""Unvalidated landmark shape and temporal diagnostics; never control evidence."""
import math

from app.handover_gesture import GestureGate


def angle(a, b, c):
    u, v = [x-y for x, y in zip(a, b)], [x-y for x, y in zip(c, b)]
    length = math.sqrt(sum(x*x for x in u)*sum(x*x for x in v))
    if length < 1e-12:
        raise ValueError("degenerate landmark segment")
    return math.degrees(math.acos(max(-1, min(1, sum(x*y for x, y in zip(u, v))/length))))


def shape_preview(landmarks, width, height):
    """Pixel-scaled model xyz angles. Thresholds are prototype hypotheses only.

    Thumb extension with four folded fingers is a thumbs-up shape candidate;
    this does not prove the thumb's direction in the physical world.
    """
    result = dict(pose="UNKNOWN", fingers=[], center=None, palm_size=None,
                  pose_verified=False, orientation_verified=False, surface="unknown")
    if len(landmarks) != 21 or min(width, height) <= 0:
        return result
    p = [[v["x"]*width, v["y"]*height, v["z"]*width] for v in landmarks]
    if any(not math.isfinite(n) for point in p for n in point):
        return result
    size = math.dist(p[5], p[17])
    if size < 10:
        return result
    states = []
    try:
        for base, pip, dip, tip in ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20)):
            bend = min(angle(p[base], p[pip], p[dip]), angle(p[pip], p[dip], p[tip]))
            extended = bend >= 155 and math.dist(p[tip], p[0]) > math.dist(p[pip], p[0])
            if tip == 4:
                extended = extended and math.dist(p[4], p[5]) > .6*size
            folded = bend <= 110 or math.dist(p[tip], p[0]) < .85*math.dist(p[pip], p[0])
            states.append("EXTENDED" if extended else "FOLDED" if folded else "UNKNOWN")
    except ValueError:
        return result
    patterns = {
        ("EXTENDED", "FOLDED", "FOLDED", "FOLDED", "FOLDED"): "THUMBS_UP",
        ("EXTENDED", "EXTENDED", "FOLDED", "FOLDED", "FOLDED"): "L",
        ("FOLDED",)*5: "FIST",
        ("EXTENDED",)*5: "OPEN_HAND",
    }
    pose = patterns.get(tuple(states), "UNKNOWN")
    if pose == "L":
        # Two extended adjacent fingers also form other shapes; require an L angle.
        opening = angle(p[4], p[5], p[8])
        if not 45 <= opening <= 135:
            pose = "UNKNOWN"
    center = [sum(p[k][i] for k in (0, 5, 9, 13, 17))/5 for i in (0, 1)]
    result.update(pose=pose, fingers=states, center=center, palm_size=size)
    return result


class PosePreview:
    """Continuity estimate, not verified identity; separate from GestureGate.

    Time is callback receipt monotonic time, not a verified camera capture clock.
    A quick unseen hand substitution cannot be ruled out by spatial continuity.
    """
    def __init__(self, open_hold_ns=GestureGate.HOLD_NS, question_hold_ns=GestureGate.HOLD_NS):
        if type(open_hold_ns) is not int or not 400_000_000 <= open_hold_ns <= 5_000_000_000:
            raise ValueError("open hold must be 0.4..5 seconds")
        self.open_hold_ns = open_hold_ns
        if type(question_hold_ns) is not int or not 400_000_000<=question_hold_ns<=5_000_000_000:
            raise ValueError('question hold must be 0.4..5 seconds')
        self.question_hold_ns = question_hold_ns
        self.context = None
        self.previous = None
        self.last_stamp = None
        self.emitted = False

    def evaluate(self, hands, received_ns, source_ns, frame, context):
        if context != self.context:
            self.context, self.previous, self.last_stamp, self.emitted = context, None, None, False
        result = dict(candidate_event=None, held_ns=0, continuity_estimate=False,
                      event=None, real_output_enabled=False, reason=None)

        def reject(reason):
            self.previous = None
            result["reason"] = reason
            return result

        if not context or context[0] == "INACTIVE":
            return reject("INACTIVE")
        if not frame or source_ns <= 0 or (self.last_stamp is not None and source_ns <= self.last_stamp):
            return reject("OLD_OR_INVALID_SOURCE")
        self.last_stamp = source_ns
        if (not isinstance(hands, list) or len(hands) != 1
                or not isinstance(hands[0], dict) or hands[0].get("pose", "UNKNOWN") == "UNKNOWN"):
            return reject("SINGLE_KNOWN_SHAPE_REQUIRED")
        h, prev = hands[0], self.previous
        center, size = h.get("center"), h.get("palm_size")
        # NaN comparisons can silently pass the spatial continuity checks below.
        if (not isinstance(center, (list, tuple)) or len(center) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*center, size))
                or size <= 0):
            return reject("INVALID_HAND_GEOMETRY")
        current = dict(t=received_ns, start=received_ns, frame=frame, pose=h["pose"],
                       center=center, size=size)
        if prev and (frame != prev["frame"] or not 0 < received_ns-prev["t"] <= 300_000_000
                     or math.dist(current["center"], prev["center"]) > .5*min(current["size"], prev["size"])
                     or not .7 <= current["size"]/prev["size"] <= 1.4):
            prev = None
        result["continuity_estimate"] = prev is not None
        candidate = None
        if context[0] == "QUESTION" and h["pose"] in ("THUMBS_UP", "L"):
            if prev and prev["pose"] == h["pose"]:
                current["start"] = prev["start"]
            result["held_ns"] = received_ns-current["start"]
            if result["held_ns"] >= self.question_hold_ns:
                candidate = "THUMBS_UP_HELD" if h["pose"] == "THUMBS_UP" else "L_HELD_ORIENTATION_UNKNOWN"
        elif context[0] == "OPEN_GRIPPER" and h["pose"] == "OPEN_HAND":
            if prev and prev["pose"] == "OPEN_HAND":
                current["start"] = prev["start"]
            result["held_ns"] = received_ns-current["start"]
            if result["held_ns"] >= self.open_hold_ns:
                candidate = "OPEN_HAND_HELD_ORIENTATION_UNKNOWN"
        elif context[0] == "RECEIVE" and h["pose"] in ("FIST", "OPEN_HAND"):
            if prev and prev["pose"] == "FIST" and h["pose"] == "OPEN_HAND":
                candidate = "FIST_TO_OPEN_ORIENTATION_UNKNOWN"
        else:
            return reject("SHAPE_OUTSIDE_MODE")
        self.previous = current
        if candidate and not self.emitted:
            result["candidate_event"] = candidate
            self.emitted = True
        result["reason"] = "PREVIEW_ONLY_UNVERIFIED"
        return result
