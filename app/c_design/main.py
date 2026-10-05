"""C Design 공개 진입점.

목적:
    다른 파트(D Backend·통합)가 C를 호출하는 유일한 입구.
    Initial Design 흐름과 Intervention 대화 흐름을 orchestration한다.

향후 들어갈 기능:
    - create_initial_design: (voice 녹음+STT) → dialogue 목표 사물 인식
      → designer Initial Design → validator → 결과 반환
    - run_intervention: D가 준 현재 채택 Design·Current·Difference로
      dialogue 질문 생성 → voice TTS → voice 녹음+STT → dialogue 응답 해석
      → UNCLEAR면 선택지를 다시 설명해 재질문, 침묵이면 계속 대기(Day4 시간 기준 자동 취소 없음)
      → KEEP이면 현재 채택 Design 그대로 반환
      → REVISE면 designer Revised Design(최대 10회 재생성) → validator
      → 명시적 취소(CANCEL) 또는 should_stop(STOP)이면 CANCELLED 반환
      → HRI 결과 / Design 반환
    - 오류·실패(Contract §10): 일시적 음성·LLM 실패는 간격을 두고 재시도,
      재생성 한도 도달은 DESIGN_GENERATION_FAILED, 같은 서비스 지속 장애만 FAILED
    - Current가 support 후보 기준을 위반하면 REVISE 선택 시 LLM 재생성 없이
      즉시 escalation 질문(해당 블록을 채택 Design 위치로 되돌리기 제안)
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
