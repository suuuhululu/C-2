"""Single-PC D bridge adapter. Actual sensing/motion is supplied by a real runtime."""
from copy import deepcopy
from importlib import import_module
import os
from queue import Queue
from threading import RLock, Thread

from .backend_adapter import deliver_observed
from .contracts import validate_block
from .inspection import VisionInspection


def connect_inspection(submit_result, *, observe, geometry_reference, initial_current=None,
                       display_sink=None):
    """10/8 entry point: D binds request/cancel/load_plan explicitly.

    submit_result must enqueue into D's owning thread (not mutate Qt/Backend here).
    observe(context, is_active) supplies real six-field Observed after safe capture.
    No legacy bridge method is silently reinterpreted as a new inspection channel.
    """
    if not callable(submit_result) or not callable(observe):
        raise ValueError('actual observe and D result callback required')
    if not isinstance(geometry_reference, str) or not geometry_reference:
        raise ValueError('geometry reference required')
    if display_sink is not None and not callable(display_sink):
        raise ValueError('display_sink must enqueue into the display owner thread')
    connection = InspectionConnection(submit_result, observe, geometry_reference, initial_current, display_sink)
    connection._worker.start()
    return connection


def connect_real_inspection(submit_result, *, gate, hand_detector, weights, calibration,
                            config, detector_confidence, scene_id, output_root,
                            confirm_view, is_stopped, robot_pose, workflow_valid,
                            bundle_valid, initial_current=None, display_sink=None):
    """Wire actual ROS capture into B's inspection worker, not a fixture runtime.

    Controller supplies arrival/stop/pose and interruption hooks. confirm_view
    may wait for movement but must return only after the actual View is stopped.
    STOP closes workflow_valid/bundle_valid AND cancels the active check in D.
    This function never issues movement or treats cancellation as physical stop.
    """
    from pathlib import Path
    from .main import make_inspection_observer
    from .ros_capture import capture_inspection_view

    hooks = (confirm_view, is_stopped, robot_pose, workflow_valid, bundle_valid)
    if not all(callable(hook) for hook in hooks):
        raise ValueError('actual Controller stop/pose/continuity hooks required')
    if not isinstance(scene_id, str) or not scene_id.strip():
        raise ValueError('actual scene_id required')
    if not Path(weights).is_file():
        raise ValueError('actual block weights file required')
    profile = calibration['calibration_id']
    if config['calibration_id'] != profile or set(calibration['views']) != {'V0', 'D1', 'D3'}:
        raise ValueError('three View calibration and Geometry IDs must agree')
    calibration, config = deepcopy(calibration), deepcopy(config)

    def capture(manifest, view, active):
        valid = lambda: active() is True and workflow_valid() is True and bundle_valid() is True
        return capture_inspection_view(manifest, view, valid,
            output_root=Path(output_root) / 'captures', scene_id=scene_id,
            calibration_id=profile, robot_pose=robot_pose, is_stopped=is_stopped)

    observer = make_inspection_observer(gate, hand_detector, None, capture,
        weights, calibration, config, detector_confidence,
        confirm_view=confirm_view, workflow_valid=workflow_valid,
        bundle_valid=bundle_valid, is_stopped=is_stopped,
        output_root=Path(output_root) / 'cycles')
    return connect_inspection(submit_result, observe=observer,
        geometry_reference=profile, initial_current=initial_current,
        display_sink=display_sink)


