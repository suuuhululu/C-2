"""LLM API 호출 전용 (OpenAI Chat Completions, 표준 라이브러리 urllib).

목적:
    C 파트에서 외부 LLM과 통신하는 유일한 지점. Chair Design 후보 JSON을 받아 온다.

구현 범위 (WAVE 5):
    - generate_initial_design / generate_revised_design: designer의 generate 자리에 들어가는
      후보 생성 함수. 반환은
        * 파싱된 JSON 객체(dict) — 검증·버전은 designer / validator가 정한다
        * JSON으로 읽을 수 없는 응답 원문(str) — validator가 malformed_output으로 거부
        * provider 실패 {"llm_error": {"kind", "message"}} — designer가 재생성 없이 종료
    - API 재시도는 일시적 실패(network / timeout / 429 / 5xx)만 최대 3회(RETRY_BACKOFF).
      설계 후보 거부와 섞지 않으며 설계 재생성 횟수는 designer가 정한다.
    - 모델은 DEFAULT_MODEL, 환경 변수 OPENAI_MODEL로 바꿀 수 있다. API key는 환경 변수
      OPENAI_API_KEY에서 호출 시점에만 읽고 어디에도 기록하지 않는다.

하지 않는 것:
    - 설계 검증·금지 키 검사(validator 담당), 재생성 정책·버전(designer 담당)
    - 응답 보정(괄호 복구·필드 추정·타입 변환)
    - Robot joint / TCP / 속도 / 힘 / trajectory 값 생성
    - import 시 API 호출·secret loading·네트워크 요청

연결:
    main.py가 C_DESIGN_USE_LLM=1일 때 designer에 이 함수들을 generate로 넘긴다.
"""

import json
import os
import time
import urllib.error
import urllib.request

from app.c_design import designer, validator

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_TOKENS = 2000
TIMEOUT_SECONDS = 30
RETRY_BACKOFF = (1, 2, 4)  # 일시적 provider 실패 재시도 간격(초), 최대 3회

_RULES = f"""Rules (the validator rejects any violation):
- Board {len(validator.BOARD_RANGE)} x {len(validator.BOARD_RANGE)} studs. x and y are integers: the minimum corner of the block footprint; the whole footprint must stay inside 0..{validator.BOARD_RANGE[-1]}.
- brick_type: {", ".join(sorted(validator.BRICK_TYPES))}. color: {", ".join(sorted(validator.COLORS))} (lowercase).
- layer: integer 1..{validator.MAX_LAYER}; layer 1 sits on the board.
- orientation_deg: 2x3x1 uses 0 (X 2 studs, Y 3 studs) or 90 (X 3 studs, Y 2 studs); 2x2x1 always 0.
- blocks: 1..{validator.MAX_BLOCKS}. No two blocks on the same layer may share a stud.
- Every block on layer >= 2 must overlap blocks on the layer directly below by at least {validator.MIN_SUPPORT_STUDS} studs in total.
- All blocks must form one connected structure through stud overlaps between adjacent layers.
- Shape: a chair with legs, a seat and a backrest, left-right balanced.
Output schema: {{"design_version": <int>, "blocks": [{{"brick_type": ..., "color": ..., "x": ..., "y": ..., "layer": ..., "orientation_deg": ...}}]}}. Each block has exactly these six keys."""

# 검증을 통과하는 예시: designer의 Mock 의자를 Board 중앙에 놓은 실제 좌표(복사본이 아니라 같은 출처).
_EXAMPLE_DESIGN = {
    "design_version": 1,
    "blocks": designer.center_blocks(designer.mock_initial_candidate("CHAIR")["blocks"]),
}

_SELF_CHECK = (
    "Before output, for every block on layer >= 2 count the studs it shares with blocks on the layer "
    f"directly below and confirm the total is at least {validator.MIN_SUPPORT_STUDS}; then confirm all blocks "
    "form one connected structure through stud overlaps between adjacent layers. Output the final JSON only "
    "after both checks pass."
)

