# engraving.py — 확정된 실행 경로(path.json)의 조각 실행·진행 보고. 담당: 이시율 (초안 2026-09-18, main 이관 2026-09-19).
# PR #73 후보: CUT 중 법선 힘 유지(MoveSX + 순응/힘 제어)·세은 검사 서명 재사용·안전 홈 복귀(return_home).
#   cut_contact 가 없는 기존 프로파일은 이전과 같은 '획 시작 접촉 offset 고정' 방식으로 실행된다 (호환).
# 9/19 결정: 기준 도구 engraving_drill(철사 고정, 집기·반납·청소 없음), 도구 축은 tools.yaml 의 tool_axis(팀 규칙 툴 -Y = 표면 안쪽),
# frame_id c2_base. 실기 성공 조건(9/18 드릴 하트): 획 시작 터치 1.5 mm/s·0.8 N, 긋기 6.6 mm/s, 접근 여유 6 mm.
# 상태 기계가 execute_path(path, context, on_progress) 를 함수로 부른다. 새 ROS 통신을 만들지 않는다.
# 원본 표면 경로는 보존하고 실행용 깊이/접촉 계획을 따로 검사한다. 명령은 robot_adapter만 사용한다.
#
# 실행 규칙 (INTERFACE_RECOMMENDATION v1 §4·§5·§9):
#   - 구간(segment) 종류: APPROACH / CUT / TRAVEL / RETRACT. 순서가 고정이고 서로 떨어진 획을 암묵적으로 잇지 않는다.
#   - waypoint 는 m + quaternion(x,y,z,w), frame_id 는 path 의 값. 단위 변환은 robot_adapter 가 한다.
#   - 접촉 방식은 가공 프로파일의 contact_mode 만 실행: force_touch(획마다 힘 감시로 표면 찾기) / fixed_depth(표면점에서
#     법선 안쪽으로 depth_mm). 프로파일이 없거나 미지원이면 UNSUPPORTED_RECIPE 로 거절하고 움직이지 않는다.
#   - 취소(context.cancel)·실패·제한 시간 초과 시 새 명령을 보내지 않고 마지막 완료 구간만 기록한다. 자동 재개 없음.
#   - 진행률 = 완료한 CUT 길이 / 전체 CUT 길이. 조각 100% 와 전체 공정 성공은 다르다 (상태 기계가 판단).
import math
import copy
import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .robot_adapter import RobotAdapter, StepResult, tool_axis_in_base

SUPPORTED_SCHEMA = (2,)                 # 9/19 고정 드릴 계약 v2 (INTERFACE_RECOMMENDATION 13절). v1 은 묵시 변환 없이 거절
SEGMENT_KINDS = ("APPROACH", "CUT", "TRAVEL", "RETRACT")
CONTACT_MODES = ("force_touch", "fixed_depth")
CUT_CONTACT_MODES = ("normal_force_hold", "chunk_adaptive")   # 9/22: CUT 중 법선 보정 방식 (아래 execute_path 주석)
CUT_MOTION_MODES = ("movesx", "movel")     # 9/23: CUT 이동 명령. movesx(기본) = 스플라인 묶음, movel = 직선 구간별 MoveL (순응 검증용 네모 시험)


def collapse_collinear(points, tol_m):
    """연속 waypoint 중 한 직선(현) 위에 tol_m 안으로 놓이는 점들을 하나의 MoveL 목표로 합친다. 위치·자세·순서는 원본 그대로,
    끝점만 남긴다. 곡면 위 호는 tol_m 에 맞는 여러 현으로 나뉜다 (R 34 mm·0.1 mm 이면 현 약 3.7 mm)."""
    out = []; i = 0; n = len(points)
    while i < n - 1:
        k = i + 1
        while k + 1 < n:
            a, b = points[i], points[k + 1]
            ab = [b[j] - a[j] for j in range(3)]; L2 = sum(v * v for v in ab)
            ok = True
            for m in range(i + 1, k + 1):
                pm = points[m]; ap = [pm[j] - a[j] for j in range(3)]
                t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, sum(ap[j] * ab[j] for j in range(3)) / L2))
                if math.dist(pm[:3], [a[j] + ab[j] * t for j in range(3)]) > tol_m:
                    ok = False; break
            if not ok:
                break
            k += 1
        out.append(list(points[k])); i = k
    return out
MAX_SPLINE_POINTS = 80                 # 제어기 movesx 한도 100 (9/17 실측) 에 여유


@dataclass
class ExecutionContext:
    """상태 기계가 만들어 넘기는 실행 맥락. (정식 정의 위치는 상태 기계 쪽으로 옮길 수 있음 — 제안서 4절)"""
    run_id: str
    source_mode: str                                   # "SIMULATION" | "REAL"
    cancel: threading.Event
    motion_profiles: Dict[str, Dict]                   # motion_profile_id → {vel_mm_s, acc_mm_s2, completion_timeout_s, ...}
    tool_profile: Dict                                 # tools.yaml 스냅샷의 도구 항목 (contact_mode, tool_axis, depth_mm, ...)
    stop_profile: Dict = field(default_factory=lambda: {"mode": 2, "confirmation_timeout_s": 2.0})
    checked_plan_signature: Optional[str] = None
    checked_tool_offset_m: Optional[List] = None
    joint_limits_deg: Optional[List] = None
    j6_margin_deg: float = 10.0
    path_binding: Dict = field(default_factory=dict)


@dataclass
class _Progress:
    total_cut_m: float = 0.0
    done_cut_m: float = 0.0
    completed_segment_id: str = ""
    phase: str = "APPROACH"


def _dist(a, b):
    return math.dist(a[:3], b[:3])


def _seg_length(wps):
    return sum(_dist(wps[i], wps[i + 1]) for i in range(len(wps) - 1))


def _shift(pose, direction, meters):
    p = list(pose)
    for k in range(3):
        p[k] += direction[k] * meters
    return p


# ---------------------------------------------------------------- 검사 ----
def _m(profile: Dict, name: str, default=None):
    """거리 필드를 m 로 읽는다: `<name>_m` 우선, 없으면 `<name>_mm`/1000 (v1 호환), 둘 다 없으면 default.
    clearance_m 은 세은님 tools.yaml 에서 {stroke, process_entry_exit} 딕셔너리일 수 있어 stroke 값을 쓴다."""
    v = profile.get(f"{name}_m")
    if isinstance(v, dict):
        v = v.get("stroke", v.get("value"))
    if v is None and profile.get(f"{name}_mm") is not None:
        v = float(profile[f"{name}_mm"]) / 1000.0
    return default if v is None else float(v)


def _cut_contact_profile_error(profile, contact_mode):
    """CUT 중 보정 설정을 정적 검사한다. 로봇 조회나 기본값 보정은 하지 않는다."""
    cut_contact = profile.get("cut_contact")
    if cut_contact is None:
        return None
    if cut_contact not in CUT_CONTACT_MODES:
        return f"cut_contact {cut_contact!r} 미지원 ({CUT_CONTACT_MODES})"
    if contact_mode != "force_touch":
        return "cut_contact는 force_touch에서만 사용 가능"
    if profile.get("tool_axis") not in ("x", "+x", "-x", "y", "+y", "-y", "z", "+z", "-z"):
        return f"cut_contact {cut_contact}: tool_axis는 ±x/±y/±z 명시 필요"

    def finite_number(value):
        return type(value) in (int, float) and math.isfinite(value)

    for key in ("force_limit_n", "air_force_limit_n"):
        if not finite_number(profile.get(key)) or profile[key] <= 0:
            return f"cut_contact {cut_contact}: {key}는 유한한 양수 필요"
    bounds = profile.get("touch_offset_range_m")
    try:
        clearance = _m(profile, "clearance")
        extra = _m(profile, "touch_extra")
    except (TypeError, ValueError):
        return f"cut_contact {cut_contact}: clearance_m/touch_extra_m 형식 오류"
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
            or any(not finite_number(v) for v in bounds) or bounds[0] > bounds[1]
            or clearance is None or not math.isfinite(clearance) or clearance <= 0
            or extra is None or not math.isfinite(extra) or extra < 0
            or bounds[0] < -clearance or bounds[1] > extra):
        return (f"cut_contact {cut_contact}: touch_offset_range_m은 "
                "[-clearance_m, touch_extra_m] 범위의 유한한 [최소, 최대]여야 함")
    if cut_contact == "normal_force_hold":
        force = profile.get("cut_force_n")
        stiffness = profile.get("cut_stiffness")
        ramp = profile.get("ramp_s")
        if not finite_number(force) or force <= 0:
            return "cut_contact normal_force_hold: cut_force_n은 유한한 양수 필요"
        if (not isinstance(stiffness, (list, tuple)) or len(stiffness) != 6
                or any(not finite_number(v) or v < 0 for v in stiffness)):
            return "cut_contact normal_force_hold: cut_stiffness는 0 이상 유한값 6개 필요"
        if not finite_number(ramp) or not 0 <= ramp <= 1:
            return "cut_contact normal_force_hold: ramp_s는 0~1 유한값 필요"
    else:
        low = profile.get("cut_force_min_n")
        high = profile.get("cut_force_max_n")
        step = profile.get("adaptive_step_m")
        points = profile.get("adaptive_chunk_points")
        if (not finite_number(low) or low <= 0 or not finite_number(high)
                or high <= 0 or low > high):
            return "cut_contact chunk_adaptive: cut_force_min_n <= cut_force_max_n 양수 범위 필요"
        if not finite_number(step) or step <= 0:
            return "cut_contact chunk_adaptive: adaptive_step_m은 유한한 양수 필요"
        if type(points) is not int or not 2 <= points <= MAX_SPLINE_POINTS:
            return f"cut_contact chunk_adaptive: adaptive_chunk_points는 2~{MAX_SPLINE_POINTS} 정수 필요"
    return None


