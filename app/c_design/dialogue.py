"""C 대화의 텍스트 처리(순수 텍스트).

목적:
    질문 문장을 만들고 사용자의 자유 답변을 HRI 결과로 해석한다.

제공하는 기능:
    - 모든 질문·재질문·escalation 문장은 자연스러운 존댓말 주관식이다(번호·선택지 없음, 2026-10-08 사용자 확정).
    - Initial 인사(build_greeting, Stage 2 Wave 4b: C가 먼저 "오늘 어떤 걸 만들고 싶으세요?"라고 묻는다)와 첫 자유 발화 중
      명시적 "아무거나·알아서·맡길게요"류 판정(parse_initial_request → ANY 또는 None. None이면 호출자가 LLM 해석으로 넘긴다).
      지원하지 않는 사물·침묵 재질문에 쓰는 고정 문장(UNSUPPORTED_REPLY·SILENCE_REASK).
    - 진행 안내(Stage 2 Wave 4c): 단계별 고정 문장 PROGRESS_MESSAGES와 음성으로 읽는 단계 PROGRESS_TTS_STAGES,
      LLM 되읽기(reply)가 없을 때 쓰는 확인 문장(initial_ack_fallback·revise_ack_fallback)과 KEEP 확인(keep_ack).
      확인 문장은 후보 중 무작위로 고르되 바로 앞과 같은 문장은 피한다.
      앉는 가구 단어 없이 흔한 비착석 사물만 요구하는 발화는 LLM 없이 지원 밖으로 판정(is_unsupported_request).
    - 변경 context(채택 Design·Current·Difference)에 따른 Intervention 질문(build_question),
      재질문(build_reask), escalation 질문(§8.11, 잘못 놓인 블록을 채택 Design 위치로 돌려 달라는 제안).
    - 자유 답변 해석 → KEEP / REVISE / UNCLEAR(불명확) / CANCEL(명시 취소).
      명확한 답변은 Python Rule(정규화 → 취소 → 앞머리 예/아니요 → 명시 구문 → 부정 감지),
      두 부류가 함께 나오거나 아무것도 못 찾으면 llm_fallback으로 넘기고, 그래도 아니면 UNCLEAR.
      CANCEL은 HRI 결과(KEEP/REVISE/UNCLEAR)가 아니라 대화 종료를 알리는 내부 신호다.
    - 최초 목표 사물 인식(parse_goal, CHAIR만. Mock 모드·D 텍스트 호환용)

하지 않는 것:
    - 실제 음성 I/O(녹음·STT·TTS는 voice.py 담당)
    - 대화 루프·재질문 반복·LLM 호출(main.py 담당). 계속 불명확하면 명시 답변 대기(루프·대기는 main)
    - 스타일 힌트 추출(애매한 답변의 decision·style_hint는 main이 llm으로 받는다)
    - Design 생성·검증
    - Data Association(블록은 ID 없이 위치(x, y, layer)로 설명한다)

연결:
    main.py 가 호출한다. 애매한 답변일 때만 호출자가 llm.py fallback을 넘긴다.
"""

import random
import re

KEEP = "KEEP"
REVISE = "REVISE"
UNCLEAR = "UNCLEAR"
CANCEL = "CANCEL"
ANY = "ANY"

MOVE_BACK = "MOVE_BACK"
KEEP_SEARCHING = "KEEP_SEARCHING"

# 숫자 답변 호환용(질문에 노출하지 않음). Stage 1의 "1번/2번" 답변을 쓰는 D fixture·스크립트가
# 그대로 동작하도록 답변 전체가 숫자이거나 "N번"이 들어 있을 때만 조용히 받는다.
OPTIONS = {"1": KEEP, "2": REVISE}
ESCALATION_OPTIONS = {"1": MOVE_BACK, "2": KEEP_SEARCHING}

GREETING = "안녕하세요. 오늘 어떤 걸 만들고 싶으세요?"
UNSUPPORTED_REPLY = "죄송해요, 지금은 의자나 벤치 같은 앉는 가구만 만들 수 있어요."
SILENCE_REASK = "잘 못 들었어요. 오늘 어떤 걸 만들고 싶으세요?"

