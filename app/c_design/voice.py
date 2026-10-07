"""C의 모든 음성 I/O.

구현 (WAVE 6):
    - record: InputStream으로 블록 단위 녹음. 블록마다 RMS(에너지)를 재는 energy gate.
      * 스트림을 연 직후 WARMUP_SECONDS는 버린다(open 직후 레벨 램프·직전 재생 잔향).
      * 적응형 임계값: 그다음 NOISE_CALIBRATION_SECONDS 동안 블록 RMS의 중앙값(noise floor)을 재고
        threshold = max(RMS_THRESHOLD_MIN, noise_floor × NOISE_MULTIPLIER). 방 소음이 커도
        소음을 발화로 오인하지 않고, 조용한 방에서도 하한 아래 잡음은 걸러낸다.
      * threshold 이상 블록이 WAIT_SECONDS 안에 없으면 발화 없음 b"".
      * 발화가 시작되면 직전 PRE_ROLL_SECONDS 블록을 앞에 붙이고(첫 음절 보존),
        TRAILING_SILENCE_SECONDS 무음이나 MAX_UTTERANCE_SECONDS(발화 시작부터) 길이에서 멈춘다.
      * 발화 블록 합이 MIN_SPEECH_SECONDS 미만이면 b""(짧은 잡음).
      * 앞뒤 무음은 TRIM_MARGIN_SECONDS만 남기고 잘라 낸다. 잘라 낸 뒤 길이가 MIN_SPEECH_SECONDS
        미만이거나 전체 RMS가 threshold의 절반 미만이면 b""(whisper 환각 억제).
      시간은 블록 수로 세어 테스트가 wall clock에 의존하지 않는다.
      on_ready(선택): warm-up·보정이 끝나 발화 대기에 들어가는 시점(첫 대기 블록을 읽기 전)에 1회 부른다.
      "지금 말씀하세요" 안내를 이때 띄우면 사용자 발화가 보정 구간(noise floor)에 섞이지 않는다.
      콜백 예외는 그대로 호출자에게 전파한다(장치 실패로 바꾸지 않음).
    - transcribe: record의 PCM을 WAV(메모리, 임시파일 없음)로 감싸 OpenAI Whisper
      STT에 보낸다(key: OPENAI_API_KEY). language=ko와 도메인 어휘 힌트 STT_PROMPT를 함께 보낸다.
      MIN_CLIP_SECONDS보다 짧은 클립은 앞 PAD_FRONT_SECONDS·뒤 나머지를 무음으로 채워 보낸다(1초 미만 클립은
      whisper 환각이 잦다). 응답은 verbose_json으로 받아, 모든 segment의 no_speech_prob가 NO_SPEECH_REJECT
      이상이거나 segments가 빈 채 text도 비면 ""(last_error stt_no_speech)로 본다. segments 키 자체가 없는
      응답(json 형식·D 통합 테스트 fake)은 text를 그대로 믿는다.
      whisper가 힌트를 그대로 되풀이한 결과(힌트 전체, 또는 힌트 항목 3개 이상 포함)는 발화가 아니므로
      ""로 바꾸고 last_error에 stt_prompt_echo를 남긴다.
      요청·재시도·실패 분류는 llm.py의 _call과 같은 정책(_request).
      환경 변수 C_VOICE_DEBUG_DIR이 있을 때만 보낸 WAV와 게이트 통계를 그 폴더에
      latest_input.wav / latest_input.json으로 덮어써 남긴다(기본 off, key 미기록). json의 stt_called·reason은
      STT 전송 여부와 ""로 끝난 이유(no_speech_detected / too_short / weak_input / no_speech_prob / prompt_echo)를
      남긴다. STT를 부르지 않은 경우에는 json만 쓰고, 이전 전송의 WAV는 지워 짝이 어긋나지 않게 한다.
    - listen: record → transcribe. record가 None이면 None(장치 실패), b""이면 ""을
      그대로 반환하고 STT를 부르지 않는다(무음에 STT를 보내면 whisper가 환각 텍스트를
      만들 수 있다). transcribe가 None이면 None. 그 외엔 strip한 텍스트("" 가능).
    - speak: OpenAI TTS에 문장을 보내 WAV를 받고 재생한 뒤 POST_SPEAK_DELAY만큼
      쉰다(key: OPENAI_TTS_API_KEY, 없으면 OPENAI_API_KEY로 대체하지 않고 missing_key). 재생이 끝난 뒤에만 다음 listen을 시작하는 순서(main이 보장)와 이 지연이
      합쳐져, 스피커 잔향이 마이크에 들어가 질문을 답변으로 재인식하는 echo를
      막는다(sequencing으로 막는 것이므로 하드웨어 echo cancellation은 아니다).
      실패해도 예외를 던지지 않고 last_error만 남긴다.
    - last_error: 가장 최근 공개 호출의 실패 원인("kind: 설명"). API key는 절대
      포함하지 않는다. 각 공개 호출 시작 시 초기화된다.
    - import 시 recording·재생·모델 로딩·네트워크 요청 없음. sounddevice·numpy는
      호출 시점에만 지연 import하므로(_sounddevice·_numpy) 설치되어 있지 않아도
      이 모듈을 import할 수 있다.
    - 실제 TTS 재생은 프로젝트의 OpenAI project가 해당 모델에 접근 권한이 있어야
      동작한다(TTS model availability depends on the OpenAI project). 이 모듈은
      권한 여부와 무관하게 같은 재시도·실패 분류를 적용한다.

하지 않는 것:
    - 응답 의미 해석·질문 문장 생성(dialogue.py 담당)
    - Design 생성·검증
    - import 시 녹음·재생·모델 로딩·API 호출

연결:
    main.py 가 호출한다.
"""

