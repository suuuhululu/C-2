"""C 내부 Design 독립 검증.

목적:
    Initial / Revised Design을 순수 Python 규칙으로 검증한다.
    LLM 판단에 맡기지 않으며 A / D / HMI 없이 단독으로 통과해야 한다.

구현 범위(값은 docs/06_CONTRACT_DRAFT.md §1·§2를 따른다):
    - color: yellow / blue (소문자)
    - brick_type: 2x2x1 / 2x3x1
    - x, y: 0~23 (24×24 Board stud 위치, Robot mm 아님). footprint 최소 모서리
    - layer: 1~5, 1-based (layer 1 = Board 위 첫 Block 층)
    - orientation_deg: 2x3x1은 0(X 2 / Y 3 stud) 또는 90(X 3 / Y 2 stud), 2x2x1은 0
    - Board 범위, overlap, support, connectivity
    - support 규칙 "바로 아래 layer와 겹치는 stud 합계 2 이상(아래 Block 개수 무관,
      같은 stud 중복 합산 없음)"은 2026-10-06 A 동의·D 회신으로 통일한 Day4
      기하 기준이다. 실제 체결·물리 안정성 검증을 의미하지 않는다.
    - Design은 정확히 {design_version, blocks} 두 key만 허용(§2). 다른 top-level
      key는 unknown_key
    - 조립된 Block 보존(Revised): current에 있는 각 Block의 6값 조합이 candidate의
      blocks에 적어도 같은 개수만큼(멀티셋 포함 관계) 존재해야 한다. 블록 ID가
      없으므로 값 자체로 식별한다
    - malformed output, Robot field 유입 거부
    - 거부 사유를 [{rule, blocks, message}]로 반환(후보 거부일 뿐 실패 아님).
      blocks는 특정 Block이 관련될 때만 그 Block(들)의 dict 목록이며, 그렇지 않으면
      빈 리스트
    - 입력 Current: overlap 위반만 입력 오류. support 위반은 오류가 아니며
      main이 Revised 생성 대신 escalation으로 처리

하지 않는 것:
    - Design 생성(designer.py 담당)
    - 사람 조립 Plan 검증·조립 순서(A 담당), Expected / Current 비교(D 담당)
    - LLM 호출

연결:
    designer.py 가 호출한다. 다른 C 모듈에 의존하지 않는다.
"""

import json
from collections import Counter

TOP_FIELDS = ("design_version", "blocks")
BLOCK_FIELDS = ("brick_type", "color", "x", "y", "layer", "orientation_deg")

COLORS = {"yellow", "blue"}
BRICK_TYPES = {"2x2x1", "2x3x1"}
BOARD_RANGE = range(0, 24)
MAX_LAYER = 5
MAX_BLOCKS = 30  # 2026-10-07 사용자 승인(EXPRESSIVE v4: 큰 가구 설계 허용)
# 2026-10-06 A 동의·D 회신으로 통일한 Day4 기하 기준(물리 안정성 검증 아님).
MIN_SUPPORT_STUDS = 2


def footprint(block):
    """Studs covered by a block's brick_type/orientation at its anchor (x, y)."""
    brick_type = block["brick_type"]
    x, y = block["x"], block["y"]
    if brick_type == "2x2x1":
        w, h = 2, 2
    else:  # "2x3x1"
        w, h = (2, 3) if block["orientation_deg"] == 0 else (3, 2)
    return {(x + dx, y + dy) for dx in range(w) for dy in range(h)}


def _is_int(value):
    # bool is an int subclass and 1.0 == 1, so both need explicit exclusion.
    return isinstance(value, int) and not isinstance(value, bool)


def _reason(rule, blocks, message):
    return {"rule": rule, "blocks": blocks, "message": message}


def _parse(candidate):
    """Returns (dict, None) or (None, [malformed_output reason])."""
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except ValueError:
            return None, [_reason("malformed_output", [], "input is not valid JSON")]
    if not isinstance(candidate, dict):
        return None, [_reason("malformed_output", [], "input is not a JSON object")]
    return candidate, None


