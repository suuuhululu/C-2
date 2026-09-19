"""Jazzy + 생성된 c2_interfaces가 있는 환경에서 게이트웨이 타입 경계를 검사한다."""
import json
import math

import pytest

pytest.importorskip('c2_interfaces.action', reason='c2_interfaces 빌드·source 후 실행')
from builtin_interfaces.msg import Time
from c2_interfaces.action import ExecuteProcess, GeneratePath
from c2_interfaces.msg import ProcessEvent, ProcessState
from c2_interfaces.srv import StopProcess

from app.ros_bridge import check_installed_contract, fill_message, ros_message_values, ros_time_from_iso


def test_installed_v1_types_are_rejected_before_gateway_start():
    check_installed_contract((GeneratePath.Goal, ExecuteProcess.Goal, StopProcess.Request, ProcessState, ProcessEvent))
    class OldGoal:
        SCHEMA_VERSION = 1
    with pytest.raises(RuntimeError, match='v2'):
        check_installed_contract((OldGoal,))


def test_generate_and_stop_fields_match_monitor_payloads():
    payload = dict(
        schema_version=2, request_id='request', source_mode='SIMULATION', asset_id='asset',
        asset_sha256='a' * 64, width_mm=40.0, height_mm=50.0, offset_u_mm=0.0,
        offset_v_mm=60.0, rotation_deg=0.0, conversion_preset='simulation_centerline',
        tool_id='test-tool', profile_snapshot_id='profile', profile_sha256='b' * 64,
    )
    assert ros_message_values(fill_message(GeneratePath.Goal(), payload)) == payload
    stop = dict(schema_version=2, request_id='stop', run_id='run', reason='운영자 정지 요청')
    assert ros_message_values(fill_message(StopProcess.Request(), stop)) == stop
    with pytest.raises(ValueError, match='필드 불일치'):
        fill_message(GeneratePath.Goal(), {'unagreed_field': True})


def test_execution_confirmation_time_converts_without_unit_or_timezone_loss():
    payload = dict(
        schema_version=2, request_id='request', run_id='run', source_mode='SIMULATION',
        path_id='path', path_version=1, path_sha256='c' * 64,
        operator_confirmed_fixture=True, operator_id='local-operator',
        confirmed_at='2026-09-19T14:00:00.123456789+09:00',
    )
    goal = fill_message(ExecuteProcess.Goal(), payload)
    assert isinstance(goal.confirmed_at, Time)
    assert goal.confirmed_at.nanosec == 123456789
    assert ros_message_values(goal)['confirmed_at'] == '2026-09-19T05:00:00.123456789Z'


@pytest.mark.parametrize('timestamp', ['2026-09-19T14:00:00', 'invalid', '2026-09-19'])
def test_confirmation_rejects_missing_timezone(timestamp):
    with pytest.raises(ValueError):
        ros_time_from_iso(timestamp)


def test_process_event_time_is_json_text_for_database_storage():
    event = ProcessEvent(occurred_at=ros_time_from_iso('2026-09-19T05:00:00Z'))
    assert ros_message_values(event)['occurred_at'] == '2026-09-19T05:00:00.000000000Z'
    json.dumps(ros_message_values(event), allow_nan=False)


def test_unknown_or_stale_measurements_are_not_zero_or_fresh_values():
    state = ProcessState(
        published_at=Time(sec=100), joints=[0.1] * 6, joints_quality='STALE',
        joints_measured_at=Time(sec=10), grip_state='GRIPPED', grip_quality='UNKNOWN',
        temperature=[0.0] * 6, temperature_quality='UNSUPPORTED',
        robot_connection_state='CONNECTED', robot_quality='UNKNOWN',
    )
    result = ros_message_values(state)
    assert result['joints'] is result['tcp'] is result['temperature'] is None
    assert result['grip_state'] == result['robot_connection_state'] == 'UNKNOWN'
    assert result['joints_measured_at'] == '1970-01-01T00:00:10.000000000Z'
    assert result['published_at'] == '1970-01-01T00:01:40.000000000Z'
    assert result['grip_measured_at'] is None
    json.dumps(result, allow_nan=False)


def test_valid_pose_retains_frame_stamp_and_nonfinite_values_become_null():
    state = ProcessState(joints=[0.0, math.nan, 0.0, 0.0, 0.0, 0.0], joints_quality='VALID', tcp_quality='VALID')
    state.tcp.header.frame_id = 'test_base'
    state.tcp.header.stamp = Time(sec=99, nanosec=4)
    state.tcp.pose.position.x = 0.25
    state.tcp.pose.orientation.w = 1.0
    result = ros_message_values(state)
    assert result['tcp']['header']['frame_id'] == 'test_base'
    assert result['tcp']['header']['stamp'] == '1970-01-01T00:01:39.000000004Z'
    assert result['tcp']['pose']['position']['x'] == 0.25
    assert result['joints'][1] is None
    json.dumps(result, allow_nan=False)
