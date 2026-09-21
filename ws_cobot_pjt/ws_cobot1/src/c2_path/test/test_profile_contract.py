#!/usr/bin/env python3
"""스냅샷 contract `/1`·`/2` 구분 시험.

  /1 : 지금처럼 c2_path 상수와 정확히 같을 때만 받는다 (valid_v_range_mm=[10,140], 바닥 기준).
  /2 : height_reference="bottom", v_direction="up", calibration_status="SIMULATION_ONLY" 가 필수이고
       작업 범위·도달각·원통 치수(반지름·높이·축 원점)는 요청별 값을 받는다. 축 방향·u 원점·이음매는 상수와 같아야 한다.
"""
import copy
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from c2_path import readiness, workcell as wc  # noqa: E402
from c2_path.artifacts import ArtifactWrite, json_bytes, new_id  # noqa: E402
from c2_path.pipeline import (  # noqa: E402
    PROFILE_CONTRACT_V1,
    PROFILE_CONTRACT_V2,
    GeneratePipeline,
    PipelineError,
    matching_test_profile,
    matching_test_profile_v2,
    profile_surface,
    validate_profile,
)
from c2_path.worker import run_generation  # noqa: E402
from test_generate_pipeline import initialize_store, line_png  # noqa: E402


def rejected(profile):
    with_error = None
    try:
        validate_profile(profile)
    except PipelineError as exc:
        with_error = exc
    return with_error


class TestContractV1(unittest.TestCase):
    def test_v1_range_is_bottom_based_10_to_140(self):
        profile = matching_test_profile()
        self.assertEqual(profile["contract"], PROFILE_CONTRACT_V1)
        self.assertEqual(profile["surface"]["valid_v_range_mm"], [10.0, 140.0])
        validate_profile(profile)

    def test_v1_without_contract_field_still_accepted(self):
        profile = matching_test_profile()
        del profile["contract"]
        validate_profile(profile)

    def test_v1_requires_exact_constants(self):
        for value in ([85.0, 130.0], [20.0, 130.0], [10.0, 130.0], [11.0, 140.0]):
            profile = matching_test_profile()
            profile["surface"]["valid_v_range_mm"] = value
            error = rejected(profile)
            self.assertIsNotNone(error, value)
            self.assertEqual(error.code, "PROFILE_MISMATCH")

    def test_v1_does_not_need_new_fields(self):
        profile = matching_test_profile()
        self.assertNotIn("height_reference", profile["surface"])
        self.assertNotIn("v_direction", profile["surface"])
        validate_profile(profile)

    def test_unknown_contract_is_rejected(self):
        for contract in ("c2-path-test-profile/3", "c2-path-test-profile", "other/1", 2):
            profile = matching_test_profile()
            profile["contract"] = contract
            error = rejected(profile)
            self.assertIsNotNone(error, contract)
            self.assertEqual(error.code, "PROFILE_MISMATCH")


