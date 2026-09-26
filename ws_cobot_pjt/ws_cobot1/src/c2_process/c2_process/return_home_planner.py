"""최종 RETRACT에서 승인된 HOME까지 이어지는 실행 전 복귀 계획.

ENTRY와 마찬가지로 PRECHECK에서 후보를 만들고 검사한 뒤 해시로 고정한다.
실행 단계에서는 현재 자세가 계획 시작점과 같은지 확인하고, 고정된 target만
소비한다. 후보 재탐색이나 좌표 재계산은 하지 않는다.
"""

import copy
import hashlib
import json
import math
import time
from typing import Mapping

from .engraving import (
    RETURN_MIN_ABOVE_TOP_M,
    RETURN_MIN_SURFACE_GAP_M,
    _geometry_ok,
    _home_steps,
)
from .engraving_workspace import check_waypoints, validate_workspace
from .entry_planner import _interpolate, _pose, _policy, _quat_angle_deg, _vector
from .joint_check import _unwrap, check_path_joints, evaluate_path_joints
from .robot_adapter import StepResult, apply_tool_offset


def _last_retract_pose(path):
    segments = path.get("segments") if isinstance(path, Mapping) else None
    if not isinstance(segments, list):
        return None
    for segment in reversed(segments):
        if not isinstance(segment, Mapping) or segment.get("kind") != "RETRACT":
            continue
        points = segment.get("waypoints")
        if isinstance(points, list) and points and _pose(points[-1]):
            return list(points[-1])
    return None


def _return_workcell(workcell, tool_offset_m):
    if not isinstance(workcell, Mapping):
        raise ValueError("복귀 workcell 형식 오류")
    value = copy.deepcopy(dict(workcell))
    if (not _vector(value.get("axis_xy_m"), 2)
            or not isinstance(value.get("radius_m"), (int, float))
            or not math.isfinite(value["radius_m"]) or value["radius_m"] <= 0):
        raise ValueError("복귀에 사용할 실측 중심·반지름 없음")
    if not _vector(tool_offset_m, 3):
        raise ValueError("복귀에 사용할 도구 오프셋 형식 오류")
    stored_offset = value.get("tool_offset_m")
    if not _vector(stored_offset, 3) or list(stored_offset) != list(tool_offset_m):
        raise ValueError("측정 workcell과 실행 도구 오프셋 불일치")
    # 시율 복귀 후보/형상 함수가 사용하는 seed 필드에는 이번 측정값을 넣는다.
    # 입력 객체는 복사했으므로 저장 측정 원본은 바뀌지 않는다.
    value["seed_axis_xy_m"] = list(value["axis_xy_m"])
    value["seed_radius_m"] = float(value["radius_m"])
    value["tool_offset_m"] = list(tool_offset_m)
    required = ("top_z_m", "bottom_z_m", "outer_gap_m", "slow_retract_gap_m",
                "home", "top")
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError("복귀 workcell 필드 없음: " + ", ".join(missing))
    validate_workspace(value.get("engraving_workspace"))
    return value


def _motion_samples(start_tip, target_tip, tool_offset_m, sample_m, sample_deg):
    """제어기 MoveL과 같이 TCP를 보간한 뒤 각 샘플의 도구 끝 자세를 계산한다."""
    start_tcp = apply_tool_offset(start_tip, tool_offset_m, -1)
    target_tcp = apply_tool_offset(target_tip, tool_offset_m, -1)
    return [apply_tool_offset(pose, tool_offset_m, +1)
            for pose in _interpolate(start_tcp, target_tcp, sample_m, sample_deg)]


