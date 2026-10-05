"""Design 생성.

목적:
    어떤 Brick(color·geometry)을 Board의 어느 grid_x / grid_y / layer /
    orientation_deg에 놓는지 담은 Design을 만든다.

구현 범위 (WAVE 3, Mock):
    - build_initial_design: Mock Initial Design(다리 4개 + 좌석·등받이 구조) 생성,
      center_bricks로 24x24 Board 중앙 배치(§3.3), block_id B001..순서 발급,
      validator.validate_design 통과까지 _generate_until_valid로 재생성.
      주입된 generate가 malformed 후보(JSON 문자열·bricks 없음·필드 누락)를 내도
      예외를 던지지 않고 거부 사유로 반환한다(§4, §8.10)
    - build_revised_design: validator.check_intervention_input으로 입력 검사 →
      current_support_violations로 §8.11 escalation 트리거 판정(재생성 없이 반환) →
      Mock Revised 후보(mock_revised_candidate) 생성 → validator.validate_revised →
      통과하면 block_id가 null인 Brick만 Python이 새 ID 발급 → 최종 Design을
      validator.validate_design으로 한 번 더 확인(새로 만든 ID 조합이라 방어적으로 재검증)
    - generate 인자로 LLM 등 다른 생성기를 주입할 수 있게 열어 두되, Mock 생성기는
      결정론적이라 재생성하지 않는다(main·test는 max_attempts=1로 호출)
    - Mock Revised는 다리(layer 1)만 조립된 상태를 다룬다; layer ≥ 2 Brick이 이미
      조립돼 재설계 상부와 겹치면 검증이 거부하고 사유를 반환한다(실제 LLM 경로·
      main escalation 몫)

하지 않는 것(다음 WAVE):
    - 실제 LLM 호출 연결(llm.py). generate 인자로 주입 가능하도록만 열어둠(WAVE 5)
    - 연속 거부 시 전략 전환·LLM backoff·6회마다 escalation 질문(§8.10·§8.11)은
      main이 맡는다(WAVE 4). 이 모듈은 단일 재생성 loop(_generate_until_valid)만 제공
    - 사람 조립 순서·NextPart·남은 작업·Replan(A 담당)
    - Robot mm 좌표·Board→Robot 변환·TCP / Joint / trajectory
    - 검증 규칙 자체 구현(validator.py 담당)

연결:
    main.py 가 호출한다. validator.py 를 호출한다. (LLM 연결은 WAVE 5)
"""

import time

from app.c_design import validator

RETRY_DELAY = 1.0

BOARD_SIZE = 24


def center_bricks(bricks):
    """bricks를 그대로 평행 이동해 전체 footprint bounding box를 Board 중앙에 맞춘다(§3.3).

    특정 Brick anchor를 24 // 2에 두지 않는다: bbox 최소 stud를 공식대로 옮기므로
    짝수/홀수 폭 모두 금지된 (12, 12) 중심 앵커를 쓰지 않는다.
    """
    cells = set()
    for brick in bricks:
        cells |= validator.footprint(brick)
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width, height = max_x - min_x + 1, max_y - min_y + 1
    dx = (BOARD_SIZE - width) // 2 - min_x
    dy = (BOARD_SIZE - height) // 2 - min_y
    return [dict(brick, grid_x=brick["grid_x"] + dx, grid_y=brick["grid_y"] + dy) for brick in bricks]


def _generate_until_valid(make_candidate, finalize, max_attempts, delay):
    """§8.10 재생성 loop. 거부는 실패가 아니라 후보 하나의 거부일 뿐이다.

    make_candidate(reasons)는 직전 거부 사유([] 첫 시도)를 받아 후보를 만든다.
    finalize(candidate)는 (design, reasons)를 돌려준다: design이 있으면 통과.
    """
    reasons = []
    attempts = 0
    while True:
        candidate = make_candidate(reasons)
        design, reasons = finalize(candidate)
        if design is not None:
            return {"design": design, "reasons": [], "attempts": attempts + 1}
        attempts += 1
        if max_attempts is not None and attempts >= max_attempts:
            return {"design": None, "reasons": reasons, "attempts": attempts}
        if delay > 0:
            time.sleep(delay)  # busy loop 금지(§8.10)


