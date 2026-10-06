"""관측 증거로 Current를 채택한다. Expected·완료·실행 흐름은 다루지 않는다."""

from copy import deepcopy

from app.contracts import (
    BLOCK_FIELDS, _array, _integer, _object, _text, validate_block, validate_observed,
)


def _key(block: dict) -> tuple:
    return tuple(block[field] for field in BLOCK_FIELDS)


def _footprint(block: dict) -> set[tuple[int, int, int]]:
    width, height = (2, 2) if block["brick_type"] == "2x2x1" else (2, 3)
    if block["orientation_deg"] == 90:
        width, height = height, width
    if block["x"] + width > 24 or block["y"] + height > 24:
        raise ValueError("block footprint: extends outside board")
    return {(x, y, block["layer"])
            for x in range(block["x"], block["x"] + width)
            for y in range(block["y"], block["y"] + height)}


def _placements(value: object, path: str, *, allow_duplicates: bool) -> list[dict]:
    blocks, keys, occupied = [], set(), set()
    for value_block in _array(value, path):
        block = validate_block(value_block)
        key, cells = _key(block), _footprint(block)
        if key in keys and allow_duplicates:
            continue
        if cells & occupied:
            raise ValueError(f"{path}: duplicate or conflicting same-layer placements")
        blocks.append(block)
        keys.add(key)
        occupied.update(cells)
    return blocks


def open_observation_check(check_id: str, job_id: str, plan_id: str | None, step_id: str | None) -> dict:
    """Backend가 새 고유 ID로 연 check의 문맥. 닫힌 check는 호출 시 None이다."""
    context = dict(check_id=check_id, job_id=job_id, plan_id=plan_id, step_id=step_id,
                   last_observation_seq=None)
    _check_context(context)
    return context


def _check_context(value: object) -> None:
    context = _object(value, ("check_id", "job_id", "plan_id", "step_id",
                              "last_observation_seq"), "active_check")
    for field in ("check_id", "job_id"):
        _text(context[field], f"active_check.{field}")
    # 최초 사람 정리에는 아직 채택 Plan이 없다. 가짜 Plan/Step 식별을 만들지 않는다.
    if context["plan_id"] is not None or context["step_id"] is not None:
        for field in ("plan_id", "step_id"):
            _text(context[field], f"active_check.{field}")
    if context["last_observation_seq"] is not None:
        _integer(context["last_observation_seq"], 0, None,
                 "active_check.last_observation_seq")


def _verified_cells(regions: list[dict]) -> set[tuple[int, int, int]]:
    return {(x, y, region["layer"]) for region in regions
            for x in range(region["x"], region["x"] + region["width"])
            for y in range(region["y"], region["y"] + region["height"])}


def _merge(blocks: list[dict], visible: list[dict], verified: set) -> tuple[list, bool, bool]:
    seen = {_key(block) for block in visible}
    retained, removed = [], []
    for old in blocks:
        old_cells = _footprint(old)
        # 부분 누락은 삭제 근거가 아니다. 실제 교체 점유는 전체 빈 영역 없이도 증거다.
        replaced = any((old["x"], old["y"], old["layer"]) ==
                       (new["x"], new["y"], new["layer"]) or
                       bool(old_cells & _footprint(new) & verified) for new in visible)
        if _key(old) not in seen and (old_cells <= verified or replaced):
            removed.append(old)
        else:
            retained.append(old)

    retained_keys = {_key(block) for block in retained}
    added = [block for block in visible if _key(block) not in retained_keys]
    for new in added:
        for old in retained:
            if _footprint(new) & _footprint(old):
                return blocks, False, True
            # 가려진 아래층은 유지한다. 같은 층의 미확인 동일 종류·색상은 이동/추가가 불명확하다.
            if (_key(old) not in seen and old["layer"] == new["layer"] and
                    (old["brick_type"], old["color"]) == (new["brick_type"], new["color"])):
                return blocks, False, True
    return retained + added, bool(removed), False


def adopt_observation(current: object, active_check: dict | None, value: object) -> dict:
    """순수 함수: Current/check 복사와 채택·무시·보류 사유를 반환한다.

    잘못된 입력은 ValueError이며 원본/촬영 순번을 바꾸지 않는다. 유효한 보류 결과는
    순번을 소비해 과거 프레임을 막는다. 결과의 active_check를 다음 호출에 전달한다.
    """
    state = _object(current, ("current_revision", "blocks"), "current")
    _integer(state["current_revision"], 0, None, "current.current_revision")
    blocks = _placements(state["blocks"], "current.blocks", allow_duplicates=False)
    observation = validate_observed(value)
    if active_check is not None:
        _check_context(active_check)
    result = dict(current=deepcopy(state), active_check=deepcopy(active_check),
                  disposition="IGNORED", reason=None, existing_changed=False,
                  pending_observation=None)
    if active_check is None:
        result["reason"] = "NO_ACTIVE_CHECK"
        return result
    if observation["check_id"] != active_check["check_id"]:
        result["reason"] = "CHECK_MISMATCH"
        return result
    previous_seq = active_check["last_observation_seq"]
    if previous_seq is not None and observation["observation_seq"] <= previous_seq:
        result["reason"] = "STALE_OBSERVATION"
        return result

    if observation["status"] == "UNOBSERVABLE":
        merged, existing_changed, hold_reason = blocks, False, "UNOBSERVABLE"
    else:
        visible = _placements(observation["visible_blocks"], "observed.visible_blocks",
                              allow_duplicates=True)
        verified = _verified_cells(observation["verified_regions"])
        if any(not (_footprint(block) & verified) for block in visible):
            raise ValueError("observed.visible_blocks: placement has no same-layer verified region")
        merged, existing_changed, ambiguous = _merge(blocks, visible, verified)
        hold_reason = "AMBIGUOUS_RELOCATION" if ambiguous else None
        if not verified:
            hold_reason = "NO_VERIFIED_REGIONS"

    result["active_check"]["last_observation_seq"] = observation["observation_seq"]
    if hold_reason is not None:
        result.update(disposition="HOLD", reason=hold_reason, pending_observation=observation)
        return result
    changed = {_key(block) for block in merged} != {_key(block) for block in blocks}
    if changed:
        result["current"] = dict(current_revision=state["current_revision"] + 1, blocks=merged)
    result.update(disposition="ADOPTED" if changed else "UNCHANGED",
                  reason="LAYOUT_CHANGED" if changed else "NO_LAYOUT_CHANGE",
                  existing_changed=existing_changed)
    return result
