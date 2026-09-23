"""ROS/로봇 없이 node.py의 실제 함수 연결과 중복·정지를 확인한다."""

import hashlib
import copy
import json
import math
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from c2_process.engraving import ExecutionContext
from c2_process.node import (ExecutionInputs, ProcessCoordinator, RunJournal,
                             InputsUnavailable, load_execution_inputs,
                             make_asset_bundle_loader, make_hmi_asset_resolver,
                             prepared_binding_observation_valid,
                             read_real_execution_evidence)
from c2_process.preconditions import PreconditionEvidence, check_robot_status
from c2_process.robot_adapter import DoosanRobotAdapter, MockRobotAdapter, StepResult
from c2_process.tool_calibration import TipCalibration, measure_tool_tip, upright_quat



def fixture():
    adapter = MockRobotAdapter()
    context = ExecutionContext(
        run_id="run-1", source_mode="SIMULATION", cancel=threading.Event(),
        motion_profiles={}, tool_profile={},
    )
    calibration = TipCalibration(
        tool_id="engraving_drill", projection_m=0.06, lateral_x_m=0.0,
        offset_tool_m=[0.0, -0.06, 0.0], residual_rms_m=0.0,
        axis_fit_xy_m=[0.0, 0.0], side=1, z_m=0.1,
    )
    inputs = ExecutionInputs(
        path={"schema_version": 2, "config": {"profile_snapshot_id": "snapshot-1"}},
        path_bytes=b"{}", snapshot={}, snapshot_bytes=b"{}",
        evidence=PreconditionEvidence(runtime_mode="SIMULATION", robot_state=adapter.observe()),
        context=context, adapter=adapter, workcell={}, calibration_profiles={},
        calibration=calibration, calibration_snapshot_id="snapshot-1", tip_tolerance_m=0.001,
        joint_limits_deg=[(-360.0, 360.0)] * 6, j6_margin_deg=10.0,
    )
    goal = dict(schema_version=2, request_id="req-1", run_id="run-1", source_mode="SIMULATION",
                path_id="path-1", path_version=1, path_sha256="a" * 64)
    return goal, inputs


def test_connects_team_functions_in_order_and_deduplicates_request():
    goal, inputs = fixture()
    calls = []

    def precheck(*args, **kwargs):
        calls.append("precheck")
        assert args[5].robot_state.quality == "VALID"
        return StepResult("SUCCEEDED")

    def validate(path, context):
        calls.append("validate_path")
        return None

    def verify(adapter, workcell, profiles, calib, context, tol_m):
        calls.append("verify_tool_tip")
        assert calib.tool_id == "engraving_drill" and tol_m == 0.001
        return StepResult("SUCCEEDED", observed_state={"error_m": 0.0002})

    def engrave(path, context, progress, adapter):
        calls.append("execute_path")
        progress({"phase": "ENGRAVE", "engraving_progress": 0.5})
        return StepResult("SUCCEEDED", observed_state={"last_completed_segment_id": "cut-1"})

    coordinator = ProcessCoordinator(
        lambda _: inputs, precheck_fn=precheck, validate_engraving_fn=validate,
        verify_tip_fn=verify, engrave_fn=engrave,
    )
    result = coordinator.execute(goal, on_progress=lambda _: None)
    assert result.outcome == "SUCCEEDED"
    assert result.observed_state["tool_check"]["error_m"] == 0.0002
    assert calls == ["precheck", "validate_path", "verify_tool_tip", "execute_path"]
    assert coordinator.execute(goal) is result
    assert len(calls) == 4


def test_malformed_v2_path_is_rejected_before_tip_motion():
    goal, inputs = fixture()
    coordinator = ProcessCoordinator(
        lambda _: inputs, precheck_fn=lambda *args, **kwargs: StepResult("SUCCEEDED"),
        verify_tip_fn=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("tip moved")),
    )
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("FAILED", "INVALID_INPUT")


def test_missing_loader_fails_closed_and_same_request_is_not_retried():
    goal, _ = fixture()
    coordinator = ProcessCoordinator()
    first = coordinator.execute(goal)
    assert (first.outcome, first.error_code) == ("FAILED", "NOT_READY")
    assert coordinator.execute(goal) is first


def test_real_request_is_rejected_before_loading():
    goal, _ = fixture()
    goal["source_mode"] = "REAL"
    coordinator = ProcessCoordinator(lambda _: (_ for _ in ()).throw(AssertionError("loaded")))
    assert coordinator.execute(goal).error_code == "SOURCE_MODE_MISMATCH"


def test_stop_during_tool_check_does_not_start_engraving():
    goal, inputs = fixture()
    entered = threading.Event()
    release = threading.Event()
    output = []

    def verify(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return StepResult("SUCCEEDED")

    coordinator = ProcessCoordinator(
        lambda _: inputs, precheck_fn=lambda *args, **kwargs: StepResult("SUCCEEDED"),
        validate_engraving_fn=lambda *args: None, verify_tip_fn=verify,
        engrave_fn=lambda *args: (_ for _ in ()).throw(AssertionError("engraving started")),
    )
    worker = threading.Thread(target=lambda: output.append(coordinator.execute(goal)))
    worker.start()
    assert entered.wait(2)
    stopped = coordinator.stop("run-1")
    release.set()
    worker.join(timeout=2)
    assert stopped.accepted and stopped.stop_state == "ACCEPTED"
    assert (output[0].outcome, output[0].error_code) == ("STOPPED", "NONE")
    assert output[0].observed_state["stop_confirmed"] is True
    assert any(call["fn"] == "stop" for call in inputs.adapter.calls)


def test_stop_service_decision_does_not_wait_for_robot_confirmation():
    goal, inputs = fixture()
    entered = threading.Event()
    release_check = threading.Event()
    release_stop = threading.Event()
    output = []

    def verify(*args, **kwargs):
        entered.set()
        assert release_check.wait(2)
        return StepResult("STOPPED", "NONE", "동작 중단 확인", "tool_check")

    def delayed_stop(profile, deadline):
        assert release_stop.wait(2)
        return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "정지 확인 불가", "stop")

    inputs.adapter.stop = delayed_stop
    coordinator = ProcessCoordinator(
        lambda _: inputs, precheck_fn=lambda *args, **kwargs: StepResult("SUCCEEDED"),
        validate_engraving_fn=lambda *args: None, verify_tip_fn=verify,
    )
    worker = threading.Thread(target=lambda: output.append(coordinator.execute(goal)))
    worker.start()
    assert entered.wait(2)
    started = time.monotonic()
    decision = coordinator.stop("run-1")
    assert time.monotonic() - started < 0.2
    assert decision.accepted and decision.stop_state == "ACCEPTED"
    release_check.set()
    release_stop.set()
    worker.join(timeout=2)
    assert (output[0].outcome, output[0].error_code) == ("UNKNOWN", "STOP_UNCONFIRMED")


def _mock_candle_surface(projection_m):
    """실험 좌표의 복제가 아닌 모의 원통. 로봇 명령은 MockRobotAdapter에만 기록된다."""
    cx, cy, radius, side = 0.4224, -0.0026, 0.034, -1

    def surface(pose, _direction):
        dx = pose[0] - cx
        if abs(dx) > radius:
            return None
        y_surface = cy + side * math.sqrt(radius * radius - dx * dx)
        distance = side * (pose[1] - side * projection_m - y_surface)
        return max(0.0, distance)

    return surface


def _team_mock_inputs():
    """실제 사전 검사·도구 보정 함수 연결용 시험 입력. 승인된 현장 설정이 아니다."""
    from c2_process.tool_calibration import TipCalibration

    workcell = {"axis_xy_m": [0.4224, -0.0026], "radius_m": 0.034, "top_z_m": 0.2344}
    profiles = {"travel": {"id": "travel", "vel_mm_s": 26.0, "completion_timeout_s": 60.0},
                "tip_touch": {"touch_force_n": 0.8, "touch_speed_mm_s": 2.0}}
    adapter = MockRobotAdapter(surface_fn=_mock_candle_surface(0.0633))
    adapter.pose = [0.4221, -0.0026, 0.2644, *upright_quat(-1)]
    context = ExecutionContext(run_id="team-run", source_mode="SIMULATION", cancel=threading.Event(),
                               motion_profiles={"cut": {"completion_timeout_s": 30.0}},
                               tool_profile={"tool_id": "engraving_drill", "contact_mode": "force_touch",
                                             "clearance_m": 0.01, "touch_extra_m": 0.008,
                                             "touch_offset_range_m": [-0.003, 0.003]})
    measured = measure_tool_tip(adapter, workcell, profiles, context)
    assert measured.ok, measured
    calibration = TipCalibration(**measured.observed_state["calibration"])
    adapter.calls.clear()  # 3점 기준 측정은 실행 공정 밖의 준비 절차다.

    snapshot = {"profile_snapshot_id": "team-snapshot", "tool_id": "engraving_drill",
                "tool_version": 1, "frame_id": "c2_base"}
    snapshot_bytes = json.dumps(snapshot).encode()
    path = {"schema_version": 2, "path_id": "team-path", "path_version": 1,
            "source_mode": "SIMULATION", "frame_id": "c2_base", "tool_id": "engraving_drill",
            "position_unit": "m", "orientation": "quaternion_xyzw",
            "config": {"profile_snapshot_id": "team-snapshot",
                       "profile_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                       "tool_id": "engraving_drill", "tool_version": 1},
            "segments": [{"segment_id": "mock-cut", "kind": "CUT", "motion_profile_id": "cut",
                          "waypoints": [[0.5, 0.0, 0.25, *upright_quat(-1)],
                                        [0.501, 0.0, 0.25, *upright_quat(-1)]]}]}
    path_bytes = json.dumps(path).encode()
    path_sha256 = hashlib.sha256(path_bytes).hexdigest()
    now = time.monotonic()
    evidence = PreconditionEvidence(
        runtime_mode="SIMULATION", robot_state=adapter.observe(),
        control_authority_confirmed=True, stop_latched=False,
        path_validation_passed=True, j6_validation_passed=True,
        validation_path_sha256=path_sha256, profile_snapshot_id="team-snapshot",
        max_robot_state_age_s=2.0,
    )
    inputs = ExecutionInputs(path=path, path_bytes=path_bytes, snapshot=snapshot,
                             snapshot_bytes=snapshot_bytes, evidence=evidence, context=context,
                             adapter=adapter, workcell=workcell, calibration_profiles=profiles,
                             calibration=calibration, calibration_snapshot_id="team-snapshot",
                             tip_tolerance_m=0.001,
                             joint_limits_deg=[(-360.0, 360.0), (-95.0, 95.0), (-135.0, 135.0),
                                               (-360.0, 360.0), (-135.0, 135.0), (-360.0, 360.0)],
                             j6_margin_deg=10.0)
    goal = {"schema_version": 2, "request_id": "team-request", "run_id": "team-run",
            "source_mode": "SIMULATION", "path_id": "team-path", "path_version": 1,
            "path_sha256": path_sha256}
    return goal, inputs


def test_team_precheck_joint_check_and_tip_verifier_connect_to_mock_engraving():
    goal, inputs = _team_mock_inputs()
    called = []

    def engrave(_path, _context, _progress, _adapter):
        called.append("engrave")
        return StepResult("SUCCEEDED", "NONE", "모의 조각 완료", "execute_path")

    # v2 조각 검증·관절 검사는 팀원 실제 함수, 최종 조각 모션만 명시적으로 모의한다.
    coordinator = ProcessCoordinator(lambda _: inputs, engrave_fn=engrave)
    result = coordinator.execute(goal)
    assert result.ok, result
    assert called == ["engrave"]
    assert abs(result.observed_state["tool_check"]["error_m"]) < 0.001
    assert [call["fn"] for call in inputs.adapter.calls].count("probe_touch") == 1
    assert [call["fn"] for call in inputs.adapter.calls].count("ik") == 6


def test_test_only_team_path_runs_mock_integration():
    goal, inputs = _team_mock_inputs()
    snapshot = dict(inputs.snapshot, test_only=True)
    snapshot_bytes = json.dumps(snapshot).encode()
    path = dict(inputs.path, test_only=True)
    path["config"] = dict(path["config"], profile_sha256=hashlib.sha256(snapshot_bytes).hexdigest())
    path_bytes = json.dumps(path).encode()
    path_sha256 = hashlib.sha256(path_bytes).hexdigest()
    goal = dict(goal, path_sha256=path_sha256)
    evidence = replace(inputs.evidence, validation_path_sha256=path_sha256)
    inputs = replace(inputs, path=path, path_bytes=path_bytes, snapshot=snapshot,
                     snapshot_bytes=snapshot_bytes, evidence=evidence)
    coordinator = ProcessCoordinator(lambda _: inputs,
        engrave_fn=lambda *_: StepResult("SUCCEEDED", "NONE", "모의 조각 완료", "execute_path"))
    result = coordinator.execute(goal)
    assert result.ok, result
    assert [call["fn"] for call in inputs.adapter.calls].count("probe_touch") == 1


def test_simulation_rejects_non_mock_adapter_before_motion():
    goal, inputs = _team_mock_inputs()
    inputs = replace(inputs, adapter=object())
    coordinator = ProcessCoordinator(lambda _: inputs)
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("FAILED", "NOT_READY")


def test_team_tip_shift_blocks_mock_engraving():
    goal, inputs = _team_mock_inputs()
    inputs.adapter.surface_fn = _mock_candle_surface(0.0603)  # 고정 드릴 끝이 3 mm 밀린 모의 상황
    coordinator = ProcessCoordinator(
        lambda _: inputs,
        engrave_fn=lambda *_: (_ for _ in ()).throw(AssertionError("조각에 진입함")),
    )
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("FAILED", "VALIDATION_FAILED")
    assert abs(result.observed_state["error_m"] - 0.003) < 0.0005


def test_joint_check_failure_blocks_tip_motion_and_engraving():
    goal, inputs = _team_mock_inputs()
    inputs.adapter.ik_fail_at_call = 1
    coordinator = ProcessCoordinator(
        lambda _: inputs,
        engrave_fn=lambda *_: (_ for _ in ()).throw(AssertionError("조각에 진입함")),
    )
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("FAILED", "NOT_READY")
    assert [call["fn"] for call in inputs.adapter.calls].count("probe_touch") == 0


def test_missing_approved_joint_limits_blocks_tip_motion():
    goal, inputs = _team_mock_inputs()
    inputs = replace(inputs, joint_limits_deg=None)
    coordinator = ProcessCoordinator(lambda _: inputs,
        engrave_fn=lambda *_: (_ for _ in ()).throw(AssertionError("조각에 진입함")))
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("FAILED", "NOT_READY")
    assert [call["fn"] for call in inputs.adapter.calls].count("probe_touch") == 0


def test_journal_replays_result_after_coordinator_restart_without_motion(tmp_path):
    goal, inputs = fixture()
    path = tmp_path / "process-runs.sqlite3"
    calls = []
    coordinator = ProcessCoordinator(
        lambda _: inputs, journal=RunJournal(path),
        precheck_fn=lambda *_, **kwargs: StepResult("SUCCEEDED"),
        validate_engraving_fn=lambda *_: None,
        verify_tip_fn=lambda *args, **kwargs: StepResult("SUCCEEDED"),
        engrave_fn=lambda *_: (calls.append("engrave") or StepResult("SUCCEEDED")),
    )
    first = coordinator.execute(goal)
    assert first.ok and calls == ["engrave"]

    restarted = ProcessCoordinator(
        lambda _: (_ for _ in ()).throw(AssertionError("loader called again")), journal=RunJournal(path),
    )
    replay = restarted.execute(goal)
    assert replay.outcome == first.outcome and replay.error_code == first.error_code
    assert calls == ["engrave"]


def test_journal_blocks_reexecution_when_previous_result_was_not_recorded(tmp_path):
    goal, _ = fixture()
    journal = RunJournal(tmp_path / "process-runs.sqlite3")
    identity = (goal["run_id"], goal["source_mode"], goal["path_id"],
                goal["path_version"], goal["path_sha256"])
    assert journal.reserve(goal["request_id"], identity) is None
    coordinator = ProcessCoordinator(
        lambda _: (_ for _ in ()).throw(AssertionError("motion inputs loaded")), journal=RunJournal(journal.path),
    )
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("UNKNOWN", "STORAGE_ERROR")
    changed = dict(goal, path_sha256="b" * 64)
    assert coordinator.execute(changed).error_code == "REQUEST_CONFLICT"
    reused_run = dict(goal, request_id="req-other")
    assert coordinator.execute(reused_run).error_code == "RUN_MISMATCH"


def test_journal_reservation_failure_does_not_load_motion_inputs():
    goal, _ = fixture()

    class BrokenJournal:
        def reserve(self, *_):
            raise OSError("disk unavailable")

    coordinator = ProcessCoordinator(
        lambda _: (_ for _ in ()).throw(AssertionError("motion inputs loaded")), journal=BrokenJournal(),
    )
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("UNKNOWN", "STORAGE_ERROR")


class OfflineDoosanAdapter(DoosanRobotAdapter):
    """Doosan 인터페이스를 가진 시험 대역. ROS 생성·장비 연결은 하지 않는다."""
    def __init__(self, backing):
        self.backing = backing

    def observe(self):
        return self.backing.observe()

    def inverse_kinematics(self, *args):
        return self.backing.inverse_kinematics(*args)

    def stop(self, *args):
        return self.backing.stop(*args)

    def set_tool_offset(self, offset):
        self.backing.set_tool_offset(offset)

    def _read_tool_tcp(self):
        return ("GripperDA_v1", "ToolWeight_1")

    def initialize_controller(self):
        return StepResult("SUCCEEDED", "NONE", "시험 대역 제어기 초기화", "controller_initialization",
                          {"singularity_mode": 0, "already_initialized": False})


def real_fixture():
    goal, inputs = _team_mock_inputs()
    adapter = OfflineDoosanAdapter(inputs.adapter)
    path = dict(inputs.path, source_mode="REAL")
    path["config"] = dict(path["config"], tcp_profile_id="GripperDA_v1", load_profile_id="ToolWeight_1")
    path_bytes = json.dumps(path).encode()
    digest = hashlib.sha256(path_bytes).hexdigest()
    goal = dict(goal, source_mode="REAL", path_sha256=digest)
    inputs.context.source_mode = "REAL"
    # 시험용 근거다. 실제 현장 확인을 수행했다는 의미가 아니다.
    evidence = replace(inputs.evidence, runtime_mode="REAL", validation_path_sha256=digest,
        mounted_tool_id="engraving_drill", mount_confirmation_source="OPERATOR",
        mount_confirmed_at=time.monotonic(), gripper_closed_confirmed=True,
        gripper_confirmation_source="OPERATOR", gripper_confirmed_at=time.monotonic(),
        max_confirmation_age_s=10.0)
    inputs.context.tool_profile.update(touch_force_n=1.0, touch_speed_mm_s=1.0)
    inputs = replace(inputs, path=path, path_bytes=path_bytes, evidence=evidence, adapter=None)
    return goal, inputs, adapter


def test_real_adapter_is_bound_to_all_team_calls_and_journal_replays(tmp_path):
    goal, inputs, adapter = real_fixture()
    calls = []
    def verify(ad, *args, **kwargs):
        assert ad is adapter
        assert ad.backing.tool_offset_m == inputs.calibration.offset_tool_m
        calls.append("verify")
        return StepResult("SUCCEEDED")
    def start(path, ad, context):
        assert ad is adapter and context.source_mode == "REAL"
        calls.append("start")
        return StepResult("SUCCEEDED")
    def engrave(path, context, progress, ad):
        assert ad is adapter
        calls.append("engrave")
        return StepResult("SUCCEEDED", observed_state={"last_completed_segment_id": "cut-1"})
    def home(ad, context):
        assert ad is adapter
        calls.append("home")
        return StepResult("SUCCEEDED", observed_state={"arrived": True})
    coordinator = ProcessCoordinator(lambda _: inputs, runtime_mode="REAL", real_adapter=adapter,
        journal=RunJournal(tmp_path / "runs.sqlite3"), verify_tip_fn=verify,
        go_to_path_start_fn=start, engrave_fn=engrave, return_home_fn=home)
    result = coordinator.execute(goal)
    assert result.ok, result
    assert calls == ["verify", "start", "engrave", "home"]
    assert any(c["fn"] == "ik" for c in adapter.backing.calls)
    assert result.observed_state["return_home"]["arrived"] is True
    assert coordinator.execute(goal) is result
    assert len(calls) == 4


def test_real_connection_rejects_missing_dependencies_and_mock_adapter(tmp_path):
    import pytest
    goal, inputs, adapter = real_fixture()
    journal = RunJournal(tmp_path / "runs.sqlite3")
    base = dict(runtime_mode="REAL", real_adapter=adapter, journal=journal,
        go_to_path_start_fn=lambda *a: StepResult("SUCCEEDED"),
        return_home_fn=lambda *a: StepResult("SUCCEEDED"))
    for changed in ({"real_adapter": MockRobotAdapter()}, {"journal": None},
                    {"go_to_path_start_fn": None}, {"return_home_fn": None}):
        with pytest.raises(ValueError):
            ProcessCoordinator(lambda _: inputs, **dict(base, **changed))
    with pytest.raises(ValueError):
        ProcessCoordinator(**base)  # 기본 로더 누락
    with pytest.raises(ValueError):
        ProcessCoordinator(lambda _: inputs, real_adapter=adapter)  # SIMULATION 혼입


def test_real_loader_cannot_swap_bound_adapter(tmp_path):
    goal, inputs, adapter = real_fixture()
    inputs = replace(inputs, adapter=MockRobotAdapter())
    coordinator = ProcessCoordinator(lambda _: inputs, runtime_mode="REAL", real_adapter=adapter,
        journal=RunJournal(tmp_path / "runs.sqlite3"),
        go_to_path_start_fn=lambda *a: StepResult("SUCCEEDED"),
        return_home_fn=lambda *a: StepResult("SUCCEEDED"))
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("FAILED", "NOT_READY")
    assert adapter.backing.calls == []


def test_real_stop_fallback_confirms_after_non_motion_callback_returns(tmp_path):
    goal, inputs, adapter = real_fixture()
    entered = threading.Event()
    output, stop_threads = [], []
    def verify(ad, workcell, profiles, calibration, context, **kwargs):
        entered.set()
        assert context.cancel.wait(2)
        return StepResult("STOPPED")
    def stop(profile, timeout):
        stop_threads.append(threading.get_ident())
        return StepResult("SUCCEEDED")
    adapter.stop = stop
    coordinator = ProcessCoordinator(lambda _: inputs, runtime_mode="REAL", real_adapter=adapter,
        journal=RunJournal(tmp_path / "runs.sqlite3"), verify_tip_fn=verify,
        go_to_path_start_fn=lambda *a: (_ for _ in ()).throw(AssertionError("start ran")),
        return_home_fn=lambda *a: (_ for _ in ()).throw(AssertionError("home ran")))
    worker = threading.Thread(target=lambda: output.append(coordinator.execute(goal)))
    worker.start()
    assert entered.wait(2)
    assert coordinator.stop(goal["run_id"]).accepted
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert output[0].outcome == "STOPPED"
    assert stop_threads == [worker.ident]


def test_real_tcp_mismatch_blocks_tip_and_engraving(tmp_path):
    goal, inputs, adapter = real_fixture()
    adapter._read_tool_tcp = lambda: ("wrong-tcp", "ToolWeight_1")
    coordinator = ProcessCoordinator(lambda _: inputs, runtime_mode="REAL", real_adapter=adapter,
        journal=RunJournal(tmp_path / "runs.sqlite3"),
        verify_tip_fn=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("tip ran")),
        go_to_path_start_fn=lambda *a: StepResult("SUCCEEDED"),
        return_home_fn=lambda *a: StepResult("SUCCEEDED"))
    result = coordinator.execute(goal)
    assert (result.outcome, result.error_code) == ("FAILED", "PROFILE_MISMATCH")
    assert result.observed_state["tcp"] == "wrong-tcp"


