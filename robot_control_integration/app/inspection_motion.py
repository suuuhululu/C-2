"""Inspection-only moves inside D's existing locked physical process."""
from copy import deepcopy
import math
from threading import Event, Lock
import time

from app.assembly_motion import motion_still, pose_error, vector
from scripts.assembly_position_trial import guard


class InspectionMotion:
    def __init__(self, raw, connection, *, clock=time.monotonic, sleep=time.sleep):
        self.raw, self.connection = raw, connection
        self.clock, self.sleep = clock, sleep
        self.cancelled = Event()
        self.command_lock = Lock()
        self.sample_lock = Lock()
        self.identity = self.view = self.settings = None

    def stop(self):
        self.cancelled.set()
        with self.command_lock:
            self.raw.stop()
        count = 0
        deadline = self.clock()+self.raw.config['timing']['stop_timeout_s']
        while self.clock() < deadline:
            with self.sample_lock:
                value = self.raw.sample()
            guard(value, self.connection, None, automatic=True, required_gripper_status=0)
            count = count+1 if motion_still(value, self.settings['stillness']) else 0
            if count >= 3:
                return value
            self.sleep(.05)
        raise TimeoutError('INSPECTION_STOP_NOT_VERIFIED')

    def sample(self):
        with self.sample_lock:
            if self.cancelled.is_set():
                raise RuntimeError('INSPECTION_CANCELED')
            value = self.raw.sample()
        guard(value, self.connection, None, automatic=True, required_gripper_status=0)
        if self.cancelled.is_set():
            raise RuntimeError('INSPECTION_CANCELED')
        return value

    def state(self, check_id, view):
        if (check_id, view) != (self.identity, self.view):
            raise ValueError('INACTIVE_INSPECTION_VIEW')
        value = self.sample()
        mm, deg = pose_error(value['posx'], self.settings['views'][view]['posx'])
        tolerance = self.settings['arrival']
        still = motion_still(value, self.settings['stillness'])
        return dict(sample=value, stopped_verified=still and
                    mm <= tolerance['position_mm'] and deg <= tolerance['orientation_deg'],
                    checked_monotonic_ns=time.monotonic_ns(), motion_still=still,
                    position_error_mm=mm, orientation_error_deg=deg,
                    arrival=deepcopy(tolerance), stillness=deepcopy(self.settings['stillness']))

    def confirm(self, check_id, view, settings, review_ref, *, allow_move=True):
        if not isinstance(review_ref, str) or not review_ref or view not in ('HOME','V0','D1','D3'):
            raise ValueError('INSPECTION_ROUTE_REVIEW_REQUIRED')
        if settings.get('route_reviewed') is not True:
            raise ValueError('INSPECTION_ROUTE_REVIEW_REQUIRED')
        target = settings['views'][view]
        posj = vector(target['posj'], 6, 'inspection posj')
        posx = None if view=='HOME' else vector(target['posx'],6,'inspection posx')
        rates = settings['joint_motion']
        if any(type(rates[k]) not in (int, float) or not math.isfinite(rates[k]) or rates[k] <= 0
               for k in ('velocity_deg_s', 'acceleration_deg_s2', 'timeout_s')):
            raise ValueError('INSPECTION_MOTION_RATES_REQUIRED')
        for key in ('position_mm', 'orientation_deg'):
            if not 0 < settings['arrival'][key] <= 1:
                raise ValueError('INSPECTION_ARRIVAL_TOLERANCE_REQUIRED')
        self.identity, self.view, self.settings = check_id, view, deepcopy(settings)
        moved = False
        try:
            first = self.sample()
            if not motion_still(first, settings['stillness']):
                raise RuntimeError('INSPECTION_REQUIRES_STOPPED_EMPTY_ROBOT')
            # User-supplied TCP/joint pairs must agree with this robot's actual TCP/FK.
            fk = self.raw.call('motion/fkin', 'Fkin', pos=posj, ref=0).conv_posx
            from app.assembly_motion_ros import response_vector
            fk_pose=response_vector(fk,'inspection FK')
            if view=='HOME':
                # HOME is the user's joint teaching; derive its TCP with this actual Tool/TCP.
                posx=fk_pose
                self.settings['views']['HOME']['posx']=posx
            mm, deg = pose_error(fk_pose, posx)
            if mm > settings['arrival']['position_mm'] or deg > settings['arrival']['orientation_deg']:
                raise ValueError('INSPECTION_TAUGHT_TCP_JOINT_MISMATCH')
            current = self.state(check_id, view)
            if not current['stopped_verified']:
                if not allow_move:
                    raise RuntimeError('INSPECTION_START_HOME_REQUIRED')
                with self.command_lock:
                    if self.cancelled.is_set():
                        raise RuntimeError('INSPECTION_CANCELED')
                    moved = True
                    self.raw.call('motion/move_joint', 'MoveJoint', pos=posj,
                        vel=rates['velocity_deg_s'], acc=rates['acceleration_deg_s2'],
                        time=0., radius=0., mode=0, blend_type=0, sync_type=1)
            deadline = self.clock()+rates['timeout_s']
            samples = 0
            while self.clock() < deadline:
                result = self.state(check_id, view)
                samples = samples+1 if result['stopped_verified'] else 0
                if samples >= 3:
                    return dict(result, check_id=check_id, view=view, review_ref=review_ref)
                self.sleep(.05)
            raise TimeoutError('INSPECTION_VIEW_ARRIVAL_TIMEOUT')
        except Exception:
            self.cancelled.set()
            if moved:
                with self.command_lock:
                    self.raw.stop()
            raise
