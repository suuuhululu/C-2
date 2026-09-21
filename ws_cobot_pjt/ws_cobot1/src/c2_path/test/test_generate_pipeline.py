#!/usr/bin/env python3
"""상위 파이프라인·관리 파일 안전장치 회귀 시험. ROS·로봇은 사용하지 않는다."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from c2_path import validate_path, workcell as wc  # noqa: E402
from c2_path.artifacts import (  # noqa: E402
    ArtifactError,
    ArtifactWrite,
    ManagedArtifactStore,
    json_bytes,
    new_id,
)
from c2_path.pipeline import (  # noqa: E402
    GeneratePipeline,
    GenerationCanceled,
    PipelineError,
    matching_test_profile,
    validate_goal,
    validate_profile,
)


def initialize_store(root):
    root = Path(root)
    (root / "assets").mkdir()
    connection = sqlite3.connect(root / "monitor.sqlite3")
    connection.execute(
        """CREATE TABLE assets (
        id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, kind TEXT NOT NULL,
        storage_key TEXT NOT NULL UNIQUE, mime TEXT NOT NULL, name TEXT NOT NULL,
        size_bytes INTEGER NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL)"""
    )
    connection.commit()
    connection.close()
    return ManagedArtifactStore(root)


def line_png():
    image = np.full((200, 200), 255, np.uint8)
    cv2.line(image, (20, 100), (180, 100), 0, 5, cv2.LINE_AA)
    okay, encoded = cv2.imencode(".png", image)
    assert okay
    return encoded.tobytes()


def filled_rectangle_png():
    image = np.full((200, 200), 255, np.uint8)
    cv2.rectangle(image, (25, 35), (175, 165), 0, -1)
    okay, encoded = cv2.imencode(".png", image)
    assert okay
    return encoded.tobytes()


class PipelineFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = initialize_store(self.temp.name)
        self.asset_id, self.profile_id = new_id(), new_id()
        self.store.put_bundle([
            ArtifactWrite(line_png(), "image", "image/png", "line.png", {}, self.asset_id),
            ArtifactWrite(json_bytes(matching_test_profile()), "profile", "application/json",
                          "c2-path-test-profile.json", {}, self.profile_id),
        ])
        self.asset = self.store.read(self.asset_id, self._sha(self.asset_id), ("image",))
        self.profile = self.store.read(self.profile_id, self._sha(self.profile_id), ("profile",))

    def tearDown(self):
        self.temp.cleanup()

    def _sha(self, asset_id):
        connection = sqlite3.connect(Path(self.temp.name) / "monitor.sqlite3")
        value = connection.execute("SELECT sha256 FROM assets WHERE id=?", (asset_id,)).fetchone()[0]
        connection.close()
        return value

    def goal(self, **changes):
        value = {
            "schema_version": 2,
            "request_id": str(uuid4()),
            "source_mode": "SIMULATION",
            "asset_id": self.asset_id,
            "asset_sha256": self.asset.sha256,
            "width_mm": 24.0,
            "height_mm": 24.0,
            "offset_u_mm": 0.0,
            "offset_v_mm": 105.0,
            "rotation_deg": 0.0,
            "conversion_preset": "raster_centerline_bezier",
            "tool_id": wc.TOOL_ID,
            "profile_snapshot_id": self.profile_id,
            "profile_sha256": self.profile.sha256,
        }
        value.update(changes)
        return value


class TestGeneratePipeline(PipelineFixture):
    def test_success_writes_complete_bundle_and_valid_path(self):
        feedback = []
        result = GeneratePipeline(self.store).run(
            self.goal(), feedback=lambda stage, progress: feedback.append((stage, progress))
        )
        self.assertGreater(result.segment_count, 0)
        self.assertGreater(result.cut_length_m, 0.0)
        self.assertEqual(feedback[-1], ("VALIDATING", 1.0))
        path_artifact = self.store.read(result.path_asset_id, result.path_sha256, ("path",))
        path = json.loads(path_artifact.path.read_text(encoding="utf-8"))
        self.assertTrue(path["test_only"])
        self.assertTrue(validate_path.validate(path)["passed"])
        for aid, kind in ((result.svg_asset_id, "svg"),
                          (result.preview_asset_id, "preview"),
                          (result.validation_report_id, "validation")):
            self.store.read(aid, self._sha(aid), (kind,))

    def test_parallel_hatch_preset_generates_valid_path_with_fixed_spacing(self):
        hatch_asset_id = new_id()
        self.store.put_bundle([
            ArtifactWrite(filled_rectangle_png(), "image", "image/png", "filled.png", {}, hatch_asset_id)
        ])
        hatch_asset = self.store.read(hatch_asset_id, self._sha(hatch_asset_id), ("image",))
        goal = self.goal(
            asset_id=hatch_asset_id,
            asset_sha256=hatch_asset.sha256,
            conversion_preset="raster_parallel_hatch",
        )
        result = GeneratePipeline(self.store).run(goal)
        path = json.loads(self.store.read(result.path_asset_id, result.path_sha256, ("path",)).data)
        report = json.loads(self.store.read(
            result.validation_report_id, self._sha(result.validation_report_id), ("validation",)
        ).data)
        self.assertTrue(validate_path.validate(path)["passed"])
        self.assertGreater(report["stats"]["convert"]["stroke_count"], 1)
        self.assertEqual(report["stats"]["convert"]["spacing_mm"], 0.8)
        self.assertTrue(report["stats"]["convert"]["fixed_test_only"])

    def test_any_mapping_failure_fails_whole_generation(self):
        with self.assertRaises(PipelineError) as caught:
            GeneratePipeline(self.store).run(self.goal(offset_v_mm=200.0))   # 옆면(150mm) 밖
        self.assertEqual(caught.exception.code, "VALIDATION_FAILED")
        self.assertTrue(caught.exception.validation_report_id)
        connection = sqlite3.connect(Path(self.temp.name) / "monitor.sqlite3")
        path_count = connection.execute("SELECT count(*) FROM assets WHERE kind='path'").fetchone()[0]
        connection.close()
        self.assertEqual(path_count, 0, "실패한 생성이 실행 path를 등록함")

    def test_cancel_before_work_registers_no_output(self):
        before = self._asset_count()
        with self.assertRaises(GenerationCanceled):
            GeneratePipeline(self.store).run(self.goal(), canceled=lambda: True)
        self.assertEqual(self._asset_count(), before)

    def _asset_count(self):
        connection = sqlite3.connect(Path(self.temp.name) / "monitor.sqlite3")
        count = connection.execute("SELECT count(*) FROM assets").fetchone()[0]
        connection.close()
        return count


class TestInputAndProfile(PipelineFixture):
    def test_mock_preset_is_not_silently_treated_as_real_conversion(self):
        with self.assertRaises(PipelineError) as caught:
            validate_goal(self.goal(conversion_preset="simulation_centerline"))
        self.assertEqual(caught.exception.code, "UNSUPPORTED_FORMAT")

    def test_parallel_hatch_is_supported_without_a_spacing_goal_field(self):
        value = validate_goal(self.goal(conversion_preset="raster_parallel_hatch"))
        self.assertEqual(value["conversion_preset"], "raster_parallel_hatch")
        self.assertNotIn("hatch_spacing_mm", value)

    def test_real_is_rejected_while_workcell_is_test_only(self):
        with self.assertRaises(PipelineError) as caught:
            validate_goal(self.goal(source_mode="REAL"))
        self.assertEqual(caught.exception.code, "NOT_READY")

    def test_profile_mismatch_is_rejected(self):
        profile = matching_test_profile()
        profile["surface"]["radius_mm"] = 34.0
        with self.assertRaises(PipelineError) as caught:
            validate_profile(profile)
        self.assertEqual(caught.exception.code, "PROFILE_MISMATCH")

    def test_hash_tamper_is_rejected(self):
        self.asset.path.write_bytes(self.asset.path.read_bytes() + b"tamper")
        with self.assertRaises(ArtifactError) as caught:
            self.store.read(self.asset_id, self.asset.sha256, ("image",))
        self.assertEqual(caught.exception.code, "HASH_MISMATCH")


class TestEmptyPathValidation(unittest.TestCase):
    def test_validator_rejects_empty_segments(self):
        report = validate_path.validate({
            "schema_version": 2,
            "frame_id": wc.FRAME_ID,
            "tool_id": wc.TOOL_ID,
            "position_unit": "m",
            "orientation": "quaternion_xyzw",
            "segments": [],
        })
        self.assertFalse(report["passed"])
        self.assertTrue(any(error.startswith("EMPTY_PATH") for error in report["errors"]))

    def test_validator_rejects_non_cut_only_path(self):
        q = wc.tool_orientation(0.0)
        waypoints = [wc.to_pose7(wc.offset_point(0.0, 0.1, 0.01), q),
                     wc.to_pose7(wc.offset_point(1.0, 0.1, 0.01), q)]
        report = validate_path.validate({
            "schema_version": 2,
            "frame_id": wc.FRAME_ID,
            "tool_id": wc.TOOL_ID,
            "position_unit": "m",
            "orientation": "quaternion_xyzw",
            "segments": [{"segment_id": "seg-1", "stroke_id": None,
                          "kind": "TRAVEL", "motion_profile_id": "candle_travel",
                          "waypoints": waypoints}],
        })
        self.assertFalse(report["passed"])
        self.assertTrue(any(error.startswith("EMPTY_PATH") for error in report["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
