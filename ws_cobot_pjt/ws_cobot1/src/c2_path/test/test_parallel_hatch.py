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
    def test_filled_rectangle_uses_fixed_spacing_and_one_direction(self):
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
        self.assertTrue(all(stroke[0][0] <= stroke[-1][0] for stroke in raw))

        uv, uv_stats = extract_2d.transform_raw_strokes(raw, bbox, 32.0, 24.0, 0.0, 80.0)
        ordered, opt_stats = optimize_2d.optimize(uv)
        self.assertEqual(len(ordered), len(uv))
        self.assertEqual(opt_stats["direction_reversed_count"], 0)
        self.assertTrue(all(stroke[0][0] <= stroke[-1][0] for stroke in ordered))
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

    def test_blank_and_too_thin_regions_fail_closed(self):
        blank = _write(np.full((100, 100), 255, np.uint8))
        thin = np.full((100, 200), 255, np.uint8)
        cv2.line(thin, (10, 50), (190, 50), 0, 1)
        thin_path = _write(thin)
        try:
            with self.assertRaises(ValueError):
                image_to_hatch.convert(blank, 20.0, 20.0)
            with self.assertRaises(ValueError):
                image_to_hatch.convert(thin_path, 20.0, 20.0)
        finally:
            os.unlink(blank)
            os.unlink(thin_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
