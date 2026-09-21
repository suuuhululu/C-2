#!/usr/bin/env python3
"""채워진 라스터 영역을 단방향 평행선 해칭 획으로 변환한다.

이 모듈은 중심선 변환(image_to_svg.py)과 목적이 다르다. 검은 영역을
일정 간격의 수평선으로 채우며, 모든 CUT 획은 이미지 좌표에서 왼쪽→오른쪽
방향을 유지한다. 실제 mm 좌표 변환은 extract_2d.transform_raw_strokes가 한다.

현재 홈 폭·간격은 실기 승인값이 없는 SIMULATION/test_only 고정값이다.
HMI 입력으로 받지 않으며 실측 홈 폭이 확정되면 코드·근거·시험을 함께 갱신한다.
"""
from __future__ import annotations

import math
import os

import cv2
import numpy as np

from .image_to_svg import binarize


# 2026-09-21 설계 결정: 초기 시험은 홈 폭의 50% 간격. 아래 1.6mm는
# 실측값이 아니라 시뮬레이션용 고정 가정이며 REAL 승인값으로 사용하지 않는다.
EFFECTIVE_GROOVE_WIDTH_MM = 1.6
HATCH_STEPOVER_RATIO = 0.5
HATCH_SPACING_MM = EFFECTIVE_GROOVE_WIDTH_MM * HATCH_STEPOVER_RATIO
BOUNDARY_INSET_MM = EFFECTIVE_GROOVE_WIDTH_MM / 2.0
MIN_HATCH_LENGTH_MM = 1.0
MAX_HATCH_STROKES = 1000


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
        raise ValueError("공구 반경을 보정한 뒤 조각할 영역이 남지 않습니다.")

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
        raise ValueError("고정 간격과 경계 보정 조건에서 생성 가능한 해칭 획이 없습니다.")
    return strokes, {
        "spacing_mm": round(spacing_mm, 6),
        "spacing_px": round(spacing_px, 6),
        "effective_groove_width_mm": round(EFFECTIVE_GROOVE_WIDTH_MM, 6),
        "stepover_ratio": round(HATCH_STEPOVER_RATIO, 6),
        "boundary_inset_mm": round(boundary_inset_mm, 6),
        "minimum_stroke_length_mm": round(min_length_mm, 6),
        "removed_short_strokes": removed_short,
        "direction": "image_left_to_right",
        "fixed_test_only": True,
    }


def strokes_to_svg(strokes, width_px, height_px, source_name):
    body = "\n  ".join(
        f'<path fill="none" stroke="#000" stroke-width="1" d="M {a[0]:.3f},{a[1]:.3f} L {b[0]:.3f},{b[1]:.3f}" />'
        for a, b in strokes
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!-- image_to_hatch.py 자동 생성: {source_name}; '
        f'고정 간격 {HATCH_SPACING_MM:.3f}mm; SIMULATION/test_only -->\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {width_px} {height_px}">\n  {body}\n</svg>\n'
    )


def validate_hatch(strokes, safe_mask):
    """생성된 끝점의 방향·마스크 포함 관계를 검사한다."""
    errors = []
    for index, stroke in enumerate(strokes):
        if len(stroke) != 2 or stroke[0][0] > stroke[-1][0]:
            errors.append(f"stroke {index}: 단방향 조건 위반")
            continue
        for x, y in stroke:
            ix, iy = int(round(x)), int(round(y))
            if not (0 <= iy < safe_mask.shape[0] and 0 <= ix < safe_mask.shape[1] and safe_mask[iy, ix]):
                errors.append(f"stroke {index}: 경계 보정 영역 밖 끝점")
                break
    if errors:
        raise ValueError("해칭 검증 실패: " + "; ".join(errors[:4]))


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
    strokes, hatch_stats = generate_scanlines(mask, bbox, scale)
    safe = _safe_mask(mask, BOUNDARY_INSET_MM / scale)
    validate_hatch(strokes, safe)
    svg = strokes_to_svg(strokes, w, h, source_name)
    stats = {
        "mode": "parallel_hatch",
        "source_image": source_name,
        "image_size_px": [w, h],
        "foreground_pixels": int(np.count_nonzero(mask)),
        "source_bbox_px": list(bbox),
        "scale_mm_per_px": round(scale, 9),
        "stroke_count": len(strokes),
        **hatch_stats,
    }
    return svg, strokes, bbox, stats