class TestContractV2(unittest.TestCase):
    def test_default_v2_is_accepted(self):
        profile = matching_test_profile_v2()
        self.assertEqual(profile["contract"], PROFILE_CONTRACT_V2)
        self.assertEqual(profile["surface"]["height_reference"], "bottom")
        self.assertEqual(profile["surface"]["v_direction"], "up")
        validate_profile(profile)

    def test_v2_accepts_request_specific_ranges(self):
        for v_range, angle in (([20.0, 130.0], None), ([10.0, 140.0], [-120.0, 120.0]),
                               ([0.0, 150.0], [-179.0, 179.0]), ([85.0, 130.0], None)):
            validate_profile(matching_test_profile_v2(valid_v_range_mm=v_range, reachable_angle_deg=angle))

    def test_v2_accepts_optional_measurement_fields(self):
        for measured_at in ("2026-09-21T10:30:00+09:00", "2026-09-21T01:30:00Z"):
            validate_profile(matching_test_profile_v2(measurement_id="m-0001", measured_at=measured_at))

    def test_v2_requires_new_surface_fields(self):
        for key, bad in (("height_reference", None), ("height_reference", "top"), ("height_reference", ""),
                         ("v_direction", None), ("v_direction", "down"), ("v_direction", True)):
            profile = matching_test_profile_v2()
            if bad is None:
                del profile["surface"][key]
            else:
                profile["surface"][key] = bad
            error = rejected(profile)
            self.assertIsNotNone(error, (key, bad))
            self.assertEqual(error.code, "PROFILE_MISMATCH")
            self.assertIn(key, error.message)

    def test_v2_calibration_status_must_be_simulation_only_for_now(self):
        for value in (None, "MEASURED", "CALIBRATED", "simulation_only", 1):
            profile = matching_test_profile_v2()
            if value is None:
                del profile["calibration_status"]
            else:
                profile["calibration_status"] = value
            error = rejected(profile)
            self.assertIsNotNone(error, value)
            self.assertIn("calibration_status", error.message)

    def test_v2_rejects_bad_ranges(self):
        cases = ([140.0, 10.0], [10.0, 10.0], [-1.0, 140.0], [10.0, 150.5], [10.0], [10.0, float("nan")],
                 [True, 140.0], "10-140", None)
        for value in cases:
            profile = matching_test_profile_v2()
            profile["surface"]["valid_v_range_mm"] = value
            error = rejected(profile)
            self.assertIsNotNone(error, value)
            self.assertEqual(error.code, "PROFILE_MISMATCH")

    def test_v2_rejects_bad_reachable_angle(self):
        # 이음매(180°)가 도달각 안에 들어가면 안 된다. 순서·개수도 본다.
        for value in ([-90.0, 190.0], [135.0, -135.0], [-135.0], [-181.0, 135.0], [-200.0, 135.0]):
            error = rejected(matching_test_profile_v2(reachable_angle_deg=value))
            self.assertIsNotNone(error, value)

    def test_v2_rejects_bad_optional_fields(self):
        for kwargs in ({"measurement_id": ""}, {"measurement_id": 5}, {"measurement_id": "x" * 200},
                       {"measured_at": "yesterday"}, {"measured_at": "2026-09-21T10:30:00"},
                       {"measured_at": 12345}):
            error = rejected(matching_test_profile_v2(**kwargs))
            self.assertIsNotNone(error, kwargs)

    def test_v2_accepts_request_specific_cylinder(self):
        profile = matching_test_profile_v2(radius_mm=30.0, height_mm=120.0, axis_origin_m=[0.45, 0.01, 0.09],
                                           valid_v_range_mm=[10.0, 110.0])
        validate_profile(profile)
        surface = profile_surface(profile)
        self.assertAlmostEqual(surface.radius_m, 0.030)
        self.assertAlmostEqual(surface.height_m, 0.120)
        self.assertEqual(surface.axis_origin_m, (0.45, 0.01, 0.09))

    def test_v2_rejects_bad_cylinder_values(self):
        for key, value in (("radius_mm", 0.0), ("radius_mm", -5.0), ("radius_mm", "34"), ("height_mm", 0.0),
                           ("axis_origin_m", [0.4, 0.0]), ("axis_origin_m", [0.4, 0.0, "x"])):
            profile = matching_test_profile_v2()
            profile["surface"][key] = value
            error = rejected(profile)
            self.assertIsNotNone(error, (key, value))
            self.assertEqual(error.code, "PROFILE_MISMATCH")

    def test_v2_range_must_fit_inside_requested_height(self):
        # 높이가 120mm 인데 작업 범위 상한이 140mm 이면 옆면 밖이다.
        error = rejected(matching_test_profile_v2(height_mm=120.0, valid_v_range_mm=[10.0, 140.0]))
        self.assertIsNotNone(error)

    def test_v2_still_pins_axis_direction_u_origin_and_seam(self):
        for key, value in (("kind", "cone"), ("axis_direction", [0.0, 1.0, 0.0]), ("seam_angle_deg", 90.0),
                           ("u_origin_angle_deg", 10.0)):
            profile = matching_test_profile_v2()
            profile["surface"][key] = value
            error = rejected(profile)
            self.assertIsNotNone(error, key)
            self.assertEqual(error.code, "PROFILE_MISMATCH")

    def test_v1_still_pins_cylinder_dimensions(self):
        for key, value in (("radius_mm", 40.0), ("height_mm", 200.0), ("axis_origin_m", [0.5, 0.0, 0.08])):
            profile = matching_test_profile()
            profile["surface"][key] = value
            self.assertIsNotNone(rejected(profile), key)

    def test_v2_keeps_identity_checks(self):
        for key, value in (("tool_id", "other"), ("frame_id", "world"), ("source_mode", "REAL"),
                           ("gripper_open_allowed", True), ("schema_version", 3)):
            profile = matching_test_profile_v2()
            profile[key] = value
            self.assertIsNotNone(rejected(profile), key)

    def test_v2_error_messages_are_deduplicated(self):
        profile = matching_test_profile_v2()
        profile["surface"]["seam_angle_deg"] = 90.0
        profile["surface"]["kind"] = "cone"
        profile["surface"]["valid_v_range_mm"] = [140.0, 10.0]
        error = rejected(profile)
        parts = error.message.split(": ", 1)[1].split("; ")
        self.assertEqual(len(parts), len(set(parts)))

    def test_v2_input_is_not_mutated(self):
        profile = matching_test_profile_v2(valid_v_range_mm=[20.0, 130.0])
        before = copy.deepcopy(profile)
        validate_profile(profile)
        self.assertEqual(profile, before)


