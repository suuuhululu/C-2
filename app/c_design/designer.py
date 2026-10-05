"""Target Design 생성.

목적:
    어떤 블록(color·geometry)을 Board의 어느 grid_x / grid_y / layer /
    orientation_deg에 놓는지 담은 Target Design을 만든다.

향후 들어갈 기능:
    - Initial Target Design 생성
    - KEEP_CURRENT 기반 Modified Target Design 생성:
      D가 준 Current의 실제 배치를 보존한 전체 Target Design.
      보존 대상은 LLM이 고르지 않고 Python이 Current 기준으로 결정한다.
    - validator.py 호출과 검증 실패 시 재요청
    - Design 식별·버전은 Python이 결정
    - Mock 먼저(개발 5·6단계), 실제 LLM은 8단계

하지 않는 것:
    - 사람 조립 순서·NextPart·남은 작업·Replan(A 담당)
    - Robot mm 좌표·Board→Robot 변환·TCP / Joint / trajectory
    - 검증 규칙 자체 구현(validator.py 담당)

연결:
    main.py 가 호출한다. llm.py 를 사용하고 validator.py 를 호출한다.
"""
