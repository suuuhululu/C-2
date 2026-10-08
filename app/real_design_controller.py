"""현장에서 검증한 네 공급열을 기존 한 블록 실행/증거 처리에 연결한다."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.contracts import _integer, _object, _text
from app.hmi_contracts import SUPPLY_COLUMNS, _column
from app.real_trial_hmi import RealTrialController
from app.robot_trial import load_trial_config, prepare_plan, resolve_config_path, validate_trial_config


def load_workflow_rows(path):
    manifest = _object(json.loads(Path(path).read_text()),
        ("config_id", "mode", "base_config", "measurements_path", "measurements_sha256", "supply_rows"), "workflow")
    _text(manifest["config_id"], "workflow.config_id")
    if manifest["mode"] != "REAL":
        raise ValueError("workflow.mode: explicit REAL required")
    for field in ("base_config", "measurements_path"):
        manifest[field] = resolve_config_path(manifest[field], path)
    base = load_trial_config(manifest["base_config"])
    measurement_path = Path(manifest["measurements_path"])
    if hashlib.sha256(measurement_path.read_bytes()).hexdigest() != manifest["measurements_sha256"]:
        raise ValueError("workflow.measurements: changed source; review required")
    measurements = json.loads(measurement_path.read_text())["lines"]
    rows = {}
    for entry in manifest["supply_rows"]:
        row = _object(entry, ("brick_type", "color", "first_slot", "return_route_verified"), "workflow.row")
        column = _column(row, "workflow.row")
        _integer(row["first_slot"], 1, 6, "workflow.row.first_slot")
        if row["return_route_verified"] is not True or column in rows:
            raise ValueError("workflow.row: verified route and unique column required")
        studs = 4 if row["brick_type"] == "2x2x1" else 6
        measured = measurements[f"{row['color']}_{studs}"]
        config = deepcopy(base)
        config.update(config_id=f"{manifest['config_id']}:{row['color']}:{studs}", slot=row["first_slot"],
            pick_line=dict(brick_type=row["brick_type"], color=row["color"], start=measured["start"],
                end=measured["end"], measurements_path=str(measurement_path),
                measurements_sha256=manifest["measurements_sha256"]))
        config = validate_trial_config(config)
        if not all(flag for name, flag in config["confirmations"].items() if name != "empty_place_and_slot"):
            raise ValueError("workflow: onsite/setup/return confirmation required")
        prepare_plan(config)  # 원본 경로/hash만 확인한다. ROS 연결 또는 이동 없음.
        rows[column] = config
    if set(rows) != SUPPLY_COLUMNS:
        raise ValueError("workflow: all four Day4 rows required")
    return deepcopy(manifest), rows


class RealDesignController(RealTrialController):
    def __init__(self, manifest_path, log_directory, **kwargs):
        self.manifest_path = Path(manifest_path)
        self.manifest, self.rows = load_workflow_rows(self.manifest_path)
        self.slots = {column: config["slot"] for column, config in self.rows.items()}
        self.plan_columns = None
        column = next(iter(self.rows))
        super().__init__(self.manifest["base_config"], log_directory,
                         brick_type=column[0], color=column[1], slot=self.slots[column], **kwargs)

    @property
    def state(self):
        state = super().state
        selected = self.target["brick_type"], self.target["color"]
        state["config_id"] = self.manifest["config_id"]
        for row in state["supply"]:
            column = row["brick_type"], row["color"]
            slot = self._next_slot if column == selected else self.slots[column]
            row.update(next_slot=slot, needs_refill=slot is None)
        if self._attempts == 0 and self._ready:
            state["trial_notice"] = ((self._notice + "\n" if self._prepare_attempted else "") +
                "네 공급열 지정 슬롯부터 준비 · 시작은 조립판 비움 확인. 전달판은 B의 새 관측 후 진행.")
        elif self._ready:
            state["trial_notice"] = "전달·observe 복귀 확인. B의 조립/전달판 관측을 기다립니다."
        return state

    @property
    def configuration(self):
        return dict(workflow=deepcopy(self.manifest), rows=deepcopy(list(self.rows.values())))

    def _read_config(self):
        manifest, rows = load_workflow_rows(self.manifest_path)
        if manifest != self.manifest or rows != self.rows:
            raise ValueError("CONFIG_CHANGED_RECHECK_REQUIRED")
        return deepcopy(rows[self.target["brick_type"], self.target["color"]])

    def prepare_design_plan(self, plan):
        """전체 Plan을 첫 전달 전에 검사한다. 실제 재고 수량을 추정하지 않는다."""
        if self._operation is not None or self._stop or self._fault or not self._ready:
            raise ValueError("REAL_PLAN_ROBOT_NOT_READY")
        columns = [(step["after"]["brick_type"], step["after"]["color"]) for step in plan["steps"]]
        for column in set(columns):
            if column not in self.slots:
                raise ValueError(f"UNVERIFIED_TARGET: {column}")
        self._read_config()
        # 재계획은 남은 전달만 바꾼다. 전달 시도·확인된 집기·공급 순서는 초기화하지 않는다.
        self.plan_columns = (self.plan_columns or [])[:self._attempts] + columns
        self._limit = self._attempts + len(columns)

    def new_job(self, config=None):
        if config is not None or not self._ready or self._operation or self._stop or self._fault:
            return dict(accepted=False, reason="REAL_WORKFLOW_NOT_READY")
        try:
            if self._read_config() != self._checked_config:
                return dict(accepted=False, reason="CONFIG_CHANGED_RECHECK_REQUIRED")
        except (OSError, ValueError) as error:
            return dict(accepted=False, reason=str(error))
        self.slots[self.target["brick_type"], self.target["color"]] = self._next_slot
        # START confirms an empty assembly board; it does not refill supply rows.
        self._attempts = 0
        self._used = self._pick_confirmed = self._released = self._returned = False
        self._identity = self._final = None
        self.plan_columns = None
        self._config = deepcopy(self._checked_config)
        return dict(accepted=True, reason=None)

    def supply_refilled(self, brick_type, color):
        column = _column(dict(brick_type=brick_type, color=color), "robot.refill")
        if not self._ready or self._operation or self._stop or self._fault:
            return dict(accepted=False, reason="NOT_READY_AT_OBSERVE")
        selected = self.target["brick_type"], self.target["color"]
        slot = self._next_slot if column == selected else self.slots[column]
        if slot is not None:
            return dict(accepted=False, reason="REFILL_NOT_REQUIRED")
        self.slots[column] = 1
        if column == selected:
            self._next_slot = 1
        return dict(accepted=True, reason=None)

    def deliver(self, value):
        goal = _object(value, ("execution_id", "brick_type", "color"), "robot.goal")
        _text(goal["execution_id"], "robot.goal.execution_id")
        column = _column(goal, "robot.goal")
        if goal["execution_id"] in self._seen:
            return dict(accepted=False, reason="DUPLICATE")
        if self._operation is not None:
            return dict(accepted=False, reason="BUSY")
        if not self._ready or self._fault or self.plan_columns is None or self._attempts >= len(self.plan_columns):
            return dict(accepted=False, reason="REAL_TRIAL_NOT_READY")
        if column != self.plan_columns[self._attempts]:
            return dict(accepted=False, reason="PLAN_TARGET_MISMATCH")
        try:
            self._read_config()
        except (OSError, ValueError) as error:
            return dict(accepted=False, reason=str(error))
        old = self.target["brick_type"], self.target["color"]
        self.slots[old] = self._next_slot
        if self.slots[column] is None:
            return dict(accepted=False, reason="NEEDS_REFILL")
        self.target = dict(brick_type=column[0], color=column[1], slot=self.slots[column])
        self._next_slot = self.slots[column]
        self._checked_config = deepcopy(self.rows[column])
        self._config = deepcopy(self._checked_config)
        self._config["slot"] = self.target["slot"]
        # 새 EMPTY와 현장 준비 입력을 받은 deliver에서만 실행 복사본을 확인한다.
        self._config["confirmations"]["empty_place_and_slot"] = True
        return super().deliver(goal)
