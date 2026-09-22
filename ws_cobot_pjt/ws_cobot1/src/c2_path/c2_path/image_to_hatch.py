#!/usr/bin/env python3
"""라스터 이미지를 중심선과 단방향 평행선 해칭의 혼합 획으로 변환한다.

연결 성분마다 물리 폭을 판정해 공구 폭 이상인 면은 일정 간격의 수평선으로
채우고, 그보다 좁은 선은 골격 중심선을 유지한다. 골격이 한 점으로 축소되는
작은 면은 성분 내부의 중심 1패스로 보완한다. 실제 mm 좌표 변환은
extract_2d.transform_raw_strokes가 한다.

홈 폭·경계 보정·해칭 간격은 SIMULATION/test_only 경로 생성의 고정 레시피다.
HMI 입력으로 받지 않으며 값이 바뀌면 경로·설정 해시와 시험을 새로 생성한다.
"""
from __future__ import annotations

import math
import os

import cv2
import numpy as np

from skimage.morphology import skeletonize

from .image_to_svg import binarize, trace_strokes


# 2026-09-22 SIMULATION/test_only 표면 경로 레시피: 홈 폭 0.8mm, 경계 안쪽 보정 0.4mm,
# 해칭 간격 0.25mm. 가공 깊이 0.8mm는 c2_path가 아닌 실행 프로파일의
# fixed_depth.depth_m에서 적용한다. 이 값들은 REAL 실행 승인값이나 드릴 팁 직경 자체를 뜻하지 않는다.
EFFECTIVE_GROOVE_WIDTH_MM = 0.8
HATCH_SPACING_MM = 0.25
HATCH_STEPOVER_RATIO = HATCH_SPACING_MM / EFFECTIVE_GROOVE_WIDTH_MM
BOUNDARY_INSET_MM = 0.4
MIN_HATCH_LENGTH_MM = 1.0
MAX_HATCH_STROKES = 1000
MIN_FALLBACK_LENGTH_MM = 0.3
MIN_CROSS_HATCH_LINES_PER_DIRECTION = 2
# 넓은 도안 bbox 안에 선이 드문드문 있는 경우(선화)는 일부 굵은 교차점의 최대 폭만으로
# 면 채움으로 바꾸지 않는다. 이 값은 SIMULATION/test_only 분류 기준이다.
MIN_HATCH_FILL_RATIO = 0.20


class NoHatchStrokes(ValueError):
    """성분은 존재하지만 안전한 수평 해칭 획을 만들 수 없음."""


def _foreground_bbox(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("조각할 검은 영역을 찾지 못했습니다.")
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def _fit_scale_mm_per_px(source_bbox, width_mm, height_mm):
    x0, y0, x1, y1 = source_bbox
    src_w = max(x1 - x0, 1.0)
    src_h = max(y1 - y0, 1.0)
    return min(float(width_mm) / src_w, float(height_mm) / src_h)


def _safe_mask(mask, inset_px):
    """전경 경계에서 inset_px 이상 떨어진 픽셀만 남긴다."""
    if inset_px <= 0:
        return mask.copy()
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    return distance + 1e-9 >= float(inset_px)


def _runs(row):
    """True가 연속된 [시작, 끝] 구간을 반환한다."""
    padded = np.pad(row.astype(np.int8), (1, 1))
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1) - 1
    return list(zip(starts.tolist(), ends.tolist()))


