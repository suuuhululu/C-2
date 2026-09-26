"""고정 드릴 process_controller_node와 공정 함수 연결.

기본 모드는 SIMULATION이다. REAL은 실물 어댑터·입력 로더·실행 저널과
시작/복귀 함수를 명시적으로 연결한다. 모드와 다른 어댑터는 허용하지 않는다.
"""

import math
import argparse
import sys
import copy
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import quote, urljoin
from urllib.request import urlopen
from uuid import uuid4

from .engraving import ExecutionContext, execute_path, validate_path, build_execution_plan, execution_signature
from .entry_planner import execute_entry_plan, plan_entry_path
from .return_home_planner import execute_return_home_plan, plan_return_home_path
from .engraving_workspace import check_path_workspace, validate_workspace
from .joint_check import check_path_joints, evaluate_path_joints
from .preconditions import PreconditionEvidence, check_preconditions, check_robot_status, check_prepared_path
from .robot_adapter import DoosanRobotAdapter, MockRobotAdapter, RobotState, StepResult, apply_tool_offset
from .state_machine import run_process, run_preparation, run_prepared_process
from .tool_calibration import TipCalibration, verify_tool_tip, upright_quat
from .workpiece_calibration import MeasurementContext, measure_workpiece
from .workpiece_simulation import SimulatedWorkpieceAdapter


def preparation_result_view(result, preparation_id, measurement_id):
    """Python 표시용 복사본. ROS Result 규격이 아니며 null/정지 근거를 보존한다."""
    observed = copy.deepcopy(result.observed_state)
    measurement = observed.get("measurement")
    return dict(preparation_id=preparation_id, measurement_id=measurement_id,
                outcome=result.outcome, error_code=result.error_code, message=result.message,
                completed_step=result.completed_step,
                measurement_available=isinstance(measurement, Mapping),
                measurement=measurement, stop_confirmed=observed.get("stop_confirmed"),
                partial=observed.get("partial"), observed_state=observed)


def preparation_context_from_request(request, *, cancel, motion_lock):
    """현재 MeasurementContext 필드만 사용하는 내부 SIM 요청 변환.

    설정은 호출자가 별도로 해석해 전달한다. 임의 Goal/승인 필드나 UTC 확인
    시각을 여기서 만들지 않는다. 등록 ID/해시 전달은 등록 검증의 대체가 아니다.
    """
    allowed = {"preparation_id", "measurement_id", "source_mode",
               "profile_snapshot_id", "profile_sha256"}
    if not isinstance(request, Mapping) or set(request) - allowed:
        raise ValueError("지원하지 않는 내부 준비 요청 필드")
    for key in ("preparation_id", "measurement_id"):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise ValueError(f"{key} 필요")
    if request.get("source_mode") != "SIMULATION":
        raise ValueError("준비 요청 변환은 SIMULATION 전용")
    if not isinstance(cancel, threading.Event):
        raise ValueError("호출자가 제공한 취소 Event 필요")
    pid, sha = request.get("profile_snapshot_id", ""), request.get("profile_sha256", "")
    if not isinstance(pid, str) or not isinstance(sha, str):
        raise ValueError("설정 참조는 문자열이어야 함")
    if (pid or sha) and (not pid.strip() or len(sha) != 64 or
                        any(c not in "0123456789abcdef" for c in sha)):
        raise ValueError("설정 ID/해시는 함께 제공해야 함")
    return MeasurementContext(request["measurement_id"], request["preparation_id"],
                              request["source_mode"], cancel=cancel, motion_lock=motion_lock,
                              profile_snapshot_id=pid, profile_sha256=sha)


def check_selected_tool_profiles(adapter, settings: Mapping) -> StepResult:
    """선택된 TCP/하중 이름만 읽어 비교한다. 설정 변경·모드 전환 없음."""
    tcp_id, load_id = settings.get("tcp_profile_id"), settings.get("load_profile_id")
    if any(not isinstance(value, str) or not value.strip() for value in (tcp_id, load_id)):
        return StepResult("FAILED", "PROFILE_MISMATCH", "TCP/하중 프로파일 ID 없음", "robot_status")
    try:
        tcp, tool = adapter._read_tool_tcp()
    except Exception as exc:
        return StepResult("UNKNOWN", "COMMUNICATION_LOST", f"TCP/하중 조회 실패: {exc}", "robot_status")
    observed = {"tcp": tcp, "tool": tool}
    if tcp != tcp_id or tool != load_id:
        return StepResult("FAILED", "PROFILE_MISMATCH", "제어기 TCP/하중과 설정 불일치",
                          "robot_status", observed)
    return StepResult("SUCCEEDED", "NONE", "TCP/하중 이름 확인", "robot_status", observed)


def check_preparation_status(adapter, evidence: PreconditionEvidence, settings: Mapping,
                             *, cancel=None, on_observation=None,
                             initialize_controller=None) -> StepResult:
    """경로 생성 전 상태검사의 함수 진입점. 측정·조각·그리퍼 명령 없음.

    HMI 준비 요청과 연결할 내부 함수이며 새 ROS 인터페이스가 아니다.
    settings는 기대 TCP/하중 이름을 포함한다. 작업자 확인값을 자동 생성하지 않는다.
    취소 시 이 함수는 모션을 보내지 않으므로 실제 로봇 정지 확인으로 해석하지 않는다.
    """
    def cancelled():
        return StepResult("STOPPED", "NONE", "상태검사 취소 (모션 없음)", "robot_status")

    if cancel is not None and cancel.is_set():
        return cancelled()
    if (evidence.runtime_mode not in {"REAL", "SIMULATION"}
            or (evidence.runtime_mode == "REAL" and not isinstance(adapter, DoosanRobotAdapter))
            or (evidence.runtime_mode == "SIMULATION" and not isinstance(adapter, MockRobotAdapter))):
        return StepResult("FAILED", "SOURCE_MODE_MISMATCH", "상태검사와 어댑터 모드 불일치", "robot_status")
    try:
        state = adapter.observe()
    except Exception as exc:
        if callable(on_observation):
            on_observation(None, None, None)
        return StepResult("UNKNOWN", "COMMUNICATION_LOST", f"상태 조회 실패: {exc}", "robot_status")
    if callable(on_observation):
        on_observation(state, getattr(adapter, "tool_offset_m", None),
                       evidence.max_robot_state_age_s)
    if cancel is not None and cancel.is_set():
        return cancelled()
    checked = check_robot_status(replace(evidence, robot_state=state))
    if not checked.ok:
        return checked
    selected = check_selected_tool_profiles(adapter, settings)
    if cancel is not None and cancel.is_set():
        return cancelled()
    if not selected.ok:
        return selected
    if initialize_controller is not None:
        if not callable(initialize_controller):
            return StepResult("FAILED", "INVALID_INPUT", "제어기 초기화 함수 오류", "robot_status")
        initialized = initialize_controller()
        if not isinstance(initialized, StepResult):
            return StepResult("UNKNOWN", "INTERNAL_ERROR", "제어기 초기화 반환 형식 오류", "robot_status")
        if not initialized.ok:
            return initialized
        if cancel is not None and cancel.is_set():
            return cancelled()
    return StepResult("SUCCEEDED", "NONE", "준비 상태검사 통과", "robot_status",
                      {**checked.observed_state, **selected.observed_state,
                       **(initialized.observed_state if initialize_controller is not None else {}),
                       "robot_state": state.robot_state, "measured_at": state.measured_at})


@dataclass(frozen=True)
class ExecutionInputs:
    """승인된 저장소에서 ID로 읽은 한 실행의 불변 입력. 로더가 파일 원본도 제공한다."""

    path: Mapping
    path_bytes: bytes
    snapshot: Mapping
    snapshot_bytes: bytes
    evidence: PreconditionEvidence
    context: object
    adapter: object
    workcell: Mapping
    calibration_profiles: Mapping
    calibration: Optional[TipCalibration]
    calibration_snapshot_id: str
    tip_tolerance_m: Optional[float]
    joint_limits_deg: object = None
    j6_margin_deg: Optional[float] = None
    tool_offset_m: object = None


@dataclass(frozen=True)
class StopDecision:
    accepted: bool
    stop_state: str
    error_code: str
    message: str


@dataclass
class _ActiveRun:
    request_id: str
    run_id: str
    cancel: threading.Event
    adapter: Optional[object] = None
    context: Optional[object] = None
    measurement_owned_stop: bool = False
    stop_requested: bool = False
    stop_done: threading.Event = None
    stop_result: Optional[StepResult] = None

    def __post_init__(self):
        self.stop_done = threading.Event()


def _missing_loader(_goal):
    raise InputsUnavailable("경로·설정 ID를 승인된 원본 파일로 해석하는 로더가 연결되지 않음")


class InputsUnavailable(Exception):
    """모션 시작 전에 확인된 입력 부재/불일치. 오류 코드를 공정까지 보존한다."""

    def __init__(self, message, error_code="NOT_READY"):
        super().__init__(message)
        self.error_code = error_code



def build_execution_settings(goal, *, evidence, adapter, workcell, calibration_record,
                             calibration_snapshot_id, calibration_profiles, motion_profiles,
                             tool_profile, stop_profile, tip_tolerance_m, joint_limits_deg,
                             j6_margin_deg, require_tool_verification=True, tool_offset_m=None):
    """매퍼가 추출한 기존 함수 인자를 묶는다. 팀 파일 내부 배치를 정의하지 않는다.

    호출자는 각 설정이 검증된 스냅샷에 속함을 확인해야 한다. adapter/evidence는
    실행 프로그램에서 주입하고, 이 함수는 관측·모션·승인 근거 생성을 하지 않는다.
    """
    def invalid(message):
        raise InputsUnavailable(message, "INVALID_INPUT")

    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    def vector(value, length):
        return isinstance(value, (list, tuple)) and len(value) == length and all(map(finite, value))

    if (not isinstance(goal, Mapping) or not isinstance(goal.get("run_id"), str)
            or not goal["run_id"] or goal.get("source_mode") not in ("SIMULATION", "REAL")):
        invalid("실행 맥락의 run_id/source_mode 오류")
    if not isinstance(evidence, PreconditionEvidence) or evidence.runtime_mode != goal["source_mode"]:
        invalid("실행 근거의 모드 불일치")
    if (not isinstance(calibration_snapshot_id, str) or not calibration_snapshot_id
            or calibration_snapshot_id != evidence.profile_snapshot_id):
        raise InputsUnavailable("도구 오프셋의 스냅샷 연결 근거 불일치", "PROFILE_MISMATCH")
    required_mappings = (("workcell", workcell), ("motion_profiles", motion_profiles),
                         ("tool_profile", tool_profile), ("stop_profile", stop_profile))
    if require_tool_verification:
        required_mappings += (("calibration_record", calibration_record),
                              ("calibration_profiles", calibration_profiles))
    for name, value in required_mappings:
        if not isinstance(value, Mapping) or not value:
            invalid(f"{name} 설정 없음 또는 형식 오류")
        try:
            json.dumps(dict(value), allow_nan=False)
        except (TypeError, ValueError):
            invalid(f"{name}에 비유한 값 또는 직렬화할 수 없는 값 포함")
    if (not vector(workcell.get("axis_xy_m"), 2) or not finite(workcell.get("radius_m"))
            or workcell["radius_m"] <= 0 or not finite(workcell.get("top_z_m"))):
        invalid("작업대 axis_xy_m/radius_m/top_z_m 오류 (단위 m)")
    calibration = None
    if require_tool_verification:
        try:
            calibration = TipCalibration(**copy.deepcopy(dict(calibration_record)))
        except TypeError as exc:
            invalid(f"TipCalibration 필드 오류: {exc}")
        if (calibration.tool_id != "engraving_drill" or not finite(calibration.projection_m)
                or not 0 < calibration.projection_m <= 0.110
                or not finite(calibration.lateral_x_m) or not vector(calibration.offset_tool_m, 3)
                or not vector(calibration.axis_fit_xy_m, 2) or not finite(calibration.z_m)
                or not finite(calibration.residual_rms_m) or calibration.residual_rms_m < 0
                or type(calibration.side) is not int or calibration.side not in (-1, 1)):
            invalid("드릴 보정 기록의 도구/치수/방향 오류")
        expected = [calibration.lateral_x_m, -calibration.projection_m, 0.0]
        if any(not math.isclose(a, b, rel_tol=0, abs_tol=1e-9)
               for a, b in zip(calibration.offset_tool_m, expected)):
            invalid("돌출 길이·옆 어긋남과 offset_tool_m 불일치")
        if not isinstance(calibration_profiles.get("travel"), Mapping) or not calibration_profiles["travel"]:
            invalid("도구 확인 travel 프로파일 없음")
        if not finite(tip_tolerance_m) or tip_tolerance_m <= 0:
            invalid("도구 확인 허용차 설정 오류")
        tool_offset_m = calibration.offset_tool_m
    if not vector(tool_offset_m, 3):
        invalid("준비 결과에 연결된 드릴 오프셋 없음")
    if (not isinstance(joint_limits_deg, (list, tuple)) or len(joint_limits_deg) != 6
            or any(not vector(pair, 2) or pair[0] >= pair[1] for pair in joint_limits_deg)
            or not finite(j6_margin_deg) or j6_margin_deg < 0
            or 2 * j6_margin_deg >= joint_limits_deg[5][1] - joint_limits_deg[5][0]):
        invalid("관절 한계·J6 여유 설정 오류")
    # J6 margin은 추가 여유다. limits에 여유가 반영됐다면 0을 허용한다.
    # JSON 설정은 복사하고 런타임 어댑터는 동일 객체를 유지한다. 요청마다 새 취소 이벤트.
    return dict(evidence=evidence, adapter=adapter,
                context=ExecutionContext(goal["run_id"], goal["source_mode"], threading.Event(),
                                         copy.deepcopy(dict(motion_profiles)), copy.deepcopy(dict(tool_profile)),
                                         copy.deepcopy(dict(stop_profile)),
                                         joint_limits_deg=copy.deepcopy(joint_limits_deg),
                                         j6_margin_deg=j6_margin_deg),
                workcell=copy.deepcopy(dict(workcell)), calibration=calibration,
                calibration_profiles=copy.deepcopy(dict(calibration_profiles or {})),
                calibration_snapshot_id=calibration_snapshot_id, tip_tolerance_m=tip_tolerance_m,
                joint_limits_deg=copy.deepcopy(joint_limits_deg), j6_margin_deg=j6_margin_deg,
                tool_offset_m=copy.deepcopy(list(tool_offset_m)))



def resolve_simulation_settings(snapshot, goal, *, evidence, adapter):
    """9/20 handoff의 SIM 설정을 기존 인자로 매핑한다. 등록/검증 근거는 만들지 않는다.

    load_execution_inputs의 resolve_settings 콜백에서 사용할 수 있지만 원본
    handoff 경로에는 config/validation/Result가 없으므로 파일 로더 전체 입력은 아니다.
    REAL 및 실제 어댑터는 거절한다. 실행 ID·cancel은 현재 요청에서 새로 구성하고,
    파일의 ref_joints_rad는 사용하지 않는다(관절 검사는 어댑터 관측값 사용).
    """
    def invalid(message):
        raise InputsUnavailable(message, "INVALID_INPUT")

    if not isinstance(snapshot, Mapping) or not isinstance(goal, Mapping):
        invalid("SIM 설정/요청 형식 오류")
    if (snapshot.get("source_mode") != "SIMULATION" or goal.get("source_mode") != "SIMULATION"
            or snapshot.get("test_only") is not True or snapshot.get("allow_real") is not False
            or not isinstance(adapter, MockRobotAdapter)):
        raise InputsUnavailable("handoff 설정은 MockRobotAdapter SIMULATION 전용", "NOT_READY")
    if (snapshot.get("format") != "c2-simulation-inputs/1"
            or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 2
            or snapshot.get("frame_id") != "c2_base"):
        invalid("지원하지 않는 handoff 형식·버전·좌표계")
    context = snapshot.get("execution_context")
    joints = snapshot.get("joint_check_arguments")
    verify = snapshot.get("verify_tool_tip_arguments")
    if not all(isinstance(v, Mapping) for v in (context, joints, verify)):
        invalid("execution_context/joint_check_arguments/verify_tool_tip_arguments 누락")
    if context.get("source_mode") != "SIMULATION":
        raise InputsUnavailable("handoff 실행 맥락 모드 불일치", "SOURCE_MODE_MISMATCH")
    # 파일 로더가 원본 해시·경로 config·외부 등록정보를 대조한 ID를 사용한다.
    # 과거 SIM 파일의 본문 ID는 선택 사항이며, 있으면 일치해야 한다.
    if ("profile_snapshot_id" in snapshot
            and snapshot["profile_snapshot_id"] != evidence.profile_snapshot_id):
        raise InputsUnavailable("스냅샷 내부와 실행 근거의 등록 ID 불일치", "PROFILE_MISMATCH")
    # fixed_mount_baseline은 실험 참고값이다. 모의 TipCalibration과 섞지 않는다.
    return build_execution_settings(
        goal, evidence=evidence, adapter=adapter, workcell=snapshot.get("workcell"),
        calibration_record=snapshot.get("tip_calibration"),
        calibration_snapshot_id=evidence.profile_snapshot_id,
        calibration_profiles=snapshot.get("calibration_profiles"),
        motion_profiles=context.get("motion_profiles"), tool_profile=context.get("tool_profile"),
        stop_profile=context.get("stop_profile"), tip_tolerance_m=verify.get("tol_m"),
        joint_limits_deg=joints.get("limits_deg"), j6_margin_deg=joints.get("j6_margin_deg"))


