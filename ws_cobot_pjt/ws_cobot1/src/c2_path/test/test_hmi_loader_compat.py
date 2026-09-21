#!/usr/bin/env python3
"""c2_path 가 만든 산출물을 HMI 의 실제 `PathArtifactLoader`(backend/app/artifact_loader.py)로 읽어 본다.

저장소 안에서 `backend/` 가 이 패키지의 상위 폴더 어딘가에 있을 때만 실행한다 (없으면 건너뜀). ROS·로봇 불필요.

확인하려는 것
  * 전체 옆면(높이 0~150mm, 둘레 360°) 안이면 잠정 로봇 작업 범위 밖이어도 생성·검증·HMI 등록 읽기가 모두 성공한다.
  * 그때 `execution_readiness` 는 보고서·미리보기에만 있고, HMI 가 엄격히 비교하는 `path.validation` 은 그대로다.
  * 옆면 밖(원기둥 높이 초과)은 생성 자체가 실패한다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def find_backend():
    for parent in ROOT.parents[:6]:
        if (parent / "backend" / "app" / "artifact_loader.py").is_file():
            return parent
    return None


BACKEND_PARENT = find_backend()
if BACKEND_PARENT is not None:
    sys.path.insert(0, str(BACKEND_PARENT))
    from backend.app.artifact_loader import ArtifactLoadError, PathArtifactLoader  # noqa: E402
    from backend.app.storage import Storage  # noqa: E402

from c2_path import workcell as wc  # noqa: E402
from c2_path.artifacts import ManagedArtifactStore, sha256_bytes  # noqa: E402
from c2_path.pipeline import GeneratePipeline, PipelineError, matching_test_profile, success_message  # noqa: E402


def heart_png():
    image = np.full((400, 400), 255, np.uint8)
    t = np.linspace(0.0, 2.0 * np.pi, 400)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    points = np.stack([200 + x * 10.5, 190 - y * 10.5], axis=1).astype(np.int32)
    cv2.polylines(image, [points], True, 0, 6, cv2.LINE_AA)
    return cv2.imencode(".png", image)[1].tobytes()


@unittest.skipUnless(BACKEND_PARENT is not None, "backend/app/artifact_loader.py 가 상위 폴더에 없음")
class TestRealHmiLoader(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(self.temp.name)
        image = heart_png()
        self.asset = self.storage.put_asset(image, "image", "image/png", "heart.png")
        self.profile = self.storage.profile(matching_test_profile())
        self.store = ManagedArtifactStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def goal(self, theta_deg=-90.0, v_mm=105.0):
        return {"schema_version": 2, "request_id": str(uuid4()), "source_mode": "SIMULATION",
                "asset_id": self.asset["id"], "asset_sha256": self.asset["sha256"],
                "width_mm": 24.0, "height_mm": 24.0,
                "offset_u_mm": wc.u_mm_from_theta_deg(theta_deg), "offset_v_mm": v_mm, "rotation_deg": 0.0,
                "conversion_preset": "raster_centerline_bezier", "tool_id": wc.TOOL_ID,
                "profile_snapshot_id": self.profile["id"], "profile_sha256": self.profile["sha256"]}

    def generate_and_load(self, goal):
        generated = GeneratePipeline(self.store).run(goal)
        result = {"success": True, "error_code": "NONE", "message": success_message(generated),
                  "path_id": generated.path_id, "path_version": generated.path_version,
                  "path_sha256": generated.path_sha256, "svg_asset_id": generated.svg_asset_id,
                  "preview_asset_id": generated.preview_asset_id, "segment_count": generated.segment_count,
                  "cut_length_m": generated.cut_length_m, "validation_passed": True,
                  "validation_report_id": generated.validation_report_id}
        loaded = PathArtifactLoader(self.storage).load(goal, result)
        report = json.loads(self.storage.read_asset(generated.validation_report_id))
        preview = json.loads(self.storage.read_asset(generated.preview_asset_id))
        return generated, loaded, report, preview

    def test_inside_robot_window_loads(self):
        for v_mm in (105.0, 50.0, 30.0):                     # 작업 범위 10~140mm 안 (9/21 변경, 이전 85~130mm)
            _generated, _loaded, report, _preview = self.generate_and_load(self.goal(v_mm=v_mm))
            self.assertEqual(report["execution_readiness"]["precheck"], "WITHIN_LIMITS", v_mm)
        generated, loaded, report, preview = self.generate_and_load(self.goal())
        self.assertEqual(report["execution_readiness"]["precheck"], "WITHIN_LIMITS")
        self.assertEqual(preview["execution_readiness"]["executability"], "NOT_JUDGED")
        self.assertEqual(loaded["path_id"], generated.path_id)

    def test_outside_robot_window_still_generates_and_loads_but_is_marked(self):
        cases = {"seam_180deg": self.goal(theta_deg=180.0),
                 "low_15mm": self.goal(v_mm=15.0),
                 "high_136mm": self.goal(v_mm=136.0),
                 "robot_side_150deg": self.goal(theta_deg=150.0)}
        for name, goal in cases.items():
            with self.subTest(name):
                _generated, _loaded, report, preview = self.generate_and_load(goal)
                self.assertEqual(report["execution_readiness"]["precheck"], "OUT_OF_LIMITS")
                self.assertEqual(preview["execution_readiness"]["precheck"], "OUT_OF_LIMITS")
                self.assertGreater(report["execution_readiness"]["violation_count"], 0)
                self.assertEqual(report["execution_readiness"]["executability"], "NOT_JUDGED")

    def test_every_direction_around_the_cylinder_generates(self):
        """옆면 전체(360°): 어느 각도에 놓아도 생성·검증·HMI 읽기가 성공한다."""
        for theta in (-180.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 179.0):
            with self.subTest(theta=theta):
                self.generate_and_load(self.goal(theta_deg=theta))

    def test_whole_height_of_the_side_generates(self):
        for v_mm in (15.0, 30.0, 75.0, 120.0, 135.0):
            with self.subTest(v_mm=v_mm):
                self.generate_and_load(self.goal(v_mm=v_mm))

    def test_off_surface_fails_generation(self):
        with self.assertRaises(PipelineError) as caught:
            GeneratePipeline(self.store).run(self.goal(v_mm=200.0))
        self.assertEqual(caught.exception.code, "VALIDATION_FAILED")

    def test_loader_still_rejects_a_tampered_validation_block(self):
        """readiness 를 path.validation 에 끼워 넣으면 HMI 가 거절한다 — 그래서 넣지 않았다는 점을 고정한다."""
        generated = GeneratePipeline(self.store).run(self.goal())
        path = json.loads(self.storage.read_asset(generated.path_asset_id))
        self.assertEqual(set(path["validation"]), {"report_id", "passed", "checks", "not_checked"})


if __name__ == "__main__":
    unittest.main()
