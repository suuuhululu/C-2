#!/usr/bin/env python3
"""readiness.py — 로봇 실행 사전 점검 (경로 생성 성공과 별개).

경로 생성·3D 미리보기는 원기둥 옆면 전체(둘레 360°, 높이는 프로파일 기준)를 대상으로 성공할 수 있다.
그 경로가 로봇이 지금 닿을 수 있는 범위 안인지는 별개의 문제라서 여기서 따로 점검하고 결과만 표시한다.

  * 이 점검은 **잠정 범위** 로 구간이 범위 밖인지만 본다. 실행 가능 판정이 아니다.
    그래서 `executability` 는 항상 "NOT_JUDGED" 이고, 판정은 실행 전 검사(joint_check 의 IK·J5/J6 등)가 한다.
  * 각도 범위(±135°)는 9/20 J5 실측에서 나온 **원통 도달각 참고 범위**다. 실제 J5 관절 한계 판정이 아니다
    (J5 는 `not_checked` 의 `J5_JOINT_LIMIT` 로 남는다). 높이 범위는 로봇 작업 범위(바닥 기준)다.
  * 범위 밖이어도 경로·미리보기는 만들어진다. 실행 요청을 보낼지는 이 결과를 보고 소비하는 쪽이 정한다.
  * 검증 보고서의 `checks`(모두 통과해야 하는 기하 검사)와 섞지 않는다. 그래서 `execution_readiness` 는
    보고서·미리보기의 별도 필드이고, path.json 의 `validation` 블록은 바꾸지 않는다.

점검 대상은 CUT 구간이다. TRAVEL/APPROACH/RETRACT 는 CUT 끝점 각도·높이 사이를 보간하거나 같은 (θ, h) 에서
반경만 바꾸므로 모든 CUT 이 범위 안이면 벗어나지 않는다.
"""
import math

from . import workcell as wc

CONTRACT = "c2-path-execution-readiness/1"
WITHIN = "WITHIN_LIMITS"
OUT_OF = "OUT_OF_LIMITS"
MAX_LISTED_VIOLATIONS = 100

DEFAULT_LIMITS_SOURCE = ("시율님 지시(잠정) — 높이 9/21 변경(10~140mm), 각도 9/20 J5 실측 — "
                         "surface.valid_v_range_mm / surface.reachable_angle_deg")
SNAPSHOT_LIMITS_SOURCE = "요청 스냅샷(/2) — surface.valid_v_range_mm / surface.reachable_angle_deg (요청별 값)"
ANGLE_MEANING = "원통 도달각 참고 범위(잠정). 실제 J5 관절 한계 판정이 아니다."

# c2_path 가 계산하지 않는 항목. 실행 전 검사가 직접 봐야 한다.
NOT_CHECKED = ["J5_JOINT_LIMIT", "J6_RANGE", "IK_REACHABILITY", "COLLISION"]


def _theta(p):
    ox, oy = wc.current_surface().axis_origin_xy_m
    return math.degrees(math.atan2(p[1] - oy, p[0] - ox))


def _height(p):
    return p[2] - wc.current_surface().axis_origin_z_m


def default_limits():
    return {
        "work_height_range_m": list(wc.WORKABLE_HEIGHT_RANGE_M),
        "height_reference": "bottom",          # 높이 0 = 양초 바닥(축 원점 z). 윗면 기준이 아니다.
        "reachable_angle_deg": list(wc.REACHABLE_ANGLE_DEG),
        "source": DEFAULT_LIMITS_SOURCE,
    }


def limits_from_profile(profile):
    """스냅샷 `surface` 의 잠정 작업 범위. 없으면 workcell 상수.

    파이프라인에서는 `validate_profile` 을 먼저 통과한 스냅샷만 이 함수에 온다.
      /1 : 스냅샷 값이 workcell 상수와 정확히 같다 (`test_readiness.TestSingleWorkRange` 가 고정).
      /2 : 스냅샷 값이 요청별 기준이다. workcell 상수와 달라도 되고, 이 값이 유일한 기준이다."""
    surface = profile.get("surface") if isinstance(profile, dict) else None
    limits = default_limits()
    if isinstance(profile, dict) and profile.get("contract") == "c2-path-test-profile/2":
        limits["source"] = SNAPSHOT_LIMITS_SOURCE
    if isinstance(surface, dict):
        v = surface.get("valid_v_range_mm")
        a = surface.get("reachable_angle_deg")
        if isinstance(v, (list, tuple)) and len(v) == 2:
            limits["work_height_range_m"] = [float(v[0]) / 1000.0, float(v[1]) / 1000.0]
        if isinstance(a, (list, tuple)) and len(a) == 2:
            limits["reachable_angle_deg"] = [float(a[0]), float(a[1])]
    return limits


