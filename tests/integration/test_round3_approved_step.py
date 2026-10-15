"""Actual C review, A planning and B adoption; device transport is explicitly simulated."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Queue
import signal
import subprocess
import sys
import time

import pytest
from jsonschema import Draft202012Validator, RefResolver

from app.mvp_real_trial import ApprovedStepRealTrial
from app.round3_approved_step import load_initial_capture, validate_binding

ROOT = Path(__file__).resolve().parents[2]
ROBOT = ROOT / 'robot_control_integration'
SCENARIO = ROBOT / 'settings/round3_supply_rgbd_20261015/execution-portable-20261015/scenario.json'
REGISTRY = ROBOT / 'settings/round3_supply_rgbd_20261015/execution-portable-20261015/profile.json'
TARGET = dict(brick_type='2x3x1', color='blue', x=13, y=11, layer=2, orientation_deg=0)
REAL_POPEN = subprocess.Popen
COMMON = json.loads((ROOT / 'interfaces/schemas/day4.schema.json').read_text())
HMI = json.loads((ROOT / 'interfaces/schemas/hmi.schema.json').read_text())
HMI_VALIDATOR = Draft202012Validator(HMI, resolver=RefResolver.from_schema(HMI,
    store={COMMON['$id']: COMMON, 'https://c-2.invalid/schemas/day4.schema.json': COMMON}))


class Transport:
    def __init__(self, *args, **kwargs):
        self.events, self.sent, self.closed = Queue(), [], False

    def send(self, command, **kwargs):
        self.sent.append(command)
        if command == 'READ_STATE':
            sample = dict(posx=[400., 8., 315., 175., -179., 175.], velx=[0.] * 6,
                tcp='GripperDA_v4', tool='ToolWeight0', robot_state=1, robot_mode=1,
                drl_state=3, motion_status=0, gripper_status=0, gripper_width_mm=55., query_duration_s=.01)
            self.events.put(dict(event='STATE_SNAPSHOT', data=dict(captured_unix_s=time.time(),
                physical_commands=0, samples=[deepcopy(sample) for _ in range(3)])))

    def close(self):
        self.closed = True
        self.events.put(dict(event='PROCESS_EXITED', data={}))


class Child:
    def __init__(self):
        self.code, self.signals = None, []

    def poll(self): return self.code
    def send_signal(self, value): self.signals.append(value)
    def wait(self, timeout): self.code = -2


def install(tmp_path, monkeypatch, *, initial='OK', target=None):
    monkeypatch.setenv('C_DESIGN_USE_LLM', '0')
    monkeypatch.setattr('app.mvp_integration.RobotProcess', Transport)
    baseline = [p['block'] for p in json.loads(SCENARIO.read_text())['preplaced']]
    observation = dict(check_id='source-check', observation_seq=7, status='OK', visible_blocks=baseline,
        verified_regions=[dict(x=0, y=0, width=24, height=24, layer=i) for i in range(1, 6)], reason=None)
    if initial == 'unobservable':
        observation.update(status='UNOBSERVABLE', visible_blocks=[], verified_regions=[], reason='TEST_OCCLUSION')
    capture = tmp_path / 'initial-capture'
    capture.mkdir()
    context = dict(mode='REAL', check_kind='INITIAL', check_id='source-check', observation_seq=7,
        view_order=['V0', 'D1', 'D3'])
    (capture / 'context.json').write_text(json.dumps(dict(manifest=context,
        calibration=dict(calibration_id='TEST_CAPTURE_GEOMETRY'))))
    (capture / 'observed.json').write_text(json.dumps(observation))
    stamp = time.time() - (301 if initial == 'stale' else 0)
    for view in context['view_order']:
        (capture / view).mkdir()
        (capture / view / 'metadata.json').write_text(json.dumps(dict(mode='REAL', view_id=view,
            check_id='source-check', observation_seq=7, calibration_id='TEST_CAPTURE_GEOMETRY',
            scene_id='TEST_SCENE_NOT_PHYSICAL', captured_at=datetime.fromtimestamp(stamp, timezone.utc).isoformat())))
    targets = [p['target'] for p in json.loads(SCENARIO.read_text())['steps']]
    if target is not None: targets[0] = deepcopy(target)
    design = dict(design_version=1, blocks=baseline + targets)
    runtime = ApprovedStepRealTrial(ROBOT, tmp_path / 'jobs', initial_observation=capture,
        fixed_trial_scenario=SCENARIO, execution_profile=REGISTRY, fixture_design=design)
    child = Child()
    def launch(command, **kwargs):
        assert runtime.robot.closed  # Read-only ROS process released its writer lock first.
        child.command = command
        return child
    monkeypatch.setattr('app.round3_fixed_trial.subprocess.Popen', launch)
    return runtime, child


def settle(runtime, condition, *, approve=True):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        runtime.poll()
        HMI_VALIDATOR.validate(runtime.workflow.snapshot())
        if runtime.workflow.candidate:
            runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
        if approve and runtime.c_pending:
            assert runtime.answer('좋아 이걸로 하자')
        if condition(): return
        time.sleep(.01)
    pytest.fail(str((runtime.workflow.status, runtime.workflow.reason)))


@pytest.mark.parametrize('stop,wrong_result', [(False, False), (True, False), (False, True)])
def test_c_approval_actual_a_step_and_native_binding_hold_before_b(tmp_path, monkeypatch, stop, wrong_result):
    runtime, child = install(tmp_path, monkeypatch)
    try:
        assert not runtime.command('START')
        runtime.review_preparation(True)
        assert runtime.command('START')
        settle(runtime, lambda: runtime.c_pending is not None, approve=False)
        assert runtime.workflow.approved is None and runtime.fixed_trial is None
        settle(runtime, lambda: runtime.fixed_trial is not None or runtime.workflow.status == 'HOLD')
        assert runtime.fixed_trial is not None, runtime.workflow.reason
        path = runtime.fixed_trial.approved_step_document
        document = json.loads(path.read_text())
        identity = validate_binding(document, runtime.native_config, runtime.scenario, REGISTRY)
        assert document['prepared']['step']['after'] == TARGET
        assert document['prepared']['slot']['slot_index'] == 3
        assert document['prepared']['motion']['status'] == 'CANDIDATE'
        assert runtime.robot.sent == ['READ_STATE']
        assert '--approved-step-document' in child.command and '--only-step' in child.command
        assert identity['step_id'] == runtime.workflow.step()['step_id']
        assert identity['native_step_id'] == 'T2'  # The actual optimizer's first step is preserved.
        with monkeypatch.context() as native:
            native.setattr(subprocess, 'Popen', REAL_POPEN)
            command = [sys.executable, '-m', 'scripts.round2_three_step_trial', 'preview',
                '--scenario', str(SCENARIO), '--only-step', identity['native_step_id'],
                '--execution-profile', str(REGISTRY), '--approved-step-document', str(path)]
            preview = subprocess.run(command, cwd=ROBOT, capture_output=True, text=True, timeout=15)
            assert preview.returncode == 0, preview.stderr
            value = json.loads(preview.stdout)
            assert value['physical_commands'] == 0 and value['total_cycles'] == 1
        if stop:
            assert runtime.command('STOP')
            assert child.signals == [signal.SIGINT]
        if wrong_result: identity['execution_id'] = 'old-execution'
        output = runtime.fixed_trial.directory / 'native'
        output.mkdir()
        (output / 'result.json').write_text(json.dumps(dict(status='FIXED_STEP_EXECUTED',
            completed_steps=[identity['native_step_id']], backend='REAL', provenance='LIVE_D_RUNTIME',
            assembly_completion=False, current_update=False, service_binding=identity)))
        child.code = 0
        settle(runtime, lambda: runtime.fixed_result is not None)
        assert runtime.workflow.status == 'HOLD'
        assert (runtime.workflow.reason == 'APPROVED_STEP_EXECUTED_B_CONFIRMATION_REQUIRED') == (not stop and not wrong_result)
        assert runtime.workflow.current['blocks'] == document['prepared']['current']['blocks']
        assert runtime.workflow.completed == [] and runtime.workflow.storage == 'NOT_STARTED'
        assert not runtime.command('RESUME') and not runtime.command('REINSPECT')
        runtime.workflow.snapshot()
        for fault in ('target', 'slot', 'revision', 'profile', 'expired'):
            changed = deepcopy(document)
            if fault == 'target': changed['prepared']['step']['after']['x'] += 1
            if fault == 'slot': changed['prepared']['slot']['slot_index'] = 1
            if fault == 'revision': changed['prepared']['request']['latest_current']['current_revision'] += 1
            if fault == 'profile': changed['native_config_sha256'] = '0' * 64
            if fault == 'expired': changed['expires_unix_s'] = 0
            with pytest.raises(ValueError): validate_binding(changed, runtime.native_config, runtime.scenario, REGISTRY)
    finally:
        runtime.close()


@pytest.mark.parametrize('initial', ['stale', 'unobservable'])
def test_initial_observation_failure_never_generates_match_or_starts_robot(tmp_path, monkeypatch, initial):
    runtime, child = install(tmp_path, monkeypatch, initial=initial)
    try:
        runtime.review_preparation(True)
        assert runtime.command('START')
        settle(runtime, lambda: runtime.workflow.status == 'HOLD')
        assert runtime.fixed_trial is None and runtime.robot.sent == []
        assert runtime.workflow.current['blocks'] == [] and runtime.workflow.approved is None
    finally:
        runtime.close()


def test_cli_requires_real_initial_and_explicit_registry_before_ui():
    result = subprocess.run([sys.executable, '-m', 'app.mvp_real_trial', '--robot-root', str(ROBOT),
        '--execute', '--round3-approved-step'], cwd=ROOT, text=True, capture_output=True, timeout=15)
    assert result.returncode == 2 and '--initial-observation' in result.stderr


def test_other_c_approved_design_is_held_without_replacing_actual_current(tmp_path, monkeypatch):
    target = dict(brick_type='2x2x1', color='blue', x=9, y=9, layer=2, orientation_deg=0)
    runtime, child = install(tmp_path, monkeypatch, target=target)
    try:
        runtime.review_preparation(True)
        assert runtime.command('START')
        settle(runtime, lambda: runtime.workflow.status == 'HOLD')
        assert runtime.workflow.approved is not None
        assert runtime.fixed_trial is None and len(runtime.workflow.current['blocks']) == 8
        assert runtime.workflow.reason == 'APPROVED_STEP_SCENARIO_MISMATCH'
    finally:
        runtime.close()


@pytest.mark.parametrize('fault', ['missing_view', 'scene', 'identity', 'source_changed'])
def test_initial_capture_rejects_incomplete_or_changed_evidence(tmp_path, monkeypatch, fault):
    runtime, child = install(tmp_path, monkeypatch)
    path = tmp_path / 'initial-capture/D3/metadata.json'
    try:
        if fault == 'missing_view': path.unlink()
        else:
            metadata = json.loads(path.read_text())
            metadata['scene_id' if fault == 'scene' else 'check_id'] = 'different'
            path.write_text(json.dumps(metadata))
        if fault == 'source_changed':
            runtime.review_preparation(True)
            assert runtime.command('START')
            settle(runtime, lambda: runtime.workflow.status == 'HOLD')
        else:
            with pytest.raises((ValueError, OSError)):
                load_initial_capture(tmp_path / 'initial-capture')
        assert runtime.fixed_trial is None and runtime.robot.sent == []
    finally:
        runtime.close()


def test_approved_mode_ui_shows_saved_real_source_and_keeps_c_controls(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PyQt5 import QtWidgets
    from app.mvp_integration import main
    from app.qt_hmi import HmiWindow
    runtime, child = install(tmp_path, monkeypatch)
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    windows = []
    def make_window():
        window = HmiWindow()
        windows.append(window)
        return window
    def inspect():
        qapp.processEvents()
        window = windows[0]
        assert '첫 A Step' in window.heading.text()
        assert 'B 조립 확인' in window.progress.text()
        assert '저장 실관측' in window.footer.text()
        assert not window.buttons['RESUME'].isEnabled()
        assert runtime.robot.sent == [] and runtime.fixed_trial is None
        window.close()
        return 0
    monkeypatch.setattr('app.qt_hmi.HmiWindow', make_window)
    monkeypatch.setattr('app.mvp_real_trial.ApprovedStepRealTrial', lambda *a, **kw: runtime)
    monkeypatch.setattr(QtWidgets, 'QApplication', lambda _: SimpleNamespace(exec_=inspect))
    monkeypatch.setattr(sys, 'argv', ['trial', '--robot-root', str(ROBOT), '--execute',
        '--round3-approved-step', '--initial-observation', str(tmp_path / 'initial-capture'),
        '--fixed-trial-scenario', str(SCENARIO), '--execution-profile', str(REGISTRY)])
    main(real_trial=True)
