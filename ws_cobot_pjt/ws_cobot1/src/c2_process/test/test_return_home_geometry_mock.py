"""return_home 이 실행 workcell 의 실측 축·반지름을 쓰는지 (mock, 실기 아님).

8점 측정이 끝나면 실행 workcell 에 axis_xy_m/radius_m 이 실리지만, 측정 전 탐색용 추정치
seed_axis_xy_m/seed_radius_m 도 함께 남는다. return_home 이 seed 를 읽으면 실제 양초와 다른
원통 주위로 복귀 경로를 검사한다.

이 시험은 특정 양초 좌표를 박지 않는다. 기존 mock workcell 의 seed 에 합성 오프셋만 더해
"어느 쌍을 읽었는가" 만 본다.
"""
import math

import pytest

from test_execution_plan import home_workcell, home_ctx, HomeMock, cut_end_tip
from c2_process.engraving import return_home, _candle_geometry
from c2_process.robot_adapter import apply_tool_offset

SHIFT_XY = (0.003, 0.0003)      # seed 대비 실측 중심 오프셋 (합성값)
RADIUS_DELTA = -0.0004          # seed 대비 실측 반지름 차이 (합성값)


def measured_workcell():
    """seed 는 남긴 채 실측 키를 얹는다 — 측정 후 실행 프로파일과 같은 모양."""
    w = home_workcell()
    w["axis_xy_m"] = [w["seed_axis_xy_m"][0] + SHIFT_XY[0], w["seed_axis_xy_m"][1] + SHIFT_XY[1]]
    w["radius_m"] = w["seed_radius_m"] + RADIUS_DELTA
    return w


def tip_on_measured_surface(w, inside_m=0.0008, z=0.17):
    """실측 원통 표면 안쪽 inside_m, 축을 −Y 로 보는 자세 (cut_end_tip 과 같은 자세)."""
    c, r = w["axis_xy_m"], w["radius_m"]
    return [c[0], c[1] - (r - inside_m), z, *cut_end_tip(home_workcell())[3:]]


def ctx(mode):
    c = home_ctx(); c.source_mode = mode
    return c


# ------------------------------------------------------------- 우선순위 ----
def test_measured_pair_wins_over_seed():
    w = measured_workcell()
    center, radius, source = _candle_geometry(w)
    assert source == "measured"
    assert center == pytest.approx(w["axis_xy_m"]) and radius == pytest.approx(w["radius_m"])
    assert math.dist(center, w["seed_axis_xy_m"]) == pytest.approx(math.hypot(*SHIFT_XY))


def test_seed_only_falls_back_for_legacy_profiles():
    w = home_workcell()
    assert "axis_xy_m" not in w
    center, radius, source = _candle_geometry(w)
    assert source == "seed"
    assert center == w["seed_axis_xy_m"] and radius == w["seed_radius_m"]


def test_neither_pair_is_rejected_before_any_motion():
    w = home_workcell()
    del w["seed_axis_xy_m"]; del w["seed_radius_m"]
    ad = HomeMock(cut_end_tip(home_workcell()))
    r = return_home(ctx("SIMULATION"), ad, w)
    assert not r.ok and r.error_code == "NOT_READY" and "축·반지름" in r.message
    assert ad.moves == []


# ------------------------------------------------- REAL 은 실측 필수 ----
def test_real_with_measured_geometry_plans_with_measured():
    """REAL + 실측 있음 → measured 사용, 계획 성공, 이동 없음(plan_only)."""
    w = measured_workcell()
    ad = HomeMock(tip_on_measured_surface(w))
    r = return_home(ctx("REAL"), ad, w, plan_only=True)
    assert r.ok, r
    assert r.observed_state["candle_geometry_source"] == "measured"
    assert ad.moves == []


def test_real_without_measured_geometry_is_not_ready():
    """REAL + 실측 없음(seed 만) → NOT_READY, 이동 없음."""
    w = home_workcell()
    ad = HomeMock(cut_end_tip(w))
    r = return_home(ctx("REAL"), ad, w)
    assert not r.ok and r.error_code == "NOT_READY" and "실측" in r.message
    assert ad.moves == []


def test_simulation_without_measured_geometry_uses_seed():
    """SIMULATION + 실측 없음 → seed 폴백 허용 (기존 mock 시험·legacy 프로파일 호환)."""
    w = home_workcell()
    ad = HomeMock(cut_end_tip(w))
    r = return_home(ctx("SIMULATION"), ad, w)
    assert r.ok and r.observed_state["candle_geometry_source"] == "seed"


# ------------------------------------------------------ 복귀 경로에 반영 ----
def test_retreat_target_uses_measured_axis_not_seed():
    """후퇴 목표(반지름 + outer_gap)가 실측 축·반지름 기준으로 잡힌다."""
    w = measured_workcell()
    ad = HomeMock(tip_on_measured_surface(w))
    r = return_home(ctx("SIMULATION"), ad, w)
    assert r.ok, r
    assert r.observed_state["candle_geometry_source"] == "measured"
    assert ad.moves[0][0] == "candle_retract" and ad.moves[1][0] == "candle_travel"
    p_out = ad.moves[1][1]
    d_measured = math.hypot(p_out[0] - w["axis_xy_m"][0], p_out[1] - w["axis_xy_m"][1])
    d_seed = math.hypot(p_out[0] - w["seed_axis_xy_m"][0], p_out[1] - w["seed_axis_xy_m"][1])
    assert d_measured == pytest.approx(w["radius_m"] + w["outer_gap_m"], abs=1e-6)
    assert d_seed != pytest.approx(w["seed_radius_m"] + w["outer_gap_m"], abs=1e-6)   # seed 로 계산한 값이 아니다


def test_already_home_reports_source_too():
    w = measured_workcell()
    ad = HomeMock(apply_tool_offset(w["home"]["tcp_pose"], w["tool_offset_m"], +1))
    r = return_home(ctx("REAL"), ad, w)
    assert r.ok and r.observed_state["moved"] is False
    assert r.observed_state["candle_geometry_source"] == "measured"
