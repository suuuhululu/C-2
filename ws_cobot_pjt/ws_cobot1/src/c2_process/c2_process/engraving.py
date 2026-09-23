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
    checked_entry_plan: Optional[Dict] = None
    checked_entry_plan_sha256: Optional[str] = None
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
            context.joint_limits_deg, context.j6_margin_deg, context.checked_tool_offset_m,
            context.checked_entry_plan_sha256]
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
        from .run_fixed_path_trial import execute_path as execute_fixed_path
        return execute_fixed_path(path, context, on_progress, adapter)
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
    hold = dict(active=False, released=True)         # 법선 힘 유지 상태 (9/22)
    cut_contact = tp.get("cut_contact")              # None(구형: 획당 offset 고정) / normal_force_hold / chunk_adaptive
    t_start = time.monotonic()

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
                if not math.isfinite(off) or not lo <= off <= hi:
                    return StepResult("FAILED", "VALIDATION_FAILED", "실제 접촉 보정 범위 초과", "execution_plan",
                                      dict(segment_id=sid, stroke_id=stroke, applied_offset_m=off))
                final_offset = off if dual else (off + depth_m if cut_contact is not None else off)   # 9/22 호환: depth 가산은 cut_contact 프로파일만
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
                                    offset_mm=round(off * 1000.0, 2), pose=contact, ik_rechecked=ik_rechecked,
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
            cut_prof = dict(prof, contact_monitor=dict(
                kind="CUT", bias=list(stroke_bias.get(stroke) or [0.0, 0.0, 0.0]),
                force_limit_n=float(tp["force_limit_n"]),
                surface=[list(w) for w in wps], normals=[tool_axis_in_base(w, axis_name) for w in wps],
                offset_range=[lo_r, hi_r], ignore_normal=(cut_contact == "normal_force_hold"), samples=[], max_read_failures=2))
        # 진입: 첫 CUT 구간은 힘 유지 전 위치 제어. 같은 획의 이어지는 구간은 힘 유지가 켜진 채라 감시 프로파일로 보낸다.
        r = adapter.move(pts[0], frame, cut_prof if hold["active"] else prof, deadline_of(seg), context.cancel)
        if not r.ok:
            release_hold(seg)
            return finish(r.outcome, r.error_code, f"CUT {sid} 진입: {r.message}", f"segment:{sid}")
        if cut_contact is not None:
            if cut_contact == "normal_force_hold" and not hold["active"]:
                blocked = guard()
                if blocked:
                    return blocked
                r = adapter.hold_normal_force_begin(axis_name, tp, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                                  f"CUT {sid} 힘 유지 시작 실패: {r.message}", f"segment:{sid}")
                hold["active"], hold["released"] = True, False
        chunk_n = MAX_SPLINE_POINTS
        if cut_contact == "chunk_adaptive":
            chunk_n = max(2, min(MAX_SPLINE_POINTS, int(tp["adaptive_chunk_points"])))
        rest = pts[1:]
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
            else:
                r = adapter.move(chunk[-1], frame, cut_prof, deadline_of(seg), context.cancel)
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
    box = w.get("trial_scene") or {}
    if box.get("tcp_min_m") and box.get("tcp_max_m"):
        axes = (0, 1, 2) if box_z else (0, 1)
        if not all(box["tcp_min_m"][k] <= g["tcp"][k] <= box["tcp_max_m"][k] for k in axes):
            return False, f"TCP 작업 범위 밖 {[round(v, 3) for v in g['tcp'][:3]]} (상자 {box['tcp_min_m']}~{box['tcp_max_m']})", None
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


