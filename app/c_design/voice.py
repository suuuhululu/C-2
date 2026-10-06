"""C의 모든 음성 I/O.

구현 (WAVE 6):
    - record: InputStream으로 블록 단위 녹음. 블록마다 RMS(에너지)를 재서 무음 구간을
      걸러낸다(energy gate) — 임계값 미달이 WAIT_SECONDS만큼 이어지면 발화 없음으로
      보고 b""를 돌려주고, 발화가 시작되면 TRAILING_SILENCE_SECONDS 무음이나
      MAX_UTTERANCE_SECONDS 길이에서 멈춘다. 시간은 블록 수로 세어 테스트가
      wall clock에 의존하지 않는다.
    - transcribe: record의 PCM을 WAV(메모리, 임시파일 없음)로 감싸 OpenAI Whisper
      STT에 보낸다(key: OPENAI_API_KEY). 요청·재시도·실패 분류는 llm.py의 _call과 같은 정책(_request).
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
import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import wave

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
RMS_THRESHOLD = 500  # int16 scale, tune on the real mic
WAIT_SECONDS = 8.0  # 이 창 안에 RMS_THRESHOLD를 넘지 못하면 침묵으로 본다
TRAILING_SILENCE_SECONDS = 1.0
MAX_UTTERANCE_SECONDS = 10.0
POST_SPEAK_DELAY = 0.5  # 0.2-1.0: 재생이 끝난 뒤 방·스피커 잔향이 가라앉을 시간을
# 줘서 마이크를 그 다음에 여는 순서 자체로 echo를 막는다(echo cancellation 아님)

_last_error = None


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


def _capture(stream, blocksize, np):
    """energy gate 루프. 시간은 읽은 블록 수로 센다(결정적, wall clock 아님)."""
    wait_blocks = int(round(WAIT_SECONDS / BLOCK_SECONDS))
    first = None
    for _ in range(wait_blocks):
        data, _overflowed = stream.read(blocksize)
        if _rms(data, np) >= RMS_THRESHOLD:
            first = data
            break
    if first is None:
        return b""  # WAIT_SECONDS 동안 침묵

    max_blocks = int(round(MAX_UTTERANCE_SECONDS / BLOCK_SECONDS))
    trailing_blocks = int(round(TRAILING_SILENCE_SECONDS / BLOCK_SECONDS))
    frames = [first]
    silence_run = 0
    while len(frames) < max_blocks:
        data, _overflowed = stream.read(blocksize)
        frames.append(data)
        if _rms(data, np) >= RMS_THRESHOLD:
            silence_run = 0
        else:
            silence_run += 1
            if silence_run >= trailing_blocks:
                break
    return _to_pcm_bytes(frames, np)


def record():
    """녹음 결과 PCM(int16 LE bytes). 침묵이면 b"". 장치 실패면 None."""
    _clear_error()
    try:
        sd = _sounddevice()
        np = _numpy()
        blocksize = int(SAMPLE_RATE * BLOCK_SECONDS)
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=blocksize) as stream:
            return _capture(stream, blocksize, np)
    except Exception as exc:  # noqa: BLE001 - 이 I/O 경계에서만 폭넓게 잡는다
        _set_error("audio_device", type(exc).__name__)
        return None


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
    for name, value in (("model", model), ("language", LANGUAGE), ("response_format", "json")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(wav_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts)


def transcribe(pcm):
    """PCM(int16 bytes) → 한국어 텍스트. 실패면 None."""
    _clear_error()
    model = os.environ.get("OPENAI_STT_MODEL") or DEFAULT_STT_MODEL
    boundary = uuid.uuid4().hex
    body = _multipart_body(boundary, model, _wav_bytes(pcm))
    response = _request(STT_URL, body, f"multipart/form-data; boundary={boundary}", STT_KEY_ENV)
    if response is None:
        return None
    try:
        text = json.loads(response)["text"]
    except (ValueError, KeyError, TypeError):
        _set_error("bad_response", "STT response missing text")
        return None
    return text


def listen():
    """한 번 듣기 결과 텍스트. 침묵이면 "". 장치·provider 실패면 None."""
    _clear_error()
    pcm = record()
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
