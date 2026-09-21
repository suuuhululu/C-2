"""ROS와 독립적인 GeneratePath 상위 파이프라인.

계산 단계의 유일한 조합 지점이며, 일부 획 실패·빈 경로·검증 실패를 성공
산출물로 공개하지 않는다. 현재 workcell.py 값은 test_only이므로 SIMULATION만
허용한다.
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


def validate_goal(goal: Mapping) -> dict:
    value = dict(goal)
    if value.get("schema_version") != wc.PATH_SCHEMA_VERSION:
        raise PipelineError("UNSUPPORTED_SCHEMA_VERSION", "고정 드릴 schema_version=2만 지원합니다.")
    value["request_id"] = _uuid(value.get("request_id"), "request_id")
    value["asset_id"] = _uuid(value.get("asset_id"), "asset_id")
    value["profile_snapshot_id"] = _uuid(value.get("profile_snapshot_id"), "profile_snapshot_id")
    value["asset_sha256"] = _sha(value.get("asset_sha256"), "asset_sha256")
    value["profile_sha256"] = _sha(value.get("profile_sha256"), "profile_sha256")
    if value.get("source_mode") != "SIMULATION":
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
HEIGHT_REFERENCE_BOTTOM = "bottom"       # v=0 은 양초 바닥(축 원점 z). 윗면 기준이 아니다.
V_DIRECTION_UP = "up"                    # v 는 바닥에서 위로 갈수록 커진다.
MEASUREMENT_ID_MAX_LEN = 128


def _identity_errors(profile: Mapping, errors: list) -> None:
    """/1·/2 공통: 작업 셀·도구·프레임 식별. 실측으로 바뀌는 값이 아니라 c2_path 가 아는 설정과 같아야 한다."""
    _same(profile.get("schema_version"), 2, "schema_version", errors)
    _same(profile.get("source_mode"), "SIMULATION", "source_mode", errors)
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
    if isinstance(profile, Mapping) and profile.get("contract") == PROFILE_CONTRACT_V2:
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
    else:
        raise PipelineError(
            "PROFILE_MISMATCH",
            f"지원하지 않는 스냅샷 contract입니다: {contract!r} (지원: {PROFILE_CONTRACT_V1}, {PROFILE_CONTRACT_V2})")


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


def _preview(path, path_sha256, goal, ready=None, ready_limits=None):
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
        "source_mode": "SIMULATION",
        "test_only": True,
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
    if ready is not None:
        # 미리보기 성공은 실행 가능 판정이 아니다. 잠정 로봇 작업 범위 점검 결과를 따로 싣는다.
        document["execution_readiness"] = readiness.preview_summary(ready)
    return document


class GeneratePipeline:
    def __init__(self, store, timeout_s=120.0):
        self.store = store
        self.timeout_s = float(timeout_s)

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

        goal = validate_goal(raw_goal)
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
            )
        except ValueError as exc:
            raise PipelineError("VALIDATION_FAILED", str(exc)) from exc

        checkpoint("VALIDATING", 0.88)
        report = validate_path.validate(path)
        ready_limits = readiness.limits_from_profile(profile)
        ready = readiness.execution_readiness(path, ready_limits)
        report["execution_readiness"] = ready
        cs = wc.current_surface()
        report.update({
            # 이 경로를 계산한 스냅샷과 실제로 쓴 원통 형상을 보고서에도 남긴다(경로 config 의 ID·해시와 같은 값).
            "profile_snapshot_id": goal["profile_snapshot_id"],
            "profile_sha256": goal["profile_sha256"],
            "profile_contract": profile.get("contract") or PROFILE_CONTRACT_V1,
            "measurement_id": profile.get("measurement_id"),
            "measured_at": profile.get("measured_at"),
            "surface_used": {
                "radius_mm": round(cs.radius_m * 1000.0, 6),
                "height_mm": round(cs.height_m * 1000.0, 6),
                "axis_origin_m": list(cs.axis_origin_m),
                "height_reference": HEIGHT_REFERENCE_BOTTOM,
                "v_direction": V_DIRECTION_UP,
                "source": "스냅샷 surface" if profile.get("contract") == PROFILE_CONTRACT_V2 else "c2_path 기본 상수(/1)",
            },
            "request_id": goal["request_id"],
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
        preview = _preview(path, path_sha256, goal, ready, ready_limits)
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
