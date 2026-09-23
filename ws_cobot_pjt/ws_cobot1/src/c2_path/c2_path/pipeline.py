"""ROS와 독립적인 GeneratePath 상위 파이프라인.

계산 단계의 유일한 조합 지점이며, 일부 획 실패·빈 경로·검증 실패를 성공
산출물로 공개하지 않는다. 현재 workcell.py 값은 test_only이므로 기본은 SIMULATION만
허용한다. REAL `/3`은 `allow_real_preview=True`일 때 미리보기 전용으로 받고,
별도 실행 계약은 `allow_real_execution=True`일 때만 실행 전 검사 후보로 만든다.
"""
from __future__ import annotations

import math
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping
from uuid import UUID

from . import (extract_2d, generate_path, image_to_hatch, image_to_svg, map_3d,
               optimize_2d, readiness, snapshot, validate_path)
from . import workcell as wc
from .artifacts import ArtifactError, ArtifactWrite, json_bytes, new_id, sha256_bytes


SUPPORTED_PRESETS = {"raster_centerline_bezier", "raster_parallel_hatch"}
STAGES = (
    "CONVERTING",
    "EXTRACTING_2D",
    "OPTIMIZING_2D",
    "MAPPING_3D",
    "BUILDING_PATH",
    "VALIDATING",
)


class PipelineError(RuntimeError):
    def __init__(self, code, message, *, svg_asset_id="", validation_report_id=""):
        self.code = code
        self.message = message
        self.svg_asset_id = svg_asset_id
        self.validation_report_id = validation_report_id
        super().__init__(message)


class GenerationCanceled(PipelineError):
    def __init__(self):
        super().__init__("CANCELED", "경로 생성 요청이 취소되었습니다.")


@dataclass(frozen=True)
class GenerationResult:
    path_id: str
    path_version: int
    path_sha256: str
    path_asset_id: str
    svg_asset_id: str
    preview_asset_id: str
    validation_report_id: str
    segment_count: int
    cut_length_m: float
    # 실행 사전 점검 결과(WITHIN_LIMITS/OUT_OF_LIMITS). GeneratePath Result 에는 필드가 없어 메시지·산출물로만 전달한다.
    execution_precheck: str = ""
    execution_message: str = ""


SUCCESS_MESSAGE = "경로 생성과 기하 검증이 완료되었습니다. 실행 전 J6/IK 검사가 별도로 필요합니다."


def success_message(result: "GenerationResult") -> str:
    """GeneratePath Result.message. 생성 성공이 실행 가능을 뜻하지 않는다는 점과 사전 점검 결과를 함께 적는다."""
    return f"{SUCCESS_MESSAGE} {result.execution_message}".strip()


def _uuid(value, name):
    try:
        normalized = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PipelineError("INVALID_INPUT", f"{name}는 UUID여야 합니다.") from exc
    if normalized != str(value).lower():
        raise PipelineError("INVALID_INPUT", f"{name}는 정규화된 UUID여야 합니다.")
    return normalized


def _sha(value, name):
    value = str(value)
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise PipelineError("INVALID_INPUT", f"{name}는 소문자 SHA-256이어야 합니다.")
    return value


def validate_goal(goal: Mapping, *, allow_real_preview: bool = False) -> dict:
    value = dict(goal)
    if value.get("schema_version") != wc.PATH_SCHEMA_VERSION:
        raise PipelineError("UNSUPPORTED_SCHEMA_VERSION", "고정 드릴 schema_version=2만 지원합니다.")
    value["request_id"] = _uuid(value.get("request_id"), "request_id")
    value["asset_id"] = _uuid(value.get("asset_id"), "asset_id")
    value["profile_snapshot_id"] = _uuid(value.get("profile_snapshot_id"), "profile_snapshot_id")
    value["asset_sha256"] = _sha(value.get("asset_sha256"), "asset_sha256")
    value["profile_sha256"] = _sha(value.get("profile_sha256"), "profile_sha256")
    mode = value.get("source_mode")
    if mode == "REAL" and allow_real_preview:
        pass  # REAL 은 스냅샷 /3(추정값·미리보기 전용)과 함께일 때만 계산된다. 아래 profile 검사에서 확인한다.
    elif mode == "REAL":
        raise PipelineError("NOT_READY", "REAL 요청은 이 노드에서 꺼져 있습니다(allow_real_preview). "
                                         "현재 c2_path 설정은 test_only이므로 SIMULATION만 지원합니다.")
    elif mode != "SIMULATION":
        raise PipelineError("NOT_READY", "현재 c2_path 설정은 test_only이므로 SIMULATION만 지원합니다.")
    if value.get("tool_id") != wc.TOOL_ID:
        raise PipelineError("UNSUPPORTED_RECIPE", f"tool_id는 {wc.TOOL_ID}이어야 합니다.")
    if value.get("conversion_preset") not in SUPPORTED_PRESETS:
        raise PipelineError(
            "UNSUPPORTED_FORMAT",
            "지원 preset: raster_centerline_bezier, raster_parallel_hatch",
        )
    for name in ("width_mm", "height_mm"):
        number = value.get(name)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise PipelineError("INVALID_INPUT", f"{name}는 유한한 수여야 합니다.")
        if not 0 < number <= 500:
            raise PipelineError("INVALID_INPUT", f"{name}는 0보다 크고 500 이하여야 합니다.")
    for name in ("offset_u_mm", "offset_v_mm", "rotation_deg"):
        number = value.get(name)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise PipelineError("INVALID_INPUT", f"{name}는 유한한 수여야 합니다.")
    if not -500 <= value["offset_u_mm"] <= 500 or not -500 <= value["offset_v_mm"] <= 500:
        raise PipelineError("INVALID_INPUT", "offset_u_mm/offset_v_mm는 -500~500 범위여야 합니다.")
    if not -180 <= value["rotation_deg"] <= 180:
        raise PipelineError("INVALID_INPUT", "rotation_deg는 -180~180 범위여야 합니다.")
    return value


