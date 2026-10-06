"""고정 Plan 기준 Expected와 관측 확인 기록으로 차이·완료를 판단한다."""

from copy import deepcopy

from app.contracts import (
    _array, _integer, _object, _text, validate_design, validate_observed, validate_plan,
)
from app.current import (
    _check_context, _footprint, _key, _placements, _verified_cells, adopt_observation,
)


def _current(value: object) -> dict:
    current = _object(value, ("current_revision", "blocks"), "current")
    _integer(current["current_revision"], 0, None, "current.current_revision")
    blocks = _placements(current["blocks"], "current.blocks", allow_duplicates=False)
    return dict(current_revision=current["current_revision"], blocks=blocks)


def freeze_plan_basis(design: object, plan: object, current: object) -> dict:
    """채택 시점의 복사본. 활성 Job/계획 요청 확인은 Backend 연결부의 책임이다."""
    design, plan, current = validate_design(design), validate_plan(plan), _current(current)
    if design["design_version"] != plan["design_version"]:
        raise ValueError("plan.design_version: differs from adopted Design")
    if current["current_revision"] != plan["base_current_revision"]:
        raise ValueError("plan.base_current_revision: differs from adoption Current")
    _placements(design["blocks"], "design.blocks", allow_duplicates=False)
    context = dict(design=design, plan=plan, base_current=current, confirmed_steps=[])
    calculate_expected(context)
    return context


def _context(value: object) -> dict:
    context = _object(value, ("design", "plan", "base_current", "confirmed_steps"), "context")
    design, plan = validate_design(context["design"]), validate_plan(context["plan"])
    base = _current(context["base_current"])
    if design["design_version"] != plan["design_version"]:
        raise ValueError("context: Design/Plan version mismatch")
    if base["current_revision"] != plan["base_current_revision"]:
        raise ValueError("context: Plan/baseline revision mismatch")
    _placements(design["blocks"], "design.blocks", allow_duplicates=False)
    records = _array(context["confirmed_steps"], "confirmed_steps")
    if len(records) > len(plan["steps"]):
        raise ValueError("confirmed_steps: exceeds Plan")
    checks = set()
    for index, record in enumerate(records):
        _object(record, ("step_id", "check_id", "observation_seq"), "confirmation")
        _text(record["check_id"], "confirmation.check_id")
        _integer(record["observation_seq"], 0, None, "confirmation.observation_seq")
        if record["step_id"] != plan["steps"][index]["step_id"] or record["check_id"] in checks:
            raise ValueError("confirmed_steps: must be an ordered prefix with distinct checks")
        checks.add(record["check_id"])
    return deepcopy(context)


def calculate_expected(value: object) -> dict:
    context = _context(value)
    steps = context["plan"]["steps"]
    completed = len(context["confirmed_steps"])
    # 최신 Current를 입력받지 않는다. 아직 확인하지 않은 미래 Step도 포함하지 않는다.
    effects = [step["after"] for step in steps[:completed + 1]]
    blocks = context["base_current"]["blocks"] + effects
    blocks = _placements(blocks, "expected.blocks", allow_duplicates=True)
    step_id = steps[completed]["step_id"] if completed < len(steps) else None
    return dict(plan_id=context["plan"]["plan_id"], step_id=step_id, blocks=blocks)


def _difference(expected: list[dict], actual: list[dict]) -> dict:
    expected_keys, actual_keys = {_key(block) for block in expected}, {_key(block) for block in actual}
    return dict(missing=[deepcopy(block) for block in expected if _key(block) not in actual_keys],
                unexpected=[deepcopy(block) for block in actual if _key(block) not in expected_keys],
                unobservable=[])


def evaluate_job_completion(value: object, current: object) -> dict:
    context, current = _context(value), _current(current)
    if len(context["confirmed_steps"]) != len(context["plan"]["steps"]):
        return dict(job_complete=False, reason="STEPS_UNCONFIRMED", difference=None)
    difference = _difference(context["design"]["blocks"], current["blocks"])
    complete = not (difference["missing"] or difference["unexpected"])
    return dict(job_complete=complete, reason="JOB_CONFIRMED" if complete else "FINAL_DESIGN_MISMATCH",
                difference=None if complete else difference)


def _target_readable(target: dict, observation: dict) -> bool:
    visible, verified = observation["visible_blocks"], _verified_cells(observation["verified_regions"])
    # 영역 경계의 블록도 전체 배치 값은 긍정 증거다. 누락 판정에는 확인 영역이 필요하다.
    return (any(_key(block) == _key(target) for block in visible) or
            _footprint(target) <= verified or
            any(_footprint(target) & _footprint(block) & verified for block in visible))


def evaluate_observation(value: object, current: object, active_check: dict | None,
                         observed: object) -> dict:
    """완료 확인용 Observed 전용. Robot 결과를 완료 근거로 받지 않는다."""
    context, current = _context(value), _current(current)
    observation, expected = validate_observed(observed), calculate_expected(context)
    if active_check is not None:
        _check_context(active_check)
    wrong_context = active_check is not None and (
        active_check["plan_id"] != expected["plan_id"] or
        active_check["step_id"] != expected["step_id"] or
        active_check["check_id"] in {record["check_id"] for record in context["confirmed_steps"]})
    adoption = adopt_observation(current, None if wrong_context else active_check, observation)
    result = dict(**adoption, context=context, expected=expected, comparison="WAITING",
                  difference=None, step_confirmed=False,
                  job_complete=evaluate_job_completion(context, current)["job_complete"],
                  requires_intent=False)
    if wrong_context:
        result.update(active_check=deepcopy(active_check), reason="CHECK_CONTEXT_MISMATCH")
    if result["disposition"] == "IGNORED":
        return result
    if result["disposition"] == "HOLD":
        result["comparison"] = "UNOBSERVABLE"
        return result

    target = context["plan"]["steps"][len(context["confirmed_steps"])]["after"]
    readable = _target_readable(target, observation)
    difference = _difference(expected["blocks"], result["current"]["blocks"])
    if not readable:
        difference["unobservable"] = [deepcopy(target)]
        difference["missing"] = [block for block in difference["missing"] if _key(block) != _key(target)]
    if difference["missing"] or difference["unexpected"]:
        result.update(comparison="MISMATCH", difference=difference, requires_intent=True,
                      active_check=None, reason="OBSERVATION_MISMATCH")
        return result
    if not readable:
        result.update(comparison="UNOBSERVABLE", disposition="HOLD", reason="TARGET_UNVERIFIED",
                      pending_observation=observation)
        return result

    context["confirmed_steps"].append(dict(step_id=expected["step_id"], check_id=observation["check_id"],
                                          observation_seq=observation["observation_seq"]))
    final = evaluate_job_completion(context, result["current"])
    result.update(comparison="MATCH", step_confirmed=True, active_check=None,
                  job_complete=final["job_complete"], reason="STEP_CONFIRMED")
    if final["reason"] != "STEPS_UNCONFIRMED":
        result.update(reason=final["reason"], difference=final["difference"],
                      requires_intent=not final["job_complete"])
    return result
