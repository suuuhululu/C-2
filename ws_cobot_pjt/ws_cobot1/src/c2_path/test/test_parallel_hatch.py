#!/usr/bin/env python3
"""고정 간격 단방향 평행선 해칭 시험. ROS·로봇은 사용하지 않는다."""
import os
import tempfile
import unittest

import cv2
import numpy as np

from c2_path import extract_2d, image_to_hatch, optimize_2d


def _write(image):
    temp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    temp.close()
    if not cv2.imwrite(temp.name, image):
        raise RuntimeError("시험 이미지 저장 실패")
    return temp.name


class TestParallelHatch(unittest.TestCase):
    def test_filled_rectangle_uses_fixed_spacing_and_cross_hatch(self):
        image = np.full((160, 200), 255, np.uint8)
        cv2.rectangle(image, (20, 20), (180, 140), 0, -1)
        path = _write(image)
        try:
            svg, raw, bbox, stats = image_to_hatch.convert(path, 32.0, 24.0)
        finally:
            os.unlink(path)

        self.assertIn("SIMULATION/test_only", svg)
        self.assertEqual(stats["spacing_mm"], image_to_hatch.HATCH_SPACING_MM)
        self.assertTrue(stats["fixed_test_only"])
        self.assertTrue(raw)
        self.assertGreater(stats["horizontal_hatch_stroke_count"], 1)
        self.assertGreater(stats["vertical_hatch_stroke_count"], 1)
        self.assertEqual(stats["component_modes"]["cross_hatch"], 1)

        uv, uv_stats = extract_2d.transform_raw_strokes(raw, bbox, 32.0, 24.0, 0.0, 80.0)
        ordered, opt_stats = optimize_2d.optimize(uv)
        self.assertEqual(len(ordered), len(uv))
        self.assertEqual(opt_stats["direction_reversed_count"], 0)
        self.assertLessEqual(uv_stats["spacing_mm"]["max"], 2.0 + 1e-9)

    def test_white_hole_is_not_cut(self):
        image = np.full((200, 200), 255, np.uint8)
        cv2.rectangle(image, (20, 20), (180, 180), 0, -1)
        cv2.rectangle(image, (75, 60), (125, 140), 255, -1)
        path = _write(image)
        try:
            _svg, raw, _bbox, _stats = image_to_hatch.convert(path, 40.0, 40.0)
        finally:
            os.unlink(path)

        crossing_rows = [stroke for stroke in raw if 70 <= stroke[0][1] <= 130]
        self.assertTrue(crossing_rows)
        self.assertTrue(all(stroke[-1][0] < 75 or stroke[0][0] > 125 for stroke in crossing_rows))
        self.assertTrue(any(stroke[-1][0] < 75 for stroke in crossing_rows))
        self.assertTrue(any(stroke[0][0] > 125 for stroke in crossing_rows))

    def test_boundary_inset_keeps_endpoints_inside_safe_mask(self):
        image = np.full((180, 180), 255, np.uint8)
        cv2.circle(image, (90, 90), 70, 0, -1)
        path = _write(image)
        try:
            _svg, raw, bbox, stats = image_to_hatch.convert(path, 28.0, 28.0)
        finally:
            os.unlink(path)
        self.assertGreater(stats["boundary_inset_mm"], 0.0)
        self.assertLess(min(p[0] for s in raw for p in s), bbox[2])
        self.assertGreater(max(p[0] for s in raw for p in s), bbox[0])

    def test_blank_fails_but_thin_line_is_kept_as_centerline(self):
        blank = _write(np.full((100, 100), 255, np.uint8))
        thin = np.full((100, 200), 255, np.uint8)
        cv2.line(thin, (10, 50), (190, 50), 0, 1)
        thin_path = _write(thin)
        try:
            with self.assertRaises(ValueError):
                image_to_hatch.convert(blank, 20.0, 20.0)
            _svg, raw, _bbox, stats = image_to_hatch.convert(thin_path, 20.0, 20.0)
            self.assertTrue(raw)
            self.assertEqual(stats["component_modes"]["centerline"], 1)
        finally:
            os.unlink(blank)
            os.unlink(thin_path)

    def test_mixed_image_hatches_wide_area_and_preserves_small_components(self):
        image = np.full((220, 260), 255, np.uint8)
        cv2.line(image, (15, 25), (150, 25), 0, 2)       # 가는 선
        cv2.rectangle(image, (20, 70), (150, 190), 0, -1)  # 넓은 면
        cv2.circle(image, (205, 90), 6, 0, -1)           # 작은 눈/단추
        cv2.circle(image, (220, 150), 4, 0, -1)
        path = _write(image)
        try:
            _svg, raw, _bbox, stats = image_to_hatch.convert(path, 52.0, 44.0)
        finally:
            os.unlink(path)

        modes = stats["component_modes"]
        self.assertEqual(stats["component_count"], 4)
        self.assertGreaterEqual(modes["parallel_hatch"] + modes["cross_hatch"], 1)
        self.assertGreaterEqual(modes["centerline"] + modes["minimum_one_pass"], 1)
        self.assertEqual(modes["omitted_too_small"], 0)
        self.assertEqual(stats["warnings"], [])
        self.assertTrue(raw)
        for detail in stats["components"]:
            self.assertGreater(detail["stroke_count"], 0)

    def test_small_filled_dot_gets_exactly_one_fallback_pass(self):
        image = np.full((120, 240), 255, np.uint8)
        cv2.line(image, (10, 20), (230, 20), 0, 1)  # 전체 배율을 정하는 가는 선
        cv2.circle(image, (120, 80), 1, 0, -1)      # 유효 홈 폭보다 작은 채움
        path = _write(image)
        try:
            _svg, _raw, _bbox, stats = image_to_hatch.convert(path, 44.0, 24.0)
        finally:
            os.unlink(path)

        fallback = [item for item in stats["components"]
                    if item["mode"] == "minimum_one_pass"]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["stroke_count"], 1)
        self.assertLess(fallback[0]["estimated_width_mm"],
                        image_to_hatch.EFFECTIVE_GROOVE_WIDTH_MM)

    def test_sparse_line_art_component_stays_centerline_despite_thick_joint(self):
        image = np.full((180, 240), 255, np.uint8)
        cv2.line(image, (15, 90), (225, 90), 0, 3)
        cv2.line(image, (120, 15), (120, 165), 0, 3)
        cv2.circle(image, (120, 90), 12, 0, -1)  # 연결된 굵은 교차부
        path = _write(image)
        try:
            _svg, raw, _bbox, stats = image_to_hatch.convert(path, 48.0, 36.0)
        finally:
            os.unlink(path)

        self.assertEqual(stats["component_count"], 1)
        detail = stats["components"][0]
        self.assertEqual(detail["mode"], "centerline")
        self.assertLess(detail["fill_ratio"], image_to_hatch.MIN_HATCH_FILL_RATIO)
        self.assertGreater(len(raw), 0)

    def test_cross_hatch_requires_two_safe_lines_in_both_directions(self):
        image = np.full((160, 220), 255, np.uint8)
        cv2.circle(image, (55, 80), 24, 0, -1)   # 충분히 큰 면
        cv2.circle(image, (155, 80), 1, 0, -1)   # 작은 점: 단방향/1패스만 허용
        path = _write(image)
        try:
            _svg, _raw, _bbox, stats = image_to_hatch.convert(path, 44.0, 32.0)
        finally:
            os.unlink(path)
        details = stats["components"]
        self.assertIn("cross_hatch", [item["mode"] for item in details])
        self.assertNotEqual(details[1]["mode"], "cross_hatch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