# 9/20 파일·함수 부분 통합: 아래 스냅샷 배치는 시험 fixture 전용이다.
# 팀의 최종 스냅샷 스키마 또는 실기 설정을 정의하지 않는다.
import copy
import pytest
from dataclasses import asdict
from c2_process.node import build_execution_settings
from c2_process.engraving import execute_path, validate_path
from c2_process.joint_check import check_path_joints
from c2_process.tool_calibration import verify_tool_tip


def _file_integration(tmp_path):
    goal, inputs = _team_mock_inputs()
    ad = inputs.adapter
    cx, cy = inputs.workcell['axis_xy_m']
    radius = inputs.workcell['radius_m']
    z = inputs.calibration.z_m
    q = upright_quat(-1)
    sy = cy - radius
    points = [[cx + dx, cy - math.sqrt(radius**2 - dx**2), z, *q] for dx in (0, .001, .002)]
    path = copy.deepcopy(inputs.path)
    path['test_only'] = True
    path['validation'] = {
        'report_id': 'test-report',
        'passed': True,
        'checks': [{'code': 'GEOMETRY', 'passed': True}],
        'not_checked': ['IK', 'JOINT_LIMITS', 'J6_RANGE'],
    }
    path['segments'] = [
        dict(segment_id='approach', kind='APPROACH', motion_profile_id='approach',
             waypoints=[[cx, sy-.01, z, *q]]),
        dict(segment_id='cut', kind='CUT', motion_profile_id='cut', stroke_id='s', waypoints=points),
        dict(segment_id='retract', kind='RETRACT', motion_profile_id='retract',
             waypoints=[[points[-1][0], sy-.01, z, *q]]),
    ]
    motion = {name: {'id': name, 'vel_mm_s': 5., 'completion_timeout_s': 30.}
              for name in ('approach', 'cut', 'retract')}
    tool = dict(inputs.context.tool_profile, touch_force_n=.8, touch_speed_mm_s=1.5)
    snapshot = dict(inputs.snapshot, test_only=True, test_execution={
        'workcell': inputs.workcell, 'calibration_profiles': inputs.calibration_profiles,
        'calibration': asdict(inputs.calibration), 'motion_profiles': motion, 'tool_profile': tool,
        'stop_profile': {'mode': 2, 'confirmation_timeout_s': 2.},
        'tip_tolerance_m': inputs.tip_tolerance_m, 'joint_limits_deg': inputs.joint_limits_deg,
        'j6_margin_deg': inputs.j6_margin_deg})
    files = {name: tmp_path / (name + '.json') for name in ('path', 'result', 'snapshot')}
    files['snapshot'].write_text(json.dumps(snapshot, indent=2))
    path['config']['profile_sha256'] = hashlib.sha256(files['snapshot'].read_bytes()).hexdigest()
    files['path'].write_text(json.dumps(path, indent=2))
    digest = hashlib.sha256(files['path'].read_bytes()).hexdigest()
    goal = dict(goal, path_sha256=digest)
    result = dict(success=True, error_code='NONE', path_id=path['path_id'], path_version=path['path_version'],
                  path_sha256=digest, validation_passed=True, validation_report_id='test-report')
    files['result'].write_text(json.dumps(result))
    def resolve(snapshot, goal, snapshot_id):
        data = snapshot['test_execution']
        return build_execution_settings(goal,
            evidence=replace(inputs.evidence, path_validation_passed=False, validation_path_sha256=''),
            motion_profiles=data['motion_profiles'], tool_profile=data['tool_profile'],
            stop_profile=data['stop_profile'],
            adapter=ad, workcell=data['workcell'], calibration_profiles=data['calibration_profiles'],
            calibration_record=data['calibration'],
            calibration_snapshot_id=snapshot_id,
            tip_tolerance_m=data['tip_tolerance_m'], joint_limits_deg=data['joint_limits_deg'],
            j6_margin_deg=data['j6_margin_deg'])
    def loader(g):
        return load_execution_inputs(g, path_file=files['path'], result_file=files['result'],
                                     snapshot_file=files['snapshot'], resolve_settings=resolve)
    # MockRobotAdapter의 표면 모형도 현재 좌표 의미(패드/도구 끝)에 맞춘다.
    pad_surface = ad.surface_fn
    def surface(pose, direction):
        if ad.tool_offset_m is None:
            return pad_surface(pose, direction)
        dx = pose[0] - cx
        if abs(dx) > radius:
            return None
        return max(0., (cy - math.sqrt(radius**2-dx**2)) - pose[1])
    ad.surface_fn = surface
    return goal, loader, ad, files


def test_files_connect_all_four_real_python_functions_on_one_mock_adapter(tmp_path):
    goal, loader, ad, files = _file_integration(tmp_path)
    seen, phases, identities = [], [], {}
    def validate(path, context):
        seen.append('validate'); identities['path'] = copy.deepcopy(path); identities['ctx'] = context
        return validate_path(path, context)
    def joints(path, adapter, offset, ref, **kw):
        seen.append('joints'); assert adapter is ad
        assert path["inspection_scope"] == "BOUNDED_FORCE_TOUCH_CANDIDATES"
        assert path["config"] == json.loads(files["path"].read_bytes())["config"]
        return check_path_joints(path, adapter, offset, ref, **kw)
    def tip(adapter, workcell, profiles, calibration, context, **kw):
        seen.append('tip'); assert adapter is ad and context is identities['ctx']
        result = verify_tool_tip(adapter, workcell, profiles, calibration, context, **kw)
        assert ad.tool_offset_m == calibration.offset_tool_m
        return result
    def engrave(path, context, progress, adapter):
        seen.append('engrave'); assert adapter is ad and context is identities['ctx']
        assert path == identities['path']
        return execute_path(path, context, progress, adapter)
    def start(path, adapter, context):
        assert adapter is ad and path == identities['path'] and context is identities['ctx']
        seen.append('start_callback'); return StepResult('SUCCEEDED')
    def home(adapter, context):
        assert adapter is ad and context is identities['ctx']
        seen.append('home_callback'); return StepResult('SUCCEEDED')  # 모션 없는 계약 대역
    coordinator = ProcessCoordinator(loader, joint_check_fn=joints, validate_engraving_fn=validate,
        verify_tip_fn=tip, engrave_fn=engrave, go_to_path_start_fn=start, return_home_fn=home)
    result = coordinator.execute(goal, on_phase=phases.append, on_progress=lambda _: None)
    assert result.ok, result
    assert seen == ['joints', 'validate', 'tip', 'start_callback', 'engrave', 'home_callback']
    assert result.observed_state['last_completed_segment_id'] == 'retract'
    assert any(c['fn'] == 'move_spline' for c in ad.calls)
    assert phases == ['PRECHECK', 'TOOL_CHECK', 'APPROACH', 'RETRACT', 'FINISH']
    previous = list(ad.calls)
    assert coordinator.execute(goal) is result
    assert ad.calls == previous  # 중복 요청으로 파일/모션 재실행 없음


@pytest.mark.parametrize('case,code', [
    ('schema_v1', 'UNSUPPORTED_SCHEMA_VERSION'), ('path_bytes', 'PATH_MISMATCH'),
    ('snapshot_bytes', 'PROFILE_MISMATCH'), ('path_id', 'PATH_MISMATCH'),
    ('path_version', 'PATH_MISMATCH'), ('result_hash', 'PATH_MISMATCH'),
    ('result_failed', 'VALIDATION_UNAVAILABLE'), ('result_validation', 'VALIDATION_UNAVAILABLE'),
    ('report_id', 'VALIDATION_UNAVAILABLE'), ('snapshot_id', 'PROFILE_MISMATCH'),
    ('tool_version', 'PROFILE_MISMATCH'), ('missing_file', 'NOT_READY'),
    ('invalid_json', 'INVALID_INPUT'), ('duplicate_json_key', 'INVALID_INPUT'),
    ('missing_mapper', 'NOT_READY'),
])
def test_file_failures_block_settings_and_all_motion(tmp_path, case, code):
    goal, _, ad, files = _file_integration(tmp_path)
    path = json.loads(files['path'].read_bytes()); result = json.loads(files['result'].read_bytes())
    snapshot = json.loads(files['snapshot'].read_bytes())
    if case == 'schema_v1': path['schema_version'] = 1
    elif case == 'path_id': result['path_id'] = 'other'
    elif case == 'path_version': result['path_version'] += 1
    elif case == 'result_hash': result['path_sha256'] = '0'*64
    elif case == 'result_failed': result['success'] = False
    elif case == 'result_validation': result['validation_passed'] = False
    elif case == 'report_id': result['validation_report_id'] = 'other'
    elif case == 'snapshot_id': snapshot['profile_snapshot_id'] = 'other'
    elif case == 'tool_version': snapshot['tool_version'] = 2
    files['snapshot'].write_text(json.dumps(snapshot))
    path['config']['profile_sha256'] = hashlib.sha256(files['snapshot'].read_bytes()).hexdigest()
    files['path'].write_text(json.dumps(path))
    goal['path_sha256'] = hashlib.sha256(files['path'].read_bytes()).hexdigest()
    if case != 'result_hash': result['path_sha256'] = goal['path_sha256']
    files['result'].write_text(json.dumps(result))
    if case == 'path_bytes': files['path'].write_bytes(files['path'].read_bytes()+b' ')
    elif case == 'snapshot_bytes': files['snapshot'].write_bytes(files['snapshot'].read_bytes()+b' ')
    elif case == 'missing_file': files['result'].unlink()
    elif case == 'invalid_json': files['result'].write_text('{')
    elif case == 'duplicate_json_key': files['result'].write_text('{"success":true,"success":false}')
    def forbidden(*_): raise AssertionError('설정 매퍼에 진입함')
    def loader(g):
        return load_execution_inputs(g, path_file=files['path'], result_file=files['result'],
            snapshot_file=files['snapshot'], resolve_settings=None if case=='missing_mapper' else forbidden)
    r = ProcessCoordinator(loader).execute(goal)
    assert (r.outcome, r.error_code) == ('FAILED', code), r
    assert ad.calls == []


@pytest.mark.parametrize('case', ['ik', 'j5', 'j6', 'nan', 'infinity', 'short'])
def test_file_integration_joint_rejection_stops_before_touch(tmp_path, case):
    goal, loader, ad, _ = _file_integration(tmp_path)
    if case == 'ik': ad.ik_fail_at_call = 1
    elif case in ('nan', 'infinity', 'short'):
        values = {'nan': [0., 0., 0., 0., float('nan'), 0.],
                  'infinity': [0., 0., 0., 0., 0., float('inf')], 'short': [0.] * 5}
        ad.inverse_kinematics = lambda *_: values[case]
    elif case == 'j5':
        ad.inverse_kinematics = lambda *_: [0., 0., 0., 0., 175., 0.]
    else:
        observe = ad.observe
        ad.observe = lambda: replace(observe(), joints_rad=[0., 0., 0., 0., 0., math.radians(340.)])
        ad.inverse_kinematics = lambda *_: [0., 0., 0., 0., 0., 355.]
    called=[]
    coordinator = ProcessCoordinator(loader, go_to_path_start_fn=lambda *_: called.append('start'),
                                      return_home_fn=lambda *_: called.append('home'))
    r=coordinator.execute(goal)
    invalid = case in ('nan', 'infinity', 'short')
    assert r.outcome == ('UNKNOWN' if invalid else 'FAILED'), r
    assert r.error_code == ('VALIDATION_UNAVAILABLE' if invalid else
                            'NOT_READY' if case == 'ik' else 'VALIDATION_FAILED')
    assert not any(c['fn'] in ('move','move_spline','probe_touch') for c in ad.calls)
    assert called == []


@pytest.mark.parametrize('case,outcome,code', [
    ('tip_failure','FAILED','VALIDATION_FAILED'), ('tip_timeout','UNKNOWN','TIMEOUT'),
    ('tip_retreat','FAILED','NOT_READY'), ('cut_timeout','UNKNOWN','TIMEOUT'),
    ('path_retract','FAILED','NOT_READY')])
def test_team_function_failures_block_later_motion(tmp_path, case, outcome, code):
    goal, loader, ad, _ = _file_integration(tmp_path)
    original_touch, original_move, original_spline = ad.probe_touch, ad.move, ad.move_spline
    calls=[]; travel_count=0
    def touch(*args):
        calls.append('touch')
        if len([x for x in calls if x=='touch'])==1:
            if case=='tip_failure': return StepResult('FAILED','VALIDATION_FAILED')
            if case=='tip_timeout': return StepResult('UNKNOWN','TIMEOUT')
        return original_touch(*args)
    def move(pose, frame, profile, timeout, cancel):
        nonlocal travel_count
        pid=profile.get('id'); calls.append(pid)
        if pid=='travel':
            travel_count+=1
            if case=='tip_retreat' and travel_count==4: return StepResult('FAILED','NOT_READY')
        if case=='path_retract' and pid=='retract': return StepResult('FAILED','NOT_READY')
        return original_move(pose,frame,profile,timeout,cancel)
    def spline(*args):
        calls.append('spline')
        if case=='cut_timeout': return StepResult('UNKNOWN','TIMEOUT')
        return original_spline(*args)
    ad.probe_touch,ad.move,ad.move_spline=touch,move,spline
    def start(*_): calls.append('start'); return StepResult('SUCCEEDED')
    def home(*_): calls.append('home'); return StepResult('SUCCEEDED')
    phases=[]
    r=ProcessCoordinator(loader,go_to_path_start_fn=start,return_home_fn=home).execute(goal,on_phase=phases.append)
    assert (r.outcome,r.error_code)==(outcome,code),r
    assert 'home' not in calls and 'FINISH' not in phases
    if case.startswith('tip'): assert 'start' not in calls and 'cut' not in calls
    if case=='cut_timeout': assert 'retract' not in calls
    if case=='path_retract': assert calls[-1]=='retract'


@pytest.mark.parametrize('confirmed', [True, False])
def test_stop_during_actual_engraving_distinguishes_acceptance_and_confirmation(tmp_path, confirmed):
    goal,loader,ad,_=_file_integration(tmp_path)
    entered=threading.Event(); stop_entered=threading.Event(); release_stop=threading.Event()
    output=[]; transitions=[]
    original=ad.move_spline
    def spline(poses,frame,profile,timeout,cancel):
        entered.set()
        assert cancel.wait(2)
        return original(poses,frame,profile,timeout,cancel)
    def stop(*_):
        stop_entered.set(); assert release_stop.wait(2)
        return StepResult('SUCCEEDED') if confirmed else StepResult('UNKNOWN','STOP_UNCONFIRMED')
    ad.move_spline,ad.stop=spline,stop
    def start(*_): transitions.append('start'); return StepResult('SUCCEEDED')
    def home(*_): transitions.append('home'); return StepResult('SUCCEEDED')
    coordinator=ProcessCoordinator(loader,go_to_path_start_fn=start,return_home_fn=home)
    worker=threading.Thread(target=lambda:output.append(coordinator.execute(goal)))
    worker.start()
    try:
        assert entered.wait(2)
        decision=coordinator.stop(goal['run_id'])
        assert decision.accepted and decision.stop_state=='ACCEPTED'
        assert stop_entered.wait(2)
        assert output==[]  # 접수는 됐지만 정지 확인 결과는 아직 없음
    finally:
        release_stop.set(); worker.join(3)
    assert not worker.is_alive()
    assert output[0].outcome==('STOPPED' if confirmed else 'UNKNOWN'),output
    if not confirmed: assert output[0].error_code=='STOP_UNCONFIRMED'
    assert transitions==['start']
    assert not any(c.get('profile')=='retract' for c in ad.calls)


def test_loader_keeps_unconfirmed_runtime_evidence_unconfirmed(tmp_path):
    goal, loader, ad, files = _file_integration(tmp_path)
    bound = loader(goal)
    def resolve(snapshot, request, snapshot_id):
        fields = {key: getattr(bound, key) for key in (
            'evidence','context','adapter','workcell','calibration_profiles','calibration',
            'calibration_snapshot_id','tip_tolerance_m','joint_limits_deg','j6_margin_deg')}
        fields['evidence'] = replace(bound.evidence, control_authority_confirmed=False,
                                    stop_latched=None)
        return fields
    def unresolved(g):
        return load_execution_inputs(g,path_file=files['path'],result_file=files['result'],
                                     snapshot_file=files['snapshot'],resolve_settings=resolve)
    loaded=unresolved(goal)
    assert not loaded.evidence.control_authority_confirmed
    assert loaded.evidence.stop_latched is None
    assert loaded.evidence.mount_confirmation_source=='UNKNOWN'
    assert not loaded.evidence.gripper_closed_confirmed
    result=ProcessCoordinator(unresolved).execute(goal)
    assert result.error_code=='NOT_READY'
    assert ad.calls==[]


def test_repository_heart_original_is_not_silently_repaired(tmp_path):
    # c2_path가 보낸 실제 원본을 읽는다. 파일 플래그/해시를 수정하지 않는다.
    samples = Path(__file__).resolve().parents[2] / 'c2_path/samples/heart'
    if not samples.is_dir(): pytest.skip('c2_path 샘플 미제공')
    raw=(samples/'path.json').read_bytes(); path=json.loads(raw)
    result=json.loads((samples/'result.json').read_bytes())
    assert hashlib.sha256(raw).hexdigest()==result['path_sha256']
    assert path['source_mode']=='SIMULATION' and path['test_only'] is True
    # 현재 원본의 스냅샷 해시는 자리표시자. 가짜 파일로 대조 통과시키지 않는다.
    snapshot=tmp_path/'snapshot.json'; snapshot.write_text('{}')
    goal=dict(schema_version=2,request_id='original',run_id='original',source_mode='SIMULATION',
              path_id=path['path_id'],path_version=path['path_version'],path_sha256=result['path_sha256'])
    coordinator=ProcessCoordinator(lambda g:load_execution_inputs(g,path_file=samples/'path.json',
        result_file=samples/'result.json',snapshot_file=snapshot))
    r=coordinator.execute(goal)
    assert r.error_code=='PROFILE_MISMATCH'
    assert (samples/'path.json').read_bytes()==raw


@pytest.mark.parametrize("outcome,cancel_requested,expected", [
    ("SUCCEEDED", False, "succeed"),
    ("FAILED", False, "abort"),
    ("FAILED", True, "abort"),
    ("STOPPED", False, "abort"),   # StopProcess 서비스 중단
    ("STOPPED", True, "canceled"), # 수락된 Action 취소 + 정지 확인
    ("UNKNOWN", False, "abort"),
    ("UNKNOWN", True, "abort"),    # 취소 요청이 있어도 정지 미확인은 UNKNOWN
])
def test_ros_terminal_state_preserves_process_outcome(outcome, cancel_requested, expected):
    from c2_process.node import _finish_action
    class Handle:
        is_cancel_requested = cancel_requested
        def __init__(self): self.calls = []
        def succeed(self): self.calls.append("succeed")
        def canceled(self): self.calls.append("canceled")
        def abort(self): self.calls.append("abort")
    handle = Handle()
    result = StepResult(outcome, "STOP_UNCONFIRMED" if outcome == "UNKNOWN" else "NONE")
    before = asdict(result)
    _finish_action(handle, result)
    assert handle.calls == [expected]
    assert asdict(result) == before  # ROS 종료 방식으로 도메인 STOPPED/UNKNOWN을 바꾸지 않음


