#!/usr/bin/env python3
"""generate_path.py — 3D 획을 실행 경로(path.json)로 만든다.

적용한 결정 (2026-09-19 최종 조합):
  - 2D 순서를 초기해로 쓰고, **안전비용 NN+2-opt** 로 다시 정렬한다.
    비용: 비접촉 이동 호 길이 + 자세 변화 + seam 근접 + 큰 둘레 회전 + 승강 횟수.
  - 옆면 밖 이동·원통 내부 통과·clearance 미달·금지 영역·설정 불일치는
    **비용이 아니라 금지 조건**으로 다룬다 (후보에서 제외). 로봇 작업 범위(높이 구간·도달각)는
    여기서 다루지 않는다 — 생성은 옆면 전체에서 하고 범위 점검은 execution_readiness 가 한다 (9/21).
  - 획 사이 TRAVEL 은 직선 chord 가 아니라 **반지름 R+clearance 인 오프셋 원통 위**
    에서 만든다. 자유공간 직선 이동은 쓰지 않는다.
  - CUT segment 는 최대 점 수로 나누되 경계점을 공유한다.
  - 출력 waypoint 는 로봇팀(engraving.py·joint_check.py) 형식 [x, y, z, qx, qy, qz, qw] 이다
    (2026-09-20, 세은님 답변에 따라 c2_path 가 맞춤). 내부 계산은 dict 로 하고
    파일로 내보내기 직전에 한 번만 변환한다.
"""
import math
import time

import numpy as np

from . import ordering
from . import workcell as wc

# 안전비용 가중치. 근거: 획당 힘 프로브(접근 6mm를 1.5mm/s + 정착)가 사이클의
# 대부분을 차지하고(측정 기준 약 75%), 비접촉 이동은 3% 남짓이다. 그래서 이동 거리
# 자체보다 자세 변화·둘레 회전처럼 재접근을 어렵게 만드는 항에 더 무게를 둔다.
# 승강 횟수는 획 수가 고정이면 순서와 무관한 상수라 정렬에는 영향이 없다(기록만 한다).
COST_WEIGHTS = {
    "travel_arc_m": 1.0,        # 오프셋 원통 위 이동 호 길이 (m)
    "orientation_deg": 0.002,   # 자세 변화 1도당 (m 환산)
    "theta_turn_deg": 0.004,    # 둘레 회전 1도당 — J6 감김 억제
    "seam_proximity": 0.05,     # 이음매 근처를 지나는 이동에 붙는 벌점
    "lift": 0.0,                # 승강 1회당 (획 수 고정 시 상수)
}
SEAM_GUARD_DEG = 10.0           # 이음매에서 이 각도 안쪽을 지나면 벌점


# ---------------------------------------------------------------------------
# 금지 조건 (비용이 아니라 하드 제약)
# ---------------------------------------------------------------------------
def forbidden_reasons(theta_a, h_a, theta_b, h_b, clearance_m):
    """이 이동이 금지 조건을 어기면 이유 목록을 돌려준다."""
    bad = []
    lo, hi = wc.current_surface().height_range_m
    for h in (h_a, h_b):
        if not (lo - 1e-9 <= h <= hi + 1e-9):
            bad.append("HEIGHT_OUT_OF_SURFACE")
            break
    # 오프셋 원통 위를 따라가므로 반지름은 항상 R+clearance -> 내부 통과·clearance 미달 없음.
    if clearance_m < wc.CLEARANCE_STROKE_M - 1e-9:
        bad.append("CLEARANCE_TOO_SMALL")
    # 이동이 이음매를 지나는지 (표면 밖이라 금지는 아니지만 기록)
    return bad


# ---------------------------------------------------------------------------
# 오프셋 원통 위 TRAVEL
# ---------------------------------------------------------------------------
def travel_waypoints(theta_a, h_a, theta_b, h_b, clearance_m, max_step_m=None):
    """반지름 R+clearance 인 원통 표면을 따라가는 이동 점열.

    직선 현으로 이으면 각도차가 커질 때 원통을 뚫는다
    (clearance 10mm 기준 78.8도가 한계). 그래서 theta·height 를 함께 보간한다.
    """
    max_step_m = max_step_m or (wc.WAYPOINT_SPACING_MAX_M * 3.0)
    r = wc.current_surface().radius_m + clearance_m
    d_theta = theta_b - theta_a
    arc = abs(math.radians(d_theta)) * r
    dz = abs(h_b - h_a)
    length = math.hypot(arc, dz)
    n = max(1, int(math.ceil(length / max_step_m)))
    out = []
    for k in range(n + 1):
        t = k / n
        th = theta_a + d_theta * t
        h = h_a + (h_b - h_a) * t
        out.append((th, h))
    return out


