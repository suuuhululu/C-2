"""C의 모든 음성 I/O.

목적:
    녹음, STT(음성 → 한국어 텍스트), TTS 재생을 담당한다. 의미는 판단하지 않는다.

향후 들어갈 기능:
    - record: 사용자 음성 녹음(최초 목표 음성과 질문 응답 음성 공용),
      짧은 듣기 창 안에 침묵이면 빈 문자열
    - STT: 녹음 결과 → 텍스트, 언어는 한국어
    - speak: 질문·재질문 문장 TTS 재생
    - 재생이 끝난 뒤 녹음을 시작하는 순서로 질문 음성을 답변으로 재인식하지 않음
      (팀 결정 F05·F07)
    - 실제 provider 연결은 개발 9단계(STT+녹음)·10단계(TTS)
    - 테스트에서는 text_answers(텍스트 모드)로 음성 대신 응답을 준다.

현재(WAVE 4): provider 미연결 stub. speak는 아무것도 하지 않고 listen은 None을
돌려준다. main은 None을 "음성 미연결"로 보고 VOICE_IO_FAILED를 반환한다.

하지 않는 것:
    - 응답 의미 해석·질문 문장 생성(dialogue.py 담당)
    - Design 생성·검증
    - import 시 녹음·재생·모델 로딩·API 호출

연결:
    main.py 가 호출한다.
"""


def speak(text):
    """질문 문장 TTS 재생 자리(provider 미연결: 아무것도 하지 않음)."""


def listen():
    """한 번 듣기 결과 텍스트. 침묵이면 "". provider 미연결이면 None."""
    return None
