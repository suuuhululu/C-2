#!/usr/bin/env python3
"""image_to_svg.py — 입력 이미지(PNG/JPEG)를 중심선(centerline) SVG로 바꾼다.

적용 파이프라인 (docs/ALGORITHM_VALIDATION.md 3차 검증 조합):
    Otsu 이진화 → Zhang-Suen 세선화(skimage skeletonize) → 골격 그래프 추적
    → 짧은 잔가지(spur) 정리 → Schneider 최소제곱 베지어 근사 → SVG(M/C/Z) 저장

주의 — 이 모듈은 docs/SVG_VECTORIZATION_VALIDATION.md 의 Potrace(영역 보존)
방식과 목적이 다르다. Potrace 는 잉크 면적을 감싸는 윤곽선(edge) 두 줄을
만들지만, extract_2d.py 는 heart.svg 처럼 붓이 지나간 "중심선 하나"를
전제로 한다. 그래서 여기서는 영역이 아니라 골격(skeleton)을 추적한다.

알려진 한계 (v1):
    - 선이 교차하는 지점(십자 교차 등)에서는 접선 방향으로 이어 붙이지
      않고, 교차점에서 각각 별도 획으로 끊는다. 도안 전체는 그대로
      보존되지만 "한 붓 그리기"였던 교차 도안은 여러 획으로 나뉜다.
      (교차가 없는 하트류 단순 도안에는 영향 없음)
    - 선 굵기·필압 정보는 버려진다 (로봇이 일정 깊이로 파므로 원래 불필요).
"""
import math
import os

import cv2
import networkx as nx
import numpy as np
from skimage.morphology import skeletonize

# ---------------------------------------------------------------------------
# 1) 이진화
# ---------------------------------------------------------------------------


def binarize(gray, invert=None):
    """Otsu 이진화로 전경(잉크) 마스크를 만든다.

    invert=None 이면 전경 픽셀이 절반을 넘을 때 자동으로 뒤집는다
    (일반적으로 잉크가 배경보다 적은 면적을 차지한다고 가정).
    """
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg = bw < 128
    if invert is True:
        fg = ~fg
    elif invert is None and fg.mean() > 0.5:
        fg = ~fg
    return fg


# ---------------------------------------------------------------------------
# 2) 골격화 + 그래프 추적
# ---------------------------------------------------------------------------
_NEI8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def skeleton_graph(skel):
    """골격 이진 이미지 -> networkx 그래프 (노드=(row,col) 픽셀, 8-연결 간선)."""
    ys, xs = np.nonzero(skel)
    nodes = set(zip(ys.tolist(), xs.tolist()))
    g = nx.Graph()
    g.add_nodes_from(nodes)
    for (y, x) in nodes:
        for dy, dx in _NEI8:
            q = (y + dy, x + dx)
            if q in nodes:
                g.add_edge((y, x), q)
    return g


def _merge_adjacent(nodes, g):
    """서로 붙어있는 노드 집합(분기점 뭉치)을 대표 노드 하나로 묶는다."""
    sub = g.subgraph(nodes)
    rep = {}
    for comp in nx.connected_components(sub):
        r = next(iter(comp))
        for n in comp:
            rep[n] = r
    return rep


def _path_length(path):
    return sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))


