"""C 대화의 텍스트 처리(순수 텍스트).

목적:
    질문 문장을 만들고 사용자 텍스트 응답을 HRI 결과로 해석한다.

향후 들어갈 기능:
    - 변경 context(현재 채택 Design·Current·Difference)에 따른 질문 문장 생성
    - 선택지 상수: 1번 = KEEP_ORIGINAL(Original 유지), 2번 = CREATE_REVISED(Revised 생성)
      (질문 문장과 응답 해석이 같은 상수를 공유)
    - 재질문, 침묵 시 확인 질문·상태 확인 질문, 무응답 최종 안내 문장 생성
    - escalation 질문 문장(잘못 놓인 Brick을 채택 Design 위치로 옮기기 제안)
    - 사용자 텍스트 응답 해석 → KEEP_ORIGINAL / CREATE_REVISED / UNCLEAR(불명확)
      명확한 응답은 Python Rule(정규화 → 전체 일치 → 구문 일치 → 부정 감지),
      애매한 응답은 추후 llm.py fallback, 그래도 애매하면 UNCLEAR
    - 최초 목표 사물 인식(Day 4는 CHAIR)

하지 않는 것:
    - 실제 음성 I/O(녹음·STT·TTS는 voice.py 담당)
    - 대화 루프·재질문 반복(main.py 담당)
    - Design 생성·검증

연결:
    main.py 가 호출한다. 애매한 응답일 때만 추후 llm.py 를 사용한다.
"""
