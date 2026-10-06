import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "callback_examples", Path(__file__).parents[1] / "callback_examples.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_exported_json_files_match_sources_and_keep_review_metadata():
    directory = Path(__file__).parents[1] / "fixtures"
    cases = module.examples("example-check-replace-with-active-check", 0)
    cases.append(module.lower_layer_occluded_example("example-check-replace-with-active-check", 0))
    assert len(list(directory.glob("*.json"))) == 13
    for case in cases:
        observed = json.loads((directory / (case["case"] + ".observed.json")).read_text())
        details = json.loads((directory / (case["case"] + ".diagnostics.json")).read_text())
        assert observed == case["vision_result"]
        assert details["proposed_diagnostics"] == case["vision_diagnostics"]
        assert details["example_only"] is True
        assert details["temporary_expressions"] == case["temporary_expressions"]
        received = []
        module.deliver_example({"vision_result": observed}, received.append)
        assert received == [observed]
    sequence = json.loads((directory / "check_change_sequence.json").read_text())
    assert sequence == module.sequence_examples()


def test_five_cases_keep_ids_and_mark_temporary():
    cases = module.examples("check-from-backend", 7)
    assert len(cases) == 5
    for case in cases:
        received = []
        module.deliver_example(case, received.append)
        assert received[0]["check_id"] == "check-from-backend"
        assert received[0]["observation_seq"] == 7
        assert "backend_test_context" not in received[0]
        assert "expected_blocks" not in received[0]
        assert case["example_only"] and case["temporary_expressions"]
        assert set(received[0]) == {"check_id", "observation_seq", "status",
                                    "visible_blocks", "verified_regions", "reason"}
        details = case["vision_diagnostics"]
        assert details["check_id"] == received[0]["check_id"]
        assert details["observation_seq"] == received[0]["observation_seq"]


def test_mismatch_keeps_real_observation():
    case = module.examples("c", 1)[1]
    assert case["vision_result"]["visible_blocks"][0]["color"] == "blue"
    assert case["backend_test_context"]["expected_blocks"][0]["color"] == "yellow"


def test_empty_is_scoped_and_unobservable_not_empty():
    cases = module.examples("c", 1)
    empty = cases[2]["vision_result"]
    assert empty["visible_blocks"] == []
    assert empty["verified_regions"] == [module.region(4, 6, 6, 8)]
    assert empty["status"] == "OK" and empty["reason"] is None
    blocked = cases[4]["vision_result"]
    assert blocked["status"] == "OK" and blocked["visible_blocks"]
    delivery = cases[4]["vision_diagnostics"]["delivery_board"]
    assert delivery["state"] == "UNOBSERVABLE"
    assert delivery["reason"]


def test_lower_layer_retained_separately():
    case = module.lower_layer_occluded_example("c", 1)
    result = case["vision_result"]
    assert result["visible_blocks"][0]["layer"] == 2
    assert result["status"] == "OK" and result["reason"] is None
    assert case["vision_diagnostics"]["tracked_blocks"][0]["placement"]["layer"] == 1
    assert module.region(4, 6, 6, 8) not in result["verified_regions"]


def test_current_target_unreadable():
    case = module.examples("c", 1)[3]
    observed = case["vision_result"]
    assert observed["status"] == "UNOBSERVABLE" and observed["reason"]
    assert observed["visible_blocks"] == []
    target = module.region(4, 6, 6, 8, layer=2)
    assert target not in observed["verified_regions"]
    assert any(d["reason"] == "insufficient_depth" and d["affected_region"] == target
               for d in case["vision_diagnostics"]["unverified_regions"])


def test_documented_placement_and_region_contract():
    cases = module.examples("c", 0) + [module.lower_layer_occluded_example("c", 0)]
    for case in cases:
        observed = case["vision_result"]
        assert observed["status"] in ("OK", "UNOBSERVABLE")
        if observed["status"] == "OK":
            assert observed["reason"] is None
        placements = observed["visible_blocks"] + case["backend_test_context"]["expected_blocks"]
        placements += [b["placement"] for b in case["vision_diagnostics"]["tracked_blocks"]]
        for b in placements:
            assert set(b) == {"brick_type", "color", "x", "y", "layer", "orientation_deg"}
            assert b["brick_type"] in ("2x2x1", "2x3x1")
            assert b["color"] in ("yellow", "blue")
            assert 0 <= b["x"] <= 23 and 0 <= b["y"] <= 23 and 1 <= b["layer"] <= 4
            assert b["orientation_deg"] == 0 if b["brick_type"] == "2x2x1" else b["orientation_deg"] in (0, 90)
        for r in observed["verified_regions"]:
            assert set(r) == {"x", "y", "width", "height", "layer"}
            assert all(type(v) is int for v in r.values())
            assert 0 <= r["x"] < r["x"] + r["width"] <= 24
            assert 0 <= r["y"] < r["y"] + r["height"] <= 24
            assert 1 <= r["layer"] <= 4


def test_callback_failure_propagates_and_input_is_preserved():
    case = module.examples("c", 1)[0]
    def failure(payload):
        payload["visible_blocks"].clear()
        raise RuntimeError("consumer failed")
    with pytest.raises(RuntimeError, match="consumer failed"):
        module.deliver_example(case, failure)
    assert case["vision_result"]["visible_blocks"]


def test_arrival_order_does_not_reassign_sequence():
    received = []
    later = module.examples("c", 2)[0]
    earlier = module.examples("c", 1)[0]
    module.deliver_example(later, received.append)
    module.deliver_example(earlier, received.append)
    assert [p["observation_seq"] for p in received] == [2, 1]


def test_check_change_resets_example_sequence_and_preserves_late_result():
    trace = module.sequence_examples()
    bundles = trace["bundles_in_start_order"]
    assert [(b["vision_result"]["check_id"], b["vision_result"]["observation_seq"])
            for b in bundles] == [("check-A", 0), ("check-A", 1), ("check-B", 0), ("check-B", 1)]
    received = []
    for index in trace["arrival_order"]:
        module.deliver_example(bundles[index], received.append)
    assert [(p["check_id"], p["observation_seq"]) for p in received] == [
        ("check-A", 1), ("check-B", 0), ("check-A", 0), ("check-B", 1)]


def test_views_share_bundle_identity_and_time_is_diagnostic_only():
    for bundle in module.sequence_examples()["bundles_in_start_order"]:
        observed, diagnostics = bundle["vision_result"], bundle["vision_diagnostics"]
        assert len(diagnostics["view_ids"]) == 5
        assert diagnostics["check_id"] == observed["check_id"]
        assert diagnostics["observation_seq"] == observed["observation_seq"]
        assert "observed_at" not in observed
        original = observed.copy()
        diagnostics["observed_at"] = "2099-01-01T00:00:00Z"
        received = []
        module.deliver_example(bundle, received.append)
        assert received[0] == original


@pytest.mark.parametrize("check,seq", [("", 1), ("c", -1), ("c", True)])
def test_invalid_identifiers(check, seq):
    with pytest.raises(ValueError):
        module.examples(check, seq)
