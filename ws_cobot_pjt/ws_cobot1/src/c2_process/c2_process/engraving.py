# engraving.py — 확정된 실행 경로(path.json)의 조각 실행·진행 보고. 담당: 이시율 (초안 2026-09-18, 로컬).
# 상태 기계가 execute_path(path, context, on_progress) 를 함수로 부른다. 새 ROS 통신을 만들지 않는다.
# 좌표를 새로 만들지 않는다. 로봇 명령은 robot_adapter 를 통해서만 나간다.
#
# 실행 규칙 (INTERFACE_RECOMMENDATION v1 §4·§5·§9):
#   - 구간(segment) 종류: APPROACH / CUT / TRAVEL / RETRACT. 순서가 고정이고 서로 떨어진 획을 암묵적으로 잇지 않는다.
#   - waypoint 는 m + quaternion(x,y,z,w), frame_id 는 path 의 값. 단위 변환은 robot_adapter 가 한다.
#   - 접촉 방식은 가공 프로파일의 contact_mode 만 실행: force_touch(획마다 힘 감시로 표면 찾기) / fixed_depth(표면점에서
#     법선 안쪽으로 depth_mm). 프로파일이 없거나 미지원이면 UNSUPPORTED_RECIPE 로 거절하고 움직이지 않는다.
#   - 취소(context.cancel)·실패·제한 시간 초과 시 새 명령을 보내지 않고 마지막 완료 구간만 기록한다. 자동 재개 없음.
#   - 진행률 = 완료한 CUT 길이 / 전체 CUT 길이. 조각 100% 와 전체 공정 성공은 다르다 (상태 기계가 판단).
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .robot_adapter import RobotAdapter, StepResult, tool_axis_in_base

SUPPORTED_SCHEMA = (1,)
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
    mode = tp.get("contact_mode")
    if mode not in CONTACT_MODES:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", f"contact_mode {mode!r} 미지원 ({CONTACT_MODES})", "validate")
    if mode == "fixed_depth" and tp.get("depth_mm") is None:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", "fixed_depth 인데 depth_mm 없음", "validate")
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


# ---------------------------------------------------------------- 실행 ----
def execute_path(path: Dict, context: ExecutionContext, on_progress: Optional[Callable[[Dict], None]] = None,
                 adapter: RobotAdapter = None) -> StepResult:
    """경로의 구간을 순서대로 실행한다. 반환 StepResult.observed_state 에 last_completed_segment_id, engraving_progress,
    touches(획별 접촉 기록) 가 들어간다. outcome: SUCCEEDED / FAILED / STOPPED / UNKNOWN."""
    err = validate_path(path, context)
    if err:
        return err
    if adapter is None:
        return StepResult("FAILED", "NOT_READY", "robot_adapter 없음", "execute_path")
    tp = context.tool_profile
    axis_name = tp.get("tool_axis", "+z")            # 송곳이 향하는 도구 축 (경로 자세에서 표면 법선 안쪽을 가리켜야 함)
    mode = tp["contact_mode"]
    clearance_m = float(tp.get("clearance_mm", 10.0)) / 1000.0
    touch_extra_m = float(tp.get("touch_extra_mm", 8.0)) / 1000.0
    depth_m = float(tp.get("depth_mm", 0.0)) / 1000.0
    frame = path["frame_id"]
    segs = path["segments"]
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
                               touches=touches, elapsed_s=time.monotonic() - t_start))

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
                r = adapter.move(w, frame, prof, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                                  f"{kind} {sid}: {r.message}", f"segment:{sid}")
            prog.completed_segment_id = sid
            continue

        # ---- CUT: 접촉 높이 결정 → 등속 긋기 ----
        report("ENGRAVE")
        normal_in = tool_axis_in_base(wps[0], axis_name)          # 표면 안쪽(법선 반대) 방향 = 송곳 축
        if stroke not in stroke_offset:
            if mode == "force_touch":
                # 표면 위 clearance 에서 출발해 안쪽으로 힘 감시. (APPROACH 가 이미 그 자리에 두었다고 가정하되, 확인 이동)
                start = _shift(wps[0], normal_in, -clearance_m)
                r = adapter.move(start, frame, prof, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome, r.error_code, f"CUT {sid} 접근: {r.message}", f"segment:{sid}")
                r = adapter.probe_touch(normal_in, clearance_m + touch_extra_m, tp, deadline_of(seg), context.cancel)
                if not r.ok or not r.observed_state.get("contact"):
                    return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED",
                                  r.error_code if r.error_code != "NONE" else "VALIDATION_FAILED",
                                  f"CUT {sid} 표면을 못 찾음: {r.message}", f"segment:{sid}")
                contact = r.observed_state["tcp_pose"]
                # 보정량 = 실제 접촉점이 경로 표면점보다 법선 안쪽으로 얼마나 더 갔나 (m). 같은 획 안에서는 같은 값을 쓴다.
                off = sum((contact[k] - wps[0][k]) * normal_in[k] for k in range(3))
                stroke_offset[stroke] = off
                touches.append(dict(segment_id=sid, stroke_id=stroke, force_n=r.observed_state.get("force_n"),
                                    offset_mm=round(off * 1000.0, 2), pose=contact))
            else:                                    # fixed_depth
                stroke_offset[stroke] = depth_m
                start = _shift(wps[0], normal_in, depth_m)
                r = adapter.move(start, frame, prof, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome, r.error_code, f"CUT {sid} 진입: {r.message}", f"segment:{sid}")
        off = stroke_offset[stroke]
        pts = [_shift(w, tool_axis_in_base(w, axis_name), off) for w in wps]
        # 첫 점 위에 이미 있으므로 첫 점을 빼고 보낸다 (길이 0 구간 → 제어기 등속 경고, 9/17)
        rest = pts[1:] if _dist(adapter.observe().tcp_pose or pts[0], pts[0]) < 0.0015 else pts
        for i in range(0, len(rest), MAX_SPLINE_POINTS):
            chunk = rest[i:i + MAX_SPLINE_POINTS]
            if context.cancel.is_set():
                return finish("STOPPED", "NONE", f"취소됨 (CUT {sid} 중)", f"segment:{sid}")
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
    return finish("SUCCEEDED", "NONE", f"{len(segs)} 구간 완료", "execute_path")
