"""Manual retry gets a new grant; consumed ledgers and first failure records survive."""
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from scripts import robot_control_trial as cli

SOURCE = Path(__file__).resolve().parents[2]/'settings/onsite_5_18_l4_20261011'
spec = importlib.util.spec_from_file_location('target5_18_prepare', SOURCE/'prepare_approach.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@pytest.fixture
def folder(tmp_path):
    for name in ('held-approach.profile.json', 'session.approach.live.json',
                 'retry-readiness.json', 'ik-check.json'):
        value = json.loads((SOURCE/name).read_text())
        if name == 'retry-readiness.json':
            value['generated_at_unix_s'] = time.time()
        (tmp_path/name).write_text(json.dumps(value))
    return tmp_path


def test_two_preparations_use_fresh_identity_without_modifying_original_session(folder):
    original = (folder/'session.approach.live.json').read_bytes()
    va, a = helper.make_preparation(folder)
    vb, b = helper.make_preparation(folder)
    assert a['execution_id'] != b['execution_id'] and a['source_epoch'] != b['source_epoch']
    assert (folder/'session.approach.live.json').read_bytes() == original
    assert va == vb and a['profile_id'] == va['d_profile']['profile_id']
    assert a['allowed_trial_phase'] == 'approach' and a['seating_evidence_ref'] is None
    assert 590 < a['expires_unix_s']-time.time() <= 600


def test_expired_readiness_does_not_create_a_grant(folder):
    ready = json.loads((folder/'retry-readiness.json').read_text())
    with pytest.raises(ValueError, match='FRESH_READ_ONLY_READINESS'):
        helper.make_preparation(folder, now=ready['generated_at_unix_s']+601.)


@pytest.mark.parametrize('change', [dict(gripper_status=0), dict(query_duration_s=.6), dict(motion_status=1)])
def test_bad_readiness_is_not_promoted(folder, change):
    path = folder/'retry-readiness.json'
    ready = json.loads(path.read_text())
    ready['samples'][0].update(change)
    path.write_text(json.dumps(ready))
    with pytest.raises(ValueError, match='HELD_STOPPED'):
        helper.make_preparation(folder)


def test_wrong_target_rejected(folder):
    path = folder/'held-approach.profile.json'
    value = json.loads(path.read_text())
    value['desired_target']['trial_min_xy'] = [18, 5]
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='ONLY_FOR_TRIAL5_18'):
        helper.make_preparation(folder)


def test_preview_has_no_subprocess_or_saved_session(folder, monkeypatch):
    factory = helper.make_preparation
    monkeypatch.setattr(helper, 'make_preparation', lambda: factory(folder))
    monkeypatch.setattr(helper.subprocess, 'run', lambda *args, **kwargs: pytest.fail('NO_EXECUTION_IN_PREVIEW'))
    before = set(folder.iterdir())
    assert helper.main([]) == 0
    assert set(folder.iterdir()) == before


def test_explicit_run_creates_distinct_files_and_calls_cli_once(folder, monkeypatch):
    factory = helper.make_preparation
    monkeypatch.setattr(helper, 'make_preparation', lambda: factory(folder))
    monkeypatch.setattr(helper, 'DIRECTORY', folder)
    calls = []
    def launch(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(helper.subprocess, 'run', launch)
    assert helper.main(['--run']) == 0
    assert helper.main(['--run']) == 0
    assert len(calls) == 2 and calls[0] != calls[1]
    for command in calls:
        assert command[command.index('--phase')+1] == 'approach'
        assert command[-1] == '--execute'
        session = json.loads(Path(command[command.index('--session')+1]).read_text())
        assert session['execution_id'] in command[command.index('--output')+1]


def test_duplicate_grant_blocked_before_ros_and_first_cause_survives(folder, tmp_path, monkeypatch):
    value, session = helper.make_preparation(folder)
    setup_path, session_path = folder/'setup.json', folder/'new.session.json'
    setup_path.write_text(json.dumps(value)); session_path.write_text(json.dumps(session))
    monkeypatch.setenv('ROS_DOMAIN_ID', '20')
    monkeypatch.setattr(cli, 'ROOT', tmp_path/'runtime')
    ledger = cli.ROOT/'logs/executions'
    ledger.mkdir(parents=True)
    receipt = ledger/(hashlib.sha256(session['execution_id'].encode()).hexdigest()+'.json')
    receipt.write_text('original consumed receipt')
    args = ['run', '--execute', '--held-profile', str(setup_path), '--session', str(session_path),
            '--phase', 'approach', '--output', str(folder/'attempt')]
    original_preflight = cli.preflight
    original_import = builtins.__import__
    def no_devices(name, *args, **kwargs):
        if name.startswith(('rclpy', 'dsr_msgs2', 'pymodbus')):
            raise AssertionError('NO_DEVICE_IMPORT_IN_DUPLICATE_TEST')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_devices)
    def fail_first(*args): raise RuntimeError('FIRST_STARTUP_FAILURE')
    monkeypatch.setattr(cli, 'preflight', fail_first)
    assert cli.main(args) == 1
    monkeypatch.setattr(cli, 'preflight', original_preflight)
    assert cli.main(args) == 1  # The duplicate must fail before importing/connecting ROS.
    assert receipt.read_text() == 'original consumed receipt'
    journals = [json.loads(line) for file in (folder/'attempt').glob('trial-*.jsonl')
                for line in file.read_text().splitlines() if line.strip()]
    reasons = {row['data']['reason'] for row in journals if row['event'] == 'INTEGRATION_TRIAL_FAILURE'}
    assert reasons == {'FIRST_STARTUP_FAILURE', 'EXECUTION_ALREADY_CLAIMED_NEW_SESSION_REQUIRED'}