# 진행 단계별 고정 안내(로그·HMI·음성 공용). 음성 모드에서는 PROGRESS_TTS_STAGES만 읽는다(나머지는 로그·콜백만).
# LISTENING·UNDERSTANDING·REGENERATING·ESCALATION은 로그·콜백 전용 문장이다(음성으로 읽지 않음).
PROGRESS_MESSAGES = {
    "LISTENING": "말씀을 듣고 있어요.",
    "UNDERSTANDING": "말씀하신 내용을 이해하고 있어요.",
    "REGENERATING": "디자인을 한 번 더 다듬고 있어요.",
    "ESCALATION": "새 설계가 어려워 확인을 요청하고 있어요.",
    "GENERATING": "디자인을 생성하고 있어요.",
    "VALIDATING": "구조를 확인하고 있어요.",
    "DESCRIBING": "디자인을 정리하고 있어요.",
    "READY": "디자인이 완성됐어요.",
    "GENERATING_REVISED": "수정된 디자인을 만들고 있어요.",
    "JUDGING": "완성된 디자인을 확인하고 있어요.",
    "READY_REVISED": "수정된 디자인이 완성됐어요.",
}
PROGRESS_TTS_STAGES = ("GENERATING", "READY", "GENERATING_REVISED", "JUDGING", "READY_REVISED")

# 확인(ack) 문장 후보. LLM 되읽기가 있으면 그것을 쓰고, 없을 때(규칙 "아무거나"·숫자 답·해석 실패)만 여기서 고른다.
INITIAL_ACKS = (
    "좋아요. 제가 어울리는 스타일을 골라서 멋진 의자를 만들어볼게요.",
    "알겠어요, 제가 어울리는 의자를 골라 볼게요.",
    "좋아요. 제가 골라서 앉기 편한 의자를 만들어볼게요.",
    "네, 어울리는 디자인을 골라서 만들어볼게요.",
)
INITIAL_CONCEPT_ACKS = (
    "좋아요. {concept} 느낌을 살린 의자로 만들어볼게요.",
    "알겠어요. {concept} 분위기의 의자를 만들어볼게요.",
    "좋아요. {concept} 모습을 담은 의자로 만들어볼게요.",
)
REVISE_ACKS = (
    "알겠습니다. 지금 놓인 블록을 살려서 새로 만들어볼게요.",
    "좋아요. 놓아 주신 자리를 살린 디자인으로 다시 만들어볼게요.",
    "네, 지금 상태에 맞춰 디자인을 새로 만들어볼게요.",
)
REVISE_HINT_ACKS = (
    "알겠습니다. {hint} 느낌으로 다시 만들어볼게요.",
    "좋아요. 말씀하신 대로 {hint} 쪽으로 새로 만들어볼게요.",
    "네, {hint} 방향으로 디자인을 다시 만들어볼게요.",
)
KEEP_ACKS = (
    "네, 원래 자리로 고쳐 주시면 그대로 진행할게요.",
    "알겠습니다. 블록을 원래 자리로 옮겨 주시면 이어서 진행할게요.",
    "좋아요. 원래 디자인대로 계속할게요. 블록만 제자리로 놓아 주세요.",
)
_last_pick = {}  # 후보 묶음별 바로 앞에 고른 문장(같은 문장 연속 반복을 피한다)


def _pick(options):
    previous = _last_pick.get(options)
    choices = [option for option in options if option != previous] or list(options)
    chosen = random.choice(choices)
    _last_pick[options] = chosen
    return chosen


def keep_ack():
    """KEEP(실수라 원래 자리로 고침) 확인 문장. 후보 중 무작위, 바로 앞과 다른 문장."""
    return _pick(KEEP_ACKS)


def revise_ack_fallback(style_hint=None):
    """REVISE 확인 문장(LLM 되읽기가 없을 때: 숫자 답·해석 실패). style_hint가 있으면 그 바람을 넣는다."""
    if isinstance(style_hint, str) and style_hint.strip():
        return _pick(REVISE_HINT_ACKS).format(hint=style_hint.strip())
    return _pick(REVISE_ACKS)