def generate_return_home_candidates(execution_plan, workcell, tool_offset_m,
                                    motion_profiles):
    """마지막 RETRACT를 시작점으로 복귀 후보를 만든다. IK나 모션은 호출하지 않는다."""
    if execution_plan.get("frame_id") != "c2_base":
        raise ValueError("복귀 계획은 c2_base 경로만 지원")
    start = _last_retract_pose(execution_plan)
    if start is None:
        raise ValueError("최종 RETRACT waypoint 없음")
    normalized = _return_workcell(workcell, tool_offset_m)
    policy = _policy(normalized, motion_profiles)
    candidates = []
    candidate_index = 0
    rejected = []
    # 최신 main의 시율 복귀 생성기는 법선 후퇴 후보 네 가지를 제공한다.
    # 지원하지 않는 escape 인자를 추측해 넘기지 않고 현재 계약만 소비한다.
    for xy_first, yaw_alt in ((False, False), (True, False),
                              (False, True), (True, True)):
        candidate_index += 1
        candidate_id = f"return-home-{candidate_index:03d}"
        try:
            raw_steps = _home_steps(
                start, normalized,
                min_gap_m=RETURN_MIN_SURFACE_GAP_M,
                min_above_top_m=RETURN_MIN_ABOVE_TOP_M,
                yaw_alt=yaw_alt, xy_first=xy_first)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected.append({"candidate_id": candidate_id, "reason": str(exc)})
            continue
        if not raw_steps:
            rejected.append({"candidate_id": candidate_id,
                             "reason": "HOME과 RETRACT가 같아 복귀 target 없음"})
            continue
        sections = []
        targets = []
        previous = list(start)
        valid = True
        reason = ""
        for target, profile_id, label in raw_steps:
            if profile_id not in motion_profiles:
                valid, reason = False, f"복귀 모션 프로파일 {profile_id} 없음"
                break
            samples = _motion_samples(previous, list(target), tool_offset_m,
                                      policy["sample_m"], policy["sample_deg"])
            targets.append({"kind": "CARTESIAN", "label": label,
                            "motion_profile_id": profile_id,
                            "tip_pose": list(target)})
            sections.append({"label": label, "waypoints": samples})
            previous = list(target)
        if not valid:
            rejected.append({"candidate_id": candidate_id, "reason": reason})
            continue
        candidates.append({
            "candidate_id": candidate_id,
            "frame_id": "c2_base",
            "expected_start_tip_pose": list(start),
            "targets": targets,
            "validation_sections": sections,
            "validation_waypoints": [list(p) for s in sections for p in s["waypoints"]],
            "candidate": {"escape": "normal", "xy_first": xy_first,
                          "yaw_alt": yaw_alt},
            "policy": policy,
            "workspace": validate_workspace(normalized.get("engraving_workspace")),
        })
    return candidates, rejected, normalized


def _geometry_check(candidate, workcell):
    checked = 0
    worst_gap = float("inf")
    for section in candidate["validation_sections"]:
        workspace = check_waypoints(section["waypoints"], candidate["workspace"])
        if not workspace.ok:
            workspace.observed_state["return_label"] = section["label"]
            return workspace
        retreating = section["label"].startswith(("return_retreat", "return_escape"))
        box_z = not (retreating or section["label"] == "return_lift")
        previous_gap = None
        for index, pose in enumerate(section["waypoints"]):
            ok, reason, gap = _geometry_ok(
                pose, workcell, min_gap_m=RETURN_MIN_SURFACE_GAP_M,
                retreating=retreating, box_z=box_z)
            if gap is not None:
                worst_gap = min(worst_gap, gap)
                if (retreating and previous_gap is not None
                        and gap < previous_gap - 1e-6):
                    return StepResult(
                        "FAILED", "VALIDATION_FAILED",
                        f"{section['label']} sample {index}: 후퇴 중 표면 거리가 줄어듦",
                        "return_home_check",
                        {"return_label": section["label"], "sample_index": index,
                         "radial_gap_m": gap})
                previous_gap = gap
            if not ok:
                return StepResult(
                    "FAILED", "VALIDATION_FAILED",
                    f"{section['label']} sample {index}: {reason}", "return_home_check",
                    {"return_label": section["label"], "sample_index": index})
            checked += 1
    return StepResult(
        "SUCCEEDED", "NONE", "HOME 복귀 형상 검사 통과", "return_home_check",
        {"checked_samples": checked,
         "minimum_radial_gap_m": None if math.isinf(worst_gap) else worst_gap,
         "full_mesh_checked": False})


def _prefix_waypoints(entry_plan, execution_plan):
    points = []
    if isinstance(entry_plan, Mapping):
        values = entry_plan.get("validation_waypoints")
        if isinstance(values, list):
            points.extend(list(p) for p in values)
    for segment in execution_plan.get("segments", []):
        points.extend(list(p) for p in segment.get("waypoints", []))
    return points


def _predicted_end_joints(points, adapter, tool_offset_m, current_joints_rad, cancel):
    previous = [math.degrees(v) for v in current_joints_rad]
    for index, pose in enumerate(points):
        if cancel is not None and cancel.is_set():
            return StepResult("STOPPED", "NONE", "복귀 검사 취소", "return_home_check"), None
        joints = adapter.inverse_kinematics(pose, tool_offset_m, previous)
        if not _vector(joints, 6):
            return StepResult("FAILED", "NOT_READY",
                              f"복귀 시작 관절 예측 IK 실패: waypoint {index}",
                              "return_home_check"), None
        joints = list(joints)
        joints[5] = _unwrap(previous[5], joints[5])
        previous = joints
    return StepResult("SUCCEEDED"), previous


