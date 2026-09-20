#!/usr/bin/env python3
"""map_3d.py — 전개면 u/v 획을 원통 표면 3D 자세로 매핑한다.

적용한 결정 (2026-09-19 최종 조합):
  - 정면 투영이 아니라 **원통 iso-parametric 해석식**으로 매핑한다.
  - 작업 가능 높이·둘레 각도·이음매·한 획의 최대 각도 기준으로 검사하고 분할한다.
  - (9/20) θ = u 원점 각도(0°) + u/R. 이음매(180°)는 별도 상수이며, 분할된 구간은
    [−180°, 180°] 로 옮겨 표현한다.
  - 각 표면점에서 승인된 도구 축(-Y)을 안쪽 접촉 방향에 정렬하고, 원통 축으로
    나머지 자세를 정한다.
  - quaternion 은 정규화하고 **인접 자세의 부호·회전 연속성을 보정**한다.
  - CUT waypoint 는 원통 매개변수 공간에서 적응형으로 재샘플링한다.
    (2D 직선이 3D 에서는 호가 되므로, 3D 현 오차로 다시 확인한다.)
"""
import math

from . import workcell as wc


# ---------------------------------------------------------------------------
# 분할
# ---------------------------------------------------------------------------
def _on_seam(theta, eps=1e-9):
    k = round((theta - wc.SEAM_ANGLE_DEG) / 360.0)
    return abs(theta - (wc.SEAM_ANGLE_DEG + 360.0 * k)) < eps, wc.SEAM_ANGLE_DEG + 360.0 * k


def split_at_seam(tv):
    """이음매(seam_angle + 360k)를 지나는 지점에서 끊는다.

    - 두 점 사이에서 이음매를 넘으면 교점을 넣고 끊는다 (여러 번 넘어도 모두).
    - 점이 정확히 이음매 위에 있고 앞뒤 점이 이음매 반대편에 있으면 그 점에서 끊는다.
      (예: 하트 아래 꼭짓점이 정확히 180° 에 놓이는 경우. 교점 검사만으로는 놓친다.)
    """
    parts, cur = [], [tv[0]]
    for i in range(1, len(tv)):
        a, b = tv[i - 1], tv[i]
        seams = wc.seams_strictly_between(a[0], b[0])
        if a[0] > b[0]:
            seams = seams[::-1]
        for seam_t in seams:
            den = b[0] - a[0]
            r = 0.0 if abs(den) < 1e-12 else (seam_t - a[0]) / den
            h = a[1] + (b[1] - a[1]) * r
            cur.append((seam_t, h))
            parts.append(cur)
            cur = [(seam_t, h)]
        cur.append(b)
        if i + 1 < len(tv):
            on, seam_t = _on_seam(b[0])
            c = tv[i + 1]
            if on and (a[0] - seam_t) * (c[0] - seam_t) < 0:
                parts.append(cur)
                cur = [b]
    parts.append(cur)
    return [p for p in parts if len(p) >= 2]


def to_seam_interval(part):
    """이음매로 끊긴 구간을 대표 구간 [seam−360, seam] (= [−180, 180]) 으로 옮긴다.

    같은 물리 각도를 한 가지 숫자로 나타내야 TRAVEL 보간이 이음매를 넘지 않는다
    (θ 를 선형 보간하므로, 구간 안의 두 각도 사이 이동은 항상 이음매 반대쪽으로 돈다).
    """
    ts = [t for t, _ in part]
    mid = (min(ts) + max(ts)) / 2.0
    shift = -360.0 * wc.seam_index(mid)
    return [(t + shift, h) for t, h in part]


def split_by_arc_limit(tv, max_arc_deg):
    """한 구간의 둘레 각도 범위가 한계를 넘으면 쪼갠다 (J6 감김 방지)."""
    parts, cur = [], [tv[0]]
    tmin = tmax = tv[0][0]
    for p in tv[1:]:
        ntmin, ntmax = min(tmin, p[0]), max(tmax, p[0])
        if (ntmax - ntmin) > max_arc_deg:
            parts.append(cur)
            cur = [cur[-1], p]
            tmin, tmax = min(cur[0][0], p[0]), max(cur[0][0], p[0])
        else:
            cur.append(p)
            tmin, tmax = ntmin, ntmax
    parts.append(cur)
    return [p for p in parts if len(p) >= 2]


# ---------------------------------------------------------------------------
# 매개변수 공간 적응형 재샘플링
# ---------------------------------------------------------------------------
def _pos(theta, h):
    return wc.surface_point(theta, h)


def _chord_error_3d(t0, h0, t1, h1):
    """(theta,h) 두 점을 직선으로 이었을 때 실제 표면과의 최대 이탈(근사).
    중점에서의 거리로 본다 — 원통에서는 이게 sagitta 와 같다."""
    mid_t, mid_h = (t0 + t1) / 2.0, (h0 + h1) / 2.0
    on_surface = _pos(mid_t, mid_h)
    a, b = _pos(t0, h0), _pos(t1, h1)
    chord_mid = tuple((a[k] + b[k]) / 2.0 for k in range(3))
    return math.dist(on_surface, chord_mid)