def initial_ack_fallback(family=None, concept=None):
    """Initial 확인 문장(LLM 되읽기가 없을 때: 규칙 "아무거나"·침묵·해석 실패). concept가 있으면 그 느낌을 넣는다.

    family는 카탈로그 영어 키라 한국어 음성으로 읽지 않는다(받아 두기만 하며 문장은 일반 확인으로 고른다).
    """
    del family
    if isinstance(concept, str) and concept.strip():
        return _pick(INITIAL_CONCEPT_ACKS).format(concept=concept.strip())
    return _pick(INITIAL_ACKS)

_INTERVENTION_ASK = "Design과 다르게 놓인 부분이 있는데, 의도하신 건가요?"
_INTERVENTION_GUIDE = (
    "일부러 그렇게 놓으셨다면 어떤 생각이셨는지 편하게 말씀해 주세요. "
    "실수였다면 원래 자리로 고쳐 주시면 돼요."
)
_ESCALATION_ALTERNATIVE = "아니면 계속 새 설계를 찾아볼까요?"

# Difference의 어떤 필드가 다른지 질문 문장에 쓸 한국어 단어(§5.2).
_FIELD_LABELS = {
    "x": "위치",
    "y": "위치",
    "orientation_deg": "방향",
    "color": "색",
    "brick_type": "크기",
    "layer": "층",
}

# 숫자 표현 토큰(답변 전체 일치 전용, 한글 수사 포함).
_NUMBER_WORD_TOKENS = {
    "1": ("1", "1번", "일번", "일"),
    "2": ("2", "2번", "이번", "이"),
}
# 문장 속 숫자는 "N번"만 본다. 자유 답변에는 "2층"·"(x=3)" 같은 숫자가 섞이므로 맨 숫자는 쓰지 않는다.
_EMBEDDED_NUMBER_RE = re.compile(r"([12])번")

# 전체 일치 단계에서만 쓰는 공손체 어미. 구문 일치 단계에서는 벗기지 않는다.
_ENDINGS = tuple(
    sorted({"요", "이요", "할게", "할게요", "해줘", "으로", "로"}, key=len, reverse=True)
)

# 질문("의도하신 건가요?")에 대한 앞머리 예/아니요. 답변 첫 어절(정규화·어미 제거 후)만 본다.
# "어"는 "어… 모르겠어요" 같은 망설임과 겹쳐 넣지 않는다.
_YES_WORDS = ("네", "넵", "예", "응", "그래", "그래요", "맞아", "맞아요", "맞습니다", "그렇습니다", "그럼요")
_NO_WORDS = ("아니", "아니요", "아니오", "아뇨", "아냐", "아니야", "아니에요", "아닙니다")

# 정규화(공백·구두점 제거) 텍스트의 부분 일치 구문.
_INTERVENTION_PHRASES = {
    REVISE: (
        "일부러", "의도", "고의", "이렇게하고싶", "이렇게하려", "이렇게만들", "그렇게하고싶",
        "이대로", "지금상태", "현재상태", "지금처럼", "살려", "새설계", "새로설계", "다시설계",
        "새로만들", "다시만들", "더화려", "다른느낌", "바꿔",
    ),
    KEEP: (
        "실수", "잘못", "원래대로", "원래자리", "원래위치", "원래설계", "제자리",
        "고칠게", "고쳐", "되돌", "수정할게", "다시놓을", "옮길게",
    ),
}
# 부정이 붙은 의도 표현은 그 자체로 KEEP이다("의도하지 않았어요", "일부러 그런 거 아니에요").
_NEGATED_INTENT_PHRASES = (
    "의도하지않", "의도한거아니", "의도한게아니", "의도아니", "고의아니",
    "일부러그런거아니", "일부러그런게아니", "일부러한거아니", "일부러한게아니", "일부러아니",
)
_ESCALATION_PHRASES = {
    MOVE_BACK: ("옮길게", "옮기", "옮겨", "원래대로", "원래자리", "제자리", "되돌", "고칠게", "고쳐"),
    KEEP_SEARCHING: ("계속", "찾아", "새설계", "다시설계", "다른설계"),
}

# 정규화 텍스트에서 찾는 부정 표지. "못"은 "잘못"과 겹쳐 넣지 않는다.
_NEGATION_MARKERS = ("아니", "않", "안해", "안했", "안할", "안한", "싫", "지마", "말아")

