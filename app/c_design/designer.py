"""Design 생성.

목적:
    어떤 Block(brick_type·color)을 Board의 어느 x / y / layer /
    orientation_deg에 놓는지 담은 Design을 만든다.

구현 범위 (WAVE 3, Mock):
    - build_initial_design: Mock Initial Design(다리 4개 + 좌석·등받이 구조) 생성,
      center_blocks로 24x24 Board 중앙 배치(§3.3), validator.validate_design 통과까지
      _generate_until_valid로 재생성. 주입된 generate가 malformed 후보(JSON 문자열·
      blocks 없음·필드 누락)를 내도 예외를 던지지 않고 거부 사유로 반환한다(§8.10)
    - build_revised_design: validator.check_intervention_input으로 입력 검사 →
      current_support_violations로 escalation 트리거 판정(재생성 없이 반환) →
      Mock Revised 후보(mock_revised_candidate) 생성 → validator.validate_revised →
      통과하면 최종 Design을 validator.validate_design으로 한 번 더 확인(방어적
      재검증). 최종 blocks 멀티셋이 입력 Design의 blocks 멀티셋과 순서 무관하게
      같으면 design_version을 올리지 않고 입력 Design을 그대로 반환한다(§4:
      전체 목표 배치가 실제 바뀔 때만 +1)
    - 블록 ID는 두지 않는다: Design/Current/Revised 어디에도 ID를
      붙이거나 재사용하지 않는다
    - 재생성 loop은 MAX_ATTEMPTS(기본 10)회로 제한된다(무제한 None은 더 이상
      기본값이 아니다). should_stop(인자 없는 callable)이 주어지면 각 시도 사이
      (처음 시도 다음부터) 호출해 True면 즉시 "stopped" 사유로 중단한다
    - 결과 dict은 {"design", "reasons", "attempts", "source"}이며 source("MOCK"
      또는 "LLM")는 어떤 생성기를 썼는지 보여주는 진단 정보일 뿐 Design 객체
      안에는 들어가지 않는다
    - generate 인자로 LLM 등 다른 생성기를 주입할 수 있게 열어 두되, Mock 생성기는
      결정론적이라 재생성하지 않는다(main·test는 max_attempts=1로 호출)
    - Mock Revised는 다리(layer 1)만 조립된 상태를 다룬다; layer ≥ 2 Block이 이미
      조립돼 재설계 상부와 겹치면 검증이 거부하고 사유를 반환한다(실제 LLM 경로·
      main escalation 몫)

하지 않는 것(다음 WAVE):
    - 실제 LLM 호출 연결(llm.py). generate 인자로 주입 가능하도록만 열어둠(WAVE 5)
    - 연속 거부 시 전략 전환·LLM backoff·escalation 질문은 main이 맡는다(WAVE 4).
      이 모듈은 단일 재생성 loop(_generate_until_valid)과 should_stop 훅만 제공
    - 사람 조립 순서·NextPart·남은 작업·Replan(A 담당)
    - Robot mm 좌표·Board→Robot 변환·TCP / Joint / trajectory
    - 검증 규칙 자체 구현(validator.py 담당)

연결:
    main.py 가 호출한다. validator.py 를 호출한다. (LLM 연결은 WAVE 5)
"""

import json
import time
from collections import Counter

from app.c_design import validator

RETRY_DELAY = 1.0
MAX_ATTEMPTS = 10

BOARD_SIZE = 24


def center_blocks(blocks):
    """blocks를 그대로 평행 이동해 전체 footprint bounding box를 Board 중앙에 맞춘다(§3.3).

    특정 Block anchor를 24 // 2에 두지 않는다: bbox 최소 stud를 공식대로 옮기므로
    짝수/홀수 폭 모두 금지된 (12, 12) 중심 앵커를 쓰지 않는다.
    """
    cells = set()
    for block in blocks:
        cells |= validator.footprint(block)
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width, height = max_x - min_x + 1, max_y - min_y + 1
    dx = (BOARD_SIZE - width) // 2 - min_x
    dy = (BOARD_SIZE - height) // 2 - min_y
    return [dict(block, x=block["x"] + dx, y=block["y"] + dy) for block in blocks]


def _generate_until_valid(make_candidate, finalize, max_attempts, delay, should_stop=None):
    """재생성 loop. 거부는 실패가 아니라 후보 하나의 거부일 뿐이다(§8.10).

    make_candidate(reasons)는 직전 거부 사유([] 첫 시도)를 받아 후보를 만든다.
    finalize(candidate)는 (design, reasons)를 돌려준다: design이 있으면 통과.
    should_stop은 처음 시도 다음부터, 매 시도 사이에 확인한다(처음 시도 전에는
    확인하지 않는다).
    """
    reasons = []
    attempts = 0
    while True:
        candidate = make_candidate(reasons)
        if isinstance(candidate, dict) and "llm_error" in candidate:
            # provider 실패는 후보 거부가 아니므로 재생성하지 않고 끝낸다(API 재시도는 llm.py).
            kind = candidate["llm_error"].get("kind")
            rule = "stopped" if kind == "stopped" else "llm_call_failed"
            return {"design": None, "reasons": [{"rule": rule, "blocks": [], "message": kind}], "attempts": attempts}
        design, reasons = finalize(candidate)
        if design is not None:
            return {"design": design, "reasons": [], "attempts": attempts + 1}
        attempts += 1
        if max_attempts is not None and attempts >= max_attempts:
            return {"design": None, "reasons": reasons, "attempts": attempts}
        if should_stop is not None and should_stop():
            reason = {"rule": "stopped", "blocks": [], "message": "generation stopped before next attempt"}
            return {"design": None, "reasons": [reason], "attempts": attempts}
        if delay > 0:
            time.sleep(delay)  # busy loop 금지(§8.10)


