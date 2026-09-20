# 전체 경로 IK·J6 검사 모의 시험
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from c2_process.robot_adapter import MockRobotAdapter, matrix_to_quat  # noqa: E402
from c2_process.joint_check import check_path_joints  # noqa: E402


def upright(yaw_deg):
    """툴 Z 아래, 툴 Y 가 base yaw 방향"""
    t = math.radians(yaw_deg)
    x = [-math.cos(t), -math.sin(t), 0.0]; y = [-math.sin(t), math.cos(t), 0.0]; z = [0.0, 0.0, -1.0]
    return matrix_to_quat([[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]])


def arc_path(yaw_from, yaw_to, n=40):
    wps = [[0.4, 0.0, 0.2, *upright(yaw_from + (yaw_to - yaw_from) * i / (n - 1))] for i in range(n)]
    return dict(schema_version=2, segments=[dict(segment_id="s1", stroke_id="st1", kind="CUT", waypoints=wps, motion_profile_id="cut")])


REF = [0.0, 0.0, math.radians(90), 0.0, math.radians(90), 0.0]


def test_pass_within_limits():
    ad = MockRobotAdapter()
    r = check_path_joints(arc_path(90, -60), ad, None, REF)
    assert r.ok, r
    assert r.observed_state["j6_total_rotation_deg"] > 100 and r.observed_state["checked_waypoints"] >= 10


def test_fail_when_j6_exceeds_margin():
    ad = MockRobotAdapter(); ad.ik_j6_offset = 300.0                  # 시작 J6 가 이미 300° 근처
    ref = list(REF); ref[5] = math.radians(300.0)                      # 현재 J6 = 300 → 첫 점은 가까운 해(390)로 이어짐
    r = check_path_joints(arc_path(90, 160), ad, None, ref)          # +70° 더 돌면 370 > 350
    assert r.outcome == "FAILED" and r.error_code == "VALIDATION_FAILED", r
    assert r.observed_state["worst"]["joint"] == 6


def test_unwrap_keeps_continuity_across_180():
    ad = MockRobotAdapter()
    ref = list(REF); ref[5] = math.radians(-100.0)                     # 모의 IK: J6 = yaw+90 → 170° 에서 -100
    r = check_path_joints(arc_path(170, 190), ad, None, ref)          # atan2 가 ±180 에서 접히는 구간
    assert r.ok and r.observed_state["j6_total_rotation_deg"] < 25, r


def test_ik_failure_reported():
    ad = MockRobotAdapter(); ad.ik_fail_at_call = 3
    r = check_path_joints(arc_path(0, 30), ad, None, REF)
    assert r.outcome == "FAILED" and r.error_code == "NOT_READY" and "IK" in r.message