import http.client
import array
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections import deque

STT_URL = "https://api.openai.com/v1/audio/transcriptions"
TTS_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_STT_MODEL = "whisper-1"  # env OPENAI_STT_MODEL이 호출 시점에 덮어쓴다
DEFAULT_TTS_MODEL = "tts-1"  # env OPENAI_TTS_MODEL
DEFAULT_TTS_VOICE = "alloy"  # env OPENAI_TTS_VOICE
# STT와 TTS는 서로 다른 key 변수를 쓴다(사용자 지시). TTS key가 없을 때 STT key로 대체하지 않는다.
STT_KEY_ENV = "OPENAI_API_KEY"
TTS_KEY_ENV = "OPENAI_TTS_API_KEY"
LANGUAGE = "ko"
SAMPLE_RATE = 16000
TIMEOUT_SECONDS = 30
RETRY_BACKOFF = (1, 2, 4)  # llm.py와 같은 정책: 일시적 provider 실패만 최대 3회
BLOCK_SECONDS = 0.1
# 적응형 energy gate(int16 RMS). 2026-10-06 실측: 방 소음 RMS가 오후 600~1000, 저녁 0~276으로 바뀌어
# 고정 임계값 500은 소음을 발화로 오인(→ whisper 환각)하거나 조용할 때만 동작했다. 보통 말소리는 2000~8000.
RMS_THRESHOLD_MIN = 600  # threshold 하한: 이 방의 소음 돌출 RMS 400~900 대응(루프백 발화 1500~2500, 사람 발화는 더 큼)
NOISE_MULTIPLIER = 3.0  # threshold = max(RMS_THRESHOLD_MIN, noise_floor × NOISE_MULTIPLIER)
WARMUP_SECONDS = 0.2  # 스트림을 연 직후 버리는 구간(레벨 램프·직전 TTS 잔향이 noise floor를 올리지 않게)
NOISE_CALIBRATION_SECONDS = 0.5  # warm-up 다음 noise floor(중앙값)를 재는 구간
WAIT_SECONDS = 8.0  # 보정 뒤 이 창 안에 threshold를 넘지 못하면 침묵으로 본다
TRAILING_SILENCE_SECONDS = 1.0
MAX_UTTERANCE_SECONDS = 10.0  # 발화 시작부터 센다
PRE_ROLL_SECONDS = 0.3  # 발화 시작 직전 블록을 앞에 붙여 첫 음절을 살린다
MIN_SPEECH_SECONDS = 0.2  # 발화로 판정된 블록 합이 이보다 짧으면 STT를 부르지 않는다("1번"·"2번"은 약 0.2~0.45초)
TRIM_MARGIN_SECONDS = 0.2  # 앞뒤 무음 트리밍 후 남기는 여유
# whisper prompt 힌트(도메인 어휘). 무관한 소음 입력에서 자막형 환각을 줄이는 데도 도움이 된다.
# whisper가 짧은 입력에서 힌트를 그대로 되풀이할 수 있으므로(2026-10-06 루프백 실측), 되풀이돼도 응답 의미가
# 바뀌지 않게 취소·원복·재설계 어휘는 넣지 않는다. 숫자 항목("1번, 2번")은 짧은 "2번" 클립에 "3번, 4번, …"
# 나열을 지어내게 해서 뺐다(같은 클립이 명사만 힌트로는 "2번"으로 정확히 인식됨). 되풀이는 _is_prompt_echo가 걸러 낸다.
STT_PROMPT = "의자, 벤치, 소파, 스툴, 만들어줘, 만들고 싶어"
PROMPT_ECHO_MIN_ITEMS = 3  # 결과에 힌트 항목이 이만큼 이상 들어 있으면 힌트 되풀이로 본다
MIN_CLIP_SECONDS = 2.0  # 이보다 짧은 클립은 무음 패딩해 이 길이로 보낸다
PAD_FRONT_SECONDS = 0.3  # 패딩 중 앞쪽 무음(나머지는 뒤쪽)
CALIBRATION_RETRY_DELAY_SECONDS = 0.3  # 보정 구간에 발화·순간 잡음이 섞였을 때 한 번만 다시 보정하기 전 버리는 길이
CALIBRATION_RETRIES_MAX = 1  # 재보정은 녹음 한 번당 최대 1회(무한 재보정 금지)
WEAK_INPUT_PEAK = 4000  # 보낸 WAV의 peak가 이보다 작으면 "입력이 약함" 표시(STT 결과는 바꾸지 않음)
NO_SPEECH_REJECT = 0.8  # 모든 segment의 no_speech_prob가 이 이상이면 발화 없음(짧은 정상 "2번"도 0.55라 보수적으로 둔다)
DEBUG_DIR_ENV = "C_VOICE_DEBUG_DIR"  # 설정 시에만 STT 입력 WAV·통계를 남긴다(기본 off)
POST_SPEAK_DELAY = 0.5  # 0.2-1.0: 재생이 끝난 뒤 방·스피커 잔향이 가라앉을 시간을
# 줘서 마이크를 그 다음에 여는 순서 자체로 echo를 막는다(echo cancellation 아님)

