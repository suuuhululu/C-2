"""C 내부 Design 독립 검증.

목적:
    Initial / Revised Design을 순수 Python 규칙으로 검증한다.
    LLM 판단에 맡기지 않으며 A / D / HMI 없이 단독으로 통과해야 한다.

구현 범위(값은 docs/C_DESIGN_CONTRACT.md §2·§9를 따른다):
    - color: YELLOW / BLUE
    - geometry: 2x2x1 / 2x3x1
    - grid_x, grid_y: 0~23 (24×24 Board stud 위치, Robot mm 아님)
    - layer: 1~4, 1-based (layer 1 = Board 위 첫 LEGO 층)
    - orientation_deg: 2x3x1은 0(X 2 / Y 3 stud) 또는 90(X 3 / Y 2 stud), 2x2x1은 0
    - Board 범위, overlap, support(아래 Brick 개수와 무관하게 바로 아래 layer와의
      겹침 합계 2 stud 이상), connectivity
    - 조립된 Brick 보존: Current Brick이 같은 block_id와 같은 color·geometry·grid_x·grid_y·
      orientation_deg·layer가 Revised Design에 그대로 있는지
    - malformed output, Robot field 유입, 입력 Design에 없는 기존 block_id 거부
    - 거부 사유를 [{rule, block_ids, message}]로 반환(후보 거부일 뿐 실패 아님)
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
import re

TOP_FIELDS = ("design_version", "parent_version", "object_type", "source", "bricks")
BRICK_FIELDS = ("block_id", "color", "geometry", "grid_x", "grid_y", "orientation_deg", "layer")
VALUE_FIELDS = ("color", "geometry", "grid_x", "grid_y", "orientation_deg", "layer")

COLORS = {"YELLOW", "BLUE"}
GEOMETRIES = {"2x2x1", "2x3x1"}
BLOCK_ID_RE = re.compile(r"^B[0-9]{3}$")
BOARD_RANGE = range(0, 24)


def footprint(brick):
    """Studs covered by a brick's geometry/orientation at its anchor (grid_x, grid_y)."""
    geometry = brick["geometry"]
    gx, gy = brick["grid_x"], brick["grid_y"]
    if geometry == "2x2x1":
        w, h = 2, 2
    else:  # "2x3x1"
        w, h = (2, 3) if brick["orientation_deg"] == 0 else (3, 2)
    return {(gx + dx, gy + dy) for dx in range(w) for dy in range(h)}


def _is_int(value):
    # bool is an int subclass and 1.0 == 1, so both need explicit exclusion.
    return isinstance(value, int) and not isinstance(value, bool)


def _reason(rule, block_id, message):
    return {"rule": rule, "block_ids": [block_id], "message": message}


def _parse(candidate):
    """Returns (dict, None) or (None, [malformed_output reason])."""
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except ValueError:
            return None, [_reason("malformed_output", None, "input is not valid JSON")]
    if not isinstance(candidate, dict):
        return None, [_reason("malformed_output", None, "input is not a JSON object")]
    return candidate, None


def _check_brick(brick, allow_none_id, reject_unknown_keys=True):
    """Validate one brick dict's fields/values.

    D input (Current / Difference bricks) passes reject_unknown_keys=False: C reads only the
    contract fields and ignores the rest (§5), so extra keys there are not errors.

    Returns (reasons, node). node is None when geometry/position/layer are not well-formed
    enough to run footprint-based checks without crashing; otherwise it is
    {"id", "layer", "footprint"} for use by overlap/support/connectivity.
    """
    if not isinstance(brick, dict):
        return [_reason("invalid_type", None, "brick is not an object")], None

    reasons = []
    report_id = brick.get("block_id") if isinstance(brick.get("block_id"), str) else None

    for key in BRICK_FIELDS:
        if key not in brick:
            reasons.append(_reason("missing_field", report_id, f"brick missing '{key}'"))
    if reject_unknown_keys:
        for key in brick:
            if key not in BRICK_FIELDS:
                reasons.append(_reason("unknown_key", report_id, f"brick has unknown key '{key}'"))

    if "block_id" in brick:
        bid = brick["block_id"]
        if bid is None:
            if not allow_none_id:
                reasons.append(_reason("invalid_type", None, "block_id must be a string"))
        elif not isinstance(bid, str):
            reasons.append(_reason("invalid_type", report_id, "block_id must be a string"))
        elif not BLOCK_ID_RE.match(bid):
            reasons.append(_reason("invalid_block_id", bid, f"block_id '{bid}' has invalid format"))

    if "color" in brick and brick["color"] not in COLORS:
        reasons.append(_reason("invalid_value", report_id, f"color '{brick['color']}' not allowed"))

    geometry = brick.get("geometry")
    geometry_ok = "geometry" in brick and geometry in GEOMETRIES
    if "geometry" in brick and not geometry_ok:
        reasons.append(_reason("invalid_value", report_id, f"geometry '{geometry}' not allowed"))

    grid_x, grid_y = brick.get("grid_x"), brick.get("grid_y")
    grid_x_ok = "grid_x" in brick and _is_int(grid_x)
    grid_y_ok = "grid_y" in brick and _is_int(grid_y)
    if "grid_x" in brick and not grid_x_ok:
        reasons.append(_reason("invalid_type", report_id, "grid_x must be an int"))
    if "grid_y" in brick and not grid_y_ok:
        reasons.append(_reason("invalid_type", report_id, "grid_y must be an int"))

    orientation = brick.get("orientation_deg")
    orientation_type_ok = "orientation_deg" in brick and _is_int(orientation)
    if "orientation_deg" in brick and not orientation_type_ok:
        reasons.append(_reason("invalid_type", report_id, "orientation_deg must be an int"))

    orientation_ok = False
    if geometry_ok and orientation_type_ok:
        allowed = {0, 90} if geometry == "2x3x1" else {0}
        orientation_ok = orientation in allowed
        if not orientation_ok:
            reasons.append(
                _reason("invalid_value", report_id, f"orientation_deg '{orientation}' invalid for {geometry}")
            )

    layer = brick.get("layer")
    layer_ok = False
    if "layer" in brick:
        if _is_int(layer):
            layer_ok = 1 <= layer <= 4
            if not layer_ok:
                reasons.append(_reason("invalid_value", report_id, f"layer '{layer}' out of range"))
        else:
            reasons.append(_reason("invalid_type", report_id, "layer must be an int"))

    if not (geometry_ok and orientation_ok and grid_x_ok and grid_y_ok and layer_ok):
        return reasons, None

    cells = footprint({"geometry": geometry, "orientation_deg": orientation, "grid_x": grid_x, "grid_y": grid_y})
    if any(x not in BOARD_RANGE or y not in BOARD_RANGE for x, y in cells):
        reasons.append(_reason("out_of_board", report_id, "brick footprint outside 0..23"))

    return reasons, {"id": report_id, "layer": layer, "footprint": cells}


