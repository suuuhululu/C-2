"""INITIAL only: existing B Docker observer and round3 D driver, no assembly."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import sys
from threading import Event, Lock, Thread
import time
from types import SimpleNamespace
from uuid import uuid4

import yaml

from app.cad_real_trial import REAL_STILLNESS_TOLERANCES
from app.docker_b_observer import DockerBObserver
from app.round3_approved_step import load_initial_capture, same_blocks
from perception.perception_mvp.main import inspection_view_order
from perception.perception_mvp.team_connection import connect_inspection

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'interfaces/round3_initial_inspection.json'


def load_settings(path):
    settings = json.loads(Path(path).read_text())
    if (settings.get('integration_scope') != 'INITIAL_ONLY_ROUND3_DRIVER_NO_ASSEMBLY'
            or settings.get('stillness_policy_ref') != 'app.cad_real_trial.REAL_STILLNESS_TOLERANCES'
            or set(settings['views']) != {'HOME', 'V0', 'D1', 'D3'}
            or inspection_view_order('INITIAL') != ['V0', 'D1', 'D3']):
        raise ValueError('ROUND3_THREE_VIEW_INITIAL_CONFIGURATION_REQUIRED')
    for view, target in settings['views'].items():
        for field in (('posj',) if view == 'HOME' else ('posj', 'posx')):
            values = target[field]
            if (len(values) != 6 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
                raise ValueError('INITIAL_FINITE_TAUGHT_POSE_REQUIRED: ' + view)
    if (set(settings['joint_motion']) != {'velocity_deg_s', 'acceleration_deg_s2', 'timeout_s'}
            or any(type(settings['arrival'][k]) not in (int, float)
                   or not 0 < settings['arrival'][k] <= 1 for k in ('position_mm', 'orientation_deg'))
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                   for v in settings['joint_motion'].values())):
        raise ValueError('INITIAL_EXISTING_MOTION_LIMITS_REQUIRED')
    for name in ('settings', 'calibration', 'weights'):
        path = (ROOT / settings[name]).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('INITIAL_LOCAL_SOURCE_REQUIRED: ' + name)
    config = yaml.safe_load((ROOT / settings['settings']).read_text())
    calibration = json.loads((ROOT / settings['calibration']).read_text())
    if not settings['calibration_id'] == config['geometry']['calibration_id'] == calibration['calibration_id']:
        raise ValueError('INITIAL_CALIBRATION_MISMATCH')
    # Use the existing round3 state contract, rather than round2's exact-zero velocity.
    settings['stillness'] = deepcopy(REAL_STILLNESS_TOLERANCES)
    return settings


@contextmanager
def open_motion(settings, cancelled):
    import app
    native = ROOT / 'robot_control_integration'
    app.__path__.append(str(native / 'app'))
    sys.path.insert(0, str(native))
    from app.assembly_motion_ros import AssemblyMotionRos
    from app.inspection_motion import InspectionMotion
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.signals import SignalHandlerOptions

    config = json.loads((native / 'interfaces/assembly_contact_trial.json').read_text())
    if os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_REAL_DOMAIN_REQUIRED')
    lock_path = '/tmp/c2-assembly-' + config['connection']['robot_id'] + '.lock'
    with open(lock_path, 'a') as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        driver = node = executor = thread = None
        initialized = False
        try:
            rclpy.init(args=[], signal_handler_options=SignalHandlerOptions.NO)
            initialized = True
            node = rclpy.create_node('round3_initial_inspection')
            executor = MultiThreadedExecutor(num_threads=2)
            executor.add_node(node)
            thread = Thread(target=executor.spin, daemon=True)
            thread.start()
            driver = AssemblyMotionRos(config, node=node)
            if driver.robot_system() != 0:
                raise ValueError('PHYSICAL_ROBOT_REQUIRED')
            motion = InspectionMotion(driver, config['connection'])
            motion.cancelled, motion.settings = cancelled, deepcopy(settings)
            yield motion
        finally:
            try:
                if driver is not None:
                    driver.close()
            finally:
                if executor is not None:
                    executor.shutdown()
                if thread is not None and thread.ident is not None:
                    thread.join()
                if node is not None:
                    node.destroy_node()
                if initialized and rclpy.ok():
                    rclpy.shutdown()


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


def run_initial(settings, directory, *, review_ref, cancelled, timeout_s=900.):
    if not isinstance(review_ref, str) or not review_ref.strip():
        raise ValueError('INITIAL_OPERATOR_REVIEW_REQUIRED')
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError('INITIAL_POSITIVE_TIMEOUT_REQUIRED')
    directory = Path(directory).resolve()
    if not directory.is_relative_to(ROOT / 'logs'):
        raise ValueError('INITIAL_OUTPUT_MUST_BE_UNDER_CHECKOUT_LOGS')
    directory.mkdir(parents=True, exist_ok=False)
    settings = deepcopy(settings)
    settings['route_reviewed'] = True
    request = dict(check_id=str(uuid4()), check_kind='INITIAL', plan_id=None, step_id=None)
    result = dict(status='HOLD', request=request, current=None, home_return_verified=False,
        writer_released=False, actual_stop_verified=False, assembly_steps_executed=0,
        gripper_commands=0, output_directory=str(directory), reason=None, operator_review_ref=review_ref)
    write(directory / 'settings.json', settings)
    journal_lock = Lock()

    def record(event, data):
        with journal_lock, (directory / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(event=event, data=data, unix_s=time.time()),
                ensure_ascii=False, allow_nan=False) + '\n')

    active = lambda: not cancelled.is_set()
    try:
        if not active():
            raise RuntimeError('INITIAL_CANCELED_BEFORE_DEVICE_CONNECTION')
        with open_motion(settings, cancelled) as motion:
            connection = None

            def state(check_id, view, valid):
                if check_id != request['check_id'] or not valid():
                    raise RuntimeError('INITIAL_CANCELED_OR_STALE')
                value = motion.state(check_id, view)
                if value['stopped_verified'] is not True:
                    failures = directory / 'inspection-state-failures'
                    failures.mkdir(exist_ok=True)
                    write(failures / f'{view}-{time.monotonic_ns()}.json',
                        dict(check_id=check_id, view=view, state=value))
                return value

            def confirm(check_id, view, valid):
                if check_id != request['check_id'] or not valid():
                    raise RuntimeError('INITIAL_CANCELED_OR_STALE')
                value = motion.confirm(check_id, view, settings, review_ref)
                record('VIEW_ARRIVAL', dict(check_id=check_id, view=view, state=value))
                return value['stopped_verified'] is True and valid()

            def pose(check_id, view, valid):
                value = state(check_id, view, valid)
                if value['stopped_verified'] is not True:
                    raise RuntimeError('INITIAL_VIEW_NOT_STOPPED')
                return dict(posx=value['sample']['posx'], basis='LIVE_D_INSPECTION_STATE',
                            check_id=check_id, view=view)

            controller = SimpleNamespace(confirm_view=confirm, robot_pose=pose,
                is_stopped=lambda check, view, valid: state(check, view, valid)['stopped_verified'] is True)
            try:
                if not active():
                    raise RuntimeError('INITIAL_CANCELED')
                observer = DockerBObserver(ROOT, controller, settings=ROOT / settings['settings'],
                    calibration=ROOT / settings['calibration'], weights=ROOT / settings['weights'],
                    output=directory / 'b')
                inbox = Queue()
                connection = connect_inspection(inbox.put, geometry_reference=settings['calibration_id'],
                    observe=lambda context, valid: observer(context, lambda: valid() and active()))
                connection.request(request)
                deadline = time.monotonic() + timeout_s
                while active():
                    if time.monotonic() >= deadline:
                        raise TimeoutError('INITIAL_CHECK_TIMEOUT')
                    try:
                        response = inbox.get(timeout=.1)
                        break
                    except Empty:
                        continue
                else:
                    raise RuntimeError('INITIAL_CANCELED')
                if not active() or any(response[k] != request[k] for k in request):
                    raise ValueError('INITIAL_RESPONSE_CANCELED_OR_STALE')
                result['current'] = deepcopy(response['current'])
                write(directory / 'b-response.json', response)
                if response['status'] != 'OK' or response['current'] is None:
                    raise ValueError(response['reason'] or 'INITIAL_CURRENT_UNAVAILABLE')
                archives = list((directory / 'b' / request['check_id'] / 'cycles').glob('*/observed.json'))
                if len(archives) != 1:
                    raise ValueError('INITIAL_SINGLE_CAPTURE_ARCHIVE_REQUIRED')
                observed, evidence = load_initial_capture(archives[0].parent)
                if (evidence['check_id'] != request['check_id']
                        or evidence['geometry_reference'] != settings['calibration_id']
                        or not same_blocks(observed['visible_blocks'], result['current']['blocks'])):
                    raise ValueError('INITIAL_ARCHIVE_CHECK_MISMATCH')
                result.update(initial_capture_directory=evidence['source_directory'], source=evidence)
                if not confirm(request['check_id'], 'HOME', active):
                    raise ValueError('INITIAL_HOME_RETURN_NOT_CONFIRMED')
                result.update(status='INITIAL_CAPTURED_HOME_RETURNED', home_return_verified=True,
                    actual_stop_verified=True, capture_expires_unix_s=evidence['captured_unix_s'] + 300)
            except Exception as error:
                result.update(status='HOLD', reason=str(error))
            finally:
                cancelled.set()
                if result['status'] != 'INITIAL_CAPTURED_HOME_RETURNED':
                    try:
                        result['stop_sample'] = motion.stop()
                        result['actual_stop_verified'] = True
                    except Exception as error:
                        result['stop_error'] = str(error)
                if connection is not None:
                    connection.close()
                    # Do not release the writer while a B callback may still use D.
                    connection._worker.join()
        result['writer_released'] = True
    except Exception as error:
        result.update(status='HOLD', reason=str(error))
    write(directory / 'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preview', 'run'), nargs='?', default='preview')
    parser.add_argument('--inspection-config', type=Path, default=DEFAULT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-route-reviewed', action='store_true')
    parser.add_argument('--confirm-empty-gripper', action='store_true')
    parser.add_argument('--confirm-hand-clear', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'run' and not all((args.execute, args.confirm_route_reviewed,
                                        args.confirm_empty_gripper, args.confirm_hand_clear)):
        parser.error('run requires --execute --confirm-route-reviewed --confirm-empty-gripper --confirm-hand-clear')
    settings = load_settings(args.inspection_config)
    if args.command == 'preview':
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION', device_connections=0,
            physical_commands=0, view_order=inspection_view_order('INITIAL'), settings=settings), indent=2))
        return 0
    cancelled = Event()
    previous = {sig:signal.signal(sig, lambda *_:cancelled.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        directory = args.output or ROOT / 'logs/round3-initial' / str(uuid4())
        result = run_initial(settings, directory, review_ref='OPERATOR_INITIAL_' + str(uuid4()), cancelled=cancelled)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'INITIAL_CAPTURED_HOME_RETURNED' and result['writer_released'] else 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
