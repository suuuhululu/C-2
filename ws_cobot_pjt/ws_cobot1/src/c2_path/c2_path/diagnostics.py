"""공정 IK/J6 실패 구간을 경로 생성 당시의 이미지 배치에 연결한다.

공정의 판정이나 관절 한계는 변경하지 않는다. 저장된 경로와 실패 결과만 읽는다.
"""
from __future__ import annotations


def placement_for_joint_failure(path, preview, observed_state):
    """실패 segment의 도안 배치·UV 범위를 반환한다. 불일치하면 실패한다."""
    if not isinstance(observed_state, dict):
        raise ValueError("공정 실패 관측값이 필요합니다.")
    worst = observed_state.get("worst")
    detail = worst if isinstance(worst, dict) else observed_state
    segment_id = detail.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id:
        raise ValueError("실패 segment_id가 필요합니다.")
    if (path.get("path_id") != preview.get("path_id")
            or path.get("path_version") != preview.get("path_version")
            or path.get("test_only") != preview.get("test_only")
            or path.get("source_mode") != preview.get("source_mode")):
        raise ValueError("경로와 미리보기의 식별자 또는 실행 모드가 다릅니다.")
    path_segment = next((s for s in path.get("segments", [])
                         if s.get("segment_id") == segment_id), None)
    shown = next((s for s in preview.get("segments", [])
                  if s.get("segment_id") == segment_id), None)
    if path_segment is None or shown is None or shown.get("kind") != path_segment.get("kind"):
        raise ValueError("실패 segment를 동일한 미리보기에서 찾지 못했습니다.")
    conversion = path.get("config", {}).get("conversion", {})
    placement = conversion.get("placement")
    if not isinstance(placement, dict):
        raise ValueError("경로에 원본 이미지 배치 설정이 없습니다.")
    uv = shown.get("points_uv_mm") or []
    return {
        "path_id": path["path_id"],
        "path_version": path["path_version"],
        "segment_id": segment_id,
        "stroke_id": path_segment.get("stroke_id"),
        "kind": path_segment["kind"],
        "point_index": detail.get("index"),
        "placement": dict(placement),
        "segment_u_range_mm": [min(p[0] for p in uv), max(p[0] for p in uv)] if uv else None,
        "segment_v_range_mm": [min(p[1] for p in uv), max(p[1] for p in uv)] if uv else None,
    }