def test_overlapping_stop_and_cancel_finish_action_once():
    from c2_process.node import _finish_action
    from types import SimpleNamespace
    goal, inputs = fixture()
    entered = threading.Event()
    output, terminals = [], []
    def verify(*args, **kwargs):
        entered.set()
        assert inputs.context.cancel.wait(2)
        assert release.wait(2)
        return StepResult("STOPPED")
    release = threading.Event()
    coordinator = ProcessCoordinator(lambda _: inputs,
        precheck_fn=lambda *a, **kw: StepResult("SUCCEEDED"),
        validate_engraving_fn=lambda *a: None, verify_tip_fn=verify,
        engrave_fn=lambda *a: (_ for _ in ()).throw(AssertionError("조각 진입")))
    handle = SimpleNamespace(is_cancel_requested=False,
        succeed=lambda: terminals.append("succeed"),
        canceled=lambda: terminals.append("canceled"),
        abort=lambda: terminals.append("abort"))
    def execute():
        result = coordinator.execute(goal)
        _finish_action(handle, result)
        output.append(result)
    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(2)
        assert coordinator.stop(goal["run_id"]).accepted  # StopProcess
        assert coordinator.stop(goal["run_id"]).accepted  # Action cancel도 같은 정지 처리 사용
        handle.is_cancel_requested = True  # ROS가 취소를 수락한 상태의 대역
        assert terminals == []  # 요청 수락 시점에는 종료하지 않음
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert output[0].outcome == "STOPPED"
    assert terminals == ["canceled"]


@pytest.mark.parametrize("case", ["missing_calibration", "offset_mismatch", "bad_radius",
                                  "nan_speed", "no_travel", "no_tolerance", "bad_limits"])
def test_settings_reject_invalid_data_before_motion(tmp_path, case):
    goal, loader, ad, files = _file_integration(tmp_path)
    inputs = loader(goal)
    snapshot = json.loads(files['snapshot'].read_bytes())
    data = snapshot['test_execution']
    if case == 'missing_calibration': del data['calibration']['projection_m']
    elif case == 'offset_mismatch': data['calibration']['offset_tool_m'][1] = -.04
    elif case == 'bad_radius': data['workcell']['radius_m'] = -1
    elif case == 'nan_speed': data['motion_profiles']['cut']['vel_mm_s'] = float('nan')
    elif case == 'no_travel': data['calibration_profiles'].pop('travel')
    elif case == 'no_tolerance': data['tip_tolerance_m'] = None
    elif case == 'bad_limits': data['joint_limits_deg'][4] = [135, -135]
    before = list(inputs.adapter.calls)
    with pytest.raises(InputsUnavailable) as error:
        build_execution_settings(goal, evidence=inputs.evidence, adapter=inputs.adapter,
            calibration_snapshot_id=snapshot['profile_snapshot_id'],
            calibration_record=data.pop('calibration'), **data)
    assert error.value.error_code == 'INVALID_INPUT'
    assert inputs.adapter.calls == before


def test_settings_isolate_requests_and_preserve_unconfirmed_evidence(tmp_path):
    goal, loader, ad, files = _file_integration(tmp_path)
    inputs = loader(goal)
    first = loader(goal)
    second = loader(dict(goal, run_id='another-run'))
    assert first.adapter is second.adapter is inputs.adapter
    assert first.context.cancel is not second.context.cancel
    first.context.cancel.set()
    assert not second.context.cancel.is_set()
    first.context.motion_profiles['cut']['vel_mm_s'] = 999
    first.calibration.offset_tool_m[0] = 999
    assert second.context.motion_profiles['cut']['vel_mm_s'] == 5
    assert second.calibration.offset_tool_m[0] != 999
    assert first.evidence.mount_confirmation_source == inputs.evidence.mount_confirmation_source
    assert first.evidence.gripper_closed_confirmed == inputs.evidence.gripper_closed_confirmed
    assert first.context.run_id == goal['run_id']
    assert second.context.run_id == 'another-run'


from c2_process.node import ObservationCache, ProcessAlarms
from c2_process.robot_adapter import RobotState, apply_tool_offset


def test_observation_stamp_stays_at_query_time_and_expires():
    cache = ObservationCache()
    state = RobotState(joints_rad=[0.] * 6, tcp_pose=[.1,.2,.3,0.,0.,0.,1.],
                       robot_state=1, frame_id='c2_base', quality='VALID', measured_at=10.)
    cache.capture(state, None, 2., now=10.5, utc_ns=100_500_000_000)
    first = cache.values(now=11.)
    assert first['joints_quality'] == first['tcp_quality'] == 'VALID'
    assert first['robot_connection_state'] == 'CONNECTED'
    assert first['joints_stamp_ns'] == 100_000_000_000
    state.joints_rad[0] = 99  # cache is a snapshot
    stale = cache.values(now=12.1)
    assert stale['joints_quality'] == stale['tcp_quality'] == stale['robot_quality'] == 'STALE'
    assert stale['joints_stamp_ns'] == first['joints_stamp_ns']
    assert stale['joints'][0] == 0
    assert stale['robot_connection_state'] == 'UNKNOWN'


def test_prepared_binding_observation_requires_fresh_authority_and_robot():
    from types import SimpleNamespace as NS
    ready = NS(active=True, connected=True, valid=True, has_control=True)
    owner = NS(cache=NS(fresh=lambda: ready))
    values = dict(robot_connection_state='CONNECTED', robot_quality='VALID',
                  robot_state_code=1)
    assert prepared_binding_observation_valid(values, owner)
    assert not prepared_binding_observation_valid(
        dict(values, robot_connection_state='UNKNOWN'), owner)
    assert not prepared_binding_observation_valid(
        dict(values, robot_quality='STALE'), owner)
    owner.cache.fresh = lambda: None
    assert not prepared_binding_observation_valid(values, owner)


@pytest.mark.parametrize('state_code', [3, 5, 6, 9, 10])
def test_prepared_binding_observation_rejects_confirmed_stop_states(state_code):
    from types import SimpleNamespace as NS
    authority = NS(active=True, connected=True, valid=True, has_control=True)
    owner = NS(cache=NS(fresh=lambda: authority))
    values = dict(robot_connection_state='CONNECTED', robot_quality='VALID',
                  robot_state_code=state_code)
    assert not prepared_binding_observation_valid(values, owner)


def test_real_execution_evidence_reads_fresh_authority_stop_and_robot_state():
    from types import SimpleNamespace as NS
    authority=NS(active=True,connected=True,valid=True,has_control=True)
    owner=NS(cache=NS(max_age_s=.5,fresh=lambda: authority),
             stop_latched=lambda _context: False)
    node=NS(real_preparation_observations=owner)

    evidence=read_real_execution_evidence(node,'real-profile')

    assert evidence.runtime_mode=='REAL'
    assert evidence.profile_snapshot_id=='real-profile'
    assert evidence.control_authority_confirmed is True
    assert evidence.stop_latched is False
    assert evidence.max_robot_state_age_s==.5
    assert evidence.robot_state is None


@pytest.mark.parametrize('authority,stopped', [(None,False),
    (type('Authority',(),dict(active=True,connected=True,valid=True,has_control=True))(),None),
    (type('Authority',(),dict(active=True,connected=True,valid=True,has_control=True))(),True)])
def test_real_execution_evidence_does_not_invent_missing_or_stopped_readiness(authority,stopped):
    from types import SimpleNamespace as NS
    owner=NS(cache=NS(max_age_s=.5,fresh=lambda:authority),
             stop_latched=lambda _context:stopped)
    evidence=read_real_execution_evidence(
        NS(real_preparation_observations=owner),'real-profile')

    checked=check_robot_status(evidence)

    assert not checked.ok and checked.error_code=='NOT_READY'


def test_observation_tip_is_converted_to_controller_tcp():
    cache = ObservationCache()
    pad = [.42, .001, .264, *upright_quat(-1)]
    offset = [.00085, -.09955, 0.]
    tip = apply_tool_offset(pad, offset)
    state = RobotState(tcp_pose=tip, frame_id='c2_base', quality='VALID', measured_at=10.)
    cache.capture(state, offset, 2., now=10., utc_ns=100_000_000_000)
    assert cache.values(now=10.)['tcp_pose'] == pytest.approx(pad)


def test_measurement_observation_updates_same_cache_and_keeps_measurement_time():
    cache = ObservationCache()
    offset = [.00085, -.09955, 0.]
    tip = [.42, .001, .16445, 0., 0., 0., 1.]
    cache.capture_measurement(dict(
        tip_pose=tip, joints_rad=[.1] * 6, measured_at_monotonic_s=10.,
        frame_id='c2_base', quality='VALID', robot_state=2), offset, 2.,
        now=10.25, utc_ns=100_250_000_000)
    values = cache.values(now=10.5)
    assert values['joints_quality'] == values['tcp_quality'] == 'VALID'
    assert values['joints_stamp_ns'] == values['tcp_stamp_ns'] == 100_000_000_000
    assert values['tcp_pose'] == pytest.approx(apply_tool_offset(tip, offset, -1))
    assert values['robot_connection_state'] == 'CONNECTED'


@pytest.mark.parametrize('case', ['nan_joint', 'bad_quaternion', 'wrong_frame', 'future', 'query_failed'])
def test_observation_invalid_signals_are_not_valid(case):
    cache = ObservationCache()
    state = RobotState(joints_rad=[0.] * 6, tcp_pose=[0.,0.,0.,0.,0.,0.,1.],
                       frame_id='c2_base', quality='VALID', robot_state=1, measured_at=10.)
    if case == 'nan_joint': state.joints_rad[0] = float('nan')
    elif case == 'bad_quaternion': state.tcp_pose[-1] = 0
    elif case == 'wrong_frame': state.frame_id = 'other'
    elif case == 'future': state.measured_at = 11
    elif case == 'query_failed': state.quality = 'UNKNOWN'
    cache.capture(state, None, 2., now=10., utc_ns=100_000_000_000)
    values = cache.values(now=10.)
    if case == 'nan_joint': assert values['joints_quality'] == 'UNKNOWN' and values['joints'] == []
    elif case in ('bad_quaternion', 'wrong_frame'): assert values['tcp_quality'] == 'UNKNOWN'
    else:
        assert values['robot_connection_state'] == values['joints_quality'] == values['tcp_quality'] == 'UNKNOWN'
    assert values['temperature_quality'] == 'UNSUPPORTED'


def test_alarm_deduplicates_and_only_clears_same_precheck():
    alarms = ProcessAlarms()
    scope = ('path', 1, 'path-hash', 'snapshot', 'profile-hash')
    failure = StepResult('FAILED', 'PROFILE_MISMATCH', '설정 불일치')
    assert alarms.update(scope, 'PRECHECK', failure)[0][0] == 'ALARM_RAISED'
    assert alarms.update(scope, 'PRECHECK', failure) == []
    assert alarms.update(('other',), 'PRECHECK', StepResult('SUCCEEDED')) == []
    assert alarms.update(scope, 'ENGRAVE', StepResult('SUCCEEDED')) == []
    assert alarms.update(scope, 'PRECHECK', StepResult('STOPPED')) == []
    assert alarms.update(scope, 'PRECHECK', StepResult('SUCCEEDED'))[0][0] == 'ALARM_CLEARED'
    assert alarms.update(scope, 'PRECHECK', StepResult('SUCCEEDED')) == []


def test_motion_and_unknown_alarms_are_not_automatically_cleared():
    alarms = ProcessAlarms()
    scope = ('p',)
    alarms.update(scope, 'ENGRAVE', StepResult('FAILED', 'FORCE_LIMIT'))
    alarms.update(scope, 'PRECHECK', StepResult('UNKNOWN', 'STOP_UNCONFIRMED'))
    assert alarms.update(scope, 'PRECHECK', StepResult('SUCCEEDED')) == []
    assert alarms.update(scope, 'FINISH', StepResult('SUCCEEDED')) == []
    assert len(alarms.active) == 2


def test_coordinator_reuses_precheck_observation_without_extra_driver_queries():
    goal, inputs = fixture()
    inputs = replace(inputs, evidence=replace(inputs.evidence, max_robot_state_age_s=2.))
    cache, results = ObservationCache(), []
    calls = []
    observe = inputs.adapter.observe
    def counted():
        calls.append('observe')
        return observe()
    inputs.adapter.observe = counted
    coordinator = ProcessCoordinator(lambda _: inputs, observation_cache=cache,
        on_precheck_result=lambda g,c,r: results.append(r.outcome),
        precheck_fn=lambda *a, **k: StepResult('FAILED', 'VALIDATION_FAILED'),
        verify_tip_fn=lambda *a, **k: pytest.fail('tool motion must not run'))
    result = coordinator.execute(goal)
    for _ in range(10): cache.values()
    assert result.outcome == 'FAILED'
    assert results == ['FAILED'] and calls == ['observe']
    assert cache.values()['joints_quality'] == 'VALID'


def test_ros_callbacks_publish_cached_signals_and_alarm_events(monkeypatch):
    from types import SimpleNamespace as NS
    from c2_process.node import create_ros_node
    class Packet:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class State(Packet):
        def __init__(self):
            self.tcp = NS(header=NS(), pose=NS(position=NS(), orientation=NS()))
    class Publisher:
        def __init__(self): self.sent = []
        def publish(self, message): self.sent.append(message)
    class Node:
        def __init__(self, *a): pass
        def create_publisher(self, *a): return Publisher()
        def create_service(self, *a, **k): return None
        def create_timer(self, *a, **k): return None
        def get_logger(self): return NS(warn=lambda message: None)
    monkeypatch.setitem(sys.modules, 'rclpy.action', NS(ActionServer=lambda *a, **k: None,
        CancelResponse=NS(ACCEPT=1, REJECT=0), GoalResponse=NS(ACCEPT=1, REJECT=0)))
    monkeypatch.setitem(sys.modules, 'rclpy.callback_groups', NS(ReentrantCallbackGroup=lambda: None))
    monkeypatch.setitem(sys.modules, 'rclpy.node', NS(Node=Node))
    monkeypatch.setitem(sys.modules, 'rclpy.qos', NS(QoSProfile=Packet,
        ReliabilityPolicy=NS(RELIABLE=1), DurabilityPolicy=NS(VOLATILE=1)))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.action', NS(ExecuteProcess=NS(Feedback=Packet, Result=Packet), PrepareWorkpiece=NS(Feedback=Packet, Result=Packet)))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.msg', NS(ProcessEvent=Packet, ProcessState=State))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.srv', NS(StopProcess=Packet))
    monkeypatch.setitem(sys.modules, 'builtin_interfaces.msg', NS(Time=Packet))
    monkeypatch.setitem(sys.modules, 'rosidl_runtime_py.set_message', NS(set_message_fields=lambda *a: None))
    node = create_ros_node(enable_preparation=False)
    node.goal_values = dict(run_id='r', request_id='q', path_id='p', path_version=1, path_sha256='h')
    config = dict(profile_snapshot_id='s', profile_sha256='sh')
    node.observations.capture(RobotState(joints_rad=[0.] * 6, tcp_pose=[.1,.2,.3,0.,0.,0.,1.],
        frame_id='c2_base', measured_at=time.monotonic(), robot_state=1, quality='VALID'), None, 2.)
    node.publish_state()
    message = node.state_pub.sent[-1]
    assert message.joints_quality == message.tcp_quality == 'VALID'
    assert message.tcp.header.frame_id == 'c2_base'
    assert message.tcp.pose.position.x == .1
    assert message.robot_connection_state == 'CONNECTED' and message.robot_mode == 'UNKNOWN'
    stamp = message.joints_measured_at
    node.publish_state()
    assert vars(node.state_pub.sent[-1].joints_measured_at) == vars(stamp)
    node.report_precheck(node.goal_values, config, StepResult('FAILED', 'PROFILE_MISMATCH'))
    node.report_precheck(node.goal_values, config, StepResult('FAILED', 'PROFILE_MISMATCH'))
    node.report_precheck(node.goal_values, config, StepResult('SUCCEEDED'))
    assert [e.event_type for e in node.event_pub.sent] == ['ALARM_RAISED', 'ALARM_CLEARED']
    assert all(e.profile_snapshot_id == 's' and e.profile_sha256 == 'sh' for e in node.event_pub.sent)

    made = []
    real = object.__new__(DoosanRobotAdapter)
    real.tool_offset_m = None
    real.observe = lambda: RobotState(
        joints_rad=[.2] * 6, tcp_pose=[.1,.2,.3,0.,0.,0.,1.], frame_id='c2_base',
        measured_at=time.monotonic(), robot_state=1, quality='VALID')
    real_node = create_ros_node(
        runtime_mode="REAL", measurement_only=True, enable_preparation=False,
        real_adapter_factory=lambda owner: made.append(owner) or real)
    assert made == [real_node]
    assert real_node.coordinator.real_adapter is real
    assert not hasattr(real_node, 'observation_timer')

    invalidated = []
    real_node.preparation = NS(invalidate=lambda: (
        invalidated.append(True), real_node.coordinator._preparation_bindings.clear()))
    real_node.coordinator._preparation_bindings['prep'] = ('snapshot', 'a' * 64)
    authority = NS(active=True, connected=True, valid=True, has_control=True)
    real_node.real_preparation_observations = NS(cache=NS(fresh=lambda: authority))
    real_node.observations.capture(real.observe(), None, 2.)
    real_node.publish_state()
    assert not invalidated and real_node.coordinator._preparation_bindings
    real_node.real_preparation_observations.cache.fresh = lambda: None
    real_node.publish_state()
    assert invalidated and real_node.coordinator._preparation_bindings == {}
    assert not hasattr(real_node, 'refresh_robot_observation')
    with pytest.raises(ValueError, match="REAL 노드"):
        create_ros_node(enable_preparation=False, real_adapter_factory=lambda _: real)


@pytest.mark.parametrize('outcome,error,partial,stop_confirmed,terminal', [
    ('SUCCEEDED', 'NONE', False, True, 'succeed'),
    ('FAILED', 'MEASUREMENT_FAILED', True, True, 'abort'),
    ('STOPPED', 'CANCELLED', True, True, 'canceled'),
    ('UNKNOWN', 'STOP_UNCONFIRMED', True, False, 'abort'),
])
def test_prepare_action_updates_process_state_returns_once_and_resumes_idle(
        monkeypatch, outcome, error, partial, stop_confirmed, terminal):
    from types import SimpleNamespace as NS
    from c2_process.node import create_ros_node
    from c2_process.preparation_action import GOAL_FIELDS
    class Packet:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class State(Packet):
        def __init__(self):
            self.tcp = NS(header=NS(), pose=NS(position=NS(), orientation=NS()))
    class Publisher:
        def __init__(self): self.sent = []
        def publish(self, message): self.sent.append(message)
    class Node:
        def __init__(self, *a): self.timers = []
        def create_publisher(self, *a): return Publisher()
        def create_service(self, *a, **k): return None
        def create_timer(self, period, callback, **k):
            timer = NS(period=period, callback=callback, canceled=False)
            timer.cancel = lambda: setattr(timer, 'canceled', True)
            self.timers.append(timer)
            return timer
        def get_logger(self): return NS(info=lambda *_: None, warn=lambda *_: None)
    monkeypatch.setitem(sys.modules, 'rclpy.action', NS(ActionServer=lambda *a, **k: None,
        CancelResponse=NS(ACCEPT=1, REJECT=0), GoalResponse=NS(ACCEPT=1, REJECT=0)))
    monkeypatch.setitem(sys.modules, 'rclpy.callback_groups', NS(ReentrantCallbackGroup=lambda: None))
    monkeypatch.setitem(sys.modules, 'rclpy.node', NS(Node=Node))
    monkeypatch.setitem(sys.modules, 'rclpy.qos', NS(QoSProfile=Packet,
        ReliabilityPolicy=NS(RELIABLE=1), DurabilityPolicy=NS(VOLATILE=1)))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.action', NS(
        ExecuteProcess=NS(Feedback=Packet, Result=Packet),
        PrepareWorkpiece=NS(Feedback=Packet, Result=Packet)))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.msg', NS(ProcessEvent=Packet, ProcessState=State))
    monkeypatch.setitem(sys.modules, 'c2_interfaces.srv', NS(StopProcess=Packet))
    monkeypatch.setitem(sys.modules, 'builtin_interfaces.msg', NS(Time=Packet))
    def assign(message, values):
        for key, value in values.items(): setattr(message, key, value)
    monkeypatch.setitem(sys.modules, 'rosidl_runtime_py.set_message', NS(set_message_fields=assign))
    node = create_ros_node(enable_preparation=False)
    entered, release = threading.Event(), threading.Event()
    class Preparation:
        def execute(self, goal, feedback):
            feedback(dict(stage='ROBOT_CHECK', progress=.1, message='상태 검사'))
            entered.set()
            assert release.wait(1.)
            feedback(dict(stage='SIDE_TOUCH', progress=.5, message='측정 중'))
            return dict(outcome=outcome, error_code=error, message='끝',
                        partial=partial, stop_confirmed=stop_confirmed)
        def cancel(self, goal): return True
    node.preparation = Preparation()
    request = NS(**{key: '' for key in GOAL_FIELDS})
    request.operation = 'MEASURE'
    calls = []
    handle = NS(request=request, publish_feedback=lambda packet: calls.append(('feedback', packet.stage)),
                is_cancel_requested=outcome == 'STOPPED',
                succeed=lambda: calls.append(('succeed', None)),
                abort=lambda: calls.append(('abort', None)),
                canceled=lambda: calls.append(('canceled', None)))
    result = []
    worker = threading.Thread(target=lambda: result.append(node.execute_preparation(handle)))
    worker.start()
    assert entered.wait(1.)
    state_timer = next(timer for timer in node.timers if timer.period == pytest.approx(.2))
    for _ in range(5):
        state_timer.callback()
    if outcome == 'STOPPED':
        assert node.cancel_preparation(handle) == 1
        assert node.status == 'STOPPING' and node.stop_state == 'REQUESTED'
    release.set(); worker.join(1.)
    assert not worker.is_alive()
    result = result[0]
    assert result.outcome == outcome
    assert result.partial is partial and result.stop_confirmed is stop_confirmed
    assert [name for name, _ in calls].count(terminal) == 1
    assert sum(name in {'succeed', 'abort', 'canceled'} for name, _ in calls) == 1
    assert [m.status for m in node.state_pub.sent[:5]] == ['RUNNING'] * 5
    assert [m.phase for m in node.state_pub.sent[:5]] == ['PRECHECK'] * 5
    assert [m.engraving_progress for m in node.state_pub.sent[:5]] == [0.] * 5
    assert node.state_pub.sent[:5][-1].message.startswith('ROBOT_CHECK (10%)')
    assert node.state_pub.sent[-1].status == outcome
    node.publish_state()
    assert node.state_pub.sent[-1].status == 'IDLE'


