"""실제 HMI 조립 → 공정 매퍼·모의 실행 연결. 입력은 합성 시험값, 실물 모션 없음."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'ws_cobot1/src/c2_path'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ros_preparation import real_bound_profile, display_result
from c2_path.pipeline import matching_test_profile_v4
from c2_process.engraving import execute_path
from c2_process.node import create_ros_node, resolve_real_execution_settings
from c2_process.robot_adapter import MockRobotAdapter, StepResult


def inputs():
    package = Path(__file__).resolve().parents[1]
    config = json.loads((package / 'config/workpiece_real_trial_0921.json').read_text())
    template = matching_test_profile_v4()
    template['tip_calibration']['offset_tool_m'] = copy.deepcopy(config['workcell']['tool_offset_m'])
    template['execution_context']['stop_profile']['confirmation_timeout_s'] = 1.
    for name, motion in template['execution_context']['motion_profiles'].items():
        motion.update(id=name, vel_mm_s=1., acc_mm_s2=1., pos_tol_mm=1.,
                      completion_timeout_s=1.)
    template['execution_context']['entry_planning'] = {
        'enabled': True,
        'tcp_clearance_above_top_range_m': [.10, .12],
        'tcp_z_step_m': .01,
        'sample_m': .005,
        'sample_deg': 2.,
        'min_radial_gap_m': .005,
        'min_j3_abs_deg': 10.,
        'min_j5_margin_deg': 15.,
        'max_joint_step_deg': 20.,
        'start_position_tolerance_m': .001,
        'start_angle_tolerance_deg': 1.,
        'motion_profile_id': 'candle_travel',
    }
    template['execution_context']['tool_profile'].update(
        contact_mode='fixed_depth', depth_m=.001, clearance_m=.001)
    config['execution_profile'] = template
    fixture = json.loads((package / 'test/fixtures/prepare_workpiece_action_samples/success.json').read_text())
    goal = dict(fixture['goal'], source_mode='REAL', height_m=.15)
    # REAL 분기의 수치/계약 시험용 합성 입력. 실제 측정/실기 통과 근거가 아니다.
    raw = dict(fixture['result'], source_mode='REAL', validity='ESTIMATED', absolute_top_verified=False)
    display = display_result(raw, goal)
    record = {'id': '55555555-5555-4555-8555-555555555555', 'sha256': 'b' * 64}
    return config, goal, display, record


class ProfileRecorder(MockRobotAdapter):
    """구간 실행 경계에서 공정이 넘긴 프로파일 전체와 완료 기한을 기록한다."""

    def __init__(self):
        super().__init__()
        self.received_profiles = []

    def _remember(self, operation, profile, deadline_s):
        self.received_profiles.append(
            (operation, profile['id'], copy.deepcopy(profile), deadline_s))

    def move(self, pose, frame_id, profile, deadline_s, cancel):
        self._remember('move', profile, deadline_s)
        return super().move(pose, frame_id, profile, deadline_s, cancel)

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel):
        self._remember('move_spline', profile, deadline_s)
        return super().move_spline(poses, frame_id, profile, deadline_s, cancel)


class FailureRecorder(ProfileRecorder):
    """지정한 실행 경계 한 곳에서만 실패하고 이후 호출 여부를 기록한다."""

    def __init__(self, operation, profile_id, result):
        super().__init__()
        self.failure = (operation, profile_id, result)

    def _failure(self, operation, profile):
        expected_operation, expected_profile, result = self.failure
        return result if (operation, profile['id']) == (expected_operation, expected_profile) else None

    def move(self, pose, frame_id, profile, deadline_s, cancel):
        self._remember('move', profile, deadline_s)
        failed = self._failure('move', profile)
        if failed is not None:
            return failed
        return MockRobotAdapter.move(self, pose, frame_id, profile, deadline_s, cancel)

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel):
        self._remember('move_spline', profile, deadline_s)
        failed = self._failure('move_spline', profile)
        if failed is not None:
            return failed
        return MockRobotAdapter.move_spline(self, poses, frame_id, profile, deadline_s, cancel)


def four_segment_real_path():
    def pose(x, y, z):
        return [x, y, z, 0., 0., 0., 1.]

    return {
        'schema_version': 2,
        'source_mode': 'REAL',
        'frame_id': 'c2_base',
        'position_unit': 'm',
        'orientation': 'quaternion_xyzw',
        'tool_id': 'engraving_drill',
        'segments': [
            {'segment_id': 'approach', 'stroke_id': 'stroke-1', 'kind': 'APPROACH',
             'motion_profile_id': 'candle_approach',
             'waypoints': [pose(.40, -.01, .20)]},
            {'segment_id': 'cut', 'stroke_id': 'stroke-1', 'kind': 'CUT',
             'motion_profile_id': 'candle_cut',
             'waypoints': [pose(.40, 0., .20), pose(.401, 0., .20), pose(.402, 0., .20)]},
            {'segment_id': 'travel', 'stroke_id': 'stroke-2', 'kind': 'TRAVEL',
             'motion_profile_id': 'candle_travel',
             'waypoints': [pose(.403, -.01, .20)]},
            {'segment_id': 'retract', 'stroke_id': 'stroke-2', 'kind': 'RETRACT',
             'motion_profile_id': 'candle_retract',
             'waypoints': [pose(.403, -.02, .20)]},
        ],
    }


def test_measurement_offset_reaches_execution_unchanged():
    config, goal, display, record = inputs()
    profile = real_bound_profile(goal, display, config, record)
    adapter = MockRobotAdapter()
    settings = resolve_real_execution_settings(profile, {'run_id': 'run', 'source_mode': 'REAL'},
                                                'registered-profile', adapter=adapter)
    assert settings['tool_offset_m'] == config['workcell']['tool_offset_m']
    assert settings['tool_offset_m'] == profile['tip_calibration']['offset_tool_m']
    assert settings['tool_offset_m'] != profile['contact_calibration']['contact_offset_tool_m']
    assert profile['absolute_top_verified'] is False and profile['validity'] == 'ESTIMATED'
    assert not adapter.calls


def test_hmi_real_profile_reaches_each_execution_segment_unchanged():
    config, goal, display, record = inputs()
    snapshot = real_bound_profile(goal, display, config, record)
    adapter = ProfileRecorder()
    settings = resolve_real_execution_settings(
        snapshot, {'run_id': 'run', 'source_mode': 'REAL'},
        'registered-profile', adapter=adapter)
    context = settings['context']
    expected = snapshot['execution_context']

    assert context.motion_profiles == expected['motion_profiles']
    assert context.tool_profile == expected['tool_profile']
    assert context.stop_profile == expected['stop_profile']
    assert context.joint_limits_deg == snapshot['joint_check_arguments']['limits_deg']
    assert context.j6_margin_deg == snapshot['joint_check_arguments']['j6_margin_deg'] == 0.
    assert context.joint_limits_deg[5] == [-170., 170.]
    assert settings['tool_offset_m'] == snapshot['tip_calibration']['offset_tool_m']
    assert settings['tool_offset_m'] == config['workcell']['tool_offset_m']

    result = execute_path(four_segment_real_path(), context, adapter=adapter)

    assert result.ok
    received_ids = [item[1] for item in adapter.received_profiles]
    assert set(received_ids) == {
        'candle_approach', 'candle_cut', 'candle_travel', 'candle_retract'}
    assert received_ids[0] == 'candle_approach'
    assert received_ids[-2:] == ['candle_travel', 'candle_retract']
    assert all(item[1] == 'candle_cut' for item in adapter.received_profiles[1:-2])
    for _, profile_id, received, deadline_s in adapter.received_profiles:
        assert received == expected['motion_profiles'][profile_id]
        assert received['vel_mm_s'] == 1.
        assert received['acc_mm_s2'] == 1.
        assert received['pos_tol_mm'] == 1.
        assert deadline_s == received['completion_timeout_s'] == 1.


@pytest.mark.parametrize(
    'operation,failed_profile,failure,expected_outcome,expected_code,completed,received_ids', [
        ('move', 'candle_approach', StepResult('FAILED', 'NOT_READY', '접근 실패'),
         'FAILED', 'NOT_READY', '', ['candle_approach']),
        ('move_spline', 'candle_cut',
         StepResult('UNKNOWN', 'STOP_UNCONFIRMED', 'CUT 상태 불명',
                    observed_state={'stop_confirmed': False}),
         'UNKNOWN', 'STOP_UNCONFIRMED', 'approach',
         ['candle_approach', 'candle_cut', 'candle_cut']),
        ('move', 'candle_retract', StepResult('FAILED', 'NOT_READY', '이탈 실패'),
         'FAILED', 'NOT_READY', 'travel',
         ['candle_approach', 'candle_cut', 'candle_cut',
          'candle_travel', 'candle_retract']),
    ])
def test_real_failure_stops_after_confirmed_segment(
        operation, failed_profile, failure, expected_outcome, expected_code,
        completed, received_ids):
    config, goal, display, record = inputs()
    snapshot = real_bound_profile(goal, display, config, record)
    adapter = FailureRecorder(operation, failed_profile, failure)
    settings = resolve_real_execution_settings(
        snapshot, {'run_id': 'run', 'source_mode': 'REAL'},
        'registered-profile', adapter=adapter)

    result = execute_path(four_segment_real_path(), settings['context'], adapter=adapter)

    assert (result.outcome, result.error_code) == (expected_outcome, expected_code)
    assert result.outcome != 'SUCCEEDED'
    assert result.observed_state['last_completed_segment_id'] == completed
    assert [item[1] for item in adapter.received_profiles] == received_ids
    assert failed_profile in result.message or failure.message in result.message


@pytest.mark.parametrize('result,cancel_requested,terminal', [
    (StepResult('FAILED', 'NOT_READY', 'APPROACH approach: 접근 실패',
                observed_state={'last_completed_segment_id': ''}), False, 'abort'),
    (StepResult('UNKNOWN', 'STOP_UNCONFIRMED', 'CUT cut: 상태 불명',
                observed_state={'last_completed_segment_id': 'approach'}), False, 'abort'),
    (StepResult('FAILED', 'NOT_READY', 'RETRACT retract: 이탈 실패',
                observed_state={'last_completed_segment_id': 'travel'}), False, 'abort'),
    (StepResult('STOPPED', 'NONE', '정지 확인 완료',
                observed_state={'last_completed_segment_id': 'cut'}), True, 'canceled'),
])
def test_execute_result_preserves_failure_for_hmi(
        monkeypatch, result, cancel_requested, terminal):
    class Packet:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class State(Packet):
        def __init__(self):
            self.tcp = NS(header=NS(), pose=NS(position=NS(), orientation=NS()))

    class Publisher:
        def __init__(self):
            self.sent = []

        def publish(self, message):
            self.sent.append(message)

    class Node:
        def __init__(self, *_args):
            pass

        def create_publisher(self, *_args):
            return Publisher()

        def create_service(self, *_args, **_kwargs):
            return None

        def create_timer(self, *_args, **_kwargs):
            return None

        def get_logger(self):
            return NS(warn=lambda _message: None)

    monkeypatch.setitem(sys.modules, 'rclpy.action', NS(
        ActionServer=lambda *_args, **_kwargs: None,
        CancelResponse=NS(ACCEPT=1, REJECT=0), GoalResponse=NS(ACCEPT=1, REJECT=0)))
    monkeypatch.setitem(sys.modules, 'rclpy.callback_groups', NS(ReentrantCallbackGroup=lambda: None))
    monkeypatch.setitem(sys.modules, 'rclpy.node', NS(Node=Node))
    monkeypatch.setitem(sys.modules, 'rclpy.qos', NS(
        QoSProfile=Packet, ReliabilityPolicy=NS(RELIABLE=1),
        DurabilityPolicy=NS(VOLATILE=1)))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.action', NS(
        ExecuteProcess=NS(Feedback=Packet, Result=Packet),
        PrepareWorkpiece=NS(Feedback=Packet, Result=Packet)))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.msg', NS(
        ProcessEvent=Packet, ProcessState=State))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.srv', NS(StopProcess=Packet))
    monkeypatch.setitem(sys.modules, 'builtin_interfaces.msg', NS(Time=Packet))
    monkeypatch.setitem(sys.modules, 'rosidl_runtime_py.set_message', NS(
        set_message_fields=lambda *_args: None))

    node = create_ros_node(enable_preparation=False)
    node.coordinator.execute = lambda *_args, **_kwargs: copy.deepcopy(result)
    calls = []
    request = NS(schema_version=2, request_id='request', run_id='run', source_mode='SIMULATION',
                 path_id='path', path_version=1, path_sha256='a' * 64)
    handle = NS(
        request=request, is_cancel_requested=cancel_requested,
        publish_feedback=lambda _packet: None,
        succeed=lambda: calls.append('succeed'), abort=lambda: calls.append('abort'),
        canceled=lambda: calls.append('canceled'))

    output = node.execute_goal(handle)

    assert output.run_id == 'run'
    assert output.outcome == result.outcome
    assert output.error_code == result.error_code
    assert output.message == result.message
    assert output.last_completed_segment_id == result.observed_state['last_completed_segment_id']
    assert calls == [terminal]


@pytest.mark.parametrize('mismatch', [[0., -.09, 0.], [0., 0., .02], None])
def test_hmi_rejects_mismatched_or_missing_drill_offset_before_execution(mismatch):
    config, goal, display, record = inputs()
    config['execution_profile']['tip_calibration']['offset_tool_m'] = mismatch
    with pytest.raises(ValueError, match='측정/가공 도구 끝 오프셋 불일치'):
        real_bound_profile(goal, display, config, record)
