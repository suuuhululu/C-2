#!/usr/bin/env python3
"""validate_path.py — 만들어진 경로가 계약·안전 제약을 지키는지 검사한다.

금지 조건(어기면 실패)과 품질 지표(기록만)를 나눈다.
`c2_path` 가 확인하지 않는 항목은 `not_checked` 에 명시해서, 실행 측
(preconditions.py)이 무엇을 직접 봐야 하는지 코드로 판단할 수 있게 한다.
"""
import math

from . import workcell as wc

TOL_POS = 1e-4
TOL_QUAT = 1e-4
TOL_SPACING = 1e-4

# c2_path 가 확인하지 않는 항목. 실행 측이 확인해야 한다.
NOT_CHECKED = ["J6_RANGE"]          # 역기구학이 필요 — path_planner_node 는 로봇을 실행하지 않음


def _v(w):
    """waypoint [x, y, z, qx, qy, qz, qw] 의 위치 (로봇팀 형식)."""
    return (w[0], w[1], w[2])


def _q(w):
    return (w[3], w[4], w[5], w[6])


def _is_pose7(w):
    return (isinstance(w, (list, tuple)) and len(w) == wc.POSE_LEN
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c)
                    for c in w))


def _radial(p):
    return math.hypot(p[0] - wc.AXIS_ORIGIN_XY_M[0], p[1] - wc.AXIS_ORIGIN_XY_M[1])


def _theta(p):
    return math.degrees(math.atan2(p[1] - wc.AXIS_ORIGIN_XY_M[1], p[0] - wc.AXIS_ORIGIN_XY_M[0]))


def _height(p):
    return p[2] - wc.AXIS_ORIGIN_Z_M


def _unwrap(seq):
    """atan2 의 ±180 을 펴서 연속된 각도로 만든다. 9/20 부터 이음매도 ±180 이라 두 경계가 겹치므로,
    이음매 통과 여부는 편 각도에서 seam + 360k 전부를 기준으로 본다 (wc.seams_strictly_between)."""
    out, acc = [seq[0]], 0.0
    for k in range(1, len(seq)):
        d = seq[k] - seq[k - 1]
        if d > 180.0:
            acc -= 360.0
        elif d < -180.0:
            acc += 360.0
        out.append(seq[k] + acc)
    return out


def _crosses_seam(unwrapped, tol=1e-6):
    """편 각도 열이 이음매를 넘는지. 연속된 열이므로 최솟값과 최댓값 사이(끝 제외)에 이음매가 하나라도
    있으면 넘은 것이다. 점이 정확히 이음매 위에 찍혀 지나가는 경우도 잡는다. 끝점이 닿는 것은 허용
    (이음매에서 분할된 조각은 이음매에서 시작·끝난다)."""
    if len(unwrapped) < 2:
        return False
    return bool(wc.seams_strictly_between(min(unwrapped) + tol, max(unwrapped) - tol))


def _quat_axes(q):
    x, y, z, w = q
    R = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return ((R[0][0], R[1][0], R[2][0]), (R[0][1], R[1][1], R[2][1]), (R[0][2], R[1][2], R[2][2]))


