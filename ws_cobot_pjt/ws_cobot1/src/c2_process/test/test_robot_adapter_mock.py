# robot_adapter 모의 시험 (로봇·ROS 없음). 실행: python3 test/test_robot_adapter_mock.py
# 사례: 단위 왕복 변환, 툴 오프셋 환산(v1 홈 + 60 mm = 9/17 v3 홈), 이동 중 취소 → STOPPED, 프로파일 선택 결과, 접촉 모의.
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from c2_process.robot_adapter import MockRobotAdapter, pose_to_posx, posx_to_pose, tool_axis_in_base  # noqa: E402

PROFILE = dict(id="travel", vel_mm_s=26.0, acc_mm_s2=50.0, completion_timeout_s=30.0)


def test_unit_roundtrip():
    for px in ([384.1, 7.6, 105.4, 90.3, 88.6, 90.9], [400.0, -20.0, 150.0, 45.0, 133.6, -30.0], [367.3, 3.6, 215.8, -0.1, 179.8, 0.3]):
        back = pose_to_posx(posx_to_pose(px))
        assert all(abs(a - b) < 1e-3 for a, b in zip(back[:3], px[:3])), px
        assert all(abs(((a - b + 180) % 360) - 180) < 1e-3 for a, b in zip(back[3:], px[3:])), px


def test_tool_offset_matches_v3_home():
    """GripperDA_v1(패드) 로 읽은 홈 + 툴 -Y 60 mm 오프셋 = 9/17 GripperDA_v3 로 읽던 홈 (384.1, 7.6, 105.4)"""
    tip = posx_to_pose([385.0, 6.1, 165.4, 90.35, 88.61, 90.87], [0.0, -0.060, 0.0])
    assert abs(tip[0] * 1000 - 384.1) < 0.3 and abs(tip[1] * 1000 - 7.6) < 0.3 and abs(tip[2] * 1000 - 105.4) < 0.3, tip
    back = pose_to_posx(tip, [0.0, -0.060, 0.0])
    assert abs(back[2] - 165.4) < 1e-3


def test_tool_axis():
    p = posx_to_pose([384.1, 7.6, 105.4, 90.3, 88.6, 90.9])          # 9/17 홈: 툴 -Y 가 아래
    d = tool_axis_in_base(p, "-y")
    assert d[2] < -0.99, d


def test_cancel_during_motion():
    ad = MockRobotAdapter(move_time_s=0.3)
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    r = ad.move([0.4, 0.0, 0.3, 0, 1, 0, 0], "dsr01_base", PROFILE, 30.0, cancel)
    assert r.outcome == "STOPPED" and ad.stopped and "대기 중" in r.message, r
    assert 0.0 < ad.pose[2] < 0.3                                       # 도중에 섰다


def test_select_tool_profile():
    ad = MockRobotAdapter()
    r = ad.select_tool_profile("GripperDA_v1", "ToolWeight_1", profile_version=1)
    assert r.ok and r.observed_state == dict(tcp="GripperDA_v1", tool="ToolWeight_1", profile_version=1, applied=True)


def test_probe_touch_mock():
    ad = MockRobotAdapter(surface_fn=lambda pose, d: 0.012)
    r = ad.probe_touch([0, 0, -1], 0.06, dict(touch_force_n=1.0, touch_speed_mm_s=4.0), 60.0, None)
    assert r.ok and r.observed_state["contact"] and abs(r.observed_state["travelled_m"] - 0.012) < 1e-9
    ad2 = MockRobotAdapter(surface_fn=lambda pose, d: None)
    r2 = ad2.probe_touch([0, 0, -1], 0.06, dict(touch_force_n=1.0, touch_speed_mm_s=4.0), 60.0, None)
    assert r2.outcome == "FAILED" and not r2.observed_state["contact"]


def test_spline_point_limit():
    ad = MockRobotAdapter()
    r = ad.move_spline([[0.4, 0, 0.3, 0, 1, 0, 0]] * 81, "dsr01_base", PROFILE, 30.0, None)
    assert r.outcome == "FAILED" and r.error_code == "INVALID_INPUT"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