def trace_strokes(skel, spur_min_len_px=4.0):
    """골격에서 (점열, is_closed) 목록을 뽑는다."""
    g = skeleton_graph(skel)
    if g.number_of_nodes() < 2:
        return []

    deg = dict(g.degree())
    junctions = {n for n, d in deg.items() if d >= 3}
    endpoints = {n for n, d in deg.items() if d == 1}
    special = junctions | endpoints
    rep = _merge_adjacent(junctions, g)

    def rep_of(n):
        return rep.get(n, n)

    visited = set()
    edges = []  # (path 점열, endpoint 인접 여부 튜플)
    for s in special:
        for nb in g.neighbors(s):
            e = (s, nb)
            if e in visited or (nb, s) in visited:
                continue
            if s in junctions and nb in junctions and rep_of(s) == rep_of(nb):
                visited.add(e)
                continue
            path = [s, nb]
            visited.add(e)
            prev, cur = s, nb
            while cur not in special:
                nxts = [n for n in g.neighbors(cur) if n != prev]
                if not nxts:
                    break
                nxt = nxts[0]
                visited.add((cur, nxt))
                path.append(nxt)
                prev, cur = cur, nxt
            edges.append((path[0] in endpoints, path[-1] in endpoints, path))

    # 잔가지 정리: 한쪽만 끝점이고(=반대쪽은 분기점) 길이가 짧으면 버린다.
    kept = []  # [rep_a, rep_b, path]
    for path in [p for _, _, p in edges]:
        a_is_end, b_is_end = path[0] in endpoints, path[-1] in endpoints
        is_spur = a_is_end != b_is_end
        if is_spur and _path_length(path) < spur_min_len_px:
            continue
        kept.append([rep_of(path[0]), rep_of(path[-1]), path])

    # 잔가지를 지우고 나면 분기점에 정확히 두 조각만 남는 경우가 있다.
    # 그런 경우는 선택의 여지가 없으므로(=교차가 아니라 원래 이어진 선) 자동으로 이어 붙인다.
    # 세 조각 이상 남는 진짜 교차점은 v1 한계로 남겨두고 그대로 분리해 둔다.
    junction_reps = set(rep.values())
    changed = True
    while changed:
        changed = False
        touch = {}
        for idx, (ra, rb, _) in enumerate(kept):
            if ra in junction_reps:
                touch.setdefault(ra, []).append((idx, "a"))
            if rb in junction_reps:
                touch.setdefault(rb, []).append((idx, "b"))
        for node, arms in touch.items():
            if len(arms) != 2 or arms[0][0] == arms[1][0]:
                continue
            (i1, side1), (i2, side2) = arms
            ra1, rb1, p1 = kept[i1]
            ra2, rb2, p2 = kept[i2]
            # node 쪽 끝을 서로 맞대어 이어 붙인다.
            seg1 = p1 if side1 == "b" else p1[::-1]
            seg2 = p2 if side2 == "a" else p2[::-1]
            merged_path = seg1[:-1] + seg2
            new_a = ra1 if side1 == "b" else rb1
            new_b = rb2 if side2 == "a" else ra2
            for idx in sorted((i1, i2), reverse=True):
                kept.pop(idx)
            kept.append([new_a, new_b, merged_path])
            changed = True
            break

    kept = [path for _, _, path in kept]

    # special 노드를 하나도 거치지 않는 순수 폐곡선(고리)
    touched = {p for path in kept for p in path} | special
    remaining = set(g.nodes()) - touched
    for comp in nx.connected_components(g.subgraph(remaining)):
        if len(comp) < 3:
            continue
        sub = g.subgraph(comp)
        start = next(iter(comp))
        order = list(nx.dfs_preorder_nodes(sub, start))
        kept.append(order + [order[0]])

    strokes = []
    min_stroke_len_px = spur_min_len_px * 1.5
    for path in kept:
        if _path_length(path) < min_stroke_len_px:
            # 뾰족한 오목 모서리에서 세선화가 만드는 아주 작은 고리·조각(잡음).
            # 실제 획이 아니라 골격화 부작용이라 실질적인 최소 길이 미만은 버린다.
            continue
        is_closed = path[0] == path[-1] or math.dist(path[0], path[-1]) < 1.5
        pts = [(float(x), float(y)) for (y, x) in path]  # (row,col) -> (x,y)
        strokes.append((pts, is_closed))
    return strokes