def validate_path(path: Dict, context: ExecutionContext) -> Optional[StepResult]:
    """실행 전 형식 검사. 문제가 있으면 StepResult(FAILED, ...) 를, 없으면 None 을 반환. 로봇을 건드리지 않는다."""
    if path.get("schema_version") not in SUPPORTED_SCHEMA:
        return StepResult("FAILED", "UNSUPPORTED_SCHEMA_VERSION", f"schema_version {path.get('schema_version')}", "validate")
    if path.get("position_unit") != "m" or path.get("orientation") != "quaternion_xyzw":
        return StepResult("FAILED", "INVALID_INPUT", "position_unit=m, orientation=quaternion_xyzw 만 지원", "validate")
    if not path.get("frame_id"):
        return StepResult("FAILED", "INVALID_INPUT", "frame_id 없음", "validate")
    if path.get("source_mode") not in (None, context.source_mode):
        return StepResult("FAILED", "PROFILE_MISMATCH", f"경로 source_mode {path.get('source_mode')} ≠ 실행 {context.source_mode}", "validate")
    tp = context.tool_profile or {}
    # 도구 ID 대조 (9/19 팀 결정: 기준 도구 engraving_drill). 경로와 도구 프로파일 양쪽에 tool_id 가 있으면 같아야 한다.
    if path.get("tool_id") and tp.get("tool_id") and path["tool_id"] != tp["tool_id"]:
        return StepResult("FAILED", "PROFILE_MISMATCH", f"경로 tool_id {path['tool_id']!r} ≠ 도구 프로파일 {tp['tool_id']!r}", "validate")
    mode = tp.get("contact_mode")
    if mode not in CONTACT_MODES:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", f"contact_mode {mode!r} 미지원 ({CONTACT_MODES})", "validate")
    if mode == "fixed_depth" and _m(tp, "depth") is None:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", "fixed_depth 인데 depth_m 없음", "validate")
    if context.source_mode == "REAL" and _m(tp, "clearance") is None:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", "가공 프로파일에 clearance_m 없음 (REAL 은 기본값 주입 안 함)", "validate")
    if mode == "force_touch" and context.source_mode == "REAL":
        for k in ("touch_force_n", "touch_speed_mm_s"):
            if tp.get(k) is None:
                return StepResult("FAILED", "UNSUPPORTED_RECIPE", f"force_touch 인데 {k} 없음", "validate")
    cut_contact_error = _cut_contact_profile_error(tp, mode)
    if cut_contact_error:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", cut_contact_error, "validate")
    cut_contact = tp.get("cut_contact")
    cut_motion = tp.get("cut_motion")
    if cut_motion is not None and cut_motion not in CUT_MOTION_MODES:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", f"cut_motion {cut_motion!r} 미지원 ({CUT_MOTION_MODES})", "validate")
    if cut_motion == "movel" and _m(tp, "movel_chord_tol") is None:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", "cut_motion movel 인데 movel_chord_tol_m 없음", "validate")
    if tp.get("hold_retreat_target_m") is not None:
        lo, hi = tp["touch_offset_range_m"]
        target = _m(tp, "hold_retreat_target")
        tolerance = _m(tp, "hold_retreat_tolerance")
        margin = _m(tp, "hold_correction_margin", 0.002)
        if (cut_contact != "normal_force_hold" or tolerance is None
                or not all(math.isfinite(v) for v in (target, tolerance, margin))
                or tolerance <= 0 or margin < 0 or not lo <= target < target + tolerance < hi):
            return StepResult("FAILED", "INVALID_INPUT", "후퇴 목표·확인 허용오차·정상 상한 설정 오류", "validate")
    segs = path.get("segments") or []
    if not segs:
        return StepResult("FAILED", "INVALID_INPUT", "segments 비어 있음", "validate")
    for s in segs:
        if s.get("kind") not in SEGMENT_KINDS:
            return StepResult("FAILED", "INVALID_INPUT", f"segment {s.get('segment_id')} kind {s.get('kind')!r}", "validate")
        wps = s.get("waypoints") or []
        if len(wps) < 1 or any(len(w) != 7 for w in wps):
            return StepResult("FAILED", "INVALID_INPUT", f"segment {s.get('segment_id')} waypoint 형식 (7개 값 필요)", "validate")
        if s["kind"] == "CUT" and len(wps) < 2:
            return StepResult("FAILED", "INVALID_INPUT", f"CUT {s.get('segment_id')} 는 점 2개 이상", "validate")
        pid = s.get("motion_profile_id")
        if pid not in context.motion_profiles:
            return StepResult("FAILED", "PROFILE_MISMATCH", f"segment {s.get('segment_id')} motion_profile_id {pid!r} 없음", "validate")
        if context.source_mode == "REAL" and context.motion_profiles[pid].get("completion_timeout_s") is None:
            return StepResult("FAILED", "UNSUPPORTED_RECIPE", f"profile {pid} 에 completion_timeout_s 없음 (REAL 거절)", "validate")
    return None


def execution_signature(path, context):
    """원본 경로와 실행 설정을 결합한다. 파일 바이트 해시는 node의 path_binding으로 보존."""
    data = [path, context.tool_profile, context.motion_profiles, context.stop_profile,
            context.path_binding, context.run_id, context.source_mode,
            context.joint_limits_deg, context.j6_margin_deg, context.checked_tool_offset_m]
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def cut_points(segment, tool_profile, offset_m):
    """표면점 → 도구 축 방향 최종점. 원본은 변경하지 않는다."""
    return [_shift(w, tool_axis_in_base(w, tool_profile.get("tool_axis", "-y")), offset_m)
            for w in segment["waypoints"]]


def build_execution_plan(path, context):
    """순수 변환. fixed는 최종 명령점, force는 경계 후보(연속 안전 증명 아님).

    반환은 내부 검사 전용 경로 또는 실패 StepResult. 이 경로를 원본으로 재입력하지 않는다.
    touch_offset_range_m은 획별 법선 보정의 명시적 [최소, 최대] m 계약이다.
    """
    if path.get("inspection_scope"):
        return StepResult("FAILED", "INVALID_INPUT", "실행 계획을 표면 경로로 재입력할 수 없음", "execution_plan")
    try:
        err = validate_path(path, context)
    except (ValueError, TypeError, KeyError):
        return StepResult("FAILED", "INVALID_INPUT", "경로/프로파일 형식 오류", "execution_plan")
    if err:
        return err
    if not any(s["kind"] == "CUT" for s in path["segments"]):
        return StepResult("FAILED", "INVALID_INPUT", "CUT 없는 경로", "execution_plan")
    tp = context.tool_profile
    mode = tp["contact_mode"]
    try:
        depth = _m(tp, "depth", 0.0)
        if not math.isfinite(depth) or depth < 0:
            raise ValueError("depth_m은 유한한 0 이상의 값이어야 함")
        bounds = tp.get("touch_offset_range_m")
        dual = tp.get("entry_confirmation") == "force_and_position"
        # 9/22 승격 호환: force_touch 에서 접촉 offset 에 depth_m 을 더하는 것은 cut_contact 프로파일에서만 한다.
        # cut_contact 없는 기존 프로파일은 종전(main)과 같이 접촉점을 그대로 실행 깊이로 쓴다 (팀 test_node 계약).
        depth_add = depth if (mode == "force_touch" and tp.get("cut_contact") is not None) else 0.0
        if mode == "force_touch":
            clearance, extra = _m(tp, "clearance"), _m(tp, "touch_extra")
            if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
                    or bounds[0] > bounds[1] or clearance is None or extra is None
                    or not math.isfinite(clearance) or not math.isfinite(extra)
                    or clearance <= 0 or extra < 0
                    or bounds[0] < -clearance or bounds[1] > extra):
                return StepResult("FAILED", "NOT_READY", "force_touch: 명시적 touch_offset_range_m, clearance_m, touch_extra_m 필요",
                                  "execution_plan", {"inspection_scope": "UNPLANNED_DYNAMIC"})
        if dual and (mode != "force_touch" or bounds[0] < depth or extra <= depth):
            return StepResult("FAILED", "INVALID_INPUT", "복합 진입은 깊이 이상 보정 범위와 추가 탐색 상한 필요", "execution_plan")
        plan = copy.deepcopy(path)
        plan["inspection_scope"] = "FINAL_EXECUTION_PLAN" if mode == "fixed_depth" else "BOUNDED_FORCE_TOUCH_CANDIDATES"
        plan["segments"] = []
        seen = set()
        def append(seg, points, movement, offset=None):
            item = dict(seg, waypoints=points, movement_kind=movement, applied_offset_m=offset,
                        applied_depth_m=depth if movement in ("CUT_ENTRY_AND_CUT", "CUT_OFFSET_BOUND") else None)
            plan["segments"].append(item)
        for seg in path["segments"]:
            if any(any(type(v) not in (float, int) or not math.isfinite(v) for v in w) for w in seg["waypoints"]):
                raise ValueError("waypoint는 유한한 숫자여야 함")
            if seg["kind"] != "CUT":
                # 후퇴·이동 뒤 재진입은 같은 stroke_id라도 새 접촉 판정 구간이다.
                seen.clear()
                append(seg, copy.deepcopy(seg["waypoints"]), seg["kind"])
                continue
            stroke = seg.get("stroke_id", seg.get("segment_id", "?"))
            if mode == "fixed_depth":
                # 첫 점은 명시적 move, 나머지는 spline/chunk. 모두 이 목록에 포함.
                append(seg, cut_points(seg, tp, depth), "CUT_ENTRY_AND_CUT", depth)
            else:
                first = dict(seg, waypoints=seg["waypoints"][:1])
                if stroke not in seen:
                    append(first, cut_points(first, tp, -clearance), "PROBE_START", -clearance)
                    append(first, cut_points(first, tp, extra), "PROBE_END_BOUND", extra)
                for off in bounds:
                    append(seg, cut_points(seg, tp, off if dual else off + depth_add), "CUT_OFFSET_BOUND", off if dual else off + depth_add)
            seen.clear()
            seen.add(stroke)
        return plan
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return StepResult("FAILED", "INVALID_INPUT", str(exc), "execution_plan")


def _check_plan(plan, context, adapter):
    from .joint_check import check_path_joints
    try:
        return check_path_joints(plan, adapter, getattr(adapter, "tool_offset_m", None),
                                 adapter.observe().joints_rad, limits_deg=context.joint_limits_deg,
                                 j6_margin_deg=context.j6_margin_deg, cancel=context.cancel)
    except Exception as exc:
        return StepResult("UNKNOWN", "VALIDATION_UNAVAILABLE", f"IK 결과 확인 불가: {exc}",
                          "joint_check", {"inspection_scope": plan["inspection_scope"]})


