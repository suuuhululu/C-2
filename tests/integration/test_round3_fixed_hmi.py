"""HMI ownership/STOP/result boundaries; no camera, robot, DB or API access."""
from copy import deepcopy
import json
from pathlib import Path
from queue import Queue
import signal
import subprocess
import sys

import pytest

from app.mvp_real_trial import FullFeatureRealTrial
from app.round3_fixed_trial import FixedStepProcess

ROOT = Path(__file__).resolve().parents[2]


class IdleTransport:
    def __init__(self, *args, **kwargs):
        self.events = Queue()
        self.sent = []

    def send(self, command, **payload):
        self.sent.append(command)

    def close(self):
        pass


class Child:
    def __init__(self):
        self.code = None
        self.signals = []

    def poll(self):
        return self.code

    def send_signal(self, value):
        self.signals.append(value)

    def wait(self, timeout):
        self.code = -2


@pytest.fixture
def child(monkeypatch):
    value = Child()
    def launch(command, **kwargs):
        value.command, value.kwargs = command, kwargs
        return value
    monkeypatch.setattr('app.round3_fixed_trial.subprocess.Popen', launch)
    return value


def write_result(process, **changes):
    directory = process.directory / 'native-run'
    directory.mkdir()
    value = dict(status='FIXED_STEP_EXECUTED', completed_steps=['T1'],
        assembly_completion=False, current_update=False, backend='REAL', provenance='LIVE_D_RUNTIME')
    value.update(changes)
    (directory / 'result.json').write_text(json.dumps(value))


@pytest.mark.parametrize('changes,accepted', [({}, True),
    ({'completed_steps':['T1','T2']}, False), ({'assembly_completion':True}, False),
    ({'backend':'MOCK','provenance':'SYNTHETIC'}, False)])
def test_process_adopts_only_exact_real_fixed_step_result(tmp_path, child, changes, accepted):
    process = FixedStepProcess(ROOT/'robot_control_integration', tmp_path/'trial')
    process.start()
    assert child.command[-2:] == ['--output', str(process.directory)]
    assert child.command[child.command.index('--only-step')+1] == 'T1'
    write_result(process, **changes)
    child.code = 0
    result = process.poll()
    assert (result['status']=='FIXED_STEP_EXECUTED') is accepted
    assert not result['assembly_completion'] and not result['current_update']
    assert not result['actual_stop_verified']


def test_stop_never_promotes_a_late_success_and_close_waits(tmp_path, child):
    process = FixedStepProcess(ROOT/'robot_control_integration', tmp_path/'trial')
    process.start()
    process.stop()
    assert child.signals == [signal.SIGINT]
    write_result(process)
    child.code = 0
    assert process.poll()['status'] == 'FIXED_STEP_INTERRUPTED_OR_FAILED'
    process.close()


def test_close_timeout_does_not_kill_or_claim_stopped(tmp_path, child):
    process = FixedStepProcess(ROOT/'robot_control_integration', tmp_path/'trial')
    process.start()
    def timeout(timeout):
        raise subprocess.TimeoutExpired(child.command, timeout)
    child.wait = timeout
    with pytest.raises(RuntimeError, match='VERIFY_PHYSICAL_STOP'):
        process.close()
    assert child.signals == [signal.SIGINT]
    assert process.result is None
    child.code = -2
    process.close()


@pytest.mark.parametrize('stop', [False, True])
def test_hmi_start_gates_login_and_review_then_runs_exactly_one_trial(tmp_path, monkeypatch, child, stop):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    monkeypatch.setattr('app.mvp_integration.RobotProcess', IdleTransport)
    runtime = FullFeatureRealTrial(ROOT/'robot_control_integration', tmp_path,
        round3_fixed_step=True, history_dsn='not-connected', c_mode='offline',
        fixed_trial_scenario=tmp_path/'scenario.json',supply_depth_profile=tmp_path/'depth.json',
        educational_depth_demo=True)
    try:
        assert not runtime.command('START')
        runtime.review_preparation(True)
        assert not runtime.command('START')
        runtime.creator = dict(user_id='test-owner',username='tester',display_name='Tester')
        linked = []
        monkeypatch.setattr(runtime, 'link_creator', lambda: linked.append(deepcopy(runtime.job_creator)))
        assert runtime.command('START')
        assert child.command[child.command.index('--scenario')+1] == str(tmp_path/'scenario.json')
        assert child.command[child.command.index('--supply-depth-profile')+1] == str(tmp_path/'depth.json')
        assert '--educational-depth-demo' in child.command
        assert linked == [runtime.creator]
        assert runtime.c_pending is None and runtime.workflow.check is None
        assert runtime.robot.sent == []  # No old EXECUTE/READ_STATE route.
        assert not runtime.command('START') and not runtime.command('RESUME')
        if stop:
            assert runtime.command('STOP')
        write_result(runtime.fixed_trial)
        child.code = 0
        runtime.poll()
        assert runtime.workflow.status == 'HOLD'
        assert runtime.workflow.completed == []
        assert runtime.workflow.storage == 'NOT_STARTED'
        assert runtime.fixed_result['status']==('FIXED_STEP_INTERRUPTED_OR_FAILED' if stop else 'FIXED_STEP_EXECUTED')
        runtime.workflow.snapshot()  # Existing HMI schema is still valid.
    finally:
        runtime.close()


