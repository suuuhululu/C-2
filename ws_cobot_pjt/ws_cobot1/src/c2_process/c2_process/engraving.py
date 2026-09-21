# engraving.py — 확정된 실행 경로(path.json)의 조각 실행·진행 보고. 담당: 이시율 (초안 2026-09-18, main 이관 2026-09-19).
# 9/19 결정: 기준 도구 engraving_drill(철사 고정, 집기·반납·청소 없음), 도구 축은 tools.yaml 의 tool_axis(팀 규칙 툴 -Y = 표면 안쪽),
# frame_id c2_base. 실기 성공 조건(9/18 드릴 하트): 획 시작 터치 1.5 mm/s·0.8 N, 긋기 6.6 mm/s, 접근 여유 6 mm.
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
    # 최종 검사 성공 뒤 호출자가 기록. HMI 파일 바이트 해시와 별도인 내부 계획 해시.
    prechecked_execution_sha256: Optional[str] = None


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


def execution_path_digest(path: Dict) -> str:
    """내부 실행 계획의 객체 해시. 외부 path/profile 파일 SHA-256을 대체하지 않는다."""
    return hashlib.sha256(json.dumps(path, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _execution_settings(context):
    return dict(tool_profile=copy.deepcopy(context.tool_profile),
                motion_profiles=copy.deepcopy(context.motion_profiles),
                stop_profile=copy.deepcopy(context.stop_profile), source_mode=context.source_mode)


def prepare_execution_path(path: Dict, context: ExecutionContext) -> Dict:
    """깊이를 한 번 적용한 복사본 반환. 관절 검사 전에 호출하며 중심·높이는 옮기지 않는다.

    원본 ID/버전/참조 해시는 유지하고 execution_plan에 파생 관계를 기록한다.
    이 함수는 경로 검사/승인이 아니다. 호출자가 최종 경로와 진입·이탈을 검사해야 한다.
    """
    err = validate_path(path, context)
    if err:
        raise ValueError(err.message)
    if 'execution_plan' in path:
        raise ValueError('이미 준비된 경로: 깊이 중복 적용 금지')
    tp = context.tool_profile
    if tp['contact_mode'] != 'fixed_depth':
        raise ValueError('확정 경로 실행은 fixed_depth만 지원; 접촉 재보정은 재검사 필요')
    depth = _m(tp, 'depth')
    if not math.isfinite(depth) or depth < 0:
        raise ValueError('depth_m은 유한한 0 이상 값이어야 함')
    if tp.get('surface_z_gradient', 0) or tp.get('adaptive_max_m', 0) or tp.get('cut_monitor'):
        raise ValueError('실행 중 좌표 변경 설정을 제거하고 최종 경로를 먼저 검사해야 함')
    maximum = _m(tp, 'max_depth')
    if maximum is not None and (not math.isfinite(maximum) or depth > maximum):
        raise ValueError('목표 깊이가 max_depth를 초과함')
    out = copy.deepcopy(path)
    for segment in out['segments']:
        if segment['kind'] == 'CUT':
            segment['waypoints'] = [_shift(w, tool_axis_in_base(w, tp.get('tool_axis', '-y')), depth)
                                    for w in segment['waypoints']]
    out['execution_plan'] = dict(version=1, interpolation='LINEAR', depth_m=depth,
        source_object_sha256=execution_path_digest(path), settings=_execution_settings(context))
    # 표면 경로의 검증 통과를 깊이 적용 경로의 검증으로 잘못 재사용하지 않는다.
    out['validation'] = dict(passed=False, not_checked=['FINAL_IK_JOINTS', 'ENTRY_EXIT', 'INTERPOLATION_COLLISION'])
    return out


def _execute_prepared(path, context, adapter, on_progress):
    """최종 경로의 점을 생략/추가 보정하지 않고 직선 명령으로 실행한다."""
    plan = path['execution_plan']
    if context.tool_profile.get('contact_mode') != 'fixed_depth':
        return StepResult('FAILED', 'UNSUPPORTED_RECIPE', '확정 경로는 fixed_depth 필요', 'execute_path')
    required = ('vel_mm_s', 'acc_mm_s2', 'completion_timeout_s')
    if context.source_mode == 'REAL':
        required += ('angular_vel_deg_s', 'angular_acc_deg_s2', 'pos_tol_mm', 'angle_tol_deg',
                     'force_limit_n', 'completion_settle_s', 'start_timeout_s')
    for seg in path['segments']:
        prof = context.motion_profiles[seg['motion_profile_id']]
        if any(not isinstance(prof.get(k), (int, float)) or not math.isfinite(prof[k]) or prof[k] <= 0 for k in required):
            return StepResult('FAILED', 'UNSUPPORTED_RECIPE', '이동/감시 프로파일 필수값 미확정', 'execute_path')
    timeout = context.stop_profile.get('confirmation_timeout_s')
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        return StepResult('FAILED', 'UNSUPPORTED_RECIPE', '정지 확인 제한 시간 미확정', 'execute_path')
    digest = execution_path_digest(path)
    if plan.get('version') != 1 or plan.get('interpolation') != 'LINEAR':
        return StepResult('FAILED', 'INVALID_INPUT', '미지원 실행 계획', 'execute_path')
    if plan.get('settings') != _execution_settings(context):
        return StepResult('FAILED', 'PROFILE_MISMATCH', '검사 이후 실행 설정 변경', 'execute_path')
    if context.prechecked_execution_sha256 != digest:
        return StepResult('FAILED', 'VALIDATION_FAILED', '최종 검사 경로와 실행 계획 해시 불일치', 'execute_path')
    if context.source_mode == 'REAL':
        if path.get('test_only') or path.get('frame_id') != 'c2_base':
            return StepResult('FAILED', 'INVALID_INPUT', 'REAL 경로/좌표계 확인 필요', 'execute_path')
        offset = context.tool_profile.get('tool_offset_m')
        if offset is None or list(offset) != getattr(adapter, 'tool_offset_m', None):
            return StepResult('FAILED', 'PROFILE_MISMATCH', '검사 설정과 실제 어댑터 도구 오프셋 불일치', 'execute_path')
    # 공유 입력/진행 콜백이 명령 도중 좌표와 설정을 바꾸지 못하도록 이미 복사된 값을 사용.
    total = sum(_seg_length(s['waypoints']) for s in path['segments'] if s['kind'] == 'CUT')
    done = 0.; last = ''; started = time.monotonic()
    def result(r, sid=''):
        obs = dict(r.observed_state or {})
        obs.update(last_completed_segment_id=last, engraving_progress=done / total if total else 0.,
                   execution_sha256=digest, elapsed_s=time.monotonic()-started)
        return StepResult(r.outcome, r.error_code, r.message, sid or r.completed_step, obs)
    def cancelled():
        try:
            stopped = adapter.stop(context.stop_profile, float(context.stop_profile['confirmation_timeout_s']))
        except Exception as exc:
            return result(StepResult('UNKNOWN', 'STOP_UNCONFIRMED', str(exc), 'execute_path',
                                     {'stop_confirmed': False}))
        confirmed = stopped.ok and stopped.observed_state.get('stop_confirmed') is True
        return result(StepResult('STOPPED' if confirmed else 'UNKNOWN',
            'NONE' if confirmed else 'STOP_UNCONFIRMED', '조각 취소', 'execute_path', stopped.observed_state))
    for seg in path['segments']:
        if context.cancel.is_set():
            return cancelled()
        if on_progress:
            on_progress(dict(phase=seg['kind'], completed_segment_id=last,
                             engraving_progress=done/total if total else 0., execution_sha256=digest))
        profile = context.motion_profiles[seg['motion_profile_id']]
        for waypoint in seg['waypoints']:
            if context.source_mode == 'REAL' and list(context.tool_profile['tool_offset_m']) != getattr(adapter, 'tool_offset_m', None):
                return result(StepResult('FAILED', 'PROFILE_MISMATCH', '도구 오프셋 변경', 'execute_path'))
            if context.cancel.is_set():
                return cancelled()
            motion_profile = dict(copy.deepcopy(profile), stop_profile=copy.deepcopy(context.stop_profile))
            try:
                r = adapter.move(list(waypoint), path['frame_id'], motion_profile,
                                 float(profile['completion_timeout_s']), context.cancel)
            except Exception as exc:
                try:
                    stopped = adapter.stop(context.stop_profile, float(context.stop_profile['confirmation_timeout_s']))
                    obs = stopped.observed_state
                except Exception:
                    obs = {'stop_confirmed': False}
                return result(StepResult('FAILED' if obs.get('stop_confirmed') else 'UNKNOWN',
                              'ADAPTER_EXCEPTION', str(exc), 'execute_path', obs))
            if not r.ok:
                return result(r, 'segment:' + seg['segment_id'])
        last = seg['segment_id']
        if seg['kind'] == 'CUT':
            done += _seg_length(seg['waypoints'])
    if context.cancel.is_set():
        return cancelled()
    return result(StepResult('SUCCEEDED', message='확정 실행 경로 완료', completed_step='execute_path'))


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
    if context.source_mode not in ('SIMULATION', 'REAL'):
        return StepResult('FAILED', 'INVALID_INPUT', '실행 모드 없음', 'validate')
    segs = path.get("segments") or []
    if not segs:
        return StepResult("FAILED", "INVALID_INPUT", "segments 비어 있음", "validate")
    if not any(s.get('kind') == 'CUT' for s in segs):
        return StepResult('FAILED', 'INVALID_INPUT', 'CUT 없는 경로', 'validate')
    for s in segs:
        if s.get("kind") not in SEGMENT_KINDS:
            return StepResult("FAILED", "INVALID_INPUT", f"segment {s.get('segment_id')} kind {s.get('kind')!r}", "validate")
        wps = s.get("waypoints") or []
        if len(wps) < 1 or any(len(w) != 7 for w in wps):
            return StepResult("FAILED", "INVALID_INPUT", f"segment {s.get('segment_id')} waypoint 형식 (7개 값 필요)", "validate")
        if any(not all(isinstance(v, (int, float)) and math.isfinite(v) for v in w) or
               abs(sum(v*v for v in w[3:])-1.) > 0.01 for w in wps):
            return StepResult('FAILED', 'INVALID_INPUT', '비유한 좌표/잘못된 quaternion', 'validate')
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
    # Event는 공유하고 설정/경로는 불변 실행 사본으로 묶는다.
    path = copy.deepcopy(path)
    frozen = copy.copy(context)
    frozen.tool_profile = copy.deepcopy(context.tool_profile)
    frozen.motion_profiles = copy.deepcopy(context.motion_profiles)
    frozen.stop_profile = copy.deepcopy(context.stop_profile)
    context = frozen
    err = validate_path(path, context)
    if err:
        return err
    if adapter is None:
        return StepResult("FAILED", "NOT_READY", "robot_adapter 없음", "execute_path")
    if 'execution_plan' in path:
        return _execute_prepared(path, context, adapter, on_progress)
    if context.source_mode == 'REAL':
        return StepResult('FAILED', 'VALIDATION_FAILED',
                          'prepare_execution_path → 최종 검사 → 해시 연결 후 실행 필요', 'execute_path')
    tp = context.tool_profile
    axis_name = tp.get("tool_axis", "-y")            # 도구가 향하는 축 (9/19 팀 규칙: 툴 -Y = 표면 안쪽). tools.yaml 값이 우선 (경로 자세에서 표면 법선 안쪽을 가리켜야 함)
    mode = tp["contact_mode"]
    clearance_m = _m(tp, "clearance", 0.010)          # v2: 거리 필드는 m (clearance_m). *_mm 는 과도기 호환
    touch_extra_m = _m(tp, "touch_extra", 0.008)
    depth_m = _m(tp, "depth", 0.0)
    frame = path["frame_id"]
    segs = path["segments"]
    prog = _Progress(total_cut_m=sum(_seg_length(s["waypoints"]) for s in segs if s["kind"] == "CUT"))
    touches: List[Dict] = []
    stroke_touch_z: Dict[str, float] = {}
    stroke_bias: Dict[str, Optional[List[float]]] = {}
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
                # 9/20 실기: 이동 직후 힘이 튀어(드리프트) 정착 전 비상 기준(2×hard)에 걸려 공중에서 "접촉" → 허공에 하트.
                # 터치 전 잠깐 멈춰 힘이 가라앉게 한 뒤 기준을 잡는다 (LESSONS L13).
                time.sleep(float(tp.get("pre_touch_pause_s", 2.0)))
                try:
                    stroke_bias[stroke] = adapter.read_force_bias()      # 공중 정지 상태의 힘 편향 (법선 힘 계산용)
                except Exception:
                    stroke_bias[stroke] = None
                r = adapter.probe_touch(normal_in, clearance_m + touch_extra_m, tp, deadline_of(seg), context.cancel)
                if not r.ok or not r.observed_state.get("contact"):
                    return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED",
                                  r.error_code if r.error_code != "NONE" else "VALIDATION_FAILED",
                                  f"CUT {sid} 표면을 못 찾음: {r.message}", f"segment:{sid}")
                contact = r.observed_state.get("onset_pose") or r.observed_state["tcp_pose"]
                # 보정량 = 실제 접촉점이 경로 표면점보다 법선 안쪽으로 얼마나 더 갔나 (m). 같은 획 안에서는 같은 값을 쓴다.
                off = sum((contact[k] - wps[0][k]) * normal_in[k] for k in range(3))
                # 시작 전 확인: 표면이 경로가 말한 자리에서 허용 범위 밖이면 양초가 없거나 옮겨진 것 → 움직이지 않고 중단
                # 기준: 실행기가 조각 직전에 잰 표면 오프셋(expected_touch_offset_m)이 있으면 그것 대비, 없으면 경로 표면 대비
                max_off = float(tp.get("max_touch_offset_m", 0.004))
                expected = float(tp.get("expected_touch_offset_m", 0.0))
                f_n = float(r.observed_state.get("force_n") or 0.0)
                if abs(off - expected) > max_off or f_n > float(tp.get("max_touch_force_n", 6.0)):
                    touches.append(dict(segment_id=sid, stroke_id=stroke, force_n=f_n, offset_mm=round(off * 1000.0, 2), pose=contact, rejected=True))
                    return finish("FAILED", "VALIDATION_FAILED",
                                  f"CUT {sid} 표면 위치 확인 실패: 경로 표면 대비 {off * 1000:+.1f} mm, 기대 {expected * 1000:+.1f} ± {max_off * 1000:.0f}, 힘 {f_n:.1f} N", f"segment:{sid}")
                stroke_offset[stroke] = off + depth_m
                stroke_touch_z[stroke] = contact[2]
                touches.append(dict(segment_id=sid, stroke_id=stroke, force_n=r.observed_state.get("force_n"),
                                    offset_mm=round(off * 1000.0, 2), pose=contact))
            else:                                    # fixed_depth
                stroke_offset[stroke] = depth_m
                start = _shift(wps[0], normal_in, depth_m)
                r = adapter.move(start, frame, prof, deadline_of(seg), context.cancel)
                if not r.ok:
                    return finish(r.outcome, r.error_code, f"CUT {sid} 진입: {r.message}", f"segment:{sid}")
        off = stroke_offset[stroke]
        # z 기울기 보정 (9/20: 양초가 기울었거나 위로 가늘어져 봉오리(높은 z)에서 표면이 더 안쪽 → 스크래치만 남음).
        # tools 프로파일 surface_z_gradient = 높이 1 m 당 법선 안쪽 보정량[m], 기준 z = 이 획의 터치 높이.
        grad = float(tp.get("surface_z_gradient", 0.0))
        z_ref = stroke_touch_z.get(stroke, wps[0][2])
        pts = [_shift(w, tool_axis_in_base(w, axis_name), off + grad * (w[2] - z_ref)) for w in wps]
        # 1 mm 미만 간격 점은 걸러낸다 (제어기 경고 3213: 구간 길이 1 mm 미만이면 등속 불가, 9/20 Seg-26)
        thin = [pts[0]]
        for q in pts[1:-1]:
            if _dist(q, thin[-1]) >= 0.0011:
                thin.append(q)
        if len(pts) > 1:
            thin.append(pts[-1])
        pts = thin
        # 첫 점 위에 이미 있으므로 첫 점을 빼고 보낸다 (길이 0 구간 → 제어기가 movesx 를 무시, 9/20 seg-0003 무동작).
        # 완료 허용 오차(pos_tol 2 mm)만큼 어긋나 있을 수 있으니 3 mm 안이면 뺀다.
        rest = pts[1:] if _dist(adapter.observe().tcp_pose or pts[0], pts[0]) < 0.003 else pts
        # 깊이 추종 (9/20 사용자: 힘이 안 걸리면 더 들어가라): cut_monitor 가 있으면 획을 adaptive_chunk_points 씩 잘라 긋고,
        # 조각마다 긋는 동안의 평균 힘이 min 아래면 다음 조각을 step 만큼 더 안쪽으로, max 넘으면 바깥으로 옮긴다 (누적 ±adaptive_max).
        mon_cfg = tp.get("cut_monitor")
        chunk_n = int(tp.get("adaptive_chunk_points", 10)) if mon_cfg else MAX_SPLINE_POINTS
        chunk_n = max(2, min(chunk_n, MAX_SPLINE_POINTS))
        adapt = 0.0
        step_m = float(tp.get("adaptive_step_m", 0.0003)); adapt_max = float(tp.get("adaptive_max_m", 0.003))
        i = 0
        while i < len(rest):
            chunk = rest[i:i + chunk_n]
            i += chunk_n
            if adapt:
                chunk = [_shift(w, tool_axis_in_base(w, axis_name), adapt) for w in chunk]
            if context.cancel.is_set():
                return finish("STOPPED", "NONE", f"취소됨 (CUT {sid} 중)", f"segment:{sid}")
            if mon_cfg:
                mid = chunk[len(chunk) // 2]
                adapter.contact_monitor = dict(mon_cfg, samples=[], normal=list(tool_axis_in_base(mid, axis_name)), bias=stroke_bias.get(stroke))
            try:
                if len(chunk) >= 2:
                    r = adapter.move_spline(chunk, frame, prof, deadline_of(seg), context.cancel)
                else:
                    r = adapter.move(chunk[-1], frame, prof, deadline_of(seg), context.cancel)
            finally:
                mon = getattr(adapter, "contact_monitor", None); adapter.contact_monitor = None
            if mon_cfg and mon and mon.get("samples"):
                smp = mon["samples"]; mean_f = sum(smp) / len(smp)
                lo, hi = float(mon_cfg.get("min_force_n", 0.8)), float(mon_cfg.get("max_force_n", 6.0))
                if mean_f < lo and adapt < adapt_max:
                    adapt = min(adapt_max, adapt + (step_m * 2.0 if mean_f < 0.3 else step_m))   # 9/20: 0.3 N 미만은 사실상 공중 → 두 배
                elif mean_f > hi and adapt > -adapt_max:
                    adapt = max(-adapt_max, adapt - step_m)
                touches.append(dict(segment_id=sid, stroke_id=stroke, chunk_end=i, mean_force_n=round(mean_f, 2), adapt_mm=round(adapt * 1000, 2)))
            if not r.ok:
                return finish(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code,
                              f"CUT {sid}: {r.message}", f"segment:{sid}")
        prog.done_cut_m += _seg_length(wps)
        prog.completed_segment_id = sid
        report("ENGRAVE")

    report("RETRACT")
    return finish("SUCCEEDED", "NONE", f"{len(segs)} 구간 완료", "execute_path")