def _check_block(block, reject_unknown_keys=True):
    """Validate one block dict's fields/values.

    D input (Current / Difference blocks) passes reject_unknown_keys=False: C reads only
    the contract fields and ignores the rest (§5), so extra keys there are not errors.

    Returns (reasons, node). node is None when brick_type/position/layer are not well-formed
    enough to run footprint-based checks without crashing; otherwise it is
    {"layer", "footprint", "block"} for use by overlap/support/connectivity.
    """
    if not isinstance(block, dict):
        return [_reason("invalid_type", [], "block is not an object")], None

    reasons = []

    for key in BLOCK_FIELDS:
        if key not in block:
            reasons.append(_reason("missing_field", [block], f"block missing '{key}'"))
    if reject_unknown_keys:
        for key in block:
            if key not in BLOCK_FIELDS:
                reasons.append(_reason("unknown_key", [block], f"block has unknown key '{key}'"))

    if "color" in block and block["color"] not in COLORS:
        reasons.append(_reason("invalid_value", [block], f"color '{block['color']}' not allowed"))

    brick_type = block.get("brick_type")
    type_ok = "brick_type" in block and brick_type in BRICK_TYPES
    if "brick_type" in block and not type_ok:
        reasons.append(_reason("invalid_value", [block], f"brick_type '{brick_type}' not allowed"))

    x, y = block.get("x"), block.get("y")
    x_ok = "x" in block and _is_int(x)
    y_ok = "y" in block and _is_int(y)
    if "x" in block and not x_ok:
        reasons.append(_reason("invalid_type", [block], "x must be an int"))
    if "y" in block and not y_ok:
        reasons.append(_reason("invalid_type", [block], "y must be an int"))

    orientation = block.get("orientation_deg")
    orientation_type_ok = "orientation_deg" in block and _is_int(orientation)
    if "orientation_deg" in block and not orientation_type_ok:
        reasons.append(_reason("invalid_type", [block], "orientation_deg must be an int"))

    orientation_ok = False
    if type_ok and orientation_type_ok:
        allowed = {0, 90} if brick_type == "2x3x1" else {0}
        orientation_ok = orientation in allowed
        if not orientation_ok:
            reasons.append(
                _reason("invalid_value", [block], f"orientation_deg '{orientation}' invalid for {brick_type}")
            )

    layer = block.get("layer")
    layer_ok = False
    if "layer" in block:
        if _is_int(layer):
            layer_ok = 1 <= layer <= MAX_LAYER
            if not layer_ok:
                reasons.append(_reason("invalid_value", [block], f"layer '{layer}' out of range"))
        else:
            reasons.append(_reason("invalid_type", [block], "layer must be an int"))

    if not (type_ok and orientation_ok and x_ok and y_ok and layer_ok):
        return reasons, None

    cells = footprint({"brick_type": brick_type, "orientation_deg": orientation, "x": x, "y": y})
    if any(cx not in BOARD_RANGE or cy not in BOARD_RANGE for cx, cy in cells):
        reasons.append(_reason("out_of_board", [block], "block footprint outside 0..23"))

    return reasons, {"layer": layer, "footprint": cells, "block": block}


def _overlap_violations(nodes):
    by_layer = {}
    for node in nodes:
        by_layer.setdefault(node["layer"], []).append(node)
    reasons = []
    for same_layer in by_layer.values():
        for i in range(len(same_layer)):
            for j in range(i + 1, len(same_layer)):
                a, b = same_layer[i], same_layer[j]
                if a["footprint"] & b["footprint"]:
                    reasons.append(_reason("overlap", [a["block"], b["block"]], "blocks overlap on same layer"))
    return reasons


def _support_violations(nodes):
    by_layer = {}
    for node in nodes:
        by_layer.setdefault(node["layer"], []).append(node)
    reasons = []
    for node in nodes:
        if node["layer"] < 2:
            continue
        below = by_layer.get(node["layer"] - 1, [])
        shared = sum(len(node["footprint"] & other["footprint"]) for other in below)
        if shared < MIN_SUPPORT_STUDS:
            reasons.append(_reason("support", [node["block"]], f"block support studs={shared} < {MIN_SUPPORT_STUDS}"))
    return reasons


def _connectivity_violations(nodes):
    if len(nodes) <= 1:
        return []
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if abs(nodes[i]["layer"] - nodes[j]["layer"]) == 1 and nodes[i]["footprint"] & nodes[j]["footprint"]:
                parent[find(i)] = find(j)

    components = {}
    for i, node in enumerate(nodes):
        components.setdefault(find(i), []).append(node["block"])
    if len(components) == 1:
        return []
    # 어느 블록이 어느 덩어리인지 알려 줘야 재생성(LLM)이 끊긴 곳을 잇는 방향을 찾을 수 있다(§8.10).
    groups = sorted(components.values(), key=len, reverse=True)
    listed = [[{key: block.get(key) for key in BLOCK_FIELDS} for block in group] for group in groups]
    message = (
        f"design is not fully connected: {len(groups)} disconnected components "
        f"(sizes {', '.join(str(len(group)) for group in groups)}); components: {json.dumps(listed)}"
    )
    return [_reason("connectivity", [block for group in groups for block in group], message)]


def _placement_violations(nodes):
    return _overlap_violations(nodes) + _support_violations(nodes) + _connectivity_violations(nodes)


def _validate_blocks_list(container):
    """Shared top-level 'blocks' handling for validate_design / validate_revised.

    Returns (reasons, nodes, dict_blocks).
    """
    reasons = []
    nodes = []
    dict_blocks = []
    blocks = container.get("blocks")
    if not isinstance(blocks, list):
        reasons.append(_reason("invalid_type", [], "blocks must be a list"))
        return reasons, nodes, dict_blocks

    if not (1 <= len(blocks) <= MAX_BLOCKS):
        reasons.append(_reason("brick_count", [], f"blocks count {len(blocks)} out of 1..{MAX_BLOCKS}"))

    for block in blocks:
        block_reasons, node = _check_block(block)
        reasons.extend(block_reasons)
        if node is not None:
            nodes.append(node)
        if isinstance(block, dict):
            dict_blocks.append(block)

    return reasons, nodes, dict_blocks


