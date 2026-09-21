#!/usr/bin/env python3
"""스냅샷 기하 필드·workcell 연결 규칙·필드 명세 문서 동기화 시험."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from c2_path import snapshot, workcell as wc  # noqa: E402
from c2_path.pipeline import (  # noqa: E402
    PipelineError,
    matching_test_profile,
    matching_test_profile_v2,
    validate_profile,
)

SPEC = ROOT / "BUNDLE_SPEC.md"
TOOL_CALIBRATION = ROOT.parent / "c2_process" / "c2_process" / "tool_calibration.py"


class TestWorkcellView(unittest.TestCase):
    def test_view_matches_workcell_constants(self):
        view = snapshot.workcell_view(matching_test_profile())
        self.assertEqual(view["axis_xy_m"], [wc.AXIS_ORIGIN_XY_M[0], wc.AXIS_ORIGIN_XY_M[1]])
        self.assertAlmostEqual(view["radius_m"], wc.RADIUS_M, places=12)
        self.assertAlmostEqual(view["top_z_m"], wc.TOP_Z_BASE_M, places=9)

    def test_view_has_exactly_the_keys_tool_calibration_reads(self):
        self.assertEqual(set(snapshot.workcell_view(matching_test_profile())), {"axis_xy_m", "radius_m", "top_z_m"})

    @unittest.skipUnless(TOOL_CALIBRATION.is_file(), "c2_process 가 옆에 없음")
    def test_tool_calibration_reads_those_keys(self):
        source = TOOL_CALIBRATION.read_text(encoding="utf-8")
        for key in ("axis_xy_m", "radius_m", "top_z_m"):
            self.assertIn(f'workcell["{key}"]', source)

    def test_consistent_workcell_passes(self):
        profile = matching_test_profile()
        self.assertEqual(snapshot.check_workcell_view(profile, snapshot.workcell_view(profile)), [])

    def test_millimetre_value_under_metre_name_is_caught(self):
        profile = matching_test_profile()
        workcell = snapshot.workcell_view(profile)
        workcell["radius_m"] = 34.25
        errors = snapshot.check_workcell_view(profile, workcell)
        self.assertTrue(any("radius_m" in e for e in errors), errors)

    def test_stale_axis_from_0918_is_caught(self):
        profile = matching_test_profile()
        workcell = snapshot.workcell_view(profile)
        workcell["axis_xy_m"] = [0.4224, -0.0026]               # simulation_inputs.json 의 구버전
        errors = snapshot.check_workcell_view(profile, workcell)
        self.assertEqual(len(errors), 2, errors)

    def test_top_z_must_equal_bottom_plus_height(self):
        profile = matching_test_profile()
        workcell = snapshot.workcell_view(profile)
        workcell["top_z_m"] += 0.001
        self.assertTrue(any("top_z_m" in e for e in snapshot.check_workcell_view(profile, workcell)))

    def test_non_numbers_are_reported_not_raised(self):
        profile = matching_test_profile()
        errors = snapshot.check_workcell_view(profile, {"axis_xy_m": "x", "radius_m": True, "top_z_m": None})
        self.assertEqual(len(errors), 3, errors)


class TestSurfaceGeometry(unittest.TestCase):
    def surface(self, **changes):
        surface = copy.deepcopy(matching_test_profile()["surface"])
        surface.update(changes)
        return surface

    def test_current_test_profile_is_structurally_valid(self):
        self.assertEqual(snapshot.surface_geometry_errors(matching_test_profile()["surface"]), [])

    def test_each_structural_rule(self):
        cases = {
            "kind": {"kind": "cone"},
            "radius": {"radius_mm": 0.0},
            "height": {"height_mm": -1.0},
            "origin": {"axis_origin_m": [0.4, 0.0]},
            "direction": {"axis_direction": [0.0, 1.0, 0.0]},
            "v_range": {"valid_v_range_mm": [140.0, 10.0]},
            "v_range above height": {"valid_v_range_mm": [10.0, 200.0]},
            "u origin": {"u_origin_angle_deg": 270.0},
            "seam": {"seam_angle_deg": -180.0},
            "reachable order": {"reachable_angle_deg": [135.0, -135.0]},
            "reachable contains seam": {"seam_angle_deg": 90.0},
            "bool as number": {"radius_mm": True},
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertTrue(snapshot.surface_geometry_errors(self.surface(**change)), name)

    def test_not_an_object(self):
        self.assertTrue(snapshot.surface_geometry_errors(None))


class TestValidateProfileTypeStrictness(unittest.TestCase):
    def rejects(self, **top):
        profile = matching_test_profile()
        profile.update(top)
        with self.assertRaises(PipelineError) as caught:
            validate_profile(profile)
        self.assertEqual(caught.exception.code, "PROFILE_MISMATCH")

    def test_tools_config_version_true_is_not_one(self):
        self.rejects(tools_config_version=True)

    def test_tools_config_version_as_string_or_float_is_rejected(self):
        self.rejects(tools_config_version="1")
        self.rejects(tools_config_version=1.0)

    def test_tools_config_id_missing_or_wrong(self):
        profile = matching_test_profile()
        del profile["tools_config_id"]
        with self.assertRaises(PipelineError):
            validate_profile(profile)
        self.rejects(tools_config_id="c2_tools_v2")

    def test_numeric_string_is_not_accepted_for_geometry(self):
        profile = matching_test_profile()
        profile["surface"]["radius_mm"] = "34.25"
        with self.assertRaises(PipelineError):
            validate_profile(profile)

    def test_matching_profile_still_passes(self):
        validate_profile(matching_test_profile())


@unittest.skipUnless(SPEC.is_file(), "BUNDLE_SPEC.md 가 없음")
class TestSpecDocumentsEveryProfileField(unittest.TestCase):
    """스냅샷에 필드를 추가하고 명세를 안 고치는 일을 막는다."""

    def test_every_profile_and_surface_field_is_named_in_spec(self):
        text = SPEC.read_text(encoding="utf-8")
        profile = matching_test_profile()
        v2 = matching_test_profile_v2(measurement_id="m-0001", measured_at="2026-09-21T10:30:00+09:00")
        names = set(profile) | {f"surface.{k}" for k in profile["surface"]}
        names |= set(v2) | {f"surface.{k}" for k in v2["surface"]}
        names.discard("surface")
        missing = sorted(n for n in names if f"`{n}`" not in text)
        self.assertEqual(missing, [], f"BUNDLE_SPEC.md 에 필드 설명이 없음: {missing}")
        for contract in ("c2-path-test-profile/1", "c2-path-test-profile/2"):
            self.assertIn(contract, text)

    def test_every_manifest_key_is_named_in_spec(self):
        from c2_path import bundle
        text = SPEC.read_text(encoding="utf-8")
        keys = ["asset_id", "kind", "file", "name", "mime", "sha256", "size_bytes", "path_id", "path_version",
                "executable", "bundle_role", "origin", "inputs", "path", "files", "documents"]
        missing = [k for k in keys if f"`{k}`" not in text]
        self.assertEqual(missing, [])
        self.assertIn(bundle.MANIFEST_CONTRACT, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
