import json

import pytest

from app.assembly_step_bridge import read
from app.jsonl_log import JsonlLog
from scripts import assembly_held_trial as cli


def forbidden_driver(_):
    raise AssertionError('DEVICE_CONNECTION_FORBIDDEN')


@pytest.mark.parametrize('phase', ['plan', 'probe', 'approach', 'contact'])
def test_no_execute_never_connects(phase, capsys):
    assert cli.main([phase], driver_factory=forbidden_driver) == 0
    assert json.loads(capsys.readouterr().out)['execution'] is False


def test_unreviewed_motion_rejected_before_device_connection():
    with pytest.raises(ValueError, match='D_PHYSICAL_REFERENCE_REVIEW_REQUIRED'):
        cli.main(['approach', '--start-zone', 'supply', '--execute'], driver_factory=forbidden_driver)


def environment(monkeypatch, tmp_path):
    monkeypatch.setenv('ROS_DOMAIN_ID', '20')
    monkeypatch.setattr(cli, 'LOCK', tmp_path/'lock')
    monkeypatch.setattr(cli, 'JsonlLog', lambda _: JsonlLog(tmp_path/'logs'))


class ReadOnlyDriver:
    def __init__(self):
        self.closed = False
        self.samples = 0

    def robot_system(self):
        return 0

    def sample(self):
        self.samples += 1
        return dict(posx=[1., 2., 3., 4., 5., 6.], robot_mode=0, gripper_status=2)

    def close(self):
        self.closed = True


def test_probe_only_queries_even_in_manual_mode(monkeypatch, tmp_path, capsys):
    environment(monkeypatch, tmp_path)
    driver = ReadOnlyDriver()  # No motion, mode-change, STOP or gripper methods exist.
    assert cli.main(['probe', '--execute'], driver_factory=lambda _: driver) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'HELD_READ_ONLY_PROBE_COMPLETE'
    assert result['sample']['robot_mode'] == 0
    assert result['robot_motion_commands'] == result['robot_gripper_commands'] == result['robot_mode_commands'] == 0
    assert driver.samples == 1 and driver.closed


@pytest.mark.parametrize('phase', ['approach', 'contact'])
def test_operator_review_is_session_only_and_does_not_invent_hardware_validation(
        monkeypatch, tmp_path, phase, capsys):
    environment(monkeypatch, tmp_path)
    original = cli.DEFAULT.read_bytes()
    driver = ReadOnlyDriver()
    calls = []

    def run(driver, connection, plan, profile, confirm, record, **kwargs):
        calls.append((plan, profile, kwargs))
        return dict(status='TEST_SESSION_NO_MOTION')

    monkeypatch.setattr(cli, 'run_step', run)
    args = [phase, '--confirm-envelope', '--execute']
    if phase == 'approach':
        args += ['--start-zone', 'supply']
    assert cli.main(args, driver_factory=lambda _: driver) == 0
    plan, profile, kwargs = calls[0]
    assert plan['settings']['physical_reference_reviewed']
    assert profile['physical_route_reviewed'] is (phase == 'approach')
    assert not plan['hardware_verified'] and not plan['source_execution_allowed']
    assert kwargs['phase'] == phase
    assert cli.DEFAULT.read_bytes() == original
    assert not read(cli.DEFAULT)['d_profile']['physical_route_reviewed']
    events = [json.loads(line) for p in (tmp_path/'logs').glob('*.jsonl') for line in p.read_text().splitlines()]
    review = next(e['payload'] for e in events if e['event'] == 'OPERATOR_ENVELOPE_REVIEW')
    assert review['command_line_confirmed'] and not review['physical_validation_performed']
    assert driver.closed