def _wp(theta, h, clearance_m, quat=None):
    p = wc.offset_point(theta, h, clearance_m) if clearance_m > 0 else wc.surface_point(theta, h)
    q = quat if quat is not None else wc.tool_orientation(theta)
    return {
        "position_m": {"x": round(p[0], 6), "y": round(p[1], 6), "z": round(p[2], 6)},
        "orientation_xyzw": {"x": round(q[0], 6), "y": round(q[1], 6),
                             "z": round(q[2], 6), "w": round(q[3], 6)},
    }


# ---------------------------------------------------------------------------
# 안전비용 정렬
# ---------------------------------------------------------------------------
def _ends(stroke):
    w0, w1 = stroke["waypoints"][0], stroke["waypoints"][-1]
    return (w0["theta_deg"], w0["height_m"]), (w1["theta_deg"], w1["height_m"])


def _quat_of(stroke, at_end):
    w = stroke["waypoints"][-1 if at_end else 0]["orientation_xyzw"]
    return (w["x"], w["y"], w["z"], w["w"])


def move_cost(a_stroke, b_stroke, clearance_m):
    """획 a 끝 -> 획 b 시작 이동의 안전비용. 금지면 None."""
    _, a_end = _ends(a_stroke)
    b_start, _ = _ends(b_stroke)
    if forbidden_reasons(a_end[0], a_end[1], b_start[0], b_start[1], clearance_m):
        return None
    r = wc.current_surface().radius_m + clearance_m
    d_theta = abs(b_start[0] - a_end[0])
    arc = math.radians(d_theta) * r
    dz = abs(b_start[1] - a_end[1])
    travel = math.hypot(arc, dz)
    ori = wc.quat_angle_deg(_quat_of(a_stroke, True), _quat_of(b_stroke, False))
    seam_pen = 0.0
    lo, hi = min(a_end[0], b_start[0]), max(a_end[0], b_start[0])
    if wc.seams_strictly_between(lo - SEAM_GUARD_DEG, hi + SEAM_GUARD_DEG):
        seam_pen = 1.0            # 이음매(−X, 로봇 쪽) 근처를 지나는 이동
    w = COST_WEIGHTS
    return (w["travel_arc_m"] * travel + w["orientation_deg"] * ori
            + w["theta_turn_deg"] * d_theta + w["seam_proximity"] * seam_pen + w["lift"])


def move_cost_matrix(strokes, clearance_m):
    """모든 (획 a 끝 -> 획 b 시작) 이동의 안전비용 행렬. 금지는 inf, 대각선은 inf (자기 자신으로는 가지 않음).

    `move_cost()` 와 같은 식을 numpy 로 한 번에 계산한다 (test_ordering.py 가 두 결과를 대조한다).
    """
    n = len(strokes)
    end_t = np.empty(n); end_h = np.empty(n); start_t = np.empty(n); start_h = np.empty(n)
    end_q = np.empty((n, 4)); start_q = np.empty((n, 4))
    for k, stroke in enumerate(strokes):
        (start_t[k], start_h[k]), (end_t[k], end_h[k]) = _ends(stroke)
        start_q[k] = _quat_of(stroke, False)
        end_q[k] = _quat_of(stroke, True)
    r = wc.current_surface().radius_m + clearance_m
    d_theta = np.abs(start_t[None, :] - end_t[:, None])                 # [a, b]
    travel = np.hypot(np.radians(d_theta) * r, np.abs(start_h[None, :] - end_h[:, None]))
    dot = np.abs(end_q @ start_q.T)
    ori = np.degrees(2.0 * np.arccos(np.minimum(1.0, dot)))
    guard = SEAM_GUARD_DEG
    lo = np.minimum(end_t[:, None], start_t[None, :]) - guard
    hi = np.maximum(end_t[:, None], start_t[None, :]) + guard
    seam_deg = wc.current_surface().seam_angle_deg
    first_seam = seam_deg + 360.0 * (np.floor((lo - seam_deg) / 360.0) + 1.0)
    seam_pen = np.where(first_seam < hi, 1.0, 0.0)
    w = COST_WEIGHTS
    cost = (w["travel_arc_m"] * travel + w["orientation_deg"] * ori
            + w["theta_turn_deg"] * d_theta + w["seam_proximity"] * seam_pen + w["lift"])
    s_lo, s_hi = wc.current_surface().height_range_m
    bad_h = lambda h: ~((s_lo - 1e-9 <= h) & (h <= s_hi + 1e-9))       # noqa: E731
    forbidden = bad_h(end_h)[:, None] | bad_h(start_h)[None, :]
    if clearance_m < wc.CLEARANCE_STROKE_M - 1e-9:
        forbidden = np.ones((n, n), dtype=bool)
    cost = np.where(forbidden, np.inf, cost)
    np.fill_diagonal(cost, np.inf)
    return cost


