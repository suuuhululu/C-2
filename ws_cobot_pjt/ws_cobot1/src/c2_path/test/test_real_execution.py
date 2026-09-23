#!/usr/bin/env python3
"""준비 BIND에 연결된 REAL 실행 후보 경로 계약 시험.

이 시험은 로봇을 움직이지 않는다. c2_path가 실행 후보를 만들 때 필요한
스냅샷 근거와 산출물의 ID·버전·해시 연결만 검증한다. 최종 IK·관절·J6
판정은 c2_process가 ExecuteProcess 안에서 수행한다.
"""
import copy
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from c2_path import readiness  # noqa: E402
from c2_path.diagnostics import placement_for_joint_failure  # noqa: E402
from c2_path.artifacts import ArtifactWrite, json_bytes, new_id  # noqa: E402
from test_generate_pipeline import filled_rectangle_png  # noqa: E402
from c2_path.pipeline import (  # noqa: E402
    GeneratePipeline,
    PipelineError,
    matching_test_profile_v3,
    matching_test_profile_v4,
    validate_profile,
)
from c2_path.worker import run_generation  # noqa: E402
from test_profile_contract import ProfileRegistered  # noqa: E402


class RealExecutionBase(ProfileRegistered):
    profile_factory = staticmethod(matching_test_profile_v4)

    def goal(self, **changes):
        changes.setdefault("source_mode", "REAL")
        return super().goal(**changes)

    def register(self, profile):
        profile_id = new_id()
        self.store.put_bundle([ArtifactWrite(
            json_bytes(profile), "profile", "application/json", "real-execution-profile.json", {}, profile_id)])
        return profile_id, self._sha(profile_id)

    def run_profile(self, profile=None, **goal_changes):
        profile = profile or matching_test_profile_v4()
        profile_id, profile_sha = self.register(profile)
        result = GeneratePipeline(self.store, allow_real_execution=True).run(
            self.goal(profile_snapshot_id=profile_id, profile_sha256=profile_sha, **goal_changes))
        return result, profile, profile_id, profile_sha

    def read(self, asset_id, kind):
        artifact = self.store.read(asset_id, self._sha(asset_id), (kind,))
        return json.loads(artifact.path.read_text(encoding="utf-8")), artifact

    def outputs(self, result):
        path, artifact = self.read(result.path_asset_id, "path")
        preview, _ = self.read(result.preview_asset_id, "preview")
        report, _ = self.read(result.validation_report_id, "validation")
        return path, preview, report, artifact