def validate_design(design):
    """Validation of a full Design (Initial or finalized Revised). §2: exactly
    {design_version, blocks}."""
    parsed, err = _parse(design)
    if err:
        return err

    reasons = []
    for key in TOP_FIELDS:
        if key not in parsed:
            reasons.append(_reason("missing_field", [], f"design missing '{key}'"))
    for key in parsed:
        if key not in TOP_FIELDS:
            reasons.append(_reason("unknown_key", [], f"design has unknown key '{key}'"))

    if "design_version" in parsed:
        version = parsed["design_version"]
        if not _is_int(version):
            reasons.append(_reason("invalid_type", [], "design_version must be an int"))
        elif version < 1:
            reasons.append(_reason("invalid_value", [], "design_version must be >= 1"))

    nodes = []
    if "blocks" in parsed:
        blocks_reasons, nodes, _ = _validate_blocks_list(parsed)
        reasons.extend(blocks_reasons)

    reasons.extend(_placement_violations(nodes))
    return reasons


def _block_value_tuple(block):
    return tuple(block.get(key) for key in BLOCK_FIELDS)


def _assembled_preserved(blocks, current):
    """current의 각 Block 값 조합이 candidate blocks 멀티셋에 최소 같은 개수만큼
    포함돼야 한다(블록 ID가 없으므로 값으로 식별)."""
    if not isinstance(current, list):
        return []
    candidate_counts = Counter(_block_value_tuple(b) for b in blocks if isinstance(b, dict))
    current_counts = Counter(_block_value_tuple(c) for c in current if isinstance(c, dict))

    missing = [tup for tup, needed in current_counts.items() if candidate_counts.get(tup, 0) < needed]
    if not missing:
        return []
    offending = [dict(zip(BLOCK_FIELDS, tup)) for tup in missing]
    return [_reason("assembled_not_preserved", offending, "assembled blocks not preserved in candidate")]


def validate_revised(candidate, current):
    """Revised candidate 검증. candidate는 정확히 {"blocks": [...]}만 허용한다."""
    parsed, err = _parse(candidate)
    if err:
        return err

    reasons = []
    if "blocks" not in parsed:
        reasons.append(_reason("missing_field", [], "candidate missing 'blocks'"))
    for key in parsed:
        if key != "blocks":
            reasons.append(_reason("unknown_key", [], f"candidate has unknown key '{key}'"))

    nodes, dict_blocks = [], []
    if "blocks" in parsed:
        blocks_reasons, nodes, dict_blocks = _validate_blocks_list(parsed)
        reasons.extend(blocks_reasons)

    reasons.extend(_placement_violations(nodes))
    reasons.extend(_assembled_preserved(dict_blocks, current))
    return reasons


def _check_current(current):
    if not isinstance(current, list):
        return [_reason("invalid_type", [], "current must be a list")]

    reasons = []
    nodes = []
    for block in current:
        block_reasons, node = _check_block(block, reject_unknown_keys=False)
        reasons.extend(block_reasons)
        if node is not None:
            nodes.append(node)

    reasons.extend(_overlap_violations(nodes))  # support/connectivity are not input errors (§9, §10)
    return reasons


def _check_differences(differences):
    if not isinstance(differences, list):
        return [_reason("invalid_type", [], "differences must be a list")]
    if not differences:
        return [_reason("invalid_value", [], "differences must not be empty")]

    reasons = []
    for diff in differences:
        if not isinstance(diff, dict):
            reasons.append(_reason("invalid_type", [], "difference must be an object"))
            continue
        if "expected" not in diff:
            reasons.append(_reason("missing_field", [], "difference missing 'expected'"))
        if "actual" not in diff:
            reasons.append(_reason("missing_field", [], "difference missing 'actual'"))

        expected, actual = diff.get("expected"), diff.get("actual")
        if expected is None and actual is None:
            reasons.append(_reason("invalid_value", [], "difference expected and actual both null"))
        if expected is not None:
            reasons.extend(_check_block(expected, reject_unknown_keys=False)[0])
        if actual is not None:
            reasons.extend(_check_block(actual, reject_unknown_keys=False)[0])
    return reasons


def check_intervention_input(design, current, differences):
    """Reasons for an INVALID_INPUT verdict on run_intervention's arguments (§9, §10)."""
    reasons = list(validate_design(design))
    reasons.extend(_check_current(current))
    reasons.extend(_check_differences(differences))
    return reasons


def current_support_violations(current):
    """Support reasons for Current blocks only (escalation trigger, not an input error)."""
    if not isinstance(current, list):
        return []
    nodes = []
    for block in current:
        _, node = _check_block(block, reject_unknown_keys=False)
        if node is not None:
            nodes.append(node)
    return _support_violations(nodes)
