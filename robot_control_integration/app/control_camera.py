"""Camera candidate producer only. Has no arm/gripper clients or write API."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from app.handover_camera_test import image_array, frame_metadata
from app.handover_gesture_camera import stop_relay
from app.handover_pose_preview import PosePreview, shape_preview


class RequestCamera:
    def __init__(self, node, session, *, model, model_deps, topic, transport, record, output, open_hold_seconds=1., question_hold_seconds=2.):
        if type(open_hold_seconds) not in (int, float) or not .4 <= open_hold_seconds <= 5:
            raise ValueError('INVALID_CAMERA_OPEN_HOLD_SECONDS')
        if type(question_hold_seconds) not in (int,float) or not .4<=question_hold_seconds<=5:
            raise ValueError('INVALID_CAMERA_QUESTION_HOLD_SECONDS')
        self.preview = PosePreview(open_hold_ns=round(open_hold_seconds*1_000_000_000),
            question_hold_ns=round(question_hold_seconds*1_000_000_000))
        sys.path.insert(0, str(Path(model_deps).resolve()))
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Image
        self.np, self.mp, self.session, self.record = np, mp, session, record
        self.model = self.relay = self.relay_log = None
        self.latest, self.seen = None, None
        try:
            self.model = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model)), num_hands=2))
            if transport == 'theora':
                base = topic.removesuffix('/theora').rstrip('/')
                decoded = '/robot_control_trial/decoded_'+uuid4().hex
                self.relay_log = (Path(output)/'theora-relay.log').open('x')
                self.relay = subprocess.Popen(['ros2', 'run', 'image_transport', 'republish', '--ros-args',
                    '-p', 'in_transport:=theora', '-p', 'out_transport:=raw', '-r', 'in:='+base,
                    '-r', 'in/theora:='+base+'/theora', '-r', 'out:='+decoded,
                    '-r', '__node:=control_decoder_'+uuid4().hex], stdout=self.relay_log,
                    stderr=subprocess.STDOUT, start_new_session=True)
                topic = decoded
            node.create_subscription(Image, topic, self.receive, qos_profile_sensor_data)
        except BaseException:
            self.close()
            raise

    def receive(self, message):
        # Bind at reception, never relabel an old frame with the request active at inference.
        self.latest = (message, time.monotonic_ns(), deepcopy(self.session.request))

    def poll(self):
        if self.relay is not None and self.relay.poll() is not None:
            raise RuntimeError('THEORA_RELAY_EXITED')
        if self.latest is None:
            return None
        msg, received, req = self.latest
        if req is None or self.session.request is None or req['request_id'] != self.session.request['request_id']:
            return None
        meta = frame_metadata(msg, received)
        if meta['source_ns'] == self.seen or time.monotonic_ns()-received > 300_000_000:
            return None
        self.seen = meta['source_ns']
        rgb = image_array(msg)
        detected = self.model.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                                                    data=self.np.ascontiguousarray(rgb)))
        hands = [shape_preview([dict(x=p.x, y=p.y, z=p.z) for p in hand],
                              rgb.shape[1], rgb.shape[0]) for hand in detected.hand_landmarks]
        mode = 'OPEN_GRIPPER' if req['kind'] in ('RELEASE', 'TRAY_RELEASE', 'RECEIVE') else 'QUESTION'
        result = self.preview.evaluate(hands, received, meta['source_ns'], meta['frame'], (mode, req['request_id']))
        row = dict(result, **self.session.binding, execution_id=req['execution_id'],
                   source_epoch=req['source_epoch'], preview_request_id=req['request_id'],
                   received_monotonic_ns=received, capture_clock_verified=False,
                   pose_verified=False, orientation_verified=False, provenance='SENSOR',
                   real_output_enabled=False)
        row.update(source_ns=meta['source_ns'], frame=meta['frame'], hands=hands)
        self.record('CAMERA_CANDIDATE', row)
        self.session.gesture(row, time.monotonic_ns())
        return row

    def close(self):
        stop_relay(self.relay)
        if self.relay_log is not None:
            self.relay_log.close()
        if self.model is not None:
            self.model.close()
