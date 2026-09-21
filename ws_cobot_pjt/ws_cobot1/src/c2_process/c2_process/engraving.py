# engraving.py — 확정된 실행 경로(path.json)의 조각 실행·진행 보고. 담당: 이시율 (초안 2026-09-18, main 이관 2026-09-19).
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
        plan = copy.deepcopy(path)
        plan["inspection_scope"] = "FINAL_EXECUTION_PLAN" if mode == "fixed_depth" else "BOUNDED_FORCE_TOUCH_CANDIDATES"
        plan["segments"] = []
        seen = set()
        def append(seg, points, movement, offset=None):
            item = dict(seg, waypoints=points, movement_kind=movement, applied_offset_m=offset,
                        applied_depth_m=depth if mode == "fixed_depth" else None)
            plan["segments"].append(item)
        for seg in path["segments"]:
            if any(any(type(v) not in (float, int) or not math.isfinite(v) for v in w) for w in seg["waypoints"]):
                raise ValueError("waypoint는 유한한 숫자여야 함")
            if seg["kind"] != "CUT":
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
                    append(seg, cut_points(seg, tp, off), "CUT_OFFSET_BOUND", off)
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
    t_start = time.monotonic()

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
                               inspection_scope=plan["inspection_scope"], plan_signature=signature))

    def profile_of(seg):
        return context.motion_profiles[seg["motion_profile_id"]]

    def deadline_of(seg):
        return float(profile_of(seg).get("completion_timeout_s", 60.0))

    for seg in segs:
        sid, kind, wps = seg.get("segment_id", "?"), seg["kind"], seg["waypoints"]
        stroke = seg.get("stroke_id", sid)
        if context.cancel.is_set():
            return finish("STOPPED", "NONE", f"취소됨 (구간 {sid} 전)", f"segment:{sid}")
        prof = profile_of(seg)

        if kind in ("APPROACH", "TRAVEL", "RETRACT"):
            report({"APPROACH": "APPROACH", "TRAVEL": "ENGRAVE", "RETRACT": "RETRACT"}[kind])
            for w in wps:                            # 바깥 점들은 직선 이동으로 하나씩
                blocked = guard()
                if blocked:
                    return blocked
                r = adapter.move(w, frame, prof, deadline_of(seg), context.cancel)
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
            if mode == "force_touch":
                # 표면 위 clearance 에서 출발해 안쪽으로 힘 감시. (APPROACH 가 이미 그 자리에 두었다고 가정하되, 확인 이동)
                start = _shift(wps[0], normal_in, -clearance_m)
                r = adapter.move(start, frame, prof, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome, r.error_code, f"CUT {sid} 접근: {r.message}", f"segment:{sid}")
                blocked = guard()
                if blocked:
                    return blocked
                r = adapter.probe_touch(normal_in, clearance_m + touch_extra_m, tp, deadline_of(seg), context.cancel)
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
                actual = dict(path, inspection_scope="DYNAMIC_STROKE_FINAL", segments=[
                    dict(s, waypoints=cut_points(s, tp, off), movement_kind="CUT_ENTRY_AND_CUT",
                         applied_offset_m=off) for s in path["segments"]
                    if s["kind"] == "CUT" and s.get("stroke_id", s.get("segment_id", "?")) == stroke])
                blocked = guard()
                if blocked:
                    return blocked
                checked = _check_plan(actual, context, adapter)
                if not checked.ok:
                    return checked
                stroke_offset[stroke] = off
                touches.append(dict(segment_id=sid, stroke_id=stroke, force_n=r.observed_state.get("force_n"),
                                    offset_mm=round(off * 1000.0, 2), pose=contact))
            else:
                stroke_offset[stroke] = depth_m
        off = stroke_offset[stroke]
        # fixed 계획에는 이미 깊이가 반영되어 있다. 두 번째 변환은 하지 않는다.
        pts = wps if mode == "fixed_depth" else cut_points(seg, tp, off)
        blocked = guard()
        if blocked:
            return blocked
        r = adapter.move(pts[0], frame, prof, deadline_of(seg), context.cancel)
        if not r.ok:
            return finish(r.outcome, r.error_code, f"CUT {sid} 진입: {r.message}", f"segment:{sid}")
        rest = pts[1:]
        for i in range(0, len(rest), MAX_SPLINE_POINTS):
            chunk = rest[i:i + MAX_SPLINE_POINTS]
            if context.cancel.is_set():
                return finish("STOPPED", "NONE", f"취소됨 (CUT {sid} 중)", f"segment:{sid}")
            blocked = guard()
            if blocked:
                return blocked
            if len(chunk) >= 2:
                r = adapter.move_spline(chunk, frame, prof, deadline_of(seg), context.cancel)
            else:
                r = adapter.move(chunk[-1], frame, prof, deadline_of(seg), context.cancel)
            if not r.ok:
                return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                              f"CUT {sid}: {r.message}", f"segment:{sid}")
        prog.done_cut_m += _seg_length(wps)
        prog.completed_segment_id = sid
        report("ENGRAVE")

    report("RETRACT")
    blocked = guard()
    if blocked:
        return blocked
    return finish("SUCCEEDED", "NONE", f"{len(segs)} 구간 완료", "execute_path")
