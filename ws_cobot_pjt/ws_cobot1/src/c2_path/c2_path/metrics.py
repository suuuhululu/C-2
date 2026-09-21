#!/usr/bin/env python3
"""metrics.py — 9/21 오후 일정 "정량 평가" 지표.

기존 알고리즘(image_to_svg/extract_2d/optimize_2d/map_3d/generate_path/validate_path)은
건드리지 않고, 각 단계가 이미 만드는 stats·검증 결과에서 정량 지표를 뽑아 모은다.
`pipeline.GeneratePipeline.run()`이 만드는 `c2-path-validation(.json)`/`c2-path-validation-failed.json`
(= validate_path.validate() 결과 + stats.convert/extract_2d/optimize_2d/map_3d/build)을 입력으로 받는다.

일정에 나온 항목 중 아래는 여기서 다루지 않는다 (김세은/joint_check.py 담당):
  - 실제 두산 IK를 이용한 도달 가능성 확인
  - 경로별 J5/J6 최소 여유 계산
  - IK 성공 waypoint 비율 / 최소 관절 여유
"""
from __future__ import annotations


def error_code(message) -> str:
    """validate_path 오류 메시지 'CODE: 상세' 에서 CODE 만 뽑는다.

    3D 매핑 단계 실패 보고서의 오류는 문자열이 아니라 {"reason_code": ...} 객체다."""
    if isinstance(message, dict):
        return str(message.get("reason_code") or message.get("code") or "UNKNOWN")
    return str(message).split(":", 1)[0].strip()


def raster_to_vector_error(convert_stats: dict | None) -> dict:
    """이미지→SVG 변환(image_to_svg.convert) 단계의 실측 형상 오차(px).

    `convert_stats` 가 없으면(예: 손으로 만든 SVG를 직접 쓴 샘플) None 을 채운다 —
    래스터 입력이 없던 샘플에 오차를 지어내지 않는다.
    """
    if not convert_stats:
        return {"measured_max_error_px": None, "measured_mean_error_px": None,
                "allowed_fit_error_px": None, "note": "raster 입력 없음(손으로 만든 SVG)"}
    return {
        "measured_max_error_px": convert_stats.get("measured_max_error_px"),
        "measured_mean_error_px": convert_stats.get("measured_mean_error_px"),
        "allowed_fit_error_px": convert_stats.get("fit_error_px"),
        "note": ("실측치는 최종 베지어 곡선을 촘촘히 샘플링해 원본 점과의 최단거리로 재는 "
                 "사후 근사값이라, Schneider 피팅 내부의 허용 오차(같은 값)와 약간 다를 수 있다. "
                 "허용치를 살짝 넘는 정도는 측정 방식 차이지 회귀가 아니다."),
    }


def travel_reduction_pct(optimize_stats: dict) -> float | None:
    """2-opt 최적화 전후 비가공(TRAVEL) 이동 거리 감소율(%). (2D, mm 기준)"""
    nn = (optimize_stats or {}).get("travel_mm_nearest_neighbor")
    opt = (optimize_stats or {}).get("travel_mm_after_2opt")
    if not nn:
        return None
    return round((nn - opt) / nn * 100.0, 2)


def stroke_preservation_ratio(extract_stats: dict, optimize_stats: dict) -> float | None:
    """추출된 획 수 대비 최적화 단계까지 남은 획 수 비율.

    현재 파이프라인은 획을 지우지 않으므로 1.0 이 정상이다. 1.0 미만이면 어느
    단계에서 획이 소실됐다는 뜻이라 회귀 신호로 쓸 수 있다.
    """
    extracted = (extract_stats or {}).get("stroke_count")
    optimized = (optimize_stats or {}).get("stroke_count")
    if not extracted:
        return None
    return round(optimized / extracted, 4)


def split_relations(map_stats: dict, mapped_strokes: list | None = None) -> dict:
    """이음매·각도 분할로 생긴 조각 관계 요약 (`map_3d.py`의 `split_from_stroke_id` 필드 기준)."""
    out = {
        "strokes_split_at_seam": (map_stats or {}).get("strokes_split_at_seam", 0),
        "strokes_split_by_arc_limit": (map_stats or {}).get("strokes_split_by_arc_limit", 0),
    }
    if mapped_strokes:
        out["split_pieces"] = sum(1 for s in mapped_strokes if "split_from_stroke_id" in s)
    return out


def violations(validation_report: dict) -> dict:
    """errors 목록에서 오류 코드별 건수를 센다 (검증 실패 사유별 건수)."""
    counts: dict[str, int] = {}
    for e in (validation_report or {}).get("errors", []):
        code = error_code(e)
        counts[code] = counts.get(code, 0) + 1
    return counts


def sample_report(name: str, validation_report: dict) -> dict:
    """샘플/번들 산출물 하나(`c2-path-validation(.json)`류)의 정량 평가."""
    stats = (validation_report or {}).get("stats", {})
    build = stats.get("build", {})
    return {
        "name": name,
        "passed": validation_report.get("passed"),
        "raster_to_vector_error": raster_to_vector_error(stats.get("convert")),
        "stroke_preservation_ratio": stroke_preservation_ratio(stats.get("extract_2d"), stats.get("optimize_2d")),
        "travel_reduction_pct_2opt": travel_reduction_pct(stats.get("optimize_2d")),
        "split_relations": split_relations(stats.get("map_3d")),
        "cut_length_m": build.get("cut_length_m"),
        "travel_length_m": build.get("travel_length_m"),
        "segment_count": build.get("segment_count"),
        "failure_reasons": violations(validation_report),
        # 9/21: 생성 성공과 로봇 실행 가능 여부는 별개다. 사전 점검 결과는 생성 실패 사유(failure_reasons)에 넣지 않는다.
        "execution_precheck": (validation_report.get("execution_readiness") or {}).get("precheck"),
    }


def suite_report(samples: list[dict]) -> dict:
    """여러 샘플의 실패 사유·분할 위반을 합산한 전체 요약."""
    total_failures: dict[str, int] = {}
    for s in samples:
        for code, n in s.get("failure_reasons", {}).items():
            total_failures[code] = total_failures.get(code, 0) + n
    return {
        "sample_count": len(samples),
        "samples": samples,
        "failure_reasons_total": total_failures,
        "seam_crossed_total": total_failures.get("SEAM_CROSSED", 0),
        # 각도 범위는 9/21 부터 생성 검증이 아니라 실행 사전 점검이다 (이 값은 이제 항상 0). 아래 두 값을 본다.
        "angle_out_of_range_total": total_failures.get("ANGLE_OUT_OF_RANGE", 0),
        "generated_sample_count": sum(1 for s in samples if s.get("passed")),
        "execution_precheck_out_of_limits_sample_count": sum(
            1 for s in samples if s.get("execution_precheck") == "OUT_OF_LIMITS"),
        "cylinder_penetration_total": total_failures.get("CYLINDER_PENETRATION", 0),
    }
