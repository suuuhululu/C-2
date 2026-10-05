"""C 대화의 텍스트 처리(순수 텍스트).

목적:
    질문 문장을 만들고 사용자 텍스트 응답을 의도값으로 해석한다.

향후 들어갈 기능:
    - deviation context에 따른 질문 문장 생성
    - 선택지 상수: 1번 = KEEP_TARGET, 2번 = KEEP_CURRENT
      (질문 문장과 응답 해석이 같은 상수를 공유)
    - 재질문 문장 생성
    - 사용자 텍스트 응답 해석 → KEEP_TARGET / KEEP_CURRENT / UNCLEAR
      명확한 응답은 Python Rule(정규화 → 전체 일치 → 구문 일치 → 부정 감지),
      애매한 응답은 추후 llm.py fallback, 그래도 애매하면 UNCLEAR
    - 최초 목표 사물 인식(Day 4 첫 예시는 의자)

하지 않는 것:
    - 실제 음성 I/O(녹음·STT·TTS는 voice.py 담당)
    - 대화 루프·재질문 반복(main.py 담당)
    - Target Design 생성·검증

연결:
    main.py 가 호출한다. 애매한 응답일 때만 추후 llm.py 를 사용한다.
"""
