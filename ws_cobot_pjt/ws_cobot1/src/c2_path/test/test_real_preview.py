#!/usr/bin/env python3
"""REAL 추정값 미리보기 전용 경로 생성(스냅샷 `c2-path-test-profile/3`) 시험.

완료 조건(팀장님 9/21):
  1. 실측 중심·반지름·높이·바닥·작업 범위로 계산하고 고정값으로 대체하지 않는다.
  2. REAL 입력을 SIMULATION 으로 바꾸지 않는다(반대도).
  3. 미리보기와 최종 검사에 전달하는 경로의 ID·버전·해시가 같다.
  4. 범위 초과·설정 불일치·측정 출처 누락을 거절한다.
  + 기존 SIMULATION 과 `/1`·`/2` 동작은 그대로다.
  + `executability=NOT_JUDGED` 유지, 경로는 test_only 라 실행 금지.

이 시험의 REAL 스냅샷은 **형식 예시**다(가짜 측정 출처). 실제 측정값이 아니다.
"""
import copy
import hashlib
import json
import math
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from c2_path import readiness, workcell as wc  # noqa: E402
from c2_path.artifacts import ArtifactWrite, json_bytes, new_id  # noqa: E402
from c2_path.pipeline import (  # noqa: E402
    PROFILE_CONTRACT_V3,
    GeneratePipeline,
    PipelineError,
    matching_test_profile,
    matching_test_profile_v2,
    matching_test_profile_v3,
    validate_goal,
    validate_profile,
)
from c2_path.worker import run_generation  # noqa: E402
from test_profile_contract import ProfileRegistered  # noqa: E402

PROCESS_FIXTURE = (Path(__file__).resolve().parents[2] / "c2_process" / "test" / "fixtures"
                   / "prepare_workpiece_action_samples" / "success.json")

CUSTOM = dict(radius_mm=30.0, height_mm=120.0, axis_origin_m=[0.45, 0.01, 0.09], valid_v_range_mm=[10.0, 110.0])


def converted_from_result(result: dict, **changes) -> dict:
    """`PREPARE_WORKPIECE_ACTION.md` 5.2절 변환: 윗면 기준(아래로 +) work_v_range_m → 바닥 기준(위로 +) valid_v_range_mm."""
    height = result["height_m"]
    v_min, v_max = result["work_v_range_m"]
    profile = matching_test_profile_v3(
        radius_mm=result["radius_m"] * 1000.0, height_mm=height * 1000.0,
        axis_origin_m=[result["axis_xy_m"][0], result["axis_xy_m"][1], result["bottom_z_m"]],
        valid_v_range_mm=[(height - v_max) * 1000.0, (height - v_min) * 1000.0])
    profile.update(changes)
    return profile


class RealPreviewBase(ProfileRegistered):
    profile_factory = staticmethod(matching_test_profile_v3)
    pipeline_kwargs = {"allow_real_preview": True}

    def goal(self, **changes):
        changes.setdefault("source_mode", "REAL")
        return super().goal(**changes)

    def _register(self, profile, name="p"):
        profile_id = new_id()
        self.store.put_bundle([ArtifactWrite(json_bytes(profile), "profile", "application/json",
                                             f"{name}.json", {}, profile_id)])
        return profile_id, self._sha(profile_id)

    def run_pipeline(self, profile, *, mode="REAL", allow=True, **goal_changes):
        profile_id, profile_sha = self._register(profile)
        goal = self.goal(profile_snapshot_id=profile_id, profile_sha256=profile_sha, source_mode=mode, **goal_changes)
        return GeneratePipeline(self.store, allow_real_preview=allow).run(goal), profile_id, profile_sha

    def read_json(self, asset_id, kind):
        artifact = self.store.read(asset_id, self._sha(asset_id), (kind,))
        return json.loads(artifact.path.read_text(encoding="utf-8")), artifact

    def outputs(self, result):
        path, path_artifact = self.read_json(result.path_asset_id, "path")
        preview, _ = self.read_json(result.preview_asset_id, "preview")
        report, _ = self.read_json(result.validation_report_id, "validation")
        return path, preview, report, path_artifact

    def assertRejected(self, code, profile, **kwargs):
        with self.assertRaises(PipelineError) as caught:
            self.run_pipeline(profile, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.message)
        return caught.exception