def generate_scanlines(mask, source_bbox, scale_mm_per_px, *,
                       spacing_mm=HATCH_SPACING_MM,
                       boundary_inset_mm=BOUNDARY_INSET_MM,
                       min_length_mm=MIN_HATCH_LENGTH_MM,
                       max_strokes=MAX_HATCH_STROKES):
    """마스크 내부의 왼쪽→오른쪽 해칭 획을 픽셀 좌표로 만든다."""
    if not math.isfinite(spacing_mm) or spacing_mm <= 0:
        raise ValueError("해칭 간격은 0보다 큰 유한한 mm 값이어야 합니다.")
    if not math.isfinite(boundary_inset_mm) or boundary_inset_mm < 0:
        raise ValueError("경계 안쪽 보정 거리는 0 이상의 유한한 mm 값이어야 합니다.")
    spacing_px = spacing_mm / scale_mm_per_px
    inset_px = boundary_inset_mm / scale_mm_per_px
    min_length_px = min_length_mm / scale_mm_per_px
    if spacing_px < 1.0:
        raise ValueError("입력 이미지 해상도가 낮아 고정 해칭 간격을 표현할 수 없습니다.")

    safe = _safe_mask(mask, inset_px)
    x0, y0, x1, y1 = source_bbox
    first_y = y0 + inset_px
    last_y = y1 - inset_px
    if first_y > last_y:
        raise NoHatchStrokes("공구 반경을 보정한 뒤 조각할 영역이 남지 않습니다.")

    strokes = []
    removed_short = 0
    used_rows = set()
    y = first_y
    while y <= last_y + 1e-9:
        row_y = min(mask.shape[0] - 1, max(0, int(round(y))))
        if row_y not in used_rows:
            used_rows.add(row_y)
            for start_x, end_x in _runs(safe[row_y]):
                if end_x - start_x < min_length_px:
                    removed_short += 1
                    continue
                # 이미지 좌표에서 항상 왼쪽→오른쪽. 이후 회전해도 점열 순서는 보존된다.
                strokes.append([(float(start_x), float(row_y)),
                                (float(end_x), float(row_y))])
                if len(strokes) > max_strokes:
                    raise ValueError(
                        f"해칭 획이 안전 제한({max_strokes}개)을 초과했습니다. "
                        "도안 크기 또는 고정 간격을 다시 검토해야 합니다."
                    )
        y += spacing_px

    if not strokes:
        raise NoHatchStrokes("고정 간격과 경계 보정 조건에서 생성 가능한 해칭 획이 없습니다.")
    return strokes, {
        "spacing_mm": round(spacing_mm, 6),
        "spacing_px": round(spacing_px, 6),
        "effective_groove_width_mm": round(EFFECTIVE_GROOVE_WIDTH_MM, 6),
        "stepover_ratio": round(HATCH_STEPOVER_RATIO, 6),
        "boundary_inset_mm": round(boundary_inset_mm, 6),
        "minimum_stroke_length_mm": round(min_length_mm, 6),
        "removed_short_strokes": removed_short,
        "direction": "image_left_to_right",
        "recipe_scope": "simulation_test_only",
        "fixed_test_only": True,
    }


def generate_vertical_scanlines(mask, source_bbox, scale_mm_per_px, **kwargs):
    """같은 안전 조건으로 아래쪽 방향 세로 해칭을 생성한다."""
    x0, y0, x1, y1 = source_bbox
    transposed_bbox = (y0, x0, y1, x1)
    strokes, stats = generate_scanlines(mask.T, transposed_bbox, scale_mm_per_px, **kwargs)
    vertical = [[(float(y), float(x)) for x, y in stroke] for stroke in strokes]
    stats = {**stats, "direction": "image_top_to_bottom"}
    return vertical, stats


def _component_centerlines(component_mask):
    """가는 연결 성분을 골격 중심선 픽셀 획으로 변환한다."""
    raw = trace_strokes(skeletonize(component_mask), spur_min_len_px=0.0)
    return [points for points, _closed in raw if len(points) >= 2]


def _run_through_peak(component_mask, scale_mm_per_px):
    """골격이 사라진 작은 성분에 대해 내부 중심 1패스를 만든다.

    거리 변환 최대점에서 성분의 긴 bbox 축 방향 run을 선택한다. 픽셀 한 개를
    실제 공구 폭처럼 확대하지 않으며, 2점 사이가 waypoint 최소 간격보다 짧으면
    호출자가 안전하게 생략한다.
    """
    ys, xs = np.nonzero(component_mask)
    if not len(xs):
        return None
    distance = cv2.distanceTransform(component_mask.astype(np.uint8), cv2.DIST_L2, 5)
    peak_y, peak_x = np.unravel_index(int(np.argmax(distance)), distance.shape)
    use_horizontal = (xs.max() - xs.min()) >= (ys.max() - ys.min())
    if use_horizontal:
        runs = _runs(component_mask[peak_y])
        run = next(((a, b) for a, b in runs if a <= peak_x <= b), None)
        if run is None:
            return None
        a, b = (float(run[0]), float(peak_y)), (float(run[1]), float(peak_y))
    else:
        runs = _runs(component_mask[:, peak_x])
        run = next(((a, b) for a, b in runs if a <= peak_y <= b), None)
        if run is None:
            return None
        a, b = (float(peak_x), float(run[0])), (float(peak_x), float(run[1]))
    if math.dist(a, b) * scale_mm_per_px < MIN_FALLBACK_LENGTH_MM:
        return None
    return [a, b]


