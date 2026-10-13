"""Stage-bound operator gestures; never measure assembly alignment or completion."""
from copy import deepcopy
from pathlib import Path
import threading
import time
from uuid import uuid4

from app.handover_pose_preview import PosePreview


class OperatorGestureInput:
    def __init__(self, runtime, record, *, clock=time.monotonic):
        self.runtime, self.record, self.clock = runtime, record, clock
        self.monitor_id = str(uuid4())
        self.stop_preview = PosePreview(open_hold_ns=1_000_000_000)
        self.confirmed_requests = set()
        self.watermark = None

    @property
    def binding(self):
        plan = self.runtime.plan or {}
        return {k:plan.get(k) for k in ('plan_id','step_id','current_revision')}

    @property
    def request(self):
        r = self.runtime
        request = deepcopy(r.request)
        if request is not None:
            return dict(request, source_epoch=r.session.value['source_epoch'])
        return dict(request_id=self.monitor_id, kind='STOP_MONITOR',
            execution_id=r.session.value['execution_id'] if r.session else self.monitor_id,
            source_epoch=r.session.value['source_epoch'] if r.session else self.monitor_id)

    def gesture(self, row, now_ns):
        received = row.get('received_monotonic_ns')
        r = self.runtime
        synthetic = row.get('provenance') == 'SYNTHETIC'
        if (row.get('provenance') not in ('SENSOR', 'SYNTHETIC')
                or synthetic and getattr(getattr(r, 'raw', None), 'mode', None) != 'MOCK'
                or type(received) is not int or not 0 <= now_ns-received <= 300_000_000
                or self.watermark is not None and received <= self.watermark):
            return
        self.watermark = received
        identity = r.session.value['execution_id'] if r.session else self.monitor_id
        if (row.get('execution_id') != identity or r.session and
                row.get('source_epoch') != r.session.value['source_epoch']):
            return
        request = r.request
        hands = row.get('hands', [])
        source = 'FAKE' if synthetic else 'SENSOR'
        active = (r.state == 'RUNNING' and request is not None and
                  row.get('preview_request_id') == request['request_id'])
        if request and request['kind'] == 'RECEIVE':
            # Open palm means receive only during this stopped handover request.
            # Keep fresh hand presence until release; an old latch cannot open.
            self.stop_preview.evaluate([], received, row.get('source_ns', 0),
                                       row.get('frame'), ('INACTIVE', identity))
            if not active:
                return
            opened = len(hands) == 1 and hands[0].get('pose') == 'OPEN_HAND'
            if not opened:
                self.confirmed_requests.discard(request['request_id'])
            ready = opened and (request['request_id'] in self.confirmed_requests or
                row.get('candidate_event') == 'OPEN_HAND_HELD_ORIENTATION_UNKNOWN' and
                row.get('continuity_estimate') is True)
            if ready:
                self.confirmed_requests.add(request['request_id'])
            signal = dict(request, sequence=r.signal_seq+1, source=source,
                verified=ready, hand_present=bool(hands), receiving_ready=ready,
                observed_monotonic_s=received/1e9)
        else:
            if getattr(r,'handover_active',False) and len(hands)==1 and hands[0].get('pose')=='OPEN_HAND':
                self.stop_preview.evaluate([],received,row.get('source_ns',0),row.get('frame'),('INACTIVE',identity))
                return
            stopped = self.stop_preview.evaluate(hands, received, row.get('source_ns', 0),
                row.get('frame'), ('OPEN_GRIPPER', identity))
            if stopped['candidate_event'] == 'OPEN_HAND_HELD_ORIENTATION_UNKNOWN':
                if getattr(r,'request_handover',lambda:False)():
                    self.stop_preview.evaluate([],received,row.get('source_ns',0),row.get('frame'),('INACTIVE',identity))
                    self.record('GESTURE_HANDOVER_REQUESTED',dict(execution_id=identity,hold_seconds=1.,actual_stop_verified=False))
                    return
                # 손바닥은 항상 인계 의도다. 인계 불가 상태를 STOP 명령으로 바꾸지 않는다.
                self.record('GESTURE_HANDOVER_UNAVAILABLE', dict(execution_id=identity,
                    hold_seconds=1., state=r.state, actual_stop_verified=False))
                return
            if (not active or request['kind'] not in ('ALIGNMENT_READY', 'HELP_READY', 'ASSEMBLY_ACK')
                    or request['request_id'] in self.confirmed_requests
                    or row.get('candidate_event') != 'THUMBS_UP_HELD'
                    or len(hands) != 1 or hands[0].get('pose') != 'THUMBS_UP'
                    or row.get('continuity_estimate') is not True):
                return
            signal = dict(request, sequence=r.signal_seq+1, source=source, verified=True,
                ready=True, observed_monotonic_s=received/1e9,
                confirmation_kind='OPERATOR_GESTURE_NOT_ALIGNMENT_MEASUREMENT')
        try:
            r.accept_signal(signal)
        except (RuntimeError, ValueError) as error:
            if str(error) not in ('NO_ACTIVE_SIGNAL_REQUEST', 'STALE_SIGNAL'):
                raise
            self.record('GESTURE_RESPONSE_IGNORED', dict(reason=str(error), request_id=request['request_id']))
            return
        if request['kind'] != 'RECEIVE':
            self.confirmed_requests.add(request['request_id'])
        self.record('GESTURE_READY_CONFIRMED', dict(request_id=request['request_id'],
            execution_id=identity, kind=request['kind'], source=source,
            ready=signal.get('ready', signal.get('receiving_ready')),
            pose_verified=row.get('pose_verified', False), assembly_alignment_measured=False))


class IntegrationGestureCamera:
    def __init__(self, node, runtime, record, output, *, topic='/camera/color/image_raw'):
        from app.control_camera import RequestCamera
        root = Path(__file__).resolve().parents[1]
        self.runtime, self.record = runtime, record
        self.ending, self.ready = threading.Event(), threading.Event()
        self.error = None
        self.camera = RequestCamera(node,OperatorGestureInput(runtime,record),
            model=root/'logs/handover/stage02/hand_landmarker.task',
            model_deps=root/'logs/handover/model-deps',topic=topic,transport='raw',
            record=record,output=output,question_hold_seconds=2.,open_hold_seconds=1.)
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.thread.start()
        if not self.ready.wait(6) or self.error:
            self.close()
            raise RuntimeError(self.error or 'GESTURE_RGB_NOT_RECEIVED')
        record('GESTURE_CAMERA_READY',dict(topic=topic,thumb_seconds=2.,stop_seconds=1.,
            purpose='OPERATOR_INPUT_NOT_B_VISION'))

    def run(self):
        begin = time.monotonic()
        try:
            while not self.ending.wait(.03):
                latest = self.camera.latest
                if latest is None:
                    if time.monotonic()-begin > 5:raise RuntimeError('GESTURE_RGB_NOT_RECEIVED')
                    continue
                if time.monotonic_ns()-latest[1] > 1_000_000_000:
                    raise RuntimeError('GESTURE_RGB_STALLED')
                self.camera.poll()
                self.ready.set()
        except Exception as error:
            self.error = str(error)
            self.runtime.stop()
            self.record('GESTURE_CAMERA_FAILED',dict(reason=self.error,actual_stop_verified=False))
            self.ready.set()

    def close(self):
        self.ending.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():raise RuntimeError('GESTURE_CAMERA_SHUTDOWN_PENDING')
        self.camera.close()