# ---------------------------------------------------------------- 실행 ----
def execute_path(path: Dict, context: ExecutionContext, on_progress: Optional[Callable[[Dict], None]] = None,
                 adapter: RobotAdapter = None) -> StepResult:
    """경로의 구간을 순서대로 실행한다. 반환 StepResult.observed_state 에 last_completed_segment_id, engraving_progress,
    touches(획별 접촉 기록) 가 들어간다. outcome: SUCCEEDED / FAILED / STOPPED / UNKNOWN."""
    # 공정 호출 형식은 유지하고 기존 가공 설정으로 실행기를 선택한다.
    # 설정 선택은 snapshot/계획 검사 전에 끝나야 하며 실행 실패 중 자동 교체하지 않는다.
    if (context.tool_profile or {}).get("contact_mode") == "fixed_depth":
        return execute_fixed_depth_path(path, context, on_progress, adapter)
    if adapter is None:
        return StepResult("FAILED", "NOT_READY", "robot_adapter 없음", "execute_path")
    plan = build_execution_plan(path, context)
    if isinstance(plan, StepResult):
        return plan
    try:
        signature = execution_signature(path, context)
    except (ValueError, TypeError):
        return StepResult("FAILED", "INVALID_INPUT", "경로/설정 fingerprint 생성 불가", "execution_plan")
    if context.checked_plan_signature is not None and context.checked_plan_signature != signature:
        return StepResult("FAILED", "PROFILE_MISMATCH", "검사 후 경로/설정 변경", "execution_plan")
    offset_before = copy.deepcopy(getattr(adapter, "tool_offset_m", None))
    if context.checked_plan_signature is not None and offset_before != context.checked_tool_offset_m:
        return StepResult("FAILED", "PROFILE_MISMATCH", "검사한 도구 오프셋과 실행 어댑터 불일치", "execution_plan")
    # 동일 계획·도구의 검사 완료 서명이 있으면 전체 후보 IK를 반복하지 않는다.
    # 접촉 후 달라진 실제 획은 아래 DYNAMIC_STROKE_FINAL 검사로 별도 확인한다.
    if context.checked_plan_signature is None:
        checked = _check_plan(plan, context, adapter)
        if not checked.ok:
            return checked
    def guard():
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "취소 후 새 검사/모션 차단", "execution_plan")
        try:
            current_signature = execution_signature(path, context)
        except (ValueError, TypeError):
            current_signature = None
        if (current_signature != signature
                or getattr(adapter, "tool_offset_m", None) != offset_before):
            return StepResult("FAILED", "PROFILE_MISMATCH", "검사 후 경로/설정/도구 오프셋 변경", "execution_plan")
        return None
    tp = context.tool_profile
    axis_name = tp.get("tool_axis", "-y")            # 도구가 향하는 축 (9/19 팀 규칙: 툴 -Y = 표면 안쪽). tools.yaml 값이 우선 (경로 자세에서 표면 법선 안쪽을 가리켜야 함)
    mode = tp["contact_mode"]
    clearance_m = _m(tp, "clearance", 0.010)          # v2: 거리 필드는 m (clearance_m). *_mm 는 과도기 호환
    touch_extra_m = _m(tp, "touch_extra", 0.008)
    depth_m = _m(tp, "depth", 0.0)
    frame = path["frame_id"]
    segs = plan["segments"] if mode == "fixed_depth" else path["segments"]
    prog = _Progress(total_cut_m=sum(_seg_length(s["waypoints"]) for s in segs if s["kind"] == "CUT"))
    touches: List[Dict] = []
    stroke_offset: Dict[str, float] = {}             # stroke_id → 법선 방향 보정량 (m, + 는 표면 안쪽)
    stroke_bias: Dict[str, List[float]] = {}         # stroke_id → 획 시작 전 무접촉 힘 편향 (base, N)
    hold = dict(active=False, released=True, force_n=None)   # 법선 힘 유지 상태 (9/22) + 현재 힘 목표 (9/23 보정)
    cut_contact = tp.get("cut_contact")              # None(구형: 획당 offset 고정) / normal_force_hold / chunk_adaptive
    t_start = time.monotonic()
    verified_retreat = tp.get("hold_retreat_target_m") is not None

    def normal_dev_now(wps_, normals_):
        state = adapter.observe()
        cur = state.tcp_pose
        if (state.quality != "VALID" or (verified_retreat and state.robot_state != 1) or not cur or len(cur) != 7
                or not all(math.isfinite(v) for v in cur)):
            raise ValueError("후퇴 위치 관측 무효")
        i = min(range(len(wps_)), key=lambda k: math.dist(cur[:3], wps_[k][:3]))
        n = normals_[i]
        return sum((cur[k] - wps_[i][k]) * n[k] for k in range(3)), cur, i, n

    def retreat_to_band(seg, wps_, normals_, target_off, tol=0.0005, tries=3):
        """9/23: 실제 법선 위치를 target_off(후퇴 목표) 근처까지 위치 제어로 빼고, 다시 읽어 확인한다. 힘 유지는 꺼져 있어야 한다.
        반환 (ok, dev, moves)."""
        try:
            moves = []
            if verified_retreat:
                tol = _m(tp, "hold_retreat_tolerance")
            for _ in range(tries):
                if context.cancel.is_set():
                    return False, float("nan"), moves
                dev, cur, i, n = normal_dev_now(wps_, normals_)
                if verified_retreat and not (-abs(_m(tp, "normal_hard_limit", touch_extra_m)) <= dev <= abs(_m(tp, "normal_hard_limit", touch_extra_m))):
                    return False, dev, moves
                if dev <= target_off + tol:
                    return True, dev, moves
                retreat_profile = context.motion_profiles[seg["motion_profile_id"]]
                if verified_retreat:
                    hard = abs(_m(tp, "normal_hard_limit", touch_extra_m))
                    retreat_profile = dict(retreat_profile, contact_monitor=dict(
                        kind="CUT", bias=list(stroke_bias.get(seg.get("stroke_id", seg.get("segment_id"))) or [0.0] * 3),
                        force_limit_n=float(tp["force_limit_n"]), surface=wps_, normals=normals_,
                        offset_range=[-hard, hard], samples=[]))
                rr = adapter.move(_shift(cur, n, -(dev - target_off)), frame, retreat_profile, deadline_of(seg), context.cancel)
                moves.append(dict(before_mm=round(dev * 1000, 2), outcome=rr.outcome))
                if not rr.ok:
                    return False, dev, moves
            dev, _, _, _ = normal_dev_now(wps_, normals_)
            hard = abs(_m(tp, "normal_hard_limit", touch_extra_m))
            return (dev <= target_off + tol and (not verified_retreat or -hard <= dev <= hard)), dev, moves
        except Exception as exc:
            moves.append(dict(error=str(exc)))
            return False, float("nan"), moves

    def confirm_retreat_ready(seg):
        """정지 요청 → 힘/순응 해제 → 실제 정지 확인. 하나라도 불명확하면 후퇴/재개하지 않는다."""
        hold["released"] = False
        try:
            adapter.stop(context.stop_profile, 2.0)
            released = adapter.hold_normal_force_end(2.0)
            if not released.ok or released.observed_state.get("force_released") is not True:
                return False
            hold["active"] = False
            stopped = adapter.stop(context.stop_profile, 2.0)
            if not stopped.ok or stopped.observed_state.get("stop_confirmed") is not True:
                return False
            hold["released"] = True
            return True
        except Exception:
            return False

    def release_hold(seg):
        """힘 유지 해제. 실패하면 이후 어떤 이동도 보내지 않도록 hold['released']=False 로 남긴다."""
        if not hold["active"]:
            return None
        r = adapter.hold_normal_force_end(deadline_of(seg))
        hold["active"] = False
        hold["released"] = r.observed_state.get("force_released") is True
        return r

    def report(phase):
        prog.phase = phase
        if on_progress:
            on_progress(dict(phase=phase, completed_segment_id=prog.completed_segment_id,
                             engraving_progress=(prog.done_cut_m / prog.total_cut_m) if prog.total_cut_m > 0 else 0.0,
                             elapsed_s=time.monotonic() - t_start))

    def finish(outcome, code, msg, step):
        return StepResult(outcome, code, msg, step,
                          dict(last_completed_segment_id=prog.completed_segment_id,
                               engraving_progress=(prog.done_cut_m / prog.total_cut_m) if prog.total_cut_m > 0 else 0.0,
                               touches=touches, elapsed_s=time.monotonic() - t_start,
                               inspection_scope=plan["inspection_scope"], plan_signature=signature,
                               hold_released=hold["released"], cut_contact=cut_contact,
                               normal_range_continuity_verified=False))   # 세은 검사는 범위 양 끝만 IK 검사 (미구현: 연속 증명)

    def profile_of(seg):
        return context.motion_profiles[seg["motion_profile_id"]]

    def deadline_of(seg):
        return float(profile_of(seg).get("completion_timeout_s", 60.0))

    for segment_index, seg in enumerate(segs):
        sid, kind, wps = seg.get("segment_id", "?"), seg["kind"], seg["waypoints"]
        stroke = seg.get("stroke_id", sid)
        if context.cancel.is_set():
            return finish("STOPPED", "NONE", f"취소됨 (구간 {sid} 전)", f"segment:{sid}")
        prof = profile_of(seg)

        if kind in ("APPROACH", "TRAVEL", "RETRACT"):
            # 연속 CUT 동안만 보정값을 재사용한다. 공중 이동 후에는 다시 판정한다.
            stroke_offset.clear()
            # 9/22: 힘 유지가 켜진 채로는 공중 이동을 보내지 않는다. 해제가 확인되지 않으면 여기서 멈춘다.
            r = release_hold(seg)
            if r is not None and not hold["released"]:
                return finish("UNKNOWN", "STOP_UNCONFIRMED", f"{kind} {sid} 전 힘/순응 해제 미확인: {r.message}", f"segment:{sid}")
            report({"APPROACH": "APPROACH", "TRAVEL": "ENGRAVE", "RETRACT": "RETRACT"}[kind])
            air_prof = prof
            if cut_contact is not None and tp.get("air_force_limit_n") is not None:
                # RETRACT/AIR 감시: 접촉이 풀리며 생기는 힘 변화는 정상이라 상대 변화 조건 없이 절대 상한만 본다
                air_prof = dict(prof, air_monitor=dict(kind="AIR", bias=list(stroke_bias.get(stroke) or [0.0, 0.0, 0.0]),
                                                       force_limit_n=float(tp["air_force_limit_n"]), samples=[], max_read_failures=3))
            for w in wps:                            # 바깥 점들은 직선 이동으로 하나씩
                blocked = guard()
                if blocked:
                    return blocked
                r = adapter.move(w, frame, air_prof, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                                  f"{kind} {sid}: {r.message}", f"segment:{sid}")
            prog.completed_segment_id = sid
            continue

        # ---- CUT: 접촉 높이 결정 → 등속 긋기 ----
        report("ENGRAVE")
        blocked = guard()
        if blocked:
            return blocked
        normal_in = tool_axis_in_base(wps[0], axis_name)          # 표면 안쪽(법선 반대) 방향 = 송곳 축
        if stroke not in stroke_offset:
            stroke_offset.clear()
            if mode == "force_touch":
                # 표면 위 clearance 에서 출발해 안쪽으로 힘 감시. (APPROACH 가 이미 그 자리에 두었다고 가정하되, 확인 이동)
                start = _shift(wps[0], normal_in, -clearance_m)
                r = adapter.move(start, frame, prof, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome, r.error_code, f"CUT {sid} 접근: {r.message}", f"segment:{sid}")
                blocked = guard()
                if blocked:
                    return blocked
                if cut_contact is not None:
                    try:                              # 정지·무접촉 상태 편향: CUT/AIR 감시의 기준 (자세마다 수 N 튐, L13)
                        stroke_bias[stroke] = list(adapter.read_force_bias())
                    except Exception as exc:
                        return finish("UNKNOWN", "COMMUNICATION_LOST", f"CUT {sid} 힘 편향 읽기 실패: {exc}", f"segment:{sid}")
                probe_profile = dict(tp)
                dual = tp.get("entry_confirmation") == "force_and_position"
                if dual:
                    probe_profile["entry_target_tip_pose"] = _shift(wps[0], normal_in, depth_m)
                r = adapter.probe_touch(normal_in, clearance_m + touch_extra_m, probe_profile, deadline_of(seg), context.cancel)
                if dual and r.ok and not (r.observed_state.get("force_ok") is True
                                         and r.observed_state.get("position_ok") is True
                                         and r.observed_state.get("entry_confirmed") is True):
                    return finish("FAILED", "VALIDATION_FAILED", "좌표·힘 진입 근거 누락", f"segment:{sid}")
                if not r.ok or not r.observed_state.get("contact"):
                    return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED",
                                  r.error_code if r.error_code != "NONE" else "VALIDATION_FAILED",
                                  f"CUT {sid} 표면을 못 찾음: {r.message}", f"segment:{sid}")
                contact = r.observed_state["tcp_pose"]
                # 보정량 = 실제 접촉점이 경로 표면점보다 법선 안쪽으로 얼마나 더 갔나 (m). 같은 획 안에서는 같은 값을 쓴다.
                off = sum((contact[k] - wps[0][k]) * normal_in[k] for k in range(3))
                lo, hi = tp["touch_offset_range_m"]
                # 9/23 우선순위 변경(시율): 시작 접촉 offset 은 즉시 실패 조건이 아니라 초기값이다.
                #   정상 제어 범위 touch_offset_range_m(권장 대역) / 시작 허용 범위 touch_start_range_m(넓게, 없으면 정상 범위) /
                #   절대 안전 한계 normal_hard_limit_m(없으면 touch_extra_m). 시작 허용 범위 밖일 때만 후퇴·실패한다.
                start_lo, start_hi = (tp.get("touch_start_range_m") or [lo, hi])
                if not math.isfinite(off) or not float(start_lo) <= off <= float(start_hi):
                    # 범위 밖 접촉에서 드릴을 표면에 둔 채 반환하면 자동 복귀도 막힌다 → 법선 바깥 clearance 로 먼저 후퇴
                    touches.append(dict(segment_id=sid, stroke_id=stroke, force_n=r.observed_state.get("force_n"),
                                        offset_mm=round(off * 1000.0, 2), pose=contact, rejected=True))
                    adapter.move(_shift(contact, normal_in, -clearance_m), frame, prof, deadline_of(seg), context.cancel)
                    return finish("FAILED", "VALIDATION_FAILED",
                                  f"CUT {sid} 실제 접촉 보정 {off * 1000:+.2f} mm 가 시작 허용 [{float(start_lo) * 1000:+.1f}, {float(start_hi) * 1000:+.1f}] mm 밖", f"segment:{sid}")
                in_control_band = lo <= off <= hi
                raw_off = off
                start_retreat = None
                if cut_contact is not None and off > hi:
                    # 9/23: 깊은 시작 접촉(이전 홈)은 초기값으로만 쓰고, 실제 TCP 를 위치 제어로 정상 범위 상한까지 빼낸 뒤 다시 읽어 확인한다.
                    # 확인이 안 되면 CUT 를 시작하지 않는다.
                    normals_all = [tool_axis_in_base(w, axis_name) for w in wps]
                    target_off = _m(tp, "hold_retreat_target", hi)
                    if verified_retreat and not confirm_retreat_ready(seg):
                        return finish("UNKNOWN", "STOP_UNCONFIRMED", "시작 후퇴 전 정지·힘 해제 미확인", f"segment:{sid}")
                    ok_r, dev_r, moves_r = retreat_to_band(seg, wps, normals_all, target_off)
                    start_retreat = dict(ok=ok_r, dev_after_mm=round(dev_r * 1000, 2), moves=moves_r)
                    if not ok_r:
                        if not verified_retreat:
                            adapter.move(_shift(contact, normal_in, -clearance_m), frame, prof, deadline_of(seg), context.cancel)
                        return finish("UNKNOWN" if verified_retreat else "FAILED", "VALIDATION_FAILED",
                                      f"CUT {sid} 시작 후퇴 보정 실패: 접촉 {raw_off * 1000:+.2f} mm → 후퇴 뒤 {dev_r * 1000:+.2f} mm (목표 {hi * 1000:+.1f})", f"segment:{sid}")
                    off = target_off
                final_offset = off if (dual or start_retreat is not None) else (off + depth_m if cut_contact is not None else off)   # 9/22 호환: depth 가산은 cut_contact 프로파일만
                if verified_retreat:
                    final_offset = min(final_offset, hi)
                # 이번 진입부터 후퇴 전까지 이어지는 획만 보정·검사한다.
                # 매 waypoint / spline 묶음에서는 접촉 조회나 보정 갱신을 하지 않는다.
                entry_segments = []
                for upcoming in segs[segment_index:]:
                    if (upcoming["kind"] != "CUT"
                            or upcoming.get("stroke_id", upcoming.get("segment_id", "?")) != stroke):
                        break
                    entry_segments.append(upcoming)
                actual = dict(path, inspection_scope="DYNAMIC_STROKE_FINAL", segments=[
                    dict(s, waypoints=cut_points(s, tp, final_offset), movement_kind="CUT_ENTRY_AND_CUT",
                         applied_offset_m=final_offset, applied_depth_m=depth_m) for s in entry_segments])
                blocked = guard()
                if blocked:
                    return blocked
                if context.checked_plan_signature is None:
                    # 세은 검사 서명이 없을 때만(단독 시험) 실제 획을 여기서 IK 검사한다.
                    checked = _check_plan(actual, context, adapter)
                    if not checked.ok:
                        return checked
                    ik_rechecked = True
                else:
                    # 9/22: 같은 서명의 세은 검사(범위 양 끝 오프셋 두 벌 IK 통과)를 재사용한다. 실제 offset 은 위에서 범위 안임을 확인했다.
                    # 미구현: 범위 안 연속 영역·힘 유지 중 실제 위치의 IK 증명은 세은 검사 계약에 없다 (finish 의 normal_range_continuity_verified=False).
                    ik_rechecked = False
                stroke_offset[stroke] = final_offset
                touches.append(dict(segment_id=sid, stroke_id=stroke, force_n=r.observed_state.get("force_n"),
                                    offset_mm=round(raw_off * 1000.0, 2), pose=contact, ik_rechecked=ik_rechecked,   # offset_mm = 실제 접촉 (클램프 전)
                                    in_control_band=in_control_band,          # False 면 정상 범위 밖 접촉 → 명령 offset 은 상한으로 잘림 (start_clamped)
                                    start_clamped=(not in_control_band and cut_contact is not None), start_retreat=start_retreat,
                                    force_ok=r.observed_state.get("force_ok"),
                                    position_ok=r.observed_state.get("position_ok"),
                                    entry_confirmed=r.observed_state.get("entry_confirmed"),
                                    applied_offset_m=final_offset))
            else:
                stroke_offset[stroke] = depth_m
        off = stroke_offset[stroke]
        # fixed 계획에는 이미 깊이가 반영되어 있다. 두 번째 변환은 하지 않는다.
        # 접촉 보정량과 가공 깊이는 별개이며, 검사와 실행에 동일하게 한 번 적용한다.
        pts = wps if mode == "fixed_depth" else cut_points(seg, tp, off)
        blocked = guard()
        if blocked:
            return blocked
        # ---- 9/22 CUT 중 법선 보정 ----
        #  normal_force_hold: 획의 첫 CUT 구간 앞에서 제어기 힘 유지(툴 축 방향 힘 제어 + 나머지 순응)를 켜고, 홍동 waypoint 를
        #    MoveSX 로 그대로 보낸다. 진행 방향·자세는 경로(위치 제어), 법선 방향 위치는 제어기가 목표 힘에 맞춰 연속 보정한다.
        #    이동 중 어댑터가 힘·법선 이탈을 감시: 절대 상한 초과 또는 touch_offset_range_m 밖이면 정지·해제·실패.
        #  chunk_adaptive (대안): 힘 유지 없이 MoveSX 묶음 사이에서 평균 접촉력으로 offset 을 조금씩 옮긴다 (정지-재출발 있음).
        cut_prof = prof
        if cut_contact is not None:
            lo_r, hi_r = (float(v) for v in tp["touch_offset_range_m"])
            hard = abs(_m(tp, "normal_hard_limit", touch_extra_m))      # 절대 안전 한계 (법선, 경로 표면 기준 절대값). 시작 깊이와 무관 (9/23 확정)
            hard_in = hard
            corr_dev = hi_r + _m(tp, "hold_correction_margin", 0.002)  # 이 이상 깊어지면 묶음 중단 → 바깥 보정 → 이어감
            cut_prof = dict(prof, contact_monitor=dict(
                kind="CUT", bias=list(stroke_bias.get(stroke) or [0.0, 0.0, 0.0]),
                force_limit_n=float(tp["force_limit_n"]),
                surface=[list(w) for w in wps], normals=[tool_axis_in_base(w, axis_name) for w in wps],
                offset_range=[-hard, hard_in], control_range=[lo_r, hi_r], correction_dev_m=corr_dev,
                ignore_normal=(cut_contact == "normal_force_hold"), samples=[], max_read_failures=2))
        # 진입: 첫 CUT 구간은 힘 유지 전 위치 제어 MoveL. 같은 획의 이어지는 구간은 힘 유지가 켜진 채인데, 그 상태에서 MoveL 은
        # 제어기가 실행하지 않는다(9/23 실기: seg-0003 진입 NOT_ACCEPTED, 첫 점 = 직전 끝점이라 법선 방향 3 mm 짜리 MoveL 이 됨).
        # → 이어지는 구간은 진입 MoveL 없이 첫 점을 스플라인에 포함해 MoveSX 로 이어 간다 (첫 점이 직전 끝점과 같으면 생략).
        if hold["active"]:
            last_cmd = hold.get("last_point")
            rest_override = pts[1:] if (last_cmd is not None and math.dist(wps[0][:3], last_cmd[:3]) < 1e-6) else list(pts)   # 원본 점끼리 비교
        else:
            rest_override = None
            r = adapter.move(pts[0], frame, prof, deadline_of(seg), context.cancel)
            if not r.ok:
                release_hold(seg)
                return finish(r.outcome, r.error_code, f"CUT {sid} 진입: {r.message}", f"segment:{sid}")
        if cut_contact is not None:
            if cut_contact == "normal_force_hold" and not hold["active"]:
                blocked = guard()
                if blocked:
                    return blocked
                hold["start_clamped"] = bool(touches and touches[-1].get("start_clamped"))
                r = adapter.hold_normal_force_begin(axis_name, tp, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                                  f"CUT {sid} 힘 유지 시작 실패: {r.message}", f"segment:{sid}")
                hold["active"], hold["released"] = True, False
                hold["force_n"] = float(tp["cut_force_n"])
                if hold.get("start_clamped") and tp.get("cut_force_min_n") is not None and hold["force_n"] > float(tp["cut_force_min_n"]):
                    # 9/23: 깊은 접촉(이전 홈)에서 시작하면 힘 목표를 하한부터 시작해 다시 파고드는 것을 줄인다
                    rs = adapter.hold_normal_force_set(float(tp["cut_force_min_n"]), deadline_of(seg))
                    if rs.ok:
                        hold["force_n"] = float(tp["cut_force_min_n"])
        chunk_n = MAX_SPLINE_POINTS
        if cut_contact == "chunk_adaptive":
            chunk_n = max(2, min(MAX_SPLINE_POINTS, int(tp["adaptive_chunk_points"])))
        elif cut_contact == "normal_force_hold" and tp.get("hold_chunk_points") is not None:
            chunk_n = max(2, min(MAX_SPLINE_POINTS, int(tp["hold_chunk_points"])))   # 9/23: 묶음마다 힘 목표 보정 기회를 주기 위한 묶음 크기
        rest = pts[1:] if rest_override is None else rest_override
        hold["last_point"] = list(wps[-1])                              # 이 구간의 마지막 원본 점 (이어지는 구간의 첫 점과 비교)
        if tp.get("cut_motion") == "movel":
            # 9/23 네모 시험: 스플라인 대신 직선 현(chord)마다 MoveL. 순응/힘 유지 동작을 MoveSX 문제와 분리해 검증한다.
            rest = collapse_collinear([pts[0]] + rest, _m(tp, "movel_chord_tol"))
            chunk_n = 1
        i = 0
        while i < len(rest):
            chunk = rest[i:i + chunk_n]
            i += chunk_n
            if context.cancel.is_set():
                release_hold(seg)
                return finish("STOPPED", "NONE", f"취소됨 (CUT {sid} 중)", f"segment:{sid}")
            blocked = guard()
            if blocked:
                release_hold(seg)
                return blocked
            if cut_contact is not None:
                cut_prof["contact_monitor"]["samples"] = []
            if len(chunk) >= 2:
                r = adapter.move_spline(chunk, frame, cut_prof, deadline_of(seg), context.cancel)
            elif verified_retreat and hold["active"]:
                # 보정 뒤 남은 점이 하나여도 힘 유지 중 MoveL로 전환하지 않는다.
                # 현재 실제 자세를 시작점으로 붙이고 원본의 마지막 목표까지 MoveSX로 잇는다.
                try:
                    current = adapter.observe()
                    if current.quality != "VALID" or current.robot_state != 1 or not current.tcp_pose:
                        raise ValueError("마지막 점 재개 전 현재 자세 미확인")
                    r = adapter.move_spline([current.tcp_pose, chunk[-1]], frame, cut_prof, deadline_of(seg), context.cancel)
                except Exception as exc:
                    release_hold(seg)
                    return finish("UNKNOWN", "COMMUNICATION_LOST", str(exc), f"segment:{sid}")
            else:
                r = adapter.move(chunk[-1], frame, cut_prof, deadline_of(seg), context.cancel)
            dev_samples = [x["normal_dev_m"] for x in cut_prof.get("contact_monitor", {}).get("samples", [])
                           if x.get("normal_dev_m") is not None]
            end_correction = (verified_retreat and r.ok and dev_samples
                              and sum(dev_samples) / len(dev_samples) > hi_r)
            if (r.error_code == "NORMAL_CORRECTION" or end_correction) and cut_contact == "normal_force_hold":
                # 9/23: 묶음 도중 깊어짐 → 어댑터가 정지·힘 해제. 실제 위치를 정상 범위로 빼고(확인), 힘 목표 낮춰 다시 켜고, 남은 점부터 이어간다.
                if end_correction:
                    confirmed = confirm_retreat_ready(seg)
                else:
                    confirmed = (r.outcome != "UNKNOWN" and r.observed_state.get("stop_confirmed") is True
                                 and r.observed_state.get("force_released") is True)
                if not confirmed:
                    hold["released"] = False
                    return finish("UNKNOWN", "STOP_UNCONFIRMED", "깊이 보정 전 정지·힘 해제 미확인", f"segment:{sid}")
                hold["active"], hold["released"] = False, True
                hold["corrections"] = hold.get("corrections", 0) + 1
                if hold["corrections"] > int(tp.get("hold_max_corrections", 10)):
                    return finish("FAILED", "VALIDATION_FAILED", f"CUT {sid} 법선 보정 {hold['corrections']}회 초과 → 중단", f"segment:{sid}")
                normals_all = cut_prof["contact_monitor"]["normals"]
                retreat_target = _m(tp, "hold_retreat_target", hi_r)
                ok_r, dev_r, moves_r = retreat_to_band(seg, wps, normals_all, retreat_target)
                touches.append(dict(segment_id=sid, stroke_id=stroke, mid_chunk_correction=True, ok=ok_r, dev_after_mm=round(dev_r * 1000, 2), moves=moves_r))
                if not ok_r:
                    return finish("UNKNOWN" if verified_retreat else "FAILED", "VALIDATION_FAILED", f"CUT {sid} 묶음 중 후퇴 보정 실패 (후퇴 뒤 {dev_r * 1000:+.2f} mm)", f"segment:{sid}")
                if context.cancel.is_set():
                    return finish("STOPPED", "NONE", "후퇴 확인 뒤 취소", f"segment:{sid}")
                try:
                    final_dev, cur, near, _ = normal_dev_now(wps, normals_all)
                    if verified_retreat and not (-abs(_m(tp, "normal_hard_limit", touch_extra_m)) <= final_dev
                                                 <= retreat_target + _m(tp, "hold_retreat_tolerance")):
                        raise ValueError("재개 직전 실제 위치가 후퇴 확인 범위 밖")
                except Exception as exc:
                    return finish("UNKNOWN", "COMMUNICATION_LOST", f"보정 뒤 위치 재확인 실패: {exc}", f"segment:{sid}")
                base_index = len(wps) - len(rest)
                start_i = max(0, i - chunk_n)
                if not end_correction:
                    passed = max(0, near - base_index)
                    i = min(len(rest), max(start_i, passed + 1))
                if verified_retreat:
                    off = retreat_target
                    stroke_offset[stroke] = off
                    rest = [_shift(w, tool_axis_in_base(w, axis_name), off) for w in wps[base_index:]]
                touches[-1]["resume_index"] = i
                new_f = max(float(tp["cut_force_min_n"]), hold["force_n"] - float(tp.get("cut_force_step_n", 0.0)))
                rb = adapter.hold_normal_force_begin(axis_name, dict(tp, cut_force_n=new_f), deadline_of(seg), context.cancel)
                if not rb.ok:
                    hold["released"] = rb.observed_state.get("force_released") is True
                    return finish(rb.outcome if rb.outcome != "SUCCEEDED" else "FAILED", rb.error_code, f"CUT {sid} 보정 뒤 힘 유지 재시작 실패: {rb.message}", f"segment:{sid}")
                hold["active"], hold["released"], hold["force_n"] = True, False, new_f
                continue
            if cut_contact is not None:
                smp = cut_prof["contact_monitor"]["samples"]
                fn = [x["normal_force_n"] for x in smp if x.get("normal_force_n") is not None]
                dev = [x["normal_dev_m"] for x in smp if x.get("normal_dev_m") is not None]
                rec = dict(segment_id=sid, stroke_id=stroke, chunk_end=i, samples=len(smp), applied_offset_mm=round(off * 1000.0, 2),
                           normal_force_mean_n=round(sum(fn) / len(fn), 2) if fn else None,
                           normal_force_min_n=round(min(fn), 2) if fn else None, normal_force_max_n=round(max(fn), 2) if fn else None,
                           normal_dev_min_mm=round(min(dev) * 1000.0, 2) if dev else None,
                           normal_dev_max_mm=round(max(dev) * 1000.0, 2) if dev else None)
                touches.append(rec)
                if r.ok and cut_contact == "normal_force_hold" and dev and tp.get("cut_force_step_n") is not None:
                    # 9/23 (2차): 힘 목표 조절만으로는 부족했다(홈 안에서 반력이 줄어 더 파고듦 → 1 묶음에 5→10 mm). 깊으면 힘 목표를
                    # 줄이고 동시에 명령 위치 offset 도 바깥으로 옮기며, 이탈이 직전 묶음보다 커지면 '파고드는 중' 으로 보고 다음 묶음 전에
                    # 힘 유지를 잠시 풀고 위치 제어로 정상 범위 상한까지 실제로 빼낸(retreat correction) 뒤 낮춘 힘 목표로 다시 켠다.
                    mean_dev = sum(dev) / len(dev); step_n = float(tp["cut_force_step_n"])
                    f_lo, f_hi = float(tp["cut_force_min_n"]), float(tp["cut_force_max_n"])
                    dig_step = _m(tp, "hold_dig_step", 0.0005)
                    prev_dev = hold.get("prev_dev")
                    hold["prev_dev"] = mean_dev
                    new_f = hold["force_n"]
                    if mean_dev > hi_r:
                        new_f = max(f_lo, hold["force_n"] - step_n)
                        digging = prev_dev is not None and mean_dev > prev_dev + dig_step
                        correction = (mean_dev - hi_r) + (max(0.0, mean_dev - prev_dev) if digging else 0.0)
                        rec["digging"] = digging; rec["retreat_correction_mm"] = round(correction * 1000.0, 2)
                        # 위치 offset 도 바깥으로 (남은 점 재계산). 힘 유지 중엔 제어기가 법선 위치를 힘으로 정하므로 실제 후퇴는 아래 순서로 한다.
                        off = max(-clearance_m, off - correction); stroke_offset[stroke] = off
                        rest = rest[:i] + [_shift(w, tool_axis_in_base(w, axis_name), off) for w in wps[1 + i:]]
                        rel = release_hold(seg)
                        if rel is not None and not hold["released"]:
                            return finish("UNKNOWN", "STOP_UNCONFIRMED", f"CUT {sid} 후퇴 보정 전 힘 해제 미확인: {rel.message}", f"segment:{sid}")
                        try:
                            cur = adapter.observe().tcp_pose
                            rr = adapter.move(_shift(cur, tool_axis_in_base(cur, axis_name), -correction), frame, prof, deadline_of(seg), context.cancel)
                        except Exception as exc:
                            rr = StepResult("UNKNOWN", "COMMUNICATION_LOST", str(exc), "retreat_correction")
                        rec["retreat_move"] = rr.outcome
                        if not rr.ok:
                            return finish(rr.outcome if rr.outcome != "SUCCEEDED" else "FAILED", rr.error_code, f"CUT {sid} 후퇴 보정 이동 실패: {rr.message}", f"segment:{sid}")
                        rb = adapter.hold_normal_force_begin(axis_name, dict(tp, cut_force_n=new_f), deadline_of(seg), context.cancel)
                        if not rb.ok:
                            return finish(rb.outcome if rb.outcome != "SUCCEEDED" else "FAILED", rb.error_code, f"CUT {sid} 후퇴 보정 뒤 힘 유지 재시작 실패: {rb.message}", f"segment:{sid}")
                        hold["active"], hold["released"], hold["force_n"] = True, False, new_f
                        rec["force_target_n"] = new_f; rec["force_target_change"] = "REAPPLIED"
                    elif mean_dev < lo_r:
                        new_f = min(f_hi, hold["force_n"] + step_n)
                        correction = lo_r - mean_dev
                        off = min(hi_r if verified_retreat else hi_r + depth_m, off + correction); stroke_offset[stroke] = off      # 얕으면 명령 offset 안쪽으로
                        rest = rest[:i] + [_shift(w, tool_axis_in_base(w, axis_name), off) for w in wps[1 + i:]]
                        rec["inward_correction_mm"] = round(correction * 1000.0, 2)
                        if new_f != hold["force_n"]:
                            rs = adapter.hold_normal_force_set(new_f, deadline_of(seg))
                            rec["force_target_n"] = new_f if rs.ok else hold["force_n"]
                            rec["force_target_change"] = rs.outcome
                            if rs.ok:
                                hold["force_n"] = new_f
                if r.ok and cut_contact == "chunk_adaptive" and fn:
                    mean = sum(fn) / len(fn); step_m = float(tp["adaptive_step_m"])
                    if mean < float(tp["cut_force_min_n"]):
                        off = min(hi_r, off + step_m)        # 접촉이 약하면 안쪽으로
                    elif mean > float(tp["cut_force_max_n"]):
                        off = max(lo_r, off - step_m)        # 과하면 바깥으로
                    if off != stroke_offset[stroke]:
                        stroke_offset[stroke] = off
                        rest = rest[:i] + [_shift(w, tool_axis_in_base(w, axis_name), off) for w in wps[1 + i:]]
                        rec["adapted_offset_mm"] = round(off * 1000.0, 2)
            if not r.ok:
                release_hold(seg)
                return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                              f"CUT {sid}: {r.message}", f"segment:{sid}")
        prog.done_cut_m += _seg_length(wps)
        prog.completed_segment_id = sid
        report("ENGRAVE")
        # 획의 마지막 CUT 구간이면(다음 구간이 같은 획의 CUT 가 아니면) 여기서 힘 유지를 해제한다. 해제 실패 시 이동 없이 중단.
        nxt = segs[segment_index + 1] if segment_index + 1 < len(segs) else None
        if hold["active"] and not (nxt is not None and nxt["kind"] == "CUT" and nxt.get("stroke_id", nxt.get("segment_id")) == stroke):
            r = release_hold(seg)
            if r is not None and not hold["released"]:
                return finish("UNKNOWN", "STOP_UNCONFIRMED", f"CUT {sid} 뒤 힘/순응 해제 미확인: {r.message}", f"segment:{sid}")

    report("RETRACT")
    blocked = guard()
    if blocked:
        release_hold(segs[-1])
        return blocked
    r = release_hold(segs[-1])                       # 안전망: 경로가 CUT 로 끝나도 힘 유지를 켠 채 반환하지 않는다
    if r is not None and not hold["released"]:
        return finish("UNKNOWN", "STOP_UNCONFIRMED", f"종료 시 힘/순응 해제 미확인: {r.message}", "execute_path")
    return finish("SUCCEEDED", "NONE", f"{len(segs)} 구간 완료", "execute_path")