def validate_real_execution_profiles(execution):
    """측정과 무관한 REAL 실행 설정 검사. 값 생성·로봇 조회는 하지 않는다."""
    def positive(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0

    def invalid(message):
        raise InputsUnavailable(message, "INVALID_INPUT")

    if not isinstance(execution, Mapping) or execution.get("source_mode") != "REAL":
        invalid("REAL execution_context 모드/형식 오류")
    profiles = execution.get("motion_profiles")
    if not isinstance(profiles, Mapping):
        invalid("REAL motion_profiles 없음")
    for pid in ("candle_approach", "candle_cut", "candle_travel", "candle_retract"):
        if pid not in profiles:
            invalid(f"REAL motion_profiles.{pid} 없음")
    for pid, profile in profiles.items():
        if not isinstance(profile, Mapping):
            invalid(f"REAL motion_profiles.{pid} 형식 오류")
        for key in ("vel_mm_s", "acc_mm_s2", "pos_tol_mm", "completion_timeout_s"):
            if not positive(profile.get(key)):
                invalid(f"REAL motion_profiles.{pid}.{key} 양수 필요")
    policy = execution.get("entry_planning")
    if not isinstance(policy, Mapping) or policy.get("enabled") is not True:
        invalid("REAL execution_context.entry_planning.enabled=true 설정 필요")
    try:
        validate_workspace(execution.get("engraving_workspace"))
    except ValueError as exc:
        invalid(str(exc))
    bounds = policy.get("tcp_clearance_above_top_range_m")
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in bounds)
            or bounds[0] <= 0 or bounds[0] > bounds[1]):
        invalid("REAL entry_planning.tcp_clearance_above_top_range_m 범위 오류")
    for key in ("tcp_z_step_m", "sample_m", "sample_deg", "min_radial_gap_m",
                "min_j3_abs_deg", "min_j5_margin_deg", "max_joint_step_deg",
                "start_position_tolerance_m", "start_angle_tolerance_deg"):
        if not positive(policy.get(key)):
            invalid(f"REAL entry_planning.{key} 양수 필요")
    if (policy["tcp_z_step_m"] > bounds[1] - bounds[0]
            and not math.isclose(bounds[0], bounds[1])):
        invalid("REAL entry_planning.tcp_z_step_m이 탐색 범위보다 큼")
    profile_id = policy.get("motion_profile_id")
    if not isinstance(profile_id, str) or not profile_id or profile_id not in profiles:
        invalid("REAL entry_planning.motion_profile_id가 이동 프로파일에 없음")
    tool = execution.get("tool_profile")
    if not isinstance(tool, Mapping) or tool.get("contact_mode") not in ("fixed_depth", "force_touch"):
        invalid("REAL tool_profile.contact_mode 명시 필요")
    clearance = tool.get("clearance_m")
    if isinstance(clearance, Mapping):
        clearance = clearance.get("stroke")
    if not positive(clearance):
        invalid("REAL tool_profile.clearance_m 양수 필요")
    if tool["contact_mode"] == "fixed_depth":
        depth = tool.get("depth_m")
        if type(depth) not in (int, float) or not math.isfinite(depth) or depth < 0:
            invalid("REAL fixed_depth depth_m 비음수 필요")
    else:
        for key in ("touch_force_n", "touch_speed_mm_s"):
            if not positive(tool.get(key)):
                invalid(f"REAL force_touch {key} 양수 필요")
    cut_contact = tool.get("cut_contact")
    if cut_contact is not None:
        if tool["contact_mode"] != "force_touch":
            invalid("REAL cut_contact는 force_touch에서만 사용 가능")
        if cut_contact not in ("normal_force_hold", "chunk_adaptive"):
            invalid(f"REAL cut_contact {cut_contact!r} 미지원")
        if tool.get("tool_axis") not in ("x", "+x", "-x", "y", "+y", "-y", "z", "+z", "-z"):
            invalid("REAL cut_contact.tool_axis ±x/±y/±z 명시 필요")
        for key in ("force_limit_n", "air_force_limit_n"):
            if not positive(tool.get(key)):
                invalid(f"REAL cut_contact.{key} 양수 필요")
        bounds = tool.get("touch_offset_range_m")
        extra = tool.get("touch_extra_m")
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
                or bounds[0] > bounds[1] or type(extra) not in (int, float)
                or not math.isfinite(extra) or extra < 0
                or bounds[0] < -clearance or bounds[1] > extra):
            invalid("REAL cut_contact.touch_offset_range_m/clearance_m/touch_extra_m 범위 오류")
        if cut_contact == "normal_force_hold":
            stiffness = tool.get("cut_stiffness")
            ramp = tool.get("ramp_s")
            if not positive(tool.get("cut_force_n")):
                invalid("REAL normal_force_hold.cut_force_n 양수 필요")
            if (not isinstance(stiffness, (list, tuple)) or len(stiffness) != 6
                    or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                           for v in stiffness)):
                invalid("REAL normal_force_hold.cut_stiffness 6축 범위 오류")
            if (type(ramp) not in (int, float) or not math.isfinite(ramp)
                    or not 0 <= ramp <= 1):
                invalid("REAL normal_force_hold.ramp_s 0~1 범위 오류")
        else:
            low, high = tool.get("cut_force_min_n"), tool.get("cut_force_max_n")
            points = tool.get("adaptive_chunk_points")
            if not positive(low) or not positive(high) or low > high:
                invalid("REAL chunk_adaptive.cut_force_min_n/cut_force_max_n 범위 오류")
            if not positive(tool.get("adaptive_step_m")):
                invalid("REAL chunk_adaptive.adaptive_step_m 양수 필요")
            if type(points) is not int or not 2 <= points <= 80:
                invalid("REAL chunk_adaptive.adaptive_chunk_points 2~80 정수 필요")
    stop = execution.get("stop_profile")
    if (not isinstance(stop, Mapping) or type(stop.get("mode")) is not int
            or not positive(stop.get("confirmation_timeout_s"))):
        invalid("REAL 정지 방식 또는 확인 timeout 누락")


def resolve_real_execution_settings(snapshot, goal, profile_snapshot_id, *, adapter,
                                    evidence_provider=None):
    """확정된 REAL profile 배치를 기존 ``ExecutionInputs`` 설정으로 변환한다.

    HMI 저장소의 등록 ID는 profile 본문에 자기참조로 넣지 않으므로 호출자가
    대조를 마친 ``profile_snapshot_id``를 별도로 전달한다. 누락값이나 미리보기
    전용 표시는 기본값으로 보완하지 않고 모션 전에 거절한다.
    """
    def unavailable(message, code="NOT_READY"):
        raise InputsUnavailable(message, code)

    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    def vector(value, length):
        return (isinstance(value, (list, tuple)) and len(value) == length
                and all(finite(item) for item in value))

    if not isinstance(snapshot, Mapping) or not isinstance(goal, Mapping):
        unavailable("REAL 설정/요청 형식 오류", "INVALID_INPUT")
    if snapshot.get("source_mode") != "REAL" or goal.get("source_mode") != "REAL":
        unavailable("REAL 설정/요청 모드 불일치", "SOURCE_MODE_MISMATCH")
    if (snapshot.get("schema_version") != 2 or snapshot.get("frame_id") != "c2_base"
            or snapshot.get("tool_id") != "engraving_drill"):
        unavailable("REAL profile 스키마·좌표계·도구 불일치", "INVALID_INPUT")
    if (snapshot.get("test_only") is not False
            or snapshot.get("real_execution_allowed") is not True
            or ("preview_only" in snapshot and snapshot["preview_only"] is not False)
            or ("geometry_ready" in snapshot and snapshot["geometry_ready"] is not True)):
        unavailable("실행 승인되지 않은 REAL profile")
    if snapshot.get("gripper_open_allowed") is not False:
        unavailable("고정 드릴 profile의 그리퍼 열기 금지 설정 불일치", "INVALID_INPUT")
    if (not isinstance(profile_snapshot_id, str) or not profile_snapshot_id
            or snapshot.get("tcp_id") != "GripperDA_v1"
            or snapshot.get("load_id") != "ToolWeight_1"):
        unavailable("등록 snapshot ID 또는 TCP/load ID 없음", "PROFILE_MISMATCH")

    workcell = snapshot.get("workcell")
    surface = snapshot.get("surface")
    if not isinstance(workcell, Mapping) or not isinstance(surface, Mapping):
        unavailable("REAL workcell/surface 설정 없음", "INVALID_INPUT")
    if (not vector(workcell.get("axis_xy_m"), 2)
            or not finite(workcell.get("radius_m")) or workcell["radius_m"] <= 0
            or not finite(workcell.get("top_z_m"))):
        unavailable("REAL workcell 중심·반지름·윗면 높이 누락", "INVALID_INPUT")
    origin = surface.get("axis_origin_m")
    radius_mm, height_mm = surface.get("radius_mm"), surface.get("height_mm")
    if (surface.get("kind") != "cylinder" or not vector(origin, 3)
            or not finite(radius_mm) or radius_mm <= 0
            or not finite(height_mm) or height_mm <= 0):
        unavailable("REAL surface 원통 기하 누락", "INVALID_INPUT")
    expected_top = origin[2] + height_mm / 1000.0
    if (not math.isclose(workcell["axis_xy_m"][0], origin[0], rel_tol=0, abs_tol=1e-9)
            or not math.isclose(workcell["axis_xy_m"][1], origin[1], rel_tol=0, abs_tol=1e-9)
            or not math.isclose(workcell["radius_m"], radius_mm / 1000.0, rel_tol=0, abs_tol=1e-9)
            or not math.isclose(workcell["top_z_m"], expected_top, rel_tol=0, abs_tol=1e-9)):
        unavailable("REAL workcell과 surface 기하 불일치", "PROFILE_MISMATCH")

    execution = snapshot.get("execution_context")
    joints = snapshot.get("joint_check_arguments")
    if not all(isinstance(value, Mapping) for value in (execution, joints)):
        unavailable("REAL execution_context/관절 설정 없음", "INVALID_INPUT")
    if execution.get("source_mode") != "REAL":
        unavailable("REAL execution_context 모드 불일치", "SOURCE_MODE_MISMATCH")
    validate_real_execution_profiles(execution)
    if workcell.get("entry_planning") != execution.get("entry_planning"):
        unavailable("REAL workcell과 execution_context entry_planning 불일치", "PROFILE_MISMATCH")
    try:
        same_workspace = (validate_workspace(workcell.get("engraving_workspace"))
                          == validate_workspace(execution.get("engraving_workspace")))
    except ValueError as exc:
        unavailable(str(exc), "INVALID_INPUT")
    if not same_workspace:
        unavailable("REAL 조각 작업영역 설정 불일치", "PROFILE_MISMATCH")
    stop_profile = execution.get("stop_profile")
    if (not isinstance(stop_profile, Mapping)
            or type(stop_profile.get("mode")) is not int
            or not finite(stop_profile.get("confirmation_timeout_s"))
            or stop_profile["confirmation_timeout_s"] <= 0):
        unavailable("REAL 정지 방식 또는 확인 timeout 누락", "INVALID_INPUT")

    if evidence_provider is None:
        try:
            state = adapter.observe()
        except Exception as exc:
            unavailable(f"최종 관절 검사 시작 상태 조회 실패: {exc}", "COMMUNICATION_LOST")
        # 매퍼 단독 사용은 제어권·정지 근거를 만들지 않는다. REAL 노드는
        # 아래 provider를 주입하며, 미주입 결과는 실행 직전 상태 검사에서 fail closed다.
        evidence = PreconditionEvidence(
            runtime_mode="REAL", robot_state=state,
            profile_snapshot_id=profile_snapshot_id)
    else:
        try:
            evidence = evidence_provider(profile_snapshot_id)
        except InputsUnavailable:
            raise
        except Exception as exc:
            unavailable(f"실행 직전 상태 근거 조회 실패: {exc}", "COMMUNICATION_LOST")
        if (not isinstance(evidence, PreconditionEvidence)
                or evidence.runtime_mode != "REAL"
                or evidence.profile_snapshot_id != profile_snapshot_id):
            unavailable("실행 직전 상태 근거의 모드·스냅샷 불일치", "PROFILE_MISMATCH")
    tip = snapshot.get("tip_calibration")
    tool_offset_m = tip.get("offset_tool_m") if isinstance(tip, Mapping) else None
    return build_execution_settings(
        goal, evidence=evidence, adapter=adapter, workcell=workcell,
        calibration_record=None,
        calibration_snapshot_id=profile_snapshot_id,
        calibration_profiles=None,
        motion_profiles=execution.get("motion_profiles"),
        tool_profile=execution.get("tool_profile"),
        stop_profile=stop_profile,
        tip_tolerance_m=None,
        joint_limits_deg=joints.get("limits_deg"),
        j6_margin_deg=joints.get("j6_margin_deg"),
        require_tool_verification=False, tool_offset_m=tool_offset_m)


