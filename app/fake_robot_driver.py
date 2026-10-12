"""수동 성공 확인을 제공하는 Fake driver. 실제 pose·통신·장치 호출 없음."""

from copy import deepcopy

from app.contracts import _text


class FakeRobotDriver:
    mode = "FAKE"

    def __init__(self, *, ready_at_observe: bool, on_request=None):
        if type(ready_at_observe) is not bool:
            raise ValueError("FakeRobotDriver.ready_at_observe: expected boolean")
        self.ready_at_observe = ready_at_observe
        self.calls = []
        self._confirmations = {}
        self._active_request = None
        self._failures = {}
        self._stops = {}
        self._stop_request = None
        self.block_state = "UNPICKED"
        self._on_request = on_request

    def request(self, operation: str, payload: dict, completed, *, failed) -> None:
        if operation not in ("pick", "place", "observe"):
            raise ValueError("FakeRobotDriver.operation: unsupported request")
        key = payload["execution_id"], operation
        self.calls.append((operation, deepcopy(payload)))
        self._confirmations[key] = completed
        self._failures[key] = failed
        self._active_request = key
        if operation == "pick":
            self.block_state = "UNPICKED"
        self.ready_at_observe = False
        if self._on_request:
            self._on_request(operation, deepcopy(payload))

    def confirm(self, execution_id: str, operation: str) -> bool:
        key = execution_id, operation
        if key not in self._confirmations:
            raise ValueError("FakeRobotDriver: no matching requested operation")
        if key == self._active_request and self._stop_request is None:
            self._active_request = None
            if operation == "pick":
                self.block_state = "HOLDING"
            elif operation == "place":
                self.block_state = "RELEASED"
            if operation == "observe":
                self.ready_at_observe = True
        # callback을 보관해 실제처럼 중복/늦은 성공을 전달할 수 있게 한다.
        return self._confirmations[key](execution_id, operation)

    def fail(self, execution_id: str, operation: str, reason: str) -> bool:
        _text(reason, "FakeRobotDriver.failure.reason")
        key = execution_id, operation
        if key not in self._failures:
            raise ValueError("FakeRobotDriver: no matching requested operation")
        if key == self._active_request:
            self._active_request = None
            self.ready_at_observe = False
        return self._failures[key](execution_id, operation, reason)

    def stop(self, request_id: str, completed) -> None:
        self.calls.append(("stop", dict(request_id=request_id)))
        self._stops[request_id] = completed
        self._stop_request = request_id
        self.ready_at_observe = False
        if self._on_request:
            self._on_request("stop", dict(request_id=request_id))

    def confirm_stop(self, request_id: str, *, stopped: bool, execution_ended: bool,
                     block_state_known: bool, block_state: str) -> bool:
        result = self._stops[request_id](request_id, stopped=stopped, execution_ended=execution_ended,
                                       block_state_known=block_state_known, block_state=block_state)
        if result and stopped and execution_ended and block_state_known and block_state != "UNKNOWN":
            self._active_request = None
            self._stop_request = None
            self.block_state = block_state
        return result

    def confirm_cleanup(self, *, ready_at_observe: bool, gripper_empty: bool) -> None:
        if any(type(flag) is not bool for flag in (ready_at_observe, gripper_empty)):
            raise ValueError("Fake cleanup: expected boolean evidence")
        if self._stop_request is not None or self._active_request is not None:
            raise ValueError("Fake cleanup: stop is not confirmed")
        self.ready_at_observe = ready_at_observe
        self.block_state = "UNPICKED" if gripper_empty else "HOLDING"
