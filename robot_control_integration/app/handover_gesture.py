"""Gesture timing/transition unit. Consumes verified evidence; no device output.

This does not infer poses, hand identity, orientation, or clock alignment from RGB.
The caller owns the active request ID and must never reopen a closed request ID.
"""
import argparse
import json
from pathlib import Path


class GestureGate:
    HOLD_NS = 2_000_000_000

    def __init__(self, *, max_age_ns, max_gap_ns, max_latency_ns):
        limits = (max_age_ns, max_gap_ns, max_latency_ns)
        if any(type(v) is not int or v < 0 for v in limits) or max_gap_ns == 0:
            raise ValueError("nonnegative ns limits and a positive frame gap required")
        self.max_age_ns = max_age_ns
        self.max_gap_ns = max_gap_ns
        self.max_latency_ns = max_latency_ns
        self.context = None
        self.previous = None
        self.last_source_ns = None
        self.emitted = False

    def evaluate(self, sample, now_ns, *, mode=None, request_id=None):
        """Return YES/NO/RECEIVE_REQUEST once per current request, or event=None.

        mode: QUESTION, RECEIVE, or None (inactive). All ns timestamps must share
        a verified clock. Unknown/absent evidence cancels continuous progress.
        """
        if mode not in (None, "QUESTION", "RECEIVE"):
            raise ValueError("unknown gesture mode")
        if mode is not None and (not isinstance(request_id, str) or not request_id):
            raise ValueError("active mode requires the caller's current request_id")
        context = (mode, request_id) if mode is not None else None
        if context != self.context:
            self.context = context
            self.previous = self.last_source_ns = None
            self.emitted = False
        result = dict(event=None, reason=None, held_ns=0, request_id=request_id,
                      mode=mode, real_output_enabled=False)

        def reject(reason):
            self.previous = None
            result["reason"] = reason
            return result

        if context is None:
            return reject("INACTIVE")
        if sample.get("request_id") != request_id:
            return reject("REQUEST_MISMATCH")
        if self.emitted:
            return reject("ALREADY_EMITTED")
        t, inferred = sample.get("source_ns"), sample.get("inference_ns")
        if any(type(v) is not int or v < 0 for v in (t, inferred, now_ns)):
            return reject("INVALID_TIME")
        if sample.get("clock_verified") is not True:
            return reject("CLOCK_UNKNOWN")
        if not t <= inferred <= now_ns or now_ns-t > self.max_age_ns or inferred-t > self.max_latency_ns:
            return reject("STALE_OR_LATE_FRAME")
        if self.last_source_ns is not None and t <= self.last_source_ns:
            return reject("OLD_OR_DUPLICATE_FRAME")
        # Retain this watermark even if evidence below is rejected.
        self.last_source_ns = t
        hands = sample.get("hands")
        if not isinstance(hands, list) or len(hands) != 1:
            return reject("SINGLE_HAND_REQUIRED")
        hand = hands[0]
        track, frame = hand.get("track_id"), sample.get("frame")
        if not isinstance(track, str) or not track or hand.get("track_confirmed") is not True:
            return reject("TRACK_UNKNOWN")
        if not isinstance(frame, str) or not frame or hand.get("pose_confirmed") is not True:
            return reject("POSE_OR_FRAME_UNKNOWN")
        pose = hand.get("pose")
        previous = self.previous
        if previous and (previous["track"] != track or previous["frame"] != frame or t-previous["t"] > self.max_gap_ns):
            previous = None
        current = dict(track=track, frame=frame, t=t, start=t, pose=pose)
        if mode == "QUESTION":
            if pose == "THUMBS_UP":
                event = "YES"
            elif pose == "L" and hand.get("surface") == "back" and hand.get("orientation_confirmed") is True:
                event = "NO"
            else:
                return reject("ANSWER_POSE_UNKNOWN")
            if previous and previous["pose"] == pose:
                current["start"] = previous["start"]
            result["held_ns"] = t-current["start"]
            ready = result["held_ns"] >= self.HOLD_NS
        else:
            # A fist only arms this unit; it never issues a gripper-close command.
            ready = pose == "OPEN_PALM" and hand.get("surface") == "palm" and hand.get("orientation_confirmed") is True and previous is not None and previous["pose"] == "FIST"
            if pose != "FIST" and not ready:
                return reject("FIST_TO_PALM_REQUIRED")
            event = "RECEIVE_REQUEST"
        self.previous = current
        if ready:
            self.emitted = True
            result.update(event=event, reason="EMITTED")
        else:
            result["reason"] = "HOLD_PENDING" if mode == "QUESTION" else "FIST_ARMED"
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="SYNTHETIC evidence JSON; no ROS imports")
    args = parser.parse_args(argv)
    data = json.loads(args.fixture.read_text())
    if data["provenance"] != "SYNTHETIC":
        raise ValueError("this unit runner only accepts explicitly synthetic evidence")
    gate = GestureGate(**data["limits"])
    for step in data["steps"]:
        result = gate.evaluate(step["sample"], step["now_ns"],
                               mode=step["mode"], request_id=step["request_id"])
        print(json.dumps(dict(provenance="SYNTHETIC", **result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
