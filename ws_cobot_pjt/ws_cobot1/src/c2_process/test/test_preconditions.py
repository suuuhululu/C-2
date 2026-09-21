"""고정 드릴 PRECHECK가 확인 근거 없이는 통과하지 않는지 검사."""

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
from c2_process.robot_adapter import RobotState, StepResult

draft = PACKAGE / "c2_process/preconditions.py"
spec = importlib.util.spec_from_file_location("c2_process.preconditions", draft)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def sample():
    snapshot = {"profile_snapshot_id": "snapshot-1", "tool_id": "engraving_drill",
                "tool_version": 1, "frame_id": "c2_base"}
    snapshot_bytes = json.dumps(snapshot).encode()
    path = {"schema_version": 2, "path_id": "path-1", "path_version": 1,
            "profile_snapshot_id": "snapshot-1",
            "profile_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "tool_id": "engraving_drill", "tool_version": 1,
            "frame_id": "c2_base", "source_mode": "SIMULATION",
            "position_unit": "m", "orientation": "quaternion_xyzw",
            "segments": [{"segment_id": "cut-1", "kind": "CUT"}]}
    path_bytes = json.dumps(path).encode()
    goal = {"schema_version": 2, "request_id": "req-1", "run_id": "run-1",
            "path_id": "path-1", "path_version": 1,
            "path_sha256": hashlib.sha256(path_bytes).hexdigest(),
            "source_mode": "SIMULATION"}
    state = RobotState(frame_id="c2_base", robot_state=1, measured_at=100.0, quality="VALID")
    evidence = module.PreconditionEvidence(
        runtime_mode="SIMULATION", robot_state=state,
        control_authority_confirmed=True, stop_latched=False,
        mounted_tool_id="engraving_drill", mount_confirmation_source="OPERATOR", mount_confirmed_at=100.0,
        gripper_closed_confirmed=True, gripper_confirmation_source="OPERATOR", gripper_confirmed_at=100.0,
        path_validation_passed=True, j6_validation_passed=True,
        validation_path_sha256=goal["path_sha256"], profile_snapshot_id="snapshot-1",
        max_robot_state_age_s=2.0,
        max_confirmation_age_s=2.0)
    return goal, path, path_bytes, snapshot, snapshot_bytes, evidence


def real_sample():
    values = list(sample())
    values[1] = dict(values[1], source_mode="REAL")
    values[2] = json.dumps(values[1]).encode()
    values[0] = dict(values[0], source_mode="REAL",
                     path_sha256=hashlib.sha256(values[2]).hexdigest())
    values[5] = module.PreconditionEvidence(**{**vars(values[5]),
        "runtime_mode": "REAL", "validation_path_sha256": values[0]["path_sha256"]})
    return values


