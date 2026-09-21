"""설정 스냅샷의 기하 정보(`surface`)와 공정 쪽 `workcell` 입력 사이의 연결·일치 규칙.

배경: 경로 생성은 스냅샷의 ``surface`` (반지름 mm, 축 원점 m, 높이 mm) 를 쓰고,
``tool_calibration.measure_tool_tip/verify_tool_tip`` 은 ``workcell`` 사전
``{axis_xy_m, radius_m, top_z_m}`` 을 쓴다. 같은 원통을 다른 이름·단위로 적으면 어긋나므로,
**원본은 스냅샷의 `surface` 하나**로 두고 공정 입력은 이 모듈의 ``workcell_view`` 로 파생한다.
두 표현을 함께 저장한다면 ``check_workcell_view`` 로 일치를 검사한다.

  surface.axis_origin_m[0:2]                      == workcell.axis_xy_m          (m, 변환 없음)
  surface.radius_mm / 1000                        == workcell.radius_m           (mm → m)
  surface.axis_origin_m[2] + surface.height_mm/1e3 == workcell.top_z_m            (바닥 z + 높이 = 윗면 z)

``surface_geometry_errors`` 는 **실측값을 받는 새 프로필**에 필요한 기하 필드의 구조적 조건이다.
수치 상·하한(예: 반지름 허용 범위, 재장착 허용 이동량)은 여기서 정하지 않는다 — 담당자 확정 전이다
(BUNDLE_SPEC.md 의 "미정 항목"). ``pipeline.validate_profile`` 은 contract ``/1`` 스냅샷을 test_only 값과 정확히
비교하고(이 모듈을 부르지 않는다), ``/2`` 스냅샷에서만 ``surface_geometry_errors`` 로 구조를 검사하고, 그 ``surface`` 값(``workcell.surface_from_snapshot``)으로 경로를 계산한다.
"""
from __future__ import annotations

import math
from typing import Mapping

LENGTH_TOL_M = 1e-6          # 1 µm. 같은 값을 mm↔m 로 바꾼 부동소수 오차만 허용한다.
UNIT_AXIS_TOL = 1e-9


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _numbers(values, count) -> bool:
    return isinstance(values, (list, tuple)) and len(values) == count and all(_number(v) for v in values)


def workcell_view(profile: Mapping) -> dict:
    """스냅샷 surface → tool_calibration 의 workcell 입력 ({axis_xy_m, radius_m, top_z_m}).

    surface 가 구조적으로 올바르지 않으면 ValueError (먼저 surface_geometry_errors 로 검사할 것).
    """
    surface = profile.get("surface") if isinstance(profile, Mapping) else None
    errors = surface_geometry_errors(surface)
    if errors:
        raise ValueError("surface가 올바르지 않습니다: " + "; ".join(errors[:3]))
    x, y, z = surface["axis_origin_m"]
    return {
        "axis_xy_m": [float(x), float(y)],
        "radius_m": float(surface["radius_mm"]) / 1000.0,
        "top_z_m": float(z) + float(surface["height_mm"]) / 1000.0,
    }


def check_workcell_view(profile: Mapping, workcell: Mapping, tol_m: float = LENGTH_TOL_M) -> list[str]:
    """스냅샷 surface 와 별도로 저장된 workcell 값이 같은지 검사한다 (빈 목록 = 일치).

    흔한 실수: radius 를 mm 로 넣었는데 이름이 radius_m 인 경우(34.25 대 0.03425)를 잡는다.
    """
    try:
        expected = workcell_view(profile)
    except ValueError as exc:
        return [str(exc)]
    errors = []
    if not isinstance(workcell, Mapping):
        return ["workcell은 객체여야 합니다."]
    xy = workcell.get("axis_xy_m")
    if not _numbers(xy, 2):
        errors.append("workcell.axis_xy_m은 유한한 수 2개(m)여야 합니다.")
    else:
        for name, got, want in zip(("x", "y"), xy, expected["axis_xy_m"]):
            if abs(got - want) > tol_m:
                errors.append(f"axis_xy_m.{name}: workcell {got!r} != surface {want!r} (m)")
    for key in ("radius_m", "top_z_m"):
        got = workcell.get(key)
        if not _number(got):
            errors.append(f"workcell.{key}는 유한한 수(m)여야 합니다.")
        elif abs(got - expected[key]) > tol_m:
            errors.append(f"{key}: workcell {got!r} != surface에서 계산한 {expected[key]!r} (m)")
    return errors


def surface_geometry_errors(surface) -> list[str]:
    """실측 프로필 surface 의 구조적 조건. 수치 상·하한은 검사하지 않는다(미정)."""
    if not isinstance(surface, Mapping):
        return ["surface는 객체여야 합니다."]
    errors = []
    if surface.get("kind") != "cylinder":
        errors.append("surface.kind는 'cylinder'여야 합니다.")
    for key in ("radius_mm", "height_mm"):
        if not _number(surface.get(key)) or surface[key] <= 0:
            errors.append(f"surface.{key}는 0보다 큰 유한한 수(mm)여야 합니다.")
    if not _numbers(surface.get("axis_origin_m"), 3):
        errors.append("surface.axis_origin_m은 유한한 수 3개 [x, y, 바닥 z] (m)여야 합니다.")
    direction = surface.get("axis_direction")
    if not _numbers(direction, 3) or any(abs(a - b) > UNIT_AXIS_TOL for a, b in zip(direction, (0.0, 0.0, 1.0))):
        errors.append("surface.axis_direction은 [0, 0, 1]이어야 합니다 (경로 계산·미리보기가 +Z 축만 지원).")

    height = surface.get("height_mm")
    v_range = surface.get("valid_v_range_mm")
    if not _numbers(v_range, 2):
        errors.append("surface.valid_v_range_mm은 유한한 수 2개 [하한, 상한] (mm, 바닥 기준)여야 합니다.")
    elif not 0.0 <= v_range[0] < v_range[1] or (_number(height) and v_range[1] > height):
        errors.append("surface.valid_v_range_mm은 0 <= 하한 < 상한 <= height_mm 여야 합니다.")

    origin = surface.get("u_origin_angle_deg")
    if not _number(origin) or not -180.0 <= origin <= 180.0:
        errors.append("surface.u_origin_angle_deg는 -180~180 (도)여야 합니다.")
    seam = surface.get("seam_angle_deg")
    if not _number(seam) or not -180.0 < seam <= 180.0:
        errors.append("surface.seam_angle_deg는 -180 초과 180 이하 (도)여야 합니다.")
    reach = surface.get("reachable_angle_deg")
    if not _numbers(reach, 2):
        errors.append("surface.reachable_angle_deg는 유한한 수 2개 [하한, 상한] (도)여야 합니다.")
    elif not -180.0 <= reach[0] < reach[1] <= 180.0:
        errors.append("surface.reachable_angle_deg는 -180 <= 하한 < 상한 <= 180 여야 합니다.")
    elif _number(seam):
        for k in range(-2, 3):
            if reach[0] < seam + 360.0 * k < reach[1]:
                errors.append("surface.reachable_angle_deg 안에 이음매가 있습니다 (획이 이음매를 넘지 못하는 조건과 모순).")
                break
    return errors