def _duplicate_ids(bricks):
    counts = {}
    for brick in bricks:
        bid = brick.get("block_id")
        if isinstance(bid, str):
            counts[bid] = counts.get(bid, 0) + 1
    return [_reason("duplicate_block_id", bid, f"block_id '{bid}' duplicated") for bid, n in counts.items() if n > 1]


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
                    reasons.append(
                        {"rule": "overlap", "block_ids": [a["id"], b["id"]], "message": "bricks overlap on same layer"}
                    )
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
        if shared < 2:
            reasons.append(_reason("support", node["id"], f"brick '{node['id']}' support studs={shared} < 2"))
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

    if len({find(i) for i in range(len(nodes))}) > 1:
        ids = [node["id"] for node in nodes]
        return [{"rule": "connectivity", "block_ids": ids, "message": "design is not fully connected"}]
    return []


def _geometry_violations(nodes):
    return _overlap_violations(nodes) + _support_violations(nodes) + _connectivity_violations(nodes)


def _validate_bricks_list(container, allow_none_id):
    """Shared top-level 'bricks' handling for validate_design / validate_revised.

    Returns (reasons, nodes, dict_bricks).
    """
    reasons = []
    nodes = []
    dict_bricks = []
    bricks = container.get("bricks")
    if not isinstance(bricks, list):
        reasons.append(_reason("invalid_type", None, "bricks must be a list"))
        return reasons, nodes, dict_bricks

    if not (1 <= len(bricks) <= 20):
        reasons.append(_reason("brick_count", None, f"bricks count {len(bricks)} out of 1..20"))

    for brick in bricks:
        brick_reasons, node = _check_brick(brick, allow_none_id)
        reasons.extend(brick_reasons)
        if node is not None:
            nodes.append(node)
        if isinstance(brick, dict):
            dict_bricks.append(brick)

    reasons.extend(_duplicate_ids(dict_bricks))
    return reasons, nodes, dict_bricks


def validate_design(design):
    """§9.1 validation of a full Design (Initial or finalized Revised)."""
    parsed, err = _parse(design)
    if err:
        return err

    reasons = []
    for key in TOP_FIELDS:
        if key not in parsed:
            reasons.append(_reason("missing_field", None, f"design missing '{key}'"))
    for key in parsed:
        if key not in TOP_FIELDS:
            reasons.append(_reason("unknown_key", None, f"design has unknown key '{key}'"))

    if "design_version" in parsed:
        version = parsed["design_version"]
        if not _is_int(version):
            reasons.append(_reason("invalid_type", None, "design_version must be an int"))
        elif version < 1:
            reasons.append(_reason("invalid_value", None, "design_version must be >= 1"))

    if "parent_version" in parsed and parsed["parent_version"] is not None and not _is_int(parsed["parent_version"]):
        reasons.append(_reason("invalid_type", None, "parent_version must be an int or null"))

    if "object_type" in parsed and parsed["object_type"] != "CHAIR":
        reasons.append(_reason("invalid_value", None, f"object_type '{parsed['object_type']}' not allowed"))

    if "source" in parsed and parsed["source"] not in ("MOCK", "LLM"):
        reasons.append(_reason("invalid_value", None, f"source '{parsed['source']}' not allowed"))

    nodes = []
    if "bricks" in parsed:
        bricks_reasons, nodes, _ = _validate_bricks_list(parsed, allow_none_id=False)
        reasons.extend(bricks_reasons)

    reasons.extend(_geometry_violations(nodes))
    return reasons