def test_educational_child_requires_explicit_profile_before_start(tmp_path):
    with pytest.raises(ValueError,match='REQUIRES_SUPPLY_DEPTH_PROFILE'):
        FixedStepProcess(ROOT/'robot_control_integration',tmp_path/'trial',educational_depth_demo=True)
    assert not (tmp_path/'trial').exists()


@pytest.mark.parametrize('options', [
    ['--educational-depth-demo','--round3-fixed-step'],
    ['--supply-depth-profile','unused.json']])
def test_hmi_rejects_incomplete_or_nonfixed_calibration_options(tmp_path, options):
    result=subprocess.run([sys.executable,'-m','app.mvp_real_trial','--robot-root',
        str(ROOT/'robot_control_integration'),'--execute',*options],cwd=ROOT,
        text=True,capture_output=True,timeout=20)
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_native_single_step_replay_never_executes_T2_T3(tmp_path):
    result = subprocess.run([sys.executable,
        str(ROOT/'robot_control_integration/scripts/round2_three_step_trial.py'),
        'replay', '--only-step', 'T1', '--output', str(tmp_path)],
        text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    document = json.loads(next(tmp_path.glob('*/result.json')).read_text())
    assert document['completed_steps'] == ['T1']
    assert document['status'] == 'FIXED_STEP_EXECUTED'
    assert document['physical_commands'] == 0 and document['backend'] == 'MOCK'
    assert not document['image_yaw_replayed']


def test_fixed_mode_ui_uses_real_start_signal_without_old_execute(tmp_path, monkeypatch, child):
    from types import SimpleNamespace
    from PyQt5 import QtWidgets
    from app.qt_hmi import HmiWindow
    from app.mvp_integration import main
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    monkeypatch.setattr('app.mvp_integration.RobotProcess', IdleTransport)
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    runtime = FullFeatureRealTrial(ROOT/'robot_control_integration', tmp_path,
        round3_fixed_step=True, c_mode='offline')
    windows = []
    def make_window():
        window = HmiWindow()
        windows.append(window)
        return window
    def inspect():
        qapp.processEvents()
        window = windows[0]
        review = window.findChild(QtWidgets.QCheckBox)
        review.setChecked(True)
        qapp.processEvents()
        # QTimer's next render normally enables START after the review response.
        window.buttons['START'].setEnabled(True)
        window.buttons['START'].click()
        assert runtime.fixed_trial is not None
        assert '--only-step' in child.command
        assert runtime.robot.sent == []
        assert not next(b for b in window.findChildren(QtWidgets.QPushButton)
            if b.text()=='C 음성 대화').isVisible()
        window.close()
        return 0
    monkeypatch.setattr('app.qt_hmi.HmiWindow', make_window)
    monkeypatch.setattr(QtWidgets, 'QApplication', lambda _:SimpleNamespace(exec_=inspect))
    monkeypatch.setattr(sys, 'argv', ['trial','--robot-root',str(ROOT/'robot_control_integration'),
        '--log-directory',str(tmp_path),'--execute','--round3-fixed-step'])
    main(runtime_class=lambda *a,**kw:runtime, real_trial=True)


def test_conditionally_approved_supply_registry_forwarded(tmp_path, child):
    registry=tmp_path/'profile.json'
    process=FixedStepProcess(ROOT/'robot_control_integration',tmp_path/'trial',execution_profile=registry)
    process.start()
    index=child.command.index('--execution-profile')
    assert child.command[index+1]==str(registry.resolve())
    assert '--educational-depth-demo' not in child.command
    with pytest.raises(ValueError,match='CONFLICTING_SUPPLY_PROFILE_OPTIONS'):
        FixedStepProcess(ROOT/'robot_control_integration',tmp_path/'other',execution_profile=registry,
                         supply_depth_profile=tmp_path/'old.json')