def order_safety_cost(strokes, clearance_m, initial_order=None, max_pass=50,
                      on_progress=None, should_stop=None):
    """2D 순서를 초기해로 받아 안전비용 NN + 2-opt 로 다시 정렬한다.

    비용 행렬과 접두합으로 계산해 획이 수백 개여도 빠르다. 같은 입력이면 이전의 전체 재계산 구현과
    같은 순서를 돌려준다. on_progress(0~1) 는 이 단계 안의 진행률이고, should_stop() 이 True 면
    개선만 멈추고 지금 순서를 쓴다 (획은 하나도 빠지지 않는다).
    """
    notify = on_progress or (lambda _fraction: None)
    n = len(strokes)
    if n <= 1:
        return list(range(n)), {"reordered": False, "cost_initial": 0.0, "cost_final": 0.0,
                                "two_opt_improvements": 0, "forbidden_pairs": 0,
                                "two_opt_stopped_early": False}

    cost = move_cost_matrix(strokes, clearance_m)
    forbidden = int(np.isinf(cost).sum()) - n           # 대각선 n개는 제외
    init = list(initial_order) if initial_order else list(range(n))
    cost_init = ordering.sequential_cost(np.asarray(init), cost)

    # NN (안전비용 기준). 같은 비용이면 번호가 작은 획을 고른다 (이전 구현의 min((비용, 번호)) 와 같음).
    unused = np.ones(n, dtype=bool)
    nn = [init[0]]
    unused[init[0]] = False
    last_poll = time.monotonic()
    while unused.any():
        row = np.where(unused, cost[nn[-1]], np.inf)
        j = int(np.argmin(row))
        if not np.isfinite(row[j]):
            nn.extend(int(k) for k in np.flatnonzero(unused))
            break
        nn.append(j)
        unused[j] = False
        if time.monotonic() - last_poll >= 0.2:
            last_poll = time.monotonic()
            notify(0.3 * len(nn) / n)

    nn_cost = ordering.sequential_cost(np.asarray(nn), cost)
    best = nn if nn_cost < cost_init else init
    order, best_cost, moves, stopped = ordering.two_opt(
        best, cost, max_pass=max_pass, min_n=3,
        on_progress=lambda f: notify(0.3 + 0.7 * f), should_stop=should_stop)
    notify(1.0)
    return order, {"reordered": order != init, "cost_initial": round(cost_init, 6),
                   "cost_final": round(best_cost, 6), "two_opt_improvements": moves,
                   "forbidden_pairs": forbidden, "two_opt_stopped_early": bool(stopped)}


# ---------------------------------------------------------------------------
def to_robot_waypoint(w):
    """내부 dict waypoint -> 로봇팀 형식 [x, y, z, qx, qy, qz, qw]."""
    p, o = w["position_m"], w["orientation_xyzw"]
    return wc.to_pose7((p["x"], p["y"], p["z"]), (o["x"], o["y"], o["z"], o["w"]))


# ---------------------------------------------------------------------------
def chunk(points, max_points):
    if len(points) <= max_points:
        return [points]
    out, i = [], 0
    while i < len(points) - 1:
        j = min(i + max_points - 1, len(points) - 1)
        out.append(points[i:j + 1])
        i = j
    return out