class TestPreconditions(unittest.TestCase):
    def check(self, inputs):
        return module.check_preconditions(*inputs, now_monotonic=100.5)

    def test_confirmed_inputs_pass(self):
        self.assertEqual(self.check(sample()).outcome, "SUCCEEDED")

    def test_simulation_does_not_require_physical_mount_or_grip_confirmation(self):
        values = list(sample())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "mounted_tool_id": "", "mount_confirmation_source": "UNKNOWN", "mount_confirmed_at": None,
            "gripper_closed_confirmed": False, "gripper_confirmation_source": "UNKNOWN",
            "gripper_confirmed_at": None, "max_confirmation_age_s": None})
        self.assertEqual(self.check(values).outcome, "SUCCEEDED")

    def test_test_only_path_and_snapshot_pass_in_simulation(self):
        values = list(sample())
        values[3] = dict(values[3], test_only=True)
        values[4] = json.dumps(values[3]).encode()
        values[1] = dict(values[1], test_only=True,
                         profile_sha256=hashlib.sha256(values[4]).hexdigest())
        values[2] = json.dumps(values[1]).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).outcome, "SUCCEEDED")

    def test_current_joint_check_overrides_stale_positive_boolean(self):
        values = sample()
        result = module.check_preconditions(*values, now_monotonic=100.5,
            joint_check=lambda: StepResult("FAILED", "VALIDATION_FAILED", "J5 한계 초과", "joint_check"))
        self.assertEqual((result.outcome, result.error_code), ("FAILED", "VALIDATION_FAILED"))

    def test_invalid_path_does_not_call_joint_check(self):
        values = list(sample())
        values[2] += b" "
        result = module.check_preconditions(*values, now_monotonic=100.5,
            joint_check=lambda: self.fail("손상된 경로로 IK를 호출함"))
        self.assertEqual(result.error_code, "PATH_MISMATCH")

    def test_fixture_confirmation_is_not_required(self):
        goal, path, path_bytes, snapshot, snapshot_bytes, evidence = sample()
        self.assertNotIn("operator_confirmed_fixture", goal)
        self.assertEqual(self.check((goal, path, path_bytes, snapshot, snapshot_bytes, evidence)).outcome, "SUCCEEDED")

    def test_old_tool_is_rejected(self):
        values = list(sample())
        values[1] = dict(values[1], tool_id="engraving_knife")
        values[2] = json.dumps(values[1]).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        self.assertEqual(self.check(values).error_code, "TOOL_MISMATCH")

    def test_nested_path_config_is_accepted(self):
        values = list(sample())
        path = dict(values[1])
        path["config"] = {key: path.pop(key) for key in
                          ("profile_snapshot_id", "profile_sha256", "tool_version")}
        path["config"]["tool_id"] = path["tool_id"]
        values[1] = path
        values[2] = json.dumps(path).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]), "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).outcome, "SUCCEEDED")

    def test_conflicting_tool_ids_are_rejected_even_when_both_are_valid_strings(self):
        values = list(sample())
        path = dict(values[1], config={
            "profile_snapshot_id": "snapshot-1",
            "profile_sha256": values[1]["profile_sha256"],
            "tool_id": "engraving_drill", "tool_version": 1,
        }, tool_id="engraving_knife")
        values[1] = path
        values[2] = json.dumps(path).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).error_code, "TOOL_MISMATCH")

    def test_missing_engraving_tool_mirror_is_rejected(self):
        values = list(sample())
        path = dict(values[1])
        path["config"] = {key: path[key] for key in
                          ("profile_snapshot_id", "profile_sha256", "tool_id", "tool_version")}
        path.pop("tool_id")
        values[1] = path
        values[2] = json.dumps(path).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).error_code, "TOOL_MISMATCH")

    def test_test_only_path_is_rejected_despite_positive_validation_evidence(self):
        values = list(sample())
        values[1] = dict(values[1], test_only=True, source_mode="REAL")
        values[2] = json.dumps(values[1]).encode()
        values[0] = dict(values[0], source_mode="REAL",
                         path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "runtime_mode": "REAL", "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).error_code, "NOT_READY")

    def test_explicit_failed_validation_cannot_be_overridden_by_evidence(self):
        values = list(sample())
        values[1] = dict(values[1], validation={"passed": False})
        values[2] = json.dumps(values[1]).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).error_code, "VALIDATION_UNAVAILABLE")

    def test_frame_id_remains_top_level_and_rejects_conflicting_config_copy(self):
        values = list(sample())
        values[1] = dict(values[1], config={**values[1], "frame_id": "other"})
        values[2] = json.dumps(values[1]).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).error_code, "FRAME_MISMATCH")

    def test_snapshot_id_from_store_metadata_is_accepted(self):
        values = list(sample())
        snapshot = dict(values[3])
        snapshot.pop("profile_snapshot_id")
        values[3] = snapshot
        values[4] = json.dumps(snapshot).encode()
        values[1] = dict(values[1], profile_sha256=hashlib.sha256(values[4]).hexdigest())
        values[2] = json.dumps(values[1]).encode()
        values[0] = dict(values[0], path_sha256=hashlib.sha256(values[2]).hexdigest())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]),
            "profile_snapshot_id": "snapshot-1", "validation_path_sha256": values[0]["path_sha256"]})
        self.assertEqual(self.check(values).outcome, "SUCCEEDED")

    def test_self_declared_snapshot_id_without_store_record_is_rejected(self):
        values = list(sample())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]), "profile_snapshot_id": ""})
        self.assertEqual(self.check(values).error_code, "PROFILE_MISMATCH")

    def test_v1_goal_is_rejected(self):
        values = list(sample())
        values[0] = dict(values[0], schema_version=1)
        self.assertEqual(self.check(values).error_code, "UNSUPPORTED_SCHEMA_VERSION")

    def test_legacy_gripper_source_is_not_a_required_input(self):
        values = real_sample()
        values[5] = module.PreconditionEvidence(**{**vars(values[5]), "gripper_confirmation_source": "COMMAND_ONLY"})
        self.assertTrue(self.check(values).ok)

    def test_legacy_gripper_timestamp_is_not_a_required_input(self):
        values = real_sample()
        values[5] = module.PreconditionEvidence(**{**vars(values[5]), "gripper_confirmed_at": 90.0})
        self.assertTrue(self.check(values).ok)

    def test_old_validation_is_rejected(self):
        values = list(sample())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]), "validation_path_sha256": "other"})
        self.assertEqual(self.check(values).error_code, "VALIDATION_UNAVAILABLE")

    def test_stale_robot_is_rejected(self):
        values = list(sample())
        values[5].robot_state.measured_at = 90.0
        self.assertEqual(self.check(values).error_code, "ROBOT_NOT_READY")

    def test_bytes_and_decoded_path_must_match(self):
        values = list(sample())
        values[1] = dict(values[1], frame_id="other")
        self.assertEqual(self.check(values).error_code, "INVALID_INPUT")

    def test_no_confirmation_fails_closed(self):
        values = list(sample())
        values[5] = module.PreconditionEvidence(runtime_mode="SIMULATION", robot_state=values[5].robot_state)
        self.assertEqual(self.check(values).outcome, "FAILED")

    def test_tampered_path_bytes_rejected(self):
        values = list(sample())
        values[2] += b" "
        self.assertEqual(self.check(values).error_code, "PATH_MISMATCH")

    def test_missing_freshness_limit_rejected(self):
        values = list(sample())
        values[5] = module.PreconditionEvidence(**{**vars(values[5]), "max_robot_state_age_s": None})
        self.assertEqual(self.check(values).error_code, "NOT_READY")




