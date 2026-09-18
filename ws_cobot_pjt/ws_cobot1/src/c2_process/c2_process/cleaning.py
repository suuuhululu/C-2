# cleaning.py — 도구(송곳)에 뭉친 재료 제거 순서. 담당: 이시율 (초안 2026-09-18, 로컬).
# 상태 기계가 clean_tool(tool_profile, context, adapter, return_pose) 를 부른다. 로봇 명령은 robot_adapter 로만.
#
# 방식 (9/17 지점토 실기에서 확정): 청소면(작업대의 정해진 옆면) 바깥에서 윗면 아래 wipe_down_mm 높이로 내려간 뒤,
# 청소면을 향해 힘 감시로 살짝 닿을 때까지만 접근하고, 닿은 자리에서 그대로 위로 올려 송곳을 훑어 낸다. 왕복 없이 1회.
# 여러 번 비비면 재료가 밀린다. 청소 위치·방향은 tools.yaml 의 cleaning 항목(현장 확정값)에서 온다:
#   cleaning: { pose: [x,y,z,qx,qy,qz,qw] (청소면 위 접근 기준점, m), inward: [nx,ny,nz] (청소면 안쪽 단위벡터, base),
#               up: [ux,uy,uz] (훑어 올릴 방향), approach_mm, wipe_down_mm, wipe_up_mm, touch_force_n, touch_speed_mm_s,
#               motion_profile_id, completion_timeout_s }
# 청소 뒤 복귀는 return_pose(호출자가 준 검증된 재진입 지점, 보통 다음 획의 APPROACH 점) 로만 간다. 임의의 다음 점으로 가지 않는다.
import math
from typing import Dict, Optional

from .robot_adapter import RobotAdapter, StepResult


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        raise ValueError("zero vector")
    return [x / n for x in v]


def _shift(pose, direction, meters):
    p = list(pose)
    for k in range(3):
        p[k] += direction[k] * meters
    return p


def clean_tool(tool_profile: Dict, context, adapter: RobotAdapter, return_pose: Optional[list]) -> StepResult:
    c = (tool_profile or {}).get("cleaning")
    if not c:
        return StepResult("FAILED", "UNSUPPORTED_RECIPE", "tools.yaml 에 cleaning 항목 없음", "clean_tool")
    for k in ("pose", "inward", "up", "motion_profile_id"):
        if k not in c:
            return StepResult("FAILED", "UNSUPPORTED_RECIPE", f"cleaning.{k} 없음", "clean_tool")
    prof = context.motion_profiles.get(c["motion_profile_id"])
    if prof is None:
        return StepResult("FAILED", "PROFILE_MISMATCH", f"motion_profile_id {c['motion_profile_id']!r} 없음", "clean_tool")
    deadline = float(c.get("completion_timeout_s", prof.get("completion_timeout_s", 60.0)))
    frame = c.get("frame_id") or (return_pose and None) or context.tool_profile.get("frame_id") or "dsr01_base"
    inward, up = _unit(c["inward"]), _unit(c["up"])
    approach_m = float(c.get("approach_mm", 15.0)) / 1000.0
    down_m = float(c.get("wipe_down_mm", 6.0)) / 1000.0
    up_m = float(c.get("wipe_up_mm", 20.0)) / 1000.0
    touch = dict(tool_profile, touch_force_n=float(c.get("touch_force_n", 0.7)),
                 touch_speed_mm_s=float(c.get("touch_speed_mm_s", 1.5)))

    def bail(r, what):
        return StepResult(r.outcome if r.outcome != "SUCCEEDED" else "FAILED", r.error_code, f"청소 {what}: {r.message}",
                          "clean_tool", dict(stage=what))

    if context.cancel.is_set():
        return StepResult("STOPPED", "NONE", "취소됨 (청소 전)", "clean_tool")
    base = c["pose"]
    outside = _shift(base, inward, -approach_m)                     # 청소면 바깥 접근점
    r = adapter.move(_shift(outside, up, up_m), frame, prof, deadline, context.cancel)   # 위쪽에서 들어간다
    if not r.ok:
        return bail(r, "접근")
    r = adapter.move(_shift(outside, up, -down_m), frame, prof, deadline, context.cancel)  # 윗면 아래 높이로
    if not r.ok:
        return bail(r, "하강")
    r = adapter.probe_touch(inward, approach_m + 0.012, touch, deadline, context.cancel)   # 살짝 닿을 때까지
    if not r.ok or not r.observed_state.get("contact"):
        return bail(r if not r.ok else StepResult("FAILED", "VALIDATION_FAILED", "청소면을 못 찾음", "probe_touch"), "접촉")
    touched = r.observed_state["tcp_pose"]
    r = adapter.move(_shift(touched, up, down_m + up_m), frame, prof, deadline, context.cancel)   # 닿은 채 위로 훑기
    if not r.ok:
        return bail(r, "훑기")
    r = adapter.move(_shift(_shift(touched, up, down_m + up_m), inward, -approach_m), frame, prof, deadline, context.cancel)
    if not r.ok:
        return bail(r, "이탈")
    if return_pose is not None:
        r = adapter.move(return_pose, frame, prof, deadline, context.cancel)
        if not r.ok:
            return bail(r, "복귀")
    return StepResult("SUCCEEDED", "NONE", "청소 1회 완료", "clean_tool",
                      dict(touch_force_n=touched and r.observed_state.get("force_n"), returned=return_pose is not None))
