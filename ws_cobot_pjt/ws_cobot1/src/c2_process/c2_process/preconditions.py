"""고정 드릴 공정의 실행 전 검사. 검사 중 로봇이나 그리퍼를 움직이지 않는다.

ROS 노드는 관리 ID로 이미 읽은 불변 경로/설정 파일의 원본 바이트와
검증 근거를 이 함수에 전달한다. 확인되지 않은 근거는 실행 허가가 아니다.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from .robot_adapter import StepResult


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EXPECTED_TOOL = "engraving_drill"
_EXPECTED_FRAME = "c2_base"
_MODES = {"REAL", "SIMULATION"}


@dataclass(frozen=True)
class PreconditionEvidence:
    """노드가 수집한 검사 근거. bool은 명령 접수가 아니라 확인 결과여야 한다."""

    runtime_mode: str
    robot_state: object
    control_authority_confirmed: bool = False
    stop_latched: Optional[bool] = None
    mounted_tool_id: str = ""
    mount_confirmation_source: str = "UNKNOWN"  # 호환용 과거 필드: 검사에 사용하지 않음
    mount_confirmed_at: Optional[float] = None  # monotonic 초
    gripper_closed_confirmed: bool = False
    gripper_confirmation_source: str = "UNKNOWN"  # 호환용 과거 필드: 검사에 사용하지 않음
    gripper_confirmed_at: Optional[float] = None  # monotonic 초
    path_validation_passed: bool = False
    j6_validation_passed: bool = False
    validation_path_sha256: str = ""
    profile_snapshot_id: str = ""  # 파일 저장소의 승인된 스냅샷 ID
    max_robot_state_age_s: Optional[float] = None
    max_confirmation_age_s: Optional[float] = None


def _fail(code: str, message: str) -> StepResult:
    return StepResult("FAILED", code, message, "precheck")


def _sha_ok(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def check_robot_status(
    evidence: PreconditionEvidence, *, now_monotonic: Optional[float] = None,
) -> StepResult:
    """경로 없이 로봇 기본 상태를 검사한다.

    장착·닫힘은 수동 절차이며 프로그램의 확인 대상으로 삼지 않는다.
    준비 통신 연결 전에는 기존 check_preconditions도 이 함수를 사용한다.
    """
    if evidence.runtime_mode not in _MODES:
        return _fail("SOURCE_MODE_MISMATCH", "상태검사 실행 모드 오류")
    if evidence.stop_latched is not False or evidence.control_authority_confirmed is not True:
        return _fail("NOT_READY", "정지 래치 또는 로봇 제어권 미확인")
    state = evidence.robot_state
    now = time.monotonic() if now_monotonic is None else now_monotonic
    measured_at = getattr(state, "measured_at", 0.0)
    max_age = evidence.max_robot_state_age_s
    if max_age is None or not 0 < max_age < float("inf"):
        return _fail("NOT_READY", "로봇 상태 최대 경과시간 설정 없음")
    if (getattr(state, "quality", None) != "VALID" or getattr(state, "robot_state", None) != 1
            or getattr(state, "frame_id", None) != _EXPECTED_FRAME
            or not 0 <= now - measured_at <= max_age):
        return _fail("ROBOT_NOT_READY", "최신 c2_base STANDBY 상태 미확인")
    # 장착·닫힘 확인은 수동 운영 절차. 코드가 확인 완료를 주장하지 않는다.
    return StepResult("SUCCEEDED", "NONE", "로봇 상태 검사 통과", "robot_status",
                      {"physical_confirmation_source":
                       "MANUAL_PROCEDURE_NOT_VERIFIED" if evidence.runtime_mode == "REAL" else "NOT_CHECKED_SIMULATION"})


def _check_preconditions(
    goal: Mapping,
    path: Mapping,
    path_bytes: bytes,
    snapshot: Mapping,
    snapshot_bytes: bytes,
    evidence: PreconditionEvidence,
    *,
    now_monotonic: Optional[float] = None,
    joint_check: Optional[Callable[[], StepResult]] = None,
    check_status: bool = True,
) -> StepResult:
    """실행 가능한지 검사하고 StepResult를 반환한다. 외부 호출·모션 없음."""
    if goal.get("schema_version") != 2 or path.get("schema_version") != 2:
        return _fail("UNSUPPORTED_SCHEMA_VERSION", "지원하지 않는 계약 버전")
    config = path.get("config", path)
    if not isinstance(config, Mapping):
        return _fail("INVALID_INPUT", "경로 config 형식 오류")
    validation = path.get("validation")
    if validation is not None and (not isinstance(validation, Mapping)
                                   or validation.get("passed") is not True):
        return _fail("VALIDATION_UNAVAILABLE", "경로 자체의 검증 결과가 통과가 아님")
    for key in ("request_id", "run_id", "path_id"):
        if not isinstance(goal.get(key), str) or not goal[key]:
            return _fail("INVALID_INPUT", f"{key} 없음")
    if goal.get("source_mode") not in _MODES or goal["source_mode"] != evidence.runtime_mode:
        return _fail("SOURCE_MODE_MISMATCH", "실행 요청과 실제 실행 모드 불일치")
    if path.get("source_mode") != evidence.runtime_mode:
        return _fail("SOURCE_MODE_MISMATCH", "경로와 실행 모드 불일치")
    # 시험 파일은 SIMULATION에서 검증하고 REAL에는 반입하지 않는다.
    if evidence.runtime_mode == "REAL" and any(
        item.get("test_only") is not None and item.get("test_only") is not False
        for item in (path, config, snapshot) if isinstance(item, Mapping)
    ):
        return _fail("NOT_READY", "시험 전용 경로·설정은 실물 실행에 사용할 수 없음")
    if goal.get("path_id") != path.get("path_id") or goal.get("path_version") != path.get("path_version"):
        return _fail("PATH_MISMATCH", "요청과 경로 ID/버전 불일치")
    if not isinstance(path_bytes, bytes) or not _sha_ok(goal.get("path_sha256")):
        return _fail("INVALID_INPUT", "경로 바이트 또는 SHA-256 형식 오류")
    if hashlib.sha256(path_bytes).hexdigest() != goal["path_sha256"]:
        return _fail("PATH_MISMATCH", "경로 파일 SHA-256 불일치")
    if not isinstance(snapshot_bytes, bytes) or not _sha_ok(config.get("profile_sha256")):
        return _fail("INVALID_INPUT", "설정 스냅샷 바이트 또는 SHA-256 형식 오류")
    if hashlib.sha256(snapshot_bytes).hexdigest() != config["profile_sha256"]:
        return _fail("PROFILE_MISMATCH", "설정 스냅샷 SHA-256 불일치")
    try:
        if json.loads(path_bytes) != path or json.loads(snapshot_bytes) != snapshot:
            return _fail("INVALID_INPUT", "검사 중인 데이터와 파일 바이트 내용 불일치")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return _fail("INVALID_INPUT", "경로 또는 설정 스냅샷 JSON 오류")
    # 스냅샷이 파일 안에 스스로 적은 ID만으로는 저장소 등록·승인을 증명하지 못한다.
    snapshot_id = evidence.profile_snapshot_id
    if not isinstance(snapshot_id, str) or not snapshot_id:
        return _fail("PROFILE_MISMATCH", "저장소의 승인된 스냅샷 ID 근거 없음")
    if not config.get("profile_snapshot_id") or config["profile_snapshot_id"] != snapshot_id:
        return _fail("PROFILE_MISMATCH", "설정 스냅샷 ID 불일치")
    if snapshot.get("profile_snapshot_id") and snapshot["profile_snapshot_id"] != snapshot_id:
        return _fail("PROFILE_MISMATCH", "설정 파일과 저장소 스냅샷 ID 불일치")
    if (config.get("tool_id") != _EXPECTED_TOOL or snapshot.get("tool_id") != _EXPECTED_TOOL
            or path.get("tool_id") != config.get("tool_id")):
        return _fail("TOOL_MISMATCH", "고정 드릴 ID 불일치")
    if config.get("tool_version") != snapshot.get("tool_version") or not config.get("tool_version"):
        return _fail("PROFILE_MISMATCH", "도구 버전 불일치")
    if path.get("frame_id") != _EXPECTED_FRAME or snapshot.get("frame_id") != _EXPECTED_FRAME:
        return _fail("FRAME_MISMATCH", "c2_base 프레임 불일치")
    if "frame_id" in config and config.get("frame_id") != path.get("frame_id"):
        return _fail("FRAME_MISMATCH", "경로 최상위와 config 프레임 불일치")
    if path.get("position_unit") != "m" or path.get("orientation") != "quaternion_xyzw":
        return _fail("INVALID_INPUT", "경로 위치·자세 단위 불일치")
    segments = path.get("segments")
    if not isinstance(segments, list) or not segments:
        return _fail("INVALID_INPUT", "실행 구간 없음 또는 형식 오류")
    if (any(not isinstance(segment, Mapping) for segment in segments)
            or not any(segment.get("kind") == "CUT" for segment in segments)):
        return _fail("INVALID_INPUT", "조각할 CUT 구간 없음 또는 구간 형식 오류")
    if check_status:
        status = check_robot_status(evidence, now_monotonic=now_monotonic)
        if not status.ok:
            return status
    if (evidence.path_validation_passed is not True
            or evidence.validation_path_sha256 != goal["path_sha256"]):
        return _fail("VALIDATION_UNAVAILABLE", "현재 경로의 검증 근거 없음")
    if joint_check is None:
        if evidence.j6_validation_passed is not True:
            return _fail("VALIDATION_UNAVAILABLE", "현재 경로의 관절 검사 근거 없음")
        return StepResult("SUCCEEDED", "NONE", "실행 전 검사 통과", "precheck")
    try:
        joints = joint_check()
    except Exception as exc:
        return StepResult("UNKNOWN", "VALIDATION_UNAVAILABLE", f"관절 검사 결과 미확인: {exc}", "precheck")
    if not isinstance(joints, StepResult) or not isinstance(joints.observed_state, dict):
        return StepResult("UNKNOWN", "VALIDATION_UNAVAILABLE", "관절 검사 결과 형식 오류", "precheck")
    if not joints.ok:
        return joints
    return StepResult("SUCCEEDED", "NONE", "실행 전 검사 통과", "precheck",
                      {"joint_check": dict(joints.observed_state)})


def check_preconditions(*args, **kwargs) -> StepResult:
    """기존 직접 실행 입구: 상태와 경로를 확인한다."""
    return _check_preconditions(*args, **kwargs)


def check_prepared_path(*args, **kwargs) -> StepResult:
    """준비 BIND 후 경로/설정/IK와 실행 직전 로봇 상태를 검사한다."""
    return _check_preconditions(*args, **kwargs, check_status=True)