class TestRealPreviewAccepted(RealPreviewBase):
    def test_real_goal_with_v3_snapshot_generates_and_keeps_real_source(self):
        result, profile_id, profile_sha = self.run_pipeline(matching_test_profile_v3(), offset_v_mm=75.0)
        path, preview, report, _ = self.outputs(result)
        self.assertGreater(result.segment_count, 0)
        for document in (path, preview, report):
            self.assertEqual(document["source_mode"], "REAL")          # SIMULATION 으로 바뀌지 않는다
        self.assertIs(path["test_only"], True)                          # 실행 금지 유지
        self.assertIs(preview["test_only"], True)
        self.assertEqual(path["config"]["profile_snapshot_id"], profile_id)
        self.assertEqual(path["config"]["profile_sha256"], profile_sha)

    def test_estimate_status_and_provenance_are_preserved_everywhere(self):
        for status in ("ESTIMATED", "FORCE_CONTACT_ESTIMATE"):
            with self.subTest(status=status):
                profile = matching_test_profile_v3(measurement_status=status)
                result, _pid, _psha = self.run_pipeline(profile, offset_v_mm=75.0)
                path, preview, report, _ = self.outputs(result)
                for marks in (path["config"]["real_preview"], preview["real_preview"], report["real_preview"]):
                    self.assertEqual(marks["measurement_status"], status)
                    self.assertIs(marks["independent_accuracy_verified"], False)
                    self.assertIs(marks["preview_only"], True)
                    self.assertIs(marks["real_execution_allowed"], False)
                    for key in ("preparation_id", "measurement_id", "measurement_record_id", "measurement_record_sha256",
                                "input_profile_snapshot_id", "input_profile_sha256", "measured_at"):
                        self.assertEqual(marks[key], profile[key])

    def test_executability_stays_not_judged_and_execution_is_blocked_separately(self):
        result, _pid, _psha = self.run_pipeline(matching_test_profile_v3(), offset_v_mm=75.0)
        _path, preview, report, _ = self.outputs(result)
        for ready in (report["execution_readiness"], preview["execution_readiness"]):
            self.assertEqual(ready["executability"], "NOT_JUDGED")
            self.assertEqual(ready["precheck"], readiness.WITHIN)       # 범위 안이어도
            self.assertEqual(ready["execution_blocked"]["code"], readiness.PREVIEW_ONLY_CODE)   # 실행은 막힌다
        self.assertIn("미리보기 전용", result.execution_message)
        self.assertEqual(report["execution_readiness"]["not_checked"], list(readiness.NOT_CHECKED))

    def test_geometry_and_range_come_from_the_snapshot_not_from_constants(self):
        profile = matching_test_profile_v3(**CUSTOM)
        result, _pid, _psha = self.run_pipeline(profile, offset_v_mm=60.0)
        path, _preview, report, _ = self.outputs(result)
        for segment in (s for s in path["segments"] if s["kind"] == "CUT"):
            for w in segment["waypoints"]:
                self.assertAlmostEqual(math.hypot(w[0] - 0.45, w[1] - 0.01), 0.030, delta=2e-4)
                self.assertTrue(-1e-6 <= w[2] - 0.09 <= 0.120 + 1e-6)
        limits = report["execution_readiness"]["limits"]
        self.assertEqual(limits["work_height_range_m"], [0.010, 0.110])   # [10,140] 고정값이 아니다
        self.assertIn("/3", limits["source"])
        self.assertEqual(report["surface_used"]["radius_mm"], 30.0)
        self.assertEqual(report["surface_used"]["height_mm"], 120.0)

    def test_request_outside_snapshot_work_range_is_generated_but_flagged_not_clamped(self):
        profile = matching_test_profile_v3(**CUSTOM)          # 작업 범위 [10, 110] mm
        result, _pid, _psha = self.run_pipeline(profile, offset_v_mm=112.0, height_mm=10.0, width_mm=10.0)
        _path, preview, report, _ = self.outputs(result)
        self.assertEqual(report["execution_readiness"]["precheck"], readiness.OUT_OF)
        self.assertGreater(report["execution_readiness"]["summary"]["out_of_limit_cut_waypoint_count"], 0)
        self.assertEqual(preview["execution_readiness"]["execution_blocked"]["code"], readiness.PREVIEW_ONLY_CODE)

    def test_path_preview_and_result_share_id_version_and_hash(self):
        result, _pid, _psha = self.run_pipeline(matching_test_profile_v3(), offset_v_mm=75.0)
        path, preview, report, path_artifact = self.outputs(result)
        stored_sha = hashlib.sha256(path_artifact.path.read_bytes()).hexdigest()
        self.assertEqual(result.path_sha256, stored_sha)
        self.assertEqual(preview["path_sha256"], stored_sha)
        for document in (path, preview, report):
            self.assertEqual(document["path_id"], result.path_id)
            self.assertEqual(document["path_version"], result.path_version)
        self.assertEqual(path["validation"]["report_id"], result.validation_report_id)

    def test_measurement_result_conversion_follows_the_top_down_to_bottom_up_rule(self):
        if not PROCESS_FIXTURE.is_file():
            self.skipTest("c2_process 준비 Action 샘플이 옆에 없습니다")
        result = json.loads(PROCESS_FIXTURE.read_text(encoding="utf-8"))["result"]
        profile = converted_from_result(result)
        height = result["height_m"] * 1000.0
        v_min, v_max = (v * 1000.0 for v in result["work_v_range_m"])
        for got, want in zip(profile["surface"]["valid_v_range_mm"], [height - v_max, height - v_min]):
            self.assertAlmostEqual(got, want, places=9)
        self.assertNotEqual(profile["surface"]["valid_v_range_mm"], [10.0, 140.0])
        run, _pid, _psha = self.run_pipeline(profile, offset_v_mm=75.0)
        _path, _preview, report, _ = self.outputs(run)
        for got, want in zip(report["execution_readiness"]["limits"]["work_height_range_m"],
                             [(height - v_max) / 1000.0, (height - v_min) / 1000.0]):
            self.assertAlmostEqual(got, want, places=9)