def generate_mixed_strokes(mask, source_bbox, scale_mm_per_px,
                           max_strokes=MAX_HATCH_STROKES):
    """연결 성분별로 해칭·중심선·작은 면 1패스를 선택한다."""
    count, labels, component_stats, _centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8)
    strokes = []
    horizontal_hatch_strokes = []
    vertical_hatch_strokes = []
    mode_counts = {"parallel_hatch": 0, "cross_hatch": 0, "centerline": 0, "minimum_one_pass": 0,
                   "omitted_too_small": 0}
    component_details = []
    removed_short = 0

    for label in range(1, count):
        x, y, width, height, area = component_stats[label].tolist()
        component = labels == label
        distance = cv2.distanceTransform(component.astype(np.uint8), cv2.DIST_L2, 5)
        physical_width_mm = float(distance.max()) * 2.0 * scale_mm_per_px
        component_bbox = (float(x), float(y), float(x + width - 1), float(y + height - 1))
        fill_ratio = float(area) / max(1, width * height)
        selected = []
        mode = ""

        if (physical_width_mm + 1e-9 >= EFFECTIVE_GROOVE_WIDTH_MM
                and fill_ratio >= MIN_HATCH_FILL_RATIO):
            try:
                horizontal, hatch_stats = generate_scanlines(
                    component, component_bbox, scale_mm_per_px,
                    max_strokes=max_strokes - len(strokes))
                removed_short += hatch_stats["removed_short_strokes"]
                try:
                    vertical, vertical_stats = generate_vertical_scanlines(
                        component, component_bbox, scale_mm_per_px,
                        max_strokes=max_strokes - len(strokes) - len(horizontal))
                    removed_short += vertical_stats["removed_short_strokes"]
                except NoHatchStrokes:
                    vertical = []
                if (len(horizontal) >= MIN_CROSS_HATCH_LINES_PER_DIRECTION
                        and len(vertical) >= MIN_CROSS_HATCH_LINES_PER_DIRECTION):
                    selected = horizontal + vertical
                    horizontal_hatch_strokes.extend(horizontal)
                    vertical_hatch_strokes.extend(vertical)
                    mode = "cross_hatch"
                else:
                    selected = horizontal
                    horizontal_hatch_strokes.extend(horizontal)
                    mode = "parallel_hatch"
            except NoHatchStrokes:
                # 방향·형상 때문에 수평 해칭이 하나도 나오지 않으면 중심선으로
                # 안전하게 후퇴한다. 성분 자체를 확대하거나 경계를 넘지 않는다.
                selected = []

        if not selected:
            selected = _component_centerlines(component)
            mode = "centerline" if selected else ""
        if not selected:
            fallback = _run_through_peak(component, scale_mm_per_px)
            if fallback is not None:
                selected = [fallback]
                mode = "minimum_one_pass"
        if not selected:
            mode = "omitted_too_small"

        if len(strokes) + len(selected) > max_strokes:
            raise ValueError(
                f"혼합 획이 안전 제한({max_strokes}개)을 초과했습니다. "
                "도안 크기 또는 고정 간격을 다시 검토해야 합니다."
            )
        strokes.extend(selected)
        mode_counts[mode] += 1
        component_details.append({
            "component": label,
            "area_px": int(area),
            "bbox_px": list(component_bbox),
            "estimated_width_mm": round(physical_width_mm, 6),
            "fill_ratio": round(fill_ratio, 6),
            "mode": mode,
            "stroke_count": len(selected),
        })

    if not strokes:
        raise ValueError("공구 폭과 최소 길이 조건에서 생성 가능한 획이 없습니다.")
    omitted = mode_counts["omitted_too_small"]
    warnings = ([] if omitted == 0 else [
        f"공구·해상도 기준 최소 길이보다 작은 연결 성분 {omitted}개를 확대하지 않고 생략했습니다."
    ])
    return strokes, horizontal_hatch_strokes, vertical_hatch_strokes, {
        "component_count": count - 1,
        "component_modes": mode_counts,
        "components": component_details,
        "removed_short_strokes": removed_short,
        "cross_hatch_min_lines_per_direction": MIN_CROSS_HATCH_LINES_PER_DIRECTION,
        "warnings": warnings,
    }


def strokes_to_svg(strokes, width_px, height_px, source_name):
    body = "\n  ".join(
        '<path fill="none" stroke="#000" stroke-width="1" d="M '
        + " L ".join(f"{point[0]:.3f},{point[1]:.3f}" for point in stroke)
        + '" />'
        for stroke in strokes
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!-- image_to_hatch.py 자동 생성: {source_name}; '
        f'SIMULATION/test_only 표면 경로 레시피; 고정 간격 {HATCH_SPACING_MM:.3f}mm -->\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {width_px} {height_px}">\n  {body}\n</svg>\n'
    )


