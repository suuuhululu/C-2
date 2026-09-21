"""생성된 ROS 타입의 직렬화·기본값 확인. 노드·네트워크·로봇을 실행하지 않는다."""
import math

import pytest
from builtin_interfaces.msg import Time
from rclpy.serialization import deserialize_message, serialize_message

from c2_interfaces.action import ExecuteProcess, GeneratePath, PrepareWorkpiece
from geometry_msgs.msg import Pose
from c2_interfaces.msg import ProcessEvent, ProcessState
from c2_interfaces.srv import StopProcess


@pytest.mark.parametrize('message', [
    PrepareWorkpiece.Goal(
        operation='MEASURE', request_id='request', preparation_id='prep',
        measurement_id='measurement', source_mode='SIMULATION',
        input_profile_snapshot_id='config', input_profile_sha256='a' * 64,
    ),
    PrepareWorkpiece.Goal(
        operation='BIND_SNAPSHOT', request_id='bind-request', preparation_id='prep',
        measurement_id='measurement', source_mode='SIMULATION',
        input_profile_snapshot_id='config', input_profile_sha256='a' * 64,
        measurement_record_id='record', measurement_record_sha256='b' * 64,
        profile_snapshot_id='profile', profile_sha256='c' * 64,
    ),
    PrepareWorkpiece.Result(
        operation='MEASURE', outcome='FAILED', error_code='CONTACT_OUT_OF_RANGE',
        partial=True, stop_confirmed=True, frame_id='c2_base',
        contact_indices=[0], contact_tip_poses=[Pose()],
        contact_normal_force_n=[1.0], contact_received_at=[Time(sec=100)],
        contact_monotonic_s=[12.5], contact_sources=['SIMULATED'],
        message='부분 결과 보존',
    ),
    PrepareWorkpiece.Result(
        operation='BIND_SNAPSHOT', outcome='SUCCEEDED', error_code='NONE',
        snapshot_bound=True, partial=False, geometry_ready=True, stop_confirmed=True,
        profile_snapshot_id='profile', profile_sha256='c' * 64,
    ),
    PrepareWorkpiece.Feedback(operation='MEASURE', stage='HOME_RECHECK', progress=0.2),
    GeneratePath.Goal(
        request_id='00000000-0000-4000-8000-000000000001', source_mode='SIMULATION',
        asset_id='00000000-0000-4000-8000-000000000002', asset_sha256='a' * 64,
        width_mm=34.0, height_mm=50.0, offset_u_mm=-12.0, offset_v_mm=60.0,
        rotation_deg=30.0, conversion_preset='simulation_centerline', tool_id='test_tool',
        profile_snapshot_id='00000000-0000-4000-8000-000000000003', profile_sha256='b' * 64,
    ),
    GeneratePath.Feedback(request_id='test-request', stage='VALIDATING', progress=0.8),
    GeneratePath.Result(
        success=True, error_code='NONE', path_id='test-path', path_version=2,
        path_sha256='c' * 64, svg_asset_id='test-svg', preview_asset_id='test-preview',
        validation_passed=True, validation_report_id='test-report',
        segment_count=3, cut_length_m=0.12,
    ),
    ExecuteProcess.Goal(
        request_id='test-request', run_id='test-run', source_mode='SIMULATION',
        path_id='test-path', path_version=2, path_sha256='c' * 64,
        operator_confirmed_fixture=True, operator_id='test-operator',
        confirmed_at=Time(sec=1_000_000, nanosec=123456789),
    ),
    ExecuteProcess.Feedback(
        run_id='test-run', phase='ENGRAVE', engraving_progress=0.5,
        completed_segment_id='cut-1', elapsed_s=10.0,
    ),
    ExecuteProcess.Result(
        run_id='test-run', outcome='STOPPED', error_code='NONE',
        last_completed_segment_id='cut-1', log_id='test-log',
    ),
    StopProcess.Request(request_id='stop-request', run_id='test-run', reason='시험 정지'),
    StopProcess.Response(accepted=True, run_id='test-run', stop_state='ACCEPTED', error_code='NONE'),
    ProcessEvent(
        source_mode='SIMULATION', event_id='test-event', source_epoch='test-epoch',
        event_seq=2, occurred_at=Time(sec=1_000_000, nanosec=42), run_id='test-run',
        event_type='ALARM_RAISED', severity='ERROR', code='STOP_UNCONFIRMED',
        message='실제 정지 미확인', path_id='test-path', path_version=2,
        profile_snapshot_id='test-profile', profile_sha256='b' * 64,
    ),
])
def test_wire_roundtrip(message):
    """C 타입 지원을 사용한 직렬화가 한글·ID·구간·시간 정보를 보존해야 한다."""
    assert deserialize_message(serialize_message(message), type(message)) == message