def _continuity_check(candidate, adapter, tool_offset_m, previous, limits_deg, cancel,
                      joints_sequence=None):
    policy = candidate["policy"]
    minimum_margin = float("inf")
    minimum_singularity = float("inf")
    checked = 0
    if joints_sequence is not None and len(joints_sequence) != len(candidate["validation_waypoints"]):
        return StepResult("UNKNOWN", "INVALID_RESULT",
                          "HOME 복귀 관절열과 표본 개수 불일치", "return_home_check")
    for index, pose in enumerate(candidate["validation_waypoints"]):
        if cancel is not None and cancel.is_set():
            return StepResult("STOPPED", "NONE", "복귀 검사 취소", "return_home_check")
        joints = (joints_sequence[index] if joints_sequence is not None
                  else adapter.inverse_kinematics(pose, tool_offset_m, previous))
        if not _vector(joints, 6):
            return StepResult("FAILED", "NOT_READY",
                              f"복귀 IK 실패: sample {index}", "return_home_check")
        joints = list(joints)
        joints[5] = _unwrap(previous[5], joints[5])
        margins = [min(joints[k] - limits_deg[k][0], limits_deg[k][1] - joints[k])
                   for k in range(6)]
        minimum_margin = min(minimum_margin, *margins)
        j3 = abs(joints[2])
        j5 = min(abs(joints[4]), abs(180.0 - abs(joints[4])))
        minimum_singularity = min(minimum_singularity, j3, j5)
        if j3 < policy["min_j3_abs_deg"] or j5 < policy["min_j5_margin_deg"]:
            return StepResult(
                "FAILED", "VALIDATION_FAILED",
                f"복귀 특이점 여유 부족: J3 {j3:.1f}°, J5 {j5:.1f}°",
                "return_home_check", {"sample_index": index,
                                       "j3_abs_deg": j3, "j5_margin_deg": j5})
        delta = max(abs(a - b) for a, b in zip(joints, previous))
        if delta > policy["max_joint_step_deg"]:
            return StepResult(
                "FAILED", "VALIDATION_FAILED",
                f"복귀 관절 변화 {delta:.1f}° > {policy['max_joint_step_deg']:.1f}°",
                "return_home_check", {"sample_index": index,
                                       "max_joint_step_deg": delta})
        previous = joints
        checked += 1
    return StepResult(
        "SUCCEEDED", "NONE", "HOME 복귀 연속성 검사 통과", "return_home_check",
        {"checked_samples": checked, "minimum_joint_margin_deg": minimum_margin,
         "minimum_singularity_margin_deg": minimum_singularity})


def _return_path(candidate):
    segments = []
    for index, section in enumerate(candidate["validation_sections"]):
        segments.append({"segment_id": f"return-{index:03d}", "kind": "TRAVEL",
                         "waypoints": copy.deepcopy(section["waypoints"])})
    return {"frame_id": "c2_base",
            "inspection_scope": "RETURN_HOME_INTERPOLATION_SAMPLES",
            "segments": segments}