def _collect_design_ids(design):
    if not isinstance(design, dict) or not isinstance(design.get("bricks"), list):
        return set()
    return {b.get("block_id") for b in design["bricks"] if isinstance(b, dict) and isinstance(b.get("block_id"), str)}


def _same_brick_values(a, b):
    return all(a.get(key) == b.get(key) and type(a.get(key)) is type(b.get(key)) for key in VALUE_FIELDS)


def _assembled_preserved(bricks, current):
    if not isinstance(current, list):
        return []
    by_id = {}
    for brick in bricks:
        bid = brick.get("block_id")
        if isinstance(bid, str):
            by_id.setdefault(bid, []).append(brick)

    reasons = []
    for cur in current:
        if not isinstance(cur, dict):
            continue
        cid = cur.get("block_id")
        matches = by_id.get(cid, [])
        if len(matches) != 1 or not _same_brick_values(matches[0], cur):
            reasons.append(_reason("assembled_not_preserved", cid, f"assembled block_id '{cid}' not preserved"))
    return reasons


def validate_revised(candidate, input_design, current):
    """§9.1 validation of a Revised candidate before Python assigns new block_ids."""
    parsed, err = _parse(candidate)
    if err:
        return err

    reasons = []
    if "bricks" not in parsed:
        reasons.append(_reason("missing_field", None, "design missing 'bricks'"))
    for key in parsed:
        if key not in TOP_FIELDS:
            reasons.append(_reason("unknown_key", None, f"design has unknown key '{key}'"))

    nodes, dict_bricks = [], []
    if "bricks" in parsed:
        bricks_reasons, nodes, dict_bricks = _validate_bricks_list(parsed, allow_none_id=True)
        reasons.extend(bricks_reasons)

    design_ids = _collect_design_ids(input_design)
    for brick in dict_bricks:
        bid = brick.get("block_id")
        if isinstance(bid, str) and bid not in design_ids:
            reasons.append(_reason("unknown_block_id", bid, f"block_id '{bid}' not in input design"))

    reasons.extend(_geometry_violations(nodes))
    reasons.extend(_assembled_preserved(dict_bricks, current))
    return reasons


def _check_current(current, design_ids):
    if not isinstance(current, list):
        return [_reason("invalid_type", None, "current must be a list")]

    reasons = []
    nodes = []
    dict_bricks = [b for b in current if isinstance(b, dict)]
    for brick in current:
        brick_reasons, node = _check_brick(brick, allow_none_id=False, reject_unknown_keys=False)
        reasons.extend(brick_reasons)
        if node is not None:
            nodes.append(node)

    for brick in dict_bricks:
        bid = brick.get("block_id")
        if isinstance(bid, str) and bid not in design_ids:
            reasons.append(_reason("unknown_block_id", bid, f"current block_id '{bid}' not in design"))

    reasons.extend(_duplicate_ids(dict_bricks))
    reasons.extend(_overlap_violations(nodes))  # support/connectivity are not input errors (§9.1, §10)
    return reasons


def _check_differences(differences):
    if not isinstance(differences, list):
        return [_reason("invalid_type", None, "differences must be a list")]
    if not differences:
        return [_reason("invalid_value", None, "differences must not be empty")]

    reasons = []
    for diff in differences:
        if not isinstance(diff, dict):
            reasons.append(_reason("invalid_type", None, "difference must be an object"))
            continue
        if "expected" not in diff:
            reasons.append(_reason("missing_field", None, "difference missing 'expected'"))
        if "actual" not in diff:
            reasons.append(_reason("missing_field", None, "difference missing 'actual'"))

        expected, actual = diff.get("expected"), diff.get("actual")
        if expected is None and actual is None:
            reasons.append(_reason("invalid_value", None, "difference expected and actual both null"))
        if expected is not None:
            reasons.extend(_check_brick(expected, allow_none_id=False, reject_unknown_keys=False)[0])
        if actual is not None:
            reasons.extend(_check_brick(actual, allow_none_id=False, reject_unknown_keys=False)[0])
    return reasons


def check_intervention_input(design, current, differences):
    """Reasons for an INVALID_INPUT verdict on run_intervention's arguments (§9.1, §10)."""
    reasons = list(validate_design(design))

    parsed_design, _ = _parse(design)
    design_ids = _collect_design_ids(parsed_design)
    reasons.extend(_check_current(current, design_ids))
    reasons.extend(_check_differences(differences))
    return reasons


def current_support_violations(current):
    """Support reasons for Current bricks only (§8.11 escalation trigger, not an input error)."""
    if not isinstance(current, list):
        return []
    nodes = []
    for brick in current:
        _, node = _check_brick(brick, allow_none_id=False, reject_unknown_keys=False)
        if node is not None:
            nodes.append(node)
    return _support_violations(nodes)