# ---------------------------------------------------------------- 안전 홈 복귀 (9/22) ----
# 요구(시율 9/22): 현재 위치에서 바로 홈으로 가지 않는다.
#   현재 위치 → 양초 표면에서 바깥쪽으로 충분히 후퇴 → 윗면보다 충분히 높은 안전 높이로 상승 → 그 높이에서 자세·XY 정렬
#   → 홈까지 IK·관절 검사 → 홈 이동.
# TCP 한 점이 아니라 드릴(툴 −Y 돌출)·드릴 뒷단(툴 +Y)·그리퍼 하단(툴 +Z)의 실제 위치로 간섭을 본다.
# 거부: 검사 실패·정지 미확인·힘 유지 해제 미확인·취소·응답 불명확. 재전송 없음. 그리퍼 명령 없음.
RETURN_MIN_SURFACE_GAP_M = 0.010      # 드릴 끝·몸통이 양초 표면에서 떨어져야 하는 거리 (시율 9/22 지정)
RETURN_MIN_ABOVE_TOP_M = 0.050        # 도구 최저점이 양초 윗면보다 높아야 하는 거리 (시율 9/22 지정)
RETURN_SAMPLE_M, RETURN_SAMPLE_DEG = 0.003, 2.0     # 단계 보간 간격 (캐릭터 시험 prepare.py 와 같음)
RETURN_MAX_JOINT_STEP_DEG = 8.0
RETURN_J3_MIN_DEG, RETURN_J5_MARGIN_DEG = 10.0, 15.0


