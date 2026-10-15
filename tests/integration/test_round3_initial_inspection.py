"""Real B owner and process protocol; D and all camera data are explicit fixtures."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

import pytest

from app import round3_initial_inspection as initial
from app.cad_real_trial import REAL_STILLNESS_TOLERANCES
from app.docker_b_observer import DockerBObserver
from app.round3_approved_step import load_initial_capture

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = '''
import json,sys
from pathlib import Path
from datetime import datetime,timezone
x=json.loads(sys.stdin.readline()); c=x['context']; root=Path(sys.argv[1]); fault=sys.argv[2]
seq=0
def send(value): print(json.dumps(value),flush=True)
def hook(name,view):
 global seq
 seq+=1; send(dict(kind='HOOK',check_id=c['check_id'],sequence=seq,name=name,args=[view]))
 r=json.loads(sys.stdin.readline())
 if r.get('error'): raise RuntimeError(r['error'])
 return r['value']
try:
 for view in ['V0','D1','D3']:
  if not hook('confirm_view',view) or not hook('is_stopped',view):raise RuntimeError('VIEW_NOT_STOPPED:'+view)
  hook('robot_pose',view)
 path=root/x['output'].removeprefix('/workspace/')/'cycles'/'synthetic-test-cycle'
 path.mkdir(parents=True)
 def write(p,v):p.write_text(json.dumps(v))
 manifest=dict(c,mode='REAL',view_order=['V0','D1','D3'])
 write(path/'context.json',dict(manifest=manifest,calibration=dict(calibration_id='TEST_GEOMETRY')))
 block=dict(brick_type='2x2x1',color='blue',x=6,y=6,layer=1,orientation_deg=0)
 observed=dict(check_id=c['check_id'],observation_seq=c['observation_seq'],status='OK',visible_blocks=[block],
  verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in range(1,6)],reason=None)
 if fault=='partial':observed.update(status='UNOBSERVABLE',visible_blocks=[],verified_regions=[],reason='TEST_OCCLUSION')
 for view in manifest['view_order']:
  (path/view).mkdir()
  write(path/view/'metadata.json',dict(mode='REAL',view_id=view,check_id=c['check_id'],
   observation_seq=c['observation_seq'],calibration_id='TEST_GEOMETRY',scene_id='SYNTHETIC_PROTOCOL_FIXTURE',
   captured_at=datetime.now(timezone.utc).isoformat()))
 write(path/'observed.json',observed)
 if fault=='archive':
  archived=json.loads(json.dumps(observed));archived['visible_blocks'][0]['x']=7
  write(path/'observed.json',archived)
 if fault=='wrong_id':observed['check_id']='closed-check'
 send(dict(kind='RESULT',check_id=c['check_id'],observed=observed,diagnostics={}))
except Exception as error:
 send(dict(kind='ERROR',check_id=c['check_id'],reason=str(error)));sys.exit(1)
'''


class Motion:
    def __init__(self, cancelled, fault):
        self.cancelled, self.fault = cancelled, fault
        self.views, self.stops, self.released = [], 0, False

    def state(self, check_id, view):
        stopped = not (view == 'D3' and self.fault == 'd3_motion')
        return dict(stopped_verified=stopped, sample=dict(posx=[0., 0., 300., 0., 180., 0.],
            velx=[0.] * 6 if stopped else [5.01] * 6), position_error_mm=0.,
            orientation_error_deg=0., stillness=deepcopy(REAL_STILLNESS_TOLERANCES))

    def confirm(self, check_id, view, settings, review_ref, *, allow_move=True):
        assert not self.cancelled.is_set()
        assert settings['route_reviewed'] and settings['stillness'] == REAL_STILLNESS_TOLERANCES
        self.views.append(view if allow_move else 'START_HOME')
        if not allow_move and self.fault == 'handoff':
            return dict(stopped_verified=False, sample={})
        if view == 'D3' and self.fault == 'cancel': self.cancelled.set()
        return dict(stopped_verified=not (view == 'HOME' and allow_move and self.fault == 'home'), sample={})

    def stop(self):
        self.stops += 1
        return dict(motion_status=0)


def install(tmp_path, monkeypatch, fault='normal'):
    monkeypatch.setattr(initial, 'ROOT', tmp_path)
    config = dict(integration_scope='INITIAL_ONLY_ROUND3_DRIVER_NO_ASSEMBLY',
        stillness_policy_ref='app.cad_real_trial.REAL_STILLNESS_TOLERANCES',
        calibration_id='TEST_GEOMETRY', settings='settings.yaml', calibration='calibration.json',
        weights='weights.pt', views=json.loads((ROOT/'interfaces/round3_initial_inspection.json').read_text())['views'],
        arrival=dict(position_mm=1., orientation_deg=1.),
        joint_motion=dict(velocity_deg_s=23., acceleration_deg_s2=23., timeout_s=240.))
    (tmp_path/'settings.yaml').write_text('geometry:\n  calibration_id: TEST_GEOMETRY\n')
    (tmp_path/'calibration.json').write_text(json.dumps(dict(calibration_id='TEST_GEOMETRY')))
    (tmp_path/'weights.pt').write_bytes(b'EXPLICIT_TEST_MODEL_NOT_LOADED')
    config_path = tmp_path/'inspection.json'
    config_path.write_text(json.dumps(config))
    settings = initial.load_settings(config_path)
    cancelled = Event()
    motion = Motion(cancelled, fault)
    @contextmanager
    def open_motion(*args):
        try: yield motion
        finally: motion.released = True
    monkeypatch.setattr(initial, 'open_motion', open_motion)
    def observer(*args, **kwargs):
        def process(*ignored, **fields):
            return subprocess.Popen([sys.executable, '-u', '-c', SCRIPT, str(tmp_path), fault], **fields)
        return DockerBObserver(*args, **kwargs, process_factory=process)
    monkeypatch.setattr(initial, 'DockerBObserver', observer)
    return settings, cancelled, motion


def test_initial_b_owns_current_then_home_and_writer_release(tmp_path, monkeypatch):
    settings, cancelled, motion = install(tmp_path, monkeypatch)
    result = initial.run_initial(settings, tmp_path/'logs/run', review_ref='TEST_OPERATOR', cancelled=cancelled)
    assert result['status'] == 'INITIAL_CAPTURED_HOME_RETURNED', result
    assert result['current']['current_revision'] == 1 and len(result['current']['blocks']) == 1
    assert motion.views == ['V0', 'D1', 'D3', 'HOME'] and motion.stops == 0
    assert motion.released and result['writer_released'] and result['home_return_verified']
    assert result['assembly_steps_executed'] == 0 and result['gripper_commands'] == 0
    observed, evidence = load_initial_capture(result['initial_capture_directory'])
    assert observed['visible_blocks'] == result['current']['blocks']
    assert evidence['check_id'] == result['request']['check_id']
    assert json.loads((tmp_path/'logs/run/b-response.json').read_text())['status'] == 'OK'


@pytest.mark.parametrize('fault', ['partial', 'wrong_id', 'd3_motion', 'home', 'cancel', 'archive'])
def test_failure_or_cancel_never_claims_ready_or_starts_assembly(tmp_path, monkeypatch, fault):
    settings, cancelled, motion = install(tmp_path, monkeypatch, fault)
    result = initial.run_initial(settings, tmp_path/'logs/run', review_ref='TEST_OPERATOR', cancelled=cancelled)
    assert result['status'] == 'HOLD' and result['reason']
    assert result['writer_released'] and motion.released and motion.stops == 1
    assert not result['home_return_verified']
    assert result['assembly_steps_executed'] == 0 and result['gripper_commands'] == 0
    if fault in ('home', 'archive'): assert result['current'] is not None
    else:
        assert result['current'] is None and 'HOME' not in motion.views
    if fault == 'd3_motion':
        path = next((tmp_path/'logs/run/inspection-state-failures').glob('D3-*.json'))
        value = json.loads(path.read_text())
        assert value['view'] == 'D3' and value['state']['sample']['velx'][0] == 5.01
    if fault == 'archive': assert 'HOME' not in motion.views


def test_source_or_calibration_error_is_detected_before_connection(tmp_path, monkeypatch):
    settings, _, _ = install(tmp_path, monkeypatch)
    (tmp_path/'calibration.json').write_text(json.dumps(dict(calibration_id='other')))
    with pytest.raises(ValueError, match='CALIBRATION'):
        initial.load_settings(tmp_path/'inspection.json')


def test_preview_and_incomplete_run_do_not_construct_motion(monkeypatch, capsys):
    def forbidden(*args): raise AssertionError('must not connect a physical device')
    monkeypatch.setattr(initial, 'open_motion', forbidden)
    assert initial.main(['preview']) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['physical_commands'] == 0 and value['device_connections'] == 0
    with pytest.raises(SystemExit) as error:
        initial.main(['run', '--execute'])
    assert error.value.code == 2


@pytest.mark.parametrize('fault', ['normal', 'create_node', 'system'])
def test_real_writer_lock_and_partial_ros_cleanup_without_devices(tmp_path, monkeypatch, fault):
    import app
    monkeypatch.setattr(app, '__path__', list(app.__path__))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(initial, 'ROOT', tmp_path)
    config_path = tmp_path/'robot_control_integration/interfaces/assembly_contact_trial.json'
    config_path.parent.mkdir(parents=True)
    robot_id = 'initial-test-' + tmp_path.name
    config_path.write_text(json.dumps(dict(connection=dict(robot_id=robot_id, ros_domain_id=20))))
    monkeypatch.setenv('ROS_DOMAIN_ID', '20')
    events, stopped = [], Event()
    def create_node(name):
        if fault == 'create_node': raise RuntimeError('TEST_NODE_FAILURE')
        return SimpleNamespace(destroy_node=lambda: events.append('node.destroy'))
    ros = SimpleNamespace(init=lambda **_:events.append('ros.init'), create_node=create_node,
        ok=lambda:True, shutdown=lambda:events.append('ros.shutdown'))
    class Executor:
        def __init__(self, **_): pass
        def add_node(self, node): pass
        def spin(self): stopped.wait()
        def shutdown(self):
            events.append('executor.shutdown')
            stopped.set()
    class Driver:
        def __init__(self, *args, **kwargs): events.append('driver.open')
        def robot_system(self): return 1 if fault == 'system' else 0
        def close(self): events.append('driver.close')
    for name, value in {
        'rclpy':ros,
        'rclpy.executors':SimpleNamespace(MultiThreadedExecutor=Executor),
        'rclpy.signals':SimpleNamespace(SignalHandlerOptions=SimpleNamespace(NO=0)),
        'app.assembly_motion_ros':SimpleNamespace(AssemblyMotionRos=Driver),
        'app.inspection_motion':SimpleNamespace(InspectionMotion=lambda *args:SimpleNamespace()),
    }.items(): monkeypatch.setitem(sys.modules, name, value)
    lock_path = Path('/tmp/c2-assembly-' + robot_id + '.lock')
    try:
        with lock_path.open('a') as writer:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError):
                with initial.open_motion({}, Event()): pass
        assert events == []
        if fault == 'normal':
            with initial.open_motion({}, Event()):
                with pytest.raises(BlockingIOError):
                    with initial.open_motion({}, Event()): pass
            assert events == ['ros.init', 'driver.open', 'driver.close',
                              'executor.shutdown', 'node.destroy', 'ros.shutdown']
        else:
            with pytest.raises((RuntimeError, ValueError)):
                with initial.open_motion({}, Event()): pass
            assert events[-1] == 'ros.shutdown'
            assert ('driver.close' in events) == (fault == 'system')
        with lock_path.open('a') as writer:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        lock_path.unlink(missing_ok=True)
