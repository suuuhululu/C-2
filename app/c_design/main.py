"""C Design 공개 진입점.

목적:
    다른 파트(D Backend·통합)가 C를 호출하는 유일한 입구.
    최초 목표 처리 흐름과 deviation 대화 흐름을 orchestration한다.

향후 들어갈 기능:
    - 최초 목표: (voice 녹음+STT) → dialogue 목표 사물 인식 → designer Initial
      → validator → Initial Target Design 반환
    - deviation 대화: D가 준 Target Design·Current·deviation context로
      dialogue 질문 생성 → voice TTS → voice 녹음+STT → dialogue 응답 해석
      → UNCLEAR면 재질문 반복
      → KEEP_TARGET이면 현재 채택된 Target Design 유지
      → KEEP_CURRENT면 designer Modified → validator
      → 최종 Decision / Design 반환
    - 재질문 횟수는 팀 결정 F04에 따라 기본 제한 없음(테스트용 최대 횟수 인자는 선택)
    - 텍스트 입력 모드에서는 voice를 호출하지 않는다.
    - 정확한 공개 함수 이름 / Input / Output은 Contract 단계에서 확정한다.

하지 않는 것:
    - 음성 I/O·질문 문장·응답 규칙·LLM 호출·검증 로직 자체 구현(각 모듈에 위임)
    - Current 채택·deviation 감지·사람 조립 순서·NextPart·Robot 제어·화면 표시
    - import 시 녹음·재생·모델 로딩·네트워크 요청

연결:
    dialogue.py, voice.py, designer.py 를 호출한다(validator는 designer 경유).
    외부 모듈은 이 파일의 공개 함수만 호출한다.
"""
