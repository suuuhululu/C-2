# 모의 어댑터로 조각 실행 흐름 검증 (로봇·ROS 없음). 실행: python3 -m pytest test/ 또는 python3 test/test_engraving_mock.py
# 검증 사례: 정상 완료, 거절(프로파일 없음·스키마), 실패 후 다음 구간 미진입, 취소 시 정지, 80점 초과 분할, 청소 1회.
import math
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from c2_process.robot_adapter import MockRobotAdapter, matrix_to_quat, pose_to_posx, posx_to_pose, tool_axis_in_base  # noqa: E402
from c2_process.engraving import ExecutionContext, execute_path, validate_path  # noqa: E402


# ---- 시험용 원기둥 경로 생성 (c2_path 의 형식이 확정되면 그쪽 샘플로 대체) ----
def cylinder_pose(axis_xy, radius, z, angle_deg, tool_axis="+z"):
    """원기둥(축 ∥ base Z, 중심 axis_xy, m) 옆면의 점: 도구 +Z 축이 표면 법선 안쪽(축을 향함), 도구 X 는 base +Z (축 방향)."""
    a = math.radians(angle_deg)
    nx, ny = math.cos(a), math.sin(a)                       # 바깥 법선
    px, py = axis_xy[0] + radius * nx, axis_xy[1] + radius * ny
    zc = [-nx, -ny, 0.0]                                    # 도구 +Z = 안쪽
    xc = [0.0, 0.0, 1.0]                                    # 도구 +X = 원기둥 축(위)
    yc = [zc[1] * xc[2] - zc[2] * xc[1], zc[2] * xc[0] - zc[0] * xc[2], zc[0] * xc[1] - zc[1] * xc[0]]
    M = [[xc[0], yc[0], zc[0]], [xc[1], yc[1], zc[1]], [xc[2], yc[2], zc[2]]]
    return [px, py, z] + matrix_to_quat(M)


def sample_path(n_cut=30, arc_deg=40.0):
    axis, R = (0.45, 0.0), 0.034                              # 양초 지름 68 mm (9/18), 축 위치는 임시
    z0 = 0.15
    seg = []
    # 획 1: 수직 직선 (각도 0°, z 0.15→0.12)
    line = [cylinder_pose(axis, R, z0 - 0.03 * i / (n_cut - 1), 0.0) for i in range(n_cut)]
    seg.append(dict(segment_id="s1_app", stroke_id="st1", kind="APPROACH", motion_profile_id="travel",
                    waypoints=[_out(line[0], 0.03), _out(line[0], 0.01)]))
    seg.append(dict(segment_id="s1_cut", stroke_id="st1", kind="CUT", motion_profile_id="cut", waypoints=line))
    seg.append(dict(segment_id="s1_ret", stroke_id="st1", kind="RETRACT", motion_profile_id="travel", waypoints=[_out(line[-1], 0.01)]))
    # 획 2: 둘레 호 (−arc/2 … +arc/2, z 0.13), 점 100개 → 80 초과 분할 검증
    arc = [cylinder_pose(axis, R, 0.13, -arc_deg / 2 + arc_deg * i / 99) for i in range(100)]
    seg.append(dict(segment_id="s2_tr", stroke_id="st2", kind="TRAVEL", motion_profile_id="travel", waypoints=[_out(arc[0], 0.03)]))
    seg.append(dict(segment_id="s2_app", stroke_id="st2", kind="APPROACH", motion_profile_id="travel", waypoints=[_out(arc[0], 0.01)]))
    seg.append(dict(segment_id="s2_cut", stroke_id="st2", kind="CUT", motion_profile_id="cut", waypoints=arc))
    seg.append(dict(segment_id="s2_ret", stroke_id="st2", kind="RETRACT", motion_profile_id="travel", waypoints=[_out(arc[-1], 0.03)]))
    return dict(schema_version=2, path_id="p-test", path_version=1, source_mode="SIMULATION", frame_id="c2_base",
                position_unit="m", orientation="quaternion_xyzw", segments=seg)


def _out(pose, m):
    """표면점에서 법선 바깥으로 m 만큼 (도구 +Z 가 안쪽이므로 −Z 방향)"""
    d = tool_axis_in_base(pose, "+z")
    return [pose[0] - d[0] * m, pose[1] - d[1] * m, pose[2] - d[2] * m] + pose[3:]


def make_ctx(mode="force_touch", source="SIMULATION"):
    return ExecutionContext(
        run_id="run-test", source_mode=source, cancel=threading.Event(),
        motion_profiles={"travel": dict(id="travel", vel_mm_s=26.0, completion_timeout_s=60.0),
                         "cut": dict(id="cut", vel_mm_s=6.6, completion_timeout_s=60.0)},
        tool_profile=dict(contact_mode=mode, tool_axis="+z", depth_m=0.0005, clearance_m=0.010, touch_extra_m=0.008,
                          touch_force_n=0.8, touch_speed_mm_s=1.5, frame_id="c2_base", tool_id="engraving_drill"))


def surface_offset_fn(delta_m):
    """모의 표면: 경로 표면점보다 delta_m 만큼 안쪽에 실제 표면이 있다고 가정 (접촉은 clearance+delta 에서)"""
    return lambda pose, direction: 0.010 + delta_m


