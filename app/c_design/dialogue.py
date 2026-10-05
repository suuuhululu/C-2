"""C 대화의 텍스트 처리(순수 텍스트).

목적:
    질문 문장을 만들고 사용자 텍스트 응답을 HRI 결과로 해석한다.

제공하는 기능:
    - 선택지 상수: 1번 = KEEP_ORIGINAL(Original 유지), 2번 = CREATE_REVISED(Revised 생성)
      (질문 문장과 응답 해석이 같은 OPTIONS 상수를 공유)
    - 변경 context(채택 Design·Current·Difference)에 따른 질문 문장 생성(build_question)
    - 재질문(build_reask), 침묵 시 확인 질문·상태 확인 질문·무응답 최종 안내 문장(§4.3)
    - escalation 질문 문장(§8.11, 잘못 놓인 Brick을 채택 Design 위치로 옮기기 제안)
    - 사용자 텍스트 응답 해석 → KEEP_ORIGINAL / CREATE_REVISED / UNCLEAR(불명확).
      명확한 응답은 Python Rule(정규화 → 전체 일치 → 구문 일치 → 부정 감지),
      애매한 응답만 llm_fallback으로 넘기고, 그래도 애매하면 UNCLEAR
    - 최초 목표 사물 인식(parse_goal, Day 4는 CHAIR만)

하지 않는 것:
    - 실제 음성 I/O(녹음·STT·TTS는 voice.py 담당)
    - 대화 루프·재질문 반복·무응답 시계(main.py 담당)
    - Design 생성·검증
    - Data Association(Brick 대응은 D가 준 block_id를 그대로 씀)

연결:
    main.py 가 호출한다. 애매한 응답일 때만 호출자가 llm.py fallback을 넘긴다.
"""

import re

KEEP_ORIGINAL = "KEEP_ORIGINAL"
CREATE_REVISED = "CREATE_REVISED"
UNCLEAR = "UNCLEAR"
# 질문 문장과 응답 해석이 같은 상수를 공유한다(§1).
OPTIONS = {"1": KEEP_ORIGINAL, "2": CREATE_REVISED}

MOVE_BACK = "MOVE_BACK"
KEEP_SEARCHING = "KEEP_SEARCHING"
ESCALATION_OPTIONS = {"1": MOVE_BACK, "2": KEEP_SEARCHING}

_OPTION_LABELS = {
    KEEP_ORIGINAL: "원래 설계대로 고치기 (Original 유지)",
    CREATE_REVISED: "지금 놓인 상태를 살린 새 설계 (Revised 생성)",
}

# Difference의 어떤 필드가 다른지 질문 문장에 쓸 한국어 단어(§5.2).
_FIELD_LABELS = {
    "grid_x": "위치",
    "grid_y": "위치",
    "orientation_deg": "방향",
    "color": "색",
    "geometry": "크기",
    "layer": "층",
}

# 숫자 표현 토큰(전체 일치 전용, 한글 수사 포함). §8.11 응답 해석에도 재사용한다.
_NUMBER_WORD_TOKENS = {
    "1": ("1", "1번", "일번", "일"),
    "2": ("2", "2번", "이번", "이"),
}
# 문장 속에 섞여 나온 숫자 탐색은 숫자 기반 토큰만 본다. 한글 "이번"은
# "this time"과 겹치는 표현이라 문장 내부 탐색에서는 쓰지 않는다(§4.2 규칙 d).
_EMBEDDED_DIGIT_RE = re.compile(r"1번|2번|1|2")

# 전체 일치 단계에서만 쓰는 공손체 어미. 구문 일치 단계에서는 벗기지 않는다.
_ENDINGS = tuple(
    sorted({"요", "이요", "할게", "할게요", "해줘", "으로", "로"}, key=len, reverse=True)
)

_KEEP_CREATE_PHRASES = {
    KEEP_ORIGINAL: ("원래대로", "원래설계", "원래위치"),
    CREATE_REVISED: ("이대로", "지금상태", "현재상태", "이대로유지"),
}
_ESCALATION_PHRASES = {
    MOVE_BACK: ("옮길게", "옮기기", "옮겨"),
    KEEP_SEARCHING: ("계속찾", "계속해", "새설계"),
}

_NEGATION_MARKERS = ("싫어", "싫", "하지마", "하지 마", "아니", "안 해", "안해")


def _normalize(text):
    """공백·구두점 제거. 한글 음절·숫자는 \\w라서 그대로 남는다."""
    return re.sub(r"[^\w]", "", text)


def _strip_endings(text):
    """숫자 토큰 전체 일치 비교 전용 어미 제거(최장 일치 1회)."""
    for ending in _ENDINGS:
        if len(text) > len(ending) and text.endswith(ending):
            return text[: -len(ending)]
    return text


def _match_number_whole(norm, option_map):
    stripped = _strip_endings(norm)
    return {
        option_map[digit]
        for digit, tokens in _NUMBER_WORD_TOKENS.items()
        if stripped in tokens
    }


def _match_number_embedded(norm, option_map):
    digits = {"1" if m.group().startswith("1") else "2" for m in _EMBEDDED_DIGIT_RE.finditer(norm)}
    return {option_map[d] for d in digits}


def _match_phrase(norm, phrase_map):
    return {value for value, phrases in phrase_map.items() if any(p in norm for p in phrases)}


def _has_negation(raw_text):
    return any(marker in raw_text for marker in _NEGATION_MARKERS)