_last_error = None
_last_capture = None  # 가장 최근 record()의 게이트 통계(디버그 덤프용, 오디오는 담지 않음)


def _sounddevice():
    import sounddevice as sd
    return sd


def _numpy():
    import numpy as np
    return np


def _clear_error():
    global _last_error
    _last_error = None


def _set_error(kind, detail):
    global _last_error
    _last_error = f"{kind}: {detail}"


def last_error():
    """가장 최근 공개 호출의 실패 원인(kind + 짧은 설명). API key는 절대 포함하지 않는다."""
    return _last_error


def _post(url, data, content_type, api_key):
    request = urllib.request.Request(
        url, data=data, headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def _request(url, data, content_type, key_env):
    """llm.py의 _call과 같은 재시도·실패 분류 정책. key는 key_env 변수에서만 읽는다. 응답 바이트 또는 None."""
    api_key = os.environ.get(key_env)
    if not api_key:
        _set_error("missing_key", f"{key_env} is not set")  # 변수 이름만, 값은 담지 않는다
        return None

    retrying = False
    for wait in (0,) + RETRY_BACKOFF:
        if retrying and wait > 0:
            time.sleep(wait)
        try:
            return _post(url, data, content_type, api_key)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                _set_error("auth", f"HTTP {exc.code}")
                return None
            if exc.code == 429:
                _set_error("rate_limit", f"HTTP {exc.code}")
            elif exc.code >= 500:
                _set_error("server", f"HTTP {exc.code}")
            else:
                _set_error("bad_response", f"HTTP {exc.code}")
                return None
        except TimeoutError:
            _set_error("timeout", f"no response within {TIMEOUT_SECONDS} s")
        except (OSError, http.client.HTTPException):  # URLError·연결 끊김·응답 중간 끊김(IncompleteRead) 등
            _set_error("network", "request did not reach the API")
        retrying = True
    return None


def _rms(block, np):
    samples = np.asarray(block, dtype=np.float64)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def _to_pcm_bytes(frames, np):
    audio = np.concatenate([np.asarray(frame) for frame in frames], axis=0)
    return audio.astype("<i2").tobytes()  # little-endian int16 고정


def _calibration_unstable(calibration, np):
    """보정 블록 중 하나라도 발화 수준(RMS_THRESHOLD_MIN 이상이고 중앙값의 NOISE_MULTIPLIER배 이상)이면 True."""
    if not calibration:
        return False
    median = float(np.median(calibration))
    return float(max(calibration)) >= max(RMS_THRESHOLD_MIN, median * NOISE_MULTIPLIER)


def _blocks(seconds):
    return int(round(seconds / BLOCK_SECONDS))


class _ReadyCallbackError(Exception):
    """on_ready 콜백이 던진 예외를 record()의 장치 실패 처리와 구분해 그대로 다시 던지기 위한 포장."""


def _capture(stream, blocksize, np, on_ready=None):
    """적응형 energy gate. (PCM bytes 또는 b"", 게이트 통계)를 돌려준다. 시간은 읽은 블록 수로 센다.

    통계의 reason은 b""인 이유(no_speech_detected / too_short / weak_input), capture_seconds는 보정 뒤 읽은 길이.
    """
    started = time.monotonic()
    timeline = {}
    for _ in range(_blocks(WARMUP_SECONDS)):
        stream.read(blocksize)  # warm-up: 버린다
    timeline["warmup_done"] = round(time.monotonic() - started, 3)

    def calibrate():
        return [_rms(stream.read(blocksize)[0], np) for _ in range(_blocks(NOISE_CALIBRATION_SECONDS))]

    calibration = calibrate()
    retries = 0
    # 보정 블록 하나가 발화 수준(최소 게이트 이상이면서 중앙값의 NOISE_MULTIPLIER배 이상)이면 발화·순간 잡음이 섞인 것이다.
    # 그대로 두면 threshold가 발화 크기의 배수로 올라가 뒤따르는 발화를 놓친다(2026-10-07 실측: floor 351 → threshold 1054,
    # voiced 0.1 s). CALIBRATION_RETRY_DELAY_SECONDS를 버리고 최대 CALIBRATION_RETRIES_MAX회만 다시 보정한다.
    unstable = _calibration_unstable(calibration, np)
    first_calibration = list(calibration)
    while unstable and retries < CALIBRATION_RETRIES_MAX:
        for _ in range(_blocks(CALIBRATION_RETRY_DELAY_SECONDS)):
            stream.read(blocksize)
        calibration = calibrate()
        retries += 1
        unstable = _calibration_unstable(calibration, np)
    noise_floor = float(np.median(calibration)) if calibration else 0.0
    threshold = max(RMS_THRESHOLD_MIN, noise_floor * NOISE_MULTIPLIER)
    timeline["calibration_done"] = round(time.monotonic() - started, 3)
    stats = {"noise_floor": round(noise_floor, 1), "threshold": round(threshold, 1),
             "voiced_seconds": 0.0, "trimmed_seconds": 0.0, "reason": None, "capture_seconds": 0.0,
             "calibration_min": round(float(min(calibration)), 1) if calibration else 0.0,
             "calibration_median": round(noise_floor, 1),
             "calibration_max": round(float(max(calibration)), 1) if calibration else 0.0,
             "calibration_unstable": bool(_calibration_unstable(first_calibration, np)),  # 첫 보정이 오염됐었는지
             "calibration_retries": retries, "calibration_still_unstable": bool(unstable), "timeline": timeline}
    if on_ready is not None:
        try:
            on_ready()
        except Exception as exc:  # noqa: BLE001 - 호출자 콜백 예외는 record()에서 그대로 다시 던진다
            raise _ReadyCallbackError() from exc
    timeline["on_ready"] = round(time.monotonic() - started, 3)

    pre_roll = deque(maxlen=_blocks(PRE_ROLL_SECONDS))
    first = None
    waited = 0
    for _ in range(_blocks(WAIT_SECONDS)):
        data, _overflowed = stream.read(blocksize)
        waited += 1
        if _rms(data, np) >= threshold:
            first = data
            break
        pre_roll.append(data)
    if first is None:
        stats.update(reason="no_speech_detected", capture_seconds=round(waited * BLOCK_SECONDS, 2))
        return b"", stats  # WAIT_SECONDS 동안 침묵

    frames = list(pre_roll) + [first]
    voiced = [False] * len(pre_roll) + [True]
    speech_blocks, silence_run = 1, 0
    while speech_blocks < _blocks(MAX_UTTERANCE_SECONDS):
        data, _overflowed = stream.read(blocksize)
        loud = _rms(data, np) >= threshold
        frames.append(data)
        voiced.append(loud)
        speech_blocks += 1
        if loud:
            silence_run = 0
        else:
            silence_run += 1
            if silence_run >= _blocks(TRAILING_SILENCE_SECONDS):
                break

    stats["voiced_seconds"] = round(sum(voiced) * BLOCK_SECONDS, 2)
    stats["capture_seconds"] = round((waited - 1 + speech_blocks) * BLOCK_SECONDS, 2)
    if sum(voiced) < _blocks(MIN_SPEECH_SECONDS):
        stats["reason"] = "too_short"
        return b"", stats  # 짧은 잡음: STT를 부르지 않는다

    margin = _blocks(TRIM_MARGIN_SECONDS)
    first_voiced = voiced.index(True)
    last_voiced = len(voiced) - 1 - voiced[::-1].index(True)
    kept = frames[max(0, first_voiced - margin):last_voiced + 1 + margin]
    stats["trimmed_seconds"] = round((len(frames) - len(kept)) * BLOCK_SECONDS, 2)
    audio = np.concatenate([np.asarray(frame) for frame in kept], axis=0)
    if len(kept) < _blocks(MIN_SPEECH_SECONDS) or _rms(audio, np) < threshold / 2:
        stats["reason"] = "weak_input"
        return b"", stats  # 환각 억제: 짧거나 전체가 약한 입력은 보내지 않는다
    return _to_pcm_bytes(kept, np), stats


def record(on_ready=None):
    """녹음 결과 PCM(int16 LE bytes). 침묵·짧은 잡음이면 b"". 장치 실패면 None. on_ready는 listen()과 같다."""
    global _last_capture
    _clear_error()
    _last_capture = None
    try:
        sd = _sounddevice()
        np = _numpy()
        blocksize = int(SAMPLE_RATE * BLOCK_SECONDS)
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=blocksize) as stream:
            opened_at = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
            pcm, _last_capture = _capture(stream, blocksize, np, on_ready)
            _last_capture["stream_opened_at"] = opened_at
        _last_capture["stream_closed_at"] = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
    except _ReadyCallbackError as exc:
        raise exc.__cause__
    except Exception as exc:  # noqa: BLE001 - 이 I/O 경계에서만 폭넓게 잡는다
        _set_error("audio_device", type(exc).__name__)
        return None
    debug_dir = os.environ.get(DEBUG_DIR_ENV)
    if pcm == b"" and debug_dir:
        _dump_no_stt(debug_dir, _last_capture)
    return pcm