def validate(path):
    errors, checks = [], []
    segs = path["segments"]
    stroke_theta = {}

    # ---- 설정 일치 (금지 조건) ----
    if path.get("frame_id") != wc.FRAME_ID:
        errors.append(f"CONFIG_MISMATCH: frame_id {path.get('frame_id')} != {wc.FRAME_ID}")
    if path.get("tool_id") != wc.TOOL_ID:
        errors.append(f"CONFIG_MISMATCH: tool_id {path.get('tool_id')} != {wc.TOOL_ID}")
    if path.get("position_unit") != "m" or path.get("orientation") != "quaternion_xyzw":
        errors.append("CONFIG_MISMATCH: position_unit/orientation")
    if path.get("schema_version") != wc.PATH_SCHEMA_VERSION:
        errors.append(f"UNSUPPORTED_SCHEMA_VERSION: {path.get('schema_version')} != {wc.PATH_SCHEMA_VERSION}")

    # waypoint 형식 (로봇팀 engraving.py 와 동일: 유한한 수 7개). 형식이 틀리면 기하 검사를 하지 않는다.
    bad_fmt = [f"{s_.get('segment_id')}[{k}]" for s_ in segs
               for k, w in enumerate(s_.get("waypoints") or []) if not _is_pose7(w)]
    if bad_fmt:
        errors.append(f"WAYPOINT_FORMAT: [x,y,z,qx,qy,qz,qw] 아님 {len(bad_fmt)}곳 (예: {bad_fmt[0]})")
        return {"passed": False,
                "checks": [{"code": "WAYPOINT_FORMAT", "passed": False, "observed_bad": len(bad_fmt)}],
                "not_checked": NOT_CHECKED, "errors": errors}

    q_flips = 0
    max_spacing = 0.0
    max_points = 0
    min_travel_clear = math.inf
    worst_chord_err = 0.0

    for seg in segs:
        kind, wps, sid = seg["kind"], seg["waypoints"], seg.get("stroke_id")

        # 쿼터니언 정규화 + 부호 연속성
        for k, w in enumerate(wps):
            q = _q(w)
            nq = math.sqrt(sum(c * c for c in q))
            if abs(nq - 1.0) > TOL_QUAT:
                errors.append(f"QUAT_NOT_NORMALIZED: {seg['segment_id']}[{k}] |q|={nq:.6f}")
            if k > 0 and wc.quat_dot(_q(wps[k - 1]), q) < 0.0:
                q_flips += 1

            # 자세 규약: 로컬 +Z = base -Z, 로컬 -Y = 안쪽 법선
            _, ly, lz = _quat_axes(q)
            if abs(lz[2] + 1.0) > 1e-3:
                errors.append(f"ORIENTATION: {seg['segment_id']}[{k}] 로컬 +Z가 base -Z 아님")
            th = _theta(_v(w))
            outward = wc.radial_direction(th)
            dot = sum(-a * -b for a, b in zip(ly, outward))
            if dot < 1 - 1e-3:
                errors.append(f"ORIENTATION: {seg['segment_id']}[{k}] 로컬 -Y가 안쪽 법선 아님")

        if kind == "CUT":
            max_points = max(max_points, len(wps))
            if len(wps) > wc.SEGMENT_POINTS_MAX:
                errors.append(f"SEGMENT_POINTS_MAX: {seg['segment_id']} {len(wps)}점")
            for k, w in enumerate(wps):
                p = _v(w)
                if abs(_radial(p) - wc.RADIUS_M) > TOL_POS:
                    errors.append(f"NOT_ON_SURFACE: {seg['segment_id']}[{k}] r={_radial(p):.6f}")
                h = _height(p)
                lo, hi = wc.WORKABLE_HEIGHT_RANGE_M
                if not (lo - 1e-6 <= h <= hi + 1e-6):
                    errors.append(f"HEIGHT_OUT_OF_RANGE: {seg['segment_id']}[{k}] h={h:.6f}")
                stroke_theta.setdefault(sid, []).append(_theta(p))
            for k in range(len(wps) - 1):
                d = math.dist(_v(wps[k]), _v(wps[k + 1]))
                max_spacing = max(max_spacing, d)
                if d > wc.WAYPOINT_SPACING_MAX_M + TOL_SPACING:
                    errors.append(f"CUT_SPACING: {seg['segment_id']}[{k}] {d*1000:.3f}mm")
                # 현 오차 (표면 이탈)
                a, b = _v(wps[k]), _v(wps[k + 1])
                mid = tuple((a[i] + b[i]) / 2 for i in range(3))
                worst_chord_err = max(worst_chord_err, abs(_radial(mid) - wc.RADIUS_M))
        else:
            # 비절삭 구간: TRAVEL 은 표면 밖이어야 한다.
            # APPROACH/RETRACT 는 절삭점으로 들어가고 나오므로 표면에 닿는 것이 정상이다.
            for k in range(len(wps) - 1):
                a, b = _v(wps[k]), _v(wps[k + 1])
                for i in range(21):
                    t = i / 20
                    p = tuple(a[c] + (b[c] - a[c]) * t for c in range(3))
                    r = _radial(p)
                    if kind == "TRAVEL":
                        min_travel_clear = min(min_travel_clear, r - wc.RADIUS_M)
                        if r < wc.RADIUS_M - TOL_POS:
                            errors.append(f"CYLINDER_PENETRATION: {seg['segment_id']} r={r:.6f}")
                    elif r < wc.RADIUS_M - TOL_POS:
                        errors.append(f"CYLINDER_PENETRATION: {seg['segment_id']}({kind}) r={r:.6f}")

    # 획당 둘레 각도 / 이음매
    max_arc = 0.0
    for sid, ths in stroke_theta.items():
        unw = _unwrap(ths)
        span = max(unw) - min(unw)
        max_arc = max(max_arc, span)
        if span > wc.STROKE_MAX_ARC_DEG + 1e-6:
            errors.append(f"STROKE_ARC_MAX: {sid} {span:.2f}도")
        # 이음매(seam + 360k): 편 각도에서 연속한 두 점 사이에 이음매가 있으면 통과한 것.
        if _crosses_seam(unw):
            errors.append(f"SEAM_CROSSED: {sid}")
        # CUT 허용 각도 범위 (J5 안전 범위 — 수치 확정 전까지 전 범위)
        lo_r, hi_r = wc.REACHABLE_ANGLE_DEG
        for t in ths:
            if not (lo_r - 1e-6 <= t <= hi_r + 1e-6):
                errors.append(f"ANGLE_OUT_OF_RANGE: {sid} θ={t:.2f}도 (허용 {lo_r}~{hi_r})")
                break

    # TRAVEL 도 이음매(로봇 쪽)를 넘지 않는다 — 오프셋 원통 위라도 자세는 반경 방향이라 J5 위험은 같다.
    for seg in segs:
        if seg["kind"] == "TRAVEL" and _crosses_seam(_unwrap([_theta(_v(w)) for w in seg["waypoints"]])):
            errors.append(f"SEAM_CROSSED: {seg['segment_id']}(TRAVEL)")

    # segment 연결 연속성
    for i in range(len(segs) - 1):
        d = math.dist(_v(segs[i]["waypoints"][-1]), _v(segs[i + 1]["waypoints"][0]))
        if d > TOL_POS:
            errors.append(f"SEGMENT_GAP: {segs[i]['segment_id']} -> {segs[i+1]['segment_id']} {d*1000:.3f}mm")

    if q_flips:
        errors.append(f"QUAT_SIGN_DISCONTINUITY: {q_flips}곳")

    lo, hi = wc.WORKABLE_HEIGHT_RANGE_M
    checks = [
        {"code": "SCHEMA_VERSION", "passed": not any(e.startswith("UNSUPPORTED_SCHEMA") for e in errors),
         "expected": wc.PATH_SCHEMA_VERSION, "observed": path.get("schema_version")},
        {"code": "WAYPOINT_FORMAT", "passed": True, "format": "[x,y,z,qx,qy,qz,qw]"},
        {"code": "CONFIG_MATCH", "passed": not any(e.startswith("CONFIG") for e in errors),
         "frame_id": path.get("frame_id"), "tool_id": path.get("tool_id")},
        {"code": "HEIGHT_IN_RANGE", "passed": not any("HEIGHT_OUT" in e for e in errors),
         "limit_m": [lo, hi]},
        {"code": "CUT_ON_SURFACE", "passed": not any("NOT_ON_SURFACE" in e for e in errors),
         "observed_max_chord_error_m": round(worst_chord_err, 8)},
        {"code": "CUT_SPACING_MAX", "passed": not any("CUT_SPACING" in e for e in errors),
         "limit_m": wc.WAYPOINT_SPACING_MAX_M, "observed_max_m": round(max_spacing, 6)},
        {"code": "SEGMENT_POINTS_MAX", "passed": not any("SEGMENT_POINTS" in e for e in errors),
         "limit": wc.SEGMENT_POINTS_MAX, "observed_max": max_points},
        {"code": "STROKE_ARC_MAX", "passed": not any("STROKE_ARC" in e for e in errors),
         "limit_deg": wc.STROKE_MAX_ARC_DEG, "observed_max_deg": round(max_arc, 3)},
        {"code": "SEAM_NOT_CROSSED", "passed": not any("SEAM_CROSSED" in e for e in errors),
         "seam_angle_deg": wc.SEAM_ANGLE_DEG, "applies_to": ["CUT", "TRAVEL"]},
        {"code": "ANGLE_IN_REACHABLE_RANGE", "passed": not any("ANGLE_OUT_OF_RANGE" in e for e in errors),
         "limit_deg": list(wc.REACHABLE_ANGLE_DEG), "note": "J5 안전 범위 확정 전 — 현재 전 범위"},
        {"code": "NO_CYLINDER_PENETRATION", "passed": not any("PENETRATION" in e for e in errors),
         "observed_min_travel_clearance_m": (round(min_travel_clear, 6)
                                             if min_travel_clear < math.inf else None)},
        {"code": "QUAT_NORMALIZED_AND_CONTINUOUS",
         "passed": not any("QUAT" in e for e in errors), "observed_sign_flips": q_flips},
        {"code": "SEGMENT_CONTINUITY", "passed": not any("SEGMENT_GAP" in e for e in errors)},
    ]
    report = {"passed": len(errors) == 0, "checks": checks, "not_checked": NOT_CHECKED,
              "errors": errors}
    return report
