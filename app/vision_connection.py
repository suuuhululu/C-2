"""B의 비동기 결과를 Qt thread의 D callback으로 전달한다. 관측을 생성하지 않는다."""

from copy import deepcopy

from PyQt5.QtCore import QObject, Qt, pyqtSignal

from app.contracts import _object


class VisionConnection(QObject):
    observation_received = pyqtSignal(object)
    place_received = pyqtSignal(object)
    failure_received = pyqtSignal(str, str)

    def __init__(self, backend, publish):
        super().__init__()
        self.backend, self.publish = backend, publish
        self.handler = None
        self.observation_received.connect(self._observation, Qt.QueuedConnection)
        self.place_received.connect(self._place, Qt.QueuedConnection)
        self.failure_received.connect(self._failure, Qt.QueuedConnection)

    def bind(self, handler):
        if not callable(handler) or self.handler is not None:
            raise ValueError("B request handler must be bound once")
        self.handler = handler

    @property
    def connected(self):
        return self.handler is not None

    def request(self, payload):
        if not self.connected:
            raise ValueError("VISION_NOT_CONNECTED")
        state = self.backend.state
        purpose = "CURRENT" if state["current_check"] else "ASSEMBLY" if payload["after"] is not None else "PLACE"
        self.handler(dict(deepcopy(payload), purpose=purpose))

    def submit_observation(self, value):
        self.observation_received.emit(deepcopy(value))

    def submit_place(self, value):
        self.place_received.emit(deepcopy(value))

    def submit_failure(self, check_id, reason):
        self.failure_received.emit(check_id, reason)

    def _observation(self, value):
        try:
            self.backend.on_observation(value)
        except (ValueError, KeyError, TypeError) as error:
            self._invalid(value, error)
        self.publish()

    def _place(self, value):
        try:
            value = _object(value, ("check_id", "observation_seq", "status", "reason"), "place")
            self.backend.on_place(**value)
        except (ValueError, KeyError, TypeError) as error:
            self._invalid(value, error)
        self.publish()

    def _invalid(self, value, error):
        identity = value.get("check_id") if isinstance(value, dict) else None
        if isinstance(identity, str) and identity:
            self.backend.on_failure("vision", identity, "B_RESULT_INVALID: " + str(error))
        else:
            # 식별 없는 결과로 현재의 다른 요청을 실패 처리하지 않는다.
            self.backend._event("B_RESULT_REJECTED", reason="MISSING_CHECK_ID")

    def _failure(self, check_id, reason):
        self.backend.on_failure("vision", check_id, reason)
        self.publish()