def _plan_digest(plan):
    value = {key: value for key, value in plan.items()
             if key != "return_home_plan_sha256"}
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def plan_return_home_path(execution_plan, workcell, adapter, state, tool_offset_m,
                          limits_deg, j6_margin_deg, motion_profiles, *, entry_plan=None,
                          plan_signature=None, cancel=None, predicted_end_joints_deg=None,
                          joint_check_fn=check_path_joints):
    """ENTRY와 본경로로 예상한 마지막 관절에서 복귀 후보를 검사해 하나를 확정한다."""
    try:
        if (state is None or state.quality != "VALID" or not _pose(state.tcp_pose)
                or not _vector(state.joints_rad, 6)):
            raise ValueError("유효한 현재 도구 끝 자세·관절 없음")
        candidates, rejected, normalized = generate_return_home_candidates(
            execution_plan, workcell, tool_offset_m, motion_profiles)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return StepResult("FAILED", "NOT_READY", str(exc), "return_home_planning")

    prefix_ik_calls = 0
    prefix_ik_elapsed_s = 0.0
    if predicted_end_joints_deg is not None:
        if not _vector(predicted_end_joints_deg, 6):
            return StepResult("UNKNOWN", "INVALID_RESULT",
                              "재사용할 복귀 시작 관절값 형식 오류", "return_home_planning")
        final_joints = list(predicted_end_joints_deg)
    else:
        prefix = _prefix_waypoints(entry_plan, execution_plan)
        started = time.monotonic()
        predicted, final_joints = _predicted_end_joints(
            prefix, adapter, tool_offset_m, state.joints_rad, cancel)
        prefix_ik_elapsed_s = max(0.0, time.monotonic() - started)
        prefix_ik_calls = len(prefix) if predicted.ok else 0
        if not predicted.ok:
            return predicted

    accepted = []
    total_ik_calls = prefix_ik_calls
    total_ik_elapsed_s = prefix_ik_elapsed_s
    for candidate in candidates:
        geometry = _geometry_check(candidate, normalized)
        if not geometry.ok:
            rejected.append({"candidate_id": candidate["candidate_id"],
                             "reason": geometry.message})
            continue
        return_path = _return_path(candidate)
        kwargs = dict(limits_deg=limits_deg, j6_margin_deg=j6_margin_deg)
        if joint_check_fn is check_path_joints:
            kwargs["cancel"] = cancel
        joint_evaluation = None
        if joint_check_fn is check_path_joints:
            joint_evaluation = evaluate_path_joints(
                return_path, adapter, tool_offset_m,
                [math.radians(v) for v in final_joints], limits_deg=limits_deg,
                j6_margin_deg=j6_margin_deg, cancel=cancel)
            joints = joint_evaluation.result
            total_ik_calls += joint_evaluation.inverse_kinematics_calls
            total_ik_elapsed_s += joint_evaluation.elapsed_s
        else:
            joints = joint_check_fn(return_path, adapter, tool_offset_m,
                                    [math.radians(v) for v in final_joints], **kwargs)
        if not isinstance(joints, StepResult):
            return StepResult("UNKNOWN", "INVALID_RESULT",
                              "HOME 복귀 관절 검사 결과 형식 오류", "return_home_planning")
        if not joints.ok:
            if joints.outcome == "STOPPED":
                return joints
            rejected.append({"candidate_id": candidate["candidate_id"],
                             "reason": joints.message})
            continue
        continuity = _continuity_check(
            candidate, adapter, tool_offset_m, list(final_joints), limits_deg, cancel,
            None if joint_evaluation is None else joint_evaluation.joints_deg)
        if not continuity.ok:
            if continuity.outcome == "STOPPED":
                return continuity
            rejected.append({"candidate_id": candidate["candidate_id"],
                             "reason": continuity.message})
            continue
        selected = copy.deepcopy(candidate)
        selected["source_binding"] = {
            "path_id": execution_plan.get("path_id"),
            "path_version": execution_plan.get("path_version"),
            "profile_snapshot_id": (execution_plan.get("config") or {}).get(
                "profile_snapshot_id"),
            "profile_sha256": (execution_plan.get("config") or {}).get("profile_sha256"),
            "execution_plan_signature": plan_signature,
            "tool_offset_m": list(tool_offset_m),
            "axis_xy_m": list(normalized["axis_xy_m"]),
            "radius_m": normalized["radius_m"],
            "top_z_m": normalized["top_z_m"],
        }
        used_profiles = {target["motion_profile_id"] for target in selected["targets"]}
        selected["motion_profiles"] = {
            key: copy.deepcopy(dict(motion_profiles[key])) for key in sorted(used_profiles)}
        selected["checks"] = {"geometry": geometry.observed_state,
                              "joint_check": joints.observed_state,
                              "continuity": continuity.observed_state}
        selected["return_home_plan_sha256"] = _plan_digest(selected)
        accepted.append(selected)
        # 후보 우선순위는 기존 복귀 함수와 동일하게 normal→radial→lift_only,
        # 각 후보에서 align/xy 순서를 고정한다.
        break
    if not accepted:
        return StepResult(
            "FAILED", "RETURN_HOME_PATH_UNAVAILABLE", "실행 가능한 HOME 복귀 후보 없음",
            "return_home_planning", {"rejected_candidates": rejected})
    selected = accepted[0]
    return StepResult(
        "SUCCEEDED", "NONE", f"{selected['candidate_id']} HOME 복귀 계획 확정",
        "return_home_planning",
        {"return_home_plan": selected,
         "return_home_plan_sha256": selected["return_home_plan_sha256"],
         "rejected_candidates": rejected,
         "ik_metrics": {
             "inverse_kinematics_calls": total_ik_calls,
             "elapsed_s": total_ik_elapsed_s,
             "prefix_reused": predicted_end_joints_deg is not None,
         }})


