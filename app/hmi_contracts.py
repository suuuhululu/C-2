"""Backend↔HMI 표시/입력 계약. 상태 생성·명령 실행·최신성 판정은 별도다."""

from copy import deepcopy

from .completion import _current
from .contracts import (
    _array, _block, _integer, _object, _text, validate_design, validate_observed,
)


WORKFLOW_STATUSES = (
    "IDLE", "PREPARING", "DELIVERING", "WAIT_ASSEMBLY", "WAIT_INTENT",
    "REPLANNING", "WAIT_CORRECTION", "HOLD", "STOPPED", "COMPLETE",
)
COMMAND_FIELDS = {
    "START": ("command",),
    "PREPARE_OBSERVE": ("command",),
    "STOP_PREPARATION": ("command",),
    "RESUME_PREPARATION": ("command",),
    "STOP": ("command", "job_id"),
    "RESUME": ("command", "job_id"),
    "CHOOSE_INTENT": ("command", "job_id", "request_id", "choice"),
    "CONTINUE_AFTER_CORRECTION": ("command", "job_id", "request_id"),
    "SUPPLY_REFILLED": ("command", "job_id", "brick_type", "color"),
}
SUPPLY_COLUMNS = {
    (brick, color) for brick in ("2x2x1", "2x3x1") for color in ("yellow", "blue")
}


def _nullable_text(value: object, path: str) -> None:
    if value is not None:
        _text(value, path)


