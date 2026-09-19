# 도구 끝 보정(3점 원 맞춤·1점 확인) 모의 시험. 로봇 없이 MockRobotAdapter 로 흐름과 계산을 검증한다.
import math
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from c2_process.robot_adapter import MockRobotAdapter  # noqa: E402
from c2_process.tool_calibration import TipCalibration, measure_tool_tip, verify_tool_tip, upright_quat  # noqa: E402

WORKCELL = dict(axis_xy_m=[0.4224, -0.0026], radius_m=0.034, top_z_m=0.2344)
PROFILES = dict(travel=dict(id="travel", vel_mm_s=26.0, completion_timeout_s=60.0),
                tip_touch=dict(touch_force_n=0.8, touch_speed_mm_s=2.0))


class Ctx:
    def __init__(self):
        self.cancel = threading.Event()


def candle_surface(side, projection, lateral_x, cx=0.4224, cy=-0.0026, R=0.034):
    """모의 옆면: 패드가 (x, y) 에서 −side·Y 로 갈 때 도구 끝이 원통에 닿는 거리(m). 끝 = 패드 + lateral_x·툴X − projection·툴Y."""
    def fn(pose, direction):
        px, py = pose[0], pose[1]
        tip_x = px + lateral_x * (-side)                     # 툴 X = base (−side, 0, 0)
        dx = tip_x - cx
        if abs(dx) > R:
            return None
        y_surface = cy + side * math.sqrt(R * R - dx * dx)   # 이 면의 표면 y
        tip_y = py - side * projection                        # 툴 −Y 방향으로 돌출
        dist = side * (tip_y - y_surface)
        return dist if dist >= 0 else 0.0
    return fn


def start_upright(ad, side):
    ad.pose = [0.4221, -0.0026, 0.2644, *upright_quat(side)]


def test_measure_recovers_projection_and_lateral():
    for side, proj, lat in ((-1, 0.0633, -0.0025), (+1, 0.0513, +0.0042)):
        ad = MockRobotAdapter(surface_fn=candle_surface(side, proj, lat))
        start_upright(ad, side)
        r = measure_tool_tip(ad, WORKCELL, PROFILES, Ctx())
        assert r.ok, r
        c = r.observed_state["calibration"]
        assert abs(c["projection_m"] - proj) < 0.0004, c
        assert abs(c["lateral_x_m"] - lat) < 0.0004, c
        assert c["residual_rms_m"] < 0.0002
        assert ad.tool_offset_m == c["offset_tool_m"]
        assert [k["fn"] for k in ad.calls].count("probe_touch") == 3


def test_measure_rejects_when_not_upright():
    ad = MockRobotAdapter(surface_fn=candle_surface(-1, 0.06, 0.0))
    ad.pose = [0.4, 0.0, 0.3, 0, 0, 0, 1]                    # 툴 Z 가 위(항등 자세) = 세운 자세 아님
    r = measure_tool_tip(ad, WORKCELL, PROFILES, Ctx())
    assert r.outcome == "FAILED" and r.error_code == "NOT_READY"
    assert not any(k["fn"] == "probe_touch" for k in ad.calls)


def test_measure_no_contact_fails():
    ad = MockRobotAdapter(surface_fn=lambda p, d: None)
    start_upright(ad, -1)
    r = measure_tool_tip(ad, WORKCELL, PROFILES, Ctx())
    assert r.outcome == "FAILED" and r.completed_step == "touch0"


def test_measure_cancel_stops_before_touch():
    ad = MockRobotAdapter(surface_fn=candle_surface(-1, 0.06, 0.0))
    start_upright(ad, -1)
    ctx = Ctx(); ctx.cancel.set()
    r = measure_tool_tip(ad, WORKCELL, PROFILES, ctx)
    assert r.outcome == "STOPPED"


def test_verify_passes_then_fails_after_shift():
    side, proj, lat = -1, 0.0633, -0.0025
    ad = MockRobotAdapter(surface_fn=candle_surface(side, proj, lat))
    start_upright(ad, side)
    r = measure_tool_tip(ad, WORKCELL, PROFILES, Ctx())
    calib = TipCalibration(**r.observed_state["calibration"])
    r2 = verify_tool_tip(ad, WORKCELL, PROFILES, calib, Ctx())
    assert r2.ok, r2
    assert ad.tool_offset_m == calib.offset_tool_m                 # 검사 뒤 오프셋 복원
    ad.surface_fn = candle_surface(side, proj - 0.003, lat)         # 드릴이 3 mm 밀려 들어감
    r3 = verify_tool_tip(ad, WORKCELL, PROFILES, calib, Ctx())
    assert r3.outcome == "FAILED" and abs(r3.observed_state["error_m"] - 0.003) < 0.0005, r3


def test_measure_failure_restores_previous_offset():
    ad = MockRobotAdapter(surface_fn=lambda p, d: None, fail_at="probe_touch")
    start_upright(ad, -1)
    ad.set_tool_offset([0.001, -0.05, 0.0])
    r = measure_tool_tip(ad, WORKCELL, PROFILES, Ctx())
    assert r.outcome == "FAILED" and r.error_code == "NOT_READY" and r.completed_step == "touch0", r   # 모의 실패 그대로
    assert ad.tool_offset_m == [0.001, -0.05, 0.0]


def test_verify_passes_stop_and_retreat_failure_through():
    side, proj, lat = -1, 0.0633, -0.0025
    ad = MockRobotAdapter(surface_fn=candle_surface(side, proj, lat))
    start_upright(ad, side)
    calib = TipCalibration(**measure_tool_tip(ad, WORKCELL, PROFILES, Ctx()).observed_state["calibration"])
    ctx = Ctx(); ctx.cancel.set()
    r = verify_tool_tip(ad, WORKCELL, PROFILES, calib, ctx)
    assert r.outcome == "STOPPED", r                                   # 취소는 STOPPED 그대로
    assert ad.tool_offset_m == calib.offset_tool_m
    ad2 = MockRobotAdapter(surface_fn=candle_surface(side, proj, lat), fail_at="move")
    start_upright(ad2, side)
    r = verify_tool_tip(ad2, WORKCELL, PROFILES, calib, Ctx())
    assert r.outcome == "FAILED" and r.error_code == "NOT_READY", r     # 이동(이탈 포함) 실패는 그 결과 그대로