def validate_hatch(strokes, safe_mask, *, direction):
    """생성된 끝점의 방향·마스크 포함 관계를 검사한다."""
    errors = []
    for index, stroke in enumerate(strokes):
        if len(stroke) != 2:
            errors.append(f"stroke {index}: 점 수 조건 위반")
            continue
        if direction == "horizontal":
            direction_ok = stroke[0][0] <= stroke[-1][0] and abs(stroke[0][1] - stroke[-1][1]) <= 1e-9
        elif direction == "vertical":
            direction_ok = stroke[0][1] <= stroke[-1][1] and abs(stroke[0][0] - stroke[-1][0]) <= 1e-9
        else:
            raise ValueError(f"알 수 없는 해칭 방향: {direction}")
        if not direction_ok:
            errors.append(f"stroke {index}: {direction} 방향 조건 위반")
            continue
        for x, y in stroke:
            ix, iy = int(round(x)), int(round(y))
            if not (0 <= iy < safe_mask.shape[0] and 0 <= ix < safe_mask.shape[1] and safe_mask[iy, ix]):
                errors.append(f"stroke {index}: 경계 보정 영역 밖 끝점")
                break
    if errors:
        raise ValueError("해칭 검증 실패: " + "; ".join(errors[:4]))


def validate_inside_foreground(strokes, mask):
    """혼합 획의 모든 선분이 원래 검은 성분 내부에 있는지 검사한다."""
    errors = []
    for index, stroke in enumerate(strokes):
        if len(stroke) < 2:
            errors.append(f"stroke {index}: 점이 2개 미만")
            continue
        for a, b in zip(stroke[:-1], stroke[1:]):
            samples = max(1, int(math.ceil(math.dist(a, b) * 2.0)))
            for step in range(samples + 1):
                t = step / samples
                x = int(round(a[0] + (b[0] - a[0]) * t))
                y = int(round(a[1] + (b[1] - a[1]) * t))
                if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]):
                    errors.append(f"stroke {index}: 원본 전경 밖 선분")
                    break
            if errors and errors[-1].startswith(f"stroke {index}:"):
                break
    if errors:
        raise ValueError("혼합 획 검증 실패: " + "; ".join(errors[:4]))


def convert(image_path, width_mm, height_mm, *, invert=None,
            max_pixels=16_000_000, max_side_px=6000, source_name=None):
    """이미지 파일을 고정 간격 단방향 해칭 SVG와 픽셀 획으로 변환한다."""
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")
    h, w = gray.shape
    if h * w > max_pixels or max(h, w) > max_side_px:
        raise ValueError("이미지는 16MP 이하이고 한 변이 6000px 이하여야 합니다.")
    source_name = source_name or os.path.basename(image_path)
    # 중심선 변환의 자동 반전(전경이 화면 절반보다 넓으면 반전)은 채워진 면에서
    # 정상 검은 영역을 배경으로 오인할 수 있다. 해칭 preset의 기본 계약은
    # 흰 배경/검은 가공 영역이며, 반전 이미지는 호출자가 invert=True로 명시한다.
    mask = binarize(gray, invert=False if invert is None else invert)
    bbox = _foreground_bbox(mask)
    scale = _fit_scale_mm_per_px(bbox, width_mm, height_mm)
    strokes, horizontal_hatches, vertical_hatches, mixed_stats = generate_mixed_strokes(mask, bbox, scale)
    safe = _safe_mask(mask, BOUNDARY_INSET_MM / scale)
    validate_hatch(horizontal_hatches, safe, direction="horizontal")
    validate_hatch(vertical_hatches, safe, direction="vertical")
    validate_inside_foreground(strokes, mask)
    svg = strokes_to_svg(strokes, w, h, source_name)
    stats = {
        "mode": "centerline_parallel_hatch_mixed",
        "source_image": source_name,
        "image_size_px": [w, h],
        "foreground_pixels": int(np.count_nonzero(mask)),
        "source_bbox_px": list(bbox),
        "scale_mm_per_px": round(scale, 9),
        "stroke_count": len(strokes),
        "spacing_mm": round(HATCH_SPACING_MM, 6),
        "effective_groove_width_mm": round(EFFECTIVE_GROOVE_WIDTH_MM, 6),
        "stepover_ratio": round(HATCH_STEPOVER_RATIO, 6),
        "boundary_inset_mm": round(BOUNDARY_INSET_MM, 6),
        "minimum_stroke_length_mm": round(MIN_HATCH_LENGTH_MM, 6),
        "minimum_fallback_length_mm": round(MIN_FALLBACK_LENGTH_MM, 6),
        "minimum_hatch_fill_ratio": MIN_HATCH_FILL_RATIO,
        "direction": "hatch_image_left_to_right",
        "cross_hatch_enabled": True,
        "recipe_scope": "simulation_test_only",
        "horizontal_hatch_stroke_count": len(horizontal_hatches),
        "vertical_hatch_stroke_count": len(vertical_hatches),
        "fixed_test_only": True,
        **mixed_stats,
    }
    return svg, strokes, bbox, stats
