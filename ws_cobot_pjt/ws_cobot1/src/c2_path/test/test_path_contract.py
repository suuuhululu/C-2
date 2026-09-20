#!/usr/bin/env python3
"""test_path_contract.py — 생성된 실행 경로가 계약·안전 제약을 지키는지 검사한다.

로봇·ROS·네트워크를 쓰지 않는다. 생성 모듈과 저장된 샘플만 본다.
검사 근거:
  - c2_interfaces/action/GeneratePath.action (main 병합, 2026-09-19)
  - docs/INTERFACE_RECOMMENDATION.md 3·4절
  - c2_process/engraving.py 가 읽는 필드와 waypoint 형식 [x,y,z,qx,qy,qz,qw], schema_version 2
    (2026-09-20 로봇팀 형식으로 통일)
  - 시율님 실기 확정값: 획당 둘레 각도 180도 이내, 이음매 미통과, 작업 높이 윗면 아래 20~65mm
"""
import json
import math
import os
import re
import sys
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from c2_path import extract_2d, generate_path, image_to_svg, map_3d, optimize_2d, workcell as wc  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
SAMPLE_NAMES = ("heart", "heart_pair", "heart_seam")

# engraving.py 가 path 최상위에서 읽는 필드 (PR #25 기준)
ENGRAVING_TOP_LEVEL = ("schema_version", "position_unit", "orientation", "frame_id",
                       "source_mode", "tool_id")

_SVG_PATH_D = re.compile(r"<path[^>]*\sd=\"([^\"]+)\"")
_SVG_D_LETTERS = re.compile(r"[A-Za-z]")