def _quat_slerp(qa, qb, t):
    dot = sum(a * b for a, b in zip(qa, qb))
    if dot < 0:
        qb = [-v for v in qb]; dot = -dot
    if dot > 0.9995:
        q = [a + (b - a) * t for a, b in zip(qa, qb)]
    else:
        th = math.acos(min(1.0, dot)); s = math.sin(th)
        q = [(math.sin((1 - t) * th) * a + math.sin(t * th) * b) / s for a, b in zip(qa, qb)]
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q]


def _quat_angle_deg(qa, qb):
    return math.degrees(2 * math.acos(min(1.0, abs(sum(a * b for a, b in zip(qa, qb))))))


def _tool_geometry(tip_pose, w):
    """도구 끝 자세 → 실제 형상 점들. 반환 dict(tcp, tip, bottom, rear, segments). 모든 값 base m.
    w: tool_offset_m(툴 좌표, 끝 = TCP + R·offset), top.contact_offset_tool_m(그리퍼 하단 = TCP + R·[0,0,+z]),
       tool_rear_protrusion_m(선택, 드릴 뒷단 = TCP + R·[0,+rear,0])."""
    from .robot_adapter import apply_tool_offset
    offset = w["tool_offset_m"]
    tcp = apply_tool_offset(tip_pose, offset, -1)
    bottom = apply_tool_offset(tcp, list(w["top"]["contact_offset_tool_m"]), +1)
    out = dict(tcp=tcp, tip=list(tip_pose), bottom=bottom, rear=None,
               segments=[("drill", tcp[:3], list(tip_pose[:3]))])
    rear = w.get("tool_rear_protrusion_m")
    if rear:
        out["rear"] = apply_tool_offset(tcp, [0.0, float(rear), 0.0], +1)
        out["segments"].append(("drill_rear", tcp[:3], out["rear"][:3]))
    return out