def execute_return_home_plan(plan, adapter, context):
    """검사·고정된 HOME 복귀 target만 실행한다. 경로 재계산은 하지 않는다."""
    if (not isinstance(plan, Mapping)
            or plan.get("return_home_plan_sha256") != _plan_digest(plan)):
        return StepResult("FAILED", "PROFILE_MISMATCH",
                          "HOME 복귀 계획 해시 불일치", "return_home")
    binding = plan.get("source_binding")
    if not isinstance(binding, Mapping):
        return StepResult("FAILED", "PROFILE_MISMATCH",
                          "HOME 복귀 계획 원본 연결 없음", "return_home")
    checked_offset = getattr(context, "checked_tool_offset_m", None)
    adapter_offset = getattr(adapter, "tool_offset_m", None)
    if (checked_offset is None or list(checked_offset) != list(binding.get("tool_offset_m", []))
            or adapter_offset is None or list(adapter_offset) != list(checked_offset)):
        return StepResult("FAILED", "PROFILE_MISMATCH",
                          "HOME 복귀 검사 후 도구 오프셋 변경", "return_home")
    if (binding.get("execution_plan_signature") is not None
            and binding.get("execution_plan_signature")
            != getattr(context, "checked_plan_signature", None)):
        return StepResult("FAILED", "PROFILE_MISMATCH",
                          "HOME 복귀 검사 후 경로·설정 변경", "return_home")
    for profile_id, frozen in plan.get("motion_profiles", {}).items():
        current = context.motion_profiles.get(profile_id)
        if not isinstance(current, Mapping) or dict(current) != dict(frozen):
            return StepResult("FAILED", "PROFILE_MISMATCH",
                              f"HOME 복귀 모션 프로파일 변경: {profile_id}", "return_home")
    if getattr(adapter, "_hold_active", False) or getattr(adapter, "hold_active", False):
        return StepResult("UNKNOWN", "STOP_UNCONFIRMED",
                          "조각 힘/순응 해제 미확인", "return_home")
    try:
        state = adapter.observe()
    except Exception as exc:
        return StepResult("UNKNOWN", "COMMUNICATION_LOST", str(exc), "return_home")
    policy = plan.get("policy", {})
    expected = plan.get("expected_start_tip_pose")
    if (state.quality != "VALID" or state.robot_state != 1 or not _pose(state.tcp_pose)
            or not _pose(expected)
            or math.dist(state.tcp_pose[:3], expected[:3])
            > policy.get("start_position_tolerance_m", -1)
            or _quat_angle_deg(state.tcp_pose[3:7], expected[3:7])
            > policy.get("start_angle_tolerance_deg", -1)):
        return StepResult("FAILED", "ROBOT_STATE_CHANGED",
                          "조각 완료 자세가 검사된 RETRACT 시작점과 다름", "return_home")
    completed = []
    for index, target in enumerate(plan.get("targets", [])):
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "HOME 복귀 이동 전 취소", "return_home",
                              {"completed_targets": len(completed), "targets": completed})
        profile_id = target.get("motion_profile_id")
        profile = plan["motion_profiles"].get(profile_id)
        try:
            timeout = float(profile["completion_timeout_s"])
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return StepResult("FAILED", "INVALID_INPUT",
                              f"HOME 복귀 완료 제한 시간 오류: {profile_id}", "return_home")
        if target.get("kind") != "CARTESIAN" or not _pose(target.get("tip_pose")):
            return StepResult("FAILED", "INVALID_INPUT",
                              f"HOME 복귀 target 형식 오류: {index}", "return_home")
        result = adapter.move(list(target["tip_pose"]), plan["frame_id"],
                              copy.deepcopy(dict(profile)), timeout, context.cancel)
        if not isinstance(result, StepResult):
            return StepResult("UNKNOWN", "INVALID_RESULT",
                              "HOME 복귀 이동 결과 형식 오류", "return_home",
                              {"completed_targets": len(completed), "targets": completed})
        completed.append({"label": target.get("label"), "outcome": result.outcome,
                          "error_code": result.error_code, "message": result.message})
        if not result.ok:
            return StepResult(result.outcome, result.error_code,
                              f"{target.get('label')}: {result.message}", "return_home",
                              {"completed_targets": index, "targets": completed,
                               "return_home_plan_sha256": plan["return_home_plan_sha256"]})
        if context.cancel.is_set():
            return StepResult("UNKNOWN", "STOP_UNCONFIRMED",
                              f"{target.get('label')} 성공 응답 뒤 취소", "return_home",
                              {"completed_targets": index + 1, "targets": completed})
    return StepResult(
        "SUCCEEDED", "NONE", "검사된 HOME 복귀 완료", "return_home",
        {"return_home_plan_sha256": plan["return_home_plan_sha256"],
         "candidate_id": plan["candidate_id"],
         "completed_targets": len(completed), "targets": completed})
