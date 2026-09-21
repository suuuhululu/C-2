#!/usr/bin/env python3
"""ordering.py(빠른 2-opt)가 이전 구현과 같은 순서를 내는지, 획을 하나도 잃지 않는지 확인한다.

이전 구현은 후보마다 전체 비용을 처음부터 다시 더했다(패스당 O(n^3)). 글자 많은 이미지에서 2분 제한을 넘긴 원인이다.
여기서는 그 이전 구현을 시험 안에 그대로 두고(느리지만 정답 기준), 무작위 입력으로 결과를 대조한다.
"""
import math
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from c2_path import generate_path, optimize_2d, ordering  # noqa: E402


def _reference_two_opt(order, strokes, max_pass=50):
    """이전 optimize_2d.two_opt 와 같은 구현(참조용)."""
    def total(o):
        return sum(math.dist(strokes[a][-1], strokes[b][0]) for a, b in zip(o[:-1], o[1:]))
    best = list(order)
    best_cost = total(best)
    n = len(best)
    if n < 4:
        return best, best_cost, 0
    moves = 0
    for _ in range(max_pass):
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                cand = best[:i + 1] + best[i + 1:j + 1][::-1] + best[j + 1:]
                c = total(cand)
                if c < best_cost - 1e-12:
                    best, best_cost = cand, c
                    improved = True
                    moves += 1
        if not improved:
            break
    return best, best_cost, moves


def random_strokes(rng, n):
    strokes = []
    for _ in range(n):
        x, y = rng.uniform(0, 100), rng.uniform(0, 100)
        length = rng.uniform(0.5, 6.0)
        angle = rng.uniform(0, 2 * math.pi)
        strokes.append([(x, y), (x + length * math.cos(angle), y + length * math.sin(angle))])
    return strokes


class TestTwoOptMatchesReference(unittest.TestCase):
    def test_same_order_and_move_count_as_previous_implementation(self):
        rng = random.Random(20260921)
        for trial in range(60):
            strokes = random_strokes(rng, rng.randint(4, 40))
            init = optimize_2d.nearest_neighbor(strokes)
            expected, expected_cost, expected_moves = _reference_two_opt(init, strokes)
            got, got_cost, got_moves = optimize_2d.two_opt(init, strokes)
            self.assertEqual(got, expected, f"trial {trial}")
            self.assertEqual(got_moves, expected_moves, f"trial {trial}")
            self.assertAlmostEqual(got_cost, expected_cost, places=9)

    def test_no_stroke_is_dropped_or_duplicated(self):
        rng = random.Random(7)
        strokes = random_strokes(rng, 300)
        ordered, stats = optimize_2d.optimize(strokes)
        self.assertEqual(len(ordered), 300)
        self.assertEqual(sorted(stats["order"]), list(range(300)))
        self.assertEqual({id(s) for s in ordered}, {id(s) for s in strokes})   # 획 객체 그대로

    def test_strokes_keep_their_direction(self):
        rng = random.Random(3)
        strokes = random_strokes(rng, 50)
        ordered, _ = optimize_2d.optimize(strokes)
        for stroke in ordered:
            self.assertIn(stroke, strokes)

    def test_small_inputs(self):
        self.assertEqual(optimize_2d.optimize([])[0], [])
        one = [[(0.0, 0.0), (1.0, 0.0)]]
        self.assertEqual(optimize_2d.optimize(one)[0], one)
        three = [[(0.0, 0.0), (1.0, 0.0)], [(5.0, 0.0), (6.0, 0.0)], [(2.0, 0.0), (3.0, 0.0)]]
        self.assertEqual(len(optimize_2d.optimize(three)[0]), 3)


class TestTextHeavyIsFast(unittest.TestCase):
    """글자 많은 이미지 규모(획 수백 개)가 제한 시간 안에 끝난다."""

    def test_544_strokes_two_stage_sorting_is_seconds_not_minutes(self):
        rng = random.Random(544)
        strokes = random_strokes(rng, 544)
        started = time.monotonic()
        ordered, stats = optimize_2d.optimize(strokes)
        elapsed = time.monotonic() - started
        self.assertEqual(len(ordered), 544)
        self.assertFalse(stats["two_opt_stopped_early"])
        self.assertLess(elapsed, 20.0, f"{elapsed:.1f}s")