def _registered_input_fixture(tmp_path):
    # actual artifacts.py storage; settings/Action result are explicit SIMULATION fixtures.
    import sqlite3
    from uuid import uuid4
    source = Path(__file__).resolve().parents[2] / 'c2_path'
    if not (source / 'c2_path/artifacts.py').is_file():
        pytest.skip('c2_path 관리 저장소 코드 미제공')
    monkey_path = str(source)
    if monkey_path not in sys.path: sys.path.insert(0, monkey_path)
    from c2_path.artifacts import ManagedArtifactStore, ArtifactWrite, json_bytes
    goal, loader, adapter, files = _file_integration(tmp_path)
    bound = loader(goal)
    snapshot = json.loads(files['snapshot'].read_bytes())
    snapshot.pop('profile_snapshot_id')
    profile_id = str(uuid4())
    snapshot.update(tcp_id='GripperDA_v1', tcp_version=1, load_id='ToolWeight_1', load_version=1,
                    tools_config_id='c2_tools', tools_config_version=1)
    path = json.loads(files['path'].read_bytes())
    path['config'].update(profile_snapshot_id=profile_id, tcp_profile_id='GripperDA_v1',
        tcp_profile_version=1, load_profile_id='ToolWeight_1', load_profile_version=1,
        tools_config_id='c2_tools', tools_config_version=1)
    root = tmp_path / 'managed'; root.mkdir(); (root / 'assets').mkdir()
    with sqlite3.connect(root / 'monitor.sqlite3') as db:
        db.execute('CREATE TABLE assets (id TEXT PRIMARY KEY, sha256 TEXT, kind TEXT, storage_key TEXT, '
                   'mime TEXT, name TEXT, size_bytes INTEGER, metadata TEXT, created_at TEXT)')
    store = ManagedArtifactStore(root)
    profile = store.put_bundle([ArtifactWrite(json_bytes(snapshot), 'profile', 'application/json',
                                  'snapshot.json', {}, profile_id)])[profile_id]
    path['config']['profile_sha256'] = profile.sha256
    asset_id = str(uuid4())
    artifact = store.put_bundle([ArtifactWrite(json_bytes(path), 'path', 'application/json',
        'c2-path.json', {'path_id': path['path_id'], 'path_version': path['path_version']}, asset_id)])[asset_id]
    # Resolve by asset ID, not path_id. Byte SHA is validated by actual store.read.
    artifact = store.read(asset_id, artifact.sha256, ('path',))
    profile = store.read(profile_id, profile.sha256, ('profile',))
    goal = dict(goal, path_sha256=artifact.sha256)
    result = json.loads(files['result'].read_bytes()); result['path_sha256'] = artifact.sha256
    fields = {k: getattr(bound, k) for k in (
        'evidence','context','adapter','workcell','calibration_profiles','calibration',
        'calibration_snapshot_id','tip_tolerance_m','joint_limits_deg','j6_margin_deg')}
    fields['evidence'] = replace(fields['evidence'], profile_snapshot_id=profile_id)
    fields['calibration_snapshot_id'] = profile_id
    kwargs = dict(path_file=artifact.path, snapshot_file=profile.path, generation_result=result,
                  snapshot_metadata={'id':profile.id, 'sha256':profile.sha256},
                  resolve_settings=lambda s,g,snapshot_id: fields)
    return goal, kwargs, store


def test_managed_artifacts_and_action_result_load_without_rewriting_snapshot(tmp_path):
    goal, kwargs, store = _registered_input_fixture(tmp_path)
    original = kwargs['snapshot_file'].read_bytes()
    loaded = load_execution_inputs(goal, **kwargs)
    assert 'profile_snapshot_id' not in loaded.snapshot
    assert loaded.snapshot['tcp_id'] == loaded.path['config']['tcp_profile_id']
    assert kwargs['snapshot_file'].suffix == '.bin'
    assert kwargs['snapshot_file'].read_bytes() == original == loaded.snapshot_bytes
    result = ProcessCoordinator(lambda _: loaded).execute(goal)
    assert result.ok, result


def _validation_report_bytes(kwargs):
    path = json.loads(kwargs["path_file"].read_bytes())
    validation = path["validation"]
    return json.dumps({
        "path_id": path["path_id"],
        "path_version": path["path_version"],
        "passed": True,
        "checks": validation["checks"],
        "not_checked": validation["not_checked"],
        "errors": [],
        "mapping_failures": [],
    }).encode()


def test_hmi_asset_bundle_bytes_use_existing_integrity_checks(tmp_path):
    goal, kwargs, _ = _registered_input_fixture(tmp_path)
    settings = kwargs["resolve_settings"]
    assets = {
        "path_bytes": kwargs["path_file"].read_bytes(),
        "snapshot_bytes": kwargs["snapshot_file"].read_bytes(),
        "generation_result": kwargs["generation_result"],
        "validation_report_bytes": _validation_report_bytes(kwargs),
        "snapshot_metadata": kwargs["snapshot_metadata"],
    }
    requested = []
    loader = make_asset_bundle_loader(
        lambda received: requested.append(received) or assets,
        settings,
    )

    loaded = loader(goal)

    assert requested == [goal]
    assert loaded.path_bytes == assets["path_bytes"]
    assert loaded.snapshot_bytes == assets["snapshot_bytes"]
    assert loaded.path["path_id"] == goal["path_id"]


def test_hmi_asset_bundle_rejects_changed_path_bytes(tmp_path):
    goal, kwargs, _ = _registered_input_fixture(tmp_path)
    assets = {
        "path_bytes": kwargs["path_file"].read_bytes() + b" ",
        "snapshot_bytes": kwargs["snapshot_file"].read_bytes(),
        "generation_result": kwargs["generation_result"],
        "validation_report_bytes": _validation_report_bytes(kwargs),
        "snapshot_metadata": kwargs["snapshot_metadata"],
    }
    loader = make_asset_bundle_loader(lambda _: assets, kwargs["resolve_settings"])

    with pytest.raises(InputsUnavailable, match="SHA-256") as caught:
        loader(goal)

    assert caught.value.error_code == "PATH_MISMATCH"


def test_hmi_asset_bundle_requires_only_the_four_existing_inputs(tmp_path):
    goal, kwargs, _ = _registered_input_fixture(tmp_path)
    loader = make_asset_bundle_loader(
        lambda _: {"path_bytes": kwargs["path_file"].read_bytes()},
        kwargs["resolve_settings"],
    )

    with pytest.raises(InputsUnavailable, match="필드 누락/초과") as caught:
        loader(goal)

    assert caught.value.error_code == "INVALID_INPUT"


def test_hmi_resolver_uses_existing_path_and_asset_endpoints(tmp_path):
    goal, kwargs, _ = _registered_input_fixture(tmp_path)
    metadata = dict(
        kwargs["generation_result"],
        path_asset_id="path-asset",
        validation_report_id="validation-asset",
        profile_snapshot_id=kwargs["snapshot_metadata"]["id"],
        profile_sha256=kwargs["snapshot_metadata"]["sha256"],
    )
    replies = {
        f"http://hmi.local/api/operator/paths/{goal['path_id']}/versions/{goal['path_version']}":
            json.dumps(metadata).encode(),
        "http://hmi.local/api/operator/assets/path-asset/content":
            kwargs["path_file"].read_bytes(),
        "http://hmi.local/api/operator/assets/validation-asset/content":
            _validation_report_bytes(kwargs),
        f"http://hmi.local/api/operator/assets/{kwargs['snapshot_metadata']['id']}/content":
            kwargs["snapshot_file"].read_bytes(),
    }
    requested = []
    resolver = make_hmi_asset_resolver(
        "http://hmi.local",
        fetch_bytes=lambda url: requested.append(url) or replies[url],
    )

    assets = resolver(goal)

    assert assets["path_bytes"] == kwargs["path_file"].read_bytes()
    assert assets["snapshot_bytes"] == kwargs["snapshot_file"].read_bytes()
    assert requested == list(replies)


@pytest.mark.parametrize("defect,code", [
    (lambda r: r.update(passed=False), "VALIDATION_UNAVAILABLE"),
    (lambda r: r.update(path_version=r["path_version"] + 1), "PATH_MISMATCH"),
    (lambda r: r["checks"][0].update(passed=False), "VALIDATION_UNAVAILABLE"),
])
def test_hmi_validation_report_must_match_path_and_be_complete(tmp_path, defect, code):
    goal, kwargs, _ = _registered_input_fixture(tmp_path)
    report = json.loads(_validation_report_bytes(kwargs))
    defect(report)
    assets = {
        "path_bytes": kwargs["path_file"].read_bytes(),
        "snapshot_bytes": kwargs["snapshot_file"].read_bytes(),
        "generation_result": kwargs["generation_result"],
        "validation_report_bytes": json.dumps(report).encode(),
        "snapshot_metadata": kwargs["snapshot_metadata"],
    }
    loader = make_asset_bundle_loader(lambda _: assets, kwargs["resolve_settings"])

    with pytest.raises(InputsUnavailable) as caught:
        loader(goal)

    assert caught.value.error_code == code


def _hmi_validation_report(kwargs):
    path_bytes = kwargs["path_file"].read_bytes()
    path = json.loads(path_bytes)
    return {
        "path_id": path["path_id"],
        "path_version": path["path_version"],
        "path_sha256": hashlib.sha256(path_bytes).hexdigest(),
        "geometry_passed": True,
        "execution_readiness": {
            "executability": "NOT_JUDGED",
            "runtime_checks_passed": None,
            "trial_authorized": True,
        },
        "not_checked": ["LIVE_ROBOT_STATE", "REAL_IK", "CONTINUOUS_COLLISION", "ACTUAL_DEPTH"],
    }


def test_hmi_geometry_validation_report_uses_embedded_path_checks(tmp_path):
    goal, kwargs, _ = _registered_input_fixture(tmp_path)
    report = _hmi_validation_report(kwargs)
    assets = {
        "path_bytes": kwargs["path_file"].read_bytes(),
        "snapshot_bytes": kwargs["snapshot_file"].read_bytes(),
        "generation_result": kwargs["generation_result"],
        "validation_report_bytes": json.dumps(report).encode(),
        "snapshot_metadata": kwargs["snapshot_metadata"],
    }

    loaded = make_asset_bundle_loader(
        lambda _: assets, kwargs["resolve_settings"])(goal)

    assert loaded.path["validation"]["passed"] is True
    assert report["not_checked"] != loaded.path["validation"]["not_checked"]


@pytest.mark.parametrize("defect", [
    lambda r: r.update(geometry_passed=False),
    lambda r: r.pop("execution_readiness"),
    lambda r: r["execution_readiness"].update(executability=""),
    lambda r: r["execution_readiness"].update(runtime_checks_passed="unknown"),
    lambda r: r["execution_readiness"].pop("trial_authorized"),
    lambda r: r.update(not_checked=[None]),
])
def test_hmi_geometry_validation_report_rejects_incomplete_data(tmp_path, defect):
    goal, kwargs, _ = _registered_input_fixture(tmp_path)
    report = _hmi_validation_report(kwargs)
    defect(report)
    assets = {
        "path_bytes": kwargs["path_file"].read_bytes(),
        "snapshot_bytes": kwargs["snapshot_file"].read_bytes(),
        "generation_result": kwargs["generation_result"],
        "validation_report_bytes": json.dumps(report).encode(),
        "snapshot_metadata": kwargs["snapshot_metadata"],
    }

    with pytest.raises(InputsUnavailable) as caught:
        make_asset_bundle_loader(lambda _: assets, kwargs["resolve_settings"])(goal)

    assert caught.value.error_code == "VALIDATION_UNAVAILABLE"


def test_prepared_real_node_does_not_require_extra_start_or_home_callbacks(tmp_path):
    adapter = object.__new__(DoosanRobotAdapter)
    coordinator = ProcessCoordinator(
        lambda _: None,
        runtime_mode="REAL",
        real_adapter=adapter,
        journal=RunJournal(tmp_path / "runs.sqlite3"),
        preparation_required=True,
    )

    assert coordinator.real_adapter is adapter
    assert coordinator.preparation_required is True


@pytest.mark.parametrize('case', ['bad_id', 'bad_sha', 'no_metadata', 'conflicting_alias',
                                  'missing_tools_version', 'failed_result', 'two_results'])
def test_registered_inputs_reject_missing_or_conflicting_evidence(tmp_path, case):
    goal, kwargs, store = _registered_input_fixture(tmp_path)
    if case == 'bad_id': kwargs['snapshot_metadata']['id'] = 'wrong'
    elif case == 'bad_sha': kwargs['snapshot_metadata']['sha256'] = '0' * 64
    elif case == 'no_metadata': kwargs.pop('snapshot_metadata')
    elif case in ('conflicting_alias', 'missing_tools_version'):
        snapshot = json.loads(kwargs['snapshot_file'].read_bytes())
        if case == 'conflicting_alias': snapshot['tcp_profile_id'] = 'other'
        else: snapshot.pop('tools_config_version')
        # New synthetic export bytes and matching SHA, so the test reaches field comparison.
        raw = json.dumps(snapshot).encode(); kwargs['snapshot_file'].write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest(); kwargs['snapshot_metadata']['sha256'] = sha
        path = json.loads(kwargs['path_file'].read_bytes()); path['config']['profile_sha256'] = sha
        raw = json.dumps(path).encode(); kwargs['path_file'].write_bytes(raw)
        goal['path_sha256'] = kwargs['generation_result']['path_sha256'] = hashlib.sha256(raw).hexdigest()
    elif case == 'failed_result': kwargs['generation_result']['success'] = False
    elif case == 'two_results': kwargs['result_file'] = tmp_path / 'not-used.json'
    called = []
    kwargs['resolve_settings'] = lambda *a: called.append(True)
    with pytest.raises(InputsUnavailable): load_execution_inputs(goal, **kwargs)
    assert called == []


class _DriverBoundaryMock(MockRobotAdapter, DoosanRobotAdapter):
    """모션 변환은 실제 어댑터 메서드, 드라이버/완료/접촉은 전부 메모리 대역.

    DoosanRobotAdapter 생성자를 호출하지 않아 ROS import·서비스·장치 설정이 없다.
    """
    _frame_ok = DoosanRobotAdapter._frame_ok

    def __init__(self, touch_distance_m):
        from types import SimpleNamespace

        super().__init__(surface_fn=lambda _pose, _direction: touch_distance_m)
        self.commands = []
        self.tip_commands = []
        self.waits = []
        self.posx = lambda *values: list(values)
        self._srv = {name: SimpleNamespace(Request=SimpleNamespace)
                     for name in ('MoveLine', 'MoveSplineTask')}

    def _motion_sample(self, timeout):
        # 이 시험은 명령 변환 경계만 확인한다. 완료 관측은 별도 어댑터 시험에서 검증.
        return [1000., 1000., 1000., 0., 0., 0.], 1, 0

    def _call(self, endpoint, kind, request, timeout=5.):
        from types import SimpleNamespace
        spline = endpoint == 'motion/move_spline_task'
        poses = [list(p.data) for p in request.pos] if spline else [list(request.pos)]
        self.commands.append(('move_spline' if spline else 'move', poses,
                              dict(ref=request.ref, mod=request.mode,
                                   vel=request.vel, acc=request.acc)))
        assert request.sync_type == 1
        return SimpleNamespace(success=True)

    def move(self, pose, frame_id, profile, deadline_s, cancel):
        self.tip_commands.append(("move", [list(pose)], frame_id))
        self.pending_tip = list(pose)
        return DoosanRobotAdapter.move(self, pose, frame_id, profile, deadline_s, cancel)

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel):
        self.tip_commands.append(("move_spline", copy.deepcopy(poses), frame_id))
        self.pending_tip = list(poses[-1])
        from types import SimpleNamespace
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(sys.modules, 'std_msgs.msg', SimpleNamespace(Float64MultiArray=SimpleNamespace))
            return DoosanRobotAdapter.move_spline(self, poses, frame_id, profile, deadline_s, cancel)

    def _wait_motion(self, target, deadline_s, cancel, step, tolerance_mm, **_kwargs):
        self.waits.append((list(target[:3]), deadline_s, tolerance_mm))
        return self._simulate_motion(self.pending_tip, step, cancel)


def _producer_heart_and_context():
    """원본 경로는 그대로, 프로파일은 이 오프라인 명령 경계 시험 전용.

    임시 snapshot 해시를 승인값으로 만들지 않는다. 파일/PRECHECK 통합 시험과 별개다.
    """
    source = Path(__file__).resolve().parents[2] / "c2_path/samples/heart/path.json"
    raw = source.read_bytes()
    path = json.loads(raw)
    assert path["test_only"] and path["source_mode"] == "SIMULATION"
    assert path["schema_version"] == 2 and path["frame_id"] == "c2_base"
    assert {s["stroke_id"] for s in path["segments"]} == {"stroke000"}
    assert [s["kind"] for s in path["segments"]] == ["APPROACH", "CUT", "CUT", "RETRACT"]
    profiles = {
        pid: {"id": pid, "vel_mm_s": 7.0 + i, "acc_mm_s2": 17.0 + i,
              "completion_timeout_s": 30.0 + i, "pos_tol_mm": 1.0}
        for i, pid in enumerate(dict.fromkeys(s["motion_profile_id"] for s in path["segments"]))
    }
    context = ExecutionContext(
        run_id="test-only-producer-stroke", source_mode="SIMULATION", cancel=threading.Event(),
        motion_profiles=profiles,
        tool_profile={"tool_id": "engraving_drill", "tool_axis": "-y",
                      "contact_mode": "force_touch", "clearance_m": {"stroke": 0.006},
                      "touch_offset_range_m": [-0.003, 0.003],
                      "touch_extra_m": 0.008, "touch_force_n": 0.8, "touch_speed_mm_s": 1.5},
    )
    return source, raw, path, context


def _sample_radial(pose):
    # heart生成元 workcell.py の test_only 中心。現場の最新中心を意味しない。
    dx, dy = pose[0] - 0.4218, pose[1] - 0.0001
    radius = math.hypot(dx, dy)
    return [dx / radius, dy / radius, 0.0]


@pytest.mark.parametrize("mode,inward_m", [
    ("force_touch", 0.0), ("force_touch", 0.0007), ("fixed_depth", 0.0007),
])
def test_producer_heart_axes_offset_and_driver_commands(mode, inward_m, monkeypatch):
    from c2_process.robot_adapter import tool_axis_in_base, zyz_deg_to_matrix

    # 실물 어댑터 초기화를 실수로 추가하면 장치 접속 전에 실패한다.
    def forbid_real_init(*_args, **_kwargs):
        raise AssertionError("이 시험에서 실물 어댑터 초기화 금지")
    monkeypatch.setattr(DoosanRobotAdapter, "__init__", forbid_real_init)
    source, raw, path, context = _producer_heart_and_context()
    unchanged = copy.deepcopy(path)
    context.tool_profile.update(contact_mode=mode, depth_m=inward_m)
    adapter = _DriverBoundaryMock(touch_distance_m=0.006 + inward_m)
    # 돌출 합의값과 옆 어긋남 시험값의 조합. 현장 전체 보정 기록/승인값이 아니다.
    lateral_m, projection_m = 0.0017, 0.09955
    adapter.set_tool_offset([lateral_m, -projection_m, 0.0])
    approach, cut_a, cut_b, retract = path["segments"]
    for segment in path["segments"]:
        for pose in segment["waypoints"]:
            radial = _sample_radial(pose)
            assert tool_axis_in_base(pose, "-y") == pytest.approx([-v for v in radial], abs=3e-5)
            assert tool_axis_in_base(pose, "+z") == pytest.approx([0., 0., -1.], abs=1e-12)

    def shifted(pose, inward):
        radial = _sample_radial(pose)
        return [pose[k] - radial[k] * inward for k in range(3)] + pose[3:]

    # 30mm APPROACH 후 force_touch는 6mm 바깥으로 재접근한다.
    # CUT 각 구간의 첫 점 진입을 계획과 실행에 명시한다.
    entry = shifted(cut_a["waypoints"][0], -0.006 if mode == "force_touch" else inward_m)
    expected = [("move", [p], approach["motion_profile_id"]) for p in approach["waypoints"]]
    if mode == "force_touch":
        expected.append(("move", [entry], cut_a["motion_profile_id"]))
    for cut in (cut_a, cut_b):
        expected.append(("move", [shifted(cut["waypoints"][0], inward_m)], cut["motion_profile_id"]))
        expected.append(("move_spline", [shifted(p, inward_m) for p in cut["waypoints"][1:]],
                         cut["motion_profile_id"]))
    expected.extend(("move", [p], retract["motion_profile_id"]) for p in retract["waypoints"])

    result = execute_path(path, context, adapter=adapter)
    assert result.ok, result
    assert result.observed_state["last_completed_segment_id"] == retract["segment_id"]
    assert result.observed_state["engraving_progress"] == pytest.approx(1.0)
    assert len(adapter.commands) == len(adapter.tip_commands) == len(adapter.waits) == len(expected) == (9 if mode == "force_touch" else 8)
    assert [len(pts) for kind, pts, _ in adapter.commands if kind == "move_spline"] == [79, 43]
    for actual, tips, wait, (kind, poses, pid) in zip(
            adapter.commands, adapter.tip_commands, adapter.waits, expected):
        actual_kind, controller_poses, options = actual
        tip_kind, tip_poses, frame = tips
        profile = context.motion_profiles[pid]
        assert actual_kind == tip_kind == kind
        assert frame == "c2_base" and len(controller_poses) == len(poses)
        assert options["ref"] == 0 and options["mod"] == 0
        assert options["vel"] == [profile["vel_mm_s"]] * 2
        assert options["acc"] == [profile["acc_mm_s2"]] * 2
        assert wait[0] == controller_poses[-1][:3]
        assert wait[1] == pytest.approx(profile["completion_timeout_s"], abs=0.1)
        assert wait[2] == profile["pos_tol_mm"]
        for px, tip, expected_tip in zip(controller_poses, tip_poses, poses):
            assert tip == pytest.approx(expected_tip, abs=3e-8)
            radial = _sample_radial(expected_tip)
            tangent = [-radial[1], radial[0], 0.0]  # +X = +Y × +Z
            # 기대값은 pose_to_posx/apply_tool_offset을 재호출하지 않고 원통 기하로 계산.
            tcp_mm = [(expected_tip[k] - lateral_m * tangent[k] + projection_m * radial[k]) * 1000.
                      for k in range(3)]
            # JSON 위치/quat 6자리 반올림 오차만 허용. 실기 허용차가 아니다.
            assert px[:3] == pytest.approx(tcp_mm, abs=0.003)
            matrix = zyz_deg_to_matrix(*px[3:])
            assert [-matrix[k][1] for k in range(3)] == pytest.approx([-v for v in radial], abs=3e-5)
            # acos(-1 + 부동소수점 오차)의 특이점 왕복에서 약 2e-8 축 오차가 생긴다.
            assert [matrix[k][2] for k in range(3)] == pytest.approx([0., 0., -1.], abs=1e-7)
            assert px[4] == pytest.approx(180.0)
    touches = [c for c in adapter.calls if c["fn"] == "probe_touch"]
    assert len(touches) == (1 if mode == "force_touch" else 0)
    if touches:
        assert touches[0]["direction"] == pytest.approx([0., 1., 0.])
        assert touches[0]["max_m"] == pytest.approx(0.014)
        assert result.observed_state["touches"][0]["offset_mm"] == pytest.approx(inward_m * 1000.)
    assert adapter.tool_offset_m == [lateral_m, -projection_m, 0.0]
    assert source.read_bytes() == raw and path == unchanged


