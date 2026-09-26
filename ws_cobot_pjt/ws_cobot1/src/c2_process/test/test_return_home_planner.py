import copy
import math
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from c2_process.engraving import ExecutionContext
from c2_process.return_home_planner import (
    execute_return_home_plan,
    plan_return_home_path,
)
from c2_process.robot_adapter import RobotState, StepResult
from c2_process.state_machine import run_prepared_process


class ReturnAdapter:
    def __init__(self):
        self.pose = [0.3, -0.1, 0.35, 0.0, 0.0, 0.0, 1.0]
        self.joints_deg = [0.0, 0.0, 20.0, 0.0, 30.0, 0.0]
        self.tool_offset_m = [0.0, -0.1, 0.0]
        self.moves = []
        self.ik_calls = 0

    def observe(self):
        return RobotState(joints_rad=[math.radians(v) for v in self.joints_deg],
                          tcp_pose=list(self.pose), frame_id="c2_base",
                          robot_state=1, quality="VALID")

    def inverse_kinematics(self, _pose, _offset, _reference):
        self.ik_calls += 1
        return list(self.joints_deg)

    def move(self, pose, _frame_id, _profile, _deadline, cancel):
        if cancel.is_set():
            return StepResult("STOPPED", "NONE", "취소", "return_home",
                              {"stop_confirmed": True})
        self.moves.append(list(pose))
        self.pose = list(pose)
        return StepResult("SUCCEEDED", "NONE", "이동 완료", "return_home")


def fixture(start_z=0.15):
    adapter = ReturnAdapter()
    profiles = {
        "candle_travel": {"vel_mm_s": 25.0, "acc_mm_s2": 10.0,
                          "completion_timeout_s": 90.0},
        "candle_retract": {"vel_mm_s": 25.0, "acc_mm_s2": 10.0,
                           "completion_timeout_s": 90.0},
    }
    execution_plan = {
        "path_id": "path-1", "path_version": 1, "frame_id": "c2_base",
        "config": {"profile_snapshot_id": "snapshot-1",
                   "profile_sha256": "a" * 64},
        "segments": [
            {"segment_id": "approach-1", "kind": "APPROACH",
             "waypoints": [[0.0, 0.04, start_z, 0.0, 0.0, 0.0, 1.0]]},
            {"segment_id": "retract-1", "kind": "RETRACT",
             "waypoints": [[0.0, 0.04, start_z, 0.0, 0.0, 0.0, 1.0]]},
        ],
    }
    entry_policy = {
        "enabled": True,
        "tcp_clearance_above_top_range_m": [0.10, 0.12],
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
    }
    workcell = {
        "frame_id": "c2_base", "axis_xy_m": [0.0, 0.0], "radius_m": 0.03,
        "top_z_m": 0.20, "bottom_z_m": 0.05,
        "tool_offset_m": list(adapter.tool_offset_m),
        "outer_gap_m": 0.03, "slow_retract_gap_m": 0.005,
        "max_tip_inside_m": 0.005,
        "top": {"contact_offset_tool_m": [0.0, 0.0, 0.02]},
        "home": {"tcp_pose": [0.3, 0.0, 0.35, 0.0, 0.0, 0.0, 1.0],
                 "clearance_tcp_z_m": 0.30,
                 "position_tolerance_m": 0.001,
                 "angle_tolerance_rad": math.radians(1.0)},
        "entry_planning": entry_policy,
        "engraving_workspace": {"frame_id": "c2_base", "waypoint_min_z_m": 0.05},
    }
    context = ExecutionContext("run-1", "SIMULATION", threading.Event(), profiles, {})
    context.checked_tool_offset_m = list(adapter.tool_offset_m)
    context.checked_plan_signature = "plan-signature"
    limits = [(-355.0, 355.0), (-95.0, 95.0), (-135.0, 135.0),
              (-355.0, 355.0), (-135.0, 135.0), (-170.0, 170.0)]
    return adapter, execution_plan, workcell, profiles, context, limits


def test_plans_from_final_retract_without_motion_and_uses_measured_geometry():
    adapter, path, workcell, profiles, context, limits = fixture()

    result = plan_return_home_path(
        path, workcell, adapter, adapter.observe(), adapter.tool_offset_m,
        limits, 0.0, profiles, plan_signature="plan-signature",
        cancel=context.cancel)

    assert result.ok, result
    plan = result.observed_state["return_home_plan"]
    assert plan["expected_start_tip_pose"] == path["segments"][-1]["waypoints"][-1]
    assert plan["source_binding"]["axis_xy_m"] == workcell["axis_xy_m"]
    assert plan["source_binding"]["radius_m"] == workcell["radius_m"]
    assert plan["targets"][-1]["tip_pose"] == [0.3, -0.1, 0.35, 0.0, 0.0, 0.0, 1.0]
    assert adapter.moves == []


def test_return_reuses_predicted_end_and_joint_sequence():
    adapter, path, workcell, profiles, context, limits = fixture()

    result = plan_return_home_path(
        path, workcell, adapter, adapter.observe(), adapter.tool_offset_m,
        limits, 0.0, profiles, plan_signature="plan-signature",
        predicted_end_joints_deg=adapter.joints_deg, cancel=context.cancel)

    assert result.ok
    plan = result.observed_state["return_home_plan"]
    assert adapter.ik_calls == len(plan["validation_waypoints"])
    assert result.observed_state["ik_metrics"]["prefix_reused"] is True
    assert result.observed_state["ik_metrics"]["inverse_kinematics_calls"] == adapter.ik_calls