def _same(actual, expected, label, errors, tol=1e-9):
    # bool 은 int/float 의 하위 형이라 True == 1 이다. 스냅샷에 true/false 가 숫자 자리에 들어와도
    # 통과하지 않도록 자료형까지 확인한다 (예: tools_config_version=true).
    if isinstance(expected, float):
        try:
            okay = not isinstance(actual, (bool, str)) and math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=tol)
        except (TypeError, ValueError):
            okay = False
    elif isinstance(expected, (bool, int, str)):
        okay = type(actual) is type(expected) and actual == expected
    else:
        okay = actual == expected
    if not okay:
        errors.append(f"{label}: {actual!r} != {expected!r}")


PROFILE_CONTRACT_V1 = "c2-path-test-profile/1"
PROFILE_CONTRACT_V2 = "c2-path-test-profile/2"
# REAL 추정값 미리보기 전용. **이름·필드는 팀 합의 전 제안이다**(BUNDLE_SPEC.md 5.1절). 바꿀 때는 이 상수만 고친다.
PROFILE_CONTRACT_V3 = "c2-path-test-profile/3"
PROFILE_CONTRACT_V4 = "c2-path-real-execution-profile/1"
CALIBRATION_STATUS_REAL_PREVIEW = "REAL_ESTIMATE_PREVIEW_ONLY"
REAL_PREVIEW_MEASUREMENT_STATUSES = ("ESTIMATED", "FORCE_CONTACT_ESTIMATE")   # 준비 Result 의 validity 값 그대로
REAL_EXECUTION_OFFSET_STATUSES = ("VERIFIED", "ESTIMATED")
REAL_EXECUTION_MOTION_PROFILE_IDS = (
    "candle_approach", "candle_cut", "candle_travel", "candle_retract",
)
UUID_FIELDS_V3 = ("preparation_id", "measurement_id", "input_profile_snapshot_id", "measurement_record_id")
SHA256_FIELDS_V3 = ("input_profile_sha256", "measurement_record_sha256")
HEIGHT_REFERENCE_BOTTOM = "bottom"       # v=0 은 양초 바닥(축 원점 z). 윗면 기준이 아니다.
V_DIRECTION_UP = "up"                    # v 는 바닥에서 위로 갈수록 커진다.
MEASUREMENT_ID_MAX_LEN = 128


def _identity_errors(profile: Mapping, errors: list, source_mode: str = "SIMULATION") -> None:
    """/1·/2·/3 공통: 작업 셀·도구·프레임 식별. 실측으로 바뀌는 값이 아니라 c2_path 가 아는 설정과 같아야 한다.
    `source_mode` 는 계약이 정한다(/1·/2 는 SIMULATION, /3 은 REAL). 다른 값으로 바꿔 통과시키지 않는다."""
    _same(profile.get("schema_version"), 2, "schema_version", errors)
    _same(profile.get("source_mode"), source_mode, "source_mode", errors)
    _same(profile.get("frame_id"), wc.FRAME_ID, "frame_id", errors)
    _same(profile.get("workcell_id"), wc.WORKCELL_ID, "workcell_id", errors)
    _same(profile.get("workcell_version"), wc.WORKCELL_VERSION, "workcell_version", errors)
    _same(profile.get("tools_config_id"), wc.TOOLS_CONFIG_ID, "tools_config_id", errors)
    _same(profile.get("tools_config_version"), wc.TOOLS_CONFIG_VERSION, "tools_config_version", errors)
    _same(profile.get("tool_id"), wc.TOOL_ID, "tool_id", errors)
    _same(profile.get("tool_version"), wc.TOOL_VERSION, "tool_version", errors)
    _same(profile.get("tcp_id"), wc.TCP_PROFILE_ID, "tcp_id", errors)
    _same(profile.get("tcp_version"), wc.TCP_PROFILE_VERSION, "tcp_version", errors)
    _same(profile.get("load_id"), wc.LOAD_PROFILE_ID, "load_id", errors)
    _same(profile.get("load_version"), wc.LOAD_PROFILE_VERSION, "load_version", errors)
    _same(profile.get("gripper_open_allowed"), False, "gripper_open_allowed", errors)


def validate_profile_identity(profile: Mapping, source_mode: str) -> None:
    """측정 전 배포 설정과 경로 생성이 같은 식별 기준을 사용한다."""
    errors = []
    _identity_errors(profile, errors, source_mode)
    if errors:
        raise ValueError("경로 설정 식별 불일치: " + "; ".join(errors))


def _fixed_axis_errors(surface: Mapping, errors: list) -> None:
    """`/1`·`/2` 공통: 원통 종류·축 방향·u 원점·이음매는 아직 상수와 같은 값만 받는다.
    이음매·u 원점은 J5 위험 구역(로봇 쪽)과 도안 배치 기준에 묶여 있고, 축은 +Z 만 계산·미리보기가 지원한다."""
    _same(surface.get("kind"), "cylinder", "surface.kind", errors)
    _same(surface.get("axis_direction"), list(wc.AXIS_DIRECTION), "surface.axis_direction", errors)
    _same(surface.get("u_origin_angle_deg"), wc.U_ORIGIN_ANGLE_DEG,
          "surface.u_origin_angle_deg", errors)
    _same(surface.get("seam_angle_deg"), wc.SEAM_ANGLE_DEG, "surface.seam_angle_deg", errors)


def _default_geometry_errors(surface: Mapping, errors: list) -> None:
    """`/1`: 원통 치수(반지름·높이·축 원점)도 test_only 상수와 정확히 같아야 한다."""
    _fixed_axis_errors(surface, errors)
    _same(surface.get("radius_mm"), wc.RADIUS_M * 1000.0, "surface.radius_mm", errors, 1e-6)
    _same(surface.get("height_mm"), wc.HEIGHT_TOTAL_M * 1000.0, "surface.height_mm", errors, 1e-6)
    _same(surface.get("axis_origin_m"), [wc.AXIS_ORIGIN_XY_M[0], wc.AXIS_ORIGIN_XY_M[1],
                                          wc.AXIS_ORIGIN_Z_M], "surface.axis_origin_m", errors)


def profile_surface(profile: Mapping) -> wc.Surface:
    """검증을 통과한 스냅샷이 쓰는 원통 형상. `/1` 은 기본 상수, `/2` 는 스냅샷의 실측 값이다."""
    if isinstance(profile, Mapping) and profile.get("contract") in (
            PROFILE_CONTRACT_V2, PROFILE_CONTRACT_V3, PROFILE_CONTRACT_V4):
        return wc.surface_from_snapshot(profile["surface"])
    return wc.DEFAULT_SURFACE