class InspectionConnection:
    """Serial B state owner, asynchronous capture, synchronous cancel boundary."""
    def __init__(self, submit_result, observe, geometry_reference, current, display_sink=None):
        self.submit_result, self.observe = submit_result, observe
        self.geometry_reference = geometry_reference
        self.inspection = VisionInspection(current)
        self._lock, self._queue = RLock(), Queue()
        self._active, self._closed, self._seen = None, False, {}
        self.last_delivery_error = None
        self._display_state = None
        self.display_sink = display_sink
        self.last_display_error = None
        self._worker = Thread(target=self._run, name='b-inspection-worker', daemon=True)

    def load_plan(self, design, plan, plan_base_current, *, geometry_reference):
        with self._lock:
            if self._closed or self._active is not None:
                raise ValueError('cancel before Plan replacement; connection must be open')
            if geometry_reference != self.geometry_reference:
                raise ValueError('geometry reference mismatch')
            self.inspection.load_plan(design, plan, plan_base_current,
                                      geometry_reference=geometry_reference)
            self._set_display(None)

    def comparison_display_state(self):
        """Local display snapshot, not an extension of the common result schema."""
        with self._lock:
            return deepcopy(self._display_state)

    def _set_display(self, state):
        self._display_state = deepcopy(state)
        if self.display_sink is not None:
            try:
                self.display_sink(deepcopy(state))
            except Exception as error:
                self.last_display_error = str(error)
                self._display_state = None

    @staticmethod
    def _failure(request, status, reason):
        return dict(**request, status=status, comparison=None, current=None, expected=None,
                    difference=None, observation=None, reason=reason)

    def _publish(self, response):
        try:
            self.submit_result(deepcopy(response))
        except Exception as error:
            # Transport failure is not a canceled/failed B state transaction.
            self.last_delivery_error = dict(check_id=response['check_id'], error=str(error),
                                           response=deepcopy(response))

    def request(self, value):
        if not isinstance(value, dict) or set(value) != {'check_id', 'check_kind', 'plan_id', 'step_id'}:
            raise ValueError('inspection request requires exactly check_id/check_kind/plan_id/step_id')
        request = deepcopy(value)
        if not isinstance(request['check_id'], str) or not request['check_id'].strip():
            raise ValueError('nonempty check_id required')
        kind = request['check_kind']
        if kind not in ('INITIAL', 'STEP', 'FINAL'):
            raise ValueError('unsupported check kind')
        for field in ('plan_id', 'step_id'):
            if request[field] is not None and (not isinstance(request[field], str) or not request[field]):
                raise ValueError('invalid inspection identifier')
        if (kind == 'INITIAL' and (request['plan_id'] is not None or request['step_id'] is not None) or
            kind != 'INITIAL' and request['plan_id'] is None or
            kind == 'STEP' and request['step_id'] is None or
            kind == 'FINAL' and request['step_id'] is not None):
            raise ValueError('invalid kind/Plan/Step binding')
        with self._lock:
            if self._closed:
                raise ValueError('inspection connection closed')
            identity = request['check_id']
            if identity in self._seen:
                if self._seen[identity] != request:
                    raise ValueError('conflicting duplicate check_id')
                return  # Completed/canceled identical requests never trigger capture twice.
            if self._active is not None:
                raise ValueError('cancel current check before replacement')
            self._set_display(None)
            try:
                context = self.inspection.start_check(request, geometry_reference=self.geometry_reference)
            except (ValueError, LookupError) as error:
                self._seen[identity] = request
                self._publish(self._failure(request, 'ERROR', str(error)))
                return
            self._seen[identity], self._active = request, identity
            self._set_display(dict(**request, display_stage='OBSERVING',
                previous_current=deepcopy(context['current']), current=deepcopy(context['current']),
                expected=deepcopy(context['expected']), comparison=None))
            self._queue.put((request, dict(context, check_kind=kind, observation_seq=0,
                                           geometry_reference=self.geometry_reference)))

    def is_active(self, identity):
        with self._lock:
            return not self._closed and self._active == identity

    def cancel(self, identity):
        with self._lock:
            if self._display_state and self._display_state['check_id'] == identity:
                self._set_display(None)
            self.inspection.cancel(identity)
            if self._active == identity:
                self._active = None
                self._publish(self._failure(self._seen[identity], 'CANCELED', 'inspection canceled'))
            return True  # State commit rights are closed, not proof of Robot stop.

    def _run(self):
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                request, context = item
                identity = request['check_id']
                if not self.is_active(identity):
                    continue
                try:
                    observed, diagnostics = self.observe(deepcopy(context), lambda: self.is_active(identity))
                    if observed['check_id'] != identity or observed['observation_seq'] != context['observation_seq']:
                        raise ValueError('capture must retain bundle check_id/sequence')
                    with self._lock:
                        if not self.is_active(identity):
                            continue
                        result = self.inspection.finish_check(request, observed,
                            geometry_reference=self.geometry_reference, issues=diagnostics.get('issues', ()))
                        self._set_display(dict(**request,
                            display_stage='CONFIRMED' if result['comparison'] in ('MATCH', 'MISMATCH') else 'UNOBSERVABLE',
                            previous_current=deepcopy(result.get('previous_current')),
                            current=deepcopy(result['current']), expected=deepcopy(result['expected']),
                            comparison=result['comparison']))
                        comparison = result['comparison']
                        unavailable = comparison == 'UNOBSERVABLE' or (
                            request['check_kind'] == 'INITIAL' and (
                                observed['status'] == 'UNOBSERVABLE' or diagnostics.get('issues')))
                        if result['current'] is None:
                            raise ValueError('INITIAL_STATE_UNAVAILABLE: no confirmed Current; ' + str(observed['reason']))
                        response = dict(**request, status='UNOBSERVABLE' if unavailable else 'OK',
                            comparison=comparison, current=result['current'],
                            expected=None if request['check_kind'] == 'INITIAL' else dict(
                                plan_id=request['plan_id'], step_id=request['step_id'], blocks=result['expected']),
                            difference=result['difference'],
                            observation={k: deepcopy(observed[k]) for k in
                                ('observation_seq', 'visible_blocks', 'verified_regions', 'reason')},
                            reason=(observed['reason'] or 'insufficient observation evidence') if unavailable else observed['reason'])
                        self._active = None
                        self._publish(response)
                except Exception as error:
                    with self._lock:
                        if self.is_active(identity):
                            self._set_display(None)
                            self.inspection.cancel(identity)
                            self._active = None
                            self._publish(self._failure(request, 'ERROR', 'PROCESSING_FAILED: ' + str(error)))
            finally:
                self._queue.task_done()

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self._active is not None:
                self.cancel(self._active)
            self._closed = True
            self._set_display(None)
            self._queue.put(None)
        self._worker.join(timeout=1.)


