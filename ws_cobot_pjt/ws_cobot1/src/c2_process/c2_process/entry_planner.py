"""현재/HOME에서 c2_path의 첫 APPROACH까지 이어지는 실행 전 진입 계획.

이 모듈은 새 ROS 노드가 아니다. 공정 노드가 불변 측정 스냅샷의 workcell,
현재 로봇 상태와 경로를 넘겨 내부 함수로 호출한다. 후보 생성·IK 검사는 로봇을
움직이지 않으며, 실행 함수는 검사 후 해시로 고정된 계획만 소비한다.
"""

import copy
import hashlib
import json
import math
from typing import Mapping

from .joint_check import check_path_joints
from .engraving_workspace import check_waypoints
from .robot_adapter import StepResult, apply_tool_offset


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pose(value):
    return (isinstance(value, (list, tuple)) and len(value) == 7
            and all(_finite(v) for v in value))


def _vector(value, length):
    return (isinstance(value, (list, tuple)) and len(value) == length
            and all(_finite(v) for v in value))


def _quat_normalize(q):
    n = math.sqrt(sum(v * v for v in q))
    if not math.isfinite(n) or n <= 1e-12:
        raise ValueError("quaternion 크기가 0")
    return [v / n for v in q]


def _quat_angle_deg(a, b):
    qa, qb = _quat_normalize(a), _quat_normalize(b)
    dot = min(1.0, abs(sum(x * y for x, y in zip(qa, qb))))
    return math.degrees(2.0 * math.acos(dot))


def _quat_slerp(a, b, t):
    qa, qb = _quat_normalize(a), _quat_normalize(b)
    dot = sum(x * y for x, y in zip(qa, qb))
    if dot < 0:
        qb, dot = [-v for v in qb], -dot
    if dot > 0.9995:
        return _quat_normalize([x + (y - x) * t for x, y in zip(qa, qb)])
    theta = math.acos(min(1.0, dot))
    scale = math.sin(theta)
    return [(math.sin((1.0 - t) * theta) * x + math.sin(t * theta) * y) / scale
            for x, y in zip(qa, qb)]


def _interpolate(a, b, sample_m, sample_deg):
    count = max(1, math.ceil(math.dist(a[:3], b[:3]) / sample_m),
                math.ceil(_quat_angle_deg(a[3:7], b[3:7]) / sample_deg))
    return [[a[k] + (b[k] - a[k]) * i / count for k in range(3)]
            + _quat_slerp(a[3:7], b[3:7], i / count)
            for i in range(1, count + 1)]


def _first_approach(path):
    segments = path.get("segments") if isinstance(path, Mapping) else None
    if not isinstance(segments, list):
        return None
    for segment in segments:
        if isinstance(segment, Mapping) and segment.get("kind") == "APPROACH":
            points = segment.get("waypoints")
            if isinstance(points, list) and points and _pose(points[0]):
                return list(points[0])
    return None


def _policy(workcell, motion_profiles):
    policy = workcell.get("entry_planning") if isinstance(workcell, Mapping) else None
    if not isinstance(policy, Mapping) or policy.get("enabled") is not True:
        raise ValueError("entry_planning.enabled=true 설정 없음")
    bounds = policy.get("tcp_clearance_above_top_range_m")
    required = ("tcp_z_step_m", "sample_m", "sample_deg", "min_radial_gap_m",
                "min_j3_abs_deg", "min_j5_margin_deg", "max_joint_step_deg",
                "start_position_tolerance_m", "start_angle_tolerance_deg")
    if (not _vector(bounds, 2) or bounds[0] <= 0 or bounds[0] > bounds[1]
            or any(not _finite(policy.get(key)) or policy[key] <= 0 for key in required)):
        raise ValueError("entry_planning 탐색·검사 범위 형식 오류")
    profile_id = policy.get("motion_profile_id")
    if not isinstance(profile_id, str) or not profile_id or profile_id not in motion_profiles:
        raise ValueError("entry_planning motion_profile_id가 실행 프로파일에 없음")
    if policy["tcp_z_step_m"] > bounds[1] - bounds[0] and not math.isclose(bounds[0], bounds[1]):
        raise ValueError("entry 후보 간격이 탐색 범위보다 큼")
    return copy.deepcopy(dict(policy))


