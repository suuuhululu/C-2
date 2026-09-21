"""c2_path 실제 계산 샘플(heart/heart_pair/heart_seam)을 HMI 미리보기 계약으로 변환한다.

REVIEW.md "권장 부분 통합 순서 · 1차: 샘플 3종을 HMI에 표시"의 최소 구현이다.
- 원본 request/path/result/validation_report.json 은 그대로 두고 읽기만 한다 (등록·해시 재발급 없음).
- 이 모듈이 만드는 값은 `path_versions`/`assets` 테이블에 등록하지 않는다 — 즉 이 값으로 `/runs`
  실행 요청을 보내면 `store.path()` 조회가 실패해 자연히 거절된다(REVIEW.md 4·1차 절 요구사항:
  "이 모드에서는 서버가 시작 요청을 거절").
- c2_path 패키지 중 `workcell.py`만 가져온다 (math만 사용, cv2/numpy 등 무거운 의존성 없음).
  `image_to_svg`/`extract_2d` 등 나머지 계산 모듈은 2차(실제 PNG 업로드 계산) 단계에서 필요하다.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # backend/app/이 파일 -> ws_cobot_pjt -> C-2
C2_PATH_PKG_DIR = ROOT / "ws_cobot_pjt" / "ws_cobot1" / "src" / "c2_path"
SAMPLES_DIR = C2_PATH_PKG_DIR / "samples"

if str(C2_PATH_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(C2_PATH_PKG_DIR))

from c2_path import workcell as wc  # noqa: E402  (경로 계산 상수만 사용)

CONTRACT = "c2-path-sample/1"

SAMPLE_NAMES = ("heart", "heart_pair", "heart_seam")

SAMPLE_LABELS = {
    "heart": "하트 1개",
    "heart_pair": "하트 2개 (180° 간격)",
    "heart_seam": "이음매(180°) 위 배치",
}
SAMPLE_DESCRIPTIONS = {
    "heart": "시율님 9/18 실기 조건과 동일 배치(폭 24mm, 윗면 아래 45mm, −Y 면). 실제 c2_path 계산 결과다.",
    "heart_pair": "두 획 정렬과 오프셋 원통 TRAVEL 검증용. 실제 c2_path 계산 결과다.",
    "heart_seam": (
        "이음매(로봇 쪽 J5 위험 구역) 위에 놓아 분할 로직 확인용으로 만든 샘플. "
        "실기 대상이 아니다. J5 안전 범위(REACHABLE_ANGLE_DEG) 반영 이후 "
        "ANGLE_OUT_OF_RANGE로 검증에 실패하도록 바뀌었다 — 버그가 아니라 의도된 동작이다."
    ),
}


def _sample_dir(name):
    if name not in SAMPLE_NAMES:
        raise KeyError(name)
    d = SAMPLES_DIR / name
    if not d.is_dir():
        raise KeyError(name)
    return d


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sample_file_bytes(name, filename):
    """샘플 폴더 안의 파일(path.json/request.json/validation_report.json)을 원문 그대로 반환한다.

    filename은 화이트리스트로만 허용해 경로 조작을 막는다.
    """
    allowed = {"path.json", "request.json", "result.json", "validation_report.json", "feedback.json"}
    if filename not in allowed:
        raise KeyError(filename)
    d = _sample_dir(name)
    with open(d / filename, "rb") as f:
        return f.read()


def sample_svg_bytes():
    """세 샘플이 공유하는 원본 도안(heart.svg)을 반환한다. 실제 업로드 이미지가 아니라
    c2_path 샘플 생성에 쓰인 고정 SVG다 — '원본 비교' 토글에 그대로 쓸 수 있다."""
    with open(SAMPLES_DIR / "heart.svg", "rb") as f:
        return f.read()


def _theta_and_height(waypoint):
    x, y, z = waypoint[0], waypoint[1], waypoint[2]
    local_x = x - wc.AXIS_ORIGIN_XY_M[0]
    local_y = y - wc.AXIS_ORIGIN_XY_M[1]
    h_m = z - wc.AXIS_ORIGIN_Z_M
    theta_deg = math.degrees(math.atan2(local_y, local_x))
    return local_x, local_y, h_m, theta_deg


def _unwrap_deg(thetas_deg):
    """atan2 결과(-180°,180°]를 스트로크 안에서 이어지는 실제 회전각으로 펼친다.

    heart_seam 샘플의 TRAVEL처럼 이음매(±180°) 부근을 지나는 구간은, 점마다 atan2를
    독립적으로 계산하면 -180°/+180° 경계에서 인위적인 점프(전개면 폭 전체를 가로지르는
    엉뚱한 선)가 생긴다. 이전 점과의 차이를 ±360°로 보정해 실제 이동 방향을 유지한다.
    points_m(3D)은 atan2 값과 무관하므로 영향 없고, points_uv_mm(2D 전개면)만 바뀐다.
    """
    if not thetas_deg:
        return thetas_deg
    out = [thetas_deg[0]]
    for t in thetas_deg[1:]:
        prev = out[-1]
        delta = t - prev
        delta -= 360.0 * round(delta / 360.0)
        out.append(prev + delta)
    return out


def _strokes(path_json):
    strokes = []
    for seg in path_json["segments"]:
        raw = [_theta_and_height(wpt) for wpt in seg["waypoints"]]
        thetas = _unwrap_deg([r[3] for r in raw])
        points_uv_mm, points_m = [], []
        for (local_x, local_y, h_m, _theta_raw), theta_deg in zip(raw, thetas):
            points_uv_mm.append([round(wc.u_mm_from_theta_deg(theta_deg), 4), round(h_m * 1000.0, 4)])
            points_m.append([round(local_x, 6), round(local_y, 6), round(h_m, 6)])
        strokes.append({
            "stroke_id": seg.get("stroke_id") or seg["segment_id"],
            "segment_id": seg["segment_id"],
            "kind": seg["kind"],
            "points_uv_mm": points_uv_mm,
            "points_m": points_m,
            "connect_to_next": False,
        })
    return strokes


def list_samples():
    """세 샘플의 요약(선택 목록용). 실행 등록 없이 읽기만 한다."""
    out = []
    for name in SAMPLE_NAMES:
        d = _sample_dir(name)
        path_json = _read_json(d / "path.json")
        result = _read_json(d / "result.json")
        passed = bool(path_json.get("validation", {}).get("passed"))
        out.append({
            "name": name,
            "label": SAMPLE_LABELS[name],
            "description": SAMPLE_DESCRIPTIONS[name],
            "validation_passed": passed,
            "segment_count": result.get("segment_count"),
            "cut_length_m": result.get("cut_length_m"),
        })
    return out


def load_sample(name):
    """PathResult(프런트 api.ts)와 같은 모양의 딕셔너리를 만든다.

    주의: 이 값은 DB에 등록되지 않는다. `contract`가 `mock-preview/1`이 아니라 `c2-path-sample/1`이라
    Monitor.tsx의 실행(runs) 흐름과 절대 섞이지 않는다 — 화면에 보여주는 용도로만 쓴다.
    """
    d = _sample_dir(name)
    path_json = _read_json(d / "path.json")
    request_json = _read_json(d / "request.json")
    result_json = _read_json(d / "result.json")
    validation = path_json.get("validation", {})
    errors = []
    if not validation.get("passed", True):
        report = _read_json(d / "validation_report.json")
        errors = report.get("errors", [])

    return {
        "path_id": path_json["path_id"],
        "path_version": path_json["path_version"],
        "path_sha256": result_json.get("path_sha256", ""),
        "svg_url": f"/api/operator/c2-path-samples/{name}/asset",
        "path_url": f"/api/operator/c2-path-samples/{name}/path.json",
        "validation_url": f"/api/operator/c2-path-samples/{name}/validation_report.json",
        "validation_passed": bool(validation.get("passed")),
        "validation_errors": errors,
        "segment_count": result_json.get("segment_count"),
        "cut_length_m": result_json.get("cut_length_m"),
        "input": {
            "width_mm": request_json["width_mm"],
            "height_mm": request_json["height_mm"],
            "offset_u_mm": request_json["offset_u_mm"],
            "offset_v_mm": request_json["offset_v_mm"],
            "rotation_deg": request_json["rotation_deg"],
            "asset_id": request_json["asset_id"],
        },
        "preview": {
            "contract": CONTRACT,
            "note": (
                f"c2_path 실제 계산 샘플({name}) · 첨부 이미지의 변환 결과가 아니라 "
                "고정 도안(heart.svg)으로 만든 참고용 미리보기입니다."
            ),
            "strokes": _strokes(path_json),
            "profile_snapshot_id": path_json.get("profile_snapshot_id", ""),
            "path_id": path_json["path_id"],
            "path_version": path_json["path_version"],
            "path_sha256": result_json.get("path_sha256", ""),
        },
    }
