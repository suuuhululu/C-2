"""Synthetic Observed fixtures aligned with PR #6; diagnostic envelope is proposed."""
from copy import deepcopy
import json


TEMPORARY = {
    "tracked_blocks": "TEST ONLY: field name and provenance/reason layout pending agreement",
    "observed_at": "TEST ONLY: UTC bundle-start timestamp for diagnostics only, not freshness selection; exact field pending agreement",
    "observation_seq": "EXAMPLE POLICY: reset to 0 per new check, increment by 1 at bundle start; not a mandatory common counter policy",
    "other_fields": "separate vision_diagnostics, views, calibration, quality and delivery_board layouts are proposals",
    "fixture_values": "all geometry, timestamps, scores and IDs are synthetic; not measured",
}


def block(color="yellow", layer=1):
    return {"brick_type": "2x2x1", "color": color, "x": 4, "y": 6,
            "layer": layer, "orientation_deg": 0}


def region(x0=0, y0=0, x1=24, y1=24, layer=1):
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0, "layer": layer}


def examples(check_id, observation_seq):
    """Caller supplies Backend check ID and bundle-start sequence; no ID generation."""
    if not isinstance(check_id, str) or not check_id:
        raise ValueError("nonempty Backend-issued check_id required")
    if type(observation_seq) is not int or observation_seq < 0:
        raise ValueError("nonnegative bundle-start observation_seq required")
    base = {"check_id": check_id, "observation_seq": observation_seq,
            "status": "OK", "visible_blocks": [], "verified_regions": [], "reason": None}
    diagnostics = {"check_id": check_id, "observation_seq": observation_seq,
                   "observed_at": "2026-10-06T00:00:00Z",
                   "view_ids": ["V0", "D1", "D2", "D3", "D4"],
                   "calibration_id": "synthetic-calibration", "tracked_blocks": [],
                   "unverified_regions": [],
                   "quality": {"basis": "synthetic_fixture", "reason": "no_camera_measurement"}}
    cases = []

    def add(name, payload, expected, explanation, details=None):
        cases.append({"case": name, "example_only": True,
                      "temporary_expressions": deepcopy(TEMPORARY),
                      "backend_test_context": {"expected_blocks": expected,
                                               "review_expectation": explanation},
                      "vision_result": payload,
                      "vision_diagnostics": deepcopy(diagnostics if details is None else details)})

    result = deepcopy(base)
    result["visible_blocks"] = [block()]
    result["verified_regions"] = [region()]
    add("normal_match", result, [block()],
        "Backend compares observed placement with Expected; this fixture covers only layer 1")

    result = deepcopy(base)
    result["visible_blocks"] = [block("blue")]
    result["verified_regions"] = [region()]
    add("mismatch", result, [block()],
        "Backend detects color difference; Vision still returns the actual blue block")

    result = deepcopy(base)
    result["verified_regions"] = [region(4, 6, 6, 8)]
    add("verified_empty", result, [block()],
        "Target footprint is checked empty: Backend detects missing placement, not waiting or unreadable")

    result = deepcopy(base)
    result["status"] = "UNOBSERVABLE"
    result["reason"] = "target_occluded_or_insufficient_depth"
    result["verified_regions"] = [region(0, 0, 4, 24)]
    details = deepcopy(diagnostics)
    details["tracked_blocks"] = [{"placement": block(),
                                  "basis": "previous_backend_accepted_state",
                                  "reason": "lower_layer_occluded"}]
    details["unverified_regions"] = [
        {"reason": "lower_layer_occluded", "affected_region": region(4, 6, 6, 8)},
        {"reason": "insufficient_depth", "affected_region": region(4, 6, 6, 8, layer=2)},
        {"reason": "outside_view_or_unverified", "affected_region": region(12, 0, 24, 24)},
    ]
    add("occlusion_or_low_quality", result, [block(), block("blue", 2)],
        "Current target is unreadable: Backend keeps records and holds completion/delivery", details)

    result = deepcopy(base)
    result["visible_blocks"] = [block()]
    result["verified_regions"] = [region(4, 6, 6, 8)]
    details = deepcopy(diagnostics)
    details["delivery_board"] = {"state": "UNOBSERVABLE", "reason": "camera_view_occluded"}
    add("delivery_unobservable", result, [block()],
        "Assembly is readable independently; delivery board is unreadable so Backend holds next delivery", details)
    return cases


def lower_layer_occluded_example(check_id, observation_seq):
    """Supplement to the fifth-category set: only previous lower layer is hidden."""
    case = deepcopy(examples(check_id, observation_seq)[3])
    case["case"] = "lower_layer_only_occluded"
    case["vision_result"].update(status="OK", reason=None,
                                  visible_blocks=[block("blue", 2)],
                                  verified_regions=[region(4, 6, 6, 8, layer=2)])
    case["vision_diagnostics"]["unverified_regions"] = [
        {"reason": "lower_layer_occluded", "affected_region": region(4, 6, 6, 8)}]
    case["backend_test_context"]["review_expectation"] = (
        "Current target is readable; keep accepted lower layer, its occlusion alone does not block comparison")
    return case


def deliver_example(example, callback):
    """Pass only Vision data. Review notes/Expected never enter the callback."""
    payload = deepcopy(example["vision_result"])
    json.dumps(payload, allow_nan=False)
    return callback(payload)


def sequence_examples():
    """Synthetic start/arrival trace; does not implement a runtime counter or Backend gate."""
    bundles = []
    for check, seq, at in (("check-A", 0, "2026-10-06T00:00:00Z"),
                           ("check-A", 1, "2026-10-06T00:00:01Z"),
                           ("check-B", 0, "2026-10-06T00:00:02Z"),
                           ("check-B", 1, "2026-10-06T00:00:03Z")):
        bundle = examples(check, seq)[0]
        bundle["vision_diagnostics"]["observed_at"] = at
        bundles.append(bundle)
    return {"case": "check_change_sequence", "example_only": True,
            "policy": "check-local reset to 0; increment at bundle start",
            "bundles_in_start_order": bundles,
            "arrival_order": [1, 2, 0, 3],
            "backend_review": "A is closed before B opens: late A result keeps A/0 and is not used for progress; timestamps are diagnostic only"}


def main():
    cases = examples("backend-issued-test-check", 0)
    cases.append(lower_layer_occluded_example("backend-issued-test-check", 0))
    cases.append(sequence_examples())
    for example in cases:
        print(json.dumps(example, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