def _segment_axis_gap(a, b, center, radius):
    """xy 평면에서 선분 a→b 와 원기둥 축(center) 사이 최단 거리 − radius (m). 음수 = 원기둥 안."""
    dx, dy = b[0] - a[0], b[1] - a[1]; den = dx * dx + dy * dy
    f = 0.0 if den < 1e-12 else max(0.0, min(1.0, ((center[0] - a[0]) * dx + (center[1] - a[1]) * dy) / den))
    return math.hypot(a[0] + f * dx - center[0], a[1] + f * dy - center[1]) - radius


def _geometry_ok(tip_pose, w, *, min_gap_m, retreating=False, box_z=True):
    """샘플 하나의 간섭 검사. 반환 (ok, reason, gap). 양초 = 축(seed_axis_xy_m)·반지름(seed_radius_m)·윗면 top_z_m·받침대 bottom_z_m.
    box_z=False: 후퇴·상승 단계용. 시작 자세(조각 높이)가 측정용 TCP 상자보다 낮을 수 있어 xy 만 상자로 보고 z 는 받침대·양초 조건으로만 본다."""
    g = _tool_geometry(tip_pose, w)
    center, radius = w["seed_axis_xy_m"], float(w["seed_radius_m"])
    top, stand = float(w["top_z_m"]), float(w["bottom_z_m"])
    body_r = float(w.get("gripper_body_half_width_m") or 0.0)
    # 9/23: 복구는 일반 작업 상자(trial_scene)가 아니라 별도 recovery_envelope(셀 물리 한계) 로 본다. 작업 상자 밖에서 시작해도
    # 셀 안이면 허용하고, 실제 물체(양초·받침대)와의 간섭은 아래에서 따로 검사한다. envelope 가 없으면 종전대로 작업 상자.
    box = w.get("recovery_envelope") or w.get("trial_scene") or {}
    if box.get("tcp_min_m") and box.get("tcp_max_m"):
        axes = (0, 1, 2) if box_z else (0, 1)
        if not all(box["tcp_min_m"][k] <= g["tcp"][k] <= box["tcp_max_m"][k] for k in axes):
            return False, f"TCP 가 복구 허용 영역 밖 {[round(v, 3) for v in g['tcp'][:3]]} (허용 {box['tcp_min_m']}~{box['tcp_max_m']})", None
    if box.get("max_reach_m"):
        reach = math.hypot(g["tcp"][0], g["tcp"][1])
        if reach > float(box["max_reach_m"]):
            return False, f"TCP 가 로봇 도달 반경 밖 {reach:.3f} m > {float(box['max_reach_m']):.2f}", None
    lowest = min(p[2] for p in (g["tcp"], g["tip"], g["bottom"]) + ((g["rear"],) if g["rear"] else ()))
    if lowest < stand + 0.005:
        return False, f"도구 최저점 {lowest * 1000:.1f} mm 가 받침대 윗면 + 5 mm 아래", None
    gap = None
    for name, a, b in g["segments"]:
        if min(a[2], b[2]) < top + 0.020:                        # 양초 높이 대역(윗면 + 20 mm 아래)에 걸친 요소만
            d = _segment_axis_gap(a, b, center, radius)
            gap = d if gap is None else min(gap, d)
            if not retreating and d < min_gap_m:
                return False, f"{name} 이 양초 표면에서 {d * 1000:.1f} mm (필요 {min_gap_m * 1000:.0f})", gap
    # 그리퍼 하단·몸체가 양초 위를 지날 때: 윗면 + 5 mm 위여야 한다
    if math.hypot(g["bottom"][0] - center[0], g["bottom"][1] - center[1]) < radius + body_r + min_gap_m and g["bottom"][2] < top + 0.005:
        return False, f"그리퍼 하단 {g['bottom'][2] * 1000:.1f} mm 가 양초 윗면 위 5 mm 아래", gap
    return True, "", gap


def _home_steps(tip, w, *, min_gap_m, min_above_top_m, yaw_alt=False, xy_first=False, escape="normal"):
    """현재 도구 끝 자세 → 홈까지 단계 [(tip_pose, profile_id, label)]. 위치·자세는 그 단계에서만 바뀐다.
    xy_first=True: 안전 높이에서 자세를 돌리기 전에 홈 xy 로 먼저 옮긴다 (9/22 실기: 멀리 뻗은 자세에서 회전하면 J3 가 특이점 여유 10° 아래로 떨어짐).
    escape (9/23 일반화): "normal" = 드릴 축(툴 +Y) 바깥으로 후퇴(축을 보는 자세에서만), "radial" = 양초 축에서 끝 방향으로 xy 직진 탈출(자세 무관),
    "lift_only" = 후퇴 없이 현재 자세로 수직 상승(간섭 검사가 판정)."""
    from .robot_adapter import apply_tool_offset, tool_axis_in_base
    offset = w["tool_offset_m"]; h = w["home"]
    center, radius, top = w["seed_axis_xy_m"], float(w["seed_radius_m"]), float(w["top_z_m"])
    home_tcp = list(h["tcp_pose"]); home_q = home_tcp[3:7]
    steps = []
    cur = list(tip)
    # 1) 후퇴: 드릴 축(툴 +Y) 바깥 방향으로, 끝의 반지름 거리가 R + outer_gap 이 될 때까지. 표면 근처 slow_gap 은 후퇴 속도.
    radial = [cur[0] - center[0], cur[1] - center[1]]; dist = math.hypot(*radial)
    g0 = _tool_geometry(cur, w)
    if min(g0["tcp"][2], cur[2]) < top + 0.020 and dist < radius + float(w["outer_gap_m"]) and escape != "lift_only":
        if dist < radius - float(w.get("max_tip_inside_m", 0.005)):
            # 정상 조각 종료는 표면 안쪽 수 mm(접촉 offset + depth) 이므로 그 안은 허용, 더 깊으면 위치 불명으로 본다
            raise ValueError(f"드릴 끝이 표면 안쪽 {(radius - dist) * 1000:.1f} mm (허용 {float(w.get('max_tip_inside_m', 0.005)) * 1000:.0f}) → 자동 복귀 안 함")
        if escape == "normal":
            out_axis = tool_axis_in_base(cur, "+y")
            horiz = math.hypot(out_axis[0], out_axis[1])        # 기울어진 자세면 수평 성분만으로 방향을 본다 (기울기 자체는 상승 뒤 정렬에서 푼다)
            if dist < 1e-6 or horiz < 0.5 or (radial[0] * out_axis[0] + radial[1] * out_axis[1]) / (dist * horiz) < math.cos(math.radians(float(w.get("facing_tolerance_deg", 2.0)))):
                raise ValueError("드릴 축이 양초 축 바깥 방향과 다름 → 법선 후퇴 불가")
            labels = ("return_retreat_slow", "return_retreat")
        else:                                                  # radial: 양초 축 → 끝 방향 xy 직진 (자세와 무관)
            if dist < 1e-6:
                raise ValueError("드릴 끝이 축 위 → 반지름 방향 불명")
            out_axis = [radial[0] / dist, radial[1] / dist, 0.0]
            labels = ("return_escape_slow", "return_escape")
        targets = []
        slow = float(w["slow_retract_gap_m"])
        if dist < radius + slow:
            targets.append((radius + slow, "candle_retract", labels[0]))
        targets.append((radius + float(w["outer_gap_m"]), "candle_travel", labels[1]))
        for r, pid, label in targets:
            # 탈출 축을 따라 이동해 반지름 거리 r 에 닿는 거리 s (2차식 해)
            b = 2 * (radial[0] * out_axis[0] + radial[1] * out_axis[1]); c = dist * dist - r * r
            s = (-b + math.sqrt(max(0.0, b * b - 4 * (out_axis[0] ** 2 + out_axis[1] ** 2) * c))) / (2 * (out_axis[0] ** 2 + out_axis[1] ** 2))
            cur = [cur[0] + out_axis[0] * s, cur[1] + out_axis[1] * s, cur[2] + out_axis[2] * s, *cur[3:7]]
            radial = [cur[0] - center[0], cur[1] - center[1]]; dist = math.hypot(*radial)
            steps.append((list(cur), pid, label))
    # 2) 상승: 도구 최저점이 윗면 + min_above_top 이상, TCP 는 홈 안전 높이 이상이 되도록 수직으로만
    g = _tool_geometry(cur, w)
    lowest = min(p[2] for p in (g["tcp"], g["tip"], g["bottom"]) + ((g["rear"],) if g["rear"] else ()))
    dz = max(top + min_above_top_m - lowest, float(h["clearance_tcp_z_m"]) - g["tcp"][2], 0.0)
    if dz > 0.001:                                              # 1 mm 미만은 이미 안전 높이 (9/22: 0.1 mm 상승 명령을 제어기가 무시해 '이동 시작 미확인')
        cur = [cur[0], cur[1], cur[2] + dz, *cur[3:7]]
        steps.append((list(cur), "candle_travel", "return_lift"))
    # 3) 그 높이에서 자세 정렬: TCP 위치 고정, 홈 자세까지 ≤ 90° 단계로 (드릴 끝은 TCP 주위를 돈다 — 안전 높이에서만)
    tcp = apply_tool_offset(cur, offset, -1)
    if xy_first:                                                 # 자세는 그대로 두고 홈 xy 로 먼저 (x → y), 회전은 홈 위에서
        for label, native in (("return_x", [home_tcp[0], tcp[1], tcp[2], *tcp[3:7]]),
                              ("return_y", [home_tcp[0], home_tcp[1], tcp[2], *tcp[3:7]])):
            cand = apply_tool_offset(native, offset, +1)
            if math.dist(cand[:3], cur[:3]) >= 0.001:
                steps.append((cand, "candle_travel", label)); cur = cand
        tcp = apply_tool_offset(cur, offset, -1)
    total = _quat_angle_deg(tcp[3:7], home_q)
    if total > 0.5:
        n = max(1, math.ceil(total / 90.0))
        if yaw_alt and n == 1:
            n = 2
        for i in range(1, n + 1):
            q = _quat_slerp(tcp[3:7], home_q, i / n)
            if yaw_alt:                                          # 반대 방향 회전 후보: 중간 자세를 base z 축 반대편으로
                from .robot_adapter import quat_to_matrix, matrix_to_quat
                ang = -math.radians(total * i / n) * 2.0
                cz, sz = math.cos(ang), math.sin(ang)
                M = quat_to_matrix(q); R = [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]
                q = matrix_to_quat([[sum(R[r][k] * M[k][c] for k in range(3)) for c in range(3)] for r in range(3)])
            cur = apply_tool_offset(tcp[:3] + q, offset, +1)
            steps.append((list(cur), "candle_travel", "return_align"))
    # 4) XY 정렬 (x 먼저, 그다음 y) → 5) 하강
    tcp = apply_tool_offset(cur, offset, -1)
    for label, native in (("return_x", [home_tcp[0], tcp[1], tcp[2], *home_q]),
                          ("return_y", [home_tcp[0], home_tcp[1], tcp[2], *home_q]),
                          ("return_down", list(home_tcp))):
        cand = apply_tool_offset(native, offset, +1)
        prev_pose = steps[-1][0] if steps else cur
        if math.dist(cand[:3], prev_pose[:3]) < 0.001 and _quat_angle_deg(cand[3:7], prev_pose[3:7]) < 0.5:
            continue                                            # 1 mm·0.5° 미만 단계는 보내지 않는다 (제어기가 무시하면 시작 미확인으로 정지)
        steps.append((cand, "candle_travel", label))
    return steps


