#!/usr/bin/env python3
"""ordering.py — 획 방문 순서 개선(2-opt)의 공용 구현.

`optimize_2d`(2D 이동 거리)와 `generate_path`(안전비용)가 같은 방식으로 순서를 개선하므로 한곳에 둔다.

이전 구현은 후보 순서마다 전체 비용을 처음부터 다시 더해서 획이 n개일 때 한 번 훑는 데 O(n^3)이 들었다.
글자가 많은 이미지(획 수백 개)에서는 2분 제한을 넘겼다. 이 구현은 다음 두 가지만 바꾼다.

  1. 비용 행렬 C[i, j] (획 i의 끝 → 획 j의 시작)를 한 번 만들어 두고,
  2. 부분열 뒤집기의 비용 변화를 접두합으로 O(1)에 구한다.

탐색 순서(i 오름차순, j 오름차순), 첫 개선 즉시 채택, 채택 조건(`새 비용 < 현재 비용 − 1e-12`),
최대 패스 수는 이전 구현과 같다. 접두합의 부동소수 오차 때문에 놓치거나 잘못 채택하는 일이 없도록,
접두합으로 고른 후보는 이전 구현과 같은 방식(순차 합)으로 전체 비용을 다시 계산해 확정한다.
그래서 같은 입력이면 이전 구현과 같은 순서가 나온다 (test_ordering.py 가 무작위 입력으로 대조한다).

획은 하나도 빼거나 바꾸지 않는다. 순서만 다룬다.
"""
import time

import numpy as np

_EPS = 2.3e-16
ACCEPT_MARGIN = 1e-12          # 이전 구현과 같은 채택 조건
BIG = 1e9                      # 금지된 이동(무한대)을 접두합 계산에서 대신하는 큰 수 — 확정은 실제 값으로 한다


def sequential_cost(order, cost):
    """순서를 따라 비용을 앞에서부터 차례로 더한다 (이전 구현의 `total()`과 같은 덧셈 순서)."""
    if len(order) < 2:
        return 0.0
    total = 0.0
    for value in cost[order[:-1], order[1:]].tolist():
        total += value
    return total


def _prefix(order, cost):
    forward = np.concatenate(([0.0], np.cumsum(np.minimum(cost[order[:-1], order[1:]], BIG))))
    reverse = np.concatenate(([0.0], np.cumsum(np.minimum(cost[order[1:], order[:-1]], BIG))))
    return forward, reverse


def two_opt(order, cost, *, max_pass=50, min_n=3, on_progress=None, should_stop=None, poll_s=0.2):
    """부분열 뒤집기 2-opt. 각 획의 진행 방향은 바꾸지 않고 방문 순서만 뒤집는다.

    order       : 초기 방문 순서 (획 번호 목록)
    cost        : n×n 배열. cost[i, j] = 획 i를 끝내고 획 j를 시작하는 이동 비용 (금지는 inf)
    on_progress : 0~1 사이 추정 진행률을 받는 함수 (poll_s 초마다 호출). 여기서 예외를 던지면 그대로 전파된다
                  (취소·시간 초과).
    should_stop : True 를 돌려주면 개선을 멈추고 지금까지의 순서를 돌려준다 (소프트 시간 제한).
    반환        : (순서 목록, 비용, 채택한 뒤집기 횟수, 도중에 멈췄는지)
    """
    cost = np.asarray(cost, dtype=float)
    o = np.asarray(order, dtype=np.int64).copy()
    n = len(o)
    best_cost = sequential_cost(o, cost)
    if n < min_n:
        return o.tolist(), best_cost, 0, False

    moves = 0
    stopped = False
    last_poll = time.monotonic()
    for pass_index in range(max_pass):
        improved = False
        forward, reverse = _prefix(o, cost)
        tolerance = 4.0 * n * _EPS * max(1.0, float(forward[-1]), float(reverse[-1]))
        for i in range(n - 1):
            now = time.monotonic()
            if now - last_poll >= poll_s:
                last_poll = now
                if on_progress is not None:
                    on_progress(1.0 - 1.0 / (1.0 + pass_index + i / n))
                if should_stop is not None and should_stop():
                    return o.tolist(), best_cost, moves, True
            start = i + 2
            while start < n:
                js = np.arange(start, n)
                a, b = o[i], o[i + 1]
                c = o[js]
                has_next = js + 1 < n
                d = o[np.minimum(js + 1, n - 1)]
                np_next = np.where(has_next, 1.0, 0.0)
                old = (min(cost[a, b], BIG) + (forward[js] - forward[i + 1])
                       + np.minimum(cost[c, d], BIG) * np_next)
                new = (np.minimum(cost[a, c], BIG) + (reverse[js] - reverse[i + 1])
                       + np.minimum(cost[b, d], BIG) * np_next)
                candidates = np.flatnonzero((new - old) < (-ACCEPT_MARGIN + tolerance))
                accepted = False
                for k in candidates:
                    j = int(js[k])
                    trial = o.copy()
                    trial[i + 1:j + 1] = trial[i + 1:j + 1][::-1]
                    trial_cost = sequential_cost(trial, cost)
                    if trial_cost < best_cost - ACCEPT_MARGIN:
                        o, best_cost = trial, trial_cost
                        moves += 1
                        improved = accepted = True
                        forward, reverse = _prefix(o, cost)
                        tolerance = 4.0 * n * _EPS * max(1.0, float(forward[-1]), float(reverse[-1]))
                        start = j + 1
                        break
                if not accepted:
                    break
        if not improved:
            break
    if on_progress is not None:
        on_progress(1.0)
    return o.tolist(), best_cost, moves, stopped
