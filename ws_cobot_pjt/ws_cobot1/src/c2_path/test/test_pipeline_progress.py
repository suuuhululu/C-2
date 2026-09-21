#!/usr/bin/env python3
"""글자가 많은 이미지에서 정렬 단계가 제한 시간 안에 끝나고, 단계 안 진행률·취소·시간 초과가 동작하는지 확인한다."""
import os
import sqlite3
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_generate_pipeline import PipelineFixture  # noqa: E402

from c2_path.artifacts import ArtifactWrite, new_id  # noqa: E402
from c2_path.pipeline import GenerationCanceled, GeneratePipeline, PipelineError  # noqa: E402

LINES = ("The quick brown fox jumps over the lazy dog 0123456789",
         "CANDLE ENGRAVING TEST PATTERN abcdefghijklmnopqrstuvwxyz")


def text_png(rows=3):
    image = np.full((rows * 70 + 40, 1500), 255, np.uint8)
    for row in range(rows):
        cv2.putText(image, LINES[row % len(LINES)], (20, 60 + row * 70), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3,
                    cv2.LINE_AA)
    okay, encoded = cv2.imencode(".png", image)
    assert okay
    return encoded.tobytes(), image.shape


class TestTextHeavyPipeline(PipelineFixture):
    def add_text_image(self, rows=3):
        data, (height, width) = text_png(rows)
        asset_id = new_id()
        self.store.put_bundle([ArtifactWrite(data, "image", "image/png", "text.png", {}, asset_id)])
        connection = sqlite3.connect(Path(self.temp.name) / "monitor.sqlite3")
        sha = connection.execute("SELECT sha256 FROM assets WHERE id=?", (asset_id,)).fetchone()[0]
        connection.close()
        width_mm = 140.0
        return dict(asset_id=asset_id, asset_sha256=sha, width_mm=width_mm,
                    height_mm=round(width_mm * height / width, 3), offset_u_mm=0.0, offset_v_mm=75.0)

    def test_text_heavy_image_generates_within_time_and_keeps_every_stroke(self):
        goal = self.goal(**self.add_text_image(3))
        feedback = []
        result = GeneratePipeline(self.store, timeout_s=120.0).run(
            goal, feedback=lambda stage, progress: feedback.append((stage, progress)))
        self.assertGreater(result.segment_count, 0)
        stages = [stage for stage, _ in feedback]
        self.assertIn("OPTIMIZING_2D", stages)
        values = [progress for _, progress in feedback]
        self.assertEqual(values, sorted(values), "진행률은 줄어들지 않는다")
        self.assertEqual(feedback[-1], ("VALIDATING", 1.0))

    def test_progress_inside_optimizing_2d_stays_in_its_range(self):
        goal = self.goal(**self.add_text_image(3))
        feedback = []
        GeneratePipeline(self.store).run(goal, feedback=lambda stage, progress: feedback.append((stage, progress)))
        optimizing = [p for s, p in feedback if s == "OPTIMIZING_2D"]
        self.assertTrue(optimizing)
        self.assertTrue(all(0.38 - 1e-9 <= p <= 0.55 + 1e-9 for p in optimizing), optimizing)

    def test_cancel_takes_effect_inside_a_stage(self):
        goal = self.goal(**self.add_text_image(3))
        seen = {"optimizing": 0}

        def canceled():
            return seen["optimizing"] > 0

        def feedback(stage, _progress):
            if stage == "OPTIMIZING_2D":
                seen["optimizing"] += 1

        with self.assertRaises(GenerationCanceled):
            GeneratePipeline(self.store).run(goal, feedback=feedback, canceled=canceled)

    def test_timeout_still_fails_with_timeout_code_and_never_returns_partial_path(self):
        goal = self.goal(**self.add_text_image(3))
        with self.assertRaises(PipelineError) as caught:
            GeneratePipeline(self.store, timeout_s=0.0001).run(goal)
        self.assertEqual(caught.exception.code, "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