class TestRealNeverBecomesSimulation(RealPreviewBase):
    def test_real_goal_is_rejected_when_the_node_has_real_preview_off(self):
        error = self.assertRejected("NOT_READY", matching_test_profile_v3(), allow=False)
        self.assertIn("allow_real_preview", error.message)

    def test_real_goal_with_simulation_snapshot_is_rejected(self):
        self.assertRejected("PROFILE_MISMATCH", matching_test_profile_v2())
        self.assertRejected("PROFILE_MISMATCH", matching_test_profile())

    def test_simulation_goal_with_real_snapshot_is_rejected(self):
        self.assertRejected("PROFILE_MISMATCH", matching_test_profile_v3(), mode="SIMULATION")

    def test_real_snapshot_relabeled_as_simulation_is_rejected(self):
        profile = matching_test_profile_v3()
        profile["source_mode"] = "SIMULATION"
        self.assertRejected("PROFILE_MISMATCH", profile, mode="SIMULATION")
        self.assertRejected("PROFILE_MISMATCH", profile, mode="REAL")

    def test_simulation_snapshot_relabeled_as_real_is_rejected(self):
        profile = matching_test_profile_v2()
        profile["source_mode"] = "REAL"
        self.assertRejected("PROFILE_MISMATCH", profile)

    def test_unknown_modes_are_rejected(self):
        for mode in ("real", "SIM", "", None):
            with self.subTest(mode=mode):
                with self.assertRaises(PipelineError) as caught:
                    validate_goal({**self.goal(), "source_mode": mode}, allow_real_preview=True)
                self.assertEqual(caught.exception.code, "NOT_READY")


