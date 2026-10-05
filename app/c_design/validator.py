"""C 내부 Target Design 독립 검증.

목적:
    Initial / Modified Target Design을 순수 Python 규칙으로 검증한다.
    LLM 판단에 맡기지 않으며 A / D / HMI 없이 단독으로 통과해야 한다.

향후 들어갈 기능:
    - color: YELLOW / BLUE
    - geometry: 2x2x1 / 2x3x1
    - grid_x, grid_y: 0~23 (24×24 Board stud 위치, Robot mm 아님)
    - layer: 1~4, 1-based (layer 1 = Board 위 첫 LEGO 층)
    - orientation_deg: 2x3x1은 0(X 2 / Y 3 stud) 또는 90(X 3 / Y 2 stud), 2x2x1은 0
    - Board 범위, overlap, support, connectivity
    - Current 보존(preserved): 보존 대상의 color·geometry·grid_x·grid_y·
      orientation_deg·layer가 바뀌면 거부
    - malformed output, Robot field 유입 거부

하지 않는 것:
    - Target Design 생성(designer.py 담당)
    - 사람 조립 Plan 검증·조립 순서(A 담당), Expected / Current 비교(D 담당)
    - LLM 호출

연결:
    designer.py 가 호출한다. 다른 C 모듈에 의존하지 않는다.
"""