def build_initial_design(object_type, generate=None, max_attempts=MAX_ATTEMPTS, delay=RETRY_DELAY, should_stop=None):
    """Initial Design(design_version=1)을 만든다(§3.3)."""
    source = "LLM" if generate else "MOCK"

    if object_type != "CHAIR":
        reason = {"rule": "unsupported_object", "blocks": [], "message": f"object_type '{object_type}' not supported"}
        return {"design": None, "reasons": [reason], "attempts": 0, "source": source}

    make = generate or mock_initial_candidate
    if generate is None:
        max_attempts = 1  # Mock은 결정론적이라 같은 후보를 다시 만들 뿐이다(§8.10)

    def make_candidate(prev_reasons):
        return make(object_type, prev_reasons)

    def finalize(candidate):
        if not isinstance(candidate, dict) or not isinstance(candidate.get("blocks"), list):
            reason = {"rule": "malformed_output", "blocks": [], "message": "candidate is not an object with a blocks list"}
            return None, [reason]

        blocks = [dict(block) if isinstance(block, dict) else block for block in candidate["blocks"]]
        design = {"design_version": 1, "blocks": blocks}
        reasons = validator.validate_design(design)
        if any(r["rule"] != "out_of_board" for r in reasons):
            return None, reasons
        # 남은 거부 사유가 없거나 out_of_board뿐일 때만 center_blocks를 시도한다:
        # 그 외 형식 오류가 있으면 footprint()가 well-formed block을 전제하므로 그대로 거부한다.
        design = {"design_version": 1, "blocks": center_blocks(blocks)}
        reasons = validator.validate_design(design)
        if reasons:
            return None, reasons
        return design, []

    if generate is not None and should_stop is not None and should_stop():
        # 주입된 생성기(LLM)는 호출 비용이 있으므로 첫 호출 전에도 STOP을 확인한다.
        reason = {"rule": "stopped", "blocks": [], "message": "generation stopped before the first attempt"}
        return {"design": None, "reasons": [reason], "attempts": 0, "source": source}
    result = _generate_until_valid(make_candidate, finalize, max_attempts, delay, should_stop)
    result["source"] = source
    return result


def build_revised_design(design, current, differences, generate=None, max_attempts=MAX_ATTEMPTS, delay=RETRY_DELAY, should_stop=None):
    """Revised Design(입력 design.design_version + 1, 레이아웃이 실제로 바뀔 때만)을
    만든다. full object, patch 아님."""
    source = "LLM" if generate else "MOCK"

    input_reasons = validator.check_intervention_input(design, current, differences)
    if input_reasons:
        return {"design": None, "reasons": input_reasons, "attempts": 0, "source": source}

    support_reasons = validator.current_support_violations(current)
    if support_reasons:
        # current 자체가 support를 위반하면 보존한 채로 통과할 후보가 없으므로
        # 재생성을 시작하지 않고 main의 escalation으로 바로 넘긴다.
        blocks = [b for reason in support_reasons for b in reason["blocks"]]
        reason = {
            "rule": "current_support_violation",
            "blocks": blocks,
            "message": "current violates support and cannot be preserved as-is",
        }
        return {"design": None, "reasons": [reason], "attempts": 0, "source": source}

    make = generate or mock_revised_candidate
    if generate is None:
        max_attempts = 1  # Mock은 결정론적이라 같은 후보를 다시 만들 뿐이다(§8.10)

    def make_candidate(prev_reasons):
        return make(design, current, differences, prev_reasons)

    def finalize(candidate):
        if isinstance(candidate, dict):
            # 후보의 design_version은 무시한다: 버전은 designer가 정한다(§8.2). 다른 키는 그대로 검증.
            candidate = {key: value for key, value in candidate.items() if key != "design_version"}
        reasons = validator.validate_revised(candidate, current)
        if reasons:
            return None, reasons

        parsed = json.loads(candidate) if isinstance(candidate, str) else candidate
        blocks = [dict(block) for block in parsed["blocks"]]

        if _same_blocks(blocks, design["blocks"]):
            # 목표 배치가 실제로 바뀌지 않았으면 design_version을 올리지 않는다(§4).
            return design, []

        final = {"design_version": design["design_version"] + 1, "blocks": blocks}
        # 새로 조합한 blocks라 방어적으로 다시 검증한다.
        final_reasons = validator.validate_design(final)
        if final_reasons:
            return None, final_reasons
        return final, []

    if generate is not None and should_stop is not None and should_stop():
        # 주입된 생성기(LLM)는 호출 비용이 있으므로 첫 호출 전에도 STOP을 확인한다.
        reason = {"rule": "stopped", "blocks": [], "message": "generation stopped before the first attempt"}
        return {"design": None, "reasons": [reason], "attempts": 0, "source": source}
    result = _generate_until_valid(make_candidate, finalize, max_attempts, delay, should_stop)
    result["source"] = source
    return result


