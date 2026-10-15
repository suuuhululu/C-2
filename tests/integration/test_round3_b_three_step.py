"""Real C/A/B code; only device transport/camera images are explicit fixtures."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
from threading import Event
import time

import pytest

from app.round3_approved_step import validate_binding
from test_round3_approved_step import install, settle, ROOT, ROBOT, REGISTRY, SCENARIO, REAL_POPEN


@pytest.fixture(autouse=True)
def deployed_profile(monkeypatch):
    import test_round3_approved_step as shared
    profile = ROBOT / 'settings/round3_b_three_step_20261015'
    monkeypatch.setattr(shared,'REGISTRY',profile/'profile.json')
    monkeypatch.setattr(shared,'SCENARIO',profile/'scenario.json')
    monkeypatch.setattr(sys.modules[__name__],'REGISTRY',profile/'profile.json')
    monkeypatch.setattr(sys.modules[__name__],'SCENARIO',profile/'scenario.json')


def setup_runtime(tmp_path, monkeypatch, fault=None):
    entered, release = Event(), Event()
    class FixtureCamera:
        def __init__(self, root, settings, output, review):
            self.output, self.outcomes = output, {}

        def __call__(self, context, active):
            kind = context['check_kind']
            entered.set()
            if fault == 'delayed':
                while not release.is_set() and active():
                    time.sleep(.005)
            if fault == 'ERROR':
                raise RuntimeError('EXPLICIT_TEST_CAMERA_FAILURE')
            blocks = deepcopy(runtime.workflow.current['blocks'])
            if kind == 'STEP':
                blocks.append(deepcopy(context['target_after']))
            if fault == 'MISMATCH' or fault == 'FINAL_MISMATCH' and kind == 'FINAL':
                blocks[-1]['color'] = 'yellow' if blocks[-1]['color'] == 'blue' else 'blue'
            value = dict(check_id=context['check_id'], observation_seq=context['observation_seq'],
                status='OK', visible_blocks=blocks,
                verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in range(1,6)], reason=None)
            if fault == 'UNOBSERVABLE':
                value.update(status='UNOBSERVABLE',visible_blocks=[],verified_regions=[],reason='TEST_OCCLUSION')
            self.outcomes[context['check_id']] = dict(home_return_verified=True,
                writer_released=fault != 'writer', actual_stop_verified=True)
            return value, dict(provenance='SYNTHETIC_TEST_CAMERA')
    monkeypatch.setattr('app.round3_live_inspection.LiveInspectionObserver', FixtureCamera)
    runtime, child = install(tmp_path, monkeypatch, live=True, live_three=True)
    runtime.review_preparation(True)
    assert runtime.command('START')
    settle(runtime, lambda:runtime.fixed_trial is not None)
    return runtime, child, entered, release


def complete(runtime, child, *, home=True):
    output = runtime.fixed_trial.directory / 'native'
    output.mkdir()
    identity = runtime.service_binding
    result = dict(status='FIXED_STEP_EXECUTED', completed_steps=[identity['native_step_id']],
        backend='REAL', provenance='LIVE_D_RUNTIME', assembly_completion=False, current_update=False,
        service_binding=identity, home_returns=[dict(view='HOME',stopped_verified=True)] if home else [])
    (output/'result.json').write_text(json.dumps(result))
    child.code = 0


@pytest.mark.parametrize('fault', [None, 'FINAL_MISMATCH'])
def test_all_three_steps_use_fresh_b_prefix_native_consumer_and_separate_final(tmp_path, monkeypatch, fault):
    runtime, child, _, _ = setup_runtime(tmp_path, monkeypatch, fault)
    try:
        directories = []
        for index, native_id in enumerate(('T2','T1','T3')):
            assert child.launches == index + 1
            assert runtime.service_binding['native_step_id'] == native_id
            assert runtime.service_binding['b_confirmed_step_count'] == index
            assert len(runtime.workflow.completed) == index
            assert len(runtime.workflow.current['blocks']) == 8 + index
            assert '--return-home-after-step' in child.command
            assert '--only-step' in child.command and '--three-step-trial' not in child.command
            path = runtime.fixed_trial.approved_step_document
            directories.append(runtime.fixed_trial.directory)
            doc = json.loads(path.read_text())
            assert validate_binding(doc,runtime.native_config,runtime.scenario,REGISTRY) == runtime.service_binding
            depth = json.loads(Path(runtime.native_config['vision']['depth_center_profile']).read_text())
            assert [depth[k] for k in ('max_shift_mm','max_height_error_mm','max_depth_spread_mm')] == [10.,10.,10.]
            if native_id == 'T2':
                assert runtime.native_config['assembly_board_offset']['board_y_mm'] == 1.5
                assert 'board_x_mm' not in runtime.native_config['assembly_board_offset']
            if native_id == 'T3':
                assert runtime.native_config['trial_step']['human_hold'] is True
                # Native's extra onsite support stays required even when A says NONE.
                assert doc['prepared']['assessment']['action_proposal']['assistance_kind'] == 'NONE'
            with monkeypatch.context() as native:
                native.setattr(subprocess,'Popen',REAL_POPEN)
                preview = subprocess.run([sys.executable,'-m','scripts.round2_three_step_trial','preview',
                    '--scenario',str(SCENARIO),'--execution-profile',str(REGISTRY),'--only-step',native_id,
                    '--return-home-after-step','--approved-step-document',str(path)],
                    cwd=ROBOT,text=True,capture_output=True,timeout=20)
                assert preview.returncode == 0, preview.stderr
                assert json.loads(preview.stdout)['physical_commands'] == 0
            complete(runtime,child)
            settle(runtime, lambda:child.launches == index+2 or runtime.workflow.status in ('HOLD','COMPLETE','WAIT_INTENT'), approve=False)
            if index < 2:
                assert child.launches == index+2, runtime.workflow.reason
        assert len(set(directories)) == 3 and child.launches == 3
        assert len(runtime.workflow.completed) == 3
        assert [v['check_kind'] for v in runtime.workflow.accepted_checks.values()] == ['INITIAL','STEP','STEP','STEP','FINAL']
        if fault:
            assert runtime.workflow.status == 'WAIT_INTENT' and runtime.workflow.assembly == 'MISMATCH'
            assert runtime.c_pending[0] == 'c.intent'
        else:
            assert runtime.workflow.status == 'COMPLETE' and runtime.workflow.reason == 'B_FINAL_MATCH'
            assert runtime.workflow.assembly == 'MATCH'
        assert runtime.workflow.storage == 'NOT_STARTED'
    finally:
        runtime.close()


@pytest.mark.parametrize('fault', ['MISMATCH','UNOBSERVABLE','ERROR','writer','missing_home','invalid_home','delayed'])
def test_no_next_native_without_real_b_match_and_released_home(tmp_path, monkeypatch, fault):
    runtime, child, entered, release = setup_runtime(tmp_path, monkeypatch, fault)
    try:
        before = deepcopy(runtime.workflow.current)
        complete(runtime,child,home=fault != 'missing_home')
        if fault == 'invalid_home':
            path = runtime.fixed_trial.directory/'native/result.json'
            document = json.loads(path.read_text())
            document['home_returns'] = None
            path.write_text(json.dumps(document))
        if fault == 'delayed':
            settle(runtime,entered.is_set,approve=False)
            for _ in range(4):runtime.poll()
            assert runtime.workflow.current == before and child.launches == 1
            assert runtime.command('STOP')
            release.set()
            settle(runtime,lambda:not runtime.live_check_running.is_set(),approve=False)
        else:
            settle(runtime,lambda:runtime.workflow.status in ('HOLD','WAIT_INTENT'),approve=False)
            if fault in ('UNOBSERVABLE','ERROR','missing_home','invalid_home'):
                assert runtime.workflow.current == before
            if fault in ('missing_home','invalid_home'):assert not entered.is_set()
        assert child.launches == 1
        assert runtime.workflow.assembly != 'MATCH' and runtime.workflow.storage == 'NOT_STARTED'
        assert not runtime.command('RESUME')
    finally:
        release.set()
        runtime.close()


@pytest.mark.parametrize('field', ['current','prefix','slot','expired','home_settings'])
def test_second_step_rejects_changed_current_prefix_slot_expiry_or_home(tmp_path, monkeypatch, field):
    runtime, child, _, _ = setup_runtime(tmp_path, monkeypatch)
    try:
        complete(runtime,child)
        settle(runtime,lambda:child.launches==2)
        doc = json.loads(runtime.fixed_trial.approved_step_document.read_text())
        if field == 'current':doc['prepared']['current']['current_revision'] += 1
        if field == 'prefix':doc['b_confirmed_steps'][0]['comparison'] = 'MISMATCH'
        if field == 'slot':doc['prepared']['slot']['slot_index'] = 5
        if field == 'expired':doc['expires_unix_s'] = time.time()-1
        if field == 'home_settings':doc['home_settings_sha256'] = 'changed'
        with pytest.raises(ValueError):
            validate_binding(doc,runtime.native_config,runtime.scenario,REGISTRY)
    finally:runtime.close()


@pytest.mark.parametrize('extra', [[],['--round3-camera-free-trial'],['--round3-three-step-trial']])
def test_real_b_cli_rejects_missing_initial_and_synthetic_modes_before_devices(extra):
    value = subprocess.run([sys.executable,'-m','app.mvp_real_trial','--robot-root',str(ROBOT),
        '--execute','--round3-b-three-step',*extra],cwd=ROOT,text=True,capture_output=True,timeout=15)
    assert value.returncode == 2 and '실제 --initial-observation' in value.stderr


def test_real_b_hmi_mode_labels_current_and_c_keeps_review_controls(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PyQt5 import QtWidgets
    from PyQt5.QtCore import QSize
    from app.mvp_integration import main
    from app.qt_hmi import HmiWindow
    runtime, _ = install(tmp_path,monkeypatch,live=True,live_three=True)
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    windows = []
    def make_window(**kwargs):
        window = HmiWindow(screen_size=QSize(1920,1080),**kwargs)
        windows.append(window)
        return window
    def inspect():
        qapp.processEvents()
        window = windows[0]
        assert '실제 B와 3-Step' in window.windowTitle()
        assert 'B 실제 검사' in window.heading.text()
        assert 'FINAL MATCH' in window.footer.text()
        assert not window.buttons['RESUME'].isEnabled()
        assert not window.user_request_controls.buttons['change_design'].isEnabled()
        assert runtime.robot.sent == [] and runtime.fixed_trial is None
        window.grab().save(str(ROOT.parent/'evidence/hmi-real-b.png'))
        window.close()
        return 0
    monkeypatch.setattr('app.qt_hmi.HmiWindow',make_window)
    monkeypatch.setattr('app.mvp_real_trial.ApprovedStepRealTrial',lambda *a,**kw:runtime)
    monkeypatch.setattr(QtWidgets,'QApplication',lambda _:SimpleNamespace(exec_=inspect))
    monkeypatch.setattr(sys,'argv',['trial','--robot-root',str(ROBOT),'--execute',
        '--round3-b-three-step','--initial-observation',str(tmp_path/'initial-capture'),
        '--fixed-trial-scenario',str(SCENARIO),'--execution-profile',str(REGISTRY)])
    main(real_trial=True)