class TestRobotStatus(unittest.TestCase):
    """경로/해시 없이 로봇 상태를 검사한다. 수동 확인은 코드로 주장하지 않는다."""

    def test_real_status_does_not_claim_manual_confirmation(self):
        result = module.check_robot_status(real_sample()[5], now_monotonic=100.5)
        self.assertTrue(result.ok)
        self.assertEqual(result.observed_state["physical_confirmation_source"], "MANUAL_PROCEDURE_NOT_VERIFIED")

    def test_legacy_operator_fields_are_not_required(self):
        cases = [
            ({"mount_confirmation_source": "SENSOR"}, "TOOL_NOT_CONFIRMED"),
            ({"mount_confirmation_source": "UNKNOWN"}, "TOOL_NOT_CONFIRMED"),
            ({"mounted_tool_id": "other"}, "TOOL_NOT_CONFIRMED"),
            ({"mount_confirmed_at": None}, "TOOL_NOT_CONFIRMED"),
            ({"mount_confirmed_at": 90.0}, "TOOL_NOT_CONFIRMED"),
            ({"gripper_confirmation_source": "SENSOR"}, "GRIP_NOT_CONFIRMED"),
            ({"gripper_confirmation_source": "COMMAND_ONLY"}, "GRIP_NOT_CONFIRMED"),
            ({"gripper_closed_confirmed": False}, "GRIP_NOT_CONFIRMED"),
            ({"gripper_closed_confirmed": "true"}, "GRIP_NOT_CONFIRMED"),
            ({"gripper_confirmed_at": 101.0}, "GRIP_NOT_CONFIRMED"),
        ]
        for changes, code in cases:
            with self.subTest(changes=changes):
                evidence = module.PreconditionEvidence(**{**vars(real_sample()[5]), **changes})
                result = module.check_robot_status(evidence, now_monotonic=100.5)
                self.assertTrue(result.ok)

    def test_simulation_does_not_claim_operator_confirmation(self):
        result = module.check_robot_status(sample()[5], now_monotonic=100.5)
        self.assertTrue(result.ok)
        self.assertEqual(result.observed_state["physical_confirmation_source"], "NOT_CHECKED_SIMULATION")


if __name__ == "__main__":
    unittest.main()
