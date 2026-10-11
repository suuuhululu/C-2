"""외부 설정을 사용하는 Fake 전달·슬롯·정지/재개. 실제 장치 호출 없음."""

from copy import deepcopy
import json
from pathlib import Path

from app.contracts import _array, _integer, _object, _text
from app.hmi_contracts import LEGACY_SUPPLY_COLUMNS, SUPPLY_COLUMNS, _column


def validate_robot_config(value: object) -> dict:
    config = _object(value, ("config_id", "mode", "slot_count", "supply_rows",
                             "place_point", "observe_point"), "robot.config")
    if config["mode"] != "FAKE":
        raise ValueError("robot.config.mode: explicit FAKE mode required")
    for field in ("config_id", "place_point", "observe_point"):
        _text(config[field], f"robot.config.{field}")
    _integer(config["slot_count"], 1, 6, "robot.config.slot_count")
    columns = set()
    for index, value in enumerate(_array(config["supply_rows"], "robot.config.supply_rows")):
        path = f"robot.config.supply_rows[{index}]"
        row = _object(value, ("brick_type", "color", "supply_point"), path)
        column = _column(row, path)
        _text(row["supply_point"], f"{path}.supply_point")
        if column in columns:
            raise ValueError(f"{path}: duplicate supply column")
        columns.add(column)
    if columns not in (LEGACY_SUPPLY_COLUMNS, SUPPLY_COLUMNS):
        raise ValueError("robot.config.supply_rows: expected all Day4 supply columns")
    return deepcopy(config)


def load_robot_config(path: str | Path) -> dict:
    """지정한 파일을 검사한다. 누락/잘못된 파일을 기본 설정으로 바꾸지 않는다."""
    return validate_robot_config(json.loads(Path(path).read_text(encoding="utf-8")))