def resample_adaptive(tv, chord_tol_m, max_step_m, min_step_m, max_depth=12):
    """매개변수 공간에서 적응형 재샘플링.

    - 현 오차가 크거나 간격이 max_step 을 넘으면 중점을 넣어 쪼갠다.
    - 간격이 min_step 보다 작으면 중간점을 버린다 (끝점은 보존).
    """
    out = [tv[0]]
    for i in range(1, len(tv)):
        a, b = tv[i - 1], tv[i]
        stack = [(a, b, 0)]
        pending = []
        while stack:
            p, q, d = stack.pop()
            step = math.dist(_pos(*p), _pos(*q))
            err = _chord_error_3d(p[0], p[1], q[0], q[1])
            if d < max_depth and (step > max_step_m or err > chord_tol_m):
                m = ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)
                stack.append((m, q, d + 1))
                stack.append((p, m, d + 1))
            else:
                pending.append(q)
        out.extend(pending)
    # 너무 촘촘한 점 정리 (끝점 보존)
    cleaned = [out[0]]
    for p in out[1:-1]:
        if math.dist(_pos(*cleaned[-1]), _pos(*p)) >= min_step_m:
            cleaned.append(p)
    cleaned.append(out[-1])
    return cleaned


# ---------------------------------------------------------------------------
def map_strokes(strokes_uv, check_height=True):
    """u/v(mm) 획 -> 3D 획. 반환: (mapped, failures, stats)"""
    mapped, failures = [], []
    n_seam = n_arc = 0
    pts_before = pts_after = 0

    for idx, pts in enumerate(strokes_uv):
        sid = f"stroke{idx:03d}"
        tv = [(wc.theta_deg_from_u_mm(u), v / 1000.0) for u, v in pts]
        pts_before += len(tv)

        if check_height:
            lo, hi = wc.WORKABLE_HEIGHT_RANGE_M
            bad = [i for i, (_, h) in enumerate(tv) if not (lo - 1e-9 <= h <= hi + 1e-9)]
            if bad:
                failures.append({
                    "reason_code": "HEIGHT_OUT_OF_RANGE",
                    "stroke_id": sid,
                    "first_offending_index": bad[0],
                    "offending_height_m": round(tv[bad[0]][1], 6),
                    "workable_height_range_m": list(wc.WORKABLE_HEIGHT_RANGE_M),
                })
                continue

        seam_parts = [to_seam_interval(p) for p in split_at_seam(tv)]
        if len(seam_parts) > 1:
            n_seam += 1
        parts = []
        for sp in seam_parts:
            ap = split_by_arc_limit(sp, wc.STROKE_MAX_ARC_DEG)
            if len(ap) > 1:
                n_arc += 1
            parts.extend(ap)

        for pi, part in enumerate(parts):
            part = resample_adaptive(part, wc.CHORD_TOLERANCE_M,
                                     wc.WAYPOINT_SPACING_MAX_M, wc.WAYPOINT_SPACING_MIN_M)
            pts_after += len(part)
            quats = wc.make_continuous([wc.tool_orientation(t) for t, _ in part])
            waypoints = []
            for (t, h), q in zip(part, quats):
                p = wc.surface_point(t, h)
                waypoints.append({
                    "position_m": {"x": round(p[0], 6), "y": round(p[1], 6), "z": round(p[2], 6)},
                    "orientation_xyzw": {"x": round(q[0], 6), "y": round(q[1], 6),
                                         "z": round(q[2], 6), "w": round(q[3], 6)},
                    "theta_deg": round(t, 5),
                    "height_m": round(h, 6),
                })
            entry = {
                "stroke_id": sid if len(parts) == 1 else f"{sid}_part{pi}",
                "waypoints": waypoints,
                "theta_range_deg": [round(min(t for t, _ in part), 4),
                                    round(max(t for t, _ in part), 4)],
            }
            if len(parts) > 1:
                entry.update({"split_from_stroke_id": sid, "split_index": pi,
                              "split_count": len(parts), "join_forbidden": True})
            mapped.append(entry)

    stats = {
        "input_strokes": len(strokes_uv),
        "mapped_strokes": len(mapped),
        "strokes_split_at_seam": n_seam,
        "strokes_split_by_arc_limit": n_arc,
        "failed_strokes": len(failures),
        "points_before_resample": pts_before,
        "points_after_resample": pts_after,
        "seam_angle_deg": wc.SEAM_ANGLE_DEG,
        "u_origin_angle_deg": wc.U_ORIGIN_ANGLE_DEG,
        "stroke_max_arc_deg": wc.STROKE_MAX_ARC_DEG,
        "projection": "cylinder_iso_parametric",
    }
    if mapped:
        th = [w["theta_deg"] for s in mapped for w in s["waypoints"]]
        hh = [w["height_m"] for s in mapped for w in s["waypoints"]]
        stats["theta_range_deg"] = [round(min(th), 3), round(max(th), 3)]
        stats["height_range_m"] = [round(min(hh), 6), round(max(hh), 6)]
    return mapped, failures, stats