def _home_steps(tip, w, *, min_gap_m, min_above_top_m, yaw_alt=False, xy_first=False):
    """현재 도구 끝 자세 → 홈까지 단계 [(tip_pose, profile_id, label)]. 위치·자세는 그 단계에서만 바뀐다.
    xy_first=True: 안전 높이에서 자세를 돌리기 전에 홈 xy 로 먼저 옮긴다 (9/22 실기: 멀리 뻗은 자세에서 회전하면 J3 가 특이점 여유 10° 아래로 떨어짐)."""
    from .robot_adapter import apply_tool_offset, tool_axis_in_base
    offset = w["tool_offset_m"]; h = w["home"]
    center, radius, top = w["seed_axis_xy_m"], float(w["seed_radius_m"]), float(w["top_z_m"])
    home_tcp = list(h["tcp_pose"]); home_q = home_tcp[3:7]
    steps = []
    cur = list(tip)
    # 1) 후퇴: 드릴 축(툴 +Y) 바깥 방향으로, 끝의 반지름 거리가 R + outer_gap 이 될 때까지. 표면 근처 slow_gap 은 후퇴 속도.
    radial = [cur[0] - center[0], cur[1] - center[1]]; dist = math.hypot(*radial)
    g0 = _tool_geometry(cur, w)
    if min(g0["tcp"][2], cur[2]) < top + 0.020 and dist < radius + float(w["outer_gap_m"]):
        out_axis = tool_axis_in_base(cur, "+y")
        horiz = math.hypot(out_axis[0], out_axis[1])            # 기울어진 자세면 수평 성분만으로 방향을 본다 (기울기 자체는 상승 뒤 정렬에서 푼다)
        if dist < 1e-6 or horiz < 0.5 or (radial[0] * out_axis[0] + radial[1] * out_axis[1]) / (dist * horiz) < math.cos(math.radians(float(w.get("facing_tolerance_deg", 2.0)))):
            raise ValueError("드릴 축이 양초 축 바깥 방향과 다름 → 법선 후퇴 불가, 자동 복귀 안 함")
        if dist < radius - float(w.get("max_tip_inside_m", 0.005)):
            # 정상 조각 종료는 표면 안쪽 수 mm(접촉 offset + depth) 이므로 그 안은 허용, 더 깊으면 위치 불명으로 본다
            raise ValueError(f"드릴 끝이 표면 안쪽 {(radius - dist) * 1000:.1f} mm (허용 {float(w.get('max_tip_inside_m', 0.005)) * 1000:.0f}) → 자동 복귀 안 함")
        targets = []
        slow = float(w["slow_retract_gap_m"])
        if dist < radius + slow:
            targets.append((radius + slow, "candle_retract", "return_retreat_slow"))
        targets.append((radius + float(w["outer_gap_m"]), "candle_travel", "return_retreat"))
        for r, pid, label in targets:
            # 툴 +Y 를 따라 이동해 반지름 거리 r 에 닿는 거리 s (2차식 해)
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
        retreating = label.startswith("return_retreat")
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
        # 단계 생성 → 검사 (후보 4개: 정렬→xy / xy→정렬 × 회전 방향 두 가지). 먼저 통과하는 후보를 쓴다.
        errors = []
        chosen = None
        for xy_first, alt in ((False, False), (True, False), (False, True), (True, True)):
            try:
                steps = _home_steps(tip, w, min_gap_m=min_surface_gap_m, min_above_top_m=min_above_top_m, yaw_alt=alt, xy_first=xy_first)
            except ValueError as exc:
                return StepResult("FAILED", "VALIDATION_FAILED", str(exc), step, dict(moved=False))
            ok, why, samples = _check_return_steps(steps, tip, st.joints_rad, w, context, adapter, min_gap_m=min_surface_gap_m)
            if ok:
                chosen = (steps, samples); break
            errors.append(why)
            if context.cancel.is_set():
                return StepResult("STOPPED", "NONE", "취소됨 (복귀 검사 중)", step, dict(moved=False))
        if chosen is None:
            return StepResult("FAILED", "VALIDATION_FAILED", "복귀 경로 검사 실패 → 이동 안 함: " + " | ".join(dict.fromkeys(errors)), step, dict(moved=False))
        steps, samples = chosen
        if plan_only:
            return StepResult("SUCCEEDED", "NONE", f"복귀 계획 {len(steps)} 단계 검사 통과 (이동 없음)", step,
                              dict(moved=False, plan_only=True, checked_samples=samples, full_mesh_checked=False, fk_roundtrip_checked=False,
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
            r = adapter.move(target, w.get("frame_id", "c2_base"), prof, float(prof.get("completion_timeout_s", 60.0)), context.cancel)
            done.append(dict(label=label, outcome=r.outcome, error_code=r.error_code, message=r.message))
            if not r.ok:
                return StepResult(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                                  f"{label}: {r.message} → 이후 단계 중단", step, dict(moved=True, steps=done))
        return StepResult("SUCCEEDED", "NONE", f"홈 복귀 {len(steps)} 단계", step,
                          dict(moved=True, steps=done, checked_samples=samples, full_mesh_checked=False, fk_roundtrip_checked=False))
    except Exception as exc:
        return StepResult("UNKNOWN", "COMMUNICATION_LOST", f"복귀 중 예외: {exc}", step)