class TestRealSnapshotRejections(RealPreviewBase):
    def mutated(self, change):
        profile = matching_test_profile_v3()
        change(profile)
        return profile

    def test_missing_or_malformed_measurement_provenance_is_rejected_not_filled_in(self):
        for key in ("preparation_id", "measurement_id", "input_profile_snapshot_id", "input_profile_sha256",
                    "measurement_record_id", "measurement_record_sha256", "measured_at"):
            with self.subTest(missing=key):
                error = self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, key=key: p.pop(key)))
                self.assertIn(key, error.message)
        bad = {"preparation_id": "not-a-uuid", "measurement_record_id": "44444444-4444-4444-8444-44444444444",
               "measurement_record_sha256": "B" * 64, "input_profile_sha256": "a" * 63,
               "measured_at": "2026-09-21T13:00:00", "measurement_id": 123}
        for key, value in bad.items():
            with self.subTest(bad=key):
                self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, key=key, value=value: p.update({key: value})))

    def test_measurement_status_must_be_a_real_estimate(self):
        for value in ("SIMULATED", "INCOMPLETE", "REFERENCE_ONLY", "ABSOLUTE_VERIFIED", "", None, 1):
            with self.subTest(status=value):
                self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, v=value: p.update(measurement_status=v)))
        self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p: p.pop("measurement_status")))

    def test_accuracy_verified_flag_cannot_be_true_or_missing(self):
        self.assertRejected("PROFILE_MISMATCH", self.mutated(
            lambda p: p["measurement_assumptions"].update(independent_accuracy_verified=True)))
        self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p: p.pop("measurement_assumptions")))
        self.assertRejected("PROFILE_MISMATCH", self.mutated(
            lambda p: p["measurement_assumptions"].pop("independent_accuracy_verified")))

    def test_calibration_status_must_be_the_preview_only_value(self):
        for value in ("SIMULATION_ONLY", "MEASURED", "CALIBRATED", None):
            with self.subTest(status=value):
                self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, v=value: p.update(calibration_status=v)))

    def test_setting_mismatch_is_rejected(self):
        for key, value in (("workcell_id", "other"), ("tools_config_version", 2), ("tool_id", "x"), ("tcp_id", "Other"),
                           ("load_id", "Other"), ("frame_id", "world"), ("gripper_open_allowed", True),
                           ("schema_version", 3)):
            with self.subTest(key=key):
                self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, k=key, v=value: p.update({k: v})))
        for key in ("workcell_id", "tools_config_id", "tcp_version", "load_id", "frame_id", "gripper_open_allowed"):
            with self.subTest(missing=key):
                self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, k=key: p.pop(k)))

    def test_geometry_and_range_violations_are_rejected(self):
        surface_changes = (
            {"valid_v_range_mm": [10.0, 200.0]},            # 높이(150)를 넘는 범위
            {"valid_v_range_mm": [140.0, 10.0]},            # 뒤집힌 범위
            {"valid_v_range_mm": [-1.0, 100.0]},
            {"valid_v_range_mm": None},
            {"radius_mm": 0.0}, {"radius_mm": -3.0}, {"radius_mm": None},
            {"height_mm": 0.0}, {"axis_origin_m": [0.4, 0.0]},
            {"height_reference": "top"}, {"v_direction": "down"},
            {"axis_direction": [0.0, 0.1, 0.995]}, {"seam_angle_deg": 90.0}, {"kind": "cone"},
        )
        for change in surface_changes:
            with self.subTest(change=change):
                self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, c=change: p["surface"].update(c)))
        for key in ("radius_mm", "height_mm", "axis_origin_m", "valid_v_range_mm", "reachable_angle_deg",
                    "height_reference", "v_direction", "u_origin_angle_deg"):
            with self.subTest(missing=key):
                self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p, k=key: p["surface"].pop(k)))

    def test_design_outside_the_side_surface_is_still_rejected(self):
        with self.assertRaises(PipelineError) as caught:
            self.run_pipeline(matching_test_profile_v3(), offset_v_mm=400.0)
        self.assertEqual(caught.exception.code, "VALIDATION_FAILED")
        self.assertTrue(caught.exception.validation_report_id)

    def test_unknown_contract_is_still_rejected(self):
        self.assertRejected("PROFILE_MISMATCH", self.mutated(lambda p: p.update(contract="c2-path-test-profile/4")))

    def test_validate_profile_checks_v3_without_a_node(self):
        validate_profile(matching_test_profile_v3())           # HMI 백엔드가 직접 호출하는 경로
        broken = matching_test_profile_v3()
        broken.pop("measurement_record_id")
        with self.assertRaises(PipelineError):
            validate_profile(broken)


