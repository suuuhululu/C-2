"""Callable D/B boundary; transport-neutral, not a ROS Service or robot authority."""
from copy import deepcopy
from threading import RLock

from .main import process, validate_config


class SupplyRequestSession:
    """One active request; cancellation can invalidate inference already in flight."""

    def __init__(self, model, config, now_ns):
        self._model = model
        self._config = deepcopy(config)
        self._now_ns = now_ns  # Same clock as ROS RGB header stamps.
        self._active = None
        self._seen = set()
        self._running = False
        self._lock = RLock()

    def submit(self, request):
        request = deepcopy(request)
        validate_config(self._config, request)
        if request.get('mode') not in ('TEST', 'REAL'):
            raise ValueError('explicit TEST/REAL mode required')
        if (request['view_id'] != self._config['view_id']
                or request['config_id'] != self._config['config_id']
                or request['stopped'] is not True):
            raise ValueError('observation/config mismatch or stop not confirmed')
        now = self._now_ns()
        if not request['not_before_ns'] <= now < request['expires_at_ns']:
            raise ValueError('request inactive or expired')
        with self._lock:
            if request['request_id'] in self._seen:
                raise ValueError('duplicate_or_closed_request')
            if self._active is not None or self._running:
                raise ValueError('request_busy')
            self._seen.add(request['request_id'])
            self._active = request
        return {'request_id': request['request_id'], 'status': 'WAITING_FOR_RGB'}

    def cancel(self, request_id):
        with self._lock:
            self._require_active(request_id)
            self._active = None
        return {'request_id': request_id, 'status': 'CANCELLED'}

    def expire(self, request_id):
        """Call from a transport timer; frame absence must not become EMPTY."""
        with self._lock:
            request = self._require_active(request_id)
            if self._now_ns() < request['expires_at_ns']:
                raise ValueError('request_not_expired')
            self._active = None
        return {'request_id': request_id, 'status': 'TIMEOUT', 'reason': 'request_expired'}

    def _require_active(self, request_id):
        if self._active is None or self._active['request_id'] != request_id:
            raise ValueError('request_not_active')
        return self._active

    def observe(self, request_id, frame, stamp_ns):
        """Return a fresh result once; exceptions preserve errors and close failed inference."""
        with self._lock:
            request = deepcopy(self._require_active(request_id))
            now = self._now_ns()
            if (type(stamp_ns) is not int or not request['not_before_ns'] < stamp_ns
                    <= now < request['expires_at_ns']):
                raise ValueError('stale_future_or_expired_frame')
            if self._running:
                raise ValueError('inference_busy')
            self._running = True
        try:
            result = process(frame.copy(), self._model, self._config, request, stamp_ns)
            with self._lock:
                self._require_active(request_id)  # Cancel/timeout while inference ran.
                if self._now_ns() >= request['expires_at_ns']:
                    raise ValueError('request_expired_during_inference')
                self._active = None
            result['mode'] = request['mode']
            return result
        except Exception:
            with self._lock:
                if self._active is not None and self._active['request_id'] == request_id:
                    self._active = None
            raise
        finally:
            with self._lock:
                self._running = False
