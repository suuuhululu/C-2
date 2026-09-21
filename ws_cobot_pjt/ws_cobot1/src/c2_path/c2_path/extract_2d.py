#!/usr/bin/env python3
"""extract_2d.py — SVG 중심선을 전개면 u/v(mm) 점열로 바꾼다.

적용한 결정 (2026-09-19 최종 조합):
  - SVG path·subpath 연결관계를 보존한다. 획을 임의로 끊거나 잇지 않는다.
  - 중복점과 0길이 구간을 제거한다.
  - **이미 정상적인 Bézier 는 다시 피팅하지 않는다.** de Casteljau 분할로
    현(chord) 오차 기준 적응형 샘플링만 해서 좌표화한다.
  - RDP·B-spline 은 쓰지 않는다 (원본 도안 이탈 위험).

배치 규약 (권장안 3절, GeneratePath.action 확정):
  offset_u/v 는 **도안 중심**의 위치이고, 회전은 그 중심 기준 반시계다.
  SVG 의 아래 방향 y 축은 이 단계에서 v(위 방향)로 뒤집는다.
"""
import math
import re

from . import workcell as wc


# ---------------------------------------------------------------------------
# SVG 파싱 (M/L/C/Z. 중심선 SVG 에 필요한 최소 집합)
# ---------------------------------------------------------------------------
_TOKEN = re.compile(r"[MmLlCcZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_svg_subpaths(svg_text):
    """SVG <path> 들을 subpath 목록으로 돌려준다.

    각 subpath = {"closed": bool, "segments": [("L", p0, p1) | ("C", p0,p1,p2,p3)]}
    연결관계를 그대로 보존한다 (subpath 하나가 획 하나).
    """
    subpaths = []
    for m in re.finditer(r"<path[^>]*\sd=\"([^\"]+)\"", svg_text):
        toks = _TOKEN.findall(m.group(1))
        i = 0
        cur = None
        start = None
        pos = (0.0, 0.0)
        cmd = None
        while i < len(toks):
            t = toks[i]
            if t in "MmLlCcZz":
                cmd = t
                i += 1
                if cmd in "Zz":
                    if cur is not None:
                        if start is not None and math.dist(pos, start) > 1e-12:
                            cur["segments"].append(("L", pos, start))
                        cur["closed"] = True
                        subpaths.append(cur)
                        cur = None
                    continue
            if cmd is None:
                break
            rel = cmd.islower()

            def take(n):
                nonlocal i
                vals = [float(v) for v in toks[i:i + n]]
                i += n
                return vals

            if cmd in "Mm":
                x, y = take(2)
                pos = (pos[0] + x, pos[1] + y) if rel else (x, y)
                if cur is not None and cur["segments"]:
                    subpaths.append(cur)
                cur = {"closed": False, "segments": []}
                start = pos
                cmd = "l" if rel else "L"   # M 뒤 연속 좌표는 L 로 해석 (SVG 규칙)
            elif cmd in "Ll":
                x, y = take(2)
                nxt = (pos[0] + x, pos[1] + y) if rel else (x, y)
                if cur is not None and math.dist(pos, nxt) > 1e-12:
                    cur["segments"].append(("L", pos, nxt))
                pos = nxt
            elif cmd in "Cc":
                x1, y1, x2, y2, x3, y3 = take(6)
                if rel:
                    c1 = (pos[0] + x1, pos[1] + y1)
                    c2 = (pos[0] + x2, pos[1] + y2)
                    nxt = (pos[0] + x3, pos[1] + y3)
                else:
                    c1, c2, nxt = (x1, y1), (x2, y2), (x3, y3)
                if cur is not None:
                    cur["segments"].append(("C", pos, c1, c2, nxt))
                pos = nxt
            else:
                i += 1
        if cur is not None and cur["segments"]:
            subpaths.append(cur)
    return subpaths


# ---------------------------------------------------------------------------
# de Casteljau 적응형 샘플링
# ---------------------------------------------------------------------------
def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def de_casteljau_split(p0, p1, p2, p3, t=0.5):
    """3차 Bézier 를 t 에서 두 개로 나눈다 (de Casteljau)."""
    a = _lerp(p0, p1, t); b = _lerp(p1, p2, t); c = _lerp(p2, p3, t)
    d = _lerp(a, b, t); e = _lerp(b, c, t)
    f = _lerp(d, e, t)
    return (p0, a, d, f), (f, e, c, p3)


def _point_line_distance(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    den = math.hypot(dx, dy)
    if den < 1e-15:
        return math.dist(p, a)
    return abs(dx * (ay - p[1]) - (ax - p[0]) * dy) / den


def cubic_flatness(p0, p1, p2, p3):
    """제어점이 현에서 벗어난 최대 거리 = 현 오차 상한의 보수적 추정."""
    return max(_point_line_distance(p1, p0, p3), _point_line_distance(p2, p0, p3))


def sample_cubic_adaptive(p0, p1, p2, p3, chord_tol, max_step, depth=0, max_depth=20):
    """곡률이 큰 곳은 촘촘히, 직선에 가까운 곳은 성기게 샘플링한다.
    현 오차가 chord_tol 이하이고 현 길이가 max_step 이하면 더 쪼개지 않는다.
    반환: p0 를 제외한 점들 (앞 구간과 이어붙이기 위해)."""
    if depth >= max_depth:
        return [p3]
    if cubic_flatness(p0, p1, p2, p3) <= chord_tol and math.dist(p0, p3) <= max_step:
        return [p3]
    left, right = de_casteljau_split(p0, p1, p2, p3)
    pts = sample_cubic_adaptive(*left, chord_tol, max_step, depth + 1, max_depth)
    pts += sample_cubic_adaptive(*right, chord_tol, max_step, depth + 1, max_depth)
    return pts


def sample_line(p0, p1, max_step):
    n = max(1, int(math.ceil(math.dist(p0, p1) / max_step)))
    return [_lerp(p0, p1, k / n) for k in range(1, n + 1)]


def subpath_to_points(sub, chord_tol, max_step):
    """subpath -> 점열. 연결관계를 유지한 채 한 획으로 만든다."""
    pts = [sub["segments"][0][1]]
    for seg in sub["segments"]:
        if seg[0] == "L":
            pts += sample_line(seg[1], seg[2], max_step)
        else:
            pts += sample_cubic_adaptive(seg[1], seg[2], seg[3], seg[4], chord_tol, max_step)
    return pts


# ---------------------------------------------------------------------------
# 정리 / 배치
# ---------------------------------------------------------------------------
def dedup(points, min_gap):
    """중복점과 0길이 구간 제거. 끝점은 항상 보존한다."""
    if len(points) < 2:
        return list(points)
    out = [points[0]]
    for p in points[1:-1]:
        if math.dist(out[-1], p) >= min_gap:
            out.append(p)
    if math.dist(out[-1], points[-1]) < min_gap and len(out) > 1:
        out[-1] = points[-1]
    else:
        out.append(points[-1])
    return out


def _bbox(strokes):
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    return min(xs), min(ys), max(xs), max(ys)


def transform_raw_strokes(raw_strokes, source_bbox, width_mm, height_mm,
                          offset_u_mm, offset_v_mm, rotation_deg=0.0,
                          max_step_mm=None, min_gap_mm=None):
    """이미지 픽셀 점열을 u/v(mm) 획으로 변환한다.

    평행선 해칭은 공구 반경만큼 안쪽으로 줄어들므로, 획 자체 bbox가 아니라
    보정 전 전경 source_bbox를 기준으로 요청 width/height에 맞춘다. 그래야
    경계 보정 때문에 도안 전체가 다시 확대되는 일이 없다.
    """
    if not raw_strokes:
        raise ValueError("변환할 픽셀 획이 없습니다.")
    max_step_mm = max_step_mm if max_step_mm is not None else wc.WAYPOINT_SPACING_MAX_M * 1000.0
    min_gap_mm = min_gap_mm if min_gap_mm is not None else wc.WAYPOINT_SPACING_MIN_M * 1000.0
    x0, y0, x1, y1 = source_bbox
    src_w, src_h = max(x1 - x0, 1e-12), max(y1 - y0, 1e-12)
    scale = min(width_mm / src_w, height_mm / src_h)
    fitted_w, fitted_h = src_w * scale, src_h * scale
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    strokes = [[((px - cx) * scale, (cy - py) * scale) for px, py in s]
               for s in raw_strokes]
    if rotation_deg:
        t = math.radians(rotation_deg)
        ct, st = math.cos(t), math.sin(t)
        strokes = [[(p[0] * ct - p[1] * st, p[0] * st + p[1] * ct) for p in s]
                   for s in strokes]
    strokes = [[(p[0] + offset_u_mm, p[1] + offset_v_mm) for p in s]
               for s in strokes]

    sampled = []
    for stroke in strokes:
        points = [stroke[0]]
        for a, b in zip(stroke[:-1], stroke[1:]):
            # sample_line은 시작점을 제외하고 끝점을 포함한다. 첫 보간점을 버리면
            # 최대 waypoint 간격을 넘을 수 있으므로 반환값 전체를 붙인다.
            points.extend(sample_line(a, b, max_step_mm))
        points = dedup(points, min_gap_mm)
        if len(points) >= 2:
            sampled.append(points)
    if not sampled:
        raise ValueError("mm 변환 후 유효한 해칭 획이 남지 않았습니다.")

    us = [p[0] for s in sampled for p in s]
    vs = [p[1] for s in sampled for p in s]
    gaps = [math.dist(s[i], s[i + 1]) for s in sampled for i in range(len(s) - 1)]
    stats = {
        "subpath_count": len(raw_strokes),
        "stroke_count": len(sampled),
        "closed_subpaths": 0,
        "point_count": sum(len(s) for s in sampled),
        "fitted_size_mm": [round(fitted_w, 4), round(fitted_h, 4)],
        "scale": round(scale, 8),
        "center_uv_mm": [offset_u_mm, offset_v_mm],
        "rotation_deg": rotation_deg,
        "u_range_mm": [round(min(us), 4), round(max(us), 4)],
        "v_range_mm": [round(min(vs), 4), round(max(vs), 4)],
        "spacing_mm": {"min": round(min(gaps), 4), "max": round(max(gaps), 4),
                       "mean": round(sum(gaps) / len(gaps), 4)},
        "max_step_mm": max_step_mm,
        "source_bbox_px": list(source_bbox),
        "refit_applied": False,
    }
    return sampled, stats


def extract(svg_text, width_mm, height_mm, offset_u_mm, offset_v_mm, rotation_deg=0.0,
            chord_tol_mm=None, max_step_mm=None, min_gap_mm=None):
    """SVG -> u/v(mm) 획 목록.

    offset_u/v 는 **도안 중심**의 위치다 (GeneratePath.action 확정).
    """
    chord_tol_mm = chord_tol_mm if chord_tol_mm is not None else wc.CHORD_TOLERANCE_M * 1000.0
    max_step_mm = max_step_mm if max_step_mm is not None else wc.WAYPOINT_SPACING_MAX_M * 1000.0
    min_gap_mm = min_gap_mm if min_gap_mm is not None else wc.WAYPOINT_SPACING_MIN_M * 1000.0

    subs = parse_svg_subpaths(svg_text)
    if not subs:
        raise ValueError("SVG에서 획을 찾지 못했습니다.")

    # 1) 원본 좌표계에서 샘플링 (아직 mm 아님 — 스케일 전)
    raw = [subpath_to_points(s, chord_tol_mm, max_step_mm) for s in subs]
    closed = [s["closed"] for s in subs]

    # 2) 비율 유지 스케일 (요청 크기 안에 맞춤)
    x0, y0, x1, y1 = _bbox(raw)
    src_w, src_h = max(x1 - x0, 1e-12), max(y1 - y0, 1e-12)
    scale = min(width_mm / src_w, height_mm / src_h)
    fitted_w, fitted_h = src_w * scale, src_h * scale

    # 3) 도안 중심을 원점으로 옮기고 스케일 + y 뒤집기(v 는 위 방향)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    strokes = [[((px - cx) * scale, (cy - py) * scale) for px, py in s] for s in raw]

    # 4) 회전 (도안 중심 기준, u→v 반시계가 양)
    if rotation_deg:
        t = math.radians(rotation_deg)
        ct, st = math.cos(t), math.sin(t)
        strokes = [[(p[0] * ct - p[1] * st, p[0] * st + p[1] * ct) for p in s] for s in strokes]

    # 5) 중심을 offset 으로 이동
    strokes = [[(p[0] + offset_u_mm, p[1] + offset_v_mm) for p in s] for s in strokes]

    # 6) 샘플링이 만든 중복점 정리 (스케일 후 기준)
    strokes = [dedup(s, min_gap_mm) for s in strokes]
    strokes = [s for s in strokes if len(s) >= 2]

    us = [p[0] for s in strokes for p in s]
    vs = [p[1] for s in strokes for p in s]
    gaps = [math.dist(s[i], s[i + 1]) for s in strokes for i in range(len(s) - 1)]
    stats = {
        "subpath_count": len(subs),
        "stroke_count": len(strokes),
        "closed_subpaths": sum(1 for c in closed if c),
        "point_count": sum(len(s) for s in strokes),
        "fitted_size_mm": [round(fitted_w, 4), round(fitted_h, 4)],
        "scale": round(scale, 8),
        "center_uv_mm": [offset_u_mm, offset_v_mm],
        "rotation_deg": rotation_deg,
        "u_range_mm": [round(min(us), 4), round(max(us), 4)],
        "v_range_mm": [round(min(vs), 4), round(max(vs), 4)],
        "spacing_mm": {"min": round(min(gaps), 4), "max": round(max(gaps), 4),
                       "mean": round(sum(gaps) / len(gaps), 4)},
        "chord_tolerance_mm": chord_tol_mm,
        "max_step_mm": max_step_mm,
        "refit_applied": False,   # 정상 Bézier 는 재피팅하지 않음
    }
    return strokes, stats