class TestRealExecutionCandidate(RealExecutionBase):
    def test_real_hatch_candidate_uses_same_profile_and_recipe_in_outputs(self):
        image_id = new_id()
        self.store.put_bundle([ArtifactWrite(
            filled_rectangle_png(), "image", "image/png", "filled.png", {}, image_id)])
        image_sha = self._sha(image_id)
        goal_placement = dict(width_mm=24.0, height_mm=24.0, offset_u_mm=0.0,
                              offset_v_mm=75.0, rotation_deg=0.0)
        generated, profile, profile_id, profile_sha = self.run_profile(
            asset_id=image_id, asset_sha256=image_sha,
            conversion_preset="raster_parallel_hatch", **goal_placement)
        path, preview, report, artifact = self.outputs(generated)
        for output in (path, preview, report):
            self.assertEqual(output["source_mode"], "REAL")
            self.assertIs(output["test_only"], False)
            self.assertIs(output["real_execution_allowed"], True)
        self.assertEqual(path["config"]["profile_snapshot_id"], profile_id)
        self.assertEqual(path["config"]["profile_sha256"], profile_sha)
        self.assertEqual(preview["profile_snapshot_id"], profile_id)
        self.assertEqual(preview["profile_sha256"], profile_sha)
        self.assertEqual(report["profile_snapshot_id"], profile_id)
        self.assertEqual(report["profile_sha256"], profile_sha)
        self.assertEqual(preview["path_sha256"], hashlib.sha256(artifact.path.read_bytes()).hexdigest())
        self.assertEqual(path["config"]["conversion"], report["conversion"])
        self.assertEqual(path["config"]["conversion"]["recipe_scope"], "surface_path")
        self.assertEqual(path["config"]["conversion"]["placement"], goal_placement)
        self.assertEqual(path["preparation_id"], profile["preparation_id"])
        cut = next(seg for seg in path["segments"] if seg["kind"] == "CUT")
        diagnostic = placement_for_joint_failure(
            path, preview, {"segment_id": cut["segment_id"], "index": 0})
        self.assertEqual(diagnostic["placement"], goal_placement)
        self.assertEqual(diagnostic["stroke_id"], cut["stroke_id"])
        self.assertIsNotNone(diagnostic["segment_u_range_mm"])
        with self.assertRaises(ValueError):
            placement_for_joint_failure(path, dict(preview, path_id="wrong"),
                                        {"segment_id": cut["segment_id"]})

    def test_execution_candidate_preserves_binding_and_stays_not_judged(self):
        result, profile, profile_id, profile_sha = self.run_profile(offset_v_mm=75.0)
        path, preview, report, artifact = self.outputs(result)

        for document in (path, preview, report):
            self.assertEqual(document["source_mode"], "REAL")
            self.assertIs(document["test_only"], False)
            self.assertIs(document["real_execution_allowed"], True)
        self.assertEqual(path["preparation_id"], profile["preparation_id"])
        self.assertEqual(path["measurement_id"], profile["measurement_id"])
        self.assertEqual(path["config"]["profile_snapshot_id"], profile_id)
        self.assertEqual(path["config"]["profile_sha256"], profile_sha)
        self.assertEqual(report["execution_readiness"]["executability"], "NOT_JUDGED")
        self.assertNotIn("execution_blocked", report["execution_readiness"])
        self.assertEqual(preview["execution_readiness"]["precheck"], readiness.WITHIN)
        for document in (path["config"]["real_execution"], preview["real_execution"],
                         report["real_execution"]):
            self.assertEqual(document["validity"], "ESTIMATED")
            self.assertIs(document["absolute_top_verified"], False)
            self.assertIs(document["independent_accuracy_verified"], False)
            self.assertEqual(document["offset_status"], "ESTIMATED")
            self.assertEqual(document["offset_record_id"], "unit-test-offset")
            self.assertEqual(document["offset_estimate_source"], "unit-test-estimate")

        digest = hashlib.sha256(artifact.path.read_bytes()).hexdigest()
        self.assertEqual(result.path_sha256, digest)
        self.assertEqual(preview["path_sha256"], digest)
        self.assertEqual(path["path_id"], preview["path_id"])
        self.assertEqual(path["path_id"], report["path_id"])
        self.assertEqual(path["path_version"], preview["path_version"])
        self.assertEqual(path["path_version"], report["path_version"])

    def test_real_execution_requires_explicit_node_switch(self):
        profile_id, profile_sha = self.register(matching_test_profile_v4())
        with self.assertRaises(PipelineError) as caught:
            GeneratePipeline(self.store, allow_real_preview=True).run(
                self.goal(profile_snapshot_id=profile_id, profile_sha256=profile_sha, offset_v_mm=75.0))
        self.assertEqual(caught.exception.code, "NOT_READY")
        self.assertIn("allow_real_execution", caught.exception.message)

    def test_preview_contract_never_becomes_execution_candidate(self):
        profile_id, profile_sha = self.register(matching_test_profile_v3())
        result = GeneratePipeline(self.store, allow_real_execution=True).run(
            self.goal(profile_snapshot_id=profile_id, profile_sha256=profile_sha, offset_v_mm=75.0))
        path, preview, report, _ = self.outputs(result)
        self.assertIs(path["test_only"], True)
        self.assertIs(path.get("real_execution_allowed", False), False)
        self.assertIs(preview["test_only"], True)
        self.assertNotIn("real_execution_allowed", preview)
        self.assertEqual(report["execution_readiness"]["execution_blocked"]["code"],
                         readiness.PREVIEW_ONLY_CODE)

    def test_out_of_provisional_range_is_not_execution_allowed(self):
        profile = matching_test_profile_v4(
            radius_mm=30.0, height_mm=120.0, axis_origin_m=[0.45, 0.01, 0.09],
            valid_v_range_mm=[10.0, 110.0])
        result, _profile, _pid, _sha = self.run_profile(
            profile, offset_v_mm=112.0, height_mm=10.0, width_mm=10.0)
        path, preview, report, _ = self.outputs(result)
        self.assertIs(path["test_only"], False)
        self.assertIs(path["real_execution_allowed"], False)
        self.assertIs(path["config"]["real_execution_allowed"], False)
        self.assertIs(path["config"]["real_execution"]["real_execution_allowed"], False)
        self.assertIs(preview["real_execution_allowed"], False)
        self.assertIs(report["real_execution_allowed"], False)
        self.assertEqual(report["execution_readiness"]["precheck"], readiness.OUT_OF)

    def test_missing_execution_evidence_is_rejected(self):
        mutations = (
            lambda p: p.__setitem__("test_only", True),
            lambda p: p.__setitem__("real_execution_allowed", False),
            lambda p: p["workcell"].__setitem__("measurement_scope", "INTEGRATION_ESTIMATE"),
            lambda p: p["workcell"]["top"].__setitem__("offset_status", "UNKNOWN"),
            lambda p: p["workcell"]["top"].__setitem__("offset_record_id", ""),
            lambda p: p.pop("execution_context"),
            lambda p: p.pop("joint_check_arguments"),
            lambda p: p.pop("tip_calibration"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                profile = copy.deepcopy(matching_test_profile_v4())
                mutate(profile)
                with self.assertRaises(PipelineError) as caught:
                    validate_profile(profile)
                self.assertEqual(caught.exception.code, "PROFILE_MISMATCH")

    def test_estimated_offset_is_accepted_but_never_promoted(self):
        profile = matching_test_profile_v4()
        validate_profile(profile)
        result, _profile, _pid, _sha = self.run_profile(profile, offset_v_mm=75.0)
        path, preview, report, _artifact = self.outputs(result)
        self.assertIs(path["test_only"], False)
        self.assertIs(path["real_execution_allowed"], True)
        for marks in (path["config"]["real_execution"], preview["real_execution"],
                      report["real_execution"]):
            self.assertEqual(marks["offset_status"], "ESTIMATED")
            self.assertEqual(marks["validity"], "ESTIMATED")
            self.assertIs(marks["absolute_top_verified"], False)

    def test_estimated_offset_requires_its_source(self):
        profile = matching_test_profile_v4()
        profile["workcell"]["top"].pop("estimate_source")
        with self.assertRaises(PipelineError) as caught:
            validate_profile(profile)
        self.assertEqual(caught.exception.code, "PROFILE_MISMATCH")

    def test_confirmed_top_state_is_preserved_without_becoming_permission(self):
        profile = matching_test_profile_v4()
        profile["absolute_top_verified"] = True
        profile["measurement_assumptions"]["absolute_top_verified"] = True
        profile["measurement_assumptions"]["independent_accuracy_verified"] = True
        result, _profile, _pid, _sha = self.run_profile(profile, offset_v_mm=75.0)
        path, preview, report, _artifact = self.outputs(result)
        for marks in (path["config"]["real_execution"], preview["real_execution"],
                      report["real_execution"]):
            self.assertIs(marks["absolute_top_verified"], True)
            self.assertIs(marks["independent_accuracy_verified"], True)
        self.assertEqual(report["execution_readiness"]["executability"], "NOT_JUDGED")

    def test_measurement_confirmation_fields_must_be_consistent(self):
        profile = matching_test_profile_v4()
        profile["measurement_status"] = "FORCE_CONTACT_ESTIMATE"
        with self.assertRaises(PipelineError) as caught:
            validate_profile(profile)
        self.assertEqual(caught.exception.code, "PROFILE_MISMATCH")

    def test_missing_generated_motion_profile_is_rejected(self):
        profile = matching_test_profile_v4()
        profile["execution_context"]["motion_profiles"].pop("candle_retract")
        with self.assertRaises(PipelineError) as caught:
            validate_profile(profile)
        self.assertEqual(caught.exception.code, "PROFILE_MISMATCH")

    def test_worker_carries_real_execution_switch(self):
        profile_id, profile_sha = self.register(matching_test_profile_v4())
        generated = run_generation(
            self.store,
            self.goal(profile_snapshot_id=profile_id, profile_sha256=profile_sha, offset_v_mm=75.0),
            timeout_s=60.0,
            allow_real_execution=True,
        )
        path, _preview, _report, _artifact = self.outputs(generated)
        self.assertIs(path["test_only"], False)
        self.assertIs(path["real_execution_allowed"], True)


if __name__ == "__main__":
    import unittest
    unittest.main()