def _joint_escape_prefix(joints_rad, w, adapter, *, min_gap_m):
    """후보 D: 미리 검증해 둔 안전 관절 자세(w['safe_joint_waypoints_deg'])로 관절공간 탈출. 현재 관절에서 목표까지 2° 간격으로
    보간하며 FK → 도구 형상 간섭(표면 거리 비감소 규칙)·관절 한계·특이점 여유를 검사한다. 통과하는 첫 목표를 (joints, tip_pose) 로 돌려준다.
    FK 미지원 어댑터면 (None, 사유)."""
    targets = w.get("safe_joint_waypoints_deg") or []
    if not targets:
        return None, "안전 관절 자세(safe_joint_waypoints_deg) 미설정"
    q0 = [math.degrees(v) for v in joints_rad]
    tip0 = adapter.forward_kinematics(q0)
    if tip0 is None:
        return None, "어댑터 FK 미지원 → 관절공간 탈출 검사 불가"
    reasons = []
    for idx, qt in enumerate(targets):
        qt = [float(v) for v in qt]
        n = max(1, math.ceil(max(abs(a - b) for a, b in zip(qt, q0)) / RETURN_SAMPLE_DEG))
        last_gap = None; ok = True; why = ""
        for i in range(1, n + 1):
            q = [a + (b - a) * i / n for a, b in zip(q0, qt)]
            if abs(q[2]) < RETURN_J3_MIN_DEG or min(abs(q[4]), abs(180.0 - abs(q[4]))) < RETURN_J5_MARGIN_DEG:
                ok, why = False, f"샘플 {i}/{n}: 특이점 여유 부족 J3 {q[2]:.1f} J5 {q[4]:.1f}"; break
            tip = adapter.forward_kinematics(q)
            if tip is None:
                ok, why = False, f"샘플 {i}/{n}: FK 실패"; break
            g_ok, g_why, gap = _geometry_ok(tip, w, min_gap_m=min_gap_m, retreating=True, box_z=False)
            if not g_ok:
                ok, why = False, f"샘플 {i}/{n}: {g_why}"; break
            if gap is not None and last_gap is not None and gap < last_gap - 1e-6:
                ok, why = False, f"샘플 {i}/{n}: 표면 거리가 줄어듦"; break
            last_gap = gap
        if ok:
            tip_end = adapter.forward_kinematics(qt)
            g_ok, g_why, _ = _geometry_ok(tip_end, w, min_gap_m=min_gap_m)
            if g_ok:
                return (qt, tip_end), ""
            why = f"목표 자세: {g_why}"
        reasons.append(f"관절 자세 {idx}: {why}")
    return None, " | ".join(reasons)


def _check_return_steps(steps, start_tip, joints_rad, w, context, adapter, *, min_gap_m):
    """단계별 3 mm·2° 보간 샘플마다 간섭·IK·관절 한계·특이점 여유·관절 변화 검사 + 팀 check_path_joints. 실패면 (False, 이유)."""
    from .joint_check import check_path_joints
    from .robot_adapter import apply_tool_offset
    limits = context.joint_limits_deg or [(-360.0, 360.0)] * 6
    offset = w["tool_offset_m"]
    # 제어기(movel)는 TCP(패드) 를 직선·자세는 보간으로 움직이므로 샘플도 TCP 기준으로 만들고 끝 위치는 거기서 계산한다
    prev, q_prev = apply_tool_offset(list(start_tip), offset, -1), [math.degrees(v) for v in joints_rad]
    samples = 0
    for k, (target_tip, pid, label) in enumerate(steps):
        target = apply_tool_offset(list(target_tip), offset, -1)
        n = max(1, math.ceil(math.dist(prev[:3], target[:3]) / RETURN_SAMPLE_M),
                math.ceil(_quat_angle_deg(prev[3:7], target[3:7]) / RETURN_SAMPLE_DEG))
        retreating = label.startswith(("return_retreat", "return_escape"))
        last_gap = None
        for i in range(1, n + 1):
            t = i / n
            tcp = [prev[j] + (target[j] - prev[j]) * t for j in range(3)] + _quat_slerp(prev[3:7], target[3:7], t)
            pose = apply_tool_offset(tcp, offset, +1)
            ok, why, gap = _geometry_ok(pose, w, min_gap_m=min_gap_m, retreating=retreating,
                                        box_z=not (retreating or label == "return_lift"))
            if not ok:
                return False, f"{label} 샘플 {i}/{n}: {why}", samples
            if retreating and gap is not None and last_gap is not None and gap < last_gap - 1e-6:
                return False, f"{label}: 후퇴 중 표면 거리가 줄어듦", samples
            last_gap = gap
            q = adapter.inverse_kinematics(pose, getattr(adapter, "tool_offset_m", None), q_prev)
            if q is None:
                return False, f"{label} 샘플 {i}/{n}: IK 해 없음", samples
            if any(not (lo <= v <= hi) for v, (lo, hi) in zip(q, limits)):
                return False, f"{label} 샘플 {i}/{n}: 관절 한계 {[round(v, 1) for v in q]}", samples
            if abs(q[2]) < RETURN_J3_MIN_DEG or min(abs(q[4]), abs(180.0 - abs(q[4]))) < RETURN_J5_MARGIN_DEG:
                return False, f"{label} 샘플 {i}/{n}: 특이점 여유 부족 J3 {q[2]:.1f} J5 {q[4]:.1f}", samples
            if max(abs(a - b) for a, b in zip(q, q_prev)) > RETURN_MAX_JOINT_STEP_DEG:
                return False, f"{label} 샘플 {i}/{n}: 관절 변화 {max(abs(a - b) for a, b in zip(q, q_prev)):.1f}° > {RETURN_MAX_JOINT_STEP_DEG}", samples
            q_prev = q; samples += 1
        prev = list(target)
    team = check_path_joints(dict(frame_id=w.get("frame_id", "c2_base"),
                                  segments=[dict(kind="TRAVEL", segment_id=label, waypoints=[list(target)]) for target, _, label in steps]),
                             adapter, getattr(adapter, "tool_offset_m", None), list(joints_rad),
                             limits_deg=context.joint_limits_deg, j6_margin_deg=context.j6_margin_deg, cancel=context.cancel)
    if not team.ok:
        return False, f"팀 joint_check: {team.message}", samples
    return True, "", samples