class RobotController:
    def __init__(self, config: dict, driver, on_result, *, on_stopped=None, on_event=None):
        self._config = validate_robot_config(config)
        if driver.mode != "FAKE":
            raise ValueError("RobotController: explicit Fake driver required")
        self._driver, self._on_result = driver, on_result
        self._on_stopped = on_stopped
        self._on_event = on_event
        self._rows = {(row["brick_type"], row["color"]): row
                      for row in self._config["supply_rows"]}
        self._next_slots = {column: 1 for column in self._rows}
        self._requests = {}
        self._active = None
        self._stop = None
        self._fault = None

    @property
    def state(self) -> dict:
        return deepcopy(dict(mode=self._config["mode"], config_id=self._config["config_id"],
            active_execution=self._active,
            stop=self._stop, fault=self._fault,
            cleanup_ready=self._stop is not None and self._stop["confirmed"]
                          and self._driver.ready_at_observe and self._driver.block_state == "UNPICKED",
            ready_at_observe=self._active is None and self._stop is None and self._fault is None
                             and self._driver.ready_at_observe
                             and self._driver.block_state in ("UNPICKED", "RELEASED"),
            supply=[dict(brick_type=brick, color=color, next_slot=slot, needs_refill=slot is None)
                    for (brick, color), slot in self._next_slots.items()]))

    @property
    def configuration(self) -> dict:
        return deepcopy(self._config)

    def new_job(self, config=None) -> dict:
        settings = validate_robot_config(self._config if config is None else config)
        if not (self.state["ready_at_observe"] or self.state["cleanup_ready"]):
            return dict(accepted=False, reason="CONTROLLER_NOT_READY_AT_OBSERVE")
        self._config = settings
        self._rows = {(row["brick_type"], row["color"]): row for row in settings["supply_rows"]}
        self._next_slots = {column: 1 for column in self._rows}
        self._active = self._stop = self._fault = None
        # 새 시작은 초기 배치/공급판 채움의 명시 확인이다. 이전 ID는 계속 닫혀 있다.
        return dict(accepted=True, reason=None)

    def _note(self, event, identity):
        if self._on_event is None or self._on_event(event, identity, self.state):
            return True
        self._fault = "ROBOT_LOG_FAILED"
        return False

    def deliver(self, value: object) -> dict:
        goal = _object(value, ("execution_id", "brick_type", "color"), "robot.goal")
        _text(goal["execution_id"], "robot.goal.execution_id")
        column = _column(goal, "robot.goal")
        identity = goal["execution_id"]
        if identity in self._requests:
            reason = "DUPLICATE" if self._requests[identity] == goal else "EXECUTION_ID_CONFLICT"
            return dict(accepted=False, reason=reason)
        if self._active is not None:
            return dict(accepted=False, reason="BUSY")
        if self._stop is not None or self._fault is not None:
            return dict(accepted=False, reason="STOP_OR_FAULT_PENDING")
        if not self.state["ready_at_observe"]:
            return dict(accepted=False, reason="NOT_READY_AT_OBSERVE")
        if column not in self._next_slots:
            return dict(accepted=False, reason="UNCONFIGURED_SUPPLY_COLUMN")
        slot = self._next_slots[column]
        if slot is None:
            return dict(accepted=False, reason="NEEDS_REFILL")
        self._requests[identity] = deepcopy(goal)
        self._active = dict(**deepcopy(goal), slot=slot, stage="pick", consumed=False)
        self._request("pick")
        return dict(accepted=True, reason=None)

    def _request(self, operation):
        active = self._active
        active["stage"] = operation
        payload = dict(execution_id=active["execution_id"], point=self._config[f"{operation}_point"]
                       if operation != "pick" else self._rows[active["brick_type"], active["color"]]["supply_point"])
        if operation == "pick":
            payload.update(brick_type=active["brick_type"], color=active["color"], slot=active["slot"])
        try:
            self._driver.request(operation, payload, self.on_confirmation, failed=self.on_failure)
        except Exception as error:
            self.on_failure(active["execution_id"], operation, f"DRIVER_CALL_FAILED: {error}")

    def _consume(self):
        active = self._active
        if not active["consumed"]:
            column = active["brick_type"], active["color"]
            slot = active["slot"]
            self._next_slots[column] = slot + 1 if slot < self._config["slot_count"] else None
            active["consumed"] = True

    def on_confirmation(self, execution_id: str, operation: str) -> bool:
        """Fake pick는 집어 올림 확인, observe는 도착/정지 확인을 뜻한다."""
        _text(execution_id, "robot.confirmation.execution_id")
        if operation not in ("pick", "place", "observe"):
            raise ValueError("robot.confirmation.operation: unsupported confirmation")
        active = self._active
        if (active is None or self._stop is not None or self._fault is not None
                or execution_id != active["execution_id"] or operation != active["stage"]):
            return False
        if operation == "pick":
            self._consume()
            if self._note("ROBOT_PICK_CONFIRMED", execution_id):
                self._request("place")
        elif operation == "place":
            if self._note("ROBOT_PLACE_CONFIRMED", execution_id):
                self._request("observe")
        else:
            if not self._driver.ready_at_observe:
                return False
            if not self._note("ROBOT_OBSERVE_CONFIRMED", execution_id):
                return True
            self._active = None
            self._on_result(dict(execution_id=execution_id, success=True, reason=None))
        return True

    def on_failure(self, execution_id: str, operation: str, reason: str) -> bool:
        _text(reason, "robot.failure.reason")
        active = self._active
        if (active is None or self._stop is not None or self._fault is not None
                or active["execution_id"] != execution_id or active["stage"] != operation):
            return False
        # timeout도 정지/미집기의 증거가 아니다. 활성 실행을 보존해 STOP으로 확인한다.
        self._fault = reason
        self._on_result(dict(execution_id=execution_id, success=False, reason=reason))
        return True

    def stop(self, value: object) -> dict:
        request = _object(value, ("request_id", "execution_id"), "robot.stop")
        _text(request["request_id"], "robot.stop.request_id")
        if request["execution_id"] is not None:
            _text(request["execution_id"], "robot.stop.execution_id")
        if self._stop is not None:
            return dict(accepted=False, reason="STOP_ALREADY_REQUESTED")
        active = self._active
        if active is not None and request["execution_id"] not in (None, active["execution_id"]):
            return dict(accepted=False, reason="OLD_EXECUTION")
        self._stop = dict(request_id=request["request_id"], confirmed=False, block_state="UNKNOWN",
                          previous_execution_id=active["execution_id"] if active else request["execution_id"])
        self._driver.stop(request["request_id"], self.on_stop_confirmation)
        return dict(accepted=True, reason=None)

    def on_stop_confirmation(self, request_id: str, *, stopped: bool, execution_ended: bool,
                             block_state_known: bool, block_state: str) -> bool:
        if any(type(flag) is not bool for flag in (stopped, execution_ended, block_state_known)):
            raise ValueError("robot.stop confirmation: expected booleans")
        if block_state not in ("UNPICKED", "HOLDING", "RELEASED", "UNKNOWN"):
            raise ValueError("robot.stop.block_state: unsupported value")
        if self._stop is None or request_id != self._stop["request_id"] or self._stop["confirmed"]:
            return False
        known = block_state_known and block_state != "UNKNOWN"
        active = self._active
        # 확인된 집기와 모순되는 미집기 증거로 슬롯을 되돌리거나 재집기하지 않는다.
        if active and active["consumed"] and block_state == "UNPICKED":
            known = False
        if (active is None or active["slot"] is None) and block_state == "HOLDING":
            known = False
        confirmed = stopped and execution_ended and known
        if confirmed:
            if active and active["slot"] is not None and block_state in ("HOLDING", "RELEASED"):
                consumed = active["consumed"]
                self._consume()
                if not consumed:
                    self._note("ROBOT_PICK_CONFIRMED", active["execution_id"])
            self._stop.update(confirmed=True, block_state=block_state)
        if self._on_stopped:
            self._on_stopped(request_id, stopped=stopped, execution_ended=execution_ended,
                             block_state_known=known)
        return confirmed

    def resume(self, value: object) -> dict:
        request = _object(value, ("execution_id", "previous_execution_id", "goal"), "robot.resume")
        identity, previous, goal = request["execution_id"], request["previous_execution_id"], request["goal"]
        _text(identity, "robot.resume.execution_id")
        if previous is not None:
            _text(previous, "robot.resume.previous_execution_id")
        if goal is not None:
            goal = _object(goal, ("execution_id", "brick_type", "color"), "robot.resume.goal")
            _column(goal, "robot.resume.goal")
            if goal["execution_id"] != identity:
                raise ValueError("robot.resume.goal: execution_id differs")
        if identity in self._requests:
            return dict(accepted=False, reason="DUPLICATE")
        if self._stop is None or not self._stop["confirmed"] or self._fault:
            return dict(accepted=False, reason="STOP_OR_FAULT_UNCONFIRMED")
        if previous != self._stop["previous_execution_id"]:
            return dict(accepted=False, reason="OLD_EXECUTION")
        active, block_state = self._active, self._stop["block_state"]
        delivery = active is not None and active["slot"] is not None
        if delivery:
            if goal is None or any(goal[key] != active[key] for key in ("brick_type", "color")):
                return dict(accepted=False, reason="GOAL_CONFLICT")
            active["execution_id"] = identity
        elif goal is not None:
            return dict(accepted=False, reason="GOAL_CONFLICT")
        else:
            self._active = dict(execution_id=identity, slot=None, consumed=False, stage="observe")
        self._requests[identity] = deepcopy(goal)
        self._stop = None
        self._request({"UNPICKED":"pick", "HOLDING":"place", "RELEASED":"observe"}[block_state]
                      if delivery else "observe")
        return dict(accepted=True, reason=None)

    def supply_refilled(self, brick_type: str, color: str) -> dict:
        column = _column(dict(brick_type=brick_type, color=color), "robot.refill")
        if not self.state["ready_at_observe"]:
            return dict(accepted=False, reason="NOT_READY_AT_OBSERVE")
        if column not in self._next_slots:
            return dict(accepted=False, reason="UNCONFIGURED_SUPPLY_COLUMN")
        if self._next_slots[column] is not None:
            return dict(accepted=False, reason="REFILL_NOT_REQUIRED")
        # 예외 운영 입력이다. Backend가 현재 Job과 해당 열을 확인해 호출한다.
        self._next_slots[column] = 1
        return dict(accepted=True, reason=None)