# 명시적 취소 구문(정규화된 텍스트 기준 부분 일치). 부정되면(예: "취소하지 마")
# 취소로 보지 않고 일반 파이프라인으로 넘긴다.
_CANCEL_PHRASES = ("취소", "그만할게", "그만하자", "중단")

# Initial 요청 중 "고르는 걸 맡긴다"는 명시적 표지와, 그 요청이 사실은 선호·다른 사물을 담고 있음을 알리는 단어.
# 특징·사물 단어가 하나라도 있거나 요청이 길면 ANY로 보지 않고 LLM 해석에 맡긴다(선호·지원 밖 사물을 놓치지 않는 쪽).
# 인사("오늘 어떤 걸 만들고 싶으세요?")에 대한 "모르겠어요"·"없어요"는 맡김이 아니라 되물을 대상이라 넣지 않는다.
# "길"·"길게"·"긴"은 "맡길게요"·"맡긴"과 겹치므로 겹치지 않는 형태로만 적는다.
_ANY_MARKERS = (
    "아무거나", "아무거", "아무의자", "아무렇게", "상관없", "알아서", "네가정해", "니가정해", "정해줘", "정해주세요",
    "맡길게", "맡겨", "마음대로", "맘대로", "자유롭게",
)
_PREFERENCE_FEATURE_WORDS = (
    "등받이", "팔걸이", "다리", "좌석", "방석", "높", "낮", "길고", "길쭉", "길이", "기다란", "긴의자", "긴거", "긴걸", "넓", "좁", "크", "작", "두꺼", "얇",
    "빨간", "빨강", "노란", "노랑", "파란", "파랑", "색", "화려", "멋", "예쁜", "예쁘", "귀여", "심플", "단순",
    "튼튼", "벤치", "소파", "스툴", "왕좌", "흔들", "1인", "2인", "두명", "여러명",
    "처럼", "같은", "책상", "테이블", "탁자", "집", "자동차", "로봇", "선반", "침대", "탑",
)
# 앉는 가구가 아닌 흔한 사물. 앉는 가구 단어 없이 이것만 요구하면 LLM 해석 없이 지원 밖으로 본다(Mock의 parse_goal과
# 같은 보장: "자동차 만들어줘"에는 LLM 호출이 없다). "자동차 모양 의자"처럼 앉는 가구 단어가 있으면 LLM에 맡긴다.
_NON_SEATING_OBJECTS = ("책상", "테이블", "탁자", "자동차", "비행기", "로봇", "선반", "컵", "상자", "건물")
_SEATING_WORDS = ("의자", "벤치", "소파", "쇼파", "스툴", "왕좌", "걸상", "앉")
_ANY_MAX_CHARS = 30  # 정규화 후 이보다 긴 요청은 "아무거나"류로 보지 않는다("아무거나의자하나만들어주세요"는 14자)


def _normalize(text):
    """공백·구두점 제거. 한글 음절·숫자는 \\w라서 그대로 남는다."""
    return re.sub(r"[^\w]", "", text)


def _strip_endings(text):
    """전체 일치 비교 전용 어미 제거(최장 일치 1회)."""
    for ending in _ENDINGS:
        if len(text) > len(ending) and text.endswith(ending):
            return text[: -len(ending)]
    return text


def _has_negation(norm):
    return any(marker in norm for marker in _NEGATION_MARKERS)


def _has_cancel_phrase(norm):
    return any(phrase in norm for phrase in _CANCEL_PHRASES)


def _match_number(norm, number_map):
    """숫자 호환: 답변 전체가 숫자 토큰이면 그 값, 아니면 문장 속 "N번"들(부정 확인은 호출자)."""
    stripped = _strip_endings(norm)
    whole = {number_map[digit] for digit, tokens in _NUMBER_WORD_TOKENS.items() if stripped in tokens}
    if whole:
        return whole, True
    return {number_map[m.group(1)] for m in _EMBEDDED_NUMBER_RE.finditer(norm)}, False