def _validate_profile_v1(profile: Mapping, surface: Mapping) -> None:
    """`/1`: 하드코딩된 test_only workcell 값과 정확히 같을 때만 받는다."""
    errors = []
    _identity_errors(profile, errors)
    _default_geometry_errors(surface, errors)
    _same(surface.get("valid_v_range_mm"), [v * 1000.0 for v in wc.WORKABLE_HEIGHT_RANGE_M],
          "surface.valid_v_range_mm", errors)
    _same(surface.get("reachable_angle_deg"), list(wc.REACHABLE_ANGLE_DEG),
          "surface.reachable_angle_deg", errors)
    if errors:
        raise PipelineError("PROFILE_MISMATCH", "설정 스냅샷과 c2_path test_only 값이 다릅니다: " + "; ".join(errors[:4]))


def _iso8601(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _validate_profile_v2(profile: Mapping, surface: Mapping) -> None:
    """`/2`: 요청별 작업 범위·도달각을 스냅샷에서 받는다.

    필수: surface.height_reference="bottom", surface.v_direction="up", calibration_status="SIMULATION_ONLY".
    범위(`valid_v_range_mm`, `reachable_angle_deg`)와 원통 치수(`radius_mm`, `height_mm`, `axis_origin_m`)는 코드 상수와
    같을 필요가 없고 구조 조건만 본다(`profile_surface` 가 이 값으로 경로를 계산한다). 종류(cylinder)·축 방향(+Z)·u 원점·
    이음매는 아직 상수와 같은 값만 받는다. 실측 유효 상태 값은 제어팀 확인 후 추가한다."""
    errors = []
    _identity_errors(profile, errors)
    _same(profile.get("calibration_status"), "SIMULATION_ONLY", "calibration_status", errors)
    _same(surface.get("height_reference"), HEIGHT_REFERENCE_BOTTOM, "surface.height_reference", errors)
    _same(surface.get("v_direction"), V_DIRECTION_UP, "surface.v_direction", errors)
    for key in ("measurement_id", "measured_at"):
        if key in profile and profile[key] is not None:
            value = profile[key]
            if key == "measurement_id":
                okay = isinstance(value, str) and 0 < len(value) <= MEASUREMENT_ID_MAX_LEN
                if not okay:
                    errors.append(f"measurement_id는 1~{MEASUREMENT_ID_MAX_LEN}자 문자열이어야 합니다.")
            elif not _iso8601(value):
                errors.append("measured_at은 시간대가 있는 ISO 8601 문자열이어야 합니다.")
    # 범위·도달각 등 구조 조건 (0 <= 하한 < 상한 <= height_mm, 이음매가 도달각 안에 없음 등)
    errors.extend(snapshot.surface_geometry_errors(surface))
    _fixed_axis_errors(surface, errors)
    if errors:
        # 같은 원인이 두 검사에서 중복될 수 있어 순서를 지키며 중복만 제거한다.
        unique = list(dict.fromkeys(errors))
        raise PipelineError("PROFILE_MISMATCH", "요청 스냅샷(/2)이 올바르지 않습니다: " + "; ".join(unique[:4]))


def _provenance_errors(profile: Mapping, errors: list) -> None:
    """`/3`: 측정 출처 필수. 없거나 형식이 틀리면 보충·추정하지 않고 거절한다."""
    for key in UUID_FIELDS_V3:
        value = profile.get(key)
        try:
            okay = isinstance(value, str) and str(UUID(value)) == value.lower() == value
        except (ValueError, AttributeError, TypeError):
            okay = False
        if not okay:
            errors.append(f"측정 출처 {key}는 정규화된 UUID여야 합니다.")
    for key in SHA256_FIELDS_V3:
        value = profile.get(key)
        if not (isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)):
            errors.append(f"측정 출처 {key}는 소문자 SHA-256이어야 합니다.")
    if not _iso8601(profile.get("measured_at")):
        errors.append("측정 출처 measured_at은 시간대가 있는 ISO 8601 문자열이어야 합니다.")


def _validate_profile_v3(profile: Mapping, surface: Mapping) -> None:
    """`/3`: REAL 추정값 미리보기 전용. 실행 승인이 아니며 이 스냅샷으로 만든 경로도 test_only 다.

    /2 와 같은 기하 구조 조건에, source_mode=REAL·측정 상태(ESTIMATED/FORCE_CONTACT_ESTIMATE)·측정 출처를 더한다.
    REAL 을 SIMULATION 으로 바꿔 받거나(반대도) 정확도 검증 완료로 표시된 값은 받지 않는다."""
    errors = []
    _identity_errors(profile, errors, "REAL")
    _same(profile.get("calibration_status"), CALIBRATION_STATUS_REAL_PREVIEW, "calibration_status", errors)
    status = profile.get("measurement_status")
    if not (isinstance(status, str) and status in REAL_PREVIEW_MEASUREMENT_STATUSES):
        errors.append(f"measurement_status는 {'/'.join(REAL_PREVIEW_MEASUREMENT_STATUSES)} 중 하나여야 합니다: {status!r}")
    assumptions = profile.get("measurement_assumptions")
    if not (isinstance(assumptions, Mapping) and assumptions.get("independent_accuracy_verified") is False):
        errors.append("measurement_assumptions.independent_accuracy_verified=false 가 필요합니다(정확도 미검증 표시 유지).")
    _provenance_errors(profile, errors)
    _same(surface.get("height_reference"), HEIGHT_REFERENCE_BOTTOM, "surface.height_reference", errors)
    _same(surface.get("v_direction"), V_DIRECTION_UP, "surface.v_direction", errors)
    errors.extend(snapshot.surface_geometry_errors(surface))
    _fixed_axis_errors(surface, errors)
    if errors:
        unique = list(dict.fromkeys(errors))
        raise PipelineError("PROFILE_MISMATCH", "요청 스냅샷(/3, REAL 추정값)이 올바르지 않습니다: " + "; ".join(unique[:4]))