def _wav_bytes(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


def _multipart_body(boundary, model, wav_bytes):
    parts = []
    for name, value in (("model", model), ("language", LANGUAGE), ("prompt", STT_PROMPT), ("response_format", "verbose_json")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(wav_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts)


def _write_debug_json(debug_dir, info):
    try:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "latest_input.json"), "w", encoding="utf-8") as handle:
            json.dump(info, handle, indent=2)
    except OSError:
        pass


def _dump_no_stt(debug_dir, capture):
    """STT를 부르지 않고 끝난 녹음: json만 남기고 이전 전송의 WAV는 지운다(짝이 어긋나지 않게)."""
    _write_debug_json(debug_dir, {
        "stt_called": False, "reason": capture.get("reason"),
        "noise_floor": capture.get("noise_floor"), "threshold": capture.get("threshold"),
        "voiced_seconds": capture.get("voiced_seconds"), "duration": capture.get("capture_seconds"),
        "calibration_unstable": capture.get("calibration_unstable"), "calibration_retries": capture.get("calibration_retries"),
    })
    try:
        os.remove(os.path.join(debug_dir, "latest_input.wav"))
    except OSError:
        pass


def _update_debug_json(debug_dir, **fields):
    """이미 쓴 latest_input.json에 필드를 덧붙인다(없으면 무시)."""
    path = os.path.join(debug_dir, "latest_input.json")
    try:
        with open(path, encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, ValueError):
        return
    info.update(fields)
    _write_debug_json(debug_dir, info)


