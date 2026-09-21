# joint_check.py — 전체 경로의 IK·관절 한계·J6 누적 회전 검사. 최초 구현: 이시율. 담당: 김세은 (2026-09-20).
# 팀 규칙(INTERFACE_RECOMMENDATION 13절): 각도 범위·이음매는 c2_path 검증, "현재 관절·IK·전체 경로 J6 한계/여유" 는 공정 준비에서 확인.
# 상태 기계(PRECHECK)가 부른다. 로봇을 움직이지 않는다. 어댑터의 inverse_kinematics(제어기 ikin) 만 쓴다.
#   r = check_path_joints(path, adapter, tool_offset_m, ref_joints_rad, limits_deg=None, j6_margin_deg=10)
#   r.ok → 통과. 실패: FAILED/VALIDATION_FAILED (한계 초과·J6 여유 부족) 또는 FAILED/NOT_READY (IK 불가·어댑터 없음).
#   observed_state: joints_min_deg, joints_max_deg, j6_start/end/min/max, j6_total_rotation_deg, checked_waypoints, worst(segment_id, joint, value)
import math
from typing import Dict, List, Optional

from .robot_adapter import RobotAdapter, StepResult

# M0609 관절 범위 [deg] (두산 사양. 현장 안전 설정이 더 좁으면 limits_deg 로 넘긴다)
DEFAULT_LIMITS_DEG = [(-360.0, 360.0), (-95.0, 95.0), (-135.0, 135.0), (-360.0, 360.0), (-135.0, 135.0), (-360.0, 360.0)]


def _unwrap(prev_deg: float, cur_deg: float) -> float:
    """ikin 이 ±180 로 접어 준 J6 를 이전 값과 이어지게 펼친다 (연속 경로에서 360° 점프 방지)."""
    # fmod는 반복 없이 처리하며 기존의 +180/-180 방향을 보존한다.
    delta = cur_deg - prev_deg
    if not all(math.isfinite(v) for v in (prev_deg, cur_deg, delta)):
        raise ValueError("J6 각도는 유한한 숫자여야 함")
    delta = math.fmod(delta, 360.0)
    if delta > 180.0:
        delta -= 360.0
    elif delta < -180.0:
        delta += 360.0
    return prev_deg + delta


def _finite_joints(values):
    """문자열·bool·누락·NaN/무한대는 관절 측정값으로 인정하지 않는다."""
    try:
        return (isinstance(values, (list, tuple)) and len(values) == 6
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) for v in values))
    except (TypeError, ValueError, OverflowError):
        return False