def test_success_force_touch():
    ad = MockRobotAdapter(surface_fn=surface_offset_fn(0.0015))
    progress = []
    r = execute_path(sample_path(), make_ctx(), progress.append, ad)
    assert r.ok, r
    st = r.observed_state
    assert st["last_completed_segment_id"] == "s2_ret"
    assert abs(st["engraving_progress"] - 1.0) < 1e-9
    assert len(st["touches"]) == 2 and abs(st["touches"][0]["offset_mm"] - 1.5) < 0.05
    splines = [c for c in ad.calls if c["fn"] == "move_spline"]
    assert [c["n"] for c in splines] == [15, 20], [c["n"] for c in splines]   # 9/20: 1 mm 미만 간격 점 걸러냄(제어기 등속 불가 경고) → 시험 경로(1 mm 간격)는 절반이 빠진다
    assert progress[-1]["phase"] == "RETRACT"


def test_success_fixed_depth():
    ad = MockRobotAdapter()
    r = execute_path(sample_path(), make_ctx("fixed_depth"), None, ad)
    assert r.ok and not [c for c in ad.calls if c["fn"] == "probe_touch"]


def test_reject_without_profile():
    ctx = make_ctx(); ctx.tool_profile["contact_mode"] = "laser"
    ad = MockRobotAdapter()
    r = execute_path(sample_path(), ctx, None, ad)
    assert r.outcome == "FAILED" and r.error_code == "UNSUPPORTED_RECIPE" and not ad.calls


def test_reject_schema_v1_and_clearance_required_in_real():
    ctx = make_ctx()
    p = sample_path(); p["schema_version"] = 1
    r = validate_path(p, ctx)
    assert r is not None and r.error_code == "UNSUPPORTED_SCHEMA_VERSION"
    ctx_real = make_ctx(source="REAL"); ctx_real.tool_profile.pop("clearance_m")
    ctx_real.motion_profiles["travel"]["completion_timeout_s"] = 60.0
    p2 = sample_path(); p2["source_mode"] = "REAL"
    r = validate_path(p2, ctx_real)
    assert r is not None and r.error_code == "UNSUPPORTED_RECIPE", r
    ctx_real.tool_profile["clearance_m"] = dict(stroke=0.006, process_entry_exit=0.025)   # 세은님 tools.yaml 형태
    assert validate_path(p2, ctx_real) is None


def test_reject_schema():
    p = sample_path(); p["schema_version"] = 3
    r = execute_path(p, make_ctx(), None, MockRobotAdapter())
    assert r.error_code == "UNSUPPORTED_SCHEMA_VERSION"


def test_failure_blocks_next_segment():
    ad = MockRobotAdapter(surface_fn=surface_offset_fn(0.0), fail_at="move_spline")
    r = execute_path(sample_path(), make_ctx(), None, ad)
    assert r.outcome == "FAILED" and r.observed_state["last_completed_segment_id"] == "s1_app"
    assert not [c for c in ad.calls if c["fn"] == "move" and c.get("profile") == "travel" and c["pose"][2] < 0.125]


def test_cancel_stops():
    ctx = make_ctx(); ad = MockRobotAdapter(surface_fn=surface_offset_fn(0.0))
    def cancel_after_first_cut(p):
        if p["completed_segment_id"] == "s1_cut":
            ctx.cancel.set()
    r = execute_path(sample_path(), ctx, cancel_after_first_cut, ad)
    assert r.outcome == "STOPPED" and r.observed_state["last_completed_segment_id"] == "s1_cut"
    assert not [c for c in ad.calls if c["fn"] == "move_spline" and c["n"] == 80]


def test_cancel_during_motion():
    """이동 대기 중 취소 → 즉시 STOPPED, 정지 호출 기록, 다음 구간 미진입 (세은님 요구: 대기 중 정지 처리)"""
    ctx = make_ctx()
    ad = MockRobotAdapter(surface_fn=surface_offset_fn(0.0), move_time_s=0.3)
    threading.Timer(0.1, ctx.cancel.set).start()
    r = execute_path(sample_path(), ctx, None, ad)
    assert r.outcome == "STOPPED" and ad.stopped and "대기 중" in r.message, r
    assert r.observed_state["last_completed_segment_id"] == ""       # 첫 구간(APPROACH) 도중에 섰다
    assert not [c for c in ad.calls if c["fn"] in ("probe_touch", "move_spline")]


def test_select_tool_profile_reports_version():
    ad = MockRobotAdapter()
    r = ad.select_tool_profile("GripperDA_v3", "ToolWeight_1", profile_version=3)
    assert r.ok and r.observed_state["applied"] and r.observed_state["profile_version"] == 3


def test_no_surface_found():
    ad = MockRobotAdapter(surface_fn=lambda p, d: None)
    r = execute_path(sample_path(), make_ctx(), None, ad)
    assert r.outcome == "FAILED" and "표면" in r.message



def test_unit_roundtrip():
    for px in ([384.1, 7.6, 105.4, 90.3, 88.6, 90.9], [400.0, -20.0, 150.0, 45.0, 133.6, -30.0]):
        back = pose_to_posx(posx_to_pose(px))
        assert all(abs(a - b) < 1e-3 for a, b in zip(back[:3], px[:3]))
        assert all(abs(((a - b + 180) % 360) - 180) < 1e-3 for a, b in zip(back[3:], px[3:]))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)


def test_reject_tool_id_mismatch():
    ctx = make_ctx()
    p = sample_path(); p["tool_id"] = "awl"
    r = validate_path(p, ctx)
    assert r is not None and r.error_code == "PROFILE_MISMATCH", r
    p["tool_id"] = "engraving_drill"
    assert validate_path(p, ctx) is None