def generate_entry_candidates(path, workcell, current_pose, tool_offset_m, motion_profiles):
    """실측 윗면에 대한 상대 범위에서 상공 entry 후보를 만든다. IK나 모션은 호출하지 않는다."""
    if not _pose(current_pose) or not _vector(tool_offset_m, 3):
        raise ValueError("현재 도구 끝 자세 또는 도구 오프셋 형식 오류")
    if path.get("frame_id") != "c2_base" or workcell.get("frame_id", "c2_base") != "c2_base":
        raise ValueError("entry 계획은 c2_base 경로만 지원")
    if (not _vector(workcell.get("axis_xy_m"), 2)
            or not _finite(workcell.get("radius_m")) or workcell["radius_m"] <= 0
            or not _finite(workcell.get("top_z_m"))):
        raise ValueError("실측 중심·반지름·윗면 높이 없음")
    home = workcell.get("home")
    if not isinstance(home, Mapping) or not _pose(home.get("tcp_pose")):
        raise ValueError("공용 workcell HOME TCP 자세 없음")
    policy = _policy(workcell, motion_profiles)
    home_tip = apply_tool_offset(list(home["tcp_pose"]), tool_offset_m, +1)
    if (math.dist(current_pose[:3], home_tip[:3]) > policy["start_position_tolerance_m"]
            or _quat_angle_deg(current_pose[3:7], home_tip[3:7]) > policy["start_angle_tolerance_deg"]):
        raise ValueError("현재 자세가 승인된 HOME 허용차 밖")
    approach = _first_approach(path)
    if approach is None:
        raise ValueError("첫 APPROACH waypoint 없음")
    approach_tcp = apply_tool_offset(approach, tool_offset_m, -1)
    low, high = policy["tcp_clearance_above_top_range_m"]
    step = policy["tcp_z_step_m"]
    count = int(math.floor((high - low) / step + 1e-9))
    clearances = [high - i * step for i in range(count + 1)]
    if not math.isclose(clearances[-1], low, abs_tol=1e-9):
        clearances.append(low)
    candidates = []
    config = path.get("config") if isinstance(path.get("config"), Mapping) else {}
    source_binding = {
        "path_id": path.get("path_id"),
        "path_version": path.get("path_version"),
        "profile_snapshot_id": config.get("profile_snapshot_id"),
        "profile_sha256": config.get("profile_sha256"),
        "axis_xy_m": list(workcell["axis_xy_m"]),
        "radius_m": workcell["radius_m"],
        "top_z_m": workcell["top_z_m"],
    }
    for index, clearance in enumerate(clearances):
        entry_tcp = list(approach_tcp)
        entry_tcp[2] = float(workcell["top_z_m"]) + clearance
        entry_tip = apply_tool_offset(entry_tcp, tool_offset_m, +1)
        samples = (_interpolate(list(current_pose), entry_tip, policy["sample_m"], policy["sample_deg"])
                   + _interpolate(entry_tip, approach, policy["sample_m"], policy["sample_deg"]))
        candidates.append({
            "candidate_id": f"entry-{index + 1:03d}",
            "frame_id": "c2_base",
            "motion_profile_id": policy["motion_profile_id"],
            "start_pose": list(current_pose),
            "entry_pose": entry_tip,
            "first_approach_pose": approach,
            "targets": [entry_tip],
            "validation_waypoints": samples,
            "tcp_clearance_above_top_m": clearance,
            "policy": policy,
            "source_binding": source_binding,
        })
    return candidates


def _segment_axis_gap(a, b, center, radius):
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    ratio = 0.0 if den < 1e-12 else max(0.0, min(1.0,
        ((center[0] - a[0]) * dx + (center[1] - a[1]) * dy) / den))
    return math.hypot(a[0] + ratio * dx - center[0],
                      a[1] + ratio * dy - center[1]) - radius


def _geometry_check(candidate, workcell, tool_offset_m):
    center = workcell["axis_xy_m"]
    radius = float(workcell["radius_m"])
    top = float(workcell["top_z_m"])
    policy = candidate["policy"]
    minimum = float(policy["min_radial_gap_m"])
    workspace = check_waypoints(candidate["validation_waypoints"], workcell.get("engraving_workspace"))
    if not workspace.ok:
        return workspace
    worst = float("inf")
    for index, tip in enumerate(candidate["validation_waypoints"]):
        tcp = apply_tool_offset(tip, tool_offset_m, -1)
        if min(tip[2], tcp[2]) <= top + 0.020:
            gap = _segment_axis_gap(tip, tcp, center, radius)
            worst = min(worst, gap)
            if gap < minimum:
                return StepResult("FAILED", "VALIDATION_FAILED",
                                  f"entry 도구-양초 간격 {gap * 1000:.1f} mm < {minimum * 1000:.1f} mm",
                                  "entry_check", {"sample_index": index, "radial_gap_m": gap})
    return StepResult("SUCCEEDED", "NONE", "entry 단순 형상 검사 통과", "entry_check",
                      {"minimum_radial_gap_m": None if math.isinf(worst) else worst,
                       "full_mesh_checked": False})