def test_state_measurements_keep_units_frames_and_separate_timestamps():
    state = ProcessState(
        source_mode='SIMULATION', source_epoch='test-epoch', seq=5,
        published_at=Time(sec=101), joints=[0.0, 0.1, -0.2, math.pi, 0.4, -0.5],
        joints_quality='VALID', joints_measured_at=Time(sec=100), tcp_quality='VALID',
        tcp_profile_id='test_tcp', temperature_quality='UNSUPPORTED',
    )
    state.tcp.header.frame_id = 'test_base'
    state.tcp.header.stamp = Time(sec=99, nanosec=123)
    state.tcp.pose.position.x = 0.123
    state.tcp.pose.orientation.w = 1.0
    restored = deserialize_message(serialize_message(state), ProcessState)
    assert restored == state
    assert restored.published_at.sec > restored.joints_measured_at.sec > restored.tcp.header.stamp.sec
    assert restored.tcp.pose.position.x == 0.123
    assert restored.joints[3] == math.pi
    assert not restored.temperature and restored.temperature_quality == 'UNSUPPORTED'


def test_unfilled_messages_do_not_report_success_or_valid_signals():
    for kind in (PrepareWorkpiece.Goal, GeneratePath.Goal, ExecuteProcess.Goal, StopProcess.Request, ProcessState, ProcessEvent):
        assert kind.SCHEMA_VERSION == kind().schema_version == 2
    assert not GeneratePath.Result().success
    assert not GeneratePath.Result().validation_passed
    assert GeneratePath.Result().path_version == 0
    assert not ExecuteProcess.Goal().operator_confirmed_fixture
    assert ExecuteProcess.Result().outcome == 'UNKNOWN'
    assert not StopProcess.Response().accepted
    assert StopProcess.Response().stop_state == 'UNKNOWN'
    state = ProcessState()
    assert state.status == state.stop_state == state.grip_state == 'UNKNOWN'
    for signal in ('joints', 'tcp', 'grip', 'temperature', 'robot'):
        assert getattr(state, f'{signal}_quality') == 'UNKNOWN'
    assert state.source_mode == ''  # 송신자가 의식적으로 모드를 지정한다.


def test_preparation_defaults_and_manual_control_exclusion():
    goal = PrepareWorkpiece.Goal()
    result = PrepareWorkpiece.Result()
    assert goal.operation == goal.source_mode == ''
    assert result.outcome == result.error_code == 'UNKNOWN'
    assert result.partial and not result.geometry_ready
    assert not result.snapshot_bound and not result.stop_confirmed
    assert not result.contact_indices and result.validity == 'INCOMPLETE'
    fields = goal.get_fields_and_field_types()
    assert not any('operator_confirmed' in name or 'drill_on' in name for name in fields)


def test_preparation_complete_contacts_keep_geometry_and_time_bases():
    poses = []
    for index in range(9):
        pose = Pose()
        pose.position.x = index * 0.001
        pose.position.z = 0.15
        pose.orientation.w = 1.0
        poses.append(pose)
    result = PrepareWorkpiece.Result(
        outcome='SUCCEEDED', error_code='NONE', partial=False,
        stop_confirmed=True, geometry_ready=True, validity='SIMULATED',
        frame_id='c2_base', height_m=0.10, radius_m=0.03,
        axis_xy_m=[0.1, -0.2], top_z_m=0.15, bottom_z_m=0.05,
        work_v_range_m=[0.01, 0.09], work_z_range_m=[0.06, 0.14],
        height_source='OPERATOR_RULER', vertical_axis_assumed=True,
        started_at=Time(sec=100), measured_at=Time(sec=120),
        contact_indices=list(range(9)), contact_tip_poses=poses,
        contact_normal_force_n=[1.0] * 9,
        contact_received_at=[Time(sec=101 + i) for i in range(9)],
        contact_monotonic_s=[10.5 + i for i in range(9)],
        contact_sources=['SIMULATED'] * 9,
    )
    restored = deserialize_message(serialize_message(result), PrepareWorkpiece.Result)
    assert restored == result
    assert len(restored.contact_tip_poses) == 9
    assert restored.contact_tip_poses[8].position.x == 0.008
    assert restored.contact_received_at[0].sec == 101
    assert restored.contact_monotonic_s[0] == 10.5
    assert not restored.snapshot_bound  # 측정 완료만으로 등록 완료가 되지 않는다.