class TestReadinessUsesSnapshotRange(unittest.TestCase):
    def test_v1_limits_equal_constants(self):
        limits = readiness.limits_from_profile(matching_test_profile())
        self.assertEqual(limits["work_height_range_m"], [0.010, 0.140])
        self.assertEqual(limits["height_reference"], "bottom")
        self.assertEqual(limits["source"], readiness.DEFAULT_LIMITS_SOURCE)

    def test_v2_limits_come_from_snapshot(self):
        limits = readiness.limits_from_profile(
            matching_test_profile_v2(valid_v_range_mm=[20.0, 130.0], reachable_angle_deg=[-120.0, 120.0]))
        self.assertEqual(limits["work_height_range_m"], [0.020, 0.130])
        self.assertEqual(limits["reachable_angle_deg"], [-120.0, 120.0])
        self.assertEqual(limits["source"], readiness.SNAPSHOT_LIMITS_SOURCE)

    def test_angle_range_is_not_presented_as_j5_judgement(self):
        self.assertIn("J5_JOINT_LIMIT", readiness.NOT_CHECKED)
        ready = readiness.execution_readiness({"segments": []}, readiness.default_limits())
        self.assertIn("J5", ready["limits"]["angle_meaning"])
        self.assertIn("아니다", ready["limits"]["angle_meaning"])


