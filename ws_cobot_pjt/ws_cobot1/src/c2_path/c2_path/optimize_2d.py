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


def nearest_neighbor(strokes, start=0):
    """가장 가까운 다음 획을 고르는 초기해. 방향은 바꾸지 않는다."""
    n = len(strokes)
    unused = set(range(n))
    order = [start]
    unused.discard(start)
    while unused:
        cur_end = strokes[order[-1]][-1]
        nxt = min(unused, key=lambda j: _d(cur_end, strokes[j][0]))
        order.append(nxt)
        unused.discard(nxt)
    return order


def two_opt(order, strokes, max_pass=50):
    """방문 순서만 개선. 각 획의 진행 방향은 유지한다.

    부분열 [i..j] 의 방문 순서를 뒤집어도 각 획은 여전히 start->end 로 지나간다.
    그래서 비용을 매번 실제로 계산해서 비교한다 (대칭 가정 없음).
    """
    best = list(order)
    best_cost = travel_cost(best, strokes)
    n = len(best)
    if n < 4:
        return best, best_cost, 0
    improved_total = 0
    for _ in range(max_pass):
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                cand = best[:i + 1] + best[i + 1:j + 1][::-1] + best[j + 1:]
                c = travel_cost(cand, strokes)
                if c < best_cost - 1e-12:
                    best, best_cost = cand, c
                    improved = True
                    improved_total += 1
        if not improved:
            break
    return best, best_cost, improved_total


def optimize(strokes, allow_reverse=False):
    """반환: (정렬된 획 목록, stats)"""
    if not strokes:
        return [], {"stroke_count": 0}
    init = nearest_neighbor(strokes)
    cost_nn = travel_cost(init, strokes)
    order, cost_2opt, moves = two_opt(init, strokes)
    ordered = [strokes[i] for i in order]
    stats = {
        "stroke_count": len(strokes),
        "order": order,
        "travel_mm_nearest_neighbor": round(cost_nn, 4),
        "travel_mm_after_2opt": round(cost_2opt, 4),
        "two_opt_improvements": moves,
        "direction_reversal_allowed": allow_reverse,
        "direction_reversed_count": 0,
        "shape_modified": False,
    }
    return ordered, stats
