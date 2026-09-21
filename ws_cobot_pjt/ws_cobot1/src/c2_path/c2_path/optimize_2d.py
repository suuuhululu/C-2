#!/usr/bin/env python3
"""optimize_2d.py — 획 방문 순서만 개선한다. CUT 형상은 건드리지 않는다.

적용한 결정 (2026-09-19 최종 조합):
  - 분리된 획의 초기 방문 순서는 Nearest Neighbor.
  - 2-opt 는 **비접촉 이동 순서만** 개선한다. 획의 점열은 그대로 둔다.
  - 열린 획의 방향 반전은 실제 양방향 가공 품질이 확인된 경우에만 허용한다.
    아직 미확인이므로 기본값은 `allow_reverse=False` 이고, 각 획은 원래 방향으로만
    지나간다. (일반적인 2-opt 는 부분열을 뒤집으며 진행 방향까지 바꾸므로,
    여기서는 방문 순서만 뒤집고 각 획의 방향은 유지하는 형태로 구현한다.)

닫힌 획(하트처럼 시작=끝)은 시작점을 옮겨도 형상이 같지만, 그것도 형상 변경으로
보고 이번 결정에서는 하지 않는다.
"""
import math
import time

import numpy as np

from . import ordering


def _d(a, b):
    return math.dist(a, b)


def travel_cost(order, strokes, allow_reverse=False, reversed_flags=None):
    """획 사이 비접촉 이동 거리 합. 획 내부 길이는 포함하지 않는다."""
    total = 0.0
    for k in range(len(order) - 1):
        i, j = order[k], order[k + 1]
        a = strokes[i][0] if (reversed_flags and reversed_flags[i]) else strokes[i][-1]
        b = strokes[j][-1] if (reversed_flags and reversed_flags[j]) else strokes[j][0]
        total += _d(a, b)
    return total


def nearest_neighbor(strokes, start=0, on_progress=None):
    """가장 가까운 다음 획을 고르는 초기해. 방향은 바꾸지 않는다."""
    n = len(strokes)
    unused = set(range(n))
    order = [start]
    unused.discard(start)
    last_poll = time.monotonic()
    while unused:
        cur_end = strokes[order[-1]][-1]
        nxt = min(unused, key=lambda j: _d(cur_end, strokes[j][0]))
        order.append(nxt)
        unused.discard(nxt)
        if on_progress is not None and time.monotonic() - last_poll >= 0.2:
            last_poll = time.monotonic()
            on_progress(len(order) / n)
    return order


def cost_matrix(strokes):
    """C[i][j] = 획 i의 끝점에서 획 j의 시작점까지 거리 (방향은 바꾸지 않으므로 끝→시작만 쓴다)."""
    n = len(strokes)
    ends = [strokes[i][-1] for i in range(n)]
    starts = [strokes[i][0] for i in range(n)]
    matrix = np.zeros((n, n))
    for i in range(n):
        row = matrix[i]
        end = ends[i]
        for j in range(n):
            row[j] = math.dist(end, starts[j])
    return matrix


def two_opt(order, strokes, max_pass=50, on_progress=None, should_stop=None):
    """방문 순서만 개선. 각 획의 진행 방향은 유지한다.

    부분열 [i..j] 의 방문 순서를 뒤집어도 각 획은 여전히 start->end 로 지나간다.
    비용은 끝→시작 거리 행렬로 비교한다 (대칭 가정 없음). 계산은 `ordering.two_opt` 가 하며
    이전의 후보마다 전체 재계산하던 구현과 같은 순서를 돌려준다.

    반환: (순서, 비용, 채택 횟수). 도중에 멈췄는지는 `two_opt_full` 로 본다.
    """
    best, cost, moves, _stopped = two_opt_full(order, strokes, max_pass, on_progress, should_stop)
    return best, cost, moves


def two_opt_full(order, strokes, max_pass=50, on_progress=None, should_stop=None):
    if len(order) < 4:
        return list(order), travel_cost(list(order), strokes), 0, False
    return ordering.two_opt(order, cost_matrix(strokes), max_pass=max_pass, min_n=4,
                            on_progress=on_progress, should_stop=should_stop)


def optimize(strokes, allow_reverse=False, on_progress=None, should_stop=None):
    """반환: (정렬된 획 목록, stats)

    on_progress(0~1) : 이 단계 안의 진행률. 여기서 던진 예외(취소·시간 초과)는 그대로 전파한다.
    should_stop()    : True 면 2-opt 개선만 멈추고 지금 순서를 쓴다. 획은 하나도 빠지지 않는다.
    """
    if not strokes:
        return [], {"stroke_count": 0}
    notify = on_progress or (lambda _fraction: None)
    init = nearest_neighbor(strokes, on_progress=lambda f: notify(0.3 * f))
    cost_nn = travel_cost(init, strokes)
    order, cost_2opt, moves, stopped = two_opt_full(
        init, strokes, on_progress=lambda f: notify(0.3 + 0.7 * f), should_stop=should_stop)
    ordered = [strokes[i] for i in order]
    notify(1.0)
    stats = {
        "stroke_count": len(strokes),
        "order": order,
        "travel_mm_nearest_neighbor": round(cost_nn, 4),
        "travel_mm_after_2opt": round(cost_2opt, 4),
        "two_opt_improvements": moves,
        "two_opt_stopped_early": bool(stopped),
        "direction_reversal_allowed": allow_reverse,
        "direction_reversed_count": 0,
        "shape_modified": False,
    }
    return ordered, stats