@pytest.mark.parametrize("case", ["mode", "profile"])
def test_producer_heart_mismatch_sends_no_driver_command(case):
    _, _, path, context = _producer_heart_and_context()
    if case == "mode":
        context.source_mode = "REAL"  # 거절만 확인. 실행 어댑터는 여전히 메모리 대역.
    else:
        context.motion_profiles.pop("candle_cut")
    adapter = _DriverBoundaryMock(0.006)
    result = execute_path(path, context, adapter=adapter)
    assert (result.outcome, result.error_code) == ("FAILED", "PROFILE_MISMATCH")
    assert adapter.commands == adapter.tip_commands == adapter.calls == []


def test_ros_simulation_terminal_roundtrip(tmp_path, monkeypatch):
    """명시적으로 켠 경우만 ROS Action/Topic 실제 왕복. 장비는 Mock 전용."""
    import os
    if os.environ.get("C2_RUN_ROS_SMOKE") != "1":
        pytest.skip("ROS 모의 왕복은 Jazzy source 후 C2_RUN_ROS_SMOKE=1로 별도 실행")
    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        pytest.fail("이 시험은 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST 필요")
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from action_msgs.msg import GoalStatus
    from c2_interfaces.action import ExecuteProcess
    from c2_interfaces.msg import ProcessState, ProcessEvent
    from c2_process.node import create_ros_node
    from uuid import uuid4

    def forbid_real_init(*_args, **_kwargs):
        raise AssertionError("ROS 모의시험에서 실물 어댑터 초기화 금지")
    monkeypatch.setattr(DoosanRobotAdapter, "__init__", forbid_real_init)
    goal, loader, adapter, files = _file_integration(tmp_path)
    assert type(adapter) is MockRobotAdapter
    assert goal["source_mode"] == "SIMULATION"
    adapter.move_time_s = 0.12
    # 다른 실행 PC/노드에 닿지 않도록 localhost + 매번 고유 토픽으로 remap.
    prefix = "/c2_smoke_" + uuid4().hex
    names = ["execute_process", "stop_process", "process_state", "process_events"]
    ros_args = ["--ros-args"]
    for name in names:
        ros_args += ["-r", f"/c2/{name}:={prefix}/{name}"]
    print("\n[시험] 실제 ROS 통신 + MockRobotAdapter / 실물 명령 없음", flush=True)
    print("[입력] 기존 합성 SIMULATION 시험 경로·설정 (실제 팀 스냅샷 아님)", flush=True)
    print(f"[격리] localhost, ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '20')}, {prefix}", flush=True)
    rclpy.init(args=ros_args)
    server = client = executor = thread = None
    feedbacks, events, states = [], [], []
    finished_event = threading.Event()
    terminal_state = threading.Event()
    try:
        server = create_ros_node(load_inputs=loader, runtime_mode="SIMULATION", enable_preparation=False)  # 기존 Execute 단독 시험
        client = Node("process_smoke_client")
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(server)
        executor.add_node(client)

        def on_event(msg):
            events.append(msg)
            if msg.event_type == "RUN_FINISHED" and msg.run_id == goal["run_id"]:
                finished_event.set()

        def on_state(msg):
            states.append(msg)
            if msg.run_id == goal["run_id"] and msg.status == "SUCCEEDED":
                terminal_state.set()

        client.create_subscription(ProcessEvent, prefix + "/process_events", on_event, 100)
        client.create_subscription(ProcessState, prefix + "/process_state", on_state, 10)
        action = ActionClient(client, ExecuteProcess, prefix + "/execute_process")
        thread = threading.Thread(target=executor.spin, daemon=True)
        thread.start()
        assert action.wait_for_server(timeout_sec=10.0), "공정 Action 서버 발견 시간 초과"
        # Action과 독립인 Topic discovery도 확인한 뒤 요청하여 첫 이벤트 유실을 피한다.
        deadline = time.monotonic() + 5.0
        while (server.event_pub.get_subscription_count() < 1
               or server.state_pub.get_subscription_count() < 1):
            assert time.monotonic() < deadline, "상태/이벤트 구독 연결 시간 초과"
            threading.Event().wait(0.05)

        def feedback(packet):
            value = packet.feedback
            previous = feedbacks[-1] if feedbacks else None
            feedbacks.append(value)
            if previous is None or (value.phase, value.engraving_progress) != (previous.phase, previous.engraving_progress):
                print(f"[진행] {value.phase:10s} 조각 {value.engraving_progress:.0%}"
                      f" / 마지막 완료: {value.completed_segment_id or '-'}", flush=True)

        def wait_result(future, seconds):
            done = threading.Event()
            future.add_done_callback(lambda _future: done.set())
            assert done.wait(seconds), "ROS 응답 시간 초과"
            return future.result()

        request = ExecuteProcess.Goal()
        for key, value in goal.items():
            setattr(request, key, value)
        print(f"[요청] run_id={goal['run_id']} / path_id={goal['path_id']} / version={goal['path_version']}", flush=True)
        handle = wait_result(action.send_goal_async(request, feedback_callback=feedback), 10.)
        assert handle.accepted, "ROS 시작 요청 거절"
        print("[접수] Action 요청 수락 (공정 성공과는 별개)", flush=True)
        response = wait_result(handle.get_result_async(), 20.)
        result = response.result
        print(f"[결과] ROS status={response.status} / {result.outcome} / {result.error_code}", flush=True)
        print(f"[설명] {result.message}", flush=True)
        assert response.status == GoalStatus.STATUS_SUCCEEDED
        assert (result.run_id, result.outcome, result.error_code) == (goal["run_id"], "SUCCEEDED", "NONE")
        assert result.last_completed_segment_id == "retract"
        assert finished_event.wait(3.), "RUN_FINISHED 이벤트 수신 안 됨"
        assert terminal_state.wait(3.), "최종 ProcessState 수신 안 됨"
        assert {"PRECHECK", "TOOL_CHECK", "APPROACH", "ENGRAVE", "RETRACT", "FINISH"} <= {f.phase for f in feedbacks}
        assert all(f.run_id == goal["run_id"] for f in feedbacks)
        final = next(e for e in events if e.event_type == "RUN_FINISHED")
        config = json.loads(files["path"].read_bytes())["config"]
        assert (final.request_id, final.run_id, final.path_id, final.path_version, final.path_sha256) == tuple(
            goal[k] for k in ("request_id", "run_id", "path_id", "path_version", "path_sha256"))
        assert (final.profile_snapshot_id, final.profile_sha256) == (config["profile_snapshot_id"], config["profile_sha256"])
        state = next(s for s in states if s.status == "SUCCEEDED")
        assert (state.path_id, state.path_version, state.source_mode) == (goal["path_id"], goal["path_version"], "SIMULATION")
        assert any(c["fn"] == "move_spline" for c in adapter.calls)
        print("[확인] 실행·경로 ID/버전/해시 유지, 단계·상태·완료 이벤트 수신", flush=True)
        print("[통과] ROS 모의 정상 요청 1건 완료. 실물·HMI·정지 시험은 별도입니다.", flush=True)
    finally:
        if executor is not None:
            executor.shutdown(timeout_sec=5.)
        if thread is not None:
            thread.join(timeout=5.)
        if client is not None:
            client.destroy_node()
        if server is not None:
            server.destroy_node()
        rclpy.shutdown()


from c2_process.node import resolve_simulation_settings


