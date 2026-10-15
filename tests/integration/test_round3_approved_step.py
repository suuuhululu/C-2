"""Actual C review, A planning and B adoption; device transport is explicitly simulated."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Queue
from threading import Event
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
        self.options = kwargs

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


def install(tmp_path, monkeypatch, *, initial='OK', target=None, live=False, camera_free=False, three_step=False, scenario=None,
            live_three=False):
    monkeypatch.setenv('C_DESIGN_USE_LLM', '0')
    monkeypatch.setattr('app.mvp_integration.RobotProcess', Transport)
    scenario = Path(scenario or SCENARIO)
    baseline = [p['block'] for p in json.loads(scenario.read_text())['preplaced']]
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
    targets = [p['target'] for p in json.loads(scenario.read_text())['steps']]
    if target is not None: targets[0] = deepcopy(target)
    design = dict(design_version=1, blocks=baseline + targets)
    if live:
        from app.cad_real_trial import REAL_STILLNESS_TOLERANCES
        settings = json.loads((ROOT/'interfaces/round3_initial_inspection.json').read_text())
        settings.update(calibration_id='TEST_CAPTURE_GEOMETRY', stillness=REAL_STILLNESS_TOLERANCES)
        monkeypatch.setattr('app.round3_initial_inspection.load_settings', lambda _:settings)
    runtime = ApprovedStepRealTrial(ROBOT, tmp_path / 'jobs', initial_observation=None if camera_free else capture,
        fixed_trial_scenario=scenario, execution_profile=REGISTRY, fixture_design=design,
        live_inspection=live, camera_free_trial=camera_free, three_step_trial=three_step, live_three_step=live_three)
    child = Child()
    child.launches = 0
    def launch(command, **kwargs):
        assert runtime.robot.closed  # Read-only ROS process released its writer lock first.
        child.command = command
        child.launches += 1
        child.code = None
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
        release = next(iter(document['prepared']['d_profile']['steps'].values()))
        assert release['release_width_mm'] == runtime.native_config['release_width_mm'] == 47.
        assert release['release_feedback_range_mm'] == runtime.native_config['release_feedback_range_mm'] == [32.,55.]
        assert release['press_force_stop_n'] == runtime.native_config['press_force_stop_n'] == 70.
        assert release['seating_force_stop_n'] == runtime.native_config['seating_force_stop_n'] == 55.
        assert runtime.native_config['force_stop_n'] == 45.
        assert document['prepared']['d_profile']['seating_force_stop_n'] == 55.
        assert document['prepared']['d_profile']['press_force_stop_n'] == 70.
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


def test_camera_free_trial_uses_explicit_scenario_and_never_claims_b_completion(tmp_path, monkeypatch):
    monkeypatch.setattr('app.round3_approved_step.load_initial_capture',
        lambda _: pytest.fail('camera-free trial must not load or manufacture a B capture'))
    runtime, child = install(tmp_path, monkeypatch, camera_free=True)
    try:
        assert runtime.robot.options['gestures'] is False
        runtime.review_preparation(True)
        assert runtime.command('START')
        settle(runtime, lambda:runtime.c_pending is not None, approve=False)
        assert runtime.fixed_trial is None and runtime.workflow.approved is None
        settle(runtime, lambda:runtime.fixed_trial is not None or runtime.workflow.status=='HOLD')
        assert runtime.fixed_trial is not None, runtime.workflow.reason
        doc=json.loads(runtime.fixed_trial.approved_step_document.read_text())
        identity=validate_binding(doc,runtime.native_config,runtime.scenario,REGISTRY)
        assert identity['trial_scope']=='SIXPART_REAL_D_SINGLE_STEP'
        assert identity['physical_assembly_verified'] is False
        assert doc['state_basis']=='SYNTHETIC_SCENARIO_NOT_B_OBSERVATION'
        assert 'captured_unix_s' not in runtime.initial_packet
        assert doc['prepared']['step']['after']==TARGET and identity['native_step_id']=='T2'
        original=deepcopy(runtime.workflow.current)
        output=runtime.fixed_trial.directory/'native';output.mkdir()
        (output/'result.json').write_text(json.dumps(dict(status='FIXED_STEP_EXECUTED',completed_steps=['T2'],
            backend='REAL',provenance='LIVE_D_RUNTIME',assembly_completion=False,current_update=False,service_binding=identity)))
        child.code=0
        settle(runtime,lambda:runtime.fixed_result is not None)
        assert runtime.workflow.status=='HOLD' and runtime.workflow.current==original
        assert not runtime.workflow.completed and runtime.workflow.storage=='NOT_STARTED'
        for command in ('START','RESUME','REINSPECT','CONTINUE_AFTER_CORRECTION'):
            assert not runtime.command(command)
        assert child.launches==1
        for field,value in (('state_basis','REAL'),('physical_assembly_verified',True),('baseline_source_sha256',{})):
            changed=deepcopy(doc);changed[field]=value
            with pytest.raises(ValueError):validate_binding(changed,runtime.native_config,runtime.scenario,REGISTRY)
    finally:runtime.close()


@pytest.mark.parametrize('option', ['--initial-observation','--round3-live-inspection','--round3-approved-step'])
def test_camera_free_cli_rejects_mixed_b_or_real_initial_before_ui(option):
    args=[sys.executable,'-m','app.mvp_real_trial','--robot-root',str(ROBOT),'--execute',
          '--round3-camera-free-trial',option]
    if option=='--initial-observation':args.append('/unused')
    result=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert result.returncode==2 and '혼용' in result.stderr


from test_history_personal_db import connection, users


@pytest.mark.parametrize('web_retry', [False,True])
def test_sixpart_login_c_a_native_result_actual_db_web_stays_unverified(
        connection,users,tmp_path,monkeypatch,web_retry):
    from contextlib import nullcontext
    from threading import Thread
    from history import personal,store
    from history.mvp_save import verify_web_job
    from history.web import HistoryServer
    monkeypatch.setattr(store,'connect',lambda _:nullcontext(connection))
    runtime,child=install(tmp_path,monkeypatch,camera_free=True)
    runtime.history_dsn=''
    with HistoryServer(('127.0.0.1',0),'') as server:
        worker=Thread(target=server.serve_forever,daemon=True);worker.start()
        runtime.web_url='http://127.0.0.1:1' if web_retry else server.origin
        try:
            runtime.review_preparation(True)
            assert not runtime.command('START')
            assert runtime.login(users[0]['username'],'fixture-password')
            settle(runtime,lambda:not runtime.login_pending,approve=False)
            assert runtime.command('START')
            settle(runtime,lambda:runtime.owner_state=='SUCCEEDED',approve=False)
            assert runtime.fixed_trial is None
            settle(runtime,lambda:runtime.fixed_trial is not None or runtime.workflow.status=='HOLD')
            assert runtime.fixed_trial is not None,runtime.workflow.reason
            current=deepcopy(runtime.workflow.current)
            finish_native(runtime,child)
            settle(runtime,lambda:runtime.trial_archive_status in ('SUCCEEDED','FAILED'))
            assert runtime.trial_db_recorded
            if web_retry:
                assert runtime.trial_archive_status=='FAILED'
                original_count=store.job_counts(connection,runtime.workflow.job_id)['event_count']
                runtime.web_url=server.origin
                assert runtime.archive_trial()
                settle(runtime,lambda:runtime.trial_archive_status=='SUCCEEDED')
                assert store.job_counts(connection,runtime.workflow.job_id)['event_count']==original_count
            assert runtime.trial_archive_status=='SUCCEEDED',runtime.trial_archive_reason
            summary=verify_web_job(server.origin,runtime.workflow.job_id,
                users[0]['username'],'fixture-password',None)
            assert summary['completion']['assembly']=='NOT_RECORDED'
            assert summary['storage']['status']=='PENDING'
            assert len(summary['designs'][0]['design']['blocks'])==11
            with pytest.raises(ValueError,match='WEB_JOB_UNAVAILABLE'):
                verify_web_job(server.origin,runtime.workflow.job_id,users[1]['username'],'fixture-password',None)
            assert runtime.workflow.status=='HOLD' and runtime.workflow.current==current
            assert runtime.workflow.completed==[] and child.launches==1
            assert not runtime.save_logged_in()
            assert personal.bundle(connection,runtime.workflow.job_id,users[0]['user_id'])['completion']['assembly']=='NOT_RECORDED'
        finally:
            runtime.close();server.shutdown();worker.join(timeout=2)


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


@pytest.mark.parametrize('camera_free', [False,True])
def test_approved_mode_ui_shows_saved_real_source_and_keeps_c_controls(tmp_path, monkeypatch,camera_free):
    from types import SimpleNamespace
    from PyQt5 import QtWidgets
    from app.mvp_integration import main
    from app.qt_hmi import HmiWindow
    runtime, child = install(tmp_path, monkeypatch,camera_free=camera_free)
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    windows = []
    def make_window(**kwargs):
        from PyQt5.QtCore import QSize
        window = HmiWindow(screen_size=QSize(1920,1080),**kwargs)
        windows.append(window)
        return window
    def inspect():
        qapp.processEvents()
        window = windows[0]
        assert ('A 첫 Step' if camera_free else '첫 A Step') in window.heading.text()
        assert 'B 조립 확인' in window.progress.text()
        assert ('조립 완료 미확인' if camera_free else '저장 실관측') in window.footer.text()
        if camera_free:
            assert 'B 관측 없음' in window.target_caption.text()
            assert '실관측 없음' in window.inspection_view.board_panels[0].title()
            assert '시험 기준' in window.inspection_view.summary.text()
            screenshot=ROOT/'reports/restore-20261015/sixpart-hmi-preview.png'
            screenshot.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(screenshot))
        assert not window.buttons['RESUME'].isEnabled()
        assert runtime.robot.sent == [] and runtime.fixed_trial is None
        window.close()
        return 0
    monkeypatch.setattr('app.qt_hmi.HmiWindow', make_window)
    monkeypatch.setattr('app.mvp_real_trial.ApprovedStepRealTrial', lambda *a, **kw: runtime)
    monkeypatch.setattr(QtWidgets, 'QApplication', lambda _: SimpleNamespace(exec_=inspect))
    mode=['--round3-camera-free-trial'] if camera_free else [
        '--round3-approved-step','--initial-observation',str(tmp_path/'initial-capture')]
    monkeypatch.setattr(sys, 'argv', ['trial', '--robot-root', str(ROBOT), '--execute',*mode,
        '--fixed-trial-scenario', str(SCENARIO), '--execution-profile', str(REGISTRY)])
    main(real_trial=True)


def finish_native(runtime, child):
    output = runtime.fixed_trial.directory/'native'
    output.mkdir()
    identity = runtime.service_binding
    (output/'result.json').write_text(json.dumps(dict(status='FIXED_STEP_EXECUTED',
        completed_steps=[identity['native_step_id']], backend='REAL', provenance='LIVE_D_RUNTIME',
        assembly_completion=False, current_update=False, service_binding=identity)))
    child.code = 0


@pytest.mark.parametrize('fault', ['MATCH', 'MISMATCH', 'UNOBSERVABLE', 'ERROR', 'STOP'])
def test_native_completion_to_actual_b_contract_without_devices(tmp_path, monkeypatch, fault):
    entered = Event()
    class FixtureCamera:
        """Explicit fixture replaces only D/camera; actual B performs comparison."""
        def __init__(self, root, settings, output, review):
            self.output, self.outcomes = output, {}
        def __call__(self, context, active):
            entered.set()
            if fault == 'STOP':
                while active(): time.sleep(.005)
                self.outcomes[context['check_id']] = dict(actual_stop_verified=True,
                    stop_sample=dict(provenance='SYNTHETIC_TEST_ONLY'))
                raise RuntimeError('TEST_CANCELED')
            if fault == 'ERROR': raise RuntimeError('TEST_CAMERA_ERROR')
            blocks = deepcopy(runtime.initial_observation['visible_blocks']) + [deepcopy(TARGET)]
            if fault == 'MISMATCH': blocks[-1]['color'] = 'yellow'
            value = dict(check_id=context['check_id'], observation_seq=context['observation_seq'],
                status='OK', visible_blocks=blocks,
                verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in range(1,6)],reason=None)
            if fault == 'UNOBSERVABLE':
                value.update(status='UNOBSERVABLE', visible_blocks=[], verified_regions=[], reason='TEST_OCCLUSION')
            return value, {}
    monkeypatch.setattr('app.round3_live_inspection.LiveInspectionObserver', FixtureCamera)
    runtime, child = install(tmp_path, monkeypatch, live=True)
    try:
        runtime.review_preparation(True)
        assert runtime.command('START')
        settle(runtime, lambda:runtime.fixed_trial is not None)
        assert not entered.is_set() and len(runtime.workflow.current['blocks']) == 8
        finish_native(runtime, child)
        settle(runtime, entered.is_set, approve=False)
        if fault == 'STOP':
            assert runtime.command('STOP')
            settle(runtime, lambda:runtime.workflow.status=='STOPPED', approve=False)
        else:
            settle(runtime, lambda:runtime.workflow.check is None and
                runtime.workflow.status in ('HOLD','WAIT_INTENT'), approve=False)
        if fault == 'MATCH':
            assert len(runtime.workflow.completed) == 1
            assert len(runtime.workflow.current['blocks']) == 9
            assert runtime.workflow.current['current_revision'] == 2
            assert runtime.workflow.reason == 'REMAINING_NATIVE_STEP_BINDING_REQUIRED'
            assert runtime.command('REQUEST_DESIGN_CHANGE')
            assert runtime.c_pending[0] == 'c.intent'
        else:
            assert runtime.workflow.completed == []
            if fault == 'MISMATCH':
                assert runtime.c_pending[0] == 'c.intent'
                assert runtime.c_pending[1]['current'] == runtime.workflow.current
                assert runtime.workflow.current['blocks'][-1]['color'] == 'yellow'
            else: assert len(runtime.workflow.current['blocks']) == 8
        for _ in range(3):runtime.poll()
        assert child.launches == 1 and runtime.robot.sent == ['READ_STATE']
        assert runtime.workflow.storage == 'NOT_STARTED'
        assert not runtime.command('RESUME')
    finally:runtime.close()


def test_live_inspection_cli_requires_approved_mode_before_ui():
    result = subprocess.run([sys.executable,'-m','app.mvp_real_trial','--robot-root',str(ROBOT),
        '--execute','--round3-live-inspection'],cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert result.returncode == 2 and '--round3-approved-step' in result.stderr


def test_offline_preflight_keeps_all_supply_targets_and_exposes_native_support_gap():
    result=subprocess.run([sys.executable,'-m','app.round3_service_preflight'],cwd=ROOT,
        text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout)
    assert value['sample_kind']=='SYNTHETIC_EXPECTED_PREFIX_NOT_B_CURRENT'
    assert value['user_design_approved'] is False
    assert value['physical_commands']==value['device_connections']==0
    assert value['supply_physical_targets']==25
    assert all(row['execution_approved'] for row in value['supply_slots'])
    assert [row['native_step_id'] for row in value['steps']]==['T2','T1','T3']
    assert all(row['assessment_status']=='CANDIDATE' for row in value['steps'])
    assert value['steps'][2]['additional_native_support_required']
    assert value['steps'][2]['native_support_target']['layer']==2


@pytest.mark.parametrize('stop,missing_home', [(False,False),(True,False),(False,True)])
def test_three_step_approval_binds_all_configs_and_never_updates_b(tmp_path, monkeypatch, stop, missing_home):
    from app.round3_approved_step import validate_trial_sequence
    scenario=json.loads(SCENARIO.read_text())
    scenario['free_motion_speed_scale']=2.
    scenario['steps'][1]['assembly_board_x_offset_mm']=1.5
    path=tmp_path/'scenario.json';path.write_text(json.dumps(scenario))
    runtime,child=install(tmp_path,monkeypatch,camera_free=True,three_step=True,scenario=path)
    try:
        runtime.review_preparation(True)
        assert runtime.command('START')
        settle(runtime,lambda:runtime.fixed_trial is not None or runtime.workflow.status=='HOLD')
        assert runtime.fixed_trial is not None,runtime.workflow.reason
        document=json.loads(runtime.fixed_trial.approved_step_document.read_text())
        items=[dict(case=cfg['trial_step'],config=cfg) for cfg in runtime.native_configs]
        ordered,binding=validate_trial_sequence(document,items,runtime.scenario,REGISTRY)
        assert [item['case']['step_id'] for item in ordered]==['T2','T1','T3']
        assert [row['additional_native_support_required'] for row in document['native_sequence']]==[False,False,True]
        assert document['manual_step_confirmation'] and document['home_after_each_step']
        assert '--three-step-trial' in child.command and '--only-step' not in child.command
        cfg=runtime.native_config
        settings=next(iter(document['prepared']['d_profile']['steps'].values()))
        assert settings['assembly_board_offset']==cfg['assembly_board_offset']
        assert settings['assembly_board_offset']['board_x_mm']==1.5
        assert settings['rise_velocity']==24. and settings['transit_velocity']==240.
        assert settings['seating_velocity']==settings['press_velocity']==12.
        changed=deepcopy(items);changed[0]['config']['velocity']+=1
        with pytest.raises(ValueError,match='SEQUENCE_CONFIG_CHANGED'):
            validate_trial_sequence(document,changed,runtime.scenario,REGISTRY)
        bad=deepcopy(document);bad['native_sequence'].reverse()
        with pytest.raises(ValueError,match='SEQUENCE_CONFIG_CHANGED'):
            validate_trial_sequence(bad,items,runtime.scenario,REGISTRY)
        baseline=deepcopy(runtime.workflow.current)
        progressdir=runtime.fixed_trial.directory/'native-test';progressdir.mkdir()
        (progressdir/'progress.json').write_text(json.dumps(dict(event='TRIAL_STEP_CONFIRMATION_REQUIRED',
            data=dict(step=runtime.scenario['steps'][0],index=1,total=3,completed_steps=['T2']))))
        display=runtime.trial_display()
        assert display['step_id']=='T1' and display['completed']==1
        assert len(display['trial_expected'])==9 and runtime.workflow.current==baseline
        homes=[dict(view='HOME',stopped_verified=True) for _ in range(2 if missing_home else 3)]
        (progressdir/'result.json').write_text(json.dumps(dict(status='THREE_CYCLES_COMPLETED',
            completed_steps=['T2','T1','T3'],home_returns=homes,backend='REAL',provenance='LIVE_D_RUNTIME',
            service_binding=binding,assembly_completion=False,current_update=False)))
        if stop:assert runtime.command('STOP')
        child.code=0
        settle(runtime,lambda:runtime.fixed_result is not None,approve=False)
        assert (runtime.fixed_result['status']=='THREE_STEP_TRIAL_EXECUTED')==(not stop and not missing_home)
        assert runtime.workflow.status=='HOLD' and runtime.workflow.completed==[]
        assert runtime.workflow.current==baseline and runtime.workflow.inspection is None
        assert not runtime.command('RESUME') and not runtime.command('START')
        assert child.launches==1
    finally:runtime.close()
