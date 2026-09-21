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


import pytest
from c2_process.joint_check import _unwrap


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), None, "20", True])
@pytest.mark.parametrize("joint", [0, 4, 5])
def test_invalid_ik_result_blocks_following_checks(bad, joint):
    class InvalidIK:
        calls = 0
        def inverse_kinematics(self, pose, offset, ref):
            self.calls += 1
            result = [0.0] * 6
            result[joint] = bad
            return result
    adapter = InvalidIK()
    result = check_path_joints(arc_path(0, 30), adapter, None, REF)
    assert (result.outcome, result.error_code) == ("UNKNOWN", "VALIDATION_UNAVAILABLE")
    assert adapter.calls == 1
    assert result.observed_state == {"segment_id": "s1", "index": 0, "checked_waypoints": 0, "inspection_scope": "SURFACE_PATH"}


@pytest.mark.parametrize("values", [[], [0]*5, [0]*7, "000000", [0, 0, 0, 0, 0, float("nan")]])
def test_invalid_reference_does_not_call_ik(values):
    adapter = MockRobotAdapter()
    adapter.inverse_kinematics = lambda *args: pytest.fail("invalid reference must not reach IK")
    assert check_path_joints(arc_path(0, 30), adapter, None, values).outcome == "UNKNOWN"


@pytest.mark.parametrize("values", [[], [0]*5, [0]*7, 3, "000000"])
def test_invalid_ik_shape(values):
    adapter = MockRobotAdapter()
    adapter.inverse_kinematics = lambda *args: values
    assert check_path_joints(arc_path(0, 30), adapter, None, REF).outcome == "UNKNOWN"


@pytest.mark.parametrize("previous,current,expected", [
    (0, 370, 10), (170, -170, 190), (-170, 170, -190),
    (0, 180, 180), (0, -180, -180), (0, 540, 180), (0, -540, -180),
    (300, 30, 390),
])
def test_unwrap_preserves_direction(previous, current, expected):
    assert _unwrap(previous, current) == expected


def test_unwrap_extreme_values_terminate_in_subprocess():
    # 무한 반복이 재발해도 시험 전체가 멈추지 않도록 별도 프로세스에 제한을 둔다.
    import subprocess
    code = """
from c2_process.joint_check import _unwrap
import math
for value in [float('nan'), float('inf'), -float('inf')]:
    try:
        _unwrap(0, value)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid angle accepted')
assert abs(_unwrap(0, 1e300)) <= 180
assert abs(_unwrap(0, -1e300)) <= 180
try:
    _unwrap(-1e308, 1e308)
except ValueError:
    pass
else:
    raise AssertionError('overflow accepted')
"""
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(__file__)))
    subprocess.run([sys.executable, "-c", code], env=env, check=True, timeout=5)


@pytest.mark.parametrize('bad_index', [1, 2, 3])
@pytest.mark.parametrize('failure', ['ik', 'j5', 'j6'])
def test_cut_previously_skipped_points_are_rejected(bad_index, failure):
    path = arc_path(0, 0, n=6)
    points = path['segments'][0]['waypoints']
    for i, point in enumerate(points): point[0] = .4 + i * .001
    class Adapter:
        def inverse_kinematics(self, pose, offset, ref):
            i = points.index(pose)
            if i == bad_index and failure == 'ik': return None
            return [0, 0, 0, 0, 175 if i == bad_index and failure == 'j5' else 0,
                    355 if i == bad_index and failure == 'j6' else 340]
    result = check_path_joints(path, Adapter(), None, [0, 0, 0, 0, 0, math.radians(340)])
    assert result.outcome == 'FAILED'
    if failure == 'ik':
        assert result.error_code == 'NOT_READY'
        assert result.observed_state['index'] == bad_index
        assert result.observed_state['checked_waypoints'] == bad_index
    else:
        assert result.error_code == 'VALIDATION_FAILED'
        assert result.observed_state['worst']['index'] == bad_index
        assert result.observed_state['worst']['joint'] == (5 if failure == 'j5' else 6)


def test_all_segment_waypoints_are_checked_in_order_with_previous_solution():
    path = {'segments': []}
    for kind, count in [('APPROACH', 2), ('CUT', 6), ('TRAVEL', 2), ('CUT', 3), ('RETRACT', 1)]:
        path['segments'].append({'kind': kind, 'waypoints': [[len(path['segments']), i, 0, 0, 0, 0, 1]
                                                          for i in range(count)]})
    points = [p for s in path['segments'] for p in s['waypoints']]
    class Adapter:
        calls = []
        def inverse_kinematics(self, pose, offset, ref):
            assert ref == [0, 0, 0, 0, 0, len(self.calls)]
            self.calls.append(pose)
            return [0, 0, 0, 0, 0, len(self.calls)]
    adapter = Adapter()
    result = check_path_joints(path, adapter, None, [0]*6)
    assert result.ok and adapter.calls == points
    assert result.observed_state['checked_waypoints'] == len(points)


@pytest.mark.parametrize('kind', ['CUT', 'TRAVEL'])
def test_empty_segment_is_not_silently_skipped(kind):
    adapter = MockRobotAdapter()
    result = check_path_joints({'segments': [{'kind': kind, 'waypoints': []}]}, adapter, None, REF)
    assert (result.outcome, result.error_code) == ('FAILED', 'INVALID_INPUT')
    assert adapter.calls == []


def test_empty_path_does_not_report_zero_point_ik_success():
    adapter = MockRobotAdapter()
    result = check_path_joints({'segments': []}, adapter, None, REF)
    assert (result.outcome, result.error_code) == ('FAILED', 'INVALID_INPUT')
    assert result.observed_state['checked_waypoints'] == 0
    assert adapter.calls == []


def test_joint_checker_still_accepts_non_cut_motion_for_reuse():
    adapter = MockRobotAdapter()
    path = arc_path(0, 5, n=2)
    path['segments'][0]['kind'] = 'TRAVEL'
    result = check_path_joints(path, adapter, None, REF)
    assert result.ok and result.observed_state['checked_waypoints'] == 2
