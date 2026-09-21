#!/usr/bin/env python3
"""파일 묶음(bundle) 샘플 생성 — HMI 가져오기 대조용.

`samples/bundles/<이름>/input/`  : HMI가 등록해 넘겨줄 입력 묶음을 흉내낸 것 (이미지·스냅샷·요청·manifest)
`samples/bundles/<이름>/output/` : 그 입력으로 실제 `GeneratePipeline` 을 돌린 결과 묶음 (manifest 포함)

샘플 6종 (경로 생성 성공과 로봇 실행 가능 여부는 별개다 — 앞의 5개는 모두 생성·검증에 성공한다)
입력 스냅샷은 모두 contract `c2-path-test-profile/2` (height_reference="bottom", v_direction="up") 다.
  heart_ok                           : 하트 1개, 윗면 아래 45mm, −Y 면(θ=−90°). 생성 성공, 잠정 작업 범위 안(WITHIN_LIMITS).
  heart_seam_out_of_limits           : 같은 하트를 이음매(180°)에 놓음. 생성 성공, 각도가 잠정 범위 밖(OUT_OF_LIMITS).
  heart_low_out_of_limits            : 같은 하트를 높이 15mm(바닥 근처)에 놓음. 생성 성공, 높이가 범위(10~140mm) 밖(OUT_OF_LIMITS).
  heart_request_range_out_of_limits  : 하트는 heart_ok 와 같고 **스냅샷의 작업 범위만 [110,140]mm 로 바꿈**. 생성 성공,
                                       요청별 범위가 사전 점검에 쓰이는 걸 보여 준다(OUT_OF_LIMITS).
  heart_custom_cylinder              : **스냅샷의 원통 치수를 바꿈**(반지름 30mm, 높이 120mm, 축 원점 [0.45, 0.01, 0.09], 작업 범위 [10,110]mm).
                                       경로 좌표가 이 스냅샷 원통 위에 놓이는 것을 보여 준다(WITHIN_LIMITS). 상수 값이 아니라 스냅샷 값을 쓴다.
  heart_off_surface                  : 원기둥 높이(150mm) 밖에 놓음. 옆면 위에 없으므로 생성 실패(HEIGHT_OUT_OF_SURFACE) → 진단 svg·validation 만.

주의: 이 ID·해시는 **HMI가 발급한 값이 아니다**. 입력 manifest 의 origin="local_test_sample" 이다.
재실행해도 파일이 바뀌지 않도록 UUID 를 고정 네임스페이스로 만든다(샘플 전용, 실제 실행은 uuid4).
스냅샷 바이트는 HMI 저장소(backend/app/storage.py `encoded`)와 같은 방식(정렬·compact JSON)으로 직렬화했다.
c2_path 는 받은 스냅샷 바이트를 다시 직렬화하지 않고 그대로 해시를 확인한다.

실행: 패키지 루트(c2_path/)에서 `python3 build_bundle_samples.py`
"""
import json
import math
import os
import shutil
import sys
import uuid

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c2_path import bundle, pipeline as ppl, workcell as wc  # noqa: E402
from c2_path.artifacts import sha256_bytes  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "samples", "bundles")
NAMESPACE = uuid.UUID("c2c2c2c2-0000-4000-8000-0000c2b00d1e")
V_CENTER = (wc.HEIGHT_TOTAL_M - 0.045) * 1000.0            # 윗면 아래 45mm
U_OF = wc.u_mm_from_theta_deg


def heart_png() -> bytes:
    """하트 선(굵기 6px) 400x400 흑백 PNG. 결정적이다."""
    image = np.full((400, 400), 255, np.uint8)
    t = np.linspace(0.0, 2.0 * math.pi, 400)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    points = np.stack([200 + x * 10.5, 190 - y * 10.5], axis=1).astype(np.int32)
    cv2.polylines(image, [points], True, 0, 6, cv2.LINE_AA)
    okay, encoded = cv2.imencode(".png", image)
    assert okay
    return encoded.tobytes()


def hmi_encoded(value) -> bytes:
    """backend/app/storage.py 의 encoded() 와 같은 직렬화."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


CUSTOM_CYLINDER = {"radius_mm": 30.0, "height_mm": 120.0, "axis_origin_m": [0.45, 0.01, 0.09],
                   "valid_v_range_mm": [10.0, 110.0], "measurement_id": "sample-0921-custom",
                   "measured_at": "2026-09-21T10:00:00+09:00"}


def build(name, theta_deg, v_mm=None, valid_v_range_mm=None, profile_kwargs=None):
    root = os.path.join(OUT, name)
    if os.path.isdir(root):
        shutil.rmtree(root)
    counter = iter(range(1, 100))
    new = lambda: str(uuid.uuid5(NAMESPACE, f"{name}:{next(counter)}"))  # noqa: E731

    image = heart_png()
    kwargs = dict(profile_kwargs or {})
    if valid_v_range_mm is not None:
        kwargs["valid_v_range_mm"] = valid_v_range_mm
    profile_value = ppl.matching_test_profile_v2(**kwargs)
    profile = hmi_encoded(profile_value)
    with wc.using_surface(ppl.profile_surface(profile_value)):     # u 는 이 스냅샷 반지름 기준이다
        offset_u = round(U_OF(theta_deg), 4)
    height_mm = profile_value["surface"]["height_mm"]
    default_v = V_CENTER if profile_kwargs is None else height_mm - 45.0     # 윗면 아래 45mm
    request = {
        "schema_version": wc.PATH_SCHEMA_VERSION,
        "request_id": new(),
        "source_mode": "SIMULATION",
        "asset_id": new(),
        "asset_sha256": sha256_bytes(image),
        "width_mm": 24.0,
        "height_mm": 24.0,
        "offset_u_mm": offset_u,
        "offset_v_mm": round(default_v if v_mm is None else v_mm, 4),
        "rotation_deg": 0.0,
        "conversion_preset": "raster_centerline_bezier",
        "tool_id": wc.TOOL_ID,
        "profile_snapshot_id": new(),
        "profile_sha256": sha256_bytes(profile),
    }
    input_dir, output_dir = os.path.join(root, "input"), os.path.join(root, "output")
    bundle.write_input_bundle(
        input_dir, request=request, image=image, image_name="heart.png", image_mime="image/png",
        profile_bytes=profile, profile_name="simulation-profile.json", origin="local_test_sample",
    )
    ppl.new_id = new                                       # 샘플 전용: 산출물 UUID 를 고정한다
    result = bundle.run_bundle(input_dir, output_dir)
    errors = bundle.verify_bundle(input_dir) + bundle.verify_bundle(output_dir)
    return result, errors


SAMPLES = (
    ("heart_ok", -90.0, None),
    ("heart_seam_out_of_limits", 180.0, None),
    ("heart_low_out_of_limits", -90.0, 15.0),
    ("heart_request_range_out_of_limits", -90.0, None, [110.0, 140.0]),
    ("heart_custom_cylinder", -90.0, None, None, CUSTOM_CYLINDER),
    ("heart_off_surface", -90.0, 200.0),
)


def main():
    failed = False
    for name, theta, v_mm, *extra in SAMPLES:
        result, errors = build(name, theta, v_mm, *extra)
        print(f"[{name}] success={result['success']} error_code={result['error_code']} "
              f"segments={result['segment_count']} cut={result['cut_length_m'] * 1000:.1f}mm "
              f"| 묶음 검증 {'통과' if not errors else errors}")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
