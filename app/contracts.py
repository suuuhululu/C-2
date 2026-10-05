"""Day4 Consumer 입력 검사. 기하 검증·상태 채택·완료 판정은 수행하지 않는다."""

from copy import deepcopy


BLOCK_FIELDS = ("brick_type", "color", "x", "y", "layer", "orientation_deg")


def _object(value: object, fields: tuple[str, ...], path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    missing = set(fields) - value.keys()
    extra = value.keys() - set(fields)
    if missing or extra:
        raise ValueError(f"{path}: missing={sorted(missing)}, unsupported={sorted(extra, key=repr)}")
    return value


def _integer(value: object, minimum: int, maximum: int | None, path: str) -> None:
    # bool은 Python에서 int의 하위 타입이지만 계약의 좌표·버전이 아니다.
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{path}: expected integer in {minimum}..{maximum}")


def _text(value: object, path: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: expected non-empty string")


def _array(value: object, path: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected array")
    return value


def _block(value: object, path: str) -> None:
    block = _object(value, BLOCK_FIELDS, path)
    if block["brick_type"] not in ("2x2x1", "2x3x1"):
        raise ValueError(f"{path}.brick_type: unsupported brick type")
    if block["color"] not in ("yellow", "blue"):
        raise ValueError(f"{path}.color: unsupported color")
    for field in ("x", "y"):
        _integer(block[field], 0, 23, f"{path}.{field}")
    _integer(block["layer"], 1, 4, f"{path}.layer")
    _integer(block["orientation_deg"], 0, 90, f"{path}.orientation_deg")
    angles = (0,) if block["brick_type"] == "2x2x1" else (0, 90)
    if block["orientation_deg"] not in angles:
        raise ValueError(f"{path}.orientation_deg: unsupported representative angle")


def _blocks(value: object, path: str) -> None:
    for index, block in enumerate(_array(value, path)):
        _block(block, f"{path}[{index}]")


def validate_block(value: object) -> dict:
    _block(value, "block")
    return deepcopy(value)


def validate_design(value: object) -> dict:
    design = _object(value, ("design_version", "blocks"), "design")
    _integer(design["design_version"], 1, None, "design.design_version")
    _blocks(design["blocks"], "design.blocks")
    return deepcopy(design)


def _step(value: object, path: str) -> None:
    step = _object(value, ("step_id", "operation", "before", "after",
                           "prerequisites", "requires_delivery"), path)
    _text(step["step_id"], f"{path}.step_id")
    if step["operation"] != "PLACE" or step["before"] is not None or step["requires_delivery"] is not True:
        raise ValueError(f"{path}: PLACE requires before=null and requires_delivery=true")
    _block(step["after"], f"{path}.after")
    prerequisites = _array(step["prerequisites"], f"{path}.prerequisites")
    for index, step_id in enumerate(prerequisites):
        _text(step_id, f"{path}.prerequisites[{index}]")
    if len(set(prerequisites)) != len(prerequisites):
        raise ValueError(f"{path}.prerequisites: duplicate reference")


def validate_step(value: object) -> dict:
    _step(value, "step")
    return deepcopy(value)


def validate_plan(value: object) -> dict:
    plan = _object(value, ("plan_id", "design_version", "base_current_revision", "steps"), "plan")
    _text(plan["plan_id"], "plan.plan_id")
    _integer(plan["design_version"], 1, None, "plan.design_version")
    _integer(plan["base_current_revision"], 0, None, "plan.base_current_revision")
    earlier = set()
    for index, step in enumerate(_array(plan["steps"], "plan.steps")):
        path = f"plan.steps[{index}]"
        _step(step, path)
        if step["step_id"] in earlier:
            raise ValueError(f"{path}.step_id: duplicate identifier")
        # 배열 순서대로 실행할 수 있는 참조인지 검사하며 지지 관계를 생성하지 않는다.
        if not set(step["prerequisites"]).issubset(earlier):
            raise ValueError(f"{path}.prerequisites: must reference earlier steps in this Plan")
        earlier.add(step["step_id"])
    return deepcopy(plan)


def _region(value: object, path: str) -> None:
    region = _object(value, ("x", "y", "width", "height", "layer"), path)
    for field in ("x", "y"):
        _integer(region[field], 0, 23, f"{path}.{field}")
    for field in ("width", "height"):
        _integer(region[field], 1, 24, f"{path}.{field}")
    _integer(region["layer"], 1, 4, f"{path}.layer")
    if region["x"] + region["width"] > 24 or region["y"] + region["height"] > 24:
        raise ValueError(f"{path}: verified region extends outside board")


def validate_observed(value: object) -> dict:
    observed = _object(value, ("check_id", "observation_seq", "status", "visible_blocks",
                               "verified_regions", "reason"), "observed")
    _text(observed["check_id"], "observed.check_id")
    _integer(observed["observation_seq"], 0, None, "observed.observation_seq")
    if observed["status"] not in ("OK", "UNOBSERVABLE"):
        raise ValueError("observed.status: expected OK or UNOBSERVABLE")
    _blocks(observed["visible_blocks"], "observed.visible_blocks")
    for index, region in enumerate(_array(observed["verified_regions"], "observed.verified_regions")):
        _region(region, f"observed.verified_regions[{index}]")
    if observed["status"] == "UNOBSERVABLE" or observed["reason"] is not None:
        _text(observed["reason"], "observed.reason")
    return deepcopy(observed)