def _validate_profile_v4(profile: Mapping, surface: Mapping) -> None:
    """준비 성공에 연결된 REAL 실행 후보용 스냅샷.

    c2_path는 로봇 실행 가능 판정을 하지 않는다. 다만 공정 노드가 요구하는 승인
    근거가 같은 불변 스냅샷에 들어 있는지 확인한 뒤 ``test_only=false`` 후보를
    만든다. 최종 IK·관절·도구 확인은 ExecuteProcess가 모션 전에 다시 수행한다.
    """
    errors = []
    _identity_errors(profile, errors, "REAL")
    _same(profile.get("test_only"), False, "test_only", errors)
    _same(profile.get("real_execution_allowed"), True, "real_execution_allowed", errors)
    _provenance_errors(profile, errors)
    validity = profile.get("validity", profile.get("measurement_status"))
    measurement_status = profile.get("measurement_status", validity)
    if validity not in REAL_PREVIEW_MEASUREMENT_STATUSES:
        errors.append("validity/measurement_status는 ESTIMATED 또는 FORCE_CONTACT_ESTIMATE여야 합니다.")
    if measurement_status != validity:
        errors.append("validity와 measurement_status는 같은 원본 측정 확인 수준이어야 합니다.")
    absolute_top_verified = profile.get("absolute_top_verified")
    if type(absolute_top_verified) is not bool:
        errors.append("absolute_top_verified는 원본 측정 결과의 boolean이어야 합니다.")
    assumptions = profile.get("measurement_assumptions")
    if not isinstance(assumptions, Mapping):
        errors.append("measurement_assumptions 원본 측정 확인 정보가 필요합니다.")
    else:
        independent_accuracy_verified = assumptions.get("independent_accuracy_verified")
        if type(independent_accuracy_verified) is not bool:
            errors.append("measurement_assumptions.independent_accuracy_verified는 boolean이어야 합니다.")
        if ("absolute_top_verified" in assumptions
                and assumptions["absolute_top_verified"] != absolute_top_verified):
            errors.append("absolute_top_verified와 measurement_assumptions 원본 값이 일치해야 합니다.")
    _same(surface.get("height_reference"), HEIGHT_REFERENCE_BOTTOM, "surface.height_reference", errors)
    _same(surface.get("v_direction"), V_DIRECTION_UP, "surface.v_direction", errors)
    errors.extend(snapshot.surface_geometry_errors(surface))
    _fixed_axis_errors(surface, errors)

    workcell = profile.get("workcell")
    top = workcell.get("top") if isinstance(workcell, Mapping) else None
    offset = top.get("contact_offset_tool_m") if isinstance(top, Mapping) else None
    if not isinstance(workcell, Mapping) or workcell.get("measurement_scope") != "ABSOLUTE_GEOMETRY":
        errors.append("workcell.measurement_scope=ABSOLUTE_GEOMETRY가 필요합니다.")
    offset_status = top.get("offset_status") if isinstance(top, Mapping) else None
    if (not isinstance(top, Mapping) or offset_status not in REAL_EXECUTION_OFFSET_STATUSES
            or not isinstance(top.get("offset_record_id"), str) or not top.get("offset_record_id").strip()
            or not isinstance(offset, (list, tuple)) or len(offset) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (offset or []))):
        errors.append("출처가 있는 VERIFIED/ESTIMATED workcell.top 접촉 오프셋이 필요합니다.")
    if (offset_status == "ESTIMATED"
            and (not isinstance(top.get("estimate_source"), str) or not top.get("estimate_source").strip())):
        errors.append("ESTIMATED 접촉 오프셋에는 workcell.top.estimate_source가 필요합니다.")
    if isinstance(workcell, Mapping):
        _same(workcell.get("tcp_id"), profile.get("tcp_id"), "workcell.tcp_id", errors)
        _same(workcell.get("load_id"), profile.get("load_id"), "workcell.load_id", errors)
    for key in ("tip_calibration", "execution_context", "joint_check_arguments"):
        if not isinstance(profile.get(key), Mapping):
            errors.append(f"{key} 실행 설정이 필요합니다.")
    execution = profile.get("execution_context")
    if isinstance(execution, Mapping):
        _same(execution.get("source_mode"), "REAL", "execution_context.source_mode", errors)
        for key in ("motion_profiles", "tool_profile", "stop_profile"):
            if not isinstance(execution.get(key), Mapping):
                errors.append(f"execution_context.{key}가 필요합니다.")
        profiles = execution.get("motion_profiles")
        if isinstance(profiles, Mapping):
            missing = [name for name in REAL_EXECUTION_MOTION_PROFILE_IDS if name not in profiles]
            if missing:
                errors.append("실제 실행 설정에 필요한 motion_profile_id가 없습니다: " + ", ".join(missing))
    joints = profile.get("joint_check_arguments")
    limits = joints.get("limits_deg") if isinstance(joints, Mapping) else None
    margin = joints.get("j6_margin_deg") if isinstance(joints, Mapping) else None
    if (not isinstance(limits, (list, tuple)) or len(limits) != 6
            or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                   or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in pair)
                   or pair[0] >= pair[1] for pair in (limits or []))):
        errors.append("joint_check_arguments.limits_deg 6축 범위가 필요합니다.")
    if isinstance(limits, (list, tuple)) and len(limits) == 6:
        if (isinstance(margin, bool) or not isinstance(margin, (int, float)) or not math.isfinite(margin)
                or margin < 0 or 2 * margin >= limits[5][1] - limits[5][0]):
            errors.append("joint_check_arguments.j6_margin_deg가 유효하지 않습니다.")
    if errors:
        unique = list(dict.fromkeys(errors))
        raise PipelineError("PROFILE_MISMATCH", "REAL 실행 스냅샷이 올바르지 않습니다: " + "; ".join(unique[:6]))


def validate_profile(profile: Mapping) -> None:
    """스냅샷 `contract` 로 검사 규칙을 고른다. 없으면 기존(/1)과 같다.

      /1 : c2_path 상수와 정확히 같을 때만 받는다 (valid_v_range_mm=[10,140], 원통 치수도 상수).
      /2 : 새 필수 필드 + 요청별 작업 범위·도달각·원통 치수. 축 방향·u 원점·이음매는 아직 상수와 같아야 한다.
    """
    surface = profile.get("surface") if isinstance(profile, Mapping) else None
    surface = surface if isinstance(surface, Mapping) else {}
    contract = profile.get("contract") if isinstance(profile, Mapping) else None
    if contract in (None, PROFILE_CONTRACT_V1):
        _validate_profile_v1(profile, surface)
    elif contract == PROFILE_CONTRACT_V2:
        _validate_profile_v2(profile, surface)
    elif contract == PROFILE_CONTRACT_V3:
        _validate_profile_v3(profile, surface)
    elif contract == PROFILE_CONTRACT_V4:
        _validate_profile_v4(profile, surface)
    else:
        raise PipelineError(
            "PROFILE_MISMATCH",
            f"지원하지 않는 스냅샷 contract입니다: {contract!r} "
            f"(지원: {PROFILE_CONTRACT_V1}, {PROFILE_CONTRACT_V2}, {PROFILE_CONTRACT_V3}, {PROFILE_CONTRACT_V4})")