def _continuity_check(candidate, adapter, tool_offset_m, current_joints_rad, limits_deg, cancel):
    policy = candidate["policy"]
    previous = [math.degrees(v) for v in current_joints_rad]
    minimum_margin = float("inf")
    minimum_singularity = float("inf")
    for index, pose in enumerate(candidate["validation_waypoints"]):
        if cancel is not None and cancel.is_set():
            return StepResult("STOPPED", "NONE", "entry 검사 취소", "entry_check")
        joints = adapter.inverse_kinematics(pose, tool_offset_m, previous)
        if not _vector(joints, 6):
            return StepResult("FAILED", "NOT_READY", f"entry IK 실패: sample {index}", "entry_check")
        joints = list(joints)
        margins = [min(joints[k] - limits_deg[k][0], limits_deg[k][1] - joints[k]) for k in range(6)]
        minimum_margin = min(minimum_margin, *margins)
        j3 = abs(joints[2])
        j5 = min(abs(joints[4]), abs(180.0 - abs(joints[4])))
        minimum_singularity = min(minimum_singularity, j3, j5)
        if j3 < policy["min_j3_abs_deg"] or j5 < policy["min_j5_margin_deg"]:
            return StepResult("FAILED", "VALIDATION_FAILED",
                              f"entry 특이점 여유 부족: J3 {j3:.1f}°, J5 {j5:.1f}°", "entry_check",
                              {"sample_index": index, "j3_abs_deg": j3, "j5_margin_deg": j5})
        delta = max(abs(a - b) for a, b in zip(joints, previous))
        if delta > policy["max_joint_step_deg"]:
            return StepResult("FAILED", "VALIDATION_FAILED",
                              f"entry 관절 변화 {delta:.1f}° > {policy['max_joint_step_deg']:.1f}°", "entry_check",
                              {"sample_index": index, "max_joint_step_deg": delta})
        previous = joints
    return StepResult("SUCCEEDED", "NONE", "entry 연속성 검사 통과", "entry_check",
                      {"minimum_joint_margin_deg": minimum_margin,
                       "minimum_singularity_margin_deg": minimum_singularity,
                       "checked_samples": len(candidate["validation_waypoints"])})


