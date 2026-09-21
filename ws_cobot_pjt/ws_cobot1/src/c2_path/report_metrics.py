#!/usr/bin/env python3
"""report_metrics.py — 9/21 오후 일정 "정량 평가" 산출.

`samples/bundles/*/output/`의 실제 `GeneratePipeline.run()` 결과(c2-path-validation(.json)
/ c2-path-validation-failed.json, stats.convert/extract_2d/optimize_2d/map_3d/build 포함)를
읽어 `c2_path/metrics.py`로 집계하고 `samples/metrics_report.json`에 쓴다.

먼저 `python3 build_bundle_samples.py`로 번들을 만들어 둬야 한다.
실행: 패키지 루트(c2_path/)에서 `python3 report_metrics.py`
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c2_path import metrics  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
BUNDLES = os.path.join(BASE, "samples", "bundles")

# (번들 이름, 출력 폴더 안의 검증 결과 파일)
SOURCES = [
    ("heart_ok", "c2-path-validation.json"),
    ("heart_seam_out_of_limits", "c2-path-validation.json"),
    ("heart_low_out_of_limits", "c2-path-validation.json"),
    ("heart_request_range_out_of_limits", "c2-path-validation.json"),
    ("heart_custom_cylinder", "c2-path-validation.json"),
    ("heart_off_surface", "c2-path-validation-failed.json"),
]


def load(name, filename):
    path = os.path.join(BUNDLES, name, "output", filename)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    samples = []
    for name, filename in SOURCES:
        report = load(name, filename)
        samples.append(metrics.sample_report(name, report))

    suite = metrics.suite_report(samples)
    out_path = os.path.join(BASE, "samples", "metrics_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(suite, f, ensure_ascii=False, indent=2)
        f.write("\n")

    for s in samples:
        rv = s["raster_to_vector_error"]
        err = (f"실측 오차 max {rv['measured_max_error_px']}px / 평균 {rv['measured_mean_error_px']}px"
               if rv["measured_max_error_px"] is not None else "raster 입력 없음")
        print(f"[{s['name']}] passed={s['passed']} | {err} | "
              f"획 보존율 {s['stroke_preservation_ratio']} | TRAVEL 감소율 {s['travel_reduction_pct_2opt']}% | "
              f"CUT {s['cut_length_m']}m TRAVEL {s['travel_length_m']}m | "
              f"실행 사전 점검 {s['execution_precheck'] or '해당 없음(경로 없음)'} | "
              f"실패 사유 {s['failure_reasons'] or '없음'}")
    print(f"\n합계: 이음매 위반 {suite['seam_crossed_total']}건, "
          f"생성 성공 {suite['generated_sample_count']}/{suite['sample_count']}개 중 "
          f"잠정 작업 범위 밖 {suite['execution_precheck_out_of_limits_sample_count']}개, "
          f"원통 관통 {suite['cylinder_penetration_total']}건")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
