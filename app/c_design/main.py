"""C Design 공개 진입점.

목적:
    다른 파트(D Backend·통합)가 C를 호출하는 유일한 입구.
    Initial Design 흐름과 Intervention 대화 흐름을 orchestration한다.

향후 들어갈 기능:
    - create_initial_design: (voice 녹음+STT) → dialogue 목표 사물 인식
      → designer Initial Design → validator → 결과 반환
    - run_intervention: D가 준 현재 채택 Design·Current·Difference로
      dialogue 질문 생성 → voice TTS → voice 녹음+STT → dialogue 응답 해석
      → 불명확이면 즉시 재질문, 침묵이면 짧은 확인 질문
      → Original 유지면 현재 채택 Design 그대로 반환
      → Revised 생성이면 designer Revised Design → validator
      → HRI 결과 / Design 반환
    - 음성 모드 무응답(Contract §4.3): 침묵 25초 확인 질문, 60초마다 상태 확인 질문,
      의미 있는 발화 없이 300초면 최종 안내 후 CANCELLED / NO_RESPONSE 반환.
      thread·watchdog 없이 대화 루프에서 침묵 시계 확인
    - Recovery First(Contract §10): 일시적 음성·LLM 실패는 backoff 재시도,
      같은 서비스가 300초 계속 실패할 때만 FAILED
    - Current가 support 규칙을 위반하면 Revised 생성 선택 시 LLM 재생성 없이
      즉시 escalation 질문(해당 Brick을 채택 Design 위치로 되돌리기 제안)
    - 텍스트 입력 모드에서는 voice를 호출하지 않는다.
    - 공개 함수 Input / Output / 실패 반환은 docs/C_DESIGN_CONTRACT.md를 따른다.

하지 않는 것:
    - 음성 I/O·질문 문장·응답 규칙·LLM 호출·검증 로직 자체 구현(각 모듈에 위임)
    - Current 채택·Difference 판정·사람 조립 순서·NextPart·Robot 제어·화면 표시
    - import 시 녹음·재생·모델 로딩·네트워크 요청

연결:
    dialogue.py, voice.py, designer.py 를 호출한다(validator는 designer 경유).
    외부 모듈은 이 파일의 공개 함수만 호출한다.
"""