def check_goal_profile_mode(goal: Mapping, profile: Mapping) -> None:
    """요청의 source_mode 와 스냅샷의 출처가 같아야 한다. REAL↔SIMULATION 을 서로 바꿔 통과시키지 않는다."""
    contract = profile.get("contract") or PROFILE_CONTRACT_V1
    goal_mode, profile_mode = goal.get("source_mode"), profile.get("source_mode")
    expected = "REAL" if contract in (PROFILE_CONTRACT_V3, PROFILE_CONTRACT_V4) else "SIMULATION"
    if goal_mode != profile_mode or goal_mode != expected:
        raise PipelineError(
            "PROFILE_MISMATCH",
            f"요청 source_mode={goal_mode!r}, 스냅샷 source_mode={profile_mode!r}, 스냅샷 contract={contract}: "
            f"REAL 은 /3 또는 실행 계약 스냅샷과, SIMULATION 은 /1·/2 스냅샷과만 계산합니다.")


def matching_test_profile_v4(**surface_overrides) -> dict:
    """실행 계약 단위시험용 형식 예시. 실제 로봇 승인값으로 사용하지 않는다."""
    profile = matching_test_profile_v3(measurement_status="ESTIMATED", **surface_overrides)
    profile.pop("calibration_status", None)
    profile.update({
        "contract": PROFILE_CONTRACT_V4,
        "test_only": False,
        "real_execution_allowed": True,
        "validity": "ESTIMATED",
        "absolute_top_verified": False,
        "workcell": {"measurement_scope": "ABSOLUTE_GEOMETRY", "tcp_id": wc.TCP_PROFILE_ID,
                     "load_id": wc.LOAD_PROFILE_ID,
                     "top": {"contact_offset_tool_m": [0.0, 0.0, 0.02], "offset_status": "ESTIMATED",
                             "offset_record_id": "unit-test-offset",
                             "estimate_source": "unit-test-estimate"}},
        "tip_calibration": {"tool_id": wc.TOOL_ID, "offset_tool_m": [0.0, -0.1, 0.0]},
        "execution_context": {"source_mode": "REAL", "motion_profiles": {
                              "candle_approach": {}, "candle_cut": {},
                              "candle_travel": {}, "candle_retract": {}},
                              "tool_profile": {"tool_id": wc.TOOL_ID}, "stop_profile": {"mode": 1}},
        "joint_check_arguments": {"limits_deg": [[-180.0, 180.0]] * 6, "j6_margin_deg": 5.0},
    })
    return profile


def matching_test_profile() -> dict:
    """통합 시험에서 서버가 등록할 수 있는 명시적 test_only 스냅샷."""
    return {
        "contract": PROFILE_CONTRACT_V1,
        "schema_version": 2,
        "source_mode": "SIMULATION",
        "workcell_id": wc.WORKCELL_ID,
        "workcell_version": wc.WORKCELL_VERSION,
        "tools_config_id": wc.TOOLS_CONFIG_ID,
        "tools_config_version": wc.TOOLS_CONFIG_VERSION,
        "tool_id": wc.TOOL_ID,
        "tool_version": wc.TOOL_VERSION,
        "tcp_id": wc.TCP_PROFILE_ID,
        "tcp_version": wc.TCP_PROFILE_VERSION,
        "load_id": wc.LOAD_PROFILE_ID,
        "load_version": wc.LOAD_PROFILE_VERSION,
        "frame_id": wc.FRAME_ID,
        "gripper_open_allowed": False,
        "calibration_status": "SIMULATION_ONLY",
        "surface": {
            "kind": "cylinder",
            "radius_mm": wc.RADIUS_M * 1000.0,
            "height_mm": wc.HEIGHT_TOTAL_M * 1000.0,
            "axis_origin_m": [wc.AXIS_ORIGIN_XY_M[0], wc.AXIS_ORIGIN_XY_M[1], wc.AXIS_ORIGIN_Z_M],
            "axis_direction": list(wc.AXIS_DIRECTION),
            "valid_v_range_mm": [v * 1000.0 for v in wc.WORKABLE_HEIGHT_RANGE_M],
            "u_origin_angle_deg": wc.U_ORIGIN_ANGLE_DEG,
            "seam_angle_deg": wc.SEAM_ANGLE_DEG,
            "reachable_angle_deg": list(wc.REACHABLE_ANGLE_DEG),
        },
    }


def matching_test_profile_v2(*, valid_v_range_mm=None, reachable_angle_deg=None,
                            measurement_id=None, measured_at=None,
                            radius_mm=None, height_mm=None, axis_origin_m=None) -> dict:
    """`/2` 시험용 스냅샷. HMI 백엔드가 실측을 등록할 때 만들 모양을 흉내낸다(SIMULATION_ONLY).

    기본 값은 /1 과 같지만 범위·도달각·원통 치수(radius_mm, height_mm, axis_origin_m)를 요청별로 바꿔 넣을 수 있다."""
    profile = matching_test_profile()
    profile["contract"] = PROFILE_CONTRACT_V2
    surface = profile["surface"]
    surface["height_reference"] = HEIGHT_REFERENCE_BOTTOM
    surface["v_direction"] = V_DIRECTION_UP
    if valid_v_range_mm is not None:
        surface["valid_v_range_mm"] = list(valid_v_range_mm)
    if reachable_angle_deg is not None:
        surface["reachable_angle_deg"] = list(reachable_angle_deg)
    if radius_mm is not None:
        surface["radius_mm"] = radius_mm
    if height_mm is not None:
        surface["height_mm"] = height_mm
    if axis_origin_m is not None:
        surface["axis_origin_m"] = list(axis_origin_m)
    if measurement_id is not None:
        profile["measurement_id"] = measurement_id
    if measured_at is not None:
        profile["measured_at"] = measured_at
    return profile


