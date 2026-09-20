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
from typing import Callable, Mapping
from uuid import UUID

from . import extract_2d, generate_path, image_to_svg, map_3d, optimize_2d, validate_path
from . import workcell as wc
from .artifacts import ArtifactError, ArtifactWrite, json_bytes, new_id, sha256_bytes


SUPPORTED_PRESETS = {"raster_centerline_bezier"}
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
        raise PipelineError("UNSUPPORTED_FORMAT", "지원 preset: raster_centerline_bezier")
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
    if isinstance(expected, float):
        try:
            okay = math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=tol)
        except (TypeError, ValueError):
            okay = False
    else:
        okay = actual == expected
    if not okay:
        errors.append(f"{label}: {actual!r} != {expected!r}")


def validate_profile(profile: Mapping) -> None:
    """하드코딩된 test_only workcell 값과 스냅샷이 정확히 같은지 확인한다."""
    surface = profile.get("surface") if isinstance(profile, Mapping) else None
    surface = surface if isinstance(surface, Mapping) else {}
    errors = []
    _same(profile.get("schema_version"), 2, "schema_version", errors)
    _same(profile.get("source_mode"), "SIMULATION", "source_mode", errors)
    _same(profile.get("frame_id"), wc.FRAME_ID, "frame_id", errors)
    _same(profile.get("workcell_id"), wc.WORKCELL_ID, "workcell_id", errors)
    _same(profile.get("workcell_version"), wc.WORKCELL_VERSION, "workcell_version", errors)
    _same(profile.get("tool_id"), wc.TOOL_ID, "tool_id", errors)
    _same(profile.get("tool_version"), wc.TOOL_VERSION, "tool_version", errors)
    _same(profile.get("tcp_id"), wc.TCP_PROFILE_ID, "tcp_id", errors)
    _same(profile.get("tcp_version"), wc.TCP_PROFILE_VERSION, "tcp_version", errors)
    _same(profile.get("load_id"), wc.LOAD_PROFILE_ID, "load_id", errors)
    _same(profile.get("load_version"), wc.LOAD_PROFILE_VERSION, "load_version", errors)
    _same(profile.get("gripper_open_allowed"), False, "gripper_open_allowed", errors)
    _same(surface.get("kind"), "cylinder", "surface.kind", errors)
    _same(surface.get("radius_mm"), wc.RADIUS_M * 1000.0, "surface.radius_mm", errors, 1e-6)
    _same(surface.get("height_mm"), wc.HEIGHT_TOTAL_M * 1000.0, "surface.height_mm", errors, 1e-6)
    _same(surface.get("axis_origin_m"), [wc.AXIS_ORIGIN_XY_M[0], wc.AXIS_ORIGIN_XY_M[1],
                                          wc.AXIS_ORIGIN_Z_M], "surface.axis_origin_m", errors)
    _same(surface.get("axis_direction"), list(wc.AXIS_DIRECTION), "surface.axis_direction", errors)
    _same(surface.get("valid_v_range_mm"), [v * 1000.0 for v in wc.WORKABLE_HEIGHT_RANGE_M],
          "surface.valid_v_range_mm", errors)
    _same(surface.get("u_origin_angle_deg"), wc.U_ORIGIN_ANGLE_DEG,
          "surface.u_origin_angle_deg", errors)
    _same(surface.get("seam_angle_deg"), wc.SEAM_ANGLE_DEG, "surface.seam_angle_deg", errors)
    _same(surface.get("reachable_angle_deg"), list(wc.REACHABLE_ANGLE_DEG),
          "surface.reachable_angle_deg", errors)
    if errors:
        raise PipelineError("PROFILE_MISMATCH", "설정 스냅샷과 c2_path test_only 값이 다릅니다: " + "; ".join(errors[:4]))


def matching_test_profile() -> dict:
    """통합 시험에서 서버가 등록할 수 있는 명시적 test_only 스냅샷."""
    return {
        "contract": "c2-path-test-profile/1",
        "schema_version": 2,
        "source_mode": "SIMULATION",
        "workcell_id": wc.WORKCELL_ID,
        "workcell_version": wc.WORKCELL_VERSION,
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


def _preview(path, path_sha256, goal):
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
                        p[1] - wc.AXIS_ORIGIN_XY_M[1], p[0] - wc.AXIS_ORIGIN_XY_M[0]))), 6),
                    round((p[2] - wc.AXIS_ORIGIN_Z_M) * 1000.0, 6),
                ]
                for p in points_m
            ]
        for key in ("split_from_stroke_id", "split_index", "split_count", "join_forbidden"):
            if key in segment:
                item[key] = segment[key]
        segments.append(item)
    return {
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
        feedback = feedback or (lambda _stage, _progress: None)
        canceled = canceled or (lambda: False)
        started = time.monotonic()

        def checkpoint(stage, progress):
            if canceled():
                raise GenerationCanceled()
            if time.monotonic() - started > self.timeout_s:
                raise PipelineError("TIMEOUT", f"경로 생성 제한 시간 {self.timeout_s:g}초를 초과했습니다.")
            feedback(stage, progress)

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

        checkpoint("CONVERTING", 0.05)
        try:
            suffix = ".png" if asset.mime == "image/png" else ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix) as image_file:
                image_file.write(asset.data)
                image_file.flush()
                svg, convert_stats = image_to_svg.convert(
                    image_file.name,
                    source_name=asset.name,
                )
        except ValueError as exc:
            raise PipelineError("UNSUPPORTED_FORMAT", str(exc)) from exc

        checkpoint("EXTRACTING_2D", 0.22)
        try:
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
        ordered, optimize_stats = optimize_2d.optimize(strokes)

        checkpoint("MAPPING_3D", 0.55)
        mapped, mapping_failures, map_stats = map_3d.map_strokes(ordered)
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
                              "c2-path-centerline-diagnostic.svg", {"executable": False}, svg_id),
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
            )
        except ValueError as exc:
            raise PipelineError("VALIDATION_FAILED", str(exc)) from exc

        checkpoint("VALIDATING", 0.88)
        report = validate_path.validate(path)
        report.update({
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
                              "c2-path-centerline-diagnostic.svg", {"executable": False}, svg_id),
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
        preview = _preview(path, path_sha256, goal)
        self.store.put_bundle([
            ArtifactWrite(json_bytes(report), "validation", "application/json",
                          "c2-path-validation.json", {"path_id": path_id}, validation_id),
            ArtifactWrite(path_bytes, "path", "application/json",
                          "c2-path.json", {"path_id": path_id, "path_version": path_version}, path_asset_id),
            ArtifactWrite(svg.encode("utf-8"), "svg", "image/svg+xml",
                          "c2-path-centerline.svg", {"path_id": path_id}, svg_id),
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
        )