def load_execution_inputs(goal, *, path_file=None, snapshot_file=None,
                          path_bytes=None, snapshot_bytes=None, result_file=None,
                          generation_result=None, validation_report_file=None,
                          validation_report_bytes=None, snapshot_metadata=None,
                          resolve_settings=None):
    """호출자가 지정한 경로·스냅샷과 파일/메모리 결과를 읽는다. 새 ROS 필드 없음.

    resolve_settings(snapshot, goal, profile_snapshot_id)는 승인/현장 근거와 스냅샷 내부 설정을
    ExecutionInputs의 나머지 필드로 매핑한다. 팀 스냅샷 배치는 아직 미확정이라
    기본 구현으로 추측하지 않는다. 이 함수와 매퍼는 모션을 호출하지 않는다.
    경로는 Goal/브라우저 입력이 아니라 호출자의 명시적 인자로만 받는다.
    result_file 또는 실제 수신/저장한 generation_result 중 하나를 전달한다.
    snapshot_metadata는 관리 저장소에서 조회한 id/sha256이다. 파일에 ID를 삽입하지 않는다.
    """
    def fail(code, message):
        raise InputsUnavailable(message, code)

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"중복 JSON 키: {key}")
            value[key] = item
        return value

    def bad_constant(value):
        raise ValueError(f"유한하지 않은 JSON 수: {value}")

    def read_json(filename, raw, label):
        if (filename is None) == (raw is None):
            fail("INVALID_INPUT", f"{label} 파일 경로 또는 원본 바이트 중 하나만 필요")
        if raw is None:
            try:
                raw = Path(filename).read_bytes()
            except (OSError, TypeError, ValueError) as exc:
                fail("NOT_READY", f"{label} 파일 읽기 실패: {exc}")
        elif not isinstance(raw, bytes):
            fail("INVALID_INPUT", f"{label} 원본은 bytes여야 함")
        try:
            obj = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
            # 1e999처럼 문법은 JSON이지만 Python에서 inf로 변환되는 수도 거절.
            json.dumps(obj, allow_nan=False)
        except (ValueError, TypeError, UnicodeError) as exc:
            fail("INVALID_INPUT", f"{label} JSON 오류: {exc}")
        if not isinstance(obj, dict):
            fail("INVALID_INPUT", f"{label}는 JSON 객체여야 함")
        return raw, obj

    if not isinstance(goal, Mapping) or type(goal.get("schema_version")) is not int or goal["schema_version"] != 2:
        fail("UNSUPPORTED_SCHEMA_VERSION", "실행 요청은 v2만 지원")
    path_bytes, path = read_json(path_file, path_bytes, "경로")
    if (result_file is None) == (generation_result is None):
        fail("INVALID_INPUT", "result_file 또는 generation_result 중 하나만 필요")
    if result_file is not None:
        _, result = read_json(result_file, None, "경로 결과")
    else:
        if not isinstance(generation_result, Mapping):
            fail("INVALID_INPUT", "경로 생성 결과는 Mapping이어야 함")
        try:
            result = json.loads(json.dumps(dict(generation_result), allow_nan=False))
        except (ValueError, TypeError):
            fail("INVALID_INPUT", "경로 생성 결과에 비유한 값 또는 잘못된 자료형 포함")
    snapshot_bytes, snapshot = read_json(snapshot_file, snapshot_bytes, "스냅샷")
    if type(path.get("schema_version")) is not int or path["schema_version"] != 2:
        fail("UNSUPPORTED_SCHEMA_VERSION", "경로는 v2만 지원")
    for obj in (goal, path, result):
        if (not isinstance(obj.get("path_id"), str) or not obj["path_id"]
                or type(obj.get("path_version")) is not int or obj["path_version"] < 1):
            fail("INVALID_INPUT", "경로 ID/버전 누락 또는 형식 오류")
    for key in ("path_id", "path_version"):
        if not goal[key] == path[key] == result[key]:
            fail("PATH_MISMATCH", f"요청·경로·결과의 {key} 불일치")
    digest = hashlib.sha256(path_bytes).hexdigest()
    if goal.get("path_sha256") != digest or result.get("path_sha256") != digest:
        fail("PATH_MISMATCH", "최종 경로 파일 바이트 SHA-256 불일치")
    if (result.get("success") is not True or result.get("error_code") != "NONE"
            or result.get("validation_passed") is not True):
        fail("VALIDATION_UNAVAILABLE", "경로 결과가 성공/검증 통과가 아님")
    validation = path.get("validation")
    if (not isinstance(validation, dict) or validation.get("passed") is not True
            or not isinstance(validation.get("report_id"), str) or not validation["report_id"]
            or validation["report_id"] != result.get("validation_report_id")):
        fail("VALIDATION_UNAVAILABLE", "경로·결과의 검증 결과/보고서 ID 불일치")
    if validation_report_file is not None or validation_report_bytes is not None:
        _, report = read_json(validation_report_file, validation_report_bytes, "검증 보고서")
        if ("path_id" in report and report["path_id"] != path["path_id"]
                or "path_version" in report and report["path_version"] != path["path_version"]):
            fail("PATH_MISMATCH", "검증 보고서의 경로 ID/버전 불일치")
        if "path_sha256" in report and report["path_sha256"] != digest:
            fail("PATH_MISMATCH", "검증 보고서의 경로 SHA-256 불일치")
        not_checked = report.get("not_checked")
        if (not isinstance(not_checked, list)
                or any(not isinstance(item, str) for item in not_checked)):
            fail("VALIDATION_UNAVAILABLE", "검증 보고서 미검사 목록 형식 오류")
        # c2_path 원본 보고서도 execution_readiness를 포함한다.
        # HMI 외피 형식은 고유 필드 geometry_passed로 구별한다.
        if "geometry_passed" in report:
            readiness = report.get("execution_readiness")
            if (report.get("geometry_passed") is not True
                    or not isinstance(readiness, Mapping)
                    or not isinstance(readiness.get("executability"), str)
                    or not readiness["executability"]
                    or (readiness.get("runtime_checks_passed") is not None
                        and type(readiness["runtime_checks_passed"]) is not bool)
                    or type(readiness.get("trial_authorized")) is not bool):
                fail("VALIDATION_UNAVAILABLE", "HMI 검증 보고서가 통과/완전한 결과가 아님")
            checks = validation.get("checks")
            path_not_checked = validation.get("not_checked")
            if (not isinstance(checks, list) or not checks
                    or any(not isinstance(item, Mapping) or item.get("passed") is not True
                           for item in checks)
                    or not isinstance(path_not_checked, list)
                    or any(not isinstance(item, str) for item in path_not_checked)):
                fail("VALIDATION_UNAVAILABLE", "경로 내부 검증 요약 형식 오류")
        else:
            if (report.get("passed") is not True or report.get("errors") not in (None, [])
                    or report.get("mapping_failures") not in (None, [])):
                fail("VALIDATION_UNAVAILABLE", "검증 보고서가 통과/완전한 결과가 아님")
            checks = report.get("checks")
            if (not isinstance(checks, list) or not checks
                    or any(not isinstance(item, Mapping) or item.get("passed") is not True
                           for item in checks)):
                fail("VALIDATION_UNAVAILABLE", "검증 보고서 항목 형식 오류")
            expected_validation = {
                "report_id": result.get("validation_report_id"),
                "passed": True,
                "checks": checks,
                "not_checked": not_checked,
            }
            if validation != expected_validation:
                fail("VALIDATION_UNAVAILABLE", "경로 내부 검증 요약과 원본 보고서 불일치")
    elif goal["source_mode"] == "REAL":
        fail("VALIDATION_UNAVAILABLE", "REAL 실행에는 원본 validation report가 필요")
    config = path.get("config")
    if not isinstance(config, dict):
        fail("INVALID_INPUT", "경로 config 없음")
    if hashlib.sha256(snapshot_bytes).hexdigest() != config.get("profile_sha256"):
        fail("PROFILE_MISMATCH", "최종 스냅샷 파일 바이트 SHA-256 불일치")
    snapshot_id = config.get("profile_snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        fail("PROFILE_MISMATCH", "경로의 스냅샷 ID 없음")
    if snapshot_metadata is not None:
        if (not isinstance(snapshot_metadata, Mapping)
                or snapshot_metadata.get("id") != snapshot_id
                or snapshot_metadata.get("sha256") != hashlib.sha256(snapshot_bytes).hexdigest()):
            fail("PROFILE_MISMATCH", "관리 저장소의 스냅샷 ID/해시 불일치")
        if "profile_snapshot_id" in snapshot and snapshot["profile_snapshot_id"] != snapshot_id:
            fail("PROFILE_MISMATCH", "스냅샷 내부와 등록 ID 불일치")
    elif snapshot_id != snapshot.get("profile_snapshot_id"):
        fail("PROFILE_MISMATCH", "스냅샷 ID 불일치; 외부 등록 ID는 snapshot_metadata 필요")
    # c2_path/서버 스냅샷은 tcp_id/load_id, 경로 config는 *_profile_id를 사용한다.
    aliases = {"tcp_profile_id": "tcp_id", "tcp_profile_version": "tcp_version",
               "load_profile_id": "load_id", "load_profile_version": "load_version"}
    for key in ("tool_id", "tool_version", "workcell_id", "workcell_version",
                "tools_config_id", "tools_config_version", "tcp_profile_id", "tcp_profile_version",
                "load_profile_id", "load_profile_version"):
        alias = aliases.get(key)
        if alias and key in snapshot and alias in snapshot and snapshot[key] != snapshot[alias]:
            fail("PROFILE_MISMATCH", f"스냅샷 {key}/{alias} 중복 정의 불일치")
        value = snapshot[key] if key in snapshot else snapshot.get(alias) if alias else None
        if key in config and config[key] != value:
            fail("PROFILE_MISMATCH", f"경로와 스냅샷 {key} 불일치 또는 누락")
    if path.get("frame_id") != snapshot.get("frame_id"):
        fail("FRAME_MISMATCH", "경로와 스냅샷 frame_id 불일치")
    if goal.get("source_mode") not in ("SIMULATION", "REAL") or path.get("source_mode") != goal["source_mode"]:
        fail("SOURCE_MODE_MISMATCH", "요청·경로 모드 불일치")
    if goal["source_mode"] == "REAL" and any(
            item.get("test_only") is not None and item.get("test_only") is not False
            for item in (path, config, snapshot)):
        fail("NOT_READY", "시험 전용 파일은 REAL에 사용할 수 없음")
    if not callable(resolve_settings):
        fail("NOT_READY", "파일 대조 완료; 스냅샷 보정·프로파일/현장 근거 매퍼 미연결")
    # 매퍼가 원본 파일 해시와 연결된 데이터를 수정할 수 없게 복사본만 전달.
    settings = resolve_settings(copy.deepcopy(snapshot), dict(goal), snapshot_id)
    if not isinstance(settings, Mapping):
        fail("NOT_READY", "설정 매퍼는 ExecutionInputs의 나머지 필드 Mapping을 반환해야 함")
    fields = {"evidence", "context", "adapter", "workcell", "calibration_profiles", "calibration",
              "calibration_snapshot_id", "tip_tolerance_m", "joint_limits_deg", "j6_margin_deg",
              "tool_offset_m"}
    legacy_fields = fields - {"tool_offset_m"}
    if set(settings) == legacy_fields and isinstance(settings.get("calibration"), TipCalibration):
        settings = dict(settings, tool_offset_m=copy.deepcopy(settings["calibration"].offset_tool_m))
    if set(settings) != fields:
        fail("NOT_READY", f"설정 매퍼 필드 누락/초과: {sorted(set(settings) ^ fields)}")
    evidence = settings["evidence"]
    if (not isinstance(evidence, PreconditionEvidence)
            or evidence.profile_snapshot_id != config["profile_snapshot_id"]
            or settings["calibration_snapshot_id"] != config["profile_snapshot_id"]):
        fail("PROFILE_MISMATCH", "설정/보정의 스냅샷 연결 근거 불일치")
    # 여기서 갱신하는 것은 파일에서 직접 확인한 검증 결과뿐이다.
    # 제어권·장착·그리퍼 확인을 생성하거나 True로 채우지 않는다.
    settings = dict(settings, evidence=replace(evidence, path_validation_passed=True,
                                               validation_path_sha256=digest))
    return ExecutionInputs(path=path, path_bytes=path_bytes, snapshot=snapshot,
                           snapshot_bytes=snapshot_bytes, **settings)


def make_asset_bundle_loader(resolve_assets, resolve_settings):
    """HMI 저장소 조회 결과를 기존 실행 검사기에 연결한다.

    ``resolve_assets(goal)``은 요청의 ID·버전으로 조회한 원본을 다음 키로
        반환한다: path_bytes, snapshot_bytes, generation_result,
        validation_report_bytes, snapshot_metadata. 이 함수는 저장소 주소나 JSON 내부 설정 배치를 새로
    정하지 않는다. 조회 구현은 HMI 저장소가 보존한 원본 바이트를 그대로
    반환해야 하며, 아래 ``load_execution_inputs``가 Goal·경로·결과·스냅샷의
    ID와 SHA-256을 다시 대조한다.
    """
    if not callable(resolve_assets) or not callable(resolve_settings):
        raise ValueError("자산 조회 함수와 설정 매퍼가 필요함")

    def load(goal):
        try:
            assets = resolve_assets(dict(goal))
        except InputsUnavailable:
            raise
        except Exception as exc:
            raise InputsUnavailable(f"HMI 실행 자산 조회 실패: {exc}") from exc
        if not isinstance(assets, Mapping):
            raise InputsUnavailable("HMI 실행 자산 조회 결과 형식 오류", "INVALID_INPUT")
        required = {"path_bytes", "snapshot_bytes", "generation_result",
                    "validation_report_bytes", "snapshot_metadata"}
        if set(assets) != required:
            raise InputsUnavailable(
                f"HMI 실행 자산 필드 누락/초과: {sorted(set(assets) ^ required)}",
                "INVALID_INPUT")
        return load_execution_inputs(
            goal,
            path_bytes=assets["path_bytes"],
            snapshot_bytes=assets["snapshot_bytes"],
            generation_result=assets["generation_result"],
            validation_report_bytes=assets["validation_report_bytes"],
            snapshot_metadata=assets["snapshot_metadata"],
            resolve_settings=resolve_settings,
        )

    return load


def make_hmi_asset_resolver(backend_url, *, fetch_bytes=None, timeout_s=5.0):
    """기존 HMI path/version·asset content API에서 실행 원본을 읽는다.

    HTTP 응답을 승인으로 바꾸지 않는다. 이 함수는 저장된 바이트와 GeneratePath
    메타데이터를 가져오기만 하며, 실제 ID·버전·해시·검증·REAL 시험 파일 거절은
    ``load_execution_inputs``가 담당한다. 시험에서는 ``fetch_bytes(url)``을 주입한다.
    """
    if not isinstance(backend_url, str) or not backend_url.strip():
        raise ValueError("HMI backend URL 필요")
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("HMI 조회 timeout은 양수여야 함")
    base = backend_url.rstrip("/") + "/"

    if fetch_bytes is None:
        def fetch_bytes(url):
            with urlopen(url, timeout=float(timeout_s)) as response:
                return response.read()
    elif not callable(fetch_bytes):
        raise ValueError("fetch_bytes는 호출 가능해야 함")

    def fetch(relative_or_absolute):
        url = urljoin(base, relative_or_absolute)
        raw = fetch_bytes(url)
        if not isinstance(raw, bytes):
            raise InputsUnavailable("HMI 자산 응답은 bytes여야 함", "INVALID_INPUT")
        return raw

    def resolve(goal):
        if (not isinstance(goal, Mapping) or not isinstance(goal.get("path_id"), str)
                or not goal["path_id"] or type(goal.get("path_version")) is not int
                or goal["path_version"] < 1):
            raise InputsUnavailable("HMI 경로 조회 ID/버전 오류", "INVALID_INPUT")
        metadata_raw = fetch(
            f"api/operator/paths/{quote(goal['path_id'], safe='')}/versions/{goal['path_version']}")
        try:
            metadata = json.loads(metadata_raw)
        except (ValueError, UnicodeError, TypeError) as exc:
            raise InputsUnavailable(f"HMI 경로 메타데이터 JSON 오류: {exc}", "INVALID_INPUT") from exc
        if not isinstance(metadata, dict):
            raise InputsUnavailable("HMI 경로 메타데이터는 JSON 객체여야 함", "INVALID_INPUT")
        path_asset_id = metadata.get("path_asset_id")
        validation_report_id = metadata.get("validation_report_id")
        snapshot_id = metadata.get("profile_snapshot_id")
        snapshot_sha256 = metadata.get("profile_sha256")
        if (not isinstance(path_asset_id, str) or not path_asset_id
                or not isinstance(validation_report_id, str) or not validation_report_id
                or not isinstance(snapshot_id, str) or not snapshot_id
                or not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64):
            raise InputsUnavailable("HMI 경로의 원본 경로/스냅샷 참조 없음", "NOT_READY")
        return {
            "path_bytes": fetch(f"api/operator/assets/{quote(path_asset_id, safe='')}/content"),
            "validation_report_bytes": fetch(
                f"api/operator/assets/{quote(validation_report_id, safe='')}/content"),
            "snapshot_bytes": fetch(f"api/operator/assets/{quote(snapshot_id, safe='')}/content"),
            "generation_result": metadata,
            "snapshot_metadata": {"id": snapshot_id, "sha256": snapshot_sha256},
        }

    return resolve



class RunJournal:
    """프로세스 재시작 뒤 같은 요청이 다시 모션을 시작하지 못하게 하는 로컬 기록.

    SQLite 파일 위치는 호출자가 정한다. 이전 실행이 결과를 기록하기 전에
    프로세스가 죽었다면 그 요청은 UNKNOWN으로 남기고 자동 재시도하지 않는다.
    """

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.parent.is_dir():
            raise FileNotFoundError(f"실행 기록 디렉터리 없음: {self.path.parent}")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS process_runs (
                request_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                identity_json TEXT NOT NULL,
                result_json TEXT,
                created_at_ns INTEGER NOT NULL
            )""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5.0)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, request_id, identity) -> Optional[StepResult]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT identity_json, result_json FROM process_runs WHERE request_id=?",
                             (request_id,)).fetchone()
            if row:
                if tuple(json.loads(row[0])) != identity:
                    return StepResult("FAILED", "REQUEST_CONFLICT", "같은 요청 ID에 다른 실행 입력", "precheck")
                if row[1] is None:
                    return StepResult("UNKNOWN", "STORAGE_ERROR", "이전 실행 결과 미확인; 자동 재시작 금지", "precheck")
                saved = json.loads(row[1])
                return StepResult(**saved)
            old_run = db.execute("SELECT request_id FROM process_runs WHERE run_id=?", (identity[0],)).fetchone()
            if old_run:
                return StepResult("FAILED", "RUN_MISMATCH", "사용한 run_id의 새 요청 금지", "precheck")
            db.execute("INSERT INTO process_runs VALUES (?,?,?,?,?)",
                       (request_id, identity[0], json.dumps(identity), None, time.time_ns()))
        return None

    def finish(self, request_id, result: StepResult):
        payload = json.dumps({"outcome": result.outcome, "error_code": result.error_code,
                              "message": result.message, "completed_step": result.completed_step,
                              "observed_state": result.observed_state}, ensure_ascii=False, allow_nan=False)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("UPDATE process_runs SET result_json=? WHERE request_id=? AND result_json IS NULL",
                                 (payload, request_id))
            if updated.rowcount != 1:
                raise RuntimeError("예약되지 않았거나 이미 종료한 실행")



