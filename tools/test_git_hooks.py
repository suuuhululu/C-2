"""Exercise pre-push input without creating commits or contacting a remote."""

from pathlib import Path
import subprocess
import unittest


HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "pre-push"
OID = "1" * 40
ZERO = "0" * 40


class PushGuardTests(unittest.TestCase):
    def run_hook(self, updates):
        return subprocess.run(
            ["sh", str(HOOK), "origin", "unused-test-remote"],
            input=updates,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_main_update_is_blocked(self):
        result = self.run_hook(f"refs/heads/main {OID} refs/heads/main {OID}\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("main", result.stderr)

    def test_different_source_to_main_is_blocked(self):
        result = self.run_hook(f"HEAD {OID} refs/heads/main {OID}\n")
        self.assertNotEqual(result.returncode, 0)

    def test_initial_main_creation_is_blocked(self):
        result = self.run_hook(f"refs/heads/feature {OID} refs/heads/main {ZERO}\n")
        self.assertNotEqual(result.returncode, 0)

    def test_main_deletion_is_blocked(self):
        result = self.run_hook(f"(delete) {ZERO} refs/heads/main {OID}\n")
        self.assertNotEqual(result.returncode, 0)

    def test_one_protected_ref_blocks_multi_ref_push(self):
        result = self.run_hook(
            f"refs/heads/feature {OID} refs/heads/feature {ZERO}\n"
            f"refs/heads/main {OID} refs/heads/main {OID}\n"
        )
        self.assertNotEqual(result.returncode, 0)

    def test_feature_branch_is_allowed(self):
        result = self.run_hook(f"refs/heads/feature {OID} refs/heads/feature {ZERO}\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_same_named_tag_is_not_a_branch(self):
        result = self.run_hook(f"refs/tags/main {OID} refs/tags/main {ZERO}\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_updates_is_allowed(self):
        result = self.run_hook("")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
