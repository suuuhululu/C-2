#!/usr/bin/env python3
"""하트 샘플 경로 3종 생성 — 2026-09-19 확정 알고리즘 조합 적용.

  heart        : 하트 1개. 시율님 9/18 실기 조건(폭 24mm, 윗면 아래 45mm, -Y 면).
  heart_pair   : 하트 2개를 180도 떨어뜨림. 획 정렬·오프셋 원통 TRAVEL 검증용.
                 (직선 현으로 이으면 원통을 뚫는 조건)
  heart_seam   : 하트를 이음매(180도, −X 면 = 로봇 쪽) 위에 놓음. 이음매 분할 검증용.
                 J5 위험 구역이라 실기 실행 대상이 아니다 (분할 로직 확인용).

각도 기준 (9/20): 0° = base +X(로봇 반대편), 반시계 양수, 이음매 = ±180°. u=0 은 0° 에 놓인다.

2026-09-20: path.json waypoint 를 로봇팀 형식 [x,y,z,qx,qy,qz,qw], schema_version 2 로 변경.
path_sha256 은 path.json 을 저장한 뒤 그 바이트로 계산해 result.json 에만 넣는다
(파일이 자기 해시를 담지 않는다 — 권장안 4절).
실행: 패키지 루트(c2_path/)에서 `python3 build_samples.py`
"""
import json, math, os, hashlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c2_path import extract_2d, optimize_2d, map_3d, generate_path, validate_path, workcell as wc
from c2_path import pipeline as ppl
from c2_path.artifacts import json_bytes as _json_bytes, sha256_bytes as _sha256_bytes

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "samples", "heart.svg"), "rb") as f:
    SVG_BYTES = f.read()
SVG = SVG_BYTES.decode("utf-8")
ASSET_SHA = hashlib.sha256(SVG_BYTES).hexdigest()     # 파일 바이트 기준
V_CENTER = (wc.HEIGHT_TOTAL_M - 0.045) * 1000.0     # 윗면 아래 45mm
U_OF = lambda deg: wc.u_mm_from_theta_deg(deg)       # 원하는 도안 중심 각도 -> offset_u(mm)

# 프로필 스냅샷: pipeline.matching_test_profile() 로 만든 실제 test_only 스냅샷을
# 한 번만 만들어서 모든 샘플이 같은 ID·해시를 공유한다 ("0" * 64 자리표시값을 쓰지 않는다).
PROFILE_ID = "snap-candle-0919"
PROFILE = ppl.matching_test_profile()
PROFILE_BYTES = _json_bytes(PROFILE)
PROFILE_SHA = _sha256_bytes(PROFILE_BYTES)
with open(os.path.join(BASE, "samples", "profile_snapshot.json"), "wb") as f:
    f.write(PROFILE_BYTES)


def build(name, placements, note):
    out = os.path.join(BASE, "samples", name)
    os.makedirs(out, exist_ok=True)
    strokes, st_ex = [], None
    for u, v in placements:
        s, st = extract_2d.extract(SVG, 24.0, 24.0, u, v)
        strokes += s
        st_ex = st
    st_ex = dict(st_ex); st_ex["stroke_count"] = len(strokes)
    st_ex["point_count"] = sum(len(s) for s in strokes)

    ordered, st_opt = optimize_2d.optimize(strokes)
    mapped, failures, st_map = map_3d.map_strokes(ordered)
    path, st_gen = generate_path.build(mapped, f"path-{name}-0001", 1,
                                       f"asset-{name}-0001", ASSET_SHA,
                                       PROFILE_ID, PROFILE_SHA)
    rep = validate_path.validate(path)
    path["validation"] = {"report_id": f"val-{name}-0001", "passed": rep["passed"],
                          "checks": rep["checks"], "not_checked": rep["not_checked"]}
    path["note"] = note

    req = {"schema_version": wc.PATH_SCHEMA_VERSION, "request_id": f"req-{name}-0001", "source_mode": "SIMULATION",
           "asset_id": f"asset-{name}-0001", "asset_sha256": ASSET_SHA,
           "width_mm": 24.0, "height_mm": 24.0,
           "offset_u_mm": round(placements[0][0], 4), "offset_v_mm": round(placements[0][1], 4),
           "rotation_deg": 0.0, "conversion_preset": "raster_centerline_bezier",
           "tool_id": wc.TOOL_ID, "profile_snapshot_id": PROFILE_ID,
           "profile_sha256": PROFILE_SHA}
    if len(placements) > 1:
        req["note"] = f"샘플 편의상 도안 {len(placements)}개를 한 경로에 넣었다. 실제 Goal 은 배치 1개다."
    fb = [{"stage": s, "progress": round((i + 1) / 6, 3)} for i, s in enumerate(
        ["CONVERTING", "EXTRACTING_2D", "OPTIMIZING_2D", "MAPPING_3D", "BUILDING_PATH", "VALIDATING"])]
    res = {"success": rep["passed"], "error_code": "NONE" if rep["passed"] else "VALIDATION_FAILED",
           "message": note, "path_id": path["path_id"] if rep["passed"] else "",
           "path_version": 1 if rep["passed"] else 0,
           "svg_asset_id": f"svg-{name}-0001", "preview_asset_id": f"preview-{name}-0001",
           "segment_count": st_gen["segment_count"], "cut_length_m": st_gen["cut_length_m"],
           "validation_passed": rep["passed"], "validation_report_id": f"val-{name}-0001"}

    def dump(fn, obj):
        with open(os.path.join(out, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2); f.write("\n")

    for fn, obj in [("request.json", req), ("feedback.json", fb), ("path.json", path),
                    ("validation_report.json", rep)]:
        dump(fn, obj)
    with open(os.path.join(out, "path.json"), "rb") as f:
        res["path_sha256"] = hashlib.sha256(f.read()).hexdigest() if rep["passed"] else ""
    dump("result.json", res)
    return {"name": name, "extract": st_ex, "optimize": st_opt, "map_3d": st_map,
            "generate": st_gen, "passed": rep["passed"], "errors": rep["errors"][:4]}


results = [
    build("heart", [(U_OF(-90), V_CENTER)],
          "하트 1개. 시율님 9/18 드릴 하트와 같은 조건(폭 24mm, 윗면 아래 45mm, -Y 면)."),
    build("heart_pair", [(U_OF(-90), V_CENTER), (U_OF(90), V_CENTER)],
          "하트 2개를 180도 떨어뜨렸다. 획 정렬과 오프셋 원통 TRAVEL 검증용."),
    build("heart_seam", [(U_OF(180), V_CENTER)],
          "하트를 이음매(180도, −X 면 = 로봇 쪽) 위에 놓아 이음매 분할을 재현한다. J5 위험 구역 — 실기 금지, 분할 확인용."),
]
for r in results:
    g, m = r["generate"], r["map_3d"]
    print(f"[{r['name']}] 획 {m['mapped_strokes']}개 (분할: 이음매 {m['strokes_split_at_seam']} / 각도 {m['strokes_split_by_arc_limit']})"
          f" | segment {g['segment_count']} | CUT {g['cut_length_m']*1000:.1f}mm"
          f" | TRAVEL {g['travel_length_m']*1000:.1f}mm | 검증 {'통과' if r['passed'] else '실패 '+str(r['errors'])}")