def build_initial_design(object_type, generate=None, max_attempts=None, delay=RETRY_DELAY):
    """Initial Design(design_version=1, parent_version=None)을 만든다(§3.3, §8.4)."""
    if object_type != "CHAIR":
        reason = {"rule": "unsupported_object", "block_ids": [], "message": f"object_type '{object_type}' not supported"}
        return {"design": None, "reasons": [reason], "attempts": 0}

    make = generate or mock_initial_candidate
    source = "LLM" if generate else "MOCK"

    def make_candidate(prev_reasons):
        return make(object_type, prev_reasons)

    def finalize(candidate):
        if not isinstance(candidate, dict) or not isinstance(candidate.get("bricks"), list):
            return None, [{"rule": "malformed_output", "block_ids": [], "message": "candidate is not an object with a bricks list"}]

        bricks = [
            dict(brick, block_id=f"B{i + 1:03d}") if isinstance(brick, dict) else brick
            for i, brick in enumerate(candidate["bricks"])
        ]
        design = {
            "design_version": 1,
            "parent_version": None,
            "object_type": object_type,
            "source": source,
            "bricks": bricks,
        }
        reasons = validator.validate_design(design)
        if any(r["rule"] != "out_of_board" for r in reasons):
            return None, reasons
        # 남은 거부 사유가 없거나 out_of_board뿐일 때만 center_bricks를 시도한다:
        # 그 외 형식 오류가 있으면 footprint()가 well-formed brick을 전제하므로 그대로 거부한다.
        design = dict(design, bricks=center_bricks(bricks))
        reasons = validator.validate_design(design)
        if reasons:
            return None, reasons
        return design, []

    return _generate_until_valid(make_candidate, finalize, max_attempts, delay)


def _max_block_num(design):
    nums = [int(brick["block_id"][1:]) for brick in design["bricks"] if isinstance(brick.get("block_id"), str)]
    return max(nums) if nums else 0


def build_revised_design(design, current, differences, generate=None, max_attempts=None, delay=RETRY_DELAY):
    """Revised Design(입력 design.design_version + 1)을 만든다(§8). full object, patch 아님."""
    input_reasons = validator.check_intervention_input(design, current, differences)
    if input_reasons:
        return {"design": None, "reasons": input_reasons, "attempts": 0}

    support_reasons = validator.current_support_violations(current)
    if support_reasons:
        # current 자체가 support를 위반하면 보존한 채로 통과할 후보가 없으므로
        # 재생성을 시작하지 않고 main의 §8.11 escalation으로 바로 넘긴다.
        block_ids = [bid for reason in support_reasons for bid in reason["block_ids"]]
        reason = {
            "rule": "current_support_violation",
            "block_ids": block_ids,
            "message": "current violates support and cannot be preserved as-is",
        }
        return {"design": None, "reasons": [reason], "attempts": 0}

    make = generate or mock_revised_candidate
    source = "LLM" if generate else "MOCK"
    next_num = _max_block_num(design) + 1

    def make_candidate(prev_reasons):
        return make(design, current, differences, prev_reasons)

    def finalize(candidate):
        reasons = validator.validate_revised(candidate, design, current)
        if reasons:
            return None, reasons

        bricks = []
        new_num = next_num
        for brick in candidate["bricks"]:
            if brick.get("block_id") is None:
                bricks.append(dict(brick, block_id=f"B{new_num:03d}"))
                new_num += 1
            else:
                bricks.append(dict(brick))

        final = {
            "design_version": design["design_version"] + 1,
            "parent_version": design["design_version"],
            "object_type": design["object_type"],
            "source": source,
            "bricks": bricks,
        }
        # id 배정은 이번에 새로 만든 데이터라 방어적으로 다시 검증한다.
        final_reasons = validator.validate_design(final)
        if final_reasons:
            return None, final_reasons
        return final, []

    return _generate_until_valid(make_candidate, finalize, max_attempts, delay)


# ---- Mock 생성기(§8.10: 결정론적이라 재생성하지 않음) ----

BRICK_VALUE_KEYS = ("geometry", "grid_x", "grid_y", "orientation_deg", "layer", "color")


def _brick(geometry, grid_x, grid_y, orientation_deg, layer, color):
    return {
        "geometry": geometry,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "orientation_deg": orientation_deg,
        "layer": layer,
        "color": color,
    }


def _xrange(brick):
    xs = [x for x, _ in validator.footprint(brick)]
    return min(xs), max(xs)


def _yrange(brick):
    ys = [y for _, y in validator.footprint(brick)]
    return min(ys), max(ys)


BASE_LEGS = (
    _brick("2x3x1", 0, 0, 0, 1, "BLUE"),
    _brick("2x3x1", 4, 0, 0, 1, "BLUE"),
    _brick("2x3x1", 0, 3, 0, 1, "BLUE"),
    _brick("2x3x1", 4, 3, 0, 1, "BLUE"),
)


