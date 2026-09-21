#!/usr/bin/env python3
"""경로 생성 성공과 로봇 실행 가능 여부의 분리(execution_readiness) 시험.

원기둥 옆면 전체(360°, 높이 0~150mm)에서 생성은 성공하고, 로봇 잠정 작업 범위(높이 10~140mm, 각도 ±135°)
밖인지는 별도 사전 점검이 표시한다. 생성 성공·검증 통과·미리보기 성공은 실행 가능을 뜻하지 않는다.
"""
import copy
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from c2_path import readiness, validate_path, workcell as wc  # noqa: E402

BUNDLES = Path(__file__).resolve().parent.parent / "samples" / "bundles"


def load(name, file):
    return json.loads((BUNDLES / name / "output" / file).read_text(encoding="utf-8"))


def within_limits_path():
    return load("heart_ok", "c2-path.json")


def bundle_profile(name):
    return json.loads((BUNDLES / name / "input" / "simulation-profile.json").read_text(encoding="utf-8"))


class TestSeparation(unittest.TestCase):
    def test_full_surface_ranges_are_wider_than_robot_window(self):
        lo, hi = wc.SURFACE_HEIGHT_RANGE_M
        self.assertEqual((lo, hi), (0.0, wc.HEIGHT_TOTAL_M))
        self.assertLess(lo, wc.WORKABLE_HEIGHT_RANGE_M[0])
        self.assertGreater(hi, wc.WORKABLE_HEIGHT_RANGE_M[1])

    def test_validation_no_longer_reads_robot_limits(self):
        source = Path(validate_path.__file__).read_text(encoding="utf-8")
        self.assertNotIn("WORKABLE_HEIGHT_RANGE_M", source)
        self.assertNotIn("REACHABLE_ANGLE_DEG", source)

    def test_samples_generate_whatever_the_precheck_says(self):
        expected = {"heart_ok": readiness.WITHIN,
                    "heart_seam_out_of_limits": readiness.OUT_OF,
                    "heart_low_out_of_limits": readiness.OUT_OF,
                    "heart_request_range_out_of_limits": readiness.OUT_OF}
        for name, precheck in expected.items():
            result = load(name, "result.json")
            self.assertTrue(result["success"], name)
            self.assertTrue(result["validation_passed"], name)
            report = load(name, "c2-path-validation.json")
            self.assertTrue(report["passed"], name)
            self.assertEqual(report["execution_readiness"]["precheck"], precheck, name)
            preview = load(name, "c2-path-preview.json")
            self.assertEqual(preview["execution_readiness"]["precheck"], precheck, name)

    def test_success_never_claims_executable(self):
        for name in ("heart_ok", "heart_seam_out_of_limits", "heart_low_out_of_limits",
                     "heart_request_range_out_of_limits"):
            ready = load(name, "c2-path-validation.json")["execution_readiness"]
            self.assertEqual(ready["executability"], "NOT_JUDGED", name)
            self.assertFalse(ready["authoritative"], name)
            self.assertTrue(ready["limits"]["provisional"], name)
            for item in ("J6_RANGE", "IK_REACHABILITY", "COLLISION"):
                self.assertIn(item, ready["not_checked"], name)
            message = load(name, "result.json")["message"]
            self.assertIn("실행", message)
            self.assertNotIn("실행 가능합니다", message)

    def test_off_surface_still_fails_generation(self):
        result = load("heart_off_surface", "result.json")
        self.assertFalse(result["success"])
        self.assertFalse(result["validation_passed"])
        report = load("heart_off_surface", "c2-path-validation-failed.json")
        self.assertEqual({e["reason_code"] for e in report["errors"]}, {"HEIGHT_OUT_OF_SURFACE"})
        self.assertFalse((BUNDLES / "heart_off_surface" / "output" / "c2-path.json").exists())


