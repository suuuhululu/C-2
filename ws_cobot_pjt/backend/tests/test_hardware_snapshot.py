"""REAL HMI 읽기 전용 하드웨어 관측 계약 시험."""
import pytest

from app.hardware_snapshot import build_hardware_snapshot


def config(**changes):
    value = {
        'controller_prefix': '/dsr01/dsr_controller2',
        'tcp_id': 'GripperDA_v1',
        'load_id': 'ToolWeight_1',
    }
    value.update(changes)
    return value


def observed(**changes):
    value = {
        'robot_state': 1,
        'robot_mode': 1,
        'robot_system': 0,
        'motion_status': 0,
        'tcp_id': 'GripperDA_v1',
        'load_id': 'ToolWeight_1',
        'joints_deg': [0.] * 6,
        'controller_tcp_posx': [0.] * 6,
    }
    value.update(changes)
    return value


def test_ready_snapshot_contains_only_automatic_observations():
    snapshot = build_hardware_snapshot(config(), observed())
    assert snapshot['state'] == 'READY'
    assert snapshot['errors'] == []
    assert set(snapshot['observation']) == {
        'robot_state', 'robot_mode', 'robot_system', 'motion_status',
        'tcp_id', 'load_id', 'joints_deg', 'controller_tcp_posx'}
    for forbidden in ('speed', 'force', 'fixture', 'gripper_state', 'drill',
                      'execution_profile', 'operator_confirmation'):
        assert forbidden not in snapshot['observation']


@pytest.mark.parametrize('changes', [
    {'robot_mode': 0}, {'robot_system': 1}, {'robot_state': 2},
    {'motion_status': 2}, {'tcp_id': 'wrong'}, {'load_id': 'wrong'},
    {'joints_deg': [0.] * 5}, {'controller_tcp_posx': [float('nan')] * 6},
])
def test_mismatch_is_observed_but_not_defaulted(changes):
    snapshot = build_hardware_snapshot(config(), observed(**changes))
    assert snapshot['state'] == 'NOT_READY'
    assert snapshot['errors']
    for key, value in changes.items():
        if key == 'controller_tcp_posx':
            assert len(snapshot['observation'][key]) == 6
        else:
            assert snapshot['observation'][key] == value


@pytest.mark.parametrize('changes', [
    {'tcp_id': 'other'}, {'load_id': 'other'}, {'controller_prefix': 'relative'},
])
def test_fixed_real_configuration_is_required(changes):
    with pytest.raises(ValueError, match='TCP/load|prefix'):
        build_hardware_snapshot(config(**changes), observed())


def test_connection_error_does_not_invent_values():
    snapshot = build_hardware_snapshot(config(), error='service unavailable')
    assert snapshot['state'] == 'UNAVAILABLE'
    assert snapshot['observation'] is None
    assert snapshot['errors'] == ['service unavailable']