def _resolve(text, option_map, phrase_map, llm_fallback):
    """공유 Rule 파이프라인: 정규화 → 전체 일치 → 내부 숫자 → 구문 → 부정 → fallback."""
    working = (text or "").strip()
    if "말고" in working:
        # "A 말고 B": A는 취소된 선택이므로 B만 해석한다.
        working = working.rsplit("말고", 1)[-1].strip()
    norm = _normalize(working)

    matched = _match_number_whole(norm, option_map)
    if not matched:
        matched = _match_number_embedded(norm, option_map)
    if not matched:
        matched = _match_phrase(norm, phrase_map)

    if len(matched) > 1:
        return UNCLEAR
    if len(matched) == 1:
        candidate = next(iter(matched))
        # 부정은 뒤집지 않고 보수적으로 불명확 처리한다(§4.2 규칙 f).
        return UNCLEAR if _has_negation(working) else candidate

    if llm_fallback is not None:
        allowed = set(option_map.values()) | {UNCLEAR}
        result = llm_fallback(text)
        return result if result in allowed else UNCLEAR
    return UNCLEAR


def is_meaningful(text):
    """정규화 후 비어 있지 않은 STT 텍스트인가(§4.3 "의미 있는 발화")."""
    if text is None:
        return False
    return _normalize(text) != ""


def parse_response(text, llm_fallback=None):
    """사용자 텍스트 응답 → KEEP_ORIGINAL / CREATE_REVISED / UNCLEAR."""
    return _resolve(text, OPTIONS, _KEEP_CREATE_PHRASES, llm_fallback)


def parse_escalation_response(text, llm_fallback=None):
    """§8.11 escalation 응답 → MOVE_BACK / KEEP_SEARCHING / UNCLEAR."""
    return _resolve(text, ESCALATION_OPTIONS, _ESCALATION_PHRASES, llm_fallback)


def parse_goal(text):
    """최초 목표 문장 → "CHAIR" 또는 None(Day 4는 CHAIR만 지원, §4.1)."""
    if text and "의자" in text:
        return "CHAIR"
    return None


def _differing_fields(expected, actual):
    """expected/actual Brick 사이에 값이 다른 필드의 한국어 단어 목록(중복 제거)."""
    labels = []
    for field, label in _FIELD_LABELS.items():
        if expected.get(field) != actual.get(field) and label not in labels:
            labels.append(label)
    return labels


def _describe_difference(diff):
    """Difference 1개를 질문 문장 속 한 줄로 설명한다(Data Association 없음, §5.2)."""
    expected, actual = diff.get("expected"), diff.get("actual")
    if actual is None:
        return f"{expected['block_id']}: Design에 있지만 실제로 놓이지 않았습니다 (누락)."
    if expected is None:
        return f"{actual['block_id']}: Design에 없는 블록이 추가로 놓였습니다."
    items = _differing_fields(expected, actual)
    words = ", ".join(items) if items else "배치"
    return f"{expected['block_id']}: {words}이(가) 다릅니다."


def _choice_lines(option_map, labels):
    return [f"{num}번: {labels[option_map[num]]}" for num in sorted(option_map)]


def build_question(design, current, differences):
    """채택 Design/Current/Difference로 사용자에게 물을 질문 문장을 만든다(§4.2)."""
    del design, current  # 문구에만 쓰일 수 있으나 현재 wording에 불필요
    lines = [_describe_difference(diff) for diff in differences]
    lines.append("어떻게 할까요?")
    lines.extend(_choice_lines(OPTIONS, _OPTION_LABELS))
    return "\n".join(lines)


def build_reask(question):
    """불명확 응답 시 전체 질문을 다시 낸다(§4.2)."""
    return "잘 이해하지 못했어요. 다시 여쭤볼게요.\n" + question


def short_confirm_prompt():
    """무응답 25초: 짧은 확인 질문(§4.3)."""
    return "1번 또는 2번으로 말씀해 주세요."


def status_check_prompt():
    """무응답 60/120/180/240초: 응답 필요·선택지 재안내(§4.3)."""
    return "작업을 계속하려면 1번 원래 설계 유지 또는 2번 새 설계 중 하나를 말씀해 주세요."


def final_notice():
    """무응답 300초: 최종 안내, 이후 CANCELLED/NO_RESPONSE로 종료(§4.3)."""
    return "5분 동안 답변을 기다렸지만 응답이 없어 이번 요청을 취소 처리하겠습니다."


def escalation_question(differences):
    """§8.11: 자동 재설계가 거의 불가능할 때 잘못 놓인 Brick을 원래 위치로 옮기자고 제안."""
    parts = []
    for diff in differences:
        actual, expected = diff.get("actual"), diff.get("expected")
        if actual is None:
            continue
        if expected is not None:
            parts.append(
                f"{actual['block_id']}(grid_x={expected['grid_x']}, grid_y={expected['grid_y']}, "
                f"layer={expected['layer']})"
            )
        else:
            parts.append(actual["block_id"])
    bricks_text = ", ".join(parts) if parts else "해당 블록"
    lines = [
        "지금 놓인 블록으로는 새 설계를 만들기 어렵습니다.",
        f"{bricks_text}을(를) 원래 위치로 옮겨 주시겠어요?",
        "1번: 원래 위치로 옮기기",
        "2번: 계속 새 설계 찾기",
    ]
    return "\n".join(lines)