# ---------------------------------------------------------------------------
# 3) Schneider 최소제곱 베지어 근사 (Graphics Gems FitCurves.c 원리)
# ---------------------------------------------------------------------------


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, s):
    return (a[0] * s, a[1] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _norm(a):
    n = math.hypot(a[0], a[1])
    return (a[0] / n, a[1] / n) if n > 1e-12 else (0.0, 0.0)


def _bezier_point(ctrl, t):
    u = 1 - t
    b0, b1, b2, b3 = u**3, 3 * u * u * t, 3 * u * t * t, t**3
    x = b0 * ctrl[0][0] + b1 * ctrl[1][0] + b2 * ctrl[2][0] + b3 * ctrl[3][0]
    y = b0 * ctrl[0][1] + b1 * ctrl[1][1] + b2 * ctrl[2][1] + b3 * ctrl[3][1]
    return (x, y)


def _chord_length_parameterize(pts):
    u = [0.0]
    for i in range(1, len(pts)):
        u.append(u[-1] + math.dist(pts[i], pts[i - 1]))
    total = u[-1] if u[-1] > 1e-12 else 1.0
    return [v / total for v in u]


def _generate_bezier(pts, u, t1, t2):
    p0, p3 = pts[0], pts[-1]
    n = len(pts)
    a = []
    for i in range(n):
        ui = u[i]
        b1 = 3 * (1 - ui) ** 2 * ui
        b2 = 3 * (1 - ui) * ui * ui
        a.append((_mul(t1, b1), _mul(t2, b2)))

    c = [[0.0, 0.0], [0.0, 0.0]]
    x = [0.0, 0.0]
    for i in range(n):
        c[0][0] += _dot(a[i][0], a[i][0])
        c[0][1] += _dot(a[i][0], a[i][1])
        c[1][0] = c[0][1]
        c[1][1] += _dot(a[i][1], a[i][1])
        ui = u[i]
        b0 = (1 - ui) ** 3
        b1 = 3 * (1 - ui) ** 2 * ui
        b2 = 3 * (1 - ui) * ui * ui
        b3 = ui**3
        shortfall = _sub(pts[i], _add(_mul(p0, b0 + b1), _mul(p3, b2 + b3)))
        x[0] += _dot(a[i][0], shortfall)
        x[1] += _dot(a[i][1], shortfall)

    det_c0_c1 = c[0][0] * c[1][1] - c[1][0] * c[0][1]
    det_c0_x = c[0][0] * x[1] - c[1][0] * x[0]
    det_x_c1 = x[0] * c[1][1] - x[1] * c[0][1]
    alpha_l = 0.0 if abs(det_c0_c1) < 1e-12 else det_x_c1 / det_c0_c1
    alpha_r = 0.0 if abs(det_c0_c1) < 1e-12 else det_c0_x / det_c0_c1

    seg_len = math.dist(p0, p3)
    eps = 1.0e-6 * seg_len
    if alpha_l < eps or alpha_r < eps or seg_len < 1e-12:
        dist = seg_len / 3.0
        p1 = _add(p0, _mul(t1, dist))
        p2 = _add(p3, _mul(t2, dist))
    else:
        p1 = _add(p0, _mul(t1, alpha_l))
        p2 = _add(p3, _mul(t2, alpha_r))
    return (p0, p1, p2, p3)


def _compute_max_error(pts, u, bez):
    max_err, split = 0.0, len(pts) // 2
    for i, p in enumerate(pts):
        d2 = math.dist(p, _bezier_point(bez, u[i]))
        if d2 > max_err:
            max_err, split = d2, i
    return max_err, split


def _reparameterize(pts, u, bez):
    out = []
    for i, p in enumerate(pts):
        out.append(_newton_raphson_u(bez, p, u[i]))
    return out


def _bezier_deriv(ctrl, t, order=1):
    pts = ctrl
    for _ in range(order):
        pts = [_sub(pts[i + 1], pts[i]) for i in range(len(pts) - 1)]
        pts = [_mul(p, len(pts)) for p in pts]
    return _bezier_point_generic(pts, t)


def _bezier_point_generic(ctrl, t):
    pts = list(ctrl)
    while len(pts) > 1:
        pts = [_add(_mul(pts[i], 1 - t), _mul(pts[i + 1], t)) for i in range(len(pts) - 1)]
    return pts[0]


def _newton_raphson_u(bez, p, u):
    q = _bezier_point(bez, u)
    q1 = _bezier_deriv(list(bez), u, 1)
    q2 = _bezier_deriv(list(bez), u, 2)
    num = _dot(_sub(q, p), q1)
    den = _dot(q1, q1) + _dot(_sub(q, p), q2)
    return u if abs(den) < 1e-12 else u - num / den


def _left_tangent(pts):
    return _norm(_sub(pts[1], pts[0])) if len(pts) > 1 else (0.0, 0.0)


def _right_tangent(pts):
    return _norm(_sub(pts[-2], pts[-1])) if len(pts) > 1 else (0.0, 0.0)


def _center_tangent(pts, i):
    v = _sub(pts[i - 1], pts[i + 1]) if 0 < i < len(pts) - 1 else (0.0, 0.0)
    return _norm(v)


def _fit_cubic(pts, t1, t2, error, depth=0, max_depth=24):
    if len(pts) == 2 or depth >= max_depth:
        dist = math.dist(pts[0], pts[-1]) / 3.0
        p1 = _add(pts[0], _mul(t1, dist))
        p2 = _add(pts[-1], _mul(t2, dist))
        return [(pts[0], p1, p2, pts[-1])]

    u = _chord_length_parameterize(pts)
    bez = _generate_bezier(pts, u, t1, t2)
    max_err, split = _compute_max_error(pts, u, bez)
    if max_err < error:
        return [bez]

    if max_err < error * 4:
        for _ in range(4):
            u = _reparameterize(pts, u, bez)
            bez = _generate_bezier(pts, u, t1, t2)
            max_err, split = _compute_max_error(pts, u, bez)
            if max_err < error:
                return [bez]

    if split < 1:
        split = 1
    if split > len(pts) - 2:
        split = len(pts) - 2
    t_center = _center_tangent(pts, split)
    left = _fit_cubic(pts[: split + 1], t1, t_center, error, depth + 1, max_depth)
    right = _fit_cubic(pts[split:], _mul(t_center, -1.0), t2, error, depth + 1, max_depth)
    return left + right


def fit_curve(points, error_px):
    """점열(중복 제거된 (x,y) 리스트) -> 3차 베지어 목록 [(p0,p1,p2,p3), ...]."""
    pts = [points[0]]
    for p in points[1:]:
        if math.dist(pts[-1], p) > 1e-9:
            pts.append(p)
    if len(pts) < 2:
        return []
    if len(pts) == 2:
        return _fit_cubic(pts, _left_tangent(pts), _right_tangent(pts), error_px)
    t1 = _left_tangent(pts)
    t2 = _right_tangent(pts)
    return _fit_cubic(pts, t1, t2, error_px)


# ---------------------------------------------------------------------------
# 4) SVG 조립
# ---------------------------------------------------------------------------


def _fmt(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if "." in f"{v:.3f}" else f"{v:.3f}"


def beziers_to_path_d(beziers, closed):
    if not beziers:
        return ""
    p0 = beziers[0][0]
    d = [f"M {_fmt(p0[0])},{_fmt(p0[1])}"]
    for (_, c1, c2, p3) in beziers:
        d.append(f"C {_fmt(c1[0])},{_fmt(c1[1])} {_fmt(c2[0])},{_fmt(c2[1])} {_fmt(p3[0])},{_fmt(p3[1])}")
    if closed:
        d.append("Z")
    return " ".join(d)


def convert(image_path, spur_min_len_px=4.0, fit_error_px=0.6, invert=None,
            max_pixels=16_000_000, max_side_px=6000, max_foreground_pixels=1_000_000,
            source_name=None):
    """이미지 파일 -> (svg_text, stats).

    fit_error_px: Schneider 근사 허용 오차(px). 팀 검증값(허용거리 0.5px)에
    맞춘 기본값이다.
    """
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")
    h, w = gray.shape
    source_name = source_name or os.path.basename(image_path)
    if h * w > max_pixels or max(h, w) > max_side_px:
        raise ValueError("이미지는 16MP 이하이고 한 변이 6000px 이하여야 합니다.")

    fg = binarize(gray, invert=invert)
    foreground_pixels = int(np.count_nonzero(fg))
    if foreground_pixels > max_foreground_pixels:
        raise ValueError("전경 픽셀이 너무 많아 안전한 시간 안에 중심선을 만들 수 없습니다.")
    skel = skeletonize(fg)

    raw_strokes = trace_strokes(skel, spur_min_len_px=spur_min_len_px)
    if not raw_strokes:
        raise ValueError("골격에서 획을 찾지 못했습니다 (빈 이미지이거나 임계값이 안 맞습니다).")

    paths = []
    stroke_stats = []
    for pts, is_closed in raw_strokes:
        if len(pts) < 2:
            continue
        beziers = fit_curve(pts, fit_error_px)
        if not beziers:
            continue
        paths.append(beziers_to_path_d(beziers, is_closed))
        stroke_stats.append({"point_count": len(pts), "bezier_count": len(beziers), "closed": is_closed})

    body = "\n  ".join(f'<path fill="none" stroke="#000" stroke-width="1" d="{d}" />' for d in paths)
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!-- image_to_svg.py 자동 생성 ({w}x{h}px). '
        "세선화 기반 중심선 변환 (docs/ALGORITHM_VALIDATION.md 3차 조합). -->\n"
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n  '
        f"{body}\n</svg>\n"
    )
    stats = {
        "source_image": source_name,
        "image_size_px": [w, h],
        "foreground_pixels": foreground_pixels,
        "stroke_count": len(paths),
        "strokes": stroke_stats,
        "spur_min_len_px": spur_min_len_px,
        "fit_error_px": fit_error_px,
    }
    return svg, stats
