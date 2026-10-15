"""Actual STEP/FINAL camera observation through the existing round3 D driver."""
from copy import deepcopy
import json
from pathlib import Path
from threading import Event, Lock
import time
from types import SimpleNamespace

from app.docker_b_observer import DockerBObserver
from app.round3_initial_inspection import open_motion, write


class LiveInspectionObserver:
    """B owns comparison/Current; this callable owns only D/camera resources."""
    def __init__(self, root, settings, output, review_ref):
        self.root, self.output = Path(root).resolve(), Path(output).resolve()
        if not self.output.is_relative_to(self.root / 'logs'):
            raise ValueError('LIVE_INSPECTION_OUTPUT_MUST_BE_UNDER_CHECKOUT_LOGS')
        if not isinstance(review_ref, str) or not review_ref.strip():
            raise ValueError('LIVE_INSPECTION_OPERATOR_REVIEW_REQUIRED')
        self.settings, self.review_ref = deepcopy(settings), review_ref
        self.settings['route_reviewed'] = True
        self.outcomes = {}

    def __call__(self, context, active):
        if context['check_kind'] not in ('STEP', 'FINAL'):
            raise ValueError('LIVE_INSPECTION_STEP_OR_FINAL_REQUIRED')
        if context['geometry_reference'] != self.settings['calibration_id']:
            raise ValueError('LIVE_INSPECTION_GEOMETRY_MISMATCH')
        directory = self.output / context['check_id']
        directory.mkdir(parents=True, exist_ok=False)
        outcome = dict(check_id=context['check_id'], status='HOLD', home_return_verified=False,
            writer_released=False, actual_stop_verified=False, reason=None)
        self.outcomes[context['check_id']] = outcome
        write(directory / 'inspection-settings.json', dict(self.settings, operator_review_ref=self.review_ref))
        local_cancel = Event()
        token = SimpleNamespace(is_set=lambda:local_cancel.is_set() or active() is not True,
                                set=local_cancel.set)
        journal_lock = Lock()

        def record(name, data):
            with journal_lock, (directory / 'd-events.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(event=name, data=data, unix_s=time.time()),
                    allow_nan=False, ensure_ascii=False) + '\n')

        try:
            if token.is_set():
                raise RuntimeError('LIVE_INSPECTION_CANCELED_BEFORE_CONNECTION')
            failure = None
            with open_motion(self.settings, token) as motion:
                def require(check_id, view, valid):
                    if check_id != context['check_id'] or view not in ('V0', 'D1', 'D3', 'HOME') or not valid():
                        raise RuntimeError('LIVE_INSPECTION_CANCELED_OR_STALE')

                def state(check_id, view, valid):
                    require(check_id, view, valid)
                    value = motion.state(check_id, view)
                    if value['stopped_verified'] is not True:
                        write(directory / f'{view}-state-failure-{time.monotonic_ns()}.json', value)
                    return value

                def confirm(check_id, view, valid):
                    require(check_id, view, valid)
                    value = motion.confirm(check_id, view, self.settings, self.review_ref)
                    record('VIEW_ARRIVAL', dict(check_id=check_id, view=view, state=value))
                    if view == 'HOME':
                        outcome['home_sample'] = deepcopy(value)
                    return value['stopped_verified'] is True and valid() is True

                def pose(check_id, view, valid):
                    value = state(check_id, view, valid)
                    if value['stopped_verified'] is not True:
                        raise RuntimeError('LIVE_INSPECTION_VIEW_NOT_STOPPED')
                    return dict(posx=value['sample']['posx'], basis='LIVE_D_INSPECTION_STATE',
                                check_id=check_id, view=view)

                controller = SimpleNamespace(confirm_view=confirm, robot_pose=pose,
                    is_stopped=lambda check, view, valid:state(check, view, valid)['stopped_verified'] is True)
                try:
                    # Native seating ends above assembly with an empty closed pad.
                    # Until that handoff is commissioned, never invent an opening or
                    # a return path. This HOME check only reads actual D feedback.
                    start = motion.confirm(context['check_id'], 'HOME', self.settings,
                        self.review_ref, allow_move=False)
                    record('START_HOME_VERIFIED', start)
                    if start['stopped_verified'] is not True:
                        raise RuntimeError('LIVE_INSPECTION_START_HOME_REQUIRED')
                    observer = DockerBObserver(self.root, controller,
                        settings=self.root / self.settings['settings'],
                        calibration=self.root / self.settings['calibration'],
                        weights=self.root / self.settings['weights'], output=self.output)
                    observed, diagnostics = observer(context, active)
                    if not confirm(context['check_id'], 'HOME', active):
                        raise RuntimeError('LIVE_INSPECTION_HOME_RETURN_NOT_CONFIRMED')
                    outcome.update(home_return_verified=True, actual_stop_verified=True)
                except Exception as error:
                    failure = error
                    try:
                        outcome['stop_sample'] = motion.stop()
                        outcome['actual_stop_verified'] = True
                    except Exception as error:
                        outcome['stop_error'] = str(error)
            outcome['writer_released'] = True
            if failure is not None:
                raise failure
            outcome['status'] = 'CAPTURED_HOME_RETURNED'
            if active() is not True:
                raise RuntimeError('LIVE_INSPECTION_CANCELED_AFTER_CAPTURE')
            return observed, diagnostics
        except Exception as error:
            outcome.update(status='HOLD', reason=str(error))
            raise
        finally:
            write(directory / 'd-result.json', outcome)
