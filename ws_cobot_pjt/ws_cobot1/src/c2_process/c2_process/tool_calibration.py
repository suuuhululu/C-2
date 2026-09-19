# tool_calibration.py — 드릴(도구) 끝 보정. 담당: 이시율 (2026-09-19).
# 9/19 결정: 드릴은 그리퍼에 철사로 고정(집기·반납 없음, 그리퍼 열기 금지). 도구 끝은 패드(제어기 TCP GripperDA_v1) 축에서
# 툴 -Y 로 돌출 길이만큼, 툴 X 로 몇 mm 어긋나 있다 (9/18 실측: 송곳 51.3/+4.2, 드릴 63.3/-2.5 mm). 길이 한 축만 재면 중심을
# 비껴가므로 (LESSONS_ROBOT L4) 원통 옆면을 세 점 터치해 반지름 고정 원을 맞춰 길이·어긋남을 같이 구한다.
#
# 쓰는 법 (상태 기계가 함수로 부른다, 새 ROS 통신 없음):
#   장착·재장착 때  : measure_tool_tip(adapter, workcell, profiles, context, ...) → TipCalibration, 어댑터 set_tool_offset 적용
#   매 실행 시작    : verify_tool_tip(adapter, workcell, profiles, calib, context, ...) → StepResult (저장값과 tol 안이면 SUCCEEDED)
# 전제: 그리퍼가 세워져(툴 +Z = base -Z) 있고 툴 Y 가 base ±Y 를 향한다 (9/18 실기 자세). 도구는 툴 -Y 로 돌출.
# 좌표는 m·quaternion(x,y,z,w), frame_id 는 어댑터 값. 어댑터의 tool_offset 은 측정 중 비워 두고(패드 기준) 끝나면 적용한다.
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .robot_adapter import RobotAdapter, StepResult, matrix_to_quat, tool_axis_in_base

CHORD_OFFSETS_M = (0.0, +0.015, -0.015)     # 축 위, 축 ±15 mm 세 현 (9/18 실기 순서)
FIT_SEARCH_M = 0.025                         # 원 중심 x 탐색 폭 ±
FIT_STEP_M = 0.00025                         # 탐색 간격 (0.25 mm)
DEFAULT_MAX_PROJECTION_M = 0.110             # 이보다 길게 물렸을 리 없음 → 첫 접근 거리 산정
DEFAULT_CLEAR_M = 0.015


@dataclass
class TipCalibration:
    tool_id: str
    projection_m: float                      # 패드 중심 → 도구 끝 (툴 -Y)
    lateral_x_m: float                       # 도구 끝의 툴 X 어긋남
    offset_tool_m: List[float]               # 어댑터 set_tool_offset 값 = [lateral_x, -projection, 0]
    residual_rms_m: float                    # 3점 원 맞춤 잔차
    axis_fit_xy_m: List[float]               # 패드 기준으로 본 원 중심 (x_fit, y_offset)
    side: int                                # +1: 툴 Y = base +Y (+Y 면 측정), -1: 180° 돌린 자세 (-Y 면)
    z_m: float
    points_pad_m: List[List[float]] = field(default_factory=list)
    forces_n: List[float] = field(default_factory=list)
    measured_at: float = 0.0

    def to_dict(self):
        return asdict(self)


def upright_quat(side: int):
    """세운 자세 quaternion: 툴 Z = base -Z, 툴 Y = base (0, side, 0), 툴 X = Y × Z = (-side, 0, 0)."""
    x = [-side, 0.0, 0.0]; y = [0.0, float(side), 0.0]; z = [0.0, 0.0, -1.0]
    return matrix_to_quat([[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]])


def _side_from_pose(pose) -> Optional[int]:
    """지금 자세가 세운 자세인지 확인하고 툴 Y 방향(±base Y)을 돌려준다. 아니면 None."""
    tz = tool_axis_in_base(pose, "+z"); ty = tool_axis_in_base(pose, "+y")
    if tz[2] > -0.98 or abs(ty[1]) < 0.98:
        return None
    return 1 if ty[1] > 0 else -1


def _fit_circle(points, cx_guess, radius, side):
    """반지름 고정 원 맞춤: pad_y = yoff + side·sqrt(R² − (pad_x − cx_fit)²). cx_fit 격자 탐색, yoff 평균."""
    best = None
    n = int(FIT_SEARCH_M / FIT_STEP_M)
    for k in range(-n, n + 1):
        cxf = cx_guess + k * FIT_STEP_M
        ys = [y - side * math.sqrt(max(0.0, radius * radius - (x - cxf) ** 2)) for (x, y) in points]
        yoff = sum(ys) / len(ys)
        err = sum((v - yoff) ** 2 for v in ys)
        if best is None or err < best[0]:
            best = (err, cxf, yoff)
    err, cxf, yoff = best
    return cxf, yoff, math.sqrt(err / len(points))