def _rasterize_polyline(points, closed, size=400, thickness=3, margin=0.1):
    """점열(임의 단위)을 size x size 흑백 이미지로 그린다 (image_to_svg.py 입력용)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny, 1e-6)
    scale = (1 - 2 * margin) * size / span
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    img = np.full((size, size), 255, np.uint8)
    poly = np.array([[int(size / 2 + (x - cx) * scale), int(size / 2 + (y - cy) * scale)]
                     for x, y in points], np.int32)
    cv2.polylines(img, [poly], isClosed=closed, color=0, thickness=thickness, lineType=cv2.LINE_AA)
    return img


def _heart_centerline_points():
    svg = open(os.path.join(SAMPLES, "heart.svg"), encoding="utf-8").read()
    subs = extract_2d.parse_svg_subpaths(svg)
    return extract_2d.subpath_to_points(subs[0], chord_tol=0.05, max_step=0.5)


def load(name):
    with open(os.path.join(SAMPLES, name, "path.json"), encoding="utf-8") as f:
        return json.load(f)


def pos(w):
    """로봇팀 waypoint [x, y, z, qx, qy, qz, qw] 의 위치."""
    return (w[0], w[1], w[2])


def quat(w):
    return (w[3], w[4], w[5], w[6])


def radial(p):
    return math.hypot(p[0] - wc.AXIS_ORIGIN_XY_M[0], p[1] - wc.AXIS_ORIGIN_XY_M[1])


def theta_of(p):
    return math.degrees(math.atan2(p[1] - wc.AXIS_ORIGIN_XY_M[1], p[0] - wc.AXIS_ORIGIN_XY_M[0]))


def height_of(p):
    return p[2] - wc.AXIS_ORIGIN_Z_M


def unwrap(seq):
    out, acc = [seq[0]], 0.0
    for k in range(1, len(seq)):
        d = seq[k] - seq[k - 1]
        if d > 180.0:
            acc -= 360.0
        elif d < -180.0:
            acc += 360.0
        out.append(seq[k] + acc)
    return out


class TestPathFileContract(unittest.TestCase):
    """path.json 이 계약 형식을 지키는가."""

    def test_top_level_fields_engraving_reads(self):
        """engraving.py 가 최상위에서 읽는 필드가 다 있어야 한다.
        없으면 도구 대조 같은 검사가 조용히 건너뛰어진다."""
        for name in SAMPLE_NAMES:
            p = load(name)
            for key in ENGRAVING_TOP_LEVEL:
                self.assertIn(key, p, f"{name}: 최상위 {key} 없음")
            self.assertEqual(p["position_unit"], "m")
            self.assertEqual(p["orientation"], "quaternion_xyzw")
            self.assertEqual(p["frame_id"], wc.FRAME_ID)
            self.assertEqual(p["tool_id"], wc.TOOL_ID)

    def test_schema_version_matches_robot_team(self):
        """engraving.py 는 schema_version 2 만 받는다 (v1 은 묵시 변환 없이 거절)."""
        for name in SAMPLE_NAMES:
            self.assertEqual(load(name)["schema_version"], 2, f"{name}: schema_version")
            self.assertEqual(wc.PATH_SCHEMA_VERSION, 2)

    def test_waypoints_are_robot_pose7(self):
        """모든 waypoint 는 유한한 수 7개 [x,y,z,qx,qy,qz,qw] (engraving.py·joint_check.py 형식)."""
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                for k, w in enumerate(s["waypoints"]):
                    self.assertIsInstance(w, list, f"{name}/{s['segment_id']}[{k}] 리스트 아님")
                    self.assertEqual(len(w), 7, f"{name}/{s['segment_id']}[{k}] 값 {len(w)}개")
                    for c in w:
                        self.assertIsInstance(c, (int, float))
                        self.assertTrue(math.isfinite(c))

    def test_validator_rejects_old_dict_waypoint(self):
        """이전 dict 형식이 섞이면 검증이 실패해야 한다 (조용히 통과 금지)."""
        from c2_path import validate_path
        p = load("heart")
        w = p["segments"][0]["waypoints"][0]
        p["segments"][0]["waypoints"][0] = {
            "position_m": {"x": w[0], "y": w[1], "z": w[2]},
            "orientation_xyzw": {"x": w[3], "y": w[4], "z": w[5], "w": w[6]}}
        rep = validate_path.validate(p)
        self.assertFalse(rep["passed"])
        self.assertTrue(any(e.startswith("WAYPOINT_FORMAT") for e in rep["errors"]))

    def test_validator_rejects_schema_v1(self):
        from c2_path import validate_path
        p = load("heart")
        p["schema_version"] = 1
        rep = validate_path.validate(p)
        self.assertFalse(rep["passed"])
        self.assertTrue(any(e.startswith("UNSUPPORTED_SCHEMA_VERSION") for e in rep["errors"]))

    def test_config_block_has_recommendation_4_fields(self):
        """권장안 4절 '설정' 영역: 스냅샷·workcell·tool·TCP·하중."""
        need = ("profile_snapshot_id", "profile_sha256", "workcell_id", "workcell_version",
                "tools_config_id", "tools_config_version", "tool_id", "tool_version",
                "tcp_profile_id", "tcp_profile_version", "load_profile_id", "load_profile_version")
        for name in SAMPLE_NAMES:
            cfg = load(name)["config"]
            for key in need:
                self.assertIn(key, cfg, f"{name}: config.{key} 없음")

    def test_no_self_hash_inside_file(self):
        """자기 해시를 자기 파일에 넣지 않는다 (권장안 4절)."""
        for name in SAMPLE_NAMES:
            self.assertNotIn("path_sha256", load(name))

    def test_segment_kinds_and_order(self):
        for name in SAMPLE_NAMES:
            segs = load(name)["segments"]
            self.assertTrue(segs)
            for s in segs:
                self.assertIn(s["kind"], ("APPROACH", "CUT", "TRAVEL", "RETRACT"))
                self.assertIn("motion_profile_id", s)
                self.assertGreaterEqual(len(s["waypoints"]), 2)

    def test_segment_continuity(self):
        """이전 구간 끝점 = 다음 구간 시작점. 끊기면 로봇이 자유공간을 지난다."""
        for name in SAMPLE_NAMES:
            segs = load(name)["segments"]
            for i in range(len(segs) - 1):
                d = math.dist(pos(segs[i]["waypoints"][-1]), pos(segs[i + 1]["waypoints"][0]))
                self.assertLess(d, 1e-4, f"{name}: {segs[i]['segment_id']} 뒤 연결 끊김 {d*1000:.3f}mm")


class TestCutGeometry(unittest.TestCase):
    """CUT 구간이 원통 표면과 작업 범위를 지키는가."""

    def test_cut_points_on_surface(self):
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                if s["kind"] != "CUT":
                    continue
                for k, w in enumerate(s["waypoints"]):
                    self.assertAlmostEqual(radial(pos(w)), wc.RADIUS_M, delta=1e-4,
                                           msg=f"{name}/{s['segment_id']}[{k}] 표면 이탈")

    def test_cut_height_in_workable_band(self):
        lo, hi = wc.WORKABLE_HEIGHT_RANGE_M
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                if s["kind"] != "CUT":
                    continue
                for w in s["waypoints"]:
                    h = height_of(pos(w))
                    self.assertGreaterEqual(h, lo - 1e-6, f"{name}: 높이 {h:.6f} < {lo}")
                    self.assertLessEqual(h, hi + 1e-6, f"{name}: 높이 {h:.6f} > {hi}")

    def test_cut_spacing_max(self):
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                if s["kind"] != "CUT":
                    continue
                for k in range(len(s["waypoints"]) - 1):
                    d = math.dist(pos(s["waypoints"][k]), pos(s["waypoints"][k + 1]))
                    self.assertLessEqual(d, wc.WAYPOINT_SPACING_MAX_M + 1e-4,
                                         f"{name}: 간격 {d*1000:.3f}mm > 2mm")

    def test_cut_segment_point_limit(self):
        """movesx 한도(100)에 여유를 둔 80점 상한."""
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                if s["kind"] == "CUT":
                    self.assertLessEqual(len(s["waypoints"]), wc.SEGMENT_POINTS_MAX)

    def test_stroke_arc_limit_and_seam(self):
        """획당 둘레 각도 180도 이내, 이음매(0도) 미통과 — J6 감김 방지."""
        for name in SAMPLE_NAMES:
            by_stroke = {}
            for s in load(name)["segments"]:
                if s["kind"] == "CUT":
                    by_stroke.setdefault(s["stroke_id"], []).extend(
                        theta_of(pos(w)) for w in s["waypoints"])
            for sid, ths in by_stroke.items():
                unw = unwrap(ths)
                span = max(unw) - min(unw)
                self.assertLessEqual(span, wc.STROKE_MAX_ARC_DEG + 1e-6,
                                     f"{name}/{sid}: 둘레 각도 {span:.2f}도")
                for k in range(len(unw) - 1):
                    lo, hi = min(unw[k], unw[k + 1]), max(unw[k], unw[k + 1])
                    self.assertFalse(wc.seams_strictly_between(lo + 1e-6, hi - 1e-6),
                                     f"{name}/{sid}: 이음매 통과")


class TestNonCutGeometry(unittest.TestCase):
    """비절삭 구간이 원통을 뚫지 않는가."""

    def test_travel_stays_outside_cylinder(self):
        """TRAVEL 은 오프셋 원통 위를 따라간다. 직선 현이면 각도차가 클 때 관통한다."""
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                if s["kind"] != "TRAVEL":
                    continue
                W = s["waypoints"]
                for k in range(len(W) - 1):
                    a, b = pos(W[k]), pos(W[k + 1])
                    for i in range(21):
                        t = i / 20
                        p = tuple(a[c] + (b[c] - a[c]) * t for c in range(3))
                        self.assertGreaterEqual(radial(p), wc.RADIUS_M - 1e-4,
                                                f"{name}/{s['segment_id']} 원통 관통")

    def test_travel_is_not_straight_chord(self):
        """각도차가 큰 이동은 중간 waypoint 가 있어야 한다 (직선 현 금지)."""
        limit_deg = 2 * math.degrees(math.acos(
            wc.RADIUS_M / (wc.RADIUS_M + wc.CLEARANCE_STROKE_M)))
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                if s["kind"] != "TRAVEL" or s.get("surface") != "offset_cylinder":
                    continue
                W = s["waypoints"]
                ta, tb = theta_of(pos(W[0])), theta_of(pos(W[-1]))
                d = abs(tb - ta)
                d = min(d, 360 - d)
                if d > limit_deg:
                    self.assertGreater(len(W), 2,
                                       f"{name}/{s['segment_id']}: {d:.1f}도인데 2점뿐")


class TestOrientation(unittest.TestCase):
    """도구 자세 규약과 쿼터니언 연속성."""

    def test_quaternion_normalized(self):
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                for k, w in enumerate(s["waypoints"]):
                    n = math.sqrt(sum(c * c for c in quat(w)))
                    self.assertAlmostEqual(n, 1.0, delta=1e-4,
                                           msg=f"{name}/{s['segment_id']}[{k}] |q|={n}")

    def test_quaternion_sign_continuous(self):
        """q 와 -q 는 같은 회전이지만 부호가 튀면 보간 시 손목이 먼 쪽으로 돈다.
        theta=180도 통과 지점에서 실제로 발생했던 문제."""
        for name in SAMPLE_NAMES:
            segs = load(name)["segments"]
            flat = [w for s in segs for w in s["waypoints"]]
            for k in range(len(flat) - 1):
                dot = sum(a * b for a, b in zip(quat(flat[k]), quat(flat[k + 1])))
                self.assertGreaterEqual(dot, 0.0, f"{name}: {k}번째에서 부호 튐")

    def test_tool_axis_convention(self):
        """툴 -Y = 표면 안쪽 법선, 툴 +Z = base -Z."""
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                for k, w in enumerate(s["waypoints"]):
                    x, y, z, ww = quat(w)
                    local_y = (2 * (x * y - z * ww), 1 - 2 * (x * x + z * z), 2 * (y * z + x * ww))
                    local_z = (2 * (x * z + y * ww), 2 * (y * z - x * ww), 1 - 2 * (x * x + y * y))
                    self.assertAlmostEqual(local_z[2], -1.0, delta=1e-3,
                                           msg=f"{name}/{s['segment_id']}[{k}] 툴 +Z")
                    out = wc.radial_direction(theta_of(pos(w)))
                    dot = sum(-a * -b for a, b in zip(local_y, out))
                    self.assertGreater(dot, 1 - 1e-3,
                                       f"{name}/{s['segment_id']}[{k}] 툴 -Y")


class TestAlgorithms(unittest.TestCase):
    """확정 조합의 각 단계가 의도대로 동작하는가."""

    def test_de_casteljau_split_preserves_curve(self):
        """분할한 두 조각이 원곡선과 같은 점을 지나야 한다."""
        p0, p1, p2, p3 = (0, 0), (10, 30), (40, 30), (50, 0)

        def bez(t):
            u = 1 - t
            return (u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1])

        left, right = extract_2d.de_casteljau_split(p0, p1, p2, p3, 0.5)
        self.assertAlmostEqual(math.dist(left[3], bez(0.5)), 0.0, places=9)
        self.assertAlmostEqual(math.dist(right[0], bez(0.5)), 0.0, places=9)

    def test_adaptive_sampling_respects_chord_tolerance(self):
        """샘플링 결과가 현 오차 허용치 안에 들어와야 한다."""
        p0, p1, p2, p3 = (0, 0), (10, 30), (40, 30), (50, 0)
        tol, step = 0.05, 2.0
        pts = [p0] + extract_2d.sample_cubic_adaptive(p0, p1, p2, p3, tol, step)
        for k in range(len(pts) - 1):
            self.assertLessEqual(math.dist(pts[k], pts[k + 1]), step + 1e-9)
        self.assertGreater(len(pts), 4)

    def test_adaptive_sampling_is_denser_in_curves(self):
        """곡률이 큰 구간이 더 촘촘해야 한다 (균일 샘플링이 아님)."""
        p0, p1, p2, p3 = (0, 0), (0, 40), (40, 40), (40, 0)
        pts = [p0] + extract_2d.sample_cubic_adaptive(p0, p1, p2, p3, 0.05, 2.0)
        gaps = [math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
        self.assertGreater(max(gaps) / min(gaps), 1.2, "간격이 사실상 균일함")

    def test_optimize_2d_does_not_modify_shape_or_direction(self):
        """2-opt 는 방문 순서만 바꾼다. 점열과 진행 방향은 그대로여야 한다."""
        a = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
        b = [(10.0, 0.0), (11.0, 0.0)]
        c = [(5.0, 0.0), (6.0, 0.0)]
        out, st = optimize_2d.optimize([a, b, c])
        self.assertFalse(st["shape_modified"])
        self.assertEqual(st["direction_reversed_count"], 0)
        self.assertFalse(st["direction_reversal_allowed"])
        for s in out:
            self.assertIn(s, [a, b, c], "획의 점열이 바뀌었다")

    def test_seam_split_cuts_at_seam(self):
        """이음매를 지나는 획은 정확히 이음매 각도에서 끊겨야 한다."""
        tv = [(-10.0, 0.10), (0.0 - 1e-9, 0.10), (10.0, 0.10)]
        parts = map_3d.split_at_seam([(170.0, 0.10), (190.0, 0.10)])
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(parts[0][-1][0], wc.SEAM_ANGLE_DEG, places=9)
        self.assertAlmostEqual(parts[1][0][0], wc.SEAM_ANGLE_DEG, places=9)

    def test_arc_limit_split(self):
        """둘레 각도가 한계를 넘으면 쪼개야 한다."""
        tv = [(t, 0.10) for t in range(0, 300, 10)]
        parts = map_3d.split_by_arc_limit(tv, wc.STROKE_MAX_ARC_DEG)
        self.assertGreater(len(parts), 1)
        for p in parts:
            span = max(t for t, _ in p) - min(t for t, _ in p)
            self.assertLessEqual(span, wc.STROKE_MAX_ARC_DEG + 1e-9)

    def test_offset_cylinder_travel_never_penetrates(self):
        """180도 이동도 오프셋 원통을 따라가면 관통하지 않는다."""
        tv = generate_path.travel_waypoints(-90.0, 0.10, 90.0, 0.10, wc.CLEARANCE_STROKE_M)
        self.assertGreater(len(tv), 2)
        for t, h in tv:
            p = wc.offset_point(t, h, wc.CLEARANCE_STROKE_M)
            self.assertGreaterEqual(radial(p), wc.RADIUS_M + wc.CLEARANCE_STROKE_M - 1e-9)

    def test_straight_chord_would_penetrate(self):
        """대조군: 같은 이동을 직선 현으로 하면 원통을 뚫는다 (그래서 금지)."""
        a = wc.offset_point(-90.0, 0.10, wc.CLEARANCE_STROKE_M)
        b = wc.offset_point(90.0, 0.10, wc.CLEARANCE_STROKE_M)
        worst = min(radial(tuple(a[c] + (b[c] - a[c]) * (i / 100) for c in range(3)))
                    for i in range(101))
        self.assertLess(worst, wc.RADIUS_M, "직선 현이 관통하지 않음 — 시험 전제가 틀림")

    def test_no_rdp_or_bspline_used(self):
        """RDP·B-spline 은 쓰지 않는다 (원본 도안 이탈 위험)."""
        _, st = extract_2d.extract(
            open(os.path.join(SAMPLES, "heart.svg"), encoding="utf-8").read(),
            24.0, 24.0, 0.0, 105.0)
        self.assertFalse(st["refit_applied"])


class TestSeamAndOrigin(unittest.TestCase):
    """9/20 각도 기준: 0° = +X, 반시계 양수, 이음매 = ±180°(−X, 로봇 쪽). u 원점과 이음매 분리."""

    def test_constants(self):
        self.assertEqual(wc.U_ORIGIN_ANGLE_DEG, 0.0)
        self.assertEqual(wc.SEAM_ANGLE_DEG, 180.0)

    def test_u_zero_maps_to_plus_x_not_seam(self):
        """offset_u=0 도안은 +X 면(로봇 반대편)에 놓여야 한다. 이음매(로봇 쪽)에 놓이면 안 된다."""
        self.assertAlmostEqual(wc.theta_deg_from_u_mm(0.0), 0.0)
        p = wc.surface_point(wc.theta_deg_from_u_mm(0.0), 0.1)
        self.assertGreater(p[0], wc.AXIS_ORIGIN_XY_M[0])

    def test_unrolled_sheet_edges_are_seam(self):
        """전개면 u = ±πR 양 끝이 이음매다."""
        half = math.pi * wc.RADIUS_M * 1000.0
        self.assertAlmostEqual(wc.theta_deg_from_u_mm(half), 180.0)
        self.assertAlmostEqual(wc.theta_deg_from_u_mm(-half), -180.0)

    def test_split_parts_are_in_minus180_180(self):
        """이음매에서 끊긴 조각은 [−180, 180] 으로 옮겨 표현한다 (TRAVEL 이 이음매를 넘지 않게)."""
        half = math.pi * wc.RADIUS_M * 1000.0
        v = (wc.WORKABLE_HEIGHT_RANGE_M[0] + 0.01) * 1000.0
        mapped, failures, st = map_3d.map_strokes([[(half - 5.0, v), (half + 5.0, v)]])
        self.assertEqual(st["strokes_split_at_seam"], 1)
        self.assertEqual(len(mapped), 2)
        for m in mapped:
            for w in m["waypoints"]:
                self.assertGreaterEqual(w["theta_deg"], -180.0 - 1e-6)
                self.assertLessEqual(w["theta_deg"], 180.0 + 1e-6)

    def test_validator_detects_cut_crossing_seam(self):
        """분할하지 않은 채 −X 면을 가로지르는 CUT 은 실패해야 한다 (atan2 ±180 과 이음매가 겹쳐도)."""
        from c2_path import validate_path
        h = wc.WORKABLE_HEIGHT_RANGE_M[0] + 0.01
        ths = [170.0 + i * 0.5 for i in range(41)]          # 170 → 190 (= −170)
        quats = wc.make_continuous([wc.tool_orientation(t) for t in ths])
        wps = [wc.to_pose7(wc.surface_point(t, h), q) for t, q in zip(ths, quats)]
        path = {"schema_version": 2, "frame_id": wc.FRAME_ID, "tool_id": wc.TOOL_ID,
                "position_unit": "m", "orientation": "quaternion_xyzw",
                "segments": [{"segment_id": "s1", "stroke_id": "st1", "kind": "CUT",
                              "motion_profile_id": "candle_cut", "waypoints": wps}]}
        rep = validate_path.validate(path)
        self.assertTrue(any(e.startswith("SEAM_CROSSED") for e in rep["errors"]), rep["errors"])

    def test_travel_does_not_cross_seam(self):
        """샘플 TRAVEL 이 −X 면(로봇 쪽)을 지나지 않는다."""
        for name in SAMPLE_NAMES:
            for s in load(name)["segments"]:
                if s["kind"] != "TRAVEL":
                    continue
                unw = unwrap([theta_of(pos(w)) for w in s["waypoints"]])
                for k in range(len(unw) - 1):
                    lo, hi = min(unw[k], unw[k + 1]), max(unw[k], unw[k + 1])
                    self.assertFalse(wc.seams_strictly_between(lo + 1e-6, hi - 1e-6),
                                     f"{name}/{s['segment_id']}: TRAVEL 이 이음매 통과")

    def test_workcell_matches_0919_yaml(self):
        """workcell_candle_0919.yaml (PR #32) 과 같은 값."""
        self.assertEqual(wc.AXIS_ORIGIN_XY_M, (0.4218, 0.0001))
        self.assertAlmostEqual(wc.TOP_Z_BASE_M, 0.2334)
        self.assertAlmostEqual(wc.AXIS_ORIGIN_Z_M, 0.0834)
        self.assertAlmostEqual(wc.RADIUS_M, 0.034)


class TestFailureResultFormat(unittest.TestCase):
    """실패 결과는 빈 문자열·버전 0 (GeneratePath.action 확정). null 이 아니다."""

    def test_height_out_of_range_is_detected(self):
        lo, hi = wc.WORKABLE_HEIGHT_RANGE_M
        bad = [[(0.0, (hi + 0.02) * 1000.0), (1.0, (hi + 0.02) * 1000.0)]]
        mapped, failures, st = map_3d.map_strokes(bad)
        self.assertEqual(len(mapped), 0)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason_code"], "HEIGHT_OUT_OF_RANGE")

    def test_sample_result_uses_empty_string_not_null(self):
        for name in SAMPLE_NAMES:
            with open(os.path.join(SAMPLES, name, "result.json"), encoding="utf-8") as f:
                r = json.load(f)
            self.assertIsNotNone(r["path_id"])
            self.assertIsInstance(r["path_id"], str)
            self.assertIsInstance(r["path_version"], int)
            self.assertIsInstance(r["path_sha256"], str)


class TestValidationReport(unittest.TestCase):
    """검증 결과가 확인하지 않은 항목을 밝히는가."""

    def test_not_checked_declares_j6(self):
        """c2_path 는 J6 를 계산하지 않는다. 실행 측이 봐야 한다는 걸 파일이 밝혀야 한다."""
        for name in SAMPLE_NAMES:
            v = load(name)["validation"]
            self.assertIn("J6_RANGE", v["not_checked"])
            self.assertTrue(v["passed"])


class TestImageToSvg(unittest.TestCase):
    """image_to_svg.py: 이미지 -> 중심선(centerline) SVG 변환.

    docs/SVG_VECTORIZATION_VALIDATION.md 의 Potrace(영역 보존) 방식이 아니라, extract_2d.py
    가 기대하는 "붓이 지나간 선 하나" 형식(docs/ALGORITHM_VALIDATION.md 3차 검증 조합:
    세선화 + 잔가지 정리 + Schneider 베지어 근사)으로 만드는지 확인한다.
    """

    def test_roundtrip_recovers_closed_shape(self):
        """하트를 라스터화했다가 되돌리면 원본과 거의 같은 닫힌 획 하나가 나와야 한다.

        오목한 뾰족점(하트 윗부분 중앙)에서 세선화가 만드는 미세 잡음 고리 때문에
        획이 둘로 쪼개졌던 회귀가 있었다 — stroke_count == 1 로 그 회귀를 잡는다."""
        pts = _heart_centerline_points()
        with tempfile.TemporaryDirectory() as td:
            img_path = os.path.join(td, "heart.png")
            cv2.imwrite(img_path, _rasterize_polyline(pts, closed=True, thickness=3))
            svg, stats = image_to_svg.convert(img_path, spur_min_len_px=8.0, fit_error_px=0.8)

        self.assertEqual(stats["stroke_count"], 1, "잔가지·미세 고리 정리 후에도 획이 하나로 안 뭉침")
        self.assertTrue(stats["strokes"][0]["closed"])

        conv_strokes, _ = extract_2d.extract(svg, 24.0, 24.0, 0.0, 0.0)
        self.assertEqual(len(conv_strokes), 1)

        orig_svg = open(os.path.join(SAMPLES, "heart.svg"), encoding="utf-8").read()
        orig_strokes, _ = extract_2d.extract(orig_svg, 24.0, 24.0, 0.0, 0.0)
        orig, conv = orig_strokes[0], conv_strokes[0]
        max_dev = max(min(math.dist(p, q) for q in orig) for p in conv)
        self.assertLess(max_dev, 0.6, f"복원된 하트가 원본에서 {max_dev:.3f}mm 벗어남 (24mm 기준)")

    def test_output_uses_only_move_line_cubic_close(self):
        """extract_2d.py 는 M/L/C/Z 만 해석한다. 다른 명령이 섞이면 조용히 무시되므로
        image_to_svg.py 가 그 외 명령(호 A 등)을 내보내지 않는지 직접 확인한다."""
        pts = _heart_centerline_points()
        with tempfile.TemporaryDirectory() as td:
            img_path = os.path.join(td, "heart.png")
            cv2.imwrite(img_path, _rasterize_polyline(pts, closed=True, thickness=3))
            svg, _ = image_to_svg.convert(img_path)
        for m in _SVG_PATH_D.finditer(svg):
            letters = set(_SVG_D_LETTERS.findall(m.group(1)))
            self.assertTrue(letters <= {"M", "L", "C", "Z"}, f"허용 안 된 SVG 명령 발견: {letters}")

    def test_open_stroke_is_not_closed(self):
        """열린 선(지그재그)은 Z 로 닫으면 안 된다 — 끝점을 이으면 원본에 없는 선이 생긴다."""
        zigzag = [(0.0, 0.0), (20.0, 30.0), (40.0, 0.0), (60.0, 30.0)]
        with tempfile.TemporaryDirectory() as td:
            img_path = os.path.join(td, "zigzag.png")
            cv2.imwrite(img_path, _rasterize_polyline(zigzag, closed=False, thickness=3))
            svg, stats = image_to_svg.convert(img_path, spur_min_len_px=8.0, fit_error_px=0.8)
        self.assertEqual(stats["stroke_count"], 1)
        self.assertFalse(stats["strokes"][0]["closed"])
        d = _SVG_PATH_D.search(svg).group(1)
        self.assertFalse(d.rstrip().endswith("Z"), "열린 획인데 Z 로 닫힘")

    def test_empty_image_raises(self):
        """빈(전부 배경) 이미지는 획을 못 찾았다고 명확히 실패해야 한다.
        조용히 빈 SVG를 내놓으면 이후 extract_2d 가 "SVG에서 획을 찾지 못했습니다" 로
        실패하긴 하지만, 원인을 여기서 바로 밝히는 것이 낫다."""
        with tempfile.TemporaryDirectory() as td:
            img_path = os.path.join(td, "blank.png")
            cv2.imwrite(img_path, np.full((200, 200), 255, np.uint8))
            with self.assertRaises(ValueError):
                image_to_svg.convert(img_path)

    def test_missing_file_raises(self):
        with self.assertRaises(ValueError):
            image_to_svg.convert("/no/such/file.png")


if __name__ == "__main__":
    unittest.main(verbosity=2)