def check_path_joints(path: Dict, adapter: RobotAdapter, tool_offset_m: Optional[List[float]], ref_joints_rad: List[float],
                      limits_deg: Optional[List] = None, j6_margin_deg: float = 10.0, cancel=None) -> StepResult:
    limits = DEFAULT_LIMITS_DEG if limits_deg is None else limits_deg
    if (not isinstance(limits, (list, tuple)) or len(limits) != 6
            or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                   or any(type(v) not in (int, float) or not math.isfinite(v) for v in pair)
                   or pair[0] >= pair[1] for pair in limits)
            or type(j6_margin_deg) not in (int, float) or not math.isfinite(j6_margin_deg)
            or j6_margin_deg < 0 or 2*j6_margin_deg >= limits[5][1]-limits[5][0]):
        return StepResult("FAILED", "NOT_READY", "관절 한계/여유 형식 오류", "joint_check")
    if not hasattr(adapter, "inverse_kinematics"):
        return StepResult("FAILED", "NOT_READY", "어댑터에 inverse_kinematics 없음", "joint_check")
    if not _finite_joints(ref_joints_rad):
        return StepResult("UNKNOWN", "VALIDATION_UNAVAILABLE", "현재 관절값은 유한한 숫자 6개여야 함", "joint_check")
    ref = [math.degrees(v) for v in ref_joints_rad]
    if not _finite_joints(ref):
        return StepResult("UNKNOWN", "VALIDATION_UNAVAILABLE", "현재 관절값의 도 단위 변환 불가", "joint_check")
    jmin = list(ref); jmax = list(ref)
    j6_start = ref[5]; j6_prev = ref[5]; j6_min = j6_max = ref[5]
    worst = None; n_checked = 0
    segments = path.get("segments")
    if not isinstance(segments, list) or not segments:
        return StepResult("FAILED", "INVALID_INPUT", "검사할 경로 구간 없음 또는 형식 오류", "joint_check",
                          dict(checked_waypoints=0))
    for seg in segments:
        wps = seg.get("waypoints") or []
        if not wps:
            return StepResult("FAILED", "INVALID_INPUT", "검사할 waypoint가 없는 구간", "joint_check",
                              dict(segment_id=seg.get("segment_id"), checked_waypoints=n_checked))
        # CUT을 포함한 모든 명시 waypoint를 순서대로 검사한다.
        # 표면 경로 또는 실행기가 만든 계획을 검사한다. 점 사이 보간·충돌 보장은 아니다.
        for i, waypoint in enumerate(wps):
            detail = dict(segment_id=seg.get("segment_id"), index=i, checked_waypoints=n_checked,
                          inspection_scope=path.get("inspection_scope", "SURFACE_PATH"))
            if path.get("inspection_scope"):
                detail.update(inspection_scope=path["inspection_scope"], stroke_id=seg.get("stroke_id"),
                              movement_kind=seg.get("movement_kind"), applied_offset_m=seg.get("applied_offset_m"),
                              applied_depth_m=seg.get("applied_depth_m"))
            if cancel is not None and cancel.is_set():
                return StepResult("STOPPED", "NONE", "IK 검사 취소", "joint_check", detail)
            q = adapter.inverse_kinematics(waypoint, tool_offset_m, ref)
            if cancel is not None and cancel.is_set():
                return StepResult("STOPPED", "NONE", "IK 검사 중 취소", "joint_check", detail)
            if q is None:
                return StepResult("FAILED", "NOT_READY", f"IK 실패: segment {seg.get('segment_id')} 점 {i}", "joint_check",
                                  detail)
            if not _finite_joints(q):
                return StepResult("UNKNOWN", "VALIDATION_UNAVAILABLE", "IK 관절값은 유한한 숫자 6개여야 함", "joint_check",
                                  detail)
            q = list(q)
            try:
                q[5] = _unwrap(j6_prev, q[5])
            except ValueError:
                return StepResult("UNKNOWN", "VALIDATION_UNAVAILABLE", "IK J6 각도 전개 불가", "joint_check",
                                  detail)
            for k in range(6):
                jmin[k] = min(jmin[k], q[k]); jmax[k] = max(jmax[k], q[k])
                lo, hi = limits[k]
                margin = j6_margin_deg if k == 5 else 0.0
                if q[k] < lo + margin or q[k] > hi - margin:
                    if worst is None or abs(q[k]) > abs(worst["value_deg"]):
                        worst = dict(detail, joint=k + 1, value_deg=q[k], limits_deg=[lo, hi], margin_deg=margin,
                                     remaining_margin_deg=min(q[k]-lo-margin, hi-margin-q[k]))
            j6_prev = q[5]; j6_min = min(j6_min, q[5]); j6_max = max(j6_max, q[5])
            ref = q; n_checked += 1
    obs = dict(inspection_scope=path.get("inspection_scope", "SURFACE_PATH"), joints_min_deg=[round(v, 1) for v in jmin], joints_max_deg=[round(v, 1) for v in jmax],
               j6_start_deg=round(j6_start, 1), j6_end_deg=round(j6_prev, 1), j6_min_deg=round(j6_min, 1), j6_max_deg=round(j6_max, 1),
               j6_total_rotation_deg=round(j6_max - j6_min, 1), checked_waypoints=n_checked, worst=worst)
    if worst is not None:
        return StepResult("FAILED", "VALIDATION_FAILED",
                          f"관절 한계/여유 초과: J{worst['joint']} {worst['value_deg']:.0f}° (segment {worst['segment_id']})", "joint_check", obs)
    return StepResult("SUCCEEDED", "NONE", f"{n_checked} 점 IK 통과, J6 {j6_min:.0f}~{j6_max:.0f}°", "joint_check", obs)