def _same_blocks(blocks_a, blocks_b):
    """순서 무관 멀티셋 비교(§4: KEEP / 배열 순서 변경만으로 version 증가하지 않음)."""

    def tup(block):
        return tuple(block.get(key) for key in validator.BLOCK_FIELDS)

    return Counter(tup(b) for b in blocks_a) == Counter(tup(b) for b in blocks_b)


# ---- Mock 생성기(§8.10: 결정론적이라 재생성하지 않음) ----


def _block(brick_type, x, y, orientation_deg, layer, color):
    return {
        "brick_type": brick_type,
        "color": color,
        "x": x,
        "y": y,
        "layer": layer,
        "orientation_deg": orientation_deg,
    }


def _only_block_fields(block):
    # D가 주는 Current Block은 §5처럼 extra key를 가질 수 있고, Design에는 그 6개 key만 허용된다(§2).
    return {key: block[key] for key in validator.BLOCK_FIELDS}


def _xrange(block):
    xs = [x for x, _ in validator.footprint(block)]
    return min(xs), max(xs)


def _yrange(block):
    ys = [y for _, y in validator.footprint(block)]
    return min(ys), max(ys)


BASE_LEGS = (
    _block("2x3x1", 0, 0, 0, 1, "blue"),
    _block("2x3x1", 4, 0, 0, 1, "blue"),
    _block("2x3x1", 0, 3, 0, 1, "blue"),
    _block("2x3x1", 4, 3, 0, 1, "blue"),
)


def _chair_upper(legs):
    """다리(legs) 위에 좌석·등받이·상단 bridge를 쌓는다. 처리 못 하는 배치는 None(거부)."""
    if not legs:  # 조립된 다리가 상대편 다리를 밀어내 한쪽이 통째로 비는 경우(예외 없이 None)
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
                out.append(_block("2x3x1", side_x, y, 90, 2, "yellow"))
            back_row[side] = rows[-1]
        elif k0 == f1 + 2:  # 다리 사이 빈 행 1개: 3칸짜리 connector로 앞뒤를 잇는다
            link_x = min(_xrange(front)[0], _xrange(back)[0])
            out.append(_block("2x3x1", side_x, f0, 90, 2, "yellow"))
            out.append(_block("2x3x1", link_x, f1, 0, 2, "yellow"))
            out.append(_block("2x3x1", side_x, k1 - 1, 90, 2, "yellow"))
            back_row[side] = k1 - 1
        else:
            return None

    for side in ("L", "R"):
        out.append(_block("2x3x1", strip[side][0], back_row[side], 90, 3, "blue"))  # 등받이
    out.append(_block("2x2x1", strip["L"][0], back_row["L"], 0, 4, "blue"))
    out.append(_block("2x2x1", strip["R"][1] - 1, back_row["R"], 0, 4, "blue"))
    gap = strip["R"][0] - strip["L"][1] - 1  # 상단 bridge가 좌우 반쪽을 연결한다
    if gap == 0:
        out.append(_block("2x2x1", strip["L"][1], min(back_row.values()), 0, 4, "blue"))
    elif gap == 1:
        out.append(_block("2x3x1", strip["L"][1], min(back_row.values()), 90, 4, "blue"))
    else:
        return None
    return out


def mock_initial_candidate(object_type, reasons=None):
    """Mock Initial 후보(local 좌표, build_initial_design이 center_blocks로 옮긴다)."""
    del object_type, reasons  # Mock은 고정된 Chair 하나만 만들고 거부 사유에 반응하지 않는다
    return {"blocks": list(BASE_LEGS) + _chair_upper(BASE_LEGS)}


def mock_revised_candidate(design, current, differences, reasons=None):
    """Mock Revised 후보: current를 그대로 보존하고 미조립 다리 기준으로 상부를 다시 설계한다."""
    del differences, reasons  # Mock은 current/design 구조만으로 재설계하고 사유·Difference 문구는 쓰지 않는다

    current_legs = [block for block in current if block["layer"] == 1]
    current_leg_cells = {cell for block in current_legs for cell in validator.footprint(block)}
    design_legs = [
        block
        for block in design["blocks"]
        if block["layer"] == 1 and not (validator.footprint(block) & current_leg_cells)
    ]
    legs = current_legs + design_legs
    upper = _chair_upper(legs) or []

    out = [_only_block_fields(block) for block in current]
    out += [_only_block_fields(block) for block in design_legs]
    out += upper

    return {"blocks": out}
