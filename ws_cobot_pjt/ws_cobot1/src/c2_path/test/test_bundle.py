#!/usr/bin/env python3
"""파일 묶음(bundle) 입·출력 시험. ROS·로봇·HMI DB 없이 파일만으로 확인한다."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from c2_path import bundle, workcell as wc  # noqa: E402
from c2_path.artifacts import json_bytes, sha256_bytes  # noqa: E402
from c2_path.pipeline import matching_test_profile  # noqa: E402

ACTION = ROOT.parent / "c2_interfaces" / "action" / "GeneratePath.action"
SAMPLES = ROOT / "samples" / "bundles"


def line_png():
    image = np.full((200, 200), 255, np.uint8)
    cv2.line(image, (20, 100), (180, 100), 0, 5, cv2.LINE_AA)
    okay, encoded = cv2.imencode(".png", image)
    assert okay
    return encoded.tobytes()


def hmi_encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def action_fields(section):
    """GeneratePath.action 의 Goal(0)/Result(1) 필드 이름 목록. 상수 줄(NAME=값)은 제외."""
    body = ACTION.read_text(encoding="utf-8").split("\n---\n")[section]
    names = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if "=" in parts[0] or "=" in parts[1]:
            continue
        names.append(parts[1])
    return names


class BundleFixture(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.image = line_png()
        self.profile = hmi_encoded(matching_test_profile())

    def request(self, **changes):
        value = {
            "schema_version": 2, "request_id": str(uuid4()), "source_mode": "SIMULATION",
            "asset_id": str(uuid4()), "asset_sha256": sha256_bytes(self.image),
            "width_mm": 24.0, "height_mm": 24.0, "offset_u_mm": 0.0, "offset_v_mm": 105.0,
            "rotation_deg": 0.0, "conversion_preset": "raster_centerline_bezier", "tool_id": wc.TOOL_ID,
            "profile_snapshot_id": str(uuid4()), "profile_sha256": sha256_bytes(self.profile),
        }
        value.update(changes)
        return value

    def make_input(self, request=None, profile=None, name="in"):
        request = request or self.request()
        profile = self.profile if profile is None else profile
        directory = self.temp / name
        bundle.write_input_bundle(directory, request=request, image=self.image, image_name="line.png",
                                  image_mime="image/png", profile_bytes=profile,
                                  profile_name="profile.json", origin="local_test_sample")
        return directory, request

    def run_ok(self, **changes):
        request = self.request(**changes)
        directory, request = self.make_input(request)
        out = self.temp / "out"
        return directory, out, request, bundle.run_bundle(directory, out)


class TestGoalAndResultMatchAction(unittest.TestCase):
    @unittest.skipUnless(ACTION.is_file(), "c2_interfaces 가 옆에 없음")
    def test_fields_match_generate_path_action(self):
        self.assertEqual(list(bundle.GOAL_FIELDS), action_fields(0))
        self.assertEqual(list(bundle.RESULT_FIELDS), action_fields(1))


class TestRunAndVerify(BundleFixture):
    def test_success_bundle_is_complete_and_verifies(self):
        _, out, request, result = self.run_ok()
        self.assertTrue(result["success"])
        self.assertEqual(list(result), list(bundle.RESULT_FIELDS))
        self.assertEqual(bundle.verify_bundle(out), [])
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        kinds = sorted(e["kind"] for e in manifest["files"])
        self.assertEqual(kinds, ["path", "preview", "svg", "validation"])
        path_entry = next(e for e in manifest["files"] if e["kind"] == "path")
        # path_id(논리 경로)와 path 파일의 asset_id 는 다르고, manifest 가 둘을 잇는다.
        self.assertNotEqual(path_entry["asset_id"], result["path_id"])
        self.assertEqual(manifest["path"], {"path_id": result["path_id"], "path_version": 1,
                                            "path_sha256": result["path_sha256"], "asset_id": path_entry["asset_id"]})
        self.assertEqual(path_entry["sha256"], result["path_sha256"])
        self.assertEqual(manifest["inputs"]["profile_sha256"], request["profile_sha256"])
        # manifest 는 자기 자신을 목록에 넣지 않는다.
        self.assertNotIn("manifest.json", [e["file"] for e in manifest["files"]])

    def test_path_file_bytes_hash_matches_result(self):
        _, out, _, result = self.run_ok()
        path_bytes = (out / "c2-path.json").read_bytes()
        self.assertEqual(sha256_bytes(path_bytes), result["path_sha256"])
        path = json.loads(path_bytes)
        self.assertEqual(path["path_id"], result["path_id"])
        self.assertNotIn("path_sha256", path, "파일이 자기 해시를 담으면 안 된다")

    def test_input_bytes_are_used_as_received_not_reserialized(self):
        # 사람이 읽기 좋게 들여쓴 바이트로 등록돼도 해시는 그 바이트 기준이어야 한다.
        pretty = json_bytes(matching_test_profile())
        self.assertNotEqual(pretty, self.profile)
        request = self.request(profile_sha256=sha256_bytes(pretty))
        directory, request = self.make_input(request, profile=pretty)
        result = bundle.run_bundle(directory, self.temp / "out")
        self.assertTrue(result["success"], result)

    def test_generation_failure_still_writes_verifiable_failed_bundle(self):
        _, out, _, result = self.run_ok(offset_v_mm=200.0)         # 옆면(높이 150mm) 밖
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "VALIDATION_FAILED")
        self.assertEqual((result["path_id"], result["path_version"], result["path_sha256"]), ("", 0, ""))
        self.assertEqual(bundle.verify_bundle(out), [])
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["path"])
        self.assertTrue(all(e["executable"] is False for e in manifest["files"]))
        self.assertNotIn("path", [e["kind"] for e in manifest["files"]])

    def test_profile_mismatch_writes_failed_bundle_without_files(self):
        wrong = matching_test_profile()
        wrong["surface"]["radius_mm"] = 34.0
        raw = hmi_encoded(wrong)
        request = self.request(profile_sha256=sha256_bytes(raw))
        directory, _ = self.make_input(request, profile=raw)
        out = self.temp / "out"
        result = bundle.run_bundle(directory, out)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "PROFILE_MISMATCH")
        self.assertEqual(bundle.verify_bundle(out), [])
        self.assertEqual(json.loads((out / "manifest.json").read_text(encoding="utf-8"))["files"], [])

    def test_tampered_input_image_is_rejected_by_hash(self):
        directory, _ = self.make_input()
        (directory / "line.png").write_bytes(self.image + b"tamper")
        out = self.temp / "out"
        result = bundle.run_bundle(directory, out)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "HASH_MISMATCH")
        self.assertEqual(bundle.verify_bundle(out), [])

    def test_output_folder_is_never_overwritten(self):
        directory, _ = self.make_input()
        out = self.temp / "out"
        out.mkdir()
        (out / "keep.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(bundle.BundleError) as caught:
            bundle.run_bundle(directory, out)
        self.assertEqual(caught.exception.code, "OUTPUT_EXISTS")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["keep.txt"])

    def test_request_must_have_exactly_goal_fields(self):
        directory, request = self.make_input()
        extra = dict(request, note="extra")
        raw = json_bytes(extra)
        (directory / "request.json").write_bytes(raw)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifest["documents"][0]["sha256"] = sha256_bytes(raw)
        (directory / "manifest.json").write_bytes(json_bytes(manifest))
        with self.assertRaises(bundle.BundleError) as caught:
            bundle.run_bundle(directory, self.temp / "out")
        self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_write_input_bundle_rejects_hash_that_differs_from_bytes(self):
        request = self.request(asset_sha256="0" * 64)
        with self.assertRaises(bundle.BundleError) as caught:
            self.make_input(request)
        self.assertEqual(caught.exception.code, "HASH_MISMATCH")


class TestVerifyCatchesBrokenBundles(BundleFixture):
    def setUp(self):
        super().setUp()
        _, self.out, self.request_, self.result = self.run_ok()

    def rewrite(self, name, mutate):
        path = self.out / name
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_bytes(json_bytes(value))

    def assertHas(self, needle):
        errors = bundle.verify_bundle(self.out)
        self.assertTrue(any(needle in e for e in errors), errors)

    def test_modified_file_is_hash_mismatch(self):
        (self.out / "c2-path.json").write_bytes((self.out / "c2-path.json").read_bytes() + b" ")
        self.assertHas("HASH_MISMATCH")

    def test_missing_file(self):
        (self.out / "c2-path-preview.json").unlink()
        self.assertHas("파일이 없습니다")

    def test_unlisted_extra_file(self):
        (self.out / "extra.json").write_text("{}", encoding="utf-8")
        self.assertHas("UNLISTED_FILE")

    def test_result_path_hash_must_match_path_file(self):
        self.rewrite("result.json", lambda v: v.update(path_sha256="a" * 64))
        errors = bundle.verify_bundle(self.out)
        self.assertTrue(any("HASH_MISMATCH" in e or "manifest.path" in e for e in errors), errors)

    def test_result_asset_id_must_point_to_right_kind(self):
        def swap(v):
            v["svg_asset_id"], v["preview_asset_id"] = v["preview_asset_id"], v["svg_asset_id"]
        self.rewrite("result.json", swap)
        self.assertHas("svg 파일이 files에 없습니다")

    def test_manifest_path_summary_must_link_path_id_to_asset(self):
        def alter(v):
            v["path"]["asset_id"] = str(uuid4())
        self.rewrite("manifest.json", alter)
        self.assertHas("manifest.path")

    def test_absolute_or_nested_file_names_are_rejected(self):
        def alter(v):
            v["files"][0]["file"] = "/etc/passwd"
        self.rewrite("manifest.json", alter)
        self.assertHas("상대 파일명")

    def test_result_missing_fields(self):
        self.rewrite("result.json", lambda v: v.pop("error_code"))
        self.assertHas("GeneratePath Result 전체")

    def test_success_must_not_carry_executable_false(self):
        def alter(v):
            v["files"][0]["executable"] = False
        self.rewrite("manifest.json", alter)
        self.assertHas("executable=false")


@unittest.skipUnless(SAMPLES.is_dir(), "samples/bundles 가 없음 (build_bundle_samples.py 로 생성)")
class TestCommittedSamples(unittest.TestCase):
    def test_every_sample_bundle_verifies(self):
        folders = sorted(p for p in SAMPLES.glob("*/*") if p.is_dir())
        self.assertGreaterEqual(len(folders), 4)
        for folder in folders:
            self.assertEqual(bundle.verify_bundle(folder), [], folder)

    def test_sample_input_is_marked_as_not_issued_by_hmi(self):
        for manifest in SAMPLES.glob("*/input/manifest.json"):
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["origin"], "local_test_sample")

    def test_sample_off_surface_bundle_has_no_executable_path(self):
        out = SAMPLES / "heart_off_surface" / "output"
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "VALIDATION_FAILED")
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