class TestProgressAndStop(unittest.TestCase):
    def test_progress_is_reported_within_the_stage_and_ends_at_one(self):
        rng = random.Random(1)
        strokes = random_strokes(rng, 400)
        seen = []
        optimize_2d.optimize(strokes, on_progress=seen.append)
        self.assertTrue(seen)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in seen))
        self.assertEqual(seen[-1], 1.0)

    def test_exception_from_progress_callback_propagates(self):
        """취소·시간 초과는 콜백이 예외를 던져 단계 도중에도 멈추게 한다."""
        class Stop(Exception):
            pass

        def raise_stop(_fraction):
            raise Stop()

        rng = random.Random(2)
        with self.assertRaises(Stop):
            optimize_2d.optimize(random_strokes(rng, 300), on_progress=raise_stop)

    def test_soft_stop_returns_a_valid_complete_order(self):
        rng = random.Random(5)
        strokes = random_strokes(rng, 300)
        ordered, stats = optimize_2d.optimize(strokes, should_stop=lambda: True)
        self.assertEqual(len(ordered), 300)
        self.assertEqual(sorted(stats["order"]), list(range(300)))
        self.assertLessEqual(stats["travel_mm_after_2opt"], stats["travel_mm_nearest_neighbor"] + 1e-6)

    def test_ordering_core_never_returns_worse_than_input(self):
        rng = random.Random(9)
        for _ in range(20):
            n = rng.randint(3, 30)
            cost = np_random_cost(rng, n)
            start = list(range(n))
            order, value, _moves, _stopped = ordering.two_opt(start, cost)
            self.assertEqual(sorted(order), start)
            self.assertLessEqual(value, ordering.sequential_cost(start, cost) + 1e-9)


def np_random_cost(rng, n):
    import numpy as np
    matrix = np.array([[rng.uniform(0, 10) for _ in range(n)] for _ in range(n)])
    np.fill_diagonal(matrix, np.inf)
    return matrix


class TestSafetyCostOrdering(unittest.TestCase):
    """generate_path.order_safety_cost — 안전비용 정렬도 같은 방식으로 빨라졌다."""

    def _mapped(self, n, seed):
        from c2_path import map_3d
        rng = random.Random(seed)
        uv = []
        for _ in range(n):
            u, v = rng.uniform(-100.0, 100.0), rng.uniform(20.0, 140.0)
            uv.append([(u, v), (u + rng.uniform(1, 6), v + rng.uniform(-3, 3))])
        mapped, failures, _stats = map_3d.map_strokes(uv)
        self.assertEqual(failures, [])
        return mapped

    def test_matrix_equals_scalar_move_cost(self):
        import numpy as np
        mapped = self._mapped(25, 11)
        clearance = 0.010
        matrix = generate_path.move_cost_matrix(mapped, clearance)
        for i, a in enumerate(mapped):
            for j, b in enumerate(mapped):
                if i == j:
                    continue
                scalar = generate_path.move_cost(a, b, clearance)
                if math.isinf(scalar):
                    self.assertTrue(np.isinf(matrix[i, j]), (i, j))
                else:
                    self.assertAlmostEqual(matrix[i, j], scalar, places=9, msg=(i, j))

    def test_order_is_a_permutation_and_fast_for_hundreds_of_strokes(self):
        mapped = self._mapped(400, 12)
        started = time.monotonic()
        order, stats = generate_path.order_safety_cost(mapped, 0.010, initial_order=list(range(len(mapped))))
        elapsed = time.monotonic() - started
        self.assertEqual(sorted(order), list(range(len(mapped))))
        self.assertLess(elapsed, 20.0, f"{elapsed:.1f}s")
        self.assertIn("two_opt_stopped_early", stats)


if __name__ == "__main__":
    unittest.main()