def _split_lead(working):
    """첫 어절이 예/아니요면 (REVISE|KEEP, 나머지 텍스트), 아니면 (None, 원문)."""
    first, _, rest = working.partition(" ")
    word = _strip_endings(_normalize(first))
    if word in _YES_WORDS:
        return REVISE, rest
    if word in _NO_WORDS:
        return KEEP, rest
    return None, working


def _phrase_votes(norm, phrase_map):
    """부정이 없을 때만 구문 일치 값을 표로 센다. (표 집합, 부정된 일치가 있었는지)."""
    matched = {value for value, phrases in phrase_map.items() if any(p in norm for p in phrases)}
    if matched and _has_negation(norm):
        return set(), True
    return matched, False


def _finish(text, votes, ambiguous, allowed, llm_fallback):
    if len(votes) == 1 and not ambiguous:
        return next(iter(votes))
    if llm_fallback is not None:
        result = llm_fallback(text)
        return result if result in allowed else UNCLEAR
    return UNCLEAR


def _resolve(text, number_map, phrase_map, llm_fallback, use_lead=False, negated_keep=()):
    """공유 Rule 파이프라인: 말고 → 취소 → 숫자 호환 → 예/아니요 → 부정된 의도 → 구문 → fallback."""
    working = (text or "").strip()
    if "말고" in working:
        # "A 말고 B": A는 취소된 선택이므로 B만 해석한다.
        working = working.rsplit("말고", 1)[-1].strip()
    norm = _normalize(working)
    allowed = set(number_map.values()) | {UNCLEAR, CANCEL}

    if _has_cancel_phrase(norm) and not _has_negation(norm):
        return CANCEL

    numbers, whole = _match_number(norm, number_map)
    if whole:
        return next(iter(numbers))
    if numbers:
        # 문장 속 "N번": 둘 다 나오거나 부정되면("2번은 싫어") 보수적으로 불명확.
        return _finish(text, numbers, _has_negation(norm), allowed, None)

    votes = set()
    if use_lead:
        lead, working = _split_lead(working)
        if lead is not None:
            votes.add(lead)
        norm = _normalize(working)
    for phrase in negated_keep:
        if phrase in norm:
            votes.add(KEEP)
            norm = norm.replace(phrase, "")
    matched, negated = _phrase_votes(norm, phrase_map)
    return _finish(text, votes | matched, negated, allowed, llm_fallback)


def is_meaningful(text):
    """정규화 후 비어 있지 않은 STT 텍스트인가(§4.3 "의미 있는 발화")."""
    if text is None:
        return False
    return _normalize(text) != ""


def parse_response(text, llm_fallback=None):
    """Intervention 자유 답변 → KEEP / REVISE / UNCLEAR / CANCEL.

    REVISE = 일부러 놓았고 지금 상태를 살린 새 설계를 원함, KEEP = 실수라 원래 Design대로 고침.
    llm_fallback(text)는 두 부류가 함께 나오거나 아무것도 못 찾았을 때만 부르며, KEEP/REVISE/UNCLEAR/CANCEL
    밖의 값은 UNCLEAR로 본다.
    """
    return _resolve(text, OPTIONS, _INTERVENTION_PHRASES, llm_fallback,
                    use_lead=True, negated_keep=_NEGATED_INTENT_PHRASES)


def is_number_answer(text):
    """답변 전체가 숫자 호환 토큰("1"·"2번"·"일번"·"2번이요" 등)인가. 이런 답에는 해석할 바람이 없다."""
    return _match_number(_normalize(text or ""), OPTIONS)[1]


def parse_escalation_response(text, llm_fallback=None):
    """§8.11 escalation 자유 답변 → MOVE_BACK / KEEP_SEARCHING / UNCLEAR / CANCEL.

    질문이 두 길을 함께 묻으므로 "네"·"아니요"만으로는 고르지 않는다.
    """
    return _resolve(text, ESCALATION_OPTIONS, _ESCALATION_PHRASES, llm_fallback)


def build_greeting():
    """Initial 첫 질문(인사). main·테스트가 같은 경로로 문장을 받게 함수로 둔다."""
    return GREETING