def connect(bridge, *, process_request=None):
    """D entry point; never bind an unconfigured or synthetic producer.

    Runtime process_request(request, is_active) performs actual sensing and returns
    observation/place results. It must check is_active during hand waiting/motion.
    D DTOs remain unchanged; this worker does not read Backend from another thread.
    """
    if process_request is None:
        module = os.environ.get("B_PERCEPTION_RUNTIME_MODULE")
        if not module:
            raise ValueError("B_PERCEPTION_RUNTIME_MODULE required: actual capture/Controller runtime")
        process_request = import_module(module).process_request
    if not callable(process_request):
        raise ValueError("actual process_request must be callable")
    for name in ("bind", "submit_observation", "submit_place", "submit_failure"):
        if not callable(getattr(bridge, name, None)):
            raise ValueError("D bridge missing " + name)
    connection = TeamConnection(bridge, process_request)
    bridge.bind(connection.request)
    connection.start()
    return connection


class TeamConnection:
    def __init__(self, bridge, process_request):
        self.bridge, self.process_request = bridge, process_request
        self._queue, self._lock = Queue(), RLock()
        self._closed, self._active = False, None
        self._seen = {}
        self._worker = Thread(target=self._run, name="b-perception-worker", daemon=True)

    def start(self):
        self._worker.start()

    def request(self, value):
        identity = value.get("check_id") if isinstance(value, dict) else None
        if not isinstance(identity, str) or not identity:
            raise ValueError("B request requires nonempty check_id")
        try:
            if set(value) != {"check_id", "after", "purpose"}:
                raise ValueError("B request requires check_id/after/purpose")
            if value["purpose"] not in ("PLACE", "ASSEMBLY", "CURRENT"):
                raise ValueError("unsupported B request purpose")
            if value["purpose"] == "ASSEMBLY":
                validate_block(value["after"])
            elif value["after"] is not None:
                raise ValueError("PLACE/CURRENT after must be null")
            context = deepcopy(value)
            with self._lock:
                if self._closed:
                    raise ValueError("B connection closed")
                if identity in self._seen:
                    if context != self._seen[identity]:
                        raise ValueError("check_id reused with different request")
                    return
                self._seen[identity] = context
                self._active = identity
                self._queue.put(context)
        except (ValueError, KeyError, TypeError) as error:
            self.bridge.submit_failure(identity, "B_REQUEST_INVALID: " + str(error))

    def is_active(self, identity):
        with self._lock:
            return not self._closed and self._active == identity

    def cancel(self, identity):
        """Call on actual D closure/STOP; does not stop the Robot or release a hold."""
        with self._lock:
            if self._active == identity:
                self._active = None

    def _validate_results(self, request, results):
        expected = ({"place"} if request["purpose"] == "PLACE" else
                    {"observation"} if request["purpose"] == "CURRENT" else
                    {"observation", "place"})
        if not isinstance(results, dict) or set(results) != expected:
            raise ValueError("runtime must return all results for requested purpose")
        for value in results.values():
            if (not isinstance(value, dict) or value.get("check_id") != request["check_id"] or
                    type(value.get("observation_seq")) is not int or value["observation_seq"] != 0):
                raise ValueError("result must retain check_id and bundle-start sequence 0")
        if "observation" in results:
            deliver_observed(results["observation"], lambda value: None)
        if "place" in results:
            value = results["place"]
            if set(value) != {"check_id", "observation_seq", "status", "reason"}:
                raise ValueError("place requires exactly four D fields")
            if value["status"] not in ("EMPTY", "OCCUPIED", "UNOBSERVABLE"):
                raise ValueError("invalid place status")
            if ((value["status"] == "UNOBSERVABLE" and
                 (not isinstance(value["reason"], str) or not value["reason"])) or
                    (value["status"] != "UNOBSERVABLE" and value["reason"] is not None)):
                raise ValueError("invalid place status/reason")

    def _run(self):
        while True:
            request = self._queue.get()
            try:
                if request is None:
                    return
                identity = request["check_id"]
                if not self.is_active(identity):
                    continue
                context = dict(deepcopy(request), observation_seq=0)
                try:
                    results = self.process_request(context, lambda: self.is_active(identity))
                    self._validate_results(request, results)
                    with self._lock:
                        if not self.is_active(identity):
                            continue
                        if "observation" in results:
                            self.bridge.submit_observation(deepcopy(results["observation"]))
                        if "place" in results:
                            self.bridge.submit_place(deepcopy(results["place"]))
                        self._active = None
                except Exception as error:
                    # Propagate real sensing/transport errors, never fabricate EMPTY.
                    with self._lock:
                        if self.is_active(identity):
                            self.bridge.submit_failure(identity, "B_PROCESS_FAILED: " + str(error))
                            self._active = None
            finally:
                self._queue.task_done()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed, self._active = True, None
            self._queue.put(None)
        self._worker.join(timeout=1.)