def _handoff_settings():
    base = Path(__file__).parent / 'fixtures' / 'handoff_0920'
    raw = (base / 'simulation_inputs.json').read_bytes()
    path_raw = (base / 'simulation_path.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '7e7149820b2ed6df166af99694c2e1fe62232fa741d0a18a4fb71c26ff760cbe'
    assert hashlib.sha256(path_raw).hexdigest() == '6b8d66cc6d3cedc5abc422bf3316f6681f31315fb08b04d30a3a1a5f67fc2b02'
    cfg, path = json.loads(raw), json.loads(path_raw)
    goal = {'run_id': 'current-sim-request', 'source_mode': 'SIMULATION'}
    ad = MockRobotAdapter()
    evidence = PreconditionEvidence(runtime_mode='SIMULATION', robot_state=ad.observe(),
                                   profile_snapshot_id=cfg['profile_snapshot_id'])
    return cfg, path, goal, ad, evidence


def test_handoff_mapping_preserves_values_without_fabricating_evidence():
    cfg, path, goal, ad, evidence = _handoff_settings()
    before = json.dumps(cfg, sort_keys=True)
    fields = resolve_simulation_settings(cfg, goal, evidence=evidence, adapter=ad)
    assert fields['adapter'] is ad and fields['evidence'] is evidence
    assert fields['context'].run_id == goal['run_id'] != cfg['execution_context']['run_id']
    assert fields['j6_margin_deg'] == 0
    assert fields['joint_limits_deg'][5] == [-345, 345]
    assert fields['calibration'].offset_tool_m == cfg['tip_calibration']['offset_tool_m']
    assert fields['calibration'].offset_tool_m != cfg['fixed_mount_baseline']['offset_tool_m']
    assert not evidence.path_validation_passed and not evidence.control_authority_confirmed
    assert ad.calls == []
    second = resolve_simulation_settings(cfg, goal, evidence=evidence, adapter=ad)
    fields['context'].cancel.set()
    assert not second['context'].cancel.is_set()
    fields['context'].tool_profile['depth_m'] = 99
    assert json.dumps(cfg, sort_keys=True) == before


def _complete_real_profile():
    cfg, _, goal, adapter, _ = _handoff_settings()
    workcell = copy.deepcopy(cfg['workcell'])
    height_m = 0.15
    return {
        'schema_version': 2,
        'source_mode': 'REAL',
        'frame_id': 'c2_base',
        'tool_id': 'engraving_drill',
        'tcp_id': 'GripperDA_v1',
        'load_id': 'ToolWeight_1',
        'test_only': False,
        'real_execution_allowed': True,
        'preview_only': False,
        'gripper_open_allowed': False,
        'geometry_ready': True,
        'workcell': workcell,
        'surface': {
            'kind': 'cylinder',
            'radius_mm': workcell['radius_m'] * 1000.0,
            'height_mm': height_m * 1000.0,
            'axis_origin_m': [*workcell['axis_xy_m'], workcell['top_z_m'] - height_m],
        },
        'tip_calibration': copy.deepcopy(cfg['tip_calibration']),
        'calibration_profiles': copy.deepcopy(cfg['calibration_profiles']),
        'execution_context': {
            'source_mode': 'REAL',
            'motion_profiles': copy.deepcopy(cfg['execution_context']['motion_profiles']),
            'tool_profile': copy.deepcopy(cfg['execution_context']['tool_profile']),
            'stop_profile': copy.deepcopy(cfg['execution_context']['stop_profile']),
        },
        'verify_tool_tip_arguments': copy.deepcopy(cfg['verify_tool_tip_arguments']),
        'joint_check_arguments': copy.deepcopy(cfg['joint_check_arguments']),
    }, dict(goal, source_mode='REAL'), adapter


def test_real_profile_mapping_uses_confirmed_nested_layout_and_external_id():
    import c2_process.node as module
    profile, goal, adapter = _complete_real_profile()
    before = json.dumps(profile, sort_keys=True)

    fields = module.resolve_real_execution_settings(
        profile, goal, 'registered-real-profile', adapter=adapter)

    assert fields['evidence'].profile_snapshot_id == 'registered-real-profile'
    assert fields['calibration_snapshot_id'] == 'registered-real-profile'
    assert fields['context'].motion_profiles == profile['execution_context']['motion_profiles']
    assert fields['context'].tool_profile == profile['execution_context']['tool_profile']
    assert fields['context'].stop_profile == profile['execution_context']['stop_profile']
    assert fields['calibration'] is None
    assert fields['calibration_profiles'] == {}
    assert fields['tip_tolerance_m'] is None
    assert fields['tool_offset_m'] == profile['tip_calibration']['offset_tool_m']
    assert fields['joint_limits_deg'] == profile['joint_check_arguments']['limits_deg']
    assert fields['j6_margin_deg'] == profile['joint_check_arguments']['j6_margin_deg']
    assert json.dumps(profile, sort_keys=True) == before


def test_real_profile_mapping_uses_injected_execution_status_evidence():
    import c2_process.node as module
    profile, goal, adapter = _complete_real_profile()
    supplied = PreconditionEvidence(
        runtime_mode='REAL', robot_state=None,
        control_authority_confirmed=True, stop_latched=False,
        profile_snapshot_id='registered-real-profile', max_robot_state_age_s=.5)
    calls=[]

    fields = module.resolve_real_execution_settings(
        profile, goal, 'registered-real-profile', adapter=adapter,
        evidence_provider=lambda profile_id: calls.append(profile_id) or supplied)

    assert calls==['registered-real-profile']
    assert fields['evidence'] is supplied


@pytest.mark.parametrize('field', ['preview_only', 'geometry_ready'])
def test_real_profile_mapping_allows_optional_summary_flags_to_be_absent(field):
    import c2_process.node as module
    profile, goal, adapter = _complete_real_profile()
    profile.pop(field)

    fields = module.resolve_real_execution_settings(
        profile, goal, 'registered-real-profile', adapter=adapter)

    assert fields['context'].source_mode == 'REAL'


@pytest.mark.parametrize('field,value', [('preview_only', True), ('geometry_ready', False)])
def test_real_profile_mapping_rejects_invalid_optional_summary_flags(field, value):
    import c2_process.node as module
    profile, goal, adapter = _complete_real_profile()
    profile[field] = value

    with pytest.raises(InputsUnavailable, match='실행 승인되지 않은'):
        module.resolve_real_execution_settings(
            profile, goal, 'registered-real-profile', adapter=adapter)


@pytest.mark.parametrize('case,match', [
    ('preview', '실행 승인되지 않은'),
    ('top_z', 'workcell 중심'),
    ('tool_offset', '드릴 오프셋'),
    ('j6_margin', '관절 한계'),
])
def test_real_profile_mapping_rejects_handoff_sample_gaps(case, match):
    import c2_process.node as module
    profile, goal, adapter = _complete_real_profile()
    if case == 'preview':
        profile.update(test_only=True, real_execution_allowed=False,
                       preview_only=True, geometry_ready=False)
    elif case == 'top_z':
        profile['workcell']['top_z_m'] = None
    elif case == 'tool_offset':
        profile['tip_calibration']['offset_tool_m'] = [None, None, None]
    elif case == 'j6_margin':
        profile['joint_check_arguments']['j6_margin_deg'] = None

    with pytest.raises(InputsUnavailable, match=match):
        module.resolve_real_execution_settings(
            profile, goal, 'registered-real-profile', adapter=adapter)


@pytest.mark.parametrize('depth_m,cut_speed', [(0.0003, 5.0), (0.0007, 2.5)])
def test_real_profile_mapping_passes_per_job_recipe_without_fixed_defaults(depth_m, cut_speed):
    import c2_process.node as module
    profile, goal, adapter = _complete_real_profile()
    profile['tip_calibration'] = {
        'tool_id': 'engraving_drill',
        'offset_tool_m': [0.00085, -0.09955, 0.0],
    }
    profile.pop('calibration_profiles')
    profile.pop('verify_tool_tip_arguments')
    profile['execution_context']['tool_profile'].update(
        contact_mode='fixed_depth', depth_m=depth_m, clearance_m=0.002)
    profile['execution_context']['motion_profiles']['candle_cut']['vel_mm_s'] = cut_speed

    fields = module.resolve_real_execution_settings(
        profile, goal, 'registered-real-profile', adapter=adapter)

    assert fields['context'].tool_profile['depth_m'] == depth_m
    assert fields['context'].motion_profiles['candle_cut']['vel_mm_s'] == cut_speed
    assert fields['tool_offset_m'] == [0.00085, -0.09955, 0.0]
    assert fields['calibration'] is None
    assert fields['tip_tolerance_m'] is None


@pytest.mark.parametrize('margin', [-1, float('nan'), float('inf'), True, None, 345])
def test_handoff_mapping_rejects_invalid_additional_margin(margin):
    cfg, _, goal, ad, evidence = _handoff_settings()
    cfg['joint_check_arguments']['j6_margin_deg'] = margin
    with pytest.raises(InputsUnavailable):
        resolve_simulation_settings(cfg, goal, evidence=evidence, adapter=ad)
    assert ad.calls == []


@pytest.mark.parametrize('case', ['real_goal', 'real_context', 'not_test', 'allow_real',
                                 'missing_calibration', 'missing_profiles', 'wrong_snapshot', 'real_adapter'])
def test_handoff_mapping_does_not_enable_real_or_fill_missing_values(case):
    cfg, _, goal, ad, evidence = _handoff_settings()
    if case == 'real_goal': goal['source_mode'] = 'REAL'
    elif case == 'real_context': cfg['execution_context']['source_mode'] = 'REAL'
    elif case == 'not_test': cfg['test_only'] = False
    elif case == 'allow_real': cfg['allow_real'] = True
    elif case == 'missing_calibration': cfg.pop('tip_calibration')
    elif case == 'missing_profiles': cfg['execution_context'].pop('motion_profiles')
    elif case == 'wrong_snapshot': cfg['profile_snapshot_id'] = 'wrong'
    elif case == 'real_adapter': ad = object()  # 실물 객체를 생성하지 않는다.
    with pytest.raises(InputsUnavailable):
        resolve_simulation_settings(cfg, goal, evidence=evidence, adapter=ad)


@pytest.mark.parametrize('margin,expected', [(0, 'SUCCEEDED'), (-1, 'FAILED'),
                                            (float('nan'), 'FAILED'), (True, 'FAILED')])
def test_process_accepts_zero_additional_margin_only_when_valid(tmp_path, margin, expected):
    goal, loader, _, _ = _file_integration(tmp_path)
    inputs = loader(goal)
    inputs = replace(inputs, j6_margin_deg=margin)
    result = ProcessCoordinator(lambda _: inputs).execute(goal)
    assert result.outcome == expected, result
    if expected != 'SUCCEEDED':
        assert not any(c['fn'] in ('move', 'move_spline', 'probe_touch') for c in inputs.adapter.calls)


def test_handoff_functions_share_adapter_and_calibration_without_claiming_path_validation():
    cfg, path, goal, _, evidence = _handoff_settings()
    wc = cfg['workcell']
    geom = cfg['fixed_mount_baseline']['offset_tool_m']
    def surface(pose, direction):
        dx = pose[0] - geom[0] - wc['axis_xy_m'][0]
        if abs(dx) > wc['radius_m']: return None
        y = wc['axis_xy_m'][1] + math.sqrt(wc['radius_m']**2 - dx**2)
        return max(0., pose[1] + geom[1] - y)
    ad = MockRobotAdapter(surface_fn=surface)
    ad.pose = [*wc['axis_xy_m'], .3244, *upright_quat(1)]
    fields = resolve_simulation_settings(cfg, goal, evidence=evidence, adapter=ad)
    cal, ctx = fields['calibration'], fields['context']
    ad.set_tool_offset(cal.offset_tool_m)
    original = json.dumps(path, sort_keys=True)
    assert validate_path(path, ctx) is None
    checked_offsets = []
    inverse = ad.inverse_kinematics
    def ik(pose, offset, ref):
        checked_offsets.append(list(offset))
        return inverse(pose, offset, ref)
    ad.inverse_kinematics = ik
    result = check_path_joints(path, ad, cal.offset_tool_m, ad.observe().joints_rad,
                               limits_deg=fields['joint_limits_deg'], j6_margin_deg=0)
    assert result.ok
    assert checked_offsets and all(v == cal.offset_tool_m for v in checked_offsets)
    result = verify_tool_tip(ad, wc, fields['calibration_profiles'], cal, ctx,
                             tol_m=fields['tip_tolerance_m'])
    assert result.ok and ad.tool_offset_m == cal.offset_tool_m
    result = execute_path(path, ctx, adapter=ad)
    assert result.ok and ad.tool_offset_m == cal.offset_tool_m
    assert json.dumps(path, sort_keys=True) == original
    assert not evidence.path_validation_passed  # 함수 시험은 경로 기하 검증을 대신하지 않는다.
    assert ad.stop(ctx.stop_profile, ctx.stop_profile['confirmation_timeout_s']).ok


@pytest.mark.parametrize('failure', ['ik', 'j5', 'j6'])
def test_cut_middle_point_failure_blocks_all_process_motion(tmp_path, failure):
    goal, loader, ad, files = _file_integration(tmp_path)
    path = json.loads(files['path'].read_bytes())
    base_loader = loader
    def loader(g):
        inputs = base_loader(g)
        inputs.context.tool_profile.update(contact_mode="fixed_depth", depth_m=0.0)
        return inputs
    middle = path['segments'][1]['waypoints'][1]  # CUT 3점 중 기존 표본 검사가 생략한 점
    observe = ad.observe
    ad.observe = lambda: replace(observe(), joints_rad=[0, 0, 0, 0, 0, math.radians(340)])
    def ik(pose, offset, ref):
        if pose == middle and failure == 'ik': return None
        return [0, 0, 0, 0, 175 if pose == middle and failure == 'j5' else 0,
                355 if pose == middle and failure == 'j6' else 340]
    ad.inverse_kinematics = ik
    followups = []
    result = ProcessCoordinator(loader,
        go_to_path_start_fn=lambda *_: followups.append('start'),
        return_home_fn=lambda *_: followups.append('home')).execute(goal)
    assert result.outcome == 'FAILED', result
    assert result.error_code == ('NOT_READY' if failure == 'ik' else 'VALIDATION_FAILED')
    observed = result.observed_state
    assert (observed if failure == 'ik' else observed['worst'])['index'] == 1
    assert followups == []
    assert not any(c['fn'] in ('move', 'move_spline', 'probe_touch') for c in ad.calls)


from c2_process.node import make_simulation_file_loader, _parse_process_args


def _entry_files(tmp_path):
    # 합성 SIM 시험 묶음. 팀의 실측·등록 근거를 생성하는 함수가 아니다.
    goal, _, _, files = _file_integration(tmp_path)
    snap = json.loads(files['snapshot'].read_text())
    data = snap.pop('test_execution')
    snap.update(format='c2-simulation-inputs/1', schema_version=2,
        source_mode='SIMULATION', allow_real=False, frame_id='c2_base',
        workcell=data['workcell'], tip_calibration=data['calibration'],
        calibration_profiles=data['calibration_profiles'],
        execution_context=dict(source_mode='SIMULATION', motion_profiles=data['motion_profiles'],
            tool_profile=data['tool_profile'], stop_profile=data['stop_profile']),
        joint_check_arguments=dict(limits_deg=data['joint_limits_deg'], j6_margin_deg=data['j6_margin_deg']),
        verify_tool_tip_arguments=dict(tol_m=data['tip_tolerance_m']))
    files['snapshot'].write_text(json.dumps(snap))
    sha = hashlib.sha256(files['snapshot'].read_bytes()).hexdigest()
    path = json.loads(files['path'].read_text())
    path['config']['profile_sha256'] = sha
    files['path'].write_text(json.dumps(path))
    goal['path_sha256'] = hashlib.sha256(files['path'].read_bytes()).hexdigest()
    result = json.loads(files['result'].read_text())
    result['path_sha256'] = goal['path_sha256']
    files['result'].write_text(json.dumps(result))
    args = ['--path-file', str(files['path']), '--result-file', str(files['result']),
            '--snapshot-file', str(files['snapshot']), '--snapshot-id', snap['profile_snapshot_id'],
            '--snapshot-sha256', sha]
    return goal, files, args


def test_entry_files_run_existing_functions_without_rewriting_inputs(tmp_path):
    goal, files, args = _entry_files(tmp_path)
    before = {k: p.read_bytes() for k,p in files.items()}
    loader, ros_args = _parse_process_args(args)
    inputs = loader(goal)
    assert type(inputs.adapter) is MockRobotAdapter
    assert not any(c['fn'] in ('move', 'probe_touch', 'move_spline') for c in inputs.adapter.calls)
    result = ProcessCoordinator(loader).execute(goal)
    assert result.outcome == 'SUCCEEDED', result
    assert ros_args == []
    assert {k:p.read_bytes() for k,p in files.items()} == before


@pytest.mark.parametrize('case', ['real', 'path_hash', 'snapshot_hash', 'missing_validation'])
def test_entry_bad_input_never_reaches_motion(tmp_path, case):
    goal, files, args = _entry_files(tmp_path)
    loader, _ = _parse_process_args(args)
    if case == 'real': goal['source_mode'] = 'REAL'
    elif case == 'path_hash': goal['path_sha256'] = 'a'*64
    elif case == 'snapshot_hash': files['snapshot'].write_text('{}')
    else:
        path = json.loads(files['path'].read_text()); path.pop('validation')
        files['path'].write_text(json.dumps(path))
        goal['path_sha256'] = hashlib.sha256(files['path'].read_bytes()).hexdigest()
        result = json.loads(files['result'].read_text()); result['path_sha256'] = goal['path_sha256']
        files['result'].write_text(json.dumps(result))
    with pytest.raises(InputsUnavailable): loader(goal)


def test_entry_loader_does_not_clear_stop_latch(tmp_path):
    goal, _, args = _entry_files(tmp_path)
    loader, _ = _parse_process_args(args)
    inputs = loader(goal)
    inputs.adapter.stopped = True
    assert loader(goal).adapter is inputs.adapter
    result = ProcessCoordinator(loader).execute(goal)
    assert result.outcome != 'SUCCEEDED'
    assert not any(c['fn'] in ('move', 'probe_touch', 'move_spline') for c in inputs.adapter.calls)


@pytest.mark.parametrize('args', [['--path-file', '/missing'], ['--unknown'],
    ['--path-file','/missing','--result-file','/missing','--snapshot-file','/missing',
     '--snapshot-id','id','--snapshot-sha256','0'*64]])
def test_entry_rejects_incomplete_cli(args):
    with pytest.raises(SystemExit) as exc: _parse_process_args(args)
    assert exc.value.code == 2


def test_main_passes_loader_and_ros_args_to_existing_node(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    import c2_process.node as module
    goal, _, args = _entry_files(tmp_path)
    observed = {}
    class Node:
        def get_logger(self): return NS(info=lambda _:None, warn=lambda _:None)
        def destroy_node(self): observed['destroyed'] = True
    class Executor:
        def __init__(self, **kwargs): pass
        def add_node(self, node): pass
        def spin(self):
            # 외부 Action 요청을 대신하는 콜백. 파일 지정 자체로 실행하지 않는다.
            observed['result'] = ProcessCoordinator(observed['loader']).execute(goal)
        def shutdown(self): observed['executor_shutdown'] = True
    def create(**kwargs):
        observed['loader'] = kwargs['load_inputs']
        assert kwargs['runtime_mode'] == 'SIMULATION'
        assert callable(kwargs['preparation_runner_factory'])
        observed['preparation_runner_factory'] = kwargs['preparation_runner_factory']
        return Node()
    monkeypatch.setattr(module, 'create_ros_node', create)
    monkeypatch.setitem(sys.modules, 'rclpy', NS(init=lambda **kw:observed.update(kw),
                                               ok=lambda: True,
                                               shutdown=lambda:observed.update(shutdown=True)))
    monkeypatch.setitem(sys.modules, 'rclpy.executors', NS(MultiThreadedExecutor=Executor))
    module.main(args + ['--ros-args', '-r', '__node:=file_test'])
    assert observed['result'].outcome == 'SUCCEEDED', observed['result']
    assert observed['result'].ok
    assert observed['args'] == ['--ros-args', '-r', '__node:=file_test']
    assert callable(observed['preparation_runner_factory'](ProcessCoordinator()))
    assert observed['destroyed'] and observed['shutdown'] and observed['executor_shutdown']


def _rewrite_entry_hashes(goal, files, args):
    """합성 시험 입력 변경 후 실제 바이트 해시만 다시 계산한다."""
    path = json.loads(files['path'].read_text())
    digest = hashlib.sha256(files['snapshot'].read_bytes()).hexdigest()
    args[args.index('--snapshot-sha256') + 1] = digest
    path['config']['profile_sha256'] = digest
    files['path'].write_text(json.dumps(path))
    goal['path_sha256'] = hashlib.sha256(files['path'].read_bytes()).hexdigest()
    result = json.loads(files['result'].read_text())
    result['path_sha256'] = goal['path_sha256']
    files['result'].write_text(json.dumps(result))


@pytest.mark.parametrize('case', ['external_only', 'legacy_matching', 'wrong_external_id',
                                  'wrong_external_hash', 'conflicting_body_id'])
def test_registered_snapshot_id_reaches_calibration_without_mutating_file(tmp_path, case):
    goal, files, args = _entry_files(tmp_path)
    snapshot = json.loads(files['snapshot'].read_text())
    if case != 'legacy_matching': snapshot.pop('profile_snapshot_id')
    if case == 'conflicting_body_id': snapshot['profile_snapshot_id'] = 'different-body-id'
    files['snapshot'].write_text(json.dumps(snapshot))
    _rewrite_entry_hashes(goal, files, args)
    if case == 'wrong_external_id': args[args.index('--snapshot-id')+1] = 'different-external-id'
    if case == 'wrong_external_hash': args[args.index('--snapshot-sha256')+1] = 'f'*64
    raw = {k:p.read_bytes() for k,p in files.items()}
    loader,_ = _parse_process_args(args)
    if case in ('external_only', 'legacy_matching'):
        inputs = loader(goal)
        assert inputs.calibration_snapshot_id == inputs.path['config']['profile_snapshot_id']
        assert inputs.evidence.profile_snapshot_id == inputs.calibration_snapshot_id
        assert ProcessCoordinator(loader).execute(goal).outcome == 'SUCCEEDED'
        if case == 'external_only': assert 'profile_snapshot_id' not in inputs.snapshot
    else:
        with pytest.raises(InputsUnavailable) as exc: loader(goal)
        assert exc.value.error_code == 'PROFILE_MISMATCH'
    assert {k:p.read_bytes() for k,p in files.items()} == raw


@pytest.mark.parametrize('case', ['no_cut', 'empty_segments', 'empty_cut', 'one_point_cut'])
def test_bad_cut_blocks_ik_tip_and_process_motion_despite_passed_report(tmp_path, case):
    goal, files, args = _entry_files(tmp_path)
    path = json.loads(files['path'].read_text())
    if case == 'no_cut': path['segments'] = [s for s in path['segments'] if s['kind'] != 'CUT']
    elif case == 'empty_segments': path['segments'] = []
    else:
        cut = next(s for s in path['segments'] if s['kind'] == 'CUT')
        cut['waypoints'] = [] if case == 'empty_cut' else cut['waypoints'][:1]
    files['path'].write_text(json.dumps(path))
    _rewrite_entry_hashes(goal, files, args)
    loader,_ = _parse_process_args(args)
    inputs = loader(goal)
    calls=[]
    def forbidden(*a, **kw): calls.append('motion'); return StepResult('SUCCEEDED')
    phases=[]
    result = ProcessCoordinator(lambda _:inputs, verify_tip_fn=forbidden,
        go_to_path_start_fn=forbidden, engrave_fn=forbidden,
        return_home_fn=forbidden).execute(goal, on_phase=phases.append)
    assert result.outcome == 'FAILED', result
    assert calls == [] and 'TOOL_CHECK' not in phases
    assert not any(c['fn'] in ('move','move_spline','probe_touch') for c in inputs.adapter.calls)
    if case in ('no_cut','empty_segments'):
        assert result.error_code == 'INVALID_INPUT'
        assert not any(c['fn']=='ik' for c in inputs.adapter.calls)


class PreparationMockAdapter(MockRobotAdapter):
    """조회만 허용하는 시험 대역. 선택 이름은 명시적 모의값이다."""
    def __init__(self):
        super().__init__()
        self.reads = []
        self.names = ("test_tcp", "test_load")

    def observe(self):
        self.reads.append("observe")
        return super().observe()

    def _read_tool_tcp(self):
        self.reads.append("profiles")
        return self.names


def preparation_inputs():
    adapter = PreparationMockAdapter()
    evidence = PreconditionEvidence(runtime_mode="SIMULATION", robot_state=None,
        control_authority_confirmed=True, stop_latched=False, max_robot_state_age_s=2.0)
    settings = {"tcp_profile_id": "test_tcp", "load_profile_id": "test_load"}
    return adapter, evidence, settings


def test_preparation_reads_state_and_names_without_path_or_motion():
    from c2_process.node import check_preparation_status
    adapter, evidence, settings = preparation_inputs()
    result = check_preparation_status(adapter, evidence, settings)
    assert result.ok
    assert adapter.reads == ["observe", "profiles"]
    assert adapter.calls == []
    assert result.observed_state["tcp"] == "test_tcp"
    assert result.observed_state["physical_confirmation_source"] == "NOT_CHECKED_SIMULATION"


def test_preparation_bad_state_blocks_profile_lookup():
    from c2_process.node import check_preparation_status
    for quality, state_code in [("UNKNOWN", 1), ("VALID", 2)]:
        adapter, evidence, settings = preparation_inputs()
        observe = adapter.observe
        def bad_state():
            state = observe()
            state.quality, state.robot_state = quality, state_code
            return state
        adapter.observe = bad_state
        assert not check_preparation_status(adapter, evidence, settings).ok
        assert adapter.reads == ["observe"]
        assert adapter.calls == []


def test_preparation_mismatched_and_missing_names_block_without_selection():
    from c2_process.node import check_preparation_status
    for names in [("other", "test_load"), ("test_tcp", "other")]:
        adapter, evidence, settings = preparation_inputs()
        adapter.names = names
        assert check_preparation_status(adapter, evidence, settings).error_code == "PROFILE_MISMATCH"
        assert adapter.calls == []
    adapter, evidence, _ = preparation_inputs()
    assert check_preparation_status(adapter, evidence, {}).error_code == "PROFILE_MISMATCH"
    assert adapter.reads == ["observe"]


def test_preparation_query_exception_is_unknown_without_motion():
    from c2_process.node import check_preparation_status
    for method in ("observe", "_read_tool_tcp"):
        adapter, evidence, settings = preparation_inputs()
        def disconnected():
            raise RuntimeError("offline test")
        setattr(adapter, method, disconnected)
        result = check_preparation_status(adapter, evidence, settings)
        assert (result.outcome, result.error_code) == ("UNKNOWN", "COMMUNICATION_LOST")
        assert adapter.calls == []


def test_preparation_cancel_before_and_during_read_blocks_success():
    from c2_process.node import check_preparation_status
    for when in ("before", "observe", "profiles"):
        adapter, evidence, settings = preparation_inputs()
        cancel = threading.Event()
        if when == "before":
            cancel.set()
        else:
            name = "observe" if when == "observe" else "_read_tool_tcp"
            read = getattr(adapter, name)
            def cancelled_read():
                result = read()
                cancel.set()
                return result
            setattr(adapter, name, cancelled_read)
        result = check_preparation_status(adapter, evidence, settings, cancel=cancel)
        assert result.outcome == "STOPPED"
        assert adapter.calls == []
        assert adapter.reads == {"before": [], "observe": ["observe"],
                                 "profiles": ["observe", "profiles"]}[when]


def test_preparation_real_manual_checks_are_not_inputs_and_never_moves():
    from c2_process.node import check_preparation_status
    _, inputs, adapter = real_fixture()
    settings = {"tcp_profile_id": "GripperDA_v1", "load_profile_id": "ToolWeight_1"}
    for changes, expected in [({}, "SUCCEEDED"),
            ({"mount_confirmation_source": "SENSOR"}, "SUCCEEDED"),
            ({"gripper_closed_confirmed": False}, "SUCCEEDED")]:
        result = check_preparation_status(adapter, replace(inputs.evidence, **changes), settings)
        assert result.outcome == expected
    assert adapter.backing.calls == []


def test_real_controller_initialization_runs_only_after_status_and_profile_checks():
    from c2_process.node import check_preparation_status
    _, inputs, adapter = real_fixture()
    settings = {"tcp_profile_id": "GripperDA_v1", "load_profile_id": "ToolWeight_1"}
    calls = []
    original_read = adapter._read_tool_tcp
    adapter._read_tool_tcp = lambda: (calls.append("profiles") or original_read())

    def initialize():
        calls.append("initialize")
        return StepResult("SUCCEEDED", "NONE", observed_state={"singularity_mode": 0})

    result = check_preparation_status(
        adapter, inputs.evidence, settings, initialize_controller=initialize)
    assert result.ok and calls == ["profiles", "initialize"]

    calls.clear()
    adapter._read_tool_tcp = lambda: (calls.append("profiles") or ("wrong", "ToolWeight_1"))
    result = check_preparation_status(
        adapter, inputs.evidence, settings, initialize_controller=initialize)
    assert result.error_code == "PROFILE_MISMATCH"
    assert calls == ["profiles"]


def test_preparation_rejects_mock_for_real_without_observation():
    from c2_process.node import check_preparation_status
    adapter, evidence, settings = preparation_inputs()
    result = check_preparation_status(adapter, replace(evidence, runtime_mode="REAL"), settings)
    assert result.error_code == "SOURCE_MODE_MISMATCH"
    assert adapter.reads == []


# 새 준비 흐름은 내부 SIM 함수 연결 시험. 측정값은 현장 근거가 아닌 명시적 대역이다.
def _preparation_flow_fixture():
    goal, inputs = _team_mock_inputs()
    adapter = inputs.adapter
    adapter._read_tool_tcp = lambda: ("test_tcp", "test_load")
    ctx = ExecutionContext(run_id="prepare-1", source_mode="SIMULATION", cancel=threading.Event(),
                           motion_profiles={}, tool_profile={})
    settings = {"tcp_profile_id": "test_tcp", "load_profile_id": "test_load"}
    def confirm(result):
        if result.observed_state.get("mock_retreat_confirmed") is not True:
            return StepResult("FAILED", "VALIDATION_FAILED", "후퇴 근거 없음", "confirm_measurement")
        return StepResult("SUCCEEDED")
    kwargs = dict(motion_check=lambda a, c: StepResult("SUCCEEDED"),
                  measure=lambda a, c: StepResult("SUCCEEDED", observed_state={
                      "mock_retreat_confirmed": True, "measurement_id": "mock-measurement"}),
                  confirm_result=confirm)
    return goal, inputs, ctx, settings, kwargs


def _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs):
    result = coordinator.prepare(ctx.run_id, ctx, inputs.adapter, inputs.evidence, settings, **kwargs)
    assert result.ok, result
    config = inputs.path["config"]
    assert coordinator.bind_preparation_snapshot(ctx.run_id, config["profile_snapshot_id"],
                                                 config["profile_sha256"]).ok
    return result


@pytest.mark.parametrize("explicit_preparation_id", [True, False])
def test_prepared_execution_rechecks_current_status_without_repeating_tip(explicit_preparation_id):
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    calls, phases = [], []
    def forbidden(*a, **k):
        raise AssertionError("준비 완료 뒤 도구/홈 재호출")
    def joints(path, adapter, offset, current, **kw):
        calls.append("joints")
        assert path["inspection_scope"] == "BOUNDED_FORCE_TOUCH_CANDIDATES"
        assert path["config"] == inputs.path["config"] and adapter is inputs.adapter
        assert offset == inputs.calibration.offset_tool_m
        return StepResult("SUCCEEDED")
    def engrave(path, context, progress, adapter):
        calls.append("engrave")
        assert path == inputs.path and adapter is inputs.adapter
        assert adapter.tool_offset_m == inputs.calibration.offset_tool_m
        return StepResult("SUCCEEDED", observed_state={"last_completed_segment_id": "mock-cut"})
    coordinator = ProcessCoordinator(lambda _: inputs, preparation_required=True,
        joint_check_fn=joints, engrave_fn=engrave, verify_tip_fn=forbidden,
        go_to_path_start_fn=forbidden, return_home_fn=forbidden)
    kwargs["on_phase"] = phases.append
    _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs)
    assert phases == ["ROBOT_STATUS", "MEASUREMENT_PRECHECK", "MEASURE_WORKPIECE", "CONFIRM_MEASUREMENT"]
    # 도구 선택은 반복하지 않고, 실행 직전 현재 상태와 관절만 다시 읽는다.
    inputs.adapter._read_tool_tcp = forbidden
    observe = inputs.adapter.observe
    status_reads=[]
    def current_status():
        status_reads.append('observe')
        return observe()
    inputs.adapter.observe = current_status
    result = coordinator.execute(goal, preparation_id=ctx.run_id if explicit_preparation_id else None)
    assert result.ok, result
    assert status_reads==['observe']
    assert calls == ["joints", "engrave"]
    assert coordinator.execute(goal, preparation_id=ctx.run_id if explicit_preparation_id else None) is result
    assert calls == ["joints", "engrave"]


@pytest.mark.parametrize("quality,robot_state", [("UNKNOWN", 1), ("VALID", 2)])
def test_prepared_execution_blocks_bad_current_state_before_joint_or_motion(quality, robot_state):
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    calls=[]
    coordinator = ProcessCoordinator(lambda _: inputs, preparation_required=True,
        joint_check_fn=lambda *a, **k: calls.append('joints') or StepResult('SUCCEEDED'),
        engrave_fn=lambda *a: calls.append('engrave') or StepResult('SUCCEEDED'))
    _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs)
    observe=inputs.adapter.observe
    def bad_status():
        state=observe()
        state.quality=quality
        state.robot_state=robot_state
        return state
    inputs.adapter.observe=bad_status

    result=coordinator.execute(goal,preparation_id=ctx.run_id)

    assert result.outcome=='FAILED' and result.error_code=='ROBOT_NOT_READY'
    assert calls==[]