def _mark_debug_reason(debug_dir, reason):
    """STT 응답이 발화 없음으로 판정되면 이미 쓴 json의 reason만 바꾼다."""
    _update_debug_json(debug_dir, reason=reason)


def _dump_debug(debug_dir, wav, pcm):
    """C_VOICE_DEBUG_DIR이 있을 때만: STT에 보내는 WAV와 통계를 덮어써 남긴다. 실패해도 STT는 진행한다."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if sys.byteorder == "big":
        samples.byteswap()  # PCM은 little-endian int16
    count = len(samples)
    capture = _last_capture or {}
    info = {
        "sample_rate": SAMPLE_RATE, "channels": 1, "duration": round(count / SAMPLE_RATE, 3),
        "rms": round((sum(v * v for v in samples) / count) ** 0.5, 1) if count else 0.0,
        "peak": max((abs(v) for v in samples), default=0),
        "weak_input": (max((abs(v) for v in samples), default=0) < WEAK_INPUT_PEAK),
        "noise_floor": capture.get("noise_floor"), "threshold": capture.get("threshold"),
        "voiced_seconds": capture.get("voiced_seconds"), "trimmed_seconds": capture.get("trimmed_seconds"),
        "calibration_unstable": capture.get("calibration_unstable"), "calibration_retries": capture.get("calibration_retries"),
        "stt_called": True, "reason": None,
    }
    try:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "latest_input.wav"), "wb") as handle:
            handle.write(wav)
        with open(os.path.join(debug_dir, "latest_input.json"), "w", encoding="utf-8") as handle:
            json.dump(info, handle, indent=2)
    except OSError:
        pass


def _normalize(text):
    return re.sub(r"[\W_]+", "", text)


def _is_prompt_echo(text):
    """whisper가 STT_PROMPT를 그대로(또는 대부분) 되풀이한 결과인지. 정상 발화는 힌트 항목 1~2개 정도만 담는다."""
    normalized = _normalize(text)
    if not normalized:
        return False
    items = [_normalize(item) for item in STT_PROMPT.split(",")]
    return normalized == _normalize(STT_PROMPT) or sum(item in normalized for item in items) >= PROMPT_ECHO_MIN_ITEMS


def _pad_short_clip(pcm):
    """MIN_CLIP_SECONDS보다 짧으면 앞 PAD_FRONT_SECONDS(최대)·뒤 나머지를 무음으로 채운다."""
    deficit = int(round(MIN_CLIP_SECONDS * SAMPLE_RATE)) - len(pcm) // 2
    if deficit <= 0:
        return pcm
    front = min(int(round(PAD_FRONT_SECONDS * SAMPLE_RATE)), deficit)
    return b"\x00\x00" * front + pcm + b"\x00\x00" * (deficit - front)


def _all_no_speech(segments, text):
    """verbose_json segment 기준 무음 판정. segments 키가 없는 응답(json 형식·D 테스트 fake)은 판정하지 않고
    text를 그대로 믿는다. 빈 segments는 text도 비었을 때만 무음이다."""
    if segments is None:
        return False
    if not isinstance(segments, list) or not segments:
        return not text.strip()
    return all(isinstance(seg, dict) and seg.get("no_speech_prob", 0) >= NO_SPEECH_REJECT for seg in segments)


def transcribe(pcm):
    """PCM(int16 bytes) → 한국어 텍스트. 발화 없음으로 판정되면 "". 실패면 None."""
    _clear_error()
    model = os.environ.get("OPENAI_STT_MODEL") or DEFAULT_STT_MODEL
    boundary = uuid.uuid4().hex
    pcm = _pad_short_clip(pcm)
    wav = _wav_bytes(pcm)
    debug_dir = os.environ.get(DEBUG_DIR_ENV)
    if debug_dir:
        _dump_debug(debug_dir, wav, pcm)
    body = _multipart_body(boundary, model, wav)
    response = _request(STT_URL, body, f"multipart/form-data; boundary={boundary}", STT_KEY_ENV)
    if response is None:
        return None
    try:
        data = json.loads(response)
        text = data["text"]
    except (ValueError, KeyError, TypeError):
        _set_error("bad_response", "STT response missing text")
        return None
    if debug_dir:
        segments = data.get("segments")
        _update_debug_json(debug_dir, whisper_text=text,
                           no_speech_probs=[seg.get("no_speech_prob") for seg in segments if isinstance(seg, dict)] if isinstance(segments, list) else None)
    if _all_no_speech(data.get("segments"), text if isinstance(text, str) else ""):
        _set_error("stt_no_speech", f"no segment below no_speech_prob {NO_SPEECH_REJECT}; treated as no speech")
        if debug_dir:
            _mark_debug_reason(debug_dir, "no_speech_prob")
        return ""
    if isinstance(text, str) and _is_prompt_echo(text):
        _set_error("stt_prompt_echo", "transcript repeats the STT prompt; treated as no speech")
        if debug_dir:
            _mark_debug_reason(debug_dir, "prompt_echo")
        return ""
    return text


def listen(on_ready=None):
    """한 번 듣기 결과 텍스트. 침묵이면 "". 장치·provider 실패면 None.

    on_ready(선택): 보정이 끝나 발화를 기다리기 시작할 때 1회 호출된다(안내 출력용). 기본 None.
    """
    _clear_error()
    # D/HMI와 기존 테스트는 record()를 인자 없이 호출·대체한다. on_ready가 있을 때만 넘겨 호환을 유지한다.
    pcm = record(on_ready) if on_ready is not None else record()
    if pcm is None:
        return None
    if pcm == b"":
        return ""  # 침묵에 STT를 보내면 whisper가 텍스트를 환각할 수 있다
    text = transcribe(pcm)
    if text is None:
        return None
    return text.strip()


def _decode_wav(data, np):
    with wave.open(io.BytesIO(data), "rb") as wav_file:
        channels = wav_file.getnchannels()
        samplerate = wav_file.getframerate()
        raw = wav_file.readframes(wav_file.getnframes())
    audio = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        audio = audio.reshape(-1, channels)
    return audio, samplerate


def speak(text):
    """질문 문장을 OpenAI TTS로 재생한 뒤 POST_SPEAK_DELAY만큼 쉰다. 절대 예외를 던지지 않는다."""
    _clear_error()
    model = os.environ.get("OPENAI_TTS_MODEL") or DEFAULT_TTS_MODEL
    voice_name = os.environ.get("OPENAI_TTS_VOICE") or DEFAULT_TTS_VOICE
    payload = json.dumps(
        {"model": model, "input": text, "voice": voice_name, "response_format": "wav"}
    ).encode("utf-8")
    response = _request(TTS_URL, payload, "application/json", TTS_KEY_ENV)
    if response is None:
        return
    try:
        sd = _sounddevice()
        np = _numpy()
        frames, samplerate = _decode_wav(response, np)
        sd.play(frames, samplerate)
        sd.wait()
    except Exception as exc:  # noqa: BLE001 - 디코딩·재생 실패를 한 곳에서 잡는다
        _set_error("audio_device", type(exc).__name__)
        return
    time.sleep(POST_SPEAK_DELAY)