class TestExistingBehaviourUnchanged(ProfileRegistered):
    """SIMULATION 과 `/1`·`/2` 는 그대로다: /3 표시가 섞이지 않고, source_mode 는 SIMULATION 이다."""

    def _outputs(self, profile):
        profile_id = new_id()
        self.store.put_bundle([ArtifactWrite(json_bytes(profile), "profile", "application/json", "p.json", {}, profile_id)])
        result = GeneratePipeline(self.store).run(self.goal(profile_snapshot_id=profile_id, profile_sha256=self._sha(profile_id)))
        read = lambda aid, kind: json.loads(self.store.read(aid, self._sha(aid), (kind,)).path.read_text(encoding="utf-8"))
        return (result, read(result.path_asset_id, "path"), read(result.preview_asset_id, "preview"),
                read(result.validation_report_id, "validation"))

    def test_v1_and_v2_outputs_have_no_real_marks(self):
        for factory in (matching_test_profile, matching_test_profile_v2):
            with self.subTest(factory=factory.__name__):
                result, path, preview, report = self._outputs(factory())
                for document in (path, preview, report):
                    self.assertEqual(document["source_mode"], "SIMULATION")
                self.assertNotIn("real_preview", path["config"])
                self.assertNotIn("real_preview", preview)
                self.assertNotIn("real_preview", report)
                self.assertNotIn("execution_blocked", report["execution_readiness"])
                self.assertNotIn("execution_blocked", preview["execution_readiness"])
                self.assertNotIn("미리보기 전용", result.execution_message)

    def test_real_goal_is_still_rejected_by_default(self):
        profile_id = new_id()
        self.store.put_bundle([ArtifactWrite(json_bytes(matching_test_profile_v3()), "profile", "application/json",
                                             "p.json", {}, profile_id)])
        goal = self.goal(profile_snapshot_id=profile_id, profile_sha256=self._sha(profile_id), source_mode="REAL")
        with self.assertRaises(PipelineError) as caught:
            GeneratePipeline(self.store).run(goal)
        self.assertEqual(caught.exception.code, "NOT_READY")

    def test_simulation_goal_with_v1_v2_snapshots_is_not_affected_by_the_flag(self):
        for allow in (False, True):
            with self.subTest(allow=allow):
                profile_id = new_id()
                self.store.put_bundle([ArtifactWrite(json_bytes(matching_test_profile_v2()), "profile", "application/json",
                                                     "p.json", {}, profile_id)])
                goal = self.goal(profile_snapshot_id=profile_id, profile_sha256=self._sha(profile_id))
                self.assertGreater(GeneratePipeline(self.store, allow_real_preview=allow).run(goal).segment_count, 0)


class TestWorkerCarriesTheRealPreviewSwitch(RealPreviewBase):
    """ROS 노드가 쓰는 취소 가능한 계산 프로세스에도 스위치가 전달된다(꺼져 있으면 기존 그대로)."""

    def _goal(self):
        profile_id, profile_sha = self._register(matching_test_profile_v3())
        return self.goal(profile_snapshot_id=profile_id, profile_sha256=profile_sha, offset_v_mm=75.0)

    def test_worker_generates_real_preview_only_when_switched_on(self):
        generated = run_generation(self.store, self._goal(), timeout_s=60.0, allow_real_preview=True)
        self.assertGreater(generated.segment_count, 0)
        path, _p, _r, _a = self.outputs(generated)
        self.assertEqual(path["source_mode"], "REAL")
        self.assertIs(path["test_only"], True)

    def test_worker_rejects_real_when_switched_off(self):
        with self.assertRaises(PipelineError) as caught:
            run_generation(self.store, self._goal(), timeout_s=60.0)
        self.assertEqual(caught.exception.code, "NOT_READY")


if __name__ == "__main__":
    unittest.main()