def test_executes_only_frozen_plan_and_rejects_mutation_or_wrong_start():
    adapter, path, workcell, profiles, context, limits = fixture()
    planned = plan_return_home_path(
        path, workcell, adapter, adapter.observe(), adapter.tool_offset_m,
        limits, 0.0, profiles, plan_signature="plan-signature",
        cancel=context.cancel)
    plan = planned.observed_state["return_home_plan"]
    adapter.pose = list(plan["expected_start_tip_pose"])

    executed = execute_return_home_plan(plan, adapter, context)

    assert executed.ok, executed
    assert adapter.moves == [target["tip_pose"] for target in plan["targets"]]
    assert executed.observed_state["return_home_plan_sha256"] == plan["return_home_plan_sha256"]

    changed = copy.deepcopy(plan)
    changed["targets"][0]["tip_pose"][2] += 0.001
    adapter2, *_ = fixture()
    adapter2.pose = list(plan["expected_start_tip_pose"])
    assert execute_return_home_plan(changed, adapter2, context).error_code == "PROFILE_MISMATCH"
    assert adapter2.moves == []

    adapter3, *_ = fixture()
    adapter3.pose = list(plan["expected_start_tip_pose"])
    adapter3.pose[0] += 0.01
    assert execute_return_home_plan(plan, adapter3, context).error_code == "ROBOT_STATE_CHANGED"
    assert adapter3.moves == []


def test_tool_tip_floor_failure_rejects_plan_without_motion():
    adapter, path, workcell, profiles, context, limits = fixture(start_z=0.04)

    result = plan_return_home_path(
        path, workcell, adapter, adapter.observe(), adapter.tool_offset_m,
        limits, 0.0, profiles, plan_signature="plan-signature",
        cancel=context.cancel)

    assert (result.outcome, result.error_code) == (
        "FAILED", "RETURN_HOME_PATH_UNAVAILABLE")
    assert adapter.moves == []


def test_prepared_flow_returns_home_only_after_successful_engraving():
    _, _, _, _, context, _ = fixture()
    calls = []
    phases = []

    def done(name):
        return lambda: calls.append(name) or StepResult("SUCCEEDED", observed_state={name: True})

    result = run_prepared_process(
        context, precheck=done("precheck"), enter=done("entry"),
        engrave=lambda _progress: calls.append("engrave") or StepResult(
            "SUCCEEDED", observed_state={"engraved": True,
                                         "last_completed_segment_id": "retract-1",
                                         "engraving_progress": 1.0}),
        return_home=done("return_home"), on_phase=phases.append)

    assert result.ok
    assert calls == ["precheck", "entry", "engrave", "return_home"]
    assert phases == ["PRECHECK", "ENTRY", "ENGRAVE", "RETURN_HOME", "FINISH"]
    assert result.observed_state["engrave"]["engraved"] is True
    assert result.observed_state["last_completed_segment_id"] == "retract-1"
    assert result.observed_state["engraving_progress"] == 1.0

    calls.clear()
    failed = run_prepared_process(
        context, precheck=done("precheck"), enter=done("entry"),
        engrave=lambda _progress: calls.append("engrave") or StepResult(
            "FAILED", "VALIDATION_FAILED"),
        return_home=done("return_home"))
    assert failed.outcome == "FAILED"
    assert calls == ["precheck", "entry", "engrave"]


def test_return_failure_blocks_finish_and_cancel_after_engraving_blocks_return():
    _, _, _, _, context, _ = fixture()
    calls = []
    phases = []
    failed = run_prepared_process(
        context,
        precheck=lambda: StepResult("SUCCEEDED"),
        enter=lambda: StepResult("SUCCEEDED"),
        engrave=lambda _progress: StepResult(
            "SUCCEEDED", observed_state={"last_completed_segment_id": "retract-1",
                                         "engraving_progress": 1.0}),
        return_home=lambda: calls.append("return_home") or StepResult(
            "FAILED", "VALIDATION_FAILED", "복귀 실패"),
        on_phase=phases.append)
    assert (failed.outcome, failed.error_code) == ("FAILED", "VALIDATION_FAILED")
    assert calls == ["return_home"]
    assert phases == ["PRECHECK", "ENTRY", "ENGRAVE", "RETURN_HOME"]
    assert failed.observed_state["last_completed_segment_id"] == "retract-1"
    assert failed.observed_state["engraving_progress"] == 1.0

    context.cancel.clear()
    calls.clear()

    def late_engraving_success(_progress):
        calls.append("engrave")
        context.cancel.set()
        return StepResult("SUCCEEDED")

    cancelled = run_prepared_process(
        context,
        precheck=lambda: StepResult("SUCCEEDED"),
        enter=lambda: StepResult("SUCCEEDED"),
        engrave=late_engraving_success,
        return_home=lambda: calls.append("return_home") or StepResult("SUCCEEDED"))
    assert (cancelled.outcome, cancelled.error_code) == ("UNKNOWN", "STOP_UNCONFIRMED")
    assert calls == ["engrave"]