def _boolean(value: object, path: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{path}: expected boolean")


def _column(value: dict, path: str) -> tuple[str, str]:
    if value["brick_type"] not in ("2x2x1", "2x3x1"):
        raise ValueError(f"{path}.brick_type: unsupported supply column")
    if value["color"] not in ("yellow", "blue"):
        raise ValueError(f"{path}.color: unsupported supply column")
    return value["brick_type"], value["color"]


def _button(value: object, path: str, fields=("visible", "enabled")) -> dict:
    button = _object(value, fields, path)
    for field in ("visible", "enabled"):
        _boolean(button[field], f"{path}.{field}")
    if button["enabled"] and not button["visible"]:
        raise ValueError(f"{path}: hidden button cannot be enabled")
    return button


def _step(value: object) -> dict:
    path = "snapshot.step"
    step = _object(value, ("plan_id", "step_id", "target", "observed", "comparison"), path)
    for field in ("plan_id", "step_id"):
        _nullable_text(step[field], f"{path}.{field}")
    if step["comparison"] not in ("WAITING", "MATCH", "MISMATCH", "UNOBSERVABLE"):
        raise ValueError(f"{path}.comparison: unsupported comparison")
    if step["target"] is not None:
        _block(step["target"], f"{path}.target")
        if step["plan_id"] is None or step["step_id"] is None:
            raise ValueError(f"{path}: target requires plan_id and step_id")
    elif step["step_id"] is not None or step["observed"] is not None:
        raise ValueError(f"{path}: no target requires no step_id or observed")
    observed = step["observed"]
    if observed is None:
        if step["comparison"] != "WAITING":
            raise ValueError(f"{path}.comparison: missing observation requires WAITING")
    else:
        validate_observed(observed)
        # 판단 불가를 대기로 숨기지 않는다. 목표 일치의 계산은 Backend 책임이다.
        # OK의 부분 관측도 이번 목표 영역은 판단 불가일 수 있다.
        if observed["status"] == "UNOBSERVABLE" and step["comparison"] != "UNOBSERVABLE":
            raise ValueError(f"{path}.comparison: conflicts with observation status")
    return step


def _monitor(value: object, step: dict) -> dict:
    path = "snapshot.monitor"
    monitor = _object(value, ("robot", "observation", "place_status", "supply"), path)
    robot = _object(monitor["robot"], ("mode", "status"), f"{path}.robot")
    if robot["mode"] not in ("FAKE", "REAL"):
        raise ValueError(f"{path}.robot.mode: explicit FAKE or REAL required")
    if robot["status"] not in (None, "IDLE", "BUSY", "STOP_PENDING", "STOPPED", "ERROR"):
        raise ValueError(f"{path}.robot.status: unsupported status")
    observation = _object(monitor["observation"],
                          ("status", "check_id", "observation_seq", "reason"),
                          f"{path}.observation")
    for field in ("check_id", "reason"):
        _nullable_text(observation[field], f"{path}.observation.{field}")
    if observation["status"] not in (None, "OK", "UNOBSERVABLE"):
        raise ValueError(f"{path}.observation.status: unsupported status")
    if observation["status"] is not None and (
        observation["check_id"] is None or observation["observation_seq"] is None
    ):
        raise ValueError(f"{path}.observation: received status requires capture identity")
    if observation["observation_seq"] is not None:
        _integer(observation["observation_seq"], 0, None, f"{path}.observation.observation_seq")
        if observation["check_id"] is None or observation["status"] is None:
            raise ValueError(f"{path}.observation: capture sequence requires check_id and status")
    if observation["status"] == "UNOBSERVABLE" and observation["reason"] is None:
        raise ValueError(f"{path}.observation.reason: UNOBSERVABLE requires reason")
    if step["observed"] is not None:
        for field in ("status", "check_id", "observation_seq"):
            if observation[field] != step["observed"][field]:
                raise ValueError(f"{path}.observation.{field}: differs from Step observation")
    if monitor["place_status"] not in (None, "EMPTY", "OCCUPIED", "UNOBSERVABLE"):
        raise ValueError(f"{path}.place_status: unsupported status")
    columns = {}
    for index, value in enumerate(_array(monitor["supply"], f"{path}.supply")):
        item_path = f"{path}.supply[{index}]"
        item = _object(value, ("brick_type", "color", "next_slot", "needs_refill"), item_path)
        key = _column(item, item_path)
        if key in columns:
            raise ValueError(f"{item_path}: duplicate supply column")
        if item["next_slot"] is not None:
            _integer(item["next_slot"], 1, 6, f"{item_path}.next_slot")
        if item["needs_refill"] is not None:
            _boolean(item["needs_refill"], f"{item_path}.needs_refill")
        columns[key] = item
    if columns.keys() != SUPPLY_COLUMNS:
        raise ValueError(f"{path}.supply: requires all four supply columns")
    return columns


def _actions(value: object, workflow: str, notice: dict, columns: dict, *, trial_start=None, trial_controls=None) -> None:
    path = "snapshot.actions"
    actions = _object(value, ("job_id", "start", "stop", "resume", "intent_choice",
                              "correction_continue", "supply_refill") +
                     (("prepare_observe",) if "prepare_observe" in value else ()), path)
    if "prepare_observe" in actions:
        prepare = _button(actions["prepare_observe"], f"{path}.prepare_observe")
        if trial_start is None or workflow != "IDLE" or actions["job_id"] is not None:
            raise ValueError("snapshot.actions.prepare_observe: REAL before Job only")
        if prepare["enabled"] and actions["start"]["enabled"]:
            raise ValueError("snapshot.actions.prepare_observe: already ready at observe")
    _nullable_text(actions["job_id"], f"{path}.job_id")
    if workflow not in ("IDLE", "COMPLETE") and actions["job_id"] is None:
        raise ValueError(f"{path}.job_id: active workflow requires Job context")
    # 표시 계약의 일관성 검사이며 Qt의 actions를 생성하거나 보정하지 않는다.
    expected = (workflow in ("IDLE", "COMPLETE"),
                workflow not in ("IDLE", "COMPLETE", "STOPPED"), workflow == "STOPPED")
    if trial_start is not None:
        expected = trial_controls
    for name, enabled in zip(("start", "stop", "resume"), expected):
        button = _button(actions[name], f"{path}.{name}")
        if not button["visible"] or button["enabled"] != enabled:
            raise ValueError(f"{path}.{name}: conflicts with basic button table")
    for name in ("intent_choice", "correction_continue"):
        button = _button(actions[name], f"{path}.{name}", ("visible", "enabled", "request_id"))
        _nullable_text(button["request_id"], f"{path}.{name}.request_id")
        if button["visible"]:
            if actions["job_id"] is None or button["request_id"] is None:
                raise ValueError(f"{path}.{name}.request_id: visible action requires Job/request")
            if button["request_id"] != notice["request_id"]:
                raise ValueError(f"{path}.{name}.request_id: differs from notice request")
    if actions["intent_choice"]["visible"] and notice["question"] is None:
        raise ValueError(f"{path}.intent_choice: requires displayed question")
    if actions["intent_choice"]["visible"] and actions["correction_continue"]["visible"]:
        raise ValueError(f"{path}: intent choice and correction cannot both be displayed")
    seen = set()
    for index, value in enumerate(_array(actions["supply_refill"], f"{path}.supply_refill")):
        item_path = f"{path}.supply_refill[{index}]"
        button = _button(value, item_path, ("brick_type", "color", "visible", "enabled"))
        key = _column(button, item_path)
        if key in seen:
            raise ValueError(f"{item_path}: duplicate supply column")
        if button["visible"] and (actions["job_id"] is None or columns[key]["needs_refill"] is not True):
            raise ValueError(f"{item_path}: visible refill requires Job and refill-needed column")
        seen.add(key)


def validate_hmi_snapshot(value: object) -> dict:
    optional = tuple(key for key in ("transfer_target", "manual_trial", "reported_placement") if isinstance(value, dict) and key in value)
    snapshot = _object(value, ("workflow_status", "step", "progress", "monitor",
                               "notice", "actions", "design", "current") + optional, "snapshot")
    _current(snapshot["current"])
    if snapshot["workflow_status"] not in WORKFLOW_STATUSES:
        raise ValueError("snapshot.workflow_status: unsupported workflow")
    if snapshot["design"] is not None:
        validate_design(snapshot["design"])
    step = _step(snapshot["step"])
    if step["target"] is not None and snapshot["design"] is None:
        raise ValueError("snapshot.design: Step target requires adopted Design")
    progress = _object(snapshot["progress"], ("completed", "total"), "snapshot.progress")
    _integer(progress["total"], 0, None, "snapshot.progress.total")
    _integer(progress["completed"], 0, progress["total"], "snapshot.progress.completed")
    columns = _monitor(snapshot["monitor"], step)
    notice = _object(snapshot["notice"], ("question", "reason", "required_action", "request_id"),
                     "snapshot.notice")
    for field, item in notice.items():
        _nullable_text(item, f"snapshot.notice.{field}")
    if (snapshot["workflow_status"] == "STOPPED"
            and snapshot["monitor"]["robot"]["status"] == "STOP_PENDING"):
        raise ValueError("snapshot.monitor.robot.status: STOP_PENDING is not confirmed STOPPED")
    real_trial = snapshot["monitor"]["robot"]["mode"] == "REAL"
    manual_trial = snapshot.get("manual_trial", False)
    if "manual_trial" in snapshot and (manual_trial is not True or not real_trial):
        raise ValueError("snapshot.manual_trial: explicit REAL manual trial required")
    if manual_trial and "transfer_target" in snapshot:
        raise ValueError("snapshot.manual_trial: assembly target and single transfer display cannot be combined")
    if "reported_placement" in snapshot:
        reported = snapshot["reported_placement"]
        _block(reported, "snapshot.reported_placement")
        if (not manual_trial or not real_trial or step["comparison"] != "MISMATCH" or
                step["observed"] is None or reported not in step["observed"]["visible_blocks"]):
            raise ValueError("snapshot.reported_placement: requires a manual REAL mismatch observation")
    if "transfer_target" in snapshot:
        if not real_trial:
            raise ValueError("snapshot.transfer_target: only available in REAL single transfer trial")
        target = _object(snapshot["transfer_target"], ("brick_type", "color", "slot"), "snapshot.transfer_target")
        _column(target, "snapshot.transfer_target")
        _integer(target["slot"], 1, 6, "snapshot.transfer_target.slot")
    trial_start = (snapshot["workflow_status"] == "IDLE" and snapshot["actions"]["job_id"] is None
                   and snapshot["monitor"]["robot"]["status"] == "IDLE") if real_trial else None
    startup = snapshot["actions"]["job_id"] is None
    robot_status = snapshot["monitor"]["robot"]["status"]
    controls = (trial_start, snapshot["workflow_status"] not in ("IDLE", "COMPLETE", "STOPPED") or
                startup and robot_status in ("BUSY", "STOP_PENDING"),
                snapshot["workflow_status"] == "STOPPED" or startup and robot_status == "STOPPED")
    _actions(snapshot["actions"], snapshot["workflow_status"], notice, columns, trial_start=trial_start, trial_controls=controls)
    if real_trial and manual_trial:
        if (snapshot["workflow_status"] not in ("IDLE", "PREPARING", "DELIVERING", "WAIT_ASSEMBLY", "WAIT_INTENT", "REPLANNING", "WAIT_CORRECTION", "HOLD", "STOPPED", "COMPLETE") or
                progress["total"] > 24):
            raise ValueError("snapshot: manual REAL trial requires bounded workflow within four six-slot rows")
    elif real_trial:
        if (snapshot["workflow_status"] not in ("IDLE", "DELIVERING", "HOLD", "STOPPED") or
                snapshot["design"] is not None or step["target"] is not None or
                progress != dict(completed=0, total=0)):
            raise ValueError("snapshot: REAL currently supports a single transfer trial, no simulated assembly/STOP proof")
    return deepcopy(snapshot)


def validate_hmi_command(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("command"), str):
        raise ValueError("command.command: expected command object and name")
    name = value["command"]
    if name not in COMMAND_FIELDS:
        raise ValueError("command.command: unsupported command")
    command = _object(value, COMMAND_FIELDS[name], "command")
    for field in ("job_id", "request_id"):
        if field in command:
            _text(command[field], f"command.{field}")
    if name == "CHOOSE_INTENT" and command["choice"] not in ("KEEP", "REVISE"):
        raise ValueError("command.choice: expected explicit KEEP or REVISE")
    if name == "SUPPLY_REFILLED":
        _column(command, "command")
    return deepcopy(command)