def test_prepared_execution_needs_only_bound_tool_offset_not_full_tip_verification():
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    offset = list(inputs.calibration.offset_tool_m)
    inputs = replace(inputs, calibration=None, calibration_profiles={}, tip_tolerance_m=None,
                     tool_offset_m=offset)
    calls = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("준비 완료 뒤 TipCalibration 재검사")

    def joints(_path, _adapter, received_offset, _current, **_kwargs):
        calls.append("joints")
        assert received_offset == offset
        return StepResult("SUCCEEDED")

    def engrave(_path, _context, _progress, adapter):
        calls.append("engrave")
        assert adapter.tool_offset_m == offset
        return StepResult("SUCCEEDED")

    coordinator = ProcessCoordinator(lambda _: inputs, preparation_required=True,
        joint_check_fn=joints, engrave_fn=engrave, verify_tip_fn=forbidden)
    _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs)

    result = coordinator.execute(goal, preparation_id=ctx.run_id)

    assert result.ok, result
    assert calls == ["joints", "engrave"]


def test_prepared_execution_plans_checks_and_runs_entry_before_engraving():
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    workcell = dict(inputs.workcell, entry_planning={"enabled": True})
    inputs = replace(inputs, workcell=workcell)
    calls, phases = [], []
    plan = {"entry_plan_sha256": "entry-sha", "targets": [[1.0] * 7]}

    def plan_entry(path, received_workcell, adapter, state, offset, limits, margin,
                   profiles, **_kwargs):
        calls.append("entry_plan")
        assert path == inputs.path and received_workcell["entry_planning"]["enabled"] is True
        assert adapter is inputs.adapter and state.quality == "VALID"
        return StepResult("SUCCEEDED", observed_state={
            "entry_plan": plan, "entry_plan_sha256": "entry-sha"})

    def joints(_path, _adapter, _offset, _current, **_kwargs):
        calls.append("joints")
        return StepResult("SUCCEEDED")

    def enter(received, adapter, context):
        calls.append("entry")
        assert received == plan and adapter is inputs.adapter
        assert context.checked_entry_plan_sha256 == "entry-sha"
        return StepResult("SUCCEEDED", observed_state={"entry_plan_sha256": "entry-sha"})

    def engrave(_path, _context, _progress, _adapter):
        calls.append("engrave")
        return StepResult("SUCCEEDED")

    coordinator = ProcessCoordinator(
        lambda _: inputs, preparation_required=True, joint_check_fn=joints,
        entry_plan_fn=plan_entry, entry_execute_fn=enter, engrave_fn=engrave)
    _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs)

    result = coordinator.execute(goal, preparation_id=ctx.run_id,
                                 on_phase=phases.append)

    assert result.ok, result
    assert calls == ["entry_plan", "joints", "entry", "engrave"]
    assert phases == ["PRECHECK", "ENTRY", "ENGRAVE", "FINISH"]
    assert result.observed_state["preparation_id"] == ctx.run_id


@pytest.mark.parametrize("stage,outcome", [("motion_check", "FAILED"), ("measure", "FAILED"),
    ("measure", "STOPPED"), ("measure", "UNKNOWN"), ("confirm_result", "FAILED")])
def test_preparation_failure_has_no_success_receipt_or_followup(stage, outcome):
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    calls = []
    for name in tuple(kwargs):
        original = kwargs[name]
        def operation(*args, name=name, original=original):
            calls.append(name)
            return StepResult(outcome, "VALIDATION_FAILED") if name == stage else original(*args)
        kwargs[name] = operation
    coordinator = ProcessCoordinator(lambda _: inputs, preparation_required=True)
    result = coordinator.prepare(ctx.run_id, ctx, inputs.adapter, inputs.evidence, settings, **kwargs)
    assert result.outcome == outcome
    assert calls[-1] == stage
    assert not coordinator.bind_preparation_snapshot(ctx.run_id, "snapshot", "a" * 64).ok
    assert not coordinator.execute(goal, preparation_id=ctx.run_id).ok
    assert inputs.adapter.calls == []


@pytest.mark.parametrize("defect", ["missing_preparation", "unbound", "hash", "adapter", "path_bytes", "ik"])
def test_prepared_execution_blocks_missing_or_wrong_links_before_motion(defect):
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    calls = []
    coordinator = ProcessCoordinator(lambda _: inputs, preparation_required=True,
        joint_check_fn=lambda *a, **k: StepResult("FAILED", "VALIDATION_FAILED") if defect == "ik" else StepResult("SUCCEEDED"),
        engrave_fn=lambda *a: calls.append("engrave") or StepResult("SUCCEEDED"))
    if defect != "missing_preparation":
        _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs)
    if defect == "unbound":
        # 실제 입력은 연결되지 않은 다른 준비 ID를 지정한다.
        ctx.run_id = "not-bound"
    elif defect == "hash":
        path = copy.deepcopy(inputs.path)
        path["config"]["profile_sha256"] = "b" * 64
        inputs = replace(inputs, path=path)
    elif defect == "adapter":
        inputs = replace(inputs, adapter=MockRobotAdapter())
    elif defect == "path_bytes":
        inputs = replace(inputs, path_bytes=inputs.path_bytes + b" ")
    result = coordinator.execute(goal, preparation_id=ctx.run_id)
    assert not result.ok
    assert calls == []


def test_preparation_and_engraving_share_owner_and_stop_confirmation():
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    entered, release = threading.Event(), threading.Event()
    results = []
    def measure(adapter, context):
        entered.set()
        assert release.wait(2)
        assert context.cancel.is_set()
        return StepResult("STOPPED")
    kwargs["measure"] = measure
    coordinator = ProcessCoordinator(lambda _: inputs)
    worker = threading.Thread(target=lambda: results.append(coordinator.prepare(
        ctx.run_id, ctx, inputs.adapter, inputs.evidence, settings, **kwargs)))
    worker.start()
    assert entered.wait(2)
    try:
        assert coordinator.execute(goal).error_code == "BUSY"
        ctx2 = replace(ctx, run_id="prepare-2", cancel=threading.Event())
        assert coordinator.prepare(ctx2.run_id, ctx2, inputs.adapter, inputs.evidence,
                                   settings, **kwargs).error_code == "BUSY"
        assert coordinator.stop(ctx.run_id).accepted
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert results[0].outcome == "STOPPED"
    assert coordinator.active_run_id == ""
    assert any(c["fn"] == "stop" for c in inputs.adapter.calls)


def test_preparation_does_not_start_during_engraving():
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    entered, release = threading.Event(), threading.Event()
    def engrave(*args):
        entered.set()
        assert release.wait(2)
        return StepResult("SUCCEEDED")
    coordinator = ProcessCoordinator(lambda _: inputs, precheck_fn=lambda *a, **k: StepResult("SUCCEEDED"),
        verify_tip_fn=lambda *a, **k: StepResult("SUCCEEDED"), engrave_fn=engrave)
    worker = threading.Thread(target=lambda: coordinator.execute(goal))
    worker.start()
    assert entered.wait(2)
    try:
        assert coordinator.prepare(ctx.run_id, ctx, inputs.adapter, inputs.evidence,
                                   settings, **kwargs).error_code == "BUSY"
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()


def test_remeasurement_invalidates_old_receipt_and_snapshot():
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    coordinator = ProcessCoordinator(lambda _: inputs, preparation_required=True)
    _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs)
    assert coordinator.bind_preparation_snapshot(ctx.run_id, "other", "a" * 64).error_code == "REQUEST_CONFLICT"
    assert coordinator.prepare(ctx.run_id, ctx, inputs.adapter, inputs.evidence,
                               settings, **kwargs).error_code == "REQUEST_CONFLICT"
    newctx = replace(ctx, run_id="prepare-2", cancel=threading.Event())
    kwargs["measure"] = lambda *a: StepResult("FAILED", "VALIDATION_FAILED")
    assert not coordinator.prepare(newctx.run_id, newctx, inputs.adapter, inputs.evidence,
                                   settings, **kwargs).ok
    assert not coordinator.execute(goal, preparation_id=ctx.run_id).ok


def test_preparation_late_cancel_blocks_next_motion_until_stop_is_resolved():
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    def measure(adapter, context):
        context.cancel.set()
        return StepResult("SUCCEEDED")
    kwargs["measure"] = measure
    coordinator = ProcessCoordinator(lambda _: inputs)
    result = coordinator.prepare(ctx.run_id, ctx, inputs.adapter, inputs.evidence, settings, **kwargs)
    assert (result.outcome, result.error_code) == ("UNKNOWN", "STOP_UNCONFIRMED")
    assert coordinator.execute(goal).error_code == "BUSY"


def test_preparation_required_rejects_missing_id_before_loading():
    goal, _ = fixture()
    coordinator = ProcessCoordinator(lambda _: pytest.fail("입력 로드"), preparation_required=True)
    assert coordinator.execute(goal).error_code == "NOT_READY"


@pytest.mark.parametrize("outcome", ["FAILED", "STOPPED", "UNKNOWN"])
def test_prepared_engraving_terminal_results_do_not_trigger_home(outcome):
    goal, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    coordinator = ProcessCoordinator(lambda _: inputs, preparation_required=True,
        joint_check_fn=lambda *a, **k: StepResult("SUCCEEDED"),
        engrave_fn=lambda *a: StepResult(outcome, "TIMEOUT" if outcome == "UNKNOWN" else "NONE"),
        go_to_path_start_fn=lambda *a: pytest.fail("추가 시작 이동"),
        return_home_fn=lambda *a: pytest.fail("자동 홈 복귀"))
    _prepare_and_bind(coordinator, inputs, ctx, settings, kwargs)
    result = coordinator.execute(goal, preparation_id=ctx.run_id)
    assert result.outcome == outcome
    assert [c["fn"] for c in inputs.adapter.calls] == ["set_tool_offset"]


def test_preparation_status_failure_blocks_measurement():
    _, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    coordinator = ProcessCoordinator()
    kwargs["measure"] = lambda *a: pytest.fail("측정 호출")
    evidence = replace(inputs.evidence, control_authority_confirmed=False)
    assert not coordinator.prepare(ctx.run_id, ctx, inputs.adapter, evidence, settings, **kwargs).ok


def test_preparation_confirm_requires_retreat_evidence():
    _, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    kwargs["measure"] = lambda *a: StepResult("SUCCEEDED", observed_state={"measurement_id": "sample"})
    coordinator = ProcessCoordinator()
    result = coordinator.prepare(ctx.run_id, ctx, inputs.adapter, inputs.evidence, settings, **kwargs)
    assert result.error_code == "VALIDATION_FAILED"
    assert not coordinator.bind_preparation_snapshot(ctx.run_id, "sample", "a" * 64).ok


def test_preparation_cancel_from_feedback_sends_no_measurement():
    _, inputs, ctx, settings, kwargs = _preparation_flow_fixture()
    kwargs["measure"] = lambda *a: pytest.fail("취소 후 측정")
    kwargs["on_phase"] = lambda phase: ctx.cancel.set() if phase == "MEASURE_WORKPIECE" else None
    result = ProcessCoordinator().prepare(ctx.run_id, ctx, inputs.adapter, inputs.evidence, settings, **kwargs)
    assert result.outcome == "STOPPED"
    assert inputs.adapter.calls == []

# PR #42의 실제 함수와 JSON 설정을 공정 준비 입구에서 사용한다.
def _workpiece_connection():
    from c2_process.workpiece_calibration import MeasurementContext
    from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter
    config = json.loads((Path(__file__).resolve().parents[1] / "config/workpiece_simulation.json").read_text())
    coordinator = ProcessCoordinator(preparation_required=True)
    context = MeasurementContext("measurement-connected", "prepare-connected", "SIMULATION",
                                 motion_lock=coordinator.motion_lock)
    measurement = SimulatedWorkpieceAdapter(config["workcell"], clock=context.monotonic)
    status = MockRobotAdapter()
    status._read_tool_tcp = lambda: ("sim-tcp", "sim-load")
    evidence = PreconditionEvidence(runtime_mode="SIMULATION", robot_state=None,
        control_authority_confirmed=True, stop_latched=False, max_robot_state_age_s=2.)
    settings = {"tcp_profile_id": "sim-tcp", "load_profile_id": "sim-load"}
    args = (context, status, measurement, config["workcell"], config["profiles"], evidence, settings)
    return coordinator, args


def test_team_workpiece_sim_preparation_eight_points_and_flat_result():
    coordinator, args = _workpiece_connection()
    context, status, adapter, workcell, *_ = args
    before = copy.deepcopy(workcell)
    events = []
    result = coordinator.prepare_workpiece(*args, on_progress=events.append)
    assert result.ok, result
    m = result.observed_state["measurement"]
    assert "measurement" not in m  # HMI가 원본 측정 사전을 한 번만 꺼낸다.
    assert m["measurement_id"] == context.measurement_id
    assert m["preparation_id"] == result.observed_state["preparation_id"] == context.preparation_id
    assert m["axis_xy_m"] == pytest.approx(adapter.center)
    assert m["radius_m"] == pytest.approx(adapter.radius)
    assert m["top_z_m"] == pytest.approx(adapter.top_z)
    assert m["work_v_range_m"] == pytest.approx([.01, .14])
    assert m["position_unit"] == "m" and m["frame_id"] == "c2_base"
    assert m["geometry_ready"] is True and m["validity"] == "SIMULATED"
    assert result.observed_state["partial"] is False
    assert result.observed_state["stop_confirmed"] is True
    assert [e["point_index"] for e in events if e["stage"] == "SIDE_TOUCH" and e["status"] == "SUCCEEDED"] == list(range(1, 9))
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["stage"] == "COMPLETE"
    assert len(result.observed_state["plans"]) == 4  # 홈 진입·윗면·옆면·정상 홈 복귀
    assert result.observed_state["home_return_confirmed"] is True
    assert adapter.calls[-1][1]["label"].startswith("home_")
    assert not coordinator.motion_lock.locked() and status.calls == []
    assert workcell == before
    print("\n[공정 SIM] 상태검사 → 윗면 → 옆면 8/8 → 계산·후퇴 완료")
    print(f"[결과] center={m['axis_xy_m']}, radius={m['radius_m']:.6f} m, top={m['top_z_m']:.6f} m")
    print(f"[근거] validity={m['validity']}, geometry_ready={m['geometry_ready']}, stop_confirmed=True")


@pytest.mark.parametrize("confirmed", [True, False])
def test_team_measurement_cancel_owns_stop_and_keeps_partial(confirmed):
    coordinator, args = _workpiece_connection()
    context, status, adapter, *_ = args
    if not confirmed:
        def stop(profile):
            adapter.calls.append(("stop", profile))
            return StepResult("UNKNOWN", "STOP_UNCONFIRMED", observed_state={"stop_confirmed": False})
        adapter.stop_measurement = stop
    decisions = []
    def progress(event):
        if event["stage"] == "SIDE_TOUCH" and event["status"] == "SUCCEEDED":
            decisions.append(coordinator.stop(context.preparation_id))
    result = coordinator.prepare_workpiece(*args, on_progress=progress)
    assert decisions[0].accepted and decisions[0].stop_state == "ACCEPTED"
    assert result.outcome == ("STOPPED" if confirmed else "UNKNOWN")
    assert result.observed_state["stop_confirmed"] is confirmed
    assert len(result.observed_state["measurement"]["points"]) == 1
    assert result.observed_state["partial"] is True
    assert [k for k, _ in adapter.calls].count("stop") == 1
    assert status.calls == []  # 조각용 stop worker의 중복 호출 없음.
    assert adapter.calls[-2][1]["kind"] == "PROBE"  # 취소 뒤 후퇴 없음.
    assert not coordinator.bind_preparation_snapshot(context.preparation_id, "snapshot", "a" * 64).ok
    if not confirmed:
        goal, _ = fixture()
        assert coordinator.execute(goal, preparation_id=context.preparation_id).error_code == "BUSY"


def test_team_measurement_motion_failure_blocks_receipt_and_keeps_eight_points():
    coordinator, args = _workpiece_connection()
    context, status, adapter, *_ = args
    execute = adapter.execute_measurement_step
    def fail_retract(step, *rest):
        if step["label"] == "point_8_outer":
            adapter.calls.append(("execute", step))
            return StepResult("FAILED", "MOTION_INCOMPLETE")
        return execute(step, *rest)
    adapter.execute_measurement_step = fail_retract
    result = coordinator.prepare_workpiece(*args)
    assert result.outcome == "FAILED" and result.error_code == "MOTION_INCOMPLETE"
    assert len(result.observed_state["measurement"]["points"]) == 8
    assert result.observed_state["measurement"]["geometry_ready"] is False
    assert result.observed_state["stop_confirmed"] is True
    assert adapter.calls[-1][0] == "stop" and status.calls == []
    assert not coordinator.bind_preparation_snapshot(context.preparation_id, "snapshot", "a" * 64).ok


def test_team_measurement_timeout_propagates_after_confirmed_stop():
    coordinator, args = _workpiece_connection()
    context, status, adapter, workcell, *_ = args
    now = [time.monotonic()]
    context.monotonic = lambda: now[0]
    adapter.clock = context.monotonic
    def progress(event):
        if event["stage"] == "SIDE_TOUCH" and event["status"] == "SUCCEEDED":
            now[0] += workcell["runtime_timeout_s"] + 1
    result = coordinator.prepare_workpiece(*args, on_progress=progress)
    assert (result.outcome, result.error_code) == ("FAILED", "TIMEOUT")
    assert result.observed_state["stop_confirmed"] is True
    assert status.calls == []


def test_team_measurement_callback_failure_stops_without_next_point():
    coordinator, args = _workpiece_connection()
    def progress(event):
        if event["stage"] == "SIDE_TOUCH" and event["status"] == "SUCCEEDED":
            raise ConnectionError("HMI feedback lost")
    result = coordinator.prepare_workpiece(*args, on_progress=progress)
    assert (result.outcome, result.error_code) == ("FAILED", "COMMUNICATION_LOST")
    assert result.observed_state["stop_confirmed"] is True
    assert len(result.observed_state["measurement"]["points"]) == 1


def test_team_measurement_and_execute_respect_shared_motion_lock():
    coordinator, args = _workpiece_connection()
    context, _, adapter, *_ = args
    coordinator.motion_lock.acquire()
    try:
        result = coordinator.prepare_workpiece(*args)
        assert result.error_code == "BUSY" and adapter.calls == []
        goal, _ = fixture()
        assert coordinator.execute(goal, preparation_id=context.preparation_id).error_code == "BUSY"
        assert coordinator.motion_lock.locked()
    finally:
        coordinator.motion_lock.release()


def test_team_measurement_blocks_engraving_requests_during_feedback():
    coordinator, args = _workpiece_connection()
    goal, _ = fixture()
    rejected = []
    def progress(event):
        if event["stage"] == "START":
            rejected.append(coordinator.execute(goal, preparation_id=args[0].preparation_id))
    assert coordinator.prepare_workpiece(*args, on_progress=progress).ok
    assert rejected[0].error_code == "BUSY"


@pytest.mark.parametrize("defect", ["geometry", "unit", "id", "nan"])
def test_team_measurement_invalid_success_is_not_preparation_success(monkeypatch, defect):
    import c2_process.node as module
    coordinator, args = _workpiece_connection()
    original = module.measure_workpiece
    def changed(*a, **kw):
        result = original(*a, **kw)
        assert result.ok
        m = result.observed_state["measurement"]
        if defect == "geometry":
            m.update(geometry_ready=False, validity="REFERENCE_ONLY", top_z_m=None,
                     bottom_z_m=None, work_z_range_m=None)
        elif defect == "unit": m["position_unit"] = "mm"
        elif defect == "id": m["measurement_id"] = "other"
        else: m["radius_m"] = math.nan
        return result
    monkeypatch.setattr(module, "measure_workpiece", changed)
    result = coordinator.prepare_workpiece(*args)
    assert not result.ok
    assert "measurement" in result.observed_state  # 거절 원본도 보존.
    assert not coordinator.bind_preparation_snapshot(args[0].preparation_id, "snapshot", "a" * 64).ok


@pytest.mark.parametrize("defect", ["mode", "lock", "state", "config"])
def test_team_measurement_bad_setup_sends_no_measurement_motion(defect):
    coordinator, args = _workpiece_connection()
    args = list(args)
    if defect == "mode": args[0].source_mode = "REAL"
    elif defect == "lock": args[0].motion_lock = threading.Lock()
    elif defect == "state": args[5] = replace(args[5], control_authority_confirmed=False)
    else: args[3]["source_mode"] = "REAL"
    result = coordinator.prepare_workpiece(*args)
    assert not result.ok and args[2].calls == []


def _preparation_request_connection():
    coordinator, args = _workpiece_connection()
    context, status, adapter, workcell, profiles, evidence, settings = args
    request = dict(preparation_id=context.preparation_id, measurement_id=context.measurement_id,
                   source_mode=context.source_mode)
    kwargs = dict(cancel=context.cancel, status_adapter=status, measurement_adapter=adapter,
                  workcell=workcell, profiles=profiles, evidence=evidence, settings=settings)
    return coordinator, request, kwargs


def test_preparation_request_view_real_sim_call_and_feedback_isolation():
    coordinator, request, kwargs = _preparation_request_connection()
    events = []
    before = copy.deepcopy(kwargs['workcell'])
    def feedback(event):
        events.append(copy.deepcopy(event))
        if isinstance(event.get('values'), dict):
            event['values'].clear()  # 소비자 변경으로 측정 원본이 바뀌지 않음
    result = coordinator.prepare_workpiece_request(request, **kwargs, on_feedback=feedback)
    assert result['outcome'] == 'SUCCEEDED'
    assert result['measurement']['axis_xy_m'] == pytest.approx([.4264, .0001])
    assert result['stop_confirmed'] is True and result['partial'] is False
    assert [e['sequence'] for e in events] == list(range(1, len(events)+1))
    assert events[0]['stage'] == 'ROBOT_STATUS'
    assert events[-1]['stage'] == 'CONFIRM_MEASUREMENT'
    assert events[-1]['status'] == 'RUNNING'  # Result만 최종 준비 성공
    measured = [e for e in events if e['origin'] == 'measurement']
    assert [e['measurement_sequence'] for e in measured] == list(range(1,len(measured)+1))
    assert kwargs['workcell'] == before
    saved = coordinator._preparations[request['preparation_id']][0]
    result['measurement']['axis_xy_m'][0] = 999
    assert saved.observed_state['measurement']['axis_xy_m'][0] != 999