class ProfileRegistered(unittest.TestCase):
    """스냅샷을 관리 저장소에 등록하고 실제 파이프라인·worker 프로세스로 돌린다."""

    profile_factory = staticmethod(matching_test_profile_v2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = initialize_store(self.temp.name)
        self.asset_id, self.profile_id = new_id(), new_id()
        self.store.put_bundle([
            ArtifactWrite(line_png(), "image", "image/png", "line.png", {}, self.asset_id),
            ArtifactWrite(json_bytes(self.profile_factory()), "profile", "application/json",
                          "profile.json", {}, self.profile_id),
        ])
        self.asset_sha, self.profile_sha = self._sha(self.asset_id), self._sha(self.profile_id)

    def tearDown(self):
        self.temp.cleanup()

    def _sha(self, asset_id):
        connection = sqlite3.connect(Path(self.temp.name) / "monitor.sqlite3")
        try:
            return connection.execute("SELECT sha256 FROM assets WHERE id=?", (asset_id,)).fetchone()[0]
        finally:
            connection.close()

    def goal(self, **changes):
        value = {
            "schema_version": 2, "request_id": str(uuid4()), "source_mode": "SIMULATION",
            "asset_id": self.asset_id, "asset_sha256": self.asset_sha, "width_mm": 24.0, "height_mm": 24.0,
            "offset_u_mm": 0.0, "offset_v_mm": 105.0, "rotation_deg": 0.0,
            "conversion_preset": "raster_centerline_bezier", "tool_id": wc.TOOL_ID,
            "profile_snapshot_id": self.profile_id, "profile_sha256": self.profile_sha,
        }
        value.update(changes)
        return value

    def readiness_of(self, result):
        report = self.store.read(result.validation_report_id, self._sha(result.validation_report_id), ("validation",))
        return json.loads(report.path.read_text(encoding="utf-8"))["execution_readiness"]


class TestPipelineWithV2Snapshot(ProfileRegistered):
    def test_default_v2_is_within_limits(self):
        result = GeneratePipeline(self.store).run(self.goal())
        ready = self.readiness_of(result)
        self.assertEqual(ready["precheck"], readiness.WITHIN)
        self.assertEqual(ready["limits"]["source"], readiness.SNAPSHOT_LIMITS_SOURCE)
        self.assertEqual(ready["executability"], "NOT_JUDGED")

    def test_request_range_changes_precheck_but_not_generation(self):
        """같은 도안·같은 위치라도 스냅샷의 작업 범위가 다르면 사전 점검만 달라지고 경로 생성은 성공한다."""
        results = {}
        for name, v_range in (("wide", [10.0, 140.0]), ("narrow", [110.0, 140.0])):
            store_profile = matching_test_profile_v2(valid_v_range_mm=v_range)
            new_profile = new_id()
            self.store.put_bundle([ArtifactWrite(json_bytes(store_profile), "profile", "application/json",
                                                 f"{name}.json", {}, new_profile)])
            goal = self.goal(profile_snapshot_id=new_profile, profile_sha256=self._sha(new_profile))
            result = GeneratePipeline(self.store).run(goal)
            self.assertGreater(result.segment_count, 0, name)
            results[name] = self.readiness_of(result)
        self.assertEqual(results["wide"]["precheck"], readiness.WITHIN)
        self.assertEqual(results["narrow"]["precheck"], readiness.OUT_OF)
        self.assertEqual(results["narrow"]["limits"]["work_height_range_m"], [0.110, 0.140])
        self.assertEqual(results["narrow"]["limits"]["height_reference"], "bottom")

    def test_missing_new_field_fails_generation(self):
        bad = matching_test_profile_v2()
        del bad["surface"]["height_reference"]
        bad_id = new_id()
        self.store.put_bundle([ArtifactWrite(json_bytes(bad), "profile", "application/json", "bad.json", {}, bad_id)])
        with self.assertRaises(PipelineError) as caught:
            GeneratePipeline(self.store).run(self.goal(profile_snapshot_id=bad_id, profile_sha256=self._sha(bad_id)))
        self.assertEqual(caught.exception.code, "PROFILE_MISMATCH")


class TestPipelineWithRequestSpecificCylinder(ProfileRegistered):
    """`/2` 스냅샷의 반지름·높이·축 원점으로 경로가 계산되고, 다른 요청에 새지 않는다."""

    def _register(self, profile, name):
        profile_id = new_id()
        self.store.put_bundle([ArtifactWrite(json_bytes(profile), "profile", "application/json",
                                             f"{name}.json", {}, profile_id)])
        return profile_id, self._sha(profile_id)

    def _run(self, profile, name, **goal_changes):
        profile_id, profile_sha = self._register(profile, name)
        result = GeneratePipeline(self.store).run(
            self.goal(profile_snapshot_id=profile_id, profile_sha256=profile_sha, **goal_changes))
        path = json.loads(self.store.read(result.path_asset_id, self._sha(result.path_asset_id),
                                          ("path",)).path.read_text(encoding="utf-8"))
        return result, path, profile_id, profile_sha

    def test_path_lies_on_the_snapshot_cylinder_and_survives_validation(self):
        import math
        profile = matching_test_profile_v2(radius_mm=30.0, height_mm=120.0, axis_origin_m=[0.45, 0.01, 0.09],
                                           valid_v_range_mm=[10.0, 110.0])
        result, path, _pid, _psha = self._run(profile, "custom", offset_v_mm=60.0)
        self.assertGreater(result.segment_count, 0)
        cuts = [s for s in path["segments"] if s["kind"] == "CUT"]
        for segment in cuts:
            for w in segment["waypoints"]:
                self.assertAlmostEqual(math.hypot(w[0] - 0.45, w[1] - 0.01), 0.030, delta=2e-4)
                self.assertGreaterEqual(w[2] - 0.09, -1e-6)
                self.assertLessEqual(w[2] - 0.09, 0.120 + 1e-6)
        self.assertTrue(path["validation"]["passed"])

    def test_geometry_does_not_leak_between_requests(self):
        custom = matching_test_profile_v2(radius_mm=30.0, height_mm=120.0, axis_origin_m=[0.45, 0.01, 0.09],
                                          valid_v_range_mm=[10.0, 110.0])
        self._run(custom, "custom", offset_v_mm=60.0)
        self.assertIs(wc.current_surface(), wc.DEFAULT_SURFACE)
        _r1, path_default, _a, _b = self._run(matching_test_profile_v2(), "default")
        # 기본 형상 스냅샷은 /1 과 같은 좌표를 만든다 (같은 도안·같은 위치).
        _r2, path_v1, _c, _d = self._run(matching_test_profile(), "v1")
        self.assertEqual(path_default["segments"], path_v1["segments"])

    def test_different_cylinder_gives_different_coordinates(self):
        _r1, path_a, _pa, _sa = self._run(matching_test_profile_v2(), "a")
        _r2, path_b, _pb, _sb = self._run(matching_test_profile_v2(radius_mm=30.0, height_mm=150.0), "b")
        self.assertNotEqual(path_a["segments"][0]["waypoints"], path_b["segments"][0]["waypoints"])

    def test_path_links_the_snapshot_id_and_hash_that_was_used(self):
        profile = matching_test_profile_v2(radius_mm=30.0, height_mm=120.0, axis_origin_m=[0.45, 0.01, 0.09],
                                           valid_v_range_mm=[10.0, 110.0], measurement_id="m-0921-a")
        result, path, profile_id, profile_sha = self._run(profile, "linked", offset_v_mm=60.0)
        self.assertEqual(path["config"]["profile_snapshot_id"], profile_id)
        self.assertEqual(path["config"]["profile_sha256"], profile_sha)
        report = json.loads(self.store.read(result.validation_report_id, self._sha(result.validation_report_id),
                                            ("validation",)).path.read_text(encoding="utf-8"))
        self.assertEqual(report["profile_snapshot_id"], profile_id)
        self.assertEqual(report["profile_sha256"], profile_sha)
        preview = json.loads(self.store.read(result.preview_asset_id, self._sha(result.preview_asset_id),
                                             ("preview",)).path.read_text(encoding="utf-8"))
        self.assertEqual(preview["profile_snapshot_id"], profile_id)
        self.assertEqual(preview["profile_sha256"], profile_sha)

    def test_snapshot_surface_used_for_the_path_is_recorded_in_the_report(self):
        profile = matching_test_profile_v2(radius_mm=30.0, height_mm=120.0, axis_origin_m=[0.45, 0.01, 0.09],
                                           valid_v_range_mm=[10.0, 110.0], measurement_id="m-0921-a")
        result, _path, _pid, _psha = self._run(profile, "recorded", offset_v_mm=60.0)
        report = json.loads(self.store.read(result.validation_report_id, self._sha(result.validation_report_id),
                                            ("validation",)).path.read_text(encoding="utf-8"))
        used = report["surface_used"]
        self.assertEqual(used["radius_mm"], 30.0)
        self.assertEqual(used["height_mm"], 120.0)
        self.assertEqual(used["axis_origin_m"], [0.45, 0.01, 0.09])
        self.assertEqual(used["height_reference"], "bottom")
        self.assertEqual(report["profile_contract"], PROFILE_CONTRACT_V2)
        self.assertEqual(report["measurement_id"], "m-0921-a")


class TestPipelineWithV1Snapshot(ProfileRegistered):
    profile_factory = staticmethod(matching_test_profile)

    def test_v1_still_generates(self):
        result = GeneratePipeline(self.store).run(self.goal())
        ready = self.readiness_of(result)
        self.assertEqual(ready["precheck"], readiness.WITHIN)
        self.assertEqual(ready["limits"]["source"], readiness.DEFAULT_LIMITS_SOURCE)


class TestWorkerProcessWithRealPipeline(ProfileRegistered):
    """main 의 취소 가능한 계산 프로세스(worker.py)가 실제 파이프라인 결과를 파이프로 받아 저장하는지."""

    def test_result_and_bundles_cross_the_process_boundary(self):
        feedback = []
        result = run_generation(self.store, self.goal(), timeout_s=120,
                                feedback=lambda stage, progress: feedback.append((stage, progress)))
        self.assertGreater(result.segment_count, 0)
        self.assertIn(result.execution_precheck, (readiness.WITHIN, readiness.OUT_OF))
        self.assertTrue(result.execution_message)
        self.assertEqual(feedback[-1][0], "VALIDATING")
        self.assertEqual(self.readiness_of(result)["precheck"], result.execution_precheck)
        stages = [stage for stage, _ in feedback]
        self.assertEqual(stages, sorted(stages, key=lambda s: ("CONVERTING", "EXTRACTING_2D", "OPTIMIZING_2D",
                                                               "MAPPING_3D", "BUILDING_PATH", "VALIDATING").index(s)))


if __name__ == "__main__":
    unittest.main()
