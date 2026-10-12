"""2단계 수신 후보 판정. 실제 개방/이동 없음; 모델 자세 근거 부족은 unknown."""
import argparse
import json
import math
from pathlib import Path
from statistics import median


def raw_pixel(pixel, processed_to_raw):
    x, y = pixel
    v = [sum(row[i]*[x,y,1][i] for i in range(3)) for row in processed_to_raw]
    if not all(math.isfinite(n) for n in v) or abs(v[2]) < 1e-12:
        raise ValueError("invalid pixel transform")
    return [v[0]/v[2],v[1]/v[2]]


def mediapipe_landmarks(rgb, model_path):
    """Caller supplies an existing RGB frame; never opens the camera."""
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    options = vision.HandLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),num_hands=2)
    with vision.HandLandmarker.create_from_options(options) as model:
        result = model.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb))
    return [[dict(x=p.x,y=p.y,z=p.z) for p in hand] for hand in result.hand_landmarks]


def landmark_hand(landmarks,track_id,depth,*,processed_size,processed_to_raw,surface_evidence=None):
    """Landmarks→open shape/palm interior depth. Palm side requires separate evidence."""
    import cv2
    import numpy as np
    if len(landmarks)!=21 or depth.ndim!=2:
        raise ValueError("21 landmarks and a raw aligned depth image required")
    raw_height,raw_width=depth.shape
    width,height=processed_size
    points=[[p["x"]*width,p["y"]*height,p["z"]*width] for p in landmarks]
    if not all(math.isfinite(v) for p in points for v in p):
        raise ValueError("nonfinite landmarks")
    opened=all(math.dist(points[tip],points[0])>math.dist(points[pip],points[0]) for tip,pip in ((4,2),(8,6),(12,10),(16,14),(20,18)))
    polygon=[raw_pixel(points[i][:2],processed_to_raw) for i in (0,5,9,13,17)]
    if any(not 0<=p[0]<raw_width or not 0<=p[1]<raw_height for p in polygon):
        raise ValueError("palm lies outside raw depth image")
    mask=np.zeros(depth.shape,dtype=np.uint8)
    cv2.fillConvexPoly(mask,cv2.convexHull(np.asarray(polygon,dtype=np.int32)),1)
    center=[sum(points[k][i] for k in (0,5,9,13,17))/5 for i in (0,1)]
    evidence=surface_evidence or {}
    return dict(track_id=track_id,open_hand=opened,pixel=center,
        interior_depth=depth[mask==1].astype(float).tolist(),surface=evidence.get("surface","unknown"),
        orientation_confirmed=evidence.get("orientation_confirmed",False),palm_normal_camera=evidence.get("palm_normal_camera"))


class ReceiverCandidate:
    def __init__(self, *, max_age_ns, max_latency_ns, hold_ns, max_gap_ns,
                 min_depth_fraction, max_depth_spread_m, max_motion_px):
        if any(type(v) is not int or v < 0 for v in (max_age_ns,max_latency_ns,hold_ns,max_gap_ns)):
            raise ValueError("time limits require nonnegative ns")
        if not 0 < min_depth_fraction <= 1 or max_depth_spread_m <= 0 or max_motion_px <= 0:
            raise ValueError("invalid perception limits")
        self.limits = dict(max_age_ns=max_age_ns,max_latency_ns=max_latency_ns,hold_ns=hold_ns,
            max_gap_ns=max_gap_ns,min_depth_fraction=min_depth_fraction,max_depth_spread_m=max_depth_spread_m,max_motion_px=max_motion_px)
        self.previous = None

    def evaluate(self, sample, now_ns, generation):
        result = dict(ready=False,hand_present=False,open_hand="unknown",grasp="unknown",
            reason=None,pixel=None,depth_m=None,depth_fraction=0,depth_spread_m=None,
            track_id=None,source_ns=sample["source_ns"],frame=sample["frame"],generation=generation,
            real_output_enabled=False)

        def reject(reason):
            self.previous = None
            result["reason"] = reason
            return result

        t = sample["source_ns"]
        if sample["generation"] != generation or not sample["frame"]:
            return reject("GENERATION_OR_FRAME_MISMATCH")
        if t > now_ns or now_ns-t > self.limits["max_age_ns"] or not t <= sample["inference_ns"] <= now_ns or sample["inference_ns"]-t > self.limits["max_latency_ns"]:
            return reject("STALE_OR_LATE_FRAME")
        hands = sample["hands"]
        result["hand_present"] = bool(hands)
        if len(hands) != 1:
            return reject("NO_HAND" if not hands else "MULTIPLE_HANDS")
        hand = hands[0]
        result.update(track_id=hand["track_id"],open_hand=hand["open_hand"])
        if not hand["track_id"] or hand["open_hand"] is not True:
            return reject("HAND_NOT_OPEN_OR_UNKNOWN")
        if hand.get("surface") != "palm" or hand.get("orientation_confirmed") is not True:
            return reject("RECEIVING_ORIENTATION_UNKNOWN")
        normal=hand.get("palm_normal_camera")
        if not isinstance(normal,list) or len(normal)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in normal) or abs(sum(v*v for v in normal)-1)>1e-6:
            return reject("INVALID_PALM_NORMAL")
        # Alignment is a verified producer property, never inferred from topic spelling.
        scale = sample.get("depth_scale_m")
        raw = hand["interior_depth"]
        if sample.get("aligned") is not True or type(scale) not in (float,int) or not math.isfinite(scale) or scale <= 0 or not raw:
            return reject("DEPTH_ALIGNMENT_OR_SCALE_UNKNOWN")
        depths = [v*scale for v in raw if type(v) in (int,float) and math.isfinite(v) and v>0]
        fraction = len(depths)/len(raw)
        result["depth_fraction"] = fraction
        if fraction < self.limits["min_depth_fraction"]:
            return reject("DEPTH_MISSING")
        depth = median(depths)
        spread = max(abs(v-depth) for v in depths)
        result["depth_spread_m"] = spread
        if spread > self.limits["max_depth_spread_m"]:
            return reject("DEPTH_UNSTABLE")
        pixel = raw_pixel(hand["pixel"], sample["processed_to_raw"])
        previous = self.previous
        current = dict(t=t,start=t,track=hand["track_id"],generation=generation,frame=sample["frame"],pixel=pixel)
        if previous:
            if t <= previous["t"]:
                return reject("OLD_OR_DUPLICATE_FRAME")
            same = all(previous[k] == current[k] for k in ("track","generation","frame"))
            stable = math.dist(pixel,previous["pixel"]) <= self.limits["max_motion_px"]
            if same and stable and t-previous["t"] <= self.limits["max_gap_ns"]:
                current["start"] = previous["start"]
        self.previous = current
        ready = t-current["start"] >= self.limits["hold_ns"]
        result.update(ready=ready,reason=None if ready else "STABILITY_PENDING",
            pixel=pixel if ready else None,depth_m=depth if ready else None,
            palm_normal_camera=normal,orientation_confirmed=True)
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture",type=Path)
    args=parser.parse_args(argv)
    data=json.loads(args.fixture.read_text())
    candidate=ReceiverCandidate(**data["limits"])
    for sample in data["samples"]:
        print(json.dumps(candidate.evaluate(sample,sample["inference_ns"],data["generation"]),ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