def matching_test_profile_v3(*, measurement_status="ESTIMATED", **surface_overrides) -> dict:
    """`/3`(REAL 추정값 미리보기 전용) 시험용 스냅샷. **가짜 측정 출처를 채운 형식 예시**이며 실제 측정이 아니다.

    surface_overrides: radius_mm, height_mm, axis_origin_m, valid_v_range_mm, reachable_angle_deg."""
    profile = matching_test_profile_v2(**surface_overrides)
    profile.update({
        "contract": PROFILE_CONTRACT_V3,
        "source_mode": "REAL",
        "calibration_status": CALIBRATION_STATUS_REAL_PREVIEW,
        "measurement_status": measurement_status,
        "measurement_assumptions": {"vertical_axis_assumed": True, "tilt_measured": False,
                                    "independent_accuracy_verified": False},
        "preparation_id": "11111111-1111-4111-8111-111111111111",
        "measurement_id": "22222222-2222-4222-8222-222222222222",
        "input_profile_snapshot_id": "33333333-3333-4333-8333-333333333333",
        "input_profile_sha256": "a" * 64,
        "measurement_record_id": "44444444-4444-4444-8444-444444444444",
        "measurement_record_sha256": "b" * 64,
        "measured_at": "2026-09-21T13:00:00+09:00",
    })
    return profile


def _real_preview_marks(profile: Mapping) -> dict:
    """/3 산출물에 남길 출처·상태 표시(경로 config, 보고서, 미리보기 공통)."""
    return {
        "measurement_status": profile.get("measurement_status"),
        "calibration_status": profile.get("calibration_status"),
        "independent_accuracy_verified": False,
        "preview_only": True,
        "real_execution_allowed": False,
        "preparation_id": profile.get("preparation_id"),
        "measurement_id": profile.get("measurement_id"),
        "measurement_record_id": profile.get("measurement_record_id"),
        "measurement_record_sha256": profile.get("measurement_record_sha256"),
        "input_profile_snapshot_id": profile.get("input_profile_snapshot_id"),
        "input_profile_sha256": profile.get("input_profile_sha256"),
        "measured_at": profile.get("measured_at"),
    }


def _real_execution_marks(profile: Mapping) -> dict:
    """실행 후보 산출물에 보존할 준비·측정 binding."""
    top = profile.get("workcell", {}).get("top", {})
    return {
        "measurement_status": profile.get("measurement_status"),
        "validity": profile.get("validity", profile.get("measurement_status")),
        "absolute_top_verified": profile.get("absolute_top_verified"),
        "independent_accuracy_verified": profile.get("measurement_assumptions", {}).get(
            "independent_accuracy_verified"),
        "offset_status": top.get("offset_status"),
        "offset_record_id": top.get("offset_record_id"),
        "offset_estimate_source": top.get("estimate_source"),
        "preview_only": False,
        "real_execution_allowed": True,
        "preparation_id": profile.get("preparation_id"),
        "measurement_id": profile.get("measurement_id"),
        "measurement_record_id": profile.get("measurement_record_id"),
        "measurement_record_sha256": profile.get("measurement_record_sha256"),
        "input_profile_snapshot_id": profile.get("input_profile_snapshot_id"),
        "input_profile_sha256": profile.get("input_profile_sha256"),
        "measured_at": profile.get("measured_at"),
    }


def _preview(path, path_sha256, goal, ready=None, ready_limits=None, real_preview=None,
             real_execution=None):
    flags = readiness.segment_flags(path, ready_limits) if ready_limits else {}
    cs = wc.current_surface()
    segments = []
    for segment in path["segments"]:
        points_m = [waypoint[:3] for waypoint in segment["waypoints"]]
        item = {
            "segment_id": segment["segment_id"],
            "stroke_id": segment.get("stroke_id"),
            "kind": segment["kind"],
            "points_m": points_m,
            "connect_to_next": False,
        }
        if segment["kind"] == "CUT":
            item["points_uv_mm"] = [
                [
                    round(wc.u_mm_from_theta_deg(math.degrees(math.atan2(
                        p[1] - cs.axis_origin_xy_m[1], p[0] - cs.axis_origin_xy_m[0]))), 6),
                    round((p[2] - cs.axis_origin_z_m) * 1000.0, 6),
                ]
                for p in points_m
            ]
        for key in ("split_from_stroke_id", "split_index", "split_count", "join_forbidden"):
            if key in segment:
                item[key] = segment[key]
        if segment["segment_id"] in flags:
            item.update(flags[segment["segment_id"]])
        segments.append(item)
    document = {
        "contract": "c2-path-preview/1",
        "schema_version": 2,
        "source_mode": goal["source_mode"],
        "test_only": path["test_only"],
        "render_only": True,
        "path_id": path["path_id"],
        "path_version": path["path_version"],
        "path_sha256": path_sha256,
        "asset_id": goal["asset_id"],
        "asset_sha256": goal["asset_sha256"],
        "profile_snapshot_id": goal["profile_snapshot_id"],
        "profile_sha256": goal["profile_sha256"],
        "frame_id": wc.FRAME_ID,
        "pose_reference": "tool_tip",
        "segments": segments,
    }
    if real_preview is not None:
        document["real_preview"] = dict(real_preview)
    if real_execution is not None:
        document["real_execution_allowed"] = path["real_execution_allowed"]
        document["real_execution"] = dict(real_execution)
    if ready is not None:
        # 미리보기 성공은 실행 가능 판정이 아니다. 잠정 로봇 작업 범위 점검 결과를 따로 싣는다.
        document["execution_readiness"] = readiness.preview_summary(ready)
    return document