class TestReadinessCheck(unittest.TestCase):
    def test_within_limits_path(self):
        ready = readiness.execution_readiness(within_limits_path())
        self.assertEqual(ready["precheck"], readiness.WITHIN)
        self.assertEqual(ready["violation_count"], 0)
        self.assertTrue(all(c["passed"] for c in ready["checks"]))

    def test_moving_a_cut_point_out_of_height_window_is_flagged(self):
        path = copy.deepcopy(within_limits_path())
        cut = next(s for s in path["segments"] if s["kind"] == "CUT")
        cut["waypoints"][0][2] = wc.AXIS_ORIGIN_Z_M + 0.145            # 140mm 초과, 옆면(150mm) 안
        ready = readiness.execution_readiness(path)
        self.assertEqual(ready["precheck"], readiness.OUT_OF)
        self.assertEqual({v["code"] for v in ready["violations"]}, {"HEIGHT_OUT_OF_RANGE"})
        self.assertEqual(ready["out_of_limit_segment_ids"], [cut["segment_id"]])
        errors = validate_path.validate(path)["errors"]                    # 점을 옮겼으니 연속성 오류는 나지만
        self.assertFalse([e for e in errors if "HEIGHT" in str(e)], errors)  # 높이 오류는 아니다 (옆면 안)

    def test_only_cut_segments_are_checked(self):
        path = copy.deepcopy(within_limits_path())
        travel = next(s for s in path["segments"] if s["kind"] != "CUT")
        travel["waypoints"][0][2] = wc.AXIS_ORIGIN_Z_M + 0.149
        self.assertEqual(readiness.execution_readiness(path)["precheck"], readiness.WITHIN)

    def test_limits_come_from_profile_surface_when_present(self):
        profile = {"surface": {"valid_v_range_mm": [10, 140], "reachable_angle_deg": [-170, 170]}}
        limits = readiness.limits_from_profile(profile)
        self.assertEqual(limits["work_height_range_m"], [0.010, 0.140])
        self.assertEqual(limits["reachable_angle_deg"], [-170.0, 170.0])
        self.assertEqual(readiness.limits_from_profile({}), readiness.default_limits())

    def test_violation_list_is_capped(self):
        path = copy.deepcopy(within_limits_path())
        cut = next(s for s in path["segments"] if s["kind"] == "CUT")
        many = []
        for k in range(readiness.MAX_LISTED_VIOLATIONS + 20):
            seg = copy.deepcopy(cut)
            seg["segment_id"] = f"x{k}"
            seg["waypoints"][0][2] = wc.AXIS_ORIGIN_Z_M + 0.145
            many.append(seg)
        path["segments"] = many
        ready = readiness.execution_readiness(path)
        self.assertEqual(ready["violation_count"], len(many))
        self.assertEqual(len(ready["violations"]), readiness.MAX_LISTED_VIOLATIONS)
        self.assertTrue(ready["violations_truncated"])


class TestSingleWorkRange(unittest.TestCase):
    """작업 가능 범위 기준이 pipeline.py 안에서 두 개로 갈라지지 않는지 고정한다.

    한 곳은 `validate_profile` 의 스냅샷↔상수 대조, 다른 한 곳은 `execution_readiness` 의 점검 범위다.
    둘 다 같은 `workcell` 상수(WORKABLE_HEIGHT_RANGE_M, REACHABLE_ANGLE_DEG)에서 나와야 한다."""

    def test_snapshot_limits_equal_workcell_constants(self):
        from c2_path import pipeline
        profile = pipeline.matching_test_profile()
        pipeline.validate_profile(profile)                       # 상수와 같아야 통과한다
        limits = readiness.limits_from_profile(profile)
        self.assertEqual(limits, readiness.default_limits())
        self.assertEqual(limits["work_height_range_m"], list(wc.WORKABLE_HEIGHT_RANGE_M))
        self.assertEqual(limits["reachable_angle_deg"], list(wc.REACHABLE_ANGLE_DEG))

    def test_profile_with_a_different_work_range_is_rejected_not_silently_used(self):
        from c2_path import pipeline
        for key, value in (("valid_v_range_mm", [85.0, 130.0]), ("reachable_angle_deg", [-170.0, 170.0])):
            profile = pipeline.matching_test_profile()
            profile["surface"][key] = value
            with self.assertRaises(pipeline.PipelineError) as caught:
                pipeline.validate_profile(profile)
            self.assertEqual(caught.exception.code, "PROFILE_MISMATCH", key)

    def test_report_limits_match_the_constants(self):
        for name in ("heart_ok", "heart_seam_out_of_limits", "heart_low_out_of_limits"):
            limits = load(name, "c2-path-validation.json")["execution_readiness"]["limits"]
            self.assertEqual(limits["work_height_range_m"], list(wc.WORKABLE_HEIGHT_RANGE_M), name)
            self.assertEqual(limits["reachable_angle_deg"], list(wc.REACHABLE_ANGLE_DEG), name)

    def test_all_heights_share_one_reference_the_candle_bottom(self):
        """작업 범위·옆면 범위·스냅샷 값이 모두 바닥(0) 기준이라 서로 직접 비교할 수 있다."""
        from c2_path import pipeline
        self.assertEqual(wc.WORKABLE_HEIGHT_RANGE_M, (0.010, 0.140))
        self.assertEqual(wc.SURFACE_HEIGHT_RANGE_M[0], 0.0)                      # 옆면 범위도 바닥 0 에서 시작
        profile = pipeline.matching_test_profile()["surface"]
        self.assertEqual(profile["valid_v_range_mm"], [10.0, 140.0])
        self.assertEqual(readiness.default_limits()["height_reference"], "bottom")
        # 윗면 z = 바닥 z + 높이 (작업 범위는 이 윗면 z 를 쓰지 않는다)
        self.assertAlmostEqual(wc.TOP_Z_BASE_M, wc.AXIS_ORIGIN_Z_M + wc.HEIGHT_TOTAL_M)

    def test_surface_range_is_a_different_concept_from_the_work_range(self):
        """0~150mm(옆면 전체, 생성 가능)와 10~140mm(로봇 작업 범위, 사전 점검)는 서로 다른 기준이다 — 의도된 구분."""
        self.assertNotEqual(wc.SURFACE_HEIGHT_RANGE_M, wc.WORKABLE_HEIGHT_RANGE_M)
        self.assertLessEqual(wc.SURFACE_HEIGHT_RANGE_M[0], wc.WORKABLE_HEIGHT_RANGE_M[0])
        self.assertGreaterEqual(wc.SURFACE_HEIGHT_RANGE_M[1], wc.WORKABLE_HEIGHT_RANGE_M[1])


