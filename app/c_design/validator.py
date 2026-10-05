"""C 내부 Design 독립 검증.

목적:
    Initial / Revised Design을 순수 Python 규칙으로 검증한다.
    LLM 판단에 맡기지 않으며 A / D / HMI 없이 단독으로 통과해야 한다.

향후 들어갈 기능(값은 docs/C_DESIGN_CONTRACT.md §2·§9를 따른다):
    - color: YELLOW / BLUE
    - geometry: 2x2x1 / 2x3x1
    - grid_x, grid_y: 0~23 (24×24 Board stud 위치, Robot mm 아님)
    - layer: 1~4, 1-based (layer 1 = Board 위 첫 LEGO 층)
    - orientation_deg: 2x3x1은 0(X 2 / Y 3 stud) 또는 90(X 3 / Y 2 stud), 2x2x1은 0
    - Board 범위, overlap, support(아래 Brick 개수와 무관하게 바로 아래 layer와의
      겹침 합계 2 stud 이상), connectivity
    - 조립된 Brick 보존: Current Brick이 같은 block_id와 같은 color·geometry·grid_x·grid_y·
      orientation_deg·layer가 Revised Design에 그대로 있는지
    - malformed output, Robot field 유입, 입력 Design에 없는 기존 block_id 거부
    - 거부 사유를 [{rule, block_ids, message}]로 반환(후보 거부일 뿐 실패 아님)
    - 입력 Current: overlap 위반만 입력 오류. support 위반은 오류가 아니며
      main이 Revised 생성 대신 escalation으로 처리

하지 않는 것:
    - Design 생성(designer.py 담당)
    - 사람 조립 Plan 검증·조립 순서(A 담당), Expected / Current 비교(D 담당)
    - LLM 호출

연결:
    designer.py 가 호출한다. 다른 C 모듈에 의존하지 않는다.
"""