def build(mapped, path_id, path_version, asset_id, asset_sha256,
          snapshot_id, profile_sha256, source_mode="SIMULATION", on_progress=None, should_stop=None,
          real_preview=None, real_execution=None, conversion_config=None):
    """on_progress(0~1): 이 단계 안의 진행률 (정렬 0~0.5, 구간 조립 0.5~1). 예외는 그대로 전파한다.

    real_preview: REAL 추정값 미리보기 전용 경로의 출처 표시.
    real_execution: 준비·측정 스냅샷에 연결된 REAL 실행 후보 경로의 출처 표시.
    두 값은 동시에 줄 수 없다."""
    if real_preview is not None and real_execution is not None:
        raise ValueError("REAL 미리보기와 실행 후보 표시는 동시에 사용할 수 없습니다.")
    if not mapped:
        raise ValueError("EMPTY_PATH: 매핑된 3D 획이 없습니다.")
    notify = on_progress or (lambda _fraction: None)
    order, order_stats = order_safety_cost(mapped, wc.CLEARANCE_STROKE_M,
                                           initial_order=list(range(len(mapped))),
                                           on_progress=lambda f: notify(0.5 * f),
                                           should_stop=should_stop)
    strokes = [mapped[i] for i in order]

    segments, n = [], 0

    def sid():
        nonlocal n
        n += 1
        return f"seg-{n:04d}"

    cut_len = travel_len = 0.0
    prev_end = None   # (theta, h, clearance)

    last_poll = time.monotonic()
    for k, st in enumerate(strokes):
        if time.monotonic() - last_poll >= 0.2:
            last_poll = time.monotonic()
            notify(0.5 + 0.5 * k / len(strokes))
        first = st["waypoints"][0]
        last = st["waypoints"][-1]
        t0, h0 = first["theta_deg"], first["height_m"]
        t1, h1 = last["theta_deg"], last["height_m"]
        appr_c = wc.CLEARANCE_FIRST_LAST_M if k == 0 else wc.CLEARANCE_STROKE_M
        retr_c = wc.CLEARANCE_FIRST_LAST_M if k == len(strokes) - 1 else wc.CLEARANCE_STROKE_M

        # TRAVEL: 오프셋 원통 위를 따라 이동
        if prev_end is not None:
            pt, ph, pc = prev_end
            tv = travel_waypoints(pt, ph, t0, h0, pc)
            quats = wc.make_continuous([wc.tool_orientation(t) for t, _ in tv])
            wps = [_wp(t, h, pc, q) for (t, h), q in zip(tv, quats)]
            for a, b in zip(wps, wps[1:]):
                travel_len += math.dist((a["position_m"]["x"], a["position_m"]["y"], a["position_m"]["z"]),
                                        (b["position_m"]["x"], b["position_m"]["y"], b["position_m"]["z"]))
            segments.append({"segment_id": sid(), "stroke_id": None, "kind": "TRAVEL",
                             "motion_profile_id": wc.MOTION_PROFILE["travel"],
                             "surface": "offset_cylinder",
                             "clearance_m": pc, "waypoints": wps})
            # 이동 끝 clearance 가 접근 clearance 와 다르면 반경만 맞춰준다
            if abs(pc - appr_c) > 1e-9:
                q = wc.tool_orientation(t0)
                segments.append({"segment_id": sid(), "stroke_id": None, "kind": "TRAVEL",
                                 "motion_profile_id": wc.MOTION_PROFILE["travel"],
                                 "surface": "radial", "clearance_m": appr_c,
                                 "waypoints": [_wp(t0, h0, pc, q), _wp(t0, h0, appr_c, q)]})

        # APPROACH: 오프셋 원통 -> 표면
        q0 = (first["orientation_xyzw"]["x"], first["orientation_xyzw"]["y"],
              first["orientation_xyzw"]["z"], first["orientation_xyzw"]["w"])
        segments.append({"segment_id": sid(), "stroke_id": st["stroke_id"], "kind": "APPROACH",
                         "motion_profile_id": wc.MOTION_PROFILE["approach"],
                         "clearance_m": appr_c,
                         "waypoints": [_wp(t0, h0, appr_c, q0),
                                       {"position_m": first["position_m"],
                                        "orientation_xyzw": first["orientation_xyzw"]}]})

        # CUT
        pts = [{"position_m": w["position_m"], "orientation_xyzw": w["orientation_xyzw"]}
               for w in st["waypoints"]]
        for a, b in zip(pts, pts[1:]):
            cut_len += math.dist((a["position_m"]["x"], a["position_m"]["y"], a["position_m"]["z"]),
                                 (b["position_m"]["x"], b["position_m"]["y"], b["position_m"]["z"]))
        chunks = chunk(pts, wc.SEGMENT_POINTS_MAX)
        for ci, ch in enumerate(chunks):
            seg = {"segment_id": sid(), "stroke_id": st["stroke_id"], "kind": "CUT",
                   "motion_profile_id": wc.MOTION_PROFILE["cut"], "waypoints": ch}
            if len(chunks) > 1:
                seg["chunk_index"], seg["chunk_count"] = ci, len(chunks)
            for key in ("split_from_stroke_id", "split_index", "split_count", "join_forbidden"):
                if key in st:
                    seg[key] = st[key]
            segments.append(seg)

        # RETRACT: 표면 -> 오프셋 원통
        q1 = (last["orientation_xyzw"]["x"], last["orientation_xyzw"]["y"],
              last["orientation_xyzw"]["z"], last["orientation_xyzw"]["w"])
        segments.append({"segment_id": sid(), "stroke_id": st["stroke_id"], "kind": "RETRACT",
                         "motion_profile_id": wc.MOTION_PROFILE["retract"],
                         "clearance_m": retr_c,
                         "waypoints": [{"position_m": last["position_m"],
                                        "orientation_xyzw": last["orientation_xyzw"]},
                                       _wp(t1, h1, retr_c, q1)]})
        prev_end = (t1, h1, retr_c)

    # 내보내기: waypoint 를 로봇팀 형식으로 한 번에 변환
    for seg in segments:
        seg["waypoints"] = [to_robot_waypoint(w) for w in seg["waypoints"]]

    execution_candidate = real_execution is not None
    path = {
        "schema_version": wc.PATH_SCHEMA_VERSION,
        "path_id": path_id,
        "path_version": path_version,
        "test_only": not execution_candidate,
        "source_mode": source_mode,
        # engraving.py 가 최상위에서 읽는 값들 (validate_path, schema v2)
        "tool_id": wc.TOOL_ID,
        "frame_id": wc.FRAME_ID,
        "position_unit": "m",
        "orientation": "quaternion_xyzw",
        "input": {"asset_id": asset_id, "asset_sha256": asset_sha256},
        "config": {
            "profile_snapshot_id": snapshot_id,
            "profile_sha256": profile_sha256,
            "workcell_id": wc.WORKCELL_ID, "workcell_version": wc.WORKCELL_VERSION,
            "tools_config_id": wc.TOOLS_CONFIG_ID, "tools_config_version": wc.TOOLS_CONFIG_VERSION,
            "tool_id": wc.TOOL_ID, "tool_version": wc.TOOL_VERSION,
            "tcp_profile_id": wc.TCP_PROFILE_ID, "tcp_profile_version": wc.TCP_PROFILE_VERSION,
            "load_profile_id": wc.LOAD_PROFILE_ID, "load_profile_version": wc.LOAD_PROFILE_VERSION,
        },
        "segments": segments,
    }
    if conversion_config is not None:
        path["config"]["conversion"] = dict(conversion_config)
    if real_preview is not None:
        path["config"]["real_preview"] = dict(real_preview)
    if real_execution is not None:
        path["real_execution_allowed"] = True
        path["preparation_id"] = real_execution["preparation_id"]
        path["measurement_id"] = real_execution["measurement_id"]
        path["config"]["test_only"] = False
        path["config"]["real_execution_allowed"] = True
        path["config"]["real_execution"] = dict(real_execution)
    stats = {
        "segment_count": len(segments),
        "waypoint_count": sum(len(s["waypoints"]) for s in segments),
        "cut_length_m": round(cut_len, 6),
        "travel_length_m": round(travel_len, 6),
        "cut_segments": sum(1 for s in segments if s["kind"] == "CUT"),
        "travel_segments": sum(1 for s in segments if s["kind"] == "TRAVEL"),
        "lift_count": len(strokes),
        "ordering": order_stats,
        "cost_weights": COST_WEIGHTS,
    }
    return path, stats