SYSTEM_PROMPT = (
    "You generate a LEGO CHAIR Design as JSON only. Output one JSON object and no explanation. "
    "Never output robot commands, ROS2 code, world or robot coordinates, a Plan, Replan, NextPart, "
    "supply slot, or backend state.\n" + _RULES + "\n"
    "Example of a valid design (it passes every rule above): " + json.dumps(_EXAMPLE_DESIGN) + "\n" + _SELF_CHECK
)


def _error(kind, message):
    return {"llm_error": {"kind": kind, "message": message}}


def _reasons_text(reasons):
    if not reasons:
        return "None."
    return json.dumps(reasons, ensure_ascii=False)


def _initial_user_message(object_type, reasons):
    return (
        f"Target object: {object_type}.\n"
        f"Previous candidate was rejected for: {_reasons_text(reasons)}\n"
        "Return a complete new design."
    )


def _revised_user_message(design, current, differences, reasons):
    return (
        "The user chose REVISE: keep the blocks already on the board and redesign the rest of the CHAIR.\n"
        f"Current adopted design: {json.dumps(design, ensure_ascii=False)}\n"
        "Latest Current (actually placed blocks). Every Current block must appear in the final Revised Design "
        "with brick_type, color, x, y, layer and orientation_deg unchanged: no moving, deleting, altering or "
        "omitting. Copy the Current blocks into the output first, then design the rest: "
        f"{json.dumps(current, ensure_ascii=False)}\n"
        f"Differences (expected vs actual): {json.dumps(differences, ensure_ascii=False)}\n"
        f"Previous candidate was rejected for: {_reasons_text(reasons)}\n"
        "Redesign the whole remaining structure around the Current. Do not simply shift every block by the "
        "same offset and do not re-center the chair. Return the complete design (all blocks)."
    )


def _parse_content(text):
    """순수 JSON, ```json fence, 앞뒤 공백만 처리한다. 읽지 못하면 원문을 그대로 돌려준다."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(body)
    except ValueError:
        return text
    return parsed if isinstance(parsed, dict) else text


def _post_json(payload, api_key):
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read())


def _content_of(body):
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else None


def _call(user_message, should_stop):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _error("missing_key", "OPENAI_API_KEY is not set")
    payload = {
        "model": os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }

    last_error = None
    for wait in (0,) + RETRY_BACKOFF:
        if last_error is not None:
            if should_stop is not None and should_stop():
                return _error("stopped", "stopped before the next API retry")
            if wait > 0:
                time.sleep(wait)
        try:
            body = _post_json(payload, api_key)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return _error("auth", f"HTTP {exc.code}")
            if exc.code == 429:
                last_error = _error("rate_limit", "HTTP 429")
            elif exc.code >= 500:
                last_error = _error("server", f"HTTP {exc.code}")
            else:
                return _error("bad_response", f"HTTP {exc.code}")
            continue
        except TimeoutError:
            last_error = _error("timeout", f"no response within {TIMEOUT_SECONDS} s")
            continue
        except OSError as exc:  # URLError·연결 끊김(ConnectionResetError 등)
            kind = "timeout" if isinstance(getattr(exc, "reason", None), TimeoutError) else "network"
            last_error = _error(kind, "request did not reach the API")
            continue
        except ValueError:
            return _error("bad_response", "response body is not JSON")

        content = _content_of(body)
        if content is None:
            return _error("bad_response", "response has no message content")
        return _parse_content(content)
    return last_error


def generate_initial_design(object_type, reasons=None, should_stop=None):
    """Initial Design 후보. 사용자 발화 원문은 보내지 않고 해석된 object_type만 보낸다."""
    return _call(_initial_user_message(object_type, reasons), should_stop)


def generate_revised_design(design, current, differences, reasons=None, should_stop=None):
    """Revised Design 후보. Current 보존·전체 재설계를 지시한다(검증은 validator)."""
    return _call(_revised_user_message(design, current, differences, reasons), should_stop)
