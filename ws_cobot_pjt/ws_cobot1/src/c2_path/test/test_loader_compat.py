#!/usr/bin/env python3
"""c2_path 산출물이 공정 쪽 함수(engraving.validate_path, joint_check.check_path_joints)의
입력 구조에 맞는지 확인한다. c2_process 가 옆에 있을 때만 실행한다 (ROS·실제 로봇 불필요, 모의 어댑터만 사용).

이 시험은 "구조가 맞는가"만 본다. 관절 한계·실기 성공은 판단하지 않는다 (모의 IK).
"""
import json
import math
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESS = ROOT.parent / "c2_process"
sys.path.insert(0, str(ROOT))
if PROCESS.is_dir():
    sys.path.insert(0, str(PROCESS))

from c2_path import workcell as wc  # noqa: E402

SAMPLE = ROOT / "samples" / "bundles" / "heart_ok" / "output" / "c2-path.json"
HAVE = PROCESS.is_dir() and SAMPLE.is_file()

if HAVE:
    from c2_process import engraving, joint_check  # noqa: E402
    from c2_process.robot_adapter import MockRobotAdapter  # noqa: E402


@unittest.skipUnless(HAVE, "c2_process 또는 samples/bundles 가 없음")
class TestPathMatchesProcessInputs(unittest.TestCase):
    def setUp(self):
        self.path = json.loads(SAMPLE.read_text(encoding="utf-8"))
        self.motion_profiles = {pid: {"vel_mm_s": 10.0, "acc_mm_s2": 50.0, "completion_timeout_s": 60.0}
                                for pid in wc.MOTION_PROFILE.values()}

    def context(self, mode, **tool):
        profile = {"tool_id": wc.TOOL_ID, "contact_mode": mode, "tool_axis": "-y", "clearance_m": 0.010,
                   "touch_force_n": 0.8, "touch_speed_mm_s": 1.5, "depth_mm": 0.5}
        profile.update(tool)
        return engraving.ExecutionContext("run-1", "SIMULATION", threading.Event(),
                                          self.motion_profiles, profile)

    def test_engraving_accepts_path_in_both_contact_modes(self):
        for mode in engraving.CONTACT_MODES:
            self.assertIsNone(engraving.validate_path(self.path, self.context(mode)), mode)

    def test_process_must_provide_the_four_motion_profiles_c2_path_emits(self):
        used = {s["motion_profile_id"] for s in self.path["segments"]}
        self.assertLessEqual(used, set(wc.MOTION_PROFILE.values()))
        without = dict(self.motion_profiles)
        del without["candle_cut"]
        context = engraving.ExecutionContext("run-1", "SIMULATION", threading.Event(), without,
                                             self.context("force_touch").tool_profile)
        result = engraving.validate_path(self.path, context)
        self.assertEqual(result.error_code, "PROFILE_MISMATCH")

    def test_tool_id_and_source_mode_must_agree(self):
        result = engraving.validate_path(self.path, self.context("force_touch", tool_id="other_tool"))
        self.assertEqual(result.error_code, "PROFILE_MISMATCH")
        real = engraving.ExecutionContext("run-1", "REAL", threading.Event(), self.motion_profiles,
                                          self.context("force_touch").tool_profile)
        self.assertEqual(engraving.validate_path(self.path, real).error_code, "PROFILE_MISMATCH")

    def test_cut_segments_fit_the_controller_spline_limit(self):
        for segment in self.path["segments"]:
            if segment["kind"] == "CUT":
                self.assertGreaterEqual(len(segment["waypoints"]), 2)
                self.assertLessEqual(len(segment["waypoints"]), engraving.MAX_SPLINE_POINTS)

    def test_c2_path_puts_cut_points_on_the_surface_and_leaves_depth_to_the_process(self):
        # 깊이는 실행 쪽(engraving.py: fixed_depth 의 depth_m / force_touch 의 접촉 보정)에서만 적용한다.
        # c2_path 의 CUT 은 반지름 R 원통 표면 위의 점이어야 한다 (깊이를 미리 넣으면 이중 적용된다).
        ox, oy = wc.AXIS_ORIGIN_XY_M
        for segment in self.path["segments"]:
            if segment["kind"] != "CUT":
                continue
            for x, y, *_ in segment["waypoints"]:
                self.assertAlmostEqual(math.hypot(x - ox, y - oy), wc.RADIUS_M, delta=1e-5)

    def test_joint_check_runs_over_the_path_with_mock_adapter(self):
        ref = [0.0, 0.0, math.radians(90), 0.0, math.radians(90), 0.0]
        result = joint_check.check_path_joints(self.path, MockRobotAdapter(), None, ref)
        self.assertIn(result.outcome, ("SUCCEEDED", "FAILED"))
        self.assertNotEqual(result.error_code, "NOT_READY", result.message)
        self.assertGreater(result.observed_state["checked_waypoints"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
