import copy
import math
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from c2_process.engraving import ExecutionContext
from c2_process.entry_planner import (
    execute_entry_plan,
    generate_entry_candidates,
    plan_entry_path,
)
from c2_process.robot_adapter import RobotState, StepResult
from c2_process.state_machine import run_prepared_process


class EntryAdapter:
    def __init__(self, *, reject_all=False):
        self.pose = [0.0, 0.0, 0.33, 0.0, 0.0, 0.0, 1.0]
        self.joints_deg = [0.0, 0.0, 20.0, 0.0, 30.0, 0.0]
        self.reject_all = reject_all
        self.moves = []
        self.ik_calls = []

    def observe(self):
        return RobotState(joints_rad=[math.radians(v) for v in self.joints_deg],
                          tcp_pose=list(self.pose), frame_id="c2_base",
                          robot_state=1, quality="VALID")

    def inverse_kinematics(self, pose, _offset, _reference):
        self.ik_calls.append(list(pose))
        if self.reject_all:
            return None
        joints = list(self.joints_deg)
        # 모의 330 mm 후보는 J2 한계, 320 mm 후보는 J3 특이점 여유로 거절한다.
        # 310 mm 후보는 통과한다. 실제 현장값 또는 승인값이 아니다.
        if pose[1] < -0.039 and pose[2] >= 0.329:
            joints[1] = 100.0
        elif pose[1] < -0.039 and 0.319 <= pose[2] <= 0.321:
            joints[2] = 5.0
        return joints

    def move(self, pose, _frame_id, _profile, _deadline, cancel):
        if cancel.is_set():
            return StepResult("STOPPED", "NONE", "취소", "entry")
        self.moves.append(list(pose))
        self.pose = list(pose)
        return StepResult("SUCCEEDED", "NONE", "이동 완료", "entry")


def inputs(adapter=None):
    adapter = adapter or EntryAdapter()
    path = {
        "path_id": "path-1", "path_version": 1, "frame_id": "c2_base",
        "config": {"profile_snapshot_id": "snapshot-1", "profile_sha256": "a" * 64},
        "segments": [
            {"segment_id": "approach-1", "kind": "APPROACH",
             "motion_profile_id": "candle_approach",
             "waypoints": [[0.0, -0.04, 0.22, 0.0, 0.0, 0.0, 1.0]]},
        ],
    }
    workcell = {
        "frame_id": "c2_base", "axis_xy_m": [0.0, 0.0],
        "radius_m": 0.03, "top_z_m": 0.20,
        "home": {"tcp_pose": [0.0, 0.0, 0.33, 0.0, 0.0, 0.0, 1.0]},
        "entry_planning": {
            "enabled": True,
            "tcp_clearance_above_top_range_m": [0.11, 0.13],
            "tcp_z_step_m": 0.01,
            "sample_m": 0.005,
            "sample_deg": 2.0,
            "min_radial_gap_m": 0.005,
            "min_j3_abs_deg": 10.0,
            "min_j5_margin_deg": 15.0,
            "max_joint_step_deg": 20.0,
            "start_position_tolerance_m": 0.001,
            "start_angle_tolerance_deg": 1.0,
            "motion_profile_id": "candle_travel",
        },
    }
    profiles = {"candle_travel": {"vel_mm_s": 5.0, "acc_mm_s2": 10.0,
                                   "completion_timeout_s": 30.0}}
    context = ExecutionContext("run-1", "SIMULATION", threading.Event(), profiles, {})
    limits = [(-355.0, 355.0), (-90.0, 90.0), (-130.0, 130.0),
              (-355.0, 355.0), (-130.0, 130.0), (-345.0, 345.0)]
    return adapter, path, workcell, profiles, context, limits


def test_planner_selects_ik_valid_relative_height_without_motion():
    adapter, path, workcell, profiles, context, limits = inputs()
    state = adapter.observe()

    result = plan_entry_path(path, workcell, adapter, state, [0.0, 0.0, 0.0],
                             limits, 0.0, profiles, cancel=context.cancel)

    assert result.ok, result
    plan = result.observed_state["entry_plan"]
    assert plan["entry_pose"][2] == 0.31
    assert plan["tcp_clearance_above_top_m"] == 0.11
    assert len(result.observed_state["rejected_candidates"]) == 2
    assert adapter.moves == []
    assert adapter.ik_calls
    assert plan["source_binding"]["profile_snapshot_id"] == "snapshot-1"


def test_entry_joint_sequence_is_reused_for_continuity_check():
    adapter, path, workcell, profiles, context, limits = inputs()
    candidates = generate_entry_candidates(
        path, workcell, adapter.pose, [0.0, 0.0, 0.0], profiles)

    result = plan_entry_path(
        path, workcell, adapter, adapter.observe(), [0.0, 0.0, 0.0],
        limits, 0.0, profiles, cancel=context.cancel)

    expected_calls = sum(len(candidate["validation_waypoints"])
                         for candidate in candidates)
    assert result.ok
    assert len(adapter.ik_calls) == expected_calls
    assert result.observed_state["ik_metrics"]["inverse_kinematics_calls"] == expected_calls
    assert len(result.observed_state["entry_plan"]["final_joints_deg"]) == 6


def test_all_candidates_fail_closed_without_motion():
    adapter, path, workcell, profiles, context, limits = inputs(EntryAdapter(reject_all=True))

    result = plan_entry_path(path, workcell, adapter, adapter.observe(), [0.0, 0.0, 0.0],
                             limits, 0.0, profiles, cancel=context.cancel)

    assert (result.outcome, result.error_code) == ("FAILED", "ENTRY_PATH_UNAVAILABLE")
    assert adapter.moves == []


def test_checked_plan_executes_once_and_mutation_is_rejected():
    adapter, path, workcell, profiles, context, limits = inputs()
    result = plan_entry_path(path, workcell, adapter, adapter.observe(), [0.0, 0.0, 0.0],
                             limits, 0.0, profiles, cancel=context.cancel)
    plan = result.observed_state["entry_plan"]

    executed = execute_entry_plan(plan, adapter, context)
    assert executed.ok and adapter.moves == [plan["entry_pose"]]

    adapter2, *_ = inputs()
    changed = copy.deepcopy(plan)
    changed["entry_pose"][2] += 0.001
    blocked = execute_entry_plan(changed, adapter2, context)
    assert blocked.error_code == "PROFILE_MISMATCH" and adapter2.moves == []


def test_prepared_state_machine_runs_entry_between_check_and_engraving():
    _, _, _, _, context, _ = inputs()
    calls, phases = [], []

    def done(name):
        return lambda: calls.append(name) or StepResult("SUCCEEDED")

    result = run_prepared_process(
        context, precheck=done("precheck"), enter=done("entry"),
        engrave=lambda _progress: calls.append("engrave") or StepResult("SUCCEEDED"),
        on_phase=phases.append)

    assert result.ok
    assert calls == ["precheck", "entry", "engrave"]
    assert phases == ["PRECHECK", "ENTRY", "ENGRAVE", "FINISH"]


def test_entry_failure_blocks_engraving():
    _, _, _, _, context, _ = inputs()
    calls = []
    result = run_prepared_process(
        context,
        precheck=lambda: StepResult("SUCCEEDED"),
        enter=lambda: StepResult("FAILED", "ENTRY_PATH_UNAVAILABLE"),
        engrave=lambda _progress: calls.append("engrave") or StepResult("SUCCEEDED"))
    assert result.error_code == "ENTRY_PATH_UNAVAILABLE"
    assert calls == []
