"""Design 생성.

목적:
    어떤 Brick(color·geometry)을 Board의 어느 grid_x / grid_y / layer /
    orientation_deg에 놓는지 담은 Design을 만든다.

향후 들어갈 기능:
    - Initial Design 생성(Chair 전체 footprint를 Board 중앙에 배치)
    - Revised 생성 시 Revised Design 생성:
      D가 준 Current의 조립된 Brick을 같은 block_id·실제 값으로 보존하고
      남은 Brick을 다시 설계한 전체 Design(full object). 단순 일괄 이동 금지.
      보존 대상은 LLM이 고르지 않고 Python이 Current 기준으로 결정한다.
    - validator.py 호출. 거부 사유를 LLM에 다시 주고 통과할 때까지 재생성
      (고정 최대 횟수 없음, backoff, 연속 거부 횟수로 전략 전환·escalation)
    - design_version·parent_version은 검증 통과 후 Python이 부여
    - 기존 Brick은 LLM이 같은 block_id를 그대로 적고 새 Brick만 null,
      Python이 null에만 새 ID(입력 Design 최대 번호 + 1부터) 부여
    - Mock 먼저(개발 5·6단계), 실제 LLM은 8단계

하지 않는 것:
    - 사람 조립 순서·NextPart·남은 작업·Replan(A 담당)
    - Robot mm 좌표·Board→Robot 변환·TCP / Joint / trajectory
    - 검증 규칙 자체 구현(validator.py 담당)

연결:
    main.py 가 호출한다. llm.py 를 사용하고 validator.py 를 호출한다.
"""