def _touch_profile(profiles: Dict, speed_mm_s: float, long_approach: bool) -> Dict:
    """긴 접근(≥ 20 mm)은 완만 상승 판정을 끄고 정착을 길게 (LESSONS L2: 회전 뒤 이동 방향 반력 드리프트 → 거짓 접촉)."""
    p = dict(profiles.get("tip_touch", {}))
    p.setdefault("touch_force_n", 0.8); p.setdefault("touch_step_n", 1.5); p.setdefault("hard_limit_n", 2.5)
    p["touch_speed_mm_s"] = speed_mm_s
    if long_approach:
        p.update(settle_s=3.0, settle_mm=10.0, touch_force_n=99.0)      # 완만 판정 사실상 끔, 급증·|Δ|≥hard 만
    else:
        p.update(settle_s=1.2, settle_mm=2.0)
    return p


def _pad_xy(res: StepResult):
    op = res.observed_state.get("onset_pose") or res.observed_state.get("tcp_pose")
    return [op[0], op[1]]


def measure_tool_tip(adapter: RobotAdapter, workcell: Dict, profiles: Dict, context, tool_id: str = "engraving_drill",
                     z_m: Optional[float] = None, side: Optional[int] = None, apply: bool = True,
                     max_projection_m: float = DEFAULT_MAX_PROJECTION_M, clear_m: float = DEFAULT_CLEAR_M) -> StepResult:
    """원통 옆면 3점 터치로 도구 끝의 돌출 길이·툴 X 어긋남을 재고 (apply=True 면) 어댑터에 오프셋을 넣는다.
    workcell: {axis_xy_m: [x, y], radius_m, top_z_m}.  profiles: {travel: 이동 프로파일, tip_touch: 터치 프로파일(선택)}.
    context: cancel(threading.Event) 를 가진 실행 맥락.  z_m: 측정 높이 (기본 윗면 −45 mm).
    시작 자세: 세운 그리퍼, 툴 Y 가 base ±Y, 원통 위·옆 어디든 (첫 이동은 같은 높이에서 바깥 y 로 나간 뒤 z 로 내려간다).
    반환 observed_state: calibration(TipCalibration.to_dict())."""
    cx, cy = float(workcell["axis_xy_m"][0]), float(workcell["axis_xy_m"][1])
    R = float(workcell["radius_m"]); top = float(workcell["top_z_m"])
    z = top - 0.045 if z_m is None else float(z_m)
    travel = profiles["travel"]
    cancel = getattr(context, "cancel", None)
    st = adapter.observe()
    s = side if side is not None else _side_from_pose(st.tcp_pose)
    if s is None:
        return StepResult("FAILED", "NOT_READY", "그리퍼가 세운 자세(툴 +Z 아래, 툴 Y = ±base Y)가 아님", "measure_tool_tip")
    q = upright_quat(s)
    prev_offset = list(adapter.tool_offset_m) if getattr(adapter, "tool_offset_m", None) else None
    adapter.set_tool_offset(None)                                   # 측정은 패드 기준. 실패하면 prev_offset 으로 되돌린다
    y_far = cy + s * (R + max_projection_m + clear_m)
    frame = adapter.frame_id

    def fail(r: StepResult) -> StepResult:
        """중간 실패·정지·시간 초과: 결과(outcome·error_code)는 그대로 넘기고 오프셋만 이전 값으로 복원."""
        adapter.set_tool_offset(prev_offset)
        return r

    def move(x, y, zz, step):
        r = adapter.move([x, y, zz, *q], frame, travel, float(travel.get("completion_timeout_s", 60.0)), cancel)
        if not r.ok:
            r.completed_step = step
        return r

    # 1) 지금 높이에서 바깥으로 → 측정 높이로 (대각선 금지: 도구 끝이 윗모서리에 걸림, LESSONS L7)
    cur = st.tcp_pose
    r = move(cur[0], y_far, cur[2], "go_out")
    if not r.ok:
        return fail(r)
    r = move(cx, y_far, z, "go_down")
    if not r.ok:
        return fail(r)
    points, forces = [], []
    for i, u in enumerate(CHORD_OFFSETS_M):
        if i == 0:
            travel_m, speed, long_ap = max_projection_m + clear_m + 0.005, 4.0, True
        else:
            # 첫 접촉 y 보다 8.5 mm 바깥에서 (곡률로 3.5 mm 더 안쪽에 표면) 2 mm/s
            r = move(cx + u, points[0][1] + s * (0.012 - 0.0035), z, f"go_chord{i}")
            if not r.ok:
                return fail(r)
            travel_m, speed, long_ap = 0.025, 2.0, False
        prof = _touch_profile(profiles, speed, long_ap)
        deadline = travel_m * 1000.0 / speed + 10.0
        r = adapter.probe_touch([0.0, -float(s), 0.0], travel_m, prof, deadline, cancel)
        if not r.ok:                                                # STOPPED / UNKNOWN(TIMEOUT) / FAILED 는 그대로 상위로
            r.completed_step = f"touch{i}"
            return fail(r)
        if not r.observed_state.get("contact"):
            return fail(StepResult("FAILED", "VALIDATION_FAILED", f"touch{i}: {travel_m * 1000:.0f} mm 안에 접촉 없음", f"touch{i}"))
        pxy = _pad_xy(r)
        points.append(pxy); forces.append(float(r.observed_state.get("force_n", 0.0)))
        r = move(pxy[0], pxy[1] + s * 0.012, z, f"back{i}")            # 12 mm 물러남
        if not r.ok:
            return fail(r)
    cx_fit, yoff, rms = _fit_circle(points, cx, R, s)
    projection = s * (yoff - cy)                                        # 패드 y(축 위 접촉) − 표면 y = 돌출 길이
    lateral_x = s * (cx_fit - cx)                                       # 툴 X = base (−side, 0, 0)
    calib = TipCalibration(tool_id=tool_id, projection_m=projection, lateral_x_m=lateral_x,
                           offset_tool_m=[lateral_x, -projection, 0.0], residual_rms_m=rms,
                           axis_fit_xy_m=[cx_fit, yoff], side=s, z_m=z, points_pad_m=points, forces_n=forces,
                           measured_at=time.time())
    if projection <= 0.0 or projection > max_projection_m:
        return fail(StepResult("FAILED", "VALIDATION_FAILED", f"돌출 길이 {projection * 1000:.1f} mm 비정상", "fit",
                               dict(calibration=calib.to_dict())))
    adapter.set_tool_offset(calib.offset_tool_m if apply else prev_offset)
    return StepResult("SUCCEEDED", "NONE", f"돌출 {projection * 1000:.1f} mm, 툴X 어긋남 {lateral_x * 1000:+.1f} mm, "
                      f"잔차 {rms * 1000:.2f} mm", "measure_tool_tip", dict(calibration=calib.to_dict()))


