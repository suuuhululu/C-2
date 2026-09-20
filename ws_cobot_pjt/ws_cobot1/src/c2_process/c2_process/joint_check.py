# joint_check.py — 전체 경로의 IK·관절 한계·J6 누적 회전 검사. 담당: 이시율 (2026-09-19).
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
CUT_STRIDE = 4                     # CUT 구간은 점이 촘촘하므로 4점마다 + 마지막 점


def _unwrap(prev_deg: float, cur_deg: float) -> float:
    """ikin 이 ±180 로 접어 준 J6 를 이전 값과 이어지게 펼친다 (연속 경로에서 360° 점프 방지)."""
    while cur_deg - prev_deg > 180.0:
        cur_deg -= 360.0
    while cur_deg - prev_deg < -180.0:
        cur_deg += 360.0
    return cur_deg


def check_path_joints(path: Dict, adapter: RobotAdapter, tool_offset_m: Optional[List[float]], ref_joints_rad: List[float],
                      limits_deg: Optional[List] = None, j6_margin_deg: float = 10.0) -> StepResult:
    limits = limits_deg or DEFAULT_LIMITS_DEG
    if not hasattr(adapter, "inverse_kinematics"):
        return StepResult("FAILED", "NOT_READY", "어댑터에 inverse_kinematics 없음", "joint_check")
    ref = [math.degrees(v) for v in ref_joints_rad]
    jmin = list(ref); jmax = list(ref)
    j6_start = ref[5]; j6_prev = ref[5]; j6_min = j6_max = ref[5]
    worst = None; n_checked = 0
    for seg in path.get("segments") or []:
        wps = seg.get("waypoints") or []
        idx = list(range(len(wps))) if seg.get("kind") != "CUT" else sorted(set(list(range(0, len(wps), CUT_STRIDE)) + [len(wps) - 1]))
        for i in idx:
            q = adapter.inverse_kinematics(wps[i], tool_offset_m, ref)
            if q is None:
                return StepResult("FAILED", "NOT_READY", f"IK 실패: segment {seg.get('segment_id')} 점 {i}", "joint_check",
                                  dict(segment_id=seg.get("segment_id"), index=i, checked_waypoints=n_checked))
            q = list(q)
            q[5] = _unwrap(j6_prev, q[5])
            for k in range(6):
                jmin[k] = min(jmin[k], q[k]); jmax[k] = max(jmax[k], q[k])
                lo, hi = limits[k]
                margin = j6_margin_deg if k == 5 else 0.0
                if q[k] < lo + margin or q[k] > hi - margin:
                    if worst is None or abs(q[k]) > abs(worst["value_deg"]):
                        worst = dict(segment_id=seg.get("segment_id"), index=i, joint=k + 1, value_deg=q[k])
            j6_prev = q[5]; j6_min = min(j6_min, q[5]); j6_max = max(j6_max, q[5])
            ref = q; n_checked += 1
    obs = dict(joints_min_deg=[round(v, 1) for v in jmin], joints_max_deg=[round(v, 1) for v in jmax],
               j6_start_deg=round(j6_start, 1), j6_end_deg=round(j6_prev, 1), j6_min_deg=round(j6_min, 1), j6_max_deg=round(j6_max, 1),
               j6_total_rotation_deg=round(j6_max - j6_min, 1), checked_waypoints=n_checked, worst=worst)
    if worst is not None:
        return StepResult("FAILED", "VALIDATION_FAILED",
                          f"관절 한계/여유 초과: J{worst['joint']} {worst['value_deg']:.0f}° (segment {worst['segment_id']})", "joint_check", obs)
    return StepResult("SUCCEEDED", "NONE", f"{n_checked} 점 IK 통과, J6 {j6_min:.0f}~{j6_max:.0f}°", "joint_check", obs)