class GeneratePipeline:
    def __init__(self, store, timeout_s=120.0, allow_real_preview=False,
                 allow_real_execution=False):
        self.store = store
        self.timeout_s = float(timeout_s)
        self.allow_real_preview = bool(allow_real_preview)
        self.allow_real_execution = bool(allow_real_execution)

    def run(
        self,
        raw_goal: Mapping,
        feedback: Callable[[str, float], None] | None = None,
        canceled: Callable[[], bool] | None = None,
    ) -> GenerationResult:
        # 요청이 정한 원통 형상은 이 요청 안에서만 쓴다(끝나면 기본 형상으로 되돌린다).
        token = wc.set_active_surface(wc.DEFAULT_SURFACE)
        try:
            return self._run(raw_goal, feedback, canceled)
        finally:
            wc.reset_active_surface(token)

    def _run(
        self,
        raw_goal: Mapping,
        feedback: Callable[[str, float], None] | None = None,
        canceled: Callable[[], bool] | None = None,
    ) -> GenerationResult:
        feedback = feedback or (lambda _stage, _progress: None)
        canceled = canceled or (lambda: False)
        started = time.monotonic()
        sent = [0.0]

        def checkpoint(stage, progress):
            if canceled():
                raise GenerationCanceled()
            if time.monotonic() - started > self.timeout_s:
                raise PipelineError("TIMEOUT", f"경로 생성 제한 시간 {self.timeout_s:g}초를 초과했습니다.")
            sent[0] = max(sent[0], float(progress))          # 진행률은 줄어들지 않는다
            feedback(stage, sent[0])

        def within_stage(stage, low, high):
            """단계 안의 0~1 진행률을 전체 진행률 구간 [low, high] 로 옮기는 함수. 취소·시간 초과도 여기서 확인한다."""
            return lambda fraction: checkpoint(stage, low + (high - low) * min(1.0, max(0.0, float(fraction))))

        def should_stop_refining():
            """2-opt 개선은 선택 사항이다. 제한 시간의 60%가 지나면 개선만 멈추고 지금 순서를 쓴다 (획은 그대로)."""
            return time.monotonic() - started > 0.6 * self.timeout_s

        goal = validate_goal(raw_goal, allow_real_preview=(self.allow_real_preview or self.allow_real_execution))
        try:
            asset = self.store.read(goal["asset_id"], goal["asset_sha256"], ("image",))
            if asset.mime not in ("image/png", "image/jpeg"):
                raise PipelineError("UNSUPPORTED_FORMAT", "PNG/JPEG 이미지만 지원합니다.")
            profile, _profile_artifact = self.store.read_json(
                goal["profile_snapshot_id"], goal["profile_sha256"], ("profile",)
            )
        except ArtifactError as exc:
            raise PipelineError(exc.code, str(exc)) from exc
        validate_profile(profile)
        check_goal_profile_mode(goal, profile)
        real_preview = _real_preview_marks(profile) if profile.get("contract") == PROFILE_CONTRACT_V3 else None
        real_execution = _real_execution_marks(profile) if profile.get("contract") == PROFILE_CONTRACT_V4 else None
        if real_execution is not None and not self.allow_real_execution:
            raise PipelineError("NOT_READY", "REAL 실행 경로 생성은 allow_real_execution이 필요합니다.")
        wc.set_active_surface(profile_surface(profile))

        checkpoint("CONVERTING", 0.05)
        hatch_raw = None
        hatch_bbox = None
        try:
            suffix = ".png" if asset.mime == "image/png" else ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix) as image_file:
                image_file.write(asset.data)
                image_file.flush()
                if goal["conversion_preset"] == "raster_parallel_hatch":
                    svg, hatch_raw, hatch_bbox, convert_stats = image_to_hatch.convert(
                        image_file.name,
                        goal["width_mm"],
                        goal["height_mm"],
                        source_name=asset.name,
                    )
                else:
                    svg, convert_stats = image_to_svg.convert(
                        image_file.name,
                        source_name=asset.name,
                    )
        except ValueError as exc:
            raise PipelineError("UNSUPPORTED_FORMAT", str(exc)) from exc
        conversion_config = {
            "preset": goal["conversion_preset"],
            "recipe_scope": "surface_path",
            "placement": {key: goal[key] for key in (
                "width_mm", "height_mm", "offset_u_mm", "offset_v_mm", "rotation_deg")},
        }
        if goal["conversion_preset"] == "raster_parallel_hatch":
            conversion_config.update({
                key: convert_stats[key] for key in (
                    "effective_groove_width_mm", "boundary_inset_mm", "spacing_mm",
                    "stepover_ratio", "minimum_hatch_fill_ratio",
                )
            })

        checkpoint("EXTRACTING_2D", 0.22)
        try:
            if hatch_raw is not None:
                strokes, extract_stats = extract_2d.transform_raw_strokes(
                    hatch_raw,
                    hatch_bbox,
                    goal["width_mm"],
                    goal["height_mm"],
                    goal["offset_u_mm"],
                    goal["offset_v_mm"],
                    goal["rotation_deg"],
                )
            else:
                strokes, extract_stats = extract_2d.extract(
                    svg,
                    goal["width_mm"],
                    goal["height_mm"],
                    goal["offset_u_mm"],
                    goal["offset_v_mm"],
                    goal["rotation_deg"],
                )
        except (ValueError, KeyError, IndexError) as exc:
            raise PipelineError("INVALID_INPUT", f"2D 좌표 추출 실패: {exc}") from exc
        if not strokes:
            raise PipelineError("VALIDATION_FAILED", "2D 좌표 획이 비어 있습니다.")

        checkpoint("OPTIMIZING_2D", 0.38)
        ordered, optimize_stats = optimize_2d.optimize(
            strokes, on_progress=within_stage("OPTIMIZING_2D", 0.38, 0.55), should_stop=should_stop_refining)

        checkpoint("MAPPING_3D", 0.55)
        mapped, mapping_failures, map_stats = map_3d.map_strokes(
            ordered, on_progress=within_stage("MAPPING_3D", 0.55, 0.64))
        if mapping_failures or not mapped:
            checkpoint("MAPPING_3D", 0.65)
            report = {
                "passed": False,
                "stage": "MAPPING_3D",
                "errors": mapping_failures or [{"reason_code": "EMPTY_PATH"}],
                "stats": map_stats,
                "not_checked": validate_path.NOT_CHECKED,
            }
            report_id, svg_id = new_id(), new_id()
            self.store.put_bundle([
                ArtifactWrite(json_bytes(report), "validation", "application/json",
                              "c2-path-validation-failed.json", {"executable": False}, report_id),
                ArtifactWrite(svg.encode("utf-8"), "svg", "image/svg+xml",
                              "c2-path-vector-diagnostic.svg", {"executable": False}, svg_id),
            ])
            raise PipelineError(
                "VALIDATION_FAILED",
                "3D 매핑에서 제외된 획이 있어 전체 생성을 실패 처리했습니다.",
                svg_asset_id=svg_id,
                validation_report_id=report_id,
            )

        checkpoint("BUILDING_PATH", 0.72)
        path_id = new_id()
        path_version = 1
        try:
            path, build_stats = generate_path.build(
                mapped,
                path_id,
                path_version,
                goal["asset_id"],
                goal["asset_sha256"],
                goal["profile_snapshot_id"],
                goal["profile_sha256"],
                goal["source_mode"],
                on_progress=within_stage("BUILDING_PATH", 0.72, 0.87),
                should_stop=should_stop_refining,
                real_preview=real_preview,
                real_execution=real_execution,
                conversion_config=conversion_config,
            )
        except ValueError as exc:
            raise PipelineError("VALIDATION_FAILED", str(exc)) from exc

        if real_execution is not None:
            motion_profiles = profile["execution_context"]["motion_profiles"]
            missing = sorted({segment.get("motion_profile_id") for segment in path["segments"]
                              if segment.get("motion_profile_id") not in motion_profiles})
            if missing:
                raise PipelineError(
                    "PROFILE_MISMATCH",
                    "생성 경로의 motion_profile_id가 실제 실행 설정에 없습니다: " + ", ".join(missing),
                )

        checkpoint("VALIDATING", 0.88)
        report = validate_path.validate(path)
        ready_limits = readiness.limits_from_profile(profile)
        ready = readiness.execution_readiness(path, ready_limits)
        if real_preview is not None:
            readiness.mark_preview_only(ready)      # 사전 점검 값은 그대로 두고 실행 금지만 따로 표시
        if real_execution is not None and ready["precheck"] != readiness.WITHIN:
            path["real_execution_allowed"] = False
            path["config"]["real_execution_allowed"] = False
            path["config"]["real_execution"]["real_execution_allowed"] = False
            real_execution["real_execution_allowed"] = False
        report["execution_readiness"] = ready
        cs = wc.current_surface()
        report.update({
            # 이 경로를 계산한 스냅샷과 실제로 쓴 원통 형상을 보고서에도 남긴다(경로 config 의 ID·해시와 같은 값).
            "profile_snapshot_id": goal["profile_snapshot_id"],
            "profile_sha256": goal["profile_sha256"],
            "profile_contract": profile.get("contract") or PROFILE_CONTRACT_V1,
            "source_mode": goal["source_mode"],
            "measurement_id": profile.get("measurement_id"),
            "measured_at": profile.get("measured_at"),
            "surface_used": {
                "radius_mm": round(cs.radius_m * 1000.0, 6),
                "height_mm": round(cs.height_m * 1000.0, 6),
                "axis_origin_m": list(cs.axis_origin_m),
                "height_reference": HEIGHT_REFERENCE_BOTTOM,
                "v_direction": V_DIRECTION_UP,
                "source": ("스냅샷 surface" if profile.get("contract") in (PROFILE_CONTRACT_V2, PROFILE_CONTRACT_V3, PROFILE_CONTRACT_V4)
                           else "c2_path 기본 상수(/1)"),
            },
            "request_id": goal["request_id"],
            "conversion": conversion_config,
            "path_id": path_id,
            "path_version": path_version,
            "input_stroke_count": len(strokes),
            "mapped_stroke_count": len(mapped),
            "mapping_failures": mapping_failures,
            "stats": {
                "convert": convert_stats,
                "extract_2d": extract_stats,
                "optimize_2d": optimize_stats,
                "map_3d": map_stats,
                "build": build_stats,
            },
        })
        if real_preview is not None:
            report["real_preview"] = dict(real_preview)
        if real_execution is not None:
            report["test_only"] = path["test_only"]
            report["real_execution_allowed"] = path["real_execution_allowed"]
            report["real_execution"] = dict(real_execution)
        if not report["passed"]:
            checkpoint("VALIDATING", 0.93)
            report_id, svg_id = new_id(), new_id()
            self.store.put_bundle([
                ArtifactWrite(json_bytes(report), "validation", "application/json",
                              "c2-path-validation-failed.json", {"executable": False}, report_id),
                ArtifactWrite(svg.encode("utf-8"), "svg", "image/svg+xml",
                              "c2-path-vector-diagnostic.svg", {"executable": False}, svg_id),
            ])
            raise PipelineError(
                "VALIDATION_FAILED",
                "생성 경로가 기하 안전 검증을 통과하지 못했습니다.",
                svg_asset_id=svg_id,
                validation_report_id=report_id,
            )

        checkpoint("VALIDATING", 0.96)

        validation_id = new_id()
        path_asset_id = new_id()
        svg_id = new_id()
        preview_id = new_id()
        path["validation"] = {
            "report_id": validation_id,
            "passed": True,
            "checks": report["checks"],
            "not_checked": report["not_checked"],
        }
        path_bytes = json_bytes(path)
        path_sha256 = sha256_bytes(path_bytes)
        preview = _preview(path, path_sha256, goal, ready, ready_limits, real_preview, real_execution)
        self.store.put_bundle([
            ArtifactWrite(json_bytes(report), "validation", "application/json",
                          "c2-path-validation.json", {"path_id": path_id}, validation_id),
            ArtifactWrite(path_bytes, "path", "application/json",
                          "c2-path.json", {"path_id": path_id, "path_version": path_version}, path_asset_id),
            ArtifactWrite(svg.encode("utf-8"), "svg", "image/svg+xml",
                          "c2-path-vector.svg", {"path_id": path_id}, svg_id),
            ArtifactWrite(json_bytes(preview), "preview", "application/json",
                          "c2-path-preview.json", {"path_id": path_id}, preview_id),
        ])
        # 이 시점에는 네 산출물이 한 DB transaction으로 모두 확정됐다. 이후 도착한
        # 취소를 성공 파일이 없는 것처럼 보고하지 않고 완료 feedback을 보낸다.
        feedback("VALIDATING", 1.0)
        return GenerationResult(
            path_id=path_id,
            path_version=path_version,
            path_sha256=path_sha256,
            path_asset_id=path_asset_id,
            svg_asset_id=svg_id,
            preview_asset_id=preview_id,
            validation_report_id=validation_id,
            segment_count=int(build_stats["segment_count"]),
            cut_length_m=float(build_stats["cut_length_m"]),
            execution_precheck=ready["precheck"],
            execution_message=readiness.message_suffix(ready),
        )