def _chair_upper(legs):
    """다리(legs) 위에 좌석·등받이·상단 bridge를 쌓는다. 처리 못 하는 배치는 None(§9.1이 거부)."""
    if not legs:  # 조립된 다리가 상대편 다리를 밀어내 한쪽이 통째로 비는 경우(§4: 예외 없이 None)
        return None
    all_x = [x for leg in legs for x in _xrange(leg)]
    mid = (min(all_x) + max(all_x)) / 2
    sides = {
        "L": [leg for leg in legs if sum(_xrange(leg)) / 2 < mid],
        "R": [leg for leg in legs if sum(_xrange(leg)) / 2 >= mid],
    }

    out = []
    back_row = {}
    strip = {}
    for side, side_legs in sides.items():
        if len(side_legs) != 2:  # Mock은 한 쪽에 다리 2개인 chair만 안다; 그 외는 validator가 거부
            return None
        front, back = sorted(side_legs, key=lambda leg: _yrange(leg)[0])
        side_x = min(_xrange(leg)[0] for leg in side_legs) if side == "L" else max(_xrange(leg)[1] for leg in side_legs) - 2
        strip[side] = (side_x, side_x + 2)
        f0, f1 = _yrange(front)
        k0, k1 = _yrange(back)
        if k0 == f1 + 1:  # 다리가 맞붙음: 앞에서부터 2칸씩 좌석을 채움, 각 행 경계가 다리 안에 들어감
            rows = list(range(f0, k1, 2))
            for y in rows:
                out.append(_brick("2x3x1", side_x, y, 90, 2, "YELLOW"))
            back_row[side] = rows[-1]
        elif k0 == f1 + 2:  # 다리 사이 빈 행 1개: 3칸짜리 connector로 앞뒤를 잇는다
            link_x = min(_xrange(front)[0], _xrange(back)[0])
            out.append(_brick("2x3x1", side_x, f0, 90, 2, "YELLOW"))
            out.append(_brick("2x3x1", link_x, f1, 0, 2, "YELLOW"))
            out.append(_brick("2x3x1", side_x, k1 - 1, 90, 2, "YELLOW"))
            back_row[side] = k1 - 1
        else:
            return None

    for side in ("L", "R"):
        out.append(_brick("2x3x1", strip[side][0], back_row[side], 90, 3, "BLUE"))  # 등받이
    out.append(_brick("2x2x1", strip["L"][0], back_row["L"], 0, 4, "BLUE"))
    out.append(_brick("2x2x1", strip["R"][1] - 1, back_row["R"], 0, 4, "BLUE"))
    gap = strip["R"][0] - strip["L"][1] - 1  # 상단 bridge가 좌우 반쪽을 연결한다
    if gap == 0:
        out.append(_brick("2x2x1", strip["L"][1], min(back_row.values()), 0, 4, "BLUE"))
    elif gap == 1:
        out.append(_brick("2x3x1", strip["L"][1], min(back_row.values()), 90, 4, "BLUE"))
    else:
        return None
    return out


def mock_initial_candidate(object_type, reasons=None):
    """Mock Initial 후보(local 좌표, build_initial_design이 center_bricks로 옮긴다)."""
    del object_type, reasons  # Mock은 고정된 Chair 하나만 만들고 거부 사유에 반응하지 않는다
    return {"bricks": list(BASE_LEGS) + _chair_upper(BASE_LEGS)}


def _only_brick_fields(brick):
    # D가 주는 Current Brick은 §5처럼 extra key를 가질 수 있고, Design에는 그 7개 key만 허용된다(§3.2).
    return {"block_id": brick["block_id"], **{key: brick[key] for key in BRICK_VALUE_KEYS}}


def mock_revised_candidate(design, current, differences, reasons=None):
    """Mock Revised 후보: current를 그대로 보존하고 미조립 다리 기준으로 상부를 다시 설계한다."""
    del differences, reasons  # Mock은 current/design 구조만으로 재설계하고 사유·Difference 문구는 쓰지 않는다

    fixed_ids = {brick["block_id"] for brick in current}
    fixed_cells = {(brick["layer"],) + cell for brick in current for cell in validator.footprint(brick)}
    design_legs = [
        brick
        for brick in design["bricks"]
        if brick["layer"] == 1
        and brick["block_id"] not in fixed_ids
        and not any((1,) + cell in fixed_cells for cell in validator.footprint(brick))
    ]
    legs = [brick for brick in current if brick["layer"] == 1] + design_legs
    upper = _chair_upper(legs) or []

    out = [_only_brick_fields(brick) for brick in current]
    out += [_only_brick_fields(leg) for leg in design_legs]

    pool = {
        layer: [brick["block_id"] for brick in design["bricks"] if brick["layer"] == layer and brick["block_id"] not in fixed_ids]
        for layer in (2, 3, 4)
    }
    for new_brick in upper:
        block_id = pool[new_brick["layer"]].pop(0) if pool[new_brick["layer"]] else None
        out.append(dict(new_brick, block_id=block_id))

    return {"bricks": out}
