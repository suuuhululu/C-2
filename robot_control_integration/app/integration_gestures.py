"""Local operator gestures for the no-B trial; never measure assembly alignment."""
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
        if (row.get('provenance') != 'SENSOR' or type(received) is not int
                or not 0 <= now_ns-received <= 300_000_000
                or (self.watermark is not None and received <= self.watermark)):
            return
        self.watermark = received
        r = self.runtime
        identity = r.session.value['execution_id'] if r.session else self.monitor_id
        stopped = self.stop_preview.evaluate(row.get('hands'), received, row.get('source_ns',0),
            row.get('frame'), ('OPEN_GRIPPER',identity))
        if stopped['candidate_event'] == 'OPEN_HAND_HELD_ORIENTATION_UNKNOWN':
            self.record('GESTURE_STOP_REQUESTED', dict(execution_id=identity, hold_seconds=1.,
                assembly_alignment_measured=False, actual_stop_verified=False))
            r.stop()
            return
        hands = row.get('hands',[])
        if len(hands) != 1 or hands[0].get('pose') != 'OPEN_HAND':
            self.stop_preview.evaluate([],received,row.get('source_ns',0),row.get('frame'),('INACTIVE',identity))
        request = r.request
        if (r.state != 'RUNNING' or not request or request['kind'] != 'ALIGNMENT_READY'
                or request['request_id'] in self.confirmed_requests
                or row.get('preview_request_id') != request['request_id']
                or row.get('execution_id') != request['execution_id']
                or row.get('source_epoch') != r.session.value['source_epoch']
                or row.get('candidate_event') != 'THUMBS_UP_HELD'
                or row.get('continuity_estimate') is not True
                or now_ns-received > round(r.session.value['frame_max_age_s']*1e9)):
            return
        # This is the operator's readiness response, like the HMI button.
        # The landmark candidate remains unverified as geometric alignment evidence.
        try:
            r.accept_signal(dict(request, sequence=r.signal_seq+1, source='SENSOR', verified=True,
                ready=True, observed_monotonic_s=received/1e9,
                confirmation_kind='OPERATOR_GESTURE_NOT_ALIGNMENT_MEASUREMENT'))
        except (RuntimeError,ValueError) as error:
            if str(error) not in ('NO_ACTIVE_SIGNAL_REQUEST','STALE_SIGNAL'):
                raise
            self.record('GESTURE_RESPONSE_IGNORED',dict(reason=str(error),request_id=request['request_id']))
            return
        self.confirmed_requests.add(request['request_id'])
        self.record('GESTURE_READY_CONFIRMED',dict(request_id=request['request_id'],
            execution_id=request['execution_id'], hold_seconds=2.,
            pose_verified=row.get('pose_verified',False), assembly_alignment_measured=False))


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