def is_unsupported_request(text):
    """앉는 가구 단어 없이 흔한 비착석 사물(책상·자동차 등)만 요구하는가. 그 밖의 판단은 LLM 해석에 맡긴다."""
    norm = _normalize(text or "")
    return (any(word in norm for word in _NON_SEATING_OBJECTS)
            and not any(word in norm for word in _SEATING_WORDS))


def parse_initial_request(text):
    """Initial 자유 발화(첫 요청 또는 되묻기 답) → ANY(고르는 걸 맡김) 또는 None(LLM 해석 필요).

    특징·스타일·사물 단어 없는 짧은 "아무거나·알아서·맡길게요" 류만 ANY. 빈 답·긴 답·특징 언급은 None.
    """
    norm = _normalize(text or "")
    if not norm or len(norm) > _ANY_MAX_CHARS:
        return None
    if any(word in norm for word in _PREFERENCE_FEATURE_WORDS):
        return None
    return ANY if any(marker in norm for marker in _ANY_MARKERS) else None


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


def _location_label(brick):
    """블록 ID 없이 위치로 블록을 설명한다: "(x=3, y=5) 2층 블록"(§5.2)."""
    return f"(x={brick['x']}, y={brick['y']}) {brick['layer']}층 블록"


def _has_final_consonant(word):
    """마지막 글자가 받침 있는 한글 음절인가(조사 이/가·와/과 선택용)."""
    code = ord(word[-1]) - 0xAC00
    return 0 <= code < 11172 and code % 28 != 0


def _subject(words):
    """["위치", "색"] → "위치와 색이". 셋 이상은 쉼표로 잇고 마지막 낱말에 맞춰 이/가를 붙인다."""
    if len(words) == 2:
        joined = words[0] + ("과 " if _has_final_consonant(words[0]) else "와 ") + words[1]
    else:
        joined = ", ".join(words)
    return joined + ("이" if _has_final_consonant(words[-1]) else "가")


def _describe_difference(diff):
    """Difference 1개를 질문 문장 속 한 줄(존댓말)로 설명한다(Data Association 없음, §5.2)."""
    expected, actual = diff.get("expected"), diff.get("actual")
    location = _location_label(expected if expected is not None else actual)
    if actual is None:
        return f"{location}이 Design에는 있는데 아직 놓이지 않았어요."
    if expected is None:
        return f"{location}은 Design에 없는 블록이에요."
    items = _differing_fields(expected, actual) or ["배치"]
    return f"{location}의 {_subject(items)} 달라요."


def build_question(design, current, differences):
    """채택 Design/Current/Difference로 주관식 질문 문장을 만든다(§4.2, 번호·선택지 없음)."""
    del design, current  # 문구에만 쓰일 수 있으나 현재 wording에 불필요
    lines = [_INTERVENTION_ASK]
    lines.extend(_describe_difference(diff) for diff in differences)
    lines.append(_INTERVENTION_GUIDE)
    return "\n".join(lines)


REASK_LEAD = (
    "제가 잘 못 알아들었어요. 어떤 부분을 바꾸고 싶으신지 조금만 더 말씀해 주시겠어요? "
    "실수로 놓으신 거라면 그렇게 말씀해 주셔도 돼요."
)


def build_reask(question):
    """불명확 답변 시 자연스럽게 다시 묻고(키워드·번호 안내 없음) 전체 질문을 다시 낸다(§4.2)."""
    return "\n".join([REASK_LEAD, question])


def escalation_question(differences):
    """§8.11: 자동 재설계가 거의 불가능할 때 잘못 놓인 블록을 원래대로 돌려 달라고 제안(번호 없음)."""
    parts = []
    for diff in differences:
        actual, expected = diff.get("actual"), diff.get("expected")
        if actual is None:
            continue
        name = _location_label(actual)
        if expected is not None:
            parts.append(f"{name}은 (x={expected['x']}, y={expected['y']}) {expected['layer']}층 자리로")
        else:
            parts.append(f"{name}은 빼서")
    request = ", ".join(parts) + " " if parts else "놓인 블록을 "
    lines = [
        "지금 놓인 블록으로는 새 설계를 만들기가 어려워요.",
        f"{request}원래대로 돌려 주실 수 있을까요?",
        _ESCALATION_ALTERNATIVE,
    ]
    return "\n".join(lines)
