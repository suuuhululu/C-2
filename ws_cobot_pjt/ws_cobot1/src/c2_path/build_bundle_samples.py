#!/usr/bin/env python3
"""파일 묶음(bundle) 샘플 생성 — HMI 가져오기 대조용.

`samples/bundles/<이름>/input/`  : HMI가 등록해 넘겨줄 입력 묶음을 흉내낸 것 (이미지·스냅샷·요청·manifest)
`samples/bundles/<이름>/output/` : 그 입력으로 실제 `GeneratePipeline` 을 돌린 결과 묶음 (manifest 포함)

샘플 2종
  heart_ok            : 하트 1개, 윗면 아래 45mm, −Y 면(θ=−90°). 검증 통과 → path·svg·preview·validation.
  heart_seam_rejected : 같은 하트를 이음매(180°)에 놓음. J5 허용 범위 밖이라 검증 실패 → 진단 svg·validation 만.

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


def build(name, theta_deg):
    root = os.path.join(OUT, name)
    if os.path.isdir(root):
        shutil.rmtree(root)
    counter = iter(range(1, 100))
    new = lambda: str(uuid.uuid5(NAMESPACE, f"{name}:{next(counter)}"))  # noqa: E731

    image, profile = heart_png(), hmi_encoded(ppl.matching_test_profile())
    request = {
        "schema_version": wc.PATH_SCHEMA_VERSION,
        "request_id": new(),
        "source_mode": "SIMULATION",
        "asset_id": new(),
        "asset_sha256": sha256_bytes(image),
        "width_mm": 24.0,
        "height_mm": 24.0,
        "offset_u_mm": round(U_OF(theta_deg), 4),
        "offset_v_mm": round(V_CENTER, 4),
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


def main():
    failed = False
    for name, theta in (("heart_ok", -90.0), ("heart_seam_rejected", 180.0)):
        result, errors = build(name, theta)
        print(f"[{name}] success={result['success']} error_code={result['error_code']} "
              f"segments={result['segment_count']} cut={result['cut_length_m'] * 1000:.1f}mm "
              f"| 묶음 검증 {'통과' if not errors else errors}")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