def segment_status(segment, limits):
    """CUT 구간 하나의 점검 결과. 범위 안이면 (True, [])."""
    lo_h, hi_h = limits["work_height_range_m"]
    lo_a, hi_a = limits["reachable_angle_deg"]
    heights = [_height(w[:3]) for w in segment["waypoints"]]
    thetas = [_theta(w[:3]) for w in segment["waypoints"]]
    out_points = 0
    reasons = []
    h_bad = [h for h in heights if not (lo_h - 1e-6 <= h <= hi_h + 1e-6)]
    a_bad = [t for t in thetas if not (lo_a - 1e-6 <= t <= hi_a + 1e-6)]
    if h_bad:
        reasons.append({"code": "HEIGHT_OUT_OF_RANGE", "observed_min": round(min(heights), 6),
                        "observed_max": round(max(heights), 6), "limit": [lo_h, hi_h]})
    if a_bad:
        reasons.append({"code": "ANGLE_OUT_OF_RANGE", "observed_min": round(min(thetas), 3),
                        "observed_max": round(max(thetas), 3), "limit": [lo_a, hi_a]})
    for h, t in zip(heights, thetas):
        if not (lo_h - 1e-6 <= h <= hi_h + 1e-6) or not (lo_a - 1e-6 <= t <= hi_a + 1e-6):
            out_points += 1
    return (not reasons), reasons, out_points, len(heights)


def execution_readiness(path, limits=None):
    """경로의 CUT 구간이 잠정 로봇 작업 범위 안인지 점검한다. 반환: 보고서에 넣을 dict."""
    limits = limits or default_limits()
    cut_segments = [s for s in path.get("segments", []) if s.get("kind") == "CUT"]
    violations = []
    out_segments = []
    out_strokes = []
    points_total = points_out = 0
    for segment in cut_segments:
        okay, reasons, out_points, count = segment_status(segment, limits)
        points_total += count
        points_out += out_points
        if not okay:
            out_segments.append(segment["segment_id"])
            if segment.get("stroke_id") not in out_strokes:
                out_strokes.append(segment.get("stroke_id"))
            for reason in reasons:
                violations.append({"segment_id": segment["segment_id"], "stroke_id": segment.get("stroke_id"),
                                   **reason})
    height_violations = sum(1 for v in violations if v["code"] == "HEIGHT_OUT_OF_RANGE")
    angle_violations = sum(1 for v in violations if v["code"] == "ANGLE_OUT_OF_RANGE")
    within = not violations
    return {
        "contract": CONTRACT,
        "authoritative": False,
        "executability": "NOT_JUDGED",
        "precheck": WITHIN if within else OUT_OF,
        "note": ("c2_path 의 잠정 범위 사전 점검이다. 실행 가능 여부는 판정하지 않으며 실행 전 검사(IK·J5/J6·충돌)가 한다. "
                 "경로 생성 성공·검증 통과·미리보기 성공은 로봇이 실행할 수 있다는 뜻이 아니다."),
        "limits": {"provisional": True, "angle_meaning": ANGLE_MEANING, **limits},
        "checks": [
            {"code": "WORK_HEIGHT_IN_RANGE", "passed": height_violations == 0,
             "limit_m": limits["work_height_range_m"]},
            {"code": "ANGLE_IN_REACHABLE_RANGE", "passed": angle_violations == 0,
             "limit_deg": limits["reachable_angle_deg"]},
        ],
        "summary": {
            "cut_segment_count": len(cut_segments),
            "out_of_limit_cut_segment_count": len(out_segments),
            "out_of_limit_stroke_count": len(out_strokes),
            "cut_waypoint_count": points_total,
            "out_of_limit_cut_waypoint_count": points_out,
        },
        "out_of_limit_segment_ids": out_segments,
        "violation_count": len(violations),
        "violations": violations[:MAX_LISTED_VIOLATIONS],
        "violations_truncated": len(violations) > MAX_LISTED_VIOLATIONS,
        "not_checked": list(NOT_CHECKED),
    }


def preview_summary(readiness):
    """미리보기 JSON 상단에 넣는 요약 (전체 위반 목록은 검증 보고서에 있다)."""
    return {
        "contract": readiness["contract"],
        "executability": readiness["executability"],
        "precheck": readiness["precheck"],
        "limits": readiness["limits"],
        "out_of_limit_cut_segment_count": readiness["summary"]["out_of_limit_cut_segment_count"],
        "cut_segment_count": readiness["summary"]["cut_segment_count"],
        "note": readiness["note"],
    }


def segment_flags(path, limits):
    """미리보기 구간별 표시: segment_id -> {precheck, reasons}. CUT 구간만 담는다."""
    flags = {}
    for segment in path.get("segments", []):
        if segment.get("kind") != "CUT":
            continue
        okay, reasons, _out, _n = segment_status(segment, limits)
        flags[segment["segment_id"]] = {
            "execution_precheck": WITHIN if okay else OUT_OF,
            "execution_precheck_reasons": [r["code"] for r in reasons],
        }
    return flags


def message_suffix(readiness):
    """GeneratePath Result.message 에 붙일 한 문장."""
    summary = readiness["summary"]
    if readiness["precheck"] == WITHIN:
        return "잠정 로봇 작업 범위 안이지만 실행 가능 여부는 판정하지 않았습니다."
    return (f"절삭 구간 {summary['out_of_limit_cut_segment_count']}/{summary['cut_segment_count']}개가 잠정 로봇 작업 범위를 "
            "벗어나 있어 실행 전 검사 전까지 실행할 수 없는 경로로 취급해야 합니다.")