def verify_tool_tip(adapter: RobotAdapter, workcell: Dict, profiles: Dict, calib: TipCalibration, context,
                    tol_m: float = 0.001) -> StepResult:
    """매 실행 시작: 축 위 한 점만 터치해 저장된 보정값(측정 당시 접촉 y)과 tol 안인지 본다. 넘으면 FAILED → 3점 재측정.
    어댑터 오프셋은 검사 중 비웠다가 끝나면 원래 값으로 되돌린다."""
    cx = float(workcell["axis_xy_m"][0]); s = int(calib.side); z = float(calib.z_m)
    q = upright_quat(s); travel = profiles["travel"]; frame = adapter.frame_id
    cancel = getattr(context, "cancel", None)
    saved = list(calib.offset_tool_m)
    adapter.set_tool_offset(None)
    y_expect = calib.axis_fit_xy_m[1] + s * float(workcell["radius_m"])      # 축 위에서 패드가 닿는 y
    try:
        st = adapter.observe(); cur = st.tcp_pose
        r = adapter.move([cur[0], y_expect + s * 0.020, cur[2], *q], frame, travel, 60.0, cancel)
        if not r.ok:
            return r
        r = adapter.move([calib.axis_fit_xy_m[0], y_expect + s * 0.010, z, *q], frame, travel, 60.0, cancel)
        if not r.ok:
            return r
        prof = _touch_profile(profiles, 2.0, False)
        r = adapter.probe_touch([0.0, -float(s), 0.0], 0.020, prof, 20.0, cancel)
        if not r.ok:                                                        # STOPPED / UNKNOWN(TIMEOUT) / FAILED 그대로 상위로
            r.completed_step = "verify_touch"
            return r
        if not r.observed_state.get("contact"):
            return StepResult("FAILED", "VALIDATION_FAILED", "확인 터치: 20 mm 안에 접촉 없음 → 3점 재측정", "verify_touch")
        y_got = _pad_xy(r)[1]
        err = -s * (y_got - y_expect)                                       # + 면 패드가 더 안쪽까지 가야 닿음 (도구가 짧아짐·밀려 들어감)
        obs = dict(error_m=err, contact_pad_y_m=y_got, expected_pad_y_m=y_expect)
        r = adapter.move([calib.axis_fit_xy_m[0], y_got + s * 0.012, z, *q], frame, travel, 60.0, cancel)
        if not r.ok:                                                        # 이탈 실패도 그 결과 그대로 (오차값은 같이 넘김)
            r.completed_step = "verify_retreat"; r.observed_state.update(obs)
            return r
        ok = abs(err) <= tol_m
        return StepResult("SUCCEEDED" if ok else "FAILED", "NONE" if ok else "VALIDATION_FAILED",
                          f"확인 터치 오차 {err * 1000:+.2f} mm (허용 ±{tol_m * 1000:.1f})", "verify_tool_tip", obs)
    finally:
        adapter.set_tool_offset(saved)