@pytest.mark.parametrize('change', [
    {'preparation_id': ''}, {'measurement_id': None}, {'source_mode': 'REAL'},
    {'profile_snapshot_id': 'missing-hash'}, {'operator_confirmed_drill_off': True},
])
def test_preparation_request_invalid_input_has_no_motion(change):
    coordinator, request, kwargs = _preparation_request_connection()
    request.update(change)
    result = coordinator.prepare_workpiece_request(request, **kwargs)
    assert result['outcome'] == 'FAILED' and result['error_code'] == 'INVALID_INPUT'
    assert result['measurement'] is None and result['stop_confirmed'] is None
    assert kwargs['measurement_adapter'].calls == []
    assert kwargs['status_adapter'].calls == []


@pytest.mark.parametrize('confirmed', [True, False])
def test_preparation_request_cancel_view_preserves_stop_evidence(confirmed):
    coordinator, request, kwargs = _preparation_request_connection()
    adapter = kwargs['measurement_adapter']
    if not confirmed:
        adapter.stop_measurement = lambda profile: StepResult(
            'UNKNOWN', 'STOP_UNCONFIRMED', observed_state={'stop_confirmed': False})
    def feedback(event):
        if event['stage'] == 'SIDE_TOUCH' and event['status'] == 'SUCCEEDED':
            kwargs['cancel'].set()
    result = coordinator.prepare_workpiece_request(request, **kwargs, on_feedback=feedback)
    assert result['outcome'] == ('STOPPED' if confirmed else 'UNKNOWN')
    assert result['stop_confirmed'] is confirmed
    assert result['partial'] is True
    assert len(result['measurement']['points']) == 1
    assert request['preparation_id'] not in coordinator._preparations


def test_preparation_request_missing_control_evidence_not_fabricated():
    coordinator, request, kwargs = _preparation_request_connection()
    kwargs['evidence'] = replace(kwargs['evidence'], control_authority_confirmed=False)
    result = coordinator.prepare_workpiece_request(request, **kwargs)
    assert result['outcome'] == 'FAILED'
    assert result['measurement_available'] is False
    assert result['measurement'] is None and result['stop_confirmed'] is None
    assert kwargs['measurement_adapter'].calls == []


def test_preparation_request_feedback_disconnect_stops_measurement():
    coordinator, request, kwargs = _preparation_request_connection()
    def feedback(event):
        if event['stage'] == 'SIDE_TOUCH' and event['status'] == 'SUCCEEDED':
            raise ConnectionError('feedback disconnected')
    result = coordinator.prepare_workpiece_request(request, **kwargs, on_feedback=feedback)
    assert (result['outcome'], result['error_code']) == ('FAILED', 'COMMUNICATION_LOST')
    assert result['stop_confirmed'] is True
    assert len(result['measurement']['points']) == 1


@pytest.mark.parametrize('outcome,stop', [('FAILED', True), ('UNKNOWN', False)])
def test_preparation_result_view_preserves_timeout_and_null(outcome, stop):
    from c2_process.node import preparation_result_view
    raw = StepResult(outcome, 'TIMEOUT', observed_state={
        'stop_confirmed': stop, 'partial': True,
        'measurement': {'top_z_m': None, 'geometry_ready': False}})
    result = preparation_result_view(raw, 'prep', 'measurement')
    assert result['outcome'] == outcome and result['error_code'] == 'TIMEOUT'
    assert result['stop_confirmed'] is stop
    assert result['measurement']['top_z_m'] is None
    result['measurement']['top_z_m'] = 0
    assert raw.observed_state['measurement']['top_z_m'] is None


def test_preparation_request_duplicate_does_not_measure_twice():
    coordinator, request, kwargs = _preparation_request_connection()
    first = coordinator.prepare_workpiece_request(request, **kwargs)
    assert first['outcome'] == 'SUCCEEDED'
    calls = len(kwargs['measurement_adapter'].calls)
    second = coordinator.prepare_workpiece_request(request, **kwargs)
    assert second['outcome'] == 'FAILED'
    assert len(kwargs['measurement_adapter'].calls) == calls


def test_preparation_request_cancel_before_motion_does_not_invent_stop_confirmation():
    coordinator, request, kwargs = _preparation_request_connection()
    kwargs['cancel'].set()
    result = coordinator.prepare_workpiece_request(request, **kwargs)
    assert result['outcome'] == 'STOPPED'
    assert result['stop_confirmed'] is None
    assert result['measurement_available'] is False
    assert kwargs['measurement_adapter'].calls == []


def test_execute_has_no_drill_on_input():
    from dataclasses import fields
    assert 'drill_on_confirmation' not in {f.name for f in fields(ExecutionInputs)}


def test_cancel_blocks_motion_and_same_request_replays():
    goal, inputs = fixture()
    calls = []
    def precheck(*a, **kw):
        coordinator.stop(goal['run_id'])
        return StepResult('SUCCEEDED')
    coordinator = ProcessCoordinator(lambda _: inputs, precheck_fn=precheck,
        validate_engraving_fn=lambda *a: None,
        engrave_fn=lambda *a: calls.append('engrave'),
        verify_tip_fn=lambda *a, **k: calls.append('verify'))
    result = coordinator.execute(goal)
    assert result.outcome == 'STOPPED'
    assert coordinator.execute(goal) is result
    assert calls == []


def test_parse_real_preparation_args_separates_ros_arguments(tmp_path):
    from c2_process.node import _parse_real_preparation_args
    journal = tmp_path / "prepare.sqlite3"
    options, ros_args = _parse_real_preparation_args([
        "--preparation-backend-url", "http://127.0.0.1:8000",
        "--preparation-journal-path", str(journal),
        "--controller-prefix", "/dsr01/dsr_controller2",
        "--control-authority-max-age-s", "0.5",
        "--ros-args", "-r", "__node:=real_prepare",
    ])
    assert options.preparation_backend_url == "http://127.0.0.1:8000"
    assert options.preparation_journal_path == journal
    assert options.controller_prefix == "/dsr01/dsr_controller2"
    assert options.control_authority_max_age_s == pytest.approx(0.5)
    assert options.control_authority_topic == "/dsr01/dsr_controller2/control_authority"
    assert ros_args == ["--ros-args", "-r", "__node:=real_prepare"]


def test_real_prefix_derives_authority_topic_and_strips_trailing_slash(tmp_path):
    from c2_process.node import _parse_real_process_args
    options, _ = _parse_real_process_args([
        "--preparation-backend-url", "http://127.0.0.1:8000",
        "--preparation-journal-path", str(tmp_path / "prepare.sqlite3"),
        "--execution-journal-path", str(tmp_path / "execute.sqlite3"),
        "--controller-prefix", "/cell_a/robot/controller/",
    ])
    assert options.controller_prefix == "/cell_a/robot/controller"
    assert options.control_authority_topic == "/cell_a/robot/controller/control_authority"


def test_real_prefix_rejects_mismatched_authority_topic(tmp_path):
    from c2_process.node import _parse_real_process_args
    with pytest.raises(SystemExit):
        _parse_real_process_args([
            "--preparation-backend-url", "http://127.0.0.1:8000",
            "--preparation-journal-path", str(tmp_path / "prepare.sqlite3"),
            "--execution-journal-path", str(tmp_path / "execute.sqlite3"),
            "--controller-prefix", "/dsr01/dsr_controller2",
            "--control-authority-topic", "/other/control_authority",
        ])


@pytest.mark.parametrize("arguments", [
    ["--preparation-backend-url", "relative/path"],
    ["--controller-prefix", "dsr01/dsr_controller2"],
    ["--control-authority-max-age-s", "0"],
    ["--control-authority-max-age-s", "nan"],
    ["--control-authority-max-age-s", "0.501"],
    ["--control-authority-topic", "relative/topic"],
])
def test_parse_real_preparation_args_rejects_unsafe_values(tmp_path, arguments):
    from c2_process.node import _parse_real_preparation_args
    base = [
        "--preparation-backend-url", "http://127.0.0.1:8000",
        "--preparation-journal-path", str(tmp_path / "prepare.sqlite3"),
        "--controller-prefix", "/dsr01/dsr_controller2",
        "--control-authority-max-age-s", "0.5",
    ]
    for index in range(0, len(arguments), 2):
        key = arguments[index]
        if key in base:
            position = base.index(key)
            base[position + 1] = arguments[index + 1]
        else:
            base.extend((key, arguments[index + 1]))
    with pytest.raises(SystemExit):
        _parse_real_preparation_args(base)



def test_real_observation_options_connect_providers(monkeypatch):
    from types import SimpleNamespace
    import c2_process.real_preparation_observations as observations_module
    from c2_process.node import _real_preparation_options
    made = []
    class Observations:
        def __init__(self, node, **kwargs):
            made.append((node, kwargs))
        def evidence(self, context):
            return {"measurement_id": context.measurement_id}
        def stop_latched(self, context):
            return None
        def record_process_result(self, result, cancel): pass
    monkeypatch.setattr(observations_module, "RealPreparationObservations", Observations)
    class Logger:
        def info(self, message): self.message = message
    class Node:
        def __init__(self): self.logger = Logger()
        def get_logger(self): return self.logger
    node = Node()
    options = SimpleNamespace(
        control_authority_topic="/dsr01/dsr_controller2/control_authority",
        control_authority_max_age_s=.5,
        controller_prefix="/dsr01/dsr_controller2")
    values = _real_preparation_options(node, options)
    assert made == [(node, {
        "topic": options.control_authority_topic, "max_age_s": .5,
        "controller_prefix": options.controller_prefix, "service_timeout_s": .5})]
    assert values["evidence_provider"](SimpleNamespace(measurement_id="m")) == {
        "measurement_id": "m"}
    assert values["stop_latched_provider"](None) is None
    assert values["stop_latch_recorder"].__self__ is node.real_preparation_observations
    assert node.real_preparation_observations is made[0][0].real_preparation_observations
    assert "정지 상태 조회 연결 완료" in node.logger.message


def test_real_preparation_main_wires_measurement_only_node(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    import c2_process.node as module
    journal = tmp_path / 'prepare.sqlite3'
    options = NS(preparation_backend_url='http://127.0.0.1:8000',
                 preparation_journal_path=journal,
                 controller_prefix='/dsr01/dsr_controller2',
                 control_authority_max_age_s=1.0)
    monkeypatch.setattr(module, '_parse_real_preparation_args',
                        lambda args: (options, ['--ros-args']))
    calls = {}
    class Logger:
        def info(self, message): calls['log'] = message
    class Node:
        def get_logger(self): return Logger()
        def destroy_node(self): calls['destroyed'] = True
    server = Node()
    monkeypatch.setattr(module, 'create_ros_node',
                        lambda **kwargs: calls.setdefault('kwargs', kwargs) or server)
    # setdefault returns the dict, so use a normal factory instead.
    def create(**kwargs):
        calls['kwargs'] = kwargs
        return server
    monkeypatch.setattr(module, 'create_ros_node', create)
    class Executor:
        def __init__(self, num_threads): calls['threads'] = num_threads
        def add_node(self, node): calls['node'] = node
        def spin(self): calls['spun'] = True
        def shutdown(self): calls['shutdown'] = True
    fake_rclpy = NS(init=lambda args: calls.setdefault('ros_args', args),
                    ok=lambda: True,
                    shutdown=lambda: calls.setdefault('rclpy_shutdown', True))
    monkeypatch.setitem(sys.modules, 'rclpy', fake_rclpy)
    monkeypatch.setitem(sys.modules, 'rclpy.executors', NS(MultiThreadedExecutor=Executor))
    provider_factory = lambda node: {'provider': node}
    adapter_factory = lambda node: object()
    module.real_preparation_main([], observation_options_factory=provider_factory,
                                 adapter_factory=adapter_factory)
    kwargs = calls['kwargs']
    assert kwargs['runtime_mode'] == 'REAL' and kwargs['measurement_only'] is True
    assert kwargs['load_inputs'] is module._missing_loader
    assert kwargs['preparation_journal_path'] == journal
    assert kwargs['real_adapter_factory'] is adapter_factory
    assert kwargs['real_preparation_options_factory'] is provider_factory
    assert calls['node'] is server and calls['spun'] and calls['destroyed']


def test_real_preparation_main_does_not_shutdown_stopped_context(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    import c2_process.node as module
    calls = []
    options = NS(
        preparation_backend_url='http://127.0.0.1:8000',
        preparation_journal_path=tmp_path / 'prepare.sqlite3',
        controller_prefix='/dsr01/dsr_controller2',
        control_authority_topic='/dsr01/dsr_controller2/control_authority',
        control_authority_max_age_s=.5)
    monkeypatch.setattr(module, '_parse_real_preparation_args',
                        lambda args: (options, []))
    class Node:
        def get_logger(self): return NS(info=lambda message: None)
        def destroy_node(self): calls.append('destroy_node')
    monkeypatch.setattr(module, 'create_ros_node', lambda **kwargs: Node())
    alive = {'value': True}
    class Executor:
        def __init__(self, num_threads): pass
        def add_node(self, node): pass
        def spin(self): alive['value'] = False
        def shutdown(self): calls.append('executor_shutdown')
    fake_rclpy = NS(
        init=lambda args: calls.append('init'), ok=lambda: alive['value'],
        shutdown=lambda: (_ for _ in ()).throw(AssertionError('double shutdown')))
    monkeypatch.setitem(sys.modules, 'rclpy', fake_rclpy)
    monkeypatch.setitem(sys.modules, 'rclpy.executors', NS(MultiThreadedExecutor=Executor))
    module.real_preparation_main(
        [], observation_options_factory=lambda node: {},
        adapter_factory=lambda node: object())
    assert calls == ['init', 'executor_shutdown', 'destroy_node']


def test_real_process_main_wires_one_adapter_preparation_and_execution(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    import c2_process.node as module
    calls = {}
    options = NS(
        preparation_backend_url='http://127.0.0.1:8000',
        preparation_journal_path=tmp_path / 'prepare.sqlite3',
        execution_journal_path=tmp_path / 'execute.sqlite3',
        controller_prefix='/dsr01/dsr_controller2',
        control_authority_topic='/dsr01/dsr_controller2/control_authority',
        control_authority_max_age_s=.5)
    monkeypatch.setattr(module, '_parse_real_process_args',
                        lambda args: (options, ['--ros-args']))

    class Logger:
        def info(self, message): calls['info'] = message
        def warn(self, message): calls['warn'] = message
    class Node:
        def get_logger(self): return Logger()
        def destroy_node(self): calls['destroyed'] = True
    server = Node()
    def create(**kwargs):
        calls['kwargs'] = kwargs
        return server
    monkeypatch.setattr(module, 'create_ros_node', create)
    class Executor:
        def __init__(self, num_threads): calls['threads'] = num_threads
        def add_node(self, node): calls['node'] = node
        def spin(self): calls['spun'] = True
        def shutdown(self): calls['shutdown'] = True
    fake_rclpy = NS(init=lambda args: calls.setdefault('ros_args', args),
                    ok=lambda: True,
                    shutdown=lambda: calls.setdefault('rclpy_shutdown', True))
    monkeypatch.setitem(sys.modules, 'rclpy', fake_rclpy)
    monkeypatch.setitem(sys.modules, 'rclpy.executors', NS(MultiThreadedExecutor=Executor))
    provider_factory = lambda node: {'provider': node}
    adapter_factory = lambda node: object()
    settings_factory = lambda node, adapter: lambda snapshot, goal, snapshot_id: {}

    module.real_process_main(
        [], observation_options_factory=provider_factory,
        adapter_factory=adapter_factory,
        execution_settings_resolver_factory=settings_factory,
        fetch_bytes=lambda url: b'{}')

    kwargs = calls['kwargs']
    assert kwargs['runtime_mode'] == 'REAL'
    assert kwargs['measurement_only'] is False
    assert kwargs['preparation_required'] is True
    assert kwargs['load_inputs'] is module._missing_loader
    assert kwargs['real_adapter_factory'] is adapter_factory
    assert kwargs['real_preparation_options_factory'] is provider_factory
    assert callable(kwargs['real_execution_loader_factory'])
    assert isinstance(kwargs['journal'], module.RunJournal)
    assert calls['node'] is server and calls['spun'] and calls['destroyed']


def test_real_process_main_uses_confirmed_settings_mapper_by_default(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    import c2_process.node as module
    calls = {}
    options = NS(
        preparation_backend_url='http://127.0.0.1:8000',
        preparation_journal_path=tmp_path / 'prepare.sqlite3',
        execution_journal_path=tmp_path / 'execute.sqlite3',
        controller_prefix='/dsr01/dsr_controller2',
        control_authority_topic='/dsr01/dsr_controller2/control_authority',
        control_authority_max_age_s=.5)
    monkeypatch.setattr(module, '_parse_real_process_args', lambda args: (options, []))

    class Logger:
        def info(self, message): pass
        def warn(self, message): pass
    class Node:
        def get_logger(self): return Logger()
        def destroy_node(self): pass
    def create(**kwargs):
        loader = kwargs['real_execution_loader_factory'](Node(), MockRobotAdapter())
        assert callable(loader)
        return Node()
    monkeypatch.setattr(module, 'create_ros_node', create)
    class Executor:
        def __init__(self, num_threads): pass
        def add_node(self, node): pass
        def spin(self): pass
        def shutdown(self): pass
    fake_rclpy = NS(init=lambda args: None, ok=lambda: False, shutdown=lambda: None)
    monkeypatch.setitem(sys.modules, 'rclpy', fake_rclpy)
    monkeypatch.setitem(sys.modules, 'rclpy.executors', NS(MultiThreadedExecutor=Executor))
    module.real_process_main([], adapter_factory=lambda node: object(),
                             observation_options_factory=lambda node: {})


@pytest.mark.parametrize('pid',['candle_approach','candle_cut','candle_travel','candle_retract'])
@pytest.mark.parametrize('field',['vel_mm_s','acc_mm_s2','pos_tol_mm','completion_timeout_s'])
@pytest.mark.parametrize('value',[None,0,-1,True,float('nan')])
def test_real_profiles_reject_missing_or_invalid_motion_before_observe(pid,field,value):
    import c2_process.node as module
    profile,goal,adapter=_complete_real_profile()
    profile['execution_context']['motion_profiles'][pid][field]=value
    adapter.observe=lambda: (_ for _ in ()).throw(AssertionError('static failure observed robot'))
    with pytest.raises(InputsUnavailable,match=field):
        module.resolve_real_execution_settings(profile,goal,'registered-real-profile',adapter=adapter)


def test_real_profiles_require_all_existing_segment_ids_and_explicit_mode():
    from c2_process.node import validate_real_execution_profiles
    profile,_,_=_complete_real_profile()
    execution=profile['execution_context']
    del execution['motion_profiles']['candle_travel']
    with pytest.raises(InputsUnavailable,match='candle_travel'):
        validate_real_execution_profiles(execution)
    profile,_,_=_complete_real_profile()
    execution=profile['execution_context']
    del execution['tool_profile']['contact_mode']
    with pytest.raises(InputsUnavailable,match='contact_mode'):
        validate_real_execution_profiles(execution)


@pytest.mark.parametrize('confirmed',[True,False])
def test_real_stop_consumes_adapter_confirmation_without_duplicate_stop(tmp_path,confirmed):
    goal,inputs,adapter=real_fixture()
    entered,stop_called,release=threading.Event(),threading.Event(),threading.Event()
    output=[]
    stop_calls=[]
    def stop(*args):
        stop_calls.append(threading.get_ident())
        stop_called.set()
        return StepResult('SUCCEEDED' if confirmed else 'UNKNOWN',
                          'NONE' if confirmed else 'STOP_UNCONFIRMED', observed_state={
                              'stop_confirmed':confirmed})
    def verify(*args,**kwargs):
        entered.set()
        context=args[4]
        assert context.cancel.wait(2)
        stopped=stop({},2.)  # 최신 어댑터의 이동/probe 내부 cancel 처리 대역
        assert release.wait(3)
        return StepResult('STOPPED' if confirmed else 'UNKNOWN',
                          'NONE' if confirmed else 'STOP_UNCONFIRMED', observed_state={
                              'stop_confirmed':stopped.observed_state['stop_confirmed']})
    adapter.stop=stop
    coordinator=ProcessCoordinator(lambda _:inputs,runtime_mode='REAL',real_adapter=adapter,
        journal=RunJournal(tmp_path/'runs.sqlite3'),verify_tip_fn=verify,
        go_to_path_start_fn=lambda *a: (_ for _ in ()).throw(AssertionError('next motion')),
        return_home_fn=lambda *a: (_ for _ in ()).throw(AssertionError('home')))
    worker=threading.Thread(target=lambda:output.append(coordinator.execute(goal)))
    worker.start()
    try:
        assert entered.wait(2)
        assert coordinator.stop(goal['run_id']).accepted
        assert stop_called.wait(1)  # 어댑터 함수 반환 전 정지 확인 실행
        assert worker.is_alive() and not output
        assert coordinator.stop(goal['run_id']).accepted
    finally:
        release.set();worker.join(3)
    assert output[0].outcome==('STOPPED' if confirmed else 'UNKNOWN')
    assert output[0].observed_state['stop_confirmed'] is confirmed
    assert len(stop_calls)==1
    if not confirmed:
        assert coordinator._motion_uncertain
        assert coordinator.execute(dict(goal,request_id='new',run_id='new')).error_code=='BUSY'