def _plan_digest(plan):
    value = {key: value for key, value in plan.items() if key != "entry_plan_sha256"}
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def plan_entry_path(path, workcell, adapter, state, tool_offset_m, limits_deg,
                    j6_margin_deg, motion_profiles, cancel=None,
                    joint_check_fn=check_path_joints):
    """후보를 만들고 실제 IK 조건으로 검사해 하나를 확정한다. 모션 명령은 보내지 않는다."""
    try:
        if (state is None or state.quality != "VALID" or not _pose(state.tcp_pose)
                or not _vector(state.joints_rad, 6)):
            raise ValueError("유효한 현재 도구 끝 자세·관절 없음")
        candidates = generate_entry_candidates(path, workcell, state.tcp_pose,
                                               tool_offset_m, motion_profiles)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return StepResult("FAILED", "NOT_READY", str(exc), "entry_planning")
    accepted, rejected = [], []
    for candidate in candidates:
        geometry = _geometry_check(candidate, workcell, tool_offset_m)
        if not geometry.ok:
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": geometry.message})
            continue
        sampled = {
            "frame_id": "c2_base",
            "inspection_scope": "ENTRY_INTERPOLATION_SAMPLES",
            "segments": [{"segment_id": candidate["candidate_id"], "kind": "TRAVEL",
                          "movement_kind": "PROCESS_ENTRY", "stroke_id": None,
                          "applied_offset_m": None, "applied_depth_m": None,
                          "waypoints": candidate["validation_waypoints"]}],
        }
        joint_kwargs = dict(limits_deg=limits_deg, j6_margin_deg=j6_margin_deg)
        if joint_check_fn is check_path_joints:
            joint_kwargs["cancel"] = cancel
        joints = joint_check_fn(sampled, adapter, tool_offset_m, state.joints_rad,
                                **joint_kwargs)
        if not joints.ok:
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": joints.message})
            continue
        continuity = _continuity_check(candidate, adapter, tool_offset_m,
                                       state.joints_rad, limits_deg, cancel)
        if not continuity.ok:
            if continuity.outcome == "STOPPED":
                return continuity
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": continuity.message})
            continue
        plan = copy.deepcopy(candidate)
        plan["checks"] = {"geometry": geometry.observed_state,
                          "joint_check": joints.observed_state,
                          "continuity": continuity.observed_state}
        plan["score"] = [continuity.observed_state["minimum_singularity_margin_deg"],
                         continuity.observed_state["minimum_joint_margin_deg"],
                         candidate["tcp_clearance_above_top_m"]]
        accepted.append(plan)
    if not accepted:
        return StepResult("FAILED", "ENTRY_PATH_UNAVAILABLE", "실행 가능한 상공 entry 후보 없음",
                          "entry_planning", {"rejected_candidates": rejected})
    accepted.sort(key=lambda item: tuple(item["score"]), reverse=True)
    selected = accepted[0]
    selected["entry_plan_sha256"] = _plan_digest(selected)
    return StepResult("SUCCEEDED", "NONE", f"{selected['candidate_id']} entry 계획 확정",
                      "entry_planning", {"entry_plan": selected,
                                         "entry_plan_sha256": selected["entry_plan_sha256"],
                                         "accepted_candidates": len(accepted),
                                         "rejected_candidates": rejected})


def execute_entry_plan(plan, adapter, context):
    """검사·고정된 entry target만 실행한다. 후보 재탐색이나 좌표 변경은 하지 않는다."""
    if not isinstance(plan, Mapping) or plan.get("entry_plan_sha256") != _plan_digest(plan):
        return StepResult("FAILED", "PROFILE_MISMATCH", "entry 계획 해시 불일치", "entry")
    checked_offset = getattr(context, "checked_tool_offset_m", None)
    if (checked_offset is not None
            and list(getattr(adapter, "tool_offset_m", []) or []) != list(checked_offset)):
        return StepResult("FAILED", "PROFILE_MISMATCH",
                          "entry 검사 후 도구 오프셋 변경", "entry")
    profile_id = plan.get("motion_profile_id")
    profile = context.motion_profiles.get(profile_id)
    if not isinstance(profile, Mapping):
        return StepResult("FAILED", "PROFILE_MISMATCH", "entry 모션 프로파일 없음", "entry")
    try:
        timeout = float(profile["completion_timeout_s"])
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return StepResult("FAILED", "INVALID_INPUT", "entry 완료 제한 시간 오류", "entry")
    state = adapter.observe()
    policy = plan["policy"]
    if (state.quality != "VALID" or not _pose(state.tcp_pose)
            or math.dist(state.tcp_pose[:3], plan["start_pose"][:3]) > policy["start_position_tolerance_m"]
            or _quat_angle_deg(state.tcp_pose[3:7], plan["start_pose"][3:7]) > policy["start_angle_tolerance_deg"]):
        return StepResult("FAILED", "ROBOT_STATE_CHANGED",
                          "entry 검사 후 로봇 시작 자세 변경", "entry")
    for index, target in enumerate(plan["targets"]):
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "entry 이동 전 취소", "entry",
                              {"completed_targets": index})
        result = adapter.move(target, plan["frame_id"], dict(profile), timeout, context.cancel)
        if not isinstance(result, StepResult):
            return StepResult("UNKNOWN", "INVALID_RESULT", "entry 이동 결과 형식 오류", "entry")
        if not result.ok:
            observed = dict(result.observed_state)
            observed.update(entry_plan_sha256=plan["entry_plan_sha256"], completed_targets=index)
            return StepResult(result.outcome, result.error_code, result.message,
                              result.completed_step or "entry", observed)
    return StepResult("SUCCEEDED", "NONE", "검사된 상공 entry 이동 완료", "entry",
                      {"entry_plan_sha256": plan["entry_plan_sha256"],
                       "candidate_id": plan["candidate_id"],
                       "completed_targets": len(plan["targets"])})