class ObservationCache:
    """기존 observe 결과만 보관한다. 발행 타이머는 드라이버를 호출하지 않는다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sample = None

    def capture(self, state, offset, max_age_s, *, now=None, utc_ns=None):
        now = time.monotonic() if now is None else now
        utc_ns = time.time_ns() if utc_ns is None else utc_ns
        measured = getattr(state, "measured_at", None)
        valid_time = (type(measured) in (int, float) and math.isfinite(measured)
                      and 0 < measured <= now)
        age_limit = (max_age_s if type(max_age_s) in (int, float)
                     and math.isfinite(max_age_s) and max_age_s > 0 else 0)
        stamp = max(0, utc_ns - int((now - measured) * 1e9)) if valid_time else 0
        with self.lock:
            self.sample = (copy.deepcopy(state), copy.deepcopy(offset), age_limit,
                           measured if valid_time else 0, stamp)

    def values(self, *, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            sample = copy.deepcopy(self.sample)
        out = dict(joints=[], joints_quality="UNKNOWN", joints_stamp_ns=0,
                   tcp_pose=None, tcp_quality="UNKNOWN", tcp_stamp_ns=0, frame_id="",
                   robot_connection_state="UNKNOWN", robot_mode="UNKNOWN",
                   robot_quality="UNKNOWN", robot_stamp_ns=0, robot_state_code=None,
                   temperature=[], temperature_quality="UNSUPPORTED")
        if sample is None:
            return out
        state, offset, max_age, measured, stamp = sample
        def vector(v, n):
            return (isinstance(v, (list, tuple)) and len(v) == n
                    and all(type(x) in (int, float) and math.isfinite(x) for x in v))
        quality = getattr(state, "quality", "UNKNOWN")
        if quality != "VALID" or not measured or not max_age or now < measured:
            return out
        quality = "VALID" if now - measured <= max_age else "STALE"
        joints = getattr(state, "joints_rad", None)
        if vector(joints, 6):
            out.update(joints=[float(v) for v in joints], joints_quality=quality, joints_stamp_ns=stamp)
        pose = getattr(state, "tcp_pose", None)
        frame = getattr(state, "frame_id", "")
        if (frame == "c2_base" and vector(pose, 7)
                and math.isclose(sum(v*v for v in pose[3:]), 1, abs_tol=1e-5)
                and (offset is None or vector(offset, 3))):
            # observe.tcp_pose는 오프셋 적용 시 도구 끝이다. 제어기 TCP로 환산한다.
            tcp = apply_tool_offset(pose, offset, -1) if offset is not None else list(pose)
            out.update(tcp_pose=[float(v) for v in tcp], tcp_quality=quality, tcp_stamp_ns=stamp, frame_id=frame)
        code = getattr(state, "robot_state", None)
        if type(code) is int and code >= 0:
            out.update(robot_quality=quality, robot_stamp_ns=stamp,
                       robot_state_code=code,
                       robot_connection_state="CONNECTED" if quality == "VALID" else "UNKNOWN")
            # robot_state는 동작 상태이며 수동/자동 robot_mode와 다르다. 모드는 미확인 유지.
        return out

    def capture_measurement(self, observation, offset, max_age_s, *, now=None, utc_ns=None):
        """측정 어댑터의 검증된 관측 dict를 공용 RobotState 캐시에 넣는다."""
        if not isinstance(observation, Mapping):
            self.capture(None, None, None, now=now, utc_ns=utc_ns)
            return
        measured = observation.get("measured_at_monotonic_s")
        state = RobotState(
            joints_rad=copy.deepcopy(observation.get("joints_rad")),
            tcp_pose=copy.deepcopy(observation.get("tip_pose")),
            frame_id=observation.get("frame_id", ""),
            robot_state=observation.get("robot_state"),
            quality=observation.get("quality", "UNKNOWN"),
            measured_at=measured,
        )
        self.capture(state, offset, max_age_s, now=now, utc_ns=utc_ns)


def prepared_binding_observation_valid(values, authority_owner) -> bool:
    """준비 뒤 상시 관측이 기존 BIND를 계속 보유할 수 있는지만 판정한다.

    새 실행 승인을 만들거나 기본 상태를 재검사하지 않는다. 준비 때 확인한
    제어권/연결 근거가 상실·만료되거나 확인된 보호정지 상태가 되면 False다.
    """
    if not isinstance(values, Mapping):
        return False
    if (values.get("robot_connection_state") != "CONNECTED"
            or values.get("robot_quality") != "VALID"):
        return False
    # 설치 드라이버의 기존 상태 코드 계약. 미지원/미확인 코드는 승인으로 만들지 않는다.
    if values.get("robot_state_code") in {3, 5, 6, 9, 10}:
        return False
    cache = getattr(authority_owner, "cache", None)
    fresh = getattr(cache, "fresh", None)
    if not callable(fresh):
        return False
    observation = fresh()
    return bool(observation is not None
                and observation.active and observation.connected
                and observation.valid and observation.has_control)


def defer_prepared_binding_invalidation(status, phase, active_run) -> bool:
    """장시간 PRECHECK 중의 일시적인 관측 만료만 BIND 삭제에서 제외한다.

    실행 허가를 만드는 함수가 아니다. PRECHECK가 끝난 뒤에는 새로 읽은 로봇
    상태·제어권·정지 상태와 동일 BIND를 다시 검사해야 한다.
    """
    return status == "RUNNING" and phase == "PRECHECK" and active_run is not None


def read_real_execution_evidence(node, profile_snapshot_id):
    """ExecuteProcess 진입 직전의 읽기 전용 REAL 상태 근거를 만든다.

    준비 측정, TCP/load 선택, 정지 해제, 모션을 수행하지 않는다.
    제어권 관측과 정지/대기 상태 조회가 완전히 확인된 경우만
    ``check_robot_status``가 통과할 근거를 반환한다.
    """
    owner = getattr(node, "real_preparation_observations", None)
    cache = getattr(owner, "cache", None)
    fresh = getattr(cache, "fresh", None)
    stop_latched = getattr(owner, "stop_latched", None)
    max_age_s = getattr(cache, "max_age_s", None)
    if not callable(fresh) or not callable(stop_latched):
        raise InputsUnavailable("실행 직전 제어권·정지 관측 미연결", "NOT_READY")
    try:
        stopped = stop_latched(None)
        authority = fresh()
    except Exception as exc:
        raise InputsUnavailable(f"실행 직전 제어권·정지 조회 실패: {exc}",
                                "COMMUNICATION_LOST") from exc
    authority_confirmed = bool(
        authority is not None and authority.active and authority.connected
        and authority.valid and authority.has_control)
    return PreconditionEvidence(
        # 현재 로봇 상태와 관절은 ProcessCoordinator PRECHECK에서
        # adapter.observe()로 한 번만 읽고 이 근거에 결합한다.
        runtime_mode="REAL", robot_state=None,
        control_authority_confirmed=authority_confirmed,
        stop_latched=stopped, profile_snapshot_id=profile_snapshot_id,
        max_robot_state_age_s=max_age_s)


class ProcessAlarms:
    """공정 오류만 추적한다. 같은 경로·설정의 PRECHECK 재통과만 자동 해소한다."""

    def __init__(self):
        self.active = {}
        self.lock = threading.Lock()

    def update(self, scope, phase, result):
        events = []
        with self.lock:
            if result.outcome in {"FAILED", "UNKNOWN"}:
                key = (scope, phase, result.error_code)
                if key not in self.active:
                    self.active[key] = result.outcome
                    events.append(("ALARM_RAISED", result.error_code, result.message, "ERROR"))
                if result.outcome == "UNKNOWN":
                    self.active[key] = "UNKNOWN"  # 미확인 장애는 재검사 성공만으로 해소하지 않음.
            elif result.ok and phase == "PRECHECK":
                for key in list(self.active):
                    if key[0] == scope and key[1] == "PRECHECK" and self.active[key] == "FAILED":
                        del self.active[key]
                        events.append(("ALARM_CLEARED", key[2], "동일 경로·설정 사전검사 재통과", "INFO"))
        return events


class ProcessCoordinator:
    """ROS 콜백과 독립적인 단일 실행 소유자. 의존 함수를 주입해 모의시험한다."""

    def __init__(
        self,
        load_inputs: Callable[[Mapping], ExecutionInputs] = _missing_loader,
        *,
        precheck_fn=check_preconditions,
        joint_check_fn=check_path_joints,
        validate_engraving_fn=validate_path,
        verify_tip_fn=verify_tool_tip,
        engrave_fn=execute_path,
        entry_plan_fn=plan_entry_path,
        entry_execute_fn=execute_entry_plan,
        return_home_plan_fn=plan_return_home_path,
        return_home_execute_fn=execute_return_home_plan,
        journal: Optional[RunJournal] = None,
        runtime_mode: str = "SIMULATION",
        real_adapter: Optional[DoosanRobotAdapter] = None,
        go_to_path_start_fn=None,
        return_home_fn=None,
        observation_cache=None, on_precheck_result=None,
        preparation_required=False, measurement_only=False,
    ):
        if runtime_mode not in {"SIMULATION", "REAL"}:
            raise ValueError("runtime_mode은 SIMULATION 또는 REAL이어야 함")
        if runtime_mode == "SIMULATION" and real_adapter is not None:
            raise ValueError("SIMULATION에 실물 어댑터를 연결할 수 없음")
        if runtime_mode == "REAL":
            if not isinstance(real_adapter, DoosanRobotAdapter):
                raise ValueError("REAL에는 DoosanRobotAdapter 객체가 필요함")
            if not measurement_only and (journal is None or load_inputs is _missing_loader):
                raise ValueError("REAL에는 입력 로더와 실행 저널이 필요함")
            if (not measurement_only and not preparation_required
                    and (not callable(go_to_path_start_fn) or not callable(return_home_fn))):
                raise ValueError("REAL에는 시작점 이동·홈 복귀 함수가 필요함")
        self.measurement_only = measurement_only
        self.preparation_required = preparation_required
        self._preparation_action_busy = False
        self._preparations = {}
        self._preparation_bindings = {}
        self._preparation_ids = set()
        self._motion_uncertain = False
        self.observations = observation_cache or ObservationCache()
        self.on_precheck_result = on_precheck_result
        self.runtime_mode = runtime_mode
        self.real_adapter = real_adapter
        self.go_to_path_start_fn = go_to_path_start_fn
        self.return_home_fn = return_home_fn
        self.load_inputs = load_inputs
        self.precheck_fn = precheck_fn
        self.joint_check_fn = joint_check_fn
        self.validate_engraving_fn = validate_engraving_fn
        self.verify_tip_fn = verify_tip_fn
        self.engrave_fn = engrave_fn
        self.entry_plan_fn = entry_plan_fn
        self.entry_execute_fn = entry_execute_fn
        self.return_home_plan_fn = return_home_plan_fn
        self.return_home_execute_fn = return_home_execute_fn
        self.journal = journal
        self._lock = threading.Lock()
        # 접수 잠금과 분리: 측정 함수가 직접 획득하고, 조각은 execute가 획득한다.
        self.motion_lock = threading.Lock()
        self._active: Optional[_ActiveRun] = None
        self._completed = {}  # 프로세스 내 재전송 방지. REAL은 영속 저널도 필수다.
        self._run_ids = set()

    def prepare(self, preparation_id, context, adapter, evidence, settings, *,
                motion_check, measure, confirm_result, on_phase=None,
                _measurement_owned_stop=False):
        """경로 없는 내부 SIM 준비 입구. ROS 계약/실물 측정 연결 전의 함수 통합용.

        motion_check(adapter, context): 측정 접근/접촉/후퇴의 동작 전 검사.
        measure(adapter, context): 측정·계산·후퇴를 모두 수행하는 담당자 함수 래퍼.
        confirm_result(StepResult): 측정값 확보와 실제 후퇴 완료 근거 검사(모션 없음).
        세 콜백은 StepResult를 반환한다. 정상 결과를 임의 생성하는 기본값은 없다.
        """
        if not ((self.runtime_mode == "SIMULATION" and type(adapter) is MockRobotAdapter)
                or (self.runtime_mode == "REAL" and adapter is self.real_adapter and isinstance(adapter, DoosanRobotAdapter))):
            return StepResult("FAILED", "NOT_READY", "준비 상태 어댑터 모드/객체 불일치", "preparation")
        if (not isinstance(preparation_id, str) or not preparation_id
                or getattr(context, "run_id", None) != preparation_id
                or getattr(context, "source_mode", None) != self.runtime_mode
                or not callable(getattr(getattr(context, "cancel", None), "is_set", None))
                or not isinstance(evidence, PreconditionEvidence)
                or evidence.runtime_mode != self.runtime_mode
                or not isinstance(settings, Mapping)
                or any(not callable(fn) for fn in (motion_check, measure, confirm_result))):
            return StepResult("FAILED", "INVALID_INPUT", "준비 입력/콜백 오류", "preparation")
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "준비 시작 전 취소", "preparation")
        with self._lock:
            if self._active or self._motion_uncertain:
                return StepResult("FAILED", "BUSY", "측정/조각 실행 중 또는 정지 미확인", "preparation")
            if preparation_id in self._preparation_ids or preparation_id in self._run_ids:
                return StepResult("FAILED", "REQUEST_CONFLICT", "사용한 준비 ID", "preparation")
            self._preparations.clear()
            self._preparation_bindings.clear()
            self._preparation_ids.add(preparation_id)
            active = _ActiveRun(preparation_id, preparation_id, context.cancel)
            active.adapter, active.context = adapter, context
            active.measurement_owned_stop = _measurement_owned_stop
            context.cancel = active.cancel
            self._active = active
        try:
            result = run_preparation(
                context,
                status_check=lambda: check_preparation_status(
                    adapter, evidence, settings, cancel=active.cancel,
                    on_observation=self.observations.capture,
                    initialize_controller=(adapter.initialize_controller
                                           if self.runtime_mode == "REAL" else None)),
                motion_check=lambda: motion_check(adapter, context),
                measure=lambda: measure(adapter, context), confirm_result=confirm_result,
                on_phase=on_phase)
            result = self._finalize_stop(active, result)
        except Exception as exc:
            result = StepResult("UNKNOWN", "INTERNAL_ERROR", str(exc), "preparation")
        with self._lock:
            # 정지 접수와 준비 성공 기록 사이의 경쟁도 막는다.
            if active.cancel.is_set() and result.ok:
                result = StepResult("UNKNOWN", "STOP_UNCONFIRMED", "준비 완료 직전 취소", "preparation")
            if result.ok:
                result.observed_state["preparation_id"] = preparation_id
                self._preparations[preparation_id] = (copy.deepcopy(result), adapter)
            if result.outcome == "UNKNOWN":
                self._motion_uncertain = True
            self._active = None
        return result

    def prepare_workpiece_request(self, request, *, cancel, status_adapter,
                                  measurement_adapter, workcell, profiles, evidence,
                                  settings, on_feedback=None):
        """요청→실제 준비 함수→표시용 dict. 동기 SIM 전용, ROS 수신부 아님.

        workcell/profiles/settings와 evidence는 시험 또는 설정 생산자가 명시적으로
        공급한다. 미확인 근거를 생성하지 않는다. Feedback 실패는 기존 준비·측정
        함수가 처리하며 이 입구에서 후퇴/홈/중복 정지 명령을 추가하지 않는다.
        """
        ids = request if isinstance(request, Mapping) else {}
        try:
            context = preparation_context_from_request(
                request, cancel=cancel, motion_lock=self.motion_lock)
            if (not isinstance(evidence, PreconditionEvidence)
                    or evidence.runtime_mode != context.source_mode
                    or any(not isinstance(v, Mapping) for v in (workcell, profiles, settings))
                    or (on_feedback is not None and not callable(on_feedback))):
                raise ValueError("설정·검사 근거·진행 콜백 형식/모드 오류")
            workcell, profiles, settings = copy.deepcopy((workcell, profiles, settings))
            evidence = replace(evidence)
        except (ValueError, TypeError) as exc:
            return preparation_result_view(
                StepResult("FAILED", "INVALID_INPUT", str(exc), "preparation_request"),
                ids.get("preparation_id"), ids.get("measurement_id"))

        sequence = 0
        def emit(event):
            nonlocal sequence
            sequence += 1
            packet = copy.deepcopy(event)
            packet.update(preparation_id=context.preparation_id,
                          measurement_id=context.measurement_id, sequence=sequence)
            if on_feedback is not None:
                on_feedback(packet)

        def phase(name):
            emit(dict(stage=name, status="RUNNING", message=name,
                      point_index=None, total_points=None,
                      measured_at=context.utc_now(), origin="preparation"))

        def progress(event):
            emit({**event, "origin": "measurement", "measurement_sequence": event["sequence"]})

        result = self.prepare_workpiece(
            context, status_adapter, measurement_adapter, workcell, profiles, evidence,
            settings, on_phase=phase, on_progress=progress)
        return preparation_result_view(result, context.preparation_id, context.measurement_id)

    def prepare_workpiece(self, context, status_adapter, measurement_adapter, workcell,
                          profiles, evidence, settings, *, on_progress=None, on_phase=None, before_measure=None):
        """팀 측정 함수와 연결하는 SIM 입구. ROS Action 계약은 변경하지 않는다.

        context.motion_lock에는 이 coordinator의 motion_lock을 전달한다.
        상태 조회/이후 조각의 어댑터와 측정 전용 어댑터를 분리한다. 측정 함수가
        내부 preflight와 취소 후 실제 정지를 소유하므로 기존 stop worker를 중복 호출하지 않는다.
        이 메서드는 동기 함수이며 수신부 작업 스레드에서 호출한다.
        """
        from .measurement_robot_adapter import GuardedMeasurementAdapter
        expected = SimulatedWorkpieceAdapter if self.runtime_mode == "SIMULATION" else GuardedMeasurementAdapter
        if (not isinstance(context, MeasurementContext) or context.source_mode != self.runtime_mode
                or not isinstance(measurement_adapter, expected)
                or measurement_adapter.source_mode != self.runtime_mode):
            return StepResult("FAILED", "NOT_READY", "측정 어댑터·요청·공정 모드 불일치", "preparation")
        if (context.motion_lock is not self.motion_lock
                or not isinstance(context.measurement_id, str) or not context.measurement_id
                or not isinstance(workcell, Mapping) or not isinstance(profiles, Mapping)
                or (on_progress is not None and not callable(on_progress))):
            return StepResult("FAILED", "INVALID_INPUT", "측정 ID·공유 잠금·설정·콜백 확인 필요", "preparation")
        # 준비 ID와 측정 ID를 합치거나 MeasurementContext에 run_id를 임의 추가하지 않는다.
        preparation_context = ExecutionContext(
            run_id=context.preparation_id, source_mode=context.source_mode,
            cancel=context.cancel, motion_profiles={}, tool_profile={})

        def measurement_contract(_adapter, _context):
            # 실제 이동 검사는 measure_workpiece → preflight_measurement가 수행한다.
            # 이 결과를 IK 또는 충돌 검사의 통과 근거로 사용하지 않는다.
            if measurement_adapter.measurement_contract_version != 1:
                return StepResult("FAILED", "UNSUPPORTED_ADAPTER", "측정 어댑터 계약 불일치", "preparation")
            return StepResult("SUCCEEDED", message="측정 계약 확인; 이동 검사는 측정 함수 내부 수행",
                              observed_state={"motion_check_owner": "measure_workpiece"})

        def measure(_adapter, _context):
            if before_measure is not None:
                ready = before_measure(context, on_progress)
                if not isinstance(ready, StepResult):
                    return StepResult("UNKNOWN", "INTERNAL_ERROR", "홈/재검사 반환 형식 오류", "home_recheck")
                if not ready.ok:
                    return ready
                if context.cancel.is_set():
                    return StepResult("STOPPED", "NONE", "홈 확인 후 취소", "home_recheck", ready.observed_state)
            return measure_workpiece(measurement_adapter, workcell, profiles, context, on_progress)

        def confirm(result):
            observed = result.observed_state
            measurement = observed.get("measurement")
            if (not isinstance(measurement, Mapping)
                    or measurement.get("measurement_id") != context.measurement_id
                    or measurement.get("preparation_id") != context.preparation_id
                    or measurement.get("source_mode") != context.source_mode
                    or measurement.get("frame_id") != "c2_base"
                    or measurement.get("position_unit") != "m"):
                return StepResult("FAILED", "INVALID_INPUT", "측정 결과 ID·모드·단위·좌표계 불일치", "preparation")
            # CONTACT_REFERENCE도 SUCCEEDED일 수 있다. 경로 생성용 준비 완료와 구분한다.
            if (measurement.get("geometry_ready") is not True
                    or measurement.get("validity") not in (("SIMULATED",) if self.runtime_mode == "SIMULATION" else ("FORCE_CONTACT_ESTIMATE", "ESTIMATED"))
                    or observed.get("partial") is not False
                    or observed.get("stop_confirmed") is not True):
                return StepResult("FAILED", "NOT_READY", "경로 생성용 절대 형상/후퇴 완료 미확인", "preparation")
            values = [measurement.get(k) for k in ("radius_m", "top_z_m", "bottom_z_m", "height_m")]
            vectors = [(measurement.get(k), n) for k, n in (
                ("axis_xy_m", 2), ("work_z_range_m", 2), ("work_v_range_m", 2))]
            if any(not isinstance(v, (list, tuple)) or len(v) != n for v, n in vectors):
                return StepResult("FAILED", "INVALID_INPUT", "측정 기하 배열 형식 오류", "preparation")
            values += [x for v, _ in vectors for x in v]
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                    or measurement["radius_m"] <= 0 or measurement["height_m"] <= 0
                    or measurement["bottom_z_m"] >= measurement["top_z_m"]):
                return StepResult("FAILED", "INVALID_INPUT", "측정 기하값 오류", "preparation")
            return StepResult("SUCCEEDED", observed_state={"geometry_ready": True,
                              "measurement_id": context.measurement_id})

        return self.prepare(context.preparation_id, preparation_context, status_adapter,
                            evidence, settings, motion_check=measurement_contract, measure=measure,
                            confirm_result=confirm, on_phase=on_phase, _measurement_owned_stop=True)

    def bind_preparation_snapshot(self, preparation_id, snapshot_id, snapshot_sha256):
        """HMI 등록 결과를 연결할 내부 입구. 실제 전송 필드는 계약 확정 뒤 매핑한다.

        해당 준비 결과로 만든 스냅샷임을 등록 담당자가 보증해야 한다.
        한 준비 ID에 다른 스냅샷을 덮어쓰지 않는다. 디스크 영속 복원은 아직 미지원.
        """
        if (not isinstance(snapshot_id, str) or not snapshot_id
                or not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64
                or any(c not in "0123456789abcdef" for c in snapshot_sha256)):
            return StepResult("FAILED", "INVALID_INPUT", "스냅샷 ID/해시 형식 오류", "preparation")
        with self._lock:
            if preparation_id not in self._preparations:
                return StepResult("FAILED", "NOT_READY", "성공 완료된 준비 기록 없음", "preparation")
            identity = (snapshot_id, snapshot_sha256)
            old = self._preparation_bindings.get(preparation_id)
            if old is not None and old != identity:
                return StepResult("FAILED", "REQUEST_CONFLICT", "준비 결과에 다른 스냅샷 연결", "preparation")
            self._preparation_bindings[preparation_id] = identity
        return StepResult("SUCCEEDED", "NONE", "준비 스냅샷 참조 연결", "preparation")

    @property
    def active_run_id(self) -> str:
        with self._lock:
            return self._active.run_id if self._active else ""

    def execute(self, goal: Mapping, on_phase=None, on_progress=None, *, preparation_id=None) -> StepResult:
        if not isinstance(goal, Mapping) or goal.get("schema_version") != 2:
            return StepResult("FAILED", "UNSUPPORTED_SCHEMA_VERSION", "고정 드릴 v2 요청만 지원", "precheck")
        if self.measurement_only:
            return StepResult("FAILED", "NOT_READY", "측정 전용 노드: 조각 실행 금지", "precheck")
        if goal.get("source_mode") != self.runtime_mode:
            return StepResult("FAILED", "SOURCE_MODE_MISMATCH", "요청과 공정 노드 실행 모드 불일치", "precheck")
        request_id, run_id = goal.get("request_id"), goal.get("run_id")
        if not isinstance(request_id, str) or not request_id or not isinstance(run_id, str) or not run_id:
            return StepResult("FAILED", "INVALID_INPUT", "request_id/run_id 없음", "precheck")
        if self.preparation_required and not preparation_id and not self._preparation_bindings:
            return StepResult("FAILED", "NOT_READY", "준비 결과 연결 필요", "precheck")
        if preparation_id is not None and (not isinstance(preparation_id, str) or not preparation_id):
            return StepResult("FAILED", "INVALID_INPUT", "준비 ID 형식 오류", "precheck")
        identity = (run_id, goal["source_mode"], goal.get("path_id"), goal.get("path_version"),
                    goal.get("path_sha256"))
        if preparation_id is not None:
            identity += (preparation_id,)
        with self._lock:
            previous = self._completed.get(request_id)
            if previous:
                if previous[0] == identity:
                    return previous[1]  # 같은 요청은 모션을 다시 시작하지 않는다.
                return StepResult("FAILED", "REQUEST_CONFLICT", "같은 요청 ID에 다른 실행 입력", "precheck")
            if self._preparation_action_busy or self._active or self._motion_uncertain or run_id in self._run_ids or run_id in self._preparation_ids:
                return StepResult("FAILED", "BUSY", "실행 중이거나 사용한 run_id", "precheck")
            if self.journal is not None:
                try:
                    previous = self.journal.reserve(request_id, identity)
                except Exception as exc:
                    return StepResult("UNKNOWN", "STORAGE_ERROR", f"실행 기록 예약 실패: {exc}", "precheck")
                if previous is not None:
                    return previous
            active = _ActiveRun(request_id, run_id, threading.Event())
            self._active = active
            self._run_ids.add(run_id)

        result = StepResult("UNKNOWN", "INTERNAL_ERROR", "실행 결과 미확인", "precheck")
        motion_acquired = self.motion_lock.acquire(blocking=False)
        try:
            if motion_acquired:
                result = self._run_active(goal, active, on_phase, on_progress, preparation_id)
            else:
                result = StepResult("FAILED", "BUSY", "공유 모션 소유권 사용 중", "precheck")
        except InputsUnavailable as exc:
            result = StepResult("FAILED", exc.error_code, str(exc), "precheck")
        except Exception as exc:
            result = StepResult("UNKNOWN", "INTERNAL_ERROR", f"공정 실행 결과 미확인: {exc}", "precheck")
        finally:
            result = self._finalize_stop(active, result)
            if motion_acquired:
                self.motion_lock.release()
        if self.journal is not None:
            try:
                self.journal.finish(request_id, result)
            except Exception as exc:
                result = StepResult("UNKNOWN", "STORAGE_ERROR", f"실행 결과 기록 실패: {exc}",
                                    result.completed_step, dict(result.observed_state))
        with self._lock:
            if self._active is active:
                self._active = None
            self._completed[request_id] = (identity, result)
            if result.outcome == "UNKNOWN" and (preparation_id is not None or active.stop_requested):
                self._motion_uncertain = True
        return result

    def _run_active(self, goal, active, on_phase, on_progress, preparation_id=None) -> StepResult:
        loaded = self.load_inputs(goal)
        if not isinstance(loaded, ExecutionInputs):
            return StepResult("FAILED", "NOT_READY", "실행 입력 로더 결과 오류", "precheck")
        if self.runtime_mode == "REAL":
            if loaded.adapter is not None and loaded.adapter is not self.real_adapter:
                return StepResult("FAILED", "NOT_READY", "로더와 노드의 실물 어댑터 불일치", "precheck")
            loaded = replace(loaded, adapter=self.real_adapter)
        if loaded.adapter is None or loaded.context is None or not isinstance(loaded.evidence, PreconditionEvidence):
            return StepResult("FAILED", "NOT_READY", "어댑터·실행 맥락·검사 근거 없음", "precheck")
        if self.runtime_mode == "SIMULATION" and type(loaded.adapter) is not MockRobotAdapter:
            return StepResult("FAILED", "NOT_READY", "SIMULATION은 모의 어댑터에서만 실행 가능", "precheck")
        if (getattr(loaded.context, "run_id", None) != active.run_id
                or getattr(loaded.context, "source_mode", None) != goal["source_mode"]):
            return StepResult("FAILED", "PROFILE_MISMATCH", "실행 맥락 ID/모드 불일치", "precheck")
        config = loaded.path.get("config", loaded.path)
        if not isinstance(config, Mapping):
            return StepResult("FAILED", "INVALID_INPUT", "경로 config 형식 오류", "precheck")
        if self.preparation_required and preparation_id is None:
            identity = (config.get("profile_snapshot_id"), config.get("profile_sha256"))
            with self._lock:
                matches = [pid for pid, bound in self._preparation_bindings.items() if bound == identity]
            if len(matches) != 1:
                return StepResult("FAILED", "NOT_READY", "경로에 등록된 준비 스냅샷 없음", "precheck")
            preparation_id = matches[0]
        prepared = preparation_id is not None
        if prepared:
            with self._lock:
                record = self._preparations.get(preparation_id)
                binding = self._preparation_bindings.get(preparation_id)
            if (record is None or record[1] is not loaded.adapter
                    or binding != (config.get("profile_snapshot_id"), config.get("profile_sha256"))):
                return StepResult("FAILED", "NOT_READY", "이번 경로에 연결된 준비 성공 기록 없음", "precheck")
        if (not loaded.calibration_snapshot_id
                or loaded.calibration_snapshot_id != config.get("profile_snapshot_id")):
            return StepResult("FAILED", "PROFILE_MISMATCH", "저장된 드릴 오프셋과 경로 스냅샷 불일치", "precheck")
        offset = loaded.tool_offset_m
        if offset is None and isinstance(loaded.calibration, TipCalibration):
            offset = loaded.calibration.offset_tool_m
        if (not isinstance(offset, (list, tuple)) or len(offset) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in offset)):
            return StepResult("FAILED", "NOT_READY", "승인된 드릴 오프셋 없음", "precheck")
        if not prepared:
            if (not isinstance(loaded.calibration, TipCalibration)
                    or loaded.calibration.tool_id != "engraving_drill"):
                return StepResult("FAILED", "PROFILE_MISMATCH", "저장된 드릴 보정과 경로 스냅샷 불일치", "precheck")
            if (not isinstance(loaded.tip_tolerance_m, (int, float))
                    or not math.isfinite(loaded.tip_tolerance_m) or loaded.tip_tolerance_m <= 0):
                return StepResult("FAILED", "NOT_READY", "승인된 드릴 끝 확인 허용차 없음", "precheck")
        context = loaded.context
        approved_runtime_settings = dict(
            workcell=copy.deepcopy(loaded.workcell),
            calibration_profiles=copy.deepcopy(loaded.calibration_profiles),
            joint_limits_deg=copy.deepcopy(loaded.joint_limits_deg),
            j6_margin_deg=loaded.j6_margin_deg,
            tool_offset_m=copy.deepcopy(offset),
            motion_profiles=copy.deepcopy(context.motion_profiles),
            tool_profile=copy.deepcopy(context.tool_profile),
            stop_profile=copy.deepcopy(context.stop_profile),
        )
        context.cancel = active.cancel
        with self._lock:
            active.adapter, active.context = loaded.adapter, context

        entry_policy = loaded.workcell.get("entry_planning") if isinstance(loaded.workcell, Mapping) else None
        entry_enabled = prepared and (self.runtime_mode == "REAL"
                                      or (isinstance(entry_policy, Mapping)
                                          and entry_policy.get("enabled") is True))
        checked_return_home = {}

        def revalidate_prepared_readiness():
            """오래 걸린 IK 뒤 동일 입력과 최신 REAL 상태를 다시 확인한다.

            읽기 전용 재조회이며 모션/TCP/모드 설정을 변경하지 않는다. 이 검사가
            실패하면 ENTRY로 넘어가지 않는다.
            """
            if not prepared or self.runtime_mode != "REAL":
                return StepResult("SUCCEEDED", "NONE", "추가 REAL 재검사 불필요",
                                  "precheck_revalidation")
            if context.cancel.is_set():
                return StepResult("STOPPED", "NONE", "실행 직전 재검사 취소",
                                  "precheck_revalidation")
            try:
                refreshed = self.load_inputs(goal)
            except InputsUnavailable as exc:
                return StepResult("FAILED", exc.error_code, str(exc),
                                  "precheck_revalidation")
            except Exception as exc:
                return StepResult("UNKNOWN", "COMMUNICATION_LOST",
                                  f"실행 직전 입력·상태 재조회 실패: {exc}",
                                  "precheck_revalidation")
            if not isinstance(refreshed, ExecutionInputs):
                return StepResult("FAILED", "NOT_READY", "실행 직전 입력 로더 결과 오류",
                                  "precheck_revalidation")
            if refreshed.adapter not in (None, self.real_adapter):
                return StepResult("FAILED", "NOT_READY", "실행 직전 실물 어댑터 불일치",
                                  "precheck_revalidation")
            refreshed_context = refreshed.context
            refreshed_offset = refreshed.tool_offset_m
            if refreshed_offset is None and isinstance(refreshed.calibration, TipCalibration):
                refreshed_offset = refreshed.calibration.offset_tool_m
            immutable_match = (
                refreshed.path_bytes == loaded.path_bytes
                and refreshed.snapshot_bytes == loaded.snapshot_bytes
                and refreshed.calibration_snapshot_id == loaded.calibration_snapshot_id
                and refreshed.workcell == approved_runtime_settings["workcell"]
                and refreshed.calibration_profiles == approved_runtime_settings["calibration_profiles"]
                and refreshed.joint_limits_deg == approved_runtime_settings["joint_limits_deg"]
                and refreshed.j6_margin_deg == approved_runtime_settings["j6_margin_deg"]
                and refreshed_offset == approved_runtime_settings["tool_offset_m"]
                and getattr(refreshed_context, "run_id", None) == active.run_id
                and getattr(refreshed_context, "source_mode", None) == goal["source_mode"]
                and getattr(refreshed_context, "motion_profiles", None)
                    == approved_runtime_settings["motion_profiles"]
                and getattr(refreshed_context, "tool_profile", None)
                    == approved_runtime_settings["tool_profile"]
                and getattr(refreshed_context, "stop_profile", None)
                    == approved_runtime_settings["stop_profile"]
            )
            if not immutable_match:
                return StepResult("FAILED", "PROFILE_MISMATCH",
                                  "관절 검사 중 경로·스냅샷·실행 설정 변경",
                                  "precheck_revalidation")
            if not isinstance(refreshed.evidence, PreconditionEvidence):
                return StepResult("FAILED", "NOT_READY", "실행 직전 상태 근거 없음",
                                  "precheck_revalidation")
            expected_binding = (config.get("profile_snapshot_id"),
                                config.get("profile_sha256"))
            with self._lock:
                current_record = self._preparations.get(preparation_id)
                current_binding = self._preparation_bindings.get(preparation_id)
            if (current_record is None or current_record[1] is not loaded.adapter
                    or current_binding != expected_binding):
                return StepResult("FAILED", "NOT_READY", "실행 직전 동일 준비 BIND 미확인",
                                  "precheck_revalidation")
            try:
                current_state = loaded.adapter.observe()
            except Exception as exc:
                self.observations.capture(None, None, None)
                return StepResult("UNKNOWN", "COMMUNICATION_LOST",
                                  f"실행 직전 로봇 상태 조회 실패: {exc}",
                                  "precheck_revalidation")
            self.observations.capture(
                current_state, getattr(loaded.adapter, "tool_offset_m", None),
                refreshed.evidence.max_robot_state_age_s)
            checked_status = check_robot_status(
                replace(refreshed.evidence, robot_state=current_state))
            if not checked_status.ok:
                return checked_status
            return StepResult("SUCCEEDED", "NONE",
                              "동일 준비 BIND와 최신 로봇 상태 재확인",
                              "precheck_revalidation",
                              {"preparation_id": preparation_id,
                               "profile_snapshot_id": expected_binding[0]})

        def precheck():
            reset_ik_metrics = getattr(loaded.adapter, "reset_ik_metrics", None)
            if callable(reset_ik_metrics):
                reset_ik_metrics()
            try:
                # 준비 완료 실행은 저장된 고정 장착 오프셋을 먼저 연결해야 observe()도
                # 경로와 같은 도구 끝 기준이 된다. 로봇 모션이나 제어기 설정 변경은 아니다.
                if prepared:
                    loaded.adapter.set_tool_offset(list(offset))
                state = loaded.adapter.observe()
            except Exception:
                self.observations.capture(None, None, None)
                raise
            self.observations.capture(state, getattr(loaded.adapter, "tool_offset_m", None),
                                      loaded.evidence.max_robot_state_age_s)
            evidence = replace(loaded.evidence, robot_state=state)

            def joints():
                stage_started = time.monotonic()
                stage_metrics = {}
                limits = loaded.joint_limits_deg
                margin = loaded.j6_margin_deg
                current = getattr(state, "joints_rad", None)
                if (not isinstance(limits, (list, tuple)) or len(limits) != 6
                        or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                               or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in pair)
                               or pair[0] >= pair[1] for pair in limits)
                        or type(margin) not in (int, float) or not math.isfinite(margin) or margin < 0
                        or 2 * margin >= limits[5][1] - limits[5][0]):
                    return StepResult("FAILED", "NOT_READY", "승인된 관절 한계·J6 여유 설정 없음", "joint_check")
                if (not isinstance(current, (list, tuple)) or len(current) != 6
                        or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in current)
                        or not isinstance(offset, (list, tuple)) or len(offset) != 3
                        or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in offset)):
                    return StepResult("FAILED", "NOT_READY", "현재 관절 또는 승인된 드릴 오프셋 없음", "joint_check")
                context.joint_limits_deg = [tuple(pair) for pair in limits]
                context.j6_margin_deg = float(margin)
                context.path_binding = dict(goal)
                context.checked_tool_offset_m = list(offset)
                context.checked_entry_plan = None
                context.checked_entry_plan_sha256 = None
                if entry_enabled:
                    workspace = check_path_workspace(loaded.path, loaded.workcell.get("engraving_workspace"))
                    if not workspace.ok:
                        return workspace
                    entry_started = time.monotonic()
                    entry = self.entry_plan_fn(
                        dict(loaded.path), dict(loaded.workcell), loaded.adapter, state,
                        list(offset), context.joint_limits_deg, context.j6_margin_deg,
                        context.motion_profiles, cancel=context.cancel,
                        joint_check_fn=self.joint_check_fn)
                    stage_metrics["entry"] = {
                        "stage_elapsed_s": max(0.0, time.monotonic() - entry_started),
                    }
                    if isinstance(entry, StepResult):
                        entry_ik_metrics = dict(entry.observed_state.get("ik_metrics") or {})
                        if "elapsed_s" in entry_ik_metrics:
                            entry_ik_metrics["ik_elapsed_s"] = entry_ik_metrics.pop("elapsed_s")
                        stage_metrics["entry"].update(entry_ik_metrics)
                    if not isinstance(entry, StepResult):
                        return StepResult("UNKNOWN", "INVALID_RESULT",
                                          "entry 계획 결과 형식 오류", "entry_planning")
                    if not entry.ok:
                        return entry
                    entry_plan = entry.observed_state.get("entry_plan")
                    entry_sha = entry.observed_state.get("entry_plan_sha256")
                    if not isinstance(entry_plan, Mapping) or not isinstance(entry_sha, str):
                        return StepResult("UNKNOWN", "INVALID_RESULT",
                                          "entry 계획·해시 누락", "entry_planning")
                    context.checked_entry_plan = copy.deepcopy(dict(entry_plan))
                    context.checked_entry_plan_sha256 = entry_sha
                plan = build_execution_plan(dict(loaded.path), context)
                if isinstance(plan, StepResult):
                    return plan
                if entry_enabled:
                    workspace = check_path_workspace(plan, loaded.workcell.get("engraving_workspace"))
                    if not workspace.ok:
                        return workspace
                if context.cancel.is_set():
                    return StepResult("STOPPED", "NONE", "검사 취소", "joint_check")
                kwargs = dict(limits_deg=context.joint_limits_deg, j6_margin_deg=context.j6_margin_deg)
                if self.joint_check_fn is check_path_joints:
                    kwargs["cancel"] = context.cancel
                signature = execution_signature(dict(loaded.path), context)
                main_reference = list(current)
                if entry_enabled:
                    final_entry = context.checked_entry_plan.get("final_joints_deg")
                    if (isinstance(final_entry, (list, tuple)) and len(final_entry) == 6
                            and all(isinstance(v, (int, float)) and math.isfinite(v)
                                    for v in final_entry)):
                        main_reference = [math.radians(v) for v in final_entry]
                main_started = time.monotonic()
                main_evaluation = None
                if self.joint_check_fn is check_path_joints:
                    main_evaluation = evaluate_path_joints(
                        plan, loaded.adapter, list(offset), main_reference,
                        limits_deg=context.joint_limits_deg,
                        j6_margin_deg=context.j6_margin_deg, cancel=context.cancel)
                    checked = main_evaluation.result
                else:
                    checked = self.joint_check_fn(
                        plan, loaded.adapter, list(offset), main_reference, **kwargs)
                stage_metrics["main_path"] = {
                    "stage_elapsed_s": max(0.0, time.monotonic() - main_started),
                }
                if main_evaluation is not None:
                    stage_metrics["main_path"].update({
                        "inverse_kinematics_calls": main_evaluation.inverse_kinematics_calls,
                        "ik_elapsed_s": main_evaluation.elapsed_s,
                    })
                if checked.ok:
                    if signature != execution_signature(dict(loaded.path), context):
                        return StepResult("FAILED", "PROFILE_MISMATCH", "IK 중 경로/설정 변경", "execution_plan")
                    context.checked_plan_signature = signature
                    checked.observed_state["plan_signature"] = signature
                    if context.checked_entry_plan_sha256 is not None:
                        checked.observed_state["entry_plan_sha256"] = context.checked_entry_plan_sha256
                    if entry_enabled:
                        home_kwargs = dict(
                            entry_plan=context.checked_entry_plan,
                            plan_signature=signature, cancel=context.cancel,
                            joint_check_fn=self.joint_check_fn)
                        if (self.return_home_plan_fn is plan_return_home_path
                                and main_evaluation is not None):
                            home_kwargs["predicted_end_joints_deg"] = (
                                main_evaluation.final_joints_deg)
                        home_started = time.monotonic()
                        home = self.return_home_plan_fn(
                            plan, dict(loaded.workcell), loaded.adapter, state,
                            list(offset), context.joint_limits_deg, context.j6_margin_deg,
                            context.motion_profiles, **home_kwargs)
                        stage_metrics["return_home"] = {
                            "stage_elapsed_s": max(0.0, time.monotonic() - home_started),
                        }
                        if isinstance(home, StepResult):
                            home_ik_metrics = dict(home.observed_state.get("ik_metrics") or {})
                            if "elapsed_s" in home_ik_metrics:
                                home_ik_metrics["ik_elapsed_s"] = home_ik_metrics.pop("elapsed_s")
                            stage_metrics["return_home"].update(home_ik_metrics)
                        if not isinstance(home, StepResult):
                            return StepResult("UNKNOWN", "INVALID_RESULT",
                                              "HOME 복귀 계획 결과 형식 오류",
                                              "return_home_planning")
                        if not home.ok:
                            return home
                        if signature != execution_signature(dict(loaded.path), context):
                            return StepResult("FAILED", "PROFILE_MISMATCH",
                                              "HOME 복귀 검사 중 경로/설정 변경",
                                              "return_home_planning")
                        return_plan = home.observed_state.get("return_home_plan")
                        return_sha = home.observed_state.get("return_home_plan_sha256")
                        if not isinstance(return_plan, Mapping) or not isinstance(return_sha, str):
                            return StepResult("UNKNOWN", "INVALID_RESULT",
                                              "HOME 복귀 계획·해시 누락",
                                              "return_home_planning")
                        checked_return_home["plan"] = copy.deepcopy(dict(return_plan))
                        checked_return_home["sha256"] = return_sha
                        checked.observed_state["return_home_plan_sha256"] = return_sha
                    stage_metrics["total"] = {
                        "stage_elapsed_s": max(0.0, time.monotonic() - stage_started),
                        "inverse_kinematics_calls": sum(
                            int(value.get("inverse_kinematics_calls", 0))
                            for key, value in stage_metrics.items() if key != "total"),
                    }
                    checked.observed_state["precheck_ik_metrics"] = stage_metrics
                return checked

            checker = check_prepared_path if prepared else self.precheck_fn
            checked = checker(goal, loaded.path, loaded.path_bytes, loaded.snapshot,
                                       loaded.snapshot_bytes, evidence, joint_check=joints)
            metrics_snapshot = getattr(loaded.adapter, "ik_metrics_snapshot", None)
            if callable(metrics_snapshot):
                adapter_metrics = metrics_snapshot()
                if isinstance(adapter_metrics, Mapping):
                    checked.observed_state = dict(checked.observed_state)
                    checked.observed_state["adapter_ik_metrics"] = dict(adapter_metrics)
            if not checked.ok:
                # 실패한 관절 검사를 재시도할 때도 일시적 cache 만료만으로 이미
                # 성공한 측정/BIND가 삭제되지 않도록 최신 관측을 다시 채운다.
                revalidated = revalidate_prepared_readiness()
                return revalidated if not revalidated.ok else checked
            if self.runtime_mode == "REAL":
                # 현장 TP에서 선택한 TCP/하중을 읽기만 한다. 자동 재선택/모드 전환 없음.
                selected = check_selected_tool_profiles(loaded.adapter, config)
                if not selected.ok:
                    return selected
            # v2 조각 경로 자체도 1점 확인 모션 전에 검사한다.
            path_error = self.validate_engraving_fn(dict(loaded.path), context)
            if path_error:
                return path_error
            # 성공 경로에서는 모든 긴/정적 검사가 끝난 뒤, ENTRY에 가장 가까운
            # 시점에 동일 BIND·제어권·정지·STANDBY를 다시 확인한다.
            revalidated = revalidate_prepared_readiness()
            if not revalidated.ok:
                return revalidated
            return checked

        def tool_check():
            if self.runtime_mode == "REAL":
                # 생성 직후 어댑터의 offset은 None이다. 저장 보정을 먼저 연결해야
                # verify의 복원과 이후 경로 실행이 모두 도구 끝 기준이 된다.
                loaded.adapter.set_tool_offset(list(offset))
            return self.verify_tip_fn(loaded.adapter, dict(loaded.workcell),
                                      dict(loaded.calibration_profiles), loaded.calibration,
                                      context, tol_m=float(loaded.tip_tolerance_m))

        def engrave(progress):
            return self.engrave_fn(dict(loaded.path), context, progress, loaded.adapter)

        def go_to_start():
            return self.go_to_path_start_fn(dict(loaded.path), loaded.adapter, context)

        def return_home():
            return self.return_home_fn(loaded.adapter, context)

        def reported_precheck():
            result = precheck()
            if self.on_precheck_result is not None:
                self.on_precheck_result(goal, config, result)
            return result

        if prepared:
            # 저장된 장착 기준을 적용할 뿐 재측정/자동 홈 동작을 추가하지 않는다.
            def prepared_engrave(progress):
                return engrave(progress)
            def prepared_entry():
                if context.checked_entry_plan is None:
                    return StepResult("FAILED", "NOT_READY", "검사된 entry 계획 없음", "entry")
                if context.checked_plan_signature != execution_signature(dict(loaded.path), context):
                    return StepResult("FAILED", "PROFILE_MISMATCH",
                                      "entry 실행 전 경로/설정 변경", "entry")
                expected = (config.get("profile_snapshot_id"), config.get("profile_sha256"))
                with self._lock:
                    record = self._preparations.get(preparation_id)
                    current = self._preparation_bindings.get(preparation_id)
                if (record is None or record[1] is not loaded.adapter or current != expected):
                    return StepResult("FAILED", "NOT_READY",
                                      "entry 실행 직전 동일 준비 BIND 미확인", "entry")
                return self.entry_execute_fn(context.checked_entry_plan, loaded.adapter, context)
            def prepared_return_home():
                plan = checked_return_home.get("plan")
                if not isinstance(plan, Mapping):
                    return StepResult("FAILED", "NOT_READY",
                                      "검사된 HOME 복귀 계획 없음", "return_home")
                if context.checked_plan_signature != execution_signature(dict(loaded.path), context):
                    return StepResult("FAILED", "PROFILE_MISMATCH",
                                      "HOME 복귀 실행 전 경로/설정 변경", "return_home")
                return self.return_home_execute_fn(plan, loaded.adapter, context)
            result = run_prepared_process(context, precheck=reported_precheck,
                                          enter=prepared_entry if entry_enabled else None,
                                          engrave=prepared_engrave, on_phase=on_phase,
                                          on_progress=on_progress,
                                          return_home=prepared_return_home if entry_enabled else None)
            result.observed_state["preparation_id"] = preparation_id
            return result

        result = run_process(context, precheck=reported_precheck, tool_check=tool_check,
                             engrave=engrave, on_phase=on_phase, on_progress=on_progress,
                             go_to_start=go_to_start if self.go_to_path_start_fn else None,
                             return_home=return_home if self.return_home_fn else None)
        return result

    def _finalize_stop(self, active: _ActiveRun, result: StepResult) -> StepResult:
        if not active.stop_requested or active.measurement_owned_stop:
            # 측정 함수의 STOPPED/UNKNOWN 및 stop_confirmed 원본을 그대로 보존한다.
            return result
        profile = getattr(active.context, "stop_profile", {}) or {}
        timeout = float(profile.get("confirmation_timeout_s", 2.0))
        if self.runtime_mode == "REAL" and not active.stop_done.is_set():
            # 최신 REAL 어댑터는 이동·probe 내부에서 cancel을 관측하고 정지까지
            # 확인한 뒤 반환한다. 그 근거를 우선 소비하여 정지 명령을 중복하지 않는다.
            confirmed = result.observed_state.get("stop_confirmed")
            if type(confirmed) is bool:
                active.stop_result = StepResult(
                    "SUCCEEDED" if confirmed else "UNKNOWN",
                    "NONE" if confirmed else "STOP_UNCONFIRMED",
                    "어댑터 반환 정지 확인" if confirmed else "어댑터 반환 정지 미확인",
                    "stop", {"stop_confirmed": confirmed})
                active.stop_done.set()
            else:
                # 이동이 아닌 콜백이 cancel 뒤 늦게 반환한 경우에만 한 번 확인한다.
                self._stop_worker(active, active.adapter, profile, timeout)
        if not active.stop_done.wait(timeout=max(0.0, timeout) + 0.5):
            return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "정지 확인 제한 시간 초과",
                              result.completed_step, dict(result.observed_state, stop_confirmed=False))
        if active.stop_result is None or not active.stop_result.ok:
            return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "실제 정지 미확인",
                              result.completed_step, dict(result.observed_state, stop_confirmed=False))
        observed = dict(result.observed_state, stop_confirmed=True)
        # 정지 요청 뒤 도착한 성공/UNKNOWN 응답은 정상 실행 완료나 미확인 정지로
        # 남기지 않는다. 실제 정지가 확인된 경우에만 STOPPED로 확정한다.
        if result.outcome in ("SUCCEEDED", "STOPPED", "UNKNOWN"):
            return StepResult("STOPPED", "NONE", "정지 확인 완료", result.completed_step, observed)
        return StepResult(result.outcome, result.error_code, result.message, result.completed_step, observed)

    def _stop_worker(self, active: _ActiveRun, adapter, profile: Mapping, deadline: float):
        try:
            stopped = adapter.stop(dict(profile), deadline)
            if not isinstance(stopped, StepResult):
                stopped = StepResult("UNKNOWN", "STOP_UNCONFIRMED", "정지 결과 형식 오류", "stop")
        except Exception as exc:
            stopped = StepResult("UNKNOWN", "STOP_UNCONFIRMED", f"정지 호출 결과 미확인: {exc}", "stop")
        with self._lock:
            active.stop_result = stopped
            active.stop_done.set()

    def stop(self, run_id: str) -> StopDecision:
        with self._lock:
            active = self._active
            if active is None or active.run_id != run_id:
                return StopDecision(False, "UNKNOWN", "NOT_READY", "해당 활성 실행 없음")
            if active.stop_requested:
                return StopDecision(True, "ACCEPTED", "NONE", "정지 요청 처리 중")
            active.stop_requested = True
            active.cancel.set()
            adapter, context = active.adapter, active.context
            if active.measurement_owned_stop:
                return StopDecision(True, "ACCEPTED", "NONE", "측정 취소 전달; 정지는 측정 함수 결과로 확인")
        if adapter is None or context is None:
            with self._lock:
                active.stop_result = StepResult("SUCCEEDED", "NONE", "모션 전 취소", "stop")
                active.stop_done.set()
            return StopDecision(True, "REQUESTED", "NONE", "모션 시작 전 취소 요청")
        profile = getattr(context, "stop_profile", None)
        if not isinstance(profile, Mapping):
            with self._lock:
                active.stop_result = StepResult("UNKNOWN", "STOP_UNCONFIRMED", "정지 프로파일 없음", "stop")
                active.stop_done.set()
            return StopDecision(True, "UNKNOWN", "STOP_UNCONFIRMED", "정지 프로파일 없음")
        try:
            deadline = float(profile.get("confirmation_timeout_s"))
            if not math.isfinite(deadline) or deadline <= 0:
                raise ValueError("정지 확인 제한 시간 오류")
        except Exception as exc:
            with self._lock:
                active.stop_result = StepResult("UNKNOWN", "STOP_UNCONFIRMED", str(exc), "stop")
                active.stop_done.set()
            return StopDecision(True, "UNKNOWN", "STOP_UNCONFIRMED", str(exc))
        if self.runtime_mode == "REAL":
            # REAL 이동·probe가 같은 cancel을 관측하고 함수 반환 전에 정지 확인한다.
            return StopDecision(True, "ACCEPTED", "NONE", "취소 전달; 어댑터 정지 확인 대기")
        threading.Thread(target=self._stop_worker, args=(active, adapter, profile, deadline),
                         name="c2-stop", daemon=True).start()
        return StopDecision(True, "ACCEPTED", "NONE", "정지 요청 접수; 실제 정지는 별도 확인")


def _time_from_ns(ns):
    from builtin_interfaces.msg import Time
    return Time(sec=int(ns) // 1_000_000_000, nanosec=int(ns) % 1_000_000_000)


def _utc_time():
    """ROS /clock과 별개인 UTC Unix epoch Time."""
    from builtin_interfaces.msg import Time
    ns = time.time_ns()
    return Time(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)


def create_ros_node(load_inputs: Callable[[Mapping], ExecutionInputs] = _missing_loader,
                    *, journal: Optional[RunJournal] = None,
                    runtime_mode: str = "SIMULATION",
                    real_adapter: Optional[DoosanRobotAdapter] = None,
                    real_adapter_factory=None,
                    go_to_path_start_fn=None, return_home_fn=None,
                    preparation_runner_factory=None, preparation_resolver=None,
                    preparation_journal_path=None, enable_preparation=True, measurement_only=False,
                    real_preparation_options=None, real_preparation_options_factory=None,
                    real_execution_loader_factory=None, preparation_required=False):
    """Jazzy ROS 노드를 만든다. c2_interfaces 빌드·source 뒤에 호출한다."""
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from c2_interfaces.action import ExecuteProcess, PrepareWorkpiece
    from rosidl_runtime_py.set_message import set_message_fields
    from .preparation_action import PreparationActionHandler, AssetResolver, GOAL_FIELDS
    from c2_interfaces.msg import ProcessEvent, ProcessState
    from c2_interfaces.srv import StopProcess

    class ProcessControllerNode(Node):
        def __init__(self):
            super().__init__("process_controller_node")
            if real_adapter is not None and real_adapter_factory is not None:
                raise ValueError("real_adapter와 real_adapter_factory는 동시에 지정할 수 없음")
            if real_adapter_factory is not None and runtime_mode != "REAL":
                raise ValueError("real_adapter_factory는 REAL 노드에서만 사용할 수 있음")
            adapter = real_adapter
            if real_adapter_factory is not None:
                if not callable(real_adapter_factory):
                    raise ValueError("real_adapter_factory는 호출 가능해야 함")
                adapter = real_adapter_factory(self)
            current_loader = load_inputs
            if real_execution_loader_factory is not None:
                if runtime_mode != "REAL" or measurement_only:
                    raise ValueError("REAL 실행 로더 factory는 조각 가능한 REAL 노드에서만 사용")
                if load_inputs is not _missing_loader:
                    raise ValueError("load_inputs와 REAL 실행 로더 factory는 동시에 지정할 수 없음")
                if not callable(real_execution_loader_factory):
                    raise ValueError("REAL 실행 로더 factory는 호출 가능해야 함")
                current_loader = real_execution_loader_factory(self, adapter)
                if not callable(current_loader):
                    raise ValueError("REAL 실행 로더 factory 결과는 호출 가능해야 함")
            self.observations = ObservationCache()
            self._preparation_action_active = False
            self._precheck_binding_warning_active = False
            self.alarms = ProcessAlarms()
            self.profile_values = {}
            self.coordinator = ProcessCoordinator(
                current_loader, journal=journal, runtime_mode=runtime_mode,
                real_adapter=adapter, go_to_path_start_fn=go_to_path_start_fn,
                return_home_fn=return_home_fn, observation_cache=self.observations,
                on_precheck_result=self.report_precheck, measurement_only=measurement_only,
                preparation_required=preparation_required)
            self.preparation = None
            if enable_preparation:
                backend = self.declare_parameter("preparation_backend_url", "").value
                ledger = self.declare_parameter("preparation_journal_path", "").value
                if real_preparation_options is not None and real_preparation_options_factory is not None:
                    raise ValueError("REAL 준비 options와 options factory는 동시에 지정할 수 없음")
                current_real_options = real_preparation_options
                if real_preparation_options_factory is not None:
                    if not callable(real_preparation_options_factory):
                        raise ValueError("real_preparation_options_factory는 호출 가능해야 함")
                    current_real_options = real_preparation_options_factory(self)
                if current_real_options is not None:
                    if preparation_runner_factory is not None or runtime_mode != "REAL":
                        raise ValueError("실물 준비 options는 REAL 노드에서만 사용")
                    from .preparation_action import make_real_measurement_runner
                    runner = make_real_measurement_runner(self.coordinator,self,**current_real_options)
                else:
                    runner = preparation_runner_factory(self.coordinator) if preparation_runner_factory else None
                self.preparation = PreparationActionHandler(self.coordinator,
                    preparation_resolver or AssetResolver(backend or None),
                    preparation_journal_path or ledger or None, runner)
            self.group = ReentrantCallbackGroup()
            self.epoch = str(uuid4())
            self.seq = self.event_seq = 0
            self.lock = threading.Lock()
            self.status = "IDLE"
            self.phase = ""
            self.stop_state = "NONE"
            self.error_code = "NONE"
            self.message = "공정 대기"
            self.progress = 0.0
            self.segment_id = ""
            self.started_at = 0.0
            self.goal_values = {}
            state_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.VOLATILE)
            event_qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE,
                                   durability=DurabilityPolicy.VOLATILE)
            self.state_pub = self.create_publisher(ProcessState, "/c2/process_state", state_qos)
            self.event_pub = self.create_publisher(ProcessEvent, "/c2/process_events", event_qos)
            self.action = ActionServer(self, ExecuteProcess, "/c2/execute_process",
                                       execute_callback=self.execute_goal, goal_callback=self.accept_goal,
                                       cancel_callback=self.cancel_goal, callback_group=self.group)
            self.prepare_action = ActionServer(self, PrepareWorkpiece, "/c2/prepare_workpiece",
                execute_callback=self.execute_preparation, goal_callback=lambda _: GoalResponse.ACCEPT,
                cancel_callback=self.cancel_preparation, callback_group=self.group, result_timeout=600,
                feedback_pub_qos_profile=QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE,
                                                  durability=DurabilityPolicy.VOLATILE)) if self.preparation else None
            self.stop_service = self.create_service(StopProcess, "/c2/stop_process",
                                                     self.stop_request, callback_group=self.group)
            self.timer = self.create_timer(0.2, self.publish_state, callback_group=self.group)

        def cancel_preparation(self, handle):
            goal = {k:getattr(handle.request,k) for k in GOAL_FIELDS}
            accepted = self.preparation.cancel(goal)
            if accepted:
                with self.lock:
                    self.status = "STOPPING"
                    self.stop_state = "REQUESTED"
                    self.message = "준비 취소 요청 접수; 실제 정지 확인 대기"
            return CancelResponse.ACCEPT if accepted else CancelResponse.REJECT

        def execute_preparation(self, handle):
            goal = {k:getattr(handle.request,k) for k in GOAL_FIELDS}
            with self.lock:
                self.goal_values = {}
                self.status = "RUNNING"
                # ProcessState.phase는 기존 실행 공정 단계만 사용한다. 준비의 세부
                # stage/progress는 PrepareWorkpiece Feedback으로만 전달한다.
                self.phase = "PRECHECK"
                self.stop_state = "NONE"
                self.error_code = "NONE"
                self.message = "준비 요청 접수"
                self.progress = 0.0
                self.segment_id = ""
                self.started_at = time.monotonic()
                self._preparation_action_active = True
            self.emit_event("COMMAND", message="준비 요청 접수")
            def publish(value):
                with self.lock:
                    stage = value.get("stage", "UNKNOWN")
                    progress = float(value.get("progress", 0.0))
                    detail = value.get("message", "")
                    self.message = f"{stage} ({progress:.0%})" + (f" {detail}" if detail else "")
                packet = PrepareWorkpiece.Feedback()
                set_message_fields(packet,value)
                handle.publish_feedback(packet)
            try:
                data = self.preparation.execute(goal,publish)
                with self.lock:
                    self.status = data["outcome"]
                    self.error_code = data["error_code"]
                    self.message = data["message"]
                    self.progress = 1.0 if data["outcome"] == "SUCCEEDED" else self.progress
                    if data["outcome"] == "STOPPED":
                        self.stop_state = "CONFIRMED" if data.get("stop_confirmed") else "UNKNOWN"
                    elif data["outcome"] == "UNKNOWN":
                        self.stop_state = "UNKNOWN"
                # Action Result보다 먼저 최종 상태를 한 번 발행하고 다음 timer tick부터 대기로 돌아간다.
                self.publish_state()
                result = StepResult(data["outcome"], data["error_code"], data["message"])
                self.report_alarm(self.phase, result)
                self.emit_event("RUN_FINISHED", code=data["error_code"], message=data["message"],
                                severity="INFO" if data["outcome"] == "SUCCEEDED" else "ERROR")
                output = PrepareWorkpiece.Result()
                set_message_fields(output,data)
                _finish_action(handle,result)
                return output
            finally:
                with self.lock:
                    self._preparation_action_active = False
                    self.status = "IDLE"
                    self.phase = ""
                    self.stop_state = "NONE"
                    self.error_code = "NONE"
                    self.message = "공정 대기"
                    self.progress = 0.0
                    self.started_at = 0.0

        def accept_goal(self, request):
            if (request.schema_version != 2 or request.source_mode != self.coordinator.runtime_mode
                    or not request.request_id or not request.run_id or self.coordinator.active_run_id
                    or self.coordinator._preparation_action_busy):
                return GoalResponse.REJECT
            return GoalResponse.ACCEPT

        def cancel_goal(self, goal_handle):
            decision = self.coordinator.stop(goal_handle.request.run_id)
            if decision.accepted and self.preparation:
                self.preparation.invalidate()
            return CancelResponse.ACCEPT if decision.accepted else CancelResponse.REJECT

        def stop_request(self, request, response):
            if request.schema_version != 2 or not request.request_id:
                response.accepted = False
                response.run_id = request.run_id
                response.stop_state = "UNKNOWN"
                response.error_code = "UNSUPPORTED_SCHEMA_VERSION"
                response.message = "v2 정지 요청만 지원"
                return response
            decision = self.coordinator.stop(request.run_id)
            if decision.accepted and self.preparation:
                self.preparation.invalidate()
            response.accepted = decision.accepted
            response.run_id = request.run_id
            response.stop_state = decision.stop_state
            response.error_code = decision.error_code
            response.message = decision.message
            if decision.accepted:
                with self.lock:
                    self.status = "STOPPING"
                    self.stop_state = decision.stop_state
                    self.error_code = decision.error_code
                    self.message = decision.message
            return response

        def publish_state(self):
            with self.lock:
                self.seq += 1
                values = dict(self.goal_values)
                status, phase = self.status, self.phase
                stop_state, progress, started = self.stop_state, self.progress, self.started_at
                preparation_active = self._preparation_action_active
                error_code, message = self.error_code, self.message
            msg = ProcessState()
            msg.schema_version = 2
            msg.source_mode = self.coordinator.runtime_mode
            msg.source_epoch = self.epoch
            msg.seq = self.seq
            msg.published_at = _utc_time()
            msg.run_id = values.get("run_id", "")
            msg.path_id = values.get("path_id", "")
            msg.path_version = values.get("path_version", 0)
            msg.status, msg.phase, msg.stop_state = status, phase, stop_state
            msg.error_code, msg.message = error_code, message
            # 이 필드는 조각 진행률이다. 준비 진행률은 Action Feedback.progress를 사용한다.
            msg.engraving_progress = 0.0 if preparation_active else progress
            msg.elapsed_s = max(0.0, time.monotonic() - started) if started else 0.0
            msg.requested_tool_id = "engraving_drill"
            values = self.observations.values()
            with self.coordinator._lock:
                has_bound_preparation = bool(self.coordinator._preparation_bindings)
                active_run = self.coordinator._active
            if (self.coordinator.runtime_mode == "REAL" and self.preparation
                    and has_bound_preparation):
                authority_owner = getattr(self, "real_preparation_observations", None)
                if not prepared_binding_observation_valid(values, authority_owner):
                    if defer_prepared_binding_invalidation(status, phase, active_run):
                        if not self._precheck_binding_warning_active:
                            self._precheck_binding_warning_active = True
                            self.get_logger().warn(
                                "PRECHECK 중 관측 만료: 준비 BIND 유지, ENTRY 전 재검사 예정")
                    else:
                        self._precheck_binding_warning_active = False
                        self.preparation.invalidate()
                        self.get_logger().warn(
                            "준비 BIND 무효화: 제어권/로봇 연결·관측 상실 또는 보호정지")
                else:
                    self._precheck_binding_warning_active = False
            msg.joints = values["joints"]
            msg.joints_quality = values["joints_quality"]
            msg.joints_measured_at = _time_from_ns(values["joints_stamp_ns"])
            msg.tcp_quality = values["tcp_quality"]
            msg.tcp.header.frame_id = values["frame_id"]
            msg.tcp.header.stamp = _time_from_ns(values["tcp_stamp_ns"])
            if values["tcp_pose"] is not None:
                x, y, z, qx, qy, qz, qw = values["tcp_pose"]
                msg.tcp.pose.position.x, msg.tcp.pose.position.y, msg.tcp.pose.position.z = x, y, z
                msg.tcp.pose.orientation.x, msg.tcp.pose.orientation.y = qx, qy
                msg.tcp.pose.orientation.z, msg.tcp.pose.orientation.w = qz, qw
            msg.robot_connection_state = values["robot_connection_state"]
            msg.robot_mode = values["robot_mode"]
            msg.robot_quality = values["robot_quality"]
            msg.robot_measured_at = _time_from_ns(values["robot_stamp_ns"])
            msg.temperature_quality = values["temperature_quality"]
            # 장착·그리퍼·미조회 TCP 프로파일은 기본 UNKNOWN/빈값 유지.
            self.state_pub.publish(msg)

        def alarm_scope(self):
            with self.lock:
                return tuple(self.goal_values.get(k, "") for k in
                             ("path_id", "path_version", "path_sha256")) + tuple(
                    self.profile_values.get(k, "") for k in ("profile_snapshot_id", "profile_sha256"))

        def report_precheck(self, goal, config, result):
            with self.lock:
                self.profile_values = {k: config.get(k, "") for k in
                                       ("profile_snapshot_id", "profile_sha256")}
            self.report_alarm("PRECHECK", result)

        def report_alarm(self, phase, result):
            for event in self.alarms.update(self.alarm_scope(), phase, result):
                self.emit_event(*event)

        def emit_event(self, event_type, code="NONE", message="", severity="INFO"):
            with self.lock:
                self.event_seq += 1
                values = dict(self.goal_values)
                phase = self.phase
                segment_id = self.segment_id
                profile = dict(self.profile_values)
            event = ProcessEvent()
            event.schema_version = 2
            event.source_mode = self.coordinator.runtime_mode
            event.event_id = str(uuid4())
            event.source_epoch = self.epoch
            event.event_seq = self.event_seq
            event.occurred_at = _utc_time()
            event.run_id = values.get("run_id", "")
            event.request_id = values.get("request_id", "")
            event.event_type, event.phase = event_type, phase
            event.severity, event.code, event.message = severity, code, message
            event.segment_id = segment_id
            event.path_id = values.get("path_id", "")
            event.path_version = values.get("path_version", 0)
            event.path_sha256 = values.get("path_sha256", "")
            event.profile_snapshot_id = profile.get("profile_snapshot_id", "")
            event.profile_sha256 = profile.get("profile_sha256", "")
            event.tool_id = "engraving_drill"
            self.event_pub.publish(event)

        def execute_goal(self, goal_handle):
            request = goal_handle.request
            goal = {key: getattr(request, key) for key in
                    ("schema_version", "request_id", "run_id", "source_mode",
                     "path_id", "path_version", "path_sha256")}
            with self.lock:
                self.goal_values = goal
                self.profile_values = {}
                self.status = "RUNNING"
                self.phase = "PRECHECK"
                self.stop_state = "NONE"
                self.error_code = "NONE"
                self.message = "실행 요청 접수"
                self.progress = 0.0
                self.segment_id = ""
                self.started_at = time.monotonic()
            self.emit_event("COMMAND", message="실행 요청 접수")

            def feedback(phase=None, progress=None):
                with self.lock:
                    if phase:
                        self.phase = phase
                    if progress:
                        self.phase = progress.get("phase", self.phase)
                        self.progress = float(progress.get("engraving_progress", self.progress))
                        self.segment_id = progress.get("completed_segment_id", self.segment_id)
                    current_phase, current_progress = self.phase, self.progress
                    segment, started = self.segment_id, self.started_at
                packet = ExecuteProcess.Feedback()
                packet.run_id = goal["run_id"]
                packet.phase = current_phase
                packet.engraving_progress = current_progress
                packet.completed_segment_id = segment
                packet.elapsed_s = max(0.0, time.monotonic() - started)
                goal_handle.publish_feedback(packet)

            def on_phase(name):
                feedback(phase=name)
                self.emit_event("PHASE_CHANGED", message=f"{name} 시작")

            result = self.coordinator.execute(goal, on_phase=on_phase,
                                              on_progress=lambda value: feedback(progress=value))
            with self.lock:
                self.status = result.outcome
                self.stop_state = "CONFIRMED" if result.outcome == "STOPPED" else self.stop_state
                self.error_code = result.error_code
                self.message = result.message
                self.segment_id = result.observed_state.get("last_completed_segment_id", self.segment_id)
                self.progress = float(result.observed_state.get("engraving_progress", self.progress))
            # UNKNOWN/실패는 기록하되 STOPPED 자체를 장애로 생성하지 않는다.
            self.report_alarm(self.phase, result)
            self.emit_event("RUN_FINISHED", code=result.error_code, message=result.message,
                            severity="INFO" if result.ok else "ERROR")
            output = ExecuteProcess.Result()
            output.run_id = goal["run_id"]
            output.outcome = result.outcome
            output.error_code = result.error_code
            output.message = result.message
            output.last_completed_segment_id = result.observed_state.get("last_completed_segment_id", "")
            output.log_id = ""  # 요청 중복 방지 저널은 공정 실행 로그 계약을 대체하지 않는다.
            _finish_action(goal_handle, result)
            return output

        def destroy_node(self):
            from .process_state_observer import stop_process_state_observer
            stop_process_state_observer(self)
            observation_owner = getattr(self, "real_preparation_observations", None)
            if observation_owner is not None:
                observation_owner.close()
            self.action.destroy()
            if self.prepare_action:
                self.prepare_action.destroy()
            if self.preparation and self.preparation.db:
                self.preparation.db.close()
            return super().destroy_node()

    return ProcessControllerNode()


def _finish_action(goal_handle, result):
    """확인된 공정 결과를 ROS 종료 상태로 변환한다(인터페이스 권장안 §6).

    취소 요청 자체는 정지 완료가 아니다. STOPPED가 확인됐을 때만
    ROS가 수락한 Action 취소 여부에 따라 CANCELED/ABORTED를 나눈다.
    정지 서비스와 Action 취소가 겹쳐도 실행 콜백의 이 지점에서 한 번 종료한다.
    """
    if result.outcome == "SUCCEEDED":
        goal_handle.succeed()
    elif result.outcome == "STOPPED" and goal_handle.is_cancel_requested:
        goal_handle.canceled()
    else:
        goal_handle.abort()


def make_simulation_file_loader(*, path_file, result_file, snapshot_file,
                                snapshot_id, snapshot_sha256, max_state_age_s=2.0):
    """지정 파일용 Mock 로더. 누락 정보를 성공/승인 값으로 채우지 않는다.

    SIM 제어권은 이 프로세스가 소유한 Mock, 정지 상태는 Mock.stopped에서 얻는다.
    가상 접촉면은 설정으로 만든 시험 모델이며 실측/독립 보정의 검증이 아니다.
    """
    if (not isinstance(snapshot_id, str) or not snapshot_id
            or not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64
            or any(c not in "0123456789abcdef" for c in snapshot_sha256)
            or type(max_state_age_s) not in (int, float)
            or not math.isfinite(max_state_age_s) or max_state_age_s <= 0):
        raise ValueError("스냅샷 ID/SHA-256 또는 상태 유효시간 오류")
    paths = [Path(p).expanduser().resolve() for p in (path_file, result_file, snapshot_file)]
    metadata = {"id": snapshot_id, "sha256": snapshot_sha256}
    adapter = MockRobotAdapter()
    initialized = False

    def resolve(snapshot, goal, registered_snapshot_id):
        nonlocal initialized
        if registered_snapshot_id != snapshot_id:
            raise InputsUnavailable("SIM 등록 snapshot ID 불일치", "PROFILE_MISMATCH")
        evidence = PreconditionEvidence(
            runtime_mode="SIMULATION", robot_state=adapter.observe(),
            control_authority_confirmed=True,  # 프로세스 전용 Mock 제어권이며 실물 확인이 아니다.
            stop_latched=adapter.stopped, profile_snapshot_id=snapshot_id,
            max_robot_state_age_s=max_state_age_s)
        fields = resolve_simulation_settings(snapshot, goal, evidence=evidence, adapter=adapter)
        cal, wc = fields["calibration"], fields["workcell"]

        def virtual_surface(pose, direction):
            # verify 중에는 pad, execute 중에는 tool-tip 좌표를 Mock이 보관한다.
            center = cal.axis_fit_xy_m if adapter.tool_offset_m is None else wc["axis_xy_m"]
            dx = pose[0] - center[0]
            radius = wc["radius_m"]
            if abs(dx) > radius or abs(direction[1]) < 1e-9:
                return None
            surface_y = center[1] + cal.side * math.sqrt(radius * radius - dx * dx)
            distance = (surface_y - pose[1]) / direction[1]
            return distance if distance >= 0 else None

        adapter.surface_fn = virtual_surface
        if not initialized:
            adapter.pose = [*wc["axis_xy_m"], wc["top_z_m"] + 0.090, *upright_quat(cal.side)]
            initialized = True
        adapter.set_tool_offset(list(cal.offset_tool_m))
        return fields

    def load(goal):
        if goal.get("source_mode") != "SIMULATION":
            raise InputsUnavailable("파일 진입점은 SIMULATION 전용", "SOURCE_MODE_MISMATCH")
        return load_execution_inputs(goal, path_file=paths[0], result_file=paths[1],
                                     snapshot_file=paths[2], snapshot_metadata=metadata,
                                     resolve_settings=resolve)
    return load


def _parse_process_args(argv):
    parser = argparse.ArgumentParser(description="C-2 공정 노드 — 파일 입력은 SIMULATION/Mock 전용")
    parser.add_argument("--path-file", help="검증된 v2 path.json")
    parser.add_argument("--result-file", help="저장된 경로 생성 결과 JSON")
    parser.add_argument("--snapshot-file", help="c2-simulation-inputs/1 설정 스냅샷 JSON")
    parser.add_argument("--snapshot-id", help="이 실행에 사용할 스냅샷 ID")
    parser.add_argument("--snapshot-sha256", help="스냅샷 최종 파일 바이트 SHA-256")
    parser.add_argument("--max-state-age-s", type=float, default=2.0,
                        help="모의 관측 최대 경과시간(초), 기본 2")
    # ROS 인자는 ROS에 전달하고 파일 입력 인자와 분리한다.
    argv = list(argv)
    split = argv.index("--ros-args") if "--ros-args" in argv else len(argv)
    options = parser.parse_args(argv[:split])
    required = (options.path_file, options.result_file, options.snapshot_file,
                options.snapshot_id, options.snapshot_sha256)
    if any(v is not None for v in required) and not all(required):
        parser.error("파일 입력은 --path-file/--result-file/--snapshot-file/--snapshot-id/--snapshot-sha256 모두 필요")
    loader = _missing_loader
    if all(required):
        for filename in required[:3]:
            if not Path(filename).expanduser().is_file():
                parser.error(f"입력 파일 없음: {filename}")
        try:
            loader = make_simulation_file_loader(
                path_file=options.path_file, result_file=options.result_file,
                snapshot_file=options.snapshot_file, snapshot_id=options.snapshot_id,
                snapshot_sha256=options.snapshot_sha256, max_state_age_s=options.max_state_age_s)
        except ValueError as exc:
            parser.error(str(exc))
    return loader, argv[split:]


def _parse_real_preparation_args(argv):
    """REAL 준비 측정 노드의 장치 독립 기동 설정을 검사한다.

    측정 설정 자산 ID/해시는 PrepareWorkpiece Goal에서 요청별로 받는다.
    토픽 이름과 메시지 타입은 드라이버 계약이 확정된 뒤 별도 연결한다.
    """
    parser = argparse.ArgumentParser(description="C-2 REAL 준비 측정 전용 공정 노드")
    parser.add_argument("--preparation-backend-url", required=True,
                        help="불변 준비 설정 자산을 조회할 HMI backend URL")
    parser.add_argument("--preparation-journal-path", required=True,
                        help="준비 요청 중복 방지 SQLite 원장 경로")
    parser.add_argument("--controller-prefix", required=True,
                        help="두산 제어기 ROS 서비스 prefix (예: /dsr01/dsr_controller2)")
    parser.add_argument("--control-authority-topic",
                        help="controller-prefix/control_authority와 같은 제어권 토픽; 생략 시 prefix에서 생성")
    parser.add_argument("--control-authority-max-age-s", type=float, default=0.5,
                        help="제어권 관측 최대 경과시간(초), 0초 초과 0.5초 이하")
    argv = list(argv)
    split = argv.index("--ros-args") if "--ros-args" in argv else len(argv)
    options = parser.parse_args(argv[:split])

    from urllib.parse import urlparse
    endpoint = urlparse(options.preparation_backend_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        parser.error("--preparation-backend-url은 http(s) 절대 URL이어야 함")
    if not options.controller_prefix.startswith("/") or options.controller_prefix.rstrip("/") == "":
        parser.error("--controller-prefix는 /로 시작하는 구체적인 ROS prefix여야 함")
    options.controller_prefix = options.controller_prefix.rstrip("/")
    authority_topic = options.controller_prefix + "/control_authority"
    if options.control_authority_topic is None:
        options.control_authority_topic = authority_topic
    elif options.control_authority_topic != authority_topic:
        parser.error("--control-authority-topic은 --controller-prefix/control_authority와 일치해야 함")
    if (not math.isfinite(options.control_authority_max_age_s)
            or not 0 < options.control_authority_max_age_s <= 0.5):
        parser.error("--control-authority-max-age-s는 0초 초과 0.5초 이하여야 함")
    journal_path = Path(options.preparation_journal_path).expanduser()
    if not journal_path.name:
        parser.error("--preparation-journal-path에 파일 경로 필요")
    if not journal_path.parent.is_dir():
        parser.error("--preparation-journal-path 상위 디렉터리가 존재해야 함")
    options.preparation_journal_path = journal_path
    return options, argv[split:]


def _parse_real_process_args(argv):
    """준비와 조각을 함께 제공하는 REAL 공정 노드 인자를 검사한다."""
    parser = argparse.ArgumentParser(description="C-2 REAL 준비·조각 통합 공정 노드")
    parser.add_argument("--preparation-backend-url", required=True,
                        help="준비·실행 관리 자산을 조회할 HMI backend URL")
    parser.add_argument("--preparation-journal-path", required=True,
                        help="준비 요청 중복 방지 SQLite 원장 경로")
    parser.add_argument("--execution-journal-path", required=True,
                        help="실행 요청 중복 방지 SQLite 저널 경로")
    parser.add_argument("--controller-prefix", required=True,
                        help="두산 제어기 ROS 서비스 prefix")
    parser.add_argument("--control-authority-topic",
                        help="controller-prefix/control_authority와 같은 제어권 토픽; 생략 시 prefix에서 생성")
    parser.add_argument("--control-authority-max-age-s", type=float, default=0.5)
    argv = list(argv)
    split = argv.index("--ros-args") if "--ros-args" in argv else len(argv)
    options = parser.parse_args(argv[:split])

    from urllib.parse import urlparse
    endpoint = urlparse(options.preparation_backend_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        parser.error("--preparation-backend-url은 http(s) 절대 URL이어야 함")
    if not options.controller_prefix.startswith("/") or options.controller_prefix.rstrip("/") == "":
        parser.error("--controller-prefix는 /로 시작하는 구체적인 ROS prefix여야 함")
    options.controller_prefix = options.controller_prefix.rstrip("/")
    authority_topic = options.controller_prefix + "/control_authority"
    if options.control_authority_topic is None:
        options.control_authority_topic = authority_topic
    elif options.control_authority_topic != authority_topic:
        parser.error("--control-authority-topic은 --controller-prefix/control_authority와 일치해야 함")
    if (not math.isfinite(options.control_authority_max_age_s)
            or not 0 < options.control_authority_max_age_s <= 0.5):
        parser.error("--control-authority-max-age-s는 0초 초과 0.5초 이하여야 함")
    for name in ("preparation_journal_path", "execution_journal_path"):
        value = Path(getattr(options, name)).expanduser()
        if not value.name or not value.parent.is_dir():
            parser.error(f"--{name.replace('_', '-')} 상위 디렉터리가 존재하는 파일 경로 필요")
        setattr(options, name, value)
    return options, argv[split:]


def _real_preparation_options(node, options):
    from .real_preparation_observations import RealPreparationObservations
    observations = RealPreparationObservations(
        node, topic=options.control_authority_topic,
        max_age_s=options.control_authority_max_age_s,
        controller_prefix=options.controller_prefix,
        service_timeout_s=options.control_authority_max_age_s)
    # Node가 subscriber/cache 수명을 명시적으로 소유한다.
    node.real_preparation_observations = observations
    node.get_logger().info(
        "제어권 subscriber와 읽기 전용 정지 상태 조회 연결 완료")
    def start_state_observer(config):
        from .process_state_observer import start_process_state_observer
        return start_process_state_observer(node, config)
    return {
        "evidence_provider": observations.evidence,
        "evidence_max_age_s": {
            "control_authority": options.control_authority_max_age_s,
        },
        "stop_latched_provider": observations.stop_latched,
        "stop_latch_recorder": observations.record_process_result,
        "state_observer_starter": start_state_observer,
        "controller_prefix": options.controller_prefix,
    }


def real_preparation_main(args=None, *, observation_options_factory=None,
                          adapter_factory=None):
    """REAL 준비 측정 전용 노드. 조각 실행은 항상 FAILED/NOT_READY로 종료한다."""
    options, ros_args = _parse_real_preparation_args(
        sys.argv[1:] if args is None else args)
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from .preparation_action import AssetResolver

    rclpy.init(args=ros_args)
    node = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        options_factory = observation_options_factory or (
            lambda owner: _real_preparation_options(owner, options))
        robot_factory = adapter_factory or (
            lambda owner: DoosanRobotAdapter(
                owner, controller_prefix=options.controller_prefix))
        node = create_ros_node(
            load_inputs=_missing_loader,
            runtime_mode="REAL",
            measurement_only=True,
            real_adapter_factory=robot_factory,
            preparation_resolver=AssetResolver(options.preparation_backend_url),
            preparation_journal_path=options.preparation_journal_path,
            enable_preparation=True,
            real_preparation_options_factory=options_factory,
        )
        executor.add_node(node)
        node.get_logger().info(
            "REAL 준비 측정 전용 노드 기동: /c2/prepare_workpiece, ExecuteProcess 비활성")
        executor.spin()
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def real_process_main(args=None, *, observation_options_factory=None,
                      adapter_factory=None, execution_settings_resolver_factory=None,
                      fetch_bytes=None):
    """같은 REAL 공정 노드에서 준비와 조각 Action을 함께 제공한다.

    ``execution_settings_resolver_factory(node, adapter)``를 생략하면 확정된 REAL
    profile 배치를 읽는 기본 매퍼를 사용한다. 누락/null과 실행 금지 profile은
    ``NOT_READY``로 종료하며 기본값을 만들거나 로봇을 움직이지 않는다.
    """
    options, ros_args = _parse_real_process_args(sys.argv[1:] if args is None else args)
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from .preparation_action import AssetResolver

    def execution_loader_factory(node, adapter):
        settings_resolver = ((lambda snapshot, goal, snapshot_id:
                              resolve_real_execution_settings(
                                  snapshot, goal, snapshot_id, adapter=adapter,
                                  evidence_provider=lambda profile_id:
                                  read_real_execution_evidence(
                                      node, profile_id)))
                             if execution_settings_resolver_factory is None
                             else execution_settings_resolver_factory(node, adapter))
        if not callable(settings_resolver):
            raise ValueError("REAL 설정 매퍼 factory 결과는 호출 가능해야 함")
        asset_resolver = make_hmi_asset_resolver(
            options.preparation_backend_url, fetch_bytes=fetch_bytes)
        return make_asset_bundle_loader(asset_resolver, settings_resolver)

    rclpy.init(args=ros_args)
    node = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        options_factory = observation_options_factory or (
            lambda owner: _real_preparation_options(owner, options))
        robot_factory = adapter_factory or (
            lambda owner: DoosanRobotAdapter(
                owner, controller_prefix=options.controller_prefix))
        node = create_ros_node(
            load_inputs=_missing_loader,
            journal=RunJournal(options.execution_journal_path),
            runtime_mode="REAL",
            measurement_only=False,
            preparation_required=True,
            real_adapter_factory=robot_factory,
            preparation_resolver=AssetResolver(options.preparation_backend_url),
            preparation_journal_path=options.preparation_journal_path,
            enable_preparation=True,
            real_preparation_options_factory=options_factory,
            real_execution_loader_factory=execution_loader_factory,
        )
        executor.add_node(node)
        node.get_logger().info(
            "REAL 통합 공정 노드 기동: /c2/prepare_workpiece, /c2/execute_process")
        executor.spin()
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main(args=None):
    """지정 파일을 기존 로더에 주입하고 ExecuteProcess 요청을 기다린다."""
    loader, ros_args = _parse_process_args(sys.argv[1:] if args is None else args)
    import rclpy
    from rclpy.executors import MultiThreadedExecutor

    rclpy.init(args=ros_args)
    node = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        from .preparation_action import make_simulation_runner_factory
        node = create_ros_node(
            load_inputs=loader, runtime_mode="SIMULATION",
            preparation_runner_factory=make_simulation_runner_factory())
        executor.add_node(node)
        if loader is _missing_loader:
            node.get_logger().warn("실행 파일 로더 미연결: 모든 조각 요청을 거절합니다.")
        else:
            node.get_logger().info("SIMULATION 파일 로더 연결: Mock 전용, 기존 실행 요청 대기")
        executor.spin()
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