def return_home(context: ExecutionContext, adapter: RobotAdapter, workcell: Dict,
                min_surface_gap_m: float = RETURN_MIN_SURFACE_GAP_M,
                min_above_top_m: float = RETURN_MIN_ABOVE_TOP_M, plan_only: bool = False) -> StepResult:
    """안전 홈 복귀. 홈이면 이동 없음. 검사 실패·정지 미확인·힘 유지 해제 미확인·취소·응답 불명확이면 이동하지 않는다.
    제어권 확인은 호출자(상태 기계/시험 스크립트)가 한다. 그리퍼·드릴 전원은 건드리지 않는다.
    plan_only=True: 단계 생성·검사까지만 하고(실제 IK 서비스 사용) 이동 없이 검사된 단계를 돌려준다."""
    from .robot_adapter import apply_tool_offset
    step = "return_home"
    w = workcell
    try:
        for key in ("home", "tool_offset_m", "seed_axis_xy_m", "seed_radius_m", "top_z_m", "bottom_z_m", "outer_gap_m", "slow_retract_gap_m", "top"):
            if key not in w:
                return StepResult("FAILED", "NOT_READY", f"workcell 에 {key} 없음", step)
        for pid in ("candle_travel", "candle_retract"):
            if pid not in (context.motion_profiles or {}):
                return StepResult("FAILED", "NOT_READY", f"motion_profiles 에 {pid} 없음", step)
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "취소됨 (복귀 전)", step)
        if getattr(adapter, "_hold_active", False) or getattr(adapter, "hold_active", False):
            r = adapter.hold_normal_force_end(float(context.motion_profiles["candle_travel"].get("completion_timeout_s", 30.0)))
            if r.observed_state.get("force_released") is not True:
                return StepResult("UNKNOWN", "STOP_UNCONFIRMED", f"힘/순응 해제 미확인 → 자동 복귀 안 함: {r.message}", step)
        st = adapter.observe()
        if st.quality != "VALID" or st.robot_state != 1 or not st.tcp_pose or not st.joints_rad:
            return StepResult("FAILED", "NOT_READY", f"로봇 상태 {st.robot_state}/{st.quality}: STANDBY 확인 전 자동 복귀 안 함", step)
        if getattr(adapter, "tool_offset_m", None) is None or list(adapter.tool_offset_m) != list(w["tool_offset_m"]):
            return StepResult("FAILED", "PROFILE_MISMATCH", "어댑터 도구 오프셋이 workcell 과 다름", step)
        tip = list(st.tcp_pose)
        home_tip = apply_tool_offset(list(w["home"]["tcp_pose"]), w["tool_offset_m"], +1)
        h = w["home"]
        if (math.dist(tip[:3], home_tip[:3]) <= float(h["position_tolerance_m"])
                and _quat_angle_deg(tip[3:7], home_tip[3:7]) <= math.degrees(float(h["angle_tolerance_rad"]))):
            return StepResult("SUCCEEDED", "NONE", "이미 홈", step, dict(moved=False, steps=[]))
        # 9/23 일반화: 탈출 후보 A(법선 후퇴) → B(축 반대 방향 직진) → C(현재 자세로 상승) → D(안전 관절 자세로 관절공간 탈출),
        # 각각 정렬→xy / xy→정렬 × 회전 방향 두 가지. 실제 이동 전 모든 후보를 같은 검사(보간 샘플·IK·관절 한계·특이점·도구 형상 간섭)로
        # 거른다. 하나가 실패해도 다음 후보를 보고, 전부 실패할 때만 RECOVERY_REQUIRED 로 멈춘다 (사람이 TP 로 처리).
        errors = []
        chosen = None
        joint_prefix = None
        for escape in ("normal", "radial", "lift_only", "joint"):
            if chosen is not None:
                break
            start_tip = tip
            if escape == "joint":
                joint_prefix, why = _joint_escape_prefix(st.joints_rad, w, adapter, min_gap_m=min_surface_gap_m)
                if joint_prefix is None:
                    errors.append(f"D 관절 탈출: {why}"); continue
                start_tip = joint_prefix[1]
            for xy_first, alt in ((False, False), (True, False), (False, True), (True, True)):
                try:
                    steps = _home_steps(start_tip, w, min_gap_m=min_surface_gap_m, min_above_top_m=min_above_top_m, yaw_alt=alt, xy_first=xy_first,
                                        escape=("lift_only" if escape == "joint" else escape))
                except ValueError as exc:
                    errors.append(f"{escape}: {exc}"); break
                ref_joints = st.joints_rad if escape != "joint" else [math.radians(v) for v in joint_prefix[0]]
                if steps:
                    ok, why, samples = _check_return_steps(steps, start_tip, ref_joints, w, context, adapter, min_gap_m=min_surface_gap_m)
                else:
                    ok, why, samples = True, "", 0                      # 관절 탈출 목표가 이미 홈이면 데카르트 단계 없음
                if ok:
                    if escape == "joint":
                        steps = [(list(joint_prefix[0]), "candle_travel", "return_joint_escape")] + steps
                    chosen = (steps, samples, escape); break
                errors.append(f"{escape}: {why}")
                if context.cancel.is_set():
                    return StepResult("STOPPED", "NONE", "취소됨 (복귀 검사 중)", step, dict(moved=False))
        if chosen is None:
            return StepResult("FAILED", "RECOVERY_REQUIRED", "모든 복귀 후보가 검사 실패 → 이동 안 함, TP 로 처리: " + " | ".join(dict.fromkeys(errors)),
                              step, dict(moved=False, candidates_tried=["normal", "radial", "lift_only", "joint"], reasons=list(dict.fromkeys(errors))))
        steps, samples, escape = chosen
        if plan_only:
            return StepResult("SUCCEEDED", "NONE", f"복귀 계획 {len(steps)} 단계 검사 통과 (이동 없음, 후보 {escape})", step,
                              dict(moved=False, plan_only=True, candidate=escape, checked_samples=samples, full_mesh_checked=False, fk_roundtrip_checked=False,
                                   rejected=list(dict.fromkeys(errors)),
                                   steps=[dict(label=label, profile=pid, tip_pose=[round(v, 4) for v in target]) for target, pid, label in steps]))
        # 실행: 공중 절대 상한 감시, 단계마다 STANDBY 확인, 응답 불명확이면 어댑터가 정지 요청 후 UNKNOWN (재전송 없음)
        limit = (context.tool_profile or {}).get("air_force_limit_n")
        done = []
        for target, pid, label in steps:
            if context.cancel.is_set():
                return StepResult("STOPPED", "NONE", f"취소됨 ({label} 전)", step, dict(moved=bool(done), steps=done))
            prof = dict(context.motion_profiles[pid])
            if limit is not None:
                prof["air_monitor"] = dict(kind="AIR", bias=[0.0, 0.0, 0.0], force_limit_n=float(limit), samples=[], max_read_failures=3)
            if label == "return_joint_escape":
                r = adapter.move_joints(target, prof, float(prof.get("completion_timeout_s", 60.0)), context.cancel)
            else:
                r = adapter.move(target, w.get("frame_id", "c2_base"), prof, float(prof.get("completion_timeout_s", 60.0)), context.cancel)
            done.append(dict(label=label, outcome=r.outcome, error_code=r.error_code, message=r.message))
            if not r.ok:
                return StepResult(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                                  f"{label}: {r.message} → 이후 단계 중단", step, dict(moved=True, steps=done))
        return StepResult("SUCCEEDED", "NONE", f"홈 복귀 {len(steps)} 단계 (후보 {escape})", step,
                          dict(moved=True, candidate=escape, steps=done, checked_samples=samples, full_mesh_checked=False, fk_roundtrip_checked=False))
    except Exception as exc:
        return StepResult("UNKNOWN", "COMMUNICATION_LOST", f"복귀 중 예외: {exc}", step)


# ------------------------------------------------- 고정 깊이(fixed_depth) 실행 ----
# 9/23 이동: 기존 run_fixed_path_trial.py 의 execute_path 본문. 로직 변경 없음.
# 조각 실행의 한 갈래이므로 조각 모듈이 소유한다. 기존 import 경로는 얇은 wrapper 로 유지.
def execute_fixed_depth_path(path: Dict, context: ExecutionContext,
                             on_progress: Optional[Callable[[Dict], None]] = None,
                             adapter: RobotAdapter = None) -> StepResult:
    """execute_path와 동일 계약. 설정을 몰래 fixed_depth로 바꾸지 않는다.

    원본 도구 끝 표면 경로와 fixed_depth 설정으로 최종 계획을 만들고 검사한 점을 실행한다.
    접촉 탐색/획별 재보정은 하지 않으며, 완료는 경로 이동 완료만 뜻한다.
    """
    if (context.tool_profile or {}).get('contact_mode') != 'fixed_depth':
        return StepResult('FAILED', 'UNSUPPORTED_RECIPE',
                          '고정 경로 실행에는 검사 전 fixed_depth 설정이 필요함', 'execute_path')
    if adapter is None:
        return StepResult('FAILED', 'NOT_READY', 'robot_adapter 없음', 'execute_path')
    plan = build_execution_plan(path, context)
    if isinstance(plan, StepResult):
        return plan
    try:
        signature = execution_signature(path, context)
    except (ValueError, TypeError):
        return StepResult('FAILED', 'INVALID_INPUT', '경로/설정 fingerprint 생성 불가', 'execution_plan')
    offset_before = copy.deepcopy(getattr(adapter, 'tool_offset_m', None))
    if context.checked_plan_signature is not None:
        if (context.checked_plan_signature != signature
                or context.checked_tool_offset_m != offset_before):
            return StepResult('FAILED', 'PROFILE_MISMATCH',
                              '검사 후 경로/설정/도구 오프셋 변경', 'execution_plan')
    checked = _check_plan(plan, context, adapter)
    if not checked.ok:
        return checked

    segments = plan['segments']
    progress = _Progress(total_cut_m=sum(_seg_length(s['waypoints'])
                                       for s in segments if s['kind'] == 'CUT'))
    began = time.monotonic()

    def finish(outcome, code='NONE', message='', step='execute_path', observed=None):
        values = dict(observed or {})
        values.update(last_completed_segment_id=progress.completed_segment_id,
                      engraving_progress=progress.done_cut_m / progress.total_cut_m if progress.total_cut_m else 0.,
                      touches=[], elapsed_s=time.monotonic()-began,
                      inspection_scope=plan['inspection_scope'], plan_signature=signature,
                      execution_mode='FIXED_PATH_REPLAY', contact_verified=False,
                      engraving_quality_verified=False)
        return StepResult(outcome, code, message, step, values)

    def guard():
        if context.cancel.is_set():
            return finish('STOPPED', message='취소 후 후속 이동 차단')
        try:
            current = execution_signature(path, context)
        except (ValueError, TypeError):
            current = None
        if current != signature or getattr(adapter, 'tool_offset_m', None) != offset_before:
            return finish('FAILED', 'PROFILE_MISMATCH', '검사 후 경로/설정/도구 오프셋 변경')
        return None

    def report(phase):
        if on_progress:
            on_progress(dict(phase=phase, completed_segment_id=progress.completed_segment_id,
                             engraving_progress=progress.done_cut_m / progress.total_cut_m if progress.total_cut_m else 0.,
                             elapsed_s=time.monotonic()-began))

    def send(points, segment, spline=False):
        blocked = guard()
        if blocked:
            return blocked
        profile = context.motion_profiles[segment['motion_profile_id']]
        timeout = float(profile.get('completion_timeout_s', 60.))
        result = (adapter.move_spline(points, path['frame_id'], profile, timeout, context.cancel)
                  if spline else adapter.move(points, path['frame_id'], profile, timeout, context.cancel))
        if not result.ok:
            return finish(result.outcome, result.error_code,
                          f"{segment['kind']} {segment['segment_id']}: {result.message}",
                          f"segment:{segment['segment_id']}", result.observed_state)
        return None

    try:
        for segment in segments:
            blocked = guard()
            if blocked:
                return blocked
            kind, points = segment['kind'], segment['waypoints']
            report({'APPROACH': 'APPROACH', 'TRAVEL': 'ENGRAVE',
                    'CUT': 'ENGRAVE', 'RETRACT': 'RETRACT'}[kind])
            if kind == 'CUT':
                # 깊이는 계획에 적용했다. 각 구간의 첫 점으로 진입한 뒤 나머지를 spline으로 보낸다.
                result = send(points[0], segment)
                if result:
                    return result
                rest = points[1:]
                for i in range(0, len(rest), MAX_SPLINE_POINTS):
                    chunk = rest[i:i + MAX_SPLINE_POINTS]
                    result = send(chunk if len(chunk) >= 2 else chunk[0], segment, len(chunk) >= 2)
                    if result:
                        return result
                progress.done_cut_m += _seg_length(points)
            else:
                for point in points:
                    result = send(point, segment)
                    if result:
                        return result
            progress.completed_segment_id = segment.get('segment_id', '?')
            if kind == 'CUT':
                report('ENGRAVE')
        report('RETRACT')
        blocked = guard()
        if blocked:
            return blocked
        return finish('SUCCEEDED', message=f'{len(segments)} 구간 경로 이동 완료')
    except Exception as exc:
        # 접수 여부가 불명확한 명령은 재전송하지 않는다. 완료 구간은 그대로 남긴다.
        try:
            stopped = adapter.stop(context.stop_profile,
                                   float(context.stop_profile.get('confirmation_timeout_s', 2.)))
            confirmed = stopped.ok and stopped.observed_state.get('stop_confirmed') is True
        except Exception:
            confirmed = False
        return finish('UNKNOWN', 'COMMUNICATION_LOST', str(exc),
                      observed={'stop_confirmed': confirmed})