class TestHmiLoaderContractUnchanged(unittest.TestCase):
    """HMI 가져오기(artifact_loader)가 보는 path.validation 블록은 그대로다 — readiness 는 보고서·미리보기의 별도 필드."""

    def test_path_validation_block_has_only_the_original_keys(self):
        for name in ("heart_ok", "heart_seam_out_of_limits", "heart_low_out_of_limits"):
            path = load(name, "c2-path.json")
            self.assertEqual(set(path["validation"]), {"report_id", "passed", "checks", "not_checked"}, name)
            report = load(name, "c2-path-validation.json")
            self.assertEqual(path["validation"]["checks"], report["checks"], name)
            self.assertTrue(all(c["passed"] for c in report["checks"]), name)

    def test_readiness_is_not_inside_report_checks(self):
        """checks 는 모두 통과해야 하는 기하 검사다. 로봇 범위 항목이 섞이면 HMI 가 등록을 거절하게 된다."""
        report = load("heart_seam_out_of_limits", "c2-path-validation.json")
        codes = {c["code"] for c in report["checks"]}
        self.assertNotIn("ANGLE_IN_REACHABLE_RANGE", codes)
        self.assertNotIn("WORK_HEIGHT_IN_RANGE", codes)


if __name__ == "__main__":
    unittest.main()


class TestBundleSamplesUseSnapshotV2(unittest.TestCase):
    """파일 묶음 샘플의 입력 스냅샷은 /2 이고, 사전 점검 범위는 그 스냅샷 값이다."""

    def test_every_bundle_input_is_v2_with_new_fields(self):
        for name in ("heart_ok", "heart_seam_out_of_limits", "heart_low_out_of_limits",
                     "heart_request_range_out_of_limits", "heart_custom_cylinder", "heart_off_surface"):
            profile = bundle_profile(name)
            self.assertEqual(profile["contract"], "c2-path-test-profile/2", name)
            self.assertEqual(profile["surface"]["height_reference"], "bottom", name)
            self.assertEqual(profile["surface"]["v_direction"], "up", name)
            self.assertEqual(profile["calibration_status"], "SIMULATION_ONLY", name)

    def test_request_range_sample_uses_snapshot_range_not_constants(self):
        profile = bundle_profile("heart_request_range_out_of_limits")
        self.assertEqual(profile["surface"]["valid_v_range_mm"], [110.0, 140.0])
        self.assertNotEqual(profile["surface"]["valid_v_range_mm"], [v * 1000.0 for v in wc.WORKABLE_HEIGHT_RANGE_M])
        ready = load("heart_request_range_out_of_limits", "c2-path-validation.json")["execution_readiness"]
        self.assertEqual(ready["limits"]["work_height_range_m"], [0.110, 0.140])
        self.assertEqual(ready["limits"]["height_reference"], "bottom")
        self.assertEqual(ready["precheck"], readiness.OUT_OF)
        # 같은 하트가 기본 범위(10~140)에서는 안이다: 결과 차이는 범위 값에서만 온다.
        self.assertEqual(load("heart_ok", "c2-path-validation.json")["execution_readiness"]["precheck"], readiness.WITHIN)

    def test_custom_cylinder_sample_is_computed_from_the_snapshot_geometry(self):
        import math
        profile = bundle_profile("heart_custom_cylinder")
        surface = profile["surface"]
        self.assertNotEqual(surface["radius_mm"], wc.RADIUS_M * 1000.0)
        self.assertNotEqual(surface["height_mm"], wc.HEIGHT_TOTAL_M * 1000.0)
        ox, oy, oz = surface["axis_origin_m"]
        path = json.loads((BUNDLES / "heart_custom_cylinder" / "output" / "c2-path.json").read_text(encoding="utf-8"))
        for segment in path["segments"]:
            if segment["kind"] != "CUT":
                continue
            for w in segment["waypoints"]:
                self.assertAlmostEqual(math.hypot(w[0] - ox, w[1] - oy) * 1000.0, surface["radius_mm"], delta=0.2)
                self.assertTrue(0.0 <= (w[2] - oz) * 1000.0 <= surface["height_mm"])
        # 경로·보고서·미리보기가 이 스냅샷의 ID·해시를 가리킨다.
        request = json.loads((BUNDLES / "heart_custom_cylinder" / "output" / "request.json").read_text(encoding="utf-8"))
        report = load("heart_custom_cylinder", "c2-path-validation.json")
        self.assertEqual(path["config"]["profile_snapshot_id"], request["profile_snapshot_id"])
        self.assertEqual(path["config"]["profile_sha256"], request["profile_sha256"])
        self.assertEqual(report["profile_snapshot_id"], request["profile_snapshot_id"])
        self.assertEqual(report["surface_used"]["radius_mm"], surface["radius_mm"])
        self.assertEqual(report["execution_readiness"]["precheck"], readiness.WITHIN)
